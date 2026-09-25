# src/core/utils/queue_manager.py
import os
import re
import threading
import time
from uuid import uuid4
from PySide6.QtCore import QObject, Signal, QThread, QMutex, QRecursiveMutex, QMutexLocker
from core.logger.logger_manager import logger
from core.utils.output_artifacts import OutputArtifactTracker, find_actual_downloaded_file, sanitize_filename


def _extract_vf_value(args: list) -> tuple:
    """Separa el valor de '-vf' (si está) del resto de una lista de argumentos de
    ffmpeg. Necesario para la marca de agua de imagen: no se puede pasar '-vf' y
    '-filter_complex' juntos apuntando al mismo stream de video de salida, así que el
    -vf que ya armó advanced_recode_panel.py (escala/recorte/texto) se reinyecta como
    primera etapa del filter_complex en vez de quedar como -vf suelto."""
    if "-vf" not in args:
        return None, list(args)
    idx = args.index("-vf")
    value = args[idx + 1] if idx + 1 < len(args) else None
    remaining = args[:idx] + args[idx + 2:]
    return value, remaining


# Contenedores de salida que admiten una carátula incrustada (attached_pic). El resto
# (webm, avi, gif...) no la guarda: mapearla ahí haría fallar el mux o la recodificaría
# como un segundo video de verdad.
COVER_ART_CONTAINERS = {".mp4", ".m4v", ".m4a", ".mov", ".mkv", ".mka"}


def output_supports_cover_art(output_file: str) -> bool:
    return os.path.splitext(output_file or "")[1].lower() in COVER_ART_CONTAINERS


def probe_video_streams(input_file: str) -> tuple[bool, int | None]:
    """(tiene_video_real, índice_absoluto_de_la_carátula) del archivo, con UN solo ffprobe.

    Las dos respuestas salen del mismo dato -- la disposición `attached_pic` de cada
    stream de video -- así que se sondea una vez y se reparte, en vez de pagar dos
    arranques de ffprobe por archivo recodificado.

    Se devuelve el índice absoluto y no un simple "sí/no" porque es lo que hace falta
    para mapear la carátula de forma portable: el selector por disposición
    ("0:disp:attached_pic") solo existe desde ffmpeg 7.0, y DowP admite que el usuario
    apunte a su propio ffmpeg, que puede ser más viejo. Un "-map 0:2" funciona en
    cualquier versión.

    Ante la duda (sin ffprobe, salida ilegible) devuelve (True, None): se mantiene el
    comportamiento de siempre, que es no tocar el video ni mapear carátula alguna."""
    import json
    import subprocess
    from core.setup.ffmpeg_setup import get_ffprobe_path

    try:
        ffprobe = get_ffprobe_path()
        if not ffprobe or not os.path.exists(ffprobe):
            return True, None
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        salida = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json", "-show_streams",
             "-select_streams", "v", input_file],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30, startupinfo=startupinfo,
        )
        if salida.returncode != 0:
            return True, None
        streams = (json.loads(salida.stdout or "{}") or {}).get("streams") or []
        if not streams:
            return False, None
        caratulas = [st for st in streams if (st.get("disposition") or {}).get("attached_pic", 0)]
        hay_video_real = len(caratulas) < len(streams)
        indice = caratulas[0].get("index") if caratulas else None
        return hay_video_real, (int(indice) if isinstance(indice, int) else None)
    except Exception as e:
        logger.warning(f"QueueWorker: No se pudo sondear el video de '{input_file}': {e}")
        return True, None


def source_has_real_video(input_file: str) -> bool:
    """True si el archivo tiene un stream de video de verdad.

    La carátula incrustada de un audio (la que la propia app mete con
    `embed_thumbnail`) viaja como un stream de VIDEO mjpeg con disposición
    `attached_pic`. ffmpeg la elige automáticamente como "el video" del archivo, así que
    un preset de video aplicado a un .m4a intentaba codificar la carátula:

        [mov] Could not find tag for codec prores in stream #0
        Conversion failed!

    El muxer mov guarda un attached_pic como carátula, y ahí solo caben jpeg/png -- no
    prores. Distinguirlo por la disposición es preciso: un archivo de imagen de verdad
    (jpg/png de entrada) NO es attached_pic, así que convertir una imagen a video sigue
    funcionando igual. Mismo criterio que usa ffprobe_metadata_manager.py al decidir si
    un medio "tiene video".

    Ante la duda (sin ffprobe, salida ilegible) devuelve True: se mantiene el
    comportamiento de siempre en vez de tirar el video de un archivo que sí lo tenía.
    """
    return probe_video_streams(input_file)[0]


# Job types que compiten por GPU/CPU local (a diferencia de DOWNLOAD/PLAYLIST,
# limitados por ancho de banda) -- máximo 1 a la vez, ver QueueWorker.run() y
# QueueManager._get_next_runnable_job.
_HEAVY_JOB_TYPES = frozenset({"RECODE", "UPSCALE_VIDEO", "DEPTH_VIDEO", "NORMAL_VIDEO"})


class JobStatus:
    PENDING = "PENDING"
    ANALYZING = "ANALYZING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"
    NO_AUDIO = "NO_AUDIO"

class Job:
    """
    Representa una tarea de descarga o procesamiento en la cola.
    """
    def __init__(self, config: dict, job_type: str = "DOWNLOAD"):
        self.job_id = str(uuid4())
        self.job_type = job_type
        self.config = config  # Contiene url, output_path, speed_limit, etc. (Opciones iniciales por defecto)
        self.video_data = None    # Datos en crudo de la extracción de yt-dlp (formatos disponibles, miniatura, etc.)
        self.request_data = None  # Opciones específicas seleccionadas por el usuario para esta descarga
        self.analysis_data = None
        self.status = JobStatus.PENDING
        self.progress = 0.0
        self.speed = ""
        self.eta = ""
        self.title = config.get("title", "Tarea de descarga")
        self.error_message = ""
        self.final_filepath = None
        # Todo lo que este trabajo dejó en disco (medio, fragmentos, recodificado...),
        # para poder arrastrar la tarjeta terminada a otra aplicación con TODO su
        # resultado -- los sidecars (miniatura, subtítulos) se barren por nombre base al
        # arrastrar, no hace falta registrarlos. Ver core/utils/output_artifacts.py.
        self.artifacts = OutputArtifactTracker()
        self.created_at = time.time()

    def add_output_files(self, paths, is_stem_source=True):
        self.artifacts.add(paths, is_stem_source=is_stem_source)

class SingleJobWorker(QThread):
    """Hilo individual de descarga para un trabajo en la cola."""
    finished_job = Signal(str, str) # job_id, status

    def __init__(self, job, queue_worker):
        super().__init__()
        self.job = job
        self.queue_worker = queue_worker
        self.cancellation_event = threading.Event()
        self.downloader = None

    def cancel(self):
        self.cancellation_event.set()
        if self.downloader:
            self.downloader.cancel_download()

    def run(self):
        try:
            if self.job.job_type == "DOWNLOAD":
                self.queue_worker._execute_download(self.job, self.cancellation_event, self)
            elif self.job.job_type == "PLAYLIST":
                self.queue_worker._execute_playlist(self.job, self.cancellation_event, self)
            elif self.job.job_type == "RECODE":
                self.queue_worker._execute_recode(self.job, self.cancellation_event, self)
            elif self.job.job_type == "UPSCALE_VIDEO":
                self.queue_worker._execute_upscale_video(self.job, self.cancellation_event, self)
            elif self.job.job_type == "DEPTH_VIDEO":
                self.queue_worker._execute_depth_video(self.job, self.cancellation_event, self)
            elif self.job.job_type == "NORMAL_VIDEO":
                self.queue_worker._execute_normal_video(self.job, self.cancellation_event, self)
        except Exception as e:
            import traceback
            logger.error(f"SingleJobWorker: Error inesperado en job {self.job.job_id}: {traceback.format_exc()}")
            self.job.status = JobStatus.FAILED
            self.job.error_message = str(e)
            self.queue_worker.job_status_changed.emit(self.job.job_id, JobStatus.FAILED)
        finally:
            self.finished_job.emit(self.job.job_id, self.job.status)


