from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QSpacerItem, QSizePolicy, QPushButton, QLineEdit, QFileDialog
from PySide6.QtCore import Qt, QUrl, QThread, Signal, QSize
from PySide6.QtGui import QDesktopServices, QIcon
from core.utils.i18n import logger
from core.utils.config_manager import get_config, save_config
from core.setup.ytdlp_setup import get_ytdlp_path
from core.setup.ffmpeg_setup import check_ffmpeg, get_ffmpeg_dir
from gui.widgets.combo_box import AutoPopupComboBox
from gui.styles import apply_folder_browse_button_style, generate_tinted_svg
from core.utils.paths import get_src_dir
import os
import sys

class CookieTestWorker(QThread):
    finished = Signal(bool, str)

    def __init__(self, mode, file_path, browser, profile):
        super().__init__()
        self.mode = mode
        self.file_path = file_path
        self.browser = browser
        self.profile = profile

    def run(self):
        # No usa subprocess.run([sys.executable, ytdlp_path, ...]): en el .exe
        # compilado sys.executable es el propio DowP.exe (no un intérprete
        # genérico), así que esa llamada lanzaba una segunda instancia
        # completa de la app en vez de ejecutar yt-dlp. En su lugar se
        # importa yt_dlp en este mismo proceso, igual que el resto de la app.
        logger.info(f"CookieTestWorker: Iniciando prueba de cookies. Modo: {self.mode}, Browser: {self.browser}, Perfil: {self.profile}")
        ytdlp_path = get_ytdlp_path()
        if not ytdlp_path:
            logger.error("CookieTestWorker: yt-dlp no encontrado.")
            self.finished.emit(False, self.tr("yt-dlp no encontrado"))
            return

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'noplaylist': True,
        }
        if check_ffmpeg():
            ydl_opts['ffmpeg_location'] = get_ffmpeg_dir()

        if self.mode == "file":
            if not self.file_path:
                logger.error("CookieTestWorker: Archivo de cookies no especificado.")
                self.finished.emit(False, self.tr("Archivo no especificado"))
                return
            ydl_opts['cookiefile'] = self.file_path
        elif self.mode == "browser":
            # Formato exacto que usa yt-dlp internamente: (browser, profile, keyring, container)
            ydl_opts['cookiesfrombrowser'] = (self.browser.lower(), self.profile or None, None, None)

        try:
            if ytdlp_path not in sys.path:
                if 'yt_dlp' in sys.modules:
                    for mod in list(sys.modules.keys()):
                        if mod.startswith('yt_dlp'):
                            del sys.modules[mod]
                sys.path.insert(0, ytdlp_path)

            import yt_dlp
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info("https://www.youtube.com/watch?v=dQw4w9WgXcQ", download=False)

            if info:
                logger.info("CookieTestWorker: Prueba de cookies exitosa.")
                self.finished.emit(True, self.tr("Correcto"))
            else:
                logger.error("CookieTestWorker: Falló la prueba de cookies (sin información extraída).")
                self.finished.emit(False, self.tr("Falló"))
        except Exception as e:
            logger.error(f"CookieTestWorker: Error de ejecución: {e}")
            self.finished.emit(False, self.tr("Error de ejecución"))

