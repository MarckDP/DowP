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


def normalize_rgb_array(rgb: np.ndarray) -> np.ndarray:
    """Fotograma RGB uint8 (alto, ancho, 3) YA al tamaño de proceso -> tensor CHW
    normalizado con la media/desvío de ImageNet. Lo usa el Mapa de Profundidad de
    video (core/tabs/video_tools/video_depth_engine.py), que recibe los fotogramas ya
    escalados por ffmpeg en vez de una imagen de Pillow."""
    arr = rgb.astype(np.float32) / 255.0
    return ((arr - _IMAGENET_MEAN) / _IMAGENET_STD).transpose(2, 0, 1)


def raw_to_disparity(raw, output_kind: str):
    """Salida cruda del modelo -> mapa 2D de disparidad (cerca = valor alto), SIN
    normalizar. El video necesita la escala cruda para mantenerla estable entre
    fotogramas; la imagen normaliza enseguida (ver _to_near_bright)."""
    depth = np.squeeze(raw).astype(np.float32)
    if depth.ndim != 2:
        raise ValueError(f"forma de salida inesperada {tuple(np.shape(raw))}")
    if output_kind == "depth":
        # Profundidad real (cerca = valor bajo): la inversa la vuelve disparidad,
        # que es lo que devuelven los demás modelos y lo que se espera ver.
        depth = 1.0 / np.maximum(depth, 1e-6)
    if not np.isfinite(depth).all():
        raise ValueError("el modelo devolvió valores no numéricos")
    return depth


def _to_near_bright(raw, output_kind: str):
    """Salida cruda del modelo -> mapa 2D en 0..1 con cerca = 1."""
    depth = raw_to_disparity(raw, output_kind)
    lo, hi = float(depth.min()), float(depth.max())
    return (depth - lo) / (hi - lo + 1e-8)


def _moge_near_bright(session, rgb: Image.Image, detail: str, near_out: dict | None = None) -> np.ndarray:
    """Mapa 2D en 0..1 con cerca = 1 a partir de MoGe-2 (familia de NORMAL_MODEL_FAMILIES,
    ver models_setup.get_depth_families), al tamaño de trabajo de MoGe (lado mayor hasta
    1024 px). Usa la z de "points" (distancia a lo largo del eje de la cámara).

    A diferencia de los demás modelos no se pasa a 1/z: la profundidad de MoGe es real, y en
    una calle con alguien cerca 1/z deja a esa persona en blanco y toda la ciudad casi negra.
    Se usa -log(z), con el rango de los percentiles 1-99 (lo que queda fuera se satura), que
    reparte el gris entre lo cercano y lo lejano (comparado con fotos reales, 2026-09-30).
    Lo que no es superficie según su máscara (el cielo) queda en 0, lo más lejano.

    near_out, si se pasa, recibe además "points" (HxWx3 en metros, ejes de cámara OpenCV) y
    "mask" (HxW bool), al tamaño de trabajo -- los usa la Escena 3D (ver relief_mesh.py)."""
    from core.tabs.image_tools.normal_engine import MOGE_TOKENS, moge_outputs, moge_work_size

    work_size = moge_work_size(rgb.width, rgb.height)
    work = rgb if work_size == rgb.size else rgb.resize(work_size, Image.Resampling.LANCZOS)
    outputs = moge_outputs(session, np.asarray(work), MOGE_TOKENS.get(detail, MOGE_TOKENS["medium"]))
    z = outputs["points"][0][..., 2].astype(np.float32)
    valid = (outputs["mask"][0] > 0.5) & np.isfinite(z) & (z > 1e-6)
    if near_out is not None:
        # El ONNX de Large la llama "metric_scale" y el de Small "scale" (comprobado el
        # 2026-09-30); si faltara, la escena sale sin escala real pero con la forma bien.
        scale_out = outputs.get("metric_scale", outputs.get("scale"))
        scale = float(np.asarray(scale_out).ravel()[0]) if scale_out is not None else 1.0
        near_out["points"] = outputs["points"][0].astype(np.float32) * scale
        near_out["mask"] = valid
    depth = np.zeros_like(z)
    if not valid.any():
        return depth
    nearness = -np.log(z[valid])
    lo, hi = (float(v) for v in np.percentile(nearness, (1, 99)))
    depth[valid] = np.clip((nearness - lo) / (hi - lo + 1e-8), 0.0, 1.0)
    return depth


def estimate_depth(img: Image.Image, options: dict, progress_callback=None,
                   near_out: dict | None = None) -> tuple[Image.Image, tuple[int, int]]:
    """Calcula el mapa de profundidad de `img` según options (depth_family/
    depth_model/depth_gpu/depth_invert, y depth_detail solo con MoGe-2 -- ver
    DepthPopoverContent.get_settings(); y
    depth_16bit, que viene de las opciones de PNG/TIFF, ver ConvertPanel.get_settings()).
    near_out, si se pasa, recibe en "near" el mapa en coma flotante (0..1, cerca = 1, sin
    invertir, al tamaño de proceso) -- lo usa el relieve 3D (ver relief_mesh.py), que así no
    parte de la versión ya cuantizada a 8 bits.
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
    is_moge = model_info.get("engine") == "moge"
    detail = options.get("depth_detail", "medium")
    if is_moge:
        from core.tabs.image_tools.normal_engine import get_process_size as moge_process_size
        process_size = moge_process_size(model_info, width, height, detail)
    else:
        process_size = get_process_size(model_info, width, height)

    try:
        session = onnx_sessions.get_session(get_depth_model_path(model_info), use_gpu, label="Mapa de Profundidad")
        if is_moge:
            depth = _moge_near_bright(session, img.convert("RGB"), detail, near_out)
        else:
            feed = {session.get_inputs()[0].name: _preprocess(img.convert("RGB"), process_size,
                                                              model_info.get("input_layout", "4d"))}
            raw = session.run([session.get_outputs()[0].name], feed)[0]
    except Exception as e:
        if use_gpu and is_gpu_failure(e):
            logger.warning(f"Mapa de Profundidad: la GPU falló o se colgó ({e!r}) -- reintentando por CPU.")
            return estimate_depth(img, {**options, "depth_gpu": False}, progress_callback, near_out)
        raise

    if not is_moge:
        depth = _to_near_bright(raw, model_info.get("output_kind", "disparity"))
    if near_out is not None:
        near_out["near"] = depth
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
