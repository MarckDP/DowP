# src/gui/tabs/video_tools/upscale_ia_panel.py
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QScrollArea, QSizePolicy, QComboBox,
)
from PySide6.QtCore import QCoreApplication, Signal, Qt

from gui.styles import get_theme_token
from gui.widgets.combo_box import CheckmarkComboDelegate, AutoPopupComboBox
from gui.widgets.preset_bar import PresetBar
from gui.tabs.image_tools.depth_popover import DepthPopoverContent
from gui.tabs.image_tools.normal_popover import NormalPopoverContent
from gui.tabs.image_tools.upscale_popover import UpscalePopoverContent
from gui.tabs.video_tools.ia_output_options import VideoIAOutputOptions
from core.tabs.video_tools.ia_video_common import CONTAINERS_16BIT
from core.utils.preset_manager import IA_TOOL_FUNCTIONS, IA_TOOLS_NAMESPACE
from core.utils.recode_guard import CONTAINER_LABELS
from gui.styles import set_themed_style

# Namespace PROPIO, no "video_tools/avanzado" -- ese namespace ya lo lee tal
# cual el picker de Recodificar de Modo Rápido, y su ejecución asume presets
# RECODE-shaped (ver build_recode_output_path). Mezclar ahí presets de
# UPSCALE_VIDEO los mostraría en esa lista sin que Modo Rápido pueda
# correrlos -- integrarlo de verdad ahí es trabajo de una fase futura, ver
# conversación. Nombrado de forma genérica ("ia_tools", no "upscale_ia") a
# propósito: es el namespace compartido de TODA función de IA (ver
# core.utils.preset_manager.IA_TOOL_FUNCTIONS y presets_panel.py, tarjeta
# "Preajustes de Herramientas IA") -- renombrado desde "video_tools/upscale_ia"
# (ver PresetManager._RENAMED_NAMESPACES, migra solo lo ya guardado).
_PRESET_NAMESPACE = IA_TOOLS_NAMESPACE

# Contenedores ofrecidos: los de uso general. Con "16 bits" (solo en los mapas) la lista
# se reduce a los que lo admiten sin pérdida (CONTAINERS_16BIT). Cómo se
# codifica cada caso: core/tabs/video_tools/ia_video_common.py.
_CONTAINER_IDS = ["mp4", "mov", "mkv"]

# Funciones de la pestaña. La clave viaja en los ajustes ("ia_function") para que la
# vista y los preajustes sepan qué job crear sin mirar el nombre visible.
FUNCTION_UPSCALE = "upscale"
FUNCTION_DEPTH = "depth"
FUNCTION_NORMALS = "normals"
FUNCTION_TRANSCRIPTION = "transcription"
_PRESET_FUNCTION_IDS = {FUNCTION_UPSCALE: ("ia_reescalar", "UPSCALE_VIDEO"),
                        FUNCTION_DEPTH: ("ia_profundidad", "DEPTH_VIDEO"),
                        FUNCTION_NORMALS: ("ia_normales", "NORMAL_VIDEO"),
                        FUNCTION_TRANSCRIPTION: ("ia_transcripcion", "TRANSCRIBE")}
# Funciones que generan un mapa fotograma a fotograma (ver video_frame_engine.py):
# comparten las opciones de video (suavizado, procesar a menos fps) y la casilla "16 bits".
_MAP_FUNCTIONS = (FUNCTION_DEPTH, FUNCTION_NORMALS)
# Contenedor inicial de cada función, hasta que el usuario elija otro. Mapa de Normales
# empieza en MOV (ProRes 4444): H.264 deforma las direcciones (ver
# ia_video_common.build_video_encode_args).
_DEFAULT_CONTAINERS = {FUNCTION_NORMALS: "mov"}


def ia_function_of(settings: dict | None) -> str:
    """Qué función de IA describe un dict de ajustes (o un preajuste guardado). Los
    preajustes anteriores al Mapa de Profundidad no traen la clave: son Reescalado."""
    return (settings or {}).get("ia_function") or FUNCTION_UPSCALE


def ia_settings_ready(settings: dict | None) -> bool:
    """¿El motor/modelo de un dict de ajustes de IA (un preajuste guardado) está en
    disco y no a medio descargar? Ver gui/widgets/ia_preset_models.py."""
    from gui.widgets.ia_preset_models import preset_model_ready
    return preset_model_ready(settings)


