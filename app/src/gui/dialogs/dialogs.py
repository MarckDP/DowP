# src/gui/tabs/single_process/dialogs.py
from PySide6.QtWidgets import (QMessageBox, QDialog, QVBoxLayout, QHBoxLayout,
                                 QLabel, QLineEdit, QPushButton, QFileDialog, QColorDialog, QSlider, QWidget, QFrame,
                                 QComboBox)
from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QLinearGradient
import os
from core.logger.logger_manager import logger
from gui.styles import apply_folder_browse_button_style

def _apply_dialog_styles(msg_box):
    """
    Aplica el estilo de botones unificado del tema activo a un QMessageBox.
    """
    try:
        from gui.styles import get_theme_token
        bg_color = get_theme_token("boton_secundario_fondo", "#1b3b22")
        fg_color = get_theme_token("boton_secundario_texto", "#B9E640")
        hover_color = get_theme_token("boton_secundario_hover", "#224a2b")
        btn_style = f"""
            QPushButton {{
                background-color: {bg_color};
                color: {fg_color};
                border: none;
                border-radius: 6px;
                padding: 5px 12px;
                font-weight: bold;
                min-width: 50px;
                min-height: 22px;
            }}
            QPushButton:hover {{
                background-color: {hover_color};
            }}
        """
        for button in msg_box.buttons():
            button.setStyleSheet(btn_style)
    except Exception as e:
        logger.error(f"Error cargando estilos para el diálogo: {e}")

def _translate_dialog_text(parent, text: str) -> str:
    if not isinstance(text, str) or not text:
        return text
    if parent and hasattr(parent, "tr"):
        res = parent.tr(text)
        if res != text:
            return res
    from PySide6.QtCore import QCoreApplication
    res = QCoreApplication.translate("dialogs", text)
    if res != text:
        return res
    return text

def show_warning_confirm(parent, title, text):
    """
    Muestra un diálogo de advertencia con botones Sí/No (Yes/No).
    Retorna True si el usuario responde Sí, False si responde No.
    """
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Icon.Warning)
    msg.setWindowTitle(_translate_dialog_text(parent, title))
    msg.setText(_translate_dialog_text(parent, text))
    msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    msg.setDefaultButton(QMessageBox.StandardButton.No)
    _apply_dialog_styles(msg)
    ret = msg.exec()
    return ret == QMessageBox.StandardButton.Yes

def show_info(parent, title, text):
    """
    Muestra un diálogo de información con el botón Aceptar (Ok).
    """
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Icon.Information)
    msg.setWindowTitle(_translate_dialog_text(parent, title))
    msg.setText(_translate_dialog_text(parent, text))
    msg.setStandardButtons(QMessageBox.StandardButton.Ok)
    _apply_dialog_styles(msg)
    msg.exec()

def show_warning(parent, title, text):
    """
    Muestra un diálogo de advertencia simple con el botón Aceptar (Ok).
    """
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Icon.Warning)
    msg.setWindowTitle(_translate_dialog_text(parent, title))
    msg.setText(_translate_dialog_text(parent, text))
    msg.setStandardButtons(QMessageBox.StandardButton.Ok)
    _apply_dialog_styles(msg)
    msg.exec()


