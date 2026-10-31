"""Muestra de Ajustes > Apariencia: una ventanita pintada con los cambios sin aplicar. Es un
dibujo, así que se actualiza al momento, mientras que aplicar de verdad recarga toda la app."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QWidget

from core.utils import background_images as bg
from gui.widgets.background_canvas import background_notifier


class ThemePreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._tokens = {}
        self._shapes = {}
        self._family = ""
        self._font_px = 13
        self._panel_alpha = None
        self._image = (None, None)  # (ruta, QPixmap)
        self._image_override = None
        self.setMinimumSize(280, 148)
        background_notifier().changed.connect(self._on_background_changed)

    def set_draft(self, tokens: dict, shapes: dict, family: str, panel_alpha, image: str | None = None):
        """panel_alpha: opacidad de los paneles (0-1), o None si van sólidos. image: la imagen
        de fondo elegida y aún sin aplicar; sin ella, la actual."""
        self._image_override = image
        self._tokens, self._shapes, self._family = tokens, shapes, family
        self._font_px = shapes.get("tamano_fuente", 13)
        self._panel_alpha = panel_alpha
        self.update()

    def _on_background_changed(self, place: str):
        if place == bg.PLACE_GENERAL:
            self.update()

    def _c(self, key: str, fallback="#808080", alpha=None) -> QColor:
        color = QColor(self._tokens.get(key, fallback))
        if not color.isValid():
            color = QColor(fallback)
        if alpha is not None:
            color.setAlphaF(alpha)
        return color

    def _background(self, p: QPainter, area: QRectF):
        p.fillRect(area, self._c("fondo_principal"))
        path = self._image_override or bg.image_path(bg.PLACE_GENERAL)
        if not path:
            return
        if self._image[0] != path:
            self._image = (path, QPixmap(path))
        pix = self._image[1]
        if pix.isNull():
            return
        scaled = pix.scaled(area.size().toSize(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        p.save()
        p.setOpacity(bg.get_place(bg.PLACE_GENERAL)["opacity"] / 100.0)
        p.drawPixmap(area.topLeft(), scaled, QRectF(0, 0, area.width(), area.height()))
        p.restore()

    def _rounded(self, p: QPainter, rect: QRectF, radius, fill, border=None):
        p.setPen(QPen(border, 1) if border is not None else Qt.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(rect, radius, radius)

    def paintEvent(self, event):
        if not self._tokens:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        frame = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        big = self._shapes.get("radio_grande", 8)
        radius = self._shapes.get("radio", 6)
        clip = QPainterPath()
        clip.addRoundedRect(frame, big, big)
        p.save()
        p.setClipPath(clip)
        self._background(p, frame)
        font = QFont(self._family) if self._family else p.font()
        font.setPixelSize(int(self._font_px))
        p.setFont(font)
        row_h = max(24, QFontMetrics(font).height() + 8)
        alpha = self._panel_alpha
        panel_alpha = alpha if alpha is not None else 1.0
        # Controles: como en la app, menos transparentes que su panel.
        control_alpha = panel_alpha + (1 - panel_alpha) * 0.4

        panel = frame.adjusted(10, 10, -10, -10)
        self._rounded(p, panel, big, self._c("fondo_secundario", alpha=panel_alpha), self._c("borde_normal"))
        inner = panel.adjusted(10, 8, -10, -8)

        metrics = QFontMetrics(font)
        gap = 6
        half = inner.width() / 2

        def text(rect, key, label, flags=Qt.AlignVCenter | Qt.AlignLeft):
            p.setPen(self._c(key))
            p.drawText(rect, flags, metrics.elidedText(label, Qt.ElideRight, int(rect.width())))

        def tabs(y):
            x = inner.left()
            for i, label in enumerate((self.tr("Pestaña"), self.tr("Otra"), self.tr("Más"))):
                w = metrics.horizontalAdvance(label) + 18
                rect = QRectF(x, y, w, row_h)
                if i == 0:
                    p.fillRect(QRectF(x, y + row_h - 2, w, 2), self._c("acento_primario"))
                text(rect, "texto_principal" if i == 0 else "tab_texto_inactivo", label, Qt.AlignCenter)
                x += w + 4

        def field_and_button(y):
            button_w = max(90, metrics.horizontalAdvance(self.tr("Aplicar")) + 26)
            field = QRectF(inner.left(), y, inner.width() - button_w - gap, row_h)
            self._rounded(p, field, radius, self._c("fondo_campo", "#1a1a1a", control_alpha), self._c("borde_campo", "#333333"))
            text(field.adjusted(8, 0, -8, 0), "texto_principal", self.tr("Texto de ejemplo"))
            button = QRectF(field.right() + gap, y, button_w, row_h)
            gradient = QLinearGradient(button.topLeft(), button.topRight())
            gradient.setColorAt(0, self._c("boton_fondo_inicio"))
            gradient.setColorAt(1, self._c("boton_fondo_fin"))
            self._rounded(p, button, radius, gradient)
            text(button, "boton_texto", self.tr("Aplicar"), Qt.AlignCenter)

        def selection(y):
            selected = QRectF(inner.left(), y, half - gap / 2, row_h)
            self._rounded(p, selected, radius, self._c("seleccion_fondo"))
            text(selected.adjusted(8, 0, -4, 0), "seleccion_texto", self.tr("Seleccionado"))
            text(QRectF(inner.left() + half + 4, y, half - 4, row_h), "texto_secundario", self.tr("Texto secundario"))

        def controls(y):
            combo = QRectF(inner.left(), y, half - gap / 2, row_h)
            self._rounded(p, combo, radius, self._c("fondo_control", "#1a1a1a", control_alpha), self._c("borde_campo", "#333333"))
            text(combo.adjusted(8, 0, -22, 0), "texto_principal", self.tr("Menú"))
            cx, cy = combo.right() - 12, combo.center().y()
            p.setPen(Qt.NoPen)
            p.setBrush(self._c("acento_primario"))
            p.drawPolygon(QPolygonF([QPointF(cx - 4, cy - 2), QPointF(cx + 4, cy - 2), QPointF(cx, cy + 3)]))
            quarter = (half - gap * 1.5) / 2
            second = QRectF(inner.left() + half + gap / 2, y, quarter, row_h)
            self._rounded(p, second, radius, self._c("boton_secundario_fondo", "#1b3b22", control_alpha))
            text(second, "boton_secundario_texto", self.tr("Botón"), Qt.AlignCenter)
            off = QRectF(second.right() + gap, y, quarter, row_h)
            self._rounded(p, off, radius, self._c("fondo_control", "#1a1a1a", control_alpha))
            text(off, "texto_deshabilitado", self.tr("Apagado"), Qt.AlignCenter)

        def check_and_states(y):
            box = QRectF(inner.left(), y + (row_h - 14) / 2, 14, 14)
            self._rounded(p, box, self._shapes.get("radio_chico", 4), self._c("checkbox_checked"))
            text(QRectF(box.right() + 6, y, half - 24, row_h), "acento_primario", self.tr("Acento"))
            p.setPen(Qt.NoPen)
            for i, key in enumerate(("estado_exito", "estado_aviso", "estado_error", "estado_progreso")):
                p.setBrush(self._c(key))
                p.drawEllipse(QRectF(inner.left() + half + 4 + i * 18, y + (row_h - 12) / 2, 12, 12))

        def progress(y):
            track = QRectF(inner.left(), y + (row_h - 8) / 2, inner.width(), 8)
            self._rounded(p, track, 4, self._c("progreso_fondo", "#222222", control_alpha))
            done = QRectF(track.left(), track.top(), track.width() * 0.62, track.height())
            gradient = QLinearGradient(done.topLeft(), done.topRight())
            gradient.setColorAt(0, self._c("progreso_inicio"))
            gradient.setColorAt(1, self._c("progreso_fin"))
            self._rounded(p, done, 4, gradient)

        def list_item(y):
            item = QRectF(inner.left(), y, inner.width(), row_h)
            self._rounded(p, item, radius, self._c("tarjeta_lista_fondo", "#1a1a1a", control_alpha), self._c("tarjeta_lista_borde", "#333333"))
            text(item.adjusted(8, 0, -8, 0), "texto_principal", self.tr("Elemento de una lista"))

        # Lo que quepa, de lo más a lo menos importante; luego se reparte en toda la altura.
        by_priority = [field_and_button, selection, check_and_states, controls, tabs, progress, list_item]
        fits = max(1, min(len(by_priority), int((inner.height() + gap) // (row_h + gap))))
        chosen = by_priority[:fits]
        order = [tabs, field_and_button, selection, controls, check_and_states, progress, list_item]
        rows = [row for row in order if row in chosen]
        spare = inner.height() - len(rows) * row_h
        step = row_h + (spare / (len(rows) - 1) if len(rows) > 1 else 0)
        for i, row in enumerate(rows):
            row(inner.top() + i * step)
        p.restore()
        p.setPen(QPen(self._c("borde_sutil"), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(clip)
        p.end()
