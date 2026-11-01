# src/gui/styles.py
"""
Motor de Temas DowP 2.0
========================
Lee un template QSS (_base.qss) y los tokens del tema activo, reemplaza las
variables {{token}} por sus valores, y genera assets dinámicos como el ícono SVG
del triángulo del ComboBox.

Los temas (con sus dos modos, claro y oscuro) los carga y resuelve
core/utils/theme_loader.py; el que los aplica a la app es gui/theme_manager.py.

Para crear un tema: Ajustes > Apariencia > botón junto a "Tema visual" > Exportar tema
actual, editar el JSON y volver a importarlo. El formato completo (colores en sus dos
modos, formas y tipografía) está en gui/themes/TEMAS.md.
"""
import os
import re
import json
import tempfile
from core.logger.logger_manager import logger
from core.utils.paths import get_src_dir
from PySide6.QtCore import QCoreApplication
from core.utils.theme_loader import DEFAULT_SHAPES as DEFAULT_SHAPES_UI

# Directorio base de temas
_THEMES_DIR = os.path.join(get_src_dir(), "gui", "themes")
_BASE_QSS = os.path.join(_THEMES_DIR, "_base.qss")

# Directorio temporal para assets generados (SVGs, etc.)
_TEMP_DIR = os.path.join(tempfile.gettempdir(), "dowp_theme_assets")
os.makedirs(_TEMP_DIR, exist_ok=True)


def generate_triangle_svg(color: str) -> str:
    """
    Genera un archivo SVG de triángulo invertido (▼) con el color dado.
    Retorna la ruta al archivo SVG generado.
    """
    # Normalizar color para nombre de archivo seguro
    safe_color = color.replace("#", "").replace(" ", "")
    svg_path = os.path.join(_TEMP_DIR, f"triangle_{safe_color}.svg")
    
    # Solo generar si no existe ya
    if not os.path.exists(svg_path):
        svg_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 8" width="12" height="8">
  <polygon points="0,0 12,0 6,8" fill="{color}"/>
</svg>'''
        try:
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(svg_content)
            logger.debug(f"Temas: SVG triángulo generado: {svg_path}")
        except Exception as e:
            logger.error(f"Temas: Error generando SVG: {e}")
            return ""
    
    return svg_path.replace("\\", "/")

def themed_icon(icon_name: str, token: str = "icono_principal", fallback: str = "#e3e3e3"):
    """QIcon de assets/icons/svg teñido con un token del tema (sigue siendo vectorial).
    Para que cambie en vivo, quien lo usa lo vuelve a pedir desde un
    register_theme_callback."""
    from PySide6.QtGui import QIcon
    tinted = generate_tinted_svg(icon_name, get_theme_token(token, fallback))
    if tinted:
        return QIcon(tinted)
    return QIcon(os.path.join(get_src_dir(), "assets", "icons", "svg", icon_name))


def token_rgba(token: str, fallback: str, alpha: int) -> str:
    """'rgba(r, g, b, alpha)' a partir de un token (los tokens son '#rrggbb')."""
    from PySide6.QtGui import QColor
    c = QColor(get_theme_token(token, fallback))
    if not c.isValid():
        c = QColor(fallback)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"


def tooltip_qss() -> str:
    """Regla QToolTip del tema, para añadirla a hojas locales que fijan color a sus
    QLabel: el tooltip de Qt ES un QLabel hijo del widget, así que sin esto hereda
    ese color (p. ej. rojo de error) en vez del de los tooltips."""
    return f"""
        QToolTip {{
            background-color: {get_theme_token('fondo_terciario', '#2a2a2a')};
            color: {get_theme_token('texto_activo', '#ffffff')};
            border: 1px solid {get_theme_token('borde_sutil', '#333333')};
            border-radius: 6px;
            padding: 5px 9px;
            font-size: 11px;
            font-weight: normal;
        }}
    """


def generate_tinted_svg(icon_name: str, color_hex: str) -> str:
    """
    Toma un SVG de assets/icons/svg, le aplica un color inyectando una regla CSS,
    y lo guarda en la caché temporal. Retorna la ruta normalizada al SVG resultante.
    """
    safe_color = color_hex.replace("#", "").replace(" ", "")
    safe_name = icon_name.replace(".svg", "")
    out_name = f"{safe_name}_{safe_color}.svg"
    svg_out_path = os.path.join(_TEMP_DIR, out_name)

    if not os.path.exists(svg_out_path):
        src_path = os.path.join(get_src_dir(), "assets", "icons", "svg", f"{safe_name}.svg")
        if not os.path.exists(src_path):
            return ""
        
        try:
            with open(src_path, "r", encoding="utf-8") as f:
                svg_content = f.read()
                
            idx = svg_content.find('>')
            if idx != -1:
                style_block = f'<style>* {{ fill: {color_hex} !important; }}</style>'
                svg_content = svg_content[:idx+1] + style_block + svg_content[idx+1:]
                
            with open(svg_out_path, "w", encoding="utf-8") as f:
                f.write(svg_content)
        except Exception as e:
            logger.error(f"Error generando SVG tintado {out_name}: {e}")
            
    return svg_out_path.replace("\\", "/")


def _generate_spinbox_symbol_svg(symbol: str, color: str) -> str:
    """
    Genera SVGs pequenos para los botones +/- de QSpinBox/QDoubleSpinBox.
    """
    safe_color = color.replace("#", "").replace(" ", "")
    svg_path = os.path.join(_TEMP_DIR, f"spinbox_{symbol}_{safe_color}.svg")

    if not os.path.exists(svg_path):
        if symbol == "plus":
            shape = (
                '<rect x="5" y="1" width="2" height="10" rx="1" fill="{color}"/>'
                '<rect x="1" y="5" width="10" height="2" rx="1" fill="{color}"/>'
            )
        else:
            shape = '<rect x="1" y="5" width="10" height="2" rx="1" fill="{color}"/>'

        svg_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 12" width="12" height="12">
  {shape.format(color=color)}
</svg>'''
        try:
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(svg_content)
            logger.debug(f"Temas: SVG spinbox generado: {svg_path}")
        except Exception as e:
            logger.error(f"Temas: Error generando SVG spinbox: {e}")
            return ""

    return svg_path.replace("\\", "/")


def _generate_radio_checked_svg(color: str) -> str:
    """
    Genera un archivo SVG con un punto central para QRadioButton::indicator:checked.
    """
    safe_color = color.replace("#", "").replace(" ", "")
    svg_path = os.path.join(_TEMP_DIR, f"radio_checked_{safe_color}.svg")

    if not os.path.exists(svg_path):
        svg_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" width="16" height="16">
  <circle cx="8" cy="8" r="4.5" fill="{color}"/>
</svg>'''
        try:
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(svg_content)
            logger.debug(f"Temas: SVG radio checked generado: {svg_path}")
        except Exception as e:
            logger.error(f"Temas: Error generando SVG radio checked: {e}")
            return ""

    return svg_path.replace("\\", "/")


def _generate_checkbox_checked_svg(color: str) -> str:
    """
    Genera un archivo SVG con marca check para QCheckBox::indicator:checked.
    """
    safe_color = color.replace("#", "").replace(" ", "")
    svg_path = os.path.join(_TEMP_DIR, f"checkbox_checked_{safe_color}.svg")

    if not os.path.exists(svg_path):
        svg_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" width="16" height="16">
  <polyline points="3.5,8.5 6.5,11.5 12.5,4.5" fill="none" stroke="{color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
</svg>'''
        try:
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(svg_content)
            logger.debug(f"Temas: SVG checkbox checked generado: {svg_path}")
        except Exception as e:
            logger.error(f"Temas: Error generando SVG checkbox checked: {e}")
            return ""

    return svg_path.replace("\\", "/")


