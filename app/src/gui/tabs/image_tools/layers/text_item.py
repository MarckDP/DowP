# src/gui/tabs/image_tools/layers/text_item.py
"""Capa de texto del Editor de Imagen: un QGraphicsTextItem que se edita escribiendo
directamente sobre la imagen (edición en línea de Qt) y cuyo estilo -- fuente, tamaño,
color, negrita, cursiva, alineación -- se aplica al texto entero, igual que una capa
de texto simple de Photoshop.

El estilo vive en un dict (ver DEFAULT_TEXT_STYLE) para poder guardarlo, compararlo y
restaurarlo desde el historial sin tocar el contenido."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QTextOption, QTextCursor
from PySide6.QtWidgets import QGraphicsTextItem

DEFAULT_TEXT_STYLE = {
    "family": "",        # "" = fuente por defecto del sistema
    "size": 48,          # px de la imagen
    "color": "#000000",
    "bold": False,
    "italic": False,
    "align": "left",     # left | center | right
}

_ALIGN = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight}


class EditableTextItem(QGraphicsTextItem):
    """Texto editable sobre la imagen. Fuera de edición no acepta interacción de
    texto (así Seleccionar lo puede arrastrar como cualquier capa); el visor lo pone
    en modo edición con start_editing() y lo saca con stop_editing().

    finish_requested: el usuario pidió terminar de escribir (Esc o Ctrl+Enter). El
    visor es quien decide cerrar la edición, porque también la cierra por otras vías
    (clic afuera, cambio de herramienta o de archivo)."""
    finish_requested = Signal()

    def __init__(self, style: dict | None = None, text: str = "", parent=None):
        super().__init__(parent)
        self._style = dict(DEFAULT_TEXT_STYLE)
        self.setTextInteractionFlags(Qt.NoTextInteraction)
        self.document().setDocumentMargin(2)
        self.document().contentsChanged.connect(self._reflow)
        self.apply_style(style or {})
        if text:
            self.setPlainText(text)

    # -- Estilo ---------------------------------------------------------------
    def style(self) -> dict:
        return dict(self._style)

    def apply_style(self, style: dict):
        self._style.update({k: v for k, v in style.items() if k in DEFAULT_TEXT_STYLE})
        s = self._style
        font = QFont(s["family"]) if s["family"] else QFont()
        font.setPixelSize(max(1, int(s["size"])))
        font.setBold(bool(s["bold"]))
        font.setItalic(bool(s["italic"]))
        self.setFont(font)
        self.setDefaultTextColor(QColor(s["color"]))
        option = self.document().defaultTextOption()
        option.setAlignment(_ALIGN.get(s["align"], Qt.AlignLeft))
        self.document().setDefaultTextOption(option)
        self._reflow()

    def _reflow(self):
        """La alineación centrada/derecha solo tiene efecto con un ancho fijo: se fija
        al ancho natural del texto (la línea más larga), así las demás se alinean
        respecto de ella y el cuadro sigue midiendo lo que mide el texto."""
        if self._style["align"] == "left":
            if self.textWidth() != -1:
                self.setTextWidth(-1)
            return
        self.setTextWidth(-1)
        self.setTextWidth(self.document().idealWidth())

    # -- Edición --------------------------------------------------------------
    def is_editing(self) -> bool:
        return bool(self.textInteractionFlags() & Qt.TextEditorInteraction)

    def start_editing(self, select_all: bool = False):
        self.setTextInteractionFlags(Qt.TextEditorInteraction)
        self.setFocus(Qt.MouseFocusReason)
        cursor = self.textCursor()
        if select_all:
            cursor.select(QTextCursor.Document)
        else:
            cursor.movePosition(QTextCursor.End)
        self.setTextCursor(cursor)

    def stop_editing(self):
        cursor = self.textCursor()
        cursor.clearSelection()
        self.setTextCursor(cursor)
        self.setTextInteractionFlags(Qt.NoTextInteraction)
        self.clearFocus()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape or (
                event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() & Qt.ControlModifier):
            self.finish_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def clone(self) -> "EditableTextItem":
        copy = EditableTextItem(self.style(), self.toPlainText())
        copy.setPos(self.pos())
        copy.setTransform(self.transform())
        return copy
