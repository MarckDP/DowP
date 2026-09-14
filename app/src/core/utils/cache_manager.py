# src/core/utils/cache_manager.py
import os
from PySide6.QtCore import QCoreApplication
from abc import ABC, abstractmethod
from typing import Dict, List, Any
from core.logger.logger_manager import logger
from core.utils.paths import get_thumbnail_cache_dir, get_cache_dir, get_indexed_media_path


def format_bytes(bytes_size: int) -> str:
    """Formatea bytes en una representación legible para el usuario (B, KB, MB, GB)."""
    if bytes_size <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    size = float(bytes_size)
    while size >= 1024 and i < len(units) - 1:
        size /= 1024
        i += 1
    return f"{size:.2f} {units[i]}" if i > 0 else f"{int(size)} {units[i]}"


def format_bytes_compact(bytes_size: int) -> str:
    """Como format_bytes pero corto, para pesos que van pegados a un nombre
    (ej. "General (Estándar) (928 MB)" en los combos de modelos de IA): sin
    decimales a partir de 10 MB, porque ahí el segundo decimal no le dice nada a
    nadie y sí alarga cada ítem de la lista. Mismas unidades binarias que
    format_bytes -- las que muestra el explorador de archivos."""
    if bytes_size <= 0:
        return ""
    kb = bytes_size / 1024
    if kb < 1024:
        return f"{kb:.0f} KB"
    mb = kb / 1024
    if mb < 10:
        return f"{mb:.1f} MB"
    if mb < 1024:
        return f"{mb:.0f} MB"
    return f"{mb / 1024:.1f} GB"


class BaseCacheProvider(ABC):
    """Clase base abstracta para cualquier proveedor de caché en la aplicación."""

    @property
    @abstractmethod
    def key(self) -> str:
        """Clave identificadora única del proveedor de caché."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Nombre visible para el usuario."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Descripción explicativa de qué almacena esta caché."""
        pass

    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """
        Retorna las estadísticas actuales de la caché.
        Respuesta esperada: {
            "key": str,
            "name": str,
            "description": str,
            "file_count": int,
            "size_bytes": int,
            "formatted_size": str
        }
        """
        pass

    @abstractmethod
    def clear(self) -> Dict[str, Any]:
        """
        Elimina el contenido de la caché.
        Respuesta esperada: {
            "files_removed": int,
            "bytes_freed": int
        }
        """
        pass


class ImageThumbnailCacheProvider(BaseCacheProvider):
    """Proveedor de caché para imágenes y miniaturas generadas."""

    @property
    def key(self) -> str:
        return "thumbnails"

    @property
    def name(self) -> str:
        return QCoreApplication.translate("ImageThumbnailCacheProvider", "Caché de Imágenes y Miniaturas")

    @property
    def description(self) -> str:
        return QCoreApplication.translate("ImageThumbnailCacheProvider", "Miniaturas en disco generadas para previas rápidas de imágenes, videos y audios.")

    def get_stats(self) -> Dict[str, Any]:
        thumb_dir = get_thumbnail_cache_dir()
        file_count = 0
        total_size = 0

        if os.path.exists(thumb_dir):
            for entry in os.scandir(thumb_dir):
                if entry.is_file():
                    file_count += 1
                    try:
                        total_size += entry.stat().st_size
                    except Exception:
                        pass

        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "file_count": file_count,
            "size_bytes": total_size,
            "formatted_size": format_bytes(total_size)
        }

    def clear(self) -> Dict[str, Any]:
        stats_before = self.get_stats()
        from core.tabs.editing_media.thumbnail_cache_manager import ThumbnailCacheManager
        deleted_count = ThumbnailCacheManager.get_instance().clear_cache()
        return {
            "files_removed": deleted_count,
            "bytes_freed": stats_before["size_bytes"]
        }


class IndexingMetadataCacheProvider(BaseCacheProvider):
    """Proveedor de caché para indexación y metadatos extraídos con FFprobe."""

    @property
    def key(self) -> str:
        return "indexing_metadata"

    @property
    def name(self) -> str:
        return QCoreApplication.translate("IndexingMetadataCacheProvider", "Caché de Indexación y Metadatos")

    @property
    def description(self) -> str:
        return QCoreApplication.translate("IndexingMetadataCacheProvider", "Base de datos y caché de metadatos multimedia extraídos para optimizar la carga del árbol.")

    def get_stats(self) -> Dict[str, Any]:
        cache_dir = get_cache_dir()
        meta_cache_file = os.path.join(cache_dir, "metadata_cache.json")
        
        file_count = 0
        total_size = 0

        # Verificar metadata_cache.json
        if os.path.exists(meta_cache_file):
            try:
                from core.tabs.editing_media.ffprobe_metadata_manager import FFprobeMetadataManager
                mgr = FFprobeMetadataManager.get_instance()
                file_count += len(mgr.cache)
                total_size += os.path.getsize(meta_cache_file)
            except Exception:
                pass

        # Verificar indexed_media.json si existe
        indexed_path = get_indexed_media_path()
        if os.path.exists(indexed_path):
            try:
                total_size += os.path.getsize(indexed_path)
            except Exception:
                pass

        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "file_count": file_count,
            "size_bytes": total_size,
            "formatted_size": format_bytes(total_size)
        }

    def clear(self) -> Dict[str, Any]:
        stats_before = self.get_stats()
        from core.tabs.editing_media.ffprobe_metadata_manager import FFprobeMetadataManager
        deleted_count = FFprobeMetadataManager.get_instance().clear_cache()
        return {
            "files_removed": deleted_count,
            "bytes_freed": stats_before["size_bytes"]
        }


