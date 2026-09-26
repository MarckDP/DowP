# src/gui/tabs/single_process/output_options.py
import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtCore import Qt, QUrl, QSize, QPropertyAnimation, QParallelAnimationGroup, QEasingCurve
from gui.widgets.animated_button import AnimatedButton
from gui.widgets.combo_box import AutoPopupComboBox
from gui.styles import apply_folder_browse_button_style, apply_folder_open_button_style, apply_cut_button_style
from gui.widgets.native_file_drag import DraggableFilesButton
from PySide6.QtCore import Signal


class OutputOptionsWidget(QFrame):
    TOOL_BUTTON_SIZE = 32
    PANEL_HEIGHT = 210

    # Clic simple sobre el botón de arrastre (ver btn_drag_output): abre el explorador
    # con los archivos producidos seleccionados. El arrastre en sí no pasa por aquí.
    output_drag_clicked = Signal()
    # La ruta propia de la pestaña cambió (el usuario la eligió o la escribió); no se
    # emite cuando el campo muestra la ruta de una etiqueta. Ver own_output_path.
    own_path_changed = Signal(str)

    def __init__(self, path_config_key=None):
        """path_config_key: clave de configuración donde recordar la ruta de salida de
        esta pestaña entre sesiones (cada pestaña la suya). Sin ella, el campo arranca
        siempre en la carpeta de Descargas del sistema."""
        super().__init__()
        self._path_config_key = path_config_key
        self.setObjectName("outputOptionsContainer")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        self.output_title_label = QLabel(self.tr("Opciones de salida"))
        self.output_title_label.setObjectName("sectionTitle")
        self.output_title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.output_title_label)

        controls_layout = QHBoxLayout()
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(6)

        # --- CONFLICT POLICY SECTION (a la izquierda de la ruta) ---
        # Visible siempre en Modo Rápido; en Proceso Avanzado solo en modo LOTES
        # (ver advanced_process_view.py::_on_solo_toggled, que llama
        # set_conflict_policy_visible()).
        self.conflict_policy_container = QWidget()
        conflict_policy_layout = QHBoxLayout(self.conflict_policy_container)
        conflict_policy_layout.setContentsMargins(0, 0, 4, 0)
        conflict_policy_layout.setSpacing(4)

        self.lbl_conflict_policy = QLabel(self.tr("Si existe:"))
        self.lbl_conflict_policy.setObjectName("menuLabel")

        self.conflict_policy_combo = AutoPopupComboBox()
        self.conflict_policy_combo.addItem(self.tr("Sobrescribir"), "sobrescribir")
        self.conflict_policy_combo.addItem(self.tr("Conservar"), "conservar")
        self.conflict_policy_combo.addItem(self.tr("Omitir"), "omitir")
        self.conflict_policy_combo.setCurrentIndex(1)  # "Conservar" por defecto
        
        conflict_tooltip = self.tr(
            "Determina qué hacer si un archivo con el mismo nombre ya existe:\n"
            "• Sobrescribir: reemplaza el archivo antiguo (con respaldo reversible).\n"
            "• Conservar: guarda el nuevo archivo como 'nombre (1).ext'.\n"
            "• Omitir: no descarga ese archivo."
        )
        self.conflict_policy_combo.setToolTip(conflict_tooltip)
        self.lbl_conflict_policy.setToolTip(conflict_tooltip)

        conflicts_fixed_height = 32
        self.conflict_policy_combo.setFixedHeight(conflicts_fixed_height)

        conflict_policy_layout.addWidget(self.lbl_conflict_policy)
        conflict_policy_layout.addWidget(self.conflict_policy_combo)

        controls_layout.addWidget(self.conflict_policy_container)

        # --- PATH SECTION ---
        self.output_path_input = QLineEdit()
        self.output_path_input.setPlaceholderText(self.tr("Ruta de salida"))
        self.output_path_input.setText(self.own_output_path())
        self.output_path_input.setFixedHeight(32)
        self.output_path_input.editingFinished.connect(self._remember_output_path)
        
        self.btn_select_output_path = QPushButton()
        self.btn_select_output_path.setFixedSize(self.TOOL_BUTTON_SIZE, self.TOOL_BUTTON_SIZE)
        apply_folder_browse_button_style(self.btn_select_output_path, self.tr("Seleccionar carpeta de salida"), icon_size=20)

        self.btn_open_output_path = QPushButton()
        self.btn_open_output_path.setFixedSize(self.TOOL_BUTTON_SIZE, self.TOOL_BUTTON_SIZE)
        apply_folder_open_button_style(self.btn_open_output_path, self.tr("Abrir carpeta de salida"), icon_size=20)

        self.btn_select_output_path.clicked.connect(self.select_output_path)
        self.btn_open_output_path.clicked.connect(self.open_output_path)

        # --- ARRASTRE DEL RESULTADO (solo Proceso Avanzado en modo SOLO) ---
        # En modo LOTES cada tarjeta de la cola se arrastra sola (ver queue_panel.py) y
        # en Modo Rápido lo hace cada fila, pero en SOLO no hay ninguna lista: sin este
        # botón no habría de dónde agarrar el resultado. Mismo gesto que el botón de
        # corte físico del diálogo de subclips: se puede clicar y se puede arrastrar.
        # Oculto por defecto; lo muestra advanced_process_view.py::_on_solo_toggled.
        self.btn_drag_output = DraggableFilesButton(files_provider=None)
        self.btn_drag_output.setFixedSize(self.TOOL_BUTTON_SIZE, self.TOOL_BUTTON_SIZE)
        self.btn_drag_output.setEnabled(False)
        self.btn_drag_output.hide()
        self.btn_drag_output.clicked.connect(self.output_drag_clicked.emit)
        self._refresh_output_drag_style()
        controls_layout.addWidget(self.btn_drag_output)

        controls_layout.addWidget(self.output_path_input, 1) # Stretch 1
        controls_layout.addWidget(self.btn_select_output_path)
        controls_layout.addWidget(self.btn_open_output_path)

        # El límite de velocidad vivía aquí; ahora es un ajuste global (Ajustes >
        # Descargas, ver DownloaderMaster._prepare_opts).

        # --- DOWNLOAD BUTTON ---
        self.btn_start_download = AnimatedButton(self.tr("Iniciar descarga"))
        self.btn_start_download.setObjectName("downloadButton")
        self.btn_start_download.setFixedWidth(135)
        self.btn_start_download.setFixedHeight(32)
        self.btn_start_download.setEnabled(False)

        controls_layout.addWidget(self.btn_start_download)

        layout.addLayout(controls_layout)

        # --- PROGRESS BAR ---
        from gui.widgets.bouncing_progress_bar import BouncingProgressBar
        self.progress_bar = BouncingProgressBar()
        self.progress_bar.setObjectName("downloadProgressBar")
        self.progress_bar.setProperty("status", "wait")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(self.tr("En espera"))
        self.progress_bar.setTextVisible(True)

        layout.addWidget(self.progress_bar)

    def _refresh_output_drag_style(self):
        """Verde cuando hay algo que arrastrar, gris cuando no -- mismos tres estados
        que el resto de botones de acción de la app (ver styles.apply_cut_button_style)."""
        enabled = self.btn_drag_output.isEnabled()
        apply_cut_button_style(
            self.btn_drag_output, "saved" if enabled else "normal",
            icon_size=18, shape="square", icon_name="drag_pan.svg"
        )
        self.btn_drag_output.setToolTip(
            self.tr("Arrastra para llevarte todos los archivos de esta descarga a otra "
                    "aplicación (clic: abrirlos en el explorador)")
            if enabled else
            self.tr("Aquí podrás arrastrar el resultado cuando la descarga termine")
        )

    def set_output_drag_visible(self, visible: bool):
        self.btn_drag_output.setVisible(bool(visible))

    def set_output_drag_files_provider(self, provider):
        self.btn_drag_output.set_files_provider(provider)

    def set_output_drag_enabled(self, enabled: bool):
        self.btn_drag_output.setEnabled(bool(enabled))
        self._refresh_output_drag_style()

    def set_download_state(self, state, text=None):
        state_names = {
            "idle": self.tr("Iniciar descarga"),
            "running": self.tr("Descargando..."),
            "pause_queue": self.tr("Pausar cola"),
            "paused": self.tr("Reanudar descarga"),
            "done": self.tr("Descarga completada"),
            "error": self.tr("Reintentar descarga"),
            "cancelling": self.tr("Cancelar"),
        }

        self.btn_start_download.setProperty("state", state)
        self.btn_start_download.setText(text or state_names.get(state, state_names["idle"]))
        self._refresh_style(self.btn_start_download)

    def set_progress(self, value, message=None, status="wait"):
        """
        Estados:
          - 'running'      → barrita rebotando (modo indeterminado custom)
          - 'downloading'  → barra real 0-100% con info de descarga
          - 'done'         → barra al 100%
          - 'wait'         → barra vacía
          - 'error'        → barra vacía con error
        """
        if status == "running":
            self.progress_bar.setBouncing(True)
        else:
            self.progress_bar.setBouncing(False)
            self.progress_bar.setValue(value)

        self.progress_bar.setProperty("status", status)

        if message:
            self.progress_bar.setFormat(message)
        elif status == "wait":
            self.progress_bar.setFormat(self.tr("En espera"))
        else:
            self.progress_bar.setFormat(f"{value}%")

        self._refresh_style(self.progress_bar)

    def select_output_path(self):
        current_path = self.output_path_input.text().strip()
        start_path = current_path if os.path.isdir(current_path) else os.path.expanduser("~")
        selected_path = QFileDialog.getExistingDirectory(
            self,
            self.tr("Seleccionar carpeta de salida"),
            start_path,
        )
        if selected_path:
            self.output_path_input.setText(selected_path)
            self._remember_output_path()

    def own_output_path(self):
        """La ruta de salida elegida por el usuario para esta pestaña (la última, guardada
        entre sesiones), aunque el campo muestre ahora la de una etiqueta. Si la carpeta
        guardada ya no existe, la de Descargas del sistema."""
        from core.tabs.advanced_process.output_logic import get_default_download_path
        from core.utils.config_manager import get_config
        saved = get_config().get(self._path_config_key) if self._path_config_key else None
        if saved and os.path.isdir(saved):
            return saved
        return get_default_download_path()

    def restore_own_output_path(self):
        """Vuelve a mostrar la ruta propia de la pestaña (al quitar una etiqueta)."""
        self.output_path_input.setText(self.own_output_path())

    def _remember_output_path(self):
        # Con una etiqueta activa el campo está bloqueado y muestra la ruta de la
        # etiqueta: esa no es la ruta que el usuario eligió para la pestaña.
        if not self._path_config_key or not self.output_path_input.isEnabled():
            return
        path = self.output_path_input.text().strip()
        if not path:
            return
        from core.utils.config_manager import get_config, save_config
        config = get_config()
        if config.get(self._path_config_key) != path:
            config[self._path_config_key] = path
            save_config(config)
        self.own_path_changed.emit(path)

    def open_output_path(self):
        path = self.output_path_input.text().strip()
        if not path:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def set_conflict_policy_visible(self, visible: bool, animated: bool = True):
        """
        Muestra/oculta el combo de política de conflicto. Usado por Proceso Avanzado
        para ocultarlo en modo SOLO (donde en su lugar se pregunta con un diálogo
        modal por archivo) y mostrarlo en modo LOTES. Modo Rápido nunca llama a este
        método: el combo queda siempre visible ahí.

        Anima minimumWidth/maximumWidth del contenedor a 0 <-> ancho natural.
        """
        if hasattr(self, "_conflict_anim_group") and self._conflict_anim_group.state() == QParallelAnimationGroup.State.Running:
            self._conflict_anim_group.stop()

        if not animated:
            target_width = self.conflict_policy_container.sizeHint().width() if visible else 0
            self.conflict_policy_container.setMinimumWidth(target_width)
            self.conflict_policy_container.setMaximumWidth(target_width if visible else 0)
            self.conflict_policy_container.setVisible(visible)
            return

        if visible:
            # Calcular ancho natural del contenido
            target_width = self.conflict_policy_container.sizeHint().width()
            if target_width <= 0:
                target_width = 185
            # Iniciar colapsado para animar la entrada
            self.conflict_policy_container.setMinimumWidth(0)
            self.conflict_policy_container.setMaximumWidth(0)
            self.conflict_policy_container.setVisible(True)
            current_width = 0
        else:
            target_width = 0
            current_width = self.conflict_policy_container.width()
            if current_width <= 0:
                current_width = self.conflict_policy_container.sizeHint().width()

        self._conflict_anim_group = QParallelAnimationGroup(self)

        anim_min = QPropertyAnimation(self.conflict_policy_container, b"minimumWidth")
        anim_min.setDuration(220)
        anim_min.setStartValue(current_width)
        anim_min.setEndValue(target_width)
        anim_min.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._conflict_anim_group.addAnimation(anim_min)

        anim_max = QPropertyAnimation(self.conflict_policy_container, b"maximumWidth")
        anim_max.setDuration(220)
        anim_max.setStartValue(current_width)
        anim_max.setEndValue(target_width)
        anim_max.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._conflict_anim_group.addAnimation(anim_max)

        def on_finished():
            if visible:
                self.conflict_policy_container.setMaximumWidth(16777215)
                self.conflict_policy_container.setMinimumWidth(0)
            else:
                self.conflict_policy_container.setVisible(False)
                self.conflict_policy_container.setMaximumWidth(0)
                self.conflict_policy_container.setMinimumWidth(0)

        self._conflict_anim_group.finished.connect(on_finished)
        self._conflict_anim_group.start()

    def _refresh_style(self, widget):
        from gui.widgets.bouncing_progress_bar import BouncingProgressBar
        if isinstance(widget, BouncingProgressBar):
            widget.refresh_theme_colors()
            
        widget.style().unpolish(widget)
        widget.style().polish(widget)
