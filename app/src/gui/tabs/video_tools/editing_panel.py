# src/gui/tabs/video_tools/editing_panel.py
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QLabel,
    QComboBox,
    QPushButton,
    QButtonGroup,
    QStackedWidget,
    QSizePolicy,
    QScrollArea,
)
from PySide6.QtCore import Signal, Qt, QT_TRANSLATE_NOOP

from gui.styles import get_theme_token
from gui.widgets.mode_selector import ModeSelector
from gui.widgets.combo_box import CheckmarkComboDelegate, AutoPopupComboBox
from core.utils.recode_guard import resolve_encoder, is_stream_copy_compatible
from core.tabs.video_tools.codec_profiles import (
    get_profiles, recommend_audio_codec, build_custom_audio_bitrate_args,
    ENCODER_VARIANTS, ordered_encoder_variants, preferred_encoder,
)
from core.tabs.video_tools.size_estimator import source_codec_id

_MAX_VISIBLE_COMBO_ITEMS = 12

# Familias de códec ofrecidas en Edición: las 3 orientadas a intermedios/proxies de
# edición reconocidas en toda la industria (Premiere/Resolve/Avid/FCP) - confirmadas
# contra el matrix real de ESTE ffmpeg empaquetado, no adivinadas (ver conversación:
# CineForm en particular es la trampa típica de builds recortados que solo lo traen como
# decoder - aquí sí tiene encoder que funciona de verdad).
_EDIT_CODEC_IDS = ["prores", "dnxhd", "cfhd"]
_EDIT_CODEC_LABELS = {"prores": "Apple ProRes", "dnxhd": "Avid DNxHR", "cfhd": "GoPro CineForm"}
_EDIT_CODEC_DEFAULT_ENCODER = {"prores": "prores_ks", "dnxhd": "dnxhd", "cfhd": "cfhd"}

_RESOLUTION_LABELS = {
    "completa": QT_TRANSLATE_NOOP("EditingPanel", "Completa"),
    "mitad": QT_TRANSLATE_NOOP("EditingPanel", "Mitad"),
    "cuarto": QT_TRANSLATE_NOOP("EditingPanel", "Cuarto"),
}
_RESOLUTION_SCALES = {"completa": None, "mitad": 0.5, "cuarto": 0.25}

# Único contenedor ofrecido: .mov (id "qtff") - el matrix real confirma que es el ÚNICO
# que acepta los 3 códecs a la vez (ProRes/DNxHR/CineForm), y es además el formato que
# todas las NLE (Premiere/Resolve/Avid/FCP) esperan para media de edición/proxy - no hace
# falta exponer un selector de contenedor en esta pestaña.
_CONTAINER = "qtff"


def _encoder_for(codec_id: str) -> str:
    """Encoder por defecto para este códec, YA con la preferencia de plataforma aplicada
    cuando hay mas de una implementacion valida (ver codec_profiles.ENCODER_VARIANTS /
    WINDOWS_PREFERRED_ENCODER - ej. ProRes: prores_aw resulto ~8x mas rapido que
    prores_ks en Windows con este ffmpeg, benchmark real, ver conversación). A
    diferencia de recode_guard.resolve_encoder (que da el que el matrix uso para
    VERIFICAR, no necesariamente el mejor para el usuario), esta es la que corresponde
    ofrecer por defecto tanto en Rápido (sin UI para elegir - Rápido decide por el
    usuario) como en Manual (con combo para anular, ver _reload_manual_variant)."""
    fallback = resolve_encoder(codec_id) or _EDIT_CODEC_DEFAULT_ENCODER[codec_id]
    return preferred_encoder(codec_id, fallback)


def _quick_proxy_profile(codec_id: str, encoder: str) -> dict:
    """El perfil mas liviano/proxy de la tabla real de codec_profiles.py para este
    encoder - identificado por el flag "quick_proxy" de esa tabla (ver codec_profiles.py),
    nunca un perfil "proxy" inventado aparte: son los mismos valores que ya usa
    Manual/Avanzado. Antes se buscaba por substring del label (ej. "lb", "low"), pero eso
    se rompía si el label traducido dejaba de contener esas letras."""
    profiles = get_profiles("video", encoder)
    if not profiles:
        return {"label": "Predeterminado", "args": ["-c:v", encoder]}
    for profile in profiles:
        if profile.get("quick_proxy"):
            return profile
    return profiles[0]


