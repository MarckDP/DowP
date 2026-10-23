"""Diálogo único "Crear subtítulos: falta descargar".

whisper.cpp es una dependencia opcional: no se instala con DowP, solo cuando alguien
quiere crear subtítulos. En ese momento (Herramientas IA > Transcripción, Proceso
Avanzado > Subtítulos > Crear con IA, o la tarjeta de Dependencias) este diálogo junta
en una sola pregunta todo lo que falta, en vez de encadenar dos o tres:

- el motor, con la aceleración por GPU que admita el equipo (ver whisper_setup.detect_gpu):
  Vulkan recomendada (cualquier GPU, ~15 MB; decisión del usuario) y, con NVIDIA, CUDA como
  alternativa oficial más pesada; "Solo CPU" siempre está. En macOS el motor ya acelera
  (Metal o Accelerate) y no hay elección;
- el modelo de Whisper elegido;
- el detector de voz, si los ajustes usan "Saltar silencios".

Lo que nadie probó en equipos reales (Vulkan con AMD o Intel, Linux, macOS) va marcado
"Beta": si falla, la transcripción se repite por CPU sola. Siempre pregunta.

Con missing={"accel_only": True} (motor ya instalado) solo ofrece la aceleración.
"""
from PySide6.QtCore import QCoreApplication, Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QDialog, QDialogButtonBox, QFrame, QLabel, QPushButton, QRadioButton,
                               QSizePolicy, QVBoxLayout, QHBoxLayout)

from core.setup import whisper_setup as setup
from core.utils.cache_manager import format_bytes
from core.whisper_catalog import WHISPER_MODELS, VAD_MODEL, VAD_DOWNLOAD_INFO
from gui.styles import get_theme_token, set_themed_style
from gui.widgets.model_download_prompt import model_downloads, model_download_key




def missing_downloads(settings: dict | None) -> dict:
    """Qué falta para transcribir con estos ajustes (y no se está bajando ya)."""
    settings = settings or {}
    manager = model_downloads()
    info = WHISPER_MODELS.get(settings.get("transcription_model"))
    engine_key = model_download_key(setup.ENGINE_INFO)
    return {
        "engine": not setup.runtime_ready() and not manager.is_downloading(engine_key),
        "model": info if info and not setup.model_ready(info)
        and not manager.is_downloading(model_download_key(info)) else None,
        "vad": bool(settings.get("transcription_vad")) and not setup.vad_ready()
        and not manager.is_downloading(model_download_key(VAD_DOWNLOAD_INFO)),
    }


def downloads_in_progress(settings: dict | None) -> bool:
    settings = settings or {}
    manager = model_downloads()
    keys = [model_download_key(setup.ENGINE_INFO), model_download_key(VAD_DOWNLOAD_INFO)]
    info = WHISPER_MODELS.get(settings.get("transcription_model"))
    if info:
        keys.append(model_download_key(info))
    return any(manager.is_downloading(key) for key in keys)


def _base_size():
    asset = setup.runtime_asset()
    return asset["size"] if asset else 0


