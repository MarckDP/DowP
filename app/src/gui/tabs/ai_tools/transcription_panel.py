"""Selector de modelo y variante, y tarjeta del motor opcional que comparte con Ajustes."""
import os
import unicodedata

from PySide6.QtCore import QLocale, Signal, Qt, QTimer, QUrl, QEvent, QCoreApplication
from PySide6.QtGui import QDesktopServices, QFontMetrics, QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox, QMessageBox, QFileDialog, QSizePolicy, QFrame, QToolButton, QProgressBar, QCheckBox, QLineEdit, QDoubleSpinBox

from core.whisper_catalog import WHISPER_MODELS, WHISPER_LANGUAGES, VAD_MODEL, VAD_DOWNLOAD_INFO, VAD_PRESETS
from core.setup import whisper_setup as setup
from gui.widgets.combo_box import AutoPopupComboBox
from gui.widgets.model_download_prompt import (
    model_downloads, model_download_key, format_model_label, confirm_model_download,
    ModelActionsRow, ModelStatusRow, open_models_settings,
)
from gui.styles import set_button_variant, apply_folder_browse_button_style, apply_folder_open_button_style, get_theme_token, register_theme_callback, set_themed_style, apply_shapes
from gui.widgets.mode_selector import ModeSelector
from core.tabs.video_tools.transcript_formats import DEFAULT_STYLE, KARAOKE_FORMATS
from core.utils.font_manager import get_available_fonts, get_static_font_path
from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon
from core.constants import AI_MODEL_HOLDER
from core.utils.cache_manager import format_bytes



# Qt da la variante regional ("Español de España", "American English", "简体中文"), pero
# Whisper reconoce el idioma, no la región.
_LANGUAGE_NAME_OVERRIDES = {"es": "Español", "en": "English", "zh": "中文"}


def _native_language_name(code: str, fallback: str) -> str:
    if code in _LANGUAGE_NAME_OVERRIDES:
        return _LANGUAGE_NAME_OVERRIDES[code]
    locale = QLocale(code)
    name = locale.nativeLanguageName() if locale.language() != QLocale.Language.C else ""
    if not name:
        return fallback.capitalize()
    # Mayúscula inicial solo en alfabeto latino: otros (como el georgiano) no la usan así.
    if "LATIN" in unicodedata.name(name[0], ""):
        name = name[:1].upper() + name[1:]
    return name



def fill_whisper_models(combo):
    """Llena un combo con los modelos de Whisper agrupados (Tiny … Turbo), con su
    variante y tamaño. Lo usan Transcripción y "Crear con IA" de Proceso Avanzado."""
    combo.addItem(AI_MODEL_HOLDER, None)
    for group in ("Tiny", "Base", "Small", "Medium", "Large", "Turbo"):
        combo.addItem(f"─── {group.upper()} ───", None)
        header = combo.model().item(combo.count() - 1)
        header.setEnabled(False)
        font = header.font()
        font.setBold(True)
        header.setFont(font)
        header.setTextAlignment(Qt.AlignCenter)
        # El catálogo ordena cada versión: multilingüe, .en; original, Q8, Q5.
        for ident, info in WHISPER_MODELS.items():
            family = "Turbo" if "turbo" in info["model"] else info["model"].split(".")[0].split("-")[0].capitalize()
            if family != group:
                continue
            precision = "F16" if info["variant"] == "f16" else info["variant"].upper()
            language = QCoreApplication.translate("TranscriptionPanel", "solo inglés") if info["english_only"] else QCoreApplication.translate("TranscriptionPanel", "multilingüe")
            label = f"{info['model']} · {precision} · {language}"
            combo.addItem(format_model_label(label, info["size_bytes"]), ident)
    refresh_whisper_model_icons(combo)
    combo.setToolTip(QCoreApplication.translate("TranscriptionPanel", "F16: modelo original. Q: variante cuantizada, de menor tamaño y consumo de memoria."))


def refresh_whisper_model_icons(combo):
    """Ícono de instalado o de descarga en cada modelo del combo."""
    ready_icon = get_colored_svg_icon("check_circle.svg", get_theme_token("estado_exito", "#40d66b"), size=14)
    missing_icon = get_colored_svg_icon("download.svg", get_theme_token("texto_secundario", "#888888"), size=14)
    for index in range(combo.count()):
        info = WHISPER_MODELS.get(combo.itemData(index))
        if not info:
            continue
        installed = setup.model_ready(info)
        combo.setItemIcon(index, ready_icon if installed else missing_icon)
        state = QCoreApplication.translate("TranscriptionPanel", "Instalado") if installed else QCoreApplication.translate("TranscriptionPanel", "No descargado")
        combo.setItemData(index, state + " · " + QCoreApplication.translate("TranscriptionPanel", "Licencia: MIT"), Qt.ToolTipRole)


def whisper_language_items():
    """[(nombre, código)] de los idiomas de Whisper: cada uno en su propio nombre, los de
    las traducciones de DowP primero."""
    first = ("es", "en", "pt")
    return [(_native_language_name(code, name), code)
            for code, name in sorted(WHISPER_LANGUAGES.items(), key=lambda item: (item[0] not in first, item[1]))]


