# src/gui/widgets/collapsible_panel.py
"""
CollapsiblePanel — envoltorio genérico para un panel lateral (izquierdo o derecho) que
puede vivir "acoplado" (widget normal dentro de un QHBoxLayout, con ancho fijo) o
"flotante" (overlay animado que se superpone al contenido sin empujarlo ni redimensionarlo,
con una pestaña de borde para abrir/cerrarlo).

Pensado para VideoToolsTab (Herramientas Multimedia): panel de cola de medios a la
izquierda y panel de opciones de codificación a la derecha, ambos colapsables en
ventanas angostas mientras el preview central y la fila inferior (timeline + salida)
permanecen siempre visibles.
"""
from PySide6.QtWidgets import QWidget, QFrame, QVBoxLayout, QScrollArea
from PySide6.QtCore import Qt, QRect, QPoint, QSize, QEasingCurve, QPropertyAnimation, Signal
from PySide6.QtGui import QPainter, QColor, QPolygon


class EdgeTabButton(QWidget):
    """Pestaña angosta pegada a un borde (izquierdo o derecho) para abrir/cerrar el overlay."""
    clicked = Signal()

    def __init__(self, edge: str, parent=None):
        super().__init__(parent)
        self.edge = edge
        self.setObjectName("collapsiblePanelEdgeTab")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(20, 90)
        self._hovered = False
        self._is_open = False

    def set_open(self, is_open: bool):
        self._is_open = is_open
        self.update()

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
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

        # Fondo: lado plano pegado al borde exterior, lado redondeado hacia el contenido.
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#2a2a2a" if self._hovered else "#1a1a1a"))
        if self.edge == "left":
            p.drawRoundedRect(-10, 0, w + 10, h, 8, 8)
        else:
            p.drawRoundedRect(0, 0, w + 10, h, 8, 8)

        if self._hovered:
            p.setBrush(QColor("#1DC038"))
            if self.edge == "left":
                p.drawRect(0, 0, 3, h)
            else:
                p.drawRect(w - 3, 0, 3, h)

        # Flecha: cerrado invita a abrir (apunta hacia el contenido), abierto invita a cerrar.
        # Centrada en el ancho de la pestaña: con el ancho por defecto (20) queda en los mismos
        # píxeles de siempre, y con una pestaña más ancha (ver history_panel.py) no se corre
        # hacia un costado.
        points_right = (self.edge == "left") != self._is_open
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#B9E640") if self._hovered else QColor("#888888"))
        cx = w // 2
        if points_right:
            triangle = QPolygon([QPoint(cx - 4, h // 2 - 8), QPoint(cx - 4, h // 2 + 8), QPoint(cx + 4, h // 2)])
        else:
            triangle = QPolygon([QPoint(cx + 4, h // 2 - 8), QPoint(cx + 4, h // 2 + 8), QPoint(cx - 4, h // 2)])
        p.drawPolygon(triangle)


class CollapsiblePanel(QFrame):
    """Panel colapsable genérico: acoplado (layout normal) u overlay (flotante, animado)."""

    opened = Signal()
    closed = Signal()

    def __init__(self, content: QWidget, edge: str, docked_size: int, overlay_max_width: int = None, parent=None):
        super().__init__(parent)
        assert edge in ("left", "right")
        self.edge = edge
        self.docked_size = docked_size
        self._dock_max_width = docked_size
        # Techo aparte para el overlay (independiente de _dock_max_width, que puede llegar a
        # ser bastante más grande para ventanas anchas acopladas): el overlay solo aparece
        # con la ventana angosta, y queremos que sea lo bastante ancho para que su
        # contenido entre cómodo, no que tape casi toda la ventana.
        self._overlay_max_width = overlay_max_width if overlay_max_width is not None else docked_size
        self._content = content
        self._docked = True
        self._overlay_open = False
        self._overlay_host = None
        self._dock_layout = None
        self._dock_index = 0
        self._dock_stretch = 0

        self.setObjectName("collapsiblePanel")
        self.setProperty("edge", edge)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # El contenido va dentro de un QScrollArea en vez de directo en el layout: así el
        # ancho mínimo real de `content` (que puede ser mayor que docked_size, p.ej. la
        # pestaña Avanzado de opciones) no se filtra hacia arriba y termina ganándole al
        # setFixedWidth de este panel. Con esto, el panel respeta docked_size siempre, y si
        # el contenido no entra aparece scroll horizontal en vez de recortarse o ensancharse.
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setWidget(content)
        layout.addWidget(self._scroll)

        # docked_size SÍ es un piso duro real (setMinimumWidth), no solo el sizeHint
        # preferido: con mínimo 0, el layout de Qt (qGeomCalc) reparte el DÉFICIT de ancho
        # proporcional al stretch cuando el espacio total no alcanza para todos los
        # sizeHint — y eso encoge este panel muy por debajo de docked_size (con scroll
        # horizontal de por medio) bastante antes de llegar al ancho mínimo "de verdad"
        # que necesita su contenido, no solo justo antes de colapsar a overlay como se
        # esperaba. VideoToolsTab._docked_floor_width() ya calcula el umbral de colapso
        # incluyendo este piso, así que en teoría nunca deberíamos llegar a necesitar
        # encogerlo por debajo — un resize() de un solo salto grande→chico puede quedar
        # momentáneamente clampeado un poco por encima del ancho pedido, pero se
        # autocorrige con el próximo resizeEvent (ver _update_responsive_mode).
        self.setMinimumWidth(docked_size)
        self.setMaximumWidth(self._dock_max_width)

        self.edge_tab = EdgeTabButton(edge)
        self.edge_tab.clicked.connect(self._on_edge_tab_clicked)
        self.edge_tab.hide()

        self._anim = QPropertyAnimation(self, b"geometry")
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)
        # Sin esto, _position_edge_tab() solo se calculaba una vez al ARRANCAR la animación
        # (con self.width() todavía en su valor inicial, no el final) — la pestaña quedaba
        # mal posicionada y, encima, tapada detrás del panel una vez terminaba de abrir.
        self._anim.valueChanged.connect(lambda _: self._position_edge_tab())

    def configure_container(self, host: QWidget, dock_layout, dock_index: int, dock_stretch: int = 0):
        """Define dónde vive este panel: `host` es el widget sobre el que se posiciona el
        overlay (debe cubrir exactamente el área que el overlay puede tapar, sin incluir
        la fila inferior siempre visible); `dock_layout`/`dock_index` es dónde se reinserta
        el panel cuando está acoplado. `dock_stretch` es el factor de stretch original con
        el que se agregó al layout — hay que reaplicarlo a mano en cada _enter_docked()
        porque QBoxLayout.insertWidget() no lo conserva al remover/reinsertar el widget
        (removeWidget + insertWidget sin stretch explícito lo resetea a 0, dejando el panel
        sin crecer nunca más después de haber pasado por overlay una vez)."""
        self._overlay_host = host
        self._dock_layout = dock_layout
        self._dock_index = dock_index
        self._dock_stretch = dock_stretch
        self.edge_tab.setParent(host)

    def sizeHint(self) -> QSize:
        if self._docked:
            return QSize(self.docked_size, super().sizeHint().height())
        return super().sizeHint()

    def set_dock_max_width(self, max_width: int):
        """Sube (o baja) el techo real de ancho, tanto acoplado como en overlay, sin tocar
        docked_size (que sigue siendo el ancho "preferido"/de arranque vía sizeHint). Con
        un stretch > 0 en el layout que lo contiene, esto es lo que le permite crecer más
        allá de docked_size cuando sobra espacio, en vez de quedar 100% fijo."""
        self._dock_max_width = max(max_width, self.docked_size)
        if self._docked:
            self.setMaximumWidth(self._dock_max_width)
        else:
            self.setMaximumWidth(self._overlay_max_width)

    def is_docked(self) -> bool:
        return self._docked

    def is_overlay_open(self) -> bool:
        return (not self._docked) and self._overlay_open

    def set_mode(self, docked: bool):
        if docked == self._docked:
            return
        if docked:
            self._enter_docked()
        else:
            self._enter_overlay()

    def _enter_docked(self):
        self._docked = True
        self._overlay_open = False
        self._anim.stop()
        self.edge_tab.hide()
        self.setParent(self._dock_layout.parentWidget())
        self.setMinimumWidth(self.docked_size)
        self.setMaximumWidth(self._dock_max_width)
        self.setProperty("dockMode", "docked")
        self.style().unpolish(self)
        self.style().polish(self)
        self.updateGeometry()
        self._dock_layout.insertWidget(self._dock_index, self, self._dock_stretch)
        self.show()

    def _enter_overlay(self):
        self._docked = False
        self._overlay_open = False
        self._anim.stop()
        self._dock_layout.removeWidget(self)
        self.setParent(self._overlay_host)
        self.setMinimumWidth(0)
        self.setMaximumWidth(self._overlay_max_width)
        self.setProperty("dockMode", "overlay")
        self.style().unpolish(self)
        self.style().polish(self)
        self.hide()
        self.edge_tab.set_open(False)
        self.edge_tab.show()
        self.edge_tab.raise_()
        self._position_edge_tab()

    def _on_edge_tab_clicked(self):
        if self._overlay_open:
            self.close_overlay()
        else:
            self.open_overlay()

    def _end_geometry(self, expanded: bool) -> QRect:
        host_rect = self._overlay_host.rect()
        # _overlay_max_width (no _dock_max_width): antes usaba docked_size fijo y el
        # overlay quedaba pegado al ancho de arranque aunque sobrara espacio; pero usar
        # directamente _dock_max_width (pensado para ventanas grandes acopladas) hacía que
        # el overlay casi tapara toda la ventana angosta donde SÍ aparece.
        w = min(self._overlay_max_width, max(host_rect.width(), 0))
        h = host_rect.height()
        if not expanded:
            w = 0
        if self.edge == "left":
            return QRect(0, 0, w, h)
        return QRect(host_rect.width() - w, 0, w, h)

    def open_overlay(self):
        if self._docked or self._overlay_open or not self._overlay_host:
            return
        self._overlay_open = True
        self._anim.stop()
        start_rect = self._end_geometry(False)
        self.setGeometry(start_rect)
        self.show()
        self.raise_()
        self._anim.setStartValue(start_rect)
        self._anim.setEndValue(self._end_geometry(True))
        self._anim.start()
        self.edge_tab.set_open(True)
        self._position_edge_tab()
        # self.raise_() (arriba) puso el panel por encima de todo, incluida la pestaña —
        # sin esto, el botón para cerrar queda tapado detrás del panel abierto.
        self.edge_tab.raise_()
        self.opened.emit()

    def close_overlay(self):
        if self._docked or not self._overlay_open:
            return
        self._overlay_open = False
        self._anim.stop()
        self._anim.setStartValue(self.geometry())
        self._anim.setEndValue(self._end_geometry(False))
        self._anim.finished.connect(self._hide_after_close)
        self._anim.start()
        self.edge_tab.set_open(False)
        self._position_edge_tab()
        self.closed.emit()

    def _hide_after_close(self):
        if not self._overlay_open and not self._docked:
            self.hide()
        try:
            self._anim.finished.disconnect(self._hide_after_close)
        except RuntimeError:
            pass

    def _position_edge_tab(self):
        if not self._overlay_host:
            return
        host_rect = self._overlay_host.rect()
        y = max((host_rect.height() - self.edge_tab.height()) // 2, 0)
        if self.edge == "left":
            x = self.width() if self._overlay_open else 0
        else:
            x = host_rect.width() - self.width() - self.edge_tab.width() if self._overlay_open \
                else host_rect.width() - self.edge_tab.width()
        self.edge_tab.move(x, y)

    def sync_overlay_geometry(self):
        """Llamar desde el resizeEvent del contenedor padre para que, si el overlay está
        abierto (o el host cambió de tamaño), la geometría del panel y su pestaña se
        mantengan alineadas al borde correspondiente."""
        if self._docked or not self._overlay_host:
            return
        if self._overlay_open:
            self.setGeometry(self._end_geometry(True))
        self._position_edge_tab()
