# src/core/tabs/image_tools/normal_engine.py
"""Motor de "Mapa de Normales" -- dos motores ONNX en un mismo módulo, elegidos por el
campo "engine" de cada entrada de NORMAL_MODEL_FAMILIES (core/constants.py):

  - "moge"     MoGe-2 (Microsoft, MIT): normales de una ESCENA o foto, en el espacio de la
               cámara. Salida en la convención OpenGL de Blender/DaVinci: R = derecha,
               G = arriba, B = hacia el espectador. Lo que no es superficie (el cielo) sale
               como plano frontal, (0, 0, 1).
  - "deepbump" DeepBump (Hugo Tini, GPL-3.0): normal map de una TEXTURA plana a partir de su
               brillo, para materiales 3D. Trabaja por bloques de 256 px con solape.

Convenciones que se comprobaron con los modelos reales (2026-09-19):
  - MoGe-2 quiere la imagen en [0, 1]; con normalización ImageNet las normales salen
    deformadas. Devuelve normales unitarias con ejes tipo OpenCV (x derecha, y abajo, z
    hacia dentro de la escena): una superficie que mira a la cámara tiene z < 0.
  - DeepBump ya produce la convención OpenGL (G positivo = luz desde arriba).

El troceado y la mezcla de bloques de DeepBump son implementación propia (ventana de
pesos lineal en el solape), no el código del autor.

Si la imagen trae canal alfa (por ejemplo, porque Eliminar Fondo corrió antes en el mismo
lote), el mapa lo conserva: sale solo la superficie del sujeto."""
import numpy as np
from PIL import Image

from core.logger.logger_manager import logger
from core.setup.models_setup import get_normal_families, get_normal_model_path, is_normal_model_installed
from core.utils import onnx_sessions
from core.utils.onnx_providers import is_gpu_failure
from PySide6.QtCore import QCoreApplication

# MoGe-2 -------------------------------------------------------------------------------
# Nivel de detalle -> tokens ViT (los autores sugieren 1200-2500). Más tokens = más
# detalle y más tiempo/memoria.
MOGE_TOKENS = {"low": 1200, "medium": 1800, "high": 2500}
_MOGE_PATCH = 14
# El modelo remuestrea la entrada a su propia rejilla de tokens (~800 px de lado con 2500
# tokens), así que pasarle una foto de 4K solo infla la memoria de sus tres salidas sin
# darle más detalle. Se limita el lado mayor y las normales se amplían después.
_MOGE_MAX_SIDE = 1024

