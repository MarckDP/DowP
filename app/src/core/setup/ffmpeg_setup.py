# src/core/setup/ffmpeg_setup.py
import os
import requests
import zipfile
import tarfile
import shutil
import platform
import stat
import subprocess
import re
from core.logger.logger_manager import logger
from core.utils.http_download import download_file
from core.utils.config_manager import get_config, save_config
from core.utils.paths import get_bin_root_dir
from PySide6.QtCore import QCoreApplication

# Versión fija recomendada de FFmpeg para DowP (máxima estabilidad con yt-dlp)
FFMPEG_RECOMMENDED_VERSION = "9.0.1"
GYAND_RELEASES_API = "https://api.github.com/repos/GyanD/codexffmpeg/releases"


def get_ffmpeg_config() -> dict:
    """Devuelve la configuración actual de FFmpeg desde config.json."""
    config = get_config()
    return {
        "mode": config.get("ffmpeg_mode", "managed"),
        "variant": config.get("ffmpeg_variant", "essentials"),
        "channel": config.get("ffmpeg_channel", "recommended"),
        "keep_ffplay": config.get("ffmpeg_keep_ffplay", False),
        "custom_path": config.get("ffmpeg_custom_path", ""),
    }


def get_managed_ffmpeg_dir() -> str:
    """Retorna el directorio donde DowP almacena los binarios gestionados de FFmpeg."""
    ffmpeg_dir = os.path.join(get_bin_root_dir(), "bin", "dependences", "ffmpeg")
    if not os.path.exists(ffmpeg_dir):
        logger.info(f"Creating directory: {ffmpeg_dir}")
        os.makedirs(ffmpeg_dir, exist_ok=True)
    return ffmpeg_dir


def get_ffmpeg_path() -> str:
    """
    Retorna la ruta absoluta al binario activo de ffmpeg (gestionado o personalizado).
    """
    cfg = get_ffmpeg_config()
    exe_name = "ffmpeg.exe" if platform.system().lower() == "windows" else "ffmpeg"

    if cfg["mode"] == "custom" and cfg["custom_path"]:
        custom = cfg["custom_path"].strip()
        if os.path.isfile(custom):
            return custom
        if os.path.isdir(custom):
            candidate = os.path.join(custom, exe_name)
            if os.path.isfile(candidate):
                return candidate

    # Fallback al FFmpeg gestionado por DowP
    return os.path.join(get_managed_ffmpeg_dir(), exe_name)


def get_ffprobe_path():
    """
    Retorna la ruta absoluta al ejecutable ffprobe si está disponible, o None.
    Si se usa un FFmpeg personalizado, primero busca ffprobe en su misma carpeta.
    """
    probe_name = "ffprobe.exe" if platform.system().lower() == "windows" else "ffprobe"
    cfg = get_ffmpeg_config()

    if cfg["mode"] == "custom" and cfg["custom_path"]:
        custom = cfg["custom_path"].strip()
        custom_dir = custom if os.path.isdir(custom) else os.path.dirname(custom)
        candidate = os.path.join(custom_dir, probe_name)
        if os.path.isfile(candidate):
            return candidate

    # Fallback a la carpeta gestionada
    managed_probe = os.path.join(get_managed_ffmpeg_dir(), probe_name)
    if os.path.isfile(managed_probe):
        return managed_probe

    return None


def get_ffmpeg_dir() -> str:
    """
    Retorna el directorio que contiene el binario activo de FFmpeg.
    Mantiene compatibilidad total con llamadas existentes (yt-dlp ffmpeg_location, etc.).
    """
    active_path = get_ffmpeg_path()
    if os.path.isfile(active_path):
        return os.path.dirname(active_path)
    return get_managed_ffmpeg_dir()


_ffmpeg_checked = False

def check_ffmpeg() -> bool:
    """Verifica si el binario activo de FFmpeg existe y es ejecutable."""
    global _ffmpeg_checked
    active_path = get_ffmpeg_path()
    exists = os.path.isfile(active_path)
    if not _ffmpeg_checked:
        logger.debug(f"Checking FFmpeg existence at '{active_path}': {exists}")
        _ffmpeg_checked = True
    return exists


