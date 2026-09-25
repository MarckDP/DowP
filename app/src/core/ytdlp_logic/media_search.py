# src/core/ytdlp_logic/media_search.py
"""Búsqueda de medios (YouTube / SoundCloud) para la ventana de la lupa de Modo Rápido y
Proceso Avanzado -- ver gui/dialogs/media_search_dialog.py.

Todo va en modo 'extract_flat': solo se leen los listados (título, duración, canal, ID),
nunca los formatos de cada video, así una página de 20 resultados tarda 1-5 s. La ventana
devuelve únicamente URLs: el análisis real (formatos, miniatura buena, etc.) lo hace el
flujo normal de cada pestaña, como si el usuario hubiera pegado la URL a mano.

Cómo se arma cada filtro de YouTube (probado con yt-dlp 2026.08.19, ver conversación):
- Todos / Videos / Directos: página de resultados de YouTube con el parámetro 'sp' nativo
  (Videos = "Tipo: Video", que excluye Shorts y directos; Directos = "En vivo").
- Shorts: el filtro nativo de Shorts casi no devuelve nada por yt-dlp (2-3 resultados), así
  que se usa la página de Shorts del hashtag (/hashtag/<texto>/shorts). Si el hashtag no
  existe o viene vacío, se recurre al filtro nativo como respaldo. Estos Shorts no traen
  canal.
"""
import re
from urllib.parse import quote, quote_plus

from PySide6.QtCore import QCoreApplication

from core.logger.logger_manager import logger
from core.ytdlp_logic.analyzer import get_base_ydl_opts, load_ytdlp_module

SOURCE_YOUTUBE = "youtube"
SOURCE_SOUNDCLOUD = "soundcloud"

FILTER_ALL = "all"
FILTER_VIDEOS = "videos"
FILTER_SHORTS = "shorts"
FILTER_LIVE = "live"

PAGE_SIZE = 20

_YT_RESULTS_URL = "https://www.youtube.com/results?search_query={q}"
_YT_SP = {
    FILTER_VIDEOS: "EgIQAQ%3D%3D",
    FILTER_LIVE: "EgJAAQ%3D%3D",
    FILTER_SHORTS: "EgIQCQ%3D%3D",  # solo respaldo, ver docstring del módulo
}
# Secciones de un canal de YouTube equivalentes a cada filtro (el canal no tiene "Todos").
_YT_CHANNEL_TABS = {
    FILTER_VIDEOS: "/videos",
    FILTER_SHORTS: "/shorts",
    FILTER_LIVE: "/streams",
}


def shorts_hashtag(query: str) -> str:
    """'green screen' -> 'greenscreen' (el hashtag que se consulta para el filtro Shorts)."""
    return re.sub(r"[\W_]+", "", query or "").lower()


def _extract_entries(url: str, page: int) -> list:
    # Mismo yt-dlp (ZIP + plugins) que el análisis. A diferencia de get_video_info no se
    # toca os.environ["PATH"]: un listado flat no lanza ffmpeg ni deno, y cambiar PATH
    # desde otro hilo a la vez que un análisis dejaría el PATH de alguno mal restaurado.
    yt_dlp = load_ytdlp_module()
    if yt_dlp is None:
        raise RuntimeError(QCoreApplication.translate("media_search", "No se pudo cargar yt-dlp."))
    start = (page - 1) * PAGE_SIZE + 1
    opts = get_base_ydl_opts({
        "extract_flat": "in_playlist",
        "skip_download": True,
        "playliststart": start,
        "playlistend": start + PAGE_SIZE - 1,
    })
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return [e for e in (info or {}).get("entries") or [] if e]


def _youtube_thumb(video_id: str) -> str:
    # Variante chica fija (320x180): los listados traen 'hq720', que es mucho más grande
    # de lo que necesita una tarjeta. Esta miniatura es SOLO para la ventana de búsqueda.
    return f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"


def _soundcloud_thumb(entry: dict) -> str:
    thumbs = {t.get("id"): t.get("url") for t in entry.get("thumbnails") or [] if t.get("url")}
    for key in ("t300x300", "large", "small"):
        if thumbs.get(key):
            return thumbs[key]
    return entry.get("thumbnail") or ""


