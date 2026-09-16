# src/gui/tabs/editing_media/preview_panel.py
import os
from PySide6.QtWidgets import (
    QFrame, QLabel, QVBoxLayout, QHBoxLayout, QSizePolicy, QWidget, QPushButton, QSlider,
    QGraphicsScene, QGraphicsView
)
from PySide6.QtCore import Qt, QUrl, QSize, QSizeF, QRectF
from PySide6.QtGui import QPixmap, QIcon, QPainter, QColor, QImage

from core.logger.logger_manager import logger
from core.utils.paths import get_src_dir
from core.tabs.editing_media.editing_media_logic import RAW_EXTS
from gui.styles import (
    get_theme_token,
    apply_player_play_button_style,
    apply_player_loop_button_style,
    apply_edit_subclip_button_style,
    create_checkerboard_pixmap,
)
from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon
from gui.widgets.volume_control import VolumeControlWidget
from gui.widgets.zoomable_image_viewer import ZoomableImageViewer
from gui.widgets.compare_viewer import CompareViewer

try:
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
    from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
    MULTIMEDIA_AVAILABLE = True
except ImportError as e:
    MULTIMEDIA_AVAILABLE = False
    logger.warning(f"PreviewPanel: QtMultimedia no está disponible en este sistema: {e}")

_SVG_DIR = os.path.join(get_src_dir(), "assets", "icons", "svg")

def get_svg_icon(name: str) -> QIcon:
    path = os.path.join(_SVG_DIR, name)
    return QIcon(path) if os.path.exists(path) else QIcon()