class WhisperDownloadDialog(QDialog):
    def __init__(self, parent, missing: dict, engine_only_title: bool = False):
        super().__init__(parent)
        self._missing = missing
        accel_only = bool(missing.get("accel_only"))
        self.setWindowTitle(QCoreApplication.translate("WhisperDownloadDialog", "Motor de transcripción") if (engine_only_title or accel_only)
                            else QCoreApplication.translate("WhisperDownloadDialog", "Crear subtítulos"))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        title = QLabel(QCoreApplication.translate("WhisperDownloadDialog", "Acelerar la transcripción con la GPU:") if accel_only
                       else QCoreApplication.translate("WhisperDownloadDialog", "Para crear subtítulos falta descargar:"))
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(title)
        self._accel_choices = []
        self._cpu_choice = None
        self._group = QButtonGroup(self)

        if missing.get("engine") or accel_only:
            box, bl = self._section(QCoreApplication.translate("WhisperDownloadDialog", "Aceleración por GPU") if accel_only
                                    else QCoreApplication.translate("WhisperDownloadDialog", "Motor whisper.cpp"))
            base = setup.runtime_asset()
            gpu = setup.detect_gpu()
            if base and base.get("beta") and not accel_only:
                # macOS: el motor de dowp-runtimes ya acelera; no hay nada que elegir.
                kind = QCoreApplication.translate("WhisperDownloadDialog", "Metal (GPU)") if "metal" in base["name"] \
                    else QCoreApplication.translate("WhisperDownloadDialog", "CPU con Accelerate")
                bl.addWidget(self._line(QCoreApplication.translate("WhisperDownloadDialog", "Motor ({0})").format(kind), format_bytes(base["size"])))
                bl.addWidget(self._note(self._beta_text()))
            else:
                if gpu:
                    gpu_name = gpu["name"] + (f" ({gpu['vram_mb'] // 1024} GB)" if gpu["vram_mb"] else "")
                    detected = (QCoreApplication.translate("WhisperDownloadDialog", "Se detectó: {0} · driver {1}").format(gpu_name, gpu["driver"])
                                if gpu["driver"] else QCoreApplication.translate("WhisperDownloadDialog", "Se detectó: {0}").format(gpu_name))
                    bl.addWidget(self._note(detected))
                    if gpu["vendor"] == "NVIDIA" and gpu["driver"] and not gpu["cuda"] and not gpu["vulkan"]:
                        bl.addWidget(self._note(QCoreApplication.translate("WhisperDownloadDialog",
                            "Se detectó {0}, pero su driver ({1}) es antiguo para usar la GPU. "
                            "Actualízalo para poder acelerar la transcripción.").format(gpu["name"], gpu["driver"])))
                for position, variant in enumerate(gpu["options"] if gpu else []):
                    self._add_accel_choice(bl, variant, position == 0, accel_only, gpu)
                if not accel_only:
                    if self._accel_choices:
                        self._cpu_choice = self._radio(bl, QCoreApplication.translate("WhisperDownloadDialog", "Solo CPU"), format_bytes(_base_size()),
                                                       QCoreApplication.translate("WhisperDownloadDialog", "Funciona en cualquier equipo."))
                    else:
                        bl.addWidget(self._line(QCoreApplication.translate("WhisperDownloadDialog", "Motor (CPU)"), format_bytes(_base_size())))
                if self._accel_choices:
                    self._accel_choices[0].setChecked(True)
            layout.addWidget(box)

        if missing.get("model") or missing.get("vad"):
            box, bl = self._section(QCoreApplication.translate("WhisperDownloadDialog", "Modelos"))
            if missing.get("model"):
                bl.addWidget(self._line(QCoreApplication.translate("WhisperDownloadDialog", "Modelo {0}").format(missing["model"]["id"]),
                                        format_bytes(missing["model"]["size_bytes"])))
            if missing.get("vad"):
                bl.addWidget(self._line(QCoreApplication.translate("WhisperDownloadDialog", "Detector de voz (Silero)"), format_bytes(VAD_MODEL["size_bytes"])))
            layout.addWidget(box)

        self.lbl_total = QLabel()
        self.lbl_total.setAlignment(Qt.AlignRight)
        self.lbl_total.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.lbl_total)
        layout.addWidget(self._note(QCoreApplication.translate("WhisperDownloadDialog", "Se descarga una sola vez y se verifica antes de instalarse.")))
        buttons = QDialogButtonBox(self)
        self.btn_download = buttons.addButton(QCoreApplication.translate("WhisperDownloadDialog", "Descargar"), QDialogButtonBox.AcceptRole)
        buttons.addButton(QCoreApplication.translate("WhisperDownloadDialog", "Cancelar"), QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._group.buttonToggled.connect(lambda *_: self._update_total())
        self._update_total()
        self.setMinimumWidth(500)

    # ── Construcción ─────────────────────────────────────────────────────────
    @staticmethod
    def _beta_text():
        return QCoreApplication.translate("WhisperDownloadDialog",
            "Beta: compilación sin probar todavía en equipos como este. Si falla, DowP repite "
            "la transcripción por CPU automáticamente.")

    def _add_accel_choice(self, layout, variant, recommended, accel_only, gpu):
        asset = setup.accel_asset(variant)
        if not asset:
            return
        label = setup.ACCEL_VARIANTS[variant]["label"]
        if accel_only:
            title = QCoreApplication.translate("WhisperDownloadDialog", "Aceleración por GPU ({0})").format(label)
            size = format_bytes(asset["size"])
        else:
            title = QCoreApplication.translate("WhisperDownloadDialog", "CPU + aceleración por GPU ({0})").format(label)
            size = f"{format_bytes(_base_size())} + {format_bytes(asset['size'])}"
        details = [QCoreApplication.translate("WhisperDownloadDialog", "Recomendado: mucho más rápido.") if recommended
                   else QCoreApplication.translate("WhisperDownloadDialog", "Alternativa: paquete oficial de NVIDIA, más pesado.")]
        if variant == "vulkan":
            details.append(QCoreApplication.translate("WhisperDownloadDialog",
                "La primera transcripción tarda más: el driver prepara la GPU una sola vez."))
        if setup.accel_is_beta(variant, gpu):
            details.append(self._beta_text())
        radio = self._radio(layout, title, size, " ".join(details))
        radio.setProperty("variant", variant)
        self._accel_choices.append(radio)

    def _section(self, title):
        box = QFrame(self)
        box.setObjectName("whisperDownloadSection")
        set_themed_style(box, lambda: f"QFrame#whisperDownloadSection {{ border: 1px solid "
                                      f"{get_theme_token('borde_sutil', '#2d2d2d')}; border-radius: 6px; }}")
        v = QVBoxLayout(box)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)
        label = QLabel(title)
        label.setStyleSheet("font-weight: bold;")
        v.addWidget(label)
        return box, v

    def _note(self, text):
        label = QLabel(text)
        label.setWordWrap(True)
        set_themed_style(label, lambda: f"color: {get_theme_token('texto_tenue', '#888888')}; font-size: 11px;")
        return label

    def _line(self, text, size):
        row = QFrame(self)
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(QLabel(text), 1)
        h.addWidget(QLabel(size))
        return row

    def _radio(self, layout, text, size, detail):
        radio = QRadioButton(f"{text}  ·  {size}")
        self._group.addButton(radio)
        layout.addWidget(radio)
        hint = self._note(detail)
        hint.setContentsMargins(26, 0, 0, 0)
        layout.addWidget(hint)
        return radio

    # ── Resultado ────────────────────────────────────────────────────────────
    def selected_accel(self):
        return next((r.property("variant") for r in self._accel_choices if r.isChecked()), None)

    def engine_variants(self) -> list:
        """Lo que hay que instalar: "cpu" (el motor base) y/o la aceleración elegida."""
        accel = self.selected_accel()
        if self._missing.get("accel_only"):
            return [accel] if accel else []
        return ["cpu"] + ([accel] if accel else [])

    def _update_total(self):
        total = 0
        if self._missing.get("engine") or self._missing.get("accel_only"):
            for variant in self.engine_variants():
                total += _base_size() if variant == "cpu" else (setup.accel_asset(variant) or {}).get("size", 0)
        if self._missing.get("model"):
            total += self._missing["model"]["size_bytes"]
        if self._missing.get("vad"):
            total += VAD_MODEL["size_bytes"]
        self.lbl_total.setText(QCoreApplication.translate("WhisperDownloadDialog", "Total: {0}").format(format_bytes(total)))
        self.btn_download.setEnabled(total > 0) if hasattr(self, "btn_download") else None


