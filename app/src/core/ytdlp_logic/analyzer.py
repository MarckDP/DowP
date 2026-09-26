import json
import os
import sys
import traceback
import re
from core.logger.logger_manager import logger
from core.utils.config_manager import get_config
from core.setup.ytdlp_setup import get_ytdlp_path
from core.setup.setup_manager import get_dependency_env
from PySide6.QtCore import QCoreApplication

def strip_ansi_codes(text):
    """Elimina códigos de color ANSI como [0;31m del texto."""
    if not text:
        return ""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

import time

class YTDLLogger:
    """Redirige los logs de yt-dlp al logger de DowP con limitador de velocidad.

    Con cancellation_event, también es el punto de corte del análisis: yt-dlp manda
    cada paso (cada página, cada video de una playlist) por debug(), y extract_info() no
    tiene otra forma de interrumpirse desde afuera. Se lanza cancel_exception, que tiene
    que ser utils.DownloadCancelled de yt-dlp: con ignoreerrors=True (el análisis de
    playlist lo usa) yt-dlp se traga cualquier otra excepción por entrada y sigue con la
    siguiente, pero DownloadCancelled la re-lanza a propósito."""
    def __init__(self, progress_callback=None, cancellation_event=None, cancel_exception=None,
                 message_callback=None):
        self._last_download_log = 0
        self.progress_callback = progress_callback
        self.cancellation_event = cancellation_event
        self._cancel_exception = cancel_exception
        # Recibe cada mensaje crudo de yt-dlp (ver DownloaderMaster._on_ytdlp_message).
        self.message_callback = message_callback
        self.errors = []

    def __deepcopy__(self, memo):
        # make_fallback_ydl_opts hace deepcopy de las opciones: un threading.Event no se
        # puede copiar, y el reintento tiene que seguir escuchando la MISMA cancelación.
        return self

    def _check_cancelled(self):
        if self._cancel_exception and self.cancellation_event is not None and self.cancellation_event.is_set():
            raise self._cancel_exception("Análisis cancelado por el usuario")

    def _notify(self, msg):
        if self.message_callback:
            try:
                self.message_callback(msg)
            except Exception:
                pass

    def _process_message(self, msg):
        if self.progress_callback:
            try:
                clean_msg = strip_ansi_codes(msg)
                # Texto crudo de yt-dlp, siempre en ingles - no traducir estos marcadores.
                if "Downloading item" in clean_msg or "Downloading video" in clean_msg:
                    match = re.search(r'(?:item|video)\s+(\d+)\s+of\s+(\d+)', clean_msg, re.IGNORECASE)
                    if match:
                        current = int(match.group(1))
                        total = int(match.group(2))
                        self.progress_callback(current, total)
            except Exception:
                pass

    def debug(self, msg):
        self._check_cancelled()
        self._notify(msg)
        self._process_message(msg)
        # Filtrar mensajes de progreso de descarga (muy ruidosos)
        if "[download]" in msg:
            current_time = time.time()
            if current_time - self._last_download_log < 0.33:
                return
            self._last_download_log = current_time
            
        logger.debug(f"[yt-dlp] {msg}")

    def info(self, msg):
        self._check_cancelled()
        self._notify(msg)
        self._process_message(msg)
        logger.info(f"[yt-dlp] {msg}")

    def warning(self, msg):
        logger.warning(f"[yt-dlp] {msg}")

    def error(self, msg):
        logger.error(f"[yt-dlp] {msg}")
        self.errors.append(msg)

