# src/gui/tabs/settings/pages/deps_page.py
import os
import platform
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QFrame, QScrollArea, QProgressBar, QMessageBox,
    QRadioButton, QButtonGroup, QFileDialog, QLineEdit, QToolButton,
    QSizePolicy, QGroupBox, QCheckBox, QApplication
)
from PySide6.QtCore import Qt, Signal, QThread, QUrl, QTimer, QCoreApplication
from PySide6.QtGui import QDesktopServices, QIcon
from core.utils.i18n import logger
from gui.styles import get_theme_token, set_button_variant, apply_folder_browse_button_style, apply_folder_open_button_style
from core.utils.config_manager import get_config, save_config

from core.setup.ffmpeg_setup import (
    check_ffmpeg, download_ffmpeg, get_local_version as ffmpeg_local,
    get_latest_remote_version as ffmpeg_remote, get_ffmpeg_dir,
    get_managed_ffmpeg_dir, get_ffmpeg_path, get_ffprobe_path,
    validate_custom_ffmpeg, FFMPEG_RECOMMENDED_VERSION
)
from core.setup.deno_setup import check_deno, download_deno, get_local_version as deno_local, get_latest_remote_version as deno_remote
from core.setup.ytdlp_setup import check_ytdlp, download_ytdlp, get_local_version as ytdlp_local, get_latest_remote_version as ytdlp_remote
from core.setup.potprovider_setup import (
    check_all as check_potprovider, download_potprovider,
    get_local_version as potprovider_local, get_latest_remote_version as potprovider_remote
)
from core.setup.wpc_setup import (
    check_wpc, install_wpc,
    get_local_version as wpc_local, get_latest_remote_version as wpc_remote,
    get_browser_display_name, detect_system_browser
)
from core.setup.ghostscript_setup import (
    check_ghostscript, download_ghostscript, get_local_version as gs_local,
    get_remote_version as gs_remote, get_install_info as gs_install_info,
)


class UpdateCheckWorker(QThread):
    finished_signal = Signal(dict) # {dep_id: {"local": str, "remote": str}}
    
    def __init__(self, configs, parent=None):
        super().__init__(parent)
        self.configs = configs

    def run(self):
        results = {}
        for config in self.configs:
            dep_id = config["id"]
            try:
                if "channel" in config:
                    remote_ver = config["remote_func"](channel=config["channel"])
                else:
                    remote_ver = config["remote_func"]()
            except Exception as e:
                logger.error(f"Error fetching remote version for {dep_id}: {e}")
                remote_ver = None
            
            try:
                local_ver = config["local_func"]()
            except Exception:
                local_ver = None
                
            results[dep_id] = {"local": local_ver, "remote": remote_ver}
        self.finished_signal.emit(results)


class YTDLPUpdateCheckWorker(QThread):
    """Consulta en segundo plano la última versión remota de yt-dlp según el canal."""
    finished_signal = Signal(object)  # remote_version (str) o None

    def __init__(self, channel, parent=None):
        super().__init__(parent)
        self.channel = channel

    def run(self):
        try:
            remote_ver = ytdlp_remote(channel=self.channel)
        except Exception as e:
            logger.error(f"Error obteniendo la versión remota de yt-dlp ({self.channel}): {e}")
            remote_ver = None
        self.finished_signal.emit(remote_ver)


class WPCUpdateCheckWorker(QThread):
    """Consulta en segundo plano la última versión remota de WPC (pip/PyPI)."""
    finished_signal = Signal(object)  # remote_version (str) o None

    def run(self):
        try:
            remote_ver = wpc_remote()
        except Exception as e:
            logger.error(f"Error obteniendo la versión remota de WPC: {e}")
            remote_ver = None
        self.finished_signal.emit(remote_ver)


class BGUtilUpdateCheckWorker(QThread):
    """Consulta en segundo plano la última versión remota de bgutil-pot en GitHub Releases."""
    finished_signal = Signal(object)  # remote_version (str) o None

    def run(self):
        try:
            remote_ver = potprovider_remote()
        except Exception as e:
            logger.error(f"Error obteniendo la versión remota de bgutil-pot: {e}")
            remote_ver = None
        self.finished_signal.emit(remote_ver)


class DependencyDownloadWorker(QThread):
    finished_signal = Signal(bool, str, str)  # success, message, dep_id
    progress_signal = Signal(str, str) # current phase message, dep_id
    numeric_progress_signal = Signal(int, str) # percentage, dep_id

    def __init__(self, dep_id, download_func, version=None, channel=None, parent=None):
        super().__init__(parent)
        self.dep_id = dep_id
        self.download_func = download_func
        self.version = version
        self.channel = channel

    def run(self):
        try:
            self.progress_signal.emit(f"Descargando {self.dep_id}...", self.dep_id)
            
            def progress_cb(percent):
                self.numeric_progress_signal.emit(percent, self.dep_id)
            
            if self.dep_id == "ffmpeg":
                success, msg = self.download_func(version=self.version, progress_callback=progress_cb)
            elif self.dep_id == "ytdlp":
                success, msg = self.download_func(channel=self.channel, progress_callback=progress_cb)
            else:
                success, msg = self.download_func(progress_callback=progress_cb)
                
            self.finished_signal.emit(success, msg, self.dep_id)
        except Exception as e:
            logger.error(f"Error in DependencyDownloadWorker for {self.dep_id}: {e}")
            self.finished_signal.emit(False, str(e), self.dep_id)


# ═════════════════════════════════════════════════════════════════════════════
# TARJETA 1: PANEL DE OPCIONES DE FFMPEG (Essentials, Full, Nightly y Personalizado)
# ═════════════════════════════════════════════════════════════════════════════

class FFmpegDownloadWorker(QThread):
    finished_signal = Signal(bool, str)
    progress_signal = Signal(str)
    numeric_progress_signal = Signal(int)

    def __init__(self, variant, channel, keep_ffplay, version=None, parent=None):
        super().__init__(parent)
        self.variant = variant
        self.channel = channel
        self.keep_ffplay = keep_ffplay
        self.version = version

    def run(self):
        try:
            self.progress_signal.emit(self.tr("Iniciando descarga de FFmpeg..."))
            def cb(pct):
                self.numeric_progress_signal.emit(pct)
            success, msg = download_ffmpeg(
                variant=self.variant,
                channel=self.channel,
                keep_ffplay=self.keep_ffplay,
                version=self.version,
                progress_callback=cb
            )
            self.finished_signal.emit(success, msg)
        except Exception as e:
            logger.error(f"Error en FFmpegDownloadWorker: {e}")
            self.finished_signal.emit(False, str(e))


