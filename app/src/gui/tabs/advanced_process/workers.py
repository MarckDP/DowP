# src/gui/tabs/single_process/workers.py
from PySide6.QtCore import QThread, Signal
from core.tabs.advanced_process.video_details_logic import analyze_media_for_queue
from core.ytdlp_logic.downloader_master import DownloaderMaster
import threading
import time

class AnalysisWorker(QThread):
    """Worker thread for running yt-dlp analysis in background."""
    finished = Signal(dict, str)
    progress = Signal(int, int)

    def __init__(self, url, analyze_playlist=True, fast_mode=True):
        super().__init__()
        self.url = url
        self.analyze_playlist = analyze_playlist
        self.fast_mode = fast_mode
        self._cancel_event = threading.Event()

    def cancel(self):
        """Corta el análisis en el siguiente paso de yt-dlp (ver YTDLLogger en
        analyzer.py). No espera: el hilo termina solo poco después y emite finished con
        el error "Análisis cancelado" -- quien lo lanzó debe mirar is_cancelled() en su
        handler y descartar el resultado."""
        self._cancel_event.set()

    def is_cancelled(self):
        return self._cancel_event.is_set()

    def run(self):
        def on_progress(current, total):
            if not self._cancel_event.is_set():
                self.progress.emit(current, total)

        data, error = analyze_media_for_queue(
            self.url,
            analyze_playlist=self.analyze_playlist,
            fast_mode=self.fast_mode,
            progress_callback=on_progress,
            cancellation_event=self._cancel_event,
        )
        self.finished.emit(data if data else {}, error if error else "")

class DownloadWorker(QThread):
    """Hilo encargado de la descarga y reporte de progreso."""
    finished = Signal(bool, str)
    progress = Signal(dict)

    def __init__(self, request_data, cancellation_event=None):
        super().__init__()
        self.request_data = request_data
        self.cancellation_event = cancellation_event
        self.master = DownloaderMaster()
        self._last_emit_time = 0

    def run(self):
        success, message = self.master.download(
            self.request_data,
            self._on_progress,
            self.cancellation_event,
            conflict_ask_callback=self._ask_conflict,
        )
        self.finished.emit(success, message)

    def _ask_conflict(self, filename):
        """
        Invocado desde DownloaderMaster (este mismo hilo worker) solo cuando
        request_data["conflict_policy"] == "ask" (Proceso Avanzado en modo SOLO).
        Bloquea este hilo hasta que el usuario responde en ConflictDialog.
        """
        from gui.dialogs.conflict_bridge import get_conflict_bridge
        bridge = get_conflict_bridge()
        if bridge is None:
            return "cancel"
        return bridge.ask(filename)

    def _on_progress(self, d):
        # Limitamos la emisión de señales para no saturar el hilo principal, pero solo
        # para el % de "downloading" (ahí sí da igual perderse valores intermedios, se
        # ve el último). "finished" y "fragment_progress" son transiciones de estado
        # discretas, no ruido a suavizar - con un fragmento corto (unos pocos segundos)
        # el "fragment_progress" del fragmento N+1 podía llegar a <100ms del "finished"
        # del fragmento N y quedaba descartado aquí, dejando a Modo Rápido sin forma de
        # saber a qué fragmento pertenecía cada archivo (ver
        # QuickDownloadController._resolve_target_rows) - "Recodificar" terminaba
        # aplicándose a un fragmento cualquiera y dejando el resto sin recodificar.
        # 0.5s = 2 actualizaciones/seg por descarga activa. yt-dlp llama a este hook
        # mucho más seguido que eso; con varias descargas simultáneas, emitir a esa
        # frecuencia nativa saturaba la cola de eventos del hilo principal (cada tick
        # dispara un ciclo de repintado en la fila -- ver
        # QuickDownloadRow._refresh_card_style).
        current_time = time.time()
        if current_time - self._last_emit_time < 0.5 and d.get('status') not in ('finished', 'fragment_progress'):
            return

        self._last_emit_time = current_time
        self.progress.emit(d)
