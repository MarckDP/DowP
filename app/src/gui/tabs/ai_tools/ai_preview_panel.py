# src/gui/tabs/ai_tools/ai_preview_panel.py
"""
Columna central de Herramientas IA: "Vista Previa y Detalles", con las mismas piezas
que el Gestor de Medios en vez del reproductor con línea de tiempo de Multimedia:

- el reproductor del Gestor (PreviewContainerWidget), con Play, Repetir y la tijera
  (editor de subclips, para cortes precisos o varios tramos);
- la forma de onda del Gestor (AudioWaveformWidget): clic izquierdo para moverse, clic
  derecho y arrastrar para marcar el tramo a procesar (rápido, no tan preciso);
- la información técnica, con lo que importa para la IA (fotogramas a procesar,
  resolución de salida), y los botones "Abrir en Explorador" y "Enviar al editor".

Cumple lo que MediaWorkbenchTab le pide a su vista previa (load_media, clear, set_fps,
get_audio_track_selection y las señales range_changed / audio_track_selection_changed),
así la base guarda el tramo de cada fila igual que en Multimedia (_trim_cache).
"""
import os

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QToolButton, QVBoxLayout,
    QWidget,
)

from gui.styles import apply_folder_open_button_style, get_theme_token, set_themed_style
from gui.tabs.editing_media.preview_panel import PreviewContainerWidget
from gui.tabs.editing_media.waveform_widget import AudioWaveformWidget
from gui.widgets.animated_button import AnimatedButton


def _format_seconds(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0.0))
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(int(minutes), 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:04.1f}"
    return f"{minutes:02d}:{secs:04.1f}"


