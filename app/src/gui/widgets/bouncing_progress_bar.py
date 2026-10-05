# src/gui/widgets/bouncing_progress_bar.py
"""
BouncingProgressBar — QProgressBar con modo indeterminado personalizado.
Dibuja una barra rebotando de izquierda a derecha que respeta el border-radius
y siempre muestra texto centrado.
"""
from PySide6.QtWidgets import QProgressBar
from PySide6.QtCore import (
    Property, QPropertyAnimation, QSequentialAnimationGroup,
    QEasingCurve, Qt,
)
from PySide6.QtGui import QPainter, QColor, QLinearGradient, QPainterPath
from gui.styles import get_theme_token


class BouncingProgressBar(QProgressBar):
    """
    Reemplaza el modo indeterminado nativo de Qt (feo, sin border-radius, sin texto)
    con una animación personalizada pintada con QPainter.
    """
    CHUNK_RATIO = 0.28  # El chunk ocupa el 28% del ancho total

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bouncing = False
        self._bounce_pos = 0.0        # 0.0 … 1.0
        self._status_text = ""
        
        # Cargar colores desde el sistema de temas (evita hardcodeo), y de nuevo al cambiarlo
        self.refresh_theme_colors()
        from gui.theme_manager import get_theme_manager
        get_theme_manager().theme_changed.connect(lambda _tokens: self.refresh_theme_colors())
        self.setFixedHeight(18) # Barra ultra delgada

        # Grupo de animación para el ping-pong
        fwd = QPropertyAnimation(self, b"bounce_pos")
        fwd.setDuration(1000)
        fwd.setStartValue(0.0)
        fwd.setEndValue(1.0)
        fwd.setEasingCurve(QEasingCurve.InOutSine)

        bwd = QPropertyAnimation(self, b"bounce_pos")
        bwd.setDuration(1000)
        bwd.setStartValue(1.0)
        bwd.setEndValue(0.0)
        bwd.setEasingCurve(QEasingCurve.InOutSine)

        self._bounce_group = QSequentialAnimationGroup(self)
        self._bounce_group.addAnimation(fwd)
        self._bounce_group.addAnimation(bwd)
        self._bounce_group.setLoopCount(-1)

    # ── Qt Property para animar ─────────────────────────────
    def _get_bounce_pos(self):
        return self._bounce_pos

    def _set_bounce_pos(self, v):
        self._bounce_pos = v
        if self._bouncing:
            self.update()

    bounce_pos = Property(float, _get_bounce_pos, _set_bounce_pos)

    # ── API pública ─────────────────────────────────────────
    def setBouncing(self, enabled):
        """Activa/desactiva el modo rebote."""
        if self._bouncing == enabled:
            return
        self._bouncing = enabled
        if enabled:
            self._bounce_group.start()
        else:
            self._bounce_group.stop()
            self.update()

    def isBouncing(self):
        return self._bouncing

    def setBounceColors(self, start, end):
        """Permite al tema inyectar los colores del chunk."""
        self._bounce_color_start = QColor(start)
        self._bounce_color_end = QColor(end)

    def refresh_theme_colors(self):
        """Sincroniza los colores internos con los tokens del tema actual."""
        self._bounce_color_start = QColor(get_theme_token("progreso_inicio", "#35d6b8"))
        self._bounce_color_end   = QColor(get_theme_token("progreso_fin", "#138f7d"))
        self._bg_color_token     = QColor(get_theme_token("progreso_fondo", "#0f0f0f"))
        self._text_color_token   = QColor(get_theme_token("progreso_texto", "#ffffff"))
        self.update()

    # ── Pintado ─────────────────────────────────────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        radius = h / 2  # Pill shape

        # 1. Fondo de la barra
        p.setPen(Qt.NoPen)
        p.setBrush(self._bg_color_token)
        p.drawRoundedRect(0, 0, w, h, radius, radius)

        # 2. Chunk (Bouncing o Normal)
        if self._bouncing:
            chunk_w = max(int(w * self.CHUNK_RATIO), 20)
            travel = w - chunk_w
            x = int(self._bounce_pos * travel)
        else:
            # Modo normal: El ancho depende del valor (0-100%)
            val_range = self.maximum() - self.minimum()
            if val_range > 0:
                percent = (self.value() - self.minimum()) / val_range
                chunk_w = int(w * percent)
                x = 0
            else:
                chunk_w = 0
                x = 0

        if chunk_w > 0:
            grad = QLinearGradient(x, 0, x + chunk_w, 0)
            grad.setColorAt(0, self._bounce_color_start)
            grad.setColorAt(1, self._bounce_color_end)

            p.setBrush(grad)
            # Clipear al contorno redondeado para que el chunk no se salga
            clip = QPainterPath()
            clip.addRoundedRect(0, 0, w, h, radius, radius)
            p.setClipPath(clip)
            p.drawRoundedRect(x, 0, chunk_w, h, radius, radius)
            p.setClipping(False)

        # 3. Texto con Modo de Fusión (Inversión inteligente)
        # Usamos CompositionMode_Difference con color blanco para invertir el fondo.
        # Esto hace que el texto sea oscuro sobre el chunk claro y claro sobre el fondo oscuro.
        p.setCompositionMode(QPainter.CompositionMode_Difference)
        p.setPen(Qt.white) 
        
        font = p.font()
        font.setBold(True)
        p.setFont(font)
        
        p.drawText(self.rect(), Qt.AlignCenter, self.format())

        p.end()
