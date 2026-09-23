# src/core/setup/potprovider_setup.py
"""
Setup del PO Token Provider (bgutil-ytdlp-pot-provider-rs) para DowP.
Sigue el mismo patrón que deno_setup.py:
  - Binario standalone por plataforma descargado de GitHub Releases
  - Plugin Python (ZIP cross-platform) descomprimido en ytdlp/plugins/
"""
import os
import stat
import platform
import zipfile
import subprocess
import requests
from core.logger.logger_manager import logger
from core.utils.http_download import download_file
from core.utils.config_manager import get_config, save_config
from core.utils.paths import get_bin_root_dir
from PySide6.QtCore import QCoreApplication

POTPROVIDER_API_URL = "https://api.github.com/repos/jim60105/bgutil-ytdlp-pot-provider-rs/releases/latest"
PLUGIN_ZIP_ASSET = "bgutil-ytdlp-pot-provider-rs.zip"
PLUGIN_SENTINEL = os.path.join("yt_dlp_plugins", "extractor", "getpot_bgutil.py")

# Mapa de (sistema, arch) → nombre del asset en GitHub Releases
_ASSET_MAP = {
    ("windows", "x86_64"):  "bgutil-pot-windows-x86_64.exe",
    ("linux",   "x86_64"):  "bgutil-pot-linux-x86_64",
    ("linux",   "aarch64"): "bgutil-pot-linux-aarch64",
    ("darwin",  "x86_64"):  "bgutil-pot-macos-x86_64",
    ("darwin",  "aarch64"): "bgutil-pot-macos-aarch64",
}

# Nombre local del binario (sin variante de plataforma)
_BINARY_NAME = {
    "windows": "bgutil-pot.exe",
    "linux":   "bgutil-pot",
    "darwin":  "bgutil-pot",
}


def get_platform_info():
    """
    Determina el asset correcto del release y el nombre local del binario
    según el OS y la arquitectura del sistema.
    Devuelve (asset_name, binary_name).
    """
    system = platform.system().lower()
    machine = platform.machine().lower()

    if machine in ("amd64", "x86_64"):
        arch = "x86_64"
    elif machine in ("arm64", "aarch64"):
        arch = "aarch64"
    else:
        arch = "x86_64"  # Fallback

    key = (system, arch)
    asset_name = _ASSET_MAP.get(key)
    if asset_name is None:
        # Fallback a linux x86_64 si la plataforma no se reconoce
        logger.warning(f"PotProvider: plataforma no reconocida ({system}, {arch}), usando fallback linux-x86_64")
        asset_name = "bgutil-pot-linux-x86_64"
        system = "linux"

    binary_name = _BINARY_NAME.get(system, "bgutil-pot")
    return asset_name, binary_name


def get_potprovider_dir():
    """Devuelve y crea si hace falta el directorio del binario motor."""
    pot_dir = os.path.join(get_bin_root_dir(), "bin", "dependences", "potprovider")
    os.makedirs(pot_dir, exist_ok=True)
    return pot_dir


def get_plugin_dir():
    """
    Devuelve el directorio padre que contiene 'yt_dlp_plugins/'.
    Este path es el que se agrega a sys.path para que yt-dlp cargue el plugin.
    """
    plugin_dir = os.path.join(get_bin_root_dir(), "bin", "dependences", "ytdlp", "plugins")
    os.makedirs(plugin_dir, exist_ok=True)
    return plugin_dir


def get_binary_path():
    """Devuelve la ruta completa al binario bgutil-pot."""
    _, binary_name = get_platform_info()
    return os.path.join(get_potprovider_dir(), binary_name)


_potprovider_checked = False


def check_potprovider():
    """Verifica si el binario motor bgutil-pot existe."""
    global _potprovider_checked
    exists = os.path.exists(get_binary_path())
    if not _potprovider_checked:
        logger.debug(f"PotProvider: verificando binario -> {exists}")
        _potprovider_checked = True
    return exists


def check_plugin():
    """
    Verifica si el plugin Python (yt_dlp_plugins/extractor/getpot_bgutil.py)
    existe en la carpeta de plugins de yt-dlp.
    """
    sentinel = os.path.join(get_plugin_dir(), PLUGIN_SENTINEL)
    exists = os.path.exists(sentinel)
    logger.debug(f"PotProvider: verificando plugin -> {exists} ({sentinel})")
    return exists


def check_all():
    """Devuelve True solo si tanto el binario como el plugin están presentes."""
    return check_potprovider() and check_plugin()


