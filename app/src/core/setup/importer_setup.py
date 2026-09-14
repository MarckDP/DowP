# src/core/setup/importer_setup.py
r"""Instalación del DowP Importer (el panel CEP de Adobe) desde la propia app.

El panel viaja dentro del bundle de DowP (ver get_bundled_importer_dir()), así que
instalarlo es copiar una carpeta: sin descarga, sin release aparte, sin número de
versión aparte. Cuando la app se actualiza, el panel queda viejo y se refresca solo.

Todo ocurre en el perfil del usuario y NADA pide administrador:

    panel            -> %APPDATA%\Adobe\CEP\extensions                    (Windows)
                        ~/Library/Application Support/Adobe/CEP/extensions  (macOS)
    PlayerDebugMode  -> HKCU\Software\Adobe\CSXS.<n>                      (Windows)
                        ~/Library/Preferences/com.adobe.CSXS.<n>.plist      (macOS)

CEP también lee una ubicación de sistema (Program Files / /Library), que sí requiere
elevación. La app nunca instala ahí, pero tiene que DETECTAR lo que haya: una copia
antigua puesta a mano declara el mismo ExtensionBundleId, y CEP acabaría cargando dos
paneles idénticos. Para ese único caso existe remove_system_install_elevated().
"""

import os
import platform
import shutil
import subprocess
import xml.etree.ElementTree as ET

from core.logger.logger_manager import logger
from core.utils.paths import get_bundled_importer_dir
from core.version import APP_VERSION
from PySide6.QtCore import QCoreApplication

# Identidad de la extensión. Es el ancla de toda la detección: el nombre de la carpeta
# da igual (CEP lee el manifiesto de dentro), y de hecho las instalaciones manuales
# antiguas usan "DowP Importer", con espacio, en vez del id.
BUNDLE_ID = "com.dowp.importer"

# Nombre de carpeta que usa la app al instalar. Coincidir con el bundle id es la
# convención de CEP y evita colisiones con otras extensiones.
INSTALL_FOLDER_NAME = BUNDLE_ID

# Versiones de CSXS a las que se les activa PlayerDebugMode. Adobe publica una nueva
# con cada release anual y cada aplicación lee la suya, así que se cubre un rango
# amplio por adelantado: son valores de cadena en HKCU, no cuestan nada, y evitan que
# el panel deje de aparecer cuando salga la siguiente versión de Premiere.
CSXS_VERSIONS = tuple(range(9, 25))

_IS_WINDOWS = platform.system() == "Windows"
_IS_MACOS = platform.system() == "Darwin"

# Archivos del repo que no tienen por qué acabar en la instalación del usuario.
# .debug abre puertos de depuración remota de CEF: útil desarrollando, ruido en una
# instalación normal.
_INSTALL_IGNORE = shutil.ignore_patterns(
    "*.md", ".debug", ".DS_Store", "__pycache__", "*.pyc", ".git*"
)


# ─────────────────────────────────────────────────────────────────────────
# Ubicaciones de CEP
# ─────────────────────────────────────────────────────────────────────────

def is_supported() -> bool:
    """CEP solo existe en Windows y macOS. En Linux no hay Adobe que integrar."""
    return _IS_WINDOWS or _IS_MACOS


def get_user_extensions_dir():
    """Carpeta de extensiones CEP del usuario actual. Escribible sin elevación.
    None en plataformas sin CEP."""
    if _IS_WINDOWS:
        base = os.environ.get("APPDATA") or os.path.expanduser("~/AppData/Roaming")
        return os.path.join(base, "Adobe", "CEP", "extensions")
    if _IS_MACOS:
        return os.path.expanduser("~/Library/Application Support/Adobe/CEP/extensions")
    return None


def get_system_extensions_dirs() -> list:
    """Carpetas de extensiones CEP de sistema. Requieren administrador para escribir;
    la app solo las lee, para detectar copias antiguas puestas a mano.

    En Windows hay dos porque las aplicaciones de Adobe de 32 y 64 bits no comparten
    Common Files, y una instalación manual antigua pudo acabar en cualquiera de las dos.
    """
    if _IS_WINDOWS:
        dirs = []
        roots = [
            os.environ.get("CommonProgramFiles(x86)"),
            os.environ.get("CommonProgramFiles"),
        ]
        # Respaldo por si las variables de Common Files no están definidas.
        for var in ("ProgramFiles(x86)", "ProgramFiles"):
            base = os.environ.get(var)
            if base:
                roots.append(os.path.join(base, "Common Files"))
        for root in roots:
            if not root:
                continue
            path = os.path.join(root, "Adobe", "CEP", "extensions")
            if path not in dirs:
                dirs.append(path)
        return dirs
    if _IS_MACOS:
        return ["/Library/Application Support/Adobe/CEP/extensions"]
    return []


