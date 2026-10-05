import os
from PySide6.QtCore import Qt, QSize, QTimer, QRectF
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QPen
from PySide6.QtWidgets import QWidget
from core.utils.paths import get_src_dir

class LoadingSpinnerWidget(QWidget):
    """Widget vectorial de spinner de carga animado a 30 FPS dibujado dinámicamente con QPainter."""
    def __init__(self, parent=None, size=16, color="#B9E640"):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.color = QColor(color)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(33)  # ~30 FPS
        self._timer.timeout.connect(self._rotate)
        self.hide()

    def set_color(self, color_hex: str):
        self.color = QColor(color_hex)
        self.update()

    def _rotate(self):
        self._angle = (self._angle + 30) % 360
        self.update()

    def start(self):
        self.show()
        if not self._timer.isActive():
            self._timer.start()

    def stop(self):
        self._timer.stop()
        self.hide()

    def paintEvent(self, event):
        if not self.isVisible():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(2, 2, self.width() - 4, self.height() - 4)
        pen = QPen(self.color, 2.0)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, int(-self._angle * 16), int(270 * 16))

_SVG_DIR = os.path.join(get_src_dir(), "assets", "icons", "svg")

def get_colored_svg_icon(name: str, color_hex: str, size=16, disabled_color_hex: str = "#666666") -> QIcon:
    """Carga y tintura un icono SVG con el color especificado y soporte para estado deshabilitado."""
    path = os.path.join(_SVG_DIR, name)
    if not os.path.exists(path):
        return QIcon()
    pix = QPixmap(path)
    if pix.isNull():
        return QIcon()
    pix = pix.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    painter = QPainter(pix)
    painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    painter.fillRect(pix.rect(), QColor(color_hex))
    painter.end()

    icon = QIcon()
    icon.addPixmap(pix, QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(pix, QIcon.Mode.Normal, QIcon.State.On)
    icon.addPixmap(pix, QIcon.Mode.Selected, QIcon.State.Off)
    icon.addPixmap(pix, QIcon.Mode.Selected, QIcon.State.On)
    icon.addPixmap(pix, QIcon.Mode.Active, QIcon.State.Off)
    icon.addPixmap(pix, QIcon.Mode.Active, QIcon.State.On)

    if disabled_color_hex:
        pix_dis = QPixmap(path)
        if not pix_dis.isNull():
            pix_dis = pix_dis.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            painter_dis = QPainter(pix_dis)
            painter_dis.setCompositionMode(QPainter.CompositionMode_SourceIn)
            painter_dis.fillRect(pix_dis.rect(), QColor(disabled_color_hex))
            painter_dis.end()
            icon.addPixmap(pix_dis, QIcon.Mode.Disabled, QIcon.State.Off)
            icon.addPixmap(pix_dis, QIcon.Mode.Disabled, QIcon.State.On)

    return icon

def get_colored_folder_icon(color_hex: str) -> QIcon:
    """Genera un icono de carpeta abierta/cerrada coloreado sin tinte de selección."""
    icon = QIcon()
    path_closed = os.path.join(_SVG_DIR, "folder.svg")
    path_open = os.path.join(_SVG_DIR, "folder_open.svg")
    
    if os.path.exists(path_closed):
        pix_closed = QPixmap(path_closed)
        if not pix_closed.isNull():
            pix_closed = pix_closed.scaled(16, 16, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            painter = QPainter(pix_closed)
            painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
            painter.fillRect(pix_closed.rect(), QColor(color_hex))
            painter.end()
            icon.addPixmap(pix_closed, QIcon.Mode.Normal, QIcon.State.Off)
            icon.addPixmap(pix_closed, QIcon.Mode.Selected, QIcon.State.Off)
            icon.addPixmap(pix_closed, QIcon.Mode.Active, QIcon.State.Off)
            
    if os.path.exists(path_open):
        pix_open = QPixmap(path_open)
        if not pix_open.isNull():
            pix_open = pix_open.scaled(16, 16, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            painter = QPainter(pix_open)
            painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
            painter.fillRect(pix_open.rect(), QColor(color_hex))
            painter.end()
            icon.addPixmap(pix_open, QIcon.Mode.Normal, QIcon.State.On)
            icon.addPixmap(pix_open, QIcon.Mode.Selected, QIcon.State.On)
            icon.addPixmap(pix_open, QIcon.Mode.Active, QIcon.State.On)
            
    return icon

def get_svg_icon(name: str) -> QIcon:
    path = os.path.join(_SVG_DIR, name)
    if not os.path.exists(path):
        return QIcon()
    pix = QPixmap(path)
    if pix.isNull():
        return QIcon(path)
    icon = QIcon()
    icon.addPixmap(pix, QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(pix, QIcon.Mode.Normal, QIcon.State.On)
    icon.addPixmap(pix, QIcon.Mode.Selected, QIcon.State.Off)
    icon.addPixmap(pix, QIcon.Mode.Selected, QIcon.State.On)
    icon.addPixmap(pix, QIcon.Mode.Active, QIcon.State.Off)
    icon.addPixmap(pix, QIcon.Mode.Active, QIcon.State.On)
    return icon

def get_contrast_svg_icon(name: str, normal_color_hex="#B9E640", active_color_hex="#101010", size=16) -> QIcon:
    """Genera un QIcon con modos Normal (color acento) y Active/Selected (color oscuro contraste)."""
    path = os.path.join(_SVG_DIR, name)
    if not os.path.exists(path):
        return QIcon()

    def make_pix(color_hex):
        pix = QPixmap(path)
        if pix.isNull():
            return QPixmap()
        pix = pix.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        painter = QPainter(pix)
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(pix.rect(), QColor(color_hex))
        painter.end()
        return pix

    icon = QIcon()
    pix_norm = make_pix(normal_color_hex)
    pix_act = make_pix(active_color_hex)

    icon.addPixmap(pix_norm, QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(pix_norm, QIcon.Mode.Normal, QIcon.State.On)
    icon.addPixmap(pix_act, QIcon.Mode.Active, QIcon.State.Off)
    icon.addPixmap(pix_act, QIcon.Mode.Active, QIcon.State.On)
    icon.addPixmap(pix_act, QIcon.Mode.Selected, QIcon.State.Off)
    icon.addPixmap(pix_act, QIcon.Mode.Selected, QIcon.State.On)
    return icon


def get_themed_svg_icon(name: str) -> QIcon:
    """Icono monocromo teñido con el color de iconos del tema (no usar con logos de
    colores como los de Adobe/DaVinci: para esos, get_svg_icon)."""
    from gui.styles import themed_icon
    return themed_icon(name)


def get_folder_icon() -> QIcon:
    """Carpeta sin color personalizado: toma el color de iconos del tema."""
    from gui.styles import generate_tinted_svg, get_theme_token
    color = get_theme_token("icono_principal", "#e3e3e3")
    icon = QIcon()
    path_closed = generate_tinted_svg("folder.svg", color) or os.path.join(_SVG_DIR, "folder.svg")
    path_open = generate_tinted_svg("folder_open.svg", color) or os.path.join(_SVG_DIR, "folder_open.svg")
    if os.path.exists(path_closed):
        icon.addFile(path_closed, QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        icon.addFile(path_closed, QSize(), QIcon.Mode.Selected, QIcon.State.Off)
        icon.addFile(path_closed, QSize(), QIcon.Mode.Active, QIcon.State.Off)
    if os.path.exists(path_open):
        icon.addFile(path_open, QSize(), QIcon.Mode.Normal, QIcon.State.On)
        icon.addFile(path_open, QSize(), QIcon.Mode.Selected, QIcon.State.On)
        icon.addFile(path_open, QSize(), QIcon.Mode.Active, QIcon.State.On)
    return icon

_PLACEHOLDER_CACHE = {}

def get_placeholder_thumbnail_icon(svg_name: str, color_hex: str, canvas_size=256) -> QIcon:
    """Genera un QIcon con un lienzo cuadrado uniforme para evitar desajustes en el GridMode."""
    from gui.styles import get_theme_token
    bg_hex = get_theme_token("miniatura_relleno_fondo", "#1c1c1e")
    border_hex = get_theme_token("miniatura_relleno_borde", "#2d2d32")
    cache_key = f"{svg_name}:{color_hex}:{canvas_size}:{bg_hex}:{border_hex}"
    if cache_key in _PLACEHOLDER_CACHE:
        return _PLACEHOLDER_CACHE[cache_key]

    pixmap = QPixmap(canvas_size, canvas_size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    # Dibujar fondo rectangular redondeado
    bg_color = QColor(bg_hex)
    border_color = QColor(border_hex)
    painter.setBrush(bg_color)
    painter.setPen(border_color)
    painter.drawRoundedRect(4, 4, canvas_size - 8, canvas_size - 8, 12, 12)

    # Dibujar el icono central
    svg_icon = get_colored_svg_icon(svg_name, color_hex, size=64)
    if not svg_icon.isNull():
        icon_pixmap = svg_icon.pixmap(64, 64)
        x = (canvas_size - 64) // 2
        y = (canvas_size - 64) // 2
        painter.drawPixmap(x, y, icon_pixmap)

    painter.end()

    icon = QIcon()
    icon.addPixmap(pixmap, QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(pixmap, QIcon.Mode.Normal, QIcon.State.On)
    icon.addPixmap(pixmap, QIcon.Mode.Selected, QIcon.State.Off)
    icon.addPixmap(pixmap, QIcon.Mode.Selected, QIcon.State.On)
    icon.addPixmap(pixmap, QIcon.Mode.Active, QIcon.State.Off)
    icon.addPixmap(pixmap, QIcon.Mode.Active, QIcon.State.On)
    _PLACEHOLDER_CACHE[cache_key] = icon
    return icon


