# src/core/tabs/video_tools/video_depth_engine.py
"""Mapa de Profundidad de VIDEO -- los mismos modelos ONNX que el Editor de Imagen (ver
core/tabs/image_tools/depth_engine.py), aplicados fotograma a fotograma.

Tuberías, recorte, audio, transparencia, "procesar a menos fps" y suavizado viven en el
motor común (video_frame_engine.py); aquí solo está lo propio de la profundidad: los
mapas salen en gris de 16 bits al tamaño de proceso del modelo y ffmpeg los amplía al
tamaño original.

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
    puede, por CPU (ver _DepthRunner / _DepthProcessor.process).
  - Normalización estable (siempre): el rango cerca/lejos se adapta de a poco a lo largo
    del video en vez de recalcularse de cero en cada fotograma (_StableNormalizer).
  - Suavizado temporal y procesar a menos fps (opcionales): ver video_frame_engine.
"""
import numpy as np
from PySide6.QtCore import QCoreApplication

from core.logger.logger_manager import logger
from core.setup.models_setup import get_depth_families, get_depth_model_path, is_depth_model_installed
from core.tabs.image_tools.depth_engine import get_process_size, normalize_rgb_array, raw_to_disparity
from core.tabs.video_tools.video_frame_engine import (
    FrameProcessor, frame_step_of, run_frame_video, smoothing_weight_of,
)
from core.utils import onnx_sessions
from core.utils.onnx_providers import is_gpu_failure

_TAG = "Mapa de Profundidad (video)"

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
        self.session = onnx_sessions.get_session(self.path, use_gpu, label=_TAG)

    def _run(self, feed_array, images: int = 1):
        name_in = self.session.get_inputs()[0].name
        name_out = self.session.get_outputs()[0].name
        try:
            return self.session.run([name_out], {name_in: feed_array})[0]
        except Exception as e:
            if self.use_gpu and images > 1 and is_gpu_failure(e):
                raise _WindowTooLarge() from e
            if self.use_gpu and is_gpu_failure(e):
                logger.warning(f"{_TAG}: la GPU falló ({e!r}) -- sigue por CPU.")
                self.use_gpu = False
                self.session = onnx_sessions.get_session(self.path, False, label=_TAG)
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


class _DepthProcessor(FrameProcessor):
    """Mapas en gris 0..1 (ya normalizados de forma estable e invertidos si se pidió) al
    tamaño de proceso; ffmpeg los amplía."""
    pipe_pix_fmt = "gray16le"
    log_tag = _TAG

    def __init__(self, model_info: dict, options: dict, width: int, height: int):
        self.model_info = model_info
        self.model_name = options.get("depth_model")
        self.invert = bool(options.get("depth_invert"))
        self.proc_w, self.proc_h = get_process_size(model_info, width, height)
        self.map_w, self.map_h = self.proc_w, self.proc_h
        self.runner = _DepthRunner(model_info, bool(options.get("depth_gpu", True)))
        self.normalizer = _StableNormalizer()
        self.prev_disp = None
        self.window = 1
        if self.runner.layout == "5d":
            self.window = _da3_window(self.proc_w, self.proc_h)
            logger.info(f"{_TAG}: {self.window} fotograma(s) por pasada.")

    def describe(self) -> str:
        return f"modelo {self.model_name} ({self.runner.layout})"

    def _infer_window(self, rgbs):
        """Una ventana; si la GPU no da abasto, se sigue de a un fotograma (y, si
        tampoco puede, _DepthRunner pasa a CPU)."""
        try:
            return self.runner.infer(rgbs)
        except _WindowTooLarge:
            logger.warning(f"{_TAG}: la GPU no pudo con {len(rgbs)} fotogramas por pasada -- "
                           f"se sigue de a uno.")
            self.window = 1
            return [d for rgb in rgbs for d in self.runner.infer([rgb])]

    def process(self, rgbs: list) -> list:
        disps = self._infer_window(rgbs)
        if self.runner.layout == "5d":
            # Escala común DENTRO de la ventana (la da el modelo); ENTRE ventanas se ajusta
            # con el primer fotograma de esta contra el último de la anterior.
            ref = self.prev_disp
            if ref is not None:
                cur = disps[0]
                valid = (ref > 0) & (cur > 0)
                if valid.any():
                    scale = float(np.median(ref[valid] / cur[valid]))
                    if np.isfinite(scale) and scale > 0:
                        disps = [d * scale for d in disps]
            self.prev_disp = disps[-1]
        maps = [self.normalizer(d) for d in disps]
        return [1.0 - m for m in maps] if self.invert else maps

    def to_bytes(self, frame_map: np.ndarray) -> bytes:
        return (frame_map * 65535.0 + 0.5).astype("<u2").tobytes()


def run_depth_video(input_path: str, output_path: str, options: dict, fps: float,
                    duration_sec: float, trim_in=None, trim_out=None, cancellation_event=None,
                    progress_callback=None, worker_ref=None) -> tuple[bool, str]:
    """Genera el video de Mapa de Profundidad de `input_path` (o del tramo recortado).

    options: depth_family/depth_model/depth_gpu/depth_invert (mismo selector que el
    Editor de Imagen), depth_16bit, keep_alpha, keep_audio, depth_smoothing
    ("off"/"low"/"medium"/"high") y depth_frame_step (1-4).
    `duration_sec` es la del tramo recortado. progress_callback(pct, eta_segundos)."""
    model_info = _model_info(options)
    if not model_info:
        return False, QCoreApplication.translate("video_depth_engine", "No hay un modelo de profundidad seleccionado.")
    if not is_depth_model_installed(model_info):
        return False, QCoreApplication.translate("video_depth_engine", "El modelo '{0}' no está instalado -- ve a Ajustes > Modelos para "
                          "descargarlo.").format(options.get("depth_model"))

    return run_frame_video(
        input_path, output_path,
        lambda w, h, _ow, _oh: _DepthProcessor(model_info, options, w, h),
        encode_kind="gray", sixteen_bit=bool(options.get("depth_16bit")),
        keep_alpha=bool(options.get("keep_alpha")), keep_audio=bool(options.get("keep_audio", True)),
        step=frame_step_of(options.get("depth_frame_step")),
        smooth_weight=smoothing_weight_of(options.get("depth_smoothing")),
        fps=fps, duration_sec=duration_sec, trim_in=trim_in, trim_out=trim_out,
        cancellation_event=cancellation_event, progress_callback=progress_callback,
        worker_ref=worker_ref,
    )
