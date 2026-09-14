# src/gui/tabs/image_tools/image_queue_widget.py
from PySide6.QtCore import QCoreApplication
import os
import uuid
from datetime import datetime
from PySide6.QtWidgets import (
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
    QApplication,
    QMessageBox,
)
from PySide6.QtCore import Qt, Signal, QSize, QUrl, QThread, QAbstractTableModel, QModelIndex, QEvent
from PySide6.QtGui import QDragEnterEvent, QDropEvent

from gui.styles import get_theme_token, create_colored_circle_icon
from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon
from core.tabs.editing_media.thumbnail_cache_manager import ThumbnailCacheManager
from core.tabs.editing_media.editing_media_logic import VALID_IMAGE_EXTS, VALID_VECTOR_EXTS, format_size
from core.logger.logger_manager import logger
from core.utils.paths import get_pasted_images_dir

# Copia adaptada de gui/tabs/video_tools/media_queue_widget.py::MediaQueueWidget (misma
# estructura/estilo tal cual pidió el usuario) -- sin lo específico de video/audio
# (waveforms, distinción video/audio) y con el set de extensiones de imagen que ya
# soporta el Gestor de Medios (raster + RAW + vectoriales, ver editing_media_logic.py).
#
# Backing store: QAbstractTableModel + QTreeView, NO QTreeWidget -- con QTreeWidget,
# add_files() creaba un QTreeWidgetItem POR ARCHIVO, en vivo (con el árbol ya como
# padre), más un os.path.getsize() y un chequeo de caché de miniatura síncronos por
# archivo, todo en el hilo de UI -- con miles de archivos (reportado: ~6000) eso
# colgaba la app por minutos. El modelo/vista es perezoso de verdad (miniatura/tamaño
# se calculan recién cuando ESA fila se pinta, no al agregarla) y una importación
# grande termina en un solo beginResetModel()/endResetModel() -- mismo principio que
# ya prueba el Gestor de Medios con decenas de miles de archivos sin colgarse, ver
# gui/tabs/editing_media/media_model.py::MediaTableModel.

_STATUS_COLOR_MAP = {
    "completado (": "estado_aviso",
    "pendiente": "estado_espera",
    "en cola": "estado_espera",
    "procesando": "estado_aviso",
    "completado": "estado_exito",
    "finalizado": "estado_exito",
    "error": "estado_error",
    "cancelado": "estado_espera",
    "eliminado": "estado_error",
}

def _get_status_icon(status_text: str):
    clean = (status_text or "").lower().strip()
    token_key = "estado_espera"
    for key, token in _STATUS_COLOR_MAP.items():
        if key in clean:
            token_key = token
            break
    color = get_theme_token(token_key, "#888888")
    return create_colored_circle_icon(color, size=10)


def _accent_rgba(alpha: int) -> str:
    from PySide6.QtGui import QColor
    color = QColor(get_theme_token('acento_primario', '#B9E640'))
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha})"

SUPPORTED_EXTENSIONS = VALID_IMAGE_EXTS | VALID_VECTOR_EXTS

# Mismo color que usa el Gestor de Medios (media_model.py) para el ícono de "imagen".
_IMAGE_ICON_COLOR = "#2ecc71"
_ROW_THUMB_SIZE = 18  # px, cuadrado

_HEADERS = (QCoreApplication.translate("image_queue_widget", "Nombre"),
            QCoreApplication.translate("image_queue_widget", "Tipo"),
            QCoreApplication.translate("image_queue_widget", "Tamaño"),
            QCoreApplication.translate("image_queue_widget", "Estado"))


