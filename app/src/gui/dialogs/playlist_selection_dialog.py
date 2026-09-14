import queue
from PySide6.QtCore import QCoreApplication
import concurrent.futures
import requests
import threading
import time
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from gui.widgets.toggle_switch import ToggleSwitch
from gui.widgets.combo_box import AutoPopupComboBox
from gui.widgets.title_bar import CustomTitleBar
from gui.tabs.advanced_process.video_details_components import RichComboBox, RichTextDelegate

PLAYLIST_MODE_OPTIONS = [
    (QCoreApplication.translate("playlist_selection_dialog", "Video + Audio"), "video+audio"),
    (QCoreApplication.translate("playlist_selection_dialog", "Solo Audio"), "audio_only"),
]

PLAYLIST_QUALITY_OPTIONS = [
    (QCoreApplication.translate("playlist_selection_dialog", "Mejor compatible"), "best_compatible"),
    (QCoreApplication.translate("playlist_selection_dialog", "Mejor Calidad"), "best"),
    (QCoreApplication.translate("playlist_selection_dialog", "Hasta 2160p"), "2160"),
    (QCoreApplication.translate("playlist_selection_dialog", "Hasta 1440p"), "1440"),
    (QCoreApplication.translate("playlist_selection_dialog", "Hasta 1080p"), "1080"),
    (QCoreApplication.translate("playlist_selection_dialog", "Hasta 720p"), "720"),
    (QCoreApplication.translate("playlist_selection_dialog", "Hasta 480p"), "480"),
]

AUDIO_QUALITY_OPTIONS = [
    (QCoreApplication.translate("playlist_selection_dialog", "Mejor compatible"), "best_compatible"),
    (QCoreApplication.translate("playlist_selection_dialog", "Mejor Calidad"), "best"),
    (QCoreApplication.translate("playlist_selection_dialog", "Alta (320kbps)"), "320"),
    (QCoreApplication.translate("playlist_selection_dialog", "Media (192kbps)"), "192"),
    (QCoreApplication.translate("playlist_selection_dialog", "Baja (128kbps)"), "128"),
]


def format_duration(seconds):
    if seconds is None:
        return "-"
    try:
        seconds = int(float(seconds))
    except (TypeError, ValueError):
        return "-"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def entry_title(entry, index):
    title = entry.get("title") or entry.get("id") or entry.get("url") or f"Item {index + 1}"
    return str(title).strip() or f"Item {index + 1}"


def entry_thumbnail_url(entry):
    if entry.get("thumbnail"):
        return entry.get("thumbnail")
    thumbs = entry.get("thumbnails") or []
    valid = [t for t in thumbs if t.get("url")]
    if not valid:
        return None
    valid.sort(key=lambda t: (t.get("width") or 0) * (t.get("height") or 0), reverse=True)
    return valid[0].get("url")