class AddLabelDialog(QDialog):
    def __init__(self, parent=None, edit_data=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._edit_data = edit_data  # {"name": ..., "path": ..., "color": ...} or None
        if edit_data:
            self.setWindowTitle(self.tr("Editar Etiqueta"))
            self.selected_color = edit_data.get("color", "#B9E640")
        else:
            self.setWindowTitle(self.tr("Agregar Nueva Etiqueta"))
            self.selected_color = "#B9E640"  # Accent color
        self.setFixedSize(380, 256)
        self.init_ui()
        if edit_data:
            self.name_input.setText(edit_data.get("name", ""))
            self.path_input.setText(edit_data.get("path", ""))

    def init_ui(self):
        from gui.widgets.title_bar import CustomTitleBar
        from gui.styles import get_theme_token

        # Main layout of the dialog (no margins)
        main_dialog_layout = QVBoxLayout(self)
        main_dialog_layout.setContentsMargins(0, 0, 0, 0)
        main_dialog_layout.setSpacing(0)

        # Central widget container for styling
        self.central_widget = QFrame()
        self.central_widget.setObjectName("AddLabelDialogContainer")
        self.central_widget.setStyleSheet(f"""
            QFrame#AddLabelDialogContainer {{
                background-color: {get_theme_token("fondo_secundario", "#1e1e1e")};
                border: 1px solid {get_theme_token("borde", "#2d2d2d")};
                border-radius: 6px;
            }}
            QLabel {{
                color: {get_theme_token("texto_principal", "#ffffff")};
                font-size: 12px;
                border: none;
                background: transparent;
            }}
            QLineEdit {{
                background-color: {get_theme_token("fondo_principal", "#121212")};
                color: {get_theme_token("texto_principal", "#ffffff")};
                border: 1px solid {get_theme_token("borde", "#2d2d2d")};
                border-radius: 6px;
                padding: 6px;
            }}
            QPushButton#dialogButton {{
                background-color: {get_theme_token("boton_secundario_fondo", "#1b3b22")};
                color: {get_theme_token("boton_secundario_texto", "#B9E640")};
                border: none;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: bold;
            }}
            QPushButton#dialogButton:hover {{
                background-color: {get_theme_token("boton_secundario_hover", "#224a2b")};
            }}
            QPushButton#dialogCancelButton {{
                background-color: transparent;
                color: #e74c3c;
                border: 1px solid #e74c3c;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: bold;
            }}
            QPushButton#dialogCancelButton:hover {{
                background-color: rgba(231, 76, 60, 0.15);
            }}
            QPushButton#dialogCancelButton:pressed {{
                background-color: rgba(231, 76, 60, 0.3);
            }}
        """)
        main_dialog_layout.addWidget(self.central_widget)

        # Internal vertical layout for central_widget
        central_layout = QVBoxLayout(self.central_widget)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        # Title bar
        title_text = self.windowTitle()
        self.title_bar = CustomTitleBar(self, title_text)
        self.title_bar.btn_min.hide()
        self.title_bar.btn_max.hide()
        self.title_bar.btn_close.clicked.disconnect()
        self.title_bar.btn_close.clicked.connect(self.reject)
        self.title_bar.setStyleSheet("""
            CustomTitleBar {
                background-color: #0d0d0d;
                border-bottom: 1px solid #222222;
                border-top-left-radius: 11px;
                border-top-right-radius: 11px;
            }
        """)
        central_layout.addWidget(self.title_bar)

        # Content layout inside the central frame
        layout = QVBoxLayout()
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(8)

        # Name & Color row (Horizontal Layout)
        name_color_layout = QHBoxLayout()
        name_color_layout.setSpacing(15)

        # Name field
        name_layout = QVBoxLayout()
        name_layout.setSpacing(4)
        self.lbl_name = QLabel(self.tr("Nombre de la etiqueta:"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText(self.tr("ej: Música"))
        name_layout.addWidget(self.lbl_name)
        name_layout.addWidget(self.name_input)

        # Color field
        color_layout = QVBoxLayout()
        color_layout.setSpacing(4)
        self.lbl_color = QLabel(self.tr("Color:"))
        
        self.color_button_layout = QHBoxLayout()
        self.color_button_layout.setContentsMargins(0, 0, 0, 0)
        self.btn_color = QPushButton()
        self.btn_color.setFixedSize(30, 30)
        self.btn_color.setCursor(Qt.PointingHandCursor)
        self.btn_color.setStyleSheet(f"background-color: {self.selected_color}; border: 1px solid #ffffff; border-radius: 15px;")
        self.btn_color.clicked.connect(self.pick_color)
        self.color_button_layout.addWidget(self.btn_color)
        self.color_button_layout.addStretch()

        color_layout.addWidget(self.lbl_color)
        color_layout.addLayout(self.color_button_layout)

        name_color_layout.addLayout(name_layout, 1) # stretch 1
        name_color_layout.addLayout(color_layout)
        layout.addLayout(name_color_layout)

        # Path row (Grouped inside a QVBoxLayout to keep label and input close)
        path_container_layout = QVBoxLayout()
        path_container_layout.setSpacing(4)

        self.lbl_path = QLabel(self.tr("Ruta de salida:"))
        path_layout = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText(self.tr("Selecciona una carpeta"))
        
        self.btn_browse = QPushButton()
        self.btn_browse.setFixedSize(30, 30)
        self.btn_browse.setCursor(Qt.PointingHandCursor)
        apply_folder_browse_button_style(self.btn_browse, self.tr("Seleccionar carpeta para la etiqueta"))
        self.btn_browse.clicked.connect(self.browse_path)
        
        path_layout.addWidget(self.path_input, 1)
        path_layout.addWidget(self.btn_browse)

        path_container_layout.addWidget(self.lbl_path)
        path_container_layout.addLayout(path_layout)
        layout.addLayout(path_container_layout)

        # Error feedback
        self.error_lbl = QLabel("")
        self.error_lbl.setStyleSheet("color: #e74c3c; font-size: 11px;")
        self.error_lbl.hide()  # Ocultar por defecto
        layout.addWidget(self.error_lbl)

        # Actions row
        actions_layout = QHBoxLayout()
        
        self.btn_cancel = QPushButton(self.tr("Cancelar"))
        self.btn_cancel.setObjectName("dialogCancelButton")
        self.btn_cancel.clicked.connect(self.reject)
        
        self.btn_save = QPushButton(self.tr("Guardar"))
        self.btn_save.setObjectName("dialogButton")
        self.btn_save.clicked.connect(self.save_label)
        
        actions_layout.addStretch()
        actions_layout.addWidget(self.btn_cancel)
        actions_layout.addWidget(self.btn_save)
        layout.addLayout(actions_layout)

        central_layout.addLayout(layout)

    def browse_path(self):
        path = QFileDialog.getExistingDirectory(self, self.tr("Seleccionar carpeta para la etiqueta"), "")
        if path:
            self.path_input.setText(path)

    def pick_color(self):
        dialog = AdobeColorPickerDialog(self.selected_color, self)
        if dialog.exec():
            self.selected_color = dialog.get_color()
            self.btn_color.setStyleSheet(f"background-color: {self.selected_color}; border: 1px solid #ffffff; border-radius: 12px;")

    def save_label(self):
        name = self.name_input.text().strip()
        path = self.path_input.text().strip()

        if not name:
            self.error_lbl.setText(self.tr("El nombre no puede estar vacío."))
            self.error_lbl.show()
            return
        if not path:
            self.error_lbl.setText(self.tr("La ruta no puede estar vacía."))
            self.error_lbl.show()
            return
        if not os.path.exists(path):
            self.error_lbl.setText(self.tr("La ruta seleccionada no existe."))
            self.error_lbl.show()
            return

        # Check duplicate (skip if editing and name unchanged)
        from core.utils.config_manager import get_config
        config = get_config()
        labels = config.get("labels", [])
        original_name = self._edit_data.get("name", "") if self._edit_data else ""
        for label in labels:
            if label["name"].lower() == name.lower() and name.lower() != original_name.lower():
                self.error_lbl.setText(self.tr("Ya existe una etiqueta con este nombre."))
                self.error_lbl.show()
                return

        self.accept()

    def get_data(self):
        return {
            "name": self.name_input.text().strip(),
            "path": self.path_input.text().strip(),
            "color": self.selected_color
        }


class SavePresetDialog(QDialog):
    """Diálogo simple para pedir el nombre de un preset nuevo (ver gui.widgets.preset_bar.
    PresetBar). Reemplaza al patrón anterior de escribir el nombre directo en el combo
    -no tenía sentido tener que escribir dentro de un combo pensado para elegir de una
    lista existente."""
    def __init__(self, parent=None, existing_names=None, default_function=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle(self.tr("Guardar como preajuste"))
        self.setFixedSize(360, 230)
        self._existing_names = existing_names or []
        self._default_function = default_function
        self.result_name = None
        self.result_function = None
        self.init_ui()

    def init_ui(self):
        from gui.widgets.title_bar import CustomTitleBar
        from gui.styles import get_theme_token

        main_dialog_layout = QVBoxLayout(self)
        main_dialog_layout.setContentsMargins(0, 0, 0, 0)
        main_dialog_layout.setSpacing(0)

        self.central_widget = QFrame()
        self.central_widget.setObjectName("SavePresetDialogContainer")
        self.central_widget.setStyleSheet(f"""
            QFrame#SavePresetDialogContainer {{
                background-color: {get_theme_token("fondo_secundario", "#1e1e1e")};
                border: 1px solid {get_theme_token("borde", "#2d2d2d")};
                border-radius: 6px;
            }}
            QLabel {{
                color: {get_theme_token("texto_principal", "#ffffff")};
                font-size: 12px;
                border: none;
                background: transparent;
            }}
            QLineEdit, QComboBox {{
                background-color: {get_theme_token("fondo_principal", "#121212")};
                color: {get_theme_token("texto_principal", "#ffffff")};
                border: 1px solid {get_theme_token("borde", "#2d2d2d")};
                border-radius: 6px;
                padding: 6px;
            }}
            QPushButton#dialogButton {{
                background-color: {get_theme_token("boton_secundario_fondo", "#1b3b22")};
                color: {get_theme_token("boton_secundario_texto", "#B9E640")};
                border: none;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: bold;
            }}
            QPushButton#dialogButton:hover {{
                background-color: {get_theme_token("boton_secundario_hover", "#224a2b")};
            }}
            QPushButton#dialogCancelButton {{
                background-color: transparent;
                color: #e74c3c;
                border: 1px solid #e74c3c;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: bold;
            }}
            QPushButton#dialogCancelButton:hover {{
                background-color: rgba(231, 76, 60, 0.15);
            }}
        """)
        main_dialog_layout.addWidget(self.central_widget)

        central_layout = QVBoxLayout(self.central_widget)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        self.title_bar = CustomTitleBar(self, self.windowTitle())
        self.title_bar.btn_min.hide()
        self.title_bar.btn_max.hide()
        self.title_bar.btn_close.clicked.disconnect()
        self.title_bar.btn_close.clicked.connect(self.reject)
        self.title_bar.setStyleSheet("""
            CustomTitleBar {
                background-color: #0d0d0d;
                border-bottom: 1px solid #222222;
                border-top-left-radius: 11px;
                border-top-right-radius: 11px;
            }
        """)
        central_layout.addWidget(self.title_bar)

        layout = QVBoxLayout()
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(8)

        self.lbl_name = QLabel(self.tr("Nombre del preajuste:"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText(self.tr("ej: ProRes Proxy"))
        self.name_input.returnPressed.connect(self._on_save_clicked)
        layout.addWidget(self.lbl_name)
        layout.addWidget(self.name_input)

        # Categoría de "qué hace" el preajuste (ver core.utils.preset_manager.
        # PRESET_FUNCTIONS) - independiente de qué pestaña lo armó, pensado para un
        # futuro filtro/menú universal (ver conversación). Siempre visible y editable
        # (nunca se pre-fija sin poder cambiarla): Avanzado puede armar cualquier cosa,
        # así que no hay una función "correcta" única que asumir por default ahí.
        from core.utils.preset_manager import PRESET_FUNCTIONS
        self.lbl_function = QLabel(self.tr("Tipo de tarea:"))
        self.combo_function = QComboBox()
        self.combo_function.setCursor(Qt.PointingHandCursor)
        for func_id, label in PRESET_FUNCTIONS.items():
            self.combo_function.addItem(QCoreApplication.translate("preset_manager", label), func_id)
        if self._default_function:
            idx = self.combo_function.findData(self._default_function)
            if idx >= 0:
                self.combo_function.setCurrentIndex(idx)
        layout.addWidget(self.lbl_function)
        layout.addWidget(self.combo_function)

        self.error_lbl = QLabel("")
        self.error_lbl.setStyleSheet("color: #e74c3c; font-size: 11px;")
        self.error_lbl.hide()
        layout.addWidget(self.error_lbl)

        actions_layout = QHBoxLayout()
        self.btn_cancel = QPushButton(self.tr("Cancelar"))
        self.btn_cancel.setObjectName("dialogCancelButton")
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_save = QPushButton(self.tr("Guardar"))
        self.btn_save.setObjectName("dialogButton")
        self.btn_save.clicked.connect(self._on_save_clicked)

        actions_layout.addStretch()
        actions_layout.addWidget(self.btn_cancel)
        actions_layout.addWidget(self.btn_save)
        layout.addLayout(actions_layout)

        central_layout.addLayout(layout)
        self.name_input.setFocus()

    def _on_save_clicked(self):
        name = self.name_input.text().strip()
        if not name:
            self.error_lbl.setText(self.tr("El nombre no puede estar vacío."))
            self.error_lbl.show()
            return
        if name in self._existing_names:
            resp = show_warning_confirm(
                self,
                self.tr("Sobrescribir preset"),
                self.tr("El preset '{0}' ya existe. ¿Sobrescribirlo?").format(name),
            )
            if not resp:
                return
        self.result_name = name
        self.result_function = self.combo_function.currentData()
        self.accept()


class PdfPageRangeDialog(QDialog):
    """Rango de páginas al importar un PDF de varias páginas al Editor de Imagen
    (ver ImageQueueWidget._resolve_pdf_pages en
    gui/tabs/image_tools/image_queue_widget.py) -- mismo diálogo que tenía
    DowP1. Mismo patrón visual que SavePresetDialog (un solo QLineEdit +
    error_lbl), la validación real vive en
    core/tabs/image_tools/pdf_pages.py::parse_page_range."""

    def __init__(self, parent, filename: str, page_count: int):
        super().__init__(parent)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle(self.tr("Rango de páginas"))
        self.setFixedSize(360, 210)
        self._filename = filename
        self._page_count = page_count
        self.result_pages: list[int] | None = None
        self.init_ui()

    def init_ui(self):
        from gui.widgets.title_bar import CustomTitleBar
        from gui.styles import get_theme_token

        main_dialog_layout = QVBoxLayout(self)
        main_dialog_layout.setContentsMargins(0, 0, 0, 0)
        main_dialog_layout.setSpacing(0)

        self.central_widget = QFrame()
        self.central_widget.setObjectName("PdfPageRangeDialogContainer")
        self.central_widget.setStyleSheet(f"""
            QFrame#PdfPageRangeDialogContainer {{
                background-color: {get_theme_token("fondo_secundario", "#1e1e1e")};
                border: 1px solid {get_theme_token("borde", "#2d2d2d")};
                border-radius: 6px;
            }}
            QLabel {{
                color: {get_theme_token("texto_principal", "#ffffff")};
                font-size: 12px;
                border: none;
                background: transparent;
            }}
            QLineEdit {{
                background-color: {get_theme_token("fondo_principal", "#121212")};
                color: {get_theme_token("texto_principal", "#ffffff")};
                border: 1px solid {get_theme_token("borde", "#2d2d2d")};
                border-radius: 6px;
                padding: 6px;
            }}
            QPushButton#dialogButton {{
                background-color: {get_theme_token("boton_secundario_fondo", "#1b3b22")};
                color: {get_theme_token("boton_secundario_texto", "#B9E640")};
                border: none;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: bold;
            }}
            QPushButton#dialogButton:hover {{
                background-color: {get_theme_token("boton_secundario_hover", "#224a2b")};
            }}
            QPushButton#dialogCancelButton {{
                background-color: transparent;
                color: #e74c3c;
                border: 1px solid #e74c3c;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: bold;
            }}
            QPushButton#dialogCancelButton:hover {{
                background-color: rgba(231, 76, 60, 0.15);
            }}
        """)
        main_dialog_layout.addWidget(self.central_widget)

        central_layout = QVBoxLayout(self.central_widget)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        self.title_bar = CustomTitleBar(self, self.windowTitle())
        self.title_bar.btn_min.hide()
        self.title_bar.btn_max.hide()
        self.title_bar.btn_close.clicked.disconnect()
        self.title_bar.btn_close.clicked.connect(self.reject)
        self.title_bar.setStyleSheet("""
            CustomTitleBar {
                background-color: #0d0d0d;
                border-bottom: 1px solid #222222;
                border-top-left-radius: 11px;
                border-top-right-radius: 11px;
            }
        """)
        central_layout.addWidget(self.title_bar)

        layout = QVBoxLayout()
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(8)

        self.lbl_info = QLabel(
            self.tr("\"{0}\" tiene {1} páginas. ¿Cuáles quieres importar?").format(
                self._filename, self._page_count
            )
        )
        self.lbl_info.setWordWrap(True)
        layout.addWidget(self.lbl_info)

        self.range_input = QLineEdit()
        self.range_input.setText(f"1-{self._page_count}")
        self.range_input.setPlaceholderText(self.tr("ej. 1-5, 8, 10-12"))
        self.range_input.selectAll()
        self.range_input.returnPressed.connect(self._on_import_clicked)
        layout.addWidget(self.range_input)

        self.error_lbl = QLabel("")
        self.error_lbl.setStyleSheet("color: #e74c3c; font-size: 11px;")
        self.error_lbl.setWordWrap(True)
        self.error_lbl.hide()
        layout.addWidget(self.error_lbl)

        actions_layout = QHBoxLayout()
        self.btn_cancel = QPushButton(self.tr("Cancelar"))
        self.btn_cancel.setObjectName("dialogCancelButton")
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_import = QPushButton(self.tr("Importar"))
        self.btn_import.setObjectName("dialogButton")
        self.btn_import.clicked.connect(self._on_import_clicked)

        actions_layout.addStretch()
        actions_layout.addWidget(self.btn_cancel)
        actions_layout.addWidget(self.btn_import)
        layout.addLayout(actions_layout)

        central_layout.addLayout(layout)
        self.range_input.setFocus()

    def _on_import_clicked(self):
        from core.tabs.image_tools.pdf_pages import parse_page_range
        try:
            self.result_pages = parse_page_range(self.range_input.text(), self._page_count)
        except ValueError as e:
            self.error_lbl.setText(str(e))
            self.error_lbl.show()
            return
        self.accept()

    @staticmethod
    def get_pages(parent, filename: str, page_count: int) -> list[int] | None:
        dialog = PdfPageRangeDialog(parent, filename, page_count)
        if dialog.exec():
            return dialog.result_pages
        return None


class ColorSquare(QWidget):
    color_changed = Signal(int, int) # Sat, Val

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(256, 256)
        self.hue = 0
        self.sat = 255
        self.val = 255
        self.mouse_down = False

    def set_hue(self, hue):
        self.hue = hue
        self.update()

    def set_color(self, sat, val):
        self.sat = sat
        self.val = val
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 1. Base horizontal gradient: from White (S=0) to Pure Hue Color (S=255)
        hue_color = QColor.fromHsv(self.hue, 255, 255)
        grad_h = QLinearGradient(0, 0, self.width(), 0)
        grad_h.setColorAt(0.0, Qt.white)
        grad_h.setColorAt(1.0, hue_color)
        painter.fillRect(self.rect(), grad_h)

        # 2. Vertical overlay gradient: from Transparent (V=255, top) to Black (V=0, bottom)
        grad_v = QLinearGradient(0, 0, 0, self.height())
        grad_v.setColorAt(0.0, Qt.transparent)
        grad_v.setColorAt(1.0, Qt.black)
        painter.fillRect(self.rect(), grad_v)

        # 3. Draw selector circle
        painter.setPen(QPen(Qt.white, 2))
        px = self.sat
        py = 255 - self.val
        painter.drawEllipse(QPoint(px, py), 5, 5)

        if self.val > 180 and self.sat < 80:
            painter.setPen(QPen(Qt.black, 1))
            painter.drawEllipse(QPoint(px, py), 4, 4)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.mouse_down = True
            self.update_from_mouse(event.position().toPoint())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.mouse_down = False

    def mouseMoveEvent(self, event):
        if self.mouse_down:
            self.update_from_mouse(event.position().toPoint())

    def update_from_mouse(self, pos):
        x = max(0, min(pos.x(), 255))
        y = max(0, min(pos.y(), 255))
        self.sat = x
        self.val = 255 - y
        self.color_changed.emit(self.sat, self.val)
        self.update()


class HueSlider(QSlider):
    def __init__(self, parent=None):
        super().__init__(Qt.Vertical, parent)
        self.setRange(0, 359)
        self.setFixedWidth(24)
        self.setFixedHeight(256)
        self.setStyleSheet("""
            QSlider::groove:vertical {
                border: 1px solid #333333;
                width: 14px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0.0 #ff0000, stop:0.17 #ffff00, stop:0.33 #00ff00,
                    stop:0.5 #00ffff, stop:0.67 #0000ff, stop:0.83 #ff00ff, stop:1.0 #ff0000);
                border-radius: 7px;
            }
            QSlider::handle:vertical {
                background: #ffffff;
                border: 2px solid #2d2d2d;
                height: 8px;
                width: 20px;
                margin: 0 -3px;
                border-radius: 4px;
            }
        """)


class AdobeColorPickerDialog(QDialog):
    def __init__(self, initial_color_hex="#B9E640", parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle(self.tr("Selector de Color"))
        self.setFixedSize(430, 322)
        
        # Parse initial color
        color = QColor(initial_color_hex)
        self.hue = color.hue()
        if self.hue < 0: self.hue = 0
        self.sat = color.saturation()
        self.val = color.value()
        
        self.init_ui()

    def init_ui(self):
        # Styling matching theme
        from gui.styles import get_theme_token
        from gui.widgets.title_bar import CustomTitleBar

        # Main layout of the dialog (no margins)
        main_dialog_layout = QVBoxLayout(self)
        main_dialog_layout.setContentsMargins(0, 0, 0, 0)
        main_dialog_layout.setSpacing(0)

        # Central widget container for styling
        self.central_widget = QFrame()
        self.central_widget.setObjectName("ColorPickerDialogContainer")
        self.central_widget.setStyleSheet(f"""
            QFrame#ColorPickerDialogContainer {{
                background-color: {get_theme_token("fondo_secundario", "#1e1e1e")};
                border: 1px solid {get_theme_token("borde", "#2d2d2d")};
                border-radius: 6px;
            }}
            QLabel {{
                color: {get_theme_token("texto_principal", "#ffffff")};
                font-size: 11px;
                border: none;
                background: transparent;
            }}
            QLineEdit {{
                background-color: {get_theme_token("fondo_principal", "#121212")};
                color: {get_theme_token("texto_principal", "#ffffff")};
                border: 1px solid {get_theme_token("borde", "#2d2d2d")};
                border-radius: 6px;
                padding: 4px;
                font-size: 11px;
            }}
            QPushButton {{
                background-color: {get_theme_token("boton_secundario_fondo", "#1b3b22")};
                color: {get_theme_token("boton_secundario_texto", "#B9E640")};
                border: none;
                border-radius: 6px;
                padding: 5px 12px;
                font-weight: bold;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {get_theme_token("boton_secundario_hover", "#224a2b")};
            }}
            QPushButton#dialogCancelButton {{
                background-color: transparent;
                color: #e74c3c;
                border: 1px solid #e74c3c;
                border-radius: 6px;
                padding: 5px 12px;
                font-weight: bold;
                font-size: 11px;
            }}
            QPushButton#dialogCancelButton:hover {{
                background-color: rgba(231, 76, 60, 0.15);
            }}
            QPushButton#dialogCancelButton:pressed {{
                background-color: rgba(231, 76, 60, 0.3);
            }}
        """)
        main_dialog_layout.addWidget(self.central_widget)

        # Internal vertical layout for central_widget
        central_layout = QVBoxLayout(self.central_widget)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        # Title bar
        title_text = self.windowTitle()
        self.title_bar = CustomTitleBar(self, title_text)
        self.title_bar.btn_min.hide()
        self.title_bar.btn_max.hide()
        self.title_bar.btn_close.clicked.disconnect()
        self.title_bar.btn_close.clicked.connect(self.reject)
        self.title_bar.setStyleSheet("""
            CustomTitleBar {
                background-color: #0d0d0d;
                border-bottom: 1px solid #222222;
                border-top-left-radius: 11px;
                border-top-right-radius: 11px;
            }
        """)
        central_layout.addWidget(self.title_bar)

        # Content layout (Horizontal)
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        # 1. Saturation-Value Square
        self.square = ColorSquare()
        self.square.set_hue(self.hue)
        self.square.set_color(self.sat, self.val)
        self.square.color_changed.connect(self.on_square_changed)
        main_layout.addWidget(self.square)

        # 2. Hue Slider
        self.slider = HueSlider()
        self.slider.setInvertedAppearance(True)
        self.slider.setValue(self.hue)
        self.slider.valueChanged.connect(self.on_slider_changed)
        main_layout.addWidget(self.slider)

        # 3. Right control panel
        panel_layout = QVBoxLayout()
        panel_layout.setSpacing(10)

        # Color preview circle
        preview_label = QLabel(self.tr("Nuevo:"))
        self.preview_btn = QPushButton()
        self.preview_btn.setFixedSize(60, 60)
        self.preview_btn.setFlat(True)
        self.preview_btn.setFocusPolicy(Qt.NoFocus)
        self.preview_btn.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.preview_btn.setStyleSheet(f"background-color: {QColor.fromHsv(self.hue, self.sat, self.val).name()}; border: 1px solid #ffffff; border-radius: 30px;")
        
        panel_layout.addWidget(preview_label)
        panel_layout.addWidget(self.preview_btn)
        panel_layout.addSpacing(10)

        # Hex field
        hex_label = QLabel(self.tr("Código Hex:"))
        self.hex_input = QLineEdit()
        self.hex_input.setMaxLength(7)
        self.hex_input.setFixedWidth(80)
        self.hex_input.setText(QColor.fromHsv(self.hue, self.sat, self.val).name().upper())
        self.hex_input.textChanged.connect(self.on_hex_text_changed)
        
        panel_layout.addWidget(hex_label)
        panel_layout.addWidget(self.hex_input)
        panel_layout.addStretch()

        # Save/Cancel buttons
        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(6)
        
        self.btn_ok = QPushButton(self.tr("Aceptar"))
        self.btn_ok.clicked.connect(self.accept)
        
        self.btn_cancel = QPushButton(self.tr("Cancelar"))
        self.btn_cancel.setObjectName("dialogCancelButton")
        self.btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addWidget(self.btn_ok)
        btn_layout.addWidget(self.btn_cancel)
        
        panel_layout.addLayout(btn_layout)
        main_layout.addLayout(panel_layout)

        central_layout.addLayout(main_layout)

    def on_slider_changed(self, value):
        self.hue = value
        self.square.set_hue(self.hue)
        self.update_color_preview()

    def on_square_changed(self, sat, val):
        self.sat = sat
        self.val = val
        self.update_color_preview()

    def on_hex_text_changed(self, text):
        text = text.strip()
        if not text.startswith("#"):
            text = "#" + text
        color = QColor(text)
        if color.isValid():
            self.slider.blockSignals(True)
            self.square.blockSignals(True)
            
            self.hue = color.hue()
            if self.hue < 0: self.hue = 0
            self.sat = color.saturation()
            self.val = color.value()
            
            self.slider.setValue(self.hue)
            self.square.set_hue(self.hue)
            self.square.set_color(self.sat, self.val)
            
            self.slider.blockSignals(False)
            self.square.blockSignals(False)
            
            self.preview_btn.setStyleSheet(f"background-color: {color.name()}; border: 1px solid #ffffff; border-radius: 30px;")

    def update_color_preview(self):
        color = QColor.fromHsv(self.hue, self.sat, self.val)
        self.preview_btn.setStyleSheet(f"background-color: {color.name()}; border: 1px solid #ffffff; border-radius: 30px;")
        
        self.hex_input.blockSignals(True)
        self.hex_input.setText(color.name().upper())
        self.hex_input.blockSignals(False)

    def get_color(self):
        return QColor.fromHsv(self.hue, self.sat, self.val).name()
