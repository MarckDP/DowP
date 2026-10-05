# src/core/utils/font_manager.py
"""
Gestor Centralizado de Tipografías para DowP 2.0
=================================================
Maneja el escaneo, registro en QFontDatabase y resolución de la fuente activa
tanto para fuentes empaquetadas en assets/fonts como para fuentes personalizadas
agregadas por el usuario en %APPDATA%/DowP2/fonts.
"""
import os
from PySide6.QtGui import QFontDatabase
from core.logger.logger_manager import logger
from core.utils.paths import get_src_dir, get_user_fonts_dir, get_app_data_dir
from core.utils.config_manager import get_config

# Pesos estándar ofrecidos en el selector de marca de agua (nombre, valor de eje 'wght').
STANDARD_WEIGHTS = [
    ("Thin", 100), ("Extra Light", 200), ("Light", 300), ("Regular", 400),
    ("Medium", 500), ("Semi Bold", 600), ("Bold", 700), ("Extra Bold", 800), ("Black", 900),
]
_FONT_CACHE_DIR = None

# Cache de familias detectadas y registradas
_REGISTERED_FAMILIES = []
_REGISTERED_FILE_PATHS = set()
_INITIALIZED_FULL = False
# Familia -> ruta absoluta del .ttf/.otf que la registró. QFontDatabase solo expone
# nombres de familia (registro en memoria de la app, no instalado a nivel de SO), pero
# ffmpeg (drawtext=fontfile=...) necesita la ruta real del archivo — ver watermark_builder.py.
_FAMILY_TO_PATH = {}

DEFAULT_FALLBACK_FONT = "Google Sans Flex"
PRIORITY_FAMILIES = [
    "Google Sans Flex", "Google Sans", "Raleway", "Roboto",
    "Inter", "Outfit", "Plus Jakarta Sans", "JetBrains Mono"
]


def _register_font_file(font_path: str, is_user: bool = False) -> str:
    """Registra un archivo de fuente individual (.ttf/.otf) en QFontDatabase si aún no ha sido registrado."""
    if not font_path or not os.path.isfile(font_path) or font_path in _REGISTERED_FILE_PATHS:
        return ""

    try:
        font_id = QFontDatabase.addApplicationFont(font_path)
        if font_id != -1:
            fams = QFontDatabase.applicationFontFamilies(font_id)
            if fams:
                primary_family = fams[0]
                _FAMILY_TO_PATH.setdefault(primary_family, font_path)
                if primary_family not in _REGISTERED_FAMILIES:
                    _REGISTERED_FAMILIES.append(primary_family)
                _REGISTERED_FILE_PATHS.add(font_path)
                prefix = "Usuario" if is_user else "Interna"
                logger.debug(f"FontManager: [{prefix}] Fuente registrada: {primary_family} ({os.path.basename(font_path)})")
                return primary_family
            else:
                logger.warning(f"FontManager: No se detectaron familias para {font_path}")
        else:
            logger.warning(f"FontManager: No se pudo registrar {font_path} (archivo corrupto o formato no soportado)")
    except Exception as e:
        logger.error(f"FontManager: Error al registrar fuente {font_path}: {e}")
    return ""