def start_downloads(missing: dict, variants: list) -> list:
    """Arranca lo que falta en el gestor de descargas compartido. Devuelve sus claves."""
    manager = model_downloads()
    started = []
    if (missing.get("engine") or missing.get("accel_only")) and variants:
        key = model_download_key(setup.ENGINE_INFO)
        if manager.start(key, setup.download_runtime, dict(setup.ENGINE_INFO, variants=variants)):
            started.append(key)
    if missing.get("model"):
        key = model_download_key(missing["model"])
        if manager.start(key, setup.download_model, missing["model"]):
            started.append(key)
    if missing.get("vad"):
        key = model_download_key(VAD_DOWNLOAD_INFO)
        if manager.start(key, setup.download_vad, VAD_MODEL):
            started.append(key)
    return started


def ask_transcription_downloads(parent, settings: dict | None) -> str:
    """"ready" si no falta nada; "downloading" si algo ya se está bajando; "started" si el
    usuario aceptó y arrancaron las descargas; "cancel" si no."""
    missing = missing_downloads(settings)
    if not any(missing.values()):
        return "downloading" if downloads_in_progress(settings) else "ready"
    dialog = WhisperDownloadDialog(parent, missing)
    if dialog.exec() != QDialog.Accepted:
        return "cancel"
    start_downloads(missing, dialog.engine_variants())
    return "started"


