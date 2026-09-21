# src/core/tabs/image_tools/rembg_engine.py
"""Motor de "Eliminar Fondo IA" -- corre los modelos ONNX de REMBG_MODEL_FAMILIES
(core/constants.py) directo con onnxruntime, sin pasar por la librería `rembg` de
PyPI: DowP1 la importaba (image_converter.pyc, `_load_rembg_lazy`) pero nunca
llegó a invocar su API real para inferir -- import muerto, confirmado revisando
el decompilado completo. Todo el trabajo pasaba (y aquí también) por
onnxruntime.InferenceSession crudo con pre/post-procesado manual.

Un solo pipeline para las 4 familias (Standard U2Net, BiRefNet, RMBG 2.0,
InSPyReNet) en vez de dos casi-iguales como tenía DowP1 (_process_onnx_manual /
_process_high_res_onnx): la única diferencia real entre modelos es el tamaño de
entrada, y eso ya lo declara cada entrada de REMBG_MODEL_FAMILIES vía
"input_size" -- ver la nota de ese diccionario en core/constants.py. Agregar un
modelo nuevo no toca este archivo."""
import os

from PIL import Image, ImageFilter

from core.logger.logger_manager import logger
from core.setup.models_setup import get_all_rembg_families
from core.utils import onnx_sessions
from core.utils.onnx_providers import is_gpu_failure
from core.utils.paths import get_models_dir
from PySide6.QtCore import QCoreApplication

_DEFAULT_INPUT_SIZE = (1024, 1024)
_IMAGENET_MEAN = (0.485, 0.456, 0.406)
_IMAGENET_STD = (0.229, 0.224, 0.225)

# Las sesiones ONNX cacheadas viven en core/utils/onnx_sessions.py, compartidas
# con Mapa de Profundidad (depth_engine.py): "Liberar" y el límite de modelos en
# memoria de Ajustes > Modelos tienen que cubrir a los dos motores a la vez.
# loaded_session_count()/clear_sessions() siguen existiendo aquí con el mismo
# nombre porque es lo que ya llaman ImageConvertWorker y models_page.py.


def _model_info(family: str | None, model: str | None) -> dict | None:
    if not family or not model:
        return None
    return get_all_rembg_families().get(family, {}).get(model)


def _model_path(model_info: dict) -> str:
    return os.path.join(get_models_dir(), model_info.get("folder", "rembg"), model_info["file"])


def _get_session(model_path: str, use_gpu: bool):
    return onnx_sessions.get_session(model_path, use_gpu, label="Eliminar Fondo")


def prepare_session(options: dict) -> None:
    """Precarga la sesión ONNX antes de arrancar un lote -- evita que la primera
    imagen pague sola el costo de inicialización (carga de pesos + compilación
    del grafo, que con modelos de 1024x1024 puede ser varios segundos)."""
    if not options.get("rembg_enabled", False):
        return
    model_info = _model_info(options.get("rembg_family"), options.get("rembg_model"))
    if not model_info:
        return
    model_path = _model_path(model_info)
    if not os.path.exists(model_path):
        return
    try:
        _get_session(model_path, options.get("rembg_gpu", True))
    except Exception as e:
        logger.warning(f"Eliminar Fondo: no se pudo precargar la sesión ({e}) -- se reintentará por imagen.")


def loaded_session_count() -> int:
    """Ver onnx_sessions.loaded_session_count() -- cuenta las sesiones de TODOS
    los motores ONNX, no solo las de Eliminar Fondo."""
    return onnx_sessions.loaded_session_count()


def clear_sessions() -> int:
    """Ver onnx_sessions.clear_sessions() -- libera las sesiones de TODOS los
    motores ONNX (Eliminar Fondo y Mapa de Profundidad)."""
    return onnx_sessions.clear_sessions()


def _preprocess(img: Image.Image, size: tuple[int, int]):
    import numpy as np
    rgb = img.convert("RGB")
    resized = rgb.resize(size, Image.Resampling.BILINEAR)
    arr = np.asarray(resized).astype(np.float32) / 255.0
    mean = np.array(_IMAGENET_MEAN, dtype=np.float32)
    std = np.array(_IMAGENET_STD, dtype=np.float32)
    arr = (arr - mean) / std
    arr = arr.transpose(2, 0, 1)  # HWC -> CHW
    return np.expand_dims(arr, 0).astype(np.float32)