def _load_base_template() -> str:
    """
    Carga el template QSS base.
    """
    if not os.path.exists(_BASE_QSS):
        logger.error(f"Temas: Template base no encontrado: {_BASE_QSS}")
        return ""
    
    try:
        with open(_BASE_QSS, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logger.error(f"Temas: Error leyendo template base: {e}")
        return ""


def get_available_themes() -> list:
    """
    Retorna una lista de temas disponibles con sus metadatos (id, name, is_user, has_modes).
    Escanea tanto los temas empaquetados como los temas personalizados del usuario en AppData.
    """
    from core.utils.theme_loader import list_themes
    themes = list_themes()
    for t in themes:
        if t["is_user"]:
            t["name"] = QCoreApplication.translate("Styles", "{0} (Usuario)").format(t["name"])
    return themes


# Estilos que se vuelven a calcular al cambiar de tema (ver set_themed_style). Una
# entrada por widget (la última gana: un widget que cambia de estado a menudo no acumula
# entradas) y referencias débiles: al destruirse el widget, su entrada desaparece sola.
import weakref as _weakref
_THEMED_STYLES = _weakref.WeakKeyDictionary()


_RADIUS_RE = re.compile(r"(radius\s*:\s*)(\d+(?:\.\d+)?)px")
_FONT_RE = re.compile(r"(font-size\s*:\s*)(\d+(?:\.\d+)?)px")
_BORDER_RE = re.compile(r"(\bborder(?:-top|-bottom|-left|-right)?(?:-width)?\s*:\s*)(\d+(?:\.\d+)?)px")


def _fmt_px(value: float) -> str:
    value = max(0.0, value)
    return f"{int(round(value))}px" if abs(value - round(value)) < 0.05 or value >= 3 else f"{value:.1f}px"


def _scaled_radius(px: float, shapes: dict) -> float:
    """Los estilos están escritos con las formas por defecto (radio 6, chico 4, grande
    8). Cada esquina se escala con el grupo al que pertenece su valor original. No se
    tocan las que dibujan círculos o píldoras (9, 10, 14 y 20+ px: indicadores de
    radio, botones de info, chips), que dependen del alto del widget y no del tema."""
    d = DEFAULT_SHAPES_UI
    if px <= 0:
        return px
    if px <= 4:
        return px * shapes["radio_chico"] / d["radio_chico"]
    # Qt dibuja esquinas rectas si el radio pasa de la mitad del alto. Los controles chicos miden
    # desde unos 20 px, y los de 11 y 12 ya son píldoras: no pueden crecer más.
    if px <= 7:
        return min(px * shapes["radio"] / d["radio"], MAX_CONTROL_RADIUS)
    if px in (11, 12):
        return min(px * shapes["radio_grande"] / d["radio_grande"], px)
    if px in (8, 16):
        return px * shapes["radio_grande"] / d["radio_grande"]
    return px


MAX_CONTROL_RADIUS = 10
_SIZE_RE = re.compile(r"(?:^|[;{\s])(?:min-|max-)?(?:width|height)\s*:\s*(\d+)px")
_BLOCK_RE = re.compile(r"\{[^{}]*\}")


def theme_radius(px: float) -> float:
    """Para lo que se pinta a mano: el radio escrito con las formas por defecto, adaptado
    a las formas activas (tema o control de Redondez), como hace apply_shapes en las hojas."""
    from core.utils.theme_loader import get_active_shapes
    return _scaled_radius(px, get_active_shapes())


def _scale_radii(qss: str, shapes: dict) -> str:
    """Escala los radios bloque a bloque: si en el mismo bloque hay un alto o ancho que
    es el doble del radio, es un círculo o una píldora y se deja como está."""
    def scale_in(text):
        sizes = {int(x) for x in _SIZE_RE.findall(text)}
        def one(m):
            px = float(m.group(2))
            if px > 0 and int(px * 2) in sizes:
                return m.group(0)
            return m.group(1) + _fmt_px(_scaled_radius(px, shapes))
        return _RADIUS_RE.sub(one, text)
    if "{" not in qss:  # hoja sin selectores: todo es un solo bloque
        return scale_in(qss)
    return _BLOCK_RE.sub(lambda b: scale_in(b.group(0)), qss)


def apply_shapes(qss: str) -> str:
    """Adapta una hoja de estilos a las formas y el tamaño de letra del tema activo
    (bloques "formas" y "tipografia" del JSON). Con los valores por defecto la deja
    tal cual, así el tema DowP no cambia en nada."""
    from core.utils.theme_loader import get_active_shapes
    shapes = get_active_shapes()
    if not qss or shapes == DEFAULT_SHAPES_UI:
        return qss
    d = DEFAULT_SHAPES_UI
    if (shapes["radio"], shapes["radio_chico"], shapes["radio_grande"]) != (d["radio"], d["radio_chico"], d["radio_grande"]):
        qss = _scale_radii(qss, shapes)
    if shapes["tamano_fuente"] != d["tamano_fuente"]:
        factor = shapes["tamano_fuente"] / d["tamano_fuente"]
        qss = _FONT_RE.sub(lambda m: m.group(1) + f"{max(7, int(round(float(m.group(2)) * factor)))}px", qss)
    if shapes["borde"] != d["borde"]:
        # Solo los bordes normales (1px). Los más gruesos son de dibujo (aro de los
        # botones de radio, foco, marcas) y dependen del tamaño del indicador.
        qss = _BORDER_RE.sub(
            lambda m: m.group(1) + _fmt_px(shapes["borde"]) if float(m.group(2)) == d["borde"] else m.group(0), qss)
    return qss


# ── Imagen de fondo: paneles translúcidos ─────────────────────────────────────
# Con una imagen de fondo general puesta (core/utils/background_images.py), la
# interfaz deja ver la imagen con la opacidad que eligió el usuario. Sin imagen, nada
# de esto cambia nada: la app queda exactamente como siempre. Cada widget dentro del
# lienzo tiene un estado (glass_status):
#   "outer"   panel más externo de su zona: la opacidad elegida.
#   "nested"  panel dentro de otro panel translúcido: un 30 % de esa opacidad. Si no,
#             las capas se suman (dos al 80 % tapan el 96 % de la imagen).
#   "control" campo, botón, combo, barra...: más sólido que su panel, en proporción
#             (paneles al 50 % -> controles al 70 %), así se distinguen y se leen.
#   "frosted" lo que flota encima del contenido (paneles ocultables superpuestos,
#             popovers, Posprocesar): "vidrio recortado", pinta el pedazo de la imagen
#             de fondo que tiene detrás, desenfocado, y su color translúcido encima.
#             Se ve el fondo, pero no la interfaz que tapa.
#   None      sólido: fuera de la ventana (diálogos, listas desplegables, menús),
#             etiquetas, indicadores, botones de acción con color, excluidos.
GLASS_CANVAS_NAME = "dowpCanvas"  # el widget central que dibuja la imagen
_GLASS_NESTED_FACTOR = 0.3
_GLASS_CONTROL_SHARE = 0.4   # control = panel + 40 % de lo que le falta para 100 %
# Botones de acción (degradados y colores de acento o de estado): translúcidos pero más
# fuertes que un control normal, para no perder su color (paneles al 50 % -> 85 %).
_GLASS_ACTION_SHARE = 0.7
_GLASS_ALT_ROW_FACTOR = 0.35  # el color alterno de las filas va encima del de la lista
_GLASS_TAB_TEXT_MIX = 0.75    # cuánto del texto normal llevan las pestañas no seleccionadas

# Tipos que cuentan como "panel" en un selector de QSS.
_GLASS_CONTAINER_TYPES = {
    "QFrame", "QWidget", "QScrollArea", "QStackedWidget", "QGroupBox", "QSplitter",
    "QAbstractItemView", "QAbstractScrollArea", "QTreeView", "QListView", "QTableView",
    "QTreeWidget", "QListWidget", "QTableWidget", "QDockWidget",
}
# Tipos que cuentan como "control".
_GLASS_CONTROL_TYPES = {
    "QLineEdit", "QPushButton", "QToolButton", "QComboBox", "QSpinBox", "QDoubleSpinBox",
    "QAbstractSpinBox", "QDateTimeEdit", "QProgressBar", "QScrollBar", "QHeaderView", "QTabBar",
    "QCheckBox", "QRadioButton",
}
# Subcontroles que se transparentan (el resto, como ::indicator o ::handle, no).
_GLASS_PANEL_SUBCONTROLS = ("QTabWidget::pane",)
_GLASS_CONTROL_SUBCONTROLS = ("QHeaderView::section", "QTabBar::tab", "QComboBox::drop-down",
                              "QCheckBox::indicator", "QRadioButton::indicator")
# Vistas previas: aunque sean QLabel, con imagen de fondo se comportan como un panel
# (vacías, dejan ver la imagen en vez de un bloque sólido).
_GLASS_PREVIEW_NAMES = ("thumbnailLabel", "playerTimeInfo")
# Siempre sólidos: tarjetas de las colas (su opacidad será un ajuste aparte), video,
# el modal de Ajustes y su velo, el indicador de pestaña, la consola.
_GLASS_SOLID_NAMES = (
    "queueItemCard", "fragmentVideoContainer", "mediaSearchPreviewContainer",
    "settingsModalCard", "settingsModalOverlay", "animatedTabIndicator", "modeIndicator",
    "consoleContent", "bottomConsolePanel", "consoleOverlayPanel",
)
# Tokens de los botones de acción: su color es lo que indica la acción, quedan sólidos.
_GLASS_ACTION_TOKENS = (
    "acento_primario", "acento_secundario", "estado_error", "estado_exito", "estado_aviso",
    "estado_progreso", "progreso_inicio",
)
_GLASS_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_GLASS_BG_RE = re.compile(r"((?:alternate-)?background(?:-color)?\s*:\s*)([^;}]+)")
_GLASS_RGBA_RE = re.compile(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)", re.IGNORECASE)
_GLASS_RADIUS_RE = re.compile(r"border-radius\s*:\s*(\d+(?:\.\d+)?)px")

_THEMED_RAW = _weakref.WeakKeyDictionary()     # widget -> hoja sin transparencia (ver set_themed_style)
_GLASS_STATUS = _weakref.WeakKeyDictionary()   # widget -> estado (caché, ver glass_status)
_GLASS_PAINTS = _weakref.WeakKeyDictionary()   # widget -> pinta un fondo liso (caché)
_GLASS_FROSTED_HOOKED = _weakref.WeakSet()      # widgets con el pintor de vidrio instalado
_GLASS_MAIN = {"names": set(), "types": set()}  # paneles con fondo en la hoja de la ventana
_GLASS_ACTION_RGB: list = []                   # colores de acción del tema activo


def glass_alpha_for(status: str, panel_alpha: float) -> float:
    if status == "nested":
        return panel_alpha * _GLASS_NESTED_FACTOR
    if status == "control":
        return panel_alpha + (1.0 - panel_alpha) * _GLASS_CONTROL_SHARE
    if status == "action":
        return panel_alpha + (1.0 - panel_alpha) * _GLASS_ACTION_SHARE
    return panel_alpha


def _parse_color(value: str):
    """(r, g, b, a 0-255) de un color de QSS, o None si no es un color liso."""
    from PySide6.QtGui import QColor
    v = value.strip()
    low = v.lower()
    if low in ("transparent", "none") or "gradient" in low or "url(" in low or low.startswith("palette("):
        return None
    m = _GLASS_RGBA_RE.fullmatch(v)
    if m:
        a = m.group(4)
        # Como Qt: con decimales es una fracción (0.08), sin decimales va de 0 a 255.
        a = 255 if a is None else (round(float(a) * 255) if "." in a else int(a))
        return int(m.group(1)), int(m.group(2)), int(m.group(3)), a
    c = QColor(v)
    return (c.red(), c.green(), c.blue(), c.alpha()) if c.isValid() else None


def _is_action_color(r, g, b) -> bool:
    if not _GLASS_ACTION_RGB:
        from PySide6.QtGui import QColor
        for token in _GLASS_ACTION_TOKENS:
            c = QColor(get_theme_token(token, ""))
            if c.isValid():
                _GLASS_ACTION_RGB.append((c.red(), c.green(), c.blue()))
    return any(abs(r - ar) + abs(g - ag) + abs(b - ab) <= 36 for ar, ag, ab in _GLASS_ACTION_RGB)


_GLASS_GRADIENT_STOP_RE = re.compile(r"(stop\s*:\s*[\d.]+\s+)(#[0-9a-fA-F]{3,8}|rgba?\([^)]*\)|[a-zA-Z]+)")


def _glass_gradient(value: str, alpha: float) -> str:
    """El degradado con la opacidad de cada parada multiplicada por `alpha`: se vuelve
    translúcido sin perder sus colores."""
    def stop(m):
        c = _parse_color(m.group(2))
        if c is None:
            return m.group(0)
        r, g, b, a = c
        return f"{m.group(1)}rgba({r}, {g}, {b}, {max(0, min(255, round(a * alpha)))})"
    return _GLASS_GRADIENT_STOP_RE.sub(stop, value)


def _glass_color(value: str, alpha: float, control: bool = False, allow_black: bool = False,
                 action_alpha: float | None = None) -> str | None:
    """El color con su opacidad multiplicada por `alpha`, o None si no conviene tocarlo
    (transparente, imagen, negro puro -los reproductores siguen negros- y, en un
    control, los colores que ya traen su propia transparencia). Los degradados y, en un
    control, los colores de acción usan `action_alpha` (más alta) si se da: se vuelven
    translúcidos sin perder fuerza."""
    if "gradient" in value.lower():
        return _glass_gradient(value, action_alpha if action_alpha is not None else alpha)
    parsed = _parse_color(value)
    if parsed is None:
        return None
    r, g, b, a = parsed
    if (r, g, b) == (0, 0, 0) and a == 255 and not allow_black:
        return None
    if control and a < 255:
        return None
    if control and _is_action_color(r, g, b):
        if action_alpha is None:
            return None
        alpha = action_alpha
    return f"rgba({r}, {g}, {b}, {max(0, min(255, round(a * alpha)))})"


def _glass_kind(selector: str) -> str | None:
    """"panel", "control", "unknown" (#nombre suelto: depende del widget) o None (no
    se toca: excluidos, lo que flota, indicadores, botones de acción)."""
    sel = selector.strip()
    if not sel or any(name in sel for name in _GLASS_SOLID_NAMES):
        return None
    if any(mark in sel for mark in ("QMenu", "QToolTip", "QCompleter")):
        return None
    parts = sel.split()
    if any(p.startswith("QComboBox") for p in parts[:-1]):
        return None  # la lista desplegable de un combo (otra ventana)
    last = parts[-1]
    if "::" in last:
        if last.startswith(_GLASS_PANEL_SUBCONTROLS):
            return "panel"
        return "control" if last.startswith(_GLASS_CONTROL_SUBCONTROLS) else None
    m = re.match(r"[A-Za-z_]\w*", last)
    if not m:
        return "unknown"
    if m.group(0) in _GLASS_CONTAINER_TYPES or any(n in last for n in _GLASS_PREVIEW_NAMES):
        return "panel"
    return "control" if m.group(0) in _GLASS_CONTROL_TYPES else None


def _glass_body(body: str, alpha: float, control: bool = False, allow_black: bool = False,
                action_alpha: float | None = None) -> str:
    def one(m):
        a = alpha * _GLASS_ALT_ROW_FACTOR if m.group(1).startswith("alternate") else alpha
        new = _glass_color(m.group(2), a, control, allow_black, action_alpha)
        return m.group(0) if new is None else m.group(1) + new
    return _GLASS_BG_RE.sub(one, body)


def _has_solid_background(qss: str) -> bool:
    for m in _GLASS_BG_RE.finditer(qss or ""):
        if m.group(1).startswith("alternate"):
            continue
        color = _parse_color(m.group(2))
        if color is not None and color[3] > 0:
            return True
    return False


def _is_control_widget(widget) -> bool:
    from PySide6.QtWidgets import (QAbstractSpinBox, QCheckBox, QComboBox, QHeaderView, QLineEdit,
                                   QProgressBar, QPushButton, QRadioButton, QScrollBar, QTabBar,
                                   QToolButton)
    return isinstance(widget, (QLineEdit, QAbstractSpinBox, QComboBox, QPushButton, QToolButton,
                               QProgressBar, QScrollBar, QHeaderView, QTabBar, QCheckBox, QRadioButton))


def _is_panel_widget(widget) -> bool:
    from PySide6.QtWidgets import (QAbstractButton, QAbstractSlider, QAbstractSpinBox, QComboBox,
                                   QHeaderView, QLabel, QLineEdit, QMenu, QPlainTextEdit,
                                   QProgressBar, QTabBar, QTextEdit)
    controls = (QAbstractButton, QAbstractSlider, QAbstractSpinBox, QComboBox, QHeaderView, QLabel,
                QLineEdit, QMenu, QPlainTextEdit, QProgressBar, QTabBar, QTextEdit)
    return not isinstance(widget, controls)


def _layout_has(layout, widget) -> bool:
    """Si `widget` está en `layout` o en alguno de sus sub-layouts. Con indexOf y
    findChildren a propósito, nunca con itemAt(): Python se quedaba con los
    QLayoutItem que devuelve y, al soltarlos, Qt perdía el widget (pasó con la barra
    de scroll del Gestor)."""
    from PySide6.QtWidgets import QLayout
    if layout.indexOf(widget) >= 0:
        return True
    return any(sub.indexOf(widget) >= 0 for sub in layout.findChildren(QLayout))


def _is_floating(widget) -> bool:
    """Flota encima del contenido: su padre tiene layout pero él no está en él (lo
    posicionan a mano, como los popovers, Posprocesar o el modal de Ajustes)."""
    from PySide6.QtWidgets import QWidget
    parent = widget.parentWidget()
    # QWidget.layout(...) y no parent.layout(): algunas clases de DowP guardan su
    # layout en un atributo "self.layout", que tapa el método.
    layout = QWidget.layout(parent) if parent is not None else None
    return layout is not None and not _layout_has(layout, widget)


def _is_frosted_candidate(widget, floating: bool) -> bool:
    """Lo que flota y lleva vidrio recortado: popovers, paneles ocultables en modo
    superpuesto y Posprocesar del Modo Rápido. Otras cosas que flotan (velos, chips
    sobre el video, indicadores) quedan sólidas."""
    if widget.objectName().endswith("Popover") or widget.property("dockMode") == "overlay":
        return True
    return floating and widget.inherits("RecodeOptionsWidget")


def _paints_glass_background(widget) -> bool:
    """Si el widget pinta un fondo liso propio (que con imagen se vuelve translúcido)."""
    cached = _GLASS_PAINTS.get(widget)
    if cached is not None:
        return cached
    name = widget.objectName()
    if name == "collapsiblePanel" and widget.property("dockMode") != "overlay":
        # Solo tiene fondo al flotar. Acoplado no es una capa: si contara, su contenido
        # quedaba como "anidado" (casi transparente) sin nada detrás.
        _GLASS_PAINTS[widget] = False
        return False
    paints = bool(name and name in _GLASS_MAIN["names"]) or any(widget.inherits(t) for t in _GLASS_MAIN["types"])
    if not paints:
        raw = _THEMED_RAW.get(widget)
        try:
            paints = _has_solid_background(raw() if raw is not None else widget.styleSheet())
        except Exception:
            paints = False
    _GLASS_PAINTS[widget] = paints
    return paints


# Construcción de una pestaña (ver glass_building): los widgets nacen sin padre, y si la
# hoja sale sólida hay que rehacerla al meterlos en la ventana, lo que vuelve a estilizar
# a todos sus hijos. Mientras se construye se supone cómo van a quedar; refresh_glass
# solo rehace las que no acertaron.
_GLASS_BUILDING = [False]
_GLASS_ASSUMED = _weakref.WeakSet()


def _assumed_status(widget) -> str | None:
    """Estado probable de un widget todavía suelto. No se guarda en la caché."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog, QMainWindow
    name = widget.objectName()
    if name == GLASS_CANVAS_NAME or name in _GLASS_SOLID_NAMES or isinstance(widget, (QDialog, QMainWindow)):
        return None
    # Sin padre Qt lo llama ventana, pero solo está suelto; con padre, sí es una ventana.
    kind = widget.windowType()
    if kind not in (Qt.Widget, Qt.Window) or (kind == Qt.Window and widget.parentWidget() is not None):
        return None
    # Sin mirar si flota: su padre puede tener layout y no haberlo agregado todavía.
    control = _is_control_widget(widget)
    if not control and not _is_panel_widget(widget) and name not in _GLASS_PREVIEW_NAMES:
        return None
    if control:
        return "control"
    if _is_frosted_candidate(widget, _is_floating(widget)):
        return "frosted"
    a = widget.parentWidget()
    while a is not None:
        if glass_status(a) in ("outer", "nested", "frosted") and _paints_glass_background(a):
            return "nested"
        a = a.parentWidget()
    return "outer"


def glass_building():
    """Para envolver la construcción de una pestaña que irá dentro del lienzo."""
    from contextlib import contextmanager

    @contextmanager
    def scope():
        _GLASS_BUILDING[0] = True
        try:
            yield
        finally:
            _GLASS_BUILDING[0] = False
    return scope()


def glass_status(widget) -> str | None:
    """Estado del widget con imagen de fondo (ver el comentario de arriba)."""
    if widget is None:
        return None
    try:
        if widget in _GLASS_STATUS:
            return _GLASS_STATUS[widget]
    except TypeError:
        return None
    if _GLASS_BUILDING[0]:
        return _assumed_status(widget)
    status = None
    name = widget.objectName()
    if not widget.isWindow() and name != GLASS_CANVAS_NAME and name not in _GLASS_SOLID_NAMES:
        floating = _is_floating(widget)
        frosted = _is_frosted_candidate(widget, floating)
        control = _is_control_widget(widget)
        panel = _is_panel_widget(widget) or name in _GLASS_PREVIEW_NAMES
        if (control or panel) and (frosted or not floating):
            a = widget.parentWidget()
            nested = reached = False
            while a is not None:
                if a.objectName() == GLASS_CANVAS_NAME:
                    reached = True
                    break
                if a.isWindow():  # otra ventana (diálogo, lista desplegable): fuera del lienzo
                    break
                if glass_status(a) in ("outer", "nested", "frosted") and _paints_glass_background(a):
                    nested = reached = True  # ese panel ya está dentro del lienzo
                    break
                a = a.parentWidget()
            if reached:
                if control:
                    status = "control"
                elif frosted:
                    status = "frosted"
                else:
                    status = "nested" if nested else "outer"
    _GLASS_STATUS[widget] = status
    if status == "frosted" and widget not in _GLASS_FROSTED_HOOKED:
        widget.installEventFilter(_frosted_painter())
        _GLASS_FROSTED_HOOKED.add(widget)
    return status


def _glass_forget():
    _GLASS_STATUS.clear()
    _GLASS_PAINTS.clear()
    _GLASS_ACTION_RGB.clear()
    _GLASS_ALPHA_CACHE.clear()


_GLASS_ALPHA_CACHE: list = []  # [opacidad de paneles o None]: glass_fill corre en cada repintado
_GLASS_CHECKER_FLOOR = 0.35   # la cuadrícula nunca baja de esto: tiene que seguir viéndose


def _cached_glass_alpha():
    if not _GLASS_ALPHA_CACHE:
        from core.utils.background_images import glass_alpha
        _GLASS_ALPHA_CACHE.append(glass_alpha())
    return _GLASS_ALPHA_CACHE[0]


def glass_previews_transparent(widget) -> bool:
    """Si está activa la opción "Transparentar vistas previas" para este widget."""
    if widget is None or _cached_glass_alpha() is None or not _inside_glass_area(widget):
        return False
    from core.utils.background_images import get_previews_transparent
    return get_previews_transparent()


def glass_preview_fill(widget, color):
    """Relleno alrededor del medio en una vista previa: sólido, o translúcido como un panel con
    "Transparentar vistas previas"."""
    from PySide6.QtGui import QColor
    return glass_fill(widget, color) if glass_previews_transparent(widget) else QColor(color)


def glass_checker_colors(widget, color_a, color_b):
    """Los dos colores de la cuadrícula de transparencia para `widget`: sólidos, translúcidos
    con "Transparentar vistas previas" (nunca menos que _GLASS_CHECKER_FLOOR), o None si está
    apagada "Mostrar cuadrícula de transparencia"."""
    from PySide6.QtGui import QColor
    from core.utils.background_images import get_preview_checker
    if widget is not None and not get_preview_checker():
        return None
    a, b = QColor(color_a), QColor(color_b)
    if glass_previews_transparent(widget):
        f = max(_cached_glass_alpha(), _GLASS_CHECKER_FLOOR)
        a.setAlpha(round(255 * f))
        b.setAlpha(round(255 * f))
    return a, b


# ── Vidrio recortado en ventanas aparte: menús y listas desplegables ──────────
_GLASS_POPUP_PAINTER = None


def _glass_canvas_for_popup(anchor):
    """El lienzo con imagen del que cuelga un menú o un combo, o None: si está dentro de
    un diálogo (detrás tiene el diálogo sólido, no la imagen) queda sólido. En Wayland
    una ventana no conoce su posición en pantalla, así que también."""
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QMenu
    if _cached_glass_alpha() is None or QGuiApplication.platformName().startswith("wayland"):
        return None
    w = anchor
    while isinstance(w, QMenu):  # un submenú cuelga de otro menú: importa el de arriba
        w = w.parentWidget()
    while w is not None:
        if w.objectName() == GLASS_CANVAS_NAME:
            break
        if w.isWindow():
            central = getattr(w, "centralWidget", lambda: None)()
            w = central if central is not None and central.objectName() == GLASS_CANVAS_NAME else None
            break
        w = w.parentWidget()
    return w if w is not None and getattr(w, "has_image", lambda: False)() else None


def _glass_popup_entry(popup):
    """(lienzo, widget con la regla de vidrio) de una ventana con vidrio, o None. Se busca
    al pintar: el objeto Python de la ventana de un combo es temporal, así que no sirve
    como clave de un diccionario débil."""
    from PySide6.QtWidgets import QAbstractItemView
    styled = popup if popup.property("glass") == "menu" else popup.findChild(QAbstractItemView)
    if styled is None or styled.property("glass") != "menu":
        return None
    canvas = _glass_canvas_for_popup(popup.parentWidget())
    return (canvas, styled) if canvas is not None else None


def _glass_popup_painter():
    global _GLASS_POPUP_PAINTER
    if _GLASS_POPUP_PAINTER is None:
        from PySide6.QtCore import QEvent, QObject, QRectF
        from PySide6.QtGui import QPainter, QPainterPath

        class _PopupPainter(QObject):
            def eventFilter(self, obj, event):
                if event.type() == QEvent.Paint:
                    entry = _glass_popup_entry(obj)
                    if entry is not None:
                        canvas, shaped = entry
                        if shaped.property("scrollFrame"):
                            return False  # lo pinta paint_combo_scroll_frame
                        p = QPainter(obj)
                        # Afuera de la forma redondeada, nada. La lista del combo además
                        # es más chica que su ventana; un menú la ocupa entera.
                        from core.utils.theme_loader import get_active_shapes
                        radius = get_active_shapes()["radio"]
                        path = QPainterPath()
                        path.addRoundedRect(QRectF(obj.rect() if shaped is obj else shaped.geometry()),
                                            radius, radius)
                        p.setRenderHint(QPainter.Antialiasing)
                        p.setClipPath(path)
                        canvas.paint_backdrop_for_popup(p, obj)
                        p.end()
                return False

        _GLASS_POPUP_PAINTER = _PopupPainter()
    return _GLASS_POPUP_PAINTER


def _relative_luminance(color) -> float:
    def channel(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(color.red()) + 0.7152 * channel(color.green()) + 0.0722 * channel(color.blue())


def _contrast_ratio(a, b) -> float:
    la, lb = _relative_luminance(a), _relative_luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _blend_until_contrast(background, target_color, ratio: float) -> str:
    """El primer color entre `background` y `target_color` que contrasta `ratio` contra
    el fondo: así el resultado sale igual de visible en todos los temas."""
    from PySide6.QtGui import QColor
    bg, fg = QColor(background), QColor(target_color)
    for step in range(1, 51):
        t = step / 50
        mix = QColor(round(bg.red() + (fg.red() - bg.red()) * t),
                     round(bg.green() + (fg.green() - bg.green()) * t),
                     round(bg.blue() + (fg.blue() - bg.blue()) * t))
        if _contrast_ratio(mix, bg) >= ratio:
            return mix.name()
    return fg.name()


_MENU_BORDER_CONTRAST = 1.8    # sin sombra, el borde es lo que separa el menú del fondo
_MENU_DISABLED_CONTRAST = 3.2  # se lee, y sigue muy por debajo del texto normal (10:1 o más)
_MENU_GLASS_DISABLED_CONTRAST = 4.0  # sobre vidrio: lo que hay detrás le resta contraste


def menu_contrast_rules() -> str:
    """Borde, separadores y opciones deshabilitadas de los menús, calculados a partir del
    fondo y el texto del tema activo. Los tokens borde_normal y texto_deshabilitado sirven
    para botones y campos, pero en un menú casi no se ven (contraste de 1,1 y de 2)."""
    from PySide6.QtGui import QColor
    bg = get_theme_token("fondo_secundario", "#121212")
    text = get_theme_token("texto_principal", "#e0e0e0")
    if not QColor(bg).isValid() or not QColor(text).isValid():  # un degradado: queda el del tema
        return ""
    border = _blend_until_contrast(bg, text, _MENU_BORDER_CONTRAST)
    disabled = _blend_until_contrast(bg, text, _MENU_DISABLED_CONTRAST)
    glass_disabled = _blend_until_contrast(bg, text, _MENU_GLASS_DISABLED_CONTRAST)
    return (f"\nQMenu {{ border-color: {border}; }}"
            f"\nQMenu::separator {{ background-color: {border}; }}"
            f"\nQMenu::item:disabled {{ color: {disabled}; }}"
            f'\nQMenu[glass="menu"]::item:disabled {{ color: {glass_disabled}; }}\n')


def prepare_menu_window(menu):
    """Ventana transparente y sin marco para que el menú tome la forma del tema, igual que
    la lista de un combo. Windows redondea por su cuenta las ventanas opacas, con un radio
    fijo que ignora el tema. Debe correr antes de que exista la ventana nativa (al evento
    Polish): más tarde quedan esquinas negras."""
    from PySide6.QtCore import Qt
    if menu.testAttribute(Qt.WA_TranslucentBackground) or menu.isVisible():
        return
    menu.setAttribute(Qt.WA_TranslucentBackground, True)
    menu.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)


def glass_prepare_popup(popup, styled=None):
    """Al abrirse un menú o una lista desplegable: con imagen de fondo lleva vidrio
    recortado, con la opacidad de los paneles flotantes. `popup` es la ventana y `styled`
    el widget al que se aplica la regla [glass="menu"] (la vista, en un combo)."""
    styled = styled if styled is not None else popup
    canvas = _glass_canvas_for_popup(popup.parentWidget())
    if canvas is not None:
        popup.removeEventFilter(_glass_popup_painter())  # sin duplicar si se abre otra vez
        popup.installEventFilter(_glass_popup_painter())
    value = "menu" if canvas is not None else None
    if styled.property("glass") != value:
        styled.setProperty("glass", value)
        styled.style().unpolish(styled)
        styled.style().polish(styled)
    if styled is not popup:
        _glass_clear_list_palette(styled, value is not None or bool(styled.property("scrollFrame")))


def set_combo_scroll_frame(view, active: bool):
    """Lista con flechas: la vista deja de pintar marco y fondo, y los pone su ventana."""
    if bool(view.property("scrollFrame")) == active:
        return
    view.setProperty("scrollFrame", True if active else None)
    view.style().unpolish(view)
    view.style().polish(view)
    _glass_clear_list_palette(view, active or view.property("glass") is not None)


def paint_combo_scroll_frame(container):
    """Fondo y borde de una lista con flechas: una sola pieza redondeada que abarca la
    lista y las franjas. Con imagen de fondo lleva el mismo vidrio que el resto."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
    from core.utils.theme_loader import get_active_shapes
    radius = get_active_shapes()["radio"]
    path = QPainterPath()
    path.addRoundedRect(QRectF(container.rect()).adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
    fill = QColor(get_theme_token("fondo_terciario", "#161616"))
    p = QPainter(container)
    p.setRenderHint(QPainter.Antialiasing)
    entry = _glass_popup_entry(container)
    if entry is not None:
        p.save()
        p.setClipPath(path)
        entry[0].paint_backdrop_for_popup(p, container)
        p.restore()
        fill.setAlphaF(_cached_glass_alpha())
    p.fillPath(path, fill)
    p.setPen(QPen(QColor(get_theme_token("acento_primario", "#B9E640")), 1))
    p.drawPath(path)
    p.end()


def paint_combo_scroller_arrow(scroller, down: bool):
    """La flecha de una franja de desplazamiento, sin fondo: se ve el marco de detrás."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QPainter, QPolygonF
    token = "texto_principal" if scroller.underMouse() else "texto_secundario"
    cx, cy = scroller.width() / 2, scroller.height() / 2
    tip = 2.5 if down else -2.5
    p = QPainter(scroller)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(get_theme_token(token, "#c2c2c2")))
    p.drawPolygon(QPolygonF([QPointF(cx - 5, cy - tip), QPointF(cx + 5, cy - tip), QPointF(cx, cy + tip)]))
    p.end()


def _glass_clear_list_palette(view, clear: bool):
    """La lista de un combo (QComboBoxListView) borra su viewport con el color de la
    paleta antes de pintar las filas, y eso tapaba el vidrio: con la paleta transparente
    ese borrado no pinta nada."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPalette
    viewport = view.viewport()
    if not clear:
        viewport.setPalette(QPalette())
        return
    palette = viewport.palette()
    for role in (QPalette.Window, QPalette.Base):
        palette.setColor(role, Qt.transparent)
    viewport.setPalette(palette)


def _has_glass_ancestor(widget) -> bool:
    a = widget.parentWidget()
    while a is not None and a.objectName() != GLASS_CANVAS_NAME:
        if a.isWindow():
            return False
        if glass_status(a) in ("outer", "nested", "frosted") and _paints_glass_background(a):
            return True
        a = a.parentWidget()
    return False


def glass_fill(widget, color, kind: str = "panel"):
    """El color de fondo que un widget pintado a mano (QPainter) tiene que usar con
    imagen de fondo: el mismo color, con la opacidad de un panel ("panel", menor si
    está dentro de otro panel translúcido) o de un control ("control"). Sin imagen, o
    fuera de la ventana principal, devuelve el color tal cual. Para la barra de
    progreso, el botón de lotes, la onda de audio, el reproductor vacío..."""
    from PySide6.QtGui import QColor
    c = QColor(color)
    alpha = _cached_glass_alpha()
    if alpha is None or widget is None or not _inside_glass_area(widget):
        return c
    if kind == "control":
        f = glass_alpha_for("control", alpha)
    else:
        f = alpha * _GLASS_NESTED_FACTOR if _has_glass_ancestor(widget) else alpha
    c.setAlpha(round(c.alpha() * f))
    return c


def _inside_glass_area(widget) -> bool:
    """Si el widget está dentro del lienzo de la ventana principal (no en un diálogo)."""
    w = widget
    while w is not None:
        if w.objectName() == GLASS_CANVAS_NAME:
            return True
        if w.isWindow():
            return False
        w = w.parentWidget()
    return False


def _glass_canvas_of(widget):
    w = widget.parentWidget()
    while w is not None and w.objectName() != GLASS_CANVAS_NAME:
        if w.isWindow():
            return None
        w = w.parentWidget()
    return w


_FROSTED_PAINTER = None


def _frosted_painter():
    """Filtro de pintado del vidrio recortado: antes de los hijos, pinta el pedazo
    desenfocado de la imagen de fondo que le toca al widget y vuelve a pintar su fondo
    translúcido encima (Qt ya lo pintó antes de este filtro y quedaría tapado)."""
    global _FROSTED_PAINTER
    if _FROSTED_PAINTER is None:
        from PySide6.QtCore import QEvent, QObject, QRectF
        from PySide6.QtGui import QPainter, QPainterPath
        from PySide6.QtWidgets import QStyle, QStyleOption

        class _FrostedPainter(QObject):
            def eventFilter(self, obj, event):
                if event.type() != QEvent.Paint or glass_status(obj) != "frosted":
                    return False
                canvas = _glass_canvas_of(obj)
                if canvas is None or not hasattr(canvas, "paint_backdrop") or not canvas.has_image():
                    return False
                m = _GLASS_RADIUS_RE.search(_THEMED_RAW[obj]() if obj in _THEMED_RAW else obj.styleSheet())
                radius = float(m.group(1)) if m else 8.0
                p = QPainter(obj)
                path = QPainterPath()
                path.addRoundedRect(QRectF(obj.rect()), radius, radius)
                p.setClipPath(path)
                canvas.paint_backdrop(p, obj)
                p.setClipping(False)
                opt = QStyleOption()
                opt.initFrom(obj)
                obj.style().drawPrimitive(QStyle.PE_Widget, opt, p, obj)
                p.end()
                return False

        _FROSTED_PAINTER = _FrostedPainter()
    return _FROSTED_PAINTER


def apply_glass(qss: str, widget) -> str:
    """Hoja local de un widget con sus fondos translúcidos según su estado (ver
    glass_status). Sin imagen de fondo, o si el widget queda sólido, la deja intacta."""
    from core.utils.background_images import glass_alpha
    panel_alpha = glass_alpha()
    if panel_alpha is None or not qss or widget is None:
        return qss
    status = glass_status(widget)
    if status is None:
        return qss
    own = glass_alpha_for(status, panel_alpha)
    action = glass_alpha_for("action", panel_alpha)
    preview = widget.objectName() in _GLASS_PREVIEW_NAMES
    if "{" not in qss:  # declaraciones sueltas: se aplican al propio widget
        return _glass_body(qss, own, control=status == "control", allow_black=preview, action_alpha=action)
    panel_own = glass_alpha_for(status if status != "control" else "outer", panel_alpha)

    def rule(m):
        if preview and not any(n in m.group(1) for n in _GLASS_SOLID_NAMES):
            # Vista previa: su propia hoja (selector "QLabel", etc.) va como panel.
            return m.group(1) + "{" + _glass_body(m.group(2), panel_own, allow_black=True) + "}"
        kinds = [_glass_kind(s) for s in m.group(1).split(",")]
        if any(k is None for k in kinds):
            return m.group(0)
        if all(k == "control" for k in kinds) or (status == "control" and "panel" not in kinds):
            return m.group(1) + "{" + _glass_body(m.group(2), glass_alpha_for("control", panel_alpha), True,
                                                  action_alpha=action) + "}"
        if "control" in kinds:
            return m.group(0)  # mezcla rara de panel y control: se deja como está
        return m.group(1) + "{" + _glass_body(m.group(2), panel_own, allow_black=preview) + "}"
    return _GLASS_RULE_RE.sub(rule, qss)


def _glass_inactive_tab_color() -> str:
    """Mezcla del texto normal (75 %) y el de pestaña inactiva: se lee sobre la imagen,
    pero sigue siendo más apagado que la pestaña activa."""
    from PySide6.QtGui import QColor
    strong = QColor(get_theme_token("texto_principal", "#e0e0e0"))
    weak = QColor(get_theme_token("tab_texto_inactivo", "#666666"))
    mix = lambda a, b: round(a * _GLASS_TAB_TEXT_MIX + b * (1 - _GLASS_TAB_TEXT_MIX))
    return QColor(mix(strong.red(), weak.red()), mix(strong.green(), weak.green()),
                  mix(strong.blue(), weak.blue())).name()


def _with_glass_attr(selector: str, value: str) -> str:
    """'QFrame#x:hover' -> 'QFrame#x[glass="outer"]:hover' (la condición va en el
    último elemento, antes de sus pseudo-estados o subcontroles)."""
    head, _, last = selector.rpartition(" ")
    cut = last.find(":")
    last = (last + f'[glass="{value}"]') if cut < 0 else (last[:cut] + f'[glass="{value}"]' + last[cut:])
    return f"{head} {last}".strip()


def glass_main_rules(qss: str) -> str:
    """Reglas extra para la hoja de la ventana: cada regla de panel o control con fondo
    liso se repite, limitada a lo que está dentro del lienzo (#dowpCanvas ...) y al
    estado que refresh_glass marca en cada widget (propiedad "glass"). Al ser más
    específicas ganan, y lo que no está marcado (diálogos, listas desplegables) no se
    toca. Vacío si no hay imagen de fondo."""
    from core.utils.background_images import glass_alpha
    _GLASS_MAIN["names"].clear()
    _GLASS_MAIN["types"].clear()
    _GLASS_ACTION_RGB.clear()
    alpha = glass_alpha()
    if alpha is None:
        return ""
    # Sin comentarios: el que va antes de una regla quedaba pegado a su selector, y la
    # copia salía con un selector inválido que Qt descartaba entera.
    qss = re.sub(r"/\*.*?\*/", "", qss, flags=re.S)
    extra = []
    for m in _GLASS_RULE_RE.finditer(qss):
        by_kind = {"panel": [], "control": []}
        for s in m.group(1).split(","):
            k = _glass_kind(s)
            if k in by_kind:
                by_kind[k].append(s.strip())
        for kind, selectors in by_kind.items():
            if not selectors:
                continue
            variants = (("outer", "outer"), ("nested", "nested"), ("frosted", "frosted")) if kind == "panel" \
                else (("control", "control"),)
            rules = []
            changed = False
            for value, status in variants:
                decls = []
                for d in _GLASS_BG_RE.finditer(m.group(2)):
                    a = glass_alpha_for(status, alpha)
                    if d.group(1).startswith("alternate"):
                        a *= _GLASS_ALT_ROW_FACTOR
                    new = _glass_color(d.group(2), a, control=kind == "control",
                                       action_alpha=glass_alpha_for("action", alpha))
                    prop = d.group(1).split(":")[0].strip()
                    # Lo que no se transparenta (transparente, tintes, negro) se copia igual:
                    # la copia tiene que existir para no perder contra la copia de una regla
                    # más general.
                    decls.append(f"{prop}: {new if new is not None else d.group(2).strip()};")
                    changed = changed or new is not None
                if decls:
                    scoped = ", ".join(f"QWidget#{GLASS_CANVAS_NAME} {_with_glass_attr(s, value)}" for s in selectors)
                    rules.append(f"{scoped} {{ {' '.join(decls)} }}")
            if rules and kind == "panel" and changed:
                for s in selectors:
                    last = s.split()[-1]
                    name = re.search(r"#(\w+)", last)
                    t = re.match(r"[A-Za-z_]\w*", last)
                    if name:
                        _GLASS_MAIN["names"].add(name.group(1))
                    elif t and t.group(0) not in ("QWidget", "QFrame"):
                        _GLASS_MAIN["types"].add(t.group(0))
            extra.extend(rules)
    # Las cabeceras de las listas pintan un fondo propio debajo de sus secciones, y las
    # áreas con scroll, el color de la paleta en su viewport, detrás de su contenido
    # (tapaba, por ejemplo, todo el panel de Opciones de Multimedia). El fondo de un
    # QScrollArea se controla en él, no en su viewport. Su contenido tiene el suyo.
    extra.append(f"QWidget#{GLASS_CANVAS_NAME} QHeaderView {{ background: transparent; }}")
    extra.append(f"QWidget#{GLASS_CANVAS_NAME} QScrollArea {{ background: transparent; }}")
    # Igual en los visores (QGraphicsView): el relleno y la cuadrícula los pintan ellos.
    extra.append(f"QWidget#{GLASS_CANVAS_NAME} QGraphicsView {{ background: transparent; }}")
    # Pestañas no seleccionadas (principales e internas): su color tenue se pierde sobre
    # una imagen, así que van casi con el color de texto normal.
    extra.append(f"QWidget#{GLASS_CANVAS_NAME} QTabBar::tab:!selected {{ color: {_glass_inactive_tab_color()}; }}")
    # Menús y listas desplegables con vidrio recortado (ver glass_prepare_popup). Sin
    # "#dowpCanvas": son ventanas aparte; lo que limita es la propiedad.
    menu_bg = _glass_color(get_theme_token("fondo_secundario", "#121212"), alpha, allow_black=True)
    list_bg = _glass_color(get_theme_token("fondo_terciario", "#161616"), alpha, allow_black=True)
    extra.append(f'QMenu[glass="menu"] {{ background-color: {menu_bg}; }}')
    extra.append(f'QComboBox QAbstractItemView[glass="menu"] {{ background-color: {list_bg}; }}')
    return "\n/* Imagen de fondo: paneles translúcidos */\n" + "\n".join(extra)


def refresh_glass(root=None) -> int:
    """Recalcula qué va translúcido bajo `root` (el lienzo, una pestaña recién
    construida o un panel que cambió de modo): marca la propiedad "glass" que usan las
    reglas de la ventana y vuelve a calcular las hojas registradas con
    set_themed_style. Hace falta después de meter widgets en la ventana (cuando se
    crearon todavía no estaban dentro del lienzo) y al poner o quitar la imagen. Solo
    toca lo que cambia."""
    import shiboken6
    from PySide6.QtWidgets import QWidget
    from core.utils.background_images import glass_alpha
    _glass_forget()
    active = glass_alpha() is not None
    marked = []
    restyled = set()
    if root is not None:
        for w in [root] + root.findChildren(QWidget):
            value = (glass_status(w) or "") if active else ""
            if (w.property("glass") or "") != value:
                w.setProperty("glass", value or None)
                marked.append(w)
            if value == "frosted":
                w.update()
        # Los ayudantes con estado (apply_*_button_style) también pasan por la
        # transparencia. Sin imagen no hace falta: al quitarla, el cambio de tema ya los
        # vuelve a llamar a todos (y así el arranque normal no paga nada extra).
        if active:
            for widget, calls in list(_THEMED_CALLS.items()):
                try:
                    if not shiboken6.isValid(widget) or not (widget is root or root.isAncestorOf(widget)):
                        continue
                    for fn, args, kwargs in list(calls.values()):
                        fn() if args is None else fn(widget, *args, **kwargs)
                except RuntimeError:
                    _THEMED_CALLS.pop(widget, None)
        if active or marked:
            root.update()  # lo que se dibuja a mano (barra de progreso, onda...) usa glass_fill
    updated = 0
    # Lo construido suponiendo que iba dentro y que al final quedó fuera de `root` (un
    # diálogo, un widget suelto): también hay que corregirlo.
    assumed = set(_GLASS_ASSUMED)
    if not _GLASS_BUILDING[0]:
        _GLASS_ASSUMED.clear()
    for widget, (builder, qss) in list(_THEMED_STYLES.items()):
        if not shiboken6.isValid(widget):
            _THEMED_STYLES.pop(widget, None)
            continue
        try:
            if (root is not None and widget is not root and not root.isAncestorOf(widget)
                    and (_GLASS_BUILDING[0] or widget not in assumed)):
                continue
            if widget.styleSheet() != qss:
                continue
            new_qss = builder()
            if new_qss != qss:
                widget.setStyleSheet(new_qss)
                _THEMED_STYLES[widget] = (builder, new_qss)
                restyled.add(widget)
                updated += 1
        except RuntimeError:
            _THEMED_STYLES.pop(widget, None)
    # Poner una hoja ya vuelve a estilizar al widget y a todo lo que cuelga de él: las
    # marcas nuevas solo piden repulir lo que ninguna hoja alcanzó (es lo caro: cada
    # repulido recalcula tamaños y reglas).
    for w in marked:
        a = w
        while a is not None and a not in restyled and a is not root:
            a = a.parentWidget()
        if a is None or a not in restyled:
            w.style().unpolish(w)
            w.style().polish(w)
    if updated or marked:
        logger.debug(f"Fondo: {updated} hojas y {len(marked)} marcas recalculadas "
                     f"({'con' if active else 'sin'} transparencia)")
    return updated


def set_themed_style(widget, builder):
    """Aplica builder() como hoja de estilos del widget y la recuerda para recalcularla
    cuando cambie el tema o el modo (ThemeManager -> refresh_themed_styles).

    builder es una función sin argumentos que solo debe depender de get_theme_token(...):
    así, volver a llamarla con el tema nuevo da el estilo correcto."""
    # Referencia débil: la entrada vive en un WeakKeyDictionary con el widget de clave,
    # y un lambda que lo retuviera impediría liberarlo.
    ref = _weakref.ref(widget)
    raw = lambda: apply_shapes(builder())
    shaped = lambda: apply_glass(raw(), ref())
    _THEMED_RAW[widget] = raw
    _GLASS_PAINTS.pop(widget, None)
    qss = shaped()
    if _GLASS_BUILDING[0]:
        _GLASS_ASSUMED.add(widget)
    widget.setStyleSheet(qss)
    _THEMED_STYLES[widget] = (shaped, qss)


# Ayudantes de estilo con estado (apply_*_button_style): al cambiar de tema se vuelven a
# llamar con los MISMOS argumentos, así se recalculan estilo e icono teñido juntos. Una
# entrada por (widget, ayudante): la última llamada (el estado actual) es la que vale.
_THEMED_CALLS = _weakref.WeakKeyDictionary()


def _prune_themed_calls():
    import shiboken6
    for widget in list(_THEMED_CALLS.keys()):
        if not shiboken6.isValid(widget):
            _THEMED_CALLS.pop(widget, None)


def _themed_calls_for(widget):
    """Las llamadas suelen guardar métodos del propio widget (referencia fuerte): al
    destruirse el widget se quita su entrada, para no retener su objeto Python."""
    try:
        if widget in _THEMED_CALLS:
            return _THEMED_CALLS[widget]
        calls = _THEMED_CALLS.setdefault(widget, {})
    except TypeError:
        return None
    try:
        from PySide6.QtCore import QTimer
        widget.destroyed.connect(lambda *_: QTimer.singleShot(0, _prune_themed_calls))
    except (AttributeError, RuntimeError):
        pass
    return calls


def _remember_for_theme(widget, fn, *args, **kwargs):
    """Lo llaman los ayudantes apply_* al aplicarse: guarda cómo repetir la llamada."""
    calls = _themed_calls_for(widget)
    if calls is not None:
        calls[fn.__name__] = (fn, args, kwargs)


def register_theme_callback(widget, key: str, callback):
    """Como _remember_for_theme, para métodos con estado: callback() sin argumentos
    (normalmente un lambda que repite la llamada con el estado actual). Se vuelve a
    ejecutar al cambiar de tema mientras el widget exista; la última de cada key vale."""
    calls = _themed_calls_for(widget)
    if calls is not None:
        calls[key] = (callback, None, None)


def refresh_themed_styles() -> int:
    """Recalcula los estilos registrados con set_themed_style. Se salta los widgets ya
    destruidos y los que otro código cambió después con setStyleSheet() (por ejemplo,
    un estado de 'descargando'): pisarlos con el estilo registrado sería un error."""
    import shiboken6
    _glass_forget()
    updated = 0
    for widget, calls in list(_THEMED_CALLS.items()):
        if not shiboken6.isValid(widget):
            _THEMED_CALLS.pop(widget, None)
            continue
        for fn, args, kwargs in list(calls.values()):
            try:
                if args is None:
                    fn()
                else:
                    fn(widget, *args, **kwargs)
                updated += 1
            except RuntimeError:
                _THEMED_CALLS.pop(widget, None)
                break
    for widget, (builder, qss) in list(_THEMED_STYLES.items()):
        if not shiboken6.isValid(widget):
            _THEMED_STYLES.pop(widget, None)
            continue
        try:
            if widget.styleSheet() != qss:
                continue
            new_qss = builder()
            if new_qss != qss:  # re-aplicar una hoja idéntica solo cuesta tiempo
                widget.setStyleSheet(new_qss)
                _THEMED_STYLES[widget] = (builder, new_qss)
            updated += 1
        except RuntimeError:
            _THEMED_STYLES.pop(widget, None)
    return updated


def get_theme_token(token_key: str, default_value: str = None) -> str:
    """
    Obtiene un token de color del tema activo (en el modo activo, claro u oscuro).
    """
    from core.utils.theme_loader import get_active_token
    return get_active_token(token_key, default_value)


def load_stylesheet(theme_name: str = None, font_family: str = None, tokens: dict = None) -> str:
    """
    Genera el QSS final.

    1. Lee _base.qss (template con {{variables}})
    2. Toma los tokens: los recibidos, o los del tema activo (ya resueltos según el
       modo claro/oscuro por core/utils/theme_loader.py)
    3. Inyecta la fuente activa (font_manager o tema) en {{fuente_principal}}
    4. Genera los SVGs dinámicos con el color de acento
    5. Reemplaza todas las {{variables}} por sus valores
    6. Retorna el QSS listo para aplicar
    """
    from core.utils.font_manager import get_active_font_family, system_ui_family
    from core.utils.theme_loader import get_active_tokens

    # 1. Cargar template base
    template = _load_base_template()
    if not template:
        logger.warning("Temas: Template vacío, usando estilos por defecto")
        return ""

    # 2. Tokens (copia: lo de abajo agrega claves que no son del tema)
    tokens = dict(tokens if tokens is not None else get_active_tokens())
    if not tokens:
        logger.warning("Temas: No hay tokens de tema para generar los estilos")
        return ""

    # 3. Inyectar tipografía activa
    # Va dentro de la hoja: un nombre con comillas o llaves podría salirse de ella.
    from core.utils.theme_io import clean_font_name
    active_font = clean_font_name(font_family or get_active_font_family(theme_name)) or system_ui_family()
    tokens["fuente_principal"] = active_font
    tokens["fuente_sistema"] = system_ui_family()

    # 4. Generar SVGs dinámicos con el color de acento primario
    triangle_color = tokens.get("acento_primario", "#B9E640")
    triangle_path = generate_triangle_svg(triangle_color)
    tokens["icono_triangulo"] = triangle_path
    tokens["icono_spinbox_plus"] = _generate_spinbox_symbol_svg("plus", triangle_color)
    tokens["icono_spinbox_minus"] = _generate_spinbox_symbol_svg("minus", triangle_color)
    tokens["icono_radio_checked"] = _generate_radio_checked_svg(triangle_color)
    check_icon_color = tokens.get("boton_texto", "#000000")
    tokens["icono_checkbox_checked"] = _generate_checkbox_checked_svg(check_icon_color)

    # 5. Reemplazar todas las {{variables}}
    result = template
    for key, value in tokens.items():
        result = result.replace("{{" + key + "}}", value)

    # 6. Verificar si quedaron variables sin resolver
    import re
    unresolved = re.findall(r"\{\{(\w+)\}\}", result)
    if unresolved:
        logger.warning(f"Temas: Variables sin resolver: {unresolved}")

    result = apply_shapes(result)
    result += glass_main_rules(result)
    logger.info(f"Temas: estilos generados con tipografía '{active_font}'")
    return result


def set_button_variant(btn, variant: str):
    """
    Asigna una variante semántica al botón y reaplica el estilo en vivo si es necesario.
    Variantes: 'primary', 'accent-solid', 'secondary', 'accent-blue', 'accent-orange', 'danger'
    """
    btn.setProperty("variant", variant)
    if btn.style():
        btn.style().unpolish(btn)
        btn.style().polish(btn)
    btn.update()


# Valor con el que Qt representa "sin límite" en maximumWidth()/maximumHeight().
_QT_WIDGET_SIZE_MAX = 16777215


def _apply_fixed_size_qss(btn):
    """Vuelca al QSS del propio botón el tamaño que quien llama ya fijó con
    setFixedSize(). Sin esto, un botón de icono sale rectangular por más que se
    pida cuadrado.

    El motivo: QStyleSheetStyle::polish() recalcula el minimumSize del widget a
    partir de la hoja de estilos y PISA el que había dejado setFixedSize(). Alcanza
    con que alguna regla aplicable declare geometría -- y la regla genérica
    `QPushButton` de _base.qss declara `min-height: 18px` -- para que Qt dé por
    sentado que manda el QSS. El MÁXIMO sí sobrevive, así que el botón terminaba en
    min=(32,22) / max=(32,32) y el layout lo dibujaba con el alto de su sizeHint:
    22 px con un icono de 18. Reordenar las llamadas no sirve, porque el polish se
    repite en cada show().

    `padding: 0px` va incluido a propósito, y no es cosmético: min-width/min-height
    de Qt miden la caja de CONTENIDO, así que con el `padding: 2px` que trae
    #pathToolButton un mínimo de 32 pediría 36 y dejaría el mínimo por encima del
    máximo. Con padding 0 -- y `border: none`, que es lo que ya usan estas
    variantes -- la caja de contenido coincide con la del botón y la cuenta cierra
    exacta (comprobado a 30, 32 y 34 px).

    El tamaño se lee de maximumSize(), que es donde setFixedSize() lo dejó intacto,
    para que ningún llamador tenga que repetir un número que ya declaró."""
    width, height = btn.maximumWidth(), btn.maximumHeight()
    if width >= _QT_WIDGET_SIZE_MAX or height >= _QT_WIDGET_SIZE_MAX:
        # Sin tamaño fijo (o fijo en un solo eje, ej. un botón con texto): que siga
        # mandando el sizeHint de siempre, no hay nada que reponer.
        return
    btn.setStyleSheet(f"min-width: {width}px; min-height: {height}px; padding: 0px;")


def apply_folder_browse_button_style(btn, tooltip=None, icon_size=18, icon_name="folder_managed.svg"):
    """
    Aplica el estilo unificado al botón de examinar/configurar carpeta o ruta.
    - Icono: folder_managed.svg en negro (#000000) habilitado y gris (#777777) deshabilitado.
    - icon_name permite reutilizar el mismo estilo para otros ajustes.
    - Variante: 'accent-solid' (verde plano reactivo).
    """
    from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon
    from PySide6.QtCore import QSize
    dis_color = get_theme_token("texto_deshabilitado", "#777777")
    _remember_for_theme(btn, apply_folder_browse_button_style, tooltip=tooltip, icon_size=icon_size, icon_name=icon_name)
    btn.setIcon(get_colored_svg_icon(icon_name, get_theme_token("boton_acento_texto", "#000000"), size=icon_size, disabled_color_hex=dis_color))
    btn.setIconSize(QSize(icon_size, icon_size))
    if not btn.objectName():
        btn.setObjectName("pathToolButton")
    set_button_variant(btn, "accent-solid")
    # Después de set_button_variant(): es su repolish el que descarta el tamaño
    # fijo, así que reponerlo antes no serviría de nada.
    _apply_fixed_size_qss(btn)
    if tooltip:
        btn.setToolTip(tooltip)


def apply_folder_open_button_style(btn, tooltip=None, icon_size=18):
    """
    Aplica el estilo unificado al botón de abrir carpeta en el explorador.
    - Icono: folder_open.svg en negro (#000000) habilitado y gris (#777777) deshabilitado.
    - Variante: 'accent-solid' (verde plano reactivo).
    """
    from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon
    from PySide6.QtCore import QSize
    dis_color = get_theme_token("texto_deshabilitado", "#777777")
    _remember_for_theme(btn, apply_folder_open_button_style, tooltip=tooltip, icon_size=icon_size)
    btn.setIcon(get_colored_svg_icon("folder_open.svg", get_theme_token("boton_acento_texto", "#000000"), size=icon_size, disabled_color_hex=dis_color))
    btn.setIconSize(QSize(icon_size, icon_size))
    if not btn.objectName() and not btn.text():
        btn.setObjectName("pathToolButton")
    set_button_variant(btn, "accent-solid")
    # Después de set_button_variant(): es su repolish el que descarta el tamaño
    # fijo, así que reponerlo antes no serviría de nada.
    _apply_fixed_size_qss(btn)
    if tooltip:
        btn.setToolTip(tooltip)


def apply_download_action_button_style(btn, tooltip=None, icon_size=18):
    """
    Aplica el estilo unificado al botón de acción de descargar medio.
    - Icono: download.svg en negro (#000000) habilitado y gris (#777777) deshabilitado.
    - Variante: 'accent-solid' (verde plano reactivo).
    """
    from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon
    from PySide6.QtCore import QSize
    dis_color = get_theme_token("texto_deshabilitado", "#777777")
    _remember_for_theme(btn, apply_download_action_button_style, tooltip=tooltip, icon_size=icon_size)
    btn.setIcon(get_colored_svg_icon("download.svg", get_theme_token("boton_acento_texto", "#000000"), size=icon_size, disabled_color_hex=dis_color))
    btn.setIconSize(QSize(icon_size, icon_size))
    if not btn.objectName():
        btn.setObjectName("pathToolButton")
    set_button_variant(btn, "accent-solid")
    # Después de set_button_variant(): es su repolish el que descarta el tamaño
    # fijo, así que reponerlo antes no serviría de nada.
    _apply_fixed_size_qss(btn)
    if tooltip:
        btn.setToolTip(tooltip)


def apply_cut_button_style(btn, status="normal", icon_size=18, shape="circular", icon_name="content_cut.svg"):
    """
    Aplica el estilo unificado del botón de recorte de fragmentos
    basado en los tokens del tema actual.

    icon_name: ícono a usar (por defecto content_cut.svg, el de Modo Rápido) --
    mismo estilo cuadrado/circular y mismos 3 colores de estado para cualquier botón
    de "acción de corte" de la app, ej. control_camera.svg para el corte físico de
    subclips en subclip_dialog.py (ver conversación).

    Status:
      - 'normal': gris elegante (#2d2d2d / fondo_elemento) con hover claro
      - 'saved': verde (#1DC038 / acento_secundario)
      - 'unsaved': amarillo (#ffc107 / estado_aviso)

    Shape:
      - 'circular': círculo perfecto (radio = mitad de la altura). Para el botón
        overlay flotante sobre la miniatura del video, donde sigue la convención
        habitual de un badge circular sobre un preview.
      - 'square': el radio de 6px estándar de la app (igual que QPushButton en
        _base.qss / apply_player_play_button_style). Para el botón inline en la
        barra de Quick Mode, donde va codo a codo con controles rectangulares.
    """
    from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon
    
    colors = {
        "normal":  {
            "bg": get_theme_token('fondo_elemento', '#2d2d2d'),
            "hover": get_theme_token('seleccion_fondo', '#3d3d3d'),
            "border": f"1px solid {get_theme_token('borde_normal', '#3d3d3d')}",
            "icon": get_theme_token('texto_activo', '#FFFFFF')
        },
        "saved":   {
            "bg": get_theme_token('acento_secundario', '#1DC038'),
            "hover": get_theme_token('acento_primario', '#B9E640'),
            "border": "none",
            "icon": get_theme_token('boton_acento_texto', '#000000')
        },
        "unsaved": {
            "bg": get_theme_token('estado_aviso', '#ffc107'),
            "hover": "#ffdb58",
            "border": "none",
            "icon": "#000000"
        }
    }
    
    cfg = colors.get(status, colors["normal"])
    _remember_for_theme(btn, apply_cut_button_style, status=status, icon_size=icon_size, shape=shape, icon_name=icon_name)
    btn.setIcon(get_colored_svg_icon(icon_name, cfg["icon"], size=icon_size))
    
    if shape == "square":
        from core.utils.theme_loader import get_active_shapes
        radius = int(round(get_active_shapes()["radio"]))
    else:
        # Círculo perfecto: radio = mitad de la altura del botón
        radius = 17
        if hasattr(btn, 'height') and btn.height() > 0:
            radius = btn.height() // 2
        elif hasattr(btn, 'fixedSize') and btn.fixedSize().height() > 0:
            radius = btn.fixedSize().height() // 2


    btn.setStyleSheet(apply_glass(f"""
        QPushButton {{
            background-color: {cfg['bg']};
            border: {cfg['border']};
            border-radius: {radius}px;
            padding: 0px;
        }}
        QPushButton:hover {{
            background-color: {cfg['hover']};
        }}
        QPushButton:disabled {{
            background-color: {get_theme_token('borde_fuerte', '#555')};
        }}
    """, btn))


def apply_player_play_button_style(btn, is_playing: bool = False, icon_size: int = 14):
    """
    Aplica el estilo unificado al botón de Play/Pausa de los reproductores.
    - Icono: pause.svg si is_playing=True, play_arrow.svg si is_playing=False (en #000000).
    - Fondo: verde acento (#1DC038), hover verde claro (#B9E640).
    """
    from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon
    
    icon_name = "pause.svg" if is_playing else "play_arrow.svg"
    _remember_for_theme(btn, apply_player_play_button_style, is_playing=is_playing, icon_size=icon_size)
    btn.setIcon(get_colored_svg_icon(icon_name, get_theme_token("boton_acento_texto", "#000000"), size=icon_size))
        
    set_themed_style(btn, lambda: f"""
        QPushButton {{
            background-color: {get_theme_token('acento_secundario', '#1DC038')};
            border: none;
            border-radius: 6px;
            padding: 0px;
        }}
        QPushButton:hover {{
            background-color: {get_theme_token('acento_primario', '#B9E640')};
        }}
        QPushButton:disabled {{
            background-color: #555;
        }}
    """)


def apply_player_loop_button_style(btn, is_active: bool = False, icon_size: int = 14):
    """
    Aplica el estilo unificado al botón de Repetir (Loop) de los reproductores.
    - is_active=True: Fondo verde acento (#1DC038), hover (#B9E640), icono repeat.svg en #000000.
    - is_active=False: Fondo gris (#2d2d2d), border (#2d2d2d), hover (#3d3d3d), icono repeat.svg en #6c7086.
    """
    from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon
    _remember_for_theme(btn, apply_player_loop_button_style, is_active=is_active, icon_size=icon_size)
        
    if is_active:
        btn.setIcon(get_colored_svg_icon("repeat.svg", get_theme_token("boton_acento_texto", "#000000"), size=icon_size))
        btn.setToolTip("Repetir: Activado")
        set_themed_style(btn, lambda: f"""
            QPushButton {{
                background-color: {get_theme_token('acento_secundario', '#1DC038')};
                border: none;
                border-radius: 6px;
                padding: 0px;
            }}
            QPushButton:hover {{
                background-color: {get_theme_token('acento_primario', '#B9E640')};
            }}
            QPushButton:disabled {{
                background-color: #555;
            }}
        """)
    else:
        btn.setIcon(get_colored_svg_icon("repeat.svg", get_theme_token('icono_tenue', '#6c7086'), size=icon_size))
        btn.setToolTip("Repetir: Desactivado")
        set_themed_style(btn, lambda: f"""
            QPushButton {{
                background-color: {get_theme_token('fondo_elemento', '#2d2d2d')};
                border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                border-radius: 6px;
                padding: 0px;
            }}
            QPushButton:hover {{
                background-color: {get_theme_token('seleccion_fondo', '#3d3d3d')};
            }}
            QPushButton:disabled {{
                background-color: #555;
            }}
        """)


def apply_edit_subclip_button_style(btn, has_subclips: bool = False, icon_size: int = 14):
    """
    Aplica el estilo unificado al botón de Editar/Recortar Subclips de los reproductores.
    - has_subclips=True ("encendido"): fondo verde acento, ícono en negro.
    - has_subclips=False ("apagado"): fondo gris neutro, ícono gris apagado.
    """
    from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon
    _remember_for_theme(btn, apply_edit_subclip_button_style, has_subclips=has_subclips, icon_size=icon_size)

    if has_subclips:
        btn.setIcon(get_colored_svg_icon("edit.svg", get_theme_token("boton_acento_texto", "#000000"), size=icon_size))
        btn.setToolTip(QCoreApplication.translate("styles", "Editar / Recortar Subclips (In/Out) — hay subclips guardados"))
        set_themed_style(btn, lambda: f"""
            QPushButton {{
                background-color: {get_theme_token('acento_secundario', '#1DC038')};
                border: none;
                border-radius: 6px;
                padding: 0px;
            }}
            QPushButton:hover {{
                background-color: {get_theme_token('acento_primario', '#B9E640')};
            }}
            QPushButton:disabled {{
                background-color: #555;
            }}
        """)
    else:
        btn.setIcon(get_colored_svg_icon("edit.svg", get_theme_token('icono_tenue', '#6c7086'), size=icon_size))
        btn.setToolTip(QCoreApplication.translate("styles", "Editar / Recortar Subclips (In/Out)"))
        set_themed_style(btn, lambda: f"""
            QPushButton {{
                background-color: {get_theme_token('fondo_elemento', '#2d2d2d')};
                border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                border-radius: 6px;
                padding: 0px;
            }}
            QPushButton:hover {{
                background-color: {get_theme_token('seleccion_fondo', '#3d3d3d')};
            }}
            QPushButton:disabled {{
                background-color: #555;
            }}
        """)


def apply_volume_control_style(btn_mute, slider):
    """
    Aplica el estilo unificado basado en tokens de tema para el botón Mute
    y el Slider de Volumen en cualquier reproductor.
    """

    set_themed_style(btn_mute, lambda: f"""
        QPushButton {{
            background-color: transparent;
            border: none;
            border-radius: 12px;
            padding: 0px;
        }}
        QPushButton:hover {{
            background-color: {get_theme_token('seleccion_fondo', '#3d3d3d')};
        }}
    """)

    set_themed_style(slider, lambda: f"""
        QSlider::groove:horizontal {{
            border-radius: 2px;
            height: 4px;
            background: {get_theme_token('borde_normal', '#444444')};
        }}
        QSlider::sub-page:horizontal {{
            background: {get_theme_token('acento_secundario', '#1DC038')};
            border-radius: 2px;
        }}
        QSlider::handle:horizontal {{
            background: #ffffff;
            width: 8px;
            margin-top: -2px;
            margin-bottom: -2px;
            border-radius: 4px;
        }}
        QSlider::handle:horizontal:hover {{
            background: {get_theme_token('acento_primario', '#B9E640')};
        }}
    """)


def create_checkerboard_pixmap(width: int, height: int, square_size: int = 10, widget=None):
    """
    Genera una cuadrícula de transparencia (patrón de ajedrez) para diferenciar fondos transparentes.
    Utiliza los tokens de color del tema activo ('ajedrez_c1', 'ajedrez_c2').
    `widget`: quién la va a mostrar. Translúcida con "Transparentar vistas previas", o vacía
    con la cuadrícula apagada (ver glass_checker_colors).
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap, QPainter
    pix = QPixmap(width, height)
    pix.fill(Qt.transparent)
    colors = glass_checker_colors(widget, get_theme_token('ajedrez_c1', '#2a2a2a'),
                                  get_theme_token('ajedrez_c2', '#181818'))
    if colors is None:
        return pix
    painter = QPainter(pix)
    c1, c2 = colors

    rows = (height + square_size - 1) // square_size
    cols = (width + square_size - 1) // square_size

    for r in range(rows):
        for c in range(cols):
            color = c1 if (r + c) % 2 == 0 else c2
            painter.fillRect(c * square_size, r * square_size, square_size, square_size, color)
    painter.end()
    return pix


VIEWER_CHIP_MARGIN = 10


def create_viewer_info_chip(parent):
    """Etiqueta flotante sobre un visor de imagen ("Original: 1920×1080 px").

    Vive aquí, junto a create_checkerboard_pixmap(), porque la comparten los dos
    visores del Editor de Imagen -- CompareViewer y ZoomableImageViewer -- y tienen
    que verse idénticos: es el MISMO cuadro, que sigue en su sitio se entre o se
    salga de la vista comparativa. Duplicando el QSS en cada visor, la primera
    corrección de estilo que tocara solo uno los desalinearía.

    Nace oculta: quien la use la muestra cuando tiene un tamaño real que poner."""
    from PySide6.QtWidgets import QLabel
    lbl = QLabel(parent)
    set_themed_style(lbl, lambda: f"""
        QLabel {{
            background-color: rgba(0, 0, 0, 170);
            color: #ffffff;  /* fijo: va sobre la imagen/vídeo en ambos modos */
            border-radius: 4px;
            padding: 3px 8px;
            font-size: 11px;
            font-weight: bold;
        }}
    """)
    lbl.hide()
    return lbl


def create_colored_circle_icon(color_hex: str, size: int = 12):
    """
    Genera un QIcon circular del color especificado sin tinte automático de selección.
    """
    from PySide6.QtGui import QPixmap, QPainter, QColor, QIcon
    from PySide6.QtCore import Qt
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(color_hex))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(1, 1, size - 2, size - 2)
    painter.end()
    
    icon = QIcon()
    icon.addPixmap(pixmap, QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(pixmap, QIcon.Mode.Normal, QIcon.State.On)
    icon.addPixmap(pixmap, QIcon.Mode.Selected, QIcon.State.Off)
    icon.addPixmap(pixmap, QIcon.Mode.Selected, QIcon.State.On)
    icon.addPixmap(pixmap, QIcon.Mode.Active, QIcon.State.Off)
    icon.addPixmap(pixmap, QIcon.Mode.Active, QIcon.State.On)
    return icon


def update_label_combobox_style(combo):
    """
    Actualiza el color del texto del QComboBox según la etiqueta seleccionada.
    """
    from PySide6.QtCore import Qt
    idx = combo.currentIndex()
    if idx > 0:
        color = combo.itemData(idx, Qt.UserRole + 1)
        if color:
            text_color = get_theme_token("texto_principal", "#cdd6f4")
            combo.setStyleSheet(
                f"QComboBox {{ color: {color}; font-weight: bold; }} "
                f"QComboBox QAbstractItemView {{ color: {text_color}; font-weight: normal; }}"
            )
            combo.style().unpolish(combo)
            combo.style().polish(combo)
            return
    combo.setStyleSheet("")
    combo.style().unpolish(combo)
    combo.style().polish(combo)





