# src/gui/tabs/video_tools/advanced_recode_panel.py
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QLabel,
    QComboBox,
    QRadioButton,
    QButtonGroup,
    QScrollArea,
    QSpinBox,
    QDoubleSpinBox,
    QCheckBox,
    QSizePolicy,
    QPushButton,
    QStyledItemDelegate,
    QLineEdit,
    QFileDialog,
    QSlider,
)
from PySide6.QtCore import Signal, Qt, QT_TRANSLATE_NOOP
from PySide6.QtGui import QColor, QPixmap
import math

from gui.styles import get_theme_token
from gui.widgets.mode_selector import ModeSelector
from gui.widgets.preset_bar import PresetBar
from gui.widgets.collapsible_section import CollapsibleSection
from gui.widgets.combo_box import CheckmarkComboDelegate, AutoPopupComboBox
from core.logger.logger_manager import logger
from core.utils.recode_guard import evaluate_recode, get_video_codecs, get_audio_codecs, get_compatible_containers, resolve_encoder, get_channel_support, get_dimension_alignment, CONTAINER_LABELS
from core.utils.hardware_detector import detect_hardware
from core.utils.font_manager import get_available_fonts, get_active_font_family, get_static_font_path, STANDARD_WEIGHTS
from core.utils.watermark_builder import build_drawtext_filter, build_image_overlay_filter, check_watermark_file
from core.utils.audio_filter_builder import build_audio_normalization_filter
from core.tabs.video_tools.codec_profiles import (
    get_profiles, build_custom_bitrate_args, extract_bitrate_kbps,
    recommend_audio_codec, supports_two_pass, encoder_is_two_pass_capable, build_pass_args, ENCODER_VARIANTS,
    ordered_encoder_variants,
)
from core.tabs.video_tools.size_estimator import (
    parse_duration_to_seconds, parse_kbps_from_label, estimate_size_mb, source_codec_id,
)

# Con listas de ~25-30 codecs, el popup del combo se cae a scroll para no tapar la pantalla
_MAX_VISIBLE_COMBO_ITEMS = 12

_PRESET_NAMESPACE = "video_tools/avanzado"

# Contenedores de stream elemental que NUNCA pueden llevar más de una pista de audio,
# sin importar el códec (a diferencia del resto, que son contenedores de multiplexado
# reales y sí pueden). Lista acotada a mano por ahora, igual que hacía DowP Lite -
# pendiente de reemplazar por un dato verificado empíricamente contra el ffmpeg
# empaquetado cuando se amplíe tools/codec_matrix con soporte multi-pista (ver charla).
_SINGLE_AUDIO_STREAM_CONTAINERS = {"mp3", "wav", "flac"}

from PySide6.QtCore import QT_TR_NOOP, QT_TRANSLATE_NOOP

_SEVERITY_LABELS = {
    "ok": QT_TRANSLATE_NOOP("AdvancedRecodePanel", "Compatible"),
    "warning": QT_TRANSLATE_NOOP("AdvancedRecodePanel", "Advertencia"),
    "unverified": QT_TRANSLATE_NOOP("AdvancedRecodePanel", "No verificado"),
    "blocked": QT_TRANSLATE_NOOP("AdvancedRecodePanel", "No compatible"),
}
_SEVERITY_TOKENS = {
    "ok": "estado_exito",
    "warning": "estado_aviso",
    "unverified": "estado_espera",
    "blocked": "estado_error",
}

_ENGINE_LABELS = {
    "h264_nvenc": "NVIDIA NVENC", "hevc_nvenc": "NVIDIA NVENC", "av1_nvenc": "NVIDIA NVENC",
    "h264_videotoolbox": "Apple VideoToolbox", "hevc_videotoolbox": "Apple VideoToolbox",
    "h264_qsv": "Intel QuickSync", "hevc_qsv": "Intel QuickSync", "av1_qsv": "Intel QuickSync",
    "h264_amf": "AMD AMF", "hevc_amf": "AMD AMF", "av1_amf": "AMD AMF",
    "h264_vaapi": "VA-API", "hevc_vaapi": "VA-API", "av1_vaapi": "VA-API", "vp9_vaapi": "VA-API",
}

# Presets de resolución: escalan el LADO LARGO del video preservando el aspecto real del fuente
# (modelo "conservar aspecto" — nunca recortan ni deforman por sí solos). El valor es el tamaño
# objetivo en píxeles del lado más largo; la expresión ffmpeg que lo usa decide en tiempo de
# ejecución (con iw/ih) si ese lado es el ancho o el alto, sin que DowP necesite saber la
# orientación del fuente de antemano.
_RESOLUTION_PRESETS = [
    ("original", QT_TRANSLATE_NOOP("AdvancedRecodePanel", "Original"), None),
    ("4k", "4K (2160p)", 3840),
    ("2k", "2K (1440p)", 2560),
    ("1080p", "1080p (Full HD)", 1920),
    ("720p", "720p (HD)", 1280),
    ("480p", "480p (SD)", 854),
    ("custom", QT_TRANSLATE_NOOP("AdvancedRecodePanel", "Personalizado"), None),
]

# Framerates estándar de broadcast/cine para forzar CFR.
_CFR_FPS_OPTIONS = [23.976, 24, 25, 29.97, 30, 50, 59.94, 60]

_FIT_MODE_LABELS = {
    "deformar": QT_TRANSLATE_NOOP("AdvancedRecodePanel", "Deformar"),
    "ajustar": QT_TRANSLATE_NOOP("AdvancedRecodePanel", "Ajustar"),
    "crop": QT_TRANSLATE_NOOP("AdvancedRecodePanel", "Recortar"),
}
_FIT_MODE_TOOLTIPS = {
    "deformar": QCoreApplication.translate("advanced_recode_panel", "Estira la imagen al tamaño exacto elegido, sin respetar su relación de aspecto original."),
    "ajustar": QCoreApplication.translate("advanced_recode_panel", "Encoge la imagen para que quepa entera en el tamaño elegido y rellena el sobrante con barras negras."),
    "crop": QCoreApplication.translate("advanced_recode_panel", "Agranda la imagen para cubrir todo el tamaño elegido y recorta lo que sobre por los bordes."),
}

_PREFERRED_CONTAINER_BY_CODEC = {
    # Video profesional / edición -> qtff (MOV)
    "prores": "qtff",
    "dnxhd": "qtff",
    "dnxhr": "qtff",
    "cfhd": "qtff",
    "qtrle": "qtff",
    "hap": "qtff",
    # Animaciones
    "gif": "gif",
    "apng": "apng",
    # Web / Abiertos
    "theora": "ogg",
    "vp8": "webm",
    "vp9": "webm",
    "h264": "mp4",
    "hevc": "mp4",
    "av1": "mp4",
    "vvc": "mp4",
    # Audio
    "mp3": "mp3",
    "aac": "m4a",
    "flac": "flac",
    "alac": "m4a",
    "opus": "opus",
    "vorbis": "ogg",
    "pcm_s16le": "wav",
    "pcm_s24le": "wav",
    "pcm_s32le": "wav",
    "pcm_f32le": "wav",
}


