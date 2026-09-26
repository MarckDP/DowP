# src/gui/tabs/settings/pages/labels_page.py
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QScrollArea
)
from PySide6.QtCore import Qt, Signal, QSize
from core.utils.config_manager import get_config, save_config
from core.utils.paths import get_src_dir
from gui.styles import get_theme_token
from gui.widgets.top_aligned_layout import TopAlignedVBoxLayout

class LabelRow(QFrame):
    delete_requested = Signal(str)
    edit_requested = Signal(str)

    def __init__(self, name, path, color="#B9E640", parent=None):
        super().__init__(parent)
        self.name = name
        self.path = path
        self.color = color
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        # Info column
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        self.name_lbl = QLabel(self.name)
        self.name_lbl.setStyleSheet(f"color: {self.color}; font-weight: bold; font-size: 13px; border: none; background: transparent;")

        self.path_lbl = QLabel(self.path)
        self.path_lbl.setStyleSheet(f"color: {get_theme_token('texto_secundario', '#aaaaaa')}; font-size: 11px; border: none; background: transparent;")
        self.path_lbl.setWordWrap(True)

        info_layout.addWidget(self.name_lbl)
        info_layout.addWidget(self.path_lbl)

        # Icon paths
        import os
        _icon_dir = os.path.join(get_src_dir(), "assets", "icons", "svg")
        from gui.widgets.queue_panel import get_colored_icon

        # Edit button (SVG icon)
        self.btn_edit = QPushButton()
        self.btn_edit.setToolTip(self.tr("Editar etiqueta"))
        self.btn_edit.setFixedSize(26, 26)
        self.btn_edit.setIcon(get_colored_icon(os.path.join(_icon_dir, "edit.svg"), get_theme_token('texto_principal', '#ffffff'), 16))
        self.btn_edit.setIconSize(QSize(16, 16))
        self.btn_edit.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.1);
            }
        """)
        self.btn_edit.clicked.connect(lambda: self.edit_requested.emit(self.name))

        # Delete button (SVG icon, tinted red)
        self.btn_delete = QPushButton()
        self.btn_delete.setToolTip(self.tr("Eliminar etiqueta"))
        self.btn_delete.setFixedSize(26, 26)
        self.btn_delete.setIcon(get_colored_icon(os.path.join(_icon_dir, "close.svg"), '#e74c3c', 16))
        self.btn_delete.setIconSize(QSize(16, 16))
        self.btn_delete.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: rgba(231, 76, 60, 0.15);
            }
        """)
        self.btn_delete.clicked.connect(lambda: self.delete_requested.emit(self.name))

        layout.addLayout(info_layout, 1)
        layout.addWidget(self.btn_edit)
        layout.addWidget(self.btn_delete)

        borde = get_theme_token('borde', '#2d2d2d')
        fondo = get_theme_token('fondo_secundario', '#1e1e1e')
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {fondo};
                border: 1px solid {borde};
                border-radius: 6px;
            }}
            QFrame:hover {{
                border-color: {self.color};
            }}
        """)


class LabelsPage(QWidget):
    labels_changed = Signal()

    def __init__(self):
        super().__init__()
        self.init_ui()
        self.load_labels()

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(12)

        # Title
        self.title_label = QLabel(self.tr("Gestión de Etiquetas"))
        self.title_label.setObjectName("settingsTitle")
        self.main_layout.addWidget(self.title_label)
        
        # Divider
        line = QFrame()
        line.setObjectName("settingsDivider")
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        self.main_layout.addWidget(line)

        # Description
        self.desc_label = QLabel(self.tr("Crea etiquetas con rutas predefinidas. Al seleccionar una etiqueta en la descarga, esta se guardará automáticamente en la ruta configurada sin posibilidad de editarla manualmente para evitar errores."))
        self.desc_label.setObjectName("settingsDescription")
        self.desc_label.setWordWrap(True)
        self.main_layout.addWidget(self.desc_label)

        self.main_layout.addSpacing(10)

        # Button Row to Add label + Feedback
        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton(self.tr("Agregar Etiqueta"))
        self.add_btn.setProperty("variant", "secondary")
        self.add_btn.setFixedWidth(160)
        self.add_btn.clicked.connect(self.open_add_dialog)

        self.feedback_lbl = QLabel("")
        self.feedback_lbl.setStyleSheet("color: #aaaaaa; font-size: 11px;")
        
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.feedback_lbl)
        btn_layout.addStretch()
        self.main_layout.addLayout(btn_layout)

        self.main_layout.addSpacing(10)

        # List Header
        list_title = QLabel(self.tr("Etiquetas registradas:"))
        font_list = list_title.font()
        font_list.setBold(True)
        list_title.setFont(font_list)
        self.main_layout.addWidget(list_title)

        # Scroll Area for registered labels
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        
        self.scroll_content = QWidget()
        self.scroll_content.setObjectName("labelsScrollContent")
        self.scroll_content.setStyleSheet("QWidget#labelsScrollContent { background: transparent; }")
        self.scroll_layout = TopAlignedVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 5, 0)
        self.scroll_layout.setSpacing(8)

        # Empty state label
        self.empty_lbl = QLabel(self.tr("No hay etiquetas registradas. Crea una arriba."))
        self.empty_lbl.setStyleSheet("color: #888888; font-style: italic; border: none; background: transparent;")
        self.empty_lbl.setAlignment(Qt.AlignCenter)
        self.scroll_layout.addWidget(self.empty_lbl)

        self.scroll.setWidget(self.scroll_content)
        self.main_layout.addWidget(self.scroll, 1)

    def open_add_dialog(self):
        from gui.dialogs.dialogs import AddLabelDialog
        dialog = AddLabelDialog(self)
        if dialog.exec():
            data = dialog.get_data()
            config = get_config()
            labels = config.get("labels", [])
            labels.append(data)
            config["labels"] = labels
            save_config(config)
            
            self.feedback_lbl.setText(self.tr("¡Etiqueta creada con éxito!"))
            self.feedback_lbl.setStyleSheet(f"color: {get_theme_token('acento_primario', '#B9E640')}; font-size: 11px;")
            
            self.load_labels()
            self.labels_changed.emit()

    def open_edit_dialog(self, name):
        """Abre el diálogo de edición para una etiqueta existente."""
        from gui.dialogs.dialogs import AddLabelDialog
        config = get_config()
        labels = config.get("labels", [])
        
        # Buscar la etiqueta por nombre
        label_data = None
        label_index = -1
        for i, lbl in enumerate(labels):
            if lbl["name"] == name:
                label_data = lbl
                label_index = i
                break
        
        if label_data is None:
            return
        
        dialog = AddLabelDialog(self, edit_data=label_data)
        if dialog.exec():
            new_data = dialog.get_data()
            labels[label_index] = new_data
            config["labels"] = labels
            save_config(config)
            
            self.feedback_lbl.setText(self.tr("Etiqueta actualizada."))
            self.feedback_lbl.setStyleSheet(f"color: {get_theme_token('acento_primario', '#B9E640')}; font-size: 11px;")
            
            self.load_labels()
            self.labels_changed.emit()

    def delete_label(self, name):
        config = get_config()
        labels = config.get("labels", [])
        
        new_labels = [lbl for lbl in labels if lbl["name"] != name]
        config["labels"] = new_labels
        save_config(config)

        self.feedback_lbl.setText(self.tr("Etiqueta eliminada."))
        self.feedback_lbl.setStyleSheet("color: #aaaaaa; font-size: 11px;")
        
        self.load_labels()
        self.labels_changed.emit()

    def load_labels(self):
        for i in reversed(range(self.scroll_layout.count())):
            widget = self.scroll_layout.itemAt(i).widget()
            if widget and widget != self.empty_lbl:
                widget.hide()
                self.scroll_layout.removeWidget(widget)
                widget.setParent(None)
                widget.deleteLater()

        config = get_config()
        labels = config.get("labels", [])

        if not labels:
            self.empty_lbl.show()
        else:
            self.empty_lbl.hide()
            for lbl in labels:
                color = lbl.get("color", "#B9E640")
                row = LabelRow(lbl["name"], lbl["path"], color)
                row.delete_requested.connect(self.delete_label)
                row.edit_requested.connect(self.open_edit_dialog)
                self.scroll_layout.addWidget(row)
