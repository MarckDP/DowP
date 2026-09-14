# src/gui/tabs/single_process/subtitle_controller.py
import os
import glob
import re
import threading
from PySide6.QtCore import QObject, QCoreApplication
from PySide6.QtWidgets import QFileDialog
from core.logger.logger_manager import logger
from core.constants import LANGUAGE_ORDER, DEFAULT_PRIORITY
from core.ytdlp_logic.analyzer import strip_ansi_codes
from gui.tabs.advanced_process.workers import DownloadWorker

class SubtitleController(QObject):
    def __init__(self, tab):
        super().__init__()
        self.tab = tab
        self._cancellation_event = threading.Event()
        self._subtitle_worker = None
        self._subtitle_target_path = None
        self._subtitle_request_data = None

    def start_subtitle_download(self):
        """Inicia una descarga de solo subtítulos con selector de archivo."""
        if not self.tab._current_video_data:
            return
        url = self.tab._current_video_data.get("original_url", self.tab._current_video_data.get("webpage_url"))
        if not url:
            return

        def sanitize_filename(name):
            return re.sub(r'[<>:"/\\|?*#]', '', name).strip()

        title = sanitize_filename(self.tab.video_details.title_input.text().strip())
        lang_data = self.tab.subtitle_options.combo_subtitle_language.currentData()
        if not lang_data:
            return
        
        lang_code = lang_data.get("lang")
        
        # Obtener el formato seleccionado del combo (no hardcodear .vtt)
        fmt_data = self.tab.subtitle_options.combo_subtitle_format.currentData()
        ext = fmt_data.get("ext", "srt") if fmt_data else "srt"
        output_ext = self.get_selected_subtitle_output_ext() or ext
        
        # 1. Abrir selector de archivos con confirmación de sobreescritura
        default_filename = f"{title}.{lang_code}.{output_ext}"
        
        file_path, selected_filter = QFileDialog.getSaveFileName(
            self.tab,
            QCoreApplication.translate("AdvancedProcessTab", "Guardar subtítulo como"),
            os.path.join(self.tab.output_options.output_path_input.text(), default_filename),
            f"Subtitles (*.{output_ext});;All Files (*)",
            options=QFileDialog.Option(0) # Usar opciones por defecto que incluyen confirmación
        )
        
        if not file_path:
            return # Cancelado por el usuario

        self._subtitle_target_path = file_path
        
        # Separar directorio y nombre base para yt-dlp
        output_dir = os.path.dirname(file_path)
        # Usamos el nombre elegido por el usuario como plantilla
        # Quitamos la extensión porque yt-dlp la añade
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        # Si termina en .lang_code, lo quitamos también para evitar duplicados si yt-dlp lo añade
        if base_name.endswith(f".{lang_code}"):
            base_name = base_name[:-(len(lang_code)+1)]

        request_data = {
            "url": url,
            "output_path": output_dir,
            "title": base_name,
            "mode": "subtitle_only",
            "subtitle_lang": lang_code,
            "subtitle_is_auto": self.get_selected_subtitle_is_auto(),
            "subtitle_format": ext,
            "subtitle_output_ext": output_ext,
            "speed_limit": f"{int(self.tab.output_options.speed_limit_input.value() * 1024)}K" if self.tab.output_options.speed_limit_input.value() > 0 else None,
            "standardize_srt": self.tab.subtitle_options.chk_standardize_srt["switch"].isChecked(),
            "cut_subtitles": self.tab.subtitle_options.chk_cut_to_fragment["switch"].isChecked(),
            "selected_fragments": self.tab.video_details.selected_fragments,
            "fragment_mode": self.tab.video_details.fragment_mode
        }

        self.tab.subtitle_options.btn_download_subtitles.setEnabled(False)
        self.tab.output_options.set_progress(0, QCoreApplication.translate("AdvancedProcessTab", "Bajando subtítulos..."), "running")
        if self.tab.taskbar_manager:
            self.tab.taskbar_manager.set_state("indeterminate")
            
        self.tab._is_downloading = True
        
        # Ejecutar descarga en segundo plano directamente sin usar la cola global
        self._cancellation_event.clear()
        self._subtitle_worker = DownloadWorker(request_data, self._cancellation_event)
        self._subtitle_request_data = request_data.copy()
        
        def on_sub_progress(d):
            if d.get("status") == "downloading":
                p_str = strip_ansi_codes(d.get('_percent_str', '0%')).replace('%','').strip()
                try:
                    val = float(p_str)
                    speed = strip_ansi_codes(d.get('_speed_str', '')).strip() or '...'
                    eta = strip_ansi_codes(d.get('_eta_str', '')).strip() or '...'
                    msg = QCoreApplication.translate("AdvancedProcessTab", "Bajando subtítulos... {0}% — {1} — ETA: {2}").format(int(val), speed, eta)
                    self.tab.output_options.set_progress(int(val), msg, "downloading")
                    if self.tab.taskbar_manager:
                        self.tab.taskbar_manager.set_value(int(val))
                except Exception:
                    pass
            elif d.get("status") == "finished":
                self.tab.output_options.set_progress(100, QCoreApplication.translate("AdvancedProcessTab", "Procesando subtítulos..."), "downloading")

        def on_sub_finished(success, message):
            self.tab._is_downloading = False
            self.tab.subtitle_options.btn_download_subtitles.setEnabled(True)
            if self.tab.taskbar_manager:
                self.tab.taskbar_manager.stop()
                
            if success:
                self.process_downloaded_subtitles(output_dir, self._subtitle_request_data)
                self.tab.output_options.set_progress(100, QCoreApplication.translate("AdvancedProcessTab", "Subtítulos descargados con éxito"), "done")
                logger.info("AdvancedProcessTab: Descarga de subtítulos directa finalizada con éxito.")
            else:
                self.tab.output_options.set_progress(0, QCoreApplication.translate("AdvancedProcessTab", "Error al bajar subtítulos: {0}").format(message), "wait")
                logger.error(f"AdvancedProcessTab: Error en descarga de subtítulos: {message}")
                self._subtitle_target_path = None
                self._subtitle_request_data = None
                
            self._subtitle_worker = None

        self._subtitle_worker.progress.connect(on_sub_progress)
        self._subtitle_worker.finished.connect(on_sub_finished)
        self._subtitle_worker.start()

    def on_fragments_changed(self):
        """Habilita o deshabilita la opción de recortar subtítulos según los fragmentos."""
        has_fragments = bool(self.tab.video_details.selected_fragments)
        self.tab.subtitle_options.chk_cut_to_fragment["container"].setEnabled(has_fragments)
        if not has_fragments:
            self.tab.subtitle_options.chk_cut_to_fragment["switch"].setChecked(False)

    def on_subtitle_selection_changed(self):
        """Habilita o deshabilita el botón y opciones de subtítulos según la selección."""
        lang_idx = self.tab.subtitle_options.combo_subtitle_language.currentIndex()
        format_idx = self.tab.subtitle_options.combo_subtitle_format.currentIndex()
        format_data = self.tab.subtitle_options.combo_subtitle_format.currentData()
        
        # Habilitar solo si hay algo seleccionado que no sea el placeholder
        is_valid = lang_idx > 0 and format_idx >= 0 and bool(format_data)
        self.tab.subtitle_options.btn_download_subtitles.setEnabled(is_valid)
        self.tab.subtitle_options.set_header_active(is_valid)
        
        # Opciones generales de subtítulos requieren un idioma seleccionado
        self.tab.subtitle_options.chk_download_with_media["container"].setEnabled(is_valid)
        
        if not is_valid:
            # Forzar deshabilitado si no hay subtítulo
            self.tab.subtitle_options.chk_standardize_srt["container"].setEnabled(False)
            self.tab.subtitle_options.chk_cut_to_fragment["container"].setEnabled(False)
        else:
            # Evaluar condiciones específicas si hay subtítulo válido
            self.tab.subtitle_options.update_standardize_visibility()
            self.on_fragments_changed()

    def get_selected_subtitle_lang(self):
        data = self.tab.subtitle_options.combo_subtitle_language.currentData()
        return data.get("lang") if data else None

    def get_selected_subtitle_is_auto(self):
        fmt_data = self.tab.subtitle_options.combo_subtitle_format.currentData()
        if fmt_data and "auto" in fmt_data:
            return fmt_data.get("auto", False)
        data = self.tab.subtitle_options.combo_subtitle_language.currentData()
        return data.get("automatic", False) if data else False

    def get_selected_subtitle_output_ext(self):
        fmt_data = self.tab.subtitle_options.combo_subtitle_format.currentData()
        if not fmt_data:
            return None
        if self.tab.subtitle_options.chk_cut_to_fragment["switch"].isChecked():
            return "srt"
        if self.tab.subtitle_options.chk_standardize_srt["switch"].isChecked():
            return "srt"
        return fmt_data.get("output_ext", fmt_data.get("ext"))

    def process_downloaded_subtitles(self, directory, request_data=None):
        """Mueve el subtítulo directo al destino elegido sin perder formato o fragmentos."""
        request_data = request_data or {}

        # Si se recortó en fragmentos, el backend ya generó varios archivos con sufijo.
        # No deben colapsarse en la ruta única elegida en el diálogo.
        if request_data.get("cut_subtitles") and request_data.get("selected_fragments"):
            self._subtitle_target_path = None
            self._subtitle_request_data = None
            return

        # Si el usuario seleccionó una ruta destino personalizada, usamos el nombre base del archivo
        # elegido (sin extensión) para buscar las descargas de yt-dlp, ya que yt-dlp usa ese nombre base.
        if self._subtitle_target_path:
            base = os.path.splitext(os.path.basename(self._subtitle_target_path))[0]
            title_pattern = base
        else:
            title_pattern = self.tab.video_details.title_input.text().strip()

        if not title_pattern:
            self._subtitle_target_path = None
            self._subtitle_request_data = None
            return

        # Buscar cualquier archivo que empiece con el patrón y sea un subtítulo
        sub_extensions = ('srt', 'vtt', 'ass', 'ssa', 'ttml', 'srv1', 'srv2', 'srv3', 'json3')
        expected_ext = request_data.get("subtitle_output_ext") or request_data.get("subtitle_format")
        ordered_exts = []
        if expected_ext:
            ordered_exts.append(expected_ext.lower())
        ordered_exts.extend(e for e in sub_extensions if e not in ordered_exts)

        patterns = [f"{title_pattern}*.{ext}" for ext in ordered_exts]
        found_subs = []
        for pattern in patterns:
            for sub_file in glob.glob(os.path.join(directory, pattern)):
                if sub_file not in found_subs:
                    found_subs.append(sub_file)

        files_to_process = found_subs[:1] if self._subtitle_target_path else found_subs
        
        final_files_for_editor = []

        for sub_file in files_to_process:
            logger.info(f"AdvancedProcessTab: Subtítulo encontrado: {sub_file}")
            
            # Si el usuario eligió una ruta específica, movemos/renombramos el resultado final
            if self._subtitle_target_path:
                try:
                    # Si el archivo de salida no es el mismo que el destino final, lo movemos
                    if os.path.normpath(sub_file) != os.path.normpath(self._subtitle_target_path):
                        # Si el destino ya existe, lo quitamos para que os.rename no falle en Windows
                        if os.path.exists(self._subtitle_target_path):
                            os.remove(self._subtitle_target_path)
                        os.rename(sub_file, self._subtitle_target_path)
                        logger.info(f"AdvancedProcessTab: Subtítulo movido a destino final: {self._subtitle_target_path}")
                    
                    # Limpiar el original si quedó (solo si era .vtt y el destino final no es ese mismo archivo .vtt)
                    if (sub_file.lower().endswith(".vtt") and 
                        os.path.exists(sub_file) and 
                        os.path.normpath(sub_file) != os.path.normpath(self._subtitle_target_path)):
                        os.remove(sub_file)
                        
                    final_files_for_editor.append(self._subtitle_target_path)
                except Exception as e:
                    logger.error(f"AdvancedProcessTab: Error al mover subtítulo al destino final: {e}")
            else:
                # Si no había ruta de destino (como en fragmentos), el archivo original es el final
                final_files_for_editor.append(sub_file)
                
        # Integración con el editor
        from core.services.editor_integration_manager import EditorIntegrationManager
        editor_mgr = EditorIntegrationManager.get_instance()
        if editor_mgr and editor_mgr.is_auto_send_enabled:
            for filepath in final_files_for_editor:
                editor_mgr.process_raw_download(filepath, request_data)
        
        # Resetear la ruta objetivo tras procesar
        self._subtitle_target_path = None
        self._subtitle_request_data = None

    def populate_subtitles(self, data):
        sub_combo = self.tab.subtitle_options.combo_subtitle_language
        sub_combo.clear()
        
        subs = data.get('subtitles') or {}
        auto_subs = data.get('automatic_captions') or {}
        
        if not subs and not auto_subs:
            sub_combo.addItem(QCoreApplication.translate("AdvancedProcessTab", "Sin subtítulos disponibles"))
            sub_combo.setEnabled(False)
            self.tab.subtitle_options.btn_download_subtitles.setEnabled(False)
            return
            
        sub_combo.setEnabled(True)
        self.tab.subtitle_options.btn_download_subtitles.setEnabled(True)
        sub_combo.addItem(QCoreApplication.translate("AdvancedProcessTab", "Seleccionar idioma..."), None)
        
        # Merge unique languages
        all_langs = {}
        
        for lang, formats in subs.items():
            name = formats[-1].get('name', lang) if formats else lang
            all_langs[lang] = name
            
        for lang, formats in auto_subs.items():
            if lang not in all_langs:
                name = formats[-1].get('name', lang) if formats else lang
                all_langs[lang] = name
                
        # Sort languages
        sorted_langs = sorted(all_langs.keys(), key=lambda l: (
            LANGUAGE_ORDER.get(l.lower(), DEFAULT_PRIORITY),
            all_langs[l].lower()
        ))
        
        # Add to combo
        for lang in sorted_langs:
            name = all_langs[lang]
            is_auto = lang in auto_subs and lang not in subs
            sub_combo.addItem(f"{name} ({lang})", {"lang": lang, "automatic": is_auto})
                
        # Trigger format population
        self.on_subtitle_language_changed()

    def on_subtitle_language_changed(self):
        if not self.tab._current_video_data:
            return
            
        lang_combo = self.tab.subtitle_options.combo_subtitle_language
        fmt_combo = self.tab.subtitle_options.combo_subtitle_format
        
        # --- MEMORIA: Guardar selección actual ---
        current_selection = fmt_combo.currentData()
        current_ext = current_selection.get("ext") if current_selection else None
        current_is_auto = current_selection.get("auto") if current_selection else None
        
        # Bloquear señales para evitar que la limpieza (clear) detone actualizaciones
        # intermedias que apagarían otros switches por el estado "inválido" temporal
        fmt_combo.blockSignals(True)
        fmt_combo.clear()
        
        # Get selected user data
        idx = lang_combo.currentIndex()
        if idx < 0:
            fmt_combo.blockSignals(False)
            self.on_subtitle_selection_changed()
            self.tab.subtitle_options.update_standardize_visibility()
            return

        user_data = lang_combo.itemData(idx)
        if not user_data:
            # "Seleccionar idioma..."
            fmt_combo.addItem("-")
            fmt_combo.setEnabled(False)
            fmt_combo.blockSignals(False)
            self.on_subtitle_selection_changed()
            self.tab.subtitle_options.update_standardize_visibility()
            return
            
        lang = user_data.get("lang")
        
        subs = self.tab._current_video_data.get('subtitles', {})
        auto_subs = self.tab._current_video_data.get('automatic_captions', {})
        
        manual_formats = subs.get(lang, [])
        auto_formats = auto_subs.get(lang, [])
        
        if not manual_formats and not auto_formats:
            fmt_combo.addItem("-")
            fmt_combo.setEnabled(False)
            fmt_combo.blockSignals(False)
            self.on_subtitle_selection_changed()
            self.tab.subtitle_options.update_standardize_visibility()
            return
            
        fmt_combo.setEnabled(True)
        
        # 1. Obtener y limpiar formatos manuales y automáticos
        manual_exts = []
        for f in manual_formats:
            ext = f.get('ext')
            if ext and ext not in manual_exts:
                manual_exts.append(ext)
        
        auto_exts = []
        for f in auto_formats:
            ext = f.get('ext')
            if ext and ext not in auto_exts:
                auto_exts.append(ext)

        # 2. Verificar si el modo de recorte está activo para filtrar
        is_cut_active = self.tab.subtitle_options.chk_cut_to_fragment["switch"].isChecked()
        source_manual_exts = manual_exts[:]
        source_auto_exts = auto_exts[:]
        if is_cut_active:
            manual_exts = [e for e in manual_exts if e.lower() == "srt"]
            auto_exts = [e for e in auto_exts if e.lower() == "srt"]

        # 3. Función de ordenamiento (SRT y VTT primero)
        def sort_priority(ext_list):
            priority_map = {'srt': 0, 'vtt': 1}
            return sorted(ext_list, key=lambda x: (priority_map.get(x.lower(), 99), x.lower()))

        manual_exts = sort_priority(manual_exts)
        auto_exts = sort_priority(auto_exts)

        # 4. Añadir a la UI y restaurar selección si es posible
        restore_idx = -1
        
        for e in manual_exts:
            manual_label = QCoreApplication.translate("AdvancedProcessTab", "{0} (Manual)").format(e.upper())
            fmt_combo.addItem(manual_label, {"ext": e, "auto": False})
            if e == current_ext and current_is_auto is False:
                restore_idx = fmt_combo.count() - 1
            
        for e in auto_exts:
            auto_label = QCoreApplication.translate("AdvancedProcessTab", "{0} (Automático)").format(e.upper())
            fmt_combo.addItem(auto_label, {"ext": e, "auto": True})
            if e == current_ext and current_is_auto is True:
                restore_idx = fmt_combo.count() - 1

        if is_cut_active:
            has_manual_srt = any(e.lower() == "srt" for e in manual_exts)
            has_auto_srt = any(e.lower() == "srt" for e in auto_exts)
            if not has_manual_srt and source_manual_exts:
                source_ext = source_manual_exts[0]
                fmt_combo.addItem(QCoreApplication.translate("AdvancedProcessTab", "Convertir a SRT (Manual)"), {
                    "ext": source_ext,
                    "output_ext": "srt",
                    "auto": False
                })
                if current_is_auto is False:
                    restore_idx = fmt_combo.count() - 1
            if not has_auto_srt and source_auto_exts:
                source_ext = source_auto_exts[0]
                fmt_combo.addItem(QCoreApplication.translate("AdvancedProcessTab", "Convertir a SRT (Automático)"), {
                    "ext": source_ext,
                    "output_ext": "srt",
                    "auto": True
                })
                if current_is_auto is True:
                    restore_idx = fmt_combo.count() - 1

            for i in range(fmt_combo.count()):
                d = fmt_combo.itemData(i)
                if d and d.get("auto") == current_is_auto and d.get("output_ext", d.get("ext", "")).lower() == "srt":
                    restore_idx = i
                    break
            
        # Si no quedan formatos tras el filtrado (ej: modo recorte activo pero no hay srt/vtt)
        if fmt_combo.count() == 0:
            fmt_combo.addItem(QCoreApplication.translate("AdvancedProcessTab", "No compatible con corte"))
            fmt_combo.setEnabled(False)
        else:
            fmt_combo.setEnabled(True)
            # Restaurar selección previa si se encontró
            if restore_idx != -1:
                fmt_combo.setCurrentIndex(restore_idx)
            else:
                fmt_combo.setCurrentIndex(0)

        # Restaurar señales y disparar actualización final de estado real
        fmt_combo.blockSignals(False)
        self.on_subtitle_selection_changed()
        self.tab.subtitle_options.update_standardize_visibility()

    def clear_subtitles(self):
        self.tab.subtitle_options.combo_subtitle_language.clear()
        self.tab.subtitle_options.combo_subtitle_format.clear()
        self.tab.subtitle_options.btn_download_subtitles.setEnabled(False)
        self.tab.subtitle_options.update_standardize_visibility()

    def collect_subtitle_data(self):
        """Returns dict of current subtitle options for request_data."""
        return {
            "subtitle_lang": self.get_selected_subtitle_lang(),
            "subtitle_is_auto": self.get_selected_subtitle_is_auto(),
            "subtitle_format": self.tab.subtitle_options.combo_subtitle_format.currentData().get("ext") if self.tab.subtitle_options.combo_subtitle_format.currentData() else None,
            "subtitle_output_ext": self.get_selected_subtitle_output_ext(),
            "embed_subtitles": self.tab.subtitle_options.chk_download_with_media["switch"].isChecked(),
            "standardize_srt": self.tab.subtitle_options.chk_standardize_srt["switch"].isChecked(),
            "cut_subtitles": self.tab.subtitle_options.chk_cut_to_fragment["switch"].isChecked(),
        }

    def restore_subtitles_to_ui(self, req: dict):
        if "subtitle_lang" in req:
            lang = req["subtitle_lang"]
            for i in range(self.tab.subtitle_options.combo_subtitle_language.count()):
                item_data = self.tab.subtitle_options.combo_subtitle_language.itemData(i)
                if item_data and item_data.get("lang") == lang:
                    self.tab.subtitle_options.combo_subtitle_language.setCurrentIndex(i)
                    break
                    
        if "embed_subtitles" in req:
            self.tab.subtitle_options.chk_download_with_media["switch"].setChecked(req["embed_subtitles"])
        if "standardize_srt" in req:
            self.tab.subtitle_options.chk_standardize_srt["switch"].setChecked(req["standardize_srt"])
        if "cut_subtitles" in req:
            self.tab.subtitle_options.chk_cut_to_fragment["switch"].setChecked(req["cut_subtitles"])

        if "subtitle_format" in req:
            self.on_subtitle_language_changed()
            fmt = req["subtitle_format"]
            is_auto = req.get("subtitle_is_auto", False)
            output_ext = req.get("subtitle_output_ext")
            for i in range(self.tab.subtitle_options.combo_subtitle_format.count()):
                d = self.tab.subtitle_options.combo_subtitle_format.itemData(i)
                if not d or d.get("ext") != fmt or d.get("auto") != is_auto:
                    continue
                if output_ext and d.get("output_ext", d.get("ext")) != output_ext:
                    continue
                self.tab.subtitle_options.combo_subtitle_format.setCurrentIndex(i)
                break
