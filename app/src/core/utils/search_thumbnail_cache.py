# src/core/utils/search_thumbnail_cache.py
"""Caché en disco de las miniaturas chicas de la ventana de búsqueda (media_search_dialog).

Aislada a propósito de la lógica de miniaturas de descarga: carpeta propia
(cache/search_thumbnails), nada de aquí se entrega a los flujos de descarga -- la ventana
de búsqueda solo devuelve URLs y cada pestaña vuelve a analizar el video desde cero."""
import hashlib
import os
import time

import requests
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from core.logger.logger_manager import logger
from core.utils.paths import get_search_thumbnail_cache_dir

MAX_SEARCH_THUMBNAIL_FILES = 400
FAILURE_COOLDOWN_SECONDS = 300
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}


class _ThumbRunnable(QRunnable):
    def __init__(self, url: str, target_path: str, manager: "SearchThumbnailCache"):
        super().__init__()
        self.url = url
        self.target_path = target_path
        self.manager = manager

    def run(self):
        temp_path = self.target_path + ".tmp"
        ok = False
        try:
            response = requests.get(self.url, headers=_HEADERS, timeout=10)
            response.raise_for_status()
            if response.content:
                with open(temp_path, "wb") as f:
                    f.write(response.content)
                os.replace(temp_path, self.target_path)
                ok = True
        except Exception as e:
            logger.debug(f"SearchThumbnailCache: No se pudo bajar {self.url}: {e}")
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
        self.manager._task_finished(self.url, self.target_path if ok else "")


class SearchThumbnailCache(QObject):
    """Baja y cachea miniaturas en segundo plano. Límite de MAX_SEARCH_THUMBNAIL_FILES
    archivos: al pasarlo se borran los más viejos (por fecha de uso)."""

    thumbnail_ready = Signal(str, str)  # (url, local_path)

    _instance = None

    @classmethod
    def get_instance(cls) -> "SearchThumbnailCache":
        if cls._instance is None:
            cls._instance = SearchThumbnailCache()
        return cls._instance

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(6)
        self._pending: set[str] = set()
        self._failed: dict[str, float] = {}
        self._downloads_since_trim = 0

    def _path_for(self, url: str) -> str:
        name = hashlib.md5(url.encode("utf-8")).hexdigest() + ".jpg"
        return os.path.join(get_search_thumbnail_cache_dir(), name)

    def get_cached_path(self, url: str) -> str:
        path = self._path_for(url)
        if os.path.exists(path):
            try:
                os.utime(path, None)  # marca de uso para el recorte por antigüedad
            except Exception:
                pass
            return path
        return ""

    def request(self, url: str) -> str:
        """Devuelve la ruta si ya está en disco; si no, la pide en segundo plano (llega por
        thumbnail_ready) y devuelve ''."""
        if not url:
            return ""
        cached = self.get_cached_path(url)
        if cached:
            return cached
        if url in self._pending:
            return ""
        failed_at = self._failed.get(url)
        if failed_at and time.time() - failed_at < FAILURE_COOLDOWN_SECONDS:
            return ""
        self._pending.add(url)
        self.pool.start(_ThumbRunnable(url, self._path_for(url), self))
        return ""

    def _task_finished(self, url: str, path: str):
        # Llamado desde el hilo del pool: la señal se entrega en el hilo principal.
        self._pending.discard(url)
        if not path:
            self._failed[url] = time.time()
            return
        self._downloads_since_trim += 1
        if self._downloads_since_trim >= 20:
            self._downloads_since_trim = 0
            self._trim()
        self.thumbnail_ready.emit(url, path)

    def _trim(self):
        try:
            entries = [e for e in os.scandir(get_search_thumbnail_cache_dir())
                       if e.is_file() and not e.name.endswith(".tmp")]
            if len(entries) <= MAX_SEARCH_THUMBNAIL_FILES:
                return
            entries.sort(key=lambda e: e.stat().st_mtime)
            for entry in entries[:len(entries) - MAX_SEARCH_THUMBNAIL_FILES]:
                try:
                    os.remove(entry.path)
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"SearchThumbnailCache: Error recortando la caché: {e}")

    def clear_cache(self) -> int:
        removed = 0
        cache_dir = get_search_thumbnail_cache_dir()
        for entry in os.scandir(cache_dir):
            if entry.is_file():
                try:
                    os.remove(entry.path)
                    removed += 1
                except Exception:
                    pass
        self._failed.clear()
        return removed


def search_thumbnail_stats() -> tuple:
    """(cantidad, bytes) de la caché, para Ajustes > Memoria y Caché."""
    count, size = 0, 0
    cache_dir = get_search_thumbnail_cache_dir()
    for entry in os.scandir(cache_dir):
        if entry.is_file() and not entry.name.endswith(".tmp"):
            count += 1
            try:
                size += entry.stat().st_size
            except Exception:
                pass
    return count, size