class _QueueTableModel(QAbstractTableModel):
    """Lista de paths (strings) -- nunca un widget por fila. `data()` es perezoso
    (miniatura/tamaño se calculan/cachean recién la primera vez que Qt pinta esa
    fila -- Qt solo llama a data() para las filas visibles en el viewport, no hace
    falta ninguna lógica propia de "qué fila está visible"). `set_rows()` es un
    solo reset para todo el lote en vez de insertar de a una fila."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._paths: list[str] = []
        self._path_to_row: dict[str, int] = {}
        self._sizes: dict[str, str] = {}     # cache perezoso: path -> "x.y MB"
        self._statuses: dict[str, str] = {}  # path -> texto de estado (sobrevive a los resets, ver set_rows)
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

    def update_status(self, path: str, status_text: str):
        """Llamado desde ImageQueueWidget.update_file_status() -- guarda el estado
        (persiste entre resets, a diferencia de _sizes que es solo cache) y emite
        dataChanged puntual de esa fila solamente, sin tocar el resto del modelo."""
        self._statuses[path] = status_text
        row = self._path_to_row.get(path)
        if row is not None:
            idx = self.index(row, 3)
            self.dataChanged.emit(idx, idx, [Qt.DisplayRole, Qt.DecorationRole])

    def on_thumbnail_loaded(self, file_path: str):
        row = self._path_to_row.get(file_path)
        if row is not None:
            idx = self.index(row, 0)
            self.dataChanged.emit(idx, idx, [Qt.DecorationRole])

    def _fallback_icon(self, svg_name: str, color: str, size: int = 18):
        key = (svg_name, color, size)
        if key not in self._icon_cache:
            self._icon_cache[key] = get_colored_svg_icon(svg_name, color, size=size)
        return self._icon_cache[key]

    def _size_str(self, path: str) -> str:
        cached = self._sizes.get(path)
        if cached is not None:
            return cached
        try:
            # Mismo formato que el Gestor de Medios (format_size, KB para archivos
            # chicos en vez de forzar siempre MB, ver editing_media_logic.py).
            s = format_size(os.path.getsize(path))
        except Exception:
            s = "N/A"
        self._sizes[path] = s
        return s

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        path = self._paths[row]

        if col == 0:
            if role == Qt.DisplayRole:
                return os.path.basename(path)
            if role == Qt.DecorationRole:
                thumb_mgr = ThumbnailCacheManager.get_instance()
                cached = thumb_mgr.get_cached_qicon(path, _ROW_THUMB_SIZE)
                if cached is not None:
                    return cached
                thumb_mgr.request_thumbnail(path, "imagen", _ROW_THUMB_SIZE)
                return self._fallback_icon("image.svg", _IMAGE_ICON_COLOR)
            if role == Qt.UserRole:
                return path
        elif col == 1:
            if role == Qt.DisplayRole:
                return os.path.splitext(path)[1].upper().replace(".", "")
        elif col == 2:
            if role == Qt.DisplayRole:
                return self._size_str(path)
        elif col == 3:
            status = self._statuses.get(path) or self.tr("Pendiente")
            if role == Qt.DisplayRole:
                return status
            if role == Qt.DecorationRole:
                return _get_status_icon(status)
        return None


class _PathScanThread(QThread):
    """Escanea en un hilo de fondo una lista de rutas (archivos y/o carpetas) --
    evita que os.walk() de una carpeta enorme bloquee la UI al arrastrarla o
    elegirla desde "Agregar Carpeta" (mismo espíritu que AsyncIndexerThread del
    Gestor de Medios, sin todo su aparato de índice persistente -- aquí es un uso
    único por importación)."""
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


class ImageQueueWidget(QFrame):
    """
    Cola de archivos de imagen (panel izquierdo del Editor de Imagen). Permite
    importar por Drag and Drop o explorador, sincronizando la selección con la
    vista previa. Misma estructura visual que MediaQueueWidget (Herramientas de
    Video), adaptada a imágenes.
    """
    file_selected = Signal(str)  # Emite la ruta del archivo seleccionado
    queue_updated = Signal(int)  # Emite la cantidad de archivos en cola

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("imageQueueWidget")
        self.setAcceptDrops(True)
        self.files_list = []
        self._path_set = set()
        self._scan_thread = None
        # filepath -> ruta del archivo ya convertido (ver set_output_path/
        # get_output_path) -- lo usa ImageToolsTab para saber si mostrar la vista
        # de comparación antes/después al seleccionar una fila.
        self._output_paths = {}
        # filepath -> título editado por el usuario (ver set_title/get_title) --
        # nombre base (sin extensión) que va a usar ImageConvertWorker para el
        # archivo de salida en vez del nombre original.
        self._titles = {}
        self._init_ui()

        ThumbnailCacheManager.get_instance().thumbnail_loaded.connect(self._model.on_thumbnail_loaded)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        bg_color = get_theme_token('fondo_secundario', '#1e1e1e')
        border_color = get_theme_token('borde_normal', '#2d2d2d')
        # Eliminado el estilo de tarjeta para permitir unificación externa
        self.setStyleSheet("""
            QFrame#imageQueueWidget {
                background-color: transparent;
                border: none;
            }
        """)

        header_grid = QGridLayout()
        header_grid.setContentsMargins(4, 2, 4, 2)

        self.lbl_title = QLabel(self.tr("Lista de Imágenes"), self)
        self.lbl_title.setObjectName("sectionTitle")
        self.lbl_title.setAlignment(Qt.AlignCenter)

        self.lbl_count = QLabel(self.tr("0 archivos"), self)
        self.lbl_count.setStyleSheet(f"color: {get_theme_token('texto_secundario', '#888888')}; font-size: 11px;")
        self.lbl_count.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        header_grid.addWidget(self.lbl_title, 0, 0, 1, 3, Qt.AlignCenter)
        header_grid.addWidget(self.lbl_count, 0, 2, Qt.AlignRight | Qt.AlignVCenter)
        layout.addLayout(header_grid)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)

        # Etiquetas cortas a propósito: este panel es angosto (~380px, ancho fijo del
        # panel izquierdo colapsable) -- con el texto largo original ("Agregar
        # Archivos"/"Agregar Carpeta"/"Limpiar Todo") la fila de botones sola pedía
        # ~588px de ancho mínimo, más que el panel entero, disparando un scroll
        # horizontal en todo el panel (QScrollArea de CollapsiblePanel). El texto
        # completo queda en el tooltip.
        self.btn_add_files = QPushButton(self.tr("Archivos"))
        self.btn_add_files.setProperty("variant", "secondary")
        self.btn_add_files.setCursor(Qt.PointingHandCursor)
        self.btn_add_files.setToolTip(self.tr("Agregar archivos de imagen"))
        self.btn_add_files.clicked.connect(self._on_add_files_clicked)

        self.btn_add_folder = QPushButton(self.tr("Carpetas"))
        self.btn_add_folder.setProperty("variant", "secondary")
        self.btn_add_folder.setCursor(Qt.PointingHandCursor)
        self.btn_add_folder.setToolTip(self.tr("Agregar todas las imágenes de una carpeta"))
        self.btn_add_folder.clicked.connect(self._on_add_folder_clicked)

        self.btn_clear = QPushButton(self.tr("Limpiar"))
        self.btn_clear.setProperty("variant", "danger")
        self.btn_clear.setCursor(Qt.PointingHandCursor)
        self.btn_clear.setToolTip(self.tr("Limpiar toda la lista"))
        self.btn_clear.clicked.connect(self.clear_queue)

        self.btn_paste = QPushButton(self.tr("Pegar"))
        # accent-solid (verde plano, hover lima) y no "secondary": Pegar es la vía de
        # entrada rápida de la cola -- se merece el mismo peso visual que el resto de
        # las acciones verdes de la app (carpeta, play, descargar), no el gris de los
        # botones neutros de al lado.
        self.btn_paste.setProperty("variant", "accent-solid")
        self.btn_paste.setCursor(Qt.PointingHandCursor)
        self.btn_paste.setToolTip(self.tr(
            "Pegar una imagen del portapapeles (captura de pantalla, \"copiar imagen\" "
            "del navegador, o archivos copiados en el explorador)"))
        self.btn_paste.clicked.connect(self._on_paste_clicked)

        btn_layout.addWidget(self.btn_add_files)
        btn_layout.addWidget(self.btn_add_folder)
        btn_layout.addWidget(self.btn_paste)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_clear)
        layout.addLayout(btn_layout)

        self._model = _QueueTableModel(self)

        self.tree = QTreeView()
        self.tree.setObjectName("imageQueueTree")
        self.tree.setModel(self._model)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(0)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setAlternatingRowColors(True)
        self.tree.setIconSize(QSize(18, 18))
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
            QTreeView#imageQueueTree {{
                background-color: {get_theme_token('fondo_principal', '#0a0a0a')};
                border: 1px solid {border_color};
                padding: 0px;
                color: {get_theme_token('texto_principal', '#cdd6f4')};
                font-size: 12px;
                alternate-background-color: {get_theme_token('fondo_secundario', '#121212')};
                outline: none;
            }}
            QTreeView#imageQueueTree::branch {{
                background: transparent;
            }}
            QTreeView#imageQueueTree::item {{
                padding: 4px 8px;
                border-bottom: 1px solid {get_theme_token('borde_normal', '#1f1f23')};
                color: {get_theme_token('texto_principal', '#cdd6f4')};
            }}
            QTreeView#imageQueueTree::item:hover {{
                background-color: {_accent_rgba(22)};
            }}
            QTreeView#imageQueueTree::item:selected {{
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

        header = self.tree.header()
        # Interactive en las 4 columnas para poder redimensionar cada una a mano
        # (ver comentario equivalente en MediaQueueWidget). stretchLastSection en
        # True para que Estado (la última) absorba por defecto el espacio horizontal
        # sobrante en vez de dejarlo vacío -- no bloquea el resize manual, el usuario
        # igual puede arrastrar el borde entre Peso y Estado para ajustar ambas.
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        header.setSectionResizeMode(3, QHeaderView.Interactive)
        # Anchos por defecto más chicos que MediaQueueWidget (que asumía un panel más
        # ancho): aquí el panel es angosto (~380px) -- estos igual son interactivos,
        # el usuario los puede agrandar a mano si hace falta.
        self.tree.setColumnWidth(0, 140)
        self.tree.setColumnWidth(1, 45)
        self.tree.setColumnWidth(2, 65)
        self.tree.setColumnWidth(3, 90)

        layout.addWidget(self.tree, 1)

        self.lbl_drop_hint = QLabel(self.tr("Arrastra archivos de imagen aquí"))
        self.lbl_drop_hint.setAlignment(Qt.AlignCenter)
        # Sin wrap, este texto en una sola línea pedía 370px de ancho mínimo -- más
        # que el panel angosto (~380px con margen incluido, ver comentario de los
        # botones más arriba).
        self.lbl_drop_hint.setWordWrap(True)
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
        exts_pattern = " ".join(f"*{e}" for e in sorted(SUPPORTED_EXTENSIONS))
        filter_str = self.tr("Archivos de Imagen ({0});;Todos los archivos (*.*)").format(exts_pattern)
        files, _ = QFileDialog.getOpenFileNames(self, self.tr("Seleccionar Archivos de Imagen"), "", filter_str)
        if files:
            self.add_files(files)

    def _on_add_folder_clicked(self):
        from PySide6.QtWidgets import QFileDialog
        folder = QFileDialog.getExistingDirectory(self, self.tr("Seleccionar Carpeta con Imágenes"))
        if folder:
            self._start_scan([folder])

    # ── Pegar desde el portapapeles ─────────────────────────────────────────
    def _on_paste_clicked(self):
        """Trae al Editor lo que haya en el portapapeles, sin depender del SO:
        QClipboard ya normaliza los formatos nativos (CF_DIB/PNG en Windows,
        TIFF/PNG en macOS, image/png en X11/Wayland).

        El ORDEN de comprobación es lo importante, y no es el intuitivo. Copiar una
        imagen desde el navegador deja a la vez un bitmap Y un text/uri-list con una
        URL remota (https://...), así que preguntar primero "¿hay URLs?" encontraría
        una que no es ningún archivo local y no pegaría nada. Por eso:

          1. Archivos locales de verdad (copiados en Explorador/Finder/Nautilus):
             se agregan por referencia, sin duplicar nada en disco ni perder su nombre.
          2. Un bitmap: eso sí hay que materializarlo, porque la cola trabaja con
             rutas (ver add_files) -- se guarda como PNG, que es sin pérdida y
             conserva la transparencia.
          3. Nada utilizable: se avisa, en vez de quedarse mudo."""
        clipboard = QApplication.clipboard()
        mime = clipboard.mimeData() if clipboard else None
        if mime is None:
            self._warn_clipboard_unusable()
            return

        local_paths = self._local_image_paths_from_mime(mime)
        if local_paths:
            self.add_files(local_paths)
            self._select_path(local_paths[-1])
            logger.info(f"Editor de Imagen: pegados {len(local_paths)} archivo(s) del portapapeles")
            return

        if mime.hasImage():
            image = clipboard.image()
            if not image.isNull():
                saved = self._save_pasted_image(image)
                if saved is None:
                    QMessageBox.warning(
                        self, self.tr("No se pudo pegar"),
                        self.tr("Había una imagen en el portapapeles, pero no se pudo "
                                "guardar en disco. Revisa el espacio libre y los permisos."),
                    )
                    return
                self.add_files([saved])
                self._select_path(saved)
                return

        self._warn_clipboard_unusable()

    def _local_image_paths_from_mime(self, mime) -> list[str]:
        """Rutas locales utilizables que traiga el portapapeles, en orden y sin
        repetir. Se descartan las URLs remotas (isLocalFile() False), lo que ya no
        existe en disco y lo que no sea una imagen soportada -- pegar un .docx
        copiado en el explorador no debería meterlo en la cola.

        También se mira el texto plano: copiar la ruta de un archivo desde una
        terminal o desde la barra del explorador es texto, no una URL, y viene con
        comillas alrededor bastante a menudo."""
        candidates = []
        if mime.hasUrls():
            candidates.extend(url.toLocalFile() for url in mime.urls() if url.isLocalFile())
        if mime.hasText():
            candidates.append(mime.text().strip().strip('"').strip("'"))

        paths, seen = [], set()
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            if os.path.splitext(candidate)[1].lower() not in SUPPORTED_EXTENSIONS:
                continue
            if not os.path.isfile(candidate):
                continue
            paths.append(candidate)
        return paths

    def _save_pasted_image(self, image) -> str | None:
        """Escribe el bitmap del portapapeles como PNG y devuelve su ruta (None
        si falla). El sufijo aleatorio evita pisar un pegado anterior del mismo
        segundo; el nombre queda legible porque es lo que se ve en la lista."""
        name = f"Pegado {datetime.now():%Y-%m-%d %H-%M-%S} {uuid.uuid4().hex[:4]}.png"
        path = os.path.join(get_pasted_images_dir(), name)
        try:
            if not image.save(path, "PNG"):
                logger.error(f"Editor de Imagen: QImage.save() falló al pegar en {path}")
                return None
        except Exception as e:
            logger.error(f"Editor de Imagen: no se pudo guardar la imagen pegada: {e}")
            return None
        logger.info(f"Editor de Imagen: imagen pegada del portapapeles -> {path} "
                    f"({image.width()}x{image.height()}, alfa={image.hasAlphaChannel()})")
        return path

    def _select_path(self, path: str):
        """Deja seleccionado lo recién pegado para que se vea al toque en la
        previsualización. add_files() solo selecciona cuando no había nada
        seleccionado, que no es el caso si ya se estaba trabajando con otra imagen."""
        if path in self.files_list:
            self.tree.setCurrentIndex(self._model.index(self.files_list.index(path), 0))

    def _warn_clipboard_unusable(self):
        QMessageBox.information(
            self, self.tr("Nada que pegar"),
            self.tr("No hay ninguna imagen en el portapapeles.\n\n"
                    "Copia una imagen (por ejemplo con una captura de pantalla, o con "
                    "\"Copiar imagen\" en el navegador) o copia archivos de imagen desde "
                    "el explorador de archivos, y vuelve a intentarlo."),
        )

    def _start_scan(self, paths: list[str]):
        """Enumera archivos/carpetas en un hilo de fondo (ver _PathScanThread) --
        ni siquiera el os.walk() de una carpeta enorme debe bloquear la UI."""
        self._scan_thread = _PathScanThread(paths, self)
        self._scan_thread.finished_scan.connect(self._on_scan_finished)
        self._scan_thread.start()

    def _on_scan_finished(self, valid_paths: list[str]):
        if valid_paths:
            self.add_files(valid_paths)

    def add_files(self, paths):
        # Normalizar antes de de-duplicar: la misma imagen llega escrita distinto
        # según por dónde entre -- QUrl.toLocalFile() (arrastrar y soltar, y pegar
        # archivos copiados en el explorador) devuelve "C:/x/y", mientras que el
        # diálogo de archivos y las rutas pegadas como texto traen "C:\x\y".
        # Comparando cadenas sin normalizar, el mismo archivo entra dos veces.
        paths = [os.path.normpath(p) for p in paths]
        new_paths = [p for p in paths if p not in self._path_set]
        if not new_paths:
            return
        self.files_list.extend(new_paths)
        self._path_set.update(new_paths)
        # Un solo reset para todo el lote -- nada de construir un item por
        # archivo (ver _QueueTableModel, esto es lo que evita el colgado con
        # miles de archivos).
        self._model.set_rows(self.files_list)
        self._update_counter()
        if self.files_list and not self.tree.selectionModel().hasSelection():
            self.tree.setCurrentIndex(self._model.index(0, 0))

    def clear_queue(self):
        self.files_list.clear()
        self._path_set.clear()
        self._model.set_rows([])
        self._output_paths.clear()
        self._titles.clear()
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
            self._output_paths.pop(path, None)
            self._titles.pop(path, None)
        self._model.set_rows(self.files_list)
        self._update_counter()

    def get_all_filepaths(self):
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
            if path and os.path.exists(path):
                from PySide6.QtGui import QDesktopServices
                QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))

    def update_file_status(self, filepath: str, status_text: str):
        self._model.update_status(filepath, status_text)

    def set_output_path(self, filepath: str, output_path: str):
        """Registra el archivo de salida de una conversión completada -- ver
        ImageToolsTab._on_convert_file_completed. Sobrescribe cualquier ruta previa
        (una reconversión reemplaza al resultado anterior)."""
        self._output_paths[filepath] = output_path

    def get_output_path(self, filepath: str) -> str | None:
        """Devuelve la ruta del resultado convertido de `filepath`, o None si
        nunca se convirtió O si el archivo ya no existe en disco (se borró/movió
        después de convertir, ej. desde el explorador) -- en ese caso también se
        auto-corrige: se limpia el registro interno y la fila vuelve a mostrar
        "Resultado eliminado" en vez de seguir diciendo "Completado" para un
        archivo que ya no está. Único punto de verdad -- todo lo que decide si
        mostrar Comparar/Copiar pasa por aquí (ver ImageToolsTab)."""
        output_path = self._output_paths.get(filepath)
        if output_path and not os.path.exists(output_path):
            self._output_paths.pop(filepath, None)
            self.update_file_status(filepath, self.tr("Resultado eliminado"))
            return None
        return output_path

    def set_title(self, filepath: str, title: str):
        title = (title or "").strip()
        if title:
            self._titles[filepath] = title
        else:
            self._titles.pop(filepath, None)

    def get_title(self, filepath: str) -> str:
        """Título editado por el usuario, o el nombre base del archivo (sin
        extensión) si nunca se tocó -- default razonable para el campo "Título"."""
        return self._titles.get(filepath) or os.path.splitext(os.path.basename(filepath))[0]
