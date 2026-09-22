# src/gui/tabs/settings/pages/models_page.py
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QScrollArea,
    QPushButton, QMessageBox, QProgressBar, QFileDialog, QDialog,
    QLineEdit, QSpinBox, QDialogButtonBox, QFormLayout,
)
from PySide6.QtCore import Qt, QThread, Signal, QUrl, QSize
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
    delete_custom_rembg_model, probe_onnx_input_size,
    get_rembg_model_size_bytes, get_upscaling_engine_size_bytes,
)
from core.tabs.image_tools import rembg_engine
from core.utils.onnx_providers import get_gpu_adapter_name, get_gpu_provider_label
from core.utils.hardware_detector import get_cached_gpu_name
from gui.widgets.toggle_switch import ToggleSwitch
# Las descargas no se lanzan desde aquí sino desde el gestor común (model_downloads(),
# ver gui/widgets/model_download_prompt.py): los popovers del Editor de Imagen también
# descargan modelos, y así el progreso de cada descarga se ve en las dos pantallas.
from gui.widgets.model_download_prompt import format_model_label, model_download_key, model_downloads
from gui.styles import (
    get_theme_token,
    set_button_variant,
    apply_download_action_button_style,
    apply_folder_open_button_style,
)
from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon


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
        info_lbl.setStyleSheet("color: #AAAAAA; font-size: 11px;")
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
        self.lbl_probe.setStyleSheet("color: #888888; font-size: 11px; font-style: italic;")
        self.lbl_probe.setWordWrap(True)
        layout.addWidget(self.lbl_probe)

        hint = QLabel(self.tr(
            "Si no se detecta solo, dejalo en 1024 (el más común en modelos "
            "modernos de Eliminar Fondo) o revisa la página de donde bajaste el "
            "modelo -- los legacy tipo U2Net suelen usar 320."
        ))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666666; font-size: 10px;")
        layout.addWidget(hint)

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
            self.lbl_probe.setStyleSheet("color: #4CAF50; font-size: 11px;")
        else:
            self.lbl_probe.setText(self.tr("No se pudo detectar el tamaño -- confírmalo a mano."))
            self.lbl_probe.setStyleSheet("color: #FFC107; font-size: 11px;")

    def get_values(self) -> tuple[str, int]:
        return self.entry_name.text().strip(), self.spin_size.value()

    def closeEvent(self, event):
        # El sondeo corre en un QThread aparte -- si el usuario cierra el diálogo
        # antes de que termine, hay que esperarlo un toque para no destruirlo
        # mientras sigue corriendo (Qt tira warning/crash con eso).
        if self._probe_worker.isRunning():
            self._probe_worker.wait(2000)
        super().closeEvent(event)


