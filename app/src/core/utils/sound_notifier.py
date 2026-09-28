# src/core/utils/sound_notifier.py
"""Sonido al terminar un proceso (éxito o error), configurable en Ajustes > General.

Las pestañas solo AVISAN qué pasó; qué suena y cuándo se decide aquí, en un solo
sitio:

  - item_finished(source, ok): terminó un elemento (una descarga con su
    posprocesado, una recodificación, una imagen).
  - group_finished(source): esa pestaña ya no tiene nada corriendo ni pendiente.
  - single_finished(source, ok): proceso de un solo elemento (Proceso Avanzado en
    modo SOLO), donde "elemento" y "grupo" son lo mismo -- suena una vez.
  - discard(source): el usuario canceló; lo acumulado de esa pestaña no suena.

Según "Cuándo sonar" (notify_sound_when):
  - "group": un sonido al terminar todo -- de error si falló algún elemento.
  - "item": un sonido por elemento.
  - "both": por elemento, y al terminar todo; si el último elemento y el fin del
    grupo llegan juntos suena solo el del grupo (no dos seguidos).

Los elementos que terminan casi a la vez (ej. 20 descargas en el mismo segundo)
se agrupan en un solo sonido. No suena nada por las cancelaciones.

Reproducción con QSoundEffect (baja latencia, no bloquea), que solo acepta WAV sin
comprimir: por eso los sonidos propios del usuario se convierten a WAV 16 bits al
importarlos (import_custom_sound), con el FFmpeg que ya trae DowP.

Sonidos predeterminados (assets/audio), ambos CC0 de Freesound:
  - dowp_bass_pass.wav: "Electric bass guitar loop 2 bpm 110", josefpres
    (https://freesound.org/people/josefpres/sounds/483145/)
  - dowp_bass_fail.wav: "bass suspended chord 2", CVLTIV8R
    (https://freesound.org/people/CVLTIV8R/sounds/799096/)
"""
import os
import subprocess
import time
import wave

from PySide6.QtCore import QObject, QTimer, QUrl

from core.logger.logger_manager import logger
from core.utils.config_manager import get_config, save_config
from core.utils.paths import get_app_data_dir, get_src_dir

SOURCE_QUICK = "quick"
SOURCE_ADVANCED = "advanced"
SOURCE_ADVANCED_SOLO = "advanced_solo"
SOURCE_VIDEO_TOOLS = "video_tools"
SOURCE_IMAGE_TOOLS = "image_tools"

KIND_SUCCESS = "success"
KIND_ERROR = "error"

WHEN_GROUP = "group"
WHEN_ITEM = "item"
WHEN_BOTH = "both"

# Claves de config (valores por defecto en config_manager.py).
CFG_ENABLED = "notify_sound_enabled"
CFG_WHEN = "notify_sound_when"
CFG_VOLUME = "notify_sound_volume"
CFG_CUSTOM = {KIND_SUCCESS: "notify_sound_success", KIND_ERROR: "notify_sound_error"}
CFG_CUSTOM_NAME = {KIND_SUCCESS: "notify_sound_success_name", KIND_ERROR: "notify_sound_error_name"}

# Límites para los sonidos propios del usuario.
ALLOWED_EXTENSIONS = (".wav", ".mp3", ".ogg")
MAX_SIZE_BYTES = 2 * 1024 * 1024
MAX_DURATION_SEC = 10.0

_DEFAULT_FILES = {KIND_SUCCESS: "dowp_bass_pass.wav", KIND_ERROR: "dowp_bass_fail.wav"}

# Elementos que terminan dentro de esta ventana suenan una sola vez.
_ITEM_COALESCE_MS = 350
# Mismo sonido repetido antes de este intervalo: se omite.
_MIN_REPEAT_SEC = 0.4


def get_custom_sounds_dir() -> str:
    path = os.path.join(get_app_data_dir(), "sounds")
    os.makedirs(path, exist_ok=True)
    return path


def default_sound_path(kind: str) -> str:
    return os.path.join(get_src_dir(), "assets", "audio", _DEFAULT_FILES[kind])


