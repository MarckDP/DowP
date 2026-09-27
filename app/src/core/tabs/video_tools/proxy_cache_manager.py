# src/core/tabs/video_tools/proxy_cache_manager.py
import os
import hashlib
import subprocess
from PySide6.QtCore import QObject, Signal, QRunnable, QThreadPool, QMutex, QMutexLocker

from core.logger.logger_manager import logger
from core.setup.ffmpeg_setup import get_ffmpeg_dir, get_platform_info, check_ffmpeg
from core.utils.paths import get_proxy_cache_dir

DEFAULT_MAX_CACHE_BYTES = 5 * 1024 * 1024 * 1024  # 5 GB

# "Divisor" especial: copia de previsualización a calidad completa que CONSERVA la
# transparencia. El reproductor de Qt no muestra el alfa de varios formatos aunque el
# archivo lo tenga (verificado con QVideoSink): VP8/VP9 (usa el decodificador nativo de
# ffmpeg, que descarta la capa alfa aparte de WebM), ProRes 4444 y FFV1 (los convierte a
# un formato sin alfa), CineForm; y el WebP animado ni siquiera lo abre. Para esos se
# reproduce una copia en HAP Alpha (.mov), que Qt sí muestra transparente.
ALPHA_PREVIEW_DIVISOR = -1

# Lado largo máximo de esa copia: el panel de vista previa casi nunca ocupa más de 1080p
# en pantalla, y a 4K la copia pesaría ~4 veces más sin que se note la diferencia.
_ALPHA_PREVIEW_MAX_SIDE = 1920

# Códecs cuyo alfa el reproductor de Qt SÍ muestra tal cual (verificado): con ellos no
# hace falta copia. Cualquier otro con transparencia la necesita.
_QT_SHOWS_ALPHA = {"qtrle", "apng", "hap", "png", "gif", "utvideo", "huffyuv"}


def probe_alpha_preview(file_path: str) -> dict | None:
    """Si `file_path` necesita la copia con transparencia para verse bien en la vista
    previa, devuelve {"width", "height", "decoder_args"}; si no, None."""
    from core.tabs.video_tools.ia_video_common import probe_video_source
    info = probe_video_source(file_path)
    codec = info.get("codec") or ""
    if codec in _QT_SHOWS_ALPHA or not (info.get("has_alpha") or codec == "webp"):
        return None
    return {"width": info.get("width") or 0, "height": info.get("height") or 0,
            "decoder_args": list(info.get("decoder_args") or [])}


class _AlphaProbeSignals(QObject):
    done = Signal(str, object)   # (file_path, resultado de probe_alpha_preview)


class _AlphaProbeRunnable(QRunnable):
    def __init__(self, file_path: str):
        super().__init__()
        self.file_path = file_path
        self.signals = _AlphaProbeSignals()

    def run(self):
        try:
            result = probe_alpha_preview(self.file_path)
        except Exception as e:
            logger.warning(f"ProxyCacheManager: No se pudo sondear la transparencia de {self.file_path}: {e}")
            result = None
        self.signals.done.emit(self.file_path, result)


class ProxyWorkerSignals(QObject):
    finished = Signal(str, int, int, str)  # (file_path, divisor, audio_track, proxy_path)
    failed = Signal(str, int, int)         # (file_path, divisor, audio_track)


