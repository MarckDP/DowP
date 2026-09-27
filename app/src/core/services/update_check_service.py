# src/core/services/update_check_service.py
"""Chequeo de actualizaciones desacoplado de la pestaña de Ajustes. Antes vivia
adentro de SettingsTab, pero eso obligaba a construir las 11 paginas de Ajustes
(dependencias, modelos IA, cache, adaptadores GPU...) en cada arranque solo para
poder chequear actualizaciones y prender el badge de la esquina -- aunque el
usuario nunca abriera Ajustes. Este servicio es el unico dueño real del estado
de chequeo; SettingsTab (que ahora se construye recien, ver
MainWindow.settings_overlay en gui/main_window.py) lo consulta al armarse para
reflejar un resultado que ya haya llegado, y delega en el los clics de "Buscar
actualizaciones"."""
from PySide6.QtCore import QObject, Signal

from core.updater.update_service import UpdateCheckWorker


class UpdateCheckService(QObject):
    """Singleton. Mismos estados que antes tenia SettingsTab._update_state:
    "idle" | "checking" | "available" | "full_install"."""

    update_status_changed = Signal(bool)  # True = hay actualizacion pendiente (para el badge)
    check_finished = Signal(object)  # UpdateInfo | None -- para quien tenga la UI abierta

    _instance = None

    @classmethod
    def get_instance(cls) -> "UpdateCheckService":
        if cls._instance is None:
            cls._instance = UpdateCheckService()
        return cls._instance

    def __init__(self):
        super().__init__()
        self.update_info = None
        self.state = "idle"
        self._worker = None

    def start_check(self):
        """No-op en modo fuente (igual que antes) y si ya hay un chequeo en
        curso -- llamar de nuevo mientras "checking" no hace nada."""
        import sys
        if not getattr(sys, "frozen", False):
            return
        if self.state not in ("idle",):
            return
        self.state = "checking"
        self._worker = UpdateCheckWorker()
        self._worker.finished.connect(self._on_check_finished)
        self._worker.start()

    def _on_check_finished(self, update_info):
        self.update_info = update_info
        if update_info is None:
            self.state = "idle"
            self.update_status_changed.emit(False)
        elif update_info.must_full_install:
            self.state = "full_install"
            self.update_status_changed.emit(True)
        else:
            self.state = "available"
            self.update_status_changed.emit(True)
        self.check_finished.emit(update_info)