def _normalize_youtube(entry: dict):
    video_id = entry.get("id")
    if not video_id:
        return None
    live_status = entry.get("live_status")
    # Programados (estreno/directo que aún no empieza): no hay nada que descargar todavía.
    if live_status == "is_upcoming":
        return None
    url = entry.get("url") or f"https://www.youtube.com/watch?v={video_id}"
    return {
        "id": video_id,
        "url": url,
        "title": entry.get("title") or video_id,
        "duration": entry.get("duration"),
        "thumb_url": _youtube_thumb(video_id),
        "channel": entry.get("channel") or entry.get("uploader") or "",
        "channel_url": entry.get("channel_url") or entry.get("uploader_url") or "",
        "is_live": live_status == "is_live",
        "is_short": "/shorts/" in url,
        "source": SOURCE_YOUTUBE,
    }


def _normalize_soundcloud(entry: dict):
    url = entry.get("webpage_url") or entry.get("url")
    if not url:
        return None
    return {
        "id": str(entry.get("id") or url),
        "url": url,
        "title": entry.get("title") or url,
        "duration": entry.get("duration"),
        "thumb_url": _soundcloud_thumb(entry),
        "channel": entry.get("uploader") or "",
        # Los listados de un usuario de SoundCloud vienen sin miniatura ni duración en modo
        # flat -- el artista se muestra pero no es clicable.
        "channel_url": "",
        "is_live": False,
        "is_short": False,
        "source": SOURCE_SOUNDCLOUD,
    }


def _finish(raw_entries: list, normalizer, hint: str = "") -> dict:
    results, seen = [], set()
    for entry in raw_entries:
        item = normalizer(entry)
        if item and item["id"] not in seen:
            seen.add(item["id"])
            results.append(item)
    return {
        "results": results,
        # Una página completa sugiere que hay más; una incompleta, que se terminó.
        "has_more": len(raw_entries) >= PAGE_SIZE,
        "hint": hint,
    }


def search(query: str, source: str = SOURCE_YOUTUBE, filter_key: str = FILTER_ALL, page: int = 1) -> dict:
    """Devuelve {'results': [item, ...], 'has_more': bool, 'hint': str}. Lanza excepción si
    yt-dlp falla (la ventana muestra el mensaje)."""
    query = (query or "").strip()
    if not query:
        return {"results": [], "has_more": False, "hint": ""}

    if source == SOURCE_SOUNDCLOUD:
        # scsearchN: N es el tope total, así que se pide hasta el final de esta página.
        raw = _extract_entries(f"scsearch{page * PAGE_SIZE}:{query}", page)
        return _finish(raw, _normalize_soundcloud)

    if filter_key == FILTER_SHORTS:
        tag = shorts_hashtag(query)
        if tag:
            try:
                raw = _extract_entries(f"https://www.youtube.com/hashtag/{quote(tag)}/shorts", page)
                if raw or page > 1:
                    return _finish(raw, _normalize_youtube, hint="hashtag")
            except Exception as e:
                logger.info(f"MediaSearch: Hashtag #{tag} sin Shorts ({e}), usando filtro nativo.")
        raw = _extract_entries(_YT_RESULTS_URL.format(q=quote_plus(query)) + "&sp=" + _YT_SP[FILTER_SHORTS], page)
        return _finish(raw, _normalize_youtube, hint="fallback")

    url = _YT_RESULTS_URL.format(q=quote_plus(query))
    if filter_key in _YT_SP:
        url += "&sp=" + _YT_SP[filter_key]
    return _finish(_extract_entries(url, page), _normalize_youtube)


def browse_channel(channel_url: str, filter_key: str = FILTER_VIDEOS, page: int = 1) -> dict:
    """Lista una sección (Videos / Shorts / Directos) de un canal de YouTube."""
    tab = _YT_CHANNEL_TABS.get(filter_key, "/videos")
    try:
        raw = _extract_entries(channel_url.rstrip("/") + tab, page)
    except Exception as e:
        # Un canal sin esa sección (ej. sin Shorts) no es un error para el usuario: yt-dlp
        # responde "This channel does not have a shorts tab".
        if "does not have a" in str(e):
            return {"results": [], "has_more": False, "hint": ""}
        raise
    return _finish(raw, _normalize_youtube)


def is_live_now(info):
    """True si el análisis de yt-dlp dice que es un directo en curso."""
    return bool(info) and (info.get("live_status") == "is_live" or info.get("is_live") is True)
