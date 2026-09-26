# src/gui/tabs/image_tools/layers/history.py
"""Deshacer/Rehacer del Editor de Imagen: un QUndoCommand por tipo de acción.

Convenciones:
  - La acción YA ocurrió cuando se registra (el usuario dibujó, borró, movió...), así
    que el primer redo() -- el que QUndoStack.push() ejecuta solo -- se salta. Los
    siguientes redo() sí la rehacen.
  - Los comandos no tocan la escena ni el LayerStack directamente: llaman a helpers
    de ImageToolsTab (`tab._history_*`), que ya saben mantener sincronizados escena,
    lista de capas, panel y visor.
  - La imagen base se referencia de forma simbólica (item None), nunca por objeto: al
    volver a un archivo, el visor crea un QGraphicsPixmapItem nuevo para ella, y un
    comando que guardara el viejo quedaría apuntando a un item muerto.
  - Pasos "de arrastre" (opacidad, estilo de la forma seleccionada) se fusionan si
    llegan seguidos (MERGE_WINDOW): mover una barra es UN paso, no uno por valor."""
import time

from PySide6.QtGui import QImage, QUndoCommand

MERGE_WINDOW = 1.5  # segundos entre cambios para considerarlos el mismo gesto

_ID_OPACITY = 1001
_ID_STYLE = 1002
_ID_NUDGE = 1003
_ID_TEXT_STYLE = 1004


class _EditorCommand(QUndoCommand):
    def __init__(self, tab, text, parent=None):
        super().__init__(text, parent)
        self.tab = tab
        self._skip_first_redo = True

    def redo(self):
        if self._skip_first_redo:
            self._skip_first_redo = False
            return
        self._apply(redo=True)
        self.tab._history_after_change()

    def undo(self):
        self._skip_first_redo = False
        self._apply(redo=False)
        self.tab._history_after_change()

    def _apply(self, redo: bool):
        raise NotImplementedError


class MacroCommand(QUndoCommand):
    """Varios comandos como UN paso (ej. la capa de pincel nueva + su primer trazo).
    Los hijos NO se cuelgan como hijos Qt (parent=): con eso Qt y Python se
    disputaban la propiedad -- Python los liberaba (crash al deshacer) o los dos los
    liberaban (heap corrupto al cerrar). Aquí son objetos Python normales en una
    lista, y este comando los ejecuta en orden (rehacer) y al revés (deshacer)."""

    def __init__(self, text):
        super().__init__(text)
        self._children = []

    def add(self, command_cls, *args, **kwargs):
        child = command_cls(*args, **kwargs)
        self._children.append(child)
        return child

    def redo(self):
        for child in self._children:
            child.redo()

    def undo(self):
        for child in reversed(self._children):
            child.undo()


class AddLayerCommand(_EditorCommand):
    """Capa nueva (forma, fondo, pincel): deshacer la quita, rehacer la repone."""

    def __init__(self, tab, text, layer, index, parent=None):
        super().__init__(tab, text, parent)
        self.layer = layer
        self.index = index

    def _apply(self, redo):
        if redo:
            self.tab._history_insert_layer(self.layer, self.index)
        else:
            self.tab._history_remove_layer(self.layer)


class RemoveLayerCommand(AddLayerCommand):
    """Capa borrada: el inverso exacto de AddLayerCommand (vuelve a su mismo lugar)."""

    def _apply(self, redo):
        super()._apply(not redo)


class MoveLayerCommand(_EditorCommand):
    def __init__(self, tab, text, layer, up: bool, parent=None):
        super().__init__(tab, text, parent)
        self.layer = layer
        self.up = up

    def _apply(self, redo):
        stack = self.tab.layer_stack
        (stack.move_up if redo == self.up else stack.move_down)(self.layer)


class VisibilityCommand(_EditorCommand):
    def __init__(self, tab, text, layer, visible: bool, parent=None):
        super().__init__(tab, text, parent)
        self.layer = layer
        self.visible = visible

    def _apply(self, redo):
        self.layer.set_visible(self.visible if redo else not self.visible)


class OpacityCommand(_EditorCommand):
    def __init__(self, tab, text, layer, before: float, after: float, parent=None):
        super().__init__(tab, text, parent)
        self.layer = layer
        self.before = before
        self.after = after
        self.stamp = time.monotonic()

    def id(self):
        return _ID_OPACITY

    def mergeWith(self, other):
        if other.layer is not self.layer or other.stamp - self.stamp > MERGE_WINDOW:
            return False
        self.after = other.after
        self.stamp = other.stamp
        return True

    def _apply(self, redo):
        self.layer.set_opacity(self.after if redo else self.before)


class RasterizeCommand(_EditorCommand):
    """Forma/fondo -> píxeles: deshacer devuelve el item vectorial original."""

    def __init__(self, tab, text, layer, old_item, old_kind, new_item, parent=None):
        super().__init__(tab, text, parent)
        self.layer = layer
        self.old_item, self.old_kind = old_item, old_kind
        self.new_item = new_item

    def _apply(self, redo):
        if redo:
            self.tab._history_swap_item(self.layer, self.new_item, "raster")
        else:
            self.tab._history_swap_item(self.layer, self.old_item, self.old_kind)


class PixelPatchCommand(_EditorCommand):
    """Trazo de Pincel/Borrador: guarda solo el recuadro que tocó (antes y después),
    no la imagen entera -- un trazo chico sobre una foto grande pesa unos KB.
    `item` None = la máscara de la imagen base."""

    def __init__(self, tab, text, item, rect, before, after, parent=None):
        super().__init__(tab, text, parent)
        self.item = item
        self.rect = rect
        self.before = before
        self.after = after

    def _apply(self, redo):
        self.tab._history_apply_pixels(self.item, self.rect, self.after if redo else self.before)


