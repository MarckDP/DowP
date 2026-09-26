# src/gui/widgets/screen_color_picker.py
from PySide6.QtCore import Qt, QObject, QPoint, QRect, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget


class ScreenColorPicker(QObject):
    """Cuentagotas de pantalla completa: congela una captura de cada monitor, la muestra
    a pantalla completa con cursor en cruz y una lupa del píxel bajo el cursor, y devuelve
    el color con un clic. Esc o clic derecho cancelan.

    Se trabaja sobre la captura congelada (no en vivo) para que la lupa no se capture a
    sí misma y para que el color sea el que el usuario ve, sin parpadeos.

    `host` debe ser la ventana modal que lo abre: los overlays se crean como hijos suyos,
    porque una ventana modal bloquea la entrada a cualquier ventana que no descienda de
    ella. En macOS la captura requiere el permiso de Grabación de pantalla; sin él el
    sistema devuelve solo el fondo de escritorio y las ventanas propias."""

    picked = Signal(QColor)
    cancelled = Signal()

    def __init__(self, host: QWidget):
        super().__init__(host)
        self._host = host
        self._overlays = []

    def start(self):
        # Ocultar el diálogo con opacidad (no con hide(): ocultar un QDialog dentro de
        # exec() termina su bucle y lo cierra) para que no salga en la captura.
        self._host_opacity = self._host.windowOpacity()
        self._host.setWindowOpacity(0.0)
        # Margen para que el compositor (DWM en Windows) redibuje sin el diálogo antes
        # de capturar; capturando en el acto a veces el diálogo todavía salía.
        QTimer.singleShot(150, self._grab_and_show)

    def _grab_and_show(self):
        try:
            for screen in QGuiApplication.screens():
                shot = screen.grabWindow(0)
                if shot.isNull():
                    continue
                overlay = _PickerOverlay(self._host, screen, shot)
                overlay.color_clicked.connect(self._finish_picked)
                overlay.cancel_requested.connect(self._finish_cancelled)
                self._overlays.append(overlay)
        finally:
            self._host.setWindowOpacity(self._host_opacity)
        if not self._overlays:
            self._finish_cancelled()
            return
        for overlay in self._overlays:
            overlay.showFullScreen()
        # El overlay bajo el cursor recibe el foco para que Esc funcione de entrada.
        under = next((o for o in self._overlays if o.geometry().contains(QCursor.pos())), self._overlays[0])
        under.activateWindow()
        under.setFocus()

    def _close_overlays(self):
        for overlay in self._overlays:
            overlay.close()
            overlay.deleteLater()
        self._overlays = []

    def _finish_picked(self, color: QColor):
        self._close_overlays()
        self.picked.emit(color)

    def _finish_cancelled(self):
        self._close_overlays()
        self.cancelled.emit()


class _PickerOverlay(QWidget):
    color_clicked = Signal(QColor)
    cancel_requested = Signal()

    ZOOM_PIXELS = 11      # píxeles de la captura que muestra la lupa (impar: hay un centro)
    ZOOM_SCALE = 10       # cada píxel se dibuja de 10x10
    OFFSET = 22           # distancia de la lupa al cursor

    def __init__(self, host, screen, shot):
        super().__init__(host, Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setGeometry(screen.geometry())
        self.setScreen(screen)
        self._shot = shot
        self._image = shot.toImage()
        self._dpr = shot.devicePixelRatio() or 1.0
        # grabWindow devuelve la captura en píxeles físicos; si la escala del monitor no
        # quedó registrada en el pixmap, se deduce del tamaño real contra el lógico.
        if self._dpr == 1.0 and screen.geometry().width() > 0:
            self._dpr = self._image.width() / screen.geometry().width()
        self._cursor = self.mapFromGlobal(QCursor.pos())

    # -- Muestreo -----------------------------------------------------------
    def _pixel_at(self, pos: QPoint) -> QPoint:
        x = min(max(int(pos.x() * self._dpr), 0), self._image.width() - 1)
        y = min(max(int(pos.y() * self._dpr), 0), self._image.height() - 1)
        return QPoint(x, y)

    def _color_at(self, pos: QPoint) -> QColor:
        p = self._pixel_at(pos)
        return QColor(self._image.pixel(p.x(), p.y()))

    # -- Pintado --------------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self._shot)

        n, scale = self.ZOOM_PIXELS, self.ZOOM_SCALE
        size = n * scale
        label_h = 22
        center = self._pixel_at(self._cursor)
        src = QRect(center.x() - n // 2, center.y() - n // 2, n, n)

        # Lupa abajo-derecha del cursor, o del otro lado si no entra en pantalla.
        x = self._cursor.x() + self.OFFSET
        y = self._cursor.y() + self.OFFSET
        if x + size > self.width():
            x = self._cursor.x() - self.OFFSET - size
        if y + size + label_h > self.height():
            y = self._cursor.y() - self.OFFSET - size - label_h
        box = QRect(x, y, size, size)

        painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
        painter.fillRect(box, QColor("#000000"))
        painter.drawImage(box, self._image, src)

        # Recuadro del píxel central: doble trazo para verse sobre cualquier color.
        cx = x + (n // 2) * scale
        cy = y + (n // 2) * scale
        painter.setPen(QPen(QColor("#000000"), 3))
        painter.drawRect(cx, cy, scale, scale)
        painter.setPen(QPen(QColor("#ffffff"), 1))
        painter.drawRect(cx, cy, scale, scale)

        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.drawRect(box)

        # Muestra + código del color bajo el cursor.
        color = self._color_at(self._cursor)
        label = QRect(x, y + size, size, label_h)
        painter.fillRect(label, QColor(20, 20, 20, 235))
        painter.fillRect(QRect(label.x() + 5, label.y() + 5, 12, 12), color)
        painter.setPen(QColor("#ffffff"))
        font = QFont(self.font())
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(label.adjusted(22, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, color.name().upper())
        painter.end()

    # -- Interacción ---------------------------------------------------------
    def mouseMoveEvent(self, event):
        self._cursor = event.position().toPoint()
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.color_clicked.emit(self._color_at(event.position().toPoint()))
        elif event.button() == Qt.RightButton:
            self.cancel_requested.emit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.cancel_requested.emit()
            return
        # Flechas: mover el cursor de a un píxel lógico para afinar la elección.
        step = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0), Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1)}.get(event.key())
        if step:
            QCursor.setPos(QCursor.pos() + QPoint(*step))
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.color_clicked.emit(self._color_at(self._cursor))
            return
        super().keyPressEvent(event)
