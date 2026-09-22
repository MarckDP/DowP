# src/gui/tabs/image_tools/normal_popover.py
"""Contenido del popover "Mapa de Normales (IA)" del Editor de Imagen.

Misma forma y mismas reglas que el de Mapa de Profundidad (ver depth_popover.py, que a su vez
sigue el de Eliminar Fondo, rembg_popover.py, donde está explicada cada decisión): Aceleración
GPU (encendida por defecto en Windows, APAGADA con aviso en macOS, oculta en Linux), Motor
(familia), Modelo, línea de estado con descarga en el sitio, licencia, y los botones
Eliminar/Administrar. Sin checkbox de "activar": con Motor y Modelo elegidos la función se
aplica (botón verde), con cualquiera de los dos en su placeholder, no.

Los dos motores del catálogo (ver NORMAL_MODEL_FAMILIES en core/constants.py) sirven para cosas
distintas, y por eso el popover muestra opciones distintas según el modelo elegido:
  - MoGe-2 (escenas): normales de una foto en el espacio de la cámara -> "Detalle".
  - DeepBump (texturas): normal map de un material plano -> "Solape" y "Textura repetible".
"Convención DirectX" vale para los dos.

Mapa de Profundidad y Mapa de Normales son excluyentes (los dos producen una imagen nueva que
reemplaza a la foto): ImageToolsTab apaga uno al encender el otro."""
import platform

from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QMessageBox, QWidget,
)
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
    delete_normal_model, download_normal_model, get_depth_model_license, get_depth_model_license_note,
    get_normal_families, get_normal_model_size_bytes, is_depth_model_noncommercial,
    is_normal_model_installed,
)

_GPU_MACOS_WARNING = QCoreApplication.translate(
    "NormalPopoverContent",
    "En macOS, la aceleración por GPU (CoreML) no es confiable con todos los "
    "modelos de IA -- con los de Eliminar Fondo hay bugs conocidos de Apple "
    "(macOS 26.x) que pueden cerrar la app de golpe, y los de normales todavía "
    "no se han probado en Mac. La CPU sola ya rinde bien para esto.\n\n"
    "Puedes dejarla activada igual si quieres probar, pero si la app se cierra "
    "sola o se cuelga, vuelve a desmarcar esta opción."
)
_GPU_TOOLTIP = QCoreApplication.translate(
    "NormalPopoverContent",
    "Si está activo, usa la tarjeta gráfica (GPU).\n"
    "Si se desactiva, usará el procesador (CPU) a máxima potencia.\n"
    "Desactívalo si tienes problemas de drivers o cuelgues."
)
_DIRECTX_TOOLTIP = QCoreApplication.translate(
    "NormalPopoverContent",
    "Por defecto se usa la convención OpenGL (Blender, DaVinci Resolve, Godot).\n"
    "Marca esta opción si tu programa espera DirectX, como Unreal Engine: "
    "invierte el canal verde."
)
_DETAIL_TOOLTIP = QCoreApplication.translate(
    "NormalPopoverContent",
    "Cuánto detalle calcula el modelo. Más detalle tarda más y usa más memoria."
)
_OVERLAP_TOOLTIP = QCoreApplication.translate(
    "NormalPopoverContent",
    "La textura se procesa por bloques de 256 px que se mezclan en la zona donde se "
    "solapan. Un solape mayor disimula mejor las uniones pero tarda más."
)
_TILEABLE_TOOLTIP = QCoreApplication.translate(
    "NormalPopoverContent",
    "Marca esta opción si la textura se repite en mosaico: sus bordes se calculan "
    "como continuación del lado opuesto, para que el resultado también encaje.\n"
    "Desmárcala para una imagen normal: en los bordes se refleja."
)


