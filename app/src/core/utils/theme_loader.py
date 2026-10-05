# src/core/utils/theme_loader.py
"""Carga y resolución de temas (sin dependencias de la interfaz).

Un tema es un JSON en src/gui/themes/ (incluidos) o en %APPDATA%/DowP2/themes/ (del
usuario). Formato 2:

    {
      "meta": {"nombre": "Mi tema", "autor": "...", "formato": 2},
      "basado_en": "dowp",                       # opcional; por defecto "dowp"
      "colores": {
        "acento_primario": ["#1DC038", "#B9E640"],   # [modo claro, modo oscuro]
        "estado_error": "#ff6b5f"                    # un solo valor = igual en ambos
      },
      "fuente": "Inter",                             # opcional
      "formas": {                                    # opcional, en píxeles
        "radio": 6,          # esquinas de botones, campos, menús y tarjetas
        "radio_chico": 4,    # esquinas de elementos pequeños (chips, muestras)
        "radio_grande": 8,   # esquinas de paneles y diálogos
        "borde": 1           # grosor de los bordes
      },
      "tipografia": {"tamano": 13}                   # opcional: tamaño base del texto
    }

Resolver un tema = elegir el valor de cada token según el modo (claro/oscuro) y
completar lo que falte con su tema base. El resultado es un dict plano
{token: valor} que es lo que consumen _base.qss y get_theme_token().

Los temas de formato 1 (los dark.json/light.json de antes, o temas de usuario hechos
con ellos) siguen funcionando: sus valores son de un solo color, iguales en ambos
modos, y heredan de "dowp" lo que no definan. Los nombres "dark" y "light" se
resuelven como el tema "dowp" en ese modo (ver LEGACY_ALIASES).
"""
import json
import os
import re

from core.logger.logger_manager import logger
from core.utils.paths import get_src_dir, get_user_themes_dir

DEFAULT_THEME = "dowp"
MODES = ("light", "dark")
MODE_SYSTEM = "system"

# Ids de antes del formato 2: eran dos temas separados y ahora son los dos modos de "dowp".
LEGACY_ALIASES = {"dark": (DEFAULT_THEME, "dark"), "light": (DEFAULT_THEME, "light")}

_MAX_BASE_DEPTH = 5

# Colores admitidos: #rgb, #rrggbb, #aarrggbb, rgb()/rgba() y 'transparent'. Todo lo
# demás se rechaza: los valores se insertan tal cual en el QSS, y un ';' o un '}'
# podría romper la hoja de estilos de toda la app.
_COLOR_RE = re.compile(
    r"^(#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})"
    r"|rgba?\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*(?:,\s*(?:0|1|0?\.\d+|\d{1,3})\s*)?\)"
    r"|transparent)$"
)

_file_cache = {}      # ruta -> (mtime, datos)
_warned = set()       # avisos ya registrados: resolve_theme se llama a menudo
_active_tokens = None  # tokens del tema aplicado (ver set_active_tokens)
_active_shapes = None  # formas del tema aplicado (ver set_active_shapes)

# Formas y tamaño de letra del diseño original de DowP. Los estilos de la app están
# escritos con estos valores; un tema que los cambie los escala en proporción (ver
# gui/styles.py::apply_shapes). Límites: fuera de ellos la interfaz se descuadra
# (textos cortados en alturas fijas, esquinas más grandes que el propio botón).
DEFAULT_SHAPES = {"radio": 6, "radio_chico": 4, "radio_grande": 8, "borde": 1, "tamano_fuente": 13}
SHAPE_LIMITS = {"radio": (0, 14), "radio_chico": (0, 8), "radio_grande": (0, 20),
                "borde": (0, 3), "tamano_fuente": (11, 14)}


def _builtin_dir() -> str:
    return os.path.join(get_src_dir(), "gui", "themes")


def find_theme_path(theme_id: str) -> str:
    """Ruta del JSON del tema: primero los del usuario, luego los incluidos."""
    for folder in (get_user_themes_dir(), _builtin_dir()):
        path = os.path.join(folder, f"{theme_id}.json")
        if os.path.isfile(path):
            return path
    return ""


def _read_json(path: str) -> dict:
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    cached = _file_cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("el archivo no contiene un objeto JSON")
    except Exception as e:
        logger.error(f"Temas: no se pudo leer {path}: {e}")
        data = {}
    _file_cache[path] = (mtime, data)
    return data


def read_theme(theme_id: str) -> dict:
    path = find_theme_path(theme_id)
    return _read_json(path) if path else {}


def _warn_once(key, message: str):
    if key not in _warned:
        _warned.add(key)
        logger.warning(message)