class ModelRow(QFrame):
    """Fila para un modelo rembg o un motor de upscaling. `gated=True` lo muestra
    bloqueado (sin acciones) para variantes que necesitan cuenta/login externo."""
    download_requested = Signal(str)  # row_id

    def __init__(self, row_id: str, title: str, path_for_size: str, gated: bool = False,
                 no_download: bool = False, installed_check=None, disk_size=None,
                 license_text: str = "", license_noncommercial: bool = False,
                 license_note: str = "", parent=None):
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
        self.lbl_title.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 13px;")
        if self._license_text:
            title_row = QHBoxLayout()
            title_row.setSpacing(8)
            title_row.addWidget(self.lbl_title)
            self.lbl_license = QLabel(self._license_text)
            color = get_theme_token("estado_aviso", "#d8c94a") if self._license_noncommercial else "#888888"
            self.lbl_license.setStyleSheet(f"color: {color}; font-size: 10px;")
            self.lbl_license.setToolTip(self._license_note)
            title_row.addWidget(self.lbl_license, 0, Qt.AlignBottom)
            title_row.addStretch()
            info_vbox.addLayout(title_row)
        else:
            info_vbox.addWidget(self.lbl_title)

        self.lbl_status = QLabel()
        self.lbl_status.setStyleSheet("font-size: 11px;")
        info_vbox.addWidget(self.lbl_status)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.hide()
        info_vbox.addWidget(self.progress_bar)

        layout.addLayout(info_vbox, 1)

        if self.gated:
            # Icono SVG de assets, no un emoji: el emoji no se tiñe con el tema y se
            # dibuja distinto (o no se dibuja) según la fuente de cada sistema.
            lbl_locked_icon = QLabel()
            lbl_locked_icon.setPixmap(
                get_colored_svg_icon("login.svg", "#888888", size=14).pixmap(14, 14))
            layout.addWidget(lbl_locked_icon, 0, Qt.AlignVCenter)
            lbl_locked = QLabel(self.tr("Requiere cuenta (próximamente)"))
            lbl_locked.setStyleSheet("color: #888888; font-size: 11px; font-style: italic;")
            layout.addWidget(lbl_locked, 0, Qt.AlignVCenter)
            return

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
        self.btn_delete.setFixedWidth(80)
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

    def refresh_status(self):
        if self.gated:
            return
        dis_color = get_theme_token("texto_deshabilitado", "#777777")

        if self.is_installed():
            size = self._disk_size() if self._disk_size is not None else get_folder_size(self.path_for_size)
            self.lbl_status.setText(self.tr("Instalado ({0})").format(format_bytes(size)))
            self.lbl_status.setStyleSheet("color: #4CAF50; font-size: 11px; font-weight: bold;")
            if not self.no_download:
                self.btn_download.setIcon(get_colored_svg_icon("check_circle.svg", "#000000", size=18, disabled_color_hex=dis_color))
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
            self.lbl_status.setText(self.tr("Archivo no encontrado — elimínalo de la lista"))
            self.lbl_status.setStyleSheet("color: #FFC107; font-size: 11px; font-weight: bold;")
            self.btn_folder.setDisabled(False)
            self.btn_delete.setDisabled(False)

        else:
            self.lbl_status.setText(self.tr("No descargado"))
            self.lbl_status.setStyleSheet("color: #888888; font-size: 11px;")
            self.btn_download.setIcon(get_colored_svg_icon("download.svg", "#000000", size=18, disabled_color_hex=dis_color))
            self.btn_download.setIconSize(QSize(18, 18))
            self.btn_download.setToolTip(self.tr("Descargar"))
            self.btn_folder.setDisabled(True)
            self.btn_delete.setDisabled(True)

    def set_downloading(self, is_downloading: bool):
        if self.gated:
            return
        self.btn_download.setDisabled(is_downloading)
        self.btn_delete.setDisabled(is_downloading)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(is_downloading)
        if is_downloading:
            self.lbl_status.setText(self.tr("Descargando..."))
            self.lbl_status.setStyleSheet("color: #FFC107; font-size: 11px; font-weight: bold;")
            self.btn_download.setToolTip(self.tr("Descargando..."))

    def set_progress(self, pct: int):
        self.progress_bar.setValue(pct)


