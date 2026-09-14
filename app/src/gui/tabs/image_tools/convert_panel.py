# src/gui/tabs/image_tools/convert_panel.py
import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFrame, QLabel, QComboBox, QCheckBox,
    QSlider, QScrollArea, QSizePolicy, QStackedWidget,
)
from PySide6.QtCore import Signal, Qt

from gui.styles import get_theme_token
from gui.widgets.combo_box import CheckmarkComboDelegate, AutoPopupComboBox
from core.tabs.image_tools.convert_options import (
    OUTPUT_FORMATS, JPG_SUBSAMPLING_OPTIONS, TIFF_COMPRESSION_OPTIONS,
    ICO_SIZES, ICO_DEFAULT_SIZES, ICNS_SIZES, ICNS_DEFAULT_SIZES,
    default_options_for_format,
)

_MAX_VISIBLE_COMBO_ITEMS = 12


class ConvertPanel(QWidget):
    """Panel "Convertir" del Editor de Imagen -- formato de salida + sus opciones,
    encapsulado todo dentro de una misma tarjeta visual. Redimensionar vive
    aparte en su propio popover, y las opciones de destino (ruta, conflicto,
    botón Convertir y barra de progreso) viven en la barra inferior unificada."""

    validity_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ico_checkboxes = {}
        self._icns_checkboxes = {}
        self._init_ui()
        self._on_format_changed()

    # ─── UI ──────────────────────────────────────────────────────

    def _init_ui(self):
        self.setObjectName("convertPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Tarjeta unificada "Formato de salida" que encapsula selector + opciones
        frame_format, fv = self._card_frame(self.tr("Formato de salida"), self)
        self.combo_format = AutoPopupComboBox(frame_format)
        self._setup_fixed_combo(self.combo_format)
        for fmt in OUTPUT_FORMATS:
            self.combo_format.addItem(fmt, fmt)
        self.combo_format.currentIndexChanged.connect(self._on_format_changed)
        fv.addWidget(self.combo_format)

        # Divisor sutil entre el selector y las opciones del formato
        sep = QFrame(frame_format)
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"background-color: {get_theme_token('borde_sutil', '#2d2d2d')}; max-height: 1px; border: none;")
        fv.addWidget(sep)

        self.format_stack = QStackedWidget(frame_format)
        self._build_format_pages(frame_format)
        fv.addWidget(self.format_stack)

        layout.addWidget(frame_format)

    def _card_frame(self, title: str | None, parent=None) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame(parent or self)
        frame.setObjectName("advancedCard")
        border_color = get_theme_token('borde_normal', '#2d2d2d')
        bg_color = get_theme_token('fondo_secundario', '#1e1e1e')
        # Eliminado el estilo de tarjeta para permitir unificación externa
        frame.setStyleSheet("""
            QFrame#advancedCard {
                background-color: transparent;
                border: none;
            }
        """)
        frame.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        v = QVBoxLayout(frame)
        v.setContentsMargins(12, 10, 12, 12)
        v.setSpacing(8)
        if title:
            lbl = QLabel(title, frame)
            lbl.setObjectName("sectionTitle")
            lbl.setAlignment(Qt.AlignCenter)
            v.addWidget(lbl)
        return frame, v

    def _translated_fixed_option(self, value: str) -> str:
        """Traduce las opciones de JPG_SUBSAMPLING_OPTIONS/TIFF_COMPRESSION_OPTIONS
        (core/tabs/image_tools/convert_options.py) para mostrarlas -- esas listas deben
        seguir siendo texto crudo en español porque image_converter.py las usa como
        clave de un dict local (subsampling_map/compression_map) con las mismas claves en
        español; traducirlas en la lista rompería ese lookup. Por eso la traducción es
        solo de display, acá, valor por valor (self.tr() con argumento variable no lo
        puede extraer pyside6-lupdate)."""
        table = {
            "4:2:0 (Estándar)": self.tr("4:2:0 (Estándar)"),
            "4:2:2 (Alta)": self.tr("4:2:2 (Alta)"),
            "4:4:4 (Máxima)": self.tr("4:4:4 (Máxima)"),
            "Ninguna": self.tr("Ninguna"),
            "LZW (Recomendada)": self.tr("LZW (Recomendada)"),
            "Deflate (ZIP)": self.tr("Deflate (ZIP)"),
        }
        return table.get(value, value)  # "PackBits" no tiene palabras en español, queda igual

    def _setup_fixed_combo(self, combo: QComboBox):
        combo.setMaxVisibleItems(_MAX_VISIBLE_COMBO_ITEMS)
        combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(1)
        combo.setItemDelegate(CheckmarkComboDelegate(combo))
        combo.setCursor(Qt.PointingHandCursor)

    # ─── Páginas de opciones por formato ────────────────────────

    def _build_format_pages(self, parent):
        pages = {
            self.tr("No Convertir"): self._build_passthrough_page(parent),
            "PNG": self._build_png_page(parent),
            "JPG": self._build_jpg_page(parent),
            "WEBP": self._build_webp_page(parent),
            "AVIF": self._build_avif_page(parent),
            "PDF": QWidget(parent),  # sin opciones propias
            "TIFF": self._build_tiff_page(parent),
            "ICO": self._build_ico_page(parent),
            "ICNS": self._build_icns_page(parent),
            "BMP": self._build_bmp_page(parent),
        }
        self._format_page_index = {}
        for fmt in OUTPUT_FORMATS:
            self._format_page_index[fmt] = self.format_stack.count()
            self.format_stack.addWidget(pages[fmt])

    def _build_passthrough_page(self, parent) -> QWidget:
        page = QWidget(parent)
        v = QVBoxLayout(page)
        lbl = QLabel(
            self.tr("Mantiene el formato original de cada archivo -- útil si solo "
                     "quieres aplicar Redimensionar (franja superior) sin cambiar de formato."),
            page,
        )
        lbl.setWordWrap(True)
        lbl.setObjectName("mutedLabel")
        v.addWidget(lbl)
        v.addStretch()
        return page

    def _build_png_page(self, parent) -> QWidget:
        page = QWidget(parent)
        v = QVBoxLayout(page)
        self.chk_png_transparency = QCheckBox(self.tr("Mantener transparencia"), page)
        self.chk_png_transparency.setChecked(True)
        v.addWidget(self.chk_png_transparency)
        v.addWidget(QLabel(self.tr("Compresión:"), page))
        self.slider_png_compression = QSlider(Qt.Horizontal, page)
        self.slider_png_compression.setRange(0, 9)
        self.slider_png_compression.setValue(6)
        v.addWidget(self.slider_png_compression)
        v.addStretch()
        return page

    def _build_jpg_page(self, parent) -> QWidget:
        page = QWidget(parent)
        v = QVBoxLayout(page)
        v.addWidget(QLabel(self.tr("Calidad:"), page))
        self.slider_jpg_quality = QSlider(Qt.Horizontal, page)
        self.slider_jpg_quality.setRange(1, 100)
        self.slider_jpg_quality.setValue(90)
        v.addWidget(self.slider_jpg_quality)
        v.addWidget(QLabel(self.tr("Submuestreo de color:"), page))
        self.combo_jpg_subsampling = AutoPopupComboBox(page)
        self._setup_fixed_combo(self.combo_jpg_subsampling)
        for opt in JPG_SUBSAMPLING_OPTIONS:
            self.combo_jpg_subsampling.addItem(self._translated_fixed_option(opt), opt)
        v.addWidget(self.combo_jpg_subsampling)
        self.chk_jpg_progressive = QCheckBox(self.tr("Escaneo progresivo (web)"), page)
        v.addWidget(self.chk_jpg_progressive)
        v.addStretch()
        return page

    def _build_webp_page(self, parent) -> QWidget:
        page = QWidget(parent)
        v = QVBoxLayout(page)
        self.chk_webp_lossless = QCheckBox(self.tr("Sin pérdida"), page)
        self.chk_webp_lossless.toggled.connect(self._on_webp_lossless_toggled)
        v.addWidget(self.chk_webp_lossless)
        self.lbl_webp_quality = QLabel(self.tr("Calidad:"), page)
        v.addWidget(self.lbl_webp_quality)
        self.slider_webp_quality = QSlider(Qt.Horizontal, page)
        self.slider_webp_quality.setRange(1, 100)
        self.slider_webp_quality.setValue(90)
        v.addWidget(self.slider_webp_quality)
        self.chk_webp_transparency = QCheckBox(self.tr("Mantener transparencia"), page)
        self.chk_webp_transparency.setChecked(True)
        v.addWidget(self.chk_webp_transparency)
        self.chk_webp_metadata = QCheckBox(self.tr("Guardar metadatos EXIF"), page)
        v.addWidget(self.chk_webp_metadata)
        v.addStretch()
        return page

    def _on_webp_lossless_toggled(self, checked: bool):
        self.lbl_webp_quality.setVisible(not checked)
        self.slider_webp_quality.setVisible(not checked)

    def _build_avif_page(self, parent) -> QWidget:
        page = QWidget(parent)
        v = QVBoxLayout(page)
        v.addWidget(QLabel(self.tr("Calidad:"), page))
        self.slider_avif_quality = QSlider(Qt.Horizontal, page)
        self.slider_avif_quality.setRange(1, 100)
        self.slider_avif_quality.setValue(80)
        v.addWidget(self.slider_avif_quality)
        v.addStretch()
        return page

    def _build_tiff_page(self, parent) -> QWidget:
        page = QWidget(parent)
        v = QVBoxLayout(page)
        v.addWidget(QLabel(self.tr("Compresión:"), page))
        self.combo_tiff_compression = AutoPopupComboBox(page)
        self._setup_fixed_combo(self.combo_tiff_compression)
        for opt in TIFF_COMPRESSION_OPTIONS:
            self.combo_tiff_compression.addItem(self._translated_fixed_option(opt), opt)
        self.combo_tiff_compression.setCurrentIndex(1)  # LZW (Recomendada)
        v.addWidget(self.combo_tiff_compression)
        self.chk_tiff_transparency = QCheckBox(self.tr("Mantener transparencia"), page)
        self.chk_tiff_transparency.setChecked(True)
        v.addWidget(self.chk_tiff_transparency)
        v.addStretch()
        return page

    def _build_ico_page(self, parent) -> QWidget:
        page = QWidget(parent)
        v = QVBoxLayout(page)
        v.addWidget(QLabel(self.tr("Tamaños a incluir:"), page))
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        for i, size in enumerate(ICO_SIZES):
            chk = QCheckBox(f"{size}×{size}", page)
            chk.setChecked(size in ICO_DEFAULT_SIZES)
            chk.toggled.connect(self._emit_validity)
            grid.addWidget(chk, i // 3, i % 3)
            self._ico_checkboxes[size] = chk
        v.addLayout(grid)
        v.addStretch()
        return page

    def _build_icns_page(self, parent) -> QWidget:
        page = QWidget(parent)
        v = QVBoxLayout(page)
        v.addWidget(QLabel(self.tr("Tamaños a incluir:"), page))
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        for i, size in enumerate(ICNS_SIZES):
            chk = QCheckBox(f"{size}×{size}", page)
            chk.setChecked(size in ICNS_DEFAULT_SIZES)
            chk.toggled.connect(self._emit_validity)
            grid.addWidget(chk, i // 3, i % 3)
            self._icns_checkboxes[size] = chk
        v.addLayout(grid)
        v.addStretch()
        return page

    def _build_bmp_page(self, parent) -> QWidget:
        page = QWidget(parent)
        v = QVBoxLayout(page)
        self.chk_bmp_rle = QCheckBox(self.tr("Comprimir (RLE)"), page)
        v.addWidget(self.chk_bmp_rle)
        v.addStretch()
        return page

    def _on_format_changed(self, *_args):
        fmt = self.combo_format.currentData() or self.tr("No Convertir")
        self.format_stack.setCurrentIndex(self._format_page_index.get(fmt, 0))
        self._emit_validity()

    def _emit_validity(self, *_args):
        self.validity_changed.emit(self.is_valid())

    # ─── API pública ─────────────────────────────────────────────

    def is_valid(self) -> bool:
        fmt = self.combo_format.currentData()
        if fmt == "ICO":
            return any(chk.isChecked() for chk in self._ico_checkboxes.values())
        if fmt == "ICNS":
            return any(chk.isChecked() for chk in self._icns_checkboxes.values())
        return True

    def get_status(self) -> tuple[bool, str]:
        if self.is_valid():
            return True, self.tr("Convertir")
        return False, self.tr("Elige al menos un tamaño de ícono.")

    def get_settings(self) -> dict:
        """No incluye resize_*/interpolation_method (eso lo aporta
        ResizePopoverContent) ni destino/conflicto (eso lo aporta el panel
        inferior de salida)."""
        fmt = self.combo_format.currentData() or self.tr("No Convertir")
        settings = {"format": fmt}
        settings.update(default_options_for_format(fmt))

        if fmt == "PNG":
            settings["png_transparency"] = self.chk_png_transparency.isChecked()
            settings["png_compression"] = self.slider_png_compression.value()
        elif fmt == "JPG":
            settings["jpg_quality"] = self.slider_jpg_quality.value()
            settings["jpg_subsampling"] = self.combo_jpg_subsampling.currentData()
            settings["jpg_progressive"] = self.chk_jpg_progressive.isChecked()
        elif fmt == "WEBP":
            settings["webp_lossless"] = self.chk_webp_lossless.isChecked()
            settings["webp_quality"] = self.slider_webp_quality.value()
            settings["webp_transparency"] = self.chk_webp_transparency.isChecked()
            settings["webp_metadata"] = self.chk_webp_metadata.isChecked()
        elif fmt == "AVIF":
            settings["avif_quality"] = self.slider_avif_quality.value()
        elif fmt == "TIFF":
            settings["tiff_compression"] = self.combo_tiff_compression.currentData()
            settings["tiff_transparency"] = self.chk_tiff_transparency.isChecked()
        elif fmt == "ICO":
            settings["ico_sizes"] = {size: chk.isChecked() for size, chk in self._ico_checkboxes.items()}
        elif fmt == "ICNS":
            settings["icns_sizes"] = {size: chk.isChecked() for size, chk in self._icns_checkboxes.items()}
        elif fmt == "BMP":
            settings["bmp_rle"] = self.chk_bmp_rle.isChecked()

        return settings