def is_valid_color(value) -> bool:
    return isinstance(value, str) and bool(_COLOR_RE.match(value.strip()))


def _pick(value, mode: str):
    """Valor de un token para `mode`: una pareja [claro, oscuro] o un valor único."""
    if isinstance(value, (list, tuple)):
        if len(value) != 2:
            return None
        return value[0] if mode == "light" else value[1]
    return value


def theme_has_modes(theme_id: str) -> bool:
    """True si el tema, ya completado con su base, se ve distinto en claro y en oscuro.
    Un tema de usuario que redefine todos los colores sin parejas es de un solo modo,
    aunque herede de "dowp" (que sí tiene los dos)."""
    if theme_id in LEGACY_ALIASES:
        return False  # 'dark'/'light' fuerzan su modo
    return resolve_theme(theme_id, "light") != resolve_theme(theme_id, "dark")


def _base_of(theme_id: str, data: dict):
    if "basado_en" in data:
        base = data.get("basado_en") or None
    else:
        base = None if theme_id == DEFAULT_THEME else DEFAULT_THEME
    if base:
        base = LEGACY_ALIASES.get(base, (base, None))[0]
    return base if base != theme_id else None


def resolve_theme(theme_id: str, mode: str, _depth: int = 0) -> dict:
    """Tokens planos del tema en ese modo, completados con su tema base.

    Nunca lanza: un tema inexistente o roto cae al tema por defecto, y un valor
    inválido se descarta (con aviso en el log) para que gane el de la base."""
    theme_id, forced_mode = LEGACY_ALIASES.get(theme_id, (theme_id, None))
    if forced_mode:
        mode = forced_mode
    if mode not in MODES:
        mode = "dark"

    data = read_theme(theme_id)
    if not data and theme_id != DEFAULT_THEME:
        _warn_once((theme_id, "missing"), f"Temas: el tema '{theme_id}' no existe o no se pudo leer; se usa '{DEFAULT_THEME}'")
        return resolve_theme(DEFAULT_THEME, mode, _depth + 1)

    tokens = {}
    base = _base_of(theme_id, data)
    if base and _depth < _MAX_BASE_DEPTH:
        tokens.update(resolve_theme(base, mode, _depth + 1))
    elif base:
        _warn_once((theme_id, "basado_en"), f"Temas: cadena 'basado_en' demasiado larga o circular en '{theme_id}'")

    for key, raw in (data.get("colores") or {}).items():
        value = _pick(raw, mode)
        if isinstance(value, str):
            value = value.strip()
        if not is_valid_color(value):
            _warn_once((theme_id, key, repr(raw)),
                       f"Temas: '{theme_id}' -> '{key}': {raw!r} no es un color válido; se ignora")
            continue
        tokens[key] = value
    return tokens


def get_theme_font(theme_id: str) -> str:
    """Fuente que pide el tema ('fuente' o 'tipografia.familia'), si la define."""
    theme_id = LEGACY_ALIASES.get(theme_id, (theme_id, None))[0]
    data = read_theme(theme_id)
    font = data.get("fuente") or data.get("font_family") or (data.get("tipografia") or {}).get("familia")
    return font if isinstance(font, str) else ""


def list_themes() -> list:
    """[{id, name, is_user, has_modes}] de los temas incluidos y de usuario."""
    themes, seen = [], set()
    for folder, is_user in ((_builtin_dir(), False), (get_user_themes_dir(), True)):
        if not os.path.isdir(folder):
            continue
        for filename in sorted(os.listdir(folder)):
            theme_id, ext = os.path.splitext(filename)
            if ext.lower() != ".json" or theme_id in seen or theme_id in LEGACY_ALIASES:
                continue
            data = _read_json(os.path.join(folder, filename))
            if not data:
                continue
            seen.add(theme_id)
            name = (data.get("meta") or {}).get("nombre") or theme_id.replace("_", " ").title()
            themes.append({"id": theme_id, "name": name, "is_user": is_user,
                           "has_modes": theme_has_modes(theme_id)})
    # DowP primero, luego los incluidos y al final los del usuario, por nombre
    themes.sort(key=lambda t: (t["id"] != DEFAULT_THEME, t["is_user"], t["name"].casefold()))
    return themes


