# src/gui/dialogs/about_dialogs.py
"""Ventanas que se abren desde Ajustes > Acerca de:

  - CreditsDialog: "Créditos y licencias" de todo lo de terceros que usa DowP.
  - SupportDialog: "Otras formas de apoyar" (Binance Pay: QR + UID copiable).

Mismo patrón de ventana sin bordes que WhatsNewDialog (gui/dialogs/whats_new_dialog.py).
Los datos vienen de core/credits.py.
"""
import os

from PySide6.QtCore import QCoreApplication, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from core import credits
from gui.styles import set_themed_style
from gui.styles import get_theme_token


def _tr(text: str) -> str:
    return QCoreApplication.translate("Credits", text) if text else ""


def link_html(text: str, url: str) -> str:
    """Enlace con el color de acento del tema (QLabel usa HTML para los enlaces)."""
    from gui.styles import get_theme_token
    if not url:
        return text
    color = get_theme_token("boton_secundario_texto", "#B9E640")
    return f'<a href="{url}" style="color:{color}; text-decoration:none;">{text}</a>'


def make_link_label(text: str, url: str, style="") -> QLabel:
    """style puede ser un str o una función que lo devuelva (para que se recalcule con
    el tema). El color del enlace va dentro del HTML, así que al cambiar de tema la
    etiqueta se regenera entera."""
    import shiboken6
    from gui.theme_manager import get_theme_manager

    label = QLabel()
    label.setTextFormat(Qt.RichText)
    label.setOpenExternalLinks(True)
    label.setTextInteractionFlags(Qt.TextBrowserInteraction)
    if url:
        label.setToolTip(url)
        label.setCursor(Qt.PointingHandCursor)

    def refresh(_tokens=None):
        if not shiboken6.isValid(label):
            return
        label.setText(link_html(text, url))
        extra = style() if callable(style) else style
        label.setStyleSheet(f"border: none; background: transparent; {extra}")

    refresh()
    manager = get_theme_manager()
    manager.theme_changed.connect(refresh)

    def _disconnect(*_):
        try:
            manager.theme_changed.disconnect(refresh)
        except (RuntimeError, TypeError):
            pass

    label.destroyed.connect(_disconnect)
    return label


def _styled_button(text: str, primary: bool = False) -> QPushButton:
    from gui.styles import get_theme_token
    btn = QPushButton(text)
    btn.setObjectName("dialogButton")
    btn.setCursor(Qt.PointingHandCursor)
    btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    set_themed_style(btn, lambda: f"""
        QPushButton#dialogButton {{
            background-color: {get_theme_token('boton_secundario_fondo', '#1b3b22')}; color: {get_theme_token('boton_secundario_texto', '#B9E640')}; border: none; border-radius: 6px;
            padding: 8px 20px; font-weight: bold;
        }}
        QPushButton#dialogButton:hover {{ background-color: {get_theme_token('boton_secundario_hover', '#224a2b')}; }}
    """)
    return btn


class _FramelessDialog(QDialog):
    """Contenedor redondeado + barra de título de DowP; las subclases llenan
    self.content_layout."""

    def __init__(self, title: str, width: int, height: int, parent=None):
        super().__init__(parent)
        from gui.styles import get_theme_token
        from gui.widgets.title_bar import CustomTitleBar

        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle(title)
        self.setFixedSize(width, height)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        container = QFrame()
        container.setObjectName("AboutDialogContainer")
        set_themed_style(container, lambda: f"""
            QFrame#AboutDialogContainer {{
                background-color: {get_theme_token("fondo_secundario", "#1e1e1e")};
                border: 1px solid {get_theme_token("borde", "#2d2d2d")};
                border-radius: 6px;
            }}
        """)
        main_layout.addWidget(container)

        central = QVBoxLayout(container)
        central.setContentsMargins(0, 0, 0, 0)
        central.setSpacing(0)

        title_bar = CustomTitleBar(self, title)
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
        central.addWidget(title_bar)

        self.content_layout = QVBoxLayout()
        self.content_layout.setContentsMargins(20, 16, 20, 16)
        self.content_layout.setSpacing(12)
        central.addLayout(self.content_layout)

    def add_close_row(self, text: str):
        btn = _styled_button(text)
        btn.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(btn)
        self.content_layout.addLayout(row)


