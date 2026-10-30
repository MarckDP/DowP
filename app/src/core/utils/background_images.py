# src/core/utils/background_images.py
"""Imágenes de fondo elegidas por el usuario (Ajustes > General > Imagen de fondo).

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
import os

from core.logger.logger_manager import logger
from core.utils.config_manager import get_config, save_config
from core.utils.paths import get_app_data_dir

# Lugares. Fase 1: solo el fondo general de la ventana.
PLACE_GENERAL = "general"
PLACES = (PLACE_GENERAL,)

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

# Lado máximo de la copia guardada: cubre un 4K sin que pese de más.
MAX_SIDE = 3840

_CONFIG_KEY = "background_images"
_PANEL_KEY = "background_panel_opacity"


def backgrounds_dir() -> str:
    path = os.path.join(get_app_data_dir(), "backgrounds")
    os.makedirs(path, exist_ok=True)
    return path


def default_settings() -> dict:
    # "file": la copia de DowP; "name": el nombre del archivo que eligió el usuario.
    return {"file": "", "name": "", "opacity": DEFAULT_OPACITY, "fit": FIT_FILL, "align": "center-center",
            "blur": False}


def get_place(place: str) -> dict:
    """Ajustes de un lugar, siempre completos y válidos."""
    saved = (get_config().get(_CONFIG_KEY) or {}).get(place) or {}
    settings = default_settings()
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


def glass_alpha() -> float | None:
    """Opacidad (0-1) que llevan los paneles, o None si no hace falta tocarlos: sin
    imagen de fondo general (o con los paneles al 100 %) todo queda como siempre."""
    if image_path(PLACE_GENERAL) is None:
        return None
    opacity = get_panel_opacity()
    return None if opacity >= 100 else opacity / 100.0


def import_image(place: str, source: str) -> tuple[str, bool]:
    """Guarda la copia de `source` para `place` y la deja elegida. Devuelve (nombre
    de la copia, era_animada). Lanza si Pillow no puede abrir el archivo."""
    from PIL import Image, ImageOps

    with Image.open(source) as im:
        animated = bool(getattr(im, "is_animated", False)) and getattr(im, "n_frames", 1) > 1
        im.seek(0)
        frame = ImageOps.exif_transpose(im)  # fotos de celular giradas
        has_alpha = frame.mode in ("RGBA", "LA", "PA") or (frame.mode == "P" and "transparency" in frame.info)
        frame = frame.convert("RGBA" if has_alpha else "RGB")
        if has_alpha and frame.getextrema()[3][0] == 255:
            frame, has_alpha = frame.convert("RGB"), False  # canal alfa sin transparencia real
        if max(frame.size) > MAX_SIDE:
            frame.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)

        digest = hashlib.sha1(f"{source}|{os.path.getsize(source)}|{os.path.getmtime(source)}".encode()).hexdigest()[:10]
        name = f"{place}_{digest}.{'png' if has_alpha else 'jpg'}"
        dest = os.path.join(backgrounds_dir(), name)
        if has_alpha:
            frame.save(dest, "PNG", optimize=True)
        else:
            frame.save(dest, "JPEG", quality=92, optimize=True)

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
