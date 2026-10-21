import os
import re
import platform
import subprocess
from PySide6.QtCore import QObject, Signal, QThread
from core.logger.logger_manager import logger

from core.services.adobe_socket_server import AdobeSocketServer
from core.services.davinci_integration_service import DaVinciIntegrationService
from core.services.vegas_integration_service import VegasIntegrationService

class ProcessMonitorThread(QThread):
    processes_updated = Signal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_running = True
        self.targets = {
            "premiere": "Adobe Premiere Pro.exe",
            "aftereffects": "AfterFX.exe",
            "photoshop": "Photoshop.exe",
            "davinci": "Resolve.exe",
            "vegas": [
                "vegas2026.exe", "vegas220.exe", "vegas210.exe", "vegas200.exe",
                "vegas190.exe", "vegas180.exe", "vegas170.exe", "vegas160.exe",
                "vegas150.exe", "vegas140.exe", "vegas.exe"
            ]
        }
        
    def run(self):
        import time
        is_windows = platform.system() == "Windows"
        while self.is_running:
            try:
                if is_windows:
                    import csv, io
                    creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                    output = subprocess.check_output(['tasklist', '/fo', 'csv', '/nh'], creationflags=creationflags).decode('utf-8', errors='ignore')
                    reader = csv.reader(io.StringIO(output))
                    
                    running_exes = set()
                    for row in reader:
                        if len(row) > 0 and row[0]:
                            running_exes.add(row[0].strip())
                                
                    status = {}
                    for app_id, target in self.targets.items():
                        if isinstance(target, (list, tuple)):
                            status[app_id] = any(t in running_exes for t in target)
                        else:
                            status[app_id] = (target in running_exes)
                        
                    self.processes_updated.emit(status)
                else:
                    output = subprocess.check_output(['ps', '-A', '-o', 'comm'], text=True, errors='ignore')
                    status = {
                        "premiere": "Adobe Premiere Pro" in output,
                        "aftereffects": ("After Effects" in output or "AfterFX" in output),
                        "photoshop": "Photoshop" in output,
                        "davinci": bool(re.search(r'(?:^|/|\s)Resolve(?:\.app)?(?:\s|$)', output, re.MULTILINE)),
                        "vegas": False
                    }
                    self.processes_updated.emit(status)
            except Exception as e:
                pass
            time.sleep(3.0)
            
    def stop(self):
        self.is_running = False
        self.wait()


