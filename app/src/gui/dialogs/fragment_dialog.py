# src/gui/tabs/single_process/fragment_dialog.py
import os

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QListWidget, QListWidgetItem, QWidget,
    QSizePolicy, QLineEdit, QAbstractItemView, QFrame,
    QRadioButton, QButtonGroup, QGraphicsView, QGraphicsScene
)
from PySide6.QtCore import Qt, QUrl, QPoint, QSize, QSizeF, QRegularExpression, QEvent, QTimer, Signal
from PySide6.QtGui import QPixmap, QIcon, QRegularExpressionValidator, QPainter, QColor
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtSvg import QSvgRenderer

from gui.styles import get_theme_token
from gui.widgets.range_slider import RangeSlider
from gui.widgets.volume_control import VolumeControlWidget
from core.tabs.advanced_process.fragment_logic import FragmentManager, FragmentState
from core.utils.paths import get_src_dir

# ── Icon helpers ────────────────────────────────────────────
_SVG_DIR = os.path.join(get_src_dir(), "assets", "icons", "svg")

def _icon(name, color_hex=None, size=None):
    path = os.path.join(_SVG_DIR, name)
    if not os.path.exists(path):
        return QIcon()
    pix = QPixmap(path)
    if pix.isNull():
        return QIcon()
    if size:
        pix = pix.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    if color_hex:
        painter = QPainter(pix)
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(pix.rect(), QColor(color_hex))
        painter.end()
    return QIcon(pix)


# ── Custom widgets ────────────────────────────────────────────
class DeSelectableRadioButton(QRadioButton):
    """Radio button que se deselecciona si se vuelve a pulsar."""
    def mousePressEvent(self, event):
        if self.isChecked():
            # Deseleccionar manualmente rompiendo la exclusividad temporalmente
            group = self.group()
            if group:
                group.setExclusive(False)
                self.setChecked(False)
                group.setExclusive(True)
            else:
                self.setAutoExclusive(False)
                self.setChecked(False)
                self.setAutoExclusive(True)
        else:
            super().mousePressEvent(event)

class _FragmentItem(QWidget):
    """Fila personalizada para cada fragmento en la lista con sufijo editable."""
    def __init__(self, index, text, suffix, on_delete, on_suffix_changed, parent=None):
        super().__init__(parent)
        self.setFixedHeight(58)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 4, 6, 4)
        layout.setSpacing(2)

        # Fila superior: sufijo editable + botón eliminar
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(6)
        
        lbl_prefix = QLabel("_")
        lbl_prefix.setStyleSheet("color: #888; font-size: 11px; font-weight: bold;")
        lbl_prefix.setFixedWidth(8)
        top_row.addWidget(lbl_prefix)
        
        self.suffix_input = QLineEdit(suffix)
        self.suffix_input.setPlaceholderText("sufijo...")
        self.suffix_input.setStyleSheet(f"""
            QLineEdit {{
                background: {get_theme_token('fondo_secundario', '#121212')};
                color: {get_theme_token('acento_primario', '#B9E640')};
                border: 1px solid {get_theme_token('borde_sutil', '#333')};
                border-radius: 6px;
                padding: 1px 4px;
                font-size: 11px;
                font-weight: bold;
            }}
            QLineEdit:focus {{
                border: 1px solid {get_theme_token('acento_primario', '#B9E640')};
            }}
        """)
        self.suffix_input.setFixedHeight(20)
        self.suffix_input.textChanged.connect(lambda t, idx=index: on_suffix_changed(idx, t))
        top_row.addWidget(self.suffix_input, 1)
        
        btn_del = QPushButton()
        btn_del.setIcon(_icon("delete.svg"))
        btn_del.setIconSize(QSize(15, 15))
        btn_del.setFixedSize(22, 22)
        btn_del.setToolTip(self.tr("Eliminar fragmento"))
        btn_del.setStyleSheet("""
            QPushButton { background: transparent; border: none; border-radius: 6px; }
            QPushButton:hover { background: rgba(229,57,53,160); }
        """)
        btn_del.clicked.connect(on_delete)
        top_row.addWidget(btn_del)
        layout.addLayout(top_row)

        # Fila inferior: tiempos
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #999; font-size: 11px;")
        layout.addWidget(lbl)


