# src/gui/tabs/editing_media/editing_media_freesound.py
from PySide6.QtCore import QCoreApplication
import os
from PySide6.QtCore import Qt, QThread, Signal, QSize
from PySide6.QtWidgets import QMessageBox
from core.logger.logger_manager import logger
from core.tabs.editing_media.editing_media_logic import resolve_filter_type
from gui.tabs.editing_media.editing_media_icons import get_svg_icon

class WebSourceSearchThread(QThread):
    """Hilo secundario para buscar en cualquier origen web (Freesound, Wikimedia, ...) sin
    congelar la interfaz. Delega el mapeo de resultados al WebSourceProvider correspondiente."""
    finished_search = Signal(dict)
    error_search = Signal(str)

    def __init__(self, provider, query, page=1, filters=None, parent=None):
        super().__init__(parent)
        self.provider = provider
        self.query = query
        self.page = page
        self.filters = filters or {}

    def run(self):
        try:
            results = self.provider.search(self.query, page=self.page, **self.filters)
            self.finished_search.emit(results)
        except Exception as e:
            self.error_search.emit(str(e))

class WebSourceDownloadThread(QThread):
    """Hilo secundario para descargar el archivo ORIGINAL/en alta calidad de un medio web,
    delegando en el WebSourceProvider correspondiente (Freesound requiere OAuth2, Wikimedia no)."""
    progress = Signal(int)
    finished = Signal(bool, str)  # (success, ruta_final_resuelta)
    error = Signal(str)

    def __init__(self, provider, item_data, dest_dir, fallback_name, parent=None):
        super().__init__(parent)
        self.provider = provider
        self.item_data = item_data
        self.dest_dir = dest_dir
        self.fallback_name = fallback_name

    def run(self):
        try:
            resolved_path = self.provider.download(
                self.item_data, self.dest_dir, self.fallback_name,
                progress_callback=self.progress.emit
            )
            self.finished.emit(True, resolved_path)
        except Exception as e:
            self.error.emit(str(e))


