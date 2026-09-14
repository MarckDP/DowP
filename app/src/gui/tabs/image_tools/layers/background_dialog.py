# src/gui/tabs/image_tools/layers/background_dialog.py
"""Diálogo modal "+ Fondo" del panel de Capas -- a diferencia de las figuras/pincel
(que se dibujan a mano sobre la vista previa), un fondo es una acción de "crear una
sola vez", así que es un QDialog en vez de un popover que se ajusta en vivo. Mismos
tipos/direcciones que usaba DowP 1 (BACKGROUND_TYPES/GRADIENT_DIRECTIONS en
core/constants.py), pero el degradado se pinta con QLinearGradient/QRadialGradient
nativos de Qt en vez del loop píxel-por-píxel de PIL (image_converter.pyc_Decompiled.py
:1173-1221) -- mismo resultado visual, directo para la escena interactiva."""
import os
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QBrush, QLinearGradient, QRadialGradient, QPixmap
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton, QFrame,
    QFileDialog, QDialogButtonBox, QSizePolicy,
)

from gui.styles import get_theme_token
from gui.dialogs.dialogs import AdobeColorPickerDialog
from core.constants import BACKGROUND_TYPES, GRADIENT_DIRECTIONS

# BACKGROUND_TYPES/GRADIENT_DIRECTIONS ya vienen traducidos desde constants.py (evaluado
# una sola vez al importar, ver i18n.py) -- comparar contra estos alias en vez de volver a
# llamar self.tr() sobre el literal en español evita mantener la misma traducción
# duplicada en dos contextos distintos (constants + BackgroundDialog) que podrían
# desincronizarse.
_TYPE_SOLID, _TYPE_GRADIENT, _TYPE_IMAGE = BACKGROUND_TYPES
_DIR_HORIZONTAL, _DIR_VERTICAL, _DIR_DIAG_DOWN, _DIR_DIAG_UP, _DIR_RADIAL = GRADIENT_DIRECTIONS


