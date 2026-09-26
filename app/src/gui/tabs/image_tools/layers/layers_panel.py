# src/gui/tabs/image_tools/layers/layers_panel.py
"""Contenido del panel flotante "Capas" -- SIN fila de herramientas (Seleccionar/
Rectángulo/Elipse/Línea/Pincel ahora son botones propios en la franja superior de
image_tools_view.py); aquí solo quedan "+ Fondo" y la lista de capas. El estilo de
dibujo (relleno/borde/grosor, pincel) se elige con clic derecho en cada herramienta,
ver tool_options_popover.py (LayerRow,
mismo patrón de fila-con-botones-propios que QueueItemCard en
gui/widgets/queue_panel.py, con look más compacto/tipo Photoshop: miniatura +
visibilidad + nombre en una sola línea, opacidad en una segunda línea sin label)."""
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSlider, QCheckBox, QSizePolicy, QMenu,
)

from gui.styles import get_theme_token
from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon

_KIND_ICON = {"image": "image.svg", "shape": "edit.svg", "raster": "content_cut.svg", "fill": "grid_view.svg",
              "text": "title4.svg"}


def _ignore_wheel(widget):
    """Evita que la rueda del mouse le cambie el valor a `widget` (comportamiento
    default de QSlider/QComboBox al pasar el cursor por encima) -- necesario aquí
    porque este panel flota LIBREMENTE encima de la vista previa (ver
    floating_panel.py); sin esto, intentar hacer zoom con la rueda mientras el
    cursor pasa cerca de un slider (tamaño de pincel, opacidad de una capa) le
    cambiaba el valor a ese control en vez de zoomear la imagen."""
    widget.wheelEvent = lambda event: event.ignore()


