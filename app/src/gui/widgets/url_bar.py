# src/gui/widgets/url_bar.py
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLineEdit, QSizePolicy, QPushButton
from PySide6.QtCore import Signal, Qt, QSize
from core.logger.logger_manager import logger
from gui.widgets.animated_button import AnimatedButton

class URLBar(QWidget):
    analyze_requested = Signal(str)
    solo_toggled = Signal(bool)
    # Lupa o Enter con texto que no es URL: abre la ventana de búsqueda con ese texto
    # (vacío si no hay) -- ver AdvancedProcessTab.open_media_search.
    search_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.init_ui()
        
        # Registrar el campo de URL en el monitor de portapapeles
        from core.utils.clipboard_monitor import ClipboardURLMonitor
        monitor = ClipboardURLMonitor.instance()
        monitor.register(self.url_input)
        monitor.url_detected.connect(self._on_clipboard_url_detected)

    def _on_clipboard_url_detected(self, url):
        """Llamado cuando el monitor de portapapeles pega una URL."""
        # Solo auto-analizar si la URL fue pegada en NUESTRO campo
        if self.url_input.text().strip() != url:
            return
        # Verificar si auto-análisis está activado
        from core.utils.config_manager import get_config
        if get_config().get("auto_analyze", False):
            self.analyze_requested.emit(url)

    def _on_text_edited(self, text):
        """Llamado cuando el usuario edita el texto manualmente (incluyendo pegar)."""
        url = text.strip()
        if not url:
            return
            
        # Verificar si auto-análisis está activado
        from core.utils.config_manager import get_config
        if not get_config().get("auto_analyze", False):
            return
            
        # Comprobar si parece una URL válida
        if not url.startswith(("http://", "https://")):
            return
            
        # Comprobar si el texto coincide con el portapapeles (indica que fue pegado)
        from PySide6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        if clipboard:
            clip_text = clipboard.text().strip()
            if url == clip_text:
                logger.info("URLBar: Detección de pegado manual. Analizando...")
                self.analyze_requested.emit(url)

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.solo_btn = AnimatedButton(self.tr("SOLO"))
        self.solo_btn.setCheckable(True)
        from core.utils.config_manager import get_config
        self.solo_btn.setChecked(get_config().get("solo_mode", True))
        self.solo_btn.setObjectName("soloButton")
        self.solo_btn.setFixedWidth(65)
        self.solo_btn.toggled.connect(self.solo_toggled.emit)

        from gui.styles import apply_cut_button_style
        self.search_btn = QPushButton()
        self.search_btn.setFixedSize(34, 34)
        self.search_btn.setCursor(Qt.PointingHandCursor)
        self.search_btn.setToolTip(self.tr("Buscar videos o audios por nombre"))
        self.search_btn.setIconSize(QSize(18, 18))
        self.search_btn.clicked.connect(self._on_search_clicked)
        apply_cut_button_style(self.search_btn, "normal", icon_size=18, shape="square", icon_name="search.svg")

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText(self.tr("Pega la URL aquí (YouTube, Twitch, etc.) o escribe algo para buscar"))
        self.url_input.returnPressed.connect(self.on_analyze_clicked)
        self.url_input.textEdited.connect(self._on_text_edited)
        
        self.analyze_btn = AnimatedButton(self.tr("Analizar URL"))
        self.analyze_btn.setFixedWidth(120)
        self.analyze_btn.setObjectName("analyzeButton")
        self.analyze_btn.clicked.connect(self.on_analyze_clicked)

        layout.addWidget(self.solo_btn)
        layout.addWidget(self.search_btn)
        layout.addWidget(self.url_input)
        layout.addWidget(self.analyze_btn)

    def on_analyze_clicked(self):
        url = self.url_input.text().strip()
        if not url:
            return
        from gui.dialogs.media_search_dialog import looks_like_url
        if looks_like_url(url):
            self.analyze_requested.emit(url)
        else:
            # Texto libre (ej. "green screen"): se toma como búsqueda.
            self.search_requested.emit(url)

    def _on_search_clicked(self):
        from gui.dialogs.media_search_dialog import looks_like_url
        text = self.url_input.text().strip()
        self.search_requested.emit("" if looks_like_url(text) else text)

    def set_loading(self, loading: bool):
        self.analyze_btn.setEnabled(not loading)
        self.analyze_btn.setText(self.tr("Analizando...") if loading else self.tr("Analizar URL"))

    def text(self):
        return self.url_input.text().strip()
