# src/gui/tabs/image_tools/image_tools_view.py
import os
import platform
import shutil
import tempfile

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QScrollArea, QApplication,
    QPushButton, QButtonGroup, QLineEdit, QFileDialog, QMessageBox, QProgressDialog,
    QGraphicsRectItem, QGraphicsEllipseItem, QGraphicsLineItem, QCheckBox, QToolTip,
)
from PySide6.QtCore import (
    Qt, QSize, QEvent, QUrl, QStandardPaths, QThread, Signal, QTimer, QMimeData, QRectF, QLineF, QPointF,
)
from PySide6.QtGui import (
    QDesktopServices, QPixmap, QColor, QPen, QBrush, QCursor,
    QUndoGroup, QUndoStack,
)

from core.logger.logger_manager import logger
from core.setup.ghostscript_setup import check_ghostscript, download_ghostscript
from core.setup.vtracer_setup import check_vtracer, download_vtracer
from core.utils.sound_notifier import get_sound_notifier, SOURCE_IMAGE_TOOLS
from core.utils.config_manager import get_config, save_config
from gui.styles import (
    get_theme_token, apply_folder_browse_button_style, apply_folder_open_button_style,
    create_colored_circle_icon, update_label_combobox_style,
)
from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon
from gui.widgets.animated_button import AnimatedButton
from gui.widgets.bouncing_progress_bar import BouncingProgressBar
from gui.widgets.combo_box import AutoPopupComboBox
from gui.widgets.collapsible_panel import CollapsiblePanel
from gui.widgets.resettable_splitter import ResettableSplitter
from gui.widgets.floating_panel import FloatingPanel
from gui.widgets.popover_button import PopoverTriggerButton
from gui.tabs.editing_media.preview_panel import PreviewContainerWidget
from gui.tabs.image_tools.image_queue_widget import ImageQueueWidget
from gui.tabs.image_tools.upscale_popover import UpscalePopoverContent
from gui.tabs.image_tools.rembg_popover import RembgPopoverContent
from gui.tabs.image_tools.depth_popover import DepthPopoverContent
from gui.tabs.image_tools.normal_popover import NormalPopoverContent
from gui.tabs.image_tools.canvas_popover import CanvasPopoverContent
from gui.tabs.image_tools.resize_popover import ResizePopoverContent
from gui.tabs.image_tools.tool_rail import ToolRail
from gui.tabs.image_tools.tool_options_popover import (
    DEFAULT_TOOL_STYLES, TOOL_OPTION_MODE, ToolOptionsButton, ToolOptionsPopoverContent,
)
from gui.tabs.image_tools.convert_panel import ConvertPanel
from gui.tabs.image_tools.image_convert_worker import ImageConvertWorker
from gui.tabs.image_tools.canvas_flatten import build_flattened_image, rasterize_item, _clone_item
from core.utils import shortcuts
from gui.tabs.image_tools.layers.layer_model import Layer, LayerStack
from gui.tabs.image_tools.layers.history import (
    MacroCommand, AddLayerCommand, RemoveLayerCommand, MoveLayerCommand, VisibilityCommand, OpacityCommand,
    RasterizeCommand, PixelPatchCommand, GeometryCommand, StyleCommand, CanvasCommand, NudgeCommand,
    RasterGrowCommand, TextContentCommand, TextStyleCommand, TextResizeCommand,
)
from gui.tabs.image_tools.layers.text_item import EditableTextItem
from gui.widgets.zoomable_image_viewer import ZoomableImageViewer
from gui.tabs.image_tools.layers.layers_panel import LayersPanel
from gui.tabs.image_tools.layers.background_dialog import BackgroundDialog

_COMPARE_CACHE_SIZE = 5


class _CompareCache:
    """Cache RAM chico para la vista antes/después (ver PreviewContainerWidget.
    show_compare_preview) -- evita recargar de disco/re-renderizar un vector o RAW
    en cada selección de la misma fila. A diferencia del cache de DowP1 (que solo
    guardaba el "antes"), aquí se guardan ambos lados -- el "después" también se
    recargaba de disco en cada click en DowP1, un desperdicio real ya que el
    proceso mismo lo acaba de escribir. FIFO simple, tope 5 (mismo tamaño que
    DowP1), suficiente para un flujo de "comparar unas pocas filas por sesión"."""

    def __init__(self, max_size: int = _COMPARE_CACHE_SIZE):
        self._max_size = max_size
        self._entries: dict[str, tuple[QPixmap, QPixmap]] = {}
        self._order: list[str] = []

    def get(self, filepath: str) -> tuple[QPixmap | None, QPixmap | None]:
        entry = self._entries.get(filepath)
        return entry if entry else (None, None)

    def put(self, filepath: str, before: QPixmap, after: QPixmap):
        if before is None or after is None or before.isNull() or after.isNull():
            return
        if filepath not in self._entries and len(self._entries) >= self._max_size:
            oldest = self._order.pop(0)
            self._entries.pop(oldest, None)
        if filepath in self._order:
            self._order.remove(filepath)
        self._order.append(filepath)
        self._entries[filepath] = (before, after)

    def invalidate(self, filepath: str):
        """Descarta el par antes/después cacheado de `filepath` -- se llama al
        registrar un output_path NUEVO para un archivo (reconversión), para que
        Comparar no muestre el resultado anterior ya pisado en disco."""
        self._entries.pop(filepath, None)
        if filepath in self._order:
            self._order.remove(filepath)