def validate_custom_ffmpeg(path: str) -> tuple[bool, str, str]:
    """
    Valida un ejecutable o directorio de FFmpeg personalizado.
    Retorna: (es_valido: bool, version_str: str, mensaje_detalle: str).
    """
    if not path or not path.strip():
        return False, "", QCoreApplication.translate("ffmpeg_setup", "Ruta vacía.")

    path = path.strip()
    exe_name = "ffmpeg.exe" if platform.system().lower() == "windows" else "ffmpeg"
    candidate = path

    if os.path.isdir(candidate):
        candidate = os.path.join(candidate, exe_name)

    if not os.path.isfile(candidate):
        return False, "", QCoreApplication.translate("ffmpeg_setup", "No se encontró el ejecutable '{0}' en la ruta especificada.").format(exe_name)

    try:
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        result = subprocess.run(
            [candidate, "-version"],
            capture_output=True, text=True, timeout=6, creationflags=flags
        )
        if result.returncode != 0:
            err_msg = QCoreApplication.translate("ffmpeg_setup", "El ejecutable falló con código de salida {0}.").format(result.returncode)
            logger.warning(f"FFmpeg: Validación de ruta personalizada falló en '{candidate}': {err_msg}")
            return False, "", err_msg

        first_line = result.stdout.strip().split('\n')[0]
        match = re.search(r'version\s+([^\s]+)', first_line)
        version = match.group(1) if match else first_line.split()[2]
        logger.info(f"FFmpeg: Ejecutable personalizado validado exitosamente en '{candidate}' (Versión detectada: {version})")
        return True, version, QCoreApplication.translate("ffmpeg_setup", "Ejecutable válido y funcional.")
    except Exception as e:
        logger.error(f"FFmpeg: Error ejecutando/validando ejecutable en '{candidate}': {e}")
        return False, "", QCoreApplication.translate("ffmpeg_setup", "Error ejecutando FFmpeg: {0}").format(e)


