# src/gui/tabs/image_tools/layers/layer_model.py
"""Modelo de datos de las capas del Editor de Imagen -- deliberadamente sin lógica de
compositing propia: cada `Layer` es solo metadata (nombre/visibilidad/opacidad/tipo)
más una referencia al `QGraphicsItem` real que ya vive en la escena de
ZoomableImageViewer. Orden = zValue, visibilidad = item.setVisible(), opacidad =
item.setOpacity() -- todo nativo de Qt, la QGraphicsScene ya es el stack de capas."""
from PySide6.QtCore import QObject, Signal

_KINDS = ("image", "shape", "raster", "fill", "text")


class Layer:
    _next_id = 1

    def __init__(self, name: str, kind: str, graphics_item):
        assert kind in _KINDS
        self.id = Layer._next_id
        Layer._next_id += 1
        self.name = name
        self.kind = kind
        self.graphics_item = graphics_item
        self._visible = True
        self._opacity = 1.0

    @property
    def visible(self) -> bool:
        return self._visible

    def set_visible(self, visible: bool):
        self._visible = visible
        if self.graphics_item is not None:
            self.graphics_item.setVisible(visible)

    @property
    def opacity(self) -> float:
        return self._opacity

    def set_opacity(self, opacity: float):
        self._opacity = max(0.0, min(1.0, opacity))
        if self.graphics_item is not None:
            self.graphics_item.setOpacity(self._opacity)


class LayerStack(QObject):
    """Lista ordenada de abajo hacia arriba (índice 0 = fondo). `layers_changed` se
    emite tras cualquier cambio de estructura (agregar/quitar/reordenar) -- no tras
    cambios de opacidad/visibilidad de una sola capa, esos ya son instantáneos vía
    Layer.set_visible/set_opacity y no necesitan reconstruir la lista completa."""
    layers_changed = Signal()

    def __init__(self):
        super().__init__()
        self.layers: list[Layer] = []
        self.active_layer: Layer | None = None

    def add_layer(self, layer: Layer, index: int | None = None) -> Layer:
        if index is None:
            self.layers.append(layer)
        else:
            self.layers.insert(index, layer)
        self._reassign_z_values()
        self.active_layer = layer
        self.layers_changed.emit()
        return layer

    def remove_layer(self, layer: Layer):
        if layer not in self.layers:
            return
        self.layers.remove(layer)
        if layer.graphics_item is not None and layer.graphics_item.scene() is not None:
            layer.graphics_item.scene().removeItem(layer.graphics_item)
        if self.active_layer is layer:
            self.active_layer = self.layers[-1] if self.layers else None
        self._reassign_z_values()
        self.layers_changed.emit()

    def move_up(self, layer: Layer):
        i = self._index_of(layer)
        if i is None or i >= len(self.layers) - 1:
            return
        self.layers[i], self.layers[i + 1] = self.layers[i + 1], self.layers[i]
        self._reassign_z_values()
        self.layers_changed.emit()

    def move_down(self, layer: Layer):
        i = self._index_of(layer)
        if i is None or i <= 0:
            return
        self.layers[i], self.layers[i - 1] = self.layers[i - 1], self.layers[i]
        self._reassign_z_values()
        self.layers_changed.emit()

    def set_active(self, layer: Layer | None):
        self.active_layer = layer

    def clear(self):
        """Saca todas las capas de la escena (para cargar una imagen nueva) sin
        emitir un layers_changed por cada una -- una sola señal al final."""
        for layer in self.layers:
            if layer.graphics_item is not None:
                try:
                    if layer.graphics_item.scene() is not None:
                        layer.graphics_item.scene().removeItem(layer.graphics_item)
                except RuntimeError:
                    pass  # El objeto C++ subyacente ya fue destruido por Qt (ej. limpieza de escena)
        self.layers = []
        self.active_layer = None
        self.layers_changed.emit()

    def layer_for_item(self, item) -> Layer | None:
        for layer in self.layers:
            if layer.graphics_item is item:
                return layer
        return None

    def _index_of(self, layer: Layer):
        try:
            return self.layers.index(layer)
        except ValueError:
            return None

    def _reassign_z_values(self):
        for i, layer in enumerate(self.layers):
            if layer.graphics_item is not None:
                layer.graphics_item.setZValue(i)
