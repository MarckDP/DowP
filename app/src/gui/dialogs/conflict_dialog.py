# src/gui/dialogs/conflict_dialog.py
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout
from gui.styles import get_theme_token
from gui.styles import set_themed_style


class ConflictDialog(QDialog):
    """
    Diálogo modal mostrado cuando el archivo de salida ya existe (Proceso Avanzado,
    modo SOLO). Tres acciones posibles, guardadas en self.result tras exec():
      - "overwrite": sobrescribir (se respalda el original a .dbak antes).
      - "rename":    conservar ambos (se busca "nombre (1).ext" libre).
      - "cancel":    cancelar la operación (valor por defecto).

    Se llama únicamente desde el hilo principal (ver gui/dialogs/conflict_bridge.py,
    que lo invoca vía Qt.BlockingQueuedConnection desde el hilo de descarga).
    """

    def __init__(self, parent, filename: str):
        super().__init__(parent)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle(self.tr("Conflicto de Archivo"))
        self.setFixedSize(420, 210)
        self.result = "cancel"
        self._filename = filename
        self.init_ui()

    def init_ui(self):
        from gui.widgets.title_bar import CustomTitleBar
        from gui.styles import get_theme_token

        main_dialog_layout = QVBoxLayout(self)
        main_dialog_layout.setContentsMargins(0, 0, 0, 0)
        main_dialog_layout.setSpacing(0)

        self.central_widget = QFrame()
        self.central_widget.setObjectName("ConflictDialogContainer")
        set_themed_style(self.central_widget, lambda: f"""
            QFrame#ConflictDialogContainer {{
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
            QPushButton#dialogNeutralButton {{
                background-color: {get_theme_token('boton_neutro_fondo', '#333333')};
                color: {get_theme_token('texto_principal', '#e0e0e0')};
                border: 1px solid {get_theme_token('boton_neutro_borde', '#4a4a4a')};
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: bold;
            }}
            QPushButton#dialogNeutralButton:hover {{
                background-color: {get_theme_token('boton_neutro_hover', '#3d3d3d')};
            }}
            QPushButton#dialogCancelButton {{
                background-color: transparent;
                color: {get_theme_token('etiqueta_peligro', '#e74c3c')};
                border: 1px solid {get_theme_token('etiqueta_peligro', '#e74c3c')};
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

        central_layout = QVBoxLayout(self.central_widget)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        self.title_bar = CustomTitleBar(self, self.windowTitle())
        self.title_bar.btn_min.hide()
        self.title_bar.btn_max.hide()
        self.title_bar.btn_close.clicked.disconnect()
        self.title_bar.btn_close.clicked.connect(self._on_cancel)
        set_themed_style(self.title_bar, lambda: f"""
            CustomTitleBar {{
                background-color: {get_theme_token('cabecera_dialogo', '#0d0d0d')};
                border-bottom: 1px solid {get_theme_token('borde_normal', '#222222')};
                border-top-left-radius: 11px;
                border-top-right-radius: 11px;
            }}
        """)
        central_layout.addWidget(self.title_bar)

        layout = QVBoxLayout()
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)

        main_label = QLabel(
            self.tr("El archivo '{0}' ya existe en la carpeta de destino.").format(self._filename)
        )
        main_label.setWordWrap(True)
        layout.addWidget(main_label)

        question_label = QLabel(self.tr("¿Qué deseas hacer?"))
        layout.addWidget(question_label)

        layout.addStretch()

        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(8)

        self.btn_overwrite = QPushButton(self.tr("Sobrescribir"))
        self.btn_overwrite.setObjectName("dialogButton")
        self.btn_overwrite.clicked.connect(self._on_overwrite)

        self.btn_rename = QPushButton(self.tr("Conservar Ambos"))
        self.btn_rename.setObjectName("dialogNeutralButton")
        self.btn_rename.clicked.connect(self._on_rename)

        self.btn_cancel = QPushButton(self.tr("Cancelar"))
        self.btn_cancel.setObjectName("dialogCancelButton")
        self.btn_cancel.clicked.connect(self._on_cancel)

        actions_layout.addWidget(self.btn_overwrite)
        actions_layout.addWidget(self.btn_rename)
        actions_layout.addWidget(self.btn_cancel)
        layout.addLayout(actions_layout)

        central_layout.addLayout(layout)

    def _on_overwrite(self):
        self.result = "overwrite"
        self.accept()

    def _on_rename(self):
        self.result = "rename"
        self.accept()

    def _on_cancel(self):
        self.result = "cancel"
        self.reject()
