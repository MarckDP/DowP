# src/gui/widgets/floating_panel.py
"""Ventana flotante arrastrable genérica -- a diferencia de CollapsiblePanel (que solo
desliza pegada a un borde), esta se puede mover libremente por encima de otro widget
(su `host`), agarrando la barra de título con el mouse. Pensada para el panel de Capas
del Editor de Imagen (estilo paneles flotantes de Photoshop), pero sin nada específico
de capas -- reusable para cualquier otro panel flotante futuro."""
from PySide6.QtCore import Qt, QPoint, QRect, QEvent, Signal
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget

from gui.styles import get_theme_token
from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon
from gui.styles import set_themed_style


class _TitleBar(QWidget):
    close_clicked = Signal()

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.SizeAllCursor)
        self.setFixedHeight(28)
        self._drag_start = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 4, 0)
        layout.setSpacing(4)

        lbl = QLabel(title)
        set_themed_style(lbl, lambda: f"color: {get_theme_token('texto_principal', '#ffffff')}; font-weight: bold; font-size: 12px;")
        layout.addWidget(lbl)
        layout.addStretch()

        self.btn_close = QPushButton()
        self.btn_close.setIcon(get_colored_svg_icon("close.svg", get_theme_token('texto_tenue', '#888888'), size=12))
        self.btn_close.setFixedSize(18, 18)
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.setStyleSheet("border: none; background: transparent; padding: 0px;")
        self.btn_close.clicked.connect(self.close_clicked.emit)
        layout.addWidget(self.btn_close)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_start is not None and (event.buttons() & Qt.LeftButton):
            panel = self.parent()
            global_pos = event.globalPosition().toPoint()
            delta = global_pos - self._drag_start
            self._drag_start = global_pos
            panel.move(panel.pos() + delta)
            panel.clamp_to_host()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_start = None
        super().mouseReleaseEvent(event)