class CookiesPage(QWidget):
    def __init__(self):
        super().__init__()
        self._is_loading = True
        self.init_ui()
        self.load_current_settings()
        self._is_loading = False
        self.on_mode_changed()

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(12)

        # Title
        self.title_label = QLabel(self.tr("Gestión de Cookies"))
        self.title_label.setObjectName("settingsTitle")
        self.main_layout.addWidget(self.title_label)
        
        # Divider
        line = QFrame()
        line.setObjectName("settingsDivider")
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        self.main_layout.addWidget(line)

        # Description
        self.desc_label = QLabel(self.tr("Configura las cookies para acceder a contenido protegido por edad, videos privados, o contenido\nrestringido que requiera haber iniciado sesión en el servicio."))
        self.desc_label.setObjectName("settingsDescription")
        self.desc_label.setWordWrap(True)
        self.main_layout.addWidget(self.desc_label)
        
        self.main_layout.addSpacing(10)

        # Modo de Cookies Label
        self.mode_label = QLabel(self.tr("Modo de Cookies:"))
        font = self.mode_label.font()
        font.setBold(True)
        self.mode_label.setFont(font)
        self.main_layout.addWidget(self.mode_label)

        # Combo and Test Button Row
        self.combo_row = QHBoxLayout()
        self.combo_row.setSpacing(10)
        self.combo_row.setAlignment(Qt.AlignVCenter)
        
        self.mode_combo = AutoPopupComboBox()
        self.mode_combo.addItem(self.tr("No usar"), "none")
        self.mode_combo.addItem(self.tr("Desde el navegador..."), "browser")
        self.mode_combo.addItem(self.tr("Archivo Manual..."), "file")
        self.mode_combo.setFixedWidth(300)
        
        self.test_btn = QPushButton(self.tr("Probar Cookies"))
        self.test_btn.setObjectName("secondaryButton")
        self.test_btn.setFixedWidth(120)
        
        self.test_status_label = QPushButton("")
        self.test_status_label.setObjectName("sectionStatus")
        self.test_status_label.setFlat(True)
        self.test_status_label.setFocusPolicy(Qt.NoFocus)
        self.test_status_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        font_status = self.test_status_label.font()
        font_status.setBold(True)
        self.test_status_label.setFont(font_status)
        self.test_status_label.setIconSize(QSize(20, 20))
        self.test_status_label.setStyleSheet("border: none; background: transparent; padding: 0px;")
        
        self.combo_row.addWidget(self.mode_combo)
        self.combo_row.addWidget(self.test_btn)
        self.combo_row.addWidget(self.test_status_label)
        self.combo_row.addStretch()
        
        self.main_layout.addLayout(self.combo_row)

        # File selection row (hidden by default unless 'file' is selected)
        self.file_row = QHBoxLayout()
        self.file_row.setSpacing(10)
        
        self.file_input = QLineEdit()
        self.file_input.setPlaceholderText(self.tr("Ruta del archivo cookies.txt"))
        
        self.browse_btn = QPushButton()
        self.browse_btn.setFixedSize(32, 32)
        self.browse_btn.setCursor(Qt.PointingHandCursor)
        apply_folder_browse_button_style(self.browse_btn, self.tr("Examinar archivo de cookies (*.txt)"))
        
        self.file_row.addWidget(self.file_input)
        self.file_row.addWidget(self.browse_btn)
        
        self.file_widget = QWidget()
        self.file_widget.setLayout(self.file_row)
        self.file_row.setContentsMargins(0,0,0,0)
        self.main_layout.addWidget(self.file_widget)
        
        # Browser selection row (hidden by default unless 'browser' is selected)
        self.browser_row = QHBoxLayout()
        self.browser_row.setSpacing(10)
        self.browser_row.setAlignment(Qt.AlignVCenter)
        
        self.browser_label = QLabel(self.tr("Navegador:"))
        
        self.browser_combo = AutoPopupComboBox()
        self.browser_combo.addItems(["brave", "chrome", "chromium", "edge", "firefox", "opera", "safari", "vivaldi"])
        self.browser_combo.setFixedWidth(150)
        
        self.browser_profile = QLineEdit()
        self.browser_profile.setPlaceholderText(self.tr("Perfil / Contenedor (Opcional, ej: Profile 1)"))
        self.browser_profile.setFixedWidth(300)
        
        self.browser_row.addWidget(self.browser_label)
        self.browser_row.addWidget(self.browser_combo)
        self.browser_row.addWidget(self.browser_profile)
        self.browser_row.addStretch()
        
        self.browser_widget = QWidget()
        self.browser_widget.setLayout(self.browser_row)
        self.browser_row.setContentsMargins(0,0,0,0)
        self.main_layout.addWidget(self.browser_widget)

        self.main_layout.addSpacing(15)

        # Info Card
        self.info_card = QFrame()
        self.info_card.setObjectName("infoCard")
        card_layout = QVBoxLayout(self.info_card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card_layout.setSpacing(10)

        card_title = QLabel(self.tr("¿Cómo obtener cookies locales de forma segura?"))
        font_card = card_title.font()
        font_card.setBold(True)
        card_title.setFont(font_card)
        card_layout.addWidget(card_title)

        card_desc = QLabel(self.tr("Se recomienda exportar tu sesión actual usando la extensión de navegador Get cookies.txt\nLOCALLY en formato NetScape y luego cargar ese archivo .txt usando la opción 'Archivo Manual'.\nEs el método más seguro y confiable."))
        card_desc.setWordWrap(True)
        card_layout.addWidget(card_desc)

        self.github_btn = QPushButton(self.tr("Descargar 'Get cookies.txt LOCALLY' (GitHub)"))
        self.github_btn.setObjectName("githubButton")
        self.github_btn.setCursor(Qt.PointingHandCursor)
        # left align the button
        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.github_btn)
        btn_layout.addStretch()
        card_layout.addLayout(btn_layout)

        self.main_layout.addWidget(self.info_card)

        # Spacer
        self.main_layout.addSpacerItem(QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding))

        # Connections
        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        self.browser_combo.currentIndexChanged.connect(self.save_settings)
        self.browser_profile.textChanged.connect(self.save_settings)
        self.browse_btn.clicked.connect(self.browse_file)
        self.github_btn.clicked.connect(self.open_github)
        self.test_btn.clicked.connect(self.test_cookies)

    def load_current_settings(self):
        config = get_config()
        mode = config.get("cookies_mode", "none")
        file_path = config.get("cookies_file", "")
        browser = config.get("cookies_browser", "chrome")
        
        index = self.mode_combo.findData(mode)
        if index >= 0:
            self.mode_combo.setCurrentIndex(index)
            
        b_index = self.browser_combo.findText(browser)
        if b_index >= 0:
            self.browser_combo.setCurrentIndex(b_index)
            
        profile = config.get("cookies_profile", "")
        self.browser_profile.setText(profile)
        self.browser_profile.setCursorPosition(0)
            
        self.file_input.setText(file_path)
        self.file_input.setCursorPosition(0)

    def save_settings(self, *args):
        if getattr(self, '_is_loading', False):
            return
        config = get_config()
        config["cookies_mode"] = self.mode_combo.currentData()
        config["cookies_file"] = self.file_input.text()
        config["cookies_browser"] = self.browser_combo.currentText()
        config["cookies_profile"] = self.browser_profile.text()
        save_config(config)

    def on_mode_changed(self):
        mode = self.mode_combo.currentData()
        
        self.file_widget.setVisible(mode == "file")
        self.browser_widget.setVisible(mode == "browser")
        
        self.test_btn.setEnabled(mode != "none")
        self.test_status_label.setText("")
            
        self.save_settings()

    def test_cookies(self):
        mode = self.mode_combo.currentData()
        file_path = self.file_input.text()
        browser = self.browser_combo.currentText()
        profile = self.browser_profile.text()
        
        self.test_status_label.setText(self.tr("Probando..."))
        self.test_status_label.setIcon(QIcon())
        self.test_status_label.setStyleSheet("border: none; background: transparent; color: #d8c94a; padding: 0px;") # estado_aviso
        self.test_btn.setEnabled(False)
        
        self.worker = CookieTestWorker(mode, file_path, browser, profile)
        self.worker.finished.connect(self.on_test_finished)
        self.worker.start()
        
    def on_test_finished(self, success, message):
        self.test_btn.setEnabled(True)
        self.test_status_label.setText(message)
        icons_dir = os.path.join(get_src_dir(), "assets", "icons", "svg")
        if success:
            self.test_status_label.setIcon(QIcon(generate_tinted_svg("check_circle", "#40d66b")))
            self.test_status_label.setStyleSheet("border: none; background: transparent; color: #40d66b; padding: 0px;") # estado_exito
        else:
            self.test_status_label.setIcon(QIcon(generate_tinted_svg("error", "#ff6b5f")))
            self.test_status_label.setStyleSheet("border: none; background: transparent; color: #ff6b5f; padding: 0px;") # estado_error

    def browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            self.tr("Seleccionar archivo de cookies"), 
            "", 
            self.tr("Archivos de texto (*.txt);;Todos los archivos (*.*)")
        )
        if file_path:
            self.file_input.setText(file_path)
            self.file_input.setCursorPosition(0)
            self.save_settings()

    def open_github(self):
        QDesktopServices.openUrl(QUrl("https://github.com/kairi003/Get-cookies.txt-LOCALLY"))