class LayerRow(QFrame):
    """Fila de una capa en la lista: visibilidad, miniatura, nombre, opacidad, subir/
    bajar, borrar. Se identifica por `layer_id` (Layer.id) en todas sus señales -- el
    panel no conoce la clase Layer directamente, solo ids, igual que QueueItemCard con
    job_id."""
    visibility_toggled = Signal(int, bool)
    opacity_changed = Signal(int, int)  # layer_id, 0-100
    move_up_requested = Signal(int)
    move_down_requested = Signal(int)
    delete_requested = Signal(int)
    row_clicked = Signal(int)
    rasterize_requested = Signal(int)

    def __init__(self, layer_id: int, name: str, kind: str, thumb_color: QColor | None,
                 parent=None, deletable: bool = True):
        super().__init__(parent)
        self.layer_id = layer_id
        self._kind = kind
        self._selected = False
        self._deletable = deletable
        self.setObjectName("layerRow")
        self._apply_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 5, 6, 5)
        layout.setSpacing(3)

        top = QHBoxLayout()
        top.setSpacing(5)
        self.check_visible = QCheckBox()
        self.check_visible.setChecked(True)
        self.check_visible.setFixedSize(20, 20)
        self.check_visible.setCursor(Qt.PointingHandCursor)
        self.check_visible.setStyleSheet("QCheckBox { spacing: 0px; }")
        self.check_visible.setToolTip(self.tr("Mostrar/ocultar capa"))
        self.check_visible.toggled.connect(lambda v: self.visibility_toggled.emit(self.layer_id, v))
        top.addWidget(self.check_visible)

        self.lbl_thumb = QLabel()
        self.lbl_thumb.setFixedSize(20, 20)
        self._set_thumb(kind, thumb_color)
        top.addWidget(self.lbl_thumb)

        self.lbl_name = QLabel(name)
        self.lbl_name.setStyleSheet(f"color: {get_theme_token('texto_principal', '#ffffff')}; font-size: 11px;")
        top.addWidget(self.lbl_name, 1)

        self.btn_up = self._mini_btn("arrow_upward_alt.svg", "#888888", self.tr("Subir"))
        self.btn_up.clicked.connect(lambda: self.move_up_requested.emit(self.layer_id))
        top.addWidget(self.btn_up)

        self.btn_down = self._mini_btn("arrow_downward_alt.svg", "#888888", self.tr("Bajar"))
        self.btn_down.clicked.connect(lambda: self.move_down_requested.emit(self.layer_id))
        top.addWidget(self.btn_down)

        self.btn_delete = self._mini_btn("close.svg", "#e74c3c", self.tr("Eliminar capa"))
        self.btn_delete.clicked.connect(lambda: self.delete_requested.emit(self.layer_id))
        top.addWidget(self.btn_delete)
        layout.addLayout(top)
        # setVisible recién aquí, cuando `top` ya cuelga de la fila y el botón tiene padre:
        # antes, sin padre, setVisible(True) lo abría un instante como ventana suelta que
        # le robaba la activación a la ventana principal (el teclado dejaba de llegar al
        # visor tras crear cada capa).
        self.btn_delete.setVisible(self._deletable)

        opacity_row = QHBoxLayout()
        opacity_row.setSpacing(4)
        opacity_row.addSpacing(25)  # alinea con el nombre, debajo de check+thumb
        self.slider_opacity = QSlider(Qt.Horizontal)
        self.slider_opacity.setFixedHeight(14)
        self.slider_opacity.setRange(0, 100)
        self.slider_opacity.setValue(100)
        self.slider_opacity.setCursor(Qt.PointingHandCursor)
        _ignore_wheel(self.slider_opacity)
        self.slider_opacity.valueChanged.connect(self._on_opacity_slider_changed)
        opacity_row.addWidget(self.slider_opacity, 1)
        self.lbl_opacity_val = QLabel("100%")
        self.lbl_opacity_val.setFixedWidth(30)
        self.lbl_opacity_val.setStyleSheet(f"color: {get_theme_token('texto_secundario', '#888888')}; font-size: 10px;")
        self.lbl_opacity_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        opacity_row.addWidget(self.lbl_opacity_val)
        layout.addLayout(opacity_row)

    def _set_thumb(self, kind: str, color: QColor | None):
        if color is not None:
            self.lbl_thumb.setStyleSheet(
                f"background-color: {color.name()}; border: 1px solid #444444; border-radius: 3px;"
            )
            return
        icon = get_colored_svg_icon(_KIND_ICON.get(kind, "image.svg"), "#888888", size=14)
        self.lbl_thumb.setStyleSheet(
            f"background-color: {get_theme_token('fondo_principal', '#121212')}; "
            f"border: 1px solid #444444; border-radius: 3px;"
        )
        if not icon.isNull():
            self.lbl_thumb.setPixmap(icon.pixmap(14, 14))
            self.lbl_thumb.setAlignment(Qt.AlignCenter)

    def _mini_btn(self, icon: str, color: str, tooltip: str) -> QPushButton:
        btn = QPushButton()
        btn.setIcon(get_colored_svg_icon(icon, color, size=11))
        btn.setToolTip(tooltip)
        btn.setFixedSize(15, 15)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet("""
            QPushButton {
                min-width: 15px; max-width: 15px;
                min-height: 15px; max-height: 15px;
                border: none;
                background: transparent;
                padding: 0px;
            }
        """)
        return btn

    def _on_opacity_slider_changed(self, value: int):
        self.lbl_opacity_val.setText(f"{value}%")
        self.opacity_changed.emit(self.layer_id, value)

    def set_selected(self, selected: bool):
        self._selected = selected
        self._apply_style()

    def _apply_style(self):
        bg = get_theme_token('fondo_hover', '#1a1a1a') if self._selected else get_theme_token('fondo_principal', '#121212')
        border = get_theme_token('acento_primario', '#B9E640') if self._selected else get_theme_token('borde', '#2d2d2d')
        self.setStyleSheet(f"""
            QFrame#layerRow {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 4px;
            }}
        """)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton:
            self.row_clicked.emit(self.layer_id)

    def contextMenuEvent(self, event):
        """Clic derecho: "Rasterizar capa" para formas y fondos (convertirlas en píxeles
        para poder borrarlas, como en Photoshop). Las demás capas no tienen menú."""
        if self._kind not in ("shape", "fill", "text"):
            return
        menu = QMenu(self)
        action = menu.addAction(self.tr("Rasterizar capa"))
        if menu.exec(event.globalPos()) is action:
            self.rasterize_requested.emit(self.layer_id)