class WhisperRuntimeCard(QFrame):
    def __init__(self, parent=None, *, dependency_card=False):
        super().__init__(parent)
        self._dependency_card = dependency_card
        self._release = None
        self._searching = False
        self._search_failed = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12) if dependency_card else layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        if dependency_card:
            self.setProperty("variant", "card")
            self.setObjectName("whisperCardPanel")
            top = QHBoxLayout()
            top.setSpacing(8)
            title = QLabel(self.tr("whisper.cpp (Transcripción)"))
            set_themed_style(title, lambda: f"font-size: 14px; font-weight: bold; color: {get_theme_token('texto_titulo', '#EEEEEE')};")
            top.addWidget(title)
            info = QToolButton()
            info.setText("?")
            info.setFixedSize(20, 20)
            set_themed_style(info, lambda: f"QToolButton {{ border: 1px solid {get_theme_token('borde_fuerte', '#555')}; border-radius: 10px;"
                f" color: {get_theme_token('texto_gris', '#AAA')}; font-size: 11px; background: {get_theme_token('fondo_control', '#2a2a2a')}; }}"
                f" QToolButton:hover {{ background: {get_theme_token('fondo_control_hover', '#3a3a3a')}; color: {get_theme_token('texto_activo', '#FFF')}; }}")
            info.setToolTip(self.tr("Motor opcional para transcribir audio y video localmente. Solo se instala cuando lo solicitas. Los modelos se administran por separado en Ajustes > Modelos."))
            top.addWidget(info)
            self.badge = QLabel()
            top.addWidget(self.badge)
            top.addStretch()
            self.version = QLabel()
            set_themed_style(self.version, lambda: f"color: {get_theme_token('texto_gris', '#AAAAAA')}; font-size: 12px;")
            top.addWidget(self.version)
            layout.addLayout(top)
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            set_themed_style(sep, lambda: f"color: {get_theme_token('borde_sutil', '#333')};")
            layout.addWidget(sep)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        if dependency_card:
            set_themed_style(self.status, lambda: f"color: {get_theme_token('texto_tenue', '#888888')}; font-size: 12px;")
        else:
            layout.addWidget(self.status)
        row = QHBoxLayout()
        row.setSpacing(12 if dependency_card else 6)
        if dependency_card:
            row.addWidget(self.status, 1)
        self.folder_button = QPushButton()
        self.folder_button.setFixedSize(32, 32)
        apply_folder_open_button_style(self.folder_button, self.tr("Abrir carpeta del motor"))
        self.folder_button.clicked.connect(self._open_folder)
        row.addWidget(self.folder_button, 0, Qt.AlignVCenter)
        self.download = QPushButton(self.tr("Descargar"))
        self.import_button = QPushButton(self.tr("Importar paquete…"))
        self.remove_button = QPushButton(self.tr("Desinstalar"))
        for button in (self.import_button, self.remove_button, self.download):
            button.setCursor(Qt.PointingHandCursor)
            set_button_variant(button, "secondary")
            if dependency_card:
                button.setMinimumWidth(110)
            row.addWidget(button, 0, Qt.AlignVCenter)
        layout.addLayout(row)
        if dependency_card:
            self.progress_bar = QProgressBar()
            self.progress_bar.setTextVisible(False)
            self.progress_bar.setFixedHeight(4)
            self.progress_bar.setRange(0, 100)
            layout.addWidget(self.progress_bar)
            self.progress_msg = QLabel()
            set_themed_style(self.progress_msg, lambda: f"color: {get_theme_token('texto_tenue', '#888888')}; font-size: 11px;")
            layout.addWidget(self.progress_msg)
            # La aceleración NVIDIA y el detector de voz, cada uno en su sección.
            self.gpu_section = WhisperGpuSection(self)
            layout.addWidget(self.gpu_section)
            self.vad_section = WhisperVadSection(self)
            layout.addWidget(self.vad_section)
        self.download.clicked.connect(self._download)
        self.import_button.clicked.connect(self._import)
        self.remove_button.clicked.connect(self._remove)
        self._started = False
        manager = model_downloads()
        manager.started.connect(self.refresh)
        manager.progress_changed.connect(self.refresh)
        manager.finished.connect(self._finished)
        manager.models_changed.connect(self.refresh)
        self.refresh()

    def refresh(self, *_):
        manager = model_downloads()
        key = model_download_key(setup.ENGINE_INFO)
        busy = manager.is_downloading(key)
        asset = setup.runtime_asset()
        installed = setup.runtime_ready()
        local = setup.get_local_version() if installed else None
        remote = self._release["version"] if self._release else None
        newer = setup.is_newer_version(remote, local)
        downloadable = bool(self._release.get("asset")) if self._release else bool(asset)
        self.download.setEnabled(downloadable and not busy and not self._searching)
        self.folder_button.setEnabled(installed)
        self.remove_button.setEnabled(installed and not busy)
        if self._dependency_card:
            self.gpu_section.refresh(busy)
        self.import_button.setEnabled(not busy)
        self.download.setText(self.tr("Actualizar") if newer else self.tr("Instalar oficial") if installed and not local and remote else self.tr("Reinstalar") if installed else self.tr("Descargar"))
        if busy:
            text = self.tr("Descargando whisper.cpp: {0}%").format(manager.progress(key))
        elif setup.runtime_ready():
            text = self.tr("whisper.cpp instalado. Los modelos se descargan por separado.")
        elif asset:
            text = format_model_label("whisper.cpp " + setup.VERSION, asset["size"])
        else:
            text = self.tr("No hay un CLI oficial descargable para este sistema. Importa un paquete nativo con whisper-cli y sus bibliotecas.")
        if self._dependency_card:
            version_text = self.tr("Versión: {0}").format(local) if local else self.tr("Versión: Desconocida") if installed else self.tr("No instalado")
            if self._searching:
                version_text += self.tr(" · Buscando…")
            elif self._search_failed:
                version_text += self.tr(" · No se pudo comprobar")
            elif remote and (newer or not local):
                version_text += self.tr(" · Disponible: {0}").format(remote)
            self.version.setText(version_text)
            self.version.setToolTip(version_text)
            self.badge.setText(self.tr("Procesando") if busy else self.tr("✓ Instalado") if installed else self.tr("Opcional · No instalado"))
            token, fallback = ("estado_aviso", "#FFC107") if busy else ("estado_exito", "#4CAF50") if installed else ("texto_gris", "#AAAAAA")
            set_themed_style(self.badge, lambda: f"color: {get_theme_token(token, fallback)}; font-weight: bold; font-size: 12px;")
            set_button_variant(self.download, "accent-blue" if (newer or not installed) and not busy else "secondary")
            self.progress_bar.setVisible(busy)
            self.progress_msg.setVisible(busy)
            self.progress_bar.setValue(manager.progress(key) if busy else 0)
            self.progress_msg.setText(self.tr("Procesando whisper.cpp: {0}%").format(manager.progress(key)) if busy else "")
            text = self.tr("Opcional. Transcribe audio y video sin conexión. Los modelos se descargan por separado.")
            if setup.runtime_is_homebrew():
                text = self.tr("Se usa el whisper-cli instalado con Homebrew. Para usar el de DowP, descárgalo.")
            elif asset and asset.get("beta"):
                text += " " + self.tr("Beta: compilación sin probar todavía en equipos como este; si falla, avísanos.")
            if not downloadable:
                text += " " + self.tr("La versión consultada no ofrece un paquete nativo verificado para este sistema; puedes importarlo.")
        self.status.setText(text)

    def set_searching_updates(self):
        self._searching = True
        self.refresh()

    def set_update_available(self, release):
        self._searching = False
        self._search_failed = release is None
        # Ante un fallo de red pasajero se conserva el candidato verificado antes.
        if release is not None:
            self._release = release
        self.refresh()

    def _open_folder(self):
        binary = setup.runtime_path()
        if binary:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(binary)))

    def _can_modify(self):
        from core.utils import queue_manager
        manager = queue_manager._global_queue_manager
        terminal = {queue_manager.JobStatus.COMPLETED, queue_manager.JobStatus.FAILED, queue_manager.JobStatus.CANCELLED}
        if manager and any(job.job_type == "TRANSCRIBE" and job.status not in terminal for job in manager.get_all_jobs()):
            QMessageBox.information(self, self.tr("Motor en uso"), self.tr("Espera a que terminen o cancela las transcripciones pendientes antes de modificar el motor."))
            return False
        return not model_downloads().is_downloading(model_download_key(setup.ENGINE_INFO))

    def _remove(self):
        if not self._can_modify():
            return
        if QMessageBox.question(self, self.tr("Desinstalar whisper.cpp"), self.tr("¿Desinstalar el motor whisper.cpp? Los modelos descargados se conservarán.")) != QMessageBox.Yes:
            return
        self._started = model_downloads().start(model_download_key(setup.ENGINE_INFO), setup.uninstall_runtime, setup.ENGINE_INFO)

    def _download(self):
        if not self._can_modify():
            return
        key = model_download_key(setup.ENGINE_INFO)
        if not setup.runtime_ready():
            # Primera instalación: el mismo diálogo que al crear subtítulos (con la
            # aceleración por GPU que admita el equipo), ver whisper_download_dialog.
            from PySide6.QtWidgets import QDialog
            from gui.widgets.whisper_download_dialog import WhisperDownloadDialog
            dialog = WhisperDownloadDialog(self, {"engine": True, "model": None, "vad": False}, engine_only_title=True)
            if dialog.exec() == QDialog.Accepted:
                info = dict(setup.ENGINE_INFO, variants=dialog.engine_variants())
                if self._release:
                    info["release"] = self._release
                self._started = model_downloads().start(key, setup.download_runtime, info)
            return
        # Actualizar o reinstalar: también la aceleración por GPU, si está instalada.
        variants = ["cpu"] + ([setup.accel_variant()] if setup.accel_variant() else [])
        asset = self._release.get("asset") if self._release else None
        size = asset["size"] if asset else setup.runtime_asset()["size"] if not self._release and setup.runtime_asset() else None
        if size and len(variants) > 1:
            size += (setup.accel_asset(variants[1], self._release) or {}).get("size", 0)
        version = self._release["version"] if self._release else setup.VERSION
        if size and confirm_model_download(self, "whisper.cpp " + version, size, subject=self.tr("motor")):
            info = dict(setup.ENGINE_INFO, variants=variants)
            if self._release:
                info["release"] = self._release
            self._started = model_downloads().start(key, setup.download_runtime, info)

    def _toggle_accel(self):
        if not self._can_modify():
            return
        key = model_download_key(setup.ENGINE_INFO)
        if setup.accel_variant():
            if QMessageBox.question(self, self.tr("Desinstalar aceleración por GPU"), self.tr(
                    "¿Desinstalar la aceleración por GPU? El motor base se conserva: las transcripciones "
                    "seguirán funcionando, pero más lentas.")) == QMessageBox.Yes:
                self._started = model_downloads().start(key, setup.uninstall_accel, setup.ENGINE_INFO)
            return
        # Elegir entre las que admite el equipo (Vulkan recomendada; CUDA con NVIDIA).
        from gui.widgets.whisper_download_dialog import ask_accel_download
        self._started = ask_accel_download(self)

    def _import(self):
        if not self._can_modify():
            return
        path, _ = QFileDialog.getOpenFileName(self, self.tr("Importar whisper.cpp"), "", self.tr("Paquetes (*.zip *.tar.gz *.tgz)"))
        if not path:
            return
        def install(_info, progress_callback=None):
            try:
                setup.install_archive(path)
                return True, ""
            except Exception as exc:
                return False, str(exc)
        self._started = model_downloads().start(model_download_key(setup.ENGINE_INFO), install, setup.ENGINE_INFO)

    def _finished(self, success, message, key):
        if key == model_download_key(setup.ENGINE_INFO) and self._started:
            self._started = False
            if not success:
                QMessageBox.warning(self, self.tr("whisper.cpp"), message)
        self.refresh()


