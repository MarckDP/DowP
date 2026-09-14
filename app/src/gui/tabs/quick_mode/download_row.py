# src/gui/tabs/quick_mode/download_row.py
import os
import re
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt, QSize, Signal, QT_TRANSLATE_NOOP
from PySide6.QtGui import QImage, QPixmap, QIcon, QColor
from PySide6.QtWidgets import QApplication

from core.logger.logger_manager import logger
from core.utils.paths import get_src_dir
from gui.styles import get_theme_token
from gui.tabs.advanced_process.video_details_components import ThumbnailLoaderThread
from core.tabs.quick_mode.quick_mode_logic import reveal_in_file_manager
from core.utils.output_artifacts import collect_output_artifacts


def progress_bar_qss():
    """Estilo de las barras de progreso del Modo Rápido, en un solo sitio.

    Sin hoja propia, una QProgressBar se pinta con el color `Highlight` de la paleta, y
    Qt cambia ese color al grupo *Inactive* en cuanto la ventana pierde el foco: la
    barra parecía apagarse al hacer clic fuera de la app y encenderse al volver. Además
    salía del color del sistema (rojo), no del tema. Pintarla con los tokens arregla
    ambas cosas de una vez.
    """
    return f"""
            QProgressBar {{
                background-color: {get_theme_token('progreso_fondo', '#0f0f0f')};
                border: none;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {get_theme_token('progreso_inicio', '#35d6b8')},
                    stop:1 {get_theme_token('progreso_fin', '#138f7d')});
                border-radius: 3px;
            }}
    """


