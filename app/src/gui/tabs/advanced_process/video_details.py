# src/gui/tabs/single_process/video_details.py
import os
import requests
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel,
                               QLineEdit, QFrame, QPushButton, QCheckBox,
                               QSizePolicy, QComboBox, QStyledItemDelegate, QGraphicsOpacityEffect, QGridLayout, QStyle, QStyleOptionComboBox, QFileDialog, QMessageBox)
from PySide6.QtCore import Qt, QPropertyAnimation, QParallelAnimationGroup, QEasingCurve, Signal, QThread
from PySide6.QtGui import QPixmap, QImage, QIcon, QFontMetrics, QPainter
from core.logger.logger_manager import logger
from core.utils.paths import get_src_dir
from gui.widgets.mode_selector import ModeSelector
from gui.dialogs.fragment_dialog import FragmentDialog
from gui.styles import get_theme_token
from core.utils.config_manager import get_config
from core.tabs.advanced_process.video_details_logic import download_thumbnail, send_thumbnail_to_image_tools
from core.tabs.advanced_process.fragment_logic import FragmentState
from PySide6.QtSvg import QSvgRenderer

from gui.tabs.advanced_process.video_details_components import (
    ThumbnailLoaderThread,
    RichTextDelegate,
    ResponsiveThumbnail,
    RichComboBox
)
from gui.widgets.combo_box import AutoPopupComboBox