class AdvancedRecodePanel(QWidget):
    """
    Pestaña "Avanzado": eleccion libre de codec de video/audio (o copiar el stream
    original) y contenedor, validada en vivo contra recode_guard (ffmpeg_codec_matrix.json
    + hardware_detector) antes de permitir iniciar el proceso.
    """
    validity_changed = Signal(bool)
    crop_edit_toggled = Signal(bool)
    crop_dimensions_changed = Signal(int, int)  # width_px, height_px (tipeados a mano en Ancho/Alto)
    text_watermark_style_changed = Signal()
    image_watermark_style_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._building = False
        self._last_valid = True
        self._force_cpu_engine = False
        self._last_profile_codec = {"video": None, "audio": None}
        self._source_meta = None
        self._crop_active = False
        self._source_filepath = None
        self._init_ui()
        self._reload_codec_lists()
        initial_video_codec = self._current_video_codec()
        if initial_video_codec:
            self._apply_audio_recommendation(initial_video_codec)
        self._on_selection_changed()

    def _init_ui(self):
        self.setObjectName("advancedTabPanel")
        self.setStyleSheet("""
            QWidget#advancedTabPanel { background: transparent; }
            QScrollArea#advancedScroll { background: transparent; }
            QWidget#advancedContent { background: transparent; }
        """)
        
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setObjectName("advancedScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)

        content = QWidget(scroll)
        content.setObjectName("advancedContent")
        self._content_widget = content
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # 0. Selector de Modo (Video + Audio / Solo Audio / Solo Video)
        self.mode_selector = ModeSelector(content)
        self.mode_selector.mode_changed.connect(self._on_mode_changed)
        layout.addWidget(self.mode_selector)

        # 1. Tarjeta de Estado de Compatibilidad
        layout.addWidget(self._build_messages_section(content))

        # 2. Lista vertical de secciones. Video/Audio/Transformación/Marca de agua son
        # acordeones colapsables (Video y Audio abiertos por defecto, las otras dos
        # cerradas); Contenedor de salida y Peso estimado son tarjetas cortas que se
        # dejan siempre visibles, sin acordeón.
        self._build_stream_section(self.tr("Video"), "video", is_video=True, parent=content)
        self._build_stream_section(self.tr("Audio"), "audio", is_video=False, parent=content)
        self._build_transform_section(content)
        self._build_watermark_section(content)
        self._build_container_section(content)
        self._build_size_estimate_section(content)

        self.section_video = CollapsibleSection(
            self.tr("Video"), self.frame_video, start_expanded=True, header_extra=self.lbl_video_engine,
        )
        self.section_audio = CollapsibleSection(
            self.tr("Audio"), self.frame_audio, start_expanded=True, header_extra=self.lbl_audio_engine,
        )
        self.section_transform = CollapsibleSection(
            self.tr("Transformación de video"), self.frame_transform, start_expanded=False,
        )
        self.section_watermark = CollapsibleSection(
            self.tr("Marca de agua"), self.frame_watermark, start_expanded=False,
        )

        self.cards_column = QVBoxLayout()
        self.cards_column.setSpacing(10)
        self.cards_column.addWidget(self.section_video)
        self.cards_column.addWidget(self.section_audio)
        self.cards_column.addWidget(self.section_transform)
        self.cards_column.addWidget(self.section_watermark)
        self.cards_column.addWidget(self.frame_container)
        self.cards_column.addWidget(self.frame_size)

        layout.addLayout(self.cards_column)

        # Preajustes: va debajo de todo el panel (no es una tarjeta más de la
        # cuadrícula) - ver conversación sobre el sistema de presets.
        preset_card, preset_card_layout = self._card_frame(self.tr("Preajustes"), parent=content)
        self.preset_bar = PresetBar(
            _PRESET_NAMESPACE, self.get_settings, preset_card,
            show_picker=False, show_save_button=True,
        )
        preset_card_layout.addWidget(self.preset_bar)
        preset_card_layout.addStretch(1)
        layout.addWidget(preset_card)

        layout.addStretch(1)

        scroll.setWidget(content)
        outer.addWidget(scroll)

    def _card_frame(self, title: str | None = None, parent=None, bordered: bool = True) -> tuple[QFrame, QVBoxLayout]:
        """Crea una tarjeta con fondo transparente y borde sutil mediante ID selector para no afectar popups.

        `bordered=False` se usa para las secciones que van dentro de un CollapsibleSection
        (Video/Audio/Transformación/Marca de agua): ese widget ya aporta su propio borde y
        título en el header, así que la tarjeta interna no debe duplicarlos."""
        frame = QFrame(parent or self)
        frame.setObjectName("advancedCard")
        if bordered:
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
        v.setSizeConstraint(QVBoxLayout.SetMinimumSize)
        v.setContentsMargins(12, 10, 12, 12)
        v.setSpacing(8)
        if title:
            lbl = QLabel(title, frame)
            lbl.setObjectName("sectionTitle")
            lbl.setAlignment(Qt.AlignCenter)
            v.addWidget(lbl)
        return frame, v

    def _setup_fixed_combo(self, combo: QComboBox):
        """Configura el combo para que nunca empuje el ancho de columna aunque el texto sea largo."""
        combo.setMaxVisibleItems(_MAX_VISIBLE_COMBO_ITEMS)
        combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(1)
        combo.setItemDelegate(CheckmarkComboDelegate(combo))
        # El filtro global de cursor (HandCursorInstaller, main.py) escucha ChildAdded, pero aquí
        # todos los combos se construyen pasando el parent directo al constructor
        # (AutoPopupComboBox(frame)) en vez de agregarlos después vía layout.addWidget() — con eso
        # el evento ChildAdded nunca llega a dispararse (verificado), así que el filtro global no
        # los alcanza nunca. Se fija a mano aquí, mismo patrón que ya usan los QRadioButton/
        # QCheckBox de este archivo.
        combo.setCursor(Qt.PointingHandCursor)

    def _build_stream_section(self, title: str, prefix: str, is_video: bool, parent=None) -> QFrame:
        # bordered=False y sin título propio: esta tarjeta vive dentro de un
        # CollapsibleSection que ya aporta el borde y el título en su header.
        frame, v = self._card_frame(parent=parent, bordered=False)

        # Badge CPU/GPU: se pasa como header_extra al CollapsibleSection (ver _init_ui),
        # ya no vive en una fila propia dentro de la tarjeta.
        engine_badge = QPushButton("")
        engine_badge.setObjectName(f"{prefix}EngineBadge")
        engine_badge.setCursor(Qt.PointingHandCursor)
        engine_badge.setVisible(False)

        # Selector de Modo (Recodificar / Copiar original)
        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 2, 0, 4)
        mode_row.setSpacing(14)

        rb_recode = QRadioButton(self.tr("Recodificar"), frame)
        rb_copy = QRadioButton(self.tr("Copiar original"), frame)
        rb_recode.setChecked(True)
        rb_recode.setCursor(Qt.PointingHandCursor)
        rb_copy.setCursor(Qt.PointingHandCursor)

        group = QButtonGroup(frame)
        group.addButton(rb_recode)
        group.addButton(rb_copy)
        mode_row.addWidget(rb_recode)
        mode_row.addWidget(rb_copy)
        mode_row.addStretch(1)
        v.addLayout(mode_row)

        # Códec
        lbl_codec = QLabel(self.tr("Códec:"), frame)
        lbl_codec.setObjectName("menuLabel")
        v.addWidget(lbl_codec)

        codec_combo = AutoPopupComboBox(frame)
        self._setup_fixed_combo(codec_combo)
        v.addWidget(codec_combo)

        # Variante / Motor (Opcional)
        lbl_variant = QLabel(self.tr("Motor / Variante:"), frame)
        lbl_variant.setObjectName("menuLabel")
        v.addWidget(lbl_variant)
        lbl_variant.setVisible(False)

        variant_combo = AutoPopupComboBox(frame)
        self._setup_fixed_combo(variant_combo)
        v.addWidget(variant_combo)
        variant_combo.setVisible(False)

        # Perfil de Calidad
        lbl_profile = QLabel(self.tr("Perfil de calidad:"), frame)
        lbl_profile.setObjectName("menuLabel")
        v.addWidget(lbl_profile)

        profile_combo = AutoPopupComboBox(frame)
        self._setup_fixed_combo(profile_combo)
        v.addWidget(profile_combo)

        # Valor Personalizado (Bitrate o CQ)
        custom_container = QWidget(frame)
        custom_layout = QVBoxLayout(custom_container)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        custom_layout.setSpacing(4)

        lbl_custom = QLabel(self.tr("Valor:"), custom_container)
        lbl_custom.setObjectName("menuLabel")
        custom_layout.addWidget(lbl_custom)

        bitrate_spin = QSpinBox(custom_container)
        if is_video:
            bitrate_spin.setRange(64, 500000)
            bitrate_spin.setSingleStep(500)
            bitrate_spin.setValue(8000)
        else:
            bitrate_spin.setRange(16, 640)
            bitrate_spin.setSingleStep(32)
            bitrate_spin.setValue(192)
        bitrate_spin.setSuffix(" kbps")
        bitrate_spin.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        custom_layout.addWidget(bitrate_spin)

        cq_spin = QSpinBox(custom_container)
        cq_spin.setRange(0, 63)
        cq_spin.setSingleStep(1)
        cq_spin.setValue(23)
        cq_spin.setSuffix(" (CRF/CQ)")
        cq_spin.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        custom_layout.addWidget(cq_spin)

        if is_video:
            gif_container = QWidget(custom_container)
            gif_layout = QVBoxLayout(gif_container)
            gif_layout.setContentsMargins(0, 0, 0, 0)
            gif_layout.setSpacing(4)

            lbl_dither = QLabel(self.tr("Difuminado (Dither):"), gif_container)
            lbl_dither.setObjectName("menuLabel")
            gif_layout.addWidget(lbl_dither)

            combo_dither = AutoPopupComboBox(gif_container)
            self._setup_fixed_combo(combo_dither)
            combo_dither.addItem(self.tr("Floyd-Steinberg (Suave, estándar)"), "floyd_steinberg")
            combo_dither.addItem(self.tr("Bayer (Geométrico, liviano)"), "bayer")
            combo_dither.addItem(self.tr("Sierra2_4a (Equilibrado)"), "sierra2_4a")
            combo_dither.addItem(self.tr("Sierra2"), "sierra2")
            combo_dither.addItem(self.tr("Sin Difuminado (Colores planos)"), "none")
            gif_layout.addWidget(combo_dither)

            lbl_stats = QLabel(self.tr("Generación de Paleta:"), gif_container)
            lbl_stats.setObjectName("menuLabel")
            gif_layout.addWidget(lbl_stats)

            combo_stats = AutoPopupComboBox(gif_container)
            self._setup_fixed_combo(combo_stats)
            combo_stats.addItem(self.tr("Global / Todo el clip (full)"), "full")
            combo_stats.addItem(self.tr("Zonas en movimiento (diff)"), "diff")
            combo_stats.addItem(self.tr("Por Fotograma (single)"), "single")
            gif_layout.addWidget(combo_stats)

            lbl_colors = QLabel(self.tr("Máximo de Colores:"), gif_container)
            lbl_colors.setObjectName("menuLabel")
            gif_layout.addWidget(lbl_colors)

            combo_colors = AutoPopupComboBox(gif_container)
            self._setup_fixed_combo(combo_colors)
            combo_colors.addItem(self.tr("256 colores (Máximo)"), 256)
            combo_colors.addItem(self.tr("128 colores"), 128)
            combo_colors.addItem(self.tr("64 colores"), 64)
            combo_colors.addItem(self.tr("32 colores"), 32)
            combo_colors.addItem(self.tr("16 colores"), 16)
            gif_layout.addWidget(combo_colors)

            lbl_fps = QLabel(self.tr("Cuadros por Segundo (FPS):"), gif_container)
            lbl_fps.setObjectName("menuLabel")
            gif_layout.addWidget(lbl_fps)

            combo_fps = AutoPopupComboBox(gif_container)
            self._setup_fixed_combo(combo_fps)
            combo_fps.addItem(self.tr("Original (Sin cambios)"), None)
            combo_fps.addItem(self.tr("30 FPS (Fluido)"), 30)
            combo_fps.addItem(self.tr("24 FPS (Cinemático)"), 24)
            combo_fps.addItem(self.tr("20 FPS"), 20)
            combo_fps.addItem(self.tr("15 FPS (Recomendado para GIF)"), 15)
            combo_fps.addItem(self.tr("12 FPS (Ligero)"), 12)
            combo_fps.addItem(self.tr("10 FPS (Máximo ahorro)"), 10)
            gif_layout.addWidget(combo_fps)

            custom_layout.addWidget(gif_container)
            gif_container.setVisible(False)
            self.widget_video_gif_custom = gif_container
            self.combo_video_gif_dither = combo_dither
            self.combo_video_gif_stats = combo_stats
            self.combo_video_gif_colors = combo_colors
            self.combo_video_gif_fps = combo_fps

            combo_dither.currentIndexChanged.connect(self._update_size_estimate)
            combo_stats.currentIndexChanged.connect(self._update_size_estimate)
            combo_colors.currentIndexChanged.connect(self._update_size_estimate)
            combo_fps.currentIndexChanged.connect(self._update_size_estimate)

        v.addWidget(custom_container)
        custom_container.setVisible(False)

        # Registro de atributos
        setattr(self, f"rb_{prefix}_recode", rb_recode)
        setattr(self, f"rb_{prefix}_copy", rb_copy)
        setattr(self, f"lbl_{prefix}_codec", lbl_codec)
        setattr(self, f"combo_{prefix}_codec", codec_combo)
        setattr(self, f"lbl_{prefix}_variant", lbl_variant)
        setattr(self, f"combo_{prefix}_variant", variant_combo)
        setattr(self, f"lbl_{prefix}_engine", engine_badge)
        setattr(self, f"lbl_{prefix}_profile", lbl_profile)
        setattr(self, f"combo_{prefix}_profile", profile_combo)
        setattr(self, f"widget_{prefix}_custom", custom_container)
        setattr(self, f"lbl_{prefix}_custom", lbl_custom)
        setattr(self, f"spin_{prefix}_bitrate", bitrate_spin)
        setattr(self, f"spin_{prefix}_cq", cq_spin)
        setattr(self, f"frame_{prefix}", frame)

        rb_recode.toggled.connect(self._on_selection_changed)
        if is_video:
            codec_combo.currentIndexChanged.connect(self._on_video_codec_changed)
        else:
            codec_combo.currentIndexChanged.connect(self._on_selection_changed)
        profile_combo.currentIndexChanged.connect(lambda *_: self._on_profile_changed(prefix))
        variant_combo.currentIndexChanged.connect(lambda *_: self._on_variant_changed(prefix))
        bitrate_spin.valueChanged.connect(self._update_size_estimate)
        cq_spin.valueChanged.connect(self._update_size_estimate)

        if is_video:
            engine_badge.clicked.connect(self._toggle_engine_mode)

        # Pasadas (Solo Video)
        if is_video:
            pass_container = QWidget(frame)
            pass_layout = QVBoxLayout(pass_container)
            pass_layout.setContentsMargins(0, 0, 0, 4)
            pass_layout.setSpacing(8)

            lbl_passes = QLabel(self.tr("Pasadas:"), pass_container)
            lbl_passes.setObjectName("menuLabel")
            pass_layout.addWidget(lbl_passes)

            pass_radios_row = QHBoxLayout()
            pass_radios_row.setContentsMargins(0, 0, 0, 0)
            pass_radios_row.setSpacing(16)

            rb_pass1 = QRadioButton(self.tr("1 pasada"), pass_container)
            rb_pass2 = QRadioButton(self.tr("2 pasadas"), pass_container)
            rb_pass1.setCursor(Qt.PointingHandCursor)
            rb_pass2.setCursor(Qt.PointingHandCursor)
            rb_pass2.setToolTip(self.tr("2 pasadas: más precisión de bitrate objetivo, tarda el doble."))
            rb_pass1.setChecked(True)

            pass_group = QButtonGroup(pass_container)
            pass_group.addButton(rb_pass1)
            pass_group.addButton(rb_pass2)
            pass_radios_row.addWidget(rb_pass1)
            pass_radios_row.addWidget(rb_pass2)
            pass_radios_row.addStretch(1)
            pass_layout.addLayout(pass_radios_row)

            v.addWidget(pass_container)
            self.widget_video_passes = pass_container
            self.lbl_video_passes = lbl_passes
            self.rb_video_pass1 = rb_pass1
            self.rb_video_pass2 = rb_pass2
            pass_container.setVisible(False)
            rb_pass1.toggled.connect(self._update_size_estimate)

        if not is_video:
            channels_container = QWidget(frame)
            channels_layout = QVBoxLayout(channels_container)
            channels_layout.setContentsMargins(0, 0, 0, 4)
            channels_layout.setSpacing(8)

            lbl_channels = QLabel(self.tr("Canales:"), channels_container)
            lbl_channels.setObjectName("menuLabel")
            channels_layout.addWidget(lbl_channels)

            channels_combo = AutoPopupComboBox(channels_container)
            self._setup_fixed_combo(channels_combo)
            channels_combo.addItem(self.tr("Igual al original"), "")
            channels_combo.addItem(self.tr("Mono (1 canal)"), "1")
            channels_combo.addItem(self.tr("Estéreo (2 canales)"), "2")
            channels_combo.addItem(self.tr("5.1 Surround"), "6")
            channels_layout.addWidget(channels_combo)

            v.addWidget(channels_container)
            self.widget_audio_channels = channels_container
            self.lbl_audio_channels = lbl_channels
            self.combo_audio_channels = channels_combo

            samplerate_container = QWidget(frame)
            samplerate_layout = QVBoxLayout(samplerate_container)
            samplerate_layout.setContentsMargins(0, 0, 0, 4)
            samplerate_layout.setSpacing(8)

            lbl_samplerate = QLabel(self.tr("Velocidad de muestreo:"), samplerate_container)
            lbl_samplerate.setObjectName("menuLabel")
            samplerate_layout.addWidget(lbl_samplerate)

            samplerate_combo = AutoPopupComboBox(samplerate_container)
            self._setup_fixed_combo(samplerate_combo)
            samplerate_combo.addItem(self.tr("Igual al original"), "")
            samplerate_combo.addItem("48000 Hz", "48000")
            samplerate_combo.addItem("44100 Hz", "44100")
            samplerate_combo.addItem("32000 Hz", "32000")
            samplerate_combo.addItem("24000 Hz", "24000")
            samplerate_combo.addItem("22050 Hz", "22050")
            samplerate_combo.addItem("16000 Hz", "16000")
            samplerate_layout.addWidget(samplerate_combo)

            v.addWidget(samplerate_container)
            self.widget_audio_samplerate = samplerate_container
            self.lbl_audio_samplerate = lbl_samplerate
            self.combo_audio_samplerate = samplerate_combo

            # ── Normalización de Audio ─────────────────────────
            self.chk_audio_normalize = QCheckBox(self.tr("Normalizar audio"), frame)
            self.chk_audio_normalize.setCursor(Qt.PointingHandCursor)
            v.addWidget(self.chk_audio_normalize)

            norm_container = QWidget(frame)
            norm_layout = QVBoxLayout(norm_container)
            norm_layout.setContentsMargins(18, 2, 0, 0)
            norm_layout.setSpacing(6)

            # Selector de método
            lbl_norm_method = QLabel(self.tr("Método:"), norm_container)
            lbl_norm_method.setObjectName("menuLabel")
            norm_layout.addWidget(lbl_norm_method)

            self.combo_audio_norm_method = AutoPopupComboBox(norm_container)
            self._setup_fixed_combo(self.combo_audio_norm_method)
            self.combo_audio_norm_method.addItem(self.tr("Sonoridad Percibida (EBU R128 / LUFS)"), "loudnorm")
            self.combo_audio_norm_method.addItem(self.tr("Dinámica Inteligente (Voz y Diálogo)"), "dynaudnorm")
            self.combo_audio_norm_method.addItem(self.tr("Normalización por Pico (dBFS)"), "peak")
            norm_layout.addWidget(self.combo_audio_norm_method)

            # Sub-panel 1: Sonoridad Percibida (loudnorm)
            self.widget_norm_loudnorm = QWidget(norm_container)
            loudnorm_layout = QVBoxLayout(self.widget_norm_loudnorm)
            loudnorm_layout.setContentsMargins(0, 2, 0, 0)
            loudnorm_layout.setSpacing(4)

            # I (Sonoridad Integrada)
            lbl_loudnorm_i = QLabel(self.tr("Sonoridad integrada (I):"), self.widget_norm_loudnorm)
            lbl_loudnorm_i.setObjectName("menuLabel")
            loudnorm_layout.addWidget(lbl_loudnorm_i)
            self.spin_loudnorm_i = QDoubleSpinBox(self.widget_norm_loudnorm)
            self.spin_loudnorm_i.setRange(-70.0, -5.0)
            self.spin_loudnorm_i.setSingleStep(0.5)
            self.spin_loudnorm_i.setValue(-14.0)
            self.spin_loudnorm_i.setDecimals(1)
            self.spin_loudnorm_i.setSuffix(" LUFS")
            self.spin_loudnorm_i.setToolTip(self.tr("Sonoridad integrada promedio (típico: -14 LUFS para web/streaming, -23 LUFS para broadcast)."))
            loudnorm_layout.addWidget(self.spin_loudnorm_i)

            # TP (Pico real máximo)
            lbl_loudnorm_tp = QLabel(self.tr("Pico real máximo (TP):"), self.widget_norm_loudnorm)
            lbl_loudnorm_tp.setObjectName("menuLabel")
            loudnorm_layout.addWidget(lbl_loudnorm_tp)
            self.spin_loudnorm_tp = QDoubleSpinBox(self.widget_norm_loudnorm)
            self.spin_loudnorm_tp.setRange(-9.0, 0.0)
            self.spin_loudnorm_tp.setSingleStep(0.5)
            self.spin_loudnorm_tp.setValue(-1.0)
            self.spin_loudnorm_tp.setDecimals(1)
            self.spin_loudnorm_tp.setSuffix(" dBTP")
            self.spin_loudnorm_tp.setToolTip(self.tr("Límite máximo de True Peak para evitar distorsión digital o analógica (típico: -1.0 dBTP)."))
            loudnorm_layout.addWidget(self.spin_loudnorm_tp)

            # LRA (Rango de sonoridad)
            lbl_loudnorm_lra = QLabel(self.tr("Rango de sonoridad (LRA):"), self.widget_norm_loudnorm)
            lbl_loudnorm_lra.setObjectName("menuLabel")
            loudnorm_layout.addWidget(lbl_loudnorm_lra)
            self.spin_loudnorm_lra = QDoubleSpinBox(self.widget_norm_loudnorm)
            self.spin_loudnorm_lra.setRange(1.0, 50.0)
            self.spin_loudnorm_lra.setSingleStep(1.0)
            self.spin_loudnorm_lra.setValue(11.0)
            self.spin_loudnorm_lra.setDecimals(1)
            self.spin_loudnorm_lra.setSuffix(" LU")
            self.spin_loudnorm_lra.setToolTip(self.tr("Rango de sonoridad permitido (típico: 11 LU para streaming/música, 7 LU para TV)."))
            loudnorm_layout.addWidget(self.spin_loudnorm_lra)

            norm_layout.addWidget(self.widget_norm_loudnorm)

            # Sub-panel 2: Dinámica Inteligente (dynaudnorm)
            self.widget_norm_dynaudnorm = QWidget(norm_container)
            dynaudnorm_layout = QVBoxLayout(self.widget_norm_dynaudnorm)
            dynaudnorm_layout.setContentsMargins(0, 2, 0, 0)
            dynaudnorm_layout.setSpacing(4)

            # Ganancia máxima
            lbl_dyn_gain = QLabel(self.tr("Ganancia máxima:"), self.widget_norm_dynaudnorm)
            lbl_dyn_gain.setObjectName("menuLabel")
            dynaudnorm_layout.addWidget(lbl_dyn_gain)
            self.spin_dyn_gain = QDoubleSpinBox(self.widget_norm_dynaudnorm)
            self.spin_dyn_gain.setRange(1.0, 30.0)
            self.spin_dyn_gain.setSingleStep(1.0)
            self.spin_dyn_gain.setValue(10.0)
            self.spin_dyn_gain.setDecimals(1)
            self.spin_dyn_gain.setSuffix(" dB")
            self.spin_dyn_gain.setToolTip(self.tr("Amplificación máxima permitida para partes silenciosas (evita elevar demasiado el ruido de fondo)."))
            dynaudnorm_layout.addWidget(self.spin_dyn_gain)

            # Nivel de pico objetivo
            lbl_dyn_peak = QLabel(self.tr("Pico objetivo:"), self.widget_norm_dynaudnorm)
            lbl_dyn_peak.setObjectName("menuLabel")
            dynaudnorm_layout.addWidget(lbl_dyn_peak)
            self.spin_dyn_peak = QSpinBox(self.widget_norm_dynaudnorm)
            self.spin_dyn_peak.setRange(50, 100)
            self.spin_dyn_peak.setSingleStep(1)
            self.spin_dyn_peak.setValue(95)
            self.spin_dyn_peak.setSuffix(" %")
            self.spin_dyn_peak.setToolTip(self.tr("Nivel de volumen pico objetivo (95% ≈ -0.4 dBFS)."))
            dynaudnorm_layout.addWidget(self.spin_dyn_peak)

            # Ventana de análisis
            lbl_dyn_len = QLabel(self.tr("Ventana de análisis:"), self.widget_norm_dynaudnorm)
            lbl_dyn_len.setObjectName("menuLabel")
            dynaudnorm_layout.addWidget(lbl_dyn_len)
            self.spin_dyn_len = QSpinBox(self.widget_norm_dynaudnorm)
            self.spin_dyn_len.setRange(50, 3000)
            self.spin_dyn_len.setSingleStep(50)
            self.spin_dyn_len.setValue(500)
            self.spin_dyn_len.setSuffix(" ms")
            self.spin_dyn_len.setToolTip(self.tr("Tiempo de análisis para suavizar las transiciones de volumen (típico: 500 ms)."))
            dynaudnorm_layout.addWidget(self.spin_dyn_len)

            norm_layout.addWidget(self.widget_norm_dynaudnorm)
            self.widget_norm_dynaudnorm.setVisible(False)

            # Sub-panel 3: Normalización por Pico (peak)
            self.widget_norm_peak = QWidget(norm_container)
            peak_layout = QVBoxLayout(self.widget_norm_peak)
            peak_layout.setContentsMargins(0, 2, 0, 0)
            peak_layout.setSpacing(4)

            lbl_peak_val = QLabel(self.tr("Nivel de pico objetivo:"), self.widget_norm_peak)
            lbl_peak_val.setObjectName("menuLabel")
            peak_layout.addWidget(lbl_peak_val)
            self.spin_peak_val = QDoubleSpinBox(self.widget_norm_peak)
            self.spin_peak_val.setRange(-30.0, 0.0)
            self.spin_peak_val.setSingleStep(0.5)
            self.spin_peak_val.setValue(-1.0)
            self.spin_peak_val.setDecimals(1)
            self.spin_peak_val.setSuffix(" dB")
            self.spin_peak_val.setToolTip(self.tr("Límite máximo de pico de audio (ej: 0.0 dB máximo digital, -1.0 dB con margen seguro)."))
            peak_layout.addWidget(self.spin_peak_val)

            norm_layout.addWidget(self.widget_norm_peak)
            self.widget_norm_peak.setVisible(False)

            v.addWidget(norm_container)
            self.widget_audio_normalize = norm_container
            norm_container.setVisible(False)

            self.chk_audio_normalize.toggled.connect(self._on_audio_normalize_toggled)
            self.combo_audio_norm_method.currentIndexChanged.connect(self._on_audio_norm_method_changed)
            for spin in (
                self.spin_loudnorm_i, self.spin_loudnorm_tp, self.spin_loudnorm_lra,
                self.spin_dyn_gain, self.spin_dyn_peak, self.spin_dyn_len,
                self.spin_peak_val
            ):
                spin.valueChanged.connect(self._update_size_estimate)

        v.addStretch(1)
        return frame

    def _build_transform_section(self, parent=None) -> QFrame:
        # bordered=False y sin título propio: vive dentro de un CollapsibleSection.
        frame, v = self._card_frame(parent=parent, bordered=False)

        # ── CFR ──────────────────────────────────────────────
        cfr_row = QHBoxLayout()
        cfr_row.setSpacing(8)
        self.chk_cfr = QCheckBox(self.tr("CFR"), frame)
        self.chk_cfr.setCursor(Qt.PointingHandCursor)
        self.chk_cfr.setToolTip(self.tr(
            "Forzar FPS constante (Constant Frame Rate): reescribe el video a una tasa de "
            "fotogramas fija, en vez de conservar la original."
        ))
        cfr_row.addWidget(self.chk_cfr)

        self.combo_cfr_fps = AutoPopupComboBox(frame)
        self._setup_fixed_combo(self.combo_cfr_fps)
        self.combo_cfr_fps.setEditable(True)
        # _setup_fixed_combo deja el ancho "Ignored" + mínimo de 1 caracter (pensado para combos
        # de solo lectura en columnas angostas) — aquí hace falta lugar real para escribir/leer un
        # valor como "29.97 fps" sin que la caja quede achicada a una estampilla.
        self.combo_cfr_fps.setMinimumWidth(100)
        self.combo_cfr_fps.setToolTip(self.tr("Elige un valor común o escribe el FPS que prefieras."))
        from PySide6.QtGui import QDoubleValidator
        fps_validator = QDoubleValidator(1.0, 300.0, 3, self.combo_cfr_fps)
        fps_validator.setNotation(QDoubleValidator.StandardNotation)
        self.combo_cfr_fps.lineEdit().setValidator(fps_validator)
        for fps in _CFR_FPS_OPTIONS:
            label = f"{fps:g} fps"
            self.combo_cfr_fps.addItem(label, fps)
        self.combo_cfr_fps.setCurrentIndex(_CFR_FPS_OPTIONS.index(30))
        self.combo_cfr_fps.setEnabled(False)
        cfr_row.addWidget(self.combo_cfr_fps, 1)
        v.addLayout(cfr_row)

        self.chk_cfr.toggled.connect(self._on_cfr_toggled)
        self.combo_cfr_fps.currentIndexChanged.connect(self._update_size_estimate)

        # ── Resolución ───────────────────────────────────────
        lbl_res = QLabel(self.tr("Resolución:"), frame)
        lbl_res.setObjectName("menuLabel")
        v.addWidget(lbl_res)

        self.combo_resolution = AutoPopupComboBox(frame)
        self._setup_fixed_combo(self.combo_resolution)
        for key, label, _target in _RESOLUTION_PRESETS:
            self.combo_resolution.addItem(self.tr(label), key)
        v.addWidget(self.combo_resolution)
        self.combo_resolution.currentIndexChanged.connect(self._on_resolution_changed)

        # ── Sub-panel Personalizado ───────────────────────────
        custom_container = QWidget(frame)
        custom_layout = QVBoxLayout(custom_container)
        custom_layout.setContentsMargins(0, 4, 0, 0)
        custom_layout.setSpacing(6)

        dims_row = QHBoxLayout()
        dims_row.setSpacing(8)

        w_col = QVBoxLayout()
        lbl_w = QLabel(self.tr("Ancho:"), custom_container)
        lbl_w.setObjectName("menuLabel")
        w_col.addWidget(lbl_w)
        self.spin_custom_width = QSpinBox(custom_container)
        self.spin_custom_width.setRange(2, 7680)
        self.spin_custom_width.setSingleStep(2)
        self.spin_custom_width.setValue(1920)
        # Sin esto, valueChanged (y con él el redondeo a par + recálculo del alto vinculado)
        # dispara en cada tecla que escribes, no solo al terminar — por eso "19" saltaba a "20"
        # a mitad de escritura en vez de esperar a que sueltes el campo.
        self.spin_custom_width.setKeyboardTracking(False)
        w_col.addWidget(self.spin_custom_width)
        dims_row.addLayout(w_col)

        h_col = QVBoxLayout()
        lbl_h = QLabel(self.tr("Alto:"), custom_container)
        lbl_h.setObjectName("menuLabel")
        h_col.addWidget(lbl_h)
        self.spin_custom_height = QSpinBox(custom_container)
        self.spin_custom_height.setRange(2, 7680)
        self.spin_custom_height.setSingleStep(2)
        self.spin_custom_height.setValue(1080)
        self.spin_custom_height.setKeyboardTracking(False)
        h_col.addWidget(self.spin_custom_height)
        dims_row.addLayout(h_col)

        custom_layout.addLayout(dims_row)

        self.chk_keep_aspect = QCheckBox(self.tr("Conservar relación de aspecto"), custom_container)
        self.chk_keep_aspect.setCursor(Qt.PointingHandCursor)
        self.chk_keep_aspect.setChecked(True)
        self.chk_keep_aspect.setToolTip(self.tr(
            "Al escribir un valor, el otro se recalcula solo para mantener la proporción real del "
            "archivo de origen."
        ))
        custom_layout.addWidget(self.chk_keep_aspect)

        self.lbl_source_aspect = QLabel(self.tr("Fuente: -"), custom_container)
        self.lbl_source_aspect.setObjectName("mutedLabel")
        custom_layout.addWidget(self.lbl_source_aspect)

        fit_row = QHBoxLayout()
        fit_row.setSpacing(14)
        self.fit_mode_group = QButtonGroup(custom_container)
        self.rb_fit_deformar = QRadioButton(self.tr(_FIT_MODE_LABELS["deformar"]), custom_container)
        self.rb_fit_ajustar = QRadioButton(self.tr(_FIT_MODE_LABELS["ajustar"]), custom_container)
        self.rb_fit_crop = QRadioButton(self.tr(_FIT_MODE_LABELS["crop"]), custom_container)
        self.rb_fit_deformar.setToolTip(self.tr(_FIT_MODE_TOOLTIPS["deformar"]))
        self.rb_fit_ajustar.setToolTip(self.tr(_FIT_MODE_TOOLTIPS["ajustar"]))
        self.rb_fit_crop.setToolTip(self.tr(_FIT_MODE_TOOLTIPS["crop"]))
        self.rb_fit_ajustar.setChecked(True)
        for rb in (self.rb_fit_deformar, self.rb_fit_ajustar, self.rb_fit_crop):
            rb.setCursor(Qt.PointingHandCursor)
            self.fit_mode_group.addButton(rb)
            fit_row.addWidget(rb)
        custom_layout.addLayout(fit_row)

        self.chk_apply_crop_to_all = QCheckBox(self.tr("Aplicar a todos los medios"), custom_container)
        self.chk_apply_crop_to_all.setCursor(Qt.PointingHandCursor)
        self.chk_apply_crop_to_all.setVisible(False)
        custom_layout.addWidget(self.chk_apply_crop_to_all)

        v.addWidget(custom_container)
        self.widget_custom_resolution = custom_container
        custom_container.setVisible(False)

        self.spin_custom_width.valueChanged.connect(lambda _v: self._on_custom_dim_changed("width"))
        self.spin_custom_height.valueChanged.connect(lambda _v: self._on_custom_dim_changed("height"))
        self.chk_keep_aspect.toggled.connect(self._on_keep_aspect_toggled)
        for rb in (self.rb_fit_deformar, self.rb_fit_ajustar, self.rb_fit_crop):
            rb.toggled.connect(self._update_size_estimate)
            # Sin esto, elegir "Recortar" no activaba el recorte interactivo hasta que
            # además cambiara algún valor de Ancho/Alto (lo único que antes disparaba
            # _update_fit_mode_enabled) — debía activarse apenas se selecciona el radio.
            rb.toggled.connect(self._update_fit_mode_enabled)

        v.addStretch(1)
        self.frame_transform = frame
        return frame

    def _build_watermark_section(self, parent=None) -> QFrame:
        """Texto y/o imagen combinables. La posición NO se elige aquí — se arrastra sobre
        la vista previa (ver media_trim_player_widget.py::_DraggableWatermarkItem); este
        panel solo controla estilo (texto/fuente/tamaño/color/opacidad para texto,
        archivo/escala/opacidad para imagen)."""
        # bordered=False y sin título propio: vive dentro de un CollapsibleSection.
        frame, v = self._card_frame(parent=parent, bordered=False)

        lbl_hint = QLabel(self.tr("La posición se elige arrastrando sobre la vista previa."), frame)
        lbl_hint.setObjectName("mutedLabel")
        lbl_hint.setWordWrap(True)
        v.addWidget(lbl_hint)

        # ── Texto ──────────────────────────────────────────────
        self.chk_watermark_text = QCheckBox(self.tr("Agregar texto"), frame)
        self.chk_watermark_text.setCursor(Qt.PointingHandCursor)
        v.addWidget(self.chk_watermark_text)

        text_container = QWidget(frame)
        text_layout = QVBoxLayout(text_container)
        text_layout.setContentsMargins(18, 2, 0, 0)
        text_layout.setSpacing(6)

        self.txt_watermark_text = QLineEdit(text_container)
        self.txt_watermark_text.setPlaceholderText(self.tr("Texto de la marca de agua"))
        text_layout.addWidget(self.txt_watermark_text)

        font_row = QHBoxLayout()
        font_row.setSpacing(8)
        self.combo_watermark_font = AutoPopupComboBox(text_container)
        self._setup_fixed_combo(self.combo_watermark_font)
        for family in get_available_fonts():
            self.combo_watermark_font.addItem(family, family)
        default_idx = self.combo_watermark_font.findData(get_active_font_family())
        if default_idx >= 0:
            self.combo_watermark_font.setCurrentIndex(default_idx)
        font_row.addWidget(self.combo_watermark_font, 1)

        self._watermark_text_color = QColor("#FFFFFF")
        self.btn_watermark_text_color = QPushButton(text_container)
        self.btn_watermark_text_color.setFixedSize(28, 28)
        self.btn_watermark_text_color.setCursor(Qt.PointingHandCursor)
        self._update_color_button(self.btn_watermark_text_color, self._watermark_text_color)
        self.btn_watermark_text_color.clicked.connect(self._on_pick_watermark_text_color)
        font_row.addWidget(self.btn_watermark_text_color)
        text_layout.addLayout(font_row)

        weight_row = QHBoxLayout()
        weight_row.setSpacing(8)
        lbl_weight = QLabel(self.tr("Peso:"), text_container)
        lbl_weight.setObjectName("menuLabel")
        weight_row.addWidget(lbl_weight)
        self.combo_watermark_text_weight = AutoPopupComboBox(text_container)
        self._setup_fixed_combo(self.combo_watermark_text_weight)
        for label, value in STANDARD_WEIGHTS:
            self.combo_watermark_text_weight.addItem(self.tr(label), value)
        default_weight_idx = self.combo_watermark_text_weight.findData(400)
        if default_weight_idx >= 0:
            self.combo_watermark_text_weight.setCurrentIndex(default_weight_idx)
        weight_row.addWidget(self.combo_watermark_text_weight, 1)
        text_layout.addLayout(weight_row)

        size_row = QHBoxLayout()
        size_row.setSpacing(8)
        lbl_size = QLabel(self.tr("Tamaño:"), text_container)
        lbl_size.setObjectName("menuLabel")
        size_row.addWidget(lbl_size)
        self.spin_watermark_text_size = QSpinBox(text_container)
        self.spin_watermark_text_size.setRange(1, 30)
        self.spin_watermark_text_size.setValue(5)
        self.spin_watermark_text_size.setSuffix("%")
        self.spin_watermark_text_size.setToolTip(self.tr("Porcentaje de la altura del video de salida."))
        size_row.addWidget(self.spin_watermark_text_size)
        size_row.addStretch(1)
        text_layout.addLayout(size_row)

        opacity_row = QHBoxLayout()
        opacity_row.setSpacing(8)
        lbl_opacity = QLabel(self.tr("Opacidad:"), text_container)
        lbl_opacity.setObjectName("menuLabel")
        opacity_row.addWidget(lbl_opacity)
        self.slider_watermark_text_opacity = QSlider(Qt.Horizontal, text_container)
        self.slider_watermark_text_opacity.setRange(0, 100)
        self.slider_watermark_text_opacity.setValue(100)
        self.slider_watermark_text_opacity.setCursor(Qt.PointingHandCursor)
        opacity_row.addWidget(self.slider_watermark_text_opacity)
        self.lbl_watermark_text_opacity_val = QLabel("100%", text_container)
        self.lbl_watermark_text_opacity_val.setFixedWidth(36)
        self.lbl_watermark_text_opacity_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        opacity_row.addWidget(self.lbl_watermark_text_opacity_val)
        text_layout.addLayout(opacity_row)

        v.addWidget(text_container)
        self.widget_watermark_text = text_container
        text_container.setVisible(False)

        # ── Imagen ─────────────────────────────────────────────
        self.chk_watermark_image = QCheckBox(self.tr("Agregar imagen"), frame)
        self.chk_watermark_image.setCursor(Qt.PointingHandCursor)
        v.addWidget(self.chk_watermark_image)

        image_container = QWidget(frame)
        image_layout = QVBoxLayout(image_container)
        image_layout.setContentsMargins(18, 2, 0, 0)
        image_layout.setSpacing(6)

        file_row = QHBoxLayout()
        file_row.setSpacing(8)
        self.txt_watermark_image_path = QLineEdit(image_container)
        self.txt_watermark_image_path.setPlaceholderText(self.tr("Ningún archivo seleccionado"))
        self.txt_watermark_image_path.setReadOnly(True)
        file_row.addWidget(self.txt_watermark_image_path, 1)
        self.btn_watermark_image_browse = QPushButton(self.tr("Examinar…"), image_container)
        self.btn_watermark_image_browse.setObjectName("secondaryButton")
        self.btn_watermark_image_browse.setCursor(Qt.PointingHandCursor)
        self.btn_watermark_image_browse.clicked.connect(self._on_browse_watermark_image)
        file_row.addWidget(self.btn_watermark_image_browse)
        image_layout.addLayout(file_row)

        scale_row = QHBoxLayout()
        scale_row.setSpacing(8)
        lbl_scale = QLabel(self.tr("Tamaño:"), image_container)
        lbl_scale.setObjectName("menuLabel")
        scale_row.addWidget(lbl_scale)
        self.spin_watermark_image_scale = QSpinBox(image_container)
        self.spin_watermark_image_scale.setRange(1, 100)
        self.spin_watermark_image_scale.setValue(15)
        self.spin_watermark_image_scale.setSuffix("%")
        self.spin_watermark_image_scale.setToolTip(self.tr("Porcentaje del ancho del video de salida."))
        scale_row.addWidget(self.spin_watermark_image_scale)
        scale_row.addStretch(1)
        image_layout.addLayout(scale_row)

        image_opacity_row = QHBoxLayout()
        image_opacity_row.setSpacing(8)
        lbl_image_opacity = QLabel(self.tr("Opacidad:"), image_container)
        lbl_image_opacity.setObjectName("menuLabel")
        image_opacity_row.addWidget(lbl_image_opacity)
        self.slider_watermark_image_opacity = QSlider(Qt.Horizontal, image_container)
        self.slider_watermark_image_opacity.setRange(0, 100)
        self.slider_watermark_image_opacity.setValue(100)
        self.slider_watermark_image_opacity.setCursor(Qt.PointingHandCursor)
        image_opacity_row.addWidget(self.slider_watermark_image_opacity)
        self.lbl_watermark_image_opacity_val = QLabel("100%", image_container)
        self.lbl_watermark_image_opacity_val.setFixedWidth(36)
        self.lbl_watermark_image_opacity_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        image_opacity_row.addWidget(self.lbl_watermark_image_opacity_val)
        image_layout.addLayout(image_opacity_row)

        v.addWidget(image_container)
        self.widget_watermark_image = image_container
        image_container.setVisible(False)

        self._watermark_image_path = ""
        self._text_watermark_pos = (0.9, 0.9)
        self._image_watermark_pos = (0.9, 0.9)

        self.chk_watermark_text.toggled.connect(self._on_watermark_text_toggled)
        self.txt_watermark_text.textChanged.connect(self._on_watermark_text_field_changed)
        self.combo_watermark_font.currentIndexChanged.connect(self._on_watermark_text_field_changed)
        self.combo_watermark_text_weight.currentIndexChanged.connect(self._on_watermark_text_field_changed)
        self.spin_watermark_text_size.valueChanged.connect(self._on_watermark_text_field_changed)
        self.slider_watermark_text_opacity.valueChanged.connect(self._on_watermark_text_field_changed)

        self.chk_watermark_image.toggled.connect(self._on_watermark_image_toggled)
        self.spin_watermark_image_scale.valueChanged.connect(self._on_watermark_image_field_changed)
        self.slider_watermark_image_opacity.valueChanged.connect(self._on_watermark_image_field_changed)

        v.addStretch(1)
        self.frame_watermark = frame
        return frame

    def _update_color_button(self, button: QPushButton, color: QColor):
        button.setStyleSheet(
            f"QPushButton {{ background-color: {color.name()}; border: 1px solid #555555; border-radius: 4px; }}"
        )

    def _on_pick_watermark_text_color(self):
        # Reusar el selector de color ya existente (mismo que las etiquetas de carpetas/
        # colecciones en Herramientas Multimedia) en vez de QColorDialog nativo.
        from gui.dialogs.dialogs import AdobeColorPickerDialog
        dialog = AdobeColorPickerDialog(self._watermark_text_color.name(), self)
        if dialog.exec():
            self._watermark_text_color = QColor(dialog.get_color())
            self._update_color_button(self.btn_watermark_text_color, self._watermark_text_color)
            self._on_watermark_text_field_changed()

    def _on_browse_watermark_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Seleccionar imagen de marca de agua"), "",
            self.tr("Imágenes (*.png *.jpg *.jpeg *.webp *.bmp);;Todos los archivos (*.*)"),
        )
        if file_path:
            self._watermark_image_path = file_path
            self.txt_watermark_image_path.setText(file_path)
            # A diferencia de un cambio de estilo cualquiera, la ruta del archivo sí
            # puede afectar la validez (aviso de "no existe") — revalidar aquí.
            self.image_watermark_style_changed.emit()
            self._evaluate_and_render()

    def _show_watermark_container(self, container: QWidget, visible: bool):
        container.setVisible(visible)
        self._relayout_cards()

    def _on_watermark_text_toggled(self, checked: bool):
        if self._building:
            return
        self._show_watermark_container(self.widget_watermark_text, checked)
        self.text_watermark_style_changed.emit()
        self._evaluate_and_render()

    def _on_watermark_text_field_changed(self, *_args):
        """Cambios de texto/fuente/tamaño/color/opacidad: solo re-empujan el estilo a
        la vista previa. A propósito NO llaman a _show_watermark_container ni
        _evaluate_and_render en cada tick — eso es lo que hacía saltar la UI mientras
        se arrastraba el slider de opacidad (reconstruía la tarjeta de mensajes y
        forzaba adjustSize() en cada movimiento del mouse)."""
        if hasattr(self, "lbl_watermark_text_opacity_val") and hasattr(self, "slider_watermark_text_opacity"):
            self.lbl_watermark_text_opacity_val.setText(f"{self.slider_watermark_text_opacity.value()}%")
        if self._building:
            return
        self.text_watermark_style_changed.emit()

    def _on_watermark_image_toggled(self, checked: bool):
        if self._building:
            return
        self._show_watermark_container(self.widget_watermark_image, checked)
        self.image_watermark_style_changed.emit()
        self._evaluate_and_render()

    def _on_watermark_image_field_changed(self, *_args):
        if hasattr(self, "lbl_watermark_image_opacity_val") and hasattr(self, "slider_watermark_image_opacity"):
            self.lbl_watermark_image_opacity_val.setText(f"{self.slider_watermark_image_opacity.value()}%")
        if self._building:
            return
        self.image_watermark_style_changed.emit()

    def get_text_watermark_style(self) -> dict:
        return {
            "enabled": self.chk_watermark_text.isChecked(),
            "text": self.txt_watermark_text.text(),
            "font_family": self.combo_watermark_font.currentData() or self.combo_watermark_font.currentText(),
            "weight": self.combo_watermark_text_weight.currentData() or 400,
            "size_pct": self.spin_watermark_text_size.value(),
            "color": QColor(self._watermark_text_color),
            "opacity": self.slider_watermark_text_opacity.value() / 100.0,
        }

    def get_image_watermark_style(self) -> dict:
        return {
            "enabled": self.chk_watermark_image.isChecked(),
            "image_path": self._watermark_image_path,
            "scale_pct": self.spin_watermark_image_scale.value(),
            "opacity": self.slider_watermark_image_opacity.value() / 100.0,
        }

    def set_text_watermark_position(self, fx: float, fy: float):
        self._text_watermark_pos = (fx, fy)

    def set_image_watermark_position(self, fx: float, fy: float):
        self._image_watermark_pos = (fx, fy)

    def set_text_watermark_size(self, size_pct: float):
        """Refleja en el slider el tamaño arrastrado desde la manija de la vista previa
        (dirección opuesta al spin_watermark_text_size -> preview vía set_style)."""
        if self._building or round(size_pct) == self.spin_watermark_text_size.value():
            return
        self._building = True
        try:
            self.spin_watermark_text_size.setValue(round(size_pct))
        finally:
            self._building = False

    def set_image_watermark_size(self, scale_pct: float):
        """Refleja en el slider la escala arrastrada desde la manija de la vista previa."""
        if self._building or round(scale_pct) == self.spin_watermark_image_scale.value():
            return
        self._building = True
        try:
            self.spin_watermark_image_scale.setValue(round(scale_pct))
        finally:
            self._building = False

    def _build_text_watermark_filter(self) -> str | None:
        if not self.chk_watermark_text.isChecked():
            return None
        text = self.txt_watermark_text.text().strip()
        if not text:
            return None
        font_family = self.combo_watermark_font.currentData() or self.combo_watermark_font.currentText()
        weight = self.combo_watermark_text_weight.currentData() or 400
        font_path = get_static_font_path(font_family, weight)
        if not font_path:
            return None
        size_expr = f"h*{self.spin_watermark_text_size.value() / 100.0:.4f}"
        color_hex = self._watermark_text_color.name()
        opacity = self.slider_watermark_text_opacity.value() / 100.0
        fx, fy = self._text_watermark_pos
        return build_drawtext_filter(text, font_path, size_expr, color_hex, opacity, fx, fy)

    def _build_image_watermark_settings(self) -> tuple[str | None, str | None]:
        """(watermark_image_path, watermark_overlay_filter) — ambos None si la marca de
        agua de imagen está desactivada o sin archivo elegido."""
        if not self.chk_watermark_image.isChecked() or not self._watermark_image_path:
            return None, None
        scale_pct = self.spin_watermark_image_scale.value()
        opacity = self.slider_watermark_image_opacity.value() / 100.0
        fx, fy = self._image_watermark_pos
        # Aspecto real (alto/ancho) de la imagen: hace falta pasárselo al filtro para
        # que no se estire al aspecto del video (ver watermark_builder.build_image_overlay_filter).
        pixmap = QPixmap(self._watermark_image_path)
        aspect_hw = (pixmap.height() / pixmap.width()) if pixmap.width() > 0 else 1.0
        overlay_filter = build_image_overlay_filter(scale_pct, opacity, fx, fy, aspect_hw)
        return self._watermark_image_path, overlay_filter

    def _check_watermark_issues(self) -> dict | None:
        text_active = self.chk_watermark_text.isChecked() and bool(self.txt_watermark_text.text().strip())
        image_active = self.chk_watermark_image.isChecked() and bool(self._watermark_image_path)
        if not text_active and not image_active:
            return None
        if hasattr(self, "rb_video_copy") and self.rb_video_copy.isChecked():
            return {"severity": "blocked", "message": self.tr(
                "La marca de agua necesita recodificar el video: no funciona con 'Copiar original'.")}
        if image_active:
            warning = check_watermark_file({"watermark_image_path": self._watermark_image_path})
            if warning:
                return {"severity": "blocked", "message": warning}
        return None

    def _on_audio_normalize_toggled(self, checked: bool):
        if self._building:
            return
        self.widget_audio_normalize.setVisible(checked)
        self._relayout_cards()
        self._evaluate_and_render()
        self._update_size_estimate()

    def _on_audio_norm_method_changed(self, *_args):
        if self._building:
            return
        method = self.combo_audio_norm_method.currentData() or "loudnorm"
        self.widget_norm_loudnorm.setVisible(method == "loudnorm")
        self.widget_norm_dynaudnorm.setVisible(method == "dynaudnorm")
        self.widget_norm_peak.setVisible(method == "peak")
        self._relayout_cards()
        self._evaluate_and_render()
        self._update_size_estimate()

    def _build_audio_normalization_filter(self) -> str | None:
        if not hasattr(self, "chk_audio_normalize") or not self.chk_audio_normalize.isChecked():
            return None
        method = self.combo_audio_norm_method.currentData() or "loudnorm"
        if method == "loudnorm":
            params = {
                "integrated_lufs": self.spin_loudnorm_i.value(),
                "true_peak_dbtp": self.spin_loudnorm_tp.value(),
                "lra_lu": self.spin_loudnorm_lra.value(),
            }
        elif method == "dynaudnorm":
            params = {
                "max_gain_db": self.spin_dyn_gain.value(),
                "peak_factor": self.spin_dyn_peak.value() / 100.0,
                "frame_len_ms": self.spin_dyn_len.value(),
            }
        elif method == "peak":
            params = {
                "peak_db": self.spin_peak_val.value(),
            }
        else:
            params = {}
        return build_audio_normalization_filter(method, params)

    def _build_container_section(self, parent=None) -> QFrame:
        frame, v = self._card_frame(self.tr("Contenedor de salida"), parent=parent)

        self.combo_container = AutoPopupComboBox(frame)
        self._setup_fixed_combo(self.combo_container)
        v.addWidget(self.combo_container)

        lbl_hint = QLabel(self.tr("Se muestran únicamente los contenedores compatibles con los códecs seleccionados."), frame)
        lbl_hint.setObjectName("mutedLabel")
        lbl_hint.setWordWrap(True)
        v.addWidget(lbl_hint)

        self.combo_container.currentIndexChanged.connect(self._on_container_changed)
        v.addStretch(1)
        self.frame_container = frame
        return frame

    def _build_size_estimate_section(self, parent=None) -> QFrame:
        frame, v = self._card_frame(self.tr("Peso final estimado"), parent=parent)

        self.lbl_source_info = QLabel(self.tr("Selecciona un archivo en la cola para estimar el peso."), frame)
        self.lbl_source_info.setObjectName("mutedLabel")
        self.lbl_source_info.setWordWrap(True)
        v.addWidget(self.lbl_source_info)

        self.lbl_size_estimate = QLabel("", frame)
        self.lbl_size_estimate.setWordWrap(True)
        self.lbl_size_estimate.setObjectName("sectionTitle")
        v.addWidget(self.lbl_size_estimate)

        v.addStretch(1)
        self.frame_size = frame
        return frame

    def _build_messages_section(self, parent=None) -> QFrame:
        frame, v = self._card_frame(self.tr("Estado de compatibilidad"), parent=parent)
        self.messages_layout = QVBoxLayout()
        self.messages_layout.setContentsMargins(0, 2, 0, 2)
        self.messages_layout.setSpacing(6)
        v.addLayout(self.messages_layout)
        v.addStretch(1)
        return frame

    # ─── Poblado de combos ──────────────────────────────────────

    def _reload_codec_lists(self):
        self._building = True
        try:
            for combo, codecs in (
                (self.combo_video_codec, get_video_codecs(only_verified=False)),
                (self.combo_audio_codec, get_audio_codecs(only_verified=False)),
            ):
                combo.clear()
                model = combo.model()
                current_cat = None
                
                for c in codecs:
                    cat = c.get("category", "Otros")
                    if cat != current_cat:
                        current_cat = cat
                        # Insert header
                        combo.addItem(f"─── {current_cat.upper()} ───")
                        
                        # Disable the header item
                        idx = combo.count() - 1
                        item = model.item(idx)
                        item.setEnabled(False)
                        
                        # Style it
                        font = item.font()
                        font.setBold(True)
                        item.setFont(font)
                        item.setTextAlignment(Qt.AlignCenter)
                        
                    label = c["display_name"] if c["verified"] else self.tr("{0} (sin verificar)").format(c["display_name"])
                    combo.addItem(f"  {label}", c["codec_id"])
                    
                # Seleccionar el primer elemento que esté habilitado (saltando las cabeceras)
                for i in range(combo.count()):
                    if model.item(i).isEnabled():
                        combo.setCurrentIndex(i)
                        break
        finally:
            self._building = False

    # ─── Logica de cambio de seleccion ──────────────────────────

    def _current_stream_mode(self) -> str:
        """Devuelve 'video+audio', 'audio_only' o 'video_only'."""
        if not hasattr(self, "mode_selector"):
            return "video+audio"
        if self.mode_selector.btn_audio.isChecked():
            return "audio_only"
        if self.mode_selector.btn_video.isChecked():
            return "video_only"
        return "video+audio"

    def _on_mode_changed(self, _mode_text: str = ""):
        self._on_selection_changed()

    def _current_video_codec(self):
        if self._current_stream_mode() == "audio_only":
            return None
        if getattr(self, "frame_video", None) and not self.frame_video.isEnabled():
            return None
        if self.rb_video_copy.isChecked():
            return None
        return self.combo_video_codec.currentData()

    def _current_audio_codec(self):
        if self._current_stream_mode() == "video_only":
            return None
        if getattr(self, "frame_audio", None) and not self.frame_audio.isEnabled():
            return None
        if self.rb_audio_copy.isChecked():
            return None
        return self.combo_audio_codec.currentData()

    def _on_video_codec_changed(self, *_args):
        if self._building:
            return
        video_codec = self._current_video_codec()
        if video_codec and self.rb_audio_recode.isChecked():
            self._apply_audio_recommendation(video_codec)
        self._revalidate_custom_dimensions()
        self._on_selection_changed()

    def _apply_audio_recommendation(self, video_codec_id: str):
        """Autocompleta el codec de audio recomendado para agilizar el flujo."""
        recommended = recommend_audio_codec(video_codec_id)
        idx = self.combo_audio_codec.findData(recommended)
        if idx < 0 or idx == self.combo_audio_codec.currentIndex():
            return
        self._building = True
        try:
            self.combo_audio_codec.setCurrentIndex(idx)
        finally:
            self._building = False
        self._last_profile_codec["audio"] = None

    def _on_selection_changed(self, *_args):
        if self._building:
            return

        stream_mode = self._current_stream_mode()
        is_audio_only = (stream_mode == "audio_only")
        is_video_only = (stream_mode == "video_only")

        # Habilitar o deshabilitar columnas según el selector de modo
        if getattr(self, "frame_video", None):
            self.frame_video.setEnabled(not is_audio_only)

        is_gif = (self.combo_video_codec.currentData() == "gif" and self.rb_video_recode.isChecked() and not is_audio_only)
        if getattr(self, "frame_audio", None):
            self.frame_audio.setEnabled((not is_video_only) and (not is_gif))

        # Habilitar o deshabilitar campos según modo recodificar vs copiar
        video_recode = self.rb_video_recode.isChecked() and (not is_audio_only)
        audio_recode = self.rb_audio_recode.isChecked() and (not is_video_only)

        self.combo_video_codec.setEnabled(video_recode)
        self.combo_audio_codec.setEnabled(audio_recode)
        self.combo_video_profile.setEnabled(video_recode)
        self.combo_audio_profile.setEnabled(audio_recode)
        if hasattr(self, "combo_audio_channels"):
            self.combo_audio_channels.setEnabled(audio_recode)
        if hasattr(self, "combo_audio_samplerate"):
            self.combo_audio_samplerate.setEnabled(audio_recode)
        if hasattr(self, "chk_audio_normalize"):
            self.chk_audio_normalize.setEnabled(audio_recode)
            self.chk_audio_normalize.setToolTip(
                "" if audio_recode else self.tr("No disponible con Audio en modo 'Copiar original'.")
            )
            if hasattr(self, "widget_audio_normalize"):
                self.widget_audio_normalize.setEnabled(audio_recode)
        if getattr(self, "frame_transform", None):
            # Un filtro de video (-vf) o -r no puede aplicarse con -c:v copy.
            self.frame_transform.setEnabled(video_recode)
            self.frame_transform.setToolTip(
                "" if video_recode else self.tr("No disponible con Video en modo 'Copiar original'.")
            )

        self._relayout_cards()
        self._update_engine_label()
        self._refresh_variant_combo("video", self._current_video_codec())
        self._refresh_variant_combo("audio", self._current_audio_codec())
        self._refresh_profile_combo("video", self._current_video_codec())
        self._refresh_profile_combo("audio", self._current_audio_codec())
        self._update_two_pass_visibility()
        self._refresh_container_options()
        self._evaluate_and_render()
        self._update_size_estimate()

    def _relayout_cards(self):
        """Muestra/oculta las secciones (acordeones de Video/Audio/Transformación/Marca de
        agua) según el modo activo. El orden vertical es siempre el mismo (ver cards_column
        en _init_ui); aquí solo cambia qué secciones quedan visibles, no su posición."""
        if not hasattr(self, "cards_column") or not hasattr(self, "frame_container") or not hasattr(self, "frame_size"):
            return

        stream_mode = self._current_stream_mode()
        has_transform = getattr(self, "section_transform", None) is not None
        has_watermark = getattr(self, "section_watermark", None) is not None

        if stream_mode == "audio_only":
            self.section_video.setVisible(False)
            self.section_audio.setVisible(True)
            if has_transform:
                self.section_transform.setVisible(False)
            if has_watermark:
                self.section_watermark.setVisible(False)
        elif stream_mode == "video_only":
            self.section_audio.setVisible(False)
            self.section_video.setVisible(True)
            if has_transform:
                self.section_transform.setVisible(True)
            if has_watermark:
                self.section_watermark.setVisible(True)
        else:  # video+audio
            self.section_video.setVisible(True)
            self.section_audio.setVisible(True)
            if has_transform:
                self.section_transform.setVisible(True)
            if has_watermark:
                self.section_watermark.setVisible(True)

    def _refresh_variant_combo(self, prefix: str, codec_id):
        combo = getattr(self, f"combo_{prefix}_variant")
        lbl = getattr(self, f"lbl_{prefix}_variant")
        variants = ENCODER_VARIANTS.get(codec_id) if codec_id else None
        self._building = True
        try:
            combo.clear()
            if not variants:
                combo.setVisible(False)
                lbl.setVisible(False)
                return
            # Preferencia de plataforma (ver codec_profiles.WINDOWS_PREFERRED_ENCODER) -
            # reordena para que el mejor por defecto en ESTE sistema quede primero (índice
            # 0 = seleccionado al abrir el combo), sin dejar de exponer el resto.
            variants = ordered_encoder_variants(codec_id, variants)
            for encoder, label in variants:
                combo.addItem(label, encoder)
            combo.setVisible(True)
            lbl.setVisible(True)
        finally:
            self._building = False

    def _on_variant_changed(self, prefix: str):
        if self._building:
            return
        self._last_profile_codec[prefix] = None
        self._refresh_profile_combo(prefix, getattr(self, f"combo_{prefix}_codec").currentData())
        if prefix == "video":
            self._update_two_pass_visibility()
        self._evaluate_and_render()
        self._update_size_estimate()

    def _effective_encoder(self, prefix: str, codec_id):
        if not codec_id:
            return None
        variant_combo = getattr(self, f"combo_{prefix}_variant")
        if variant_combo.isVisible() and variant_combo.currentData():
            return variant_combo.currentData()
            
        if prefix == "video" and self._force_cpu_engine:
            from core.utils.recode_guard import _load_matrix
            matrix = _load_matrix()
            entry = matrix.get("codecs", {}).get(codec_id)
            return entry.get("encoder") if entry else resolve_encoder(codec_id)
            
        return resolve_encoder(codec_id)

    def _on_profile_changed(self, prefix: str):
        if self._building:
            return
        profile = getattr(self, f"combo_{prefix}_profile").currentData()
        custom_type = profile.get("custom") if profile else None
        
        custom_container = getattr(self, f"widget_{prefix}_custom")
        bitrate_spin = getattr(self, f"spin_{prefix}_bitrate")
        cq_spin = getattr(self, f"spin_{prefix}_cq")
        lbl_custom = getattr(self, f"lbl_{prefix}_custom")
        widget_gif_custom = getattr(self, "widget_video_gif_custom", None)

        is_gif_custom = (prefix == "video" and custom_type == "gif")
        custom_container.setVisible(bool(custom_type))

        if is_gif_custom:
            lbl_custom.setVisible(False)
            bitrate_spin.setVisible(False)
            cq_spin.setVisible(False)
            if widget_gif_custom:
                widget_gif_custom.setVisible(True)
        elif custom_type == "cq":
            lbl_custom.setVisible(True)
            lbl_custom.setText(self.tr("Nivel de calidad (CRF/CQ):"))
            bitrate_spin.setVisible(False)
            cq_spin.setVisible(True)
            if widget_gif_custom:
                widget_gif_custom.setVisible(False)
        elif custom_type in ("vbr", "cbr", "audio_bitrate"):
            lbl_custom.setVisible(True)
            lbl_custom.setText(self.tr("Bitrate objetivo:"))
            bitrate_spin.setVisible(True)
            cq_spin.setVisible(False)
            if widget_gif_custom:
                widget_gif_custom.setVisible(False)
        else:
            if widget_gif_custom:
                widget_gif_custom.setVisible(False)

        if prefix == "video":
            self._update_two_pass_visibility()
        self._update_size_estimate()

    def _update_two_pass_visibility(self):
        if not hasattr(self, "widget_video_passes"):
            return
        video_codec = self._current_video_codec()
        encoder = self._effective_encoder("video", video_codec)
        profile = self.combo_video_profile.currentData()

        show = encoder_is_two_pass_capable(encoder)
        can_use_2pass = supports_two_pass(encoder, profile)
        
        self.widget_video_passes.setVisible(show)
        self.rb_video_pass2.setEnabled(can_use_2pass)
        self.rb_video_pass2.setToolTip(
            self.tr("2 pasadas: más precisión de bitrate objetivo, tarda el doble.") if can_use_2pass
            else self.tr("Solo disponible con un perfil de bitrate objetivo (ej. 'Bitrate Personalizado'); no aplica a calidad constante (CRF/CQ).")
        )
        if not can_use_2pass:
            self.rb_video_pass1.setChecked(True)

    def _effective_args(self, prefix: str) -> list[str] | None:
        codec_id = self._current_video_codec() if prefix == "video" else self._current_audio_codec()
        if not codec_id:
            return None
        profile = getattr(self, f"combo_{prefix}_profile").currentData()
        if not profile:
            return None
            
        custom_type = profile.get("custom")
        args = []
        if custom_type:
            encoder = self._effective_encoder(prefix, codec_id)
            if custom_type == "gif":
                from core.tabs.video_tools.codec_profiles import build_custom_gif_args
                dither = self.combo_video_gif_dither.currentData() if hasattr(self, "combo_video_gif_dither") else "floyd_steinberg"
                stats = self.combo_video_gif_stats.currentData() if hasattr(self, "combo_video_gif_stats") else "full"
                colors = self.combo_video_gif_colors.currentData() if hasattr(self, "combo_video_gif_colors") else 256
                fps = self.combo_video_gif_fps.currentData() if hasattr(self, "combo_video_gif_fps") else None
                args = build_custom_gif_args(dither=dither or "floyd_steinberg", stats_mode=stats or "full", max_colors=colors or 256, fps=fps)
            elif custom_type == "cq":
                from core.tabs.video_tools.codec_profiles import build_custom_quality_args
                cq_val = getattr(self, f"spin_{prefix}_cq").value()
                args = build_custom_quality_args(encoder, cq_val)
            elif custom_type == "audio_bitrate":
                from core.tabs.video_tools.codec_profiles import build_custom_audio_bitrate_args
                bitrate = getattr(self, f"spin_{prefix}_bitrate").value()
                args = build_custom_audio_bitrate_args(encoder, bitrate)
            else:
                from core.tabs.video_tools.codec_profiles import build_custom_bitrate_args
                bitrate = getattr(self, f"spin_{prefix}_bitrate").value()
                args = build_custom_bitrate_args(encoder, custom_type, bitrate)
        else:
            args = list(profile["args"])
            
        if prefix == "audio":
            if hasattr(self, "combo_audio_channels"):
                channels = self.combo_audio_channels.currentData()
                if channels:
                    args.extend(["-ac", channels])
            if hasattr(self, "combo_audio_samplerate"):
                sr = self.combo_audio_samplerate.currentData()
                if sr:
                    args.extend(["-ar", sr])
            if hasattr(self, "chk_audio_normalize") and self.chk_audio_normalize.isChecked() and self.chk_audio_normalize.isEnabled():
                af_filter = self._build_audio_normalization_filter()
                if af_filter:
                    args.extend(["-af", af_filter])
                
        return args

    # ─── Datos del archivo fuente (cola de medios) ──────────────

    def set_source_media(self, meta: dict, filepath: str):
        self._source_meta = meta or None
        self._source_filepath = filepath
        self._update_source_info_label()
        self._update_source_aspect_label()
        self._evaluate_and_render()
        self._update_size_estimate()

    def _update_source_info_label(self):
        meta = self._source_meta
        if not meta:
            self.lbl_source_info.setText(self.tr("Selecciona un archivo en la cola para estimar el peso."))
            return
        dur = meta.get("duración", "-")
        vcod = meta.get("video_codec", "-")
        acod = meta.get("audio_codec", "-")
        self.lbl_source_info.setText(
            self.tr("Archivo de origen: duración {0} | video {1} | audio {2}").format(dur, vcod, acod)
        )

    def _source_codec(self, prefix: str):
        if not self._source_meta:
            return None
        key = "video_codec" if prefix == "video" else "audio_codec"
        return source_codec_id(self._source_meta.get(key))

    # ─── Transformación de video (CFR / Resolución / Aspecto) ───

    def _source_wh(self) -> tuple[int, int] | None:
        """Ancho/alto reales del archivo fuente, parseados de meta['resolución'] ('WxH')."""
        if not self._source_meta:
            return None
        raw = self._source_meta.get("resolución", "-")
        try:
            w_str, h_str = raw.lower().split("x")
            w, h = int(w_str), int(h_str)
            if w > 0 and h > 0:
                return w, h
        except (ValueError, AttributeError):
            pass
        return None

    def _update_source_aspect_label(self):
        if not hasattr(self, "lbl_source_aspect"):
            return
        wh = self._source_wh()
        if not wh:
            self.lbl_source_aspect.setText(self.tr("Fuente: -"))
            return
        w, h = wh
        divisor = math.gcd(w, h) or 1
        self.lbl_source_aspect.setText(
            self.tr("Fuente: {0}×{1} ({2}:{3})").format(w, h, w // divisor, h // divisor)
        )

    def _on_cfr_toggled(self, checked: bool):
        self.combo_cfr_fps.setEnabled(checked)
        self._update_size_estimate()

    def _on_resolution_changed(self, *_args):
        if self._building:
            return
        is_custom = self.combo_resolution.currentData() == "custom"
        self.widget_custom_resolution.setVisible(is_custom)
        self._relayout_cards()
        if is_custom:
            self._update_source_aspect_label()
            self._update_fit_mode_enabled()
        self._update_size_estimate()

    def _round_to_even(self, value: int) -> int:
        return value if value % 2 == 0 else value + 1

    def _current_dimension_alignment(self) -> dict:
        """Requisito real de paridad ancho/alto para el códec de video elegido (ver
        core.utils.recode_guard.get_dimension_alignment, generado empíricamente contra el
        encoder — no todo códec 4:2:2/4:4:4 se comporta igual, ver notas del matrix)."""
        return get_dimension_alignment(self._current_video_codec())

    def _on_custom_dim_changed(self, which: str):
        if self._building:
            return
        alignment = self._current_dimension_alignment()

        spin = self.spin_custom_width if which == "width" else self.spin_custom_height
        needs_even = alignment["width_even_required" if which == "width" else "height_even_required"]
        if needs_even:
            rounded = self._round_to_even(spin.value())
            if rounded != spin.value():
                self._building = True
                try:
                    spin.setValue(rounded)
                finally:
                    self._building = False

        if self.chk_keep_aspect.isChecked():
            wh = self._source_wh()
            if wh:
                src_w, src_h = wh
                self._building = True
                try:
                    if which == "width":
                        new_h = round(self.spin_custom_width.value() * src_h / src_w)
                        if alignment["height_even_required"]:
                            new_h = self._round_to_even(new_h)
                        self.spin_custom_height.setValue(max(2, new_h))
                    else:
                        new_w = round(self.spin_custom_height.value() * src_w / src_h)
                        if alignment["width_even_required"]:
                            new_w = self._round_to_even(new_w)
                        self.spin_custom_width.setValue(max(2, new_w))
                finally:
                    self._building = False

        self._update_fit_mode_enabled()
        self._update_size_estimate()

        if self._crop_active:
            self.crop_dimensions_changed.emit(self.spin_custom_width.value(), self.spin_custom_height.value())

    def is_crop_active(self) -> bool:
        """True cuando el recorte interactivo debería estar visible en la vista previa:
        resolución personalizada + ajuste "Recortar" + aspecto no conservado. Es un estado
        derivado de la configuración del panel, no algo que se prenda/apague a mano — por
        eso se re-evalúa automáticamente en cada cambio relevante (ver _update_fit_mode_enabled)
        y también hay que volver a consultarlo al cambiar de archivo previsualizado."""
        return self._crop_active

    def get_crop_target_fraction(self) -> tuple[float | None, float | None]:
        """(fw, fh) — Ancho/Alto elegidos como fracción de la resolución real de la fuente
        previsualizada. None si todavía no hay metadata del archivo fuente."""
        return self.pixels_to_crop_fraction(self.spin_custom_width.value(), self.spin_custom_height.value())

    def pixels_to_crop_fraction(self, width_px: int, height_px: int) -> tuple[float | None, float | None]:
        src_wh = self._source_wh()
        if not src_wh:
            return None, None
        src_w, src_h = src_wh
        return min(width_px / src_w, 1.0), min(height_px / src_h, 1.0)

    def sync_dimensions_from_crop(self, crop_fraction: tuple[float, float, float, float]):
        """Refleja en vivo, en los campos Ancho/Alto, el tamaño del recorte que se está
        arrastrando en la vista previa — dirección opuesta a crop_dimensions_changed (que
        sincroniza cuando se tipea Ancho/Alto a mano). A propósito NO se suprime con
        self._building: dejar que pase por _on_custom_dim_changed normalmente hace que el
        redondeo a par se aplique en vivo mientras se arrastra (el rectángulo "encastra" al
        valor par más cercano), sin loop infinito porque resize_keep_center() en el overlay
        no vuelve a emitir 'changed' (solo lo hace un arrastre real del usuario)."""
        src_wh = self._source_wh()
        if not src_wh or not hasattr(self, "spin_custom_width"):
            return
        src_w, src_h = src_wh
        _, _, fw, fh = crop_fraction
        self.spin_custom_width.setValue(max(2, round(fw * src_w)))
        self.spin_custom_height.setValue(max(2, round(fh * src_h)))

    def show_apply_to_all_checkbox(self):
        self.chk_apply_crop_to_all.setVisible(True)

    def hide_apply_to_all_checkbox(self):
        self.chk_apply_crop_to_all.setChecked(False)
        self.chk_apply_crop_to_all.setVisible(False)

    def _revalidate_custom_dimensions(self):
        """Vuelve a aplicar el redondeo de paridad a los campos Ancho/Alto ya cargados —
        se usa cuando cambia el códec de video, porque el requisito de paridad puede cambiar
        (ej. veniás de ProRes sin restricción y pasaste a H.264, que sí la exige)."""
        if not hasattr(self, "spin_custom_width"):
            return
        alignment = self._current_dimension_alignment()
        self._building = True
        try:
            if alignment["width_even_required"]:
                self.spin_custom_width.setValue(self._round_to_even(self.spin_custom_width.value()))
            if alignment["height_even_required"]:
                self.spin_custom_height.setValue(self._round_to_even(self.spin_custom_height.value()))
        finally:
            self._building = False
        self._update_fit_mode_enabled()

    def _on_keep_aspect_toggled(self, checked: bool):
        if checked:
            # Al reactivar el vínculo, recalcular el alto a partir del ancho actual para que
            # los dos campos vuelvan a quedar coherentes de inmediato.
            self._on_custom_dim_changed("width")
        self._update_fit_mode_enabled()

    def _update_fit_mode_enabled(self):
        """El selector Crop/Ajustar/Deformar solo importa cuando el aspecto conservado está
        desactivado. Se habilita apenas se desmarca "Conservar relación de aspecto", sin
        esperar a que además cambie algún valor de Ancho/Alto — al desactivarlo, W×H todavía
        coinciden con el aspecto real (eso es justamente lo que mantenía activado), así que
        exigir además un "mismatch" actual dejaba los radios apagados hasta el primer cambio,
        que se sentía como que no respondía."""
        enabled = not self.chk_keep_aspect.isChecked()
        for rb in (self.rb_fit_deformar, self.rb_fit_ajustar, self.rb_fit_crop):
            rb.setEnabled(enabled)

        # El recorte interactivo no es una casilla aparte: se activa/desactiva solo,
        # siguiendo exactamente la misma condición que habilita el selector Crop/Ajustar/
        # Deformar, restringida además al ajuste "Recortar" en sí.
        crop_available = enabled and self._current_fit_mode() == "crop"
        if crop_available != self._crop_active:
            self._crop_active = crop_available
            self.crop_edit_toggled.emit(crop_available)
            if not crop_available and hasattr(self, "chk_apply_crop_to_all"):
                self.hide_apply_to_all_checkbox()

    def _current_cfr_fps(self) -> float | None:
        """FPS elegido para CFR, parseado directo del texto mostrado en el combo (editable): sirve
        igual para un valor predefinido ("30 fps") que para uno escrito a mano ("48"), sin
        depender de si currentIndex/currentData quedaron sincronizados con lo que se ve en pantalla."""
        if not hasattr(self, "combo_cfr_fps"):
            return None
        text = self.combo_cfr_fps.currentText().strip().lower().replace("fps", "").replace(",", ".").strip()
        try:
            value = float(text)
            return value if value > 0 else None
        except ValueError:
            return None

    def _current_fit_mode(self) -> str:
        if self.rb_fit_crop.isChecked():
            return "crop"
        if self.rb_fit_deformar.isChecked():
            return "deformar"
        return "ajustar"

    def _build_vf_expression(self, crop_fraction_override: tuple[float, float, float, float] | None = None) -> str | None:
        preset = self.combo_resolution.currentData() if hasattr(self, "combo_resolution") else "original"
        if not preset or preset == "original":
            return None

        if preset == "custom":
            w = self.spin_custom_width.value()
            h = self.spin_custom_height.value()
            if self.chk_keep_aspect.isChecked():
                return f"scale={w}:{h}"
            fit_mode = self._current_fit_mode()
            if fit_mode == "deformar":
                return f"scale={w}:{h}"
            if fit_mode == "crop":
                if crop_fraction_override is not None:
                    return self._build_vf_expression_with_crop(crop_fraction_override, w, h)
                return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
            return f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"

        target = next((t for key, _label, t in _RESOLUTION_PRESETS if key == preset), None)
        if not target:
            return None
        return f"scale='if(gt(iw,ih),{target},-2)':'if(gt(iw,ih),-2,{target})'"

    def _build_vf_expression_with_crop(self, crop_fraction: tuple[float, float, float, float],
                                         target_w: int, target_h: int) -> str:
        """Arma crop=cw:ch:cx:cy,scale=target_w:target_h a partir de la fracción elegida
        interactivamente en la vista previa (MediaTrimPlayerWidget.get_crop_rect).

        A propósito usa las variables de ffmpeg iw/ih (ancho/alto reales del archivo que se
        está codificando EN ESE MOMENTO) en vez de precalcular píxeles contra la resolución
        de un solo archivo: con "Aplicar a todos los medios" el mismo filtro se aplica a
        cada archivo de la cola, y si tuvieran resoluciones distintas entre sí, unos píxeles
        fijos calculados sobre el archivo previsualizado quedarían mal en cualquier otro. Con
        iw/ih, ffmpeg resuelve el recorte correcto para cada archivo por su cuenta.

        El redondeo a par (get_dimension_alignment) se expresa con trunc(.../2)*2 dentro de
        la propia fórmula de ffmpeg, por la misma razón: tiene que evaluarse por archivo. A
        propósito NO se agrega ':exact=1' al filtro crop — verificado empíricamente que sin
        él, un offset impar se autocorrige en silencio a lo sumo 1px sin artefactos; con
        exact=1 se respeta el offset pero puede introducir corrimiento de croma."""
        fx, fy, fw, fh = crop_fraction
        alignment = self._current_dimension_alignment()

        def axis(expr: str, even_required: bool) -> str:
            return f"trunc(({expr})/2)*2" if even_required else f"trunc({expr})"

        cw = axis(f"iw*{fw}", alignment["width_even_required"])
        ch = axis(f"ih*{fh}", alignment["height_even_required"])
        cx = axis(f"iw*{fx}", alignment["width_even_required"])
        cy = axis(f"ih*{fy}", alignment["height_even_required"])
        return f"crop={cw}:{ch}:{cx}:{cy},scale={target_w}:{target_h}"

    def _transform_args(self, video_args: list[str],
                         crop_fraction_override: tuple[float, float, float, float] | None = None) -> list[str]:
        """Fusiona el filtro de resolución/aspecto (si hay) y el -r de CFR (si está activo) con
        los args que ya trae el perfil de códec — reusando el -vf existente en vez de agregar uno
        segundo, para no romper perfiles que ya arman su propio filtro (ej. paleta de GIF)."""
        args = list(video_args) if video_args else []

        vf_expr = self._build_vf_expression(crop_fraction_override)
        text_watermark_expr = self._build_text_watermark_filter()
        if text_watermark_expr:
            vf_expr = f"{vf_expr},{text_watermark_expr}" if vf_expr else text_watermark_expr
        if vf_expr:
            if "-vf" in args:
                idx = args.index("-vf") + 1
                args[idx] = f"{args[idx]},{vf_expr}"
            else:
                args += ["-vf", vf_expr]

        if hasattr(self, "chk_cfr") and self.chk_cfr.isChecked():
            fps = self._current_cfr_fps()
            if fps:
                args += ["-r", f"{fps:g}"]

        return args

    def _guard_codec(self, prefix: str):
        stream_mode = self._current_stream_mode()
        if prefix == "video" and stream_mode == "audio_only":
            return None
        if prefix == "audio" and stream_mode == "video_only":
            return None

        frame = getattr(self, f"frame_{prefix}", None)
        if frame and not frame.isEnabled():
            return None
            
        is_copy = getattr(self, f"rb_{prefix}_copy").isChecked()
        if is_copy:
            return self._source_codec(prefix)
        return getattr(self, f"combo_{prefix}_codec").currentData()

    def _update_size_estimate(self, *_args):
        if self._building or not hasattr(self, "lbl_size_estimate"):
            return

        if not self._source_meta:
            self.lbl_size_estimate.setText("")
            return

        duration_sec = parse_duration_to_seconds(self._source_meta.get("duración", "0"))
        if duration_sec <= 0:
            self.lbl_size_estimate.setText(self.tr("Duración del archivo todavía no disponible."))
            return

        stream_mode = self._current_stream_mode()

        def stream_kbps(prefix, meta_key, arg_flag):
            if getattr(self, f"rb_{prefix}_copy").isChecked():
                return parse_kbps_from_label(self._source_meta.get(meta_key))
            args = self._effective_args(prefix)
            return extract_bitrate_kbps(args, arg_flag) if args else None

        video_kbps = stream_kbps("video", "bitrate_video", "-b:v") if stream_mode != "audio_only" else None
        audio_kbps = stream_kbps("audio", "bitrate_audio", "-b:a") if stream_mode != "video_only" else None
        size_mb = estimate_size_mb(video_kbps, audio_kbps, duration_sec)

        if size_mb is None:
            self.lbl_size_estimate.setText(self.tr(
                "No se puede estimar: ningún stream tiene un bitrate fijo conocido (perfiles de "
                "calidad constante como CRF/CQ no tienen un tamaño predecible de antemano)."
            ))
            return

        parts = []
        if stream_mode != "audio_only":
            parts.append(self.tr("video: {0:.0f} kbps").format(video_kbps) if video_kbps is not None
                          else self.tr("video: sin bitrate fijo, no incluido"))
        if stream_mode != "video_only":
            parts.append(self.tr("audio: {0:.0f} kbps").format(audio_kbps) if audio_kbps is not None
                          else self.tr("audio: sin bitrate fijo, no incluido"))

        self.lbl_size_estimate.setText(
            self.tr("~ {0:.1f} MB").format(size_mb) + "  (" + ", ".join(parts) + ")"
        )

    def _refresh_profile_combo(self, prefix: str, codec_id):
        if codec_id == self._last_profile_codec[prefix]:
            return
        self._last_profile_codec[prefix] = codec_id

        combo = getattr(self, f"combo_{prefix}_profile")
        lbl = getattr(self, f"lbl_{prefix}_profile")
        self._building = True
        try:
            combo.clear()
            if not codec_id:
                combo.setEnabled(False)
                lbl.setVisible(False)
                combo.setVisible(False)
                return
            encoder = self._effective_encoder(prefix, codec_id)
            profiles = get_profiles(prefix, encoder)
            for p in profiles:
                combo.addItem(p["label"], p)
            combo.setEnabled(bool(profiles))
            lbl.setVisible(True)
            combo.setVisible(True)
        finally:
            self._building = False
        self._on_profile_changed(prefix)

    def _on_container_changed(self, *_args):
        if self._building:
            return
        self._evaluate_and_render()

    def _toggle_engine_mode(self):
        self._force_cpu_engine = not self._force_cpu_engine
        self._on_video_codec_changed()

    def _update_engine_label(self):
        codec_id = self._current_video_codec()
        if not codec_id:
            self.lbl_video_engine.setVisible(False)
            return
        
        hw_info = detect_hardware()
        status = hw_info.get("codec_status", {}).get(codec_id)
        
        has_hw = bool(status and status.get("status") == "full")
        is_cpu_forced = self._force_cpu_engine

        if is_cpu_forced or not has_hw:
            self.lbl_video_engine.setText(self.tr("CPU"))
            self.lbl_video_engine.setStyleSheet("""
                QPushButton {
                    background-color: rgba(255, 255, 255, 0.08);
                    color: #aaaaaa;
                    border: 1px solid rgba(255, 255, 255, 0.15);
                    border-radius: 4px;
                    padding: 2px 8px;
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: rgba(255, 255, 255, 0.15); }
            """)
            if has_hw:
                self.lbl_video_engine.setToolTip(self.tr("Clic para usar aceleración por GPU"))
            else:
                self.lbl_video_engine.setToolTip("")
        else:
            self.lbl_video_engine.setText(self.tr("GPU Acelerado"))
            self.lbl_video_engine.setStyleSheet("""
                QPushButton {
                    background-color: rgba(185, 230, 64, 0.15);
                    color: #B9E640;
                    border: 1px solid rgba(185, 230, 64, 0.35);
                    border-radius: 4px;
                    padding: 2px 8px;
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: rgba(185, 230, 64, 0.25); }
            """)
            self.lbl_video_engine.setToolTip(self.tr("Clic para usar codificación por CPU"))

        self.lbl_video_engine.setVisible(True)
        self.lbl_video_engine.setEnabled(has_hw)

    def _refresh_container_options(self):
        self._building = True
        try:
            v_codec = self._guard_codec("video")
            a_codec = self._guard_codec("audio")
            codec_ids = [c for c in (v_codec, a_codec) if c]
            containers = get_compatible_containers(codec_ids) if codec_ids else []
            current = self.combo_container.currentData()
            self.combo_container.clear()
            for cont_id in containers:
                label = CONTAINER_LABELS.get(cont_id, cont_id.upper())
                self.combo_container.addItem(label, cont_id)

            stream_mode = self._current_stream_mode()
            is_audio_only = (stream_mode == "audio_only")
            primary_codec = a_codec if is_audio_only else v_codec
            preferred = _PREFERRED_CONTAINER_BY_CODEC.get(primary_codec)

            # Auto-selección inteligente de contenedor:
            # 1. En modo Solo Audio: auto-seleccionar siempre de inmediato el contenedor nativo del códec de audio
            if is_audio_only and preferred in containers:
                target = preferred
            # 2. En video: Códecs con contenedor obligatorio / estándar de la industria (ProRes/DNxHD/etc -> MOV, GIF -> GIF):
            elif primary_codec in ("prores", "dnxhd", "dnxhr", "cfhd", "qtrle", "hap", "gif", "apng") and preferred in containers:
                target = preferred
            # 3. Si el contenedor actual sigue siendo compatible y válido en la lista, conservarlo
            elif current and self.combo_container.findData(current) >= 0:
                target = current
            # 4. Si el contenedor anterior no es compatible, usar el preferido del códec si está en la lista
            elif preferred and preferred in containers:
                target = preferred
            # 5. Homónimo directo (ej. webp, flac, mp3, wav)
            elif v_codec and v_codec in containers:
                target = v_codec
            elif a_codec and a_codec in containers:
                target = a_codec
            else:
                target = None

            if target:
                idx = self.combo_container.findData(target)
                if idx >= 0:
                    self.combo_container.setCurrentIndex(idx)
        finally:
            self._building = False

    # ─── Evaluacion contra el colchon ───────────────────────────

    def _clear_messages(self):
        while self.messages_layout.count():
            child = self.messages_layout.takeAt(0)
            if child.widget():
                child.widget().hide()
                child.widget().deleteLater()

    def _translate_issue_message(self, text: str) -> str:
        if not text:
            return ""
        for ctx in ("AdvancedRecodePanel", "HardwareDetector", "RecodeMessages", "recode_guard", "watermark_builder", ""):
            trans = QCoreApplication.translate(ctx, text)
            if trans and trans != text:
                return trans
        return text

    def _add_message(self, severity: str, text: str, compact: bool = False):
        color = get_theme_token(_SEVERITY_TOKENS[severity], "#aaaaaa")
        raw_sev = _SEVERITY_LABELS.get(severity, severity)
        sev_label = self._translate_issue_message(raw_sev)
        label_text = f"● {text}" if compact else f"● {sev_label}: {text}"
        lbl = QLabel(label_text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {color}; font-size: {'13px' if compact else '12px'}; font-weight: {'bold' if compact else 'normal'};")
        self.messages_layout.addWidget(lbl)

    def _refresh_audio_channel_options(self, container_id: str | None):
        """Muestra/oculta y habilita/deshabilita las opciones del combo 'Canales' según lo
        que el codec de audio elegido soporta en el contenedor elegido (ver
        recode_guard.get_channel_support / ffmpeg_codec_matrix.json)."""
        if not hasattr(self, "combo_audio_channels"):
            return
        combo = self.combo_audio_channels
        audio_codec = self._current_audio_codec()
        support = get_channel_support(audio_codec, container_id) if (audio_codec and container_id) else {}

        self._building = True
        try:
            model = combo.model()
            view = combo.view()
            current_data = combo.currentData()
            reset_needed = False
            for i in range(combo.count()):
                data = combo.itemData(i)
                if not data:
                    continue  # "Igual al original": siempre disponible
                info = support.get(data)
                enabled = info["supported"] if info else True
                item = model.item(i)
                item.setEnabled(enabled)
                item.setToolTip((info or {}).get("reason") or "" if not enabled else "")
                view.setRowHidden(i, not enabled)
                if not enabled and data == current_data:
                    reset_needed = True
            if reset_needed:
                combo.setCurrentIndex(0)
        finally:
            self._building = False

    def _evaluate_and_render(self):
        self._clear_messages()
        container_id = self.combo_container.currentData()
        self._refresh_audio_channel_options(container_id)

        if not container_id:
            self._add_message("unverified", self.tr("No hay ningún contenedor compatible con la combinación de codecs elegida."))
            self._last_valid = False
            self._invalid_reason = self.tr("Sin contenedor compatible")
            self.validity_changed.emit(False)
            return

        result = evaluate_recode(self._guard_codec("video"), self._guard_codec("audio"), container_id)

        if not result["issues"]:
            self._add_message("ok", self.tr("Configuración compatible y lista para procesar."), compact=True)
        else:
            for issue in result["issues"]:
                if issue["check"] == "playback_risk":
                    message = self._format_playback_risk_message(issue["risk"])
                else:
                    message = self._translate_issue_message(issue["message"])
                    if "message_args" in issue:
                        for i, arg in enumerate(issue["message_args"], 1):
                            message = message.replace(f"%{i}", str(arg))
                
                self._add_message(issue["severity"], message)

        self._last_valid = result["verdict"] != "blocked"
        self._invalid_reason = self.tr("Combinación no compatible") if not self._last_valid else ""

        watermark_issue = self._check_watermark_issues()
        if watermark_issue:
            wm_msg = self._translate_issue_message(watermark_issue["message"])
            self._add_message(watermark_issue["severity"], wm_msg)
            if watermark_issue["severity"] == "blocked":
                self._last_valid = False
                self._invalid_reason = wm_msg

        self.validity_changed.emit(self._last_valid)

    def _format_playback_risk_message(self, risk: dict) -> str:
        """Arma el texto final del warning de "riesgo de reproducción" (ver
        recode_guard._check_playback_risk, que solo devuelve datos estructurados).
        Vive aquí y no en recode_guard.py porque necesita self.tr() para ser
        traducible — ese módulo es lógica pura, no un QObject.

        level="none"/"planned" es un caso distinto de los demás: ahí ffmpeg logró
        el mux pero el estándar del contenedor directamente NO contempla esta
        combinación (no es solo "no estándar" o "parcial"), así que se avisa con
        una frase separada en vez de reusar la plantilla genérica con una
        descripción de nivel que diría, de forma confusa, "no es estándar (sin
        soporte)"."""
        level = risk.get("level")

        if level in ("none", "planned"):
            msg = self.tr(
                "ffmpeg permite generar este archivo, pero el estándar del contenedor "
                "no contempla esta combinación de codec"
            )
        else:
            level_descriptions = {
                "partial": self.tr("soporte restringido a un perfil, versión o subformato específico"),
                "indirect": self.tr("soporte indirecto a través de un mecanismo externo, no nativo del contenedor"),
                "requires_external": self.tr("requiere un componente o codec adicional instalado aparte"),
                "private": self.tr("implementación privada o no estandarizada del contenedor"),
                "nonstandard": self.tr("reconocido por algunos reproductores/editores pero no forma parte del estándar"),
                "problematic": self.tr("técnicamente posible pero problemático o poco fiable en la práctica"),
                "beta": self.tr("soporte en fase beta, puede ser inestable"),
            }
            desc = level_descriptions.get(level, level)
            msg = self.tr("ffmpeg acepta este mux, pero no es un uso estándar del contenedor ({0})").format(desc)

        extra = None
        if risk.get("via"):
            via_labels = {
                "vcm": self.tr("Video Compression Manager (VCM)"),
                "acm": self.tr("Audio Compression Manager (ACM)"),
            }
            extra = self.tr("vía {0}").format(via_labels.get(risk["via"], risk["via"]))
        elif risk.get("requires"):
            extra = self.tr("requiere {0}").format(risk["requires"])
        elif risk.get("note"):
            extra = risk["note"]  # hecho técnico (nombre de perfil/formato), no se traduce a propósito

        if extra:
            msg += f" — {extra}"
        msg += ". " + self.tr("Podría no reproducirse en todos los reproductores/dispositivos.")
        return msg

    # ─── API publica ─────────────────────────────────────────────

    def is_valid(self) -> bool:
        return self._last_valid

    def get_status(self) -> tuple[bool, str]:
        if not self._last_valid:
            return False, self._invalid_reason or self.tr("Combinación no compatible")
        return True, self.tr("Iniciar Recodificación")

    def get_settings(self, crop_fraction_override: tuple[float, float, float, float] | None = None) -> dict:
        stream_mode = self._current_stream_mode()
        v_codec = self._current_video_codec()
        is_gif = (v_codec == "gif" and self.rb_video_recode.isChecked())
        video_recode_active = (stream_mode != "audio_only" and self.rb_video_recode.isChecked())
        video_args = self._effective_args("video") if video_recode_active else None
        if video_args is not None and video_recode_active:
            # Fusiona -vf (resolución/aspecto) y -r (CFR) con los args del perfil de códec ANTES
            # de dividir en pasadas, para que ambas pasadas de un 2-pass usen el mismo filtro.
            video_args = self._transform_args(video_args, crop_fraction_override)
        passes = 2 if (video_args and self.rb_video_pass2.isChecked() and self.rb_video_pass2.isEnabled() and stream_mode != "audio_only" and not is_gif) else 1

        resolution_preset = self.combo_resolution.currentData() if hasattr(self, "combo_resolution") else "original"
        watermark_image_path, watermark_overlay_filter = (
            self._build_image_watermark_settings() if video_recode_active else (None, None)
        )
        settings = {
            "stream_mode": stream_mode,
            "video_mode": "copy" if self.rb_video_copy.isChecked() else "recode",
            "video_codec": v_codec,
            "video_args": video_args,
            "video_passes": passes,
            "audio_mode": "copy" if self.rb_audio_copy.isChecked() else "recode",
            "audio_codec": self._current_audio_codec() if not is_gif else None,
            "audio_args": self._effective_args("audio") if (stream_mode != "video_only" and self.rb_audio_recode.isChecked() and not is_gif) else None,
            "container": self.combo_container.currentData(),
            "resolution_preset": resolution_preset,
            "custom_width": self.spin_custom_width.value() if (hasattr(self, "spin_custom_width") and resolution_preset == "custom") else None,
            "custom_height": self.spin_custom_height.value() if (hasattr(self, "spin_custom_height") and resolution_preset == "custom") else None,
            "keep_aspect_ratio": self.chk_keep_aspect.isChecked() if hasattr(self, "chk_keep_aspect") else True,
            "fit_mode": self._current_fit_mode() if hasattr(self, "rb_fit_ajustar") else "ajustar",
            "force_cfr": self.chk_cfr.isChecked() if hasattr(self, "chk_cfr") else False,
            "target_fps": self._current_cfr_fps() if (hasattr(self, "chk_cfr") and self.chk_cfr.isChecked()) else None,
            "crop_apply_to_all": bool(
                hasattr(self, "chk_apply_crop_to_all")
                and self.chk_apply_crop_to_all.isVisible()
                and self.chk_apply_crop_to_all.isChecked()
            ),
            "watermark_image_path": watermark_image_path,
            "watermark_overlay_filter": watermark_overlay_filter,
            "audio_normalize": bool(hasattr(self, "chk_audio_normalize") and self.chk_audio_normalize.isChecked() and self.rb_audio_recode.isChecked() and stream_mode != "video_only" and not is_gif),
            "audio_normalize_method": self.combo_audio_norm_method.currentData() if hasattr(self, "combo_audio_norm_method") else "loudnorm",
            "audio_filter": self._build_audio_normalization_filter() if (hasattr(self, "chk_audio_normalize") and self.chk_audio_normalize.isChecked() and self.rb_audio_recode.isChecked() and stream_mode != "video_only" and not is_gif) else None,
        }
        if passes == 2:
            settings["video_args_pass1"] = build_pass_args(video_args, 1)
            settings["video_args_pass2"] = build_pass_args(video_args, 2)
        return settings
