import os
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
                                 QSpacerItem, QSizePolicy, QStyledItemDelegate, QScrollArea,
                                 QPushButton, QMessageBox, QToolButton, QRadioButton, QButtonGroup)
from PySide6.QtCore import Signal, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from core.logger.logger_manager import logger
from core.utils.config_manager import get_config, save_config
from core.utils.paths import get_user_themes_dir, get_user_fonts_dir
from core.utils.font_manager import get_available_fonts, init_fonts
from core.version import IS_BETA
from gui.styles import get_available_themes, apply_folder_open_button_style, get_theme_token, set_button_variant
from core.utils.theme_loader import sync_legacy_theme_key
from gui.widgets.toggle_switch import ToggleSwitch
from gui.widgets.combo_box import AutoPopupComboBox
from gui.widgets.top_aligned_layout import TopAlignedVBoxLayout
from gui.styles import set_themed_style

class GeneralPage(QWidget):
    language_changed = Signal(str)
    theme_changed = Signal(str)
    font_changed = Signal(str)
    update_channel_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self._is_loading = True
        self.init_ui()
        self.load_current_settings()
        self._is_loading = False

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(12)

        # Title
        self.title_label = QLabel(self.tr("Ajustes Generales"))
        self.title_label.setObjectName("settingsTitle")
        self.main_layout.addWidget(self.title_label)
        
        # Divider
        line = QFrame()
        line.setObjectName("settingsDivider")
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        self.main_layout.addWidget(line)

        # Crear el QScrollArea
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")
        
        # Widget contenedor para el contenido del scroll
        self.scroll_content = QWidget()
        self.scroll_content.setObjectName("settingsScrollContent")
        self.scroll_content.setStyleSheet("QWidget#settingsScrollContent { background-color: transparent; }")
        
        # Layout para el contenido del scroll
        self.content_layout = TopAlignedVBoxLayout(self.scroll_content)
        self.content_layout.setContentsMargins(0, 10, 10, 0)
        self.content_layout.setSpacing(12)

        # --- TARJETA: ACTUALIZACIONES DOWP ---
        # Mismo mecanismo visual de tarjeta que usan DenoCardPanel/GhostscriptCardPanel
        # en deps_page.py (setProperty variant="card", estilo centralizado via QSS) --
        # arriba de todo a pedido explicito del usuario, no una fila mas de texto plano.
        self.update_channel_card = QFrame()
        self.update_channel_card.setObjectName("updateChannelCard")
        self.update_channel_card.setProperty("variant", "card")

        card_layout = QVBoxLayout(self.update_channel_card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(8)

        card_top_row = QHBoxLayout()
        card_top_row.setSpacing(8)
        card_title = QLabel(self.tr("Actualizaciones DowP"))
        set_themed_style(card_title, lambda: f"font-size: 14px; font-weight: bold; color: {get_theme_token('texto_titulo', '#EEEEEE')};")
        card_top_row.addWidget(card_title)

        card_info_btn = QToolButton()
        card_info_btn.setText("?")
        card_info_btn.setFixedSize(20, 20)
        set_themed_style(card_info_btn, lambda: "QToolButton { border: 1px solid #555; border-radius: 10px;"
            f" color: {get_theme_token('texto_gris', '#AAA')}; font-size: 11px; background: #2a2a2a; }}")
        card_info_btn.setToolTip(self.tr(
            "Solo releases oficiales: recibe únicamente versiones estables, ya probadas.\n"
            "Todas (incluye experimentales): recibe también compilaciones de prueba, antes de "
            "que salgan como estables -- pueden traer errores nuevos sin detectar todavía."
        ))
        card_top_row.addWidget(card_info_btn)
        card_top_row.addStretch()
        card_layout.addLayout(card_top_row)

        channel_row = QHBoxLayout()
        channel_row.setSpacing(14)

        self._group_update_channel = QButtonGroup(self)
        self._radio_update_stable = self._make_radio(self.tr("Solo releases oficiales"), "stable")
        self._radio_update_stable.setToolTip(self.tr("Solo versiones estables, ya probadas"))
        self._radio_update_beta = self._make_radio(self.tr("Todas (incluye experimentales)"), "beta")
        self._radio_update_beta.setToolTip(self.tr("También compilaciones de prueba, antes de que salgan como estables"))
        self._group_update_channel.addButton(self._radio_update_stable, 0)
        self._group_update_channel.addButton(self._radio_update_beta, 1)
        self._group_update_channel.idClicked.connect(self._on_update_channel_radio_changed)

        channel_row.addWidget(self._radio_update_stable)
        channel_row.addWidget(self._radio_update_beta)
        channel_row.addStretch()
        card_layout.addLayout(channel_row)

        self.content_layout.addWidget(self.update_channel_card)

        # --- SECCIÓN: ASPECTO ---
        self.aspecto_label = QLabel(self.tr("Aspecto"))
        self.aspecto_label.setObjectName("settingsSectionTitle")
        self.content_layout.addWidget(self.aspecto_label)

        # 1. Idioma
        self.lang_row = QHBoxLayout()
        self.lang_label = QLabel(self.tr("Idioma de la aplicación"))
        self.lang_label.setObjectName("settingsLabel")
        
        self.lang_combo = AutoPopupComboBox()
        self.lang_combo.setFixedWidth(180)
        self.lang_combo.addItem("Español", "es")
        self.lang_combo.addItem("English", "en")
        self.lang_combo.addItem("Português (Brasil)", "pt_BR")
        
        self.lang_row.addWidget(self.lang_label)
        self.lang_row.addStretch()
        self.lang_row.addWidget(self.lang_combo)
        self.content_layout.addLayout(self.lang_row)

        # 2. Tema
        self.theme_row = QHBoxLayout()
        self.theme_label = QLabel(self.tr("Tema visual"))
        self.theme_label.setObjectName("settingsLabel")
        
        self.theme_combo = AutoPopupComboBox()
        self.theme_combo.setFixedWidth(180)
        
        self.btn_open_themes = QPushButton()
        self.btn_open_themes.setFixedSize(30, 30)
        apply_folder_open_button_style(self.btn_open_themes, tooltip=self.tr("Importar, exportar o eliminar temas"), icon_size=15)
        self.btn_open_themes.clicked.connect(self._show_themes_menu)

        self.theme_row.addWidget(self.theme_label)
        self.theme_row.addStretch()
        self.theme_row.addWidget(self.theme_combo)
        self.theme_row.addWidget(self.btn_open_themes)
        self.content_layout.addLayout(self.theme_row)

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
        self.mode_row.addSpacing(30 + self.theme_row.spacing())
        self.content_layout.addLayout(self.mode_row)


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
        
        self.btn_apply_font_size = QPushButton(self.tr("Aplicar"))
        self.btn_apply_font_size.setFixedWidth(80)
        self.btn_apply_font_size.setFixedHeight(30)
        self.btn_apply_font_size.setCursor(Qt.PointingHandCursor)
        set_button_variant(self.btn_apply_font_size, "secondary")
        self.btn_apply_font_size.clicked.connect(lambda: self.on_font_size_selection(self.font_size_spin.value()))
        
        self.font_size_row.addWidget(self.font_size_label)
        self.font_size_row.addStretch()
        self.font_size_row.addWidget(self.font_size_spin)
        self.font_size_row.addWidget(self.btn_apply_font_size)
        # Mismo ancho que el botón de carpeta de la fila de Fuente, para alinear los controles.
        self.font_size_row.addSpacing(30 + self.font_row.spacing())
        self.content_layout.addLayout(self.font_size_row)

        self.font_size_warning = QLabel(self.tr("⚠️ Tamaños mayores a 18px pueden causar que algunos textos y botones se vean cortados."))
        set_themed_style(self.font_size_warning, lambda: f"color: {get_theme_token('estado_alerta', '#ffa500')}; font-size: 11px;")
        self.font_size_warning.setWordWrap(True)
        self.font_size_warning.hide()
        self.content_layout.addWidget(self.font_size_warning)
        
        self.font_size_spin.valueChanged.connect(lambda v: self.font_size_warning.setVisible(v > 18))

        # Aviso tras cambiar tema o modo: la mayor parte se actualiza en vivo, pero algunos
        # estilos se calculan al crear cada widget y solo cambian del todo al reiniciar.
        # Sin diálogo (a diferencia del idioma) para no interrumpir mientras se prueban modos.
        self.theme_restart_hint = QWidget()
        hint_row = QHBoxLayout(self.theme_restart_hint)
        hint_row.setContentsMargins(0, 0, 0, 0)
        self.theme_restart_label = QLabel(self.tr("Si alguna parte no cambió de aspecto, reiniciar DowP la actualiza."))
        self.theme_restart_label.setWordWrap(True)
        set_themed_style(self.theme_restart_label, lambda: f"color: {get_theme_token('texto_secundario', '#666666')}; font-size: 11px;")
        self.btn_theme_restart = QPushButton(self.tr("Reiniciar ahora"))
        set_button_variant(self.btn_theme_restart, "accent-solid")
        self.btn_theme_restart.clicked.connect(self._restart_for_theme)
        hint_row.addWidget(self.theme_restart_label, 1)
        hint_row.addWidget(self.btn_theme_restart)
        self.theme_restart_hint.hide()
        self.content_layout.addWidget(self.theme_restart_hint)

        # --- SECCIÓN: COMPORTAMIENTO ---
        self.comp_label = QLabel(self.tr("Comportamiento"))
        self.comp_label.setObjectName("settingsSectionTitle")
        self.content_layout.addWidget(self.comp_label)

        # 3. Switch: Análisis automático
        self.auto_row = QHBoxLayout()
        self.auto_label = QLabel(self.tr("Analizar automáticamente al pegar URL"))
        self.auto_label.setObjectName("settingsLabel")
        
        self.auto_switch = ToggleSwitch()
        self.auto_row.addWidget(self.auto_label)
        self.auto_row.addStretch()
        self.auto_row.addWidget(self.auto_switch)
        self.content_layout.addLayout(self.auto_row)

        # 4. Switch: Auto-pegar URL del portapapeles
        self.paste_row = QHBoxLayout()
        self.paste_vbox = QVBoxLayout()
        
        self.paste_label = QLabel(self.tr("Auto-pegar URL del portapapeles"))
        self.paste_label.setObjectName("settingsLabel")
        
        self.paste_desc = QLabel(self.tr("Al volver a la ventana, pega automáticamente la URL copiada en el campo de análisis."))
        set_themed_style(self.paste_desc, lambda: f"color: {get_theme_token('texto_tenue', '#888888')}; font-size: 11px;")
        self.paste_desc.setWordWrap(True)
        
        self.paste_vbox.addWidget(self.paste_label)
        self.paste_vbox.addWidget(self.paste_desc)
        
        self.paste_switch = ToggleSwitch()
        
        self.paste_row.addLayout(self.paste_vbox, 1)
        self.paste_row.addWidget(self.paste_switch)
        self.content_layout.addLayout(self.paste_row)

        # 5. Switch: Compatibilidad Adobe (Selección predeterminada)
        self.adobe_row = QHBoxLayout()
        self.adobe_vbox = QVBoxLayout()
        
        self.adobe_label = QLabel(self.tr("Selección predeterminada para Adobe"))
        self.adobe_label.setObjectName("settingsLabel")
        
        self.adobe_desc = QLabel(self.tr("Si está activo, preseleccionará el formato más compatible (✨). Si no, la mejor calidad absoluta."))
        self.adobe_desc.setWordWrap(True)
        set_themed_style(self.adobe_desc, lambda: f"color: {get_theme_token('texto_tenue', '#888888')}; font-size: 11px;") # Compact description
        
        self.adobe_vbox.addWidget(self.adobe_label)
        self.adobe_vbox.addWidget(self.adobe_desc)
        
        self.adobe_switch = ToggleSwitch()
        
        self.adobe_row.addLayout(self.adobe_vbox, 1)
        self.adobe_row.addWidget(self.adobe_switch)
        self.content_layout.addLayout(self.adobe_row)

        # 5b. Switch: Desplazamiento con rueda en menús desplegables
        self.combo_wheel_row = QHBoxLayout()
        self.combo_wheel_vbox = QVBoxLayout()

        self.combo_wheel_label = QLabel(self.tr("Cambiar opción con la rueda en menús"))
        self.combo_wheel_label.setObjectName("settingsLabel")

        self.combo_wheel_desc = QLabel(self.tr("Permite cambiar la opción seleccionada al pasar la rueda del ratón sobre un menú cerrado. Si está desactivado (recomendado), la rueda desplazará la página normalmente."))
        self.combo_wheel_desc.setWordWrap(True)
        set_themed_style(self.combo_wheel_desc, lambda: f"color: {get_theme_token('texto_tenue', '#888888')}; font-size: 11px;")

        self.combo_wheel_vbox.addWidget(self.combo_wheel_label)
        self.combo_wheel_vbox.addWidget(self.combo_wheel_desc)

        self.combo_wheel_switch = ToggleSwitch()

        self.combo_wheel_row.addLayout(self.combo_wheel_vbox, 1)
        self.combo_wheel_row.addWidget(self.combo_wheel_switch)
        self.content_layout.addLayout(self.combo_wheel_row)

        # 6. Botón: Restablecer Tutoriales
        self.tutorials_row = QHBoxLayout()
        self.tutorials_vbox = QVBoxLayout()
        
        self.tutorials_label = QLabel(self.tr("Tutoriales interactivos"))
        self.tutorials_label.setObjectName("settingsLabel")
        
        self.tutorials_desc = QLabel(self.tr("Si deseas volver a ver los tutoriales iniciales de cada pestaña, puedes restablecerlos aquí."))
        set_themed_style(self.tutorials_desc, lambda: f"color: {get_theme_token('texto_tenue', '#888888')}; font-size: 11px;")
        self.tutorials_desc.setWordWrap(True)
        
        self.tutorials_vbox.addWidget(self.tutorials_label)
        self.tutorials_vbox.addWidget(self.tutorials_desc)
        
        self.btn_reset_tutorials = QPushButton(self.tr("Restablecer"))
        self.btn_reset_tutorials.setCursor(Qt.PointingHandCursor)
        self.btn_reset_tutorials.setFixedWidth(120)
        self.btn_reset_tutorials.setProperty("variant", "secondary")
        self.btn_reset_tutorials.clicked.connect(self._on_reset_tutorials_clicked)
        
        self.tutorials_row.addLayout(self.tutorials_vbox, 1)
        self.tutorials_row.addWidget(self.btn_reset_tutorials)
        self.content_layout.addLayout(self.tutorials_row)

        self._build_sounds_section()

        # Finalizar setup del scroll area
        self.scroll_area.setWidget(self.scroll_content)
        self.main_layout.addWidget(self.scroll_area)

        # Configuración de colores del switch (basado en tema)
        self.update_switch_colors()

        # Connections
        self.lang_combo.currentIndexChanged.connect(self.on_language_selection)
        self.theme_combo.currentIndexChanged.connect(self.on_theme_selection)
        self.mode_combo.currentIndexChanged.connect(self.on_mode_selection)
        self.font_combo.currentIndexChanged.connect(self.on_font_selection)
        self.auto_switch.toggled.connect(self.on_auto_analyze_toggled)
        self.paste_switch.toggled.connect(self.on_auto_paste_toggled)
        self.adobe_switch.toggled.connect(self.on_adobe_compat_toggled)
        self.combo_wheel_switch.toggled.connect(self.on_combo_wheel_toggled)


    # ── SECCIÓN: SONIDOS (ver core/utils/sound_notifier.py) ──────────────────
    def _build_sounds_section(self):
        from core.utils import sound_notifier as sn

        self.sounds_label = QLabel(self.tr("Sonidos"))
        self.sounds_label.setObjectName("settingsSectionTitle")
        self.content_layout.addWidget(self.sounds_label)

        # Activar / desactivar
        enable_row = QHBoxLayout()
        enable_vbox = QVBoxLayout()
        enable_label = QLabel(self.tr("Sonido al terminar un proceso"))
        enable_label.setObjectName("settingsLabel")
        enable_desc = QLabel(self.tr(
            "Suena al terminar en Modo Rápido, Proceso Avanzado, Herramientas Multimedia "
            "y Herramientas de Imagen. Un sonido para cuando todo sale bien y otro si algo falla."))
        set_themed_style(enable_desc, lambda: f"color: {get_theme_token('texto_tenue', '#888888')}; font-size: 11px;")
        enable_desc.setWordWrap(True)
        enable_vbox.addWidget(enable_label)
        enable_vbox.addWidget(enable_desc)
        self.sound_switch = ToggleSwitch()
        enable_row.addLayout(enable_vbox, 1)
        enable_row.addWidget(self.sound_switch)
        self.content_layout.addLayout(enable_row)

        # Cuándo sonar
        when_row = QHBoxLayout()
        self.sound_when_label = QLabel(self.tr("Cuándo sonar"))
        self.sound_when_label.setObjectName("settingsLabel")
        self.sound_when_combo = AutoPopupComboBox()
        self.sound_when_combo.setFixedWidth(220)
        self.sound_when_combo.addItem(self.tr("Al terminar todo"), sn.WHEN_GROUP)
        self.sound_when_combo.addItem(self.tr("Al terminar cada elemento"), sn.WHEN_ITEM)
        self.sound_when_combo.addItem(self.tr("Ambos"), sn.WHEN_BOTH)
        self.sound_when_combo.setToolTip(self.tr(
            "Al terminar todo: un solo sonido cuando acaba toda la tanda (de error si algo falló).\n"
            "Al terminar cada elemento: un sonido por cada descarga, archivo o imagen.\n"
            "Ambos: por cada elemento y también al final."))
        when_row.addWidget(self.sound_when_label)
        when_row.addStretch()
        when_row.addWidget(self.sound_when_combo)
        self.content_layout.addLayout(when_row)

        # Sonido de éxito / de error
        self._sound_name_labels = {}
        self._sound_reset_buttons = {}
        self._sound_rows_widgets = [self.sound_when_label, self.sound_when_combo]
        for kind, title in ((sn.KIND_SUCCESS, self.tr("Sonido de éxito")),
                            (sn.KIND_ERROR, self.tr("Sonido de error"))):
            row = QHBoxLayout()
            vbox = QVBoxLayout()
            label = QLabel(title)
            label.setObjectName("settingsLabel")
            name_label = QLabel()
            set_themed_style(name_label, lambda: f"color: {get_theme_token('texto_tenue', '#888888')}; font-size: 11px;")
            vbox.addWidget(label)
            vbox.addWidget(name_label)

            btn_test = QPushButton(self.tr("Probar"))
            btn_test.setProperty("variant", "secondary")
            btn_test.setCursor(Qt.PointingHandCursor)
            btn_test.setFixedWidth(80)
            btn_test.clicked.connect(lambda _=False, k=kind: sn.get_sound_notifier().play(k, force=True))

            btn_choose = QPushButton(self.tr("Elegir..."))
            btn_choose.setProperty("variant", "secondary")
            btn_choose.setCursor(Qt.PointingHandCursor)
            btn_choose.setFixedWidth(90)
            btn_choose.setToolTip(self.tr("WAV, MP3 u OGG, de hasta 10 segundos y 2 MB."))
            btn_choose.clicked.connect(lambda _=False, k=kind: self._on_choose_sound(k))

            btn_reset = QPushButton(self.tr("Restablecer"))
            btn_reset.setProperty("variant", "secondary")
            btn_reset.setCursor(Qt.PointingHandCursor)
            btn_reset.setFixedWidth(120)
            btn_reset.setToolTip(self.tr("Volver al sonido predeterminado de DowP"))
            btn_reset.clicked.connect(lambda _=False, k=kind: self._on_reset_sound(k))

            row.addLayout(vbox, 1)
            row.addWidget(btn_test)
            row.addWidget(btn_choose)
            row.addWidget(btn_reset)
            self.content_layout.addLayout(row)

            self._sound_name_labels[kind] = name_label
            self._sound_reset_buttons[kind] = btn_reset
            self._sound_rows_widgets += [label, name_label, btn_test, btn_choose, btn_reset]

        # Volumen
        from PySide6.QtWidgets import QSlider
        volume_row = QHBoxLayout()
        self.sound_volume_label = QLabel(self.tr("Volumen"))
        self.sound_volume_label.setObjectName("settingsLabel")
        self.sound_volume_slider = QSlider(Qt.Horizontal)
        self.sound_volume_slider.setRange(0, 100)
        self.sound_volume_slider.setFixedWidth(180)
        self.sound_volume_value = QLabel()
        self.sound_volume_value.setFixedWidth(40)
        volume_row.addWidget(self.sound_volume_label)
        volume_row.addStretch()
        volume_row.addWidget(self.sound_volume_slider)
        volume_row.addWidget(self.sound_volume_value)
        self.content_layout.addLayout(volume_row)
        self._sound_rows_widgets += [self.sound_volume_label, self.sound_volume_slider, self.sound_volume_value]

        self.sound_switch.toggled.connect(self._on_sound_enabled_toggled)
        self.sound_when_combo.currentIndexChanged.connect(self._on_sound_when_changed)
        self.sound_volume_slider.valueChanged.connect(self._on_sound_volume_changed)
        # Se guarda al soltar el control, no en cada paso (cada guardado escribe config.json).
        self.sound_volume_slider.sliderReleased.connect(lambda: save_config(get_config()))

    def _load_sound_settings(self):
        from core.utils import sound_notifier as sn
        config = get_config()
        self.sound_switch.setChecked(bool(config.get(sn.CFG_ENABLED, True)))
        index = self.sound_when_combo.findData(config.get(sn.CFG_WHEN, sn.WHEN_GROUP))
        self.sound_when_combo.setCurrentIndex(index if index >= 0 else 0)
        volume = int(config.get(sn.CFG_VOLUME, 70))
        self.sound_volume_slider.setValue(volume)
        self.sound_volume_value.setText(f"{volume}%")
        self._refresh_sound_names()
        self._update_sound_rows_enabled()

    def _refresh_sound_names(self):
        from core.utils import sound_notifier as sn
        config = get_config()
        for kind, label in self._sound_name_labels.items():
            custom = config.get(sn.CFG_CUSTOM[kind], "")
            has_custom = bool(custom) and os.path.isfile(custom)
            name = config.get(sn.CFG_CUSTOM_NAME[kind], "") if has_custom else ""
            label.setText(name or (self.tr("Personalizado") if has_custom else self.tr("Predeterminado")))
            self._sound_reset_buttons[kind].setEnabled(has_custom and self.sound_switch.isChecked())

    def _update_sound_rows_enabled(self):
        enabled = self.sound_switch.isChecked()
        for widget in self._sound_rows_widgets:
            widget.setEnabled(enabled)
        if enabled:
            self._refresh_sound_names()

    def _on_sound_enabled_toggled(self, checked):
        self._update_sound_rows_enabled()
        if self._is_loading: return
        from core.utils import sound_notifier as sn
        config = get_config()
        config[sn.CFG_ENABLED] = checked
        save_config(config)
        logger.info(f"GeneralPage: Sonido al terminar procesos: {checked}")

    def _on_sound_when_changed(self, index):
        if self._is_loading: return
        from core.utils import sound_notifier as sn
        config = get_config()
        config[sn.CFG_WHEN] = self.sound_when_combo.itemData(index)
        save_config(config)
        logger.info(f"GeneralPage: Cuándo sonar: {config[sn.CFG_WHEN]}")

    def _on_sound_volume_changed(self, value):
        self.sound_volume_value.setText(f"{value}%")
        if self._is_loading: return
        from core.utils import sound_notifier as sn
        get_config()[sn.CFG_VOLUME] = int(value)

    def _on_choose_sound(self, kind):
        from PySide6.QtWidgets import QFileDialog
        from core.utils import sound_notifier as sn
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Elegir sonido"), "", self.tr("Audio (*.wav *.mp3 *.ogg)"))
        if not path:
            return
        ok, reason = sn.import_custom_sound(path, kind)
        if not ok:
            messages = {
                "ext": self.tr("Formato no admitido. Usa un archivo WAV, MP3 u OGG."),
                "size": self.tr("El archivo pesa más de 2 MB."),
                "duration": self.tr("El sonido dura más de 10 segundos."),
                "ffmpeg": self.tr("Hace falta FFmpeg para preparar el sonido. Instálalo desde Ajustes > Dependencias."),
                "convert": self.tr("No se pudo leer el archivo de audio. Prueba con otro."),
            }
            QMessageBox.warning(self, self.tr("No se pudo usar ese sonido"),
                                messages.get(reason, messages["convert"]))
            return
        self._refresh_sound_names()
        sn.get_sound_notifier().play(kind, force=True)

    def _on_reset_sound(self, kind):
        from core.utils import sound_notifier as sn
        sn.reset_custom_sound(kind)
        self._refresh_sound_names()

    # ── Gestión de temas (importar / exportar / eliminar) ─────────────────────
    def _show_themes_menu(self):
        from PySide6.QtWidgets import QMenu
        from core.utils import theme_io
        current = self.theme_combo.currentData() or "dowp"
        menu = QMenu(self)
        menu.addAction(self.tr("Importar tema…"), self._import_theme)
        menu.addAction(self.tr("Exportar tema actual…"), self._export_theme)
        act_delete = menu.addAction(self.tr("Eliminar este tema"), self._delete_theme)
        act_delete.setEnabled(theme_io.is_user_theme(current))
        menu.addSeparator()
        menu.addAction(self.tr("Abrir carpeta de temas"), self._open_user_themes_dir)
        menu.exec(self.btn_open_themes.mapToGlobal(self.btn_open_themes.rect().bottomLeft()))

    def _select_theme(self, theme_id):
        """Recarga la lista y elige el tema (lo aplica on_theme_selection)."""
        self._populate_themes()
        index = self.theme_combo.findData(theme_id)
        if index < 0:
            index = self.theme_combo.findData("dowp")
        if self.theme_combo.currentIndex() == index:
            self.on_theme_selection(index)
        else:
            self.theme_combo.setCurrentIndex(index)

    def _import_theme(self):
        from PySide6.QtWidgets import QFileDialog
        from core.utils import theme_io
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Importar tema"), os.path.expanduser("~"), self.tr("Temas de DowP (*.json)"))
        if not path:
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

    def _export_theme(self):
        from PySide6.QtWidgets import QFileDialog
        from core.utils import theme_io
        theme_id = self.theme_combo.currentData() or "dowp"
        suggested = os.path.join(os.path.expanduser("~"), f"{theme_id}.json")
        path, _ = QFileDialog.getSaveFileName(
            self, self.tr("Exportar tema"), suggested, self.tr("Temas de DowP (*.json)"))
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            theme_io.export_theme(theme_id, path)
        except OSError as e:
            QMessageBox.warning(self, self.tr("No se pudo exportar el tema"), str(e))
            return
        QMessageBox.information(
            self, self.tr("Tema exportado"),
            self.tr("Se guardó el tema completo, con sus dos modos, formas y tipografía. "
                    "Puedes editarlo y volver a importarlo, o compartirlo.") + "\n\n" + path)

    def _delete_theme(self):
        from core.utils import theme_io
        theme_id = self.theme_combo.currentData()
        if not theme_id or not theme_io.is_user_theme(theme_id):
            return
        answer = QMessageBox.question(
            self, self.tr("Eliminar tema"),
            self.tr("¿Eliminar el tema «{0}»? Se volverá al tema DowP.").format(self.theme_combo.currentText()))
        if answer != QMessageBox.Yes:
            return
        try:
            theme_io.delete_user_theme(theme_id)
        except OSError as e:
            QMessageBox.warning(self, self.tr("No se pudo eliminar el tema"), str(e))
            return
        self._select_theme("dowp")

    def _open_user_themes_dir(self):
        """Abre la carpeta de temas personalizados del usuario en el explorador de archivos."""
        themes_dir = get_user_themes_dir()
        QDesktopServices.openUrl(QUrl.fromLocalFile(themes_dir))
        logger.info(f"GeneralPage: Abierta carpeta de temas: {themes_dir}")

    def _open_user_fonts_dir(self):
        """Abre la carpeta de fuentes personalizadas del usuario en el explorador de archivos."""
        fonts_dir = get_user_fonts_dir()
        QDesktopServices.openUrl(QUrl.fromLocalFile(fonts_dir))
        logger.info(f"GeneralPage: Abierta carpeta de fuentes: {fonts_dir}")

    def _populate_themes(self):
        """Carga los temas disponibles dinámicamente."""
        self.theme_combo.blockSignals(True)
        self.theme_combo.clear()
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

    def update_switch_colors(self):
        accent = get_theme_token("acento_primario", "#B9E640")
        off = get_theme_token("switch_apagado", "#333333")
        self.auto_switch.setTrackColors(off, accent)
        self.paste_switch.setTrackColors(off, accent)
        self.adobe_switch.setTrackColors(off, accent)
        if hasattr(self, "combo_wheel_switch"):
            self.combo_wheel_switch.setTrackColors(off, accent)
        if hasattr(self, "sound_switch"):
            self.sound_switch.setTrackColors(off, accent)

    def load_current_settings(self):
        config = get_config()

        # Load Update Channel
        default_channel = "beta" if IS_BETA else "stable"
        if config.get("update_channel", default_channel) == "beta":
            self._radio_update_beta.setChecked(True)
        else:
            self._radio_update_stable.setChecked(True)

        # Load Language
        lang = config.get("language", "es")
        index = self.lang_combo.findData(lang)
        if index >= 0:
            self.lang_combo.setCurrentIndex(index)
            
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
            
        # Load Switches
        self.auto_switch.setChecked(config.get("auto_analyze", True))
        self.paste_switch.setChecked(config.get("auto_paste_url", True))
        self.adobe_switch.setChecked(config.get("adobe_compat_default", True))
        self.combo_wheel_switch.setChecked(config.get("combobox_wheel_scroll", False))
        self._load_sound_settings()

    def _make_radio(self, text, code):
        rb = QRadioButton(text)
        rb.setProperty("code", code)
        return rb

    def _on_update_channel_radio_changed(self, btn_id):
        if self._is_loading:
            return
        channel = "beta" if btn_id == 1 else "stable"
        config = get_config()
        if config.get("update_channel") != channel:
            config["update_channel"] = channel
            save_config(config)
            logger.info(f"GeneralPage: Canal de actualizaciones cambiado a '{channel.upper()}'.")
            self.update_channel_changed.emit(channel)

    def on_language_selection(self, index):
        if self._is_loading: return
        lang_code = self.lang_combo.itemData(index)
        config = get_config()
        if config.get("language") != lang_code:
            config["language"] = lang_code
            save_config(config)
            logger.info(f"GeneralPage: Idioma guardado: {lang_code}. Reinicio requerido.")
            self.language_changed.emit(lang_code)
            self._prompt_language_restart()

    def _prompt_language_restart(self):
        """El idioma solo se aplica entero al arrancar: el .qm se instala una vez
        (core/utils/i18n.py) y muchos textos son constantes de módulo ya resueltas
        en el import, así que sin reiniciar la UI quedaría mitad en un idioma y
        mitad en el otro. Se ofrece reiniciar en el momento."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(self.tr("Reinicio necesario"))
        box.setText(self.tr("El idioma cambia al reiniciar DowP."))
        box.setInformativeText(self.tr(
            "La preferencia ya quedó guardada. Si sigues sin reiniciar, la interfaz "
            "se queda en el idioma actual hasta la próxima vez que abras la aplicación."
        ))
        btn_restart = box.addButton(self.tr("Reiniciar ahora"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(self.tr("Más tarde"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(btn_restart)
        try:
            from gui.dialogs.dialogs import _apply_dialog_styles
            _apply_dialog_styles(box)
        except Exception as e:
            logger.error(f"GeneralPage: no se pudieron aplicar estilos al diálogo de reinicio: {e}")
        box.exec()

        if box.clickedButton() is not btn_restart:
            logger.info("GeneralPage: reinicio pospuesto por el usuario tras cambiar de idioma.")
            return

        from core.utils.app_restart import restart_app
        if restart_app():
            from PySide6.QtWidgets import QApplication
            QApplication.instance().quit()
        else:
            QMessageBox.warning(
                self,
                self.tr("No se pudo reiniciar"),
                self.tr("Cierra y vuelve a abrir DowP a mano para aplicar el idioma nuevo."),
            )

    def on_theme_selection(self, index):
        if self._is_loading: return
        theme_code = self.theme_combo.itemData(index)
        if not theme_code: return
        config = get_config()
        if config.get("theme_id") != theme_code:
            config["theme_id"] = theme_code
            sync_legacy_theme_key(config)
            save_config(config)
            logger.info(f"GeneralPage: Tema cambiado a {theme_code}")
            self._update_mode_combo_state(theme_code)
            # Primero se aplica el tema (MainWindow.update_theme) y después se leen sus
            # colores: al revés, los interruptores tomaban los del tema anterior.
            self.theme_changed.emit(theme_code)
            self.update_switch_colors()
            self.theme_restart_hint.show()

    def on_mode_selection(self, index):
        if self._is_loading: return
        mode = self.mode_combo.itemData(index)
        if not mode: return
        config = get_config()
        if config.get("theme_mode") != mode:
            config["theme_mode"] = mode
            sync_legacy_theme_key(config)
            save_config(config)
            logger.info(f"GeneralPage: Modo de tema cambiado a {mode}")
            self.theme_changed.emit(config.get("theme_id", "dowp"))
            self.update_switch_colors()
            self.theme_restart_hint.show()

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
        config = get_config()
        if config.get("font_family") != font_code:
            config["font_family"] = font_code
            save_config(config)
            logger.info(f"GeneralPage: Tipografía cambiada a {font_code}")
            self.font_changed.emit(font_code)

    def on_font_size_selection(self, value):
        if self._is_loading: return
        config = get_config()
        if config.get("font_size_override") != value:
            config["font_size_override"] = value
            save_config(config)
            logger.info(f"GeneralPage: Tamaño de texto cambiado a {value}")
            self.theme_changed.emit(config.get("theme_id", "dowp"))
            self.theme_restart_hint.show()

    def on_auto_analyze_toggled(self, checked):
        if self._is_loading: return
        config = get_config()
        config["auto_analyze"] = checked
        save_config(config)
        logger.info(f"GeneralPage: Auto-análisis cambiado a: {checked}")

    def on_auto_paste_toggled(self, checked):
        if self._is_loading: return
        config = get_config()
        config["auto_paste_url"] = checked
        save_config(config)
        # Actualizar el monitor en tiempo real
        from core.utils.clipboard_monitor import ClipboardURLMonitor
        ClipboardURLMonitor.instance().set_enabled(checked)
        logger.info(f"GeneralPage: Auto-pegar URL cambiado a: {checked}")

    def on_adobe_compat_toggled(self, checked):
        if self._is_loading: return
        config = get_config()
        config["adobe_compat_default"] = checked
        save_config(config)
        logger.info(f"GeneralPage: Selección Adobe por defecto cambiada a: {checked}")

    def on_combo_wheel_toggled(self, checked):
        if self._is_loading: return
        config = get_config()
        config["combobox_wheel_scroll"] = checked
        save_config(config)
        logger.info(f"GeneralPage: Scroll de rueda en menús cambiado a: {checked}")

    def _on_reset_tutorials_clicked(self):
        config = get_config()
        config["tutorial_quick_mode_seen"] = False
        config["tutorial_advanced_process_seen"] = False
        config["tutorial_image_tools_seen"] = False
        config["tutorial_video_tools_seen"] = False
        config["tutorial_editing_media_seen"] = False
        config["tutorial_subclip_seen"] = False
        save_config(config)
        
        QMessageBox.information(
            self,
            self.tr("Tutoriales restablecidos"),
            self.tr("Los tutoriales interactivos volverán a mostrarse la próxima vez que abras sus respectivas pestañas.")
        )
        logger.info("GeneralPage: Tutoriales interactivos restablecidos.")
