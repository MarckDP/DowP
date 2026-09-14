# src/gui/styles.py
"""
Motor de Temas DowP 2.0
========================
Lee un template QSS (_base.qss) y un archivo de tokens JSON ({tema}.json),
reemplaza las variables {{token}} por sus valores, y genera assets dinámicos
como el ícono SVG del triángulo del ComboBox.

Para crear un tema custom:
  1. Copiar dark.json o light.json
  2. Renombrar (ej: monokai.json)
  3. Cambiar los colores
  4. Seleccionarlo desde Ajustes
"""
import os
import json
import tempfile
from core.logger.logger_manager import logger
from core.utils.paths import get_src_dir
from PySide6.QtCore import QCoreApplication

# Directorio base de temas
_THEMES_DIR = os.path.join(get_src_dir(), "gui", "themes")
_BASE_QSS = os.path.join(_THEMES_DIR, "_base.qss")

# Directorio temporal para assets generados (SVGs, etc.)
_TEMP_DIR = os.path.join(tempfile.gettempdir(), "dowp_theme_assets")
os.makedirs(_TEMP_DIR, exist_ok=True)

# Cache de tokens para evitar lecturas de disco repetitivas
_THEME_CACHE = {}


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


def _get_theme_path(theme_name: str) -> str:
    """Busca el archivo JSON del tema en AppData (temas de usuario) y luego en el directorio empaquetado."""
    from core.utils.paths import get_user_themes_dir
    user_path = os.path.join(get_user_themes_dir(), f"{theme_name}.json")
    if os.path.exists(user_path):
        return user_path
    
    builtin_path = os.path.join(_THEMES_DIR, f"{theme_name}.json")
    if os.path.exists(builtin_path):
        return builtin_path
    
    return ""