class QuickThumbnailWidget(QWidget):
    """
    Widget de tamaño fijo para mostrar la miniatura del medio
    y una etiqueta flotante de duración en la esquina inferior derecha.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(96, 54)
        
        # Etiqueta base de la imagen
        self.thumb_label = QLabel(self)
        self.thumb_label.setFixedSize(96, 54)
        self.thumb_label.setScaledContents(False)
        self.thumb_label.setAlignment(Qt.AlignCenter)
        
        # Etiqueta de duración superpuesta
        self.duration_label = QLabel(self)
        self.duration_label.setStyleSheet("""
            background-color: rgba(0, 0, 0, 0.75);
            color: #ffffff;
            font-size: 8px;
            font-weight: bold;
            border-radius: 3px;
            padding: 1px 3px;
        """)
        self.duration_label.setAlignment(Qt.AlignCenter)
        self.duration_label.hide()
        
        self.thumb_label.setGeometry(0, 0, 96, 54)
        self._set_default_thumbnail()
        
    def _set_default_thumbnail(self):
        icon_path = os.path.join(get_src_dir(), "assets", "icons", "svg", "movie.svg")
        
        bg_color = get_theme_token('fondo_principal', '#121212')
        borde_color = get_theme_token('borde', '#2d2d2d')
        
        self.thumb_label.setStyleSheet(f"""
            QLabel {{
                background-color: {bg_color};
                border: 1px solid {borde_color};
                border-radius: 4px;
            }}
        """)
        
        if os.path.exists(icon_path):
            pixmap = QIcon(icon_path).pixmap(24, 24)
            self.thumb_label.setPixmap(pixmap)
        else:
            self.thumb_label.setText("🎞️")
            
    def set_duration(self, duration_sec):
        if not duration_sec:
            self.duration_label.hide()
            return
        try:
            seconds = int(float(duration_sec))
            h = seconds // 3600
            m = (seconds % 3600) // 60
            s = seconds % 60
            if h > 0:
                formatted = f"{h}:{m:02d}:{s:02d}"
            else:
                formatted = f"{m:02d}:{s:02d}"
            self.duration_label.setText(formatted)
            self.duration_label.adjustSize()
            
            # Posicionar en la esquina inferior derecha
            lbl_w = self.duration_label.width()
            lbl_h = self.duration_label.height()
            self.duration_label.setGeometry(96 - lbl_w - 4, 54 - lbl_h - 4, lbl_w, lbl_h)
            self.duration_label.show()
        except Exception:
            self.duration_label.hide()
            
    def set_pixmap(self, pixmap):
        self.thumb_label.setText("")
        self.thumb_label.setStyleSheet("background-color: transparent; border: none;")
        scaled = pixmap.scaled(96, 54, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.thumb_label.setPixmap(scaled)


class QuickDownloadRow(QFrame):
    """Tarjeta individual de descarga con miniatura, progreso y botones de acción."""
    close_requested = Signal(object)    # Emitido al pulsar X
    reveal_requested = Signal(object)   # Emitido al pulsar botón de carpeta
    drag_requested = Signal(object)     # Emitido al arrastrar la tarjeta (lo resuelve ActivityPanel)
    selection_requested = Signal(object, object)  # (fila, modificadores de teclado) al hacer clic
    # Cambió el progreso o el estado terminal de esta fila. La emite para que
    # PlaylistGroupRow pueda recalcular su resumen ("3 de 9") sin que la fila tenga que
    # saber que está dentro de un grupo: quien no escuche, no se entera de nada.
    state_changed = Signal(object)

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("queueItemCard")
        self.original_title = title
        self._thumb_loaded = False
        self._thumb_loading = False
        self.thumb_thread = None
        self._duration_set = False
        self.downloaded_filepath = None
        self._is_completed = False
        self._is_error = False
        # Se pone en True con el primer porcentaje REAL (> 0) que llega del proceso.
        # Sirve para distinguir "todavía no ha empezado nada" de "va por el 0%", que es
        # lo que decide si la barra debe ir intermitente.
        self._has_real_progress = False
        # Rutas que esta fila produjo. _known_paths son las que la app conoce con
        # certeza (medio bajado, cada fragmento, salida recodificada); _stem_paths es el
        # subconjunto cuyo nombre base sirve para barrer sidecars (miniatura,
        # subtítulos) al armar el arrastre -- ver core/utils/output_artifacts.py. Nunca
        # se filtran aquí por existencia: eso se hace al arrastrar, porque entre medio
        # el pipeline puede borrar el original (no marcar "mantener medios originales")
        # o el usuario puede mover los archivos.
        self._known_paths = []
        self._stem_paths = []
        self._is_selected = False
        self._drag_press_pos = None
        self._status_color = None
        self.init_ui(title)

    def init_ui(self, title):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 8, 10, 8)
        main_layout.setSpacing(12)

        # Miniatura a la izquierda
        self.thumb_widget = QuickThumbnailWidget(self)
        main_layout.addWidget(self.thumb_widget)

        # Detalles en el centro
        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(4)

        # Fila superior: Título y Estado
        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(0, 0, 0, 0)
        self.title_lbl = QLabel(title)
        self.title_lbl.setStyleSheet(f"color: {get_theme_token('texto_principal', '#dddddd')}; font-weight: bold;")
        self.title_lbl.setWordWrap(False)
        self.title_lbl.setToolTip(title)
        
        self.status_lbl = QLabel(self.tr("En espera") if hasattr(self, "tr") else "En espera")
        self.status_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.status_lbl.setStyleSheet(f"color: {get_theme_token('texto_secundario', '#aaaaaa')}; font-size: 10px;")
        
        top_layout.addWidget(self.title_lbl, 1)
        top_layout.addWidget(self.status_lbl)
        content_layout.addLayout(top_layout)

        # Barra de progreso intermedia
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        content_layout.addWidget(self.progress_bar)

        # Fila inferior: Info y Porcentaje
        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        self.info_lbl = QLabel("")
        self.info_lbl.setStyleSheet(f"color: {get_theme_token('texto_secundario', '#888888')}; font-size: 10px;")
        
        self.percent_lbl = QLabel("0%")
        self.percent_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.percent_lbl.setStyleSheet(f"color: {get_theme_token('acento_primario', '#B9E640')}; font-size: 10px; font-weight: bold;")
        
        bottom_layout.addWidget(self.info_lbl, 1)
        bottom_layout.addWidget(self.percent_lbl)
        content_layout.addLayout(bottom_layout)

        main_layout.addLayout(content_layout, 1)

        # --- Botones de acción a la derecha ---
        actions_layout = QVBoxLayout()
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(4)
        actions_layout.setAlignment(Qt.AlignCenter)

        icon_dir = os.path.join(get_src_dir(), "assets", "icons", "svg")
        _action_btn_style = f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: 6px;
                padding: 2px;
            }}
            QPushButton:hover {{
                background-color: {get_theme_token('fondo_hover', '#2a2a2a')};
            }}
        """

        # Botón de abrir carpeta (oculto hasta que la descarga termine)
        self.btn_reveal = QPushButton()
        self.btn_reveal.setFixedSize(24, 24)
        self.btn_reveal.setToolTip(self.tr("Abrir ubicación del archivo") if hasattr(self, "tr") else "Abrir ubicación del archivo")
        self.btn_reveal.setStyleSheet(_action_btn_style)
        _folder_icon = os.path.join(icon_dir, "folder_open.svg")
        if os.path.exists(_folder_icon):
            self.btn_reveal.setIcon(QIcon(_folder_icon))
            self.btn_reveal.setIconSize(QSize(16, 16))
        else:
            self.btn_reveal.setText("📂")
        self.btn_reveal.hide()
        self.btn_reveal.clicked.connect(lambda: self.reveal_requested.emit(self))

        # Botón X (cerrar / quitar de la lista)
        self.btn_close = QPushButton()
        self.btn_close.setFixedSize(24, 24)
        self.btn_close.setToolTip(self.tr("Quitar de la lista") if hasattr(self, "tr") else "Quitar de la lista")
        self.btn_close.setStyleSheet(_action_btn_style)
        _close_icon = os.path.join(icon_dir, "close.svg")
        if os.path.exists(_close_icon):
            self.btn_close.setIcon(QIcon(_close_icon))
            self.btn_close.setIconSize(QSize(14, 14))
        else:
            self.btn_close.setText("✕")
        self.btn_close.clicked.connect(lambda: self.close_requested.emit(self))

        actions_layout.addWidget(self.btn_reveal)
        actions_layout.addWidget(self.btn_close)
        main_layout.addLayout(actions_layout)

        self._refresh_card_style()

    def _is_alive(self) -> bool:
        """True si el widget de Qt subyacente todavía existe. Las señales que
        llaman a mark_completed/mark_error/update_progress/etc. llegan async
        (progreso de descarga, fin de tarea, estado de recodificación) y pueden
        disparar DESPUÉS de que la fila ya fue sacada de la UI (el usuario la
        canceló/limpió mientras la tarea seguía en vuelo) -- en ese momento el
        lado C++ del widget ya no existe, aunque este objeto Python siga vivo
        (referenciado desde task_data/self._recode_by_download en
        download_controller.py). Mismo patrón que
        ClipboardURLMonitor._is_deleted (clipboard_monitor.py)."""
        try:
            self.objectName()
            return True
        except RuntimeError:
            return False

    # ------------------------------------------------------------------
    # Resultados en disco y arrastre nativo hacia otras aplicaciones
    # ------------------------------------------------------------------
    def add_output_files(self, paths, is_stem_source=True):
        """Registra rutas producidas por esta fila. is_stem_source=False para la salida
        recodificada: su nombre lleva el prefijo/sufijo elegido por el usuario, así que
        usarlo para barrer hermanos podría arrastrar archivos de otra descarga."""
        for path in paths or []:
            if not path:
                continue
            if path not in self._known_paths:
                self._known_paths.append(path)
            if is_stem_source and path not in self._stem_paths:
                self._stem_paths.append(path)

    def output_stems(self):
        """Rutas cuyo nombre base identifica a ESTA fila, para que otra fila de la lista
        no reclame sus archivos (ver collect_output_artifacts)."""
        return list(self._stem_paths)

    def collect_drag_files(self, foreign_stems=None):
        """Todo lo que HOY sigue existiendo en disco como resultado de esta fila: medio
        (o fragmentos), completo conservado, miniatura, subtítulos y recodificado, según
        lo que el usuario haya elegido conservar. Se resuelve en el momento del
        arrastre, nunca antes. foreign_stems son las rutas de las demás filas de la
        lista, para no llevarse lo que es de ellas."""
        try:
            return collect_output_artifacts(self._known_paths, stem_paths=self._stem_paths,
                                            foreign_stems=foreign_stems)
        except Exception as e:
            logger.error(f"QuickDownloadRow: No se pudieron reunir los archivos para arrastrar: {e}")
            return []

    def is_draggable(self):
        """Solo cuando el proceso COMPLETO terminó bien: con recodificación pedida,
        _is_completed no se activa hasta que termina también el recode (lo resuelve
        DownloadController._on_recode_job_status)."""
        return bool(self._is_completed and not self._is_error)

    def is_error(self):
        return self._is_error

    def is_selected(self):
        return self._is_selected

    def set_selected(self, selected):
        selected = bool(selected)
        if selected == self._is_selected or not self._is_alive():
            return
        self._is_selected = selected
        self._refresh_card_style()

    def _update_drag_affordance(self):
        if not self._is_alive():
            return
        self.setCursor(Qt.OpenHandCursor if self.is_draggable() else Qt.ArrowCursor)
        # El tinte verde de "listo para arrastrar" depende de is_draggable(), que cambia
        # aquí (mark_completed/mark_error) y no en _apply_status_color.
        self._refresh_card_style()
        if self.is_draggable():
            self.setToolTip(self.tr("Arrastra este elemento a otra aplicación para importar todos sus archivos")
                            if hasattr(self, "tr") else
                            self.tr("Arrastra este elemento a otra aplicación para importar todos sus archivos"))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_press_pos = event.position().toPoint()
            self.selection_requested.emit(self, event.modifiers())
            # Se acepta para que el clic no siga subiendo hasta ActivityPanel, que lo
            # interpreta como "clic en zona vacía" y limpiaría la selección recién hecha.
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_press_pos is None or not (event.buttons() & Qt.LeftButton):
            return super().mouseMoveEvent(event)
        if (event.position().toPoint() - self._drag_press_pos).manhattanLength() < QApplication.startDragDistance():
            return super().mouseMoveEvent(event)
        # Se limpia ANTES de emitir: el arrastre abre un bucle de eventos anidado y el
        # gesto no debe poder relanzarse desde dentro de él.
        self._drag_press_pos = None
        if self.is_draggable():
            self.drag_requested.emit(self)

    def mouseReleaseEvent(self, event):
        self._drag_press_pos = None
        super().mouseReleaseEvent(event)

    def _settle_progress_bar(self, percent):
        """Detiene la animación si la barra quedó intermitente.

        Una fila que termina (bien o mal) con la barra en rango 0-0 se quedaría
        parpadeando para siempre: pasa al acabar una recodificación sin duración
        conocida, y al fallar durante la espera previa al primer byte."""
        if self.progress_bar.maximum() != 0:
            return
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(percent)
        self.percent_lbl.setText(f"{percent}%" if percent else "")

    def mark_completed(self, filepath=None):
        """Marca este item como completado y muestra el botón de carpeta."""
        self._is_completed = True
        if filepath:
            self.downloaded_filepath = filepath
            self.add_output_files([filepath])
        if not self._is_alive():
            return
        self._settle_progress_bar(100)
        self._update_drag_affordance()
        self.refresh_reveal_button()
        self.state_changed.emit(self)

    def refresh_reveal_button(self):
        """Muestra el botón de carpeta si esta fila dejó un archivo en disco.

        Va aparte de mark_completed porque una recodificación fallida deja el original
        recuperado: la fila es un error, pero el archivo existe y el usuario tiene que
        poder llegar a él."""
        if not self._is_alive() or not self.downloaded_filepath:
            return
        if os.path.exists(self.downloaded_filepath):
            self.btn_reveal.show()
        else:
            # Si las extensiones temporales cambiaron al fusionar con ffmpeg, verificar el directorio destino
            parent = os.path.dirname(self.downloaded_filepath)
            if parent and os.path.exists(parent):
                self.btn_reveal.show()

    def mark_error(self):
        """Marca este item como error."""
        self._is_error = True
        self.set_selected(False)
        self._update_drag_affordance()
        if self._is_alive():
            self._settle_progress_bar(0)
            # El rojo se fija por ESTADO, no por el texto del estado: una fila fallida se
            # pinta igual diga "Error", "Error al recodificar" o nada.
            self._set_status_color(self._TOKEN_ERROR)
            self.state_changed.emit(self)

    # Mismo mapeo estado -> token de tema que usa QueueItemCard en queue_panel.py,
    # para que Modo Rápido y LOTES se vean consistentes.
    _STATUS_TOKENS = {
        QT_TRANSLATE_NOOP("QuickDownloadRow", "Completado"): ("estado_exito", "#40d66b"),
        QT_TRANSLATE_NOOP("QuickDownloadRow", "Error"): ("estado_error", "#ff6b5f"),
        QT_TRANSLATE_NOOP("QuickDownloadRow", "Cancelado"): ("estado_error", "#ff6b5f"),
        QT_TRANSLATE_NOOP("QuickDownloadRow", "Omitido"): ("estado_aviso", "#d8c94a"),
        QT_TRANSLATE_NOOP("QuickDownloadRow", "Descargando"): ("estado_progreso", "#3498db"),
        QT_TRANSLATE_NOOP("QuickDownloadRow", "Analizando"): ("estado_progreso", "#3498db"),
        QT_TRANSLATE_NOOP("QuickDownloadRow", "Procesando"): ("estado_progreso", "#3498db"),
        QT_TRANSLATE_NOOP("QuickDownloadRow", "Preparando"): ("estado_progreso", "#3498db"),
        QT_TRANSLATE_NOOP("QuickDownloadRow", "Recodificando"): ("estado_progreso", "#3498db"),
        QT_TRANSLATE_NOOP("QuickDownloadRow", "En espera"): ("estado_espera", "#aaaaaa"),
        QT_TRANSLATE_NOOP("QuickDownloadRow", "En cola"): ("estado_espera", "#aaaaaa"),
    }

    @staticmethod
    def _blend(base_hex, tint_hex, ratio):
        """Mezcla `ratio` de tint sobre base y devuelve un '#rrggbb'. Los tokens de tema
        son cadenas de color, así que la mezcla se hace aquí en vez de con rgba() en la
        hoja de estilo (que se compondría contra el panel, no contra el fondo del tema)."""
        try:
            base, tint = QColor(base_hex), QColor(tint_hex)
            if not base.isValid() or not tint.isValid():
                return base_hex
            mix = lambda b, t: int(round(b + (t - b) * ratio))
            return QColor(mix(base.red(), tint.red()),
                          mix(base.green(), tint.green()),
                          mix(base.blue(), tint.blue())).name()
        except Exception:
            return base_hex

    def _refresh_card_style(self):
        """Único punto que pinta la tarjeta. El borde lo decide el estado
        (_apply_status_color) y el fondo, si la fila está seleccionada para arrastrar
        (set_selected) -- antes cada uno reescribía la hoja completa por su cuenta y el
        último en escribir borraba lo del otro."""
        border = self._status_color or get_theme_token('borde', '#2d2d2d')
        base = get_theme_token('fondo_principal', '#121212')
        if self._is_selected:
            background = get_theme_token('fondo_hover', '#2a2a2a')
            border_width = 2
        elif self.is_draggable():
            # Una fila terminada se tiñe del verde de éxito para que se lea de un
            # vistazo cuál ya se puede arrastrar a otra aplicación.
            background = self._blend(base, border, 0.14)
            border_width = 1
        else:
            background = base
            border_width = 1
        self.setStyleSheet(f"""
            QFrame#queueItemCard {{
                background-color: {background};
                border: {border_width}px solid {border};
                border-radius: 6px;
            }}
            QLabel {{
                color: {get_theme_token('texto_principal', '#dddddd')};
            }}
            {progress_bar_qss()}
        """)

    _TOKEN_ERROR = ("estado_error", "#ff6b5f")
    _TOKEN_ESPERA = ("estado_espera", "#aaaaaa")

    @classmethod
    def _resolve_status_token(cls, status):
        """El mapa exigía coincidencia EXACTA, así que los estados compuestos que sí usa
        el controlador ("Error al recodificar", "Recodificación cancelada",
        "Recodificando 2 de 5...") caían al gris de espera: un ítem que fallaba no se
        pintaba de rojo. Se resuelve por prefijo, y el error/cancelado se detecta por
        palabra para no depender de la redacción exacta."""
        texto = (status or "").strip()
        if texto in cls._STATUS_TOKENS:
            return cls._STATUS_TOKENS[texto]
        bajo = texto.lower()
        if bajo.startswith("error") or "cancel" in bajo or "fall" in bajo:
            return cls._TOKEN_ERROR
        for clave, valor in cls._STATUS_TOKENS.items():
            if bajo.startswith(clave.lower()):
                return valor
        return cls._TOKEN_ESPERA

    def _apply_status_color(self, status):
        self._set_status_color(self._resolve_status_token(status))

    def _set_status_color(self, token_default):
        token, default = token_default
        color = get_theme_token(token, default)
        self.status_lbl.setStyleSheet(f"color: {color}; font-size: 10px; font-weight: bold;")
        self._status_color = color
        self._refresh_card_style()

    def update_progress(self, percent, info="", status=None):
        if not self._is_alive():
            return
        percent = max(0, min(100, int(percent)))
        if percent > 0:
            self._has_real_progress = True
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(percent)
        self.percent_lbl.setText(f"{percent}%")
        if info:
            self.info_lbl.setText(info)
            self.info_lbl.setToolTip(info)
        if status:
            self.status_lbl.setText(status)
            self._apply_status_color(status)
        self.state_changed.emit(self)

    def set_busy(self, status, info=""):
        """Barra indeterminada para un trabajo en curso del que no se puede calcular
        porcentaje.

        La usa la recodificación cuando no se logró averiguar la duración del medio: sin
        duración, ffmpeg no puede reportar avance, y dejar la barra clavada en 0% durante
        un minuto parece que la app se colgó. Una barra en movimiento comunica lo que de
        verdad está pasando: hay trabajo, pero no hay porcentaje."""
        if not self._is_alive():
            return
        self.progress_bar.setRange(0, 0)
        self.percent_lbl.setText("")
        if info:
            self.info_lbl.setText(info)
            self.info_lbl.setToolTip(info)
        if status:
            self.status_lbl.setText(status)
            self._apply_status_color(status)
        self.state_changed.emit(self)

    _ESTADOS_EN_MARCHA = ("Descargando", "Procesando", "Analizando", "Preparando",
                          "Recodificando")

    def set_waiting(self, status=None):
        """Barra intermitente mientras se espera la PRIMERA señal real de progreso.

        En YouTube pasan varios segundos entre que se lanza la descarga y llega el
        primer byte (negociación de formatos, resolución de la URL del stream). Durante
        ese hueco no hay ningún porcentaje que mostrar, y una barra clavada en 0 parece
        que la app no está haciendo nada. Intermitente comunica lo cierto: está
        trabajando, todavía no se puede medir.

        No pisa nada: si la fila ya recibió progreso real, o terminó, o falló, no hace
        nada. Y respeta el texto de estado si ya dice en qué anda."""
        if not self._is_alive() or self._has_real_progress or self._is_completed or self._is_error:
            return
        actual = self.status_lbl.text().strip()
        # "En cola" lo pone el controlador a propósito cuando la tanda supera la
        # concurrencia máxima: ahí de verdad no se está haciendo nada con esta fila y
        # una barra en movimiento mentiría.
        if actual == (self.tr("En cola") if hasattr(self, "tr") else "En cola"):
            return
        en_marcha = any(actual.startswith(e) for e in self._ESTADOS_EN_MARCHA)
        destino = status or (actual if en_marcha
                             else (self.tr("Preparando") if hasattr(self, "tr") else "Preparando"))
        # Ya está como debe: no repetir el emit y no reiniciar la animación de la barra.
        if self.progress_bar.maximum() == 0 and self.status_lbl.text() == destino:
            return
        self.set_busy(destino)

    def set_fragment_progress(self, fragment_index, fragment_count, phase="downloading"):
        """
        Estado especial para ítems con más de un fragmento: la barra queda
        intermitente (no representa un % real) y el texto avisa en qué
        fragmento va, en vez de un porcentaje engañoso.
        """
        if not self._is_alive():
            return
        self.progress_bar.setRange(0, 0)
        self.percent_lbl.setText("")
        verb = self.tr("Cortando") if phase == "cutting" else self.tr("Descargando")
        msg = self.tr("{0} fragmento {1} de {2}").format(verb, fragment_index, fragment_count)
        self.info_lbl.setText(msg)
        self.info_lbl.setToolTip(msg)
        self.status_lbl.setText(self.tr("Procesando"))
        self._apply_status_color("Procesando")

    def update_metadata_from_dict(self, info):
        if not info or not self._is_alive():
            return
            
        title = info.get("title")
        if title and (self.original_title == (self.tr("Descarga directa") if hasattr(self, "tr") else "Descarga directa") or not self.original_title):
            self.original_title = title
            metrics = self.title_lbl.fontMetrics()
            elided = metrics.elidedText(title, Qt.ElideRight, self.title_lbl.width() or 300)
            self.title_lbl.setText(elided)
            self.title_lbl.setToolTip(title)
            
        duration_sec = info.get("duration")
        if duration_sec:
            # Se guarda además de pintarla: la recodificación posterior necesita la
            # duración en segundos para poder calcular su porcentaje, y volver a
            # sondearla con ffprobe sobre el archivo recién descargado no funciona
            # (ver _start_post_download_recode en download_controller.py).
            try:
                self.media_duration_sec = float(duration_sec)
            except (TypeError, ValueError):
                pass
        if duration_sec and not self._duration_set:
            self.thumb_widget.set_duration(duration_sec)
            self._duration_set = True
            
        if not self._thumb_loaded and not self._thumb_loading:
            thumb_url = None
            thumbs = info.get("thumbnails") or []
            valid = [t for t in thumbs if t.get("url")]
            if valid:
                valid.sort(key=lambda t: (t.get("width") or 0) * (t.get("height") or 0))
                thumb_url = valid[0]["url"]
            else:
                thumb_url = info.get("thumbnail")
                
            if thumb_url:
                self.load_thumbnail(thumb_url)

    def load_thumbnail(self, url):
        if not url or self._thumb_loaded or self._thumb_loading:
            return
        self._thumb_loading = True
        
        fallback_urls = []
        match = re.match(r'(https?://i\.ytimg\.com/vi/[^/]+/)([^?]+)', url)
        if match:
            base = match.group(1)
            primary = base + "default.jpg"
            fallback_urls = [base + "mqdefault.jpg", url]
        else:
            primary = url
            
        self.thumb_thread = ThumbnailLoaderThread(primary, fallback_urls=fallback_urls)
        
        def on_finished(content, error):
            self._thumb_loading = False
            if content:
                self._thumb_loaded = True
                img = QImage.fromData(content)
                if not img.isNull():
                    pix = QPixmap.fromImage(img)
                    self.thumb_widget.set_pixmap(pix)
            if self.thumb_thread:
                self.thumb_thread.deleteLater()
            self.thumb_thread = None
            
        self.thumb_thread.finished.connect(on_finished)
        self.thumb_thread.start()

    def destroy_row(self):
        if self.thumb_thread:
            try:
                self.thumb_thread.finished.disconnect()
            except Exception:
                pass
            try:
                if self.thumb_thread.isRunning():
                    self.thumb_thread.quit()
                    self.thumb_thread.wait()
            except RuntimeError:
                pass
            self.thumb_thread = None


