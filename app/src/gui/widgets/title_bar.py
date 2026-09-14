# src/gui/widgets/title_bar.py
"""
Barra de título personalizada para DowP 2.0.
Reemplaza la barra nativa del OS para permitir personalización completa
de colores e iconos manteniendo compatibilidad cross-platform.
"""
import os
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton, QSizePolicy
from PySide6.QtCore import Qt, QPoint, Signal
from PySide6.QtGui import QIcon, QPixmap
from core.logger.logger_manager import logger
from core.utils.paths import get_src_dir

# Ruta base de iconos SVG
_ICONS_DIR = os.path.join(get_src_dir(), "assets", "icons", "svg")
_APP_ICONS_DIR = os.path.join(get_src_dir(), "assets", "icons", "app")


def _icon(name: str) -> QIcon:
    """Carga un ícono SVG desde assets/icons/svg/."""
    path = os.path.abspath(os.path.join(_ICONS_DIR, name))
    if os.path.exists(path):
        return QIcon(path)
    logger.warning(f"TitleBar: Ícono no encontrado: {path}")
    return QIcon()


class CustomTitleBar(QWidget):
    """
    Barra de título personalizada con soporte de drag, minimizar,
    maximizar/restaurar y cerrar. Completamente pintada por Qt.
    """

    # Señal emitida al hacer doble clic (toggle maximize)
    double_clicked = Signal()

    # Estilos de la barra
    _BAR_STYLE = """
        CustomTitleBar {
            background-color: #0d0d0d;
            border-bottom: 1px solid #222222;
        }
    """

    _TITLE_STYLE = """
        QLabel {
            color: #e0e0e0;
            font-size: 13px;
            font-weight: 600;
            background: transparent;
            padding-left: 4px;
        }
    """

    _BTN_BASE = """
        QPushButton {{
            background: transparent;
            border: none;
            border-radius: {radius}px;
            padding: 4px;
            min-width: {size}px;
            min-height: {size}px;
            max-width: {size}px;
            max-height: {size}px;
        }}
        QPushButton:hover {{
            background-color: {hover};
        }}
        QPushButton:pressed {{
            background-color: {pressed};
        }}
    """

    def __init__(self, parent=None, title: str = "DowP 2.0"):
        super().__init__(parent)
        self.setObjectName("CustomTitleBar")
        self.setFixedHeight(36)
        self.setStyleSheet(self._BAR_STYLE)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # Estado de drag
        self._drag_active = False
        self._drag_start_pos = QPoint()

        self._build_ui(title)

    def _build_ui(self, title: str):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 4, 0)
        layout.setSpacing(4)

        # ── Logo ──────────────────────────────────────────────────────────────
        logo_path = os.path.abspath(os.path.join(_APP_ICONS_DIR, "DowP_Logo.ico"))
        if os.path.exists(logo_path):
            logo_label = QLabel(self)
            logo_label.setPixmap(
                QIcon(logo_path).pixmap(18, 18)
            )
            logo_label.setFixedSize(20, 20)
            logo_label.setStyleSheet("background: transparent;")
            layout.addWidget(logo_label)

        # ── Espacio para empujar los botones a la derecha ─────────────────────
        layout.addStretch()

        # ── Título (Centrado Absoluto) ────────────────────────────────────────
        # Lo creamos como hijo del widget pero NO lo agregamos al layout
        self.title_label = QLabel(title, self)
        self.title_label.setStyleSheet(self._TITLE_STYLE)
        self.title_label.setAlignment(Qt.AlignCenter)
        # Hacerlo transparente a eventos del ratón para no bloquear el drag
        self.title_label.setAttribute(Qt.WA_TransparentForMouseEvents)

        # ── Botones de control ────────────────────────────────────────────────
        btn_size = 28
        radius = 6

        # Minimizar
        self.btn_min = QPushButton(self)
        self.btn_min.setObjectName("titleBarMinimize")
        self.btn_min.setIcon(_icon("minimize.svg"))
        self.btn_min.setToolTip("Minimizar")
        self.btn_min.setStyleSheet(
            self._BTN_BASE.format(
                size=btn_size, radius=radius,
                hover="#1e3a1e", pressed="#163016"
            )
        )
        self.btn_min.clicked.connect(self._on_minimize)

        # Maximizar / Restaurar
        self.btn_max = QPushButton(self)
        self.btn_max.setObjectName("titleBarMaximize")
        self.btn_max.setIcon(_icon("fullscreen.svg"))
        self.btn_max.setToolTip("Maximizar")
        self.btn_max.setStyleSheet(
            self._BTN_BASE.format(
                size=btn_size, radius=radius,
                hover="#1e3a1e", pressed="#163016"
            )
        )
        self.btn_max.clicked.connect(self._on_maximize_restore)

        # Cerrar
        self.btn_close = QPushButton(self)
        self.btn_close.setObjectName("titleBarClose")
        self.btn_close.setIcon(_icon("close.svg"))
        self.btn_close.setToolTip(self.tr("Cerrar"))
        self.btn_close.setStyleSheet(
            self._BTN_BASE.format(
                size=btn_size, radius=radius,
                hover="#4a1010", pressed="#3a0a0a"
            )
        )
        self.btn_close.clicked.connect(self._on_close)

        layout.addWidget(self.btn_min)
        layout.addWidget(self.btn_max)
        layout.addWidget(self.btn_close)

    # ── Acciones ──────────────────────────────────────────────────────────────

    def _window(self):
        return self.window()

    def _on_minimize(self):
        self._window().showMinimized()

    def _on_maximize_restore(self):
        win = self._window()
        if win.isMaximized():
            win.showNormal()
            self.btn_max.setIcon(_icon("fullscreen.svg"))
            self.btn_max.setToolTip("Maximizar")
        else:
            win.showMaximized()
            # Restaurar icono
            self.btn_max.setIcon(_icon("fullscreen_exit.svg"))
            self.btn_max.setToolTip("Restaurar")

    def _on_close(self):
        self._window().close()

    # ── Drag para mover la ventana ────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_active = True
            self._drag_start_pos = (
                event.globalPosition().toPoint() - self._window().frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_active and (event.buttons() & Qt.LeftButton):
            win = self._window()
            if win.isMaximized():
                # Al arrastrar desde maximizado: restaurar y reposicionar
                win.showNormal()
                self.btn_max.setIcon(_icon("fullscreen.svg"))
                self.btn_max.setToolTip("Maximizar")
                # Recalcular punto de drag para que el cursor quede sobre la barra
                self._drag_start_pos = QPoint(
                    win.width() // 2,
                    self.height() // 2
                )
                win.move(event.globalPosition().toPoint() - self._drag_start_pos)

            # A partir de aquí le cedemos el gesto al gestor de ventanas nativo
            # (startSystemMove) en vez de seguir moviendo la ventana a mano con
            # move(): un move() manual nunca es reconocido como arrastre nativo por
            # el sistema operativo, así que los snaps de borde (Windows/macOS/Linux)
            # no se activaban. Una vez que el SO toma el control no van a llegar más
            # mouseMoveEvent para este gesto.
            handle = win.windowHandle()
            if handle is not None:
                self._drag_active = False
                handle.startSystemMove()
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_active = False
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._on_maximize_restore()
            event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'title_label'):
            self.title_label.resize(self.width(), self.height())
            self.title_label.move(0, 0)

    # ── Actualización dinámica del título ─────────────────────────────────────

    def set_title(self, title: str):
        self.title_label.setText(title)
