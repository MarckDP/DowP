"""Ajustes > Apariencia: tema, modo, letra, redondez e imagen de fondo.

Lo que recarga toda la app (tema, modo, letra, redondez, opacidad de paneles...) no se aplica
al tocarlo: queda en self._pending, con la vista previa al día, hasta pulsar Aplicar. Así varios
cambios cuestan una sola recarga. Los ajustes de la imagen no recargan nada y siguen en vivo.
"""
import os

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea, QVBoxLayout,
                               QWidget)

from core.logger.logger_manager import logger
from core.utils.config_manager import get_config, save_config
from core.utils.font_manager import get_available_fonts, init_fonts
from core.utils.paths import get_user_fonts_dir, get_user_themes_dir
from core.utils import appearance_store, theme_io, theme_loader as TL
from core.utils.theme_loader import sync_legacy_theme_key
from gui.styles import (apply_folder_open_button_style, get_available_themes, get_theme_token, set_button_variant,
                        set_themed_style)
from gui.widgets.color_editor import ColorEditor
from gui.widgets.combo_box import AutoPopupComboBox
from gui.widgets.theme_gallery import ThemeGallery
from gui.widgets.theme_preview import ThemePreview
from gui.widgets.toggle_switch import ToggleSwitch
from gui.widgets.top_aligned_layout import TopAlignedVBoxLayout


