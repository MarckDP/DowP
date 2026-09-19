# src/core/utils/config_manager.py
import os
import json
from core.logger.logger_manager import logger
from core.utils.paths import get_config_path
from core.version import IS_BETA

CONFIG_FILE = get_config_path()

_cached_config = None

def get_config():
    """Lee el archivo de configuración y lo mantiene en memoria."""
    global _cached_config
    if _cached_config is not None:
        return _cached_config

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                _cached_config = json.load(f)
        except Exception as e:
            logger.error(f"ConfigManager: Error leyendo config: {e}")

    if _cached_config is None:
        _cached_config = {}

    # Rellenar con valores por defecto si no existen
    defaults = {
        "language": "es",
        "theme": "dark",
        "last_seen_version": "",  # ultima version cuyas novedades ya se mostraron (gui/dialogs/whats_new_dialog.py)
        "auto_analyze": False,
        "use_impersonate": False,
        "adobe_compat_default": True,
        "auto_paste_url": True,
        "labels": [],
        "default_web_download_dir": "",
        "pixabay_api_key": "",
        "pexels_api_key": "",
        "default_subclip_dir": "",
        "editing_media_view_mode": "grid",
        "editing_media_icon_size": 112,
        "editing_media_splitter_sizes": [240, 480, 480],
        "console_capture_enabled": True,
        "console_wrap_enabled": True,
        "integrations": {
            "premiere_enabled": False,
            "premiere_path": "",
            "aftereffects_enabled": False,
            "aftereffects_path": "",
            "davinci_enabled": False,
            "davinci_path": ""
        },
        "pot_provider": "bgutil",       # "bgutil" | "wpc" | "none"
        "pot_wpc_browser_path": "",     # ruta al ejecutable Chromium; vacío = auto-detect
        "ytdlp_channel": "stable",      # "stable" | "nightly"
        "ffmpeg_mode": "managed",       # "managed" | "custom"
        "ffmpeg_variant": "essentials", # "essentials" | "full"
        "ffmpeg_channel": "recommended",# "recommended" | "latest" | "nightly"
        "ffmpeg_keep_ffplay": False,    # False = eliminar ffplay, True = conservar
        "ffmpeg_custom_path": "",       # Ruta personalizada a ffmpeg.exe o carpeta
        "update_channel": "beta" if IS_BETA else "stable",  # "stable" | "beta" (incluye prereleases de GitHub)
        "max_concurrent_downloads": 3,  # Número máximo de descargas simultáneas (1 a 10)
        "hardware_info": {},            # Información del sistema y GPU detectada
        "analyze_playlist": True,       # Estado de casilla de análisis de playlist
        "fast_mode": True,              # Estado de casilla de modo rápido
    }
    for k, v in defaults.items():
        if k not in _cached_config:
            _cached_config[k] = v

    # Opciones transitorias de AdvancedProcessTab (siempre inician en su valor por defecto al arrancar)
    transient_defaults = {
        "batch_thumbnail_mode": "manual",
        "global_download_mode": "manual",
        "global_download_quality": "manual"
    }
    for k, v in transient_defaults.items():
        _cached_config[k] = v

    return _cached_config

def save_config(config):
    """Guarda la configuración en archivo, omitiendo las opciones transitorias."""
    global _cached_config
    _cached_config = config

    # Filtrar las opciones transitorias de la AdvancedProcessTab
    save_dict = config.copy()
    transient_keys = [
        "batch_thumbnail_mode",
        "global_download_mode",
        "global_download_quality"
    ]
    for key in transient_keys:
        save_dict.pop(key, None)

    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(save_dict, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"ConfigManager: Error guardando config: {e}")

def get_default_web_download_dir():
    """Retorna la carpeta de descargas web predeterminada configurada o ~/Downloads."""
    cfg = get_config()
    val = cfg.get("default_web_download_dir")
    if val and os.path.exists(val):
        return os.path.normpath(val).replace("\\", "/")
    return os.path.normpath(os.path.expanduser("~/Downloads")).replace("\\", "/")

def get_default_subclip_dir():
    """Retorna la carpeta de subclips configurada por el usuario (creándola si hace falta), o
    Documentos/DowP2/Subclips si no hay ninguna configurada."""
    cfg = get_config()
    val = cfg.get("default_subclip_dir")
    if val:
        os.makedirs(val, exist_ok=True)
        return os.path.normpath(val).replace("\\", "/")
    sub_dir = os.path.join(os.path.expanduser("~/Documents"), "DowP2", "Subclips")
    os.makedirs(sub_dir, exist_ok=True)
    return os.path.normpath(sub_dir).replace("\\", "/")