def ask_accel_download(parent) -> bool:
    """Motor ya instalado: ofrece solo la aceleración por GPU. True si arrancó la descarga."""
    missing = {"accel_only": True}
    dialog = WhisperDownloadDialog(parent, missing)
    if not dialog._accel_choices or dialog.exec() != QDialog.Accepted:
        return False
    return bool(start_downloads(missing, dialog.engine_variants()))


class WhisperEngineNotice(QFrame):
    """Aviso en línea, sin ventana emergente: "Para crear subtítulos hace falta el motor
    whisper.cpp · [Descargar…]". Mientras se descarga, muestra el progreso. Se oculta solo
    cuando el motor ya está. `get_settings` da los ajustes actuales (modelo, detector de
    voz) para que "Descargar…" ofrezca de una vez todo lo que falta."""

    visibility_changed = Signal(bool)

    def __init__(self, get_settings, parent=None):
        super().__init__(parent)
        self._get_settings = get_settings
        self.setObjectName("whisperEngineNotice")
        set_themed_style(self, lambda: f"QFrame#whisperEngineNotice {{ border: 1px solid "
                                       f"{get_theme_token('estado_aviso', '#FFC107')}; border-radius: 6px; }}")
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 6, 6)
        row.setSpacing(8)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        set_themed_style(self.label, lambda: f"color: {get_theme_token('texto_secundario', '#AAAAAA')}; font-size: 11px;")
        row.addWidget(self.label, 1)
        self.button = QPushButton(QCoreApplication.translate("WhisperDownloadDialog", "Descargar…"))
        self.button.setObjectName("secondaryButton")
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.clicked.connect(self._download)
        row.addWidget(self.button, 0, Qt.AlignVCenter)
        manager = model_downloads()
        for signal in (manager.started, manager.progress_changed, manager.finished, manager.models_changed):
            signal.connect(self.refresh)
        self._shown = None
        self.refresh()

    def _download(self):
        from gui.widgets.ia_preset_models import offer_preset_model_download
        settings = dict(self._get_settings() or {}, ia_function="transcription")
        offer_preset_model_download(self.window(), settings)
        self.refresh()

    def refresh(self, *_):
        manager = model_downloads()
        key = model_download_key(setup.ENGINE_INFO)
        if manager.is_downloading(key):
            self.label.setText(QCoreApplication.translate("WhisperDownloadDialog", "Descargando el motor whisper.cpp: {0}%").format(manager.progress(key)))
            self.button.hide()
            shown = True
        elif not setup.runtime_ready():
            self.label.setText(QCoreApplication.translate("WhisperDownloadDialog", "Para crear subtítulos hace falta el motor whisper.cpp (se descarga una sola vez)."))
            self.button.show()
            shown = True
        else:
            shown = False
        self.setVisible(shown)
        if shown != self._shown:
            self._shown = shown
            self.visibility_changed.emit(shown)