class ThumbnailWorker(QThread):
    thumbnail_loaded = Signal(int, bytes)

    def __init__(self, entries, initial_cache=None):
        super().__init__()
        self.entries = entries
        self._running = True
        self.visible_indices = set()
        self.downloaded_indices = set()
        self.cache = {}
        self.lock = threading.Lock()
        # Pre-cargar caché de sesiones anteriores
        if initial_cache:
            self.cache.update(initial_cache)
            self.downloaded_indices.update(initial_cache.keys())

    def update_visible_indices(self, indices):
        with self.lock:
            self.visible_indices = set(indices)

    def stop(self):
        self._running = False

    def emit_cached_for_visible(self):
        """Emite señales para las miniaturas ya cacheadas que están visibles."""
        with self.lock:
            for idx in list(self.visible_indices):
                if idx in self.cache:
                    self.thumbnail_loaded.emit(idx, self.cache[idx])

    def run(self):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        }
        max_workers = 5
        
        def download_thumb(idx):
            if not self._running:
                return
            url = entry_thumbnail_url(self.entries[idx])
            if not url:
                with self.lock:
                    self.downloaded_indices.add(idx)
                return
            try:
                response = requests.get(url, headers=headers, timeout=2)
                if response.status_code == 200 and response.content:
                    if self._running:
                        with self.lock:
                            self.cache[idx] = response.content
                        self.thumbnail_loaded.emit(idx, response.content)
            except Exception:
                pass
            with self.lock:
                self.downloaded_indices.add(idx)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            while self._running:
                # Limpiar futures completados
                with self.lock:
                    done = [idx for idx, f in futures.items() if f.done()]
                    for idx in done:
                        del futures[idx]

                # Llenar todos los slots disponibles del pool
                submitted_any = False
                slots_available = max_workers - len(futures)
                if slots_available > 0:
                    with self.lock:
                        pending_visible = self.visible_indices - self.downloaded_indices - set(futures.keys())
                        to_download = list(pending_visible)[:slots_available]
                    
                    for idx in to_download:
                        future = executor.submit(download_thumb, idx)
                        with self.lock:
                            futures[idx] = future
                        submitted_any = True
                
                if not submitted_any:
                    time.sleep(0.05)