class AppearancePage(QWidget):
    theme_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self._is_loading = True
        self._pending = {}  # clave de config -> valor elegido y aún sin aplicar
        self.init_ui()
        self.load_current_settings()
        self._is_loading = False
        self._refresh_pending()

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(12)

        self.title_label = QLabel(self.tr("Apariencia"))
        self.title_label.setObjectName("settingsTitle")
        self.main_layout.addWidget(self.title_label)

        line = QFrame()
        line.setObjectName("settingsDivider")
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        self.main_layout.addWidget(line)

        # Arriba, en dos mitades: cómo queda y qué temas hay.
        self.top_area = QHBoxLayout()
        self.top_area.setSpacing(12)
        self.preview = ThemePreview()
        self.top_area.addWidget(self.preview, 1)
        themes_column = QVBoxLayout()
        themes_column.setSpacing(6)
        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.btn_create_from_image = QPushButton(self.tr("Crear desde imagen"))
        self.btn_create_from_image.setCursor(Qt.PointingHandCursor)
        set_button_variant(self.btn_create_from_image, "accent-solid")
        self.btn_create_from_image.clicked.connect(self._create_theme_from_image)
        actions.addWidget(self.btn_create_from_image)
        self.btn_import = QPushButton(self.tr("Importar"))
        self.btn_import.setCursor(Qt.PointingHandCursor)
        set_button_variant(self.btn_import, "secondary")
        self.btn_import.clicked.connect(self._import_theme)
        actions.addWidget(self.btn_import)
        self.btn_pick = QPushButton(self.tr("Seleccionar"))
        self.btn_pick.setCheckable(True)
        self.btn_pick.setCursor(Qt.PointingHandCursor)
        self.btn_pick.setToolTip(self.tr("Marcar varios temas para eliminarlos juntos"))
        set_button_variant(self.btn_pick, "secondary")
        self.btn_pick.toggled.connect(self._on_pick_toggled)
        actions.addWidget(self.btn_pick)
        self.btn_delete_picked = QPushButton()
        self.btn_delete_picked.setCursor(Qt.PointingHandCursor)
        set_button_variant(self.btn_delete_picked, "danger")
        self.btn_delete_picked.clicked.connect(lambda: self._delete_themes(self.gallery.picked()))
        self.btn_delete_picked.hide()
        actions.addWidget(self.btn_delete_picked)
        actions.addStretch()
        self.btn_open_themes = QPushButton()
        self.btn_open_themes.setFixedSize(30, 30)
        apply_folder_open_button_style(self.btn_open_themes, tooltip=self.tr("Abrir carpeta de temas"))
        self.btn_open_themes.clicked.connect(self._open_user_themes_dir)
        actions.addWidget(self.btn_open_themes)
        themes_column.addLayout(actions)
        self.gallery = ThemeGallery()
        self.gallery.selected.connect(self._on_gallery_selected)
        self.gallery.delete_requested.connect(self._delete_themes)
        self.gallery.action_requested.connect(self._on_gallery_action)
        self.gallery.picking_changed.connect(self._on_picked_changed)
        themes_column.addWidget(self.gallery, 1)
        self.top_area.addLayout(themes_column, 1)
        self.top_widget = QWidget()
        self.top_widget.setLayout(self.top_area)
        self.top_area.setContentsMargins(0, 0, 0, 0)
        self.top_widget.setFixedHeight(224)
        self.main_layout.addWidget(self.top_widget)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")

        self.scroll_content = QWidget()
        self.scroll_content.setObjectName("settingsScrollContent")
        self.scroll_content.setStyleSheet("QWidget#settingsScrollContent { background-color: transparent; }")

        self.content_layout = TopAlignedVBoxLayout(self.scroll_content)
        self.content_layout.setContentsMargins(0, 10, 10, 0)
        self.content_layout.setSpacing(12)

        # 2. Tema
        # La galería es lo que se ve; este selector oculto sigue guardando la lista y la elección.
        
        self.theme_combo = AutoPopupComboBox(self)
        self.theme_combo.hide()
        

        self._add_section(self.tr("Colores"))

        # 2b. Modo (claro / oscuro / según el sistema) del tema elegido
        self.mode_row = QHBoxLayout()
        self.mode_label = QLabel(self.tr("Modo"))
        self.mode_label.setObjectName("settingsLabel")

        self.mode_combo = AutoPopupComboBox()
        self.mode_combo.setFixedWidth(180)
        self.mode_combo.addItem(self.tr("Oscuro"), "dark")
        self.mode_combo.addItem(self.tr("Claro"), "light")
        self.mode_combo.addItem(self.tr("Según el sistema"), "system")

        self.mode_row.addWidget(self.mode_label)
        self.mode_row.addStretch()
        self.mode_row.addWidget(self.mode_combo)
        # Mismo ancho que el botón de carpeta de la fila de Tema, para alinear los combos.
        self.mode_row.addSpacing(30 + 6)
        self.content_layout.addLayout(self.mode_row)


        # 2c. Colores
        self.color_editor = ColorEditor()
        self.color_editor.edited.connect(self._on_colors_edited)
        self.color_editor.reverted.connect(self._on_colors_reverted)
        self.content_layout.addWidget(self.color_editor)

        self._add_section(self.tr("Texto"))

        # 3. Tipografía / Fuente
        self.font_row = QHBoxLayout()
        self.font_label = QLabel(self.tr("Tipografía / Fuente"))
        self.font_label.setObjectName("settingsLabel")
        
        self.font_combo = AutoPopupComboBox()
        self.font_combo.setFixedWidth(180)

        self.btn_open_fonts = QPushButton()
        self.btn_open_fonts.setFixedSize(30, 30)
        apply_folder_open_button_style(self.btn_open_fonts, tooltip=self.tr("Abrir carpeta de fuentes personalizadas (%APPDATA%/DowP2/fonts)"), icon_size=15)
        self.btn_open_fonts.clicked.connect(self._open_user_fonts_dir)

        self.font_row.addWidget(self.font_label)
        self.font_row.addStretch()
        self.font_row.addWidget(self.font_combo)
        self.font_row.addWidget(self.btn_open_fonts)
        self.content_layout.addLayout(self.font_row)

        # 3b. Tamaño de texto
        self.font_size_row = QHBoxLayout()
        self.font_size_label = QLabel(self.tr("Tamaño de texto (requiere reinicio para ver todo)"))
        self.font_size_label.setObjectName("settingsLabel")
        
        from PySide6.QtWidgets import QSpinBox
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setFixedWidth(80)
        self.font_size_spin.setRange(8, 22)
        self.font_size_spin.setSuffix(" px")
        
        
        self.font_size_row.addWidget(self.font_size_label)
        self.font_size_row.addStretch()
        self.font_size_row.addWidget(self.font_size_spin)
        # Mismo ancho que el botón de carpeta de la fila de Fuente, para alinear los controles.
        self.font_size_row.addSpacing(30 + self.font_row.spacing())
        self.content_layout.addLayout(self.font_size_row)

        self.font_size_warning = QLabel(self.tr("⚠️ Tamaños mayores a 18px pueden causar que algunos textos y botones se vean cortados."))
        set_themed_style(self.font_size_warning, lambda: f"color: {get_theme_token('estado_aviso', '#d8c94a')}; font-size: 11px;")
        self.font_size_warning.setWordWrap(True)
        self.font_size_warning.hide()
        self.content_layout.addWidget(self.font_size_warning)
        
        self.font_size_spin.valueChanged.connect(lambda v: self.font_size_warning.setVisible(v > 18))
        self.font_size_spin.valueChanged.connect(self.on_font_size_selection)

        self._add_section(self.tr("Interfaz"))

        # 3c. Redondez: encima del tema, sin modificar su archivo.
        from PySide6.QtWidgets import QSlider
        self.radius_row = QHBoxLayout()
        self.radius_label = QLabel(self.tr("Redondez"))
        self.radius_label.setObjectName("settingsLabel")
        self.radius_slider = QSlider(Qt.Horizontal)
        self.radius_slider.setRange(0, 14)
        self.radius_slider.setFixedWidth(150)
        self.radius_slider.setToolTip(self.tr("Qué tan redondeadas son las esquinas de botones, campos, "
                                              "menús y paneles."))
        self.radius_value = QLabel()
        self.radius_value.setFixedWidth(40)
        self.btn_radius_reset = QPushButton(self.tr("Según el tema"))
        self.btn_radius_reset.setCursor(Qt.PointingHandCursor)
        set_button_variant(self.btn_radius_reset, "secondary")
        self.btn_radius_reset.clicked.connect(lambda: self._set_radius(None))
        self.radius_slider.valueChanged.connect(self._set_radius)
        self.radius_row.addWidget(self.radius_label)
        self.radius_row.addStretch()
        self.radius_row.addWidget(self.btn_radius_reset)
        self.radius_row.addWidget(self.radius_slider)
        self.radius_row.addWidget(self.radius_value)
        self.content_layout.addLayout(self.radius_row)
        from gui.theme_manager import get_theme_manager
        get_theme_manager().theme_changed.connect(lambda _tokens: self._sync_radius_control())

        # Aviso tras cambiar tema o modo: la mayor parte se actualiza en vivo, pero algunos
        # estilos se calculan al crear cada widget y solo cambian del todo al reiniciar.
        # Sin diálogo (a diferencia del idioma) para no interrumpir mientras se prueban modos.
        self.theme_restart_hint = QWidget()
        hint_row = QHBoxLayout(self.theme_restart_hint)
        hint_row.setContentsMargins(0, 0, 10, 0)
        self.theme_restart_label = QLabel(self.tr("Si alguna parte no cambió de aspecto, reiniciar DowP la actualiza."))
        self.theme_restart_label.setWordWrap(True)
        set_themed_style(self.theme_restart_label, lambda: f"color: {get_theme_token('texto_secundario', '#666666')}; font-size: 11px;")
        self.btn_theme_restart = QPushButton(self.tr("Reiniciar ahora"))
        set_button_variant(self.btn_theme_restart, "accent-solid")
        self.btn_theme_restart.clicked.connect(self._restart_for_theme)
        hint_row.addWidget(self.theme_restart_label, 1)
        hint_row.addWidget(self.btn_theme_restart)
        self.theme_restart_hint.hide()

        self._build_transparency_rows()
        self._build_background_section()

        self.scroll_area.setWidget(self.scroll_content)
        self.main_layout.addWidget(self.scroll_area)

        self.pending_bar = QWidget()
        bar = QHBoxLayout(self.pending_bar)
        bar.setContentsMargins(0, 0, 10, 0)
        self.btn_save = QPushButton(self.tr("Guardar"))
        self.btn_save.setCursor(Qt.PointingHandCursor)
        set_button_variant(self.btn_save, "secondary")
        self.btn_save.clicked.connect(self._save_appearance)
        bar.addWidget(self.btn_save)
        self.btn_export = QPushButton(self.tr("Exportar"))
        self.btn_export.setCursor(Qt.PointingHandCursor)
        set_button_variant(self.btn_export, "secondary")
        self.btn_export.clicked.connect(self._export_theme)
        bar.addWidget(self.btn_export)
        self.pending_label = QLabel()
        self.pending_label.setObjectName("settingsLabel")
        bar.addWidget(self.pending_label)
        bar.addStretch()
        self.btn_discard = QPushButton(self.tr("Descartar"))
        self.btn_discard.setCursor(Qt.PointingHandCursor)
        set_button_variant(self.btn_discard, "secondary")
        self.btn_discard.clicked.connect(self._discard_pending)
        bar.addWidget(self.btn_discard)
        self.btn_apply = QPushButton(self.tr("Aplicar"))
        self.btn_apply.setCursor(Qt.PointingHandCursor)
        set_button_variant(self.btn_apply, "accent-solid")
        self.btn_apply.clicked.connect(self._apply_pending)
        bar.addWidget(self.btn_apply)
        # Justo después de Aplicar: al final de la lista con scroll podría no verse.
        self.main_layout.addWidget(self.theme_restart_hint)
        self.main_layout.addWidget(self.pending_bar)

        self.theme_combo.currentIndexChanged.connect(self.on_theme_selection)
        self.mode_combo.currentIndexChanged.connect(self.on_mode_selection)
        self.font_combo.currentIndexChanged.connect(self.on_font_selection)

    def load_current_settings(self):
        config = get_config()

        # Load Themes
        self._populate_themes()
        theme = config.get("theme_id", "dowp")
        index = self.theme_combo.findData(theme)
        if index >= 0:
            self.theme_combo.setCurrentIndex(index)
        mode_index = self.mode_combo.findData(config.get("theme_mode", "dark"))
        if mode_index >= 0:
            self.mode_combo.setCurrentIndex(mode_index)
        self._update_mode_combo_state(theme)
            
        # Load Fonts
        self._populate_fonts()
        font_family = config.get("font_family", "theme_default")
        index = self.font_combo.findData(font_family)
        if index >= 0:
            self.font_combo.setCurrentIndex(index)
        else:
            self.font_combo.setCurrentIndex(0) # fallback a por defecto
            
        # Load Font Size
        font_size_override = config.get("font_size_override", "default")
        if font_size_override == "default":
            self.font_size_spin.setValue(13)
        elif isinstance(font_size_override, int):
            self.font_size_spin.setValue(font_size_override)
        else:
            self.font_size_spin.setValue(13)

        self._load_background_settings()
        self._sync_radius_control()

    # ── IMAGEN DE FONDO (ver core/utils/background_images.py) ─────────────────
    def _add_section(self, text):
        label = QLabel(text)
        label.setObjectName("settingsSectionTitle")
        self.content_layout.addWidget(label)

    def _add_row(self, label_text, *widgets, align_with_folder=False):
        layout = QHBoxLayout()
        label = QLabel(label_text)
        label.setObjectName("settingsLabel")
        layout.addWidget(label)
        layout.addStretch()
        for w in widgets:
            layout.addWidget(w)
        if align_with_folder:  # como la fila de Modo: alineado con los combos de arriba
            layout.addSpacing(30 + 6)
        self.content_layout.addLayout(layout)
        return label

    def _build_transparency_rows(self):
        """Opacidad de los paneles y Transparentar vistas previas: dependen del fondo general."""
        from PySide6.QtWidgets import QSlider
        from core.utils import background_images as bg
        row = self._add_row
        self.bg_panel_slider = QSlider(Qt.Horizontal)
        self.bg_panel_slider.setRange(bg.MIN_PANEL_OPACITY, 100)
        self.bg_panel_slider.setFixedWidth(150)
        self.bg_panel_value = QLabel()
        self.bg_panel_value.setFixedWidth(40)
        self.bg_panel_slider.setToolTip(self.tr(
            "Cuánto tapan los paneles a la imagen. El texto, los botones y los campos siguen sólidos."))
        self.bg_panel_slider.valueChanged.connect(self._on_bg_panel_value_changed)
        self.bg_panel_label = row(self.tr("Opacidad de los paneles"), self.bg_panel_slider, self.bg_panel_value)

        self.bg_previews_switch = ToggleSwitch()
        self.bg_previews_switch.setToolTip(self.tr(
            "Sin relleno ni cuadrícula: lo único sólido es la imagen o el video.\n"
            "Las zonas transparentes de una imagen se mezclan con el fondo y ya no se distinguen."))
        self.bg_previews_switch.toggled.connect(self._on_bg_previews_toggled)
        row(self.tr("Transparentar vistas previas"), self.bg_previews_switch)

    def _build_background_section(self):
        from PySide6.QtWidgets import QSlider
        from core.utils import background_images as bg

        self._add_section(self.tr("Imágenes"))
        row = self._add_row


        # Lugar: el fondo general y las vistas previas vacías (las listas vienen después).
        self.bg_place_combo = AutoPopupComboBox()
        self.bg_place_combo.setFixedWidth(180)
        self.bg_place_combo.addItem(self.tr("Fondo general"), bg.PLACE_GENERAL)
        self.bg_place_combo.addItem(self.tr("Vistas previas vacías"), bg.PLACE_PREVIEWS)
        self.bg_place_combo.currentIndexChanged.connect(lambda _i: self._load_background_settings())
        row(self.tr("Lugar"), self.bg_place_combo, align_with_folder=True)

        self.bg_file_label = QLabel()
        set_themed_style(self.bg_file_label, lambda: f"color: {get_theme_token('texto_tenue', '#888888')}; font-size: 11px;")
        self.btn_bg_choose = QPushButton(self.tr("Elegir…"))
        self.btn_bg_choose.setCursor(Qt.PointingHandCursor)
        set_button_variant(self.btn_bg_choose, "secondary")
        self.btn_bg_choose.clicked.connect(self._on_bg_choose)
        self.btn_bg_remove = QPushButton(self.tr("Quitar"))
        self.btn_bg_remove.setCursor(Qt.PointingHandCursor)
        set_button_variant(self.btn_bg_remove, "secondary")
        self.btn_bg_remove.clicked.connect(self._on_bg_remove)
        row(self.tr("Imagen"), self.bg_file_label, self.btn_bg_choose, self.btn_bg_remove)

        self.bg_opacity_slider = QSlider(Qt.Horizontal)
        self.bg_opacity_slider.setRange(0, 100)
        self.bg_opacity_slider.setFixedWidth(150)
        self.bg_opacity_value = QLabel()
        self.bg_opacity_value.setFixedWidth(40)
        self.bg_opacity_slider.valueChanged.connect(self._on_bg_opacity_changed)
        self.bg_opacity_slider.sliderReleased.connect(lambda: save_config(get_config()))
        row(self.tr("Opacidad de la imagen"), self.bg_opacity_slider, self.bg_opacity_value)

        self.bg_fit_combo = AutoPopupComboBox()
        self.bg_fit_combo.setFixedWidth(180)
        for label, key in ((self.tr("Rellenar"), bg.FIT_FILL), (self.tr("Ajustar"), bg.FIT_FIT),
                           (self.tr("Estirar"), bg.FIT_STRETCH), (self.tr("Tamaño original"), bg.FIT_ORIGINAL),
                           (self.tr("Mosaico"), bg.FIT_TILE)):
            self.bg_fit_combo.addItem(label, key)
        self.bg_fit_combo.setToolTip(self.tr(
            "Rellenar: cubre todo sin deformar; recorta lo que sobra.\n"
            "Ajustar: la imagen entera siempre visible.\n"
            "Estirar: cubre todo deformando la imagen.\n"
            "Tamaño original: sin escalar; ideal para un personaje o un logo.\n"
            "Mosaico: repite la imagen."))
        self.bg_fit_combo.currentIndexChanged.connect(self._on_bg_fit_changed)
        row(self.tr("Ajuste"), self.bg_fit_combo, align_with_folder=True)

        self.bg_align_combo = AutoPopupComboBox()
        self.bg_align_combo.setFixedWidth(180)
        vertical = {"top": self.tr("Arriba"), "center": self.tr("Centro"), "bottom": self.tr("Abajo")}
        horizontal = {"left": self.tr("izquierda"), "center": self.tr("centro"), "right": self.tr("derecha")}
        for key in bg.ALIGNS:
            v, h = key.split("-")
            label = self.tr("Centro") if key == "center-center" else f"{vertical[v]} {horizontal[h]}"
            self.bg_align_combo.addItem(label, key)
        self.bg_align_combo.setToolTip(self.tr("Qué parte queda a la vista al recortar, o dónde se ubica la imagen."))
        self.bg_align_combo.currentIndexChanged.connect(self._on_bg_align_changed)
        row(self.tr("Posición"), self.bg_align_combo, align_with_folder=True)

        self.bg_blur_switch = ToggleSwitch()
        self.bg_blur_switch.toggled.connect(self._on_bg_blur_toggled)
        row(self.tr("Desenfocar la imagen"), self.bg_blur_switch)

    def _bg_place(self) -> str:
        return self.bg_place_combo.currentData()

    def _load_background_settings(self):
        from core.utils import background_images as bg
        s = bg.get_place(self._bg_place())
        path = bg.image_path(self._bg_place())
        name = s["name"] or (os.path.basename(path) if path else "")
        self.bg_file_label.setText(self.bg_file_label.fontMetrics().elidedText(name, Qt.ElideMiddle, 220)
                                   if path else self.tr("Ninguna"))
        self.bg_file_label.setToolTip(name if path else "")
        for w in (self.bg_opacity_slider, self.bg_fit_combo, self.bg_align_combo, self.bg_blur_switch,
                  self.bg_panel_slider, self.bg_previews_switch):
            w.blockSignals(True)
        self.bg_previews_switch.setChecked(self._pending.get("previews", bg.get_previews_transparent()))
        self.bg_opacity_slider.setValue(s["opacity"])
        self.bg_opacity_value.setText(f"{s['opacity']} %")
        self.bg_fit_combo.setCurrentIndex(max(0, self.bg_fit_combo.findData(s["fit"])))
        self.bg_align_combo.setCurrentIndex(max(0, self.bg_align_combo.findData(s["align"])))
        self.bg_blur_switch.setChecked(s["blur"])
        panel = self._pending.get("panel", bg.get_panel_opacity())
        self.bg_panel_slider.setValue(panel)
        self.bg_panel_value.setText(f"{panel} %")
        for w in (self.bg_opacity_slider, self.bg_fit_combo, self.bg_align_combo, self.bg_blur_switch,
                  self.bg_panel_slider, self.bg_previews_switch):
            w.blockSignals(False)
        self._update_bg_controls_enabled()

    def _update_bg_controls_enabled(self):
        from core.utils import background_images as bg
        has = bg.image_path(self._bg_place()) is not None
        for w in (self.btn_bg_remove, self.bg_opacity_slider, self.bg_fit_combo, self.bg_blur_switch):
            w.setEnabled(has)
        # Estos dos dependen siempre del fondo general, sea cual sea el lugar elegido.
        has_general = bg.image_path(bg.PLACE_GENERAL) is not None
        for w, tip in ((self.bg_panel_slider, self.tr("Cuánto tapan los paneles a la imagen. El texto, los botones y los campos siguen sólidos.")),
                       (self.bg_previews_switch, self.tr("Sin relleno ni cuadrícula: lo único sólido es la imagen o el video.\n"
                                                         "Las zonas transparentes de una imagen se mezclan con el fondo y ya no se distinguen."))):
            w.setEnabled(has_general)
            w.setToolTip(tip if has_general else self.tr("Necesita una imagen de fondo general"))
        # La posición no cambia nada al estirar ni en mosaico.
        self.bg_align_combo.setEnabled(has and self.bg_fit_combo.currentData() not in (bg.FIT_STRETCH, bg.FIT_TILE))

    def _notify_background(self):
        from gui.widgets.background_canvas import background_notifier
        background_notifier().changed.emit(self._bg_place())

    def _apply_glass_if_changed(self, before):
        """La transparencia de los paneles cambia la hoja de estilos: eso pasa por el
        tema (con su aviso de unos segundos), y solo si de verdad cambió algo."""
        from core.utils.background_images import glass_alpha
        if glass_alpha() != before:
            from gui.theme_manager import get_theme_manager
            get_theme_manager().apply()

    def _on_bg_choose(self):
        from PySide6.QtWidgets import QFileDialog
        from core.utils import background_images as bg
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Elegir imagen de fondo"), os.path.expanduser("~"),
            self.tr("Imágenes") + " (*.png *.jpg *.jpeg *.webp *.bmp *.gif)")
        if not path:
            return
        before = bg.glass_alpha()
        try:
            _name, animated = bg.import_image(self._bg_place(), path)
        except Exception as e:
            logger.error(f"Fondo: no se pudo usar {path}: {e}")
            QMessageBox.warning(self, self.tr("Imagen de fondo"),
                                self.tr("No se pudo abrir la imagen: {0}").format(e))
            return
        if animated:
            QMessageBox.information(self, self.tr("Imagen de fondo"), self.tr(
                "Las imágenes animadas todavía no se admiten como fondo: se usa su primer fotograma."))
        self._load_background_settings()
        self._notify_background()
        self._apply_glass_if_changed(before)

    def _on_bg_remove(self):
        from core.utils import background_images as bg
        before = bg.glass_alpha()
        bg.remove_image(self._bg_place())
        self._load_background_settings()
        self._notify_background()
        self._apply_glass_if_changed(before)

    def _on_bg_opacity_changed(self, value):
        from core.utils import background_images as bg
        self.bg_opacity_value.setText(f"{value} %")
        # En vivo mientras se arrastra; se guarda en disco al soltar.
        bg.set_place(self._bg_place(), save=not self.bg_opacity_slider.isSliderDown(), opacity=value)
        self._notify_background()

    def _on_bg_fit_changed(self, _index):
        from core.utils import background_images as bg
        bg.set_place(self._bg_place(), fit=self.bg_fit_combo.currentData())
        self._update_bg_controls_enabled()
        self._notify_background()

    def _on_bg_align_changed(self, _index):
        from core.utils import background_images as bg
        bg.set_place(self._bg_place(), align=self.bg_align_combo.currentData())
        self._notify_background()

    def _on_bg_blur_toggled(self, checked):
        from core.utils import background_images as bg
        bg.set_place(self._bg_place(), blur=bool(checked))
        self._notify_background()

    def _on_bg_previews_toggled(self, checked):
        from core.utils import background_images as bg
        self._set_pending("previews", bool(checked), bg.get_previews_transparent())

    def _on_bg_panel_value_changed(self, value):
        from core.utils import background_images as bg
        self.bg_panel_value.setText(f"{value} %")
        self._set_pending("panel", value, bg.get_panel_opacity())


    # ── Gestión de temas (importar / exportar / eliminar) ─────────────────────

    def _create_theme_from_image(self):
        from gui.dialogs.theme_from_image_dialog import ThemeFromImageDialog
        dialog = ThemeFromImageDialog(self.window())
        if dialog.exec() and dialog.result_theme:
            self._stage_image_theme(*dialog.result_theme)

    def _stage_image_theme(self, theme_id, data, background):
        """Queda como cambio pendiente, sin escribir nada: se revisa con la vista previa y el
        editor de colores. Solo Aplicar crea el archivo."""
        self._pending.pop("colors", None)
        self._pending["image_theme"] = {"id": theme_id, "data": data, "background": background}
        self._pending["theme_id"] = theme_id
        self._populate_themes()
        self.theme_combo.blockSignals(True)
        index = self.theme_combo.findData(theme_id)
        if index < 0:
            self.theme_combo.addItem(self.tr("{0} (sin aplicar)").format(data["meta"]["nombre"]), theme_id)
            index = self.theme_combo.count() - 1
        self.theme_combo.setCurrentIndex(index)
        self.theme_combo.blockSignals(False)
        self._update_mode_combo_state(theme_id)
        self._refresh_pending()
        self._sync_radius_control()

    def _select_theme(self, theme_id):
        """Recarga la lista y elige el tema. Es el resultado de una acción (crear, importar,
        eliminar), no una prueba: se aplica enseguida."""
        self._populate_themes()
        index = self.theme_combo.findData(theme_id)
        if index < 0:
            index = self.theme_combo.findData("dowp")
        if self.theme_combo.currentIndex() == index:
            self.on_theme_selection(index)
        else:
            self.theme_combo.setCurrentIndex(index)
        self._apply_pending(force=True)

    def _import_theme(self):
        from PySide6.QtWidgets import QFileDialog
        from core.utils import theme_io
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Importar tema"), os.path.expanduser("~"), self.tr("Temas de DowP (*.json *.dthmp)"))
        if not path:
            return
        if path.lower().endswith(".dthmp"):
            self._import_package(path)
            return
        try:
            theme_id, data, report = theme_io.read_theme_file(path)
        except theme_io.ThemeImportError as e:
            QMessageBox.warning(self, self.tr("No se pudo importar el tema"), str(e))
            return
        if theme_io.is_user_theme(theme_id):
            answer = QMessageBox.question(
                self, self.tr("Importar tema"),
                self.tr("Ya tienes un tema llamado «{0}». ¿Quieres reemplazarlo?").format(theme_id))
            if answer != QMessageBox.Yes:
                return
        try:
            theme_io.save_imported(theme_id, data)
        except OSError as e:
            QMessageBox.warning(self, self.tr("No se pudo importar el tema"), str(e))
            return

        lines = [self.tr("Se importó el tema «{0}» y ya está aplicado.").format(report["name"])]
        if report.get("converted"):
            lines.append(self.tr("Era un tema de DowP 1: se convirtió al formato nuevo. "
                                 "Lo que no tiene equivalente se toma del tema DowP."))
        if report["invalid"]:
            shown = ", ".join(report["invalid"][:5]) + ("…" if len(report["invalid"]) > 5 else "")
            lines.append(self.tr("Se ignoraron {0} colores no válidos: {1}").format(len(report["invalid"]), shown))
        self._select_theme(theme_id)
        QMessageBox.information(self, self.tr("Tema importado"), "\n\n".join(lines))

    def _import_package(self, path):
        from core.utils import theme_package
        try:
            contents = theme_package.read_package(path)
        except theme_io.ThemeImportError as e:
            QMessageBox.warning(self, self.tr("No se pudo importar el tema"), str(e))
            return
        if theme_io.is_user_theme(contents.theme_id):
            answer = QMessageBox.question(
                self, self.tr("Importar tema"),
                self.tr("Ya tienes un tema llamado «{0}». ¿Quieres reemplazarlo?").format(contents.name))
            if answer != QMessageBox.Yes:
                return
        with_assets = False
        if contents.has_appearance:
            answer = QMessageBox.question(
                self, self.tr("Importar tema"),
                self.tr("Este tema trae sus imágenes y ajustes. ¿Usarlos también?\n\n"
                        "Lo que tienes ahora se guarda como «Apariencia anterior»."))
            with_assets = answer == QMessageBox.Yes
        try:
            theme_id = theme_package.install(contents, with_assets)
        except OSError as e:
            QMessageBox.warning(self, self.tr("No se pudo importar el tema"), str(e))
            return
        self._select_or_restore(theme_id)
        QMessageBox.information(self, self.tr("Tema importado"), self.tr(
            "Se importó el tema «{0}» y ya está aplicado. Ya puedes borrar el archivo original.").format(contents.name))

    def _select_or_restore(self, theme_id):
        """Reimportar el tema activo no cambia el selector: igual hay que restaurar lo que trae."""
        same = get_config().get("theme_id") == theme_id
        if same and appearance_store.has_appearance(theme_id):
            appearance_store.backup_previous()
            appearance_store.restore(theme_id)
            from core.utils import background_images as bg
            from gui.widgets.background_canvas import background_notifier
            for place in bg.PLACES:
                background_notifier().changed.emit(place)
            self._reload_after_restore()
        self._select_theme(theme_id)

    def _export_theme(self):
        from PySide6.QtWidgets import QFileDialog
        from core.utils import theme_package
        from gui.dialogs.theme_from_image_dialog import ExportThemeDialog
        theme_id = self.theme_combo.currentData() or "dowp"
        family = theme_package.active_family(theme_id)
        dialog = ExportThemeDialog(family if theme_package.is_user_font(family) else "", self.window())
        if not dialog.exec():
            return
        kind = dialog.kind()
        extension, file_filter = ((theme_package.EXTENSION, self.tr("Paquetes de tema de DowP (*.dthmp)"))
                                  if kind == dialog.PACKAGE else (".json", self.tr("Temas de DowP (*.json)")))
        suggested = os.path.join(os.path.expanduser("~"), f"{theme_id}{extension}")
        path, _ = QFileDialog.getSaveFileName(self, self.tr("Exportar tema"), suggested, file_filter)
        if not path:
            return
        if not path.lower().endswith(extension):
            path += extension
        try:
            if kind == dialog.PACKAGE:
                theme_package.export_package(theme_id, path)
            elif kind == dialog.COLORS:
                theme_package.export_colors_only(theme_id, path)
            else:
                theme_io.export_theme(theme_id, path)
        except OSError as e:
            QMessageBox.warning(self, self.tr("No se pudo exportar el tema"), str(e))
            return
        QMessageBox.information(self, self.tr("Tema exportado"), self.tr("Se guardó en:\n{0}").format(path))

    def _open_user_themes_dir(self):
        """Abre la carpeta de temas personalizados del usuario en el explorador de archivos."""
        themes_dir = get_user_themes_dir()
        QDesktopServices.openUrl(QUrl.fromLocalFile(themes_dir))
        logger.info(f"AppearancePage: Abierta carpeta de temas: {themes_dir}")

    def _open_user_fonts_dir(self):
        """Abre la carpeta de fuentes personalizadas del usuario en el explorador de archivos."""
        fonts_dir = get_user_fonts_dir()
        QDesktopServices.openUrl(QUrl.fromLocalFile(fonts_dir))
        logger.info(f"AppearancePage: Abierta carpeta de fuentes: {fonts_dir}")

    def _populate_themes(self):
        """Carga los temas disponibles dinámicamente."""
        self.theme_combo.blockSignals(True)
        self.theme_combo.clear()
        self._theme_names = {t["id"]: t["name"] for t in TL.list_themes()}  # sin "(Usuario)"
        themes = get_available_themes()
        self._theme_has_modes = {}
        for t in themes:
            self.theme_combo.addItem(t["name"], t["id"])
            self._theme_has_modes[t["id"]] = t.get("has_modes", False)
        self.theme_combo.blockSignals(False)

    def _update_mode_combo_state(self, theme_id):
        """Un tema sin parejas [claro, oscuro] se ve igual en cualquier modo: el selector
        queda desactivado (pero conserva su valor, por si se vuelve a un tema con modos)."""
        has_modes = getattr(self, "_theme_has_modes", {}).get(theme_id, True)
        self.mode_combo.setEnabled(has_modes)
        self.mode_combo.setToolTip("" if has_modes else self.tr("Este tema tiene un solo modo"))

    def _populate_fonts(self):
        """Carga las fuentes disponibles dinámicamente."""
        self.font_combo.blockSignals(True)
        self.font_combo.clear()
        self.font_combo.addItem(self.tr("Por defecto del tema"), "theme_default")
        
        fonts = get_available_fonts()
        for f in fonts:
            self.font_combo.addItem(f, f)
        self.font_combo.blockSignals(False)

    def on_theme_selection(self, index):
        if self._is_loading: return
        theme_code = self.theme_combo.itemData(index)
        if not theme_code: return
        if self._pending.pop("image_theme", None):  # el creado sin aplicar deja de existir
            self._populate_themes()
            self.theme_combo.blockSignals(True)
            self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(theme_code)))
            self.theme_combo.blockSignals(False)
        self._update_mode_combo_state(theme_code)
        self._pending.pop("colors", None)  # eran ajustes del tema anterior
        self._set_pending("theme_id", theme_code, get_config().get("theme_id"))
        self._sync_radius_control()

    def on_mode_selection(self, index):
        if self._is_loading: return
        mode = self.mode_combo.itemData(index)
        if not mode: return
        self._set_pending("theme_mode", mode, get_config().get("theme_mode"))

    def _restart_for_theme(self):
        """Mismo reinicio que el cambio de idioma (ver _prompt_language_restart)."""
        from core.utils.app_restart import restart_app
        if restart_app():
            from PySide6.QtWidgets import QApplication
            QApplication.instance().quit()
        else:
            QMessageBox.warning(
                self,
                self.tr("No se pudo reiniciar"),
                self.tr("Cierra y vuelve a abrir DowP a mano para aplicar el tema por completo."),
            )

    def on_font_selection(self, index):
        if self._is_loading: return
        font_code = self.font_combo.itemData(index)
        if font_code is None: return
        self._set_pending("font_family", font_code, get_config().get("font_family", "theme_default"))

    def _sync_radius_control(self):
        """El control muestra lo que se verá: el valor elegido o el del tema."""
        override = self._draft("radius_override", None)
        own = self._draft_own_shapes()["radio"]
        self.radius_slider.blockSignals(True)
        self.radius_slider.setValue(override if isinstance(override, int) else round(own))
        self.radius_slider.blockSignals(False)
        self.radius_value.setText(str(self.radius_slider.value()))
        self.btn_radius_reset.setEnabled(override is not None)

    def _set_radius(self, value):
        if self._is_loading:
            return
        self._set_pending("radius_override", value, get_config().get("radius_override"))
        self._sync_radius_control()

    # ── Cambios sin aplicar ─────────────────────────────────────────────────
    def _draft(self, key, default):
        """El valor que se verá: lo pendiente o, si no hay, lo guardado."""
        return self._pending[key] if key in self._pending else get_config().get(key, default)

    def _draft_own_shapes(self) -> dict:
        """Las formas del tema elegido, sin el control de Redondez."""
        unsaved = self._pending.get("image_theme")
        shapes = TL.resolve_shapes(unsaved["data"]["basado_en"] if unsaved else self._draft("theme_id", TL.DEFAULT_THEME),
                                   use_overrides=False)
        if unsaved:
            shapes.update(unsaved["data"].get("formas", {}))
        return shapes

    def _draft_tokens(self, mode: str) -> dict:
        unsaved = self._pending.get("image_theme")
        if unsaved:  # todavía no existe el archivo: su base y encima sus colores
            tokens = dict(TL.resolve_theme(unsaved["data"]["basado_en"], mode))
            index = 1 if mode == "dark" else 0
            tokens.update({k: v[index] for k, v in unsaved["data"]["colores"].items()})
            return tokens
        return dict(TL.resolve_theme(self._draft("theme_id", TL.DEFAULT_THEME), mode))

    def _draft_mode(self) -> str:
        return TL.effective_mode(self._draft("theme_mode", "dark"))

    def _on_colors_edited(self, changes: dict):
        colors = self._pending.setdefault("colors", {})
        colors.setdefault(self._draft_mode(), {}).update(changes)
        self._refresh_pending()

    def _on_colors_reverted(self, tokens: list):
        colors = self._pending.get("colors", {})
        edits = colors.get(self._draft_mode(), {})
        for token in tokens:
            edits.pop(token, None)
        if not edits:
            colors.pop(self._draft_mode(), None)
        if not colors:
            self._pending.pop("colors", None)
        self._refresh_pending()

    def _set_pending(self, key, value, current):
        if value == current:
            self._pending.pop(key, None)
        else:
            self._pending[key] = value
        self._refresh_pending()

    def _refresh_pending(self):
        from core.utils import background_images as bg
        # Siempre visible, para que el área con scroll no cambie de alto y la página no salte.
        has_changes = bool(self._pending)
        self.btn_apply.setEnabled(has_changes)
        self.btn_discard.setEnabled(has_changes)
        self.pending_label.setText(self.tr("Tienes cambios sin aplicar") if has_changes else "")
        # Se exporta el tema guardado: con colores o un tema nuevo sin aplicar saldría otra cosa.
        self.btn_export.setEnabled(not any(k in self._pending for k in ("theme_id", "colors", "image_theme")))
        self.btn_save.setEnabled(not has_changes)
        self.btn_save.setToolTip(self.tr("Guardar colores, imágenes, opacidades, letra y redondez") if not has_changes
                                 else self.tr("Aplica o descarta los cambios para guardar"))
        self.btn_export.setToolTip(self.tr("Exportar el tema actual") if self.btn_export.isEnabled()
                                   else self.tr("Aplica o descarta los cambios del tema para exportarlo"))
        theme = self._draft("theme_id", TL.DEFAULT_THEME)
        mode = self._draft_mode()
        edits = self._pending.get("colors", {}).get(mode, {})
        tokens = {**self._draft_tokens(mode), **edits}
        self.color_editor.set_state(tokens, set(edits))
        shapes = self._draft_own_shapes()
        radius = self._draft("radius_override", None)
        if isinstance(radius, int):
            shapes.update(TL.radius_shapes(radius))
        size = self._draft("font_size_override", "default")
        if isinstance(size, int):
            shapes["tamano_fuente"] = size
        family = self._draft("font_family", "theme_default")
        if family == "theme_default":
            family = TL.get_theme_font(theme)
        panel = self._pending.get("panel", bg.get_panel_opacity())
        new_image = (self._pending.get("image_theme") or {}).get("background")
        if "theme_id" in self._pending and not new_image:
            new_image = appearance_store.preview_image(self._pending["theme_id"])
        has_image = new_image is not None or bg.image_path(bg.PLACE_GENERAL) is not None
        self._refresh_gallery()
        self.preview.set_draft(tokens, shapes, family, panel / 100 if has_image and panel < 100 else None, new_image)

    def _apply_pending(self, force=False):
        """Todo de golpe, con una sola recarga. force: aunque no quede nada pendiente (el tema
        activo pudo cambiar por dentro, como al crearlo de nuevo con el mismo nombre)."""
        from core.utils import background_images as bg
        if not self._pending and not force:
            return
        pending, self._pending = self._pending, {}
        config = get_config()
        # Una apariencia guardada trae sus imágenes y ajustes: lo actual se respalda antes, y lo
        # que se haya tocado además de elegirla (más abajo) manda sobre lo que ella traía.
        target = pending.get("theme_id")
        restoring = bool(target and appearance_store.has_appearance(target))
        replacing_image = bool((pending.get("image_theme") or {}).get("background"))
        if restoring or replacing_image:
            if target != appearance_store.PREVIOUS_ID:
                appearance_store.backup_previous()
        if restoring:
            appearance_store.restore(target)
            # Antes de recargar: la imagen anterior ya no existe y el lienzo aún apuntaría a ella.
            from gui.widgets.background_canvas import background_notifier
            for place in bg.PLACES:
                background_notifier().changed.emit(place)
        if "panel" in pending:
            bg.set_panel_opacity(pending.pop("panel"))
        if "previews" in pending:
            bg.set_previews_transparent(pending.pop("previews"))
        unsaved = pending.pop("image_theme", None)
        edits = pending.pop("colors", None)
        if unsaved:
            theme_io.save_imported(unsaved["id"], unsaved["data"])
            if unsaved["background"]:
                self._use_background(unsaved["background"])
        if edits:
            theme = pending.get("theme_id", config.get("theme_id", TL.DEFAULT_THEME))
            pending["theme_id"] = theme_io.apply_color_edits(theme, edits)
        if unsaved or edits:
            self._populate_themes()
            self.theme_combo.blockSignals(True)
            self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(pending["theme_id"])))
            self.theme_combo.blockSignals(False)
            self._update_mode_combo_state(pending["theme_id"])
        visual_reload = bool(pending)
        config.update(pending)
        if "theme_id" in pending or "theme_mode" in pending:
            sync_legacy_theme_key(config)
        save_config(config)
        logger.info(f"AppearancePage: cambios aplicados: {sorted(pending)}")
        self.theme_changed.emit(config.get("theme_id", "dowp"))
        if visual_reload:
            self.theme_restart_hint.show()
        if restoring or appearance_store.PREVIOUS_ID in theme_io.user_theme_ids():
            self._populate_themes()
            self.theme_combo.blockSignals(True)
            self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(config.get("theme_id"))))
            self.theme_combo.blockSignals(False)
        if restoring:
            self._reload_after_restore()
        self._sync_radius_control()
        self._refresh_pending()

    def _save_appearance(self):
        from gui.dialogs.theme_from_image_dialog import SaveAppearanceDialog
        config = get_config()
        current = config.get("theme_id", TL.DEFAULT_THEME)
        is_mine = theme_io.is_user_theme(current) and current != appearance_store.PREVIOUS_ID
        default = (TL.read_theme(current).get("meta") or {}).get("nombre", "") if is_mine else ""
        dialog = SaveAppearanceDialog(default, self.window())
        if not dialog.exec():
            return
        name = dialog.name_edit.text().strip()
        theme_id = theme_io.slugify(name)
        if theme_id in theme_io.builtin_theme_ids():
            theme_id = f"{theme_id}_usuario"
        if theme_io.is_user_theme(theme_id) and theme_id != current:
            answer = QMessageBox.question(self, dialog.windowTitle(),
                                          self.tr("Ya tienes un tema llamado «{0}». ¿Quieres reemplazarlo?").format(name))
            if answer != QMessageBox.Yes:
                return
        try:
            appearance_store.save(theme_id, name, current)
        except OSError as e:
            QMessageBox.warning(self, dialog.windowTitle(), self.tr("No se pudo guardar: {0}").format(e))
            return
        config["theme_id"] = theme_id
        sync_legacy_theme_key(config)
        save_config(config)
        self._populate_themes()
        self.theme_combo.blockSignals(True)
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(theme_id)))
        self.theme_combo.blockSignals(False)
        self._update_mode_combo_state(theme_id)
        self._refresh_pending()

    # ── Galería de temas ────────────────────────────────────────────────────
    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Algo menos de la mitad de la página, sin aplastar los ajustes de abajo en una ventana chica.
        self.top_widget.setFixedHeight(max(224, min(420, int(self.height() * 0.42), self.height() - 300)))

    def _gallery_tokens(self, theme_id):
        mode = self._draft_mode()
        if theme_id == "__modo__":
            return mode
        unsaved = self._pending.get("image_theme")
        if unsaved and unsaved["id"] == theme_id:
            return self._draft_tokens(mode)
        return TL.resolve_theme(theme_id, mode)

    def _refresh_gallery(self, force=False):
        builtin = self.tr("Temas de DowP")
        mine = self.tr("Mis temas")
        backup = self.tr("Respaldo automático")
        unsaved = self._pending.get("image_theme")
        items = []
        for i in range(self.theme_combo.count()):
            theme_id = self.theme_combo.itemData(i)
            if theme_id == appearance_store.PREVIOUS_ID:
                group = backup
            elif (unsaved and unsaved["id"] == theme_id) or theme_io.is_user_theme(theme_id):
                group = mine
            else:
                group = builtin
            label = self._theme_names.get(theme_id) or self.theme_combo.itemText(i)
            items.append((theme_id, label, group))
        order = {builtin: 0, mine: 1, backup: 2}
        items.sort(key=lambda item: order[item[2]])
        deletable = lambda t: theme_io.is_user_theme(t) and not (unsaved and unsaved["id"] == t)
        image_for = lambda t: (unsaved["background"] if unsaved and unsaved["id"] == t else None) or appearance_store.preview_image(t)
        self.gallery.set_themes(items, self._gallery_tokens, image_for, deletable,
                                self._draft("theme_id", TL.DEFAULT_THEME), get_config().get("theme_id", TL.DEFAULT_THEME), force)

    def _on_gallery_selected(self, theme_id):
        index = self.theme_combo.findData(theme_id)
        if index >= 0:
            self.theme_combo.setCurrentIndex(index)

    def _on_gallery_action(self, action, theme_id):
        if action == "apply":
            self._on_gallery_selected(theme_id)
            self._apply_pending()
        elif action == "export":
            self._export_theme()
        elif action == "duplicate":
            try:
                copy = theme_io.duplicate_theme(theme_id)
            except OSError as e:
                QMessageBox.warning(self, self.tr("No se pudo duplicar el tema"), str(e))
                return
            self._repopulate_keeping_choice(copy)
        elif action == "rename":
            from gui.dialogs.theme_from_image_dialog import SaveAppearanceDialog
            current = (TL.read_theme(theme_id).get("meta") or {}).get("nombre", theme_id)
            dialog = SaveAppearanceDialog(current, self.window(), renaming=True)
            if dialog.exec():
                theme_io.rename_user_theme(theme_id, dialog.name_edit.text().strip())
                self._repopulate_keeping_choice()

    def _repopulate_keeping_choice(self, _new_id=None):
        choice = self.theme_combo.currentData()
        self._populate_themes()
        self.theme_combo.blockSignals(True)
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(choice)))
        self.theme_combo.blockSignals(False)
        self._refresh_gallery(force=True)

    def _on_pick_toggled(self, picking):
        self.gallery.set_picking(picking)
        self.btn_delete_picked.setVisible(picking)
        self.btn_create_from_image.setVisible(not picking)
        self.btn_import.setVisible(not picking)

    def _on_picked_changed(self, count):
        self.btn_delete_picked.setText(self.tr("Eliminar ({0})").format(count))
        self.btn_delete_picked.setEnabled(count > 0)

    def _delete_themes(self, ids):
        """A la Papelera: se puede recuperar, así que una sola prueba no pide confirmación."""
        ids = [t for t in ids if theme_io.is_user_theme(t)]
        if not ids:
            return
        if len(ids) > 1:
            answer = QMessageBox.question(self, self.tr("Eliminar temas"),
                                          self.tr("¿Enviar {0} temas a la Papelera?").format(len(ids)))
            if answer != QMessageBox.Yes:
                return
        config = get_config()
        active_deleted = config.get("theme_id") in ids
        draft_deleted = self._pending.get("theme_id") in ids
        for theme_id in ids:
            try:
                theme_io.delete_user_theme(theme_id, to_trash=True)
            except OSError as e:
                QMessageBox.warning(self, self.tr("No se pudo eliminar el tema"), str(e))
                break
        if self.btn_pick.isChecked():
            self.btn_pick.setChecked(False)
        if active_deleted:
            self._pending.pop("colors", None)
            self._select_theme(TL.DEFAULT_THEME)
            return
        if draft_deleted:
            self._pending.pop("theme_id", None)
            self._pending.pop("colors", None)
            self.theme_combo.blockSignals(True)
            self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(config.get("theme_id"))))
            self.theme_combo.blockSignals(False)
        self._repopulate_keeping_choice()
        self._refresh_pending()

    def _reload_after_restore(self):
        self._is_loading = True
        self.load_current_settings()
        self._is_loading = False

    def _use_background(self, path):
        from core.utils import background_images as bg
        from gui.widgets.background_canvas import background_notifier
        try:
            bg.import_image(bg.PLACE_GENERAL, path)
        except Exception as e:
            QMessageBox.warning(self, self.tr("Imagen de fondo"), self.tr("No se pudo abrir la imagen: {0}").format(e))
            return
        self._load_background_settings()
        background_notifier().changed.emit(bg.PLACE_GENERAL)

    def _discard_pending(self):
        self._pending = {}
        self._is_loading = True
        self.load_current_settings()
        self._is_loading = False
        self._refresh_pending()

    def on_font_size_selection(self, value):
        if self._is_loading: return
        current = get_config().get("font_size_override", "default")
        self._set_pending("font_size_override", value, current if isinstance(current, int) else 13)
