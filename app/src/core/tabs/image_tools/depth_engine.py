# src/core/tabs/image_tools/depth_engine.py
"""Motor de "Mapa de Profundidad" -- corre los modelos ONNX de
DEPTH_MODEL_FAMILIES (core/constants.py) directo con onnxruntime, mismo enfoque
que rembg_engine.py: sesión ONNX cruda con pre/post-procesado manual, y un solo
pipeline para todas las familias. Lo que cambia entre modelos (forma de la
entrada, si devuelve disparidad o profundidad, cómo se escala la imagen) lo
declara cada entrada del catálogo -- agregar un modelo no toca este archivo.

La salida es un mapa en escala de grises con la convención "cerca = blanco"
(invertible desde el popover), al tamaño de la imagen de entrada. Si la imagen
trae canal alfa (por ejemplo, porque Eliminar Fondo corrió antes en el mismo
lote), el mapa conserva ese alfa: sale solo la profundidad del sujeto. El
modelo igual ve la imagen completa -- Eliminar Fondo solo toca el alfa y deja
los colores de debajo intactos, así que la profundidad se calcula con todo el
contexto de la escena."""
import os

import numpy as np
from PIL import Image

from core.logger.logger_manager import logger
from core.setup.models_setup import get_depth_families, get_depth_model_path, is_depth_model_installed
from core.utils import onnx_sessions
from core.utils.onnx_providers import is_gpu_failure
from PySide6.QtCore import QCoreApplication

_IMAGENET_MEAN = np.array((0.485, 0.456, 0.406), dtype=np.float32)
_IMAGENET_STD = np.array((0.229, 0.224, 0.225), dtype=np.float32)
# Tamaño de parche del ViT (DINOv2) que usan todos estos modelos: alto y ancho
# de la entrada tienen que ser múltiplos de 14.
_PATCH = 14
_DEFAULT_PROCESS_SIZE = 518


def _model_info(family: str | None, model: str | None) -> dict | None:
    if not family or not model:
        return None
    return get_depth_families().get(family, {}).get(model)


def get_process_size(model_info: dict, width: int, height: int) -> tuple[int, int]:
    """(ancho, alto) al que el modelo calcula la profundidad de una imagen de
    width x height. Es la resolución REAL del detalle del mapa -- el resultado
    se amplía después al tamaño original, de ahí el aviso "920×518 calculado"
    que muestra el Editor de Imagen sobre el resultado."""
    size = int(model_info.get("process_size") or _DEFAULT_PROCESS_SIZE)
    if model_info.get("process_mode") == "square":
        return size, size
    scale = size / max(1, min(width, height))
    new_w = max(_PATCH, round(width * scale / _PATCH) * _PATCH)
    new_h = max(_PATCH, round(height * scale / _PATCH) * _PATCH)
    return new_w, new_h


def prepare_session(options: dict) -> None:
    """Precarga la sesión ONNX antes de arrancar un lote -- ver
    rembg_engine.prepare_session()."""
    if not options.get("depth_enabled", False):
        return
    model_info = _model_info(options.get("depth_family"), options.get("depth_model"))
    if not model_info or not is_depth_model_installed(model_info):
        return
    try:
        onnx_sessions.get_session(get_depth_model_path(model_info), options.get("depth_gpu", True),
                                  label="Mapa de Profundidad")
    except Exception as e:
        logger.warning(f"Mapa de Profundidad: no se pudo precargar la sesión ({e}) -- se reintentará por imagen.")


def _preprocess(rgb: Image.Image, size: tuple[int, int], layout: str):
    resized = rgb.resize(size, Image.Resampling.BICUBIC)
    arr = np.asarray(resized, dtype=np.float32) / 255.0
    arr = ((arr - _IMAGENET_MEAN) / _IMAGENET_STD).transpose(2, 0, 1)[None]  # HWC -> 1CHW
    if layout == "5d":
        arr = arr[None]  # [lote, n_imágenes, C, H, W]
    return np.ascontiguousarray(arr, dtype=np.float32)


