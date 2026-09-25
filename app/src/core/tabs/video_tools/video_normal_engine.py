# src/core/tabs/video_tools/video_normal_engine.py
"""Mapa de Normales de VIDEO -- MoGe-2, el mismo modelo que el Editor de Imagen (ver
core/tabs/image_tools/normal_engine.py), aplicado fotograma a fotograma.

Tuberías, recorte, audio, transparencia, "procesar a menos fps" y suavizado viven en el
motor común (video_frame_engine.py). Lo propio de las normales:

  - Solo MoGe-2 (escenas). DeepBump no se ofrece en video: es para texturas planas y su
    coste crece con la resolución (bloques de 256 px).
  - Sin parpadeo de rango: a diferencia de la profundidad, cada píxel es una dirección
    absoluta (no "más cerca o más lejos que el resto"), así que no hace falta
    normalización estable ni ventanas multivista. Queda el temblor fino entre
    fotogramas, que se quita con el suavizado opcional.
  - Mezclar o ampliar vectores unitarios los acorta: el suavizado, la interpolación de
    "procesar a menos fps" y la ampliación al tamaño original se hacen en la app, y cada
    mapa se vuelve a normalizar antes de entregarlo (ver normal_engine.resize_vectors).
    Por eso los mapas salen al tamaño FINAL, en RGB de 16 bits, y ffmpeg no los amplía.
  - El formato de salida importa (ver ia_video_common.build_video_encode_args): por
    defecto MOV ProRes 4444; H.264 4:2:0 deforma las direcciones.
"""
import numpy as np
from PySide6.QtCore import QCoreApplication

from core.logger.logger_manager import logger
from core.setup.models_setup import get_normal_families, get_normal_model_path, is_normal_model_installed
from core.tabs.image_tools.normal_engine import moge_tokens, moge_vectors, moge_work_size, resize_vectors
from core.tabs.video_tools.video_frame_engine import (
    FrameProcessor, frame_step_of, run_frame_video, smoothing_weight_of,
)
from core.utils import onnx_sessions
from core.utils.onnx_providers import is_gpu_failure

_TAG = "Mapa de Normales (video)"


def _model_info(options: dict):
    family, model = options.get("normals_family"), options.get("normals_model")
    if not family or not model:
        return None
    return get_normal_families().get(family, {}).get(model)


class _NormalProcessor(FrameProcessor):
    """Mapas = vectores unitarios HxWx3 (convención OpenGL) al tamaño de trabajo de
    MoGe-2; to_bytes los amplía al tamaño de salida, los normaliza y los codifica en RGB
    de 16 bits (0.5 + 0.5 * n)."""
    pipe_pix_fmt = "rgb48le"
    log_tag = _TAG

    def __init__(self, model_info: dict, options: dict, width: int, height: int,
                 out_w: int, out_h: int):
        self.model_name = options.get("normals_model")
        self.path = get_normal_model_path(model_info)
        self.tokens = moge_tokens(options)
        self.directx = bool(options.get("normals_directx"))
        self.proc_w, self.proc_h = moge_work_size(width, height)
        self.map_w, self.map_h = out_w, out_h
        self.use_gpu = bool(options.get("normals_gpu", True))
        self.session = onnx_sessions.get_session(self.path, self.use_gpu, label=_TAG)

    def describe(self) -> str:
        return f"modelo {self.model_name}, {self.tokens} tokens, DirectX={self.directx}"

    def _infer(self, rgb):
        try:
            return moge_vectors(self.session, rgb, self.tokens)
        except Exception as e:
            if self.use_gpu and is_gpu_failure(e):
                logger.warning(f"{_TAG}: la GPU falló ({e!r}) -- sigue por CPU.")
                self.use_gpu = False
                self.session = onnx_sessions.get_session(self.path, False, label=_TAG)
                return moge_vectors(self.session, rgb, self.tokens)
            raise

    def process(self, rgbs: list) -> list:
        return [self._infer(rgb) for rgb in rgbs]

    def to_bytes(self, frame_map: np.ndarray) -> bytes:
        vectors = resize_vectors(frame_map, (self.map_w, self.map_h))
        if self.directx:
            vectors[..., 1] *= -1.0      # DirectX: canal verde invertido
        encoded = (vectors * 0.5 + 0.5).clip(0.0, 1.0) * 65535.0 + 0.5
        return encoded.astype("<u2").tobytes()


def run_normal_video(input_path: str, output_path: str, options: dict, fps: float,
                     duration_sec: float, trim_in=None, trim_out=None, cancellation_event=None,
                     progress_callback=None, worker_ref=None) -> tuple[bool, str]:
    """Genera el video de Mapa de Normales de `input_path` (o del tramo recortado).

    options: normals_family/normals_model/normals_gpu/normals_directx/normals_detail
    (mismo selector que el Editor de Imagen), depth_16bit (la casilla "16 bits" es común
    a las funciones de mapas), keep_alpha, keep_audio, normals_smoothing
    ("off"/"low"/"medium"/"high") y normals_frame_step (1-4).
    `duration_sec` es la del tramo recortado. progress_callback(pct, eta_segundos)."""
    model_info = _model_info(options)
    if not model_info:
        return False, QCoreApplication.translate("video_normal_engine", "No hay un modelo de normales seleccionado.")
    if model_info.get("engine") != "moge":
        return False, QCoreApplication.translate("video_normal_engine", "Ese modelo es solo para texturas: en video usa MoGe-2.")
    if not is_normal_model_installed(model_info):
        return False, QCoreApplication.translate("video_normal_engine", "El modelo '{0}' no está instalado -- ve a Ajustes > Modelos para "
                          "descargarlo.").format(options.get("normals_model"))

    return run_frame_video(
        input_path, output_path,
        lambda w, h, ow, oh: _NormalProcessor(model_info, options, w, h, ow, oh),
        encode_kind="normals", sixteen_bit=bool(options.get("depth_16bit")),
        keep_alpha=bool(options.get("keep_alpha")), keep_audio=bool(options.get("keep_audio", True)),
        step=frame_step_of(options.get("normals_frame_step")),
        smooth_weight=smoothing_weight_of(options.get("normals_smoothing")),
        fps=fps, duration_sec=duration_sec, trim_in=trim_in, trim_out=trim_out,
        cancellation_event=cancellation_event, progress_callback=progress_callback,
        worker_ref=worker_ref,
    )