def download_potprovider(progress_callback=None):
    """
    Descarga el binario motor y el plugin Python del PO Token Provider.
    Sigue el mismo patrón que download_deno():
      1. Consulta GitHub API para la última release.
      2. Descarga el binario correcto para esta plataforma.
      3. Descarga el ZIP del plugin y lo descomprime en ytdlp/plugins/.
    """
    try:
        asset_name, binary_name = get_platform_info()
        logger.info(f"PotProvider: consultando release desde {POTPROVIDER_API_URL} (asset: {asset_name})")

        response = requests.get(POTPROVIDER_API_URL, timeout=15)
        response.raise_for_status()
        data = response.json()

        # ── Localizar URLs de descarga ─────────────────────────────────────
        binary_url = None
        plugin_url = None

        for asset in data.get("assets", []):
            if asset["name"] == asset_name:
                binary_url = asset["browser_download_url"]
            elif asset["name"] == PLUGIN_ZIP_ASSET:
                plugin_url = asset["browser_download_url"]

        if not binary_url:
            logger.error(f"PotProvider: asset '{asset_name}' no encontrado en el release")
            return False, QCoreApplication.translate("potprovider_setup", "Asset del binario '{0}' no encontrado.").format(asset_name)

        if not plugin_url:
            logger.error(f"PotProvider: asset '{PLUGIN_ZIP_ASSET}' no encontrado en el release")
            return False, QCoreApplication.translate("potprovider_setup", "Asset del plugin '{0}' no encontrado.").format(PLUGIN_ZIP_ASSET)

        pot_dir = get_potprovider_dir()
        plugin_dir = get_plugin_dir()

        # ── Paso 1: Descargar el binario motor ─────────────────────────────
        logger.info(f"PotProvider: descargando binario desde {binary_url}")
        binary_path = get_binary_path()
        # El binario es el 80% del progreso total; el plugin, el 20% restante.
        download_file(binary_url, binary_path, progress_callback=progress_callback,
                      progress_range=(0, 80))

        # Permisos de ejecución en Unix
        if platform.system().lower() != "windows":
            logger.info("PotProvider: asignando permisos de ejecución al binario...")
            st = os.stat(binary_path)
            os.chmod(binary_path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

        if not check_potprovider():
            return False, QCoreApplication.translate("potprovider_setup", "El binario '{0}' no se encontró después de la descarga.").format(binary_name)

        logger.info("PotProvider: binario descargado correctamente.")

        # ── Paso 2: Descargar y descomprimir el plugin Python ──────────────
        logger.info(f"PotProvider: descargando plugin desde {plugin_url}")
        temp_plugin_zip = os.path.join(plugin_dir, "_pot_plugin_temp.zip")
        download_file(plugin_url, temp_plugin_zip, progress_callback=progress_callback,
                      progress_range=(80, 100))

        logger.info("PotProvider: descomprimiendo plugin...")
        with zipfile.ZipFile(temp_plugin_zip, "r") as zf:
            zf.extractall(plugin_dir)

        os.remove(temp_plugin_zip)

        if not check_plugin():
            return False, QCoreApplication.translate("potprovider_setup", "Plugin Python no encontrado después de la extracción.")

        logger.info("PotProvider: setup completo (binario + plugin).")
        return True, "PO Token Provider descargado y configurado."

    except Exception as e:
        logger.error(f"PotProvider: error en download_potprovider: {e}")
        return False, str(e)


def get_local_version(force_check=False):
    """
    Ejecuta el binario local para obtener su versión y la cachea en config.json.
    Devuelve la cadena de versión o None si no está disponible.
    """
    if not check_potprovider():
        return None

    config = get_config()
    versions = config.get("dependency_versions", {})
    if not force_check and "potprovider" in versions:
        return versions["potprovider"]

    try:
        binary_path = get_binary_path()
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        result = subprocess.run(
            [binary_path, "--version"],
            capture_output=True, text=True, timeout=10,
            creationflags=flags
        )
        # El binario imprime algo como "bgutil-pot 0.8.1"
        output = result.stdout.strip() or result.stderr.strip()
        # Extraer solo el número de versión (segunda palabra si hay espacio)
        parts = output.split()
        version = parts[-1].lstrip("v") if parts else output

        versions["potprovider"] = version
        config["dependency_versions"] = versions
        save_config(config)

        return version
    except Exception as e:
        logger.error(f"PotProvider: error obteniendo versión local: {e}")
        return None


def get_latest_remote_version():
    """Consulta la API de GitHub para obtener la versión más reciente disponible."""
    try:
        response = requests.get(POTPROVIDER_API_URL, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("tag_name", "").lstrip("v")
    except Exception as e:
        logger.error(f"PotProvider: error obteniendo versión remota: {e}")
        return None


if __name__ == "__main__":
    if not check_all():
        success, msg = download_potprovider()
        logger.info(msg)
    else:
        logger.info("PO Token Provider ya está configurado.")