def _scan_all_fonts():
    """Escanea y registra todas las fuentes (.ttf, .otf) empaquetadas y de usuario."""
    global _INITIALIZED_FULL

    if _INITIALIZED_FULL:
        return

    # 1. Fuentes empaquetadas
    builtin_fonts_dir = os.path.join(get_src_dir(), "assets", "fonts")
    if os.path.isdir(builtin_fonts_dir):
        for file_name in os.listdir(builtin_fonts_dir):
            if file_name.lower().endswith((".ttf", ".otf")):
                _register_font_file(os.path.join(builtin_fonts_dir, file_name), is_user=False)

    # 2. Fuentes de usuario en AppData
    user_fonts_dir = get_user_fonts_dir()
    if os.path.isdir(user_fonts_dir):
        for file_name in os.listdir(user_fonts_dir):
            if file_name.lower().endswith((".ttf", ".otf")):
                _register_font_file(os.path.join(user_fonts_dir, file_name), is_user=True)

    # Reordenar _REGISTERED_FAMILIES según prioridades predeterminadas
    ordered = []
    for prio in PRIORITY_FAMILIES:
        if prio in _REGISTERED_FAMILIES and prio not in ordered:
            ordered.append(prio)
    for other in sorted(_REGISTERED_FAMILIES):
        if other not in ordered:
            ordered.append(other)

    _REGISTERED_FAMILIES.clear()
    _REGISTERED_FAMILIES.extend(ordered)
    _INITIALIZED_FULL = True
    logger.info(f"FontManager: Fuentes completas inicializadas. Familias disponibles: {_REGISTERED_FAMILIES}")


def _ensure_active_font(theme_name: str = None) -> str:
    """
    Identifica y registra únicamente la fuente activa necesaria para el arranque.
    Evita el escaneo de todo el sistema y de fuentes innecesarias durante el boot.
    """
    config = get_config()
    configured_font = config.get("font_family", "theme_default")

    target_family = ""
    if configured_font and configured_font not in ("theme_default", "auto"):
        target_family = configured_font
    else:
        if not theme_name:
            theme_name = config.get("theme_id", "dowp")
        theme_font = get_theme_defined_font(theme_name)
        if theme_font:
            target_family = theme_font

    if not target_family:
        target_family = DEFAULT_FALLBACK_FONT

    # Si ya está registrada, retornar directamente
    if target_family in _FAMILY_TO_PATH:
        return target_family

    # Buscar coincidencia rápida por nombre de archivo en assets/fonts
    builtin_fonts_dir = os.path.join(get_src_dir(), "assets", "fonts")
    clean_target = target_family.replace(" ", "").lower()

    if os.path.isdir(builtin_fonts_dir):
        for f in os.listdir(builtin_fonts_dir):
            if f.lower().endswith((".ttf", ".otf")):
                clean_f = f.replace(" ", "").replace("-", "").lower()
                if clean_target in clean_f:
                    reg = _register_font_file(os.path.join(builtin_fonts_dir, f), is_user=False)
                    if reg:
                        return reg

    # Si no se encontró por nombre de archivo, buscar en fuentes de usuario
    user_fonts_dir = get_user_fonts_dir()
    if os.path.isdir(user_fonts_dir):
        for f in os.listdir(user_fonts_dir):
            if f.lower().endswith((".ttf", ".otf")):
                clean_f = f.replace(" ", "").replace("-", "").lower()
                if clean_target in clean_f:
                    reg = _register_font_file(os.path.join(user_fonts_dir, f), is_user=True)
                    if reg:
                        return reg

    # Si aún no se encontró, registrar la fuente de respaldo (Google Sans Flex o Raleway)
    for fallback_file in ["GoogleSansFlex-VariableFont.ttf", "Raleway.ttf"]:
        fb_path = os.path.join(builtin_fonts_dir, fallback_file)
        if os.path.isfile(fb_path):
            reg = _register_font_file(fb_path, is_user=False)
            if reg:
                return reg

    return target_family or "Segoe UI"


def init_fonts(lazy: bool = True) -> list:
    """
    Inicializa el sistema de fuentes.
    Por defecto (lazy=True) registra únicamente la fuente activa requerida para el inicio instantáneo.
    Si lazy=False, realiza un escaneo completo de todas las fuentes disponibles.
    """
    if lazy:
        active = _ensure_active_font()
        logger.debug(f"FontManager: Inicialización rápida (Lazy). Fuente activa lista: {active}")
        return list(_REGISTERED_FAMILIES)
    else:
        _scan_all_fonts()
        return list(_REGISTERED_FAMILIES)


def get_available_fonts() -> list:
    """Retorna la lista de todas las familias de fuentes disponibles (escaneo completo bajo demanda)."""
    global _INITIALIZED_FULL
    if not _INITIALIZED_FULL:
        _scan_all_fonts()
    return list(_REGISTERED_FAMILIES)