def _to_near_bright(raw, output_kind: str):
    """Salida cruda del modelo -> mapa 2D en 0..1 con cerca = 1."""
    depth = np.squeeze(raw).astype(np.float32)
    if depth.ndim != 2:
        raise ValueError(f"forma de salida inesperada {tuple(np.shape(raw))}")
    if output_kind == "depth":
        # Profundidad real (cerca = valor bajo): la inversa la vuelve disparidad,
        # que es lo que devuelven los demás modelos y lo que se espera ver.
        depth = 1.0 / np.maximum(depth, 1e-6)
    if not np.isfinite(depth).all():
        raise ValueError("el modelo devolvió valores no numéricos")
    lo, hi = float(depth.min()), float(depth.max())
    return (depth - lo) / (hi - lo + 1e-8)


def estimate_depth(img: Image.Image, options: dict, progress_callback=None) -> tuple[Image.Image, tuple[int, int]]:
    """Calcula el mapa de profundidad de `img` según options (depth_family/
    depth_model/depth_gpu/depth_invert -- ver DepthPopoverContent.get_settings(); y
    depth_16bit, que viene de las opciones de PNG/TIFF, ver ConvertPanel.get_settings()).
    Devuelve (mapa, (ancho, alto) de
    proceso). El mapa sale en modo "I;16" con depth_16bit y sin alfa, "LA" si
    `img` traía alfa (PNG no admite gris de 16 bits con alfa) y "L" si no."""
    model_info = _model_info(options.get("depth_family"), options.get("depth_model"))
    if not model_info:
        raise ValueError(QCoreApplication.translate("depth_engine", "Mapa de Profundidad: no hay un modelo de IA seleccionado."))
    if not is_depth_model_installed(model_info):
        raise FileNotFoundError(
            QCoreApplication.translate("depth_engine", "El modelo '{0}' no está instalado -- ve a Ajustes > Modelos para descargarlo.")
            .format(options.get("depth_model"))
        )

    use_gpu = options.get("depth_gpu", True)
    if progress_callback:
        # Una sola llamada a session.run() por imagen: no hay avance real que
        # contar, igual que en Eliminar Fondo.
        progress_callback(None)

    alpha = img.getchannel("A") if img.mode in ("RGBA", "LA", "PA") else None
    width, height = img.size
    process_size = get_process_size(model_info, width, height)

    try:
        session = onnx_sessions.get_session(get_depth_model_path(model_info), use_gpu, label="Mapa de Profundidad")
        feed = {session.get_inputs()[0].name: _preprocess(img.convert("RGB"), process_size,
                                                          model_info.get("input_layout", "4d"))}
        raw = session.run([session.get_outputs()[0].name], feed)[0]
    except Exception as e:
        if use_gpu and is_gpu_failure(e):
            logger.warning(f"Mapa de Profundidad: la GPU falló o se colgó ({e!r}) -- reintentando por CPU.")
            return estimate_depth(img, {**options, "depth_gpu": False}, progress_callback)
        raise

    depth = _to_near_bright(raw, model_info.get("output_kind", "disparity"))
    if options.get("depth_invert", False):
        depth = 1.0 - depth

    # Se amplía en coma flotante, antes de cuantizar: así la versión de 16 bits
    # conserva los degradados intermedios en vez de ampliar escalones de 8 bits.
    # (Sin el argumento mode= de fromarray, obsoleto en Pillow 12: el tipo del
    # array ya lo decide -- float32 2D -> "F", uint8 -> "L", uint16 -> "I;16".)
    full = Image.fromarray(depth.astype(np.float32)).resize((width, height), Image.Resampling.BICUBIC)
    values = np.clip(np.asarray(full), 0.0, 1.0)

    if alpha is not None:
        result = Image.fromarray((values * 255 + 0.5).astype(np.uint8))
        result.putalpha(alpha)
    elif options.get("depth_16bit", False):
        result = Image.fromarray((values * 65535 + 0.5).astype(np.uint16))
    else:
        result = Image.fromarray((values * 255 + 0.5).astype(np.uint8))
    return result, process_size
