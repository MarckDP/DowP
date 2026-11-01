# src/core/updater/launcher.py
"""Todo lo que necesita el lado de la APP PRINCIPAL para entregarle un swap
al helper (proceso aparte) y salir -- y lo que necesita el HELPER para
esperar a que la app vieja termine y comprobar si la nueva arranco bien.
Ambos lados viven en el mismo modulo porque comparten primitivas (esperar/
comprobar un PID, lanzar un proceso desacoplado) que no tiene sentido
duplicar.
"""
import ctypes
import os
import platform
import shutil
import subprocess
import sys
import time

from core.logger.logger_manager import logger
from core.updater.journal import STATUS_DONE, STATUS_ROLLED_BACK, clear_journal, journal_path, read_journal
from core.updater.update_checker import version_key
from core.version import APP_VERSION

HELPER_NAME_WINDOWS = "DowP_Updater.exe"
HELPER_NAME_POSIX = "DowP_Updater"

_WAIT_TIMEOUT = 0x00000102  # WAIT_TIMEOUT de winapi
_STILL_ACTIVE = 259


def helper_name() -> str:
    return HELPER_NAME_WINDOWS if platform.system() == "Windows" else HELPER_NAME_POSIX


def install_dir_from_executable(executable_path: str) -> str:
    """Dado sys.executable del proceso principal en marcha, devuelve la raiz
    que el updater debe tratar como "la instalacion" -- el mismo arbol que
    hashea tools/updater/publish.py al publicar.

    En Windows/Linux es simplemente la carpeta que contiene el ejecutable (el
    --onedir de PyInstaller, plano). En macOS NO es lo mismo: el onedir real
    queda partido entre Contents/Frameworks y Contents/Resources (con
    symlinks cruzados entre ambas -- ni siquiera Frameworks, con casi todo,
    tiene el 100%: _tcl_data/_tk_data son reales solo en Resources).
    Comprobado contra un bundle real: la unica raiz que cubre las dos sin
    ambiguedad, y que hash_tree() recorre completo sin duplicar nada (no
    sigue directorios symlink), es el .app entero -- no Contents/MacOS,
    que es donde vive sys.executable pero NO contiene los datos de la app."""
    parent = os.path.dirname(executable_path)
    if platform.system() == "Darwin":
        from core.updater.swap_executor import find_app_bundle_root
        bundle = find_app_bundle_root(parent)
        if bundle:
            return bundle
    return parent


def helper_path_in(install_dir: str) -> str:
    """Ruta real del binario del helper de swap dentro de `install_dir`.

    En Windows/Linux, install_dir ES la carpeta que contiene el helper
    directamente. En macOS, install_dir ahora es la raiz del .app (ver
    install_dir_from_executable) mientras que el helper compilado vive
    dentro de Contents/MacOS/, no suelto en la raiz del bundle."""
    if platform.system() == "Darwin" and install_dir.lower().endswith(".app"):
        return os.path.join(install_dir, "Contents", "MacOS", helper_name())
    return os.path.join(install_dir, helper_name())


def is_process_alive(pid: int) -> bool:
    """True si el proceso `pid` sigue vivo. En Windows distingue un PID
    reciclado por otro proceso de uno de verdad sigue corriendo, via el
    codigo de salida (STILL_ACTIVE) -- OpenProcess solo no basta, un PID
    zombie brevemente sigue abrible."""
    if platform.system() == "Windows":
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == _STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # existe, solo no es nuestro (no deberia pasar aqui, pero sigue vivo)


def wait_for_pid_exit(pid: int, timeout: float | None = None) -> bool:
    """Bloquea hasta que `pid` termina. Devuelve True si termino, False si se
    agoto `timeout` (None = sin limite).

    En Windows usa OpenProcess(SYNCHRONIZE) + WaitForSingleObject: se entera
    de cuando el proceso de verdad libero sus DLLs, no solo de que "el PID ya
    no aparece". En POSIX no hay equivalente para un proceso que no es hijo
    nuestro (el padre helper no es hijo de la app vieja), asi que se sondea
    is_process_alive() en un bucle corto."""
    if platform.system() == "Windows":
        SYNCHRONIZE = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not handle:
            return True  # ya no existe
        try:
            wait_ms = 0xFFFFFFFF if timeout is None else max(0, int(timeout * 1000))
            result = ctypes.windll.kernel32.WaitForSingleObject(handle, wait_ms)
            return result != _WAIT_TIMEOUT
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)

    deadline = None if timeout is None else time.monotonic() + timeout
    while is_process_alive(pid):
        if deadline is not None and time.monotonic() >= deadline:
            return False
        time.sleep(0.2)
    return True


