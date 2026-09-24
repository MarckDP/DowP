# src/core/tabs/video_tools/video_upscale_engine.py
"""Reescalado de Video con IA -- extrae los fotogramas de un video (ffmpeg),
los reescala TODOS en un solo proceso con el motor NCNN elegido (Waifu2x/SRMD/
Upscayl, ver core/tabs/image_tools/upscale_engine.py::run_upscale con
batch_total), y rearma el video con ffmpeg remuxando el audio original tal
cual. Tres funciones, una por etapa -- las invoca
core/utils/queue_manager.py::QueueWorker._execute_upscale_video, que arma el
peso de progreso entre las tres (0-15% extracción, 15-85% reescalado, 85-100%
rearmado -- mismo peso que usaba DowP1 para esta misma función, ver el
comentario en core/tabs/image_tools/image_converter.py::_apply_ai_upscale).

Fotogramas intermedios: JPG de máxima calidad y sin submuestreo de color por defecto
(ocupan de 5 a 10 veces menos que PNG, y el video de origen ya viene comprimido), o PNG
con canal alfa cuando hay que conservar la transparencia. La salida de los motores
NCNN es siempre PNG. El recorte, el audio y el códec de salida se resuelven igual que
en Mapa de Profundidad, ver core/tabs/video_tools/ia_video_common.py."""
import os
import re
import subprocess
import threading
import time

from PySide6.QtCore import QCoreApplication

from core.logger.logger_manager import logger
from core.setup.ffmpeg_setup import get_ffmpeg_path
from core.tabs.video_tools.ia_video_common import build_video_encode_args, container_of, trim_input_args

# Los motores NCNN escriben siempre PNG (-f png); la extracción, JPG o PNG (ver arriba).
_FRAME_NAME_PATTERN = "frame_%06d.png"
_FRAME_NAME_PATTERN_JPG = "frame_%06d.jpg"
_FRAME_EXTS = (".png", ".jpg")

_time_regex = re.compile(r"time=\s*(\d+):(\d+):(\d+\.\d+|\d+)")


def _startupinfo():
    if os.name != "nt":
        return None
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return info


def _run_ffmpeg_with_progress(cmd, duration_sec, cancellation_event, progress_callback, worker_ref, log_tag):
    """Corre un comando de ffmpeg parseando "time=" de stderr contra
    `duration_sec` para progreso 0-100 -- mismo mecanismo que
    QueueWorker._run_ffmpeg_command (core/utils/queue_manager.py), usado acá
    dos veces (extracción y rearmado) sin duplicar el parseo. Mismo truco de
    reasignar `worker_ref.cancel` para matar el proceso al toque en vez de
    esperar a que el bucle de stderr note la cancelación en la próxima línea."""
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", startupinfo=_startupinfo(),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except Exception as e:
        return False, QCoreApplication.translate("video_upscale_engine", "No se pudo iniciar ffmpeg: {0}").format(e)

    if worker_ref:
        worker_ref.downloader = proc

        def _cancel_proc():
            cancellation_event.set()
            proc.terminate()
        worker_ref.cancel = _cancel_proc

    for line in proc.stderr:
        if cancellation_event.is_set():
            proc.terminate()
            break
        clean_line = line.strip()
        if not clean_line:
            continue
        match = _time_regex.search(clean_line)
        if match and duration_sec > 0:
            h, m, s = float(match.group(1)), float(match.group(2)), float(match.group(3))
            current_sec = h * 3600 + m * 60 + s
            pct = min((current_sec / duration_sec) * 100.0, 100.0)
            if progress_callback:
                progress_callback(pct)
        else:
            lower_line = clean_line.lower()
            if any(kw in lower_line for kw in ("error", "warning")):
                logger.info(f"[{log_tag}] {clean_line}")

    proc.wait()

    if cancellation_event.is_set():
        return False, QCoreApplication.translate("video_upscale_engine", "Cancelado por el usuario.")

    if proc.returncode != 0:
        return False, QCoreApplication.translate("video_upscale_engine", "ffmpeg terminó con código {0}").format(proc.returncode)

    return True, None


def extract_frames(input_path: str, frames_dir: str, fps: float, duration_sec: float,
                    cancellation_event=None, progress_callback=None, worker_ref=None,
                    keep_alpha: bool = False, trim_in=None, trim_out=None,
                    decoder_args=None) -> tuple[bool, str]:
    """Extrae TODOS los fotogramas de `input_path` (o del tramo recortado) en
    `frames_dir`, al fps real del video (sin conversión de framerate) -- extraer más o
    menos fotogramas que los originales desincroniza el resultado final del audio
    remuxado en reassemble_video().

    keep_alpha: PNG con canal alfa (rgba); si no, JPG de máxima calidad (-q:v 2) sin
    submuestreo de color (yuvj444p). `decoder_args` es el decodificador que hace falta
    para no perder la transparencia de un WebM VP8/VP9 (ver probe_video_source).
    `duration_sec` debe ser la duración del tramo recortado (es la base del progreso)."""
    ffmpeg_exe = get_ffmpeg_path()
    if not ffmpeg_exe or not os.path.exists(ffmpeg_exe):
        return False, QCoreApplication.translate("video_upscale_engine", "No se encontró ffmpeg.")

    os.makedirs(frames_dir, exist_ok=True)
    if keep_alpha:
        frame_args = ["-pix_fmt", "rgba", os.path.join(frames_dir, _FRAME_NAME_PATTERN)]
    else:
        frame_args = ["-q:v", "2", "-pix_fmt", "yuvj444p",
                      os.path.join(frames_dir, _FRAME_NAME_PATTERN_JPG)]
    cmd = [
        ffmpeg_exe, "-y", *(decoder_args or []), *trim_input_args(trim_in, trim_out),
        "-i", input_path,
        # -fps_mode passthrough (reemplazo moderno de -vsync 0, removido en el
        # ffmpeg que empaqueta la app -- confirmado en vivo, "Unrecognized
        # option 'vsync'"): extrae cada fotograma tal cual viene, sin duplicar
        # ni descartar ninguno por conversión de framerate.
        "-map", "0:v:0", "-fps_mode", "passthrough", *frame_args,
    ]
    logger.info(f"Reescalar Video IA: extrayendo fotogramas -- {' '.join(cmd)}")

    cancellation_event = cancellation_event or threading.Event()
    return _run_ffmpeg_with_progress(
        cmd, duration_sec, cancellation_event, progress_callback, worker_ref,
        "Reescalar Video IA/Extraer",
    )


