# src/gui/tabs/image_tools/canvas_popover.py
from PySide6.QtCore import QCoreApplication
"""Contenido del popover "Canvas" del Editor de Imagen -- mismos valores y misma
matemática que usaba DowP 1 (image_tools_tab.pyc, canvas_master_frame, líneas
736-782 y 1162-1185; image_converter.pyc, _apply_canvas_by_option/
_calculate_canvas_position, líneas 1034-1123), pero además del campo numérico, la
geometría resultante (canvas_rect + posición/escala de la imagen) se empuja en vivo a
ZoomableImageViewer (ver apply_canvas_state) para poder verla y arrastrarla
directamente sobre la vista previa -- botón/menu igual, más edición visual encima.

Solo selección/estado: no aplica el canvas sobre los píxeles todavía (eso usa la misma
matemática pero contra un PIL.Image real, en un paso aparte)."""
from PySide6.QtCore import Signal, QRectF, QPointF
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
)

from gui.styles import get_theme_token
from gui.widgets.combo_box import AutoPopupComboBox
from core.constants import (
    CANVAS_OPTIONS, CANVAS_PRESET_SIZES, CANVAS_POSITIONS, CANVAS_OVERFLOW_MODES,
)

_MARGIN_MODES = ("Añadir Margen Externo", "Add External Margin")
_NONE_OPTION = "Sin ajuste"
_CUSTOM_OPTION = "Personalizado..."

_POSITION_ALIGN = {
    "Centro": ("center", "center"),
    "Arriba Izquierda": ("left", "top"),
    "Arriba Centro": ("center", "top"),
    "Arriba Derecha": ("right", "top"),
    "Centro Izquierda": ("left", "center"),
    "Centro Derecha": ("right", "center"),
    "Abajo Izquierda": ("left", "bottom"),
    "Abajo Centro": ("center", "bottom"),
    "Abajo Derecha": ("right", "bottom"),
    "Center": ("center", "center"),
    "Top Left": ("left", "top"),
    "Top Center": ("center", "top"),
    "Top Right": ("right", "top"),
    "Center Left": ("left", "center"),
    "Center Right": ("right", "center"),
    "Bottom Left": ("left", "bottom"),
    "Bottom Center": ("center", "bottom"),
    "Bottom Right": ("right", "bottom"),
}


def calc_position(canvas_w: float, canvas_h: float, img_w: float, img_h: float, position: str):
    """Misma fórmula que _calculate_canvas_position en DowP 1 (image_converter.pyc,
    líneas 1105-1123)."""
    h_align, v_align = _POSITION_ALIGN.get(position, ("center", "center"))
    if h_align == "left":
        x = 0
    elif h_align == "center":
        x = (canvas_w - img_w) / 2
    else:
        x = canvas_w - img_w
    if v_align == "top":
        y = 0
    elif v_align == "center":
        y = (canvas_h - img_h) / 2
    else:
        y = canvas_h - img_h
    return x, y