class QueueWorker(QThread):
    """
    Hilo despachador de la cola encargado de gestionar trabajos concurrentes.
    """
    job_status_changed = Signal(str, str)             # job_id, status
    job_progress_changed = Signal(str, float, str, str) # job_id, progress%, speed, eta
    finished_all = Signal()

    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self._is_running = True
        self._cancellation_event = threading.Event()
        self._active_workers = {}
        self._workers_mutex = QRecursiveMutex()

    def stop(self):
        """Detiene el despachador y sus hilos de descarga activos."""
        self._is_running = False
        self._cancellation_event.set()
        with QMutexLocker(self._workers_mutex):
            for worker in list(self._active_workers.values()):
                worker.cancel()
        self.wait(1000)

    def run(self):
        logger.info("QueueWorker: Hilo despachador de cola iniciado.")
        from core.utils.config_manager import get_config
        while self._is_running:
            if self.manager.is_paused():
                time.sleep(0.3)
                continue

            max_concurrent = get_config().get("max_concurrent_downloads", 3)
            
            with QMutexLocker(self._workers_mutex):
                active_count = len(self._active_workers)
                active_heavy = sum(1 for w in self._active_workers.values() if w.job.job_type in _HEAVY_JOB_TYPES)

            if active_count < max_concurrent:
                job = self.manager._get_next_runnable_job(active_heavy)
                if job:
                    job.status = JobStatus.RUNNING
                    self.job_status_changed.emit(job.job_id, JobStatus.RUNNING)
                    
                    worker = SingleJobWorker(job, self)
                    worker.finished_job.connect(self._on_single_job_finished)
                    with QMutexLocker(self._workers_mutex):
                        self._active_workers[job.job_id] = worker
                    worker.start()
                    continue
                else:
                    with QMutexLocker(self._workers_mutex):
                        if len(self._active_workers) == 0:
                            self.manager.pause_queue()
                            self.finished_all.emit()
            time.sleep(0.3)

    def _on_single_job_finished(self, job_id, status):
        with QMutexLocker(self._workers_mutex):
            if job_id in self._active_workers:
                worker = self._active_workers.pop(job_id)
                worker.deleteLater()

    def cancel_current_job(self):
        with QMutexLocker(self._workers_mutex):
            for worker in list(self._active_workers.values()):
                worker.cancel()

    def cancel_job(self, job_id: str):
        """Cancela SOLO el worker de este job_id, a diferencia de cancel_current_job()
        (que cancela todo lo activo - correcto para stop()/clear_queue(), pero cancelaría
        de más si hay una descarga corriendo en paralelo a la recodificación que el
        usuario quiso cancelar)."""
        with QMutexLocker(self._workers_mutex):
            worker = self._active_workers.get(job_id)
        if worker:
            worker.cancel()

    def _download_best_thumb(self, entry, output_dir, title, force_png=False, media_path=None):
        """
        Descarga la mejor miniatura disponible (Forzando MaxRes) y la guarda sin usar PIL.

        media_path: ruta del medio ya descargado. Si se pasa, la miniatura toma su MISMO
        nombre base. Sin esto se re-sanitizaba el título con _sanitize_filename, que
        borra '#' (entre otros) mientras que yt-dlp SÍ lo conserva al nombrar el medio:
        quedaban 'xane - housekeeping #deadlock.mp4' y 'xane - housekeeping deadlock.jpg',
        con lo que el envío al editor -- que deduce la miniatura del nombre del medio --
        nunca la encontraba y mandaba el paquete sin ella (ver
        editor_integration_manager.process_raw_download).
        """
        try:
            # 1. Buscar la URL base
            thumb_url = None
            thumbs = entry.get('thumbnails')
            
            if thumbs:
                sorted_thumbs = sorted(thumbs, key=lambda x: x.get('width', 0) or 0, reverse=True)
                thumb_url = sorted_thumbs[0].get('url')
            
            if not thumb_url:
                thumb_url = entry.get('thumbnail')
            
            if not thumb_url:
                return None

            # 2. INTENTO INTELIGENTE: Forzar MaxResDefault
            final_url = thumb_url
            if "i.ytimg.com" in thumb_url:
                max_res_url = re.sub(r'/(hq|mq|sd|default)default', '/maxresdefault', thumb_url)
                
                try:
                    import requests
                    check_resp = requests.get(max_res_url, timeout=5, stream=True)
                    if check_resp.status_code == 200:
                        final_url = max_res_url
                        check_resp.close()
                except:
                    pass

            # 3. Descargar datos reales
            import requests
            response = requests.get(final_url, timeout=30)
            response.raise_for_status()
            image_data = response.content
            
            # 4. Procesar y guardar sin usar PIL
            content_type = response.headers.get("Content-Type", "").lower()
            if "png" in content_type or image_data.startswith(b'\x89PNG\r\n\x1a\n'):
                smart_ext = ".png"
            elif "webp" in content_type or (image_data.startswith(b'RIFF') and image_data[8:12] == b'WEBP'):
                smart_ext = ".webp"
            elif "gif" in content_type or image_data.startswith(b'GIF8'):
                smart_ext = ".gif"
            else:
                smart_ext = ".jpg"
            
            if media_path:
                base_name = os.path.splitext(os.path.basename(media_path))[0]
            else:
                base_name = self._sanitize_filename(title)
            output_path = os.path.join(output_dir, f"{base_name}{smart_ext}")
            
            with open(output_path, "wb") as f:
                f.write(image_data)
                
            logger.info(f"QueueWorker: Miniatura guardada ({'MAXRES' if final_url != thumb_url else 'ORIG'}): {output_path}")
            return output_path
            
        except Exception as e:
            logger.warning(f"QueueWorker: Falló descarga de miniatura para '{title}': {e}")
            return None

    def _execute_download(self, job, cancellation_event=None, worker_ref=None):
        """Ejecuta una descarga usando DownloaderMaster de forma sincrónica dentro de este hilo."""
        if cancellation_event is None:
            cancellation_event = self._cancellation_event

        job.status = JobStatus.RUNNING
        self.job_status_changed.emit(job.job_id, JobStatus.RUNNING)

        from core.ytdlp_logic.downloader_master import DownloaderMaster
        downloader = DownloaderMaster()
        if worker_ref:
            worker_ref.downloader = downloader

        # Generar un progress callback que emita la señal Qt de progreso
        def progress_callback(d):
            if d.get("status") == "downloading":
                from core.ytdlp_logic.analyzer import strip_ansi_codes
                p_str = strip_ansi_codes(d.get('_percent_str', '0%')).replace('%','').strip()
                try:
                    val = float(p_str)
                    speed = strip_ansi_codes(d.get('_speed_str', '')).strip() or '...'
                    eta = strip_ansi_codes(d.get('_eta_str', '')).strip() or '...'
                    job.progress = val
                    job.speed = speed
                    job.eta = eta
                    self.job_progress_changed.emit(job.job_id, val, speed, eta)
                except Exception:
                    pass
            elif d.get("status") == "finished":
                job.progress = 100.0
                if d.get("filename"):
                    job.final_filepath = d.get("filename")
                    # Nombre DERIVADO (stream sin fusionar, o un fragmento ya cortado):
                    # se registra igual porque de él cuelga el nombre base del que se
                    # barren los hermanos al arrastrar (ver output_artifacts).
                    job.add_output_files([d.get("filename")])
                self.job_progress_changed.emit(job.job_id, 100.0, "", self.tr("Procesando final..."))
            elif d.get("status") == "fragment_progress":
                idx = d.get("fragment_index")
                total = d.get("fragment_count")
                phase = d.get("phase", "downloading")
                verb = "Cortando" if phase == "cutting" else "Descargando"
                msg = f"{verb} fragmento {idx} de {total}"
                job.speed = msg
                self.job_progress_changed.emit(job.job_id, 0, msg, phase)

        # Iniciar la descarga
        config_to_use = job.request_data if job.request_data else job.config
        
        # Sobreescribir opciones según el modo de miniatura en lote
        from core.utils.config_manager import get_config
        batch_thumb_mode = get_config().get("batch_thumbnail_mode", "manual")
        
        # Modo especial: solo descargar miniatura
        if batch_thumb_mode == "thumbnail_only":
            self.job_progress_changed.emit(job.job_id, 10.0, self.tr("Descargando miniatura..."), "...")
            output_dir = config_to_use.get("output_path") or self._default_output_path()
            title = config_to_use.get("title") or job.title or "thumbnail"
            
            data_source = job.video_data if job.video_data else job.analysis_data
            if not data_source:
                try:
                    from core.ytdlp_logic.analyzer import get_video_info
                    data_source = get_video_info(config_to_use.get("url"), extra_opts={'noplaylist': True})
                except Exception as e:
                    logger.error(f"QueueWorker: Error analizando para miniatura sola: {e}")
            
            if data_source:
                thumb_path = self._download_best_thumb(data_source, output_dir, title)
                if thumb_path:
                    job.status = JobStatus.COMPLETED
                    job.progress = 100.0
                    job.final_filepath = thumb_path
                    job.add_output_files([thumb_path])
                    self.job_status_changed.emit(job.job_id, JobStatus.COMPLETED)
                    return
            
            job.status = JobStatus.FAILED
            job.error_message = self.tr("No se pudo obtener la miniatura para este video.")
            self.job_status_changed.emit(job.job_id, JobStatus.FAILED)
            return

        # Para otros modos (manual o con video/audio)
        should_download_thumb_file = False
        if batch_thumb_mode == "with_media":
            should_download_thumb_file = True
        elif batch_thumb_mode == "manual":
            should_download_thumb_file = config_to_use.get("download_thumbnail_file", False)
            
        # Nos aseguramos de que yt-dlp NO intente descargar el archivo físico por su cuenta
        # (pero permitimos embed_thumbnail para incrustación)
        config_to_use = config_to_use.copy()
        config_to_use["download_thumbnail_file"] = False

        # GUARDIA DE MEMORIA: Proteger miniatura existente para evitar que yt-dlp la borre (al incrustar)
        output_dir_guard = config_to_use.get("output_path") or self._default_output_path()
        title_guard = config_to_use.get("title") or job.title or "download"
        sanitized_title_guard = self._sanitize_filename(title_guard)
        
        guarded_thumbnails = {}
        for ext in ['.jpg', '.jpeg', '.png', '.webp']:
            thumb_path_guard = os.path.join(output_dir_guard, f"{sanitized_title_guard}{ext}")
            if os.path.exists(thumb_path_guard):
                try:
                    with open(thumb_path_guard, "rb") as f:
                        guarded_thumbnails[thumb_path_guard] = f.read()
                except Exception:
                    pass

        success, message = downloader.download(
            config_to_use,
            progress_callback=progress_callback,
            cancellation_event=cancellation_event
        )

        # RESTAURAR GUARDIA DE MEMORIA
        for thumb_path_guard, thumb_data in guarded_thumbnails.items():
            if not os.path.exists(thumb_path_guard):
                try:
                    with open(thumb_path_guard, "wb") as f:
                        f.write(thumb_data)
                    logger.info(f"QueueWorker: Miniatura restaurada desde memoria: {thumb_path_guard}")
                except Exception as e:
                    logger.warning(f"QueueWorker: Fallo al restaurar miniatura: {e}")

        if success:
            job.status = JobStatus.COMPLETED
            job.progress = 100.0

            # config_to_use quedó con el título REAL usado (sanitizado, y renombrado con
            # "(1)" si hubo conflicto con policy "conservar") - DownloaderMaster muta esa
            # copia adentro de download(), nunca job.request_data (ver
            # _resolve_output_conflict/_sanitize_filename en downloader_master.py). El
            # hint de yt-dlp ya cargado en job.final_filepath (arriba, vía el hook de
            # progreso) además apunta al archivo INTERMEDIO de un stream en modos que
            # fusionan video+audio (ej. HLS) - se reconstruye la ruta real aquí, en la
            # única capa que tiene la copia mutada a mano, y solo se usa si existe en
            # disco (si no, se deja el hint como estaba).
            title = config_to_use.get("title")
            output_path_final = config_to_use.get("output_path")
            mode_final = config_to_use.get("mode", "video+audio")
            if title and output_path_final and mode_final in ("video+audio", "video_only", "audio_only"):
                from core.utils.file_conflict_manager import predict_final_extension
                predicted_ext = predict_final_extension(
                    config_to_use.get("video_ext"), config_to_use.get("audio_ext"),
                    mode_final, bool(config_to_use.get("video_is_combined")),
                )
                predicted_path = os.path.join(output_path_final, f"{title}{predicted_ext}")
                if os.path.exists(predicted_path):
                    job.final_filepath = predicted_path
                    job.add_output_files([predicted_path])

            if should_download_thumb_file:
                try:
                    output_dir = config_to_use.get("output_path") or self._default_output_path()
                    title = config_to_use.get("title") or job.title or "download"
                    data_source = job.video_data if job.video_data else job.analysis_data
                    if data_source:
                        thumb_path = self._download_best_thumb(data_source, output_dir, title,
                                                               force_png=True, media_path=job.final_filepath)
                        if thumb_path:
                            job.add_output_files([thumb_path], is_stem_source=False)
                except Exception as e:
                    logger.warning(f"QueueWorker: Falló la descarga de miniatura: {e}")
                    
            self.job_status_changed.emit(job.job_id, JobStatus.COMPLETED)
        else:
            if message == "SKIPPED_CONFLICT":
                job.status = JobStatus.SKIPPED
                job.error_message = self.tr("Omitido: el archivo ya existe") if hasattr(self, "tr") else "Omitido: el archivo ya existe"
                self.job_status_changed.emit(job.job_id, JobStatus.SKIPPED)
            elif self._cancellation_event.is_set():
                job.status = JobStatus.CANCELLED
                self.job_status_changed.emit(job.job_id, JobStatus.CANCELLED)
            else:
                job.status = JobStatus.FAILED
                from core.ytdlp_logic.analyzer import strip_ansi_codes
                job.error_message = strip_ansi_codes(message) if message else message
                self.job_status_changed.emit(job.job_id, JobStatus.FAILED)

    def _execute_playlist(self, job, cancellation_event=None, worker_ref=None):
        if cancellation_event is None:
            cancellation_event = self._cancellation_event

        job.status = JobStatus.RUNNING
        job.progress = 0.0
        self.job_status_changed.emit(job.job_id, JobStatus.RUNNING)

        entries = job.analysis_data.get("entries", []) if job.analysis_data else []
        selected_indices = job.config.get("selected_indices", [])
        selected_entries = [
            (idx, entries[idx]) for idx in selected_indices
            if isinstance(idx, int) and 0 <= idx < len(entries) and entries[idx]
        ]
        if not selected_entries:
            job.status = JobStatus.FAILED
            job.error_message = self.tr("La playlist no tiene medios seleccionados.")
            self.job_status_changed.emit(job.job_id, JobStatus.FAILED)
            return

        from core.ytdlp_logic.downloader_master import DownloaderMaster
        master = DownloaderMaster()
        if worker_ref:
            worker_ref.downloader = master

        playlist_title = self._sanitize_filename(job.config.get("title") or "Playlist")
        base_output = job.config.get("output_path") or self._default_output_path()
        playlist_output = os.path.join(base_output, playlist_title)
        os.makedirs(playlist_output, exist_ok=True)

        total = len(selected_entries)
        mode = job.config.get("playlist_mode", "video+audio")
        quality = job.config.get("playlist_quality", "best_compatible")
        conflict_policy = job.config.get("conflict_policy", "conservar")
        skipped_count = 0
        error_count = 0
        completed_count = 0

        from core.utils.config_manager import get_config
        batch_thumb_mode = get_config().get("batch_thumbnail_mode", "manual")

        for pos, (entry_index, entry) in enumerate(selected_entries, start=1):
            if self._cancellation_event.is_set():
                job.status = JobStatus.CANCELLED
                self.job_status_changed.emit(job.job_id, JobStatus.CANCELLED)
                return

            item_title = self._sanitize_filename(
                entry.get("title") or entry.get("id") or entry.get("url") or f"Item {pos:03d}"
            )
            item_url = self._entry_url(entry)
            if not item_url:
                logger.warning(f"QueueWorker: Item de playlist sin URL: {item_title}")
                continue

            prefix = f"{pos:03d} - "
            
            # Si el modo de lote es "Solo miniaturas"
            if batch_thumb_mode == "thumbnail_only":
                total_percent = pos / total * 100.0
                job.progress = total_percent
                self.job_progress_changed.emit(
                    job.job_id, total_percent, f"[{pos}/{total}] Descargando miniatura", ""
                )
                try:
                    self._download_best_thumb(entry, playlist_output, f"{prefix}{item_title}")
                except Exception as e:
                    logger.warning(f"QueueWorker: Falló miniatura de playlist {item_title}: {e}")
                continue

            # Para otros modos (manual o con video/audio)
            should_download_thumb_file = False
            if batch_thumb_mode == "with_media":
                should_download_thumb_file = True
            elif batch_thumb_mode == "manual":
                should_download_thumb_file = job.config.get("download_thumbnail_file", False)

            child_data = {
                "url": item_url,
                "title": f"{prefix}{item_title}",
                "mode": mode,
                "output_path": playlist_output,
                "format_selector": self._playlist_format_selector(mode, quality, url=item_url),
                "speed_limit": job.config.get("speed_limit"),
                "embed_metadata": job.config.get("embed_metadata", True),
                "embed_thumbnail": job.config.get("embed_thumbnail", True),
                "remove_sponsors": job.config.get("remove_sponsors", False),
                "is_playlist": True,
                "force_audio_extract": (mode == "audio_only"),
                "audio_ext": "mp3" if mode == "audio_only" and quality in ["320", "192", "128"] else None,
                "video_ext": "mp4" if mode != "audio_only" else None,
                "download_thumbnail_file": False, # Hacemos la descarga directa nosotros
                "conflict_policy": conflict_policy,
            }

            child_final_path = [None]

            def progress_callback(d, item_pos=pos, item_name=item_title):
                if d.get("status") == "downloading":
                    from core.ytdlp_logic.analyzer import strip_ansi_codes
                    p_str = strip_ansi_codes(d.get('_percent_str', '0%')).replace('%', '').strip()
                    try:
                        item_percent = float(p_str)
                    except Exception:
                        item_percent = 0.0
                    total_percent = ((item_pos - 1) + (item_percent / 100.0)) / total * 100.0
                    job.progress = total_percent
                    job.speed = f"[{item_pos}/{total}] {item_name[:32]}"
                    job.eta = strip_ansi_codes(d.get('_eta_str', '')).strip() or "..."
                    self.job_progress_changed.emit(job.job_id, total_percent, job.speed, job.eta)
                elif d.get("status") == "finished":
                    if d.get("filename"):
                        child_final_path[0] = d.get("filename")
                        job.add_output_files([d.get("filename")])
                    total_percent = item_pos / total * 100.0
                    job.progress = total_percent
                    self.job_progress_changed.emit(job.job_id, total_percent, f"[{item_pos}/{total}] Procesando", "")

            success, message = master.download(
                child_data,
                progress_callback=progress_callback,
                cancellation_event=cancellation_event
            )

            if success:
                completed_count += 1

                # El hook de yt-dlp reporta el ÚLTIMO stream descargado
                # ('001 - Título.f395.mp4'), que ffmpeg borra al fusionar: comprobar
                # os.path.exists() sobre esa ruta daba False y la recodificación de CADA
                # ítem de la playlist se saltaba en silencio (reproducido con una
                # playlist de dos ítems en 360p: ni un solo archivo recodificado, sin un
                # solo error en el log). Se resuelve al archivo real igual que en el
                # resto de la app.
                child_media_path = find_actual_downloaded_file(child_final_path[0])
                if child_media_path:
                    job.add_output_files([child_media_path])

                # Recodificación post-descarga: config única para toda la playlist (ver
                # advanced_process_view.py - los jobs PLAYLIST no tienen request_data por
                # ítem). Corre síncrona e inline, en el mismo hilo que el resto del loop
                # (no se encola un job RECODE aparte) - mismo criterio que ya usaba
                # DowP-Lite para no competir por el cupo de "1 recode simultáneo" de la
                # cola ni complicar el borrado del original con una espera async.
                if job.config.get("recode_enabled") and child_media_path:
                    self._recode_downloaded_file(
                        job, child_media_path,
                        preset_name=job.config.get("recode_preset_name"),
                        keep_original=job.config.get("recode_keep_original", True),
                        duration_sec=entry.get("duration") or 0.0,
                        cancellation_event=cancellation_event,
                        item_pos=pos, item_total=total,
                    )

                if should_download_thumb_file:
                    try:
                        thumb_path = self._download_best_thumb(entry, playlist_output, f"{prefix}{item_title}",
                                                               force_png=True, media_path=child_media_path)
                        if thumb_path:
                            job.add_output_files([thumb_path], is_stem_source=False)
                    except Exception as e:
                        logger.warning(f"QueueWorker: Falló miniatura de playlist {item_title}: {e}")
            elif message == "SKIPPED_CONFLICT":
                # Un ítem omitido por conflicto de archivo no debe frenar el resto de
                # la playlist (mismo espíritu que en LOTES: solo se salta ese ítem).
                logger.info(f"QueueWorker: Ítem de playlist omitido por conflicto: {item_title}")
                skipped_count += 1
                continue
            else:
                if self._cancellation_event.is_set():
                    job.status = JobStatus.CANCELLED
                    self.job_status_changed.emit(job.job_id, JobStatus.CANCELLED)
                    return
                # Un ítem que falla de verdad (no cancelación) no debe frenar el
                # resto de la playlist — se cuenta como error y se sigue.
                logger.warning(f"QueueWorker: Ítem de playlist falló, se continúa con el resto: {item_title} -> {message}")
                error_count += 1
                continue

        job.progress = 100.0
        job.final_filepath = playlist_output

        summary_parts = [f"{completed_count} de {total} completados"]
        if error_count:
            summary_parts.append(f"{error_count} con error")
        if skipped_count:
            summary_parts.append(f"{skipped_count} omitidos (ya existían)")
        summary = ", ".join(summary_parts)

        if completed_count == 0 and (error_count or skipped_count):
            job.status = JobStatus.FAILED
            job.error_message = summary
        else:
            job.status = JobStatus.COMPLETED
            if error_count or skipped_count:
                job.error_message = summary
        self.job_status_changed.emit(job.job_id, job.status)

    @staticmethod
    def _sanitize_filename(filename):
        """Delega en la única fuente de verdad (ver output_artifacts.sanitize_filename).

        Antes tenía su propia versión, y discrepaba con la de downloader_master —la que
        acaba escribiendo yt-dlp— en seis cosas, empezando por eliminar la almohadilla.
        Resultado: la ruta que se predecía aquí no era la del archivo real, así que el
        medio no llegaba al editor y el botón de abrir su carpeta no hacía nada.

        El fallback sigue siendo "Playlist" porque este sanitizador también nombra
        carpetas de listas de reproducción (ver _execute_playlist)."""
        return sanitize_filename(filename, fallback="Playlist")

    @staticmethod
    def _entry_url(entry):
        url = entry.get("webpage_url") or entry.get("url") or entry.get("id")
        if not url:
            return None
        url = str(url)
        if url.startswith(("http://", "https://")):
            return url
        ie_key = (entry.get("ie_key") or entry.get("extractor_key") or "").lower()
        if "youtube" in ie_key:
            return f"https://www.youtube.com/watch?v={entry.get('id') or url}"
        return url

    @staticmethod
    def _playlist_format_selector(mode, quality, url=""):
        from core.ytdlp_logic.format_selectors import playlist_format_selector
        return playlist_format_selector(mode, quality, url=url)

    def _recode_downloaded_file(self, job, input_path, preset_name, keep_original,
                                 duration_sec, cancellation_event, item_pos=1, item_total=1):
        """
        Recodifica SÍNCRONAMENTE (mismo hilo, sin encolar un job RECODE aparte) un archivo
        ya descargado, usado por _execute_playlist para cada hijo — a diferencia de una
        descarga individual (ver advanced_process/download_controller.py), que sí encola un
        job RECODE async porque ahí cada item ya ocupa su propia tarjeta/posición en la cola.

        Pone el original en cuarentena (.dbak) antes de recodificar, y siempre lo restaura
        si la recodificación falla o se cancela, sin importar `keep_original` (que solo
        decide qué pasa cuando SÍ hubo éxito) — mismo contrato que la ruta async.
        """
        from core.utils.preset_manager import build_recode_output_path
        from core.utils.file_conflict_manager import quarantine_for_recode, commit_backup, rollback_backup

        settings, out_file = build_recode_output_path(
            input_path, "video_tools/avanzado", preset_name,
            prefix=job.config.get("recode_filename_prefix") or "",
            suffix=job.config.get("recode_filename_suffix") or "",
        )
        if not settings:
            logger.warning(f"QueueWorker: [Playlist] Preset de recodificación '{preset_name}' no encontrado, se omite.")
            return
        # Misma regla que la tarjeta "Posprocesar" (ver preset_manager.recode_preset_fits):
        # el modo de la playlist pudo cambiar después de elegir el preajuste.
        from core.utils.preset_manager import recode_preset_fits
        playlist_mode = job.config.get("playlist_mode", "video+audio")
        if not recode_preset_fits(settings, playlist_mode):
            logger.info(f"QueueWorker: [Playlist] Recodificación omitida: '{preset_name}' no sirve "
                        f"para una descarga '{playlist_mode}'.")
            return

        try:
            backup_path = quarantine_for_recode(input_path)
        except Exception as e:
            logger.error(f"QueueWorker: [Playlist] No se pudo poner en cuarentena '{input_path}': {e}")
            return

        def progress_callback(percent, speed_str, eta_str):
            total_percent = ((item_pos - 1) + (percent / 100.0)) / item_total * 100.0
            job.progress = total_percent
            self.job_progress_changed.emit(
                job.job_id, total_percent, f"[{item_pos}/{item_total}] Recodificando {percent:.0f}%", eta_str
            )

        success, error = self._run_ffmpeg_command(
            backup_path, out_file, settings, duration_sec, cancellation_event,
            progress_callback=progress_callback,
        )

        if success and not cancellation_event.is_set():
            if keep_original:
                rollback_backup(backup_path)  # éxito + mantener: restaura el original junto al recodificado
            else:
                commit_backup(backup_path)  # éxito + no mantener: confirma (borra) el original
            job.add_output_files([out_file], is_stem_source=False)
            logger.info(f"QueueWorker: [Playlist] Recodificado: {out_file}")
        else:
            rollback_backup(backup_path)  # fallo o cancelación: SIEMPRE se restaura, sin importar keep_original
            logger.warning(f"QueueWorker: [Playlist] Recodificación falló para '{input_path}': {error or 'cancelado'}")

    def _run_ffmpeg_command(self, input_file, output_file, settings, duration_sec,
                             cancellation_event, progress_callback=None, worker_ref=None,
                             allow_cpu_fallback=True):
        """
        Arma y ejecuta el comando ffmpeg de recodificación a partir de (input_file,
        output_file, settings, duration_sec) — motor compartido por un job RECODE async
        (ver _execute_recode) y por la recodificación síncrona inline de cada hijo de una
        playlist (ver _execute_playlist), para no duplicar el armado del comando.

        progress_callback(percent, speed_str, eta_str), si se pasa, se invoca en cada
        línea de progreso parseada de ffmpeg — el llamador decide cómo reportarlo (señal
        de un job propio, o el progreso agregado de una playlist).

        Devuelve (success: bool, error_message: str | None).

        allow_cpu_fallback: si el comando usaba un encoder de GPU y ffmpeg falla, se
        reintenta UNA vez por CPU (ver el final de esta función). El escaneo de
        hardware confirma que el encoder existe y funciona, pero eso no cubre un driver
        que se cuelga, la GPU ocupada por otro programa o un formato que ese encoder no
        acepta -- sin el reintento, el usuario se queda sin resultado.
        """
        import subprocess
        from core.setup.ffmpeg_setup import get_ffmpeg_dir

        ffmpeg_exe = os.path.join(get_ffmpeg_dir(), "ffmpeg.exe" if os.name == 'nt' else "ffmpeg")
        if not os.path.exists(ffmpeg_exe):
            return False, self.tr("No se encontró ffmpeg.")

        # Construir comando FFmpeg
        cmd = [ffmpeg_exe, "-y"]
        trim_in = settings.get("trim_in_sec")
        trim_out = settings.get("trim_out_sec")
        if trim_in is not None and trim_in > 0:
            cmd.extend(["-ss", f"{trim_in:.3f}"])
        if trim_out is not None and trim_out > 0:
            cmd.extend(["-to", f"{trim_out:.3f}"])
        cmd.extend(["-i", input_file])

        # Marca de agua de imagen: segundo input (índice 1), en loop porque una imagen es
        # un solo frame — sin -loop 1 el overlay corta el video entero en el frame 0. Si
        # el archivo se borró/movió después de armar la cola (ej. desde un preajuste
        # viejo), se degrada en silencio a "sin marca de agua" en vez de fallar el job
        # entero — el aviso real ya debería haber pasado en la UI antes de llegar aquí.
        watermark_image_path = settings.get("watermark_image_path")
        watermark_overlay_filter = settings.get("watermark_overlay_filter")
        use_watermark_image = bool(watermark_image_path and watermark_overlay_filter)
        if use_watermark_image and not os.path.exists(watermark_image_path):
            logger.warning(f"QueueWorker: Imagen de marca de agua no encontrada, se omite: {watermark_image_path}")
            use_watermark_image = False
        if use_watermark_image:
            cmd.extend(["-loop", "1", "-i", watermark_image_path])

        stream_mode = settings.get("stream_mode", "video+audio")

        # Selección explícita de pistas de audio a conservar (ver advanced_recode_panel.py):
        # None = comportamiento de siempre, ffmpeg elige automáticamente 1 pista (la
        #        mayoría de los archivos fuente solo tienen una, así que este sigue siendo
        #        el camino más común, sin cambios de comportamiento).
        # "all" = todas las pistas de audio del archivo fuente.
        # int   = índice RELATIVO de audio (0 = primera pista, 1 = segunda, etc.).
        # OJO: agregar CUALQUIER -map desactiva la auto-selección de ffmpeg para TODOS
        # los tipos de stream a la vez, no solo audio — por eso, apenas se activa esto,
        # hay que mapear el video a mano también (si corresponde) para no perderlo.
        audio_track_selection = settings.get("audio_track_selection")
        explicit_mapping = audio_track_selection is not None

        # Opciones de Video
        video_mode = settings.get("video_mode", "recode")
        is_gif = (settings.get("video_codec") == "gif" or settings.get("container") == "gif")
        # Un preset de video sobre un archivo SIN video (un audio con carátula
        # incrustada) hacía que ffmpeg intentase codificar la carátula y el job entero
        # fallaba. Con una playlist de audio eso tumbaba la recodificación de todos los
        # ítems, uno por uno.
        tiene_video_real, indice_caratula = probe_video_streams(input_file)
        sin_video_real = (stream_mode != "audio_only" and video_mode != "none"
                          and not tiene_video_real)
        if sin_video_real:
            logger.info(f"QueueWorker: '{os.path.basename(input_file)}' no tiene video "
                        f"(solo audio o carátula incrustada): se recodifica solo el audio.")
            audio_mode_previo = settings.get("audio_mode", "recode")
            if audio_mode_previo == "none" or stream_mode == "video_only" or is_gif:
                return False, ("El archivo no tiene pista de video y el ajuste elegido "
                               "descarta el audio: no quedaría nada que guardar.")

        # Carátula incrustada (attached_pic): sin mapeo explícito, ffmpeg elige un video
        # y un audio y la DESCARTA -- el archivo recodificado perdía la miniatura que la
        # propia app había incrustado al descargar. Se copia tal cual (nunca se
        # recodifica) y solo cuando hay un video de verdad que siga siendo el stream
        # principal: con -vn (solo audio) ffmpeg la descarta igual, y en gif/webm/avi el
        # contenedor no la admite.
        conservar_caratula = (
            indice_caratula is not None
            and tiene_video_real
            and not is_gif
            and stream_mode != "audio_only"
            and video_mode != "none"
            and not sin_video_real
            and output_supports_cover_art(output_file)
            # Con marca de agua de imagen NO se conserva: esa rama usa -shortest (ver
            # más abajo, por el input en loop infinito) y -shortest corta la salida al
            # stream más corto, que sería la carátula -- un único fotograma. Probado:
            # el archivo salía con 0 KiB de video y audio, solo la carátula.
            and not use_watermark_image
        )

        if stream_mode == "audio_only" or video_mode == "none" or sin_video_real:
            cmd.append("-vn")
        elif use_watermark_image and video_mode != "copy":
            # No se puede usar -vf junto con -filter_complex apuntando al mismo stream:
            # se extrae el valor de -vf que ya armó advanced_recode_panel.py (escala/
            # recorte/texto) y se reinyecta como primera etapa del grafo fusionado.
            v_args = settings.get("video_args", [])
            vf_value, v_args = _extract_vf_value(v_args)
            main_stage = vf_value if vf_value else "null"  # 'null' = passthrough de ffmpeg
            filter_complex = f"[0:v]{main_stage}[main];{watermark_overlay_filter}"
            cmd.extend(["-filter_complex", filter_complex, "-map", "[vout]"])
            if v_args:
                cmd.extend(v_args)
            else:
                cmd.extend(["-c:v", "libx264", "-crf", "23"])
        else:
            if explicit_mapping or conservar_caratula:
                # "V" mayúscula = streams de video que NO son carátula. Con "v" minúscula,
                # un archivo cuya carátula va primero mapearía la carátula como "el video".
                cmd.extend(["-map", "0:V:0?"])
            if video_mode == "copy":
                cmd.extend(["-c:v", "copy"])
            else:
                v_args = settings.get("video_args", [])
                if v_args:
                    cmd.extend(v_args)
                else:
                    cmd.extend(["-c:v", "libx264", "-crf", "23"])

        # Opciones de Audio
        audio_mode = settings.get("audio_mode", "recode")
        if stream_mode == "video_only" or audio_mode == "none" or is_gif:
            cmd.append("-an")
        else:
            if audio_track_selection == "all":
                cmd.extend(["-map", "0:a"])
            elif isinstance(audio_track_selection, int):
                cmd.extend(["-map", f"0:a:{audio_track_selection}"])
            elif (use_watermark_image and video_mode != "copy") or conservar_caratula:
                # El -map de arriba (sea "[vout]" de la marca de agua o el del video por
                # la carátula) ya apagó la auto-selección de streams de ffmpeg para TODO
                # el output (ver comentario más arriba) — sin este mapeo explícito, el
                # audio desaparecería en vez de incluirse automáticamente.
                cmd.extend(["-map", "0:a?"])

            audio_mode = settings.get("audio_mode", "recode")
            if audio_mode == "copy":
                cmd.extend(["-c:a", "copy"])
            else:
                a_args = settings.get("audio_args", [])
                if a_args:
                    cmd.extend(a_args)
                else:
                    cmd.extend(["-c:a", "aac", "-b:a", "192k"])

        if conservar_caratula:
            # Va después del video/audio para que quede como segundo stream de video de
            # la salida (v:1). "-c:v:1 copy" pisa al "-c:v <encoder>" de los args del
            # perfil solo para ESE stream (el especificador más preciso manda), así que
            # la carátula se copia en vez de recodificarse, y -disposition la vuelve a
            # marcar como carátula para que los reproductores la muestren como tal.
            cmd.extend(["-map", f"0:{indice_caratula}", "-c:v:1", "copy",
                        "-disposition:v:1", "attached_pic"])

        if use_watermark_image:
            # La imagen de marca de agua entra con -loop 1 (stream infinito, ver más
            # arriba). El filtro overlay por defecto espera a que TODOS sus inputs
            # terminen antes de cerrar la salida (shortest=0) — sin este flag, ffmpeg
            # nunca ve EOF en el input infinito y el proceso queda corriendo para
            # siempre después de terminar de codificar el video real (se ve como
            # progreso pegado en 100% que nunca llega a completarse).
            cmd.append("-shortest")

        cmd.append(output_file)

        logger.info(f"QueueWorker: Ejecutando FFmpeg: {' '.join(cmd)}")

        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                startupinfo=startupinfo,
                encoding="utf-8",
                errors="replace"
            )

            # Guardamos la referencia para poder cancelarlo
            if worker_ref:
                worker_ref.downloader = proc # Usamos downloader para guardar el Popen, sobrecargando su uso temporalmente
                # Override cancel: además de terminar el proceso, hay que marcar
                # cancellation_event - si no, más abajo (tras proc.wait()) el chequeo
                # "if cancellation_event.is_set()" nunca ve la cancelación, y un proceso
                # matado a mano por el usuario terminaba reportado como FAILED (código de
                # retorno no-cero por la señal) en vez de CANCELLED, dejando además el
                # archivo de salida parcial sin borrar.
                def _cancel_proc():
                    cancellation_event.set()
                    proc.terminate()
                worker_ref.cancel = _cancel_proc

            time_regex = re.compile(r"time=\s*(\d+):(\d+):(\d+\.\d+|\d+)")
            speed_regex = re.compile(r"speed=\s*([\d\.]+)x")
            last_log_time = 0.0

            for line in proc.stderr:
                if cancellation_event.is_set():
                    proc.terminate()
                    break

                clean_line = line.strip()
                if not clean_line:
                    continue

                time_match = time_regex.search(clean_line)
                speed_match = speed_regex.search(clean_line)

                if time_match and duration_sec > 0:
                    h, m, s = float(time_match.group(1)), float(time_match.group(2)), float(time_match.group(3))
                    current_sec = h * 3600 + m * 60 + s
                    percent = min((current_sec / duration_sec) * 100.0, 100.0)

                    speed_str = f"{speed_match.group(1)}x" if speed_match else "..."

                    eta_str = "..."
                    if speed_match:
                        sp = float(speed_match.group(1))
                        if sp > 0:
                            rem = (duration_sec - current_sec) / sp
                            eta_str = f"{int(rem)}s"

                    if progress_callback:
                        progress_callback(percent, speed_str, eta_str)

                    # Registrar en consola con cadencia controlada (cada 1.0s) para progreso claro
                    now = time.time()
                    if now - last_log_time >= 1.0 or percent >= 100.0:
                        last_log_time = now
                        logger.info(f"QueueWorker: [FFmpeg] {percent:.1f}% | Velocidad: {speed_str} | ETA: {eta_str}")
                else:
                    # Registrar líneas clave de mapeo, inicio o advertencias de FFmpeg
                    lower_line = clean_line.lower()
                    if any(kw in lower_line for kw in ["error", "warning", "output #", "input #", "stream mapping", "mapping:"]):
                        logger.info(f"[FFmpeg] {clean_line}")
                    else:
                        logger.debug(f"[FFmpeg] {clean_line}")

            proc.wait()

            if cancellation_event.is_set():
                logger.info("QueueWorker: [FFmpeg] Proceso cancelado por el usuario.")
                if os.path.exists(output_file):
                    try:
                        os.remove(output_file)
                    except Exception:
                        pass
                return False, self.tr("Cancelado por el usuario")

            if proc.returncode == 0:
                return True, None
            else:
                error = f"FFmpeg terminó con código {proc.returncode}"
                logger.error(f"QueueWorker: [FFmpeg] {error}")
                reintento = self._retry_on_cpu(input_file, output_file, settings, duration_sec,
                                                cancellation_event, progress_callback, worker_ref,
                                                allow_cpu_fallback)
                return reintento if reintento is not None else (False, error)

        except Exception as e:
            logger.error(f"QueueWorker: Error ejecutando FFmpeg: {e}")
            return False, str(e)

    def _retry_on_cpu(self, input_file, output_file, settings, duration_sec,
                       cancellation_event, progress_callback, worker_ref, allow_cpu_fallback):
        """Reintenta la recodificación por CPU si la que falló usaba un encoder de GPU.

        Devuelve el resultado del reintento, o None si no corresponde reintentar (no
        había GPU de por medio, ya era el reintento, el usuario canceló, o no se pudo
        armar un equivalente por software)."""
        if not allow_cpu_fallback or cancellation_event.is_set():
            return None
        from core.utils.recode_guard import ENGINE_MODE_CPU, encoder_in_args, swap_video_encoder

        video_args = list(settings.get("video_args") or [])
        encoder = encoder_in_args(video_args)
        if not encoder or encoder.startswith("lib") or encoder in ("gif", "prores_ks", "prores_aw"):
            return None  # ya era software: el fallo no es de la GPU

        nuevos_args, nuevo_encoder = swap_video_encoder(
            video_args, settings.get("video_codec"), ENGINE_MODE_CPU, settings.get("video_tier"))
        if not nuevo_encoder or nuevo_encoder == encoder:
            return None

        logger.warning(f"QueueWorker: '{encoder}' (GPU) falló -- reintentando por CPU con "
                       f"'{nuevo_encoder}'.")
        settings_cpu = dict(settings)
        settings_cpu["video_args"] = nuevos_args
        settings_cpu.pop("video_args_pass1", None)
        settings_cpu.pop("video_args_pass2", None)
        return self._run_ffmpeg_command(
            input_file, output_file, settings_cpu, duration_sec, cancellation_event,
            progress_callback=progress_callback, worker_ref=worker_ref, allow_cpu_fallback=False,
        )

    def _execute_recode(self, job, cancellation_event=None, worker_ref=None):
        if cancellation_event is None:
            cancellation_event = self._cancellation_event

        job.status = JobStatus.RUNNING
        job.progress = 0.0
        self.job_status_changed.emit(job.job_id, JobStatus.RUNNING)
        self.job_progress_changed.emit(job.job_id, 0.0, "Iniciando FFmpeg...", "")

        config = job.config
        input_file = config.get("input_path")
        output_file = config.get("output_path")
        settings = config.get("settings", {})
        duration_sec = config.get("duration_sec", 0.0)

        def progress_callback(percent, speed_str, eta_str):
            job.progress = percent
            job.speed = speed_str
            job.eta = eta_str
            self.job_progress_changed.emit(job.job_id, percent, f"Velocidad: {speed_str}", f"ETA: {eta_str}")

        success, error = self._run_ffmpeg_command(
            input_file, output_file, settings, duration_sec, cancellation_event,
            progress_callback=progress_callback, worker_ref=worker_ref,
        )

        if cancellation_event.is_set():
            job.status = JobStatus.CANCELLED
            self.job_status_changed.emit(job.job_id, JobStatus.CANCELLED)
            logger.info(f"QueueWorker: [RECODE] Trabajo cancelado por el usuario: {job.title}")
            return

        if success:
            job.status = JobStatus.COMPLETED
            job.progress = 100.0
            job.final_filepath = output_file
            job.add_output_files([output_file], is_stem_source=False)
            self.job_progress_changed.emit(job.job_id, 100.0, "Completado", "")
            self.job_status_changed.emit(job.job_id, JobStatus.COMPLETED)
            logger.info(f"QueueWorker: [RECODE] Recodificación finalizada exitosamente: {output_file}")
        else:
            job.status = JobStatus.FAILED
            job.error_message = error or self.tr("Error desconocido en FFmpeg")
            self.job_status_changed.emit(job.job_id, JobStatus.FAILED)
            logger.error(f"QueueWorker: [RECODE] FFmpeg falló: {job.error_message} ({job.title})")

    def _execute_depth_video(self, job, cancellation_event=None, worker_ref=None):
        """Mapa de Profundidad de video -- ver core/tabs/video_tools/video_depth_engine.py."""
        from core.tabs.video_tools.video_depth_engine import run_depth_video
        self._execute_frame_video(
            job, run_depth_video, "depth_options", "DEPTH_VIDEO",
            self.tr("Calculando profundidad..."),
            self.tr("Error desconocido en Mapa de Profundidad de video"),
            cancellation_event, worker_ref)

    def _execute_normal_video(self, job, cancellation_event=None, worker_ref=None):
        """Mapa de Normales de video -- ver core/tabs/video_tools/video_normal_engine.py."""
        from core.tabs.video_tools.video_normal_engine import run_normal_video
        self._execute_frame_video(
            job, run_normal_video, "normal_options", "NORMAL_VIDEO",
            self.tr("Calculando normales..."),
            self.tr("Error desconocido en Mapa de Normales de video"),
            cancellation_event, worker_ref)

    def _execute_frame_video(self, job, run_engine, options_key, tag, label, unknown_error,
                             cancellation_event=None, worker_ref=None):
        """Herramientas IA de video fotograma a fotograma (ver
        core/tabs/video_tools/video_frame_engine.py). Mismo molde de estados que
        _execute_upscale_video; el progreso es por fotograma (la cuenta la lleva el motor)
        y el tiempo restante va en el campo de ETA."""
        if cancellation_event is None:
            cancellation_event = self._cancellation_event

        job.status = JobStatus.RUNNING
        job.progress = 0.0
        self.job_status_changed.emit(job.job_id, JobStatus.RUNNING)
        self.job_progress_changed.emit(job.job_id, 0.0, label, "")

        config = job.config
        output_file = config.get("output_path")

        def on_progress(pct, eta_sec):
            job.progress = pct
            eta = ""
            if eta_sec is not None:
                minutes, seconds = divmod(int(eta_sec), 60)
                hours, minutes = divmod(minutes, 60)
                eta = f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"
            self.job_progress_changed.emit(job.job_id, pct, label, eta)

        success, error = run_engine(
            config.get("input_path"), output_file, config.get(options_key, {}),
            config.get("fps") or 0.0, config.get("duration_sec", 0.0),
            trim_in=config.get("trim_in_sec"), trim_out=config.get("trim_out_sec"),
            cancellation_event=cancellation_event, progress_callback=on_progress,
            worker_ref=worker_ref,
        )

        if cancellation_event.is_set():
            job.status = JobStatus.CANCELLED
            self.job_status_changed.emit(job.job_id, JobStatus.CANCELLED)
            logger.info(f"QueueWorker: [{tag}] Trabajo cancelado por el usuario: {job.title}")
            return

        if success:
            job.status = JobStatus.COMPLETED
            job.progress = 100.0
            job.final_filepath = output_file
            job.add_output_files([output_file], is_stem_source=False)
            self.job_progress_changed.emit(job.job_id, 100.0, self.tr("Completado"), "")
            self.job_status_changed.emit(job.job_id, JobStatus.COMPLETED)
            logger.info(f"QueueWorker: [{tag}] Terminado: {output_file}")
        else:
            job.status = JobStatus.FAILED
            job.error_message = error or unknown_error
            self.job_status_changed.emit(job.job_id, JobStatus.FAILED)
            logger.error(f"QueueWorker: [{tag}] Falló: {job.error_message} ({job.title})")

    def _execute_upscale_video(self, job, cancellation_event=None, worker_ref=None):
        """Reescalado de Video con IA: extrae fotogramas (ffmpeg) -> los
        reescala TODOS en un solo proceso con el motor NCNN elegido -> rearma
        el video (ffmpeg, remuxando el audio original). Ver
        core/tabs/video_tools/video_upscale_engine.py para las 3 funciones,
        acá solo se pesa el progreso de cada una dentro del progreso total
        (0-15% / 15-85% / 85-100%, mismo peso que usaba DowP1 para esta misma
        función -- ver el comentario en
        core/tabs/image_tools/image_converter.py::_apply_ai_upscale) y se
        decide el estado final del job, mismo molde que _execute_recode."""
        if cancellation_event is None:
            cancellation_event = self._cancellation_event

        job.status = JobStatus.RUNNING
        job.progress = 0.0
        self.job_status_changed.emit(job.job_id, JobStatus.RUNNING)
        self.job_progress_changed.emit(job.job_id, 0.0, self.tr("Extrayendo fotogramas..."), "")

        config = job.config
        input_file = config.get("input_path")
        output_file = config.get("output_path")
        options = config.get("upscale_options", {})
        fps = config.get("fps") or 30.0
        # duration_sec ya es la del tramo recortado (ver video_tools_view.py); trim_in/
        # trim_out son el recorte de Herramientas Multimedia, None = video entero.
        duration_sec = config.get("duration_sec", 0.0)
        trim_in = config.get("trim_in_sec")
        trim_out = config.get("trim_out_sec")

        import shutil
        import tempfile
        from core.tabs.video_tools.ia_video_common import container_of, probe_video_source
        from core.tabs.video_tools.video_upscale_engine import (
            extract_frames, upscale_frames_batch, reassemble_video,
        )

        # Transparencia: solo si el usuario la pidió, la salida es MOV (ProRes 4444) y
        # el video la trae de verdad -- sin cualquiera de las tres, JPG + H.264.
        source = probe_video_source(input_file)
        keep_alpha = (bool(options.get("keep_alpha")) and container_of(output_file) == "mov"
                      and source["has_alpha"])
        keep_audio = options.get("keep_audio", True)

        temp_root = tempfile.mkdtemp(prefix="dowp_upscale_video_")
        frames_dir = os.path.join(temp_root, "frames")
        upscaled_dir = os.path.join(temp_root, "frames_up")

        def stage_progress(base, weight, label):
            def cb(pct):
                mapped = base + (pct / 100.0) * weight
                job.progress = mapped
                self.job_progress_changed.emit(job.job_id, mapped, label, "")
            return cb

        success, error = False, None
        try:
            success, error = extract_frames(
                input_file, frames_dir, fps, duration_sec, cancellation_event,
                progress_callback=stage_progress(0.0, 15.0, self.tr("Extrayendo fotogramas...")),
                worker_ref=worker_ref, keep_alpha=keep_alpha, trim_in=trim_in, trim_out=trim_out,
                decoder_args=source["decoder_args"] if keep_alpha else None,
            )
            if success:
                success, error = upscale_frames_batch(
                    frames_dir, upscaled_dir, options, cancellation_event,
                    progress_callback=stage_progress(15.0, 70.0, self.tr("Reescalando fotogramas...")),
                )
            if success:
                success, error = reassemble_video(
                    upscaled_dir, input_file, output_file, fps, duration_sec, cancellation_event,
                    progress_callback=stage_progress(85.0, 15.0, self.tr("Recomponiendo video...")),
                    worker_ref=worker_ref, keep_audio=keep_audio, alpha=keep_alpha,
                    trim_in=trim_in, trim_out=trim_out,
                )
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

        if cancellation_event.is_set():
            job.status = JobStatus.CANCELLED
            self.job_status_changed.emit(job.job_id, JobStatus.CANCELLED)
            logger.info(f"QueueWorker: [UPSCALE_VIDEO] Trabajo cancelado por el usuario: {job.title}")
            return

        if success:
            job.status = JobStatus.COMPLETED
            job.progress = 100.0
            job.final_filepath = output_file
            job.add_output_files([output_file], is_stem_source=False)
            self.job_progress_changed.emit(job.job_id, 100.0, self.tr("Completado"), "")
            self.job_status_changed.emit(job.job_id, JobStatus.COMPLETED)
            logger.info(f"QueueWorker: [UPSCALE_VIDEO] Reescalado finalizado exitosamente: {output_file}")
        else:
            job.status = JobStatus.FAILED
            job.error_message = error or self.tr("Error desconocido en Reescalado de Video IA")
            self.job_status_changed.emit(job.job_id, JobStatus.FAILED)
            logger.error(f"QueueWorker: [UPSCALE_VIDEO] Falló: {job.error_message} ({job.title})")

    @staticmethod
    def _default_output_path():
        try:
            from core.utils.config_manager import get_config
            return get_config().get("last_output_path") or os.getcwd()
        except Exception:
            return os.getcwd()

    def cancel_current_job(self):
        """Activa la bandera de cancelación para detener yt-dlp."""
        self._cancellation_event.set()

    def stop(self):
        """Detiene el bucle principal del hilo de trabajo."""
        self._is_running = False
        self.cancel_current_job()
        self.quit()
        self.wait()


