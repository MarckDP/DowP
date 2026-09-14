# updater_helper.py
"""Helper de swap: el segundo ejecutable que aplica una actualizacion sobre la
instalacion real. Corre DESACOPLADO de DowP.exe a proposito -- un proceso no
puede sobrescribir su propio .exe ni las DLLs que tiene cargadas, y DowP.exe
cambia en casi todos los releases. Se compila aparte (ver
build_cross_platform.py: build_updater_helper()), sin PySide6 ni ninguna
dependencia pesada -- solo stdlib + core.updater/.logger/.utils.paths.

Uso:
    updater_helper.py <journal_path> <wait_pid> <relaunch_exe>

No se invoca a mano: lo lanza core.updater.launcher.hand_off_to_helper()
desde la app principal (o desde ella misma, al detectar al arrancar un
journal que quedo a medias por un corte de luz).
"""
import os
import sys
import time

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from core.logger.logger_manager import logger  # noqa: E402
from core.updater import journal as journal_mod  # noqa: E402
from core.updater import launcher, swap_executor  # noqa: E402

STARTUP_CHECK_SECONDS = 8
WAIT_OLD_PROCESS_TIMEOUT = 60


def main() -> int:
    if len(sys.argv) != 4:
        logger.error("Updater helper: uso incorrecto, se esperaban 3 argumentos.")
        return 2

    journal_file, wait_pid_str, relaunch_exe = sys.argv[1], sys.argv[2], sys.argv[3]
    wait_pid = int(wait_pid_str)
    state_dir = os.path.dirname(os.path.abspath(journal_file))

    logger.info(f"Updater helper: esperando a que termine el PID {wait_pid}...")
    if not launcher.wait_for_pid_exit(wait_pid, timeout=WAIT_OLD_PROCESS_TIMEOUT):
        logger.warning(
            f"Updater helper: el PID {wait_pid} sigue vivo tras {WAIT_OLD_PROCESS_TIMEOUT}s, "
            "se continua de todos modos -- si de verdad tiene los archivos abiertos, "
            "el swap fallara con un error claro y se hara rollback."
        )

    journal = journal_mod.read_journal(state_dir)
    if journal is None:
        logger.error(f"Updater helper: no hay journal en {state_dir}, nada que hacer.")
        return 1

    applied = False
    try:
        swap_executor.apply_journal(journal, state_dir)
        applied = True
    except Exception as e:
        logger.error(f"Updater helper: fallo aplicando el swap: {e}", exc_info=True)
        try:
            swap_executor.rollback_journal(journal, state_dir)
        except Exception as rollback_error:
            # El journal NO se borra: queda como evidencia para diagnostico manual,
            # la instalacion puede haber quedado en un estado inconsistente de verdad.
            logger.critical(
                f"Updater helper: el rollback tambien fallo: {rollback_error}", exc_info=True
            )
            return 1

    logger.info(f"Updater helper: relanzando {relaunch_exe}...")
    new_pid = launcher.spawn_detached(relaunch_exe, [])

    if applied:
        time.sleep(STARTUP_CHECK_SECONDS)
        if launcher.is_process_alive(new_pid):
            logger.info("Updater helper: la nueva version sigue viva -- swap confirmado.")
            swap_executor.purge_backups(state_dir)
            swap_executor.purge_staging(journal)
            journal_mod.clear_journal(state_dir)
            return 0

        logger.error(
            "Updater helper: la nueva version no sigue viva tras el arranque -- "
            "asumiendo fallo de arranque, haciendo rollback."
        )
        try:
            swap_executor.rollback_journal(journal, state_dir)
        except Exception as rollback_error:
            logger.critical(
                f"Updater helper: el rollback tras fallo de arranque tambien fallo: {rollback_error}",
                exc_info=True,
            )
            return 1
        logger.info(f"Updater helper: relanzando la version anterior restaurada ({relaunch_exe})...")
        launcher.spawn_detached(relaunch_exe, [])
        return 1

    return 1  # se aplico rollback por un fallo durante apply_journal; ya se relanzo arriba


if __name__ == "__main__":
    sys.exit(main())