class CanvasPopoverContent(QFrame):
    """selection_changed(option, is_valid) -- is_valid es False solo para "Sin ajuste"
    (ya no significa "sin canvas visible", el canvas siempre se ve; solo indica si hay
    un ajuste con nombre elegido más allá del tamaño nativo por defecto).
    state_changed(dict) -- payload para ZoomableImageViewer.apply_canvas_state()."""
    selection_changed = Signal(str, bool)
    state_changed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("canvasPopover")
        bg = get_theme_token('fondo_secundario', '#1e1e1e')
        border = get_theme_token('borde_normal', '#2d2d2d')
        self.setStyleSheet(f"""
            QFrame#canvasPopover {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 8px;
            }}
        """)

        self._ref_w = 1000
        self._ref_h = 1000
        self._label_widgets = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        title = QLabel(self.tr("Ajustar Canvas (Lienzo)"))
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(title)

        option_row = QHBoxLayout()
        option_row.addWidget(self._label(self.tr("Ajuste:")))
        self.combo_option = AutoPopupComboBox(fit_contents=True)
        for opt in CANVAS_OPTIONS:
            self.combo_option.addItem(self._translated_option(opt), opt)
        # activated: dispara SIEMPRE que el usuario elige algo del desplegable, incluso
        # si re-elige la opción que ya estaba mostrada
        self.combo_option.activated.connect(self._on_combo_option_activated)
        option_row.addWidget(self.combo_option, 1)
        layout.addLayout(option_row)

        self.margin_row = QHBoxLayout()
        self.margin_row.addWidget(self._label(self.tr("Margen:")))
        self.entry_margin = QLineEdit("100")
        self.entry_margin.setFixedWidth(70)
        self.entry_margin.editingFinished.connect(self._on_fields_edited)
        self.margin_row.addWidget(self.entry_margin)
        self.margin_row.addWidget(QLabel("px"))
        self.margin_row.addStretch()
        layout.addLayout(self.margin_row)

        self.size_row = QHBoxLayout()
        self.size_row.addWidget(self._label(self.tr("Ancho:")))
        self.entry_width = QLineEdit()
        self.entry_width.setFixedWidth(70)
        self.entry_width.editingFinished.connect(self._on_fields_edited)
        self.size_row.addWidget(self.entry_width)
        self.size_row.addWidget(QLabel(self.tr("Alto:")))
        self.entry_height = QLineEdit()
        self.entry_height.setFixedWidth(70)
        self.entry_height.editingFinished.connect(self._on_fields_edited)
        self.size_row.addWidget(self.entry_height)
        self.size_row.addStretch()
        layout.addLayout(self.size_row)

        self.position_row = QHBoxLayout()
        self.position_row.addWidget(self._label(self.tr("Posición:")))
        self.combo_position = AutoPopupComboBox(fit_contents=True)
        for pos in CANVAS_POSITIONS:
            self.combo_position.addItem(self._translated_option(pos), pos)
        self.combo_position.currentIndexChanged.connect(self._on_fields_edited)
        self.position_row.addWidget(self.combo_position, 1)
        layout.addLayout(self.position_row)

        self.overflow_row = QHBoxLayout()
        self.overflow_row.addWidget(self._label(self.tr("Si excede:")))
        self.combo_overflow = AutoPopupComboBox(fit_contents=True)
        for mode in CANVAS_OVERFLOW_MODES:
            self.combo_overflow.addItem(self._translated_option(mode), mode)
        idx_def = self.combo_overflow.findData("Centrar (puede recortar)")
        if idx_def >= 0:
            self.combo_overflow.setCurrentIndex(idx_def)
        self.combo_overflow.currentIndexChanged.connect(self._on_fields_edited)
        self.overflow_row.addWidget(self.combo_overflow, 1)
        layout.addLayout(self.overflow_row)

        self._resize_label_column()
        self._update_rows_visibility(_NONE_OPTION)

    def _translated_option(self, value: str) -> str:
        """Traduce los valores de Ajuste/Posición/Si excede que vienen de CANVAS_OPTIONS/
        CANVAS_POSITIONS/CANVAS_OVERFLOW_MODES (core/constants.py). Esas listas deben
        seguir siendo texto crudo en español (son el valor canónico usado en
        image_converter.py) -- por eso la traducción se hace acá, explícita valor por
        valor, y no envolviendo la lista ni haciendo self.tr(variable) en el loop de
        abajo (pyside6-lupdate no puede extraer un self.tr() con argumento variable)."""
        table = {
            "Sin ajuste": self.tr("Sin ajuste"),
            "Añadir Margen Externo": self.tr("Añadir Margen Externo"),
            "Añadir Margen Interno": self.tr("Añadir Margen Interno"),
            "Personalizado...": self.tr("Personalizado..."),
            "Centro": self.tr("Centro"),
            "Arriba Izquierda": self.tr("Arriba Izquierda"),
            "Arriba Centro": self.tr("Arriba Centro"),
            "Arriba Derecha": self.tr("Arriba Derecha"),
            "Centro Izquierda": self.tr("Centro Izquierda"),
            "Centro Derecha": self.tr("Centro Derecha"),
            "Abajo Izquierda": self.tr("Abajo Izquierda"),
            "Abajo Centro": self.tr("Abajo Centro"),
            "Abajo Derecha": self.tr("Abajo Derecha"),
            "Reducir hasta que quepa": self.tr("Reducir hasta que quepa"),
            "Centrar (puede recortar)": self.tr("Centrar (puede recortar)"),
            "Recortar al canvas": self.tr("Recortar al canvas"),
            "Advertir y no procesar": self.tr("Advertir y no procesar"),
        }
        # Los presets con nombre propio (Instagram Post, YouTube Thumbnail, etc.) no
        # están en la tabla a propósito -- quedan igual en cualquier idioma.
        return table.get(value, value)

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(self.tr(text))
        self._label_widgets.append(lbl)
        return lbl

    def _resize_label_column(self):
        fm = QFontMetrics(self.font())
        width = max(fm.horizontalAdvance(w.text()) for w in self._label_widgets) + 6
        for w in self._label_widgets:
            w.setFixedWidth(width)

    def _current_canonical_option(self) -> str:
        idx = self.combo_option.currentIndex()
        if idx >= 0:
            return self.combo_option.itemData(idx) or self.combo_option.itemText(idx)
        return _NONE_OPTION

    def _on_combo_option_activated(self, index: int):
        opt = self.combo_option.itemData(index) or self.combo_option.itemText(index)
        self._on_option_changed(opt)

    def set_reference_image_size(self, w: int, h: int):
        """Tamaño nativo de la imagen actual -- usado como default de Ancho/Alto en
        Personalizado y como base de los cálculos de margen. Llamar al cargar cada
        archivo nuevo en el visor."""
        if w > 0 and h > 0:
            self._ref_w, self._ref_h = w, h

    def reset_to_none(self):
        """Deja el combo en "Sin ajuste" sin empujar ningún estado -- se usa al
        cambiar de archivo, ANTES de que ZoomableImageViewer.set_pixmap() cargue la
        imagen nueva y reinicialice el canvas solo (a su tamaño nativo, ver
        _reset_edit_state ahí); empujar aquí usaría el `_ref_w/_ref_h` todavía viejo."""
        self.combo_option.blockSignals(True)
        idx = self.combo_option.findData(_NONE_OPTION)
        if idx >= 0:
            self.combo_option.setCurrentIndex(idx)
        else:
            self.combo_option.setCurrentText(self.tr(_NONE_OPTION))
        self.combo_option.blockSignals(False)
        self._update_rows_visibility(_NONE_OPTION)
        self.selection_changed.emit(_NONE_OPTION, False)

    def is_valid_selection(self) -> bool:
        return self._current_canonical_option() not in (_NONE_OPTION, "Sin ajuste", "No adjustment")

    def _update_rows_visibility(self, option: str):
        is_margin = option in _MARGIN_MODES
        is_sized = option in CANVAS_PRESET_SIZES or option in (_CUSTOM_OPTION, "Custom...")
        for i in range(self.margin_row.count()):
            w = self.margin_row.itemAt(i).widget()
            if w:
                w.setVisible(is_margin)
        for i in range(self.size_row.count()):
            w = self.size_row.itemAt(i).widget()
            if w:
                w.setVisible(is_sized)
        for i in range(self.position_row.count()):
            w = self.position_row.itemAt(i).widget()
            if w:
                w.setVisible(option not in (_NONE_OPTION, "Sin ajuste", "No adjustment"))
        for i in range(self.overflow_row.count()):
            w = self.overflow_row.itemAt(i).widget()
            if w:
                w.setVisible(is_sized)
        editable = option in (_CUSTOM_OPTION, "Custom...")
        self.entry_width.setReadOnly(not editable)
        self.entry_height.setReadOnly(not editable)

    def _on_option_changed(self, option: str):
        self._update_rows_visibility(option)
        if option in (_CUSTOM_OPTION, "Custom..."):
            self.entry_width.setText(str(self._ref_w))
            self.entry_height.setText(str(self._ref_h))
        elif option in CANVAS_PRESET_SIZES:
            w, h = CANVAS_PRESET_SIZES[option]
            self.entry_width.setText(str(w))
            self.entry_height.setText(str(h))
        is_valid = option not in (_NONE_OPTION, "Sin ajuste", "No adjustment")
        self.selection_changed.emit(option, is_valid)
        self._push_state(option)

    def _on_fields_edited(self):
        self._push_state(self._current_canonical_option())

    def _int_or(self, text: str, default: int) -> int:
        try:
            return max(0, int(text))
        except ValueError:
            return default

    def _push_state(self, option: str):
        params = self._build_canvas_params(option)
        if params is None:
            return
        self.state_changed.emit(params)

    def _build_canvas_params(self, option: str):
        native_w, native_h = self._ref_w, self._ref_h
        if option in (_NONE_OPTION, "Sin ajuste", "No adjustment"):
            # El canvas se ve y se puede arrastrar SIEMPRE (ver zoomable_image_viewer.
            # _reset_edit_state) -- "Sin ajuste" ya no oculta el overlay, solo lo
            # resetea al tamaño nativo de la imagen (equivalente a lo que ya hace
            # set_pixmap() al cargar un archivo nuevo).
            canvas_w, canvas_h = native_w, native_h
            img_w, img_h = native_w, native_h
            scale = (1.0, 1.0)
            mode, resizable = "free", True
        elif option in _MARGIN_MODES:
            margin = self._int_or(self.entry_margin.text(), 100)
            canvas_w, canvas_h = native_w + margin * 2, native_h + margin * 2
            img_w, img_h = native_w, native_h
            scale = (1.0, 1.0)
            mode, resizable = "margin_external", True
        elif option in CANVAS_PRESET_SIZES:
            canvas_w, canvas_h = CANVAS_PRESET_SIZES[option]
            img_w, img_h = native_w, native_h
            scale = (1.0, 1.0)
            # resizable=True: los presets son solo un punto de partida rápido -- el
            # usuario pidió poder seguir ajustándolos a mano después de elegirlos, no
            # que queden fijos.
            mode, resizable = "free", True
        elif option in (_CUSTOM_OPTION, "Custom..."):
            canvas_w = self._int_or(self.entry_width.text(), native_w)
            canvas_h = self._int_or(self.entry_height.text(), native_h)
            img_w, img_h = native_w, native_h
            scale = (1.0, 1.0)
            mode, resizable = "free", True
        else:
            return None

        pos_idx = self.combo_position.currentIndex()
        position = self.combo_position.itemData(pos_idx) if pos_idx >= 0 else self.combo_position.currentText()
        pos_x, pos_y = calc_position(canvas_w, canvas_h, img_w, img_h, position)
        return {
            "canvas_rect": QRectF(0, 0, canvas_w, canvas_h),
            "mode": mode,
            "resizable": resizable,
            "image_pos": QPointF(pos_x, pos_y),
            "image_scale": scale,
        }

    def on_margin_dragged(self, margin: int):
        self.entry_margin.blockSignals(True)
        self.entry_margin.setText(str(margin))
        self.entry_margin.blockSignals(False)

    def on_size_dragged(self, w: int, h: int):
        self.entry_width.blockSignals(True)
        self.entry_height.blockSignals(True)
        self.entry_width.setText(str(w))
        self.entry_height.setText(str(h))
        self.entry_width.blockSignals(False)
        self.entry_height.blockSignals(False)

    def get_settings(self) -> dict:
        """Mismo criterio que ResizePopoverContent/UpscalePopoverContent: junta la
        configuración de LOTE (el preset elegido aquí) para que ImageConverter la
        aplique a cada archivo al convertir -- ver _apply_canvas() en
        core/tabs/image_tools/image_converter.py. La edición visual en vivo
        (state_changed/apply_canvas_state) es un concepto aparte, sin cambios aquí."""
        canonical_option = self._current_canonical_option()
        pos_idx = self.combo_position.currentIndex()
        pos = self.combo_position.itemData(pos_idx) if pos_idx >= 0 else self.combo_position.currentText()
        over_idx = self.combo_overflow.currentIndex()
        over = self.combo_overflow.itemData(over_idx) if over_idx >= 0 else self.combo_overflow.currentText()
        return {
            "canvas_enabled": self.is_valid_selection(),
            "canvas_option": canonical_option,
            "canvas_margin": self._int_or(self.entry_margin.text(), 100),
            "canvas_width": self._int_or(self.entry_width.text(), self._ref_w),
            "canvas_height": self._int_or(self.entry_height.text(), self._ref_h),
            "canvas_position": pos,
            "canvas_overflow_mode": over,
        }

    def sync(self):
        """Reemite el estado actual -- llamar al reabrir el popover, por si cambió el
        tamaño de referencia de la imagen desde la última vez."""
        option = self._current_canonical_option()
        if option in (_CUSTOM_OPTION, "Custom...") and not self.entry_width.isModified():
            self.entry_width.setText(str(self._ref_w))
            self.entry_height.setText(str(self._ref_h))
        self._push_state(option)
