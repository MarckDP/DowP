# src/gui/tabs/video_tools/compress_panel.py
import os
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QLabel,
    QComboBox,
    QRadioButton,
    QButtonGroup,
    QStackedWidget,
    QSpinBox,
    QDoubleSpinBox,
    QPushButton,
    QSizePolicy,
    QScrollArea,
)
from PySide6.QtCore import Signal, Qt

from gui.styles import get_theme_token
from gui.widgets.mode_selector import ModeSelector
from gui.widgets.combo_box import CheckmarkComboDelegate, AutoPopupComboBox
from gui.widgets.engine_badge import EngineBadge
from core.utils.recode_guard import (
    resolve_encoder, get_video_codecs, get_audio_codecs, get_compatible_containers,
    normalize_container, software_encoder, has_hardware_encoder, CONTAINER_LABELS,
    container_supports_video,
)
from core.tabs.video_tools.codec_profiles import build_custom_quality_args, build_custom_bitrate_args, build_custom_audio_bitrate_args
from core.tabs.video_tools.size_estimator import parse_duration_to_seconds, estimate_size_mb
import core.tabs.video_tools.compress_advisor as advisor

_MAX_VISIBLE_COMBO_ITEMS = 12

# Familias de codec ofrecidas en Comprimir: solo las orientadas a distribución/compresión
# real (h264/hevc/av1/vp9) — ProRes/DNxHR/GIF/lossless etc. quedan exclusivos de Avanzado,
# donde tienen sentido (mezcla/edición), no aquí.
_VIDEO_CODEC_IDS = ["h264", "hevc", "av1", "vp9"]
_AUDIO_CODEC_IDS = ["aac", "opus", "mp3"]

_QUALITY_MODE_CQ = "cq"
_QUALITY_MODE_BITRATE = "bitrate"
_QUALITY_MODE_TARGET_SIZE = "target_size"


