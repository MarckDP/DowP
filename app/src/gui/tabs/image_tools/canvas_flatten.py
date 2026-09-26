# src/gui/tabs/image_tools/canvas_flatten.py
"""Aplanado de formas/pincel/Canvas manual a un único QImage para exportar --
standalone (no vive adentro de ZoomableImageViewer, mismo criterio ya aplicado
con CompareViewer) para no seguir engordando esa clase.

Clona los QGraphicsItem en vez de reusar los reales: así una exportación nunca
corre riesgo de mover/perder algo de la sesión de edición en vivo del usuario --
la escena temporal que arma esta función es 100% descartable."""
from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import (
    QGraphicsScene, QGraphicsRectItem, QGraphicsEllipseItem,
    QGraphicsLineItem, QGraphicsPixmapItem,
)

from gui.tabs.image_tools.layers.layer_model import Layer
from gui.tabs.image_tools.layers.text_item import EditableTextItem


def _clone_item(item):
    """Copia geometría+pen+brush (formas/línea) o pixmap+pos (pincel) -- None si
    el tipo no es ninguno de los que puede producir el editor (ver
    zoomable_image_viewer.py::_make_shape_item/_press_layers_draw/_create_raster_layer)."""
    if isinstance(item, EditableTextItem):
        clone = item.clone()
    elif isinstance(item, QGraphicsRectItem):
        clone = QGraphicsRectItem(item.rect())
        clone.setPen(item.pen())
        clone.setBrush(item.brush())
    elif isinstance(item, QGraphicsEllipseItem):
        clone = QGraphicsEllipseItem(item.rect())
        clone.setPen(item.pen())
        clone.setBrush(item.brush())
    elif isinstance(item, QGraphicsLineItem):
        clone = QGraphicsLineItem(item.line())
        clone.setPen(item.pen())
    elif isinstance(item, QGraphicsPixmapItem):
        clone = QGraphicsPixmapItem(item.pixmap())
        clone.setPos(item.pos())
    else:
        return None
    clone.setTransform(item.transform())
    return clone


def rasterize_item(item):
    """Convierte una forma/línea/fondo en un QGraphicsPixmapItem equivalente (para
    poder borrarla con el Borrador, como "Rasterizar capa" en Photoshop). La capa de
    píxeles ocupa el área real del item -- no la de la imagen: una forma puede salirse
    de la imagen (lienzo agrandado con Canvas) y así no se corta. Una unidad de escena
    es un píxel de la imagen, así que sale a la misma resolución con que se exporta.
    Reusa _clone_item (mismo criterio que el aplanado), sin opacidad: esa la sigue
    llevando la capa. None si el item no es de un tipo conocido o no tiene área."""
    clone = _clone_item(item)
    if clone is None:
        return None
    rect = item.sceneBoundingRect().toAlignedRect()
    if rect.width() <= 0 or rect.height() <= 0:
        return None
    scene = QGraphicsScene()
    scene.addItem(clone)
    image = QImage(rect.width(), rect.height(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    scene.render(painter, QRectF(0, 0, rect.width(), rect.height()), QRectF(rect))
    painter.end()
    result = QGraphicsPixmapItem(QPixmap.fromImage(image))
    result.setPos(rect.topLeft())
    return result


def build_flattened_image(base_pixmap: QPixmap, canvas_state: dict | None, layers: list[Layer],
                          base_mask: QImage | None = None) -> QImage:
    """Compone `base_pixmap` (posicionada/escalada según `canvas_state`, o a
    tamaño nativo si no hay override) más las `layers` visibles no-"image" (formas/
    pincel del usuario) sobre el área de `canvas_state["canvas_rect"]` (o el propio
    tamaño de `base_pixmap` si no hay canvas_state), devolviendo un QImage RGBA listo
    para guardarse como el archivo de origen "real" a convertir.

    `base_mask` es lo que el Borrador quitó de la imagen base (ver
    ZoomableImageViewer.base_mask): se aplica antes de componer, con la misma
    función que usa el visor, así el resultado coincide con lo que se veía."""
    if base_mask is not None:
        from gui.widgets.zoomable_image_viewer import apply_alpha_mask
        base_pixmap = QPixmap.fromImage(apply_alpha_mask(base_pixmap.toImage(), base_mask))
    scene = QGraphicsScene()

    base_item = scene.addPixmap(base_pixmap)
    if canvas_state is not None:
        sx, sy = canvas_state.get("image_scale", (1.0, 1.0))
        base_item.setTransform(QTransform().scale(sx, sy))
        base_item.setPos(canvas_state["image_pos"])
        canvas_rect = QRectF(canvas_state["canvas_rect"])
    else:
        canvas_rect = QRectF(0, 0, base_pixmap.width(), base_pixmap.height())

    for layer in layers:
        if layer.kind == "image" or not layer.visible or layer.graphics_item is None:
            continue
        clone = _clone_item(layer.graphics_item)
        if clone is None:
            continue
        clone.setOpacity(layer.opacity)
        clone.setZValue(layer.graphics_item.zValue())
        scene.addItem(clone)

    w = max(1, round(canvas_rect.width()))
    h = max(1, round(canvas_rect.height()))
    image = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    scene.render(painter, QRectF(0, 0, w, h), canvas_rect)
    painter.end()
    return image