class NormalPopoverContent(QFrame):
    """selection_changed(family_key, model_key, is_valid) -- ver
    RembgPopoverContent.selection_changed."""
    selection_changed = Signal(str, str, bool)
    close_popover_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("normalPopover")
        bg = get_theme_token('fondo_secundario', '#1e1e1e')
        border = get_theme_token('borde_normal', '#2d2d2d')
        self.setStyleSheet(f"""
            QFrame#normalPopover {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 8px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        self._label_widgets = []

        title = QLabel(self.tr("Mapa de Normales con IA"))
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
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
        for family_name in get_normal_families().keys():
            self.combo_family.addItem(family_name, family_name)
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

        # Qué hace el motor elegido -- informativo, no editable.
        self.lbl_process = QLabel()
        self.lbl_process.setWordWrap(True)
        self.lbl_process.setStyleSheet(
            f"color: {get_theme_token('texto_secundario', '#888888')}; font-size: 11px;")
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
        sep.setStyleSheet(f"background-color: {border}; max-height: 1px; border: none;")
        layout.addWidget(sep)

        self.check_directx = QCheckBox(self.tr("DirectX (invertir verde)"))
        self.check_directx.setToolTip(_DIRECTX_TOOLTIP)
        layout.addWidget(self.check_directx)

        # Opciones de MoGe-2 (escenas)
        self.row_detail, detail_layout = self._option_row()
        detail_layout.addWidget(self._label(self.tr("Detalle:")))
        self.combo_detail = AutoPopupComboBox(fit_contents=True)
        self.combo_detail.setToolTip(_DETAIL_TOOLTIP)
        self.combo_detail.addItem(self.tr("Bajo (rápido)"), "low")
        self.combo_detail.addItem(self.tr("Medio"), "medium")
        self.combo_detail.addItem(self.tr("Alto (más detalle)"), "high")
        self.combo_detail.setCurrentIndex(1)
        detail_layout.addWidget(self.combo_detail, 1)
        layout.addWidget(self.row_detail)

        # Opciones de DeepBump (texturas)
        self.row_overlap, overlap_layout = self._option_row()
        overlap_layout.addWidget(self._label(self.tr("Solape:")))
        self.combo_overlap = AutoPopupComboBox(fit_contents=True)
        self.combo_overlap.setToolTip(_OVERLAP_TOOLTIP)
        self.combo_overlap.addItem(self.tr("Pequeño (rápido)"), "small")
        self.combo_overlap.addItem(self.tr("Medio"), "medium")
        self.combo_overlap.addItem(self.tr("Grande (más suave)"), "large")
        self.combo_overlap.setCurrentIndex(1)
        overlap_layout.addWidget(self.combo_overlap, 1)
        layout.addWidget(self.row_overlap)

        self.check_tileable = QCheckBox(self.tr("Textura repetible (sin costuras)"))
        self.check_tileable.setChecked(True)
        self.check_tileable.setToolTip(_TILEABLE_TOOLTIP)
        layout.addWidget(self.check_tileable)

        self._update_engine_options(None)

    def _option_row(self):
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        return row, row_layout

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

    def _on_gpu_toggled(self, checked: bool):
        """No impedimos, avisamos -- ver RembgPopoverContent._on_gpu_toggled."""
        if checked and platform.system() == "Darwin":
            QMessageBox.warning(self, self.tr("Aceleración por GPU en macOS"), _GPU_MACOS_WARNING)

    def _current_family_key(self):
        return self.combo_family.currentData()

    def _current_model_info(self):
        return get_normal_families().get(self._current_family_key(), {}).get(self.combo_model.currentData())

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
        for model_name, model_info in get_normal_families().get(self._current_family_key(), {}).items():
            if is_normal_model_installed(model_info):
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
                icon, format_model_label(model_name, get_normal_model_size_bytes(model_info)), model_name)
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
        """Clave estable de una descarga: carpeta + archivo principal."""
        return f"{model_info.get('folder', '')}/{model_info.get('file', '')}"

    def _update_engine_options(self, model_info):
        """Muestra solo las opciones del motor del modelo elegido: "Detalle" para
        MoGe-2 y "Solape"/"Textura repetible" para DeepBump. Sin modelo, ninguna."""
        engine = (model_info or {}).get("engine")
        self.row_detail.setVisible(engine == "moge")
        self.row_overlap.setVisible(engine == "deepbump")
        self.check_tileable.setVisible(engine == "deepbump")

    def _update_process_label(self, model_info):
        if not model_info:
            self.lbl_process.setVisible(False)
            return
        if model_info.get("engine") == "moge":
            text = self.tr("Calcula las normales de la escena (rojo = derecha, verde = arriba, "
                           "azul = hacia ti) y las amplía al tamaño original.")
        else:
            text = self.tr("Genera el relieve de una textura plana a partir de su brillo, por "
                           "bloques de 256 px. Sale a la resolución original.")
        self.lbl_process.setText(text)
        self.lbl_process.setVisible(True)

    def _update_license_label(self, model_info):
        """Etiqueta pequeña con la licencia del modelo elegido -- ver
        DepthPopoverContent._update_license_label."""
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
        self.lbl_license.setStyleSheet(f"color: {color}; font-size: 10px;")
        self.lbl_license.setToolTip(get_depth_model_license_note(model_info))
        self.lbl_license.setVisible(True)

    def _update_status(self):
        model_info = self._current_model_info()
        self._update_engine_options(model_info)
        self._update_process_label(model_info)
        self._update_license_label(model_info)
        if not model_info:
            self.status_row.clear()
            self.actions_row.set_delete_enabled(False)
            return
        downloading = model_downloads().is_downloading(self._model_id(model_info))
        # Borrar a media descarga dejaría el .part huérfano y el worker escribiendo
        # sobre un archivo recién borrado.
        self.actions_row.set_delete_enabled(is_normal_model_installed(model_info) and not downloading)
        if downloading:
            self.status_row.show_progress(model_downloads().progress(self._model_id(model_info)))
            return
        if is_normal_model_installed(model_info):
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
        if not model_info or not is_normal_model_installed(model_info):
            return
        pregunta = self.tr(
            "¿Eliminar '{0}' del disco?\n\nPuedes volver a descargarlo cuando quieras."
        ).format(model_name)
        if QMessageBox.question(self, self.tr("Eliminar modelo"), pregunta) != QMessageBox.Yes:
            return
        if not delete_normal_model(model_info):
            self.status_row.show_error(self.tr("No se pudo eliminar el modelo."))
            return
        self._refresh_model_items()
        self._update_status()
        self._emit_selection()

    # ── Descarga del modelo elegido ─────────────────────────────────────────
    def _offer_download_if_missing(self, model_info):
        """Ver RembgPopoverContent._offer_download_if_missing -- se difiere un
        ciclo de evento para no abrir el modal con el desplegable a medio cerrar."""
        if not model_info or is_normal_model_installed(model_info):
            return
        if model_downloads().is_downloading(self._model_id(model_info)):
            return
        model_name = self.combo_model.currentData()
        QTimer.singleShot(0, lambda: self._ask_and_download(model_name, model_info))

    def _ask_and_download(self, model_name: str, model_info: dict):
        model_id = self._model_id(model_info)
        if model_downloads().is_downloading(model_id) or is_normal_model_installed(model_info):
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
            self, model_name, get_normal_model_size_bytes(model_info), subject=self.tr("modelo"),
            extra_note=extra_note)
        if not accepted:
            self._update_status()
            return

        # Si ya se estaba bajando (lanzada desde otra pantalla), start() no hace nada
        # y el progreso llega igual por las señales del gestor.
        self._started_here.add(model_id)
        if not model_downloads().start(model_id, download_normal_model, model_info):
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
        ImageConverter._apply_normals). Las opciones de un motor se mandan aunque el
        modelo elegido sea del otro: el motor solo lee las suyas."""
        return {
            "normals_enabled": self.is_valid_selection(),
            "normals_family": self.combo_family.currentData(),
            "normals_model": self.combo_model.currentData(),
            "normals_gpu": self.gpu_enabled(),
            "normals_directx": self.check_directx.isChecked(),
            "normals_detail": self.combo_detail.currentData(),
            "normals_overlap": self.combo_overlap.currentData(),
            "normals_tileable": self.check_tileable.isChecked(),
        }