class ProxyRunnable(QRunnable):
    """Genera en segundo plano un proxy de previsualización: una copia del video escalada
    (1/2, 1/4, 1/8...) y codificada rápido, para poder hacer scrubbing fluido de medios
    pesados/RAW cuyo decodificado a resolución completa sería demasiado lento en tiempo real.

    `audio_track` (0-based) preserva en el proxy la misma pista de audio que el usuario tenga
    seleccionada en medios multipista, en vez de tomar siempre la primera por defecto."""

    def __init__(self, file_path: str, divisor: int, target_path: str, manager: "ProxyCacheManager", audio_track: int = 0,
                 decoder_args: list | None = None):
        super().__init__()
        self.decoder_args = decoder_args or []
        self.file_path = file_path
        self.divisor = divisor
        self.target_path = target_path
        self.manager = manager
        self.audio_track = audio_track
        self.signals = ProxyWorkerSignals()

    def run(self):
        try:
            ok = self._generate()
            if ok and os.path.exists(self.target_path) and os.path.getsize(self.target_path) > 0:
                self.signals.finished.emit(self.file_path, self.divisor, self.audio_track, self.target_path)
            else:
                self.signals.failed.emit(self.file_path, self.divisor, self.audio_track)
        except Exception as e:
            logger.error(f"ProxyRunnable: Error generando proxy de {self.file_path} (1/{self.divisor}): {e}")
            self.signals.failed.emit(self.file_path, self.divisor, self.audio_track)
        finally:
            self.manager._task_finished(self.file_path, self.divisor, self.audio_track)

    def _generate(self) -> bool:
        if not check_ffmpeg():
            return False

        info = get_platform_info()
        ffmpeg_exe = os.path.join(get_ffmpeg_dir(), info["binary_name"])

        # trunc(.../2)*2 asegura dimensiones pares, requisito de la mayoría de encoders H.264.
        scale_filter = f"scale=trunc(iw/{self.divisor}/2)*2:trunc(ih/{self.divisor}/2)*2"

        # Se escribe primero a un .tmp y se renombra al terminar: así get_cached_proxy_path()
        # nunca puede toparse con un archivo a medio escribir bajo el nombre final.
        tmp_target = self.target_path + ".tmp"

        alpha = self.divisor == ALPHA_PREVIEW_DIVISOR
        if alpha:
            # Lado largo acotado a _ALPHA_PREVIEW_MAX_SIDE (nunca se agranda) y medidas
            # múltiplos de 4, que HAP exige.
            # (comas escapadas: dentro de -vf una coma sin escapar separa filtros)
            f = f"min(1\\,{_ALPHA_PREVIEW_MAX_SIDE}/max(iw\\,ih))"
            scale_filter = f"scale=trunc(iw*{f}/4)*4:trunc(ih*{f}/4)*4"

        # decoder_args (libvpx) va ANTES del -i: sin él, el alfa de WebM se pierde al leer.
        cmd = [ffmpeg_exe, "-y", *(self.decoder_args if alpha else []), "-i", self.file_path]
        if self.audio_track:
            # Al usar -map explícito hay que mapear también el video, porque ffmpeg deja de
            # autoseleccionar streams en cuanto se especifica cualquier -map.
            cmd += ["-map", "0:v:0", "-map", f"0:a:{self.audio_track}"]
        if alpha:
            cmd += ["-vf", scale_filter, "-c:v", "hap", "-format", "hap_alpha",
                    "-c:a", "aac", "-b:a", "128k", "-f", "mov", tmp_target]
        else:
            cmd += [
                "-vf", scale_filter,
                # ultrafast + CRF alto: prioriza velocidad de generación y de decodificado en la
                # reproducción posterior por encima de la calidad de imagen (es solo una previa).
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                # Forzar el contenedor explícitamente: el archivo temporal termina en ".mp4.tmp",
                # una extensión que ffmpeg no reconoce para adivinar el formato de salida.
                "-f", "mp4",
                tmp_target
            ]

        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                startupinfo=startupinfo, text=True, encoding='utf-8', errors='ignore'
            )
            _, stderr = proc.communicate()
        except Exception as e:
            logger.error(f"ProxyRunnable: No se pudo ejecutar ffmpeg para {self.file_path}: {e}")
            return False

        if proc.returncode != 0:
            logger.error(
                f"ProxyRunnable: ffmpeg terminó con código {proc.returncode} para {self.file_path}: "
                f"{(stderr or '')[-500:]}"
            )
            if os.path.exists(tmp_target):
                try:
                    os.remove(tmp_target)
                except Exception:
                    pass
            return False

        os.replace(tmp_target, self.target_path)
        return True