# Formatos por modo (ver core/tabs/video_tools/transcript_formats.py): (clave, nombre visible).
_SUBTITLE_FORMATS = [("srt", "SRT"), ("vtt", "VTT"), ("ass", "ASS"), ("lrc", "LRC"), ("ttml", "TTML"), ("sbv", "SBV")]
_TEXT_FORMATS = [("txt", "TXT"), ("md", "Markdown"), ("html", "HTML"), ("rtf", "RTF"), ("json", "JSON"), ("csv", "CSV")]
_MODE_SUBTITLES, _MODE_TEXT = "subtitles", "text"


class WhisperGpuSection(QWidget):
    """Aceleración por GPU dentro de la tarjeta de whisper.cpp en Dependencias, como el
    detector de voz: cuál está instalada (Vulkan o CUDA), la GPU detectada e
    Instalar/Desinstalar. Solo aparece si el equipo tiene una GPU que se pueda usar o si ya
    está instalada. Instalarla y desinstalarla lo hace la tarjeta
    (WhisperRuntimeCard._toggle_accel), que sabe si el motor está en uso."""

    def __init__(self, card):
        super().__init__(card)
        self._card = card
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(8)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        set_themed_style(sep, lambda: f"color: {get_theme_token('borde_sutil', '#333')};")
        layout.addWidget(sep)
        top = QHBoxLayout()
        top.setSpacing(8)
        title = QLabel(self.tr("Aceleración por GPU"))
        set_themed_style(title, lambda: f"font-size: 13px; font-weight: bold; color: {get_theme_token('texto_fuerte', '#DDDDDD')};")
        top.addWidget(title)
        info = QToolButton()
        info.setText("?")
        info.setFixedSize(18, 18)
        set_themed_style(info, lambda: f"QToolButton {{ border: 1px solid {get_theme_token('borde_fuerte', '#555')}; border-radius: 9px;"
            f" color: {get_theme_token('texto_gris', '#AAA')}; font-size: 10px; background: {get_theme_token('fondo_control', '#2a2a2a')}; }}"
            f" QToolButton:hover {{ background: {get_theme_token('fondo_control_hover', '#3a3a3a')}; color: {get_theme_token('texto_activo', '#FFF')}; }}")
        info.setToolTip(self.tr(
            "Transcribe con la GPU, mucho más rápido que con la CPU. Vulkan (recomendada) "
            "funciona con NVIDIA, AMD e Intel y pesa poco; con NVIDIA también está CUDA, el "
            "paquete oficial, más pesado. Se instala junto al motor base, que queda como "
            "respaldo: si la GPU falla, la transcripción se repite por CPU. Usa la casilla "
            "\"Aceleración de Hardware (GPU)\" de Transcripción."))
        top.addWidget(info)
        self.badge = QLabel()
        top.addWidget(self.badge)
        top.addStretch()
        self.version = QLabel()
        set_themed_style(self.version, lambda: f"color: {get_theme_token('texto_gris', '#AAAAAA')}; font-size: 12px;")
        top.addWidget(self.version)
        layout.addLayout(top)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        set_themed_style(self.status, lambda: f"color: {get_theme_token('texto_tenue', '#888888')}; font-size: 12px;")
        row.addWidget(self.status, 1)
        self.button = QPushButton()
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.setMinimumWidth(110)
        set_button_variant(self.button, "secondary")
        self.button.clicked.connect(card._toggle_accel)
        row.addWidget(self.button, 0, Qt.AlignVCenter)
        layout.addLayout(row)

    def refresh(self, busy: bool):
        installed = setup.accel_variant()
        gpu = setup.detect_gpu()
        options = gpu["options"] if gpu else []
        if not (installed or options or (gpu and gpu["vendor"] == "NVIDIA")):
            self.setVisible(False)
            return
        self.setVisible(True)
        engine = bool(setup.runtime_path()) and not setup.runtime_is_homebrew()
        name = gpu["name"] if gpu else "GPU"
        if installed:
            beta = setup.accel_is_beta(installed, gpu)
            self.badge.setText(self.tr("✓ Instalada") + (" · " + self.tr("Beta") if beta else ""))
            token, fallback = "estado_exito", "#4CAF50"
            self.version.setText(setup.ACCEL_VARIANTS[installed]["label"])
            self.status.setText(self.tr("Transcribe con la GPU {0}. Si falla, se usa el motor base.").format(name))
        else:
            self.badge.setText(self.tr("Opcional · No instalada"))
            token, fallback = "texto_gris", "#AAAAAA"
            recommended = options[0] if options else None
            asset = setup.accel_asset(recommended) if recommended else None
            self.version.setText(self.tr("Disponible: {0}").format(setup.ACCEL_VARIANTS[recommended]["label"]) if recommended else "")
            if not recommended:
                self.status.setText(self.tr("Se detectó {0}, pero su driver ({1}) es antiguo para usar la GPU. "
                                            "Actualízalo para poder instalarla.").format(name, gpu["driver"] if gpu else ""))
            elif not engine:
                self.status.setText(self.tr("Se detectó {0}. Se ofrece al descargar el motor.").format(name))
            else:
                text = self.tr("Se detectó {0}. Transcribe mucho más rápido con la GPU · {1}.").format(
                    name, format_bytes(asset["size"]) if asset else "")
                if setup.accel_is_beta(recommended, gpu):
                    text += " " + self.tr("(Beta)")
                self.status.setText(text)
        set_themed_style(self.badge, lambda: f"color: {get_theme_token(token, fallback)}; font-weight: bold; font-size: 12px;")
        self.button.setText(self.tr("Desinstalar") if installed else self.tr("Instalar"))
        self.button.setVisible(bool(installed or (options and engine)))
        self.button.setEnabled(not busy)
        set_button_variant(self.button, "secondary" if installed else "accent-blue")


