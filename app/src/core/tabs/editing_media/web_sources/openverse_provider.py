# src/core/tabs/editing_media/web_sources/openverse_provider.py
import os
import requests
from urllib.parse import urlparse
from core.logger.logger_manager import logger
from core.tabs.editing_media.web_sources.base import WebSourceProvider
from PySide6.QtCore import QCoreApplication

BASE_URL = "https://api.openverse.org/v1"
PAGE_SIZE = 20

# Como Wikimedia, Openverse es de lectura libre -- sin API key ni login por usuario (ver
# conversación: se descartó Pexels/Pixabay para esto porque su modelo es una única API key
# de APLICACIÓN, que en un .exe distribuido quedaría compartida entre TODOS los usuarios de
# DowP contra el mismo límite, y extraíble del binario -- Openverse no tiene ese problema
# porque no pide ninguna credencial en absoluto). Pide igual un User-Agent descriptivo por
# buena práctica de API pública (mismo criterio que WikimediaProvider).
USER_AGENT = "DowP/2.0 (https://github.com/dowp-project; desktop media manager)"

# Openverse separa imagen y audio en dos endpoints distintos (a diferencia de la action API
# de Wikimedia, que devuelve cualquier tipo de archivo en una sola búsqueda) -- no hay video.
_ENDPOINT_BY_MEDIA_TYPE = {"imagen": "images", "audio": "audio"}

# Códigos de licencia crudos de Openverse (siempre en minúscula, ver
# https://docs.openverse.org) agrupados en los 3 buckets de license_filter_options -- mismo
# criterio que Freesound (a diferencia de Wikimedia, Openverse SÍ agrega contenido No
# Comercial/Sin Derivados de fuentes como Flickr). La clave "attribution_nc" (no
# "restricted"/"nd") es a propósito: editing_media_playback.py::_on_media_clicked arma el
# panel de licencia mirando exactamente esos 3 buckets ("cc0"/"attribution"/
# "attribution_nc") -- una clave distinta caería en su rama "Licencia Desconocida" en vez
# de mostrar la advertencia de No Comercial/Sin Derivados que corresponde.
_LICENSE_BUCKETS = {
    "cc0": ("cc0", "pdm"),
    "attribution": ("by", "by-sa"),
    "attribution_nc": ("by-nc", "by-nd", "by-nc-sa", "by-nc-nd"),
}