def count_frames(frames_dir: str) -> int:
    try:
        return sum(1 for f in os.listdir(frames_dir) if f.lower().endswith(_FRAME_EXTS))
    except OSError:
        return 0


def estimate_temp_space_bytes(width: int, height: int, fps: float, duration_sec: float, scale: int) -> int:
    """Estimación GROSERA del pico de temporales (frames originales + frames
    reescalados coexistiendo durante la etapa de reescalado, antes de que
    extract_frames() se borre) -- asume RGB sin comprimir como cota superior
    a propósito (un PNG real pesa menos, mejor sobreestimar que quedarse
    corto a mitad de un trabajo de horas). Usada por
    video_tools_view.py::_start_upscale_ia_jobs para el chequeo de espacio
    libre antes de encolar cada archivo."""
    total_frames = max(0.0, fps) * max(0.0, duration_sec)
    original_px = max(0, width) * max(0, height)
    scaled_px = original_px * max(1, scale) ** 2
    return int(total_frames * 3 * (original_px + scaled_px))


def upscale_frames_batch(frames_dir: str, out_dir: str, options: dict,
                          cancellation_event=None, progress_callback=None) -> tuple[bool, str]:
    """Reescala TODOS los fotogramas de `frames_dir` en un solo proceso (ver
    run_upscale con batch_total -- confirmado en vivo que los 3 motores NCNN
    aceptan carpeta como -i/-o). No necesita el truco de reasignar
    `worker_ref.cancel`: run_upscale() ya sondea `cancellation_event` cada
    0.2s en un bucle propio que no depende de leer stderr, así que la
    cancelación ya es inmediata sin necesidad de matar el proceso desde
    afuera (a diferencia de ffmpeg, que si no imprime nada puede bloquear la
    lectura de stderr un rato)."""
    from core.tabs.image_tools.upscale_engine import run_upscale

    total = count_frames(frames_dir)
    if total == 0:
        return False, QCoreApplication.translate("video_upscale_engine", "No se encontraron fotogramas para reescalar.")

    return run_upscale(
        frames_dir, out_dir, options, cancellation_event=cancellation_event,
        progress_callback=progress_callback, batch_total=total,
    )


def reassemble_video(frames_dir: str, original_input_path: str, output_path: str, fps: float,
                      duration_sec: float, cancellation_event=None, progress_callback=None,
                      worker_ref=None, keep_audio: bool = True, alpha: bool = False,
                      trim_in=None, trim_out=None) -> tuple[bool, str]:
    """Rearma el video a partir de los fotogramas reescalados de `frames_dir`, al fps
    original. El códec sale de build_video_encode_args (H.264 yuv420p, o ProRes 4444
    con alfa si `alpha` y el contenedor es MOV).

    keep_audio: remuxa el audio de `original_input_path` SIN recodificarlo (-c:a copy),
    con el mismo recorte que los fotogramas -- si el original no tiene audio, -map 1:a?
    simplemente no mapea nada, ffmpeg no falla por eso."""
    ffmpeg_exe = get_ffmpeg_path()
    if not ffmpeg_exe or not os.path.exists(ffmpeg_exe):
        return False, QCoreApplication.translate("video_upscale_engine", "No se encontró ffmpeg.")

    frame_pattern = os.path.join(frames_dir, _FRAME_NAME_PATTERN)
    cmd = [ffmpeg_exe, "-y", "-framerate", str(fps or 30.0), "-i", frame_pattern]
    if keep_audio:
        cmd += [*trim_input_args(trim_in, trim_out), "-i", original_input_path,
                "-map", "0:v:0", "-map", "1:a:0?", "-c:a", "copy", "-shortest"]
    else:
        cmd += ["-map", "0:v:0", "-an"]
    cmd += [*build_video_encode_args(container_of(output_path), alpha=alpha), output_path]
    logger.info(f"Reescalar Video IA: rearmando video -- {' '.join(cmd)}")

    cancellation_event = cancellation_event or threading.Event()
    success, error = _run_ffmpeg_with_progress(
        cmd, duration_sec, cancellation_event, progress_callback, worker_ref,
        "Reescalar Video IA/Rearmar",
    )
    if not success and os.path.exists(output_path):
        try:
            os.remove(output_path)
        except OSError:
            pass
    return success, error
