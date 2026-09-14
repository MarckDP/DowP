# src/gui/tabs/advanced_process/video_details_components.py
import os
import requests
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QSizePolicy, QComboBox, QStyledItemDelegate, QStyle, QStyleOptionComboBox,
    QStyleOptionViewItem, QApplication
)
from PySide6.QtCore import Qt, Signal, QThread, QSize, QRect
from PySide6.QtGui import QPixmap, QImage, QIcon, QPainter, QColor, QFontMetrics, QPalette
from PySide6.QtSvg import QSvgRenderer
from gui.styles import get_theme_token, apply_cut_button_style
from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon
from gui.widgets.combo_box import AutoPopupComboBox, CheckmarkComboDelegate
from core.utils.paths import get_src_dir
from PySide6.QtCore import QCoreApplication

class ThumbnailLoaderThread(QThread):
    finished = Signal(bytes, str) # content, error
    
    def __init__(self, url, fallback_urls=None):
        super().__init__()
        self.url = url
        self.fallback_urls = fallback_urls or []
        
    def run(self):
        urls_to_try = [self.url] + self.fallback_urls
        last_error = ""
        for url in urls_to_try:
            try:
                resp = requests.get(url, timeout=4)
                if resp.status_code == 200:
                    self.finished.emit(resp.content, "")
                    return
            except Exception as e:
                last_error = str(e)
        self.finished.emit(b"", last_error)

