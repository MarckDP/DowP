# src/core/ytdlp_logic/resilient_downloader.py
"""
Módulo de resiliencia inspirado en Xomacito para reintentar descargas y análisis
ante bloqueos temporales de YouTube (HTTP 403, HTTP 429, bot-check).
"""
import copy
import re
from core.logger.logger_manager import logger

# Marcadores de deteccion: se comparan contra el texto de error crudo de yt-dlp/red, que
# SIEMPRE esta en ingles (nunca pasa por el sistema de traduccion de la UI) - no envolver
# en QCoreApplication.translate() aca, o la deteccion se rompe en cuanto se traduzca
# alguna de estas frases a otro idioma.
YOUTUBE_ACCESS_MARKERS = (
    "http error 403",
    "403: forbidden",
    "403 forbidden",
    "server returned 403",
    "access denied",
    "ffmpeg exited with code",
    "http error 429",
    "too many requests",
    "sign in to confirm you’re not a bot",
    "sign in to confirm you're not a bot",
    "confirm you are not a bot",
    "missing required visitor data",
    "unable to download video data",
)


# Códigos de salida de ffmpeg que son errores del propio equipo, no de YouTube: el código
# es el errno negado (-5 = EIO), que Mac y Linux truncan a un byte (251) y Windows deja en
# 32 bits (4294967291). Los errores HTTP de ffmpeg son otros (403: 8 en Mac y Linux,
# 3436169992 en Windows) y siguen contando como bloqueo. Caso real: en Mac, el ffmpeg sin
# certificados para https salía con 251 en todos los fragmentos, y DowP reintentaba con
# los otros perfiles (abriendo Chrome para wpc) sin ninguna posibilidad de que funcionara.
_LOCAL_FFMPEG_ERRNOS = {
    2: "ENOENT",    # no existe el archivo o la carpeta
    5: "EIO",       # entrada/salida: disco, o la conexión https que ffmpeg no pudo abrir
    13: "EACCES",   # sin permiso
    28: "ENOSPC",   # disco lleno
    30: "EROFS",    # disco de solo lectura
}
_LOCAL_FFMPEG_CODES = {code for errno in _LOCAL_FFMPEG_ERRNOS for code in ((-errno) & 0xFF, (-errno) & 0xFFFFFFFF)}
_FFMPEG_EXIT_RE = re.compile(r"ffmpeg exited with code (\d+)")


def local_ffmpeg_error(error_msg: object) -> str | None:
    """Nombre del errno ("EIO") si ffmpeg falló por algo del equipo; None si no."""
    match = _FFMPEG_EXIT_RE.search(str(error_msg or "").lower())
    if not match or int(match.group(1)) not in _LOCAL_FFMPEG_CODES:
        return None
    code = int(match.group(1))
    return next(name for errno, name in _LOCAL_FFMPEG_ERRNOS.items()
                if code in ((-errno) & 0xFF, (-errno) & 0xFFFFFFFF))


def is_youtube_access_error(url: str, error_msg: object) -> bool:
    """Detecta si el error es un bloqueo temporal de YouTube que admite un cliente alternativo."""
    if not url:
        return False
    lowered = str(error_msg or "").lower()
    markers = [marker for marker in YOUTUBE_ACCESS_MARKERS if marker in lowered]
    if markers == ["ffmpeg exited with code"] and local_ffmpeg_error(lowered):
        logger.warning(f"Resiliencia: ffmpeg falló por un error del equipo ({local_ffmpeg_error(lowered)}), "
                       "no de YouTube: no se reintenta con otros clientes.")
        return False
    return bool(markers)


CDN_FORBIDDEN_MARKERS = (
    "http error 403",
    "403: forbidden",
    "403 forbidden",
    "server returned 403",
)


def is_cdn_forbidden_error(error_msg: object) -> bool:
    """403 al bajar el medio (no un 429 ni un aviso de bot). Con PO token, el cliente
    mweb es el que ofrece la máxima calidad (4K, AV1...) y su 403 es intermitente:
    una extracción nueva trae URLs y token nuevos y suele funcionar. El cliente
    alternativo, en cambio, a menudo solo tiene formatos combinados de menor calidad
    (SABR). Ante un 429 o un aviso de bot no conviene insistir con el mismo cliente."""
    lowered = str(error_msg or "").lower()
    return any(marker in lowered for marker in CDN_FORBIDDEN_MARKERS)


def _preserve_format_with_fallback(opts: dict) -> None:
    """Otro cliente puede no exponer el ID exacto elegido (ej. "299+140"): se agrega
    bestvideo+bestaudio/best como último recurso en vez de fallar con "Requested
    format is not available"."""
    if "format" in opts and opts["format"]:
        fmt = str(opts["format"])
        if "/bestvideo" not in fmt and "/best" not in fmt:
            opts["format"] = f"{fmt}/bestvideo+bestaudio/best"


def make_profile_fallback_opts(ydl_opts: dict, profile: str) -> dict:
    """Opciones de respaldo para YouTube: las mismas, con otro perfil de clientes
    (ver client_profiles)."""
    from core.ytdlp_logic.client_profiles import apply_profile
    fallback = copy.deepcopy(ydl_opts)
    apply_profile(fallback, profile)
    # Los encabezados fijos son los del cliente original; cada cliente trae los suyos.
    fallback.pop("user_agent", None)
    fallback.pop("referer", None)
    fallback.pop("impersonate", None)
    _preserve_format_with_fallback(fallback)
    return fallback


def make_fallback_ydl_opts(ydl_opts: dict) -> dict:
    """
    Crea opciones de fallback usando el cliente 'web_embedded' (patrón Xomacito).
    Este cliente permite descargar videos sin cookies ni PO Token cuando el cliente
    principal recibe 403 o 429.
    Preserva el formato preferido por el usuario añadiendo un fallback automático
    en caso de que el ID exacto no esté expuesto por el reproductor embebido.
    """
    fallback = copy.deepcopy(ydl_opts)
    extractor_args = fallback.setdefault("extractor_args", {})
    youtube_args = extractor_args.setdefault("youtube", {})

    if fallback.get("cookiefile") or fallback.get("cookiesfrombrowser"):
        youtube_args["player_client"] = ["tv", "default", "-android_sdkless", "-android_vr"]
    else:
        # Modo sin cookies: web_embedded bypassea bot-check y 403 en la mayoría de videos
        youtube_args["player_client"] = ["web_embedded"]

    youtube_args.pop("n_client", None)
    youtube_args["skip"] = []

    # Remover encabezados fijos para que yt-dlp use los del cliente web_embedded
    fallback.pop("user_agent", None)
    fallback.pop("referer", None)
    fallback.pop("impersonate", None)

    # Preservar el formato elegido por el usuario (ej: "299+140"):
    # yt-dlp probará primero "299+140"; si ese ID de stream no está disponible
    # en web_embedded, pasará a bestvideo+bestaudio/best en lugar de crash-403.
    _preserve_format_with_fallback(fallback)

    return fallback
