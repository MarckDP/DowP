# src/gui/widgets/top_aligned_layout.py
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout


class TopAlignedVBoxLayout(QVBoxLayout):
    """QVBoxLayout que apila su contenido arriba sin recortar textos con ajuste de línea.

    Reemplaza el patrón `layout.setAlignment(Qt.AlignTop)`: con esa alineación Qt le da al
    layout su sizeHint y no recalcula la altura de los QLabel con wordWrap al angostarse
    la ventana, así que la segunda línea de una descripción quedaba cortada. Aquí el
    contenido queda arriba gracias a un stretch final que se mantiene SIEMPRE último:
    addWidget/addLayout/... insertan antes de él, así que las filas que se agregan más
    tarde (listas que se recargan) siguen quedando en orden y arriba."""

    def __init__(self, parent=None):
        super().__init__(parent)
        super().addStretch(1)

    def _tail(self):
        return max(0, self.count() - 1)

    def addWidget(self, widget, stretch=0, alignment=Qt.Alignment()):
        self.insertWidget(self._tail(), widget, stretch, alignment)

    def addLayout(self, layout, stretch=0):
        self.insertLayout(self._tail(), layout, stretch)

    def addSpacing(self, size):
        self.insertSpacing(self._tail(), size)

    def addStretch(self, stretch=0):
        self.insertStretch(self._tail(), stretch)
