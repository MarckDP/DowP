# src/core/ytdlp_logic/downloader_master.py
from PySide6.QtCore import QCoreApplication, QT_TRANSLATE_NOOP
import os
import sys
import re
import time
import traceback
from core.logger.logger_manager import logger
from core.setup.setup_manager import get_dependency_env
from core.setup.ytdlp_setup import get_ytdlp_path

from core.ytdlp_logic.analyzer import get_base_ydl_opts, YTDLLogger
from core.utils.cleanup_manager import DownloadCancelledError
from core.utils.subtitle_manager import SubtitleProcessor
from core.utils import file_conflict_manager
import glob

class DownloaderMaster:
    """
    Clase maestra encargada de centralizar las descargas de todas las pestañas.
    Gestiona la configuración de yt-dlp, hilos y post-procesamiento.
    """
    # Prefijo del mensaje de éxito cuando el medio se bajó pero un paso opcional del
    # post-proceso falló (ver _cosmetic_pp_failure). Quien lo recibe puede mostrar el
    # aviso que sigue al prefijo.
    POSTPROCESS_WARNING_PREFIX = "POSTPROCESS_WARNING:"

    def __init__(self):
        self.active_downloads = {} # Para futuras colas simultáneas
        # Ver request_pause. No se reinicia en download(): una pausa pedida justo antes
        # de que arranque la siguiente llamada tiene que seguir valiendo.
        self._pause_requested = False

    def request_pause(self):
        """La próxima cancelación es una pausa: la limpieza conserva lo ya bajado
        (.part, fragmentos, streams sin fusionar) para que yt-dlp lo retome al volver a
        lanzar la misma descarga. Se usa junto con el cancellation_event."""
        self._pause_requested = True

    def download(self, request_data, progress_callback=None, cancellation_event=None, conflict_ask_callback=None):
        """
        Ejecuta una descarga basada en el diccionario de datos recibido de la UI.

        conflict_ask_callback: callable(filename: str) -> "overwrite"/"rename"/"cancel",
        usado únicamente cuando request_data["conflict_policy"] == "ask" (modo SOLO de
        Proceso Avanzado). Se inyecta desde la capa de GUI (ver
        gui/tabs/advanced_process/workers.py) para que este módulo no dependa de Qt.
        """
        self.cancellation_event = cancellation_event
        self._pending_backup = None
        # Índices de playlist que SÍ terminaron de descargarse, alimentado por el hook
        # de progreso. Es lo que permite reintentar solo los que fallaron: con
        # ignoreerrors='only_download' yt-dlp se traga el error por ítem y no hay
        # excepción de la que deducirlo (ver _retry_failed_playlist_items).
        self._completed_playlist_indices = set()
        # Rutas que yt-dlp reporta en el hook para ESTA descarga (ver _make_hook y
        # _cleanup_temp_artifacts): la limpieza borra solo lo derivado de ellas.
        self._touched_streams = {}   # ruta del stream -> format_id
        self._touched_tmp = set()    # rutas .part
        # Miniaturas que yt-dlp escribió (ver _on_ytdlp_message). Van aparte porque se
        # escriben ANTES de empezar a bajar: si la descarga falla antes del primer aviso
        # de progreso (ej. un 403), _touched_streams queda vacío y no habría de dónde
        # deducir su nombre.
        self._touched_thumbs = set()
        self._download_started_at = time.time()
        url = request_data.get("url")
        if not url:
            return False, "No URL provided"

        # Miniaturas sueltas: se conservan si el usuario las pidió. La cola de Proceso
        # Avanzado decide eso con su modo de miniaturas en lote y lo manda en
        # _keep_thumbnail_files, porque a yt-dlp le apaga download_thumbnail_file (baja
        # la miniatura por su cuenta, ver QueueWorker._execute_download).
        keep_thumbnails = bool(request_data.get(
            "_keep_thumbnail_files", request_data.get("download_thumbnail_file", False)))
        keep_partials = False

        # Sanitizar el título (replica de sanitize_filename del DowP 1.0)
        if request_data.get("title"):
            request_data["title"] = self._sanitize_filename(request_data["title"])

        # En modo "solo subtítulos" sin "Recortar subtítulo al fragmento" activo, se
        # ignoran los fragmentos seleccionados: debe bajar el subtítulo completo del
        # video, no un recorte por fragmento. El recorte solo aplica si el usuario
        # activó esa opción explícitamente (cut_subtitles).
        if request_data.get("mode") == "subtitle_only" and not request_data.get("cut_subtitles"):
            request_data["selected_fragments"] = []

        # 1. Preparar Opciones (Heredando base del analizador)
        ydl_opts = self._prepare_opts(request_data, progress_callback)
        
        # Detectar modo de fragmentos
        from core.tabs.advanced_process.fragment_logic import FragmentState
        fragments = request_data.get("selected_fragments", [])
        fragment_mode = request_data.get("fragment_mode")
        
        # ¿Necesitamos descargas individuales (Corte Normal o Preciso)?
        # El modo Normal (fragment_mode is None) ahora genera archivos separados.
        individual_download = fragments and (fragment_mode is None or fragment_mode == FragmentState.PRECISE)

        # 3. Preparar entorno y ejecución
        ytdlp_path = get_ytdlp_path()
        if ytdlp_path not in sys.path:
            sys.path.insert(0, ytdlp_path)

        # Inyectar siempre la carpeta de plugins si al menos uno (bgutil o wpc) está
        # presente, para que yt_dlp los registre ambos en su primera ejecución y
        # evitar el bug de caché de módulos al retirarla/reinsertarla según el provider.
        from core.setup.potprovider_setup import get_plugin_dir, check_plugin
        from core.setup.wpc_setup import check_wpc
        plugin_dir = get_plugin_dir()
        if (check_plugin() or check_wpc()) and plugin_dir not in sys.path:
            sys.path.insert(0, plugin_dir)
            logger.debug(f"DownloaderMaster: plugin dir inyectado en sys.path -> {plugin_dir}")

        from core.ytdlp_logic.resilient_downloader import is_youtube_access_error, make_fallback_ydl_opts

        try:
            import yt_dlp
            env = get_dependency_env()
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = env["PATH"]

            if individual_download:
                logger.info(f"DownloaderMaster: Iniciando descargas individuales para {len(fragments)} fragmentos.")
                for i, frag in enumerate(fragments):
                    if cancellation_event and cancellation_event.is_set():
                        raise DownloadCancelledError(QCoreApplication.translate("DownloaderMaster", "Descarga cancelada por el usuario"))

                    # Crear solicitud específica para este fragmento
                    frag_data = request_data.copy()
                    frag_data["selected_fragments"] = [frag]

                    if progress_callback:
                        progress_callback({
                            "status": "fragment_progress",
                            "phase": "downloading",
                            "fragment_index": i + 1,
                            "fragment_count": len(fragments),
                        })

                    logger.debug(f"DownloaderMaster: Preparando fragmento {i+1} con data: "
                                 f"v_id={frag_data.get('video_format_id')}, a_id={frag_data.get('audio_format_id')}")
                    
                    # Opciones para este fragmento (incluye sufijo y rango)
                    ydl_opts = self._prepare_opts(frag_data, progress_callback)
                    
                    logger.info(f"DownloaderMaster: Descargando fragmento {i+1}/{len(fragments)}: "
                                f"{frag[2] if len(frag)>2 else i} | Formato final: {ydl_opts.get('format')}")
                    
                    # Log de validación de itags en el outtmpl si es posible
                    logger.debug(f"DownloaderMaster: ydl_opts['outtmpl'] = {ydl_opts.get('outtmpl')}")
                    
                    gpu_encoder_used = self._last_gpu_encoder_used
                    try:
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            ydl.download([url])
                    except Exception as frag_err:
                        if is_youtube_access_error(url, frag_err):
                            logger.warning(
                                f"DownloaderMaster: YouTube/FFmpeg bloqueó el fragmento ({frag_err}). "
                                f"Reintentando fragmento con cliente alternativo (web_embedded)..."
                            )
                            fallback_opts = make_fallback_ydl_opts(ydl_opts)
                            with yt_dlp.YoutubeDL(fallback_opts) as ydl_fallback:
                                ydl_fallback.download([url])
                        elif gpu_encoder_used:
                            # El encoder de GPU (NVENC/QSV) puede fallar en ciertos casos -
                            # resoluciones muy bajas, drivers desactualizados, límite de
                            # sesiones NVENC concurrentes, etc. (reproducido con un video de
                            # ~240p: "Preprocessing: Conversion failed!") - en vez de perder
                            # todo el corte, reintentar UNA vez forzando CPU (libx264) para
                            # ESTE fragmento puntual. No desactiva la aceleración por GPU en
                            # general: el resto de fragmentos/descargas la siguen intentando
                            # primero, como corresponde.
                            logger.warning(
                                f"DownloaderMaster: El encoder de GPU ({gpu_encoder_used}) falló en el "
                                f"corte preciso del fragmento {i+1} ({frag_err}). Reintentando con CPU (libx264)..."
                            )
                            cpu_opts = self._prepare_opts(frag_data, progress_callback, force_cpu_encoder=True)
                            with yt_dlp.YoutubeDL(cpu_opts) as ydl_cpu:
                                ydl_cpu.download([url])
                        else:
                            raise frag_err
                        
                    # Recortar subtítulos si es necesario
                    if request_data.get("cut_subtitles") and frag_data.get("subtitle_lang"):
                        self._handle_subtitle_cuts_for_fragment(ydl_opts.get('outtmpl'), frag, request_data)
                    elif request_data.get("standardize_srt"):
                        # Estandarizar aunque no haya recorte
                        self._handle_subtitle_standardization(ydl_opts.get('outtmpl'), request_data)

                self._consolidate_fragment_thumbnails(request_data, fragments)

                return True, "Download finished successfully"
            
            else:
                # Caso estándar: Descarga única (Completa, o para corte local posterior)
                # Modo Rápido no fija un título propio (deja que yt-dlp use %(title)s
                # del sitio), así que sin un título no hay ruta que comprobar. Se
                # resuelve primero con una extracción de metadata liviana para que el
                # chequeo de conflicto también funcione ahí.
                if (not request_data.get("title") and not request_data.get("is_playlist")
                        and request_data.get("mode", "video+audio") in ("video+audio", "video_only", "audio_only")):
                    resolved_title = self._resolve_title_from_metadata(request_data, url)
                    if resolved_title:
                        request_data["title"] = resolved_title

                if not self._resolve_output_conflict(request_data, conflict_ask_callback):
                    return False, "SKIPPED_CONFLICT"

                ydl_opts = self._prepare_opts(request_data, progress_callback)
                
                # Log del comando CLI equivalente
                cli_command = self._get_cli_command(url, ydl_opts, request_data)
                logger.info(f"CLI Command: {cli_command}")

                # Detectar si requiere cortes locales tras la descarga
                needs_local_cut = fragments and fragment_mode in (
                    FragmentState.DOWNLOAD_THEN_CUT, FragmentState.KEEP_FULL
                )

                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                except Exception as dl_err:
                    if is_youtube_access_error(url, dl_err):
                        logger.warning(
                            f"DownloaderMaster: YouTube bloqueó el intento inicial ({dl_err}). "
                            f"Reintentando descarga con cliente alternativo (web_embedded)..."
                        )
                        fallback_opts = make_fallback_ydl_opts(ydl_opts)
                        with yt_dlp.YoutubeDL(fallback_opts) as ydl_fallback:
                            info = ydl_fallback.extract_info(url, download=True)
                    else:
                        raise dl_err

                # Bug preexistente: este bloque vivía indentado DENTRO del except de
                # arriba, así que solo corría cuando el primer intento fallaba Y el
                # reintento con cliente alternativo tenía éxito - en el camino normal
                # (primer intento exitoso, el caso común) nunca se ejecutaba: ni el
                # corte local de fragmentos (needs_local_cut/_handle_local_cuts, los
                # modos "Descargar para cortar"/"Conservar completo") ni el
                # procesamiento de subtítulos corrían jamás. Se saca del except para
                # que corra siempre que 'info' haya quedado definido con éxito (ver
                # conversación).
                if ydl_opts.get('skip_download') and progress_callback:
                    if 'entries' in info:
                        for entry in info['entries']:
                            if entry:
                                filename = ydl.prepare_filename(entry)
                                progress_callback({'status': 'finished', 'filename': filename, 'info_dict': entry})
                    else:
                        filename = ydl.prepare_filename(info)
                        progress_callback({'status': 'finished', 'filename': filename, 'info_dict': info})

                if needs_local_cut:
                    filename = ydl.prepare_filename(info)
                    self._handle_local_cuts(
                        filename, fragments,
                        keep_original=(fragment_mode == FragmentState.KEEP_FULL),
                        progress_callback=progress_callback
                    )

                    if request_data.get("cut_subtitles") and request_data.get("subtitle_lang"):
                        self._handle_subtitle_cuts_local(filename, fragments, request_data.get("subtitle_lang"), request_data)

                # Procesamiento de Subtítulos (Estandarización y Recorte)
                if request_data.get("subtitle_lang"):
                    if request_data.get("mode") == "subtitle_only":
                        # Maneja tanto estandarización como recorte para solo subtítulos
                        self._handle_subtitle_processing_only_sub(request_data, fragments)
                    elif not needs_local_cut and request_data.get("standardize_srt"):
                        # Descarga de video normal sin recorte pero con estandarización
                        filename = ydl.prepare_filename(info)
                        self._handle_subtitle_standardization(filename, request_data)

                file_conflict_manager.commit_backup(self._pending_backup)

                # Con ignoreerrors='only_download' (ver _prepare_opts), una playlist
                # con ítems fallidos igual termina "exitosa" a nivel de yt-dlp — mejor
                # esfuerzo para avisar cuántos de verdad se descargaron. Los ítems
                # fallidos suelen quedar como None/incompletos en 'entries'; si la
                # estructura no da para contarlos con confianza, no se rompe el
                # resultado, solo se pierde el detalle del resumen.
                if request_data.get('is_playlist') and isinstance(info, dict) and 'entries' in info:
                    try:
                        # Antes de resumir, recuperar lo que YouTube bloqueó con 403: sin
                        # esto la playlist entera se quedaba en cero mientras la misma
                        # descarga suelta sí funcionaba.
                        self._retry_failed_playlist_items(url, ydl_opts, info, yt_dlp)

                        requested = self._requested_playlist_items(ydl_opts, info)
                        total_entries = len(requested)
                        # Se cuenta contra lo que el hook vio TERMINAR, no contra las
                        # entradas no nulas: con ignoreerrors='only_download' un ítem que
                        # falló al descargar conserva su dict de metadatos, así que
                        # contarlo como bueno daba "9 de 9 completados" con cero archivos.
                        ok_entries = sum(1 for i in requested if i in self._completed_playlist_indices)
                        failed_entries = total_entries - ok_entries
                        if total_entries and failed_entries:
                            return True, f"{ok_entries} de {total_entries} completados, {failed_entries} con error"
                    except DownloadCancelledError:
                        raise
                    except Exception as summary_err:
                        logger.debug(f"DownloaderMaster: No se pudo armar el resumen de playlist: {summary_err}")

                return True, "Download finished successfully"

        except DownloadCancelledError as e:
            keep_thumbnails = False
            keep_partials = self._pause_requested
            file_conflict_manager.rollback_backup(self._pending_backup)
            return False, str(e)
        except Exception as e:
            err_msg = str(e)
            # Con fragmentos no: la excepción corta el bucle de fragmentos (o el corte
            # local posterior), así que declarar éxito dejaría la tarea a medias.
            warning = None if fragments else self._cosmetic_pp_failure(err_msg)
            if warning:
                logger.warning(f"DownloaderMaster: El medio se descargó, pero falló un paso opcional: {err_msg}")
                file_conflict_manager.commit_backup(self._pending_backup)
                return True, f"{self.POSTPROCESS_WARNING_PREFIX}{warning}"
            keep_thumbnails = False
            logger.error(f"Error en DownloaderMaster: {err_msg}\n{traceback.format_exc()}")
            file_conflict_manager.rollback_backup(self._pending_backup)
            return False, err_msg
        finally:
            os.environ["PATH"] = old_path
            # En el finally y no dentro del except: ahí la excepción en curso todavía
            # retiene los frames de yt-dlp (y con ellos el .part abierto), y Windows no
            # deja borrar un archivo abierto. Aquí ya se soltó todo -- incluidos los
            # hilos de fragmentos concurrentes, que yt-dlp espera al salir.
            self._cleanup_temp_artifacts(keep_thumbnails, keep_partials)

    def _resolve_title_from_metadata(self, request_data, url):
        """
        Resuelve el título real de la URL con una extracción de metadata liviana
        (skip_download=True, sin hooks de progreso) para poder predecir la ruta de
        salida y chequear conflictos ANTES de descargar. Solo se usa cuando
        request_data no trae un título propio (caso de Modo Rápido).

        Si la extracción falla por cualquier motivo, retorna None: el llamador debe
        seguir sin título, lo que hace que _resolve_output_conflict no revise nada y
        yt-dlp decida por su cuenta (mismo comportamiento previo a esta función).
        """
        try:
            import yt_dlp
            probe_opts = self._prepare_opts(request_data, None)
            probe_opts['skip_download'] = True
            probe_opts['quiet'] = True
            probe_opts.pop('progress_hooks', None)
            # Solo se quiere el título: nada de escribir en disco. skip_download no
            # alcanza -- con la URL de una playlist, yt-dlp escribía igual la miniatura de
            # la playlist en la carpeta de salida y quedaba de basura.
            probe_opts.update({
                'writethumbnail': False,
                'writesubtitles': False,
                'writeautomaticsub': False,
                'writeinfojson': False,
                'postprocessors': [],
            })
            with yt_dlp.YoutubeDL(probe_opts) as probe:
                info = probe.extract_info(url, download=False)
            title = info.get('title') if info else None
            return self._sanitize_filename(title) if title else None
        except Exception as e:
            logger.warning(
                f"DownloaderMaster: No se pudo resolver el título por adelantado para el "
                f"chequeo de conflicto (se continuará sin chequear): {e}"
            )
            return None

    def _resolve_output_conflict(self, request_data, conflict_ask_callback):
        """
        Comprueba si el archivo de salida principal ya existe y resuelve el conflicto
        según request_data["conflict_policy"]:
          - "sobrescribir" / "conservar" / "omitir": aplicado en silencio (Modo Rápido,
            Proceso Avanzado en modo LOTES).
          - "ask": dispara conflict_ask_callback(filename) -> "overwrite"/"rename"/"cancel"
            (Proceso Avanzado en modo SOLO). El callback lo inyecta la capa de GUI para
            que este módulo no dependa de Qt.

        Efectos secundarios sobre request_data si hay conflicto:
          - Puede reescribir request_data["title"] (política "conservar"/"rename").
          - Fija request_data["merge_output_format"] en modo "video+audio", para que
            yt-dlp respete la extensión predicha en vez de decidir el contenedor por
            su cuenta (puede caer a .mkv si los streams son incompatibles para .mp4).

        Returns:
            True si se debe continuar con la descarga, False si se debe omitir en
            silencio (política "omitir" con conflicto real: no es un error).

        Raises:
            DownloadCancelledError: si el usuario cancela en el diálogo modal.
        """
        self._pending_backup = None

        mode = request_data.get("mode", "video+audio")
        if mode not in ("video+audio", "video_only", "audio_only"):
            return True

        output_path = request_data.get("output_path")
        title = request_data.get("title")
        if not output_path or not title:
            return True

        predicted_ext = file_conflict_manager.predict_final_extension(
            request_data.get("video_ext"),
            request_data.get("audio_ext"),
            mode,
            bool(request_data.get("video_is_combined")),
        )
        desired_path = os.path.join(output_path, f"{title}{predicted_ext}")

        policy = request_data.get("conflict_policy", "conservar")

        if policy == "ask":
            if not os.path.exists(desired_path):
                return True
            if conflict_ask_callback is None:
                logger.warning(
                    "DownloaderMaster: conflict_policy='ask' sin conflict_ask_callback disponible, "
                    "se continúa sin preguntar."
                )
                return True
            choice = conflict_ask_callback(os.path.basename(desired_path))
            if choice == "cancel":
                raise DownloadCancelledError(QCoreApplication.translate("DownloaderMaster", "Descarga cancelada por el usuario en conflicto de archivo."))
            policy = "sobrescribir" if choice == "overwrite" else "conservar"

        final_path, backup_path = file_conflict_manager.resolve_conflict(desired_path, policy)

        if final_path is None:
            # Política "omitir" con conflicto real: no es un error, simplemente no se descarga.
            return False

        self._pending_backup = backup_path
        request_data["title"] = os.path.splitext(os.path.basename(final_path))[0]

        if mode == "video+audio":
            request_data["merge_output_format"] = predicted_ext.lstrip(".")

        return True

    def _prepare_opts(self, data, progress_callback, force_cpu_encoder=False):
        """
        Traduce los datos de la UI a un diccionario ydl_opts heredando de la base.

        force_cpu_encoder=True fuerza el corte preciso a libx264 (CPU) sin intentar
        ningún encoder de GPU - lo usa download() para reintentar un fragmento puntual
        cuyo primer intento con GPU falló (ver ese método), sin tocar la detección de
        hardware para el resto de descargas.

        self._last_gpu_encoder_used queda en el encoder de GPU efectivamente inyectado
        (o None si se usó CPU) - el llamador lo consulta para decidir si vale la pena
        reintentar con CPU ante un fallo.
        """
        self._last_gpu_encoder_used = None

        # Obtener opciones base (cookies, impersonate, etc.)
        ydl_opts = get_base_ydl_opts()
        ydl_opts['logger'] = YTDLLogger(message_callback=self._on_ytdlp_message)
        
        output_path = data.get("output_path", os.getcwd())
        custom_title = data.get("title")
        
        # Si el usuario puso un título, lo usamos. Si no, dejamos que yt-dlp use el original.
        if custom_title:
            filename_tpl = os.path.join(output_path, f"{custom_title}%(playlist_autonumber& #|)s%(playlist_autonumber|)s.%(ext)s")
        else:
            filename_tpl = os.path.join(output_path, "%(title)s%(playlist_autonumber& #|)s%(playlist_autonumber|)s.%(ext)s")
        
        # Actualizar con opciones de descarga específicas
        is_playlist = data.get('is_playlist', False)
        url = data.get("url", "")
        ydl_opts.update({
            'outtmpl': filename_tpl,
            'progress_hooks': [self._make_hook(progress_callback)],
            'noplaylist': not is_playlist,
            'quiet': False,
            'noprogress': True,
            'concurrent_fragment_downloads': 5,
            'fragment_retries': 2,
            'retries': 2,
            'restrictfilenames': True,
            'downloader': 'native',
        })

        # Fijar el contenedor final si _resolve_output_conflict ya predijo uno (evita
        # que yt-dlp decida por su cuenta y caiga a .mkv si los streams son
        # incompatibles para .mp4, lo que invalidaría el chequeo de conflicto previo).
        if data.get("merge_output_format"):
            ydl_opts['merge_output_format'] = data["merge_output_format"]

        # Bloquear rígidamente la extracción de más de 1 item si no es una playlist autorizada
        if not is_playlist:
            ydl_opts['playlist_items'] = '1'
        else:
            if data.get("playlist_items"):
                ydl_opts['playlist_items'] = data.get("playlist_items")
                # Solo cuando de verdad se pide un RANGO de varios ítems en una
                # misma llamada (Modo Rápido descargando una playlist completa)
                # tiene sentido tolerar errores por ítem. No usar esto como
                # criterio único basado en is_playlist: LOTES marca is_playlist=True
                # también en sus descargas de un solo video por ítem
                # (_execute_playlist en queue_manager.py, una URL puntual por
                # llamada) — ahí 'ignoreerrors' silenciaría errores reales de
                # descarga (ej. 403) impidiendo que el reintento con cliente
                # alternativo (is_youtube_access_error) llegue a dispararse.
                ydl_opts['ignoreerrors'] = 'only_download'

        # --- FRAGMENTOS / RECORTES ---
        fragments = data.get("selected_fragments", [])
        fragment_mode = data.get("fragment_mode")
        
        logger.info(f"DownloaderMaster: Fragmentos recibidos: {len(fragments)} | Modo: {fragment_mode}")
        
        if fragments:
            from core.tabs.advanced_process.fragment_logic import FragmentState
            
            # Si solo hay un fragmento (procedente del bucle de descargas individuales o único)
            # Aplicamos el sufijo al nombre del archivo y configuramos el rango
            if len(fragments) == 1:
                frag = fragments[0]
                suffix = frag[2] if len(frag) > 2 else "fragment"
                
                # Re-construir outtmpl con el sufijo
                if custom_title:
                    filename_tpl = os.path.join(output_path, f"{custom_title}_{suffix}.%(ext)s")
                else:
                    filename_tpl = os.path.join(output_path, f"%(title)s_{suffix}.%(ext)s")
                ydl_opts['outtmpl'] = filename_tpl

                # Solo aplicar rangos si no estamos en modo "Descargar completo"
                if fragment_mode not in (FragmentState.DOWNLOAD_THEN_CUT, FragmentState.KEEP_FULL):
                    try:
                        from yt_dlp.utils import download_range_func
                        ranges = [(frag[0] / 1000.0, frag[1] / 1000.0)]
                        ydl_opts['download_ranges'] = download_range_func(None, ranges)
                        
                        if fragment_mode == FragmentState.PRECISE:
                            ydl_opts['force_keyframes_at_cuts'] = True
                            try:
                                pref_enc = None
                                if not force_cpu_encoder:
                                    from core.utils.hardware_detector import detect_hardware
                                    hw_info = detect_hardware()
                                    pref_enc = hw_info.get("preferred_encoder")
                                if pref_enc and pref_enc != "libx264":
                                    gpu_args = ["-c:v", pref_enc]
                                    if pref_enc == "h264_nvenc":
                                        gpu_args.extend(["-preset", "p4"])
                                    elif pref_enc == "h264_qsv":
                                        gpu_args.extend(["-preset", "veryfast"])

                                    # 1. Inyectar en descargador external (FFmpegFD usado por download_ranges)
                                    ext_args = ydl_opts.get("external_downloader_args", {})
                                    if isinstance(ext_args, dict):
                                        ext_args["ffmpeg"] = list(gpu_args)
                                    else:
                                        ext_args = {"ffmpeg": list(gpu_args)}
                                    ydl_opts["external_downloader_args"] = ext_args

                                    # 2. Inyectar en post-procesadores
                                    post_args = ydl_opts.get("postprocessor_args", {})
                                    if isinstance(post_args, dict):
                                        post_args["ffmpeg"] = list(gpu_args)
                                    else:
                                        post_args = {"ffmpeg": list(gpu_args)}
                                    ydl_opts["postprocessor_args"] = post_args

                                    self._last_gpu_encoder_used = pref_enc
                                    logger.info(f"DownloaderMaster: Corte Preciso acelerado por GPU ({pref_enc}): {gpu_args}")
                                elif force_cpu_encoder:
                                    logger.info(f"DownloaderMaster: Fragmento INDIVIDUAL PRECISO (CPU libx264, reintento tras fallo de GPU): {ranges}")
                                else:
                                    logger.info(f"DownloaderMaster: Fragmento INDIVIDUAL PRECISO (CPU libx264): {ranges}")
                            except Exception as hw_err:
                                logger.warning(f"DownloaderMaster: No se pudo inyectar GPU encoder: {hw_err}")
                        else:
                            logger.info(f"DownloaderMaster: Fragmento INDIVIDUAL NORMAL: {ranges} | Sufijo: {suffix}")
                    except Exception as e:
                        logger.error(f"DownloaderMaster: Error configurando rango individual: {e}")
            
            elif fragment_mode == FragmentState.PRECISE:
                try:
                    from yt_dlp.utils import download_range_func
                    ranges = []
                    for start_ms, end_ms, *_ in fragments:
                        ranges.append((start_ms / 1000.0, end_ms / 1000.0))
                    ydl_opts['download_ranges'] = download_range_func(None, ranges)
                    ydl_opts['force_keyframes_at_cuts'] = True
                    try:
                        pref_enc = None
                        if not force_cpu_encoder:
                            from core.utils.hardware_detector import detect_hardware
                            hw_info = detect_hardware()
                            pref_enc = hw_info.get("preferred_encoder")
                        if pref_enc and pref_enc != "libx264":
                            gpu_args = ["-c:v", pref_enc]
                            ydl_opts["external_downloader_args"] = {"ffmpeg": list(gpu_args)}
                            ydl_opts["postprocessor_args"] = {"ffmpeg": list(gpu_args)}
                            self._last_gpu_encoder_used = pref_enc
                    except Exception:
                        pass
                    logger.info(f"DownloaderMaster: Unión de {len(fragments)} fragmentos (Modo PRECISE forzado)")
                except Exception as e:
                    logger.error(f"DownloaderMaster: Error en unión PRECISE: {e}")
            
            elif fragment_mode in (FragmentState.DOWNLOAD_THEN_CUT, FragmentState.KEEP_FULL):
                # En estos modos, descargamos el completo y cortamos después con ffmpeg
                logger.info(f"DownloaderMaster: Modo {fragment_mode}. Descargando completo para cortes locales con FFmpeg.")
            
            # Asegurar que yt-dlp use el descargador nativo para rangos si no se especifica otro
            if 'download_ranges' in ydl_opts:
                ydl_opts.setdefault('downloader', 'native')

        # Formato (Calidades seleccionadas)
        v_id = data.get("video_format_id")
        a_id = data.get("audio_format_id")
        v_lang = data.get("video_lang")
        a_lang = data.get("audio_lang")
        v_is_combined = data.get("video_is_combined")
        v_is_multi = data.get("video_is_multi")
        a_has_video = data.get("audio_has_video")
        mode = data.get("mode", "video+audio")
        format_selector = data.get("format_selector")

        # Log de lo que recibimos para el formato
        logger.debug(f"DownloaderMaster: _prepare_opts recibio IDs -> v:{v_id}, a:{a_id}, mode:{mode}, format_selector:{bool(format_selector)}")
        
        if format_selector:
            ydl_opts['format'] = format_selector
        elif mode == "video+audio":
            # 1. Caso Multi-idioma combinado (Legacy Wisdom: la selección de audio ES el formato completo)
            if v_is_multi and a_has_video and a_id:
                ydl_opts['format'] = a_id
            
            # 2. Caso Video Combinado Estándar (sin audio separado o el mismo)
            elif v_is_combined and (not a_id or v_id == a_id):
                ydl_opts['format'] = v_id
            
            # 3. Caso DASH o combinación explícita de video y audio diferente
            elif v_id and a_id:
                v_part = v_id
                if v_is_combined: v_part += "[vcodec!=none]"
                a_part = a_id
                ydl_opts['format'] = f"{v_part}+{a_part}"
                
            elif v_id:
                ydl_opts['format'] = v_id
            elif a_id:
                ydl_opts['format'] = a_id
            else:
                ydl_opts['format'] = 'bestvideo+bestaudio/best'

        elif mode == "video_only" and v_id:
            ydl_opts['format'] = v_id
            
        elif mode == "audio_only" and a_id:
            ydl_opts['format'] = a_id
        else:
            ydl_opts['format'] = 'bestvideo+bestaudio/best'

        # Fallback de formato para listas de reproducción (como Twitter Multi-media)
        # Evita que falle en el 2do video si no tiene el formato exacto seleccionado
        if data.get('is_playlist') and ydl_opts.get('format') != 'bestvideo+bestaudio/best':
            ydl_opts['format'] = f"{ydl_opts['format']}/bestvideo+bestaudio/best"

        # Límite de velocidad: ajuste global (Ajustes > Descargas), leído al empezar cada
        # descarga -- así un cambio también alcanza a lo que ya estaba en la cola.
        from core.utils.config_manager import get_config
        limit_mbps = get_config().get("speed_limit_mbps", 0) or 0
        if limit_mbps > 0:
            ydl_opts['ratelimit'] = float(limit_mbps) * 1024 * 1024  # bytes/s

        # Post-procesadores (Metadata, Subs, etc)
        ydl_opts['postprocessors'] = []
        
        # --- LÓGICA DE MODOS PARA MEDIOS COMBINADOS/MULTI-IDIOMA ---
        if mode == "audio_only" and (a_has_video or data.get("force_audio_extract")):
            # Si pedimos solo audio pero la fuente es un flujo que contiene video (ej. Multi-idioma o YouTube Low-res)
            # o si es una playlist forzando la extracción de audio post-descarga
            pref_codec = data.get("audio_ext") or 'best'
            if isinstance(pref_codec, str):
                pref_codec = pref_codec.lower().strip()
                if pref_codec.startswith('.'):
                    pref_codec = pref_codec[1:]
                
                # Mapear contenedores/extensiones de video no soportados a codecs de audio válidos
                codec_mapping = {
                    'mp4': 'm4a',
                    'webm': 'opus',
                    'mkv': 'm4a',
                    'avi': 'mp3',
                    'mov': 'm4a',
                }
                
                valid_audio_codecs = ('mp3', 'aac', 'm4a', 'opus', 'vorbis', 'flac', 'alac', 'wav', 'best')
                if pref_codec not in valid_audio_codecs:
                    pref_codec = codec_mapping.get(pref_codec, 'best')
            else:
                pref_codec = 'best'

            ydl_opts['postprocessors'].append({
                'key': 'FFmpegExtractAudio',
                'preferredcodec': pref_codec, 
                'preferredquality': 'best',
            })
            logger.info(f"DownloaderMaster: Configurando extracción de audio para medio combinado o playlist. Codec: {pref_codec}")
            
        elif mode == "video_only" and v_is_combined:
            # Si pedimos solo video pero el formato seleccionado tiene audio integrado
            # Usamos postprocessor_args para pasarle '-an' (audio none) a ffmpeg
            if 'postprocessor_args' not in ydl_opts:
                ydl_opts['postprocessor_args'] = {}
            
            # Aseguramos que ffmpeg descarte el audio en cualquier fase (merger o fixup)
            if 'ffmpeg' not in ydl_opts['postprocessor_args']:
                ydl_opts['postprocessor_args']['ffmpeg'] = []
            
            if '-an' not in ydl_opts['postprocessor_args']['ffmpeg']:
                ydl_opts['postprocessor_args']['ffmpeg'].append('-an')
            
            # FORZAMOS un post-procesador que llame a ffmpeg (ej. Metadata)
            # si no hay ninguno, ya que de lo contrario yt-dlp podría saltarse la fase de post-procesamiento
            # si el archivo ya está en el contenedor final.
            has_ffmpeg_pp = any(pp.get('key').startswith('FFmpeg') for pp in ydl_opts['postprocessors'])
            if not has_ffmpeg_pp:
                ydl_opts['postprocessors'].append({'key': 'FFmpegMetadata', 'add_metadata': True})
                logger.info("DownloaderMaster: Forzando FFmpegMetadata para asegurar el despojo de audio")
            
            logger.info("DownloaderMaster: Configurando descarte de audio (-an) para medio combinado")

        if data.get("embed_metadata"):
            ydl_opts['postprocessors'].append({'key': 'FFmpegMetadata', 'add_metadata': True})
            logger.info("DownloaderMaster: Configurando incrustación de metadatos")

        # Otras opciones de post-procesamiento
        if data.get("download_thumbnail_file") or data.get("embed_thumbnail"):
            ydl_opts['writethumbnail'] = True
            
            # Solo añadir el convertidor si el usuario quiere el ARCHIVO físico separado.
            # Según el usuario, esta opción "funciona bien" tal cual estaba.
            if data.get("download_thumbnail_file"):
                ydl_opts['postprocessors'].append({
                    'key': 'FFmpegThumbnailsConvertor',
                    'format': 'jpg',
                    'when': 'before_dl'
                })
                logger.info("DownloaderMaster: Configurando descarga de miniatura (Archivo JPG)")

            # Para la incrustación, convertimos a JPG para máxima compatibilidad con todos los contenedores (m4a, mp3, mp4, etc).
            if data.get("embed_thumbnail"):
                # Filtrar por compatibilidad de contenedor (yt-dlp arroja error en webm, avi, etc)
                supported_exts = ('mp3', 'mkv', 'mka', 'ogg', 'opus', 'flac', 'm4a', 'mp4', 'm4v', 'mov')
                
                # Determinar extensión final probable
                mode = data.get("mode")
                if mode == "audio_only":
                    final_ext = data.get("audio_ext")
                elif mode == "video_only":
                    final_ext = data.get("video_ext")
                else:
                    # En video+audio, yt-dlp suele usar mkv si los streams son incompatibles para mp4
                    # pero si el usuario seleccionó formatos específicos, usamos el del video.
                    final_ext = data.get("video_ext")

                if final_ext is None or final_ext.lower() in supported_exts:
                    # 1. Convertir a JPG primero para que sea universalmente aceptado (especialmente por m4a/mp3)
                    ydl_opts['postprocessors'].append({
                        'key': 'FFmpegThumbnailsConvertor',
                        'format': 'jpg',
                        'when': 'before_dl'
                    })
                    # 2. Incrustar la imagen convertida
                    ydl_opts['postprocessors'].append({
                        'key': 'EmbedThumbnail',
                        'already_have_thumbnail': data.get("download_thumbnail_file", False)
                    })
                    logger.info("DownloaderMaster: Configurando incrustación de carátula (convertida a JPG)")
                else:
                    logger.warning(f"DownloaderMaster: Incrustación saltada por contenedor incompatible ({final_ext})")

        # SponsorBlock (Solo si no hay fragmentos, para no romper la sincronía de tiempos)
        if data.get("remove_sponsors") and not fragments:
            ydl_opts['postprocessors'].append({
                'key': 'SponsorBlock',
                'categories': ['sponsor', 'intro', 'outro', 'selfpromo', 'preview', 'filler', 'interaction', 'music_offtopic'],
            })
            logger.info("DownloaderMaster: Configurando SponsorBlock (Eliminar sponsors)")
        elif data.get("remove_sponsors") and fragments:
            logger.info("DownloaderMaster: SponsorBlock desactivado automáticamente por modo fragmentos")

        # --- SUBTÍTULOS ---
        sub_lang = data.get("subtitle_lang")
        is_fragment_download = 'download_ranges' in ydl_opts
        
        # El switch 'embed_subtitles' actúa como control maestro para la descarga de subs con video
        should_download_subs = (mode == "subtitle_only") or data.get("embed_subtitles")
        
        if sub_lang and should_download_subs:
            sub_format = data.get("subtitle_format")
            subtitle_is_auto = data.get("subtitle_is_auto", False)
            ydl_opts.update({
                'writesubtitles': not subtitle_is_auto,
                'subtitleslangs': [sub_lang],
                'writeautomaticsub': subtitle_is_auto,
            })
            
            if sub_format:
                ydl_opts['subtitlesformat'] = sub_format
                logger.debug(f"DownloaderMaster: Forzando formato de subtítulo: {sub_format}")
            
            # Conversión a SRT: usar la opción nativa de yt-dlp (más robusta que el postprocessor)
            # Esto es equivalente a lo que hacía el DowP original con convertsubtitles='srt'
            # FORZAMOS si el usuario quiere recortar, ya que FFmpeg requiere SRT/VTT estándar para precisión.
            if data.get("standardize_srt") or data.get("cut_subtitles"):
                ydl_opts['convertsubtitles'] = 'srt'
                logger.debug("DownloaderMaster: Forzando conversión a SRT para permitir el procesamiento")

            # PERSISTENCIA: DowP conserva siempre el archivo de subtítulo lateral.
            ydl_opts['keepsubs'] = True
            
            # PARCHE CRÍTICO: Si queremos conservar los subs, yt-dlp a veces ignora 'keepsubs'
            # si 'EmbedSubtitle' está activo. Forzamos 'keepvideo' (que es el flag -k)
            # solo en descargas normales (sin fragmentos) para asegurar que nada se borre.
            if not is_fragment_download:
                ydl_opts['keepvideo'] = True
                logger.debug("DownloaderMaster: keepsubs=True y keepvideo=True (Persistencia forzada para descarga completa)")
            else:
                logger.debug("DownloaderMaster: keepsubs=True (Modo fragmentos: keepvideo desactivado para evitar conflictos)")
            
            # El modo recorte REQUIERE keepsubs=True para poder procesar el archivo después de yt-dlp
            if data.get("cut_subtitles"):
                ydl_opts['keepsubs'] = True
                logger.debug("DownloaderMaster: keepsubs forzado por modo recorte")
            
            # Incrustar subtítulos SOLO si:
            # 1. No estamos en modo subtitle_only
            # 2. El usuario lo pidió
            # 3. NO estamos en un flujo de recorte (el sub incrustado en el completo se borraría o no coincidiría)
            has_fragments = bool(data.get("selected_fragments"))
            if mode != "subtitle_only" and data.get("embed_subtitles") and not has_fragments:
                ydl_opts['postprocessors'].append({
                    'key': 'FFmpegEmbedSubtitle',
                    'already_have_subtitle': False
                })
            elif has_fragments and data.get("embed_subtitles"):
                logger.info("DownloaderMaster: Incrustación de subtítulos desactivada para flujo de fragmentos "
                            "(evita el borrado del archivo original para permitir el recorte).")

        if mode == "subtitle_only":
            ydl_opts.update({
                'skip_download': True,
            })
            if sub_lang:
                subtitle_is_auto = data.get("subtitle_is_auto", False)
                ydl_opts['writesubtitles'] = not subtitle_is_auto
                ydl_opts['writeautomaticsub'] = subtitle_is_auto
        elif mode == "thumbnail_only":
            if 'format' in ydl_opts:
                del ydl_opts['format']
                
            ydl_opts.update({
                'skip_download': True,
                'writethumbnail': True,
                'ignore_no_formats_error': True,
            })
            # Asegurar el convertidor de formato a jpg
            ydl_opts['postprocessors'].append({
                'key': 'FFmpegThumbnailsConvertor',
                'format': 'jpg',
                'when': 'before_dl'
            })
            logger.info("DownloaderMaster: Configurando descarga de miniatura unica (Modo SOLO MINIATURA)")

        return ydl_opts

    def _get_cli_command(self, url, ydl_opts, data=None):
        """
        Reconstruye un comando CLI aproximado para que el usuario pueda copiarlo.
        """
        cmd = ["yt-dlp"]
        
        if 'format' in ydl_opts:
            cmd.append(f"-f \"{ydl_opts['format']}\"")
        
        if 'outtmpl' in ydl_opts:
            cmd.append(f"-o \"{ydl_opts['outtmpl']}\"")
            
        if 'ratelimit' in ydl_opts:
            cmd.append(f"--limit-rate {ydl_opts['ratelimit']}")
            
        if any(pp.get('key') == 'FFmpegMetadata' for pp in ydl_opts.get('postprocessors', [])):
            cmd.append("--embed-metadata")

        if any(pp.get('key') == 'EmbedThumbnail' for pp in ydl_opts.get('postprocessors', [])):
            cmd.append("--embed-thumbnail")

        if any(pp.get('key') == 'FFmpegEmbedSubtitle' for pp in ydl_opts.get('postprocessors', [])):
            cmd.append("--embed-subs")

        if any(pp.get('key') == 'FFmpegExtractAudio' for pp in ydl_opts.get('postprocessors', [])):
            cmd.append("-x") # --extract-audio

        # Post-processor args (especialmente -an)
        pp_args = ydl_opts.get('postprocessor_args', {})
        if 'ffmpeg' in pp_args and '-an' in pp_args['ffmpeg']:
            cmd.append("--postprocessor-args \"ffmpeg:-an\"")
            
        if ydl_opts.get('writethumbnail'):
            cmd.append("--write-thumbnail")
            if any(pp.get('key') == 'FFmpegThumbnailsConvertor' and pp.get('format') == 'jpg' for pp in ydl_opts.get('postprocessors', [])):
                cmd.append("--convert-thumbnails jpg")

        # Fragmentos - mostrar los rangos reales
        if 'download_ranges' in ydl_opts and data:
            fragments = data.get("selected_fragments", [])
            for frag in fragments:
                s = frag[0] / 1000.0
                e = frag[1] / 1000.0
                suffix = frag[2] if len(frag) > 2 else "fragment"
                cmd.append(f"--download-sections \"*{s}-{e}\" # _{suffix}")
        
        if ydl_opts.get('force_keyframes_at_cuts'):
            cmd.append("--force-keyframes-at-cuts")

        if ydl_opts.get('impersonate'):
            cmd.append(f"--impersonate \"{ydl_opts['impersonate']}\"")

        cmd.append(f"\"{url}\"")
        return " ".join(cmd)


    # Extensiones con las que puede quedar la miniatura escrita por yt-dlp: la
    # conversión a jpg es un postprocesador que puede no correr (contenedor de origen ya
    # jpg, conversión saltada, etc.).
    _THUMBNAIL_EXTS = ('.jpg', '.jpeg', '.png', '.webp', '.gif')

    def _consolidate_fragment_thumbnails(self, request_data, fragments):
        """
        Deja UNA sola miniatura, con el nombre base del medio, cuando la descarga se
        partió en fragmentos.

        En los modos de corte Normal y Preciso cada fragmento es una invocación
        independiente de yt-dlp cuyo outtmpl ya lleva el sufijo, así que 'writethumbnail'
        escribe una miniatura por pasada; y con "guardar miniatura" marcada,
        already_have_thumbnail=True hace que EmbedThumbnail no las borre tras
        incrustarlas (ver _prepare_opts). Resultado: N copias idénticas de la misma
        imagen ('Título_fragment01.jpg', '_fragment02.jpg'...) y ninguna con el nombre
        base, porque ninguna pasada usa ese nombre.

        Se conserva la primera renombrándola a '{base}{ext}' y se borran las demás. Que
        exista la del nombre base importa además para el envío a los editores: cuando un
        fragmento no tiene miniatura propia, el empaquetado cae a la del nombre base (ver
        editor_integration_manager.process_raw_download).
        """
        if not fragments or not request_data.get("download_thumbnail_file"):
            return

        output_path = request_data.get("output_path")
        if not output_path or not os.path.isdir(output_path):
            return

        found = []  # (ruta, nombre_base_del_medio)
        for i, frag in enumerate(fragments):
            suffix = frag[2] if len(frag) > 2 else f"fragment{i+1:02d}"
            for ext in self._THUMBNAIL_EXTS:
                pattern = os.path.join(glob.escape(output_path), f"*_{suffix}{ext}")
                for path in glob.glob(pattern):
                    if os.path.isfile(path):
                        stem = os.path.splitext(os.path.basename(path))[0]
                        found.append((path, stem[: -len(f"_{suffix}")]))

        if not found:
            return

        keeper, base_name = found[0]
        target = os.path.join(output_path, f"{base_name}{os.path.splitext(keeper)[1]}")

        try:
            if os.path.normcase(keeper) != os.path.normcase(target):
                if os.path.exists(target):
                    os.remove(keeper)
                else:
                    os.replace(keeper, target)
                    logger.info(f"DownloaderMaster: Miniatura de fragmentos unificada en {target}")
        except OSError as e:
            logger.warning(f"DownloaderMaster: No se pudo unificar la miniatura de los fragmentos: {e}")
            return

        for path, _ in found[1:]:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError as e:
                logger.warning(f"DownloaderMaster: No se pudo borrar la miniatura duplicada '{path}': {e}")

    def _handle_local_cuts(self, input_file, fragments, keep_original, progress_callback=None):
        """Usa ffmpeg directamente para realizar cortes sobre el archivo ya descargado."""
        if not os.path.exists(input_file):
            logger.error(f"DownloaderMaster: No se encuentra el archivo base para cortes: {input_file}")
            return

        import subprocess
        from core.setup.ffmpeg_setup import get_ffmpeg_path
        ffmpeg_exe = get_ffmpeg_path()
        
        if not os.path.exists(ffmpeg_exe):
            logger.error(f"DownloaderMaster: Binario de ffmpeg no encontrado en {ffmpeg_exe}")
            return
        
        base, ext = os.path.splitext(input_file)
        
        for i, frag in enumerate(fragments):
            start_ms, end_ms = frag[0], frag[1]
            suffix = frag[2] if len(frag) > 2 else f"fragment{i+1:02d}"
            output_file = f"{base}_{suffix}{ext}"
            
            # Tiempos en segundos para ffmpeg
            ss = start_ms / 1000.0
            t = (end_ms - start_ms) / 1000.0
            # Mapeo de extensiones a formatos de FFmpeg
            ext_map = {
                '.srt': 'srt',
                '.vtt': 'webvtt',
                '.ass': 'ass',
                '.ssa': 'ass',
            }
            # Corrección: usar output_file que es la variable definida arriba
            ff_format = ext_map.get(ext, 'srt') 
            cmd = [
                ffmpeg_exe, "-y",
                "-ss", str(ss),
                "-i", input_file,
                "-t", str(t),
                "-c", "copy",
                "-map", "0",
                "-map_metadata", "0",
                output_file
            ]
            
            if progress_callback:
                progress_callback({
                    "status": "fragment_progress",
                    "phase": "cutting",
                    "fragment_index": i + 1,
                    "fragment_count": len(fragments),
                })

            try:
                logger.info(f"DownloaderMaster: Procesando corte local {i+1}/{len(fragments)}: {output_file}")
                # Usamos utf-8 con reemplazo de errores para evitar fallos si ffmpeg imprime caracteres especiales/emojis
                subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8', errors='replace')
                logger.info(f"DownloaderMaster: Corte {i+1} completado exitosamente.")
                if progress_callback:
                    # Sin este aviso, el resto de la app (row.downloaded_filepath en
                    # Modo Rápido, last_downloaded_filepath en SOLO) nunca se entera de
                    # cuál es el archivo cortado - "Recodificar" no tenía ningún
                    # archivo real que recodificar en estos dos modos (ver conversación).
                    progress_callback({"status": "finished", "filename": output_file})
            except subprocess.CalledProcessError as e:
                logger.error(f"DownloaderMaster: Error en corte local {i+1}: {e.stderr}")
            except Exception as e:
                logger.error(f"DownloaderMaster: Error inesperado en corte local {i+1}: {e}")

        if not keep_original:
            try:
                os.remove(input_file)
                logger.info(f"DownloaderMaster: Archivo original eliminado ({input_file})")
            except Exception as e:
                logger.error(f"DownloaderMaster: No se pudo eliminar el original: {e}")
        else:
            logger.info(f"DownloaderMaster: Archivo original conservado ({input_file})")

    def _handle_subtitle_cuts_for_fragment(self, outtmpl_pattern, fragment_data, request_data):
        """
        Busca y recorta subtítulos para un fragmento descargado individualmente.
        """
        output_path = request_data.get("output_path", os.getcwd())
        suffix = fragment_data[2] if len(fragment_data) > 2 else "fragment"
        
        # En lugar de usar outtmpl_pattern (que puede tener %(title)s), buscamos por directorio y sufijo
        # yt-dlp suele guardar el archivo como 'Título_Sufijo.idioma.ext'
        search_pattern = os.path.join(output_path, f"*_{suffix}.*")
        matches = glob.glob(search_pattern)
        
        sub_extensions = ('.srt', '.vtt', '.ass', '.ssa', '.ttml', '.srv1', '.srv2', '.srv3', '.json3')
        found_subs = [m for m in matches if m.lower().endswith(sub_extensions)]
        
        if not found_subs:
            logger.warning(f"DownloaderMaster: No se encontraron subtítulos para el fragmento con sufijo: {suffix}")
            return
            
        for sub_path in found_subs:
            start_ms, end_ms = fragment_data[0], fragment_data[1]
            logger.info(f"DownloaderMaster: Recortando subtítulo para '{suffix}' ({start_ms}ms - {end_ms}ms)")
            
            # 1. Estandarizar (Siempre a SRT para máxima compatibilidad con FFmpeg)
            # Obtenemos un nombre temporal para el estandarizado para no machacar el original aún
            sub_path = self._prepare_subtitle_for_cutting(sub_path, request_data)
            if not sub_path: continue
            
            # 2. Recortar
            temp_cut = sub_path + ".cut.temp"
            result = SubtitleProcessor.cut_subtitle(sub_path, start_ms, end_ms, temp_cut)
            
            if result and os.path.exists(result):
                try:
                    # En Windows, rename fallará si el destino existe, así que removemos el original primero
                    if os.path.exists(sub_path):
                        os.remove(sub_path)
                    os.rename(result, sub_path)
                    logger.info(f"DownloaderMaster: Recorte exitoso para fragmento '{suffix}'")
                except Exception as e:
                    logger.error(f"DownloaderMaster: Error al reemplazar subtítulo del fragmento {suffix}: {e}")

    def _handle_subtitle_cuts_local(self, full_video_path, fragments, lang_code, request_data):
        """Recorta el subtítulo completo en múltiples archivos para cada fragmento."""
        base_video, _ = os.path.splitext(full_video_path)
        
        # Buscar el subtítulo completo
        search_patterns = [
            f"{base_video}.{lang_code}.*",
            f"{base_video}.*"
        ]
        
        full_sub_path = None
        sub_extensions = ('.srt', '.vtt', '.ass', '.ssa', '.ttml', '.srv1', '.srv2', '.srv3', '.json3')
        
        for pattern in search_patterns:
            matches = glob.glob(pattern)
            subs = [m for m in matches if m.lower().endswith(sub_extensions)]
            if subs:
                full_sub_path = subs[0]
                break
        
        if not full_sub_path:
            logger.warning(f"DownloaderMaster: No se encontró el subtítulo completo para recortes locales: {base_video}")
            return

        # 1. Estandarizar el subtítulo completo una sola vez antes de los recortes
        # Siempre estandarizamos si se va a recortar para asegurar compatibilidad con FFmpeg
        full_sub_path = self._prepare_subtitle_for_cutting(full_sub_path, request_data, force_standard=True)
        if not full_sub_path: return

        logger.info(f"DownloaderMaster: Iniciando recortes de subtítulos locales desde {full_sub_path}")
        
        success_count = 0
        for i, frag in enumerate(fragments):
            start_ms, end_ms = frag[0], frag[1]
            suffix = frag[2] if len(frag) > 2 else f"fragment{i+1:02d}"
            
            sub_ext = os.path.splitext(full_sub_path)[1]
            output_sub = f"{base_video}_{suffix}{sub_ext}"
            
            logger.info(f"DownloaderMaster: Creando subtítulo para fragmento {i+1}: {output_sub}")
            result = SubtitleProcessor.cut_subtitle(full_sub_path, start_ms, end_ms, output_sub)
            if result:
                success_count += 1
        
        # 2. Limpieza del original si se generaron fragmentos y no se requiere conservar el completo
        # (En DowP 2.0, si el switch de recorte está activo, se asume que queremos los fragmentos)
        if success_count > 0 and os.path.exists(full_sub_path):
            try:
                os.remove(full_sub_path)
                logger.info(f"DownloaderMaster: Subtítulo original eliminado tras recorte: {full_sub_path}")
            except Exception as e:
                logger.error(f"DownloaderMaster: No se pudo eliminar el subtítulo original: {e}")

    def _handle_subtitle_processing_only_sub(self, request_data, fragments):
        """Estandariza y/o recorta un subtítulo que fue descargado solo (sin video)."""
        output_path = request_data.get("output_path", os.getcwd())
        title = request_data.get("title", "")
        lang = request_data.get("subtitle_lang")
        
        found_subs = self._find_subtitle_files(output_path, title, lang, request_data)
        
        if not found_subs:
            logger.warning(f"DownloaderMaster: No se encontró el subtítulo para procesar en {output_path}")
            return

        # Solo procesamos el mejor match para evitar duplicados
        sub_path = found_subs[0]
        
        # 1. Estandarización a SRT si es necesario
        standardized_path = self._prepare_subtitle_for_cutting(sub_path, request_data)
        
        # 2. Recorte si hay fragmentos
        if request_data.get("cut_subtitles") and fragments:
            # Usamos el nombre base del archivo estandarizado como referencia para los fragmentos
            self._handle_subtitle_cuts_local(standardized_path, fragments, lang, request_data)
        
    def _handle_subtitle_standardization(self, video_filename, request_data):
        """Busca y estandariza los subtítulos descargados (sin recortar)."""
        output_path = request_data.get("output_path", os.getcwd())
        title = request_data.get("title", "")
        lang = request_data.get("subtitle_lang")
        found_subs = self._find_subtitle_files(output_path, title, lang, request_data)
        
        for sub_path in found_subs:
            self._prepare_subtitle_for_cutting(sub_path, request_data)

    def _prepare_subtitle_for_cutting(self, sub_path, request_data, force_standard=False):
        """Prepara el subtítulo (estandariza si es necesario) antes del recorte."""
        if force_standard or request_data.get("standardize_srt"):
            return SubtitleProcessor.standardize_to_srt(sub_path)
        return sub_path

    def _find_subtitle_files(self, output_path, title="", lang=None, request_data=None):
        """Encuentra subtítulos del trabajo actual, priorizando idioma y extensión esperada."""
        request_data = request_data or {}
        safe_title = self._sanitize_filename(title) if title else ""
        sub_extensions = ('.srt', '.vtt', '.ass', '.ssa', '.ttml', '.srv1', '.srv2', '.srv3', '.json3')
        search_roots = []
        if safe_title:
            search_roots.append(os.path.join(output_path, f"{safe_title}*"))
        search_roots.append(os.path.join(output_path, "*"))

        matches = []
        for pattern in search_roots:
            for candidate in glob.glob(pattern):
                if candidate not in matches and candidate.lower().endswith(sub_extensions):
                    matches.append(candidate)

        if safe_title:
            title_lower = safe_title.lower()
            scoped = [m for m in matches if os.path.basename(m).lower().startswith(title_lower)]
            if not scoped:
                logger.warning(f"DownloaderMaster: No se encontraron subtítulos asociados al título '{safe_title}'.")
                return []
            matches = scoped

        if lang:
            lang_token = f".{lang.lower()}."
            lang_matches = [m for m in matches if lang_token in os.path.basename(m).lower()]
            if lang_matches:
                matches = lang_matches

        desired_ext = "srt" if (request_data.get("cut_subtitles") or request_data.get("standardize_srt")) else request_data.get("subtitle_format")
        if desired_ext:
            desired_suffix = f".{desired_ext.lower()}"
            matches.sort(key=lambda p: (
                0 if p.lower().endswith(desired_suffix) else 1,
                os.path.basename(p).lower()
            ))
        else:
            matches.sort(key=lambda p: os.path.basename(p).lower())

        return matches

    def _make_hook(self, external_callback):
        """Crea un hook que envuelve el callback externo y verifica la cancelación."""
        def hook(d):
            # 0. Anotar las rutas ANTES de revisar la cancelación: el aviso que trae la
            # cancelación suele ser el primero de un archivo recién abierto, y sin
            # anotarlo ese .part quedaría fuera de la limpieza.
            filename = d.get("filename")
            if filename:
                format_id = (d.get("info_dict") or {}).get("format_id")
                self._touched_streams.setdefault(filename, format_id)
            if d.get("tmpfilename"):
                self._touched_tmp.add(d["tmpfilename"])

            # 1. Verificar Cancelación
            if self.cancellation_event and self.cancellation_event.is_set():
                logger.info("DownloaderMaster: Cancelación detectada en el hook")
                raise DownloadCancelledError(QCoreApplication.translate("DownloaderMaster", "Descarga cancelada por el usuario"))

            # 2. Anotar qué ítem de playlist llegó a terminar. Es la ÚNICA señal fiable
            # de éxito por ítem: con ignoreerrors='only_download' yt-dlp registra el
            # error y sigue, sin lanzar nada que se pueda inspeccionar después.
            if d.get("status") == "finished":
                index = (d.get("info_dict") or {}).get("playlist_index")
                if index is not None:
                    try:
                        self._completed_playlist_indices.add(int(index))
                    except (TypeError, ValueError):
                        pass

            # 3. Ejecutar callback externo
            if external_callback:
                external_callback(d)
        return hook

    def _requested_playlist_items(self, ydl_opts, info):
        """Índices que se pidieron descargar, tal y como los numera yt-dlp.

        Sale de 'playlist_items' cuando el usuario eligió ítems concretos (el caso del
        selector de playlist), y si no, de las propias entradas devueltas."""
        spec = ydl_opts.get("playlist_items")
        if spec:
            requested = []
            for chunk in str(spec).split(","):
                chunk = chunk.strip()
                if not chunk:
                    continue
                try:
                    if "-" in chunk:  # rangos del estilo "3-7"
                        start, end = chunk.split("-", 1)
                        requested.extend(range(int(start), int(end) + 1))
                    else:
                        requested.append(int(chunk))
                except ValueError:
                    continue
            return requested

        entries = list((info or {}).get("entries") or [])
        return [((entry or {}).get("playlist_index") or pos)
                for pos, entry in enumerate(entries, start=1)]

    def _retry_failed_playlist_items(self, url, ydl_opts, info, yt_dlp):
        """Reintenta con el cliente alternativo SOLO los ítems de la playlist que fallaron.

        Por qué hace falta: una descarga suelta que recibe un 403 de YouTube se recupera
        sola, porque la excepción llega al except de download() y ahí se reintenta con
        'web_embedded'. Una playlist NO, porque lleva ignoreerrors='only_download' para
        que un vídeo privado no tumbe a los demás — y eso hace que yt-dlp se trague
        también los 403 reales, sin lanzar excepción. El reintento nunca se disparaba y
        la playlist entera acababa vacía mientras las descargas sueltas funcionaban.

        Se reintenta por índice en vez de repetir la playlist completa para no volver a
        bajar lo que ya está en disco. El hook sigue enganchado en las opciones de
        respaldo (deepcopy no clona funciones), así que los ítems que se recuperen aquí
        se anotan igual en _completed_playlist_indices.
        """
        from core.ytdlp_logic.resilient_downloader import make_fallback_ydl_opts

        pending = [i for i in self._requested_playlist_items(ydl_opts, info)
                   if i not in self._completed_playlist_indices]
        if not pending:
            return

        logger.warning(
            f"DownloaderMaster: {len(pending)} ítem(s) de la playlist no se descargaron "
            f"(YouTube suele devolver 403 en el primer intento). Reintentando solo esos "
            f"con cliente alternativo (web_embedded): {pending}"
        )
        fallback_opts = make_fallback_ydl_opts(ydl_opts)
        fallback_opts["playlist_items"] = ",".join(str(i) for i in pending)
        try:
            with yt_dlp.YoutubeDL(fallback_opts) as ydl_fallback:
                ydl_fallback.extract_info(url, download=True)
        except DownloadCancelledError:
            raise
        except Exception as retry_err:
            # El reintento es un extra: si también falla, se sigue adelante y el resumen
            # dirá cuántos quedaron sin descargar.
            logger.error(f"DownloaderMaster: el reintento de la playlist también falló: {retry_err}")

        recovered = [i for i in pending if i in self._completed_playlist_indices]
        if recovered:
            logger.info(f"DownloaderMaster: recuperados {len(recovered)} de {len(pending)} "
                        f"ítem(s) con el cliente alternativo.")

    # Pistas en el mensaje de yt-dlp de un post-proceso opcional: fallar ahí no invalida
    # el medio ya descargado (a diferencia de la fusión o la extracción de audio).
    _COSMETIC_PP_HINTS = {
        "thumbnail": QT_TRANSLATE_NOOP("DownloaderMaster", "No se pudo incrustar la carátula en este formato"),
        "subtitle": QT_TRANSLATE_NOOP("DownloaderMaster", "No se pudieron incrustar los subtítulos"),
        "metadata": QT_TRANSLATE_NOOP("DownloaderMaster", "No se pudieron incrustar los metadatos"),
    }

    def _cosmetic_pp_failure(self, err_msg):
        """Si el error es de un post-proceso opcional (carátula, subtítulos, metadatos)
        y el medio final ya está completo en disco, devuelve el aviso para el usuario;
        si no, None. Antes cualquier fallo así marcaba la descarga como error aunque el
        archivo estuviera bajado (ej. incrustar carátula en un .webm): la fila quedaba en
        rojo, sin poder arrastrarse."""
        from core.ytdlp_logic.analyzer import strip_ansi_codes
        from core.utils.output_artifacts import find_actual_downloaded_file
        clean = strip_ansi_codes(err_msg).lower()
        if "postprocessing:" not in clean:
            return None
        hint = next((text for key, text in self._COSMETIC_PP_HINTS.items() if key in clean), None)
        if not hint:
            return None
        for stream, format_id in self._touched_streams.items():
            media = find_actual_downloaded_file(stream)
            if not media or not os.path.isfile(media):
                continue
            root = os.path.splitext(media)[0]
            if format_id and root.endswith(f".f{format_id}"):
                continue  # stream sin fusionar: el medio final no existe
            return QCoreApplication.translate("DownloaderMaster", hint)
        return None

    # "[info] Writing video thumbnail 42 to: C:\...\Título.webp" (también "playlist
    # thumbnail"): yt-dlp no avisa de las miniaturas por el hook de progreso, solo así.
    _THUMB_WRITTEN_RE = re.compile(r"Writing .*?thumbnail\b.*? to: (.+)$")

    def _on_ytdlp_message(self, msg):
        from core.ytdlp_logic.analyzer import strip_ansi_codes
        match = self._THUMB_WRITTEN_RE.search(strip_ansi_codes(str(msg)).strip())
        if match and hasattr(self, "_touched_thumbs"):
            self._touched_thumbs.add(os.path.splitext(match.group(1).strip())[0])

    def _temp_artifacts(self, keep_thumbnails, keep_partials=False):
        """Residuos de ESTA descarga, derivados solo de las rutas exactas que yt-dlp
        reportó en el hook (ver _make_hook) -- nunca por patrón de nombre.

        Antes se barría la carpeta con globs armados con el título ('título*.part',
        '*.f[0-9]*.part'...): el patrón sin título se llevaba los .part de OTRAS
        descargas en curso en la misma carpeta, y el prefijo atrapaba archivos de
        títulos parecidos ('Video' -> 'Video 2.f137.mp4', 'Video (Live).jpg').

        Nunca incluye el medio final: un stream solo se borra si es intermedio (lleva
        '.f<format_id>' en el nombre, ver YoutubeDL.process_info), que es lo que ffmpeg
        fusiona y ya no sirve. Las miniaturas solo si se crearon durante esta descarga:
        una que ya existía (de una descarga anterior, o del usuario) no se toca.

        keep_partials (pausa, ver request_pause): se conserva todo lo que yt-dlp puede
        retomar -- .part, fragmentos, .ytdl y streams ya completos sin fusionar."""
        paths = set()
        bases = set()
        if not keep_partials:
            for tmp in self._touched_tmp:
                paths.add(tmp)
                paths.update(glob.glob(glob.escape(tmp) + "-Frag*"))
        for stream, format_id in self._touched_streams.items():
            root = os.path.splitext(stream)[0]
            marker = f".f{format_id}" if format_id else None
            is_intermediate = bool(marker and root.endswith(marker))
            if is_intermediate:
                root = root[: -len(marker)]
            bases.add(root)
            if keep_partials:
                continue
            part = stream + ".part"
            paths.update({part, stream + ".ytdl", part + ".ytdl"})
            paths.update(glob.glob(glob.escape(part) + "-Frag*"))
            if is_intermediate:
                paths.add(stream)
        for base in bases:
            paths.add(base + ".temp")
            paths.update(glob.glob(glob.escape(base) + ".temp.*"))
        if not keep_thumbnails:
            # Nombres de miniatura: los derivados del medio y los que yt-dlp avisó haber
            # escrito (incluye la miniatura de la playlist, que no comparte nombre con
            # ningún medio). Con estas últimas también .png: la conversión puede ir a png.
            candidates = [(base, (".webp", ".jpg")) for base in bases]
            candidates += [(base, (".webp", ".jpg", ".jpeg", ".png")) for base in self._touched_thumbs]
            for base, exts in candidates:
                for ext in exts:
                    thumb = base + ext
                    try:
                        # 2 s de margen por la resolución de fecha de algunos sistemas de archivos
                        if os.path.getmtime(thumb) >= self._download_started_at - 2:
                            paths.add(thumb)
                    except OSError:
                        pass
        return paths

    def _cleanup_temp_artifacts(self, keep_thumbnails, keep_partials=False):
        from core.utils.cleanup_manager import CleanupManager
        if keep_partials:
            logger.info("DownloaderMaster: Pausa: se conserva lo descargado para retomarlo.")
        removed = 0
        for path in self._temp_artifacts(keep_thumbnails, keep_partials):
            if os.path.isfile(path) and CleanupManager.safe_remove(path):
                logger.debug(f"DownloaderMaster: Residuo eliminado: {path}")
                removed += 1
        if removed:
            logger.info(f"DownloaderMaster: Se limpiaron {removed} archivos residuales de la descarga.")

    @staticmethod
    def _sanitize_filename(filename):
        """Delega en la única fuente de verdad (ver output_artifacts.sanitize_filename).

        La lógica vivía aquí, pero queue_manager tenía su propia copia divergente para
        predecir la ruta del archivo, y las dos tenían que dar exactamente el mismo
        nombre o la predicción apuntaba a algo inexistente. Ahora hay una sola."""
        from core.utils.output_artifacts import sanitize_filename
        return sanitize_filename(filename)