def normalize_config_theme(config: dict) -> bool:
    """Lleva la configuración al formato 2 SIN romper versiones anteriores.

    El tema elegido va en 'theme_id' y el modo en 'theme_mode'. La clave antigua
    'theme' se conserva con un valor que DowP 1.9.2 y anteriores entienden ('dark' o
    'light'): comparten config.json con esta versión (mismo %APPDATA%\DowP2), y si
    'theme' pasara a valer 'dowp', esas versiones no encontrarían el tema y
    arrancarían sin estilos. Devuelve True si cambió algo."""
    changed = False
    if "theme_id" not in config:
        legacy = config.get("theme")
        if legacy in LEGACY_ALIASES:
            new_id, mode = LEGACY_ALIASES[legacy]
            config["theme_id"] = new_id
            config.setdefault("theme_mode", mode)
        elif isinstance(legacy, str) and legacy:
            config["theme_id"] = legacy
        else:
            config["theme_id"] = DEFAULT_THEME
        changed = True
    if config.get("theme_mode") not in MODES + (MODE_SYSTEM,):
        config["theme_mode"] = "dark"
        changed = True
    return sync_legacy_theme_key(config) or changed


def sync_legacy_theme_key(config: dict) -> bool:
    """Deja 'theme' (clave de las versiones anteriores) en 'dark' o 'light' según el
    modo efectivo. Llamar cada vez que cambie el tema o el modo."""
    legacy = effective_mode(config.get("theme_mode", "dark"))
    if config.get("theme") != legacy:
        config["theme"] = legacy
        return True
    return False


# ── Tokens del tema activo ───────────────────────────────────────────────────

def resolve_shapes(theme_id: str, _depth: int = 0) -> dict:
    """Formas y tamaño de letra del tema, completados con su tema base. Son iguales en
    claro y en oscuro. Nunca lanza: un valor inválido se ignora con aviso en el log."""
    theme_id = LEGACY_ALIASES.get(theme_id, (theme_id, None))[0]
    data = read_theme(theme_id)
    if not data and theme_id != DEFAULT_THEME:
        return resolve_shapes(DEFAULT_THEME, _depth + 1)

    shapes = dict(DEFAULT_SHAPES)
    base = _base_of(theme_id, data)
    if base and _depth < _MAX_BASE_DEPTH:
        shapes.update(resolve_shapes(base, _depth + 1))

    raw = dict(data.get("formas") or {}) if isinstance(data.get("formas"), dict) else {}
    tipografia = data.get("tipografia") if isinstance(data.get("tipografia"), dict) else {}
    for key in ("tamano", "tamaño"):
        if key in tipografia:
            raw["tamano_fuente"] = tipografia[key]
    for key, value in raw.items():
        if key not in SHAPE_LIMITS:
            _warn_once((theme_id, "formas", key), f"Temas: '{theme_id}' -> formas: '{key}' no existe; se ignora")
            continue
        low, high = SHAPE_LIMITS[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not (low <= value <= high):
            _warn_once((theme_id, key, repr(value)),
                       f"Temas: '{theme_id}' -> '{key}': {value!r} debe ser un número entre {low} y {high}; se ignora")
            continue
        shapes[key] = value
    return shapes


def set_active_shapes(shapes: dict):
    """Lo llama el ThemeManager junto con set_active_tokens."""
    global _active_shapes
    _active_shapes = dict(shapes)


def get_active_shapes() -> dict:
    global _active_shapes
    if _active_shapes is None:
        from core.utils.config_manager import get_config
        _active_shapes = resolve_shapes(get_config().get("theme_id", DEFAULT_THEME))
    return _active_shapes


def set_active_tokens(tokens: dict):
    """Lo llama el ThemeManager de la interfaz cada vez que aplica un tema."""
    global _active_tokens
    _active_tokens = dict(tokens)


def system_prefers_dark() -> bool:
    """Modo del sistema operativo según Qt; oscuro si no se puede saber."""
    try:
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtCore import Qt
        app = QGuiApplication.instance()
        if app is not None:
            return app.styleHints().colorScheme() != Qt.ColorScheme.Light
    except Exception:
        pass
    return True


def effective_mode(mode_setting: str) -> str:
    if mode_setting == MODE_SYSTEM:
        return "dark" if system_prefers_dark() else "light"
    return mode_setting if mode_setting in MODES else "dark"


def get_active_tokens() -> dict:
    """Tokens del tema activo. Antes de que la interfaz aplique uno (p. ej. la pantalla
    de inicio), se resuelven desde la configuración."""
    global _active_tokens
    if _active_tokens is None:
        from core.utils.config_manager import get_config
        config = get_config()
        _active_tokens = resolve_theme(config.get("theme_id", DEFAULT_THEME),
                                       effective_mode(config.get("theme_mode", "dark")))
    return _active_tokens


def get_active_token(key: str, default=None):
    return get_active_tokens().get(key, default)