class ProxyCacheManager(QObject):
    """Gestor de caché de proxies de previsualización (video de baja resolución para
    scrubbing fluido de medios pesados/RAW).

    A diferencia de ThumbnailCacheManager/WaveformCacheManager (que acumulan sin límite,
    archivos de pocos KB cada uno), estos proxies pueden pesar cientos de MB o varios GB, así
    que el caché tiene un tope de tamaño total configurable con purga LRU (se elimina primero
    el proxy usado menos recientemente) en vez de crecer indefinidamente."""

    proxy_ready = Signal(str, int, int, str)   # (file_path, divisor, audio_track, proxy_path)
    proxy_failed = Signal(str, int, int)       # (file_path, divisor, audio_track)

    _instance = None

    @classmethod
    def get_instance(cls) -> "ProxyCacheManager":
        if cls._instance is None:
            cls._instance = ProxyCacheManager()
        return cls._instance

    def __init__(self, parent=None, max_cache_bytes: int = DEFAULT_MAX_CACHE_BYTES):
        super().__init__(parent)
        self.max_cache_bytes = max_cache_bytes
        # Pool dedicado (no el global de la app) con un solo hilo: generar un proxy es una
        # transcodificación completa de ffmpeg, mucho más pesada que una miniatura o una
        # waveform — no conviene competir por hilos con esas tareas rápidas ni lanzar varias
        # transcodificaciones simultáneas.
        self.thread_pool = QThreadPool()
        self.thread_pool.setMaxThreadCount(1)
        self.mutex = QMutex()
        self._pending = set()   # {(file_path, divisor, audio_track)}
        self._failed = set()    # {(file_path, divisor, audio_track)}
        self._hash_cache = {}   # {(file_path, divisor, audio_track): hash}
        self._alpha_probe = {}  # {(file_path, mtime, size): resultado de probe_alpha_preview}
        self._alpha_probe_pending = set()

    # Resultado del sondeo de transparencia: (file_path, dict|None). Ver probe_alpha_preview.
    alpha_probe_done = Signal(str, object)

    def _alpha_probe_key(self, file_path: str):
        try:
            st = os.stat(file_path)
            return (os.path.abspath(file_path), st.st_mtime, st.st_size)
        except Exception:
            return (os.path.abspath(file_path), 0, 0)

    def request_alpha_probe(self, file_path: str):
        """¿Necesita `file_path` la copia con transparencia? Responde por alpha_probe_done
        (en segundo plano: es un ffprobe; memorizado por archivo)."""
        key = self._alpha_probe_key(file_path)
        if key in self._alpha_probe:
            self.alpha_probe_done.emit(file_path, self._alpha_probe[key])
            return
        if key in self._alpha_probe_pending:
            return
        self._alpha_probe_pending.add(key)
        worker = _AlphaProbeRunnable(file_path)
        worker.signals.done.connect(self._on_alpha_probe_done)
        QThreadPool.globalInstance().start(worker)

    def _on_alpha_probe_done(self, file_path: str, result):
        key = self._alpha_probe_key(file_path)
        self._alpha_probe_pending.discard(key)
        self._alpha_probe[key] = result
        self.alpha_probe_done.emit(file_path, result)

    def set_max_cache_bytes(self, max_bytes: int):
        self.max_cache_bytes = max(0, int(max_bytes))
        self._enforce_cache_limit()

    def _get_hash_key(self, file_path: str, divisor: int, audio_track: int = 0) -> str:
        cache_lookup = (file_path, divisor, audio_track)
        if cache_lookup in self._hash_cache:
            return self._hash_cache[cache_lookup]
        try:
            stat = os.stat(file_path)
            raw = f"{os.path.abspath(file_path)}_{stat.st_mtime}_{stat.st_size}_proxy_d{divisor}_v1"
        except Exception:
            raw = f"{os.path.abspath(file_path)}_proxy_d{divisor}_v1"
        if audio_track:
            raw += f"_t{audio_track}"
        hash_val = hashlib.sha256(raw.encode('utf-8')).hexdigest()
        self._hash_cache[cache_lookup] = hash_val
        return hash_val

    def _target_path(self, file_path: str, divisor: int, audio_track: int = 0) -> str:
        hash_key = self._get_hash_key(file_path, divisor, audio_track)
        ext = ".mov" if divisor == ALPHA_PREVIEW_DIVISOR else ".mp4"
        return os.path.join(get_proxy_cache_dir(), f"{hash_key}{ext}")

    def get_cached_proxy_path(self, file_path: str, divisor: int, audio_track: int = 0) -> str | None:
        """Devuelve la ruta del proxy si ya existe en caché, o None si hay que generarlo.
        Si existe, se marca como usado recientemente para el criterio de purga LRU."""
        if divisor <= 1 and divisor != ALPHA_PREVIEW_DIVISOR:
            return None
        target = self._target_path(file_path, divisor, audio_track)
        if os.path.exists(target) and os.path.getsize(target) > 0:
            try:
                os.utime(target, None)
            except Exception:
                pass
            return target
        return None

    def is_pending(self, file_path: str, divisor: int, audio_track: int = 0) -> bool:
        with QMutexLocker(self.mutex):
            return (file_path, divisor, audio_track) in self._pending

    def has_failed(self, file_path: str, divisor: int, audio_track: int = 0) -> bool:
        with QMutexLocker(self.mutex):
            return (file_path, divisor, audio_track) in self._failed

    def request_proxy(self, file_path: str, divisor: int, audio_track: int = 0):
        """Encola la generación del proxy en segundo plano si no está ya en caché o en curso."""
        if divisor <= 1 and divisor != ALPHA_PREVIEW_DIVISOR:
            return
        key = (file_path, divisor, audio_track)
        with QMutexLocker(self.mutex):
            if key in self._pending:
                return
            self._pending.add(key)
            self._failed.discard(key)

        target = self._target_path(file_path, divisor, audio_track)
        decoder_args = []
        if divisor == ALPHA_PREVIEW_DIVISOR:
            decoder_args = (self._alpha_probe.get(self._alpha_probe_key(file_path)) or {}).get("decoder_args") or []
        worker = ProxyRunnable(file_path, divisor, target, self, audio_track, decoder_args)
        worker.signals.finished.connect(self._on_worker_finished)
        worker.signals.failed.connect(self._on_worker_failed)
        self.thread_pool.start(worker)

    def _on_worker_finished(self, file_path: str, divisor: int, audio_track: int, proxy_path: str):
        self._enforce_cache_limit()
        self.proxy_ready.emit(file_path, divisor, audio_track, proxy_path)

    def _on_worker_failed(self, file_path: str, divisor: int, audio_track: int):
        with QMutexLocker(self.mutex):
            self._failed.add((file_path, divisor, audio_track))
        self.proxy_failed.emit(file_path, divisor, audio_track)

    def _task_finished(self, file_path: str, divisor: int, audio_track: int = 0):
        with QMutexLocker(self.mutex):
            self._pending.discard((file_path, divisor, audio_track))

    def _enforce_cache_limit(self):
        """Purga los proxies usados menos recientemente (por mtime, actualizado en cada
        acierto de caché) hasta bajar del tope de tamaño total configurado."""
        try:
            cache_dir = get_proxy_cache_dir()
            entries = []
            total = 0
            for name in os.listdir(cache_dir):
                if not name.endswith((".mp4", ".mov")):
                    continue
                path = os.path.join(cache_dir, name)
                try:
                    st = os.stat(path)
                except Exception:
                    continue
                entries.append((st.st_mtime, st.st_size, path))
                total += st.st_size

            if total <= self.max_cache_bytes:
                return

            entries.sort(key=lambda e: e[0])  # más antiguo (usado menos recientemente) primero
            for _mtime, size, path in entries:
                if total <= self.max_cache_bytes:
                    break
                try:
                    os.remove(path)
                    total -= size
                    logger.debug(f"ProxyCacheManager: Purgado por límite de tamaño de caché: {path}")
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"ProxyCacheManager: Error aplicando el límite de caché: {e}")

    def clear_cache(self) -> int:
        count = 0
        cache_dir = get_proxy_cache_dir()
        if os.path.exists(cache_dir):
            for name in os.listdir(cache_dir):
                path = os.path.join(cache_dir, name)
                if os.path.isfile(path):
                    try:
                        os.remove(path)
                        count += 1
                    except Exception as e:
                        logger.error(f"ProxyCacheManager: Error eliminando {path}: {e}")
        with QMutexLocker(self.mutex):
            self._hash_cache.clear()
            self._failed.clear()
        logger.info(f"ProxyCacheManager: Se eliminaron {count} proxies en caché.")
        return count

    def get_stats(self) -> dict:
        cache_dir = get_proxy_cache_dir()
        file_count = 0
        total_size = 0
        if os.path.exists(cache_dir):
            for entry in os.scandir(cache_dir):
                if entry.is_file():
                    file_count += 1
                    try:
                        total_size += entry.stat().st_size
                    except Exception:
                        pass
        return {"file_count": file_count, "size_bytes": total_size}
