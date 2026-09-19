# src/gui/tabs/editing_media/editing_media_tree.py
from PySide6.QtCore import QCoreApplication
import os
from PySide6.QtCore import Qt, QSize, QRectF
from PySide6.QtGui import QIcon, QColor, QFont, QPixmap, QPainter
from PySide6.QtWidgets import (
    QTreeWidgetItem,
    QListWidgetItem,
    QFileDialog,
    QMessageBox,
    QInputDialog,
    QMenu
)
from gui.styles import get_theme_token
from core.logger.logger_manager import logger
from gui.tabs.editing_media.editing_media_icons import (
    get_colored_svg_icon,
    get_colored_folder_icon,
    get_svg_icon,
    get_contrast_svg_icon,
    get_folder_icon,
    get_placeholder_thumbnail_icon
)

from core.tabs.editing_media.folder_color_manager import get_item_color, set_item_color, get_random_label_color
from core.tabs.editing_media.editing_media_logic import VALID_EXTS, resolve_filter_type
from core.tabs.editing_media.thumbnail_cache_manager import ThumbnailCacheManager



class TreeListMixin:
    """Mixin que maneja el árbol de carpetas, lista de medios y menús contextuales."""

    def _format_collection_title(self, col_name: str) -> str:
        """Traduce títulos de colecciones predeterminadas para la UI sin tocar la clave interna."""
        if col_name == "Descargados":
            return QCoreApplication.translate("TreeListMixin", "Descargados")
        elif col_name == "Subclips":
            return QCoreApplication.translate("TreeListMixin", "Subclips")
        elif col_name == "Favoritos":
            return QCoreApplication.translate("TreeListMixin", "Favoritos")
        return col_name

    def _web_source_needs_auth(self, source_id) -> bool:
        """True si el origen web requiere sesión y todavía no la hay (ej. Freesound sin
        login) -- evita disparar una búsqueda que va a fallar con un error de token y
        mostrar un aviso redundante con la página grande de login (ver _update_media_list)."""
        provider = getattr(self, "web_providers", {}).get(source_id)
        return provider is not None and provider.requires_auth and not provider.is_authenticated()

    # ── Población y Control de Vistas del Árbol ──────────────────────────────
    def _update_tree_view(self):
        """Reconstruye el árbol de carpetas lógicas y físicas de forma jerárquica con Lazy Loading."""
        selected = self.tree_folders.currentItem()
        selected_data = None
        if selected:
            selected_data = selected.data(0, Qt.UserRole)

        self.tree_folders.clear()
        
        # 1. Nodo Raíz de Medios Web (agrupa los orígenes remotos: Freesound, Wikimedia, ...)
        self.web_root = QTreeWidgetItem(self.tree_folders, [QCoreApplication.translate("TreeListMixin", "Medios Web")])
        self.web_root.setIcon(0, get_svg_icon("travel_explore.svg"))
        self.web_root.setData(0, Qt.UserRole, {"tipo": "root_web"})
        self.web_root.setExpanded(True)

        for source_id, provider in getattr(self, "web_providers", {}).items():
            source_item = QTreeWidgetItem(self.web_root, [provider.display_name])
            source_item.setIcon(0, get_svg_icon("travel_explore.svg"))
            source_item.setData(0, Qt.UserRole, {"tipo": "web_source", "source_id": source_id})

        # 2. Nodo Raíz de Directorios Físicos
        self.physical_root = QTreeWidgetItem(self.tree_folders, [QCoreApplication.translate("TreeListMixin", "Directorios")])
        self.physical_root.setIcon(0, get_folder_icon())
        self.physical_root.setData(0, Qt.UserRole, {"tipo": "root_physical"})
        self.physical_root.setExpanded(True)

        for folder in self.controller.indexed_folders:
            folder_name = os.path.basename(folder) or folder
            item = QTreeWidgetItem(self.physical_root, [folder_name])
            color = get_item_color(f"folder:{folder}")
            if color:
                item.setIcon(0, get_colored_folder_icon(color))
            else:
                item.setIcon(0, get_folder_icon())
            item.setData(0, Qt.UserRole, {"tipo": "folder", "ruta": folder})
            item.setExpanded(True)
            self._populate_folder_children(item, folder)

        # 2b. Carpeta "Default": colección virtual (sin carpeta física real detrás) donde
        # cae por defecto un archivo indexado individualmente (ver dropEvent más abajo).
        # Se muestra aquí, dentro de Directorios, aunque técnicamente vive en
        # self.controller.collections igual que las de Colecciones -- por eso se excluye
        # explícitamente del loop de Colecciones unas líneas más abajo, para no duplicarla.
        default_item = QTreeWidgetItem(self.physical_root, ["Default"])
        default_item.setIcon(0, get_folder_icon())
        default_item.setData(0, Qt.UserRole, {"tipo": "collection", "nombre": "Default"})

        # 3. Nodo Raíz de Colecciones Virtuales
        self.virtual_root = QTreeWidgetItem(self.tree_folders, [QCoreApplication.translate("TreeListMixin", "Colecciones")])
        self.virtual_root.setIcon(0, get_svg_icon("star.svg"))
        self.virtual_root.setData(0, Qt.UserRole, {"tipo": "root_virtual"})
        self.virtual_root.setExpanded(True)

        for col_name in self.controller.collections.keys():
            if col_name == "Default":
                continue  # Ya se muestra dentro de Directorios, ver más arriba.
            item = QTreeWidgetItem(self.virtual_root, [self._format_collection_title(col_name)])
            color = get_item_color(f"col:{col_name}")
            if col_name == "Descargados":
                accent_color = get_theme_token("acento_primario", "#B9E640")
                item.setIcon(0, get_colored_svg_icon("download.svg", color or accent_color))
            elif col_name == "Subclips":
                accent_color = get_theme_token("acento_primario", "#B9E640")
                item.setIcon(0, get_colored_svg_icon("content_cut.svg", color or accent_color))
            elif col_name == "Favoritos":
                accent_color = get_theme_token("acento_primario", "#B9E640")
                item.setIcon(0, get_colored_svg_icon("star.svg", color or accent_color))
            elif color:
                item.setIcon(0, get_colored_svg_icon("star.svg", color))
            else:
                item.setIcon(0, get_svg_icon("star.svg"))
            item.setData(0, Qt.UserRole, {"tipo": "collection", "nombre": col_name})


        # Restaurar selección anterior guardada en sesión o seleccionar Directorios por defecto (primera vez)
        saved_target = getattr(self.controller, "last_selected_tree_node", None)
        target = selected_data or saved_target
        restored = False
        if target:
            restored = self._restore_tree_selection(self.tree_folders.invisibleRootItem(), target)

        if not restored:
            self.tree_folders.setCurrentItem(self.physical_root)

        # Restaurar estado de botones
        self._update_button_states()

    def _restore_tree_selection(self, parent_item, target_data):
        """Busca y restaura recursivamente la selección del árbol tras un refresco."""
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            child_data = child.data(0, Qt.UserRole)
            if child_data:
                match = False
                tipo = child_data.get("tipo")
                target_tipo = target_data.get("tipo")
                
                if tipo == target_tipo:
                    if tipo in ["folder", "subfolder"] and child_data.get("ruta") == target_data.get("ruta"):
                        match = True
                    elif tipo == "collection" and child_data.get("nombre") == target_data.get("nombre"):
                        match = True
                    elif tipo == "web_source" and child_data.get("source_id") == target_data.get("source_id"):
                        match = True
                    elif tipo in ["root_physical", "root_virtual", "root_web"]:
                        match = True
                
                if match:
                    self.tree_folders.setCurrentItem(child)
                    return True
            
            # Buscar recursivamente en hijos
            if self._restore_tree_selection(child, target_data):
                return True
        return False

    def _on_tree_item_expanded(self, item):
        """Carga bajo demanda (Lazy Loading) las subcarpetas del nodo expandido."""
        data = item.data(0, Qt.UserRole)
        if not data or data.get("tipo") not in ["folder", "subfolder"]:
            return

        # Si el primer hijo es un placeholder/dummy, poblar subcarpetas reales
        if item.childCount() == 1 and item.child(0).data(0, Qt.UserRole) == {"tipo": "dummy"}:
            item.removeChild(item.child(0))
            folder_path = data.get("ruta")
            self._populate_folder_children(item, folder_path)

    def _populate_folder_children(self, parent_item, folder_path):
        """Puebla solo las subcarpetas directas (1 nivel) de forma eficiente."""
        try:
            if not (os.path.exists(folder_path) and os.path.isdir(folder_path)):
                return

            subdirs = []
            with os.scandir(folder_path) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=False):
                        subdirs.append((entry.name, entry.path.replace("\\", "/")))

            subdirs.sort(key=lambda x: x[0].lower())

            for name, normalized_path in subdirs:
                child = QTreeWidgetItem(parent_item, [name])
                color = get_item_color(f"folder:{normalized_path}")
                if color:
                    child.setIcon(0, get_colored_folder_icon(color))
                else:
                    child.setIcon(0, get_folder_icon())
                child.setData(0, Qt.UserRole, {"tipo": "subfolder", "ruta": normalized_path})
                
                # Si esta subcarpeta tiene a su vez subcarpetas, añadir placeholder para expandir
                if self._has_subdirs(normalized_path):
                    dummy = QTreeWidgetItem(child, ["..."])
                    dummy.setData(0, Qt.UserRole, {"tipo": "dummy"})
        except Exception as e:
            logger.debug(f"EditingMediaTab: Error al buscar subcarpetas en {folder_path}: {e}")

    def _has_subdirs(self, folder_path: str) -> bool:
        """Comprueba rápidamente (O(1)) si una carpeta contiene al menos una subcarpeta."""
        try:
            with os.scandir(folder_path) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=False):
                        return True
        except Exception:
            pass
        return False

    def _update_button_states(self):
        selected = self.tree_folders.currentItem()
        is_online = False
        is_freesound_source = False
        source_id = None
        provider = None
        if selected:
            data = selected.data(0, Qt.UserRole)
            if data:
                tipo = data.get("tipo")
                if tipo == "web_source":
                    is_online = True
                    source_id = data.get("source_id")
                    provider = getattr(self, "web_providers", {}).get(source_id)
                    is_freesound_source = (source_id == "freesound")

        # Deshabilitar botón de indexar carpeta en modo online
        if hasattr(self, "btn_add_folder"):
            self.btn_add_folder.setEnabled(not is_online)

        # El login es un control propio de Freesound (único origen con auth por ahora); el
        # filtro de licencia en cambio aparece para cualquier origen que declare
        # license_filter_options (hoy Freesound y Wikimedia).
        if hasattr(self, "btn_freesound_login"):
            self.btn_freesound_login.setVisible(is_freesound_source)

        license_options = list(getattr(provider, "license_filter_options", []) or []) if provider else []
        if hasattr(self, "license_container"):
            self.license_container.setVisible(bool(license_options))
        if hasattr(self, "web_license_combo") and source_id != getattr(self, "_license_combo_source_id", None):
            self._license_combo_source_id = source_id
            self.web_license_combo.blockSignals(True)
            self.web_license_combo.clear()
            self.web_license_combo.addItem(QCoreApplication.translate("TreeListMixin", "Cualquiera"), "Cualquiera")
            for value, label in license_options:
                self.web_license_combo.addItem(QCoreApplication.translate("TreeListMixin", label), value)
            self.web_license_combo.blockSignals(False)

        # Ocultar columnas innecesarias para medios locales y actualizar headers
        if hasattr(self, "media_model"):
            self.media_model.set_online_mode(is_online)
        if hasattr(self, "media_table"):
            self.media_table.setColumnHidden(2, False) # Tamaño (Local) / Descripción (Web)
            self.media_table.setColumnHidden(3, False) # Tipo (Local) / Licencia (Web)
            self.media_table.setColumnHidden(4, False) # Modificado (Local) / Duración (Web)
            self.media_table.setColumnHidden(5, False) # Ruta (Local) / Origen (Web)
            self.media_table.setColumnHidden(6, not is_online) # Tipo de Archivo (Web)
            self.media_table.setColumnHidden(7, not is_online) # Detalles (Web)

        # Si el origen web activo solo soporta un tipo de medio (ej. Freesound = solo audio),
        # forzar ese filtro y deshabilitar los demás, igual que antes. Si soporta varios tipos
        # (ej. Wikimedia = imagen/audio/video), dejar los 4 filtros habilitados.
        was_forced = getattr(self, "_filter_forced_by_online", False)
        forced_type = None
        if is_online and provider and len(provider.supported_media_types) == 1:
            forced_type = next(iter(provider.supported_media_types))

        if forced_type:
            for btn in self.filter_buttons:
                key = btn.property("filter_key") or btn.text()
                if resolve_filter_type(key) == forced_type:
                    btn.setChecked(True)
                    btn.setEnabled(True)
                    self.active_filter = key
                else:
                    btn.setChecked(False)
                    btn.setEnabled(False)
            self._filter_forced_by_online = True
        else:
            for btn in self.filter_buttons:
                btn.setEnabled(True)
            # Si un filtro único quedó forzado por haber estado en un origen de un solo tipo
            # (ej. Freesound), al salir de ahí se restablece a "Todos" (dejarlo forzado sería
            # confuso tanto en medios locales como en un origen web multi-tipo como Wikimedia).
            if was_forced:
                self._filter_forced_by_online = False
                for btn in self.filter_buttons:
                    key = btn.property("filter_key") or btn.text()
                    btn.setChecked(resolve_filter_type(key) is None)
                self.active_filter = "Todos"

    def _get_cached_media_icon(self, icon_name: str, color: str) -> QIcon:
        """Obtiene un icono coloreado desde la cache o lo crea si no existe."""
        cache_key = f"{icon_name}:{color}"
        # Se asume la existencia de self._icon_cache en la clase principal
        if cache_key not in self._icon_cache:
            self._icon_cache[cache_key] = get_colored_svg_icon(icon_name, color)
        return self._icon_cache[cache_key]



    def _update_media_list(self):
        """Refresca la lista central de medios inyectando datos filtrados en el Modelo MVC."""
        # Limpiar la selección anterior si es posible
        target_path = getattr(self, "current_playing_path", None)
        if not target_path:
            target_path = getattr(self, "last_selected_media_path", None)

        def restore_selection():
            restored = False
            if target_path:
                idx = self.media_model.find_item_index_by_path(target_path)
                if idx.isValid():
                    from PySide6.QtCore import QItemSelectionModel
                    # Esta reselección es solo un efecto del refresco de la lista (p.ej. tras
                    # completar una descarga en segundo plano), no una nueva elección del usuario:
                    # evitar que reinicie la reproducción/waveform del ítem ya activo.
                    self._suppress_next_media_click_reset = True
                    # media_table y media_list COMPARTEN el mismo selectionModel (ver
                    # editing_media_view.py: media_list.setSelectionModel(media_table.selectionModel())).
                    # Llamar a .select()/.setCurrentIndex() en ambas vistas por separado dispara
                    # selectionChanged DOS veces sobre el mismo modelo: la primera consumía la
                    # bandera de supresión de arriba, y la segunda emisión (redundante) caía en el
                    # camino de "selección nueva" y reiniciaba la reproducción. Basta con
                    # seleccionar una sola vez; ambas vistas reflejan el resaltado igualmente
                    # porque están conectadas al mismo modelo compartido.
                    selection_model = self.media_table.selectionModel() if hasattr(self, "media_table") else None
                    if selection_model:
                        selection_model.select(idx, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
                        # NoUpdate: solo mover el índice "actual" (para que ambas vistas hagan
                        # scroll-to-visible vía su propio slot currentChanged), sin volver a
                        # tocar la selección, que .select() ya dejó correcta arriba.
                        selection_model.setCurrentIndex(idx, QItemSelectionModel.NoUpdate)
                    restored = True

            # Terminó el refresco (reset del modelo). Si no había nada que restaurar (p.ej.
            # cambiamos de carpeta/colección y el ítem activo ya no existe aquí), aplicar ahora
            # el detener/limpiar que se suprimió mientras el modelo estaba en reset transitorio.
            self._refreshing_media_list = False
            if not restored:
                self._clear_metadata()
                self._stop_audio_playback()

            # Restaurar la posición de scroll previa al refresco (p.ej. "Cargar más" o el scroll
            # infinito de Freesound), en vez de dejar que Qt salte a donde quedó reubicado el
            # ítem reseleccionado.
            pending_scroll = getattr(self, "_pending_scroll_restore", None)
            if pending_scroll is not None:
                self._pending_scroll_restore = None
                scroll_widget = self.media_table if getattr(self, "view_mode", "grid") == "list" and hasattr(self, "media_table") else self.media_list
                if scroll_widget:
                    scroll_widget.verticalScrollBar().setValue(pending_scroll)

        # Detener temporizador de búsqueda anterior si lo hubiera
        if hasattr(self, "_batch_timer") and self._batch_timer and self._batch_timer.isActive():
            self._batch_timer.stop()

        try:
            selected = self.tree_folders.currentItem()
            tipo = None
            data = None
            if selected:
                data = selected.data(0, Qt.UserRole)
                if data:
                    tipo = data.get("tipo")

            # Por defecto mostramos la tabla/cuadrícula normal; la rama "web_source" sin
            # sesión iniciada (cuando el origen la requiere) la reemplaza más abajo por la
            # página de inicio de sesión.
            if hasattr(self, "_restore_media_stack_widget"):
                self._restore_media_stack_widget()

            media_items = []

            if tipo in ["folder", "subfolder"]:
                ruta = data.get("ruta")
                media_items = self.controller.get_media_files_in_folder(ruta)
            elif tipo == "collection":
                nombre = data.get("nombre")
                media_items = self.controller.get_media_files_in_collection(nombre)
            elif tipo == "root_physical":
                media_items = self.controller.get_all_media_files()
            elif tipo == "root_virtual":
                media_items = self.controller.get_all_collections_files()
            elif tipo == "root_web":
                media_items = []
            elif tipo == "web_source":
                # Renderizar resultados del origen web seleccionado (Freesound, Wikimedia, ...)
                source_id = data.get("source_id")
                provider = getattr(self, "web_providers", {}).get(source_id)
                if provider is None:
                    self.media_model.set_data([{"nombre": QCoreApplication.translate("TreeListMixin", "Origen web no disponible."), "tipo": "empty"}])
                    return

                if self._web_source_needs_auth(source_id):
                    if hasattr(self, "media_stack") and hasattr(self, "freesound_login_page"):
                        self.media_stack.setCurrentWidget(self.freesound_login_page)
                    self.media_model.set_data([])
                    return

                if not self.online_results:
                    is_searching = self.online_search_thread and self.online_search_thread.isRunning()
                    msg = QCoreApplication.translate("TreeListMixin", "Buscando en {0}...").format(provider.display_name) if is_searching else QCoreApplication.translate("TreeListMixin", "No se encontraron resultados o la búsqueda falló. Intente de nuevo.")
                    self.media_model.set_data([{"nombre": msg, "tipo": "empty"}])
                    return

                downloaded_list = self.controller.collections.get("Descargados", [])
                from core.utils.config_manager import get_config
                config = get_config()
                custom_dl_dir = config.get("default_web_download_dir")
                user_dl_dir = custom_dl_dir if custom_dl_dir and os.path.isdir(custom_dl_dir) else os.path.expanduser("~/Downloads")
                labels = config.get("labels", [])

                for item in self.online_results:
                    file_name = item.get("nombre", "").strip()
                    is_downloaded = False
                    found_path = None

                    for d_path in downloaded_list:
                        if os.path.basename(d_path).strip().lower() == file_name.lower() and os.path.exists(d_path):
                            is_downloaded = True
                            found_path = d_path
                            break

                    if not is_downloaded:
                        target = os.path.join(user_dl_dir, file_name)
                        if os.path.exists(target):
                            is_downloaded = True
                            found_path = target

                    if not is_downloaded:
                        for lbl in labels:
                            lbl_p = lbl.get("path")
                            if lbl_p and os.path.exists(lbl_p):
                                target = os.path.join(lbl_p, file_name)
                                if os.path.exists(target):
                                    is_downloaded = True
                                    found_path = target
                                    break

                    if is_downloaded and found_path:
                        item["dest_path"] = found_path

                # Filtrar por tipo solo tiene sentido para orígenes que devuelven varios tipos
                # de medio (ej. Wikimedia). Freesound siempre es audio, así que aunque el
                # filtro esté forzado a "Audios" no hace falta filtrar (todo ya es audio).
                active_filter = getattr(self, "active_filter", "Todos")
                target_type = resolve_filter_type(active_filter)
                if target_type is None or len(provider.supported_media_types) <= 1:
                    display_results = self.online_results
                else:
                    display_results = [it for it in self.online_results if it.get("tipo") == target_type]

                if getattr(self, "_pending_scroll_restore", None) is None:
                    scroll_widget = self.media_table if getattr(self, "view_mode", "grid") == "list" and hasattr(self, "media_table") else self.media_list
                    if scroll_widget and hasattr(scroll_widget, "verticalScrollBar"):
                        val = scroll_widget.verticalScrollBar().value()
                        if val > 0:
                            self._pending_scroll_restore = val

                self._refreshing_media_list = True
                self.media_model.set_data(display_results)
                from PySide6.QtCore import QTimer
                QTimer.singleShot(0, restore_selection)
                return

            else:
                media_items = self.controller.get_all_media_files()

            # 1. Pre-filtrado + pre-ordenación, cacheados por contexto (0ms en el
            # camino de caché). "Cargar más" solo cambia _max_display_count -- ni la
            # carpeta, ni el filtro, ni la búsqueda, ni el orden -- así que
            # recalcular el filtrado+ordenado de la carpeta ENTERA en cada click era
            # el costo real de los freezes con carpetas de decenas de miles de
            # archivos. La caché se invalida sola si el contenido en disco
            # realmente cambió: get_media_files_in_folder()/get_all_media_files()
            # (editing_media_logic.py) devuelven la misma lista por referencia
            # mientras no haya un rescaneo real, y abajo se compara esa referencia
            # por identidad (ver comentario ahí sobre por qué no alcanza con id()).
            active_filter = getattr(self, "active_filter", "Todos")
            search_query = self.search_input.text().lower().strip() if hasattr(self, "search_input") else ""
            sort_by = getattr(self, "sort_by", "nombre")
            sort_asc = getattr(self, "sort_ascending", True)
            cache_key = (active_filter, search_query, sort_by, sort_asc)

            # OJO: comparar por identidad (`is`), no por id(media_items) -- id() se
            # puede RECICLAR si el objeto anterior ya fue liberado (p.ej. el []
            # efímero que devuelve get_all_media_files() mientras la indexación
            # async no terminó), y una lista nueva y completamente distinta podría
            # terminar reusando esa misma dirección de memoria y "matchear" por
            # error contra una entrada de caché vieja. Guardar la referencia real en
            # self._filtered_sort_cache_media_items mantiene ese objeto vivo
            # mientras la caché sea válida, así que la comparación por identidad es
            # segura sin ese riesgo.
            if (getattr(self, "_filtered_sort_cache_key", None) == cache_key
                    and getattr(self, "_filtered_sort_cache_media_items", None) is media_items):
                filtered_items = self._filtered_sort_cache
            else:
                target_type = resolve_filter_type(active_filter)
                filtered_items = []
                for item in media_items:
                    item_type = item.get("tipo", "")
                    item_name = item.get("nombre", "").lower()

                    if target_type is not None and item_type != target_type:
                        continue

                    if search_query and search_query not in item_name:
                        continue

                    filtered_items.append(item)

                if filtered_items:
                    def sort_key(item):
                        if sort_by == "nombre":
                            return item.get("nombre", "").lower()
                        elif sort_by in ["mtime", "ctime"]:
                            return item.get(sort_by, 0.0)
                        elif sort_by == "size":
                            return item.get("size_bytes", 0)
                        elif sort_by == "tipo":
                            ext = os.path.splitext(item.get("nombre", ""))[1].lower()
                            if not ext:
                                ext = str(item.get("file_type", item.get("tipo", ""))).lower()
                            return ext
                        elif sort_by == "ruta":
                            return item.get("ruta", "").lower()
                        elif sort_by == "license":
                            return str(item.get("license", "")).lower()
                        elif sort_by == "duration":
                            d = item.get("duration", 0)
                            if isinstance(d, (int, float)): return float(d)
                            if "duración" in item:
                                dur_str = str(item["duración"])
                                if ":" in dur_str:
                                    parts = dur_str.split(":")
                                    if len(parts) == 2:
                                        try: return float(parts[0])*60 + float(parts[1])
                                        except: return 0.0
                            return 0.0
                        return item.get("nombre", "").lower()

                    filtered_items.sort(key=sort_key, reverse=not sort_asc)

                self._filtered_sort_cache_key = cache_key
                self._filtered_sort_cache_media_items = media_items
                self._filtered_sort_cache = filtered_items

            # Si no hay ítems filtrados, mostrar mensaje
            if not filtered_items:
                msg = ""
                if tipo == "collection":
                    nombre = data.get("nombre", "") if data else ""
                    if nombre == "Favoritos":
                        msg = QCoreApplication.translate("TreeListMixin", "Aquí puedes guardar tus medios locales o web para acceder más rápido a ellos ⭐")
                    else:
                        display_name = self._format_collection_title(nombre)
                        msg = QCoreApplication.translate("TreeListMixin", "La colección '{0}' está vacía.\nAñade elementos haciendo clic derecho sobre cualquier medio.").format(display_name)
                elif tipo in ["folder", "subfolder"]:
                    msg = QCoreApplication.translate("TreeListMixin", "Esta carpeta no contiene archivos multimedia.")
                elif tipo == "root_virtual":
                    msg = QCoreApplication.translate("TreeListMixin", "Selecciona o crea una colección a la izquierda para ver sus archivos.")
                elif tipo == "root_web":
                    msg = QCoreApplication.translate("TreeListMixin", "Selecciona un origen de medios web a la izquierda (Freesound, Wikimedia, ...).")
                elif search_query:
                    msg = QCoreApplication.translate("TreeListMixin", "No se encontraron medios que coincidan con '{0}'.").format(search_query)
                elif target_type is not None:
                    display_filter = active_filter
                    for btn in getattr(self, "filter_buttons", []):
                        k = btn.property("filter_key") or btn.text()
                        if resolve_filter_type(k) == target_type:
                            display_filter = btn.text()
                            break
                    msg = QCoreApplication.translate("TreeListMixin", "No hay elementos de tipo '{0}' en esta sección.").format(display_filter)
                else:
                    msg = QCoreApplication.translate("TreeListMixin", "No hay archivos multimedia para mostrar.")

                self.media_model.set_data([{"nombre": msg, "tipo": "empty"}])
                self._applied_display_paths = []
                return

            # 2. Pasar los datos filtrados y ordenados al modelo MVC
            # Opcional: Límite de vista para evitar exceso de RAM
            max_count = getattr(self, "_max_display_count", 999999) # O lo que prefieras
            if len(filtered_items) > max_count:
                display_items = filtered_items[:max_count]
                # Agregamos el item de "Mostrar todo" si cortamos la lista
                display_items.append({"nombre": QCoreApplication.translate("TreeListMixin", "Cargar más"), "tipo": "load_more"})
            else:
                display_items = filtered_items

            # ¿Esto es solo "más página" del mismo listado ya aplicado al modelo
            # (mismo contexto, mismo orden, y ahora hay más ítems al final -- el
            # caso típico de "Cargar más")? Si display_items empieza exactamente
            # igual a lo que ya está en el modelo, insertar solo las filas nuevas en
            # vez de resetear todo -- así no se pierde ni el scroll ni la selección,
            # y no hace falta _pending_scroll_restore para este camino. Cualquier
            # caso que no calce con esto (cambio real de contexto, reducción,
            # reordenamiento) cae al camino de reset de siempre, sin cambios.
            new_paths = [it["ruta"] for it in display_items if "ruta" in it]
            applied = getattr(self, "_applied_display_paths", None)
            can_append = (
                applied is not None
                and len(new_paths) > len(applied)
                and new_paths[:len(applied)] == applied
            )

            if can_append:
                self.media_model.append_items(display_items[len(applied):])
                self._applied_display_paths = new_paths
                # No hay reset aquí, pero igual hace falta reaplicar la selección: el
                # click que disparó este refresco (normalmente sobre la fila
                # "Cargar más") ya seleccionó esa fila de forma nativa en la vista
                # ANTES de que corriera este método -- restore_selection() es lo que
                # devuelve la selección al ítem real (target_path), no solo lo que
                # sobrevive a un reset de modelo. Sin este llamado, "Cargar más"
                # dejaba la fila "Cargar más" seleccionada y el ítem que el usuario
                # tenía marcado se veía como perdido.
                from PySide6.QtCore import QTimer
                QTimer.singleShot(0, restore_selection)
                return

            if getattr(self, "_pending_scroll_restore", None) is None:
                scroll_widget = self.media_table if getattr(self, "view_mode", "grid") == "list" and hasattr(self, "media_table") else self.media_list
                if scroll_widget and hasattr(scroll_widget, "verticalScrollBar"):
                    val = scroll_widget.verticalScrollBar().value()
                    if val > 0:
                        self._pending_scroll_restore = val

            self._refreshing_media_list = True
            self.media_model.set_data(display_items)
            self._applied_display_paths = new_paths

            # Re-seleccionar si es necesario
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, restore_selection)

        except Exception as e:
            logger.error(f"EditingMediaTab: Error al actualizar lista de medios: {e}", exc_info=True)

    def _on_disk_changed(self):
        """Callback del watchdog cuando hay cambios en las carpetas vigiladas (con debounce de 500ms)."""
        if not hasattr(self, "_disk_change_timer") or self._disk_change_timer is None:
            from PySide6.QtCore import QTimer
            self._disk_change_timer = QTimer(self)
            self._disk_change_timer.setSingleShot(True)
            self._disk_change_timer.setInterval(500)
            self._disk_change_timer.timeout.connect(self._do_disk_changed_refresh)
        
        self._disk_change_timer.start()

    def _do_disk_changed_refresh(self):
        self._update_tree_view()
        self._update_media_list()
        self.controller.trigger_async_indexing()

    def _on_collections_changed(self):
        """Callback cuando se modifican las colecciones virtuales."""
        self._update_tree_view()
        self._update_media_list()
        self.controller.trigger_async_indexing()

    def _on_add_folder_clicked(self):
        """Abre un selector de carpetas e indexa la seleccionada."""
        folder = QFileDialog.getExistingDirectory(self, QCoreApplication.translate("TreeListMixin", "Seleccionar carpeta para indexar"))
        if folder:
            success = self.controller.add_folder(folder)
            if success:
                self._update_tree_view()
                # Seleccionar la nueva carpeta indexada automáticamente
                for i in range(self.physical_root.childCount()):
                    child = self.physical_root.child(i)
                    child_data = child.data(0, Qt.UserRole)
                    if child_data and child_data.get("ruta") == folder.replace("\\", "/"):
                        self.tree_folders.setCurrentItem(child)
                        self._update_media_list()
                        break
            else:
                QMessageBox.information(self, QCoreApplication.translate("TreeListMixin", "Indexador"), QCoreApplication.translate("TreeListMixin", "Esta carpeta ya se encuentra indexada."))

    def _on_remove_folder_clicked(self):
        """Remueve la carpeta indexada seleccionada."""
        selected = self.tree_folders.currentItem()
        if not selected:
            return
        
        data = selected.data(0, Qt.UserRole)
        if data and data.get("tipo") == "folder":
            ruta = data.get("ruta")
            # Confirmar desvinculación
            reply = QMessageBox.question(
                self, 
                QCoreApplication.translate("TreeListMixin", "Desvincular Carpeta"),
                QCoreApplication.translate("TreeListMixin", "¿Estás seguro de que deseas desvincular '{0}'?\n(No se eliminarán los archivos del disco).").format(os.path.basename(ruta)),
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.controller.remove_folder(ruta)
                self.preview_box.show_default_state()
                self._clear_metadata()

    def _on_add_collection_clicked(self):
        """Crea una nueva colección virtual solicitando el nombre al usuario."""
        name, ok = QInputDialog.getText(
            self, 
            QCoreApplication.translate("TreeListMixin", "Nueva Colección"), 
            QCoreApplication.translate("TreeListMixin", "Nombre de la colección virtual:")
        )
        if ok and name.strip():
            name = name.strip()
            success = self.controller.add_collection(name)
            if not success:
                QMessageBox.warning(self, QCoreApplication.translate("TreeListMixin", "Nueva Colección"), QCoreApplication.translate("TreeListMixin", "El nombre ingresado está vacío o ya existe."))

    def _on_remove_collection_clicked(self):
        """Elimina una colección virtual."""
        selected = self.tree_folders.currentItem()
        if not selected:
            return
        
        data = selected.data(0, Qt.UserRole)
        if data and data.get("tipo") == "collection":
            name = data.get("nombre")
            display_name = self._format_collection_title(name)
            reply = QMessageBox.question(
                self, 
                QCoreApplication.translate("TreeListMixin", "Eliminar Colección"),
                QCoreApplication.translate("TreeListMixin", "¿Estás seguro de que deseas eliminar la colección '{0}'?").format(display_name),
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.controller.remove_collection(name)
                self.preview_box.show_default_state()
                self._clear_metadata()

    def _on_tree_current_item_changed(self, current, previous):
        if current and current != previous:
            try:
                self._on_tree_item_clicked(current, 0)
            except RuntimeError:
                pass

    def _on_current_item_changed(self, current, previous):
        if current:
            try:
                self._on_media_clicked(current)
            except RuntimeError:
                pass

    def _on_tree_item_clicked(self, item, column):
        self._update_button_states()
        
        try:
            data = item.data(0, Qt.UserRole) if item else None

            # Evitar re-ejecución duplicada si ya es el nodo seleccionado y renderizado.
            # Se compara solo por datos lógicos (tipo/ruta/nombre): el árbol se reconstruye
            # por completo en cada refresco (_update_tree_view crea QTreeWidgetItem nuevos),
            # así que comparar por identidad de objeto siempre fallaría aunque el nodo
            # seleccionado no haya cambiado realmente.
            if data is not None and getattr(self, "_active_tree_data", None) == data:
                self._active_tree_item = item
                return
        except RuntimeError:
            self._active_tree_item = None
            self._active_tree_data = None
            if not item:
                return
            try:
                data = item.data(0, Qt.UserRole)
            except RuntimeError:
                return

        self._active_tree_item = item
        self._active_tree_data = data
        self._max_display_count = 500



        # Limpiar selección previa del reproductor al cambiar de carpeta en el árbol
        self.current_playing_path = None
        
        if data:
            self.controller.last_selected_tree_node = data
            self.controller.save_data()

        if data and data.get("tipo") == "web_source":
            source_id = data.get("source_id")
            if getattr(self, "active_web_source_id", None) != source_id:
                # Cambiamos de origen web (ej. Freesound -> Wikimedia): los resultados
                # cacheados del origen anterior ya no aplican.
                self.active_web_source_id = source_id
                self.current_page = 1
                self.online_results = []
            if not self.online_results and not self._web_source_needs_auth(source_id):
                self._exec_online_search()

        self._update_media_list()

    def _sort_media_list_items(self):
        """Reordena los ítems actualizando los datos del modelo MVC."""
        self._update_media_list()

    def _apply_active_filters_fast(self):
        """Aplica filtros de tipo, ordenación y búsqueda en RAM (0ms)."""
        self._update_media_list()

    def _on_filter_button_clicked(self):
        """Maneja el cambio de filtro y deselecciona los otros botones."""
        sender = self.sender()
        self.active_filter = sender.property("filter_key") or sender.text()
        self._max_display_count = 500  # Resetear paginación al cambiar de filtro
        
        # Si filtramos por categoría específica y el modo actual de ordenación es "tipo", revertir a "nombre"
        if resolve_filter_type(self.active_filter) is not None and getattr(self, "sort_by", "nombre") == "tipo":
            self.sort_by = "nombre"
            if hasattr(self, "btn_sort_by"):
                self.btn_sort_by.setText(QCoreApplication.translate("TreeListMixin", "Nombre"))

        for btn in self.filter_buttons:
            if btn != sender:
                btn.setChecked(False)
        sender.setChecked(True)
        
        if hasattr(self, "_build_sort_menu"):
            self._build_sort_menu()

        # En un origen web con varios tipos de medio (ej. Wikimedia: imagen/audio/video),
        # filtrar por tipo tiene que repetir la búsqueda pidiéndole al origen que filtre
        # server-side (ver WikimediaProvider.search, filemime:) — recortar client-side la
        # página ya traída se ve "siempre vacía" apenas el tipo elegido es minoritario en esa
        # página (en Commons casi cualquier búsqueda está dominada por imágenes).
        selected = self.tree_folders.currentItem()
        if selected:
            data = selected.data(0, Qt.UserRole)
            if data and data.get("tipo") == "web_source":
                source_id = data.get("source_id")
                provider = getattr(self, "web_providers", {}).get(source_id)
                if provider and len(provider.supported_media_types) > 1 and not self._web_source_needs_auth(source_id):
                    self.current_page = 1
                    self.online_results = []
                    self._exec_online_search()
                    return

        self._update_media_list()

    def _refresh_current_view(self):
        """Refresca la vista actual (limpia cachés de medios/metadatos y re-escanea o re-ejecuta búsquedas)."""
        if hasattr(self.controller, "_media_cache"):
            self.controller._media_cache = {}
        if hasattr(self, "_metadata_cache"):
            self._metadata_cache = {}

        selected = self.tree_folders.currentItem()
        if selected:
            try:
                data = selected.data(0, Qt.UserRole)
                if data and data.get("tipo") == "web_source":
                    source_id = data.get("source_id")
                    if not self._web_source_needs_auth(source_id):
                        self.current_page = 1
                        self.online_results = []
                        self._exec_online_search()
                    return
            except RuntimeError:
                pass

        self._update_media_list()

    def _show_tree_context_menu(self, position):
        item = self.tree_folders.itemAt(position)
        menu = QMenu(self)

        act_refresh = menu.addAction(get_contrast_svg_icon("refresh.svg"), QCoreApplication.translate("TreeListMixin", "Actualizar"))

        act_refresh.triggered.connect(self._refresh_current_view)
        menu.addSeparator()

        if not item:
            # Click derecho en zona vacía: ofrecer crear colección virtual
            act_new_col = menu.addAction(QCoreApplication.translate("TreeListMixin", "Nueva Colección Virtual"))
            act_new_col.triggered.connect(self._on_add_collection_clicked)
            menu.exec(self.tree_folders.mapToGlobal(position))
            return

            
        data = item.data(0, Qt.UserRole)
        if not data:
            return
            
        tipo = data.get("tipo")
        if tipo == "folder":
            act_remove = menu.addAction(QCoreApplication.translate("TreeListMixin", "Desvincular Carpeta Física"))
            act_remove.triggered.connect(self._on_remove_folder_clicked)
            
            # Opciones de coloreado
            menu.addSeparator()
            act_color = menu.addAction(QCoreApplication.translate("TreeListMixin", "Color Aleatorio"))
            act_color.triggered.connect(lambda: self._set_random_color_for_item(item))
            
            act_choose = menu.addAction(QCoreApplication.translate("TreeListMixin", "Elegir Color..."))
            act_choose.triggered.connect(lambda: self._choose_color_for_item(item))
            
            current_color = get_item_color(f"folder:{data.get('ruta')}")
            if current_color:
                act_reset_color = menu.addAction(QCoreApplication.translate("TreeListMixin", "Restablecer Color"))
                act_reset_color.triggered.connect(lambda: self._reset_color_for_item(item))
                
            menu.exec(self.tree_folders.mapToGlobal(position))
        elif tipo == "subfolder":
            # Para subcarpetas físicas, no hay acción de desvincular, pero sí de colorear
            act_color = menu.addAction(QCoreApplication.translate("TreeListMixin", "Color Aleatorio"))
            act_color.triggered.connect(lambda: self._set_random_color_for_item(item))
            
            act_choose = menu.addAction(QCoreApplication.translate("TreeListMixin", "Elegir Color..."))
            act_choose.triggered.connect(lambda: self._choose_color_for_item(item))
            
            current_color = get_item_color(f"folder:{data.get('ruta')}")
            if current_color:
                act_reset_color = menu.addAction(QCoreApplication.translate("TreeListMixin", "Restablecer Color"))
                act_reset_color.triggered.connect(lambda: self._reset_color_for_item(item))
                
            menu.exec(self.tree_folders.mapToGlobal(position))
        elif tipo == "collection":
            # "Descargados"/"Subclips"/"Default" son carpetas de sistema que la propia app
            # llena sola (descargas, cortes físicos, indexación individual) -- no se pueden
            # eliminar por clic derecho para evitar borrarlas por accidente. El coloreado sí
            # se deja disponible para las tres, igual que cualquier otra colección.
            if data.get("nombre") not in ("Descargados", "Subclips", "Default", "Favoritos"):
                act_remove = menu.addAction(QCoreApplication.translate("TreeListMixin", "Eliminar Colección Virtual"))
                act_remove.triggered.connect(self._on_remove_collection_clicked)
                menu.addSeparator()

            # Opciones de coloreado
            act_color = menu.addAction(QCoreApplication.translate("TreeListMixin", "Color Aleatorio"))
            act_color.triggered.connect(lambda: self._set_random_color_for_item(item))
            
            act_choose = menu.addAction(QCoreApplication.translate("TreeListMixin", "Elegir Color..."))
            act_choose.triggered.connect(lambda: self._choose_color_for_item(item))
            
            current_color = get_item_color(f"col:{data.get('nombre')}")
            if current_color:
                act_reset_color = menu.addAction(QCoreApplication.translate("TreeListMixin", "Restablecer Color"))
                act_reset_color.triggered.connect(lambda: self._reset_color_for_item(item))
                
            menu.exec(self.tree_folders.mapToGlobal(position))
        elif tipo == "root_virtual":
            act_new_col = menu.addAction(QCoreApplication.translate("TreeListMixin", "Nueva Colección Virtual"))
            act_new_col.triggered.connect(self._on_add_collection_clicked)
            menu.exec(self.tree_folders.mapToGlobal(position))

    def _set_random_color_for_item(self, item):
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        tipo = data.get("tipo")
        
        # Obtener el color actual para excluirlo y garantizar el cambio de color
        current_color = None
        if tipo in ["folder", "subfolder"]:
            ruta = data.get("ruta")
            current_color = get_item_color(f"folder:{ruta}")
        elif tipo == "collection":
            nombre = data.get("nombre")
            current_color = get_item_color(f"col:{nombre}")
            
        color = get_random_label_color(exclude_color=current_color)
        
        if tipo in ["folder", "subfolder"]:
            ruta = data.get("ruta")
            set_item_color(f"folder:{ruta}", color)
        elif tipo == "collection":
            nombre = data.get("nombre")
            set_item_color(f"col:{nombre}", color)
            
        self._update_tree_view()

    def _choose_color_for_item(self, item):
        from gui.dialogs.dialogs import AdobeColorPickerDialog
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        tipo = data.get("tipo")
        
        # Obtener el color actual para inicializar el picker
        current_color = None
        if tipo in ["folder", "subfolder"]:
            ruta = data.get("ruta")
            current_color = get_item_color(f"folder:{ruta}")
        elif tipo == "collection":
            nombre = data.get("nombre")
            current_color = get_item_color(f"col:{nombre}")
            
        initial_color = current_color if current_color else "#B9E640"
        
        dialog = AdobeColorPickerDialog(initial_color, self)
        if dialog.exec():
            color = dialog.get_color()
            if tipo in ["folder", "subfolder"]:
                ruta = data.get("ruta")
                set_item_color(f"folder:{ruta}", color)
            elif tipo == "collection":
                nombre = data.get("nombre")
                set_item_color(f"col:{nombre}", color)
                
            self._update_tree_view()

    def _reset_color_for_item(self, item):
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        tipo = data.get("tipo")
        
        if tipo in ["folder", "subfolder"]:
            ruta = data.get("ruta")
            set_item_color(f"folder:{ruta}", None)
        elif tipo == "collection":
            nombre = data.get("nombre")
            set_item_color(f"col:{nombre}", None)
            
        self._update_tree_view()

    def _show_media_context_menu(self, position):
        is_list_view = getattr(self, "view_mode", "grid") == "list" and hasattr(self, "media_table")
        view_widget = self.media_table if is_list_view else self.media_list
        index = view_widget.indexAt(position)
        
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {get_theme_token('fondo_elemento', '#1e1e1e')};
                border: 1px solid {get_theme_token('borde_normal', '#3d3d3d')};
                padding: 4px;
                border-radius: 6px;
            }}
            QMenu::item {{
                padding: 5px 12px 5px 24px;
                border-radius: 4px;
                color: {get_theme_token('texto_principal', '#cdd6f4')};
                font-size: 11px;
            }}
            QMenu::icon {{
                padding-left: 6px;
            }}
            QMenu::item:selected {{
                background-color: {get_theme_token('acento_primario', '#B9E640')};
                color: {get_theme_token('fondo_principal', '#0a0a0a')};
                font-weight: bold;
            }}
            QMenu::item:disabled {{
                color: #555555;
            }}
        """)

        # 1. Acciones específicas si se hace clic sobre uno o varios archivos
        selected_indexes = getattr(self, "_selected_indexes", [])
        # _selected_indexes solo guarda índices de columna 0 (ver _on_selection_changed), pero en
        # vista de lista/tabla el clic derecho puede caer en cualquier columna de la fila. Comparar
        # por fila (no por índice exacto) evita que el menú colapse a un solo ítem cuando el clic
        # cae fuera de la columna 0 de una fila que sí está seleccionada.
        selected_rows = {idx.row() for idx in selected_indexes}
        if index.isValid() and index.row() not in selected_rows:
            selected_indexes = [index] # Si el click derecho fue fuera de la selección, solo usamos el item clickeado
            
        if selected_indexes:
            file_paths = []
            item_datas = []
            for idx in selected_indexes:
                item_data = self.media_model.get_item(idx)
                if item_data and "ruta" in item_data:
                    file_paths.append(item_data["ruta"])
                    item_datas.append(item_data)

            if file_paths:
                # Determinar si estamos visualizando una colección virtual
                tree_item = self.tree_folders.currentItem()
                is_viewing_collection = False
                current_col_name = ""
                if tree_item:
                    tree_data = tree_item.data(0, Qt.UserRole)
                    if tree_data and tree_data.get("tipo") == "collection":
                        is_viewing_collection = True
                        current_col_name = tree_data.get("nombre")
                        
                count_str = f" ({len(file_paths)})" if len(file_paths) > 1 else ""

                if is_viewing_collection:
                    remove_label = QCoreApplication.translate("TreeListMixin", "Quitar de esta Colección ({0})").format(len(file_paths)) if len(file_paths) > 1 else QCoreApplication.translate("TreeListMixin", "Quitar de esta Colección")
                    act_remove = menu.addAction(remove_label)
                    act_remove.triggered.connect(lambda: [self._remove_file_from_collection(current_col_name, fp) for fp in file_paths])
                else:
                    add_label = QCoreApplication.translate("TreeListMixin", "Añadir a Colección ({0})").format(len(file_paths)) if len(file_paths) > 1 else QCoreApplication.translate("TreeListMixin", "Añadir a Colección")
                    submenu = menu.addMenu(add_label)
                    collections_list = [c for c in self.controller.collections.keys() if c not in ("Descargados", "Subclips", "Default")]
                    if collections_list:
                        for col_name in collections_list:
                            act_col = submenu.addAction(self._format_collection_title(col_name))
                            act_col.triggered.connect(lambda checked=False, cn=col_name, items=item_datas: [self._add_media_to_collection(cn, it) for it in items])
                    else:
                        act_none = submenu.addAction(QCoreApplication.translate("TreeListMixin", "(Sin colecciones)"))
                        act_none.setEnabled(False)

                if len(file_paths) == 1:
                    is_remote = file_paths[0].startswith("http://") or file_paths[0].startswith("https://")
                    if is_remote:
                        act_download = menu.addAction(get_svg_icon("download.svg"), QCoreApplication.translate("TreeListMixin", "Descargar Medio"))
                        act_download.triggered.connect(self._on_download_clicked)
                    else:
                        act_reveal = menu.addAction(get_svg_icon("folder_open.svg"), QCoreApplication.translate("TreeListMixin", "Abrir en Explorador"))
                        act_reveal.triggered.connect(self._on_reveal_clicked)
                
                from core.services.editor_integration_manager import EditorIntegrationManager
                editor_mgr = EditorIntegrationManager.get_instance()
                if editor_mgr and editor_mgr.active_editor:
                    active = editor_mgr.active_editor
                    if active == "premiere":
                        e_icon = get_svg_icon("premiere pro.svg")
                        e_name = "Premiere Pro"
                    elif active == "aftereffects":
                        e_icon = get_svg_icon("after effects.svg")
                        e_name = "After Effects"
                    elif active == "davinci":
                        e_icon = get_svg_icon("davinci resolve.svg")
                        e_name = "DaVinci Resolve"
                    else:
                        e_icon = QIcon()
                        e_name = "Editor"
                        
                    count = len(file_paths)
                    if count > 1:
                        act_send = menu.addAction(e_icon, QCoreApplication.translate("TreeListMixin", "Enviar ({0}) medios a {1}").format(count, e_name))
                    else:
                        act_send = menu.addAction(e_icon, QCoreApplication.translate("TreeListMixin", "Enviar medio a {0}").format(e_name))
                        
                    act_send.triggered.connect(self._on_send_editor_clicked)

                imagenes = [d for d in item_datas if d.get("tipo") == "imagen"]
                medios_av = [d for d in item_datas if d.get("tipo") in ("video", "audio")]

                if imagenes:
                    n = len(imagenes)
                    label = QCoreApplication.translate("TreeListMixin", "Enviar ({0}) a Editor de Imagen").format(n) if n > 1 else QCoreApplication.translate("TreeListMixin", "Enviar a Editor de Imagen")
                    act_send_img = menu.addAction(get_svg_icon("image.svg"), label)
                    act_send_img.triggered.connect(lambda checked=False, items=imagenes: self._on_send_to_tool_clicked(items, "image"))

                if medios_av:
                    n = len(medios_av)
                    label = QCoreApplication.translate("TreeListMixin", "Enviar ({0}) a Herramientas Multimedia").format(n) if n > 1 else QCoreApplication.translate("TreeListMixin", "Enviar a Herramientas Multimedia")
                    act_send_vid = menu.addAction(get_svg_icon("movie.svg"), label)
                    act_send_vid.triggered.connect(lambda checked=False, items=medios_av: self._on_send_to_tool_clicked(items, "video"))

                menu.addSeparator()

        # 2. Acciones Generales (Actualizar, Ordenar por, Vista)
        act_refresh = menu.addAction(get_contrast_svg_icon("refresh.svg"), QCoreApplication.translate("TreeListMixin", "Actualizar Lista"))
        act_refresh.triggered.connect(self._refresh_current_view)
        menu.addSeparator()

        # Detectar si estamos navegando en modo online (Freesound)
        selected_tree = self.tree_folders.currentItem()
        is_online_mode = False
        if selected_tree:
            t_data = selected_tree.data(0, Qt.UserRole)
            if t_data and t_data.get("tipo") == "web_source":
                is_online_mode = True

        sort_sub = menu.addMenu(QCoreApplication.translate("TreeListMixin", "Ordenar por"))

        if is_online_mode:
            options = [
                ("nombre", QCoreApplication.translate("TreeListMixin", "Nombre")),
                ("duration", QCoreApplication.translate("TreeListMixin", "Duración")),
                ("license", QCoreApplication.translate("TreeListMixin", "Licencia")),
            ]
        else:
            options = [
                ("nombre", QCoreApplication.translate("TreeListMixin", "Nombre")),
                ("size", QCoreApplication.translate("TreeListMixin", "Tamaño")),
                ("tipo", QCoreApplication.translate("TreeListMixin", "Tipo de Archivo")),
                ("mtime", QCoreApplication.translate("TreeListMixin", "Fecha de Modificación")),
                ("ruta", QCoreApplication.translate("TreeListMixin", "Ruta Completa")),
            ]
        curr_sort = getattr(self, "sort_by", "nombre")
        active_filter = getattr(self, "active_filter", "Todos")

        for key, label in options:
            act = sort_sub.addAction(label)
            act.setCheckable(True)
            if key == curr_sort:
                act.setChecked(True)
            if key == "tipo" and resolve_filter_type(active_filter) is not None:
                act.setEnabled(False)
            act.triggered.connect(lambda checked, k=key, l=label: self._on_sort_option_selected(k, l))

        sort_sub.addSeparator()
        act_asc = sort_sub.addAction(QCoreApplication.translate("TreeListMixin", "Ascendente (A-Z, Menor a Mayor)"))
        act_asc.setCheckable(True)
        act_asc.setChecked(getattr(self, "sort_ascending", True))
        act_asc.triggered.connect(lambda: self._set_sort_direction(True))

        act_desc = sort_sub.addAction(QCoreApplication.translate("TreeListMixin", "Descendente (Z-A, Mayor a Menor)"))
        act_desc.setCheckable(True)
        act_desc.setChecked(not getattr(self, "sort_ascending", True))
        act_desc.triggered.connect(lambda: self._set_sort_direction(False))

        view_sub = menu.addMenu(QCoreApplication.translate("TreeListMixin", "Vista"))
        act_grid = view_sub.addAction(QCoreApplication.translate("TreeListMixin", "Cuadrícula"))
        act_grid.setCheckable(True)
        act_grid.setChecked(getattr(self, "view_mode", "grid") == "grid")
        act_grid.triggered.connect(lambda: self.set_view_mode("grid"))

        act_list = view_sub.addAction(QCoreApplication.translate("TreeListMixin", "Lista"))
        act_list.setCheckable(True)
        act_list.setChecked(getattr(self, "view_mode", "grid") == "list")
        act_list.triggered.connect(lambda: self.set_view_mode("list"))

        menu.exec(view_widget.mapToGlobal(position))


    def _add_file_to_collection(self, col_name, file_path):
        success = self.controller.add_to_collection(col_name, file_path)
        if success:
            logger.info(f"EditingMediaTab: Archivo {os.path.basename(file_path)} añadido a colección {col_name}")
        else:
            logger.info(f"EditingMediaTab: El archivo ya se encuentra en la colección {col_name}")

    def _add_media_to_collection(self, col_name, item_data):
        """Añade un medio a una colección virtual, conservando el título web y la licencia si es remoto."""
        if not item_data:
            return

        dest = item_data.get("dest_path")
        has_real_file = bool(dest and os.path.exists(dest))
        path = dest if has_real_file else item_data.get("ruta", "")
        if not path:
            return

        is_remote = item_data.get("es_remoto") or (isinstance(path, str) and (path.startswith("http://") or path.startswith("https://")))
        if is_remote and not has_real_file:
            success = self.controller.add_to_collection(col_name, item_data)
        else:
            success = self.controller.add_to_collection(col_name, path)

        display_name = item_data.get("nombre") or os.path.basename(path)
        if success:
            logger.info(f"EditingMediaTab: Archivo '{display_name}' añadido a colección '{col_name}'")
        else:
            logger.info(f"EditingMediaTab: El archivo ya se encuentra en la colección '{col_name}'")

    def _upgrade_web_collection_entry(self, col_name, placeholder_url, item_data):
        """Descarga en segundo plano el archivo original de un medio de Freesound recién
        añadido a una colección y, al terminar, reemplaza la URL de previsualización por
        la ruta real en disco. Si el usuario no está autenticado con Freesound, no hace
        nada y la colección conserva la URL de streaming (no hay forma de obtener el
        archivo original sin iniciar sesión)."""
        if not hasattr(self, "_start_high_quality_download"):
            return
        token = getattr(self.controller, "freesound_auth", {}).get("access_token", "")
        if not token or not item_data.get("id"):
            return

        def _on_success(resolved_path):
            self.controller.remove_from_collection(col_name, placeholder_url)
            self._add_file_to_collection(col_name, resolved_path)
            if hasattr(self, "_update_media_list"):
                self._update_media_list()

        def _on_error(err):
            logger.info(f"EditingMediaTab: No se pudo descargar el original de '{item_data.get('nombre')}' para la colección '{col_name}': {err}")

        self._start_high_quality_download(item_data, on_success=_on_success, on_error=_on_error)

    def _remove_file_from_collection(self, col_name, file_path):
        self.controller.remove_from_collection(col_name, file_path)
        self._update_media_list()

    def _on_sort_option_selected(self, key: str, label: str):
        self.sort_by = key
        if hasattr(self, "_update_media_list"):
            self._update_media_list()

    def _set_sort_direction(self, asc: bool):
        self.sort_ascending = asc
        if hasattr(self, "btn_sort_dir"):
            if asc:
                self.btn_sort_dir.setIcon(get_colored_svg_icon("arrow_upward_alt.svg", "#FFFFFF", size=16))
                self.btn_sort_dir.setIconSize(QSize(16, 16))
                self.btn_sort_dir.setToolTip(QCoreApplication.translate("TreeListMixin", "Orden Ascendente (A-Z, Antiguos primero)"))
            else:
                self.btn_sort_dir.setIcon(get_colored_svg_icon("arrow_downward_alt.svg", "#FFFFFF", size=16))
                self.btn_sort_dir.setIconSize(QSize(16, 16))
                self.btn_sort_dir.setToolTip(QCoreApplication.translate("TreeListMixin", "Orden Descendente (Z-A, Recientes primero)"))
        self._apply_active_filters_fast()
        self.preview_box.show_default_state()
        self._clear_metadata()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and event.source() is None:
            event.acceptProposedAction()
            from gui.styles import get_theme_token
            color = self._get_border_accent_color()
            fondo_secundario = get_theme_token('fondo_secundario', '#1e1e1e')
            if hasattr(self, "col2_container"):
                self.col2_container.setStyleSheet(f"""
                    QFrame#mediaListFrame {{
                        background-color: {fondo_secundario};
                        border: 2px dashed {color};
                        border-radius: 6px;
                    }}
                """)

    def _get_border_accent_color(self):
        # Usar getter para evitar imports circulares de estilos si es posible
        from gui.styles import get_theme_token
        return get_theme_token('acento_primario', '#B9E640')

    def dragLeaveEvent(self, event):
        self.setStyleSheet("")
        self._apply_custom_styles()

    def dropEvent(self, event):
        self.setStyleSheet("")
        self._apply_custom_styles()
        urls = event.mimeData().urls()
        
        has_new_folders = False
        has_new_files = False
        first_added_path = None
        
        for url in urls:
            local_path = url.toLocalFile()
            logger.info(f"EditingMediaTab: Elemento arrastrado y soltado: {local_path}")
            
            if os.path.isdir(local_path):
                self.controller.add_folder(local_path)
                has_new_folders = True
                if not first_added_path:
                    first_added_path = local_path.replace("\\", "/")
            elif os.path.isfile(local_path):
                ext = os.path.splitext(local_path)[1].lower()
                if ext in VALID_EXTS:
                    # Los archivos indexados individualmente (sueltos, no una carpeta entera)
                    # van a la carpeta virtual "Default" dentro de Directorios, no a la
                    # colección "Favoritos" (que el usuario reserva para organizar a mano).
                    col_name = "Default"
                    if "Default" not in self.controller.collections:
                        self.controller.add_collection("Default")

                    self.controller.add_to_collection(col_name, local_path)
                    has_new_files = True

        if has_new_folders:
            self._update_tree_view()
            if first_added_path:
                for i in range(self.physical_root.childCount()):
                    child = self.physical_root.child(i)
                    child_data = child.data(0, Qt.UserRole)
                    if child_data and child_data.get("ruta") == first_added_path:
                        self.tree_folders.setCurrentItem(child)
                        self._update_media_list()
                        break
        elif has_new_files:
            self._update_tree_view()
            for i in range(self.virtual_root.childCount()):
                child = self.virtual_root.child(i)
                child_data = child.data(0, Qt.UserRole)
                if child_data and child_data.get("nombre") == "Favoritos":
                    self.tree_folders.setCurrentItem(child)
                    self._update_media_list()
                    break
