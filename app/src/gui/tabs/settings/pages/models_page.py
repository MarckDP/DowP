# src/gui/tabs/settings/pages/models_page.py
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QScrollArea,
    QPushButton, QMessageBox, QProgressBar, QFileDialog, QDialog,
    QLineEdit, QSpinBox, QDialogButtonBox, QFormLayout, QSizePolicy, QCheckBox,
)
from PySide6.QtCore import Qt, QThread, QTimer, Signal, QUrl, QSize
from PySide6.QtGui import QDesktopServices
from core.utils.i18n import logger
from core.utils.cache_manager import format_bytes
from core.utils.paths import get_models_dir
from core.utils.config_manager import get_config, save_config
from core.constants import DEPTH_MODEL_FAMILIES, NORMAL_MODEL_FAMILIES, REMBG_MODEL_FAMILIES, UPSCALING_TOOLS
from core.setup.models_setup import (
    is_depth_model_installed, download_depth_model, delete_depth_model,
    get_depth_model_size_bytes, get_depth_model_disk_size, get_depth_model_path,
    get_depth_model_license, get_depth_model_license_note, is_depth_model_noncommercial,
    is_rembg_model_installed, is_rembg_model_gated, download_rembg_model, delete_rembg_model,
    is_upscaling_engine_installed, download_upscaling_engine, delete_upscaling_engine,
    get_folder_size, get_custom_rembg_models, import_custom_rembg_model,
    probe_onnx_input_size, get_rembg_model_path, relocate_custom_rembg_model,
    get_rembg_model_size_bytes, get_upscaling_engine_size_bytes,
)
from core.utils.onnx_providers import get_gpu_adapter_name, get_gpu_provider_label
from core.utils.hardware_detector import get_cached_gpu_name
from gui.widgets.toggle_switch import ToggleSwitch
from gui.widgets.mode_selector import ModeSelector
# Las descargas no se lanzan desde aquí sino desde el gestor común (model_downloads(),
# ver gui/widgets/model_download_prompt.py): los popovers del Editor de Imagen también
# descargan modelos, y así el progreso de cada descarga se ve en las dos pantallas.
from gui.widgets.model_download_prompt import format_model_label, model_download_key, model_downloads
from gui.styles import (
    register_theme_callback,
    get_theme_token,
    set_button_variant,
    apply_download_action_button_style,
    apply_folder_open_button_style,
    apply_folder_browse_button_style,
)
from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon
from gui.widgets.top_aligned_layout import TopAlignedVBoxLayout
from gui.styles import set_themed_style
from gui.styles import apply_shapes


class _ProbeInputSizeWorker(QThread):
    """Sondea el input_size de un .onnx en segundo plano (ver
    models_setup.probe_onnx_input_size) -- crear la InferenceSession para leer la
    forma del input puede tardar unos segundos con modelos grandes, no se puede
    hacer en el hilo de la UI sin trabar el diálogo de importación."""
    finished_signal = Signal(object)  # tuple[int, int] | None

    def __init__(self, onnx_path: str, parent=None):
        super().__init__(parent)
        self.onnx_path = onnx_path

    def run(self):
        self.finished_signal.emit(probe_onnx_input_size(self.onnx_path))


class ImportOnnxDialog(QDialog):
    """Diálogo de "Importar modelo ONNX" -- pide nombre visible y tamaño de
    entrada (NxN, mismo formato que "input_size" en REMBG_MODEL_FAMILIES),
    con un intento de auto-detección en segundo plano que el usuario siempre
    puede corregir a mano antes de confirmar."""

    def __init__(self, onnx_path: str, parent=None):
        super().__init__(parent)
        self.onnx_path = onnx_path
        self.setWindowTitle(self.tr("Importar modelo ONNX"))
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)

        info_lbl = QLabel(self.tr("Archivo: {0}").format(os.path.basename(onnx_path)))
        set_themed_style(info_lbl, lambda: f"color: {get_theme_token('texto_gris', '#AAAAAA')}; font-size: 11px;")
        info_lbl.setWordWrap(True)
        layout.addWidget(info_lbl)

        form = QFormLayout()
        default_name = os.path.splitext(os.path.basename(onnx_path))[0]
        self.entry_name = QLineEdit(default_name)
        form.addRow(self.tr("Nombre:"), self.entry_name)

        self.spin_size = QSpinBox()
        self.spin_size.setRange(64, 4096)
        self.spin_size.setSingleStep(32)
        self.spin_size.setValue(1024)
        self.spin_size.setSuffix(" px")
        form.addRow(self.tr("Tamaño de entrada (NxN):"), self.spin_size)
        layout.addLayout(form)

        self.lbl_probe = QLabel(self.tr("Detectando tamaño de entrada..."))
        set_themed_style(self.lbl_probe, lambda: f"color: {get_theme_token('texto_tenue', '#888888')}; font-size: 11px; font-style: italic;")
        self.lbl_probe.setWordWrap(True)
        layout.addWidget(self.lbl_probe)

        hint = QLabel(self.tr(
            "Si no se detecta solo, déjalo en 1024 (el más común en modelos "
            "modernos de Eliminar Fondo) o revisa la página de donde bajaste el "
            "modelo -- los legacy tipo U2Net suelen usar 320."
        ))
        hint.setWordWrap(True)
        set_themed_style(hint, lambda: f"color: {get_theme_token('texto_secundario', '#666666')}; font-size: 10px;")
        layout.addWidget(hint)

        # Por defecto DowP solo apunta al archivo donde está (sin duplicar el espacio).
        self.chk_copy = QCheckBox(self.tr("Copiar a la carpeta de modelos de DowP"))
        self.chk_copy.setToolTip(self.tr(
            "Útil si el archivo está en algo que luego borrarás o desconectarás (una "
            "descarga, una memoria USB). Sin marcar, DowP usa el archivo donde está."))
        layout.addWidget(self.chk_copy)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._probe_worker = _ProbeInputSizeWorker(onnx_path)
        self._probe_worker.finished_signal.connect(self._on_probe_done)
        self._probe_worker.start()

    def _on_probe_done(self, result):
        if result:
            height, width = result
            self.spin_size.setValue(max(height, width))
            self.lbl_probe.setText(self.tr("Tamaño detectado: {0}x{1}").format(height, width))
            set_themed_style(self.lbl_probe, lambda: f"color: {get_theme_token('estado_exito', '#4CAF50')}; font-size: 11px;")
        else:
            self.lbl_probe.setText(self.tr("No se pudo detectar el tamaño -- confírmalo a mano."))
            set_themed_style(self.lbl_probe, lambda: f"color: {get_theme_token('estado_aviso', '#FFC107')}; font-size: 11px;")

    def get_values(self) -> tuple[str, int, bool]:
        return self.entry_name.text().strip(), self.spin_size.value(), self.chk_copy.isChecked()

    def closeEvent(self, event):
        # El sondeo corre en un QThread aparte -- si el usuario cierra el diálogo
        # antes de que termine, hay que esperarlo un toque para no destruirlo
        # mientras sigue corriendo (Qt tira warning/crash con eso).
        if self._probe_worker.isRunning():
            self._probe_worker.wait(2000)
        super().closeEvent(event)


