# src/gui/widgets/engine_badge.py
from PySide6.QtWidgets import QPushButton
from PySide6.QtCore import Qt, Signal


class EngineBadge(QPushButton):
    """Badge clickeable "GPU Acelerado" (verde) / "CPU" (gris) - mismo lenguaje visual que
    el badge de motor de AdvancedRecodePanel (lbl_video_engine/_update_engine_label), pero
    extraído a un widget reutilizable porque Comprimir también lo necesita (Rápido y
    Manual, cada uno con su propio codec elegido).

    No decide nada de encoders por sí solo: solo refleja el estado que le pasan
    (`set_state`) y avisa con `toggled_force_cpu` cuando el usuario hace clic para forzar
    CPU o volver a hardware - la resolución real del encoder la hace quien lo usa."""

    toggled_force_cpu = Signal(bool)

    def __init__(self, parent=None):
        super().__init__("", parent)
        self.setCursor(Qt.PointingHandCursor)
        self._force_cpu = False
        self.clicked.connect(self._on_clicked)

    def _on_clicked(self):
        if not self.isEnabled():
            return  # sin hardware disponible para este codec, no hay nada que alternar
        self._force_cpu = not self._force_cpu
        self.toggled_force_cpu.emit(self._force_cpu)

    def set_state(self, has_hw: bool, force_cpu: bool, locked_reason: str | None = None):
        """`locked_reason`: el motor está obligado a CPU por algo ajeno a la elección del
        usuario (ej. conservar transparencia: ningún encoder por GPU guarda alfa). Se
        muestra "CPU" bloqueado con ese motivo de tooltip, sin tocar su preferencia."""
        self._force_cpu = force_cpu
        active_hw = has_hw and not force_cpu and not locked_reason

        if active_hw:
            self.setText(self.tr("GPU Acelerado"))
            self.setStyleSheet("""
                QPushButton {
                    background-color: rgba(185, 230, 64, 0.15);
                    color: #B9E640;
                    border: 1px solid rgba(185, 230, 64, 0.35);
                    border-radius: 4px;
                    padding: 2px 8px;
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: rgba(185, 230, 64, 0.25); }
            """)
            self.setToolTip(self.tr("Clic para usar codificación por CPU"))
        else:
            self.setText(self.tr("CPU"))
            self.setStyleSheet("""
                QPushButton {
                    background-color: rgba(255, 255, 255, 0.08);
                    color: #aaaaaa;
                    border: 1px solid rgba(255, 255, 255, 0.15);
                    border-radius: 4px;
                    padding: 2px 8px;
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: rgba(255, 255, 255, 0.15); }
            """)
            self.setToolTip(locked_reason or (self.tr("Clic para usar aceleración por GPU") if has_hw else ""))

        self.setEnabled(has_hw and not locked_reason)
