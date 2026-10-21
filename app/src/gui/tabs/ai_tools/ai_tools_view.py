# src/gui/tabs/ai_tools/ai_tools_view.py
"""
Pestaña "Herramientas IA": Reescalado, Mapa de Profundidad y Mapa de Normales de
video, con IA local.

Comparte con Herramientas Multimedia toda la base (cola, vista previa con recorte,
opciones de salida con etiquetas, progreso, seguimiento de trabajos y la cadena
IA -> recodificación): ver gui/tabs/video_tools/media_workbench.py. Tiene su propio
carril en la cola (ORIGIN_AI_TOOLS), su carpeta de salida, su sufijo y su tutorial.
Solo corre un proceso pesado a la vez en toda la app, y la IA espera a las
recodificaciones pendientes (ver _HEAVY_JOB_TYPES/_AI_JOB_TYPES en queue_manager.py).
"""
import os
import re
from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QLabel, QMessageBox, QScrollArea, QStackedWidget, QTabWidget, QVBoxLayout, QWidget,
)

from core.utils.config_manager import get_config, save_config
from gui.tabs.ai_tools.ai_preview_panel import AIPreviewPanel
from gui.tabs.video_tools.media_workbench import MediaWorkbenchTab
from gui.tabs.video_tools.upscale_ia_panel import FUNCTION_UPSCALE, UpscaleIAPanel, ia_function_of, ia_settings_ready
from gui.widgets.animated_tab_indicator import AnimatedTabIndicator
from core.utils.preset_manager import IA_TOOL_FUNCTIONS, IA_TOOLS_NAMESPACE
from gui.widgets.mode_selector import ModeSelector
from gui.widgets.resettable_splitter import ResettableSplitter
from gui.tabs.video_tools.advanced_recode_panel import _PRESET_NAMESPACE as _RECODE_PRESET_NAMESPACE
from gui.widgets.preset_bar import PresetBar
from gui.styles import get_theme_token, set_themed_style
from core.logger.logger_manager import logger
from core.utils.queue_manager import ORIGIN_AI_TOOLS
from core.utils.sound_notifier import SOURCE_AI_TOOLS


