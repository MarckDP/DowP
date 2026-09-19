# src/core/tabs/editing_media/web_sources/pixabay_provider.py
import os
import requests
from core.logger.logger_manager import logger
from core.tabs.editing_media.web_sources.base import WebSourceProvider
from core.utils.config_manager import get_config, save_config
from PySide6.QtCore import QCoreApplication

IMAGE_URL = "https://pixabay.com/api/"
VIDEO_URL = "https://pixabay.com/api/videos/"
PAGE_SIZE = 20


class PixabayProvider(WebSourceProvider):
    """Cliente de búsqueda/descarga sobre la API de Pixabay (imágenes, ilustraciones,
    vectores y video). A diferencia de Freesound (OAuth2), usa una API key simple que el
    usuario genera en su propia cuenta de Pixabay y pega en DowP (ver api_key_url/
    api_key_instructions, consumidos por ApiKeyLoginWidget). Todo el catálogo comparte una
    única licencia (la "Licencia de Pixabay"), así que a diferencia de Freesound/Wikimedia
    no hay nada que filtrar por licencia -- ver license_filter_options vacío."""

    id = "pixabay"
    display_name = "Pixabay"
    requires_auth = True
    supported_media_types = {"imagen", "video"}
    license_filter_options: list = []
    api_key_url = "https://pixabay.com/api/docs/"
    api_key_instructions = QCoreApplication.translate(
        "PixabayProvider",
        "1. Inicia sesión o crea una cuenta gratuita en Pixabay.\n"
        "2. En esa misma página, tu API key va a estar visible (se genera automáticamente).\n"
        "3. Cópiala y pégala aquí abajo."
    )

    def __init__(self):
        self.session = requests.Session()

    def get_api_key(self) -> str:
        return get_config().get("pixabay_api_key", "") or ""

    def set_api_key(self, key: str):
        config = get_config()
        config["pixabay_api_key"] = (key or "").strip()
        save_config(config)

    def is_authenticated(self) -> bool:
        return bool(self.get_api_key())

    def validate_api_key(self, key: str):
        key = (key or "").strip()
        if not key:
            return False, QCoreApplication.translate("PixabayProvider", "La API key no puede estar vacía.")
        try:
            resp = self.session.get(IMAGE_URL, params={"key": key, "q": "test", "per_page": 3}, timeout=10)
        except requests.exceptions.RequestException as e:
            return False, QCoreApplication.translate("PixabayProvider", "Error de red al validar: {0}").format(e)
        if resp.status_code == 200:
            return True, ""
        if resp.status_code in (400, 401, 403):
            return False, QCoreApplication.translate("PixabayProvider", "La API key no es válida.")
        return False, QCoreApplication.translate("PixabayProvider", "Pixabay respondió con un error ({0}).").format(resp.status_code)

    def normalize_license(self, raw_license: str) -> str:
        return "pixabay_license"

    def search(self, query: str, page: int = 1, **filters) -> dict:
        key = self.get_api_key()
        if not key:
            raise ValueError(QCoreApplication.translate("PixabayProvider", "API key de Pixabay requerida."))

        media_type = filters.get("media_type")
        query = (query or "").strip()

        # Pixabay expone imágenes y video en 2 endpoints separados (a diferencia de Wikimedia,
        # que resuelve todo en una sola búsqueda con filemime:) -- si no hay filtro de tipo
        # activo hay que pedir a ambos y repartir la página entre los dos.
        results = []
        if media_type in (None, "imagen"):
            results.extend(self._search_images(key, query, page, full=media_type == "imagen"))
        if media_type in (None, "video"):
            results.extend(self._search_videos(key, query, page, full=media_type == "video"))
        return {"results": results}

    def _search_images(self, key, query, page, full):
        per_page = PAGE_SIZE if full else PAGE_SIZE // 2
        params = {"key": key, "per_page": max(per_page, 3), "page": page, "safesearch": "true"}
        if query:
            params["q"] = query
        try:
            resp = self.session.get(IMAGE_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"PixabayProvider: Error buscando imágenes: {e}")
            raise IOError(QCoreApplication.translate("PixabayProvider", "Error de red al conectar con Pixabay: {0}").format(e))
        return [item for item in (self._map_image(hit) for hit in data.get("hits", [])) if item]

    def _search_videos(self, key, query, page, full):
        per_page = PAGE_SIZE if full else PAGE_SIZE // 2
        params = {"key": key, "per_page": max(per_page, 3), "page": page, "safesearch": "true"}
        if query:
            params["q"] = query
        try:
            resp = self.session.get(VIDEO_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"PixabayProvider: Error buscando videos: {e}")
            raise IOError(QCoreApplication.translate("PixabayProvider", "Error de red al conectar con Pixabay: {0}").format(e))
        return [item for item in (self._map_video(hit) for hit in data.get("hits", [])) if item]

    def _map_image(self, hit: dict):
        url = hit.get("largeImageURL") or hit.get("webformatURL")
        if not url:
            return None
        size_val = hit.get("imageSize", 0) or 0
        size_kb = size_val / 1024.0
        size_str = f"{size_kb / 1024.0:.1f} MB" if size_kb > 1024 else f"{size_kb:.1f} KB"
        return {
            "nombre": f"pixabay_{hit.get('id')}.jpg",
            "ruta": hit.get("previewURL") or url,
            "download_url": url,
            "tipo": "imagen",
            "file_type": "JPG",
            "tamaño": size_str,
            "resolución": f"{hit.get('imageWidth', 0)}x{hit.get('imageHeight', 0)}",
            "es_remoto": True,
            "username": hit.get("user", "-"),
            "license": "Pixabay License",
            "library": "Pixabay",
            "source_id": "pixabay",
            "id": str(hit.get("id", "")),
            "url": hit.get("pageURL", ""),
            # Sin esto, tanto el ícono en grilla como la vista previa grande caen al
            # placeholder genérico (ver media_model.py::data() y
            # editing_media_playback.py::_show_remote_image_preview) -- ningún otro campo
            # sirve de reemplazo, es la única llave que consultan.
            "thumb_url": hit.get("webformatURL") or hit.get("previewURL") or url,
        }

    def _map_video(self, hit: dict):
        videos = hit.get("videos", {})
        best = videos.get("large") or videos.get("medium") or videos.get("small") or videos.get("tiny")
        if not best or not best.get("url"):
            return None
        # Pixabay ya genera las 4 calidades por separado -- "ruta" (lo que se previsualiza,
        # vía get_video_derivative_url) usa la más liviana disponible para que la vista previa
        # arranque rápido; "download_url" (lo que de verdad se descarga/arrastra/usa en
        # subclips, vía download()) se queda siempre en "best". Nunca deben ser el mismo campo.
        preview = videos.get("tiny") or videos.get("small") or videos.get("medium") or best
        size_val = best.get("size", 0) or 0
        size_kb = size_val / 1024.0
        size_str = f"{size_kb / 1024.0:.1f} MB" if size_kb > 1024 else f"{size_kb:.1f} KB"
        dur = hit.get("duration", 0) or 0
        dur_str = f"{int(dur // 60):02d}:{int(dur % 60):02d}"
        return {
            "nombre": f"pixabay_{hit.get('id')}.mp4",
            "ruta": preview["url"],
            "download_url": best["url"],
            "tipo": "video",
            "file_type": "MP4",
            "tamaño": size_str,
            "resolución": f"{best.get('width', 0)}x{best.get('height', 0)}",
            "duración": dur_str,
            "duration": dur,
            "es_remoto": True,
            "username": hit.get("user", "-"),
            "license": "Pixabay License",
            "library": "Pixabay",
            "source_id": "pixabay",
            "id": str(hit.get("id", "")),
            "url": hit.get("pageURL", ""),
            # Poster/miniatura del video -- Pixabay incluye "thumbnail" en cada calidad de
            # "videos" (no es un campo separado como en Wikimedia). Ver nota de thumb_url en
            # _map_image sobre por qué es obligatorio, no cosmético.
            "thumb_url": best.get("thumbnail") or "",
        }

    def get_video_derivative_url(self, item_data: dict) -> str | None:
        """Hook que consulta editing_media_playback.py (VideoDerivativeResolveThread) para
        saber qué archivo descargar y cachear antes de poder reproducir la vista previa (el
        reproductor nunca streamea directo desde una URL de red, ver show_video_preview()).
        A diferencia de Wikimedia -- que necesita resolver una transcodificación liviana
        porque sus originales pueden ser enormes/con códecs raros -- acá "ruta" YA es un mp4
        de tamaño razonable listo para reproducir, así que no hay nada que resolver."""
        if item_data.get("tipo") != "video":
            return None
        return item_data.get("ruta") or None

    def download(self, item_data: dict, dest_dir: str, fallback_name: str, progress_callback=None) -> str:
        # A diferencia de la búsqueda, descargar el archivo no necesita la key -- las URLs de
        # Pixabay (previewURL/largeImageURL/videos.*.url) son links directos a su CDN.
        url = item_data.get("download_url") or item_data.get("ruta")
        if not url:
            raise ValueError(QCoreApplication.translate("PixabayProvider", "No se pudo determinar la URL del archivo de Pixabay."))

        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, fallback_name).replace("\\", "/")

        response = self.session.get(url, stream=True, timeout=30)
        response.raise_for_status()

        total_size = int(response.headers.get("content-length", 0))
        bytes_written = 0
        try:
            with open(dest_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
                        bytes_written += len(chunk)
                        if progress_callback and total_size > 0:
                            progress_callback(int((bytes_written / total_size) * 100))
        except Exception:
            if os.path.exists(dest_path):
                try:
                    os.remove(dest_path)
                except Exception:
                    pass
            raise

        logger.info(f"PixabayProvider: Descarga completada ({bytes_written} bytes): {dest_path}")
        return dest_path