class ModelRow(QFrame):
    """Fila para un modelo rembg o un motor de upscaling. `gated=True`: modelo con
    licencia restringida en Hugging Face -- se descarga con la cuenta del usuario
    (token) o a mano, con "Abrir página" + "Ya lo descargué…"."""
    download_requested = Signal(str)        # row_id
    relocate_requested = Signal(str)        # row_id -- importado cuyo archivo se movió
    page_requested = Signal(str)            # row_id -- abrir su página en Hugging Face
    manual_install_requested = Signal(str)  # row_id -- elegir el archivo descargado a mano

    def __init__(self, row_id: str, title: str, path_for_size: str, gated: bool = False,
                 no_download: bool = False, installed_check=None, disk_size=None,
                 license_text: str = "", license_noncommercial: bool = False,
                 license_note: str = "", relocatable: bool = False, parent=None):
        super().__init__(parent)
        self.row_id = row_id
        self.path_for_size = path_for_size
        self.gated = gated
        # Para modelos que son VARIOS archivos (Mapa de Profundidad: .onnx +
        # model.onnx_data, ver models_setup.is_depth_model_installed): mirar solo
        # path_for_size daría por instalado un modelo a medio bajar, y medir la
        # carpeta sumaría el peso de otro modelo que la comparte. Sin estos dos,
        # la fila se comporta como siempre.
        self._installed_check = installed_check
        self._disk_size = disk_size
        # Etiqueta pequeña de licencia junto al nombre (solo modelos de profundidad, hoy).
        self._license_text = license_text
        self._license_noncommercial = license_noncommercial
        self._license_note = license_note
        # no_download: modelos importados a mano (ver _add_custom_row) -- ya están
        # instalados por definición (se copiaron al importar), no tiene sentido
        # ofrecer "Descargar"/"Reinstalar" para algo que no viene de una URL.
        self.no_download = no_download
        # Importados que apuntan al archivo del usuario: si ese archivo se movió, la
        # fila ofrece "Ubicar…" para elegir dónde está ahora.
        self.relocatable = relocatable
        self.setObjectName("settingsCard")
        self._build_ui(title)
        self.refresh_status()

    def _build_ui(self, title: str):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        info_vbox = QVBoxLayout()
        info_vbox.setSpacing(4)

        self.lbl_title = QLabel(title)
        set_themed_style(self.lbl_title, lambda: f"color: {get_theme_token('texto_activo', '#ffffff')}; font-weight: bold; font-size: 13px;")
        if self._license_text:
            title_row = QHBoxLayout()
            title_row.setSpacing(8)
            title_row.addWidget(self.lbl_title)
            self.lbl_license = QLabel(self._license_text)
            color = get_theme_token("estado_aviso", "#d8c94a") if self._license_noncommercial else get_theme_token('texto_tenue', '#888888')
            self.lbl_license.setStyleSheet(apply_shapes(f"color: {color}; font-size: 10px;"))
            self.lbl_license.setToolTip(self._license_note)
            title_row.addWidget(self.lbl_license, 0, Qt.AlignBottom)
            title_row.addStretch()
            info_vbox.addLayout(title_row)
        else:
            info_vbox.addWidget(self.lbl_title)

        self.lbl_status = QLabel()
        self.lbl_status.setStyleSheet(apply_shapes("font-size: 11px;"))
        info_vbox.addWidget(self.lbl_status)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.hide()
        info_vbox.addWidget(self.progress_bar)

        self.btn_relocate = None
        if self.relocatable:
            self.btn_relocate = QPushButton(self.tr("Ubicar…"))
            self.btn_relocate.setToolTip(self.tr("Elegir dónde está ahora el archivo de este modelo"))
            self.btn_relocate.setCursor(Qt.PointingHandCursor)
            self.btn_relocate.setFlat(True)
            set_themed_style(self.btn_relocate, lambda: f"""
                QPushButton {{ background: transparent; border: none; padding: 0px; text-align: left;
                               color: {get_theme_token('acento_primario', '#B9E640')}; font-size: 11px; font-weight: bold; }}
                QPushButton:hover {{ text-decoration: underline; }}
            """)
            self.btn_relocate.clicked.connect(lambda: self.relocate_requested.emit(self.row_id))
            self.btn_relocate.hide()
            info_vbox.addWidget(self.btn_relocate, 0, Qt.AlignLeft)

        layout.addLayout(info_vbox, 1)

        if self.gated:
            # Debajo del estado, como enlaces: al lado de los otros botones la fila
            # quedaba más ancha que el panel y empujaba toda la lista.
            links = QHBoxLayout()
            links.setContentsMargins(0, 2, 0, 0)
            links.setSpacing(14)
            self.btn_page = QPushButton(self.tr("Abrir página"))
            self.btn_page.setToolTip(self.tr("Abrir la página de este archivo en Hugging Face, para descargarlo a mano"))
            self.btn_manual = QPushButton(self.tr("Ya lo descargué…"))
            self.btn_manual.setToolTip(self.tr("Elegir el archivo que descargaste a mano: DowP lo copia a su carpeta"))
            for btn in (self.btn_page, self.btn_manual):
                btn.setCursor(Qt.PointingHandCursor)
                btn.setFlat(True)
                set_themed_style(btn, lambda: f"""
                    QPushButton {{ background: transparent; border: none; padding: 0px;
                                   color: {get_theme_token('acento_primario', '#B9E640')}; font-size: 11px; font-weight: bold; }}
                    QPushButton:hover {{ text-decoration: underline; }}
                    QPushButton:disabled {{ color: {get_theme_token('texto_deshabilitado', '#555555')}; }}
                """)
                links.addWidget(btn)
            links.addStretch()
            info_vbox.addLayout(links)
            self.btn_page.clicked.connect(lambda: self.page_requested.emit(self.row_id))
            self.btn_manual.clicked.connect(lambda: self.manual_install_requested.emit(self.row_id))

        self.btn_download = QPushButton()
        self.btn_download.setFixedSize(32, 32)
        self.btn_download.setCursor(Qt.PointingHandCursor)
        apply_download_action_button_style(self.btn_download, self.tr("Descargar"), icon_size=18)
        self.btn_download.clicked.connect(lambda: self.download_requested.emit(self.row_id))

        self.btn_folder = QPushButton()
        self.btn_folder.setFixedSize(32, 32)
        self.btn_folder.setCursor(Qt.PointingHandCursor)
        apply_folder_open_button_style(self.btn_folder, self.tr("Abrir carpeta"), icon_size=18)
        self.btn_folder.clicked.connect(self._open_folder)

        self.btn_delete = QPushButton(self.tr("Eliminar"))
        self.btn_delete.setFixedHeight(32)
        # Mínimo, no fijo: con la fuente y el relleno del tema, 80 px cortaba "Eliminar".
        self.btn_delete.setMinimumWidth(80)
        self.btn_delete.setCursor(Qt.PointingHandCursor)
        self.btn_delete.setProperty("variant", "danger")
        # Sin acción propia: quien crea la fila (ModelsPage) conecta este botón a su
        # callback de borrado, porque necesita saber si es un modelo rembg o un motor
        # de upscaling completo para llamar a la función de borrado correcta.

        if not self.no_download:
            layout.addWidget(self.btn_download, 0, Qt.AlignVCenter)
        layout.addWidget(self.btn_folder, 0, Qt.AlignVCenter)
        layout.addWidget(self.btn_delete, 0, Qt.AlignVCenter)

    def _folder_to_open(self) -> str:
        return self.path_for_size if os.path.isdir(self.path_for_size) else os.path.dirname(self.path_for_size)

    def _open_folder(self):
        folder = self._folder_to_open()
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def is_installed(self) -> bool:
        if self._installed_check is not None:
            return self._installed_check()
        return os.path.exists(self.path_for_size) and (
            os.path.isdir(self.path_for_size) or os.path.getsize(self.path_for_size) > 1024
        )

    def _set_download_icon(self, name):
        """El icono depende del estado (instalado o no): se guarda cuál es para volver a
        teñirlo al cambiar de tema sin recalcular el estado (medir la carpeta de un
        modelo puede tardar)."""
        self.btn_download.setIcon(get_colored_svg_icon(
            name, get_theme_token("boton_acento_texto", "#000000"), size=18,
            disabled_color_hex=get_theme_token("texto_deshabilitado", "#777777")))
        register_theme_callback(self.btn_download, "icono_tema", lambda: self._set_download_icon(name))

    def refresh_status(self):
        # Lo leen los resúmenes de las secciones/familias (ver ModelsPage._refresh_summaries).
        self.installed = False
        self.installed_bytes = 0
        self.downloading = False
        self.progress_pct = 0
        if self.btn_relocate is not None:
            self.btn_relocate.setVisible(not self.is_installed())
        # La ruta real a mano (los importados pueden estar en cualquier carpeta).
        self.lbl_status.setToolTip(self.path_for_size if self.no_download else "")
        if self.is_installed():
            size = self._disk_size() if self._disk_size is not None else get_folder_size(self.path_for_size)
            self.installed = True
            self.installed_bytes = size or 0
            self.lbl_status.setText(self.tr("Instalado ({0})").format(format_bytes(size)))
            set_themed_style(self.lbl_status, lambda: f"color: {get_theme_token('estado_exito', '#4CAF50')}; font-size: 11px; font-weight: bold;")
            if not self.no_download:
                self._set_download_icon("check_circle.svg")
                self.btn_download.setIconSize(QSize(18, 18))
                self.btn_download.setToolTip(self.tr("Instalado (clic para reinstalar)"))
            self.btn_folder.setDisabled(False)
            self.btn_delete.setDisabled(False)

        elif self.no_download:
            # Modelo importado a mano cuyo archivo ya no está en disco (el usuario lo
            # borró por fuera). No se puede "descargar" porque nunca vino de una URL,
            # así que lo único útil es poder quitarlo de la lista.
            #
            # El botón de eliminar TIENE que quedar activo. Apagarlo, como se hacía
            # antes al compartir esta rama con los modelos del catálogo, dejaba la
            # entrada huérfana de config.json imposible de borrar desde la interfaz:
            # el modelo seguía apareciendo en la lista para siempre.
            self.lbl_status.setText(
                self.tr("Archivo no encontrado — ubícalo o quítalo de la lista") if self.relocatable
                else self.tr("Archivo no encontrado — elimínalo de la lista"))
            set_themed_style(self.lbl_status, lambda: f"color: {get_theme_token('estado_aviso', '#FFC107')}; font-size: 11px; font-weight: bold;")
            self.btn_folder.setDisabled(False)
            self.btn_delete.setDisabled(False)

        else:
            self.lbl_status.setText(
                self.tr("No descargado · necesita tu cuenta de Hugging Face o descargarlo a mano")
                if self.gated else self.tr("No descargado"))
            set_themed_style(self.lbl_status, lambda: f"color: {get_theme_token('texto_tenue', '#888888')}; font-size: 11px;")
            self._set_download_icon("download.svg")
            self.btn_download.setIconSize(QSize(18, 18))
            self.btn_download.setToolTip(self.tr("Descargar"))
            self.btn_folder.setDisabled(True)
            self.btn_delete.setDisabled(True)

    def set_downloading(self, is_downloading: bool):
        self.downloading = is_downloading
        self.progress_pct = 0
        self.btn_download.setDisabled(is_downloading)
        if self.gated:
            self.btn_manual.setDisabled(is_downloading)
        self.btn_delete.setDisabled(is_downloading)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(is_downloading)
        if is_downloading:
            self.lbl_status.setText(self.tr("Descargando..."))
            set_themed_style(self.lbl_status, lambda: f"color: {get_theme_token('estado_aviso', '#FFC107')}; font-size: 11px; font-weight: bold;")
            self.btn_download.setToolTip(self.tr("Descargando..."))

    def set_progress(self, pct: int):
        self.progress_pct = pct
        self.progress_bar.setValue(pct)