def get_install_dir():
    """Ruta exacta donde la app instala el panel. None si la plataforma no tiene CEP."""
    user_dir = get_user_extensions_dir()
    return os.path.join(user_dir, INSTALL_FOLDER_NAME) if user_dir else None


# ─────────────────────────────────────────────────────────────────────────
# Lectura de manifiestos y detección
# ─────────────────────────────────────────────────────────────────────────

def _read_manifest(ext_dir: str):
    """Lee CSXS/manifest.xml de una carpeta de extensión y devuelve
    {'bundle_id': str, 'version': str}, o None si no es una extensión legible."""
    if not ext_dir:
        return None
    manifest = os.path.join(ext_dir, "CSXS", "manifest.xml")
    if not os.path.isfile(manifest):
        return None
    try:
        root = ET.parse(manifest).getroot()
        return {
            "bundle_id": (root.get("ExtensionBundleId") or "").strip(),
            "version": (root.get("ExtensionBundleVersion") or "").strip(),
        }
    except Exception as e:
        logger.debug(f"Importer: manifiesto ilegible en {manifest}: {e}")
        return None


def _is_writable(path: str) -> bool:
    """Comprueba escritura REAL creando y borrando un archivo de sondeo.

    No usa os.access(W_OK): en Windows ese solo mira el atributo de solo lectura e
    ignora las ACL, así que devuelve True para Program Files aunque escribir falle
    después con acceso denegado.

    Y tampoco usa tempfile: en Windows, _mkstemp_inner interpreta PermissionError como
    una colisión de nombres y reintenta mientras os.access(dir, W_OK) diga que sí --
    que es exactamente lo que miente aquí. Con TMP_MAX = 2.147.483.647 eso no es un
    reintento, es un cuelgue. Una sola llamada a os.open con O_EXCL da la respuesta
    verdadera y no reintenta nada."""
    if not os.path.isdir(path):
        return False
    probe = os.path.join(path, f".dowp_write_probe_{os.getpid()}")
    try:
        fd = os.open(probe, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        return False
    try:
        os.close(fd)
    finally:
        try:
            os.remove(probe)
        except OSError:
            pass
    return True


def _scan_extensions_dir(ext_root: str, scope: str) -> list:
    """Busca instalaciones de DowP Importer dentro de una carpeta de extensiones.

    Recorre subcarpetas y compara el ExtensionBundleId del manifiesto, NO el nombre de
    la carpeta: las instalaciones manuales antiguas se llaman "DowP Importer" y con una
    búsqueda por nombre pasarían desapercibidas justo en el caso que hay que detectar.
    """
    found = []
    if not ext_root or not os.path.isdir(ext_root):
        return found
    try:
        entries = sorted(os.listdir(ext_root))
    except OSError as e:
        logger.debug(f"Importer: no se pudo listar {ext_root}: {e}")
        return found

    for name in entries:
        ext_dir = os.path.join(ext_root, name)
        if not os.path.isdir(ext_dir):
            continue
        info = _read_manifest(ext_dir)
        if not info or info["bundle_id"].lower() != BUNDLE_ID.lower():
            continue
        found.append({
            "path": ext_dir,
            "folder": name,
            "version": info["version"] or "desconocida",
            "scope": scope,
            "writable": _is_writable(ext_dir),
        })
    return found


def find_installed() -> list:
    """Todas las instalaciones del panel presentes en el sistema: primero la del
    perfil del usuario, después las de sistema."""
    installs = _scan_extensions_dir(get_user_extensions_dir(), "user")
    for system_dir in get_system_extensions_dirs():
        installs.extend(_scan_extensions_dir(system_dir, "system"))
    return installs


def get_bundled_version() -> str:
    """Versión del panel que la app lleva dentro.

    Sale del manifiesto real que se va a copiar, no de APP_VERSION, para que un fallo
    de estampado en el build se vea aquí en vez de reportar una versión distinta de la
    que se instala. Si el manifiesto no se puede leer, cae a APP_VERSION."""
    info = _read_manifest(get_bundled_importer_dir())
    if info and info["version"]:
        return info["version"]
    logger.warning("Importer: no se pudo leer la versión del manifiesto incluido; se usa APP_VERSION")
    return APP_VERSION


def get_status() -> dict:
    """Estado completo para la página de Integraciones, ya masticado.

    state:
      'unsupported'   -> la plataforma no tiene CEP (Linux)
      'not_installed' -> no hay panel en el perfil del usuario
      'up_to_date'    -> instalado y coincide con el que lleva la app
      'outdated'      -> instalado pero con otra versión

    'system_installs' es independiente del estado: son copias antiguas en la ubicación
    de sistema, que hay que quitar con elevación y pueden convivir con cualquier estado.
    """
    bundled = get_bundled_version()
    if not is_supported():
        return {"supported": False, "state": "unsupported", "bundled_version": bundled,
                "user_install": None, "system_installs": [], "install_dir": None}

    installs = find_installed()
    user_install = next((i for i in installs if i["scope"] == "user"), None)
    system_installs = [i for i in installs if i["scope"] == "system"]

    if user_install is None:
        state = "not_installed"
    elif user_install["version"] == bundled:
        state = "up_to_date"
    else:
        state = "outdated"

    return {
        "supported": True,
        "state": state,
        "bundled_version": bundled,
        "user_install": user_install,
        "system_installs": system_installs,
        "install_dir": get_install_dir(),
    }


# ─────────────────────────────────────────────────────────────────────────
# PlayerDebugMode
# ─────────────────────────────────────────────────────────────────────────

def enable_player_debug_mode():
    """Activa PlayerDebugMode, sin lo cual CEP se niega a cargar extensiones sin firmar
    y el panel simplemente no aparece en el menú, sin ningún mensaje de error.

    Va en HKCU (Windows) y en las preferencias del usuario (macOS): no necesita
    administrador. El valor tiene que ser la CADENA "1"; con un DWORD, CEP lo ignora en
    silencio y el síntoma es idéntico a no haberlo puesto nunca."""
    if _IS_WINDOWS:
        import winreg
        done, failed = [], []
        for n in CSXS_VERSIONS:
            key_path = f"Software\\Adobe\\CSXS.{n}"
            try:
                with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                    winreg.SetValueEx(key, "PlayerDebugMode", 0, winreg.REG_SZ, "1")
                done.append(n)
            except OSError as e:
                failed.append(f"CSXS.{n}: {e}")
        if not done:
            return False, QCoreApplication.translate("importer_setup", "No se pudo activar el modo de depuración de CEP: ") + "; ".join(failed)
        logger.info(f"Importer: PlayerDebugMode activado en CSXS.{done[0]}-CSXS.{done[-1]}")
        return True, QCoreApplication.translate("importer_setup", "Modo de depuración de CEP activado ({0} versiones).").format(len(done))

    if _IS_MACOS:
        done, failed = [], []
        for n in CSXS_VERSIONS:
            try:
                subprocess.run(
                    ["defaults", "write", f"com.adobe.CSXS.{n}", "PlayerDebugMode", "-string", "1"],
                    check=True, capture_output=True, timeout=10,
                )
                done.append(n)
            except Exception as e:
                failed.append(f"CSXS.{n}: {e}")
        if not done:
            return False, QCoreApplication.translate("importer_setup", "No se pudo activar el modo de depuración de CEP: ") + "; ".join(failed)
        logger.info(f"Importer: PlayerDebugMode activado en com.adobe.CSXS.{done[0]}-{done[-1]}")
        return True, QCoreApplication.translate("importer_setup", "Modo de depuración de CEP activado ({0} versiones).").format(len(done))

    return False, QCoreApplication.translate("importer_setup", "Esta plataforma no usa extensiones CEP.")


# ─────────────────────────────────────────────────────────────────────────
# Instalar / desinstalar
# ─────────────────────────────────────────────────────────────────────────

def install():
    """Copia el panel incluido en la app a la carpeta de extensiones del usuario y
    activa PlayerDebugMode. Devuelve (ok, mensaje).

    La copia va a un directorio hermano y solo se intercambia al final, para que un
    fallo a media copia no deje al usuario sin el panel que ya tenía funcionando."""
    if not is_supported():
        return False, QCoreApplication.translate("importer_setup", "Esta plataforma no usa extensiones CEP.")

    source = get_bundled_importer_dir()
    if not _read_manifest(source):
        return False, QCoreApplication.translate("importer_setup", "No se encontró el panel incluido en la app ({0}).").format(source)

    target = get_install_dir()
    staging = target + ".new"
    backup = target + ".old"

    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(backup, ignore_errors=True)

        shutil.copytree(source, staging, ignore=_INSTALL_IGNORE)

        if os.path.exists(target):
            os.rename(target, backup)
        try:
            os.rename(staging, target)
        except OSError:
            # El intercambio falló: se devuelve el panel anterior a su sitio antes de
            # propagar el error, para no dejar al usuario peor de como estaba.
            if os.path.exists(backup) and not os.path.exists(target):
                os.rename(backup, target)
            raise
        shutil.rmtree(backup, ignore_errors=True)

    except Exception as e:
        shutil.rmtree(staging, ignore_errors=True)
        logger.error(f"Importer: fallo instalando el panel en {target}: {e}", exc_info=True)
        return False, QCoreApplication.translate("importer_setup", "No se pudo instalar el panel: {0}").format(e)

    version = get_bundled_version()
    logger.info(f"Importer: panel {version} instalado en {target}")

    debug_ok, debug_msg = enable_player_debug_mode()
    if not debug_ok:
        return True, QCoreApplication.translate(
            "importer_setup",
            "Panel {0} instalado, pero no se pudo activar el modo de "
            "depuración de CEP ({1}). El panel podría no aparecer."
        ).format(version, debug_msg)
    return True, QCoreApplication.translate("importer_setup", "Panel {0} instalado. Reinicia Adobe para verlo en el menú.").format(version)


def uninstall():
    """Elimina el panel del perfil del usuario. No toca las copias de sistema: para eso
    está remove_system_install_elevated()."""
    if not is_supported():
        return False, QCoreApplication.translate("importer_setup", "Esta plataforma no usa extensiones CEP.")

    removed = []
    for install_info in find_installed():
        if install_info["scope"] != "user":
            continue
        try:
            shutil.rmtree(install_info["path"])
            removed.append(install_info["path"])
        except Exception as e:
            logger.error(f"Importer: no se pudo eliminar {install_info['path']}: {e}")
            return False, QCoreApplication.translate("importer_setup", "No se pudo eliminar el panel: {0}").format(e)

    if not removed:
        return False, QCoreApplication.translate("importer_setup", "No hay ningún panel instalado en tu perfil de usuario.")
    logger.info(f"Importer: panel desinstalado de {removed}")
    return True, QCoreApplication.translate("importer_setup", "Panel desinstalado. Reinicia Adobe para que desaparezca del menú.")


def sync_if_installed() -> bool:
    """Reinstala el panel si el que hay quedó viejo respecto al que trae la app.

    Pensada para llamarse al arrancar, después de una actualización: quien ya tiene el
    panel puesto no debería tener que ir a Ajustes a pulsar un botón cada vez. Si no hay
    panel instalado no hace nada, porque instalarlo es siempre decisión del usuario."""
    if not is_supported():
        return False
    status = get_status()
    if status["state"] != "outdated":
        return False
    logger.info(f"Importer: panel {status['user_install']['version']} desactualizado "
                f"frente a {status['bundled_version']}; se refresca")
    ok, _msg = install()
    return ok


# ─────────────────────────────────────────────────────────────────────────
# Copias de sistema: el único caso de todo DowP que necesita elevación
# ─────────────────────────────────────────────────────────────────────────

def _validate_system_install_path(path: str) -> bool:
    """Barrera de seguridad antes de un borrado recursivo con privilegios elevados.

    Exige las tres cosas a la vez: que la ruta cuelgue de una carpeta de extensiones CEP
    de sistema conocida, que sea hija DIRECTA de ella, y que su manifiesto declare
    nuestro propio bundle id. Un borrado elevado con una ruta sin validar es la clase de
    error que se lleva por delante una carpeta del sistema."""
    if not path or not os.path.isdir(path):
        return False
    real = os.path.realpath(path)
    for system_dir in get_system_extensions_dirs():
        root = os.path.realpath(system_dir)
        if os.path.dirname(real) != root:
            continue
        info = _read_manifest(real)
        if info and info["bundle_id"].lower() == BUNDLE_ID.lower():
            return True
    return False


def get_elevated_removal_command(path: str) -> str:
    """Comando equivalente al borrado elevado, para quien prefiera hacerlo a mano en vez
    de pasar por el diálogo de permisos."""
    if _IS_WINDOWS:
        return f'Remove-Item -LiteralPath "{path}" -Recurse -Force'
    return f'sudo rm -rf "{path}"'


def remove_system_install_elevated(path: str):
    """Borra una copia antigua del panel de la ubicación de sistema, pidiendo permisos.

    Es la única operación de todo DowP que muestra un diálogo de administrador, y solo la
    ve quien instaló el panel a mano en su día. Una instalación nueva nunca llega aquí."""
    if not _validate_system_install_path(path):
        return False, QCoreApplication.translate("importer_setup", "La ruta no corresponde a una instalación de DowP Importer del sistema.")

    logger.info(f"Importer: solicitando permisos para eliminar la copia de sistema {path}")

    if _IS_WINDOWS:
        return _remove_elevated_windows(path)
    if _IS_MACOS:
        return _remove_elevated_macos(path)
    return False, QCoreApplication.translate("importer_setup", "Esta plataforma no usa extensiones CEP.")


def _remove_elevated_windows(path: str):
    """Relanza el borrado con el verbo 'runas', que es lo que dispara el diálogo de
    control de cuentas de usuario. Se espera al proceso y se comprueba que la carpeta
    desapareció de verdad, en vez de asumir que salió bien."""
    import ctypes
    from ctypes import wintypes

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("fMask", ctypes.c_ulong),
            ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", ctypes.c_void_p),
            ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD),
            ("hIcon", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    SEE_MASK_NOCLOSEPROCESS = 0x00000040
    SEE_MASK_NOASYNC = 0x00000100
    SW_HIDE = 0
    ERROR_CANCELLED = 1223

    ps_path = path.replace("'", "''")  # comilla simple escapada al estilo PowerShell
    params = (
        "-NoProfile -NonInteractive -WindowStyle Hidden -Command "
        f"\"Remove-Item -LiteralPath '{ps_path}' -Recurse -Force\""
    )

    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC
    info.lpVerb = "runas"
    info.lpFile = "powershell.exe"
    info.lpParameters = params
    info.nShow = SW_HIDE

    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        code = ctypes.windll.kernel32.GetLastError()
        if code == ERROR_CANCELLED:
            return False, QCoreApplication.translate("importer_setup", "Se canceló la solicitud de permisos de administrador.")
        return False, QCoreApplication.translate("importer_setup", "No se pudo solicitar permisos de administrador (error {0}).").format(code)

    try:
        ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, 120000)
        exit_code = wintypes.DWORD()
        ctypes.windll.kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(exit_code))
        rc = exit_code.value
    finally:
        ctypes.windll.kernel32.CloseHandle(info.hProcess)

    if os.path.exists(path):
        return False, QCoreApplication.translate("importer_setup", "La carpeta sigue ahí tras el intento de borrado (código {0}).").format(rc)
    logger.info(f"Importer: copia de sistema eliminada: {path}")
    return True, "Copia antigua eliminada. Reinicia Adobe."


def _remove_elevated_macos(path: str):
    """En macOS el diálogo de contraseña lo pone el propio sistema a través de osascript;
    no hace falta empaquetar un helper aparte."""
    escaped = path.replace("\\", "\\\\").replace('"', '\\"')
    script = f'do shell script "rm -rf \\"{escaped}\\"" with administrator privileges'
    try:
        subprocess.run(["osascript", "-e", script], check=True, capture_output=True, timeout=120)
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or b"").decode("utf-8", errors="ignore")
        if "-128" in stderr or "User canceled" in stderr:
            return False, QCoreApplication.translate("importer_setup", "Se canceló la solicitud de permisos de administrador.")
        return False, QCoreApplication.translate("importer_setup", "No se pudo eliminar la copia antigua: {0}").format(stderr.strip() or e)
    except Exception as e:
        return False, QCoreApplication.translate("importer_setup", "No se pudo eliminar la copia antigua: {0}").format(e)

    if os.path.exists(path):
        return False, QCoreApplication.translate("importer_setup", "La carpeta sigue ahí tras el intento de borrado.")
    logger.info(f"Importer: copia de sistema eliminada: {path}")
    return True, "Copia antigua eliminada. Reinicia Adobe."
