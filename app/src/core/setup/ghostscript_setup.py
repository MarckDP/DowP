# src/core/setup/ghostscript_setup.py
"""Descarga e instalación de Ghostscript -- dependencia OPCIONAL (Ajustes >
Dependencias, ver gui/tabs/settings/pages/deps_page.py) que habilita EPS/PS en
el Editor de Imagen (ver core/tabs/image_tools/image_converter.py::_load_eps_ps).

Descarga gestionada por DowP: solo en Windows. El único release oficial
(ArtifexSoftware/ghostpdl-downloads) es un instalador NSIS, sin build portable
ni instalación silenciosa desde la 10.01.0 -- así que en vez de correr el
instalador, se lo EXTRAE con 7-Zip sin ejecutarlo (confirmado que funciona: el
instalador se abre como archivo NSIS y expone bin/gswin64c.exe + lib/ +
Resource/ intactos, la disposición estándar que Ghostscript necesita en tiempo
de ejecución).

7-Zip en sí no es una dependencia del proyecto (no hay ninguna aquí) -- se
bootstrapea desde el paquete NuGet "7-Zip.x64" (un ZIP plano, a diferencia de
la "Extra" del propio 7-zip.org, que es un .7z y sería circular). Se cachea
una sola vez en bin/dependences/_tools/7zip/ (prefijo "_tools": detalle interno,
no es una tarjeta propia de Ajustes).

Mac/Linux: no hay build bundleable (macOS sin precompilado oficial, Linux solo
como paquete Snap) -- en vez de descargar/extraer nada, se detecta un `gs` ya
instalado por el propio usuario (típicamente `brew install ghostscript` /
`sudo apt install ghostscript`, ver get_install_info() más abajo, que la
tarjeta de Ajustes usa para sugerir el comando correcto según el SO/gestor de
paquetes detectado)."""
import os
import platform
import re
import shutil
import subprocess
import tempfile
import zipfile

import requests

from core.logger.logger_manager import logger
from core.utils.paths import get_bin_root_dir
from PySide6.QtCore import QCoreApplication

# Version y URL de respaldo: es lo que se instala si la consulta a GitHub falla
# (sin red, API caida o con el limite de peticiones agotado). El camino normal ya
# no pasa por aqui -- ver get_remote_release(), que resuelve ambas cosas contra el
# ultimo release publicado.
GS_VERSION = "10.07.1"
_GS_INSTALLER_URL = (
    "https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/"
    "gs10071/gs10071w64.exe"
)

_GS_LATEST_RELEASE_API = (
    "https://api.github.com/repos/ArtifexSoftware/ghostpdl-downloads/releases/latest"
)
# Acepta tanto "10.07.1" como "9.52": el repositorio publico ambos formatos.
_GS_VERSION_RE = re.compile(r"(\d+(?:\.\d+)+)")
_GS_WINDOWS_ASSET_SUFFIX = "w64.exe"
# 7-Zip.x64 16.2.1 -- verificado en vivo: ZIP plano, trae tools/7z.exe +
# tools/7z.dll (el 7-Zip completo, con soporte NSIS vía plugin -- a diferencia
# de "7-Zip.CommandLine", cuyo 7za.exe es la build standalone SIN plugins y
# falla con "Unsupported archive type" al pedirle NSIS).
_SEVENZIP_NUGET_URL = "https://www.nuget.org/api/v2/package/7-Zip.x64/16.2.1"
_GS_KEEP_DIRS = ("bin", "lib", "Resource")

# Rutas conocidas de gs en Mac/Linux para cuando shutil.which("gs") no alcanza
# -- ver _find_system_gs().
_SYSTEM_GS_FALLBACK_PATHS = (
    "/opt/homebrew/bin/gs",  # Homebrew en Apple Silicon
    "/usr/local/bin/gs",     # Homebrew en Intel / Linuxbrew
    "/usr/bin/gs",           # paquete nativo de la distro (apt/dnf/pacman/zypper)
)