def active_sound_path(kind: str) -> str:
    """El sonido propio del usuario si hay uno válido; si no, el predeterminado."""
    custom = get_config().get(CFG_CUSTOM[kind], "")
    if custom and os.path.isfile(custom):
        return custom
    return default_sound_path(kind)


def import_custom_sound(src_path: str, kind: str) -> tuple[bool, str]:
    """Valida el archivo elegido por el usuario y lo convierte a WAV 16 bits dentro de
    la carpeta de datos de DowP (así sigue funcionando aunque el original se mueva o
    se borre). Devuelve (ok, motivo) -- el motivo es un código para que la UI muestre
    el texto traducido: "ext", "size", "ffmpeg", "convert", "duration"."""
    from core.setup.ffmpeg_setup import get_ffmpeg_path

    ext = os.path.splitext(src_path)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False, "ext"
    try:
        if os.path.getsize(src_path) > MAX_SIZE_BYTES:
            return False, "size"
    except OSError:
        return False, "convert"

    ffmpeg = get_ffmpeg_path()
    if not ffmpeg or not os.path.isfile(ffmpeg):
        return False, "ffmpeg"

    dest = os.path.join(get_custom_sounds_dir(), f"custom_{kind}.wav")
    tmp = dest + ".tmp.wav"
    cmd = [ffmpeg, "-y", "-v", "error", "-i", src_path, "-vn",
           "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", tmp]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30, creationflags=flags)
        if res.returncode != 0 or not os.path.isfile(tmp):
            logger.warning(f"SoundNotifier: FFmpeg no pudo convertir '{src_path}': {res.stderr.strip()[:300]}")
            _silent_remove(tmp)
            return False, "convert"
        with wave.open(tmp, "rb") as w:
            duration = w.getnframes() / float(w.getframerate() or 1)
        if duration > MAX_DURATION_SEC:
            _silent_remove(tmp)
            return False, "duration"
        os.replace(tmp, dest)
    except Exception as e:
        logger.warning(f"SoundNotifier: error importando '{src_path}': {e}")
        _silent_remove(tmp)
        return False, "convert"

    config = get_config()
    config[CFG_CUSTOM[kind]] = dest
    config[CFG_CUSTOM_NAME[kind]] = os.path.basename(src_path)
    save_config(config)
    get_sound_notifier().reload()
    logger.info(f"SoundNotifier: sonido de {kind} personalizado: '{os.path.basename(src_path)}' ({duration:.1f} s)")
    return True, ""


def reset_custom_sound(kind: str) -> None:
    """Vuelve al sonido predeterminado y borra la copia convertida."""
    config = get_config()
    _silent_remove(config.get(CFG_CUSTOM[kind], ""))
    config[CFG_CUSTOM[kind]] = ""
    config[CFG_CUSTOM_NAME[kind]] = ""
    save_config(config)
    get_sound_notifier().reload()
    logger.info(f"SoundNotifier: sonido de {kind} restablecido al predeterminado.")


def _silent_remove(path: str) -> None:
    try:
        if path and os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


