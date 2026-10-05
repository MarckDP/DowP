# src/gui/styles.py
"""
Motor de Temas DowP 2.0
========================
Lee un template QSS (_base.qss) y los tokens del tema activo, reemplaza las
variables {{token}} por sus valores, y genera assets dinámicos como el ícono SVG
del triángulo del ComboBox.

Los temas (con sus dos modos, claro y oscuro) los carga y resuelve
core/utils/theme_loader.py; el que los aplica a la app es gui/theme_manager.py.

Para crear un tema: Ajustes > General > botón junto a "Tema visual" > Exportar tema
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
    if px <= 7:
        return px * shapes["radio"] / d["radio"]
    if px in (8, 11, 12, 16):
        return px * shapes["radio_grande"] / d["radio_grande"]
    return px


_SIZE_RE = re.compile(r"(?:^|[;{\s])(?:min-|max-)?(?:width|height)\s*:\s*(\d+)px")
_BLOCK_RE = re.compile(r"\{[^{}]*\}")


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


def set_themed_style(widget, builder):
    """Aplica builder() como hoja de estilos del widget y la recuerda para recalcularla
    cuando cambie el tema o el modo (ThemeManager -> refresh_themed_styles).

    builder es una función sin argumentos que solo debe depender de get_theme_token(...):
    así, volver a llamarla con el tema nuevo da el estilo correcto."""
    shaped = lambda: apply_shapes(builder())
    qss = shaped()
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
    from core.utils.font_manager import get_active_font_family
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
    active_font = font_family or get_active_font_family(theme_name)
    tokens["fuente_principal"] = active_font

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


def apply_folder_browse_button_style(btn, tooltip=None, icon_size=18):
    """
    Aplica el estilo unificado al botón de examinar/configurar carpeta o ruta.
    - Icono: folder_managed.svg en negro (#000000) habilitado y gris (#777777) deshabilitado.
    - Variante: 'accent-solid' (verde plano reactivo).
    """
    from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon
    from PySide6.QtCore import QSize
    dis_color = get_theme_token("texto_deshabilitado", "#777777")
    _remember_for_theme(btn, apply_folder_browse_button_style, tooltip=tooltip, icon_size=icon_size)
    btn.setIcon(get_colored_svg_icon("folder_managed.svg", get_theme_token("boton_acento_texto", "#000000"), size=icon_size, disabled_color_hex=dis_color))
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


    btn.setStyleSheet(f"""
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
    """)


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


def create_checkerboard_pixmap(width: int, height: int, square_size: int = 10):
    """
    Genera una cuadrícula de transparencia (patrón de ajedrez) para diferenciar fondos transparentes.
    Utiliza los tokens de color del tema activo ('ajedrez_c1', 'ajedrez_c2').
    """
    from PySide6.QtGui import QPixmap, QPainter, QColor
    pix = QPixmap(width, height)
    painter = QPainter(pix)
    c1 = QColor(get_theme_token('ajedrez_c1', '#2a2a2a'))
    c2 = QColor(get_theme_token('ajedrez_c2', '#181818'))

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





