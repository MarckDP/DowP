# src/gui/widgets/send_state_button.py
from PySide6.QtCore import QObject, QTimer


class SendButtonState(QObject):
    """
    Gestiona el estado visual temporal de un botón de envío/acción asíncrona:
    deshabilita el botón y anima puntos suspensivos mientras dura la operación
    ("Enviando", "Enviando.", "Enviando..", "Enviando..."), y al finalizar
    muestra brevemente "Éxito" o "Error" antes de restaurar el estado normal
    del botón mediante `restore_callback`.
    """

    def __init__(self, button, restore_callback=None, parent=None):
        super().__init__(parent or button)
        self.button = button
        self.restore_callback = restore_callback

        self._dots_timer = QTimer(self)
        self._dots_timer.setInterval(400)
        self._dots_timer.timeout.connect(self._tick_dots)
        self._dots_count = 0
        self._base_label = "Enviando"

        self._restore_timer = QTimer(self)
        self._restore_timer.setSingleShot(True)
        self._restore_timer.timeout.connect(self._restore)

    def is_busy(self) -> bool:
        return self._dots_timer.isActive()

    def start(self, label: str = "Enviando"):
        """Inicia la animación de espera y deshabilita el botón."""
        self._restore_timer.stop()
        self._base_label = label
        self._dots_count = 0
        self.button.setEnabled(False)
        self.button.setText(self._base_label)
        self._dots_timer.start()

    def _tick_dots(self):
        self._dots_count = (self._dots_count + 1) % 4
        self.button.setText(self._base_label + "." * self._dots_count)

    def finish(self, success: bool, message: str = None, hold_ms: int = 1800):
        """Detiene la animación y muestra el resultado final por `hold_ms` antes de restaurar."""
        self._dots_timer.stop()
        text = message if message else (self.tr("Éxito") if success else "Error")
        self.button.setText(text)
        self._restore_timer.start(hold_ms)

    def _restore(self):
        self.button.setEnabled(True)
        if self.restore_callback:
            self.restore_callback()