def get_platform_info(variant="essentials", channel="recommended", version=None):
    """Determina la estrategia de descarga de FFmpeg según el SO y opciones seleccionadas."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "windows":
        return {
            "os": "windows",
            "variant": variant,
            "channel": channel,
            "version": version or (FFMPEG_RECOMMENDED_VERSION if channel == "recommended" else None),
            "binary_name": "ffmpeg.exe",
            "extract_method": "zip_gyand"
        }
    elif system == "darwin":
        return {
            "os": "mac",
            "api_url": "https://evermeet.cx/ffmpeg/info/ffmpeg/release",
            "binary_name": "ffmpeg",
            "extract_method": "zip_direct"
        }
    elif system == "linux":
        arch = "linuxarm64" if machine in ["arm64", "aarch64"] else "linux64"
        return {
            "os": "linux",
            "download_url": f"https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-{arch}-gpl.tar.xz",
            "binary_name": "ffmpeg",
            "extract_method": "tarxz_btbn"
        }
    else:
        return {
            "os": "linux",
            "download_url": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz",
            "binary_name": "ffmpeg",
            "extract_method": "tarxz_btbn"
        }


def _resolve_windows_download_url(variant: str, channel: str, version: str = None) -> str:
    """Resuelve la URL de descarga para Windows desde GyanD/codexffmpeg."""
    is_full = (variant == "full")
    target_suffix = "full_build.zip" if is_full else "essentials_build.zip"

    # 1. Versión específica o recomendada (8.0.1)
    if version and version != "latest":
        tag_url = f"{GYAND_RELEASES_API}/tags/{version}"
        logger.info(f"Buscando release FFmpeg en {tag_url}")
        res = requests.get(tag_url, timeout=12)
        res.raise_for_status()
        data = res.json()
        for asset in data.get("assets", []):
            name = asset.get("name", "").lower()
            if target_suffix in name and "-shared" not in name:
                return asset.get("browser_download_url")

    # 2. Última release oficial (Stable latest)
    if channel == "latest":
        logger.info("Buscando última release oficial de FFmpeg en GyanD...")
        res = requests.get(GYAND_RELEASES_API, timeout=12)
        res.raise_for_status()
        releases = res.json()
        for rel in releases:
            tag = rel.get("tag_name", "")
            # Las releases estables son números de versión (ej. 9.0.1, 8.1.2) sin 'git'
            if "git" not in tag.lower():
                for asset in rel.get("assets", []):
                    name = asset.get("name", "").lower()
                    if target_suffix in name and "-shared" not in name:
                        return asset.get("browser_download_url")

    # 3. Nightly (Git master)
    if channel == "nightly":
        logger.info("Buscando compilación Nightly (Git) de FFmpeg en GyanD...")
        res = requests.get(GYAND_RELEASES_API, timeout=12)
        res.raise_for_status()
        releases = res.json()
        for rel in releases:
            tag = rel.get("tag_name", "")
            if "git" in tag.lower():
                for asset in rel.get("assets", []):
                    name = asset.get("name", "").lower()
                    if target_suffix in name and "-shared" not in name:
                        return asset.get("browser_download_url")

    # Fallback a release recomendada 8.0.1
    fallback_url = f"{GYAND_RELEASES_API}/tags/{FFMPEG_RECOMMENDED_VERSION}"
    logger.info(f"Fallback a release recomendada {FFMPEG_RECOMMENDED_VERSION}...")
    res = requests.get(fallback_url, timeout=12)
    res.raise_for_status()
    for asset in res.json().get("assets", []):
        name = asset.get("name", "").lower()
        if target_suffix in name and "-shared" not in name:
            return asset.get("browser_download_url")

    return None


def download_ffmpeg(variant=None, channel=None, keep_ffplay=None, version=None, progress_callback=None):
    """
    Descarga, extrae y configura FFmpeg.
    - variant: 'essentials' | 'full'
    - channel: 'recommended' | 'latest' | 'nightly'
    - keep_ffplay: bool (False = elimina ffplay.exe, True = conserva ffplay.exe)
    """
    try:
        cfg = get_ffmpeg_config()
        variant = variant or cfg.get("variant", "essentials")
        channel = channel or cfg.get("channel", "recommended")
        if keep_ffplay is None:
            keep_ffplay = cfg.get("keep_ffplay", False)

        logger.info(f"FFmpeg: Iniciando proceso de descarga/actualización -> Variante: '{variant}', Canal: '{channel}', Keep ffplay: {keep_ffplay}, Versión objetivo: {version or 'Auto'}")

        info = get_platform_info(variant=variant, channel=channel, version=version)
        download_url = info.get("download_url")

        if not download_url:
            if info["os"] == "windows":
                target_ver = version or (FFMPEG_RECOMMENDED_VERSION if channel == "recommended" else None)
                download_url = _resolve_windows_download_url(variant, channel, version=target_ver)
            elif info["os"] == "mac":
                res = requests.get(info["api_url"], timeout=12)
                res.raise_for_status()
                download_url = res.json().get("download", {}).get("zip", {}).get("url")

        if not download_url:
            logger.error("No se pudo resolver la URL de descarga para FFmpeg.")
            return False, QCoreApplication.translate("ffmpeg_setup", "No se encontró el enlace de descarga de FFmpeg.")

        ffmpeg_dir = get_managed_ffmpeg_dir()
        is_tar = download_url.endswith(".tar.xz")
        temp_file = os.path.join(ffmpeg_dir, "ffmpeg_temp.tar.xz" if is_tar else "ffmpeg_temp.zip")
        extract_path = os.path.join(ffmpeg_dir, "temp_extract")

        # 1. Descarga
        logger.info(f"Descargando FFmpeg ({variant} / {channel}) desde {download_url}")
        download_file(download_url, temp_file, progress_callback=progress_callback)

        # 2. Extracción temporal
        logger.info("Extrayendo paquete de FFmpeg...")
        if os.path.exists(extract_path):
            shutil.rmtree(extract_path, ignore_errors=True)
        os.makedirs(extract_path, exist_ok=True)

        if is_tar:
            with tarfile.open(temp_file, 'r:xz') as tar_ref:
                tar_ref.extractall(extract_path)
        else:
            with zipfile.ZipFile(temp_file, 'r') as zip_ref:
                zip_ref.extractall(extract_path)

        # 3. Ubicar y mover ejecutables requeridos
        logger.info("Ubicando ejecutables (ffmpeg, ffprobe, ffplay)...")
        exe_found = False
        target_ffmpeg = info["binary_name"]
        target_ffprobe = "ffprobe.exe" if info["os"] == "windows" else "ffprobe"
        target_ffplay = "ffplay.exe" if info["os"] == "windows" else "ffplay"

        # Gestión de ffplay.exe en el directorio de destino
        ffplay_in_dir = os.path.join(ffmpeg_dir, target_ffplay)
        if not keep_ffplay and os.path.exists(ffplay_in_dir):
            try:
                os.remove(ffplay_in_dir)
                logger.info(f"Eliminado binario no requerido: {target_ffplay}")
            except Exception as e:
                logger.warning(f"No se pudo eliminar {target_ffplay}: {e}")

        for root, dirs, files in os.walk(extract_path):
            for file in files:
                file_lower = file.lower()

                # ffmpeg
                if file == target_ffmpeg or (info["os"] == "windows" and file_lower == "ffmpeg.exe"):
                    src_file = os.path.join(root, file)
                    dst_file = os.path.join(ffmpeg_dir, target_ffmpeg)
                    if os.path.exists(dst_file):
                        os.remove(dst_file)
                    shutil.move(src_file, dst_file)
                    exe_found = True

                # ffprobe
                elif file == target_ffprobe or (info["os"] == "windows" and file_lower == "ffprobe.exe"):
                    src_file = os.path.join(root, file)
                    dst_file = os.path.join(ffmpeg_dir, target_ffprobe)
                    if os.path.exists(dst_file):
                        os.remove(dst_file)
                    shutil.move(src_file, dst_file)

                # ffplay (solo si keep_ffplay es True)
                elif keep_ffplay and (file == target_ffplay or (info["os"] == "windows" and file_lower == "ffplay.exe")):
                    src_file = os.path.join(root, file)
                    dst_file = os.path.join(ffmpeg_dir, target_ffplay)
                    if os.path.exists(dst_file):
                        os.remove(dst_file)
                    shutil.move(src_file, dst_file)
                    logger.info(f"Conservado binario opcional: {target_ffplay}")

        # 4. Permisos Unix si aplica
        if exe_found and info["os"] != "windows":
            logger.info("Configurando permisos de ejecución para binarios de FFmpeg...")
            for bin_name in [target_ffmpeg, target_ffprobe, target_ffplay]:
                final_bin = os.path.join(ffmpeg_dir, bin_name)
                if os.path.exists(final_bin):
                    st = os.stat(final_bin)
                    os.chmod(final_bin, st.st_mode | stat.S_IEXEC)

        # 5. Limpieza de archivos temporales
        logger.info("Limpiando archivos temporales...")
        if os.path.exists(temp_file):
            os.remove(temp_file)
        if os.path.exists(extract_path):
            shutil.rmtree(extract_path, ignore_errors=True)

        if not exe_found:
            logger.error("No se encontró el ejecutable de FFmpeg en el paquete descargado.")
            return False, QCoreApplication.translate("ffmpeg_setup", "No se encontró el ejecutable en el paquete de FFmpeg.")

        # 6. Actualizar versión en config
        new_ver = get_local_version(force_check=True)

        logger.info(f"FFmpeg: Instalación y configuración completadas exitosamente. Versión activa: '{new_ver}' en '{get_ffmpeg_path()}'")
        return True, f"FFmpeg {new_ver or ''} descargado y configurado exitosamente."
    except Exception as e:
        logger.error(f"FFmpeg: Error durante la descarga o configuración: {e}", exc_info=True)
        return False, str(e)


def get_local_version(force_check=False):
    """Obtiene la versión del FFmpeg activo (gestionado o personalizado)."""
    if not check_ffmpeg():
        return None

    config = get_config()
    versions = config.get("dependency_versions", {})
    if not force_check and "ffmpeg" in versions:
        return versions["ffmpeg"]

    try:
        ffmpeg_exe = get_ffmpeg_path()
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        result = subprocess.run(
            [ffmpeg_exe, "-version"],
            capture_output=True, text=True, check=True, creationflags=flags
        )
        first_line = result.stdout.strip().split('\n')[0]
        match = re.search(r'version\s+([^\s]+)', first_line)
        if match:
            version = match.group(1)
        else:
            version = first_line.split()[2]

        versions["ffmpeg"] = version
        config["dependency_versions"] = versions
        save_config(config)

        return version
    except Exception as e:
        logger.error(f"Error obteniendo la versión local de FFmpeg: {e}")
        return None


def get_latest_remote_version(channel="recommended", variant="essentials"):
    """Consulta la versión remota según el canal seleccionado."""
    info = get_platform_info()
    try:
        if info["os"] == "windows":
            if channel == "recommended":
                return FFMPEG_RECOMMENDED_VERSION

            res = requests.get(GYAND_RELEASES_API, timeout=10)
            res.raise_for_status()
            releases = res.json()

            if channel == "nightly":
                for rel in releases:
                    tag = rel.get("tag_name", "")
                    if "git" in tag.lower():
                        return tag
                return "nightly"
            else:
                # Latest stable release
                for rel in releases:
                    tag = rel.get("tag_name", "")
                    if "git" not in tag.lower():
                        return tag.lstrip("v")
                return FFMPEG_RECOMMENDED_VERSION
        elif info["os"] == "mac":
            url = "https://evermeet.cx/ffmpeg/info/ffmpeg/release"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.json().get("version", "")
        else:
            url = "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.json().get("name", "latest")
    except Exception as e:
        logger.error(f"Error obteniendo la versión remota de FFmpeg: {e}")
        return None


if __name__ == "__main__":
    if not check_ffmpeg():
        success, msg = download_ffmpeg()
        logger.info(msg)
    else:
        logger.info(f"FFmpeg ya está configurado. Versión: {get_local_version()}")