# DeepBump -----------------------------------------------------------------------------
_DEEPBUMP_TILE = 256
DEEPBUMP_OVERLAPS = {"small": _DEEPBUMP_TILE // 6, "medium": _DEEPBUMP_TILE // 4, "large": _DEEPBUMP_TILE // 2}


def _model_info(family: str | None, model: str | None) -> dict | None:
    if not family or not model:
        return None
    return get_normal_families().get(family, {}).get(model)


def get_process_size(model_info: dict, width: int, height: int, detail: str = "medium") -> tuple[int, int] | None:
    """(ancho, alto) aproximado al que MoGe-2 calcula las normales, o None si el motor
    trabaja a la resolución completa (DeepBump). Sale de la fórmula de los propios autores:
    con N tokens y proporción a = ancho/alto, la rejilla es sqrt(N/a) x sqrt(N*a) parches
    de 14 px. Es aproximada (el redondeo exacto no está documentado) y solo sirve para el
    aviso "calculado" del Editor de Imagen."""
    if model_info.get("engine") != "moge":
        return None
    tokens = MOGE_TOKENS.get(detail, MOGE_TOKENS["medium"])
    aspect = width / max(1, height)
    grid_h, grid_w = (tokens / aspect) ** 0.5, (tokens * aspect) ** 0.5
    return int(round(grid_w)) * _MOGE_PATCH, int(round(grid_h)) * _MOGE_PATCH


def prepare_session(options: dict) -> None:
    """Precarga la sesión ONNX antes de arrancar un lote -- ver depth_engine.prepare_session()."""
    if not options.get("normals_enabled", False):
        return
    model_info = _model_info(options.get("normals_family"), options.get("normals_model"))
    if not model_info or not is_normal_model_installed(model_info):
        return
    try:
        onnx_sessions.get_session(get_normal_model_path(model_info), options.get("normals_gpu", True),
                                  label="Mapa de Normales")
    except Exception as e:
        logger.warning(f"Mapa de Normales: no se pudo precargar la sesión ({e}) -- se reintentará por imagen.")


# ═════════════════════════════════════════════════════════════════════════════
# MoGe-2 -- normales de escena
# ═════════════════════════════════════════════════════════════════════════════

def _resize_float(channel: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """Amplía un canal float32 2D a (ancho, alto) con interpolación bicúbica."""
    return np.asarray(Image.fromarray(np.ascontiguousarray(channel, dtype=np.float32)).resize(
        size, Image.Resampling.BICUBIC), dtype=np.float32)


def _encode_normals(vectors: np.ndarray) -> np.ndarray:
    """Vectores unitarios HxWx3 en [-1, 1] -> uint8 HxWx3 (0.5 + 0.5 * n)."""
    return ((vectors * 0.5 + 0.5).clip(0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


def moge_work_size(width: int, height: int) -> tuple[int, int]:
    """Tamaño al que se le pasa la imagen a MoGe-2: lado mayor limitado a _MOGE_MAX_SIDE."""
    scale = min(1.0, _MOGE_MAX_SIDE / max(width, height))
    if scale >= 1.0:
        return width, height
    return max(1, round(width * scale)), max(1, round(height * scale))


def moge_tokens(options: dict) -> int:
    return MOGE_TOKENS.get(options.get("normals_detail", "medium"), MOGE_TOKENS["medium"])


def moge_vectors(session, rgb: np.ndarray, tokens: int) -> np.ndarray:
    """Normales (HxWx3 float32 unitarios, convención OpenGL) de un RGB uint8 HxWx3 ya al
    tamaño de trabajo (ver moge_work_size). Las usan el Editor de Imagen y el Mapa de
    Normales de video (core/tabs/video_tools/video_normal_engine.py)."""
    tensor = (np.asarray(rgb, dtype=np.float32) / 255.0).transpose(2, 0, 1)[None]
    outputs = session.run(None, {"image": np.ascontiguousarray(tensor, dtype=np.float32),
                                 "num_tokens": np.array(tokens, dtype=np.int64)})
    by_name = dict(zip((o.name for o in session.get_outputs()), outputs))
    normal, mask = by_name["normal"][0], by_name["mask"][0]     # HxWx3 y HxW, al tamaño de entrada

    # cámara (x derecha, y abajo, z hacia dentro) -> OpenGL (x derecha, y arriba, z hacia ti)
    vectors = np.stack([normal[..., 0], -normal[..., 1], -normal[..., 2]], axis=-1)
    # sin superficie (cielo, huecos): plano frontal en vez de un vector nulo
    vectors = np.where((mask > 0.5)[..., None], vectors, np.array([0.0, 0.0, 1.0], np.float32))
    return vectors.astype(np.float32)


def resize_vectors(vectors: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """Amplía un campo de normales a (ancho, alto) y lo vuelve a normalizar: interpolar
    vectores unitarios (o mezclarlos, como el suavizado del video) deja vectores algo
    más cortos. Si ya tiene ese tamaño, solo normaliza."""
    if (vectors.shape[1], vectors.shape[0]) != tuple(size):
        vectors = np.stack([_resize_float(vectors[..., c], size) for c in range(3)], axis=-1)
    vectors = vectors / np.maximum(np.linalg.norm(vectors, axis=-1, keepdims=True), 1e-6)
    return vectors.astype(np.float32)


def _run_moge(session, rgb: Image.Image, options: dict) -> np.ndarray:
    width, height = rgb.size
    work_size = moge_work_size(width, height)
    work = rgb if work_size == (width, height) else rgb.resize(work_size, Image.Resampling.LANCZOS)
    vectors = moge_vectors(session, np.asarray(work), moge_tokens(options))
    if work_size != (width, height):
        vectors = resize_vectors(vectors, (width, height))
    return vectors


# ═════════════════════════════════════════════════════════════════════════════
# DeepBump -- normal map de una textura
# ═════════════════════════════════════════════════════════════════════════════

def _run_deepbump(session, rgb: Image.Image, options: dict) -> np.ndarray:
    """Trocea la imagen en bloques de 256 px con solape, predice las normales de cada bloque
    y los mezcla con una ventana lineal en el solape. Devuelve HxWx3 float32 en [-1, 1]."""
    gray = np.asarray(rgb, dtype=np.float32).mean(axis=2) / 255.0
    height, width = gray.shape
    overlap = DEEPBUMP_OVERLAPS.get(options.get("normals_overlap", "medium"), DEEPBUMP_OVERLAPS["medium"])
    tile, stride = _DEEPBUMP_TILE, _DEEPBUMP_TILE - overlap

    # Un margen de un solape por lado (así los bordes también se promedian entre bloques),
    # y relleno hasta que quepa un número entero de bloques. "wrap" continúa la textura
    # por el lado contrario (correcto si es repetible); "reflect" la refleja.
    pad_mode = "wrap" if options.get("normals_tileable", True) else "reflect"
    extra_h = max(0, -(-max(height + 2 * overlap - tile, 0) // stride) * stride + tile - (height + 2 * overlap))
    extra_w = max(0, -(-max(width + 2 * overlap - tile, 0) // stride) * stride + tile - (width + 2 * overlap))
    padded = np.pad(gray, ((overlap, overlap + extra_h), (overlap, overlap + extra_w)), mode=pad_mode)
    full_h, full_w = padded.shape

    ramp = np.ones(tile, dtype=np.float32)
    if overlap:
        rise = (np.arange(overlap, dtype=np.float32) + 1) / (overlap + 1)
        ramp[:overlap], ramp[-overlap:] = rise, rise[::-1]
    window = np.outer(ramp, ramp)

    accum = np.zeros((3, full_h, full_w), dtype=np.float32)
    weights = np.zeros((full_h, full_w), dtype=np.float32)
    input_name = session.get_inputs()[0].name
    for y in range(0, full_h - tile + 1, stride):
        for x in range(0, full_w - tile + 1, stride):
            block = padded[y:y + tile, x:x + tile][None, None]
            predicted = session.run(None, {input_name: block})[0][0]        # 3 x 256 x 256, en [0, 1]
            accum[:, y:y + tile, x:x + tile] += predicted * window
            weights[y:y + tile, x:x + tile] += window

    merged = (accum / np.maximum(weights, 1e-6))[:, overlap:overlap + height, overlap:overlap + width]
    vectors = (merged - 0.5).transpose(1, 2, 0) * 2.0
    vectors /= np.maximum(np.linalg.norm(vectors, axis=-1, keepdims=True), 1e-6)
    return vectors.astype(np.float32)


# ═════════════════════════════════════════════════════════════════════════════
# Punto de entrada
# ═════════════════════════════════════════════════════════════════════════════

def estimate_normals(img: Image.Image, options: dict, progress_callback=None) -> tuple[Image.Image, tuple[int, int] | None]:
    """Calcula el mapa de normales de `img` según options (normals_family/normals_model/
    normals_gpu/normals_directx/normals_detail/normals_overlap/normals_tileable -- ver
    NormalPopoverContent.get_settings()). Devuelve (mapa RGB, o RGBA si `img` traía alfa;
    (ancho, alto) al que se calculó, o None si fue a resolución completa)."""
    model_info = _model_info(options.get("normals_family"), options.get("normals_model"))
    if not model_info:
        raise ValueError(QCoreApplication.translate("normal_engine", "Mapa de Normales: no hay un modelo de IA seleccionado."))
    if not is_normal_model_installed(model_info):
        raise FileNotFoundError(
            QCoreApplication.translate("normal_engine", "El modelo '{0}' no está instalado -- ve a Ajustes > Modelos para descargarlo.")
            .format(options.get("normals_model"))
        )

    use_gpu = options.get("normals_gpu", True)
    if progress_callback:
        progress_callback(None)     # sin avance real que contar (ver depth_engine.estimate_depth)

    alpha = img.getchannel("A") if img.mode in ("RGBA", "LA", "PA") else None
    rgb = img.convert("RGB")
    detail = options.get("normals_detail", "medium")
    process_size = get_process_size(model_info, rgb.width, rgb.height, detail)

    try:
        session = onnx_sessions.get_session(get_normal_model_path(model_info), use_gpu, label="Mapa de Normales")
        runner = _run_moge if model_info.get("engine") == "moge" else _run_deepbump
        vectors = runner(session, rgb, options)
    except Exception as e:
        if use_gpu and is_gpu_failure(e):
            logger.warning(f"Mapa de Normales: la GPU falló o se colgó ({e!r}) -- reintentando por CPU.")
            return estimate_normals(img, {**options, "normals_gpu": False}, progress_callback)
        raise

    if options.get("normals_directx", False):
        vectors = vectors * np.array([1.0, -1.0, 1.0], dtype=np.float32)      # DirectX: canal verde invertido
    result = Image.fromarray(_encode_normals(vectors))
    if alpha is not None:
        result.putalpha(alpha)
    return result, process_size
