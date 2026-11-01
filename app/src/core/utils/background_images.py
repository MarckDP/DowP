# src/core/utils/background_images.py
"""Imágenes de fondo elegidas por el usuario (Ajustes > Apariencia > Imagen de fondo).

Cada lugar tiene su propia imagen y sus ajustes, y DowP viene sin ninguna. Es un
ajuste del usuario, NO del tema: los temas se comparten como .json y una ruta de
imagen de otra PC no serviría.

Al elegir una imagen, DowP guarda su propia copia en <AppData>/DowP2/backgrounds,
reducida a un tamaño de pantalla: si el usuario mueve o borra el original no se
rompe nada, y una foto de 8K no se carga entera en cada arranque. Un PNG con
transparencia se guarda como PNG (para poner solo un personaje); una foto sin
transparencia, como JPEG. Las animadas (GIF/WebP) se guardan con su primer
fotograma: los fondos animados quedaron como idea aparte, por su consumo.

Sin Qt: el lienzo que dibuja (gui/widgets/background_canvas.py) y la transparencia
de los paneles (gui/styles.py, apply_glass) leen de aquí."""
import hashlib
import io
import shutil
import tempfile
import os

from core.logger.logger_manager import logger
from core.utils.config_manager import get_config, save_config
from core.utils.paths import get_app_data_dir

# Lugares. Fase 1: solo el fondo general de la ventana.
PLACE_GENERAL = "general"
PLACE_PREVIEWS = "previews"  # vistas previas sin ningún medio cargado
PLACES = (PLACE_GENERAL, PLACE_PREVIEWS)

# Modos de ajuste (como el fondo de pantalla de Windows).
FIT_FILL = "fill"          # cubre todo sin deformar; recorta lo que sobra
FIT_FIT = "fit"            # la imagen entera; el resto muestra el fondo del tema
FIT_STRETCH = "stretch"    # cubre todo deformando
FIT_ORIGINAL = "original"  # sin escalar
FIT_TILE = "tile"          # repetida
FITS = (FIT_FILL, FIT_FIT, FIT_STRETCH, FIT_ORIGINAL, FIT_TILE)

# Posición: (horizontal, vertical), cada una en "left/center/right" y "top/center/bottom".
ALIGNS = tuple(f"{v}-{h}" for v in ("top", "center", "bottom") for h in ("left", "center", "right"))

DEFAULT_OPACITY = 30          # % de la imagen sobre el color de fondo del tema
DEFAULT_PANEL_OPACITY = 80    # % de opacidad de los paneles con un fondo puesto
MIN_PANEL_OPACITY = 30        # por debajo, los paneles dejan de leerse

# Lado máximo de la copia guardada: el fondo cubre un 4K sin que pese de más; las vistas previas
# se ven pequeñas. Medido con PNG de 8K: el fondo queda en 1-4 MB y la vista previa en unos 0,2 MB.
MAX_SIDE = 3840
MAX_SIDE_PREVIEWS = 1080
IMAGE_QUALITY = 90

_CONFIG_KEY = "background_images"
_PANEL_KEY = "background_panel_opacity"
_PREVIEWS_KEY = "background_previews_transparent"
_CHECKER_KEY = "background_preview_checker"


def backgrounds_dir() -> str:
    path = os.path.join(get_app_data_dir(), "backgrounds")
    os.makedirs(path, exist_ok=True)
    return path


def default_settings(place: str = PLACE_GENERAL) -> dict:
    # "file": la copia de DowP; "name": el nombre del archivo que eligió el usuario.
    # Las vistas previas arrancan en Ajustar, a plena opacidad: suelen ser un personaje o
    # un logo, y sobre el panel no hace falta atenuarlos.
    previews = place == PLACE_PREVIEWS
    return {"file": "", "name": "", "opacity": 100 if previews else DEFAULT_OPACITY,
            "fit": FIT_FIT if previews else FIT_FILL, "align": "center-center", "blur": False}


