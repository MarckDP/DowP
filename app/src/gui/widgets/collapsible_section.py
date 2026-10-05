# src/gui/widgets/collapsible_section.py
"""
CollapsibleSection — sección con header clicable que expande/colapsa su contenido con
animación. Mismo patrón de interacción que SubtitleOptionsWidget
(gui/tabs/advanced_process/subtitle_options.py), pero genérico y con una diferencia clave:
esa clase anima hacia una EXPANDED_HEIGHT fija porque su contenido es estático, mientras que
aquí el contenido (tarjetas de Video/Audio/Transformación/Marca de agua) puede crecer o
encogerse en vivo (p.ej. marcar "Normalizar audio" agrega controles) — por eso la altura
expandida se recalcula desde el sizeHint() real del contenido en vez de ser una constante,
y al terminar de expandir se libera la altura máxima en vez de dejarla fija.
"""
from PySide6.QtCore import Qt, QEvent, Signal, QPropertyAnimation, QEasingCurve, QParallelAnimationGroup
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel, QWidget

from gui.styles import get_theme_token
from gui.styles import set_themed_style


class CollapsibleSection(QFrame):
    """Envuelve `content` con un header clicable (título + chevron, y opcionalmente un
    widget extra a la derecha, p.ej. un badge) que expande/colapsa el contenido."""

    toggled = Signal(bool)

    def __init__(self, title: str, content: QWidget, start_expanded: bool = False,
                 header_extra: QWidget = None, parent=None):
        super().__init__(parent)
        self.setObjectName("collapsibleSection")
        self._content = content
        self._is_expanded = start_expanded
        self._anim_group = None

        set_themed_style(self, lambda: f"""
            QFrame#collapsibleSection {{
                background-color: transparent;
                border: 1px solid {get_theme_token('borde_sutil', '#2d2d2d')};
                border-radius: 6px;
            }}
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.header_widget = QWidget()
        self.header_widget.setObjectName("collapsibleSectionHeader")
        self.header_widget.setCursor(Qt.PointingHandCursor)
        self.header_widget.setFixedHeight(36)
        header_layout = QHBoxLayout(self.header_widget)
        header_layout.setContentsMargins(12, 0, 12, 0)
        header_layout.setSpacing(8)

        self.chevron_label = QLabel()
        self.chevron_label.setFixedWidth(14)
        self.chevron_label.setStyleSheet("font-weight: bold;")
        header_layout.addWidget(self.chevron_label)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("sectionTitle")
        self.title_label.setStyleSheet("font-weight: bold;")
        header_layout.addWidget(self.title_label, 1)

        if header_extra is not None:
            header_layout.addWidget(header_extra, 0, Qt.AlignRight)

        self.header_widget.mousePressEvent = self._on_header_clicked
        main_layout.addWidget(self.header_widget)

        self.body_container = QWidget()
        self.body_container.setObjectName("collapsibleSectionBody")
        body_layout = QVBoxLayout(self.body_container)
        body_layout.setContentsMargins(12, 4, 12, 12)
        body_layout.setSpacing(0)
        body_layout.addWidget(content)
        main_layout.addWidget(self.body_container)

        # `content` puede crecer/encogerse en vivo (p.ej. marcar "Normalizar audio" agrega
        # controles) mucho después de expandirse — un QEvent.LayoutRequest se dispara sobre
        # `content` cada vez que su propio layout invalida su tamaño, así que lo escuchamos
        # aquí para reajustar la altura fija de la sección automáticamente, sin tener que
        # instrumentar cada uno de los toggles internos de AdvancedRecodePanel.
        content.installEventFilter(self)

        self.set_expanded(self._is_expanded, animate=False)

    def eventFilter(self, obj, event):
        if obj is self._content and event.type() == QEvent.LayoutRequest:
            is_animating = self._anim_group and self._anim_group.state() == QPropertyAnimation.Running
            if self._is_expanded and not is_animating:
                self.setFixedHeight(self._expanded_height())
        return super().eventFilter(obj, event)

    def _on_header_clicked(self, event):
        self.set_expanded(not self._is_expanded, animate=True)

    def _expanded_height(self) -> int:
        return self.header_widget.height() + self.body_container.sizeHint().height()

    def is_expanded(self) -> bool:
        return self._is_expanded

    def set_expanded(self, expanded: bool, animate: bool = True):
        self._is_expanded = expanded
        self.chevron_label.setText("▾" if expanded else "▸")

        if not animate:
            if self._anim_group and self._anim_group.state() == QPropertyAnimation.Running:
                self._anim_group.stop()
            self.body_container.setVisible(expanded)
            self.setFixedHeight(self._expanded_height() if expanded else self.header_widget.height())
            self.toggled.emit(expanded)
            return

        if self._anim_group and self._anim_group.state() == QPropertyAnimation.Running:
            self._anim_group.stop()

        start_h = self.height()
        if expanded:
            self.body_container.show()
            target_h = self._expanded_height()
        else:
            target_h = self.header_widget.height()

        anim_max = QPropertyAnimation(self, b"maximumHeight")
        anim_max.setDuration(200)
        anim_max.setStartValue(start_h)
        anim_max.setEndValue(target_h)
        anim_max.setEasingCurve(QEasingCurve.OutCubic)

        anim_min = QPropertyAnimation(self, b"minimumHeight")
        anim_min.setDuration(200)
        anim_min.setStartValue(start_h)
        anim_min.setEndValue(target_h)
        anim_min.setEasingCurve(QEasingCurve.OutCubic)

        self._anim_group = QParallelAnimationGroup(self)
        self._anim_group.addAnimation(anim_max)
        self._anim_group.addAnimation(anim_min)

        def on_finished():
            if not self._is_expanded:
                self.body_container.hide()
                self.setFixedHeight(self.header_widget.height())
            else:
                # Recalcular por si el contenido cambió de tamaño durante la animación
                # (el eventFilter ignora los LayoutRequest mientras _anim_group corre).
                self.setFixedHeight(self._expanded_height())
            self.toggled.emit(self._is_expanded)

        self._anim_group.finished.connect(on_finished)
        self._anim_group.start()
