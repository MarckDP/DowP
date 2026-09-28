# src/gui/tabs/settings/pages/system_page.py
import os
import time
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QScrollArea,
    QPushButton,
)
from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices

from core.logger.logger_manager import logger
from core.utils.config_manager import get_config
from core.utils.hardware_detector import detect_hardware
from gui.styles import get_theme_token
from gui.widgets.top_aligned_layout import TopAlignedVBoxLayout


class ScanHardwareThread(QThread):
    """Hilo secundario para realizar la detección de hardware sin congelar la UI."""
    finished_scan = Signal(dict)

    def run(self):
        info = detect_hardware(force_refresh=True)
        self.finished_scan.emit(info)


class SystemPage(QWidget):
    """Página de ajustes: Acerca de."""

    def __init__(self):
        super().__init__()
        self.scan_thread = None
        self.init_ui()
        self.load_hardware_info()

    # ── Apoyo, enlaces y agradecimientos (datos en core/credits.py) ──────────
    @staticmethod
    def _make_divider():
        divider = QFrame()
        divider.setObjectName("settingsDivider")
        divider.setFrameShape(QFrame.HLine)
        divider.setFrameShadow(QFrame.Sunken)
        return divider

    def _section_title(self, text):
        label = QLabel(text)
        label.setStyleSheet("font-weight: bold; font-size: 13px; color: #ffffff; "
                            "border: none; background: transparent; margin-bottom: 4px;")
        return label

    def _build_support_card(self):
        from core import credits
        from gui.dialogs.about_dialogs import make_link_label

        card = QFrame()
        card.setObjectName("supportCard")
        card.setProperty("variant", "card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        title = QLabel(self.tr("Apoya DowP"))
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #EEEEEE; border: none; background: transparent;")
        layout.addWidget(title)

        desc = QLabel(self.tr(
            "DowP es gratis y lo seguirá siendo. Si te resulta útil, puedes invitarme un café "
            "para ayudar a mantenerlo."))
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #888888; font-size: 11px; border: none; background: transparent;")
        layout.addWidget(desc)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        btn_kofi = QPushButton(self.tr("Invítame un café en Ko-fi"))
        btn_kofi.setProperty("variant", "primary")
        btn_kofi.setCursor(Qt.PointingHandCursor)
        btn_kofi.setToolTip(credits.KOFI_URL)
        btn_kofi.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(credits.KOFI_URL)))
        btn_other = QPushButton(self.tr("Otras formas de apoyar"))
        btn_other.setProperty("variant", "secondary")
        btn_other.setCursor(Qt.PointingHandCursor)
        btn_other.clicked.connect(self._open_support_dialog)
        buttons.addWidget(btn_kofi)
        buttons.addWidget(btn_other)
        buttons.addStretch()
        layout.addLayout(buttons)

        links = QHBoxLayout()
        links.setSpacing(16)
        for text, url in ((self.tr("X (@MarcklaX)"), credits.AUTHOR_X_URL),
                          (self.tr("GitHub de DowP"), credits.PROJECT_GITHUB_URL),
                          (self.tr("Página web"), credits.PROJECT_WEBSITE_URL)):
            links.addWidget(make_link_label(text, url, "font-size: 12px;"))
        links.addStretch()
        layout.addLayout(links)
        return card

    def _build_acknowledgements(self):
        from PySide6.QtCore import QCoreApplication
        from core import credits
        from gui.dialogs.about_dialogs import make_link_label

        self.content_layout.addWidget(self._section_title(self.tr("Agradecimientos")))
        for name, contribution, url in credits.ACKNOWLEDGEMENTS:
            row = QHBoxLayout()
            row.setSpacing(8)
            name_lbl = make_link_label(QCoreApplication.translate("Credits", name), url,
                                       "font-size: 12px; font-weight: bold; color: #EEEEEE;")
            row.addWidget(name_lbl)
            what = QLabel("— " + QCoreApplication.translate("Credits", contribution))
            what.setWordWrap(True)
            what.setStyleSheet("color: #aaaaaa; font-size: 12px; border: none; background: transparent;")
            row.addWidget(what, 1)
            self.content_layout.addLayout(row)

        btn_row = QHBoxLayout()
        btn_credits = QPushButton(self.tr("Créditos y licencias"))
        btn_credits.setProperty("variant", "secondary")
        btn_credits.setCursor(Qt.PointingHandCursor)
        btn_credits.clicked.connect(self._open_credits_dialog)
        btn_row.addWidget(btn_credits)
        btn_row.addStretch()
        self.content_layout.addLayout(btn_row)

    def _open_support_dialog(self):
        from gui.dialogs.about_dialogs import SupportDialog
        SupportDialog(self.window()).exec()

    def _open_credits_dialog(self):
        from gui.dialogs.about_dialogs import CreditsDialog
        CreditsDialog(self.window()).exec()

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(12)

        # Title
        self.title_label = QLabel(self.tr("Acerca de"))
        self.title_label.setObjectName("settingsTitle")
        self.main_layout.addWidget(self.title_label)

        # Divider
        line = QFrame()
        line.setObjectName("settingsDivider")
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        self.main_layout.addWidget(line)

        # Scroll Area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")

        self.scroll_content = QWidget()
        self.scroll_content.setObjectName("settingsScrollContent")
        self.scroll_content.setStyleSheet("QWidget#settingsScrollContent { background-color: transparent; border: none; }")

        self.content_layout = TopAlignedVBoxLayout(self.scroll_content)
        self.content_layout.setContentsMargins(0, 10, 10, 0)
        self.content_layout.setSpacing(14)

        # --- SECCIÓN: VERSIÓN Y NOVEDADES ---
        # Mismo contenido que la ventana de "Novedades" que se muestra una vez
        # tras actualizar (gui/dialogs/whats_new_dialog.py) -- una sola
        # implementación, aquí se puede volver a consultar cuando se quiera.
        from core.version import APP_VERSION
        from gui.dialogs.whats_new_dialog import build_whats_new_content

        # --- APOYO Y ENLACES (arriba de todo) ---
        self.content_layout.addWidget(self._build_support_card())

        self.content_layout.addWidget(build_whats_new_content(APP_VERSION, self))

        # --- AGRADECIMIENTOS + CRÉDITOS Y LICENCIAS ---
        self.content_layout.addWidget(self._make_divider())
        self._build_acknowledgements()

        version_divider = QFrame()
        version_divider.setObjectName("settingsDivider")
        version_divider.setFrameShape(QFrame.HLine)
        version_divider.setFrameShadow(QFrame.Sunken)
        self.content_layout.addWidget(version_divider)

        # --- SECCIÓN: SISTEMA (Texto puro) ---
        self.section_title = QLabel(self.tr("Sistema"))
        self.section_title.setStyleSheet("""
            font-weight: bold;
            font-size: 13px;
            color: #ffffff;
            border: none;
            background: transparent;
            margin-bottom: 4px;
        """)
        self.content_layout.addWidget(self.section_title)
        
        # 1. Sistema Operativo
        self.lbl_os = self._create_spec_row(self.content_layout, self.tr("Sistema operativo"), "Cargando...")
        # 2. CPU
        self.lbl_cpu = self._create_spec_row(self.content_layout, self.tr("Procesador (CPU)"), "Cargando...")
        # 3. RAM
        self.lbl_ram = self._create_spec_row(self.content_layout, self.tr("Memoria RAM total"), "Cargando...")
        # 4. GPU
        self.lbl_gpu = self._create_spec_row(self.content_layout, self.tr("Tarjeta gráfica (GPU)"), "Cargando...")
        # 5. Encoder Principal
        self.lbl_encoder = self._create_spec_row(self.content_layout, self.tr("Codificador preferido"), "Cargando...")

        # Subsección: Encoders detectados
        lbl_enc_title = QLabel(self.tr("Codificadores de vídeo detectados (FFmpeg)"))
        lbl_enc_title.setStyleSheet("""
            font-weight: bold;
            font-size: 11px;
            color: #aaaaaa;
            border: none;
            background: transparent;
            margin-top: 8px;
        """)
        self.content_layout.addWidget(lbl_enc_title)

        self.encoders_layout = QHBoxLayout()
        self.encoders_layout.setSpacing(6)
        self.encoders_layout.setContentsMargins(0, 0, 0, 0)
        self.encoders_layout.setAlignment(Qt.AlignLeft)
        
        self.encoders_widget = QWidget()
        self.encoders_widget.setStyleSheet("border: none; background: transparent;")
        self.encoders_widget.setLayout(self.encoders_layout)
        self.content_layout.addWidget(self.encoders_widget)

        # Botones pequeños de acción
        self.action_layout = QHBoxLayout()
        self.action_layout.setContentsMargins(0, 10, 0, 0)
        self.action_layout.setSpacing(8)

        borde_btn = get_theme_token('borde', '#3d3d3d')
        btn_style = f"""
            QPushButton {{
                background-color: transparent;
                border: 1px solid {borde_btn};
                border-radius: 4px;
                color: #dddddd;
                font-weight: bold;
                font-size: 11px;
                padding: 4px 10px;
            }}
            QPushButton:hover {{
                background-color: {get_theme_token('fondo_hover', '#2a2a2a')};
                color: #ffffff;
                border-color: #555555;
            }}
            QPushButton:disabled {{
                color: #666666;
                border-color: #2d2d2d;
            }}
        """

        self.btn_redetect = QPushButton(self.tr("Redetectar hardware"))
        self.btn_redetect.setFixedHeight(28)
        self.btn_redetect.setCursor(Qt.PointingHandCursor)
        self.btn_redetect.setStyleSheet(btn_style)
        self.btn_redetect.setToolTip(self.tr("Vuelve a escanear la CPU, GPU y encoders de vídeo disponibles"))
        self.btn_redetect.clicked.connect(self.on_redetect_clicked)

        self.btn_open_log = QPushButton(self.tr("Ver registro FFmpeg"))
        self.btn_open_log.setFixedHeight(28)
        self.btn_open_log.setCursor(Qt.PointingHandCursor)
        self.btn_open_log.setStyleSheet(btn_style)
        self.btn_open_log.setToolTip(self.tr("Abre el archivo ffmpeg_encoders_log.json con el informe completo"))
        self.btn_open_log.clicked.connect(self.on_open_log_clicked)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #888888; font-size: 10px; border: none; background: transparent;")

        self.action_layout.addWidget(self.btn_redetect)
        self.action_layout.addWidget(self.btn_open_log)
        self.action_layout.addWidget(self.lbl_status)
        self.action_layout.addStretch()

        self.content_layout.addLayout(self.action_layout)

        self.scroll_area.setWidget(self.scroll_content)
        self.main_layout.addWidget(self.scroll_area)

    def _create_spec_row(self, parent_layout, label_text, default_val):
        row = QHBoxLayout()
        row.setContentsMargins(0, 3, 0, 3)
        lbl_title = QLabel(label_text)
        lbl_title.setStyleSheet("font-weight: bold; font-size: 11px; color: #aaaaaa; border: none; background: transparent;")
        lbl_title.setFixedWidth(200)
        
        lbl_val = QLabel(default_val)
        lbl_val.setStyleSheet("font-size: 11px; color: #ffffff; border: none; background: transparent;")
        lbl_val.setTextInteractionFlags(Qt.TextSelectableByMouse)
        
        row.addWidget(lbl_title)
        row.addWidget(lbl_val, 1)
        parent_layout.addLayout(row)
        return lbl_val

    def load_hardware_info(self, force: bool = False):
        """Carga y muestra la información de hardware desde la caché o ejecutando detección."""
        from core.utils.hardware_detector import detect_hardware
        info = detect_hardware(force_refresh=force)

        self.lbl_os.setText(info.get("os_name", "Desconocido"))
        self.lbl_cpu.setText(info.get("cpu_name", "Desconocido"))
        self.lbl_ram.setText(info.get("ram_size", "Desconocido"))
        self.lbl_gpu.setText(info.get("gpu_name", "Desconocido"))
        
        pref = info.get("preferred_encoder", "libx264")
        pretty_encoder = self._pretty_encoder_name(pref)
        self.lbl_encoder.setText(pretty_encoder)

        self._update_encoder_badges(info.get("supported_encoders", []))

    def on_open_log_clicked(self):
        """Abre el archivo ffmpeg_encoders_log.json en el visor predeterminado del SO."""
        import os
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        from core.utils.paths import get_app_data_dir

        log_path = os.path.join(get_app_data_dir(), "ffmpeg_encoders_log.json")
        if not os.path.exists(log_path):
            from core.utils.hardware_detector import detect_hardware
            info = detect_hardware(force_refresh=True)
            log_path = info.get("ffmpeg_log_path", log_path)

        if os.path.exists(log_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(log_path))
        else:
            self.lbl_status.setText(self.tr("No se pudo generar el archivo de log."))

    def _pretty_encoder_name(self, encoder_code: str) -> str:
        names = {
            "h264_nvenc": self.tr("NVIDIA NVENC (Acelerado por GPU)"),
            "hevc_nvenc": self.tr("NVIDIA NVENC HEVC (Acelerado por GPU)"),
            "h264_videotoolbox": self.tr("Apple VideoToolbox (Acelerado por Hardware)"),
            "hevc_videotoolbox": self.tr("Apple VideoToolbox HEVC (Acelerado por Hardware)"),
            "h264_qsv": self.tr("Intel QuickSync (Acelerado por GPU)"),
            "h264_amf": self.tr("AMD AMF (Acelerado por GPU)"),
            "h264_vaapi": self.tr("Linux VA-API (Acelerado por Hardware)"),
            "libx264": self.tr("CPU Software - x264 (Estándar)"),
        }
        return names.get(encoder_code, f"{encoder_code} (Soportado)")

    def _update_encoder_badges(self, supported_list: list):
        while self.encoders_layout.count():
            child = self.encoders_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        if not supported_list:
            supported_list = ["libx264"]

        for enc in supported_list:
            badge = QLabel(enc)
            accent = get_theme_token('acento_primario', '#B9E640')
            badge.setStyleSheet(f"""
                QLabel {{
                    background-color: transparent;
                    color: {accent};
                    border: 1px solid {accent};
                    border-radius: 4px;
                    padding: 2px 6px;
                    font-size: 10px;
                    font-weight: bold;
                }}
            """)
            self.encoders_layout.addWidget(badge)

    def on_redetect_clicked(self):
        self.btn_redetect.setEnabled(False)
        self.btn_redetect.setText(self.tr("Escaneando..."))
        self.lbl_status.setText(self.tr("Analizando componentes..."))

        self.scan_thread = ScanHardwareThread()
        self.scan_thread.finished_scan.connect(self._on_scan_finished)
        self.scan_thread.start()

    def _on_scan_finished(self, info):
        self.load_hardware_info(force=False)
        self.btn_redetect.setEnabled(True)
        self.btn_redetect.setText(self.tr("Redetectar hardware"))
        sec = info.get("scan_duration_sec", 0.5)
        self.lbl_status.setText(self.tr("Actualizado en {0}s").format(sec))
        
        if self.scan_thread:
            self.scan_thread.deleteLater()
            self.scan_thread = None