def get_place(place: str) -> dict:
    """Ajustes de un lugar, siempre completos y válidos."""
    saved = (get_config().get(_CONFIG_KEY) or {}).get(place) or {}
    settings = default_settings(place)
    settings.update({k: v for k, v in saved.items() if k in settings})
    settings["opacity"] = max(0, min(100, int(settings["opacity"])))
    if settings["fit"] not in FITS:
        settings["fit"] = FIT_FILL
    if settings["align"] not in ALIGNS:
        settings["align"] = "center-center"
    settings["blur"] = bool(settings["blur"])
    return settings


def image_path(place: str) -> str | None:
    """Ruta de la copia de la imagen de ese lugar, o None si no tiene (o se borró)."""
    name = get_place(place)["file"]
    if not name:
        return None
    path = os.path.join(backgrounds_dir(), os.path.basename(name))
    return path if os.path.isfile(path) else None


def set_place(place: str, save: bool = True, **changes):
    """save=False solo cambia la config en memoria (mientras se arrastra un control
    deslizante); se guarda en disco al soltarlo."""
    config = get_config()
    all_places = dict(config.get(_CONFIG_KEY) or {})
    settings = get_place(place)
    settings.update(changes)
    all_places[place] = settings
    config[_CONFIG_KEY] = all_places
    if save:
        save_config(config)


def get_panel_opacity() -> int:
    value = get_config().get(_PANEL_KEY, DEFAULT_PANEL_OPACITY)
    try:
        return max(MIN_PANEL_OPACITY, min(100, int(value)))
    except (TypeError, ValueError):
        return DEFAULT_PANEL_OPACITY


def set_panel_opacity(value: int):
    config = get_config()
    config[_PANEL_KEY] = max(MIN_PANEL_OPACITY, min(100, int(value)))
    save_config(config)


def get_previews_transparent() -> bool:
    """Opción "Transparentar vistas previas": relleno y cuadrícula semitransparentes, como un
    panel. Desactivada por defecto: sólidos, y el fondo no se ve a través."""
    return bool(get_config().get(_PREVIEWS_KEY, False))


def set_previews_transparent(value: bool):
    config = get_config()
    config[_PREVIEWS_KEY] = bool(value)
    save_config(config)


def get_preview_checker() -> bool:
    """Opción "Mostrar cuadrícula de transparencia". Sin ella, las zonas transparentes de una
    imagen se ven sobre el relleno."""
    return bool(get_config().get(_CHECKER_KEY, True))


def set_preview_checker(value: bool):
    config = get_config()
    config[_CHECKER_KEY] = bool(value)
    save_config(config)


def glass_alpha() -> float | None:
    """Opacidad (0-1) que llevan los paneles, o None si no hace falta tocarlos: sin
    imagen de fondo general (o con los paneles al 100 %) todo queda como siempre."""
    if image_path(PLACE_GENERAL) is None:
        return None
    opacity = get_panel_opacity()
    return None if opacity >= 100 else opacity / 100.0


def max_side(place: str) -> int:
    return MAX_SIDE_PREVIEWS if place == PLACE_PREVIEWS else MAX_SIDE


def _webp_available() -> bool:
    """Con transparencia, WebP pesa unas 6 veces menos que PNG, pero Qt tiene que poder leerlo."""
    from PIL import features
    from PySide6.QtGui import QImageReader
    return features.check("webp") and b"webp" in [bytes(f) for f in QImageReader.supportedImageFormats()]


def prepare_frame(image, side: int):
    """El primer fotograma derecho, con transparencia solo si la usa y sin pasar de `side`."""
    from PIL import Image, ImageOps
    image.seek(0)
    frame = ImageOps.exif_transpose(image)  # fotos de celular giradas
    has_alpha = frame.mode in ("RGBA", "LA", "PA") or (frame.mode == "P" and "transparency" in frame.info)
    frame = frame.convert("RGBA" if has_alpha else "RGB")
    if has_alpha and frame.getextrema()[3][0] == 255:
        frame = frame.convert("RGB")  # canal alfa sin transparencia real
    if max(frame.size) > side:
        frame.thumbnail((side, side), Image.Resampling.LANCZOS)
    return frame


