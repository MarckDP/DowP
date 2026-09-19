# src/core/tabs/editing_media/remote_waveform_peaks_cache_manager.py
import time
import requests
from PySide6.QtCore import QObject, Signal, QRunnable, QThreadPool
from core.logger.logger_manager import logger

# Mismo criterio que remote_thumbnail_cache_manager.py: evitar reintentar sin parar una URL
# que ya sabemos rota (ver conversación sobre el loop de 424 de Openverse en miniaturas).
FAILURE_COOLDOWN_SECONDS = 300

_DOWNLOAD_HEADERS = {"User-Agent": "DowP/2.0 (https://github.com/dowp-project; gestor de medios de escritorio)"}


class RemoteWaveformPeaksWorkerSignals(QObject):
    finished = Signal(str, list)  # (url, peaks)
    failed = Signal(str)          # (url)


class RemoteWaveformPeaksRunnable(QRunnable):
    """Descarga y parsea el JSON de picos de forma de onda YA CALCULADOS por el origen web
    (ej. .../waveform/ de Openverse: {"len": N, "points": [0.0-1.0, ...]}). A diferencia de
    Freesound (que solo da una imagen ya renderizada y hay que aproximar los picos analizando
    píxeles, ver RemoteWaveformLoaderThread en editing_media_logic.py), acá el dato numérico
    ya viene listo -- no hace falta decodificar ninguna imagen."""

    def __init__(self, url: str, manager: "RemoteWaveformPeaksCacheManager"):
        super().__init__()
        self.url = url
        self.manager = manager
        self.signals = RemoteWaveformPeaksWorkerSignals()

    def run(self):
        try:
            response = requests.get(self.url, timeout=15, headers=_DOWNLOAD_HEADERS)
            response.raise_for_status()
            data = response.json()
            peaks = data.get("points")
            if not isinstance(peaks, list) or not peaks:
                raise ValueError("Respuesta sin 'points' válido")
            peaks = [float(p) for p in peaks]
            self.manager._on_download_success(self.url, peaks)
            try:
                self.signals.finished.emit(self.url, peaks)
            except (RuntimeError, AttributeError):
                pass
        except Exception as e:
            logger.error(f"RemoteWaveformPeaksRunnable: Error descargando/parseando {self.url}: {e}")
            try:
                self.signals.failed.emit(self.url)
            except (RuntimeError, AttributeError):
                pass
        finally:
            self.manager._task_finished(self.url)


class RemoteWaveformPeaksCacheManager(QObject):
    """Caché en RAM (no en disco -- son unos pocos KB de floats por ítem, no vale la pena
    persistir) de picos de forma de onda ya calculados por el origen web. Genérico a
    propósito: cualquier origen que devuelva el mismo formato JSON {"points": [...]} lo puede
    reusar sin cambios, igual que RemoteThumbnailCacheManager con miniaturas."""

    peaks_ready = Signal(str, list)  # (url, peaks)

    _instance = None

    @classmethod
    def get_instance(cls) -> "RemoteWaveformPeaksCacheManager":
        if cls._instance is None:
            cls._instance = RemoteWaveformPeaksCacheManager()
        return cls._instance

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thread_pool = QThreadPool.globalInstance()
        self._peaks_cache: dict[str, list] = {}
        self._pending_urls: set[str] = set()
        self._failed_urls: dict[str, float] = {}

    def get_cached_peaks(self, url: str) -> list | None:
        return self._peaks_cache.get(url)

    def request_peaks(self, url: str):
        """Pide los picos de forma no bloqueante. Si ya están en caché, emite peaks_ready de
        inmediato; si no, descarga en segundo plano."""
        if not url:
            return
        cached = self._peaks_cache.get(url)
        if cached is not None:
            self.peaks_ready.emit(url, cached)
            return
        if url in self._pending_urls:
            return
        failed_at = self._failed_urls.get(url)
        if failed_at is not None and (time.time() - failed_at) < FAILURE_COOLDOWN_SECONDS:
            return

        self._pending_urls.add(url)
        worker = RemoteWaveformPeaksRunnable(url, self)
        worker.signals.finished.connect(self._on_worker_finished)
        worker.signals.failed.connect(self._on_worker_failed)
        self.thread_pool.start(worker)

    def _on_download_success(self, url: str, peaks: list):
        self._peaks_cache[url] = peaks
        self._failed_urls.pop(url, None)

    def _on_worker_finished(self, url: str, peaks: list):
        self.peaks_ready.emit(url, peaks)

    def _on_worker_failed(self, url: str):
        self._failed_urls[url] = time.time()
        logger.warning(f"RemoteWaveformPeaksCacheManager: Falló la descarga de {url} (no se reintenta por {FAILURE_COOLDOWN_SECONDS}s)")

    def _task_finished(self, url: str):
        self._pending_urls.discard(url)