def get_font_file_path(family: str) -> str:
    """Ruta absoluta al archivo .ttf/.otf que registró esta familia."""
    if family in _FAMILY_TO_PATH:
        return _FAMILY_TO_PATH[family]

    # Si no está en el mapa, puede que no se haya realizado el escaneo completo todavía
    if not _INITIALIZED_FULL:
        _scan_all_fonts()
        return _FAMILY_TO_PATH.get(family, "")

    return _FAMILY_TO_PATH.get(family, "")


def get_theme_defined_font(theme_name: str) -> str:
    """Fuente personalizada que pide el tema, si la define (ver theme_loader.get_theme_font)."""
    if not theme_name:
        return ""
    from core.utils.theme_loader import get_theme_font
    return get_theme_font(theme_name)


def get_active_font_family(theme_name: str = None) -> str:
    """
    Resuelve la familia de tipografía activa actual (vía caché o registro rápido).
    """
    return _ensure_active_font(theme_name)


def _get_font_cache_dir() -> str:
    global _FONT_CACHE_DIR
    if _FONT_CACHE_DIR is None:
        _FONT_CACHE_DIR = os.path.join(get_app_data_dir(), "font_instances")
    return _FONT_CACHE_DIR


def get_static_font_path(family: str, weight: int = 400) -> str:
    """Ruta a un archivo de fuente ESTÁTICO (no variable) en el peso pedido, para usar
    con ffmpeg drawtext (fontfile=...). Necesario porque algunas de las fuentes variables
    empaquetadas traen el eje 'wght' con su propio default en un extremo poco útil (ej.
    Outfit y Raleway vienen con default=100/Thin de fábrica) — verificado leyendo la
    tabla 'fvar' de cada .ttf. Genera y cachea una instancia estática con
    fontTools.varLib.instancer (pinneando TODOS los ejes presentes, no solo 'wght': dejar
    alguno sin fijar mantiene el archivo parcialmente variable y ffmpeg lo sigue tratando
    igual que el original — verificado empíricamente).

    Si la familia no es una fuente variable (no tiene tabla 'fvar'), devuelve el archivo
    original sin tocar — el peso pedido no tiene efecto en ese caso."""
    source_path = get_font_file_path(family)
    if not source_path or not os.path.exists(source_path):
        return source_path

    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        logger.warning("FontManager: fontTools no está instalado, se usa la fuente sin fijar peso.")
        return source_path

    try:
        probe = TTFont(source_path, lazy=True)
        if "fvar" not in probe:
            return source_path
        axes = list(probe["fvar"].axes)
    except Exception as e:
        logger.warning(f"FontManager: no se pudo leer los ejes de '{family}': {e}")
        return source_path

    cache_dir = _get_font_cache_dir()
    mtime = int(os.path.getmtime(source_path))
    base_name = os.path.splitext(os.path.basename(source_path))[0]
    cache_path = os.path.join(cache_dir, f"{base_name}_{weight}_{mtime}.ttf")
    if os.path.exists(cache_path):
        return cache_path

    try:
        from fontTools.varLib.instancer import instantiateVariableFont
        font = TTFont(source_path)
        axis_limits = {}
        for axis in axes:
            if axis.axisTag == "wght":
                axis_limits["wght"] = min(max(float(weight), axis.minValue), axis.maxValue)
            else:
                axis_limits[axis.axisTag] = axis.defaultValue
        instance = instantiateVariableFont(font, axis_limits, inplace=False)
        os.makedirs(cache_dir, exist_ok=True)
        instance.save(cache_path)
        logger.info(f"FontManager: instancia estática generada para '{family}' @ {weight}: {cache_path}")
        return cache_path
    except Exception as e:
        logger.warning(f"FontManager: no se pudo generar instancia estática de '{family}' @ {weight}: {e}")
        return source_path
