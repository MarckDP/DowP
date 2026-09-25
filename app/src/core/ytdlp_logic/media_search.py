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

Cada resultado trae 'kind': 'video' | 'playlist' | 'channel' (ver conversación: antes TODO
se trataba como video, y una búsqueda de YouTube mezcla playlists y canales entre los
resultados -- con bastante frecuencia, no un caso raro. Una entrada de canal/playlist tiene
un 'id' que no es un ID de video, así que su miniatura se armaba con
i.ytimg.com/vi/<ese id>/mqdefault.jpg, una URL sin sentido que nunca carga: esa era la causa
real de "hay videos que nunca cargan su miniatura", no una falla de red).
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

KIND_VIDEO = "video"
KIND_PLAYLIST = "playlist"
KIND_CHANNEL = "channel"

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


def _youtube_video_thumb(video_id: str) -> str:
    # Variante chica fija (320x180): los listados traen 'hq720', que es mucho más grande
    # de lo que necesita una tarjeta. Esta miniatura es SOLO para la ventana de búsqueda.
    return f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"


def _best_thumb_url(thumbs: list, prefer_small: bool = True) -> str:
    """Elige una URL de miniatura de la lista 'thumbnails' de yt-dlp (vienen sin 'https:'
    adelante -- protocol-relative). Por defecto la más chica que alcance, siguiendo el
    criterio del resto de la app de no guardar/usar variantes grandes de más."""
    valid = [t for t in thumbs or [] if t.get("url")]
    if not valid:
        return ""
    valid.sort(key=lambda t: (t.get("width") or 0) * (t.get("height") or 0), reverse=not prefer_small)
    url = valid[0]["url"]
    return "https:" + url if url.startswith("//") else url


def _soundcloud_thumb(entry: dict) -> str:
    thumbs = {t.get("id"): t.get("url") for t in entry.get("thumbnails") or [] if t.get("url")}
    for key in ("t300x300", "large", "small"):
        if thumbs.get(key):
            return thumbs[key]
    return entry.get("thumbnail") or ""


def _normalize_video(entry: dict, video_id: str) -> dict:
    live_status = entry.get("live_status")
    url = entry.get("url") or f"https://www.youtube.com/watch?v={video_id}"
    return {
        "kind": KIND_VIDEO,
        "id": video_id,
        "url": url,
        "title": entry.get("title") or video_id,
        "duration": entry.get("duration"),
        "thumb_url": _youtube_video_thumb(video_id),
        "channel": entry.get("channel") or entry.get("uploader") or "",
        "channel_url": entry.get("channel_url") or entry.get("uploader_url") or "",
        "is_live": live_status == "is_live",
        "is_short": "/shorts/" in url,
        "source": SOURCE_YOUTUBE,
    }


def _normalize_playlist(entry: dict, playlist_id: str) -> dict:
    url = entry.get("url") or f"https://www.youtube.com/playlist?list={playlist_id}"
    return {
        "kind": KIND_PLAYLIST,
        "id": playlist_id,
        "url": url,
        "title": entry.get("title") or playlist_id,
        # La miniatura del primer video de la playlist -- ya viene en el mismo listado, sin
        # pedir nada aparte (ver conversación: se decidió NO abrir la playlist para sacar
        # más miniaturas ni el conteo de videos, que tampoco viene en modo flat).
        "thumb_url": _best_thumb_url(entry.get("thumbnails")),
        "channel": entry.get("channel") or entry.get("uploader") or "",
        "channel_url": entry.get("channel_url") or entry.get("uploader_url") or "",
        "is_live": False,
        "is_short": False,
        "source": SOURCE_YOUTUBE,
    }


def _normalize_channel(entry: dict, channel_id: str) -> dict:
    url = entry.get("url") or entry.get("channel_url") or f"https://www.youtube.com/channel/{channel_id}"
    return {
        "kind": KIND_CHANNEL,
        "id": channel_id,
        "url": url,
        "title": entry.get("channel") or entry.get("title") or channel_id,
        # Avatar redondo -- la variante chica (88x88) alcanza de sobra para el círculo de
        # la tarjeta.
        "thumb_url": _best_thumb_url(entry.get("thumbnails")),
        "subscriber_count": entry.get("channel_follower_count"),
        "is_verified": bool(entry.get("channel_is_verified")),
        "source": SOURCE_YOUTUBE,
    }


def _normalize_youtube(entry: dict):
    """Distingue video / playlist / canal dentro de una búsqueda o listado de YouTube --
    las tres formas comparten 'ie_key'/'url'/'id', pero con formas muy distintas (ver
    conversación: antes esta función solo sabía de videos, y trataba playlists y canales
    como si lo fueran, con una miniatura rota de origen)."""
    entry_id = entry.get("id") or ""
    url = entry.get("url") or ""
    ie_key = entry.get("ie_key")

    if ie_key == "YoutubeTab":
        if "/playlist" in url or entry_id.startswith(("PL", "RD", "UU", "OL", "LL", "FL")):
            return _normalize_playlist(entry, entry_id)
        if "/channel" in url or "/@" in url or entry_id.startswith("UC"):
            return _normalize_channel(entry, entry_id)
        return None  # otra pestaña desconocida de YouTube -- se descarta, no se adivina

    if not entry_id:
        return None
    if entry.get("live_status") == "is_upcoming":
        # Programado (estreno/directo que aún no empieza): nada que descargar todavía.
        return None
    return _normalize_video(entry, entry_id)


def _normalize_soundcloud(entry: dict):
    url = entry.get("webpage_url") or entry.get("url")
    if not url:
        return None
    return {
        "kind": KIND_VIDEO,
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


def search_in_channel(channel_url: str, query: str, filter_key: str = FILTER_ALL, page: int = 1) -> dict:
    """Busca DENTRO de un canal (YouTube tiene su propia página de búsqueda acotada por
    canal, probada en conversación: youtube.com/channel/<id>/search?query=texto). Mismos
    filtros 'sp' que la búsqueda general -- también componen con esta URL."""
    query = (query or "").strip()
    if not query:
        return {"results": [], "has_more": False, "hint": ""}
    url = channel_url.rstrip("/") + "/search?query=" + quote_plus(query)
    if filter_key in _YT_SP:
        url += "&sp=" + _YT_SP[filter_key]
    return _finish(_extract_entries(url, page), _normalize_youtube)


def is_live_now(info):
    """True si el análisis de yt-dlp dice que es un directo en curso."""
    return bool(info) and (info.get("live_status") == "is_live" or info.get("is_live") is True)
