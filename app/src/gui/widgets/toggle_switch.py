# src/gui/widgets/toggle_switch.py
"""
ToggleSwitch — Switch animado estilo iOS/Material para reemplazar QCheckBox.
Dibujado con QPainter para control total del aspecto visual.
"""
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Signal, Property, QPropertyAnimation, QEasingCurve, Qt, QSize
from PySide6.QtGui import QPainter, QColor, QPen


class ToggleSwitch(QWidget):
    toggled = Signal(bool)

    # Dimensiones del switch
    TRACK_WIDTH = 44
    TRACK_HEIGHT = 24
    KNOB_DIAMETER = 18
    KNOB_MARGIN = 3

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self._knob_x = self._target_x()

        self.setFixedSize(self.TRACK_WIDTH, self.TRACK_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)

        # None = tomar el color del tema al pintar (se pueden fijar desde fuera)
        self._color_off_track = None
        self._color_on_track = None
        self._color_knob = None

        try:
            from gui.theme_manager import get_theme_manager
            get_theme_manager().theme_changed.connect(self._on_theme_changed)
        except Exception:
            pass

        # Animación del knob
        self._anim = QPropertyAnimation(self, b"knob_x")
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)

    def _target_x(self):
        if self._checked:
            return self.TRACK_WIDTH - self.KNOB_DIAMETER - self.KNOB_MARGIN
        return self.KNOB_MARGIN

    # ── Qt Property para animar ──────────────────────────────
    def get_knob_x(self):
        return self._knob_x

    def set_knob_x(self, val):
        self._knob_x = val
        self.update()

    knob_x = Property(float, get_knob_x, set_knob_x)

    # ── API pública ──────────────────────────────────────────
    def isChecked(self):
        return self._checked

    def setChecked(self, checked):
        if self._checked == checked:
            return
        self._checked = checked
        self._animate()
        self.toggled.emit(self._checked)

    def toggle(self):
        self.setChecked(not self._checked)

    # ── Colores (para integración con tema) ──────────────────
    def setTrackColors(self, off_color, on_color):
        self._color_off_track = QColor(off_color)
        self._color_on_track = QColor(on_color)
        self.update()

    def setKnobColor(self, color):
        self._color_knob = QColor(color)
        self.update()

    def _on_theme_changed(self, _tokens=None):
        try:
            self.update()
        except RuntimeError:
            pass

    @staticmethod
    def _token(name, fallback):
        from gui.styles import get_theme_token
        return QColor(get_theme_token(name, fallback))

    # ── Eventos ──────────────────────────────────────────────
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.toggle()

    def sizeHint(self):
        return QSize(self.TRACK_WIDTH, self.TRACK_HEIGHT)

    # ── Animación ────────────────────────────────────────────
    def _animate(self):
        self._anim.stop()
        self._anim.setStartValue(self._knob_x)
        self._anim.setEndValue(self._target_x())
        self._anim.start()

    # ── Pintado ──────────────────────────────────────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        
        if not self.isEnabled():
            p.setOpacity(0.4)

        # Calcular progreso (0.0 = off, 1.0 = on) para interpolar colores
        max_x = self.TRACK_WIDTH - self.KNOB_DIAMETER - self.KNOB_MARGIN
        min_x = self.KNOB_MARGIN
        progress = (self._knob_x - min_x) / (max_x - min_x) if max_x != min_x else 0

        # Track (fondo ovalado)
        off_track = self._color_off_track or self._token("switch_apagado", "#333333")
        on_track = self._color_on_track or self._token("acento_primario", "#B9E640")
        track_color = self._interpolate_color(off_track, on_track, progress)
        radius = self.TRACK_HEIGHT / 2

        # El borde solo se ve con el switch apagado; encendido se funde con el acento
        border = self._interpolate_color(self._token("switch_borde", "#444444"), on_track, progress)
        p.setPen(QPen(border, 1))
        p.setBrush(track_color)
        p.drawRoundedRect(0, 0, self.TRACK_WIDTH, self.TRACK_HEIGHT, radius, radius)

        # Knob (círculo)
        knob_y = (self.TRACK_HEIGHT - self.KNOB_DIAMETER) / 2
        p.setPen(Qt.NoPen)
        p.setBrush(self._color_knob or self._token("switch_perilla", "#ffffff"))
        p.drawEllipse(int(self._knob_x), int(knob_y),
                       self.KNOB_DIAMETER, self.KNOB_DIAMETER)

        p.end()

    @staticmethod
    def _interpolate_color(c1, c2, t):
        """Interpola linealmente entre dos QColors."""
        return QColor(
            int(c1.red()   + (c2.red()   - c1.red())   * t),
            int(c1.green() + (c2.green() - c1.green()) * t),
            int(c1.blue()  + (c2.blue()  - c1.blue())  * t),
        )
