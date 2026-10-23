# src/core/ytdlp_logic/client_profiles.py
"""
Perfiles de clientes de YouTube y su cadena de respaldo.

Un perfil es la lista de player_client que se le pide a yt-dlp más el proveedor de
PO Token que la acompaña. Orden de la cadena (ver memoria del análisis 2026-10):

1. "embedded": web_embedded + los clientes por defecto de yt-dlp, SIN token
   (fetch_pot=never). Desde 2026-09 web_embedded usa UA de Safari y trae los
   combinados HLS 91-96/300/301 (hasta 1080p, uno por idioma de audio), además de
   los separados hasta 4K y subtítulos sin token. Falla en videos con la inserción
   desactivada.
2. "wpc": mweb/web con token del navegador (yt-dlp-getpot-wpc). Respaldo para lo
   que web_embedded no puede reproducir. Sus combinados se quedan en 360p (SABR).
3. "bgutil": los mismos clientes con bgutil-pot (port en Rust). Desde fines de julio
   de 2026 YouTube rechaza a menudo sus tokens, así que va al final.
   (El proveedor elegido en Ajustes intercambia 2 y 3.)

El perfil que funcionó en el análisis se recuerda por ID de video: la descarga
posterior arranca por ese mismo perfil, para que los IDs de formato elegidos existan
(dos clientes distintos no exponen los mismos formatos).
"""
import os
import re
import threading
import time

from core.logger.logger_manager import logger
from core.utils.config_manager import get_config

PROFILE_EMBEDDED = "embedded"
PROFILE_WPC = "wpc"
PROFILE_BGUTIL = "bgutil"

_TOKEN_CLIENTS = ['mweb', 'web', 'default', '-web_safari', '-tv_simply', '-android_sdkless', '-android_vr']

# Ruta inexistente: los proveedores se dan por no disponibles (is_available() -> False)
# en vez de generar un token que el perfil activo no pidió. Sin esto, con bgutil-pot en
# el PATH el plugin lo encuentra solo, y WPC abriría el navegador.
_DISABLED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "__pot_provider_disabled__")

# Las URLs de formato de YouTube caducan en ~6 h: después de eso la descarga vuelve a
# extraer igual, así que recordar el perfil más tiempo no aporta.
_MEMORY_TTL_S = 6 * 3600

_YT_ID_RE = re.compile(r"(?:[?&]v=|youtu\.be/|/shorts/|/embed/|/live/|/v/)([0-9A-Za-z_-]{11})")

_memory = {}
_memory_lock = threading.Lock()


def _token_profile_ready(profile):
    if profile == PROFILE_WPC:
        from core.setup.wpc_setup import check_wpc, get_browser_path
        return check_wpc() and bool(get_browser_path())
    if profile == PROFILE_BGUTIL:
        from core.setup.potprovider_setup import check_all
        return check_all()
    return False


def profile_chain():
    """Perfiles utilizables, en orden. El proveedor elegido en Ajustes va primero entre
    los de token y el otro queda de último recurso; "none" deja solo el perfil sin token."""
    chosen = get_config().get("pot_provider", PROFILE_WPC)
    chain = [PROFILE_EMBEDDED]
    if chosen == "none":
        return chain
    order = (PROFILE_BGUTIL, PROFILE_WPC) if chosen == PROFILE_BGUTIL else (PROFILE_WPC, PROFILE_BGUTIL)
    chain += [p for p in order if _token_profile_ready(p)]
    return chain


def chain_for(url):
    """La cadena empezando por el perfil que ya funcionó con este video, si lo hay."""
    chain = profile_chain()
    remembered = recall(url)
    if remembered in chain:
        chain.remove(remembered)
        chain.insert(0, remembered)
    return chain


