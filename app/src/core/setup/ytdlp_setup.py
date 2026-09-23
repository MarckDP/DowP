# src/core/setup/ytdlp_setup.py
import os
import shutil
import sys
import requests
from core.logger.logger_manager import logger
from core.utils.http_download import download_file
from core.utils.config_manager import get_config, save_config
from core.utils.paths import get_bin_root_dir

YTDLP_STABLE_URL = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
YTDLP_NIGHTLY_URL = "https://api.github.com/repos/yt-dlp/yt-dlp-nightly-builds/releases/latest"
FILENAME = "yt-dlp.zip"

def get_ytdlp_dir():
    """Returns the directory path for yt-dlp."""
    ytdlp_dir = os.path.join(get_bin_root_dir(), "bin", "dependences", "ytdlp")
    if not os.path.exists(ytdlp_dir):
        logger.info(f"Creating directory: {ytdlp_dir}")
        os.makedirs(ytdlp_dir)
    return ytdlp_dir

def get_ytdlp_path():
    """Returns the full path of the yt-dlp.zip file."""
    return os.path.join(get_ytdlp_dir(), FILENAME)

def get_release_url(channel=None):
    """Devuelve la URL de la API de GitHub según el canal especificado ('stable' o 'nightly')."""
    if not channel:
        config = get_config()
        channel = config.get("ytdlp_channel", "stable")
    
    if str(channel).lower() == "nightly":
        return YTDLP_NIGHTLY_URL
    return YTDLP_STABLE_URL

_ytdlp_checked = False

def check_ytdlp():
    """Verifies if yt-dlp.zip exists."""
    global _ytdlp_checked
    exists = os.path.exists(get_ytdlp_path())
    if not _ytdlp_checked:
        logger.debug(f"Checking yt-dlp.zip existence: {exists}")
        _ytdlp_checked = True
    return exists
def purge_ytdlp_cache():
    """
    Invalida el caché de zipimport y limpia sys.modules para yt_dlp
    garantizando que la nueva versión se cargue en caliente sin reiniciar.
    """
    try:
        import zipimport
        ytdlp_path = get_ytdlp_path()
        if hasattr(zipimport, '_zip_directory_cache'):
            zipimport._zip_directory_cache.pop(ytdlp_path, None)
            zipimport._zip_directory_cache.pop(os.path.normpath(ytdlp_path), None)
            zipimport._zip_directory_cache.pop(os.path.abspath(ytdlp_path), None)
    except Exception as e:
        logger.debug(f"No se pudo limpiar zipimport cache: {e}")

    try:
        import importlib
        importlib.invalidate_caches()
    except Exception:
        pass

    for mod in list(sys.modules.keys()):
        if mod == 'yt_dlp' or mod.startswith('yt_dlp.'):
            del sys.modules[mod]

def download_ytdlp(channel=None, progress_callback=None):
    """Downloads the version of yt-dlp according to the specified channel and cleans shebang."""
    try:
        config = get_config()
        if channel is None:
            channel = config.get("ytdlp_channel", "stable")

        release_url = get_release_url(channel)
        logger.info(f"Fetching {channel.upper()} release info from {release_url}")
        
        headers = {"User-Agent": "DowP2"}
        response = requests.get(release_url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        download_url = None
        for asset in data.get("assets", []):
            if asset["name"] == "yt-dlp": # ZipApp asset (no extension)
                download_url = asset["browser_download_url"]
                break
        
        if not download_url:
            # Fallback to .pyz if 'yt-dlp' asset is missing
            for asset in data.get("assets", []):
                if asset["name"] == "yt-dlp.pyz":
                    download_url = asset["browser_download_url"]
                    break

        if not download_url:
            logger.error(f"yt-dlp asset not found in {channel} release")
            return False, f"yt-dlp ({channel}) asset not found."

        target_path = get_ytdlp_path()
        logger.info(f"Downloading yt-dlp ({channel}) from {download_url}")
        # A un .part y luego se reemplaza: si la descarga falla a medias, el yt-dlp que
        # ya estaba instalado sigue intacto en vez de quedar truncado.
        part_path = target_path + ".part"
        download_file(download_url, part_path, progress_callback=progress_callback)
        try:
            os.replace(part_path, target_path)
        except PermissionError:
            # Windows no deja reemplazar un archivo que otro proceso tiene abierto sin
            # permiso de borrado, pero sí sobrescribirlo (lo que hacía el código viejo).
            with open(part_path, "rb") as src, open(target_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
            os.remove(part_path)

        # Limpieza de shebang (Lógica DowP Viejo)
        try:
            with open(target_path, "rb") as f:
                content = f.read()
            start_idx = content.find(b"PK\x03\x04")
            if start_idx > 0:
                with open(target_path, "wb") as f:
                    f.write(content[start_idx:])
                logger.info("Shebang de yt-dlp limpiado (convertido a ZIP puro).")
        except Exception as e:
            logger.error(f"No se pudo limpiar el shebang: {e}")
        
        # Purgar caché en memoria para recarga en caliente
        purge_ytdlp_cache()

        # Guardar canal en config
        config["ytdlp_channel"] = channel
        save_config(config)

        # Actualizar versión cacheada
        get_local_version(force_check=True)

        logger.info(f"yt-dlp.zip ({channel}) listo en {target_path}")
        return True, f"yt-dlp ({channel}) descargado y procesado correctamente."
    except Exception as e:
        logger.error(f"Error downloading yt-dlp ({channel}): {e}")
        return False, str(e)

def get_local_version(force_check=False):
    """
    Lee la versión de yt-dlp importándolo en el mismo proceso (via sys.path
    sobre el .zip), cacheándola en config.json para evitar reimportar.
    """
    if not check_ytdlp():
        return None

    config = get_config()
    versions = config.get("dependency_versions", {})
    if not force_check and "ytdlp" in versions:
        return versions["ytdlp"]

    try:
        ytdlp_path = get_ytdlp_path()
        purge_ytdlp_cache()

        if ytdlp_path not in sys.path:
            sys.path.insert(0, ytdlp_path)

        import yt_dlp
        version = yt_dlp.version.__version__

        # Save to config
        versions["ytdlp"] = version
        config["dependency_versions"] = versions
        save_config(config)

        return version
    except Exception as e:
        logger.error(f"Error getting local yt-dlp version: {e}")
        return None

def get_latest_remote_version(channel=None):
    """Fetches the latest version string from GitHub API for specified channel."""
    try:
        release_url = get_release_url(channel)
        headers = {"User-Agent": "DowP2"}
        response = requests.get(release_url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("tag_name", "").lstrip("v")
    except Exception as e:
        logger.error(f"Error getting remote yt-dlp version ({channel}): {e}")
        return None

if __name__ == "__main__":
    if not check_ytdlp():
        download_ytdlp()


