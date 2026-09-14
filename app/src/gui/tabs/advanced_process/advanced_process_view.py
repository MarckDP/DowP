from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QCheckBox, QComboBox, QSizePolicy, QScrollArea
from PySide6.QtCore import QPropertyAnimation, QParallelAnimationGroup, QEasingCurve, Qt, QSize
from core.logger.logger_manager import logger
from core.utils.format_manager import FormatManager
import os
import time
import threading
from core.utils.cleanup_manager import CleanupManager
from core.utils.config_manager import get_config, save_config
from core.ytdlp_logic.analyzer import strip_ansi_codes


class _ScrollContentWidget(QWidget):
    """
    QScrollArea.setWidgetResizable(True) usa minimumSizeHint() del widget contenido
    como piso DURO para su ancho (vía qSmartMinSize interno de Qt) sin importar cuánto
    se achique la ventana - verificado que, sin este parche, video_details (que antes
    de vivir aquí adentro se comprimía sin problema muy por debajo de su propio
    minimumSizeHint) queda clavado en ~884px y el resto se desborda en vez de seguir
    achicándose con texto recortado, que es el comportamiento que tenía antes y se
    quiere conservar (ver conversación). Se fuerza el ancho del hint a 0 - el alto real
    se conserva intacto, así el cálculo de scroll vertical no se ve afectado.
    """
    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        return QSize(0, hint.height())

# Widgets
from gui.widgets.url_bar import URLBar
from gui.tabs.advanced_process.video_details import VideoDetailsWidget
from gui.tabs.advanced_process.video_details_components import RichComboBox, RichTextDelegate
from gui.widgets.combo_box import AutoPopupComboBox
from gui.tabs.advanced_process.subtitle_options import SubtitleOptionsWidget
from gui.tabs.advanced_process.recode_options import RecodeOptionsWidget
from gui.tabs.advanced_process.output_options import OutputOptionsWidget
from gui.widgets.queue_panel import QueuePanel
from gui.widgets.queue_trigger_bar import QueueTriggerBar

# Controllers and Workers
from gui.tabs.advanced_process.workers import AnalysisWorker, DownloadWorker
from gui.tabs.advanced_process.subtitle_controller import SubtitleController
from gui.tabs.advanced_process.recode_controller import RecodeController
from gui.tabs.advanced_process.playlist_controller import PlaylistController
from gui.tabs.advanced_process.download_controller import DownloadController

