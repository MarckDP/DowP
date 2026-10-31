# src/core/utils/theme_io.py
"""Importar, exportar y eliminar temas de usuario, y convertir temas de DowP 1.

Los temas de usuario viven en %APPDATA%/DowP2/themes/<id>.json (ver theme_loader).
Importar = validar el JSON elegido y copiarlo ahí; si es un tema de DowP 1 (formato de
CustomTkinter), antes se traduce al formato 2. Exportar = escribir el tema completo
(todos los colores en sus dos modos, formas y tipografía), listo para editarlo y
compartirlo: no depende de "dowp" para nada que falte.
"""
import json
import os
import shutil
import re
import unicodedata

from PySide6.QtCore import QCoreApplication, QFile

from core.logger.logger_manager import logger
from core.utils.paths import get_user_themes_dir
from core.utils import theme_loader as TL

MAX_THEME_BYTES = 1024 * 1024  # un tema real pesa unos pocos KB


class ThemeImportError(Exception):
    """Error con un mensaje ya traducido, apto para mostrarse al usuario."""


# ── Utilidades ────────────────────────────────────────────────────────────────
def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return text[:48] or "tema"


def builtin_theme_ids() -> set:
    folder = TL._builtin_dir()
    ids = {os.path.splitext(f)[0] for f in os.listdir(folder) if f.lower().endswith(".json")} if os.path.isdir(folder) else set()
    return ids | set(TL.LEGACY_ALIASES)


def user_theme_path(theme_id: str) -> str:
    return os.path.join(get_user_themes_dir(), f"{theme_id}.json")


def user_theme_ids() -> set:
    folder = get_user_themes_dir()
    return {os.path.splitext(f)[0] for f in os.listdir(folder) if f.endswith(".json")} if os.path.isdir(folder) else set()


def is_user_theme(theme_id: str) -> bool:
    return os.path.isfile(user_theme_path(theme_id))


def _write_json(path: str, data: dict):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        f.write("\n")
    os.replace(tmp, path)


# ── Colores de Tk (DowP 1) ────────────────────────────────────────────────────
_TK_GRAY_RE = re.compile(r"^gr[ae]y(\d{1,3})$", re.I)


