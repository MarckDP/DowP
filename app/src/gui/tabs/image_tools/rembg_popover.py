# src/gui/tabs/image_tools/rembg_popover.py
from PySide6.QtCore import QCoreApplication
"""Contenido del popover "Eliminar Fondo (IA)" del Editor de Imagen -- misma cascada y
mismos controles que usaba DowP 1 (image_tools_tab.pyc, rembg_master_frame/
rembg_options_frame, líneas 784-847): Aceleración GPU (checkbox, encendida por
defecto -- este SÍ tiene toggle GPU/CPU, a diferencia del reescalado que es siempre
GPU), Motor (así lo llamaba DowP 1, aunque en realidad es la FAMILIA del modelo:
Rembg Standard/BiRefNet/RMBG 2.0/InSPyReNet), Modelo, Suavizado (difumina el borde,
0-20px) y Exp/Contr (contrae/expande el recorte, -10..+10px).

Sin checkbox propio de "activar/desactivar" -- mismo criterio que upscale_popover.py:
mientras Motor y/o Modelo sigan en su placeholder, la función no se aplica (botón
gris); al elegir ambos, se aplica (botón verde). Sin botones Abrir/Borrar inline --
esos ya viven en Ajustes > Modelos (ver models_page.py); aquí solo se avisa si el
modelo elegido no está instalado o requiere descarga manual.

Aceleración GPU: encendida por defecto en Windows, APAGADA por defecto en
macOS, y directamente OCULTA en Linux. No son limitaciones arbitrarias:
- macOS: confirmado en pruebas reales (M3 y M5, ver memoria de proyecto) que
  CoreMLExecutionProvider puede crashear la app de golpe con estos modelos
  (RMBG 2.0/BiRefNet/InSPyReNet, todos con backbone Swin-Transformer). Ya se
  investigó la causa: son dos bugs de Apple sin arreglar en macOS 26.x
  (Tahoe), a nivel CoreML/Metal, no algo que se pueda mitigar desde aquí -- no
  hay opción de provider (tipo MLComputeUnits) que lo resuelva del todo. En
  Mac la CPU sola ya rinde bien para esto, así que el default seguro es
  apagado. No se lo bloqueamos al usuario si lo quiere prender igual -- "no
  impedimos, avisamos": marcarlo en macOS dispara un aviso, no lo deshabilita
  (ver _on_gpu_toggled).
- Linux: el checkbox ni se muestra. onnx_providers.py solo devuelve un
  provider de GPU real en Windows (DirectML) y macOS (CoreML) -- en Linux
  siempre corre CPUExecutionProvider sin importar este valor, porque no
  instalamos onnxruntime-gpu (ver memoria "DowP ONNX Runtime GPU strategy":
  el paquete CUDA pesa cientos de MB y solo beneficiaría a usuarios Nvidia,
  dejando a todos los demás pagando el peso sin beneficio). Mostrar un
  checkbox que no hace nada distinto sería engañoso, así que se oculta en vez
  de dejarlo marcado sin efecto.

Los modelos se descargan desde aquí mismo: elegir uno que no esté instalado abre el
diálogo de confirmación con su peso real (ver confirm_model_download en
gui/widgets/model_download_prompt.py) y, si se acepta, baja en segundo plano
mostrando el porcentaje en la línea de estado. Ya no hace falta ir a Ajustes >
Modelos y volver -- ahí sigue estando la gestión completa (reinstalar, borrar, ver
cuánto ocupan, importar .onnx propios), pero para el caso normal de "lo elegí y no lo
tengo" no hace falta salir de aquí. Los modelos gated (RMBG 2.0 con URL a una página
de HuggingFace, ver is_rembg_model_gated) siguen siendo la excepción: necesitan
cuenta, no hay descarga automática que ofrecer.

Solo selección: no dispara ningún procesamiento todavía, eso se conecta en un paso
aparte."""
import platform

from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QSlider, QMessageBox,
)
from PySide6.QtCore import Signal, Qt, QTimer
from PySide6.QtGui import QFontMetrics

