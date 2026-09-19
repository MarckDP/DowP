# src/gui/tabs/editing_media/editing_media_view.py
import os
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeView,
    QListView,
    QHeaderView,
    QStackedWidget,
    QFrame,
    QLineEdit,
    QPushButton,
    QSlider,
    QScrollArea,
    QApplication,
    QAbstractItemView,
    QToolButton,
    QMenu,
    QSizePolicy,
)

from PySide6.QtCore import Qt, QSize, QEvent, QPoint, QTimer
from PySide6.QtGui import QIcon, QPixmap

# Importar QtMultimedia de forma segura para reproducción de audio
try:
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
    MULTIMEDIA_AVAILABLE = True
except ImportError:
    MULTIMEDIA_AVAILABLE = False

from core.logger.logger_manager import logger
from core.utils.paths import get_src_dir
from gui.styles import (
    get_theme_token,
    generate_tinted_svg,
    apply_player_play_button_style,
    apply_player_loop_button_style,
    apply_edit_subclip_button_style,
    apply_folder_open_button_style,
    apply_download_action_button_style,
)
from gui.widgets.animated_button import AnimatedButton
from gui.widgets.send_state_button import SendButtonState
from core.tabs.editing_media.editing_media_logic import EditingMediaController

# Importar los widgets que fueron extraídos a sus propios archivos
from gui.tabs.editing_media.waveform_widget import AudioWaveformWidget
from gui.tabs.editing_media.preview_panel import PreviewContainerWidget
from gui.widgets.volume_control import VolumeControlWidget
from gui.widgets.combo_box import AutoPopupComboBox
from gui.tabs.editing_media.editing_media_icons import (
    get_colored_svg_icon,
    get_colored_folder_icon,
    get_svg_icon,
    get_folder_icon,
)

# Importar Mixins que dividen la lógica
from gui.tabs.editing_media.editing_media_tree import TreeListMixin
from gui.tabs.editing_media.editing_media_playback import PlaybackMixin
from gui.tabs.editing_media.editing_media_freesound import FreesoundMixin
from gui.tabs.editing_media.editing_media_icons import LoadingSpinnerWidget
from gui.tabs.editing_media.media_model import MediaTableModel
from core.tabs.editing_media.thumbnail_cache_manager import ThumbnailCacheManager
from core.utils.config_manager import get_config, save_config

class _DragCleanupMixin:
    """Tras un QDrag nativo hacia otra aplicación (Premiere/AE/DaVinci/Explorador), Qt no
    siempre entrega un evento Leave al viewport porque el SO tomó el control del mouse durante
    el arrastre. Sin ese evento el estado ':hover' del stylesheet queda "pegado" indefinidamente.
    Forzamos un Leave sintético + repintado apenas termina el exec() nativo para restaurarlo.

    También evita que Qt extienda la selección al arrastrar el mouse sobre varios ítems: la
    multi-selección solo debe producirse con Ctrl/Shift + clic (comportamiento por defecto de
    mousePressEvent/mouseReleaseEvent, que dejamos intacto). Arrastrar desde un ítem únicamente
    debe iniciar un drag-and-drop, nunca ir seleccionando lo que el cursor va sobrevolando."""

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            if hasattr(self, "_press_pos") and not getattr(self, "_is_starting_drag", False):
                delta = event.pos() - self._press_pos
                if delta.manhattanLength() >= QApplication.startDragDistance():
                    index = self.indexAt(self._press_pos)
                    if index.isValid():
                        self.startDrag(self.model().supportedDragActions())
            # IMPORTANTE: Nunca llamar a super().mouseMoveEvent() con el botón izquierdo presionado.
            # En QAbstractItemView con ExtendedSelection, super().mouseMoveEvent() causa que Qt
            # seleccione todos los ítems sobre los que se arrastra el puntero del mouse.
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if hasattr(self, "_press_pos"):
            del self._press_pos
        super().mouseReleaseEvent(event)

    def startDrag(self, supportedActions):
        if getattr(self, "_is_starting_drag", False):
            return
        self._is_starting_drag = True
        try:
            model = self.model()
            if model and hasattr(self, "selectedIndexes"):
                indexes = self.selectedIndexes()
                for idx in indexes:
                    if hasattr(model, "get_item"):
                        item = model.get_item(idx)
                        if item and item.get("es_remoto"):
                            dest = item.get("dest_path")
                            if not dest or not os.path.exists(dest):
                                w = self.parentWidget()
                                while w and not hasattr(w, "ensure_hq_download_blocking"):
                                    w = w.parentWidget()
                                if w and hasattr(w, "ensure_hq_download_blocking"):
                                    w.ensure_hq_download_blocking(item)
            super().startDrag(supportedActions)
            QApplication.sendEvent(self.viewport(), QEvent(QEvent.Leave))
            self.viewport().update()
        finally:
            self._is_starting_drag = False


class _MediaTreeView(_DragCleanupMixin, QTreeView):
    def scrollTo(self, index, hint=QAbstractItemView.EnsureVisible):
        """Vista de columnas anchas con scroll horizontal AsNeeded (ver
        editing_media_view.py::init_ui) -- el scrollTo() por defecto de Qt, que
        setCurrentIndex() dispara solo en un simple clic (SelectRows selecciona toda la
        fila, pero el "current index" es la celda exacta bajo el cursor), reencuadra
        TAMBIÉN horizontalmente para que esa celda quede completa a la vista. Con
        columnas que no entran todas en el ancho disponible, eso empuja el scroll
        horizontal solo, sin que el usuario lo haya pedido. Se preserva el valor
        horizontal y se deja intacto el vertical (ese sí hace falta, ej. al navegar
        con flechas del teclado a una fila fuera de vista)."""
        hbar = self.horizontalScrollBar()
        old_value = hbar.value()
        super().scrollTo(index, hint)
        hbar.setValue(old_value)


class _MediaListView(_DragCleanupMixin, QListView):
    pass