class FreesoundPreviewCacheProvider(BaseCacheProvider):
    """Proveedor de caché para previsualizaciones de audio/video de medios web (Freesound,
    Wikimedia, ...) — máximo MAX_FREESOUND_CACHE_FILES archivos LRU, compartido entre orígenes."""

    @property
    def key(self) -> str:
        return "freesound_previews"

    @property
    def name(self) -> str:
        return QCoreApplication.translate("FreesoundPreviewCacheProvider", "Caché de Previsualización Web")

    @property
    def description(self) -> str:
        from core.tabs.editing_media.freesound_preview_cache import MAX_FREESOUND_CACHE_FILES
        return QCoreApplication.translate("FreesoundPreviewCacheProvider", "Audios/videos en caché local para preescucha instantánea al explorar medios web (Freesound, Wikimedia, máx {0} archivos).").format(MAX_FREESOUND_CACHE_FILES)

    def get_stats(self) -> Dict[str, Any]:
        from core.utils.paths import get_freesound_cache_dir
        fs_dir = get_freesound_cache_dir()
        file_count = 0
        total_size = 0

        if os.path.exists(fs_dir):
            for entry in os.scandir(fs_dir):
                if entry.is_file() and not entry.name.endswith(".tmp"):
                    file_count += 1
                    try:
                        total_size += entry.stat().st_size
                    except Exception:
                        pass

        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "file_count": file_count,
            "size_bytes": total_size,
            "formatted_size": format_bytes(total_size)
        }

    def clear(self) -> Dict[str, Any]:
        stats_before = self.get_stats()
        from core.tabs.editing_media.freesound_preview_cache import FreesoundPreviewCacheManager
        deleted_count = FreesoundPreviewCacheManager.get_instance().clear_cache()
        return {
            "files_removed": deleted_count,
            "bytes_freed": stats_before["size_bytes"]
        }


class WaveformCacheProvider(BaseCacheProvider):
    """Proveedor de caché para las ondas de audio cacheadas (waveforms)."""

    @property
    def key(self) -> str:
        return "waveforms"

    @property
    def name(self) -> str:
        return QCoreApplication.translate("WaveformCacheProvider", "Caché de Ondas de Audio")

    @property
    def description(self) -> str:
        return QCoreApplication.translate("WaveformCacheProvider", "Formas de onda (waveforms) cacheadas para visualización instantánea en la cuadrícula y reproductor.")

    def get_stats(self) -> Dict[str, Any]:
        from core.utils.paths import get_waveform_cache_dir
        wf_dir = get_waveform_cache_dir()
        file_count = 0
        total_size = 0

        if os.path.exists(wf_dir):
            for entry in os.scandir(wf_dir):
                if entry.is_file():
                    file_count += 1
                    try:
                        total_size += entry.stat().st_size
                    except Exception:
                        pass

        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "file_count": file_count,
            "size_bytes": total_size,
            "formatted_size": format_bytes(total_size)
        }

    def clear(self) -> Dict[str, Any]:
        stats_before = self.get_stats()
        from core.tabs.editing_media.waveform_cache_manager import WaveformCacheManager
        deleted_count = WaveformCacheManager.get_instance().clear_cache()
        return {
            "files_removed": deleted_count,
            "bytes_freed": stats_before["size_bytes"]
        }


class ProxyCacheProvider(BaseCacheProvider):
    """Proveedor de caché para los proxies de previsualización (video de baja resolución para
    scrubbing fluido de medios pesados/RAW en Herramientas Multimedia)."""

    @property
    def key(self) -> str:
        return "video_proxies"

    @property
    def name(self) -> str:
        return QCoreApplication.translate("ProxyCacheProvider", "Caché de Proxies de Previsualización")

    @property
    def description(self) -> str:
        return QCoreApplication.translate("ProxyCacheProvider", "Copias de video en baja resolución generadas para reproducir fluido medios pesados/RAW. Con límite de tamaño automático.")

    def get_stats(self) -> Dict[str, Any]:
        from core.tabs.video_tools.proxy_cache_manager import ProxyCacheManager
        stats = ProxyCacheManager.get_instance().get_stats()
        file_count = stats.get("file_count", 0)
        total_size = stats.get("size_bytes", 0)

        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "file_count": file_count,
            "size_bytes": total_size,
            "formatted_size": format_bytes(total_size)
        }

    def clear(self) -> Dict[str, Any]:
        stats_before = self.get_stats()
        from core.tabs.video_tools.proxy_cache_manager import ProxyCacheManager
        deleted_count = ProxyCacheManager.get_instance().clear_cache()
        return {
            "files_removed": deleted_count,
            "bytes_freed": stats_before["size_bytes"]
        }