class _CallWorker(QThread):
    """Corre una función (petición de red, copia de un archivo grande) fuera del hilo
    de la interfaz. Con with_progress=True, la función recibe un callback de %."""
    done = Signal(object)
    progress = Signal(int)

    def __init__(self, func, parent=None, with_progress: bool = False):
        super().__init__(parent)
        self._func, self._with_progress = func, with_progress
        # NO se borra con deleteLater(): con la función de Python que guarda (y que
        # apunta al diálogo o a la página), borrarlo hacía que PySide abortara la app
        # al conectar el token. Lo destruye su padre al cerrarse; pesa unos pocos KB.

    def run(self):
        try:
            result = self._func(self.progress.emit) if self._with_progress else self._func()
        except Exception as e:
            logger.error(f"Modelos IA: fallo en tarea de fondo: {e}")
            result = (False, str(e)) if self._with_progress else None
        self.done.emit(result)


class _HfTokenDialog(QDialog):
    """Pegar un token de acceso de Hugging Face (tipo "Read") y validarlo."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from core.setup import hf_auth
        self.setWindowTitle(self.tr("Conectar Hugging Face"))
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        step1 = QLabel(self.tr(
            "1. En tu cuenta de Hugging Face, crea un token de acceso de tipo «Read» "
            "(solo lectura). Si no tienes cuenta, puedes crearla gratis."))
        step1.setWordWrap(True)
        layout.addWidget(step1)
        btn_tokens = QPushButton(self.tr("Abrir página de tokens"))
        btn_tokens.setCursor(Qt.PointingHandCursor)
        btn_tokens.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(hf_auth.TOKENS_URL)))
        layout.addWidget(btn_tokens, 0, Qt.AlignLeft)

        step2 = QLabel(self.tr("2. Pégalo aquí:"))
        layout.addWidget(step2)
        self.edit_token = QLineEdit()
        self.edit_token.setPlaceholderText("hf_…")
        self.edit_token.setEchoMode(QLineEdit.Password)
        self.edit_token.setText(hf_auth.get_token())
        layout.addWidget(self.edit_token)

        note = QLabel(self.tr(
            "Además, cada modelo con licencia restringida pide aceptar sus condiciones una vez "
            "en su página; DowP te avisará cuando haga falta. El token se guarda en este equipo."))
        note.setWordWrap(True)
        set_themed_style(note, lambda: f"color: {get_theme_token('texto_tenue', '#888888')}; font-size: 11px;")
        layout.addWidget(note)

        self.lbl_error = QLabel()
        self.lbl_error.setWordWrap(True)
        self.lbl_error.hide()
        set_themed_style(self.lbl_error, lambda: f"color: {get_theme_token('estado_error', '#ff6b5f')}; font-size: 11px;")
        layout.addWidget(self.lbl_error)

        buttons = QHBoxLayout()
        buttons.addStretch()
        btn_cancel = QPushButton(self.tr("Cancelar"))
        btn_cancel.clicked.connect(self.reject)
        self.btn_ok = QPushButton(self.tr("Conectar"))
        set_button_variant(self.btn_ok, "accent-solid")
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self._on_connect)
        for b in (btn_cancel, self.btn_ok):
            b.setFixedHeight(32)
            b.setCursor(Qt.PointingHandCursor)
            buttons.addWidget(b)
        layout.addLayout(buttons)

    def _on_connect(self):
        from core.setup import hf_auth
        token = self.edit_token.text().strip()
        self.btn_ok.setEnabled(False)
        self.btn_ok.setText(self.tr("Comprobando…"))
        self.lbl_error.hide()
        worker = _CallWorker(lambda: hf_auth.validate_token(token), self)

        def finished(result):
            self.btn_ok.setEnabled(True)
            self.btn_ok.setText(self.tr("Conectar"))
            ok, value = result if result else (False, self.tr("No se pudo validar el token."))
            if ok:
                hf_auth.save_token(token, value)
                self.accept()
            else:
                self.lbl_error.setText(value)
                self.lbl_error.show()

        worker.done.connect(finished)
        self._worker = worker
        worker.start()


class _MoveModelsWorker(QThread):
    """Mueve los modelos a la carpeta nueva sin congelar la interfaz (pueden ser GB)."""
    progress = Signal(int)
    finished_move = Signal(bool, str)

    def __init__(self, src: str, dst: str, cancel_event, parent=None):
        super().__init__(parent)
        self.src, self.dst, self.cancel_event = src, dst, cancel_event

    def run(self):
        from core.setup.models_location import move_models
        try:
            ok, msg = move_models(self.src, self.dst, self.progress.emit, self.cancel_event)
        except Exception as e:
            ok, msg = False, str(e)
        self.finished_move.emit(ok, msg)


class _GroupHeader(QFrame):
    """Cabecera clicable de un grupo. Un QFrame y no un QPushButton: el botón calcula su
    alto por su propio texto e ignoraba el de los títulos de dentro (salían cortados)."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_Hover)
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class _ModelGroup(QWidget):
    """Sección (Eliminación de fondo, Profundidad...) o familia de modelos plegable: una
    cabecera clicable con flecha, título y un resumen a la derecha ("13 modelos · 2
    descargados · 2,1 GB"), y debajo el cuerpo con sus filas. Antes era una lista corrida
    de ~40 modelos en la que era fácil perderse."""

    toggled = Signal(str, bool)  # group_id, expandido

    def __init__(self, group_id: str, title: str, level: str, parent=None):
        super().__init__(parent)
        self.group_id = group_id
        self.level = level  # "section" | "family"
        self._expanded = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6 if level == "family" else 8)

        self.header = _GroupHeader(self)
        self.header.setObjectName("modelGroupHeader")
        set_themed_style(self.header, lambda: f"""
            QFrame#modelGroupHeader {{ background: transparent; border: none; border-radius: 6px; }}
            QFrame#modelGroupHeader:hover {{ background-color: {get_theme_token('fondo_hover', '#2a2a2a')}; }}
        """)
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(4, 4, 8, 4)
        header_layout.setSpacing(6)
        self.arrow = QLabel(self.header)
        self.arrow.setFixedSize(18, 18)
        self.lbl_title = QLabel(title, self.header)
        if level == "section":
            self.lbl_title.setObjectName("settingsSectionTitle")
        else:
            set_themed_style(self.lbl_title, lambda: f"color: {get_theme_token('texto_gris', '#aaaaaa')}; font-size: 12px; font-weight: bold;")
        self.lbl_summary = QLabel(self.header)
        set_themed_style(self.lbl_summary, lambda: f"color: {get_theme_token('texto_tenue', '#888888')}; font-size: 11px;")
        for w in (self.arrow, self.lbl_title, self.lbl_summary):
            # Los clics sobre los textos también pliegan/despliegan.
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
        header_layout.addWidget(self.arrow)
        header_layout.addWidget(self.lbl_title)
        header_layout.addStretch(1)
        header_layout.addWidget(self.lbl_summary)
        self.header.clicked.connect(lambda: self.set_expanded(not self._expanded, user=True))
        outer.addWidget(self.header)

        self.body = QWidget(self)
        self.body_layout = QVBoxLayout(self.body)
        # Las familias van un poco hacia adentro de su sección.
        self.body_layout.setContentsMargins(14 if level == "family" else 6, 0, 0, 4)
        self.body_layout.setSpacing(10)
        outer.addWidget(self.body)
        self._apply_expanded()
        register_theme_callback(self.arrow, "icono_tema", self._paint_arrow)

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool, user: bool = False):
        if expanded == self._expanded:
            return
        self._expanded = expanded
        self._apply_expanded()
        if user:
            self.toggled.emit(self.group_id, expanded)

    def _apply_expanded(self):
        self.body.setVisible(self._expanded)
        self._paint_arrow()

    def _paint_arrow(self):
        name = "arrow_drop_down.svg" if self._expanded else "arrow_right.svg"
        icon = get_colored_svg_icon(name, get_theme_token("texto_gris", "#aaaaaa"), size=18)
        self.arrow.setPixmap(icon.pixmap(18, 18))

    def set_summary(self, text: str):
        self.lbl_summary.setText(text)