def _postprocess_mask(raw_mask, orig_size: tuple[int, int]) -> Image.Image:
    """raw_mask: array 2D de un solo canal, salida cruda del modelo (puede venir
    ya en 0..1 o como logits sin activación final según la arquitectura -- ver
    nota de unificación en el docstring del módulo)."""
    import numpy as np
    min_val, max_val = float(raw_mask.min()), float(raw_mask.max())
    if min_val < -1.0 or max_val > 1.5:
        mask = 1.0 / (1.0 + np.exp(-raw_mask))
    else:
        mask = raw_mask
    mask = (mask - mask.min()) / (mask.max() - mask.min() + 1e-8)
    mask = (mask * 255).astype(np.uint8)
    mask_img = Image.fromarray(mask, mode="L")
    return mask_img.resize(orig_size, Image.Resampling.LANCZOS)


def _run_inference(session, model_info: dict, img: Image.Image) -> Image.Image:
    size = tuple(model_info.get("input_size") or _DEFAULT_INPUT_SIZE)
    orig_size = img.size
    input_tensor = _preprocess(img, size)
    input_name = session.get_inputs()[0].name
    result = session.run(None, {input_name: input_tensor})
    mask_img = _postprocess_mask(result[0][0, 0], orig_size)
    final = img.convert("RGBA")
    final.putalpha(mask_img)
    return final


def apply_alpha_postprocess(img: Image.Image, smooth_px: int = 0, expand_px: int = 0) -> Image.Image:
    """Post-procesa el canal alfa tras Eliminar Fondo: smooth_px difumina el
    borde del recorte (GaussianBlur), expand_px positivo expande/dilata (MaxFilter,
    recupera bordes cortados), negativo contrae/erosiona (MinFilter, elimina halos).
    Portado 1:1 de DowP1 (image_converter.pyc::_apply_alpha_postprocess)."""
    if not smooth_px and not expand_px:
        return img
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    r, g, b, alpha = img.split()
    if expand_px:
        size = abs(expand_px) * 2 + 1
        alpha = alpha.filter(ImageFilter.MaxFilter(size) if expand_px > 0 else ImageFilter.MinFilter(size))
    if smooth_px > 0:
        alpha = alpha.filter(ImageFilter.GaussianBlur(radius=smooth_px))
    return Image.merge("RGBA", (r, g, b, alpha))


def remove_background(img: Image.Image, options: dict, progress_callback=None) -> Image.Image:
    """Elimina el fondo de `img` según options (rembg_enabled/rembg_family/
    rembg_model/rembg_gpu -- ver RembgPopoverContent.get_settings()). Si la GPU
    falla por un error conocido de DirectML (driver colgado/timeout), reintenta
    automáticamente por CPU en vez de tirar abajo la conversión entera -- mismo
    criterio validado en producción por DowP1 (ver DML_FAILURE_HINTS)."""
    model_info = _model_info(options.get("rembg_family"), options.get("rembg_model"))
    if not model_info:
        raise ValueError(QCoreApplication.translate("rembg_engine", "Eliminar Fondo: no hay un modelo de IA seleccionado."))

    model_path = _model_path(model_info)
    if not os.path.exists(model_path):
        model_name = options.get("rembg_model")
        raise FileNotFoundError(
            QCoreApplication.translate("rembg_engine", "El modelo '{0}' no está instalado -- ve a Ajustes > Modelos para descargarlo.").format(model_name)
        )

    use_gpu = options.get("rembg_gpu", True)
    if progress_callback:
        # Sin progreso incremental real que reportar -- una sola llamada a
        # session.run() por imagen, no hay mosaicos ni "N de M" que contar
        # (a diferencia de Upscayl, ver upscale_engine.py). None = estado
        # "trabajando" indeterminado para quien consuma el callback.
        progress_callback(None)

    try:
        session = _get_session(model_path, use_gpu)
        return _run_inference(session, model_info, img)
    except Exception as e:
        if use_gpu and is_gpu_failure(e):
            logger.warning(f"Eliminar Fondo: la GPU falló o se colgó ({e}) -- reintentando por CPU.")
            return remove_background(img, {**options, "rembg_gpu": False}, progress_callback)
        raise