class AIPreviewPanel(QFrame):
    """Vista previa compacta + detalles (ver docstring del módulo)."""

    range_changed = Signal(float, float)
    # La IA no elige pista de audio: existe solo por el contrato con la base.
    audio_track_selection_changed = Signal()
    subclip_editor_requested = Signal()
    reveal_requested = Signal()
    send_to_editor_requested = Signal()

    # Si los picos de audio no llegan en este tiempo (video sin audio, o ffmpeg no
    # pudo leerlo), se dibuja la regla de tiempo en vez de dejar la animación de carga.
    _PEAKS_TIMEOUT_MS = 4000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("aiPreviewPanel")
        self._path = ""
        self._duration = 0.0
        self._fps = 30.0
        self._trim = None  # (in, out) en segundos, o None = video entero
        self._duration_exact = False

        # Una sola tarjeta: reproductor, forma de onda y detalles van dentro, separados por
        # una línea fina en vez de tener cada uno su propio borde.
        set_themed_style(self, lambda: f"""
            QFrame#aiPreviewPanel {{
                background-color: {get_theme_token('fondo_secundario', '#121212')};
                border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                border-radius: 6px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)

        # 1. Reproductor del Gestor (la tijera abre el editor de subclips)
        self.preview_box = PreviewContainerWidget(self)
        # Todo el alto que deje la columna (modo del Editor de Imagen), no el tope de
        # ancho x 0.6 del Gestor: aquí la columna es angosta y quedaba un hueco encima.
        self.preview_box.set_fill_available_space(True)
        # En ventanas bajas cede alto antes que los detalles (el Gestor pide 140).
        self.preview_box.setMinimumHeight(90)
        # Sin borde ni fondo propios: es parte de la tarjeta del panel (el Gestor la
        # pinta como recuadro suelto).
        set_themed_style(self.preview_box, lambda: """
            QFrame#previewContainer {
                background: transparent;
                border: none;
                border-radius: 0px;
            }
        """)
        self.preview_box.btn_edit_subclip.setToolTip(self.tr(
            "Recorte preciso: marca uno o varios tramos; cada tramo entra a la cola por separado."))
        self.preview_box.btn_edit_subclip.clicked.connect(self.subclip_editor_requested)
        layout.addWidget(self.preview_box, 1)

        # 2. Forma de onda con selección rápida (clic derecho y arrastrar)
        self.wave_frame = QFrame(self)
        self.wave_frame.setObjectName("aiWaveFrame")
        set_themed_style(self.wave_frame, lambda: f"""
            QFrame#aiWaveFrame {{
                background: transparent;
                border: none;
                border-top: 1px solid {get_theme_token('borde_sutil', '#2d2d2d')};
                border-radius: 0px;
            }}
        """)
        wave_layout = QVBoxLayout(self.wave_frame)
        wave_layout.setContentsMargins(8, 6, 8, 6)
        wave_layout.setSpacing(4)
        self.waveform = AudioWaveformWidget(self.wave_frame)
        self.waveform.setToolTip(self.tr(
            "Clic para moverte por el video. Clic derecho y arrastra para marcar el tramo a "
            "procesar; un clic derecho sin arrastrar lo quita."))
        self.waveform.seek_requested.connect(self._on_seek_requested)
        self.waveform.lite_selection_changed.connect(self._on_lite_selection_changed)
        wave_layout.addWidget(self.waveform)
        self.lbl_wave_hint = QLabel(self.tr("Clic derecho y arrastra para marcar un tramo · Tijera para cortes precisos"))
        self.lbl_wave_hint.setWordWrap(True)
        set_themed_style(self.lbl_wave_hint, lambda: f"color: {get_theme_token('texto_suave', '#a6adc8')}; font-size: 10px; background: transparent; border: none;")
        wave_layout.addWidget(self.lbl_wave_hint)
        layout.addWidget(self.wave_frame)

        # 3. Información técnica
        self.info_box = QFrame(self)
        self.info_box.setObjectName("aiInfoBox")
        set_themed_style(self.info_box, lambda: f"""
            QFrame#aiInfoBox {{
                background: transparent;
                border: none;
                border-top: 1px solid {get_theme_token('borde_sutil', '#2d2d2d')};
                border-radius: 0px;
            }}
            QFrame#aiInfoBox QLabel {{ background: transparent; border: none; }}
        """)
        info_layout = QVBoxLayout(self.info_box)
        info_layout.setContentsMargins(10, 8, 10, 8)
        info_layout.setSpacing(6)
        lbl_info_title = QLabel(self.tr("Información Técnica"))
        set_themed_style(lbl_info_title, lambda: f"font-weight: bold; font-size: 12px; color: {get_theme_token('texto_suave', '#a6adc8')};")
        info_layout.addWidget(lbl_info_title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        self._fields = {}
        fields = [
            ("nombre", self.tr("Nombre:")),
            ("resolución", self.tr("Resolución:")),
            ("fps", self.tr("FPS:")),
            ("duración", self.tr("Duración:")),
            ("video_codec", self.tr("Códec Video:")),
            ("audio_codec", self.tr("Códec Audio:")),
            ("tramo", self.tr("Tramo:")),
            ("fotogramas", self.tr("Fotogramas:")),
            ("salida", self.tr("Salida:")),
        ]
        self._field_order = [key for key, _text in fields]
        self._field_keys = {}
        for key, text in fields:
            lbl_key = QLabel(text)
            set_themed_style(lbl_key, lambda: f"color: {get_theme_token('texto_clave', '#89b4fa')}; font-size: 11px; font-weight: bold;")
            lbl_val = QLabel("-")
            lbl_val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lbl_val.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            set_themed_style(lbl_val, lambda: f"color: {get_theme_token('texto_valor', '#cdd6f4')}; font-size: 11px;")
            self._field_keys[key] = lbl_key
            self._fields[key] = lbl_val
        self._grid = grid
        self._two_columns = None
        self._place_fields(two_columns=True)
        # Con scroll propio (como el Gestor): en ventanas bajas las filas no se pisan.
        grid_host = QWidget()
        # Con selector, para no heredarlo al menú contextual de los textos seleccionables.
        grid_host.setObjectName("aiInfoGrid")
        grid_host.setStyleSheet("QWidget#aiInfoGrid { background: transparent; }")
        grid_host.setLayout(grid)
        self.info_scroll = QScrollArea(self.info_box)
        self.info_scroll.setWidgetResizable(True)
        self.info_scroll.setFrameShape(QFrame.NoFrame)
        self.info_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.info_scroll.viewport().setAutoFillBackground(False)
        self.info_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.info_scroll.setWidget(grid_host)
        self.info_scroll.setMinimumHeight(48)
        self.info_scroll.setMaximumHeight(grid_host.sizeHint().height() + 4)
        info_layout.addWidget(self.info_scroll)

        # Botones del Gestor: Abrir en Explorador + Enviar al editor
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.btn_reveal = AnimatedButton("")
        self.btn_reveal.setFixedSize(34, 34)
        apply_folder_open_button_style(self.btn_reveal, self.tr("Abrir en Explorador"), icon_size=20)
        self.btn_reveal.setEnabled(False)
        self.btn_reveal.clicked.connect(self.reveal_requested)
        buttons.addWidget(self.btn_reveal)

        self.btn_send_editor = QToolButton()
        self.btn_send_editor.setObjectName("sendEditorButton")
        self.btn_send_editor.setFixedHeight(34)
        self.btn_send_editor.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_send_editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btn_send_editor.setCursor(Qt.PointingHandCursor)
        set_themed_style(self.btn_send_editor, lambda: f"""
            QToolButton {{
                background-color: {get_theme_token('fondo_elemento', '#2d2d2d')};
                border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                border-radius: 8px;
                color: {get_theme_token('texto_valor', '#cdd6f4')};
                padding-left: 10px;
                padding-right: 10px;
                font-weight: 500;
            }}
            QToolButton:hover {{
                border-color: {get_theme_token('acento_primario', '#B9E640')};
            }}
            QToolButton:disabled {{
                color: {get_theme_token('texto_deshabilitado', '#6c7086')};
            }}
        """)
        self.btn_send_editor.clicked.connect(self.send_to_editor_requested)
        buttons.addWidget(self.btn_send_editor, 1)
        info_layout.addLayout(buttons)
        layout.addWidget(self.info_box)

        player = self.preview_box.media_player
        if player is not None:
            player.positionChanged.connect(self._on_player_position)
            player.durationChanged.connect(lambda ms: ms > 0 and self.set_duration(ms / 1000.0, exact=True))

        self._peaks_timer = QTimer(self)
        self._peaks_timer.setSingleShot(True)
        self._peaks_timer.setInterval(self._PEAKS_TIMEOUT_MS)
        self._peaks_timer.timeout.connect(self._show_ruler)
        from core.tabs.editing_media.waveform_cache_manager import WaveformCacheManager
        WaveformCacheManager.get_instance().waveform_loaded.connect(self._on_peaks_loaded)

        self.clear()

    # ------------------------------------------------------------------
    # Contrato con MediaWorkbenchTab
    # ------------------------------------------------------------------
    def load_media(self, filepath, media_type, duration_sec, fps,
                   initial_in_sec=None, initial_out_sec=None, initial_audio_track_selection=None):
        self._path = filepath
        self._duration = float(duration_sec or 0.0)
        self._duration_exact = False
        self._fps = float(fps or 30.0)
        if initial_in_sec is not None and initial_out_sec is not None:
            self._trim = (float(initial_in_sec), float(initial_out_sec))
        else:
            self._trim = None
        if media_type == "video":
            self.preview_box.show_video_preview(filepath)
            # El reproductor del Gestor arranca solo. Con la vista previa oculta (vista
            # angosta mostrando la Cola) solo se oía el audio de fondo: ahí queda en pausa,
            # en el mismo ciclo, antes de que llegue a sonar.
            if not self.isVisible():
                self.pause()
        else:
            self.preview_box.show_audio_preview(filepath)
        self._load_waveform(filepath)
        self._sync_waveform_selection()
        self._refresh_trim_fields()
        self.btn_reveal.setEnabled(True)

    def clear(self):
        self._path = ""
        self._duration = 0.0
        self._trim = None
        self._peaks_timer.stop()
        self.preview_box.stop_media()
        self.preview_box.show_default_state()
        self.waveform.set_audio_path("")
        self.waveform.clear_lite_selection()
        self.waveform.set_video_only(True, 0.0, 30.0)
        self.preview_box.set_edit_subclip_active(False)
        for label in self._fields.values():
            label.setText("-")
        self.btn_reveal.setEnabled(False)

    def set_fps(self, fps: float):
        self._fps = float(fps or 30.0)
        self._refresh_trim_fields()

    def set_duration(self, duration_sec: float, exact: bool = False):
        """Duración real del archivo. Al seleccionar una fila recién agregada, el caché
        de metadata todavía no la tiene y la base carga con 1 s de respaldo: esto la
        corrige en cuanto llega. La del reproductor (`exact`, al milisegundo) manda sobre
        la de la metadata, que viene redondeada a segundos ("00:02")."""
        duration_sec = float(duration_sec or 0.0)
        if not self._path or duration_sec <= 0 or (self._duration_exact and not exact):
            return
        self._duration_exact = self._duration_exact or exact
        if abs(duration_sec - self._duration) < 0.001:
            return
        self._duration = duration_sec
        if self.waveform.is_video_only:
            self.waveform.set_video_only(True, self._duration, self._fps)
        self._sync_waveform_selection()
        self._refresh_trim_fields()

    def get_audio_track_selection(self):
        return None

    # ------------------------------------------------------------------
    # Uso desde la pestaña
    # ------------------------------------------------------------------
    def current_path(self) -> str:
        return self._path

    def duration(self) -> float:
        return self._duration

    def fps(self) -> float:
        return self._fps

    def trim(self):
        """(in, out) en segundos del tramo marcado, o None si es el video entero."""
        return self._trim

    def set_range(self, in_sec: float, out_sec: float):
        """Fija el tramo desde fuera (editor de subclips) y avisa a la base."""
        self._trim = (float(in_sec), float(out_sec))
        self._sync_waveform_selection()
        self._refresh_trim_fields()
        self.range_changed.emit(self._trim[0], self._trim[1])

    def set_details(self, meta: dict, output_text: str = "-"):
        """Información técnica del archivo en vista previa (metadata de ffprobe) y la
        resolución de salida que calculó la pestaña según la función de IA."""
        meta = meta or {}
        self._fields["nombre"].setText(os.path.basename(self._path) if self._path else "-")
        for key in ("resolución", "fps", "duración", "video_codec", "audio_codec"):
            value = meta.get(key)
            self._fields[key].setText(str(value) if value not in (None, "") else "-")
        self._fields["salida"].setText(output_text or "-")
        self._refresh_trim_fields()
        # Con la metadata completa ya se sabe si hay audio: sin audio, la regla de tiempo.
        if meta.get("audio_codec") == "-" and meta.get("video_codec") not in (None, "-"):
            self._show_ruler()

    def set_editor_state(self, text: str, enabled: bool, icon=None):
        self.btn_send_editor.setText(text)
        self.btn_send_editor.setEnabled(enabled)
        if icon is not None:
            self.btn_send_editor.setIcon(icon)

    def pause(self):
        player = self.preview_box.media_player
        if player is not None:
            player.pause()

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------
    def _load_waveform(self, path: str):
        from core.tabs.editing_media.waveform_cache_manager import WaveformCacheManager
        manager = WaveformCacheManager.get_instance()
        self.waveform.set_video_only(False)
        self.waveform.set_audio_path(path)
        self.waveform.set_playback_ratio(0.0)
        peaks = manager.get_cached_peaks(path)
        if peaks:
            self.waveform.set_peaks(peaks)
            return
        if peaks is not None:  # en caché, pero vacío: no tiene audio
            self._show_ruler()
            return
        self.waveform.set_loading(True)
        self._peaks_timer.start()
        manager.request_waveform(path, 120, interactive=True)

    def _on_peaks_loaded(self, path: str, peaks: list):
        if path != self._path:
            return
        self._peaks_timer.stop()
        if peaks:
            self.waveform.set_video_only(False)
            self.waveform.set_peaks(peaks)
            self._sync_waveform_selection()
        else:
            self._show_ruler()

    def _show_ruler(self):
        """Video sin audio (o picos que no llegaron): regla de tiempo, igual que el Gestor."""
        if not self._path or (self.waveform.peaks and not self.waveform.is_loading):
            return
        self._peaks_timer.stop()
        self.waveform.set_video_only(True, self._duration, self._fps)
        self._sync_waveform_selection()

    def _sync_waveform_selection(self):
        if self._trim and self._duration > 0:
            self.waveform.set_lite_selection(self._trim[0] / self._duration, self._trim[1] / self._duration)
        else:
            self.waveform.clear_lite_selection()
        self.preview_box.set_edit_subclip_active(bool(self._trim))

    def _on_lite_selection_changed(self, in_ratio: float, out_ratio: float):
        if not self._path or self._duration <= 0:
            return
        if in_ratio < 0 or out_ratio < 0:
            self._trim = None
            self.range_changed.emit(0.0, self._duration)
        else:
            self._trim = (in_ratio * self._duration, out_ratio * self._duration)
            self.range_changed.emit(self._trim[0], self._trim[1])
        self.preview_box.set_edit_subclip_active(bool(self._trim))
        self._refresh_trim_fields()

    def _refresh_trim_fields(self):
        if not self._path or self._duration <= 0:
            self._fields["tramo"].setText("-")
            self._fields["fotogramas"].setText("-")
            return
        start, end = self._trim if self._trim else (0.0, self._duration)
        length = max(0.0, end - start)
        if self._trim:
            self._fields["tramo"].setText(self.tr("{0} – {1} ({2} s)").format(
                _format_seconds(start), _format_seconds(end), f"{length:.1f}"))
        else:
            self._fields["tramo"].setText(self.tr("Video completo"))
        # Estimado (duración × fps): un video con huecos al inicio puede tener menos.
        self._fields["fotogramas"].setText("≈ " + f"{int(round(length * self._fps)):,}".replace(",", "."))

    def _on_seek_requested(self, ratio: float):
        player = self.preview_box.media_player
        if player is not None and player.duration() > 0:
            player.setPosition(int(player.duration() * ratio))

    def _on_player_position(self, position: int):
        player = self.preview_box.media_player
        if player is not None and player.duration() > 0:
            self.waveform.set_playback_ratio(position / player.duration())

    # Por debajo de este ancho, los detalles van en una sola columna.
    _TWO_COLUMNS_MIN_WIDTH = 400

    def _place_fields(self, two_columns: bool):
        """Nombre, tramo y salida a todo el ancho; el resto en dos columnas, o todo en
        una sola si el panel es angosto."""
        if two_columns == self._two_columns:
            return
        self._two_columns = two_columns
        grid = self._grid
        for key in self._field_order:
            grid.removeWidget(self._field_keys[key])
            grid.removeWidget(self._fields[key])
        wide = {"nombre", "tramo", "salida"}
        row = col = 0
        for key in self._field_order:
            lbl_key, lbl_val = self._field_keys[key], self._fields[key]
            if key in wide or not two_columns:
                if col:
                    row, col = row + 1, 0
                grid.addWidget(lbl_key, row, 0)
                grid.addWidget(lbl_val, row, 1, 1, 3)
                row += 1
            else:
                grid.addWidget(lbl_key, row, col * 2)
                grid.addWidget(lbl_val, row, col * 2 + 1)
                col = 1 - col
                if col == 0:
                    row += 1
        if hasattr(self, "info_scroll"):
            self.info_scroll.setMaximumHeight(self.info_scroll.widget().sizeHint().height() + 4)

    # Por debajo de este alto, el texto de ayuda de la forma de onda se oculta (la misma
    # explicación queda en su tooltip) para que los detalles no se aprieten.
    _HINT_MIN_HEIGHT = 440

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.lbl_wave_hint.setVisible(self.height() >= self._HINT_MIN_HEIGHT)
        self._place_fields(two_columns=self.width() >= self._TWO_COLUMNS_MIN_WIDTH)

    def hideEvent(self, event):
        # Al cambiar de pestaña el video no sigue sonando de fondo.
        self.pause()
        super().hideEvent(event)
