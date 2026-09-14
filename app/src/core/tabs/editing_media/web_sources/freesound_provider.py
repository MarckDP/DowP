# src/core/tabs/editing_media/web_sources/freesound_provider.py
from core.tabs.editing_media.web_sources.base import WebSourceProvider
from PySide6.QtCore import QCoreApplication


class FreesoundProvider(WebSourceProvider):
    """Adapta FreesoundClient + la autenticación OAuth2 del controller a la interfaz
    genérica WebSourceProvider. La construcción de ítems normalizados a partir del JSON
    de búsqueda de Freesound vivía antes en editing_media_freesound.py::_on_online_search_success."""

    id = "freesound"
    display_name = "Freesound"
    requires_auth = True
    supported_media_types = {"audio"}

    # Mismos value/label que ya usaba el combo de licencia hardcodeado: el filtrado real
    # sigue siendo 100% server-side (ver search()), esto solo describe las opciones para que
    # la UI pueda armar el combo genéricamente para cualquier provider.
    license_filter_options = [
        ("CC0", QCoreApplication.translate("FreesoundProvider", "CC0 (Sin Copyright)")),
        ("Attribution", QCoreApplication.translate("FreesoundProvider", "CC-BY (Atribución)")),
        ("Attribution NonCommercial", QCoreApplication.translate("FreesoundProvider", "CC-BY-NC (No Comercial)")),
    ]

    def __init__(self, client, controller):
        self.client = client
        self.controller = controller

    def is_authenticated(self) -> bool:
        return self.controller.is_freesound_authenticated

    def normalize_license(self, raw_license: str) -> str:
        """Agrupa la licencia ya normalizada (ver _map_item) en un bucket estable. A
        diferencia de Wikimedia, Freesound sí puede traer contenido No Comercial."""
        lic = (raw_license or "").lower()
        if "zero" in lic or "cc0" in lic or "publicdomain" in lic or "public domain" in lic:
            return "cc0"
        if "nc" in lic:
            return "attribution_nc"
        return "attribution"

    def search(self, query: str, page: int = 1, **filters) -> dict:
        token = self.controller.freesound_token
        raw = self.client.search(
            query,
            token,
            duration_min=filters.get("duration_min"),
            duration_max=filters.get("duration_max"),
            license_type=filters.get("license_type"),
            sort_order=filters.get("sort_order"),
            page=page
        )
        results = []
        for r in raw.get("results", []):
            item = self._map_item(r)
            if item:
                results.append(item)
        return {"results": results}

    def _map_item(self, r: dict):
        previews = r.get("previews", {})
        preview_lq_url = previews.get("preview-lq-mp3", previews.get("preview-hq-mp3", previews.get("preview-lq-ogg", "")))
        download_hq_url = previews.get("preview-hq-mp3", previews.get("preview-hq-ogg", preview_lq_url))
        if not preview_lq_url:
            return None

        dur = r.get("duration", 0)
        dur_m = int(dur // 60)
        dur_s = int(dur % 60)
        dur_str = f"{dur_m:02d}:{dur_s:02d}"

        size_val = r.get("filesize", 0)
        size_kb = size_val / 1024.0
        if size_kb > 1024:
            size_str = f"{size_kb / 1024.0:.1f} MB"
        else:
            size_str = f"{size_kb:.1f} KB"

        sound_name = r.get("name", QCoreApplication.translate("FreesoundProvider", "Sonido sin nombre")).strip()
        sound_type = r.get("type", "").strip().lower()
        if sound_type and not any(sound_name.lower().endswith(f".{ext}") for ext in ["wav", "mp3", "flac", "ogg", "aiff", "m4a", "aac"]):
            sound_name = f"{sound_name}.{sound_type}"

        raw_license = str(r.get("license", "")).lower()
        if "zero" in raw_license or "cc0" in raw_license or "publicdomain" in raw_license:
            license_clean = "CC0"
        elif "by-nc" in raw_license or "noncommercial" in raw_license:
            license_clean = "CC BY-NC"
        elif "by" in raw_license or "attribution" in raw_license:
            license_clean = "CC BY"
        elif raw_license:
            license_clean = r.get("license", "Freesound")
        else:
            license_clean = "CC0"

        sr_val = r.get("samplerate")
        if sr_val:
            try:
                sr_num = int(sr_val)
                sample_rate_str = f"{sr_num / 1000.0:.1f} kHz" if sr_num >= 1000 else f"{sr_num} Hz"
            except Exception:
                sample_rate_str = str(sr_val)
        else:
            sample_rate_str = "-"

        return {
            "nombre": sound_name,
            "ruta": preview_lq_url,
            "download_url": download_hq_url,
            "tipo": "audio",
            "file_type": sound_type.upper() if sound_type else "AUDIO",
            "tamaño": size_str,
            "duración": dur_str,
            "duration": dur,
            "es_remoto": True,
            "username": r.get("username", "-"),
            "license": license_clean,
            "library": "Freesound",
            "source_id": "freesound",
            "sample_rate": sample_rate_str,
            "avg_rating": f"{r.get('avg_rating', 0):.1f}",
            "num_downloads": str(r.get("num_downloads", 0)),
            "description": r.get("description", "-"),
            "images": r.get("images", {}),
            "id": str(r.get("id", "")),
            "url": r.get("url", "")
        }

    def download(self, item_data: dict, dest_dir: str, fallback_name: str, progress_callback=None) -> str:
        token = self.controller.freesound_token
        if not token:
            raise PermissionError(QCoreApplication.translate("FreesoundProvider", "Debes iniciar sesión con Freesound para descargar el archivo original en alta calidad."))
        sound_id = item_data.get("id")
        if not sound_id:
            raise ValueError(QCoreApplication.translate("FreesoundProvider", "No se pudo determinar el ID del sonido de Freesound."))
        return self.client.download_original(sound_id, dest_dir, fallback_name, token, progress_callback=progress_callback)