class RichTextDelegate(CheckmarkComboDelegate):
    """
    Delegate avanzado que permite pintar etiquetas con colores específicos y
    el icono de verificación verde de DowP a la derecha en el elemento seleccionado.
    [Combinado] -> Azul
    [Multi-Idioma] -> Violeta
    """
    def __init__(self, combo=None, parent=None):
        super().__init__(combo, parent)
        self.tag_colors = {
            QCoreApplication.translate("RichTextDelegate", "[Combinado]"): get_theme_token("etiqueta_combinado", "#3498db"),
            QCoreApplication.translate("RichTextDelegate", "[Multi-Idioma]"): get_theme_token("etiqueta_multi_idioma", "#9b59b6"),
        }
        # Cargar Iconos
        _icon_dir = os.path.join(get_src_dir(), "assets", "icons", "svg")
        self.star_pixmap = self._get_colored_icon(os.path.join(_icon_dir, "star.svg"), "#58cf5c") # Verde
        self.warning_pixmap = self._get_colored_icon(os.path.join(_icon_dir, "warning.svg"), "#ddb745") # Ámbar/Amarillo

    def _get_colored_icon(self, path, color_hex):
        if not os.path.exists(path): return None
        size = 16
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        
        painter = QPainter(pixmap)
        renderer = QSvgRenderer(path)
        renderer.render(painter)
        
        # Colorear
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), QColor(color_hex))
        painter.end()
        return pixmap

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)

        combo = self._get_combo(option)
        is_current = (combo is not None and index.row() == combo.currentIndex())
        is_hovered = bool(opt.state & QStyle.StateFlag.State_Selected)

        raw_text = opt.text
        opt.text = ""  # Limpiar para controlar el dibujado de fondo

        widget = option.widget
        style = widget.style() if widget else QApplication.style()

        # 1. Dibujar Fondo
        if is_hovered:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)
        elif is_current:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            bg_rect = opt.rect.adjusted(2, 1, -2, -1)
            painter.setBrush(QColor(255, 255, 255, 22))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(bg_rect, 4, 4)
            painter.restore()
        else:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)

        # 2. Dibujar texto enriquecido, iconos y etiquetas
        rect = opt.rect
        current_x = rect.left() + 10
        check_reserved_space = 36
        max_x = rect.right() - check_reserved_space

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        parts = raw_text.split(' ')
        font = painter.font()

        for i, part in enumerate(parts):
            if not part: continue
            clean_part = part.strip()

            # ¿Es un icono especial?
            icon = None
            if "✨" in clean_part: icon = self.star_pixmap
            elif "⚠️" in clean_part: icon = self.warning_pixmap

            if icon:
                if current_x + 20 <= max_x:
                    painter.drawPixmap(current_x, rect.top() + (rect.height()-16)//2, icon)
                    current_x += 20
                continue

            # ¿Es una etiqueta con color?
            color = self.tag_colors.get(clean_part, None)
            if color:
                painter.setPen(QColor(color))
                font.setBold(True)
                painter.setFont(font)
            else:
                if is_hovered:
                    text_color = opt.palette.color(QPalette.ColorGroup.Normal, QPalette.ColorRole.HighlightedText)
                    if text_color.lightness() < 40:
                        text_color = QColor("#ffffff")
                elif is_current:
                    text_color = QColor("#ffffff")
                else:
                    text_color = QColor("#c5c5c5")
                painter.setPen(text_color)
                font.setBold(False)
                painter.setFont(font)

            fm = QFontMetrics(font)
            part_str = part + (" " if i < len(parts) - 1 else "")
            part_w = fm.horizontalAdvance(part_str)

            if current_x + part_w <= max_x:
                painter.drawText(current_x, rect.top(), part_w, rect.height(), Qt.AlignmentFlag.AlignVCenter, part_str)
                current_x += part_w
            else:
                avail_w = max(0, max_x - current_x)
                if avail_w > 10:
                    elided = fm.elidedText(part_str, Qt.TextElideMode.ElideRight, avail_w)
                    painter.drawText(current_x, rect.top(), avail_w, rect.height(), Qt.AlignmentFlag.AlignVCenter, elided)
                break

        painter.restore()

        # 3. Dibujar el checkmark verde si es el ítem seleccionado
        if is_current and self._cached_check_pixmap:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            icon_display_size = 18
            margin_right = 10
            x = option.rect.right() - margin_right - icon_display_size
            y = option.rect.top() + (option.rect.height() - icon_display_size) // 2

            painter.drawPixmap(x, y, icon_display_size, icon_display_size, self._cached_check_pixmap)
            painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(size.height() + 15) # Padding vertical
        return size

class ResponsiveThumbnail(QWidget):
    clicked_cut = Signal()  # Emitida al pulsar el botón de recorte

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(146)
        self.setMinimumWidth(220)
        
        policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setSizePolicy(policy)
        
        self._pixmap = None
        self._cut_button_allowed = True

        self.thumb_label = QLabel(self)
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setObjectName("thumbnailLabel")
        self.thumb_label.setText(self.tr("Sin Vista Previa"))
        
        self.duration_label = QLabel("", self)
        self.duration_label.setObjectName("durationLabel")
        self.duration_label.hide()

        # Botón overlay flotante sobre la miniatura del video — circular, como el
        # badge de "play" que ya usa esta misma convención en fragment_dialog.py.
        self.btn_cut = QPushButton(self)
        self.btn_cut.setFixedSize(40, 40)
        self.btn_cut.setToolTip(self.tr("Recortar fragmento"))
        self.btn_cut.hide()
        self.btn_cut.clicked.connect(self.clicked_cut)
        self.btn_cut.setIconSize(QSize(22, 22))
        apply_cut_button_style(self.btn_cut, "normal", icon_size=22, shape="circular")

    def set_cut_status(self, status):
        apply_cut_button_style(self.btn_cut, status, icon_size=22, shape="circular")

    def set_duration(self, text):
        if text:
            self.duration_label.setText(text)
            self.duration_label.adjustSize()
            self.duration_label.show()
        else:
            self.duration_label.hide()
        self._update_layout()

    def set_cut_button_visible(self, visible):
        self._cut_button_allowed = visible
        if visible:
            if self._pixmap and not self._pixmap.isNull():
                self.btn_cut.show()
        else:
            self.btn_cut.hide()

    def set_pixmap(self, pixmap):
        self._pixmap = pixmap
        self.thumb_label.setText("")
        if getattr(self, '_cut_button_allowed', True):
            self.btn_cut.show()
        else:
            self.btn_cut.hide()
        self._update_pixmap()
        
    def set_text(self, text):
        self._pixmap = None
        self.thumb_label.setPixmap(QPixmap())
        self.thumb_label.setText(text)
        self.btn_cut.hide()

    def _update_pixmap(self):
        if self._pixmap and not self._pixmap.isNull():
            self.thumb_label.setPixmap(self._pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _update_layout(self):
        self.thumb_label.setGeometry(self.rect())
        btn_size = self.btn_cut.width()
        self.btn_cut.move(self.width() - btn_size - 8, 8)
        if not self.duration_label.isHidden():
            self.duration_label.move(
                self.width() - self.duration_label.width() - 8,
                self.height() - self.duration_label.height() - 8
            )

    def hasHeightForWidth(self):
        return False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_pixmap()
        self._update_layout()

    def sizeHint(self):
        return QSize(260, 146)

class RichComboBox(AutoPopupComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.tag_colors = {
            QCoreApplication.translate("RichComboBox", "[Combinado]"): get_theme_token("etiqueta_combinado", "#3498db"),
            QCoreApplication.translate("RichComboBox", "[Multi-Idioma]"): get_theme_token("etiqueta_multi_idioma", "#9b59b6"),
        }
        _icon_dir = os.path.join(get_src_dir(), "assets", "icons", "svg")
        self.star_pixmap = self._get_colored_icon(os.path.join(_icon_dir, "star.svg"), "#4CAF50")
        self.warning_pixmap = self._get_colored_icon(os.path.join(_icon_dir, "warning.svg"), "#FFC107")

    def _get_colored_icon(self, path, color_hex):
        if not os.path.exists(path): return None
        size = 16
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        renderer = QSvgRenderer(path)
        renderer.render(painter)
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), QColor(color_hex))
        painter.end()
        return pixmap

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        
        text = opt.currentText
        is_placeholder = False
        if not text:
            text = self.placeholderText()
            is_placeholder = True
        opt.currentText = ""
        
        self.style().drawComplexControl(QStyle.ComplexControl.CC_ComboBox, opt, painter, self)
        if not self.isEnabled():
            self._paint_disabled_arrow_overlay(painter, opt)
        self.style().drawControl(QStyle.ControlElement.CE_ComboBoxLabel, opt, painter, self)

        if not text:
            return

        rect = self.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, opt, QStyle.SubControl.SC_ComboBoxEditField, self)
        rect.setLeft(rect.left() + 5)
        rect.setRight(rect.right() - 5)
        
        painter.save()
        painter.setClipRect(rect)

        if is_placeholder:
            painter.setPen(self.palette().text().color())
            fm = self.fontMetrics()
            elided = fm.elidedText(text, Qt.TextElideMode.ElideRight, max(0, rect.width()))
            painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter, elided)
            painter.restore()
            return
        
        parts = text.split(' ')
        current_x = rect.left()
        font = painter.font()
        
        for part in parts:
            if not part: continue
            clean_part = part.strip()
            
            icon = None
            if "✨" in clean_part: icon = self.star_pixmap
            elif "⚠️" in clean_part: icon = self.warning_pixmap
            
            if icon:
                if current_x + 20 <= rect.right():
                    painter.drawPixmap(current_x, rect.top() + (rect.height()-16)//2, icon)
                current_x += 20
                continue

            color = self.tag_colors.get(clean_part, None)
            
            if color:
                painter.setPen(QIcon().theme().color(color) if hasattr(QIcon(), 'theme') else color)
                font.setBold(True)
                painter.setFont(font)
            else:
                painter.setPen(self.palette().text().color())
                font.setBold(False)
                painter.setFont(font)
                
            fm = QFontMetrics(font)
            if current_x < rect.right():
                available = rect.right() - current_x
                # Red de seguridad: si la palabra no entra entera, elidir con "…" en vez de
                # dejar que setClipRect() la corte a mitad de carácter sin aviso visual.
                draw_part = part if fm.horizontalAdvance(part) <= available else \
                    fm.elidedText(part, Qt.TextElideMode.ElideRight, available)
                painter.drawText(current_x, rect.top(), available, rect.height(),
                                 Qt.AlignmentFlag.AlignVCenter, draw_part)

            current_x += fm.horizontalAdvance(part + " ")
            
        painter.restore()
