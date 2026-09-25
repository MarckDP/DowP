# src/core/tabs/video_tools/video_frame_engine.py
"""Motor común de las Herramientas IA de video que procesan fotograma a fotograma con un
modelo ONNX (Mapa de Profundidad, Mapa de Normales): todo lo que NO depende del modelo.

Sin fotogramas en disco (a diferencia del Reescalado IA, que depende de motores externos
que solo leen archivos): un ffmpeg decodifica el video ya reducido al tamaño de proceso
del modelo y lo entrega por una tubería; el "procesador" de cada función calcula el mapa
de cada fotograma y la app entrega los mapas a otro ffmpeg, que los amplía al tamaño
original si hace falta, les pega la transparencia y el audio del original si corresponde,
y codifica la salida (ver ia_video_common.build_video_encode_args).

Lo común que vive aquí:
  - Tuberías, recorte, audio, transparencia (el alfa sale del ORIGINAL a tamaño completo),
    progreso con tiempo restante, cancelación y mensajes de error.
  - Procesar a menos fps (opcional): se calcula uno de cada N fotogramas y los del medio
    se interpolan entre los dos mapas vecinos. La salida conserva fps y duración.
  - Suavizado temporal (opcional): mezcla cada mapa con el anterior.
  - Ventanas: si el procesador pide varios fotogramas por pasada (Depth Anything 3), se
    le entregan juntos.

Lo propio de cada función es un "procesador" (ver FrameProcessor): cómo calcula el mapa
de una tanda de fotogramas y cómo lo convierte en bytes para la tubería. Los mapas que
devuelve tienen que poder mezclarse linealmente (la interpolación y el suavizado los
promedian); si su espacio lo pide (vectores unitarios de las normales), el procesador
corrige en to_bytes lo que la mezcla deforma.
"""
import os
import subprocess
import threading
import time
from collections import deque

import numpy as np
from PySide6.QtCore import QCoreApplication

from core.logger.logger_manager import logger
from core.setup.ffmpeg_setup import get_ffmpeg_path
from core.tabs.video_tools.ia_video_common import (
    CONTAINERS_16BIT, alpha_supported, build_video_encode_args, container_of, probe_video_source, trim_input_args,
)

# Peso del fotograma NUEVO en el suavizado temporal (1.0 = sin suavizado).
SMOOTHING_WEIGHTS = {"off": 1.0, "low": 0.6, "medium": 0.4, "high": 0.25}
# Procesar uno de cada N fotogramas.
FRAME_STEPS = (1, 2, 3, 4)
_PROGRESS_EVERY_S = 0.25


def _startupinfo():
    if os.name != "nt":
        return None
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return info


def _popen(cmd, **kwargs):
    return subprocess.Popen(
        cmd, startupinfo=_startupinfo(),
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0, **kwargs)


def _drain(stream, sink: deque):
    """Lee stderr de ffmpeg en otro hilo: si nadie lo lee, ffmpeg se bloquea al llenar
    el búfer. Se guardan las últimas líneas para explicar un fallo."""
    try:
        for line in iter(stream.readline, b""):
            text = line.decode("utf-8", errors="replace").strip()
            if text:
                sink.append(text)
    except Exception:
        pass


def frame_step_of(value) -> int:
    step = int(value or 1)
    return step if step in FRAME_STEPS else 1


def smoothing_weight_of(value) -> float:
    return SMOOTHING_WEIGHTS.get(value or "off", 1.0)


class FrameProcessor:
    """Lo que cada función aporta al motor. Se crea ya con el tamaño del video (ver
    run_frame_video, `make_processor`) y fija:

      proc_w, proc_h   tamaño al que ffmpeg entrega los fotogramas (RGB uint8).
      map_w, map_h     tamaño de lo que devuelve to_bytes. Si difiere del de salida,
                       ffmpeg lo amplía (bicúbico).
      pipe_pix_fmt     formato de píxel de esos bytes ("gray16le", "rgb48le"...).
      window           fotogramas por llamada a process() (puede bajar a 1 en marcha).
      log_tag          prefijo de los mensajes del registro.
    """
    proc_w = proc_h = map_w = map_h = 0
    pipe_pix_fmt = "gray16le"
    window = 1
    log_tag = "IA (video)"

    def describe(self) -> str:
        """Resumen para el registro (modelo, tamaño de proceso...)."""
        return ""

    def process(self, rgbs: list) -> list:
        """Mapas float32 (mezclables linealmente) de una tanda de fotogramas RGB uint8
        de proc_h x proc_w, en el mismo orden."""
        raise NotImplementedError

    def to_bytes(self, frame_map: np.ndarray) -> bytes:
        """Bytes de un mapa (ya suavizado o interpolado) en pipe_pix_fmt, map_w x map_h."""
        raise NotImplementedError