def _load_theme_tokens(theme_name: str) -> dict:
    """
    Carga los tokens de color desde el archivo JSON del tema con cache.
    """
    if theme_name in _THEME_CACHE:
        return _THEME_CACHE[theme_name]

    json_path = _get_theme_path(theme_name)
    
    if not json_path or not os.path.exists(json_path):
        logger.error(f"Temas: Archivo de tema no encontrado: {theme_name}.json")
        return {}
    
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            tokens = data.get("colores", {})
            _THEME_CACHE[theme_name] = tokens
            return tokens
    except Exception as e:
        logger.error(f"Temas: Error leyendo tokens del tema: {e}")
        return {}


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
    Retorna una lista de temas disponibles con sus metadatos (id, nombre, is_user).
    Escanea tanto los temas empaquetados como los temas personalizados del usuario en AppData.
    """
    from core.utils.paths import get_user_themes_dir
    themes = []
    seen_ids = set()

    # 1. Temas empaquetados
    if os.path.isdir(_THEMES_DIR):
        for filename in os.listdir(_THEMES_DIR):
            if filename.endswith(".json"):
                theme_id = filename[:-5]
                name = _read_theme_display_name(os.path.join(_THEMES_DIR, filename), theme_id)
                themes.append({"id": theme_id, "name": name, "is_user": False})
                seen_ids.add(theme_id)

    # 2. Temas de usuario (%APPDATA%/DowP2/themes)
    user_dir = get_user_themes_dir()
    if os.path.isdir(user_dir):
        for filename in os.listdir(user_dir):
            if filename.endswith(".json"):
                theme_id = filename[:-5]
                if theme_id not in seen_ids:
                    name = _read_theme_display_name(os.path.join(user_dir, filename), theme_id)
                    themes.append({"id": theme_id, "name": f"{name} (Usuario)", "is_user": True})
                    seen_ids.add(theme_id)

    return themes


def _read_theme_display_name(json_path: str, default_id: str) -> str:
    """Lee el nombre amigable del tema desde su metadata si existe."""
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            meta_name = data.get("meta", {}).get("nombre")
            if meta_name:
                return meta_name
    except Exception:
        pass
    # Nombres por defecto bonitos
    if default_id == "dark":
        return "Modo Oscuro"
    elif default_id == "light":
        return "Modo Claro"
    return default_id.replace("_", " ").title()


def get_theme_token(token_key: str, default_value: str = None) -> str:
    """
    Obtiene un token de color del tema actual.
    """
    from core.utils.config_manager import get_config
    config = get_config()
    theme_name = config.get("theme", "dark")
    tokens = _load_theme_tokens(theme_name)
    return tokens.get(token_key, default_value)


def load_stylesheet(theme_name: str = "dark", font_family: str = None) -> str:
    """
    Genera el QSS final para el tema solicitado.
    
    1. Lee _base.qss (template con {{variables}})
    2. Lee {theme_name}.json (definición de colores)
    3. Inyecta la fuente activa (font_manager o tema) en {{fuente_principal}}
    4. Genera los SVGs dinámicos con el color de acento
    5. Reemplaza todas las {{variables}} por sus valores
    6. Retorna el QSS listo para aplicar
    """
    from core.utils.font_manager import get_active_font_family
    
    # 1. Cargar template base
    template = _load_base_template()
    if not template:
        logger.warning("Temas: Template vacío, usando estilos por defecto")
        return ""
    
    # 2. Cargar tokens del tema
    tokens = _load_theme_tokens(theme_name)
    if not tokens:
        logger.warning(f"Temas: No se pudieron cargar tokens para '{theme_name}'")
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
        logger.warning(f"Temas: Variables sin resolver en '{theme_name}': {unresolved}")
    
    # Limpiar cache al recargar el stylesheet para asegurar que los cambios se apliquen
    _THEME_CACHE.clear()
    
    logger.info(f"Temas: Tema '{theme_name}' cargado con tipografía '{active_font}'")
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
    btn.setIcon(get_colored_svg_icon("folder_managed.svg", "#000000", size=icon_size, disabled_color_hex=dis_color))
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
    btn.setIcon(get_colored_svg_icon("folder_open.svg", "#000000", size=icon_size, disabled_color_hex=dis_color))
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
    btn.setIcon(get_colored_svg_icon("download.svg", "#000000", size=icon_size, disabled_color_hex=dis_color))
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
            "icon": "#FFFFFF"
        },
        "saved":   {
            "bg": get_theme_token('acento_secundario', '#1DC038'),
            "hover": get_theme_token('acento_primario', '#B9E640'),
            "border": "none",
            "icon": "#000000"
        },
        "unsaved": {
            "bg": get_theme_token('estado_aviso', '#ffc107'),
            "hover": "#ffdb58",
            "border": "none",
            "icon": "#000000"
        }
    }
    
    cfg = colors.get(status, colors["normal"])
    btn.setIcon(get_colored_svg_icon(icon_name, cfg["icon"], size=icon_size))
    
    if shape == "square":
        radius = 6
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
            background-color: #555;
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
    btn.setIcon(get_colored_svg_icon(icon_name, "#000000", size=icon_size))
        
    btn.setStyleSheet(f"""
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
        
    if is_active:
        btn.setIcon(get_colored_svg_icon("repeat.svg", "#000000", size=icon_size))
        btn.setToolTip("Repetir: Activado")
        btn.setStyleSheet(f"""
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
        btn.setIcon(get_colored_svg_icon("repeat.svg", "#6c7086", size=icon_size))
        btn.setToolTip("Repetir: Desactivado")
        btn.setStyleSheet(f"""
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

    if has_subclips:
        btn.setIcon(get_colored_svg_icon("edit.svg", "#000000", size=icon_size))
        btn.setToolTip(QCoreApplication.translate("styles", "Editar / Recortar Subclips (In/Out) — hay subclips guardados"))
        btn.setStyleSheet(f"""
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
        btn.setIcon(get_colored_svg_icon("edit.svg", "#6c7086", size=icon_size))
        btn.setToolTip(QCoreApplication.translate("styles", "Editar / Recortar Subclips (In/Out)"))
        btn.setStyleSheet(f"""
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
    bg_hover = get_theme_token('seleccion_fondo', '#3d3d3d')
    border_color = get_theme_token('borde_normal', '#444444')
    accent_sec = get_theme_token('acento_secundario', '#1DC038')
    accent_pri = get_theme_token('acento_primario', '#B9E640')

    btn_mute.setStyleSheet(f"""
        QPushButton {{
            background-color: transparent;
            border: none;
            border-radius: 12px;
            padding: 0px;
        }}
        QPushButton:hover {{
            background-color: {bg_hover};
        }}
    """)

    slider.setStyleSheet(f"""
        QSlider::groove:horizontal {{
            border-radius: 2px;
            height: 4px;
            background: {border_color};
        }}
        QSlider::sub-page:horizontal {{
            background: {accent_sec};
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
            background: {accent_pri};
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
    lbl.setStyleSheet(f"""
        QLabel {{
            background-color: rgba(0, 0, 0, 170);
            color: {get_theme_token('texto_principal', '#ffffff')};
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





