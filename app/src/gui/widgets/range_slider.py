# src/gui/widgets/range_slider.py
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor, QBrush, QPen
from PySide6.QtCore import Qt, Signal, QRect
from gui.styles import get_theme_token

class RangeSlider(QWidget):
    range_changed = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(40)
        self._minimum = 0
        self._maximum = 100
        self._start_val = 0
        self._end_val = 100
        self._handle_radius = 9
        self._track_height = 6
        self._active_handle = None   # 'start' | 'end' | 'range'
        self._drag_offset_start = 0  # Para arrastre de rango completo
        self._drag_offset_end = 0

    def setMinimum(self, val):
        self._minimum = val
        self.update()

    def setMaximum(self, val):
        self._maximum = max(val, 1)
        self._end_val = self._maximum
        self.update()

    def set_values(self, start, end):
        """Establece ambos valores programáticamente."""
        self._start_val = max(self._minimum, min(start, self._maximum))
        self._end_val   = max(self._minimum, min(end,   self._maximum))
        self.update()
        self.range_changed.emit(self._start_val, self._end_val)

    def set_playhead(self, val):
        """Mueve la línea de reproducción independiente."""
        if val is None:
            self._playhead_val = None
        else:
            self._playhead_val = max(self._minimum, min(int(val), self._maximum))
        self.update()

    def get_values(self):
        return self._start_val, self._end_val

    # ──────────────────────────────────────────────
    # PAINT
    # ──────────────────────────────────────────────
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        width  = self.width()
        height = self.height()
        cy = height // 2

        track_rect = QRect(
            self._handle_radius,
            cy - self._track_height // 2,
            width - 2 * self._handle_radius,
            self._track_height,
        )

        # Background track
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(get_theme_token('pista_slider', '#3E3E3E'))))
        painter.drawRoundedRect(track_rect, 3, 3)

        x_start = self._val_to_x(self._start_val)
        x_end   = self._val_to_x(self._end_val)

        # Active range track
        active_rect = QRect(
            x_start,
            cy - self._track_height // 2,
            x_end - x_start,
            self._track_height,
        )
        painter.setBrush(QBrush(QColor(get_theme_token('estado_exito', '#4CAF50'))))
        painter.drawRoundedRect(active_rect, 3, 3)

        # Handles
        painter.setBrush(QBrush(QColor("#FFFFFF")))
        painter.setPen(QPen(QColor(get_theme_token('estado_exito', '#4CAF50')), 2))
        r = self._handle_radius
        painter.drawEllipse(x_start - r, cy - r, r * 2, r * 2)
        painter.drawEllipse(x_end   - r, cy - r, r * 2, r * 2)

        # Playhead (cabeza de reproducción independiente)
        if hasattr(self, '_playhead_val') and self._playhead_val is not None:
            px = self._val_to_x(self._playhead_val)
            painter.setPen(QPen(QColor("#FFFFFF"), 2))
            painter.drawLine(px, 0, px, height)

        painter.end()

    # ──────────────────────────────────────────────
    # MOUSE
    # ──────────────────────────────────────────────
    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        x = int(event.position().x())
        x_start = self._val_to_x(self._start_val)
        x_end   = self._val_to_x(self._end_val)
        hit = self._handle_radius * 1.5

        dist_start = abs(x - x_start)
        dist_end   = abs(x - x_end)

        if dist_start <= hit and dist_start <= dist_end:
            self._active_handle = 'start'
        elif dist_end <= hit:
            self._active_handle = 'end'
        elif x_start < x < x_end:
            # Clic en el interior del rango → modo arrastre completo
            self._active_handle = 'range'
            self._drag_offset_start = x - x_start
            self._drag_offset_end   = x_end - x
        else:
            self._active_handle = None

    def mouseMoveEvent(self, event):
        if not self._active_handle:
            return
        x = int(event.position().x())
        val = self._x_to_val(x)

        if self._active_handle == 'start':
            self._start_val = min(val, self._end_val - 1)
            self._start_val = max(self._minimum, self._start_val)
        elif self._active_handle == 'end':
            self._end_val = max(val, self._start_val + 1)
            self._end_val = min(self._maximum, self._end_val)
        elif self._active_handle == 'range':
            # Desplazar todo el rango manteniendo su tamaño
            span = self._end_val - self._start_val
            new_start_x = x - self._drag_offset_start
            new_end_x   = x + self._drag_offset_end
            new_start = self._x_to_val(new_start_x)
            new_end   = self._x_to_val(new_end_x)

            # Evitar que desborde los límites
            if new_start < self._minimum:
                new_start = self._minimum
                new_end   = self._minimum + span
            if new_end > self._maximum:
                new_end   = self._maximum
                new_start = self._maximum - span

            self._start_val = new_start
            self._end_val   = new_end

        self.update()
        self.range_changed.emit(self._start_val, self._end_val)

    def mouseReleaseEvent(self, event):
        self._active_handle = None

    def mouseMoveEvent_cursor(self, event):
        """Cambia el cursor según la zona."""
        x = int(event.position().x())
        x_start = self._val_to_x(self._start_val)
        x_end   = self._val_to_x(self._end_val)
        hit = self._handle_radius * 1.5
        if abs(x - x_start) <= hit or abs(x - x_end) <= hit:
            self.setCursor(Qt.SizeHorCursor)
        elif x_start < x < x_end:
            self.setCursor(Qt.SizeAllCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    # ──────────────────────────────────────────────
    # HELPERS
    # ──────────────────────────────────────────────
    def _val_to_x(self, val):
        w = self.width() - 2 * self._handle_radius
        ratio = (val - self._minimum) / (self._maximum - self._minimum) \
            if self._maximum > self._minimum else 0
        return int(self._handle_radius + ratio * w)

    def _x_to_val(self, x):
        w = self.width() - 2 * self._handle_radius
        ratio = (x - self._handle_radius) / w
        ratio = max(0.0, min(1.0, ratio))
        return int(self._minimum + ratio * (self._maximum - self._minimum))
