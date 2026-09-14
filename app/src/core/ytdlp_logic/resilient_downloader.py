# src/core/ytdlp_logic/resilient_downloader.py
"""
Módulo de resiliencia inspirado en Xomacito para reintentar descargas y análisis
ante bloqueos temporales de YouTube (HTTP 403, HTTP 429, bot-check).
"""
import copy
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


def is_youtube_access_error(url: str, error_msg: object) -> bool:
    """Detecta si el error es un bloqueo temporal de YouTube que admite un cliente alternativo."""
    if not url:
        return False
    lowered = str(error_msg or "").lower()
    return any(marker in lowered for marker in YOUTUBE_ACCESS_MARKERS)


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
    if "format" in fallback and fallback["format"]:
        fmt = str(fallback["format"])
        if "/bestvideo" not in fmt and "/best" not in fmt:
            fallback["format"] = f"{fmt}/bestvideo+bestaudio/best"

    return fallback