class UpscaleIAPanel(QWidget):
    """Página permanente de una función de IA, con sus propios ajustes y scroll."""

    validity_changed = Signal(bool)

    def __init__(self, parent=None, *, function=FUNCTION_UPSCALE):
        super().__init__(parent)
        if function not in _PRESET_FUNCTION_IDS:
            raise ValueError(f"Función de IA desconocida: {function}")
        self._function = function
        self._init_ui()

    def _card(self, parent, title: str, header: QWidget | None = None):
        frame = QFrame(parent)
        frame.setObjectName("advancedCard")
        set_themed_style(frame, lambda: f"""
            QFrame#advancedCard {{
                background-color: transparent;
                border: 1px solid {get_theme_token('borde_sutil', '#2d2d2d')};
                border-radius: 6px;
            }}
        """)
        frame.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        v = QVBoxLayout(frame)
        v.setContentsMargins(12, 10, 12, 12)
        v.setSpacing(8)
        if header is not None:
            # Cabecera propia en lugar del título (ej. la casilla "Recodificar").
            v.addWidget(header)
        else:
            lbl = QLabel(title, frame)
            lbl.setObjectName("sectionTitle")
            lbl.setAlignment(Qt.AlignCenter)
            v.addWidget(lbl)
        return frame, v

    def _combo(self, parent):
        combo = AutoPopupComboBox(parent)
        combo.setMaxVisibleItems(12)
        combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(1)
        combo.setItemDelegate(CheckmarkComboDelegate(combo))
        combo.setCursor(Qt.PointingHandCursor)
        return combo

    def _init_ui(self):
        self.setObjectName("upscaleIAPanel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setObjectName("upscaleIAScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        # Sin scroll horizontal mientras quepa; si la ventana es tan angosta que no entra,
        # mejor una barra que controles cortados (ver content_min_width).
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.viewport().setAutoFillBackground(False)
        self.setStyleSheet("""
            QWidget#upscaleIAPanel { background: transparent; }
            QScrollArea#upscaleIAScroll { background: transparent; }
            QWidget#upscaleIAContent { background: transparent; }
        """)

        content = QWidget(scroll)
        content.setObjectName("upscaleIAContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # ── Contenedor de salida (+ 16 bits / transparencia / audio) ─────────
        frame_container, cv = self._card(content, self.tr("Contenedor de salida"))
        self.frame_container = frame_container
        self.combo_container = self._combo(frame_container)
        cv.addWidget(self.combo_container)
        self.output_options = VideoIAOutputOptions(frame_container, allow_16bit=True)
        cv.addWidget(self.output_options)
        self.combo_container.currentIndexChanged.connect(self._on_container_changed)
        self.output_options.depth16_toggled.connect(self._populate_containers)
        layout.addWidget(frame_container)

        # ── Contenido de cada función ────────────────────────────────────────
        function = self.current_function()
        if function == FUNCTION_TRANSCRIPTION:
            from gui.tabs.ai_tools.transcription_panel import TranscriptionPanel
            self.transcription_content = page = TranscriptionPanel(content)
        elif function == FUNCTION_DEPTH:
            self.depth_content = page = DepthPopoverContent(content, video_mode=True)
        elif function == FUNCTION_NORMALS:
            self.normal_content = page = NormalPopoverContent(content, video_mode=True)
        else:
            self.upscale_content = page = UpscalePopoverContent(content)
        page.selection_changed.connect(self._on_selection_changed)
        # Solo la página activa participa en la altura; no hay pila compartida.
        page.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        for combo in page.findChildren(QComboBox):
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(8)
            policy = combo.sizePolicy()
            policy.setHorizontalPolicy(QSizePolicy.Expanding)
            combo.setSizePolicy(policy)
        layout.addWidget(page)

        # Opciones de video de los mapas (profundidad y normales): una sola tarjeta,
        # debajo del selector de modelo de la función elegida.
        frame_video, vv = self._card(content, self.tr("Opciones de video"))
        self.frame_video = frame_video
        row = QHBoxLayout()
        row.addWidget(QLabel(self.tr("Suavizado:"), frame_video))
        self.combo_smoothing = self._combo(frame_video)
        self.combo_smoothing.addItem(self.tr("Desactivado"), "off")
        self.combo_smoothing.addItem(self.tr("Bajo"), "low")
        self.combo_smoothing.addItem(self.tr("Medio"), "medium")
        self.combo_smoothing.addItem(self.tr("Alto"), "high")
        row.addWidget(self.combo_smoothing, 1)
        vv.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel(self.tr("Procesar:"), frame_video))
        self.combo_step = self._combo(frame_video)
        self.combo_step.addItem(self.tr("Todos los fotogramas"), 1)
        self.combo_step.addItem(self.tr("La mitad (2× más rápido)"), 2)
        self.combo_step.addItem(self.tr("Un tercio (3× más rápido)"), 3)
        self.combo_step.addItem(self.tr("Un cuarto (4× más rápido)"), 4)
        self.combo_step.setToolTip(self.tr(
            "Calcula el mapa solo en una parte de los fotogramas y rellena los "
            "demás mezclando los dos mapas vecinos. El video conserva sus fps y su duración."))
        row.addWidget(self.combo_step, 1)
        vv.addLayout(row)

        layout.addWidget(frame_video)

        self.lbl_note = QLabel(content)
        self.lbl_note.setObjectName("mutedLabel")
        self.lbl_note.setWordWrap(True)
        layout.addWidget(self.lbl_note)

        # Guardar como preajuste -- SOLO guardar, no elegir: el picker vive en
        # la pestaña "Preajustes" (ver presets_panel.py), junto con el de
        # Recodificación, para poder combinar los dos (correr la función de IA y
        # después Recodificación encadenados) -- mismo molde que
        # AdvancedRecodePanel (guarda) + PresetsPanel (elige).
        # Aquí solo se guarda: la lista para elegir (las tres funciones en un solo menú)
        # vive en la pestaña Preajustes de Herramientas IA, y en Multimedia y Posprocesar.
        frame_presets, pv = self._card(content, self.tr("Preajustes"))
        self.preset_bar = PresetBar(
            _PRESET_NAMESPACE, self.get_settings, frame_presets,
            show_picker=False, show_save_button=True,
            default_function="ia_reescalar", job_type="UPSCALE_VIDEO",
            function_choices=IA_TOOL_FUNCTIONS,
        )
        pv.addWidget(self.preset_bar)
        layout.addWidget(frame_presets)

        layout.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        self._scroll = scroll
        self._content = content
        self._content_layout = layout

        self._configure_function()

    def content_min_width(self) -> int:
        """Ancho que necesita el contenido para no cortarse, con la barra de scroll
        vertical incluida (el QScrollArea no lo propaga en su minimumSizeHint)."""
        bar = self._scroll.verticalScrollBar().sizeHint().width()
        frame = 2 * self._scroll.frameWidth()
        return self._content.minimumSizeHint().width() + bar + frame + 4

    def add_card(self, title: str, header: QWidget | None = None):
        """Tarjeta nueva al final del panel, dentro del mismo scroll y con el mismo
        estilo (la usa la pestaña Herramientas IA para "Recodificar"). `header`
        reemplaza al título. Devuelve (frame, layout)."""
        frame, v = self._card(self._content, title, header)
        self._content_layout.insertWidget(self._content_layout.count() - 1, frame)
        return frame, v

    # ─── Internos ────────────────────────────────────────────────────────────

    def current_function(self) -> str:
        return self._function

    def _configure_function(self):
        function = self.current_function()
        is_map = function in _MAP_FUNCTIONS
        self.frame_video.setVisible(is_map)
        self.frame_container.setVisible(function != FUNCTION_TRANSCRIPTION)
        self.output_options.set_kind("normals" if function == FUNCTION_NORMALS else
                                     "gray" if function == FUNCTION_DEPTH else "color")
        # "16 bits" solo tiene sentido en los mapas.
        if self.output_options.chk_16bit is not None:
            if not is_map:
                self.output_options.chk_16bit.setChecked(False)
            self.output_options.chk_16bit.setVisible(is_map)
        self._populate_containers(preferred=_DEFAULT_CONTAINERS.get(function))
        if function == FUNCTION_TRANSCRIPTION:
            self.lbl_note.setText(self.tr("Transcribe audio o video en tu equipo y genera subtítulos, texto o un video con los subtítulos incluidos. Tus archivos no se suben a ningún servidor. Los tiempos de un recorte comienzan en cero."))
        elif function == FUNCTION_DEPTH:
            self.combo_smoothing.setToolTip(self.tr(
                "Mezcla cada mapa con el anterior para quitar el temblor entre fotogramas. "
                "Cuanto más alto, más estable, pero en movimientos rápidos deja una ligera estela.\n"
                "Con Depth Anything 3 casi no hace falta: ya calcula varios fotogramas a la vez."))
            self.lbl_note.setText(self.tr(
                "Calcula la profundidad de cada fotograma con el modelo elegido, sin guardar "
                "fotogramas en disco. Con modelos grandes puede tardar bastante: se recomienda GPU."))
        elif function == FUNCTION_NORMALS:
            self.combo_smoothing.setToolTip(self.tr(
                "Mezcla cada mapa con el anterior para quitar el temblor entre fotogramas. "
                "Cuanto más alto, más estable, pero en movimientos rápidos deja una ligera estela."))
            self.lbl_note.setText(self.tr(
                "Calcula las normales de cada fotograma con MoGe-2, sin guardar fotogramas en "
                "disco, y las amplía al tamaño original. Con modelos grandes puede tardar "
                "bastante: se recomienda GPU."))
        else:
            self.lbl_note.setText(self.tr(
                "Extrae los fotogramas del video, los reescala todos con el motor "
                "elegido y rearma el video con el audio original -- puede tardar bastante "
                "más que una recodificación normal según la duración y la GPU."))
        preset_function, job_type = _PRESET_FUNCTION_IDS[function]
        self.preset_bar.set_save_defaults(preset_function, job_type)
        self.validity_changed.emit(self.is_valid())

    def _populate_containers(self, *_args, preferred: str | None = None):
        """Con "16 bits" solo quedan los contenedores que lo admiten (MKV, MOV); si el
        elegido (o `preferred`) ya no está, pasa al primero de esa lista."""
        current = preferred or self.combo_container.currentData()
        ids = list(CONTAINERS_16BIT) if self.output_options.is_16bit() else _CONTAINER_IDS
        self.combo_container.blockSignals(True)
        self.combo_container.clear()
        for container_id in ids:
            self.combo_container.addItem(CONTAINER_LABELS.get(container_id, container_id.upper()), container_id)
        idx = self.combo_container.findData(current)
        self.combo_container.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo_container.blockSignals(False)
        self.output_options.set_container(self.combo_container.currentData())

    def _on_container_changed(self, _index: int):
        self.output_options.set_container(self.combo_container.currentData())

    def _on_selection_changed(self, *_args):
        self.validity_changed.emit(self.is_valid())

    # ─── API pública (mismo contrato que los demás tabs de EncodingOptionsWidget) ──

    def _current_content(self):
        function = self.current_function()
        if function == FUNCTION_TRANSCRIPTION:
            return self.transcription_content
        if function == FUNCTION_DEPTH:
            return self.depth_content
        if function == FUNCTION_NORMALS:
            return self.normal_content
        return self.upscale_content

    def is_valid(self) -> bool:
        """Hay motor y modelo elegidos Y el modelo ya está en disco: mientras se
        descarga (o si no se descargó) no se puede iniciar."""
        return self._current_content().is_ready()

    @staticmethod
    def start_text(function: str) -> str:
        if function == FUNCTION_TRANSCRIPTION:
            return QCoreApplication.translate("UpscaleIAPanel", "Iniciar Transcripción")
        if function == FUNCTION_DEPTH:
            return QCoreApplication.translate("UpscaleIAPanel", "Iniciar Mapa de Profundidad")
        if function == FUNCTION_NORMALS:
            return QCoreApplication.translate("UpscaleIAPanel", "Iniciar Mapa de Normales")
        return QCoreApplication.translate("UpscaleIAPanel", "Iniciar Reescalado")

    def get_status(self) -> tuple[bool, str]:
        function = self.current_function()
        content = self._current_content()
        if function == FUNCTION_TRANSCRIPTION:
            return (True, self.tr("Iniciar Transcripción")) if content.is_ready() else (False, content.not_ready_reason())
        if content.is_valid_selection() and not content.is_ready():
            return False, self.tr("El modelo elegido todavía no está descargado.")
        if function == FUNCTION_DEPTH:
            if self.is_valid():
                return True, self.tr("Iniciar Mapa de Profundidad")
            return False, self.tr("Elige un motor y un modelo de profundidad.")
        if function == FUNCTION_NORMALS:
            if self.is_valid():
                return True, self.tr("Iniciar Mapa de Normales")
            return False, self.tr("Elige un motor y un modelo de normales.")
        if self.is_valid():
            return True, self.tr("Iniciar Reescalado")
        return False, self.tr("Elige un motor y un modelo de reescalado IA.")

    def get_settings(self, meta_override: dict | None = None, filepath_override: str | None = None) -> dict:
        function = self.current_function()
        if function == FUNCTION_TRANSCRIPTION:
            return self.transcription_content.get_settings()
        if function == FUNCTION_DEPTH:
            settings = self.depth_content.get_settings()
            settings["depth_smoothing"] = self.combo_smoothing.currentData() or "off"
            settings["depth_frame_step"] = self.combo_step.currentData() or 1
        elif function == FUNCTION_NORMALS:
            settings = self.normal_content.get_settings()
            settings["normals_smoothing"] = self.combo_smoothing.currentData() or "off"
            settings["normals_frame_step"] = self.combo_step.currentData() or 1
        else:
            settings = self.upscale_content.get_settings()
        settings["ia_function"] = function
        settings["container"] = self.combo_container.currentData() or "mp4"
        settings.update(self.output_options.get_settings())
        return settings