class CreditsDialog(_FramelessDialog):
    def __init__(self, parent=None):
        super().__init__(QCoreApplication.translate("Credits", "Créditos y licencias"), 560, 620, parent)
        from gui.styles import get_theme_token
        text_main = get_theme_token("texto_principal", "#ffffff")

        intro = QLabel(QCoreApplication.translate(
            "Credits",
            "DowP es software libre (licencia GPL-3.0) y existe gracias a estos proyectos "
            "de código abierto. Gracias a todas las personas que los hacen posibles."))
        intro.setWordWrap(True)
        set_themed_style(intro, lambda: f"color: {get_theme_token('texto_secundario', '#aaaaaa')}; font-size: 12px; border: none; background: transparent;")
        self.content_layout.addWidget(intro)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 8, 0)
        body_layout.setSpacing(6)

        for group, items in credits.THIRD_PARTY:
            header = QLabel(_tr(group))
            set_themed_style(header, lambda: f"color: {get_theme_token('boton_secundario_texto', '#B9E640')}; font-weight: bold; font-size: 13px; "
                                 "margin-top: 8px; border: none; background: transparent;")
            body_layout.addWidget(header)
            for name, purpose, license_name, url in items:
                row = QHBoxLayout()
                row.setSpacing(10)
                col = QVBoxLayout()
                col.setSpacing(0)
                name_lbl = make_link_label(name, url, f"color: {text_main}; font-size: 12px; font-weight: bold;")
                name_lbl.setWordWrap(True)
                col.addWidget(name_lbl)
                if purpose:
                    purpose_lbl = QLabel(_tr(purpose))
                    purpose_lbl.setWordWrap(True)
                    set_themed_style(purpose_lbl, lambda: f"color: {get_theme_token('texto_secundario', '#aaaaaa')}; font-size: 11px; border: none; background: transparent;")
                    col.addWidget(purpose_lbl)
                row.addLayout(col, 1)
                lic = QLabel(_tr(license_name))
                lic.setAlignment(Qt.AlignRight | Qt.AlignTop)
                lic.setWordWrap(True)
                lic.setFixedWidth(150)
                set_themed_style(lic, lambda: f"color: {get_theme_token('texto_secundario', '#aaaaaa')}; font-size: 11px; border: none; background: transparent;")
                row.addWidget(lic, 0, Qt.AlignTop)
                body_layout.addLayout(row)
        body_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background-color: transparent; border: none; }")
        scroll.setWidget(body)
        self.content_layout.addWidget(scroll, 1)

        from PySide6.QtCore import QUrl
        from core.utils.paths import get_src_dir
        licenses = QUrl.fromLocalFile(os.path.join(get_src_dir(), *credits.LICENSES_RELPATH)).toString()
        self.licenses_link = make_link_label(
            QCoreApplication.translate("Credits", "Ver los textos completos de las licencias"), licenses,
            f"color: {text_main}; font-size: 12px;")
        self.content_layout.addWidget(self.licenses_link)

        self.add_close_row(QCoreApplication.translate("Credits", "Cerrar"))


class SupportDialog(_FramelessDialog):
    def __init__(self, parent=None):
        super().__init__(QCoreApplication.translate("Credits", "Otras formas de apoyar"), 400, 620, parent)
        from gui.styles import get_theme_token
        from core.utils.paths import get_src_dir

        title = QLabel("Binance Pay")
        set_themed_style(title, lambda: f"color: {get_theme_token('texto_principal', '#ffffff')}; font-weight: bold; font-size: 15px; border: none; background: transparent;")
        self.content_layout.addWidget(title, 0, Qt.AlignHCenter)

        qr = QLabel()
        qr.setAlignment(Qt.AlignCenter)
        qr.setStyleSheet("border: none; background: transparent;")
        pixmap = QPixmap(os.path.join(get_src_dir(), *credits.BINANCE_QR_RELPATH))
        if not pixmap.isNull():
            qr.setPixmap(pixmap.scaledToWidth(300, Qt.SmoothTransformation))
        self.content_layout.addWidget(qr, 1)

        uid_row = QHBoxLayout()
        uid_row.addStretch()
        uid_label = QLabel(QCoreApplication.translate("Credits", "Binance ID (UID): {0}").format(credits.BINANCE_UID))
        uid_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        set_themed_style(uid_label, lambda: f"color: {get_theme_token('texto_principal', '#ffffff')}; font-size: 13px; border: none; background: transparent;")
        uid_row.addWidget(uid_label)
        self.btn_copy = _styled_button(QCoreApplication.translate("Credits", "Copiar"))
        self.btn_copy.clicked.connect(self._copy_uid)
        uid_row.addWidget(self.btn_copy)
        uid_row.addStretch()
        self.content_layout.addLayout(uid_row)

        note = QLabel(QCoreApplication.translate(
            "Credits",
            "Solo desde la app de Binance (Binance Pay): escanea el código o envía al UID. "
            "Comprueba que el UID coincide antes de enviar."))
        note.setWordWrap(True)
        note.setAlignment(Qt.AlignCenter)
        set_themed_style(note, lambda: f"color: {get_theme_token('texto_secundario', '#aaaaaa')}; font-size: 11px; border: none; background: transparent;")
        self.content_layout.addWidget(note)

        thanks = QLabel(QCoreApplication.translate("Credits", "¡Gracias por apoyar DowP!"))
        thanks.setAlignment(Qt.AlignCenter)
        set_themed_style(thanks, lambda: f"color: {get_theme_token('texto_principal', '#ffffff')}; font-size: 12px; border: none; background: transparent;")
        self.content_layout.addWidget(thanks)

        self.add_close_row(QCoreApplication.translate("Credits", "Cerrar"))

    def _copy_uid(self):
        QGuiApplication.clipboard().setText(credits.BINANCE_UID)
        self.btn_copy.setText(QCoreApplication.translate("Credits", "¡Copiado!"))
        QTimer.singleShot(1500, lambda: self.btn_copy.setText(QCoreApplication.translate("Credits", "Copiar")))
