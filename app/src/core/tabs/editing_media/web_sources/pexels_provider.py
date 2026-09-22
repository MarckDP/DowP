# src/core/tabs/editing_media/web_sources/pexels_provider.py
import os
import requests
from core.logger.logger_manager import logger
from core.tabs.editing_media.web_sources.base import WebSourceProvider
from core.utils.config_manager import get_config, save_config
from PySide6.QtCore import QCoreApplication

PHOTO_URL = "https://api.pexels.com/v1/search"
VIDEO_URL = "https://api.pexels.com/videos/search"
# El límite de las APIs se cuenta por petición, no por resultado: pedir 60 cuesta lo mismo
# que pedir 20 (máximo por página: Pexels 80, Pixabay 200). En "Todos" se reparte 30/30.
PAGE_SIZE = 60


class PexelsProvider(WebSourceProvider):
    """Cliente de búsqueda/descarga sobre la API de Pexels (fotos y video). Igual que
    Pixabay, usa una API key simple (sin OAuth) que el usuario genera en su cuenta de
    Pexels y pega en DowP -- ver api_key_url/api_key_instructions. Todo el catálogo
    comparte una única licencia (la "Licencia de Pexels"), así que no hay filtro de
    licencia -- ver license_filter_options vacío."""

    id = "pexels"
    display_name = "Pexels"
    requires_auth = True
    supported_media_types = {"imagen", "video"}
    license_filter_options: list = []
    # Ruta directa al formulario de generación de key -- confirmada a mano (ver
    # conversación): el flujo público (pexels.com/api/ -> Get Started -> elegir "descargar"
    # -> login) NO termina en el formulario, deja al usuario en la página de su cuenta y hay
    # que buscar "Images and Video API" en el menú "...". Esta URL salta directo al formulario
    # una vez logueado.
    api_key_url = "https://www.pexels.com/api/key/"
    api_key_instructions = QCoreApplication.translate(
        "PexelsProvider",
        "1. Inicia sesión o crea una cuenta gratuita en Pexels (va a pedir elegir "
        "\"Descargar\" en vez de \"Contribuir\").\n"
        "2. Completa el formulario corto que aparece (cualquier descripción real de "
        "mínimo 50 caracteres es válida).\n"
        "3. Al enviarlo, va a mostrar la API key -- cópiala y pégala aquí abajo."
    )

    def __init__(self):
        self.session = requests.Session()

    def get_api_key(self) -> str:
        return get_config().get("pexels_api_key", "") or ""

    def set_api_key(self, key: str):
        config = get_config()
        config["pexels_api_key"] = (key or "").strip()
        save_config(config)

    def is_authenticated(self) -> bool:
        return bool(self.get_api_key())

    def validate_api_key(self, key: str):
        key = (key or "").strip()
        if not key:
            return False, QCoreApplication.translate("PexelsProvider", "La API key no puede estar vacía.")
        try:
            resp = self.session.get(PHOTO_URL, headers={"Authorization": key}, params={"query": "test", "per_page": 1}, timeout=10)
        except requests.exceptions.RequestException as e:
            return False, QCoreApplication.translate("PexelsProvider", "Error de red al validar: {0}").format(e)
        if resp.status_code == 200:
            return True, ""
        if resp.status_code in (401, 403):
            return False, QCoreApplication.translate("PexelsProvider", "La API key no es válida.")
        return False, QCoreApplication.translate("PexelsProvider", "Pexels respondió con un error ({0}).").format(resp.status_code)

    def normalize_license(self, raw_license: str) -> str:
        return "pexels_license"

    def search(self, query: str, page: int = 1, **filters) -> dict:
        key = self.get_api_key()
        if not key:
            raise ValueError(QCoreApplication.translate("PexelsProvider", "API key de Pexels requerida."))

        media_type = filters.get("media_type")
        # Pexels exige 'query' no vacío (a diferencia de Pixabay, que sin q devuelve
        # populares) -- sin término de búsqueda mostramos algo genérico en vez de fallar.
        query = (query or "").strip() or "nature"

        results = []
        if media_type in (None, "imagen"):
            results.extend(self._search_photos(key, query, page, full=media_type == "imagen"))
        if media_type in (None, "video"):
            results.extend(self._search_videos(key, query, page, full=media_type == "video"))
        return {"results": results}

    def _search_photos(self, key, query, page, full):
        per_page = PAGE_SIZE if full else PAGE_SIZE // 2
        params = {"query": query, "per_page": max(per_page, 1), "page": page}
        try:
            resp = self.session.get(PHOTO_URL, headers={"Authorization": key}, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"PexelsProvider: Error buscando fotos: {e}")
            raise IOError(QCoreApplication.translate("PexelsProvider", "Error de red al conectar con Pexels: {0}").format(e))
        return [item for item in (self._map_photo(p) for p in data.get("photos", [])) if item]

    def _search_videos(self, key, query, page, full):
        per_page = PAGE_SIZE if full else PAGE_SIZE // 2
        params = {"query": query, "per_page": max(per_page, 1), "page": page}
        try:
            resp = self.session.get(VIDEO_URL, headers={"Authorization": key}, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"PexelsProvider: Error buscando videos: {e}")
            raise IOError(QCoreApplication.translate("PexelsProvider", "Error de red al conectar con Pexels: {0}").format(e))
        return [item for item in (self._map_video(v) for v in data.get("videos", [])) if item]

    def _map_photo(self, p: dict):
        src = p.get("src", {})
        url = src.get("original") or src.get("large2x") or src.get("large")
        if not url:
            return None
        return {
            "nombre": f"pexels_{p.get('id')}.jpg",
            "ruta": src.get("medium") or url,
            "download_url": url,
            "tipo": "imagen",
            "file_type": "JPG",
            "tamaño": "-",
            "resolución": f"{p.get('width', 0)}x{p.get('height', 0)}",
            "es_remoto": True,
            "username": p.get("photographer", "-"),
            "license": "Pexels License",
            "library": "Pexels",
            "source_id": "pexels",
            "id": str(p.get("id", "")),
            "url": p.get("url", ""),
            # Obligatorio para que la grilla y la vista previa muestren algo -- ver nota en
            # pixabay_provider.py::_map_image sobre por qué (media_model.py solo consulta esta
            # llave, sin fallback a "ruta").
            "thumb_url": src.get("medium") or src.get("small") or url,
        }

    def _map_video(self, v: dict):
        files = [f for f in v.get("video_files", []) if f.get("link")]
        if not files:
            return None
        best = max(files, key=lambda f: (f.get("width") or 0) * (f.get("height") or 0))
        # Igual que Pixabay: Pexels ya trae varias calidades sueltas en video_files -- "ruta"
        # (previsualización, vía get_video_derivative_url) usa la de menor resolución
        # disponible; "download_url" (descarga real/arrastre/subclips, vía download()) se
        # queda siempre en "best". Nunca deben ser el mismo campo.
        preview = min(files, key=lambda f: (f.get("width") or 0) * (f.get("height") or 0))
        url = best["link"]
        dur = v.get("duration", 0) or 0
        dur_str = f"{int(dur // 60):02d}:{int(dur % 60):02d}"
        return {
            "nombre": f"pexels_{v.get('id')}.mp4",
            "ruta": preview["link"],
            "download_url": url,
            "tipo": "video",
            "file_type": "MP4",
            "tamaño": "-",
            "resolución": f"{best.get('width', 0)}x{best.get('height', 0)}",
            "duración": dur_str,
            "duration": dur,
            "es_remoto": True,
            "username": (v.get("user") or {}).get("name", "-"),
            "license": "Pexels License",
            "library": "Pexels",
            "source_id": "pexels",
            "id": str(v.get("id", "")),
            "url": v.get("url", ""),
            # Pexels sí trae un poster de video como campo suelto (a diferencia de Pixabay,
            # que lo anida en cada calidad de "videos").
            "thumb_url": v.get("image") or "",
        }

    def get_video_derivative_url(self, item_data: dict) -> str | None:
        """Ver nota en pixabay_provider.py::get_video_derivative_url -- mismo motivo, "ruta"
        ya es un mp4 de tamaño razonable, no hace falta resolver una transcodificación."""
        if item_data.get("tipo") != "video":
            return None
        return item_data.get("ruta") or None

    def download(self, item_data: dict, dest_dir: str, fallback_name: str, progress_callback=None) -> str:
        # Igual que Pixabay: las URLs de descarga (src.original/video_files[].link) son links
        # directos al CDN de Pexels, no necesitan la key.
        url = item_data.get("download_url") or item_data.get("ruta")
        if not url:
            raise ValueError(QCoreApplication.translate("PexelsProvider", "No se pudo determinar la URL del archivo de Pexels."))

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

        logger.info(f"PexelsProvider: Descarga completada ({bytes_written} bytes): {dest_path}")
        return dest_path
