# src/core/tabs/editing_media/web_sources/wikimedia_provider.py
import os
import re
import requests
from core.logger.logger_manager import logger
from core.tabs.editing_media.web_sources.base import WebSourceProvider
from PySide6.QtCore import QCoreApplication

BASE_URL = "https://commons.wikimedia.org/w/api.php"
PAGE_SIZE = 30

# La API de Wikimedia pide un User-Agent descriptivo que identifique la app (política de
# etiqueta de la plataforma): https://developer.wikimedia.org/build-tools/apis/
# Es un valor de protocolo (header HTTP), no texto de UI - no debe pasar por el sistema
# de traducción (un idioma con caracteres fuera de latin-1 rompería la petición HTTP).
USER_AGENT = "DowP/2.0 (https://github.com/dowp-project; desktop media manager)"

_TAG_RE = re.compile(r"<[^<]+?>")


class WikimediaProvider(WebSourceProvider):
    """Cliente de búsqueda/descarga sobre Wikimedia Commons (action API, sin autenticación
    para lectura). A diferencia de Freesound, un solo ítem puede ser imagen, audio o video."""

    id = "wikimedia"
    display_name = "Wikimedia"
    requires_auth = False
    supported_media_types = {"imagen", "audio", "video"}

    # Wikimedia Commons por política solo aloja contenido libre (verificado contra la doc de
    # Commons:Licensing y contra 300 resultados reales de muestra): nunca aparece NC/ND, así
    # que a diferencia de Freesound no hace falta un bucket "restringida".
    license_filter_options = [
        ("cc0", "Dominio Público (CC0)"),
        ("attribution", "Requiere Atribución"),
    ]

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def normalize_license(self, raw_license: str) -> str:
        """Agrupa las variantes reales de licencia de Commons (CC0, Public domain, CC BY,
        CC BY-SA, GFDL, FAL, ...) en los 2 buckets de license_filter_options."""
        lic = (raw_license or "").lower()
        if "cc0" in lic or "zero" in lic or "public domain" in lic or lic.startswith("pd") or "pd-" in lic:
            return "cc0"
        return "attribution"

    def search(self, query: str, page: int = 1, **filters) -> dict:
        query = (query or "").strip()
        if not query:
            # Commons no acepta gsrsearch vacío; sin término mostramos un listado genérico
            # de archivos destacados en vez de dejar la lista vacía.
            query = "featured"

        # Filtrar por tipo de medio server-side (CirrusSearch de Commons soporta la keyword
        # filemime:, confirmado combinándola con un término real). Filtrar client-side una
        # sola página ya traída no sirve: en Commons casi cualquier búsqueda está dominada por
        # imágenes, así que video/audio se verían "siempre vacíos" en cuanto son minoría en
        # esa página en particular.
        media_type_map = {"imagen": "image", "video": "video", "audio": "audio"}
        filemime_kw = media_type_map.get(filters.get("media_type"))
        if filemime_kw:
            query = f"{query} filemime:{filemime_kw}"

        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": 6,  # namespace File:
            "gsrlimit": PAGE_SIZE,
            "gsroffset": max(0, (page - 1) * PAGE_SIZE),
            "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata|duration",
            "iiurlwidth": 800,
            "format": "json",
        }

        try:
            response = self.session.get(BASE_URL, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"WikimediaProvider: Error en la petición de búsqueda: {e}")
            raise IOError(QCoreApplication.translate("WikimediaProvider", "Error de red al conectar con Wikimedia: {0}").format(e))

        pages = (data.get("query") or {}).get("pages") or {}
        results = []
        for page_data in pages.values():
            info_list = page_data.get("imageinfo")
            if not info_list:
                continue
            item = self._map_item(page_data, info_list[0])
            if item:
                results.append(item)

        license_type = filters.get("license_type")
        if license_type and license_type != "Cualquiera":
            results = [it for it in results if self.normalize_license(it.get("license", "")) == license_type]

        return {"results": results}

    def _clean_meta(self, extmetadata: dict, key: str, default: str = "-") -> str:
        raw = (extmetadata.get(key) or {}).get("value", default)
        cleaned = _TAG_RE.sub("", str(raw)).strip()
        return cleaned or default

    def _map_item(self, page_data: dict, info: dict):
        url = info.get("url")
        if not url:
            return None

        mime = info.get("mime", "") or ""
        if mime.startswith("image/"):
            tipo = "imagen"
        elif mime.startswith("audio/"):
            tipo = "audio"
        elif mime.startswith("video/"):
            tipo = "video"
        else:
            # Formatos que Commons aloja pero el gestor no maneja (pdf, djvu, etc.)
            return None

        title = page_data.get("title", "")
        name = title.split(":", 1)[1] if ":" in title else title

        extmetadata = info.get("extmetadata") or {}
        license_short = self._clean_meta(extmetadata, "LicenseShortName", "Wikimedia Commons")
        artist = self._clean_meta(extmetadata, "Artist", "-")
        description = self._clean_meta(extmetadata, "ImageDescription", "-")

        size_val = info.get("size", 0) or 0
        size_kb = size_val / 1024.0
        size_str = f"{size_kb / 1024.0:.1f} MB" if size_kb > 1024 else f"{size_kb:.1f} KB"

        ext = name.rsplit(".", 1)[-1].upper() if "." in name else mime.split("/")[-1].upper()

        item = {
            "nombre": name,
            "ruta": url,
            "tipo": tipo,
            "file_type": ext,
            "tamaño": size_str,
            "es_remoto": True,
            "license": license_short,
            "library": "Wikimedia",
            "source_id": "wikimedia",
            "username": artist,
            "description": description,
            "url": f"https://commons.wikimedia.org/wiki/{title.replace(' ', '_')}",
            "wiki_title": title,
        }

        # thumburl: miniatura ya renderizada por Wikimedia (imagen y también video, un frame
        # estático), sin tocar el archivo original. El audio no trae una miniatura real (solo
        # un ícono genérico de tipo de archivo), así que no vale la pena cachearla.
        if tipo in ("imagen", "video"):
            thumb_url = info.get("thumburl")
            if thumb_url:
                item["thumb_url"] = thumb_url

        duration = info.get("duration")
        if duration:
            dur_m = int(duration // 60)
            dur_s = int(duration % 60)
            item["duración"] = f"{dur_m:02d}:{dur_s:02d}"
            item["duration"] = duration

        width = info.get("width")
        height = info.get("height")
        if width and height:
            item["resolución"] = f"{width}x{height}"

        return item

    def get_video_derivative_url(self, item_data: dict) -> str | None:
        """Resuelve la transcodificación más liviana disponible de un video de Commons (ej.
        240p vp9.webm generado por Wikimedia mismo vía TimedMediaHandler) para previsualizar
        sin bajar el original, que puede pesar decenas/cientos de MB. Devuelve None si falla
        o el video todavía no tiene derivatives generadas (uploads muy recientes)."""
        title = item_data.get("wiki_title")
        if not title:
            return None

        params = {
            "action": "query",
            "titles": title,
            "prop": "videoinfo",
            "viprop": "derivatives",
            "format": "json",
        }
        try:
            response = self.session.get(BASE_URL, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"WikimediaProvider: Error resolviendo derivative de video para '{title}': {e}")
            return None

        pages = (data.get("query") or {}).get("pages") or {}
        derivatives = []
        for page_data in pages.values():
            videoinfo_list = page_data.get("videoinfo") or []
            if videoinfo_list:
                derivatives = videoinfo_list[0].get("derivatives") or []
                break

        # La entrada sin 'transcodekey' es el archivo original (misma URL que 'ruta'); el
        # resto son transcodificaciones livianas generadas por Wikimedia. Preferimos la de
        # menor resolución (ej. 240p) para una previsualización rápida.
        candidates = [d for d in derivatives if d.get("transcodekey") and d.get("src")]
        if not candidates:
            return None
        candidates.sort(key=lambda d: d.get("width") or 0)
        return candidates[0]["src"]

    def download(self, item_data: dict, dest_dir: str, fallback_name: str, progress_callback=None) -> str:
        url = item_data.get("ruta")
        if not url:
            raise ValueError(QCoreApplication.translate("WikimediaProvider", "No se pudo determinar la URL del archivo de Wikimedia."))

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

        logger.info(f"WikimediaProvider: Descarga completada ({bytes_written} bytes): {dest_path}")
        return dest_path
