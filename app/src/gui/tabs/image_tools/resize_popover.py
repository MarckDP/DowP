# src/gui/tabs/image_tools/resize_popover.py
"""Contenido del popover "Redimensionar" del Editor de Imagen: preset de escalado
(4K/2K/1080p/720p/480p/Personalizado, igual que DowP1 -- ver preset_map en
image_tools_tab.pyc decompilado, líneas 1456-1478) + método de interpolación.
Separado del panel "Convertir" (ver convert_panel.py, que solo tiene formato de
salida + sus opciones + destino) porque Redimensionar es una operación de tamaño,
no de codificación -- mismo criterio que Canvas/Reescalar IA/Eliminar Fondo: un
botón más de la franja superior con su propio popover (ver popover_button.py)."""
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QSpinBox
from PySide6.QtCore import Signal, QT_TRANSLATE_NOOP

from gui.styles import get_theme_token
from gui.widgets.combo_box import CheckmarkComboDelegate, AutoPopupComboBox
from core.constants import INTERPOLATION_METHODS

# (ancho, alto) por preset -- mismos valores que usaba DowP1 ("Máx" en la etiqueta:
# se aplican como límite manteniendo proporción, igual que _resize_raster_image()).
# None = "No escalar" (preset por defecto, equivale a Redimensionar desactivado).
# "custom" = habilita ancho/alto/proporción editables a mano ("Personalizado...").
_PRESETS = [
    (QT_TRANSLATE_NOOP("ResizePopoverContent", "No escalar (Original)"), None),
    (QT_TRANSLATE_NOOP("ResizePopoverContent", "4K UHD (Máx: 3840×2160)"), (3840, 2160)),
    (QT_TRANSLATE_NOOP("ResizePopoverContent", "2K QHD (Máx: 2560×1440)"), (2560, 1440)),
    (QT_TRANSLATE_NOOP("ResizePopoverContent", "1080p FHD (Máx: 1920×1080)"), (1920, 1080)),
    (QT_TRANSLATE_NOOP("ResizePopoverContent", "720p HD (Máx: 1280×720)"), (1280, 720)),
    (QT_TRANSLATE_NOOP("ResizePopoverContent", "480p SD (Máx: 854×480)"), (854, 480)),
    (QT_TRANSLATE_NOOP("ResizePopoverContent", "Personalizado..."), "custom"),
]


class ResizePopoverContent(QFrame):
    """selection_changed(is_active) -- is_active es False solo mientras el preset
    elegido sea "No escalar (Original)" (el default): ese es el único estado que no
    aplica ningún resize, igual que en DowP1 no había un checkbox "Activar" aparte,
    el preset por sí solo decidía si se escalaba o no."""
    selection_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("resizePopover")
        bg = get_theme_token('fondo_secundario', '#1e1e1e')
        border = get_theme_token('borde_normal', '#2d2d2d')
        self.setStyleSheet(f"""
            QFrame#resizePopover {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 8px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        title = QLabel(self.tr("Redimensionar"))
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(title)

        lbl_preset = QLabel(self.tr("Preset de escalado:"))
        lbl_preset.setObjectName("menuLabel")
        layout.addWidget(lbl_preset)
        self.combo_preset = AutoPopupComboBox(fit_contents=True)
        self.combo_preset.setItemDelegate(CheckmarkComboDelegate(self.combo_preset))
        for label, value in _PRESETS:
            self.combo_preset.addItem(self.tr(label), value)
        self.combo_preset.currentIndexChanged.connect(self._on_preset_changed)
        layout.addWidget(self.combo_preset)

        # -- Solo visible con "Personalizado..." -- en cualquier otro preset, ancho/
        # alto ya vienen fijos por _PRESETS y la proporción se mantiene siempre.
        self.custom_row = QHBoxLayout()
        self.spin_width = QSpinBox()
        self.spin_width.setRange(1, 20000)
        self.spin_width.setValue(1920)
        self.spin_width.setSuffix(" px")
        self.custom_row.addWidget(self.spin_width)
        self._lbl_x = QLabel("×")
        self.custom_row.addWidget(self._lbl_x)
        self.spin_height = QSpinBox()
        self.spin_height.setRange(1, 20000)
        self.spin_height.setValue(1080)
        self.spin_height.setSuffix(" px")
        self.custom_row.addWidget(self.spin_height)
        layout.addLayout(self.custom_row)

        self.chk_maintain_aspect = QCheckBox(self.tr("Mantener proporción"))
        self.chk_maintain_aspect.setChecked(True)
        layout.addWidget(self.chk_maintain_aspect)

        self.lbl_interp = QLabel(self.tr("Método de interpolación:"))
        self.lbl_interp.setObjectName("menuLabel")
        layout.addWidget(self.lbl_interp)
        self.combo_interpolation = AutoPopupComboBox(fit_contents=True)
        self.combo_interpolation.setItemDelegate(CheckmarkComboDelegate(self.combo_interpolation))
        for label in INTERPOLATION_METHODS:
            self.combo_interpolation.addItem(label, label)
        layout.addWidget(self.combo_interpolation)

        self._custom_widgets = [self.spin_width, self._lbl_x, self.spin_height, self.chk_maintain_aspect]
        self._interp_widgets = [self.lbl_interp, self.combo_interpolation]
        self._apply_preset_visibility(None)

    def _current_preset_value(self):
        return self.combo_preset.currentData()

    def _apply_preset_visibility(self, value):
        is_custom = value == "custom"
        is_off = value is None
        for w in self._custom_widgets:
            w.setVisible(is_custom)
        for w in self._interp_widgets:
            w.setVisible(not is_off)

    def _on_preset_changed(self, *_args):
        value = self._current_preset_value()
        self._apply_preset_visibility(value)
        self.selection_changed.emit(value is not None)

    def is_valid_selection(self) -> bool:
        return True

    def is_active(self) -> bool:
        """Ver UpscalePopoverContent.is_active(). Aquí "activo" es tener elegido un
        preset distinto de "No escalar (Original)" -- mismo criterio con el que se
        pinta el botón en verde (ver _on_preset_changed)."""
        return self._current_preset_value() is not None

    def deactivate(self):
        """Vuelve el preset a "No escalar (Original)" -- dispara
        selection_changed(False) vía la cascada existente (_on_preset_changed)."""
        self.combo_preset.setCurrentIndex(0)

    def get_settings(self) -> dict:
        value = self._current_preset_value()
        interpolation_method = self.combo_interpolation.currentData() or self.tr("Lanczos (Mejor Calidad)")

        if value is None:
            return {
                "resize_enabled": False, "resize_width": 0, "resize_height": 0,
                "resize_maintain_aspect": True, "interpolation_method": interpolation_method,
            }
        if value == "custom":
            return {
                "resize_enabled": True,
                "resize_width": self.spin_width.value(),
                "resize_height": self.spin_height.value(),
                "resize_maintain_aspect": self.chk_maintain_aspect.isChecked(),
                "interpolation_method": interpolation_method,
            }
        width, height = value
        return {
            "resize_enabled": True, "resize_width": width, "resize_height": height,
            # Los presets fijos son un límite ("Máx: WxH") -- siempre mantienen
            # proporción, igual que DowP1 (resize_aspect_lock forzado y bloqueado).
            "resize_maintain_aspect": True,
            "interpolation_method": interpolation_method,
        }