# (ejecutable a buscar en PATH, etiqueta para la UI, comando sugerido) -- orden
# de preferencia al detectar qué gestor de paquetes tiene el usuario en Linux.
_LINUX_PKG_MANAGERS = (
    ("apt", "APT (Debian/Ubuntu)", "sudo apt install ghostscript"),
    ("dnf", "DNF (Fedora/RHEL)", "sudo dnf install ghostscript"),
    ("pacman", "Pacman (Arch)", "sudo pacman -S ghostscript"),
    ("zypper", "Zypper (openSUSE)", "sudo zypper install ghostscript"),
)


def get_managed_ghostscript_dir() -> str:
    """Mismo patrón que get_managed_ffmpeg_dir() (ffmpeg_setup.py)."""
    gs_dir = os.path.join(get_bin_root_dir(), "bin", "dependences", "ghostscript")
    os.makedirs(gs_dir, exist_ok=True)
    return gs_dir


def _tools_dir() -> str:
    d = os.path.join(get_bin_root_dir(), "bin", "dependences", "_tools", "7zip")
    os.makedirs(d, exist_ok=True)
    return d


def _ensure_7zip_tool(progress_callback=None) -> str | None:
    """Devuelve la ruta a un 7z.exe usable (con su 7z.dll al lado), descargando
    y cacheando el paquete NuGet la primera vez -- None si algo falla."""
    tools_dir = _tools_dir()
    exe_path = os.path.join(tools_dir, "7z.exe")
    dll_path = os.path.join(tools_dir, "7z.dll")
    if os.path.isfile(exe_path) and os.path.isfile(dll_path):
        return exe_path

    try:
        with tempfile.TemporaryDirectory(prefix="dowp_7zip_") as tmp_dir:
            temp_zip = os.path.join(tmp_dir, "7zip.nupkg")
            r = requests.get(_SEVENZIP_NUGET_URL, stream=True, timeout=30)
            r.raise_for_status()
            total_size = int(r.headers.get("content-length", 0))
            downloaded = 0
            with open(temp_zip, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total_size > 0:
                            progress_callback(int((downloaded / total_size) * 10))

            with zipfile.ZipFile(temp_zip, "r") as zip_ref:
                zip_ref.extract("tools/7z.exe", tmp_dir)
                zip_ref.extract("tools/7z.dll", tmp_dir)

            shutil.copy2(os.path.join(tmp_dir, "tools", "7z.exe"), exe_path)
            shutil.copy2(os.path.join(tmp_dir, "tools", "7z.dll"), dll_path)
        return exe_path
    except Exception as e:
        logger.error(f"Ghostscript: no se pudo preparar la herramienta de extracción (7-Zip): {e}")
        return None


def _find_system_gs() -> str | None:
    """gs ya instalado por el usuario en Mac/Linux (Homebrew/apt/dnf/etc).
    shutil.which() no alcanza solo: una app lanzada desde Finder (o un bundle
    de PyInstaller) arranca con un PATH mínimo que no incluye los prefijos no
    estándar de Homebrew (/opt/homebrew, /usr/local) aunque el usuario ya lo
    haya instalado ahí -- de ahí el fallback a rutas conocidas."""
    exe = shutil.which("gs")
    if exe:
        return exe
    for candidate in _SYSTEM_GS_FALLBACK_PATHS:
        if os.path.isfile(candidate):
            return candidate
    return None


def detect_package_manager() -> str | None:
    """Ejecutable del gestor de paquetes de Linux detectado en PATH (apt/dnf/
    pacman/zypper), o None si no se encontró ninguno. Solo tiene sentido en
    Linux -- en macOS siempre se ofrece Homebrew, ver get_install_info()."""
    for exe, _label, _cmd in _LINUX_PKG_MANAGERS:
        if shutil.which(exe):
            return exe
    return None


def get_install_info() -> tuple[str, str]:
    """(etiqueta del gestor, comando sugerido) para instalar Ghostscript en
    este SO -- usado por la tarjeta de Ajustes > Dependencias para mostrarle al
    usuario qué correr en su terminal. macOS siempre ofrece Homebrew (único
    gestor real ahí); en Linux se detecta el gestor nativo ya presente en PATH,
    con Homebrew (Linuxbrew) como último fallback si no se encontró ninguno."""
    if platform.system() == "Darwin":
        return "Homebrew", "brew install ghostscript"
    for exe, label, cmd in _LINUX_PKG_MANAGERS:
        if shutil.which(exe):
            return label, cmd
    if shutil.which("brew"):
        return "Homebrew", "brew install ghostscript"
    return "APT (Debian/Ubuntu)", "sudo apt install ghostscript"


def check_ghostscript() -> bool:
    """True si Ghostscript está disponible -- en Windows, el build gestionado
    por DowP (extraído del instalador oficial); en Mac/Linux, un `gs` ya
    instalado por el propio usuario (ver _find_system_gs() y get_install_info()
    -- DowP no bundlea Ghostscript ahí, no hay build portable oficial)."""
    if platform.system() == "Windows":
        exe = get_gs_exe_path()
        return bool(exe and os.path.isfile(exe))
    return bool(_find_system_gs())


def get_gs_exe_path() -> str | None:
    """Ruta a un binario de Ghostscript utilizable: el gswin64c.exe gestionado
    por DowP en Windows, o el `gs` del sistema detectado en Mac/Linux. None si
    no está instalado todavía."""
    if platform.system() == "Windows":
        return os.path.join(get_managed_ghostscript_dir(), "bin", "gswin64c.exe")
    return _find_system_gs()


def get_local_version() -> str | None:
    """Version instalada, leida siempre del propio binario con `gs --version`.

    En Windows esto antes devolvia la constante GS_VERSION sin preguntarle a nadie,
    porque DowP extraia siempre el mismo instalador fijado. Desde que la descarga
    resuelve el ultimo release publicado (ver get_remote_release), esa constante ya
    no describe lo que hay en disco: tras actualizar seguiria informando la version
    vieja, y el chequeo de actualizaciones ofreceria eternamente la misma
    actualizacion ya instalada."""
    exe = get_gs_exe_path()
    if not exe or not check_ghostscript():
        return None
    try:
        result = subprocess.run(
            [exe, "--version"], capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return result.stdout.strip() or None
    except Exception as e:
        logger.error(f"Ghostscript: no se pudo leer la version instalada: {e}")
        return None


def get_remote_release() -> tuple[str, str] | None:
    """(version, url del instalador de Windows) del ultimo Ghostscript estable,
    consultado a la API de GitHub. None si no se pudo averiguar.

    Se consulta /releases/latest y no la lista completa a proposito: GitHub ya
    excluye ahi borradores y release candidates, mientras que en la lista cruda las
    rc aparecen intercaladas por fecha (gs10080rc1 figura por delante de la ultima
    estable), de modo que recorrerla a mano se arriesga a ofrecer una rc como si
    fuera definitiva.

    La URL se toma del propio asset en vez de armarla concatenando: el instalador
    sigue el patron "<tag>w64.exe" en los releases recientes, pero el historial
    tiene excepciones (el release gs926 publica gs926aw64.exe), asi que es mas
    seguro leer lo que la API informa que deducirlo."""
    try:
        response = requests.get(
            _GS_LATEST_RELEASE_API, timeout=15,
            headers={"Accept": "application/vnd.github+json"},
        )
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logger.error(f"Ghostscript: no se pudo consultar la ultima version en GitHub: {e}")
        return None

    installer_url = next(
        (a.get("browser_download_url") for a in data.get("assets", [])
         if str(a.get("name", "")).endswith(_GS_WINDOWS_ASSET_SUFFIX)),
        None,
    )
    if not installer_url:
        logger.warning("Ghostscript: el ultimo release no publica instalador para Windows.")
        return None

    # La version sale del nombre del release ("Ghostscript/GhostPDL 10.07.1"). Si
    # ese campo viene vacio -- ocurre, por ejemplo, en el release gs10050 -- se
    # devuelve None en lugar de deducirla del tag: el tag es una cadena de digitos
    # sin separadores (gs10071) que no se puede repartir en 10.07.1 sin adivinar, y
    # una version mal leida haria anunciar actualizaciones inexistentes.
    match = _GS_VERSION_RE.search(data.get("name") or "")
    if not match:
        logger.warning("Ghostscript: no se pudo leer el numero de version del ultimo release.")
        return None
    return match.group(1), installer_url


def get_remote_version() -> str | None:
    """Ultima version estable publicada, o None si no se pudo consultar. Envoltorio
    de get_remote_release() con la forma que espera el chequeo de actualizaciones
    de Ajustes > Dependencias (ver UpdateCheckWorker en deps_page.py)."""
    release = get_remote_release()
    return release[0] if release else None


def download_ghostscript(progress_callback=None) -> tuple[bool, str]:
    """Descarga el instalador oficial de Ghostscript y lo extrae con 7-Zip SIN
    ejecutarlo (ver nota del módulo) -- deja bin/lib/Resource listos en
    get_managed_ghostscript_dir()."""
    if platform.system() != "Windows":
        label, cmd = get_install_info()
        return False, QCoreApplication.translate("ghostscript_setup", "En este SO, instala Ghostscript vía {0}: {1}").format(label, cmd)

    try:
        seven_zip = _ensure_7zip_tool(progress_callback)
        if not seven_zip:
            return False, QCoreApplication.translate("ghostscript_setup", "No se pudo preparar la herramienta de extracción (7-Zip).")

        # Se instala el ultimo release publicado; si GitHub no responde se cae al
        # instalador fijado en _GS_INSTALLER_URL, que sigue siendo una version
        # valida. Es preferible instalar una version algo vieja que dejar al usuario
        # sin Ghostscript porque la API no estaba disponible en ese momento.
        release = get_remote_release()
        if release:
            version, installer_url = release
            logger.info(f"Ghostscript: ultimo release publicado: {version}")
        else:
            installer_url = _GS_INSTALLER_URL
            logger.warning(
                f"Ghostscript: no se pudo resolver el ultimo release, se usa la "
                f"version de respaldo {GS_VERSION}.")

        with tempfile.TemporaryDirectory(prefix="dowp_ghostscript_") as tmp_dir:
            installer_path = os.path.join(tmp_dir, "gs_installer.exe")
            logger.info(f"Ghostscript: descargando instalador desde {installer_url}")
            r = requests.get(installer_url, stream=True, timeout=60)
            r.raise_for_status()
            total_size = int(r.headers.get("content-length", 0))
            downloaded = 0
            with open(installer_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=16384):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total_size > 0:
                            pct = 10 + int((downloaded / total_size) * 60)
                            progress_callback(pct)

            extract_dir = os.path.join(tmp_dir, "extracted")
            logger.info("Ghostscript: extrayendo el instalador con 7-Zip (sin ejecutarlo)...")
            result = subprocess.run(
                [seven_zip, "x", installer_path, f"-o{extract_dir}", "-y"],
                capture_output=True, text=True, timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if progress_callback:
                progress_callback(90)
            if result.returncode != 0:
                logger.error(f"Ghostscript: 7-Zip falló extrayendo el instalador: {result.stderr}")
                return False, QCoreApplication.translate("ghostscript_setup", "No se pudo extraer el instalador: {0}").format(result.stderr[:300])

            extracted_bin = os.path.join(extract_dir, "bin", "gswin64c.exe")
            if not os.path.isfile(extracted_bin):
                return False, QCoreApplication.translate("ghostscript_setup", "El instalador se extrajo pero no se encontró gswin64c.exe.")

            dest_dir = get_managed_ghostscript_dir()
            if os.path.isdir(dest_dir):
                shutil.rmtree(dest_dir, ignore_errors=True)
            os.makedirs(dest_dir, exist_ok=True)
            for name in _GS_KEEP_DIRS:
                src = os.path.join(extract_dir, name)
                if os.path.isdir(src):
                    shutil.copytree(src, os.path.join(dest_dir, name))

        if progress_callback:
            progress_callback(100)

        if not check_ghostscript():
            return False, QCoreApplication.translate("ghostscript_setup", "La instalación terminó pero Ghostscript no quedó detectable.")

        logger.info(f"Ghostscript: instalación completada en {get_managed_ghostscript_dir()}")
        return True, f"Ghostscript {GS_VERSION} instalado correctamente."
    except Exception as e:
        logger.error(f"Ghostscript: error durante la descarga/instalación: {e}", exc_info=True)
        return False, str(e)