class BackgroundDialog(QDialog):
    def __init__(self, canvas_width: int, canvas_height: int, parent=None):
        super().__init__(parent)
        self._w = max(1, canvas_width)
        self._h = max(1, canvas_height)
        self._color1 = QColor("#3498db")
        self._color2 = QColor("#e74c3c")
        self._image_path = None

        self.setWindowTitle(self.tr("Agregar Fondo"))
        self.setFixedWidth(320)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel(self.tr("Tipo:")))
        self.combo_type = QComboBox()
        self.combo_type.addItems(BACKGROUND_TYPES)
        self.combo_type.currentTextChanged.connect(self._on_type_changed)
        type_row.addWidget(self.combo_type, 1)
        layout.addLayout(type_row)

        self.color1_row = QHBoxLayout()
        self.color1_row.addWidget(QLabel(self.tr("Color:")))
        self.btn_color1 = self._swatch(self._color1)
        self.btn_color1.clicked.connect(self._pick_color1)
        self.color1_row.addWidget(self.btn_color1)
        self.color1_row.addStretch()
        layout.addLayout(self.color1_row)

        self.color2_row = QHBoxLayout()
        self.color2_row.addWidget(QLabel(self.tr("Color 2:")))
        self.btn_color2 = self._swatch(self._color2)
        self.btn_color2.clicked.connect(self._pick_color2)
        self.color2_row.addWidget(self.btn_color2)
        self.color2_row.addStretch()
        layout.addLayout(self.color2_row)

        self.direction_row = QHBoxLayout()
        self.direction_row.addWidget(QLabel(self.tr("Dirección:")))
        self.combo_direction = QComboBox()
        self.combo_direction.addItems(GRADIENT_DIRECTIONS)
        self.combo_direction.currentTextChanged.connect(self._update_preview)
        self.direction_row.addWidget(self.combo_direction, 1)
        layout.addLayout(self.direction_row)

        self.image_row = QHBoxLayout()
        self.btn_pick_image = QPushButton(self.tr("Elegir imagen..."))
        self.btn_pick_image.clicked.connect(self._pick_image)
        self.image_row.addWidget(self.btn_pick_image)
        self.lbl_image_name = QLabel(self.tr("(ninguna)"))
        self.lbl_image_name.setStyleSheet(f"color: {get_theme_token('texto_secundario', '#888')};")
        self.image_row.addWidget(self.lbl_image_name, 1)
        layout.addLayout(self.image_row)

        self.preview = QFrame()
        self.preview.setFixedHeight(60)
        self.preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(self.preview)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._on_type_changed(self.combo_type.currentText())

    def _swatch(self, color: QColor) -> QPushButton:
        btn = QPushButton()
        btn.setFixedSize(24, 24)
        btn.setCursor(Qt.PointingHandCursor)
        self._apply_swatch_style(btn, color)
        return btn

    def _apply_swatch_style(self, btn: QPushButton, color: QColor):
        btn.setStyleSheet(f"""
            QPushButton {{
                min-width: 22px; max-width: 22px;
                min-height: 22px; max-height: 22px;
                background-color: {color.name()};
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 0px;
            }}
            QPushButton:hover {{
                border-color: {get_theme_token('acento_primario', '#B9E640')};
            }}
        """)

    def _pick_color1(self):
        dialog = AdobeColorPickerDialog(self._color1.name(), self)
        if dialog.exec():
            self._color1 = QColor(dialog.get_color())
            self._apply_swatch_style(self.btn_color1, self._color1)
            self._update_preview()

    def _pick_color2(self):
        dialog = AdobeColorPickerDialog(self._color2.name(), self)
        if dialog.exec():
            self._color2 = QColor(dialog.get_color())
            self._apply_swatch_style(self.btn_color2, self._color2)
            self._update_preview()

    def _pick_image(self):
        path, _ = QFileDialog.getOpenFileName(self, self.tr("Elegir imagen de fondo"), "", self.tr("Imágenes (*.png *.jpg *.jpeg *.webp *.bmp)"))
        if path:
            self._image_path = path
            self.lbl_image_name.setText(os.path.basename(path))
            self._update_preview()

    def _on_type_changed(self, kind: str):
        is_solid = kind == _TYPE_SOLID
        is_gradient = kind == _TYPE_GRADIENT
        is_image = kind == _TYPE_IMAGE
        for i in range(self.color1_row.count()):
            w = self.color1_row.itemAt(i).widget()
            if w:
                w.setVisible(is_solid or is_gradient)
        for i in range(self.color2_row.count()):
            w = self.color2_row.itemAt(i).widget()
            if w:
                w.setVisible(is_gradient)
        for i in range(self.direction_row.count()):
            w = self.direction_row.itemAt(i).widget()
            if w:
                w.setVisible(is_gradient)
        for i in range(self.image_row.count()):
            w = self.image_row.itemAt(i).widget()
            if w:
                w.setVisible(is_image)
        self._update_preview()

    def _build_brush(self) -> QBrush:
        kind = self.combo_type.currentText()
        if kind == _TYPE_SOLID:
            return QBrush(self._color1)
        if kind == _TYPE_GRADIENT:
            direction = self.combo_direction.currentText()
            w, h = self._w, self._h
            if direction == _DIR_HORIZONTAL:
                grad = QLinearGradient(0, 0, w, 0)
            elif direction == _DIR_VERTICAL:
                grad = QLinearGradient(0, 0, 0, h)
            elif direction == _DIR_DIAG_DOWN:
                grad = QLinearGradient(0, 0, w, h)
            elif direction == _DIR_DIAG_UP:
                grad = QLinearGradient(w, 0, 0, h)
            else:  # _DIR_RADIAL
                grad = QRadialGradient(w / 2, h / 2, max(w, h) / 2)
            grad.setColorAt(0.0, self._color1)
            grad.setColorAt(1.0, self._color2)
            return QBrush(grad)
        return QBrush(QColor("#ffffff"))

    def _update_preview(self):
        kind = self.combo_type.currentText()
        if kind == _TYPE_IMAGE and self._image_path:
            path_css = self._image_path.replace("\\", "/")
            self.preview.setStyleSheet(
                f"border: 1px solid {get_theme_token('borde', '#333')}; border-radius: 4px; "
                f"background-image: url({path_css}); background-position: center; background-repeat: no-repeat;"
            )
            return
        # QFrame no soporta QBrush directo por stylesheet -- para sólido/degradado se
        # aproxima con qlineargradient CSS (suficiente para la previsualización; el
        # resultado real que se aplica a la capa usa el QBrush nativo, no esta
        # aproximación, ver _build_brush()/build_layer_item()).
        if kind == _TYPE_SOLID:
            self.preview.setStyleSheet(
                f"background-color: {self._color1.name()}; border: 1px solid {get_theme_token('borde', '#333')}; border-radius: 4px;"
            )
        elif kind == _TYPE_GRADIENT:
            self.preview.setStyleSheet(
                f"background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {self._color1.name()}, stop:1 {self._color2.name()});"
                f"border: 1px solid {get_theme_token('borde', '#333')}; border-radius: 4px;"
            )
        else:
            self.preview.setStyleSheet(f"border: 1px solid {get_theme_token('borde', '#333')}; border-radius: 4px; background-color: #ffffff;")

    def build_layer_item(self):
        """Devuelve el QGraphicsItem ya armado para insertar como capa de fondo."""
        from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsPixmapItem
        kind = self.combo_type.currentText()
        if kind == _TYPE_IMAGE and self._image_path and os.path.exists(self._image_path):
            pix = QPixmap(self._image_path)
            if not pix.isNull():
                # Estirado exacto al canvas, sin recorte -- mismo criterio que
                # _apply_background en DowP 1 (background.resize((w,h))).
                scaled = pix.scaled(self._w, self._h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                item = QGraphicsPixmapItem(scaled)
                return item
        item = QGraphicsRectItem(QRectF(0, 0, self._w, self._h))
        item.setPen(Qt.NoPen)
        item.setBrush(self._build_brush())
        return item