def spawn_detached(exe_path: str, args: list) -> int:
    """Lanza exe_path totalmente desligado de este proceso -- tiene que seguir
    vivo aunque el padre termine (el padre esta a punto de salir a proposito,
    para soltar sus DLLs). Devuelve el PID del proceso lanzado."""
    if platform.system() == "Darwin" and exe_path.endswith(".app"):
        # 'open -n' desacopla y devuelve enseguida; no da el PID del proceso
        # real dentro del bundle. Limitacion aceptada: en macOS
        # is_process_alive() sobre este PID comprueba el proceso 'open', que
        # ya habra terminado -- ver ACTUALIZACIONES.md.
        proc = subprocess.Popen(["open", "-n", exe_path, "--args", *args], start_new_session=True)
        return proc.pid

    if platform.system() == "Windows":
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        proc = subprocess.Popen(
            [exe_path, *args],
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
    else:
        proc = subprocess.Popen([exe_path, *args], start_new_session=True, close_fds=True)
    return proc.pid


def hand_off_to_helper(state_dir: str, install_dir: str, own_pid: int, relaunch_exe: str) -> None:
    """Copia el helper del install dir a state_dir (para que no se auto-bloquee
    si el journal tambien lo reemplaza a el) y lo lanza con
    [journal_path, own_pid, relaunch_exe]. Quien llama es responsable de
    salir (sys.exit) inmediatamente despues -- seguir ejecutando con archivos
    a punto de moverse debajo es como se corrompe una instalacion."""
    helper_src = helper_path_in(install_dir)
    if not os.path.exists(helper_src):
        raise FileNotFoundError(f"No se encontro el helper de swap en {helper_src}")

    os.makedirs(state_dir, exist_ok=True)
    helper_run_copy = os.path.join(state_dir, helper_name())
    shutil.copy2(helper_src, helper_run_copy)
    if platform.system() != "Windows":
        os.chmod(helper_run_copy, 0o755)

    logger.info(f"Updater: entregando el swap a {helper_run_copy}, esperando a PID {own_pid}.")
    spawn_detached(helper_run_copy, [journal_path(state_dir), str(own_pid), relaunch_exe])


def resume_pending_swap_at(state_dir: str, install_dir: str) -> bool:
    """Version parametrizada, para poder probarla contra un directorio de
    instalacion falso sin necesitar un build congelado real."""
    journal = read_journal(state_dir)
    if journal is None or journal.get("status") in (STATUS_DONE, STATUS_ROLLED_BACK):
        return False

    # Si ya se instalo una version posterior con el instalador, aplicar esto la bajaria.
    target = journal.get("target_version")
    if target and version_key(APP_VERSION) > version_key(target):
        logger.warning(f"Updater: se descarta un swap a medias hacia {target}: ya esta instalada la {APP_VERSION}.")
        clear_journal(state_dir)
        return False

    logger.warning("Updater: se encontro un swap sin terminar (corte a mitad de camino) -- reanudando.")
    hand_off_to_helper(state_dir, install_dir, os.getpid(), journal["relaunch_exe"])
    return True


def resume_pending_swap() -> bool:
    """Se llama al principio de main.py, antes de crear la QApplication. En
    modo fuente (no congelado) no hay arbol --onedir real que gestionar, asi
    que no hace nada -- solo tiene efecto en una instalacion de verdad."""
    if not getattr(sys, "frozen", False):
        return False

    from core.utils.paths import get_updater_state_dir
    state_dir = get_updater_state_dir()
    install_dir = install_dir_from_executable(sys.executable)
    return resume_pending_swap_at(state_dir, install_dir)
