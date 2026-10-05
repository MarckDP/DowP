# src/gui/tabs/image_tools/depth_popover.py
"""Contenido del popover "Mapa de Profundidad (IA)" del Editor de Imagen.

Misma forma y mismas reglas que el de Eliminar Fondo (ver rembg_popover.py, que
explica cada decisión en detalle): Aceleración GPU (encendida por defecto en
Windows, APAGADA con aviso en macOS, oculta en Linux), Motor (familia), Modelo,
línea de estado con descarga en el sitio, y los botones Eliminar/Administrar.
Sin checkbox de "activar": con Motor y Modelo elegidos la función se aplica
(botón verde), con cualquiera de los dos en su placeholder, no.

Opciones propias:
  - Invertir: por defecto el mapa sale con "cerca = blanco" (la convención de
    DaVinci/Blender para desplazamiento); invertido, cerca = negro.
  - El ancho de bits (8 o 16) NO se elige aquí sino en las opciones de PNG y TIFF
    del panel Formato de salida (ver ConvertPanel._make_depth16_checkbox): es una
    propiedad del formato de guardado -- solo PNG y TIFF guardan 16 bits, y solo sin
    transparencia -- y tenerla también en este popover chocaba con el formato elegido.

La resolución a la que calcula cada modelo es fija a propósito (ver la nota de
DEPTH_MODEL_FAMILIES en core/constants.py) -- aquí solo se informa. La excepción es
MoGe-2 (el modelo de Mapa de Normales, que también da profundidad; ver
models_setup.get_depth_families): trabaja con su propio "Detalle", igual que en normales,
y solo se ofrece en el Editor de Imagen."""
import platform

from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QMessageBox, QWidget
from PySide6.QtCore import QCoreApplication, Signal, Qt, QTimer
from PySide6.QtGui import QFontMetrics

from gui.styles import get_theme_token
from gui.widgets.combo_box import AutoPopupComboBox
from gui.widgets.model_download_prompt import (
    ModelActionsRow, model_downloads, ModelStatusRow, confirm_model_download,
    format_model_label, open_models_settings,
)
from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon
from core.constants import AI_ENGINE_HOLDER, AI_MODEL_HOLDER
from core.setup.models_setup import (
    delete_depth_model, download_depth_model, get_depth_families, get_depth_model_license,
    get_depth_model_license_note, get_depth_model_size_bytes, is_depth_model_installed,
    is_depth_model_noncommercial,
)
from gui.styles import set_themed_style
from gui.styles import apply_shapes

_GPU_MACOS_WARNING = QCoreApplication.translate(
    "DepthPopoverContent",
    "En macOS, la aceleración por GPU (CoreML) no es confiable con todos los "
    "modelos de IA -- con los de Eliminar Fondo hay bugs conocidos de Apple "
    "(macOS 26.x) que pueden cerrar la app de golpe, y los de profundidad todavía "
    "no se han probado en Mac. La CPU sola ya rinde bien para esto.\n\n"
    "Puedes dejarla activada igual si quieres probar, pero si la app se cierra "
    "sola o se cuelga, vuelve a desmarcar esta opción."
)

_GPU_TOOLTIP = QCoreApplication.translate(
    "DepthPopoverContent",
    "Si está activo, usa la tarjeta gráfica (GPU).\n"
    "Si se desactiva, usará el procesador (CPU) a máxima potencia.\n"
    "Desactívalo si tienes problemas de drivers o cuelgues."
)
_DETAIL_TOOLTIP = QCoreApplication.translate(
    "DepthPopoverContent",
    "Cuánto detalle calcula el modelo. Más detalle tarda más y usa más memoria."
)
_RELIEF_TOOLTIP = QCoreApplication.translate(
    "DepthPopoverContent",
    "Además del mapa, guarda una malla 3D con la imagen como textura (.obj + .mtl + "
    "textura), para Blender o After Effects."
)
_RELIEF_MODE_TOOLTIP = QCoreApplication.translate(
    "DepthPopoverContent",
    "Relieve: una lámina empujada hacia adelante según la profundidad, para efectos de "
    "parallax. Sirve con cualquier modelo.\n"
    "Escena 3D: cada punto en su posición real, en metros, vista desde la cámara. Solo "
    "con MoGe-2. El cielo no se incluye."
)
_RELIEF_STRENGTH_TOOLTIP = QCoreApplication.translate(
    "DepthPopoverContent",
    "Cuánto sale hacia adelante lo más cercano. El modelo no sabe las distancias reales, "
    "así que se elige a ojo."
)
_RELIEF_DENSITY_TOOLTIP = QCoreApplication.translate(
    "DepthPopoverContent",
    "Cuántos vértices tiene la malla. Más densidad sigue mejor los detalles, pero el archivo "
    "pesa más. La textura siempre va a resolución completa."
)
_RELIEF_SPLIT_TOOLTIP = QCoreApplication.translate(
    "DepthPopoverContent",
    "Corta la malla donde la profundidad salta de golpe (por ejemplo, entre una persona y la "
    "pared de atrás). Así el sujeto queda despegado del fondo en vez de estirado, pero "
    "quedan huecos al mover la cámara."
)
_INVERT_TOOLTIP = QCoreApplication.translate(
    "DepthPopoverContent",
    "Por defecto lo cercano sale blanco y lo lejano negro.\n"
    "Marca esta opción si tu programa espera lo contrario."
)