def run_frame_video(input_path: str, output_path: str, make_processor, *, encode_kind: str,
                    sixteen_bit: bool, keep_alpha: bool, keep_audio: bool, step: int,
                    smooth_weight: float, fps: float, duration_sec: float, trim_in=None,
                    trim_out=None, cancellation_event=None, progress_callback=None,
                    worker_ref=None) -> tuple[bool, str]:
    """Aplica un procesador a cada fotograma de `input_path` (o del tramo recortado).

    make_processor(ancho, alto, ancho_salida, alto_salida) -> FrameProcessor. Se llama
    después de sondear el video; si lanza una excepción, el error se informa como "no se
    pudo cargar el modelo".
    encode_kind: "gray" (profundidad) o "normals" -- ver build_video_encode_args.
    `duration_sec` es la del tramo recortado. progress_callback(pct, eta_segundos)."""
    cancellation_event = cancellation_event or threading.Event()
    ffmpeg_exe = get_ffmpeg_path()
    if not ffmpeg_exe or not os.path.exists(ffmpeg_exe):
        return False, QCoreApplication.translate("video_frame_engine", "No se encontró ffmpeg.")

    source = probe_video_source(input_path)
    width, height = source["width"], source["height"]
    if not width or not height:
        return False, QCoreApplication.translate("video_frame_engine", "No se pudo leer el video de origen.")
    fps = fps or source["fps"] or 30.0

    container = container_of(output_path)
    sixteen_bit = bool(sixteen_bit) and container in CONTAINERS_16BIT
    alpha = bool(keep_alpha) and source["has_alpha"] and alpha_supported(container, sixteen_bit, encode_kind)
    keep_audio = bool(keep_audio) and source["has_audio"]
    video_args = build_video_encode_args(container, alpha=alpha, depth16=sixteen_bit,
                                         with_filter=False, kind=encode_kind)
    # H.264 yuv420p pide lados pares (ver build_video_encode_args).
    if "libx264" in video_args:
        out_w, out_h = width - width % 2, height - height % 2
    else:
        out_w, out_h = width, height

    try:
        processor = make_processor(width, height, out_w, out_h)
    except Exception as e:
        logger.error(f"IA (video): no se pudo cargar el modelo: {e!r}")
        return False, QCoreApplication.translate("video_frame_engine", "No se pudo cargar el modelo: {0}").format(e)
    tag = processor.log_tag
    proc_w, proc_h = processor.proc_w, processor.proc_h
    trim = trim_input_args(trim_in, trim_out)

    decode_cmd = [ffmpeg_exe, "-v", "error", "-nostdin", *trim, "-i", input_path,
                  "-map", "0:v:0", "-fps_mode", "passthrough",
                  "-vf", f"scale={proc_w}:{proc_h}:flags=bicubic",
                  "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]

    encode_cmd = [ffmpeg_exe, "-y", "-v", "error", "-f", "rawvideo",
                  "-pix_fmt", processor.pipe_pix_fmt, "-s", f"{processor.map_w}x{processor.map_h}",
                  "-framerate", str(fps), "-i", "pipe:0"]
    if alpha or keep_audio:
        encode_cmd += [*(source["decoder_args"] if alpha else []), *trim, "-i", input_path]
    graph = "[0:v]"
    if (processor.map_w, processor.map_h) != (out_w, out_h):
        graph += f"scale={out_w}:{out_h}:flags=bicubic,"
    graph += f"format={processor.pipe_pix_fmt}[d]"
    if alpha:
        # El alfa sale del ORIGINAL a tamaño completo (no del fotograma reducido), así
        # el borde de la transparencia queda igual de nítido que en la fuente.
        # alphamerge necesita un formato con plano de alfa del mismo tipo que el mapa.
        with_alpha = "gbrap16le" if encode_kind == "normals" else "yuva444p16le"
        graph += (f";[1:v]alphaextract,scale={out_w}:{out_h}[a]"
                  f";[d]format={with_alpha}[dc];[dc][a]alphamerge[v]")
    else:
        graph += ";[d]null[v]"
    encode_cmd += ["-filter_complex", graph, "-map", "[v]"]
    if keep_audio:
        encode_cmd += ["-map", "1:a:0?", "-c:a", "copy", "-shortest"]
    else:
        encode_cmd += ["-an"]
    encode_cmd += [*video_args, output_path]

    logger.info(f"{tag}: {os.path.basename(input_path)} -> {os.path.basename(output_path)} | "
                f"{processor.describe()}, proceso {proc_w}x{proc_h}, 16 bits={sixteen_bit}, "
                f"alfa={alpha}, audio={keep_audio}, 1 de cada {step}, suavizado={smooth_weight}")
    logger.info(f"{tag}: decodificar -- {' '.join(decode_cmd)}")
    logger.info(f"{tag}: codificar -- {' '.join(encode_cmd)}")

    decoder = encoder = None
    dec_err, enc_err = deque(maxlen=20), deque(maxlen=20)
    try:
        decoder = _popen(decode_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
        encoder = _popen(encode_cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except Exception as e:
        for proc in (decoder, encoder):
            if proc:
                proc.kill()
        return False, QCoreApplication.translate("video_frame_engine", "No se pudo iniciar ffmpeg: {0}").format(e)
    threading.Thread(target=_drain, args=(decoder.stderr, dec_err), daemon=True).start()
    threading.Thread(target=_drain, args=(encoder.stderr, enc_err), daemon=True).start()

    def _kill():
        cancellation_event.set()
        for proc in (decoder, encoder):
            try:
                proc.kill()
            except Exception:
                pass

    if worker_ref is not None:
        worker_ref.downloader = encoder
        worker_ref.cancel = _kill

    total = max(1, int(round(duration_sec * fps)))
    frame_bytes = proc_w * proc_h * 3
    started = time.monotonic()
    state = {"written": 0, "last_report": 0.0, "last_map": None, "prev_map": None}

    def report():
        now = time.monotonic()
        if progress_callback and now - state["last_report"] >= _PROGRESS_EVERY_S:
            state["last_report"] = now
            done = state["written"]
            elapsed = now - started
            eta = (elapsed / done) * max(0, total - done) if done else None
            progress_callback(min(99.0, done / total * 100.0), eta)

    def write(frame_map):
        encoder.stdin.write(processor.to_bytes(frame_map))
        state["written"] += 1
        report()

    def smooth(frame_map):
        prev = state["prev_map"]
        if prev is not None and smooth_weight < 1.0:
            frame_map = frame_map * smooth_weight + prev * (1.0 - smooth_weight)
        state["prev_map"] = frame_map
        return frame_map

    def emit(skips_before: int, frame_map):
        """Los fotogramas saltados entre el mapa anterior y este se interpolan."""
        last = state["last_map"]
        for j in range(1, skips_before + 1):
            t = j / (skips_before + 1)
            write(last * (1.0 - t) + frame_map * t if last is not None else frame_map)
        write(frame_map)
        state["last_map"] = frame_map

    def process(entries):
        maps = processor.process([e[0] for e in entries])
        for (_rgb, skips), frame_map in zip(entries, maps):
            emit(skips, smooth(frame_map))

    pending = []   # fotogramas clave esperando inferencia: (rgb, saltados antes)
    skipped = 0
    index = 0
    error = None
    try:
        while not cancellation_event.is_set():
            data = decoder.stdout.read(frame_bytes)
            if not data or len(data) < frame_bytes:
                break
            if index % step == 0:
                rgb = np.frombuffer(data, dtype=np.uint8).reshape(proc_h, proc_w, 3)
                pending.append((rgb, skipped))
                skipped = 0
                if len(pending) >= processor.window:
                    process(pending)
                    pending = []
            else:
                skipped += 1
            index += 1
        if not cancellation_event.is_set():
            if pending:
                process(pending)
            for _ in range(skipped):
                # Cola del video después del último fotograma calculado.
                if state["last_map"] is not None:
                    write(state["last_map"])
    except (BrokenPipeError, OSError) as e:
        error = QCoreApplication.translate("video_frame_engine", "ffmpeg dejó de recibir los fotogramas: {0}").format(enc_err[-1] if enc_err else e)
    except Exception as e:
        logger.error(f"{tag}: error procesando los fotogramas: {e!r}")
        error = QCoreApplication.translate("video_frame_engine", "Error al procesar los fotogramas: {0}").format(e)
    finally:
        try:
            encoder.stdin.close()
        except Exception:
            pass

    if cancellation_event.is_set() or error:
        _kill()
    decoder.wait()
    encoder.wait()

    if cancellation_event.is_set():
        error = QCoreApplication.translate("video_frame_engine", "Cancelado por el usuario.")
    elif not error and state["written"] == 0:
        error = QCoreApplication.translate("video_frame_engine", "No se pudo leer ningún fotograma: {0}").format(dec_err[-1] if dec_err else "")
    elif not error and encoder.returncode != 0:
        error = QCoreApplication.translate("video_frame_engine", "ffmpeg terminó con código {0}: {1}").format(
            encoder.returncode, enc_err[-1] if enc_err else "")

    if error:
        logger.error(f"{tag}: {error}")
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass
        return False, error

    elapsed = time.monotonic() - started
    logger.info(f"{tag}: {state['written']} fotogramas en {elapsed:.1f} s "
                f"({state['written'] / max(elapsed, 0.001):.2f} fps de proceso)")
    if progress_callback:
        progress_callback(100.0, 0)
    return True, None
