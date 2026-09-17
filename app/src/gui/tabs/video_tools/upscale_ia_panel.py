# src/gui/tabs/video_tools/upscale_ia_panel.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame, QScrollArea, QSizePolicy, QComboBox
from PySide6.QtCore import Signal, Qt

from gui.styles import get_theme_token
from gui.widgets.combo_box import CheckmarkComboDelegate, AutoPopupComboBox
from gui.widgets.preset_bar import PresetBar
from gui.tabs.image_tools.upscale_popover import UpscalePopoverContent
from core.utils.preset_manager import IA_TOOL_FUNCTIONS, IA_TOOLS_NAMESPACE
from core.utils.recode_guard import CONTAINER_LABELS

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

# Fase 1 -- lista curada, no el matrix completo de get_compatible_containers():
# reassemble_video() (core/tabs/video_tools/video_upscale_engine.py) siempre
# codifica a H.264 y copia el audio original tal cual (-c:a copy), y estos 3
# son los contenedores ampliamente compatibles con esa combinación sin
# necesitar todavía la negociación de códec/contenedor completa que sí tiene
# Convertir/Comprimir (ver convert_panel.py). Ampliar esto es trabajo de
# una fase futura si hace falta.
_CONTAINER_IDS = ["mp4", "mov", "mkv"]


class UpscaleIAPanel(QWidget):
    """Pestaña "Herramientas IA" de Herramientas Multimedia (hoy solo Reescalado, ver
    core.utils.preset_manager.IA_TOOL_FUNCTIONS): extrae los fotogramas del video, los
    reescala con el motor NCNN elegido (mismo
    selector que Editor de Imagen, ver UpscalePopoverContent) y rearma el
    video en el contenedor elegido -- ver
    core/utils/queue_manager.py::QueueWorker._execute_upscale_video para la
    ejecución real (job_type "UPSCALE_VIDEO")."""

    validity_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        self.setObjectName("upscaleIAPanel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setObjectName("upscaleIAScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
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

        frame_container = QFrame(content)
        frame_container.setObjectName("advancedCard")
        border_color = get_theme_token('borde_sutil', '#2d2d2d')
        frame_container.setStyleSheet(f"""
            QFrame#advancedCard {{
                background-color: transparent;
                border: 1px solid {border_color};
                border-radius: 6px;
            }}
        """)
        frame_container.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        cv = QVBoxLayout(frame_container)
        cv.setContentsMargins(12, 10, 12, 12)
        cv.setSpacing(8)
        lbl_container = QLabel(self.tr("Contenedor de salida"), frame_container)
        lbl_container.setObjectName("sectionTitle")
        lbl_container.setAlignment(Qt.AlignCenter)
        cv.addWidget(lbl_container)

        self.combo_container = AutoPopupComboBox(frame_container)
        self.combo_container.setMaxVisibleItems(12)
        self.combo_container.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.combo_container.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.combo_container.setMinimumContentsLength(1)
        self.combo_container.setItemDelegate(CheckmarkComboDelegate(self.combo_container))
        self.combo_container.setCursor(Qt.PointingHandCursor)
        for container_id in _CONTAINER_IDS:
            self.combo_container.addItem(CONTAINER_LABELS.get(container_id, container_id.upper()), container_id)
        cv.addWidget(self.combo_container)
        layout.addWidget(frame_container)

        self.upscale_content = UpscalePopoverContent(content)
        self.upscale_content.selection_changed.connect(self._on_selection_changed)
        layout.addWidget(self.upscale_content)

        lbl_note = QLabel(
            self.tr("Extrae los fotogramas del video, los reescala todos con el motor "
                     "elegido y rearma el video con el audio original -- puede tardar bastante "
                     "más que una recodificación normal según la duración y la GPU."),
            content,
        )
        lbl_note.setObjectName("mutedLabel")
        lbl_note.setWordWrap(True)
        layout.addWidget(lbl_note)

        # Guardar como preajuste -- SOLO guardar, no elegir: el picker vive en
        # la pestaña "Preajustes" (ver presets_panel.py), junto con el de
        # Recodificación, para poder combinar los dos (correr Reescalado IA y
        # después Recodificación encadenados) -- mismo molde que
        # AdvancedRecodePanel (guarda) + PresetsPanel (elige), ahora repetido
        # para esta función.
        frame_presets = QFrame(content)
        frame_presets.setObjectName("advancedCard")
        frame_presets.setStyleSheet(frame_container.styleSheet())
        frame_presets.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        pv = QVBoxLayout(frame_presets)
        pv.setContentsMargins(12, 10, 12, 12)
        pv.setSpacing(8)
        lbl_presets = QLabel(self.tr("Preajustes"), frame_presets)
        lbl_presets.setObjectName("sectionTitle")
        lbl_presets.setAlignment(Qt.AlignCenter)
        pv.addWidget(lbl_presets)
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

    def _on_selection_changed(self, _engine_key, _model_key, is_valid):
        self.validity_changed.emit(is_valid)

    # ─── API pública (mismo contrato que los demás tabs de EncodingOptionsWidget) ──

    def is_valid(self) -> bool:
        return self.upscale_content.is_valid_selection()

    def get_status(self) -> tuple[bool, str]:
        if self.is_valid():
            return True, self.tr("Iniciar Reescalado")
        return False, self.tr("Elige un motor y un modelo de reescalado IA.")

    def get_settings(self, meta_override: dict | None = None, filepath_override: str | None = None) -> dict:
        settings = self.upscale_content.get_settings()
        settings["container"] = self.combo_container.currentData() or "mp4"
        return settings
