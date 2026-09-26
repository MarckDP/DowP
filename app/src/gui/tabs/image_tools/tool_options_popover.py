# src/gui/tabs/image_tools/tool_options_popover.py
"""Opciones de las herramientas de dibujo del Editor de Imagen (Rectángulo/Elipse,
Línea, Pincel), abiertas con clic derecho sobre su botón -- mismo patrón que Canvas
(ver popover_button.py, left_click_opens=False). Reemplaza las filas de estilo que
vivían dentro del panel de Capas, que ahora queda solo para capas.

Cada modo edita su propio juego de ajustes ("shape" lo comparten Rectángulo y
Elipse). El estado vive en ImageToolsTab (que lo persiste y lo aplica al visor y a
la forma seleccionada); este widget solo lo muestra y avisa de cada cambio con
option_changed(mode, key, value), de a una opción por vez, para que al aplicarlo a
una forma ya dibujada solo cambie lo que el usuario tocó."""
from PySide6.QtCore import Qt, Signal, QPointF
from PySide6.QtGui import QColor, QFont, QPainter, QPolygonF
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox, QSlider, QSpinBox,
    QFontComboBox, QComboBox,
)
from gui.tabs.image_tools.layers.text_item import DEFAULT_TEXT_STYLE

from gui.styles import get_theme_token
from gui.widgets.popover_button import PopoverTriggerButton


# Valores por defecto de cada modo -- también la forma del dict que se persiste.
DEFAULT_TOOL_STYLES = {
    "shape": {"fill": "#3498db", "fill_enabled": True,
              "stroke": "#1a1a1a", "stroke_enabled": True, "stroke_width": 2},
    "line": {"color": "#1a1a1a", "width": 3},
    "brush": {"color": "#3498db", "size": 12},
    "eraser": {"size": 30, "softness": 0},
    "text": dict(DEFAULT_TEXT_STYLE),
}

# Qué modo de opciones usa cada herramienta.
TOOL_OPTION_MODE = {"rect": "shape", "ellipse": "shape", "line": "line", "brush": "brush",
                    "eraser": "eraser", "text": "text"}


class ToolOptionsButton(PopoverTriggerButton):
    """Botón de herramienta con opciones por clic derecho: igual que
    PopoverTriggerButton, más una marquita en la esquina inferior derecha (como el
    triangulito de Photoshop) para que se note que tiene opciones."""

    def __init__(self, host, content, parent=None):
        super().__init__(host=host, content=content, parent=parent, left_click_opens=False)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        # Sobre el fondo de acento (botón activo) el icono va en negro; la marca igual.
        painter.setBrush(QColor("#000000" if self.isChecked() else "#8a8fa3"))
        w, h = self.width(), self.height()
        painter.drawPolygon(QPolygonF([QPointF(w - 3, h - 8), QPointF(w - 3, h - 3), QPointF(w - 8, h - 3)]))
        painter.end()


def _ignore_wheel(widget):
    widget.setFocusPolicy(Qt.StrongFocus)
    widget.wheelEvent = lambda event: event.ignore()