class DepthPopoverContent(QFrame):
    """selection_changed(family_key, model_key, is_valid) -- ver
    RembgPopoverContent.selection_changed.

    video_mode=True: el mismo selector dentro de Herramientas IA de Herramientas
    Multimedia (ver upscale_ia_panel.py). Oculta la nota del ancho de bits, que es de
    las opciones de PNG/TIFF del Editor de Imagen (en video lo decide la casilla "16
    bits" del contenedor), y marca como "recomendado para video" las familias
    multivista (entrada "5d", hoy Depth Anything 3), que calculan varios fotogramas a la
    vez en una escala común y así no parpadean (ver video_depth_engine.py)."""
    selection_changed = Signal(str, str, bool)
    close_popover_requested = Signal()

    def __init__(self, parent=None, video_mode: bool = False):
        super().__init__(parent)
        self._video_mode = video_mode
        self.setObjectName("depthPopover")
        set_themed_style(self, lambda: f"""
            QFrame#depthPopover {{
                background-color: {get_theme_token('fondo_secundario', '#1e1e1e')};
                border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                border-radius: 8px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        self._label_widgets = []

        title = QLabel(self.tr("Mapa de Profundidad con IA"))
        title.setStyleSheet(apply_shapes("font-weight: bold; font-size: 13px;"))
        layout.addWidget(title)

        # Mismo criterio por SO que Eliminar Fondo (ver docstring de rembg_popover.py).
        if platform.system() != "Linux":
            self.check_gpu = QCheckBox(self.tr("Aceleración de Hardware (GPU)"))
            self.check_gpu.setChecked(platform.system() != "Darwin")
            self.check_gpu.setToolTip(_GPU_TOOLTIP)
            self.check_gpu.toggled.connect(self._on_gpu_toggled)
            layout.addWidget(self.check_gpu)
        else:
            self.check_gpu = None

        family_row = QHBoxLayout()
        family_row.addWidget(self._label(self.tr("Motor:")))
        self.combo_family = AutoPopupComboBox(fit_contents=True)
        self.combo_family.addItem(AI_ENGINE_HOLDER, None)
        for family_name, models in get_depth_families().items():
            if video_mode and any(m.get("engine") == "moge" for m in models.values()):
                continue    # MoGe-2 todavía no calcula profundidad en video
            label = family_name
            if video_mode and any(m.get("input_layout") == "5d" for m in models.values()):
                label = self.tr("{0} (recomendado para video)").format(family_name)
            self.combo_family.addItem(label, family_name)
        self.combo_family.currentIndexChanged.connect(self._on_family_changed)
        family_row.addWidget(self.combo_family, 1)
        layout.addLayout(family_row)

        model_row = QHBoxLayout()
        model_row.addWidget(self._label(self.tr("Modelo:")))
        self.combo_model = AutoPopupComboBox(fit_contents=True)
        self.combo_model.addItem(AI_MODEL_HOLDER, None)
        self.combo_model.currentIndexChanged.connect(self._on_model_changed)
        model_row.addWidget(self.combo_model, 1)
        layout.addLayout(model_row)

        # A qué resolución calcula el modelo elegido -- informativo, no editable.
        self.lbl_process = QLabel()
        self.lbl_process.setWordWrap(True)
        set_themed_style(self.lbl_process, lambda: f"color: {get_theme_token('texto_secundario', '#888888')}; font-size: 11px;")
        self.lbl_process.setVisible(False)
        layout.addWidget(self.lbl_process)

        # Licencia del modelo elegido: una línea pequeña (ver _update_license_label).
        self.lbl_license = QLabel()
        self.lbl_license.setVisible(False)
        layout.addWidget(self.lbl_license)

        # Claves de las descargas que lanzó ESTE popover: solo quien lanza una descarga
        # avisa con un diálogo si falla (ver ModelDownloadManager).
        self._started_here: set[str] = set()
        model_downloads().started.connect(self._on_download_started)
        model_downloads().progress_changed.connect(self._on_download_progress)
        model_downloads().finished.connect(self._on_download_finished)

        self.actions_row = ModelActionsRow(
            delete_tooltip=self.tr("Borrar del disco el modelo seleccionado"))
        self.actions_row.delete_requested.connect(self._on_delete_clicked)
        self.actions_row.manage_requested.connect(self._on_manage_clicked)
        layout.addWidget(self.actions_row)

        self.status_row = ModelStatusRow()
        self.status_row.clicked.connect(self._on_manage_clicked)
        layout.addWidget(self.status_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        set_themed_style(sep, lambda: f"background-color: {get_theme_token('borde_normal', '#2d2d2d')}; max-height: 1px; border: none;")
        layout.addWidget(sep)

        # Solo con MoGe-2: los demás modelos calculan a una resolución fija.
        self.row_detail = QWidget()
        detail_layout = QHBoxLayout(self.row_detail)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.addWidget(self._label(self.tr("Detalle:")))
        self.combo_detail = AutoPopupComboBox(fit_contents=True)
        self.combo_detail.setToolTip(_DETAIL_TOOLTIP)
        self.combo_detail.addItem(self.tr("Bajo (rápido)"), "low")
        self.combo_detail.addItem(self.tr("Medio"), "medium")
        self.combo_detail.addItem(self.tr("Alto (más detalle)"), "high")
        self.combo_detail.setCurrentIndex(1)
        detail_layout.addWidget(self.combo_detail, 1)
        self.row_detail.setVisible(False)
        layout.addWidget(self.row_detail)

        self.check_invert = QCheckBox(self.tr("Invertir (cerca = negro)"))
        self.check_invert.setToolTip(_INVERT_TOOLTIP)
        layout.addWidget(self.check_invert)

        # Malla 3D (.obj) -- solo en el Editor de Imagen (ver relief_mesh.py).
        self.check_relief = QCheckBox(self.tr("Exportar malla 3D (.obj)"))
        self.check_relief.setToolTip(_RELIEF_TOOLTIP)
        self.check_relief.setVisible(not video_mode)
        layout.addWidget(self.check_relief)

        self.relief_options = QWidget()
        relief_layout = QVBoxLayout(self.relief_options)
        relief_layout.setContentsMargins(0, 0, 0, 0)
        relief_layout.setSpacing(8)
        # Tipo de malla: solo con MoGe-2, el único modelo que da la escena en 3D.
        self.row_relief_mode = QWidget()
        mode_row = QHBoxLayout(self.row_relief_mode)
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.addWidget(self._label(self.tr("Tipo:")))
        self.combo_relief_mode = AutoPopupComboBox(fit_contents=True)
        self.combo_relief_mode.setToolTip(_RELIEF_MODE_TOOLTIP)
        self.combo_relief_mode.addItem(self.tr("Relieve"), "relief")
        self.combo_relief_mode.addItem(self.tr("Escena 3D"), "scene")
        self.combo_relief_mode.currentIndexChanged.connect(lambda _i: self._update_relief_rows())
        mode_row.addWidget(self.combo_relief_mode, 1)
        relief_layout.addWidget(self.row_relief_mode)
        self.row_relief_strength = QWidget()
        strength_row = QHBoxLayout(self.row_relief_strength)
        strength_row.setContentsMargins(0, 0, 0, 0)
        strength_row.addWidget(self._label(self.tr("Intensidad:")))
        self.combo_relief_strength = AutoPopupComboBox(fit_contents=True)
        self.combo_relief_strength.setToolTip(_RELIEF_STRENGTH_TOOLTIP)
        self.combo_relief_strength.addItem(self.tr("Suave"), "soft")
        self.combo_relief_strength.addItem(self.tr("Media"), "medium")
        self.combo_relief_strength.addItem(self.tr("Fuerte"), "strong")
        self.combo_relief_strength.setCurrentIndex(1)
        strength_row.addWidget(self.combo_relief_strength, 1)
        relief_layout.addWidget(self.row_relief_strength)
        density_row = QHBoxLayout()
        density_row.addWidget(self._label(self.tr("Densidad:")))
        self.combo_relief_density = AutoPopupComboBox(fit_contents=True)
        self.combo_relief_density.setToolTip(_RELIEF_DENSITY_TOOLTIP)
        self.combo_relief_density.addItem(self.tr("Baja (archivo liviano)"), "low")
        self.combo_relief_density.addItem(self.tr("Media"), "medium")
        self.combo_relief_density.addItem(self.tr("Alta (archivo pesado)"), "high")
        self.combo_relief_density.setCurrentIndex(1)
        density_row.addWidget(self.combo_relief_density, 1)
        relief_layout.addLayout(density_row)
        self.check_relief_split = QCheckBox(self.tr("Separar en los bordes"))
        self.check_relief_split.setToolTip(_RELIEF_SPLIT_TOOLTIP)
        relief_layout.addWidget(self.check_relief_split)
        self.relief_options.setVisible(False)
        self.check_relief.toggled.connect(self._on_relief_toggled)
        layout.addWidget(self.relief_options)

        lbl_bits = QLabel(self.tr(
            "El ancho de bits (8 o 16) se elige en las opciones de PNG y TIFF, "
            "en Formato de salida."))
        lbl_bits.setWordWrap(True)
        set_themed_style(lbl_bits, lambda: f"color: {get_theme_token('texto_secundario', '#888888')}; font-size: 11px;")
        lbl_bits.setVisible(not video_mode)
        layout.addWidget(lbl_bits)

    def showEvent(self, event):
        super().showEvent(event)
        # Un modelo pudo instalarse o borrarse desde Ajustes > Modelos mientras el
        # popover estaba cerrado.
        self._refresh_model_items()
        self._update_status()
        self._resize_label_column()

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        self._label_widgets.append(lbl)
        return lbl

    def _resize_label_column(self):
        fm = QFontMetrics(self.font())
        width = max(fm.horizontalAdvance(w.text()) for w in self._label_widgets) + 6
        for w in self._label_widgets:
            w.setFixedWidth(width)

    def _on_relief_toggled(self, checked: bool):
        self.relief_options.setVisible(checked)
        self._update_relief_rows()

    def _relief_mode(self) -> str:
        """"scene" solo si está elegido Y el modelo es MoGe-2; si no, siempre "relief"."""
        model_info = self._current_model_info()
        if model_info and model_info.get("engine") == "moge":
            return self.combo_relief_mode.currentData()
        return "relief"

    def _update_relief_rows(self):
        """"Tipo" solo con MoGe-2; "Intensidad" solo en Relieve (la escena ya viene a
        escala real)."""
        model_info = self._current_model_info()
        self.row_relief_mode.setVisible(bool(model_info) and model_info.get("engine") == "moge")
        self.row_relief_strength.setVisible(self._relief_mode() == "relief")

    def _on_gpu_toggled(self, checked: bool):
        """No impedimos, avisamos -- ver RembgPopoverContent._on_gpu_toggled."""
        if checked and platform.system() == "Darwin":
            QMessageBox.warning(self, self.tr("Aceleración por GPU en macOS"), _GPU_MACOS_WARNING)

    def _current_family_key(self):
        return self.combo_family.currentData()

    def _current_model_info(self):
        return get_depth_families().get(self._current_family_key(), {}).get(self.combo_model.currentData())

    def _on_family_changed(self, _index: int):
        self._refresh_model_items()
        self._update_status()
        self._emit_selection()

    def _refresh_model_items(self):
        """Repuebla el combo de modelos conservando la selección -- mismo
        esquema de iconos que RembgPopoverContent._refresh_model_items."""
        current = self.combo_model.currentData()
        self.combo_model.blockSignals(True)
        self.combo_model.clear()
        self.combo_model.addItem(AI_MODEL_HOLDER, None)
        for model_name, model_info in get_depth_families().get(self._current_family_key(), {}).items():
            if is_depth_model_installed(model_info):
                icon = get_colored_svg_icon(
                    "check_circle.svg", get_theme_token('estado_exito', '#40d66b'), size=14)
                tooltip = self.tr("Instalado")
            else:
                icon = get_colored_svg_icon(
                    "download.svg", get_theme_token('texto_secundario', '#888888'), size=14)
                tooltip = self.tr("No descargado")
            license_line = self.tr("Licencia: {0}").format(get_depth_model_license(model_info))
            tooltip = tooltip + " · " + license_line
            self.combo_model.addItem(
                icon, format_model_label(model_name, get_depth_model_size_bytes(model_info)), model_name)
            self.combo_model.setItemData(self.combo_model.count() - 1, tooltip, Qt.ToolTipRole)
        idx = self.combo_model.findData(current) if current else -1
        self.combo_model.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo_model.blockSignals(False)

    def _on_model_changed(self, _index: int):
        self._update_status()
        self._emit_selection()
        self._offer_download_if_missing(self._current_model_info())

    @staticmethod
    def _model_id(model_info: dict) -> str:
        """Clave estable de una descarga: carpeta + archivo principal (los dos
        Small de Depth Anything V2 comparten carpeta)."""
        return f"{model_info.get('folder', '')}/{model_info.get('file', '')}"

    def _update_process_label(self, model_info):
        self.row_detail.setVisible(bool(model_info) and model_info.get("engine") == "moge")
        self._update_relief_rows()
        if not model_info:
            self.lbl_process.setVisible(False)
            return
        if model_info.get("engine") == "moge":
            self.lbl_process.setText(self.tr(
                "Calcula la forma 3D de la escena y la amplía al tamaño original. Lo que no "
                "es superficie (el cielo) sale negro."))
            self.lbl_process.setVisible(True)
            return
        size = int(model_info.get("process_size") or 518)
        if model_info.get("process_mode") == "square":
            text = self.tr("Calcula la profundidad a {0}×{0} px (en cuadrado) y la amplía al "
                           "tamaño original.").format(size)
        else:
            text = self.tr("Calcula la profundidad con el lado corto a {0} px y la amplía al "
                           "tamaño original.").format(size)
        self.lbl_process.setText(text)
        self.lbl_process.setVisible(True)

    def _update_license_label(self, model_info):
        """Etiqueta pequeña con la licencia del modelo elegido. En gris si permite uso
        comercial; en ámbar y con "solo uso no comercial" si es CC BY-NC -- así se ve de
        un vistazo sin llenar el popover. Si el catálogo trae una aclaración
        ("license_note"), sale como tooltip."""
        license_name = get_depth_model_license(model_info) if model_info else ""
        if not license_name:
            self.lbl_license.setVisible(False)
            return
        if is_depth_model_noncommercial(model_info):
            text = self.tr("Licencia: {0} · solo uso no comercial").format(license_name)
            color = get_theme_token('estado_aviso', '#d8c94a')
        else:
            text = self.tr("Licencia: {0}").format(license_name)
            color = get_theme_token('texto_secundario', '#888888')
        self.lbl_license.setText(text)
        self.lbl_license.setStyleSheet(apply_shapes(f"color: {color}; font-size: 10px;"))
        self.lbl_license.setToolTip(get_depth_model_license_note(model_info))
        self.lbl_license.setVisible(True)

    def _update_status(self):
        model_info = self._current_model_info()
        self._update_process_label(model_info)
        self._update_license_label(model_info)
        if not model_info:
            self.status_row.clear()
            self.actions_row.set_delete_enabled(False)
            return
        downloading = model_downloads().is_downloading(self._model_id(model_info))
        # Borrar a media descarga dejaría el .part huérfano y el worker escribiendo
        # sobre un archivo recién borrado.
        self.actions_row.set_delete_enabled(is_depth_model_installed(model_info) and not downloading)
        if downloading:
            self.status_row.show_progress(model_downloads().progress(self._model_id(model_info)))
            return
        if is_depth_model_installed(model_info):
            self.status_row.show_ready(self.tr("Modelo listo para usar."))
        else:
            self.status_row.show_missing(self.tr(
                "No descargado — vuelve a elegirlo en la lista para descargarlo."))

    # ── Acciones sobre el modelo elegido ────────────────────────────────────
    def _on_manage_clicked(self):
        if open_models_settings(self):
            self.close_popover_requested.emit()

    def _on_delete_clicked(self):
        model_name = self.combo_model.currentData()
        model_info = self._current_model_info()
        if not model_info or not is_depth_model_installed(model_info):
            return
        pregunta = self.tr(
            "¿Eliminar '{0}' del disco?\n\nPuedes volver a descargarlo cuando quieras."
        ).format(model_name)
        if QMessageBox.question(self, self.tr("Eliminar modelo"), pregunta) != QMessageBox.Yes:
            return
        if not delete_depth_model(model_info):
            self.status_row.show_error(self.tr("No se pudo eliminar el modelo."))
            return
        self._refresh_model_items()
        self._update_status()
        self._emit_selection()

    # ── Descarga del modelo elegido ─────────────────────────────────────────
    def _offer_download_if_missing(self, model_info):
        """Ver RembgPopoverContent._offer_download_if_missing -- se difiere un
        ciclo de evento para no abrir el modal con el desplegable a medio cerrar."""
        if not model_info or is_depth_model_installed(model_info):
            return
        if model_downloads().is_downloading(self._model_id(model_info)):
            return
        model_name = self.combo_model.currentData()
        QTimer.singleShot(0, lambda: self._ask_and_download(model_name, model_info))

    def _ask_and_download(self, model_name: str, model_info: dict):
        model_id = self._model_id(model_info)
        if model_downloads().is_downloading(model_id) or is_depth_model_installed(model_info):
            self._update_status()
            return
        if self.combo_model.currentData() != model_name:
            return
        # Los CC BY-NC llevan el aviso en el propio diálogo de descarga, con el peso.
        extra_note = ""
        if is_depth_model_noncommercial(model_info):
            extra_note = self.tr("Licencia {0}: solo permite uso no comercial.").format(
                get_depth_model_license(model_info))
        accepted = confirm_model_download(
            self, model_name, get_depth_model_size_bytes(model_info), subject=self.tr("modelo"),
            extra_note=extra_note)
        if not accepted:
            self._update_status()
            return

        # Si ya se estaba bajando (lanzada desde otra pantalla), start() no hace nada
        # y el progreso llega igual por las señales del gestor.
        self._started_here.add(model_id)
        if not model_downloads().start(model_id, download_depth_model, model_info):
            self._started_here.discard(model_id)

    def _is_current_model(self, model_id: str) -> bool:
        model_info = self._current_model_info()
        return bool(model_info) and self._model_id(model_info) == model_id

    def _on_download_started(self, model_id: str):
        if self._is_current_model(model_id):
            self._update_status()

    def _on_download_progress(self, pct: int, model_id: str):
        if self._is_current_model(model_id):
            self.status_row.show_progress(pct)

    def _on_download_finished(self, success: bool, message: str, model_id: str):
        started_here = model_id in self._started_here
        self._started_here.discard(model_id)
        self._refresh_model_items()
        if success:
            self._update_status()
            return
        if self._is_current_model(model_id):
            self.status_row.show_error(self.tr("No se pudo descargar: {0}").format(message))
        if started_here:
            QMessageBox.warning(self, self.tr("Error de descarga"), message)

    # ── API para ImageToolsTab ──────────────────────────────────────────────
    def is_valid_selection(self) -> bool:
        return self.combo_family.currentData() is not None and self.combo_model.currentData() is not None

    def is_active(self) -> bool:
        return self.is_valid_selection()

    def deactivate(self):
        """Vuelve Motor a su placeholder -- la cascada limpia Modelo también."""
        self.combo_family.setCurrentIndex(0)

    def _emit_selection(self):
        family_key = self.combo_family.currentData()
        model_key = self.combo_model.currentData()
        self.selection_changed.emit(family_key or "", model_key or "", self.is_valid_selection())

    def gpu_enabled(self) -> bool:
        return self.check_gpu.isChecked() if self.check_gpu else False

    def get_settings(self) -> dict:
        """Ver RembgPopoverContent.get_settings() -- se aplica recién al apretar
        "Iniciar Proceso" (ImageToolsTab._on_convert_clicked ->
        ImageConverter._apply_depth)."""
        return {
            "depth_enabled": self.is_valid_selection(),
            "depth_family": self.combo_family.currentData(),
            "depth_model": self.combo_model.currentData(),
            "depth_gpu": self.gpu_enabled(),
            "depth_invert": self.check_invert.isChecked(),
            "depth_detail": self.combo_detail.currentData(),
            "depth_relief": self.check_relief.isChecked() and not self._video_mode,
            "depth_relief_mode": self._relief_mode(),
            "depth_relief_strength": self.combo_relief_strength.currentData(),
            "depth_relief_density": self.combo_relief_density.currentData(),
            "depth_relief_split": self.check_relief_split.isChecked(),
        }