class _PreviewVideoView(QGraphicsView):
    """Vista gráfica para renderizar video en el mismo buffer 2D de Qt sin crear ventana nativa HWND,
    con soporte para cuadrícula de fondo tipo transparencia (estilo Photoshop) para videos con canal alfa."""
    SQUARE = 10
    COLOR_A = QColor(42, 42, 42)
    COLOR_B = QColor(30, 30, 30)

    def __init__(self, scene: QGraphicsScene, video_item: QGraphicsVideoItem, parent=None):
        super().__init__(scene, parent)
        self._video_item = video_item
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet("QGraphicsView { background: transparent; border: none; }")
        self.viewport().setAutoFillBackground(False)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._show_checkerboard = True

    def set_checkerboard_visible(self, visible: bool):
        if self._show_checkerboard != visible:
            self._show_checkerboard = visible
            self.viewport().update()

    def drawBackground(self, painter: QPainter, rect: QRectF):
        if self._show_checkerboard:
            painter.save()
            size = self.SQUARE
            r = self.sceneRect() if self.sceneRect().isValid() and not self.sceneRect().isEmpty() else rect
            cols = int(r.width() // size) + 2
            rows = int(r.height() // size) + 2
            for row in range(rows):
                for col in range(cols):
                    color = self.COLOR_A if (row + col) % 2 == 0 else self.COLOR_B
                    painter.fillRect(QRectF(r.left() + col * size, r.top() + row * size, size, size), color)
            painter.restore()
        else:
            super().drawBackground(painter, rect)

    def refit(self):
        vp_w = self.viewport().width()
        vp_h = self.viewport().height()
        if vp_w <= 0 or vp_h <= 0:
            return

        self.scene().setSceneRect(0, 0, vp_w, vp_h)
        native = self._video_item.nativeSize()
        if native.isEmpty() or native.width() <= 0 or native.height() <= 0:
            self._video_item.setSize(QSizeF(vp_w, vp_h))
            self._video_item.setPos(0, 0)
            return

        scale = min(vp_w / native.width(), vp_h / native.height())
        scaled_w = native.width() * scale
        scaled_h = native.height() * scale
        self._video_item.setSize(QSizeF(scaled_w, scaled_h))
        self._video_item.setPos((vp_w - scaled_w) / 2.0, (vp_h - scaled_h) / 2.0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refit()


class PreviewContainerWidget(QFrame):
    """Contenedor de vista previa rectangular (panorámico) con soporte para imágenes y reproducción de video real con controles."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("previewContainer")
        
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumHeight(140)
        # Por defecto mantiene el alto tipo "reproductor" (ancho x 0.6) que usa el
        # Gestor de Medios -- ver set_fill_available_space() para el modo usado por el
        # Editor de Imagen, donde el preview debe ocupar 100% del espacio disponible.
        self._fill_available_space = False
        # Por defecto usa el QLabel estático de siempre (ajustado a la ventana) -- ver
        # set_zoomable() para el modo con zoom/paneo interactivo del Editor de Imagen.
        self._zoomable = False

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        
        # Fondo oscuro y bordes redondeados
        self.setStyleSheet(f"""
            QFrame#previewContainer {{
                background-color: {get_theme_token('fondo_principal', '#0a0a0a')};
                border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                border-radius: 6px;
            }}
        """)
        
        # 1. Widget de Estado Vacío Estilizado (Centrado Absoluto)
        self.empty_state_widget = QWidget()
        self.empty_state_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        empty_outer = QVBoxLayout(self.empty_state_widget)
        empty_outer.setContentsMargins(0, 0, 0, 0)
        empty_outer.setSpacing(0)
        empty_outer.addStretch(1)

        empty_inner = QWidget()
        empty_inner_layout = QVBoxLayout(empty_inner)
        empty_inner_layout.setContentsMargins(10, 0, 10, 0)
        empty_inner_layout.setSpacing(6)
        empty_inner_layout.setAlignment(Qt.AlignCenter)

        self.lbl_empty_icon = QLabel()
        self.lbl_empty_icon.setAlignment(Qt.AlignCenter)
        empty_ico = get_colored_svg_icon("play_arrow.svg", "#444444", size=36)
        if not empty_ico.isNull():
            self.lbl_empty_icon.setPixmap(empty_ico.pixmap(36, 36))
        empty_inner_layout.addWidget(self.lbl_empty_icon)

        self.lbl_empty_title = QLabel(self.tr("Vista Previa"))
        self.lbl_empty_title.setAlignment(Qt.AlignCenter)
        self.lbl_empty_title.setStyleSheet(f"font-weight: bold; font-size: 13px; color: {get_theme_token('texto_secundario', '#777777')};")
        empty_inner_layout.addWidget(self.lbl_empty_title)

        self.lbl_empty_desc = QLabel(self.tr("Selecciona un archivo multimedia de la lista\npara reproducirlo o ver su detalle"))
        self.lbl_empty_desc.setAlignment(Qt.AlignCenter)
        self.lbl_empty_desc.setStyleSheet("font-size: 11px; color: #555555;")
        empty_inner_layout.addWidget(self.lbl_empty_desc)

        empty_outer.addWidget(empty_inner, 0, Qt.AlignCenter)
        empty_outer.addStretch(1)

        self.layout.addWidget(self.empty_state_widget, 1)

        # 2. Widget de Imagen / Placeholder
        self.placeholder_label = QLabel()
        self.placeholder_label.setAlignment(Qt.AlignCenter)
        self.placeholder_label.setWordWrap(True)
        self.placeholder_label.setVisible(False)
        self.layout.addWidget(self.placeholder_label, 1)

        # 2b. Visor con zoom/paneo (modo Editor de Imagen, ver set_zoomable())
        self.zoom_viewer = ZoomableImageViewer()
        self.zoom_viewer.setVisible(False)
        self.layout.addWidget(self.zoom_viewer, 1)

        # 2c. Comparación antes/después (Editor de Imagen, ver show_compare_preview())
        # -- mismo patrón que zoom_viewer/video_widget: hermano en el mismo layout,
        # se muestra/oculta con setVisible(), sin necesidad de un overlay/Z-order real.
        self.compare_viewer = CompareViewer()
        self.compare_viewer.setVisible(False)
        self.layout.addWidget(self.compare_viewer, 1)

        # 2. Widget de Video Real Integrado en Qt
        self.video_widget = None
        self.video_scene = None
        self.video_item = None
        self.media_player = None
        self.audio_output = None
        self._is_dragging_slider = False
        self._last_volume = 10
        
        if MULTIMEDIA_AVAILABLE:
            try:
                self.video_scene = QGraphicsScene(self)
                self.video_scene.setBackgroundBrush(Qt.NoBrush)
                self.video_item = QGraphicsVideoItem()
                self.video_scene.addItem(self.video_item)
                self.video_item.nativeSizeChanged.connect(lambda s: self.video_widget.refit() if self.video_widget else None)

                self.video_widget = _PreviewVideoView(self.video_scene, self.video_item, self)
                self.video_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                self.video_widget.setVisible(False)
                self.layout.addWidget(self.video_widget)
                
                self.media_player = QMediaPlayer(self)
                self.audio_output = QAudioOutput(self)
                self.media_player.setAudioOutput(self.audio_output)
                self.media_player.setVideoOutput(self.video_item)
                
                # Bajar el volumen por defecto a un nivel agradable (10%) para evitar sustos
                self.audio_output.setVolume(0.1)
                
                # Desactivar bucle de video por defecto
                self.media_player.setLoops(1)

            except Exception as ex:
                logger.error(f"PreviewPanel: Error inicializando reproductores multimedia: {ex}")
                self.video_widget = None

        # 3. Controles del Reproductor de Video
        self.controls_widget = QWidget()
        self.controls_widget.setVisible(False)
        controls_v = QVBoxLayout(self.controls_widget)
        controls_v.setContentsMargins(8, 2, 8, 8)
        controls_v.setSpacing(4)

        # Barra de tiempo
        self.time_slider = QSlider(Qt.Horizontal)
        self.time_slider.setRange(0, 100)
        self.time_slider.setValue(0)
        self.time_slider.setCursor(Qt.PointingHandCursor)
        self.time_slider.sliderPressed.connect(self._on_slider_pressed)
        self.time_slider.sliderMoved.connect(self._on_slider_moved)
        self.time_slider.sliderReleased.connect(self._on_slider_released)
        controls_v.addWidget(self.time_slider)

        # Fila inferior: Play, Tiempo, Volumen
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(4)

        # Botón Play/Pausa
        self.btn_play_pause = QPushButton()
        self.btn_play_pause.setIconSize(QSize(14, 14))
        self.btn_play_pause.setFixedSize(24, 24)
        apply_player_play_button_style(self.btn_play_pause, is_playing=True, icon_size=14)
        self.btn_play_pause.clicked.connect(self.toggle_play_pause)
        btn_layout.addWidget(self.btn_play_pause)

        # Botón Loop/Repetir
        self._video_loop_active = False  # Por defecto desactivado
        self.btn_loop = QPushButton()
        self.btn_loop.setIconSize(QSize(14, 14))
        self.btn_loop.setFixedSize(24, 24)
        apply_player_loop_button_style(self.btn_loop, is_active=False, icon_size=14)

        self.btn_loop.clicked.connect(self._toggle_video_loop)
        btn_layout.addWidget(self.btn_loop)

        # Botón Editar Subclip
        self.btn_edit_subclip = QPushButton()
        self.btn_edit_subclip.setIconSize(QSize(14, 14))
        self.btn_edit_subclip.setFixedSize(24, 24)
        self._has_subclips = False
        apply_edit_subclip_button_style(self.btn_edit_subclip, has_subclips=False, icon_size=14)
        btn_layout.addWidget(self.btn_edit_subclip)

        # Etiqueta de tiempo
        self.lbl_video_time = QLabel("00:00 / 00:00")
        self.lbl_video_time.setStyleSheet("font-size: 11px; color: #a6adc8; background: transparent; border: none;")
        self.lbl_video_time.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        btn_layout.addWidget(self.lbl_video_time)

        btn_layout.addStretch(1)

        # Control de Volumen Unificado
        self.volume_control = VolumeControlWidget(initial_volume=10, slider_width=50)
        self.volume_control.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.volume_control.volume_changed.connect(self._on_volume_changed)
        btn_layout.addWidget(self.volume_control)

        controls_v.addLayout(btn_layout)
        self.layout.addWidget(self.controls_widget)

        if MULTIMEDIA_AVAILABLE and self.media_player:
            self.media_player.positionChanged.connect(self._on_position_changed)
            self.media_player.durationChanged.connect(self._on_duration_changed)
            self.media_player.playbackStateChanged.connect(self._on_playback_state_changed)
            # El bucle se maneja manualmente (en vez de confiar en QMediaPlayer.setLoops(),
            # cuya aplicación en caliente resultaba poco fiable con algunos backends: a veces
            # había que activar/desactivar el botón más de una vez para que surtiera efecto).
            self.media_player.mediaStatusChanged.connect(self._on_media_status_changed_loop)

        from core.tabs.editing_media.thumbnail_cache_manager import ThumbnailCacheManager
        ThumbnailCacheManager.get_instance().preview_loaded.connect(self._on_heavy_preview_ready)

        self.show_default_state()

    def set_fill_available_space(self, enabled: bool):
        """Cambia entre el alto tipo "reproductor" (ancho x 0.6, usado por el Gestor de
        Medios) y ocupar el 100% del alto que le da el layout, sin franjas vacías (usado
        por el Editor de Imagen). Hay que llamarlo una sola vez tras crear el widget."""
        self._fill_available_space = enabled
        if enabled:
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)  # QWIDGETSIZE_MAX -- deshace cualquier setFixedHeight previo
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        else:
            self.setMinimumHeight(140)
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def set_zoomable(self, enabled: bool):
        """Activa el visor con zoom (rueda del mouse) y paneo (arrastrar) para
        imágenes ya decodificadas -- ver ZoomableImageViewer. Usado por el Editor de
        Imagen; el Gestor de Medios deja esto en False (comportamiento de siempre:
        QLabel estático ajustado a la ventana). Hay que llamarlo una sola vez tras
        crear el widget."""
        self._zoomable = enabled

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w = self.width()
        if w > 0:
            if self._fill_available_space:
                avail_h = self.height()
            else:
                avail_h = int(w * 0.6)
                self.setFixedHeight(avail_h)
            if hasattr(self, "volume_control") and self.volume_control:
                self.volume_control.set_slider_visible(w >= 280)
            if hasattr(self, "lbl_video_time") and self.lbl_video_time:
                self.lbl_video_time.setVisible(w >= 230)
            if hasattr(self, "_current_movie") and self._current_movie and self.placeholder_label.isVisible():
                movie = self._current_movie
                orig_size = movie.currentImage().size()
                if orig_size.isValid() and not orig_size.isEmpty():
                    scaled_size = orig_size.scaled(max(50, w - 10), max(50, avail_h - 10), Qt.KeepAspectRatio)
                    movie.setScaledSize(scaled_size)
            elif hasattr(self, "_current_base_pixmap") and self._current_base_pixmap and self.placeholder_label.isVisible():
                # Reescala desde la imagen ya decodificada en memoria en vez de recargar
                # el archivo con QPixmap(path): Qt no tiene loader nativo para .psd/.pdf/
                # .ai/.eps, así que ese reload silenciosamente no hacía nada con esos
                # formatos y la vista previa quedaba pegada al tamaño del primer render.
                scaled = self._current_base_pixmap.scaled(
                    max(50, w - 10),
                    max(50, avail_h - 10),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                bg = create_checkerboard_pixmap(scaled.width(), scaled.height(), square_size=10)
                painter = QPainter(bg)
                painter.drawPixmap(0, 0, scaled)
                painter.end()
                self.placeholder_label.setPixmap(bg)
            elif hasattr(self, "_current_image_path") and self._current_image_path and self.placeholder_label.isVisible():
                pixmap = QPixmap(self._current_image_path)
                if not pixmap.isNull():
                    scaled = pixmap.scaled(
                        max(50, w - 10),
                        max(50, avail_h - 10),
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation
                    )
                    self.placeholder_label.setPixmap(scaled)
            elif hasattr(self, "video_widget") and self.video_widget and self.video_widget.isVisible():
                self.video_widget.refit()

    def stop_media(self, clear_zoom_viewer: bool = True):
        """Detiene cualquier reproducción de video o animación GIF activa.
        `clear_zoom_viewer=False` (usado por show_compare_preview()) solo lo
        oculta sin vaciar su escena -- preserva las formas/pincel/Canvas en vivo
        del Editor de Imagen para poder volver con show_zoom_viewer_only(), ver
        ImageToolsTab._on_compare_toggled."""
        self._current_image_path = None
        self._current_base_pixmap = None
        if hasattr(self, "_current_movie") and self._current_movie:
            try:
                self._current_movie.stop()
            except Exception:
                pass
            self._current_movie = None
        if hasattr(self, "placeholder_label") and self.placeholder_label:
            self.placeholder_label.setMovie(None)
        if hasattr(self, "zoom_viewer") and self.zoom_viewer:
            if clear_zoom_viewer:
                self.zoom_viewer.clear()
            self.zoom_viewer.setVisible(False)
        if hasattr(self, "compare_viewer") and self.compare_viewer:
            self.compare_viewer.clear()
            self.compare_viewer.setVisible(False)

        if self.media_player:
            try:
                self.media_player.stop()
            except Exception:
                pass

    def show_default_state(self):
        self.stop_media()
        if self.video_widget:
            self.video_widget.setVisible(False)
        if hasattr(self, "controls_widget"):
            self.controls_widget.setVisible(False)
        if hasattr(self, "empty_state_widget"):
            self.empty_state_widget.setVisible(True)
        self.placeholder_label.setVisible(False)
        self.placeholder_label.setPixmap(QPixmap())

    def _set_preview_image(self, source, avail_w: int, avail_h: int) -> bool:
        """Escala `source` (QPixmap o QImage) a `avail_w`x`avail_h`, lo compone sobre
        el fondo de cuadrícula de transparencia y lo muestra. Cachea el pixmap base
        sin escalar en `_current_base_pixmap` para que resizeEvent pueda reescalarlo
        al agrandar/achicar el panel sin recurrir a QPixmap(path) (que no sabe releer
        .psd/.pdf/.ai/.eps desde disco)."""
        pix = source if isinstance(source, QPixmap) else QPixmap.fromImage(source)
        if pix.isNull():
            return False
        self._current_base_pixmap = pix

        if self._zoomable:
            # Resolución completa, sin escalar/hornear checkerboard: el visor maneja
            # su propio zoom/paneo y pinta el checkerboard él solo.
            self.placeholder_label.setVisible(False)
            self.zoom_viewer.setVisible(True)
            self.zoom_viewer.set_pixmap(pix)
            return True

        self.zoom_viewer.setVisible(False)
        self.placeholder_label.setVisible(True)
        scaled = pix.scaled(avail_w, avail_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        bg = create_checkerboard_pixmap(scaled.width(), scaled.height(), square_size=10)
        painter = QPainter(bg)
        painter.drawPixmap(0, 0, scaled)
        painter.end()
        self.placeholder_label.setPixmap(bg)
        return True

    def show_image_preview(self, path: str):
        self.stop_media()
        self._current_image_path = path
        self._current_base_pixmap = None
        if hasattr(self, "empty_state_widget"):
            self.empty_state_widget.setVisible(False)
        if self.video_widget:
            self.video_widget.setVisible(False)
        if hasattr(self, "controls_widget"):
            self.controls_widget.setVisible(False)

        self.placeholder_label.setVisible(True)
        self.placeholder_label.setText("")

        ext = os.path.splitext(path)[1].lower()
        avail_w = max(50, self.width() - 10)
        avail_h = max(50, self.height() - 10)

        # GIF animado: se queda con su propio camino de QMovie (animación en vivo)
        # -- NO pasa por load_pixmap_for_path(), que para .gif solo devuelve el
        # primer frame como pixmap estático (pensado para show_compare_preview(),
        # donde no tiene sentido animar el "antes").
        if ext == ".gif":
            from PySide6.QtGui import QMovie
            movie = QMovie(path)
            if movie.isValid():
                self._current_movie = movie
                movie.jumpToFrame(0)
                orig_size = movie.currentImage().size()
                if orig_size.isValid() and not orig_size.isEmpty():
                    scaled_size = orig_size.scaled(avail_w, avail_h, Qt.AspectRatioMode.KeepAspectRatio)
                    movie.setScaledSize(scaled_size)
                else:
                    movie.setScaledSize(QSize(avail_w, avail_h))
                self.placeholder_label.setMovie(movie)
                movie.start()
                return

        # Resto de formatos (vector/PDF-AI/PSD/RAW/EPS/ráster + fallback de imagen
        # pesada): decodificación centralizada en load_pixmap_for_path(), reusada
        # también por show_compare_preview() -- ver ese método para el detalle de
        # cada rama.
        pix = self.load_pixmap_for_path(path, avail_w, avail_h)
        if pix is not None:
            self._set_preview_image(pix, avail_w, avail_h)
        else:
            # Caso normal: imagen pesada sin cache todavía -- load_pixmap_for_path
            # ya dejó pedida la generación async (ver _on_heavy_preview_ready, que
            # completa el display cuando esté lista); aquí solo queda avisar mientras
            # tanto. (Caso extremo, casi inalcanzable: un EPS/PS totalmente
            # ilegible -- ya quedó loggeado por load_pixmap_for_path.)
            self.placeholder_label.setText(self.tr("Generando vista previa (imagen muy pesada)..."))
            self.placeholder_label.setStyleSheet("color: #999999; font-size: 12px;")

    def load_pixmap_for_path(self, path: str, avail_w: int, avail_h: int) -> QPixmap | None:
        """Decodifica `path` a un QPixmap mostrable -- sin componer checkerboard/
        escalado final de display (eso lo hace _set_preview_image, o lo maneja el
        propio llamador en el caso de show_compare_preview). Extraído de
        show_image_preview() para poder reusarse ahí y en show_compare_preview()
        sin duplicar el manejo por formato. Devuelve None solo para el caso de
        imagen pesada aún sin cache (la generación async ya quedó pedida)."""
        ext = os.path.splitext(path)[1].lower()

        if ext == ".gif":
            from PySide6.QtGui import QMovie
            movie = QMovie(path)
            if movie.isValid():
                movie.jumpToFrame(0)
                img = movie.currentImage()
                if not img.isNull():
                    return QPixmap.fromImage(img)
            return None

        # Renderizado vectorial dinámico para SVG
        if ext in (".svg", ".svgz"):
            try:
                from PySide6.QtSvg import QSvgRenderer
                renderer = QSvgRenderer(path)
                if renderer.isValid():
                    sz = renderer.defaultSize()
                    if sz.isEmpty() or sz.width() <= 0 or sz.height() <= 0:
                        sz = QSize(avail_w, avail_h)
                    scaled_sz = sz.scaled(avail_w, avail_h, Qt.AspectRatioMode.KeepAspectRatio)
                    pix = QPixmap(scaled_sz)
                    pix.fill(Qt.GlobalColor.transparent)
                    painter = QPainter(pix)
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                    renderer.render(painter, QRectF(0, 0, scaled_sz.width(), scaled_sz.height()))
                    painter.end()
                    return pix
            except Exception as e:
                logger.error(f"PreviewPanel: Error renderizando SVG {path}: {e}")

        # Renderizado de documento PDF / Ilustrator (.ai) -- mismo motor que la
        # conversión real (pypdfium2, ver ImageConverter._load_pdf_like) en vez de
        # QPdfDocument: éste último renderiza al tamaño en píxeles del panel (se ve
        # pixelado al hacer zoom) -- con target_size=None se renderiza a DPI fijo
        # (_DEFAULT_VECTOR_DPI). transparent=False: la vista previa debe verse como
        # un documento normal (fondo blanco); la transparencia real de salida solo
        # aplica al archivo final si el usuario marca "Fondo transparente" al
        # convertir (ver ConvertPanel._build_pdf_page/_save_as_pdf).
        if ext in (".pdf", ".ai"):
            try:
                from core.tabs.image_tools.image_converter import ImageConverter
                pil_img = ImageConverter()._load_pdf_like(path, None, True, {}, transparent=False)
                rgb_im = pil_img.convert("RGBA")
                data = rgb_im.tobytes("raw", "RGBA")
                qimg = QImage(data, rgb_im.width, rgb_im.height, rgb_im.width * 4, QImage.Format.Format_RGBA8888).copy()
                if not qimg.isNull():
                    return QPixmap.fromImage(qimg)
            except Exception as e:
                logger.error(f"PreviewPanel: Error renderizando PDF/AI {path}: {e}")

        # Renderizado para Photoshop (.psd)
        if ext == ".psd":
            try:
                # Thumbnail embebido por Photoshop (psd-tools): evita componer todas
                # las capas del documento en el hilo de UI, que es lo que congela la
                # vista previa más de un segundo en archivos con muchas capas.
                try:
                    from psd_tools import PSDImage
                    psd = PSDImage.open(path)
                    embedded = psd.thumbnail()
                    if embedded is not None:
                        rgb_im = embedded.convert("RGBA")
                        data = rgb_im.tobytes("raw", "RGBA")
                        qimg = QImage(data, rgb_im.width, rgb_im.height, rgb_im.width * 4, QImage.Format.Format_RGBA8888).copy()
                        if not qimg.isNull():
                            return QPixmap.fromImage(qimg)
                except Exception:
                    pass

                pixmap = QPixmap(path)
                if not pixmap.isNull():
                    return pixmap

                # Intentar con Pillow
                try:
                    from PIL import Image
                    with Image.open(path) as im:
                        rgb_im = im.convert("RGBA")
                        data = rgb_im.tobytes("raw", "RGBA")
                        qimg = QImage(data, rgb_im.width, rgb_im.height, rgb_im.width * 4, QImage.Format.Format_RGBA8888).copy()
                        if not qimg.isNull():
                            return QPixmap.fromImage(qimg)
                except Exception:
                    pass

                # Fallback con FFmpeg por tubería en memoria si Pillow no leyera el PSD
                from core.setup.ffmpeg_setup import get_ffmpeg_dir, get_platform_info, check_ffmpeg
                import subprocess
                if check_ffmpeg():
                    info = get_platform_info()
                    ffmpeg_exe = os.path.join(get_ffmpeg_dir(), info["binary_name"])
                    startupinfo = None
                    if os.name == 'nt':
                        startupinfo = subprocess.STARTUPINFO()
                        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    cmd = [
                        ffmpeg_exe, "-hide_banner", "-loglevel", "error",
                        "-i", path, "-vframes", "1",
                        "-f", "image2pipe", "-vcodec", "bmp", "-"
                    ]
                    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)
                    out, _ = proc.communicate(timeout=5)
                    if out:
                        img = QImage.fromData(out)
                        if not img.isNull():
                            return QPixmap.fromImage(img)
            except Exception as e:
                logger.error(f"PreviewPanel: Error renderizando PSD {path}: {e}")

        # Renderizado para RAW de cámara (.cr2, .nef, .arw, .dng, ...)
        if ext in RAW_EXTS:
            try:
                import rawpy
                with rawpy.imread(path) as raw:
                    im = None
                    try:
                        thumb = raw.extract_thumb()
                        if thumb.format == rawpy.ThumbFormat.JPEG:
                            import io
                            from PIL import Image
                            im = Image.open(io.BytesIO(thumb.data))
                        elif thumb.format == rawpy.ThumbFormat.BITMAP:
                            from PIL import Image
                            im = Image.fromarray(thumb.data)
                    except (rawpy.LibRawNoThumbnailError, rawpy.LibRawUnsupportedThumbnailError):
                        pass

                    if im is None:
                        # Sin preview embebido (raro): revelar el RAW completo como último
                        # recurso. A propósito NO se reintenta en segundo plano si esto
                        # también falla -- mismo criterio que PSD, sin reprocesado extra.
                        rgb = raw.postprocess(
                            use_camera_wb=True, output_bps=8,
                            output_color=rawpy.ColorSpace.sRGB,
                            demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD,
                        )
                        from PIL import Image
                        im = Image.fromarray(rgb)

                # El JPEG embebido viene en la orientación nativa del sensor; sin
                # aplicar su tag EXIF, las fotos tomadas en vertical salen de costado.
                try:
                    from PIL import ImageOps
                    im = ImageOps.exif_transpose(im)
                except Exception:
                    pass

                rgb_im = im.convert("RGB")
                data = rgb_im.tobytes("raw", "RGB")
                qimg = QImage(data, rgb_im.width, rgb_im.height, rgb_im.width * 3, QImage.Format.Format_RGB888).copy()
                if not qimg.isNull():
                    return QPixmap.fromImage(qimg)
            except Exception as e:
                logger.error(f"PreviewPanel: Error renderizando RAW {path}: {e}")

        # Preview para EPS / PS (PostScript)
        if ext in (".eps", ".ps"):
            try:
                import struct
                # A. Cabecera binaria DOS EPS con TIFF
                with open(path, "rb") as f:
                    raw_head = f.read(4096)
                    if len(raw_head) >= 28 and raw_head[:4] in (b'\xC5\xD0\xD3\xC6', b'\xC6\xD3\xD0\xC5'):
                        tiff_start, tiff_len = struct.unpack("<II", raw_head[20:28])
                        if tiff_len > 0:
                            f.seek(tiff_start)
                            tiff_bytes = f.read(tiff_len)
                            if tiff_bytes:
                                tiff_img = QImage.fromData(tiff_bytes)
                                if not tiff_img.isNull():
                                    return QPixmap.fromImage(tiff_img)

                # B. QPdfDocument (si el EPS contiene datos PDF/AI)
                try:
                    from PySide6.QtPdf import QPdfDocument
                    doc = QPdfDocument(self)
                    doc.load(path)
                    if doc.pageCount() > 0:
                        sz = doc.pagePointSize(0)
                        if sz.isValid() and sz.width() > 0:
                            scale = min(avail_w / sz.width(), avail_h / sz.height())
                            render_w = max(1, int(sz.width() * scale))
                            render_h = max(1, int(sz.height() * scale))
                            page_img = doc.render(0, QSize(render_w, render_h))
                            if not page_img.isNull():
                                return QPixmap.fromImage(page_img)
                except Exception:
                    pass

                # C. Tarjeta visual informativa estilizada con dimensiones
                return self._build_vector_info_card(path, ext, avail_w, avail_h)

            except Exception as e:
                logger.error(f"PreviewPanel: Error leyendo preview EPS {path}: {e}")
            return None

        # Renderizado ráster estándar (PNG, JPG, WebP, etc.)
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            return pixmap

        # Qt rechazó la imagen por superar su límite de asignación de memoria
        # (imagen muy grande/pesada). Usar el preview cacheado por
        # ThumbnailCacheManager (Pillow, sin ese límite) en vez de mostrar error.
        return self._load_heavy_image_pixmap(path)

    def _build_vector_info_card(self, path: str, ext: str, avail_w: int, avail_h: int) -> QPixmap:
        """Tarjeta informativa estilizada (nombre + dimensiones del BoundingBox) --
        último recurso cuando un EPS/PS no se pudo decodificar como imagen real."""
        import re
        dim_str = ""
        with open(path, "rb") as f:
            header_text = f.read(4096).decode("latin-1", errors="ignore")
            match = re.search(r"%%(?:HiRes)?BoundingBox:\s*([-\d\.]+)\s+([-\d\.]+)\s+([-\d\.]+)\s+([-\d\.]+)", header_text)
            if match:
                x1, y1, x2, y2 = map(float, match.groups())
                w = int(round(abs(x2 - x1)))
                h = int(round(abs(y2 - y1)))
                if w > 0 and h > 0:
                    dim_str = f"{w}x{h} px"

        card_w = min(avail_w, 320)
        card_h = min(avail_h, 180)
        out_pix = QPixmap(card_w, card_h)
        out_pix.fill(QColor("#18181a"))
        painter = QPainter(out_pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        from PySide6.QtGui import QPen, QBrush, QFont
        pen = QPen(QColor("#2d2d30"), 1.5)
        painter.setPen(pen)
        painter.setBrush(QBrush(QColor("#202024")))
        painter.drawRoundedRect(8, 8, card_w - 16, card_h - 16, 8, 8)

        ext_name = "EPS" if ext == ".eps" else "PS"
        font_badge = QFont("Segoe UI", 18, QFont.Weight.Bold)
        painter.setFont(font_badge)
        painter.setPen(QColor("#e67e22"))
        painter.drawText(QRectF(8, 20, card_w - 16, 32), Qt.AlignmentFlag.AlignCenter, f"Vector {ext_name}")

        font_name = QFont("Segoe UI", 10)
        painter.setFont(font_name)
        painter.setPen(QColor("#cccccc"))
        painter.drawText(QRectF(16, 60, card_w - 32, 40), Qt.AlignmentFlag.AlignCenter, os.path.basename(path))

        if dim_str:
            font_dim = QFont("Segoe UI", 11, QFont.Weight.DemiBold)
            painter.setFont(font_dim)
            painter.setPen(QColor(get_theme_token("acento_primario", "#B9E640")))
            painter.drawText(QRectF(8, 110, card_w - 16, 25), Qt.AlignmentFlag.AlignCenter, f"Lienzo: {dim_str}")

        painter.end()
        return out_pix

    def _load_heavy_image_pixmap(self, path: str) -> QPixmap | None:
        """El original nunca se toca: usa una versión reducida cacheada en disco (se
        genera una sola vez por archivo, vía ThumbnailCacheManager/Pillow, sin el
        límite de asignación de Qt). Si todavía no existe cache, deja pedida la
        generación async y devuelve None -- _on_heavy_preview_ready completa el
        display cuando esté lista."""
        from core.tabs.editing_media.thumbnail_cache_manager import ThumbnailCacheManager
        manager = ThumbnailCacheManager.get_instance()
        cached = manager.get_cached_preview_path(path)
        if cached:
            pix = QPixmap(cached)
            if not pix.isNull():
                return pix
        manager.request_preview(path)
        return None

    def show_compare_preview(self, before_path: str, after_path: str,
                              before_pixmap: QPixmap = None, after_pixmap: QPixmap = None):
        """Vista "antes/después" con divisor arrastrable (ver CompareViewer) --
        `before_pixmap`/`after_pixmap`, si vienen dados, evitan recargar de disco
        (cache LRU en el llamador, ver ImageToolsTab._CompareCache). El "antes" pasa
        por load_pixmap_for_path (mismo manejo por formato que el preview normal --
        vector/RAW/PSD/EPS); el "después" siempre es un ráster plano que ya escribió
        ImageConverter (PNG/JPG/WEBP/...), sin necesidad de manejo especial."""
        self.stop_media(clear_zoom_viewer=False)
        self._current_image_path = before_path
        if hasattr(self, "empty_state_widget"):
            self.empty_state_widget.setVisible(False)
        if self.video_widget:
            self.video_widget.setVisible(False)
        if hasattr(self, "controls_widget"):
            self.controls_widget.setVisible(False)
        self.placeholder_label.setVisible(False)

        avail_w = max(50, self.width() - 10)
        avail_h = max(50, self.height() - 10)
        if before_pixmap is None:
            before_pixmap = self.load_pixmap_for_path(before_path, avail_w, avail_h)
        if after_pixmap is None:
            after_pixmap = QPixmap(after_path)

        if not before_pixmap or not after_pixmap or before_pixmap.isNull() or after_pixmap.isNull():
            # Caso extremo (imagen "antes" pesada sin cache todavía, o "después"
            # ilegible) -- se cae a la vista normal en vez de mostrar un comparador
            # vacío/roto.
            self.show_image_preview(before_path)
            return

        self.compare_viewer.setVisible(True)
        self.compare_viewer.set_images(before_pixmap, after_pixmap)

    def show_zoom_viewer_only(self):
        """Vuelve a mostrar el editor sin recargar la imagen ni tocar su escena --
        usado para volver desde show_compare_preview() (ver
        ImageToolsTab._on_compare_toggled) preservando el estado en vivo tal cual
        estaba, a diferencia de show_image_preview() que sí recarga de disco."""
        if hasattr(self, "empty_state_widget"):
            self.empty_state_widget.setVisible(False)
        self.compare_viewer.setVisible(False)
        self.zoom_viewer.setVisible(True)

    def _on_heavy_preview_ready(self, path: str, preview_path: str):
        if path != self._current_image_path:
            return
        pix = QPixmap(preview_path)
        if pix.isNull():
            return
        avail_w = max(50, self.width() - 10)
        avail_h = max(50, self.height() - 10)
        if self._set_preview_image(pix, avail_w, avail_h):
            self.placeholder_label.setStyleSheet("")

    def show_video_preview(self, path: str):
        if self.video_widget and self.media_player:
            if hasattr(self, "empty_state_widget"):
                self.empty_state_widget.setVisible(False)
            self.placeholder_label.setVisible(False)
            self.video_widget.setVisible(True)
            self.video_widget.refit()
            if hasattr(self, "controls_widget"):
                self.controls_widget.setVisible(True)
            try:
                self.media_player.setSource(QUrl.fromLocalFile(path))
                self.media_player.play()
                logger.debug(f"PreviewPanel: Reproduciendo video preview: {path}")
            except Exception as e:
                logger.error(f"PreviewPanel: Error reproduciendo video: {e}")
                self.show_video_placeholder(path)
        else:
            self.show_video_placeholder(path)

    def show_video_placeholder(self, path: str, poster_path: str = None):
        """`poster_path`, si se pasa (ej. el frame estático que Wikimedia ya genera para un
        video remoto aún no descargado), se pinta como fondo en vez de dejar el pixmap vacío."""
        self.stop_media()
        if hasattr(self, "empty_state_widget"):
            self.empty_state_widget.setVisible(False)
        if self.video_widget:
            self.video_widget.setVisible(False)
        if hasattr(self, "controls_widget"):
            self.controls_widget.setVisible(False)
        self.placeholder_label.setVisible(True)
        name = os.path.basename(path)

        if poster_path and os.path.exists(poster_path):
            pixmap = QPixmap(poster_path)
            if not pixmap.isNull():
                self.placeholder_label.setPixmap(pixmap.scaled(
                    self.placeholder_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                ))
                self.placeholder_label.setText("")
                return

        self.placeholder_label.setPixmap(QPixmap())
        self.placeholder_label.setText(self.tr("▶ [ Previsualización de Video ]\n\n{0}").format(name))
        self.placeholder_label.setStyleSheet(f"color: {get_theme_token('acento_primario', '#B9E640')}; font-weight: bold; font-size: 13px;")

    def show_audio_preview(self, path: str):
        self.stop_media()
        if hasattr(self, "empty_state_widget"):
            self.empty_state_widget.setVisible(False)
        if self.video_widget:
            self.video_widget.setVisible(False)
        if hasattr(self, "controls_widget"):
            self.controls_widget.setVisible(False)
        self.placeholder_label.setVisible(True)
        self.placeholder_label.setPixmap(QPixmap())
        name = os.path.basename(path)
        self.placeholder_label.setText(self.tr("🎵 [ Detalle de Audio ]\n\n{0}").format(name))
        self.placeholder_label.setStyleSheet("color: #f5c2e7; font-weight: bold; font-size: 13px;")

    # Métodos de Control del Reproductor de Video
    def toggle_play_pause(self):
        if not self.media_player:
            return
        if self.media_player.playbackState() == QMediaPlayer.PlayingState:
            self.media_player.pause()
        else:
            self.media_player.play()

    def toggle_mute(self):
        if hasattr(self, "volume_control"):
            self.volume_control.toggle_mute()

    def _on_volume_changed(self, value):
        # value puede ser flotante (0.0 a 1.0) o entero (0 a 100)
        float_val = value if isinstance(value, float) else value / 100.0
        if self.audio_output:
            self.audio_output.setVolume(float_val)

    def _on_position_changed(self, position):
        if not self._is_dragging_slider and self.media_player:
            self.time_slider.setValue(position)
            self._update_time_label(position, self.media_player.duration())

    def _on_duration_changed(self, duration):
        self.time_slider.setRange(0, duration)
        self._update_time_label(self.time_slider.value(), duration)

    def _update_time_label(self, position, duration):
        show_hours = bool(duration and duration >= 3600000)
        pos_str = self._format_time(position, show_hours)
        dur_str = self._format_time(duration, show_hours)
        self.lbl_video_time.setText(f"{pos_str} / {dur_str}")

    def _format_time(self, ms, show_hours=False):
        if not ms or ms < 0:
            ms = 0
        ms = int(ms)
        s = ms // 1000
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        if show_hours or h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def _on_slider_pressed(self):
        self._is_dragging_slider = True
        if self.media_player:
            self._was_playing_before_drag = (self.media_player.playbackState() == QMediaPlayer.PlayingState)
            if self._was_playing_before_drag:
                self.media_player.pause()

    def _on_slider_moved(self, position):
        if self.media_player:
            self.media_player.setPosition(position)
            self._update_time_label(position, self.media_player.duration())

    def _on_slider_released(self):
        self._is_dragging_slider = False
        if self.media_player:
            self.media_player.setPosition(self.time_slider.value())
            if getattr(self, "_was_playing_before_drag", False):
                self.media_player.play()

    def _on_playback_state_changed(self, state):
        is_playing = (state == QMediaPlayer.PlayingState)
        apply_player_play_button_style(self.btn_play_pause, is_playing=is_playing, icon_size=14)

    def set_edit_subclip_active(self, has_subclips: bool):
        """Actualiza la apariencia 'encendida/apagada' del botón de editar subclips según si
        el medio actualmente mostrado ya tiene subclips guardados."""
        self._has_subclips = has_subclips
        apply_edit_subclip_button_style(self.btn_edit_subclip, has_subclips=has_subclips, icon_size=14)

    def _toggle_video_loop(self):
        """Alterna entre reproducción en bucle y reproducción única."""
        self._video_loop_active = not self._video_loop_active
        apply_player_loop_button_style(self.btn_loop, is_active=self._video_loop_active, icon_size=14)

    def _on_media_status_changed_loop(self, status):
        """Reinicia manualmente la reproducción al llegar al final si el bucle está activo.
        Esto evita depender de QMediaPlayer.setLoops(), que no siempre aplicaba el cambio
        de inmediato al alternar el botón durante la reproducción."""
        if status == QMediaPlayer.MediaStatus.EndOfMedia and getattr(self, "_video_loop_active", False):
            self.media_player.setPosition(0)
            self.media_player.play()