class CompressPanel(QWidget):
    """
    Pestaña "Comprimir": selector Rápido/Manual.

    Rápido: 3 niveles (Ligero/Equilibrado/Agresivo) expresados como fracción del bitrate
    de origen (ver core/tabs/video_tools/compress_advisor.py) — calcula automáticamente
    parámetros tanto para video como para archivos de solo audio (WAV, MP3, FLAC, etc.).

    Manual: selector explícito de modo (Video + Audio / Solo Video / Solo Audio) + codec +
    modo de calidad (CRF / bitrate manual / tamaño objetivo en MB) + codec de audio +
    contenedor compatible.
    """

    validity_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._building = False
        self._last_valid = True
        self._source_meta = None
        self._source_filepath = None
        self._queue_entries = []
        self._force_cpu_quick = False
        self._force_cpu_manual = False
        self._container_touched = False
        self._init_ui()
        self._reload_manual_video_codecs()
        self._refresh_quick_estimates()

    # ─── UI ──────────────────────────────────────────────────────

    def _init_ui(self):
        self.setObjectName("compressPanel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setObjectName("compressScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        self.setStyleSheet("""
            QWidget#compressPanel { background: transparent; }
            QScrollArea#compressScroll { background: transparent; }
            QWidget#compressContent { background: transparent; }
        """)

        content = QWidget(scroll)
        content.setObjectName("compressContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        self.mode_selector = ModeSelector(content, labels=[self.tr("Rápido"), self.tr("Manual")])
        self.mode_selector.mode_changed.connect(self._on_top_mode_changed)
        layout.addWidget(self.mode_selector)

        self.stack = QStackedWidget(content)
        self.page_quick = self._build_quick_page(self.stack)
        self.page_manual = self._build_manual_page(self.stack)
        self.stack.addWidget(self.page_quick)
        self.stack.addWidget(self.page_manual)
        layout.addWidget(self.stack)

        layout.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll)

    def _card_frame(self, title: str | None = None, parent=None) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame(parent or self)
        frame.setObjectName("advancedCard")
        border_color = get_theme_token('borde_sutil', '#2d2d2d')
        frame.setStyleSheet(f"""
            QFrame#advancedCard {{
                background-color: transparent;
                border: 1px solid {border_color};
                border-radius: 6px;
            }}
        """)
        frame.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        v = QVBoxLayout(frame)
        v.setContentsMargins(12, 10, 12, 12)
        v.setSpacing(8)
        if title:
            lbl = QLabel(title, frame)
            lbl.setObjectName("sectionTitle")
            lbl.setAlignment(Qt.AlignCenter)
            v.addWidget(lbl)
        return frame, v

    def _setup_fixed_combo(self, combo: QComboBox):
        combo.setMaxVisibleItems(_MAX_VISIBLE_COMBO_ITEMS)
        combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(1)
        combo.setItemDelegate(CheckmarkComboDelegate(combo))
        combo.setCursor(Qt.PointingHandCursor)

    # ─── Página Rápido ───────────────────────────────────────────

    def _build_quick_page(self, parent) -> QWidget:
        page = QWidget(parent)
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        compat_row = QHBoxLayout()
        compat_row.setSpacing(8)
        self.compat_toggle = ModeSelector(page, labels=[self.tr("Compatibilidad universal"), self.tr("Mejor compresión")])
        self.compat_toggle.mode_changed.connect(self._on_quick_compat_changed)
        compat_row.addWidget(self.compat_toggle, 1)
        self.badge_quick_engine = EngineBadge(page)
        self.badge_quick_engine.toggled_force_cpu.connect(self._on_quick_force_cpu_toggled)
        compat_row.addWidget(self.badge_quick_engine)
        v.addLayout(compat_row)

        self.lbl_compat_hint = QLabel(self.tr(
            "Compatibilidad universal usa H.264 (se reproduce en cualquier dispositivo). "
            "Mejor compresión usa HEVC si este equipo tiene un encoder disponible: mismo nivel de "
            "calidad en menos peso, con algo menos de compatibilidad. Ambas usan aceleración por "
            "GPU cuando este equipo la tiene — el badge de la derecha lo confirma y permite forzar CPU."
        ), page)
        self.lbl_compat_hint.setObjectName("mutedLabel")
        self.lbl_compat_hint.setWordWrap(True)
        v.addWidget(self.lbl_compat_hint)

        suggestion_frame, suggestion_layout = self._card_frame(parent=page)
        self.lbl_suggestion = QLabel("", suggestion_frame)
        self.lbl_suggestion.setWordWrap(True)
        suggestion_layout.addWidget(self.lbl_suggestion)
        v.addWidget(suggestion_frame)

        levels_row = QHBoxLayout()
        levels_row.setSpacing(8)
        self.level_group = QButtonGroup(page)
        self.level_group.setExclusive(True)
        self._level_buttons = {}
        accent = get_theme_token('acento_primario', '#B9E640')
        border_color = get_theme_token('borde_sutil', '#2d2d2d')
        fondo = get_theme_token('fondo_secundario', '#121212')
        texto = get_theme_token('texto_principal', '#ffffff')
        for level in advisor.LEVELS:
            btn = QPushButton(advisor.get_level_label(level), page)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(64)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {fondo};
                    color: {texto};
                    border: 1px solid {border_color};
                    border-radius: 6px;
                    padding: 6px;
                    font-weight: bold;
                }}
                QPushButton:checked {{
                    border: 2px solid {accent};
                    color: {accent};
                }}
            """)
            btn.clicked.connect(self._on_quick_changed)
            self.level_group.addButton(btn)
            self._level_buttons[level] = btn
            levels_row.addWidget(btn)
        self._level_buttons["equilibrado"].setChecked(True)
        v.addLayout(levels_row)

        self.lbl_queue_total = QLabel("", page)
        self.lbl_queue_total.setObjectName("mutedLabel")
        self.lbl_queue_total.setWordWrap(True)
        v.addWidget(self.lbl_queue_total)

        v.addStretch(1)
        return page

    def _current_quick_level(self) -> str:
        for level, btn in self._level_buttons.items():
            if btn.isChecked():
                return level
        return "equilibrado"

    def _current_quick_family(self) -> str:
        prefer_compat = self.compat_toggle.current_mode() == self.tr("Compatibilidad universal")
        return advisor.pick_family(prefer_compat)

    def _current_quick_encoder(self) -> str:
        family = self._current_quick_family()
        if self._force_cpu_quick:
            return software_encoder(family) or resolve_encoder(family) or "libx264"
        return resolve_encoder(family) or "libx264"

    def _refresh_quick_engine_badge(self):
        family = self._current_quick_family()
        self.badge_quick_engine.set_state(has_hardware_encoder(family), self._force_cpu_quick)

    def _on_quick_compat_changed(self, *_args):
        self._refresh_quick_estimates()

    def _on_quick_force_cpu_toggled(self, force_cpu: bool):
        self._force_cpu_quick = force_cpu
        self._refresh_quick_estimates()

    def _on_quick_changed(self, *_args):
        self._refresh_quick_estimates()

    def _refresh_quick_estimates(self):
        if not hasattr(self, "_level_buttons"):
            return
        
        meta = self._source_meta or {}
        is_audio = advisor.is_audio_only(meta, self._source_filepath) if self._source_meta else False

        self.badge_quick_engine.setVisible(True)
        self._refresh_quick_engine_badge()

        if hasattr(self, "lbl_compat_hint"):
            if is_audio:
                self.lbl_compat_hint.setText(self.tr(
                    "Compatibilidad universal usa AAC/MP3 y Mejor compresión usa Opus. "
                    "Para archivos de video se usará aceleración por GPU (configurable arriba a la derecha); los audios se procesan por CPU."
                ))
            else:
                self.lbl_compat_hint.setText(self.tr(
                    "Compatibilidad universal usa H.264 (se reproduce en cualquier dispositivo). "
                    "Mejor compresión usa HEVC si este equipo tiene un encoder disponible: mismo nivel de "
                    "calidad en menos peso, con algo menos de compatibilidad. Ambas usan aceleración por "
                    "GPU cuando este equipo la tiene — el badge de la derecha lo confirma y permite forzar CPU."
                ))

        source_mb = advisor.source_size_mb(meta) if self._source_meta else None

        for level, btn in self._level_buttons.items():
            est_mb = advisor.estimate_level_size_mb(meta, level) if self._source_meta else None
            label = advisor.get_level_label(level)
            if est_mb is None:
                btn.setText(label)
            elif source_mb:
                pct = max(0.0, (1 - est_mb / source_mb) * 100) if source_mb > 0 else 0.0
                btn.setText(f"{label}\n~{est_mb:.1f} MB (-{pct:.0f}%)")
            else:
                btn.setText(f"{label}\n~{est_mb:.1f} MB")

        if not self._source_meta:
            self.lbl_suggestion.setText(self.tr("Selecciona un archivo en la cola para ver una sugerencia."))
        else:
            info = advisor.analyze_source(self._source_meta)
            recommended = advisor.get_level_label(info["recommended_level"])
            note = info.get("note", "")
            self.lbl_suggestion.setText(self.tr("Sugerencia: {0}. {1}").format(recommended, note))

        self._refresh_queue_total_label()

    def _refresh_queue_total_label(self):
        if not hasattr(self, "lbl_queue_total"):
            return
        if not self._queue_entries:
            self.lbl_queue_total.setText("")
            return
        totals = advisor.estimate_queue_totals(self._queue_entries, self._current_quick_level())
        if totals["file_count"] == 0:
            self.lbl_queue_total.setText("")
            return
        current = totals["current_total_mb"]
        projected = totals["projected_total_mb"]
        if current > 0:
            pct = max(0.0, (1 - projected / current) * 100)
            self.lbl_queue_total.setText(
                self.tr("Peso total estimado de la cola ({0} archivos): ~{1:.0f} MB (-{2:.0f}% vs. ~{3:.0f} MB actuales)")
                .format(totals["file_count"], projected, pct, current)
            )
        else:
            self.lbl_queue_total.setText(
                self.tr("Peso total estimado de la cola ({0} archivos): ~{1:.0f} MB").format(totals["file_count"], projected)
            )

    # ─── Página Manual ───────────────────────────────────────────

    def _build_manual_page(self, parent) -> QWidget:
        page = QWidget(parent)
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        # Selector de Modo de Pista (Video+Audio / Solo Video / Solo Audio)
        self.manual_stream_mode = ModeSelector(
            page,
            labels=[self.tr("Video + Audio"), self.tr("Solo Video"), self.tr("Solo Audio")]
        )
        self.manual_stream_mode.mode_changed.connect(self._on_manual_stream_mode_changed)
        v.addWidget(self.manual_stream_mode)

        # Video
        frame_video, vv = self._card_frame(self.tr("Video"), page)
        self.frame_manual_video = frame_video
        codec_header_row = QHBoxLayout()
        lbl_codec = QLabel(self.tr("Códec:"), frame_video)
        lbl_codec.setObjectName("menuLabel")
        codec_header_row.addWidget(lbl_codec, 1)
        self.badge_manual_engine = EngineBadge(frame_video)
        self.badge_manual_engine.toggled_force_cpu.connect(self._on_manual_force_cpu_toggled)
        codec_header_row.addWidget(self.badge_manual_engine)
        vv.addLayout(codec_header_row)

        self.combo_manual_video_codec = AutoPopupComboBox(frame_video)
        self._setup_fixed_combo(self.combo_manual_video_codec)
        self.combo_manual_video_codec.currentIndexChanged.connect(self._on_manual_video_codec_changed)
        vv.addWidget(self.combo_manual_video_codec)

        lbl_quality_mode = QLabel(self.tr("Modo de calidad:"), frame_video)
        lbl_quality_mode.setObjectName("menuLabel")
        vv.addWidget(lbl_quality_mode)

        self.quality_mode_group = QButtonGroup(frame_video)
        self.rb_quality_cq = QRadioButton(self.tr("Calidad constante (CRF)"), frame_video)
        self.rb_quality_bitrate = QRadioButton(self.tr("Bitrate de video (kbps)"), frame_video)
        self.rb_quality_target = QRadioButton(self.tr("Tamaño objetivo (MB)"), frame_video)
        self.rb_quality_cq.setChecked(True)
        for rb in (self.rb_quality_cq, self.rb_quality_bitrate, self.rb_quality_target):
            rb.setCursor(Qt.PointingHandCursor)
            self.quality_mode_group.addButton(rb)
            rb.toggled.connect(self._on_quality_mode_toggled)
            vv.addWidget(rb)

        self.spin_manual_cq = QSpinBox(frame_video)
        self.spin_manual_cq.setRange(0, 51)
        self.spin_manual_cq.setValue(23)
        self.spin_manual_cq.setSuffix(self.tr(" (CRF/CQ — más bajo = más calidad y más peso)"))
        self.spin_manual_cq.valueChanged.connect(self._on_manual_changed)
        vv.addWidget(self.spin_manual_cq)

        self.spin_manual_bitrate = QSpinBox(frame_video)
        self.spin_manual_bitrate.setRange(100, 500000)
        self.spin_manual_bitrate.setSingleStep(500)
        self.spin_manual_bitrate.setValue(4000)
        self.spin_manual_bitrate.setSuffix(" kbps")
        self.spin_manual_bitrate.valueChanged.connect(self._on_manual_changed)
        self.spin_manual_bitrate.setVisible(False)
        vv.addWidget(self.spin_manual_bitrate)

        self.spin_manual_target_mb = QDoubleSpinBox(frame_video)
        self.spin_manual_target_mb.setRange(1.0, 100000.0)
        self.spin_manual_target_mb.setDecimals(1)
        self.spin_manual_target_mb.setValue(25.0)
        self.spin_manual_target_mb.setSuffix(" MB")
        self.spin_manual_target_mb.valueChanged.connect(self._on_manual_changed)
        self.spin_manual_target_mb.setVisible(False)
        vv.addWidget(self.spin_manual_target_mb)

        lbl_target_hint = QLabel(self.tr(
            "El bitrate se calcula según la duración real de CADA archivo al iniciar — el tamaño final "
            "de cada uno se acerca al objetivo, sin importar cuánto dure."
        ), frame_video)
        lbl_target_hint.setObjectName("mutedLabel")
        lbl_target_hint.setWordWrap(True)
        lbl_target_hint.setVisible(False)
        vv.addWidget(lbl_target_hint)
        self._lbl_target_hint = lbl_target_hint

        v.addWidget(frame_video)

        # Audio
        frame_audio, av = self._card_frame(self.tr("Audio"), page)
        self.frame_manual_audio = frame_audio
        lbl_acodec = QLabel(self.tr("Códec:"), frame_audio)
        lbl_acodec.setObjectName("menuLabel")
        av.addWidget(lbl_acodec)
        self.combo_manual_audio_codec = AutoPopupComboBox(frame_audio)
        self._setup_fixed_combo(self.combo_manual_audio_codec)
        for codec in get_audio_codecs(only_verified=False):
            if codec["codec_id"] in _AUDIO_CODEC_IDS:
                self.combo_manual_audio_codec.addItem(codec["display_name"], codec["codec_id"])
        default_idx = self.combo_manual_audio_codec.findData("aac")
        if default_idx >= 0:
            self.combo_manual_audio_codec.setCurrentIndex(default_idx)
        self.combo_manual_audio_codec.currentIndexChanged.connect(self._on_manual_changed)
        av.addWidget(self.combo_manual_audio_codec)

        lbl_audio_bitrate = QLabel(self.tr("Bitrate de audio:"), frame_audio)
        lbl_audio_bitrate.setObjectName("menuLabel")
        av.addWidget(lbl_audio_bitrate)

        self.spin_manual_audio_bitrate = QSpinBox(frame_audio)
        self.spin_manual_audio_bitrate.setRange(32, 320)
        self.spin_manual_audio_bitrate.setSingleStep(32)
        self.spin_manual_audio_bitrate.setValue(128)
        self.spin_manual_audio_bitrate.setSuffix(" kbps")
        self.spin_manual_audio_bitrate.valueChanged.connect(self._on_manual_changed)
        av.addWidget(self.spin_manual_audio_bitrate)
        v.addWidget(frame_audio)

        # Contenedor
        frame_container, cv = self._card_frame(self.tr("Contenedor de salida"), page)
        self.combo_manual_container = AutoPopupComboBox(frame_container)
        self._setup_fixed_combo(self.combo_manual_container)
        self.combo_manual_container.currentIndexChanged.connect(self._on_manual_changed)
        self.combo_manual_container.activated.connect(self._on_container_touched)
        cv.addWidget(self.combo_manual_container)
        lbl_container_hint = QLabel(self.tr("Solo se muestran los contenedores compatibles con los códecs elegidos."), frame_container)
        lbl_container_hint.setObjectName("mutedLabel")
        lbl_container_hint.setWordWrap(True)
        cv.addWidget(lbl_container_hint)
        v.addWidget(frame_container)

        # Peso estimado
        frame_size, sv = self._card_frame(self.tr("Peso final estimado"), page)
        self.lbl_manual_size_estimate = QLabel("", frame_size)
        self.lbl_manual_size_estimate.setWordWrap(True)
        sv.addWidget(self.lbl_manual_size_estimate)
        v.addWidget(frame_size)

        v.addStretch(1)
        return page

    def _current_manual_stream_mode(self) -> str:
        if not hasattr(self, "manual_stream_mode"):
            return "video+audio"
        mode = self.manual_stream_mode.current_mode()
        if mode == self.tr("Solo Audio"):
            return "audio_only"
        if mode == self.tr("Solo Video"):
            return "video_only"
        return "video+audio"

    def _on_manual_stream_mode_changed(self, mode_text: str):
        stream_mode = self._current_manual_stream_mode()
        self.frame_manual_video.setVisible(stream_mode in ("video+audio", "video_only"))
        self.frame_manual_audio.setVisible(stream_mode in ("video+audio", "audio_only"))
        self._on_manual_changed()

    def _reload_manual_video_codecs(self):
        self._building = True
        try:
            self.combo_manual_video_codec.clear()
            for codec in get_video_codecs(only_verified=False):
                if codec["codec_id"] in _VIDEO_CODEC_IDS:
                    self.combo_manual_video_codec.addItem(codec["display_name"], codec["codec_id"])
            idx = self.combo_manual_video_codec.findData("h264")
            if idx >= 0:
                self.combo_manual_video_codec.setCurrentIndex(idx)
        finally:
            self._building = False
        self._on_manual_video_codec_changed()

    def _current_manual_video_codec_id(self) -> str:
        return self.combo_manual_video_codec.currentData() or "h264"

    def _current_manual_video_encoder(self) -> str:
        codec_id = self._current_manual_video_codec_id()
        if self._force_cpu_manual:
            return software_encoder(codec_id) or resolve_encoder(codec_id) or "libx264"
        return resolve_encoder(codec_id) or "libx264"

    def _current_manual_audio_codec_id(self) -> str:
        return self.combo_manual_audio_codec.currentData() or "aac"

    def _current_manual_audio_encoder(self) -> str:
        return resolve_encoder(self._current_manual_audio_codec_id()) or "aac"

    def _on_manual_video_codec_changed(self, *_args):
        if self._building:
            return
        codec_id = self._current_manual_video_codec_id()
        self.badge_manual_engine.set_state(has_hardware_encoder(codec_id), self._force_cpu_manual)
        self._on_manual_changed()

    def _on_manual_force_cpu_toggled(self, force_cpu: bool):
        self._force_cpu_manual = force_cpu
        codec_id = self._current_manual_video_codec_id()
        self.badge_manual_engine.set_state(has_hardware_encoder(codec_id), self._force_cpu_manual)
        self._on_manual_changed()

    def _on_quality_mode_toggled(self, *_args):
        is_cq = self.rb_quality_cq.isChecked()
        is_bitrate = self.rb_quality_bitrate.isChecked()
        is_target = self.rb_quality_target.isChecked()
        self.spin_manual_cq.setVisible(is_cq)
        self.spin_manual_bitrate.setVisible(is_bitrate)
        self.spin_manual_target_mb.setVisible(is_target)
        self._lbl_target_hint.setVisible(is_target)
        self._on_manual_changed()

    def _current_quality_mode(self) -> str:
        if self.rb_quality_bitrate.isChecked():
            return _QUALITY_MODE_BITRATE
        if self.rb_quality_target.isChecked():
            return _QUALITY_MODE_TARGET_SIZE
        return _QUALITY_MODE_CQ

    def _source_container_id(self) -> str | None:
        if not self._source_filepath:
            return None
        ext = os.path.splitext(self._source_filepath)[1]
        return normalize_container(ext) if ext else None

    def _on_container_touched(self, *_args):
        self._container_touched = True

    def _reload_manual_containers(self):
        self._building = True
        try:
            current = self.combo_manual_container.currentData() if self._container_touched else None
            self.combo_manual_container.clear()

            stream_mode = self._current_manual_stream_mode()
            if stream_mode == "audio_only":
                codec_ids = [self._current_manual_audio_codec_id()]
                all_comp = get_compatible_containers(codec_ids)
                audio_order = ["m4a", "mp3", "opus", "ogg", "flac", "wav", "mkv", "mp4"]
                compatible = [c for c in audio_order if c in all_comp] or all_comp
            elif stream_mode == "video_only":
                codec_ids = [self._current_manual_video_codec_id()]
                compatible = get_compatible_containers(codec_ids)
            else:
                codec_ids = [self._current_manual_video_codec_id(), self._current_manual_audio_codec_id()]
                compatible = get_compatible_containers(codec_ids)

            source_id = self._source_container_id()
            if source_id and source_id in compatible:
                self.combo_manual_container.addItem(self.tr("Mismo que el original"), "same")

            if not compatible and self.combo_manual_container.count() == 0:
                compatible = ["m4a"] if stream_mode == "audio_only" else ["mp4"]
            for container_id in compatible:
                label = CONTAINER_LABELS.get(container_id, container_id.upper())
                self.combo_manual_container.addItem(label, container_id)

            if current is not None:
                idx = self.combo_manual_container.findData(current)
            else:
                idx = -1
            if idx < 0:
                idx = self.combo_manual_container.findData("same")
                if idx < 0:
                    if stream_mode == "audio_only":
                        acodec = self._current_manual_audio_codec_id()
                        pref = "mp3" if acodec == "mp3" else ("opus" if acodec == "opus" else "m4a")
                        idx = self.combo_manual_container.findData(pref)
                    else:
                        idx = self.combo_manual_container.findData("mp4")
                if idx < 0:
                    idx = 0
            self.combo_manual_container.setCurrentIndex(max(idx, 0))
        finally:
            self._building = False

    def _manual_video_kbps_for_duration(self, duration_sec: float | None) -> float | None:
        mode = self._current_quality_mode()
        if mode == _QUALITY_MODE_BITRATE:
            return float(self.spin_manual_bitrate.value())
        if mode == _QUALITY_MODE_TARGET_SIZE:
            if not duration_sec or duration_sec <= 0:
                return None
            target_mb = self.spin_manual_target_mb.value()
            audio_kbps = float(self.spin_manual_audio_bitrate.value()) if self._current_manual_stream_mode() != "video_only" else 0.0
            total_kbps = (target_mb * 8 * 1024) / duration_sec
            video_kbps = total_kbps - audio_kbps
            return max(100.0, video_kbps)
        return None  # CRF: sin bitrate fijo, no estimable de antemano.

    def _build_manual_video_args(self, duration_sec: float | None) -> list[str]:
        encoder = self._current_manual_video_encoder()
        mode = self._current_quality_mode()
        if mode == _QUALITY_MODE_CQ:
            return build_custom_quality_args(encoder, self.spin_manual_cq.value())
        kbps = self._manual_video_kbps_for_duration(duration_sec)
        if kbps is None:
            kbps = 4000.0
        return build_custom_bitrate_args(encoder, "vbr", round(kbps))

    def _on_manual_changed(self, *_args):
        if self._building:
            return
        self._reload_manual_containers()
        self._refresh_manual_size_estimate()

    def _refresh_manual_size_estimate(self):
        if not hasattr(self, "lbl_manual_size_estimate"):
            return
        if not self._source_meta:
            self.lbl_manual_size_estimate.setText(self.tr("Selecciona un archivo en la cola para estimar el peso."))
            return
        duration_sec = parse_duration_to_seconds(self._source_meta.get("duración", "0"))
        if duration_sec <= 0:
            self.lbl_manual_size_estimate.setText(self.tr("Duración del archivo todavía no disponible."))
            return

        stream_mode = self._current_manual_stream_mode()
        mode = self._current_quality_mode()

        if stream_mode == "audio_only":
            audio_kbps = float(self.spin_manual_audio_bitrate.value())
            size_mb = estimate_size_mb(0, audio_kbps, duration_sec)
            if size_mb is None:
                self.lbl_manual_size_estimate.setText("")
                return
            self.lbl_manual_size_estimate.setText(
                self.tr("~{0:.1f} MB (audio: {1:.0f} kbps)").format(size_mb, audio_kbps)
            )
            return

        if mode == _QUALITY_MODE_CQ:
            self.lbl_manual_size_estimate.setText(self.tr(
                "No se puede estimar con calidad constante (CRF): el tamaño final depende del "
                "contenido del video, no es predecible de antemano."
            ))
            return

        video_kbps = self._manual_video_kbps_for_duration(duration_sec)
        if stream_mode == "video_only":
            size_mb = estimate_size_mb(video_kbps, 0, duration_sec)
            if size_mb is None:
                self.lbl_manual_size_estimate.setText("")
                return
            self.lbl_manual_size_estimate.setText(
                self.tr("~{0:.1f} MB (video: {1:.0f} kbps)").format(size_mb, video_kbps)
            )
            return

        audio_kbps = float(self.spin_manual_audio_bitrate.value())
        size_mb = estimate_size_mb(video_kbps, audio_kbps, duration_sec)
        if size_mb is None:
            self.lbl_manual_size_estimate.setText("")
            return
        self.lbl_manual_size_estimate.setText(
            self.tr("~{0:.1f} MB (video: {1:.0f} kbps, audio: {2:.0f} kbps)").format(size_mb, video_kbps, audio_kbps)
        )

    # ─── Modo superior (Rápido/Manual) ──────────────────────────

    def _on_top_mode_changed(self, mode_text: str):
        self.stack.setCurrentIndex(0 if mode_text == self.tr("Rápido") else 1)

    # ─── API pública ─────────────────────────────────────────────

    def is_valid(self) -> bool:
        return self._last_valid

    def get_status(self) -> tuple[bool, str]:
        return True, self.tr("Iniciar Recodificación")

    def set_source_media(self, meta: dict, filepath: str):
        self._source_meta = meta or None
        self._source_filepath = filepath
        self._refresh_quick_estimates()
        self._reload_manual_containers()
        self._refresh_manual_size_estimate()

    def set_queue_entries(self, entries: list[dict]):
        self._queue_entries = entries or []
        self._refresh_queue_total_label()

    def get_settings(self, meta_override: dict | None = None, filepath_override: str | None = None) -> dict:
        """`meta_override`/`filepath_override`, si se pasan, describen un archivo DISTINTO
        al que está en preview - los usa el lote al recorrer cada archivo de la cola (ver
        video_tools_view.py): Rápido calcula el nivel como fracción del bitrate de CADA
        archivo (no del que está en preview), y Manual + "Tamaño objetivo (MB)" / "Mismo
        que el original" necesitan la duración/extensión real de cada uno."""
        is_quick = self.mode_selector.current_mode() == self.tr("Rápido")

        if is_quick:
            meta = meta_override if meta_override is not None else (self._source_meta or {})
            filepath = filepath_override if filepath_override is not None else self._source_filepath
            level = self._current_quick_level()
            prefer_compat = self.compat_toggle.current_mode() == self.tr("Compatibilidad universal")

            if advisor.is_audio_only(meta, filepath):
                audio_codec = advisor.pick_audio_family(prefer_compat)
                encoder = resolve_encoder(audio_codec) or audio_codec
                if filepath:
                    ext = os.path.splitext(filepath)[1].lower()
                    if ext == ".mp3" and prefer_compat:
                        audio_codec = "mp3"
                        encoder = resolve_encoder("mp3") or "libmp3lame"
                audio_args = advisor.build_level_audio_args(meta, level, encoder)
                container = "mp3" if audio_codec == "mp3" else ("opus" if audio_codec == "opus" else "m4a")
                return {
                    "stream_mode": "audio_only",
                    "video_mode": "none",
                    "video_codec": None,
                    "video_args": [],
                    "audio_mode": "recode",
                    "audio_codec": audio_codec,
                    "audio_args": audio_args,
                    "container": container,
                }

            family = self._current_quick_family()
            encoder = self._current_quick_encoder()
            video_args = advisor.build_level_video_args(meta, level, encoder)
            audio_kbps = advisor.AUDIO_BITRATE_BY_LEVEL[level]
            return {
                "stream_mode": "video+audio",
                "video_mode": "recode",
                "video_codec": family,
                "video_args": video_args,
                "audio_mode": "recode",
                "audio_codec": "aac",
                "audio_args": build_custom_audio_bitrate_args("aac", audio_kbps),
                "container": "mp4",
            }

        effective_meta = meta_override if meta_override is not None else self._source_meta
        effective_filepath = filepath_override if filepath_override is not None else self._source_filepath
        duration_sec = parse_duration_to_seconds(effective_meta.get("duración", "0")) if effective_meta else None
        stream_mode = self._current_manual_stream_mode()

        audio_codec_id = self._current_manual_audio_codec_id()
        audio_encoder = self._current_manual_audio_encoder()
        audio_kbps = self.spin_manual_audio_bitrate.value()
        audio_args = build_custom_audio_bitrate_args(audio_encoder, audio_kbps)

        container = self.combo_manual_container.currentData() or "mp4"
        if container == "same":
            if effective_filepath:
                ext = os.path.splitext(effective_filepath)[1]
                resolved = normalize_container(ext) if ext else None
            else:
                resolved = self._source_container_id()
            container = resolved or ("m4a" if stream_mode == "audio_only" else "mp4")

        if stream_mode == "audio_only":
            return {
                "stream_mode": "audio_only",
                "video_mode": "none",
                "video_codec": None,
                "video_args": [],
                "audio_mode": "recode",
                "audio_codec": audio_codec_id,
                "audio_args": audio_args,
                "container": container,
            }

        if stream_mode == "video_only":
            video_codec_id = self._current_manual_video_codec_id()
            video_args = self._build_manual_video_args(duration_sec)
            return {
                "stream_mode": "video_only",
                "video_mode": "recode",
                "video_codec": video_codec_id,
                "video_args": video_args,
                "audio_mode": "none",
                "audio_codec": None,
                "audio_args": [],
                "container": container,
            }

        # stream_mode == "video+audio"
        if effective_meta and advisor.is_audio_only(effective_meta, effective_filepath):
            # Fallback seguro para audios puros si se dejaron en lote con modo Video+Audio
            return {
                "stream_mode": "audio_only",
                "video_mode": "none",
                "video_codec": None,
                "video_args": [],
                "audio_mode": "recode",
                "audio_codec": audio_codec_id,
                "audio_args": audio_args,
                "container": "m4a" if container in ("mp4", "mkv") else container,
            }

        video_codec_id = self._current_manual_video_codec_id()
        video_args = self._build_manual_video_args(duration_sec)
        return {
            "stream_mode": "video+audio",
            "video_mode": "recode",
            "video_codec": video_codec_id,
            "video_args": video_args,
            "audio_mode": "recode",
            "audio_codec": audio_codec_id,
            "audio_args": audio_args,
            "container": container,
        }