class EditorIntegrationManager(QObject):
    """
    Gestor Maestro para todas las integraciones de editores de video (NLEs).
    Centraliza el estado de conexión y delega las tareas al servicio correspondiente
    (Adobe, DaVinci, Vegas, etc.).
    """
    # Se emite cuando el editor activo cambia (ej. None -> 'premiere' o viceversa)
    active_editor_changed = Signal(object)
    # Reemite lo que llega del panel con "Enviar a DowP" (ver AdobeSocketServer.files_pushed)
    # para que la ventana principal no tenga que conocer el servidor de sockets.
    media_pushed_from_editor = Signal(list, str)
    # Se emite cuando cambia el estado de proceso en el SO {app_id: bool}
    process_status_changed = Signal(dict)
    
    _instance = None

    def __init__(self):
        super().__init__()
        self.active_editor = None
        self.is_auto_send_enabled = True
        self.process_status = {}
        
        # Servicios
        self.adobe_service = AdobeSocketServer()
        self.davinci_service = DaVinciIntegrationService.get_instance()
        self.vegas_service = VegasIntegrationService.get_instance()
        
        # Conectar señales del servicio Adobe
        self.adobe_service.active_target_changed.connect(self._on_adobe_target_changed)
        self.adobe_service.files_pushed.connect(self.media_pushed_from_editor)
        self.adobe_service.client_registered.connect(self._on_adobe_client_registered)
        
        # Conectar señales de VEGAS y registrar sus rutas HTTP en el servidor aiohttp común
        self.vegas_service.files_pushed.connect(self.media_pushed_from_editor)
        self.vegas_service.attach_routes(self.adobe_service.app)

        EditorIntegrationManager._instance = self
        
        # Monitor de procesos
        self.process_monitor = ProcessMonitorThread()
        self.process_monitor.processes_updated.connect(self._on_processes_updated)

    @classmethod
    def get_instance(cls):
        return cls._instance

    def _on_adobe_client_registered(self, sid, app_id):
        if app_id in ('premiere', 'aftereffects', 'photoshop'):
            self.process_status[app_id] = True
            self.process_status_changed.emit(self.process_status)
        
    def _on_processes_updated(self, status_dict):
        # Si un cliente Adobe ya está registrado y conectado por Socket.IO, garantizar que cuente como en ejecución
        if hasattr(self, 'adobe_service') and self.adobe_service:
            connected_adobe = set(self.adobe_service.clients.values())
            for app_id in ('premiere', 'aftereffects', 'photoshop'):
                if app_id in connected_adobe:
                    status_dict[app_id] = True

        self.process_status = status_dict
        self.process_status_changed.emit(status_dict)
        
        # Auto-desvincular si Vegas se cierra y era el editor activo
        if self.active_editor == 'vegas' and not status_dict.get('vegas', False):
            logger.info("[EditorManager] VEGAS Pro se ha cerrado. Desvinculando editor activo.")
            self.force_adobe_target(None)

    def start_all_services(self):
        """Inicia todos los servidores de comunicación en segundo plano."""
        logger.info("[EditorManager] Iniciando servicios de integración...")
        self.adobe_service.start()
        self.process_monitor.start()

    def stop_all_services(self):
        """Detiene todos los servicios al cerrar la aplicación."""
        logger.info("[EditorManager] Deteniendo servicios de integración...")
        try:
            self.process_monitor.stop()
        except Exception: pass
        
        try:
            self.adobe_service.stop()
        except Exception as e:
            logger.error(f"[EditorManager] Error deteniendo Adobe service: {e}")

    def _on_adobe_target_changed(self, target_app):
        """Callback cuando Premiere o After Effects cambian de estado."""
        prev = self.active_editor
        if target_app:
            self.active_editor = target_app
            logger.info(f"[EditorManager] Editor activo establecido a: {self.active_editor}")
            if prev == "vegas" and hasattr(self, 'vegas_service') and self.vegas_service:
                self.vegas_service.notify_linked(False)
        else:
            if self.active_editor in ('premiere', 'aftereffects', 'photoshop'):
                self.active_editor = None
                logger.info("[EditorManager] Ningún editor activo conectado.")
            
        self.active_editor_changed.emit(self.active_editor)

    def disconnect_editor(self):
        """Desconecta el editor actual forzando a None."""
        self._on_adobe_target_changed(None)

    def force_adobe_target(self, target_app):
        """Intenta forzar el objetivo activo. Soporta Adobe, DaVinci y VEGAS Pro."""
        prev_editor = self.active_editor
        if target_app is None:
            self.active_editor = None
            logger.info("[EditorManager] Editor activo desvinculado (None).")
            self.active_editor_changed.emit(None)
            if hasattr(self, 'adobe_service') and self.adobe_service:
                self.adobe_service.force_active_target(None)
            if prev_editor == "vegas" and hasattr(self, 'vegas_service') and self.vegas_service:
                self.vegas_service.notify_linked(False)
            return True
            
        if target_app == "davinci":
            self.active_editor = "davinci"
            logger.info(f"[EditorManager] Editor activo establecido a: {self.active_editor}")
            self.active_editor_changed.emit(self.active_editor)
            if prev_editor == "vegas" and hasattr(self, 'vegas_service') and self.vegas_service:
                self.vegas_service.notify_linked(False)
            if hasattr(self, 'adobe_service') and self.adobe_service:
                self.adobe_service.force_active_target(None)
            return True

        if target_app == "vegas":
            self.active_editor = "vegas"
            logger.info(f"[EditorManager] Editor activo establecido a: {self.active_editor}")
            self.active_editor_changed.emit(self.active_editor)
            if hasattr(self, 'vegas_service') and self.vegas_service:
                self.vegas_service.notify_linked(True)
            if hasattr(self, 'adobe_service') and self.adobe_service:
                self.adobe_service.force_active_target(None)
            return True
            
        if self.adobe_service:
            if prev_editor == "vegas" and hasattr(self, 'vegas_service') and self.vegas_service:
                self.vegas_service.notify_linked(False)
            return self.adobe_service.force_active_target(target_app)
        return False

    def send_file(self, file_package):
        """
        Envía un archivo descargado al editor activo actual.
        """
        if not self.active_editor:
            logger.warning("[EditorManager] No hay un editor activo. No se enviará el archivo.")
            return False

        if self.active_editor in ('premiere', 'aftereffects', 'photoshop'):
            return self.adobe_service.send_file_to_adobe(file_package)
        elif self.active_editor == 'davinci':
            return self.davinci_service.send_files_to_davinci([file_package])
        elif self.active_editor == 'vegas':
            return self.vegas_service.send_files_to_vegas([file_package])
        else:
            logger.error(f"[EditorManager] Editor desconocido: {self.active_editor}")
            return False

    def send_batch(self, files, target_bin=None):
        """
        Envía un lote de archivos al editor activo actual.
        """
        if not self.active_editor:
            logger.warning("[EditorManager] No hay un editor activo. No se enviará el lote.")
            return False

        if self.active_editor in ('premiere', 'aftereffects', 'photoshop'):
            return self.adobe_service.send_batch_to_adobe(files, target_bin)
        elif self.active_editor == 'davinci':
            return self.davinci_service.send_files_to_davinci(files)
        elif self.active_editor == 'vegas':
            return self.vegas_service.send_files_to_vegas(files)
        else:
            logger.error(f"[EditorManager] Editor desconocido: {self.active_editor}")
            return False

    def send_subclips(self, payload):
        """
        Envía información de subclips (puntos in/out) al editor activo.
        payload: {"filePath": str, "subclips": [{"name": str, "in": float, "out": float}]}
        """
        if not self.active_editor:
            logger.warning("[EditorManager] No hay un editor activo. No se enviarán los subclips.")
            return False

        if self.active_editor in ('premiere', 'aftereffects', 'photoshop'):
            return self.adobe_service.send_subclips_to_adobe(payload)
        elif self.active_editor == 'davinci':
            return self.davinci_service.send_subclips_to_davinci(payload)
        elif self.active_editor == 'vegas':
            return self.vegas_service.send_subclips_to_vegas(payload)
        return False

    def connect_to_queue(self, queue_mgr):
        """Conecta el gestor de editores con el QueueManager para auto-enviar descargas."""
        queue_mgr.job_status_changed.connect(self._on_job_status_changed)
        self._queue_mgr = queue_mgr
        logger.info("[EditorManager] Conectado al QueueManager.")

    def _on_job_status_changed(self, job_id, status):
        """Callback cuando cambia el estado de un trabajo en el QueueManager."""
        if not self.is_auto_send_enabled:
            return
            
        if status == "COMPLETED" and self.active_editor:
            job = self._queue_mgr.get_job(job_id)
            if job and job.final_filepath:
                # ── Quién envía cada tipo de trabajo ──────────────────────────────
                # La pestaña que CREA el trabajo es la que lo envía al editor, nunca
                # este gestor. La pestaña sabe cosas que aquí no se saben: cuál es el
                # archivo realmente escrito en disco (_find_actual_downloaded_file
                # resuelve la extensión y los sufijos que pone yt-dlp), si la descarga
                # se partió en fragmentos, y cuándo terminó el grupo entero.
                #
                # RECODE: lo envía la pestaña después de limpiar sus temporales.
                if job.job_type == "RECODE":
                    return
                # DOWNLOAD y PLAYLIST: los envía siempre la pestaña, se recodifiquen
                # después o no.
                #
                # Antes aquí solo se descartaban los que tenían recode_enabled, así que
                # una descarga normal del Proceso Avanzado se enviaba DOS VECES: una
                # desde aquí y otra desde download_controller._on_job_status_changed.
                # En el proyecto de Premiere aparecían dos copias de cada medio y de
                # cada miniatura. El Modo Rápido no lo sufría porque solo mete trabajos
                # RECODE en la cola, y esos ya estaban descartados arriba.
                if job.job_type in ("DOWNLOAD", "PLAYLIST"):
                    return

                # Tipos de trabajo futuros que ninguna pestaña reclame acaban aquí.
                self.process_completed_job(job)

    def process_completed_job(self, job):
        """Empaqueta y envía un trabajo de cola completado al editor activo."""
        self.process_raw_download(job.final_filepath, job.request_data)

    _IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")

    # Formatos que cuentan como "el medio es una imagen" al empaquetar para el editor. Es
    # mas amplia que _IMAGE_EXTENSIONS (que solo busca miniaturas) porque el Editor de
    # Imagen exporta tambien psd, tiff, avif...: sin esto, esas salidas viajaban en el
    # hueco de "video" y Photoshop no las reconocia.
    _IMAGE_PAYLOAD_EXTENSIONS = (
        ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff",
        ".psd", ".psb", ".avif", ".heic", ".heif", ".svg", ".ico", ".tga",
    )

    @staticmethod
    def _find_sidecar_image(output_dir, base_name):
        """Miniatura de `base_name` en output_dir, en cualquier formato de imagen.
        Devuelve la ruta con separadores "/" (como la espera el panel) o None."""
        if not output_dir or not base_name:
            return None
        for ext in EditorIntegrationManager._IMAGE_EXTENSIONS:
            candidate = os.path.join(output_dir, base_name + ext)
            if os.path.exists(candidate):
                return candidate.replace(chr(92), "/")
        return None

    @staticmethod
    def _find_sidecar_subtitle(output_dir, base_name):
        """Subtítulo .srt de `base_name` en output_dir: 'base.srt' o 'base.<idioma>.srt'.
        Coincidencia exacta del nombre base: con 'startswith' entraba también el de otro
        medio cuyo nombre empezara igual ('clip 2.es.srt' para 'clip').
        Devuelve la ruta con separadores "/" o None."""
        if not output_dir or not base_name:
            return None
        pattern = re.compile(rf"^{re.escape(base_name)}(\.[^.]+)?\.srt$", re.IGNORECASE)
        try:
            names = sorted(os.listdir(output_dir))
        except OSError:
            return None
        for name in names:
            if pattern.match(name):
                return os.path.join(output_dir, name).replace(chr(92), "/")
        return None

    def _thumbnail_already_sent(self, thumb_path):
        """True si esta MISMA imagen ya viajó en un envío anterior de la misma tanda de
        fragmentos. Con cortes + recodificación, cada fragmento se envía por separado al
        terminar SU recodificación (ver los _send_to_editor_if_enabled de quick_mode y
        advanced_process) y todos comparten la única miniatura del medio (ver
        DownloaderMaster._consolidate_fragment_thumbnails), así que sin esto la misma
        imagen se importaba una vez por fragmento.

        La identidad incluye tamaño y fecha de modificación: si el usuario vuelve a
        descargar el mismo video, la miniatura se reescribe y se envía de nuevo, como
        corresponde. Solo se consulta en envíos con fragmentos, para no alterar el resto
        de flujos (herramientas de imagen/video, subtítulos, descargas normales).
        """
        try:
            stat = os.stat(thumb_path)
            key = (os.path.normcase(os.path.abspath(thumb_path)), stat.st_size, int(stat.st_mtime))
        except OSError:
            return False

        seen = getattr(self, "_sent_fragment_thumbnails", None)
        if seen is None:
            seen = self._sent_fragment_thumbnails = []
        if key in seen:
            return True
        seen.append(key)
        del seen[:-64]  # memoria acotada: solo importan los envíos recientes
        return False

    def _batch_already_sent(self, batch_key):
        """Evita reenviar el mismo lote de fragmentos si process_raw_download se invoca
        más de una vez para los archivos de una misma tanda."""
        if not batch_key:
            return False
        seen = getattr(self, "_sent_fragment_batches", None)
        if seen is None:
            seen = self._sent_fragment_batches = []
        if batch_key in seen:
            return True
        seen.append(batch_key)
        del seen[:-32]
        return False

    def process_raw_download(self, final_filepath, request_data):
        """Empaqueta y envía un archivo descargado al editor activo."""
        if not final_filepath:
            return
            
        import os
        import re
        
        # Buscar el archivo real descargado si la ruta temporal fue eliminada (ej. Streams
        # HLS / merger). Misma resolución que usan Modo Rápido y Proceso Avanzado: a
        # igualdad de nombre base el medio gana sobre su miniatura o sus subtítulos, que
        # antes podían colarse aquí y viajar al editor como si fueran el video.
        from core.utils.output_artifacts import find_actual_downloaded_file
        final_filepath = find_actual_downloaded_file(final_filepath) or final_filepath
        
        mode = request_data.get("mode") if request_data else None
        if mode not in ("thumbnail_only", "subtitle_only") and not os.path.exists(final_filepath):
            logger.error(f"[EditorManager] No se pudo encontrar el archivo final para enviar: {final_filepath}")
            return
            
        output_dir = os.path.dirname(final_filepath)
        raw_base_name = os.path.splitext(os.path.basename(final_filepath))[0]
        
        selected_fragments = request_data.get("selected_fragments", []) if request_data else []
        is_fragmented = bool(selected_fragments)

        # Miniatura y subtítulos se buscan por nombre en la carpeta de salida, así que solo
        # se adjuntan si ESTE trabajo los pidió. Si no, se colaba cualquier archivo previo
        # con el mismo nombre base: un fragmento del Modo Rápido sin miniatura viajaba con
        # 'Título.jpg' de una descarga anterior del Proceso Avanzado. La carátula
        # incrustada no cuenta: yt-dlp borra su archivo tras incrustarla.
        # '_keep_thumbnail_files' lo anota la cola cuando el modo en lote "Con medio"
        # descarga la miniatura aunque download_thumbnail_file venga en False.
        rd = request_data or {}
        wants_thumbnail = bool(rd.get("download_thumbnail_file") or rd.get("_keep_thumbnail_files"))
        wants_subtitles = mode == "subtitle_only" or bool(rd.get("embed_subtitles"))
        
        # Prefijo/sufijo que la tarjeta "Recodificar" le puso al archivo de salida (ver
        # preset_manager.build_recode_output_path: "{prefijo}{base}{sufijo}"). Hay que
        # quitarlos para volver al nombre base del medio, del que cuelgan la miniatura y
        # los subtítulos.
        recode_prefix = (request_data.get("recode_filename_prefix") or "") if request_data else ""
        recode_suffix = (request_data.get("recode_filename_suffix") or "") if request_data else ""

        def strip_recode_affixes(name):
            # '_recoded' es el sufijo por defecto histórico: se sigue quitando aunque
            # request_data no traiga los campos (ej. un envío disparado desde la cola).
            for suf in (recode_suffix, '_recoded'):
                if suf and name.endswith(suf):
                    name = name[:-len(suf)]
                    break
            if recode_prefix and name.startswith(recode_prefix):
                name = name[len(recode_prefix):]
            return name

        # Determinar el nombre base limpio de forma 100% precisa
        if is_fragmented:
            clean_base_name = raw_base_name
            for i, frag in enumerate(selected_fragments):
                suf = frag[2] if len(frag) > 2 else f"fragment{i+1:02d}"
                target_suffix = f"_{suf}"
                if raw_base_name.endswith(target_suffix):
                    clean_base_name = raw_base_name[:-len(target_suffix)]
                    break
        else:
            clean_base_name = strip_recode_affixes(raw_base_name)

        # Los sidecars conservan el nombre del medio ORIGINAL, sin los afijos del
        # recodificado ('clip_fragment01.jpg' junto a 'clip_fragment01_recoded.mov').
        sidecar_base_name = strip_recode_affixes(clean_base_name)

        # Cualquier extension de imagen, no solo .jpg: la miniatura conserva el formato
        # de origen cuando la baja la cola (ver QueueWorker._download_best_thumb) o
        # cuando el postprocesador de conversion de yt-dlp no llega a correr, asi que
        # buscar solo ".jpg" dejaba fuera .webp/.png y el paquete viajaba sin miniatura.
        # Candidatos de nombre para la miniatura, del mas especifico al mas general. El
        # segundo hace falta desde que una descarga con cortes deja UNA sola miniatura
        # con el nombre base (ver DownloaderMaster._consolidate_fragment_thumbnails): un
        # fragmento recodificado ('clip_fragment01_recoded.mov') ya no tiene la suya
        # propia y debe caer a la del medio completo ('clip.jpg').
        thumb_base_candidates = [sidecar_base_name]
        for i, frag in enumerate(selected_fragments):
            frag_suffix = frag[2] if len(frag) > 2 else f"fragment{i+1:02d}"
            if sidecar_base_name.endswith(f"_{frag_suffix}"):
                thumb_base_candidates.append(sidecar_base_name[: -len(frag_suffix) - 1])

        expected_thumb_path = None
        for candidate_base in (thumb_base_candidates if wants_thumbnail else []):
            expected_thumb_path = self._find_sidecar_image(output_dir, candidate_base)
            if expected_thumb_path:
                break
            
        file_packages = []
        # Salvo un caso (ver is_plain_fragment_file), si no se pudo armar el lote de
        # fragmentos se empaqueta el archivo recibido tal cual.
        allow_single_fallback = True
        
        # Si fue descarga de múltiples fragmentos, generamos sus nombres exactos.
        if is_fragmented:
            try:
                for i, frag in enumerate(selected_fragments):
                    suffix = frag[2] if len(frag) > 2 else f"fragment{i+1:02d}"
                    frag_base = f"{clean_base_name}_{suffix}"
                    
                    # Buscar el archivo de video (podría ser .mp4, .mkv, etc)
                    vid_path = None
                    for ext in ('.mp4', '.mkv', '.webm', '.mov', '.avi', '.flv', '.wmv', '.m4v', '.mp3', '.m4a', '.wav', '.flac', '.aac', '.ogg', '.opus', '.weba'):
                        candidate = os.path.join(output_dir, frag_base + ext)
                        if os.path.exists(candidate):
                            vid_path = candidate.replace('\\', '/')
                            break
                            
                    if vid_path:
                        # Buscar subtítulo exacto para este fragmento
                        sub_path = self._find_sidecar_subtitle(output_dir, frag_base) if wants_subtitles else None

                        # Buscar miniatura específica de este fragmento
                        frag_thumb_path = self._find_sidecar_image(output_dir, frag_base) if wants_thumbnail else None
                        if not frag_thumb_path:
                            frag_thumb_path = expected_thumb_path  # respaldo: la del nombre base
                                
                        file_packages.append({
                            "video": vid_path,
                            "thumbnail": frag_thumb_path,
                            "subtitle": sub_path
                        })
            except Exception as e:
                logger.error(f"Error empaquetando fragmentos: {e}")

            # Con cortes, esta función se llama UNA VEZ POR FRAGMENTO y solo la
            # llamada del ÚLTIMO logra reconstruir el lote completo (clean_base_name
            # solo sabe quitar el sufijo del último fragmento); las demás salen sin
            # paquetes a propósito, para no mandar el lote una vez por fragmento. Por
            # eso el fallback de abajo NO debe dispararse cuando el archivo recibido es
            # un fragmento tal cual salió de la descarga: llegaría suelto y otra vez
            # dentro del lote. Solo se usa cuando el nombre ya no es reconstruible
            # (recodificado), que es justo el caso que no enviaba nada.
            is_plain_fragment_file = any(
                raw_base_name.endswith(f"_{frag[2] if len(frag) > 2 else f'fragment{i+1:02d}'}")
                for i, frag in enumerate(selected_fragments)
            )

            allow_single_fallback = not is_plain_fragment_file
            if not file_packages and allow_single_fallback:
                # La reconstrucción "{base}_{sufijo}{ext}" no encontró ningún archivo.
                # Pasa siempre que la descarga con cortes se recodificó: cada fragmento
                # queda como "clip_fragment01_recoded.mov" y se envía por separado al
                # terminar SU recodificación (ver los _send_to_editor_if_enabled de
                # advanced_process y quick_mode), así que ni el nombre reconstruido
                # existe ni tendría sentido rearmar el lote entero — los demás
                # fragmentos todavía se están recodificando y llegarían duplicados.
                # Sin esto, la función salía en silencio por "if not file_packages:
                # return" y NADA llegaba al editor con cortes + recodificación, en
                # Modo Rápido y en Proceso Avanzado, con cualquier editor.
                logger.info(
                    "[EditorManager] Corte sin nombres reconstruibles (recodificado): "
                    f"se envía el archivo recibido tal cual ({os.path.basename(final_filepath)})."
                )

        if not file_packages and allow_single_fallback:
            # Archivo único normal (o el fragmento suelto del fallback de arriba)
            vid_path = final_filepath.replace('\\', '/') if os.path.exists(final_filepath) else None
            sub_path = self._find_sidecar_subtitle(output_dir, sidecar_base_name) if wants_subtitles else None

            if final_filepath.lower().endswith(self._IMAGE_PAYLOAD_EXTENSIONS) and os.path.exists(final_filepath):
                file_packages.append({
                    "video": None,
                    "thumbnail": vid_path,
                    "subtitle": None
                })
            elif final_filepath.lower().endswith(('.srt', '.vtt', '.ass', '.ssa', '.sub', '.ttml')) and os.path.exists(final_filepath):
                file_packages.append({
                    "video": None,
                    "thumbnail": None,
                    "subtitle": vid_path
                })
            else:
                # Si ni el video ni la miniatura ni el subtitulo existen, ignoramos
                if vid_path or expected_thumb_path or sub_path:
                    file_packages.append({
                        "video": vid_path,
                        "thumbnail": expected_thumb_path,
                        "subtitle": sub_path
                    })
                
        if not file_packages:
            return

        if is_fragmented:
            # Todos los fragmentos comparten una sola miniatura, así que solo el primer
            # paquete la lleva. Dentro de un mismo lote el panel de Adobe ya deduplica
            # (importBatchToProject arma un Set), pero DaVinci importa cada ruta que
            # recibe, y entre envíos sucesivos (fragmentos recodificados, que salen de
            # uno en uno) no deduplica nadie.
            for pkg in file_packages:
                thumb = pkg.get("thumbnail")
                if thumb and self._thumbnail_already_sent(thumb):
                    pkg["thumbnail"] = None

        if is_fragmented and len(file_packages) > 1:
            batch_key = tuple(sorted(pkg.get("video") or "" for pkg in file_packages))
            if self._batch_already_sent(batch_key):
                return

        if len(file_packages) == 1:
            logger.info(f"[EditorManager] Paquete listo para enviar: {file_packages[0]}")
            self.send_file(file_packages[0])
        else:
            # Se listan los paquetes igual que en el envío individual: sin esto, un lote
            # que sale de la app pero no aparece en el editor no dejaba forma de saber
            # desde el log si el problema era lo que se mandó o lo que hizo el panel.
            logger.info(f"[EditorManager] Lote de {len(file_packages)} archivos (fragmentos) listos para enviar: {file_packages}")
            self.send_batch(file_packages)