_GPU_HINT_DISMISSED = "whisper_gpu_hint_dismissed"


class WhisperGpuHint(QFrame):
    """Sugerencia discreta para quien ya tiene el motor base y una GPU sin la aceleración:
    "Se detectó …: instala la aceleración por GPU · [Instalar] [No mostrar más]". El
    diálogo único solo sale cuando falta el motor, así que sin esto quien instaló "Solo
    CPU" tenía que encontrar el botón en Ajustes > Dependencias. "No mostrar más" se
    recuerda; la sección de Dependencias sigue ofreciéndola."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("whisperGpuHint")
        set_themed_style(self, lambda: f"QFrame#whisperGpuHint {{ border: 1px solid "
                                       f"{get_theme_token('borde_sutil', '#2d2d2d')}; border-radius: 6px; }}")
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 6, 6)
        row.setSpacing(8)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        set_themed_style(self.label, lambda: f"color: {get_theme_token('texto_secundario', '#AAAAAA')}; font-size: 11px;")
        row.addWidget(self.label, 1)
        self.btn_add = QPushButton(QCoreApplication.translate("WhisperDownloadDialog", "Instalar"))
        self.btn_add.setObjectName("secondaryButton")
        self.btn_add.setCursor(Qt.PointingHandCursor)
        self.btn_add.clicked.connect(self._add)
        row.addWidget(self.btn_add, 0, Qt.AlignVCenter)
        self.btn_dismiss = QPushButton(QCoreApplication.translate("WhisperDownloadDialog", "No mostrar más"))
        self.btn_dismiss.setObjectName("secondaryButton")
        self.btn_dismiss.setCursor(Qt.PointingHandCursor)
        self.btn_dismiss.clicked.connect(self._dismiss)
        row.addWidget(self.btn_dismiss, 0, Qt.AlignVCenter)
        manager = model_downloads()
        for signal in (manager.started, manager.finished, manager.models_changed):
            signal.connect(self.refresh)
        self.refresh()

    def refresh(self, *_):
        from core.utils.config_manager import get_config
        show = False
        # Solo con el motor base instalado (por DowP, no el de Homebrew) y sin aceleración:
        # si falta el motor, el diálogo único ya la ofrece.
        if (setup.runtime_path() and not setup.runtime_is_homebrew() and not setup.accel_variant()
                and not get_config().get(_GPU_HINT_DISMISSED)
                and not model_downloads().is_downloading(model_download_key(setup.ENGINE_INFO))):
            gpu = setup.detect_gpu()
            variant = gpu["recommended"] if gpu else None
            asset = setup.accel_asset(variant) if variant else None
            if asset:
                text = QCoreApplication.translate(
                    "WhisperDownloadDialog", "Se detectó {0}: instala la aceleración por GPU ({1}) para transcribir "
                    "mucho más rápido · {2}.").format(gpu["name"], setup.ACCEL_VARIANTS[variant]["label"], format_bytes(asset["size"]))
                if setup.accel_is_beta(variant, gpu):
                    text += " " + QCoreApplication.translate("WhisperDownloadDialog", "(Beta)")
                self.label.setText(text)
                show = True
        self.setVisible(show)

    def _add(self):
        ask_accel_download(self.window())
        self.refresh()

    def _dismiss(self):
        from core.utils.config_manager import get_config, save_config
        config = get_config()
        config[_GPU_HINT_DISMISSED] = True
        save_config(config)
        self.refresh()
