# src/gui/tabs/quick_mode/download_controller.py
import os
import tempfile
import requests
import threading
from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtWidgets import QDialog

from core.logger.logger_manager import logger
from core.utils.cleanup_manager import CleanupManager
from core.utils.config_manager import get_config
from core.utils.queue_manager import get_queue_manager
from core.utils.output_artifacts import find_actual_downloaded_file
from core.utils.preset_manager import build_recode_output_path, get_preset_manager, IA_TOOLS_NAMESPACE
from core.utils.file_conflict_manager import quarantine_for_recode, rollback_backup
from core.tabs.video_tools.upscale_chain import start_upscale_stage, probe_fps_and_duration
from core.tabs.quick_mode.quick_mode_logic import build_quick_request_data, reveal_in_file_manager
from gui.tabs.advanced_process.workers import AnalysisWorker, DownloadWorker
from gui.dialogs.playlist_selection_dialog import PlaylistSelectionDialog


class QuickDownloadController(QObject):
    """Controlador de descargas y análisis para la pestaña QuickMode."""
    
    # Señales para notificar cambios a la vista
    busy_state_changed = Signal(bool, str)       # (busy, message)
    download_text_changed = Signal(str)         # (text)
    download_finished_signal = Signal(bool, str) # (success, message)
    progress_updated = Signal(int, str, str)    # (value, message, status_type)

    def __init__(self, parent_tab):
        super().__init__(parent_tab)
        self.tab = parent_tab
        self.download_worker = None
        self.analysis_worker = None
        self.cancellation_event = threading.Event()
        self.is_downloading = False
        self.last_request_data = None
        self.last_downloaded_filepath = None
        
        # Atributos de seguimiento para las descargas
        self.active_workers = []
        self.pending_tasks = []
        self.current_item_rows = []
        self.current_item_keys = []
        self.current_item_pos = 0
        self.completed_items = 0

        # Contadores de la tanda actual, para la barra general ("X de Y
        # completados"). Se reinician cuando arranca una tanda nueva desde
        # estado idle (ver start_worker).
        self._batch_total = 0
        self._batch_completed = 0

        # Recodificación post-descarga (misma tarjeta "Recodificar" de Proceso
        # Avanzado, ver quick_mode_view.py::recode_options y AdvancedProcessTab
        # DownloadController._start_post_download_recode, del que este bloque es
        # contraparte para Modo Rápido, con el mismo enfoque: un corte con varios
        # fragmentos sigue mostrándose como UNA sola fila (ver
        # open_cut_dialog_and_download/_on_task_progress), pero internamente se
        # encola un job RECODE por fragmento - _row_recode_pending/_row_recode_results
        # llevan la cuenta de cuántos faltan por fila para no marcarla
        # Completado/Error hasta que el último termine (ver _on_recode_job_status).
        self.queue_mgr = get_queue_manager()
        self.queue_mgr.job_progress_changed.connect(self._on_recode_job_progress)
        self.queue_mgr.job_status_changed.connect(self._on_recode_job_status)
        self._recode_by_download = {}
        self._recode_state = {}
        self._row_recode_pending = {}
        self._row_recode_results = {}
        # Reescalado IA + Recodificación combinados (ver _start_post_download_recode/
        # _on_recode_job_status): job_id del job RECODE de la etapa 2 -> ruta del
        # archivo intermedio (y su carpeta temporal propia) a borrar cuando esa etapa
        # termine, pase lo que pase -- el intermedio nunca es el resultado final.
        self._chain_cleanup = {}

    def start_download_flow(self, url, mode, quality, output_path, speed_limit_val,
                            chk_thumb_file_checked, chk_thumb_only_checked,
                            btn_cut_checked, chk_playlist_selector_checked, recode_data=None):
        """Inicia el flujo de descargas dependiendo de la configuración actual."""
        if not url:
            self.progress_updated.emit(0, self.tr("Pega una URL primero") if hasattr(self, "tr") else "Pega una URL primero", "error")
            return

        if btn_cut_checked:
            self.start_cut_analysis(url, mode, quality, output_path, speed_limit_val,
                                    chk_thumb_file_checked, chk_thumb_only_checked, recode_data)
        elif chk_playlist_selector_checked:
            self.start_playlist_selection(url, mode, quality, output_path, speed_limit_val,
                                         chk_thumb_file_checked, chk_thumb_only_checked, recode_data)
        else:
            self.start_direct_download(url, mode, quality, output_path, speed_limit_val,
                                       chk_thumb_file_checked, chk_thumb_only_checked, recode_data)

    def start_direct_download(self, url, mode, quality, output_path, speed_limit_val,
                              chk_thumb_file_checked, chk_thumb_only_checked, recode_data=None):
        """Descarga directa sin análisis previo."""
        req = build_quick_request_data(
            url=url,
            title="",
            mode=mode,
            quality=quality,
            output_path=output_path,
            speed_limit_val=speed_limit_val,
            chk_thumb_file_checked=chk_thumb_file_checked,
            chk_thumb_only_checked=chk_thumb_only_checked,
            is_playlist=False,
            conflict_policy=self.tab.output_options.conflict_policy_combo.currentData(),
        )
        if recode_data:
            req.update(recode_data)
        self.start_worker(req, selected_entries=[{"title": self.tr("Descarga directa") if hasattr(self, "tr") else "Descarga directa"}], selected_indices=[0])

    def start_playlist_selection(self, url, mode, quality, output_path, speed_limit_val,
                                 chk_thumb_file_checked, chk_thumb_only_checked, recode_data=None):
        """Inicia el análisis de la lista de reproducción para posterior selección."""
        self.busy_state_changed.emit(True, self.tr("Analizando playlist...") if hasattr(self, "tr") else "Analizando playlist...")
        self.analysis_worker = AnalysisWorker(url, analyze_playlist=True, fast_mode=True)

        def on_finished(data, error):
            if self.analysis_worker:
                self.analysis_worker.deleteLater()
            self.analysis_worker = None
            
            if error:
                self.busy_state_changed.emit(False, "")
                self.progress_updated.emit(0, self.tr("Error: {0}").format(error) if hasattr(self, "tr") else f"Error: {error}", "error")
                return

            entries = data.get("entries") or []
            if len(entries) <= 1:
                self.busy_state_changed.emit(False, "")
                self.start_direct_download(url, mode, quality, output_path, speed_limit_val,
                                           chk_thumb_file_checked, chk_thumb_only_checked, recode_data)
                return

            dialog = PlaylistSelectionDialog(data, self.tab)
            if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.result_data:
                self.busy_state_changed.emit(False, "")
                self.progress_updated.emit(0, self.tr("Selección cancelada") if hasattr(self, "tr") else "Selección cancelada", "wait")
                return

            selected = dialog.result_data.get("selected_indices", [])
            if not selected:
                self.busy_state_changed.emit(False, "")
                self.progress_updated.emit(0, self.tr("No se seleccionaron medios") if hasattr(self, "tr") else "No se seleccionaron medios", "error")
                return

            req = build_quick_request_data(
                url=data.get("original_url", data.get("webpage_url", url)),
                title=data.get("title") or (self.tr("Playlist") if hasattr(self, "tr") else "Playlist"),
                mode=mode,
                quality=quality,
                output_path=output_path,
                speed_limit_val=speed_limit_val,
                chk_thumb_file_checked=chk_thumb_file_checked,
                chk_thumb_only_checked=chk_thumb_only_checked,
                is_playlist=True,
                playlist_items=",".join(str(i + 1) for i in selected),
                conflict_policy=self.tab.output_options.conflict_policy_combo.currentData(),
            )
            
            req["mode"] = dialog.result_data.get("playlist_mode") or req["mode"]
            item_quality = dialog.result_data.get("playlist_quality") or quality
            from core.ytdlp_logic.format_selectors import quick_format_selector
            req["format_selector"] = quick_format_selector(req["mode"], item_quality, url=req.get("url", ""))
            if recode_data:
                req.update(recode_data)

            selected_entries = [entries[i] for i in selected if 0 <= i < len(entries)]
            # Una descarga por ítem en vez de una sola con playlist_items: así el 403 de
            # cada vídeo se reintenta al momento y no al terminar la pasada entera.
            self.start_playlist_workers(req, selected_entries, selected, req["mode"], item_quality)

        self.analysis_worker.finished.connect(on_finished)
        self.analysis_worker.start()

    def start_cut_analysis(self, url, mode, quality, output_path, speed_limit_val,
                           chk_thumb_file_checked, chk_thumb_only_checked, recode_data=None):
        """Inicia el análisis para corte de fragmento."""
        self.busy_state_changed.emit(True, self.tr("Analizando video para recorte...") if hasattr(self, "tr") else "Analizando video para recorte...")
        self.analysis_worker = AnalysisWorker(url, analyze_playlist=False, fast_mode=True)

        def on_finished(data, error):
            if self.analysis_worker:
                self.analysis_worker.deleteLater()
            self.analysis_worker = None
            
            if error:
                self.busy_state_changed.emit(False, "")
                self.progress_updated.emit(0, self.tr("Error al analizar: {0}").format(error) if hasattr(self, "tr") else f"Error al analizar: {error}", "error")
                return
                
            self.open_cut_dialog_and_download(url, data, mode, quality, output_path, speed_limit_val,
                                              chk_thumb_file_checked, chk_thumb_only_checked, recode_data)

        self.analysis_worker.finished.connect(on_finished)
        self.analysis_worker.start()

    def open_cut_dialog_and_download(self, url, data, mode, quality, output_path, speed_limit_val,
                                     chk_thumb_file_checked, chk_thumb_only_checked, recode_data=None):
        """Abre el diálogo de fragmento de corte."""
        thumb_url = None
        thumbs = data.get("thumbnails") or []
        valid_thumbs = [t for t in thumbs if t.get("url")]
        if valid_thumbs:
            valid_thumbs.sort(key=lambda t: (t.get("width") or 0) * (t.get("height") or 0), reverse=True)
            thumb_url = valid_thumbs[0]["url"]
        else:
            thumb_url = data.get("thumbnail")

        pixmap = None
        if thumb_url:
            try:
                from PySide6.QtGui import QImage, QPixmap
                resp = requests.get(thumb_url, timeout=3)
                resp.raise_for_status()
                img = QImage.fromData(resp.content)
                if not img.isNull():
                    pixmap = QPixmap.fromImage(img)
            except Exception as e:
                logger.warning(f"QuickDownloadController: No se pudo descargar miniatura para FragmentDialog: {e}")

        formats = data.get("formats") or []
        preview_format = None
        for f in formats:
            if f.get("url") and not f.get("url", "").startswith("rtmp") and f.get("acodec") != "none" and f.get("vcodec") != "none":
                h = f.get("height") or 0
                if 360 <= h <= 720:
                    preview_format = f
                    break
        if not preview_format:
            for f in formats:
                if f.get("url") and f.get("vcodec") != "none":
                    preview_format = f
                    break
        stream_url = preview_format.get("url", "") if preview_format else ""

        from gui.dialogs.fragment_dialog import FragmentDialog
        
        dialog = FragmentDialog(
            self.tab,
            stream_url=stream_url,
            thumbnail_pixmap=pixmap,
            duration=data.get("duration", 0),
            fps=data.get("fps", 30) or 30,
            source_url=data.get("webpage_url", url),
        )

        result = dialog.exec()
        main_win = self.tab.window()
        if main_win:
            main_win.activateWindow()
            main_win.raise_()

        if result:
            frag_data = dialog.get_fragments_data()
            selected_fragments = frag_data["fragments"]
            fragment_mode = frag_data["mode"]
            
            req = build_quick_request_data(
                url=url,
                title=data.get("title", ""),
                mode=mode,
                quality=quality,
                output_path=output_path,
                speed_limit_val=speed_limit_val,
                chk_thumb_file_checked=chk_thumb_file_checked,
                chk_thumb_only_checked=chk_thumb_only_checked,
                is_playlist=False,
                conflict_policy=self.tab.output_options.conflict_policy_combo.currentData(),
            )
            req["selected_fragments"] = selected_fragments
            req["fragment_mode"] = fragment_mode
            if recode_data:
                req.update(recode_data)

            self.busy_state_changed.emit(False, "")
            self.download_text_changed.emit(self.tr("Descargar") if hasattr(self, "tr") else "Descargar")

            # Una sola fila para todo el corte, tenga uno o varios fragmentos (mismo
            # criterio que Proceso Avanzado, que muestra un corte de varios fragmentos
            # como un único item - ver conversación) - _on_task_progress arma la lista
            # de archivos por fragmento aparte (task_data['_fragment_files']), y
            # _on_task_finished encola una recodificación por archivo, todas
            # reportando su "Recodificando N de M" a ESTA fila (ver
            # _queue_fragment_recodes).
            self.start_worker(req, selected_entries=[data], selected_indices=[0])
        else:
            self.busy_state_changed.emit(False, "")
            self.progress_updated.emit(0, self.tr("Recorte cancelado") if hasattr(self, "tr") else "Recorte cancelado", "wait")

    def _reset_batch_if_idle(self):
        """Si no hay nada activo ni encolado, esta es una tanda nueva: reiniciar los
        contadores de la barra general ('X de Y completados')."""
        if not self.active_workers and not self.pending_tasks:
            self._batch_total = 0
            self._batch_completed = 0

    def _enqueue_task(self, request_data, item_rows, item_keys):
        """Crea el trabajo de descarga para unas filas ya existentes y lo arranca (o lo
        deja en cola si se llegó al máximo de descargas simultáneas).

        Va aparte de start_worker porque una playlist crea TODAS sus filas de una vez
        (una tarjeta de grupo) pero lanza una descarga por ítem, ver
        start_playlist_workers."""
        from core.utils.config_manager import get_config
        max_concurrent = get_config().get("max_concurrent_downloads", 3)

        canc_event = threading.Event()
        task_data = {
            "request_data": request_data.copy(),
            "item_rows": item_rows,
            "item_keys": item_keys,
            "cancellation_event": canc_event,
        }

        if len(self.active_workers) < max_concurrent:
            self._start_task_worker(task_data)
        else:
            for row in item_rows:
                row.update_progress(0, status=self.tr("En cola") if hasattr(self, "tr") else "En cola")
            self.pending_tasks.append(task_data)
            self.is_downloading = True
            self._emit_batch_progress()
        return task_data

    def start_playlist_workers(self, base_request, entries, selected_indices, mode, quality):
        """Descarga una playlist con UNA descarga por ítem, no con una sola llamada.

        Es el mismo patrón que ya usa Proceso Avanzado (_execute_playlist en
        queue_manager.py): cada ítem es una descarga suelta, así que un 403 de YouTube
        llega como excepción y se reintenta con el cliente alternativo EN ESE MOMENTO
        (ver downloader_master.download).

        Con la forma anterior -- una única llamada con 'playlist_items' -- yt-dlp llevaba
        ignoreerrors='only_download' y se tragaba los 403 sin excepción, así que la
        recuperación no podía dispararse hasta que terminaba la pasada COMPLETA: con
        1000 ítems, 1000 fallos antes del primer reintento, y la sensación de que la
        descarga no arrancaba nunca.
        """
        from core.utils.queue_manager import QueueWorker
        from core.ytdlp_logic.format_selectors import quick_format_selector

        self._reset_batch_if_idle()
        self.last_request_data = base_request.copy()
        self.last_downloaded_filepath = None

        # Las filas se crean de una sola vez para que la tarjeta de grupo agrupe la
        # playlist entera, aunque después cada una tenga su propia descarga.
        item_rows, item_keys = self.tab.activity_panel.add_activity_rows(
            entries, selected_indices, group_title=base_request.get("playlist_title")
        )
        self.current_item_rows.extend(item_rows)
        self.current_item_keys.extend(item_keys)

        for pos, (row, key, entry) in enumerate(zip(item_rows, item_keys, entries), start=1):
            item_url = QueueWorker._entry_url(entry or {})
            if not item_url:
                logger.warning(f"QuickModeTab: Ítem de playlist sin URL utilizable: {row.original_title}")
                row.update_progress(0, status=self.tr("Error") if hasattr(self, "tr") else "Error")
                row.mark_error()
                continue

            child = base_request.copy()
            # SIN ESTO NO SIRVE DE NADA: 'playlist_items' es justo lo que hace que
            # _prepare_opts active ignoreerrors y vuelva a tragarse los 403.
            child.pop("playlist_items", None)
            child["url"] = item_url
            # " #N" reproduce lo que ponía la plantilla %(playlist_autonumber)s, que solo
            # funciona dentro del bucle de playlist de yt-dlp: sin esto los archivos
            # perderían la numeración.
            titulo = (entry or {}).get("title") or row.original_title or f"Item {pos}"
            child["title"] = f"{titulo} #{pos}"
            child["format_selector"] = quick_format_selector(mode, quality, url=item_url)

            self._batch_total += 1
            self._enqueue_task(child, [row], [key])

        if not self.active_workers and not self.pending_tasks:
            self.busy_state_changed.emit(False, "")

    def start_worker(self, request_data, selected_entries=None, selected_indices=None):
        """Inicia un DownloadWorker respectando la concurrencia global."""
        self._reset_batch_if_idle()
        self._batch_total += 1

        self.last_request_data = request_data.copy()
        self.last_downloaded_filepath = None

        # El nombre de la lista viaja en "playlist_title", NO en "title": para una
        # playlist build_quick_request_data vacía "title" a propósito (el nombre de cada
        # archivo lo pone yt-dlp por ítem). Leerlo de "title" dejaba la tarjeta llamándose
        # siempre "Playlist".
        group_title = request_data.get("playlist_title") if request_data.get("is_playlist") else None
        item_rows, item_keys = self.tab.activity_panel.add_activity_rows(
            selected_entries or [], selected_indices or [], group_title=group_title
        )
        self.current_item_rows.extend(item_rows)
        self.current_item_keys.extend(item_keys)

        self._enqueue_task(request_data, item_rows, item_keys)

    def _emit_batch_progress(self):
        """
        Actualiza la barra general (la de 'Opciones de salida') para que solo
        muestre cuántos ítems de la tanda actual ya terminaron — nunca el
        progreso en vivo de un ítem individual (eso lo maneja cada fila).
        """
        total = self._batch_total
        completed = self._batch_completed
        if total <= 0:
            return
        percent = int(completed / total * 100)
        msg = (
            self.tr("{0} de {1} completados").format(completed, total)
            if hasattr(self, "tr") else f"{completed} de {total} completados"
        )
        self.progress_updated.emit(percent, msg, "downloading")
        if self.tab.taskbar_manager:
            self.tab.taskbar_manager.set_state("normal")
            self.tab.taskbar_manager.set_value(percent)

    def _start_task_worker(self, task_data):
        worker = DownloadWorker(task_data["request_data"], task_data["cancellation_event"])
        task_data["worker"] = worker
        self.download_worker = worker

        worker.progress.connect(lambda d, task=task_data: self._on_task_progress(d, task))
        worker.finished.connect(lambda success, msg, task=task_data: self._on_task_finished(success, msg, task))

        self.active_workers.append(task_data)
        self.is_downloading = True
        self.download_text_changed.emit(self.tr("Descargar") if hasattr(self, "tr") else "Descargar")
        self._emit_batch_progress()
        worker.start()

    def cancel_download(self):
        """Cancela todas las descargas activas y limpia las pendientes."""
        self.pending_tasks.clear()
        for task in list(self.active_workers):
            task["cancellation_event"].set()
        self.active_workers.clear()
        
        # Cancelar todas las recodificaciones en curso
        for job_id in list(self._recode_by_download.keys()):
            self.queue_mgr.cancel_job(job_id)
            
        self.is_downloading = False
        self.download_text_changed.emit(self.tr("Descargar") if hasattr(self, "tr") else "Descargar")
        self.progress_updated.emit(0, self.tr("Descargas canceladas") if hasattr(self, "tr") else "Descargas canceladas", "wait")
        if self.tab.taskbar_manager:
            self.tab.taskbar_manager.stop()

    def cancel_row(self, row):
        """Cancela las descargas y recodificaciones asociadas a una fila específica."""
        # Cancelar descargas
        for task in list(self.active_workers):
            if row in task.get("item_rows", []):
                task["cancellation_event"].set()
                
        # Cancelar recodificaciones
        for job_id, recode_row in list(self._recode_by_download.items()):
            if recode_row == row:
                self.queue_mgr.cancel_job(job_id)

    def _find_actual_downloaded_file(self, filepath):
        return find_actual_downloaded_file(filepath)

    def _on_task_progress(self, data, task_data):
        has_fragments = bool(task_data["request_data"].get("selected_fragments"))

        if data.get("status") == "fragment_progress":
            idx = data.get("fragment_index")
            total = data.get("fragment_count")
            phase = data.get("phase", "downloading")
            # Recuerda qué fragmento está en curso - el próximo "finished" (hasta que
            # llegue el siguiente fragment_progress) pertenece a ESTE fragmento, así se
            # sabe en qué posición de task_data['_fragment_files'] guardarlo (ver más
            # abajo). Necesario porque un corte con más de un fragmento sigue siendo
            # UNA sola fila (igual que Proceso Avanzado, ver conversación), así que no
            # alcanza con pisar row.downloaded_filepath en cada "finished" - se perdía
            # el archivo de todos los fragmentos menos el último.
            task_data["_frag_idx"] = idx
            for row in task_data["item_rows"]:
                row.set_fragment_progress(idx, total, phase)
            if self.tab.taskbar_manager:
                self.tab.taskbar_manager.set_state("indeterminate")
            return

        if data.get("status") == "downloading":
            # Mientras el ítem tenga fragmentos, el % numérico crudo de yt-dlp no
            # representa el avance real (se dispara una vez por fragmento) - la barra
            # de la fila queda a cargo de fragment_progress en ese caso. Esto NO debe
            # aplicarse también a "finished" (ver más abajo): antes se descartaba con
            # el mismo guard, y como consecuencia row.downloaded_filepath/
            # last_downloaded_filepath nunca se llenaban para un corte de fragmento -
            # "Recodificar" no tenía ningún archivo real que recodificar y no hacía
            # nada después de descargar (ver conversación).
            if has_fragments:
                return
            from core.ytdlp_logic.analyzer import strip_ansi_codes
            p_str = strip_ansi_codes(data.get("_percent_str", "0%")).replace("%", "").strip()
            try:
                val = float(p_str)
            except Exception:
                val = 0
            speed = strip_ansi_codes(data.get("_speed_str", "")).strip() or "..."
            eta = strip_ansi_codes(data.get("_eta_str", "")).strip() or "..."

            for row in self._resolve_target_rows(data, task_data):
                row.update_progress(
                    val,
                    info=f"{speed} - ETA: {eta}",
                    status=self.tr("Descargando") if hasattr(self, "tr") else "Descargando",
                )
                info = data.get("info_dict")
                if info:
                    row.update_metadata_from_dict(info)

        elif data.get("status") == "finished":
            # A diferencia de "downloading", este evento SÍ hay que procesarlo aunque
            # haya fragmentos - es la única fuente del nombre real del archivo de
            # salida (yt-dlp lo reporta igual con el corte, un evento por fragmento).
            filepath = data.get("filename")
            if filepath:
                self.last_downloaded_filepath = filepath
                # Rastro PROPIO de esta tarea. self.last_downloaded_filepath es global y
                # con varias descargas a la vez (una playlist ahora son N tareas) la
                # última en escribir puede ser la de otra fila.
                task_data["_last_path"] = filepath
            if has_fragments:
                # Se acumula cada archivo en task_data['_fragment_files'], indexado
                # por fragment_index (last-write-wins por índice: un mismo fragmento
                # puede disparar más de un "finished" intermedio - stream de video,
                # de audio, fusión final - antes del archivo definitivo).
                # _on_task_finished arma la lista ordenada y encola una recodificación
                # por archivo (ver _queue_fragment_recodes).
                frag_idx = task_data.get("_frag_idx")
                if frag_idx is not None and filepath:
                    task_data.setdefault("_fragment_files", {})[frag_idx] = filepath
                if filepath:
                    for row in task_data["item_rows"]:
                        row.add_output_files([filepath])
                info = data.get("info_dict")
                if info:
                    for row in task_data["item_rows"]:
                        row.update_metadata_from_dict(info)
                return
            for row in self._resolve_target_rows(data, task_data):
                row.update_progress(100, status=self.tr("Procesando") if hasattr(self, "tr") else "Procesando")
                if filepath:
                    row.downloaded_filepath = filepath
                    # Se registran TODOS los 'finished' de la fila, incluidos los
                    # intermedios pre-fusión (pista de video sola, de audio sola): los
                    # que yt-dlp borre al fusionar se caen solos al filtrar por
                    # existencia en el momento del arrastre (ver output_artifacts.py).
                    row.add_output_files([filepath])
                info = data.get("info_dict")
                if info:
                    row.update_metadata_from_dict(info)

    def _resolve_target_rows(self, data, task_data):
        """
        Devuelve las filas de item_rows a las que corresponde este evento de progreso.
        Solo hace falta desambiguar con una playlist (más de una fila comparte la misma
        tarea/worker, ver start_playlist_selection): yt-dlp reporta el 'playlist_index'
        de CADA entrada en su propio info_dict, que se compara contra item_keys (ver
        ActivityPanel.add_activity_rows) para enrutar el evento a la fila correcta, en
        vez de aplicarlo ciegamente a todas, que pisaba el archivo/estado de cada fila
        con los de la última entrada vista (y por eso antes no se podía recodificar cada
        ítem de playlist por separado - ver conversación). Un corte de fragmentos (uno o
        varios) siempre es una sola fila (ver open_cut_dialog_and_download), así que cae
        solo en el caso trivial de abajo.
        """
        rows = task_data["item_rows"]
        if len(rows) <= 1:
            return rows
        info = data.get("info_dict") or {}
        key = info.get("playlist_index")
        if key is None:
            key = info.get("playlist_autonumber")
        if key is None:
            return rows
        keys = task_data.get("item_keys") or []
        for row, row_key in zip(rows, keys):
            if row_key == key:
                return [row]
        return rows

    def _on_task_finished(self, success, message, task_data):
        self._batch_completed += 1

        if task_data in self.active_workers:
            self.active_workers.remove(task_data)

        if task_data.get("worker"):
            task_data["worker"].deleteLater()

        from core.services.editor_integration_manager import EditorIntegrationManager
        editor_mgr = EditorIntegrationManager.get_instance()

        request_data = task_data["request_data"]
        recode_requested = bool(request_data.get("recode_enabled")) or bool(request_data.get("upscale_enabled"))
        is_single_row = len(task_data["item_rows"]) == 1
        fragment_files = task_data.get("_fragment_files")  # {frag_idx: path} o None

        for row in task_data["item_rows"]:
            if success:
                if fragment_files:
                    # Corte con fragmentos: una sola fila representa TODOS (ver
                    # open_cut_dialog_and_download), así que aquí no hay un único
                    # actual_path - hay uno por fragmento, acumulado en
                    # task_data['_fragment_files'] por _on_task_progress.
                    ordered = [
                        (fragment_files[k], self._fragment_suffix(request_data, k))
                        for k in sorted(fragment_files.keys())
                    ]
                    base_title = row.original_title or request_data.get("title") or ""
                    row.add_output_files([p for p, _ in ordered])
                    if recode_requested and self._queue_fragment_recodes(row, ordered, request_data, base_title):
                        # El estado "Completado"/envío al editor lo resuelve
                        # _on_recode_job_status una vez terminen TODAS las
                        # recodificaciones del grupo.
                        continue

                    last_path = ordered[-1][0] if ordered else None
                    row.update_progress(100, status=self.tr("Completado") if hasattr(self, "tr") else "Completado")
                    row.mark_completed(filepath=last_path)
                    if editor_mgr and editor_mgr.is_auto_send_enabled:
                        for p, _ in ordered:
                            editor_mgr.process_raw_download(p, request_data)
                    continue

                actual_path = None
                if hasattr(row, 'downloaded_filepath') and row.downloaded_filepath:
                    actual_path = self._find_actual_downloaded_file(row.downloaded_filepath)
                # self.last_downloaded_filepath es un rastro GLOBAL (última descarga de
                # cualquier tarea/fila) - solo sirve de respaldo cuando la tarea tiene una
                # sola fila. Con una playlist (varias filas por tarea, ver
                # _resolve_target_rows) usarlo aquí terminaría recodificando o marcando
                # "Completado" con el archivo de OTRA fila si esta nunca recibió su
                # propio evento "finished" (p. ej. un ítem fallido con
                # ignoreerrors='only_download', ver downloader_master.py).
                # Se prefiere SIEMPRE el rastro de esta tarea; el global solo queda como
                # último recurso para una descarga suelta, que es cuando no hay otra
                # tarea que pueda haberlo pisado.
                respaldo = task_data.get("_last_path") or (
                    self.last_downloaded_filepath if len(self.active_workers) <= 1 else None
                )
                if not actual_path and is_single_row and respaldo:
                    actual_path = self._find_actual_downloaded_file(respaldo)

                if not actual_path and not is_single_row:
                    # Ítem de playlist que nunca recibió su propio evento "finished" (p.
                    # ej. falló individualmente con ignoreerrors='only_download' - la
                    # tarea completa igual reporta éxito, pero ESTA fila no tiene un
                    # archivo real que recodificar ni marcar como completado).
                    row.update_progress(0, status=self.tr("Error") if hasattr(self, "tr") else "Error")
                    row.mark_error()
                    continue

                row.add_output_files([actual_path])

                if recode_requested and self._start_post_download_recode(
                    actual_path, request_data, row, row.original_title or request_data.get("title")
                ):
                    # El estado "Completado"/envío al editor lo resuelve
                    # _on_recode_job_status una vez termine la recodificación.
                    continue

                row.update_progress(100, status=self.tr("Completado") if hasattr(self, "tr") else "Completado")
                row.mark_completed(filepath=actual_path or getattr(row, 'downloaded_filepath', None))

                if editor_mgr and editor_mgr.is_auto_send_enabled and hasattr(row, 'downloaded_filepath') and row.downloaded_filepath:
                    editor_mgr.process_raw_download(actual_path or row.downloaded_filepath, request_data)
            elif message == "SKIPPED_CONFLICT":
                # No es un error: la política de conflicto elegida fue "Omitir"
                # y el archivo ya existía.
                row.update_progress(0, status=self.tr("Omitido") if hasattr(self, "tr") else "Omitido")
            else:
                row.update_progress(0, status=self.tr("Error") if hasattr(self, "tr") else "Error")
                row.mark_error()

        if success:
            title = task_data["request_data"].get("title", "").strip()
            output_dir = task_data["request_data"].get("output_path", "")
            if title and output_dir:
                keep_thumb = task_data["request_data"].get("download_thumbnail_file", False)
                CleanupManager.cleanup_ytdlp_temp_files(output_dir, title, keep_thumbnail=keep_thumb)
                CleanupManager.deferred_cleanup(output_dir, title, keep_thumbnail=keep_thumb)

        # Despachar siguiente tarea si existe
        from core.utils.config_manager import get_config
        max_concurrent = get_config().get("max_concurrent_downloads", 3)
        if self.pending_tasks and len(self.active_workers) < max_concurrent:
            next_task = self.pending_tasks.pop(0)
            self._start_task_worker(next_task)

        if not self.active_workers and not self.pending_tasks:
            self.is_downloading = False
            self.download_text_changed.emit(self.tr("Descargar") if hasattr(self, "tr") else "Descargar")
            self.progress_updated.emit(100, self.tr("Descargas completadas") if hasattr(self, "tr") else "Descargas completadas", "done")
            if self.tab.taskbar_manager:
                self.tab.taskbar_manager.stop()
        else:
            self._emit_batch_progress()

        self.download_finished_signal.emit(success, message)

    def _fragment_suffix(self, request_data, frag_idx):
        """Sufijo de nombre de archivo del fragmento en la posición 1-based frag_idx
        (mismo criterio que downloader_master.py al nombrar cada corte)."""
        fragments = request_data.get("selected_fragments") or []
        if frag_idx and 1 <= frag_idx <= len(fragments):
            frag = fragments[frag_idx - 1]
            if len(frag) > 2 and frag[2]:
                return frag[2]
        return f"fragment{frag_idx:02d}" if frag_idx else "fragment"

    def _recode_status_text(self, position, total, label: str | None = None):
        label = label or (self.tr("Recodificando...") if hasattr(self, "tr") else "Recodificando...")
        if total and total > 1 and position:
            return (self.tr("{0} ({1} de {2})").format(label, position, total)
                    if hasattr(self, "tr") else f"{label} ({position} de {total})")
        return label

    def _queue_fragment_recodes(self, row, fragment_files, request_data, base_title):
        """
        Encola una recodificación por cada archivo de un corte con fragmentos, todas
        reportando su progreso a la MISMA fila ("Recodificando N de M...", ver
        _recode_status_text) en vez de a una fila por fragmento - misma fila única que
        usa Proceso Avanzado para un corte múltiple (ver conversación). No se resuelve
        el estado final (Completado/Error) de la fila hasta que TODAS terminen (ver
        _on_recode_job_status) - self._row_recode_pending/_row_recode_results llevan
        esa cuenta.

        Devuelve True si se pudo encolar al menos una, False si ninguna arrancó (ej.
        preset inválido) - en ese caso el llamador resuelve "Completado" normalmente.
        """
        total = len(fragment_files)
        self._row_recode_pending[row] = total
        self._row_recode_results[row] = {"all_ok": True, "final_paths": []}

        started = 0
        for i, (actual_path, suffix) in enumerate(fragment_files, start=1):
            title = f"{base_title} - {suffix}" if base_title else suffix
            if self._start_post_download_recode(
                actual_path, request_data, row, title,
                fragment_position=i, fragment_total=total,
            ):
                started += 1
            else:
                self._row_recode_pending[row] -= 1
                self._row_recode_results[row]["all_ok"] = False

        if started == 0:
            del self._row_recode_pending[row]
            del self._row_recode_results[row]
            return False
        return True

    def _parse_duration_to_seconds(self, duration_str: str) -> float:
        """Convierte una cadena de duración (ej. 00:03:20) a segundos."""
        if not duration_str or duration_str == "0":
            return 0.0
        try:
            parts = duration_str.split(":")
            if len(parts) == 3:
                return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
            elif len(parts) == 2:
                return float(parts[0]) * 60 + float(parts[1])
            else:
                return float(duration_str)
        except Exception:
            return 0.0

    def _resolve_media_duration(self, row, path) -> float:
        """Duración del medio en segundos, para que la barra de la recodificación pueda
        calcular un porcentaje.

        Es imprescindible: _run_ffmpeg_command (queue_manager.py) solo emite progreso
        `if duration_sec > 0`. Con 0 no manda ni un porcentaje, así que la barra se
        quedaba clavada en 0% durante toda la recodificación y saltaba a 100 al acabar.

        Antes se pedía con FFprobeMetadataManager.get_metadata_instant(), y ahí estaba el
        fallo: ese método es SOLO-CACHÉ por diseño —si no tiene el archivo cacheado
        devuelve datos básicos de os.stat y encola el sondeo para más tarde—. El archivo
        que se le pasaba acababa de descargarse y de renombrarse a cuarentena, así que
        nunca estaba en caché y siempre devolvía 0. Y en silencio, porque no lanza
        excepción: por eso no había ni un aviso en el log.

        Ahora se intenta en tres capas, de la más barata a la más cara:
          1. La duración que yt-dlp ya dio en el análisis y que la fila guardó.
          2. Un sondeo de ffprobe BLOQUEANTE, que sí lee el archivo.
          3. Si aun así no hay número, 0.0 y quien llama pone la barra indeterminada.
        """
        conocida = getattr(row, "media_duration_sec", None)
        if conocida and conocida > 0:
            return float(conocida)

        try:
            from core.tabs.editing_media.ffprobe_metadata_manager import FFprobeMetadataManager
            # _extract_ffprobe_json es el sondeo síncrono real (el que corre FFprobeTask
            # en su hilo), a diferencia de get_metadata_instant, que no bloquea y por eso
            # no sirve para un archivo recién creado.
            meta = FFprobeMetadataManager.get_instance()._extract_ffprobe_json(path, "video")
            duracion = self._parse_duration_to_seconds((meta or {}).get("duración", "0"))
            if duracion > 0:
                return duracion
        except Exception as e:
            logger.debug(f"QuickModeTab: no se pudo sondear la duración de {path}: {e}")

        logger.warning(
            f"QuickModeTab: sin duración para '{os.path.basename(path)}'; la barra de "
            f"recodificación irá en modo indeterminado."
        )
        return 0.0

    def _start_post_download_recode(self, actual_path, request_data, row, title,
                                     fragment_position=None, fragment_total=None):
        """
        Encola el/los job(s) de posprocesado async para el archivo que acaba de bajar
        esta fila. Contraparte de
        AdvancedProcessTab.DownloadController._start_post_download_recode (modo SOLO)
        pero reflejando el progreso en la fila de activity_panel en vez de en
        output_options. fragment_position/fragment_total (1-based) se usan solo para
        el texto de progreso cuando esta fila agrupa varios fragmentos (ver
        _queue_fragment_recodes) - None/1 para un archivo normal. Devuelve True si el
        job quedó encolado (la fila queda a cargo de _on_recode_job_progress/_status),
        False si no se pudo iniciar - en ese caso el llamador debe resolver el estado
        "Completado" normalmente.

        Recodificación y Reescalado IA son combinables (ver tarjeta "Posprocesar",
        recode_options.py): con las dos activas se encadenan -- Reescalado IA primero
        (hacia un archivo temporal propio, invisible), Recodificación después (con el
        intermedio como entrada, ver _continue_chain_to_recode) -- mismo orden y
        mismas razones que Herramientas Multimedia
        (video_tools_view.py::_start_chained_jobs).
        """
        if not actual_path or not os.path.exists(actual_path) or os.path.isdir(actual_path):
            logger.warning(f"QuickModeTab: No se encontró el archivo descargado para posprocesar ({title}).")
            return False

        recode_enabled = bool(request_data.get("recode_enabled"))
        upscale_enabled = bool(request_data.get("upscale_enabled"))

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
            logger.warning(f"QuickModeTab: Preajuste de posprocesado '{preset_name}' no encontrado, se omite ({title}).")
            return False

        try:
            backup_path = quarantine_for_recode(actual_path)
        except Exception as e:
            logger.error(f"QuickModeTab: No se pudo poner en cuarentena '{actual_path}': {e}")
            return False

        duration_sec = self._resolve_media_duration(row, backup_path)

        chain_next = None
        stage_label = None
        if recode_enabled and upscale_enabled:
            upscale_preset_name = request_data.get("upscale_preset_name")
            upscale_settings = get_preset_manager().get_settings(IA_TOOLS_NAMESPACE, upscale_preset_name)
            if not upscale_settings:
                logger.warning(f"QuickModeTab: Preajuste de Reescalado IA '{upscale_preset_name}' no encontrado, se omite esa etapa ({title}).")
            else:
                fps, duration_sec = probe_fps_and_duration(backup_path, duration_sec)
                chain_temp_dir = tempfile.mkdtemp(prefix="dowp_chain_qm_")
                job_id, _intermediate_path = start_upscale_stage(
                    self.queue_mgr, backup_path, upscale_settings, chain_temp_dir,
                    fps, duration_sec, title=f"Reescalado IA: {title}",
                )
                chain_next = {
                    "original_path": actual_path,
                    "recode_preset_name": request_data.get("recode_preset_name"),
                    "recode_prefix": request_data.get("recode_filename_prefix") or "",
                    "recode_suffix": request_data.get("recode_filename_suffix") or "",
                }
                stage_label = self.tr("Reescalando con IA...")

        if chain_next is None:
            if upscale_enabled and not recode_enabled:
                fps, duration_sec = probe_fps_and_duration(backup_path, duration_sec)
                job_id = self.queue_mgr.add_job({
                    "input_path": backup_path,
                    "output_path": out_file,
                    "upscale_options": settings,
                    "fps": fps,
                    "duration_sec": duration_sec,
                    "title": f"Reescalado IA: {title}",
                }, "UPSCALE_VIDEO")
                stage_label = self.tr("Reescalando con IA...")
            else:
                job_id = self.queue_mgr.add_job({
                    "input_path": backup_path,
                    "output_path": out_file,
                    "settings": settings,
                    "duration_sec": duration_sec,
                    "title": f"Recode: {title}",
                }, "RECODE")

        self._recode_by_download[job_id] = row
        self._recode_state[job_id] = {
            "backup_path": backup_path,
            "keep_original": request_data.get("recode_keep_original", True),
            "request_data": dict(request_data),
            "title": title,
            "fragment_position": fragment_position,
            "fragment_total": fragment_total,
            "chain_next": chain_next,
        }

        estado = self._recode_status_text(fragment_position, fragment_total, label=stage_label)
        if duration_sec > 0:
            row.update_progress(0, info="", status=estado)
        else:
            # Sin duración no habrá porcentajes (ver _resolve_media_duration): barra en
            # movimiento en vez de un 0% congelado que parece un cuelgue.
            row.set_busy(estado)
        # La cola global nace pausada y solo se reanuda desde Proceso Avanzado (modo
        # LOTES) o Herramientas Multimedia (ver video_tools_view.py) - sin esto, un job
        # encolado desde Modo Rápido se queda esperando indefinidamente si el
        # usuario nunca tocó esas otras pestañas.
        self.queue_mgr.start_queue()
        return True

    def _on_recode_job_progress(self, job_id, percent, speed, eta):
        row = self._recode_by_download.get(job_id)
        if row is None:
            return
        info = f"{speed} | {eta}" if speed and eta else (speed or eta or "")
        state = self._recode_state.get(job_id, {})
        label = self.tr("Reescalando con IA...") if state.get("chain_next") else None
        status = self._recode_status_text(state.get("fragment_position"), state.get("fragment_total"), label=label)
        row.update_progress(percent, info=info, status=status)

    def _continue_chain_to_recode(self, job_id, row, state):
        """Arma y encola la etapa 2 (Recodificación) de una cadena, usando la
        salida de la etapa 1 (Reescalado IA, `job_id`) como entrada. Reusa el
        MISMO backup_path/keep_original/request_data/title/fragment_* que ya
        traía `state` (la cuarentena del archivo original se hizo una sola vez,
        antes de la etapa 1 -- ver _start_post_download_recode) con
        `chain_next=None` -- así el job nuevo es indistinguible de un RECODE
        normal para _on_recode_job_status, que lo resuelve con el mismo código
        de siempre cuando termine. Misma lógica que
        AdvancedProcessTab.DownloadController._continue_chain_to_recode."""
        chain_next = state["chain_next"]
        upscale_job = self.queue_mgr.get_job(job_id)
        intermediate_path = upscale_job.final_filepath if upscale_job else None
        self.queue_mgr.remove_job(job_id)

        title = state.get("title", "")

        if not intermediate_path or not os.path.exists(intermediate_path):
            logger.error(f"QuickModeTab: la etapa de Reescalado IA no dejó un archivo válido, se aborta la cadena ({title}).")
            rollback_backup(state.get("backup_path"))
            row.update_progress(0, status=self.tr("Error al reescalar"))
            row.mark_error()
            return

        settings, out_file = build_recode_output_path(
            chain_next["original_path"], "video_tools/avanzado", chain_next["recode_preset_name"],
            prefix=chain_next["recode_prefix"], suffix=chain_next["recode_suffix"],
        )
        if not settings:
            logger.warning(f"QuickModeTab: Preajuste de Recodificación inválido a mitad de cadena, se omite ({title}).")
            rollback_backup(state.get("backup_path"))
            row.update_progress(0, status=self.tr("Error al recodificar"))
            row.mark_error()
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
        }, "RECODE")

        self._recode_by_download[new_job_id] = row
        self._recode_state[new_job_id] = {**state, "chain_next": None}
        self._chain_cleanup[new_job_id] = intermediate_path

        estado = self._recode_status_text(state.get("fragment_position"), state.get("fragment_total"))
        if duration_sec > 0:
            row.update_progress(0, info="", status=estado)
        else:
            row.set_busy(estado)

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
            logger.warning(f"QuickModeTab: no se pudo limpiar el intermedio de cadena '{intermediate_path}': {e}")

    def _on_recode_job_status(self, job_id, status):
        if job_id not in self._recode_by_download:
            return
        if status not in ("COMPLETED", "FAILED", "CANCELLED"):
            return  # estado intermedio (RUNNING, etc.) - nada que resolver todavía

        row = self._recode_by_download.pop(job_id)
        state = self._recode_state.pop(job_id, {})

        if state.get("chain_next") and status == "COMPLETED":
            # Etapa 1 (Reescalado IA) de una cadena terminó bien -- todavía NO es el
            # resultado final, arma la etapa 2 (Recodificación) y listo, no cae al
            # resto de esta función (backup/fila se resuelven recién cuando ESA etapa
            # termine). FAILED/CANCELLED de la etapa 1 SÍ caen al camino de abajo tal
            # cual -- es un fallo genérico más, mismo criterio que cualquier otro.
            self._continue_chain_to_recode(job_id, row, state)
            return

        backup_path = state.get("backup_path")
        keep_original = state.get("keep_original", True)
        request_data = state.get("request_data") or {}
        title = state.get("title", "")
        fragment_total = state.get("fragment_total")
        recode_job = self.queue_mgr.get_job(job_id)

        from core.utils.file_conflict_manager import commit_backup, rollback_backup, BACKUP_SUFFIX

        final_path = None
        ok = False
        if status == "COMPLETED":
            # Éxito: la casilla "Mantener medios originales" decide qué pasa con el
            # archivo bajado antes de recodificar.
            if keep_original:
                rollback_backup(backup_path)
            else:
                commit_backup(backup_path)
            final_path = recode_job.final_filepath if recode_job else None
            ok = True
            logger.info(f"QuickModeTab: Recodificación post-descarga completada ({title}).")
        else:
            # Fallo o cancelación: SIEMPRE se restaura, sin importar "mantener
            # originales" (la casilla nunca causa pérdida de datos ante un error).
            rollback_backup(backup_path)
            if backup_path and backup_path.endswith(BACKUP_SUFFIX):
                final_path = backup_path[: -len(BACKUP_SUFFIX)]
            if status == "FAILED":
                err = recode_job.error_message if recode_job else "desconocido"
                logger.error(f"QuickModeTab: Falló la recodificación post-descarga de '{title}': {err}")

        if final_path:
            # is_stem_source=False: el nombre del recodificado lleva el prefijo/sufijo
            # elegido por el usuario, no sirve como base para buscar sidecars.
            row.add_output_files([final_path], is_stem_source=False)

        if final_path:
            from core.services.editor_integration_manager import EditorIntegrationManager
            editor_mgr = EditorIntegrationManager.get_instance()
            if editor_mgr and editor_mgr.is_auto_send_enabled:
                actual = self._find_actual_downloaded_file(final_path)
                editor_mgr.process_raw_download(actual or final_path, request_data)

        self.queue_mgr.remove_job(job_id)
        intermediate = self._chain_cleanup.pop(job_id, None)
        if intermediate:
            self._cleanup_chain_intermediate_path(intermediate)

        if fragment_total and fragment_total > 1 and row in self._row_recode_pending:
            # Parte de un grupo (corte con varios fragmentos, una sola fila, ver
            # _queue_fragment_recodes) - no se resuelve el estado final de la fila
            # hasta que TODAS las recodificaciones del grupo terminen. Las que sigan
            # pendientes van a ir mostrando su propio "Recodificando N de M..." apenas
            # les toque correr (ver _on_recode_job_progress) - aquí no hace falta
            # empujar ese texto a mano.
            results = self._row_recode_results.setdefault(row, {"all_ok": True, "final_paths": []})
            results["all_ok"] = results["all_ok"] and ok
            if final_path:
                results["final_paths"].append(final_path)

            remaining = self._row_recode_pending[row] - 1
            self._row_recode_pending[row] = remaining
            if remaining > 0:
                return

            del self._row_recode_pending[row]
            del self._row_recode_results[row]
            if results["all_ok"]:
                row.update_progress(100, status=self.tr("Completado") if hasattr(self, "tr") else "Completado")
                row.mark_completed(filepath=results["final_paths"][-1] if results["final_paths"] else None)
            else:
                row.update_progress(0, status=self.tr("Error al recodificar") if hasattr(self, "tr") else "Error al recodificar")
                row.mark_error()
            return

        # Camino normal: un solo archivo (sin fragmentos, o un fragmento único).
        if status == "COMPLETED":
            row.update_progress(100, status=self.tr("Completado") if hasattr(self, "tr") else "Completado")
            row.mark_completed(filepath=final_path)
        else:
            if status == "CANCELLED":
                row.update_progress(0, status=self.tr("Recodificación cancelada") if hasattr(self, "tr") else "Recodificación cancelada")
            else:
                row.update_progress(0, status=self.tr("Error al recodificar") if hasattr(self, "tr") else "Error al recodificar")
                row.mark_error()
            if final_path:
                # La recodificación falló pero el original volvió de la cuarentena. Se
                # registra el archivo para que el botón de carpeta funcione, PERO sin
                # marcar la fila como completada: antes se llamaba a mark_completed()
                # justo después de mark_error(), y la fila quedaba a la vez terminada y
                # fallida -- se pintaba de verde y el grupo la contaba dos veces.
                row.downloaded_filepath = final_path
                row.add_output_files([final_path])
                if row.is_error():
                    row.refresh_reveal_button()
                else:
                    row.mark_completed(filepath=final_path)

        # El job RECODE interno ya se quitó de la cola más arriba, en el tramo común
        # de esta misma función (no debe quedar visible ni reintentable en la cola
        # compartida con Proceso Avanzado / Herramientas Multimedia: no es algo que el
        # usuario haya encolado directamente). Aquí NO se vuelve a quitar: llamar dos
        # veces a remove_job() con el mismo job_id emitía job_removed dos veces, y la
        # segunda llegaba cuando la tarjeta ya no existía -- de ahí los "Tarjeta para
        # ... NO encontrada en self.cards!" y los "Cola pausada" duplicados del log.