class FFmpegOptionsPanel(QFrame):
    """
    Panel avanzado para la configuración y descarga de FFmpeg.
    Permite alternar entre FFmpeg gestionado por DowP y un ejecutable personalizado,
    así como elegir variantes (Essentials / Full) y canales (Recomendada 8.0.1, Latest, Nightly).
    """
    ffmpeg_changed = Signal()

    _TOOLTIP_FFMPEG = QCoreApplication.translate(
        "FFmpegOptionsPanel",
        "FFmpeg es el motor multimedia que DowP utiliza para unir video y audio de alta\n"
        "resolución, extraer pistas de audio, generar ondas de sonido y recodificar medios.\n\n"
        "  • Versión Recomendada ({0}): Probada a fondo para máxima estabilidad con yt-dlp y fragmentos.\n"
        "  • Variante Essentials: Más ligera (~30 MB) con códecs y aceleración por hardware estándar.\n"
        "  • Variante Full: Incluye códecs adicionales (SVT-AV1, libvpx, libplacebo, filtros avanzados).\n"
        "  • Personalizado: Usa un FFmpeg existente instalado en tu sistema."
    ).format(FFMPEG_RECOMMENDED_VERSION)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ffmpegOptionsPanel")
        self._download_worker = None
        self._build_ui()
        self._load_state()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        # ── Título y Estado General ──────────────────────────────────────────
        title_row = QHBoxLayout()
        title_lbl = QLabel(self.tr("FFmpeg (Motor Multimedia)"))
        title_lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #EEEEEE;")
        title_row.addWidget(title_lbl)

        info_btn = QToolButton()
        info_btn.setText("?")
        info_btn.setFixedSize(20, 20)
        info_btn.setStyleSheet(
            "QToolButton { border: 1px solid #555; border-radius: 10px;"
            " color: #AAA; font-size: 11px; background: #2a2a2a; }"
            " QToolButton:hover { background: #3a3a3a; color: #FFF; }"
        )
        info_btn.setToolTip(self._TOOLTIP_FFMPEG)
        title_row.addWidget(info_btn)

        self._status_badge = QLabel(self.tr("Chequeando..."))
        self._status_badge.setStyleSheet("font-weight: bold; font-size: 12px;")
        title_row.addWidget(self._status_badge)

        title_row.addStretch()

        self._version_summary = QLabel(self.tr("Versión: Calculando..."))
        self._version_summary.setStyleSheet("color: #AAAAAA; font-size: 12px;")
        title_row.addWidget(self._version_summary)

        root.addLayout(title_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #333;")
        root.addWidget(sep)

        # ── Selector de Modo Principal ────────────────────────────────────────
        row_mode = QHBoxLayout()
        row_mode.setContentsMargins(0, 0, 0, 0)
        row_mode.setSpacing(14)

        mode_lbl = QLabel(self.tr("Origen:"))
        mode_lbl.setFixedWidth(80)
        mode_lbl.setStyleSheet("color: #DDD; font-size: 12px; font-weight: bold;")
        row_mode.addWidget(mode_lbl)

        self._group_mode = QButtonGroup(self)
        self._radio_managed = self._make_radio(self.tr("Default"), "managed")
        self._radio_managed.setToolTip(self.tr("FFmpeg gestionado y descargado automáticamente por DowP (Recomendado)"))
        self._radio_managed.setFixedWidth(125)
        self._radio_custom = self._make_radio(self.tr("Personalizado"), "custom")
        self._radio_custom.setToolTip(self.tr("Usar un ejecutable de FFmpeg existente en tu sistema (ruta local)"))
        self._radio_custom.setFixedWidth(125)
        self._group_mode.addButton(self._radio_managed, 0)
        self._group_mode.addButton(self._radio_custom, 1)
        self._group_mode.idClicked.connect(self._on_mode_changed)

        row_mode.addWidget(self._radio_managed)
        row_mode.addWidget(self._radio_custom)
        row_mode.addStretch()
        root.addLayout(row_mode)

        # ── Contenedor Modo Gestionado ─────────────────────────────────────────
        self._managed_box = QWidget()
        managed_layout = QVBoxLayout(self._managed_box)
        managed_layout.setContentsMargins(0, 2, 0, 0)
        managed_layout.setSpacing(8)

        # Fila 0: Variante
        row_variant = QHBoxLayout()
        row_variant.setContentsMargins(0, 0, 0, 0)
        row_variant.setSpacing(14)

        v_lbl = QLabel(self.tr("Compilación:"))
        v_lbl.setFixedWidth(80)
        v_lbl.setStyleSheet("color: #CCC; font-size: 12px;")
        row_variant.addWidget(v_lbl)

        self._group_variant = QButtonGroup(self)
        self._radio_essentials = self._make_radio(self.tr("Essentials"), "essentials")
        self._radio_essentials.setToolTip(self.tr("Variante ligera (~30 MB) con códecs y aceleración por hardware estándar"))
        self._radio_essentials.setFixedWidth(125)
        self._radio_full = self._make_radio(self.tr("Full"), "full")
        self._radio_full.setToolTip(self.tr("Variante completa con códecs extendidos (SVT-AV1, libvpx, libplacebo, filtros avanzados)"))
        self._radio_full.setFixedWidth(125)
        self._group_variant.addButton(self._radio_essentials, 0)
        self._group_variant.addButton(self._radio_full, 1)
        self._group_variant.idClicked.connect(self._on_variant_changed)

        row_variant.addWidget(self._radio_essentials)
        row_variant.addWidget(self._radio_full)
        row_variant.addStretch()
        managed_layout.addLayout(row_variant)

        # Fila 1: Canal / Versión
        row_channel = QHBoxLayout()
        row_channel.setContentsMargins(0, 0, 0, 0)
        row_channel.setSpacing(14)

        c_lbl = QLabel(self.tr("Canal:"))
        c_lbl.setFixedWidth(80)
        c_lbl.setStyleSheet("color: #CCC; font-size: 12px;")
        row_channel.addWidget(c_lbl)

        self._group_channel = QButtonGroup(self)
        self._radio_recommended = self._make_radio(self.tr("Recomendada"), "recommended")
        self._radio_recommended.setToolTip(self.tr("Versión base probada a fondo para máxima estabilidad ({0} Oficial DowP)").format(FFMPEG_RECOMMENDED_VERSION))
        self._radio_recommended.setFixedWidth(125)
        self._radio_latest = self._make_radio(self.tr("Última Release"), "latest")
        self._radio_latest.setToolTip(self.tr("Última versión estable oficial publicada por FFmpeg"))
        self._radio_latest.setFixedWidth(125)
        self._radio_nightly = self._make_radio(self.tr("Nightly"), "nightly")
        self._radio_nightly.setToolTip(self.tr("Compilaciones diarias con parches y novedades (Git Master)"))
        self._radio_nightly.setFixedWidth(125)
        self._group_channel.addButton(self._radio_recommended, 0)
        self._group_channel.addButton(self._radio_latest, 1)
        self._group_channel.addButton(self._radio_nightly, 2)
        self._group_channel.idClicked.connect(self._on_channel_changed)

        row_channel.addWidget(self._radio_recommended)
        row_channel.addWidget(self._radio_latest)
        row_channel.addWidget(self._radio_nightly)
        row_channel.addStretch()
        managed_layout.addLayout(row_channel)

        # Fila 2: Checkbox ffplay
        row_ffplay = QHBoxLayout()
        row_ffplay.setContentsMargins(0, 0, 0, 0)
        row_ffplay.setSpacing(14)

        ffplay_spacer = QLabel()
        ffplay_spacer.setFixedWidth(80)
        row_ffplay.addWidget(ffplay_spacer)

        self._chk_keep_ffplay = QCheckBox(self.tr("Conservar ffplay.exe"))
        self._chk_keep_ffplay.setToolTip(self.tr("Mantiene el reproductor multimedia ligero por terminal (~70 MB extra)"))
        self._chk_keep_ffplay.toggled.connect(self._on_keep_ffplay_toggled)
        row_ffplay.addWidget(self._chk_keep_ffplay)
        row_ffplay.addStretch()
        managed_layout.addLayout(row_ffplay)

        # Fila de acciones gestionado
        actions_row = QHBoxLayout()
        actions_row.addStretch()

        self._btn_restore = QPushButton(self.tr("Restaurar ({0} Essentials)").format(FFMPEG_RECOMMENDED_VERSION))
        self._btn_restore.setCursor(Qt.PointingHandCursor)
        set_button_variant(self._btn_restore, "accent-solid")
        self._btn_restore.setToolTip(self.tr("Descarga y restaura la versión base recomendada y probada de DowP ({0} Essentials)").format(FFMPEG_RECOMMENDED_VERSION))
        self._btn_restore.clicked.connect(self._on_restore_clicked)
        actions_row.addWidget(self._btn_restore)

        self._btn_download = QPushButton(self.tr("Descargar"))
        self._btn_download.setCursor(Qt.PointingHandCursor)
        set_button_variant(self._btn_download, "secondary")
        self._btn_download.setMinimumWidth(110)
        self._btn_download.clicked.connect(self._on_download_clicked)
        actions_row.addWidget(self._btn_download)

        managed_layout.addLayout(actions_row)
        root.addWidget(self._managed_box)

        # ── Contenedor Modo Personalizado ──────────────────────────────────────
        self._custom_box = QWidget()
        custom_layout = QVBoxLayout(self._custom_box)
        custom_layout.setContentsMargins(0, 2, 0, 0)
        custom_layout.setSpacing(6)

        c_path_lbl = QLabel(self.tr("Ruta al ejecutable ffmpeg.exe o carpeta contenedora:"))
        c_path_lbl.setStyleSheet("color: #CCC; font-size: 12px;")
        custom_layout.addWidget(c_path_lbl)

        custom_input_row = QHBoxLayout()
        self._custom_field = QLineEdit()
        self._custom_field.setPlaceholderText(self.tr("Ej: C:/ffmpeg/bin/ffmpeg.exe o C:/ffmpeg/bin"))
        self._custom_field.textChanged.connect(self._on_custom_path_changed)

        custom_browse_btn = QPushButton()
        custom_browse_btn.setFixedSize(32, 32)
        custom_browse_btn.setCursor(Qt.PointingHandCursor)
        apply_folder_browse_button_style(custom_browse_btn, self.tr("Examinar ejecutable de FFmpeg"))
        custom_browse_btn.clicked.connect(self._pick_custom_path)

        custom_input_row.addWidget(self._custom_field, 1)
        custom_input_row.addWidget(custom_browse_btn)
        custom_layout.addLayout(custom_input_row)

        self._custom_status_lbl = QLabel()
        self._custom_status_lbl.setStyleSheet("font-size: 11px;")
        custom_layout.addWidget(self._custom_status_lbl)

        root.addWidget(self._custom_box)

        # ── Barra de Progreso y Mensaje ────────────────────────────────────────
        self._progress_bar = QProgressBar()
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setFixedHeight(4)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.hide()
        root.addWidget(self._progress_bar)

        self._progress_msg = QLabel()
        self._progress_msg.setStyleSheet("color: #888888; font-size: 11px;")
        self._progress_msg.hide()
        root.addWidget(self._progress_msg)

    def _make_radio(self, text, code):
        rb = QRadioButton(text)
        rb.setProperty("code", code)
        return rb

    def _load_state(self):
        cfg = get_config()
        mode = cfg.get("ffmpeg_mode", "managed")
        variant = cfg.get("ffmpeg_variant", "essentials")
        channel = cfg.get("ffmpeg_channel", "recommended")
        keep_ffplay = cfg.get("ffmpeg_keep_ffplay", False)
        custom_path = cfg.get("ffmpeg_custom_path", "")

        # Modo
        if mode == "custom":
            self._radio_custom.setChecked(True)
        else:
            self._radio_managed.setChecked(True)

        # Variante
        if variant == "full":
            self._radio_full.setChecked(True)
        else:
            self._radio_essentials.setChecked(True)

        # Canal
        if channel == "latest":
            self._radio_latest.setChecked(True)
        elif channel == "nightly":
            self._radio_nightly.setChecked(True)
        else:
            self._radio_recommended.setChecked(True)

        # ffplay
        self._chk_keep_ffplay.blockSignals(True)
        self._chk_keep_ffplay.setChecked(keep_ffplay)
        self._chk_keep_ffplay.blockSignals(False)

        # custom path
        self._custom_field.blockSignals(True)
        self._custom_field.setText(custom_path)
        self._custom_field.blockSignals(False)

        self._update_visibility()
        self._refresh_status()

    def _update_visibility(self):
        is_custom = self._radio_custom.isChecked()
        self._managed_box.setVisible(not is_custom)
        self._custom_box.setVisible(is_custom)

    def _refresh_status(self):
        is_installed = check_ffmpeg()
        is_custom = self._radio_custom.isChecked()

        if is_custom:
            path = self._custom_field.text().strip()
            ok, ver, msg = validate_custom_ffmpeg(path)
            if ok:
                self._status_badge.setText(self.tr("✓ Instalado (Personalizado)"))
                self._status_badge.setStyleSheet("color: #4CAF50; font-size: 12px; font-weight: bold;")
                self._version_summary.setText(self.tr("Versión: {0}").format(ver))
                self._custom_status_lbl.setText(self.tr("✓ {0} (Versión: {1})").format(msg, ver))
                self._custom_status_lbl.setStyleSheet("color: #4CAF50; font-size: 11px;")
            else:
                self._status_badge.setText(self.tr("✗ Inválido"))
                self._status_badge.setStyleSheet("color: #F44336; font-size: 12px; font-weight: bold;")
                self._version_summary.setText(self.tr("No disponible"))
                self._custom_status_lbl.setText(f"⚠ {msg}")
                self._custom_status_lbl.setStyleSheet("color: #FFC107; font-size: 11px;")
        else:
            if is_installed:
                ver = ffmpeg_local() or "?"
                variant_tag = "Full" if "full" in ver.lower() else "Essentials"
                self._status_badge.setText(self.tr("✓ Instalado"))
                self._status_badge.setStyleSheet("color: #4CAF50; font-size: 12px; font-weight: bold;")
                self._version_summary.setText(self.tr("Versión: {0} ({1})").format(ver, variant_tag))
                self._btn_download.setText(self.tr("Reinstalar"))
                set_button_variant(self._btn_download, "secondary")
            else:
                self._status_badge.setText("✗ Falta")
                self._status_badge.setStyleSheet("color: #F44336; font-size: 12px; font-weight: bold;")
                self._version_summary.setText(self.tr("No instalado"))
                self._btn_download.setText(self.tr("Descargar"))
                set_button_variant(self._btn_download, "accent-blue")

            # Restaurar button state (habilita volver a Essentials recomendada si está en Full, Nightly o Custom)
            local_ver = ffmpeg_local() or ""
            if FFMPEG_RECOMMENDED_VERSION in local_ver and "essentials" in local_ver.lower():
                self._btn_restore.setDisabled(True)
                self._btn_restore.setText(self.tr("Recomendada Activa ({0})").format(FFMPEG_RECOMMENDED_VERSION))
                set_button_variant(self._btn_restore, "secondary")
            else:
                self._btn_restore.setDisabled(False)
                self._btn_restore.setText(self.tr("Restaurar ({0} Essentials)").format(FFMPEG_RECOMMENDED_VERSION))
                set_button_variant(self._btn_restore, "accent-solid")

    def _on_mode_changed(self, btn_id):
        mode = "custom" if btn_id == 1 else "managed"
        cfg = get_config()
        cfg["ffmpeg_mode"] = mode
        save_config(cfg)
        logger.info(f"FFmpeg: Origen cambiado a '{mode.upper()}' ({'Ruta Personalizada' if mode == 'custom' else 'Gestionado por DowP'})")
        self._update_visibility()
        self._refresh_status()
        self.ffmpeg_changed.emit()

    def _on_variant_changed(self, btn_id):
        variant = "full" if btn_id == 1 else "essentials"
        cfg = get_config()
        cfg["ffmpeg_variant"] = variant
        save_config(cfg)
        logger.info(f"FFmpeg: Variante cambiada a '{variant.upper()}' (Essentials / Full)")
        self._refresh_status()
        self.ffmpeg_changed.emit()

    def _on_channel_changed(self, btn_id):
        mapping = {0: "recommended", 1: "latest", 2: "nightly"}
        channel = mapping.get(btn_id, "recommended")
        cfg = get_config()
        cfg["ffmpeg_channel"] = channel
        save_config(cfg)
        logger.info(f"FFmpeg: Canal de versión cambiado a '{channel.upper()}' (Recomendada {FFMPEG_RECOMMENDED_VERSION} / Latest / Nightly)")
        self._refresh_status()
        self.ffmpeg_changed.emit()

    def _on_keep_ffplay_toggled(self, checked):
        cfg = get_config()
        cfg["ffmpeg_keep_ffplay"] = checked
        save_config(cfg)
        logger.info(f"FFmpeg: Opción 'Conservar ffplay.exe' actualizada a: {checked}")

    def _on_custom_path_changed(self, text):
        cfg = get_config()
        cfg["ffmpeg_custom_path"] = text.strip()
        save_config(cfg)
        ok, ver, msg = validate_custom_ffmpeg(text)
        if ok:
            logger.info(f"FFmpeg: Ruta personalizada configurada: '{text}' (Versión detectada: {ver})")
        elif text.strip():
            logger.warning(f"FFmpeg: Ruta personalizada no válida: '{text}' -> {msg}")
        self._refresh_status()
        self.ffmpeg_changed.emit()

    def _pick_custom_path(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Seleccionar ejecutable de FFmpeg"),
            "",
            self.tr("Ejecutables (*.exe);;Todos los archivos (*)") if platform.system() == "Windows"
            else self.tr("Todos los archivos (*)")
        )
        if path:
            self._custom_field.setText(path)

    def _on_restore_clicked(self):
        """Descarga e instala de inmediato la versión recomendada oficial 8.0.1 Essentials."""
        logger.info(f"FFmpeg: Restaurando versión recomendada oficial de DowP ({FFMPEG_RECOMMENDED_VERSION} Essentials)...")
        self._radio_essentials.setChecked(True)
        self._radio_recommended.setChecked(True)
        cfg = get_config()
        cfg["ffmpeg_variant"] = "essentials"
        cfg["ffmpeg_channel"] = "recommended"
        save_config(cfg)
        self._start_download(variant="essentials", channel="recommended", version=FFMPEG_RECOMMENDED_VERSION)

    def _on_download_clicked(self):
        cfg = get_config()
        variant = cfg.get("ffmpeg_variant", "essentials")
        channel = cfg.get("ffmpeg_channel", "recommended")
        self._start_download(variant=variant, channel=channel)

    def _start_download(self, variant, channel, version=None):
        logger.info(f"FFmpeg: Iniciando tarea de descarga [Variante: '{variant}', Canal: '{channel}', Versión objetivo: {version or 'Auto'}]")
        self._set_downloading_state(True)
        cfg = get_config()
        keep_ffplay = cfg.get("ffmpeg_keep_ffplay", False)

        self._download_worker = FFmpegDownloadWorker(
            variant=variant,
            channel=channel,
            keep_ffplay=keep_ffplay,
            version=version
        )
        self._download_worker.numeric_progress_signal.connect(self._progress_bar.setValue)
        self._download_worker.progress_signal.connect(self._progress_msg.setText)
        self._download_worker.finished_signal.connect(self._on_download_finished)
        self._download_worker.start()

    def _set_downloading_state(self, is_downloading, message="Iniciando..."):
        self._btn_download.setDisabled(is_downloading)
        self._btn_restore.setDisabled(is_downloading)

        if is_downloading:
            self._progress_bar.setRange(0, 100)
            self._progress_bar.setValue(0)
            self._progress_bar.show()
            self._progress_msg.setText(message)
            self._progress_msg.show()
            self._status_badge.setText(self.tr("Descargando..."))
            self._status_badge.setStyleSheet("color: #FFC107; font-size: 12px; font-weight: bold;")
        else:
            self._progress_bar.hide()
            self._progress_msg.hide()
            self._refresh_status()

    def _on_download_finished(self, success, msg):
        self._set_downloading_state(False)
        if success:
            active_ver = ffmpeg_local() or "OK"
            logger.info(f"FFmpeg: Descarga e instalación finalizadas con éxito. Versión activa actual: '{active_ver}'")
            self._refresh_status()
            self.ffmpeg_changed.emit()
            QMessageBox.information(self, self.tr("FFmpeg Configurado"), self.tr("FFmpeg se ha instalado y configurado correctamente."))
        else:
            logger.error(f"FFmpeg: Error durante el proceso de instalación/cambio de versión: {msg}")
            QMessageBox.warning(self, self.tr("Error de Descarga"), self.tr("No se pudo completar la instalación de FFmpeg:\n{0}").format(msg))

    def check_updates(self):
        """Comprueba si hay actualizaciones disponibles para el canal actual."""
        cfg = get_config()
        if cfg.get("ffmpeg_mode") == "custom":
            return

        channel = cfg.get("ffmpeg_channel", "recommended")
        variant = cfg.get("ffmpeg_variant", "essentials")
        
        class _RemoteCheckWorker(QThread):
            done = Signal(object)
            def run(self):
                try:
                    r_ver = ffmpeg_remote(channel=channel, variant=variant)
                except Exception:
                    r_ver = None
                self.done.emit(r_ver)

        self._check_worker = _RemoteCheckWorker()
        self._check_worker.done.connect(self._on_remote_check_done)
        self._check_worker.start()

    def _on_remote_check_done(self, remote_ver):
        if not remote_ver:
            return
        local_ver = ffmpeg_local() or ""
        r_ver = str(remote_ver).strip().lstrip('v')
        l_ver = str(local_ver).strip().lstrip('v')

        if r_ver != l_ver and r_ver not in l_ver:
            self._version_summary.setText(self.tr("Versión: {0} (Nueva: {1})").format(local_ver, remote_ver))
            self._version_summary.setStyleSheet("color: #FFC107; font-weight: bold; font-size: 12px;")
            self._btn_download.setText(self.tr("Actualizar"))
            set_button_variant(self._btn_download, "accent-blue")


# ═════════════════════════════════════════════════════════════════════════════
# TARJETA 2: YT-DLP Y PO TOKEN PROVIDER (Motor Principal + Plugins Anti-Bot)
# ═════════════════════════════════════════════════════════════════════════════

class WPCInstallWorker(QThread):
    """Hilo para instalar/actualizar yt-dlp-getpot-wpc via pip sin bloquear la UI."""
    finished_signal = Signal(bool, str)
    numeric_progress_signal = Signal(int)

    def run(self):
        def cb(pct):
            self.numeric_progress_signal.emit(pct)
        success, msg = install_wpc(progress_callback=cb)
        self.finished_signal.emit(success, msg)


class YTDLPAndPOTPanel(QFrame):
    """
    Tarjeta unificada que contiene a yt-dlp (motor principal) en la parte superior
    y a los PO Token Providers (plugins anti-bot) en la parte inferior.
    """
    ytdlp_download_requested = Signal(str, object)  # "ytdlp", channel
    provider_changed = Signal(str)

    _TOOLTIP_YTDLP = QCoreApplication.translate(
        "YTDLPAndPOTPanel",
        "yt-dlp es el motor central de DowP para la extracción de metadatos, análisis de formatos\n"
        "y descarga de transmisiones de video y audio desde YouTube y más de 1000 sitios soportados.\n\n"
        "  • Canal Estable: Compilación oficial probada y validada de yt-dlp.\n"
        "  • Canal Nightly: Compilación diaria automática con los últimos parches y correcciones anti-bot de YouTube."
    )

    _TOOLTIP_POT = QCoreApplication.translate(
        "YTDLPAndPOTPanel",
        "El PO Token es requerido por YouTube para autenticar descargas y prevenir bloqueos anti-bot.\n"
        "DowP permite elegir entre:\n\n"
        "  • bgutil-pot (Recomendado): Binario nativo en Rust, rápido y automático.\n"
        "  • WPC (WebPoClient): Usa tu navegador Chromium (Chrome/Brave/Edge) para generar tokens.\n"
        "  • Ninguno: Sin token (puede fallar con error HTTP 429 / bot-check en YouTube)."
    )

    _TOOLTIP_WPC_BROWSER = QCoreApplication.translate(
        "YTDLPAndPOTPanel",
        "WPC (WebPoClient) usa un navegador real basado en Chromium para generar\n"
        "los PO Tokens que YouTube requiere. Cualquier navegador Chromium funciona:\n\n"
        "  •  Google Chrome\n"
        "  •  Brave Browser\n"
        "  •  Microsoft Edge\n"
        "  •  Chromium\n\n"
        "Si dejas el campo vacío, WPC intentará detectar tu navegador automáticamente.\n"
        "Haz clic en '...' para seleccionar el ejecutable manualmente."
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ytdlpPotPanel")
        self.is_ytdlp_installed = False
        self.ytdlp_local_ver = None
        self._ytdlp_update_worker = None
        self._wpc_worker = None
        self._bgutil_worker = None
        self._build_ui()
        self._load_state()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        # ═════════════════════════════════════════════════════════════════════
        # SECCIÓN SUPERIOR: YT-DLP
        # ═════════════════════════════════════════════════════════════════════
        ytdlp_top_row = QHBoxLayout()
        ytdlp_top_row.setSpacing(8)

        ytdlp_title = QLabel(self.tr("yt-dlp (Motor Principal de Descargas)"))
        ytdlp_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #EEEEEE;")
        ytdlp_top_row.addWidget(ytdlp_title)

        ytdlp_info_btn = QToolButton()
        ytdlp_info_btn.setText("?")
        ytdlp_info_btn.setFixedSize(20, 20)
        ytdlp_info_btn.setStyleSheet(
            "QToolButton { border: 1px solid #555; border-radius: 10px;"
            " color: #AAA; font-size: 11px; background: #2a2a2a; }"
            " QToolButton:hover { background: #3a3a3a; color: #FFF; }"
        )
        ytdlp_info_btn.setToolTip(self._TOOLTIP_YTDLP)
        ytdlp_top_row.addWidget(ytdlp_info_btn)

        self._ytdlp_status_badge = QLabel(self.tr("Chequeando..."))
        self._ytdlp_status_badge.setStyleSheet("font-weight: bold; font-size: 12px;")
        ytdlp_top_row.addWidget(self._ytdlp_status_badge)

        ytdlp_top_row.addStretch()

        self._ytdlp_version_summary = QLabel(self.tr("Versión: Calculando..."))
        self._ytdlp_version_summary.setStyleSheet("color: #AAAAAA; font-size: 12px;")
        ytdlp_top_row.addWidget(self._ytdlp_version_summary)

        root.addLayout(ytdlp_top_row)

        # Selector de canal para yt-dlp
        row_ytdlp_channel = QHBoxLayout()
        row_ytdlp_channel.setContentsMargins(0, 0, 0, 0)
        row_ytdlp_channel.setSpacing(14)

        c_lbl = QLabel(self.tr("Canal:"))
        c_lbl.setFixedWidth(80)
        c_lbl.setStyleSheet("color: #CCC; font-size: 12px; font-weight: bold;")
        row_ytdlp_channel.addWidget(c_lbl)

        self._group_ytdlp_channel = QButtonGroup(self)
        self._radio_ytdlp_stable = self._make_radio(self.tr("Estable"), "stable")
        self._radio_ytdlp_stable.setToolTip(self.tr("Última Release oficial y probada"))
        self._radio_ytdlp_stable.setFixedWidth(125)
        self._radio_ytdlp_nightly = self._make_radio(self.tr("Nightly"), "nightly")
        self._radio_ytdlp_nightly.setToolTip(self.tr("Versión actualizada a diario con parches y nuevos extractores (Git / Recomendado)"))
        self._radio_ytdlp_nightly.setFixedWidth(125)
        self._group_ytdlp_channel.addButton(self._radio_ytdlp_stable, 0)
        self._group_ytdlp_channel.addButton(self._radio_ytdlp_nightly, 1)
        self._group_ytdlp_channel.idClicked.connect(self._on_ytdlp_channel_changed)

        row_ytdlp_channel.addWidget(self._radio_ytdlp_stable)
        row_ytdlp_channel.addWidget(self._radio_ytdlp_nightly)
        row_ytdlp_channel.addStretch()
        root.addLayout(row_ytdlp_channel)

        ytdlp_desc_row = QHBoxLayout()
        ytdlp_desc_row.setSpacing(12)

        ytdlp_desc = QLabel(self.tr(
            "El núcleo de descargas, maneja la extracción de datos de YouTube y otras plataformas."
        ))
        ytdlp_desc.setStyleSheet("color: #888888; font-size: 12px;")
        ytdlp_desc.setWordWrap(True)
        ytdlp_desc_row.addWidget(ytdlp_desc, 1)

        self._ytdlp_btn_action = QPushButton(self.tr("Descargar"))
        self._ytdlp_btn_action.setCursor(Qt.PointingHandCursor)
        set_button_variant(self._ytdlp_btn_action, "secondary")
        self._ytdlp_btn_action.setMinimumWidth(110)
        self._ytdlp_btn_action.clicked.connect(self._on_ytdlp_action_clicked)
        ytdlp_desc_row.addWidget(self._ytdlp_btn_action, 0, Qt.AlignVCenter)

        root.addLayout(ytdlp_desc_row)

        self._ytdlp_progress_bar = QProgressBar()
        self._ytdlp_progress_bar.setTextVisible(False)
        self._ytdlp_progress_bar.setFixedHeight(4)
        self._ytdlp_progress_bar.setRange(0, 100)
        self._ytdlp_progress_bar.hide()
        root.addWidget(self._ytdlp_progress_bar)

        self._ytdlp_progress_msg = QLabel("")
        self._ytdlp_progress_msg.setStyleSheet("color: #888888; font-size: 11px;")
        self._ytdlp_progress_msg.hide()
        root.addWidget(self._ytdlp_progress_msg)

        # Separador entre yt-dlp y PO Token Provider
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #333;")
        root.addWidget(sep)

        # ═════════════════════════════════════════════════════════════════════
        # SECCIÓN INFERIOR: PO TOKEN PROVIDER
        # ═════════════════════════════════════════════════════════════════════
        pot_title_row = QHBoxLayout()
        pot_title_row.setSpacing(8)

        pot_title = QLabel(self.tr("PO Token Provider (Bypass Anti-Bot YouTube)"))
        pot_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #DDDDDD;")
        pot_title_row.addWidget(pot_title)

        pot_info_btn = QToolButton()
        pot_info_btn.setText("?")
        pot_info_btn.setFixedSize(18, 18)
        pot_info_btn.setStyleSheet(
            "QToolButton { border: 1px solid #555; border-radius: 9px;"
            " color: #AAA; font-size: 10px; background: #2a2a2a; }"
            " QToolButton:hover { background: #3a3a3a; color: #FFF; }"
        )
        pot_info_btn.setToolTip(self._TOOLTIP_POT)
        pot_title_row.addWidget(pot_info_btn)
        pot_title_row.addStretch()
        root.addLayout(pot_title_row)

        self._btn_group = QButtonGroup(self)
        self._radio_bgutil = self._make_radio(self.tr("bgutil-pot (recomendado)"), "bgutil")
        self._radio_wpc    = self._make_radio(self.tr("WPC – WebPoClient"), "wpc")
        self._radio_none   = self._make_radio(self.tr("Ninguno"), "none")

        self._btn_group.addButton(self._radio_bgutil, 0)
        self._btn_group.addButton(self._radio_wpc,    1)
        self._btn_group.addButton(self._radio_none,   2)
        self._btn_group.idClicked.connect(self._on_radio_changed)

        # Fila bgutil
        row_bgutil = QHBoxLayout()
        row_bgutil.addWidget(self._radio_bgutil)
        self._bgutil_status = QLabel(self.tr("Chequeando..."))
        self._bgutil_status.setStyleSheet("color: #888; font-size: 11px;")
        row_bgutil.addWidget(self._bgutil_status)
        row_bgutil.addStretch()
        self._bgutil_btn = QPushButton(self.tr("Comprobando..."))
        self._bgutil_btn.setMinimumWidth(110)
        self._bgutil_btn.setCursor(Qt.PointingHandCursor)
        set_button_variant(self._bgutil_btn, "secondary")
        self._bgutil_btn.clicked.connect(self._on_bgutil_action)
        row_bgutil.addWidget(self._bgutil_btn)
        root.addLayout(row_bgutil)

        self._bgutil_progress = QProgressBar()
        self._bgutil_progress.setTextVisible(False)
        self._bgutil_progress.setFixedHeight(4)
        self._bgutil_progress.setRange(0, 100)
        self._bgutil_progress.hide()
        root.addWidget(self._bgutil_progress)

        # Fila WPC
        row_wpc = QHBoxLayout()
        row_wpc.addWidget(self._radio_wpc)
        self._wpc_status = QLabel(self.tr("Chequeando..."))
        self._wpc_status.setStyleSheet("color: #888; font-size: 11px;")
        row_wpc.addWidget(self._wpc_status)
        row_wpc.addStretch()
        self._wpc_btn = QPushButton(self.tr("Instalar"))
        self._wpc_btn.setMinimumWidth(110)
        self._wpc_btn.setCursor(Qt.PointingHandCursor)
        set_button_variant(self._wpc_btn, "secondary")
        self._wpc_btn.clicked.connect(self._on_wpc_action)
        row_wpc.addWidget(self._wpc_btn)
        root.addLayout(row_wpc)

        self._wpc_progress = QProgressBar()
        self._wpc_progress.setTextVisible(False)
        self._wpc_progress.setFixedHeight(4)
        self._wpc_progress.setRange(0, 100)
        self._wpc_progress.hide()
        root.addWidget(self._wpc_progress)

        # Fila Ninguno
        root.addWidget(self._radio_none)

        # Sub-fila Navegador WPC
        browser_label_row = QHBoxLayout()
        browser_lbl = QLabel(self.tr("Navegador para WPC:"))
        browser_lbl.setStyleSheet("color: #BBB; font-size: 12px;")
        browser_label_row.addWidget(browser_lbl)

        browser_help = QToolButton()
        browser_help.setText("?")
        browser_help.setFixedSize(18, 18)
        browser_help.setToolTip(self._TOOLTIP_WPC_BROWSER)
        browser_help.setStyleSheet(
            "QToolButton { border: 1px solid #555; border-radius: 9px;"
            " color: #AAA; font-size: 10px; background: #2a2a2a; }"
            " QToolButton:hover { background: #3a3a3a; color: #FFF; }"
        )
        browser_label_row.addWidget(browser_help)
        browser_label_row.addStretch()
        root.addLayout(browser_label_row)

        browser_path_row = QHBoxLayout()
        self._browser_field = QLineEdit()
        self._browser_field.setPlaceholderText(self.tr("Auto-detectado: deja vacío o elige un ejecutable"))
        self._browser_field.textChanged.connect(self._on_browser_path_changed)

        self._browser_detected_lbl = QLabel()
        self._browser_detected_lbl.setStyleSheet("color: #4CAF50; font-size: 11px;")

        browse_btn = QPushButton()
        browse_btn.setFixedSize(32, 32)
        browse_btn.setCursor(Qt.PointingHandCursor)
        apply_folder_browse_button_style(browse_btn, self.tr("Seleccionar ejecutable del navegador (chrome.exe, brave.exe, msedge.exe...)"))
        browse_btn.clicked.connect(self._pick_browser)

        browser_path_row.addWidget(self._browser_field, 1)
        browser_path_row.addWidget(browse_btn)
        root.addLayout(browser_path_row)
        root.addWidget(self._browser_detected_lbl)

    def _make_radio(self, text, provider_id):
        rb = QRadioButton(text)
        rb.setProperty("provider_id", provider_id)
        return rb

    def _load_state(self):
        self.check_ytdlp_status()
        
        cfg = get_config()
        channel = cfg.get("ytdlp_channel", "stable")
        if channel == "nightly":
            self._radio_ytdlp_nightly.setChecked(True)
        else:
            self._radio_ytdlp_stable.setChecked(True)

        provider = cfg.get("pot_provider", "bgutil")
        browser_path = cfg.get("pot_wpc_browser_path", "")

        if provider == "bgutil":
            self._radio_bgutil.setChecked(True)
        elif provider == "wpc":
            self._radio_wpc.setChecked(True)
        else:
            self._radio_none.setChecked(True)

        self._browser_field.blockSignals(True)
        self._browser_field.setText(browser_path)
        self._browser_field.blockSignals(False)
        self._update_detected_label()
        self._refresh_pot_status()

    # ── Métodos de yt-dlp ───────────────────────────────────────────────────
    def _on_ytdlp_channel_changed(self, btn_id):
        channel = "nightly" if btn_id == 1 else "stable"
        cfg = get_config()
        cfg["ytdlp_channel"] = channel
        save_config(cfg)
        logger.info(f"yt-dlp: Canal de versión cambiado a '{channel.upper()}'")
        
        self.set_ytdlp_searching_updates()
        self._ytdlp_update_worker = YTDLPUpdateCheckWorker(channel)
        self._ytdlp_update_worker.finished_signal.connect(self.set_ytdlp_update_available)
        self._ytdlp_update_worker.start()

    def check_ytdlp_status(self):
        self.is_ytdlp_installed = check_ytdlp()
        if self.is_ytdlp_installed:
            try:
                self.ytdlp_local_ver = ytdlp_local()
            except Exception:
                self.ytdlp_local_ver = None
        else:
            self.ytdlp_local_ver = None
        self._update_ytdlp_ui()

    def _update_ytdlp_ui(self):
        if self.is_ytdlp_installed:
            self._ytdlp_status_badge.setText(self.tr("✓ Instalado"))
            self._ytdlp_status_badge.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 12px;")
            v_text = self.tr("Versión: {0}").format(self.ytdlp_local_ver) if self.ytdlp_local_ver else self.tr("Versión: Desconocida")
            self._ytdlp_version_summary.setText(v_text)
            self._ytdlp_version_summary.setStyleSheet("color: #AAAAAA; font-size: 12px;")
            self._ytdlp_btn_action.setText(self.tr("Reinstalar"))
            self._ytdlp_btn_action.setDisabled(False)
            set_button_variant(self._ytdlp_btn_action, "secondary")
        else:
            self._ytdlp_status_badge.setText(self.tr("✗ Falta"))
            self._ytdlp_status_badge.setStyleSheet("color: #F44336; font-weight: bold; font-size: 12px;")
            self._ytdlp_version_summary.setText(self.tr("No instalado"))
            self._ytdlp_version_summary.setStyleSheet("color: #F44336; font-size: 12px;")
            self._ytdlp_btn_action.setText(self.tr("Descargar"))
            self._ytdlp_btn_action.setDisabled(False)
            set_button_variant(self._ytdlp_btn_action, "accent-blue")

    def set_ytdlp_searching_updates(self):
        if self.is_ytdlp_installed:
            self._ytdlp_version_summary.setText(self.tr("Versión: {0} (Buscando...)").format(self.ytdlp_local_ver))

    def set_ytdlp_update_available(self, remote_ver):
        if not self.is_ytdlp_installed:
            return
        if not remote_ver:
            self._ytdlp_version_summary.setText(self.tr("Versión: {0}").format(self.ytdlp_local_ver))
            self._ytdlp_version_summary.setStyleSheet("color: #AAAAAA; font-size: 12px;")
            return

        r_ver = str(remote_ver).strip().lstrip('v')
        l_ver = str(self.ytdlp_local_ver).strip().lstrip('v') if self.ytdlp_local_ver else ""
        
        cfg = get_config()
        channel = cfg.get("ytdlp_channel", "stable")

        if r_ver != l_ver and r_ver not in l_ver:
            self._ytdlp_version_summary.setText(self.tr("Versión: {0} (Nueva: {1})").format(self.ytdlp_local_ver, remote_ver))
            self._ytdlp_version_summary.setStyleSheet("color: #FFC107; font-weight: bold; font-size: 12px;")
            
            # Texto descriptivo según el canal
            if channel == "nightly" and len(l_ver.split('.')) < 4:
                btn_text = self.tr("Cambiar a Nightly")
            elif channel == "stable" and len(l_ver.split('.')) >= 4:
                btn_text = self.tr("Cambiar a Estable")
            else:
                btn_text = self.tr("Actualizar")

            self._ytdlp_btn_action.setText(btn_text)
            self._ytdlp_btn_action.setDisabled(False)
            set_button_variant(self._ytdlp_btn_action, "accent-blue")
        else:
            self._ytdlp_version_summary.setText(self.tr("Versión: {0}").format(self.ytdlp_local_ver))
            self._ytdlp_version_summary.setStyleSheet("color: #AAAAAA; font-size: 12px;")
            self._ytdlp_btn_action.setText(self.tr("Reinstalar"))
            self._ytdlp_btn_action.setDisabled(False)
            set_button_variant(self._ytdlp_btn_action, "secondary")

    def _on_ytdlp_action_clicked(self):
        cfg = get_config()
        channel = cfg.get("ytdlp_channel", "stable")
        self.set_ytdlp_downloading_state(True, message=self.tr("Descargando yt-dlp ({0})...").format(channel.upper()))
        self.ytdlp_download_requested.emit("ytdlp", channel)

    def set_ytdlp_downloading_state(self, is_downloading, message=""):
        self._ytdlp_btn_action.setDisabled(is_downloading)
        if is_downloading:
            self._ytdlp_progress_bar.setRange(0, 0)
            self._ytdlp_progress_bar.setValue(0)
            self._ytdlp_progress_bar.show()
            self._ytdlp_progress_msg.setText(message if message else self.tr("Iniciando..."))
            self._ytdlp_progress_msg.show()
            self._ytdlp_status_badge.setText(self.tr("Procesando"))
            self._ytdlp_status_badge.setStyleSheet("color: #FFC107; font-weight: bold; font-size: 12px;")
        else:
            self._ytdlp_progress_bar.hide()
            self._ytdlp_progress_msg.hide()
            set_button_variant(self._ytdlp_btn_action, "secondary")
            self.check_ytdlp_status()

    def update_ytdlp_progress_msg(self, msg):
        self._ytdlp_progress_msg.setText(msg)

    def update_ytdlp_numeric_progress(self, value):
        if self._ytdlp_progress_bar.minimum() == 0 and self._ytdlp_progress_bar.maximum() == 0:
            self._ytdlp_progress_bar.setRange(0, 100)
        self._ytdlp_progress_bar.setValue(value)

    # ── Métodos de PO Token Provider ────────────────────────────────────────
    def _refresh_pot_status(self):
        # bgutil
        if check_potprovider():
            ver = potprovider_local() or "?"
            self._bgutil_status.setText(f"✓ Instalado  v{ver}")
            self._bgutil_status.setStyleSheet("color: #4CAF50; font-size: 11px;")
            self._bgutil_btn.setText(self.tr("Reinstalar"))
            self._bgutil_btn.setDisabled(False)
            set_button_variant(self._bgutil_btn, "secondary")
            self._bgutil_btn.setVisible(True)
        else:
            self._bgutil_status.setText(self.tr("✗ No instalado"))
            self._bgutil_status.setStyleSheet("color: #F44336; font-size: 11px;")
            self._bgutil_btn.setText(self.tr("Instalar"))
            self._bgutil_btn.setDisabled(False)
            set_button_variant(self._bgutil_btn, "accent-blue")
            self._bgutil_btn.setVisible(True)

        # WPC
        wpc_local(force_check=True)
        if check_wpc():
            ver = wpc_local() or "?"
            self._wpc_status.setText(f"✓ Instalado  v{ver}")
            self._wpc_status.setStyleSheet("color: #4CAF50; font-size: 11px;")
            self._wpc_btn.setText(self.tr("Reinstalar"))
            self._wpc_btn.setDisabled(False)
            set_button_variant(self._wpc_btn, "secondary")
        else:
            self._wpc_status.setText(self.tr("✗ No instalado"))
            self._wpc_status.setStyleSheet("color: #F44336; font-size: 11px;")
            self._wpc_btn.setText(self.tr("Instalar"))
            self._wpc_btn.setDisabled(False)
            set_button_variant(self._wpc_btn, "accent-blue")

    def _update_detected_label(self):
        configured = self._browser_field.text().strip()
        if configured and os.path.isfile(configured):
            self._browser_detected_lbl.setText(self.tr("✓ Ruta configurada: {0}").format(os.path.basename(configured)))
        else:
            name = get_browser_display_name()
            if name and name != "No detectado":
                self._browser_detected_lbl.setText(self.tr("Auto-detectado: {0}").format(name))
                self._browser_detected_lbl.setStyleSheet("color: #4CAF50; font-size: 11px;")
            else:
                self._browser_detected_lbl.setText(
                    self.tr("⚠ No se detectó ningún navegador Chromium (Chrome, Brave, Edge...)")
                )
                self._browser_detected_lbl.setStyleSheet("color: #FFC107; font-size: 11px;")

    def _on_radio_changed(self, btn_id):
        mapping = {0: "bgutil", 1: "wpc", 2: "none"}
        provider = mapping.get(btn_id, "bgutil")
        cfg = get_config()
        cfg["pot_provider"] = provider
        save_config(cfg)
        logger.info(f"POT Provider cambiado a: {provider}")
        self.provider_changed.emit(provider)

    def _on_browser_path_changed(self, text):
        cfg = get_config()
        cfg["pot_wpc_browser_path"] = text.strip()
        save_config(cfg)
        self._update_detected_label()

    def _pick_browser(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Seleccionar ejecutable del navegador"),
            "",
            self.tr("Ejecutables (*.exe);;Todos los archivos (*)") if platform.system() == "Windows"
            else self.tr("Todos los archivos (*)")
        )
        if path:
            self._browser_field.setText(path)

    def set_bgutil_update_available(self, remote_ver):
        if not check_potprovider():
            return

        local_ver = potprovider_local() or ""
        if not remote_ver:
            return

        r_ver = str(remote_ver).strip().lstrip('v')
        l_ver = str(local_ver).strip().lstrip('v')

        if r_ver != l_ver and r_ver not in l_ver:
            self._bgutil_status.setText(self.tr("✓ Instalado  v{0} (Nueva: {1})").format(local_ver, remote_ver))
            self._bgutil_status.setStyleSheet("color: #FFC107; font-weight: bold; font-size: 11px;")
            self._bgutil_btn.setText(self.tr("Actualizar"))
            self._bgutil_btn.setDisabled(False)
            set_button_variant(self._bgutil_btn, "accent-blue")
        else:
            self._bgutil_status.setText(f"✓ Instalado  v{local_ver}")
            self._bgutil_status.setStyleSheet("color: #4CAF50; font-size: 11px;")
            self._bgutil_btn.setText(self.tr("Reinstalar"))
            self._bgutil_btn.setDisabled(False)
            set_button_variant(self._bgutil_btn, "secondary")

    def _on_bgutil_action(self):
        self._bgutil_btn.setDisabled(True)
        self._bgutil_btn.setText(self.tr("Instalando..."))
        self._bgutil_progress.setValue(0)
        self._bgutil_progress.show()

        class _BGWorker(QThread):
            done = Signal(bool, str)
            numeric_progress = Signal(int)
            def run(self):
                def cb(pct):
                    self.numeric_progress.emit(pct)
                ok, msg = download_potprovider(progress_callback=cb)
                self.done.emit(ok, msg)

        self._bgutil_worker = _BGWorker()
        self._bgutil_worker.numeric_progress.connect(self._bgutil_progress.setValue)
        self._bgutil_worker.done.connect(self._on_bgutil_done)
        self._bgutil_worker.start()

    def _on_bgutil_done(self, ok, msg):
        self._bgutil_progress.hide()
        self._bgutil_btn.setDisabled(False)
        self._refresh_pot_status()
        if not ok:
            QMessageBox.warning(self, self.tr("Error"), self.tr("No se pudo descargar bgutil-pot:\n{0}").format(msg))

    def set_wpc_update_available(self, remote_ver):
        if not check_wpc():
            return

        local_ver = wpc_local() or ""
        if not remote_ver:
            return

        r_ver = str(remote_ver).strip().lstrip('v')
        l_ver = str(local_ver).strip().lstrip('v')

        if r_ver != l_ver and r_ver not in l_ver:
            self._wpc_status.setText(self.tr("✓ Instalado  v{0} (Nueva: {1})").format(local_ver, remote_ver))
            self._wpc_status.setStyleSheet("color: #FFC107; font-weight: bold; font-size: 11px;")
            self._wpc_btn.setText(self.tr("Actualizar"))
            self._wpc_btn.setDisabled(False)
            set_button_variant(self._wpc_btn, "accent-blue")
        else:
            self._wpc_status.setText(f"✓ Instalado  v{local_ver}")
            self._wpc_status.setStyleSheet("color: #4CAF50; font-size: 11px;")
            self._wpc_btn.setText(self.tr("Reinstalar"))
            self._wpc_btn.setDisabled(False)
            set_button_variant(self._wpc_btn, "secondary")

    def _on_wpc_action(self):
        self._wpc_btn.setDisabled(True)
        self._wpc_btn.setText(self.tr("Instalando..."))
        self._wpc_progress.setValue(0)
        self._wpc_progress.show()

        self._wpc_worker = WPCInstallWorker()
        self._wpc_worker.numeric_progress_signal.connect(self._wpc_progress.setValue)
        self._wpc_worker.finished_signal.connect(self._on_wpc_done)
        self._wpc_worker.start()

    def _on_wpc_done(self, ok, msg):
        self._wpc_progress.hide()
        self._wpc_btn.setDisabled(False)
        self._refresh_pot_status()
        if not ok:
            QMessageBox.warning(self, self.tr("Error instalando WPC"), msg)
        else:
            QMessageBox.information(self, self.tr("WPC instalado"), msg)


# ═════════════════════════════════════════════════════════════════════════════
# TARJETA 3: DENO CARD PANEL (JavaScript Runtime para YouTube Challenges)
# ═════════════════════════════════════════════════════════════════════════════

class DenoCardPanel(QFrame):
    """Tarjeta dedicada para el entorno de ejecución Deno."""
    download_requested = Signal(str, object)  # "deno", version

    _TOOLTIP_DENO = QCoreApplication.translate(
        "DenoCardPanel",
        "Deno es un entorno de ejecución de JavaScript de alto rendimiento y seguro.\n"
        "yt-dlp lo utiliza para interpretar y resolver los challenges criptográficos (EJS)\n"
        "que YouTube aplica dinámicamente en sus transmisiones."
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("denoCardPanel")
        self.dep_id = "deno"
        self.is_installed = False
        self.local_ver = None
        self._build_ui()
        self.check_status()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        # ── Título y Estado ──────────────────────────────────────────────────
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        title_lbl = QLabel(self.tr("Deno (Runtime JavaScript)"))
        title_lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #EEEEEE;")
        top_row.addWidget(title_lbl)

        info_btn = QToolButton()
        info_btn.setText("?")
        info_btn.setFixedSize(20, 20)
        info_btn.setStyleSheet(
            "QToolButton { border: 1px solid #555; border-radius: 10px;"
            " color: #AAA; font-size: 11px; background: #2a2a2a; }"
            " QToolButton:hover { background: #3a3a3a; color: #FFF; }"
        )
        info_btn.setToolTip(self._TOOLTIP_DENO)
        top_row.addWidget(info_btn)

        self._status_badge = QLabel(self.tr("Chequeando..."))
        self._status_badge.setStyleSheet("font-weight: bold; font-size: 12px;")
        top_row.addWidget(self._status_badge)

        top_row.addStretch()

        self._version_summary = QLabel(self.tr("Versión: Calculando..."))
        self._version_summary.setStyleSheet("color: #AAAAAA; font-size: 12px;")
        top_row.addWidget(self._version_summary)

        root.addLayout(top_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #333;")
        root.addWidget(sep)

        # ── Descripción y Botón de Acción ────────────────────────────────────
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(12)

        desc_lbl = QLabel(self.tr(
            "Entorno de ejecución de JavaScript. Necesario por yt-dlp para resolver los challenges de YouTube (EJS)."
        ))
        desc_lbl.setStyleSheet("color: #888888; font-size: 12px;")
        desc_lbl.setWordWrap(True)
        bottom_row.addWidget(desc_lbl, 1)

        self._btn_action = QPushButton(self.tr("Descargar"))
        self._btn_action.setCursor(Qt.PointingHandCursor)
        set_button_variant(self._btn_action, "secondary")
        self._btn_action.setMinimumWidth(110)
        self._btn_action.clicked.connect(self._on_action_clicked)
        bottom_row.addWidget(self._btn_action, 0, Qt.AlignVCenter)

        root.addLayout(bottom_row)

        # ── Barra de Progreso y Mensaje ───────────────────────────────────────
        self._progress_bar = QProgressBar()
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setFixedHeight(4)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.hide()
        root.addWidget(self._progress_bar)

        self._progress_msg = QLabel("")
        self._progress_msg.setStyleSheet("color: #888888; font-size: 11px;")
        self._progress_msg.hide()
        root.addWidget(self._progress_msg)

    def check_status(self):
        self.is_installed = check_deno()
        if self.is_installed:
            try:
                self.local_ver = deno_local()
            except Exception:
                self.local_ver = None
        else:
            self.local_ver = None
        self._update_ui_state()

    def _update_ui_state(self):
        if self.is_installed:
            self._status_badge.setText(self.tr("✓ Instalado"))
            self._status_badge.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 12px;")
            v_text = self.tr("Versión: {0}").format(self.local_ver) if self.local_ver else self.tr("Versión: Desconocida")
            self._version_summary.setText(v_text)
            self._version_summary.setStyleSheet("color: #AAAAAA; font-size: 12px;")
            self._btn_action.setText(self.tr("Reinstalar"))
            self._btn_action.setDisabled(False)
            set_button_variant(self._btn_action, "secondary")
        else:
            self._status_badge.setText(self.tr("✗ Falta"))
            self._status_badge.setStyleSheet("color: #F44336; font-weight: bold; font-size: 12px;")
            self._version_summary.setText(self.tr("No instalado"))
            self._version_summary.setStyleSheet("color: #F44336; font-size: 12px;")
            self._btn_action.setText(self.tr("Descargar"))
            self._btn_action.setDisabled(False)
            set_button_variant(self._btn_action, "accent-blue")

    def set_searching_updates(self):
        if self.is_installed:
            self._version_summary.setText(self.tr("Versión: {0} (Buscando...)").format(self.local_ver))

    def set_update_available(self, remote_ver):
        if not self.is_installed:
            return
        if not remote_ver:
            self._version_summary.setText(self.tr("Versión: {0}").format(self.local_ver))
            self._version_summary.setStyleSheet("color: #AAAAAA; font-size: 12px;")
            return
        r_ver = str(remote_ver).strip().lstrip('v')
        l_ver = str(self.local_ver).strip().lstrip('v')
        if r_ver != l_ver and r_ver not in l_ver:
            self._version_summary.setText(self.tr("Versión: {0} (Nueva: {1})").format(self.local_ver, remote_ver))
            self._version_summary.setStyleSheet("color: #FFC107; font-weight: bold; font-size: 12px;")
            self._btn_action.setText(self.tr("Actualizar"))
            self._btn_action.setDisabled(False)
            set_button_variant(self._btn_action, "accent-blue")
        else:
            self._version_summary.setText(self.tr("Versión: {0}").format(self.local_ver))
            self._version_summary.setStyleSheet("color: #AAAAAA; font-size: 12px;")
            self._btn_action.setText(self.tr("Reinstalar"))
            self._btn_action.setDisabled(False)
            set_button_variant(self._btn_action, "secondary")

    def _on_action_clicked(self):
        version = "latest" if self._btn_action.text() == self.tr("Actualizar") else None
        self.set_downloading_state(True)
        self.download_requested.emit(self.dep_id, version)

    def set_downloading_state(self, is_downloading, message=""):
        self._btn_action.setDisabled(is_downloading)
        if is_downloading:
            self._progress_bar.setRange(0, 0)
            self._progress_bar.setValue(0)
            self._progress_bar.show()
            self._progress_msg.setText(message if message else self.tr("Iniciando..."))
            self._progress_msg.show()
            self._status_badge.setText(self.tr("Procesando"))
            self._status_badge.setStyleSheet("color: #FFC107; font-weight: bold; font-size: 12px;")
        else:
            self._progress_bar.hide()
            self._progress_msg.hide()
            set_button_variant(self._btn_action, "secondary")
            self.check_status()

    def update_progress_msg(self, msg):
        self._progress_msg.setText(msg)

    def update_numeric_progress(self, value):
        if self._progress_bar.minimum() == 0 and self._progress_bar.maximum() == 0:
            self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(value)


# ═════════════════════════════════════════════════════════════════════════════
# TARJETA 4: GHOSTSCRIPT (EPS/PS del Editor de Imagen -- opcional)
# ═════════════════════════════════════════════════════════════════════════════

class GhostscriptCardPanel(QFrame):
    """Tarjeta dedicada a Ghostscript -- a diferencia de FFmpeg/yt-dlp/Deno (que
    la app necesita siempre), esta es 100% opcional: solo hace falta si el
    usuario quiere convertir archivos EPS/PS en el Editor de Imagen, y nunca se
    descarga sola (ni aquí ni al intentar convertir uno, ver
    ImageToolsTab._confirm_ghostscript_if_needed, que siempre pregunta antes).

    En Windows, DowP descarga y gestiona el binario (ver _windows_box / botón
    Descargar-Reinstalar). En Mac/Linux no hay build bundleable -- la tarjeta
    detecta un `gs` ya instalado por el usuario y le sugiere el comando de su
    gestor de paquetes (ver _system_box / ghostscript_setup.get_install_info),
    con un botón para copiarlo y otro para re-verificar tras instalarlo a mano."""
    download_requested = Signal(str, object)  # "ghostscript", None

    _TOOLTIP_GS = QCoreApplication.translate(
        "GhostscriptCardPanel",
        "Ghostscript es el intérprete de PostScript que permite convertir archivos\n"
        "EPS/PS en el Editor de Imagen -- ningún formato más de DowP lo necesita.\n\n"
        "Es opcional: si no lo instalas, todo lo demás sigue funcionando igual,\n"
        "y al intentar convertir un EPS/PS se te va a avisar cómo instalarlo.\n\n"
        "En Windows, DowP lo descarga y gestiona automáticamente. En Mac/Linux no hay\n"
        "build oficial para empaquetar: se detecta un Ghostscript ya instalado por ti\n"
        "(vía Homebrew en macOS, o el gestor de paquetes de tu distro en Linux)."
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ghostscriptCardPanel")
        self.setProperty("variant", "card")
        self.dep_id = "ghostscript"
        self.is_installed = False
        self.local_ver = None
        self._is_windows = platform.system() == "Windows"
        self._pkg_label = ""
        self._install_cmd = ""
        self._build_ui()
        self.check_status()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        title_lbl = QLabel(self.tr("Ghostscript (EPS/PS del Editor de Imagen)"))
        title_lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #EEEEEE;")
        top_row.addWidget(title_lbl)

        info_btn = QToolButton()
        info_btn.setText("?")
        info_btn.setFixedSize(20, 20)
        info_btn.setStyleSheet(
            "QToolButton { border: 1px solid #555; border-radius: 10px;"
            " color: #AAA; font-size: 11px; background: #2a2a2a; }"
            " QToolButton:hover { background: #3a3a3a; color: #FFF; }"
        )
        info_btn.setToolTip(self._TOOLTIP_GS)
        top_row.addWidget(info_btn)

        self._status_badge = QLabel(self.tr("Chequeando..."))
        self._status_badge.setStyleSheet("font-weight: bold; font-size: 12px;")
        top_row.addWidget(self._status_badge)

        top_row.addStretch()

        self._version_summary = QLabel(self.tr("Versión: Calculando..."))
        self._version_summary.setStyleSheet("color: #AAAAAA; font-size: 12px;")
        top_row.addWidget(self._version_summary)

        root.addLayout(top_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #333;")
        root.addWidget(sep)

        # ── Rama Windows: descarga gestionada por DowP ──────────────────────────
        self._windows_box = QWidget()
        windows_layout = QHBoxLayout(self._windows_box)
        windows_layout.setContentsMargins(0, 0, 0, 0)
        windows_layout.setSpacing(12)

        desc_lbl = QLabel(self.tr(
            "Opcional -- solo hace falta para convertir archivos EPS/PS. El resto del Editor de Imagen no lo necesita."
        ))
        desc_lbl.setStyleSheet("color: #888888; font-size: 12px;")
        desc_lbl.setWordWrap(True)
        windows_layout.addWidget(desc_lbl, 1)

        self._btn_action = QPushButton(self.tr("Descargar"))
        self._btn_action.setCursor(Qt.PointingHandCursor)
        set_button_variant(self._btn_action, "secondary")
        self._btn_action.setMinimumWidth(110)
        self._btn_action.clicked.connect(self._on_action_clicked)
        windows_layout.addWidget(self._btn_action, 0, Qt.AlignVCenter)

        root.addWidget(self._windows_box)

        # ── Rama Mac/Linux: no hay build bundleable, se detecta un `gs` ya ──────
        # instalado por el usuario y se sugiere el comando de su gestor de
        # paquetes (Homebrew en macOS, apt/dnf/pacman/zypper detectado en Linux).
        self._system_box = QWidget()
        system_layout = QVBoxLayout(self._system_box)
        system_layout.setContentsMargins(0, 0, 0, 0)
        system_layout.setSpacing(6)

        system_desc_lbl = QLabel(self.tr(
            "Opcional -- solo hace falta para convertir archivos EPS/PS. DowP no lo empaqueta "
            "en este sistema operativo: instálalo desde tu terminal con el comando de abajo y "
            "después presiona \"Verificar\"."
        ))
        system_desc_lbl.setStyleSheet("color: #888888; font-size: 12px;")
        system_desc_lbl.setWordWrap(True)
        system_layout.addWidget(system_desc_lbl)

        command_row = QHBoxLayout()
        command_row.setSpacing(8)

        self._command_field = QLineEdit()
        self._command_field.setReadOnly(True)
        self._command_field.setCursorPosition(0)
        self._command_field.setStyleSheet(
            "QLineEdit { background: #1e1e1e; color: #DDD; border: 1px solid #444;"
            " border-radius: 4px; padding: 4px 8px; font-family: Consolas, monospace; }"
        )
        command_row.addWidget(self._command_field, 1)

        self._btn_copy = QPushButton(self.tr("Copiar"))
        self._btn_copy.setCursor(Qt.PointingHandCursor)
        set_button_variant(self._btn_copy, "secondary")
        self._btn_copy.setFixedWidth(90)
        self._btn_copy.setToolTip(self.tr("Copiar el comando al portapapeles"))
        self._btn_copy.clicked.connect(self._on_copy_command_clicked)
        command_row.addWidget(self._btn_copy)

        self._btn_verify = QPushButton(self.tr("Verificar"))
        self._btn_verify.setCursor(Qt.PointingHandCursor)
        set_button_variant(self._btn_verify, "secondary")
        self._btn_verify.setFixedWidth(90)
        self._btn_verify.setToolTip(self.tr("Volver a comprobar si Ghostscript ya está instalado"))
        self._btn_verify.clicked.connect(self._on_verify_clicked)
        command_row.addWidget(self._btn_verify)

        system_layout.addLayout(command_row)

        self._system_hint_lbl = QLabel("")
        self._system_hint_lbl.setStyleSheet("font-size: 11px;")
        self._system_hint_lbl.setWordWrap(True)
        system_layout.addWidget(self._system_hint_lbl)

        root.addWidget(self._system_box)

        self._progress_bar = QProgressBar()
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setFixedHeight(4)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.hide()
        root.addWidget(self._progress_bar)

        self._progress_msg = QLabel("")
        self._progress_msg.setStyleSheet("color: #888888; font-size: 11px;")
        self._progress_msg.hide()
        root.addWidget(self._progress_msg)

    def check_status(self):
        self.is_installed = check_ghostscript()
        self.local_ver = gs_local() if self.is_installed else None
        if not self._is_windows:
            self._pkg_label, self._install_cmd = gs_install_info()
        self._update_ui_state()

    def _update_ui_state(self):
        self._windows_box.setVisible(self._is_windows)
        self._system_box.setVisible(not self._is_windows)

        if not self._is_windows:
            self._command_field.setText(self._install_cmd)
            self._command_field.setCursorPosition(0)
            if self.is_installed:
                self._status_badge.setText(self.tr("✓ Instalado (Sistema)"))
                self._status_badge.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 12px;")
                ver_text = self.tr("Versión: {0}").format(self.local_ver) if self.local_ver else self.tr("Versión: Desconocida")
                self._version_summary.setText(ver_text)
                self._version_summary.setStyleSheet("color: #AAAAAA; font-size: 12px;")
                self._system_hint_lbl.setText(self.tr(
                    "Detectado en el sistema -- DowP no lo gestiona aquí, actualízalo con {0} cuando quieras."
                ).format(self._pkg_label))
                self._system_hint_lbl.setStyleSheet("color: #4CAF50; font-size: 11px;")
            else:
                self._status_badge.setText(self.tr("✗ Falta"))
                self._status_badge.setStyleSheet("color: #F44336; font-weight: bold; font-size: 12px;")
                self._version_summary.setText(self.tr("No instalado"))
                self._version_summary.setStyleSheet("color: #F44336; font-size: 12px;")
                self._system_hint_lbl.setText(self.tr(
                    "No se detectó Ghostscript vía {0}. Copia el comando, ejecútalo en tu terminal "
                    "y después presiona \"Verificar\"."
                ).format(self._pkg_label))
                self._system_hint_lbl.setStyleSheet("color: #FFC107; font-size: 11px;")
            return

        if self.is_installed:
            self._status_badge.setText(self.tr("✓ Instalado"))
            self._status_badge.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 12px;")
            # Mismo resguardo que la rama de Mac/Linux: la version se lee del binario
            # (`gs --version`), asi que puede no llegar, y "Versión: None" no informa
            # de nada.
            self._version_summary.setText(
                self.tr("Versión: {0}").format(self.local_ver) if self.local_ver else self.tr("Versión: Desconocida"))
            self._version_summary.setStyleSheet("color: #AAAAAA; font-size: 12px;")
            self._btn_action.setText(self.tr("Reinstalar"))
            self._btn_action.setDisabled(False)
            set_button_variant(self._btn_action, "secondary")
        else:
            self._status_badge.setText(self.tr("✗ Falta"))
            self._status_badge.setStyleSheet("color: #F44336; font-weight: bold; font-size: 12px;")
            self._version_summary.setText(self.tr("No instalado"))
            self._version_summary.setStyleSheet("color: #F44336; font-size: 12px;")
            self._btn_action.setText(self.tr("Descargar"))
            self._btn_action.setDisabled(False)
            set_button_variant(self._btn_action, "accent-blue")

    def set_searching_updates(self):
        """Solo tiene efecto en Windows. En Mac/Linux el binario lo instala y
        actualiza el gestor de paquetes del sistema, no DowP, asi que no hay ninguna
        actualizacion que buscar aqui: la tarjeta ya remite al comando del gestor."""
        if self._is_windows and self.is_installed:
            self._version_summary.setText(self.tr("Versión: {0} (Buscando...)").format(self.local_ver))

    def set_update_available(self, remote_ver):
        """Resultado del chequeo. `remote_ver` a None significa que la consulta no
        se pudo hacer (sin conexion, o GitHub sin responder); en ese caso se deja la
        version instalada tal cual, sin afirmar que esta al dia."""
        if not self._is_windows or not self.is_installed:
            return

        # Comparacion exacta de cadenas: los dos lados vienen ya normalizados como
        # "10.07.1" -- uno de `gs --version` y el otro del nombre del release -- a
        # diferencia de yt-dlp o Deno, donde hace falta limpiar prefijos.
        # Con remote_ver o local_ver a None no se sabe nada, y eso NO es lo mismo que
        # estar al dia: se vuelve al estado neutro, boton incluido. Dejar solo la
        # etiqueta en neutro y el boton en "Actualizar" de un chequeo anterior
        # ofreceria una actualizacion que ya no se esta anunciando en ningun lado.
        has_update = bool(remote_ver and self.local_ver
                          and str(remote_ver).strip() != str(self.local_ver).strip())

        if has_update:
            self._version_summary.setText(self.tr("Versión: {0} (Nueva: {1})").format(self.local_ver, remote_ver))
            self._version_summary.setStyleSheet("color: #FFC107; font-weight: bold; font-size: 12px;")
            self._btn_action.setText(self.tr("Actualizar"))
            self._btn_action.setStyleSheet(
                "background-color: #007BFF; color: white; border: none; font-weight: bold;")
        else:
            self._version_summary.setText(
                self.tr("Versión: {0}").format(self.local_ver) if self.local_ver else self.tr("Versión: Desconocida"))
            self._version_summary.setStyleSheet("color: #AAAAAA; font-size: 12px;")
            # Se mantiene "Reinstalar" habilitado, a diferencia del resto de las
            # tarjetas, que pasan a un "Actualizado" desactivado: reinstalar es la
            # forma de reparar una extraccion a medias y esta tarjeta la ofrece
            # siempre, este o no al dia.
            self._btn_action.setText(self.tr("Reinstalar"))
            set_button_variant(self._btn_action, "secondary")
        self._btn_action.setDisabled(False)

    def _on_action_clicked(self):
        self.set_downloading_state(True)
        self.download_requested.emit(self.dep_id, None)

    def _on_copy_command_clicked(self):
        QApplication.clipboard().setText(self._install_cmd)
        self._btn_copy.setText(self.tr("¡Copiado!"))
        QTimer.singleShot(1500, lambda: self._btn_copy.setText(self.tr("Copiar")))

    def _on_verify_clicked(self):
        was_installed = self.is_installed
        self.check_status()
        if self.is_installed:
            if not was_installed:
                QMessageBox.information(
                    self, self.tr("Ghostscript detectado"),
                    self.tr("Ghostscript {0} detectado correctamente. Ya puedes convertir "
                             "archivos EPS/PS en el Editor de Imagen.").format(self.local_ver or "")
                )
        else:
            QMessageBox.warning(
                self, self.tr("No detectado"),
                self.tr("Todavía no se detecta Ghostscript. Verifica que el comando haya "
                        "terminado sin errores -- si acabas de instalarlo, puede que necesites "
                        "reiniciar DowP para que tome el PATH actualizado del sistema.")
            )

    def set_downloading_state(self, is_downloading, message=""):
        self._btn_action.setDisabled(is_downloading)
        if is_downloading:
            self._progress_bar.setRange(0, 100)
            self._progress_bar.setValue(0)
            self._progress_bar.show()
            self._progress_msg.setText(message if message else self.tr("Iniciando..."))
            self._progress_msg.show()
            self._status_badge.setText(self.tr("Procesando"))
            self._status_badge.setStyleSheet("color: #FFC107; font-weight: bold; font-size: 12px;")
        else:
            self._progress_bar.hide()
            self._progress_msg.hide()
            set_button_variant(self._btn_action, "secondary")
            self.check_status()

    def update_progress_msg(self, msg):
        self._progress_msg.setText(msg)

    def update_numeric_progress(self, value):
        self._progress_bar.setValue(value)


# ═════════════════════════════════════════════════════════════════════════════
# PÁGINA PRINCIPAL DEL GESTOR DE DEPENDENCIAS
# ═════════════════════════════════════════════════════════════════════════════

class DependenciesPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.workers = {} 
        self.update_worker = None
        self._wpc_update_worker = None
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        
        self.title_label = QLabel(self.tr("Gestor de Dependencias"))
        self.title_label.setObjectName("settingsTitle")
        layout.addWidget(self.title_label)
        
        line = QFrame()
        line.setObjectName("settingsDivider")
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

        self.desc_label = QLabel(self.tr("Configura y administra los motores y dependencias externas de DowP 2.0."))
        self.desc_label.setObjectName("settingsLabel")
        layout.addWidget(self.desc_label)

        # Scroll area para los paneles y tarjetas
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")

        scroll_content = QWidget()
        scroll_content.setObjectName("settingsScrollContent")
        scroll_content.setStyleSheet("QWidget#settingsScrollContent { background-color: transparent; }")
        self.scroll_layout = QVBoxLayout(scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 10, 0)
        self.scroll_layout.setSpacing(12)
        self.scroll_layout.setAlignment(Qt.AlignTop)

        # 1. Tarjeta FFmpeg con opciones avanzadas
        self.ffmpeg_panel = FFmpegOptionsPanel()
        self.scroll_layout.addWidget(self.ffmpeg_panel)

        # 2. Tarjeta Unificada: yt-dlp + PO Token Provider
        self.ytdlp_pot_panel = YTDLPAndPOTPanel()
        self.ytdlp_pot_panel.ytdlp_download_requested.connect(self.start_download)
        self.scroll_layout.addWidget(self.ytdlp_pot_panel)

        # 3. Tarjeta Deno (Runtime JavaScript)
        self.deno_panel = DenoCardPanel()
        self.deno_panel.download_requested.connect(self.start_download)
        self.scroll_layout.addWidget(self.deno_panel)

        # 4. Tarjeta Ghostscript (EPS/PS del Editor de Imagen -- opcional)
        self.gs_panel = GhostscriptCardPanel()
        self.gs_panel.download_requested.connect(self.start_download)
        self.scroll_layout.addWidget(self.gs_panel)

        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area)
        
        # Botones inferiores de acción
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(10)
        bottom_layout.addStretch()
        
        self.btn_open_folder = QPushButton(self.tr("Carpeta de Dependencias"))
        self.btn_open_folder.setCursor(Qt.PointingHandCursor)
        self.btn_open_folder.setFixedHeight(34)
        apply_folder_open_button_style(self.btn_open_folder, self.tr("Abrir la carpeta donde se almacenan los binarios de las dependencias"), icon_size=18)
        self.btn_open_folder.clicked.connect(self.open_dependencies_folder)
        bottom_layout.addWidget(self.btn_open_folder)

        self.btn_check_updates = QPushButton(self.tr("Buscar Actualizaciones"))
        self.btn_check_updates.setCursor(Qt.PointingHandCursor)
        self.btn_check_updates.setFixedHeight(34)
        self.btn_check_updates.setProperty("variant", "accent-orange")
        self.btn_check_updates.clicked.connect(self.check_all_updates)
        bottom_layout.addWidget(self.btn_check_updates)
        
        layout.addLayout(bottom_layout)

    def open_dependencies_folder(self):
        """Abre la carpeta de dependencias en el explorador de archivos."""
        try:
            deps_dir = os.path.dirname(get_managed_ffmpeg_dir())
            if not os.path.exists(deps_dir):
                os.makedirs(deps_dir, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(deps_dir))
        except Exception as e:
            logger.error(f"Error abriendo la carpeta de dependencias: {e}")

    def check_all_updates(self):
        self.btn_check_updates.setDisabled(True)
        self.btn_check_updates.setText(self.tr("Buscando..."))
        
        # 1. Comprobar FFmpeg
        self.ffmpeg_panel.check_updates()

        # 2. Comprobar yt-dlp y Deno
        self.ytdlp_pot_panel.set_ytdlp_searching_updates()
        self.deno_panel.set_searching_updates()

        cfg = get_config()
        ytdlp_channel = cfg.get("ytdlp_channel", "stable")

        update_configs = [
            {"id": "ytdlp", "local_func": ytdlp_local, "remote_func": ytdlp_remote, "channel": ytdlp_channel},
            {"id": "deno",  "local_func": deno_local,  "remote_func": deno_remote},
        ]

        # Ghostscript solo se comprueba en Windows, y solo si ya esta instalado: es
        # la unica plataforma donde DowP baja y gestiona el binario, asi que es la
        # unica donde puede aplicar la actualizacion que encuentre. En Mac/Linux lo
        # gestiona el gestor de paquetes del sistema y anunciar alli una version
        # nueva seria senalar algo sobre lo que la app no puede actuar.
        if platform.system() == "Windows" and self.gs_panel.is_installed:
            self.gs_panel.set_searching_updates()
            update_configs.append(
                {"id": "ghostscript", "local_func": gs_local, "remote_func": gs_remote})

        self.update_worker = UpdateCheckWorker(update_configs)
        self.update_worker.finished_signal.connect(self.on_update_check_finished)
        self.update_worker.start()

        # 3. Comprobar WPC (PO Token Provider)
        if check_wpc():
            self._wpc_update_worker = WPCUpdateCheckWorker()
            self._wpc_update_worker.finished_signal.connect(self.ytdlp_pot_panel.set_wpc_update_available)
            self._wpc_update_worker.start()

        # 4. Comprobar bgutil-pot (PO Token Provider)
        if check_potprovider():
            self._bgutil_update_worker = BGUtilUpdateCheckWorker()
            self._bgutil_update_worker.finished_signal.connect(self.ytdlp_pot_panel.set_bgutil_update_available)
            self._bgutil_update_worker.start()

    def on_update_check_finished(self, results):
        self.btn_check_updates.setDisabled(False)
        self.btn_check_updates.setText(self.tr("Buscar Actualizaciones"))
        
        if "ytdlp" in results:
            if results["ytdlp"]["local"]:
                self.ytdlp_pot_panel.ytdlp_local_ver = results["ytdlp"]["local"]
            if self.ytdlp_pot_panel.is_ytdlp_installed:
                self.ytdlp_pot_panel.set_ytdlp_update_available(results["ytdlp"]["remote"])

        if "deno" in results:
            if results["deno"]["local"]:
                self.deno_panel.local_ver = results["deno"]["local"]
            if self.deno_panel.is_installed:
                self.deno_panel.set_update_available(results["deno"]["remote"])

        if "ghostscript" in results:
            if results["ghostscript"]["local"]:
                self.gs_panel.local_ver = results["ghostscript"]["local"]
            self.gs_panel.set_update_available(results["ghostscript"]["remote"])

    def start_download(self, dep_id, version=None):
        channel = None
        if dep_id == "ytdlp":
            download_fn = download_ytdlp
            if version in ["stable", "nightly"]:
                channel = version
                version = None
            else:
                channel = get_config().get("ytdlp_channel", "stable")
        elif dep_id == "deno":
            download_fn = download_deno
        elif dep_id == "ghostscript":
            download_fn = download_ghostscript
        else:
            return

        worker = DependencyDownloadWorker(dep_id, download_fn, version=version, channel=channel)
        worker.progress_signal.connect(self.on_worker_progress)
        worker.numeric_progress_signal.connect(self.on_worker_numeric_progress)
        worker.finished_signal.connect(self.on_worker_finished)
        
        self.workers[dep_id] = worker
        worker.start()

    def on_worker_numeric_progress(self, val, dep_id):
        if dep_id == "ytdlp":
            self.ytdlp_pot_panel.update_ytdlp_numeric_progress(val)
        elif dep_id == "deno":
            self.deno_panel.update_numeric_progress(val)
        elif dep_id == "ghostscript":
            self.gs_panel.update_numeric_progress(val)

    def on_worker_progress(self, msg, dep_id):
        if dep_id == "ytdlp":
            self.ytdlp_pot_panel.update_ytdlp_progress_msg(msg)
        elif dep_id == "deno":
            self.deno_panel.update_progress_msg(msg)
        elif dep_id == "ghostscript":
            self.gs_panel.update_progress_msg(msg)

    def on_worker_finished(self, success, msg, dep_id):
        if dep_id in self.workers:
            del self.workers[dep_id] 
            
        if dep_id == "ytdlp":
            if success:
                try:
                    ytdlp_local(force_check=True)
                except Exception as e:
                    logger.error(f"Error actualizando versión local de yt-dlp: {e}")
            self.ytdlp_pot_panel.set_ytdlp_downloading_state(False)
        elif dep_id == "deno":
            if success:
                try:
                    deno_local(force_check=True)
                except Exception as e:
                    logger.error(f"Error actualizando versión local de Deno: {e}")
            self.deno_panel.set_downloading_state(False)
        elif dep_id == "ghostscript":
            self.gs_panel.set_downloading_state(False)

        if not success:
            QMessageBox.warning(self, self.tr("Error de Descarga"), self.tr("Fallo al descargar {0}:\n{1}").format(dep_id, msg))
        else:
            logger.info(f"Dependency {dep_id} downloaded successfully.")