class RemoteThumbnailCacheProvider(BaseCacheProvider):
    """Proveedor de caché para miniaturas ya renderizadas por un origen web (ej. thumburl de
    Wikimedia) — separado del caché de previsualización de audio/video de arriba."""

    @property
    def key(self) -> str:
        return "remote_thumbnails"

    @property
    def name(self) -> str:
        return QCoreApplication.translate("RemoteThumbnailCacheProvider", "Caché de Miniaturas Web")

    @property
    def description(self) -> str:
        from core.tabs.editing_media.remote_thumbnail_cache_manager import MAX_REMOTE_THUMBNAIL_FILES
        return QCoreApplication.translate("RemoteThumbnailCacheProvider", "Miniaturas de imagen/video de orígenes web (ej. Wikimedia) cacheadas localmente (máx {0} archivos).").format(MAX_REMOTE_THUMBNAIL_FILES)

    def get_stats(self) -> Dict[str, Any]:
        from core.utils.paths import get_remote_thumbnail_cache_dir
        rt_dir = get_remote_thumbnail_cache_dir()
        file_count = 0
        total_size = 0

        if os.path.exists(rt_dir):
            for entry in os.scandir(rt_dir):
                if entry.is_file() and not entry.name.endswith(".tmp"):
                    file_count += 1
                    try:
                        total_size += entry.stat().st_size
                    except Exception:
                        pass

        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "file_count": file_count,
            "size_bytes": total_size,
            "formatted_size": format_bytes(total_size)
        }

    def clear(self) -> Dict[str, Any]:
        stats_before = self.get_stats()
        from core.tabs.editing_media.remote_thumbnail_cache_manager import RemoteThumbnailCacheManager
        deleted_count = RemoteThumbnailCacheManager.get_instance().clear_cache()
        return {
            "files_removed": deleted_count,
            "bytes_freed": stats_before["size_bytes"]
        }


class CacheManager:
    """Servicio centralizado que administra todos los proveedores de caché de la aplicación."""

    _instance = None

    @classmethod
    def get_instance(cls) -> "CacheManager":
        if cls._instance is None:
            cls._instance = CacheManager()
        return cls._instance

    def __init__(self):
        self._providers: Dict[str, BaseCacheProvider] = {}
        self._register_default_providers()

    def _register_default_providers(self):
        """Registra los proveedores por defecto de la aplicación."""
        self.register_provider(ImageThumbnailCacheProvider())
        self.register_provider(IndexingMetadataCacheProvider())
        self.register_provider(FreesoundPreviewCacheProvider())
        self.register_provider(WaveformCacheProvider())
        self.register_provider(ProxyCacheProvider())
        self.register_provider(RemoteThumbnailCacheProvider())


    def register_provider(self, provider: BaseCacheProvider):
        """Permite registrar un nuevo proveedor de caché dinámicamente."""
        self._providers[provider.key] = provider
        logger.info(f"CacheManager: Proveedor de caché registrado: '{provider.key}' ({provider.name})")

    def get_providers(self) -> List[BaseCacheProvider]:
        """Retorna la lista de proveedores registrados."""
        return list(self._providers.values())

    def get_all_stats(self) -> Dict[str, Any]:
        """
        Retorna estadísticas de cada proveedor y el total acumulado.
        """
        provider_stats = []
        total_files = 0
        total_bytes = 0

        for provider in self._providers.values():
            try:
                st = provider.get_stats()
                provider_stats.append(st)
                total_files += st.get("file_count", 0)
                total_bytes += st.get("size_bytes", 0)
            except Exception as e:
                logger.error(f"CacheManager: Error obteniendo stats de '{provider.key}': {e}")

        return {
            "total_files": total_files,
            "total_bytes": total_bytes,
            "formatted_total_size": format_bytes(total_bytes),
            "providers": provider_stats
        }

    def clear_provider(self, key: str) -> Dict[str, Any]:
        """Limpia un proveedor específico por su clave."""
        if key in self._providers:
            try:
                res = self._providers[key].clear()
                logger.info(f"CacheManager: Caché '{key}' limpiada correctamente.")
                return res
            except Exception as e:
                logger.error(f"CacheManager: Error limpiando caché '{key}': {e}")
        return {"files_removed": 0, "bytes_freed": 0}

    def clear_all(self) -> Dict[str, Any]:
        """Limpia todas las cachés registradas."""
        total_removed = 0
        total_freed = 0
        for key, provider in self._providers.items():
            try:
                res = provider.clear()
                total_removed += res.get("files_removed", 0)
                total_freed += res.get("bytes_freed", 0)
            except Exception as e:
                logger.error(f"CacheManager: Error limpiando todas las cachés en '{key}': {e}")

        logger.info(f"CacheManager: Limpieza total completada. Archivos: {total_removed}, Tamaño liberado: {format_bytes(total_freed)}")
        return {
            "files_removed": total_removed,
            "bytes_freed": total_freed,
            "formatted_freed": format_bytes(total_freed)
        }
