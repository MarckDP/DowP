# src/core/updater/update_service.py
"""Workers en segundo plano que conectan el mecanismo real de actualizacion
(piezas 1-2: manifiesto firmado + diff + descarga) con la interfaz. Ninguno de
los dos bloquea el hilo de UI -- mismo patron que DependencyCheckWorker en
gui/splash_screen.py.
"""
from PySide6.QtCore import QThread, Signal

from core.logger.logger_manager import logger
from core.updater.downloader import download_update
from core.updater.update_checker import UpdateInfo, compute_diff
from core.version import UPDATE_REPO


class UpdateCheckWorker(QThread):
    """Consulta el release `latest` de UPDATE_REPO y calcula el diff contra la
    instalacion actual. Emite un UpdateInfo solo si hay algo que descargar --
    None para CUALQUIER otro caso (sin releases todavia, sin conexion, firma
    invalida, nada nuevo) porque hoy, sin ningun release publicado, "sin
    resultado" es el estado normal y no debe alarmar al usuario con un dialogo
    de error."""
    finished = Signal(object)  # UpdateInfo | None

    def __init__(self, install_dir=None, parent=None):
        super().__init__(parent)
        self._install_dir = install_dir  # None -> compute_diff usa sys.executable (frozen)

    def run(self):
        from core.utils.config_manager import get_config
        # Diferido: manifest_client arrastra Cryptodome (firma del manifiesto), que no
        # hace falta cargar al arrancar -- este módulo lo importa Ajustes al construirse.
        from core.updater.manifest_client import fetch_and_verify_manifest
        channel = get_config().get("update_channel", "stable")
        try:
            manifest = fetch_and_verify_manifest(UPDATE_REPO, channel=channel)
        except Exception as e:
            # Incluye ManifestVerificationError (firma invalida/manifiesto ausente),
            # errores de red y el 404 normal de "este repo todavia no tiene releases".
            logger.info(f"Updater: chequeo de actualizaciones sin resultado ({e}).")
            self.finished.emit(None)
            return

        try:
            info = compute_diff(manifest, install_dir=self._install_dir)
        except Exception as e:
            logger.error(f"Updater: fallo calculando el diff de actualizacion: {e}", exc_info=True)
            self.finished.emit(None)
            return

        self.finished.emit(info if info.available else None)


class UpdateDownloadWorker(QThread):
    """Descarga (download_update, pieza 2) los archivos de un UpdateInfo ya
    detectado. progress emite (bytes completados, bytes totales) en bytes de
    red -- mismo criterio que la pieza 2, no bytes descomprimidos."""
    progress = Signal(int, int)
    finished = Signal(bool, str)  # ok, mensaje de error (vacio si ok)

    def __init__(self, update_info: UpdateInfo, staging_dir: str, parent=None):
        super().__init__(parent)
        self.update_info = update_info
        self.staging_dir = staging_dir

    def run(self):
        try:
            result = download_update(self.update_info, self.staging_dir, progress_callback=self.progress.emit)
        except Exception as e:
            logger.error(f"Updater: fallo descargando la actualizacion: {e}", exc_info=True)
            self.finished.emit(False, str(e))
            return

        if result.ok:
            self.finished.emit(True, "")
        else:
            self.finished.emit(False, f"No se pudieron verificar {len(result.failed_files)} archivo(s).")
