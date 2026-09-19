# src/gui/tabs/editing_media/api_key_login_widget.py
from PySide6.QtCore import Qt, QCoreApplication, QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
)

from gui.styles import get_theme_token


class ApiKeyValidationThread(QThread):
    """Hilo secundario para validar una API key contra la API real del proveedor (una
    llamada de red) sin congelar la UI."""
    finished_validation = Signal(bool, str)

    def __init__(self, provider, key, parent=None):
        super().__init__(parent)
        self.provider = provider
        self.key = key

    def run(self):
        try:
            ok, msg = self.provider.validate_api_key(self.key)
        except Exception as e:
            ok, msg = False, str(e)
        self.finished_validation.emit(ok, msg)


class ApiKeyLoginWidget(QWidget):
    """Página genérica de "necesitás una API key" para orígenes web sin OAuth (a diferencia
    de Freesound, que tiene su propia freesound_login_page): Pixabay, Pexels, y cualquier
    origen futuro del mismo tipo. Una sola instancia se reconfigura con configure() antes de
    mostrarse en el media_stack -- nunca hay más de un origen visible a la vez, así que no
    hace falta una instancia por proveedor."""

    key_saved = Signal(str)  # source_id del proveedor cuya key se acaba de guardar

    def __init__(self, parent=None):
        super().__init__(parent)
        self.provider = None
        self._validation_thread = None

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(14)
        layout.setContentsMargins(40, 20, 40, 20)

        self.title_label = QLabel()
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet("font-size: 15px; font-weight: bold;")
        layout.addWidget(self.title_label)

        self.instructions_label = QLabel()
        self.instructions_label.setAlignment(Qt.AlignCenter)
        self.instructions_label.setWordWrap(True)
        self.instructions_label.setStyleSheet(
            f"color: {get_theme_token('texto_secundario', '#aaaaaa')}; font-size: 13px;"
        )
        self.instructions_label.setMaximumWidth(420)
        layout.addWidget(self.instructions_label)

        self.btn_open_site = QPushButton()
        self.btn_open_site.setFixedHeight(38)
        self.btn_open_site.setMinimumWidth(220)
        self.btn_open_site.setCursor(Qt.PointingHandCursor)
        self.btn_open_site.setStyleSheet(f"""
            QPushButton {{
                background-color: {get_theme_token('fondo_elemento', '#2d2d2d')};
                border: 1px solid {get_theme_token('borde_normal', '#3d3d3d')};
                border-radius: 8px;
                font-weight: bold;
                padding: 8px 20px;
            }}
            QPushButton:hover {{
                background-color: {get_theme_token('seleccion_fondo', '#3d3d3d')};
            }}
        """)
        self.btn_open_site.clicked.connect(self._on_open_site_clicked)
        layout.addWidget(self.btn_open_site, 0, Qt.AlignCenter)

        key_row = QHBoxLayout()
        key_row.setSpacing(6)

        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.Password)
        self.key_input.setFixedHeight(36)
        self.key_input.setMinimumWidth(260)
        self.key_input.setPlaceholderText(QCoreApplication.translate("ApiKeyLoginWidget", "Pega tu API key aquí"))
        self.key_input.returnPressed.connect(self._on_save_clicked)
        key_row.addWidget(self.key_input)

        self.btn_toggle_visibility = QToolButton()
        self.btn_toggle_visibility.setFixedSize(36, 36)
        self.btn_toggle_visibility.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_visibility.setCheckable(True)
        self.btn_toggle_visibility.setText(QCoreApplication.translate("ApiKeyLoginWidget", "Ver"))
        self.btn_toggle_visibility.toggled.connect(self._on_toggle_visibility)
        key_row.addWidget(self.btn_toggle_visibility)

        key_row_widget = QWidget()
        key_row_widget.setLayout(key_row)
        layout.addWidget(key_row_widget, 0, Qt.AlignCenter)

        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setMaximumWidth(420)
        layout.addWidget(self.status_label)

        self.btn_save = QPushButton(QCoreApplication.translate("ApiKeyLoginWidget", "Guardar"))
        self.btn_save.setFixedHeight(40)
        self.btn_save.setMinimumWidth(160)
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.setStyleSheet(f"""
            QPushButton {{
                background-color: {get_theme_token('acento_primario', '#B9E640')};
                color: {get_theme_token('fondo_principal', '#0a0a0a')};
                border: none;
                border-radius: 8px;
                font-weight: bold;
                font-size: 13px;
                padding: 10px 24px;
            }}
            QPushButton:hover {{
                background-color: {get_theme_token('acento_primario', '#B9E640')};
            }}
            QPushButton:disabled {{
                opacity: 0.6;
            }}
        """)
        self.btn_save.clicked.connect(self._on_save_clicked)
        layout.addWidget(self.btn_save, 0, Qt.AlignCenter)

    def configure(self, provider):
        """Reconfigura la página para un proveedor específico antes de mostrarla."""
        self.provider = provider
        self.title_label.setText(
            QCoreApplication.translate("ApiKeyLoginWidget", "Se necesita una API key de {0}").format(provider.display_name)
        )
        self.instructions_label.setText(getattr(provider, "api_key_instructions", ""))
        self.btn_open_site.setText(
            QCoreApplication.translate("ApiKeyLoginWidget", "Abrir {0}").format(provider.display_name)
        )
        self.key_input.clear()
        self.key_input.setEchoMode(QLineEdit.Password)
        self.btn_toggle_visibility.blockSignals(True)
        self.btn_toggle_visibility.setChecked(False)
        self.btn_toggle_visibility.blockSignals(False)
        self.status_label.setText("")
        self.btn_save.setEnabled(True)
        self.btn_save.setText(QCoreApplication.translate("ApiKeyLoginWidget", "Guardar"))

    def _on_open_site_clicked(self):
        if self.provider and getattr(self.provider, "api_key_url", ""):
            QDesktopServices.openUrl(QUrl(self.provider.api_key_url))

    def _on_toggle_visibility(self, checked):
        self.key_input.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)

    def _on_save_clicked(self):
        if self.provider is None or self._validation_thread is not None:
            return
        key = self.key_input.text().strip()
        if not key:
            self.status_label.setStyleSheet("color: #E67E22;")
            self.status_label.setText(QCoreApplication.translate("ApiKeyLoginWidget", "Pega tu API key antes de guardar."))
            return

        self.btn_save.setEnabled(False)
        self.btn_save.setText(QCoreApplication.translate("ApiKeyLoginWidget", "Validando..."))
        self.status_label.setStyleSheet("")
        self.status_label.setText("")

        provider = self.provider
        self._validation_thread = ApiKeyValidationThread(provider, key, parent=self)
        self._validation_thread.finished_validation.connect(
            lambda ok, msg: self._on_validation_finished(ok, msg, key, provider)
        )
        self._validation_thread.start()

    def _on_validation_finished(self, ok, msg, key, provider):
        self.btn_save.setEnabled(True)
        self.btn_save.setText(QCoreApplication.translate("ApiKeyLoginWidget", "Guardar"))
        thread = self._validation_thread
        self._validation_thread = None
        if thread:
            thread.deleteLater()

        # El usuario pudo haber cambiado de origen mientras la validación corría en el hilo
        # (la página se reconfigura in-place) -- si ya no es el mismo provider, descartar el
        # resultado en vez de guardar la key en el origen equivocado o pisar la UI actual.
        if provider is not self.provider:
            return

        if not ok:
            self.status_label.setStyleSheet("color: #E86464;")
            self.status_label.setText(msg or QCoreApplication.translate("ApiKeyLoginWidget", "La API key no es válida."))
            return

        provider.set_api_key(key)
        self.status_label.setStyleSheet("color: #1DC038;")
        self.status_label.setText(QCoreApplication.translate("ApiKeyLoginWidget", "¡Listo! Key guardada."))
        self.key_saved.emit(provider.id)