class EditingMediaTab(FreesoundMixin, PlaybackMixin, TreeListMixin, QWidget):
    """Pestaña 'Medios de Edición' con una distribución visual de tres paneles de 20/40/40."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        
        # Inicializar el controlador
        self.controller = EditingMediaController(self)
        
        self.selected_tree_item_data = None
        self.active_filter = "Todos"
        
        # Restaurar preferencias persistentes de vista
        cfg = get_config()
        self.view_mode = cfg.get("editing_media_view_mode", "grid")
        self._saved_icon_size = cfg.get("editing_media_icon_size", 112)
        
        self.sort_by = "nombre"
        self.sort_ascending = True
        self._metadata_cache = {}
        self.waveform_thread = None
        self._icon_cache = {}
        
        # Conectar señal del cargador de miniaturas y metadatos en segundo plano
        ThumbnailCacheManager.get_instance().thumbnail_loaded.connect(self._on_thumbnail_loaded)
        from core.tabs.editing_media.ffprobe_metadata_manager import FFprobeMetadataManager
        FFprobeMetadataManager.get_instance().metadata_ready.connect(self._on_async_metadata_ready)
        
        # Temporizador de retardo (debounce) para búsquedas locales (250ms)
        from PySide6.QtCore import QTimer
        self.local_search_timer = QTimer(self)
        self.local_search_timer.setSingleShot(True)
        self.local_search_timer.setInterval(250)
        self.local_search_timer.timeout.connect(self._on_local_search_timer_timeout)

        # Temporizador de retardo (debounce) para persistir tamaño de cuadrícula (500ms)
        self._icon_size_save_timer = QTimer(self)
        self._icon_size_save_timer.setSingleShot(True)
        self._icon_size_save_timer.setInterval(500)
        self._icon_size_save_timer.timeout.connect(self._save_icon_size_to_config)

        # Temporizador de retardo (debounce) para persistir tamaños del splitter (500ms)
        self._splitter_save_timer = QTimer(self)
        self._splitter_save_timer.setSingleShot(True)
        self._splitter_save_timer.setInterval(500)
        self._splitter_save_timer.timeout.connect(self._save_splitter_sizes_to_config)

        # Inicializar orígenes de medios web (Freesound, Wikimedia, ...) y timer de
        # debouncing de búsqueda. self.web_providers es un dict ordenado: el orden de
        # inserción define el orden en que aparecen como hijos del nodo "Medios Web".
        from core.tabs.editing_media.freesound_client import FreesoundClient
        from core.tabs.editing_media.web_sources.freesound_provider import FreesoundProvider
        from core.tabs.editing_media.web_sources.wikimedia_provider import WikimediaProvider
        from core.tabs.editing_media.web_sources.openverse_provider import OpenverseProvider
        self.freesound_client = FreesoundClient()
        self.web_providers = {
            "freesound": FreesoundProvider(self.freesound_client, self.controller),
            "wikimedia": WikimediaProvider(),
            "openverse": OpenverseProvider(),
        }
        self.active_web_source_id = None
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self._exec_online_search)
        self.online_search_thread = None
        self.online_results = []
        self.current_page = 1
        self.loading_next_page = False
        
        # Inicializar reproductor de audio central para el espectro
        self.audio_player = None
        self.audio_output = None
        if MULTIMEDIA_AVAILABLE:
            try:
                self.audio_player = QMediaPlayer(self)
                self.audio_output = QAudioOutput(self)
                self.audio_player.setAudioOutput(self.audio_output)
                self.audio_output.setVolume(0.7)  # Volumen por defecto al 70%
                # El bucle NUNCA se controla con setLoops() más allá de este valor fijo:
                # cambiarlo en caliente con un medio ya cargado es poco fiable en algunos
                # backends. El bucle real lo maneja _on_audio_media_status_changed_loop.
                self.audio_player.setLoops(1)

                # Conectar señales del reproductor
                self.audio_player.positionChanged.connect(self._on_audio_position_changed)
                self.audio_player.durationChanged.connect(self._on_audio_duration_changed)
                self.audio_player.playbackStateChanged.connect(self._update_background_throttle)
                self.audio_player.mediaStatusChanged.connect(self._on_audio_media_status_changed_loop)
            except Exception as e:
                logger.error(f"EditingMediaTab: Error inicializando reproductor de audio: {e}")

        self.init_ui()
        
        # Conectar señales del reproductor de video de la vista previa al waveform central
        if MULTIMEDIA_AVAILABLE and hasattr(self, "preview_box") and self.preview_box.media_player:
            self.preview_box.media_player.positionChanged.connect(self._on_video_position_changed)
            self.preview_box.media_player.playbackStateChanged.connect(self._update_background_throttle)
        
        # Conectar señales del controlador
        self.controller.disk_changed.connect(self._on_disk_changed)
        self.controller.collections_changed.connect(self._on_collections_changed)
        
        self.controller.indexing_started.connect(self._on_indexing_started)
        self.controller.indexing_progress.connect(self._on_indexing_progress)
        self.controller.indexing_finished.connect(self._on_indexing_finished)
        
        QTimer.singleShot(50, self.controller.trigger_async_indexing)
        
        # Detener el Watchdog y la música cuando se destruya el widget
        self.destroyed.connect(self._cleanup)

        # Cargar los datos en el árbol por primera vez
        self._update_tree_view()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(150, self._update_media_list)

    def hideEvent(self, event):
        super().hideEvent(event)
        if hasattr(self, "pause_playback"):
            self.pause_playback()

    def init_ui(self):
        # Layout principal
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        self.main_layout.setSpacing(8)

        # ── Splitter Horizontal Principal ─────────────────────────────────────
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(6)
        self.main_layout.addWidget(self.splitter, 1)

        # 1. Columna Izquierda (20%): Carpetas Indexadas (Acordeón)
        self.col1_container = self._build_left_column()
        self.splitter.addWidget(self.col1_container)

        # 2. Columna Central (40%): Lista de Medios e Instrumento de Audio
        self.col2_container = self._build_center_column()
        self.splitter.addWidget(self.col2_container)

        # 3. Columna Derecha (40%): Vista Previa e Info Técnica
        self.col3_container = self._build_right_column()
        self.splitter.addWidget(self.col3_container)

        # Restaurar tamaños del splitter desde la configuración guardada
        cfg = get_config()
        saved_sizes = cfg.get("editing_media_splitter_sizes", [240, 480, 480])
        self.splitter.setSizes(saved_sizes)

        # Conectar señal para persistir cambios de tamaño del splitter
        self.splitter.splitterMoved.connect(self._on_splitter_moved)

        # Asegurar anchos mínimos adaptables a ventanas pequeñas (800x600)
        self.col1_container.setMinimumWidth(160)
        self.col2_container.setMinimumWidth(220)
        self.col3_container.setMinimumWidth(220)

        # Aplicar hojas de estilo para contenedores y listas
        self._apply_custom_styles()
        
        # Conectar manager de editores
        from core.services.editor_integration_manager import EditorIntegrationManager
        editor_mgr = EditorIntegrationManager.get_instance()
        if editor_mgr:
            editor_mgr.active_editor_changed.connect(lambda active: self._update_send_button_state())
            self._update_send_button_state()

    def set_license_info(self, title: str, desc: str, color_hex: str, credits_text: str = None, icon_name: str = "copyright.svg"):
        """Actualiza el panel de licencias con los datos (Título, Descripción, Color, y opcionalmente el texto TASL e icono)."""
        self.lbl_license_text.setText(title)
        self.lbl_license_text.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {color_hex};")
        
        self.lbl_license_desc.setText(desc)
        
        # Color the icon
        icon = get_colored_svg_icon(icon_name, color_hex)
        self.lbl_license_icon.setPixmap(icon.pixmap(16, 16))

        self.license_panel.setStyleSheet(f"""
            QFrame#licensePanel {{
                background-color: {get_theme_token('fondo_elemento', '#1e1e1e')};
                border: 1px solid {color_hex};
                border-radius: 6px;
            }}
        """)

        if credits_text:
            self._current_credits_text = credits_text
            self.btn_copy_credits.setVisible(True)
            self.btn_copy_credits.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    border: 1px solid {get_theme_token('borde_normal', '#444444')};
                    border-radius: 6px;
                    color: {get_theme_token('texto_principal', '#ffffff')};
                    padding: 4px 10px;
                }}
                QPushButton:hover {{
                    background-color: {get_theme_token('seleccion_fondo', '#2d2d2d')};
                    border: 1px solid {color_hex};
                    color: {get_theme_token('texto_principal', '#ffffff')};
                }}
            """)
        else:
            self._current_credits_text = ""
            self.btn_copy_credits.setVisible(False)

        self.license_panel.setVisible(True)

    def _on_copy_credits_clicked(self):
        """Copia el texto TASL actual al portapapeles y muestra confirmación."""
        if self._current_credits_text:
            QApplication.clipboard().setText(self._current_credits_text)
            self.btn_copy_credits.setText(self.tr("¡Créditos Copiados!"))
            # Reset text after 2 seconds
            QTimer.singleShot(2000, lambda: self.btn_copy_credits.setText(self.tr("Copiar Créditos (TASL)")))

    def _cleanup(self):
        """Detiene el watchdog y cualquier reproducción activa al cerrar."""
        self.controller.stop_watcher()
        self._stop_audio_playback()
        self.preview_box.stop_media()
        if hasattr(self, "waveform_thread") and self.waveform_thread and self.waveform_thread.isRunning():
            self.waveform_thread.terminate()
            self.waveform_thread.wait()
        # Detener servidor de callback de OAuth si estuviera corriendo
        if hasattr(self, "_oauth_handler") and self._oauth_handler:
            self._oauth_handler.cancel()

    def _build_left_column(self) -> QFrame:
        col = QFrame()
        col.setObjectName("sidebarFrame")
        layout = QVBoxLayout(col)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        lbl_section = QLabel(self.tr("Carpetas & Colecciones"))
        lbl_section.setStyleSheet("font-weight: bold; font-size: 14px; color: white;")
        layout.addWidget(lbl_section)

        # Botón para Indexar Carpeta colocado arriba, justo debajo del título
        self.btn_add_folder = AnimatedButton(self.tr("Indexar Carpeta"))
        self.btn_add_folder.setObjectName("analyzeButton")
        self.btn_add_folder.setFixedHeight(32)
        self.btn_add_folder.clicked.connect(self._on_add_folder_clicked)
        layout.addWidget(self.btn_add_folder)

        # QTreeWidget en modo acordeón/árbol de carpetas
        self.tree_folders = QTreeWidget()
        self.tree_folders.setHeaderHidden(True)
        self.tree_folders.setObjectName("accordionTree")
        self.tree_folders.setAnimated(True)
        self.tree_folders.setIndentation(14)
        self.tree_folders.itemClicked.connect(self._on_tree_item_clicked)
        self.tree_folders.currentItemChanged.connect(self._on_tree_current_item_changed)
        self.tree_folders.itemExpanded.connect(self._on_tree_item_expanded)
        self.tree_folders.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree_folders.customContextMenuRequested.connect(self._show_tree_context_menu)
        # Por defecto QHeaderView.stretchLastSection=True estira la única columna al
        # ancho exacto del viewport siempre -- nunca puede ser más ancha, así que un
        # nombre de carpeta largo solo se elide ("...") sin forma de verlo completo.
        # ResizeToContents + stretchLastSection=False deja que la columna crezca con el
        # contenido (incluida la sangría de ítems anidados/expandidos); si eso supera el
        # ancho del panel, aparece el scroll horizontal (ScrollBarAsNeeded, ya es el
        # default de QAbstractItemView) en vez de seguir elidiendo el texto.
        header = self.tree_folders.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        layout.addWidget(self.tree_folders, 1)

        # Texto indicando los medios indexados al pie de la columna
        self.lbl_indexed_count = QLabel("")
        self.lbl_indexed_count.setAlignment(Qt.AlignCenter)
        self.lbl_indexed_count.setStyleSheet(f"font-size: 11px; color: {get_theme_token('texto_secundario', '#a6adc8')}; margin-top: 4px; margin-bottom: 2px;")
        layout.addWidget(self.lbl_indexed_count)

        return col

    def _build_center_column(self) -> QFrame:
        col = QFrame()
        col.setObjectName("mediaListFrame")
        layout = QVBoxLayout(col)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Título
        lbl_section = QLabel(self.tr("Lista de Medios"))
        lbl_section.setStyleSheet("font-weight: bold; font-size: 14px; color: white;")
        layout.addWidget(lbl_section)

        # Buscador
        search_layout = QHBoxLayout()
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(6)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(self.tr("Buscar medios..."))
        self.search_input.setFixedHeight(32)
        self.search_input.setStyleSheet("QLineEdit { padding-right: 28px; }")

        # Integrar spinner de carga animado a la derecha de search_input
        self.search_spinner = LoadingSpinnerWidget(self.search_input, size=16, color=get_theme_token('acento_primario', '#B9E640'))
        spin_layout = QHBoxLayout(self.search_input)
        spin_layout.setContentsMargins(0, 0, 8, 0)
        spin_layout.addStretch()
        spin_layout.addWidget(self.search_spinner)

        self.search_input.textChanged.connect(self._update_media_input_changed)
        search_layout.addWidget(self.search_input, 1)

        # Contenedor para el filtro de licencias (visible en cualquier origen web que declare
        # license_filter_options — hoy Freesound y Wikimedia; se repuebla dinámicamente en
        # _update_button_states según el provider activo).
        self.license_container = QFrame()
        self.license_container.setVisible(False)
        lic_layout = QHBoxLayout(self.license_container)
        lic_layout.setContentsMargins(0, 0, 0, 0)
        lic_layout.setSpacing(6)

        lbl_copyright = QLabel()
        lbl_copyright.setPixmap(get_svg_icon("copyright.svg").pixmap(16, 16))
        lbl_copyright.setToolTip(self.tr("Filtro de Licencia"))
        lbl_copyright.setAlignment(Qt.AlignCenter)
        lic_layout.addWidget(lbl_copyright)

        self.web_license_combo = AutoPopupComboBox()
        self.web_license_combo.setFixedHeight(32)
        self.web_license_combo.setFixedWidth(150)
        self.web_license_combo.addItem(self.tr("Cualquiera"), "Cualquiera")
        self.web_license_combo.setToolTip(self.tr("Filtrar por Licencia"))
        self.web_license_combo.currentIndexChanged.connect(lambda: self._update_media_input_changed(""))
        lic_layout.addWidget(self.web_license_combo)

        search_layout.addWidget(self.license_container)

        self.btn_freesound_login = QPushButton()
        self.btn_freesound_login.setFixedSize(32, 32)
        self.btn_freesound_login.setIconSize(QSize(18, 18))
        self.btn_freesound_login.setStyleSheet(f"""
            QPushButton {{
                background-color: {get_theme_token('fondo_elemento', '#2d2d2d')};
                border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                border-radius: 6px;
                padding: 0px;
            }}
            QPushButton:hover {{
                background-color: {get_theme_token('seleccion_fondo', '#3d3d3d')};
            }}
        """)
        self.btn_freesound_login.clicked.connect(self._on_freesound_login_clicked)
        self.btn_freesound_login.setVisible(False)
        self._update_freesound_login_button()
        search_layout.addWidget(self.btn_freesound_login)

        layout.addLayout(search_layout)

        # Botones de filtro rápido + Selector de vista
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(4)
        self.filter_buttons = []
        # Mapeo con llamadas self.tr(...) literales -- lupdate solo extrae strings
        # cuando el argumento es un literal escrito ahí mismo, no una variable de loop.
        _filter_labels = {
            "Todos": self.tr("Todos"),
            "Imágenes": self.tr("Imágenes"),
            "Videos": self.tr("Videos"),
            "Audios": self.tr("Audios"),
        }
        for text in ["Todos", "Imágenes", "Videos", "Audios"]:
            btn = QPushButton(_filter_labels[text])
            btn.setProperty("filter_key", text)
            btn.setCheckable(True)
            if text == "Todos":
                btn.setChecked(True)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {get_theme_token('fondo_elemento', '#2d2d2d')};
                    border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                    padding: 4px 8px;
                    font-size: 11px;
                    border-radius: 6px;
                }}
                QPushButton:checked {{
                    background-color: {get_theme_token('acento_primario', '#B9E640')};
                    color: {get_theme_token('fondo_principal', '#0a0a0a')};
                    font-weight: bold;
                }}
            """)
            btn.clicked.connect(self._on_filter_button_clicked)
            btn_bar.addWidget(btn)
            self.filter_buttons.append(btn)

        btn_bar.addStretch(1)

        # Botones de Modo de Vista (Lista / Cuadrícula)
        btn_mode_style = f"""
            QPushButton {{
                background-color: {get_theme_token('fondo_elemento', '#2d2d2d')};
                border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                border-radius: 6px;
                padding: 0px;
                min-height: 0px;
            }}
            QPushButton:hover {{
                background-color: {get_theme_token('seleccion_fondo', '#3d3d3d')};
            }}
            QPushButton:checked {{
                background-color: {get_theme_token('acento_primario', '#B9E640')};
                border-color: {get_theme_token('acento_primario', '#B9E640')};
            }}
        """

        self.btn_view_list = QPushButton()
        self.btn_view_list.setFixedSize(28, 28)
        self.btn_view_list.setCheckable(True)
        self.btn_view_list.setToolTip(self.tr("Vista de Lista"))
        self.btn_view_list.setIcon(get_colored_svg_icon("view_list.svg", "#FFFFFF", size=16))
        self.btn_view_list.setIconSize(QSize(16, 16))
        self.btn_view_list.setStyleSheet(btn_mode_style)
        self.btn_view_list.clicked.connect(lambda: self.set_view_mode("list"))
        btn_bar.addWidget(self.btn_view_list)

        self.btn_view_grid = QPushButton()
        self.btn_view_grid.setFixedSize(28, 28)
        self.btn_view_grid.setCheckable(True)
        self.btn_view_grid.setToolTip(self.tr("Vista de Cuadrícula"))
        self.btn_view_grid.setIcon(get_colored_svg_icon("grid_view.svg", "#000000", size=16))
        self.btn_view_grid.setIconSize(QSize(16, 16))
        self.btn_view_grid.setStyleSheet(btn_mode_style)
        self.btn_view_grid.clicked.connect(lambda: self.set_view_mode("grid"))
        self.btn_view_grid.installEventFilter(self)
        btn_bar.addWidget(self.btn_view_grid)

        # Temporizador para ocultar popup al perder hover (puente extendido de 400ms)
        from PySide6.QtCore import QTimer
        self.hide_popup_timer = QTimer(self)
        self.hide_popup_timer.setSingleShot(True)
        self.hide_popup_timer.setInterval(400)
        self.hide_popup_timer.timeout.connect(self._hide_grid_scale_popup)

        # Popup emergente flotante (usamos Tool para no robar foco modalmente)
        self.grid_scale_popup = QFrame(self, Qt.Tool | Qt.FramelessWindowHint)
        self.grid_scale_popup.setObjectName("gridScalePopup")
        self.grid_scale_popup.installEventFilter(self)
        self.grid_scale_popup.setAttribute(Qt.WA_TranslucentBackground)
        self.grid_scale_popup.setFixedWidth(100)
        self.grid_scale_popup.setStyleSheet(f"""
            QFrame#gridScalePopup {{
                background-color: {get_theme_token('panel_fondo', '#181818')};
                border: 1px solid {get_theme_token('borde_sutil', '#333333')};
                border-radius: 10px;
            }}
        """)
        popup_layout = QHBoxLayout(self.grid_scale_popup)
        popup_layout.setContentsMargins(6, 4, 6, 4)
        popup_layout.setSpacing(0)

        self.icon_size_slider = QSlider(Qt.Horizontal)
        self.icon_size_slider.setRange(48, 200)
        self.icon_size_slider.setValue(self._saved_icon_size)
        self.icon_size_slider.setFixedWidth(75)
        self.icon_size_slider.setCursor(Qt.PointingHandCursor)
        self.icon_size_slider.setToolTip(self.tr("Tamaño de cuadrícula"))
        self.icon_size_slider.valueChanged.connect(self._on_icon_size_changed)
        popup_layout.addWidget(self.icon_size_slider)



        layout.addLayout(btn_bar)

        # Contenedor apilado para alternar entre Vista de Lista Tabular (SoundQ) y Vista de Cuadrícula (Cards)
        self.media_stack = QStackedWidget()

        # Modelo de Datos MVC
        self.media_model = MediaTableModel(self)
        self.media_model.global_sort_requested.connect(self._on_global_sort_requested)

        # 1. Modo Lista Tabular (QTreeView multi-columna estilo SoundQ)
        self.media_table = _MediaTreeView()
        self.media_table.setObjectName("mediaTableWidget")
        self.media_table.setModel(self.media_model)
        self.media_table.setSortingEnabled(True) # Activamos sort (manejado nativamente por MediaTableModel)
        self.media_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.media_table.setSelectionBehavior(QTreeView.SelectRows)
        self.media_table.setAlternatingRowColors(True)
        self.media_table.setRootIsDecorated(False)
        self.media_table.setItemsExpandable(False)
        self.media_table.setIconSize(QSize(18, 18))
        self.media_table.setUniformRowHeights(True)
        self.media_table.setDragEnabled(True)
        self.media_table.setDragDropMode(QAbstractItemView.DragOnly)

        # Estilizar encabezado de columnas
        header = self.media_table.header()
        header.setVisible(True)
        header.setStretchLastSection(False)
        
        # Habilitar scrollbars horizontales y manejar anchos
        self.media_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # Los anchos iniciales se ajustarán luego
        
        # Conectar eventos de la tabla
        self.media_table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.media_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.media_table.customContextMenuRequested.connect(self._show_media_context_menu)
        self.media_table.verticalScrollBar().valueChanged.connect(self._on_list_scroll)
        
        # 2. Modo Cuadrícula (QListView IconMode)
        self.media_list = _MediaListView()
        self.media_list.setObjectName("mediaListWidget")
        self.media_list.setModel(self.media_model)
        self.media_list.setSpacing(0)
        self.media_list.setIconSize(QSize(16, 16))
        self.media_list.setUniformItemSizes(True)
        self.media_list.setVerticalScrollMode(QListView.ScrollPerPixel)
        self.media_list.verticalScrollBar().setSingleStep(30)
        self.media_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.media_list.setSelectionModel(self.media_table.selectionModel())
        self.media_list.setDragEnabled(True)
        self.media_list.setDragDropMode(QAbstractItemView.DragOnly)
        self.media_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.media_list.customContextMenuRequested.connect(self._show_media_context_menu)
        self.media_list.verticalScrollBar().valueChanged.connect(self._on_list_scroll)
        self.media_list.viewport().installEventFilter(self)

        # 3. Página de "inicia sesión" para Freesound (cuando no hay sesión iniciada)
        self.freesound_login_page = QWidget()
        login_page_layout = QVBoxLayout(self.freesound_login_page)
        login_page_layout.setAlignment(Qt.AlignCenter)
        login_page_layout.setSpacing(16)
        self.freesound_login_msg_label = QLabel(self.tr("Inicia sesión con Freesound para buscar sonidos 🔑"))
        self.freesound_login_msg_label.setAlignment(Qt.AlignCenter)
        self.freesound_login_msg_label.setStyleSheet(f"color: {get_theme_token('texto_secundario', '#aaaaaa')}; font-size: 14px;")
        self.btn_freesound_login_big = QPushButton(self.tr("Iniciar Sesión con Freesound"))
        self.btn_freesound_login_big.setFixedHeight(44)
        self.btn_freesound_login_big.setMinimumWidth(260)
        self.btn_freesound_login_big.setCursor(Qt.PointingHandCursor)
        self.btn_freesound_login_big.setStyleSheet(f"""
            QPushButton {{
                background-color: {get_theme_token('acento_primario', '#B9E640')};
                color: {get_theme_token('fondo_principal', '#0a0a0a')};
                border: none;
                border-radius: 8px;
                font-weight: bold;
                font-size: 13px;
                padding: 10px 24px;
            }}
            QPushButton:hover {{
                background-color: {get_theme_token('acento_primario', '#B9E640')};
            }}
        """)
        self.btn_freesound_login_big.clicked.connect(self._on_freesound_login_clicked)
        login_page_layout.addWidget(self.freesound_login_msg_label)
        login_page_layout.addWidget(self.btn_freesound_login_big, 0, Qt.AlignCenter)

        self.media_stack.addWidget(self.media_table) # Index 0: Lista Tabular SoundQ
        self.media_stack.addWidget(self.media_list)  # Index 1: Cuadrícula Cards
        self.media_stack.addWidget(self.freesound_login_page)  # Index 2: Inicia sesión Freesound

        layout.addWidget(self.media_stack, 1)

        # Aplicar modo de vista guardado
        self.set_view_mode(self.view_mode)

        # ── ESPECTRO DE AUDIO INTEGRADO (A pie de columna, oculto por defecto) ──
        self.audio_panel = QFrame()
        self.audio_panel.setObjectName("audioSpectrumPanel")
        self.audio_panel.setVisible(False)
        audio_layout = QVBoxLayout(self.audio_panel)
        audio_layout.setContentsMargins(10, 10, 10, 10)
        audio_layout.setSpacing(6)

        # Header superior con Carátula e información de título para archivos de audio
        self.audio_header_widget = QWidget()
        header_layout = QHBoxLayout(self.audio_header_widget)
        header_layout.setContentsMargins(0, 0, 0, 4)
        header_layout.setSpacing(12)

        self.lbl_cover_art = QLabel()
        self.lbl_cover_art.setFixedSize(64, 64)
        self.lbl_cover_art.setStyleSheet(f"""
            QLabel {{
                background-color: {get_theme_token('fondo_elemento', '#1c1c1e')};
                border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                border-radius: 8px;
            }}
        """)
        self.lbl_cover_art.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(self.lbl_cover_art)

        header_info_v = QVBoxLayout()
        header_info_v.setSpacing(2)
        header_info_v.addStretch()

        self.lbl_audio_name = QLabel()
        self.lbl_audio_name.setStyleSheet(f"font-weight: bold; font-size: 13px; color: {get_theme_token('acento_primario', '#B9E640')};")
        self.lbl_audio_name.setWordWrap(True)
        header_info_v.addWidget(self.lbl_audio_name)

        self.lbl_audio_sub = QLabel()
        self.lbl_audio_sub.setStyleSheet("font-size: 11px; color: #a6adc8;")
        header_info_v.addWidget(self.lbl_audio_sub)
        header_info_v.addStretch()

        header_layout.addLayout(header_info_v, 1)
        audio_layout.addWidget(self.audio_header_widget)

        # Título interno
        self.lbl_audio_title = QLabel(self.tr("Visualizador de Espectro"))
        self.lbl_audio_title.setStyleSheet("font-size: 11px; font-weight: bold; color: #f5c2e7;")
        audio_layout.addWidget(self.lbl_audio_title)

        # El widget gráfico del espectro
        self.waveform_widget = AudioWaveformWidget()
        self.waveform_widget.seek_requested.connect(self._on_waveform_seek_requested)
        self.waveform_widget.subclip_drag_started.connect(self._on_waveform_subclip_drag_requested)
        self.waveform_widget.subclip_send_requested.connect(self._on_waveform_subclip_send_requested)
        audio_layout.addWidget(self.waveform_widget)

        # Controles inferiores (Play/Pausa, Volumen, Tiempo) — agrupados para poder ocultarlos en videos
        self.audio_controls_widget = QWidget()
        controls_layout = QHBoxLayout(self.audio_controls_widget)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(8)

        self.btn_play = QPushButton()
        self.btn_play.setIconSize(QSize(14, 14))
        self.btn_play.setFixedSize(26, 26)
        apply_player_play_button_style(self.btn_play, is_playing=False, icon_size=14)
        self.btn_play.clicked.connect(self._on_play_clicked)
        controls_layout.addWidget(self.btn_play)

        # Botón Loop/Repetir para audio
        self._audio_loop_active = False  # Por defecto DESACTIVADO
        self.btn_loop_audio = QPushButton()
        self.btn_loop_audio.setIconSize(QSize(14, 14))
        self.btn_loop_audio.setFixedSize(26, 26)
        apply_player_loop_button_style(self.btn_loop_audio, is_active=False, icon_size=14)

        self.btn_loop_audio.clicked.connect(self._on_toggle_audio_loop)
        controls_layout.addWidget(self.btn_loop_audio)

        # Botón Editar Subclip
        self.btn_edit_subclip = QPushButton()
        self.btn_edit_subclip.setIconSize(QSize(14, 14))
        self.btn_edit_subclip.setFixedSize(26, 26)
        self._audio_has_subclips = False
        apply_edit_subclip_button_style(self.btn_edit_subclip, has_subclips=False, icon_size=14)
        self.btn_edit_subclip.clicked.connect(self._on_open_subclip_dialog)
        controls_layout.addWidget(self.btn_edit_subclip)

        self.lbl_time = QLabel("00:00 / 00:00")
        self.lbl_time.setStyleSheet("font-size: 11px; color: #a6adc8;")
        controls_layout.addWidget(self.lbl_time)

        controls_layout.addStretch(1)

        # Control de Volumen Unificado
        self.volume_control = VolumeControlWidget(initial_volume=70, slider_width=80)
        self.volume_control.volume_changed.connect(self._on_volume_changed)
        controls_layout.addWidget(self.volume_control)

        audio_layout.addWidget(self.audio_controls_widget)
        self.audio_controls_widget.installEventFilter(self)

        return col

    def _build_right_column(self) -> QFrame:
        col = QFrame()
        col.setObjectName("previewFrame")
        layout = QVBoxLayout(col)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        lbl_section = QLabel(self.tr("Vista Previa & Detalles"))
        lbl_section.setStyleSheet("font-weight: bold; font-size: 14px; color: white;")
        layout.addWidget(lbl_section)

        # Contenedor para Modo Carrusel
        self.carousel_nav_widget = QWidget()
        self.carousel_nav_widget.setObjectName("carouselNavWidget")
        self.carousel_nav_widget.setVisible(False)
        self.carousel_nav_widget.setFixedHeight(30)
        carousel_layout = QHBoxLayout(self.carousel_nav_widget)
        carousel_layout.setContentsMargins(0, 0, 0, 0)
        carousel_layout.setSpacing(10)
        
        self.btn_carousel_prev = QPushButton("<")
        self.btn_carousel_prev.setFixedSize(24, 24)
        self.btn_carousel_prev.setStyleSheet("background: transparent; font-weight: bold; color: white;")
        self.btn_carousel_prev.clicked.connect(self._on_carousel_prev)
        
        self.lbl_carousel_status = QLabel(self.tr("{0} de {1}").format(1, 1))
        self.lbl_carousel_status.setAlignment(Qt.AlignCenter)
        self.lbl_carousel_status.setStyleSheet("color: #a6adc8; font-weight: bold;")
        
        self.btn_carousel_next = QPushButton(">")
        self.btn_carousel_next.setFixedSize(24, 24)
        self.btn_carousel_next.setStyleSheet("background: transparent; font-weight: bold; color: white;")
        self.btn_carousel_next.clicked.connect(self._on_carousel_next)
        
        carousel_layout.addStretch()
        carousel_layout.addWidget(self.btn_carousel_prev)
        carousel_layout.addWidget(self.lbl_carousel_status)
        carousel_layout.addWidget(self.btn_carousel_next)
        carousel_layout.addStretch()
        
        layout.addWidget(self.carousel_nav_widget)

        # Contenedor de Vista Previa Cuadrado
        self.preview_box = PreviewContainerWidget()
        if hasattr(self.preview_box, "btn_edit_subclip"):
            self.preview_box.btn_edit_subclip.clicked.connect(self._on_open_subclip_dialog)
        layout.addWidget(self.preview_box)

        # El panel de audio/forma de onda
        layout.addWidget(self.audio_panel)

        # Panel de Licencia Online
        self.license_panel = QFrame()
        self.license_panel.setObjectName("licensePanel")
        self.license_panel.setVisible(False)
        self.license_panel.setStyleSheet(f"""
            QFrame#licensePanel {{
                background-color: {get_theme_token('fondo_elemento', '#1e1e1e')};
                border: 1px solid {get_theme_token('acento_primario', '#B9E640')};
                border-radius: 6px;
            }}
        """)
        license_layout = QVBoxLayout(self.license_panel)
        license_layout.setContentsMargins(10, 8, 10, 8)
        license_layout.setSpacing(6)

        # Fila superior: Ícono + Título
        top_row = QHBoxLayout()
        self.lbl_license_icon = QLabel()
        copyright_icon = get_colored_svg_icon("copyright.svg", get_theme_token("acento_primario", "#B9E640"))
        self.lbl_license_icon.setPixmap(copyright_icon.pixmap(16, 16))
        top_row.addWidget(self.lbl_license_icon)

        self.lbl_license_text = QLabel()
        self.lbl_license_text.setStyleSheet("font-size: 12px; font-weight: bold; color: white;")
        top_row.addWidget(self.lbl_license_text, 1)
        license_layout.addLayout(top_row)

        # Descripción
        self.lbl_license_desc = QLabel()
        self.lbl_license_desc.setStyleSheet("font-size: 11px; color: #a6adc8;")
        self.lbl_license_desc.setWordWrap(True)
        license_layout.addWidget(self.lbl_license_desc)

        # Botón Copiar Créditos
        self.btn_copy_credits = AnimatedButton(self.tr("Copiar Créditos (TASL)"))
        self.btn_copy_credits.setFixedHeight(28)
        self.btn_copy_credits.clicked.connect(self._on_copy_credits_clicked)
        self.btn_copy_credits.setVisible(False)
        license_layout.addWidget(self.btn_copy_credits)

        self._current_credits_text = ""

        layout.addWidget(self.license_panel)

        # Contenedor de Información Técnica (Metadatos)
        self.info_box = QFrame()
        self.info_box.setObjectName("infoBoxFrame")
        info_layout = QVBoxLayout(self.info_box)
        info_layout.setContentsMargins(10, 10, 10, 10)
        info_layout.setSpacing(6)

        lbl_info_title = QLabel(self.tr("Información Técnica"))
        lbl_info_title.setStyleSheet("font-weight: bold; font-size: 12px; color: #a6adc8;")
        info_layout.addWidget(lbl_info_title)

        # Crear QScrollArea para los metadatos
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.NoFrame)
        scroll_area.setStyleSheet("background: transparent; border: none;")
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # Estilizar el scrollbar de manera elegante
        scroll_area.verticalScrollBar().setStyleSheet("""
            QScrollBar:vertical {
                border: none;
                background: #111;
                width: 6px;
                margin: 0px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: #333;
                min-height: 20px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background: #1DC038;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                border: none;
                background: none;
                height: 0px;
            }
        """)

        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 8, 0)
        scroll_layout.setSpacing(6)

        # Grid de metadatos ampliado
        self.metadata_labels = {}
        fields = [
            ("nombre", self.tr("Nombre:")),
            ("ruta", self.tr("Ruta:")),
            ("tipo", self.tr("Tipo:")),
            ("tamaño", self.tr("Tamaño:")),
            ("creado", self.tr("Creado:")),
            ("modificado", self.tr("Modificado:")),
            ("duración", self.tr("Duración:")),
            ("resolución", self.tr("Resolución:")),
            ("video_codec", self.tr("Códec Video:")),
            ("video_profile", self.tr("Perfil Video:")),
            ("fps", self.tr("FPS:")),
            ("aspecto", self.tr("Rel. Aspecto:")),
            ("bitrate_video", self.tr("Bitrate Video:")),
            ("color", self.tr("Espacio Color:")),
            ("audio_codec", self.tr("Códec Audio:")),
            ("samplerate", self.tr("Muestreo:")),
            ("canales", self.tr("Canales:")),
            ("bitrate_audio", self.tr("Bitrate Audio:")),
        ]
        
        self.metadata_header_labels = {}
        for key, label_text in fields:
            row = QHBoxLayout()
            row.setSpacing(6)
            
            lbl_key = QLabel(label_text)
            lbl_key.setFixedWidth(90)
            lbl_key.setStyleSheet("color: #89b4fa; font-size: 11px; font-weight: bold;")
            self.metadata_header_labels[key] = lbl_key
            
            lbl_val = QLabel("-")
            lbl_val.setStyleSheet("color: #cdd6f4; font-size: 11px;")
            lbl_val.setWordWrap(True)
            self.metadata_labels[key] = lbl_val
            
            row.addWidget(lbl_key)
            row.addWidget(lbl_val, 1)
            scroll_layout.addLayout(row)

        scroll_layout.addStretch()
        scroll_area.setWidget(scroll_content)
        info_layout.addWidget(scroll_area, 1)

        # Botones inferiores del panel de metadatos
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(8)

        # Botón para revelar/abrir en el explorador de archivos
        self.btn_reveal = AnimatedButton("")
        self.btn_reveal.setFixedSize(34, 34)
        apply_folder_open_button_style(self.btn_reveal, self.tr("Abrir en Explorador"), icon_size=20)
        self.btn_reveal.setEnabled(False)
        self.btn_reveal.clicked.connect(self._on_reveal_clicked)
        buttons_layout.addWidget(self.btn_reveal)

        # Boton Split para enviar a editor
        self.btn_send_editor = QToolButton()
        self.btn_send_editor.setObjectName("sendEditorButton")
        self.btn_send_editor.setFixedHeight(34)
        self.btn_send_editor.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_send_editor.setPopupMode(QToolButton.MenuButtonPopup)
        self.btn_send_editor.setText(self.tr("Ningún editor conectado"))
        self.btn_send_editor.setEnabled(False)
        self.btn_send_editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btn_send_editor.setStyleSheet(f"""
            QToolButton {{
                background-color: {get_theme_token('fondo_elemento', '#2d2d2d')};
                border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                border-radius: 8px;
                color: #cdd6f4;
                padding-left: 10px;
                padding-right: 10px;
                font-weight: 500;
            }}
            QToolButton::menu-button {{
                border-left: 1px solid {get_theme_token('borde_normal', '#444444')};
                width: 22px;
                border-top-right-radius: 8px;
                border-bottom-right-radius: 8px;
            }}
            QToolButton:hover {{
                background-color: {get_theme_token('seleccion_fondo', '#3d3d3d')};
            }}
            QToolButton:disabled {{
                color: #6c7086;
                background-color: {get_theme_token('fondo_elemento', '#1e1e1e')};
            }}
        """)
        
        # Menu del boton send editor
        self.send_editor_menu = QMenu(self.btn_send_editor)
        self.action_send_single = self.send_editor_menu.addAction(self.tr("Enviar solo este medio (1)"))
        self.btn_send_editor.setMenu(self.send_editor_menu)
        
        self.btn_send_editor.clicked.connect(self._on_send_editor_clicked)
        self.action_send_single.triggered.connect(self._on_send_editor_single_clicked)
        self._send_editor_state = SendButtonState(self.btn_send_editor, restore_callback=self._update_send_button_state)

        buttons_layout.addWidget(self.btn_send_editor, 2)

        # QComboBox de selección de etiquetas (estilo nativo de la app para medios web)
        self.combo_tags = AutoPopupComboBox()
        self.combo_tags.setObjectName("tagsComboBox")
        self.combo_tags.setFixedHeight(34)
        self.combo_tags.setVisible(False)
        self.combo_tags.currentIndexChanged.connect(self._on_label_combo_changed)
        buttons_layout.addWidget(self.combo_tags, 1)

        # Botón para descargar archivo de Freesound (medios web) — solo ícono, como btn_reveal
        self.btn_download = AnimatedButton("")
        self.btn_download.setFixedSize(34, 34)
        apply_download_action_button_style(self.btn_download, self.tr("Descargar Medio"), icon_size=20)
        self.btn_download.setEnabled(False)
        self.btn_download.setVisible(False)
        self.btn_download.clicked.connect(self._on_download_clicked)
        buttons_layout.addWidget(self.btn_download)

        info_layout.addLayout(buttons_layout)


        layout.addWidget(self.info_box, 1)

        return col

    def _accent_rgba(self, alpha: int) -> str:
        """Convierte el color de acento del tema a 'rgba(r,g,b,a)' para fondos de selección
        con buen contraste (el token 'seleccion_fondo' es casi idéntico a 'borde_normal' y
        resulta casi invisible sobre el fondo oscuro)."""
        from PySide6.QtGui import QColor
        color = QColor(get_theme_token('acento_primario', '#B9E640'))
        return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha})"

    def _apply_custom_styles(self):
        """Aplica colores y bordes usando el sistema de tokens de temas."""
        fondo_secundario = get_theme_token('fondo_secundario', '#1e1e1e')
        borde_color = get_theme_token('borde_normal', '#2d2d2d')

        box_style = f"""
            QFrame#sidebarFrame, QFrame#mediaListFrame, QFrame#previewFrame {{
                background-color: {fondo_secundario};
                border: 1px solid {borde_color};
                border-radius: 6px;
            }}
            QLabel {{
                border: none;
                background: transparent;
            }}
        """
        
        self.col1_container.setStyleSheet(box_style)
        self.col2_container.setStyleSheet(box_style)
        self.col3_container.setStyleSheet(box_style)

        # Estilo para el panel de audio
        self.audio_panel.setStyleSheet(f"""
            QFrame#audioSpectrumPanel {{
                background-color: {get_theme_token('fondo_principal', '#0a0a0a')};
                border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                border-radius: 6px;
            }}
        """)

        table_style = f"""
            QTreeView#mediaTableWidget {{
                background-color: {get_theme_token('fondo_principal', '#0a0a0a')};
                border: 1px solid {borde_color};
                padding: 0px;
                color: {get_theme_token('texto_principal', '#cdd6f4')};
                font-size: 12px;
                alternate-background-color: {get_theme_token('fondo_secundario', '#121212')};
                outline: none;
            }}
            QTreeView#mediaTableWidget::item {{
                padding: 4px 8px;
                border-bottom: 1px solid {get_theme_token('borde_normal', '#1f1f23')};
                color: {get_theme_token('texto_principal', '#cdd6f4')};
            }}
            QTreeView#mediaTableWidget::item:hover {{
                background-color: {self._accent_rgba(22)};
            }}
            QTreeView#mediaTableWidget::item:selected {{
                background-color: {self._accent_rgba(60)};
                border-top: 1px solid {get_theme_token('acento_primario', '#B9E640')};
                border-bottom: 1px solid {get_theme_token('acento_primario', '#B9E640')};
                color: {get_theme_token('acento_primario', '#B9E640')};
                font-weight: bold;
            }}
            QHeaderView::section {{
                background-color: {get_theme_token('fondo_elemento', '#1c1c1e')};
                color: {get_theme_token('texto_secundario', '#a6adc8')};
                padding: 6px 8px;
                border: none;
                border-right: 1px solid {borde_color};
                border-bottom: 1px solid {get_theme_token('acento_primario', '#B9E640')};
                font-weight: bold;
                font-size: 11px;
                text-transform: uppercase;
            }}
            QHeaderView::section:hover {{
                background-color: {get_theme_token('seleccion_fondo', '#2d2d2d')};
                color: {get_theme_token('acento_primario', '#B9E640')};
            }}
        """
        if hasattr(self, "media_table"):
            self.media_table.setStyleSheet(table_style)

        list_style = f"""
            QListView {{
                background-color: {get_theme_token('fondo_principal', '#0a0a0a')};
                border: 1px solid {borde_color};
                padding: 5px;
                color: {get_theme_token('texto_principal', '#cdd6f4')};
            }}
            QListView::item {{
                padding: 6px 10px;
                margin: 2px;
                border-radius: 8px;
                min-height: 30px;
                font-size: 13px;
                background-color: {get_theme_token('fondo_elemento', '#1c1c1e')};
                border: 1px solid transparent;
            }}
            QListView::item:hover {{
                background-color: {self._accent_rgba(22)};
                border-color: {get_theme_token('borde_normal', '#3d3d3d')};
            }}
            QListView::item:selected {{
                background-color: {self._accent_rgba(65)};
                border: 2px solid {get_theme_token('acento_primario', '#B9E640')};
                color: {get_theme_token('acento_primario', '#B9E640')};
                font-weight: bold;
            }}
        """
        self.media_list.setStyleSheet(list_style)

        # Obtener rutas absolutas para las imágenes del árbol
        src_dir = get_src_dir()
        color_closed = get_theme_token("texto_secundario", "#888888")
        color_open = get_theme_token("acento_primario", "#B9E640")
        closed_arrow = generate_tinted_svg("arrow_right", color_closed)
        open_arrow = generate_tinted_svg("arrow_drop_down", color_open)

        # Estilo para el árbol de carpetas (Columna Izquierda)
        tree_style = f"""
            QTreeWidget {{
                background-color: {get_theme_token('fondo_principal', '#0a0a0a')};
                border: 1px solid {borde_color};
                padding: 5px;
                font-size: 11px;
            }}
            QTreeWidget::item {{
                padding: 4px 5px;
                border-radius: 4px;
                color: {get_theme_token('texto_principal', '#cdd6f4')};
            }}
            QTreeWidget::item:hover {{
                background-color: {get_theme_token('seleccion_fondo', '#2d2d2d')};
            }}
            QTreeWidget::item:selected {{
                background-color: {get_theme_token('seleccion_fondo', '#2d2d2d')};
                color: {get_theme_token('acento_primario', '#B9E640')};
                font-weight: bold;
            }}
            QTreeView::branch:has-children:closed:adjoins-item {{
                image: url("{closed_arrow}");
            }}
            QTreeView::branch:has-children:open:adjoins-item {{
                image: url("{open_arrow}");
            }}
            QTreeView::branch:selected {{
                background-color: {get_theme_token('seleccion_fondo', '#2d2d2d')};
            }}
            QTreeView::branch:hover {{
                background-color: {get_theme_token('seleccion_fondo', '#2d2d2d')};
            }}
        """
        self.tree_folders.setStyleSheet(tree_style)

    def _update_edit_subclip_button_state(self, has_subclips: bool):
        """Actualiza la apariencia 'encendida/apagada' de los botones de editar subclips
        (tanto el del panel de audio como el del panel de video) según si el medio
        actualmente mostrado ya tiene subclips guardados."""
        if hasattr(self, "btn_edit_subclip"):
            self._audio_has_subclips = has_subclips
            apply_edit_subclip_button_style(self.btn_edit_subclip, has_subclips=has_subclips, icon_size=14)
        if hasattr(self, "preview_box") and hasattr(self.preview_box, "set_edit_subclip_active"):
            self.preview_box.set_edit_subclip_active(has_subclips)

    def _restore_media_stack_widget(self):
        """Restaura el media_stack al widget de tabla/cuadrícula que corresponde según el
        modo de vista actual (se usa para salir de la página de 'inicia sesión' de Freesound).
        Se protege con hasattr porque _update_media_list() puede dispararse de forma síncrona
        durante la propia construcción de _build_center_column() (p.ej. al inicializar el
        slider de tamaño de ícono), antes de que media_list/media_table ya existan."""
        if not (hasattr(self, "media_stack") and hasattr(self, "media_list") and hasattr(self, "media_table")):
            return
        target = self.media_list if getattr(self, "view_mode", "grid") == "grid" else self.media_table
        if self.media_stack.currentWidget() is not target:
            self.media_stack.setCurrentWidget(target)

    def set_view_mode(self, mode: str):
        """Alterna entre vista de lista tabular (SoundQ style) y vista de cuadrícula/miniaturas."""
        self.view_mode = mode
        if hasattr(self, "media_stack"):
            if mode == "grid":
                self.btn_view_grid.setChecked(True)
                self.btn_view_list.setChecked(False)
                self.btn_view_grid.setIcon(get_colored_svg_icon("grid_view.svg", "#000000", size=14))
                self.btn_view_list.setIcon(get_colored_svg_icon("view_list.svg", "#FFFFFF", size=14))
                self.media_model.set_view_mode("grid")
                self.media_stack.setCurrentWidget(self.media_list)
                self.media_list.setViewMode(QListView.IconMode)
                self.media_list.setResizeMode(QListView.Adjust)
                self.media_list.setMovement(QListView.Static)
                self.media_list.setWordWrap(True)
                self.media_list.setSpacing(8)
                self.media_list.setUniformItemSizes(True)
                self.media_list.setBatchSize(50)
                self.media_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
                self._apply_icon_size(self.icon_size_slider.value())
            else:
                self.btn_view_list.setChecked(True)
                self.btn_view_grid.setChecked(False)
                self.btn_view_list.setIcon(get_colored_svg_icon("view_list.svg", "#000000", size=14))
                self.btn_view_grid.setIcon(get_colored_svg_icon("grid_view.svg", "#FFFFFF", size=14))
                if hasattr(self, "grid_scale_popup"):
                    self.grid_scale_popup.hide()
                self.media_model.set_view_mode("list")
                self.media_stack.setCurrentWidget(self.media_table)
                
                # Ajustar columnas de la tabla 
                self.media_table.setColumnWidth(0, 48)  # Estado / Ícono
                self.media_table.setColumnWidth(1, 240) # Filename
                self.media_table.setColumnWidth(2, 95)  # Descripción (Web) / Tamaño (Local)
                self.media_table.setColumnWidth(3, 110) # Licencia (Web) / Tipo de Archivo (Local)
                self.media_table.setColumnWidth(4, 140) # Duración (Web) / Fecha Modificación (Local)
                self.media_table.setColumnWidth(5, 300) # Origen (Web) / Ruta Completa (Local)
                self.media_table.setColumnWidth(6, 110) # Tipo de Archivo (Web)
                self.media_table.setColumnWidth(7, 150) # Detalles (Web)

        self._update_media_list()
        
        # Persistir la preferencia de modo de vista
        cfg = get_config()
        cfg["editing_media_view_mode"] = mode
        save_config(cfg)

    def _hide_grid_scale_popup(self):
        if hasattr(self, "grid_scale_popup"):
            self.grid_scale_popup.hide()

    def eventFilter(self, obj, event):
        if hasattr(self, "btn_view_grid") and obj == self.btn_view_grid:
            if event.type() == QEvent.Enter:
                if getattr(self, "view_mode", "grid") == "grid":
                    if hasattr(self, "hide_popup_timer"):
                        self.hide_popup_timer.stop()
                    self._show_grid_scale_popup()
            elif event.type() == QEvent.Leave:
                if hasattr(self, "hide_popup_timer"):
                    self.hide_popup_timer.start()
        elif hasattr(self, "grid_scale_popup") and obj == self.grid_scale_popup:
            if event.type() == QEvent.Enter:
                if hasattr(self, "hide_popup_timer"):
                    self.hide_popup_timer.stop()
            elif event.type() == QEvent.Leave:
                if hasattr(self, "hide_popup_timer"):
                    self.hide_popup_timer.start()
        elif hasattr(self, "media_list") and self.media_list and obj == self.media_list.viewport():
            if event.type() == QEvent.Resize:
                if getattr(self, "view_mode", "grid") == "grid":
                    self._recalculate_grid_spacing()
        elif hasattr(self, "audio_controls_widget") and obj == self.audio_controls_widget:
            if event.type() == QEvent.Resize:
                self._recalculate_audio_controls_layout()
        return super().eventFilter(obj, event)

    def _recalculate_audio_controls_layout(self):
        """Oculta el slider de volumen y/o la etiqueta de tiempo cuando la fila de controles
        de audio ('Detalles') se queda sin espacio, para que nada quede cortado — el mismo
        criterio que ya usa PreviewContainerWidget.resizeEvent() para el preview de video."""
        w = self.audio_controls_widget.width()
        if hasattr(self, "volume_control") and self.volume_control:
            self.volume_control.set_slider_visible(w >= 260)
        if hasattr(self, "lbl_time") and self.lbl_time:
            self.lbl_time.setVisible(w >= 190)

    def _recalculate_grid_spacing(self):
        """Calcula el ancho fluido adaptable de las tarjetas para rellenar el 100% del contenedor sin espacio muerto a la derecha."""
        if getattr(self, "view_mode", "list") != "grid":
            return
        if getattr(self, "_is_recalculating_grid", False):
            return
        self._is_recalculating_grid = True

        try:
            viewport_w = self.media_list.viewport().width()
            if viewport_w <= 50:
                return
            
            icon_size = self.icon_size_slider.value() if hasattr(self, "icon_size_slider") else 112
            base_cell_w = icon_size + 32
            cell_h = icon_size + 56
            
            spacing = 4
            # Ancho efectivo reservado para columnas (considerando márgenes laterales)
            avail_w = max(10, viewport_w - (spacing * 2))
            
            # Número exacto de columnas que caben confortablemente
            num_cols = max(1, avail_w // base_cell_w)
            
            # Ancho fluido exacto por celda
            fluid_cell_w = avail_w // num_cols
            
            # Ajuste de espaciado para absorber residuos de división entera
            leftover = avail_w - (fluid_cell_w * num_cols)
            final_spacing = spacing + (leftover // (num_cols + 1))
            
            grid_sz = QSize(fluid_cell_w, cell_h)
            self.media_list.setSpacing(max(1, final_spacing))
            self.media_list.setGridSize(grid_sz)
            
            if hasattr(self, "media_model"):
                self.media_model.set_view_mode("grid", grid_size_hint=grid_sz)
            
            self.media_list.doItemsLayout()
        finally:
            self._is_recalculating_grid = False

    def _show_grid_scale_popup(self):
        if hasattr(self, "grid_scale_popup") and hasattr(self, "btn_view_grid"):
            self.grid_scale_popup.adjustSize()
            popup_w = self.grid_scale_popup.width() if self.grid_scale_popup.width() > 0 else 90
            
            btn_global_pos = self.btn_view_grid.mapToGlobal(QPoint(0, 0))
            btn_w = self.btn_view_grid.width()
            btn_h = self.btn_view_grid.height()
            
            center_x = btn_global_pos.x() + (btn_w // 2)
            popup_x = center_x - (popup_w // 2)
            # Solapar ligeramente el popup sobre el botón (-2 px) para asegurar hitbox continuo
            popup_y = btn_global_pos.y() + btn_h - 2
            
            self.grid_scale_popup.move(QPoint(popup_x, popup_y))
            self.grid_scale_popup.show()
            self.grid_scale_popup.raise_()

    def _on_icon_size_changed(self, val: int):
        if self.view_mode == "grid":
            self.media_list.setUpdatesEnabled(False)
            try:
                self._apply_icon_size(val)
                self.media_list.doItemsLayout()
            finally:
                self.media_list.setUpdatesEnabled(True)
        
        # Reiniciar el temporizador de debounce para persistir el tamaño
        self._icon_size_save_timer.start()

    def _save_icon_size_to_config(self):
        """Persiste el tamaño de cuadrícula al archivo de configuración (llamado con debounce)."""
        val = self.icon_size_slider.value()
        cfg = get_config()
        cfg["editing_media_icon_size"] = val
        save_config(cfg)

    def _on_splitter_moved(self, pos, index):
        """Reinicia el temporizador de debounce al mover el splitter."""
        self._splitter_save_timer.start()

    def _save_splitter_sizes_to_config(self):
        """Persiste los tamaños del splitter al archivo de configuración (llamado con debounce)."""
        cfg = get_config()
        cfg["editing_media_splitter_sizes"] = self.splitter.sizes()
        save_config(cfg)

    def _apply_icon_size(self, size: int):
        self.media_list.setIconSize(QSize(size, size))
        cell_w = size + 32
        cell_h = size + 56
        grid_sz = QSize(cell_w, cell_h)
        self.media_list.setGridSize(grid_sz)
        if hasattr(self, "media_model"):
            self.media_model.set_view_mode("grid", grid_size_hint=grid_sz)

        self._recalculate_grid_spacing()

    def _on_thumbnail_loaded(self, file_path: str, thumb_path: str):
        # La actualización de la miniatura en la lista se maneja directamente en
        # MediaTableModel; aquí solo se refresca la carátula del panel de audio si el
        # archivo que terminó de procesarse es el que está sonando ahora mismo.
        if hasattr(self, "current_playing_path") and self.current_playing_path == file_path:
            if hasattr(self, "lbl_cover_art") and hasattr(self, "current_playing_type") and self.current_playing_type == "audio":
                pix = QPixmap(thumb_path).scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.lbl_cover_art.setPixmap(pix)



    def load_labels(self):
        """Carga las etiquetas configuradas en la aplicación en el QComboBox de etiquetas con círculos de color."""
        if not hasattr(self, "combo_tags"):
            return
        from gui.styles import create_colored_circle_icon, update_label_combobox_style
        self.combo_tags.blockSignals(True)
        current_text = self.combo_tags.currentText()
        self.combo_tags.clear()
        self.combo_tags.addItem(self.tr("Etiqueta"), "")
        
        from core.utils.config_manager import get_config
        from PySide6.QtGui import QColor
        config = get_config()
        labels = config.get("labels", [])
        for label in labels:
            name = label.get("name", "")
            path = label.get("path", "")
            color = label.get("color", "#B9E640")
            idx = self.combo_tags.count()
            icon = create_colored_circle_icon(color, size=12)
            self.combo_tags.addItem(icon, name, path)
            self.combo_tags.setItemData(idx, color, Qt.UserRole + 1)
            self.combo_tags.setItemData(idx, QColor(color), Qt.ForegroundRole)

        idx = self.combo_tags.findText(current_text)
        if idx >= 0:
            self.combo_tags.setCurrentIndex(idx)
        else:
            self.combo_tags.setCurrentIndex(0)

        self.combo_tags.blockSignals(False)
        update_label_combobox_style(self.combo_tags)

    def _on_label_combo_changed(self, index):
        from gui.styles import update_label_combobox_style
        update_label_combobox_style(self.combo_tags)

        label_name = self.combo_tags.itemText(index) if index > 0 else None
        self.last_selected_web_label = label_name

        item_data = self._get_current_media_data()
        if item_data:
            item_data["selected_label"] = label_name
            # Notificar al modelo que hubo un cambio si se desea
            idx = self._get_current_media_item()
            if idx and idx.isValid():
                self.media_model.dataChanged.emit(idx, idx, [])

    def _on_global_sort_requested(self, column: int, is_ascending: bool):
        """Maneja la petición de ordenamiento global originada por clic en las cabeceras del modelo MVC."""
        is_online = getattr(self.media_model, "_is_online_mode", False)
        if is_online:
            mapping = {
                1: "nombre",
                2: "nombre",
                3: "license",
                4: "duration",
                5: "nombre",
                6: "tipo",
                7: "nombre"
            }
        else:
            mapping = {
                1: "nombre",
                2: "size",
                3: "tipo",
                4: "mtime",
                5: "ruta",
                6: "tipo",
                7: "nombre"
            }
        new_sort_by = mapping.get(column, "nombre")
        
        if new_sort_by != getattr(self, "sort_by", "nombre"):
            # Al seleccionar Tamaño o Fecha por primera vez, ordenar de mayor a menor (descendente)
            if new_sort_by in ("size", "mtime"):
                self.sort_ascending = False
            else:
                self.sort_ascending = True
            self.sort_by = new_sort_by
        else:
            self.sort_ascending = is_ascending
        
        # Dispara la actualización completa (donde se ordenan los 10,000 items locales)
        if hasattr(self, "_update_media_list"):
            self._update_media_list()

    def _on_local_search_timer_timeout(self):
        """Callback cuando vence el timer de retardo (250ms) para búsquedas locales."""
        try:
            self._apply_active_filters_fast()
        finally:
            if hasattr(self, "search_spinner"):
                self.search_spinner.stop()

    def _get_current_media_item(self):
        """Devuelve el QModelIndex del ítem actualmente seleccionado."""
        if getattr(self, "view_mode", "grid") == "list" and hasattr(self, "media_table"):
            indexes = self.media_table.selectedIndexes()
            return indexes[0] if indexes else None
        elif hasattr(self, "media_list"):
            indexes = self.media_list.selectedIndexes()
            return indexes[0] if indexes else None
        return None

    def _get_current_media_data(self):
        """Devuelve la estructura dict de datos del elemento actualmente seleccionado."""
        index = self._get_current_media_item()
        if not index:
            return None
        return self.media_model.get_item(index)

    def _on_indexing_started(self):
        if hasattr(self, "lbl_indexed_count"):
            # Bandera en vez de comparar contra el texto ya traducido de la etiqueta:
            # el total final se muestra en el idioma activo y un "in" contra el literal
            # en espanol solo acertaba con la app en espanol.
            self._indexing_done = False
            if not self.lbl_indexed_count.text():
                self.lbl_indexed_count.setText(self.tr("Iniciando indexación..."))

    def _on_indexing_progress(self, count):
        if hasattr(self, "lbl_indexed_count"):
            if not getattr(self, "_indexing_done", False):
                self.lbl_indexed_count.setText(self.tr("Indexando... ({0} encontrados)").format(count))

    def _on_indexing_finished(self, files):
        if hasattr(self, "lbl_indexed_count"):
            self._indexing_done = True
            total = len(files)
            if total == 1:
                self.lbl_indexed_count.setText(self.tr("1 Medio Indexado en Total"))
            else:
                self.lbl_indexed_count.setText(self.tr("{0} Medios Indexados en Total").format(total))
        # Si estamos viendo la raíz de Directorios o de Colecciones (ambas son vistas
        # agregadas que dependen de este mismo indexado en segundo plano), actualizamos
        # automáticamente.
        current_item = self.tree_folders.currentItem()
        if current_item and current_item.data(0, Qt.UserRole).get("tipo") in ("root_physical", "root_virtual"):
            self._update_media_list()

    def showEvent(self, event):
        super().showEvent(event)
        from core.utils.config_manager import get_config, save_config
        config = get_config()
        if not config.get("tutorial_editing_media_seen", False):
            # Usar QTimer para permitir que la UI se renderice antes de mostrar el tutorial
            QTimer.singleShot(500, self.start_tutorial)
            config["tutorial_editing_media_seen"] = True
            save_config(config)

    def start_tutorial(self):
        from gui.widgets.tutorial_overlay import TutorialOverlay
        steps = [
            {
                "title": self.tr("Botón Indexar Carpetas"),
                "desc": self.tr("¡Indexa tus carpetas o archivos favoritos! DowP procesará los metadatos en segundo plano para que la búsqueda sea instantánea."),
                "widgets": [self.btn_add_folder]
            },
            {
                "title": self.tr("Árbol de Fuentes"),
                "desc": self.tr("Revisa tus medios indexados fácilmente, navega por tu disco, y guarda tus carpetas favoritas o colecciones personalizadas."),
                "widgets": [self.tree_folders]
            },
            {
                "title": self.tr("Medios Web"),
                "desc": self.tr("Además, expandiendo la sección 'Medios Web', puedes buscar y descargar sonidos o imágenes directamente de sitios como Freesound y Wikimedia para tus proyectos."),
                "widgets": [self.tree_folders]
            },
            {
                "title": self.tr("Explorador Central"),
                "desc": self.tr("Organiza y busca tus archivos. ¡El secreto aquí es que puedes arrastrar cualquier medio directamente a tus programas favoritos u otras pestañas!"),
                "widgets": [self.media_stack, self.search_input]
            },
            {
                "title": self.tr("Vista Previa y Detalles"),
                "desc": self.tr("Reproduce, visualiza los detalles técnicos de tus archivos y corta segmentos rápidamente para enviarlos a tu editor o guardarlos en disco."),
                "widgets": [self.preview_box, self.info_box]
            },
            {
                "title": self.tr("Ventana de Subclips"),
                "desc": self.tr("Al igual que en el Modo Rápido, con las tijeras puedes realizar múltiples cortes a un mismo medio, arrastrarlos o mandarlos a tu software de edición en un clic."),
                "widgets": [self.preview_box.btn_edit_subclip, self.btn_edit_subclip, self.btn_send_editor]
            }
        ]
        
        main_window = self.window()
        self.tutorial_overlay = TutorialOverlay(main_window, steps)
        self.tutorial_overlay.resize(main_window.size())
        self.tutorial_overlay.show()