class VideoDetailsWidget(QFrame):
    video_ready = Signal()  # Emitida cuando hay un video válido cargado
    fragments_changed = Signal() # Emitida cuando los fragmentos cambian

    def __init__(self):
        super().__init__()
        self.setObjectName("videoContainer")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(225)
        self.init_ui()

    def init_ui(self):
        self.current_video_url = ""
        self.selected_fragments = [] # Lista de tuplas (start_ms, end_ms, suffix)
        self.fragment_mode = None
        # Cache en memoria de miniaturas ya descargadas (url -> QPixmap), para no
        # volver a pedirlas por red al cambiar entre items ya analizados.
        self._thumbnail_pixmap_cache = {}
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 6, 10, 6)
        main_layout.setSpacing(8)

        # Contenedor para la columna izquierda (Miniatura + Controles)
        # Esto permite limitar el ancho de todo el bloque
        self.left_column_widget = QWidget()
        self.left_column_widget.setMaximumWidth(600)
        col1_layout = QVBoxLayout(self.left_column_widget)
        col1_layout.setContentsMargins(0, 0, 0, 0)
        col1_layout.setSpacing(6)
        
        # Thumbnail Responsivo
        self.thumb_container = ResponsiveThumbnail()
        self.thumb_container.setMaximumWidth(600) # Aumentamos el máximo para permitir escalado en 4K
        col1_layout.addWidget(self.thumb_container)

        # Secondary Buttons
        btns_layout = QHBoxLayout()
        btns_layout.setSpacing(10)
        self.btn_download_thumb = QPushButton(self.tr("Guardar imagen"))
        self.btn_download_thumb.setObjectName("secondaryButton")
        self.btn_download_thumb.setEnabled(False)
        self.btn_download_thumb.clicked.connect(lambda: download_thumbnail(self))
        self.btn_send_hi = QPushButton(self.tr("Enviar a E.I"))
        self.btn_send_hi.setObjectName("secondaryButton")
        self.btn_send_hi.setEnabled(False)
        self.btn_send_hi.clicked.connect(lambda: send_thumbnail_to_image_tools(self))

        btns_layout.addWidget(self.btn_download_thumb)
        btns_layout.addWidget(self.btn_send_hi)
        col1_layout.addLayout(btns_layout)

        # Checkbox "Descargar junto con el medio": texto propio del checkbox (no un
        # QLabel aparte) - el tema ya define QCheckBox { spacing: 8px } para el hueco
        # entre el indicador y su texto.
        toggle_layout = QHBoxLayout()
        self.chk_download_with_video = QCheckBox(self.tr("Descargar junto con el medio"))
        self.chk_download_with_video.setCursor(Qt.PointingHandCursor)

        toggle_layout.addWidget(self.chk_download_with_video)
        toggle_layout.addStretch()

        col1_layout.addLayout(toggle_layout)
        col1_layout.addStretch()
        
        # Añadir el widget de columna al área izquierda
        left_area = QHBoxLayout()
        left_area.setContentsMargins(0, 0, 0, 0)
        left_area.addWidget(self.left_column_widget)

        # === RIGHT AREA ===
        right_area = QVBoxLayout()
        right_area.setContentsMargins(0, 0, 0, 0)
        right_area.setSpacing(5)
        
        # Title + Tags layout
        title_layout = QHBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(8)

        self.title_input = QLineEdit(self.tr("Título del Video"))
        self.title_input.setObjectName("titleInput")
        self.title_input.setPlaceholderText(self.tr("El título aparecerá aquí"))
        self.title_input.setLayoutDirection(Qt.LeftToRight)
        
        self.combo_tags = AutoPopupComboBox()
        self.combo_tags.setObjectName("tagsComboBox")
        self.combo_tags.setPlaceholderText(self.tr("Etiqueta"))
        
        title_layout.addWidget(self.title_input, 1)
        title_layout.addWidget(self.combo_tags)
        
        right_area.addLayout(title_layout)

        # Mode Selector
        self.mode_selector = ModeSelector()
        right_area.addWidget(self.mode_selector)

        # Dropdowns for Video and Audio
        menus_layout = QVBoxLayout()
        menus_layout.setSpacing(8)

        # Contenedores para animación
        self.video_container = QWidget()
        video_layout = QVBoxLayout(self.video_container)
        video_layout.setContentsMargins(0, 0, 0, 0)
        self.lbl_video_quality = QLabel(self.tr("Calidad de Video:"))
        self.lbl_video_quality.setObjectName("menuLabel")
        self.combo_video = RichComboBox()
        self.combo_video.setItemDelegate(RichTextDelegate(self.combo_video))
        self.combo_video.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.combo_video.addItem(self.tr("Seleccionar video..."))
        video_layout.addWidget(self.lbl_video_quality)
        video_layout.addWidget(self.combo_video)
        
        self.audio_container = QWidget()
        audio_layout = QVBoxLayout(self.audio_container)
        audio_layout.setContentsMargins(0, 0, 0, 0)
        audio_layout.setSpacing(5)
        
        self.lbl_audio_quality = QLabel(self.tr("Calidad de Audio:"))
        self.lbl_audio_quality.setObjectName("menuLabel")
        self.combo_audio = RichComboBox()
        self.combo_audio.setItemDelegate(RichTextDelegate(self.combo_audio))
        self.combo_audio.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.combo_audio.addItem(self.tr("Seleccionar audio..."))
        audio_layout.addWidget(self.lbl_audio_quality)
        audio_layout.addWidget(self.combo_audio)
        
        self.col_audio_source = QWidget()
        self.col_audio_source.setObjectName("audioSourceContainer")
        col_source_layout = QVBoxLayout(self.col_audio_source)
        col_source_layout.setContentsMargins(0, 0, 0, 0)
        col_source_layout.setSpacing(5)
        self.lbl_audio_source = QLabel(self.tr("Extraer de:"))
        self.lbl_audio_source.setObjectName("menuLabel")
        self.combo_audio_source = RichComboBox()
        self.combo_audio_source.setItemDelegate(RichTextDelegate(self.combo_audio_source))
        self.combo_audio_source.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        col_source_layout.addWidget(self.lbl_audio_source)
        col_source_layout.addWidget(self.combo_audio_source)

        self.col_audio_source.hide()
        audio_layout.addWidget(self.col_audio_source)

        menus_layout.addWidget(self.video_container)
        menus_layout.addWidget(self.audio_container)
        
        right_area.addLayout(menus_layout)
        right_area.addStretch()

        # Connections
        self.mode_selector.mode_changed.connect(self.on_mode_changed)
        self.combo_video.currentIndexChanged.connect(self._on_video_changed)
        self.combo_audio_source.currentIndexChanged.connect(self._on_audio_source_changed)

        # Internal cache for audio streams
        self._audio_streams_cache = []

        main_layout.addLayout(left_area)
        main_layout.addLayout(right_area, 1) # La sección de la derecha ahora se expande para llenar el espacio

    def _on_audio_source_changed(self, index):
        """Al cambiar la fuente de extracción de audio (Ninguno vs Combinado/Multi-Idioma)."""
        # Solo aplica en modo Solo Audio
        if self.mode_selector.current_mode() != self.tr("Solo Audio"):
            return
            
        data = self.combo_audio_source.currentData()
        
        # Si es Ninguno (DASH normal)
        if not data or data.get('id') == 'none':
            self.combo_audio.setEnabled(True)
            self._restore_audio_menu()
            return
            
        # Si es Multi-Idioma
        if data.get('is_multi'):
            self.combo_audio.setEnabled(True)
            self._restore_audio_menu(data.get('internal_audios'))
            return
            
        # Si es Combinado
        if data.get('is_combined'):
            self.combo_audio.blockSignals(True)
            self.combo_audio.clear()
            audio_virtual = data.copy()
            audio_virtual['label'] = self.tr("Audio del flujo de video")
            self.combo_audio.addItem(audio_virtual['label'], userData=audio_virtual)
            self.combo_audio.setEnabled(False)
            self.combo_audio.blockSignals(False)
            return

    def _on_video_changed(self, index):
        """Al cambiar el video, filtramos audios compatibles."""
        # Si estamos en modo Solo Audio, la calidad de audio se maneja por combo_audio_source, no combo_video
        if self.mode_selector.current_mode() == self.tr("Solo Audio"):
            return
            
        data = self.combo_video.currentData()
        if not data:
            return

        # 1. Si es multi-idioma (caso MrBeast), mostramos sus audios internos
        if data.get('is_multi'):
            self.combo_audio.setEnabled(True)
            self._restore_audio_menu(data.get('internal_audios'))
            return

        # 2. Si el video es combinado (y no es multi-idioma), el audio es el mismo flujo
        if data.get('is_combined'):
            self.combo_audio.blockSignals(True)
            self.combo_audio.clear()
            # Creamos una opción virtual de audio basada en el video combinado
            # Esto permite que la lógica de descarga detecte 'has_video' y aplique la extracción
            audio_virtual = data.copy()
            audio_virtual['label'] = self.tr("Audio del flujo de video")
            self.combo_audio.addItem(audio_virtual['label'], userData=audio_virtual)
            self.combo_audio.setEnabled(False) # Lo dejamos deshabilitado para que no cambien, pero con DATA
            self.combo_audio.blockSignals(False)
            return

        # 3. Caso normal: video DASH, mostramos todos los audios separados del cache
        self.combo_audio.setEnabled(True)
        self._restore_audio_menu()

    def _restore_audio_menu(self, specific_streams=None):
        """Restaura los audios desde el cache o desde una lista específica (para Multi-Idioma)."""
        self.combo_audio.blockSignals(True)
        curr_audio = self.combo_audio.currentData()
        self.combo_audio.clear()
        
        # Usar audios específicos si se proporcionan (casos multi-idioma) 
        # o el cache general (casos estándar)
        streams = specific_streams if specific_streams is not None else self._audio_streams_cache
        
        if streams:
            for stream in streams:
                self.combo_audio.addItem(stream['label'], userData=stream)
            
            # Intentar restaurar selección previa si es posible
            if curr_audio:
                for i in range(self.combo_audio.count()):
                    if self.combo_audio.itemData(i) == curr_audio:
                        self.combo_audio.setCurrentIndex(i)
                        break
        else:
            self.combo_audio.addItem(self.tr("Sin audio disponible"))

        self.combo_audio.blockSignals(False)

    def animate_menu_visibility(self, widget, show):
        """
        Anima la opacidad de un widget para mostrarlo u ocultarlo.
        Evita colisiones de animaciones previas.
        """
        # Rápido retorno si ya está mostrado y no hay animación de ocultación activa
        if show and not widget.isHidden():
            eff = widget.graphicsEffect()
            if not eff or (isinstance(eff, QGraphicsOpacityEffect) and eff.opacity() > 0.95):
                if eff:
                    widget.setGraphicsEffect(None)
                widget.show()
                if hasattr(widget, "_visibility_anim") and widget._visibility_anim:
                    widget._visibility_anim.stop()
                    widget._visibility_anim.deleteLater()
                    widget._visibility_anim = None
                return

        # 1. Asegurar que el efecto existe y es persistente
        eff = widget.graphicsEffect()
        if not isinstance(eff, QGraphicsOpacityEffect):
            eff = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(eff)
        
        # 2. Detener cualquier animación previa en este widget
        if hasattr(widget, "_visibility_anim") and widget._visibility_anim:
            widget._visibility_anim.stop()
            widget._visibility_anim.deleteLater()
            widget._visibility_anim = None

        # 3. Configurar nueva animación
        anim = QPropertyAnimation(eff, b"opacity")
        anim.setDuration(250) # Un poco más rápido para mayor respuesta
        anim.setStartValue(eff.opacity())
        anim.setEndValue(1.0 if show else 0.0)
        anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        
        # Guardar referencia para control de concurrencia
        widget._visibility_anim = anim
        
        if show:
            widget.show()
            # Al mostrar, al finalizar la animación removemos el efecto para evitar bugs de pintado
            def on_show_finished():
                if hasattr(widget, "_visibility_anim") and widget._visibility_anim == anim:
                    if eff.opacity() > 0.95:
                        widget.setGraphicsEffect(None)
            anim.finished.connect(on_show_finished)
        else:
            # Definir callback seguro: solo oculta si esta es la última animación activa
            # y el objetivo sigue siendo ocultar.
            def on_finished():
                if hasattr(widget, "_visibility_anim") and widget._visibility_anim == anim:
                    if eff.opacity() < 0.05: # Umbral de seguridad
                        widget.hide()
            anim.finished.connect(on_finished)
            
        anim.start()

    def on_mode_changed(self, mode_text):
        """Maneja el cambio de modo (Video+Audio, Audio, Video) con animaciones limpias."""
        solo_audio = self.tr("Solo Audio")
        solo_video = self.tr("Solo Video")
        
        has_spec = getattr(self, "_has_special_audio_sources", False)
        
        if mode_text == solo_audio:
            self.animate_menu_visibility(self.video_container, False)
            self.animate_menu_visibility(self.audio_container, True)
            if has_spec:
                self.col_audio_source.show()
            else:
                self.col_audio_source.hide()
            # Actualizar menú de audio según el origen de audio seleccionado
            self._on_audio_source_changed(self.combo_audio_source.currentIndex())
        elif mode_text == solo_video:
            self.animate_menu_visibility(self.video_container, True)
            self.animate_menu_visibility(self.audio_container, False)
            self.col_audio_source.hide()
            # Resetear selección al cambiar de modo
            self.combo_audio_source.blockSignals(True)
            self.combo_audio_source.setCurrentIndex(0)
            self.combo_audio_source.blockSignals(False)
        else: # Video + Audio
            self.animate_menu_visibility(self.video_container, True)
            self.animate_menu_visibility(self.audio_container, True)
            self.col_audio_source.hide()
            # Resetear selección al cambiar de modo
            self.combo_audio_source.blockSignals(True)
            self.combo_audio_source.setCurrentIndex(0)
            self.combo_audio_source.blockSignals(False)
            # Actualizar menú de audio según el video seleccionado
            self._on_video_changed(self.combo_video.currentIndex())

    def update_info(self, data):
        # Extraer metadatos del primer video si la URL devuelve una lista
        # Esto previene que la UI se quede sin formatos (ej. crash con id 'default')
        if data.get('_type') == 'playlist' and 'entries' in data and data['entries']:
            first_entry = data['entries'][0]
            if not data.get('formats'):
                data['formats'] = first_entry.get('formats', [])
            if not data.get('thumbnail'):
                data['thumbnail'] = first_entry.get('thumbnail')
            if not data.get('duration'):
                data['duration'] = first_entry.get('duration')
            if not data.get('fps'):
                data['fps'] = first_entry.get('fps')
            if not data.get('language'):
                data['language'] = first_entry.get('language')
            
            # Forzar explícitamente a Falso para que el descargador respete la pestaña "Single Process"
            data['is_playlist'] = False

        self.current_video_url = data.get('original_url', data.get('webpage_url', ''))
        self.current_duration = data.get('duration', 0)
        from core.ytdlp_logic.media_search import is_live_now
        self.current_is_live = is_live_now(data)
        self.current_fps = data.get('fps', 30)
        if not self.current_fps:
            self.current_fps = 30
        
        self.stream_url = ""
        formats = data.get('formats', [])
        self.original_lang = data.get('language', None)  # Idioma original del video

        from core.utils.format_manager import FormatManager
        
        fmt_22 = None
        fmt_18 = None
        best_combined = None
        any_combined = None
        best_video_only = None

        # Priorizar resoluciones moderadas para la vista previa (carga más rápida)
        for f in formats:
            fmt_type = FormatManager.classify_format(f)
            
            if fmt_type not in ('VIDEO', 'VIDEO_ONLY'):
                continue

            fid = f.get('format_id', '')
            is_dub = 'dub' in str(f.get('format_note', '')).lower()
            fmt_lang = f.get('language', None)
            
            is_original = False
            if fmt_lang is None and self.original_lang is None:
                is_original = True
            elif fmt_lang and self.original_lang:
                is_original = fmt_lang.lower() == self.original_lang.lower()
            is_original = is_original and not is_dub
            
            h = f.get('height') or 0

            if fmt_type == 'VIDEO':
                if fid == '22' and is_original:
                    fmt_22 = f
                elif fid == '18' and is_original:
                    fmt_18 = f
                elif is_original:
                    # Preferimos algo entre 360 y 720 para vista previa
                    if not best_combined or (360 <= h <= 720 and (best_combined.get('height') or 0) > 720):
                        best_combined = f
                else:
                    if not any_combined or (360 <= h <= 720 and (any_combined.get('height') or 0) > 720):
                        any_combined = f
            elif fmt_type == 'VIDEO_ONLY':
                if not best_video_only or (360 <= h <= 720 and (best_video_only.get('height') or 0) > 720):
                    best_video_only = f

        # Orden de prioridad para la vista previa del reproductor
        final_format = fmt_18 or fmt_22 or best_combined or any_combined or best_video_only
        self.stream_url = final_format.get('url', '') if final_format else ''

        if self.current_video_url:
            self.video_ready.emit()
            self.btn_download_thumb.setEnabled(True)
            self.btn_send_hi.setEnabled(True)
        self.title_input.setText(data.get('title', self.tr('Título Desconocido')))
        self.title_input.setCursorPosition(0)
        
        # Duration
        duration_sec = data.get('duration')
        if duration_sec:
            mins, secs = divmod(int(duration_sec), 60)
            hours, mins = divmod(mins, 60)
            duration_str = f"{hours:02}:{mins:02}:{secs:02}" if hours > 0 else f"{mins:02}:{secs:02}"
            self.thumb_container.set_duration(duration_str)
        else:
            self.thumb_container.set_duration(None)

        # Thumbnail
        thumbnail_url = data.get('thumbnail')
        if thumbnail_url:
            self.load_thumbnail(thumbnail_url)
        else:
            # Detectar si es audio o video para poner el icono de respaldo
            from core.utils.format_manager import FormatManager
            is_audio_only = True
            for f in formats:
                fmt_type = FormatManager.classify_format(f)
                if fmt_type in ('VIDEO', 'VIDEO_ONLY'):
                    is_audio_only = False
                    break
            
            self._set_fallback_icon(is_audio_only)

    def load_thumbnail(self, url, fallback_urls=None):
        # Si ya descargamos esta miniatura antes (ej. volver a un item ya
        # analizado), reusar el pixmap en memoria en vez de pedirla por red.
        cached_pixmap = self._thumbnail_pixmap_cache.get(url)
        if cached_pixmap is not None:
            self.thumb_container.set_pixmap(cached_pixmap)
            self.btn_download_thumb.setEnabled(True)
            return

        self.thumb_container.set_text(self.tr("Cargando vista previa..."))
        if not hasattr(self, '_thumb_threads'):
            self._thumb_threads = []

        thread = ThumbnailLoaderThread(url, fallback_urls=fallback_urls)
        self._thumb_threads.append(thread)

        def cleanup(content, error):
            if thread in getattr(self, '_thumb_threads', []):
                self._thumb_threads.remove(thread)
            self._on_thumbnail_loaded(content, error, cache_key=url)

        thread.finished.connect(cleanup)
        thread.start()

    def _on_thumbnail_loaded(self, content, error, cache_key=None):
        if error:
            logger.error(f"VideoDetails: Failed to load thumbnail: {error}")
            self._set_fallback_icon(False)
            return

        try:
            image = QImage.fromData(content)
            pixmap = QPixmap.fromImage(image)
            self.thumb_container.set_pixmap(pixmap)
            self.btn_download_thumb.setEnabled(True)
            if cache_key:
                self._thumbnail_pixmap_cache[cache_key] = pixmap
                # Límite simple para no crecer sin control en playlists enormes
                if len(self._thumbnail_pixmap_cache) > 300:
                    oldest_key = next(iter(self._thumbnail_pixmap_cache))
                    del self._thumbnail_pixmap_cache[oldest_key]
        except Exception as e:
            logger.error(f"VideoDetails: Error processing thumbnail image: {e}")
            self._set_fallback_icon(False)

    def _set_fallback_icon(self, is_audio=False):
        icon_name = "music_note.svg" if is_audio else "movie.svg"
        icon_path = os.path.join(get_src_dir(), "assets", "icons", "svg", icon_name)
        
        if os.path.exists(icon_path):
            pixmap = QIcon(icon_path).pixmap(128, 128)
            self.thumb_container.set_pixmap(pixmap)
        else:
            self.thumb_container.set_text("🎵" if is_audio else "🎞️")

    def populate_menus(self, video_streams, audio_streams, has_audio_source=True):
        # Bloquear señales temporalmente para evitar recursión al llenar
        self.combo_video.blockSignals(True)
        self.combo_audio.blockSignals(True)
        
        # Limpiar opciones anteriores
        self.combo_video.clear()
        self.combo_audio.clear()
        
        # Cache de audios para restauración dinámica
        self._audio_streams_cache = audio_streams
        
        from core.utils.config_manager import get_config
        config = get_config()
        adobe_compat = config.get("adobe_compat_default", True)
        
        # ── Controlar ModeSelector según disponibilidad ──
        has_video = bool(video_streams)
        has_audio = has_audio_source or bool(audio_streams)
        
        if has_video and has_audio:
            # Ambos disponibles → todo habilitado y resetear a Video + Audio
            self.mode_selector.btn_video_audio.setEnabled(True)
            self.mode_selector.btn_audio.setEnabled(True)
            self.mode_selector.btn_video.setEnabled(True)
            self.mode_selector.btn_video_audio.click()
        elif not has_audio and has_video:
            # Solo hay video → deshabilitar el resto y forzar Solo Video
            self.mode_selector.btn_video_audio.setEnabled(False)
            self.mode_selector.btn_audio.setEnabled(False)
            self.mode_selector.btn_video.setEnabled(True)
            self.mode_selector.btn_video.click()
            logger.info("FormatManager: Sin fuentes de audio. 'Solo Audio' deshabilitado.")
        elif has_audio and not has_video:
            # Solo hay audio → forzar Solo Audio y deshabilitar los otros
            self.mode_selector.btn_video_audio.setEnabled(False)
            self.mode_selector.btn_video.setEnabled(False)
            self.mode_selector.btn_audio.setEnabled(True)
            self.mode_selector.btn_audio.click()
            logger.info("FormatManager: Solo hay audio. Forzando modo 'Solo Audio'.")
        
        # ── Llenar Video ──
        best_video_idx = 0
        found_comp = False
        if video_streams:
            for i, stream in enumerate(video_streams):
                self.combo_video.addItem(stream['label'], userData=stream)
                if adobe_compat and not found_comp and "✨" in stream.get('label', ''):
                    best_video_idx = i
                    found_comp = True
        else:
            self.combo_video.addItem(self.tr("No hay video disponible"))

        if self.combo_video.count() > 0:
            self.combo_video.setCurrentIndex(best_video_idx)
            
        # Llenar combo_audio_source (Origen de audio alternativo)
        self.combo_audio_source.blockSignals(True)
        self.combo_audio_source.clear()
        
        self.combo_audio_source.addItem(self.tr("Ninguno (Flujos separados)"), userData={'id': 'none'})
        
        has_special = False
        if video_streams:
            for stream in video_streams:
                if stream.get('is_combined') or stream.get('is_multi'):
                    self.combo_audio_source.addItem(stream['label'], userData=stream)
                    has_special = True
                    
        self._has_special_audio_sources = has_special
        self.combo_audio_source.setCurrentIndex(0)
        self.combo_audio_source.blockSignals(False)

        # Llenar Audio inicial
        self._restore_audio_menu()
        
        # ── Selección de Audio por defecto ──
        # Prioridad: 1. Original+Adobe, 2. Original, 3. Adobe Global, 4. Fallback (0)
        best_audio_idx = 0
        if audio_streams:
            orig_l = (getattr(self, 'original_lang', None) or "").lower().strip()
            
            # 1. Buscar Original + Adobe
            found_p1 = False
            if orig_l:
                for i, stream in enumerate(audio_streams):
                    lang_s = (stream.get('lang') or "").lower().strip()
                    if lang_s == orig_l and "✨" in stream.get('label', ''):
                        best_audio_idx = i
                        found_p1 = True
                        break
            
            # 2. Si no, buscar solo Original (el mejor)
            if not found_p1 and orig_l:
                for i, stream in enumerate(audio_streams):
                    lang_s = (stream.get('lang') or "").lower().strip()
                    if lang_s == orig_l:
                        best_audio_idx = i
                        found_p1 = True
                        break
            
            # 3. Si no hay original o no se encontró, buscar Adobe Global
            if not found_p1 and adobe_compat:
                for i, stream in enumerate(audio_streams):
                    if "✨" in stream.get('label', ''):
                        best_audio_idx = i
                        break

        if self.combo_audio.count() > 0:
            self.combo_audio.setCurrentIndex(best_audio_idx)
            
        self.combo_video.blockSignals(False)
        self.combo_audio.blockSignals(False)
        
        # Trigger inicial para ajustar el menú de audio según el video por defecto
        self._on_video_changed(self.combo_video.currentIndex())

        # Actualizar visibilidad de columna origen de audio en base al modo actual
        curr_mode = self.mode_selector.current_mode()
        if curr_mode == self.tr("Solo Audio") and self._has_special_audio_sources:
            self.col_audio_source.show()
        else:
            self.col_audio_source.hide()

    def open_fragments_dialog(self, btn_fragments=None):
        """Abre el diálogo de fragmentos. btn_fragments se pasa desde fuera para actualizar su texto."""
        if getattr(self, "current_is_live", False):
            # Un directo en curso no tiene duración ni rangos fijos (ver conversación).
            from gui.dialogs.dialogs import show_info
            show_info(self, self.tr("Directo en curso"),
                      self.tr("Los directos en curso no se pueden recortar. Puedes descargarlo "
                              "completo; la descarga seguirá hasta que termine la transmisión o la canceles."))
            return
        pixmap = self.thumb_container._pixmap
        dialog = FragmentDialog(
            self,
            stream_url=getattr(self, 'stream_url', ''),
            thumbnail_pixmap=pixmap,
            duration=self.current_duration,
            fps=self.current_fps,
            source_url=getattr(self, 'current_video_url', ''),  # URL de la página original
        )
        # Restaurar fragmentos previos
        dialog.fragments = self.selected_fragments.copy()
        
        # Restaurar modo previo
        if self.fragment_mode == FragmentState.PRECISE:
            dialog.rb_precise.setChecked(True)
        elif self.fragment_mode == FragmentState.DOWNLOAD_THEN_CUT:
            dialog.rb_download.setChecked(True)
        elif self.fragment_mode == FragmentState.KEEP_FULL:
            dialog.rb_keep.setChecked(True)
        # Si fragment_mode es None, no seleccionamos ninguno
            
        dialog._rebuild_list()

        result = dialog.exec()
        main_win = self.window()
        if main_win:
            main_win.activateWindow()
            main_win.raise_()

        if result:
            data = dialog.get_fragments_data()
            self.selected_fragments = data["fragments"]
            self.fragment_mode = data["mode"]
            
            # Icono Verde si hay fragmentos, Rojo si no
            if self.selected_fragments:
                self.thumb_container.set_cut_status("saved")
            else:
                self.thumb_container.set_cut_status("normal")
                
            if btn_fragments is not None:
                if self.selected_fragments:
                    btn_fragments.setText(f"Fragmentos ({len(self.selected_fragments)})")
                else:
                    btn_fragments.setText(self.tr("Fragmentos"))
            
            self.fragments_changed.emit()
        else:
            # Cancelado. Si hubo cambios o hay fragmentos colocados pero no guardados -> Amarillo
            if dialog.is_modified or dialog.fragments:
                self.thumb_container.set_cut_status("unsaved")
            # Si no hay nada y canceló, vuelve a rojo (o se mantiene)
            if not dialog.fragments:
                self.thumb_container.set_cut_status("normal")

    def reset_ui(self):
        """Limpia todos los datos de la UI."""
        self.current_is_live = False
        self.title_input.clear()
        self.combo_video.clear()
        self.combo_video.addItem(self.tr("Seleccionar video..."))
        self.combo_audio.clear()
        self.combo_audio.addItem(self.tr("Seleccionar audio..."))
        self.thumb_container.set_text(self.tr("Sin Vista Previa"))
        self.thumb_container.set_duration(None)
        self.combo_video.setCurrentIndex(0)
        self.combo_audio.setCurrentIndex(0)
        
        # Limpiar flags de estado
        self.fragment_mode = None
        self.selected_fragments = []
        self.fragments_changed.emit()
        self.thumb_container.set_cut_status("normal")
        self.is_modified = False # Resetear estado tras nueva carga
        self.btn_download_thumb.setEnabled(False)
        self.btn_send_hi.setEnabled(False)
        self.stream_url = ""

    def load_labels(self):
        """Carga las etiquetas configuradas en la aplicación en el combo de etiquetas con círculos de color."""
        from gui.styles import create_colored_circle_icon, update_label_combobox_style
        self.combo_tags.blockSignals(True)
        current_text = self.combo_tags.currentText()
        self.combo_tags.clear()
        self.combo_tags.addItem(self.tr("Etiqueta"), "")
        
        config = get_config()
        labels = config.get("labels", [])
        for label in labels:
            name = label["name"]
            path = label["path"]
            color = label.get("color", "#B9E640")
            
            idx = self.combo_tags.count()
            icon = create_colored_circle_icon(color, size=12)
            self.combo_tags.addItem(icon, name, path)
            
            # Guardar color en user data y ForegroundRole
            from PySide6.QtGui import QColor
            self.combo_tags.setItemData(idx, color, Qt.UserRole + 1)
            self.combo_tags.setItemData(idx, QColor(color), Qt.ForegroundRole)
            
        # Intentar restaurar selección si aún existe
        idx = self.combo_tags.findText(current_text)
        if idx >= 0:
            self.combo_tags.setCurrentIndex(idx)
        else:
            self.combo_tags.setCurrentIndex(0)
            
        self.combo_tags.blockSignals(False)
        self.update_combo_style()

    def update_combo_style(self):
        """Actualiza el color de texto del combo según la etiqueta seleccionada."""
        from gui.styles import update_label_combobox_style
        update_label_combobox_style(self.combo_tags)