class ModelsPage(QWidget):
    """Pestaña de Ajustes para descargar/gestionar modelos de IA (rembg, upscaling).
    Los modelos nunca se descargan solos -- solo cuando el usuario aprieta Descargar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: dict[str, ModelRow] = {}
        self.row_info: dict[str, dict] = {}          # row_id -> info dict (model_info / tool_info)
        self.row_kind: dict[str, str] = {}            # row_id -> "rembg" | "depth" | "normals" | "upscaling"
        # Claves (model_download_key) de las descargas lanzadas desde esta página:
        # solo quien lanza una descarga avisa con un diálogo si falla.
        self._started_here: set[str] = set()
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

        self.main_layout.addWidget(self._build_persist_sessions_row())
        self._max_sessions_row = self._build_max_sessions_row()
        self.main_layout.addWidget(self._max_sessions_row)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")

        scroll_content = QWidget()
        scroll_content.setObjectName("settingsScrollContent")
        scroll_content.setStyleSheet("QWidget#settingsScrollContent { background-color: transparent; }")

        self.content_layout = QVBoxLayout(scroll_content)
        self.content_layout.setContentsMargins(0, 10, 10, 0)
        self.content_layout.setSpacing(10)
        self.content_layout.setAlignment(Qt.AlignTop)

        self._add_section_header(self.tr("Eliminación de Fondo (Rembg)"))
        for family_name, models in REMBG_MODEL_FAMILIES.items():
            self._add_family_header(family_name)
            for model_name, model_info in models.items():
                self._add_rembg_row(model_name, model_info)

        self.content_layout.addSpacing(8)
        self._add_section_header(self.tr("Modelos Personalizados (Importados)"))

        import_row = QHBoxLayout()
        import_desc = QLabel(self.tr(
            "Para modelos ONNX de Eliminar Fondo que no están en el catálogo de arriba "
            "(por ejemplo, descargados a mano desde HuggingFace)."
        ))
        import_desc.setStyleSheet("color: #888888; font-size: 11px;")
        import_desc.setWordWrap(True)
        import_row.addWidget(import_desc, 1)
        self.btn_import_custom = QPushButton(self.tr("Importar modelo ONNX..."))
        self.btn_import_custom.setFixedHeight(32)
        self.btn_import_custom.setCursor(Qt.PointingHandCursor)
        set_button_variant(self.btn_import_custom, "accent-solid")
        self.btn_import_custom.clicked.connect(self._on_import_custom_clicked)
        import_row.addWidget(self.btn_import_custom, 0, Qt.AlignVCenter)
        self.content_layout.addLayout(import_row)

        self.custom_rows_container = QVBoxLayout()
        self.custom_rows_container.setSpacing(10)
        self.content_layout.addLayout(self.custom_rows_container)
        self._refresh_custom_rows()

        self.content_layout.addSpacing(8)
        self._add_section_header(self.tr("Mapas de Profundidad"))
        for family_name, models in DEPTH_MODEL_FAMILIES.items():
            self._add_family_header(family_name)
            for model_name, model_info in models.items():
                self._add_depth_row(model_name, model_info)

        self.content_layout.addSpacing(8)
        self._add_section_header(self.tr("Mapas de Normales"))
        for family_name, models in NORMAL_MODEL_FAMILIES.items():
            self._add_family_header(family_name)
            for model_name, model_info in models.items():
                self._add_depth_row(model_name, model_info, kind="normals")

        self.content_layout.addSpacing(8)
        self._add_section_header(self.tr("Motores de Reescalado (Upscaling)"))
        for engine_key, tool_info in UPSCALING_TOOLS.items():
            self._add_upscaling_row(engine_key, tool_info)

        scroll_area.setWidget(scroll_content)
        self.main_layout.addWidget(scroll_area)

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
        self.lbl_persist_desc.setStyleSheet("color: #888888; font-size: 11px;")
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

        self._gpu_label = get_gpu_provider_label()
        # El adaptador elegido antes que el nombre cacheado del escaneo: en un equipo
        # con dos tarjetas, get_cached_gpu_name() las une con " / " ("NVIDIA ... /
        # Intel ...") y deja sin responder cuál se está usando, que es justo lo que
        # esta frase tiene que decir. Se conserva como respaldo para macOS y Linux,
        # donde no hay un adaptador DXGI que nombrar.
        self._gpu_name = get_gpu_adapter_name() or get_cached_gpu_name()
        self.switch_persist.setChecked(bool(get_config().get("rembg_persist_sessions", False)))
        self._refresh_persist_row()
        return container

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
        self.lbl_max_sessions_desc.setStyleSheet("color: #888888; font-size: 11px;")
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

        if on:
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
            rembg_engine.clear_sessions()
        self._refresh_persist_row()

    def _on_free_memory_clicked(self):
        """Libera a mano lo que haya cargado, sin tener que apagar la opción ni
        cerrar la app. Se dice cuántas sesiones eran: "no había nada" es información
        útil, y sin ella el botón no da ninguna señal de haber hecho algo."""
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

    def _add_section_header(self, text: str):
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #EEEEEE; font-size: 14px; font-weight: bold; margin-top: 4px;")
        self.content_layout.addWidget(lbl)

    def _add_family_header(self, text: str):
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #B9E640; font-size: 12px; font-weight: bold; margin-top: 6px;")
        self.content_layout.addWidget(lbl)

    def _is_gated(self, model_info: dict) -> bool:
        # Los modelos con URL a una página (no a un archivo directo) necesitan
        # descarga manual con cuenta -- por ahora se muestran bloqueados sin acción.
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
        if not gated:
            row.btn_delete.clicked.connect(lambda: self._on_delete_rembg(row_id, model_name))
        self.rows[row_id] = row
        self.row_info[row_id] = model_info
        self.row_kind[row_id] = "rembg"
        self.content_layout.addWidget(row)

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
        self.content_layout.addWidget(row)

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
            lbl.setStyleSheet("color: #666666; font-size: 11px; font-style: italic;")
            self.custom_rows_container.addWidget(lbl)
            return

        for model_name, model_info in custom.items():
            self._add_custom_row(model_name, model_info)

    def _add_custom_row(self, model_name: str, model_info: dict):
        row_id = f"custom::{model_name}"
        path = os.path.join(get_models_dir(), model_info["folder"], model_info["file"])
        row = ModelRow(row_id, model_name, path, gated=False, no_download=True)
        row.btn_delete.clicked.connect(lambda: self._on_delete_custom(model_name))
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

        name, size = dialog.get_values()
        if not name:
            QMessageBox.warning(self, self.tr("Error"), self.tr("El modelo necesita un nombre."))
            return

        if name in get_custom_rembg_models():
            if QMessageBox.question(
                self, self.tr("Reemplazar modelo"),
                self.tr("Ya existe un modelo importado llamado '{0}'. ¿Reemplazarlo?").format(name)
            ) != QMessageBox.Yes:
                return

        success, msg = import_custom_rembg_model(name, path, (size, size))
        if success:
            self._refresh_custom_rows()
            QMessageBox.information(self, self.tr("Modelo importado"), msg)
        else:
            QMessageBox.warning(self, self.tr("Error al importar"), msg)

    def _on_delete_custom(self, model_name: str):
        if QMessageBox.question(
            self, self.tr("Eliminar modelo"),
            self.tr("¿Eliminar el modelo importado '{0}'?").format(model_name)
        ) != QMessageBox.Yes:
            return
        if delete_custom_rembg_model(model_name):
            self._refresh_custom_rows()

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
        self.content_layout.addWidget(row)

    # ── Descarga ─────────────────────────────────────────────────────────────
    def _on_download_requested(self, row_id: str):
        info = self.row_info[row_id]
        kind = self.row_kind[row_id]
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

    def _on_progress(self, pct: int, key: str):
        for row in self._rows_for_key(key):
            row.set_progress(pct)

    def _on_download_finished(self, success: bool, msg: str, key: str):
        started_here = key in self._started_here
        self._started_here.discard(key)
        for row in self._rows_for_key(key):
            row.set_downloading(False)
            row.refresh_status()
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

    def _on_delete_depth(self, row_id: str, display_name: str):
        if QMessageBox.question(
            self, self.tr("Eliminar modelo"),
            self.tr("¿Eliminar '{0}' del disco?").format(display_name)
        ) != QMessageBox.Yes:
            return
        if delete_depth_model(self.row_info[row_id]):
            self.rows[row_id].refresh_status()

    def _on_delete_upscaling(self, row_id: str, display_name: str):
        if QMessageBox.question(
            self, self.tr("Eliminar motor"),
            self.tr("¿Eliminar '{0}' (motor completo) del disco?").format(display_name)
        ) != QMessageBox.Yes:
            return
        if delete_upscaling_engine(self.row_info[row_id]):
            self.rows[row_id].refresh_status()