class ModelsPage(QWidget):
    """Pestaña de Ajustes para descargar/gestionar modelos de IA (rembg, upscaling).
    Los modelos nunca se descargan solos -- solo cuando el usuario aprieta Descargar."""

    # Qué secciones y familias dejó abiertas el usuario (group_id -> bool). Todo empieza
    # plegado: la página tenía ~40 filas seguidas.
    _EXPANDED_CONFIG_KEY = "models_page_expanded"

    # (etiqueta del provider de GPU o None, nombre de la tarjeta o None) -- ver
    # _start_gpu_detection.
    _gpu_info_ready = Signal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: dict[str, ModelRow] = {}
        self.row_info: dict[str, dict] = {}          # row_id -> info dict (model_info / tool_info)
        self.row_kind: dict[str, str] = {}            # row_id -> "rembg" | "depth" | "normals" | "upscaling"
        # Claves (model_download_key) de las descargas lanzadas desde esta página:
        # solo quien lanza una descarga avisa con un diálogo si falla.
        self._started_here: set[str] = set()
        # Grupos plegables (secciones y familias) y a cuáles pertenece cada fila, para
        # los resúmenes de sus cabeceras y para abrirlos al llegar a un modelo.
        self._groups: dict[str, _ModelGroup] = {}
        self._row_groups: dict[str, list] = {}
        self._target_layout = None
        self._current_groups: list = []
        self._expanded_state = dict(get_config().get(self._EXPANDED_CONFIG_KEY) or {})
        self._build_ui()
        model_downloads().started.connect(self._on_download_started)
        model_downloads().progress_changed.connect(self._on_progress)
        model_downloads().finished.connect(self._on_download_finished)

    def _build_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(12)

        title_label = QLabel(self.tr("Modelos de Inteligencia Artificial"))
        title_label.setObjectName("settingsTitle")
        self.main_layout.addWidget(title_label)

        line = QFrame()
        line.setObjectName("settingsDivider")
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        self.main_layout.addWidget(line)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")

        scroll_content = QWidget()
        scroll_content.setObjectName("settingsScrollContent")
        scroll_content.setStyleSheet("QWidget#settingsScrollContent { background-color: transparent; }")

        self.content_layout = TopAlignedVBoxLayout(scroll_content)
        self.content_layout.setContentsMargins(0, 10, 10, 0)
        self.content_layout.setSpacing(10)

        # Todo dentro del scroll (nada fijo arriba): así la lista de modelos conserva su
        # alto. Secciones con el subtítulo común de Ajustes (settingsSectionTitle, el
        # mismo de "Aspecto" en General); las familias, en un tono neutro debajo.
        self._add_section_header(self.tr("Almacenamiento y cuenta"))
        self.content_layout.addWidget(self._build_models_dir_row())
        self.content_layout.addWidget(self._build_hf_account_row())

        self._add_section_header(self.tr("Memoria"))
        self.content_layout.addWidget(self._build_persist_sessions_row())
        self._max_sessions_row = self._build_max_sessions_row()
        self.content_layout.addWidget(self._max_sessions_row)

        # Modelos: secciones y familias plegables (ver _ModelGroup), con un resumen en
        # cada cabecera para no tener que abrirlas.
        self.content_layout.addWidget(self._build_filter_row())
        self.lbl_no_matches = QLabel(self.tr("Ningún modelo coincide con el filtro."))
        set_themed_style(self.lbl_no_matches, lambda: f"color: {get_theme_token('texto_secundario', '#666666')}; font-size: 11px; font-style: italic;")
        self.lbl_no_matches.hide()
        self.content_layout.addWidget(self.lbl_no_matches)

        section = self._begin_section("rembg", self.tr("Eliminación de Fondo (Rembg)"))
        for family_name, models in REMBG_MODEL_FAMILIES.items():
            self._begin_family(section, family_name)
            for model_name, model_info in models.items():
                self._add_rembg_row(model_name, model_info)

        section = self._begin_section("depth", self.tr("Mapas de Profundidad"))
        for family_name, models in DEPTH_MODEL_FAMILIES.items():
            self._begin_family(section, family_name)
            for model_name, model_info in models.items():
                self._add_depth_row(model_name, model_info)

        section = self._begin_section("normals", self.tr("Mapas de Normales"))
        for family_name, models in NORMAL_MODEL_FAMILIES.items():
            self._begin_family(section, family_name)
            for model_name, model_info in models.items():
                self._add_depth_row(model_name, model_info, kind="normals")

        self._begin_section("upscaling", self.tr("Motores de Reescalado (Upscaling)"))
        for engine_key, tool_info in UPSCALING_TOOLS.items():
            self._add_upscaling_row(engine_key, tool_info)

        self._custom_section = self._begin_section("custom", self.tr("Modelos Personalizados (Importados)"))
        import_row = QHBoxLayout()
        import_desc = QLabel(self.tr(
            "Para modelos ONNX de Eliminar Fondo que no están en el catálogo de arriba "
            "(por ejemplo, descargados a mano desde HuggingFace)."
        ))
        set_themed_style(import_desc, lambda: f"color: {get_theme_token('texto_tenue', '#888888')}; font-size: 11px;")
        import_desc.setWordWrap(True)
        import_row.addWidget(import_desc, 1)
        self.btn_import_custom = QPushButton(self.tr("Importar modelo ONNX..."))
        self.btn_import_custom.setFixedHeight(32)
        self.btn_import_custom.setCursor(Qt.PointingHandCursor)
        set_button_variant(self.btn_import_custom, "accent-solid")
        self.btn_import_custom.clicked.connect(self._on_import_custom_clicked)
        import_row.addWidget(self.btn_import_custom, 0, Qt.AlignVCenter)
        self._target_layout.addLayout(import_row)

        self.custom_rows_container = QVBoxLayout()
        self.custom_rows_container.setSpacing(10)
        self._target_layout.addLayout(self.custom_rows_container)
        self._target_layout = None
        self._refresh_custom_rows()

        scroll_area.setWidget(scroll_content)
        self.scroll_area = scroll_area
        self.main_layout.addWidget(scroll_area)
        self._refresh_summaries()

    def refresh_rows(self):
        """Relee de disco el estado de cada fila. Hace falta porque esta página
        se construye una sola vez al arrancar la app y ya no es la única que
        instala/borra modelos: los popovers del Editor de Imagen también lo hacen
        (ver gui/widgets/model_download_prompt.py). Sin esto, borrar un modelo ahí y
        entrar aquí lo seguiría mostrando como instalado."""
        for row_id, row in self.rows.items():
            row.refresh_status()
            # refresh_status mira el disco, donde una descarga en curso todavía no
            # está: sin esto la fila diría "No descargado" a media descarga.
            key = model_download_key(self.row_info[row_id])
            if model_downloads().is_downloading(key):
                row.set_downloading(True)
                row.set_progress(model_downloads().progress(key))
        self._refresh_custom_rows()
        self._refresh_summaries()

    # ── Carpeta de modelos ───────────────────────────────────────────────────
    def _build_models_dir_row(self) -> QWidget:
        """Dónde se guardan los modelos (pueden sumar varios GB): por defecto en el
        disco del sistema; el usuario puede elegir otra carpeta y mover lo que ya
        tiene descargado (ver core/setup/models_location.py). Mismo formato que el
        resto de rutas de la app (cookies, carpeta de salida): campo + botón de
        configurar ruta + botón de abrir carpeta."""
        container = QWidget()
        col = QVBoxLayout(container)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        lbl = QLabel(self.tr("Carpeta de modelos"))
        lbl.setObjectName("settingsLabel")
        col.addWidget(lbl)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.edit_models_dir = QLineEdit()
        self.edit_models_dir.setFixedHeight(32)
        self.edit_models_dir.setToolTip(self.tr("Escribe o pega una ruta y pulsa Enter, o usa el botón de la carpeta"))
        self.edit_models_dir.returnPressed.connect(self._on_models_dir_typed)
        row.addWidget(self.edit_models_dir, 1)

        self.btn_models_dir_change = QPushButton()
        self.btn_models_dir_change.setFixedSize(32, 32)
        self.btn_models_dir_change.setCursor(Qt.PointingHandCursor)
        apply_folder_browse_button_style(self.btn_models_dir_change, self.tr("Elegir otra carpeta para los modelos"))
        self.btn_models_dir_change.clicked.connect(self._on_models_dir_change)
        row.addWidget(self.btn_models_dir_change)

        self.btn_models_dir_open = QPushButton()
        self.btn_models_dir_open.setFixedSize(32, 32)
        self.btn_models_dir_open.setCursor(Qt.PointingHandCursor)
        apply_folder_open_button_style(self.btn_models_dir_open, self.tr("Abrir la carpeta de modelos"))
        self.btn_models_dir_open.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(get_models_dir())))
        row.addWidget(self.btn_models_dir_open)

        self.btn_models_dir_reset = QPushButton(self.tr("Restablecer"))
        self.btn_models_dir_reset.setFixedHeight(32)
        self.btn_models_dir_reset.setCursor(Qt.PointingHandCursor)
        self.btn_models_dir_reset.setToolTip(self.tr("Volver a la carpeta de siempre (en el disco del sistema)"))
        self.btn_models_dir_reset.clicked.connect(self._on_models_dir_reset)
        row.addWidget(self.btn_models_dir_reset)
        col.addLayout(row)

        self.lbl_models_dir = QLabel()
        self.lbl_models_dir.setWordWrap(True)
        col.addWidget(self.lbl_models_dir)
        self._refresh_models_dir_row()
        return container

    def _refresh_models_dir_row(self):
        from core.setup.models_location import free_space
        from core.utils.paths import get_custom_models_dir, is_models_dir_available
        path = get_models_dir()
        self.btn_models_dir_reset.setVisible(bool(get_custom_models_dir()))
        self.edit_models_dir.setText(path)
        self.edit_models_dir.setCursorPosition(0)
        if not is_models_dir_available():
            self.lbl_models_dir.setText(self.tr(
                "No está disponible (¿disco desconectado?). Conéctalo o elige otra carpeta."))
            set_themed_style(self.lbl_models_dir, lambda: f"color: {get_theme_token('estado_error', '#ff6b5f')}; font-size: 11px;")
            self.btn_models_dir_open.setEnabled(False)
            return
        self.btn_models_dir_open.setEnabled(True)
        used = get_folder_size(path)
        self.lbl_models_dir.setText(self.tr("Ocupan {0} · Libre en ese disco: {1}").format(
            format_bytes(used), format_bytes(free_space(path))))
        set_themed_style(self.lbl_models_dir, lambda: f"color: {get_theme_token('texto_tenue', '#888888')}; font-size: 11px;")

    def _on_models_dir_typed(self):
        """Ruta escrita o pegada a mano + Enter: mismo camino que elegirla con el botón."""
        from core.setup.models_location import resolve_target
        text = os.path.expanduser(self.edit_models_dir.text().strip().strip('"'))
        if not text or os.path.normcase(os.path.abspath(text)) == os.path.normcase(get_models_dir()):
            self._refresh_models_dir_row()
            return
        if self._models_busy():
            self._refresh_models_dir_row()
            return
        self._switch_models_dir(resolve_target(text))
        self._refresh_models_dir_row()  # si se canceló, vuelve a mostrar la actual

    def _models_busy(self) -> bool:
        """Mover la carpeta con una descarga en curso la dejaría a medias."""
        if getattr(model_downloads(), "_workers", None):
            QMessageBox.information(self, self.tr("Carpeta de modelos"), self.tr(
                "Hay una descarga de modelos en curso. Espera a que termine para cambiar la carpeta."))
            return True
        return False

    def _on_models_dir_change(self):
        from core.setup.models_location import resolve_target
        if self._models_busy():
            return
        chosen = QFileDialog.getExistingDirectory(self, self.tr("Elegir carpeta para los modelos de IA"),
                                                  os.path.expanduser("~"))
        if not chosen:
            return
        self._switch_models_dir(resolve_target(chosen))

    def _on_models_dir_reset(self):
        from core.utils.paths import get_default_models_dir
        if self._models_busy():
            return
        self._switch_models_dir(get_default_models_dir())

    def _switch_models_dir(self, target: str):
        from core.setup.models_location import has_models, validate_target, set_models_dir
        current = get_models_dir()
        ok, msg = validate_target(target, current)
        if not ok:
            QMessageBox.warning(self, self.tr("Carpeta de modelos"), msg)
            return

        if not has_models(current) or not os.path.isdir(current):
            set_models_dir(target)
            self._after_models_dir_changed()
            return

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle(self.tr("Carpeta de modelos"))
        box.setText(self.tr("Los modelos se guardarán en:\n{0}\n\n¿Qué hacemos con los que ya tienes descargados ({1})?")
                    .format(target, format_bytes(get_folder_size(current))))
        btn_move = box.addButton(self.tr("Moverlos ahí"), QMessageBox.AcceptRole)
        btn_empty = box.addButton(self.tr("Dejarlos y empezar vacía"), QMessageBox.DestructiveRole)
        box.addButton(self.tr("Cancelar"), QMessageBox.RejectRole)
        box.setDefaultButton(btn_move)
        box.exec()
        if box.clickedButton() is btn_empty:
            set_models_dir(target)
            self._after_models_dir_changed()
            return
        if box.clickedButton() is not btn_move:
            return
        self._move_models_to(current, target)

    def _move_models_to(self, current: str, target: str):
        import threading
        from PySide6.QtWidgets import QProgressDialog
        from core.setup.models_location import move_models, set_models_dir
        from core.utils import onnx_sessions

        # Un modelo cargado mantiene el archivo abierto: en Windows no se podría mover.
        onnx_sessions.clear_sessions()
        cancel_event = threading.Event()
        dialog = QProgressDialog(self.tr("Moviendo modelos…"), self.tr("Cancelar"), 0, 100, self)
        dialog.setWindowTitle(self.tr("Carpeta de modelos"))
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.canceled.connect(cancel_event.set)

        worker = _MoveModelsWorker(current, target, cancel_event, self)
        worker.progress.connect(dialog.setValue)

        def done(ok, msg):
            dialog.close()
            if ok:
                set_models_dir(target)
                self._after_models_dir_changed()
            else:
                QMessageBox.warning(self, self.tr("Carpeta de modelos"), msg)
                self._refresh_models_dir_row()

        worker.finished_move.connect(done)
        self._move_worker = worker
        worker.start()
        dialog.show()

    def _after_models_dir_changed(self):
        """Cada fila guardó su ruta al construirse: se recalcula con la carpeta nueva."""
        for row_id, row in self.rows.items():
            info, kind = self.row_info[row_id], self.row_kind[row_id]
            if kind in ("depth", "normals"):
                row.path_for_size = get_depth_model_path(info)
            elif kind == "upscaling":
                row.path_for_size = os.path.join(get_models_dir(), info["folder"])
            else:
                row.path_for_size = os.path.join(get_models_dir(), info["folder"], info["file"])
        self._refresh_models_dir_row()
        self.refresh_rows()
        model_downloads().models_changed.emit()

    # ── Cuenta de Hugging Face (modelos con licencia restringida) ───────────
    def _build_hf_account_row(self) -> QWidget:
        """Conectar la cuenta de Hugging Face con un token, para descargar RMBG 2.0 y
        otros modelos con licencia restringida (ver core/setup/hf_auth.py)."""
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        lbl = QLabel(self.tr("Cuenta de Hugging Face"))
        lbl.setObjectName("settingsLabel")
        text_col.addWidget(lbl)
        self.lbl_hf_status = QLabel()
        self.lbl_hf_status.setWordWrap(True)
        text_col.addWidget(self.lbl_hf_status)
        row.addLayout(text_col, 1)
        self.btn_hf_disconnect = QPushButton(self.tr("Desconectar"))
        self.btn_hf_disconnect.clicked.connect(self._on_hf_disconnect)
        self.btn_hf_connect = QPushButton()
        set_button_variant(self.btn_hf_connect, "accent-solid")
        self.btn_hf_connect.clicked.connect(lambda: self._connect_hf_account())
        for btn in (self.btn_hf_disconnect, self.btn_hf_connect):
            btn.setFixedHeight(32)
            btn.setCursor(Qt.PointingHandCursor)
            row.addWidget(btn, 0, Qt.AlignVCenter)
        self._refresh_hf_row()
        return container

    def _refresh_hf_row(self):
        from core.setup import hf_auth
        connected = bool(hf_auth.get_token())
        user = hf_auth.get_username()
        if connected:
            self.lbl_hf_status.setText(
                self.tr("Conectada como {0}.").format(user) if user else self.tr("Conectada."))
            set_themed_style(self.lbl_hf_status, lambda: f"color: {get_theme_token('estado_exito', '#40d66b')}; font-size: 11px;")
        else:
            self.lbl_hf_status.setText(self.tr(
                "Sin conectar. Hace falta para descargar desde DowP los modelos con licencia "
                "restringida (como RMBG 2.0); también puedes descargarlos a mano."))
            set_themed_style(self.lbl_hf_status, lambda: f"color: {get_theme_token('texto_tenue', '#888888')}; font-size: 11px;")
        self.btn_hf_connect.setText(self.tr("Cambiar token…") if connected else self.tr("Conectar…"))
        self.btn_hf_disconnect.setVisible(connected)

    def _connect_hf_account(self) -> bool:
        """Diálogo para pegar el token. True si quedó conectada."""
        dialog = _HfTokenDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return False
        self._refresh_hf_row()
        return True

    def _on_hf_disconnect(self):
        from core.setup import hf_auth
        if QMessageBox.question(self, self.tr("Cuenta de Hugging Face"), self.tr(
                "¿Desconectar la cuenta? Se borra el token guardado en DowP. Los modelos "
                "ya descargados no se tocan.")) != QMessageBox.Yes:
            return
        hf_auth.save_token("")
        self._refresh_hf_row()

    def _run_in_background(self, func, on_done, busy_text: str):
        """Corre `func` (una petición de red) sin congelar la interfaz."""
        from PySide6.QtWidgets import QProgressDialog
        dialog = QProgressDialog(busy_text, None, 0, 0, self)
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(400)
        dialog.setCancelButton(None)
        worker = _CallWorker(func, self)

        def finished(result):
            dialog.close()
            on_done(result)

        worker.done.connect(finished)
        self._bg_worker = worker
        worker.start()

    def _start_gated_download(self, row_id: str):
        """Antes de descargar un modelo restringido se comprueba el acceso, para dar
        el paso concreto que falte en vez de un error de descarga."""
        from core.setup import hf_auth
        info = self.row_info[row_id]

        def done(access):
            if access == hf_auth.ACCESS_OK:
                key = model_download_key(info)
                self._started_here.add(key)
                if not model_downloads().start(key, download_rembg_model, info):
                    self._started_here.discard(key)
                return
            if access in (hf_auth.ACCESS_NO_TOKEN, hf_auth.ACCESS_INVALID_TOKEN):
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Information)
                box.setWindowTitle(self.tr("Cuenta de Hugging Face"))
                if access == hf_auth.ACCESS_INVALID_TOKEN:
                    box.setText(self.tr("El token guardado ya no es válido. Conecta tu cuenta de nuevo para descargarlo."))
                else:
                    box.setText(self.tr(
                        "Este modelo tiene licencia restringida: para descargarlo desde DowP hay que "
                        "conectar tu cuenta de Hugging Face (gratis). También puedes descargarlo a mano."))
                btn_connect = box.addButton(self.tr("Conectar cuenta"), QMessageBox.AcceptRole)
                btn_manual = box.addButton(self.tr("Descargar a mano"), QMessageBox.ActionRole)
                box.addButton(self.tr("Cancelar"), QMessageBox.RejectRole)
                box.exec()
                if box.clickedButton() is btn_connect:
                    if self._connect_hf_account():
                        self._start_gated_download(row_id)
                elif box.clickedButton() is btn_manual:
                    self._on_page_requested(row_id)
                return
            if access == hf_auth.ACCESS_NEEDS_LICENSE:
                user = hf_auth.get_username()
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Information)
                box.setWindowTitle(self.tr("Aceptar la licencia"))
                box.setText(self.tr(
                    "Tu cuenta{0} todavía no aceptó la licencia de este modelo.\n\n"
                    "Se abrirá su página en Hugging Face: inicia sesión con esa misma cuenta, "
                    "acepta las condiciones y vuelve a pulsar Descargar.").format(f" ({user})" if user else ""))
                btn_open = box.addButton(self.tr("Abrir página"), QMessageBox.AcceptRole)
                box.addButton(self.tr("Cancelar"), QMessageBox.RejectRole)
                box.exec()
                if box.clickedButton() is btn_open:
                    QDesktopServices.openUrl(QUrl(hf_auth.license_page_url(info)))
                return
            QMessageBox.warning(self, self.tr("Error de Descarga"), self.tr(
                "No se pudo conectar con Hugging Face. Revisa tu conexión e inténtalo de nuevo."))

        self._run_in_background(lambda: hf_auth.check_access(info), done,
                                self.tr("Comprobando el acceso en Hugging Face…"))

    def _on_page_requested(self, row_id: str):
        from core.setup import hf_auth
        info = self.row_info[row_id]
        QDesktopServices.openUrl(QUrl(hf_auth.file_page_url(info)))

    def _on_manual_install_requested(self, row_id: str):
        from PySide6.QtWidgets import QProgressDialog
        from core.setup.models_setup import install_manual_model
        from PySide6.QtCore import QStandardPaths
        info = self.row_info[row_id]
        start = QStandardPaths.writableLocation(QStandardPaths.DownloadLocation) or os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Elegir «{0}» descargado").format(info["file"]), start,
            self.tr("Modelos ONNX (*.onnx)"))
        if not path:
            return
        dialog = QProgressDialog(self.tr("Instalando modelo…"), None, 0, 100, self)
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(300)
        dialog.setCancelButton(None)
        worker = _CallWorker(lambda progress: install_manual_model(info, path, progress), self, with_progress=True)
        worker.progress.connect(dialog.setValue)

        def finished(result):
            dialog.close()
            ok, msg = result
            row = self.rows.get(row_id)
            if row:
                row.refresh_status()
            if not ok:
                QMessageBox.warning(self, self.tr("No se pudo instalar"), msg)

        worker.done.connect(finished)
        self._bg_worker = worker
        worker.start()

    # ── Mantener modelos en memoria ─────────────────────────────────────────
    def _build_persist_sessions_row(self) -> QWidget:
        """Fila de "Mantener los modelos en memoria": switch + botón para liberar
        a mano, con la misma forma que el resto de Ajustes (etiqueta y descripción a
        la izquierda, control a la derecha -- ver downloads_page.py).

        Lo que decide el switch es cuánto vive la sesión ONNX, no dónde: apagado, el
        modelo se carga al empezar cada lote de "Convertir" y se libera apenas termina
        (ver ImageConvertWorker.run / rembg_engine.prepare_session / clear_sessions);
        encendido, queda cargado entre lotes y el siguiente arranca sin volver a pagar
        la carga inicial -- que son varios segundos con los modelos grandes, los
        mismos segundos por CPU que por GPU.

        Por eso NO se condiciona a que haya GPU: el ahorro existe igual corriendo por
        CPU (cargar 900 MB de pesos y construir el grafo cuesta lo suyo en cualquier
        caso), y en Linux, donde a propósito nunca hay provider de GPU, deshabilitarlo
        dejaría sin la opción justo a quien más tarda.

        La detección de hardware entra solo para redactar: get_gpu_provider_label()
        (core/utils/onnx_providers.py, la misma función que arma la sesión de verdad)
        dice si el modelo va a vivir en la GPU o en la RAM, y get_cached_gpu_name()
        (core/utils/hardware_detector.py, leído de la config, sin lanzar un escaneo
        que tarda segundos) pone el nombre de la tarjeta. Ninguna de las dos habilita
        ni deshabilita nada."""
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self.lbl_persist = QLabel(self.tr("Mantener los modelos de IA cargados en memoria"))
        self.lbl_persist.setObjectName("settingsLabel")
        text_col.addWidget(self.lbl_persist)

        self.lbl_persist_desc = QLabel()
        self.lbl_persist_desc.setWordWrap(True)
        set_themed_style(self.lbl_persist_desc, lambda: f"color: {get_theme_token('texto_tenue', '#888888')}; font-size: 11px;")
        text_col.addWidget(self.lbl_persist_desc)
        row.addLayout(text_col, 1)

        self.switch_persist = ToggleSwitch()
        self.switch_persist.toggled.connect(self._on_persist_sessions_toggled)
        row.addWidget(self.switch_persist, 0, Qt.AlignVCenter)

        # "Liberar" solo tiene algo que hacer con la opción encendida: apagada, el
        # modelo ya se libera solo al terminar cada lote.
        self.btn_free_memory = QPushButton(self.tr("Liberar"))
        self.btn_free_memory.setFixedHeight(32)
        self.btn_free_memory.setCursor(Qt.PointingHandCursor)
        set_button_variant(self.btn_free_memory, "accent-solid")
        self.btn_free_memory.setToolTip(self.tr(
            "Descargar ahora los modelos que queden cargados, estén en la memoria de "
            "la GPU o en la RAM, sin cerrar la aplicación"))
        self.btn_free_memory.clicked.connect(self._on_free_memory_clicked)
        row.addWidget(self.btn_free_memory, 0, Qt.AlignVCenter)

        # Se sabe recién cuando termina _start_gpu_detection; hasta entonces la
        # descripción queda vacía (es cuestión de una fracción de segundo).
        self._gpu_label = None
        self._gpu_name = None
        self._gpu_known = False
        self.switch_persist.setChecked(bool(get_config().get("rembg_persist_sessions", False)))
        self._refresh_persist_row()
        self._start_gpu_detection()
        return container

    def _start_gpu_detection(self):
        """Pregunta en otro hilo qué GPU va a usar la inferencia. Hacerlo aquí mismo
        importaba onnxruntime y enumeraba las tarjetas en el hilo principal: ~1 s con la
        interfaz congelada en el compilado, solo para redactar una frase."""
        import threading

        def detect():
            label = name = None
            try:
                label = get_gpu_provider_label()
                # El adaptador elegido antes que el nombre cacheado del escaneo: en un
                # equipo con dos tarjetas, get_cached_gpu_name() las une con " / "
                # ("NVIDIA ... / Intel ...") y deja sin responder cuál se está usando,
                # que es justo lo que esta frase tiene que decir. Se conserva como
                # respaldo para macOS y Linux, donde no hay un adaptador DXGI que nombrar.
                name = get_gpu_adapter_name() or get_cached_gpu_name()
            except Exception as e:
                logger.warning(f"Modelos IA: no se pudo detectar la GPU: {e}")
            try:
                self._gpu_info_ready.emit(label, name)
            except RuntimeError:
                pass  # La página ya no existe

        self._gpu_info_ready.connect(self._on_gpu_info_ready)
        threading.Thread(target=detect, name="ModelsPageGpuInfo", daemon=True).start()

    def _on_gpu_info_ready(self, label, name):
        self._gpu_label = label
        self._gpu_name = name
        self._gpu_known = True
        self._refresh_persist_row()

    def _build_max_sessions_row(self) -> QWidget:
        """Fila de "Cantidad máxima de modelos en memoria": QSpinBox 1-5 (defecto 1).
        Solo visible cuando "Mantener en memoria" está encendido -- si está apagado
        no tiene sentido mostrarla porque los modelos se liberan al terminar cada lote."""
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        lbl = QLabel(self.tr("Cantidad máxima de modelos en memoria"))
        lbl.setObjectName("settingsLabel")
        text_col.addWidget(lbl)

        self.lbl_max_sessions_desc = QLabel(self.tr(
            "Si usas varios modelos distintos, puedes mantener más de uno cargado "
            "para no volver a esperar la carga al alternar entre ellos. Cada modelo "
            "ocupa entre 200 MB y 900 MB de memoria."
        ))
        self.lbl_max_sessions_desc.setWordWrap(True)
        set_themed_style(self.lbl_max_sessions_desc, lambda: f"color: {get_theme_token('texto_tenue', '#888888')}; font-size: 11px;")
        text_col.addWidget(self.lbl_max_sessions_desc)
        row.addLayout(text_col, 1)

        self.spin_max_sessions = QSpinBox()
        self.spin_max_sessions.setRange(1, 5)
        self.spin_max_sessions.setValue(int(get_config().get("rembg_max_cached_sessions", 1)))
        self.spin_max_sessions.setFixedWidth(60)
        self.spin_max_sessions.valueChanged.connect(self._on_max_sessions_changed)
        row.addWidget(self.spin_max_sessions, 0, Qt.AlignVCenter)

        return container

    def _on_max_sessions_changed(self, value: int):
        cfg = get_config()
        cfg["rembg_max_cached_sessions"] = value
        save_config(cfg)
        logger.info(f"Modelos IA: máximo de sesiones en memoria cambiado a {value}")

    def _refresh_persist_row(self):
        """Pone al día la descripción y el botón "Liberar" según el estado del switch.
        La descripción nombra dónde queda el modelo (memoria de la GPU o RAM), que es
        lo que el usuario necesita saber para decidir si le sobra esa memoria."""
        on = self.switch_persist.isChecked()

        if not self._gpu_known:
            self.lbl_persist_desc.setText("")
        elif on:
            self.lbl_persist_desc.setText(self.tr(
                "Encendido: el modelo queda cargado en {0} desde el primer uso, así "
                "cada conversión nueva empieza a trabajar de inmediato en vez de "
                "volver a cargarlo."
            ).format(self._memory_hint()))
        else:
            self.lbl_persist_desc.setText(self.tr(
                "Apagado: el modelo se carga al empezar cada conversión y se libera de "
                "{0} al terminar. Ocupa menos memoria en reposo, pero cada lote vuelve "
                "a pagar la carga inicial (varios segundos con los modelos grandes)."
            ).format(self._memory_hint()))

        # Apagado no hay nada que liberar: el modelo ya se descarga solo al terminar
        # cada lote.
        self.btn_free_memory.setEnabled(on)

        # La fila de cantidad máxima solo tiene sentido con la persistencia encendida.
        if hasattr(self, '_max_sessions_row'):
            self._max_sessions_row.setVisible(on)

    def _memory_hint(self) -> str:
        """Dónde vive el modelo mientras está cargado, dicho con el detalle que se
        tenga: "la memoria de la NVIDIA GeForce RTX 3060 (DirectML)" si hay GPU y el
        escaneo de hardware ya corrió, "la memoria de la GPU (CoreML)" si solo se
        sabe el provider, o "la memoria del sistema (RAM)" cuando la inferencia va
        por CPU -- que es siempre el caso en Linux, a propósito."""
        if self._gpu_label is None:
            return self.tr("la memoria del sistema (RAM)")
        if self._gpu_name:
            return self.tr("la memoria de la {0} ({1})").format(self._gpu_name, self._gpu_label)
        return self.tr("la memoria de la GPU ({0})").format(self._gpu_label)

    def _on_persist_sessions_toggled(self, checked: bool):
        cfg = get_config()
        cfg["rembg_persist_sessions"] = checked
        save_config(cfg)
        logger.info(f"Modelos IA: 'Mantener en memoria' cambiado a {checked}")
        if not checked:
            # Apagar la opción libera lo que haya quedado cargado ahora mismo, no
            # recién en la próxima conversión -- si no, el usuario apaga la
            # opción pensando que ya liberó memoria y en realidad sigue cargada
            # hasta el próximo lote.
            from core.tabs.image_tools import rembg_engine  # diferido: arrastra PIL
            rembg_engine.clear_sessions()
        self._refresh_persist_row()

    def _on_free_memory_clicked(self):
        """Libera a mano lo que haya cargado, sin tener que apagar la opción ni
        cerrar la app. Se dice cuántas sesiones eran: "no había nada" es información
        útil, y sin ella el botón no da ninguna señal de haber hecho algo."""
        from core.tabs.image_tools import rembg_engine  # diferido: arrastra PIL
        freed = rembg_engine.clear_sessions()
        if freed:
            texto = (self.tr("Se descargó 1 modelo de la memoria.") if freed == 1
                     else self.tr("Se descargaron {0} modelos de la memoria.").format(freed))
            QMessageBox.information(self, self.tr("Memoria liberada"), texto)
        else:
            QMessageBox.information(
                self, self.tr("Nada que liberar"),
                self.tr("No hay ningún modelo cargado en memoria en este momento."),
            )

    # ── Secciones y familias plegables ───────────────────────────────────────
    def _make_group(self, group_id: str, title: str, level: str, parent_layout) -> "_ModelGroup":
        group = _ModelGroup(group_id, title, level)
        group.set_expanded(bool(self._expanded_state.get(group_id, False)))
        group.toggled.connect(self._on_group_toggled)
        parent_layout.addWidget(group)
        self._groups[group_id] = group
        return group

    def _begin_section(self, section_id: str, title: str) -> "_ModelGroup":
        section = self._make_group(section_id, title, "section", self.content_layout)
        self._target_layout = section.body_layout
        self._current_groups = [section]
        return section

    def _begin_family(self, section: "_ModelGroup", family_name: str) -> "_ModelGroup":
        family = self._make_group(f"{section.group_id}::{family_name}", family_name, "family",
                                  section.body_layout)
        self._target_layout = family.body_layout
        self._current_groups = [family, section]
        return family

    def _place_row(self, row_id: str, row):
        (self._target_layout or self.content_layout).addWidget(row)
        self._row_groups[row_id] = list(self._current_groups)

    def focus_model(self, info: dict, kind: str | None = None):
        """Lleva la vista a la fila de ese modelo/motor (botón "Administrar" de los
        popovers y de los avisos de descarga): abre su sección y su familia, la hace
        visible y la resalta un momento. `kind` ("depth", "normals"...) desempata si el
        mismo archivo apareciera en dos secciones."""
        key = model_download_key(info or {})
        candidates = [row_id for row_id, row_info in self.row_info.items()
                      if model_download_key(row_info) == key]
        if kind:
            candidates.sort(key=lambda row_id: self.row_kind.get(row_id) != kind)
        if not candidates:
            return False
        if self._filter_active():
            # El filtro podría estar escondiendo justo esa fila.
            self.txt_filter.clear()
            self.filter_selector.buttons[0].click()
        row_id = candidates[0]
        row = self.rows[row_id]
        for group in self._row_groups.get(row_id, []):
            group.set_expanded(True)
        # Diferido: con los grupos recién abiertos, el layout todavía no ubicó la fila.
        QTimer.singleShot(50, lambda: self._scroll_and_flash(row))
        return True

    def _scroll_and_flash(self, row):
        self.scroll_area.ensureWidgetVisible(row, 0, 80)
        set_themed_style(row, lambda: f"""
            QFrame#settingsCard {{ border: 2px solid {get_theme_token('acento_primario', '#B9E640')}; }}
        """)
        QTimer.singleShot(1800, lambda: set_themed_style(row, lambda: ""))

    # ── Filtro: buscar por nombre y "Todos / Descargados" ─────────────────────
    def _build_filter_row(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(10)
        self.txt_filter = QLineEdit()
        self.txt_filter.setPlaceholderText(self.tr("Buscar modelo..."))
        self.txt_filter.setClearButtonEnabled(True)
        self.txt_filter.setFixedHeight(32)
        self.txt_filter.textChanged.connect(self._apply_filter)
        layout.addWidget(self.txt_filter, 1)
        self.filter_selector = ModeSelector(row, labels=[self.tr("Todos"), self.tr("Descargados")])
        self.filter_selector.setFixedWidth(240)
        self.filter_selector.mode_changed.connect(self._apply_filter)
        layout.addWidget(self.filter_selector)
        return row

    def _only_installed(self) -> bool:
        buttons = self.filter_selector.buttons
        return len(buttons) > 1 and buttons[1].isChecked()

    def _apply_filter(self, *_args):
        """Muestra solo las filas que coinciden (nombre del modelo, de su familia o de su
        sección) y, con "Descargados", solo las instaladas. Con un filtro activo se abren
        las secciones y familias que tienen coincidencias; al quitarlo, vuelven a como las
        dejó el usuario."""
        text = self.txt_filter.text().strip().lower()
        only_installed = self._only_installed()
        active = bool(text) or only_installed
        visible_in = {}
        any_match = False
        for row_id, row in self.rows.items():
            groups = self._row_groups.get(row_id, [])
            haystack = " ".join([row.lbl_title.text()] + [g.lbl_title.text() for g in groups]).lower()
            match = (not text or text in haystack) and (not only_installed or getattr(row, "installed", False))
            row.setVisible(match)
            any_match = any_match or match
            for group in groups:
                visible_in[group.group_id] = visible_in.get(group.group_id, False) or match
        for group_id, group in self._groups.items():
            if group_id == "custom":
                custom = get_custom_rembg_models()
                if only_installed:
                    # Registrados en la config, pero el archivo puede no estar en la carpeta
                    # de modelos actual (ej. tras cambiarla sin moverlos).
                    custom = {n: i for n, i in custom.items() if os.path.exists(get_rembg_model_path(i))}
                names = " ".join(custom).lower()
                show = not active or (bool(custom) and (not text or text in names or text in group.lbl_title.text().lower()))
                group.setVisible(show)
                any_match = any_match or (active and show)
                if active:
                    group.set_expanded(show)
                else:
                    group.set_expanded(bool(self._expanded_state.get(group_id, False)))
                continue
            show = visible_in.get(group_id, False) or not active
            group.setVisible(show)
            group.set_expanded(show if active else bool(self._expanded_state.get(group_id, False)))
        self.lbl_no_matches.setVisible(active and not any_match)

    def _on_group_toggled(self, group_id: str, expanded: bool):
        self._expanded_state[group_id] = expanded
        cfg = get_config()
        cfg[self._EXPANDED_CONFIG_KEY] = dict(self._expanded_state)
        save_config(cfg)

    def _refresh_summaries(self):
        """Resumen en la cabecera de cada sección y familia: cuántos modelos hay,
        cuántos están descargados y cuánto ocupan, y el avance si alguno se descarga."""
        stats = {}
        for row_id, groups in self._row_groups.items():
            row = self.rows[row_id]
            for group in groups:
                s = stats.setdefault(group.group_id, {"total": 0, "installed": 0, "bytes": 0, "pcts": []})
                s["total"] += 1
                if getattr(row, "installed", False):
                    s["installed"] += 1
                    s["bytes"] += getattr(row, "installed_bytes", 0)
                if getattr(row, "downloading", False):
                    s["pcts"].append(getattr(row, "progress_pct", 0))
        for group_id, s in stats.items():
            group = self._groups[group_id]
            engines = group_id == "upscaling"
            if engines:
                text = self.tr("{0} motores").format(s["total"]) if s["total"] != 1 else self.tr("1 motor")
            else:
                text = self.tr("{0} modelos").format(s["total"]) if s["total"] != 1 else self.tr("1 modelo")
            if s["installed"]:
                text += " · " + (self.tr("{0} descargados").format(s["installed"]) if s["installed"] != 1
                                 else self.tr("1 descargado"))
                text += " · " + format_bytes(s["bytes"])
            if s["pcts"]:
                text += " · " + self.tr("descargando {0} %").format(min(s["pcts"]))
            group.set_summary(text)
        if hasattr(self, "_custom_section"):
            count = len(get_custom_rembg_models())
            self._custom_section.set_summary(
                self.tr("{0} importados").format(count) if count != 1 else self.tr("1 importado"))
        # Con un filtro activo (ej. "Descargados"), una descarga o un borrado cambia qué
        # filas entran. Sin filtro no se toca nada: no hay que cerrar lo que abrió una descarga.
        if self._filter_active():
            self._apply_filter()

    def _filter_active(self) -> bool:
        return hasattr(self, "txt_filter") and (bool(self.txt_filter.text().strip()) or self._only_installed())

    def _add_section_header(self, text: str):
        """Subtítulo de sección: el mismo estilo que "Aspecto"/"Comportamiento" en
        General (QLabel#settingsSectionTitle en _base.qss, color del acento del tema)."""
        lbl = QLabel(text)
        lbl.setObjectName("settingsSectionTitle")
        self.content_layout.addWidget(lbl)

    def _is_gated(self, model_info: dict) -> bool:
        # Los modelos con URL a una carpeta de Hugging Face (no a un archivo directo)
        # tienen licencia restringida: se bajan con la cuenta del usuario o a mano.
        return is_rembg_model_gated(model_info)

    def _add_rembg_row(self, model_name: str, model_info: dict):
        row_id = f"rembg::{model_info['folder']}::{model_info['file']}"
        path = os.path.join(get_models_dir(), model_info["folder"], model_info["file"])
        gated = self._is_gated(model_info)
        # El título lleva el peso de la DESCARGA (constants.py); la línea de estado
        # de la fila, cuando ya está instalado, muestra lo que ocupa en disco.
        row = ModelRow(row_id, format_model_label(model_name, get_rembg_model_size_bytes(model_info)),
                       path, gated=gated)
        row.download_requested.connect(self._on_download_requested)
        row.btn_delete.clicked.connect(lambda: self._on_delete_rembg(row_id, model_name))
        if gated:
            row.page_requested.connect(self._on_page_requested)
            row.manual_install_requested.connect(self._on_manual_install_requested)
        self.rows[row_id] = row
        self.row_info[row_id] = model_info
        self.row_kind[row_id] = "rembg"
        self._place_row(row_id, row)

    def _license_row_text(self, model_info: dict) -> str:
        license_name = get_depth_model_license(model_info)
        if license_name and is_depth_model_noncommercial(model_info):
            return self.tr("{0} · no comercial").format(license_name)
        return license_name

    def _add_depth_row(self, model_name: str, model_info: dict, kind: str = "depth"):
        """Fila de un modelo de Mapa de Profundidad ("depth") o de Mapa de Normales
        ("normals"): comparten formato de catálogo, y por eso las mismas funciones de
        instalación, descarga y borrado (ver "MAPA DE NORMALES" en models_setup.py)."""
        row_id = f"{kind}::{model_info['folder']}::{model_info['file']}"
        row = ModelRow(
            row_id, format_model_label(model_name, get_depth_model_size_bytes(model_info)),
            get_depth_model_path(model_info),
            installed_check=lambda info=model_info: is_depth_model_installed(info),
            disk_size=lambda info=model_info: get_depth_model_disk_size(info),
            license_text=self._license_row_text(model_info),
            license_noncommercial=is_depth_model_noncommercial(model_info),
            license_note=get_depth_model_license_note(model_info),
        )
        row.download_requested.connect(self._on_download_requested)
        row.btn_delete.clicked.connect(lambda: self._on_delete_depth(row_id, model_name))
        self.rows[row_id] = row
        self.row_info[row_id] = model_info
        self.row_kind[row_id] = kind
        self._place_row(row_id, row)

    # ── Modelos personalizados (importados) ─────────────────────────────────
    def _refresh_custom_rows(self):
        while self.custom_rows_container.count():
            item = self.custom_rows_container.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        custom = get_custom_rembg_models()
        if not custom:
            lbl = QLabel(self.tr("Todavía no importaste ningún modelo."))
            set_themed_style(lbl, lambda: f"color: {get_theme_token('texto_secundario', '#666666')}; font-size: 11px; font-style: italic;")
            self.custom_rows_container.addWidget(lbl)
            if hasattr(self, "scroll_area"):
                self._refresh_summaries()
            return

        for model_name, model_info in custom.items():
            self._add_custom_row(model_name, model_info)
        if hasattr(self, "scroll_area"):
            self._refresh_summaries()

    def _add_custom_row(self, model_name: str, model_info: dict):
        row_id = f"custom::{model_name}"
        path = get_rembg_model_path(model_info)
        row = ModelRow(row_id, model_name, path, gated=False, no_download=True, relocatable=True)
        row.btn_delete.clicked.connect(lambda: self._on_delete_custom(model_name))
        row.relocate_requested.connect(lambda _rid: self._on_relocate_custom(model_name))
        self.custom_rows_container.addWidget(row)

    def _on_import_custom_clicked(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Seleccionar modelo ONNX"), "", self.tr("Modelos ONNX (*.onnx)")
        )
        if not path:
            return

        dialog = ImportOnnxDialog(path, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return

        name, size, copy_to_models = dialog.get_values()
        if not name:
            QMessageBox.warning(self, self.tr("Error"), self.tr("El modelo necesita un nombre."))
            return

        if name in get_custom_rembg_models():
            if QMessageBox.question(
                self, self.tr("Reemplazar modelo"),
                self.tr("Ya existe un modelo importado llamado '{0}'. ¿Reemplazarlo?").format(name)
            ) != QMessageBox.Yes:
                return

        success, msg = import_custom_rembg_model(name, path, (size, size), copy_to_models=copy_to_models)
        if success:
            self._refresh_custom_rows()
            model_downloads().models_changed.emit()
            QMessageBox.information(self, self.tr("Modelo importado"), msg)
        else:
            QMessageBox.warning(self, self.tr("Error al importar"), msg)

    def _on_delete_custom(self, model_name: str):
        """Quitar de la lista o eliminar del disco (a la Papelera): ver custom_model_dialogs."""
        from gui.widgets.custom_model_dialogs import confirm_remove_custom_model
        if confirm_remove_custom_model(self, model_name):
            self._refresh_custom_rows()
            model_downloads().models_changed.emit()

    def _on_relocate_custom(self, model_name: str):
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("¿Dónde está ahora '{0}'?").format(model_name), "", self.tr("Modelos ONNX (*.onnx)"))
        if path and relocate_custom_rembg_model(model_name, path):
            self._refresh_custom_rows()
            model_downloads().models_changed.emit()

    def _add_upscaling_row(self, engine_key: str, tool_info: dict):
        row_id = f"upscaling::{engine_key}"
        path = os.path.join(get_models_dir(), tool_info["folder"])
        row = ModelRow(row_id, format_model_label(tool_info["name"], get_upscaling_engine_size_bytes(tool_info)),
                       path, gated=False)
        row.download_requested.connect(self._on_download_requested)
        row.btn_delete.clicked.connect(lambda: self._on_delete_upscaling(row_id, tool_info["name"]))
        self.rows[row_id] = row
        self.row_info[row_id] = tool_info
        self.row_kind[row_id] = "upscaling"
        self._place_row(row_id, row)

    # ── Descarga ─────────────────────────────────────────────────────────────
    def _on_download_requested(self, row_id: str):
        info = self.row_info[row_id]
        kind = self.row_kind[row_id]
        if kind == "rembg" and is_rembg_model_gated(info):
            self._start_gated_download(row_id)
            return
        download_func = {
            "rembg": download_rembg_model,
            "depth": download_depth_model,
            "normals": download_depth_model,
        }.get(kind, download_upscaling_engine)

        # Si ya se estaba bajando (lanzada desde un popover), start() no hace nada: la
        # fila ya muestra ese progreso.
        key = model_download_key(info)
        self._started_here.add(key)
        if not model_downloads().start(key, download_func, info):
            self._started_here.discard(key)

    def _rows_for_key(self, key: str) -> list:
        """Filas de la descarga `key` -- normalmente una; varias si un mismo archivo
        apareciera en más de una sección."""
        return [self.rows[row_id] for row_id, info in self.row_info.items()
                if model_download_key(info) == key]

    def _on_download_started(self, key: str):
        for row in self._rows_for_key(key):
            row.set_downloading(True)
            row.set_progress(model_downloads().progress(key))
            # Una descarga en curso abre su sección y su familia, para ver el avance
            # (sin recordarlo: es temporal, no una elección del usuario).
            for group in self._row_groups.get(row.row_id, []):
                group.set_expanded(True)
        self._refresh_summaries()

    def _on_progress(self, pct: int, key: str):
        for row in self._rows_for_key(key):
            row.set_progress(pct)
        self._refresh_summaries()

    def _on_download_finished(self, success: bool, msg: str, key: str):
        started_here = key in self._started_here
        self._started_here.discard(key)
        for row in self._rows_for_key(key):
            row.set_downloading(False)
            row.refresh_status()
        self._refresh_summaries()
        if not success and started_here:
            QMessageBox.warning(self, self.tr("Error de Descarga"), msg)

    # ── Eliminar ─────────────────────────────────────────────────────────────
    def _on_delete_rembg(self, row_id: str, display_name: str):
        if QMessageBox.question(
            self, self.tr("Eliminar modelo"),
            self.tr("¿Eliminar '{0}' del disco?").format(display_name)
        ) != QMessageBox.Yes:
            return
        if delete_rembg_model(self.row_info[row_id]):
            self.rows[row_id].refresh_status()
            self._refresh_summaries()
            model_downloads().models_changed.emit()

    def _on_delete_depth(self, row_id: str, display_name: str):
        if QMessageBox.question(
            self, self.tr("Eliminar modelo"),
            self.tr("¿Eliminar '{0}' del disco?").format(display_name)
        ) != QMessageBox.Yes:
            return
        if delete_depth_model(self.row_info[row_id]):
            self.rows[row_id].refresh_status()
            self._refresh_summaries()
            model_downloads().models_changed.emit()

    def _on_delete_upscaling(self, row_id: str, display_name: str):
        if QMessageBox.question(
            self, self.tr("Eliminar motor"),
            self.tr("¿Eliminar '{0}' (motor completo) del disco?").format(display_name)
        ) != QMessageBox.Yes:
            return
        if delete_upscaling_engine(self.row_info[row_id]):
            self.rows[row_id].refresh_status()
            self._refresh_summaries()
            model_downloads().models_changed.emit()