class RasterGrowCommand(_EditorCommand):
    """Capa de píxeles agrandada para que entrara un trazo. Va en el mismo paso que el
    trazo: deshacer devuelve la capa a su tamaño y posición originales, así los pasos
    anteriores (guardados con esas coordenadas) siguen cuadrando. Guarda solo la
    imagen chica de antes; la grande se rearma al rehacer."""

    def __init__(self, tab, text, item, old_image, old_pos, new_pos, new_size, parent=None):
        super().__init__(tab, text, parent)
        self.item = item
        self.old_image = old_image
        self.old_pos, self.new_pos, self.new_size = old_pos, new_pos, new_size

    def _apply(self, redo):
        viewer = self.tab.preview.zoom_viewer
        if redo:
            grown = viewer.grown_image(self.old_image, self.old_pos, self.new_pos, self.new_size)
            viewer.set_raster_content(self.item, grown, self.new_pos)
        else:
            viewer.set_raster_content(self.item, QImage(self.old_image), self.old_pos)


class GeometryCommand(_EditorCommand):
    """Mover/redimensionar una forma, línea o capa de píxeles."""

    def __init__(self, tab, text, item, before, after, parent=None):
        super().__init__(tab, text, parent)
        self.item = item
        self.before = before
        self.after = after

    def _apply(self, redo):
        self.tab._history_set_geometry(self.item, self.after if redo else self.before)


class NudgeCommand(GeometryCommand):
    """Mover con las flechas del teclado: pulsaciones seguidas sobre la misma capa
    se fusionan en un solo paso (como arrastrar una barra)."""

    def __init__(self, tab, text, item, before, after, parent=None):
        super().__init__(tab, text, item, before, after, parent)
        self.stamp = time.monotonic()

    def id(self):
        return _ID_NUDGE

    def mergeWith(self, other):
        if other.item is not self.item or other.stamp - self.stamp > MERGE_WINDOW:
            return False
        self.after = other.after
        self.stamp = other.stamp
        return True


class StyleCommand(_EditorCommand):
    """Estilo de la forma seleccionada (relleno o borde, cambiado desde sus opciones).
    `before`/`after` son (brush, pen)."""

    def __init__(self, tab, text, item, before, after, parent=None):
        super().__init__(tab, text, parent)
        self.item = item
        self.before = before
        self.after = after
        self.stamp = time.monotonic()

    def id(self):
        return _ID_STYLE

    def mergeWith(self, other):
        if other.item is not self.item or other.stamp - self.stamp > MERGE_WINDOW:
            return False
        self.after = other.after
        self.stamp = other.stamp
        return True

    def _apply(self, redo):
        self.tab._history_set_style(self.item, *(self.after if redo else self.before))


class TextContentCommand(_EditorCommand):
    """Lo escrito en un texto (una sesión de edición completa = un paso; mientras se
    escribe, Ctrl+Z es el deshacer propio del cuadro de texto)."""

    def __init__(self, tab, text, item, before: str, after: str, parent=None):
        super().__init__(tab, text, parent)
        self.item = item
        self.before = before
        self.after = after

    def _apply(self, redo):
        self.item.setPlainText(self.after if redo else self.before)
        self.tab._rename_text_layer_for(self.item)


class TextStyleCommand(_EditorCommand):
    """Fuente/tamaño/color/negrita/cursiva/alineación de un texto. Cambios seguidos
    (arrastrar la barra de tamaño) se fusionan en un paso."""

    def __init__(self, tab, text, item, before: dict, after: dict, parent=None):
        super().__init__(tab, text, parent)
        self.item = item
        self.before = before
        self.after = after
        self.stamp = time.monotonic()

    def id(self):
        return _ID_TEXT_STYLE

    def mergeWith(self, other):
        if other.item is not self.item or other.stamp - self.stamp > MERGE_WINDOW:
            return False
        self.after = other.after
        self.stamp = other.stamp
        return True

    def _apply(self, redo):
        self.item.apply_style(self.after if redo else self.before)


class TextResizeCommand(_EditorCommand):
    """Tamaño de un texto cambiado arrastrando un tirador: estilo y posición juntos
    (la posición se corrige para que la esquina opuesta no se mueva)."""

    def __init__(self, tab, text, item, before, after, parent=None):
        super().__init__(tab, text, parent)
        self.item = item
        self.before = before   # (estilo, QPointF)
        self.after = after

    def _apply(self, redo):
        style, pos = self.after if redo else self.before
        self.item.apply_style(style)
        self.item.setPos(pos)


class CanvasCommand(_EditorCommand):
    """Ajuste manual de Canvas (arrastre de tiradores o de la imagen). Guarda el
    estado del visor y el override por archivo de antes y después: sin override
    previo, deshacer lo quita en vez de dejar uno igual al estado inicial."""

    def __init__(self, tab, text, filepath, before_state, after_state, before_override, parent=None):
        super().__init__(tab, text, parent)
        self.filepath = filepath
        self.before_state = before_state
        self.after_state = after_state
        self.before_override = before_override

    def _apply(self, redo):
        if redo:
            self.tab._history_set_canvas(self.filepath, self.after_state, self.after_state)
        else:
            self.tab._history_set_canvas(self.filepath, self.before_state, self.before_override)
