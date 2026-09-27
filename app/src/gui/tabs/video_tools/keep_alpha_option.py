# src/gui/tabs/video_tools/keep_alpha_option.py
"""Casilla "Conservar transparencia" + línea de estado, compartida por Comprimir,
Convertir, Edición y Avanzado (ver core/tabs/video_tools/alpha_policy.py).

Se muestra cuando el archivo seleccionado trae transparencia O cuando alguno de la cola
la trae (ver set_availability): así el valor que se aplica al lote siempre está a la
vista. Viene marcada por defecto -- perder la transparencia sin querer es peor que
conservarla.

Mientras está "activa" (visible y marcada, ver is_active) los paneles filtran sus listas
para ofrecer solo códecs/contenedores que la conservan, y fuerzan el motor a CPU (ningún
encoder por GPU de ffmpeg guarda alfa)."""
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QCheckBox, QLabel

from gui.styles import get_theme_token


class KeepAlphaOption(QWidget):
    toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._available = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.checkbox = QCheckBox(self.tr("Conservar transparencia"), self)
        self.checkbox.setChecked(True)
        self.checkbox.setCursor(Qt.PointingHandCursor)
        self.checkbox.setToolTip(self.tr(
            "Este archivo tiene transparencia (canal alfa). Marcada, DowP elige un formato que "
            "la conserve; desmarcada, la descarta."))
        self.checkbox.toggled.connect(self.toggled.emit)
        layout.addWidget(self.checkbox)
        self.lbl_status = QLabel("", self)
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)
        # Aviso de cola mezclada (archivos con y sin transparencia).
        self.lbl_note = QLabel("", self)
        self.lbl_note.setWordWrap(True)
        self.lbl_note.setVisible(False)
        layout.addWidget(self.lbl_note)
        self.setVisible(False)

    def is_checked(self) -> bool:
        return self.checkbox.isChecked()

    def is_available(self) -> bool:
        """Hay transparencia en juego: el archivo seleccionado o alguno de la cola."""
        return self._available

    def is_active(self) -> bool:
        """Hay transparencia en juego (archivo seleccionado o cola) y se quiere conservar."""
        return self._available and self.checkbox.isChecked()

    def set_availability(self, selected_has_alpha: bool, queue_with_alpha: int = 0):
        self._available = bool(selected_has_alpha or queue_with_alpha > 0)
        self.setVisible(self._available)

    def set_source_has_alpha(self, has_alpha: bool):
        self.set_availability(has_alpha)

    def set_status(self, text: str, severity: str = "ok"):
        """severity: "ok" (se conserva), "warning" (se pierde sin quererlo), "muted"."""
        self._set_label(self.lbl_status, text, severity)

    def set_queue_mix(self, with_alpha: int, without_alpha: int, per_file_text: str | None = None):
        """Avisa si la cola mezcla archivos con y sin transparencia. `per_file_text`: para
        los modos que deciden por archivo (Comprimir y Edición en Rápido); si no se pasa,
        los ajustes se aplican a todos por igual."""
        if with_alpha > 0 and without_alpha > 0 and self.checkbox.isChecked():
            text = per_file_text or self.tr(
                "La cola mezcla archivos con transparencia ({0}) y sin ella ({1}): estos "
                "ajustes se aplican a todos por igual.")
            self._set_label(self.lbl_note, text.format(with_alpha, without_alpha), "muted")
        else:
            self._set_label(self.lbl_note, "", "muted")

    def _set_label(self, label: QLabel, text: str, severity: str):
        # Mismos tokens de estado que los mensajes de Avanzado (_SEVERITY_TOKENS).
        colors = {
            "ok": get_theme_token("estado_exito", "#1DC038"),
            "warning": get_theme_token("estado_aviso", "#E6A23C"),
            "muted": get_theme_token("texto_secundario", "#888888"),
        }
        label.setStyleSheet(f"color: {colors.get(severity, colors['muted'])}; font-size: 11px;")
        label.setText(text)
        label.setVisible(bool(text))
        self._fit_heights()

    def _fit_heights(self):
        """Estos paneles viven dentro de un QStackedWidget (Rápido/Manual), que no
        propaga heightForWidth: sin esto un aviso de 2-3 líneas quedaba recortado a la
        altura de una sola. Se fija como mínimo el alto que el texto necesita al ancho
        real disponible.

        Ese ancho es el de ESTE widget (las etiquetas lo ocupan entero, sin márgenes), no
        el de cada etiqueta: durante resizeEvent las etiquetas todavía tienen el ancho
        anterior, y si el panel se había mostrado angosto (al acomodarse la ventana) el
        texto "creía" ocupar muchas líneas y dejaba un hueco grande que nunca se achicaba."""
        width = self.contentsRect().width()
        for label in (self.lbl_status, self.lbl_note):
            # heightForWidth() nunca devuelve menos que el mínimo ya fijado: sin soltarlo
            # antes, un alto grande calculado una vez quedaba pegado para siempre.
            label.setMinimumHeight(0)
            if width > 0 and label.text():
                label.setMinimumHeight(label.heightForWidth(width))
            else:
                label.setMinimumHeight(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_heights()