class FloatingPanel(QFrame):
    """`host` es el widget sobre el que flota (define los límites para no perderse
    fuera de la ventana -- ver clamp_to_host).
    Permite arrastre desde la barra de título y redimensionado desde los 4 bordes y esquinas."""
    closed = Signal()

    RESIZE_MARGIN = 6
    EDGE_NONE = 0
    EDGE_LEFT = 1
    EDGE_RIGHT = 2
    EDGE_TOP = 4
    EDGE_BOTTOM = 8

    def __init__(self, title: str, content: QWidget, host: QWidget, width: int = 300,
                 min_width: int = 220, min_height: int = 180, parent=None,
                 preferred_side: str = "right"):
        super().__init__(parent if parent is not None else host)
        assert preferred_side in ("left", "right")
        self._host = host
        self._min_width = min_width
        self._min_height = min_height
        self._preferred_side = preferred_side
        self._resizing_edge = self.EDGE_NONE
        self._drag_start_pos = None
        self._drag_start_geo = None

        self.setObjectName("floatingPanel")
        self.setMinimumSize(self._min_width, self._min_height)
        self.resize(width, 360)
        self.setMouseTracking(True)

        set_themed_style(self, lambda: f"""
            QFrame#floatingPanel {{
                background-color: {get_theme_token('fondo_secundario', '#1e1e1e')};
                border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                border-radius: 8px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.title_bar = _TitleBar(title, self)
        self.title_bar.close_clicked.connect(self.closed.emit)
        layout.addWidget(self.title_bar)

        sep = QFrame()
        sep.setFixedHeight(1)
        set_themed_style(sep, lambda: f"background-color: {get_theme_token('borde_normal', '#2d2d2d')};")
        layout.addWidget(sep)

        layout.addWidget(content)
        self.hide()
        self._positioned = False

        self._install_tracking(self)

    def _install_tracking(self, widget: QWidget):
        widget.setMouseTracking(True)
        widget.installEventFilter(self)
        for child in widget.findChildren(QWidget):
            child.setMouseTracking(True)
            child.installEventFilter(self)

    def childEvent(self, event):
        if event.type() == QEvent.ChildAdded and event.child().isWidgetType():
            w = event.child()
            w.setMouseTracking(True)
            w.installEventFilter(self)
        super().childEvent(event)

    def _get_edge(self, pt: QPoint) -> int:
        edge = self.EDGE_NONE
        r = self.rect()
        if pt.x() <= self.RESIZE_MARGIN:
            edge |= self.EDGE_LEFT
        elif pt.x() >= r.width() - self.RESIZE_MARGIN:
            edge |= self.EDGE_RIGHT
        if pt.y() <= self.RESIZE_MARGIN:
            edge |= self.EDGE_TOP
        elif pt.y() >= r.height() - self.RESIZE_MARGIN:
            edge |= self.EDGE_BOTTOM
        return edge

    def _update_cursor_for_edge(self, edge: int):
        if (edge & (self.EDGE_LEFT | self.EDGE_TOP)) == (self.EDGE_LEFT | self.EDGE_TOP) or \
           (edge & (self.EDGE_RIGHT | self.EDGE_BOTTOM)) == (self.EDGE_RIGHT | self.EDGE_BOTTOM):
            self.setCursor(Qt.SizeFDiagCursor)
        elif (edge & (self.EDGE_RIGHT | self.EDGE_TOP)) == (self.EDGE_RIGHT | self.EDGE_TOP) or \
             (edge & (self.EDGE_LEFT | self.EDGE_BOTTOM)) == (self.EDGE_LEFT | self.EDGE_BOTTOM):
            self.setCursor(Qt.SizeBDiagCursor)
        elif edge & (self.EDGE_LEFT | self.EDGE_RIGHT):
            self.setCursor(Qt.SizeHorCursor)
        elif edge & (self.EDGE_TOP | self.EDGE_BOTTOM):
            self.setCursor(Qt.SizeVerCursor)
        else:
            self.unsetCursor()

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.MouseMove, QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
            gpos = event.globalPosition().toPoint()
            pos = self.mapFromGlobal(gpos)
            edge = self._get_edge(pos)

            if event.type() == QEvent.MouseMove:
                if self._resizing_edge != self.EDGE_NONE:
                    self._handle_resize(gpos)
                    return True
                elif edge != self.EDGE_NONE:
                    self._update_cursor_for_edge(edge)
                else:
                    self.unsetCursor()

            elif event.type() == QEvent.MouseButtonPress:
                if event.button() == Qt.LeftButton and edge != self.EDGE_NONE:
                    self._resizing_edge = edge
                    self._drag_start_pos = gpos
                    self._drag_start_geo = self.geometry()
                    return True

            elif event.type() == QEvent.MouseButtonRelease:
                if self._resizing_edge != self.EDGE_NONE:
                    self._resizing_edge = self.EDGE_NONE
                    self._update_cursor_for_edge(edge)
                    return True

        return super().eventFilter(obj, event)

    def _handle_resize(self, gpos: QPoint):
        delta = gpos - self._drag_start_pos
        host_rect = self._host.rect()
        start_geo = self._drag_start_geo

        min_w = self._min_width
        min_h = self._min_height
        max_w = max(min_w, host_rect.width() - 20)
        max_h = max(min_h, host_rect.height() - 20)

        new_x = start_geo.x()
        new_y = start_geo.y()
        new_w = start_geo.width()
        new_h = start_geo.height()

        if self._resizing_edge & self.EDGE_LEFT:
            wanted_w = start_geo.width() - delta.x()
            new_w = max(min_w, min(max_w, wanted_w))
            new_x = start_geo.right() - new_w + 1
            if new_x < 0:
                new_x = 0
                new_w = start_geo.right() + 1
        elif self._resizing_edge & self.EDGE_RIGHT:
            wanted_w = start_geo.width() + delta.x()
            max_avail_w = max(min_w, host_rect.width() - start_geo.left())
            new_w = max(min_w, min(max_w, min(wanted_w, max_avail_w)))

        if self._resizing_edge & self.EDGE_TOP:
            wanted_h = start_geo.height() - delta.y()
            new_h = max(min_h, min(max_h, wanted_h))
            new_y = start_geo.bottom() - new_h + 1
            if new_y < 0:
                new_y = 0
                new_h = start_geo.bottom() + 1
        elif self._resizing_edge & self.EDGE_BOTTOM:
            wanted_h = start_geo.height() + delta.y()
            max_avail_h = max(min_h, host_rect.height() - start_geo.top())
            new_h = max(min_h, min(max_h, min(wanted_h, max_avail_h)))

        self.setGeometry(new_x, new_y, new_w, new_h)

    def show_panel(self):
        if not self._positioned:
            self._default_position()
            self._positioned = True
        self.clamp_to_host()
        self.show()
        self.raise_()

    def hide_panel(self):
        self.hide()

    def _default_position(self):
        host_rect = self._host.rect()
        if self._preferred_side == "left":
            x = 10
        else:
            x = max(10, host_rect.width() - self.width() - 20)
        y = 10
        self.move(x, y)

    def clamp_to_host(self):
        host_rect = self._host.rect()
        x = min(max(0, self.x()), max(0, host_rect.width() - self.width()))
        y = min(max(0, self.y()), max(0, host_rect.height() - self.height()))
        self.move(x, y)
