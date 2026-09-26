# src/gui/tabs/image_tools/tool_rail.py
from math import ceil

from PySide6.QtCore import QSize, Signal
from PySide6.QtWidgets import QFrame


class ToolRail(QFrame):
    """Barra vertical de herramientas que se reacomoda según el alto disponible, en vez de
    dejar que Qt monte los botones unos sobre otros cuando no caben (lo que pasaba con el
    QVBoxLayout anterior: los botones son de tamaño fijo y lo único que podía ceder era el
    espaciado).

    Disposiciones, en orden de preferencia -- se usa la primera que entra en el alto actual:
      1. Una columna, espaciado normal.
      2. Una columna, espaciado compacto.
      3. Dos columnas (como la caja de herramientas de Photoshop): la barra se ensancha.

    Los botones siguen siendo los mismos widgets en cualquier modo (solo cambia su
    posición), así que los popovers anclados a ellos y los atajos no se enteran.

    Los grupos se separan con addSeparator(); en dos columnas cada grupo se reparte por
    separado, para que una fila nunca mezcle herramientas de grupos distintos."""

    layout_changed = Signal()  # los botones se movieron (p.ej. para reubicar popovers abiertos)

    BUTTON = 32
    MARGIN_X = 4
    MARGIN_Y = 10
    COLUMN_GAP = 4
    # (columnas, espaciado vertical)
    MODES = ((1, 6), (1, 3), (2, 3))

    def __init__(self, parent=None):
        super().__init__(parent)
        self._groups = [[]]
        self._separators = []
        self._columns = 1
        self.setFixedWidth(self._width_for(1))

    # ── API tipo layout ────────────────────────────────────────────────────────
    def addWidget(self, widget):
        widget.setParent(self)
        self._groups[-1].append(widget)
        widget.show()
        self._relayout()

    def addSeparator(self, separator):
        separator.setParent(self)
        self._separators.append(separator)
        self._groups.append([])
        separator.show()
        self._relayout()

    # ── Geometría ──────────────────────────────────────────────────────────────
    def _width_for(self, columns):
        return 2 * self.MARGIN_X + columns * self.BUTTON + (columns - 1) * self.COLUMN_GAP

    def _visible_groups(self):
        return [[w for w in g if not w.isHidden()] for g in self._groups]

    def _height_for(self, columns, spacing):
        groups = self._visible_groups()
        h = 2 * self.MARGIN_Y
        for i, group in enumerate(groups):
            if i > 0:
                h += 2 * spacing + 1  # separador de 1 px con aire a ambos lados
            rows = ceil(len(group) / columns)
            if rows:
                h += rows * self.BUTTON + (rows - 1) * spacing
        return h

    def _pick_mode(self, available_height):
        for columns, spacing in self.MODES:
            if self._height_for(columns, spacing) <= available_height:
                return columns, spacing
        return self.MODES[-1]

    def minimumSizeHint(self):
        columns, spacing = self.MODES[-1]
        return QSize(self._width_for(self._columns), self._height_for(columns, spacing))

    def sizeHint(self):
        columns, spacing = self.MODES[0]
        return QSize(self._width_for(self._columns), self._height_for(columns, spacing))

    def current_width(self):
        return self._width_for(self._columns)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self):
        columns, spacing = self._pick_mode(self.height())
        if columns != self._columns:
            self._columns = columns
            # Solo cambia el ancho; el modo depende del alto, así que no hay bucle.
            self.setFixedWidth(self._width_for(columns))

        width = self._width_for(columns)
        content_w = columns * self.BUTTON + (columns - 1) * self.COLUMN_GAP
        x0 = (width - content_w) // 2
        y = self.MARGIN_Y

        for i, group in enumerate(self._visible_groups()):
            if i > 0:
                sep = self._separators[i - 1]
                y += spacing
                sep.setGeometry(self.MARGIN_X + 2, y, width - 2 * (self.MARGIN_X + 2), 1)
                y += 1 + spacing
            for idx, widget in enumerate(group):
                row, col = divmod(idx, columns)
                widget.move(x0 + col * (self.BUTTON + self.COLUMN_GAP),
                            y + row * (self.BUTTON + spacing))
            rows = ceil(len(group) / columns)
            if rows:
                y += rows * self.BUTTON + (rows - 1) * spacing

        self.layout_changed.emit()
