# src/gui/tabs/video_tools/encoding_options_widget.py
from PySide6.QtWidgets import (
    QFrame,
    QVBoxLayout,
    QTabWidget,
)
from PySide6.QtCore import Signal

from gui.styles import get_theme_token
from gui.tabs.video_tools.presets_panel import PresetsPanel
from gui.tabs.video_tools.compress_panel import CompressPanel
from gui.tabs.video_tools.convert_panel import ConvertPanel
from gui.tabs.video_tools.editing_panel import EditingPanel
from gui.tabs.video_tools.advanced_recode_panel import AdvancedRecodePanel
from gui.tabs.video_tools.upscale_ia_panel import UpscaleIAPanel
from gui.widgets.animated_tab_indicator import AnimatedTabIndicator

class EncodingOptionsWidget(QFrame):
    """
    Panel derecho de opciones con pestañas (Preajustes, Comprimir, Convertir, Edición, Avanzado).
    Caja principal contenedora con fondo transparente y borde acorde al tema.
    """
    options_changed = Signal(dict)
    # Emitida cuando cambia el estado del botón "Iniciar" (válido/inválido + texto contextual)
    start_status_changed = Signal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("encodingOptionsWidget")
        self._init_ui()

    def _init_ui(self):
        bg_color = get_theme_token('fondo_secundario', '#121212')
        border_color = get_theme_token('borde_normal', '#222222')
        accent_color = get_theme_token('acento_primario', '#B9E640')
        self.setStyleSheet(f"""
            QFrame#encodingOptionsWidget {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: 6px;
            }}
            QTabWidget#encodingTabs::pane {{
                background: transparent;
                border-top: 1px solid {border_color};
            }}
            QTabWidget#encodingTabs > QTabBar::tab {{
                background: transparent;
                padding: 8px 18px;
            }}
            QTabWidget#encodingTabs > QTabBar::tab:selected {{
                background: transparent;
                color: #ffffff;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(0)

        # Tab Widget Principal de Opciones
        self.tabs = QTabWidget()
        self.tabs.setObjectName("encodingTabs")

        self.tab_presets = PresetsPanel(self)
        self.tabs.addTab(self.tab_presets, self.tr("Preajustes"))

        self.tab_compress = CompressPanel(self)
        self.tabs.addTab(self.tab_compress, self.tr("Comprimir"))
        self.tab_compress.validity_changed.connect(self._on_compress_validity_changed)

        self.tab_convert = ConvertPanel(self)
        self.tabs.addTab(self.tab_convert, self.tr("Convertir"))
        self.tab_convert.validity_changed.connect(self._on_convert_validity_changed)

        self.tab_editing = EditingPanel(self)
        self.tabs.addTab(self.tab_editing, self.tr("Edición"))
        self.tab_editing.validity_changed.connect(self._on_editing_validity_changed)

        self.tab_advanced = AdvancedRecodePanel(self)
        self.tabs.addTab(self.tab_advanced, self.tr("Avanzado"))
        self.tab_advanced.validity_changed.connect(self._on_advanced_validity_changed)

        self.tab_upscale_ia = UpscaleIAPanel(self)
        self.tabs.addTab(self.tab_upscale_ia, self.tr("Herramientas IA"))
        self.tab_upscale_ia.validity_changed.connect(self._on_upscale_ia_validity_changed)

        # Preajustes cambia de válido/inválido cuando el usuario elige o deselecciona un
        # preset en CUALQUIERA de las dos secciones (Recodificación o Reescalado IA).
        self.tab_presets.preset_bar_recode.preset_applied.connect(self._on_presets_validity_changed)
        self.tab_presets.preset_bar_upscale.preset_applied.connect(self._on_presets_validity_changed)

        layout.addWidget(self.tabs)

        self.tabs.currentChanged.connect(self._on_tab_changed)

        self._tabs_indicator = AnimatedTabIndicator(self.tabs)

    def get_current_status(self) -> tuple[bool, str]:
        current = self.tabs.currentWidget()
        if current is self.tab_advanced:
            return self.tab_advanced.get_status()
        if current is self.tab_presets:
            return self.tab_presets.get_status()
        if current is self.tab_compress:
            return self.tab_compress.get_status()
        if current is self.tab_convert:
            return self.tab_convert.get_status()
        if current is self.tab_editing:
            return self.tab_editing.get_status()
        if current is self.tab_upscale_ia:
            return self.tab_upscale_ia.get_status()
        return True, self.tr("Iniciar Recodificación")

    def _emit_current_status(self):
        is_valid, text = self.get_current_status()
        self.start_status_changed.emit(is_valid, text)

    def _on_tab_changed(self, index: int):
        self._emit_current_status()

    def _on_advanced_validity_changed(self, _is_valid: bool):
        if self.tabs.currentWidget() is self.tab_advanced:
            self._emit_current_status()

    def _on_presets_validity_changed(self, *_args):
        if self.tabs.currentWidget() is self.tab_presets:
            self._emit_current_status()

    def _on_compress_validity_changed(self, _is_valid: bool):
        if self.tabs.currentWidget() is self.tab_compress:
            self._emit_current_status()

    def _on_convert_validity_changed(self, _is_valid: bool):
        if self.tabs.currentWidget() is self.tab_convert:
            self._emit_current_status()

    def _on_editing_validity_changed(self, _is_valid: bool):
        if self.tabs.currentWidget() is self.tab_editing:
            self._emit_current_status()

    def _on_upscale_ia_validity_changed(self, _is_valid: bool):
        if self.tabs.currentWidget() is self.tab_upscale_ia:
            self._emit_current_status()

    def get_encoding_settings(self, file_meta: dict | None = None, filepath: str | None = None) -> dict:
        """`file_meta`/`filepath`, si se pasan, describen un archivo del lote DISTINTO al
        que está en preview - Comprimir los necesita para recalcular por archivo (Rápido:
        el nivel es una fracción del bitrate de CADA archivo; Manual: "Tamaño objetivo" y
        "Mismo que el original" dependen de la duración/extensión real de cada uno - ver
        video_tools_view.py)."""
        current = self.tabs.currentWidget()
        if current is self.tab_advanced:
            return self.tab_advanced.get_settings()
        if current is self.tab_presets:
            return self.tab_presets.get_settings(meta_override=file_meta, filepath_override=filepath)
        if current is self.tab_compress:
            return self.tab_compress.get_settings(meta_override=file_meta, filepath_override=filepath)
        if current is self.tab_convert:
            return self.tab_convert.get_settings(meta_override=file_meta, filepath_override=filepath)
        if current is self.tab_editing:
            return self.tab_editing.get_settings(meta_override=file_meta, filepath_override=filepath)
        if current is self.tab_upscale_ia:
            return self.tab_upscale_ia.get_settings(meta_override=file_meta, filepath_override=filepath)
        return {}
