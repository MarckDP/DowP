# src/gui/widgets/queue_trigger_bar.py
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Signal, QRect
from PySide6.QtGui import QPainter, QColor, QFont, QPen, QPainterPath, QFontDatabase
from gui.styles import get_theme_token, glass_fill, theme_radius

class QueueTriggerBar(QWidget):
    """
    Tirador vertical que sirve de alternador para abrir/cerrar el panel de colas.
    Dibuja el texto 'Proceso por Lotes' verticalmente y reacciona al hover.
    """
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(24)
        self.setCursor(Qt.PointingHandCursor)
        
        self._hovered = False
        self._expanded = False  # Estado actual (cerrado por defecto)
        
        # Animación de hover usando opacidad o color
        self.setStyleSheet("background: transparent;")

    def set_expanded(self, expanded: bool):
        """Actualiza el estado para cambiar el sentido de la flecha indicadora."""
        if self._expanded != expanded:
            self._expanded = expanded
            self.update()

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Cargar colores del tema actual
        bg_base = get_theme_token("fondo_secundario", "#1a1a1a")
        bg_hover = get_theme_token("borde", "#2d2d2d")
        accent = get_theme_token("acento_primario", "#B9E640")
        text_color = get_theme_token("texto_secundario", "#aaaaaa")
        
        # Crear path con bordes redondeados solo a la derecha
        path = QPainterPath()
        r = theme_radius(6)  # radio del redondeado
        w = self.width()
        h = self.height()
        
        # Ajustamos el contorno para que el borde se dibuje perfectamente alineado
        w_bound = w - 1
        h_bound = h - 1
        
        path.moveTo(0, 0)
        path.lineTo(w_bound - r, 0)
        path.arcTo(w_bound - 2*r, 0, 2*r, 2*r, 90, -90)
        path.lineTo(w_bound, h_bound - r)
        path.arcTo(w_bound - 2*r, h_bound - 2*r, 2*r, 2*r, 0, -90)
        path.lineTo(0, h_bound)
        path.closeSubpath()
        
        # Dibujar fondo de la barra usando el path redondeado
        bg_color = QColor(bg_hover) if self._hovered else QColor(bg_base)
        bg_color = glass_fill(self, bg_color, "control")  # con imagen de fondo: translúcido
        painter.fillPath(path, bg_color)
        
        # Dibujar borde usando el mismo path
        border_color = QColor(get_theme_token("borde", "#2d2d2d"))
        painter.setPen(QPen(border_color, 1))
        painter.drawPath(path)

        # Dibujar indicador (Flecha) en la parte superior
        painter.save()
        painter.setPen(QPen(QColor(accent if self._hovered else text_color), 2))
        
        # Dibujar flecha indicadora
        # Si está expandido apunta a la izquierda (<), si está colapsado a la derecha (>)
        arrow_y = 25
        arrow_x = self.width() // 2
        
        if self._expanded:
            # Apuntar a la izquierda <
            painter.drawLine(arrow_x + 3, arrow_y - 5, arrow_x - 3, arrow_y)
            painter.drawLine(arrow_x - 3, arrow_y, arrow_x + 3, arrow_y + 5)
        else:
            # Apuntar a la derecha >
            painter.drawLine(arrow_x - 3, arrow_y - 5, arrow_x + 3, arrow_y)
            painter.drawLine(arrow_x + 3, arrow_y, arrow_x - 3, arrow_y + 5)
        painter.restore()

        # Dibujar texto vertical en el centro
        painter.save()
        
        # Rotar y trasladar el lienzo
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate(-90.0)
        
        # Configurar fuente
        from core.utils.font_manager import get_active_font_family
        font = QFont(get_active_font_family(), 9)
        font.setBold(True)
        painter.setFont(font)
        
        # Configurar color de texto
        painter.setPen(QColor(accent if self._hovered else text_color))
        
        # Dibujar texto centrado en el rect rotado
        # El ancho del rect rotado es el alto real de la barra, el alto es el ancho real
        text = self.tr("PROCESO POR LOTES")
        rect = QRect(-self.height() // 2, -self.width() // 2, self.height(), self.width())
        painter.drawText(rect, Qt.AlignCenter, text)
        
        painter.restore()
