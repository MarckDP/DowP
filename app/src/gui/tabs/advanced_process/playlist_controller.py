# src/gui/tabs/single_process/playlist_controller.py
from PySide6.QtCore import QObject, QCoreApplication
from PySide6.QtWidgets import QDialog
from core.logger.logger_manager import logger
from core.utils.config_manager import get_config
from gui.dialogs.playlist_selection_dialog import PlaylistSelectionDialog

class PlaylistController(QObject):
    def __init__(self, tab):
        super().__init__()
        self.tab = tab

    def is_playlist_result(self, data):
        entries = data.get("entries") or []
        if not entries:
            return False
        return data.get("_type") in ("playlist", "multi_video") or len(entries) > 1

    def handle_playlist_analysis_result(self, job_id, data):
        job = self.tab.queue_mgr.get_job(job_id)
        if not job:
            return

        dialog = PlaylistSelectionDialog(data, self.tab)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.result_data:
            job.error_message = QCoreApplication.translate("AdvancedProcessTab", "Selección de playlist cancelada")
            self.tab.queue_mgr.update_job_status(job_id, "FAILED")
            return

        selected = dialog.result_data.get("selected_indices", [])
        if not selected:
            job.error_message = QCoreApplication.translate("AdvancedProcessTab", "No se seleccionaron medios")
            self.tab.queue_mgr.update_job_status(job_id, "FAILED")
            return

        title = data.get("title") or QCoreApplication.translate("AdvancedProcessTab", "Playlist")
        job.job_type = "PLAYLIST"
        job.title = title
        job.config.update({
            "url": data.get("original_url", data.get("webpage_url", job.config.get("url"))),
            "title": title,
            "output_path": self.tab.output_options.output_path_input.text(),
            "playlist_mode": dialog.result_data.get("playlist_mode", "video+audio"),
            "playlist_quality": dialog.result_data.get("playlist_quality", "best_compatible"),
            "conflict_policy": self.tab.output_options.conflict_policy_combo.currentData(),
            "selected_indices": selected,
            "total_videos": dialog.result_data.get("total_videos", len(data.get("entries") or [])),
            "speed_limit": f"{int(self.tab.output_options.speed_limit_input.value() * 1024)}K" if self.tab.output_options.speed_limit_input.value() > 0 else None,
            "embed_metadata": get_config().get("embed_metadata", True),
            "embed_thumbnail": get_config().get("embed_thumbnail", True),
            "remove_sponsors": get_config().get("remove_sponsors", False),
            "thumbnail_cache": dialog.result_data.get("thumbnail_cache", {}),
        })
        job.analysis_data = data
        job.video_data = data
        job.request_data = None

        self.tab.queue_mgr.update_job_status(job_id, "PENDING")
        if job_id == self.tab._selected_job_id or self.tab._selected_job_id is None or len(self.tab.queue_mgr.get_all_jobs()) == 1:
            self.tab._on_card_selected(job_id)

    def unpack_slow_playlist_result(self, job_id, data):
        entries = data.get("entries") or []
        if not entries:
            job = self.tab.queue_mgr.get_job(job_id)
            if job:
                job.error_message = QCoreApplication.translate("AdvancedProcessTab", "La playlist está vacía o no tiene elementos extraíbles.")
                self.tab.queue_mgr.update_job_status(job_id, "FAILED")
            return

        # 1. Actualizar el primer trabajo con la primera entrada
        first_entry = entries[0]
        title = first_entry.get('title') or f"Video 1"
        job = self.tab.queue_mgr.get_job(job_id)
        if job:
            job.title = title
            job.config["title"] = title
            job.config["url"] = first_entry.get("webpage_url") or first_entry.get("url") or job.config.get("url")
            job.config["playlist_index"] = first_entry.get("playlist_index", 1)
            job.request_data = self.tab._build_default_request_data(first_entry, title)
        
        self.tab.queue_mgr.update_job_data(job_id, video_data=first_entry)
        self.tab.queue_mgr.update_job_status(job_id, "PENDING")
        
        # 2. Agregar el resto de entradas a la cola como nuevos trabajos
        for i, entry in enumerate(entries[1:], start=2):
            if not entry:
                continue
            entry_title = entry.get('title') or QCoreApplication.translate("AdvancedProcessTab", "Video {0}").format(i)
            entry_url = entry.get("webpage_url") or entry.get("url") or (job.config.get("url") if job else "")
            
            new_config = {
                "url": entry_url,
                "title": entry_title,
                "playlist_index": entry.get("playlist_index", i)
            }
            new_job_id = self.tab.queue_mgr.add_job(new_config, "DOWNLOAD")
            new_job = self.tab.queue_mgr.get_job(new_job_id)
            if new_job:
                new_job.request_data = self.tab._build_default_request_data(entry, entry_title)
            
            self.tab.queue_mgr.update_job_data(new_job_id, video_data=entry)
            self.tab.queue_mgr.update_job_status(new_job_id, "PENDING")

        # 3. Actualizar la selección y habilitar el botón de descarga
        if job_id == self.tab._selected_job_id or len(self.tab.queue_mgr.get_all_jobs()) == 1:
            logger.info(f"SingleProcessTab: Análisis y desempaquetado de playlist finalizado con éxito")
            self.tab.output_options.btn_start_download.setEnabled(True)

        if job_id == self.tab._selected_job_id or self.tab._selected_job_id is None or len(self.tab.queue_mgr.get_all_jobs()) == 1:
            self.tab._on_card_selected(job_id)

    def configure_specific_playlist(self, job_id):
        if not job_id:
            return
        job = self.tab.queue_mgr.get_job(job_id)
        if not job or job.job_type != "PLAYLIST" or not job.analysis_data:
            return
        if job.status == "RUNNING":
            return
        thumb_cache = job.config.get("thumbnail_cache", {})
        dialog = PlaylistSelectionDialog(job.analysis_data, self.tab, initial_config=job.config, thumbnail_cache=thumb_cache)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.result_data:
            # Aunque canceló, actualizar el caché de miniaturas si el worker descargó algo nuevo
            if dialog.thumb_worker:
                import threading
                with dialog.thumb_worker.lock:
                    new_cache = dict(dialog.thumb_worker.cache)
                if new_cache:
                    job.config["thumbnail_cache"] = new_cache
            return
        selected = dialog.result_data.get("selected_indices", [])
        if not selected:
            return
        job.config.update({
            "playlist_mode": dialog.result_data.get("playlist_mode", job.config.get("playlist_mode", "video+audio")),
            "playlist_quality": dialog.result_data.get("playlist_quality", job.config.get("playlist_quality", "best_compatible")),
            "conflict_policy": self.tab.output_options.conflict_policy_combo.currentData(),
            "selected_indices": selected,
            "total_videos": dialog.result_data.get("total_videos", job.config.get("total_videos", len(selected))),
            "thumbnail_cache": dialog.result_data.get("thumbnail_cache", thumb_cache),
        })
        self.tab.queue_mgr.update_job_data(job.job_id, video_data=job.video_data, request_data=None)
        self.tab.queue_mgr.update_job_status(job.job_id, "PENDING")
        if job_id == self.tab._selected_job_id:
            self.tab._on_card_selected(job.job_id)

    def show_playlist_job(self, job):
        self.tab._current_video_data = None
        self.tab.video_details.reset_ui()
        self.tab.subtitle_controller.clear_subtitles()
        self.tab.video_details.title_input.setText(job.title)
        self.tab.video_details.title_input.setCursorPosition(0)

        # --- Miniatura de la playlist ---
        # Prioridad: miniatura de la playlist > miniatura del primer entry
        # Siempre preferir el array 'thumbnails' (con resoluciones) sobre 'thumbnail' (URL genérica)
        thumb_url = None
        playlist_data = job.video_data or {}
        
        def _best_thumbnail_url(data_dict):
            """Extrae la URL de miniatura de mayor resolución de un dict de yt-dlp."""
            # 1. Primero buscar en el array 'thumbnails' (tiene múltiples resoluciones)
            thumbs = data_dict.get("thumbnails") or []
            valid = [t for t in thumbs if t.get("url")]
            if valid:
                valid.sort(key=lambda t: (t.get("width") or 0) * (t.get("height") or 0), reverse=True)
                return valid[0]["url"]
            # 2. Fallback al campo 'thumbnail' simple
            return data_dict.get("thumbnail")
        
        def _youtube_thumb_chain(url):
            """Para URLs de YouTube, genera una cadena de resoluciones de mayor a menor."""
            if not url:
                return url, []
            import re
            # Detectar patrón de miniatura de YouTube: i.ytimg.com/vi/ID/QUALITY.jpg
            match = re.match(r'(https?://i\.ytimg\.com/vi/[^/]+/)([^?]+)', url)
            if match:
                base = match.group(1)
                # Cadena: maxresdefault (1280x720) → sddefault (640x480) → original
                primary = base + "maxresdefault.jpg"
                fallbacks = [base + "sddefault.jpg", url]
                return primary, fallbacks
            return url, []
        
        # 1. Buscar miniatura propia de la playlist
        thumb_url = _best_thumbnail_url(playlist_data)
        
        # 2. Fallback: miniatura del primer entry
        if not thumb_url:
            entries = playlist_data.get("entries", [])
            first_entry = next((e for e in entries if e), {})
            thumb_url = _best_thumbnail_url(first_entry)
        
        # 3. Para YouTube, construir cadena de resoluciones
        thumb_url, fallback_urls = _youtube_thumb_chain(thumb_url)
        
        # Cargar la miniatura directamente con fallbacks
        if thumb_url:
            self.tab.video_details.load_thumbnail(thumb_url, fallback_urls=fallback_urls)
            self.tab.video_details.btn_download_thumb.setEnabled(True)
        else:
            self.tab.video_details.thumb_container.set_text(QCoreApplication.translate("AdvancedProcessTab", "Sin miniatura de playlist"))
            self.tab.video_details.btn_download_thumb.setEnabled(False)
        
        # Ocultar botón de corte (no aplica a playlists)
        self.tab.video_details.thumb_container.set_cut_button_visible(False)
        
        # Duración: no mostrar para playlist
        self.tab.video_details.thumb_container.set_duration(None)
        
        # --- Deshabilitar ModeSelector para playlists ---
        self.tab.video_details.mode_selector.btn_video_audio.setEnabled(False)
        self.tab.video_details.mode_selector.btn_audio.setEnabled(False)
        self.tab.video_details.mode_selector.btn_video.setEnabled(False)
        
        # Mostrar visualmente el modo configurado
        playlist_mode = job.config.get("playlist_mode", "video+audio")
        if playlist_mode == "audio_only":
            self.tab.video_details.mode_selector.btn_audio.setChecked(True)
            for btn in self.tab.video_details.mode_selector.buttons:
                btn.setProperty("active", "true" if btn == self.tab.video_details.mode_selector.btn_audio else "false")
                btn.style().unpolish(btn)
                btn.style().polish(btn)
        else:
            self.tab.video_details.mode_selector.btn_video_audio.setChecked(True)
            for btn in self.tab.video_details.mode_selector.buttons:
                btn.setProperty("active", "true" if btn == self.tab.video_details.mode_selector.btn_video_audio else "false")
                btn.style().unpolish(btn)
                btn.style().polish(btn)
        
        # --- Ocultar o bloquear combos ---
        self.tab.video_details.combo_video.blockSignals(True)
        self.tab.video_details.combo_video.clear()
        self.tab.video_details.combo_video.addItem(QCoreApplication.translate("AdvancedProcessTab", "Configurado en Playlist"))
        self.tab.video_details.combo_video.setEnabled(False)
        self.tab.video_details.combo_video.blockSignals(False)
        
        self.tab.video_details.combo_audio.blockSignals(True)
        self.tab.video_details.combo_audio.clear()
        self.tab.video_details.combo_audio.addItem(QCoreApplication.translate("AdvancedProcessTab", "Configurado en Playlist"))
        self.tab.video_details.combo_audio.setEnabled(False)
        self.tab.video_details.combo_audio.blockSignals(False)

        selected_count = len(job.config.get("selected_indices", []))
        total_count = job.config.get("total_videos", selected_count)
        mode_label = QCoreApplication.translate("AdvancedProcessTab", "Solo Audio") if job.config.get("playlist_mode") == "audio_only" else QCoreApplication.translate("AdvancedProcessTab", "Video + Audio")
        quality_label = job.config.get("playlist_quality", "best_compatible")
        self.tab.output_options.set_progress(
            0,
            QCoreApplication.translate("AdvancedProcessTab", "Playlist configurada: {0}/{1} | {2} | {3}").format(selected_count, total_count, mode_label, quality_label),
            "wait"
        )
        self.tab.output_options.btn_start_download.setEnabled(True)

        # Recodificación: config única para toda la playlist, vive en job.config (no en
        # request_data - ver advanced_process_view.py::_save_current_job_options).
        self.tab.recode_controller.restore_recode_to_ui(job.config)
