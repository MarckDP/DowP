# src/gui/tabs/video_tools/media_queue_widget.py
from PySide6.QtCore import QCoreApplication
import os
import mimetypes
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QPushButton,
    QTreeView,
    QHeaderView,
    QLabel,
    QFrame,
    QAbstractItemView,
    QMenu,
    QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QSize, QUrl, QThread, QAbstractTableModel, QModelIndex, QEvent
from PySide6.QtGui import QIcon, QDragEnterEvent, QDropEvent

from gui.styles import get_theme_token, create_colored_circle_icon
from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon
from core.tabs.editing_media.thumbnail_cache_manager import ThumbnailCacheManager
from core.tabs.editing_media.waveform_cache_manager import WaveformCacheManager
from core.tabs.editing_media.editing_media_logic import format_size
from core.logger.logger_manager import logger

# Backing store: QAbstractTableModel + QTreeView, NO QTreeWidget -- con QTreeWidget,
# add_files() creaba un QTreeWidgetItem POR ARCHIVO, en vivo (con el árbol ya como
# padre), más un os.path.getsize() y un chequeo de caché de miniatura/waveform
# síncronos por archivo, todo en el hilo de UI -- con miles de archivos eso colgaba
# la app por minutos (mismo diagnóstico que gui/tabs/image_tools/image_queue_widget.py,
# ImageQueueWidget es "copia adaptada" de este archivo, así que compartía el mismo
# problema). El modelo/vista es perezoso de verdad (miniatura/waveform/tamaño se
# calculan recién cuando ESA fila se pinta, no al agregarla) y una importación grande
# termina en un solo beginResetModel()/endResetModel() -- mismo principio que ya
# prueba el Gestor de Medios con decenas de miles de archivos sin colgarse, ver
# gui/tabs/editing_media/media_model.py::MediaTableModel.

_STATUS_COLOR_MAP_CACHE = None

def _status_color_map() -> dict:
    """TRAMPA DE TRADUCCIÓN (ver memoria i18n-dowp-workflow.md, trampa #7 -- mismo
    bug ya encontrado y arreglado en [Combinado]/[Multi-Idioma] de
    core/utils/format_manager.py y en gui/tabs/image_tools/image_queue_widget.py,
    del que este archivo es el original copiado): estas claves NO pueden quedar
    fijas en español. El texto real de estado llega ya traducido, vía self.tr(),
    desde VideoToolsTab (Completado/Procesando.../Cancelado/Error/Finalizado) y
    _QueueTableModel (Pendiente) -- en inglés "Completado" pasa a ser
    "Completed", la búsqueda de "completado" como substring dejaba de encontrar
    nada, y el círculo quedaba siempre en el color por defecto (gris), sin
    importar el estado real. Acá se traduce con el MISMO contexto/cadena que usan
    esas clases, así generador y buscador siempre coinciden sea cual sea el
    idioma activo. Memoizado (no a nivel de módulo): el cambio de idioma en DowP
    exige reiniciar la app, así que alcanza con calcularlo una sola vez, la
    primera vez que se pinta un ítem.
    "completado (" (con la salvedad entre paréntesis, ver video_tools_view.py::
    _on_job_status) tiene que seguir yendo ANTES que "completado" a secas: el
    loop de abajo devuelve el primer match, y "completado (...)" contiene
    "completado" como substring - sin este orden, un completado-con-advertencia
    se pintaria verde igual."""
    global _STATUS_COLOR_MAP_CACHE
    if _STATUS_COLOR_MAP_CACHE is None:
        tr = QCoreApplication.translate
        completado = tr("VideoToolsTab", "Completado").lower()
        _STATUS_COLOR_MAP_CACHE = {
            f"{completado} (": "estado_aviso",
            tr("_QueueTableModel", "Pendiente").lower(): "estado_espera",
            "en cola": "estado_espera",  # sin uso real hoy, se deja tal cual
            tr("VideoToolsTab", "Procesando...").lower().rstrip("."): "estado_aviso",
            completado: "estado_exito",
            tr("VideoToolsTab", "Finalizado").lower(): "estado_exito",
            tr("VideoToolsTab", "Error").lower(): "estado_error",
            tr("VideoToolsTab", "Cancelado").lower(): "estado_espera",
        }
    return _STATUS_COLOR_MAP_CACHE

def _get_status_icon(status_text: str):
    clean = (status_text or "").lower().strip()
    token_key = "estado_espera"
    for key, token in _status_color_map().items():
        if key in clean:
            token_key = token
            break
    color = get_theme_token(token_key, "#888888")
    return create_colored_circle_icon(color, size=10)