def get_base_ydl_opts(extra_opts=None):
    """
    Genera el diccionario de opciones base (cookies, impersonate, deno, etc.)
    que deben compartir tanto el analizador como el descargador.
    """
    config = get_config()
    
    from core.setup.ffmpeg_setup import get_ffmpeg_dir
    ffmpeg_dir = get_ffmpeg_dir()
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'timeout': 30,
        'logger': YTDLLogger(),
        'ffmpeg_location': ffmpeg_dir,
    }

    if extra_opts:
        ydl_opts.update(extra_opts)

    # --- LÓGICA DE COOKIES ---
    mode = config.get("cookies_mode", "none")
    use_cookies = False

    if mode == "file":
        file_path = config.get("cookies_file", "")
        if file_path and os.path.exists(file_path):
            ydl_opts['cookiefile'] = file_path
            use_cookies = True
            logger.info(f"Analyzer: Usando archivo de cookies: {file_path}")
    elif mode == "browser":
        browser = config.get("cookies_browser", "")
        if browser:
            profile = config.get("cookies_profile", "")
            spec = f"{browser}:{profile}" if profile else browser
            ydl_opts['cookiesfrombrowser'] = (spec,)
            use_cookies = True
            logger.info(f"Analyzer: Usando cookies del navegador: {browser}")

    # --- PARCHE DE IMPERSONATE ---
    from .utils import get_impersonate_target
    if config.get("use_impersonate", False):
        target = get_impersonate_target("chrome")
        if target:
            ydl_opts['impersonate'] = target

    # --- JS RUNTIMES Y COMPONENTES REMOTOS ---
    # Necesarios siempre para resolver challenges de YouTube.
    from core.setup.deno_setup import get_deno_path, get_platform_info
    _, binary_name = get_platform_info()
    env = get_dependency_env()
    deno_dir = next((p for p in env.get('PATH', '').split(os.pathsep) if 'deno' in p.lower()), '')
    deno_path = os.path.join(deno_dir, binary_name) if (deno_dir and os.path.exists(os.path.join(deno_dir, binary_name))) else get_deno_path()
    if not os.path.exists(deno_path):
        deno_path = binary_name
    
    ydl_opts['js_runtimes'] = {'deno': {'path': deno_path}}
    ydl_opts['remote_components'] = ['ejs:github']

    # --- EXTRACTOR ARGS (solo con cookies) ---
    # Sin cookies: NO forzar extractor_args. yt-dlp usará sus defaults
    # internos que se actualizan con cada release para adaptarse a YouTube.
    # Forzar clientes como web_safari o android sin autenticación provoca
    # que YouTube restrinja los formatos a calidades bajas (SABR / tokens).
    # Con cookies: excluimos clientes problemáticos conocidos.
    if use_cookies:
        ydl_opts['extractor_args'] = {
            'youtube': {
                'player_client': ['default', '-tv_simply', '-android_sdkless'],
                'n_client': ['default'],
                'skip': []
            }
        }
        
    # --- PO TOKEN PROVIDER (multi-provider) ---
    # Lee el provider activo de config.json y aplica los extractor_args correctos.
    # Ambos providers comparten la misma lista de player_client.
    _pot_provider = get_config().get("pot_provider", "bgutil")

    _pot_active = False

    if _pot_provider == "bgutil":
        from core.setup.potprovider_setup import check_all as pot_ready, get_binary_path
        if pot_ready():
            binary_path = get_binary_path()
            if 'extractor_args' not in ydl_opts:
                ydl_opts['extractor_args'] = {'youtube': {}}
            ydl_opts['extractor_args'].setdefault('youtube', {})
            # Arg oficial del provider CLI (v0.8.1+, reemplaza el deprecado getpot_bgutil_script)
            # Pasar script_path e inyectar cli_path para que bgutil:http sepa que el modo CLI está activo y no espere timeout en puerto 4416
            ydl_opts['extractor_args']['youtubepot-bgutilcli'] = {'cli_path': [binary_path]}
            ydl_opts['extractor_args']['youtubepot-bgutilscript'] = {'script_path': [binary_path]}
            _pot_active = True
            logger.info(f"Analyzer: POT provider=bgutil activo -> {binary_path}")
        else:
            logger.warning("Analyzer: bgutil no disponible - puede haber 429/bot-check")

    elif _pot_provider == "wpc":
        from core.setup.wpc_setup import check_wpc, get_browser_path, get_browser_display_name
        if check_wpc():
            if 'extractor_args' not in ydl_opts:
                ydl_opts['extractor_args'] = {'youtube': {}}
            ydl_opts['extractor_args'].setdefault('youtube', {})
            browser = get_browser_path()
            if browser:
                ydl_opts['extractor_args']['youtubepot-wpc'] = {'browser_path': [browser]}
                logger.info(f"Analyzer: POT provider=wpc activo -> {get_browser_display_name()} ({browser})")
            else:
                # Sin ruta explícita nodriver elige el navegador por su cuenta
                logger.info("Analyzer: POT provider=wpc activo -> nodriver auto-detecta navegador")
            _pot_active = True
        else:
            logger.warning("Analyzer: WPC no instalado - puede haber 429/bot-check")

    else:  # "none" o desconocido
        logger.info("Analyzer: POT provider=none - sin PO Token")

    if _pot_active:
        # Clientes óptimos con PO Token activo (cualquier provider):
        # - mweb: extrae sin visitor_data pre-fetched
        # - web:  GVS tokens más confiables para el stream real
        # Exclusiones: clientes que fallan con GVS o requieren visitor_data externo
        existing_clients = ydl_opts['extractor_args']['youtube'].get('player_client', [])
        clients = ['mweb', 'web'] + [c for c in existing_clients if c not in ('mweb', 'web')]
        exclusions = ['-web_safari', '-tv_simply', '-android_sdkless', '-android_vr']
        clients += [x for x in exclusions if x not in clients]
        ydl_opts['extractor_args']['youtube']['player_client'] = clients
        logger.debug(f"Analyzer: player_client -> {clients}")

    return ydl_opts