class PlaylistGroupRow(QFrame):
    """Tarjeta contenedora de una playlist: una sola entrada en la lista que agrupa
    dentro las filas de sus ítems.

    Antes, descargar una playlist de 9 vídeos metía 9 tarjetas sueltas en la lista y no
    se distinguía dónde empezaba y acababa cada tanda. Esta tarjeta muestra el conjunto
    ("3 de 9") y guarda las filas individuales dentro, plegadas.

    Se pliega en vez de sustituir a las filas a propósito: el reparto de progreso por
    ítem (_resolve_target_rows en download_controller.py) sigue trabajando contra las
    MISMAS filas de siempre, así que este widget no cambia nada del pipeline de descarga
    -- solo dónde se dibujan. Y desplegándola se sigue viendo qué ítem concreto falló,
    que con los 403 de YouTube es justo lo que hace falta.
    """
    close_requested = Signal(object)   # (grupo) al pulsar la X del grupo
    drag_requested = Signal(object)    # (grupo) al arrastrar la tarjeta plegada

    def __init__(self, title, item_count, parent=None):
        super().__init__(parent)
        self.setObjectName("queueItemCard")
        self.original_title = title
        self._rows = []
        self._expanded = False
        self._drag_press_pos = None
        # refresh_summary puede provocar un set_waiting en una fila, y esa fila emite
        # state_changed, que vuelve a refresh_summary. Sin este cerrojo sería recursión
        # infinita.
        self._refreshing = False
        self._init_ui(title, item_count)

    # ── Construcción ────────────────────────────────────────────────────────
    def _init_ui(self, title, item_count):
        icon_dir = os.path.join(get_src_dir(), "assets", "icons", "svg")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)

        self.btn_toggle = QPushButton()
        self.btn_toggle.setFixedSize(24, 24)
        self.btn_toggle.setCursor(Qt.PointingHandCursor)
        self.btn_toggle.setStyleSheet(f"""
            QPushButton {{ background-color: transparent; border: none; border-radius: 6px; }}
            QPushButton:hover {{ background-color: {get_theme_token('fondo_hover', '#2a2a2a')}; }}
        """)
        self._icon_collapsed = os.path.join(icon_dir, "arrow_right.svg")
        self._icon_expanded = os.path.join(icon_dir, "arrow_drop_down.svg")
        self.btn_toggle.clicked.connect(self.toggle)
        header.addWidget(self.btn_toggle)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        self.title_lbl = QLabel(title)
        self.title_lbl.setToolTip(title)
        self.title_lbl.setStyleSheet(
            f"color: {get_theme_token('texto_principal', '#dddddd')}; font-weight: bold;")
        self.status_lbl = QLabel(self.tr("{0} de {1}").format(0, item_count))
        self.status_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.status_lbl.setStyleSheet(
            f"color: {get_theme_token('texto_secundario', '#aaaaaa')}; font-size: 10px;")
        title_row.addWidget(self.title_lbl, 1)
        title_row.addWidget(self.status_lbl)
        text_col.addLayout(title_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        # La hoja va sobre la barra, no sobre la tarjeta: puesta en la tarjeta se
        # heredaría también a las filas hijas, que ya pintan la suya.
        self.progress_bar.setStyleSheet(progress_bar_qss())
        text_col.addWidget(self.progress_bar)

        header.addLayout(text_col, 1)

        self.btn_close = QPushButton()
        self.btn_close.setFixedSize(24, 24)
        self.btn_close.setToolTip(self.tr("Quitar la playlist de la lista"))
        self.btn_close.setStyleSheet(f"""
            QPushButton {{ background-color: transparent; border: none; border-radius: 6px; padding: 2px; }}
            QPushButton:hover {{ background-color: {get_theme_token('fondo_hover', '#2a2a2a')}; }}
        """)
        _close_icon = os.path.join(icon_dir, "close.svg")
        if os.path.exists(_close_icon):
            self.btn_close.setIcon(QIcon(_close_icon))
            self.btn_close.setIconSize(QSize(14, 14))
        else:
            self.btn_close.setText("✕")
        self.btn_close.clicked.connect(lambda: self.close_requested.emit(self))
        header.addWidget(self.btn_close, 0, Qt.AlignTop)

        outer.addLayout(header)

        # Contenedor de las filas hijas, oculto mientras esté plegada
        self.items_container = QWidget(self)
        self.items_layout = QVBoxLayout(self.items_container)
        self.items_layout.setContentsMargins(28, 4, 0, 0)
        self.items_layout.setSpacing(6)
        self.items_container.setVisible(False)
        outer.addWidget(self.items_container)

        self._refresh_toggle_icon()

    # ── Filas hijas ─────────────────────────────────────────────────────────
    def add_row(self, row):
        self._rows.append(row)
        self.items_layout.addWidget(row)
        row.state_changed.connect(lambda _r=None: self.refresh_summary())
        self.refresh_summary()

    def rows(self):
        return list(self._rows)

    def remove_row(self, row):
        """Saca una fila del grupo cuando el usuario pulsa la X de ESE ítem.

        Sin esto la tarjeta seguía contando la fila borrada ("0 de 4" con 3 ítems), y el
        widget quedaba en items_layout apuntando a un objeto ya destruido."""
        if row not in self._rows:
            return
        self._rows.remove(row)
        try:
            self.items_layout.removeWidget(row)
        except RuntimeError:
            pass
        self.refresh_summary()

    def is_empty(self) -> bool:
        return not self._rows

    # ── Plegado ─────────────────────────────────────────────────────────────
    def toggle(self):
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool):
        self._expanded = bool(expanded)
        self.items_container.setVisible(self._expanded)
        self._refresh_toggle_icon()

    def is_expanded(self) -> bool:
        return self._expanded

    # ── Arrastre de la playlist entera ──────────────────────────────────────
    def draggable_rows(self):
        return [r for r in self._rows if hasattr(r, "is_draggable") and r.is_draggable()]

    def is_draggable(self) -> bool:
        return bool(self.draggable_rows())

    def _update_drag_affordance(self):
        """Arrastrar desde la tarjeta plegada evita tener que desplegarla y seleccionar
        los nueve ítems a mano para llevarlos al editor."""
        arrastrable = self.is_draggable()
        self.setCursor(Qt.OpenHandCursor if arrastrable else Qt.ArrowCursor)
        # El cursor se hereda: sin esto, las filas de dentro que aún no terminaron
        # mostrarían la mano de "listo para arrastrar" sin estarlo.
        self.items_container.setCursor(Qt.ArrowCursor)
        self.setToolTip(
            (self.tr("Arrastra la playlist a otra aplicación para importar sus archivos")
             if hasattr(self, "tr") else
             self.tr("Arrastra la playlist a otra aplicación para importar sus archivos"))
            if arrastrable else "")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_press_pos = event.position().toPoint()
            # Se acepta para que el clic no suba hasta ActivityPanel, que lo leería como
            # "clic en zona vacía" y limpiaría la selección de filas.
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_press_pos is None or not (event.buttons() & Qt.LeftButton):
            return super().mouseMoveEvent(event)
        if (event.position().toPoint() - self._drag_press_pos).manhattanLength() < QApplication.startDragDistance():
            return super().mouseMoveEvent(event)
        self._drag_press_pos = None
        if self.is_draggable():
            self.drag_requested.emit(self)

    def mouseReleaseEvent(self, event):
        self._drag_press_pos = None
        super().mouseReleaseEvent(event)

    def _refresh_toggle_icon(self):
        path = self._icon_expanded if self._expanded else self._icon_collapsed
        if os.path.exists(path):
            self.btn_toggle.setIcon(QIcon(path))
            self.btn_toggle.setIconSize(QSize(16, 16))
        else:
            self.btn_toggle.setText("▾" if self._expanded else "▸")
        self.btn_toggle.setToolTip(
            self.tr("Contraer") if self._expanded else self.tr("Ver los elementos"))

    # ── Resumen agregado ────────────────────────────────────────────────────
    def _row_percent(self, row) -> int:
        """Progreso de una fila hija, normalizado a 0-100.

        Una fila con barra indeterminada (rango 0-0, ej. recodificando sin duración
        conocida) no aporta un porcentaje real: cuenta como 0 hasta que termine, en vez
        de leer un valor de la barra que ahí no significa nada."""
        if getattr(row, "_is_completed", False):
            return 100
        if getattr(row, "_is_error", False):
            return 0
        try:
            if row.progress_bar.maximum() == 0:
                return 0
            return int(row.progress_bar.value())
        except Exception:
            return 0

    @staticmethod
    def _is_indeterminate(row) -> bool:
        try:
            return row.progress_bar.maximum() == 0
        except Exception:
            return False

    def _mark_next_pending_busy(self):
        """Deja intermitente la fila que está a punto de descargarse.

        yt-dlp va de uno en uno: entre que termina un ítem y llega el primer byte del
        siguiente pasan varios segundos sin ninguna señal. Sin esto, la siguiente
        tarjeta se queda en 0% y parece atascada."""
        for row in self._rows:
            if getattr(row, "_is_completed", False) or getattr(row, "_is_error", False):
                continue
            # El primero que sigue vivo manda: si ya está avanzando de verdad, nadie
            # más está "preparando".
            if not getattr(row, "_has_real_progress", False) and hasattr(row, "set_waiting"):
                row.set_waiting()
            return

    def refresh_summary(self):
        total = len(self._rows)
        if not total or self._refreshing:
            return
        self._refreshing = True
        try:
            completados = sum(1 for r in self._rows if getattr(r, "_is_completed", False))
            con_error = sum(1 for r in self._rows if getattr(r, "_is_error", False))

            texto = self.tr("{0} de {1}").format(completados, total)
            if con_error:
                texto += self.tr(" · {0} con error").format(con_error)
            self.status_lbl.setText(texto)

            self._update_drag_affordance()
            self._mark_next_pending_busy()

            # Mientras ningún ítem haya reportado avance real ni haya terminado, no hay
            # nada que promediar: la barra del grupo va intermitente, igual que la de la
            # fila. Un 0% fijo durante el arranque de YouTube parece que no pasa nada.
            hay_avance = (completados or con_error
                          or any(getattr(r, "_has_real_progress", False) for r in self._rows))
            if not hay_avance:
                # Solo parpadea si algún ítem está de verdad esperando su primer byte.
                # Una tanda entera "En cola" no se mueve: ahí no pasa nada todavía.
                if any(self._is_indeterminate(r) for r in self._rows):
                    self.progress_bar.setRange(0, 0)
                else:
                    self.progress_bar.setRange(0, 100)
                    self.progress_bar.setValue(0)
                return

            # La barra promedia el avance real de los ítems, no solo cuántos terminaron:
            # así se mueve durante la descarga de cada uno y no a saltos de 1/9.
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(
                int(sum(self._row_percent(r) for r in self._rows) / total))
        finally:
            self._refreshing = False

    def destroy_row(self):
        """Contraparte de QuickDownloadRow.destroy_row: el panel la llama al limpiar la
        lista, y aquí hay que soltar también las filas hijas."""
        for row in self._rows:
            if hasattr(row, "destroy_row"):
                row.destroy_row()
        self._rows = []