def _accent_rgba(alpha: int) -> str:
    """Convierte el color de acento del tema a 'rgba(r,g,b,a)', igual que en el Gestor de
    Medios (editing_media_view.py), para fondos de hover/selección con buen contraste."""
    from PySide6.QtGui import QColor
    color = QColor(get_theme_token('acento_primario', '#B9E640'))
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha})"

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".m4v"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a", ".opus", ".wma"}
SUPPORTED_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS

# Mismos colores que usa el Gestor de Medios (media_model.py) para estos íconos.
_VIDEO_ICON_COLOR = "#9b59b6"
_AUDIO_ICON_COLOR = "#3498db"
_ROW_THUMB_SIZE = 18  # px, cuadrado (miniatura de video)
_ROW_WAVEFORM_SIZE = QSize(32, 18)  # icono de waveform rápida (audio)

_HEADERS = (QCoreApplication.translate("media_queue_widget", "Nombre"), QCoreApplication.translate("media_queue_widget", "Tipo"), QCoreApplication.translate("media_queue_widget", "Tamaño"), QCoreApplication.translate("media_queue_widget", "Estado"))

# Una fila de la cola se identifica por una CLAVE, no por su ruta: el mismo archivo puede
# estar varias veces con recortes distintos (ej. dos clips del mismo medio enviados desde
# la línea de tiempo de Premiere, cada uno con su corte). Para la primera aparición la
# clave ES la ruta, así que todo lo que ya existía sigue funcionando igual; a partir de la
# segunda se le añade este marcador con el número de aparición. El separador usa \x00,
# que ningún sistema de archivos admite dentro de un nombre, para que nunca pueda chocar
# con una ruta real.
_ENTRY_MARKER = "\x00#"


def entry_path(entry_key: str) -> str:
    """Ruta real en disco de una entrada de la cola (ver _ENTRY_MARKER)."""
    if not entry_key:
        return entry_key
    return entry_key.split(_ENTRY_MARKER, 1)[0]


def entry_occurrence(entry_key: str) -> int:
    """1 para la primera aparición de un archivo, 2, 3... para las siguientes."""
    if not entry_key or _ENTRY_MARKER not in entry_key:
        return 1
    try:
        return int(entry_key.split(_ENTRY_MARKER, 1)[1])
    except ValueError:
        return 1