class PlaylistItemRow(QFrame):
    def __init__(self, index, entry, parent=None):
        super().__init__(parent)
        self.index = index
        self.entry = entry
        self.setObjectName("playlistItemRow")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        self.check = ToggleSwitch()
        self.check.setChecked(True)
        layout.addWidget(self.check)

        self.thumb = QLabel()
        self.thumb.setFixedSize(96, 54)
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setText("...")
        self.thumb.setStyleSheet("background: #151515; color: #888; border: 1px solid #333; border-radius: 4px;")
        layout.addWidget(self.thumb)

        text_col = QVBoxLayout()
        self.title = QLabel(entry_title(entry, index))
        self.title.setWordWrap(False)
        self.title.setStyleSheet("font-weight: 600;")
        self.title.setToolTip(self.title.text())
        self.meta = QLabel(f"#{index + 1}  |  {format_duration(entry.get('duration'))}")
        self.meta.setStyleSheet("color: #888; font-size: 11px;")
        text_col.addWidget(self.title)
        text_col.addWidget(self.meta)
        layout.addLayout(text_col, 1)

        self.setStyleSheet("""
            QFrame#playlistItemRow {
                background: #171717;
                border: 1px solid #2e2e2e;
                border-radius: 6px;
            }
        """)

    def set_thumbnail(self, data):
        pix = QPixmap()
        if not pix.loadFromData(data) or pix.isNull():
            return
        pix = pix.scaled(96, 54, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        self.thumb.setPixmap(pix)
        self.thumb.setText("")


class PlaylistSelectionDialog(QDialog):
    def __init__(self, playlist_info, parent=None, initial_config=None, thumbnail_cache=None):
        super().__init__(parent)
        self.playlist_info = playlist_info or {}
        self.initial_config = initial_config or {}
        self._initial_thumb_cache = thumbnail_cache or {}
        self.result_data = None
        self.thumb_worker = None

        self.entries = [e for e in (self.playlist_info.get("entries") or []) if e]
        self.visible_rows = {}
        self.row_height = 74
        self.check_vars = {i: True for i in range(len(self.entries))}

        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        self.resize(760, 620)
        self.setMinimumSize(640, 480)
        self._init_ui()
        self._restore_initial_state()
        self._start_thumbnail_worker()

        # Render inicial inmediato
        QTimer.singleShot(10, self._on_scroll)

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        self.central_widget = QFrame()
        self.central_widget.setObjectName("PlaylistDialogContainer")
        self.central_widget.setStyleSheet("""
            QFrame#PlaylistDialogContainer {
                background-color: #0d0d0d;
                border: 1px solid #333333;
                border-radius: 12px;
            }
        """)
        
        layout = QVBoxLayout(self.central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        title_text = self.playlist_info.get("title") or self.tr("Configurar Playlist")
        self.title_bar = CustomTitleBar(self, title_text)
        self.title_bar.btn_min.hide()
        self.title_bar.btn_max.hide()
        self.title_bar.btn_close.clicked.disconnect()
        self.title_bar.btn_close.clicked.connect(self.reject)
        layout.addWidget(self.title_bar)
        
        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(16, 16, 16, 16)
        content_layout.setSpacing(14)

        controls = QHBoxLayout()
        controls.setSpacing(8)

        self.btn_all = QPushButton(self.tr("Marcar todos"))
        self.btn_all.setObjectName("secondaryButton")
        self.btn_all.setFixedHeight(30)
        self.btn_none = QPushButton(self.tr("Deseleccionar todos"))
        self.btn_none.setObjectName("secondaryButton")
        self.btn_none.setFixedHeight(30)
        self.btn_all.clicked.connect(lambda: self._set_all(True))
        self.btn_none.clicked.connect(lambda: self._set_all(False))
        controls.addWidget(self.btn_all)
        controls.addWidget(self.btn_none)
        controls.addStretch()

        controls.addWidget(QLabel(self.tr("Modo")))
        self.mode_combo = AutoPopupComboBox()
        for label, value in PLAYLIST_MODE_OPTIONS:
            self.mode_combo.addItem(self.tr(label), value)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        controls.addWidget(self.mode_combo)

        controls.addWidget(QLabel(self.tr("Calidad")))
        self.quality_combo = RichComboBox()
        self.quality_combo.setItemDelegate(RichTextDelegate(self.quality_combo))
        controls.addWidget(self.quality_combo)
        content_layout.addLayout(controls)

        self.scroll = QScrollArea()
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("border: none; background: transparent;")
        
        self.items_container = QWidget()
        self.items_container.setMinimumHeight(len(self.entries) * self.row_height)
        self.scroll.setWidget(self.items_container)
        content_layout.addWidget(self.scroll, 1)

        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scroll)

        footer = QHBoxLayout()
        self.count_label = QLabel()
        footer.addWidget(self.count_label)
        footer.addStretch()
        cancel = QPushButton(self.tr("Cancelar"))
        cancel.setFixedWidth(110)
        cancel.setFixedHeight(35)
        cancel.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #b71c1c, stop:0.6 #e53935, stop:1 #ef5350);
                color: #fff; border: none; font-weight: bold; border-radius: 12px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #c62828, stop:1 #b71c1c);
            }
        """)
        accept = QPushButton(self.tr("Aceptar"))
        accept.setObjectName("analyzeButton")
        accept.setFixedWidth(110)
        accept.setFixedHeight(35)
        cancel.clicked.connect(self.reject)
        accept.clicked.connect(self._accept_selection)
        footer.addWidget(cancel)
        footer.addWidget(accept)
        content_layout.addLayout(footer)

        layout.addLayout(content_layout)
        main_layout.addWidget(self.central_widget)

        self._update_count()

    def _on_mode_changed(self):
        mode = self.mode_combo.currentData()
        self.quality_combo.clear()
        if mode == "video+audio":
            for label, value in PLAYLIST_QUALITY_OPTIONS:
                display_text = label + " ✨" if value == "best_compatible" else label
                self.quality_combo.addItem(display_text, value)
        else:
            for label, value in AUDIO_QUALITY_OPTIONS:
                display_text = label + " ✨" if value == "best_compatible" else label
                self.quality_combo.addItem(display_text, value)

    def _restore_initial_state(self):
        mode = self.initial_config.get("playlist_mode")
        if mode:
            idx = self.mode_combo.findData(mode)
            if idx >= 0:
                self.mode_combo.setCurrentIndex(idx)
        
        self._on_mode_changed()

        quality = self.initial_config.get("playlist_quality")
        if quality:
            idx = self.quality_combo.findData(quality)
            if idx >= 0:
                self.quality_combo.setCurrentIndex(idx)

        selected = self.initial_config.get("selected_indices")
        if selected is not None:
            selected_set = set(selected)
            for i in self.check_vars:
                self.check_vars[i] = (i in selected_set)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._on_scroll()

    def _on_scroll(self, value=0):
        if not hasattr(self, 'items_container'):
            return
            
        viewport_height = self.scroll.viewport().height()
        container_width = self.scroll.viewport().width()
        scroll_y = self.scroll.verticalScrollBar().value()
        
        start_idx = max(0, scroll_y // self.row_height)
        end_idx = min(len(self.entries), (scroll_y + viewport_height) // self.row_height + 2)
        
        visible_indices = set(range(start_idx, end_idx))
        
        for idx in list(self.visible_rows.keys()):
            if idx not in visible_indices:
                row = self.visible_rows.pop(idx)
                row.deleteLater()
                
        for idx in visible_indices:
            if idx not in self.visible_rows:
                row = PlaylistItemRow(idx, self.entries[idx], self.items_container)
                row.check.setChecked(self.check_vars[idx])
                row.check.toggled.connect(lambda checked, i=idx: self._on_row_checked(i, checked))
                row.show()
                self.visible_rows[idx] = row
                
                if self.thumb_worker and idx in self.thumb_worker.cache:
                    row.set_thumbnail(self.thumb_worker.cache[idx])
                
        for idx, row in self.visible_rows.items():
            row.setGeometry(0, idx * self.row_height, container_width - 4, self.row_height - 4)
            
        if self.thumb_worker:
            self.thumb_worker.update_visible_indices(visible_indices)

    def _on_row_checked(self, idx, checked):
        self.check_vars[idx] = checked
        self._update_count()

    def _start_thumbnail_worker(self):
        self.thumb_worker = ThumbnailWorker(self.entries, initial_cache=self._initial_thumb_cache)
        self.thumb_worker.thumbnail_loaded.connect(self._on_thumbnail_loaded)
        self.thumb_worker.start()
        # Emitir miniaturas cacheadas para las filas visibles inmediatamente
        if self._initial_thumb_cache:
            QTimer.singleShot(50, self.thumb_worker.emit_cached_for_visible)

    def _on_thumbnail_loaded(self, index, data):
        if index in self.visible_rows:
            self.visible_rows[index].set_thumbnail(data)

    def _set_all(self, checked):
        for idx in self.check_vars:
            self.check_vars[idx] = checked
        for row in self.visible_rows.values():
            row.check.blockSignals(True)
            row.check.setChecked(checked)
            row.check.blockSignals(False)
        self._update_count()

    def _update_count(self):
        selected = sum(1 for v in self.check_vars.values() if v)
        self.count_label.setText(self.tr("{0} de {1} seleccionados").format(selected, len(self.entries)))

    def _get_thumbnail_cache(self):
        """Devuelve el caché actual de miniaturas del worker."""
        if self.thumb_worker:
            with self.thumb_worker.lock:
                return dict(self.thumb_worker.cache)
        return self._initial_thumb_cache.copy() if self._initial_thumb_cache else {}

    def _accept_selection(self):
        selected = [i for i, v in self.check_vars.items() if v]
        self.result_data = {
            "selected_indices": selected,
            "playlist_mode": self.mode_combo.currentData(),
            "playlist_quality": self.quality_combo.currentData(),
            "total_videos": len(self.entries),
            "thumbnail_cache": self._get_thumbnail_cache(),
        }
        self.accept()

    def closeEvent(self, event):
        if self.thumb_worker:
            self.thumb_worker.stop()
            self.thumb_worker.wait(500)
        super().closeEvent(event)

    def reject(self):
        if self.thumb_worker:
            self.thumb_worker.stop()
            self.thumb_worker.wait(500)
        super().reject()

    def accept(self):
        if self.thumb_worker:
            self.thumb_worker.stop()
            self.thumb_worker.wait(500)
        super().accept()
