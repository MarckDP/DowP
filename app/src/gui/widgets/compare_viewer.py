# src/gui/widgets/compare_viewer.py
"""Vista de comparación "antes/después" del Editor de Imagen -- dos
QGraphicsPixmapItem en la misma escena; el "después" vive recortado dentro de un
QGraphicsRectItem con ItemClipsChildrenToShape cuyo ancho sigue al divisor
arrastrable (en vez de recomponer bitmaps a mano en cada frame). Zoom/pan
compartidos vía QGraphicsView real (AnchorUnderMouse hace el centrado en el cursor
solo). Mismo nivel/estilo que ZoomableImageViewer/_PreviewVideoView
(preview_panel.py) -- widget propio, NO un modo más adentro de ZoomableImageViewer
(esa clase ya carga bastante: herramientas de dibujo, Canvas, capas)."""
from PySide6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsItem, QGraphicsPixmapItem,
    QGraphicsRectItem, QLabel,
)
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QPixmap, QPainter, QColor, QPen

from gui.styles import (
    VIEWER_CHIP_MARGIN, create_checkerboard_pixmap, create_viewer_info_chip,
    get_theme_token,
)

_DIVIDER_GRAB_MARGIN = 8
_HANDLE_RADIUS = 7
_MIN_SCALE = 0.05
_MAX_SCALE = 40.0


