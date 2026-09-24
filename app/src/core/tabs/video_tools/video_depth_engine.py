# src/core/tabs/video_tools/video_depth_engine.py
"""Mapa de Profundidad de VIDEO -- los mismos modelos ONNX que el Editor de Imagen (ver
core/tabs/image_tools/depth_engine.py), aplicados fotograma a fotograma.

Sin fotogramas en disco (a diferencia del Reescalado IA, que depende de motores
externos que solo leen archivos): un ffmpeg decodifica el video ya reducido al tamaño
de proceso del modelo y lo entrega por una tubería; la app calcula la profundidad y
entrega los mapas (gris de 16 bits, a tamaño de proceso) a otro ffmpeg, que los amplía
al tamaño original, les pega la transparencia y el audio del original si corresponde, y
codifica la salida (ver ia_video_common.build_video_encode_args).

Parpadeo: cada modelo decide por su cuenta qué es "cerca" y "lejos" en cada imagen, así
que normalizar cada fotograma por separado (como hace el Editor de Imagen) hace que el
brillo del mapa salte entre fotogramas. Contra eso:
  - Depth Anything 3 (entrada "5d"): es multivista -- recibe VARIAS imágenes a la vez y
    da la profundidad de todas en una escala común. Se le pasan ventanas de fotogramas
    consecutivos, y la escala de cada ventana se ajusta a la anterior comparando su
    primer fotograma con el último de la anterior (son consecutivos, casi iguales). No
    se repite ningún fotograma entre ventanas: la memoria crece mucho con cada imagen
    extra por pasada, así que cada imagen de la pasada tiene que ser un fotograma nuevo.
    El tamaño de la ventana sale de un tope de tokens por pasada (_DA3_TOKEN_BUDGET),
    porque NO hay que llegar a quedarse sin memoria: medido con DirectML, una vez que
    la GPU se queda sin memoria, ese proceso ya no vuelve a ir bien por GPU (ni
    recargando la sesión). Si igual pasa, se sigue de a 1 fotograma y, si tampoco
    puede, por CPU (ver _DepthRunner / infer_window).
  - Normalización estable (siempre): el rango cerca/lejos se adapta de a poco a lo largo
    del video en vez de recalcularse de cero en cada fotograma (_StableNormalizer).
  - Suavizado temporal (opcional): mezcla cada mapa con el anterior.
  - Procesar a menos fps (opcional): se calcula uno de cada N fotogramas y los del medio
    se interpolan entre los dos mapas vecinos. La salida conserva fps y duración.
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
from core.setup.models_setup import get_depth_families, get_depth_model_path, is_depth_model_installed
from core.tabs.image_tools.depth_engine import get_process_size, normalize_rgb_array, raw_to_disparity
from core.tabs.video_tools.ia_video_common import (
    CONTAINERS_16BIT, build_video_encode_args, container_of, probe_video_source, trim_input_args,
)
from core.utils import onnx_sessions
from core.utils.onnx_providers import is_gpu_failure

# Peso del fotograma NUEVO en el suavizado temporal (1.0 = sin suavizado).
SMOOTHING_WEIGHTS = {"off": 1.0, "low": 0.6, "medium": 0.4, "high": 0.25}
# Procesar uno de cada N fotogramas.
FRAME_STEPS = (1, 2, 3, 4)

# Fotogramas por pasada de Depth Anything 3: tantos como entren en _DA3_TOKEN_BUDGET
# tokens (parches de 14x14 px de TODAS las imágenes de la pasada), hasta _DA3_MAX_WINDOW.
# Medido con DA3 Large a 924x518 (2442 tokens por imagen) en una RTX 3060 con DirectML:
# 1 imagen 1,52 s; 2 imágenes (4884 tokens) 1,43 s por fotograma; 3 (7326) 4,93 s por
# fotograma, con la memoria al límite; 4 (9768) se queda sin memoria.
_DA3_TOKEN_BUDGET = 5000
_DA3_MAX_WINDOW = 4
_PATCH_PX = 14
# Cuánto se acerca por fotograma calculado el rango de la normalización estable al del
# fotograma actual (0..1). Bajo = más estable; alto = se adapta antes a un cambio de plano.
_NORMALIZER_ADAPT = 0.1
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


def _model_info(options: dict):
    family, model = options.get("depth_family"), options.get("depth_model")
    if not family or not model:
        return None
    return get_depth_families().get(family, {}).get(model)


class _StableNormalizer:
    """Lleva la disparidad cruda a 0..1 con un rango (percentiles 1-99) que cambia de a
    poco entre fotogramas, en vez de uno propio por fotograma. Si el rango nuevo no se
    toca con el anterior (cambio de plano), se reinicia en vez de arrastrarlo."""

    def __init__(self):
        self.lo = None
        self.hi = None

    def __call__(self, disparity: np.ndarray) -> np.ndarray:
        lo, hi = np.percentile(disparity[::4, ::4], (1.0, 99.0))
        lo, hi = float(lo), float(hi)
        if self.lo is None or hi < self.lo or lo > self.hi:
            self.lo, self.hi = lo, hi
        else:
            self.lo += (lo - self.lo) * _NORMALIZER_ADAPT
            self.hi += (hi - self.hi) * _NORMALIZER_ADAPT
        span = max(self.hi - self.lo, 1e-6)
        return np.clip((disparity - self.lo) / span, 0.0, 1.0)


class _WindowTooLarge(Exception):
    """La GPU no pudo con varias imágenes por pasada: hay que achicar la ventana."""


def _da3_window(proc_w: int, proc_h: int) -> int:
    tokens = max(1, (proc_w // _PATCH_PX) * (proc_h // _PATCH_PX))
    return max(1, min(_DA3_MAX_WINDOW, _DA3_TOKEN_BUDGET // tokens))


class _DepthRunner:
    """Inferencia sobre fotogramas ya al tamaño de proceso. Si la GPU falla con varias
    imágenes por pasada, avisa con _WindowTooLarge para seguir de a una; con una sola,
    sigue por CPU (el mismo reintento que el Editor de Imagen)."""

    def __init__(self, model_info: dict, use_gpu: bool):
        self.model_info = model_info
        self.path = get_depth_model_path(model_info)
        self.layout = model_info.get("input_layout", "4d")
        self.kind = model_info.get("output_kind", "disparity")
        self.use_gpu = use_gpu
        self.session = onnx_sessions.get_session(self.path, use_gpu, label="Mapa de Profundidad (video)")

    def _run(self, feed_array, images: int = 1):
        name_in = self.session.get_inputs()[0].name
        name_out = self.session.get_outputs()[0].name
        try:
            return self.session.run([name_out], {name_in: feed_array})[0]
        except Exception as e:
            if self.use_gpu and images > 1 and is_gpu_failure(e):
                raise _WindowTooLarge() from e
            if self.use_gpu and is_gpu_failure(e):
                logger.warning(f"Mapa de Profundidad (video): la GPU falló ({e!r}) -- sigue por CPU.")
                self.use_gpu = False
                self.session = onnx_sessions.get_session(self.path, False, label="Mapa de Profundidad (video)")
                return self._run(feed_array)
            raise

    def infer(self, rgbs: list) -> list:
        """Disparidades crudas (sin normalizar) de una lista de fotogramas RGB uint8."""
        tensors = [normalize_rgb_array(rgb) for rgb in rgbs]
        if self.layout == "5d":
            # Depth Anything 3: todos juntos, [lote=1, n_imágenes, C, H, W].
            raw = self._run(np.ascontiguousarray(np.stack(tensors)[None], dtype=np.float32),
                            images=len(tensors))
            return [raw_to_disparity(raw[0, i], self.kind) for i in range(len(rgbs))]
        return [raw_to_disparity(self._run(np.ascontiguousarray(t[None], dtype=np.float32)), self.kind)
                for t in tensors]


def run_depth_video(input_path: str, output_path: str, options: dict, fps: float,
                    duration_sec: float, trim_in=None, trim_out=None, cancellation_event=None,
                    progress_callback=None, worker_ref=None) -> tuple[bool, str]:
    """Genera el video de Mapa de Profundidad de `input_path` (o del tramo recortado).

    options: depth_family/depth_model/depth_gpu/depth_invert (mismo selector que el
    Editor de Imagen), depth_16bit, keep_alpha, keep_audio, depth_smoothing
    ("off"/"low"/"medium"/"high") y depth_frame_step (1-4).
    `duration_sec` es la del tramo recortado. progress_callback(pct, eta_segundos)."""
    cancellation_event = cancellation_event or threading.Event()
    ffmpeg_exe = get_ffmpeg_path()
    if not ffmpeg_exe or not os.path.exists(ffmpeg_exe):
        return False, QCoreApplication.translate("video_depth_engine", "No se encontró ffmpeg.")

    model_info = _model_info(options)
    if not model_info:
        return False, QCoreApplication.translate("video_depth_engine", "No hay un modelo de profundidad seleccionado.")
    if not is_depth_model_installed(model_info):
        return False, QCoreApplication.translate("video_depth_engine", "El modelo '{0}' no está instalado -- ve a Ajustes > Modelos para "
                          "descargarlo.").format(options.get("depth_model"))

    source = probe_video_source(input_path)
    width, height = source["width"], source["height"]
    if not width or not height:
        return False, QCoreApplication.translate("video_depth_engine", "No se pudo leer el video de origen.")
    fps = fps or source["fps"] or 30.0

    container = container_of(output_path)
    depth16 = bool(options.get("depth_16bit")) and container in CONTAINERS_16BIT
    alpha = (bool(options.get("keep_alpha")) and source["has_alpha"]
             and (container == "mov" or (depth16 and container == "mkv")))
    keep_audio = bool(options.get("keep_audio", True)) and source["has_audio"]
    step = int(options.get("depth_frame_step") or 1)
    step = step if step in FRAME_STEPS else 1
    smooth_weight = SMOOTHING_WEIGHTS.get(options.get("depth_smoothing") or "off", 1.0)
    invert = bool(options.get("depth_invert"))

    proc_w, proc_h = get_process_size(model_info, width, height)
    # H.264 yuv420p pide lados pares (ver build_video_encode_args).
    uses_h264 = not depth16 and not (alpha and container == "mov")
    out_w, out_h = (width - width % 2, height - height % 2) if uses_h264 else (width, height)
    trim = trim_input_args(trim_in, trim_out)

    decode_cmd = [ffmpeg_exe, "-v", "error", "-nostdin", *trim, "-i", input_path,
                  "-map", "0:v:0", "-fps_mode", "passthrough",
                  "-vf", f"scale={proc_w}:{proc_h}:flags=bicubic",
                  "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]

    encode_cmd = [ffmpeg_exe, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "gray16le",
                  "-s", f"{proc_w}x{proc_h}", "-framerate", str(fps), "-i", "pipe:0"]
    if alpha or keep_audio:
        encode_cmd += [*(source["decoder_args"] if alpha else []), *trim, "-i", input_path]
    graph = f"[0:v]scale={out_w}:{out_h}:flags=bicubic,format=gray16le[d]"
    if alpha:
        # El alfa sale del ORIGINAL a tamaño completo (no del fotograma reducido), así
        # el borde de la transparencia queda igual de nítido que en la fuente.
        graph += (f";[1:v]alphaextract,scale={out_w}:{out_h}[a]"
                  f";[d]format=yuv444p16le[dc];[dc][a]alphamerge[v]")
    else:
        graph += ";[d]null[v]"
    encode_cmd += ["-filter_complex", graph, "-map", "[v]"]
    if keep_audio:
        encode_cmd += ["-map", "1:a:0?", "-c:a", "copy", "-shortest"]
    else:
        encode_cmd += ["-an"]
    encode_cmd += [*build_video_encode_args(container, alpha=alpha, depth16=depth16,
                                            with_filter=False), output_path]

    logger.info(f"Mapa de Profundidad (video): {os.path.basename(input_path)} -> "
                f"{os.path.basename(output_path)} | modelo {options.get('depth_model')} "
                f"({model_info.get('input_layout')}), proceso {proc_w}x{proc_h}, 16 bits={depth16}, "
                f"alfa={alpha}, audio={keep_audio}, 1 de cada {step}, suavizado={options.get('depth_smoothing')}")
    logger.info(f"Mapa de Profundidad (video): decodificar -- {' '.join(decode_cmd)}")
    logger.info(f"Mapa de Profundidad (video): codificar -- {' '.join(encode_cmd)}")

    try:
        runner = _DepthRunner(model_info, bool(options.get("depth_gpu", True)))
    except Exception as e:
        return False, QCoreApplication.translate("video_depth_engine", "No se pudo cargar el modelo: {0}").format(e)

    decoder = encoder = None
    dec_err, enc_err = deque(maxlen=20), deque(maxlen=20)
    try:
        decoder = _popen(decode_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
        encoder = _popen(encode_cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except Exception as e:
        for proc in (decoder, encoder):
            if proc:
                proc.kill()
        return False, QCoreApplication.translate("video_depth_engine", "No se pudo iniciar ffmpeg: {0}").format(e)
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
    state = {"written": 0, "last_report": 0.0, "last_map": None, "prev_norm": None,
             "prev_disp": None, "window": 1}
    normalizer = _StableNormalizer()
    if runner.layout == "5d":
        state["window"] = _da3_window(proc_w, proc_h)
        logger.info(f"Mapa de Profundidad (video): {state['window']} fotograma(s) por pasada.")

    def report():
        now = time.monotonic()
        if progress_callback and now - state["last_report"] >= _PROGRESS_EVERY_S:
            state["last_report"] = now
            done = state["written"]
            elapsed = now - started
            eta = (elapsed / done) * max(0, total - done) if done else None
            progress_callback(min(99.0, done / total * 100.0), eta)

    def write(norm_map):
        values = 1.0 - norm_map if invert else norm_map
        encoder.stdin.write((values * 65535.0 + 0.5).astype("<u2").tobytes())
        state["written"] += 1
        report()

    def finalize(disparity):
        norm = normalizer(disparity)
        prev = state["prev_norm"]
        if prev is not None and smooth_weight < 1.0:
            norm = norm * smooth_weight + prev * (1.0 - smooth_weight)
        state["prev_norm"] = norm
        return norm

    def emit(skips_before: int, norm_map):
        """Los fotogramas saltados entre el mapa anterior y este se interpolan."""
        last = state["last_map"]
        for j in range(1, skips_before + 1):
            t = j / (skips_before + 1)
            write(last * (1.0 - t) + norm_map * t if last is not None else norm_map)
        write(norm_map)
        state["last_map"] = norm_map

    def infer_window(rgbs):
        """Una ventana; si la GPU no da abasto, se sigue de a un fotograma (y, si
        tampoco puede, _DepthRunner pasa a CPU)."""
        try:
            return runner.infer(rgbs)
        except _WindowTooLarge:
            logger.warning(f"Mapa de Profundidad (video): la GPU no pudo con {len(rgbs)} fotogramas "
                           f"por pasada -- se sigue de a uno.")
            state["window"] = 1
            return [d for rgb in rgbs for d in runner.infer([rgb])]

    def process(entries):
        disps = infer_window([e[0] for e in entries])
        if runner.layout == "5d":
            # Escala común DENTRO de la ventana (la da el modelo); ENTRE ventanas se ajusta
            # con el primer fotograma de esta contra el último de la anterior.
            ref = state["prev_disp"]
            if ref is not None:
                cur = disps[0]
                valid = (ref > 0) & (cur > 0)
                if valid.any():
                    scale = float(np.median(ref[valid] / cur[valid]))
                    if np.isfinite(scale) and scale > 0:
                        disps = [d * scale for d in disps]
            state["prev_disp"] = disps[-1]
        for (rgb, skips), disp in zip(entries, disps):
            emit(skips, finalize(disp))

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
                if len(pending) >= state["window"]:
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
        error = QCoreApplication.translate("video_depth_engine", "ffmpeg dejó de recibir los fotogramas: {0}").format(enc_err[-1] if enc_err else e)
    except Exception as e:
        logger.error(f"Mapa de Profundidad (video): error calculando la profundidad: {e!r}")
        error = QCoreApplication.translate("video_depth_engine", "Error al calcular la profundidad: {0}").format(e)
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
        error = QCoreApplication.translate("video_depth_engine", "Cancelado por el usuario.")
    elif not error and state["written"] == 0:
        error = QCoreApplication.translate("video_depth_engine", "No se pudo leer ningún fotograma: {0}").format(dec_err[-1] if dec_err else "")
    elif not error and encoder.returncode != 0:
        error = QCoreApplication.translate("video_depth_engine", "ffmpeg terminó con código {0}: {1}").format(
            encoder.returncode, enc_err[-1] if enc_err else "")

    if error:
        logger.error(f"Mapa de Profundidad (video): {error}")
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass
        return False, error

    elapsed = time.monotonic() - started
    logger.info(f"Mapa de Profundidad (video): {state['written']} fotogramas en {elapsed:.1f} s "
                f"({state['written'] / max(elapsed, 0.001):.2f} fps de proceso)")
    if progress_callback:
        progress_callback(100.0, 0)
    return True, None
