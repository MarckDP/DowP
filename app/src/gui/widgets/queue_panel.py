# src/gui/widgets/queue_panel.py
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QProgressBar, QFrame, QPushButton,
    QGraphicsOpacityEffect, QSizePolicy
)
from PySide6.QtCore import Qt, QVariantAnimation, QEasingCurve, Signal, QTimer
from PySide6.QtGui import QColor, QIcon, QPixmap, QPainter, QCursor
from gui.styles import get_theme_token
from core.logger.logger_manager import logger
from core.utils.paths import get_src_dir

ICONS_DIR = os.path.join(get_src_dir(), "assets", "icons", "svg")

def get_colored_icon(filename, color_hex, size=16):
    """
    Carga un ícono SVG desde assets/icons/svg por nombre de archivo y lo tiñe del
    color dado. Usa get_src_dir() (no una ruta relativa) para que funcione tanto
    corriendo desde el código fuente como dentro de un .exe compilado, donde el
    directorio de trabajo actual no es necesariamente la raíz del repo.
    """
    path = os.path.join(ICONS_DIR, filename)
    pixmap = QPixmap(path)
    if pixmap.isNull():
        return QIcon()
    pixmap = pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    painter = QPainter(pixmap)
    painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(), QColor(color_hex))
    painter.end()
    
    icon = QIcon()
    icon.addPixmap(pixmap, QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(pixmap, QIcon.Mode.Normal, QIcon.State.On)
    icon.addPixmap(pixmap, QIcon.Mode.Selected, QIcon.State.Off)
    icon.addPixmap(pixmap, QIcon.Mode.Selected, QIcon.State.On)
    icon.addPixmap(pixmap, QIcon.Mode.Active, QIcon.State.Off)
    icon.addPixmap(pixmap, QIcon.Mode.Active, QIcon.State.On)
    return icon

class QueueItemCard(QFrame):
    """
    Tarjeta individual que representa una descarga en la cola.
    Muestra título, progreso, porcentaje y estado actual.
    """
    card_clicked = Signal(str)
    delete_requested = Signal(str)
    move_up_requested = Signal(str)
    move_down_requested = Signal(str)
    reset_requested = Signal(str)
    configure_requested = Signal(str)
    open_folder_requested = Signal(str)
    drag_started = Signal(str)
    # Arrastre del RESULTADO hacia otra aplicación (no el de reordenar la cola): se
    # emite en vez de drag_started cuando la tarjeta ya terminó todo su proceso.
    file_drag_requested = Signal(str)

    DRAG_THRESHOLD = 8

    def __init__(self, title, job_id, parent=None, is_playlist=False):
        super().__init__(parent)
        self.job_id = job_id
        self.is_playlist = is_playlist
        self._is_selected = False
        self._current_border = get_theme_token('borde', '#2d2d2d')
        self._press_pos = None
        self._dragging = False
        # Una tarjeta terminada se arrastra a otra aplicación con todo lo que produjo;
        # una en curso se arrastra dentro de la cola para reordenarla. Con
        # recodificación pedida, "terminada" incluye que el recode haya terminado
        # (lo marca DownloadController, ver set_recode_pending).
        self._is_completed = False
        self._recode_pending = False
        self._raw_title = title
        self._raw_speed_text = ""
        self.setObjectName("queueItemCard")
        self.init_ui(title)

    def set_selected(self, selected: bool):
        self._is_selected = selected
        self._apply_style()

    def is_drag_ready(self) -> bool:
        """Solo cuando el proceso COMPLETO terminó bien: si se pidió recodificación, no
        basta con que la descarga haya terminado."""
        return bool(self._is_completed and not self._recode_pending)

    def set_completed(self, completed: bool):
        self._is_completed = bool(completed)
        self._update_drag_affordance()

    def set_recode_pending(self, pending: bool):
        """Llamado por DownloadController al encolar/resolver una recodificación
        post-descarga: mientras esté pendiente, la tarjeta ya dice "Completado" (la
        descarga sí terminó) pero arrastrarla entregaría el archivo a medio hacer."""
        self._recode_pending = bool(pending)
        self._update_drag_affordance()

    def _update_drag_affordance(self):
        ready = self.is_drag_ready()
        self.setCursor(Qt.OpenHandCursor if ready else Qt.ArrowCursor)
        if ready:
            self.setToolTip(self.tr("Arrastra esta tarjeta a otra aplicación para llevarte todos sus archivos"))
        else:
            self.setToolTip("")

    def _apply_style(self):
        bg_color = get_theme_token('fondo_principal', '#121212')
        acento = get_theme_token('acento_primario', '#B9E640')
        if self._is_selected:
            new_style = f"""
                QFrame#queueItemCard {{
                    background-color: {get_theme_token('fondo_hover', '#1a1a1a')};
                    border: 1px solid {acento};
                    border-radius: 6px;
                }}
            """
        else:
            new_style = f"""
                QFrame#queueItemCard {{
                    background-color: {bg_color};
                    border: 1px solid {self._current_border};
                    border-radius: 6px;
                }}
                QFrame#queueItemCard:hover {{
                    background-color: {get_theme_token('fondo_hover', '#1a1a1a')};
                }}
            """
        
        # Solo re-estilizar si el CSS realmente cambió
        if self.styleSheet() == new_style:
            return
        
        self.setStyleSheet(new_style)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()
        
    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            self._press_pos = event.position().toPoint()
            self._dragging = False

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if self._press_pos is None or self._dragging:
            return
        if not (event.buttons() & Qt.LeftButton):
            return
        delta = (event.position().toPoint() - self._press_pos).manhattanLength()
        if delta >= self.DRAG_THRESHOLD:
            if self.is_drag_ready():
                # Reordenar una tarjeta ya terminada no significa nada (sus botones de
                # subir/bajar están ocultos justamente por eso), así que ese gesto pasa
                # a ser el arrastre del resultado hacia afuera de la app. Se limpia
                # ANTES de emitir: el QDrag abre un bucle de eventos anidado y el gesto
                # no debe poder relanzarse desde dentro de él.
                self._press_pos = None
                self.file_drag_requested.emit(self.job_id)
                return
            self._dragging = True
            self.drag_started.emit(self.job_id)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() != Qt.LeftButton:
            return
        # Si nunca se superó el umbral de arrastre, es un click normal (selección).
        # Si se arrastró, QueuePanel ya tiene el mouse "grabbed" y este evento no
        # llegará aquí hasta soltar (ver reset_drag_state, llamado desde el panel).
        if self._press_pos is not None and not self._dragging:
            self.card_clicked.emit(self.job_id)
        self._press_pos = None

    def set_drag_opacity(self, dragging: bool):
        """Atenúa la tarjeta mientras se arrastra, para señalar cuál se está moviendo."""
        if dragging:
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(0.4)
            self.setGraphicsEffect(effect)
        else:
            self.setGraphicsEffect(None)

    def reset_drag_state(self):
        """Llamado por QueuePanel cuando termina un arrastre (soltado o cancelado)."""
        self._press_pos = None
        self._dragging = False
        self.set_drag_opacity(False)
        
    def init_ui(self, title):
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        
        # Fila superior: Título e Indicador de Estado
        top_layout = QHBoxLayout()
        
        self.title_lbl = QLabel(title)
        self.title_lbl.setStyleSheet(f"color: {get_theme_token('texto_principal', '#ffffff')}; font-weight: bold;")
        self.title_lbl.setWordWrap(False)
        self.title_lbl.setMinimumWidth(0)
        self.title_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.update_title(title)
        
        self.status_lbl = QLabel(self.tr("En espera"))
        self.status_lbl.setStyleSheet(f"color: {get_theme_token('texto_secundario', '#aaaaaa')}; font-size: 10px;")
        self.status_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.status_lbl.setMinimumWidth(0)
        self.status_lbl.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        
        # Botones de control
        self.btn_up = QPushButton()
        self.btn_up.setIcon(get_colored_icon('arrow_upward_alt.svg', '#888888', size=12))
        self.btn_up.setToolTip(self.tr("Mover arriba"))
        self.btn_up.setFixedSize(16, 16)
        self.btn_up.setStyleSheet("border: none; background: transparent; padding: 0px; min-width: 0px; min-height: 0px;")
        self.btn_up.clicked.connect(lambda: self.move_up_requested.emit(self.job_id))

        self.btn_down = QPushButton()
        self.btn_down.setIcon(get_colored_icon('arrow_downward_alt.svg', '#888888', size=12))
        self.btn_down.setToolTip(self.tr("Mover abajo"))
        self.btn_down.setFixedSize(16, 16)
        self.btn_down.setStyleSheet("border: none; background: transparent; padding: 0px; min-width: 0px; min-height: 0px;")
        self.btn_down.clicked.connect(lambda: self.move_down_requested.emit(self.job_id))

        self.btn_close = QPushButton()
        self.btn_close.setIcon(get_colored_icon('close.svg', '#e74c3c'))
        self.btn_close.setToolTip(self.tr("Eliminar de la cola"))
        self.btn_close.setFixedSize(16, 16)
        self.btn_close.setStyleSheet("border: none; background: transparent; padding: 0px; min-width: 0px; min-height: 0px;")
        self.btn_close.clicked.connect(lambda: self.delete_requested.emit(self.job_id))
        
        self.btn_reset = QPushButton()
        acento_color = get_theme_token('acento_primario', '#B9E640')
        self.btn_reset.setIcon(get_colored_icon('arrow_back.svg', acento_color))
        self.btn_reset.setToolTip(self.tr("Restaurar descarga"))
        self.btn_reset.setFixedSize(16, 16)
        self.btn_reset.setStyleSheet("border: none; background: transparent; padding: 0px; min-width: 0px; min-height: 0px;")
        self.btn_reset.clicked.connect(lambda: self.reset_requested.emit(self.job_id))
        self.btn_reset.hide()

        self.btn_folder = QPushButton()
        self.btn_folder.setIcon(get_colored_icon('folder_open.svg', acento_color))
        self.btn_folder.setToolTip(self.tr("Abrir carpeta contenedora"))
        self.btn_folder.setFixedSize(16, 16)
        self.btn_folder.setStyleSheet("border: none; background: transparent; padding: 0px; min-width: 0px; min-height: 0px;")
        self.btn_folder.clicked.connect(lambda: self.open_folder_requested.emit(self.job_id))
        self.btn_folder.hide()

        self.btn_configure = QPushButton()
        self.btn_configure.setIcon(get_colored_icon('settings.svg', '#888888'))
        self.btn_configure.setToolTip(self.tr("Configurar Playlist"))
        self.btn_configure.setFixedSize(16, 16)
        self.btn_configure.setStyleSheet("border: none; background: transparent; padding: 0px; min-width: 0px; min-height: 0px;")
        self.btn_configure.clicked.connect(lambda: self.configure_requested.emit(self.job_id))
        if not self.is_playlist:
            self.btn_configure.hide()
        
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(2)
        controls_layout.addWidget(self.btn_configure)
        controls_layout.addWidget(self.btn_reset)
        controls_layout.addWidget(self.btn_folder)
        controls_layout.addWidget(self.btn_up)
        controls_layout.addWidget(self.btn_down)
        controls_layout.addWidget(self.btn_close)

        top_layout.addWidget(self.title_lbl, 1)
        top_layout.addWidget(self.status_lbl, 0)
        top_layout.addLayout(controls_layout)
        layout.addLayout(top_layout)
        
        # Barra de progreso compacta
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet(f"""
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
        """)
        layout.addWidget(self.progress_bar)
        
        # Fila inferior: Info adicional (velocidad / tamaño / porcentaje)
        info_layout = QHBoxLayout()
        
        self.info_lbl = QLabel("")
        self.info_lbl.setStyleSheet(f"color: {get_theme_token('texto_secundario', '#888888')}; font-size: 10px;")
        self.info_lbl.setMinimumWidth(0)
        self.info_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        
        self.percent_lbl = QLabel("0%")
        self.percent_lbl.setStyleSheet(f"color: {get_theme_token('acento_primario', '#B9E640')}; font-size: 10px; font-weight: bold;")
        self.percent_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        
        info_layout.addWidget(self.info_lbl, 1)
        info_layout.addWidget(self.percent_lbl)
        layout.addLayout(info_layout)
        
        # Aplicar borde y fondo usando tokens de color del tema
        self.setStyleSheet(f"""
            QFrame#queueItemCard {{
                background-color: {get_theme_token('fondo_principal', '#121212')};
                border: 1px solid {get_theme_token('borde', '#2d2d2d')};
                border-radius: 6px;
            }}
        """)

    def _update_elided_title(self):
        if not hasattr(self, '_raw_title') or not self._raw_title:
            return
        if not hasattr(self, 'title_lbl'):
            return
        ctrl_w = 0
        for btn in (getattr(self, 'btn_configure', None),
                    getattr(self, 'btn_reset', None),
                    getattr(self, 'btn_folder', None),
                    getattr(self, 'btn_up', None),
                    getattr(self, 'btn_down', None),
                    getattr(self, 'btn_close', None)):
            if btn and btn.isVisible():
                ctrl_w += btn.width() + 2
        
        status_w = self.status_lbl.fontMetrics().boundingRect(self.status_lbl.text()).width() if (hasattr(self, 'status_lbl') and self.status_lbl.text()) else 0
        if status_w > 0:
            status_w += 6
        
        card_w = self.width() if self.width() > 30 else (self.parentWidget().width() if (self.parentWidget() and self.parentWidget().width() > 30) else 240)
        avail_w = max(20, card_w - ctrl_w - status_w - 26)
        metrics = self.title_lbl.fontMetrics()
        elided = metrics.elidedText(self._raw_title, Qt.ElideRight, avail_w)
        self.title_lbl.setText(elided)

    def _update_elided_info(self):
        if not hasattr(self, 'info_lbl'):
            return
        if not hasattr(self, '_raw_speed_text') or not self._raw_speed_text:
            self.info_lbl.setText("")
            return
        percent_w = self.percent_lbl.fontMetrics().boundingRect(self.percent_lbl.text()).width() if (hasattr(self, 'percent_lbl') and self.percent_lbl.text()) else 0
        if percent_w > 0:
            percent_w += 6
        card_w = self.width() if self.width() > 30 else (self.parentWidget().width() if (self.parentWidget() and self.parentWidget().width() > 30) else 240)
        avail_w = max(20, card_w - percent_w - 26)
        metrics = self.info_lbl.fontMetrics()
        elided = metrics.elidedText(self._raw_speed_text, Qt.ElideRight, avail_w)
        self.info_lbl.setText(elided)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_elided_title()
        self._update_elided_info()

    def update_progress(self, percent, speed_text=None, status_text=None):
        """Actualiza el progreso y la información de la descarga."""
        self.progress_bar.setValue(int(percent))
        self.percent_lbl.setText(f"{int(percent)}%")
        if speed_text is not None:
            self._raw_speed_text = speed_text
            self.info_lbl.setToolTip(speed_text)
            self._update_elided_info()
        if status_text:
            self.status_lbl.setText(status_text)
            self._update_elided_title()
            
            # Cambiar colores según estado
            border_color = get_theme_token('borde', '#2d2d2d')
            if status_text == self.tr("Completado"):
                color = get_theme_token('estado_exito', '#40d66b')
                self.status_lbl.setStyleSheet(f"color: {color}; font-size: 10px; font-weight: bold;")
                self.percent_lbl.setStyleSheet(f"color: {color}; font-size: 10px; font-weight: bold;")
                border_color = color
            elif status_text == self.tr("Error"):
                color = get_theme_token('estado_error', '#ff6b5f')
                self.status_lbl.setStyleSheet(f"color: {color}; font-size: 10px; font-weight: bold;")
                self.percent_lbl.setStyleSheet(f"color: {color}; font-size: 10px; font-weight: bold;")
                border_color = color
            elif status_text == self.tr("Cancelado"):
                color = get_theme_token('estado_error', '#ff6b5f')
                self.status_lbl.setStyleSheet(f"color: {color}; font-size: 10px; font-weight: bold;")
                self.percent_lbl.setStyleSheet(f"color: {color}; font-size: 10px; font-weight: bold;")
                border_color = color
            elif status_text == self.tr("Omitido"):
                color = get_theme_token('estado_aviso', '#d8c94a')
                self.status_lbl.setStyleSheet(f"color: {color}; font-size: 10px; font-weight: bold;")
                self.percent_lbl.setStyleSheet(f"color: {color}; font-size: 10px; font-weight: bold;")
                border_color = color
            elif status_text == self.tr("Descargando"):
                color = get_theme_token('estado_progreso', '#3498db')
                self.status_lbl.setStyleSheet(f"color: {color}; font-size: 10px;")
                border_color = color
            elif status_text.startswith(self.tr("Analizando")) or "Analizando" in status_text:
                color = get_theme_token('estado_progreso', '#3498db')
                self.status_lbl.setStyleSheet(f"color: {color}; font-size: 10px; font-weight: bold;")
                border_color = color
            elif status_text == self.tr("En espera"):
                # Reseteo completo: restaurar colores neutros, barra a 0, ocultar reset
                self.status_lbl.setStyleSheet(f"color: {get_theme_token('estado_espera', '#aaaaaa')}; font-size: 10px;")
                self.percent_lbl.setStyleSheet(f"color: {get_theme_token('acento_primario', '#B9E640')}; font-size: 10px; font-weight: bold;")
                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(0)
                self.percent_lbl.setText("0%")
                self._raw_speed_text = ""
                self.info_lbl.setText("")
                self.info_lbl.setToolTip("")
                self.status_lbl.setToolTip("")
                border_color = get_theme_token('borde', '#2d2d2d')

            if status_text in (self.tr("Completado"), self.tr("Error"), self.tr("Cancelado"), self.tr("Omitido")):
                self.btn_reset.show()
                self.btn_up.hide()
                self.btn_down.hide()
            else:
                self.btn_reset.hide()
                self.btn_up.show()
                self.btn_down.show()

            if status_text == self.tr("Completado"):
                self.btn_folder.show()
            else:
                self.btn_folder.hide()

            self._current_border = border_color
            self._apply_style()

    def update_title(self, title):
        """Actualiza el título con elipsis dinámica."""
        self._raw_title = title
        self.title_lbl.setToolTip(title)
        self._update_elided_title()


class QueuePanel(QWidget):
    """
    Panel colapsable que contiene la lista de descargas activas y completadas.
    Soporta animaciones de deslizamiento horizontal a 30% del ancho del padre.
    """
    card_clicked_signal = Signal(str)
    queue_action_signal = Signal(str)  # "cleared" o "reset"
    configure_playlist_signal = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_expanded = False
        self.setFixedWidth(0)
        self.setObjectName("QueuePanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        
        # Mapeo de job_id -> QueueItemCard
        self.cards = {}
        self._selected_card_id = None

        # Estado de arrastre para reordenar (ver _on_card_drag_started)
        self._dragging_job_id = None
        self._drag_insert_index = None
        self._autoscroll_direction = 0
        self._autoscroll_timer = QTimer(self)
        self._autoscroll_timer.setInterval(30)
        self._autoscroll_timer.timeout.connect(self._do_autoscroll)

        # Configurar animación
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.OutQuad)
        self._anim.valueChanged.connect(self._on_width_changed)
        self._anim.finished.connect(self._on_animation_finished)
        # Conectar al gestor de colas global (antes de init_ui para evitar AttributeError)
        from core.utils.queue_manager import get_queue_manager
        self.queue_mgr = get_queue_manager()
        self.queue_mgr.job_added.connect(self._on_job_added)
        self.queue_mgr.job_removed.connect(self._on_job_removed)
        self.queue_mgr.job_status_changed.connect(self._on_job_status_changed)
        self.queue_mgr.job_progress_changed.connect(self._on_job_progress_changed)
        self.queue_mgr.queue_reordered.connect(self._on_queue_reordered)
        
        self.init_ui()
        self.content_widget.hide()
        self.hide()

    def init_ui(self):
        # Layout principal de este widget (el cual se encoge/estira)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # Contenedor real para recortar adecuadamente el layout al colapsar
        self.content_widget = QWidget(self)
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(10, 10, 10, 10)
        self.content_layout.setSpacing(12)
        
        # Título del panel
        self.header_lbl = QLabel(self.tr("Cola de Descargas"))
        self.header_lbl.setStyleSheet(f"""
            color: {get_theme_token('acento_primario', '#B9E640')};
            font-size: 12px;
            font-weight: bold;
        """)
        self.header_lbl.setAlignment(Qt.AlignCenter)
        self.content_layout.addWidget(self.header_lbl)
        
        # Scroll Area para el listado de tarjetas
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("background: transparent; border: none;")
        
        # Contenedor interno del Scroll
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(8)
        self.scroll_layout.setAlignment(Qt.AlignTop)
        
        # Indicador de inserción para el arrastre de tarjetas (línea delgada que
        # marca dónde quedaría la tarjeta si se suelta ahí). Oculto por defecto.
        self._drag_indicator = QFrame(self.scroll_content)
        self._drag_indicator.setStyleSheet(
            f"background-color: {get_theme_token('estado_progreso', '#3498db')}; border-radius: 1px;"
        )
        self._drag_indicator.hide()

        # Mensaje de lista vacía
        self.empty_lbl = QLabel(self.tr("No hay descargas en cola"))
        self.empty_lbl.setStyleSheet(f"color: {get_theme_token('texto_secundario', '#888888')}; font-size: 11px;")
        self.empty_lbl.setAlignment(Qt.AlignCenter)
        self.scroll_layout.addWidget(self.empty_lbl)
        
        self.scroll.setWidget(self.scroll_content)
        self.content_layout.addWidget(self.scroll)
        
        # Botón limpiar lista
        self.btn_clear_list = QPushButton(self.tr("Limpiar Lista"))
        self.btn_clear_list.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: 1px solid {get_theme_token('borde', '#333')};
                border-radius: 6px;
                color: {get_theme_token('texto_secundario', '#aaa')};
                padding: 6px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: rgba(231, 76, 60, 0.15);
                border-color: #e74c3c;
                color: #ff6b6b;
            }}
            QPushButton:pressed {{
                background-color: rgba(231, 76, 60, 0.3);
                color: #ff8b8b;
            }}
        """)
        self.btn_clear_list.clicked.connect(self._on_clear_list_click)

        # Botón resetear estado
        self.btn_reset_all = QPushButton(self.tr("Resetear Estado"))
        self.btn_reset_all.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: 1px solid {get_theme_token('borde', '#333')};
                border-radius: 6px;
                color: {get_theme_token('texto_secundario', '#aaa')};
                padding: 6px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #2a2a2a;
                color: #fff;
            }}
        """)
        self.btn_reset_all.clicked.connect(self._on_reset_all_click)

        # Layout horizontal para los botones de acción global
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(4)
        actions_layout.addWidget(self.btn_clear_list)
        actions_layout.addWidget(self.btn_reset_all)

        self.content_layout.addLayout(actions_layout)

        self.main_layout.addWidget(self.content_widget)

    def toggle_expanded(self, parent_width):
        """Alterna el estado de expansión usando animaciones."""
        target_width = max(280, int(parent_width * 0.3))
        self._anim.stop()
        
        if self.is_expanded:
            # Colapsar
            self._anim.setStartValue(self.width())
            self._anim.setEndValue(0)
            self._anim.start()
            self.is_expanded = False
        else:
            # Expandir
            self.show()
            self.content_widget.show()
            self._anim.setStartValue(self.width())
            self._anim.setEndValue(target_width)
            self._anim.start()
            self.is_expanded = True

    def adjust_width(self, parent_width):
        """Ajusta instantáneamente el tamaño al redimensionar la ventana."""
        if self.is_expanded and self._anim.state() != QVariantAnimation.Running:
            target_width = max(280, int(parent_width * 0.3))
            self.setFixedWidth(target_width)
            if hasattr(self, 'content_widget'):
                self.content_widget.setFixedWidth(target_width)

    def add_download(self, title) -> QueueItemCard:
        """Añade una nueva descarga a la cola (obsoleto, usar QueueManager)."""
        self.empty_lbl.hide()
        card = QueueItemCard(title, self)
        self.scroll_layout.addWidget(card)
        return card

    def _on_job_added(self, job_id):
        job = self.queue_mgr.get_job(job_id)
        if not job:
            return
        # El QueueManager es compartido con Herramientas Multimedia (jobs "RECODE") - este
        # panel es especifico de Proceso Avanzado (descargas/playlists), asi que sin este
        # filtro aparecia una tarjeta fantasma por cada recodificacion encolada desde la
        # otra pestaña (ver conversacion: tambien contaminaba el progreso agregado y los
        # logs de DownloadController con jobs que no eran suyos).
        if job.job_type not in ("DOWNLOAD", "PLAYLIST"):
            return

        self.empty_lbl.hide()
            
        card = QueueItemCard(job.title, job.job_id, self, is_playlist=(job.job_type == "PLAYLIST"))
        
        # Conectar señales de la tarjeta
        card.card_clicked.connect(self._emit_card_clicked)
        card.delete_requested.connect(self.queue_mgr.remove_job)
        card.move_up_requested.connect(self.queue_mgr.move_job_up)
        card.move_down_requested.connect(self.queue_mgr.move_job_down)
        card.reset_requested.connect(self.queue_mgr.reset_job)
        card.configure_requested.connect(self.configure_playlist_signal.emit)
        card.open_folder_requested.connect(self._on_open_folder_requested)
        card.drag_started.connect(self._on_card_drag_started)
        card.file_drag_requested.connect(self._on_card_file_drag)
        
        self.scroll_layout.addWidget(card)
        self.cards[job_id] = card
        
        # Sincronizar estado inicial
        status_text = self.tr("En espera") if job.status == "PENDING" else self.tr("Analizando...")
        card.update_progress(0, status_text=status_text)

    def select_card(self, job_id):
        if self._selected_card_id and self._selected_card_id in self.cards:
            self.cards[self._selected_card_id].set_selected(False)
        self._selected_card_id = job_id
        if job_id in self.cards:
            self.cards[job_id].set_selected(True)

    def _emit_card_clicked(self, job_id):
        self.select_card(job_id)
        if hasattr(self, 'card_clicked_signal'):
            self.card_clicked_signal.emit(job_id)

    def _on_job_removed(self, job_id):
        card = self.cards.pop(job_id, None)
        if card is None:
            # Normal, no es un error: este panel solo crea tarjetas para DOWNLOAD y
            # PLAYLIST (ver el filtro de _on_job_added), pero la señal job_removed llega
            # por TODOS los trabajos de la cola compartida -- entre ellos los RECODE que
            # encolan Modo Rápido y Herramientas Multimedia. Antes esto se registraba
            # como WARNING y parecía un fallo en cada recodificación.
            logger.debug(f"QueuePanel: {job_id} no tenía tarjeta aquí (trabajo de otra pestaña).")
            return

        logger.debug(f"QueuePanel: quitando la tarjeta de {job_id}.")
        card.hide()
        self.scroll_layout.removeWidget(card)
        card.setParent(None)
        card.deleteLater()

        if not self.cards:
            self.empty_lbl.show()

    def _on_job_status_changed(self, job_id, status):
        card = self.cards.get(job_id)
        if not card:
            return
            
        status_translations = {
            "PENDING": self.tr("En espera"),
            "ANALYZING": self.tr("Analizando..."),
            "RUNNING": self.tr("Descargando"),
            "COMPLETED": self.tr("Completado"),
            "FAILED": self.tr("Error"),
            "CANCELLED": self.tr("Cancelado"),
            "SKIPPED": self.tr("Omitido")
        }
        status_text = status_translations.get(status, status)
        
        job = self.queue_mgr.get_job(job_id)
        
        speed_text = ""
        percent = 0.0
        if job:
            card.update_title(job.title)
            percent = job.progress
            if status == "RUNNING":
                speed_text = f"{job.speed} | ETA {job.eta}" if job.speed and job.eta else job.speed
            elif status == "FAILED":
                from core.ytdlp_logic.analyzer import strip_ansi_codes
                clean_err = strip_ansi_codes(job.error_message) if job.error_message else ""
                speed_text = clean_err
                card.status_lbl.setToolTip(clean_err)
            elif status == "COMPLETED":
                speed_text = job.error_message or self.tr("Descargado")
            elif status == "SKIPPED":
                speed_text = job.error_message or self.tr("El archivo ya existe")
        
        # Una descarga con recodificación pedida pasa por COMPLETED antes de recodificar:
        # DownloadController ya marcó set_recode_pending(True) al encolarla y lo levanta
        # al terminar, así que aquí basta con reflejar el estado de la descarga.
        card.set_completed(status == "COMPLETED")

        if status in ("COMPLETED", "FAILED", "CANCELLED", "SKIPPED"):
            card.progress_bar.setRange(0, 100)
            
        if job and job.job_type == "PLAYLIST":
            card.btn_configure.show()
            
        has_fragments = bool(job and job.request_data and job.request_data.get("selected_fragments"))
        if status == "RUNNING" and has_fragments:
            card.progress_bar.setRange(0, 0)
            percent = 0
            speed_text = self.tr("Por favor espere...")
            status_text = self.tr("Cortando fragmentos...")
            
        card.update_progress(
            percent=percent,
            speed_text=speed_text,
            status_text=status_text
        )

    def _on_job_progress_changed(self, job_id, percent, speed, eta):
        card = self.cards.get(job_id)
        if not card:
            return
            
        job = self.queue_mgr.get_job(job_id)
        if job and job.status == "ANALYZING":
            card.progress_bar.setRange(0, 100)
            card.update_progress(
                percent=percent,
                speed_text="",
                status_text=speed
            )
            return

        has_fragments = bool(job and job.request_data and job.request_data.get("selected_fragments"))
        
        if has_fragments:
            card.progress_bar.setRange(0, 0)
            # 'speed' trae el mensaje "Descargando/Cortando fragmento N de M" cuando
            # viene del pseudo-evento fragment_progress (ver queue_manager.py);
            # si no, usamos un texto genérico de respaldo.
            fragment_text = speed if speed else self.tr("Cortando fragmentos...")
            card.update_progress(
                percent=0,
                speed_text=fragment_text,
                status_text=self.tr("Descargando")
            )
        else:
            card.progress_bar.setRange(0, 100)
            speed_text = f"{speed} | ETA {eta}" if speed and eta else speed
            card.update_progress(
                percent=percent,
                speed_text=speed_text,
                status_text=self.tr("Descargando")
            )

    def _on_width_changed(self, width):
        self.setFixedWidth(width)
        if hasattr(self, 'content_widget'):
            self.content_widget.setFixedWidth(width)

    def _on_animation_finished(self):
        if not self.is_expanded:
            self.content_widget.hide()
            self.hide()

    def _on_clear_list_click(self):
        """Limpia trabajos inactivos y notifica al padre."""
        self.queue_mgr.clear_inactive_jobs()
        self.queue_action_signal.emit("cleared")

    def _on_reset_all_click(self):
        """Resetea todos los trabajos terminados y notifica al padre."""
        self.queue_mgr.reset_all_terminal_jobs()
        self.queue_action_signal.emit("reset")

    def _on_queue_reordered(self):
        """Reconstruye el orden visual de las tarjetas basado en el QueueManager."""
        self.scroll_content.setUpdatesEnabled(False)
        jobs = self.queue_mgr.get_all_jobs()
        # Eliminar las tarjetas del layout actual sin destruirlas
        for job in jobs:
            card = self.cards.get(job.job_id)
            if card:
                self.scroll_layout.removeWidget(card)
        # Volver a añadirlas en el nuevo orden
        for job in jobs:
            card = self.cards.get(job.job_id)
            if card:
                self.scroll_layout.addWidget(card)
        self.scroll_content.setUpdatesEnabled(True)

    # ── Arrastrar para reordenar ─────────────────────────────────────────────
    # Toda la orquestación vive aquí (no en QueueItemCard) porque aquí ya están
    # scroll_layout, self.cards y queue_mgr. La tarjeta solo detecta cuándo
    # empieza el arrastre (drag_started); a partir de ahí este panel "agarra" el
    # mouse (grabMouse) para recibir todos los eventos sin importar qué widget
    # hijo esté debajo del cursor.

    def _on_card_file_drag(self, job_id):
        """Arrastra hacia otra aplicación TODO lo que dejó en disco el trabajo de esta
        tarjeta: el medio (o cada fragmento), el completo conservado, la miniatura, los
        subtítulos y el recodificado -- según lo que el usuario haya elegido conservar,
        que se resuelve recién ahora comprobando qué sigue existiendo. Es la misma vía
        que Modo Rápido (ver quick_mode/activity_panel.py::_on_row_drag) y es
        independiente del envío a editores conectados, que sigue su propio camino."""
        job = self.queue_mgr.get_job(job_id)
        card = self.cards.get(job_id)
        if not job or not card:
            return

        # Las demás tarjetas pueden haber bajado a la misma carpeta con nombres
        # emparentados ('Cancion' y 'Cancion_2'): sus rutas se pasan para que cada
        # archivo se quede con su dueño más directo.
        foreign = [
            path
            for other in self.queue_mgr.get_all_jobs()
            if other.job_id != job_id and other.job_type in ("DOWNLOAD", "PLAYLIST")
            for path in other.artifacts.stems()
        ]
        try:
            files = job.artifacts.collect(foreign_stems=foreign)
        except Exception as e:
            logger.error(f"QueuePanel: No se pudieron reunir los archivos para arrastrar: {e}")
            return

        if not files:
            logger.warning(
                f"QueuePanel: No queda ningún archivo en disco para arrastrar de '{job.title}' "
                "(¿se movieron o borraron?)."
            )
            return

        badge = "" if len(files) == 1 else self.tr("{0} archivos").format(len(files))
        from gui.widgets.native_file_drag import start_native_file_drag
        start_native_file_drag(card, files, badge_text=badge)

    def _on_card_drag_started(self, job_id):
        self._dragging_job_id = job_id
        self._drag_insert_index = None
        card = self.cards.get(job_id)
        if card:
            card.set_drag_opacity(True)
        self._drag_indicator.raise_()
        self.grabMouse()
        self._update_drag_indicator(QCursor.pos())

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if self._dragging_job_id is None:
            return
        global_pos = event.globalPosition().toPoint()
        self._update_drag_indicator(global_pos)
        self._update_autoscroll(global_pos)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self._dragging_job_id is None:
            return
        self._finish_drag()

    def _update_drag_indicator(self, global_pos):
        local_pos = self.scroll_content.mapFromGlobal(global_pos)

        sibling_cards = [
            self.cards[job.job_id] for job in self.queue_mgr.get_all_jobs()
            if job.job_id != self._dragging_job_id and job.job_id in self.cards
        ]

        insert_index = len(sibling_cards)
        target_y = sibling_cards[-1].y() + sibling_cards[-1].height() if sibling_cards else 0
        for i, card in enumerate(sibling_cards):
            mid_y = card.y() + card.height() // 2
            if local_pos.y() < mid_y:
                insert_index = i
                target_y = card.y()
                break

        self._drag_insert_index = insert_index
        self._drag_indicator.setGeometry(0, max(0, target_y - 1), self.scroll_content.width(), 3)
        self._drag_indicator.show()
        self._drag_indicator.raise_()

    def _update_autoscroll(self, global_pos):
        viewport = self.scroll.viewport()
        local_y = viewport.mapFromGlobal(global_pos).y()
        margin = 30

        if local_y < margin:
            self._autoscroll_direction = -1
        elif local_y > viewport.height() - margin:
            self._autoscroll_direction = 1
        else:
            self._autoscroll_direction = 0

        if self._autoscroll_direction != 0:
            if not self._autoscroll_timer.isActive():
                self._autoscroll_timer.start()
        else:
            self._autoscroll_timer.stop()

    def _do_autoscroll(self):
        if self._autoscroll_direction == 0 or self._dragging_job_id is None:
            self._autoscroll_timer.stop()
            return
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.value() + self._autoscroll_direction * 12)
        self._update_drag_indicator(QCursor.pos())

    def _finish_drag(self):
        try:
            self.releaseMouse()
        except Exception:
            pass
        self._autoscroll_timer.stop()
        self._autoscroll_direction = 0
        self._drag_indicator.hide()

        job_id = self._dragging_job_id
        insert_index = self._drag_insert_index
        self._dragging_job_id = None
        self._drag_insert_index = None

        card = self.cards.get(job_id)
        if card:
            card.reset_drag_state()

        if job_id and insert_index is not None:
            self.queue_mgr.move_job_to_index(job_id, insert_index)

    def _on_open_folder_requested(self, job_id):
        job = self.queue_mgr.get_job(job_id)
        if not job:
            return
            
        output_path = None
        # Si no hay final_filepath en el job, intentar usar la ruta del config
        if not job.final_filepath:
            config_to_use = job.request_data if job.request_data else job.config
            output_path = config_to_use.get("output_path")
        else:
            output_path = job.final_filepath
            
        if not output_path:
            return
            
        actual_path = self._find_actual_downloaded_file(output_path)
        if actual_path:
            self._open_and_select(actual_path)

    def _find_actual_downloaded_file(self, filepath):
        from core.utils.output_artifacts import find_actual_downloaded_file
        return find_actual_downloaded_file(filepath, fallback_to_dir=True)

    def _open_and_select(self, path):
        import subprocess
        import platform
        
        path = os.path.abspath(path)
        if not os.path.exists(path):
            return
            
        try:
            if os.name == 'nt':
                # Windows
                if os.path.isdir(path):
                    os.startfile(path)
                else:
                    # En Windows, para señalar el archivo en Explorer:
                    # Se pasa como string formateado para evitar que subprocess añada comillas extra 
                    # que separen la coma de la ruta, rompiendo el parseo de explorer.exe con '#'
                    subprocess.run(f'explorer /select,"{path}"')
            elif platform.system() == 'Darwin':
                # macOS
                if os.path.isdir(path):
                    subprocess.run(['open', path])
                else:
                    subprocess.run(['open', '-R', path])
            else:
                # Linux (fallback)
                if os.path.isdir(path):
                    subprocess.run(['xdg-open', path])
                else:
                    subprocess.run(['xdg-open', os.path.dirname(path)])
        except Exception as e:
            logger.error(f"Error abriendo explorador en la ruta {path}: {e}")
