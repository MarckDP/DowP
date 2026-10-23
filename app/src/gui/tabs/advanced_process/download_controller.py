# src/gui/tabs/advanced_process/download_controller.py
import os
import tempfile
import time
import threading
import platform
import subprocess
from PySide6.QtCore import QObject, QCoreApplication
from core.logger.logger_manager import logger
from core.utils.config_manager import get_config
from core.utils.download_history import download_history
from core.utils.preset_manager import (
    build_recode_output_path, get_preset_manager, IA_TOOLS_NAMESPACE, ia_tools_fit, recode_preset_fits,
)
from core.utils.output_artifacts import OutputArtifactTracker, find_actual_downloaded_file, sanitize_filename
from core.utils.file_conflict_manager import quarantine_for_recode, commit_backup, rollback_backup, predict_final_extension
from core.tabs.video_tools.upscale_chain import ia_job_spec, ia_job_title, start_upscale_stage, probe_fps_and_duration
from core.utils.queue_manager import ORIGIN_ADVANCED
from core.utils.sound_notifier import (get_sound_notifier, SOURCE_ADVANCED,
                                       SOURCE_ADVANCED_SOLO)
from gui.tabs.advanced_process.workers import DownloadWorker

# Clave sentinel para self._recode_by_download en modo SOLO: ahí no hay job_id de cola
# (SOLO no pasa por QueueManager para la descarga en sí), así que el progreso/estado del
# job RECODE se traduce a output_options en vez de a una tarjeta (ver _on_recode_job_*).
_SOLO_RECODE_KEY = "__solo__"