from gui.styles import get_theme_token
from gui.widgets.combo_box import AutoPopupComboBox
from gui.widgets.model_download_prompt import (
    ModelActionsRow, ModelDownloadWorker, ModelStatusRow, confirm_model_download,
    format_model_label, open_models_settings,
)
from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon
from core.constants import AI_ENGINE_HOLDER, AI_MODEL_HOLDER
from core.setup.models_setup import (
    get_all_rembg_families, is_rembg_model_installed, is_rembg_model_gated,
    is_rembg_model_custom, is_rembg_model_orphaned,
    get_rembg_model_size_bytes, download_rembg_model, delete_rembg_model,
    delete_custom_rembg_model, CUSTOM_REMBG_FAMILY,
)

_GPU_MACOS_WARNING = QCoreApplication.translate(
    "RembgPopoverContent",
    "En macOS, la aceleración por GPU (CoreML) no es confiable con todos los "
    "modelos -- hay bugs conocidos y todavía sin arreglar de Apple (macOS 26.x) "
    "que pueden hacer que la app se cierre de golpe sin aviso al usar GPU con "
    "estos modelos (confirmado con RMBG 2.0/BiRefNet/InSPyReNet), no solo que "
    "tarde más o se quede colgada. La CPU sola ya rinde bien en Mac para esto.\n\n"
    "Puedes dejarla activada igual si quieres probar, pero si la app se cierra "
    "sola o se cuelga, vuelve a desmarcar esta opción."
)

_GPU_TOOLTIP = QCoreApplication.translate(
    "RembgPopoverContent",
    "Si está activo, usa la tarjeta gráfica (GPU).\n"
    "Si se desactiva, usará el procesador (CPU) a máxima potencia.\n"
    "Desactívalo si tienes problemas de drivers o cuelgues.\n\n"
    "La primera vez que se usa un modelo en esta sesión de DowP, la GPU compila "
    "el modelo antes de correr -- con modelos grandes (RMBG 2.0, InSPyReNet) esto "
    "puede tardar varios segundos y trabar la pantalla brevemente, es normal. "
    "En Ajustes > Modelos puedes marcar \"Mantener los modelos de IA cargados en "
    "memoria\" para pagar ese costo una sola vez por sesión en vez de en cada lote."
)
_SMOOTH_TOOLTIP = QCoreApplication.translate(
    "RembgPopoverContent",
    "Difumina el borde del recorte para una transición más suave.\n"
    "0 = sin suavizado, 20 = máximo difuminado."
)
_EXPAND_TOOLTIP = QCoreApplication.translate(
    "RembgPopoverContent",
    "Valores negativos contraen el recorte (elimina halos).\n"
    "Valores positivos expanden el recorte (recupera bordes cortados)."
)