def apply_profile(ydl_opts, profile):
    """Escribe en ydl_opts los extractor_args de YouTube del perfil."""
    extractor_args = ydl_opts.setdefault('extractor_args', {})
    youtube_args = extractor_args.setdefault('youtube', {})

    if profile == PROFILE_EMBEDDED:
        youtube_args['player_client'] = ['web_embedded', 'default']
        # 'default' incluye 'web', que pide token para sus formatos https/DASH: con
        # fetch_pot=auto yt-dlp llamaría al proveedor instalado (WPC abriría el
        # navegador en cada análisis). web_embedded ya trae esos formatos sin token.
        youtube_args['fetch_pot'] = ['never']
        extractor_args.pop('youtubepot-wpc', None)
        extractor_args.pop('youtubepot-bgutilcli', None)
        extractor_args.pop('youtubepot-bgutilscript', None)
        return

    youtube_args['player_client'] = list(_TOKEN_CLIENTS)
    youtube_args.pop('fetch_pot', None)

    if profile == PROFILE_WPC:
        from core.setup.wpc_setup import get_browser_path, get_browser_display_name
        browser = get_browser_path()
        extractor_args['youtubepot-wpc'] = {'browser_path': [browser or _DISABLED_PATH]}
        extractor_args['youtubepot-bgutilcli'] = {'cli_path': [_DISABLED_PATH]}
        extractor_args.pop('youtubepot-bgutilscript', None)
        logger.info(f"ClientProfiles: perfil wpc -> {get_browser_display_name()} ({browser})")
    elif profile == PROFILE_BGUTIL:
        from core.setup.potprovider_setup import get_binary_path
        binary_path = get_binary_path()
        # Arg oficial del provider CLI (v0.8.1+). script_path también, para que
        # bgutil:http sepa que el modo CLI está activo y no espere el puerto 4416.
        extractor_args['youtubepot-bgutilcli'] = {'cli_path': [binary_path]}
        extractor_args['youtubepot-bgutilscript'] = {'script_path': [binary_path]}
        extractor_args['youtubepot-wpc'] = {'browser_path': [_DISABLED_PATH]}
        logger.info(f"ClientProfiles: perfil bgutil -> {binary_path}")


# Errores en los que otro perfil sí puede ayudar. Se comparan contra el texto crudo de
# yt-dlp, siempre en inglés (no traducir). Quedan fuera a propósito el 429 (cambiar de
# cliente solo suma peticiones y alarga el bloqueo) y la verificación de edad sin
# cookies (ningún cliente la evita).
_NEXT_PROFILE_MARKERS = (
    "playback on other websites has been disabled",
    "unplayable",
    "the page needs to be reloaded",
    "failed to extract any player response",
    "http error 403",
    "403: forbidden",
    "403 forbidden",
    "sign in to confirm you’re not a bot",
    "sign in to confirm you're not a bot",
    "confirm you are not a bot",
    "missing required visitor data",
    "unable to download video data",
    # Así llega a DowP el 403 de un stream que ffmpeg estaba bajando (cortes).
    "ffmpeg exited with code",
)


def should_try_next_profile(error_msg):
    lowered = str(error_msg or "").lower()
    if "http error 429" in lowered or "too many requests" in lowered:
        return False
    markers = [marker for marker in _NEXT_PROFILE_MARKERS if marker in lowered]
    if markers == ["ffmpeg exited with code"]:
        # Un error del equipo (EIO, disco lleno...) no lo arregla otro cliente.
        from core.ytdlp_logic.resilient_downloader import local_ffmpeg_error
        if local_ffmpeg_error(lowered):
            return False
    return bool(markers)


def youtube_video_id(url):
    match = _YT_ID_RE.search(url or "")
    return match.group(1) if match else None


def remember(url, profile, info=None):
    """Anota el perfil que funcionó para el video de la URL y, si el análisis trajo
    una playlist, para cada una de sus entradas (la cola las descarga por separado)."""
    keys = {youtube_video_id(url)}
    if isinstance(info, dict):
        if info.get("extractor_key", "").lower().startswith("youtube") and info.get("id"):
            keys.add(info["id"])
        for entry in info.get("entries") or []:
            if isinstance(entry, dict) and entry.get("id"):
                keys.add(entry["id"])
    keys.discard(None)
    if not keys:
        return
    expires = time.monotonic() + _MEMORY_TTL_S
    with _memory_lock:
        for key in keys:
            _memory[key] = (profile, expires)


def recall(url):
    key = youtube_video_id(url)
    if not key:
        return None
    with _memory_lock:
        entry = _memory.get(key)
        if not entry:
            return None
        profile, expires = entry
        if time.monotonic() > expires:
            del _memory[key]
            return None
        return profile
