# src/gui/tabs/quick_mode/quick_mode_view.py
import os
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt, QEvent, QPoint, QRect, QSize
from PySide6.QtGui import QIcon

from gui.styles import get_theme_token, apply_cut_button_style
from gui.tabs.advanced_process.output_options import OutputOptionsWidget
from gui.tabs.advanced_process.video_details_components import RichComboBox, RichTextDelegate
from gui.tabs.advanced_process.recode_options import RecodeOptionsWidget
from gui.tabs.advanced_process.recode_controller import RecodeController
from gui.widgets.animated_button import AnimatedButton
from gui.widgets.combo_box import AutoPopupComboBox

from gui.tabs.quick_mode.activity_panel import ActivityPanel
from gui.tabs.quick_mode.download_controller import QuickDownloadController
from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon
from core.logger.logger_manager import logger
from core.tabs.quick_mode.quick_mode_logic import reveal_in_file_manager


class QuickModeTab(QWidget):
    def __init__(self):
        super().__init__()
        self.taskbar_manager = None
        self.recode_controller = RecodeController(self)
        self.init_ui()

        # Inicializar el controlador
        self.controller = QuickDownloadController(self)
        
        # Conectar señales del controlador
        self.controller.busy_state_changed.connect(self._set_busy)
        self.controller.controls_state_changed.connect(self._set_controls_enabled)
        self.controller.download_text_changed.connect(self._set_download_text)
        self.controller.progress_updated.connect(self.output_options.set_progress)

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        self.main_layout.setSpacing(8)

        self.url_panel = self._build_url_panel()
        self.options_panel = self._build_options_panel()
        
        # Instanciar el nuevo panel de actividad refactorizado
        self.activity_panel = ActivityPanel(self)
        self.activity_panel.row_close_requested.connect(self._on_row_close_requested)
        self.activity_panel.row_reveal_requested.connect(self._on_row_reveal_requested)
        self.activity_panel.cancel_all_requested.connect(self._on_cancel_all_clicked)
        self.activity_panel.clear_all_requested.connect(self._on_clear_all_clicked)

        self.output_options = OutputOptionsWidget()

        # Cabecera clicable "Recodificar" (misma tarjeta de Proceso Avanzado, ver
        # recode_options.py): vive en el MISMO renglón que options_panel (a su derecha,
        # fuera de esas opciones, en su propio recuadro), no en uno debajo - una fila
        # contenedora con QHBoxLayout reparte ambos QFrame lado a lado y Qt los estira
        # a la misma altura automáticamente (sin alignment explícito, cada widget toma
        # el alto máximo de la fila). El CUERPO (switch, preajustes, prefijo/sufijo)
        # flota sin agregarse a ningún layout, así que al expandir se dibuja por encima
        # de activity_panel/output_options en vez de empujarlos (ver conversación).
        self.recode_bar = self._build_recode_bar()

        self.options_row = QWidget()
        options_row_layout = QHBoxLayout(self.options_row)
        options_row_layout.setContentsMargins(0, 0, 0, 0)
        options_row_layout.setSpacing(8)
        options_row_layout.addWidget(self.options_panel, 1)
        options_row_layout.addWidget(self.recode_bar)

        self.main_layout.addWidget(self.url_panel)
        self.main_layout.addWidget(self.options_row)
        self.main_layout.addWidget(self.activity_panel, 1)
        self.main_layout.addWidget(self.output_options)

        self.options_panel.setAttribute(Qt.WA_StyledBackground, True)
        self.recode_bar.setAttribute(Qt.WA_StyledBackground, True)
        self.recode_bar.setObjectName("quickRecodeBar")
        self.recode_bar.setMinimumWidth(200)

        borde_color = get_theme_token('borde_normal', '#2d2d2d')
        fondo_color = get_theme_token('fondo_secundario', '#1e1e1e')
        box_style = f"""
            QFrame#analysisOptionsBar {{
                background-color: {fondo_color};
                border: 1px solid {borde_color};
                border-radius: 6px;
            }}
        """
        self.options_panel.setStyleSheet(box_style)

        # En Modo Rápido el botón "Descargar" junto a la URL ya dispara la descarga:
        # el botón de descarga duplicado dentro de "Opciones de Salida" es innecesario aquí.
        self.output_options.btn_start_download.setVisible(False)

        self.output_options.btn_open_output_path.clicked.disconnect()
        self.output_options.btn_open_output_path.clicked.connect(self._on_open_output_path_clicked)

        self.recode_options = RecodeOptionsWidget(start_expanded=False, show_header=False)
        self.recode_options.setParent(self)
        self.recode_options.hide()
        self.recode_options.toggled_collapse.connect(self._on_recode_toggled)
        self.recode_options.header_highlight_changed.connect(self._on_recode_highlight_changed)
        self._reposition_recode_popover()

        # Cerrar el popover de "Recodificar" al hacer clic afuera (de recode_bar y del
        # propio cuerpo flotante) - filtro global porque el cuerpo no usa Qt.Popup (ver
        # _reposition_recode_popover: vive como hijo normal posicionado a mano, no como
        # ventana top-level), así que Qt no lo cierra solo. Se ignora mientras haya un
        # popup interno abierto (ej. el combo de presets) para no comerle el clic.
        QApplication.instance().installEventFilter(self)

        self._on_mode_changed(self.mode_combo.currentIndex())
        self.load_labels()

    def _build_recode_bar(self):
        """Recuadro clicable "Recodificar", del mismo alto que options_panel (Qt los
        estira parejo al compartir fila en options_row, ver init_ui) - hace de
        cabecera del cuerpo flotante de recode_options (que vive sin su propia
        cabecera, ver show_header=False)."""
        bar = QFrame()
        bar.setObjectName("quickRecodeBar")
        bar.setCursor(Qt.PointingHandCursor)
        bar.setMinimumWidth(200)
        bar.setToolTip(self.tr("Abrir opciones de recodificación para convertir formatos"))
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(15, 6, 15, 6)
        layout.setSpacing(6)

        self.lbl_recode_toggle = QLabel(self.tr("Recodificar"))
        self.lbl_recode_toggle.setStyleSheet("font-weight: bold;")
        self.lbl_recode_toggle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_recode_toggle)

        bar.mousePressEvent = lambda event: self.recode_options.toggle_collapse()
        return bar

    def _on_recode_toggled(self, expanded):
        if expanded:
            self.recode_options.raise_()

    def _on_recode_highlight_changed(self, active: bool):
        """Réplica del resaltado verde de RecodeOptionsWidget.title_label sobre
        lbl_recode_toggle: aquí el header real vive oculto (show_header=False), la
        etiqueta visible es esta otra, fuera del widget."""
        if active:
            accent = get_theme_token('acento_primario', '#B9E640')
            self.lbl_recode_toggle.setStyleSheet(f"font-weight: bold; color: {accent};")
        else:
            self.lbl_recode_toggle.setStyleSheet("font-weight: bold;")

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress and self.recode_options.is_expanded:
            # No competir con un popup interno abierto (ej. el combo de presets):
            # mientras haya uno activo, dejarle su propio clic. Mismo criterio con un
            # diálogo modal encima: sus clics caen en otra ventana (este filtro está
            # sobre QApplication y ve toda la app), pero mientras está arriba el
            # usuario no puede tocar este panel, así que colapsarlo por ese clic es
            # un efecto colateral -- ver la nota larga en
            # gui/tabs/image_tools/image_tools_view.py::eventFilter.
            if QApplication.activePopupWidget() is None and QApplication.activeModalWidget() is None:
                pos = event.globalPos()
                bar_rect = QRect(self.recode_bar.mapToGlobal(QPoint(0, 0)), self.recode_bar.size())
                popup_rect = QRect(self.recode_options.mapToGlobal(QPoint(0, 0)), self.recode_options.size())
                if not bar_rect.contains(pos) and not popup_rect.contains(pos):
                    self.recode_options.toggle_collapse()
        return super().eventFilter(obj, event)

    def _build_url_panel(self):
        panel = QWidget()
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText(self.tr("Pega una URL para descargar directamente"))
        self.url_input.returnPressed.connect(self._on_download_clicked)
        self.url_input.textEdited.connect(self._on_text_edited)

        # Registrar el campo de URL en el monitor de portapapeles
        from core.utils.clipboard_monitor import ClipboardURLMonitor
        monitor = ClipboardURLMonitor.instance()
        monitor.register(self.url_input)
        monitor.url_detected.connect(self._on_clipboard_url_detected)

        # ComboBox de Etiquetas (a la derecha de corte de fragmentos)
        self.combo_tags = AutoPopupComboBox()
        self.combo_tags.setObjectName("tagsComboBox")
        self.combo_tags.setPlaceholderText(self.tr("Etiqueta"))
        self.combo_tags.setToolTip(self.tr("Aplica rutas y configuraciones predefinidas según la etiqueta elegida"))
        self.combo_tags.currentIndexChanged.connect(self._on_label_changed)

        # ComboBox de Modo (a la derecha de etiqueta)
        self.mode_combo = AutoPopupComboBox()
        self.mode_combo.setToolTip(self.tr("Elige descargar Video + Audio, Solo Audio o Solo Video"))
        self.mode_combo.addItem(self.tr("Video + Audio"), "video+audio")
        self.mode_combo.addItem(self.tr("Solo Audio"), "audio_only")
        self.mode_combo.addItem(self.tr("Solo Video"), "video_only")
        self.mode_combo.setCurrentIndex(0)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)

        # ComboBox de Calidad (a la derecha de modo)
        self.quality_combo = RichComboBox()
        self.quality_combo.setToolTip(self.tr("Selecciona la resolución o calidad máxima deseada para el medio"))
        self.quality_combo.setItemDelegate(RichTextDelegate(self.quality_combo))

        # Botón conmutable para activar el recorte de fragmentos - pegado a la URL (ver
        # conversación: antes vivía junto al de Descargar, muy lejos del campo de URL)
        self.btn_cut = QPushButton()
        self.btn_cut.setCheckable(True)
        self.btn_cut.setFixedSize(32, 32)
        self.btn_cut.setToolTip(self.tr("Activar recorte de fragmentos de video o audio"))
        self.btn_cut.setIconSize(QSize(18, 18))
        self.btn_cut.toggled.connect(self._on_cut_toggled)
        apply_cut_button_style(self.btn_cut, "normal", icon_size=18, shape="square")

        # Botón de Descarga compacto con icono SVG (mismo tamaño 32x32 que el de corte)
        self.btn_download = AnimatedButton("")
        self.btn_download.setObjectName("analyzeButton")
        self.btn_download.setFixedSize(32, 32)
        self.btn_download.setToolTip(self.tr("Descargar"))
        _icon_color = get_theme_token("boton_texto", "#000000")
        _icon = get_colored_svg_icon("download.svg", _icon_color, size=18)
        self.btn_download.setIcon(_icon)
        self.btn_download.setIconSize(QSize(18, 18))
        self.btn_download.setStyleSheet("padding: 0px;")
        self.btn_download.clicked.connect(self._on_download_clicked)

        layout.addWidget(QLabel(self.tr("URL:")))
        layout.addWidget(self.url_input, 1)
        layout.addWidget(self.btn_cut)
        layout.addWidget(self.combo_tags)
        layout.addWidget(self.mode_combo)
        layout.addWidget(self.quality_combo)
        layout.addWidget(self.btn_download)
        return panel

    def _build_options_panel(self):
        panel = QFrame()
        panel.setObjectName("analysisOptionsBar")
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(15, 6, 15, 6)
        layout.setSpacing(12)

        self.chk_playlist_selector = QCheckBox(self.tr("Playlist"))
        self.chk_playlist_selector.setToolTip(self.tr("Si es una playlist, permite elegir qué videos descargar"))
        self.chk_playlist_selector.toggled.connect(self._on_playlist_selector_toggled)
        layout.addWidget(self.chk_playlist_selector)

        # Divisor vertical para separar Playlist de las opciones de miniatura - mismo
        # estilo que advanced_process_view.py::_build_analysis_options_bar (self.divider).
        divider = QFrame()
        divider.setFixedWidth(1)
        borde_color = get_theme_token('borde_normal', '#2d2d2d')
        divider.setStyleSheet(f"background-color: {borde_color}; border: none; border-radius: 0px;")
        layout.addWidget(divider)

        self.chk_thumb_file = QCheckBox(self.tr("Guardar miniatura"))
        self.chk_thumb_file.setToolTip(self.tr("Guarda también la imagen de portada en un archivo aparte"))
        layout.addWidget(self.chk_thumb_file)

        self.chk_thumb_only = QCheckBox(self.tr("Solo miniatura"))
        self.chk_thumb_only.setToolTip(self.tr("Descarga EXCLUSIVAMENTE la imagen de portada (no descarga el video/audio)"))
        self.chk_thumb_only.toggled.connect(self._on_thumbnail_only_toggled)
        layout.addWidget(self.chk_thumb_only)

        layout.addStretch(1)
        return panel

    def showEvent(self, event):
        super().showEvent(event)
        # Inicializamos el gestor en el showEvent para asegurar que window() sea válido
        # (mismo patrón que AdvancedProcessTab).
        if not self.taskbar_manager:
            from core.utils.taskbar_progress import TaskbarProgressManager
            try:
                hwnd = int(self.window().winId())
                self.taskbar_manager = TaskbarProgressManager(hwnd)
                logger.info(f"QuickModeTab: TaskbarProgressManager vinculado a HWND {hwnd}")
            except Exception as e:
                logger.error(f"QuickModeTab: No se pudo inicializar TaskbarProgressManager: {e}")
        self._reposition_recode_popover()

        # Iniciar tutorial si no se ha visto
        from core.utils.config_manager import get_config, save_config
        config = get_config()
        if not config.get("tutorial_quick_mode_seen", False):
            config["tutorial_quick_mode_seen"] = True
            save_config(config)
            # Retrasar un poco para asegurar que la UI está lista y renderizada
            from PySide6.QtCore import QTimer
            QTimer.singleShot(300, self.start_tutorial)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_recode_popover()

    def _reposition_recode_popover(self):
        """Iguala el alto de recode_bar al de options_panel (comparten fila en
        options_row, pero por las dudas se fuerza igual - piden que se vean como
        recuadros pares) y ancla el cuerpo flotante de recode_options justo debajo,
        con su borde derecho alineado al de recode_bar (que al ser compacto y vivir
        pegado a la derecha de la fila, un cuerpo más ancho que él se iría fuera de
        la ventana si se alineara por la izquierda). Se reposiciona (no se re-crea)
        en cada resize, y siempre se re-eleva por si algo la tapó."""
        if not hasattr(self, "recode_options") or not hasattr(self, "recode_bar"):
            return
        panel_h = self.options_panel.height()
        if panel_h > 0 and self.recode_bar.height() != panel_h:
            self.recode_bar.setFixedHeight(panel_h)

        # recode_bar es hijo de options_row, no de self directamente - mapear su
        # posición a coordenadas de self (el padre real del cuerpo flotante).
        top_left = self.recode_bar.mapTo(self, self.recode_bar.rect().topLeft())
        bar_w = self.recode_bar.width()
        bar_h = self.recode_bar.height()

        width = max(260, min(RecodeOptionsWidget.COMPACT_WIDTH, self.width() - 20))
        x = max(10, top_left.x() + bar_w - width)
        y = top_left.y() + bar_h + 3
        self.recode_options.setFixedWidth(width)
        self.recode_options.move(x, y)
        if self.recode_options.isVisible():
            self.recode_options.raise_()

    def _on_mode_changed(self, index):
        mode = self.mode_combo.itemData(index) or "video+audio"
        current = self.quality_combo.currentData()
        self.quality_combo.blockSignals(True)
        self.quality_combo.clear()

        self.quality_combo.addItem(self.tr("Mejor compatible") + " ✨", "best_compatible")
        self.quality_combo.addItem(self.tr("Máxima calidad"), "best")
        if mode != "audio_only":
            self.quality_combo.addItem("4K (2160p)", "2160")
            self.quality_combo.addItem("2K (1440p)", "1440")
            self.quality_combo.addItem("1080p", "1080")
            self.quality_combo.addItem("720p", "720")
            self.quality_combo.addItem("480p", "480")
            self.quality_combo.addItem("360p", "360")
        else:
            self.quality_combo.addItem(self.tr("Alta"), "320")
            self.quality_combo.addItem(self.tr("Media"), "192")
            self.quality_combo.addItem(self.tr("Baja"), "128")

        if current:
            idx = self.quality_combo.findData(current)
            if idx >= 0:
                self.quality_combo.setCurrentIndex(idx)
            else:
                self.quality_combo.setCurrentIndex(0)
        else:
            self.quality_combo.setCurrentIndex(0)
        self.quality_combo.blockSignals(False)

    def _on_thumbnail_only_toggled(self, checked):
        self.mode_combo.setEnabled(not checked)
        self.quality_combo.setEnabled(not checked)
        self.chk_thumb_file.setEnabled(not checked)
        # "Solo miniatura" descarga una imagen, no un medio recodificable.
        self.recode_bar.setEnabled(not checked)
        self.recode_options.setEnabled(not checked)
        if checked:
            self.recode_options.switch_recode.setChecked(False)

    def _on_playlist_selector_toggled(self, checked):
        """Cuando playlist está activa, deshabilitar y desactivar el corte de fragmento."""
        if checked:
            self.btn_cut.setChecked(False)
            self.btn_cut.setEnabled(False)
        else:
            self.btn_cut.setEnabled(True)

    def _on_download_clicked(self):
        url = self.url_input.text().strip()
        if not url:
            return

        # Delegar la descarga al controlador
        self.controller.start_download_flow(
            url=url,
            mode=self.mode_combo.currentData() or "video+audio",
            quality=self.quality_combo.currentData() or "best_compatible",
            output_path=self.output_options.output_path_input.text(),
            speed_limit_val=self.output_options.speed_limit_input.value(),
            chk_thumb_file_checked=self.chk_thumb_file.isChecked(),
            chk_thumb_only_checked=self.chk_thumb_only.isChecked(),
            btn_cut_checked=self.btn_cut.isChecked(),
            chk_playlist_selector_checked=self.chk_playlist_selector.isChecked(),
            recode_data=self.recode_controller.collect_recode_data(),
        )
        self.url_input.clear()

    def _on_open_output_path_clicked(self):
        path = self.output_options.output_path_input.text().strip()
        if not path:
            return
        if self.controller.last_downloaded_filepath and os.path.exists(self.controller.last_downloaded_filepath):
            reveal_in_file_manager(self.controller.last_downloaded_filepath)
            return

        if os.path.exists(path):
            if os.name == "nt":
                os.startfile(path if os.path.isdir(path) else os.path.dirname(path))
            else:
                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QDesktopServices
                QDesktopServices.openUrl(QUrl.fromLocalFile(path if os.path.isdir(path) else os.path.dirname(path)))

    def _on_row_close_requested(self, row):
        """Quitar un item de la lista. Si estaba descargándose activamente, cancela."""
        if row not in self.activity_panel.item_rows:
            return
            
        if row in self.controller.current_item_rows:
            idx = self.controller.current_item_rows.index(row)
            self.controller.current_item_rows.pop(idx)
            if idx < len(self.controller.current_item_keys):
                self.controller.current_item_keys.pop(idx)
                
        # Delegamos en el controller cancelar los procesos (descargas/recodificaciones) asociados a esta fila
        self.controller.cancel_row(row)
                
        self.activity_panel.remove_row(row)

    def _on_row_reveal_requested(self, row):
        """Abrir el gestor de archivos y seleccionar el archivo descargado."""
        if row.downloaded_filepath and os.path.exists(row.downloaded_filepath):
            reveal_in_file_manager(row.downloaded_filepath)

    def _on_cancel_all_clicked(self):
        """Cancelar descargas activas en curso."""
        if self.controller.is_downloading:
            self.controller.cancel_download()

    def _on_clear_all_clicked(self):
        """Cancelar descargas activas y limpiar toda la lista."""
        if self.controller.is_downloading:
            self.controller.cancel_download()
        self.activity_panel.clear_activity_rows()

    def _set_busy(self, busy, message=None):
        self._set_controls_enabled(not busy)
        self._set_download_text(self.tr("Analizando...") if busy else self.tr("Descargar"))
        if message:
            self.output_options.set_progress(0, message, "running" if busy else "wait")

    def _set_controls_enabled(self, enabled):
        # El campo de URL y el botón de descarga siempre se mantienen habilitados para permitir encolar/añadir
        self.url_input.setEnabled(True)
        self.btn_download.setEnabled(enabled or self.controller.is_downloading)
        self.options_panel.setEnabled(enabled)
        self.mode_combo.setEnabled(enabled and not self.chk_thumb_only.isChecked())
        self.quality_combo.setEnabled(enabled and not self.chk_thumb_only.isChecked())
        self.combo_tags.setEnabled(enabled)
        self.recode_bar.setEnabled(enabled and not self.chk_thumb_only.isChecked())
        self.recode_options.setEnabled(enabled and not self.chk_thumb_only.isChecked())
        self.output_options.output_path_input.setEnabled(enabled and self.combo_tags.currentIndex() <= 0)
        self.output_options.btn_select_output_path.setEnabled(enabled and self.combo_tags.currentIndex() <= 0)
        self.output_options.speed_limit_input.setEnabled(enabled)
        
        # btn_cut: solo habilitar si playlist_selector no está activo
        if enabled:
            self.btn_cut.setEnabled(not self.chk_playlist_selector.isChecked())
        else:
            self.btn_cut.setEnabled(False)

    def _set_download_text(self, text):
        self.btn_download.setToolTip(text)

    def _on_clipboard_url_detected(self, url):
        """Llamado cuando el monitor de portapapeles pega una URL en nuestro campo."""
        if self.url_input.text().strip() != url:
            return
        if self.controller.is_downloading:
            return
        from core.utils.config_manager import get_config
        if get_config().get("auto_analyze", False):
            logger.info("QuickModeTab: Auto-inicio por pegado automático de URL")
            self._on_download_clicked()

    def _on_text_edited(self, text):
        """Llamado cuando el usuario edita el texto manualmente (incluyendo pegar)."""
        url = text.strip()
        if not url:
            return
        if self.controller.is_downloading:
            return
            
        from core.utils.config_manager import get_config
        if not get_config().get("auto_analyze", False):
            return
            
        if not url.startswith(("http://", "https://")):
            return
            
        from PySide6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        if clipboard:
            clip_text = clipboard.text().strip()
            if url == clip_text:
                logger.info("QuickModeTab: Detección de pegado manual. Iniciando descarga...")
                self._on_download_clicked()

    def _on_cut_toggled(self, checked: bool):
        status = "saved" if checked else "normal"
        apply_cut_button_style(self.btn_cut, status, icon_size=18, shape="square")

    def load_labels(self):
        """Carga las etiquetas configuradas en la aplicación en el combo de etiquetas con círculos de color."""
        if not hasattr(self, "combo_tags"):
            return
        from gui.styles import create_colored_circle_icon, update_label_combobox_style
        from core.utils.config_manager import get_config
        from PySide6.QtGui import QColor

        self.combo_tags.blockSignals(True)
        current_text = self.combo_tags.currentText()
        self.combo_tags.clear()
        self.combo_tags.addItem(self.tr("Etiqueta"), "")

        config = get_config()
        labels = config.get("labels", [])
        for label in labels:
            name = label.get("name", "")
            path = label.get("path", "")
            color = label.get("color", "#B9E640")

            idx = self.combo_tags.count()
            icon = create_colored_circle_icon(color, size=12)
            self.combo_tags.addItem(icon, name, path)

            self.combo_tags.setItemData(idx, color, Qt.UserRole + 1)
            self.combo_tags.setItemData(idx, QColor(color), Qt.ForegroundRole)

        # Intentar restaurar selección si aún existe
        idx = self.combo_tags.findText(current_text)
        if idx >= 0:
            self.combo_tags.setCurrentIndex(idx)
        else:
            self.combo_tags.setCurrentIndex(0)

        self.combo_tags.blockSignals(False)
        self._update_combo_style()

    def _update_combo_style(self):
        """Actualiza el color de texto del combo según la etiqueta seleccionada."""
        if hasattr(self, "combo_tags"):
            from gui.styles import update_label_combobox_style
            update_label_combobox_style(self.combo_tags)

    def _on_label_changed(self, index):
        """Maneja el cambio de selección en el combobox de etiquetas."""
        self._update_combo_style()
        if index <= 0:
            # Ninguna etiqueta seleccionada: restaurar ruta por defecto
            from core.tabs.advanced_process.output_logic import get_default_download_path
            default_path = get_default_download_path()
            self.output_options.output_path_input.setText(default_path)
            self.output_options.output_path_input.setEnabled(True)
            self.output_options.btn_select_output_path.setEnabled(True)
        else:
            # Etiqueta seleccionada: actualizar ruta y bloquear edición
            path = self.combo_tags.currentData()
            if path:
                self.output_options.output_path_input.setText(path)
            self.output_options.output_path_input.setEnabled(False)
            self.output_options.btn_select_output_path.setEnabled(False)


    def start_tutorial(self):
        from gui.widgets.tutorial_overlay import TutorialOverlay
        from PySide6.QtWidgets import QApplication, QPushButton

        # Ventanas simuladas
        self._dummy_frag_dialog = None
        self._dummy_playlist_dialog = None

        def run_frag_tutorial():
            if self.tutorial_overlay.is_skipping: return
            from gui.dialogs.fragment_dialog import FragmentDialog
            self._dummy_frag_dialog = FragmentDialog(self, duration=300, fps=30)
            
            frag_steps = [
                {
                    "widgets": [self._dummy_frag_dialog.range_slider],
                    "title": self.tr("Selector de Corte"),
                    "desc": self.tr("Aquí puedes elegir el inicio y fin exacto del fragmento que deseas descargar.")
                },
                {
                    "widgets": [self._dummy_frag_dialog.btn_add_ctrl],
                    "title": self.tr("Añadir Fragmento"),
                    "desc": self.tr("Usa el botón '+' para guardar el corte en la lista de la derecha.")
                },
                {
                    "widgets": [self._dummy_frag_dialog.rb_precise, self._dummy_frag_dialog.rb_download, self._dummy_frag_dialog.rb_keep],
                    "title": self.tr("Opciones de Corte"),
                    "desc": self.tr("Elige la modalidad: Corte preciso, Descargar para cortar, o Conservar el original completo.")
                },
                {
                    "widgets": [self._dummy_frag_dialog.btn_save],
                    "title": self.tr("Guardar y Descargar"),
                    "desc": self.tr("Al guardar, empezará inmediatamente la descarga de esos fragmentos.")
                }
            ]
            
            sub_tut = TutorialOverlay(self._dummy_frag_dialog, frag_steps)
            sub_tut.finished.connect(self._dummy_frag_dialog.accept)
            
            self.tutorial_overlay.card.hide()
            self._dummy_frag_dialog.exec()
            self.tutorial_overlay.card.show()
            
            self._dummy_frag_dialog.deleteLater()
            self._dummy_frag_dialog = None

        def run_playlist_tutorial():
            if self.tutorial_overlay.is_skipping: return
            from gui.dialogs.playlist_selection_dialog import PlaylistSelectionDialog
            dummy_info = {
                "title": "Tutorial Playlist",
                "entries": [{"title": self.tr("Video 1")}, {"title": self.tr("Video 2")}]
            }
            self._dummy_playlist_dialog = PlaylistSelectionDialog(dummy_info, self)
            
            btn_accept = self._dummy_playlist_dialog.findChild(QPushButton, "analyzeButton")
            
            play_steps = [
                {
                    "widgets": [self._dummy_playlist_dialog.scroll],
                    "title": self.tr("Selección de Medios"),
                    "desc": self.tr("Aquí puedes marcar o desmarcar qué videos específicos de la playlist quieres descargar.")
                },
                {
                    "widgets": [self._dummy_playlist_dialog.mode_combo, self._dummy_playlist_dialog.quality_combo],
                    "title": self.tr("Controles Internos"),
                    "desc": self.tr("Los controles de Modo y Calidad se manejan internamente aquí. Las opciones de afuera no afectarán a la playlist.")
                },
                {
                    "widgets": [btn_accept],
                    "title": self.tr("Aceptar"),
                    "desc": self.tr("Al aceptar, se guardará la configuración para esta playlist.")
                }
            ]
            
            sub_tut = TutorialOverlay(self._dummy_playlist_dialog, play_steps)
            sub_tut.finished.connect(self._dummy_playlist_dialog.accept)
            
            self.tutorial_overlay.card.hide()
            self._dummy_playlist_dialog.exec()
            self.tutorial_overlay.card.show()
            
            self._dummy_playlist_dialog.deleteLater()
            self._dummy_playlist_dialog = None

        steps = [
            {
                "widgets": [self.url_input],
                "title": self.tr("Pegado de Enlaces"),
                "desc": self.tr("DowP pega automáticamente toda URL que tengas en tu portapapeles, pero también puedes hacerlo manualmente con CTRL + V o clic derecho y 'pegar'. Si esta opción no te gusta, puedes desactivarla en Ajustes -> General.")
            },
            {
                "widgets": [self.combo_tags],
                "title": self.tr("Etiquetas de Carpeta"),
                "desc": self.tr("Las etiquetas se configuran desde 'Ajustes -> Etiquetas' y sirven para preconfigurar distintas rutas a tu gusto para la descarga de medios, para que ya no tengas que estar configurando las rutas en las opciones de salida para cada medio.")
            },
            {
                "widgets": [self.mode_combo, self.quality_combo],
                "title": self.tr("Modos y Calidades"),
                "desc": self.tr("Selecciona las opciones rápidas que necesites como Video + Audio, Solo Audio o Solo Video y sus respectivas calidades. Aquí la opción de 'Mejor compatible' siempre buscará la calidad del medio que sea compatible con los programas de Adobe.")
            },
            {
                "widgets": [self.btn_cut],
                "title": self.tr("Recorte de Fragmentos"),
                "desc": self.tr("Al seleccionar esta opción puedes escoger fragmentos de un medio. Se abrirá una ventana donde puedes controlar exactamente qué parte del video quieres descargar y sus opciones de corte."),
                "on_leave": run_frag_tutorial
            },
            {
                "widgets": [self.chk_playlist_selector],
                "title": self.tr("Descarga de Playlist"),
                "desc": self.tr("Al habilitar esta opción también se despliega una ventana. En esta ventana de playlist puedes seleccionar qué medios de la lista quieres descargar y cuáles no. Los controles de modo y calidad se manejan internamente en la ventana (aquí no mandan las opciones externas), y TODAS LAS PLAYLIST se descargan en una carpeta con el título de la playlist, el cual en el Modo Rápido no es editable (eso es para el Modo Avanzado)."),
                "on_leave": run_playlist_tutorial
            },
            {
                "widgets": [self.options_panel],
                "title": self.tr("Opciones de Descarga"),
                "desc": self.tr("En esta sección se decide si quieres guardar los medios junto con sus miniaturas/carátulas, o descargar únicamente las miniaturas/carátulas.")
            },
            {
                "widgets": [self.recode_bar],
                "title": self.tr("Recodificación Post-Descarga"),
                "desc": self.tr("En esta sección puedes decidir un post-procesado luego de una descarga de forma opcional, para convertirlo a otros formatos o crear proxys para mayor compatibilidad con otros editores.")
            },
            {
                "widgets": [self.activity_panel],
                "title": self.tr("Lista de Descargas y Tareas"),
                "desc": self.tr("Aquí aparecerán todas las descargas/procesos que hagas. Cada una cuenta con barra de progreso y son arrastrables una vez terminadas. Funciona como un explorador de archivos: simplemente arrastra tu medio a tu editor o carpeta.")
            },
            {
                "widgets": [self.output_options],
                "title": self.tr("Opciones de Salida"),
                "desc": self.tr("Decide a dónde mandar los medios, qué hacer con duplicados, limitar la velocidad de descarga y ver el progreso general. Si seleccionaste una etiqueta previamente, la ruta se bloqueará; selecciona 'Etiqueta' para dejarlo en default y recuperar el control.")
            },
            {
                "widgets": [self.btn_download],
                "title": self.tr("¡Empezar Descarga!"),
                "desc": self.tr("UNA VEZ CONFIGURES TODO A TU GUSTO O NECESIDAD, PUEDES PRESIONAR EL BOTÓN DE DESCARGAR PARA EMPEZAR.")
            }
        ]

        main_window = self.window()
        self.tutorial_overlay = TutorialOverlay(main_window, steps)
        self.tutorial_overlay.resize(main_window.size())
        self.tutorial_overlay.show()