class RembgPopoverContent(QFrame):
    """selection_changed(family_key, model_key, is_valid) -- model_key es el nombre
    amigable del modelo dentro de la familia elegida. is_valid es False mientras
    Motor y/o Modelo sigan en su placeholder."""
    selection_changed = Signal(str, str, bool)
    # Lo emite el botón "Administrar": el popover no sabe cerrarse solo (de eso se
    # encarga su PopoverTriggerButton), y dejarlo abierto detrás del modal de Ajustes
    # lo devolvería con el estado viejo -- el modelo pudo borrarse ahí mismo.
    close_popover_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("rembgPopover")
        bg = get_theme_token('fondo_secundario', '#1e1e1e')
        border = get_theme_token('borde_normal', '#2d2d2d')
        self.setStyleSheet(f"""
            QFrame#rembgPopover {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 8px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        self._label_widgets = []

        title = QLabel(self.tr("Eliminar Fondo con IA"))
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(title)

        # Aceleración por hardware -- a diferencia del reescalado (siempre GPU), rembg
        # sí corre por CPU si se desactiva. Default por SO (ver docstring del módulo):
        # encendida en Windows, apagada en macOS (CoreML no confiable con todos los
        # modelos -- no se bloquea, se avisa), oculta en Linux (no hay provider de
        # GPU real instalado ahí, mostrarla sería engañoso).
        if platform.system() != "Linux":
            self.check_gpu = QCheckBox(self.tr("Aceleración de Hardware (GPU)"))
            self.check_gpu.setChecked(platform.system() != "Darwin")
            self.check_gpu.setToolTip(_GPU_TOOLTIP)
            self.check_gpu.toggled.connect(self._on_gpu_toggled)
            layout.addWidget(self.check_gpu)
        else:
            self.check_gpu = None

        # Motor (familia del modelo)
        family_row = QHBoxLayout()
        family_row.addWidget(self._label(self.tr("Motor:")))
        self.combo_family = AutoPopupComboBox(fit_contents=True)
        self.combo_family.addItem(AI_ENGINE_HOLDER, None)
        self.combo_family.currentIndexChanged.connect(self._on_family_changed)
        family_row.addWidget(self.combo_family, 1)
        layout.addLayout(family_row)

        # Modelo
        model_row = QHBoxLayout()
        model_row.addWidget(self._label(self.tr("Modelo:")))
        self.combo_model = AutoPopupComboBox(fit_contents=True)
        self.combo_model.addItem(AI_MODEL_HOLDER, None)
        self.combo_model.currentIndexChanged.connect(self._on_model_changed)
        model_row.addWidget(self.combo_model, 1)
        layout.addLayout(model_row)

        # Estado del modelo elegido (listo / no descargado / descargando N% /
        # requiere cuenta). Las descargas en curso se guardan por clave de modelo:
        # el popover se esconde al clickear afuera, pero el QThread sigue vivo
        # mientras el widget exista -- volver a abrirlo tiene que reencontrar su
        # progreso, no arrancar de cero ni ofrecer bajar algo que ya se está bajando.
        self._downloads: dict[str, ModelDownloadWorker] = {}

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

        # Suavizado (feather del borde)
        smooth_row = QHBoxLayout()
        smooth_row.addWidget(self._label(self.tr("Suavizado:")))
        self.slider_smooth = QSlider(Qt.Horizontal)
        self.slider_smooth.setRange(0, 20)
        self.slider_smooth.setValue(0)
        self.slider_smooth.setToolTip(_SMOOTH_TOOLTIP)
        self.lbl_smooth_value = QLabel("0 px")
        self.lbl_smooth_value.setFixedWidth(40)
        self.lbl_smooth_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.slider_smooth.valueChanged.connect(
            lambda v: self.lbl_smooth_value.setText(f"{v} px")
        )
        smooth_row.addWidget(self.slider_smooth, 1)
        smooth_row.addWidget(self.lbl_smooth_value)
        layout.addLayout(smooth_row)

        # Exp/Contr (contrae o expande el recorte)
        expand_row = QHBoxLayout()
        expand_row.addWidget(self._label(self.tr("Exp/Contr:")))
        self.slider_expand = QSlider(Qt.Horizontal)
        self.slider_expand.setRange(-10, 10)
        self.slider_expand.setValue(0)
        self.slider_expand.setToolTip(_EXPAND_TOOLTIP)
        self.lbl_expand_value = QLabel("0 px")
        self.lbl_expand_value.setFixedWidth(40)
        self.lbl_expand_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.slider_expand.valueChanged.connect(self._on_expand_changed)
        expand_row.addWidget(self.slider_expand, 1)
        expand_row.addWidget(self.lbl_expand_value)
        layout.addLayout(expand_row)

        self._refresh_family_list()

    def _refresh_family_list(self):
        """Repuebla el combo de familias desde get_all_rembg_families() -- se llama
        en __init__ y cada vez que se abre el popover (ver showEvent), así un
        modelo importado en Ajustes > Modelos mientras DowP ya está corriendo
        aparece aquí sin tener que reiniciar la app."""
        current = self.combo_family.currentData()
        self.combo_family.blockSignals(True)
        self.combo_family.clear()
        self.combo_family.addItem(AI_ENGINE_HOLDER, None)
        for family_name in get_all_rembg_families().keys():
            self.combo_family.addItem(family_name, family_name)
        idx = self.combo_family.findData(current) if current else -1
        self.combo_family.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo_family.blockSignals(False)

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_family_list()
        # Igual que las familias: un modelo pudo instalarse (o borrarse) desde
        # Ajustes > Modelos mientras el popover estaba cerrado.
        self._refresh_model_items()
        self._update_status()

        self._resize_label_column()

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(self.tr(text))
        self._label_widgets.append(lbl)
        return lbl

    def _resize_label_column(self):
        fm = QFontMetrics(self.font())
        candidates = [w.text() for w in self._label_widgets]
        width = max(fm.horizontalAdvance(t) for t in candidates) + 6
        for w in self._label_widgets:
            w.setFixedWidth(width)

    def _on_gpu_toggled(self, checked: bool):
        """No impedimos, avisamos: marcar GPU en macOS no se bloquea, solo se
        advierte una vez por click (ver _GPU_MACOS_WARNING) -- el usuario decide."""
        if checked and platform.system() == "Darwin":
            QMessageBox.warning(self, self.tr("Aceleración por GPU en macOS"), self.tr(_GPU_MACOS_WARNING))

    def _on_expand_changed(self, v: int):
        sign = "+" if v > 0 else ""
        self.lbl_expand_value.setText(f"{sign}{v} px")

    def _current_family_key(self):
        return self.combo_family.currentData()

    def _on_family_changed(self, _index: int):
        self._refresh_model_items()
        self._update_status()
        self._emit_selection()

    def _refresh_model_items(self):
        """Repuebla el combo de modelos de la familia elegida, conservando la
        selección actual. El estado de cada modelo va como icono SVG teñido (listo /
        se puede descargar / requiere cuenta) y el peso en el tooltip, en vez de un
        candado emoji pegado al nombre: el emoji no se tiñe con el tema y se dibuja
        distinto (o no se dibuja) según la fuente de cada sistema."""
        current = self.combo_model.currentData()
        self.combo_model.blockSignals(True)
        self.combo_model.clear()
        self.combo_model.addItem(AI_MODEL_HOLDER, None)
        for model_name, model_info in get_all_rembg_families().get(self._current_family_key(), {}).items():
            if is_rembg_model_installed(model_info):
                icon = get_colored_svg_icon(
                    "check_circle.svg", get_theme_token('estado_exito', '#40d66b'), size=14)
                tooltip = self.tr("Instalado")
            elif is_rembg_model_orphaned(model_info):
                # Importado a mano y con el archivo ya borrado del disco. No lleva
                # icono de descarga: no hay nada de donde bajarlo, y ofrecerlo mandaba
                # al usuario a una descarga contra una URL vacía.
                icon = get_colored_svg_icon(
                    "warning.svg", get_theme_token('estado_aviso', '#d8c94a'), size=14)
                tooltip = self.tr("Archivo no encontrado — elimínalo de la lista")
            elif is_rembg_model_gated(model_info):
                icon = get_colored_svg_icon(
                    "login.svg", get_theme_token('estado_aviso', '#d8c94a'), size=14)
                tooltip = self.tr("Requiere descarga manual con cuenta")
            else:
                icon = get_colored_svg_icon(
                    "download.svg", get_theme_token('texto_secundario', '#888888'), size=14)
                tooltip = self.tr("No descargado")
            # El texto lleva el peso; el dato sigue siendo el nombre pelado, que es
            # con lo que rembg_engine busca el modelo (ver get_settings).
            self.combo_model.addItem(
                icon, format_model_label(model_name, get_rembg_model_size_bytes(model_info)), model_name)
            self.combo_model.setItemData(self.combo_model.count() - 1, tooltip, Qt.ToolTipRole)
        idx = self.combo_model.findData(current) if current else -1
        self.combo_model.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo_model.blockSignals(False)

    def _on_model_changed(self, _index: int):
        self._update_status()
        self._emit_selection()
        self._offer_download_if_missing(self._current_model_info())

    def _current_model_info(self):
        return get_all_rembg_families().get(self._current_family_key(), {}).get(
            self.combo_model.currentData())

    @staticmethod
    def _model_id(model_info: dict) -> str:
        """Clave estable de una descarga: carpeta + archivo destino. No sirve
        el nombre visible -- dos familias pueden ofrecer el mismo archivo (RMBG 2.0
        lo hace), y lo que se baja es el archivo."""
        return f"{model_info.get('folder', '')}/{model_info.get('file', '')}"

    def _update_status(self):
        model_info = self._current_model_info()
        if not model_info:
            self.status_row.clear()
            self.actions_row.set_delete_enabled(False)
            return
        downloading = self._model_id(model_info) in self._downloads
        # Borrar a media descarga dejaría el .part huérfano y el worker escribiendo
        # sobre un archivo recién borrado.
        #
        # Un importado sin archivo (huérfano) TAMBIÉN se puede borrar, aunque no esté
        # instalado: lo que se elimina entonces es su entrada en config.json, que es
        # justo lo que hay que poder quitar. Con la condición anterior —solo
        # is_rembg_model_installed()— el botón quedaba apagado y no había forma de
        # sacarlo de la lista.
        self.actions_row.set_delete_enabled(
            (is_rembg_model_installed(model_info) or is_rembg_model_orphaned(model_info))
            and not downloading)
        if downloading:
            # Descarga en curso: manda el porcentaje, no el estado en disco.
            return
        if is_rembg_model_installed(model_info):
            self.status_row.show_ready(self.tr("Modelo listo para usar."))
        elif is_rembg_model_orphaned(model_info):
            self.status_row.show_error(self.tr(
                "El archivo de este modelo importado ya no está en el disco. "
                "Elimínalo de la lista o vuelve a importarlo."
            ))
        elif is_rembg_model_gated(model_info):
            self.status_row.show_locked(self.tr(
                "Requiere descarga manual con cuenta — ve a Ajustes > Modelos."
            ), clickable=True)
        else:
            # Sin repetir el peso: ya está en el nombre del modelo, en el combo
            # de arriba (ver _refresh_model_items).
            self.status_row.show_missing(self.tr(
                "No descargado — vuelve a elegirlo en la lista para descargarlo."))

    # ── Acciones sobre el modelo elegido ────────────────────────────────────
    def _on_manage_clicked(self):
        """Salta a la gestión completa (descargar/reinstalar/importar/borrar) y
        cierra este popover: al volver de Ajustes su contenido podría estar de más
        viejo -- reabrirlo lo repuebla desde cero (ver showEvent)."""
        if open_models_settings(self):
            self.close_popover_requested.emit()

    def _on_delete_clicked(self):
        model_name = self.combo_model.currentData()
        model_info = self._current_model_info()
        # Un importado huérfano no está "instalado" y aun así debe poder eliminarse:
        # lo que se quita es su entrada en config.json.
        orphaned = model_info and is_rembg_model_orphaned(model_info)
        if not model_info or not (is_rembg_model_installed(model_info) or orphaned):
            return

        if orphaned:
            pregunta = self.tr(
                "El archivo de '{0}' ya no está en el disco.\n\n"
                "¿Quitarlo de la lista de modelos?").format(model_name)
        else:
            pregunta = self.tr(
                "¿Eliminar '{0}' del disco?\n\nPuedes volver a descargarlo cuando quieras."
            ).format(model_name)
        if QMessageBox.question(self, self.tr("Eliminar modelo"), pregunta) != QMessageBox.Yes:
            return

        # Los importados a mano no son solo un archivo: también tienen su entrada en
        # config.json, y borrar únicamente el .onnx dejaría el modelo listado y roto.
        if self._current_family_key() == CUSTOM_REMBG_FAMILY:
            ok = delete_custom_rembg_model(model_name)
            self._refresh_family_list()
        else:
            ok = delete_rembg_model(model_info)
        if not ok:
            self.status_row.show_error(self.tr("No se pudo eliminar el modelo."))
            return

        self._refresh_model_items()
        self._update_status()
        self._emit_selection()

    # ── Descarga del modelo elegido ─────────────────────────────────────────
    def _offer_download_if_missing(self, model_info):
        """Ofrece descargar el modelo que falta. Se difiere un ciclo de evento
        a propósito: esto sale de currentIndexChanged, con el desplegable del combo
        todavía cerrándose -- abrir un modal justo ahí deja el popup a medio cerrar
        por encima del diálogo."""
        if not model_info or is_rembg_model_installed(model_info) or is_rembg_model_gated(model_info):
            return
        # Un importado a mano no tiene URL: ofrecer descargarlo abría un diálogo que
        # solo podía acabar en error. Si falta su archivo, la salida es eliminarlo o
        # volver a importarlo, y eso ya lo dice _update_status().
        if is_rembg_model_custom(model_info):
            return
        if self._model_id(model_info) in self._downloads:
            return
        model_name = self.combo_model.currentData()
        QTimer.singleShot(0, lambda: self._ask_and_download(model_name, model_info))

    def _ask_and_download(self, model_name: str, model_info: dict):
        # Revalidar: entre el singleShot y este momento el usuario pudo cambiar de
        # modelo, o pudo terminar una descarga lanzada desde Ajustes > Modelos.
        model_id = self._model_id(model_info)
        if model_id in self._downloads or is_rembg_model_installed(model_info):
            self._update_status()
            return
        if self.combo_model.currentData() != model_name:
            return
        accepted = confirm_model_download(
            self, model_name, get_rembg_model_size_bytes(model_info), subject=self.tr("modelo"))
        if not accepted:
            self._update_status()
            return

        worker = ModelDownloadWorker(model_id, download_rembg_model, model_info, parent=self)
        worker.numeric_progress_signal.connect(self._on_download_progress)
        worker.finished_signal.connect(self._on_download_finished)
        self._downloads[model_id] = worker
        self.status_row.show_progress(0)
        worker.start()

    def _is_current_model(self, model_id: str) -> bool:
        model_info = self._current_model_info()
        return bool(model_info) and self._model_id(model_info) == model_id

    def _on_download_progress(self, pct: int, model_id: str):
        if self._is_current_model(model_id):
            self.status_row.show_progress(pct)

    def _on_download_finished(self, success: bool, message: str, model_id: str):
        worker = self._downloads.pop(model_id, None)
        if worker is not None:
            worker.deleteLater()
        self._refresh_model_items()
        if success:
            self._update_status()
            return
        if self._is_current_model(model_id):
            self.status_row.show_error(self.tr("No se pudo descargar: {0}").format(message))
        QMessageBox.warning(self, self.tr("Error de descarga"), message)

    def is_valid_selection(self) -> bool:
        return self.combo_family.currentData() is not None and self.combo_model.currentData() is not None

    def is_active(self) -> bool:
        """Ver UpscalePopoverContent.is_active()."""
        return self.is_valid_selection()

    def deactivate(self):
        """Vuelve Familia a su placeholder -- dispara selection_changed(is_valid=False)
        vía la cascada existente (_on_family_changed limpia Modelo también)."""
        self.combo_family.setCurrentIndex(0)

    def _emit_selection(self):
        family_key = self.combo_family.currentData()
        model_key = self.combo_model.currentData()
        self.selection_changed.emit(family_key or "", model_key or "", self.is_valid_selection())

    def current_selection(self) -> tuple[str, str]:
        return self.combo_family.currentData(), self.combo_model.currentData()

    def gpu_enabled(self) -> bool:
        return self.check_gpu.isChecked() if self.check_gpu else False

    def smooth_value(self) -> int:
        return self.slider_smooth.value()

    def expand_value(self) -> int:
        return self.slider_expand.value()

    def get_settings(self) -> dict:
        """Mismo criterio que UpscalePopoverContent.get_settings(): el popover
        solo junta la configuración, se aplica recién al apretar "Convertir" (ver
        ImageToolsTab._on_convert_clicked e ImageConverter._apply_rembg).
        rembg_enabled = is_valid_selection() -- mismo criterio que ya usa
        _style_rembg_button() para pintar el botón verde/gris."""
        return {
            "rembg_enabled": self.is_valid_selection(),
            "rembg_family": self.combo_family.currentData(),
            "rembg_model": self.combo_model.currentData(),
            "rembg_gpu": self.gpu_enabled(),
            "rembg_smooth": self.smooth_value(),
            "rembg_expand": self.expand_value(),
        }
