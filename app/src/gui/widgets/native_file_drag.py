# src/gui/widgets/native_file_drag.py
from gui.styles import theme_radius
from PySide6.QtCore import Qt, QMimeData, QUrl, QEvent, QRectF
from PySide6.QtGui import QDrag, QPixmap, QPainter, QColor, QFont, QFontMetrics
from PySide6.QtWidgets import QApplication, QPushButton


def _build_badge_pixmap(text: str) -> QPixmap:
    """Pastilla oscura con `text` que acompaña al cursor durante el arrastre, para que
    se vea cuántos archivos van cuando son varios (el cursor nativo no lo indica)."""
    font = QFont()
    font.setPointSize(9)
    font.setBold(True)
    width = QFontMetrics(font).horizontalAdvance(text) + 22
    height = 24
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(0, 0, 0, 205))
    painter.setPen(QColor(255, 255, 255, 60))
    painter.drawRoundedRect(QRectF(0.5, 0.5, width - 1, height - 1), theme_radius(6), theme_radius(6))
    painter.setPen(QColor("#ffffff"))
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, text)
    painter.end()
    return pixmap


def start_native_file_drag(source_widget, file_paths: list, badge_text: str = ""):
    """Inicia un QDrag nativo del SO ofreciendo file_paths como URLs locales, con source_widget
    como origen del gesto (p.ej. para arrastrar uno o varios subclips ya cortados hacia el
    Explorador u otra aplicación). badge_text, si se pasa, dibuja una pastilla junto al cursor
    (p.ej. "12 archivos"). Al finalizar, limpia manualmente el estado ':hover' de
    source_widget, ya que Qt no dispara un evento Leave tras un QDrag.exec nativo."""
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(p) for p in file_paths])
    drag = QDrag(source_widget)
    drag.setMimeData(mime)
    if badge_text:
        try:
            drag.setPixmap(_build_badge_pixmap(badge_text))
        except Exception:
            pass
    drag.exec(Qt.CopyAction)
    QApplication.sendEvent(source_widget, QEvent(QEvent.Leave))
    source_widget.update()


class DraggableFilesButton(QPushButton):
    """
    Botón que además se puede arrastrar como si fueran archivos del explorador: al
    superar el umbral de arrastre de Qt, en vez de completar el clic pide las rutas a
    `files_provider()` e inicia un QDrag nativo con ellas.

    Mismo gesto que el botón de corte físico del diálogo de subclips (ver
    dialogs/subclip_dialog.py::_DraggableCutButton), reunido aquí para poder usarlo
    también en las opciones de salida de Proceso Avanzado en modo SOLO, donde no hay
    una tarjeta que arrastrar.
    """

    def __init__(self, files_provider, parent=None):
        super().__init__(parent)
        self._files_provider = files_provider
        self._press_pos = None

    def set_files_provider(self, files_provider):
        self._files_provider = files_provider

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (event.buttons() & Qt.LeftButton) and self._press_pos is not None and self.isEnabled():
            delta = event.position().toPoint() - self._press_pos
            if delta.manhattanLength() >= QApplication.startDragDistance():
                # Se limpia ANTES de arrastrar: el QDrag abre un bucle de eventos
                # anidado y el gesto no debe poder relanzarse desde dentro de él.
                self._press_pos = None
                self.setDown(False)
                files = list(self._files_provider() or []) if self._files_provider else []
                if files:
                    badge = "" if len(files) == 1 else self.tr("{0} archivos").format(len(files))
                    start_native_file_drag(self, files, badge_text=badge)
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._press_pos = None
        super().mouseReleaseEvent(event)