class CompareViewer(QGraphicsView):
    """set_images(before, after) -- carga y encuadra; clear() -- vacía la escena."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setRenderHint(QPainter.Antialiasing)
        self.setFrameShape(QGraphicsView.NoFrame)
        self._checker_tile = self._build_checker_tile()
        self._dark_bg_color = QColor(get_theme_token('fondo_principal', '#0a0a0a'))
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMouseTracking(True)

        # Recorte bilateral estricto vía QGraphicsRectItem con ItemClipsChildrenToShape:
        # _clip_rect_item recorta a la izquierda del divisor (0..x) para el "Antes" (Original).
        # _after_clip_item recorta a la derecha del divisor (x..w) para el "Después" (Resultado).
        # Al estar aisladas en sus respectivas regiones, el resultado NUNCA se filtra por
        # debajo de las transparencias o márgenes del original en el lado izquierdo.
        self._after_clip_item = QGraphicsRectItem()
        self._after_clip_item.setPen(Qt.NoPen)
        self._after_clip_item.setBrush(Qt.NoBrush)
        self._after_clip_item.setFlag(QGraphicsItem.ItemClipsChildrenToShape, True)
        self._scene.addItem(self._after_clip_item)

        self._after_item = QGraphicsPixmapItem(self._after_clip_item)
        self._after_item.setTransformationMode(Qt.SmoothTransformation)

        self._clip_rect_item = QGraphicsRectItem()
        self._clip_rect_item.setPen(Qt.NoPen)
        self._clip_rect_item.setBrush(Qt.NoBrush)
        self._clip_rect_item.setFlag(QGraphicsItem.ItemClipsChildrenToShape, True)
        self._scene.addItem(self._clip_rect_item)

        self._before_item = QGraphicsPixmapItem(self._clip_rect_item)
        self._before_item.setTransformationMode(Qt.SmoothTransformation)

        # El divisor se dibuja en paintEvent(), en coordenadas de VIEWPORT (no como
        # QGraphicsLineItem de escena) -- a propósito, para que abarque SIEMPRE el
        # alto completo del panel de vista previa, no solo el alto del contenido de
        # la imagen (que puede quedar más chico que el viewport, ej. con letterbox
        # al hacer zoom out o con una imagen mucho más ancha que alta).
        divider_color = QColor(get_theme_token('acento_primario', '#B9E640'))
        self._divider_pen = QPen(divider_color, 2)

        # El agarre del divisor es un QWidget aparte (no un item de la escena) a
        # propósito: así se puede mantener siempre centrado verticalmente en lo que
        # se ve del VIEWPORT, sin importar el zoom/paneo -- si fuera un item de
        # escena anclado al centro vertical de la imagen completa (como el resto),
        # se saldría de la vista apenas el usuario hace zoom y se mueve hacia
        # arriba/abajo. Solo su X sigue al divisor (ver _position_handle);
        # transparente al mouse para no interceptar el drag que ya maneja
        # mousePressEvent/mouseMoveEvent de este mismo widget.
        self._handle = QLabel(self)
        self._handle.setFixedSize(_HANDLE_RADIUS * 2, _HANDLE_RADIUS * 2)
        self._handle.setStyleSheet(f"""
            QLabel {{
                background-color: {divider_color.name()};
                border: 2px solid white;
                border-radius: {_HANDLE_RADIUS}px;
            }}
        """)
        self._handle.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._handle.hide()

        self._content_size = None  # (w, h) -- tamaño de referencia (el más grande de los dos lados)
        self._divider_fraction = 0.5
        self._dragging_divider = False
        self._panning = False
        self._pan_start = None

        # Mismo chip que usa ZoomableImageViewer fuera de la vista comparativa
        # (ver gui/styles.create_viewer_info_chip): el cuadro de "Original: W×H px"
        # es el mismo a los dos lados del toggle, no dos etiquetas parecidas.
        self._lbl_before = create_viewer_info_chip(self)
        self._lbl_after = create_viewer_info_chip(self)

    def _build_checker_tile(self) -> QPixmap:
        square = 10
        return create_checkerboard_pixmap(square * 2, square * 2, square)

    def refresh_checker_theme(self):
        """Llamar si el tema/tokens de color cambian en caliente."""
        self._checker_tile = self._build_checker_tile()
        self._dark_bg_color = QColor(get_theme_token('fondo_principal', '#0a0a0a'))
        self.viewport().update()

    def drawBackground(self, painter: QPainter, rect: QRectF):
        """Fondo general oscuro con cuadrícula de transparencia sobre el área del lienzo."""
        painter.save()
        painter.resetTransform()
        viewport_rect = self.viewport().rect()
        painter.fillRect(viewport_rect, self._dark_bg_color)
        if self._content_size is not None:
            w, h = self._content_size
            scene_rect = QRectF(0, 0, w, h)
            content_vp = self.mapFromScene(scene_rect).boundingRect().intersected(viewport_rect)
            if not content_vp.isEmpty():
                painter.setClipRect(content_vp)
                painter.drawTiledPixmap(viewport_rect, self._checker_tile)
        painter.restore()

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------
    def set_images(self, before_pixmap: QPixmap, after_pixmap: QPixmap):
        if before_pixmap.isNull() or after_pixmap.isNull():
            return
        bw, bh = before_pixmap.width(), before_pixmap.height()
        aw, ah = after_pixmap.width(), after_pixmap.height()
        if bw <= 0 or bh <= 0 or aw <= 0 or ah <= 0:
            return

        self._before_item.setPixmap(before_pixmap)
        self._after_item.setPixmap(after_pixmap)

        # Lienzo compartido = dimensión envolvente. Se usa ajuste proporcional "fit"
        # (min de ambos ejes) para centrar sin recortar ni deformar la imagen.
        target_w, target_h = max(bw, aw), max(bh, ah)
        self._content_size = (target_w, target_h)

        before_scale = min(target_w / bw, target_h / bh)
        after_scale = min(target_w / aw, target_h / ah)
        self._before_item.setScale(before_scale)
        self._after_item.setScale(after_scale)
        self._before_item.setPos((target_w - bw * before_scale) / 2, (target_h - bh * before_scale) / 2)
        self._after_item.setPos((target_w - aw * after_scale) / 2, (target_h - ah * after_scale) / 2)

        # La escena se hace más grande que el contenido (mismo margen del 200% a cada
        # lado que usa ZoomableImageViewer.set_pixmap(), para paneAR más allá de los
        # bordes) -- el contenido (before/after/divisor) sigue viviendo en (0,0)-(w,h)
        # dentro de esa escena más grande, ningún otro cálculo cambia.
        content_rect = QRectF(0, 0, target_w, target_h)
        margin_x, margin_y = target_w * 2, target_h * 2
        self._scene.setSceneRect(QRectF(-margin_x, -margin_y, target_w + margin_x * 2, target_h + margin_y * 2))

        self._lbl_before.setText(self.tr("Original: {0}×{1} px").format(bw, bh))
        self._lbl_after.setText(self.tr("Resultado: {0}×{1} px").format(aw, ah))
        self._lbl_before.adjustSize()
        self._lbl_after.adjustSize()
        self._lbl_before.show()
        self._lbl_after.show()
        self._handle.show()

        self._divider_fraction = 0.5
        self._update_divider()
        # Encuadrar al CONTENIDO, no a la escena (que ahora es bastante más grande) --
        # si no, el ajuste inicial saldría alejadísimo mostrando todo el margen vacío.
        self.fitInView(content_rect, Qt.KeepAspectRatio)
        self._position_chips()
        self._position_handle()

    def before_pixmap(self) -> QPixmap:
        return self._before_item.pixmap()

    def after_pixmap(self) -> QPixmap:
        return self._after_item.pixmap()

    def clear(self):
        self._before_item.setPixmap(QPixmap())
        self._after_item.setPixmap(QPixmap())
        self._content_size = None
        self._clip_rect_item.setRect(0, 0, 0, 0)
        self._after_clip_item.setRect(0, 0, 0, 0)
        self._scene.setSceneRect(0, 0, 1, 1)
        self._lbl_before.hide()
        self._lbl_after.hide()
        self._handle.hide()

    # ------------------------------------------------------------------
    # Divisor / interacción
    # ------------------------------------------------------------------
    def _update_divider(self):
        if not self._content_size:
            return
        w, h = self._content_size
        x = w * self._divider_fraction
        self._clip_rect_item.setRect(0, 0, x, h)
        self._after_clip_item.setRect(x, 0, max(0.0, w - x), h)
        self.viewport().update()

    def _divider_screen_x(self) -> float:
        if not self._content_size:
            return -1000.0
        w, _h = self._content_size
        return self.mapFromScene(QPointF(w * self._divider_fraction, 0)).x()

    def _position_handle(self):
        """Mantiene el agarre centrado en el eje Y del VIEWPORT (no de la imagen) --
        se recalcula en cada zoom/paneo/resize/arrastre, ver llamadores."""
        if not self._content_size or not self._handle.isVisible():
            return
        x = self._divider_screen_x() - _HANDLE_RADIUS
        y = self.height() / 2 - _HANDLE_RADIUS
        self._handle.move(int(x), int(y))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._content_size:
            if abs(event.position().x() - self._divider_screen_x()) <= _DIVIDER_GRAB_MARGIN:
                self._dragging_divider = True
                event.accept()
                return
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging_divider and self._content_size:
            scene_pos = self.mapToScene(event.position().toPoint())
            w, _h = self._content_size
            self._divider_fraction = max(0.0, min(1.0, scene_pos.x() / w))
            self._update_divider()
            self._position_handle()
            event.accept()
            return
        if self._panning and self._pan_start is not None:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
            self._position_handle()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging_divider:
            self._dragging_divider = False
            event.accept()
            return
        if self._panning:
            self._panning = False
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if not self._content_size:
            return
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        new_scale = self.transform().m11() * factor
        if _MIN_SCALE <= new_scale <= _MAX_SCALE:
            self.scale(factor, factor)
        self._position_handle()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_chips()
        self._position_handle()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._content_size:
            return
        # En coordenadas de VIEWPORT, no de escena -- por eso abarca el alto
        # completo del panel aunque el contenido (letterboxed por fitInView/zoom)
        # ocupe menos, ver comentario en __init__ sobre por qué ya no es un
        # QGraphicsLineItem.
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(self._divider_pen)
        x = int(self._divider_screen_x())
        painter.drawLine(x, 0, x, self.viewport().height())
        painter.end()

    def _position_chips(self):
        margin = VIEWER_CHIP_MARGIN
        self._lbl_before.move(margin, margin)
        self._lbl_after.move(max(margin, self.width() - self._lbl_after.width() - margin), margin)