class ImageToolsTab(QWidget):
    """Editor de Imagen.

    Layout: barra de herramientas vertical a la izquierda (ancho fijo 40px),
    vista previa al centro, panel derecho colapsable (cola de imágenes + opciones
    de formato encapsuladas), y panel inferior unificado de salida y conversión
    (política de conflicto, ruta de destino, progreso y botón Convertir)."""

    TOOLBAR_WIDTH = 40
    RIGHT_DOCKED_WIDTH = 380
    RIGHT_OVERLAY_MAX_WIDTH = 420
    # Ancho "cómodo" mínimo del preview antes de forzar el colapso a overlay -- no su
    # mínimo técnico absoluto, mismo criterio que PREVIEW_MIN_WIDTH en VideoToolsTab.
    PREVIEW_MIN_WIDTH = 480
    COLLAPSE_THRESHOLD_WIDTH = 760

    def __init__(self):
        super().__init__()
        self._current_filepath = None
        self._compare_cache = _CompareCache()
        # Fase 3 -- persistencia por archivo de formas/pincel (capas no-"image")
        # y de un Canvas editado a mano (arrastre de handles/imagen, a diferencia
        # de un preset del popover -- eso sigue siendo 100% de lote, ver
        # canvas_popover.py). Clave = filepath. Ver _on_file_selected/_on_canvas_edited.
        self._layer_snapshots: dict[str, list] = {}
        self._canvas_overrides: dict[str, dict] = {}
        # Máscara del Borrador sobre la imagen base, por archivo (ver
        # ZoomableImageViewer.base_mask). Se guarda al terminar cada trazo.
        self._base_masks: dict = {}
        # Deshacer/Rehacer: un QUndoStack por archivo (ver layers/history.py). El grupo
        # apunta al del archivo abierto; botones y atajos hablan siempre con el grupo.
        self._undo_group = QUndoGroup(self)
        self._undo_stacks: dict[str, QUndoStack] = {}
        self._pending_raster_layer = None  # (Layer, índice) creada por el trazo en curso
        self._pending_raster_grow = None   # args de RasterGrowCommand del trazo en curso
        self._flatten_temp_dir: str | None = None
        # Filepath -> si el resultado ya convertido de ese archivo usó IA
        # (reescalado por ahora, ver _on_convert_file_completed -- a futuro también
        # Eliminar Fondo cuando tenga ejecución conectada) -- determina si Comparar
        # arranca activado por defecto al mirar ese archivo (ver _on_file_selected).
        self._files_with_ai_edit: dict[str, bool] = {}
        # Filepath -> (ancho, alto) al que se calculó su Mapa de Profundidad,
        # solo si el lote fue ÚNICAMENTE de profundidad -- de ahí sale la nota
        # amarilla "920×518 calculado" sobre el resultado (ver
        # _show_compare_view). _pending_depth_sizes guarda lo que manda el
        # worker hasta que el archivo termina y se sabe qué lote era.
        # Cada valor es (ancho, alto, tipo), con tipo "depth" o "normals": la nota es la
        # misma para los dos mapas, pero su tooltip dice qué se calculó.
        self._depth_process_sizes: dict[str, tuple[int, int, str]] = {}
        self._pending_depth_sizes: dict[str, tuple[int, int, str]] = {}
        self._active_convert_settings: dict | None = None
        self._build_ui()
        # Acepta arrastrar archivos desde fuera de la app (o desde otra pestaña de
        # DowP) en TODA la pestaña -- vista previa, toolbar, etc. -- no solo sobre
        # la cola. Qt solo entrega eventos de drag al widget exacto bajo el cursor
        # que acepte drops, no los sube solo a los ancestros con setAcceptDrops(True)
        # -- por eso no basta con activarlo aquí y ya (ver WholeAreaDropForwarder).
        # Se excluye self.image_queue porque ya maneja sus propios drops
        # correctamente (incluye carpetas vía _start_scan) sin necesitar esto.
        from gui.widgets.drop_forwarder import WholeAreaDropForwarder
        self._drop_forwarder = WholeAreaDropForwarder(
            self, lambda paths: self.image_queue._start_scan(paths), exclude=[self.image_queue]
        )

    def _build_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(10, 10, 10, 10)
        outer_layout.setSpacing(8)

        # ── Fila superior: Toolbar vertical izquierda + Fila de cuerpo
        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(8)

        # ── Barra de herramientas vertical: botones cuadrados estándar 32x32
        # (mismo tamaño y proporciones que en el resto de la app), cada uno
        # despliega su propio panel flotante o activa su herramienta de dibujo.
        # Con poco alto la barra se compacta y, si aun así no entra, pasa a dos columnas
        # (ver ToolRail) en vez de montar los botones unos sobre otros.
        self.side_toolbar = ToolRail()
        self.side_toolbar.setObjectName("imageToolsSideToolbar")
        self.side_toolbar.layout_changed.connect(self._on_side_toolbar_layout_changed)
        top_layout = self.side_toolbar

        def _make_sep():
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setFixedHeight(1)
            sep.setStyleSheet(f"background-color: {get_theme_token('borde_sutil', '#2d2d2d')}; border: none;")
            return sep

        self._popover_buttons = []

        self.selected_upscale_engine = None
        self.selected_upscale_model = None
        self.upscale_popover_content = UpscalePopoverContent()
        self.upscale_popover_content.selection_changed.connect(self._on_upscale_selection_changed)

        # ── Grupo 1: Herramientas IA ──────────────────────────────────────────
        self.btn_upscale = PopoverTriggerButton(
            host=self, content=self.upscale_popover_content,
            on_right_click=lambda: self._deactivate_on_right_click(
                self.btn_upscale, self.upscale_popover_content),
        )
        self.btn_upscale.setFixedSize(32, 32)
        self.btn_upscale.setIconSize(QSize(18, 18))
        self.btn_upscale.setCursor(Qt.PointingHandCursor)
        self._style_upscale_button(is_valid=False)
        # El popover no puede cerrarse solo: quien manda su visibilidad es el botón.
        self.upscale_popover_content.close_popover_requested.connect(
            lambda: self.btn_upscale.set_open(False))
        top_layout.addWidget(self.btn_upscale)
        self._popover_buttons.append(self.btn_upscale)

        self.selected_rembg_family = None
        self.selected_rembg_model = None
        self.rembg_popover_content = RembgPopoverContent()
        self.rembg_popover_content.selection_changed.connect(self._on_rembg_selection_changed)

        self.btn_rembg = PopoverTriggerButton(
            host=self, content=self.rembg_popover_content,
            on_right_click=lambda: self._deactivate_on_right_click(
                self.btn_rembg, self.rembg_popover_content),
        )
        self.btn_rembg.setFixedSize(32, 32)
        self.btn_rembg.setIconSize(QSize(18, 18))
        self.btn_rembg.setCursor(Qt.PointingHandCursor)
        self._style_rembg_button(is_valid=False)
        self.rembg_popover_content.close_popover_requested.connect(
            lambda: self.btn_rembg.set_open(False))
        top_layout.addWidget(self.btn_rembg)
        self._popover_buttons.append(self.btn_rembg)

        self.depth_popover_content = DepthPopoverContent()
        self.depth_popover_content.selection_changed.connect(self._on_depth_selection_changed)

        self.btn_depth = PopoverTriggerButton(
            host=self, content=self.depth_popover_content,
            on_right_click=lambda: self._deactivate_on_right_click(
                self.btn_depth, self.depth_popover_content),
        )
        self.btn_depth.setFixedSize(32, 32)
        self.btn_depth.setIconSize(QSize(18, 18))
        self.btn_depth.setCursor(Qt.PointingHandCursor)
        self._style_depth_button(is_valid=False)
        self.depth_popover_content.close_popover_requested.connect(
            lambda: self.btn_depth.set_open(False))
        top_layout.addWidget(self.btn_depth)
        self._popover_buttons.append(self.btn_depth)

        self.normal_popover_content = NormalPopoverContent()
        self.normal_popover_content.selection_changed.connect(self._on_normal_selection_changed)

        self.btn_normals = PopoverTriggerButton(
            host=self, content=self.normal_popover_content,
            on_right_click=lambda: self._deactivate_on_right_click(
                self.btn_normals, self.normal_popover_content),
        )
        self.btn_normals.setFixedSize(32, 32)
        self.btn_normals.setIconSize(QSize(18, 18))
        self.btn_normals.setCursor(Qt.PointingHandCursor)
        self._style_normals_button(is_valid=False)
        self.normal_popover_content.close_popover_requested.connect(
            lambda: self.btn_normals.set_open(False))
        top_layout.addWidget(self.btn_normals)
        self._popover_buttons.append(self.btn_normals)

        top_layout.addSeparator(_make_sep())

        # ── Grupo 2: Dimensiones y Lienzo ─────────────────────────────────────
        self.resize_popover_content = ResizePopoverContent()
        self.resize_popover_content.selection_changed.connect(self._on_resize_selection_changed)

        self.btn_resize = PopoverTriggerButton(
            host=self, content=self.resize_popover_content,
            on_right_click=lambda: self._deactivate_on_right_click(
                self.btn_resize, self.resize_popover_content),
        )
        self.btn_resize.setFixedSize(32, 32)
        self.btn_resize.setIconSize(QSize(18, 18))
        self.btn_resize.setCursor(Qt.PointingHandCursor)
        self._style_resize_button(is_active=False)
        top_layout.addWidget(self.btn_resize)
        self._popover_buttons.append(self.btn_resize)

        self.selected_canvas_option = None
        self.canvas_popover_content = CanvasPopoverContent()
        self.canvas_popover_content.selection_changed.connect(self._on_canvas_selection_changed)

        # Grupo exclusivo de herramientas (canvas + selección/dibujo)
        self._tool_group = QButtonGroup(self)
        self._tool_group.setExclusive(True)
        self._tool_buttons = {}
        self._canvas_right_activated = False
        self._TOOL_ICONS = {
            "select": "arrow_selector_tool.svg",
            "rect": "rectangle.svg",
            "ellipse": "circle.svg",
            "line": "horizontal_rule.svg",
            "brush": "edit.svg",
            "eraser": "ink_eraser.svg",
            "text": "title4.svg",
            "canvas": "crop_free.svg",
        }

        # Canvas — clic izquierdo selecciona la herramienta; clic derecho abre el popover de opciones
        self.btn_canvas = ToolOptionsButton(host=self, content=self.canvas_popover_content)
        self.btn_canvas.setCheckable(True)
        self.btn_canvas.setFixedSize(32, 32)
        self.btn_canvas.setIconSize(QSize(18, 18))
        self.btn_canvas.setCursor(Qt.PointingHandCursor)
        self.btn_canvas.setToolTip(self.tr("Canvas — clic derecho: opciones"))
        self.btn_canvas.toggled.connect(lambda checked: self._on_tool_toggled("canvas", checked))
        self.btn_canvas.opened.connect(self._on_canvas_popover_opened)
        self.btn_canvas.clicked.connect(self._on_canvas_clicked)
        self._tool_group.addButton(self.btn_canvas)
        self._tool_buttons["canvas"] = self.btn_canvas
        self._popover_buttons.append(self.btn_canvas)
        top_layout.addWidget(self.btn_canvas)

        top_layout.addSeparator(_make_sep())

        # ── Grupo 3: Capas y Composición ──────────────────────────────────────
        self.layer_stack = LayerStack()
        self.layer_stack.layers_changed.connect(self._refresh_layers_panel)

        self.layers_panel = LayersPanel()
        self.layers_panel.layer_visibility_toggled.connect(self._on_layer_visibility_toggled)
        self.layers_panel.layer_opacity_changed.connect(self._on_layer_opacity_changed)
        self.layers_panel.layer_move_up_requested.connect(self._on_layer_move_up)
        self.layers_panel.layer_move_down_requested.connect(self._on_layer_move_down)
        self.layers_panel.layer_delete_requested.connect(self._on_layer_delete)
        self.layers_panel.layer_selected.connect(self._on_layer_row_selected)
        self.layers_panel.layer_rasterize_requested.connect(self._on_layer_rasterize_requested)
        self.layers_panel.add_background_requested.connect(self._on_add_background_requested)

        # Botón para mostrar/ocultar el panel flotante de Capas
        self.btn_layers_panel = QPushButton()
        self.btn_layers_panel.setCheckable(True)
        self.btn_layers_panel.setFixedSize(32, 32)
        self.btn_layers_panel.setIconSize(QSize(18, 18))
        self.btn_layers_panel.setCursor(Qt.PointingHandCursor)
        self.btn_layers_panel.setToolTip(self.tr("Mostrar/ocultar panel de Capas"))
        self.btn_layers_panel.toggled.connect(self._on_layers_panel_toggled)
        self._style_layers_panel_button(False)
        top_layout.addWidget(self.btn_layers_panel)

        # Herramientas de capas y dibujo (Seleccionar/Rectángulo/Elipse/Línea/Pincel).
        # Las de dibujo abren sus opciones con clic derecho (ver tool_options_popover.py),
        # sin cambiar de herramienta: así se puede retocar la forma seleccionada.
        self._tool_styles = self._load_tool_styles()
        self._tool_option_popovers = {}
        self._save_tool_styles_timer = QTimer(self)
        self._save_tool_styles_timer.setSingleShot(True)
        self._save_tool_styles_timer.setInterval(400)
        self._save_tool_styles_timer.timeout.connect(self._save_tool_styles)
        for key, tooltip in (
            ("select", self.tr("Seleccionar")),
            ("rect", self.tr("Rectángulo — clic derecho: opciones")),
            ("ellipse", self.tr("Elipse — clic derecho: opciones")),
            ("line", self.tr("Línea — clic derecho: opciones")),
            ("brush", self.tr("Pincel — clic derecho: opciones")),
            ("eraser", self.tr("Borrador — clic derecho: opciones")),
            ("text", self.tr("Texto — clic derecho: opciones")),
        ):
            mode = TOOL_OPTION_MODE.get(key)
            if mode is None:
                btn = QPushButton()
            else:
                content = ToolOptionsPopoverContent(mode)
                content.load(self._tool_styles[mode])
                content.option_changed.connect(self._on_tool_option_changed)
                btn = ToolOptionsButton(host=self, content=content)
                btn.opened.connect(lambda c=content, m=mode: c.load(self._option_values_for(m)))
                self._tool_option_popovers[key] = btn
                self._popover_buttons.append(btn)
            btn.setCheckable(True)
            btn.setFixedSize(32, 32)
            btn.setIconSize(QSize(18, 18))
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(tooltip)
            btn.toggled.connect(lambda checked, k=key: self._on_tool_toggled(k, checked))
            self._tool_group.addButton(btn)
            self._tool_buttons[key] = btn
            top_layout.addWidget(btn)

        self._style_tool_buttons()
        self._tool_buttons["select"].setChecked(True)

        for btn in self._popover_buttons:
            btn.opened.connect(lambda b=btn: self._close_other_popovers(b))
        # Abrir Reescalar/Eliminar Fondo/Redimensionar te saca de la herramienta que tuvieras activa
        # (incluido Canvas) y te deja en Seleccionar.
        self.btn_upscale.opened.connect(self._reset_to_select_tool)
        self.btn_rembg.opened.connect(self._reset_to_select_tool)
        self.btn_depth.opened.connect(self._reset_to_select_tool)
        self.btn_normals.opened.connect(self._reset_to_select_tool)
        self.btn_resize.opened.connect(self._reset_to_select_tool)

        content_row.addWidget(self.side_toolbar)

        # ── Fila de cuerpo: preview + panel derecho colapsable ─────────────────────
        self.body_row = QWidget()
        body_layout = QHBoxLayout(self.body_row)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)

        # Columna del preview: fila de Título/Copiar arriba + preview abajo -- se
        # envuelve en su propio widget para que esa fila quede acotada al ancho del
        # preview (no de todo body_row, que también incluye el panel derecho).
        preview_column = QWidget()
        preview_column_layout = QVBoxLayout(preview_column)
        preview_column_layout.setContentsMargins(0, 0, 0, 0)
        preview_column_layout.setSpacing(6)

        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        lbl_title = QLabel(self.tr("Título:"))
        lbl_title.setObjectName("menuLabel")
        title_row.addWidget(lbl_title)
        self.entry_title = QLineEdit()
        self.entry_title.setPlaceholderText(self.tr("Nombre del archivo de salida"))
        self.entry_title.setEnabled(False)
        self.entry_title.editingFinished.connect(self._on_title_edited)
        title_row.addWidget(self.entry_title, 1)
        # Toggle -- por defecto SIEMPRE se ve el editor (formas/pincel/Canvas
        # siguen visibles y editables incluso después de convertir, ver
        # _on_file_selected/_show_editable_view); la comparación antes/después
        # queda como vista explícita bajo demanda, no como estado permanente.
        self.btn_undo = self._make_history_button("undo.svg")
        self.btn_undo.clicked.connect(self._undo_group.undo)
        title_row.addWidget(self.btn_undo)
        self.btn_redo = self._make_history_button("redo.svg")
        self.btn_redo.clicked.connect(self._undo_group.redo)
        title_row.addWidget(self.btn_redo)
        self._undo_group.canUndoChanged.connect(self.btn_undo.setEnabled)
        self._undo_group.canRedoChanged.connect(self.btn_redo.setEnabled)
        self._undo_group.undoTextChanged.connect(self._refresh_history_tooltips)
        self._undo_group.redoTextChanged.connect(self._refresh_history_tooltips)
        self._refresh_history_tooltips()
        self.btn_compare_result = QPushButton(self.tr("Comparar"))
        # accent-orange (degradado naranja, mismo que "Fragmentos"/"Buscar
        # actualizaciones") y accent-blue para Copiar (el degradado azul del botón
        # SOLO de Proceso Avanzado). Los dos ya traen su propio :disabled plano en
        # _base.qss, que es justo el estado que hace falta aqui: ninguno de los dos
        # tiene sentido hasta que la fila tenga un resultado convertido, y de eso se
        # encarga _refresh_title_and_copy_button().
        self.btn_compare_result.setProperty("variant", "accent-orange")
        self.btn_compare_result.setCursor(Qt.PointingHandCursor)
        self.btn_compare_result.setToolTip(self.tr("Ver comparación antes/después del resultado"))
        self.btn_compare_result.setCheckable(True)
        self.btn_compare_result.setEnabled(False)
        self.btn_compare_result.toggled.connect(self._on_compare_toggled)
        title_row.addWidget(self.btn_compare_result)
        self.btn_copy_result = QPushButton(self.tr("Copiar"))
        self.btn_copy_result.setProperty("variant", "accent-blue")
        self.btn_copy_result.setCursor(Qt.PointingHandCursor)
        self.btn_copy_result.setToolTip(self.tr("Copiar la imagen resultante al portapapeles"))
        self.btn_copy_result.setEnabled(False)
        self.btn_copy_result.clicked.connect(self._on_copy_result_clicked)
        title_row.addWidget(self.btn_copy_result)
        preview_column_layout.addLayout(title_row)

        self.preview = PreviewContainerWidget()
        self.preview.set_fill_available_space(True)
        self.preview.set_zoomable(True)
        preview_column_layout.addWidget(self.preview, 1)

        # Separador ajustable Vista previa | Panel derecho (lista de imágenes + formato):
        # el ancho del panel lo decide el usuario y se recuerda (ver _apply_layout_sizes).
        self.body_splitter = ResettableSplitter(Qt.Horizontal)
        self.body_splitter.addWidget(preview_column)
        body_layout.addWidget(self.body_splitter, 1)

        self.queue_content = self._build_queue_content()
        self.right_panel = CollapsiblePanel(
            self.queue_content, edge="right",
            docked_size=self.RIGHT_DOCKED_WIDTH,
            overlay_max_width=self.RIGHT_OVERLAY_MAX_WIDTH,
        )
        self.body_splitter.addWidget(self.right_panel)
        self.body_splitter.setStretchFactor(0, 1)
        self.body_splitter.setStretchFactor(1, 0)
        # Sin techo: docked_size sigue siendo el mínimo (que la lista no se recorte),
        # pero el usuario puede ensancharlo cuanto quiera.
        self.right_panel.set_dock_max_width(16777215)
        self._layout_save_timer = QTimer(self)
        self._layout_save_timer.setSingleShot(True)
        self._layout_save_timer.setInterval(400)
        self._layout_save_timer.timeout.connect(self._save_layout_sizes)
        self.body_splitter.splitterMoved.connect(lambda *_: self._layout_save_timer.start())
        self.body_splitter.reset_requested.connect(self._reset_layout)

        # Panel "Capas": ventana flotante arrastrable (estilo panel de Photoshop), no
        # acoplada a ningún layout -- flota libremente sobre self.body_row, la mueve
        # el usuario agarrando su barra de título (ver gui/widgets/floating_panel.py).
        # preferred_side="left": al abrirse por primera vez aparece cerca de la barra
        # de herramientas/sobre el preview, no encima del panel derecho de cola+Convertir.
        self.layers_floating_panel = FloatingPanel(
            self.tr("Capas"), self.layers_panel, host=self.body_row, width=300, preferred_side="left",
        )
        self.layers_floating_panel.closed.connect(lambda: self.btn_layers_panel.setChecked(False))

        # Suprimir / Retroceso borran la capa seleccionada. Solo con el foco en el visor o
        # en el panel de Capas: la cola de archivos usa esas mismas teclas para quitar
        # archivos (ver ImageQueueWidget.eventFilter), y un atajo a nivel de pestaña se
        # dispararía antes que ella. Los campos de texto del panel (opacidad...) se quedan
        # con esas teclas vía ShortcutOverride, así que borrar dígitos no borra una capa.
        # Todos los atajos salen del registro central (core/utils/shortcuts.py), así el
        # usuario puede cambiarlos en Ajustes > Atajos de teclado y se aplican al momento.
        self._shortcut_binder = shortcuts.ShortcutBinder(self)
        self._bind_editor_shortcuts()
        shortcuts.registry.changed.connect(lambda _id: self._refresh_shortcut_tooltips())
        self._refresh_shortcut_tooltips()
        # Oculto por defecto -- self.btn_layers_panel ya nace desmarcado (ver arriba),
        # así que no hace falta forzar nada aquí; alcanza con no mostrarlo.

        # Puente popover <-> visor para la edición visual de Canvas (ver
        # canvas_popover.py y ZoomableImageViewer.apply_canvas_state/margin_dragged/
        # size_dragged): el popover empuja el estado calculado, el visor devuelve los
        # valores en vivo mientras se arrastra un handle.
        viewer = self.preview.zoom_viewer
        self.canvas_popover_content.state_changed.connect(self._on_canvas_state_changed)
        viewer.margin_dragged.connect(self.canvas_popover_content.on_margin_dragged)
        viewer.size_dragged.connect(self.canvas_popover_content.on_size_dragged)
        # "El usuario tocó el canvas a mano" -- Fase 3, guardarlo como override
        # propio de ESTE archivo (no toca el preset de lote, ver canvas_popover.py).
        viewer.canvas_edited.connect(self._on_canvas_edited)

        # Puente panel de Capas <-> visor: figuras/trazos creados en el visor se
        # registran como capas; seleccionar en el visor resalta la fila correspondiente.
        viewer.shape_created.connect(self._on_shape_created)
        viewer.raster_layer_created.connect(self._on_raster_layer_created)
        viewer.shape_selected.connect(self._on_shape_selected)
        viewer.set_eraser_target_provider(self._eraser_target)
        viewer.set_marked_item_provider(self._marked_layer_item)
        viewer.set_brush_target_provider(self._brush_target)
        viewer.raster_layer_grown.connect(self._on_raster_layer_grown)
        viewer.text_item_created.connect(self._on_text_item_created)
        viewer.text_edit_finished.connect(self._on_text_edit_finished)
        viewer.text_editing_changed.connect(self._on_text_editing_changed)
        viewer.text_resized.connect(
            lambda item, before, after: self._push_history(
                TextResizeCommand(self, self.tr("Redimensionar"), item, before, after)))
        self.layers_panel.marked_changed.connect(viewer.viewport().update)
        viewer.base_mask_changed.connect(self._on_base_mask_changed)
        viewer.pixels_changed.connect(self._on_pixels_changed)
        viewer.item_geometry_changed.connect(self._on_item_geometry_changed)

        # El host del overlay es la pestaña completa (self), no self.body_row: Qt recorta
        # los hijos al área de su padre, así que si quedara colgado de body_row jamás podría
        # pintarse por encima de output_bar. Al no empujar ni redimensionar nada (es un
        # overlay flotante), cubre toda la altura disponible y el botón de borde queda
        # pegado al límite de la ventana (mismo comportamiento que en VideoToolsTab).
        self.right_panel.configure_container(self, self.body_splitter, 1)
        QTimer.singleShot(0, self._apply_layout_sizes)

        self.image_queue.file_selected.connect(self._on_file_selected)

        content_row.addWidget(self.body_row, 1)
        outer_layout.addLayout(content_row, 1)

        # ── Fila inferior: Barra unificada de salida y conversión
        self.output_bar = self._build_output_bar()
        outer_layout.addWidget(self.output_bar)

        self._update_convert_button_state()

        QApplication.instance().installEventFilter(self)

    def _close_other_popovers(self, opened_btn):
        """Solo un popover de la franja superior abierto a la vez -- si se abre uno,
        se cierran los demás en vez de quedar superpuestos."""
        for btn in self._popover_buttons:
            if btn is not opened_btn and btn.is_open():
                btn.set_open(False)

    def _deactivate_on_right_click(self, btn, popover_content) -> bool:
        """Handler de on_right_click para Reescalar/Eliminar Fondo/Redimensionar.
        En estos tres botones el reparto es estricto: el clic izquierdo abre el
        popover para configurar, y el derecho sirve únicamente para apagar la
        herramienta -- con una configuración activa la desactiva en el acto (vuelve
        el popover a su placeholder) y lo cierra si estaba abierto; sin nada activo
        no hace nada. Siempre devuelve True para consumir el clic, así el derecho
        nunca termina abriendo el popover. Canvas queda intacto: no pasa handler,
        y su clic derecho sigue abriendo sus opciones."""
        if popover_content.is_active():
            popover_content.deactivate()
            btn.set_open(False)
        return True

    def _on_upscale_selection_changed(self, engine_key: str, model_key: str, is_valid: bool):
        self.selected_upscale_engine = engine_key or None
        self.selected_upscale_model = model_key or None
        self._style_upscale_button(is_valid)

    def _on_rembg_selection_changed(self, family_key: str, model_key: str, is_valid: bool):
        self.selected_rembg_family = family_key or None
        self.selected_rembg_model = model_key or None
        self._style_rembg_button(is_valid)

    def _on_depth_selection_changed(self, _family_key: str, _model_key: str, is_valid: bool):
        self._style_depth_button(is_valid)
        # Profundidad y Normales son excluyentes (las dos producen una imagen nueva que
        # reemplaza a la foto): encender una apaga la otra. deactivate() vuelve a emitir
        # selection_changed con is_valid=False, que no apaga nada más -- no hay bucle.
        if is_valid and self.normal_popover_content.is_active():
            self.normal_popover_content.deactivate()

    def _on_normal_selection_changed(self, _family_key: str, _model_key: str, is_valid: bool):
        self._style_normals_button(is_valid)
        if is_valid and self.depth_popover_content.is_active():
            self.depth_popover_content.deactivate()

    def _on_resize_selection_changed(self, is_active: bool):
        self._style_resize_button(is_active)

    def _style_resize_button(self, is_active: bool):
        """Mismo criterio visual que _style_upscale_button/_style_rembg_button --
        verde cuando el preset elegido en el popover no es "No escalar (Original)"
        (el default), gris si lo es."""
        if is_active:
            self.btn_resize.setIcon(get_colored_svg_icon("resize.svg", "#000000", size=18))
            self.btn_resize.setToolTip(self.tr("Redimensionar — activo (clic derecho: desactivar)"))
            self.btn_resize.setStyleSheet(f"""
                QPushButton {{
                    min-width: 32px; max-width: 32px;
                    min-height: 32px; max-height: 32px;
                    background-color: {get_theme_token('acento_secundario', '#1DC038')};
                    border: none;
                    border-radius: 6px;
                    padding: 0px;
                }}
                QPushButton:hover {{
                    background-color: {get_theme_token('acento_primario', '#B9E640')};
                }}
            """)
        else:
            self.btn_resize.setIcon(get_colored_svg_icon("resize.svg", "#6c7086", size=18))
            self.btn_resize.setToolTip(self.tr("Redimensionar"))
            self.btn_resize.setStyleSheet(f"""
                QPushButton {{
                    min-width: 30px; max-width: 30px;
                    min-height: 30px; max-height: 30px;
                    background-color: {get_theme_token('fondo_elemento', '#2d2d2d')};
                    border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                    border-radius: 6px;
                    padding: 0px;
                }}
                QPushButton:hover {{
                    background-color: {get_theme_token('seleccion_fondo', '#3d3d3d')};
                }}
            """)

    def _style_rembg_button(self, is_valid: bool):
        """Mismo criterio visual que _style_upscale_button -- ver ese método."""
        if is_valid:
            self.btn_rembg.setIcon(get_colored_svg_icon("background_replace.svg", "#000000", size=18))
            self.btn_rembg.setToolTip(self.tr("Eliminar Fondo (IA) — configuración lista (clic derecho: desactivar)"))
            self.btn_rembg.setStyleSheet(f"""
                QPushButton {{
                    min-width: 32px; max-width: 32px;
                    min-height: 32px; max-height: 32px;
                    background-color: {get_theme_token('acento_secundario', '#1DC038')};
                    border: none;
                    border-radius: 6px;
                    padding: 0px;
                }}
                QPushButton:hover {{
                    background-color: {get_theme_token('acento_primario', '#B9E640')};
                }}
            """)
        else:
            self.btn_rembg.setIcon(get_colored_svg_icon("background_replace.svg", "#6c7086", size=18))
            self.btn_rembg.setToolTip(self.tr("Eliminar Fondo (IA)"))
            self.btn_rembg.setStyleSheet(f"""
                QPushButton {{
                    min-width: 30px; max-width: 30px;
                    min-height: 30px; max-height: 30px;
                    background-color: {get_theme_token('fondo_elemento', '#2d2d2d')};
                    border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                    border-radius: 6px;
                    padding: 0px;
                }}
                QPushButton:hover {{
                    background-color: {get_theme_token('seleccion_fondo', '#3d3d3d')};
                }}
            """)

    def _style_depth_button(self, is_valid: bool):
        """Mismo criterio visual que _style_upscale_button -- ver ese método."""
        if is_valid:
            self.btn_depth.setIcon(get_colored_svg_icon("landscape.svg", "#000000", size=18))
            self.btn_depth.setToolTip(self.tr("Mapa de Profundidad (IA) — configuración lista (clic derecho: desactivar)"))
            self.btn_depth.setStyleSheet(f"""
                QPushButton {{
                    min-width: 32px; max-width: 32px;
                    min-height: 32px; max-height: 32px;
                    background-color: {get_theme_token('acento_secundario', '#1DC038')};
                    border: none;
                    border-radius: 6px;
                    padding: 0px;
                }}
                QPushButton:hover {{
                    background-color: {get_theme_token('acento_primario', '#B9E640')};
                }}
            """)
        else:
            self.btn_depth.setIcon(get_colored_svg_icon("landscape.svg", "#6c7086", size=18))
            self.btn_depth.setToolTip(self.tr("Mapa de Profundidad (IA)"))
            self.btn_depth.setStyleSheet(f"""
                QPushButton {{
                    min-width: 30px; max-width: 30px;
                    min-height: 30px; max-height: 30px;
                    background-color: {get_theme_token('fondo_elemento', '#2d2d2d')};
                    border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                    border-radius: 6px;
                    padding: 0px;
                }}
                QPushButton:hover {{
                    background-color: {get_theme_token('seleccion_fondo', '#3d3d3d')};
                }}
            """)

    def _style_normals_button(self, is_valid: bool):
        """Mismo criterio visual que _style_depth_button -- ver ese método."""
        if is_valid:
            self.btn_normals.setIcon(get_colored_svg_icon("normal_map.svg", "#000000", size=18))
            self.btn_normals.setToolTip(self.tr("Mapa de Normales (IA) — configuración lista (clic derecho: desactivar). Al activarlo se apaga el Mapa de Profundidad."))
            self.btn_normals.setStyleSheet(f"""
                QPushButton {{
                    min-width: 32px; max-width: 32px;
                    min-height: 32px; max-height: 32px;
                    background-color: {get_theme_token('acento_secundario', '#1DC038')};
                    border: none;
                    border-radius: 6px;
                    padding: 0px;
                }}
                QPushButton:hover {{
                    background-color: {get_theme_token('acento_primario', '#B9E640')};
                }}
            """)
        else:
            self.btn_normals.setIcon(get_colored_svg_icon("normal_map.svg", "#6c7086", size=18))
            self.btn_normals.setToolTip(self.tr("Mapa de Normales (IA)"))
            self.btn_normals.setStyleSheet(f"""
                QPushButton {{
                    min-width: 30px; max-width: 30px;
                    min-height: 30px; max-height: 30px;
                    background-color: {get_theme_token('fondo_elemento', '#2d2d2d')};
                    border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                    border-radius: 6px;
                    padding: 0px;
                }}
                QPushButton:hover {{
                    background-color: {get_theme_token('seleccion_fondo', '#3d3d3d')};
                }}
            """)

    def _style_upscale_button(self, is_valid: bool):
        """Mismo criterio visual que apply_edit_subclip_button_style (verde acento +
        ícono oscuro cuando hay una configuración lista para usarse, gris neutro si
        no) -- sin reusar esa función porque está atada a "edit.svg"/textos de
        subclip, no genérica."""
        if is_valid:
            self.btn_upscale.setIcon(get_colored_svg_icon("frame_person.svg", "#000000", size=18))
            self.btn_upscale.setToolTip(self.tr("Reescalar con IA — configuración lista (clic derecho: desactivar)"))
            self.btn_upscale.setStyleSheet(f"""
                QPushButton {{
                    min-width: 32px; max-width: 32px;
                    min-height: 32px; max-height: 32px;
                    background-color: {get_theme_token('acento_secundario', '#1DC038')};
                    border: none;
                    border-radius: 6px;
                    padding: 0px;
                }}
                QPushButton:hover {{
                    background-color: {get_theme_token('acento_primario', '#B9E640')};
                }}
            """)
        else:
            self.btn_upscale.setIcon(get_colored_svg_icon("frame_person.svg", "#6c7086", size=18))
            self.btn_upscale.setToolTip(self.tr("Reescalar con IA"))
            self.btn_upscale.setStyleSheet(f"""
                QPushButton {{
                    min-width: 30px; max-width: 30px;
                    min-height: 30px; max-height: 30px;
                    background-color: {get_theme_token('fondo_elemento', '#2d2d2d')};
                    border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                    border-radius: 6px;
                    padding: 0px;
                }}
                QPushButton:hover {{
                    background-color: {get_theme_token('seleccion_fondo', '#3d3d3d')};
                }}
            """)

    def _on_canvas_selection_changed(self, option: str, is_valid: bool):
        self.selected_canvas_option = option if is_valid else None

    def _on_canvas_state_changed(self, state: dict):
        # El popover (combo/campos) volvió a ser la fuente de verdad para el
        # archivo actual -- si tenía un override manual guardado (arrastre de
        # handle/imagen, Fase 3), se descarta: elegir un preset o tocar un campo
        # es "quiero esto en vez de mi ajuste a mano", no "sumale esto a mi
        # ajuste a mano". Sin este descarte, _build_source_overrides seguía
        # aplicando el override viejo al convertir aunque el editor mostrara en
        # pantalla el preset nuevo (bug reportado: "salió con el ajuste de antes
        # sumando las opciones nuevas").
        if self._current_filepath:
            self._canvas_overrides.pop(self._current_filepath, None)
        viewer = self.preview.zoom_viewer
        viewer.apply_canvas_state(
            state["canvas_rect"], state["mode"], state["resizable"],
            state["image_pos"], state["image_scale"],
        )

    def _snapshot_layers_for(self, filepath: str | None):
        """Guarda las formas/trazos (capas no-"image") que tenga ACTUALMENTE el
        visor bajo la clave `filepath` -- usado tanto al cambiar de selección
        (_on_file_selected) como al exportar sin haber cambiado de fila
        (_on_convert_clicked), mismo criterio en los dos casos."""
        if not filepath:
            return
        non_base = [l for l in self.layer_stack.layers if l.kind != "image"]
        if non_base:
            self._layer_snapshots[filepath] = non_base
        elif filepath in self._layer_snapshots:
            del self._layer_snapshots[filepath]

    def _on_canvas_edited(self):
        """El usuario terminó de arrastrar un handle/la imagen del Canvas -- a
        diferencia de elegir un preset del popover (eso sigue siendo de lote,
        Fase 2), esto queda guardado solo para el archivo actualmente abierto."""
        if not self._current_filepath:
            return
        viewer = self.preview.zoom_viewer
        state = viewer.get_canvas_state()
        if state is not None:
            before_override = self._canvas_overrides.get(self._current_filepath)
            self._canvas_overrides[self._current_filepath] = state
            before_state = viewer.canvas_state_before_edit()
            if before_state is not None:
                self._push_history(CanvasCommand(
                    self, self.tr("Ajustar Canvas"), self._current_filepath,
                    before_state, state, before_override))

    def _on_tool_toggled(self, key: str, checked: bool):
        """Maneja los 6 botones de herramienta (Seleccionar/Rectángulo/Elipse/Línea/
        Pincel/Canvas) -- son mutuamente excluyentes por el QButtonGroup, así que
        elegir cualquiera es solo "cambiar de herramienta", sin ningún concepto de
        "modo" aparte que activar/desactivar."""
        if not checked:
            return
        if key in self._SHAPE_TOOL_CYCLE:
            self._last_shape_tool = key
        if key != "canvas":
            self._canvas_right_activated = False
            if hasattr(self, "btn_canvas") and self.btn_canvas.is_open():
                self.btn_canvas.set_open(False)
        self._style_tool_buttons()
        # Guard: el grupo fija "select" como estado inicial durante _build_ui(),
        # antes de que self.preview/self.layers_panel existan.
        if not hasattr(self, "preview") or not hasattr(self, "layers_panel"):
            return
        viewer = self.preview.zoom_viewer
        if key == "canvas":
            viewer.set_interaction_mode("canvas_edit")
        else:
            viewer.set_interaction_mode("layers_draw")
            viewer.set_active_tool(key)
            self._push_tool_style(key)
            # El Borrador trabaja sobre la capa marcada en Capas: el panel tiene que
            # estar a la vista para poder elegirla.
            if key == "eraser" and not self.btn_layers_panel.isChecked():
                self.btn_layers_panel.setChecked(True)

    def _current_tool_key(self) -> str:
        for key, btn in self._tool_buttons.items():
            if btn.isChecked():
                return key
        return "select"

    def _reset_to_select_tool(self):
        """Conectado a Reescalar/Eliminar Fondo -- abrir esos popovers te devuelve a
        Seleccionar (sea cual sea la herramienta que tuvieras, incluido Canvas), para
        que un clic mientras miras ese popover no dibuje/redimensione nada solo."""
        if not self._tool_buttons["select"].isChecked():
            self._tool_buttons["select"].setChecked(True)

    def _style_tool_buttons(self):
        accent = get_theme_token('acento_primario', '#B9E640')
        bg = get_theme_token('fondo_elemento', '#2d2d2d')
        border = get_theme_token('borde_normal', '#2d2d2d')
        canvas_right = getattr(self, "_canvas_right_activated", False)
        for key, btn in self._tool_buttons.items():
            if key == "canvas":
                icon_name = "crop.svg" if canvas_right else "crop_free.svg"
            else:
                icon_name = self._TOOL_ICONS[key]
            if btn.isChecked():
                btn.setIcon(get_colored_svg_icon(icon_name, "#000000", size=18))
                btn.setStyleSheet(f"""
                    QPushButton {{
                        min-width: 32px; max-width: 32px;
                        min-height: 32px; max-height: 32px;
                        background-color: {accent};
                        border: none;
                        border-radius: 6px;
                        padding: 0px;
                    }}
                """)
            else:
                btn.setIcon(get_colored_svg_icon(icon_name, "#6c7086", size=18))
                btn.setStyleSheet(f"""
                    QPushButton {{
                        min-width: 30px; max-width: 30px;
                        min-height: 30px; max-height: 30px;
                        background-color: {bg};
                        border: 1px solid {border};
                        border-radius: 6px;
                        padding: 0px;
                    }}
                    QPushButton:hover {{ background-color: {get_theme_token('seleccion_fondo', '#3d3d3d')}; }}
                """)

    def _on_canvas_clicked(self):
        """Clic normal (izquierdo): modo normal de canvas (crop_free)."""
        self._canvas_right_activated = False
        if hasattr(self, "btn_canvas") and self.btn_canvas.is_open():
            self.btn_canvas.set_open(False)
        self._style_tool_buttons()

    def _on_canvas_popover_opened(self):
        """Clic derecho en Canvas -- abre el menú de opciones (Ajuste/Margen/
        Posición/Overflow); si Canvas no era la herramienta activa, la selecciona
        también, y activa el icono crop."""
        self._canvas_right_activated = True
        if not self.btn_canvas.isChecked():
            self.btn_canvas.setChecked(True)
        self.canvas_popover_content.sync()
        self._style_tool_buttons()

    def _on_layers_panel_toggled(self, checked: bool):
        """Muestra/oculta el panel flotante de Capas -- independiente de qué
        herramienta esté activa (igual que el panel de Capas de Photoshop)."""
        self._style_layers_panel_button(checked)
        if checked:
            self.layers_floating_panel.show_panel()
        else:
            self.layers_floating_panel.hide_panel()

    def _style_layers_panel_button(self, checked: bool):
        icon = "stacks.svg"
        color = get_theme_token('acento_primario', '#B9E640') if checked else "#6c7086"
        self.btn_layers_panel.setIcon(get_colored_svg_icon(icon, color, size=18))
        border = get_theme_token('acento_primario', '#B9E640') if checked else get_theme_token('borde_normal', '#2d2d2d')
        self.btn_layers_panel.setStyleSheet(f"""
            QPushButton {{
                min-width: 30px; max-width: 30px;
                min-height: 30px; max-height: 30px;
                background-color: {get_theme_token('fondo_elemento', '#2d2d2d')};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 0px;
            }}
            QPushButton:hover {{
                background-color: {get_theme_token('seleccion_fondo', '#3d3d3d')};
            }}
        """)

    # ------------------------------------------------------------------
    # Puente LayerStack <-> LayersPanel <-> ZoomableImageViewer
    # ------------------------------------------------------------------
    def _refresh_layers_panel(self):
        self.layers_panel.rebuild_rows(self.layer_stack.layers)

    def _find_layer(self, layer_id: int) -> Layer | None:
        return next((l for l in self.layer_stack.layers if l.id == layer_id), None)

    # ------------------------------------------------------------------
    # Opciones de herramientas de dibujo (clic derecho, ver tool_options_popover.py)
    # ------------------------------------------------------------------
    _TOOL_STYLES_CONFIG_KEY = "image_editor_tool_styles"

    def _load_tool_styles(self) -> dict:
        saved = get_config().get(self._TOOL_STYLES_CONFIG_KEY) or {}
        return {mode: {**defaults, **(saved.get(mode) or {})}
                for mode, defaults in DEFAULT_TOOL_STYLES.items()}

    def _save_tool_styles(self):
        config = get_config()
        config[self._TOOL_STYLES_CONFIG_KEY] = self._tool_styles
        save_config(config)

    def _push_tool_style(self, tool: str):
        """Le pasa al visor el estilo con el que dibuja `tool`. El visor tiene un solo
        juego de relleno/borde/ancho para formas y líneas, así que se reescribe cada
        vez que cambia la herramienta (Línea tiene sus propios ajustes)."""
        viewer = self.preview.zoom_viewer
        mode = TOOL_OPTION_MODE.get(tool)
        style = self._tool_styles.get(mode) if mode else None
        if mode == "shape":
            viewer.set_draw_style(
                QColor(style["fill"]) if style["fill_enabled"] else None,
                QColor(style["stroke"]) if style["stroke_enabled"] else None,
                style["stroke_width"])
        elif mode == "line":
            viewer.set_draw_style(None, QColor(style["color"]), style["width"])
        elif mode == "brush":
            viewer.set_brush_style(QColor(style["color"]), style["size"])
        elif mode == "eraser":
            viewer.set_eraser_style(style["size"], style["softness"])
        elif mode == "text":
            viewer.set_text_style(style)

    def _eraser_target(self):
        """Provider del Borrador (ver ZoomableImageViewer.set_eraser_target_provider):
        solo la capa marcada en Capas, y solo si es la imagen o una capa de pincel."""
        layer_id = self.layers_panel.selected_layer_id()
        layer = self._find_layer(layer_id) if layer_id is not None else None
        if layer is None:
            return None, self.tr("Marca en Capas la capa que quieres borrar.")
        if not layer.visible:
            return None, self.tr("La capa marcada está oculta.")
        if layer.kind in ("shape", "fill", "text"):
            if get_config().get(self._RASTERIZE_NO_ASK_KEY):
                # Ya aceptó no volver a preguntar: se rasteriza y el trazo sigue sin cortarse.
                if not self._rasterize_layer(layer):
                    return None, ""
            else:
                # El aviso NO se abre aquí: estamos dentro del mousePress del visor y un
                # diálogo modal se quedaría con el release -- el visor seguiría "borrando"
                # sin botón apretado. Se pregunta apenas termina el clic; si acepta,
                # el siguiente trazo ya borra.
                QTimer.singleShot(0, lambda l=layer: self._confirm_rasterize_for_eraser(l))
                return None, ""
        return layer.graphics_item, ""

    _RASTERIZE_NO_ASK_KEY = "image_editor_rasterize_no_ask"

    def _confirm_rasterize_for_eraser(self, layer):
        if layer not in self.layer_stack.layers:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle(self.tr("Rasterizar capa"))
        box.setText(self.tr("Para borrar «{0}» hay que convertirla en píxeles.").format(layer.name))
        box.setInformativeText(self.tr(
            "Podrás borrarla y moverla, pero ya no cambiarle el color, el borde ni el tamaño "
            "como forma. ¿Continuar?"))
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Yes)
        no_ask = QCheckBox(self.tr("No volver a preguntar"))
        box.setCheckBox(no_ask)
        if box.exec() != QMessageBox.Yes:
            return
        if no_ask.isChecked():
            config = get_config()
            config[self._RASTERIZE_NO_ASK_KEY] = True
            save_config(config)
        if self._rasterize_layer(layer):
            QToolTip.showText(QCursor.pos(), self.tr("Listo: ya puedes borrar «{0}».").format(layer.name),
                              self.preview.zoom_viewer.viewport())

    def _on_layer_rasterize_requested(self, layer_id: int):
        layer = self._find_layer(layer_id)
        if layer is not None:
            self._rasterize_layer(layer)

    def _rasterize_layer(self, layer) -> bool:
        """Reemplaza el item de una forma/fondo por su versión en píxeles, conservando
        la capa (id, nombre, orden, opacidad, visibilidad). Queda marcada y como capa
        activa del Pincel, igual que cualquier capa de píxeles."""
        if layer.kind not in ("shape", "fill", "text"):
            return False
        old, old_kind = layer.graphics_item, layer.kind
        new = rasterize_item(old)
        if new is None:
            return False
        self._history_swap_item(layer, new, "raster")
        self._refresh_layers_panel()
        self._on_layer_row_selected(layer.id)
        self._push_history(RasterizeCommand(self, self.tr("Rasterizar capa"), layer, old, old_kind, new))
        return True

    # ------------------------------------------------------------------
    # Deshacer / Rehacer (ver layers/history.py)
    # ------------------------------------------------------------------
    def _make_history_button(self, icon: str) -> QPushButton:
        btn = QPushButton()
        btn.setFixedSize(30, 30)
        btn.setIcon(get_colored_svg_icon(icon, get_theme_token("texto_principal", "#ffffff"), size=16))
        btn.setIconSize(QSize(16, 16))
        btn.setCursor(Qt.PointingHandCursor)
        btn.setEnabled(False)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {get_theme_token('fondo_elemento', '#2d2d2d')};
                border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                border-radius: 6px;
                padding: 0px;
            }}
            QPushButton:hover {{ background-color: {get_theme_token('seleccion_fondo', '#3d3d3d')}; }}
            QPushButton:disabled {{ background-color: transparent; }}
        """)
        return btn

    def _refresh_history_tooltips(self, *_):
        undo_text = self._undo_group.undoText()
        redo_text = self._undo_group.redoText()
        undo = self.tr("Deshacer: {0}").format(undo_text) if undo_text else self.tr("Deshacer")
        redo = self.tr("Rehacer: {0}").format(redo_text) if redo_text else self.tr("Rehacer")
        self.btn_undo.setToolTip(self._with_keys(undo, "editor.undo"))
        self.btn_redo.setToolTip(self._with_keys(redo, "editor.redo"))

    # ------------------------------------------------------------------
    # Atajos de teclado (ver core/utils/shortcuts.py)
    # ------------------------------------------------------------------
    _SHAPE_TOOL_CYCLE = ("rect", "ellipse", "line")
    _last_shape_tool = "rect"

    @staticmethod
    def _with_keys(text: str, action_id: str) -> str:
        keys = shortcuts.display_keys(action_id)
        return f"{text} ({keys})" if keys else text

    def _bind_editor_shortcuts(self):
        b = self._shortcut_binder
        viewer = self.preview.zoom_viewer
        # Toda la pestaña: los campos de texto se quedan con las teclas que usan.
        for tool in ("select", "rect", "ellipse", "line", "brush", "eraser", "text", "canvas"):
            b.bind(f"editor.tool.{tool}", self, lambda t=tool: self._select_tool(t), auto_repeat=False)
        b.bind("editor.tool.shapes_cycle", self, self._cycle_shape_tool, auto_repeat=False)
        b.bind("editor.layers_panel", self, self.btn_layers_panel.toggle, auto_repeat=False)
        b.bind("editor.size_down", self, lambda: self._adjust_tool_size(-1))
        b.bind("editor.size_up", self, lambda: self._adjust_tool_size(+1))
        b.bind("editor.duplicate", self, self._duplicate_selected_layer, auto_repeat=False)
        b.bind("editor.undo", self, self._undo_group.undo)
        b.bind("editor.redo", self, self._undo_group.redo)
        b.bind("editor.cancel", self, self._on_cancel_shortcut, auto_repeat=False)
        # Solo en el visor: las flechas mueven la selección, pero en la cola o en un
        # campo numérico tienen que seguir haciendo lo suyo.
        for suffix, dx, dy in (("left", -1, 0), ("right", 1, 0), ("up", 0, -1), ("down", 0, 1)):
            b.bind(f"editor.nudge_{suffix}", viewer, lambda x=dx, y=dy: self._nudge_selection(x, y))
            b.bind(f"editor.nudge_{suffix}_10", viewer, lambda x=dx, y=dy: self._nudge_selection(10 * x, 10 * y))
        # Suprimir / Retroceso: solo con el foco en el visor o en el panel de Capas -- la
        # cola de archivos usa esas mismas teclas para quitar archivos (ver
        # ImageQueueWidget.eventFilter), y un atajo de pestaña se dispararía antes.
        b.bind("editor.delete_layer", [viewer, self.layers_floating_panel], self._delete_selected_layer)

    def _refresh_shortcut_tooltips(self):
        names = {
            "select": self.tr("Seleccionar"), "rect": self.tr("Rectángulo"), "ellipse": self.tr("Elipse"),
            "line": self.tr("Línea"), "brush": self.tr("Pincel"), "eraser": self.tr("Borrador"),
            "text": self.tr("Texto"), "canvas": self.tr("Canvas"),
        }
        for tool, name in names.items():
            action_id = f"editor.tool.{tool}"
            if tool in self._SHAPE_TOOL_CYCLE and not shortcuts.get_keys(action_id):
                action_id = "editor.tool.shapes_cycle"
            text = self._with_keys(name, action_id)
            if tool != "select":
                text += " — " + self.tr("clic derecho: opciones")
            self._tool_buttons[tool].setToolTip(text)
        self.btn_layers_panel.setToolTip(self._with_keys(self.tr("Mostrar/ocultar panel de Capas"), "editor.layers_panel"))
        self._refresh_history_tooltips()

    def _select_tool(self, tool: str):
        # click() y no setChecked(): pasa por los mismos handlers que un clic real
        # (Canvas, por ejemplo, cierra su panel de opciones en el clic).
        self._tool_buttons[tool].click()

    def _cycle_shape_tool(self):
        """U: fuera de las formas vuelve a la última usada; dentro, pasa a la siguiente
        (Rectángulo -> Elipse -> Línea), como en Photoshop."""
        current = self._current_tool_key()
        if current in self._SHAPE_TOOL_CYCLE:
            i = self._SHAPE_TOOL_CYCLE.index(current)
            self._select_tool(self._SHAPE_TOOL_CYCLE[(i + 1) % len(self._SHAPE_TOOL_CYCLE)])
        else:
            self._select_tool(self._last_shape_tool)

    _SIZE_KEYS = {"shape": ("stroke_width", 1, 50), "line": ("width", 1, 50),
                  "brush": ("size", 1, 200), "eraser": ("size", 1, 300)}

    def _adjust_tool_size(self, direction: int):
        """[ / ]: tamaño de la herramienta activa (grosor en formas y líneas), a pasos
        de ~10% como en Photoshop, así se nota igual en tamaños chicos y grandes."""
        tool = self._current_tool_key()
        mode = TOOL_OPTION_MODE.get(tool)
        if mode not in self._SIZE_KEYS:
            return
        key, lo, hi = self._SIZE_KEYS[mode]
        current = self._tool_styles[mode][key]
        new = max(lo, min(hi, current + direction * max(1, round(current * 0.1))))
        if new == current:
            return
        self._on_tool_option_changed(mode, key, new)
        btn = self._tool_option_popovers.get(tool)
        if btn is not None and btn.is_open():
            btn.content.load(self._tool_styles[mode])

    def _nudge_selection(self, dx: int, dy: int):
        viewer = self.preview.zoom_viewer
        item = viewer.selected_item()
        if item is None:
            return
        before = viewer.item_geometry(item)
        viewer._translate_item(item, QPointF(dx, dy))
        after = viewer.item_geometry(item)
        viewer.viewport().update()
        self._push_history(NudgeCommand(self, self.tr("Mover"), item, before, after))

    def _duplicate_selected_layer(self):
        """Ctrl+D: copia la capa seleccionada (en el visor o en la lista) justo encima,
        corrida 10 px para que se vea que es otra. La imagen base no se duplica."""
        viewer = self.preview.zoom_viewer
        layer = self.layer_stack.layer_for_item(viewer.selected_item()) if viewer.selected_item() else None
        if layer is None:
            layer_id = self.layers_panel.selected_layer_id()
            layer = self._find_layer(layer_id) if layer_id is not None else None
        if layer is None or layer.kind == "image" or layer.graphics_item is None:
            return
        clone = _clone_item(layer.graphics_item)
        if clone is None:
            return
        viewer._translate_item(clone, QPointF(10, 10))
        viewer.add_scene_item(clone)
        copy = Layer(self.tr("{0} copia").format(layer.name), layer.kind, clone)
        copy.set_opacity(layer.opacity)
        copy.set_visible(layer.visible)
        index = self.layer_stack.layers.index(layer) + 1
        self.layer_stack.add_layer(copy, index)
        self._push_history(AddLayerCommand(self, self.tr("Duplicar capa"), copy, index))
        self._on_layer_row_selected(copy.id)

    def _on_cancel_shortcut(self):
        """Esc: primero cierra un panel de opciones abierto; si no hay, quita la selección."""
        open_popovers = [btn for btn in self._popover_buttons if btn.is_open()]
        if open_popovers:
            for btn in open_popovers:
                btn.set_open(False)
            return
        viewer = self.preview.zoom_viewer
        if viewer.selected_item() is not None or self.layers_panel.selected_layer_id() is not None:
            viewer.select_item(None)
            self.layers_panel.select_row(None)

    def _history(self) -> QUndoStack | None:
        fp = self._current_filepath
        if not fp:
            return None
        stack = self._undo_stacks.get(fp)
        if stack is None:
            stack = QUndoStack(self._undo_group)
            stack.setUndoLimit(50)
            self._undo_stacks[fp] = stack
        return stack

    def _activate_history(self, filepath: str):
        self._pending_raster_layer = None
        self._undo_group.setActiveStack(self._history() if filepath else None)

    def _prune_history(self):
        """Descarta el historial de los archivos que ya no están en la cola."""
        alive = set(self.image_queue.get_all_filepaths())
        for fp in [fp for fp in self._undo_stacks if fp not in alive]:
            stack = self._undo_stacks.pop(fp)
            self._undo_group.removeStack(stack)
            stack.deleteLater()

    def _push_history(self, command):
        stack = self._history()
        if stack is None:
            return
        # Una capa de pincel que quedó "pendiente" sin trazo que la acompañe (no
        # debería pasar) se registra sola antes, para no perderla del historial.
        if self._pending_raster_layer is not None and not isinstance(command, PixelPatchCommand):
            layer, index = self._pending_raster_layer
            self._pending_raster_layer = None
            stack.push(AddLayerCommand(self, self.tr("Pincel"), layer, index))
        stack.push(command)

    def _on_pixels_changed(self, item, rect, before, after):
        text = self.tr("Borrador") if self._current_tool_key() == "eraser" else self.tr("Pincel")
        grow = self._pending_raster_grow
        self._pending_raster_grow = None
        if grow is not None and grow[0] is item:
            # La capa se agrandó al empezar este trazo: agrandado + trazo = un paso.
            macro = MacroCommand(text)
            macro.add(RasterGrowCommand, self, text, *grow)
            macro.add(PixelPatchCommand, self, text, item, rect, before, after)
            self._push_history(macro)
            return
        pending = self._pending_raster_layer
        if pending is not None and pending[0].graphics_item is item:
            # Primer trazo de una capa nueva: capa + trazo = un solo paso.
            self._pending_raster_layer = None
            macro = MacroCommand(text)
            macro.add(AddLayerCommand, self, text, pending[0], pending[1])
            macro.add(PixelPatchCommand, self, text, item, rect, before, after)
            stack = self._history()
            if stack is not None:
                stack.push(macro)
            return
        self._push_history(PixelPatchCommand(self, text, item, rect, before, after))

    def _on_item_geometry_changed(self, item, before, after):
        if isinstance(before, QRectF):
            resized = before.size() != after.size()
        elif isinstance(before, QLineF):
            resized = (before.p2() - before.p1()) != (after.p2() - after.p1())
        else:
            resized = False
        text = self.tr("Redimensionar") if resized else self.tr("Mover")
        self._push_history(GeometryCommand(self, text, item, before, after))

    def _history_after_change(self):
        # La fila marcada decide dónde pinta el Pincel y qué borra el Borrador, así
        # que deshacer/rehacer no debe perderla: primero una capa recién repuesta,
        # si no la que ya estaba marcada (si sigue existiendo), si no la selección.
        marked_before = self.layers_panel.selected_layer_id()
        self._refresh_layers_panel()
        mark = getattr(self, "_history_mark", None)
        self._history_mark = None
        if mark is None and marked_before is not None and self._find_layer(marked_before) is not None:
            mark = marked_before
        if mark is None:
            selected = self.layer_stack.layer_for_item(self.preview.zoom_viewer.selected_item())
            mark = selected.id if selected else None
        self.layers_panel.select_row(mark)
        self.preview.zoom_viewer.viewport().update()

    def _history_insert_layer(self, layer, index: int):
        if layer.graphics_item is not None and layer.graphics_item.scene() is None:
            self.preview.zoom_viewer.add_scene_item(layer.graphics_item)
        self.layer_stack.add_layer(layer, min(index, len(self.layer_stack.layers)))
        # La capa repuesta queda marcada: así un trazo de pincel después de rehacer
        # sigue en ella en vez de crear otra.
        self._history_mark = layer.id
        if layer.kind == "raster":
            self.preview.zoom_viewer.set_active_raster_layer(layer.graphics_item)

    def _history_remove_layer(self, layer):
        viewer = self.preview.zoom_viewer
        if viewer.selected_item() is layer.graphics_item:
            viewer.select_item(None)
        if viewer.active_raster_layer() is layer.graphics_item:
            viewer.set_active_raster_layer(None)
        self.layer_stack.remove_layer(layer)

    def _history_swap_item(self, layer, item, kind: str):
        """Cambia el item de una capa (rasterizar y su deshacer) conservando orden,
        opacidad y visibilidad."""
        old = layer.graphics_item
        viewer = self.preview.zoom_viewer
        if viewer.selected_item() is old:
            viewer.select_item(None)
        if viewer.active_raster_layer() is old:
            viewer.set_active_raster_layer(None)
        item.setZValue(old.zValue())
        item.setOpacity(layer.opacity)
        item.setVisible(layer.visible)
        if old.scene() is not None:
            old.scene().removeItem(old)
        if item.scene() is None:
            viewer.add_scene_item(item)
        layer.graphics_item = item
        layer.kind = kind

    def _history_apply_pixels(self, item, rect, patch):
        viewer = self.preview.zoom_viewer
        viewer.apply_pixel_patch(item, rect, patch)
        if item is None and self._current_filepath:
            mask = viewer.base_mask()
            if mask is not None:
                self._base_masks[self._current_filepath] = mask

    def _history_set_geometry(self, item, geometry):
        ZoomableImageViewer.set_item_geometry(item, geometry)

    def _history_set_style(self, item, brush, pen):
        if brush is not None and hasattr(item, "setBrush"):
            item.setBrush(brush)
        item.setPen(pen)

    def _history_set_canvas(self, filepath: str, state: dict, override: dict | None):
        self.preview.zoom_viewer.apply_canvas_state(
            state["canvas_rect"], state["mode"], state["resizable"],
            state["image_pos"], state["image_scale"],
        )
        if override is None:
            self._canvas_overrides.pop(filepath, None)
        else:
            self._canvas_overrides[filepath] = override

    def _marked_layer_item(self):
        """Provider del visor: item de la capa marcada en Capas (si está visible)."""
        layer_id = self.layers_panel.selected_layer_id()
        layer = self._find_layer(layer_id) if layer_id is not None else None
        if layer is None or not layer.visible:
            return None
        return layer.graphics_item

    def _on_base_mask_changed(self):
        if self._current_filepath:
            mask = self.preview.zoom_viewer.base_mask()
            if mask is not None:
                self._base_masks[self._current_filepath] = mask

    def _on_tool_option_changed(self, mode: str, key: str, value):
        self._tool_styles[mode][key] = value
        self._save_tool_styles_timer.start()
        current = self._current_tool_key()
        if TOOL_OPTION_MODE.get(current) == mode:
            self._push_tool_style(current)
        self._apply_tool_option_to_selection(mode, key)

    def _apply_tool_option_to_selection(self, mode: str, key: str):
        """Aplica el cambio a la forma seleccionada, si es del tipo que edita ese
        popover. Solo se toca el grupo de la opción cambiada (relleno o borde), para
        no pisarle a la forma el resto de su estilo."""
        viewer = self.preview.zoom_viewer
        if mode == "text":
            item = self._text_target()
            if item is not None:
                before = item.style()
                item.apply_style({key: self._tool_styles["text"][key]})
                after = item.style()
                if after != before:
                    self._push_history(TextStyleCommand(self, self.tr("Estilo de texto"), item, before, after))
                viewer.viewport().update()
            return
        item = viewer.selected_item()
        if item is None:
            return
        style = self._tool_styles[mode]
        before = (QBrush(item.brush()) if hasattr(item, "brush") else None, QPen(item.pen()))
        if mode == "shape" and isinstance(item, (QGraphicsRectItem, QGraphicsEllipseItem)):
            if key in ("fill", "fill_enabled"):
                item.setBrush(QBrush(QColor(style["fill"])) if style["fill_enabled"] else QBrush(Qt.NoBrush))
            else:
                if style["stroke_enabled"]:
                    item.setPen(QPen(QColor(style["stroke"]), style["stroke_width"]))
                else:
                    item.setPen(QPen(Qt.NoPen))
        elif mode == "line" and isinstance(item, QGraphicsLineItem):
            item.setPen(QPen(QColor(style["color"]), style["width"]))
        else:
            return
        after = (QBrush(item.brush()) if hasattr(item, "brush") else None, QPen(item.pen()))
        self._push_history(StyleCommand(self, self.tr("Cambiar estilo"), item, before, after))
        viewer.viewport().update()
        # La miniatura de la fila en Capas muestra el color de relleno.
        layer = self.layer_stack.layer_for_item(item)
        self._refresh_layers_panel()
        if layer is not None:
            self.layers_panel.select_row(layer.id)

    def _on_shape_created(self, item, kind: str):
        label_map = {"rect": self.tr("Rectángulo"), "ellipse": self.tr("Elipse"), "line": self.tr("Línea")}
        label = label_map.get(kind, kind.title())
        name = f"{label} {self._next_layer_number(label + ' {0}')}"
        layer = Layer(name, "shape", item)
        self.layer_stack.add_layer(layer)
        self._push_history(AddLayerCommand(self, self.tr("Dibujar forma"), layer, len(self.layer_stack.layers) - 1))

    def _on_raster_layer_created(self, item):
        pattern = self.tr("Pincel {0}")
        layer = Layer(pattern.format(self._next_layer_number(pattern)), "raster", item)
        # Como en Photoshop: la capa nueva va justo encima de la marcada (o arriba de
        # todo si no hay nada marcado) y pasa a ser la marcada, así los trazos
        # siguientes siguen en ella.
        marked_id = self.layers_panel.selected_layer_id()
        marked = self._find_layer(marked_id) if marked_id is not None else None
        index = self.layer_stack.layers.index(marked) + 1 if marked is not None else len(self.layer_stack.layers)
        self.layer_stack.add_layer(layer, index)
        self.layers_panel.select_row(layer.id)
        # No se registra sola: el trazo que la creó y la capa son UN paso (ver
        # _on_pixels_changed, que arma los dos juntos al terminar el trazo).
        self._pending_raster_layer = (layer, index)

    # -- Texto ----------------------------------------------------------------
    def _text_target(self):
        """Texto al que se aplican las opciones: el que se está editando o, si no, el
        seleccionado."""
        viewer = self.preview.zoom_viewer
        item = viewer.editing_text_item() or viewer.selected_item()
        return item if isinstance(item, EditableTextItem) else None

    def _option_values_for(self, mode: str) -> dict:
        """Lo que muestra un panel de opciones al abrirse: para Texto, el estilo del
        texto en edición/seleccionado; si no, los ajustes de la herramienta."""
        if mode == "text":
            item = self._text_target()
            if item is not None:
                return item.style()
        return self._tool_styles[mode]

    @staticmethod
    def _text_layer_name(text: str) -> str:
        """Como Photoshop: la capa se llama como su texto (primera línea, recortada)."""
        first = next((line.strip() for line in text.splitlines() if line.strip()), "")
        return first if len(first) <= 24 else first[:23].rstrip() + "…"

    def _rename_text_layer_for(self, item):
        layer = self.layer_stack.layer_for_item(item)
        if layer is not None:
            name = self._text_layer_name(item.toPlainText())
            if name:
                layer.name = name

    def _on_text_item_created(self, item):
        pattern = self.tr("Texto {0}")
        layer = Layer(pattern.format(self._next_layer_number(pattern)), "text", item)
        marked_id = self.layers_panel.selected_layer_id()
        marked = self._find_layer(marked_id) if marked_id is not None else None
        index = self.layer_stack.layers.index(marked) + 1 if marked is not None else len(self.layer_stack.layers)
        self.layer_stack.add_layer(layer, index)
        self.layers_panel.select_row(layer.id)

    def _on_text_editing_changed(self, editing: bool):
        # Mientras se escribe sobre la imagen, ningún atajo (V, U, Supr, flechas...)
        # debe robarle teclas al texto. Esc lo recibe el propio texto para terminar.
        self._shortcut_binder.set_enabled(not editing)

    def _on_text_edit_finished(self, item, before: str, is_new: bool):
        layer = self.layer_stack.layer_for_item(item)
        if layer is None:
            return
        text = item.toPlainText()
        index = self.layer_stack.layers.index(layer)
        if is_new:
            if not text.strip():
                # Clic sin escribir nada: el texto vacío se descarta sin dejar rastro.
                self._history_remove_layer(layer)
                return
            self._rename_text_layer_for(item)
            self._push_history(AddLayerCommand(self, self.tr("Texto"), layer, index))
        elif text != before:
            if not text.strip():
                # Se borró todo el texto: equivale a borrar la capa. Se repone lo que
                # decía antes, así deshacer la devuelve completa.
                item.setPlainText(before)
                self._history_remove_layer(layer)
                self._push_history(RemoveLayerCommand(self, self.tr("Borrar capa"), layer, index))
                return
            self._rename_text_layer_for(item)
            self._push_history(TextContentCommand(self, self.tr("Editar texto"), item, before, text))
        self._refresh_layers_panel()
        self.layers_panel.select_row(layer.id)

    def _next_layer_number(self, pattern: str) -> int:
        """Siguiente número libre para un nombre como "Rectángulo {0}": uno más que
        el más alto en uso, cuente o no como forma todavía (una forma rasterizada
        conserva su nombre). Antes se contaban solo las del mismo tipo y los
        números se repetían."""
        prefix, _, suffix = pattern.partition("{0}")
        highest = 0
        for layer in self.layer_stack.layers:
            name = layer.name
            if name.startswith(prefix) and name.endswith(suffix):
                middle = name[len(prefix):len(name) - len(suffix)] if suffix else name[len(prefix):]
                if middle.isdigit():
                    highest = max(highest, int(middle))
        return highest + 1

    def _brush_target(self):
        """Provider del visor para el Pincel: la capa marcada si es de píxeles y
        está visible; si no, None (el visor crea una capa nueva)."""
        layer_id = self.layers_panel.selected_layer_id()
        layer = self._find_layer(layer_id) if layer_id is not None else None
        if layer is None or layer.kind != "raster" or not layer.visible:
            return None
        return layer.graphics_item

    def _on_raster_layer_grown(self, item, old_image, old_pos, new_pos, new_size):
        self._pending_raster_grow = (item, old_image, old_pos, new_pos, new_size)

    def _on_shape_selected(self, item):
        layer = self.layer_stack.layer_for_item(item) if item is not None else None
        self.layers_panel.select_row(layer.id if layer else None)

    def _on_layer_row_selected(self, layer_id: int):
        layer = self._find_layer(layer_id)
        if layer is None:
            return
        self.layer_stack.set_active(layer)
        self.layers_panel.select_row(layer_id)
        viewer = self.preview.zoom_viewer
        if layer.kind == "raster":
            viewer.set_active_raster_layer(layer.graphics_item)
        # Marcar en Capas = seleccionar en la imagen, para cualquier tipo de capa (la
        # imagen base no se arrastra con Seleccionar, así que ella solo se marca).
        # Con otras herramientas no hay selección: el visor muestra el contorno.
        if self._current_tool_key() == "select":
            viewer.select_item(None if layer.kind == "image" else layer.graphics_item)
        # Las filas del panel no toman foco: se lo pasamos al visor para que Suprimir
        # borre esta capa (y no, por ejemplo, el archivo marcado en la cola).
        viewer.setFocus(Qt.OtherFocusReason)

    def _on_layer_visibility_toggled(self, layer_id: int, visible: bool):
        layer = self._find_layer(layer_id)
        if layer is not None and layer.visible != visible:
            layer.set_visible(visible)
            self._push_history(VisibilityCommand(self, self.tr("Visibilidad de capa"), layer, visible))

    def _on_layer_opacity_changed(self, layer_id: int, percent: int):
        layer = self._find_layer(layer_id)
        if layer is not None:
            before = layer.opacity
            layer.set_opacity(percent / 100.0)
            if layer.opacity != before:
                self._push_history(OpacityCommand(self, self.tr("Opacidad de capa"), layer, before, layer.opacity))

    def _on_layer_move_up(self, layer_id: int):
        self._move_layer(layer_id, up=True)

    def _on_layer_move_down(self, layer_id: int):
        self._move_layer(layer_id, up=False)

    def _move_layer(self, layer_id: int, up: bool):
        layer = self._find_layer(layer_id)
        if layer is None:
            return
        before = self.layer_stack.layers.index(layer)
        (self.layer_stack.move_up if up else self.layer_stack.move_down)(layer)
        if self.layer_stack.layers.index(layer) != before:
            self._push_history(MoveLayerCommand(self, self.tr("Orden de capas"), layer, up))

    def _on_add_background_requested(self):
        viewer = self.preview.zoom_viewer
        size = viewer.image_size()
        if size is None:
            return
        dialog = BackgroundDialog(size.width(), size.height(), self)
        if not dialog.exec():
            return
        item = dialog.build_layer_item()
        viewer.add_scene_item(item)
        pattern = self.tr("Fondo {0}")
        # index=0: un Fondo siempre va al fondo del stack, debajo de todo lo demás.
        layer = Layer(pattern.format(self._next_layer_number(pattern)), "fill", item)
        self.layer_stack.add_layer(layer, index=0)
        self._push_history(AddLayerCommand(self, self.tr("Añadir fondo"), layer, 0))

    def _delete_selected_layer(self):
        """Atajo Suprimir/Retroceso: borra la figura seleccionada en el visor o, si no hay,
        la fila marcada en el panel de Capas (capas de pincel y fondos no se seleccionan
        en el visor, solo desde la lista)."""
        layer = None
        item = self.preview.zoom_viewer.selected_item()
        if item is not None:
            layer = self.layer_stack.layer_for_item(item)
        if layer is None:
            layer_id = self.layers_panel.selected_layer_id()
            layer = self._find_layer(layer_id) if layer_id is not None else None
        # La capa "image" (la imagen misma) no se borra -- igual que en el panel, donde
        # su fila no tiene botón de eliminar.
        if layer is not None and layer.kind != "image":
            self._on_layer_delete(layer.id)

    def _on_layer_delete(self, layer_id: int):
        layer = self._find_layer(layer_id)
        if layer is None:
            return
        index = self.layer_stack.layers.index(layer)
        self._history_remove_layer(layer)
        self._push_history(RemoveLayerCommand(self, self.tr("Borrar capa"), layer, index))

    def eventFilter(self, obj, event):
        """Cierra cualquier popover de la franja superior (Reescalar IA, Eliminar
        Fondo IA, ...) al clickear afuera de su botón y de su contenido -- mismo
        patrón que quick_mode_view.py para su popover de "Recodificar".

        Dos clases de clic NO cuentan como "afuera", y las dos hay que dejarlas
        pasar porque este filtro está puesto sobre QApplication y por lo tanto ve
        los clics de toda la app, no solo los de esta pestaña:
          - Los de un popup interno (el desplegable de un combo): activePopupWidget.
          - Los de un diálogo modal encima (ej. "¿descargar este modelo?", ver
            gui/widgets/model_download_prompt.py): activeModalWidget. Caen en otra
            ventana, así que geométricamente son "afuera" de cualquier popover, pero
            mientras el modal está arriba el usuario ni siquiera PUEDE tocar el
            popover -- cerrarlo por ese clic es puro efecto colateral. Sin esta
            guarda, apretar Descargar/Cancelar cerraba el popover y escondía justo
            el porcentaje de la descarga recién lanzada."""
        if (event.type() == QEvent.MouseButtonPress
                and QApplication.activePopupWidget() is None
                and QApplication.activeModalWidget() is None):
            pos = event.globalPos()
            for btn in getattr(self, "_popover_buttons", []):
                if not btn.is_open():
                    continue
                btn_rect, content_rect = btn.global_rects()
                if not btn_rect.contains(pos) and not content_rect.contains(pos):
                    btn.set_open(False)
        return super().eventFilter(obj, event)

    def _on_file_selected(self, filepath: str):
        # Un texto a medio escribir se cierra (y registra) antes de guardar las capas
        # del archivo que se deja.
        self.preview.zoom_viewer.end_text_editing()
        old_filepath = self._current_filepath
        self._current_filepath = filepath
        self._activate_history(filepath)
        self._refresh_title_and_copy_button(filepath)

        # Fase 3 -- antes de tocar nada, guardar las formas/trazos (capas no-
        # "image") que tuviera el archivo que se estaba mirando hasta ahora.
        # El Canvas manual ya quedó guardado al vuelo en _on_canvas_edited, no
        # hace falta repetirlo aquí.
        self._snapshot_layers_for(old_filepath)
        self.layer_stack.clear()

        # A diferencia del diseño anterior (y de DowP1), un archivo ya convertido
        # NO pasa a mostrar la comparación antes/después de forma permanente --
        # el editor (con las formas/pincel/Canvas del usuario) sigue siendo la
        # vista por defecto, como en Photoshop: conviertes y puedes seguir editando.
        # Comparar es una acción explícita (ver btn_compare_result/
        # _on_compare_toggled)... EXCEPTO si el resultado de este archivo incluyó
        # IA (reescalado por ahora, ver _files_with_ai_edit/
        # _on_convert_file_completed -- a futuro también Eliminar Fondo, cuando
        # tenga su ejecución conectada): ahí Comparar arranca activado, porque ver
        # el antes/después es lo primero que se quiere confirmar de un resultado
        # generado por IA.
        self._show_editable_view(filepath)
        auto_compare = (
            bool(filepath)
            and bool(self.image_queue.get_output_path(filepath))
            and self._files_with_ai_edit.get(filepath, False)
        )
        self.btn_compare_result.blockSignals(True)
        self.btn_compare_result.setChecked(auto_compare)
        self.btn_compare_result.blockSignals(False)
        if auto_compare:
            self._show_compare_view(filepath)

    def _show_editable_view(self, filepath: str):
        """Carga el editor normal (imagen + formas/pincel/Canvas restaurados) para
        `filepath` -- llamado desde _on_file_selected y también al desmarcar
        Comparar (_on_compare_toggled) para volver desde la vista de comparación
        sin perder nada de lo ya restaurado."""
        if not filepath:
            self.preview.show_default_state()
            return

        self.preview.show_image_preview(filepath)
        viewer = self.preview.zoom_viewer
        # show_image_preview() vuelve a cargar el pixmap del visor -- eso ya deja
        # el canvas inicializado a su tamaño nativo (como borde de referencia) y
        # el modo en "pan" por su cuenta (ver ZoomableImageViewer._reset_edit_state);
        # aquí solo hace falta reaplicar la herramienta que estuviera activa.
        current_tool = self._current_tool_key()
        if current_tool == "canvas":
            viewer.set_interaction_mode("canvas_edit")
        else:
            viewer.set_interaction_mode("layers_draw")
            viewer.set_active_tool(current_tool)
            self._push_tool_style(current_tool)
        size = viewer.image_size()
        if size is not None:
            self.canvas_popover_content.set_reference_image_size(size.width(), size.height())
        # El Canvas NO se resetea a un estado fijo aquí a propósito: desde que un
        # preset del menú (clic derecho) pasó a ser una configuración de LOTE (ver
        # canvas_popover_content.get_settings(), usada por Convertir para TODOS los
        # archivos), resetearlo al cambiar de fila borraba esa elección apenas se
        # miraba otro archivo. Si este archivo tiene un Canvas editado a mano
        # (_canvas_overrides, Fase 3) se reaplica tal cual; si no, se llama sync()
        # (no solo si el popover está abierto) para que el overlay se reajuste al
        # tamaño nativo de CADA archivo con el mismo preset elegido -- visualmente
        # confirma que "se aplica a todos, adaptado por archivo".
        canvas_override = self._canvas_overrides.get(filepath)
        if canvas_override is not None:
            viewer.apply_canvas_state(
                canvas_override["canvas_rect"], canvas_override["mode"],
                canvas_override["resizable"], canvas_override["image_pos"],
                canvas_override["image_scale"],
            )
        else:
            self.canvas_popover_content.sync()
        base_item = viewer.base_pixmap_item()
        if base_item is not None:
            self.layer_stack.add_layer(Layer(self.tr("Imagen Base"), "image", base_item))
            if filepath in self._base_masks:
                viewer.set_base_mask(self._base_masks[filepath])
        # Fase 3 -- reponer las formas/trazos que este archivo ya tenía.
        for layer in self._layer_snapshots.get(filepath, []):
            viewer.add_scene_item(layer.graphics_item)
            self.layer_stack.add_layer(layer)

    def _warn_result_missing(self, filepath: str):
        """Comparar/Copiar clickeados sobre un resultado que ya no existe en
        disco (se movió/borró después de convertir, ej. desde el explorador) --
        image_queue.get_output_path() ya se auto-corrigió del lado de la cola
        (limpia el registro y pone "Resultado eliminado" en la fila, ver
        image_queue_widget.py); aquí solo se refleja en estos botones y se avisa
        -- sin esto fallaba en silencio (Comparar mostraba cualquier cosa,
        Copiar no copiaba nada) sin que quede claro por qué."""
        QMessageBox.information(
            self, self.tr("Resultado no encontrado"),
            self.tr("El resultado de este archivo ya no existe en disco -- puede "
                     "que lo hayas movido o borrado después de convertir."),
        )
        self._refresh_title_and_copy_button(filepath)

    def _show_compare_view(self, filepath: str) -> bool:
        """Muestra la comparación antes/después de `filepath` -- usado tanto por el
        toggle manual (_on_compare_toggled) como por la activación automática
        cuando el trabajo incluyó IA (ver _files_with_ai_edit). Devuelve False si
        el resultado ya no existe en disco (ver _warn_result_missing)."""
        output_path = self.image_queue.get_output_path(filepath)
        if not output_path:
            self._warn_result_missing(filepath)
            return False
        before_pix, after_pix = self._compare_cache.get(filepath)
        self.preview.show_compare_preview(filepath, output_path, before_pix, after_pix)
        cv = self.preview.compare_viewer
        if before_pix is None or after_pix is None:
            # Cache miss -- preview_panel ya cargó de disco/re-renderizó; se
            # guardan los pixmaps recién usados para la próxima vez.
            self._compare_cache.put(filepath, cv.before_pixmap(), cv.after_pixmap())
        self._update_depth_note(filepath)
        return True

    def _update_depth_note(self, filepath: str):
        """Nota amarilla "920×518 calculado" bajo "Resultado" en la vista
        comparativa: el mapa se guarda al tamaño original, pero su detalle real
        es el de la resolución a la que calculó el modelo (ver
        depth_engine.get_process_size). Solo aparece si el lote fue únicamente
        de profundidad (ver _on_convert_file_completed) y si el cálculo quedó
        claramente por debajo del tamaño del resultado -- en una imagen chica,
        que casi no se amplía, la nota solo sería ruido."""
        cv = self.preview.compare_viewer
        size = self._depth_process_sizes.get(filepath)
        after = cv.after_pixmap()
        if not size or after.isNull():
            cv.set_after_note("")
            return
        process_w, process_h, kind = size
        result_w, result_h = after.width(), after.height()
        if process_w >= result_w * 0.9 and process_h >= result_h * 0.9:
            cv.set_after_note("")
            return
        if kind == "normals":
            tooltip = self.tr(
                "El modelo calculó las normales a {0}×{1} y el resultado se amplió a "
                "{2}×{3}: los bordes tendrán menos detalle que la imagen original."
            ).format(process_w, process_h, result_w, result_h)
        else:
            tooltip = self.tr(
                "El modelo calculó la profundidad a {0}×{1} y el resultado se amplió a "
                "{2}×{3}: los bordes tendrán menos detalle que la imagen original."
            ).format(process_w, process_h, result_w, result_h)
        if kind == "depth" and process_w == process_h and abs(result_w / max(1, result_h) - 1.0) > 0.05:
            tooltip += "\n" + self.tr(
                "Este modelo calcula en cuadrado, así que la imagen se deformó durante el cálculo.")
        cv.set_after_note(self.tr("{0}×{1} calculado").format(process_w, process_h), tooltip)

    def _on_compare_toggled(self, checked: bool):
        """Comparar (título/botones, ver _build_ui) -- vista bajo demanda, no
        permanente: desmarcar vuelve al editor tal cual estaba (_show_editable_view
        reaplica las formas/Canvas restauradas, no se pierde nada)."""
        filepath = self._current_filepath
        if not filepath:
            return
        if checked:
            if not self._show_compare_view(filepath):
                # Resultado eliminado (ver _warn_result_missing) -- revertir el
                # toggle en vez de dejarlo marcado mostrando cualquier cosa.
                self.btn_compare_result.blockSignals(True)
                self.btn_compare_result.setChecked(False)
                self.btn_compare_result.blockSignals(False)
        else:
            # No se recarga nada -- la escena del editor (formas/pincel/Canvas)
            # nunca se tocó mientras se mostraba Comparar (show_compare_preview()
            # solo oculta el widget, no vacía la escena), así que alcanza con
            # volver a mostrarlo tal cual estaba.
            self.preview.show_zoom_viewer_only()

    def _refresh_title_and_copy_button(self, filepath: str):
        """Título editable (default = nombre del archivo) y botones Copiar/Comparar
        (solo habilitados si ese archivo ya tiene un resultado convertido) -- se
        llama en cada cambio de selección y también al completarse una conversión
        (ver _on_convert_file_completed) para la fila que se está mirando."""
        has_file = bool(filepath)
        has_output = has_file and bool(self.image_queue.get_output_path(filepath))
        self.entry_title.setEnabled(has_file)
        self.entry_title.setText(self.image_queue.get_title(filepath) if has_file else "")
        self.btn_copy_result.setEnabled(has_output)
        self.btn_compare_result.setEnabled(has_output)

    def _on_title_edited(self):
        if self._current_filepath:
            self.image_queue.set_title(self._current_filepath, self.entry_title.text())

    def _on_copy_result_clicked(self):
        if not self._current_filepath:
            return
        output_path = self.image_queue.get_output_path(self._current_filepath)
        if not output_path:
            self._warn_result_missing(self._current_filepath)
            return

        if os.path.splitext(output_path)[1].lower() == ".svg":
            copied = self._copy_svg_result_to_clipboard(output_path)
        else:
            pixmap = QPixmap(output_path)
            copied = not pixmap.isNull()
            if copied:
                QApplication.clipboard().setPixmap(pixmap)

        if copied:
            # Feedback visual
            original_text = self.btn_copy_result.text()
            self.btn_copy_result.setText(self.tr("¡Copiado!"))
            # Opcional: Cambiar estilo para dar énfasis (si el tema lo soporta) o simplemente dejar el texto.
            self.btn_copy_result.setProperty("variant", "success")
            self.btn_copy_result.style().unpolish(self.btn_copy_result)
            self.btn_copy_result.style().polish(self.btn_copy_result)
            
            def restore_button():
                self.btn_copy_result.setText(original_text)
                self.btn_copy_result.setProperty("variant", "accent-blue")
                self.btn_copy_result.style().unpolish(self.btn_copy_result)
                self.btn_copy_result.style().polish(self.btn_copy_result)
            
            QTimer.singleShot(1500, restore_button)
        else:
            QMessageBox.warning(
                self, self.tr("No se pudo copiar"),
                self.tr("El archivo existe pero no se pudo leer como imagen."),
            )

    def _copy_svg_result_to_clipboard(self, output_path: str) -> bool:
        """SVG es vectorial -- copiar un QPixmap (como el resto de los formatos)
        lo rasteriza a un bitmap fijo y pierde justo lo que hace valioso al SVG.
        En cambio se copia el ARCHIVO real vía QMimeData.setUrls(), el mismo
        mecanismo portable que ya usa _start_file_drag() en subclip_dialog.py
        para arrastrar archivos afuera de la app -- Qt lo traduce solo al formato
        de portapapeles nativo de cada SO (CF_HDROP en Windows, NSFilenamesPboardType
        en macOS, text/uri-list en Linux/X11/Wayland), así que pegarlo en el
        explorador de archivos o en un editor vectorial (Illustrator/Inkscape) da
        el SVG real, editable. Se agrega además una vista previa rasterizada en el
        mismo QMimeData -- por si la app de destino solo sabe pegar "una imagen",
        no un archivo (ej. un chat/editor de texto)."""
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(output_path)])
        pixmap = QPixmap(output_path)
        if not pixmap.isNull():
            mime.setImageData(pixmap.toImage())
        QApplication.clipboard().setMimeData(mime)
        return True

    def _build_queue_content(self) -> QWidget:
        """Lista de imágenes (arriba) + panel "Convertir" con opciones de formato
        encapsuladas (abajo). Las acciones globales de destino/conversión viven
        en la barra inferior de la pestaña."""
        container = QFrame()
        container.setObjectName("unifiedQueuePanel")
        bg_color = get_theme_token('fondo_secundario', '#1e1e1e')
        border_color = get_theme_token('borde_normal', '#2d2d2d')
        container.setStyleSheet(f"""
            QFrame#unifiedQueuePanel {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: 6px;
            }}
        """)
        
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.image_queue = ImageQueueWidget()
        layout.addWidget(self.image_queue, 1)

        # Divisor sutil entre la lista y las opciones
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"background-color: {get_theme_token('borde_sutil', '#2d2d2d')}; max-height: 1px; border: none;")
        layout.addWidget(sep)

        self.convert_panel = ConvertPanel()
        # La casilla "Mapa de profundidad: 16 bits" de las páginas PNG/TIFF solo se
        # muestra con la profundidad activa (ver ConvertPanel.set_depth_active).
        self.depth_popover_content.selection_changed.connect(
            lambda _family, _model, is_valid: self.convert_panel.set_depth_active(is_valid))
        self.convert_panel.set_depth_active(self.depth_popover_content.is_valid_selection())
        self.convert_panel.validity_changed.connect(self._on_convert_validity_changed)
        layout.addWidget(self.convert_panel, 0)

        self._convert_worker = None
        self._update_convert_button_state()
        self.image_queue.queue_updated.connect(lambda _count: self._update_convert_button_state())
        self.image_queue.queue_updated.connect(lambda _count: self._prune_history())
        return container

    def _build_output_bar(self) -> QFrame:
        """Panel inferior unificado de salida y conversión -- política de conflicto,
        ruta de destino con botones de examinar/abrir, botón de acción Convertir/Cancelar
        y barra de progreso BouncingProgressBar (mismo estilo y experiencia que
        Modo Rápido, Proceso Avanzado y Herramientas de Video)."""
        card = QFrame()
        card.setObjectName("imageToolsOutputBar")
        border_color = get_theme_token('borde_normal', '#2d2d2d')
        bg_color = get_theme_token('fondo_secundario', '#1e1e1e')
        card.setStyleSheet(f"""
            QFrame#imageToolsOutputBar {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: 6px;
            }}
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 8, 12, 8)
        card_layout.setSpacing(6)

        controls_row = QHBoxLayout()
        controls_row.setContentsMargins(0, 0, 0, 0)
        controls_row.setSpacing(8)

        # 1. Si existe (política de conflicto)
        lbl_conflict = QLabel(self.tr("Si existe:"))
        lbl_conflict.setObjectName("menuLabel")
        controls_row.addWidget(lbl_conflict)

        self.combo_conflict_policy = AutoPopupComboBox()
        self.combo_conflict_policy.addItem(self.tr("Sobrescribir"), "sobrescribir")
        self.combo_conflict_policy.addItem(self.tr("Conservar"), "conservar")
        self.combo_conflict_policy.addItem(self.tr("Omitir"), "omitir")
        self.combo_conflict_policy.setCurrentIndex(1)  # "Conservar" por defecto
        self.combo_conflict_policy.setFixedHeight(32)
        self.combo_conflict_policy.setToolTip(self.tr(
            "• Sobrescribir: reemplaza el archivo existente (con respaldo reversible).\n"
            "• Conservar: guarda el nuevo archivo como 'nombre (1).ext'.\n"
            "• Omitir: no convierte ese archivo."
        ))
        controls_row.addWidget(self.combo_conflict_policy)

        # 2. Ruta de destino + Examinar + Abrir + Etiqueta. Sin texto "Ruta:" delante: los
        # íconos de carpeta ya lo dejan claro; el tooltip cubre el caso de campo lleno (el
        # placeholder deja de verse en cuanto hay una ruta escrita).
        self.entry_output_folder = QLineEdit()
        self.entry_output_folder.setPlaceholderText(self.tr("Ruta de destino"))
        self.entry_output_folder.setToolTip(self.tr("Carpeta de destino"))
        self.entry_output_folder.setFixedHeight(32)
        
        # Cargar ruta desde config, o usar Imágenes por defecto
        config = get_config()
        saved_path = config.get("image_tools_output_path", "")
        if not saved_path or not os.path.isdir(saved_path):
            saved_path = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
        self.entry_output_folder.setText(saved_path)
        self.entry_output_folder.editingFinished.connect(self._save_output_path)
        
        controls_row.addWidget(self.entry_output_folder, 1)

        self.btn_browse_output_folder = QPushButton()
        self.btn_browse_output_folder.setFixedSize(32, 32)
        self.btn_browse_output_folder.setCursor(Qt.PointingHandCursor)
        apply_folder_browse_button_style(self.btn_browse_output_folder, self.tr("Elegir carpeta de destino"))
        self.btn_browse_output_folder.clicked.connect(self._on_browse_output_folder)
        controls_row.addWidget(self.btn_browse_output_folder)

        self.btn_open_output_folder = QPushButton()
        self.btn_open_output_folder.setFixedSize(32, 32)
        self.btn_open_output_folder.setCursor(Qt.PointingHandCursor)
        apply_folder_open_button_style(self.btn_open_output_folder, self.tr("Abrir carpeta de destino"))
        self.btn_open_output_folder.clicked.connect(self._on_open_output_folder)
        controls_row.addWidget(self.btn_open_output_folder)

        # Etiqueta: mismo comportamiento que en Herramientas Multimedia
        # (video_tools_view.py::_on_label_changed) y mismo ancho fijo que en Modo Rápido.
        self.combo_tags = AutoPopupComboBox()
        self.combo_tags.setObjectName("tagsComboBox")
        self.combo_tags.setPlaceholderText(self.tr("Etiqueta"))
        self.combo_tags.setFixedHeight(32)
        self.combo_tags.setFixedWidth(130)
        self.combo_tags.currentIndexChanged.connect(
            lambda i: self.combo_tags.setToolTip(self.combo_tags.itemText(i) if i > 0 else ""))
        self.combo_tags.currentIndexChanged.connect(self._on_label_changed)
        controls_row.addWidget(self.combo_tags)
        self.load_labels()

        # 3. Botón de acción: Iniciar Proceso (cambia dinámicamente a Cancelar en ejecución)
        self._convert_running = False
        self.btn_convert = AnimatedButton(self.tr("Iniciar Proceso"))
        self.btn_convert.setProperty("variant", "primary")
        self.btn_convert.setFixedHeight(32)
        self.btn_convert.setMinimumWidth(130)
        self.btn_convert.clicked.connect(self._on_convert_button_clicked)
        controls_row.addWidget(self.btn_convert)

        card_layout.addLayout(controls_row)

        # 4. Barra de progreso BouncingProgressBar
        self.progress_bar = BouncingProgressBar()
        self.progress_bar.setObjectName("downloadProgressBar")
        self.progress_bar.setProperty("status", "wait")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(self.tr("En espera"))
        self.progress_bar.setTextVisible(True)
        card_layout.addWidget(self.progress_bar)

        return card

    # ── Etiquetas (mismo patrón que VideoToolsTab: load_labels/_on_label_changed) ──
    def load_labels(self):
        """Carga las etiquetas configuradas, con su círculo de color. La llama MainWindow
        al entrar en la pestaña y al cambiar las etiquetas en Ajustes."""
        if not hasattr(self, "combo_tags"):
            return
        from PySide6.QtGui import QColor

        self.combo_tags.blockSignals(True)
        current_text = self.combo_tags.currentText()
        previous_index = self.combo_tags.currentIndex()
        self.combo_tags.clear()
        self.combo_tags.addItem(self.tr("Etiqueta"), "")

        for label in get_config().get("labels", []):
            name = label.get("name", "")
            path = label.get("path", "")
            color = label.get("color", "#B9E640")
            idx = self.combo_tags.count()
            self.combo_tags.addItem(create_colored_circle_icon(color, size=12), name, path)
            self.combo_tags.setItemData(idx, color, Qt.UserRole + 1)
            self.combo_tags.setItemData(idx, QColor(color), Qt.ForegroundRole)

        idx = self.combo_tags.findText(current_text)
        self.combo_tags.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo_tags.blockSignals(False)
        i = self.combo_tags.currentIndex()
        self.combo_tags.setToolTip(self.combo_tags.itemText(i) if i > 0 else "")
        if previous_index > 0 and idx < 0:
            # La etiqueta elegida se borró en Ajustes: sin esto la ruta quedaba bloqueada
            # con la de una etiqueta que ya no existe.
            self._on_label_changed(0)
        else:
            update_label_combobox_style(self.combo_tags)

    def _on_label_changed(self, index):
        """Con etiqueta: la ruta pasa a ser la suya y no se puede editar. Sin etiqueta:
        vuelve la ruta guardada del Editor de Imagen. La ruta de una etiqueta nunca se
        guarda como ruta habitual (setText no dispara editingFinished)."""
        update_label_combobox_style(self.combo_tags)
        if index <= 0:
            saved_path = get_config().get("image_tools_output_path", "")
            if not saved_path or not os.path.isdir(saved_path):
                saved_path = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
            self.entry_output_folder.setText(saved_path)
            self.entry_output_folder.setEnabled(True)
            self.btn_browse_output_folder.setEnabled(True)
        else:
            path = self.combo_tags.currentData()
            if path:
                self.entry_output_folder.setText(path)
            self.entry_output_folder.setEnabled(False)
            self.btn_browse_output_folder.setEnabled(False)

    def _on_browse_output_folder(self):
        current = self.entry_output_folder.text().strip()
        start = current if os.path.isdir(current) else QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
        selected = QFileDialog.getExistingDirectory(self, self.tr("Elegir carpeta de destino"), start)
        if selected:
            if hasattr(self, "combo_tags"):
                self.combo_tags.setCurrentIndex(0)
            self.entry_output_folder.setText(selected)
            self._save_output_path()
            
    def _save_output_path(self):
        path = self.entry_output_folder.text().strip()
        if os.path.isdir(path):
            config = get_config()
            config["image_tools_output_path"] = path
            save_config(config)

    def _on_open_output_folder(self):
        path = self.entry_output_folder.text().strip()
        if path and os.path.isdir(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # ------------------------------------------------------------------
    # Convertir
    # ------------------------------------------------------------------
    def _on_convert_validity_changed(self, _is_valid: bool):
        self._update_convert_button_state()

    def _update_convert_button_state(self):
        """Habilita "Iniciar Proceso" solo si la cola tiene archivos y las opciones
        actuales son válidas (ej. ICO necesita al menos un tamaño marcado, ver
        ConvertPanel.is_valid()). Si hay una conversión en curso, el botón actúa
        como "Cancelar" y permanece habilitado."""
        if not hasattr(self, "btn_convert"):
            return
        if getattr(self, "_convert_running", False):
            return
        has_files = bool(self.image_queue.get_all_filepaths()) if hasattr(self, "image_queue") else False
        is_valid = self.convert_panel.is_valid() if hasattr(self, "convert_panel") else True
        can_start = has_files and is_valid
        self.btn_convert.setEnabled(can_start)
        if not can_start:
            if not has_files:
                self.btn_convert.setToolTip(self.tr("Agrega al menos una imagen a la lista para iniciar el proceso"))
            else:
                self.btn_convert.setToolTip(self.tr("Revisa la configuración de conversión para continuar"))
        else:
            self.btn_convert.setToolTip(self.tr("Iniciar el proceso de conversión de las imágenes en cola"))

    def _on_convert_button_clicked(self):
        if getattr(self, "_convert_running", False):
            self._on_convert_cancel_clicked()
        else:
            self._on_convert_clicked()

    def _build_source_overrides(self, filepaths: list[str]) -> dict[str, str] | None:
        """Aplana a un PNG temporal cada archivo del lote que tenga formas/pincel
        guardados (self._layer_snapshots) o un Canvas editado a mano
        (self._canvas_overrides) -- ImageConvertWorker leerá de ahí en vez del
        archivo original para ESE archivo (ver source_overrides en
        image_convert_worker.py); el resto de la cola sigue el camino normal, sin
        pasar por aquí. El pixmap base se recarga con preview.load_pixmap_for_path()
        usando el mismo tamaño disponible que usó show_image_preview() al mostrar
        cada archivo -- mismas coordenadas en las que quedaron dibujadas las formas."""
        to_flatten = [
            fp for fp in filepaths
            if self._layer_snapshots.get(fp) or fp in self._canvas_overrides or fp in self._base_masks
        ]
        if not to_flatten:
            return None

        avail_w = max(50, self.preview.width() - 10)
        avail_h = max(50, self.preview.height() - 10)
        self._flatten_temp_dir = tempfile.mkdtemp(prefix="dowp_canvas_flatten_")
        overrides = {}
        for fp in to_flatten:
            base_pixmap = self.preview.load_pixmap_for_path(fp, avail_w, avail_h)
            if base_pixmap is None or base_pixmap.isNull():
                continue
            canvas_state = self._canvas_overrides.get(fp)
            layers = self._layer_snapshots.get(fp, [])
            image = build_flattened_image(base_pixmap, canvas_state, layers, self._base_masks.get(fp))
            temp_path = os.path.join(self._flatten_temp_dir, f"{len(overrides)}.png")
            if image.save(temp_path, "PNG"):
                overrides[fp] = temp_path
        return overrides or None

    def _confirm_ghostscript_if_needed(self, filepaths: list[str]) -> bool:
        """EPS/PS necesita Ghostscript (dependencia opcional, solo Windows por
        ahora -- ver core/setup/ghostscript_setup.py). Si el lote tiene alguno y
        no está instalado, se pregunta ANTES de arrancar en vez de dejar que cada
        archivo falle en silencio con UnsupportedFormatError (ver
        _load_eps_ps en image_converter.py). En Mac/Linux (sin build todavía) no
        se pregunta nada -- esos archivos fallan per-archivo como cualquier otro
        formato no soportado, mismo criterio de siempre."""
        if platform.system() != "Windows":
            return True
        has_eps_ps = any(os.path.splitext(fp)[1].lower() in (".eps", ".ps") for fp in filepaths)
        if not has_eps_ps or check_ghostscript():
            return True

        reply = QMessageBox.question(
            self, self.tr("Ghostscript no encontrado"),
            self.tr(
                "La cola tiene archivo(s) EPS/PS, que necesitan Ghostscript para "
                "convertirse. ¿Descargarlo ahora o cancelar el proceso?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return False
        return self._download_ghostscript_blocking()

    def _download_ghostscript_blocking(self) -> bool:
        """Diálogo modal chico con barra de progreso mientras se descarga
        Ghostscript -- mismo download_ghostscript() que usa la tarjeta de
        Ajustes > Dependencias, aquí bloqueante porque no tiene sentido arrancar
        Convertir sin saber si terminó bien. Simplificación aceptada: sin
        cancelación real a mitad de descarga (es una descarga única y chica),
        mismo criterio que las tarjetas de Ajustes."""
        progress = QProgressDialog(
            self.tr("Descargando Ghostscript..."), self.tr("Cancelar"), 0, 100, self,
        )
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(True)
        progress.setValue(0)

        result = {"success": False, "msg": ""}

        class _GsDownloadThread(QThread):
            finished_signal = Signal(bool, str)
            progress_signal = Signal(int)

            def run(self):
                success, msg = download_ghostscript(progress_callback=self.progress_signal.emit)
                self.finished_signal.emit(success, msg)

        worker = _GsDownloadThread()
        worker.progress_signal.connect(progress.setValue)

        def _on_finished(success, msg):
            result["success"] = success
            result["msg"] = msg
            progress.close()

        worker.finished_signal.connect(_on_finished)
        worker.start()
        progress.exec()
        worker.wait()

        if not result["success"]:
            QMessageBox.warning(
                self, self.tr("Error"),
                self.tr("No se pudo descargar Ghostscript:\n{0}").format(result["msg"]),
            )
        return result["success"]

    def _confirm_vtracer_if_needed(self) -> bool:
        """SVG necesita vtracer (dependencia opcional, ver
        core/setup/vtracer_setup.py, con build portable en los tres SO -- a
        diferencia de Ghostscript, no hace falta distinguir por plataforma aquí).
        Mismo criterio que _confirm_ghostscript_if_needed: si el formato elegido
        es SVG y no está instalado, se pregunta ANTES de arrancar. Solo necesita
        el formato elegido (no toda la cola de archivos), así que se consulta el
        combo directo en vez de esperar a armar el dict de settings completo."""
        if self.convert_panel.combo_format.currentData() != "SVG" or check_vtracer():
            return True

        reply = QMessageBox.question(
            self, self.tr("vtracer no encontrado"),
            self.tr(
                "Elegiste SVG como formato de salida, que necesita vtracer para "
                "vectorizar. ¿Descargarlo ahora o cancelar el proceso?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return False
        return self._download_vtracer_blocking()

    def _download_vtracer_blocking(self) -> bool:
        """Mismo patrón que _download_ghostscript_blocking, con download_vtracer()
        (la misma función que usa la tarjeta de Ajustes > Dependencias)."""
        progress = QProgressDialog(
            self.tr("Descargando vtracer..."), self.tr("Cancelar"), 0, 100, self,
        )
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(True)
        progress.setValue(0)

        result = {"success": False, "msg": ""}

        class _VtracerDownloadThread(QThread):
            finished_signal = Signal(bool, str)
            progress_signal = Signal(int)

            def run(self):
                success, msg = download_vtracer(progress_callback=self.progress_signal.emit)
                self.finished_signal.emit(success, msg)

        worker = _VtracerDownloadThread()
        worker.progress_signal.connect(progress.setValue)

        def _on_finished(success, msg):
            result["success"] = success
            result["msg"] = msg
            progress.close()

        worker.finished_signal.connect(_on_finished)
        worker.start()
        progress.exec()
        worker.wait()

        if not result["success"]:
            QMessageBox.warning(
                self, self.tr("Error"),
                self.tr("No se pudo descargar vtracer:\n{0}").format(result["msg"]),
            )
        return result["success"]

    def _on_convert_clicked(self):
        filepaths = self.image_queue.get_all_filepaths()
        if not filepaths or self._convert_worker is not None:
            return
        if not self._confirm_ghostscript_if_needed(filepaths):
            return
        if not self._confirm_vtracer_if_needed():
            return
        settings = {
            **self.resize_popover_content.get_settings(),
            **self.rembg_popover_content.get_settings(),
            **self.depth_popover_content.get_settings(),
            **self.normal_popover_content.get_settings(),
            **self.upscale_popover_content.get_settings(),
            **self.canvas_popover_content.get_settings(),
            **self.convert_panel.get_settings(),
            "output_folder": self.entry_output_folder.text().strip(),
            "conflict_policy": self.combo_conflict_policy.currentData() or "conservar",
        }

        # Fase 3 -- el archivo que se está mirando en este momento puede tener
        # ediciones sin "confirmar" (nunca se cambió de fila para disparar el
        # snapshot automático de _on_file_selected); se fuerza aquí para que
        # tampoco quede afuera del aplanado de abajo.
        self._snapshot_layers_for(self._current_filepath)

        titles = {fp: self.image_queue.get_title(fp) for fp in filepaths}
        source_overrides = self._build_source_overrides(filepaths)
        # Para saber, al completarse cada archivo, si ESTE lote usó IA -- ver
        # _on_convert_file_completed/_files_with_ai_edit.
        self._active_convert_settings = settings
        self._convert_worker = ImageConvertWorker(
            filepaths, settings, titles=titles, source_overrides=source_overrides, parent=self,
        )
        self._convert_worker.file_status_changed.connect(self._on_convert_file_status)
        self._convert_worker.file_progress.connect(self._on_convert_file_progress)
        self._convert_worker.busy_indeterminate.connect(self._on_convert_busy_indeterminate)
        self._convert_worker.file_depth_info.connect(self._on_convert_file_depth_info)
        self._convert_worker.file_normal_info.connect(self._on_convert_file_normal_info)
        self._convert_worker.file_completed.connect(self._on_convert_file_completed)
        self._convert_worker.file_completed.connect(
            lambda _i, _o: get_sound_notifier().item_finished(SOURCE_IMAGE_TOOLS, True))
        self._convert_worker.file_failed.connect(
            lambda _i: get_sound_notifier().item_finished(SOURCE_IMAGE_TOOLS, False))
        self._convert_worker.finished_signal.connect(self._on_convert_finished)

        self._convert_running = True
        self.btn_convert.setText(self.tr("Cancelar"))
        self.btn_convert.setProperty("variant", "danger")
        self.btn_convert.style().unpolish(self.btn_convert)
        self.btn_convert.style().polish(self.btn_convert)
        self.btn_convert.setEnabled(True)
        self.btn_convert.setToolTip(self.tr("Cancelar el proceso de conversión actual"))

        self.progress_bar.setProperty("status", "running")
        self.progress_bar.style().unpolish(self.progress_bar)
        self.progress_bar.style().polish(self.progress_bar)
        self.progress_bar.setBouncing(False)
        # Rango en PORCENTAJE del lote completo (no en "cantidad de archivos" como
        # antes) -- eso es lo que permite que la barra avance de forma continua
        # combinando "archivos ya terminados" + "progreso del archivo actual" (ver
        # _update_progress_bar), en vez de saltar de golpe entre archivos.
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self._convert_total = len(filepaths)
        self._convert_done = 0
        self._current_file_progress = 0
        self._current_stage = "loading"

        if self._convert_total == 1:
            self.progress_bar.setFormat(self.tr("Iniciando..."))
        else:
            self.progress_bar.setFormat(self.tr("Iniciando 0/{0}...").format(self._convert_total))

        self._convert_worker.start()

    def _on_convert_cancel_clicked(self):
        if self._convert_worker is not None:
            self._convert_worker.cancel()
            self.btn_convert.setEnabled(False)
            self.btn_convert.setText(self.tr("Cancelando..."))
            self.progress_bar.setFormat(self.tr("Cancelando..."))

    def _get_stage_text(self, stage: str) -> str:
        stages = {
            "loading": self.tr("Cargando"),
            "resize": self.tr("Redimensionando"),
            "rembg": self.tr("Eliminando fondo"),
            "depth": self.tr("Calculando profundidad"),
            "normals": self.tr("Calculando normales"),
            "upscale": self.tr("Reescalando con IA"),
            "canvas": self.tr("Ajustando canvas"),
            "saving": self.tr("Guardando"),
            "processing": self.tr("Procesando"),
        }
        return stages.get(stage, stage if stage else self.tr("Procesando"))

    def _update_progress_bar(self):
        """Combina archivos ya terminados + el progreso (0-100) del que está en
        curso en un único valor continuo entre 0% y 100%."""
        total = max(self._convert_total, 1)
        total_percent = (self._convert_done + self._current_file_progress / 100.0) / total * 100.0
        pct_int = int(round(total_percent))
        self.progress_bar.setValue(pct_int)

        stage_text = self._get_stage_text(getattr(self, "_current_stage", "processing"))
        current_idx = min(self._convert_done + 1, self._convert_total)

        if self._convert_total == 1:
            self.progress_bar.setFormat(f"{stage_text} ({pct_int}%)...")
        else:
            self.progress_bar.setFormat(f"{current_idx}/{self._convert_total} {stage_text} ({pct_int}%)...")

    def _on_convert_file_progress(self, filepath: str, pct: int, stage: str = "processing"):
        if stage:
            self._current_stage = stage
        self._current_file_progress = pct
        self._update_progress_bar()

    def _on_convert_busy_indeterminate(self, filepath: str, is_indeterminate: bool, stage: str = "processing"):
        self.progress_bar.setBouncing(is_indeterminate)
        if stage:
            self._current_stage = stage
        if is_indeterminate:
            stage_text = self._get_stage_text(self._current_stage)
            current_idx = min(self._convert_done + 1, self._convert_total)
            if self._convert_total == 1:
                self.progress_bar.setFormat(f"{stage_text}...")
            else:
                self.progress_bar.setFormat(f"{current_idx}/{self._convert_total} {stage_text}...")
        else:
            self._update_progress_bar()

    def _on_convert_file_status(self, filepath: str, status_text: str):
        self.image_queue.update_file_status(filepath, status_text)
        # "Procesando..." indica que el archivo acaba de EMPEZAR, no que terminó.
        if status_text in (self.tr("Procesando..."), "Procesando..."):
            self._current_stage = "loading"
            return
        self._convert_done += 1
        self._current_file_progress = 0
        self.progress_bar.setBouncing(False)
        self._update_progress_bar()

    def _on_convert_file_depth_info(self, input_path: str, width: int, height: int):
        self._pending_depth_sizes[input_path] = (width, height, "depth")

    def _on_convert_file_normal_info(self, input_path: str, width: int, height: int):
        self._pending_depth_sizes[input_path] = (width, height, "normals")

    def _on_convert_file_completed(self, input_path: str, output_path: str):
        """Registra el resultado de una conversión exitosa -- a propósito NO
        interrumpe una edición en curso (como en Photoshop), EXCEPTO cuando el
        lote usó IA (Reescalar y/o Eliminar Fondo, ver rembg_engine.py): ahí si
        el usuario está mirando justo esta fila, Comparar se activa solo para
        mostrar el resultado de una vez. Invalida el cache de comparación por si
        ya había un resultado previo de una reconversión."""
        self.image_queue.set_output_path(input_path, output_path)
        self._compare_cache.invalidate(input_path)
        settings = self._active_convert_settings or {}
        uses_ai = bool(settings.get("upscale_enabled") or settings.get("rembg_enabled")
                       or settings.get("depth_enabled") or settings.get("normals_enabled"))
        self._files_with_ai_edit[input_path] = uses_ai

        # La nota "calculado" solo aplica si el mapa (de profundidad o de normales) ES
        # el resultado: con otro paso de tamaño o de IA encima, el tamaño final ya no
        # depende solo del cálculo del mapa.
        depth_size = self._pending_depth_sizes.pop(input_path, None)
        depth_only = bool(settings.get("depth_enabled") or settings.get("normals_enabled")) and not any(
            settings.get(key) for key in ("rembg_enabled", "upscale_enabled", "resize_enabled", "canvas_enabled"))
        if depth_size and depth_only:
            self._depth_process_sizes[input_path] = depth_size
        else:
            self._depth_process_sizes.pop(input_path, None)
        
        # Enviar al editor si corresponde
        from core.services.editor_integration_manager import EditorIntegrationManager
        editor_mgr = EditorIntegrationManager.get_instance()
        if editor_mgr and editor_mgr.is_auto_send_enabled:
            editor_mgr.process_raw_download(output_path, {})
            
        if input_path != self._current_filepath:
            return
        self._refresh_title_and_copy_button(input_path)
        if uses_ai:
            self.btn_compare_result.blockSignals(True)
            self.btn_compare_result.setChecked(True)
            self.btn_compare_result.blockSignals(False)
            self._show_compare_view(input_path)

    def _on_convert_finished(self, completed: int, total: int):
        worker = self._convert_worker
        if worker is not None and worker.cancellation_event.is_set():
            get_sound_notifier().discard(SOURCE_IMAGE_TOOLS)
        else:
            get_sound_notifier().group_finished(SOURCE_IMAGE_TOOLS)
        if self._flatten_temp_dir is not None:
            shutil.rmtree(self._flatten_temp_dir, ignore_errors=True)
            self._flatten_temp_dir = None
        self._convert_worker = None
        self._convert_running = False
        self.btn_convert.setText(self.tr("Iniciar Proceso"))
        self.btn_convert.setProperty("variant", "primary")
        self.btn_convert.style().unpolish(self.btn_convert)
        self.btn_convert.style().polish(self.btn_convert)
        self.progress_bar.setBouncing(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.progress_bar.setProperty("status", "done")
        self.progress_bar.style().unpolish(self.progress_bar)
        self.progress_bar.style().polish(self.progress_bar)
        self.progress_bar.setFormat(self.tr("Completado: {0}/{1} archivos").format(completed, total))
        self._update_convert_button_state()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Síncrono a propósito: se probó diferir esto con QTimer.singleShot(0), pero
        # como el resize ya repinta con el tamaño nuevo antes de que corra el timer, se
        # veía un frame con el panel lateral (Capas) todavía en el modo/ancho viejo
        # (parpadeo visible) antes de corregirse. El freeze real al maximizar no era
        # este cálculo en sí, sino el setStyleSheet() en cascada que CollapsiblePanel
        # hacía en cada cambio de modo (ver collapsible_panel.py) -- ya reemplazado por
        # setProperty()+polish(), mucho más barato -- así que correrlo síncrono aquí ya
        # no bloquea perceptiblemente y evita el parpadeo.
        self._update_responsive_mode()

    def minimumSizeHint(self):
        """Se sobrescribe para SIEMPRE reportar el piso "sin panel derecho acoplado"
        (mismo criterio y mismo motivo que VideoToolsTab.minimumSizeHint()): si no lo
        hiciéramos, Qt propagaría el piso "acoplado" (más ancho, por el ancho fijo de
        right_panel) como mínimo de toda la ventana, y un resize() de un solo salto
        grande->chico quedaría atascado sin llegar a disparar el colapso a overlay.
        TOOLBAR_WIDTH sí se suma siempre -- a diferencia de right_panel, la barra de
        herramientas nunca colapsa/sale del layout."""
        base = super().minimumSizeHint()
        if not hasattr(self, "preview"):
            return base
        width = self._toolbar_width() + self.preview.minimumSizeHint().width()
        return QSize(width, base.height())

    def _toolbar_width(self):
        """Ancho real de la barra lateral: TOOLBAR_WIDTH en una columna, más en dos."""
        rail = getattr(self, "side_toolbar", None)
        return rail.current_width() if rail is not None else self.TOOLBAR_WIDTH

    def _on_side_toolbar_layout_changed(self):
        # Los botones pudieron moverse (compacto / dos columnas): los popovers abiertos
        # están anclados a ellos y tienen que seguirlos.
        for btn in getattr(self, "_popover_buttons", []):
            if btn.is_open():
                btn.reposition()

    LAYOUT_CONFIG_KEY = "image_tools_layout"

    def _apply_layout_sizes(self):
        """Ancho guardado del panel derecho (o el por defecto); la vista previa se queda
        con el resto. Solo aplica con el panel acoplado (en overlay no está en el separador)."""
        if self.body_splitter.count() < 2:
            return
        total = sum(self.body_splitter.sizes())
        if total <= 0:
            return
        panel = int((get_config().get(self.LAYOUT_CONFIG_KEY) or {}).get("panel", self.RIGHT_DOCKED_WIDTH))
        self.body_splitter.setSizes([max(1, total - panel), panel])

    def _save_layout_sizes(self):
        sizes = self.body_splitter.sizes()
        if len(sizes) == 2 and sizes[1] > 0:
            config = get_config()
            config[self.LAYOUT_CONFIG_KEY] = {"panel": sizes[1]}
            save_config(config)

    def _reset_layout(self):
        """Doble clic en el separador: panel derecho a su ancho por defecto."""
        config = get_config()
        config.pop(self.LAYOUT_CONFIG_KEY, None)
        save_config(config)
        self._apply_layout_sizes()

    def _update_responsive_mode(self):
        if not hasattr(self, "right_panel"):
            return
        threshold = max(self.COLLAPSE_THRESHOLD_WIDTH, self._toolbar_width() + self.RIGHT_DOCKED_WIDTH + self.PREVIEW_MIN_WIDTH)
        want_docked = self.width() >= threshold
        if want_docked != self.right_panel.is_docked():
            self.right_panel.set_mode(docked=want_docked)
            if want_docked:
                # Volvió al separador: reponer el ancho que el usuario le había dado.
                QTimer.singleShot(0, self._apply_layout_sizes)
        self.right_panel.sync_overlay_geometry()
        for btn in getattr(self, "_popover_buttons", []):
            if btn.is_open():
                btn.reposition()
        if hasattr(self, "layers_floating_panel") and self.layers_floating_panel.isVisible():
            self.layers_floating_panel.clamp_to_host()

    def receive_media_from_editor(self, items: list) -> int:
        """Agrega imagenes enviadas desde el editor con "Enviar a DowP". Aqui no hay
        recorte que aplicar (ver receive_media_from_editor en Herramientas Multimedia),
        asi que se deduplican como cualquier archivo agregado a mano."""
        paths = []
        for item in items or []:
            path = item.get("path")
            if not path or not os.path.exists(path):
                logger.warning(f"ImageToolsTab: El editor mando un archivo que no existe: {path}")
                continue
            paths.append(path)
        if not paths:
            return 0
        before = len(self.image_queue.get_all_filepaths()) if hasattr(self.image_queue, "get_all_filepaths") else 0
        self.image_queue.add_files(paths)
        after = len(self.image_queue.get_all_filepaths()) if hasattr(self.image_queue, "get_all_filepaths") else before + len(paths)
        return max(0, after - before)

    def showEvent(self, event):
        super().showEvent(event)
        from core.utils.config_manager import get_config, save_config
        config = get_config()
        if not config.get("tutorial_image_tools_seen", False):
            # Usar QTimer para permitir que la UI se renderice antes de mostrar el tutorial
            QTimer.singleShot(500, self.start_tutorial)
            config["tutorial_image_tools_seen"] = True
            save_config(config)

    def start_tutorial(self):
        from gui.widgets.tutorial_overlay import TutorialOverlay
        steps = [
            {
                "title": self.tr("Reescalado con Inteligencia Artificial"),
                "desc": self.tr("Aumenta la resolución y calidad de tus imágenes utilizando modelos de IA ncnn."),
                "widgets": [self.btn_upscale],
                "on_enter": lambda: self.btn_upscale.set_open(True)
            },
            {
                "title": self.tr("Quitar Fondo"),
                "desc": self.tr("Elimina automáticamente el fondo de cualquier imagen. Tienes diferentes modelos IA pesados para objetos, ropa o siluetas."),
                "widgets": [self.btn_rembg],
                "on_enter": lambda: self.btn_rembg.set_open(True)
            },
            {
                "title": self.tr("Mapa de Profundidad"),
                "desc": self.tr("Genera un mapa en escala de grises con la distancia de cada zona de la imagen (lo cercano en blanco). Sirve para efectos de desenfoque, niebla o desplazamiento en DaVinci Resolve o Blender."),
                "widgets": [self.btn_depth],
                "on_enter": lambda: self.btn_depth.set_open(True)
            },
            {
                "title": self.tr("Mapa de Normales"),
                "desc": self.tr("Genera un normal map: de una foto o escena con MoGe-2, o de una textura plana para materiales 3D con DeepBump. Sirve para relighting en DaVinci Resolve o para texturas en Blender. Si activas esta herramienta se apaga el Mapa de Profundidad."),
                "widgets": [self.btn_normals],
                "on_enter": lambda: self.btn_normals.set_open(True)
            },
            {
                "title": self.tr("Redimensionar"),
                "desc": self.tr("Cambia el tamaño de la imagen por porcentaje o píxeles. ¡Especialmente bueno y sin pérdida al trabajar con imágenes vectoriales!"),
                "widgets": [self.btn_resize],
                "on_enter": lambda: self.btn_resize.set_open(True)
            },
            {
                "title": self.tr("Control de Lienzo"),
                "desc": self.tr("Ajusta los márgenes o recorta la imagen libremente para adaptarla al formato que necesites."),
                "widgets": [self.btn_canvas],
                "on_enter": lambda: self.btn_canvas.set_open(True)
            },
            {
                "title": self.tr("Panel de Capas y Dibujo"),
                "desc": self.tr("Aquí puedes gestionar todas las formas, dibujos y fondos que añadas a tu imagen. Veamos sus opciones."),
                "widgets": [self.btn_layers_panel],
                "on_enter": lambda: self.btn_layers_panel.setChecked(True)
            },
            {
                "title": self.tr("Borrador"),
                "desc": self.tr("Marca en Capas la capa que quieres borrar y pasa el borrador por encima. Las formas y los fondos se convierten en píxeles para poder borrarlos. La imagen original nunca se modifica."),
                "widgets": [self._tool_buttons["eraser"]],
            },
            {
                "title": self.tr("Opciones de Dibujo"),
                "desc": self.tr("Haz clic derecho en Rectángulo, Elipse, Línea o Pincel para elegir colores, quitar el relleno o el borde y ajustar el grosor. Si tienes una forma seleccionada, los cambios también se aplican a ella."),
                "widgets": [self._tool_buttons[k] for k in ("rect", "ellipse", "line", "brush")],
            },
            {
                "title": self.tr("Añadir Fondo"),
                "desc": self.tr("Si eliminaste el fondo original o tienes una imagen transparente, usa este botón para colocar un fondo de color sólido detrás de todo."),
                "widgets": [self.layers_panel.btn_add_background],
            },
            {
                "title": self.tr("Vista Previa y Título"),
                "desc": self.tr("Aquí puedes ver los cambios en tiempo real y renombrar el archivo final. Puedes usar el botón 'Comparar' para ver el antes y el después."),
                "widgets": [self.entry_title, self.preview],
                "on_enter": lambda: self.btn_layers_panel.setChecked(False) # Cerramos el panel de capas para ver mejor
            },
            {
                "title": self.tr("Copiar Resultado"),
                "desc": self.tr("¡Si necesitas la imagen ya procesada para usarla rápido en otro programa, simplemente cópiala desde aquí!"),
                "widgets": [self.btn_copy_result],
            },
            {
                "title": self.tr("Cola de Procesamiento y Pegado"),
                "desc": self.tr("Arrastra varias imágenes para procesarlas en lote. También puedes usar el botón 'Pegar' para importar directamente imágenes desde tu portapapeles."),
                "widgets": [self.image_queue, self.image_queue.btn_paste],
                "on_enter": lambda: self.right_panel.open_overlay() if not self.right_panel.is_docked() and not self.right_panel.is_overlay_open() else None
            },
            {
                "title": self.tr("Formato y Calidad"),
                "desc": self.tr("Define en qué formato quieres guardar tus resultados, su calidad y cualquier otro ajuste final."),
                "widgets": [self.convert_panel],
                "on_enter": lambda: self.right_panel.open_overlay() if not self.right_panel.is_docked() and not self.right_panel.is_overlay_open() else None
            },
            {
                "title": self.tr("Exportación"),
                "desc": self.tr("Elige la carpeta de destino, la regla para archivos duplicados y haz clic en 'Convertir' para procesar todo el lote."),
                "widgets": [self.output_bar],
                "on_enter": lambda: self.right_panel.open_overlay() if not self.right_panel.is_docked() and not self.right_panel.is_overlay_open() else None
            }
        ]
        
        main_window = self.window()
        self.tutorial_overlay = TutorialOverlay(main_window, steps)
        self.tutorial_overlay.resize(main_window.size())
        self.tutorial_overlay.show()
