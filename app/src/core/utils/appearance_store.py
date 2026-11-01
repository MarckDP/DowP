"""Apariencias guardadas: un tema de usuario que además recuerda imágenes, opacidades, letra y
redondez. Lo que no es color vive en su clave "apariencia" y las imágenes en <id>_assets/, junto
al JSON, porque backgrounds/ solo guarda una copia por lugar y la borra al elegir otra."""
import os
import shutil

from core.logger.logger_manager import logger
from core.utils import background_images as bg
from core.utils import theme_io, theme_loader as TL
from core.utils.config_manager import get_config, save_config

_KEY = "apariencia"
_CONFIG_KEYS = ("font_family", "font_size_override", "radius_override")
_PLACE_SETTINGS = ("name", "opacity", "fit", "align", "blur")
FONTS_FOLDER = "fuentes"  # dentro de <id>_assets, solo en temas instalados desde un paquete


def assets_dir(theme_id: str) -> str:
    return theme_io.user_theme_path(theme_id)[:-len(".json")] + "_assets"


def capture() -> dict:
    """Lo actual que no son colores. Las imágenes van por nombre: su copia la hace save()."""
    config = get_config()
    places = {}
    for place in bg.PLACES:
        if bg.image_path(place):
            settings = bg.get_place(place)
            places[place] = {k: settings[k] for k in _PLACE_SETTINGS}
    return {"panel_opacity": bg.get_panel_opacity(), "previews_transparent": bg.get_previews_transparent(),
            "preview_checker": bg.get_preview_checker(),
            **{k: config.get(k) for k in _CONFIG_KEYS}, "places": places}


def has_appearance(theme_id: str) -> bool:
    return isinstance(TL.read_theme(theme_id).get(_KEY), dict)


def saved_place(theme_id: str, place: str) -> tuple[str, dict] | None:
    """(ruta, ajustes) de la imagen que traería esa apariencia en ese lugar, si trae."""
    settings = (TL.read_theme(theme_id).get(_KEY) or {}).get("places", {}).get(place)
    path = os.path.join(assets_dir(theme_id), os.path.basename(settings["file"])) if settings and settings.get("file") else None
    return (path, settings) if path and os.path.isfile(path) else None


def preview_image(theme_id: str) -> str | None:
    """La imagen de fondo que traería esa apariencia."""
    saved = saved_place(theme_id, bg.PLACE_GENERAL)
    return saved[0] if saved else None


def save(theme_id: str, name: str, source_theme: str) -> str:
    """Guarda colores de `source_theme` y todo lo demás en `theme_id` (lo reemplaza si existe)."""
    data = theme_io.build_export(source_theme)
    data["meta"] = dict(data["meta"], nombre=name, autor="DowP")
    # Lo elegido en Ajustes va en la apariencia, no aquí: "Según el tema" debe volver a lo que el
    # tema trae, y no a lo último que se guardó.
    own = TL.resolve_shapes(source_theme, use_overrides=False)
    data["formas"] = {k: own[k] for k in data["formas"]}
    data["tipografia"] = {"tamano": own["tamano_fuente"]}
    family = TL.get_theme_font(source_theme)
    if family:
        data["tipografia"]["familia"] = family
    appearance = capture()
    # Se copia a una carpeta nueva y luego se reemplaza: la vieja puede ser el origen.
    final = assets_dir(theme_id)
    temporary = final + "_nuevo"
    shutil.rmtree(temporary, ignore_errors=True)
    os.makedirs(temporary)
    for place, settings in appearance["places"].items():
        source = bg.image_path(place)
        file_name = place + os.path.splitext(source)[1]
        shutil.copyfile(source, os.path.join(temporary, file_name))
        settings["file"] = file_name
    fonts = os.path.join(final, FONTS_FOLDER)
    if os.path.isdir(fonts):
        shutil.copytree(fonts, os.path.join(temporary, FONTS_FOLDER))
    shutil.rmtree(final, ignore_errors=True)
    os.replace(temporary, final)
    data[_KEY] = appearance
    theme_io.save_imported(theme_id, data)
    logger.info(f"Apariencia guardada en '{theme_id}'")
    return theme_id


def _install_fonts(theme_id: str):
    """Las fuentes de un paquete se registran recién aquí, al aplicar el tema."""
    folder = os.path.join(assets_dir(theme_id), FONTS_FOLDER)
    if not os.path.isdir(folder):
        return
    from core.utils.font_manager import _register_font_file
    from core.utils.paths import get_user_fonts_dir
    target = get_user_fonts_dir()
    os.makedirs(target, exist_ok=True)
    for name in os.listdir(folder):
        dest = os.path.join(target, name)
        if not os.path.exists(dest):
            shutil.copyfile(os.path.join(folder, name), dest)
        _register_font_file(dest, is_user=True)


def restore(theme_id: str):
    """Deja activo lo que guarda esa apariencia. Quien llama recarga los estilos."""
    appearance = TL.read_theme(theme_id).get(_KEY)
    if not isinstance(appearance, dict):
        return
    _install_fonts(theme_id)
    config = get_config()
    for key in _CONFIG_KEYS:
        if appearance.get(key) is None:
            config.pop(key, None)
        else:
            config[key] = appearance[key]
    save_config(config)
    bg.set_panel_opacity(appearance.get("panel_opacity", bg.get_panel_opacity()))
    bg.set_previews_transparent(bool(appearance.get("previews_transparent", False)))
    bg.set_preview_checker(bool(appearance.get("preview_checker", True)))
    places = appearance.get("places", {})
    for place in bg.PLACES:
        settings = places.get(place)
        path = os.path.join(assets_dir(theme_id), os.path.basename(settings.get("file", ""))) if settings else None
        if not path or not os.path.isfile(path):
            bg.remove_image(place)
            continue
        bg.adopt_image(place, path)
        bg.set_place(place, **{k: settings[k] for k in _PLACE_SETTINGS if k in settings})