class DownloadController(QObject):
    def __init__(self, tab):
        super().__init__(tab)
        self.tab = tab
        self.queue_mgr = tab.queue_mgr

        self.is_downloading = False
        self.solo_worker = None
        self.solo_request_data = None
        self.cancellation_event = threading.Event()
        self.paused_job_ids = set()
        self.last_downloaded_filepath = None
        self.last_progress_update = 0

        # Recodificación post-descarga (ver Proceso Avanzado > tarjeta "Recodificar"):
        # mapea el job_id del RECODE encolado -> job_id de la descarga original (o
        # _SOLO_RECODE_KEY) y guarda el backup/checkbox pendiente para resolver al
        # terminar (ver _on_recode_job_status). Con un corte de varios fragmentos, hay
        # VARIOS jobs RECODE por descarga (uno por fragmento, ver
        # _resolve_fragment_download_paths) - _group_pending/_group_results, indexados
        # por el mismo download_key, llevan la cuenta de cuántos faltan para no
        # marcar "Completado"/reactivar el botón hasta que TODOS terminen.
        self._recode_by_download = {}
        self._recode_state = {}
        self._group_pending = {}
        self._group_results = {}
        # Reescalado IA + Recodificación combinados (ver _start_post_download_recode/
        # _on_recode_job_status): job_id del job RECODE de la etapa 2 -> ruta del
        # archivo intermedio (y su carpeta temporal propia) a borrar cuando esa etapa
        # termine, pase lo que pase -- el intermedio nunca es el resultado final.
        self._chain_cleanup = {}
        # Subtítulos > "Crear con IA" (ver _start_ai_subtitles): job TRANSCRIBE ->
        # download_key, y por download_key el estado a mostrar al terminar.
        self._subs_by_download = {}
        self._subs_base = {}

        # Connect signals
        self.queue_mgr.job_progress_changed.connect(self._on_queue_job_progress)
        self.queue_mgr.job_status_changed.connect(self._on_queue_job_status)
        self.queue_mgr.job_progress_changed.connect(self._on_recode_job_progress)
        self.queue_mgr.job_status_changed.connect(self._on_recode_job_status)
        self.queue_mgr.job_progress_changed.connect(self._on_subs_job_progress)
        self.queue_mgr.job_status_changed.connect(self._on_subs_job_status)
        self.queue_mgr.job_removed.connect(self._on_download_job_removed)
        self.queue_mgr._worker.finished_all.connect(self._on_queue_finished_all)

    def _init_solo_artifacts(self):
        """Rastro de todo lo que produjo la descarga directa (modo SOLO) para poder
        arrastrarlo desde el botón de las opciones de salida -- el equivalente a la
        tarjeta de la cola en modo LOTES y a la fila en Modo Rápido."""
        if not hasattr(self, "solo_artifacts"):
            self.solo_artifacts = OutputArtifactTracker()
        return self.solo_artifacts

    def collect_solo_drag_files(self):
        """Lo que HOY sigue existiendo en disco de la última descarga SOLO: medio (o
        fragmentos), completo conservado, miniatura, subtítulos y recodificado, según lo
        que el usuario haya elegido conservar. Se resuelve en el momento del arrastre,
        nunca antes."""
        try:
            return self._init_solo_artifacts().collect()
        except Exception as e:
            logger.error(f"AdvancedProcessTab: No se pudieron reunir los archivos para arrastrar: {e}")
            return []

    def reveal_solo_outputs(self):
        """Clic simple en el botón de arrastre: abre el explorador con el resultado
        seleccionado (no solo la carpeta, como hace el botón de al lado)."""
        files = self.collect_solo_drag_files()
        if files:
            self._open_and_select(files[0])
        else:
            self.on_open_output_path_clicked()

    def _set_solo_drag_ready(self, ready):
        self.tab.output_options.set_output_drag_enabled(bool(ready) and bool(self.collect_solo_drag_files()))

    def on_download_button_clicked(self):
        """Maneja el clic en el botón de descarga, alternando entre iniciar/reanudar y pausar."""
        if self.tab.url_bar.solo_btn.isChecked():
            if self.is_downloading:
                self.pause_solo_download()
            else:
                self.start_solo_download()
        else:
            if self.is_downloading:
                self.pause_download()
            else:
                self.start_download()

    def start_download(self):
        """Inicia o reanuda la cola de trabajos."""
        self.tab._save_current_job_options()
        
        for job in self.queue_mgr.get_all_jobs():
            if job.status == "PENDING":
                if job.job_type == "PLAYLIST":
                    continue
                if not job.request_data and job.video_data:
                    job.request_data = self.tab._build_default_request_data(job.video_data, job.title)

        # Cada trabajo guarda su propio Posprocesar: revisar los preajustes de IA de
        # todos los pendientes antes de arrancar (si no, la etapa de IA fallaría al final).
        ai_presets = []
        for job in self.queue_mgr.get_all_jobs():
            if job.status != "PENDING" or getattr(job, "origin", None) != ORIGIN_ADVANCED:
                continue
            data = (job.config if job.job_type == "PLAYLIST" else job.request_data) or {}
            if data.get("upscale_enabled"):
                ai_presets.append(data.get("upscale_preset_name"))
        if ai_presets and not self.tab.recode_controller.ensure_ai_models_ready(ai_presets):
            return
        if not self._ai_subtitles_ready(
                (job.config if job.job_type == "PLAYLIST" else job.request_data) or {}
                for job in self.queue_mgr.get_all_jobs()
                if job.status == "PENDING" and getattr(job, "origin", None) == ORIGIN_ADVANCED):
            return
        self.tab._apply_global_output_path()

        self.queue_mgr.start_queue(ORIGIN_ADVANCED)
        
        self.tab.output_options.btn_start_download.setEnabled(True)
        self.tab.output_options.set_download_state("pause_queue", QCoreApplication.translate("AdvancedProcessTab", "Pausar cola"))
        self.is_downloading = True
        self.tab.url_bar.solo_btn.setEnabled(False)
        self.update_queue_main_progress()

    def start_solo_download(self):
        """Inicia una descarga directa en modo SOLO sin usar el gestor de colas."""
        req_data = self.tab._collect_request_data()
        if not req_data:
            return
        # Posprocesar > IA con el modelo sin descargar: ofrecerlo y no empezar todavía.
        if req_data.get("upscale_enabled") and not self.tab.recode_controller.ensure_ai_models_ready(
                [req_data.get("upscale_preset_name")]):
            return
        if not self._ai_subtitles_ready([req_data]):
            return

        self.cancellation_event.clear()
        self.solo_worker = DownloadWorker(req_data, self.cancellation_event)
        self.solo_request_data = req_data.copy()
        # Tarjeta del historial de ESTE análisis, tomada ahora: mientras se descarga, el
        # usuario puede analizar otra URL. Si esa tarjeta ya se descargó (otra descarga
        # desde el mismo análisis), esta va a una tarjeta nueva.
        self._solo_history_key = download_history().key_for_new_download(
            getattr(self.tab, "_current_history_key", None))

        # Empieza un proceso nuevo: lo que se pudiera arrastrar de la descarga anterior
        # ya no corresponde a lo que muestra la barra.
        self._init_solo_artifacts().clear()
        self.tab.output_options.set_output_drag_enabled(False)

        has_fragments = bool(req_data.get("selected_fragments"))

        self.is_downloading = True
        self.tab.url_bar.solo_btn.setEnabled(False)
        self.tab.output_options.set_download_state("cancelling", QCoreApplication.translate("AdvancedProcessTab", "Cancelar"))
        self.tab.output_options.set_progress(0, QCoreApplication.translate("AdvancedProcessTab", "Iniciando descarga..."), "running")
        if self.tab.taskbar_manager:
            self.tab.taskbar_manager.set_state("indeterminate")

        def on_solo_progress(d):
            from core.ytdlp_logic.analyzer import strip_ansi_codes

            if d.get("status") == "artifact":
                # Archivo creado por la descarga, con su ruta exacta (ver
                # DownloaderMaster._note_artifact).
                self._init_solo_artifacts().add([d.get("path")], is_stem_source=False)
                return

            if d.get("status") == "fragment_progress":
                idx = d.get("fragment_index")
                total = d.get("fragment_count")
                verb = QCoreApplication.translate("AdvancedProcessTab", "Cortando") if d.get("phase") == "cutting" else QCoreApplication.translate("AdvancedProcessTab", "Descargando")
                msg = QCoreApplication.translate("AdvancedProcessTab", "{0} fragmento {1} de {2}").format(verb, idx, total)
                self.tab.output_options.set_progress(-1, msg, "running")
                if self.tab.taskbar_manager:
                    self.tab.taskbar_manager.set_state("indeterminate")
                return

            # Mientras el job tenga fragmentos, el progreso numérico crudo de
            # yt-dlp (downloading/finished) no representa el avance real del
            # job completo (se dispara una vez por fragmento) — se ignora aquí
            # y la barra queda a cargo únicamente de fragment_progress.
            if has_fragments:
                return

            if d.get("status") == "downloading":
                p_str = strip_ansi_codes(d.get('_percent_str', '0%')).replace('%','').strip()
                try:
                    val = float(p_str)
                    speed = strip_ansi_codes(d.get('_speed_str', '')).strip() or '...'
                    eta = strip_ansi_codes(d.get('_eta_str', '')).strip() or '...'
                    msg = f"{int(val)}% — {speed} — ETA: {eta}"
                    self.tab.output_options.set_progress(int(val), msg, "downloading")
                    if self.tab.taskbar_manager:
                        self.tab.taskbar_manager.set_state("normal")
                        self.tab.taskbar_manager.set_value(int(val))
                except Exception:
                    pass
            elif d.get("status") == "finished":
                if d.get("filename"):
                    self.last_downloaded_filepath = d.get("filename")
                    # Nombre DERIVADO (stream sin fusionar, o un fragmento ya cortado):
                    # se registra igual; si yt-dlp lo borra al fusionar, el arrastre lo
                    # descarta al filtrar por existencia (ver output_artifacts).
                    self._init_solo_artifacts().add([d.get("filename")])
                self.tab.output_options.set_progress(100, QCoreApplication.translate("AdvancedProcessTab", "Procesando descarga..."), "downloading")

        def on_solo_finished(success, message):
            self.is_downloading = False
            self.tab.output_options.set_download_state("idle")
            self.tab.url_bar.solo_btn.setEnabled(True)
            if self.tab.taskbar_manager:
                self.tab.taskbar_manager.stop()
                
            if success:
                logger.info("AdvancedProcessTab: Descarga directa SOLO finalizada con éxito.")
                download_history().mark_downloaded(getattr(self, "_solo_history_key", None))

                # self.solo_worker.request_data es el MISMO dict que DownloadWorker pasó a
                # DownloaderMaster.download() (sin copiar, ver workers.py::DownloadWorker) -
                # ahí es donde queda mutado con el título REAL (sanitizado y renombrado si
                # hubo conflicto). self.solo_request_data es una copia tomada ANTES de
                # arrancar la descarga (ver start_solo_download más arriba) y nunca ve esas
                # mutaciones - sirve para los ajustes elegidos en la UI (preset, keep
                # original, etc.), no para reconstruir la ruta final del archivo.
                resolved_request_data = self.solo_worker.request_data if self.solo_worker else self.solo_request_data
                # Título REAL del medio (con el nombre definitivo si hubo conflicto): lo usan
                # la recodificación, la IA posterior y los subtítulos de abajo. Faltaba desde
                # el commit 9c56619 (2026-09-26), que borró su definición pero no sus usos: en
                # SOLO, todo el posprocesado fallaba en silencio con un NameError.
                title = ((resolved_request_data or {}).get("title")
                         or (self.solo_request_data or {}).get("title") or "").strip()

                if self.solo_request_data.get("recode_enabled") or self.solo_request_data.get("upscale_enabled"):
                    # No se marca "Descarga completada" todavía: la misma barra sigue
                    # con "Recodificando..." (ver _on_recode_job_progress/_status) hasta
                    # que el/los job(s) RECODE encolados resuelvan.
                    fragment_paths = self._resolve_fragment_download_paths(resolved_request_data)
                    self._init_solo_artifacts().add([p for p, _suffix in fragment_paths])
                    if fragment_paths:
                        # Un job RECODE por fragmento - cada uno se pone en cuarentena y
                        # se recodifica por separado (ver _resolve_fragment_download_paths),
                        # todos reportando "Recodificando N de M..." a la MISMA barra.
                        total = len(fragment_paths)
                        for i, (actual_path, suffix) in enumerate(fragment_paths, start=1):
                            self._start_post_download_recode(
                                actual_path=actual_path,
                                request_data=self.solo_request_data,
                                video_data=self.tab._current_video_data,
                                title=f"{title} - {suffix}" if title else suffix,
                                download_key=_SOLO_RECODE_KEY,
                                fragment_position=i,
                                fragment_total=total,
                            )
                    else:
                        actual_path = self._resolve_final_download_path(resolved_request_data, self.last_downloaded_filepath)
                        self._init_solo_artifacts().add([actual_path])
                        self._start_post_download_recode(
                            actual_path=actual_path,
                            request_data=self.solo_request_data,
                            video_data=self.tab._current_video_data,
                            title=title or QCoreApplication.translate("AdvancedProcessTab", "Descarga"),
                            download_key=_SOLO_RECODE_KEY,
                        )
                else:
                    self.tab.output_options.set_progress(100, QCoreApplication.translate("AdvancedProcessTab", "Descarga completada con éxito"), "done")
                    get_sound_notifier().single_finished(SOURCE_ADVANCED_SOLO, True)
                    actual_path = self._resolve_final_download_path(resolved_request_data, self.last_downloaded_filepath)
                    # Sin recodificación pedida, el proceso terminó aquí: ya se puede
                    # arrastrar el resultado. Con recodificación, el botón se habilita
                    # recién cuando el/los job(s) RECODE resuelven (ver
                    # _on_recode_job_status y _finalize_group).
                    fragment_paths = self._resolve_fragment_download_paths(resolved_request_data)
                    tracker = self._init_solo_artifacts()
                    tracker.add([p for p, _suffix in fragment_paths])
                    tracker.add([actual_path])
                    self._set_solo_drag_ready(True)
                    if fragment_paths:
                        for p, _suffix in fragment_paths:
                            self._send_to_editor_if_enabled(p, resolved_request_data)
                    else:
                        self._send_to_editor_if_enabled(actual_path or self.last_downloaded_filepath, resolved_request_data)
                    self._start_ai_subtitles(
                        _SOLO_RECODE_KEY,
                        [p for p, _suffix in fragment_paths] or [actual_path or self.last_downloaded_filepath],
                        self.solo_request_data, self.tab._current_video_data, title)
                self._history_sync(_SOLO_RECODE_KEY)
            else:
                self.tab.output_options.set_progress(0, QCoreApplication.translate("AdvancedProcessTab", "Error: {0}").format(message), "wait")
                logger.error(f"AdvancedProcessTab: Error en descarga directa SOLO: {message}")
                if not self.cancellation_event.is_set():
                    get_sound_notifier().single_finished(SOURCE_ADVANCED_SOLO, False)

        self.solo_worker.progress.connect(on_solo_progress)
        self.solo_worker.job_finished.connect(on_solo_finished)
        self.solo_worker.finished.connect(self.solo_worker.deleteLater)
        self.solo_worker.start()

    def pause_solo_download(self):
        """Pausa (cancela) la descarga directa en modo SOLO."""
        if self.is_downloading and self.solo_worker:
            logger.info("AdvancedProcessTab: Cancelando descarga directa SOLO...")
            self.cancellation_event.set()
            self.is_downloading = False
            self.tab.output_options.set_download_state("idle")
            self.tab.output_options.set_progress(0, QCoreApplication.translate("AdvancedProcessTab", "Descarga cancelada"), "wait")
            self.tab.url_bar.solo_btn.setEnabled(True)

    def pause_download(self):
        """Pausa la cola sin cancelar los trabajos pendientes."""
        if self.is_downloading:
            logger.info("AdvancedProcessTab: Pausando cola de descargas...")
            self.queue_mgr.pause_queue(ORIGIN_ADVANCED)

            # Solo lo de esta pestaña: un reescalado del Modo Rápido o una
            # recodificación de Herramientas Multimedia no se tocan.
            jobs = self._own_jobs()
            running_jobs = [j for j in jobs if j.status == "RUNNING"]
            if running_jobs:
                for job in running_jobs:
                    self.paused_job_ids.add(job.job_id)
                    self.queue_mgr.pause_job(job.job_id)
                
                self.tab.output_options.set_download_state("paused", QCoreApplication.translate("AdvancedProcessTab", "Pausando..."))
                self.tab.output_options.btn_start_download.setEnabled(False)
            else:
                self.is_downloading = False
                self.tab.output_options.set_download_state("paused", QCoreApplication.translate("AdvancedProcessTab", "Reanudar cola"))
                self.tab.output_options.btn_start_download.setEnabled(True)

    def _own_jobs(self):
        """Jobs del QueueManager que le corresponden a ESTA pestaña (Proceso Avanzado).
        El QueueManager es compartido con Herramientas Multimedia (jobs "RECODE") - sin
        este filtro, encolar una recodificación desde la otra pestaña contaminaba el
        progreso agregado de aquí. Ahora se incluyen los jobs RECODE propios
        (los que están en _recode_by_download) para que el modo lotes espere
        su finalización antes de marcar todo como "Completado"."""
        return [j for j in self.queue_mgr.get_all_jobs()
                if j.origin == ORIGIN_ADVANCED and (
                    j.job_type in ("DOWNLOAD", "PLAYLIST") or
                    (j.job_type == "RECODE" and j.job_id in self._recode_by_download) or
                    (j.job_type == "TRANSCRIBE" and j.job_id in self._subs_by_download))]

    def update_queue_main_progress(self):
        """
        Actualiza la barra de progreso principal evaluando toda la cola de forma
        global. La cola soporta varios jobs corriendo en simultáneo
        (max_concurrent_downloads, ver QueueWorker.run() en queue_manager.py),
        así que "el progreso de un job en particular" deja de tener sentido en
        cuanto hay más de uno activo — en ese caso se muestra cuántos de
        cuántos ya terminaron ("X de Y completados"), igual que en Modo
        Rápido. Solo se muestra el % real de un job cuando es el único
        corriendo y no tiene fragmentos (ahí sí hay un solo número que
        representa fielmente lo que está pasando).
        """
        jobs = self._own_jobs()
        if not jobs:
            if self.tab.taskbar_manager:
                self.tab.taskbar_manager.stop()
            return

        total = len(jobs)
        completed = 0
        other_done = 0
        running_jobs = []
        analyzing_count = 0

        for j in jobs:
            if j.status == "COMPLETED":
                completed += 1
            elif j.status in ("FAILED", "CANCELLED", "SKIPPED"):
                other_done += 1
            elif j.status == "RUNNING":
                running_jobs.append(j)
            elif j.status == "ANALYZING":
                analyzing_count += 1

        processed = completed + other_done
        taskbar_state = "stop"
        taskbar_value = None

        single_job = running_jobs[0] if len(running_jobs) == 1 else None
        single_has_fragments = bool(
            single_job and single_job.request_data and single_job.request_data.get("selected_fragments")
        )

        if single_job and not single_has_fragments:
            msg = (
                f"({processed + 1}/{total}) {int(single_job.progress)}% — {single_job.speed} — ETA: {single_job.eta}"
                if total > 1 else
                f"{int(single_job.progress)}% — {single_job.speed} — ETA: {single_job.eta}"
            )
            percent = single_job.progress
            state = "downloading"
            taskbar_state = "normal"
            taskbar_value = int(percent)

        elif running_jobs:
            # Más de un job corriendo (o el único que corre tiene fragmentos):
            # no hay un % único representativo del conjunto.
            msg = f"{processed} de {total} completados"
            percent = int(processed / total * 100) if total else 0
            state = "downloading"
            taskbar_state = "indeterminate"

        elif analyzing_count:
            msg = QCoreApplication.translate("AdvancedProcessTab", "Analizando...")
            percent = 0
            state = "running"
            taskbar_state = "indeterminate"

        else:
            if processed == total and total > 0:
                msg = f"Proceso completado ({completed}/{total})"
                percent = 100
                state = "done"
            else:
                msg = f"En espera ({processed}/{total})..."
                percent = 0
                state = "wait"

        self.tab.output_options.set_progress(int(percent), msg, state)

        if self.tab.taskbar_manager:
            if taskbar_state == "stop":
                self.tab.taskbar_manager.stop()
            else:
                self.tab.taskbar_manager.set_state(taskbar_state)
                if taskbar_value is not None:
                    self.tab.taskbar_manager.set_value(taskbar_value)

    def _on_queue_job_progress(self, job_id, percent, speed, eta):
        current_time = time.time()
        if current_time - self.last_progress_update < 0.33 and percent < 100:
            return
        self.last_progress_update = current_time
        self.update_queue_main_progress()

    def _on_queue_finished_all(self, origin):
        # La cola avisa por carril: el fin de un posprocesado del Modo Rápido o de
        # Herramientas Multimedia no es el fin de las descargas de esta pestaña.
        if origin != ORIGIN_ADVANCED:
            return
        self.queue_mgr.pause_queue(ORIGIN_ADVANCED)
        get_sound_notifier().group_finished(SOURCE_ADVANCED)
        self.is_downloading = False
        jobs = self._own_jobs()
        has_pending = any(j.status == "PENDING" for j in jobs)
        if has_pending:
            self.tab.output_options.set_download_state("paused", QCoreApplication.translate("AdvancedProcessTab", "Reanudar cola"))
        else:
            self.tab.output_options.set_download_state("idle")
        self.tab.output_options.btn_start_download.setEnabled(True)
        self.tab.subtitle_controller.on_subtitle_selection_changed()
        self.tab.subtitle_options.btn_download_subtitles.setEnabled(True)
        self.tab.url_bar.solo_btn.setEnabled(True)
        self.update_queue_main_progress()
        logger.info("AdvancedProcessTab: Descargas finalizadas.")

    def on_queue_panel_action(self, action):
        jobs = self._own_jobs()
        
        if not jobs:
            self.is_downloading = False
            self.tab.output_options.set_download_state("idle")
            self.tab.output_options.btn_start_download.setEnabled(False)
            self.tab._selected_job_id = None
            self.tab._current_video_data = None
            self.tab.video_details.reset_ui()
            self.tab.subtitle_controller.clear_subtitles()
            self.tab.output_options.set_progress(0, QCoreApplication.translate("AdvancedProcessTab", "En espera"), "wait")
        else:
            if action == "reset":
                self.is_downloading = False
                has_pending = any(j.status == "PENDING" for j in jobs)
                if has_pending:
                    self.tab.output_options.set_download_state("paused", QCoreApplication.translate("AdvancedProcessTab", "Reanudar cola"))
                    self.tab.output_options.btn_start_download.setEnabled(True)
                else:
                    self.tab.output_options.set_download_state("idle")
                    self.tab.output_options.btn_start_download.setEnabled(True)
        
        self.update_queue_main_progress()

    def _on_queue_job_status(self, job_id, status):
        # Filtro de tipo (ver _own_jobs): sin esto, un job "RECODE" fallido de Herramientas
        # Multimedia se logueaba aca como "Fallo en descarga" (ver conversación).
        owned_job = self.queue_mgr.get_job(job_id)
        if not owned_job or owned_job.job_type not in ("DOWNLOAD", "PLAYLIST"):
            return

        self.update_queue_main_progress()

        if status == "COMPLETED":
            job = self.queue_mgr.get_job(job_id)
            # Historial: fuera del `if job.request_data` de abajo, porque los jobs de
            # PLAYLIST no tienen request_data y también cuentan como descargados.
            download_history().mark_job_downloaded(job_id)
            self._history_sync(job_id)
            # Sonido: sin posprocesado, el elemento terminó aquí (incluidas las
            # PLAYLIST, que no tienen request_data). Con posprocesado, avisa
            # _notify_sound_after_recode cuando se resuelve la recodificación.
            has_post = bool(
                job and job.job_type == "DOWNLOAD" and job.request_data
                and (job.request_data.get("recode_enabled") or job.request_data.get("upscale_enabled")))
            if not has_post:
                get_sound_notifier().item_finished(SOURCE_ADVANCED, True)
            if job and job.request_data:
                # Rutas reales del resultado, para poder arrastrar la tarjeta terminada
                # a otra aplicación (ver queue_panel.py::_on_card_file_drag). Los
                # sidecars (miniatura, subtítulos) llegan aparte, por el manifiesto del
                # descargador (eventos 'artifact').
                job.add_output_files(
                    [path for path, _suffix in self._resolve_fragment_download_paths(job.request_data)]
                )
                job.add_output_files([self._find_actual_downloaded_file(job.final_filepath)])
                self._history_sync(job_id)

                if job.job_type == "DOWNLOAD" and (job.request_data.get("recode_enabled") or job.request_data.get("upscale_enabled")):
                    # job.final_filepath ya viene resuelto correctamente aquí (ver
                    # QueueWorker._execute_download en queue_manager.py, que lo reconstruye
                    # con el título REAL post-conflicto — job.request_data en cambio nunca
                    # se actualiza con ese título, así que NO sirve para reconstruir la ruta).
                    fragment_paths = self._resolve_fragment_download_paths(job.request_data)
                    if fragment_paths:
                        # Un job RECODE por fragmento (ver _resolve_fragment_download_paths) -
                        # sin esto solo se recodificaba job.final_filepath, que con varios
                        # fragmentos apunta a uno solo (normalmente el último). Todos
                        # reportan "Recodificando N de M..." a la MISMA tarjeta.
                        total = len(fragment_paths)
                        for i, (actual_path, suffix) in enumerate(fragment_paths, start=1):
                            self._start_post_download_recode(
                                actual_path=actual_path,
                                request_data=job.request_data,
                                video_data=job.video_data or job.analysis_data,
                                title=f"{job.title} - {suffix}",
                                download_key=job_id,
                                fragment_position=i,
                                fragment_total=total,
                            )
                    else:
                        self._start_post_download_recode(
                            actual_path=self._find_actual_downloaded_file(job.final_filepath),
                            request_data=job.request_data,
                            video_data=job.video_data or job.analysis_data,
                            title=job.title,
                            download_key=job_id,
                        )
                else:
                    # Archivos sin recodificar en modo lotes (o playlist): se envían al editor
                    fragment_paths = self._resolve_fragment_download_paths(job.request_data)
                    if fragment_paths:
                        for p, _suffix in fragment_paths:
                            self._send_to_editor_if_enabled(p, job.request_data)
                    elif job.final_filepath:
                        actual_path = self._find_actual_downloaded_file(job.final_filepath)
                        self._send_to_editor_if_enabled(actual_path or job.final_filepath, job.request_data)
                    self._start_ai_subtitles(
                        job_id,
                        [p for p, _suffix in fragment_paths]
                        or [self._find_actual_downloaded_file(job.final_filepath) or job.final_filepath],
                        job.request_data, job.video_data or job.analysis_data, job.title)
        elif status in ("FAILED", "CANCELLED"):
            job = self.queue_mgr.get_job(job_id)
            err_msg = job.error_message if job else ""
            if status == "FAILED":
                logger.error(f"AdvancedProcessTab: Fallo en descarga de {job_id}: {err_msg}")
                get_sound_notifier().item_finished(SOURCE_ADVANCED, False)
            
            if status == "CANCELLED" and job_id in self.paused_job_ids:
                self.paused_job_ids.discard(job_id)
                self.queue_mgr.reset_job(job_id)
        
        if self.is_downloading and self.queue_mgr.is_paused(ORIGIN_ADVANCED):
            jobs = self._own_jobs()
            if not any(j.status == "RUNNING" for j in jobs):
                self.is_downloading = False
                self.tab.output_options.set_download_state("paused", QCoreApplication.translate("AdvancedProcessTab", "Reanudar cola"))
                self.tab.output_options.btn_start_download.setEnabled(True)
                self.tab.subtitle_options.btn_download_subtitles.setEnabled(True)
                self.tab.url_bar.solo_btn.setEnabled(True)

    def _on_download_job_removed(self, job_id):
        """
        Si se elimina de la cola (botón "X" de la tarjeta) un job DOWNLOAD que todavía
        tiene una recodificación en curso, cancelarla también - QueuePanel conecta el
        botón de borrar directo a queue_mgr.remove_job() (ver queue_panel.py), sin pasar
        por aquí, así que sin esto el job RECODE quedaba huérfano: la tarjeta desaparece
        pero ffmpeg sigue corriendo de fondo sin que nada lo controle (ver conversación,
        reproducido con un GIF grande que tardaba minutos).

        queue_mgr.remove_job() en el recode dispara la misma cancelación que ya usa
        cualquier otro cancel (worker.cancel() -> termina el proceso ffmpeg -> termina
        emitiendo job_status_changed CANCELLED), que _on_recode_job_status ya sabe
        resolver (restaura el .dbak) - no hace falta duplicar esa lógica aquí.
        """
        orphaned_recode_ids = [
            recode_id for recode_id, target in self._recode_by_download.items()
            if target == job_id
        ]
        for recode_id in orphaned_recode_ids:
            logger.info(
                f"AdvancedProcessTab: Job {job_id} eliminado con una recodificación en "
                f"curso, cancelando el job RECODE asociado ({recode_id})."
            )
            self.queue_mgr.remove_job(recode_id)
        for subs_id in [s for s, target in self._subs_by_download.items() if target == job_id]:
            logger.info(f"AdvancedProcessTab: Job {job_id} eliminado, se cancela la creación de subtítulos ({subs_id}).")
            self.queue_mgr.remove_job(subs_id)

    def _send_to_editor_if_enabled(self, path, request_data):
        if not path:
            return
        from core.services.editor_integration_manager import EditorIntegrationManager
        editor_mgr = EditorIntegrationManager.get_instance()
        if editor_mgr and editor_mgr.is_auto_send_enabled:
            actual_path = self._find_actual_downloaded_file(path)
            editor_mgr.process_raw_download(actual_path or path, request_data)

    def _recode_status_text(self, position, total, label: str | None = None):
        label = label or QCoreApplication.translate("AdvancedProcessTab", "Recodificando...")
        if total and total > 1 and position:
            return QCoreApplication.translate("AdvancedProcessTab", "{0} ({1} de {2})").format(label, position, total)
        return label

    def _finalize_group(self, download_key):
        """Resuelve el estado final (Completado/Error) de un grupo de recodificaciones
        por fragmento (ver _start_post_download_recode) una vez que TODAS terminaron -
        llamado tanto desde _on_recode_job_status como desde _note_group_skip (una que
        ni siquiera llegó a encolarse, ej. archivo faltante o preset inválido)."""
        results = self._group_results.pop(download_key, {"all_ok": True, "final_paths": []})
        self._group_pending.pop(download_key, None)
        self._mark_recode_pending(download_key, False)
        if not results.get("cancelled"):
            self._notify_sound_after_recode(download_key, results["all_ok"])
        if download_key == _SOLO_RECODE_KEY:
            final_path = results["final_paths"][-1] if results["final_paths"] else None
            if final_path:
                self.last_downloaded_filepath = final_path
            if results["all_ok"]:
                self.tab.output_options.set_progress(100, QCoreApplication.translate("AdvancedProcessTab", "Descarga completada con éxito"), "done")
            else:
                self.tab.output_options.set_progress(0, QCoreApplication.translate("AdvancedProcessTab", "Error al recodificar (original conservado)"), "wait")
        else:
            card = self.tab.queue_panel.cards.get(download_key)
            if card:
                text = QCoreApplication.translate("AdvancedProcessTab", "Completado") if results["all_ok"] else QCoreApplication.translate("AdvancedProcessTab", "Error al recodificar")
                # Mismo criterio que una recodificación suelta: los fragmentos se
                # descargaron, así que un fallo de recodificación es parcial (naranja).
                card.update_progress(100, speed_text="", status_text=text, partial=not results["all_ok"])

    def _notify_sound_after_recode(self, download_key, ok):
        """Sonido al terminar el posprocesado de una descarga: en SOLO es el final del
        proceso; en LOTES es un elemento más (el grupo suena con finished_all)."""
        if download_key == _SOLO_RECODE_KEY:
            get_sound_notifier().single_finished(SOURCE_ADVANCED_SOLO, ok)
        else:
            get_sound_notifier().item_finished(SOURCE_ADVANCED, ok)

    def _register_recode_outputs(self, download_key, paths, succeeded=True):
        """Suma al arrastre lo que dejó la recodificación. La salida recodificada cuenta
        como procesada (no es el medio principal del historial); el archivo restaurado
        tras un fallo, en cambio, ES el medio original."""
        paths = [p for p in (paths or []) if p]
        if not paths:
            return
        if download_key == _SOLO_RECODE_KEY:
            self._init_solo_artifacts().add(paths, is_stem_source=not succeeded)
        else:
            job = self.queue_mgr.get_job(download_key)
            if job:
                job.add_output_files(paths, is_stem_source=not succeeded)
        self._history_sync(download_key)

    def _history_sync(self, download_key):
        """Copia al historial de descargas el rastro de archivos de la descarga directa
        (modo SOLO) o de un job de la cola: los MISMOS que usa su arrastre, que el
        historial resuelve igual al consultarlos (ver download_history.record_outputs)."""
        history = download_history()
        if download_key == _SOLO_RECODE_KEY:
            key = getattr(self, "_solo_history_key", None)
            tracker = self._init_solo_artifacts()
        else:
            key = history.key_for_job(download_key)
            job = self.queue_mgr.get_job(download_key)
            tracker = job.artifacts if job else None
        if key and tracker is not None:
            history.record_outputs(key, tracker.known(), tracker.stems())

    def _note_group_skip(self, download_key, fragment_total):
        """Descuenta del grupo un fragmento cuya recodificación ni llegó a encolarse
        (ver _start_post_download_recode) - sin esto, el grupo se quedaría esperando
        para siempre a un job que nunca existió."""
        if download_key not in self._group_pending:
            self._group_pending[download_key] = fragment_total
            self._group_results[download_key] = {"all_ok": True, "final_paths": []}
        self._group_results[download_key]["all_ok"] = False
        remaining = self._group_pending[download_key] - 1
        self._group_pending[download_key] = remaining
        if remaining <= 0:
            self._finalize_group(download_key)

    def _mark_recode_pending(self, download_key, pending):
        """Bloquea/libera el arrastre del resultado mientras haya una recodificación en
        curso: la descarga ya terminó (la tarjeta dice "Completado" y en SOLO la barra
        llegó al 100%), pero arrastrar ahora entregaría el archivo a medio hacer."""
        if download_key == _SOLO_RECODE_KEY:
            if pending:
                self.tab.output_options.set_output_drag_enabled(False)
            else:
                self._set_solo_drag_ready(True)
            return
        card = self.tab.queue_panel.cards.get(download_key)
        if card:
            card.set_recode_pending(pending)

    def _start_post_download_recode(self, actual_path, request_data, video_data, title, download_key,
                                     fragment_position=None, fragment_total=None):
        """
        Encola el/los job(s) de posprocesado async para un medio recién descargado
        (individual, LOTES o SOLO — `download_key` es el job_id de la descarga para
        LOTES, o _SOLO_RECODE_KEY para SOLO, y decide cómo se refleja el progreso:
        tarjeta de la cola vs. la barra de output_options). No se usa para PLAYLIST,
        que recodifica cada hijo síncrona e inline dentro de
        QueueWorker._execute_playlist (ver core/utils/queue_manager.py) -- Reescalado
        IA no está disponible ahí (ver conversación, fuera de alcance por ahora).

        Recodificación y Reescalado IA son combinables (ver tarjeta "Posprocesar",
        recode_options.py): con las dos activas se encadenan -- Reescalado IA primero
        (hacia un archivo temporal propio, invisible), Recodificación después (con el
        intermedio como entrada, ver _continue_chain_to_recode) -- mismo orden y
        mismas razones que ya se usan en Herramientas Multimedia
        (video_tools_view.py::_start_chained_jobs).

        fragment_position/fragment_total (1-based) son solo para el texto de progreso
        cuando esta descarga es un corte de varios fragmentos y hay una llamada a este
        método por cada uno (ver _resolve_fragment_download_paths) - todas comparten
        la misma tarjeta/barra, así que no se resuelve "Completado" hasta que el grupo
        entero termine (ver _finalize_group).

        El original se pone en cuarentena (.dbak) ANTES de encolar, para que quede
        protegido incluso si la app se cierra mientras el trabajo todavía está
        esperando su turno en la cola.
        """
        is_group = bool(fragment_total and fragment_total > 1)
        recode_enabled = bool(request_data.get("recode_enabled"))
        upscale_enabled = bool(request_data.get("upscale_enabled"))

        if not actual_path or not os.path.exists(actual_path) or os.path.isdir(actual_path):
            logger.warning(f"AdvancedProcessTab: No se encontró el archivo descargado para posprocesar ({title}).")
            if is_group:
                self._note_group_skip(download_key, fragment_total)
            else:
                # No hay nada que esperar: lo que quedó en disco ya se puede
                # arrastrar (si no, el botón/tarjeta quedaría bloqueado para siempre).
                self._mark_recode_pending(download_key, False)
            return

        # Red de seguridad: el modo de la descarga pudo cambiar después de elegir el
        # posprocesado (ej. el "Modo global" de Proceso Avanzado cambia los ítems ya en
        # cola). Lo que no tiene sentido en ese modo se omite (misma regla que la
        # tarjeta "Posprocesar", ver preset_manager.recode_preset_fits).
        stream_mode = request_data.get("mode") or "video+audio"
        if upscale_enabled and not ia_tools_fit(stream_mode):
            logger.info(f"AdvancedProcessTab: Herramientas IA omitidas: la descarga es Solo Audio ({title}).")
            upscale_enabled = False
        if recode_enabled:
            recode_settings = get_preset_manager().get_settings(
                "video_tools/avanzado", request_data.get("recode_preset_name"))
            if recode_settings and not recode_preset_fits(recode_settings, stream_mode):
                logger.info(f"AdvancedProcessTab: Recodificación omitida: el preajuste no sirve para una "
                            f"descarga '{stream_mode}' ({title}).")
                recode_enabled = False
        if not recode_enabled and not upscale_enabled:
            if is_group:
                self._note_group_skip(download_key, fragment_total)
            else:
                self._mark_recode_pending(download_key, False)
            self._start_ai_subtitles(download_key, [actual_path], request_data, video_data, title)
            return

        # El archivo final se nombra con el preset/prefijo/sufijo de la ÚLTIMA etapa
        # que corre de verdad -- Recodificación si está activa (sola o encadenada),
        # Reescalado IA si es la única.
        if recode_enabled:
            preset_name = request_data.get("recode_preset_name")
            prefix = request_data.get("recode_filename_prefix") or ""
            suffix = request_data.get("recode_filename_suffix") or ""
            namespace = "video_tools/avanzado"
        else:
            preset_name = request_data.get("upscale_preset_name")
            prefix = request_data.get("upscale_filename_prefix") or ""
            suffix = request_data.get("upscale_filename_suffix") or ""
            namespace = IA_TOOLS_NAMESPACE

        settings, out_file = build_recode_output_path(
            actual_path, namespace, preset_name, prefix=prefix, suffix=suffix
        )
        if not settings:
            logger.warning(f"AdvancedProcessTab: Preajuste de posprocesado '{preset_name}' no encontrado, se omite ({title}).")
            if is_group:
                self._note_group_skip(download_key, fragment_total)
            else:
                self._mark_recode_pending(download_key, False)
            self._start_ai_subtitles(download_key, [actual_path], request_data, video_data, title)
            return

        try:
            backup_path = quarantine_for_recode(actual_path)
        except Exception as e:
            logger.error(f"AdvancedProcessTab: No se pudo poner en cuarentena '{actual_path}': {e}")
            if is_group:
                self._note_group_skip(download_key, fragment_total)
            else:
                self._mark_recode_pending(download_key, False)
            self._start_ai_subtitles(download_key, [actual_path], request_data, video_data, title)
            return

        duration_sec = (video_data or {}).get("duration") or 0.0

        if is_group and download_key not in self._group_pending:
            self._group_pending[download_key] = fragment_total
            self._group_results[download_key] = {"all_ok": True, "final_paths": []}

        self._mark_recode_pending(download_key, True)

        chain_next = None
        stage_label = self.tr("Recodificando...")
        if recode_enabled and upscale_enabled:
            # Las dos activas: encadenar. El reescalado va a un temporal propio, NO al
            # out_file calculado arriba (ese es para Recodificación, la etapa real que
            # produce el resultado final) -- ver _continue_chain_to_recode.
            upscale_preset_name = request_data.get("upscale_preset_name")
            upscale_settings = get_preset_manager().get_settings(IA_TOOLS_NAMESPACE, upscale_preset_name)
            if not upscale_settings:
                logger.warning(f"AdvancedProcessTab: Preajuste de Reescalado IA '{upscale_preset_name}' no encontrado, se omite esa etapa ({title}).")
            else:
                fps, real_duration = probe_fps_and_duration(backup_path, duration_sec)
                duration_sec = real_duration
                chain_temp_dir = tempfile.mkdtemp(prefix="dowp_chain_ap_")
                job_id, _intermediate_path = start_upscale_stage(
                    self.queue_mgr, backup_path, upscale_settings, chain_temp_dir,
                    fps, duration_sec, title=ia_job_title(upscale_settings, title),
                    origin=ORIGIN_ADVANCED,
                )
                chain_next = {
                    "original_path": actual_path,
                    "recode_preset_name": request_data.get("recode_preset_name"),
                    "recode_prefix": request_data.get("recode_filename_prefix") or "",
                    "recode_suffix": request_data.get("recode_filename_suffix") or "",
                }
                stage_label = self._ia_stage_label(upscale_settings)

        if chain_next is None:
            if upscale_enabled and not recode_enabled:
                fps, real_duration = probe_fps_and_duration(backup_path, duration_sec)
                job_type, options_key = ia_job_spec(settings)
                job_id = self.queue_mgr.add_job({
                    "input_path": backup_path,
                    "output_path": out_file,
                    options_key: settings,
                    "fps": fps,
                    "duration_sec": real_duration,
                    "title": ia_job_title(settings, title),
                }, job_type, origin=ORIGIN_ADVANCED)
                stage_label = self._ia_stage_label(settings)
            else:
                job_id = self.queue_mgr.add_job({
                    "input_path": backup_path,
                    "output_path": out_file,
                    "settings": settings,
                    "duration_sec": duration_sec,
                    "title": f"Recode: {title}",
                }, "RECODE", origin=ORIGIN_ADVANCED)

        self._recode_by_download[job_id] = download_key
        self._recode_state[job_id] = {
            "backup_path": backup_path,
            "keep_original": request_data.get("recode_keep_original", True),
            "request_data": dict(request_data),
            "title": title,
            "fragment_position": fragment_position,
            "fragment_total": fragment_total,
            "chain_next": chain_next,
            "stage_label": stage_label,
        }

        status_text = self._recode_status_text(fragment_position, fragment_total, label=stage_label)
        if download_key == _SOLO_RECODE_KEY:
            self.tab.output_options.set_progress(0, status_text, "downloading")
            # La cola global nace pausada (ver QueueManager.__init__) y en modo SOLO
            # nada más la despausa (a diferencia de LOTES, cuyo start_download() ya la
            # arranca antes de que un job pueda siquiera completarse y llegar hasta
            # aquí) - sin esto, un job RECODE encolado desde SOLO se quedaba esperando su
            # turno indefinidamente si el usuario nunca había tocado LOTES o
            # Herramientas Multimedia en la misma sesión (ver conversación: quedaba en
            # cuarentena ".dbak" para siempre, sin recodificar). No se llama para LOTES:
            # ahí la cola ya está corriendo por definición, y reanudarla de nuevo aquí
            # podría reactivar otros jobs que el usuario haya pausado a propósito.
            self.queue_mgr.start_queue(ORIGIN_ADVANCED)
        else:
            card = self.tab.queue_panel.cards.get(download_key)
            if card:
                # speed_text="" (no None) para limpiar la línea de detalle de inmediato -
                # si no, se queda mostrando lo último que dejó la descarga (ej.
                # "Descargado" o la velocidad final) hasta el primer tick de ffmpeg.
                card.update_progress(0, speed_text="", status_text=status_text)

    def _ia_stage_label(self, settings):
        """Texto de la fila mientras corre la etapa de IA, según la función del preajuste."""
        job_type, _key = ia_job_spec(settings)
        if job_type == "DEPTH_VIDEO":
            return self.tr("Creando mapa de profundidad...")
        if job_type == "NORMAL_VIDEO":
            return self.tr("Creando mapa de normales...")
        return self.tr("Reescalando con IA...")

    def _on_recode_job_progress(self, job_id, percent, speed, eta):
        target = self._recode_by_download.get(job_id)
        if target is None:
            return
        state = self._recode_state.get(job_id, {})
        label = state.get("stage_label")
        status_text = self._recode_status_text(state.get("fragment_position"), state.get("fragment_total"), label=label)
        if target == _SOLO_RECODE_KEY:
            self.tab.output_options.set_progress(int(percent), f"{status_text} {int(percent)}%", "downloading")
        else:
            card = self.tab.queue_panel.cards.get(target)
            if card:
                speed_text = f"{speed} | {eta}" if speed and eta else (speed or eta or "")
                card.update_progress(percent, speed_text=speed_text, status_text=status_text)

    def _continue_chain_to_recode(self, job_id, target, state):
        """Arma y encola la etapa 2 (Recodificación) de una cadena, usando la
        salida de la etapa 1 (Reescalado IA, `job_id`) como entrada. Reusa el
        MISMO backup_path/keep_original/request_data/title/fragment_* que ya
        traía `state` (la cuarentena del archivo original se hizo una sola vez,
        antes de la etapa 1 -- ver _start_post_download_recode) con
        `chain_next=None` -- así el job nuevo es indistinguible de un RECODE
        normal para _on_recode_job_status, que lo resuelve con el mismo código
        de siempre cuando termine."""
        chain_next = state["chain_next"]
        upscale_job = self.queue_mgr.get_job(job_id)
        intermediate_path = upscale_job.final_filepath if upscale_job else None
        self.queue_mgr.remove_job(job_id)

        title = state.get("title", "")
        target_is_solo = target == _SOLO_RECODE_KEY

        if not intermediate_path or not os.path.exists(intermediate_path):
            logger.error(f"AdvancedProcessTab: la etapa de Reescalado IA no dejó un archivo válido, se aborta la cadena ({title}).")
            rollback_backup(state.get("backup_path"))
            self._mark_recode_pending(target, False)
            if target_is_solo:
                self.tab.output_options.set_progress(0, self.tr("Error al reescalar (original conservado)"), "wait")
            else:
                card = self.tab.queue_panel.cards.get(target)
                if card:
                    card.update_progress(100, speed_text="", status_text=self.tr("Error al reescalar"))
            return

        settings, out_file = build_recode_output_path(
            chain_next["original_path"], "video_tools/avanzado", chain_next["recode_preset_name"],
            prefix=chain_next["recode_prefix"], suffix=chain_next["recode_suffix"],
        )
        if not settings:
            logger.warning(f"AdvancedProcessTab: Preajuste de Recodificación inválido a mitad de cadena, se omite ({title}).")
            rollback_backup(state.get("backup_path"))
            self._mark_recode_pending(target, False)
            self._cleanup_chain_intermediate_path(intermediate_path)
            return

        # El intermedio es recién creado, nunca está en caché -- ver docstring de
        # probe_fps_and_duration (core/tabs/video_tools/upscale_chain.py).
        _fps_unused, duration_sec = probe_fps_and_duration(intermediate_path)

        new_job_id = self.queue_mgr.add_job({
            "input_path": intermediate_path,
            "output_path": out_file,
            "settings": settings,
            "duration_sec": duration_sec,
            "title": f"Recode: {title}",
        }, "RECODE", origin=ORIGIN_ADVANCED)

        self._recode_by_download[new_job_id] = target
        self._recode_state[new_job_id] = {**state, "chain_next": None}
        self._chain_cleanup[new_job_id] = intermediate_path

        status_text = self._recode_status_text(state.get("fragment_position"), state.get("fragment_total"))
        if target_is_solo:
            self.tab.output_options.set_progress(0, status_text, "downloading")
        else:
            card = self.tab.queue_panel.cards.get(target)
            if card:
                card.update_progress(0, speed_text="", status_text=status_text)

    def _cleanup_chain_intermediate_path(self, intermediate_path: str):
        """Borra el archivo intermedio de una cadena y, si quedó vacía, su
        carpeta temporal propia (una por cadena, ver _start_post_download_recode)
        -- se llama pase lo que pase con la etapa 2 (éxito, error o cancelación),
        el intermedio nunca es el resultado que le importa al usuario."""
        try:
            if os.path.exists(intermediate_path):
                os.remove(intermediate_path)
            parent = os.path.dirname(intermediate_path)
            if os.path.isdir(parent) and not os.listdir(parent):
                os.rmdir(parent)
        except OSError as e:
            logger.warning(f"AdvancedProcessTab: no se pudo limpiar el intermedio de cadena '{intermediate_path}': {e}")

    def _on_recode_job_status(self, job_id, status):
        if job_id not in self._recode_by_download:
            return
        if status not in ("COMPLETED", "FAILED", "CANCELLED"):
            return  # estado intermedio (RUNNING, etc.) - nada que resolver todavía

        target = self._recode_by_download.pop(job_id)
        state = self._recode_state.pop(job_id, {})

        if state.get("chain_next") and status == "COMPLETED":
            # Etapa 1 (Reescalado IA) de una cadena terminó bien -- todavía NO es el
            # resultado final, arma la etapa 2 (Recodificación) y listo, no cae al
            # resto de esta función (backup/grupo/SOLO se resuelven recién cuando
            # ESA etapa termine). FAILED/CANCELLED de la etapa 1, en cambio, SÍ caen
            # al camino de abajo tal cual -- es un fallo genérico más, mismo criterio
            # que cualquier otro (restaurar original, liberar pending, etc.).
            self._continue_chain_to_recode(job_id, target, state)
            return

        backup_path = state.get("backup_path")
        keep_original = state.get("keep_original", True)
        request_data = state.get("request_data") or {}
        title = state.get("title", "")
        fragment_total = state.get("fragment_total")
        recode_job = self.queue_mgr.get_job(job_id)

        final_path = None
        ok = False
        if status == "COMPLETED":
            # Éxito: la casilla decide qué pasa con el original.
            if keep_original:
                rollback_backup(backup_path)  # restaura el original junto al recodificado
            else:
                commit_backup(backup_path)  # confirma (borra) el original
            final_path = recode_job.final_filepath if recode_job else None
            ok = True
            if target != _SOLO_RECODE_KEY:
                download_job = self.queue_mgr.get_job(target)
                if download_job and final_path:
                    download_job.final_filepath = final_path
            logger.info(f"AdvancedProcessTab: Recodificación post-descarga completada ({title}).")
        else:
            # Fallo o cancelación: SIEMPRE se restaura, sin importar "mantener originales"
            # (la casilla nunca causa pérdida de datos ante un error de ffmpeg).
            rollback_backup(backup_path)
            from core.utils.file_conflict_manager import BACKUP_SUFFIX
            if backup_path and backup_path.endswith(BACKUP_SUFFIX):
                final_path = backup_path[: -len(BACKUP_SUFFIX)]
            if status == "FAILED":
                err = recode_job.error_message if recode_job else "desconocido"
                logger.error(f"AdvancedProcessTab: Falló la recodificación post-descarga de '{title}': {err}")

        # El job interno ya cumplió su propósito - no debe quedar visible ni
        # reintentable en la cola compartida (no es algo que el usuario haya encolado
        # directamente, ver conversación).
        self.queue_mgr.remove_job(job_id)
        intermediate = self._chain_cleanup.pop(job_id, None)
        if intermediate:
            self._cleanup_chain_intermediate_path(intermediate)

        if fragment_total and fragment_total > 1:
            # Parte de un grupo (corte de varios fragmentos, ver
            # _resolve_fragment_download_paths) - no se resuelve el estado final hasta
            # que TODOS terminen (ver _finalize_group). Los que sigan pendientes van a
            # ir mostrando su propio "Recodificando N de M..." apenas les toque correr
            # (ver _on_recode_job_progress).
            results = self._group_results.setdefault(target, {"all_ok": True, "final_paths": []})
            results["all_ok"] = results["all_ok"] and ok
            if status == "CANCELLED":
                results["cancelled"] = True
            if final_path:
                results["final_paths"].append(final_path)
                self._register_recode_outputs(target, [final_path], succeeded=ok)
                self._send_to_editor_if_enabled(final_path, request_data)
            remaining = self._group_pending.get(target, 1) - 1
            self._group_pending[target] = remaining
            if remaining > 0:
                return
            group_paths = list(results["final_paths"])
            group_ok = results["all_ok"]
            self._finalize_group(target)
            self._start_ai_subtitles(
                target, group_paths, request_data, title=title,
                base_text=None if group_ok else (
                    QCoreApplication.translate("AdvancedProcessTab", "Error al recodificar (original conservado)")
                    if target == _SOLO_RECODE_KEY else QCoreApplication.translate("AdvancedProcessTab", "Error al recodificar")),
                base_partial=not group_ok)
            return

        # Camino normal: una sola recodificación (sin fragmentos, o un fragmento único).
        if status != "CANCELLED":
            self._notify_sound_after_recode(target, status == "COMPLETED")
        self._register_recode_outputs(target, [final_path], succeeded=(status == "COMPLETED"))
        self._mark_recode_pending(target, False)
        if target == _SOLO_RECODE_KEY:
            if final_path:
                self.last_downloaded_filepath = final_path
            if status == "COMPLETED":
                self.tab.output_options.set_progress(100, QCoreApplication.translate("AdvancedProcessTab", "Descarga completada con éxito"), "done")
            else:
                text = QCoreApplication.translate("AdvancedProcessTab", "Recodificación cancelada (original conservado)") if status == "CANCELLED" \
                    else QCoreApplication.translate("AdvancedProcessTab", "Error al recodificar (original conservado)")
                self.tab.output_options.set_progress(0, text, "wait")
            self._send_to_editor_if_enabled(final_path, request_data)
        else:
            card = self.tab.queue_panel.cards.get(target)
            if card:
                text = QCoreApplication.translate("AdvancedProcessTab", "Completado") if status == "COMPLETED" else (
                    QCoreApplication.translate("AdvancedProcessTab", "Recodificación cancelada") if status == "CANCELLED" else QCoreApplication.translate("AdvancedProcessTab", "Error al recodificar")
                )
                # Fallo o cancelación de la recodificación: la descarga sí terminó y el
                # original quedó restaurado, así que va en naranja (parcial) y con el
                # motivo del error en la línea de info.
                partial = status != "COMPLETED"
                info = ""
                if status == "FAILED" and recode_job and recode_job.error_message:
                    info = recode_job.error_message
                    card.status_lbl.setToolTip(info)
                card.update_progress(100, speed_text=info, status_text=text, partial=partial)
            
            if status == "COMPLETED" and final_path:
                self._send_to_editor_if_enabled(final_path, request_data)

        # Subtítulos del archivo que quedó (el recodificado, o el original restaurado si
        # la recodificación falló: también tiene sus subtítulos). Cancelada, no.
        if status == "COMPLETED":
            self._start_ai_subtitles(target, [final_path], request_data, title=title)
        elif status == "FAILED":
            failed_text = (QCoreApplication.translate("AdvancedProcessTab", "Error al recodificar (original conservado)")
                           if target == _SOLO_RECODE_KEY else QCoreApplication.translate("AdvancedProcessTab", "Error al recodificar"))
            self._start_ai_subtitles(target, [final_path], request_data, title=title,
                                     base_text=failed_text, base_partial=True)
        self.update_queue_main_progress()

    # ── Subtítulos > "Crear con IA"──────────────────────────────────────────
    # Cuando el archivo de una descarga ya es definitivo (descargado, y recodificado o
    # procesado con IA si se pidió), se encola un TRANSCRIBE por archivo (uno por
    # fragmento). Va aparte de la cadena de posprocesado: no toca su cuarentena ni sus
    # grupos, solo vuelve a mostrar "Creando subtítulos..." en la misma tarjeta/barra y
    # bloquea el arrastre hasta terminar. Las playlists lo hacen inline (ver
    # QueueWorker._transcribe_playlist_item).
    def _ai_subtitles_ready(self, request_datas) -> bool:
        """Antes de arrancar: motor y modelo (y detector de voz, si el preajuste lo usa)
        descargados. Si falta algo, lo ofrece y devuelve False para no empezar."""
        from PySide6.QtWidgets import QMessageBox
        from gui.widgets.ia_preset_models import offer_preset_model_download
        for data in request_datas:
            if not (data or {}).get("ai_subtitles"):
                continue
            settings = data.get("ai_subtitles_settings") or {}
            if not settings.get("transcription_model"):
                QMessageBox.information(
                    self.tab, QCoreApplication.translate("AdvancedProcessTab", "Crear subtítulos con IA"),
                    QCoreApplication.translate("AdvancedProcessTab", "Elige un modelo de Whisper en Subtítulos > Crear con IA."))
                return False
            # Motor (con la opción NVIDIA), modelo y detector de voz: un solo diálogo.
            if not offer_preset_model_download(self.tab, settings, notify_downloading=True):
                return False
        return True

    def _start_ai_subtitles(self, download_key, paths, request_data, video_data=None, title="",
                            base_text=None, base_partial=False) -> bool:
        """Encola la creación de subtítulos de `paths`. `base_text`/`base_partial` son el
        estado que debe volver a mostrar la tarjeta al terminar bien (ej. "Error al
        recodificar" si la recodificación falló pero los subtítulos salieron)."""
        if not request_data or not request_data.get("ai_subtitles"):
            return False
        settings = request_data.get("ai_subtitles_settings") or {}
        if not settings.get("transcription_model"):
            return False
        queued = False
        for path in dict.fromkeys(p for p in paths if p):
            if not os.path.isfile(path):
                continue
            job_settings = dict(settings, transcription_overwrite=request_data.get("conflict_policy") == "sobrescribir")
            job_id = self.queue_mgr.add_job({
                "input_path": path,
                "output_path": os.path.splitext(path)[0] + "." + job_settings.get("container", "srt"),
                "transcription_options": job_settings,
                "duration_sec": (video_data or {}).get("duration") or 0.0,
                "title": QCoreApplication.translate("AdvancedProcessTab", "Subtítulos: {0}").format(
                    title or os.path.basename(path)),
            }, "TRANSCRIBE", origin=ORIGIN_ADVANCED)
            self._subs_by_download[job_id] = download_key
            queued = True
        if not queued:
            return False
        if download_key not in self._subs_base:
            if base_text is None:
                base_text = (QCoreApplication.translate("AdvancedProcessTab", "Descarga completada con éxito")
                             if download_key == _SOLO_RECODE_KEY
                             else QCoreApplication.translate("AdvancedProcessTab", "Completado"))
            self._subs_base[download_key] = {"text": base_text, "partial": base_partial, "errors": []}
        self._mark_recode_pending(download_key, True)
        self._show_subs_progress(download_key, 0, "")
        if download_key == _SOLO_RECODE_KEY:
            # Misma razón que en _start_post_download_recode: en SOLO nadie más arranca la cola.
            self.queue_mgr.start_queue(ORIGIN_ADVANCED)
        return True

    def _show_subs_progress(self, download_key, percent, eta):
        text = QCoreApplication.translate("AdvancedProcessTab", "Creando subtítulos...")
        if download_key == _SOLO_RECODE_KEY:
            self.tab.output_options.set_progress(int(percent), f"{text} {int(percent)}%", "downloading")
        else:
            card = self.tab.queue_panel.cards.get(download_key)
            if card:
                card.update_progress(percent, speed_text=eta or "", status_text=text)

    def _on_subs_job_progress(self, job_id, percent, speed, eta):
        target = self._subs_by_download.get(job_id)
        if target is not None:
            self._show_subs_progress(target, percent, eta)

    def _on_subs_job_status(self, job_id, status):
        if job_id not in self._subs_by_download or status not in ("COMPLETED", "FAILED", "CANCELLED"):
            return
        target = self._subs_by_download.pop(job_id)
        base = self._subs_base.get(target, {"text": "", "partial": False, "errors": []})
        job = self.queue_mgr.get_job(job_id)
        if status == "COMPLETED" and job and job.final_filepath:
            self._register_recode_outputs(target, [job.final_filepath], succeeded=True)
            logger.info(f"AdvancedProcessTab: Subtítulos creados: {job.final_filepath}")
        elif status == "FAILED":
            error = (job.error_message if job else "") or ""
            base["errors"].append(error)
            logger.error(f"AdvancedProcessTab: No se pudieron crear los subtítulos: {error}")
        elif status == "CANCELLED":
            base["errors"].append(QCoreApplication.translate("AdvancedProcessTab", "Cancelado"))
        # Interno, igual que los RECODE: no queda visible ni reintentable en la cola.
        self.queue_mgr.remove_job(job_id)
        if target in self._subs_by_download.values():
            return  # quedan otros fragmentos de esta misma descarga
        self._subs_base.pop(target, None)
        self._mark_recode_pending(target, False)
        failed = bool(base["errors"])
        if target == _SOLO_RECODE_KEY:
            if failed:
                text = QCoreApplication.translate("AdvancedProcessTab", "Error al crear subtítulos: {0}").format(base["errors"][-1])
                self.tab.output_options.set_progress(0, text, "wait")
            else:
                self.tab.output_options.set_progress(100, base["text"], "done")
        else:
            card = self.tab.queue_panel.cards.get(target)
            if card:
                if failed:
                    card.status_lbl.setToolTip(base["errors"][-1])
                    card.update_progress(100, speed_text=base["errors"][-1],
                                         status_text=QCoreApplication.translate("AdvancedProcessTab", "Error al crear subtítulos"),
                                         partial=True)
                else:
                    card.update_progress(100, speed_text="", status_text=base["text"], partial=base["partial"])
        self.update_queue_main_progress()

    def on_open_output_path_clicked(self):
        path = self.tab.output_options.output_path_input.text().strip()
        if not path:
            return

        if self.tab.url_bar.solo_btn.isChecked():
            if self.last_downloaded_filepath:
                actual_path = self._find_actual_downloaded_file(self.last_downloaded_filepath)
                if actual_path:
                    self._open_and_select(actual_path)
                    return
        else:
            if self.tab._selected_job_id:
                job = self.queue_mgr.get_job(self.tab._selected_job_id)
                if job and job.status == "COMPLETED" and job.final_filepath:
                    actual_path = self._find_actual_downloaded_file(job.final_filepath)
                    if actual_path:
                        self._open_and_select(actual_path)
                        return

        # Fallback estándar
        if os.path.exists(path):
            path = os.path.abspath(path)
            if os.name == 'nt':
                os.startfile(path)
            else:
                from PySide6.QtGui import QDesktopServices
                from PySide6.QtCore import QUrl
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _resolve_final_download_path(self, request_data, fallback_filepath):
        """
        job.final_filepath / last_downloaded_filepath (puestos por el hook de progreso de
        yt-dlp, ver _execute_download) apuntan, en descargas video+audio que requieren
        fusión (ej. HLS), al archivo INTERMEDIO de un solo stream (ej. ".fhls-628.mp4")
        que yt-dlp borra apenas termina de fusionar — nunca al .mp4 final ya fusionado.
        Se reconstruye la ruta final esperada con el mismo cálculo que ya usa
        DownloaderMaster para nombrarlo (predict_final_extension, ver
        downloader_master.py::_resolve_output_conflict), y solo se cae al hint crudo de
        yt-dlp si esa reconstrucción no encuentra nada (ej. hubo un rename por conflicto
        que request_data no ve, porque DownloaderMaster lo aplica sobre una copia)."""
        request_data = request_data or {}
        title = request_data.get("title")
        output_path = request_data.get("output_path")
        if title and output_path:
            predicted_ext = predict_final_extension(
                request_data.get("video_ext"),
                request_data.get("audio_ext"),
                request_data.get("mode", "video+audio"),
                bool(request_data.get("video_is_combined")),
            )
            predicted_path = os.path.join(output_path, f"{title}{predicted_ext}")
            actual = self._find_actual_downloaded_file(predicted_path)
            if actual and os.path.isfile(actual):
                return actual
        return self._find_actual_downloaded_file(fallback_filepath)

    def _resolve_fragment_download_paths(self, request_data):
        """
        Con corte de fragmentos, cada uno termina en su propio archivo
        "..._{sufijo}{ext}" (ver downloader_master.py: individual_download y
        _handle_local_cuts nombran así cada fragmento) - a diferencia de una descarga
        normal, aquí NO alcanza con una sola ruta reconstruida (_resolve_final_download_path
        solo arma "{título}{ext}", que no matchea ningún fragmento). Se busca cada
        fragmento por PATRÓN de nombre en vez de reconstruir "{título}_{sufijo}{ext}" a
        mano: en modo LOTES, request_data["title"] puede no estar sanitizado (
        QueueWorker._execute_download le pasa una COPIA a DownloaderMaster.download(),
        ver queue_manager.py - la sanitización que hace ahí NUNCA vuelve a
        job.request_data), así que reconstruir con ese título roto ante cualquier
        carácter que la sanitización cambie (emojis, "://", etc. - ver conversación,
        reproducido con un título con emoji y URL) hacía fallar la búsqueda para todos
        los fragmentos menos el que coincidía por casualidad vía job.final_filepath.

        Devuelve una lista de (ruta_real, sufijo) - vacía si no hay fragmentos o no se
        encontró ninguno en disco (deja al llamador caer a _resolve_final_download_path
        como antes).
        """
        fragments = request_data.get("selected_fragments") or []
        output_path = request_data.get("output_path")
        if not fragments or not output_path:
            return []

        predicted_ext = predict_final_extension(
            request_data.get("video_ext"),
            request_data.get("audio_ext"),
            request_data.get("mode", "video+audio"),
            bool(request_data.get("video_is_combined")),
        )

        import glob
        skip_exts = (".jpg", ".jpeg", ".png", ".webp", ".dbak", ".part", ".ytdl", ".temp")
        title = request_data.get("title")
        results = []
        for i, frag in enumerate(fragments):
            suffix = frag[2] if len(frag) > 2 else f"fragment{i+1:02d}"
            candidates = []
            if title:
                for t in (title, sanitize_filename(title)):
                    exact = os.path.join(output_path, f"{t}_{suffix}{predicted_ext}")
                    if os.path.isfile(exact):
                        candidates = [exact]
                        break
                    pat_title = os.path.join(glob.escape(output_path), f"{glob.escape(t)}_{suffix}.*")
                    matches = [
                        p for p in glob.glob(pat_title)
                        if os.path.isfile(p) and not p.lower().endswith(skip_exts)
                    ]
                    if matches:
                        matches.sort(key=lambda p: os.path.getmtime(p), reverse=True)
                        candidates = matches
                        break

            if not candidates:
                pattern = os.path.join(glob.escape(output_path), f"*_{suffix}{predicted_ext}")
                candidates = [p for p in glob.glob(pattern) if os.path.isfile(p)]
                if not candidates:
                    # Contenedor final distinto al previsto (ej. remux) - se amplía la
                    # búsqueda a cualquier extensión con ese sufijo, evitando igual
                    # miniaturas/backups/temporales que puedan compartir el mismo sufijo.
                    pattern_any = os.path.join(glob.escape(output_path), f"*_{suffix}.*")
                    candidates = [
                        p for p in glob.glob(pattern_any)
                        if os.path.isfile(p) and not p.lower().endswith(skip_exts)
                    ]
                if candidates:
                    candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)

            if candidates:
                results.append((candidates[0], suffix))
        return results

    def _find_actual_downloaded_file(self, filepath):
        """Se cae a la carpeta contenedora cuando no encuentra nada, porque además de
        resolver la ruta para recodificar/enviar se usa para abrir el explorador (ver
        on_open_output_path_clicked)."""
        if filepath and os.path.isdir(filepath):
            return filepath
        return find_actual_downloaded_file(filepath, fallback_to_dir=True)

    def _open_and_select(self, path):
        path = os.path.abspath(path)
        if not os.path.exists(path):
            return
            
        try:
            if os.name == 'nt':
                if os.path.isdir(path):
                    os.startfile(path)
                else:
                    subprocess.run(['explorer', '/select,', path])
            elif platform.system() == 'Darwin':
                if os.path.isdir(path):
                    subprocess.run(['open', path])
                else:
                    subprocess.run(['open', '-R', path])
            else:
                if os.path.isdir(path):
                    subprocess.run(['xdg-open', path])
                else:
                    subprocess.run(['xdg-open', os.path.dirname(path)])
        except Exception as e:
            logger.error(f"Error abriendo explorador en la ruta {path}: {e}")