class _SimpleVideoView(QGraphicsView):
    """QGraphicsView de fondo transparente que aloja un único QGraphicsVideoItem,
    ajustado y centrado (letterbox/pillarbox) al redimensionar."""

    clicked = Signal()

    def __init__(self, scene: QGraphicsScene, video_item: QGraphicsVideoItem, parent=None):
        super().__init__(scene, parent)
        self._video_item = video_item
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet("QGraphicsView { background: transparent; border: none; }")
        self.viewport().setAutoFillBackground(False)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def refit(self):
        """Centra y escala el ítem de video dentro del viewport, preservando su
        proporción de aspecto nativa (o llenando el viewport si aún no se conoce)."""
        vp_w = self.viewport().width()
        vp_h = self.viewport().height()
        if vp_w <= 0 or vp_h <= 0:
            return

        self.scene().setSceneRect(0, 0, vp_w, vp_h)

        native = self._video_item.nativeSize()
        if native.isEmpty() or native.width() <= 0 or native.height() <= 0:
            self._video_item.setSize(QSizeF(vp_w, vp_h))
            self._video_item.setPos(0, 0)
        else:
            scale = min(vp_w / native.width(), vp_h / native.height())
            scaled_w = native.width() * scale
            scaled_h = native.height() * scale
            self._video_item.setSize(QSizeF(scaled_w, scaled_h))
            self._video_item.setPos((vp_w - scaled_w) / 2.0, (vp_h - scaled_h) / 2.0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refit()


# ════════════════════════════════════════════════════════════
class FragmentDialog(QDialog):
    def __init__(self, parent=None, stream_url="", thumbnail_pixmap=None, duration=0, fps=30, source_url=""):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowTitle(self.tr("Recorte de fragmentos"))
        self.setModal(True)

        self.stream_url = stream_url
        self.source_url = source_url   # URL de la página original (para el proxy)
        self.thumbnail_pixmap = thumbnail_pixmap
        self.duration_ms = int(duration) * 1000 if duration else 180000
        self.fps = fps
        self.fragments = [] # Lista de tuplas (start_ms, end_ms, suffix)
        self.selected_mode = None
        self.is_modified = False

        # Arrancar el servidor proxy local (singleton — no hace nada si ya corre)
        try:
            from core.utils.stream_proxy import get_or_start_proxy
            get_or_start_proxy()
        except Exception as _e:
            from core.logger.logger_manager import logger
            logger.warning(f"FragmentDialog: No se pudo iniciar el proxy: {_e}")

        self.setObjectName("fragmentDialogOverlay")
        self.init_ui()
        QTimer.singleShot(0, self.load_preview)

    def showEvent(self, event):
        super().showEvent(event)
        win = self.parent().window() if self.parent() else None
        if win:
            pos = win.mapToGlobal(QPoint(0, 0))
            self.setGeometry(pos.x(), pos.y(), win.width(), win.height())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 185))
        painter.end()
        super().paintEvent(event)

    # NOTA: mousePressEvent/keyPressEvent/reject/accept/closeEvent para este diálogo
    # están definidos más abajo (una sola vez cada uno) - ver sección PLAYBACK/CLOSE.
    # (Antes había una segunda definición de cada uno aquí mismo que Python descartaba en
    # silencio por quedar sombreada por la de más abajo - dead code nunca ejecutado, con
    # el efecto de que win.activateWindow()/win.raise_() sobre la ventana principal
    # jamás se llegaba a invocar al cerrar este diálogo. Se sacó de aquí y se fusionó en
    # las definiciones reales, ver conversación.)

    # ──────────────────────────────────────────────────────────
    # UI
    # ──────────────────────────────────────────────────────────
    def init_ui(self):
        overlay_layout = QVBoxLayout(self)
        overlay_layout.setContentsMargins(16, 12, 16, 12)
        overlay_layout.setAlignment(Qt.AlignCenter)

        # ── Tarjeta Central Inamovible ────────────────────────
        self.card = QFrame()
        self.card.setObjectName("fragmentDialogCard")
        self.card.setMinimumSize(740, 480)
        self.card.setMaximumSize(980, 620)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        # ── Barra de Título ───────────────────────────────────
        title_bar = QWidget()
        title_bar.setObjectName("fragmentTitleBar")
        title_bar.setFixedHeight(38)
        tb_layout = QHBoxLayout(title_bar)
        tb_layout.setContentsMargins(16, 0, 10, 0)

        title_lbl = QLabel(self.tr("Recorte de fragmentos"))
        title_lbl.setObjectName("fragmentTitleLabel")
        tb_layout.addWidget(title_lbl)
        tb_layout.addStretch()

        btn_close = QPushButton()
        btn_close.setObjectName("modalCloseBtn")
        btn_close.setIcon(_icon("close.svg"))
        btn_close.setIconSize(QSize(14, 14))
        btn_close.setFixedSize(26, 26)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setToolTip(self.tr("Cerrar (Esc)"))
        btn_close.clicked.connect(self.reject)
        tb_layout.addWidget(btn_close)

        card_layout.addWidget(title_bar)

        # ── Contenido ─────────────────────────────────────────
        content_widget = QWidget()
        content_widget.setObjectName("fragmentMainContainer")
        content_layout = QHBoxLayout(content_widget)
        content_layout.setContentsMargins(18, 14, 18, 18)
        content_layout.setSpacing(18)

        # ══════════════════════════════
        # LEFT PANEL
        # ══════════════════════════════
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        # Video area (bordes rectos — evita desbordamiento del render)
        self.preview_container = QWidget()
        self.preview_container.setObjectName("fragmentVideoContainer")
        self.preview_container.setMinimumHeight(240)
        self.preview_container.setStyleSheet(
            "background: #000; border: 1px solid #2a2a2a; border-radius: 0px;"
        )
        c_layout = QVBoxLayout(self.preview_container)
        c_layout.setContentsMargins(0, 0, 0, 0)
        c_layout.setSpacing(0)

        self.video_scene = QGraphicsScene(self)
        self.video_scene.setBackgroundBrush(Qt.NoBrush)
        self.video_item = QGraphicsVideoItem()
        self.video_scene.addItem(self.video_item)
        self.video_item.nativeSizeChanged.connect(lambda _size: self.video_widget.refit())

        self.video_widget = _SimpleVideoView(self.video_scene, self.video_item)
        self.video_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.video_widget.setStyleSheet("border-radius: 0px; background: transparent;")

        self.fallback_label = QLabel()
        self.fallback_label.setAlignment(Qt.AlignCenter)
        self.fallback_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.fallback_label.hide()

        # Loading overlay
        self.loading_label = QLabel(self.tr("Cargando..."), self.preview_container)
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.setStyleSheet("""
            background-color: rgba(0,0,0,185);
            color: #B9E640;
            font-size: 16px;
            font-weight: bold;
            border-radius: 8px;
            padding: 10px 20px;
        """)
        self.loading_label.adjustSize()
        self.loading_label.hide()

        # Error overlay (rojo — mensaje técnico de error)
        self.error_label = QLabel(self.preview_container)
        self.error_label.setAlignment(Qt.AlignCenter)
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("""
            background-color: rgba(30,0,0,210);
            color: #ff5252;
            font-size: 15px;
            font-weight: bold;
            border: 1px solid #d32f2f;
            border-radius: 8px;
            padding: 15px;
        """)
        self.error_label.hide()

        # Info overlay (amarillo — nota informativa debajo del error)
        self.info_label = QLabel(self.preview_container)
        self.info_label.setAlignment(Qt.AlignCenter)
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("""
            background-color: rgba(40,30,0,210);
            color: #FFD740;
            font-size: 12px;
            border: 1px solid #b8860b;
            border-radius: 8px;
            padding: 10px 15px;
        """)
        self.info_label.hide()

        c_layout.addWidget(self.video_widget)
        c_layout.addWidget(self.fallback_label)

        self.video_widget.clicked.connect(self.toggle_play)
        self.preview_container.setCursor(Qt.PointingHandCursor)
        self.fallback_label.setCursor(Qt.PointingHandCursor)
        self.fallback_label.mousePressEvent = lambda e: self.toggle_play() if e.button() == Qt.LeftButton else None
        self.preview_container.resizeEvent = self.on_preview_resize

        left_layout.addWidget(self.preview_container, 1)

        # Media player
        self.media_player = QMediaPlayer(self)
        self.audio_output  = QAudioOutput(self)
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.setVideoOutput(self.video_item)
        self.media_player.playbackStateChanged.connect(self._on_playback_state_changed)
        self.media_player.mediaStatusChanged.connect(self._on_media_status_changed)
        self.media_player.positionChanged.connect(self._on_position_changed)
        self.media_player.errorOccurred.connect(self._on_media_error)

        # ── Compact controls row ────────────────────────────────
        # Layout: [Play][Pause]  |stretch|  [start]─[end][+]  |stretch|  [pos_label]
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(6)

        # Play / Pause
        self.btn_play_ctrl = QPushButton()
        self.btn_play_ctrl.setIconSize(QSize(18, 18))
        self.btn_play_ctrl.setFixedSize(32, 32)
        self.btn_play_ctrl.setToolTip(self.tr("Reproducir"))
        from gui.styles import apply_player_play_button_style
        apply_player_play_button_style(self.btn_play_ctrl, is_playing=False, icon_size=18)
        self.btn_play_ctrl.clicked.connect(self.toggle_play)

        ctrl_row.addWidget(self.btn_play_ctrl)
        ctrl_row.addSpacing(8)
        
        # Control de Volumen Unificado
        self.volume_control = VolumeControlWidget(initial_volume=100, slider_width=60)
        self.volume_control.volume_changed.connect(self._on_volume_changed)
        ctrl_row.addWidget(self.volume_control)
        
        ctrl_row.addStretch()

        # Time in/out + add button (centered group)
        _time_style = f"font-size: 12px; padding: 4px 6px; border-radius: 6px; background: {get_theme_token('fondo_elemento', '#1a1a1a')}; border: 1px solid {get_theme_token('borde_normal', '#222222')}; color: {get_theme_token('texto_activo', '#ffffff')};"

        self.input_time_start = QLineEdit(FragmentManager.format_time(0))
        self.input_time_start.setFixedSize(100, 32)
        self.input_time_start.setAlignment(Qt.AlignCenter)
        self.input_time_start.setObjectName("timeLabel")
        self.input_time_start.setStyleSheet(_time_style)
        self.input_time_start.editingFinished.connect(self._on_time_input_changed)

        sep = QLabel("—")
        sep.setAlignment(Qt.AlignCenter)
        sep.setStyleSheet("color: #666; font-size: 15px;")

        self.input_time_end = QLineEdit(FragmentManager.format_time(self.duration_ms))
        self.input_time_end.setFixedSize(100, 32)
        self.input_time_end.setAlignment(Qt.AlignCenter)
        self.input_time_end.setObjectName("timeLabel")
        self.input_time_end.setStyleSheet(_time_style)
        self.input_time_end.editingFinished.connect(self._on_time_input_changed)

        self.btn_add_ctrl = QPushButton()
        self.btn_add_ctrl.setIcon(_icon("add.svg", "#000000", 18))
        self.btn_add_ctrl.setIconSize(QSize(18, 18))
        self.btn_add_ctrl.setFixedSize(32, 32)
        self.btn_add_ctrl.setToolTip(self.tr("Añadir fragmento"))
        self.btn_add_ctrl.setStyleSheet(f"""
            QPushButton {{
                background-color: {get_theme_token('acento_secundario', '#1DC038')};
                border: none;
                border-radius: 6px;
            }}
            QPushButton:hover {{
                background-color: {get_theme_token('acento_primario', '#B9E640')};
            }}
        """)
        self.btn_add_ctrl.clicked.connect(self.add_fragment)

        ctrl_row.addWidget(self.input_time_start)
        ctrl_row.addWidget(sep)
        ctrl_row.addWidget(self.input_time_end)
        ctrl_row.addSpacing(4)
        ctrl_row.addWidget(self.btn_add_ctrl)
        ctrl_row.addStretch()

        left_layout.addLayout(ctrl_row)

        # Range slider
        self.range_slider = RangeSlider()
        self.range_slider.setMinimum(0)
        self.range_slider.setMaximum(self.duration_ms)
        self.range_slider.range_changed.connect(self.on_slider_changed)
        left_layout.addWidget(self.range_slider)

        # Modes (Radio Buttons)
        sw_row = QHBoxLayout()
        sw_row.setSpacing(20)
        
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        
        self.rb_precise = DeSelectableRadioButton(self.tr("Corte preciso"))
        self.rb_precise.setToolTip(self.tr(
            "Corta al fotograma exacto, evitando errores al inicio o al final del "
            "fragmento. Consume CPU o GPU (según el sistema) y demora bastante más "
            "que una descarga de fragmento normal."
        ))
        self.rb_download = DeSelectableRadioButton(self.tr("Descargar para cortar"))
        self.rb_download.setToolTip(self.tr(
            "Descarga el medio completo, lo corta en disco y luego borra el medio "
            "completo, dejando solo el fragmento."
        ))
        self.rb_keep = DeSelectableRadioButton(self.tr("Conservar completo"))
        self.rb_keep.setToolTip(self.tr(
            "Igual que \"Descargar para cortar\" (descarga el medio completo y "
            "corta en disco), pero conserva el medio completo en vez de borrarlo."
        ))

        for rb, mode_id in [
            (self.rb_precise, FragmentState.PRECISE),
            (self.rb_download, FragmentState.DOWNLOAD_THEN_CUT),
            (self.rb_keep, FragmentState.KEEP_FULL)
        ]:
            rb.setObjectName("fragmentRadioButton")
            rb.setCursor(Qt.PointingHandCursor)
            # Sin stylesheet propio: hereda el QRadioButton global de _base.qss (mismo
            # aspecto y tokens de tema que el resto de radio buttons de la app).
            self.mode_group.addButton(rb)
            sw_row.addWidget(rb)
            
        # No activar ninguno por defecto por ahora (o dejarlo según fragmentos)
        sw_row.addStretch()
        left_layout.addLayout(sw_row)

        content_layout.addWidget(left_panel, 7)

        # ══════════════════════════════
        # RIGHT PANEL
        # ══════════════════════════════
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        # List container (header + list as one rounded unit)
        list_container = QFrame()
        list_container.setObjectName("fragmentList")
        list_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        list_container.setStyleSheet(f"""
            QFrame#fragmentList {{
                background-color: {get_theme_token('fondo_secundario', '#121212')};
                border: 1px solid {get_theme_token('borde_normal', '#222')};
                border-radius: 6px;
            }}
        """)
        list_v = QVBoxLayout(list_container)
        list_v.setContentsMargins(0, 0, 0, 0)
        list_v.setSpacing(0)

        # Header (looks like a table header, inside the rounded box)
        header_widget = QWidget()
        header_widget.setFixedHeight(36)
        header_widget.setStyleSheet(f"""
            background-color: {get_theme_token('fondo_elemento', '#1a1a1a')};
            border-radius: 5px 5px 0 0;
            border-bottom: 1px solid {get_theme_token('borde_sutil', '#2a2a2a')};
        """)
        hh = QHBoxLayout(header_widget)
        hh.setContentsMargins(12, 0, 10, 0)
        lbl_header = QLabel(self.tr("Fragmentos guardados"))
        lbl_header.setAlignment(Qt.AlignCenter)
        lbl_header.setStyleSheet("font-size: 12px; font-weight: bold; color: #aaa; letter-spacing: 0.5px;")
        hh.addWidget(lbl_header)
        list_v.addWidget(header_widget)

        # The actual QListWidget inside the container
        self.list_fragments = QListWidget()
        self.list_fragments.setObjectName("innerFragmentList")
        self.list_fragments.setStyleSheet(f"""
            QListWidget {{
                background: transparent;
                border: none;
                outline: none;
            }}
            QListWidget::item {{
                background-color: {get_theme_token('fondo_elemento', '#1a1a1a')};
                border-bottom: 1px solid {get_theme_token('borde_normal', '#222')};
                border-radius: 0px;
                padding: 0px;
                margin: 0px;
            }}
            QListWidget::item:selected {{
                background-color: #1b3b22;
                border-bottom: 1px solid #224;
            }}
            QListWidget::item:last-child {{
                border-bottom: none;
                border-radius: 0 0 5px 5px;
            }}
        """)
        self.list_fragments.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list_fragments.installEventFilter(self)
        list_v.addWidget(self.list_fragments, 1)

        right_layout.addWidget(list_container, 1)
        right_layout.addSpacing(10)

        # Bottom buttons
        bot = QHBoxLayout()
        bot.setSpacing(10)

        self.btn_cancel = QPushButton(self.tr("Cancelar"))
        self.btn_cancel.setFixedHeight(32)
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #b71c1c, stop:0.6 #e53935, stop:1 #ef5350);
                color: #fff; border: none; font-weight: bold; border-radius: 6px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #c62828, stop:1 #b71c1c);
            }
        """)
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_save = QPushButton(self.tr("Guardar"))
        self.btn_save.setObjectName("analyzeButton")
        self.btn_save.setFixedWidth(110)
        self.btn_save.setFixedHeight(32)
        self.btn_save.clicked.connect(self.accept)

        bot.addWidget(self.btn_cancel, 1)
        bot.addWidget(self.btn_save, 0)
        right_layout.addLayout(bot)

        content_layout.addWidget(right_panel, 3)
        card_layout.addWidget(content_widget, 1)
        overlay_layout.addWidget(self.card)

    # ──────────────────────────────────────────────────────────
    # EVENT FILTER — Delete/Backspace on list
    # ──────────────────────────────────────────────────────────
    def eventFilter(self, obj, event):
        if obj is self.list_fragments and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
                self._remove_selected_fragments()
                return True
        return super().eventFilter(obj, event)

    # ──────────────────────────────────────────────────────────
    # RESIZE
    # ──────────────────────────────────────────────────────────
    def on_preview_resize(self, event):
        from core.logger.logger_manager import logger
        logger.debug(f"[Preview] on_preview_resize fired — container: {self.preview_container.width()}x{self.preview_container.height()}")
        # Center loading label
        self.loading_label.adjustSize()
        lw, lh = self.loading_label.width(), self.loading_label.height()
        self.loading_label.move(
            (self.preview_container.width()  - lw) // 2,
            (self.preview_container.height() - lh) // 2,
        )
        logger.debug(f"[Preview] loading_label: size={lw}x{lh} pos={self.loading_label.pos()} visible={self.loading_label.isVisible()}")
        # Centrar el grupo error + info como bloque vertical
        label_w = self.preview_container.width() - 40
        self.error_label.setFixedWidth(label_w)
        self.error_label.adjustSize()
        ew, eh = self.error_label.width(), self.error_label.height()

        self.info_label.setFixedWidth(label_w)
        self.info_label.adjustSize()
        iw, ih = self.info_label.width(), self.info_label.height()

        gap = 8
        total_h = eh + (gap + ih if not self.info_label.isHidden() else 0)
        group_top = (self.preview_container.height() - total_h) // 2
        cx = self.preview_container.width() // 2
        self.error_label.move(cx - ew // 2, group_top)
        self.info_label.move(cx - iw // 2, group_top + eh + gap)
        # Si hay un error visible, actualizar el fondo con el nuevo tamaño
        if self.error_label.isVisible():
            self._update_error_background()

    # ──────────────────────────────────────────────────────────
    # SLIDER / TIME
    # ──────────────────────────────────────────────────────────
    def on_slider_changed(self, start_val, end_val):
        self.input_time_start.setText(FragmentManager.format_time(start_val))
        self.input_time_end.setText(FragmentManager.format_time(end_val))
        if self.media_player.playbackState() != QMediaPlayer.PlayingState:
            if self.range_slider._active_handle == 'end':
                self.media_player.setPosition(end_val)
            else:
                self.media_player.setPosition(start_val)

    def _on_time_input_changed(self):
        start_ms = self._parse_time(self.input_time_start.text())
        end_ms   = self._parse_time(self.input_time_end.text())
        
        curr_start, curr_end = self.range_slider.get_values()
        
        if start_ms is None: start_ms = curr_start
        if end_ms is None: end_ms = curr_end
        
        if start_ms >= end_ms:
            start_ms = curr_start
            end_ms = curr_end
            
        self.range_slider.set_values(start_ms, end_ms)
        self.input_time_start.setText(FragmentManager.format_time(start_ms))
        self.input_time_end.setText(FragmentManager.format_time(end_ms))

    def _on_position_changed(self, pos_ms):
        """Mueve la cabeza de reproducción del slider y actualiza input_time_start durante reproducción."""
        if self.media_player.playbackState() == QMediaPlayer.PlayingState:
            # Mover la línea de reproducción visualmente
            self.range_slider.set_playhead(pos_ms)
            # Actualizar campo de texto si no tiene foco
            if not self.input_time_start.hasFocus():
                self.input_time_start.setText(FragmentManager.format_time(pos_ms))

    def _parse_time(self, text):
        return FragmentManager.parse_time(text)

    # ──────────────────────────────────────────────────────────
    # PLAYBACK
    # ──────────────────────────────────────────────────────────
    def toggle_play(self):
        if self.media_player.playbackState() == QMediaPlayer.PlayingState:
            self.media_player.pause()
        else:
            start_val, end_val = self.range_slider.get_values()
            current_pos = self.media_player.position()
            
            # Si el usuario acaba de mover el punto final (el video está en end_val),
            # o si el video ya pasó el final del rango, o está antes del inicio,
            # lo regresamos al punto de inicio para que la previsualización del corte
            # se vea completa. Si pausó a la mitad, continuará desde ahí.
            if abs(current_pos - end_val) <= 500 or current_pos < start_val or current_pos >= end_val:
                self.media_player.setPosition(start_val)
                
            self.media_player.play()

    def _on_media_error(self, error, error_string):
        from core.logger.logger_manager import logger
        logger.error(f"FragmentDialog MediaPlayer Error: {error} - {error_string}")
        
        self.loading_label.hide()
        self.video_widget.hide()
        self.btn_play_overlay.hide()
        self.btn_play_ctrl.setEnabled(False)
        # ── Fondo: miniatura con opacidad reducida (si está disponible) ──────────
        self._update_error_background()
        self.fallback_label.show()

        # ── Cartel rojo: solo el error técnico ─────────────────────────────
        error_msg = self.tr("No se puede reproducir la vista previa.")
        self.error_label.setText(f"{error_msg}\n{error_string}")

        # ── Cartel amarillo: nota informativa ───────────────────────────────
        info_msg = self.tr(
            "Aún puedes seleccionar los fragmentos que deseas descargar "
            "usando el control deslizante y el botón +"
        )
        self.info_label.setText(info_msg)

        # Redimensionar ambos con el contenido real y posicionarlos
        label_w = self.preview_container.width() - 40
        cx = self.preview_container.width() // 2

        self.error_label.setFixedWidth(label_w)
        self.error_label.adjustSize()
        ew, eh = self.error_label.width(), self.error_label.height()

        self.info_label.setFixedWidth(label_w)
        self.info_label.adjustSize()
        iw, ih = self.info_label.width(), self.info_label.height()

        gap = 8
        group_top = (self.preview_container.height() - (eh + gap + ih)) // 2
        self.error_label.move(cx - ew // 2, group_top)
        self.info_label.move(cx - iw // 2, group_top + eh + gap)

        self.error_label.show()
        self.error_label.raise_()
        self.info_label.show()
        self.info_label.raise_()

    def _on_volume_changed(self, value):
        float_val = value if isinstance(value, float) else value / 100.0
        self.audio_output.setVolume(float_val)

    def _update_error_background(self):
        """Escala la miniatura para cubrir el contenedor (preservando aspecto)
        y la dibuja con 30% de opacidad sobre fondo negro."""
        if not (self.thumbnail_pixmap and not self.thumbnail_pixmap.isNull()):
            return
        container = self.preview_container.size()
        if container.isEmpty():
            return
        # Escalar cubriendo el contenedor sin distorsionar
        scaled = self.thumbnail_pixmap.scaled(
            container, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
        )
        # Recortar al tamaño exacto del contenedor (centrado)
        if scaled.size() != container:
            x = max(0, (scaled.width()  - container.width())  // 2)
            y = max(0, (scaled.height() - container.height()) // 2)
            scaled = scaled.copy(x, y, container.width(), container.height())
        # Componer: negro + thumbnail al 30%
        bg = QPixmap(container)
        bg.fill(Qt.black)
        painter = QPainter(bg)
        painter.setOpacity(0.30)
        painter.drawPixmap(0, 0, scaled)
        painter.end()
        self.fallback_label.setPixmap(bg)

    def _on_playback_state_changed(self, state):
        playing = (state == QMediaPlayer.PlayingState)
        tooltip = self.tr("Pausar") if playing else self.tr("Reproducir")
        
        from gui.styles import apply_player_play_button_style
        apply_player_play_button_style(self.btn_play_ctrl, is_playing=playing, icon_size=18)
        self.btn_play_ctrl.setToolTip(tooltip)
        
        # Al pausar/detener: restaurar los campos al valor actual del slider y ocultar playhead
        if not playing:
            self.range_slider.set_playhead(None)
            start_val, _ = self.range_slider.get_values()
            self.input_time_start.setText(FragmentManager.format_time(start_val))

    def _on_media_status_changed(self, status):
        from core.logger.logger_manager import logger
        logger.debug(f"[Preview] _on_media_status_changed: {status} — loading_label.isVisible={self.loading_label.isVisible()}")
        # NoMedia es transitorio al llamar setSource() — ignorar.
        if status == QMediaPlayer.NoMedia:
            return

        loading_states = (
            QMediaPlayer.LoadingMedia,
            QMediaPlayer.BufferingMedia,
            QMediaPlayer.StalledMedia,
        )
        ready_states = (
            QMediaPlayer.LoadedMedia,
            QMediaPlayer.BufferedMedia,
        )

        if status in loading_states:
            # Mantener loading label visible
            self.loading_label.show()
            self.loading_label.raise_()
        elif status in ready_states:
            # Media lista: revelar el video widget (ahora sin riesgo de cubrir el label)
            self.loading_label.hide()
            self.video_widget.show()
            self.fallback_label.hide()
        else:
            # InvalidMedia, EndOfMedia, etc.
            self.loading_label.hide()

    # ──────────────────────────────────────────────────────────
    # WINDOW DRAG
    # ──────────────────────────────────────────────────────────
    def title_mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.old_pos = event.globalPosition().toPoint()

    def title_mouseMoveEvent(self, event):
        if self.old_pos is not None:
            delta = QPoint(event.globalPosition().toPoint() - self.old_pos)
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.old_pos = event.globalPosition().toPoint()

    def title_mouseReleaseEvent(self, event):
        self.old_pos = None

    def mousePressEvent(self, event):
        if self.video_widget.geometry().contains(
            self.video_widget.mapFromParent(event.position().toPoint())
        ):
            self.toggle_play()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        # Evitar que QDialog se cierre al presionar Enter en las cajas de texto
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            return
        super().keyPressEvent(event)

    # ──────────────────────────────────────────────────────────
    # FRAGMENTS CRUD
    # ──────────────────────────────────────────────────────────
    def add_fragment(self):
        start_val, end_val = self.range_slider.get_values()
        is_valid, error = FragmentManager.validate_range(start_val, end_val, self.duration_ms)
        
        if not is_valid:
            from gui.dialogs.dialogs import show_warning
            show_warning(self, self.tr("Error"), self.tr(error))
            return
        
        # Generar sufijo por defecto
        n = len(self.fragments) + 1
        if n == 1:
            suffix = "fragment"
        else:
            suffix = f"fragment{n:02d}"
            # Renumerar el primero si era "fragment" genérico
            if len(self.fragments) == 1 and self.fragments[0][2] == "fragment":
                s, e, _ = self.fragments[0]
                self.fragments[0] = (s, e, "fragment01")
            
        self.fragments.append((start_val, end_val, suffix))
        self.is_modified = True
        self._rebuild_list()

    def _on_suffix_changed(self, index, new_suffix):
        """Callback cuando el usuario edita el sufijo de un fragmento."""
        if 0 <= index < len(self.fragments):
            s, e, _ = self.fragments[index]
            self.fragments[index] = (s, e, new_suffix)
            self.is_modified = True

    def _add_item_to_list(self, i, start_txt, end_txt, suffix):
        """Añade un ítem con widget personalizado a la lista."""
        idx_capture = i
        widget = _FragmentItem(
            index=i,
            text=f"  {i + 1}.  {start_txt}  →  {end_txt}",
            suffix=suffix,
            on_delete=lambda checked=False, ii=idx_capture: self._remove_fragment_by_index(ii),
            on_suffix_changed=self._on_suffix_changed,
        )
        item = QListWidgetItem()
        item.setSizeHint(QSize(0, 58))  # Tamaño fijo — ajustado al nuevo _FragmentItem
        self.list_fragments.addItem(item)
        self.list_fragments.setItemWidget(item, widget)

    def _rebuild_list(self):
        """Reconstruye la lista visual desde self.fragments."""
        self.list_fragments.clear()
        for i, (start_ms, end_ms, suffix) in enumerate(self.fragments):
            start_txt = FragmentManager.format_time(start_ms)
            end_txt   = FragmentManager.format_time(end_ms)
            self._add_item_to_list(i, start_txt, end_txt, suffix)

    def _remove_fragment_by_index(self, idx):
        if 0 <= idx < len(self.fragments):
            self.fragments.pop(idx)
            self.is_modified = True
            # Re-numerar sufijos por defecto si son genéricos
            self._renumber_default_suffixes()
            self._rebuild_list()

    def _renumber_default_suffixes(self):
        """Re-numera los sufijos genéricos (fragment01, fragment02...) tras eliminar."""
        import re
        generic_pattern = re.compile(r'^fragment(\d*)$')
        for i, (s, e, suffix) in enumerate(self.fragments):
            if generic_pattern.match(suffix):
                if len(self.fragments) == 1:
                    self.fragments[i] = (s, e, "fragment")
                else:
                    self.fragments[i] = (s, e, f"fragment{i+1:02d}")

    def _remove_selected_fragments(self):
        rows = sorted(
            [self.list_fragments.row(i) for i in self.list_fragments.selectedItems()],
            reverse=True,
        )
        for row in rows:
            if 0 <= row < len(self.fragments):
                self.fragments.pop(row)
                self.is_modified = True
        self._renumber_default_suffixes()
        self._rebuild_list()

    def get_fragments_data(self):
        """Retorna un diccionario con los fragmentos y el modo seleccionado."""
        mode = None
        if self.rb_precise.isChecked(): mode = FragmentState.PRECISE
        elif self.rb_download.isChecked(): mode = FragmentState.DOWNLOAD_THEN_CUT
        elif self.rb_keep.isChecked(): mode = FragmentState.KEEP_FULL
        
        return {
            "fragments": self.fragments.copy(),
            "mode": mode
        }

    # ──────────────────────────────────────────────────────────
    # PREVIEW
    # ──────────────────────────────────────────────────────────
    def load_preview(self):
        if not self.isVisible():
            return
        from core.logger.logger_manager import logger
        logger.debug(f"[Preview] load_preview() iniciado — container: {self.preview_container.width()}x{self.preview_container.height()}")
        if self.stream_url:
            # Mantener video_widget OCULTO hasta que haya datos reales, para no mostrar
            # un cuadro negro vacío antes de que cargue el medio. El loading_label se
            # muestra sobre fallback_label mientras tanto.
            self.video_widget.hide()
            self.fallback_label.show()
            self.loading_label.show()
            self.loading_label.raise_()
            logger.debug(f"[Preview] loading_label.show() — isVisible={self.loading_label.isVisible()} pos={self.loading_label.pos()} size={self.loading_label.size()}")

            playback_url = self.stream_url
            try:
                from core.utils.stream_proxy import build_proxy_url
                proxy = build_proxy_url(self.stream_url, self.source_url)
                if proxy:
                    playback_url = proxy
                    logger.debug(f"FragmentDialog: Usando proxy local → {proxy[:60]}...")
            except Exception as _e:
                logger.warning(f"FragmentDialog: Proxy no disponible, usando URL directa: {_e}")

            self.media_player.setSource(QUrl(playback_url))
            self.media_player.pause()
        else:
            self.video_widget.hide()
            self.fallback_label.show()
            self.loading_label.hide()
            if self.thumbnail_pixmap and not self.thumbnail_pixmap.isNull():
                self.fallback_label.setPixmap(self.thumbnail_pixmap.scaled(
                    640, 360, Qt.KeepAspectRatio, Qt.SmoothTransformation
                ))

    # ──────────────────────────────────────────────────────────
    # CLOSE
    # ──────────────────────────────────────────────────────────
    def cleanup_media_player(self):
        """Libera los recursos del QMediaPlayer para evitar bloqueos del hilo principal,
        y reactiva la ventana principal - sin esto (ver conversación: quedaba en un
        bloque de código muerto que nunca se ejecutaba) la ventana principal podía
        quedar en un estado de activación/foco raro al cerrar este diálogo."""
        try:
            self.media_player.stop()
            self.media_player.setSource(QUrl())
            self.media_player.setVideoOutput(None)
            self.media_player.setAudioOutput(None)
        except Exception as e:
            from core.logger.logger_manager import logger
            logger.warning(f"Error limpiando QMediaPlayer en FragmentDialog: {e}")

        win = self.parent().window() if self.parent() else None
        if win:
            win.activateWindow()
            win.raise_()

    def reject(self):
        self.cleanup_media_player()
        super().reject()

    def accept(self):
        self.cleanup_media_player()
        super().accept()

    def closeEvent(self, event):
        self.cleanup_media_player()
        super().closeEvent(event)