class WhisperVadSection(QWidget):
    """Complemento de la tarjeta de whisper.cpp en Dependencias: el detector de voz Silero
    que usa "Saltar silencios". Como el PO Token dentro de la tarjeta de yt-dlp: su propia
    versión, descarga, actualización y borrado. Si no hay una versión más nueva conocida,
    se instala la probada (VAD_MODEL)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._latest = None
        self._searching = False
        self._search_failed = False
        self._started = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(8)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        set_themed_style(sep, lambda: f"color: {get_theme_token('borde_sutil', '#333')};")
        layout.addWidget(sep)
        top = QHBoxLayout()
        top.setSpacing(8)
        title = QLabel(self.tr("Detector de voz (VAD)"))
        set_themed_style(title, lambda: f"font-size: 13px; font-weight: bold; color: {get_theme_token('texto_fuerte', '#DDDDDD')};")
        top.addWidget(title)
        info = QToolButton()
        info.setText("?")
        info.setFixedSize(18, 18)
        set_themed_style(info, lambda: f"QToolButton {{ border: 1px solid {get_theme_token('borde_fuerte', '#555')}; border-radius: 9px;"
            f" color: {get_theme_token('texto_gris', '#AAA')}; font-size: 10px; background: {get_theme_token('fondo_control', '#2a2a2a')}; }}"
            f" QToolButton:hover {{ background: {get_theme_token('fondo_control_hover', '#3a3a3a')}; color: {get_theme_token('texto_activo', '#FFF')}; }}")
        info.setToolTip(self.tr(
            "Silero VAD: un modelo pequeño que detecta en qué momentos hay voz. Con "
            "\"Saltar silencios\" whisper.cpp transcribe solo esos tramos: más rápido en audios "
            "largos y sin frases inventadas en los silencios o la música. Licencia MIT."))
        top.addWidget(info)
        self.badge = QLabel()
        top.addWidget(self.badge)
        top.addStretch()
        self.version = QLabel()
        set_themed_style(self.version, lambda: f"color: {get_theme_token('texto_gris', '#AAAAAA')}; font-size: 12px;")
        top.addWidget(self.version)
        layout.addLayout(top)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        set_themed_style(self.status, lambda: f"color: {get_theme_token('texto_tenue', '#888888')}; font-size: 12px;")
        row.addWidget(self.status, 1)
        self.remove_button = QPushButton(self.tr("Eliminar"))
        self.download = QPushButton(self.tr("Descargar"))
        for button in (self.remove_button, self.download):
            button.setCursor(Qt.PointingHandCursor)
            button.setMinimumWidth(110)
            set_button_variant(button, "secondary")
            row.addWidget(button, 0, Qt.AlignVCenter)
        layout.addLayout(row)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar)
        self.download.clicked.connect(self._download)
        self.remove_button.clicked.connect(self._remove)
        manager = model_downloads()
        manager.started.connect(self.refresh)
        manager.progress_changed.connect(self.refresh)
        manager.finished.connect(self._finished)
        manager.models_changed.connect(self.refresh)
        self.refresh()

    def _key(self):
        return model_download_key(VAD_DOWNLOAD_INFO)

    def refresh(self, *_):
        manager = model_downloads()
        busy = manager.is_downloading(self._key())
        local = setup.vad_local_version()
        newer = setup.vad_is_newer(self._latest, local)
        remote = self._latest["variant"].lstrip("v") if self._latest else None
        self.download.setEnabled(not busy and not self._searching)
        self.remove_button.setEnabled(bool(local) and not busy)
        self.download.setText(self.tr("Actualizar") if newer else self.tr("Reinstalar") if local else self.tr("Descargar"))
        set_button_variant(self.download, "accent-blue" if (newer or not local) and not busy else "secondary")
        version_text = self.tr("Versión: {0}").format(local) if local else self.tr("No instalado")
        if self._searching:
            version_text += self.tr(" · Buscando…")
        elif self._search_failed:
            version_text += self.tr(" · No se pudo comprobar")
        elif remote and (newer or not local):
            version_text += self.tr(" · Disponible: {0}").format(remote)
        self.version.setText(version_text)
        self.badge.setText(self.tr("Procesando") if busy else self.tr("✓ Instalado") if local else self.tr("Opcional · No instalado"))
        token, fallback = ("estado_aviso", "#FFC107") if busy else ("estado_exito", "#4CAF50") if local else ("texto_gris", "#AAAAAA")
        set_themed_style(self.badge, lambda: f"color: {get_theme_token(token, fallback)}; font-weight: bold; font-size: 12px;")
        self.progress_bar.setVisible(busy)
        self.progress_bar.setValue(manager.progress(self._key()) if busy else 0)
        if busy:
            self.status.setText(self.tr("Descargando detector de voz: {0}%").format(manager.progress(self._key())))
        else:
            self.status.setText(self.tr("Complemento opcional para \"Saltar silencios\" en Transcripción. Se guarda en la carpeta de modelos."))

    def set_searching_updates(self):
        self._searching = True
        self.refresh()

    def set_update_available(self, info):
        self._searching = False
        self._search_failed = info is None
        if info is not None:
            self._latest = info
        self.refresh()

    def _transcribing(self):
        from core.utils import queue_manager
        manager = queue_manager._global_queue_manager
        terminal = {queue_manager.JobStatus.COMPLETED, queue_manager.JobStatus.FAILED, queue_manager.JobStatus.CANCELLED}
        if manager and any(job.job_type == "TRANSCRIBE" and job.status not in terminal for job in manager.get_all_jobs()):
            QMessageBox.information(self, self.tr("Detector en uso"), self.tr("Espera a que terminen o cancela las transcripciones pendientes antes de modificar el detector de voz."))
            return True
        return False

    def _download(self):
        if self._transcribing() or model_downloads().is_downloading(self._key()):
            return
        # La más reciente conocida; sin consulta (o si falló), la versión probada.
        info = self._latest or VAD_MODEL
        if confirm_model_download(self, "Silero VAD " + info["variant"], info["size_bytes"]):
            self._started = model_downloads().start(self._key(), setup.download_vad, info)

    def _remove(self):
        if self._transcribing():
            return
        if QMessageBox.question(self, self.tr("Eliminar detector de voz"),
                                self.tr("¿Eliminar el detector de voz? \"Saltar silencios\" volverá a pedir descargarlo.")) != QMessageBox.Yes:
            return
        if not setup.delete_vad():
            QMessageBox.warning(self, self.tr("Eliminar detector de voz"), self.tr("No se pudo eliminar el archivo."))
        model_downloads().models_changed.emit()

    def _finished(self, success, message, key):
        if key == self._key() and self._started:
            self._started = False
            if not success:
                QMessageBox.warning(self, self.tr("Detector de voz"), message)
        self.refresh()


class TranscriptionPanel(QWidget):
    """Opciones de Transcripción, con el mismo molde que las otras páginas de Herramientas
    IA: "Salida" (modo Subtítulos | Texto, formato y sus opciones), la tarjeta del modelo
    ("Transcripción con IA", como "Mapa de Profundidad con IA") y "Opciones de audio"."""

    selection_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self._row_labels = []
        self._format_by_mode = {_MODE_SUBTITLES: "srt", _MODE_TEXT: "txt"}

        # ── Salida ───────────────────────────────────────────────────────────
        card, out = self._card(self.tr("Salida"))
        self.mode_selector = ModeSelector(card, labels=[self.tr("Subtítulos"), self.tr("Texto")])
        out.addWidget(self.mode_selector)
        self.output = self._combo(out, self.tr("Formato:"))
        self.subtitle_options = QWidget(card)
        so = QVBoxLayout(self.subtitle_options)
        so.setContentsMargins(0, 0, 0, 0)
        so.setSpacing(8)
        self.embed = self._combo(so, self.tr("Guardar como:"))
        self.embed.addItem(self.tr("Archivo de subtítulos"), "none")
        self.embed.addItem(self.tr("Pista dentro del video"), "track")
        self.embed.addItem(self.tr("Quemados en la imagen"), "burn")
        self.embed.setToolTip(self.tr(
            "Archivo: un archivo aparte, junto al video.\n"
            "Pista: un video con los subtítulos como pista que se puede activar o desactivar. "
            "No recodifica (salvo si recortas un tramo). MP4, MOV y WebM los guardan sin estilo; "
            "MKV conserva el ASS con estilo. Otros formatos salen en MKV.\n"
            "Quemados: dibujados en la imagen con el estilo elegido, visibles en cualquier "
            "reproductor o red social. Recodifica el video a MP4 (H.264), así que tarda más."))
        self.max_chars = QSpinBox()
        self.max_chars.setRange(0, 120)
        self.max_chars.setValue(42)
        self.max_chars.setSpecialValueText(self.tr("Sin límite"))
        self.max_chars.setSuffix(self.tr(" caracteres"))
        self.max_chars.setToolTip(self.tr("Largo máximo de cada línea. 42 es el estándar de subtítulos."))
        self._row(so, self.tr("Largo de línea:"), self.max_chars)
        self.max_lines = self._combo(so, self.tr("Líneas:"))
        self.max_lines.addItem(self.tr("1 línea"), 1)
        self.max_lines.addItem(self.tr("2 líneas"), 2)
        self.max_lines.setCurrentIndex(1)
        self.split = self._combo(so, self.tr("Corte:"))
        self.split.addItem(self.tr("Por frases"), "sentences")
        self.split.addItem(self.tr("Por palabras"), "words")
        self.split.addItem(self.tr("Karaoke (resalta cada palabra)"), "karaoke")
        self.split.setToolTip(self.tr(
            "Por palabras: subtítulos cortos de pocas palabras (1 = palabra por palabra), como en "
            "TikTok o Reels.\n"
            "Karaoke: la frase completa, y cada palabra cambia de color cuando se dice. Solo en "
            "ASS, LRC (el LRC \"mejorado\" de los reproductores de música) y quemados.\n"
            "Los dos calculan los tiempos de cada palabra con más precisión, así que tardan algo más."))
        self.words_row = QWidget(self.subtitle_options)
        wr = QVBoxLayout(self.words_row)
        wr.setContentsMargins(0, 0, 0, 0)
        self.max_words = QSpinBox()
        self.max_words.setRange(1, 10)
        self.max_words.setValue(1)
        self.max_words.setToolTip(self.tr(
            "Palabras por subtítulo. Un subtítulo nunca cruza el final de una frase, y las "
            "palabras de cada frase se reparten parejas."))
        self._row(wr, self.tr("Palabras:"), self.max_words)
        so.addWidget(self.words_row)
        out.addWidget(self.subtitle_options)
        self.text_options = QWidget(card)
        to = QVBoxLayout(self.text_options)
        to.setContentsMargins(0, 0, 0, 0)
        to.setSpacing(8)
        self.text_layout = self._combo(to, self.tr("Organización:"))
        self.text_layout.addItem(self.tr("Párrafos (por pausas)"), "paragraphs")
        self.text_layout.addItem(self.tr("Una línea por segmento"), "segments")
        self.timestamps = QCheckBox(self.tr("Incluir marcas de tiempo"))
        self.timestamps.setToolTip(self.tr("Agrega el tiempo, por ejemplo [01:23], al inicio de cada párrafo o línea."))
        to.addWidget(self.timestamps)
        out.addWidget(self.text_options)
        layout.addWidget(card)

        # ── Estilo (ASS y quemados) ──────────────────────────────────────────
        self.style_card, sc = self._card(self.tr("Estilo de los subtítulos"))
        # La fuente solo se puede garantizar al quemar (DowP la pasa a libass) o en una pista
        # MKV (la lleva adjunta). Un ASS suelto depende de las fuentes del equipo que lo
        # reproduce: ahí la fila se oculta y se usa Arial (ver _font_applies).
        self.font_row = QWidget(self.style_card)
        fr = QVBoxLayout(self.font_row)
        fr.setContentsMargins(0, 0, 0, 0)
        self.style_font = self._combo(fr, self.tr("Fuente:"))
        families = ["Arial"] + sorted({f for f in get_available_fonts() if f != "Arial"}, key=str.casefold)
        for family in families:
            self.style_font.addItem(family, family)
        self.style_font.setToolTip(self.tr(
            "Al quemar se dibuja con esta fuente. En una pista MKV va adjunta al video, y la "
            "usan reproductores como VLC, mpv o MPC aunque no esté instalada."))
        sc.addWidget(self.font_row)
        self.style_size = QSpinBox()
        self.style_size.setRange(16, 200)
        self.style_size.setValue(DEFAULT_STYLE["size"])
        self.style_size.setSuffix(" px")
        self.style_size.setToolTip(self.tr("Tamaño para un video de 1080 de alto; se ajusta solo a la resolución de cada video."))
        self._row(sc, self.tr("Tamaño:"), self.style_size)
        self.style_position = self._combo(sc, self.tr("Posición:"))
        self.style_position.addItem(self.tr("Abajo"), "bottom")
        self.style_position.addItem(self.tr("Centro"), "middle")
        self.style_position.addItem(self.tr("Arriba"), "top")
        self.style_color = self._color_button(DEFAULT_STYLE["color"])
        self._row(sc, self.tr("Color del texto:"), self.style_color, expand=False)
        self.style_outline = self._color_button(DEFAULT_STYLE["outline"])
        self._row(sc, self.tr("Color del borde:"), self.style_outline, expand=False)
        self.karaoke_row = QWidget(self.style_card)
        kr = QVBoxLayout(self.karaoke_row)
        kr.setContentsMargins(0, 0, 0, 0)
        self.style_karaoke = self._color_button(DEFAULT_STYLE["karaoke_color"])
        self.style_karaoke.setToolTip(self.tr("Color que toma cada palabra cuando se dice."))
        self._row(kr, self.tr("Color del karaoke:"), self.style_karaoke, expand=False)
        sc.addWidget(self.karaoke_row)
        checks = QHBoxLayout()
        self.style_bold = QCheckBox(self.tr("Negrita"))
        self.style_bold.setChecked(DEFAULT_STYLE["bold"])
        self.style_box = QCheckBox(self.tr("Caja de fondo"))
        self.style_box.setToolTip(self.tr("Un recuadro oscuro semitransparente detrás del texto, en lugar del borde. Se lee mejor sobre fondos claros o con mucho movimiento."))
        checks.addWidget(self.style_bold)
        checks.addWidget(self.style_box)
        checks.addStretch()
        sc.addLayout(checks)
        self.style_note = QLabel(self.tr("Las pistas en MP4, MOV o WebM no conservan el estilo; en MKV sí, con la fuente adjunta."))
        self.style_note.setWordWrap(True)
        self.style_note.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        set_themed_style(self.style_note, lambda: f"color: {get_theme_token('texto_tenue', '#888888')}; font-size: 11px;")
        sc.addWidget(self.style_note)
        layout.addWidget(self.style_card)

        # ── Transcripción con IA (motor y modelo) ────────────────────────────
        model_card = QFrame(self)
        model_card.setObjectName("transcriptionModelCard")
        set_themed_style(model_card, lambda: f"""
            QFrame#transcriptionModelCard {{
                background-color: {get_theme_token('fondo_secundario', '#1e1e1e')};
                border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                border-radius: 8px;
            }}
        """)
        mc = QVBoxLayout(model_card)
        mc.setContentsMargins(14, 14, 14, 14)
        mc.setSpacing(8)
        title = QLabel(self.tr("Transcripción con IA"))
        title.setStyleSheet(apply_shapes("font-weight: bold; font-size: 13px;"))
        mc.addWidget(title)
        self.check_gpu = QCheckBox(self.tr("Aceleración de Hardware (GPU)"))
        self.check_gpu.setChecked(True)
        self.check_gpu.setToolTip(self.tr(
            "Con la aceleración NVIDIA instalada (se ofrece al descargar el motor si hay una "
            "NVIDIA), transcribe con la GPU: mucho más rápido. Desmarcada, usa siempre la CPU. "
            "Si la GPU falla, se repite por CPU automáticamente."))
        mc.addWidget(self.check_gpu)
        self.runtime_toggle = QPushButton()
        self.runtime_toggle.setFixedSize(32, 32)
        self.runtime_toggle.setCursor(Qt.PointingHandCursor)
        self.runtime_toggle.setAccessibleName(self.tr("Configurar motor"))
        apply_folder_browse_button_style(self.runtime_toggle, self.tr("Configurar motor"), icon_name="settings.svg")
        self.motor = self._combo(mc, self.tr("Motor:"), trailing=self.runtime_toggle)
        self.motor.addItem("whisper.cpp", "whisper.cpp")
        self.runtime_toggle.clicked.connect(self._open_runtime_settings)
        self.model = self._combo(mc, self.tr("Modelo:"))
        fill_whisper_models(self.model)
        register_theme_callback(self, "whisper_model_icons", self._refresh_model_items)
        self.lbl_license = QLabel(self.tr("Licencia: MIT"))
        set_themed_style(self.lbl_license, lambda: f"color: {get_theme_token('texto_tenue', '#888888')}; font-size: 10px;")
        mc.addWidget(self.lbl_license)
        self.actions = ModelActionsRow(self)
        mc.addWidget(self.actions)
        self.status = ModelStatusRow(self)
        mc.addWidget(self.status)
        # Aviso en línea si falta el motor (dependencia opcional, ver whisper_download_dialog).
        from gui.widgets.whisper_download_dialog import WhisperEngineNotice
        self.engine_notice = WhisperEngineNotice(lambda: self.get_settings(), model_card)
        mc.addWidget(self.engine_notice)
        # Ya hay motor de CPU y una NVIDIA sin la aceleración: sugerencia descartable.
        from gui.widgets.whisper_download_dialog import WhisperGpuHint
        self.gpu_hint = WhisperGpuHint(model_card)
        mc.addWidget(self.gpu_hint)
        layout.addWidget(model_card)

        # ── Opciones de audio ────────────────────────────────────────────────
        card, ao = self._card(self.tr("Opciones de audio"))
        self.track = self._combo(ao, self.tr("Pista:"))
        self.track.addItem(self.tr("Todas (un archivo por pista)"), "all")
        self.track.addItem(self.tr("Pista 1"), 0)
        self.track.setCurrentIndex(1)
        self.track.setToolTip(self.tr("La selección se aplica por número de pista a cada archivo del lote. Todas crea una fila y un resultado por pista."))
        self.language = self._combo(ao, self.tr("Idioma:"))
        self.language.addItem(self.tr("Detectar automáticamente"), "auto")
        # Cada idioma en su propio nombre ("Français", "Deutsch", "日本語"), que vale en
        # cualquier idioma de DowP sin traducir 99 nombres. Si Qt no reconoce el código,
        # queda el nombre del catálogo.
        for name, code in whisper_language_items():
            self.language.addItem(name, code)
        self.task = self._combo(ao, self.tr("Tarea:"))
        self.task.addItem(self.tr("Transcribir en el idioma original"), "transcribe")
        self.task.addItem(self.tr("Traducir a inglés"), "translate")
        self.prompt = QLineEdit()
        self.prompt.setPlaceholderText(self.tr("Nombres o términos, separados por comas"))
        self.prompt.setToolTip(self.tr(
            "Vocabulario: nombres propios, marcas o jerga que Whisper debe escribir bien "
            "(por ejemplo: DowP, Upscayl, MoGe)."))
        self._row(ao, self.tr("Vocabulario:"), self.prompt)
        self.threads = QSpinBox()
        self.threads.setRange(1, 64)
        self.threads.setValue(min(8, os.cpu_count() or 4))
        self._row(ao, self.tr("Hilos de CPU:"), self.threads)
        self.vad = QCheckBox(self.tr("Saltar silencios (VAD)"))
        self.vad.setToolTip(self.tr(
            "Transcribe solo los tramos con voz: más rápido en audios largos y con menos frases "
            "inventadas en los silencios. Usa un modelo pequeño aparte (885 KB) que se descarga una vez."))
        ao.addWidget(self.vad)
        self.vad_preset = self._combo(ao, self.tr("Sensibilidad:"))
        self.vad_preset.addItem(self.tr("Normal"), "normal")
        self.vad_preset.addItem(self.tr("Alta (voces bajas, susurros)"), "high")
        self.vad_preset.addItem(self.tr("Estricta (música o ruido de fondo)"), "strict")
        self.vad_preset.addItem(self.tr("Personalizada"), "custom")
        self.vad_preset.setToolTip(self.tr(
            "Alta detecta voces débiles y deja más margen para no cortar sílabas. Estricta "
            "ignora lo que no sea voz clara. Personalizada permite ajustar cada valor."))
        self.vad_custom = QWidget(card)
        vc = QVBoxLayout(self.vad_custom)
        vc.setContentsMargins(0, 0, 0, 0)
        vc.setSpacing(8)
        self.vad_threshold = QDoubleSpinBox()
        self.vad_threshold.setRange(0.05, 0.95)
        self.vad_threshold.setSingleStep(0.05)
        self.vad_threshold.setDecimals(2)
        self.vad_threshold.setToolTip(self.tr("Probabilidad mínima para considerar que hay voz. Más bajo detecta más; más alto ignora más ruido."))
        self._row(vc, self.tr("Umbral:"), self.vad_threshold)
        self.vad_min_silence = self._ms_spin(0, 5000, 50, self.tr("Pausa necesaria para separar dos tramos de voz."))
        self._row(vc, self.tr("Silencio mínimo:"), self.vad_min_silence)
        self.vad_min_speech = self._ms_spin(0, 5000, 50, self.tr("Los sonidos más cortos se descartan (golpes, clics)."))
        self._row(vc, self.tr("Voz mínima:"), self.vad_min_speech)
        self.vad_pad = self._ms_spin(0, 2000, 10, self.tr("Margen que se agrega antes y después de cada tramo, para no cortar la primera o la última sílaba."))
        self._row(vc, self.tr("Margen:"), self.vad_pad)
        self.vad_max_speech = QSpinBox()
        self.vad_max_speech.setRange(0, 600)
        self.vad_max_speech.setSuffix(" s")
        self.vad_max_speech.setSpecialValueText(self.tr("Sin límite"))
        self.vad_max_speech.setToolTip(self.tr("Parte los tramos de voz más largos que esto."))
        self._row(vc, self.tr("Tramo máximo:"), self.vad_max_speech)
        self._set_vad_values(VAD_PRESETS["normal"])
        self._last_vad_preset = "normal"
        ao.addWidget(self.vad_custom)
        layout.addWidget(card)

        self._align_labels()
        self._started = set()
        self.mode_selector.mode_changed.connect(self._mode_changed)
        self.model.currentIndexChanged.connect(self._model_changed)
        for combo in (self.language, self.task, self.track, self.max_lines, self.text_layout,
                      self.style_font, self.style_position):
            combo.currentIndexChanged.connect(self.refresh)
        self.output.currentIndexChanged.connect(self._output_changed)
        for combo in (self.embed, self.split):
            combo.currentIndexChanged.connect(self._output_changed)
        for widget in (self.threads, self.max_chars, self.style_size, self.max_words):
            widget.valueChanged.connect(self.refresh)
        for check in (self.check_gpu, self.timestamps, self.style_bold, self.style_box):
            check.toggled.connect(self.refresh)
        self.prompt.editingFinished.connect(self.refresh)
        self.vad.toggled.connect(self._vad_toggled)
        self.vad_preset.currentIndexChanged.connect(self._vad_preset_changed)
        for spin in (self.vad_threshold, self.vad_min_silence, self.vad_min_speech, self.vad_pad, self.vad_max_speech):
            spin.valueChanged.connect(self.refresh)
        self.model.activated.connect(self._offer_download)
        self.actions.delete_requested.connect(self._delete)
        self.actions.manage_requested.connect(lambda: open_models_settings(self, self.info(), "transcription"))
        manager = model_downloads()
        manager.started.connect(self.refresh)
        manager.progress_changed.connect(self.refresh)
        manager.finished.connect(self._finished)
        manager.models_changed.connect(self._models_changed)
        self._fill_formats()
        self._update_vad_controls()
        self._model_changed()

    # ── Construcción ─────────────────────────────────────────────────────────
    def _card(self, title: str):
        """Tarjeta con borde y título centrado: el mismo estilo que "Contenedor de salida"
        y "Opciones de video" de las otras páginas (UpscaleIAPanel._card)."""
        frame = QFrame(self)
        frame.setObjectName("advancedCard")
        set_themed_style(frame, lambda: f"""
            QFrame#advancedCard {{
                background-color: transparent;
                border: 1px solid {get_theme_token('borde_sutil', '#2d2d2d')};
                border-radius: 6px;
            }}
        """)
        frame.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        v = QVBoxLayout(frame)
        v.setContentsMargins(12, 10, 12, 12)
        v.setSpacing(8)
        lbl = QLabel(title, frame)
        lbl.setObjectName("sectionTitle")
        lbl.setAlignment(Qt.AlignCenter)
        v.addWidget(lbl)
        return frame, v

    def _row(self, layout, title, widget, trailing=None, expand=True):
        row = QHBoxLayout()
        label = QLabel(title)
        self._row_labels.append(label)
        row.addWidget(label)
        if expand:
            widget.setSizePolicy(QSizePolicy.Expanding, widget.sizePolicy().verticalPolicy())
            row.addWidget(widget, 1)
        else:
            # Controles de tamaño fijo (los botones de color): pegados a la etiqueta.
            row.addWidget(widget)
            row.addStretch(1)
        if trailing is not None:
            row.addWidget(trailing)
        layout.addLayout(row)
        return widget

    def _combo(self, layout, title, trailing=None):
        return self._row(layout, title, AutoPopupComboBox(fit_contents=True), trailing)

    def _align_labels(self):
        """Todas las etiquetas del mismo ancho, así cada control empieza a la misma altura
        horizontal (como la columna de etiquetas de los popovers). Con la fuente de cada
        etiqueta ya pulida: la del tema llega después de construir, por eso se repite al
        mostrarse y al cambiar el estilo o la fuente."""
        width = 0
        for label in self._row_labels:
            label.ensurePolished()
            width = max(width, QFontMetrics(label.font()).horizontalAdvance(label.text()))
        for label in self._row_labels:
            label.setFixedWidth(width + 8)

    def showEvent(self, event):
        super().showEvent(event)
        self._align_labels()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.StyleChange, QEvent.FontChange):
            self._align_labels()

    # ── Modo y formato ───────────────────────────────────────────────────────
    def current_mode(self) -> str:
        buttons = self.mode_selector.buttons
        return _MODE_TEXT if len(buttons) > 1 and buttons[1].isChecked() else _MODE_SUBTITLES

    def _fill_formats(self):
        mode = self.current_mode()
        self.output.blockSignals(True)
        self.output.clear()
        for key, label in (_TEXT_FORMATS if mode == _MODE_TEXT else _SUBTITLE_FORMATS):
            self.output.addItem(label, key)
        self.output.setCurrentIndex(max(0, self.output.findData(self._format_by_mode[mode])))
        self.output.blockSignals(False)
        self.subtitle_options.setVisible(mode == _MODE_SUBTITLES)
        self.text_options.setVisible(mode == _MODE_TEXT)
        self._update_output_controls()

    def _mode_changed(self, *_):
        self._fill_formats()
        self.refresh()

    def _output_changed(self, *_):
        if self.output.currentData():
            self._format_by_mode[self.current_mode()] = self.output.currentData()
        self._update_output_controls()
        self.refresh()

    def _update_output_controls(self):
        """Qué opciones tienen sentido con el formato y el destino elegidos."""
        subtitles = self.current_mode() == _MODE_SUBTITLES
        fmt = self.output.currentData()
        burn = subtitles and self.embed.currentData() == "burn"
        # Al quemar siempre se dibuja un ASS con el estilo: el formato no aplica.
        self.output.setEnabled(not burn)
        karaoke_ok = burn or fmt in KARAOKE_FORMATS
        self.split.model().item(self.split.findData("karaoke")).setEnabled(karaoke_ok)
        if not karaoke_ok and self.split.currentData() == "karaoke":
            self.split.setCurrentIndex(self.split.findData("sentences"))
        # LRC es una línea por verso: no tiene sentido partirla en dos.
        self.max_lines.setEnabled(burn or fmt != "lrc")
        styled = subtitles and (burn or fmt == "ass")
        self.style_card.setVisible(styled)
        self.karaoke_row.setVisible(self.split.currentData() == "karaoke")
        self.words_row.setVisible(self.split.currentData() == "words")
        self.font_row.setVisible(self._font_applies())
        self.style_note.setVisible(subtitles and self.embed.currentData() == "track")

    def _font_applies(self) -> bool:
        """La fuente elegida llega al resultado: al quemar, o en una pista ASS (que en MKV
        lleva la fuente adjunta)."""
        if self.current_mode() != _MODE_SUBTITLES:
            return False
        embed = self.embed.currentData()
        return embed == "burn" or (embed == "track" and self.output.currentData() == "ass")

    # ── Estilo ───────────────────────────────────────────────────────────────
    def _color_button(self, color):
        button = QPushButton()
        button.setFixedSize(56, 26)
        button.setCursor(Qt.PointingHandCursor)
        button.setProperty("color", color)
        self._paint_color(button)
        button.clicked.connect(lambda: self._pick_color(button))
        return button

    def _paint_color(self, button):
        color = button.property("color")
        button.setStyleSheet(apply_shapes(
            f"QPushButton {{ background-color: {color}; border: 1px solid #555555; border-radius: 4px; }}"))
        button.setAccessibleName(color)

    def _pick_color(self, button):
        # El mismo selector que la marca de agua y las etiquetas de Herramientas Multimedia.
        from gui.dialogs.dialogs import AdobeColorPickerDialog
        dialog = AdobeColorPickerDialog(button.property("color"), self)
        if dialog.exec():
            button.setProperty("color", QColor(dialog.get_color()).name().upper())
            self._paint_color(button)
            self.refresh()

    def _style_font_file(self):
        """Archivo de la fuente si es una de las de DowP (para quemar; ver
        transcription_engine._font_folder). Las del sistema no hace falta pasarlas."""
        family = self.style_font.currentData()
        if family not in get_available_fonts():
            return ""
        try:
            return get_static_font_path(family, 700 if self.style_bold.isChecked() else 400) or ""
        except Exception:
            return ""

    # ── Detección de voz (VAD) ───────────────────────────────────────────────
    def _ms_spin(self, low, high, step, tooltip):
        spin = QSpinBox()
        spin.setRange(low, high)
        spin.setSingleStep(step)
        spin.setSuffix(" ms")
        spin.setToolTip(tooltip)
        return spin

    def _set_vad_values(self, values):
        self.vad_threshold.setValue(values["threshold"])
        self.vad_min_silence.setValue(values["min_silence_ms"])
        self.vad_min_speech.setValue(values["min_speech_ms"])
        self.vad_pad.setValue(values["pad_ms"])
        self.vad_max_speech.setValue(int(values["max_speech_s"]))

    def _vad_preset_changed(self, *_):
        preset = self.vad_preset.currentData()
        # Al pasar a Personalizada se parte de los valores del nivel que estaba elegido.
        if preset == "custom" and self._last_vad_preset in VAD_PRESETS:
            self._set_vad_values(VAD_PRESETS[self._last_vad_preset])
        self._last_vad_preset = preset
        self._update_vad_controls()
        self.refresh()

    def _update_vad_controls(self):
        on = self.vad.isChecked()
        self.vad_preset.setEnabled(on)
        self.vad_custom.setVisible(on and self.vad_preset.currentData() == "custom")

    def _vad_toggled(self, checked):
        key = model_download_key(VAD_DOWNLOAD_INFO)
        if checked and not setup.vad_ready() and not model_downloads().is_downloading(key):
            if confirm_model_download(self, self.tr("Detector de voz (Silero)"), VAD_MODEL["size_bytes"]):
                if model_downloads().start(key, setup.download_vad, VAD_MODEL):
                    self._started.add(key)
            else:
                self.vad.blockSignals(True)
                self.vad.setChecked(False)
                self.vad.blockSignals(False)
        self._update_vad_controls()
        self.refresh()

    def not_ready_reason(self) -> str:
        """Por qué todavía no se puede iniciar (texto para el botón Iniciar)."""
        if not setup.runtime_ready():
            return self.tr("Descarga el motor whisper.cpp y el modelo.")
        if not self.info() or not setup.model_ready(self.info()):
            return self.tr("Elige un modelo de transcripción descargado.")
        if self.vad.isChecked() and not setup.vad_ready():
            return self.tr("Falta el detector de voz para saltar silencios.")
        return self.tr("Descarga el motor whisper.cpp y el modelo.")

    def _open_runtime_settings(self):
        from gui.tabs.settings.settings_view import SETTINGS_PAGE_DEPENDENCIES
        overlay = getattr(self.window(), "settings_overlay", None)
        if overlay is not None:
            overlay.open_page(SETTINGS_PAGE_DEPENDENCIES)
            overlay.settings_tab.page_deps.focus_dependency("whisper")

    def _refresh_model_items(self):
        refresh_whisper_model_icons(self.model)

    def _models_changed(self):
        self._refresh_model_items()
        self.refresh()

    def set_audio_tracks(self, streams):
        selected = self.track.currentData()
        self.track.blockSignals(True)
        self.track.clear()
        self.track.addItem(self.tr("Todas (un archivo por pista)"), "all")
        for index, stream in enumerate(streams or [{}]):
            details = " · ".join(str(stream.get(key)) for key in ("language", "codec", "channel_layout") if stream.get(key))
            self.track.addItem(self.tr("Pista {0}").format(index + 1) + (" · " + details if details else ""), index)
        if selected != "all" and isinstance(selected, int) and self.track.findData(selected) < 0:
            self.track.addItem(self.tr("Pista {0} (no está en este archivo)").format(selected + 1), selected)
        self.track.setCurrentIndex(max(0, self.track.findData(selected)))
        self.track.blockSignals(False)

    def _model_changed(self, *_):
        info = self.info() or {}
        english = info.get("english_only", False)
        if english:
            self.language.setCurrentIndex(self.language.findData("en"))
        self.language.setEnabled(not english)
        # "Traducir a inglés" solo aparece si el modelo traduce (no Turbo ni los .en).
        translate = info.get("translate", False)
        if not translate:
            self.task.setCurrentIndex(0)
        self.task.view().setRowHidden(1, not translate)
        self.refresh()

    def _offer_download(self, *_):
        ident = self.model.currentData()
        info = self.info()
        if info and not setup.runtime_ready():
            # Sin motor: un solo diálogo con el motor (y la opción NVIDIA) y este modelo.
            from gui.widgets.ia_preset_models import offer_preset_model_download
            QTimer.singleShot(0, lambda: offer_preset_model_download(self, self.get_settings())
                              if self.model.currentData() == ident else None)
            return
        if info and not setup.model_ready(info) and not model_downloads().is_downloading(model_download_key(info)):
            QTimer.singleShot(0, lambda: self._download() if self.model.currentData() == ident else None)

    def info(self):
        return WHISPER_MODELS.get(self.model.currentData())

    def refresh(self, *_):
        info = self.info()
        key = model_download_key(info or {})
        manager = model_downloads()
        busy = manager.is_downloading(key)
        installed = setup.model_ready(info)
        self.actions.set_delete_enabled(installed and not busy)
        if busy:
            self.status.show_progress(manager.progress(key))
        elif installed:
            self.status.show_ready(self.tr("Modelo listo para usar."))
        elif info:
            self.status.show_missing(self.tr("No descargado — vuelve a elegirlo en la lista para descargarlo."))
        else:
            self.status.clear()
        self.runtime_toggle.setToolTip(self.tr("Configurar motor") if setup.runtime_ready() else self.tr("Instalar motor whisper.cpp"))
        self.selection_changed.emit()

    def _download(self):
        info = self.info()
        if info and confirm_model_download(self, info["id"], info["size_bytes"]):
            key = model_download_key(info)
            if model_downloads().start(key, setup.download_model, info):
                self._started.add(key)

    def _delete(self):
        info = self.info()
        if info and QMessageBox.question(self, self.tr("Eliminar modelo"), self.tr("¿Eliminar '{0}' del disco?").format(info["id"])) == QMessageBox.Yes:
            if not setup.delete_model(info):
                QMessageBox.warning(self, self.tr("Eliminar modelo"), self.tr("No se pudo eliminar el modelo."))
            model_downloads().models_changed.emit()

    def _finished(self, success, message, key):
        self._refresh_model_items()
        if key in self._started:
            self._started.discard(key)
            if not success:
                QMessageBox.warning(self, self.tr("Error de descarga"), message)
        self.refresh()

    def is_valid_selection(self):
        return bool(self.info())

    def is_ready(self):
        manager = model_downloads()
        return (setup.settings_ready(self.get_settings()) and
                not manager.is_downloading(model_download_key(self.info() or {})) and
                not manager.is_downloading(model_download_key(setup.ENGINE_INFO)) and
                not (self.vad.isChecked() and manager.is_downloading(model_download_key(VAD_DOWNLOAD_INFO))))

    def get_settings(self):
        font_applies = self._font_applies()
        return {"ia_function": "transcription", "transcription_engine": "whisper.cpp",
                "transcription_model": self.model.currentData(),
                "transcription_audio_track": self.track.currentData(),
                "transcription_language": self.language.currentData(), "transcription_task": self.task.currentData(),
                "transcription_device": "auto" if self.check_gpu.isChecked() else "cpu",
                "transcription_threads": self.threads.value(),
                "transcription_mode": self.current_mode(),
                "container": self.output.currentData(),
                "transcription_max_chars": self.max_chars.value(),
                "transcription_max_lines": self.max_lines.currentData(),
                "transcription_split": self.split.currentData(),
                "transcription_max_words": self.max_words.value(),
                "transcription_text_layout": self.text_layout.currentData(),
                "transcription_timestamps": self.timestamps.isChecked(),
                "transcription_prompt": self.prompt.text().strip(),
                "transcription_vad": self.vad.isChecked(),
                "transcription_vad_preset": self.vad_preset.currentData(),
                "transcription_vad_threshold": round(self.vad_threshold.value(), 2),
                "transcription_vad_min_silence_ms": self.vad_min_silence.value(),
                "transcription_vad_min_speech_ms": self.vad_min_speech.value(),
                "transcription_vad_pad_ms": self.vad_pad.value(),
                "transcription_vad_max_speech_s": self.vad_max_speech.value(),
                "transcription_embed": self.embed.currentData(),
                # Si la fuente no llega al resultado (un ASS suelto), Arial: la que tiene casi
                # cualquier equipo, en vez de una que el reproductor no encuentre.
                "transcription_style_font": self.style_font.currentData() if font_applies else "Arial",
                "transcription_style_font_file": self._style_font_file() if font_applies else "",
                "transcription_style_size": self.style_size.value(),
                "transcription_style_position": self.style_position.currentData(),
                "transcription_style_color": self.style_color.property("color"),
                "transcription_style_outline": self.style_outline.property("color"),
                "transcription_style_karaoke_color": self.style_karaoke.property("color"),
                "transcription_style_bold": self.style_bold.isChecked(),
                "transcription_style_box": self.style_box.isChecked()}