class _QueueTableModel(QAbstractTableModel):
    """Lista de paths (strings) -- nunca un widget por fila. `data()` es perezoso
    (miniatura/waveform/tamaño se calculan/cachean recién la primera vez que Qt
    pinta esa fila). `set_rows()` es un solo reset para todo el lote en vez de
    insertar de a una fila."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # Todos estos dicts van indexados por CLAVE de entrada, no por ruta (ver
        # _ENTRY_MARKER): dos filas del mismo archivo tienen estado propio.
        self._paths: list[str] = []
        self._path_to_row: dict[str, int] = {}
        self._sizes: dict[str, str] = {}     # cache perezoso: clave -> "x.y MB"
        self._statuses: dict[str, str] = {}  # clave -> texto de estado (sobrevive a los resets, ver set_rows)
        self._icon_cache = {}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._paths)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(_HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole and 0 <= section < len(_HEADERS):
            return self.tr(_HEADERS[section])
        return None

    def set_rows(self, paths: list[str]):
        self.beginResetModel()
        self._paths = list(paths)
        self._path_to_row = {p: i for i, p in enumerate(self._paths)}
        self.endResetModel()

    def path_at(self, row: int) -> str | None:
        if 0 <= row < len(self._paths):
            return self._paths[row]
        return None

    def rows_for_path(self, file_path: str) -> list:
        """Filas que apuntan al mismo archivo en disco (puede haber varias)."""
        return [row for row, key in enumerate(self._paths) if entry_path(key) == file_path]

    def update_status(self, path: str, status_text: str):
        self._statuses[path] = status_text
        row = self._path_to_row.get(path)
        if row is not None:
            idx = self.index(row, 3)
            self.dataChanged.emit(idx, idx, [Qt.DisplayRole, Qt.DecorationRole])

    def on_media_icon_loaded(self, file_path: str):
        """Conectado a thumbnail_loaded (video) Y waveform_loaded (audio) -- ambos
        solo necesitan invalidar el ícono (columna 0) de esa fila. Llega una RUTA real,
        que puede corresponder a más de una fila si el archivo está repetido con recortes
        distintos."""
        for row in self.rows_for_path(file_path):
            idx = self.index(row, 0)
            self.dataChanged.emit(idx, idx, [Qt.DecorationRole])

    def _fallback_icon(self, svg_name: str, color: str, size: int = 18):
        key = (svg_name, color, size)
        if key not in self._icon_cache:
            self._icon_cache[key] = get_colored_svg_icon(svg_name, color, size=size)
        return self._icon_cache[key]

    def _size_str(self, entry_key: str) -> str:
        cached = self._sizes.get(entry_key)
        if cached is not None:
            return cached
        path = entry_path(entry_key)
        try:
            # Mismo formato que el Gestor de Medios (format_size, KB para archivos
            # chicos en vez de forzar siempre MB, ver editing_media_logic.py).
            s = format_size(os.path.getsize(path))
        except Exception:
            s = "N/A"
        self._sizes[entry_key] = s
        return s

    def _icon_for(self, entry_key: str):
        """Ícono por defecto de la fila: nota musical (audio) / claqueta (video) como
        placeholder inmediato, sustituido por una miniatura real o una waveform rápida
        en cuanto termina de generarse en segundo plano (igual que en el Gestor de
        Medios) -- perezoso, se llama solo desde data() para filas visibles."""
        path = entry_path(entry_key)
        ext_lower = os.path.splitext(path)[1].lower()
        if ext_lower in AUDIO_EXTENSIONS:
            wf_mgr = WaveformCacheManager.get_instance()
            cached = wf_mgr.get_cached_qicon(path, _ROW_WAVEFORM_SIZE)
            if cached is not None:
                return cached
            wf_mgr.request_waveform(path, size=_ROW_WAVEFORM_SIZE)
            return self._fallback_icon("music_note.svg", _AUDIO_ICON_COLOR)

        thumb_mgr = ThumbnailCacheManager.get_instance()
        cached = thumb_mgr.get_cached_qicon(path, _ROW_THUMB_SIZE)
        if cached is not None:
            return cached
        thumb_mgr.request_thumbnail(path, "video", _ROW_THUMB_SIZE)
        return self._fallback_icon("movie.svg", _VIDEO_ICON_COLOR)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        entry_key = self._paths[row]
        path = entry_path(entry_key)
        occurrence = entry_occurrence(entry_key)

        if col == 0:
            if role == Qt.DisplayRole:
                name = os.path.basename(path)
                # La repetición se numera a la vista para que dos filas del mismo archivo
                # con recortes distintos no parezcan un duplicado accidental.
                return name if occurrence == 1 else f"{name}  ({occurrence})"
            if role == Qt.DecorationRole:
                return self._icon_for(entry_key)
            if role == Qt.UserRole:
                return entry_key
            if role == Qt.ToolTipRole:
                return path
        elif col == 1:
            if role == Qt.DisplayRole:
                return os.path.splitext(path)[1].upper().replace(".", "")
        elif col == 2:
            if role == Qt.DisplayRole:
                return self._size_str(entry_key)
        elif col == 3:
            status = self._statuses.get(entry_key) or self.tr("Pendiente")
            if role == Qt.DisplayRole:
                return status
            if role == Qt.DecorationRole:
                return _get_status_icon(status)
        return None


class _PathScanThread(QThread):
    """Escanea en un hilo de fondo una lista de rutas (archivos y/o carpetas) --
    evita que os.walk() de una carpeta enorme bloquee la UI al arrastrarla o
    elegirla desde "Agregar Carpeta"."""
    finished_scan = Signal(list)

    def __init__(self, paths: list[str], parent=None):
        super().__init__(parent)
        self._paths = paths

    def run(self):
        valid_paths = []
        for p in self._paths:
            if os.path.isdir(p):
                for root, _, files in os.walk(p):
                    for f in files:
                        ext = os.path.splitext(f)[1].lower()
                        if ext in SUPPORTED_EXTENSIONS:
                            valid_paths.append(os.path.join(root, f))
            else:
                ext = os.path.splitext(p)[1].lower()
                if ext in SUPPORTED_EXTENSIONS:
                    valid_paths.append(p)
        self.finished_scan.emit(valid_paths)


class MediaQueueWidget(QFrame):
    """
    Widget de la cola de archivos multimedia (Columna Izquierda / Master).
    Permite importar archivos por Drag and Drop o explorador, mostrando
    metadatos detallados y sincronizando la seleccion con la vista previa.
    """
    file_selected = Signal(str)  # Emite la ruta del archivo seleccionado
    queue_updated = Signal(int) # Emite la cantidad de archivos en cola

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("mediaQueueWidget")
        self.setAcceptDrops(True)
        self.files_list = []
        self._path_set = set()
        self._scan_thread = None
        self._init_ui()

        ThumbnailCacheManager.get_instance().thumbnail_loaded.connect(
            lambda file_path, _thumb_path: self._model.on_media_icon_loaded(file_path)
        )
        WaveformCacheManager.get_instance().waveform_loaded.connect(
            lambda file_path, _peaks: self._model.on_media_icon_loaded(file_path)
        )

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Estilo del contenedor
        bg_color = get_theme_token('fondo_secundario', '#1e1e1e')
        border_color = get_theme_token('borde_normal', '#2d2d2d')
        self.setStyleSheet(f"""
            QFrame#mediaQueueWidget {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: 6px;
            }}
        """)

        # Cabecera de la Lista de Medios
        header_grid = QGridLayout()
        header_grid.setContentsMargins(4, 2, 4, 2)

        self.lbl_title = QLabel(self.tr("Lista de Medios"), self)
        self.lbl_title.setObjectName("sectionTitle")
        self.lbl_title.setAlignment(Qt.AlignCenter)

        self.lbl_count = QLabel(self.tr("0 archivos"), self)
        self.lbl_count.setStyleSheet(f"color: {get_theme_token('texto_secundario', '#888888')}; font-size: 11px;")
        self.lbl_count.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        header_grid.addWidget(self.lbl_title, 0, 0, 1, 3, Qt.AlignCenter)
        header_grid.addWidget(self.lbl_count, 0, 2, Qt.AlignRight | Qt.AlignVCenter)
        layout.addLayout(header_grid)

        # Barra de Botones de Importación
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)

        self.btn_add_files = QPushButton(self.tr("Archivos"))
        self.btn_add_files.setProperty("variant", "secondary")
        self.btn_add_files.setCursor(Qt.PointingHandCursor)
        self.btn_add_files.setToolTip(self.tr("Agregar archivos multimedia"))
        self.btn_add_files.clicked.connect(self._on_add_files_clicked)

        self.btn_add_folder = QPushButton(self.tr("Carpetas"))
        self.btn_add_folder.setProperty("variant", "secondary")
        self.btn_add_folder.setCursor(Qt.PointingHandCursor)
        self.btn_add_folder.setToolTip(self.tr("Agregar todos los medios de una carpeta"))
        self.btn_add_folder.clicked.connect(self._on_add_folder_clicked)

        self.btn_clear = QPushButton(self.tr("Limpiar Todo"))
        self.btn_clear.setProperty("variant", "danger")
        self.btn_clear.setCursor(Qt.PointingHandCursor)
        self.btn_clear.clicked.connect(self.clear_queue)

        btn_layout.addWidget(self.btn_add_files)
        btn_layout.addWidget(self.btn_add_folder)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_clear)
        layout.addLayout(btn_layout)

        # Árbol de Archivos (QTreeView + modelo) — mismo estilo visual que la lista de
        # medios en "modo lista" del Gestor de Medios (QTreeView#mediaTableWidget en
        # editing_media_view.py), y ahora también el mismo tipo de backing store.
        self._model = _QueueTableModel(self)

        self.tree = QTreeView()
        self.tree.setObjectName("mediaQueueTree")
        self.tree.setModel(self._model)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(0)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setAlternatingRowColors(True)
        self.tree.setIconSize(QSize(32, 18))
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.selectionModel().selectionChanged.connect(self._on_selection_changed)
        # Suprimir/Backspace con foco en la lista elimina la selección actual de la
        # cola (no del disco) -- mismo criterio que "Eliminar de la cola" del menú
        # contextual (ver remove_selected). QTreeView es una clase de Qt, no una
        # subclase propia, así que se intercepta vía eventFilter en vez de
        # sobreescribir keyPressEvent directamente.
        self.tree.installEventFilter(self)

        self.tree.setStyleSheet(f"""
            QTreeView#mediaQueueTree {{
                background-color: {get_theme_token('fondo_principal', '#0a0a0a')};
                border: 1px solid {border_color};
                padding: 0px;
                color: {get_theme_token('texto_principal', '#cdd6f4')};
                font-size: 12px;
                alternate-background-color: {get_theme_token('fondo_secundario', '#121212')};
                outline: none;
            }}
            QTreeView#mediaQueueTree::branch {{
                background: transparent;
            }}
            QTreeView#mediaQueueTree::item {{
                padding: 4px 8px;
                border-bottom: 1px solid {get_theme_token('borde_normal', '#1f1f23')};
                color: {get_theme_token('texto_principal', '#cdd6f4')};
            }}
            QTreeView#mediaQueueTree::item:hover {{
                background-color: {_accent_rgba(22)};
            }}
            QTreeView#mediaQueueTree::item:selected {{
                background-color: {_accent_rgba(60)};
                border-top: 1px solid {get_theme_token('acento_primario', '#B9E640')};
                border-bottom: 1px solid {get_theme_token('acento_primario', '#B9E640')};
                color: {get_theme_token('acento_primario', '#B9E640')};
                font-weight: bold;
            }}
            QHeaderView::section {{
                background-color: {get_theme_token('fondo_elemento', '#1c1c1e')};
                color: {get_theme_token('texto_secundario', '#a6adc8')};
                padding: 6px 8px;
                border: none;
                border-right: 1px solid {border_color};
                border-bottom: 1px solid {get_theme_token('acento_primario', '#B9E640')};
                font-weight: bold;
                font-size: 11px;
                text-transform: uppercase;
            }}
            QHeaderView::section:hover {{
                background-color: {get_theme_token('seleccion_fondo', '#2d2d2d')};
                color: {get_theme_token('acento_primario', '#B9E640')};
            }}
        """)

        # Configurar cabeceras - Interactive en las 4 columnas (igual que el Gestor de
        # Medios, editing_media_view.py::media_table, que no fija Stretch/
        # ResizeToContents y deja que el usuario arrastre cada columna a gusto). Antes
        # Nombre estaba en Stretch y el resto en ResizeToContents, así que ninguna se
        # podía redimensionar a mano (ver conversación). stretchLastSection en True
        # para que Estado (la última) absorba por defecto el espacio horizontal
        # sobrante en vez de dejarlo vacío -- no bloquea el resize manual, el usuario
        # igual puede arrastrar el borde entre Peso y Estado para ajustar ambas.
        header = self.tree.header()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        header.setSectionResizeMode(3, QHeaderView.Interactive)
        self.tree.setColumnWidth(0, 220)  # Nombre
        self.tree.setColumnWidth(1, 70)   # Tipo
        self.tree.setColumnWidth(2, 90)   # Tamaño
        self.tree.setColumnWidth(3, 150)  # Estado

        layout.addWidget(self.tree, 1)

        # Mensaje de arrastre (Drop zone visual)
        self.lbl_drop_hint = QLabel(self.tr("Arrastra archivos de vídeo o audio aquí"))
        self.lbl_drop_hint.setAlignment(Qt.AlignCenter)
        self.lbl_drop_hint.setStyleSheet(f"""
            color: {get_theme_token('texto_secundario', '#888888')};
            border: 1px dashed {border_color};
            border-radius: 6px;
            padding: 8px;
            font-size: 11px;
        """)
        layout.addWidget(self.lbl_drop_hint)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        paths = [url.toLocalFile() for url in urls if url.isLocalFile()]
        if paths:
            self._start_scan(paths)
            event.acceptProposedAction()

    def _on_add_files_clicked(self):
        from PySide6.QtWidgets import QFileDialog
        filter_str = self.tr("Archivos Multimedia (*.mp4 *.mkv *.mov *.avi *.webm *.mp3 *.wav *.aac *.flac *.ogg);;Todos los archivos (*.*)")
        files, _ = QFileDialog.getOpenFileNames(self, self.tr("Seleccionar Archivos Multimedia"), "", filter_str)
        if files:
            self.add_files(files)

    def _on_add_folder_clicked(self):
        from PySide6.QtWidgets import QFileDialog
        folder = QFileDialog.getExistingDirectory(self, self.tr("Seleccionar Carpeta con Medios"))
        if folder:
            self._start_scan([folder])

    def _start_scan(self, paths: list[str]):
        """Enumera archivos/carpetas en un hilo de fondo (ver _PathScanThread) --
        ni siquiera el os.walk() de una carpeta enorme debe bloquear la UI."""
        self._scan_thread = _PathScanThread(paths, self)
        self._scan_thread.finished_scan.connect(self._on_scan_finished)
        self._scan_thread.start()

    def _on_scan_finished(self, valid_paths: list[str]):
        if valid_paths:
            self.add_files(valid_paths)

    def next_entry_key(self, path: str) -> str:
        """Clave libre para `path`: la ruta tal cual si es su primera aparición, o la ruta
        con el marcador de repetición si ya está en la cola (ver _ENTRY_MARKER)."""
        if path not in self._path_set:
            return path
        occurrence = 2
        while f"{path}{_ENTRY_MARKER}{occurrence}" in self._path_set:
            occurrence += 1
        return f"{path}{_ENTRY_MARKER}{occurrence}"

    def add_files(self, paths, allow_duplicates=False):
        """allow_duplicates=True agrega el archivo aunque ya esté en la cola, como una
        entrada aparte con su propio recorte y estado. Lo usa el envío desde la línea de
        tiempo del editor, donde dos clips del MISMO medio con cortes distintos son dos
        trabajos distintos; el resto de vías (arrastrar, explorador) sigue deduplicando."""
        if allow_duplicates:
            new_paths = []
            for p in paths:
                key = self.next_entry_key(p)
                new_paths.append(key)
                self._path_set.add(key)
        else:
            # Se deduplica contra la cola Y dentro del propio lote: sin lo segundo, pasar
            # dos veces la misma ruta en una sola llamada creaba dos filas iguales.
            seen = set(self._path_set)
            new_paths = []
            for p in paths:
                if p in seen:
                    continue
                seen.add(p)
                new_paths.append(p)
        if not new_paths:
            return []
        self.files_list.extend(new_paths)
        self._path_set.update(new_paths)
        # Un solo reset para todo el lote -- nada de construir un item por
        # archivo (ver _QueueTableModel, esto es lo que evita el colgado con
        # miles de archivos).
        self._model.set_rows(self.files_list)
        self._update_counter()
        if self.files_list and not self.tree.selectionModel().hasSelection():
            self.tree.setCurrentIndex(self._model.index(0, 0))
        # Las claves de las filas recien agregadas, en orden: quien las agrego necesita
        # poder asociarles datos propios (p.ej. el recorte que vino del editor).
        return new_paths

    def select_entry(self, entry_key: str):
        """Deja seleccionada esa fila (y por tanto cargada en la vista previa)."""
        try:
            row = self.files_list.index(entry_key)
        except ValueError:
            return
        self.tree.setCurrentIndex(self._model.index(row, 0))
        self.tree.scrollTo(self._model.index(row, 0))

    def clear_queue(self):
        self.files_list.clear()
        self._path_set.clear()
        self._model.set_rows([])
        self._update_counter()
        self.file_selected.emit("")

    def eventFilter(self, obj, event):
        if obj is self.tree and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
                self.remove_selected()
                return True
        return super().eventFilter(obj, event)

    def remove_selected(self):
        rows = sorted({idx.row() for idx in self.tree.selectionModel().selectedRows()})
        removed_paths = [self._model.path_at(r) for r in rows]
        for path in removed_paths:
            if path is None:
                continue
            if path in self._path_set:
                self.files_list.remove(path)
                self._path_set.discard(path)
        self._model.set_rows(self.files_list)
        self._update_counter()

    def get_all_filepaths(self):
        """Claves de entrada, en orden. Para la ruta real usar entry_path() -- coinciden
        salvo en las repeticiones del mismo archivo (ver _ENTRY_MARKER)."""
        return list(self.files_list)

    def _update_counter(self):
        count = len(self.files_list)
        self.lbl_count.setText(self.tr("{0} archivos").format(count))
        self.queue_updated.emit(count)
        self.lbl_drop_hint.setVisible(count == 0)

    def _on_selection_changed(self, *_args):
        indexes = self.tree.selectionModel().selectedRows()
        if indexes:
            self.file_selected.emit(self._model.path_at(indexes[0].row()) or "")
        else:
            self.file_selected.emit("")

    def _show_context_menu(self, pos):
        index = self.tree.indexAt(pos)
        if not index.isValid():
            return
        path = self._model.path_at(index.row())
        menu = QMenu(self)
        action_remove = menu.addAction(self.tr("Eliminar de la cola"))
        action_open_loc = menu.addAction(self.tr("Abrir ubicación del archivo"))

        action = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if action == action_remove:
            self.remove_selected()
        elif action == action_open_loc:
            path = entry_path(path)
            if path and os.path.exists(path):
                from PySide6.QtGui import QDesktopServices
                QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))

    def update_file_status(self, filepath: str, status_text: str):
        self._model.update_status(filepath, status_text)
