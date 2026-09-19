# src/gui/tabs/video_tools/video_tools_view.py
import os
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QFrame,
    QMessageBox,
    QCheckBox,
    QProgressDialog,
)
from PySide6.QtCore import Qt, QSize, QUrl, QTimer, QThread, Signal
from PySide6.QtGui import QIcon, QDesktopServices

from gui.widgets.animated_button import AnimatedButton
from gui.widgets.bouncing_progress_bar import BouncingProgressBar
from gui.widgets.combo_box import AutoPopupComboBox
from gui.widgets.collapsible_panel import CollapsiblePanel
from gui.styles import apply_folder_browse_button_style, apply_folder_open_button_style, create_colored_circle_icon, update_label_combobox_style
from gui.widgets.media_trim_player_widget import MediaTrimPlayerWidget
from gui.tabs.video_tools.media_queue_widget import MediaQueueWidget, entry_path
from gui.tabs.video_tools.encoding_options_widget import EncodingOptionsWidget
from core.logger.logger_manager import logger
from core.utils.config_manager import get_config, save_config
from core.tabs.editing_media.ffprobe_metadata_manager import FFprobeMetadataManager
from core.utils.queue_manager import get_queue_manager, JobStatus
from core.utils.file_conflict_manager import resolve_conflict, commit_backup, rollback_backup, find_available_rename
from core.utils.recode_guard import container_supports_multi_audio, CONTAINER_TO_EXTENSION

AUDIO_ONLY_EXTENSIONS = {".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a", ".opus", ".wma", ".adts", ".dts", ".thd", ".mlp", ".mpc", ".w64", ".shn"}


class _QueueMetadataThread(QThread):
    """Recalcula la metadata agregada de TODA la cola (ver
    VideoToolsTab._on_queue_changed) en un hilo de fondo. get_metadata_instant()
    es "instantánea" por archivo (0ms, ver su docstring), pero sumada a miles de
    archivos -- un os.path.exists()+os.stat()+lock por cada uno, en un loop
    síncrono -- alcanza a notarse igual en el hilo de UI en una importación
    grande, sobre todo si el disco es lento o hay un antivirus interceptando
    cada apertura de archivo."""
    finished_computing = Signal(list, list)  # entries, entries_with_paths

    def __init__(self, filepaths: list[str], parent=None):
        super().__init__(parent)
        self._filepaths = filepaths

    def run(self):
        entries = []
        entries_with_paths = []
        mgr = FFprobeMetadataManager.get_instance()
        for filepath in self._filepaths:
            ext = os.path.splitext(filepath)[1].lower()
            media_type = "audio" if ext in AUDIO_ONLY_EXTENSIONS else "video"
            meta = mgr.get_metadata_instant(filepath, media_type)
            entries.append(meta)
            entries_with_paths.append((filepath, meta))
        self.finished_computing.emit(entries, entries_with_paths)


