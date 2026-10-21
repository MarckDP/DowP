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

        # strip_ansi_codes: red de seguridad por si algún YoutubeDL se crea sin las
        # opciones base (que ya apagan el color, ver get_base_ydl_opts).
        logger.debug(f"[yt-dlp] {strip_ansi_codes(msg)}")

    def info(self, msg):
        self._check_cancelled()
        self._notify(msg)
        self._process_message(msg)
        logger.info(f"[yt-dlp] {strip_ansi_codes(msg)}")

    def warning(self, msg):
        logger.warning(f"[yt-dlp] {strip_ansi_codes(msg)}")

    def error(self, msg):
        logger.error(f"[yt-dlp] {strip_ansi_codes(msg)}")
        self.errors.append(msg)

def get_base_ydl_opts(extra_opts=None, profile=None):
    """
    Genera el diccionario de opciones base (cookies, impersonate, deno, etc.)
    que deben compartir tanto el analizador como el descargador.

    profile: perfil de clientes de YouTube (ver client_profiles). None = el primero
    de la cadena.
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
        # Sin códigos ANSI de color: yt-dlp colorea si stderr es una terminal (DowP
        # lanzado desde una consola) y los mete también en el texto de sus excepciones,
        # que DowP registra tal cual -- en el log quedaban como "[0;31mERROR:[0m".
        'color': {'stdout': 'no_color', 'stderr': 'no_color'},
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

    # --- CLIENTES DE YOUTUBE + PO TOKEN ---
    # Los decide el perfil (client_profiles): primero web_embedded sin token, y los
    # perfiles con token (WPC, bgutil) solo como respaldo. Los otros sitios ignoran
    # extractor_args['youtube'].
    from core.ytdlp_logic import client_profiles
    profile = profile or client_profiles.profile_chain()[0]
    client_profiles.apply_profile(ydl_opts, profile)
    logger.debug(f"Analyzer: perfil de clientes '{profile}' (cookies: {use_cookies}) -> "
                 f"{ydl_opts['extractor_args']['youtube'].get('player_client')}")

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


def _logged_errors(yt_logger):
    err_msg = ""
    if yt_logger and hasattr(yt_logger, "errors") and yt_logger.errors:
        err_msg = "\n".join(yt_logger.errors)
    return strip_ansi_codes(err_msg) or QCoreApplication.translate("analyzer", "No se pudo obtener información de la URL.")


def _extract_with_profile_chain(yt_dlp, url, build_opts, cancel_exception, cancellation_event):
    """Análisis de YouTube probando los perfiles de clientes en orden (ver
    client_profiles). Pasa al siguiente solo ante errores que otro perfil puede
    resolver (inserción desactivada, 403, aviso de bot...); un 429 o la verificación
    de edad sin cookies se devuelven tal cual. El perfil que funciona se recuerda para
    que la descarga use los mismos clientes."""
    from core.ytdlp_logic import client_profiles

    chain = client_profiles.chain_for(url)
    for attempt, profile in enumerate(chain):
        ydl_opts = build_opts(profile)
        yt_logger = ydl_opts.get('logger')
        if attempt == 0:
            logger.debug(f"Analyzer: ydl_opts finales: { {k:v for k,v in ydl_opts.items() if k != 'logger'} }")
        has_next = attempt + 1 < len(chain)
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                logger.info(f"Analyzer: Iniciando extracción (perfil '{profile}')...")
                info_dict = ydl.extract_info(url, download=False)
        except cancel_exception:
            raise
        except Exception as extract_err:
            if cancellation_event is not None and cancellation_event.is_set():
                raise cancel_exception("Análisis cancelado por el usuario")
            if has_next and client_profiles.should_try_next_profile(extract_err):
                logger.warning(f"Analyzer: El perfil '{profile}' falló ({extract_err}). "
                               f"Reintentando con el perfil '{chain[attempt + 1]}'...")
                continue
            raise

        if info_dict is None:
            # Con ignoreerrors (análisis de la cola) yt-dlp no lanza: el error queda en el logger.
            err_msg = _logged_errors(yt_logger)
            if has_next and client_profiles.should_try_next_profile(err_msg):
                logger.warning(f"Analyzer: El perfil '{profile}' falló ({err_msg}). "
                               f"Reintentando con el perfil '{chain[attempt + 1]}'...")
                continue
            return None, err_msg

        logger.info(f"Analyzer: Extracción completada (perfil '{profile}').")
        client_profiles.remember(url, profile, info_dict)
        return info_dict, None


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

    from core.ytdlp_logic import client_profiles
    from core.ytdlp_logic.format_selectors import is_youtube_url

    def build_opts(profile=None):
        opts = get_base_ydl_opts(extra_opts, profile=profile)
        if progress_callback or cancellation_event is not None:
            opts['logger'] = YTDLLogger(progress_callback, cancellation_event, cancel_exception)
        opts['skip_download'] = True
        return opts

    # Inyectar entorno (PATH) para dependencias internas
    env = get_dependency_env()
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = env["PATH"]

    try:
        logger.info(f"Analyzing URL: {url}")

        if is_youtube_url(url):
            return _extract_with_profile_chain(yt_dlp, url, build_opts, cancel_exception, cancellation_event)

        ydl_opts = build_opts()
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
                logger.warning(f"Analyzer: El sitio bloqueó el primer intento ({extract_err}). Reintentando análisis con opciones alternativas...")
                fallback_opts = make_fallback_ydl_opts(ydl_opts)
                with yt_dlp.YoutubeDL(fallback_opts) as ydl_fb:
                    info_dict = ydl_fb.extract_info(url, download=False)
                    logger.info("Analyzer: Extracción completada con opciones alternativas.")
            else:
                raise extract_err

        if info_dict is None:
            return None, _logged_errors(yt_logger)

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