class AdvancedProcessTab(QWidget):
    def __init__(self):
        super().__init__()
        self.subtitle_controller = SubtitleController(self)
        self.recode_controller = RecodeController(self)
        self.playlist_controller = PlaylistController(self)
        self.init_ui()

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        self.main_layout.setSpacing(8)

        # Initialize Widgets
        self.url_bar = URLBar()
        self.video_details = VideoDetailsWidget()
        self.subtitle_options = SubtitleOptionsWidget()
        self.recode_options = RecodeOptionsWidget()
        self.output_options = OutputOptionsWidget()

        # New Collapsible Queue Components (agrupados sin separación entre panel y tirador)
        self.queue_panel = QueuePanel()
        self.queue_trigger = QueueTriggerBar()

        self.batch_queue_container = QWidget()
        self.batch_queue_container.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        batch_layout = QHBoxLayout(self.batch_queue_container)
        batch_layout.setContentsMargins(0, 0, 0, 0)
        batch_layout.setSpacing(0)
        batch_layout.addWidget(self.queue_panel)
        batch_layout.addWidget(self.queue_trigger)

        # Middle horizontal container for collapsing layout
        self.middle_container = QWidget()
        middle_layout = QHBoxLayout(self.middle_container)
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.setSpacing(8)
        
        # Middle content container: todo (detalles de video + tarjetas) va DENTRO del
        # mismo scroll (ver conversación) - así el panel de detalles también se corre
        # hacia arriba en vez de quedar fijo mientras solo las tarjetas hacen scroll.
        self.middle_content_container = QWidget()
        middle_content_layout = QVBoxLayout(self.middle_content_container)
        middle_content_layout.setContentsMargins(0, 0, 0, 0)
        middle_content_layout.setSpacing(0)

        self.lower_scroll_area = QScrollArea()
        self.lower_scroll_area.setObjectName("advancedProcessLowerScrollArea")
        self.lower_scroll_area.setWidgetResizable(True)
        self.lower_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.lower_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.lower_scroll_area.setFrameShape(QFrame.NoFrame)

        self.lower_scroll_content = _ScrollContentWidget()
        self.lower_scroll_content.setObjectName("advancedProcessLowerScrollContent")
        self.lower_scroll_layout = QVBoxLayout(self.lower_scroll_content)
        self.lower_scroll_layout.setContentsMargins(0, 0, 4, 0)
        self.lower_scroll_layout.setSpacing(8)

        # 1. Panel de detalles de video (altura fija, solo se expande horizontalmente)
        self.lower_scroll_layout.addWidget(self.video_details)

        # 2. Fila con las tarjetas de opciones (Subtítulos + Recodificar)
        cards_row = QHBoxLayout()
        cards_row.setContentsMargins(0, 0, 0, 0)
        cards_row.setSpacing(8)

        # OJO: layout.setAlignment(Qt.AlignTop) alinea el LAYOUT dentro de su padre, no
        # cada item dentro del layout - con dos tarjetas de alto variable (colapsable),
        # sin esto Qt las centra verticalmente una respecto de la otra en vez de pegarlas
        # arriba. El alineamiento por-widget (2do argumento de addWidget) es lo que
        # realmente lo resuelve.
        #
        # Stretch 1 en ambas (no 0 + addStretch al final): con ancho MÍNIMO en vez de
        # FIJO (ver subtitle_options.py/recode_options.py), esto reparte el espacio
        # sobrante 50/50 entre las dos en vez de dejarlas ancladas a la izquierda con
        # hueco muerto a la derecha - así toda la fila se estira con la ventana.
        cards_row.addWidget(self.subtitle_options, 1, Qt.AlignTop)
        cards_row.addWidget(self.recode_options, 1, Qt.AlignTop)
        self.lower_scroll_layout.addLayout(cards_row)
        self.lower_scroll_layout.addStretch(1)

        self.lower_scroll_area.setWidget(self.lower_scroll_content)
        middle_content_layout.addWidget(self.lower_scroll_area, 1)

        # Assemble middle container
        middle_layout.addWidget(self.batch_queue_container)
        middle_layout.addWidget(self.middle_content_container, 1)

        # Add to main vertical layout
        self.main_layout.addWidget(self.url_bar)
        self.analysis_options_bar = self._build_analysis_options_bar()
        self.main_layout.addWidget(self.analysis_options_bar)
        self.main_layout.addWidget(self.middle_container)
        self.main_layout.addWidget(self.output_options)

        # Connections
        self.url_bar.analyze_requested.connect(self.start_analysis)
        self.url_bar.solo_toggled.connect(self._on_solo_toggled)
        self.queue_trigger.clicked.connect(self.toggle_queue_panel)

        # Inicializar y conectar etiquetas
        self.video_details.load_labels()
        self.video_details.combo_tags.currentIndexChanged.connect(self._on_label_changed)

        # Botón circular sobre la miniatura → abre el diálogo de fragmentos
        self.video_details.thumb_container.clicked_cut.connect(
            lambda: self.video_details.open_fragments_dialog()
        )
        self.video_details.fragments_changed.connect(self.subtitle_controller.on_fragments_changed)
        
        # Subtítulos: actualizar formatos cuando cambia el idioma
        self.subtitle_options.combo_subtitle_language.currentIndexChanged.connect(
            self.subtitle_controller.on_subtitle_language_changed
        )
        
        self.subtitle_options.combo_subtitle_language.currentIndexChanged.connect(
            self.subtitle_controller.on_subtitle_selection_changed
        )
        self.subtitle_options.combo_subtitle_format.currentIndexChanged.connect(
            self.subtitle_controller.on_subtitle_selection_changed
        )
        self.subtitle_options.btn_download_subtitles.clicked.connect(self.subtitle_controller.start_subtitle_download)
        
        # Sincronizar el switch de recorte con la lista de formatos
        self.subtitle_options.chk_cut_to_fragment["switch"].toggled.connect(
            self.subtitle_controller.on_subtitle_language_changed
        )
        
        # Iniciar Descarga o Cancelar
        self.output_options.btn_start_download.clicked.connect(self._on_download_button_clicked)
        self.output_options.btn_open_output_path.clicked.disconnect()
        self.output_options.btn_open_output_path.clicked.connect(self._on_open_output_path_clicked)

        # Botón de arrastre del resultado (solo modo SOLO, ver _on_solo_toggled): las
        # rutas se piden en el momento del arrastre, nunca antes.
        self.output_options.set_output_drag_files_provider(
            lambda: self.download_controller.collect_solo_drag_files()
        )
        self.output_options.output_drag_clicked.connect(
            lambda: self.download_controller.reveal_solo_outputs()
        )
        
        self._current_video_data = None

        # Conectar al gestor de colas global
        from core.utils.queue_manager import get_queue_manager
        self.queue_mgr = get_queue_manager()
        self.queue_mgr.job_removed.connect(self._on_job_removed)
        self._active_job_id = None
        
        self._selected_job_id = None
        self._batch_workers = {}

        # Inicializar el controlador de descargas
        from gui.tabs.advanced_process.download_controller import DownloadController
        self.download_controller = DownloadController(self)

        # Inicializar Gestor de Barra de Tareas (Windows/macOS)
        self.taskbar_manager = None
        
        # Conexiones de la cola de lotes
        self.queue_panel.card_clicked_signal.connect(self._on_card_selected)
        self.queue_panel.queue_action_signal.connect(self._on_queue_panel_action)
        self.queue_panel.configure_playlist_signal.connect(self.playlist_controller.configure_specific_playlist)

        # Aplicar estado inicial de modo SOLO
        self._on_solo_toggled(self.url_bar.solo_btn.isChecked())

    def _build_analysis_options_bar(self):
        bar = QFrame()
        bar.setObjectName("analysisOptionsBar")
        from gui.styles import get_theme_token
        borde_color = get_theme_token('borde_normal', '#2d2d2d')
        fondo_color = get_theme_token('fondo_secundario', '#1e1e1e')
        bar.setStyleSheet(f"""
            QFrame#analysisOptionsBar {{
                background-color: {fondo_color};
                border: 1px solid {borde_color};
                border-radius: 6px;
            }}
        """)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(15, 6, 15, 6)
        layout.setSpacing(12)

        config = get_config()
        analyze_pl_val = config.get("analyze_playlist", True)
        fast_mode_val = config.get("fast_mode", True)

        self.chk_playlist_analysis = QCheckBox(self.tr("Playlist"))
        self.chk_playlist_analysis.setChecked(analyze_pl_val)
        self.chk_playlist_analysis.setToolTip(self.tr("Si se activa y pegas una playlist, permite encolar múltiples medios a la vez."))
        layout.addWidget(self.chk_playlist_analysis)

        self.chk_fast_mode = QCheckBox(self.tr("Modo rápido"))
        self.chk_fast_mode.setChecked(fast_mode_val if analyze_pl_val else False)
        self.chk_fast_mode.setEnabled(analyze_pl_val)
        self.chk_fast_mode.setToolTip(self.tr("Habilita un análisis ultrarrápido que añade todos los elementos de golpe (puede no mostrar info completa al instante)."))
        layout.addWidget(self.chk_fast_mode)

        # Divisor vertical
        self.divider = QFrame()
        self.divider.setFixedWidth(1)
        self.divider.setStyleSheet(f"background-color: {borde_color}; border: none; border-radius: 0px;")
        layout.addWidget(self.divider)

        # Opciones de miniatura
        self.lbl_thumbnails = QLabel(self.tr("Miniaturas:"))
        self.lbl_thumbnails.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.lbl_thumbnails)

        batch_thumb_mode = config.get("batch_thumbnail_mode", "manual")

        self.chk_thumb_manual = QCheckBox(self.tr("Manual"))
        self.chk_thumb_manual.setChecked(batch_thumb_mode == "manual")
        self.chk_thumb_manual.setToolTip(self.tr("Decidir configuración de miniatura manualmente en cada ítem."))
        layout.addWidget(self.chk_thumb_manual)

        self.chk_thumb_media = QCheckBox(self.tr("Con medio"))
        self.chk_thumb_media.setChecked(batch_thumb_mode == "with_media")
        self.chk_thumb_media.setToolTip(self.tr("Descargar la miniatura junto con cada medio por defecto."))
        layout.addWidget(self.chk_thumb_media)

        self.chk_thumb_only = QCheckBox(self.tr("Solo miniatura"))
        self.chk_thumb_only.setChecked(batch_thumb_mode == "thumbnail_only")
        self.chk_thumb_only.setToolTip(self.tr("Descargar EXCLUSIVAMENTE la miniatura de cada medio (ignora audio/video)."))
        layout.addWidget(self.chk_thumb_only)

        # Divisor vertical para separar de las opciones globales
        self.global_divider = QFrame()
        self.global_divider.setFixedWidth(1)
        self.global_divider.setStyleSheet(f"background-color: {borde_color}; border: none; border-radius: 0px;")
        layout.addWidget(self.global_divider)

        # Opciones globales de calidad/modo
        self.lbl_global = QLabel(self.tr("Global:"))
        self.lbl_global.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.lbl_global)

        self.combo_global_mode = AutoPopupComboBox()
        self.combo_global_mode.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.combo_global_mode.addItem(self.tr("Manual"), "manual")
        self.combo_global_mode.addItem(self.tr("Video + Audio"), "video+audio")
        self.combo_global_mode.addItem(self.tr("Solo Audio"), "audio_only")
        self.combo_global_mode.addItem(self.tr("Solo Video"), "video_only")
        self.combo_global_mode.setToolTip(self.tr("Modo global por defecto para nuevos ítems."))
        layout.addWidget(self.combo_global_mode)

        self.combo_global_quality = RichComboBox()
        self.combo_global_quality.setItemDelegate(RichTextDelegate(self.combo_global_quality))
        self.combo_global_quality.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.combo_global_quality.setToolTip(self.tr("Calidad o resolución máxima global para nuevos ítems."))
        layout.addWidget(self.combo_global_quality)

        layout.addStretch(1)

        # Connections
        self.chk_playlist_analysis.toggled.connect(self._on_playlist_analysis_toggled)
        self.chk_fast_mode.toggled.connect(self._on_fast_mode_toggled)
        
        self.chk_thumb_manual.toggled.connect(self._on_thumb_manual_toggled)
        self.chk_thumb_media.toggled.connect(self._on_thumb_media_toggled)
        self.chk_thumb_only.toggled.connect(self._on_thumb_only_toggled)

        # Inicializar combos globales desde configuración
        g_mode = config.get("global_download_mode", "manual")
        g_quality = config.get("global_download_quality", "manual")

        idx_mode = self.combo_global_mode.findData(g_mode)
        if idx_mode >= 0:
            self.combo_global_mode.setCurrentIndex(idx_mode)
        else:
            self.combo_global_mode.setCurrentIndex(0)
            
        self._update_global_quality_list(g_mode)
        
        idx_quality = self.combo_global_quality.findData(g_quality)
        if idx_quality >= 0:
            self.combo_global_quality.setCurrentIndex(idx_quality)
        else:
            self.combo_global_quality.setCurrentIndex(0)

        self.combo_global_mode.currentIndexChanged.connect(self._on_global_mode_changed)
        self.combo_global_quality.currentIndexChanged.connect(self._on_global_quality_changed)

        return bar

    def _on_label_changed(self, index):
        """Maneja el cambio de selección en el combobox de etiquetas."""
        self.video_details.update_combo_style()
        if index <= 0:
            # Ninguna etiqueta seleccionada
            self.output_options.output_path_input.setEnabled(True)
            self.output_options.btn_select_output_path.setEnabled(True)
        else:
            # Etiqueta seleccionada: actualizar ruta y bloquear edición
            path = self.video_details.combo_tags.currentData()
            if path:
                self.output_options.output_path_input.setText(path)
            self.output_options.output_path_input.setEnabled(False)
            self.output_options.btn_select_output_path.setEnabled(False)

    def _on_playlist_analysis_toggled(self, checked):
        self.chk_fast_mode.setEnabled(checked)
        config = get_config()
        config["analyze_playlist"] = checked
        if checked:
            saved_fast = config.get("fast_mode", True)
            self.chk_fast_mode.setChecked(saved_fast)
        else:
            self.chk_fast_mode.setChecked(False)
        save_config(config)

    def _on_fast_mode_toggled(self, checked):
        if self.chk_playlist_analysis.isChecked():
            config = get_config()
            config["fast_mode"] = checked
            save_config(config)

    def _on_thumb_manual_toggled(self, checked):
        if not checked:
            self._keep_one_toggle_active(self.chk_thumb_manual)
            return
        self._set_toggles_state(manual=True, media=False, only=False)
        self._on_batch_thumbnail_mode_changed("manual")

    def _on_thumb_media_toggled(self, checked):
        if not checked:
            self._keep_one_toggle_active(self.chk_thumb_media)
            return
        self._set_toggles_state(manual=False, media=True, only=False)
        self._on_batch_thumbnail_mode_changed("with_media")

    def _on_thumb_only_toggled(self, checked):
        if not checked:
            self._keep_one_toggle_active(self.chk_thumb_only)
            return
        self._set_toggles_state(manual=False, media=False, only=True)
        self._on_batch_thumbnail_mode_changed("thumbnail_only")

    def _keep_one_toggle_active(self, active_toggle):
        active_toggle.blockSignals(True)
        active_toggle.setChecked(True)
        active_toggle.blockSignals(False)

    def _set_toggles_state(self, manual, media, only):
        self.chk_thumb_manual.blockSignals(True)
        self.chk_thumb_manual.setChecked(manual)
        self.chk_thumb_manual.blockSignals(False)

        self.chk_thumb_media.blockSignals(True)
        self.chk_thumb_media.setChecked(media)
        self.chk_thumb_media.blockSignals(False)

        self.chk_thumb_only.blockSignals(True)
        self.chk_thumb_only.setChecked(only)
        self.chk_thumb_only.blockSignals(False)

    def _on_batch_thumbnail_mode_changed(self, mode_str):
        config = get_config()
        config["batch_thumbnail_mode"] = mode_str
        save_config(config)

        # 1. Actualizar el estado de bloqueo en la UI
        self._update_ui_for_batch_thumbnail_mode(mode_str)

        # 2. Si hay un job seleccionado, actualizar su config/request_data y forzar guardado
        if self._selected_job_id:
            job = self.queue_mgr.get_job(self._selected_job_id)
            if job:
                self._save_current_job_options()

    def _update_ui_for_batch_thumbnail_mode(self, mode):
        is_thumb_only = (mode == "thumbnail_only")
        
        # En modo SOLO ignoramos las restricciones de lote
        if self.url_bar.solo_btn.isChecked():
            is_thumb_only = False
            self.video_details.chk_download_with_video.setEnabled(True)
            return

        # Ajustar el interruptor del inspector
        if mode in ("with_media", "thumbnail_only"):
            self.video_details.chk_download_with_video.setEnabled(False)
        else:
            self.video_details.chk_download_with_video.setEnabled(True)

        # Deshabilitar/Habilitar selectores en el inspector si es solo miniatura
        is_playlist = False
        if self._selected_job_id:
            job = self.queue_mgr.get_job(self._selected_job_id)
            if job and job.job_type == "PLAYLIST":
                is_playlist = True

        if not is_playlist:
            self.video_details.mode_selector.setEnabled(not is_thumb_only)
            self.video_details.combo_video.setEnabled(not is_thumb_only)
            self.video_details.combo_audio.setEnabled(not is_thumb_only)

    def _update_global_quality_list(self, mode):
        self.combo_global_quality.blockSignals(True)
        self.combo_global_quality.clear()
        
        if mode == "manual":
            self.combo_global_quality.addItem(self.tr("Manual"), "manual")
            self.combo_global_quality.setEnabled(False)
        elif mode in ("video+audio", "video_only"):
            self.combo_global_quality.addItem(self.tr("Mejor compatible") + " ✨", "Mejor compatible")
            self.combo_global_quality.addItem(self.tr("Máxima calidad"), "Máxima calidad")
            self.combo_global_quality.addItem("4K (2160p)", "4K (2160p)")
            self.combo_global_quality.addItem("2K (1440p)", "2K (1440p)")
            self.combo_global_quality.addItem("1080p", "1080p")
            self.combo_global_quality.addItem("720p", "720p")
            self.combo_global_quality.addItem("480p", "480p")
            self.combo_global_quality.addItem("360p", "360p")
            self.combo_global_quality.setEnabled(True)
        else: # audio_only
            self.combo_global_quality.addItem(self.tr("Mejor compatible") + " ✨", "Mejor compatible")
            self.combo_global_quality.addItem(self.tr("Alta"), "Alta")
            self.combo_global_quality.addItem(self.tr("Media"), "Media")
            self.combo_global_quality.addItem(self.tr("Baja"), "Baja")
            self.combo_global_quality.setEnabled(True)
        self.combo_global_quality.blockSignals(False)

    def _on_global_mode_changed(self, index):
        mode_str = self.combo_global_mode.itemData(index) or "manual"
        
        config = get_config()
        config["global_download_mode"] = mode_str
        save_config(config)
        
        self._update_global_quality_list(mode_str)
        
        raw_quality = self.combo_global_quality.itemData(self.combo_global_quality.currentIndex()) or "manual"
        
        config = get_config()
        config["global_download_quality"] = raw_quality
        save_config(config)
        
        self._apply_global_settings_to_queue()

    def _on_global_quality_changed(self, index):
        if index < 0:
            return
        raw_quality = self.combo_global_quality.itemData(index) or "manual"
        
        config = get_config()
        config["global_download_quality"] = raw_quality
        save_config(config)
        
        self._apply_global_settings_to_queue()



    def _resolve_formats_for_quality(self, video_data, mode, quality_str):
        cached_key = '_cached_formats'
        if cached_key not in video_data:
            video_data[cached_key] = FormatManager.parse_formats(video_data)
        video_streams, audio_streams, _ = video_data[cached_key]
        
        v_data = None
        a_data = None
        
        has_video_streams = len(video_streams) > 0 and not (len(video_streams) == 1 and video_streams[0].get('id') == 'default' and not video_streams[0].get('has_video'))
        has_audio_streams = len(audio_streams) > 0 or (len(video_streams) > 0 and any(v.get('has_audio') for v in video_streams))
        
        actual_mode = mode
        if actual_mode in ("video+audio", "video_only") and not has_video_streams:
            actual_mode = "audio_only"
        elif actual_mode == "audio_only" and not has_audio_streams:
            actual_mode = "video_only" if has_video_streams else "video+audio"
            
        config = get_config()
        adobe_compat = config.get("adobe_compat_default", True)
        
        q_str = quality_str.strip().lower()

        if actual_mode in ("video+audio", "video_only") and video_streams:
            if q_str in ("mejor compatible", "best compatible"):
                if adobe_compat:
                    for stream in video_streams:
                        if "✨" in stream.get('label', ''):
                            v_data = stream
                            break
                if not v_data:
                    v_data = video_streams[0]
            elif q_str in (self.tr("máxima calidad"), "maxima calidad", "maximum quality"):
                v_data = video_streams[0]
            else:
                height_map = {
                    "4k (2160p)": 2160,
                    "2k (1440p)": 1440,
                    "1080p": 1080,
                    "720p": 720,
                    "480p": 480,
                    "360p": 360
                }
                target_height = height_map.get(q_str, 1080)
                
                for stream in video_streams:
                    s_height = stream.get('height') or 0
                    if s_height <= target_height:
                        v_data = stream
                        break
                if not v_data:
                    v_data = video_streams[-1]
            
            if actual_mode == "video+audio":
                if v_data.get('is_multi') and v_data.get('internal_audios'):
                    a_data = v_data['internal_audios'][0]
                elif audio_streams:
                    a_data = self._resolve_audio_stream(audio_streams, quality_str)
                    
        elif actual_mode == "audio_only" and audio_streams:
            a_data = self._resolve_audio_stream(audio_streams, quality_str)
            
        return actual_mode, v_data, a_data

    def _resolve_audio_stream(self, audio_streams, quality_str):
        if not audio_streams:
            return None
            
        config = get_config()
        adobe_compat = config.get("adobe_compat_default", True)
        
        q_str = quality_str.strip().lower()
            
        if q_str in ("mejor compatible", "best compatible"):
            if adobe_compat:
                for stream in audio_streams:
                    if "✨" in stream.get('label', ''):
                        return stream
            return audio_streams[0]
        elif q_str in (self.tr("máxima calidad"), "maxima calidad", "maximum quality"):
            return audio_streams[0]
            
        bitrate_map = {
            "alta": 256,
            "media": 128,
            "baja": 64
        }
        target_tbr = bitrate_map.get(q_str, 128)
        
        for stream in audio_streams:
            s_tbr = stream.get('tbr') or 0
            if s_tbr <= target_tbr:
                return stream
                
        return audio_streams[-1]

    def _apply_global_settings_to_queue(self):
        mode_str = self.combo_global_mode.currentData() or "manual"
        if mode_str == "manual":
            return
        
        raw_quality = self.combo_global_quality.currentData() or "manual"
        
        jobs = self.queue_mgr.get_all_jobs()
        modified_any = False
        
        for job in jobs:
            if job.job_type == "PLAYLIST":
                continue
                
            v_data = job.video_data if job.video_data else job.analysis_data
            if not v_data:
                continue
                
            actual_mode, v_stream, a_stream = self._resolve_formats_for_quality(v_data, mode_str, raw_quality)
            
            req = job.request_data if job.request_data else job.config
            if not req:
                continue
                
            req = req.copy()
            req["mode"] = actual_mode
            req["video_format_id"] = v_stream.get("id") if v_stream else None
            req["video_ext"] = v_stream.get("ext") if v_stream else None
            req["video_is_combined"] = v_stream.get("is_combined", False) if v_stream else False
            req["video_is_multi"] = v_stream.get("is_multi", False) if v_stream else False
            
            req["audio_format_id"] = a_stream.get("id") if a_stream else None
            req["audio_ext"] = a_stream.get("ext") if a_stream else None
            req["audio_has_video"] = a_stream.get("has_video", False) if a_stream else False
            
            self.queue_mgr.update_job_data(job.job_id, request_data=req)
            modified_any = True
            
        if modified_any:
            if self._selected_job_id:
                curr_job = self.queue_mgr.get_job(self._selected_job_id)
                if curr_job and curr_job.job_type != "PLAYLIST" and curr_job.request_data:
                    self.video_details.combo_video.blockSignals(True)
                    self.video_details.combo_audio.blockSignals(True)
                    try:
                        self._restore_request_data_to_ui(curr_job.request_data)
                    finally:
                        self.video_details.combo_video.blockSignals(False)
                        self.video_details.combo_audio.blockSignals(False)
                        self.video_details._on_video_changed(self.video_details.combo_video.currentIndex())

    def _clear_ui_completely(self):
        """Limpia todos los campos de información del medio de la UI."""
        self._current_video_data = None
        self.video_details.reset_ui()
        self.subtitle_controller.clear_subtitles()
        self.recode_controller.reset_to_defaults()
        self.url_bar.url_input.clear()
        self.output_options.set_download_state("idle")
        self.output_options.btn_start_download.setEnabled(False)
        self.output_options.set_progress(0, self.tr("En espera"), "wait")

    def _on_solo_toggled(self, checked):
        logger.info(f"AdvancedProcessTab: Modo SOLO (Individual) {'activado' if checked else 'desactivado'}")
        
        # Guardar en la configuración de la app
        config = get_config()
        config["solo_mode"] = checked
        save_config(config)
        
        # 1. Al activar SOLO (checked = True)
        if checked:
            # Solo trabajos de ESTA pestaña (DOWNLOAD/PLAYLIST) - el QueueManager es
            # compartido con Herramientas Multimedia (jobs "RECODE"), asi que
            # clear_queue() (vacia TODO sin importar el tipo) borraria/cancelaria
            # recodificaciones ajenas con solo tocar este toggle (ver conversación).
            jobs = [j for j in self.queue_mgr.get_all_jobs() if j.job_type in ("DOWNLOAD", "PLAYLIST")]
            if jobs:
                from gui.dialogs.dialogs import show_warning_confirm
                confirm = show_warning_confirm(
                    self,
                    self.tr("Confirmar cambio a Modo Individual"),
                    self.tr("Al cambiar a Modo Individual se eliminarán todos los trabajos de la cola de descargas.\n\n¿Deseas continuar?")
                )
                if not confirm:
                    # Cancelar cambio de estado en el botón
                    self.url_bar.solo_btn.blockSignals(True)
                    self.url_bar.solo_btn.setChecked(False)
                    self.url_bar.solo_btn.blockSignals(False)
                    return
                else:
                    # Confirmado: solo estos jobs (no clear_queue(), que se llevaria por
                    # delante recodificaciones de la otra pestaña)
                    for j in jobs:
                        self.queue_mgr.remove_job(j.job_id)
                    self._clear_ui_completely()
            else:
                self._clear_ui_completely()
        else:
            # Al desactivar SOLO (checked = False)
            self._clear_ui_completely()

        # Combo de política de conflicto: visible solo en modo LOTES (oculto en SOLO,
        # donde en su lugar se pregunta con un diálogo modal por archivo).
        self.output_options.set_conflict_policy_visible(not checked, animated=True)

        # Botón de arrastre del resultado: al revés, solo en SOLO. En LOTES cada tarjeta
        # de la cola se arrastra sola (ver queue_panel.py::_on_card_file_drag), así que
        # un botón único no sabría a cuál de todas se refiere.
        self.output_options.set_output_drag_visible(checked)
        self.output_options.set_output_drag_enabled(False)

        # Detener animaciones previas si están corriendo
        if hasattr(self, "_toggle_anim_group") and self._toggle_anim_group.state() == QParallelAnimationGroup.State.Running:
            self._toggle_anim_group.stop()

        self._toggle_anim_group = QParallelAnimationGroup(self)

        if checked:
            # --- ANIMAR OCULTACIÓN (Modo SOLO Activado) ---
            anim_options = QPropertyAnimation(self.analysis_options_bar, b"maximumHeight")
            anim_options.setDuration(220)
            anim_options.setStartValue(self.analysis_options_bar.height() if self.analysis_options_bar.height() > 0 else 45)
            anim_options.setEndValue(0)
            anim_options.setEasingCurve(QEasingCurve.Type.OutQuad)
            self._toggle_anim_group.addAnimation(anim_options)

            anim_trigger_min = QPropertyAnimation(self.queue_trigger, b"minimumWidth")
            anim_trigger_min.setDuration(220)
            anim_trigger_min.setStartValue(self.queue_trigger.width())
            anim_trigger_min.setEndValue(0)
            anim_trigger_min.setEasingCurve(QEasingCurve.Type.OutQuad)
            self._toggle_anim_group.addAnimation(anim_trigger_min)

            anim_trigger_max = QPropertyAnimation(self.queue_trigger, b"maximumWidth")
            anim_trigger_max.setDuration(220)
            anim_trigger_max.setStartValue(self.queue_trigger.width())
            anim_trigger_max.setEndValue(0)
            anim_trigger_max.setEasingCurve(QEasingCurve.Type.OutQuad)
            self._toggle_anim_group.addAnimation(anim_trigger_max)

            anim_panel_min = QPropertyAnimation(self.queue_panel, b"minimumWidth")
            anim_panel_min.setDuration(220)
            anim_panel_min.setStartValue(self.queue_panel.width())
            anim_panel_min.setEndValue(0)
            anim_panel_min.setEasingCurve(QEasingCurve.Type.OutQuad)
            self._toggle_anim_group.addAnimation(anim_panel_min)

            anim_panel_max = QPropertyAnimation(self.queue_panel, b"maximumWidth")
            anim_panel_max.setDuration(220)
            anim_panel_max.setStartValue(self.queue_panel.width())
            anim_panel_max.setEndValue(0)
            anim_panel_max.setEasingCurve(QEasingCurve.Type.OutQuad)
            self._toggle_anim_group.addAnimation(anim_panel_max)

            def on_hide_finished():
                self.queue_panel.is_expanded = False
                self.queue_panel.hide()
                self.queue_trigger.hide()
                self.analysis_options_bar.hide()
                self.queue_panel.setMaximumWidth(16777215)
                self.queue_trigger.setMaximumWidth(16777215)
                self.analysis_options_bar.setMaximumHeight(16777215)
                self.queue_panel.setMinimumWidth(0)
                self.queue_trigger.setMinimumWidth(0)

            self._toggle_anim_group.finished.connect(on_hide_finished)
            self._toggle_anim_group.start()
        else:
            # --- ANIMAR APARICIÓN (Modo SOLO Desactivado) ---
            self.analysis_options_bar.setMaximumHeight(0)
            self.queue_trigger.setMinimumWidth(0)
            self.queue_trigger.setMaximumWidth(0)

            self.queue_trigger.show()
            self.analysis_options_bar.show()

            if self.queue_panel.is_expanded:
                self.queue_panel.setMinimumWidth(0)
                self.queue_panel.setMaximumWidth(0)
                self.queue_panel.show()
            else:
                self.queue_panel.hide()

            anim_options = QPropertyAnimation(self.analysis_options_bar, b"maximumHeight")
            anim_options.setDuration(220)
            anim_options.setStartValue(0)
            anim_options.setEndValue(45)
            anim_options.setEasingCurve(QEasingCurve.Type.OutQuad)
            self._toggle_anim_group.addAnimation(anim_options)

            anim_trigger_min = QPropertyAnimation(self.queue_trigger, b"minimumWidth")
            anim_trigger_min.setDuration(220)
            anim_trigger_min.setStartValue(0)
            anim_trigger_min.setEndValue(24)
            anim_trigger_min.setEasingCurve(QEasingCurve.Type.OutQuad)
            self._toggle_anim_group.addAnimation(anim_trigger_min)

            anim_trigger_max = QPropertyAnimation(self.queue_trigger, b"maximumWidth")
            anim_trigger_max.setDuration(220)
            anim_trigger_max.setStartValue(0)
            anim_trigger_max.setEndValue(24)
            anim_trigger_max.setEasingCurve(QEasingCurve.Type.OutQuad)
            self._toggle_anim_group.addAnimation(anim_trigger_max)

            if self.queue_panel.is_expanded:
                panel_target = int(self.width() * 0.3)
                anim_panel_min = QPropertyAnimation(self.queue_panel, b"minimumWidth")
                anim_panel_min.setDuration(220)
                anim_panel_min.setStartValue(0)
                anim_panel_min.setEndValue(panel_target)
                anim_panel_min.setEasingCurve(QEasingCurve.Type.OutQuad)
                self._toggle_anim_group.addAnimation(anim_panel_min)

                anim_panel_max = QPropertyAnimation(self.queue_panel, b"maximumWidth")
                anim_panel_max.setDuration(220)
                anim_panel_max.setStartValue(0)
                anim_panel_max.setEndValue(panel_target)
                anim_panel_max.setEasingCurve(QEasingCurve.Type.OutQuad)
                self._toggle_anim_group.addAnimation(anim_panel_max)

            def on_show_finished():
                self.queue_panel.setMaximumWidth(16777215)
                self.queue_trigger.setMaximumWidth(16777215)
                self.analysis_options_bar.setMaximumHeight(16777215)
                self.queue_trigger.setFixedWidth(24)
                if self.queue_panel.is_expanded:
                    self.queue_panel.setFixedWidth(int(self.width() * 0.3))
                    self.queue_panel.show()
                else:
                    self.queue_panel.setFixedWidth(0)
                    self.queue_panel.hide()
                self.queue_panel.adjust_width(self.width())

            self._toggle_anim_group.finished.connect(on_show_finished)
            self._toggle_anim_group.start()
        
        # Actualizar visibilidad/habilitación del inspector según el modo SOLO
        self._update_ui_for_batch_thumbnail_mode(get_config().get("batch_thumbnail_mode", "manual"))
        
    def showEvent(self, event):
        super().showEvent(event)
        # Inicializamos el gestor en el showEvent para asegurar que window() sea válido.
        # El progreso de LOTES ya lo maneja update_queue_main_progress() en
        # download_controller.py (única fuente de verdad para el taskbar ahí);
        # SOLO lo maneja on_solo_progress() en el mismo archivo.
        if not self.taskbar_manager:
            from core.utils.taskbar_progress import TaskbarProgressManager
            try:
                hwnd = int(self.window().winId())
                self.taskbar_manager = TaskbarProgressManager(hwnd)
                logger.info(f"AdvancedProcessTab: TaskbarProgressManager vinculado a HWND {hwnd}")
            except Exception as e:
                logger.error(f"AdvancedProcessTab: No se pudo inicializar TaskbarProgressManager: {e}")

        # Iniciar tutorial si no se ha visto
        from core.utils.config_manager import get_config, save_config
        from PySide6.QtCore import QTimer
        config = get_config()
        if not config.get("tutorial_advanced_process_seen", False):
            config["tutorial_advanced_process_seen"] = True
            save_config(config)
            # Asegurarse de empezar en modo SOLO
            if not self.url_bar.solo_btn.isChecked():
                self.url_bar.solo_btn.setChecked(True)
            QTimer.singleShot(500, self.start_tutorial_solo)

    def toggle_queue_panel(self):
        self.queue_panel.toggle_expanded(self.width())
        self.queue_trigger.set_expanded(self.queue_panel.is_expanded)
        
    def resizeEvent(self, event):
        self.queue_panel.adjust_width(self.width())
        super().resizeEvent(event)

    def start_analysis(self, url):
        logger.info(f"AdvancedProcessTab: Empezando análisis para {url}")
        
        # --- MODO SOLO ACTIVO ---
        if self.url_bar.solo_btn.isChecked():
            self.video_details.reset_ui()
            self.subtitle_controller.clear_subtitles()
            self.output_options.btn_start_download.setEnabled(False)
            self.video_details.title_input.setText(self.tr("Analizando URL..."))
            self.output_options.set_progress(0, self.tr("Analizando URL..."), "running")
            
            # Forzar análisis de un único medio
            worker = AnalysisWorker(url, analyze_playlist=False, fast_mode=False)
            self._batch_workers["solo"] = worker

            def on_progress(current, total):
                percent = (current / total) * 100.0 if total > 0 else 0.0
                status_str = self.tr("Analizando {} de {}...").format(current, total)
                self.video_details.title_input.setText(status_str)
                self.output_options.set_progress(0, status_str, "running")

            worker.progress.connect(on_progress)
            
            def handler(data, error):
                if error:
                    logger.error(f"AdvancedProcessTab: Error de análisis: {error}")
                    self.video_details.title_input.setText(str(error))
                    self.video_details.title_input.setCursorPosition(0)
                    self.output_options.btn_start_download.setEnabled(False)
                    self.output_options.set_progress(0, self.tr("Error en el análisis"), "error")
                else:
                    title = data.get('title', "Video")
                    self._current_video_data = data
                    
                    self.video_details.combo_video.blockSignals(True)
                    self.video_details.combo_audio.blockSignals(True)
                    self.subtitle_options.combo_subtitle_language.blockSignals(True)
                    self.subtitle_options.combo_subtitle_format.blockSignals(True)
                    try:
                        self.video_details.selected_fragments = []
                        self.video_details.fragment_mode = None
                        self.video_details.thumb_container.set_cut_status("normal")
                        self.video_details.fragments_changed.emit()
                        
                        self.video_details.mode_selector.btn_video_audio.setEnabled(True)
                        self.video_details.mode_selector.btn_audio.setEnabled(True)
                        self.video_details.mode_selector.btn_video.setEnabled(True)
                        
                        self.video_details.update_info(data)
                        cached_key = '_cached_formats'
                        if cached_key not in data:
                            data[cached_key] = FormatManager.parse_formats(data)
                        video_streams, audio_streams, has_audio = data[cached_key]
                        
                        self.video_details.populate_menus(video_streams, audio_streams, has_audio)
                        self.subtitle_controller.populate_subtitles(data)
                        self.output_options.btn_start_download.setEnabled(True)
                    finally:
                        self.video_details.combo_video.blockSignals(False)
                        self.video_details.combo_audio.blockSignals(False)
                        self.subtitle_options.combo_subtitle_language.blockSignals(False)
                        self.subtitle_options.combo_subtitle_format.blockSignals(False)
                        self.video_details._on_video_changed(self.video_details.combo_video.currentIndex())
                    self.output_options.set_progress(0, self.tr("En espera"), "wait")
                self._batch_workers.pop("solo", None)

            worker.finished.connect(handler)
            worker.start()
            return

        # --- MODO COLA ACTIVO ---
        self.url_bar.url_input.clear()
        job_id = self.queue_mgr.add_job({"url": url, "title": "Analizando URL..."}, "DOWNLOAD")
        job = self.queue_mgr.get_job(job_id)
        if job:
            self.queue_mgr.update_job_status(job_id, "ANALYZING")
        
        jobs = self.queue_mgr.get_all_jobs()
        if len(jobs) > 1 and not self.queue_panel.is_expanded:
            self.toggle_queue_panel()
        elif len(jobs) == 1:
            self.video_details.reset_ui()
            self.subtitle_controller.clear_subtitles()
            self.output_options.btn_start_download.setEnabled(False)
            self.video_details.title_input.setText(self.tr("Analizando URL..."))
        
        analyze_playlist = self.chk_playlist_analysis.isChecked()
        fast_mode = self.chk_fast_mode.isChecked() if analyze_playlist else False
        worker = AnalysisWorker(url, analyze_playlist=analyze_playlist, fast_mode=fast_mode)
        self._batch_workers[job_id] = worker

        def on_progress(current, total):
            job = self.queue_mgr.get_job(job_id)
            if job and job.status == "ANALYZING":
                percent = (current / total) * 100.0 if total > 0 else 0.0
                status_str = self.tr("Analizando {} de {}...").format(current, total)
                job.progress = percent
                self.queue_mgr.job_progress_changed.emit(job_id, percent, status_str, "")
                if job_id == self._selected_job_id or len(self.queue_mgr.get_all_jobs()) == 1:
                    self.video_details.title_input.setText(status_str)

        worker.progress.connect(on_progress)
        
        def create_handler(j_id):
            def handler(data, error):
                if error:
                    j = self.queue_mgr.get_job(j_id)
                    if j: j.error_message = error
                    self.queue_mgr.update_job_status(j_id, "FAILED")
                    
                    if j_id == self._selected_job_id or len(self.queue_mgr.get_all_jobs()) == 1:
                        logger.error(f"AdvancedProcessTab: Error de análisis: {error}")
                        self.video_details.title_input.setText(str(error))
                        self.video_details.title_input.setCursorPosition(0)
                        self.output_options.btn_start_download.setEnabled(False)

                    if j_id == self._selected_job_id or self._selected_job_id is None or len(self.queue_mgr.get_all_jobs()) == 1:
                        self._on_card_selected(j_id)
                else:
                    if self.playlist_controller.is_playlist_result(data):
                        if worker.fast_mode:
                            self.playlist_controller.handle_playlist_analysis_result(j_id, data)
                        else:
                            self.playlist_controller.unpack_slow_playlist_result(j_id, data)
                        self._batch_workers.pop(j_id, None)
                        return

                    title = data.get('title', "Video")
                    j = self.queue_mgr.get_job(j_id)
                    if j:
                        j.title = title
                        j.config["title"] = title
                        if not j.request_data:
                            j.request_data = self._build_default_request_data(data, title)
                    self.queue_mgr.update_job_data(j_id, video_data=data)
                    self.queue_mgr.update_job_status(j_id, "PENDING")
                    
                    if j_id == self._selected_job_id or len(self.queue_mgr.get_all_jobs()) == 1:
                        logger.info(f"AdvancedProcessTab: Análisis finalizado con éxito")
                        self.output_options.btn_start_download.setEnabled(True)

                    if j_id == self._selected_job_id or self._selected_job_id is None or len(self.queue_mgr.get_all_jobs()) == 1:
                        self._on_card_selected(j_id)
                self._batch_workers.pop(j_id, None)
            return handler
            
        worker.finished.connect(create_handler(job_id))
        worker.start()

    def _save_current_job_options(self):
        """Guarda la configuración actual de la UI en el trabajo en inspección."""
        if not self._selected_job_id:
            return
        job = self.queue_mgr.get_job(self._selected_job_id)
        if not job:
            return

        if job.job_type == "PLAYLIST":
            # Los jobs de playlist no usan request_data (van por job.config), pero
            # el título sí es editable aquí y es lo que _execute_playlist usa como
            # nombre de la carpeta de destino — hay que guardarlo igual, si no
            # queda descartado al cambiar de tarjeta.
            new_title = self.video_details.title_input.text().strip()
            if new_title and new_title != job.title:
                job.title = new_title
                job.config["title"] = new_title
                card = self.queue_panel.cards.get(job.job_id)
                if card:
                    card.update_title(new_title)

            # Recodificación: una sola config para TODA la playlist (no hay
            # request_data por hijo aquí, ver comentario arriba) - misma tarjeta que
            # una descarga individual, pero lo que junta se guarda en job.config.
            job.config.update(self.recode_controller.collect_recode_data())
            return

        req_data = self._collect_request_data()
        if req_data:
            self.queue_mgr.update_job_data(self._selected_job_id, request_data=req_data)

    def _resolve_formats_manually(self, video_data):
        cached_key = '_cached_formats'
        if cached_key not in video_data:
            video_data[cached_key] = FormatManager.parse_formats(video_data)
        video_streams, audio_streams, _ = video_data[cached_key]
        
        config = get_config()
        adobe_compat = config.get("adobe_compat_default", True)
        
        v_data = None
        if video_streams:
            if adobe_compat:
                for stream in video_streams:
                    if "✨" in stream.get('label', ''):
                        v_data = stream
                        break
            if not v_data:
                v_data = video_streams[0]
                
        a_data = None
        if audio_streams:
            orig_l = (video_data.get('language') or "").lower().strip()
            
            found_p1 = False
            if orig_l:
                for stream in audio_streams:
                    lang_s = (stream.get('lang') or "").lower().strip()
                    if lang_s == orig_l and "✨" in stream.get('label', ''):
                        a_data = stream
                        found_p1 = True
                        break
            
            if not found_p1 and orig_l:
                for stream in audio_streams:
                    lang_s = (stream.get('lang') or "").lower().strip()
                    if lang_s == orig_l:
                        a_data = stream
                        found_p1 = True
                        break
            
            if not found_p1 and adobe_compat:
                for stream in audio_streams:
                    if "✨" in stream.get('label', ''):
                        a_data = stream
                        found_p1 = True
                        break
                        
            if not a_data:
                a_data = audio_streams[0]
                
        has_video_streams = len(video_streams) > 0 and not (len(video_streams) == 1 and video_streams[0].get('id') == 'default' and not video_streams[0].get('has_video'))
        has_audio_streams = len(audio_streams) > 0 or (len(video_streams) > 0 and any(v.get('has_audio') for v in video_streams))
        
        batch_thumb_mode = config.get("batch_thumbnail_mode", "manual")
        default_mode = "video+audio"
        if batch_thumb_mode == "thumbnail_only" and not self.url_bar.solo_btn.isChecked():
            default_mode = "thumbnail_only"
            
        if default_mode in ("video+audio", "video_only") and not has_video_streams:
            default_mode = "audio_only"
        elif default_mode == "audio_only" and not has_audio_streams:
            default_mode = "video_only" if has_video_streams else "video+audio"
            
        return default_mode, v_data, a_data

    def _build_default_request_data(self, video_data: dict, title: str = "") -> dict:
        """Crea un snapshot base para un job sin copiar opciones de otro item."""
        cached_key = '_cached_formats'
        if cached_key not in video_data:
            video_data[cached_key] = FormatManager.parse_formats(video_data)
        
        config = get_config()
        g_mode = config.get("global_download_mode", "manual")
        g_quality = config.get("global_download_quality", "manual")
        
        if self.url_bar.solo_btn.isChecked() or g_mode == "manual":
            resolved_mode, v_data, a_data = self._resolve_formats_manually(video_data)
        else:
            resolved_mode, v_data, a_data = self._resolve_formats_for_quality(video_data, g_mode, g_quality)
        
        batch_thumb_mode = config.get("batch_thumbnail_mode", "manual")
        if batch_thumb_mode == "thumbnail_only" and not self.url_bar.solo_btn.isChecked():
            resolved_mode = "thumbnail_only"
            
        clean_title = title or video_data.get("title") or self.tr("Descarga de medios")

        return {
            "url": video_data.get("original_url", video_data.get("webpage_url")),
            "title": clean_title,
            "mode": resolved_mode,
            "video_format_id": v_data.get("id") if v_data else None,
            "video_lang": v_data.get("lang") if v_data else None,
            "video_is_combined": v_data.get("is_combined", False) if v_data else False,
            "video_is_multi": v_data.get("is_multi", False) if v_data else False,
            "audio_format_id": a_data.get("id") if a_data else None,
            "audio_lang": a_data.get("lang") if a_data else None,
            "audio_has_video": a_data.get("has_video", False) if a_data else False,
            "audio_source_id": "none",
            "force_audio_extract": False,
            "output_path": self.output_options.output_path_input.text(),
            "conflict_policy": "ask" if self.url_bar.solo_btn.isChecked() else self.output_options.conflict_policy_combo.currentData(),
            "label": self.video_details.combo_tags.currentText() if self.video_details.combo_tags.currentIndex() > 0 else None,
            "speed_limit": f"{int(self.output_options.speed_limit_input.value() * 1024)}K" if self.output_options.speed_limit_input.value() > 0 else None,
            "download_thumbnail_file": False,
            "subtitle_lang": None,
            "subtitle_is_auto": False,
            "subtitle_format": None,
            "subtitle_output_ext": None,
            "embed_subtitles": False,
            "standardize_srt": False,
            "cut_subtitles": False,
            "selected_fragments": [],
            "fragment_mode": None,
            "video_ext": v_data.get("ext") if v_data else None,
            "audio_ext": a_data.get("ext") if a_data else None,
            "embed_metadata": get_config().get("embed_metadata", True),
            "embed_thumbnail": get_config().get("embed_thumbnail", True),
            "remove_sponsors": get_config().get("remove_sponsors", False),
            "is_playlist": video_data.get("is_playlist", False),
            "recode_enabled": False,
            "recode_preset_name": None,
            "recode_keep_original": True,
            "recode_filename_prefix": "",
            "recode_filename_suffix": "_recoded",
        }

    def _on_card_selected(self, job_id):
        """El usuario hizo clic en una tarjeta de la cola, mostrar sus datos en el inspector."""
        job = self.queue_mgr.get_job(job_id)
        if not job or not job.video_data:
            return
            
        logger.info(f"AdvancedProcessTab: Cambiando vista al trabajo {job_id} ({job.title})")
        
        # Guardar cambios del anterior
        self._save_current_job_options()
        
        # Cambiar al nuevo
        self._selected_job_id = job_id
        self.queue_panel.select_card(job_id)

        if job.job_type == "PLAYLIST":
            self.playlist_controller.show_playlist_job(job)
            return
        
        # Bloquear señales de los combos durante la repoblación completa
        self.video_details.combo_video.blockSignals(True)
        self.video_details.combo_audio.blockSignals(True)
        self.subtitle_options.combo_subtitle_language.blockSignals(True)
        self.subtitle_options.combo_subtitle_format.blockSignals(True)
        
        try:
            # Resetear estado de fragmentos para no heredar del trabajo anterior
            self.video_details.selected_fragments = []
            self.video_details.fragment_mode = None
            self.video_details.thumb_container.set_cut_status("normal")
            
            # Ocultar botón de corte si es un item de playlist
            is_playlist_item = (job.config.get("playlist_index") is not None)
            self.video_details.thumb_container.set_cut_button_visible(not is_playlist_item)
            
            self.video_details.fragments_changed.emit()
            
            # Re-habilitar ModeSelector
            self.video_details.mode_selector.btn_video_audio.setEnabled(True)
            self.video_details.mode_selector.btn_audio.setEnabled(True)
            self.video_details.mode_selector.btn_video.setEnabled(True)
            
            # Cargar datos crudos en la interfaz
            data = job.video_data
            self.video_details.update_info(data)
            
            # Usar formatos cacheados si existen
            cached_key = '_cached_formats'
            if cached_key not in data:
                data[cached_key] = FormatManager.parse_formats(data)
            video_streams, audio_streams, has_audio = data[cached_key]
            
            self.video_details.populate_menus(video_streams, audio_streams, has_audio)
            self._current_video_data = data
            self.subtitle_controller.populate_subtitles(data)
            self.output_options.btn_start_download.setEnabled(True)
            
            # Restaurar la configuración que el usuario había guardado para este trabajo
            if job.request_data:
                self._restore_request_data_to_ui(job.request_data)
        finally:
            # Desbloquear señales y disparar un único update
            self.video_details.combo_video.blockSignals(False)
            self.video_details.combo_audio.blockSignals(False)
            self.subtitle_options.combo_subtitle_language.blockSignals(False)
            self.subtitle_options.combo_subtitle_format.blockSignals(False)
            # Disparar el ajuste de audio basado en el video seleccionado
            self.video_details._on_video_changed(self.video_details.combo_video.currentIndex())

    def _on_job_removed(self, job_id):
        """Limpia la UI si el trabajo eliminado es el que estaba seleccionado."""
        if job_id == self._selected_job_id:
            self._selected_job_id = None
            self._current_video_data = None
            self.video_details.reset_ui()
            self.subtitle_controller.clear_subtitles()
            self.recode_controller.reset_to_defaults()
            self.url_bar.url_input.clear()
            self.output_options.btn_start_download.setEnabled(False)
            self.output_options.set_progress(0, "", "wait")

    def _restore_request_data_to_ui(self, req: dict):
        if not req:
            return
            
        if req.get("title"):
            self.video_details.title_input.setText(req["title"])
            
        if "selected_fragments" in req:
            self.video_details.selected_fragments = req["selected_fragments"]
            if "fragment_mode" in req:
                self.video_details.fragment_mode = req["fragment_mode"]
            
            if self.video_details.selected_fragments:
                self.video_details.thumb_container.set_cut_status("saved")
            else:
                self.video_details.thumb_container.set_cut_status("normal")
                
            self.video_details.fragments_changed.emit()
            
        mode = req.get("mode")
        if mode == "audio_only":
            self.video_details.mode_selector.set_mode(self.tr("Solo Audio"))
        elif mode == "video_only":
            self.video_details.mode_selector.set_mode(self.tr("Solo Video"))
        elif mode:
            self.video_details.mode_selector.set_mode(self.tr("Video + Audio"))
            
        # Restaurar "Extraer de" antes que los combos de formato
        audio_src_id = req.get("audio_source_id", "none")
        for i in range(self.video_details.combo_audio_source.count()):
            d = self.video_details.combo_audio_source.itemData(i)
            if d and d.get("id") == audio_src_id:
                self.video_details.combo_audio_source.blockSignals(True)
                self.video_details.combo_audio_source.setCurrentIndex(i)
                self.video_details.combo_audio_source.blockSignals(False)
                self.video_details._on_audio_source_changed(i)
                break

        v_id = req.get("video_format_id")
        if v_id:
            for i in range(self.video_details.combo_video.count()):
                d = self.video_details.combo_video.itemData(i)
                if d and d.get("id") == v_id:
                    self.video_details.combo_video.setCurrentIndex(i)
                    break
                    
        a_id = req.get("audio_format_id")
        if a_id:
            for i in range(self.video_details.combo_audio.count()):
                d = self.video_details.combo_audio.itemData(i)
                if d and d.get("id") == a_id:
                    self.video_details.combo_audio.setCurrentIndex(i)
                    break
                    
        self.subtitle_controller.restore_subtitles_to_ui(req)
        self.recode_controller.restore_recode_to_ui(req)

        # Restaurar etiqueta
        label = req.get("label")
        self.video_details.combo_tags.blockSignals(True)
        if label:
            idx = self.video_details.combo_tags.findText(label)
            if idx >= 0:
                self.video_details.combo_tags.setCurrentIndex(idx)
            else:
                self.video_details.combo_tags.setCurrentIndex(0)
                # Si la etiqueta ya no existe en el sistema (fue eliminada en Ajustes)
                # mantenemos la ruta que tenía ese ítem y removemos la etiqueta
                req["label"] = None
        else:
            self.video_details.combo_tags.setCurrentIndex(0)
        self.video_details.combo_tags.blockSignals(False)

        # Restaurar ruta de salida propia del item
        out_path = req.get("output_path")
        if out_path:
            self.output_options.output_path_input.setText(out_path)

        # Forzar actualización del estado de bloqueo de la ruta
        self._on_label_changed(self.video_details.combo_tags.currentIndex())

        # Restaurar opción de miniatura
        batch_thumb_mode = get_config().get("batch_thumbnail_mode", "manual")
        self.video_details.chk_download_with_video.blockSignals(True)
        self.video_details.chk_download_with_video.setChecked(req.get("download_thumbnail_file", False))
        self.video_details.chk_download_with_video.blockSignals(False)
        
        if batch_thumb_mode in ("with_media", "thumbnail_only"):
            self.video_details.chk_download_with_video.setEnabled(False)
        else: # manual
            self.video_details.chk_download_with_video.setEnabled(True)

        self._update_ui_for_batch_thumbnail_mode(batch_thumb_mode)

    def _collect_request_data(self) -> dict:
        """Recolecta los datos de descarga seleccionados actualmente en la interfaz."""
        if not self._current_video_data:
            return None

        # 1. Recolectar formatos seleccionados
        v_data = self.video_details.combo_video.currentData()
        a_data = self.video_details.combo_audio.currentData()
        
        # 2. Identificar el modo (Video+Audio, etc)
        mode_text = self.video_details.mode_selector.current_mode()
        if mode_text == self.tr("Solo Audio"):
            mode = "audio_only"
        elif mode_text == self.tr("Solo Video"):
            mode = "video_only"
        else:
            mode = "video+audio"

        batch_thumb_mode = get_config().get("batch_thumbnail_mode", "manual")
        if batch_thumb_mode == "thumbnail_only" and not self.url_bar.solo_btn.isChecked():
            mode = "thumbnail_only"

        title = self.video_details.title_input.text().strip()
        if not title:
            title = self.tr("Descarga de medios")

        # Recolectar datos del origen de audio (combo_audio_source) en Solo Audio
        audio_source_id = "none"
        force_audio_extract = False
        if mode == "audio_only":
            src_data = self.video_details.combo_audio_source.currentData()
            if src_data:
                audio_source_id = src_data.get('id', 'none')
                if audio_source_id != 'none':
                    force_audio_extract = True

        # 3. Preparar solicitud
        request_data = {
            "url": self._current_video_data.get("original_url", self._current_video_data.get("webpage_url")),
            "title": title, 
            "mode": mode,
            "video_format_id": v_data.get("id") if v_data else None,
            "video_lang": v_data.get("lang") if v_data else None,
            "video_is_combined": v_data.get("is_combined", False) if v_data else False,
            "video_is_multi": v_data.get("is_multi", False) if v_data else False,
            "audio_format_id": a_data.get("id") if a_data else None,
            "audio_lang": a_data.get("lang") if a_data else None,
            "audio_has_video": a_data.get("has_video", False) if a_data else False,
            "audio_source_id": audio_source_id,
            "force_audio_extract": force_audio_extract,
            "output_path": self.output_options.output_path_input.text(),
            "conflict_policy": "ask" if self.url_bar.solo_btn.isChecked() else self.output_options.conflict_policy_combo.currentData(),
            "label": self.video_details.combo_tags.currentText() if self.video_details.combo_tags.currentIndex() > 0 else None,
            "speed_limit": f"{int(self.output_options.speed_limit_input.value() * 1024)}K" if self.output_options.speed_limit_input.value() > 0 else None,
            "download_thumbnail_file": self.video_details.chk_download_with_video.isChecked(),
            "selected_fragments": self.video_details.selected_fragments,
            "fragment_mode": self.video_details.fragment_mode,
            "video_ext": v_data.get("ext") if v_data else None,
            "audio_ext": a_data.get("ext") if a_data else None,
            "embed_metadata": get_config().get("embed_metadata", True),
            "embed_thumbnail": get_config().get("embed_thumbnail", True),
            "remove_sponsors": get_config().get("remove_sponsors", False),
            "is_playlist": self._current_video_data.get("is_playlist", False)
        }

        request_data.update(self.subtitle_controller.collect_subtitle_data())
        request_data.update(self.recode_controller.collect_recode_data())
        return request_data

    def _on_download_button_clicked(self):
        self.download_controller.on_download_button_clicked()

    def _on_open_output_path_clicked(self):
        self.download_controller.on_open_output_path_clicked()

    def _on_queue_panel_action(self, action):
        self.download_controller.on_queue_panel_action(action)

    @property
    def _is_downloading(self):
        return self.download_controller.is_downloading

    @_is_downloading.setter
    def _is_downloading(self, value):
        self.download_controller.is_downloading = value

    @property
    def _solo_worker(self):
        return self.download_controller.solo_worker

    @_solo_worker.setter
    def _solo_worker(self, value):
        self.download_controller.solo_worker = value

    @property
    def _solo_request_data(self):
        return self.download_controller.solo_request_data

    @_solo_request_data.setter
    def _solo_request_data(self, value):
        self.download_controller.solo_request_data = value

    @property
    def _cancellation_event(self):
        return self.download_controller.cancellation_event

    @_cancellation_event.setter
    def _cancellation_event(self, value):
        self.download_controller.cancellation_event = value

    @property
    def _paused_job_ids(self):
        return self.download_controller.paused_job_ids

    @_paused_job_ids.setter
    def _paused_job_ids(self, value):
        self.download_controller.paused_job_ids = value
        
    @property
    def _last_downloaded_filepath(self):
        return self.download_controller.last_downloaded_filepath

    @_last_downloaded_filepath.setter
    def _last_downloaded_filepath(self, value):
        self.download_controller.last_downloaded_filepath = value

    def start_tutorial_solo(self):
        from gui.widgets.tutorial_overlay import TutorialOverlay
        from PySide6.QtCore import QTimer
        
        # Simular animación de SOLO a LOTES y vuelta
        def animate_solo():
            self.url_bar.solo_btn.setChecked(False)
            QTimer.singleShot(800, lambda: self.url_bar.solo_btn.setChecked(True))
            
        steps = [
            {
                "title": self.tr("Modo SOLO y LOTES"),
                "desc": self.tr("Este botón intercala entre los dos modos de la pestaña: SOLO (individual) y por LOTES. Empezaremos explorando el Modo SOLO."),
                "widgets": [self.url_bar.solo_btn],
                "on_enter": animate_solo
            },
            {
                "title": self.tr("URL y Analizar"),
                "desc": self.tr("La URL se pega igual que en el Modo Rápido, pero la gran diferencia es que aquí la URL primero se analiza para extraer toda su información antes de descargar."),
                "widgets": [self.url_bar]
            },
            {
                "title": self.tr("Vista Previa y Editor"),
                "desc": self.tr("Aquí verás la miniatura del medio. Puedes guardarla directamente o usar 'Enviar a E.I' para mandarla a la pestaña Editor de Imagen y procesarla de distintas formas."),
                "widgets": [self.video_details.thumb_container]
            },
            {
                "title": self.tr("Título y Etiquetas"),
                "desc": self.tr("Puedes cambiar manualmente el título final del medio y usar las Etiquetas para asignar rutas preconfiguradas rápidamente."),
                "widgets": [self.video_details.title_input, self.video_details.combo_tags]
            },
            {
                "title": self.tr("Pistas, Modos y Calidades"),
                "desc": self.tr("¡Control total! Aquí puedes elegir con precisión quirúrgica las pistas de video, audio e idiomas disponibles del medio."),
                "widgets": [self.video_details.mode_selector, self.video_details.video_container, self.video_details.audio_container]
            },
            {
                "title": self.tr("Subtítulos"),
                "desc": self.tr("Si el video tiene subtítulos, aparecerán aquí. Puedes descargarlos solos, incrustados con el video, o usar opciones extra como estandarizar a SRT o recortarlos."),
                "widgets": [self.subtitle_options],
                "on_enter": lambda: self.subtitle_options.set_expanded(True)
            },
            {
                "title": self.tr("Recodificar"),
                "desc": self.tr("Permite post-procesar el medio descargado (cambiar formato, códec, etc.) usando presets que configures en la pestaña Herramientas Multimedia."),
                "widgets": [self.recode_options],
                "on_enter": lambda: self.recode_options.set_expanded(True)
            },
            {
                "title": self.tr("Opciones de Salida y Arrastre"),
                "desc": self.tr("Aparte de la ruta, al finalizar una descarga se iluminará el Botón de Arrastre (icono de la mano). Te permite arrastrar el archivo directamente desde DowP a tu editor de video o carpeta."),
                "widgets": [self.output_options],
                "on_leave": lambda: QTimer.singleShot(200, self._transition_to_batch_tutorial)
            }
        ]
        
        main_window = self.window()
        self.tutorial_overlay = TutorialOverlay(main_window, steps)
        self.tutorial_overlay.resize(main_window.size())
        self.tutorial_overlay.show()

    def _transition_to_batch_tutorial(self):
        from PySide6.QtCore import QTimer
        # Cambiar a modo Lotes
        self.url_bar.solo_btn.setChecked(False)
        if not self.queue_panel.is_expanded:
            self.toggle_queue_panel()
        QTimer.singleShot(600, self.start_tutorial_batch)

    def start_tutorial_batch(self):
        from gui.widgets.tutorial_overlay import TutorialOverlay
        steps = [
            {
                "title": self.tr("Lista de Lotes"),
                "desc": self.tr("¡Bienvenido al modo LOTES! Aquí puedes encolar múltiples URLs. Puedes reordenarlas, arrastrar los archivos terminados o restaurar ítems para volver a descargarlos."),
                "widgets": [self.queue_panel]
            },
            {
                "title": self.tr("Playlist y Modo Rápido"),
                "desc": self.tr("Activar ambas despliega la ventana de Playlist para elegir qué medios encolar. Si solo activas 'Playlist', el análisis extraerá TODOS los videos de golpe (útil pero lento en listas grandes)."),
                "widgets": [self.chk_playlist_analysis, self.chk_fast_mode]
            },
            {
                "title": self.tr("Miniaturas Globales"),
                "desc": self.tr("Controla las miniaturas de toda la cola: decidir 'Manual' ítem por ítem, 'Con medio' para bajarlas todas, o 'Solo miniatura'."),
                "widgets": [self.chk_thumb_manual, self.chk_thumb_media, self.chk_thumb_only]
            },
            {
                "title": self.tr("Ajuste Global"),
                "desc": self.tr("Permite forzar una calidad o formato aproximado para todos los ítems de la lista a la vez."),
                "widgets": [self.combo_global_mode, self.combo_global_quality]
            },
            {
                "title": self.tr("Si Existe (Opciones de Salida)"),
                "desc": self.tr("En las opciones de salida de lotes encontrarás el menú 'Si existe', ideal para decidir qué hacer automáticamente si te topas con archivos duplicados."),
                "widgets": [self.output_options.conflict_policy_combo]
            }
        ]
        main_window = self.window()
        self.tutorial_overlay = TutorialOverlay(main_window, steps)
        self.tutorial_overlay.resize(main_window.size())
        self.tutorial_overlay.show()