class FreesoundMixin:
    """Mixin que maneja la búsqueda y descarga remota de Freesound, así como la autenticación OAuth2."""

    def _resolve_web_dest_path(self, item_data: dict) -> str:
        """Calcula la ruta local destino (carpeta de etiqueta seleccionada, o la carpeta de
        descargas por defecto configurada en Ajustes, o ~/Downloads) para un medio web,
        sin importar el origen (Freesound, Wikimedia, ...)."""
        name = item_data["nombre"]
        selected_label_name = item_data.get("selected_label")
        from core.utils.config_manager import get_config
        config = get_config()
        labels = config.get("labels", [])
        matched_label = next((l for l in labels if l.get("name") == selected_label_name), None) if selected_label_name else None

        if matched_label and matched_label.get("path"):
            downloads_dir = matched_label["path"]
        else:
            custom_dir = config.get("default_web_download_dir")
            downloads_dir = custom_dir if custom_dir and os.path.isdir(custom_dir) else os.path.expanduser("~/Downloads")

        os.makedirs(downloads_dir, exist_ok=True)
        clean_name = "".join(c for c in name if c.isalnum() or c in (".", "_", " ", "-")).strip()
        return os.path.join(downloads_dir, clean_name).replace("\\", "/")

    def _start_high_quality_download(self, item_data: dict, on_success, on_error):
        """
        Descarga silenciosamente (sin diálogo modal) el archivo ORIGINAL/en alta calidad de un
        medio remoto, delegando en el WebSourceProvider del origen del ítem (Freesound requiere
        OAuth2; Wikimedia no). Llama on_success(dest_path) o on_error(mensaje).
        """
        source_id = item_data.get("source_id")
        provider = getattr(self, "web_providers", {}).get(source_id) if source_id else None
        if provider is None:
            msg = QCoreApplication.translate("FreesoundMixin", "No se pudo determinar el origen del medio web.")
            logger.error(f"[EditingMedia] {msg} ('{item_data.get('nombre')}')")
            on_error(msg)
            return

        if provider.requires_auth and not provider.is_authenticated():
            msg = QCoreApplication.translate("FreesoundMixin", "Debes iniciar sesión con {0} para descargar el archivo original en alta calidad.").format(provider.display_name)
            logger.error(f"[EditingMedia] {msg} ('{item_data.get('nombre')}')")
            on_error(msg)
            return

        fallback_path = self._resolve_web_dest_path(item_data)
        dest_dir = os.path.dirname(fallback_path)
        fallback_name = os.path.basename(fallback_path)

        logger.info(f"[EditingMedia] Descargando archivo original de {provider.display_name} '{item_data.get('nombre')}' -> {dest_dir}")

        thread = WebSourceDownloadThread(provider, item_data, dest_dir, fallback_name, parent=self)
        if not hasattr(self, "_hq_download_threads"):
            self._hq_download_threads = []
        self._hq_download_threads.append(thread)

        def _cleanup():
            if thread in self._hq_download_threads:
                self._hq_download_threads.remove(thread)

        def _on_finished(success, resolved_path):
            _cleanup()
            if not success or not resolved_path:
                logger.error(f"[EditingMedia] La descarga en alta calidad de '{item_data.get('nombre')}' no tuvo éxito.")
                on_error(QCoreApplication.translate("FreesoundMixin", "La descarga no tuvo éxito."))
                return

            item_data["dest_path"] = resolved_path
            if hasattr(self, "media_model"):
                idx = self.media_model.find_item_index_by_path(item_data.get("ruta"))
                if idx.isValid():
                    self.media_model.dataChanged.emit(idx, idx, [])
            if hasattr(self, "controller"):
                self.controller.add_to_downloaded_collection(resolved_path)

            logger.info(f"[EditingMedia] Descarga en alta calidad completada: {resolved_path}")
            on_success(resolved_path)

        def _on_error(err):
            _cleanup()
            logger.error(f"[EditingMedia] Error descargando '{item_data.get('nombre')}' en alta calidad: {err}")
            on_error(err)

        thread.finished.connect(_on_finished)
        thread.error.connect(_on_error)
        thread.start()

    def ensure_hq_download_blocking(self, item_data: dict, timeout_ms=10000):
        """
        Garantiza que el archivo original en alta calidad de Freesound esté descargado
        en disco antes de iniciar un arrastre nativo hacia otra app (Premiere/DaVinci/Explorador).
        Si aún no se ha descargado, bloquea limpiamente con un loop de eventos controlado.
        """
        if not item_data or not isinstance(item_data, dict):
            return None

        dest = item_data.get("dest_path")
        if dest and os.path.exists(dest):
            return dest

        if getattr(self, "_in_hq_drag_download", False):
            return None
        self._in_hq_drag_download = True

        try:
            source_id = item_data.get("source_id")
            provider = getattr(self, "web_providers", {}).get(source_id) if source_id else None

            if provider is not None and provider.requires_auth and not provider.is_authenticated():
                # Sin sesión no hay forma de bajar el original (ej. Freesound sin login): como
                # último recurso, usar la previsualización ya cacheada en disco si existe.
                if provider.id == "freesound":
                    from core.tabs.editing_media.freesound_preview_cache import FreesoundPreviewCacheManager
                    cached = FreesoundPreviewCacheManager.get_instance().get_cached_path(item_data.get("ruta", ""))
                    if cached and os.path.exists(cached):
                        item_data["dest_path"] = cached
                        return cached
                return None

            from PySide6.QtCore import QEventLoop, QTimer, Qt
            from PySide6.QtWidgets import QApplication

            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                loop = QEventLoop()
                timer = QTimer(self)
                timer.setSingleShot(True)
                timer.timeout.connect(loop.quit)
                timer.start(timeout_ms)

                def _on_done(resolved_p):
                    if timer.isActive():
                        timer.stop()
                    if loop.isRunning():
                        loop.quit()

                self._start_high_quality_download(
                    item_data,
                    on_success=lambda p: _on_done(p),
                    on_error=lambda e: _on_done(None)
                )

                loop.exec()
            finally:
                QApplication.restoreOverrideCursor()

            res_path = item_data.get("dest_path")
            if res_path and os.path.exists(res_path):
                return res_path

            if provider is not None and provider.id == "freesound":
                from core.tabs.editing_media.freesound_preview_cache import FreesoundPreviewCacheManager
                cached = FreesoundPreviewCacheManager.get_instance().get_cached_path(item_data.get("ruta", ""))
                if cached and os.path.exists(cached):
                    item_data["dest_path"] = cached
                    return cached

            return None
        finally:
            self._in_hq_drag_download = False

    def _update_media_input_changed(self, text):
        if hasattr(self, "search_spinner"):
            self.search_spinner.start()

        selected = self.tree_folders.currentItem()
        is_online = False
        if selected:
            data = selected.data(0, Qt.UserRole)
            if data and data.get("tipo") == "web_source":
                is_online = True

        if is_online:
            self.current_page = 1
            self.online_results = []
            self.search_timer.start(600)
        else:
            if hasattr(self, "local_search_timer"):
                self.local_search_timer.start(250)
            else:
                self._apply_active_filters_fast()
                if hasattr(self, "search_spinner"):
                    self.search_spinner.stop()

    def _update_freesound_login_button(self):
        """Actualiza el icono y tooltip del botón de login de Freesound según el estado de autenticación."""
        if not hasattr(self, "btn_freesound_login"):
            return
        self.btn_freesound_login.setIconSize(QSize(18, 18))
        if self.controller.is_freesound_authenticated:
            username = self.controller.freesound_username or "usuario"
            self.btn_freesound_login.setIcon(get_svg_icon("person.svg"))
            self.btn_freesound_login.setToolTip(QCoreApplication.translate("FreesoundMixin", "Conectado como: {0} (clic para cerrar sesión)").format(username))
        else:
            self.btn_freesound_login.setIcon(get_svg_icon("login.svg"))
            self.btn_freesound_login.setToolTip(QCoreApplication.translate("FreesoundMixin", "Iniciar sesión con Freesound"))

    def _on_freesound_login_clicked(self):
        """Maneja el clic en el botón de login/logout de Freesound."""
        if self.controller.is_freesound_authenticated:
            # Ya autenticado → preguntar si desea cerrar sesión
            reply = QMessageBox.question(
                self,
                QCoreApplication.translate("FreesoundMixin", "Cerrar Sesión"),
                QCoreApplication.translate("FreesoundMixin", "¿Desea cerrar la sesión de Freesound ({0})?").format(self.controller.freesound_username),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.controller.clear_freesound_auth()
                self._update_freesound_login_button()
                self.online_results = []
                self.current_page = 1
                self._update_media_list()
        else:
            # No autenticado → iniciar flujo OAuth2
            self._start_freesound_oauth()

    def _start_freesound_oauth(self):
        """Inicia el flujo OAuth2 con Freesound."""
        from core.tabs.editing_media.freesound_auth import FreesoundAuth
        
        self._oauth_handler = FreesoundAuth()
        self._oauth_handler.signals.auth_success.connect(self._on_oauth_success)
        self._oauth_handler.signals.auth_error.connect(self._on_oauth_error)
        self._oauth_handler.start_oauth_flow()
        
        # Mostrar feedback visual al usuario
        QMessageBox.information(
            self,
            QCoreApplication.translate("FreesoundMixin", "Iniciar Sesión en Freesound"),
            QCoreApplication.translate("FreesoundMixin", "Se ha abierto tu navegador para iniciar sesión en Freesound.\n\n"
                    "Inicia sesión y autoriza la aplicación. "
                    "Esta ventana se actualizará automáticamente cuando completes el proceso.")
        )

    def _on_oauth_success(self, auth_data: dict):
        """Callback cuando la autenticación OAuth2 es exitosa."""
        self.controller.freesound_auth.update(auth_data)
        self.controller.save_data()
        self._update_freesound_login_button()
        self.current_page = 1
        self.online_results = []
        self._exec_online_search()
        logger.info(f"EditingMediaTab: Autenticación OAuth2 exitosa para '{auth_data.get('username', '')}'")

    def _on_oauth_error(self, error_msg: str):
        """Callback cuando la autenticación OAuth2 falla."""
        logger.error(f"EditingMediaTab: Error OAuth2: {error_msg}")
        QMessageBox.warning(
            self,
            QCoreApplication.translate("FreesoundMixin", "Error de Autenticación"),
            QCoreApplication.translate("FreesoundMixin", "No se pudo completar la autenticación con Freesound:\n{0}").format(error_msg)
        )

    def _prompt_freesound_login_if_needed(self, item_data: dict) -> bool:
        """
        Si item_data representa un medio de un origen web que requiere sesión (hoy, Freesound)
        y todavía no está descargado ni el usuario ha iniciado sesión, muestra un diálogo
        interactivo ofreciendo iniciar sesión. Orígenes que no requieren auth (ej. Wikimedia)
        nunca disparan este diálogo.
        Retorna True si el usuario NO está autenticado (y la acción debe detenerse).
        """
        if not item_data or not isinstance(item_data, dict):
            return False

        source_id = item_data.get("source_id")
        provider = getattr(self, "web_providers", {}).get(source_id) if source_id else None
        if provider is None or not provider.requires_auth:
            return False

        path = item_data.get("ruta", "")
        is_remote = item_data.get("es_remoto", False) or (isinstance(path, str) and (path.startswith("http://") or path.startswith("https://")))
        dest = item_data.get("dest_path")
        already_downloaded = bool(dest and os.path.exists(dest))

        if is_remote and not already_downloaded:
            if not provider.is_authenticated():
                msg_box = QMessageBox(self)
                msg_box.setIcon(QMessageBox.Information)
                msg_box.setWindowTitle(QCoreApplication.translate("FreesoundMixin", "Sesión de Freesound requerida"))
                msg_box.setText(QCoreApplication.translate("FreesoundMixin", "Para acceder o descargar este medio web de Freesound debes iniciar sesión."))
                msg_box.setInformativeText(QCoreApplication.translate("FreesoundMixin", "¿Deseas iniciar sesión en Freesound ahora?"))
                btn_login = msg_box.addButton(QCoreApplication.translate("FreesoundMixin", "Iniciar Sesión"), QMessageBox.AcceptRole)
                msg_box.addButton(QCoreApplication.translate("FreesoundMixin", "Cancelar"), QMessageBox.RejectRole)
                msg_box.exec()
                if msg_box.clickedButton() == btn_login:
                    if hasattr(self, "_start_freesound_oauth"):
                        self._start_freesound_oauth()
                return True
        return False

    def _exec_online_search(self):
        provider = getattr(self, "web_providers", {}).get(getattr(self, "active_web_source_id", None))
        if provider is None:
            return

        query = self.search_input.text().strip()
        filters = {}

        if getattr(provider, "license_filter_options", None):
            license_type = self.web_license_combo.currentData() if hasattr(self, "web_license_combo") else None
            filters["license_type"] = license_type

        # En orígenes con varios tipos de medio (ej. Wikimedia), el filtro de tipo (botones
        # Imágenes/Videos/Audios) se pasa al provider para que lo aplique server-side — ver
        # nota en _on_filter_button_clicked sobre por qué no alcanza con filtrar la página ya
        # traída client-side.
        if len(getattr(provider, "supported_media_types", set())) > 1:
            media_type = resolve_filter_type(getattr(self, "active_filter", "Todos"))
            if media_type:
                filters["media_type"] = media_type

        if provider.id == "freesound":
            sort_order = None
            duration_max = None
            if not query:
                # Si el cuadro de búsqueda está vacío, cargar automáticamente sonidos recientes
                # ("Más nuevos") y limitar a audios menores a 5 minutos (300s) para mostrar solo
                # efectos/audios cortos.
                sort_order = "Más nuevos"
                duration_max = 300
            filters["sort_order"] = sort_order
            filters["duration_max"] = duration_max

        if not hasattr(self, "_active_web_search_threads"):
            self._active_web_search_threads = set()

        if hasattr(self, "online_search_thread") and self.online_search_thread and self.online_search_thread.isRunning():
            old_thread = self.online_search_thread
            try:
                old_thread.finished_search.disconnect()
            except Exception:
                pass
            try:
                old_thread.error_search.disconnect()
            except Exception:
                pass
            self._active_web_search_threads.add(old_thread)
            old_thread.finished.connect(lambda t=old_thread: self._active_web_search_threads.discard(t))

        if hasattr(self, "search_spinner"):
            self.search_spinner.start()

        self.online_search_thread = WebSourceSearchThread(
            provider,
            query,
            page=self.current_page,
            filters=filters,
            parent=self
        )
        self.online_search_thread.finished_search.connect(self._on_online_search_success)
        self.online_search_thread.error_search.connect(self._on_online_search_error)

        new_thread = self.online_search_thread
        self._active_web_search_threads.add(new_thread)
        new_thread.finished.connect(lambda t=new_thread: self._active_web_search_threads.discard(t))
        new_thread.start()

    def _on_search_timer_timeout(self):
        """Callback del temporizador de búsqueda diferida en el origen web activo."""
        self._exec_online_search()

    def _on_online_search_success(self, data):
        self.loading_next_page = False
        if hasattr(self, "search_spinner"):
            self.search_spinner.stop()

        if self.current_page == 1:
            self.online_results = []

        self.online_results.extend(data.get("results", []))
        self._update_media_list()

    def _on_online_search_error(self, error_msg):
        self.loading_next_page = False
        if hasattr(self, "search_spinner"):
            self.search_spinner.stop()
        logger.error(f"EditingMediaTab: Error en búsqueda online: {error_msg}")
        if self.current_page == 1:
            self.online_results = []
        self._update_media_list()
        provider = getattr(self, "web_providers", {}).get(getattr(self, "active_web_source_id", None))
        source_name = provider.display_name if provider else QCoreApplication.translate("FreesoundMixin", "el origen web")
        QMessageBox.warning(self, QCoreApplication.translate("FreesoundMixin", "Error de Búsqueda"), QCoreApplication.translate("FreesoundMixin", "No se pudo completar la búsqueda en {0}:\n{1}").format(source_name, error_msg))

    def _on_list_scroll(self, value):
        selected = self.tree_folders.currentItem()
        if selected:
            data = selected.data(0, Qt.UserRole)
            if data and data.get("tipo") == "web_source":
                scroll_widget = self.media_table if getattr(self, "view_mode", "grid") == "list" and hasattr(self, "media_table") else self.media_list
                max_scroll = scroll_widget.verticalScrollBar().maximum()
                # Si llega casi al final y no hay búsqueda activa, cargar la siguiente página
                if value >= max_scroll - 15 and max_scroll > 0:
                    if not self.loading_next_page:
                        if hasattr(self, "online_search_thread") and self.online_search_thread and self.online_search_thread.isRunning():
                            return
                        # Recordar la posición de scroll actual para restaurarla tras cargar la
                        # siguiente página, en vez de dejar que el reset del modelo salte al tope.
                        self._pending_scroll_restore = value
                        self.loading_next_page = True
                        self.current_page += 1
                        self._exec_online_search()
                return



    def _on_download_clicked(self):
        item_data = self._get_current_media_data() if hasattr(self, "_get_current_media_data") else None
        if not item_data or not item_data.get("es_remoto"):
            return

        if self._prompt_freesound_login_if_needed(item_data):
            return

        source_id = item_data.get("source_id")
        provider = getattr(self, "web_providers", {}).get(source_id) if source_id else None
        if provider is None:
            QMessageBox.warning(self, QCoreApplication.translate("FreesoundMixin", "Error"), QCoreApplication.translate("FreesoundMixin", "No se pudo determinar el origen del medio web."))
            return

        fallback_path = self._resolve_web_dest_path(item_data)
        dest_dir = os.path.dirname(fallback_path)
        fallback_name = os.path.basename(fallback_path)

        from PySide6.QtWidgets import QProgressDialog
        progress_dialog = QProgressDialog(QCoreApplication.translate("FreesoundMixin", "Descargando medio original de {0}...").format(provider.display_name), QCoreApplication.translate("FreesoundMixin", "Cancelar"), 0, 100, self)
        progress_dialog.setWindowModality(Qt.WindowModal)
        progress_dialog.setValue(0)
        progress_dialog.show()

        self.dl_thread = WebSourceDownloadThread(provider, item_data, dest_dir, fallback_name, parent=self)
        self.dl_thread.progress.connect(progress_dialog.setValue)

        def on_finished(success, resolved_path):
            progress_dialog.close()
            if success and resolved_path:
                item_data["dest_path"] = resolved_path
                idx = self.media_model.find_item_index_by_path(item_data["ruta"])
                if idx.isValid():
                    self.media_model.dataChanged.emit(idx, idx, [])

                # Registrar en la colección 'Descargados'
                self.controller.add_to_downloaded_collection(resolved_path)

                # Actualizar botones
                self.btn_reveal.setVisible(True)
                self.btn_reveal.setEnabled(True)
                if hasattr(self, "combo_tags"):
                    self.combo_tags.setVisible(False)

                self.btn_download.setVisible(True)
                self.btn_download.setEnabled(False)
                self.btn_download.setToolTip(QCoreApplication.translate("FreesoundMixin", "En Disco"))
                self.metadata_labels["ruta"].setText(resolved_path)

                logger.info(f"[EditingMedia] Descarga manual del original en alta calidad completada: {resolved_path}")
                QMessageBox.information(self, QCoreApplication.translate("FreesoundMixin", "Descarga Completada"), QCoreApplication.translate("FreesoundMixin", "El medio original ha sido guardado exitosamente en:\n{0}").format(resolved_path))
            else:
                logger.error(f"[EditingMedia] La descarga manual del original de '{item_data.get('nombre')}' no tuvo éxito.")

        def on_error(err):
            progress_dialog.close()
            logger.error(f"[EditingMedia] Error en descarga manual del original de '{item_data.get('nombre')}': {err}")
            QMessageBox.warning(self, QCoreApplication.translate("FreesoundMixin", "Error de Descarga"), QCoreApplication.translate("FreesoundMixin", "No se pudo descargar el archivo original:\n{0}").format(err))

        self.dl_thread.finished.connect(on_finished)
        self.dl_thread.error.connect(on_error)

        progress_dialog.canceled.connect(self.dl_thread.terminate)
        self.dl_thread.start()