class LayersPanel(QFrame):
    """Contenido del panel flotante "Capas": botón "+ Fondo" y lista de capas. Ni
    elige la herramienta activa ni su estilo (eso vive en los botones de la franja
    superior y en sus opciones por clic derecho, ver tool_options_popover.py).
    No conoce LayerStack directamente -- ImageToolsTab hace de puente (mismo criterio
    que los otros popovers de esta pestaña)."""
    add_background_requested = Signal()

    layer_visibility_toggled = Signal(int, bool)
    layer_opacity_changed = Signal(int, int)
    layer_move_up_requested = Signal(int)
    layer_move_down_requested = Signal(int)
    layer_delete_requested = Signal(int)
    layer_selected = Signal(int)
    layer_rasterize_requested = Signal(int)
    marked_changed = Signal()  # cambió la fila marcada (el visor redibuja su contorno)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("layersPanel")
        self._rows: dict[int, LayerRow] = {}
        self._selected_id: int | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(8)

        # -- Botón Fondo (acción de una sola vez, no un tool de dibujo) --
        self.btn_add_background = QPushButton(self.tr("+ Fondo"))
        self.btn_add_background.setCursor(Qt.PointingHandCursor)
        self.btn_add_background.clicked.connect(self.add_background_requested.emit)
        self.btn_add_background.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: 1px solid {get_theme_token('borde', '#333')};
                border-radius: 6px;
                color: {get_theme_token('texto_secundario', '#aaa')};
                padding: 4px;
            }}
            QPushButton:hover {{
                background-color: {get_theme_token('fondo_hover', '#1a1a1a')};
                color: {get_theme_token('texto_principal', '#fff')};
            }}
        """)
        layout.addWidget(self.btn_add_background)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"background-color: {get_theme_token('borde', '#2d2d2d')}; max-height: 1px; border: none;")
        layout.addWidget(sep)

        # -- Lista de capas -- SIN scroll horizontal (setHorizontalScrollBarPolicy
        # AlwaysOff): el ancho fijo del FloatingPanel ya alcanza para todo el
        # contenido de una fila (ver LayerRow), así que solo hace falta scroll
        # vertical si hay muchas capas.
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(4)
        self.scroll_layout.setAlignment(Qt.AlignTop)

        self.empty_lbl = QLabel(self.tr("Sin capas todavía"))
        self.empty_lbl.setStyleSheet(f"color: {get_theme_token('texto_secundario', '#888888')}; font-size: 11px;")
        self.empty_lbl.setAlignment(Qt.AlignCenter)
        self.scroll_layout.addWidget(self.empty_lbl)

        self.scroll.setWidget(self.scroll_content)
        self.scroll.setMinimumHeight(160)
        layout.addWidget(self.scroll, 1)

    # ------------------------------------------------------------------
    # Sincronización con LayerStack (llamado desde ImageToolsTab)
    # ------------------------------------------------------------------
    def rebuild_rows(self, layers: list):
        """`layers` = lista de Layer, orden bottom->top del stack. Se muestra invertida
        (arriba = capa de más adelante), igual que cualquier editor de capas."""
        for row in list(self._rows.values()):
            self.scroll_layout.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self._rows = {}

        self.empty_lbl.setVisible(len(layers) == 0)
        for layer in reversed(layers):
            thumb_color = self._thumb_color_for(layer)
            row = LayerRow(layer.id, layer.name, layer.kind, thumb_color, self.scroll_content,
                            deletable=(layer.kind != "image"))
            row.check_visible.setChecked(layer.visible)
            row.slider_opacity.setValue(int(layer.opacity * 100))
            row.visibility_toggled.connect(self.layer_visibility_toggled.emit)
            row.opacity_changed.connect(self.layer_opacity_changed.emit)
            row.move_up_requested.connect(self.layer_move_up_requested.emit)
            row.move_down_requested.connect(self.layer_move_down_requested.emit)
            row.delete_requested.connect(self.layer_delete_requested.emit)
            row.row_clicked.connect(self.layer_selected.emit)
            row.rasterize_requested.connect(self.layer_rasterize_requested.emit)
            self.scroll_layout.addWidget(row)
            self._rows[layer.id] = row

    def _thumb_color_for(self, layer) -> QColor | None:
        """Para capas de forma/fondo con relleno sólido, mostrar ese color como
        miniatura (más útil que un ícono genérico) -- None si no aplica (degradado,
        imagen, sin relleno), y LayerRow cae al ícono por tipo."""
        if layer.kind not in ("shape", "fill") or layer.graphics_item is None:
            return None
        brush_fn = getattr(layer.graphics_item, "brush", None)
        if brush_fn is None:
            return None
        try:
            b = brush_fn()
            if b.style() == Qt.SolidPattern:
                return b.color()
        except Exception:
            pass
        return None

    def select_row(self, layer_id: int | None):
        self._selected_id = layer_id
        for lid, row in self._rows.items():
            row.set_selected(lid == layer_id)
        self.marked_changed.emit()

    def selected_layer_id(self) -> int | None:
        """Capa marcada en la lista, o None si no hay ninguna (o si ya se borró)."""
        return self._selected_id if self._selected_id in self._rows else None
