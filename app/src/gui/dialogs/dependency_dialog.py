# src/gui/dialogs/dependency_dialog.py
import os
import sys
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                               QProgressBar, QPushButton, QFrame, QWidget)
from PySide6.QtCore import Qt, Signal, Slot, QThread
from PySide6.QtGui import QIcon, QFont

from gui.widgets.title_bar import CustomTitleBar
from gui.styles import get_theme_token
from core.logger.logger_manager import logger

# Import dependency verification/download modules
from core.setup.ytdlp_setup import check_ytdlp, download_ytdlp, get_local_version as get_ytdlp_version
from core.setup.ffmpeg_setup import check_ffmpeg, download_ffmpeg, get_local_version as get_ffmpeg_version
from core.setup.deno_setup import check_deno, download_deno, get_local_version as get_deno_version


class DependencyInstallerWorker(QThread):
    """
    Hilo de ejecución en segundo plano para verificar y descargar las dependencias
    una a una, reportando el progreso a la interfaz principal.
    """
    dependency_started = Signal(str)            # dep_id
    dependency_progress = Signal(str, int)       # dep_id, porcentaje
    dependency_finished = Signal(str, bool, str) # dep_id, éxito, versión/mensaje
    all_finished = Signal(bool)                  # éxito general (True/False)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_cancelled = False

    def run(self):
        try:
            # --- 1. yt-dlp ---
            if not check_ytdlp():
                if self.is_cancelled:
                    self.all_finished.emit(False)
                    return
                self.dependency_started.emit("ytdlp")
                def callback_ytdlp(pct):
                    if not self.is_cancelled:
                        self.dependency_progress.emit("ytdlp", pct)
                success, msg = download_ytdlp(progress_callback=callback_ytdlp)
                if not success:
                    self.dependency_finished.emit("ytdlp", False, msg)
                    self.all_finished.emit(False)
                    return
                version = get_ytdlp_version(force_check=True) or "Listo"
                self.dependency_finished.emit("ytdlp", True, version)
            else:
                version = get_ytdlp_version() or "Listo"
                self.dependency_finished.emit("ytdlp", True, version)

            # --- 2. FFmpeg ---
            if not check_ffmpeg():
                if self.is_cancelled:
                    self.all_finished.emit(False)
                    return
                self.dependency_started.emit("ffmpeg")
                def callback_ffmpeg(pct):
                    if not self.is_cancelled:
                        self.dependency_progress.emit("ffmpeg", pct)
                success, msg = download_ffmpeg(progress_callback=callback_ffmpeg)
                if not success:
                    self.dependency_finished.emit("ffmpeg", False, msg)
                    self.all_finished.emit(False)
                    return
                version = get_ffmpeg_version(force_check=True) or "Listo"
                self.dependency_finished.emit("ffmpeg", True, version)
            else:
                version = get_ffmpeg_version() or "Listo"
                self.dependency_finished.emit("ffmpeg", True, version)

            # --- 3. Deno ---
            if not check_deno():
                if self.is_cancelled:
                    self.all_finished.emit(False)
                    return
                self.dependency_started.emit("deno")
                def callback_deno(pct):
                    if not self.is_cancelled:
                        self.dependency_progress.emit("deno", pct)
                success, msg = download_deno(progress_callback=callback_deno)
                if not success:
                    self.dependency_finished.emit("deno", False, msg)
                    self.all_finished.emit(False)
                    return
                version = get_deno_version(force_check=True) or "Listo"
                self.dependency_finished.emit("deno", True, version)
            else:
                version = get_deno_version() or "Listo"
                self.dependency_finished.emit("deno", True, version)

            self.all_finished.emit(True)

        except Exception as e:
            logger.error(f"Error en DependencyInstallerWorker: {e}", exc_info=True)
            self.all_finished.emit(False)

    def cancel(self):
        self.is_cancelled = True


