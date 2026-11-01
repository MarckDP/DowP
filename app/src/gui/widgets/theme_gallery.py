"""Galería de temas de Ajustes > Apariencia: cada tema con su muestra, para comparar y administrar
sin tener que elegirlo primero. Solo avisa: aplicar o borrar es cosa de la página."""
from PySide6.QtCore import QEvent, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QMenu, QPushButton, QScrollArea, QVBoxLayout, QWidget

from gui.styles import get_theme_token, set_themed_style, theme_radius
from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon

CARD_WIDTH = 116
CARD_HEIGHT = 84
_NAME_HEIGHT = 22
_DARK_STATES = ("estado_exito", "estado_aviso", "estado_error", "estado_progreso")


class ThemeCard(QWidget):
    clicked = Signal(str)
    delete_clicked = Signal(str)
    menu_requested = Signal(str, object)

    def __init__(self, theme_id: str, name: str, tokens: dict, image: str | None, deletable: bool, parent=None):
        super().__init__(parent)
        self.theme_id, self.name = theme_id, name
        self._tokens = tokens
        self._image = QPixmap(image).scaled(CARD_WIDTH, CARD_HEIGHT, Qt.KeepAspectRatioByExpanding,
                                            Qt.SmoothTransformation) if image else None
        self.draft = self.saved = False
        self.deletable = deletable
        self.setFixedSize(CARD_WIDTH, CARD_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(name)
        self.btn_delete = None
        if deletable:
            self.btn_delete = QPushButton(self)
            self.btn_delete.setFixedSize(20, 20)
            self.btn_delete.move(CARD_WIDTH - 24, 4)
            self.btn_delete.setCursor(Qt.PointingHandCursor)
            self.btn_delete.setIcon(get_colored_svg_icon("delete.svg", "#ffffff", 12))
            self.btn_delete.setIconSize(QSize(12, 12))
            self.btn_delete.setToolTip(self.tr("Eliminar (va a la Papelera)"))
            self.btn_delete.setStyleSheet("QPushButton { background-color: rgba(0, 0, 0, 150); border: none; border-radius: 4px; }"
                                          "QPushButton:hover { background-color: rgba(200, 40, 40, 220); }")
            self.btn_delete.clicked.connect(lambda: self.delete_clicked.emit(self.theme_id))

    def set_marks(self, draft: bool, saved: bool):
        self.draft, self.saved = draft, saved
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.theme_id)

    def contextMenuEvent(self, event):
        self.menu_requested.emit(self.theme_id, event.globalPos())

    def _c(self, key, fallback="#808080"):
        color = QColor(self._tokens.get(key, fallback))
        return color if color.isValid() else QColor(fallback)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        frame = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = theme_radius(8)
        path = QPainterPath()
        path.addRoundedRect(frame, radius, radius)
        p.save()
        p.setClipPath(path)
        p.fillRect(frame, self._c("fondo_principal"))
        if self._image is not None and not self._image.isNull():
            p.setOpacity(0.75)
            p.drawPixmap(0, 0, self._image)
            p.setOpacity(1)
        panel = QRectF(frame.left() + 8, frame.top() + 8, frame.width() - 16, frame.height() - _NAME_HEIGHT - 12)
        back = self._c("fondo_secundario")
        back.setAlphaF(0.75 if self._image is not None else 1)
        p.setPen(Qt.NoPen)
        p.setBrush(back)
        p.drawRoundedRect(panel, 3, 3)
        button = QRectF(panel.left() + 5, panel.top() + 6, panel.width() * 0.62, 12)
        gradient = QLinearGradient(button.topLeft(), button.topRight())
        gradient.setColorAt(0, self._c("boton_fondo_inicio"))
        gradient.setColorAt(1, self._c("boton_fondo_fin"))
        p.setBrush(gradient)
        p.drawRoundedRect(button, 3, 3)
        for i, key in enumerate(_DARK_STATES):
            p.setBrush(self._c(key))
            p.drawEllipse(QRectF(panel.left() + 5 + i * 10, button.bottom() + 6, 7, 7))
        name_rect = QRectF(frame.left(), frame.bottom() - _NAME_HEIGHT, frame.width(), _NAME_HEIGHT)
        p.fillRect(name_rect, QColor(get_theme_token("panel_fondo", "#181818")))
        p.restore()
        font = p.font()
        font.setPixelSize(10)
        p.setFont(font)
        p.setPen(QColor(get_theme_token("texto_principal", "#e0e0e0")))
        text = QFontMetrics(font).elidedText(self.name, Qt.ElideRight, int(frame.width() - 10))
        p.drawText(name_rect, Qt.AlignCenter, text)
        token, width = ("acento_primario", 2) if self.draft else ("texto_secundario", 2) if self.saved else ("borde_sutil", 1)
        p.setPen(QPen(QColor(get_theme_token(token, "#333333")), width))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        p.end()