def encode_frame(frame, quality: int = IMAGE_QUALITY) -> tuple[bytes, str]:
    """(contenido, extensión con punto)."""
    out = io.BytesIO()
    if frame.mode != "RGBA":
        frame.save(out, "JPEG", quality=quality, optimize=True)
        return out.getvalue(), ".jpg"
    if _webp_available():
        frame.save(out, "WEBP", quality=quality, method=4, alpha_quality=100)
        return out.getvalue(), ".webp"
    frame.save(out, "PNG", optimize=True)
    return out.getvalue(), ".png"


def _copy_name(place: str, source: str, extension: str) -> str:
    digest = hashlib.sha1(f"{source}|{os.path.getsize(source)}|{os.path.getmtime(source)}".encode()).hexdigest()[:10]
    return f"{place}_{digest}{extension}"


def prepared_dir() -> str:
    return os.path.join(backgrounds_dir(), "preparadas")


def prepare_image(place: str, source: str) -> str:
    """Comprime `source` a una copia aparte y devuelve su ruta, sin tocar la configuración: se
    puede llamar desde otro hilo. La usa adopt_image al aplicar."""
    from PIL import Image
    with Image.open(source) as im:
        frame = prepare_frame(im, max_side(place))
    content, extension = encode_frame(frame)
    os.makedirs(prepared_dir(), exist_ok=True)
    handle, path = tempfile.mkstemp(prefix=f"{place}_", suffix=extension, dir=prepared_dir())
    with os.fdopen(handle, "wb") as f:
        f.write(content)
    return path


def discard_prepared(path: str | None = None):
    """Borra una copia preparada, o todas (las que quedaron de otra sesión) si no se indica."""
    if path:
        if os.path.dirname(os.path.abspath(path)) == os.path.abspath(prepared_dir()):
            _remove_quietly(path)
    else:
        shutil.rmtree(prepared_dir(), ignore_errors=True)


def adopt_image(place: str, source: str, display: str | None = None):
    """Usa una imagen ya preparada, como la que guarda un tema: se copia tal cual, porque
    comprimirla cada vez que se elige el tema le quitaría calidad y tardaría segundos."""
    name = _copy_name(place, source, os.path.splitext(source)[1].lower())
    dest = os.path.join(backgrounds_dir(), name)
    shutil.copyfile(source, dest)
    old = image_path(place)
    set_place(place, file=name, name=display or os.path.basename(source))
    if old and os.path.normpath(old) != os.path.normpath(dest):
        _remove_quietly(old)


def import_image(place: str, source: str) -> tuple[str, bool]:
    """Guarda la copia de `source` para `place` y la deja elegida. Devuelve (nombre
    de la copia, era_animada). Lanza si Pillow no puede abrir el archivo."""
    from PIL import Image

    with Image.open(source) as im:
        animated = bool(getattr(im, "is_animated", False)) and getattr(im, "n_frames", 1) > 1
        frame = prepare_frame(im, max_side(place))
    content, extension = encode_frame(frame)
    has_alpha = frame.mode == "RGBA"
    name = _copy_name(place, source, extension)
    dest = os.path.join(backgrounds_dir(), name)
    with open(dest, "wb") as f:
        f.write(content)

    old = image_path(place)
    set_place(place, file=name, name=os.path.basename(source))
    if old and os.path.normpath(old) != os.path.normpath(dest):
        _remove_quietly(old)
    logger.info(f"Fondo: imagen de '{place}' guardada ({frame.size[0]}x{frame.size[1]}, "
                f"{'con transparencia' if has_alpha else 'sin transparencia'}{', animada: primer fotograma' if animated else ''})")
    return name, animated


def remove_image(place: str):
    old = image_path(place)
    set_place(place, file="", name="")
    if old:
        _remove_quietly(old)


def _remove_quietly(path: str):
    try:
        os.remove(path)
    except OSError as e:
        logger.warning(f"Fondo: no se pudo borrar la copia vieja {path}: {e}")
