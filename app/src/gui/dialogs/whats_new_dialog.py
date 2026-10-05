# src/gui/dialogs/whats_new_dialog.py
"""Ventana de "Novedades": aparece una sola vez tras actualizar (ver
core/updater/launcher.py y main.py) y su contenido se reutiliza, sin cambios,
en Ajustes > Acerca de (gui/tabs/settings/pages/system_page.py) para poder
verlo de nuevo cuando se quiera.

Sigue al pie de la letra el patron de ventana sin bordes ya usado en
AddLabelDialog (gui/dialogs/dialogs.py): QDialog con FramelessWindowHint +
fondo translucido -> QFrame contenedor con bordes redondeados -> CustomTitleBar
(trae el logo de DowP integrado) -> contenido.
"""
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from core.updater.whats_new_content import get_whats_new_items
from gui.styles import get_theme_token
from gui.styles import set_themed_style

# El contexto va como string LITERAL en cada llamada a QCoreApplication.translate(),
# nunca como variable: pyside6-lupdate escanea el codigo de forma estatica y no
# reconoce QCoreApplication.translate(UNA_VARIABLE, "...") -- confirmado empiricamente.


def _build_item_row(title: str, description: str, parent=None) -> QWidget:
    from gui.styles import get_theme_token

    row = QWidget(parent)
    row_layout = QHBoxLayout(row)
    row_layout.setContentsMargins(0, 0, 0, 0)
    row_layout.setSpacing(10)

    check = QLabel("✓")
    check.setFixedWidth(18)
    set_themed_style(check, lambda: f"""
        color: {get_theme_token("boton_secundario_texto", "#B9E640")};
        font-weight: bold;
        font-size: 14px;
        border: none;
        background: transparent;
    """)
    row_layout.addWidget(check, 0, Qt.AlignTop)

    text_col = QVBoxLayout()
    text_col.setSpacing(2)

    lbl_title = QLabel(title)
    lbl_title.setWordWrap(True)
    set_themed_style(lbl_title, lambda: f"""
        color: {get_theme_token("texto_principal", "#ffffff")};
        font-weight: bold;
        font-size: 13px;
        border: none;
        background: transparent;
    """)
    lbl_desc = QLabel(description)
    lbl_desc.setWordWrap(True)
    set_themed_style(lbl_desc, lambda: f"""
        color: {get_theme_token("texto_secundario", "#aaaaaa")};
        font-size: 12px;
        border: none;
        background: transparent;
    """)
    text_col.addWidget(lbl_title)
    text_col.addWidget(lbl_desc)
    row_layout.addLayout(text_col, 1)

    return row


def build_whats_new_content(version: str, parent=None) -> QWidget:
    """Encabezado + lista de novedades de `version`, sin scroll propio ni
    tamaño fijo -- quien la use decide si la mete en un QScrollArea (el
    dialog) o la agrega tal cual a un layout ya scrolleable (la página de
    Ajustes). Una sola implementación para los dos sitios."""
    container = QWidget(parent)
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(14)

    heading = QLabel(QCoreApplication.translate("WhatsNewDialog", "DowP {0}").format(version))
    set_themed_style(heading, lambda: f"""
        font-weight: bold;
        font-size: 16px;
        color: {get_theme_token('texto_activo', '#ffffff')};
        border: none;
        background: transparent;
    """)
    layout.addWidget(heading)

    subheading = QLabel(QCoreApplication.translate("WhatsNewDialog", "Esto es lo nuevo en esta versión:"))
    set_themed_style(subheading, lambda: f"""
        font-size: 12px;
        color: {get_theme_token('texto_gris', '#aaaaaa')};
        border: none;
        background: transparent;
    """)
    layout.addWidget(subheading)

    items_layout = QVBoxLayout()
    items_layout.setSpacing(12)
    for title, description in get_whats_new_items(version):
        items_layout.addWidget(_build_item_row(title, description, container))
    layout.addLayout(items_layout)

    return container


class WhatsNewDialog(QDialog):
    def __init__(self, version: str, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle(QCoreApplication.translate("WhatsNewDialog", "Novedades"))
        self.setFixedSize(460, 560)
        self._init_ui(version)

    def _init_ui(self, version: str):
        from gui.styles import get_theme_token
        from gui.widgets.title_bar import CustomTitleBar

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        container = QFrame()
        container.setObjectName("WhatsNewDialogContainer")
        set_themed_style(container, lambda: f"""
            QFrame#WhatsNewDialogContainer {{
                background-color: {get_theme_token("fondo_secundario", "#1e1e1e")};
                border: 1px solid {get_theme_token("borde", "#2d2d2d")};
                border-radius: 6px;
            }}
        """)
        main_layout.addWidget(container)

        central_layout = QVBoxLayout(container)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        title_bar = CustomTitleBar(self, self.windowTitle())
        title_bar.btn_min.hide()
        title_bar.btn_max.hide()
        title_bar.btn_close.clicked.disconnect()
        title_bar.btn_close.clicked.connect(self.reject)
        set_themed_style(title_bar, lambda: f"""
            CustomTitleBar {{
                background-color: {get_theme_token('cabecera_dialogo', '#0d0d0d')};
                border-bottom: 1px solid {get_theme_token('borde_normal', '#222222')};
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }}
        """)
        central_layout.addWidget(title_bar)

        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(20, 16, 20, 16)
        content_layout.setSpacing(12)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        # "QScrollArea { ... }" solo pinta el marco exterior -- el viewport interno
        # (donde vive de verdad el contenido con scroll) pinta su propio fondo por
        # palette y se ve como un rectangulo mas claro encima si no se cubre tambien
        # ese selector explicitamente.
        scroll.setStyleSheet("""
            QScrollArea, QScrollArea > QWidget > QWidget {
                background-color: transparent;
                border: none;
            }
        """)
        scroll.setWidget(build_whats_new_content(version, scroll))
        content_layout.addWidget(scroll, 1)

        btn_close = QPushButton(QCoreApplication.translate("WhatsNewDialog", "Entendido"))
        btn_close.setObjectName("dialogButton")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        set_themed_style(btn_close, lambda: f"""
            QPushButton#dialogButton {{
                background-color: {get_theme_token("boton_secundario_fondo", "#1b3b22")};
                color: {get_theme_token("boton_secundario_texto", "#B9E640")};
                border: none;
                border-radius: 6px;
                padding: 8px 20px;
                font-weight: bold;
            }}
            QPushButton#dialogButton:hover {{
                background-color: {get_theme_token("boton_secundario_hover", "#224a2b")};
            }}
        """)
        btn_close.clicked.connect(self.accept)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(btn_close)
        content_layout.addLayout(btn_row)

        central_layout.addLayout(content_layout)