class SoundNotifier(QObject):
    """Vive en el hilo principal: las pestañas lo llaman desde sus slots de Qt."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._effects = {}           # kind -> QSoundEffect (se crean al primer uso)
        self._effect_paths = {}      # kind -> ruta cargada en ese efecto
        self._stats = {}             # source -> {"count": n, "failed": n}
        self._pending_item = {}      # source -> {"timer": QTimer, "failed": bool}
        self._last_played = (None, 0.0)

    # ── API para las pestañas ────────────────────────────────────────────────
    def item_finished(self, source: str, ok: bool) -> None:
        stats = self._stats.setdefault(source, {"count": 0, "failed": 0})
        stats["count"] += 1
        if not ok:
            stats["failed"] += 1
        if not self._enabled() or self._when() == WHEN_GROUP:
            return
        pending = self._pending_item.get(source)
        if pending:
            pending["failed"] = pending["failed"] or not ok
            return
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda s=source: self._fire_pending_item(s))
        self._pending_item[source] = {"timer": timer, "failed": not ok}
        timer.start(_ITEM_COALESCE_MS)

    def group_finished(self, source: str) -> None:
        stats = self._stats.pop(source, None)
        if not stats or stats["count"] == 0:
            return  # nada terminó en esta tanda (ej. se inició una cola vacía)
        if not self._enabled():
            return
        when = self._when()
        if when == WHEN_ITEM:
            return
        # "Ambos": el último elemento y el fin del grupo llegan casi juntos -- suena
        # solo el del grupo.
        self._cancel_pending_item(source)
        self.play(KIND_ERROR if stats["failed"] else KIND_SUCCESS)

    def single_finished(self, source: str, ok: bool) -> None:
        self._stats.pop(source, None)
        self._cancel_pending_item(source)
        if self._enabled():
            self.play(KIND_SUCCESS if ok else KIND_ERROR)

    def discard(self, source: str) -> None:
        self._stats.pop(source, None)
        self._cancel_pending_item(source)

    # ── Reproducción ─────────────────────────────────────────────────────────
    def play(self, kind: str, force: bool = False) -> None:
        """force=True es para el botón "Probar" de Ajustes (suena aunque esté
        desactivado y aunque acabe de sonar)."""
        now = time.monotonic()
        last_kind, last_time = self._last_played
        if not force and last_kind == kind and now - last_time < _MIN_REPEAT_SEC:
            return
        effect = self._effect_for(kind)
        if effect is None:
            return
        effect.setVolume(max(0.0, min(1.0, get_config().get(CFG_VOLUME, 70) / 100.0)))
        for other in self._effects.values():
            if other is not effect and other.isPlaying():
                other.stop()
        self._last_played = (kind, now)
        if effect.isLoaded():
            effect.stop()
            effect.play()
            return
        # QSoundEffect carga en segundo plano: la primera vez que suena un sonido
        # (o tras cambiarlo) todavía no está listo -- se reproduce al terminar de cargar.
        from PySide6.QtMultimedia import QSoundEffect

        def _on_status():
            if effect.status() == QSoundEffect.Status.Ready:
                effect.statusChanged.disconnect(_on_status)
                effect.play()
            elif effect.status() == QSoundEffect.Status.Error:
                effect.statusChanged.disconnect(_on_status)
                logger.warning(f"SoundNotifier: no se pudo cargar el sonido de {kind}.")

        effect.statusChanged.connect(_on_status)

    def reload(self) -> None:
        """Tras cambiar un sonido en Ajustes: se vuelve a cargar al próximo uso."""
        for effect in self._effects.values():
            effect.stop()
            effect.deleteLater()
        self._effects.clear()
        self._effect_paths.clear()

    # ── Internos ─────────────────────────────────────────────────────────────
    def _enabled(self) -> bool:
        return bool(get_config().get(CFG_ENABLED, True))

    def _when(self) -> str:
        when = get_config().get(CFG_WHEN, WHEN_GROUP)
        return when if when in (WHEN_GROUP, WHEN_ITEM, WHEN_BOTH) else WHEN_GROUP

    def _fire_pending_item(self, source: str) -> None:
        pending = self._pending_item.pop(source, None)
        if pending:
            pending["timer"].deleteLater()
            self.play(KIND_ERROR if pending["failed"] else KIND_SUCCESS)

    def _cancel_pending_item(self, source: str) -> None:
        pending = self._pending_item.pop(source, None)
        if pending:
            pending["timer"].stop()
            pending["timer"].deleteLater()

    def _effect_for(self, kind: str):
        path = active_sound_path(kind)
        if not os.path.isfile(path):
            logger.warning(f"SoundNotifier: no existe el sonido '{path}'.")
            return None
        effect = self._effects.get(kind)
        if effect is not None and self._effect_paths.get(kind) == path:
            return effect
        try:
            from PySide6.QtMultimedia import QSoundEffect
        except ImportError as e:
            logger.warning(f"SoundNotifier: QtMultimedia no disponible, sin sonidos: {e}")
            return None
        if effect is not None:
            effect.deleteLater()
        effect = QSoundEffect(self)
        effect.setSource(QUrl.fromLocalFile(path))
        self._effects[kind] = effect
        self._effect_paths[kind] = path
        return effect


_instance = None


def get_sound_notifier() -> SoundNotifier:
    global _instance
    if _instance is None:
        _instance = SoundNotifier()
    return _instance