def _scale_filter_args(resolution_key: str) -> list[str]:
    factor = _RESOLUTION_SCALES.get(resolution_key)
    if not factor:
        return []
    # trunc(.../2)*2 fuerza ancho/alto par - los 3 códecs de esta pestaña son 4:2:2 (o
    # 4:4:4) y varios rechazan directamente una dimension impar (ver
    # recode_guard.get_dimension_alignment) - más simple aplicarlo siempre que
    # condicionarlo por códec, no tiene costo para los que no lo exigen.
    expr_w = f"trunc(iw*{factor}/2)*2"
    expr_h = f"trunc(ih*{factor}/2)*2"
    return ["-vf", f"scale={expr_w}:{expr_h}"]


class EditingPanel(QWidget):
    """
    Pestaña "Edición": códecs intermedios de edición profesional (ProRes, DNxHD/HR, GoPro
    CineForm). No es exclusiva de proxies (por eso "Edición", no "Proxies" a secas):
    expone TODA la escala de calidad real de cada códec - desde el nivel más liviano
    (pensado para proxies de edición) hasta el de masterización/color (ProRes 4444 XQ,
    DNxHR 444, CineForm Film Scan 3+) - más un control de escala de resolución (Completa/
    Mitad/Cuarto), que es la otra mitad de lo que realmente hace liviano a un proxy (ver
    conversación: solo cambiar de códec sin bajar resolución no es lo que la mayoría
    entiende por "proxy").

    Rápido: 1 click por familia de códec (siempre a su perfil más liviano/proxy real, ver
    el flag "quick_proxy" en codec_profiles.py) + escala de resolución.
    Manual: códec + calidad completa (misma tabla que ya usa Avanzado, ver
    codec_profiles.py) + escala de resolución.

    A diferencia de Comprimir/Convertir, no hay selector de contenedor (siempre .mov, ver
    _CONTAINER) ni badge de motor/GPU: ninguno de estos 3 códecs tiene variante acelerada
    por hardware en ffmpeg (ver recode_guard._HARDWARE_TRACKED_CODECS), siempre van por
    CPU.
    """

    validity_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source_meta = None
        self._source_filepath = None
        self._init_ui()

    # ─── UI ──────────────────────────────────────────────────────

    def _init_ui(self):
        self.setObjectName("editingPanel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setObjectName("editingScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        self.setStyleSheet("""
            QWidget#editingPanel { background: transparent; }
            QScrollArea#editingScroll { background: transparent; }
            QWidget#editingContent { background: transparent; }
        """)

        content = QWidget(scroll)
        content.setObjectName("editingContent")
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

    def _build_toggle_row(self, parent, items: dict, default_key: str, on_changed, min_height: int = 40) -> tuple[QHBoxLayout, QButtonGroup, dict]:
        """Fila de botones exclusivos tipo "chip" (mismo estilo que los niveles de
        Comprimir/Rápido) - reusada tanto para elegir códec como resolución."""
        row = QHBoxLayout()
        row.setSpacing(8)
        group = QButtonGroup(parent)
        group.setExclusive(True)
        buttons = {}
        accent = get_theme_token('acento_primario', '#B9E640')
        border_color = get_theme_token('borde_sutil', '#2d2d2d')
        fondo = get_theme_token('fondo_secundario', '#121212')
        texto = get_theme_token('texto_principal', '#ffffff')
        for key, label in items.items():
            btn = QPushButton(label, parent)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(min_height)
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
            btn.clicked.connect(on_changed)
            group.addButton(btn)
            buttons[key] = btn
            row.addWidget(btn)
        buttons[default_key].setChecked(True)
        return row, group, buttons

    @staticmethod
    def _checked_key(buttons: dict, default_key: str) -> str:
        for key, btn in buttons.items():
            if btn.isChecked():
                return key
        return default_key

    # ─── Página Rápido ───────────────────────────────────────────

    def _build_quick_page(self, parent) -> QWidget:
        page = QWidget(parent)
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        lbl_codec = QLabel(self.tr("Códec (siempre a su calidad más liviana/proxy):"), page)
        lbl_codec.setObjectName("menuLabel")
        v.addWidget(lbl_codec)
        codec_row, self._quick_codec_group, self._quick_codec_buttons = self._build_toggle_row(
            page, _EDIT_CODEC_LABELS, "prores", self._on_quick_changed, min_height=56,
        )
        v.addLayout(codec_row)

        lbl_res = QLabel(self.tr("Resolución:"), page)
        lbl_res.setObjectName("menuLabel")
        v.addWidget(lbl_res)
        res_labels = {k: self.tr(v_) for k, v_ in _RESOLUTION_LABELS.items()}
        res_row, self._quick_res_group, self._quick_res_buttons = self._build_toggle_row(
            page, res_labels, "completa", self._on_quick_changed,
        )
        v.addLayout(res_row)

        hint_frame, hint_layout = self._card_frame(parent=page)
        self.lbl_quick_hint = QLabel("", hint_frame)
        self.lbl_quick_hint.setWordWrap(True)
        hint_layout.addWidget(self.lbl_quick_hint)
        v.addWidget(hint_frame)

        v.addStretch(1)
        self._refresh_quick_hint()
        return page

    def _current_quick_codec_id(self) -> str:
        return self._checked_key(self._quick_codec_buttons, "prores")

    def _on_quick_changed(self, *_args):
        self._refresh_quick_hint()

    def _refresh_quick_hint(self):
        if not hasattr(self, "lbl_quick_hint"):
            return
        codec_id = self._current_quick_codec_id()
        profile = _quick_proxy_profile(codec_id, _encoder_for(codec_id))
        res_key = self._checked_key(self._quick_res_buttons, "completa")
        res_text = {
            "completa": self.tr("resolución completa"),
            "mitad": self.tr("mitad de resolución"),
            "cuarto": self.tr("un cuarto de resolución"),
        }[res_key]
        self.lbl_quick_hint.setText(
            self.tr("Se generará como {0} en un archivo .mov, a {1}. El audio se copia tal "
                     "cual si el original entra en .mov, o se pasa a PCM sin comprimir si no.")
            .format(profile["label"], res_text)
        )

    # ─── Página Manual ───────────────────────────────────────────

    def _build_manual_page(self, parent) -> QWidget:
        page = QWidget(parent)
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        frame_codec, cv = self._card_frame(self.tr("Códec y calidad"), page)
        self.combo_manual_codec = AutoPopupComboBox(frame_codec)
        self._setup_fixed_combo(self.combo_manual_codec)
        for codec_id in _EDIT_CODEC_IDS:
            self.combo_manual_codec.addItem(_EDIT_CODEC_LABELS[codec_id], codec_id)
        self.combo_manual_codec.currentIndexChanged.connect(self._on_manual_codec_changed)
        cv.addWidget(self.combo_manual_codec)

        # Solo visible para códecs con mas de una implementacion valida en ffmpeg (hoy,
        # únicamente ProRes: ks vs aw - ver codec_profiles.ENCODER_VARIANTS). Rápido no
        # expone esto a propósito (elige la mejor por plataforma sola, ver _encoder_for) -
        # Manual sí, para el usuario que quiere el control explícito.
        self.lbl_manual_variant = QLabel(self.tr("Implementación:"), frame_codec)
        self.lbl_manual_variant.setObjectName("menuLabel")
        cv.addWidget(self.lbl_manual_variant)
        self.combo_manual_variant = AutoPopupComboBox(frame_codec)
        self._setup_fixed_combo(self.combo_manual_variant)
        self.combo_manual_variant.currentIndexChanged.connect(self._on_manual_variant_changed)
        cv.addWidget(self.combo_manual_variant)

        lbl_quality = QLabel(self.tr("Calidad:"), frame_codec)
        lbl_quality.setObjectName("menuLabel")
        cv.addWidget(lbl_quality)
        self.combo_manual_quality = AutoPopupComboBox(frame_codec)
        self._setup_fixed_combo(self.combo_manual_quality)
        cv.addWidget(self.combo_manual_quality)
        v.addWidget(frame_codec)

        frame_res, rv = self._card_frame(self.tr("Resolución"), page)
        res_labels = {k: self.tr(v_) for k, v_ in _RESOLUTION_LABELS.items()}
        res_row, self._manual_res_group, self._manual_res_buttons = self._build_toggle_row(
            page, res_labels, "completa", self._on_manual_changed,
        )
        rv.addLayout(res_row)
        v.addWidget(frame_res)

        lbl_hint = QLabel(self.tr(
            "El audio se copia tal cual cuando el original entra en .mov; si no, se "
            "recodifica a PCM sin comprimir. Estos códecs no tienen aceleración por "
            "hardware en ffmpeg: siempre se codifican por CPU."
        ), page)
        lbl_hint.setObjectName("mutedLabel")
        lbl_hint.setWordWrap(True)
        v.addWidget(lbl_hint)

        v.addStretch(1)
        self._reload_manual_variant()
        self._reload_manual_qualities()
        return page

    def _current_manual_codec_id(self) -> str:
        return self.combo_manual_codec.currentData() or "prores"

    def _reload_manual_variant(self):
        codec_id = self._current_manual_codec_id()
        variants = ENCODER_VARIANTS.get(codec_id)
        self.combo_manual_variant.blockSignals(True)
        self.combo_manual_variant.clear()
        if not variants:
            self.combo_manual_variant.setVisible(False)
            self.lbl_manual_variant.setVisible(False)
        else:
            for encoder, label in ordered_encoder_variants(codec_id, variants):
                self.combo_manual_variant.addItem(label, encoder)
            self.combo_manual_variant.setVisible(True)
            self.lbl_manual_variant.setVisible(True)
        self.combo_manual_variant.blockSignals(False)

    def _effective_manual_encoder(self, codec_id: str) -> str:
        if self.combo_manual_variant.isVisible() and self.combo_manual_variant.currentData():
            return self.combo_manual_variant.currentData()
        return _encoder_for(codec_id)

    def _reload_manual_qualities(self):
        codec_id = self._current_manual_codec_id()
        encoder = self._effective_manual_encoder(codec_id)
        current = self.combo_manual_quality.currentIndex()
        self.combo_manual_quality.blockSignals(True)
        self.combo_manual_quality.clear()
        for profile in get_profiles("video", encoder):
            self.combo_manual_quality.addItem(profile["label"])
        self.combo_manual_quality.blockSignals(False)
        restore = current if 0 <= current < self.combo_manual_quality.count() else 0
        self.combo_manual_quality.setCurrentIndex(restore)

    def _on_manual_codec_changed(self, *_args):
        self._reload_manual_variant()
        self._reload_manual_qualities()

    def _on_manual_variant_changed(self, *_args):
        self._reload_manual_qualities()

    def _on_manual_changed(self, *_args):
        pass

    # ─── Modo superior (Rápido/Manual) ──────────────────────────

    def _on_top_mode_changed(self, mode_text: str):
        self.stack.setCurrentIndex(0 if mode_text == self.tr("Rápido") else 1)

    # ─── API pública ─────────────────────────────────────────────

    def get_status(self) -> tuple[bool, str]:
        return True, self.tr("Iniciar Recodificación")

    def set_source_media(self, meta: dict, filepath: str):
        self._source_meta = meta or None
        self._source_filepath = filepath

    def _build_audio_settings(self, source_audio_codec_id: str | None, video_codec_id: str) -> dict:
        """Copia el audio tal cual si el matrix confirma que el codec de origen entra en
        .mov sin remux (igual criterio que Convertir - ver
        convert_advisor.is_stream_copy_compatible); si no, recodifica al codec recomendado
        para esta familia (PCM sin comprimir para las 3 - ver
        codec_profiles.RECOMMENDED_AUDIO_CODEC)."""
        if source_audio_codec_id and is_stream_copy_compatible(source_audio_codec_id, _CONTAINER):
            return {"audio_mode": "copy", "audio_codec": source_audio_codec_id, "audio_args": []}
        recommended = recommend_audio_codec(video_codec_id)
        encoder = resolve_encoder(recommended) or recommended
        args = ["-c:a", encoder] if recommended.startswith("pcm_") else build_custom_audio_bitrate_args(encoder, 256)
        return {"audio_mode": "recode", "audio_codec": recommended, "audio_args": args}

    def get_settings(self, meta_override: dict | None = None, filepath_override: str | None = None) -> dict:
        meta = meta_override if meta_override is not None else (self._source_meta or {})
        is_quick = self.mode_selector.current_mode() == self.tr("Rápido")

        if is_quick:
            codec_id = self._current_quick_codec_id()
            video_args = list(_quick_proxy_profile(codec_id, _encoder_for(codec_id))["args"])
            res_key = self._checked_key(self._quick_res_buttons, "completa")
        else:
            codec_id = self._current_manual_codec_id()
            encoder = self._effective_manual_encoder(codec_id)
            profiles = get_profiles("video", encoder)
            q_idx = self.combo_manual_quality.currentIndex()
            q_idx = q_idx if profiles and 0 <= q_idx < len(profiles) else 0
            video_args = list(profiles[q_idx]["args"]) if profiles else ["-c:v", encoder]
            res_key = self._checked_key(self._manual_res_buttons, "completa")

        video_args += _scale_filter_args(res_key)
        audio_settings = self._build_audio_settings(source_codec_id((meta or {}).get("audio_codec")), codec_id)

        return {
            "stream_mode": "video+audio",
            "video_mode": "recode",
            "video_codec": codec_id,
            "video_args": video_args,
            "container": _CONTAINER,
            **audio_settings,
        }