class ThemeGallery(QWidget):
    selected = Signal(str)
    delete_requested = Signal(list)
    action_requested = Signal(str, str)  # (accion, id)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._signature = None
        self._cards = {}
        self._headers = []
        self._draft = self._saved = None
        self._columns = 0
        self.unsaved_ids = ()  # borradores: aún sin archivo, solo se pueden aplicar o eliminar
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # El ancho que cuenta es el del área visible, que se fija después que el de la galería.
        self.scroll.viewport().installEventFilter(self)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.content = QWidget()
        self.content.setObjectName("themeGalleryContent")
        self.content.setStyleSheet("QWidget#themeGalleryContent { background: transparent; }")
        self.grid = QGridLayout(self.content)
        self.grid.setContentsMargins(0, 0, 6, 0)
        self.grid.setSpacing(6)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.scroll.setWidget(self.content)
        root.addWidget(self.scroll)
        self.set_minimum_columns(3)

    def set_themes(self, items: list, tokens_for, image_for, deletable_for, draft: str, saved: str, force=False):
        """items: [(id, nombre, grupo)]. Se reconstruye solo si cambió la lista o el modo."""
        signature = (tuple(items), tokens_for("__modo__"))
        if force or signature != self._signature:
            self._signature = signature
            bar = self.scroll.verticalScrollBar()
            position = bar.value()
            self._rebuild(items, tokens_for, image_for, deletable_for)
            bar.setValue(min(position, bar.maximum()))  # _layout_cards ya dejó el rango al día
        changed = draft != self._draft
        self._draft, self._saved = draft, saved
        self._update_marks()
        if changed and draft in self._cards:  # el tema activo puede estar más abajo
            QTimer.singleShot(0, lambda: self._draft in self._cards and self.scroll.ensureWidgetVisible(self._cards[self._draft], 0, 20))

    def _rebuild(self, items, tokens_for, image_for, deletable_for):
        for card in self._cards.values():
            card.setParent(None)
            card.deleteLater()
        for header in self._headers:
            header.setParent(None)
            header.deleteLater()
        self._cards, self._headers = {}, []
        self._groups = {}
        for theme_id, name, group in items:
            self._groups.setdefault(group, []).append(theme_id)
            card = ThemeCard(theme_id, name, tokens_for(theme_id), image_for(theme_id), deletable_for(theme_id), self.content)
            card.clicked.connect(self.selected)
            card.delete_clicked.connect(lambda t: self.delete_requested.emit([t]))
            card.menu_requested.connect(self._show_menu)
            self._cards[theme_id] = card
        self._layout_cards()

    def _layout_cards(self):
        columns = self._fitting_columns()
        self._columns = columns
        while self.grid.count():
            self.grid.takeAt(0)
        for header in self._headers:
            header.setParent(None)
            header.deleteLater()
        self._headers = []
        row = 0
        for group, ids in getattr(self, "_groups", {}).items():
            header = QLabel(group, self.content)
            set_themed_style(header, lambda: f"color: {get_theme_token('texto_tenue', '#888888')}; font-size: 10px; font-weight: bold;")
            header.show()
            self.grid.addWidget(header, row, 0, 1, columns)
            self._headers.append(header)
            row += 1
            for i, theme_id in enumerate(ids):
                self.grid.addWidget(self._cards[theme_id], row + i // columns, i % columns)
            row += (len(ids) + columns - 1) // columns
        self._fix_content_height()

    def _fix_content_height(self):
        """Fija el alto ya mismo: si se deja a Qt, recalcula más tarde y mientras tanto el rango
        del scroll cae a 0, y la página vuelve arriba al borrar un tema."""
        spacing = self.grid.spacing()
        rows = 0
        height = 0
        for header, ids in zip(self._headers, self._groups.values()):
            card_rows = (len(ids) + self._columns - 1) // self._columns
            height += header.sizeHint().height() + card_rows * CARD_HEIGHT
            rows += 1 + card_rows
        height += max(0, rows - 1) * spacing
        self.content.setMinimumHeight(height)
        self.content.resize(self.scroll.viewport().width(), max(height, self.scroll.viewport().height()))

    def width_for_columns(self, columns: int) -> int:
        # 20: el sitio de la barra (ver _fitting_columns).
        return columns * CARD_WIDTH + (columns - 1) * self.grid.spacing() + 20 + self.grid.contentsMargins().right()

    def set_minimum_columns(self, columns: int):
        self.setMinimumWidth(self.width_for_columns(columns))

    def _fitting_columns(self) -> int:
        margins = self.grid.contentsMargins()
        spacing = self.grid.spacing()
        # Se reserva siempre el sitio de la barra: si apareciera según el contenido cambiaría el
        # ancho, y con él las columnas y el contenido otra vez.
        bar = self.scroll.verticalScrollBar().sizeHint().width()
        available = self.scroll.width() - bar - margins.left() - margins.right()
        return max(1, (available + spacing) // (CARD_WIDTH + spacing))

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize and self._cards and self._fitting_columns() != self._columns:
            self._layout_cards()
        return False

    def _update_marks(self):
        for theme_id, card in self._cards.items():
            card.set_marks(theme_id == self._draft, theme_id == self._saved)

    def _show_menu(self, theme_id: str, position):
        card = self._cards[theme_id]
        menu = QMenu(self)
        menu.addAction(self.tr("Aplicar"), lambda: self.action_requested.emit("apply", theme_id))
        if theme_id in self.unsaved_ids:
            menu.addAction(self.tr("Eliminar"), lambda: self.delete_requested.emit([theme_id]))
            menu.exec(position)
            return
        export = menu.addAction(self.tr("Exportar…"), lambda: self.action_requested.emit("export", theme_id))
        export.setEnabled(theme_id == self._saved and theme_id == self._draft)
        if not export.isEnabled():
            export.setToolTip(self.tr("Aplica este tema para exportarlo"))
        menu.addSeparator()
        menu.addAction(self.tr("Duplicar"), lambda: self.action_requested.emit("duplicate", theme_id))
        if card.deletable:
            menu.addAction(self.tr("Renombrar…"), lambda: self.action_requested.emit("rename", theme_id))
            menu.addSeparator()
            menu.addAction(self.tr("Eliminar"), lambda: self.delete_requested.emit([theme_id]))
        menu.exec(position)
