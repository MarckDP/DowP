# src/gui/widgets/preview_panel.py
"""
PreviewPanel — Panel lateral colapsable para contenido adicional.
Se muestra automáticamente cuando la ventana es grande,
y se oculta con un botón triángulo cuando es pequeña.
"""
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget
from PySide6.QtCore import (Qt, QPropertyAnimation, QEasingCurve, 
                             QParallelAnimationGroup, Property, QSize)
from PySide6.QtGui import QPainter, QColor, QPen, QPolygon
from PySide6.QtCore import QPoint
from core.logger.logger_manager import logger


from PySide6.QtCore import Signal
from gui.styles import theme_radius
from gui.styles import get_theme_token

class EdgeOpenButton(QWidget):
    """Botón de borde para abrir/cerrar el panel."""
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panelToggleBtn")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(24, 100)
        self.hovered = False
        self._pointing_left = True

    def set_direction(self, pointing_left: bool):
        self._pointing_left = pointing_left
        self.update()

    def enterEvent(self, event):
        self.hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovered = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()

        # Fondo sutil para que parezca una pestaña adherida
        p.setPen(Qt.NoPen)
        if self.hovered:
            p.setBrush(QColor("#2a2a2a"))
        else:
            p.setBrush(QColor("#1a1a1a"))
            
        if self._pointing_left:
            # Pestaña redondeada a la izquierda
            p.drawRoundedRect(0, 0, w + 10, h, theme_radius(8), theme_radius(8))
            if self.hovered:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor("#1DC038"))
                p.drawRect(w - 3, 0, 3, h)
        else:
            # Pestaña redondeada a la derecha
            p.drawRoundedRect(-10, 0, w + 10, h, theme_radius(8), theme_radius(8))
            if self.hovered:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor("#1DC038"))
                p.drawRect(0, 0, 3, h)

        # Flecha
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#B9E640") if self.hovered else QColor(get_theme_token('texto_tenue', '#888888')))
        
        if self._pointing_left:
            triangle = QPolygon([
                QPoint(w - 6, h // 2 - 8),
                QPoint(w - 6, h // 2 + 8),
                QPoint(w - 14, h // 2),
            ])
        else:
            triangle = QPolygon([
                QPoint(6, h // 2 - 8),
                QPoint(6, h // 2 + 8),
                QPoint(14, h // 2),
            ])
        p.drawPolygon(triangle)


class PreviewPanel(QFrame):
    """Panel lateral derecho colapsable."""

    # Porcentaje del ancho del parent que ocupa el panel
    PANEL_WIDTH_RATIO = 0.30
    OVERLAY_PANEL_WIDTH_RATIO = 0.33

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("previewPanel")
        self._parent_ref = parent
        self._is_visible_panel = False
        self._is_docked = False  # True cuando ventana es grande y panel está integrado
        self._panel_opacity = 0.0

        self.init_ui()
        self.hide()  # Empieza oculto

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Título del panel
        title = QLabel(self.tr("Opciones de Recodificación"))
        title.setObjectName("panelTitle")
        title.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        layout.addWidget(title)

        # Placeholder
        placeholder = QLabel(self.tr("Las opciones de recodificación estarán disponibles aquí."))
        placeholder.setObjectName("panelPlaceholder")
        placeholder.setWordWrap(True)
        placeholder.setAlignment(Qt.AlignCenter)
        layout.addWidget(placeholder)

        layout.addStretch()

        # Botón lateral para abrir/cerrar (EdgeOpenButton)
        self.edge_btn = EdgeOpenButton(self._parent_ref if self._parent_ref else self)
        self.edge_btn.clicked.connect(self._on_toggle_clicked)
        self.edge_btn.hide()

        # Animación del panel
        self._slide_anim = QPropertyAnimation(self, b"geometry")
        self._slide_anim.setDuration(300)
        self._slide_anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._slide_anim.valueChanged.connect(self._sync_toggle_position)

    def _on_toggle_clicked(self):
        if self._is_visible_panel:
            self.collapse()
        else:
            self.expand()

    def expand(self):
        """Expande el panel con animación slide-in desde la derecha."""
        if not self._parent_ref:
            return

        self._is_visible_panel = True
        self.edge_btn.set_direction(False) # apuntar a la derecha
        self.edge_btn.show() # Asegurar que esté visible durante la animación

        parent_rect = self._parent_ref.rect()
        panel_w = int(parent_rect.width() * self.OVERLAY_PANEL_WIDTH_RATIO)
        panel_h = parent_rect.height()

        # Posición final: anclado a la derecha del parent
        end_x = parent_rect.width() - panel_w
        end_y = 0

        # Posición inicial: fuera de pantalla a la derecha
        start_x = parent_rect.width()

        self.show()
        self.raise_()
        self.edge_btn.raise_() # Traer el botón al frente DESPUÉS de haber traído el panel al frente

        self._slide_anim.stop()
        from PySide6.QtCore import QRect
        self._slide_anim.setStartValue(QRect(start_x, end_y, panel_w, panel_h))
        self._slide_anim.setEndValue(QRect(end_x, end_y, panel_w, panel_h))
        self._slide_anim.start()

        # Si la consola overlay está abierta, cederle el z-order
        self._raise_console_overlay_if_open()

    def collapse(self):
        """Colapsa el panel con animación slide-out hacia la derecha."""
        if not self._parent_ref:
            return

        self._is_visible_panel = False
        self.edge_btn.set_direction(True) # apuntar a la izquierda

        parent_rect = self._parent_ref.rect()
        panel_w = int(parent_rect.width() * self.OVERLAY_PANEL_WIDTH_RATIO)
        panel_h = parent_rect.height()

        end_x = parent_rect.width()

        self._slide_anim.stop()
        from PySide6.QtCore import QRect
        self._slide_anim.setStartValue(self.geometry())
        self._slide_anim.setEndValue(QRect(end_x, 0, panel_w, panel_h))
        self._slide_anim.finished.connect(self._on_collapse_finished)
        self._slide_anim.start()

    def _on_collapse_finished(self):
        if not self._is_visible_panel and not self._is_docked:
            self.hide()
            self._update_toggle_position()
                
        try:
            self._slide_anim.finished.disconnect(self._on_collapse_finished)
        except RuntimeError:
            pass

    def _raise_console_overlay_if_open(self):
        """Si hay un BottomConsolePanel con overlay abierto en el parent, lo sube al tope del z-order."""
        if not self._parent_ref:
            return
        bcp = getattr(self._parent_ref, 'bottom_console_panel', None)
        if bcp and bcp.overlay_panel.isVisible():
            bcp.overlay_panel.raise_()

    def update_for_window_size(self, parent_width, parent_height):
        """Llamado desde el resizeEvent del parent para ajustar el panel."""
        # Umbral: si la ventana es >= 1.30x del minimumWidth (1000), 
        # mostramos el panel integrado. Esto es ~1300px en 100% DPI
        # pero se adapta proporcionalmente en DPI altos.
        min_width = 1000
        threshold_ratio = 1.30
        threshold = int(min_width * threshold_ratio)

        if parent_width >= threshold:
            # Modo DOCKED: panel integrado
            self._dock_panel(parent_width, parent_height)
        else:
            # Modo OVERLAY: panel oculto con botón triángulo
            self._undock_panel(parent_width, parent_height)

    def _dock_panel(self, parent_width, parent_height):
        """Muestra el panel integrado y empuja el contenido ajustando el margen del top_container."""
        self._is_docked = True
        self._is_visible_panel = True
        self.edge_btn.hide()

        panel_w = int(parent_width * self.PANEL_WIDTH_RATIO)
        panel_x = parent_width - panel_w

        # Ajustar el margen derecho del main_layout para empujar todo el contenido (incluyendo consola)
        if hasattr(self._parent_ref, 'main_layout'):
            ml = self._parent_ref.main_layout
            m = ml.contentsMargins()
            ml.setContentsMargins(m.left(), m.top(), panel_w, m.bottom())

        self.setGeometry(panel_x, 0, panel_w, parent_height)
        self.show()
        self.raise_()

    def _undock_panel(self, parent_width, parent_height):
        """Oculta el panel y muestra el botón triángulo."""
        if self._is_docked:
            # Estaba docked, ahora se oculta
            self._is_docked = False
            self._is_visible_panel = False
            self.hide()

            # Restaurar el margen derecho del main_layout
            if hasattr(self._parent_ref, 'main_layout'):
                ml = self._parent_ref.main_layout
                m = ml.contentsMargins()
                ml.setContentsMargins(m.left(), m.top(), 0, m.bottom())

        # Mostrar y posicionar botón del borde
        self.edge_btn.setParent(self._parent_ref)
        self.edge_btn.show()
        self.edge_btn.raise_()
        self._update_toggle_position()

    def _sync_toggle_position(self, value):
        if not self._parent_ref or self._is_docked:
            return
        
        btn_y = (self._parent_ref.height() - self.edge_btn.height()) // 2
        
        if self._is_visible_panel:
            # Animando hacia la izquierda: el botón se queda "dentro del panel" (en su borde izquierdo interior)
            btn_x = value.left() + 4 # 4px adentro del panel
        else:
            # Animando hacia la derecha: el botón se pega al borde de la ventana
            btn_x = value.left() - self.edge_btn.width()
            
            # Si el panel ya se fue muy a la derecha, anclar al borde
            if btn_x > self._parent_ref.rect().width() - self.edge_btn.width():
                btn_x = self._parent_ref.rect().width() - self.edge_btn.width()
                
        self.edge_btn.move(btn_x, btn_y)

    def _update_toggle_position(self):
        """Posiciona el botón de borde, centrado verticalmente."""
        if not self._parent_ref or self._is_docked:
            return
        
        btn_y = (self._parent_ref.height() - self.edge_btn.height()) // 2
        
        if self._is_visible_panel:
            # Botón dentro del cuadro
            btn_x = self.geometry().left() + 4
        else:
            # Botón en el borde derecho
            btn_x = self._parent_ref.rect().width() - self.edge_btn.width()
            
        self.edge_btn.move(btn_x, btn_y)
