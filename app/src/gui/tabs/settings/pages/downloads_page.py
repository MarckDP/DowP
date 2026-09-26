from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QScrollArea, QSpinBox, QDoubleSpinBox, QPushButton,
    QMessageBox,
)
from PySide6.QtCore import Qt
from core.utils.i18n import logger
from core.utils.config_manager import get_config, save_config
from gui.widgets.toggle_switch import ToggleSwitch
from gui.styles import get_theme_token, set_button_variant
from core.utils.download_history import download_history, DEFAULT_MAX_ENTRIES


class DownloadsPage(QWidget):
    """Página de ajustes de Descargas."""

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
        self.title_label = QLabel(self.tr("Descargas"))
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
        self.content_layout = QVBoxLayout(self.scroll_content)
        self.content_layout.setContentsMargins(0, 10, 10, 0)
        self.content_layout.setSpacing(12)
        self.content_layout.setAlignment(Qt.AlignTop)

        # --- SECCIÓN: OPCIONES DE DESCARGA ---
        self.dl_section_label = QLabel(self.tr("Opciones de Descarga"))
        self.dl_section_label.setObjectName("settingsSectionTitle")
        self.content_layout.addWidget(self.dl_section_label)

        # 1. Switch: Incrustar Metadatos
        self.metadata_row = QHBoxLayout()
        self.metadata_vbox = QVBoxLayout()
        self.metadata_label = QLabel(self.tr("Incrustar Metadatos"))
        self.metadata_label.setObjectName("settingsLabel")
        self.metadata_desc = QLabel(self.tr("Añade información del video (título, autor, fecha) dentro del archivo multimedia."))
        self.metadata_desc.setStyleSheet("color: #888888; font-size: 11px;")
        self.metadata_vbox.addWidget(self.metadata_label)
        self.metadata_vbox.addWidget(self.metadata_desc)
        self.metadata_switch = ToggleSwitch()
        self.metadata_row.addLayout(self.metadata_vbox)
        self.metadata_row.addStretch()
        self.metadata_row.addWidget(self.metadata_switch)
        self.content_layout.addLayout(self.metadata_row)

        # 2. Switch: Incrustar Carátula
        self.thumb_row = QHBoxLayout()
        self.thumb_vbox = QVBoxLayout()
        self.thumb_label = QLabel(self.tr("Incrustar carátula"))
        self.thumb_label.setObjectName("settingsLabel")
        self.thumb_desc = QLabel(self.tr("Utiliza la miniatura del video como imagen de portada del archivo descargado."))
        self.thumb_desc.setStyleSheet("color: #888888; font-size: 11px;")
        self.thumb_vbox.addWidget(self.thumb_label)
        self.thumb_vbox.addWidget(self.thumb_desc)
        self.thumb_switch = ToggleSwitch()
        self.thumb_row.addLayout(self.thumb_vbox)
        self.thumb_row.addStretch()
        self.thumb_row.addWidget(self.thumb_switch)
        self.content_layout.addLayout(self.thumb_row)

        # 3. Switch: Eliminar Sponsors (SponsorBlock)
        self.sponsors_row = QHBoxLayout()
        self.sponsors_vbox = QVBoxLayout()
        self.sponsors_label = QLabel(self.tr("Eliminar sponsors"))
        self.sponsors_label.setObjectName("settingsLabel")
        self.sponsors_desc = QLabel(self.tr("Utiliza SponsorBlock para identificar y omitir segmentos publicitarios dentro del video."))
        self.sponsors_desc.setStyleSheet("color: #888888; font-size: 11px;")
        self.sponsors_vbox.addWidget(self.sponsors_label)
        self.sponsors_vbox.addWidget(self.sponsors_desc)
        self.sponsors_switch = ToggleSwitch()
        self.sponsors_row.addLayout(self.sponsors_vbox)
        self.sponsors_row.addStretch()
        self.sponsors_row.addWidget(self.sponsors_switch)
        self.content_layout.addLayout(self.sponsors_row)

        # 4. Switch: Impersonate
        self.imp_row = QHBoxLayout()
        self.imp_vbox = QVBoxLayout()
        self.imp_label = QLabel(self.tr("Usar Impersonate (Disfraz de Navegador)"))
        self.imp_label.setObjectName("settingsLabel")
        self.imp_desc = QLabel(self.tr("Evita bloqueos de YouTube simulando ser Chrome. (Puede ser más lento)"))
        self.imp_desc.setStyleSheet("color: #888888; font-size: 11px;")
        self.imp_vbox.addWidget(self.imp_label)
        self.imp_vbox.addWidget(self.imp_desc)
        self.imp_switch = ToggleSwitch()
        self.imp_row.addLayout(self.imp_vbox)
        self.imp_row.addStretch()
        self.imp_row.addWidget(self.imp_switch)
        self.content_layout.addLayout(self.imp_row)

        # 5. SpinBox: Descargas simultáneas
        self.concurrent_row = QHBoxLayout()
        self.concurrent_vbox = QVBoxLayout()
        self.concurrent_label = QLabel(self.tr("Descargas simultáneas"))
        self.concurrent_label.setObjectName("settingsLabel")
        self.concurrent_desc = QLabel(self.tr("Número máximo de descargas que se procesarán en paralelo a la vez (1 a 10)."))
        self.concurrent_desc.setStyleSheet("color: #888888; font-size: 11px;")
        self.concurrent_vbox.addWidget(self.concurrent_label)
        self.concurrent_vbox.addWidget(self.concurrent_desc)
        
        self.concurrent_spin = QSpinBox()
        self.concurrent_spin.setRange(1, 10)
        self.concurrent_spin.setFixedWidth(70)
        self.concurrent_spin.setFixedHeight(28)
        self.concurrent_spin.setStyleSheet(f"""
            QSpinBox {{
                background-color: {get_theme_token('fondo_secundario', '#1e1e1e')};
                color: {get_theme_token('texto_principal', '#ffffff')};
                border: 1px solid {get_theme_token('borde', '#2d2d2d')};
                border-radius: 6px;
                padding: 2px 6px;
                font-weight: bold;
            }}
        """)
        self.concurrent_row.addLayout(self.concurrent_vbox)
        self.concurrent_row.addStretch()
        self.concurrent_row.addWidget(self.concurrent_spin)
        self.content_layout.addLayout(self.concurrent_row)

        # 6. Límite de velocidad (global: vale para todas las descargas de todas las
        # pestañas, ver DownloaderMaster._prepare_opts)
        self.speed_row = QHBoxLayout()
        self.speed_vbox = QVBoxLayout()
        self.speed_label = QLabel(self.tr("Límite de velocidad"))
        self.speed_label.setObjectName("settingsLabel")
        self.speed_desc = QLabel(self.tr(
            "Velocidad máxima de cada descarga. También se aplica a lo que ya está en cola."))
        self.speed_desc.setWordWrap(True)
        self.speed_desc.setStyleSheet("color: #888888; font-size: 11px;")
        self.speed_vbox.addWidget(self.speed_label)
        self.speed_vbox.addWidget(self.speed_desc)
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0.0, 999.0)
        self.speed_spin.setDecimals(1)
        self.speed_spin.setSingleStep(0.5)
        self.speed_spin.setSuffix(self.tr(" MB/s"))
        self.speed_spin.setSpecialValueText(self.tr("Sin límite"))
        # Sin keyboardTracking, escribir "12" no guarda 1 y después 12 por el camino.
        self.speed_spin.setKeyboardTracking(False)
        self.speed_spin.setFixedWidth(110)
        self.speed_spin.setFixedHeight(28)
        self.speed_spin.setStyleSheet(self.concurrent_spin.styleSheet().replace("QSpinBox", "QDoubleSpinBox"))
        self.speed_row.addLayout(self.speed_vbox, 1)
        self.speed_row.addWidget(self.speed_spin)
        self.content_layout.addLayout(self.speed_row)

        # 7. Switch: numerar los archivos de una playlist
        self.numbering_row = QHBoxLayout()
        self.numbering_vbox = QVBoxLayout()
        self.numbering_label = QLabel(self.tr("Numerar archivos de playlists"))
        self.numbering_label.setObjectName("settingsLabel")
        self.numbering_desc = QLabel(self.tr(
            "Antepone el número de orden al nombre de cada archivo de una playlist "
            "(ej. «001 - Título»). Las descargas sueltas nunca se numeran."))
        self.numbering_desc.setWordWrap(True)
        self.numbering_desc.setStyleSheet("color: #888888; font-size: 11px;")
        self.numbering_vbox.addWidget(self.numbering_label)
        self.numbering_vbox.addWidget(self.numbering_desc)
        self.numbering_switch = ToggleSwitch()
        self.numbering_row.addLayout(self.numbering_vbox, 1)
        self.numbering_row.addWidget(self.numbering_switch)
        self.content_layout.addLayout(self.numbering_row)

        self._build_history_section()

        # Finalizar setup del scroll area
        self.scroll_area.setWidget(self.scroll_content)
        self.main_layout.addWidget(self.scroll_area)

        # Configuración de colores del switch (basado en tema)
        self.update_switch_colors()

        # Connections
        self.metadata_switch.toggled.connect(self.on_embed_metadata_toggled)
        self.thumb_switch.toggled.connect(self.on_embed_thumbnail_toggled)
        self.sponsors_switch.toggled.connect(self.on_remove_sponsors_toggled)
        self.imp_switch.toggled.connect(self.on_impersonate_toggled)
        self.concurrent_spin.valueChanged.connect(self.on_concurrent_downloads_changed)
        self.speed_spin.valueChanged.connect(self.on_speed_limit_changed)
        self.numbering_switch.toggled.connect(self.on_playlist_numbering_toggled)
        self.history_switch.toggled.connect(self.on_history_enabled_toggled)
        self.history_limit_spin.valueChanged.connect(self.on_history_limit_changed)
        self.btn_clear_history.clicked.connect(self.on_clear_history_clicked)
        download_history().entries_changed.connect(self._update_history_usage)

    def _build_history_section(self):
        """Historial de descargas (panel del borde izquierdo de Modo Rápido y Proceso
        Avanzado, ver gui/widgets/history_panel.py)."""
        section = QLabel(self.tr("Historial de descargas"))
        section.setObjectName("settingsSectionTitle")
        self.content_layout.addWidget(section)

        # Switch: guardar historial
        row = QHBoxLayout()
        vbox = QVBoxLayout()
        label = QLabel(self.tr("Guardar historial"))
        label.setObjectName("settingsLabel")
        desc = QLabel(self.tr("Guarda lo que analizas o descargas en Modo Rápido y Proceso Avanzado."))
        desc.setStyleSheet("color: #888888; font-size: 11px;")
        vbox.addWidget(label)
        vbox.addWidget(desc)
        self.history_switch = ToggleSwitch()
        row.addLayout(vbox, 1)
        row.addWidget(self.history_switch)
        self.content_layout.addLayout(row)

        # SpinBox: máximo de entradas (0 = sin límite)
        row = QHBoxLayout()
        vbox = QVBoxLayout()
        label = QLabel(self.tr("Máximo de entradas"))
        label.setObjectName("settingsLabel")
        desc = QLabel(self.tr("Al superarlo se borran las más antiguas. 0 = sin límite."))
        desc.setStyleSheet("color: #888888; font-size: 11px;")
        vbox.addWidget(label)
        vbox.addWidget(desc)
        self.history_limit_spin = QSpinBox()
        self.history_limit_spin.setRange(0, 10_000_000)
        self.history_limit_spin.setSingleStep(100)
        self.history_limit_spin.setSpecialValueText(self.tr("Sin límite"))
        # Sin keyboardTracking, escribir "1000" no aplica 1, 10, 100... por el camino
        # (con un límite más bajo que lo guardado, cada paso pediría confirmar un borrado).
        self.history_limit_spin.setKeyboardTracking(False)
        self.history_limit_spin.setFixedWidth(110)
        self.history_limit_spin.setFixedHeight(28)
        self.history_limit_spin.setStyleSheet(self.concurrent_spin.styleSheet())
        row.addLayout(vbox, 1)
        row.addWidget(self.history_limit_spin)
        self.content_layout.addLayout(row)

        # Uso actual + borrar
        row = QHBoxLayout()
        self.history_usage_label = QLabel()
        self.history_usage_label.setStyleSheet("color: #888888; font-size: 11px;")
        self.btn_clear_history = QPushButton(self.tr("Borrar historial"))
        set_button_variant(self.btn_clear_history, "danger")
        row.addWidget(self.history_usage_label, 1)
        row.addWidget(self.btn_clear_history)
        self.content_layout.addLayout(row)

    def _update_history_usage(self):
        count = download_history().count()
        self.history_usage_label.setText(self.tr("{0} entradas guardadas").format(count))
        self.btn_clear_history.setEnabled(count > 0)

    def on_history_enabled_toggled(self, checked):
        if self._is_loading: return
        download_history().set_enabled(checked)
        logger.info(f"DownloadsPage: Guardar historial cambiado a: {checked}")

    def on_history_limit_changed(self, value):
        if self._is_loading: return
        history = download_history()
        over = history.entries_over_limit(value)
        if over > 0:
            answer = QMessageBox.question(
                self, self.tr("Reducir el historial"),
                self.tr("Con este límite se borrarán las {0} entradas más antiguas del historial. "
                        "No se puede deshacer.\n\n¿Continuar?").format(over))
            if answer != QMessageBox.Yes:
                self._is_loading = True
                self.history_limit_spin.setValue(history.max_entries())
                self._is_loading = False
                return
        history.set_max_entries(value)
        logger.info(f"DownloadsPage: Máximo de entradas del historial cambiado a: {value}")

    def on_clear_history_clicked(self):
        answer = QMessageBox.question(
            self, self.tr("Borrar historial"),
            self.tr("¿Borrar todo el historial de descargas?\n\nNo borra ningún archivo "
                    "descargado, solo las tarjetas del historial. No se puede deshacer."))
        if answer == QMessageBox.Yes:
            download_history().clear()

    def update_switch_colors(self):
        config = get_config()
        accent = "#B9E640" if config.get("theme") == "dark" else "#1DC038"
        self.metadata_switch.setTrackColors("#333333", accent)
        self.thumb_switch.setTrackColors("#333333", accent)
        self.sponsors_switch.setTrackColors("#333333", accent)
        self.imp_switch.setTrackColors("#333333", accent)
        self.numbering_switch.setTrackColors("#333333", accent)
        self.history_switch.setTrackColors("#333333", accent)

    def load_current_settings(self):
        config = get_config()
        self.metadata_switch.setChecked(config.get("embed_metadata", True))
        self.thumb_switch.setChecked(config.get("embed_thumbnail", True))
        self.sponsors_switch.setChecked(config.get("remove_sponsors", False))
        self.imp_switch.setChecked(config.get("use_impersonate", False))
        self.concurrent_spin.setValue(config.get("max_concurrent_downloads", 3))
        self.speed_spin.setValue(config.get("speed_limit_mbps", 0.0) or 0.0)
        self.numbering_switch.setChecked(config.get("playlist_numbering", True))
        self.history_switch.setChecked(config.get("history_enabled", True))
        self.history_limit_spin.setValue(config.get("history_max_entries", DEFAULT_MAX_ENTRIES))
        self._update_history_usage()

    def on_embed_metadata_toggled(self, checked):
        if self._is_loading: return
        config = get_config()
        config["embed_metadata"] = checked
        save_config(config)
        logger.info(f"DownloadsPage: Incrustar metadatos cambiado a: {checked}")

    def on_embed_thumbnail_toggled(self, checked):
        if self._is_loading: return
        config = get_config()
        config["embed_thumbnail"] = checked
        save_config(config)
        logger.info(f"DownloadsPage: Incrustar carátula cambiado a: {checked}")

    def on_remove_sponsors_toggled(self, checked):
        if self._is_loading: return
        config = get_config()
        config["remove_sponsors"] = checked
        save_config(config)
        logger.info(f"DownloadsPage: Eliminar sponsors cambiado a: {checked}")

    def on_impersonate_toggled(self, checked):
        if self._is_loading: return
        config = get_config()
        config["use_impersonate"] = checked
        save_config(config)
        logger.info(f"DownloadsPage: Uso de Impersonate cambiado a: {checked}")

    def on_speed_limit_changed(self, value):
        if self._is_loading: return
        config = get_config()
        config["speed_limit_mbps"] = value
        save_config(config)
        logger.info(f"DownloadsPage: Límite de velocidad cambiado a: {value} MB/s")

    def on_playlist_numbering_toggled(self, checked):
        if self._is_loading: return
        config = get_config()
        config["playlist_numbering"] = checked
        save_config(config)
        logger.info(f"DownloadsPage: Numerar archivos de playlists cambiado a: {checked}")

    def on_concurrent_downloads_changed(self, value):
        if self._is_loading: return
        config = get_config()
        config["max_concurrent_downloads"] = value
        save_config(config)
        logger.info(f"DownloadsPage: Descargas simultáneas cambiadas a: {value}")
        from core.utils.queue_manager import QueueManager
        qm = QueueManager.get_instance() if hasattr(QueueManager, "get_instance") else None
        if qm:
            qm.update_max_concurrent_downloads(value)

