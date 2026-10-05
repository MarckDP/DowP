# src/core/tabs/editing_media/folder_color_manager.py
import random
from core.utils.config_manager import get_config, save_config

def get_theme_color(token_key: str, default_value: str = None) -> str:
    """Color del tema activo (en su modo claro/oscuro) sin importar módulos GUI."""
    from core.utils.theme_loader import get_active_token
    return get_active_token(token_key, default_value)

def get_item_color(item_key: str) -> str:
    """Obtiene el color personalizado para una carpeta o colección desde la configuración."""
    config = get_config()
    folder_colors = config.get("folder_colors", {})
    return folder_colors.get(item_key)

def set_item_color(item_key: str, color_hex: str):
    """Guarda o remueve un color personalizado para una carpeta o colección en la configuración."""
    config = get_config()
    if "folder_colors" not in config:
        config["folder_colors"] = {}
    if color_hex:
        config["folder_colors"][item_key] = color_hex
    else:
        config["folder_colors"].pop(item_key, None)
    save_config(config)

def get_random_label_color(exclude_color: str = None) -> str:
    """Obtiene un color aleatorio para carpetas o colecciones combinando la paleta de temas y etiquetas."""
    config = get_config()
    
    # 1. Obtener colores de etiquetas de descarga del usuario
    user_label_colors = [lbl.get("color") for lbl in config.get("labels", []) if lbl.get("color")]
    
    # 2. Paleta de colores por defecto (agradables y variados)
    default_colors = [
        get_theme_color("etiqueta_combinado", "#3498db"),
        get_theme_color("etiqueta_multi_idioma", "#9b59b6"),
        get_theme_color("etiqueta_estrella", "#f1c40f"),
        get_theme_color("etiqueta_peligro", "#e74c3c"),
        get_theme_color("acento_primario", "#B9E640"),
        "#2ecc71", # Verde
        "#e67e22", # Naranja
        "#e84393", # Rosa/Magenta
        "#1abc9c", # Turquesa
        "#34495e", # Gris azulado
    ]
    
    # Combinar las listas para tener mayor variedad
    pool = list(set(default_colors + user_label_colors))
    
    # Excluir el color actual para garantizar el cambio
    if exclude_color and exclude_color in pool and len(pool) > 1:
        pool.remove(exclude_color)
        
    return random.choice(pool)
