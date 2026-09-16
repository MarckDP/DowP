# src/core/setup/vtracer_setup.py
"""Descarga e instalación de vtracer -- dependencia OPCIONAL (Ajustes >
Dependencias, ver gui/tabs/settings/pages/deps_page.py) que vectoriza imágenes
raster a SVG en el Editor de Imagen.

Mismo molde que deno_setup.py: un solo binario portable, descarga directa desde
GitHub Releases (visioncortex/vtracer), sin variantes/canales como FFmpeg y sin
el hack de extraer-instalador-sin-ejecutar que necesita Ghostscript por no
tener build oficial portable.

Los releases de vtracer publican DOS familias de assets -- confirmado a mano
contra el último release (1.0.0-alpha.4) antes de escribir esto: los binarios
CLI sueltos que interesan acá (~1 MB, "vtracer-<target>.<zip|tar.gz>", con
"vtracer"/"vtracer.exe" solo en la raíz del archivo, sin subcarpeta) y la app
de escritorio completa ("VTracer_*", 40-120 MB, instalador/AppImage/dmg) que
NO es lo que se quiere bundlear acá.
"""
import os
import platform
import stat
import tarfile
import zipfile

import requests

from core.logger.logger_manager import logger
from core.utils.paths import get_bin_root_dir

VTRACER_API_URL = "https://api.github.com/repos/visioncortex/vtracer/releases/latest"


def get_platform_info():
    """Determina el asset y el nombre del binario según SO/arquitectura -- mismo
    criterio que deno_setup.py::get_platform_info(). Sin build de Windows ARM64
    publicado hoy: como con Deno, se cae a x86_64 si la arquitectura no se
    reconoce."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    if machine in ("arm64", "aarch64"):
        arch = "aarch64"
    else:
        arch = "x86_64"

    if system == "windows":
        asset_name = "vtracer-x86_64-pc-windows-msvc.zip"
        binary_name = "vtracer.exe"
    elif system == "darwin":
        asset_name = f"vtracer-{arch}-apple-darwin.tar.gz"
        binary_name = "vtracer"
    elif system == "linux":
        asset_name = f"vtracer-{arch}-unknown-linux-musl.tar.gz"
        binary_name = "vtracer"
    else:
        asset_name = "vtracer-x86_64-unknown-linux-musl.tar.gz"
        binary_name = "vtracer"

    return asset_name, binary_name


def get_vtracer_dir() -> str:
    """Mismo patrón que get_deno_dir() (deno_setup.py)."""
    vtracer_dir = os.path.join(get_bin_root_dir(), "bin", "dependences", "vtracer")
    if not os.path.exists(vtracer_dir):
        logger.info(f"Creating directory: {vtracer_dir}")
        os.makedirs(vtracer_dir)
    return vtracer_dir


def get_vtracer_path() -> str:
    """Ruta absoluta al binario ejecutable de vtracer según la plataforma actual."""
    _, binary_name = get_platform_info()
    return os.path.join(get_vtracer_dir(), binary_name)


_vtracer_checked = False


def check_vtracer() -> bool:
    """Verifica si el binario de vtracer existe en su carpeta gestionada."""
    global _vtracer_checked
    _, binary_name = get_platform_info()
    exists = os.path.isfile(get_vtracer_path())
    if not _vtracer_checked:
        logger.debug(f"Checking {binary_name} existence: {exists}")
        _vtracer_checked = True
    return exists


def download_vtracer(progress_callback=None) -> tuple[bool, str]:
    """Descarga, extrae y deja listo el binario de vtracer. Mismo flujo que
    download_deno(), con la diferencia de que Mac/Linux vienen en .tar.gz
    (Windows sigue siendo .zip)."""
    try:
        asset_name, binary_name = get_platform_info()
        logger.info(f"Fetching latest vtracer release info from {VTRACER_API_URL} for {asset_name}")
        response = requests.get(VTRACER_API_URL, timeout=15)
        response.raise_for_status()
        data = response.json()

        download_url = None
        for asset in data.get("assets", []):
            if asset.get("name") == asset_name:
                download_url = asset.get("browser_download_url")
                break

        if not download_url:
            logger.error(f"vtracer asset '{asset_name}' not found in release assets")
            return False, f"vtracer asset '{asset_name}' not found."

        vtracer_dir = get_vtracer_dir()
        is_tar = asset_name.endswith(".tar.gz")
        temp_file = os.path.join(vtracer_dir, "vtracer_temp.tar.gz" if is_tar else "vtracer_temp.zip")

        # 1. Descarga
        logger.info(f"Downloading vtracer from {download_url}")
        r = requests.get(download_url, stream=True, timeout=30)
        r.raise_for_status()

        total_size = int(r.headers.get("content-length", 0))
        downloaded = 0

        with open(temp_file, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total_size > 0:
                        percent = int((downloaded / total_size) * 100)
                        progress_callback(percent)

        # 2. Extracción (el binario vive suelto en la raíz del archivo, sin
        # subcarpeta, tanto en el .zip de Windows como en el .tar.gz de Mac/Linux)
        logger.info("Extracting vtracer package...")
        if is_tar:
            with tarfile.open(temp_file, "r:gz") as tar_ref:
                tar_ref.extractall(vtracer_dir)
        else:
            with zipfile.ZipFile(temp_file, "r") as zip_ref:
                zip_ref.extractall(vtracer_dir)

        # 3. Permisos Unix
        vtracer_exe = os.path.join(vtracer_dir, binary_name)
        if os.path.exists(vtracer_exe) and platform.system().lower() != "windows":
            logger.info("Setting executable permissions for vtracer binary...")
            st = os.stat(vtracer_exe)
            os.chmod(vtracer_exe, st.st_mode | stat.S_IEXEC)

        # 4. Limpieza
        logger.info("Cleaning up temporary archive...")
        os.remove(temp_file)

        if not check_vtracer():
            logger.error(f"{binary_name} was not found after extraction")
            return False, f"{binary_name} missing after extraction."

        logger.info("vtracer setup completed successfully.")
        return True, "vtracer downloaded and configured."
    except Exception as e:
        logger.error(f"Error setting up vtracer: {e}")
        return False, str(e)


import subprocess

from core.utils.config_manager import get_config, save_config


def get_local_version(force_check=False):
    """Corre el vtracer local para obtener su versión, cacheada en config.json
    para evitar el costo de lanzar el proceso en cada consulta -- mismo patrón
    que deno_setup.py::get_local_version()."""
    if not check_vtracer():
        return None

    config = get_config()
    versions = config.get("dependency_versions", {})
    if not force_check and "vtracer" in versions:
        return versions["vtracer"]

    try:
        vtracer_exe = get_vtracer_path()
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        result = subprocess.run(
            [vtracer_exe, "--version"],
            capture_output=True, text=True, check=True, timeout=10, creationflags=flags,
        )
        # Salida esperada: "vtracer 1.0.0-alpha.4" (puede variar el formato exacto
        # entre releases -- se toma el último token no vacío de la primera línea).
        first_line = result.stdout.strip().split("\n")[0]
        tokens = first_line.split()
        version = tokens[-1] if tokens else None

        if version:
            versions["vtracer"] = version
            config["dependency_versions"] = versions
            save_config(config)

        return version
    except Exception as e:
        logger.error(f"Error getting local vtracer version: {e}")
        return None


def get_latest_remote_version():
    """Última versión (tag) publicada, consultada a la API de GitHub."""
    try:
        response = requests.get(VTRACER_API_URL, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("tag_name", "").lstrip("v")
    except Exception as e:
        logger.error(f"Error getting remote vtracer version: {e}")
        return None
