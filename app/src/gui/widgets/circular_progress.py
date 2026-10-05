# src/gui/widgets/circular_progress.py
"""Indicador de progreso circular pintado a mano (estilo Material/Google): un
anillo fino de fondo como pista, y un arco mas grueso que avanza con el
progreso real -- sustituye al boton "Actualizar" mientras dura la descarga
(gui/tabs/settings/settings_view.py), no lo superpone.
"""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

_TRACK_WIDTH = 2.5
_PROGRESS_WIDTH = 5.0
_TRACK_COLOR = "#3d3d3d"
_PROGRESS_COLOR = "#B9E640"


class CircularProgress(QWidget):
    def __init__(self, parent=None, diameter: int = 28):
        super().__init__(parent)
        self._value = 0  # 0-100
        self._diameter = diameter
        self.setFixedSize(diameter, diameter)

    def setValue(self, percent: int) -> None:
        self._value = max(0, min(100, percent))
        self.update()

    def value(self) -> int:
        return self._value

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        margin = max(_TRACK_WIDTH, _PROGRESS_WIDTH) / 2 + 1
        rect = QRectF(margin, margin, self._diameter - 2 * margin, self._diameter - 2 * margin)

        from gui.styles import get_theme_token
        track_pen = QPen(QColor(get_theme_token('pista_slider', _TRACK_COLOR)), _TRACK_WIDTH)
        track_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track_pen)
        painter.drawEllipse(rect)

        if self._value > 0:
            progress_pen = QPen(QColor(get_theme_token('acento_primario', _PROGRESS_COLOR)), _PROGRESS_WIDTH)
            progress_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(progress_pen)
            start_angle = 90 * 16  # las 12 en punto, Qt mide en 1/16 de grado
            span_angle = -int(self._value / 100 * 360 * 16)  # sentido horario
            painter.drawArc(rect, start_angle, span_angle)

        painter.end()