class AIToolsOptions(QFrame):
    """Opciones de Herramientas IA, en dos pestañas (como las de Multimedia):

    - Opciones: función, motor/modelo, contenedor... (UpscaleIAPanel), "Guardar como
      preajuste" y la tarjeta "Recodificar" (opcional, corre después de la IA).
    - Preajustes: un preajuste de IA (Reescalado, Profundidad o Normales en un solo
      menú) y, si se quiere, uno de Recodificación que corre después. Se usan tal cual,
      sin tocar los controles de Opciones. Recodificar sin IA no: para eso está
      Herramientas Multimedia.

    Iniciar corre lo de la pestaña abierta, y solo se activa si hay algo válido elegido
    y su modelo ya está en disco (no mientras se descarga)."""

    start_status_changed = Signal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("aiOptionsCard")
        set_themed_style(self, lambda: f"""
            QFrame#aiOptionsCard {{
                background-color: {get_theme_token('fondo_secundario', '#121212')};
                border: 1px solid {get_theme_token('borde_normal', '#222222')};
                border-radius: 6px;
            }}
            QTabWidget#aiOptionsTabs::pane {{
                background: transparent;
                border-top: 1px solid {get_theme_token('borde_normal', '#222222')};
            }}
            QTabWidget#aiOptionsTabs > QTabBar::tab {{
                background: transparent;
                padding: 8px 18px;
            }}
            QTabWidget#aiOptionsTabs > QTabBar::tab:selected {{
                background: transparent;
                color: #ffffff;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(0)

        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("aiOptionsTabs")

        # ── Opciones ─────────────────────────────────────────────────────────
        self.panel = UpscaleIAPanel(self)
        self.chk_recode = QCheckBox(self.tr("Recodificar"))
        self.chk_recode.setObjectName("sectionTitle")
        self.chk_recode.setToolTip(self.tr(
            "Al terminar la IA, recodifica el video con un preajuste de Recodificación "
            "(por ejemplo, para pasarlo a H.265 o comprimirlo). El archivo intermedio se borra solo."))
        _frame, card = self.panel.add_card(self.tr("Recodificar"), header=self.chk_recode)
        self.preset_bar_recode = PresetBar(
            _RECODE_PRESET_NAMESPACE, get_settings=None, parent=self,
            show_picker=True, show_save_button=False,
        )
        self.preset_bar_recode.setEnabled(False)
        card.addWidget(self.preset_bar_recode)
        card.addWidget(self._hint(self.tr(
            "Los preajustes de Recodificación se crean en Herramientas Multimedia, pestaña Avanzado.")))
        self.tabs.addTab(self.panel, self.tr("Opciones"))

        # ── Preajustes ───────────────────────────────────────────────────────
        presets_page = QScrollArea(self)
        presets_page.setWidgetResizable(True)
        presets_page.setFrameShape(QFrame.NoFrame)
        presets_page.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        presets_page.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        presets_page.viewport().setAutoFillBackground(False)
        presets_content = QWidget()
        # Con selector: un "background: transparent" suelto se hereda a todo lo de
        # adentro (botones, la lista desplegable de los combos) y los deja transparentes.
        presets_content.setObjectName("aiPresetsContent")
        presets_content.setStyleSheet("QWidget#aiPresetsContent { background: transparent; }")
        pl = QVBoxLayout(presets_content)
        pl.setContentsMargins(10, 10, 10, 10)
        pl.setSpacing(10)

        frame_ia, iv = self.panel._card(presets_content, self.tr("Preajustes de IA"))
        self.preset_bar_ia = PresetBar(
            IA_TOOLS_NAMESPACE, get_settings=None, parent=frame_ia,
            show_picker=True, show_save_button=False,
            function_choices=IA_TOOL_FUNCTIONS,
        )
        iv.addWidget(self.preset_bar_ia)
        iv.addWidget(self._hint(self.tr(
            "Se guardan desde la pestaña Opciones, con \"Guardar como preajuste\".")))
        pl.addWidget(frame_ia)

        frame_rc, rv = self.panel._card(presets_content, self.tr("Recodificar"))
        self.preset_bar_recode_presets = PresetBar(
            _RECODE_PRESET_NAMESPACE, get_settings=None, parent=frame_rc,
            show_picker=True, show_save_button=False,
        )
        rv.addWidget(self.preset_bar_recode_presets)
        rv.addWidget(self._hint(self.tr("Opcional: corre después de la IA.")))
        pl.addWidget(frame_rc)
        pl.addStretch(1)
        presets_page.setWidget(presets_content)
        self.tabs.addTab(presets_page, self.tr("Preajustes"))
        self._presets_page = presets_page

        layout.addWidget(self.tabs)
        self._tabs_indicator = AnimatedTabIndicator(self.tabs)

        self.panel.validity_changed.connect(self._emit_status)
        self.chk_recode.toggled.connect(self._on_recode_toggled)
        self.preset_bar_recode.preset_applied.connect(self._emit_status)
        self.preset_bar_ia.preset_applied.connect(self._emit_status)
        self.preset_bar_recode_presets.preset_applied.connect(self._emit_status)
        self.tabs.currentChanged.connect(self._emit_status)
        # Un preajuste de IA cuyo modelo empieza o termina de descargarse.
        from gui.widgets.model_download_prompt import model_downloads
        model_downloads().started.connect(self._emit_status)
        model_downloads().finished.connect(self._emit_status)
        model_downloads().models_changed.connect(self._emit_status)

    def _hint(self, text: str) -> QLabel:
        hint = QLabel(text)
        hint.setWordWrap(True)
        set_themed_style(hint, lambda: f"color: {get_theme_token('texto_secundario', '#888888')}; font-size: 11px;")
        return hint

    def _on_recode_toggled(self, checked: bool):
        self.preset_bar_recode.setEnabled(checked)
        self._emit_status()

    def _emit_status(self, *_args):
        self.start_status_changed.emit(*self.get_current_status())

    def on_presets_tab(self) -> bool:
        return self.tabs.currentWidget() is self._presets_page

    def get_current_status(self) -> tuple[bool, str]:
        if self.on_presets_tab():
            settings = self.preset_bar_ia.current_preset_settings()
            if settings is None:
                return False, self.tr("Elige un preajuste de IA.")
            if not ia_settings_ready(settings):
                return False, self.tr("El modelo del preajuste todavía no está descargado.")
            return True, UpscaleIAPanel.start_text(ia_function_of(settings))
        valid, text = self.panel.get_status()
        if valid and self.chk_recode.isChecked() and self.preset_bar_recode.current_preset_settings() is None:
            return False, self.tr("Elige un preajuste de recodificación.")
        return valid, text

    def get_ia_settings(self) -> dict:
        if self.on_presets_tab():
            return dict(self.preset_bar_ia.current_preset_settings() or {})
        return self.panel.get_settings()

    def get_recode_settings(self) -> dict | None:
        """Ajustes de la recodificación que corre después de la IA, o None si no hay."""
        if self.on_presets_tab():
            preset = self.preset_bar_recode_presets.current_preset_settings()
        elif self.chk_recode.isChecked():
            preset = self.preset_bar_recode.current_preset_settings()
        else:
            preset = None
        if preset is None:
            return None
        settings = dict(preset)
        # "same" (ej. Normalizar Audio) se resuelve contra el archivo de origen; aquí
        # el origen de la recodificación es siempre el video que entrega la IA.
        if settings.get("container") == "same":
            settings["container"] = "mp4"
        return settings


class AIToolsTab(MediaWorkbenchTab):
    """Pestaña Herramientas IA (ver docstring del módulo).

    Layout propio, más cercano al Gestor de Medios que a Multimedia: Cola | Vista
    previa y detalles (ver ai_preview_panel.py) | Opciones siempre visibles con la
    salida debajo. Sin línea de tiempo abajo ni panel de opciones plegable."""

    QUEUE_ORIGIN = ORIGIN_AI_TOOLS
    SOUND_SOURCE = SOURCE_AI_TOOLS
    CONFIG_PREFIX = "ai_tools"
    LAYOUT_CONFIG_KEY = "ai_tools_layout"
    TUTORIAL_CONFIG_KEY = "tutorial_ai_tools_seen"
    DEFAULT_SUFFIX = "_ia"
    LOG_NAME = "AIToolsTab"

    QUEUE_WIDTH = 300
    QUEUE_MIN_WIDTH = 290
    PREVIEW_MIN_WIDTH = 320
    RIGHT_COLUMN_WIDTH = 420
    RIGHT_COLUMN_MIN_WIDTH = 400
    # Modo angosto: lo mínimo que pueden ocupar las dos columnas, para que esta pestaña
    # nunca suba el mínimo de toda la ventana (800 px). Si las opciones no caben, su
    # panel muestra scroll horizontal en vez de cortarse.
    NARROW_PREVIEW_MIN_WIDTH = 290
    NARROW_RIGHT_MIN_WIDTH = 440

    def __init__(self, parent=None):
        self._source_meta = {}
        super().__init__(parent)
        self._load_saved_suffix()
        self.txt_suffix.editingFinished.connect(self._save_suffix)

        self.preview_widget.subclip_editor_requested.connect(self._open_subclip_editor)
        self.preview_widget.reveal_requested.connect(self._on_reveal_clicked)
        self.preview_widget.send_to_editor_requested.connect(self._on_send_to_editor_clicked)
        self.options_widget.start_status_changed.connect(lambda *_: self._refresh_details())
        self.queue_widget.file_selected.connect(lambda *_: self._refresh_editor_button())
        from core.services.editor_integration_manager import EditorIntegrationManager
        editor_mgr = EditorIntegrationManager.get_instance()
        if editor_mgr:
            editor_mgr.active_editor_changed.connect(lambda *_: self._refresh_editor_button())
        self._refresh_editor_button()

    # ------------------------------------------------------------------
    # Ganchos de MediaWorkbenchTab
    # ------------------------------------------------------------------
    def _create_options_widget(self):
        return AIToolsOptions(self)

    def _create_preview_widget(self):
        return AIPreviewPanel(self)

    def _create_timeline_widget(self):
        return None

    def _assemble_layout(self, main_layout):
        self.queue_widget.setMinimumWidth(self.QUEUE_MIN_WIDTH)
        self.preview_widget.setMinimumWidth(self.PREVIEW_MIN_WIDTH)

        # Columna derecha: opciones (con su propio scroll) y, debajo, la salida e Iniciar.
        # Misma tarjeta que las opciones de Multimedia (fondo_secundario sobre el fondo
        # de la ventana).
        self.right_column = QWidget(self)
        right_layout = QVBoxLayout(self.right_column)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        right_layout.addWidget(self.options_widget, 1)
        right_layout.addWidget(self.output_card)

        # Dos modos (ver _update_responsive_mode): ancho = Cola | Vista previa | Opciones;
        # angosto = [Cola / Vista previa] | Opciones, donde la columna izquierda muestra
        # una de las dos a la vez, a tamaño completo, con un selector arriba (el mismo de
        # Reescalado / Profundidad / Normales). Las opciones nunca se esconden.
        self.left_box = QWidget(self)
        left_layout = QVBoxLayout(self.left_box)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        self.view_selector = ModeSelector(self.left_box, labels=[self.tr("Cola"), self.tr("Vista previa")])
        self.view_selector.mode_changed.connect(self._on_left_view_changed)
        left_layout.addWidget(self.view_selector)
        self.left_stack = QStackedWidget(self.left_box)
        left_layout.addWidget(self.left_stack, 1)
        self.left_box.hide()
        # Doble clic en un archivo: en la vista angosta, pasa a su vista previa.
        self.queue_widget.tree.doubleClicked.connect(lambda *_: self._show_left_view(1))

        self.main_splitter = ResettableSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.addWidget(self.queue_widget)
        self.main_splitter.addWidget(self.preview_widget)
        self.main_splitter.addWidget(self.right_column)
        self.main_splitter.splitterMoved.connect(lambda *_: self._layout_save_timer.start())
        self.main_splitter.reset_requested.connect(lambda: self._reset_layout("top"))
        self._wide_mode = True
        self._layout_applied = False
        self._set_stretch()
        main_layout.addWidget(self.main_splitter, 1)
        self.options_widget.start_status_changed.connect(lambda *_: self._update_right_min_width())
        self._update_right_min_width()

    def _set_stretch(self):
        # Al cambiar el ancho de la ventana, la diferencia la absorbe la vista previa
        # (modo ancho) o la columna de la cola y la vista previa (modo angosto).
        last_left = self.main_splitter.count() - 2  # justo antes de la columna derecha
        for index in range(self.main_splitter.count()):
            self.main_splitter.setStretchFactor(index, 1 if index == last_left else 0)

    def _right_min_width(self) -> int:
        """Lo que piden las opciones de la función elegida (el scroll del panel no lo
        informa solo) y la salida, para que nada quede cortado."""
        # La de la función más ancha, no la elegida: si no, cambiar de función movía el
        # punto en que la pestaña pasa de tres columnas a Cola / Vista previa.
        content = self.options_widget.panel.max_content_min_width()
        return max(self.RIGHT_COLUMN_MIN_WIDTH, content, self.output_card.minimumSizeHint().width())

    def _update_right_min_width(self):
        self._apply_mode_minimums()
        self._update_responsive_mode()

    def _apply_mode_minimums(self):
        if self._wide_mode:
            # Con espacio de sobra, la cola nunca más angosta que sus botones.
            self.queue_widget.setMinimumWidth(max(self.QUEUE_MIN_WIDTH, self.queue_widget.minimumSizeHint().width()))
            self.preview_widget.setMinimumWidth(self.PREVIEW_MIN_WIDTH)
            self.right_column.setMinimumWidth(self._right_min_width())
        else:
            self.queue_widget.setMinimumWidth(self.QUEUE_MIN_WIDTH)
            self.preview_widget.setMinimumWidth(self.NARROW_PREVIEW_MIN_WIDTH)
            self.right_column.setMinimumWidth(min(self._right_min_width(), self.NARROW_RIGHT_MIN_WIDTH))

    def _wide_threshold(self) -> int:
        handles = 2 * self.main_splitter.handleWidth()
        margins = self.layout().contentsMargins()
        return (max(self.QUEUE_MIN_WIDTH, self.queue_widget.minimumSizeHint().width())
                + self.PREVIEW_MIN_WIDTH + self._right_min_width()
                + handles + margins.left() + margins.right() + 20)

    def _on_left_view_changed(self, *_args):
        for index, button in enumerate(self.view_selector.buttons):
            if button.isChecked():
                self.left_stack.setCurrentIndex(index)
                return

    def _show_left_view(self, index: int):
        """0 = Cola, 1 = Vista previa (solo en la vista angosta)."""
        if not self._wide_mode and 0 <= index < len(self.view_selector.buttons):
            self.view_selector.buttons[index].click()

    def _update_responsive_mode(self):
        if not hasattr(self, "main_splitter") or self.width() <= 0:
            return
        want_wide = self.width() >= self._wide_threshold()
        if want_wide == self._wide_mode:
            # El reparto inicial pudo intentarse sin tamaño todavía (pestaña sin mostrar).
            if not self._layout_applied:
                self._apply_layout_sizes()
            return
        self._wide_mode = want_wide
        self._layout_applied = False
        self._apply_mode_minimums()
        if want_wide:
            self.main_splitter.insertWidget(0, self.queue_widget)
            self.main_splitter.insertWidget(1, self.preview_widget)
            # Al salir de la pila, la página que no se veía (y cualquier widget que cambia
            # de contenedor) queda oculta hasta mostrarla explícitamente.
            self.queue_widget.show()
            self.preview_widget.show()
            self.left_box.setParent(None)
            self.left_box.hide()
        else:
            self.left_stack.addWidget(self.queue_widget)
            self.left_stack.addWidget(self.preview_widget)
            self.main_splitter.insertWidget(0, self.left_box)
            self.left_box.show()
            self._on_left_view_changed()
        self._set_stretch()
        QTimer.singleShot(0, self._apply_layout_sizes)

    def showEvent(self, event):
        super().showEvent(event)
        # La pestaña se construye oculta y antes de que el tema termine de aplicarse a
        # sus controles: en ese momento las opciones se miden más angostas de lo que son
        # y elegía tres columnas, para pasar a Cola / Vista previa recién al tocar otra
        # función. Al mostrarse (ya con el estilo aplicado) se vuelve a decidir.
        QTimer.singleShot(0, self._update_right_min_width)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.StyleChange, QEvent.FontChange) and hasattr(self, "main_splitter"):
            QTimer.singleShot(0, self._update_right_min_width)

    def minimumSizeHint(self):
        """Siempre el piso del modo angosto, nunca el de las tres columnas: si no, Qt
        lo propagaría como mínimo de toda la ventana, que no podría achicarse hasta el
        punto en que esta pestaña pasa a dos columnas (mismo criterio que Multimedia,
        ver MediaWorkbenchTab.minimumSizeHint)."""
        base = QWidget.minimumSizeHint(self)
        margins = self.layout().contentsMargins()
        width = (max(self.QUEUE_MIN_WIDTH, self.NARROW_PREVIEW_MIN_WIDTH) + self.NARROW_RIGHT_MIN_WIDTH
                 + self.main_splitter.handleWidth() + margins.left() + margins.right())
        return QSize(width, base.height())

    def _apply_layout_sizes(self):
        total = sum(self.main_splitter.sizes())
        if total <= 0:
            return
        self._layout_applied = True
        saved = self._saved_layout()
        right = max(int(saved.get("options", self.RIGHT_COLUMN_WIDTH)), self._right_min_width())
        if self._wide_mode:
            queue = int(saved.get("queue", self.QUEUE_WIDTH))
            # Un ancho guardado enorme (ej. de una sesión con la ventana maximizada) no
            # puede dejar la vista previa por debajo de su mínimo.
            right = max(self._right_min_width(),
                        min(right, max(630, int(total * 0.35)), total - queue - self.PREVIEW_MIN_WIDTH))
            self.main_splitter.setSizes([queue, max(1, total - queue - right), right])
        else:
            left_min = max(self.QUEUE_MIN_WIDTH, self.NARROW_PREVIEW_MIN_WIDTH)
            right = max(self.right_column.minimumWidth(), min(right, self.RIGHT_COLUMN_WIDTH, total - left_min))
            self.main_splitter.setSizes([max(1, total - right), right])

    def _save_layout_sizes(self):
        sizes = self.main_splitter.sizes()
        if not sizes or sizes[-1] <= 0:
            return
        layout = self._saved_layout()
        layout["options"] = sizes[-1]
        if self._wide_mode and len(sizes) == 3 and sizes[0] > 0:
            layout["queue"] = sizes[0]
        config = get_config()
        config[self.LAYOUT_CONFIG_KEY] = layout
        save_config(config)

    def _reset_layout(self, which: str):
        layout = self._saved_layout()
        for key in ("queue", "options"):
            layout.pop(key, None)
        config = get_config()
        config[self.LAYOUT_CONFIG_KEY] = layout
        save_config(config)
        self._apply_layout_sizes()

    def _on_source_media(self, meta, filepath, new_file):
        self._source_meta = dict(meta or {})
        duration = self._parse_duration_to_seconds(self._source_meta.get("duración", "0"))
        if duration > 0:
            self.preview_widget.set_duration(duration)
        self._refresh_details()

    def _on_job_status(self, job_id: str, status: str):
        super()._on_job_status(job_id, status)
        # Al completarse la fila en vista previa, "Enviar al editor" pasa a tener qué enviar.
        self._refresh_editor_button()

    def _on_start_recoding_clicked(self):
        is_valid, reason = self.options_widget.get_current_status()
        if not is_valid:
            QMessageBox.warning(self, self.tr("Configuración no válida"), reason)
            return
        files = self.queue_widget.get_all_filepaths()
        if not files:
            QMessageBox.warning(self, self.tr("Sin archivos"),
                                self.tr("Agrega al menos un video a la cola para iniciar."))
            return
        out_dir = self.txt_output_dir.text().strip()
        same_path = self.chk_same_path.isChecked()
        if not same_path and (not out_dir or not os.path.exists(out_dir)):
            QMessageBox.warning(self, self.tr("Carpeta inválida"),
                                self.tr("Por favor selecciona una carpeta de salida válida."))
            return

        ia_settings = self.options_widget.get_ia_settings()
        recode_settings = self.options_widget.get_recode_settings()
        logger.info(f"AIToolsTab: Iniciando {ia_settings.get('ia_function')} para {len(files)} archivos"
                    f"{' + recodificación' if recode_settings else ''}. Misma ruta: {same_path}")
        if recode_settings:
            self._start_chained_jobs(files, ia_settings, recode_settings, out_dir, same_path)
        else:
            self._start_upscale_ia_jobs(files, ia_settings, out_dir, same_path)

    def start_tutorial(self):
        from gui.widgets.tutorial_overlay import TutorialOverlay
        steps = [
            {
                "title": self.tr("Herramientas IA"),
                "desc": self.tr("Reescala videos, o crea mapas de profundidad y de normales, con IA "
                                "que corre en tu equipo: sin suscripciones y sin subir tus archivos."),
                "widgets": [self.queue_widget],
            },
            {
                "title": self.tr("Vista Previa y Detalles"),
                "desc": self.tr("Revisa el video y sus datos. Para procesar solo una parte, haz clic "
                                "derecho y arrastra sobre la forma de onda; para cortes precisos o "
                                "varios tramos, usa la tijera: cada tramo entra a la cola por separado."),
                "widgets": [self.preview_widget],
            },
            {
                "title": self.tr("Función y Modelo"),
                "desc": self.tr("Elige la función, el motor y el modelo. Los modelos se descargan una "
                                "sola vez. Abajo puedes recodificar el resultado con un preajuste."),
                "widgets": [self.options_widget],
            },
            {
                "title": self.tr("Salida e Inicio"),
                "desc": self.tr("Elige la carpeta, el sufijo y la etiqueta, y pulsa iniciar. Si hay "
                                "otro proceso pesado en curso, la IA espera su turno."),
                "widgets": [self.output_card],
            },
        ]
        main_window = self.window()
        self.tutorial_overlay = TutorialOverlay(main_window, steps)
        self.tutorial_overlay.resize(main_window.size())
        self.tutorial_overlay.show()

    # ------------------------------------------------------------------
    # Vista previa y detalles
    # ------------------------------------------------------------------
    def _output_text(self) -> str:
        """Resolución que va a entregar la función de IA elegida, para los detalles."""
        match = re.match(r"(\d+)x(\d+)", str(self._source_meta.get("resolución", "")))
        if not match:
            return "-"
        width, height = int(match.group(1)), int(match.group(2))
        settings = self.options_widget.get_ia_settings() or {}
        if ia_function_of(settings) != FUNCTION_UPSCALE:
            # Los mapas salen a la resolución del original (redondeada a par).
            return f"{width - width % 2}x{height - height % 2}"
        digits = re.sub(r"[^0-9]", "", str(settings.get("upscale_scale") or ""))
        if not digits:
            return "-"
        scale = int(digits)
        return f"{width}x{height} → {width * scale}x{height * scale} (x{scale})"

    def _refresh_details(self):
        if self.preview_widget.current_path():
            self.preview_widget.set_details(self._source_meta, self._output_text())

    def _open_subclip_editor(self):
        """Tijera: el editor de subclips del Gestor. Con tramos guardados, cada uno
        reemplaza a la fila actual como fila propia (mismo archivo, su tramo y su nombre);
        sin tramos guardados, el rango marcado pasa a ser el tramo de la fila."""
        entry_key = self.current_preview_file
        path = self.preview_widget.current_path()
        duration = self.preview_widget.duration()
        if not entry_key or not path or duration <= 0:
            return
        from gui.dialogs.subclip_dialog import SubclipEditorDialog
        self.preview_widget.pause()
        trim = self.preview_widget.trim() or (0.0, duration)
        dlg = SubclipEditorDialog(
            media_path=path, media_type="video", duration_sec=duration,
            fps=self.preview_widget.fps(), existing_subclips=[],
            initial_in_sec=trim[0], initial_out_sec=trim[1],
            display_name=os.path.basename(path), parent=self,
        )
        dlg.exec()
        subclips = [sc for sc in dlg.get_subclips() if sc.get("out", 0) > sc.get("in", 0)]
        if subclips:
            items = [{
                "path": path, "in": sc["in"], "out": sc["out"], "has_trim": True,
                "name": os.path.basename(path), "clip_name": sc.get("name"),
            } for sc in subclips]
            self.queue_widget.remove_entries([entry_key])
            added = self.receive_media_from_editor(items)
            logger.info(f"{self.LOG_NAME}: {added} tramo(s) de '{os.path.basename(path)}' agregados a la cola.")
        elif dlg.out_sec > dlg.in_sec:
            self.preview_widget.set_range(dlg.in_sec, dlg.out_sec)

    def _current_output(self) -> str | None:
        key = self.current_preview_file
        return self.queue_widget.get_output_path(key) if key else None

    def _on_reveal_clicked(self):
        """Abre el resultado si la fila ya terminó; si no, el archivo de origen."""
        target = self._current_output() or self.preview_widget.current_path()
        if target and os.path.exists(target):
            from core.tabs.quick_mode.quick_mode_logic import reveal_in_file_manager
            reveal_in_file_manager(target)

    def _refresh_editor_button(self):
        from core.services.editor_integration_manager import EditorIntegrationManager
        editor_mgr = EditorIntegrationManager.get_instance()
        active = editor_mgr.active_editor if editor_mgr else None
        if not active:
            self.preview_widget.set_editor_state(self.tr("Ningún editor conectado"), False, QIcon())
            self.preview_widget.btn_send_editor.setToolTip("")
            return
        from gui.tabs.editing_media.editing_media_icons import get_svg_icon
        icon_file, name = {
            "premiere": ("premiere pro.svg", "Premiere Pro"),
            "aftereffects": ("after effects.svg", "After Effects"),
            "davinci": ("davinci resolve.svg", "DaVinci Resolve"),
        }.get(active, (None, "Editor"))
        if active == "vegas":
            from core.setup.vegas_setup import get_vegas_version_icon
            icon_file, name = get_vegas_version_icon(), "VEGAS Pro"
        icon = get_svg_icon(icon_file) if icon_file else QIcon()
        has_output = bool(self._current_output())
        self.preview_widget.set_editor_state(self.tr("Enviar a {0}").format(name), has_output, icon)
        self.preview_widget.btn_send_editor.setToolTip(
            "" if has_output else self.tr("Disponible cuando esta fila termine de procesarse."))

    def _on_send_to_editor_clicked(self):
        output = self._current_output()
        if not output:
            return
        from core.services.editor_integration_manager import EditorIntegrationManager
        editor_mgr = EditorIntegrationManager.get_instance()
        if not editor_mgr or not editor_mgr.active_editor:
            return
        package = {"video": output.replace("\\", "/"), "thumbnail": None, "subtitle": None}
        ok = editor_mgr.send_file(package)
        logger.info(f"{self.LOG_NAME}: Enviado al editor ({editor_mgr.active_editor}): {output} -> {ok}")

    # ------------------------------------------------------------------
    # Sufijo propio y editable (se recuerda)
    # ------------------------------------------------------------------
    def _load_saved_suffix(self):
        from core.utils.config_manager import get_config
        saved = get_config().get(f"{self.CONFIG_PREFIX}_suffix")
        if saved is not None:
            self.txt_suffix.setText(saved)

    def _save_suffix(self):
        from core.utils.config_manager import get_config, save_config
        config = get_config()
        config[f"{self.CONFIG_PREFIX}_suffix"] = self.txt_suffix.text()
        save_config(config)
