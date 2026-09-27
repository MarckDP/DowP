# src/gui/widgets/resettable_splitter.py
"""QSplitter para paneles ajustables por el usuario: los tiradores muestran una marca
discreta (resaltada al pasar el mouse, para que se note que se arrastran) y un doble
clic en cualquiera de ellos pide volver a la distribución por defecto (quien lo use
conecta `reset_requested`)."""
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QSplitter, QSplitterHandle

from gui.styles import get_theme_token


class _GripHandle(QSplitterHandle):
    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self.setAttribute(Qt.WA_Hover, True)
        self.setToolTip(self.tr("Arrastra para ajustar · doble clic para restablecer"))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        hovered = self.underMouse()
        color = QColor(get_theme_token("acento_primario", "#B9E640") if hovered
                       else get_theme_token("borde_normal", "#3a3a3a"))
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        w, h = self.width(), self.height()
        if self.orientation() == Qt.Horizontal:
            length = h * 0.9 if hovered else min(40.0, h * 0.3)
            painter.drawRoundedRect(QRectF((w - 2) / 2, (h - length) / 2, 2, length), 1, 1)
        else:
            length = w * 0.9 if hovered else min(40.0, w * 0.3)
            painter.drawRoundedRect(QRectF((w - length) / 2, (h - 2) / 2, length, 2), 1, 1)
        painter.end()

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.splitter().reset_requested.emit()
            return
        super().mouseDoubleClickEvent(event)


class ResettableSplitter(QSplitter):
    reset_requested = Signal()

    def __init__(self, orientation=Qt.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.setHandleWidth(8)
        self.setChildrenCollapsible(False)

    def createHandle(self):
        return _GripHandle(self.orientation(), self)
