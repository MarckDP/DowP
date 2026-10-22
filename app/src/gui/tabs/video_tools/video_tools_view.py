# src/gui/tabs/video_tools/video_tools_view.py
import os
from PySide6.QtWidgets import QMessageBox

from gui.tabs.video_tools.media_workbench import MediaWorkbenchTab
from gui.tabs.video_tools.media_queue_widget import entry_path
from gui.tabs.video_tools.encoding_options_widget import EncodingOptionsWidget
from core.logger.logger_manager import logger
from core.tabs.editing_media.ffprobe_metadata_manager import FFprobeMetadataManager
from core.utils.queue_manager import get_queue_manager, ORIGIN_VIDEO_TOOLS
from core.utils.file_conflict_manager import resolve_conflict, find_available_rename
from core.utils.recode_guard import container_supports_multi_audio, CONTAINER_TO_EXTENSION
from core.tabs.video_tools.alpha_policy import queue_alpha_counts
from core.utils.media_extensions import AUDIO_EXTS as AUDIO_ONLY_EXTENSIONS


class VideoToolsTab(MediaWorkbenchTab):
    """
    Pestaña de Herramientas Multimedia / Recodificador.

    La cola, la vista previa, la salida y el seguimiento de los trabajos viven en
    MediaWorkbenchTab (media_workbench.py). Aquí queda lo propio de Multimedia: el
    panel de opciones con sus subpestañas (Preajustes/Comprimir/Convertir/Edición/
    Avanzado/Herramientas IA), el recorte interactivo y las marcas de agua sobre la
    vista previa, y el armado del lote de recodificación.
    """

    # ------------------------------------------------------------------
    # Ganchos de MediaWorkbenchTab
    # ------------------------------------------------------------------
    def _create_options_widget(self):
        return EncodingOptionsWidget(self)

    def _connect_options_widget(self):
        # Recorte interactivo: siempre activo en Personalizado + Recortar (no hay casilla
        # de encendido). El panel Avanzado activa/desactiva el rectángulo sobre la vista
        # previa según su propia configuración (crop_edit_toggled) y sincroniza en vivo con
        # los campos Ancho/Alto en ambas direcciones: arrastrar el recorte actualiza los
        # campos (crop_rect_changed) y tipear los campos redimensiona el recorte
        # (crop_dimensions_changed).
        self.options_widget.tab_advanced.crop_edit_toggled.connect(self._on_crop_edit_toggled)
        self.options_widget.tab_advanced.crop_dimensions_changed.connect(self._on_crop_dimensions_changed)
        self.preview_widget.crop_rect_changed.connect(self._on_preview_crop_changed)

        # Marcas de agua interactivas: el panel Avanzado empuja el ESTILO (texto/fuente/
        # tamaño/color/opacidad, o archivo/escala/opacidad) hacia la vista previa; la
        # vista previa empuja de vuelta la POSICIÓN (arrastrada a mano) hacia el panel,
        # que la guarda como estado propio — a diferencia del recorte, no hace falta un
        # override por-llamada, get_settings() ya la lee directo (ver conversación:
        # esto también resuelve que "Guardar como preajuste" capture la posición actual).
        self.options_widget.tab_advanced.text_watermark_style_changed.connect(self._on_text_watermark_style_changed)
        self.options_widget.tab_advanced.image_watermark_style_changed.connect(self._on_image_watermark_style_changed)
        self.preview_widget.text_watermark_changed.connect(self._on_text_watermark_position_changed)
        self.preview_widget.image_watermark_changed.connect(self._on_image_watermark_position_changed)

    def _on_source_media(self, meta, filepath, new_file):
        self.options_widget.tab_advanced.set_source_media(meta, filepath)
        self.options_widget.tab_compress.set_source_media(meta, filepath)
        self.options_widget.tab_convert.set_source_media(meta, filepath)
        self.options_widget.tab_editing.set_source_media(meta, filepath)
        self.options_widget.tab_presets.set_source_media(meta, filepath)
        if new_file:
            # preview_widget.load_media ya ocultó el rectángulo (el encuadre elegido no
            # tiene sentido para otro archivo); esto lo vuelve a mostrar de una para el
            # archivo nuevo si el recorte interactivo sigue activo (personalizado +
            # Recortar es config. del panel, no del archivo, así que no se "apaga" solo
            # al cambiar de ítem).
            self.options_widget.tab_advanced.hide_apply_to_all_checkbox()
        # Con la metadata completa (new_file=False) puede llegar recién la resolución
        # real: si el recorte ya está activo, se re-arma con ella.
        self._on_crop_edit_toggled(self.options_widget.tab_advanced.is_crop_active())

    def _on_queue_metadata(self, entries, entries_with_paths):
        self.options_widget.tab_compress.set_queue_entries(entries)
        self.options_widget.tab_convert.set_queue_entries(entries_with_paths)

    def _on_queue_metadata_refreshed(self):
        self._push_queue_alpha_counts()

    # ------------------------------------------------------------------
    # Propio de Multimedia
    # ------------------------------------------------------------------
    def _push_queue_alpha_counts(self):
        """Transparencia en la cola -> los 4 paneles: muestran la casilla aunque el archivo
        seleccionado sea opaco, y avisan si hay archivos con y sin transparencia."""
        counts = queue_alpha_counts(self._queue_entries_with_paths.items())
        for tab in (self.options_widget.tab_compress, self.options_widget.tab_convert,
                    self.options_widget.tab_editing, self.options_widget.tab_advanced):
            tab.set_queue_alpha_counts(*counts)

    def _on_crop_edit_toggled(self, enabled: bool):
        fw, fh = self.options_widget.tab_advanced.get_crop_target_fraction() if enabled else (None, None)
        self.preview_widget.set_crop_editing_enabled(enabled, fw, fh)

    def _on_crop_dimensions_changed(self, width_px: int, height_px: int):
        fw, fh = self.options_widget.tab_advanced.pixels_to_crop_fraction(width_px, height_px)
        if fw and fh:
            self.preview_widget.update_crop_size(fw, fh)

    def _on_preview_crop_changed(self):
        if self.preview_widget.has_custom_crop():
            self.options_widget.tab_advanced.show_apply_to_all_checkbox()
        crop_frac = self.preview_widget.get_crop_rect()
        if crop_frac is not None:
            self.options_widget.tab_advanced.sync_dimensions_from_crop(crop_frac)

    def _on_text_watermark_style_changed(self):
        style = self.options_widget.tab_advanced.get_text_watermark_style()
        self.preview_widget.set_text_watermark(
            style["enabled"], style["text"], style["font_family"], style["weight"],
            style["size_pct"], style["color"], style["opacity"],
        )

    def _on_image_watermark_style_changed(self):
        style = self.options_widget.tab_advanced.get_image_watermark_style()
        self.preview_widget.set_image_watermark(
            style["enabled"], style["image_path"], style["scale_pct"], style["opacity"],
        )

    def _on_text_watermark_position_changed(self):
        pos = self.preview_widget.get_text_watermark_position()
        if pos is not None:
            self.options_widget.tab_advanced.set_text_watermark_position(*pos)
        size_pct = self.preview_widget.get_text_watermark_size_pct()
        if size_pct is not None:
            self.options_widget.tab_advanced.set_text_watermark_size(size_pct)

    def _on_image_watermark_position_changed(self):
        pos = self.preview_widget.get_image_watermark_position()
        if pos is not None:
            self.options_widget.tab_advanced.set_image_watermark_position(*pos)
        size_pct = self.preview_widget.get_image_watermark_size_pct()
        if size_pct is not None:
            self.options_widget.tab_advanced.set_image_watermark_size(size_pct)

    def _on_start_recoding_clicked(self):
        is_valid, reason = self.options_widget.get_current_status()
        if not is_valid:
            QMessageBox.warning(self, self.tr("Configuración no válida"), reason)
            return

        files = self.queue_widget.get_all_filepaths()
        if not files:
            QMessageBox.warning(self, self.tr("Sin archivos"), self.tr("Por favor agrega al menos un archivo a la cola para iniciar la recodificación."))
            return

        out_dir = self.txt_output_dir.text().strip()
        same_path = self.chk_same_path.isChecked()
        
        if not same_path and (not out_dir or not os.path.exists(out_dir)):
            QMessageBox.warning(self, self.tr("Carpeta inválida"), self.tr("Por favor selecciona una carpeta de salida válida."))
            return

        # Preajustes combinables: si la pestaña activa es "Preajustes" y hay un
        # preajuste de Reescalado IA elegido (con o sin uno de Recodificación
        # también), se decide ACÁ, ANTES de pedirle a get_encoding_settings()
        # el dict genérico de RECODE -- ese dict para "Preajustes" viene de
        # PresetsPanel.get_settings(), que ahora es un alias de
        # get_recode_settings() y devolvería {} (vacío) si solo hay un
        # preajuste de Reescalado IA elegido, disparando el aviso de "Sin
        # configuración" de más abajo antes de llegar acá. Ver
        # PresetsPanel.get_upscale_settings()/get_recode_settings().
        if self.options_widget.tabs.currentWidget() is self.options_widget.tab_presets:
            upscale_settings = self.options_widget.tab_presets.get_upscale_settings()
            if upscale_settings is not None and self.options_widget.tab_presets.is_transcription():
                # Transcripción: no produce un video, así que no se encadena. Corre aparte
                # y, si además hay un preajuste de Recodificación, este sigue el flujo de
                # siempre sobre los mismos archivos.
                self._start_upscale_ia_jobs(files, upscale_settings, out_dir, same_path)
                if self.options_widget.tab_presets.get_recode_settings() is None:
                    return
                upscale_settings = None
            if upscale_settings is not None:
                recode_settings = self.options_widget.tab_presets.get_recode_settings()
                if recode_settings is not None:
                    self._start_chained_jobs(files, upscale_settings, recode_settings, out_dir, same_path)
                else:
                    self._start_upscale_ia_jobs(files, upscale_settings, out_dir, same_path)
                return
            # Sin preajuste de Reescalado IA elegido -- sigue el flujo de
            # siempre (solo Recodificación), sin cambios.

        settings = self.options_widget.get_encoding_settings()
        if not settings:
            QMessageBox.warning(self, self.tr("Sin configuración"), self.tr("Selecciona un preajuste o una configuración válida."))
            return

        # Recorte interactivo: si el usuario lo modificó en la vista previa y marcó
        # "Aplicar a todos", se reconstruye 'settings' completo con ese recorte ya
        # incluido (afecta a todo el lote); si no, cada archivo arma el suyo más abajo,
        # y solo el archivo previsualizado recibe el recorte personalizado.
        crop_frac = self.preview_widget.get_crop_rect()
        apply_crop_to_all = bool(settings.get("crop_apply_to_all")) and crop_frac is not None
        if apply_crop_to_all:
            settings = self.options_widget.tab_advanced.get_settings(crop_fraction_override=crop_frac)

        prefix = self.txt_prefix.text() if hasattr(self, "txt_prefix") else ""
        suffix = self.txt_suffix.text() if hasattr(self, "txt_suffix") else ""

        logger.info(f"VideoToolsTab: Iniciando recodificación para {len(files)} archivos. Misma ruta: {same_path}")
        
        qm = get_queue_manager()
        raw_container = settings.get("container", "mp4")
        is_compress_tab = self.options_widget.tabs.currentWidget() is self.options_widget.tab_compress
        is_convert_tab = self.options_widget.tabs.currentWidget() is self.options_widget.tab_convert
        is_editing_tab = self.options_widget.tabs.currentWidget() is self.options_widget.tab_editing
        is_presets_tab = self.options_widget.tabs.currentWidget() is self.options_widget.tab_presets
        # Comprimir y Convertir recalculan por archivo (ver más abajo); ninguna de las dos
        # tiene UI de recorte espacial (crop), a diferencia de Avanzado/Preajustes. Edición
        # también: aunque códec/calidad/resolución son uniformes para todo el lote (los
        # elige el usuario en el panel), la decisión de audio (copiar tal cual vs.
        # recodificar a PCM) depende del códec de audio de CADA archivo de origen, no del
        # que está en preview - ver EditingPanel.get_settings/_build_audio_settings.
        # Preajustes también: un preajuste con container="same" (ver
        # core.utils.default_presets, ej. Normalizar Audio) necesita resolverse contra
        # la extensión de CADA archivo, no solo el de preview - ver
        # PresetsPanel.get_settings.
        needs_per_file_recompute = is_compress_tab or is_convert_tab or is_editing_tab or is_presets_tab
        # Nombres de salida ya asignados a otro archivo de ESTE MISMO lote (ej. video.mp4
        # + video.mov -> mismo out_file): resolve_conflict() solo ve el disco, y el
        # archivo del otro job todavía no existe ahí (ffmpeg lo va a escribir más tarde) -
        # sin este chequeo aparte, dos jobs del mismo lote se pisarían entre sí.
        claimed_out_paths = set()

        for entry_key in files:
            # entry_key identifica la FILA de la cola (con su recorte y su estado);
            # filepath es el archivo real, que puede repetirse entre filas.
            filepath = entry_path(entry_key)
            ext = os.path.splitext(filepath)[1].lower()
            media_type = "audio" if ext in AUDIO_ONLY_EXTENSIONS else "video"
            meta = FFprobeMetadataManager.get_instance().get_metadata_instant(filepath, media_type)
            duration_sec = self._parse_duration_to_seconds(meta.get("duración", "0"))

            file_settings = dict(settings)

            # Comprimir y Convertir necesitan recalcular por archivo, no reusar el
            # `settings` armado una sola vez para el archivo en preview: Comprimir/Rápido
            # calcula el nivel como fracción del bitrate de CADA archivo, Comprimir/Manual
            # + "Tamaño objetivo (MB)"/"Mismo que el original" dependen de la duración/
            # extensión real de cada uno, y Convertir decide copiar-vs-recodificar según
            # el códec de origen de CADA archivo (no el que está en preview). Recalcular
            # aquí es barato (arma un dict chico, sin I/O) y no cambia nada para los modos
            # que sí dan el mismo resultado en todos los archivos.
            if needs_per_file_recompute:
                file_settings = self.options_widget.get_encoding_settings(file_meta=meta, filepath=filepath)

            file_container = file_settings.get("container", raw_container)
            container_ext = CONTAINER_TO_EXTENSION.get(file_container, file_container)
            base_name = os.path.splitext(os.path.basename(filepath))[0]
            out_name = f"{prefix}{base_name}{suffix}.{container_ext}"

            if same_path:
                actual_out_dir = os.path.dirname(filepath)
            else:
                actual_out_dir = out_dir

            out_file = os.path.join(actual_out_dir, out_name)

            # Conflicto de nombre de salida (ver combo "Si existe:"): dos fuentes con el
            # mismo nombre base pero distinto contenedor de origen pueden terminar
            # pidiendo el mismo out_file - se resuelve aquí, por archivo, ANTES de crear el
            # job, reusando core/utils/file_conflict_manager.py (mismo mecanismo que ya
            # usa la pestaña de Descarga, backup reversible incluido para "Sobrescribir").
            conflict_policy = self.combo_conflict_policy.currentData() or "conservar"
            out_file, backup_path = resolve_conflict(out_file, conflict_policy)

            # Colisión dentro del mismo lote (ver claimed_out_paths más arriba) - un
            # archivo ya "ganó" este nombre en una vuelta anterior del loop, aunque
            # todavía no exista en disco.
            while out_file is not None and out_file in claimed_out_paths:
                if conflict_policy == "omitir":
                    out_file = None
                else:
                    # "Sobrescribir" no aplica entre dos jobs del mismo lote (no hay nada
                    # que respaldar todavía, el otro archivo ni se escribió) - se degrada
                    # a auto-renombrar, igual que "Conservar".
                    out_file = find_available_rename(out_file)

            if out_file is None:
                logger.info(f"VideoToolsTab: Omitido por conflicto de nombre: {filepath}")
                self.queue_widget.update_file_status(entry_key, self.tr("Omitido"))
                continue
            claimed_out_paths.add(out_file)

            # Recorte temporal (trim): por archivo, desde el caché (ver _trim_cache) - no
            # depende de cuál esté en el preview justo ahora, cada archivo del lote lleva
            # el suyo (o ninguno, si nunca se tocó).
            cached_trim = self._trim_cache.get(entry_key)
            if cached_trim:
                trim_in_sec, trim_out_sec = cached_trim
                if trim_in_sec > 0.05 or (duration_sec > 0 and trim_out_sec < (duration_sec - 0.05)):
                    file_settings["trim_in_sec"] = trim_in_sec
                    file_settings["trim_out_sec"] = trim_out_sec

            # Selección de pista de audio (medios multipista): por archivo, desde el caché
            # (ver _audio_track_cache) - antes, para archivos que no eran el que estaba en
            # preview, se leía la selección EN VIVO del preview y se le aplicaba a ese otro
            # archivo igual, aunque fuera de otro idioma o ni existiera esa pista ahí.
            streams = meta.get("audio_streams", [])
            job_note = None
            if len(streams) > 1:
                cached_track_sel = self._audio_track_cache.get(entry_key)
                selection = cached_track_sel if cached_track_sel is not None else "all"
                # "all" sin que el usuario haya elegido una pista puntual (cached_track_sel
                # es un int) puede pedirle a ffmpeg algo que el contenedor/códec de salida
                # no soporta (ver container_supports_multi_audio - ej. mp3/wav/flac son de
                # 1 sola pista SIEMPRE, sin importar el códec). En vez de dejar que el
                # trabajo falle a mitad de cola, se cae a la Pista 1 y se avisa - mismo
                # criterio que Convertir ya aplica para video en contenedores de audio
                # (ver advisor.container_accepts_video_for_convert): recortar lo que no
                # entra y avisar, no bloquear el lote entero.
                if selection == "all":
                    video_present = file_settings.get("video_mode") not in (None, "none")
                    video_codec_for_check = file_settings.get("video_codec") if video_present else None
                    audio_codec_for_check = file_settings.get("audio_codec")
                    if not container_supports_multi_audio(file_container, audio_codec_for_check, video_codec_for_check):
                        selection = 0
                        first_track_label = self._describe_first_audio_track(streams)
                        job_note = self.tr("se usó solo {0} — el formato de salida no admite múltiples pistas de audio").format(first_track_label)
                file_settings["audio_track_selection"] = selection

            # El recorte interactivo es exclusivo de Avanzado (Comprimir no tiene UI de
            # recorte, ver compress_panel.py) - si el usuario dejó un recorte dibujado
            # desde una visita anterior a Avanzado pero el lote actual lo está armando
            # Comprimir, no corresponde reinyectar los video_args de Avanzado aquí (son
            # de otro códec/perfil, no los que Comprimir acaba de calcular).
            if entry_key == self.current_preview_file:
                if crop_frac is not None and not apply_crop_to_all and not needs_per_file_recompute:
                    crop_settings = self.options_widget.tab_advanced.get_settings(crop_fraction_override=crop_frac)
                    file_settings["video_args"] = crop_settings["video_args"]

            config = {
                "input_path": filepath,
                "output_path": out_file,
                "settings": file_settings,
                "duration_sec": duration_sec,
                "title": f"Recode: {base_name}",
                # Fila de la cola a la que pertenece este trabajo. Hace falta guardarla
                # porque input_path ya no la identifica: dos filas pueden compartir
                # archivo con recortes distintos, y el estado debe ir a la fila correcta.
                "queue_entry_key": entry_key,
            }
            job_id = qm.add_job(config, "RECODE", origin=ORIGIN_VIDEO_TOOLS)
            self._recode_jobs.add(job_id)
            self._recode_backups[job_id] = backup_path
            if job_note:
                self._recode_job_notes[job_id] = job_note

            # Actualizamos visualmente la cola
            self.queue_widget.update_file_status(entry_key, self.tr("En cola"))
            
        self._set_start_button_running(True)
        self.progress_bar.setProperty("status", "downloading")
        self.progress_bar.style().unpolish(self.progress_bar)
        self.progress_bar.style().polish(self.progress_bar)
        qm.start_queue(ORIGIN_VIDEO_TOOLS)

    def start_tutorial(self):
        from gui.widgets.tutorial_overlay import TutorialOverlay
        steps = [
            {
                "title": self.tr("Lista de Archivos"),
                "desc": self.tr("Arrastra aquí tus archivos de video o audio. Puedes procesar un solo archivo o una lista completa en lote."),
                "widgets": [self.queue_widget]
            },
            {
                "title": self.tr("Vista Previa Interactiva"),
                "desc": self.tr("Reproduce tus videos y visualiza en tiempo real los recortes espaciales o marcas de agua que configures."),
                "widgets": [self.preview_widget]
            },
            {
                "title": self.tr("Recorte de Tiempo (Trim)"),
                "desc": self.tr("Ajusta los marcadores inicial y final en la línea de tiempo para exportar solo un fragmento exacto del video."),
                "widgets": [self.timeline_widget]
            },
            {
                "title": self.tr("Pestañas de Edición"),
                "desc": self.tr("Navega entre estas pestañas para usar preajustes guardados, comprimir videos rápido, convertir formatos o hacer ediciones básicas."),
                "widgets": [self.options_widget],
                "on_enter": lambda: (
                    self.right_panel.open_overlay() if not self.right_panel.is_docked() and not self.right_panel.is_overlay_open() else None,
                    self.options_widget.tabs.setCurrentIndex(0)
                )
            },
            {
                "title": self.tr("Opciones Avanzadas"),
                "desc": self.tr("En Avanzado tienes control profesional: puedes recortar la imagen, incrustar marcas de agua arrastrándolas en la vista previa y mucho más."),
                "widgets": [self.options_widget],
                "on_enter": lambda: (
                    self.right_panel.open_overlay() if not self.right_panel.is_docked() and not self.right_panel.is_overlay_open() else None,
                    self.options_widget.tabs.setCurrentIndex(4)
                )
            },
            {
                "title": self.tr("Exportación y Ejecución"),
                "desc": self.tr("Elige la carpeta de destino, la regla para archivos existentes, y pulsa iniciar. ¡Y lo mejor es que puedes arrastrar el resultado directamente a tu editor de video favorito!"),
                "widgets": [self.output_card]
            }
        ]
        
        main_window = self.window()
        self.tutorial_overlay = TutorialOverlay(main_window, steps)
        self.tutorial_overlay.resize(main_window.size())
        self.tutorial_overlay.show()
