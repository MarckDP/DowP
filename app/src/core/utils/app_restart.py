# src/core/utils/app_restart.py
"""
Relanzado de DowP sobre sí mismo.
==================================
Hace falta para el cambio de idioma: el .qm se instala una sola vez al arrancar
(ver core/utils/i18n.py) y buena parte de los textos son constantes de módulo
resueltas con QCoreApplication.translate() en el import, así que cambiar de
idioma en caliente dejaría la UI a medias -- lo ya construido en el idioma viejo
y lo nuevo en el nuevo. Reiniciar es la única forma de que quede consistente.

Reutiliza spawn_detached() del updater (core/updater/launcher.py): ya resuelve
las tres plataformas -- DETACHED_PROCESS en Windows, 'open -n' para bundles .app
en macOS y start_new_session en Linux -- y el proceso nuevo tiene que sobrevivir
a la muerte del actual, igual que en el swap de actualización.
"""
import os
import platform
import sys

from core.logger.logger_manager import logger


def _relaunch_target() -> tuple[str, list]:
    """(ejecutable, args) con los que volver a arrancar esta misma instalación.

    - Empaquetado (PyInstaller): sys.executable ya ES DowP. En macOS se sube a
      la raíz del .app para que spawn_detached() use 'open -n' sobre el bundle
      en vez de ejecutar el binario suelto de Contents/MacOS.
    - Desde fuente: sys.executable es el intérprete, así que hay que pasarle el
      main.py de nuevo.
    """
    if getattr(sys, "frozen", False):
        exe = sys.executable
        if platform.system() == "Darwin":
            try:
                from core.updater.swap_executor import find_app_bundle_root
                bundle = find_app_bundle_root(os.path.dirname(exe))
                if bundle:
                    exe = bundle
            except Exception as e:
                logger.warning(f"AppRestart: no se pudo resolver el .app, se usa el binario suelto: {e}")
        return exe, list(sys.argv[1:])

    main_py = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    if not main_py or not os.path.isfile(main_py):
        # .../app/src/core/utils/app_restart.py -> .../app/main.py (cuatro niveles)
        app_dir = os.path.abspath(__file__)
        for _ in range(4):
            app_dir = os.path.dirname(app_dir)
        main_py = os.path.join(app_dir, "main.py")
    return sys.executable, [main_py, *sys.argv[1:]]


def restart_app() -> bool:
    """Arranca una instancia nueva, desligada de esta. Devuelve True si salió.

    NO cierra la app: quien llama decide cuándo hacerlo (normalmente
    QApplication.quit() justo después), igual que el flujo del updater.
    """
    try:
        from core.updater.launcher import spawn_detached
        exe, args = _relaunch_target()
        if not exe or not os.path.exists(exe):
            logger.error(f"AppRestart: no existe el ejecutable para relanzar: {exe!r}")
            return False
        pid = spawn_detached(exe, args)
        logger.info(f"AppRestart: instancia nueva lanzada (pid {pid}) desde {exe!r}")
        return True
    except Exception as e:
        logger.error(f"AppRestart: no se pudo relanzar DowP: {e}")
        return False