class DependencyDialog(QDialog):
    """
    Ventana inicial elegante y compacta que aparece únicamente si faltan dependencias.
    Muestra la lista de componentes (yt-dlp, FFmpeg, Deno), colorea las instaladas
    en verde y descarga las faltantes mostrando una barra de progreso.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle(self.tr("Configuración de Dependencias"))
        self.setFixedSize(450, 310)
        
        self.worker = None
        self.dep_widgets = {}
        
        self.init_ui()
        self.start_installation()

    def init_ui(self):
        # Cargar tokens de temas
        bg_secundario = get_theme_token("fondo_secundario", "#121212")
        bg_principal = get_theme_token("fondo_principal", "#0a0a0a")
        borde_color = get_theme_token("borde_normal", "#222222")
        texto_principal = get_theme_token("texto_principal", "#e0e0e0")
        texto_secundario = get_theme_token("texto_secundario", "#666666")
        acento_primario = get_theme_token("acento_primario", "#B9E640")
        btn_bg = get_theme_token("boton_secundario_fondo", "#1b3b22")
        btn_fg = get_theme_token("boton_secundario_texto", "#B9E640")
        btn_hover = get_theme_token("boton_secundario_hover", "#224a2b")

        # Layout general del QDialog
        main_dialog_layout = QVBoxLayout(self)
        main_dialog_layout.setContentsMargins(0, 0, 0, 0)
        main_dialog_layout.setSpacing(0)

        from core.utils.font_manager import get_active_font_family
        active_font = get_active_font_family()

        # Contenedor central (Frame con bordes redondeados y fondo oscuro)
        self.central_widget = QFrame()
        self.central_widget.setObjectName("DependencyDialogContainer")
        self.central_widget.setStyleSheet(f"""
            QFrame#DependencyDialogContainer {{
                background-color: {bg_secundario};
                border: 1px solid {borde_color};
                border-radius: 12px;
            }}
            QLabel {{
                color: {texto_principal};
                font-family: '{active_font}', 'Segoe UI', sans-serif;
            }}
            QProgressBar {{
                background-color: {bg_principal};
                border: 1px solid {borde_color};
                border-radius: 4px;
                text-align: center;
                height: 8px;
            }}
            QProgressBar::chunk {{
                background-color: {acento_primario};
                border-radius: 3px;
            }}
            QPushButton {{
                background-color: {btn_bg};
                color: {btn_fg};
                border: none;
                border-radius: 8px;
                padding: 6px 12px;
                font-family: '{active_font}', 'Segoe UI', sans-serif;
                font-weight: bold;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {btn_hover};
            }}
            QPushButton#cancelButton {{
                background-color: transparent;
                color: #ff6b5f;
                border: 1px solid #ff6b5f;
                border-radius: 8px;
                padding: 6px 12px;
                font-weight: bold;
                font-size: 11px;
            }}
            QPushButton#cancelButton:hover {{
                background-color: rgba(255, 107, 95, 0.15);
            }}
        """)
        main_dialog_layout.addWidget(self.central_widget)

        # Layout interno del contenedor central
        central_layout = QVBoxLayout(self.central_widget)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        # Barra de título personalizada
        self.title_bar = CustomTitleBar(self, self.windowTitle())
        self.title_bar.btn_min.hide()
        self.title_bar.btn_max.hide()
        self.title_bar.btn_close.clicked.disconnect()
        self.title_bar.btn_close.clicked.connect(self.on_close_clicked)
        self.title_bar.setStyleSheet(f"""
            CustomTitleBar {{
                background-color: #080808;
                border-bottom: 1px solid {borde_color};
                border-top-left-radius: 11px;
                border-top-right-radius: 11px;
            }}
        """)
        central_layout.addWidget(self.title_bar)

        # Layout del contenido del diálogo
        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(20, 16, 20, 16)
        content_layout.setSpacing(10)

        # Contenedor para la lista de dependencias
        deps_layout = QVBoxLayout()
        deps_layout.setSpacing(8)

        # Crear widgets de dependencias (sin descripciones)
        self.add_dependency_item(deps_layout, "ytdlp", "yt-dlp")
        self.add_dependency_item(deps_layout, "ffmpeg", "FFmpeg")
        self.add_dependency_item(deps_layout, "deno", "Deno")

        content_layout.addLayout(deps_layout)

        # Mensaje de estado general (Abajo)
        self.status_message = QLabel(self.tr("Verificando estado del sistema..."))
        self.status_message.setStyleSheet("font-size: 11px; font-weight: bold; color: #aaaaaa;")
        content_layout.addWidget(self.status_message)

        # Fila de acciones/botones
        actions_layout = QHBoxLayout()
        
        self.btn_retry = QPushButton(self.tr("Reintentar"))
        self.btn_retry.clicked.connect(self.start_installation)
        self.btn_retry.hide() # Oculto por defecto, solo en fallos
        
        self.btn_cancel = QPushButton(self.tr("Salir"))
        self.btn_cancel.setObjectName("cancelButton")
        self.btn_cancel.clicked.connect(self.on_close_clicked)
        
        actions_layout.addStretch()
        actions_layout.addWidget(self.btn_retry)
        actions_layout.addWidget(self.btn_cancel)
        content_layout.addLayout(actions_layout)

        central_layout.addLayout(content_layout)

    def add_dependency_item(self, layout, dep_id, name):
        """Crea y añade un elemento de dependencia al layout."""
        item_frame = QFrame()
        item_frame.setObjectName(f"dep_item_frame_{dep_id}")
        item_frame.setStyleSheet(f"""
            QFrame#dep_item_frame_{dep_id} {{
                background-color: {get_theme_token("fondo_principal", "#0a0a0a")};
                border: 1px solid {get_theme_token("borde_sutil", "#1c1c1c")};
                border-radius: 8px;
            }}
            QLabel {{
                border: none;
                background-color: transparent;
            }}
        """)
        frame_layout = QVBoxLayout(item_frame)
        frame_layout.setContentsMargins(12, 10, 12, 10)
        frame_layout.setSpacing(6)

        # Cabecera: Nombre y Estado
        header_layout = QHBoxLayout()
        
        name_lbl = QLabel(f"<b>{name}</b>")
        name_lbl.setStyleSheet("font-size: 12px;")
        
        status_lbl = QLabel(self.tr("Verificando..."))
        status_lbl.setStyleSheet(f"color: {get_theme_token('texto_secundario', '#666666')}; font-size: 11px; font-weight: bold;")
        
        header_layout.addWidget(name_lbl)
        header_layout.addStretch()
        header_layout.addWidget(status_lbl)
        frame_layout.addLayout(header_layout)

        # Barra de progreso
        progress_bar = QProgressBar()
        progress_bar.setRange(0, 100)
        progress_bar.setValue(0)
        progress_bar.setTextVisible(False)
        progress_bar.hide() # Oculta hasta que empiece a descargar
        frame_layout.addWidget(progress_bar)

        layout.addWidget(item_frame)

        # Guardar referencias para actualizarlas
        self.dep_widgets[dep_id] = {
            "status_lbl": status_lbl,
            "progress_bar": progress_bar,
            "name": name
        }

    def start_installation(self):
        """Inicia el proceso de verificación y descarga asíncrona."""
        self.btn_retry.hide()
        self.status_message.setText(self.tr("Iniciando instalador de dependencias..."))
        self.status_message.setStyleSheet("color: #aaaaaa; font-size: 11px;")

        # Inicializar estados visuales de dependencias no verificadas
        for dep_id, widgets in self.dep_widgets.items():
            widgets["status_lbl"].setText(self.tr("Esperando..."))
            widgets["status_lbl"].setStyleSheet(f"color: {get_theme_token('texto_secundario', '#666666')}; font-size: 11px;")
            widgets["progress_bar"].hide()

        # Lanzar hilo secundario
        self.worker = DependencyInstallerWorker(self)
        
        # Conectar señales explícitamente usando Qt.QueuedConnection para forzar la ejecución en el hilo principal de la GUI
        self.worker.dependency_started.connect(self.on_dep_started, Qt.QueuedConnection)
        self.worker.dependency_progress.connect(self.on_dep_progress, Qt.QueuedConnection)
        self.worker.dependency_finished.connect(self.on_dep_finished, Qt.QueuedConnection)
        self.worker.all_finished.connect(self.on_all_finished, Qt.QueuedConnection)
        
        self.worker.start()

    @Slot(str)
    def on_dep_started(self, dep_id):
        """Se activa cuando una dependencia comienza a descargarse."""
        widgets = self.dep_widgets[dep_id]
        widgets["status_lbl"].setText(self.tr("Descargando... 0%"))
        widgets["status_lbl"].setStyleSheet(f"color: {get_theme_token('estado_aviso', '#d8c94a')}; font-size: 11px; font-weight: bold;")
        widgets["progress_bar"].setValue(0)
        widgets["progress_bar"].show()
        
        self.status_message.setText(self.tr("Descargando {0}...").format(widgets["name"]))

    @Slot(str, int)
    def on_dep_progress(self, dep_id, percent):
        """Se activa al recibir progreso de la descarga."""
        widgets = self.dep_widgets[dep_id]
        widgets["status_lbl"].setText(self.tr("Descargando... {0}%").format(percent))
        widgets["progress_bar"].setValue(percent)

    @Slot(str, bool, str)
    def on_dep_finished(self, dep_id, success, version_or_msg):
        """Se activa cuando una dependencia termina su verificación o descarga."""
        widgets = self.dep_widgets[dep_id]
        widgets["progress_bar"].hide()
        
        if success:
            widgets["status_lbl"].setText(self.tr("Instalada (v{0})").format(version_or_msg))
            widgets["status_lbl"].setStyleSheet(f"color: {get_theme_token('estado_exito', '#40d66b')}; font-size: 11px; font-weight: bold;")
        else:
            widgets["status_lbl"].setText(self.tr("Error al instalar"))
            widgets["status_lbl"].setStyleSheet(f"color: {get_theme_token('estado_error', '#ff6b5f')}; font-size: 11px; font-weight: bold;")
            logger.error(f"Error instalando {dep_id}: {version_or_msg}")

    @Slot(bool)
    def on_all_finished(self, overall_success):
        """Se activa cuando el hilo secundario ha finalizado."""
        if self.worker and self.worker.isRunning():
            self.worker.wait(1000)
        if overall_success:
            self.status_message.setText(self.tr("¡Todas las dependencias instaladas correctamente! Iniciando..."))
            self.status_message.setStyleSheet(f"color: {get_theme_token('estado_exito', '#40d66b')}; font-size: 11px; font-weight: bold;")
            self.thread().msleep(800)
            self.accept()
        else:
            self.status_message.setText(self.tr("Error: Una o más dependencias no pudieron ser configuradas."))
            self.status_message.setStyleSheet(f"color: {get_theme_token('estado_error', '#ff6b5f')}; font-size: 11px; font-weight: bold;")
            self.btn_retry.show()

    def on_close_clicked(self):
        """Maneja el cierre voluntario de la ventana."""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait()
        self.reject()

    def reject(self):
        """Asegura que al rechazar (cerrar), detengamos el hilo."""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait()
        super().reject()
