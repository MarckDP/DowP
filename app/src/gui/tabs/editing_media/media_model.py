import os
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, Signal, QSize
from PySide6.QtGui import QIcon, QColor, QFont
from core.tabs.editing_media.thumbnail_cache_manager import ThumbnailCacheManager
from gui.tabs.editing_media.editing_media_icons import (
    get_placeholder_thumbnail_icon,
    get_colored_svg_icon
)
from gui.styles import get_theme_token

class MediaTableModel(QAbstractTableModel):
    """
    Modelo de datos para la lista de medios.
    Soporta visualización tanto en QListView (IconMode) como en QTreeView (Tabla).
    """
    global_sort_requested = Signal(int, bool) # column, is_ascending

    def __init__(self, parent=None):
        super().__init__(parent)
        self._media_items = []
        self._view_mode = "grid"
        self._grid_size_hint = QSize(150, 150)
        
        # Conectar señal de miniaturas al modelo
        thumb_mgr = ThumbnailCacheManager.get_instance()
        thumb_mgr.thumbnail_loaded.connect(self._on_thumbnail_loaded)
        
        from core.tabs.editing_media.waveform_cache_manager import WaveformCacheManager
        wf_mgr = WaveformCacheManager.get_instance()
        wf_mgr.waveform_loaded.connect(self._on_waveform_loaded)

        from core.tabs.editing_media.freesound_preview_cache import FreesoundPreviewCacheManager
        fs_mgr = FreesoundPreviewCacheManager.get_instance()
        fs_mgr.waveform_peaks_ready.connect(self._on_freesound_waveform_loaded)

        from core.tabs.editing_media.remote_thumbnail_cache_manager import RemoteThumbnailCacheManager
        remote_thumb_mgr = RemoteThumbnailCacheManager.get_instance()
        remote_thumb_mgr.thumbnail_ready.connect(self._on_remote_thumbnail_loaded)

        # Para caché rápido de íconos base y colores
        self._icon_cache = {}
        
        self.headers = [
            self.tr("Estado"),
            self.tr("Nombre de Archivo"),
            self.tr("Descripción"),
            self.tr("Licencia"),
            self.tr("Duración"),
            self.tr("Origen"),
            self.tr("Tipo de Archivo"),
            self.tr("Detalles")
        ]

    def set_view_mode(self, mode: str, grid_size_hint: QSize = None):
        """Actualiza el modo de vista y el tamaño de la cuadrícula si aplica."""
        self._view_mode = mode
        if grid_size_hint:
            self._grid_size_hint = grid_size_hint

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        item = self._media_items[index.row()]
        if item.get("tipo") not in ("load_more", "empty"):
            base |= Qt.ItemIsDragEnabled
        return base

    def _resolve_drag_path(self, item):
        """Devuelve una ruta local existente para arrastrar el ítem como archivo del SO.
        Si es local, retorna la ruta. Si es remoto y ya se descargó en alta calidad, retorna dest_path.
        Si es remoto y existe la previsualización en caché, la retorna como fallback."""
        path = item.get("ruta", "")
        if path and not path.startswith("http://") and not path.startswith("https://"):
            return path if os.path.exists(path) else None
        dest_path = item.get("dest_path")
        if dest_path and os.path.exists(dest_path):
            return dest_path
        from core.tabs.editing_media.freesound_preview_cache import FreesoundPreviewCacheManager
        cached = FreesoundPreviewCacheManager.get_instance().get_cached_path(path)
        if cached and os.path.exists(cached):
            return cached
        return None

    def mimeTypes(self):
        return ["text/uri-list"]

    def mimeData(self, indexes):
        from PySide6.QtCore import QMimeData, QUrl
        seen_rows = set()
        urls = []
        for idx in indexes:
            if not idx.isValid() or idx.row() in seen_rows:
                continue
            seen_rows.add(idx.row())
            path = self._resolve_drag_path(self._media_items[idx.row()])
            if path:
                urls.append(QUrl.fromLocalFile(path))
        if not urls:
            return None
        mime = QMimeData()
        mime.setUrls(urls)
        return mime
        
    def get_cached_icon(self, icon_name: str, color: str, size: int = None) -> QIcon:
        key = f"{icon_name}_{color}_{size}"
        if key not in self._icon_cache:
            if "placeholder" in key:
                 self._icon_cache[key] = get_placeholder_thumbnail_icon(icon_name.replace("_placeholder", ""), color)
            else:
                 self._icon_cache[key] = get_colored_svg_icon(icon_name, color, size=size if size else 18)
        return self._icon_cache[key]

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._media_items)

    def columnCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self.headers)
        
    def set_online_mode(self, is_online: bool):
        """Alterna el modo online/local para la presentación de cabeceras."""
        self._is_online_mode = is_online
        self.headerDataChanged.emit(Qt.Horizontal, 0, len(self.headers) - 1)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            if not getattr(self, "_is_online_mode", False):
                if section == 0:
                    return self.tr("Estado")
                elif section == 1:
                    return self.tr("Nombre de Archivo")
                elif section == 2:
                    return self.tr("Tamaño")
                elif section == 3:
                    return self.tr("Tipo de Archivo")
                elif section == 4:
                    return self.tr("Fecha Modificación")
                elif section == 5:
                    return self.tr("Ruta Completa")
            online_headers = [
                self.tr("Estado"),
                self.tr("Nombre de Archivo"),
                self.tr("Descripción"),
                self.tr("Licencia"),
                self.tr("Duración"),
                self.tr("Origen"),
                self.tr("Tipo de Archivo"),
                self.tr("Detalles")
            ]
            if 0 <= section < len(online_headers):
                return online_headers[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        row = index.row()
        col = index.column()
        item = self._media_items[row]
        
        # Rol para obtener el diccionario completo
        if role == Qt.UserRole:
            return item

        tipo = item.get("tipo", "")
        file_path = item.get("ruta", "")
        is_web = item.get("es_remoto", False) or file_path.startswith("http")
        
        if role == Qt.DisplayRole:
            if self._view_mode == "grid":
                if col == 0:
                    # En modo Grid, la ListView asume que la columna 0 provee el texto y el ícono
                    if tipo == "load_more":
                        return item.get("nombre", "Mostrar todo")
                    return item.get("nombre", "")
                return None
            else:
                # Modo Tabla
                if tipo == "load_more":
                    if col == 1:
                        return item.get("nombre", "Mostrar todo")
                    return ""
                
                if col == 0: return "" # Ícono
                elif col == 1: return item.get("nombre", "")
                elif col == 2: 
                    if not is_web:
                        return str(item.get("tamaño", "-"))
                    desc = str(item.get("description", item.get("desc", "-"))).replace("\r\n", " ").replace("\n", " ").replace("\r", " ").strip()
                    import re
                    desc = re.sub(r"\s+", " ", desc)
                    return desc[:117] + "..." if len(desc) > 120 else (desc if desc else "-")
                elif col == 3: 
                    if not is_web:
                        file_type = item.get("file_type") or item.get("type", "")
                        if not file_type and "." in item.get("nombre", ""):
                            ext = item.get("nombre", "").split(".")[-1].upper()
                            if len(ext) <= 5: file_type = ext
                        return str(file_type).upper() if file_type else str(tipo).upper()
                    return str(item.get("license", "Local")).strip() or "Local"
                elif col == 4: 
                    if not is_web:
                        mtime = item.get("mtime", 0)
                        if mtime:
                            import datetime
                            try:
                                return datetime.datetime.fromtimestamp(mtime).strftime("%d/%m/%Y %H:%M")
                            except Exception:
                                pass
                        return "-"
                    return str(item.get("duración", item.get("duration_str", "-"))).strip() or "-"
                elif col == 5: 
                    if not is_web:
                        return str(item.get("ruta", "-")).strip() or "-"
                    return str(item.get("library", "Web" if is_web else "Local")).strip()
                elif col == 6: 
                    file_type = item.get("file_type") or item.get("type", "")
                    if not file_type and "." in item.get("nombre", ""):
                        ext = item.get("nombre", "").split(".")[-1].upper()
                        if len(ext) <= 5: file_type = ext
                    return str(file_type).upper() if file_type else str(tipo).upper()
                elif col == 7: 
                    if tipo == "audio":
                        detalles = item.get("detalles_audio")
                        if detalles: return detalles
                        return str(item.get("sample_rate", item.get("samplerate", "-")))
                    elif tipo == "video":
                        detalles = item.get("detalles_video")
                        if detalles: return detalles
                        res = item.get("resolución", "")
                        fps = item.get("fps", "")
                        if res and fps: return f"{res} {fps}fps".strip()
                        return "-"
                    elif tipo == "imagen":
                        res = item.get("resolución", "")
                        return res if res else "-"
                    return "-"
        
        elif role == Qt.DecorationRole and col == 0:
            accent_green = get_theme_token("acento_primario", "#B9E640")
            
            if tipo == "load_more":
                if self._view_mode == "grid":
                    return None # En grid podríamos usar un ítem personalizado o fallback
                else:
                    return self.get_cached_icon("arrow_circle_down.svg", accent_green, size=18)

            # Verificar si está descargado
            is_downloaded = False
            if is_web and "dest_path" in item:
                is_downloaded = True
                file_path = item["dest_path"]

            from core.tabs.editing_media.waveform_cache_manager import WaveformCacheManager
            wf_mgr = WaveformCacheManager.get_instance()

            if tipo == "audio":
                if (not is_web) or (is_web and is_downloaded):
                    # En modo lista las filas deben permanecer delgadas: el ícono de forma de
                    # onda se renderiza pequeño (18px) en vez del tamaño grande usado en la
                    # cuadrícula, que antes inflaba la altura de la fila.
                    icon_size = QSize(80, 80) if self._view_mode == "grid" else QSize(18, 18)
                    cached_icon = wf_mgr.get_cached_qicon(file_path, icon_size)
                    if cached_icon is not None:
                        return cached_icon
                    else:
                        wf_mgr.request_waveform(file_path, size=icon_size)
                        # Devolver ícono por defecto mientras carga
                        if self._view_mode == "grid":
                            return self.get_cached_icon("music_note.svg_placeholder", "#3498db")
                        else:
                            return self.get_cached_icon("music_note.svg", "#3498db", size=18)

            if is_web and not is_downloaded:
                if tipo == "audio" and "images" in item and item["images"].get("waveform_m"):
                    waveform_url = item["images"]["waveform_m"]
                    from core.tabs.editing_media.freesound_preview_cache import FreesoundPreviewCacheManager
                    fs_cache = FreesoundPreviewCacheManager.get_instance()
                    peaks = fs_cache.get_cached_waveform_peaks(waveform_url)
                    if peaks is not None:
                        from core.tabs.editing_media.waveform_cache_manager import render_waveform_icon
                        icon_size = QSize(80, 80) if self._view_mode == "grid" else QSize(18, 18)
                        return render_waveform_icon(peaks, icon_size)

                # Miniatura ya renderizada por el origen web (ej. thumburl de Wikimedia, tanto
                # para imagen como para video) — se cachea localmente sin descargar el archivo
                # original completo. El audio no tiene una miniatura real, cae al placeholder.
                if tipo in ("imagen", "video") and item.get("thumb_url"):
                    thumb_url = item["thumb_url"]
                    from core.tabs.editing_media.remote_thumbnail_cache_manager import RemoteThumbnailCacheManager
                    remote_thumb_mgr = RemoteThumbnailCacheManager.get_instance()
                    icon_size = 256 if self._view_mode == "grid" else 18
                    cached_icon = remote_thumb_mgr.get_cached_qicon(thumb_url, icon_size)
                    if cached_icon:
                        return cached_icon
                    remote_thumb_mgr.request_thumbnail(thumb_url)
                    placeholder_name = "movie.svg" if tipo == "video" else "image.svg"
                    placeholder_color = "#9b59b6" if tipo == "video" else "#2ecc71"
                    if self._view_mode == "grid":
                        return self.get_cached_icon(f"{placeholder_name}_placeholder", placeholder_color)
                    else:
                        return self.get_cached_icon(placeholder_name, placeholder_color, size=18)

                if self._view_mode == "grid":
                    return self.get_cached_icon("travel_explore.svg_placeholder", "#3498db")
                else:
                    return self.get_cached_icon("travel_explore.svg", "#3498db", size=18)

            # Si es local y es video/imagen, cargar miniatura
            # En modo lista se pide una miniatura pequeña (18px) para que la fila no se
            # infle con el ícono de 256px pensado para la cuadrícula.
            thumb_size = 256 if self._view_mode == "grid" else 18
            thumb_mgr = ThumbnailCacheManager.get_instance()
            cached_icon = thumb_mgr.get_cached_qicon(file_path, thumb_size)

            if cached_icon:
                return cached_icon
            else:
                # Solicitar la miniatura de forma asíncrona
                thumb_mgr.request_thumbnail(file_path, tipo, thumb_size)
                
                # Devolver ícono por defecto mientras carga
                if self._view_mode == "grid":
                    if tipo == "video": return self.get_cached_icon("movie.svg_placeholder", "#9b59b6")
                    elif tipo == "imagen": return self.get_cached_icon("image.svg_placeholder", "#2ecc71")
                    elif tipo == "audio": return self.get_cached_icon("music_note.svg_placeholder", "#3498db")
                else:
                    if tipo == "video": return self.get_cached_icon("movie.svg", "#9b59b6", size=18)
                    elif tipo == "imagen": return self.get_cached_icon("image.svg", "#2ecc71", size=18)
                    elif tipo == "audio": return self.get_cached_icon("music_note.svg", "#3498db", size=18)

        elif role == Qt.SizeHintRole:
            if self._view_mode == "grid" and col == 0:
                return self._grid_size_hint
            elif self._view_mode == "list":
                return QSize(-1, 26)

        elif role == Qt.ForegroundRole:
            if tipo == "load_more":
                return QColor(get_theme_token("acento_primario", "#B9E640"))
            if col == 1 and tipo == "load_more":
                return QColor(get_theme_token("acento_primario", "#B9E640"))
            
        elif role == Qt.FontRole:
            if tipo == "load_more":
                f = QFont()
                f.setBold(True)
                return f
        
        elif role == Qt.TextAlignmentRole:
            if tipo == "empty":
                return Qt.AlignCenter
            if tipo == "load_more" and self._view_mode == "grid":
                return Qt.AlignCenter
                
        return None
        
    def _on_thumbnail_loaded(self, file_path: str, thumbnail_path: str):
        """Se llama cuando una miniatura se ha cacheado exitosamente."""
        for i, item in enumerate(self._media_items):
            if item.get("ruta") == file_path:
                idx = self.index(i, 0)
                self.dataChanged.emit(idx, idx, [Qt.DecorationRole])
                
    def _on_waveform_loaded(self, file_path: str, peaks: list):
        """Se llama cuando una onda de audio se ha procesado exitosamente."""
        for i, item in enumerate(self._media_items):
            is_web = item.get("source") == "Freesound" or item.get("is_web", False)
            ruta = item.get("dest_path") if is_web else item.get("ruta")
            if ruta == file_path:
                idx = self.index(i, 0)
                self.dataChanged.emit(idx, idx, [Qt.DecorationRole])

    def _on_freesound_waveform_loaded(self, waveform_url: str, peaks: list):
        """Se llama cuando los picos de Freesound se descargan en segundo plano."""
        for i, item in enumerate(self._media_items):
            is_web = item.get("source") == "Freesound" or item.get("is_web", False)
            if is_web and "images" in item and item["images"].get("waveform_m") == waveform_url:
                idx = self.index(i, 0)
                self.dataChanged.emit(idx, idx, [Qt.DecorationRole])

    def _on_remote_thumbnail_loaded(self, thumb_url: str, local_path: str):
        """Se llama cuando una miniatura de un origen web (ej. thumburl de Wikimedia) termina
        de descargarse y cachearse localmente."""
        for i, item in enumerate(self._media_items):
            if item.get("thumb_url") == thumb_url:
                idx = self.index(i, 0)
                self.dataChanged.emit(idx, idx, [Qt.DecorationRole])

    def set_data(self, media_items):
        """Reemplaza los datos del modelo."""
        # Detectar un cambio REAL de contexto (carpeta, colección, filtro de tipo o
        # búsqueda) y no una carga incremental de más del mismo listado ("Cargar más"/
        # scroll infinito, donde old_paths ⊆ new_paths porque solo se agregan elementos
        # al final del mismo conjunto ya filtrado/ordenado). En un cambio real, purgar del
        # pool de fondo las miniaturas/waveforms aún no iniciadas: ya no son relevantes y
        # estaban bloqueando en cola —por orden FIFO de llegada— a los archivos de la
        # carpeta/filtro/búsqueda nueva.
        old_paths = {item.get("ruta") for item in self._media_items if item.get("ruta")}
        new_paths = {item.get("ruta") for item in media_items if item.get("ruta")}
        if old_paths and not old_paths.issubset(new_paths):
            ThumbnailCacheManager.get_instance().purge_stale_background()
            from core.tabs.editing_media.waveform_cache_manager import WaveformCacheManager
            WaveformCacheManager.get_instance().purge_stale_background()

        self.beginResetModel()
        self._media_items = media_items
        self._path_to_row = {}
        for idx, item in enumerate(self._media_items):
            if "ruta" in item:
                self._path_to_row[item["ruta"]] = idx
        self.endResetModel()

    def append_items(self, new_items: list, replace_trailing_sentinel: bool = True):
        """Agrega ítems al final sin resetear el modelo -- usado cuando "Cargar más"
        extiende el mismo listado ya mostrado, para no perder la posición de scroll
        ni la selección (a diferencia de set_data(), pensado para reemplazos reales
        de contexto: carpeta/colección/filtro/búsqueda distintos, donde sí hace
        falta el reset completo)."""
        if replace_trailing_sentinel and self._media_items and \
                self._media_items[-1].get("tipo") in ("load_more", "empty"):
            last_row = len(self._media_items) - 1
            self.beginRemoveRows(QModelIndex(), last_row, last_row)
            self._media_items.pop()
            self.endRemoveRows()

        if not new_items:
            return
        first_row = len(self._media_items)
        last_row = first_row + len(new_items) - 1
        self.beginInsertRows(QModelIndex(), first_row, last_row)
        self._media_items.extend(new_items)
        for idx, item in enumerate(new_items, start=first_row):
            if "ruta" in item:
                self._path_to_row[item["ruta"]] = idx
        self.endInsertRows()

    def get_item(self, index: QModelIndex):
        if index.isValid() and 0 <= index.row() < len(self._media_items):
            return self._media_items[index.row()]
        return None

    def get_item_by_row(self, row: int):
        if 0 <= row < len(self._media_items):
            return self._media_items[row]
        return None

    def find_item_index_by_path(self, path: str):
        if hasattr(self, "_path_to_row") and path in self._path_to_row:
            return self.index(self._path_to_row[path], 0)
        return QModelIndex()

    def sort(self, column: int, order=Qt.AscendingOrder):
        """Implementación nativa de ordenamiento para soportar clics en las cabeceras de QTreeView."""
        is_remote = False
        if len(self._media_items) > 0:
            for item in self._media_items:
                if item.get("tipo") not in ("empty", "load_more"):
                    is_remote = item.get("es_remoto", False) or item.get("ruta", "").startswith("http")
                    break
                    
        if not is_remote:
            self.global_sort_requested.emit(column, order == Qt.AscendingOrder)
            return

        self.layoutAboutToBeChanged.emit()
        
        reverse = (order == Qt.DescendingOrder)
        
        def safe_float(val):
            try: return float(val)
            except: return 0.0

        if column == 1: # Nombre de Archivo
            key_func = lambda item: item.get("nombre", "").lower()
        elif column == 2: # Descripción (Web) / Tamaño (Local)
            if not getattr(self, "_is_online_mode", False):
                key_func = lambda item: safe_float(item.get("size_bytes", 0))
            else:
                key_func = lambda item: item.get("description", "").lower()
        elif column == 3: # Licencia (Web) / Tipo de Archivo (Local)
            if not getattr(self, "_is_online_mode", False):
                key_func = lambda item: item.get("file_type", "").lower()
            else:
                key_func = lambda item: item.get("license", "").lower()
        elif column == 4: # Duración (Web) / Fecha Modificación (Local)
            if not getattr(self, "_is_online_mode", False):
                key_func = lambda item: safe_float(item.get("mtime", 0))
            else:
                def dur_key(item):
                    if "duration" in item:
                        return safe_float(item["duration"])
                    if "duración" in item:
                        dur_str = str(item["duración"])
                        if ":" in dur_str:
                            parts = dur_str.split(":")
                            if len(parts) == 2:
                                return safe_float(parts[0])*60 + safe_float(parts[1])
                    return 0.0
                key_func = dur_key
        elif column == 5: # Origen (Web) / Ruta (Local)
            if not getattr(self, "_is_online_mode", False):
                key_func = lambda item: item.get("ruta", "").lower()
            else:
                key_func = lambda item: item.get("library", "Local").lower()
        elif column == 6: # Tipo de Archivo
            key_func = lambda item: item.get("file_type", "").lower()
        elif column == 7: # Detalles
            key_func = lambda item: str(item.get("detalles_audio", item.get("detalles_video", item.get("sample_rate", "")))).lower()
        else: # Estado o fallback (columna 0)
            key_func = lambda item: str(item.get("estado", "")).lower()

        # Separar los ítems normales de los ítems de estado (load_more, empty)
        normal_items = []
        special_items = []
        for item in self._media_items:
            if item.get("tipo") in ("load_more", "empty"):
                special_items.append(item)
            else:
                normal_items.append(item)
                
        # Ordenar sólo los ítems normales
        normal_items.sort(key=key_func, reverse=reverse)
        
        # Volver a unirlos manteniendo siempre los especiales al final
        self._media_items = normal_items + special_items
        
        # Re-construir índices
        self._path_to_row = {}
        for idx, item in enumerate(self._media_items):
            if "ruta" in item:
                self._path_to_row[item["ruta"]] = idx
                
        self.layoutChanged.emit()