def load_ytdlp_module():
    """Importa yt_dlp desde el ZIP que gestiona DowP (no el de pip), con los plugins de PO
    token si están instalados. Devuelve el módulo, o None si el ZIP no existe o no se pudo
    importar. Compartido por get_video_info y la búsqueda (media_search.py)."""
    ytdlp_path = get_ytdlp_path()

    if not os.path.exists(ytdlp_path):
        logger.error(f"yt-dlp not found at {ytdlp_path}")
        return None

    # Solo recargar módulos si el path del ZIP cambió (evita reimportación innecesaria)
    if ytdlp_path not in sys.path:
        # Path nuevo: purgar módulos viejos y añadir el nuevo
        if 'yt_dlp' in sys.modules:
            for mod in list(sys.modules.keys()):
                if mod.startswith('yt_dlp'):
                    del sys.modules[mod]
        sys.path.insert(0, ytdlp_path)

    # Inyectar siempre la carpeta de plugins si al menos uno (bgutil o wpc) está
    # presente, para que yt_dlp los registre ambos en su primera ejecución y
    # evitar el bug de caché de módulos al retirarla/reinsertarla según el provider.
    from core.setup.potprovider_setup import get_plugin_dir, check_plugin
    from core.setup.wpc_setup import check_wpc
    plugin_dir = get_plugin_dir()
    if (check_plugin() or check_wpc()) and plugin_dir not in sys.path:
        sys.path.insert(0, plugin_dir)
        logger.debug(f"Analyzer: plugin dir inyectado en sys.path -> {plugin_dir}")

    try:
        import yt_dlp
    except ImportError:
        logger.error("Failed to import yt_dlp from zip")
        return None
    return yt_dlp


def get_video_info(url, extra_opts=None, progress_callback=None, cancellation_event=None):
    """
    Análisis de video usando la lógica del DowP viejo (ZIP + API Nativa)
    y respetando estrictamente los ajustes del usuario.

    cancellation_event (threading.Event): si se activa, el análisis se corta en el
    siguiente paso de yt-dlp (ver YTDLLogger) y devuelve (None, "Análisis cancelado").
    """
    if not os.path.exists(get_ytdlp_path()):
        logger.error(f"yt-dlp not found at {get_ytdlp_path()}")
        return None, "yt-dlp binary not found."

    yt_dlp = load_ytdlp_module()
    if yt_dlp is None:
        return None, QCoreApplication.translate("analyzer", "Error: yt-dlp could not be imported.")

    cancelled_msg = QCoreApplication.translate("analyzer", "Análisis cancelado")
    cancel_exception = yt_dlp.utils.DownloadCancelled
    if cancellation_event is not None and cancellation_event.is_set():
        return None, cancelled_msg

    ydl_opts = get_base_ydl_opts(extra_opts)
    if progress_callback or cancellation_event is not None:
        ydl_opts['logger'] = YTDLLogger(progress_callback, cancellation_event, cancel_exception)
    ydl_opts['skip_download'] = True

    # Inyectar entorno (PATH) para dependencias internas
    env = get_dependency_env()
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = env["PATH"]

    try:
        logger.info(f"Analyzing URL: {url}")
        logger.debug(f"Analyzer: ydl_opts finales: { {k:v for k,v in ydl_opts.items() if k != 'logger'} }")
        
        # Guardar referencia al logger para extraer errores
        yt_logger = ydl_opts.get('logger')
        
        from core.ytdlp_logic.resilient_downloader import is_youtube_access_error, make_fallback_ydl_opts

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                logger.info("Analyzer: Instancia de YoutubeDL creada exitosamente. Iniciando extracción...")
                info_dict = ydl.extract_info(url, download=False)
                logger.info("Analyzer: Extracción completada.")
        except cancel_exception:
            raise
        except Exception as extract_err:
            if cancellation_event is not None and cancellation_event.is_set():
                raise cancel_exception("Análisis cancelado por el usuario")
            if is_youtube_access_error(url, extract_err):
                logger.warning(f"Analyzer: YouTube bloqueó el primer cliente ({extract_err}). Reintentando análisis con cliente alternativo (web_embedded)...")
                fallback_opts = make_fallback_ydl_opts(ydl_opts)
                with yt_dlp.YoutubeDL(fallback_opts) as ydl_fb:
                    info_dict = ydl_fb.extract_info(url, download=False)
                    logger.info("Analyzer: Extracción completada con cliente alternativo.")
            else:
                raise extract_err
            
        if info_dict is None:
            err_msg = ""
            if yt_logger and hasattr(yt_logger, "errors") and yt_logger.errors:
                err_msg = "\n".join(yt_logger.errors)
            return None, strip_ansi_codes(err_msg) or QCoreApplication.translate("analyzer", "No se pudo obtener información de la URL.")
            
        return info_dict, None

    except cancel_exception:
        logger.info(f"Analyzer: Análisis cancelado por el usuario ({url})")
        return None, cancelled_msg

    except Exception as e:
        err_detail = traceback.format_exc()
        logger.error(f"Unexpected error in analyzer: {err_detail}")
        return None, strip_ansi_codes(str(e)) or QCoreApplication.translate("analyzer", "Error desconocido durante el análisis.")
        
    finally:
        os.environ["PATH"] = old_path