class OpenverseProvider(WebSourceProvider):
    """Cliente de búsqueda/descarga sobre Openverse (agregador de imagen/audio con licencia
    Creative Commons o dominio público de cientos de fuentes -- Flickr, Jamendo, etc.).
    Sin autenticación: a diferencia de Freesound, ningún usuario de DowP necesita iniciar
    sesión ni configurar nada para buscar o descargar (ver conversación)."""

    id = "openverse"
    display_name = "Openverse"
    requires_auth = False
    supported_media_types = {"imagen", "audio"}

    license_filter_options = [
        ("cc0", QCoreApplication.translate("OpenverseProvider", "Dominio Público (CC0)")),
        ("attribution", QCoreApplication.translate("OpenverseProvider", "Requiere Atribución")),
        ("attribution_nc", QCoreApplication.translate("OpenverseProvider", "No Comercial / Sin Derivados")),
    ]

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def normalize_license(self, raw_license: str) -> str:
        """raw_license acá es el string YA FORMATEADO por _format_license (ej. "CC BY-ND
        4.0"), no el código crudo -- ver editing_media_playback.py::_on_media_clicked,
        que llama esto con item_data["license"] tal cual. "nc" primero a propósito: un
        "by-nc-nd" es simultáneamente No Comercial Y Sin Derivados, y el bucket NC (más
        restrictivo/cauteloso en el panel de licencia) es la clasificación más segura
        para ese caso -- solo un "by-nd" puro (sin "nc") cae en el bucket ND propio."""
        lic = (raw_license or "").lower()
        if "cc0" in lic or "public domain" in lic:
            return "cc0"
        if "nc" in lic:
            return "attribution_nc"
        if "nd" in lic:
            return "attribution_nd"
        return "attribution"

    def search(self, query: str, page: int = 1, **filters) -> dict:
        media_type = filters.get("media_type")
        # "Video" es uno de los 4 filtros genéricos de la UI (ver editing_media_tree.py) pero
        # Openverse no aloja video -- resultado vacío en vez de pegarle a un endpoint que no
        # existe. "Todos" (media_type None, origen soporta >1 tipo) consulta AMBOS endpoints
        # y mezcla, igual que una búsqueda combinada real.
        if media_type == "video":
            return {"results": []}

        endpoints = [_ENDPOINT_BY_MEDIA_TYPE[media_type]] if media_type in _ENDPOINT_BY_MEDIA_TYPE else list(_ENDPOINT_BY_MEDIA_TYPE.values())

        params = {"q": (query or "").strip(), "page": max(1, page), "page_size": PAGE_SIZE}
        license_bucket = filters.get("license_type")
        raw_licenses = _LICENSE_BUCKETS.get(license_bucket)
        if raw_licenses:
            params["license"] = ",".join(raw_licenses)

        results = []
        for endpoint in endpoints:
            try:
                response = self.session.get(f"{BASE_URL}/{endpoint}/", params=params, timeout=15)
                response.raise_for_status()
                data = response.json()
            except requests.exceptions.RequestException as e:
                logger.error(f"OpenverseProvider: Error en la petición de búsqueda ({endpoint}): {e}")
                # Con dos endpoints combinados ("Todos"), un solo endpoint caído no debe tirar
                # abajo la búsqueda completa -- solo si AMBOS fallan no hay nada que mostrar.
                if len(endpoints) == 1:
                    raise IOError(QCoreApplication.translate("OpenverseProvider", "Error de red al conectar con Openverse: {0}").format(e))
                continue

            media_kind = "imagen" if endpoint == "images" else "audio"
            for raw_item in data.get("results", []):
                item = self._map_item(raw_item, media_kind)
                if item:
                    results.append(item)

        return {"results": results}

    def _format_license(self, code: str, version: str) -> str:
        """Nomenclatura de licencia tal cual (ej. "CC BY-ND 4.0"), NUNCA una frase
        traducida -- igual que license_short en WikimediaProvider/license_clean en
        FreesoundProvider. item_data["license"] es lo que normalize_license() recibe
        para reconstruir el bucket (ver editing_media_playback.py); una frase de UI
        traducida perdería la palabra clave y rompería esa detección en otro idioma."""
        code = (code or "").lower()
        version = (version or "").strip()
        if code == "pdm":
            return "Public Domain Mark"
        if code == "cc0":
            return f"CC0 {version}".strip()
        return f"CC {code.upper()} {version}".strip()

    def _guess_ext(self, filetype: str, url: str) -> str:
        if filetype:
            return filetype.upper()
        path = urlparse(url or "").path
        return path.rsplit(".", 1)[-1].upper() if "." in path else "-"

    # Formatos sin pérdida -- si un alt_file trae uno de estos, es una señal fuerte de que es
    # el master real aunque no reporte filesize (ver _map_item).
    _LOSSLESS_FILETYPES = {"wav", "flac", "aiff", "aif"}

    def _pick_best_audio_file(self, r: dict) -> dict:
        """Elige qué archivo es "el original" a descargar. Confirmado contra la API real: para
        audio agregado desde Freesound, el "url" principal de Openverse es en realidad la
        PREVIEW comprimida de Freesound (mp3 ~128kbps), no el original -- el archivo real
        (ej. wav sin comprimir) viene aparte en "alt_files", que hasta ahora no se leía en
        absoluto (ni para elegir qué descargar ni para el nombre/extensión mostrados). Para
        fuentes sin alt_files (ej. Jamendo) esto no cambia nada: "url" sigue siendo la única
        opción. Se compara por filesize (con desempate a favor de formatos sin pérdida) para
        no arriesgarse a "degradar" por error si algún alt_file resultara ser peor."""
        candidates = [{"url": r.get("url"), "filetype": r.get("filetype"), "filesize": r.get("filesize") or 0}]
        for alt in (r.get("alt_files") or []):
            if alt.get("url"):
                candidates.append({"url": alt["url"], "filetype": alt.get("filetype"), "filesize": alt.get("filesize") or 0})
        return max(candidates, key=lambda c: (c["filesize"], (c.get("filetype") or "").lower() in self._LOSSLESS_FILETYPES))

    def _map_item(self, r: dict, media_kind: str):
        url = r.get("url")
        if not url:
            return None

        title = (r.get("title") or "").strip() or QCoreApplication.translate("OpenverseProvider", "Sin título")

        # "ruta" (lo que se previsualiza/reproduce/usa para el waveform) se queda SIEMPRE en
        # la preview liviana ("url"). "download_url" (lo que realmente se descarga vía
        # download()) apunta al mejor candidato real -- solo difiere de "ruta" para audio con
        # alt_files (ver _pick_best_audio_file). El nombre/extensión/tamaño mostrados
        # describen ese archivo real, no la preview, para no guardar bytes de un formato con
        # la extensión de otro.
        if media_kind == "audio":
            best = self._pick_best_audio_file(r)
            download_url = best["url"]
            ext = self._guess_ext(best["filetype"], download_url)
            display_filesize = best["filesize"]
        else:
            download_url = url
            ext = self._guess_ext(r.get("filetype"), url)
            display_filesize = r.get("filesize")

        name = title if ext != "-" and title.lower().endswith(f".{ext.lower()}") else f"{title}.{ext}" if ext != "-" else title

        if display_filesize:
            size_kb = display_filesize / 1024.0
            size_str = f"{size_kb / 1024.0:.1f} MB" if size_kb > 1024 else f"{size_kb:.1f} KB"
        else:
            size_str = "-"

        license_str = self._format_license(r.get("license", ""), r.get("license_version", ""))

        item = {
            "nombre": name,
            "ruta": url,
            "download_url": download_url,
            "tipo": media_kind,
            "file_type": ext,
            "tamaño": size_str,
            "es_remoto": True,
            "license": license_str,
            "library": "Openverse",
            "source_id": "openverse",
            "username": r.get("creator") or "-",
            "description": title,
            "url": r.get("foreign_landing_url", ""),
        }

        if media_kind == "imagen":
            thumb_url = r.get("thumbnail")
            if thumb_url:
                item["thumb_url"] = thumb_url
            width, height = r.get("width"), r.get("height")
            if width and height:
                item["resolución"] = f"{width}x{height}"
        else:
            # duration de Openverse viene en milisegundos.
            duration_ms = r.get("duration")
            if duration_ms:
                duration_sec = duration_ms / 1000.0
                dur_m = int(duration_sec // 60)
                dur_s = int(duration_sec % 60)
                item["duración"] = f"{dur_m:02d}:{dur_s:02d}"
                item["duration"] = duration_sec

            # A diferencia de Freesound (que da una imagen ya renderizada, "images.waveform_m"),
            # Openverse ya trae los picos de amplitud como JSON puro en este endpoint --
            # {"len": N, "points": [0.0-1.0, ...]} -- confirmado contra la API real. No hace
            # falta descomponer ninguna imagen, ver RemoteWaveformPeaksCacheManager.
            waveform_url = r.get("waveform")
            if waveform_url:
                item["waveform_url"] = waveform_url

        return item

    def download(self, item_data: dict, dest_dir: str, fallback_name: str, progress_callback=None) -> str:
        # "download_url" es el original real cuando difiere de "ruta" (ver _pick_best_audio_file);
        # para ítems sin alt_files (imágenes, o audio de fuentes como Jamendo) son la misma URL.
        url = item_data.get("download_url") or item_data.get("ruta")
        if not url:
            raise ValueError(QCoreApplication.translate("OpenverseProvider", "No se pudo determinar la URL del archivo de Openverse."))

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

        logger.info(f"OpenverseProvider: Descarga completada ({bytes_written} bytes): {dest_path}")
        return dest_path