class QueueManager(QObject):
    """
    Gestor de la cola de trabajos. Centraliza la lista de trabajos y sincroniza
    los estados con la UI de forma thread-safe utilizando señales de Qt.
    """
    job_added = Signal(str)                          # job_id
    job_removed = Signal(str)                        # job_id
    job_status_changed = Signal(str, str)            # job_id, status
    job_progress_changed = Signal(str, float, str, str) # job_id, percent, speed, eta
    queue_reordered = Signal()                       # Emitido cuando la cola cambia de orden
    queue_finished = Signal()

    def __init__(self):
        super().__init__()
        self._jobs = []
        self._mutex = QRecursiveMutex()
        self._is_paused = True # Por defecto nace pausado hasta que el usuario inicie la cola

        # Inicializar y arrancar el hilo de trabajo
        self._worker = QueueWorker(self)
        self._worker.job_status_changed.connect(self._on_worker_status_changed)
        self._worker.job_progress_changed.connect(self._on_worker_progress_changed)
        self._worker.finished_all.connect(self.queue_finished)
        self._worker.start()

    def __del__(self):
        self.stop_worker()

    def stop_worker(self):
        """Detiene el hilo secundario de la cola limpiamente."""
        with QMutexLocker(self._mutex):
            if hasattr(self, '_worker') and self._worker and self._worker.isRunning():
                self._worker.stop()

    def is_paused(self) -> bool:
        with QMutexLocker(self._mutex):
            return self._is_paused

    def start_queue(self):
        """Inicia o reanuda el procesamiento de la cola."""
        with QMutexLocker(self._mutex):
            cambio = self._is_paused
            self._is_paused = False
        if cambio:
            logger.info("QueueManager: Cola iniciada/reanudada.")

    def pause_queue(self):
        """Pausa el procesamiento de la cola (las descargas activas continúan, pero no empezará ninguna nueva).

        Solo se registra el CAMBIO de estado: al vaciarse la cola, pausan tanto el hilo
        despachador (al quedarse sin trabajos activos) como el controlador de Proceso
        Avanzado al recibir finished_all -- las dos llamadas son correctas, pero en el
        log se leían como una pausa duplicada."""
        with QMutexLocker(self._mutex):
            cambio = not self._is_paused
            self._is_paused = True
        if cambio:
            logger.info("QueueManager: Cola pausada.")

    def add_job(self, config: dict, job_type: str = "DOWNLOAD") -> str:
        """Añade un nuevo trabajo a la cola."""
        job = Job(config, job_type)
        with QMutexLocker(self._mutex):
            self._jobs.append(job)
        logger.info(f"QueueManager: Trabajo añadido ({job.job_id}): {job.title}")
        self.job_added.emit(job.job_id)
        return job.job_id

    def remove_job(self, job_id: str):
        """Remueve un trabajo de la cola. Si está activo, lo cancela primero."""
        self.cancel_job(job_id)
        with QMutexLocker(self._mutex):
            self._jobs = [j for j in self._jobs if j.job_id != job_id]
        logger.info(f"QueueManager: Trabajo eliminado ({job_id})")
        self.job_removed.emit(job_id)

    def cancel_job(self, job_id: str):
        """Cancela un trabajo específico si está corriendo o pendiente."""
        with QMutexLocker(self._mutex):
            job = next((j for j in self._jobs if j.job_id == job_id), None)
            if not job:
                return

            if job.status == JobStatus.RUNNING:
                self._worker.cancel_job(job_id)
            elif job.status == JobStatus.PENDING:
                job.status = JobStatus.CANCELLED
                self.job_status_changed.emit(job_id, JobStatus.CANCELLED)

    def clear_queue(self):
        """Limpia todos los trabajos. Cancela el actual si está corriendo."""
        self.pause_queue()
        jobs_to_remove = []
        with QMutexLocker(self._mutex):
            jobs_to_remove = list(self._jobs)
            running_job = next((j for j in self._jobs if j.status == JobStatus.RUNNING), None)
            if running_job:
                self._worker.cancel_current_job()
            self._jobs = []
        logger.info("QueueManager: Cola vaciada.")
        for j in jobs_to_remove:
            self.job_removed.emit(j.job_id)
        self.queue_reordered.emit()

    def clear_inactive_jobs(self):
        """Limpia absolutamente todos los trabajos de la cola, cancelando el actual si está corriendo o analizando."""
        self.pause_queue()
        jobs_to_remove = []
        with QMutexLocker(self._mutex):
            all_statuses = [f"{j.title} ({j.job_id}): {j.status}" for j in self._jobs]
            logger.info(f"QueueManager: clear_inactive_jobs llamada. Trabajos actuales en cola: {all_statuses}")
            
            jobs_to_remove = list(self._jobs)
            
            # Cancelar el trabajo activo si está corriendo
            running_job = next((j for j in self._jobs if j.status == JobStatus.RUNNING), None)
            if running_job:
                logger.info(f"QueueManager: Cancelando trabajo activo {running_job.job_id} al limpiar toda la lista.")
                self._worker.cancel_current_job()
                
            self._jobs = []
            
        logger.info(f"QueueManager: Eliminando {len(jobs_to_remove)} trabajos de la cola.")
        for j in jobs_to_remove:
            logger.info(f"QueueManager: Removiendo trabajo {j.job_id} ({j.title}) con estado {j.status}")
            self.job_removed.emit(j.job_id)
            
        logger.info("QueueManager: Todos los trabajos de la cola han sido limpiados.")
        self.queue_reordered.emit()

    def reset_job(self, job_id: str):
        """Restaura el estado de un trabajo terminal a PENDING."""
        terminal_statuses = (JobStatus.COMPLETED, JobStatus.CANCELLED, JobStatus.FAILED, JobStatus.SKIPPED, JobStatus.NO_AUDIO)
        with QMutexLocker(self._mutex):
            job = next((j for j in self._jobs if j.job_id == job_id), None)
            if not job or job.status not in terminal_statuses:
                return
            
            job.status = JobStatus.PENDING
            job.error_message = None
            
        self.job_progress_changed.emit(job_id, 0.0, "", "")
        self.job_status_changed.emit(job_id, JobStatus.PENDING)
        logger.info(f"QueueManager: Trabajo {job_id} reseteado a PENDING.")

    def reset_all_terminal_jobs(self):
        """Restaura todos los trabajos terminados a PENDING."""
        self.pause_queue()
        inactive_statuses = (JobStatus.COMPLETED, JobStatus.CANCELLED, JobStatus.FAILED, JobStatus.SKIPPED, JobStatus.NO_AUDIO)
        with QMutexLocker(self._mutex):
            jobs_to_reset = [j.job_id for j in self._jobs if j.status in inactive_statuses]
            
        for j_id in jobs_to_reset:
            self.reset_job(j_id)
            
        if jobs_to_reset:
            logger.info(f"QueueManager: {len(jobs_to_reset)} trabajos reseteados.")

    def update_job_data(self, job_id: str, video_data=None, request_data=None):
        """Actualiza los datos internos (video_data o request_data) de un trabajo sin alterar su estado visual."""
        with QMutexLocker(self._mutex):
            job = next((j for j in self._jobs if j.job_id == job_id), None)
            if not job:
                return
            if video_data is not None:
                job.video_data = video_data
            if request_data is not None:
                job.request_data = request_data

    def update_job_status(self, job_id: str, status: str):
        """Actualiza el estado de un trabajo y emite la señal correspondiente."""
        with QMutexLocker(self._mutex):
            job = next((j for j in self._jobs if j.job_id == job_id), None)
            if not job:
                return
            job.status = status
        self.job_status_changed.emit(job_id, status)

    def move_job_up(self, job_id: str):
        """Mueve un trabajo una posición arriba en la cola."""
        with QMutexLocker(self._mutex):
            idx = next((i for i, j in enumerate(self._jobs) if j.job_id == job_id), -1)
            if idx > 0:
                self._jobs[idx - 1], self._jobs[idx] = self._jobs[idx], self._jobs[idx - 1]
        self.queue_reordered.emit()

    def move_job_down(self, job_id: str):
        """Mueve un trabajo una posición abajo en la cola."""
        with QMutexLocker(self._mutex):
            idx = next((i for i, j in enumerate(self._jobs) if j.job_id == job_id), -1)
            if idx != -1 and idx < len(self._jobs) - 1:
                self._jobs[idx], self._jobs[idx + 1] = self._jobs[idx + 1], self._jobs[idx]
        self.queue_reordered.emit()

    def move_job_to_index(self, job_id: str, new_index: int):
        """Mueve un trabajo a una posición arbitraria de la cola (usado al arrastrar
        una tarjeta y soltarla en la lista)."""
        with QMutexLocker(self._mutex):
            idx = next((i for i, j in enumerate(self._jobs) if j.job_id == job_id), -1)
            if idx == -1:
                return
            job = self._jobs.pop(idx)
            insert_at = max(0, min(new_index, len(self._jobs)))
            self._jobs.insert(insert_at, job)
        self.queue_reordered.emit()

    def get_job(self, job_id: str) -> Job | None:
        """Retorna una copia de los datos de un trabajo (o la referencia de manera segura)."""
        with QMutexLocker(self._mutex):
            return next((j for j in self._jobs if j.job_id == job_id), None)

    def get_all_jobs(self) -> list:
        """Retorna una lista con todos los trabajos actuales."""
        with QMutexLocker(self._mutex):
            return list(self._jobs)

    def _get_next_runnable_job(self, active_heavy: int) -> Job | None:
        """Obtiene la siguiente tarea PENDING saltando los job types pesados de
        GPU/CPU (ver _HEAVY_JOB_TYPES) si ya hay uno corriendo."""
        with QMutexLocker(self._mutex):
            for j in self._jobs:
                if j.status == JobStatus.PENDING:
                    if j.job_type in _HEAVY_JOB_TYPES and active_heavy > 0:
                        continue
                    return j
            return None

    def _on_worker_status_changed(self, job_id: str, status: str):
        self.job_status_changed.emit(job_id, status)

    def _on_worker_progress_changed(self, job_id: str, percent: float, speed: str, eta: str):
        self.job_progress_changed.emit(job_id, percent, speed, eta)

    def update_max_concurrent_downloads(self, value: int):
        logger.info(f"QueueManager: Límite de descargas simultáneas actualizado a: {value}")

    @classmethod
    def get_instance(cls):
        return get_queue_manager()

    def shutdown(self):
        """Apaga el hilo de forma segura al cerrar la app."""
        self._worker.stop()

# Instancia global compartida para todo el ciclo de vida de la aplicación
_global_queue_manager = None

def get_queue_manager() -> QueueManager:
    global _global_queue_manager
    if _global_queue_manager is None:
        _global_queue_manager = QueueManager()
    return _global_queue_manager