def tk_color_to_hex(value):
    """'gray92', 'white', '#abc'... -> '#rrggbb'. None si no es un color reconocible.
    'transparent' se descarta: en DowP 2 los fondos no admiten transparencia."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    if TL.is_valid_color(v) and v.lower() != "transparent":
        return v
    m = _TK_GRAY_RE.match(v)
    if m:
        level = round(min(100, int(m.group(1))) * 255 / 100)
        return f"#{level:02x}{level:02x}{level:02x}"
    try:
        from PySide6.QtGui import QColor
        c = QColor(v)
        if c.isValid() and v.lower() != "transparent":
            return c.name()
    except Exception:
        pass
    return None


def _tk_pair(value):
    """Valor de DowP 1 -> valor de DowP 2 (pareja [claro, oscuro] o color único)."""
    if isinstance(value, (list, tuple)) and len(value) == 2:
        light, dark = tk_color_to_hex(value[0]), tk_color_to_hex(value[1])
        if light and dark:
            return light if light == dark else [light, dark]
        return None
    return tk_color_to_hex(value)


# ── Conversor DowP 1 -> DowP 2 ────────────────────────────────────────────────
# token de DowP 2 <- primeras claves (sección, clave) de DowP 1 que existan.
_DOWP1_COLOR_MAP = [
    ("fondo_principal", [("CTk", "fg_color")]),
    ("fondo_secundario", [("CTkFrame", "fg_color")]),
    ("panel_fondo", [("CTkFrame", "fg_color")]),
    ("fondo_terciario", [("CTkFrame", "top_fg_color")]),
    ("fondo_elemento", [("CTkFrame", "top_fg_color")]),
    ("borde_normal", [("CTkFrame", "border_color")]),
    ("borde_sutil", [("CustomColors", "SEPARATOR_COLOR"), ("CTkFrame", "border_color")]),
    ("divisor", [("CustomColors", "SEPARATOR_COLOR")]),
    ("texto_principal", [("CTkLabel", "text_color")]),
    ("icono_principal", [("CTkLabel", "text_color")]),
    ("texto_secundario", [("CTkEntry", "placeholder_text_color")]),
    ("texto_deshabilitado", [("CTkButton", "text_color_disabled")]),
    ("acento_primario", [("CTkCheckBox", "fg_color"), ("CTkButton", "fg_color")]),
    ("acento_secundario", [("CTkButton", "hover_color")]),
    ("boton_fondo_inicio", [("CustomColors", "ANALYZE_BTN"), ("CTkButton", "fg_color")]),
    ("boton_fondo_fin", [("CustomColors", "ANALYZE_BTN_HOVER"), ("CTkButton", "hover_color")]),
    ("boton_texto", [("CustomColors", "ANALYZE_BTN_TEXT"), ("CTkButton", "text_color")]),
    ("boton_acento_texto", [("CTkButton", "text_color")]),
    ("boton_descarga_inicio", [("CustomColors", "DOWNLOAD_BTN")]),
    ("boton_descarga_fin", [("CustomColors", "DOWNLOAD_BTN_HOVER")]),
    ("boton_descarga_texto", [("CustomColors", "DOWNLOAD_BTN_TEXT")]),
    ("boton_secundario_fondo", [("CustomColors", "SECONDARY_BTN")]),
    ("boton_secundario_hover", [("CustomColors", "SECONDARY_BTN_HOVER")]),
    ("boton_secundario_texto", [("CustomColors", "SECONDARY_BTN_TEXT")]),
    ("fondo_campo", [("CTkEntry", "fg_color")]),
    ("borde_campo", [("CTkEntry", "border_color")]),
    ("checkbox_borde", [("CTkCheckBox", "border_color")]),
    ("checkbox_checked", [("CTkCheckBox", "fg_color")]),
    ("switch_apagado", [("CTkSwitch", "fg_color")]),
    ("switch_perilla", [("CTkSwitch", "button_color")]),
    ("progreso_fondo", [("CTkProgressBar", "fg_color")]),
    ("progreso_inicio", [("CTkProgressBar", "progress_color")]),
    ("progreso_fin", [("CTkProgressBar", "progress_color")]),
    ("seleccion_fondo", [("CustomColors", "LISTBOX_SELECTED_BG")]),
    ("seleccion_texto", [("CustomColors", "LISTBOX_SELECTED_TEXT")]),
    ("estado_exito", [("CustomColors", "STATUS_SUCCESS")]),
    ("estado_error", [("CustomColors", "STATUS_ERROR")]),
    ("estado_aviso", [("CustomColors", "STATUS_WARNING")]),
    ("estado_espera", [("CustomColors", "STATUS_PENDING")]),
    ("ajedrez_c1", [("CustomColors", "TRANSPARENCY_GRID_1")]),
    ("ajedrez_c2", [("CustomColors", "TRANSPARENCY_GRID_2")]),
    ("consola_fondo", [("CustomColors", "CONSOLE_BG")]),
    ("consola_texto", [("CustomColors", "CONSOLE_TEXT")]),
    ("tarjeta_fondo", [("CustomColors", "CONFIG_CARD_BG")]),
    ("titulo_settings", [("CustomColors", "SECTION_SUBTITLE")]),
    ("barra_scroll_tirador", [("CTkScrollbar", "button_color")]),
]

# Fuentes por defecto de CustomTkinter: no son una elección del autor del tema.
_CTK_DEFAULT_FONTS = {"segoe ui", "roboto", "sf display"}


def is_dowp1_theme(data: dict) -> bool:
    return isinstance(data, dict) and any(k in data for k in ("CTk", "CTkButton", "CTkFrame", "CustomColors"))


def convert_dowp1_theme(data: dict, name: str) -> dict:
    """Tema de DowP 1 (CustomTkinter) -> tema de formato 2. Lo que no tiene equivalente
    se omite y se hereda de "dowp"."""
    colores = {}
    for token, sources in _DOWP1_COLOR_MAP:
        for section, key in sources:
            raw = (data.get(section) or {}).get(key) if isinstance(data.get(section), dict) else None
            value = _tk_pair(raw) if raw is not None else None
            if value:
                colores[token] = value
                break

    def corner(section, low, high):
        v = (data.get(section) or {}).get("corner_radius") if isinstance(data.get(section), dict) else None
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v < 100:  # 1000 = "redondo" en CTk
            return max(low, min(high, int(v)))
        return None

    formas = {}
    for token, section in (("radio", "CTkButton"), ("radio_grande", "CTkFrame"), ("radio_chico", "CTkCheckBox")):
        low, high = TL.SHAPE_LIMITS[token]
        v = corner(section, low, high)
        if v is not None:
            formas[token] = v

    theme = {
        "meta": {"nombre": name, "formato": 2, "convertido_de": "DowP 1",
                 "descripcion": "Convertido automáticamente desde un tema de DowP 1."},
        "basado_en": TL.DEFAULT_THEME,
    }
    if formas:
        theme["formas"] = formas
    font = data.get("CTkFont") if isinstance(data.get("CTkFont"), dict) else {}
    font = font.get("Windows") if isinstance(font.get("Windows"), dict) else font
    family, size = font.get("family"), font.get("size")
    tipografia = {}
    if isinstance(family, str) and family.strip() and family.strip().lower() not in _CTK_DEFAULT_FONTS:
        tipografia["familia"] = family.strip()
    if isinstance(size, (int, float)) and not isinstance(size, bool):
        low, high = TL.SHAPE_LIMITS["tamano_fuente"]
        tipografia["tamano"] = max(low, min(high, int(size)))
    if tipografia:
        theme["tipografia"] = tipografia
    theme["colores"] = colores
    return theme


# ── Validación ────────────────────────────────────────────────────────────────
def validate_theme(data: dict) -> dict:
    """{'valid': n colores válidos, 'invalid': [claves], 'unknown': [claves]}."""
    known = set(TL.resolve_theme(TL.DEFAULT_THEME, "dark"))
    valid, invalid, unknown = 0, [], []
    for key, raw in (data.get("colores") or {}).items():
        values = raw if isinstance(raw, (list, tuple)) else [raw]
        if (isinstance(raw, (list, tuple)) and len(raw) != 2) or not all(
                TL.is_valid_color(v.strip() if isinstance(v, str) else v) for v in values):
            invalid.append(key)
            continue
        valid += 1
        if key not in known:
            unknown.append(key)
    return {"valid": valid, "invalid": invalid, "unknown": unknown}


# ── Importar ──────────────────────────────────────────────────────────────────
def read_theme_file(path: str) -> tuple:
    """Lee y prepara un tema para importarlo. Devuelve (theme_id, datos, informe).
    No escribe nada: la UI decide (por ejemplo, si sobrescribir) y llama a save_imported."""
    try:
        if os.path.getsize(path) > MAX_THEME_BYTES:
            raise ThemeImportError(QCoreApplication.translate("ThemeIO", "El archivo es demasiado grande para ser un tema."))
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except ThemeImportError:
        raise
    except (OSError, UnicodeDecodeError) as e:
        raise ThemeImportError(QCoreApplication.translate("ThemeIO", "No se pudo leer el archivo: {0}").format(e))
    except json.JSONDecodeError as e:
        raise ThemeImportError(QCoreApplication.translate("ThemeIO", "El archivo no es un JSON válido (línea {0}, columna {1}).").format(e.lineno, e.colno))
    if not isinstance(data, dict):
        raise ThemeImportError(QCoreApplication.translate("ThemeIO", "El archivo no contiene un tema."))

    stem = os.path.splitext(os.path.basename(path))[0]
    converted = is_dowp1_theme(data)
    if converted:
        name = stem.replace("_", " ").replace("-", " ").title()
        data = convert_dowp1_theme(data, name)
    elif not any(k in data for k in ("colores", "formas", "tipografia", "fuente")):
        raise ThemeImportError(QCoreApplication.translate("ThemeIO", "El archivo no parece un tema de DowP: no tiene «colores», «formas» ni «tipografia»."))

    report = validate_theme(data)
    report["converted"] = converted
    has_shapes = bool(data.get("formas") or data.get("tipografia") or data.get("fuente"))
    if report["valid"] == 0 and not has_shapes:
        raise ThemeImportError(QCoreApplication.translate("ThemeIO", "El tema no tiene ningún color válido."))

    name = (data.get("meta") or {}).get("nombre") if isinstance(data.get("meta"), dict) else None
    theme_id = slugify(stem)
    if theme_id in builtin_theme_ids():
        theme_id = f"{theme_id}_usuario"
    report["name"] = name or stem
    return theme_id, data, report


def save_imported(theme_id: str, data: dict) -> str:
    path = user_theme_path(theme_id)
    _write_json(path, data)
    logger.info(f"Temas: importado '{theme_id}' en {path}")
    return path


def apply_color_edits(theme_id: str, edits: dict) -> str:
    """Guarda colores editados, {modo: {color: valor}}, y devuelve el tema donde quedaron. Un
    tema de usuario se actualiza; uno de DowP no se toca: se crea una copia personalizada."""
    data = TL.read_theme(theme_id) or {}
    target = theme_id
    if not is_user_theme(theme_id):
        name = (data.get("meta") or {}).get("nombre") or theme_id.replace("_", " ").title()
        number, target = 1, f"{theme_id}_personalizado"
        while is_user_theme(target):
            number += 1
            target = f"{theme_id}_personalizado_{number}"
        suffix = QCoreApplication.translate("ThemeIO", "personalizado")
        label = f"{name} ({suffix})" if number == 1 else f"{name} ({suffix} {number})"
        data = {"meta": {"nombre": label, "autor": "DowP", "version": "1.0", "formato": 2}, "basado_en": theme_id,
                "colores": {}}
    data = dict(data)
    colors = dict(data.get("colores") or {})
    light, dark = TL.resolve_theme(theme_id, "light"), TL.resolve_theme(theme_id, "dark")
    for token in {t for changes in edits.values() for t in changes}:
        colors[token] = [edits.get("light", {}).get(token, light.get(token)),
                         edits.get("dark", {}).get(token, dark.get(token))]
    data["colores"] = colors
    _write_json(user_theme_path(target), data)
    logger.info(f"Temas: colores editados guardados en '{target}'")
    return target


# ── Exportar ──────────────────────────────────────────────────────────────────
def build_export(theme_id: str) -> dict:
    """El tema completo y autónomo: cada color en sus dos modos ([claro, oscuro], o un
    solo valor si coinciden), más formas y tipografía resueltas."""
    data = TL.read_theme(theme_id) or {}
    meta = dict(data.get("meta") or {}) if isinstance(data.get("meta"), dict) else {}
    meta.setdefault("nombre", theme_id.replace("_", " ").title())
    meta["formato"] = 2
    light = TL.resolve_theme(theme_id, "light")
    dark = TL.resolve_theme(theme_id, "dark")
    colores = {}
    for key in dark:
        lv, dv = light.get(key, dark[key]), dark[key]
        colores[key] = lv if lv == dv else [lv, dv]
    shapes = TL.resolve_shapes(theme_id)
    tipografia = {"tamano": shapes["tamano_fuente"]}
    family = TL.get_theme_font(theme_id)
    # Del tema activo se exporta lo que se ve: también la fuente elegida en Ajustes.
    from core.utils.config_manager import get_config
    config = get_config()
    if config.get("theme_id") == theme_id and config.get("font_family", "theme_default") != "theme_default":
        family = config["font_family"]
    if family:
        tipografia["familia"] = family
    return {
        "meta": meta,
        "formas": {k: shapes[k] for k in ("radio", "radio_chico", "radio_grande", "borde")},
        "tipografia": tipografia,
        "colores": colores,
    }


def export_theme(theme_id: str, dest_path: str):
    _write_json(dest_path, build_export(theme_id))
    logger.info(f"Temas: exportado '{theme_id}' a {dest_path}")


# ── Eliminar ──────────────────────────────────────────────────────────────────
def delete_user_theme(theme_id: str, to_trash: bool = False):
    """to_trash: a la Papelera, para poder recuperarlo. Si no se puede, queda un OSError."""
    path = user_theme_path(theme_id)
    assets = path[:-len(".json")] + "_assets"  # imágenes de una apariencia
    if to_trash:
        for target in (path, assets):
            if os.path.exists(target) and not QFile.moveToTrash(target):
                raise OSError(QCoreApplication.translate("ThemeIO", "No se pudo enviar a la Papelera: {0}").format(target))
        logger.info(f"Temas: tema de usuario '{theme_id}' enviado a la Papelera")
        return
    if os.path.isfile(path):
        os.remove(path)
        logger.info(f"Temas: eliminado el tema de usuario '{theme_id}'")
    shutil.rmtree(assets, ignore_errors=True)


def rename_user_theme(theme_id: str, name: str):
    data = dict(TL.read_theme(theme_id) or {})
    data["meta"] = dict(data.get("meta") or {}, nombre=name)
    _write_json(user_theme_path(theme_id), data)


def duplicate_theme(theme_id: str) -> str:
    """Una copia de usuario, con sus imágenes si las tiene. De un tema de DowP copia sus colores."""
    data = dict(TL.read_theme(theme_id) or {})
    if not is_user_theme(theme_id):
        data = build_export(theme_id)
    name = (data.get("meta") or {}).get("nombre") or theme_id
    suffix = QCoreApplication.translate("ThemeIO", "copia")
    number, target = 1, slugify(f"{theme_id}_{suffix}")
    while is_user_theme(target) or target in builtin_theme_ids():
        number += 1
        target = slugify(f"{theme_id}_{suffix}_{number}")
    label = f"{name} ({suffix})" if number == 1 else f"{name} ({suffix} {number})"
    data["meta"] = dict(data.get("meta") or {}, nombre=label)
    assets = user_theme_path(theme_id)[:-len(".json")] + "_assets"
    if os.path.isdir(assets):
        shutil.copytree(assets, user_theme_path(target)[:-len(".json")] + "_assets")
    _write_json(user_theme_path(target), data)
    return target