class VideoToolsTab(QWidget):
    """
    Pestaña de Herramientas Multimedia / Recodificador (Diseño de 2 Columnas Unificadas).
    Organiza la interfaz en 2 paneles principales:
      - Columna Izquierda: Vista Previa Multimedia (arriba) + Cola de Medios Importados (abajo).
      - Columna Derecha: Panel de Opciones con Pestañas (Preajustes/Comprimir/Convertir/Proxies/Avanzado) + Cubo de Salida e Iniciar.

    Layout tipo Premiere: cola de medios (izq) | preview centrado (centro) | opciones (der)
    en una fila superior, y timeline/waveform + salida en una fila inferior SIEMPRE visible.
    La cola de medios queda siempre acoplada (ancho fijo, cabe bien incluso en el ancho
    mínimo soportado). Solo el panel de Opciones colapsa a un overlay flotante en ventanas
    angostas (ver CollapsiblePanel) que no empuja ni redimensiona el preview ni la fila
    inferior.
    """

    COLLAPSE_THRESHOLD_WIDTH = 900
    QUEUE_WIDTH = 340
    # 300px probaba limpio con la cola vacía, pero con contenido real (mensajes de estado
    # más largos, nombres de archivo, etc.) el panel podía terminar por debajo del ancho
    # real que necesita el acordeón de Opciones — apareciendo el scroll horizontal de
    # seguridad justo antes de colapsar a overlay. 500px es el valor que ya habíamos
    # verificado sin recortes ni scroll con la pestaña Avanzado expandida.
    OPTIONS_DOCKED_WIDTH = 500
    # Ancho del panel de Opciones cuando aparece como overlay (ventana angosta): al menos
    # tan generoso como el acoplado, para no repetir el mismo problema ahí.
    OPTIONS_OVERLAY_MAX_WIDTH = 520
    PREVIEW_MIN_WIDTH = 600
    PREVIEW_MAX_WIDTH_RATIO = 0.35
    # 294px (su mínimo técnico) se veía apretado en la práctica (campos truncados) — igual
    # que con Opciones, un mínimo "cómodo" real en vez de dejar que el stretch lo deje en
    # el piso técnico por defecto.
    OUTPUT_CARD_MIN_WIDTH = 380
    OUTPUT_CARD_MAX_WIDTH_RATIO = 0.35
    # Techo de seguridad para cola/opciones, no un objetivo: el reparto real lo hace el
    # stretch (1:3:1) de top_row_layout, que ya consume el 100% del espacio disponible.
    # Este valor solo evita un ancho absurdo en monitores ultra-anchos (>2560px); a
    # resoluciones normales/maximizadas nunca debería ser lo que los limita.
    SIDE_PANEL_MAX_WIDTH_CAP = 900

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_preview_file = ""
        self.in_point_ms = 0
        self.out_point_ms = 0
        self._recode_jobs = set()  # Mantener track de los trabajos RECODE iniciados desde esta vista
        # Recorte temporal (trim) por archivo: {filepath: (in_sec, out_sec)}. A diferencia
        # del recorte espacial (crop, exclusivo del archivo en preview salvo "Aplicar a
        # todos"), el trim ahora sobrevive a cambiar de archivo en el preview - se guarda
        # aquí en cada range_changed y se restaura al volver a seleccionar ese archivo (ver
        # _on_trim_range_changed / _on_file_selected), y se usa por-archivo al armar el
        # lote (ver _on_start_recoding_clicked), no solo para el que esté en preview.
        self._trim_cache: dict[str, tuple[float, float]] = {}
        # Selección de pista de audio (medios multipista) por archivo: {filepath: "all"|int}.
        # Misma arquitectura que _trim_cache y por el mismo motivo - antes se leía en vivo
        # del preview_widget incluso para archivos que no eran el actual, lo que podía
        # aplicarle a un archivo la pista elegida en OTRO (ver conversación).
        self._audio_track_cache: dict[str, str | int] = {}
        # Cálculo de metadata agregada de la cola (ver _on_queue_changed) -- corre en
        # un hilo aparte; request_id descarta el resultado si ya quedó obsoleto por
        # un cambio de cola más nuevo mientras el hilo anterior seguía corriendo.
        self._queue_meta_thread = None
        self._queue_meta_request_id = 0
        # job_id -> backup_path pendiente (o None) para la política "Sobrescribir" - ver
        # file_conflict_manager.py: se confirma (se borra el .dbak) si el job termina bien,
        # se revierte (se restaura el original) si falla o se cancela.
        self._recode_backups: dict[str, str | None] = {}
        # job_id -> nota de advertencia (o ausente si no hubo ninguna) para trabajos que
        # terminan bien pero con una salvedad - ej. se forzó una sola pista de audio
        # porque el contenedor/códec de salida no admite multipista (ver
        # container_supports_multi_audio) y el usuario no eligió una pista a mano. Vive
        # aquí (no en el Job de queue_manager.py) porque es pura anotación de UI para esta
        # pestaña - no cambia el comando de ffmpeg ni le interesa a Descargas/Playlists.
        self._recode_job_notes: dict[str, str] = {}
        # Reescalado IA + Recodificación combinados (ver
        # _start_chained_jobs/_on_job_status): job_id de la etapa de
        # reescalado -> datos para armar la etapa de recodificación que sigue
        # cuando esa primera etapa termine bien.
        self._chain_pending: dict[str, dict] = {}
        # job_id de la etapa de recodificación (la segunda) -> ruta del
        # archivo intermedio a borrar cuando ESA etapa termine, sea cual sea
        # el resultado -- el intermedio nunca es el archivo final, no tiene
        # sentido conservarlo pase lo que pase.
        self._chain_cleanup: dict[str, str] = {}
        # Carpeta temporal para los archivos intermedios de la etapa de
        # reescalado en una cadena -- creada la primera vez que hace falta,
        # barrida en _check_all_finished() cuando ya no queda nada corriendo
        # (mismo criterio que _flatten_temp_dir en image_tools_view.py).
        self._chain_temp_dir: str | None = None

        self.init_ui()
        # Acepta arrastrar archivos desde fuera de la app (o desde otra pestaña de
        # DowP) en TODA la pestaña -- vista previa, waveform, timeline, etc. -- no
        # solo sobre la cola. Qt solo entrega eventos de drag al widget exacto bajo
        # el cursor que acepte drops, no los sube solo a los ancestros con
        # setAcceptDrops(True) -- por eso no basta con activarlo aquí y ya (ver
        # WholeAreaDropForwarder). Se excluye self.queue_widget porque ya maneja
        # sus propios drops correctamente (incluye carpetas vía _start_scan).
        from gui.widgets.drop_forwarder import WholeAreaDropForwarder
        self._drop_forwarder = WholeAreaDropForwarder(
            self, lambda paths: self.queue_widget._start_scan(paths), exclude=[self.queue_widget]
        )
        self._load_saved_output_dir()
        self.load_labels()
        FFprobeMetadataManager.get_instance().metadata_ready.connect(self._on_metadata_ready)
        
        # Conectar señales del QueueManager
        qm = get_queue_manager()
        qm.job_progress_changed.connect(self._on_job_progress)
        qm.job_status_changed.connect(self._on_job_status)

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # -------------------------------------------------------------
        # FILA SUPERIOR: Cola de Medios (izq) | Preview centrado (centro) | Opciones (der)
        # Izquierda y derecha colapsan a overlay en ventanas angostas; ver
        # _update_responsive_mode / CollapsiblePanel.
        # -------------------------------------------------------------
        self.top_row = QWidget()
        self.top_row_layout = QHBoxLayout(self.top_row)
        self.top_row_layout.setContentsMargins(0, 0, 0, 0)
        self.top_row_layout.setSpacing(8)

        self.preview_widget = MediaTrimPlayerWidget(self, card_style=True)
        self.preview_widget.range_changed.connect(self._on_trim_range_changed)
        self.preview_widget.audio_track_selection_changed.connect(self._on_audio_track_selection_changed)
        # El tope de ancho se recalcula en vivo según el ancho de ventana (ver
        # _preview_max_width) en vez de ser un número fijo: así el preview queda chico y
        # centrado en la resolución default, pero aprovecha el espacio extra en pantallas
        # grandes en vez de dejarlo como hueco muerto a los costados.

        # La waveform/regla/vúmetro + barra de controles se extraen del preview para vivir
        # en la fila inferior, siempre visible a todo el ancho (ver bottom_row más abajo).
        self.timeline_widget = self.preview_widget.extract_timeline_container()

        self.queue_widget = MediaQueueWidget(self)
        self.queue_widget.file_selected.connect(self._on_file_selected)
        self.queue_widget.queue_updated.connect(self._on_queue_changed)

        # 1. Panel de Opciones con Pestañas
        self.options_widget = EncodingOptionsWidget(self)
        self.options_widget.start_status_changed.connect(self._on_start_status_changed)

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

        # -------------------------------------------------------------
        # FILA INFERIOR: Timeline/Waveform + Cubo de Salida — SIEMPRE visible, nunca colapsa
        # -------------------------------------------------------------
        self.bottom_row = QWidget()
        bottom_row_layout = QHBoxLayout(self.bottom_row)
        bottom_row_layout.setContentsMargins(0, 0, 0, 0)
        bottom_row_layout.setSpacing(8)

        # Cubo de Opciones de Salida y Ejecución
        self.output_card = QFrame(self.bottom_row)
        self.output_card.setObjectName("outputOptionsContainer")
        self.output_card.setMinimumWidth(self.OUTPUT_CARD_MIN_WIDTH)
        out_layout = QVBoxLayout(self.output_card)
        out_layout.setContentsMargins(14, 12, 14, 12)
        out_layout.setSpacing(10)

        lbl_out_title = QLabel(self.tr("Opciones de Salida"), self.output_card)
        lbl_out_title.setObjectName("sectionTitle")
        lbl_out_title.setAlignment(Qt.AlignCenter)
        out_layout.addWidget(lbl_out_title)

        grid_out = QGridLayout()
        grid_out.setSpacing(8)
        grid_out.setColumnStretch(1, 1)

        # Fila 0: Checkbox "Guardar junto al original" + política de conflicto de nombres
        # (acortado el texto del checkbox a propósito para que entre el combo al lado,
        # ver conversación: antes decía "Guardar en la misma ruta del medio original").
        row_same_path = QHBoxLayout()
        row_same_path.setContentsMargins(0, 0, 0, 0)
        row_same_path.setSpacing(6)

        self.chk_same_path = QCheckBox(self.tr("Guardar junto al original"), self.output_card)
        self.chk_same_path.setObjectName("menuLabel")
        row_same_path.addWidget(self.chk_same_path)
        row_same_path.addStretch(1)

        lbl_conflict_policy = QLabel(self.tr("Si existe:"), self.output_card)
        lbl_conflict_policy.setObjectName("menuLabel")
        row_same_path.addWidget(lbl_conflict_policy)

        # Mismas 3 políticas y mismo criterio que ya usa la pestaña de Descarga
        # (gui/tabs/single_process/output_options.py) - reusan directo
        # core/utils/file_conflict_manager.py (backup reversible al sobrescribir), no
        # una lógica nueva.
        self.combo_conflict_policy = AutoPopupComboBox(self.output_card)
        self.combo_conflict_policy.setCursor(Qt.PointingHandCursor)
        self.combo_conflict_policy.addItem(self.tr("Sobrescribir"), "sobrescribir")
        self.combo_conflict_policy.addItem(self.tr("Conservar"), "conservar")
        self.combo_conflict_policy.addItem(self.tr("Omitir"), "omitir")
        self.combo_conflict_policy.setCurrentIndex(1)  # "Conservar" por defecto
        self.combo_conflict_policy.setFixedHeight(28)
        self.combo_conflict_policy.setToolTip(self.tr(
            "Qué hacer si ya existe un archivo con el mismo nombre de salida:\n"
            "• Sobrescribir: reemplaza el archivo antiguo (con respaldo reversible).\n"
            "• Conservar: guarda el nuevo archivo como 'nombre (1).ext'.\n"
            "• Omitir: no recodifica ese archivo."
        ))
        self.combo_conflict_policy.currentIndexChanged.connect(self._on_conflict_policy_changed)
        row_same_path.addWidget(self.combo_conflict_policy)

        grid_out.addLayout(row_same_path, 0, 0, 1, 3)

        # Fila 1: Ruta + Selector de Etiquetas + Botones de Examinar/Abrir
        self.lbl_dest = QLabel(self.tr("Ruta:"), self.output_card)
        self.lbl_dest.setObjectName("menuLabel")
        grid_out.addWidget(self.lbl_dest, 1, 0)

        path_row = QHBoxLayout()
        path_row.setSpacing(6)
        path_row.setContentsMargins(0, 0, 0, 0)

        self.txt_output_dir = QLineEdit(self.output_card)
        self.txt_output_dir.setPlaceholderText(self.tr("Seleccionar carpeta de destino..."))
        path_row.addWidget(self.txt_output_dir, 1)

        # ComboBox de Etiquetas
        self.combo_tags = AutoPopupComboBox(self.output_card)
        self.combo_tags.setObjectName("tagsComboBox")
        self.combo_tags.setPlaceholderText(self.tr("Etiqueta"))
        # Se construye con el parent directo al constructor, lo que hace que el ChildAdded del
        # filtro global de cursor (HandCursorInstaller, main.py) nunca se dispare (ver
        # advanced_recode_panel.py::_setup_fixed_combo) — se fija a mano aquí.
        self.combo_tags.setCursor(Qt.PointingHandCursor)
        self.combo_tags.currentIndexChanged.connect(self._on_label_changed)

        # Botón para examinar carpeta
        self.btn_browse_output = QPushButton(self.output_card)
        self.btn_browse_output.setFixedSize(32, 32)
        self.btn_browse_output.setCursor(Qt.PointingHandCursor)
        apply_folder_browse_button_style(self.btn_browse_output, self.tr("Seleccionar carpeta de salida"))
        self.btn_browse_output.clicked.connect(self._on_browse_output_clicked)
        
        # Botón para abrir la carpeta
        self.btn_open_output = QPushButton(self.output_card)
        self.btn_open_output.setFixedSize(32, 32)
        self.btn_open_output.setCursor(Qt.PointingHandCursor)
        apply_folder_open_button_style(self.btn_open_output, self.tr("Abrir carpeta de salida en el explorador"))
        self.btn_open_output.clicked.connect(self._on_open_output_clicked)

        path_row.addWidget(self.btn_browse_output)
        path_row.addWidget(self.btn_open_output)
        path_row.addWidget(self.combo_tags)

        grid_out.addLayout(path_row, 1, 1, 1, 2)

        # Fila 2: Prefijo y Sufijo
        self.lbl_prefix = QLabel(self.tr("Prefijo:"), self.output_card)
        self.lbl_prefix.setObjectName("menuLabel")
        grid_out.addWidget(self.lbl_prefix, 2, 0)

        affixes_row = QHBoxLayout()
        affixes_row.setSpacing(10)
        affixes_row.setContentsMargins(0, 0, 0, 0)

        self.txt_prefix = QLineEdit(self.output_card)
        self.txt_prefix.setPlaceholderText("")

        self.lbl_suffix = QLabel(self.tr("Sufijo:"), self.output_card)
        self.lbl_suffix.setObjectName("menuLabel")
        self.txt_suffix = QLineEdit("_recoded", self.output_card)

        affixes_row.addWidget(self.txt_prefix, 1)
        affixes_row.addWidget(self.lbl_suffix)
        affixes_row.addWidget(self.txt_suffix, 1)

        grid_out.addLayout(affixes_row, 2, 1, 1, 2)
        
        self.chk_same_path.toggled.connect(self._on_same_path_toggled)

        out_layout.addLayout(grid_out)

        # Barra de Progreso Global
        self.progress_bar = BouncingProgressBar(self.output_card)
        self.progress_bar.setObjectName("downloadProgressBar")
        self.progress_bar.setProperty("status", "wait")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(self.tr("En espera"))
        self.progress_bar.setTextVisible(True)
        out_layout.addWidget(self.progress_bar)

        # Botón Acción Principal: un solo botón que cambia de rol — "Iniciar
        # Recodificación" mientras no hay nada corriendo, "Cancelar" mientras hay un
        # lote en curso (mismo botón, no dos aparte — ver _set_start_button_running).
        self._batch_active = False
        self.btn_start = AnimatedButton(self.tr("Iniciar Recodificación"), self.output_card)
        self.btn_start.setProperty("variant", "primary")
        self.btn_start.setObjectName("downloadButton")
        self.btn_start.setFixedHeight(36)
        self.btn_start.clicked.connect(self._on_start_button_clicked)
        out_layout.addWidget(self.btn_start)

        # Estado y texto inicial contextual del botón
        self._on_start_status_changed(*self.options_widget.get_current_status())

        bottom_row_layout.addWidget(self.output_card, 1)
        bottom_row_layout.addWidget(self.timeline_widget, 2)

        # -------------------------------------------------------------
        # Cola de medios (izq): SIEMPRE visible/acoplada, cabe bien incluso en el ancho
        # mínimo de la app, así que no necesita colapsar a overlay.
        # Opciones (der): único panel colapsable, se oculta a overlay en ventanas angostas.
        # -------------------------------------------------------------
        # Ancho "preferido" (arranque) fijo vía minimumWidth; el techo real de crecimiento
        # (más allá de este valor cuando sobra espacio) lo pone _update_responsive_mode.
        self.queue_widget.setMinimumWidth(self.QUEUE_WIDTH)
        self.right_panel = CollapsiblePanel(
            self.options_widget, edge="right",
            docked_size=self.OPTIONS_DOCKED_WIDTH,
            overlay_max_width=self.OPTIONS_OVERLAY_MAX_WIDTH,
        )

        self.preview_center_wrapper = QWidget()
        center_layout = QHBoxLayout(self.preview_center_wrapper)
        center_layout.setContentsMargins(0, 0, 0, 0)
        # El preview debe crecer primero hasta su propio tope (setMaximumWidth) y sólo
        # repartirse el espacio sobrante entre los dos stretch de los costados para quedar
        # centrado — si los tres tuvieran el mismo peso, Qt reparte el espacio extra por
        # igual entre los 3 y el preview queda mucho más chico que su tope, dejando huecos
        # enormes a los lados en vez de "chico y centrado".
        center_layout.addStretch(1)
        center_layout.addWidget(self.preview_widget, 1000)
        center_layout.addStretch(1)

        # Pesos de stretch: el preview se lleva la mayor parte del espacio sobrante; entre
        # los paneles laterales, Opciones tiene prioridad sobre la cola de medios (crece
        # más) porque sus controles se benefician más del ancho extra que una lista simple
        # de archivos — ninguno se queda 100% fijo, para no dejar hueco muerto a los
        # costados en ventanas grandes/maximizadas.
        self.top_row_layout.addWidget(self.queue_widget, 1)
        self.top_row_layout.addWidget(self.preview_center_wrapper, 3)
        self.top_row_layout.addWidget(self.right_panel, 2)

        # El host del overlay es la pestaña completa (self), no self.top_row: Qt recorta
        # los hijos al área de su padre, así que si quedara colgado de top_row jamás podría
        # pintarse por encima de bottom_row. Al no empujar ni redimensionar nada (es un
        # overlay flotante), no hay problema en que use toda la altura disponible.
        self.right_panel.configure_container(self, self.top_row_layout, 2, dock_stretch=2)

        main_layout.addWidget(self.top_row, 1)
        main_layout.addWidget(self.bottom_row)

        # El tamaño real de la ventana no es confiable hasta que el layout se asiente;
        # se evalúa una vez apenas se procese el primer ciclo de eventos.
        QTimer.singleShot(0, self._update_responsive_mode)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Síncrono a propósito: se probó diferir esto con QTimer.singleShot(0), pero
        # como el resize ya repinta con el tamaño nuevo antes de que corra el timer, se
        # veía un frame con el panel lateral (Opciones) todavía en el modo/ancho viejo
        # (parpadeo visible) antes de corregirse. El freeze real al maximizar no era
        # este cálculo en sí, sino el setStyleSheet() en cascada que CollapsiblePanel
        # hacía en cada cambio de modo (ver collapsible_panel.py) -- ya reemplazado por
        # setProperty()+polish(), mucho más barato -- así que correrlo síncrono aquí ya
        # no bloquea perceptiblemente y evita el parpadeo.
        self._update_responsive_mode()

    def minimumSizeHint(self):
        """Se sobrescribe para SIEMPRE reportar el piso "sin panel de opciones acoplado"
        (el que rige en modo overlay), nunca el piso más ancho que exige el panel de
        Opciones cuando está acoplado (docked_size es un mínimo duro real — ver
        CollapsiblePanel — para que nunca aparezca recortado/con scroll horizontal).

        Si no hiciéramos esto, Qt propagaría el piso "acoplado" (más ancho) hacia arriba
        como mínimo de toda la ventana, y un resize() de un solo salto grande→chico
        quedaría atascado sin llegar a disparar el colapso a overlay (el mismo bloqueo que
        ya solucionamos antes, pero reintroducido por el mínimo duro del panel). Al
        reportar siempre el piso angosto, Qt permite el resize y _update_responsive_mode
        reacciona al instante (dentro del mismo resizeEvent, antes de repintar) acoplando
        u ocultando el panel de Opciones según corresponda — el usuario nunca llega a ver
        el achique transitorio."""
        base = super().minimumSizeHint()
        if not hasattr(self, "queue_widget"):
            return base
        # bottom_row (timeline + cubo de salida) sí se incluye: a diferencia del panel de
        # Opciones, nunca se saca/reinserta del layout (no "colapsa"), así que su mínimo es
        # una contribución estática de siempre — incluirla no reintroduce el bloqueo de
        # saltos grandes (ese bloqueo era específico de un mínimo que aparece/desaparece
        # al acoplar/desacoplar el panel de Opciones).
        width = max(self._undocked_floor_width(), self.bottom_row.minimumSizeHint().width())
        return QSize(width, base.height())

    def _undocked_floor_width(self) -> int:
        """Ancho mínimo real con el panel de Opciones en overlay (fuera del layout): solo
        cuentan la cola de medios (ancho fijo) y el mínimo propio del preview."""
        margins = self.top_row_layout.contentsMargins()
        spacing = self.top_row_layout.spacing()
        preview_min = self.preview_widget.minimumSizeHint().width()
        return self.QUEUE_WIDTH + preview_min + spacing + margins.left() + margins.right()

    def _docked_floor_width(self) -> int:
        """Ancho mínimo real que exige la fila superior con el panel de opciones acoplado
        Y el preview en su tamaño CÓMODO (PREVIEW_MIN_WIDTH), no su mínimo técnico absoluto
        — decisión confirmada con el usuario: a 1100px (resolución default de la app) no
        entran cola+opciones+preview cómodos a la vez (340+500+600=1440), así que a esa
        resolución el panel de Opciones vuelve a ser overlay en vez de acoplarse apretado
        contra un preview aplastado. Se calcula en vivo (no un valor fijo): si el contenido
        de cualquiera de las partes cambia a futuro, el umbral se ajusta solo."""
        margins = self.top_row_layout.contentsMargins()
        spacing = self.top_row_layout.spacing()
        return (
            self.QUEUE_WIDTH
            + self.right_panel.docked_size
            + self.PREVIEW_MIN_WIDTH
            + spacing * 2
            + margins.left() + margins.right()
            + 20  # margen de seguridad
        )

    def _preview_max_width(self) -> int:
        """Tope de ancho del preview: un porcentaje del ancho de la ventana (no un número
        fijo) para que no "siga y siga creciendo" en pantallas grandes/maximizadas a costa
        de dejar la cola de medios y las opciones (de ancho fijo) desproporcionadamente
        chicas — en la resolución default queda pequeño y centrado."""
        return max(self.PREVIEW_MIN_WIDTH, int(self.width() * self.PREVIEW_MAX_WIDTH_RATIO))

    def _output_card_max_width(self) -> int:
        """Tope de ancho del cubo de Opciones de Salida y Procesamiento: antes tenía
        stretch=0 en bottom_row_layout, así que se quedaba SIEMPRE en su ancho natural sin
        importar cuánto creciera la ventana. Ahora tiene stretch>0 (crece de verdad), y este
        método solo pone el TECHO (35% del ancho de ventana) — el piso lo sigue poniendo su
        propio minimumSizeHint natural, nunca forzado, para no repetir el mismo bloqueo de
        `setFixedWidth` que ya tuvimos con el panel de opciones."""
        return int(self.width() * self.OUTPUT_CARD_MAX_WIDTH_RATIO)

    def _queue_max_width(self) -> int:
        """Techo de la cola de medios: antes ancho 100% fijo (nunca crecía). Ahora el
        reparto real lo hace el stretch de top_row_layout (que ya usa el 100% del espacio
        disponible); esto solo pone un techo de seguridad para ventanas ultra-anchas."""
        return max(self.QUEUE_WIDTH, self.SIDE_PANEL_MAX_WIDTH_CAP)

    def _options_max_width(self) -> int:
        """Mismo criterio que _queue_max_width, para el panel de Opciones acoplado."""
        return max(self.OPTIONS_DOCKED_WIDTH, self.SIDE_PANEL_MAX_WIDTH_CAP)

    def _update_responsive_mode(self):
        if not hasattr(self, "right_panel"):
            return
        threshold = max(self.COLLAPSE_THRESHOLD_WIDTH, self._docked_floor_width())
        want_docked = self.width() >= threshold
        if want_docked != self.right_panel.is_docked():
            self.right_panel.set_mode(docked=want_docked)
        self.right_panel.set_dock_max_width(self._options_max_width())
        self.right_panel.sync_overlay_geometry()
        self.queue_widget.setMaximumWidth(self._queue_max_width())
        # Se recalcula después de resolver el modo acoplado/overlay para que el tope de
        # ancho del preview refleje el espacio realmente disponible en este mismo resize.
        preview_cap = self._preview_max_width()
        self.preview_widget.setMaximumWidth(preview_cap)
        # Sin esto, preview_center_wrapper (que tiene más peso de stretch que la cola/
        # opciones para que el preview crezca primero) reclama más ancho del que el
        # preview realmente usa una vez alcanza su propio tope, y ese sobrante queda como
        # hueco muerto alrededor del preview en vez de repartirse hacia los costados.
        self.preview_center_wrapper.setMaximumWidth(preview_cap)
        self.output_card.setMaximumWidth(self._output_card_max_width())

    def _on_file_selected(self, filepath: str):
        # filepath es la CLAVE de la entrada de la cola: para tocar disco hay que
        # resolverla a la ruta real, porque un mismo archivo puede estar repetido con
        # recortes distintos (ver media_queue_widget.entry_path).
        self.current_preview_file = filepath
        filepath = entry_path(filepath)
        if not filepath or not os.path.exists(filepath):
            self.preview_widget.clear()
            return

        ext = os.path.splitext(filepath)[1].lower()
        media_type = "audio" if ext in AUDIO_ONLY_EXTENSIONS else "video"

        meta = FFprobeMetadataManager.get_instance().get_metadata_instant(filepath, media_type)
        duration_sec = self._parse_duration_to_seconds(meta.get("duración", "0"))
        fps_val = self._parse_fps(meta.get("fps", "30"))
        if duration_sec <= 0:
            duration_sec = 1.0

        cached_trim = self._trim_cache.get(self.current_preview_file)
        cached_in, cached_out = cached_trim if cached_trim else (None, None)
        self.preview_widget.load_media(
            filepath, media_type, duration_sec, fps_val,
            initial_in_sec=cached_in, initial_out_sec=cached_out,
            initial_audio_track_selection=self._audio_track_cache.get(self.current_preview_file),
        )
        self.options_widget.tab_advanced.set_source_media(meta, filepath)
        self.options_widget.tab_compress.set_source_media(meta, filepath)
        self.options_widget.tab_convert.set_source_media(meta, filepath)
        self.options_widget.tab_editing.set_source_media(meta, filepath)
        self.options_widget.tab_presets.set_source_media(meta, filepath)
        # preview_widget.load_media ya ocultó el rectángulo (el encuadre elegido no tiene
        # sentido para otro archivo); esto lo vuelve a mostrar de una para el archivo nuevo
        # si el recorte interactivo sigue activo (personalizado + Recortar es config. del
        # panel, no del archivo, así que no se "apaga" solo al cambiar de ítem).
        self.options_widget.tab_advanced.hide_apply_to_all_checkbox()
        self._on_crop_edit_toggled(self.options_widget.tab_advanced.is_crop_active())

    def receive_media_from_editor(self, items: list) -> int:
        """Agrega a la cola medios enviados desde el editor con "Enviar a DowP".

        Cada item es {path, in, out, has_trim, name}. Un clip recortado en la linea de
        tiempo entra como entrada PROPIA aunque su archivo ya este en la cola (dos cortes
        del mismo medio son dos trabajos distintos, ver
        media_queue_widget.add_files(allow_duplicates)); un medio sin recorte se deduplica
        como cualquier otro archivo agregado a mano.

        Devuelve cuantos entraron.
        """
        trimmed, plain = [], []
        for item in items or []:
            path = item.get("path")
            if not path or not os.path.exists(path):
                logger.warning(f"VideoToolsTab: El editor mando un archivo que no existe: {path}")
                continue
            (trimmed if item.get("has_trim") else plain).append(item)

        added_keys = []
        if plain:
            added_keys += self.queue_widget.add_files([i["path"] for i in plain]) or []
        if trimmed:
            keys = self.queue_widget.add_files(
                [i["path"] for i in trimmed], allow_duplicates=True) or []
            for key, item in zip(keys, trimmed):
                # El recorte viaja por el mismo cache por-archivo que usa el recorte hecho
                # a mano en la vista previa, asi que la waveform lo muestra marcado y la
                # recodificacion lo respeta sin ningun camino especial (ver _trim_cache).
                self._trim_cache[key] = (float(item["in"]), float(item["out"]))
            added_keys += keys

        if added_keys:
            # Deja seleccionado lo ultimo que llego para que se vea el corte de una.
            self.queue_widget.select_entry(added_keys[-1])
        return len(added_keys)

    def _on_queue_changed(self, _count: int = 0):
        """Reacciona a altas/bajas en la cola: empuja la metadata de TODA la cola a
        Comprimir/Rápido (estimado de peso agregado) y a Convertir/Rápido (resumen de
        cuántos archivos remuxean vs necesitan recodificar) - a diferencia del estimado
        por-archivo, que ya cubre set_source_media con el archivo en preview. También
        poda los cachés por-archivo (recorte y selección de pista de audio) de archivos
        que ya no están en la cola - si no, un archivo distinto que reutilice la misma
        ruta más tarde heredaría ajustes que no le corresponden.

        El cálculo de metadata en sí (un get_metadata_instant() por archivo) corre en
        un hilo aparte (_QueueMetadataThread) -- con miles de archivos recién
        importados, ese loop síncrono en el hilo de UI alcanzaba a notarse (ver
        conversación: "se cuelga por varios segundos... con 4000 archivos")."""
        current_files = set(self.queue_widget.get_all_filepaths())
        for cache in (self._trim_cache, self._audio_track_cache):
            for filepath in set(cache.keys()) - current_files:
                del cache[filepath]

        self._queue_meta_request_id += 1
        request_id = self._queue_meta_request_id
        self._queue_meta_thread = _QueueMetadataThread(
            [entry_path(key) for key in current_files], self)
        self._queue_meta_thread.finished_computing.connect(
            lambda entries, entries_with_paths, rid=request_id:
                self._on_queue_metadata_computed(rid, entries, entries_with_paths)
        )
        self._queue_meta_thread.start()

    def _on_queue_metadata_computed(self, request_id: int, entries: list, entries_with_paths: list):
        if request_id != self._queue_meta_request_id:
            return  # Una importación más nueva ya disparó otro cálculo -- este quedó obsoleto.
        self.options_widget.tab_compress.set_queue_entries(entries)
        self.options_widget.tab_convert.set_queue_entries(entries_with_paths)

    def _on_metadata_ready(self, path: str, meta: dict):
        if path == entry_path(self.current_preview_file):
            self.preview_widget.set_fps(self._parse_fps(meta.get("fps", "30")))
            self.options_widget.tab_advanced.set_source_media(meta, path)
            self.options_widget.tab_compress.set_source_media(meta, path)
            self.options_widget.tab_convert.set_source_media(meta, path)
            self.options_widget.tab_editing.set_source_media(meta, path)
            self.options_widget.tab_presets.set_source_media(meta, path)
            # La metadata rápida inicial puede no traer resolución todavía; si el recorte
            # ya está activo, se re-arma ahora con la resolución real recién confirmada.
            self._on_crop_edit_toggled(self.options_widget.tab_advanced.is_crop_active())

    def _on_trim_range_changed(self, in_sec: float, out_sec: float):
        self.in_point_ms = int(in_sec * 1000)
        self.out_point_ms = int(out_sec * 1000)
        if self.current_preview_file:
            self._trim_cache[self.current_preview_file] = (in_sec, out_sec)
        logger.debug(f"VideoToolsTab: Trim points actualizados: In={self.in_point_ms}ms, Out={self.out_point_ms}ms")

    def _on_audio_track_selection_changed(self):
        if not self.current_preview_file:
            return
        selection = self.preview_widget.get_audio_track_selection()
        if selection is not None:
            self._audio_track_cache[self.current_preview_file] = selection

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

    def _describe_first_audio_track(self, streams: list[dict]) -> str:
        """Mismo criterio que MediaTrimPlayerWidget._describe_audio_track (índice + idioma
        + códec) para que la nota de fallback nombre la pista igual que la UI de
        selección, en vez de un "Pista 1" genérico sin contexto para decidir si hace falta
        rehacer el archivo a mano en Manual eligiendo otra."""
        label = self.tr("Pista 1")
        if not streams:
            return label
        first = streams[0]
        lang = (first.get("language") or "").strip()
        codec = (first.get("codec") or "").strip()
        if lang:
            label += f" — {lang}"
        if codec:
            label += f" ({codec})"
        return label

    def _parse_duration_to_seconds(self, dur_str) -> float:
        if not dur_str or dur_str == "-":
            return 0.0
        if isinstance(dur_str, (int, float)):
            return float(dur_str)
        try:
            parts = str(dur_str).split(":")
            if len(parts) == 2:
                return float(parts[0]) * 60 + float(parts[1])
            elif len(parts) == 3:
                return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        except Exception:
            pass
        return 0.0

    def _parse_fps(self, fps_val) -> float:
        try:
            return float(str(fps_val).replace("fps", "").strip())
        except (ValueError, AttributeError):
            return 30.0

    def load_labels(self):
        """Carga las etiquetas configuradas en la aplicación en el combo de etiquetas con círculos de color."""
        if not hasattr(self, "combo_tags"):
            return
        from core.utils.config_manager import get_config
        from PySide6.QtGui import QColor

        self.combo_tags.blockSignals(True)
        current_text = self.combo_tags.currentText()
        self.combo_tags.clear()
        self.combo_tags.addItem(self.tr("Etiqueta"), "")

        config = get_config()
        labels = config.get("labels", [])
        for label in labels:
            name = label.get("name", "")
            path = label.get("path", "")
            color = label.get("color", "#B9E640")

            idx = self.combo_tags.count()
            icon = create_colored_circle_icon(color, size=12)
            self.combo_tags.addItem(icon, name, path)

            self.combo_tags.setItemData(idx, color, Qt.UserRole + 1)
            self.combo_tags.setItemData(idx, QColor(color), Qt.ForegroundRole)

        # Intentar restaurar selección si aún existe
        idx = self.combo_tags.findText(current_text)
        if idx >= 0:
            self.combo_tags.setCurrentIndex(idx)
        else:
            self.combo_tags.setCurrentIndex(0)

        self.combo_tags.blockSignals(False)
        self._update_combo_style()

    def _update_combo_style(self):
        """Actualiza el color de texto del combo según la etiqueta seleccionada."""
        if hasattr(self, "combo_tags"):
            update_label_combobox_style(self.combo_tags)

    def _on_label_changed(self, index):
        """Maneja el cambio de selección en el combobox de etiquetas."""
        self._update_combo_style()
        if self.chk_same_path.isChecked():
            return
        if index <= 0:
            self._load_saved_output_dir()
            self.txt_output_dir.setEnabled(True)
            self.btn_browse_output.setEnabled(True)
        else:
            path = self.combo_tags.currentData()
            if path:
                self.txt_output_dir.setText(path)
            self.txt_output_dir.setEnabled(False)
            self.btn_browse_output.setEnabled(False)

    def _on_browse_output_clicked(self):
        folder = QFileDialog.getExistingDirectory(self, self.tr("Seleccionar Carpeta de Salida"))
        if folder:
            if hasattr(self, "combo_tags"):
                self.combo_tags.setCurrentIndex(0)
            self.txt_output_dir.setText(folder)
            config = get_config()
            config["video_tools_output_dir"] = folder
            save_config(config)

    def _on_open_output_clicked(self):
        folder = self.txt_output_dir.text().strip()
        if folder and os.path.exists(folder):
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _on_same_path_toggled(self, checked: bool):
        has_tag = hasattr(self, "combo_tags") and self.combo_tags.currentIndex() > 0
        self.lbl_dest.setEnabled(not checked)
        self.txt_output_dir.setEnabled((not checked) and (not has_tag))
        self.btn_browse_output.setEnabled((not checked) and (not has_tag))
        self.btn_open_output.setEnabled(not checked)
        if hasattr(self, "combo_tags"):
            self.combo_tags.setEnabled(not checked)
        
        config = get_config()
        config["video_tools_same_path"] = checked
        save_config(config)

    def _on_conflict_policy_changed(self, _index: int):
        config = get_config()
        config["video_tools_conflict_policy"] = self.combo_conflict_policy.currentData()
        save_config(config)

    def _load_saved_output_dir(self):
        config = get_config()
        saved = config.get("video_tools_output_dir", "")
        if saved and os.path.exists(saved):
            self.txt_output_dir.setText(saved)
        else:
            default_dir = os.path.join(os.path.expanduser("~"), "Videos")
            if os.path.exists(default_dir):
                self.txt_output_dir.setText(default_dir)

        same_path = config.get("video_tools_same_path", False)
        self.chk_same_path.setChecked(same_path)
        self._on_same_path_toggled(same_path)

        saved_policy = config.get("video_tools_conflict_policy", "conservar")
        idx = self.combo_conflict_policy.findData(saved_policy)
        if idx >= 0:
            self.combo_conflict_policy.setCurrentIndex(idx)

    def _on_start_status_changed(self, is_valid: bool, text: str):
        if getattr(self, "_recode_jobs", None):
            return
        if hasattr(self, "btn_start"):
            self.btn_start.setEnabled(is_valid)
            self.btn_start.setText(text)

    def _set_start_button_running(self, running: bool):
        """Un solo botón cambia de rol: "Iniciar Recodificación" <-> "Cancelar", en vez
        de mostrar/ocultar un segundo botón aparte."""
        self._batch_active = running
        if running:
            self.btn_start.setText(self.tr("Cancelar"))
            self.btn_start.setObjectName("redButton")
            self.btn_start.setEnabled(True)
        else:
            self.btn_start.setObjectName("downloadButton")
        self.btn_start.style().unpolish(self.btn_start)
        self.btn_start.style().polish(self.btn_start)

    def _on_start_button_clicked(self):
        if self._batch_active:
            self._on_cancel_recoding_clicked()
        else:
            self._on_start_recoding_clicked()

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

        # Reescalado IA es un job_type distinto (UPSCALE_VIDEO, no RECODE) con su
        # propia lógica de extracción/reescalado/rearmado -- ver
        # _start_upscale_ia_jobs y QueueWorker._execute_upscale_video
        # (core/utils/queue_manager.py). El resto de esta función es exclusivo
        # de RECODE (trim, marca de agua, selección de pista de audio...), nada
        # de eso aplica acá.
        if self.options_widget.tabs.currentWidget() is self.options_widget.tab_upscale_ia:
            self._start_upscale_ia_jobs(files, settings, out_dir, same_path)
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
            job_id = qm.add_job(config, "RECODE")
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
        qm.start_queue()

    def _has_enough_space_for_upscale(self, meta: dict, fps: float, duration_sec: float, settings: dict) -> bool:
        """Estimación gruesa antes de encolar (ver
        video_upscale_engine.estimate_temp_space_bytes) -- los frames
        temporales se extraen en tempfile.mkdtemp(), que en los 3 SO cae en
        el directorio temporal del sistema. Solo un archivo UPSCALE_VIDEO
        corre a la vez (ver _HEAVY_JOB_TYPES en queue_manager.py), así que
        alcanza con chequear el espacio libre ACTUAL para cada archivo por
        separado -- para cuando le toque el turno al siguiente, el anterior
        ya liberó sus temporales."""
        import re
        import shutil
        import tempfile
        from core.tabs.video_tools.video_upscale_engine import estimate_temp_space_bytes

        match = re.match(r"(\d+)x(\d+)", meta.get("resolución", ""))
        if not match:
            return True  # sin resolución confiable, no bloquear por las dudas
        width, height = int(match.group(1)), int(match.group(2))

        scale_text = str(settings.get("upscale_scale") or "4")
        scale_digits = re.sub(r"[^0-9]", "", scale_text)
        scale = int(scale_digits) if scale_digits else 4

        needed = estimate_temp_space_bytes(width, height, fps, duration_sec, scale)
        try:
            free = shutil.disk_usage(tempfile.gettempdir()).free
        except OSError:
            return True
        return needed <= free

    def _start_upscale_ia_jobs(self, files, settings, out_dir, same_path):
        """Arma un job UPSCALE_VIDEO por archivo -- versión simplificada del
        loop de RECODE (_on_start_recoding_clicked): sin trim/marca de agua/
        selección de pista de audio, esas opciones no aplican al Reescalado
        IA. Reusa self._recode_jobs/_recode_backups para el progreso/estado/
        cancelación -- _on_job_progress/_on_job_status/_on_cancel_recoding_
        clicked ya son genéricos (no miran job_type), así que no hace falta
        duplicarlos para este job_type nuevo."""
        if not self._confirm_upscale_engine_if_needed(settings.get("upscale_engine")):
            return

        qm = get_queue_manager()
        container = settings.get("container", "mp4")
        container_ext = CONTAINER_TO_EXTENSION.get(container, container)
        prefix = self.txt_prefix.text() if hasattr(self, "txt_prefix") else ""
        suffix = self.txt_suffix.text() if hasattr(self, "txt_suffix") else ""
        conflict_policy = self.combo_conflict_policy.currentData() or "conservar"
        claimed_out_paths = set()
        queued_any = False

        for entry_key in files:
            filepath = entry_path(entry_key)
            ext = os.path.splitext(filepath)[1].lower()
            if ext in AUDIO_ONLY_EXTENSIONS:
                logger.info(f"VideoToolsTab: Reescalado IA omite (sin video): {filepath}")
                self.queue_widget.update_file_status(entry_key, self.tr("Omitido (sin video)"))
                continue

            # get_metadata_instant() es solo-caché -- un archivo recién agregado a la
            # cola casi nunca está cacheado, y devuelve fps/resolución vacíos en
            # silencio (confirmado con una corrida real: el reensamblado salía a
            # 30fps fijo en vez del fps real de la fuente). _extract_ffprobe_json()
            # es el sondeo síncrono real, el único que sirve acá.
            meta = FFprobeMetadataManager.get_instance()._extract_ffprobe_json(filepath, "video")
            duration_sec = self._parse_duration_to_seconds(meta.get("duración", "0"))
            fps = self._parse_fps(meta.get("fps", "30"))

            if not self._has_enough_space_for_upscale(meta, fps, duration_sec, settings):
                logger.info(f"VideoToolsTab: Reescalado IA omite (sin espacio en disco): {filepath}")
                self.queue_widget.update_file_status(entry_key, self.tr("Sin espacio en disco"))
                continue

            base_name = os.path.splitext(os.path.basename(filepath))[0]
            out_name = f"{prefix}{base_name}{suffix}.{container_ext}"
            actual_out_dir = os.path.dirname(filepath) if same_path else out_dir
            out_file = os.path.join(actual_out_dir, out_name)

            out_file, backup_path = resolve_conflict(out_file, conflict_policy)
            while out_file is not None and out_file in claimed_out_paths:
                if conflict_policy == "omitir":
                    out_file = None
                else:
                    out_file = find_available_rename(out_file)
            if out_file is None:
                logger.info(f"VideoToolsTab: Omitido por conflicto de nombre: {filepath}")
                self.queue_widget.update_file_status(entry_key, self.tr("Omitido"))
                continue
            claimed_out_paths.add(out_file)

            config = {
                "input_path": filepath,
                "output_path": out_file,
                "upscale_options": settings,
                "fps": fps,
                "duration_sec": duration_sec,
                "title": f"Reescalado IA: {base_name}",
                "queue_entry_key": entry_key,
            }
            job_id = qm.add_job(config, "UPSCALE_VIDEO")
            self._recode_jobs.add(job_id)
            self._recode_backups[job_id] = backup_path
            queued_any = True
            self.queue_widget.update_file_status(entry_key, self.tr("En cola"))

        if not queued_any:
            return

        self._set_start_button_running(True)
        self.progress_bar.setProperty("status", "downloading")
        self.progress_bar.style().unpolish(self.progress_bar)
        self.progress_bar.style().polish(self.progress_bar)
        qm.start_queue()

    def _start_chained_jobs(self, files, upscale_settings, recode_settings, out_dir, same_path):
        """Arma, por archivo, un job UPSCALE_VIDEO seguido de un job RECODE
        encadenado -- Reescalado IA primero, Recodificación después (ver
        conversación sobre el orden: la Recodificación define el archivo
        final -- códec/calidad/contenedor -- y si hay marca de agua queda
        nítida al aplicarse sobre el video ya reescalado). El de
        Recodificación recién se crea cuando el de Reescalado IA termina bien
        (ver _on_job_status, rama COMPLETED, que chequea self._chain_pending)
        -- no hay ningún mecanismo de "depende de" en queue_manager.py, se
        arma acá en la GUI sin tocarlo. El archivo intermedio (salida de la
        etapa 1) vive en self._chain_temp_dir, invisible para el usuario --
        NO pasa por resolve_conflict (no es un destino real), y se borra
        apenas la etapa 2 termina sea cual sea el resultado (ver
        self._chain_cleanup)."""
        if not self._confirm_upscale_engine_if_needed(upscale_settings.get("upscale_engine")):
            return

        import tempfile

        qm = get_queue_manager()
        final_container = recode_settings.get("container", "mp4")
        final_container_ext = CONTAINER_TO_EXTENSION.get(final_container, final_container)
        prefix = self.txt_prefix.text() if hasattr(self, "txt_prefix") else ""
        suffix = self.txt_suffix.text() if hasattr(self, "txt_suffix") else ""
        conflict_policy = self.combo_conflict_policy.currentData() or "conservar"
        claimed_out_paths = set()
        queued_any = False

        for idx, entry_key in enumerate(files):
            filepath = entry_path(entry_key)
            ext = os.path.splitext(filepath)[1].lower()
            if ext in AUDIO_ONLY_EXTENSIONS:
                logger.info(f"VideoToolsTab: Reescalado IA omite (sin video): {filepath}")
                self.queue_widget.update_file_status(entry_key, self.tr("Omitido (sin video)"))
                continue

            # get_metadata_instant() es solo-caché -- ver comentario equivalente en
            # _start_upscale_ia_jobs, mismo motivo.
            meta = FFprobeMetadataManager.get_instance()._extract_ffprobe_json(filepath, "video")
            duration_sec = self._parse_duration_to_seconds(meta.get("duración", "0"))
            fps = self._parse_fps(meta.get("fps", "30"))

            if not self._has_enough_space_for_upscale(meta, fps, duration_sec, upscale_settings):
                logger.info(f"VideoToolsTab: Reescalado IA omite (sin espacio en disco): {filepath}")
                self.queue_widget.update_file_status(entry_key, self.tr("Sin espacio en disco"))
                continue

            base_name = os.path.splitext(os.path.basename(filepath))[0]

            # Salida FINAL -- misma lógica de nombre/conflicto que el loop de RECODE normal.
            out_name = f"{prefix}{base_name}{suffix}.{final_container_ext}"
            actual_out_dir = os.path.dirname(filepath) if same_path else out_dir
            out_file = os.path.join(actual_out_dir, out_name)
            out_file, backup_path = resolve_conflict(out_file, conflict_policy)
            while out_file is not None and out_file in claimed_out_paths:
                if conflict_policy == "omitir":
                    out_file = None
                else:
                    out_file = find_available_rename(out_file)
            if out_file is None:
                logger.info(f"VideoToolsTab: Omitido por conflicto de nombre: {filepath}")
                self.queue_widget.update_file_status(entry_key, self.tr("Omitido"))
                continue
            claimed_out_paths.add(out_file)

            # Intermedio -- invisible para el usuario, no pasa por resolve_conflict.
            if self._chain_temp_dir is None:
                self._chain_temp_dir = tempfile.mkdtemp(prefix="dowp_chain_")
            intermediate_path = os.path.join(self._chain_temp_dir, f"{idx}_{base_name}.mp4")

            config = {
                "input_path": filepath,
                "output_path": intermediate_path,
                "upscale_options": upscale_settings,
                "fps": fps,
                "duration_sec": duration_sec,
                "title": f"Reescalado IA: {base_name}",
                "queue_entry_key": entry_key,
            }
            job_id = qm.add_job(config, "UPSCALE_VIDEO")
            self._recode_jobs.add(job_id)
            self._chain_pending[job_id] = {
                "recode_settings": recode_settings,
                "final_output": out_file,
                "backup_path": backup_path,
                "duration_sec": duration_sec,
                "entry_key": entry_key,
            }
            queued_any = True
            self.queue_widget.update_file_status(entry_key, self.tr("En cola"))

        if not queued_any:
            return

        self._set_start_button_running(True)
        self.progress_bar.setProperty("status", "downloading")
        self.progress_bar.style().unpolish(self.progress_bar)
        self.progress_bar.style().polish(self.progress_bar)
        qm.start_queue()

    def _confirm_upscale_engine_if_needed(self, engine: str | None) -> bool:
        """Reescalado IA puede tardar minutos/horas -- a diferencia del popover
        de Reescalar IA de Editor de Imagen (que ofrece la descarga al elegir
        el motor pero no bloquea si se ignora), acá conviene el mismo patrón
        bloqueante que ya usa Convertir para Ghostscript/vtracer
        (_confirm_ghostscript_if_needed/_confirm_vtracer_if_needed en
        image_tools_view.py): preguntar y descargar ANTES de encolar nada, no
        dejar que cada archivo falle a mitad de un trabajo largo."""
        from core.constants import UPSCALING_TOOLS
        from core.setup.models_setup import is_upscaling_engine_installed

        tool_info = UPSCALING_TOOLS.get(engine)
        if tool_info is None or is_upscaling_engine_installed(tool_info):
            return True

        reply = QMessageBox.question(
            self, self.tr("Motor no instalado"),
            self.tr(
                "'{0}' no está instalado. ¿Descargarlo ahora o cancelar el proceso?"
            ).format(tool_info["name"]),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return False
        return self._download_upscale_engine_blocking(tool_info)

    def _download_upscale_engine_blocking(self, tool_info: dict) -> bool:
        from core.setup.models_setup import download_upscaling_engine

        progress = QProgressDialog(
            self.tr("Descargando {0}...").format(tool_info["name"]), self.tr("Cancelar"), 0, 100, self,
        )
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(True)
        progress.setValue(0)

        result = {"success": False, "msg": ""}

        class _EngineDownloadThread(QThread):
            finished_signal = Signal(bool, str)
            progress_signal = Signal(int)

            def run(self):
                def _cb(pct):
                    self.progress_signal.emit(int(pct))
                success, msg = download_upscaling_engine(tool_info, progress_callback=_cb)
                self.finished_signal.emit(success, msg)

        worker = _EngineDownloadThread()
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
                self.tr("No se pudo descargar '{0}':\n{1}").format(tool_info["name"], result["msg"]),
            )
        return result["success"]

    def _on_cancel_recoding_clicked(self):
        qm = get_queue_manager()
        for job_id in list(self._recode_jobs):
            job = qm.get_job(job_id)
            if job and job.status in (JobStatus.PENDING, JobStatus.RUNNING):
                qm.cancel_job(job_id)
        self.btn_start.setEnabled(False)
        self.progress_bar.setFormat(self.tr("Cancelando..."))

    def _on_job_progress(self, job_id: str, percent: float, speed: str, eta: str):
        if job_id in self._recode_jobs:
            self.progress_bar.setValue(int(percent))
            self.progress_bar.setFormat(f"{percent:.1f}% - {speed} - {eta}")

    def _on_job_status(self, job_id: str, status: str):
        if job_id not in self._recode_jobs:
            return
            
        qm = get_queue_manager()
        job = qm.get_job(job_id)
        if not job:
            return
            
        # La fila de la cola, no la ruta: ver "queue_entry_key" al crear el trabajo.
        file_path = job.config.get("queue_entry_key") or job.config.get("input_path")

        if status == JobStatus.RUNNING:
            self.queue_widget.update_file_status(file_path, self.tr("Procesando..."))
        elif status == JobStatus.COMPLETED and job_id in self._chain_pending:
            # Terminó la etapa 1 (Reescalado IA) de una cadena -- todavía NO es
            # el resultado final, recién ahora se arma la etapa 2
            # (Recodificación) usando la salida de esta como entrada. Nada de
            # commit_backup/envío al editor/_check_all_finished acá -- eso le
            # toca a la etapa 2 cuando termine de verdad.
            chain = self._chain_pending.pop(job_id)
            self.queue_widget.update_file_status(file_path, self.tr("Recodificando..."))
            new_config = {
                "input_path": job.config.get("output_path"),  # el intermedio
                "output_path": chain["final_output"],
                "settings": chain["recode_settings"],
                "duration_sec": chain["duration_sec"],
                "title": f"Recode (tras IA): {os.path.basename(chain['final_output'])}",
                "queue_entry_key": chain["entry_key"],
            }
            new_job_id = qm.add_job(new_config, "RECODE")
            self._recode_jobs.add(new_job_id)
            self._recode_backups[new_job_id] = chain["backup_path"]
            self._chain_cleanup[new_job_id] = job.config.get("output_path")
        elif status == JobStatus.COMPLETED:
            commit_backup(self._recode_backups.pop(job_id, None))
            note = self._recode_job_notes.pop(job_id, None)
            status_text = self.tr("Completado ({0})").format(note) if note else self.tr("Completado")
            self.queue_widget.update_file_status(file_path, status_text)
            output_path = job.config.get("output_path")
            if output_path:
                # Habilita arrastrar este resultado fuera/dentro de la app -- ver
                # MediaQueueWidget._output_paths / _QueueTableModel.flags/mimeData.
                self.queue_widget.set_output_path(file_path, output_path)

            # Enviar el archivo final al editor (el QueueManager ignora los trabajos RECODE)
            from core.services.editor_integration_manager import EditorIntegrationManager
            editor_mgr = EditorIntegrationManager.get_instance()
            if editor_mgr and editor_mgr.is_auto_send_enabled:
                if output_path:
                    editor_mgr.process_raw_download(output_path, job.request_data if job else {})

            self._cleanup_chain_intermediate(job_id)
            self._check_all_finished()
        elif status == JobStatus.FAILED:
            rollback_backup(self._recode_backups.pop(job_id, None))
            self._recode_job_notes.pop(job_id, None)
            self._chain_pending.pop(job_id, None)
            self.queue_widget.update_file_status(file_path, self.tr("Error"))
            self._cleanup_chain_intermediate(job_id)
            self._check_all_finished()
        elif status == JobStatus.CANCELLED:
            rollback_backup(self._recode_backups.pop(job_id, None))
            self._recode_job_notes.pop(job_id, None)
            self._chain_pending.pop(job_id, None)
            self.queue_widget.update_file_status(file_path, self.tr("Cancelado"))
            self._cleanup_chain_intermediate(job_id)
            self._check_all_finished()

    def _cleanup_chain_intermediate(self, job_id: str):
        """Borra el archivo intermedio de una cadena Reescalado IA ->
        Recodificación cuando la etapa 2 (Recodificación) llega a un estado
        final -- pase lo que pase (éxito, error o cancelación), el intermedio
        nunca es el resultado que le importa al usuario."""
        intermediate_path = self._chain_cleanup.pop(job_id, None)
        if not intermediate_path:
            return
        try:
            if os.path.exists(intermediate_path):
                os.remove(intermediate_path)
        except OSError as e:
            logger.warning(f"VideoToolsTab: no se pudo borrar el intermedio de cadena '{intermediate_path}': {e}")

    def _check_all_finished(self):
        qm = get_queue_manager()
        all_done = True
        for jid in list(self._recode_jobs):
            job = qm.get_job(jid)
            if job and job.status in (JobStatus.PENDING, JobStatus.RUNNING):
                all_done = False
                break
                
        if all_done:
            self._recode_jobs.clear()
            if self._chain_temp_dir is not None:
                import shutil
                shutil.rmtree(self._chain_temp_dir, ignore_errors=True)
                self._chain_temp_dir = None
            self._set_start_button_running(False)
            self._on_start_status_changed(*self.options_widget.get_current_status())
            self.progress_bar.setValue(100)
            self.progress_bar.setFormat(self.tr("Finalizado"))
            self.progress_bar.setProperty("status", "wait")
            self.progress_bar.style().unpolish(self.progress_bar)
            self.progress_bar.style().polish(self.progress_bar)

    def showEvent(self, event):
        super().showEvent(event)
        from core.utils.config_manager import get_config, save_config
        config = get_config()
        if not config.get("tutorial_video_tools_seen", False):
            QTimer.singleShot(500, self.start_tutorial)
            config["tutorial_video_tools_seen"] = True
            save_config(config)

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