class ToolOptionsPopoverContent(QFrame):
    option_changed = Signal(str, str, object)  # modo, clave, valor

    def __init__(self, mode: str, parent=None):
        super().__init__(parent)
        assert mode in DEFAULT_TOOL_STYLES
        self.mode = mode
        self._values = dict(DEFAULT_TOOL_STYLES[mode])
        self._loading = False

        self.setObjectName("toolOptionsPopover")
        self.setStyleSheet(f"""
            QFrame#toolOptionsPopover {{
                background-color: {get_theme_token('fondo_secundario', '#1e1e1e')};
                border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                border-radius: 8px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        titles = {
            "shape": self.tr("Rectángulo y elipse"),
            "line": self.tr("Línea"),
            "brush": self.tr("Pincel"),
            "eraser": self.tr("Borrador"),
            "text": self.tr("Texto"),
        }
        title = QLabel(titles[mode])
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(title)

        if mode == "shape":
            self.btn_fill, self.chk_no_fill = self._color_row(
                layout, self.tr("Relleno"), "fill", self.tr("Sin relleno"), "fill_enabled")
            self.btn_stroke, self.chk_no_stroke = self._color_row(
                layout, self.tr("Borde"), "stroke", self.tr("Sin borde"), "stroke_enabled")
            self.slider_width, self.spin_width = self._size_row(
                layout, self.tr("Grosor del borde"), "stroke_width", 1, 50)
        elif mode == "line":
            self.btn_color, _ = self._color_row(layout, self.tr("Color"), "color")
            self.slider_width, self.spin_width = self._size_row(layout, self.tr("Grosor"), "width", 1, 50)
        elif mode == "brush":
            self.btn_color, _ = self._color_row(layout, self.tr("Color"), "color")
            self.slider_size, self.spin_size = self._size_row(layout, self.tr("Tamaño"), "size", 1, 200)
        elif mode == "text":
            self._build_text_controls(layout)
        else:
            self.slider_size, self.spin_size = self._size_row(layout, self.tr("Tamaño"), "size", 1, 300)
            self.slider_softness, self.spin_softness = self._size_row(
                layout, self.tr("Suavizado"), "softness", 0, 100, suffix=" %")

        hints = {
            "shape": self.tr("Los cambios también se aplican a la forma seleccionada."),
            "line": self.tr("Los cambios también se aplican a la forma seleccionada."),
            "eraser": self.tr("Borra solo la capa marcada en Capas. Las formas y los fondos se "
                              "convierten en píxeles para poder borrarlos. La imagen original no "
                              "se modifica."),
            "text": self.tr("Clic en la imagen para escribir; Esc o clic afuera para terminar. Los "
                            "cambios se aplican al texto que estás editando o al seleccionado."),
        }
        if mode in hints:
            hint = QLabel(hints[mode])
            hint.setWordWrap(True)
            hint.setStyleSheet(f"color: {get_theme_token('texto_secundario', '#888888')}; font-size: 11px;")
            layout.addWidget(hint)

        self._sync_enabled_state()

    # -- Construcción ---------------------------------------------------------
    def _build_text_controls(self, layout):
        lbl = QLabel(self.tr("Fuente"))
        layout.addWidget(lbl)
        self.font_combo = QFontComboBox()
        self.font_combo.setMaximumWidth(260)
        self.font_combo.currentFontChanged.connect(lambda f: self._set("family", f.family()))
        layout.addWidget(self.font_combo)
        self.slider_size, self.spin_size = self._size_row(layout, self.tr("Tamaño"), "size", 6, 400)
        self.btn_color, _ = self._color_row(layout, self.tr("Color"), "color")
        row = QHBoxLayout()
        row.setSpacing(12)
        self.chk_bold = QCheckBox(self.tr("Negrita"))
        self.chk_bold.toggled.connect(lambda v: self._set("bold", v))
        row.addWidget(self.chk_bold)
        self.chk_italic = QCheckBox(self.tr("Cursiva"))
        self.chk_italic.toggled.connect(lambda v: self._set("italic", v))
        row.addWidget(self.chk_italic)
        row.addStretch()
        layout.addLayout(row)
        align_row = QHBoxLayout()
        align_row.addWidget(QLabel(self.tr("Alineación")))
        self.combo_align = QComboBox()
        for label, value in ((self.tr("Izquierda"), "left"), (self.tr("Centro"), "center"),
                             (self.tr("Derecha"), "right")):
            self.combo_align.addItem(label, value)
        self.combo_align.currentIndexChanged.connect(
            lambda _i: self._set("align", self.combo_align.currentData()))
        align_row.addWidget(self.combo_align, 1)
        layout.addLayout(align_row)


    def _color_row(self, layout, label_text, color_key, none_text=None, enabled_key=None):
        row = QHBoxLayout()
        row.setSpacing(8)
        lbl = QLabel(label_text)
        lbl.setMinimumWidth(56)
        row.addWidget(lbl)
        btn = QPushButton()
        btn.setFixedSize(28, 22)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip(self.tr("Elegir color"))
        btn.clicked.connect(lambda: self._pick_color(color_key, btn))
        row.addWidget(btn)
        chk = None
        if none_text:
            chk = QCheckBox(none_text)
            chk.toggled.connect(lambda checked: self._set(enabled_key, not checked))
            row.addWidget(chk)
        row.addStretch()
        layout.addLayout(row)
        self._paint_swatch(btn, QColor(self._values[color_key]))
        return btn, chk

    def _size_row(self, layout, label_text, key, minimum, maximum, suffix=" px"):
        lbl = QLabel(label_text)
        layout.addWidget(lbl)
        row = QHBoxLayout()
        row.setSpacing(8)
        slider = QSlider(Qt.Horizontal)
        slider.setRange(minimum, maximum)
        _ignore_wheel(slider)
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSuffix(suffix)
        spin.setFixedWidth(88)
        slider.valueChanged.connect(spin.setValue)
        spin.valueChanged.connect(slider.setValue)
        spin.valueChanged.connect(lambda v: self._set(key, v))
        row.addWidget(slider, 1)
        row.addWidget(spin)
        layout.addLayout(row)
        spin.setValue(self._values[key])
        return slider, spin

    def _paint_swatch(self, btn, color: QColor):
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {color.name()};
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 0px;
            }}
            QPushButton:hover {{ border-color: {get_theme_token('acento_primario', '#B9E640')}; }}
            QPushButton:disabled {{ background-color: #2a2a2a; border-color: #3a3a3a; }}
        """)

    # -- Estado ---------------------------------------------------------------
    def _set(self, key, value):
        if self._values.get(key) == value:
            return
        self._values[key] = value
        self._sync_enabled_state()
        if not self._loading:
            self.option_changed.emit(self.mode, key, value)

    def _pick_color(self, key, btn):
        from gui.dialogs.dialogs import AdobeColorPickerDialog
        dialog = AdobeColorPickerDialog(self._values[key], self.window())
        if dialog.exec():
            color = QColor(dialog.get_color())
            self._paint_swatch(btn, color)
            self._set(key, color.name())

    def _sync_enabled_state(self):
        if self.mode != "shape":
            return
        self.btn_fill.setEnabled(self._values["fill_enabled"])
        stroke_on = self._values["stroke_enabled"]
        self.btn_stroke.setEnabled(stroke_on)
        self.slider_width.setEnabled(stroke_on)
        self.spin_width.setEnabled(stroke_on)

    def load(self, values: dict):
        """Muestra `values` sin emitir option_changed (se llama al abrir el popover,
        para reflejar lo que hayan cambiado otros popovers del mismo modo)."""
        self._loading = True
        try:
            self._values = {**DEFAULT_TOOL_STYLES[self.mode], **values}
            if self.mode == "shape":
                self._paint_swatch(self.btn_fill, QColor(self._values["fill"]))
                self._paint_swatch(self.btn_stroke, QColor(self._values["stroke"]))
                self.chk_no_fill.setChecked(not self._values["fill_enabled"])
                self.chk_no_stroke.setChecked(not self._values["stroke_enabled"])
                self.spin_width.setValue(self._values["stroke_width"])
            elif self.mode == "line":
                self._paint_swatch(self.btn_color, QColor(self._values["color"]))
                self.spin_width.setValue(self._values["width"])
            elif self.mode == "brush":
                self._paint_swatch(self.btn_color, QColor(self._values["color"]))
                self.spin_size.setValue(self._values["size"])
            elif self.mode == "text":
                family = self._values["family"]
                self.font_combo.setCurrentFont(QFont(family) if family else QFont())
                self.spin_size.setValue(self._values["size"])
                self._paint_swatch(self.btn_color, QColor(self._values["color"]))
                self.chk_bold.setChecked(self._values["bold"])
                self.chk_italic.setChecked(self._values["italic"])
                self.combo_align.setCurrentIndex(max(0, self.combo_align.findData(self._values["align"])))
            else:
                self.spin_size.setValue(self._values["size"])
                self.spin_softness.setValue(self._values["softness"])
            self._sync_enabled_state()
        finally:
            self._loading = False
