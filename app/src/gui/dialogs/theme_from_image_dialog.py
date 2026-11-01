"""Crear un tema a partir de una imagen: se elige una de sus variantes y, si hace falta, otro
acento. Los colores los calcula core/utils/theme_palette.py; aquí solo se eligen."""
import os

from PySide6.QtCore import QEvent, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QRadioButton, QScrollArea, QLabel, QLayout,
                               QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from core.utils import background_images as bg
from core.utils import theme_io, theme_palette as tp
from gui.styles import get_theme_token, set_button_variant, set_themed_style, theme_radius
from gui.widgets.title_bar import CustomTitleBar

_IMAGE_FILTER = "*.png *.jpg *.jpeg *.webp *.bmp"
_DARK, _LIGHT = 1, 0
_CARD_WIDTH = 132
_CONTENT_WIDTH = 5 * _CARD_WIDTH + 4 * 10  # las variantes, en fila


class _VariantCard(QWidget):
    """Una ventanita de muestra pintada con los colores de la variante, en claro y oscuro."""

    clicked = Signal()

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._title = title
        self._colors = None
        self._selected = False
        self.setFixedSize(_CARD_WIDTH, 128)
        self.setCursor(Qt.PointingHandCursor)

    def set_colors(self, colors: dict):
        self._colors = colors
        self.update()

    def set_selected(self, selected: bool):
        self._selected = selected
        self.update()

    def mouseReleaseEvent(self, event):
        if self.rect().contains(event.position().toPoint()):
            self.clicked.emit()

    def _paint_mode(self, p: QPainter, area: QRectF, mode: int):
        c = lambda key: QColor(self._colors[key][mode])
        p.fillRect(area, c("fondo_principal"))
        panel = area.adjusted(6, 6, -6, -6)
        p.setPen(Qt.NoPen)
        p.setBrush(c("fondo_secundario"))
        p.drawRoundedRect(panel, 4, 4)
        p.setPen(c("texto_principal"))
        font = p.font()
        font.setPixelSize(10)
        p.setFont(font)
        p.drawText(panel.adjusted(6, 4, -4, 0), Qt.AlignLeft | Qt.AlignTop, "DowP")
        button = QRectF(panel.left() + 6, panel.top() + 22, panel.width() - 12, 20)
        gradient = QLinearGradient(button.topLeft(), button.topRight())
        gradient.setColorAt(0, c("boton_fondo_inicio"))
        gradient.setColorAt(1, c("boton_fondo_fin"))
        p.setPen(Qt.NoPen)
        p.setBrush(gradient)
        p.drawRoundedRect(button, 4, 4)
        p.setPen(c("boton_texto"))
        p.drawText(button, Qt.AlignCenter, "Aa")
        y = button.bottom() + 8
        p.setPen(Qt.NoPen)
        for i, key in enumerate(("estado_exito", "estado_aviso", "estado_error", "estado_progreso")):
            p.setBrush(c(key))
            p.drawEllipse(QRectF(panel.left() + 5 + i * 11, y, 8, 8))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        radius = theme_radius(8)
        frame = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(frame, radius, radius)
        p.fillPath(path, QColor(get_theme_token("panel_fondo", "#181818")))
        if self._colors:
            p.save()
            p.setClipPath(path)
            half = frame.width() / 2
            top, height = frame.top(), frame.height() - 26
            self._paint_mode(p, QRectF(frame.left(), top, half, height), _DARK)
            self._paint_mode(p, QRectF(frame.left() + half, top, half, height), _LIGHT)
            p.restore()
        p.setPen(QColor(get_theme_token("texto_principal", "#e0e0e0")))
        p.drawText(QRectF(frame.left(), frame.bottom() - 26, frame.width(), 26), Qt.AlignCenter, self._title)
        token = "acento_primario" if self._selected else "borde_sutil"
        p.setPen(QPen(QColor(get_theme_token(token, "#333333")), 2 if self._selected else 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        p.end()


class ExportThemeDialog(QDialog):
    """Elige qué exportar: tema completo, solo colores o paquete con imágenes y fuentes."""
    FULL, COLORS, PACKAGE = "full", "colors", "package"

    def __init__(self, user_font: str, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle(self.tr("Exportar tema"))
        self.setFixedWidth(460)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSizeConstraint(QLayout.SetFixedSize)
        container = QFrame()
        container.setObjectName("exportThemeContainer")
        set_themed_style(container, lambda: f"""
            QFrame#exportThemeContainer {{
                background-color: {get_theme_token('fondo_secundario', '#121212')};
                border: 1px solid {get_theme_token('borde', '#2d2d2d')};
                border-radius: 6px;
            }}
        """)
        container.setFixedWidth(460)
        outer.addWidget(container)
        frame = QVBoxLayout(container)
        frame.setContentsMargins(0, 0, 0, 0)
        frame.setSpacing(0)
        title_bar = CustomTitleBar(self, self.windowTitle())
        title_bar.btn_min.hide()
        title_bar.btn_max.hide()
        title_bar.btn_close.clicked.disconnect()
        title_bar.btn_close.clicked.connect(self.reject)
        frame.addWidget(title_bar)
        body = QVBoxLayout()
        body.setContentsMargins(16, 8, 16, 16)
        body.setSpacing(6)
        self.group = QButtonGroup(self)
        self._kinds = {}

        def option(kind, title, detail):
            radio = QRadioButton(title)
            self.group.addButton(radio)
            self._kinds[radio] = kind
            note = QLabel(detail)
            note.setWordWrap(True)
            note.setContentsMargins(26, 0, 0, 8)
            set_themed_style(note, lambda: f"color: {get_theme_token('texto_tenue', '#888888')}; font-size: 11px;")
            body.addWidget(radio)
            body.addWidget(note)
            return radio
        full_detail = self.tr("Colores de los dos modos, formas y nombre de la fuente (.json).")
        if user_font:
            full_detail += " " + self.tr("Tu fuente «{0}» no viaja en este archivo: quien lo importe usará otra.").format(user_font)
        option(self.FULL, self.tr("Tema completo"), full_detail).setChecked(True)
        option(self.COLORS, self.tr("Solo colores"), self.tr("Para combinarlos con las formas y la letra de otro tema (.json)."))
        option(self.PACKAGE, self.tr("Paquete con imágenes y fuentes"),
               self.tr("Todo tu tema en un archivo .dthmp. Si lo compartes, también compartes sus imágenes y fuentes, "
                       "que pueden tener derechos de autor."))
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton(self.tr("Cancelar"))
        set_button_variant(cancel, "secondary")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.btn_export = QPushButton(self.tr("Exportar"))
        set_button_variant(self.btn_export, "accent-solid")
        self.btn_export.clicked.connect(self.accept)
        buttons.addWidget(self.btn_export)
        body.addLayout(buttons)
        frame.addLayout(body)

    def kind(self) -> str:
        return self._kinds[self.group.checkedButton()]


class SaveAppearanceDialog(QDialog):
    """Pide el nombre del tema a guardar. current_id: el tema que se actualiza si el nombre se
    deja igual; con otro nombre se crea uno nuevo, y el botón lo dice."""

    def __init__(self, default_name: str, parent=None, renaming: bool = False, current_id: str = ""):
        super().__init__(parent)
        self._renaming = renaming
        self._current_id = current_id
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle(self.tr("Renombrar tema") if renaming else self.tr("Guardar como"))
        self.setFixedWidth(420)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        container = QFrame()
        container.setObjectName("saveAppearanceContainer")
        set_themed_style(container, lambda: f"""
            QFrame#saveAppearanceContainer {{
                background-color: {get_theme_token('fondo_secundario', '#121212')};
                border: 1px solid {get_theme_token('borde', '#2d2d2d')};
                border-radius: 6px;
            }}
        """)
        outer.addWidget(container)
        frame = QVBoxLayout(container)
        frame.setContentsMargins(0, 0, 0, 0)
        frame.setSpacing(0)
        title_bar = CustomTitleBar(self, self.windowTitle())
        title_bar.btn_min.hide()
        title_bar.btn_max.hide()
        title_bar.btn_close.clicked.disconnect()
        title_bar.btn_close.clicked.connect(self.reject)
        frame.addWidget(title_bar)
        body = QVBoxLayout()
        body.setContentsMargins(16, 8, 16, 16)
        body.setSpacing(12)
        info = QLabel(self.tr("Guarda colores, imágenes, opacidades, letra y redondez. "
                              "Al elegir este tema en la galería, vuelve todo."))
        info.setWordWrap(True)
        info.setVisible(not renaming)
        body.addWidget(info)
        self.name_edit = QLineEdit(default_name)
        self.name_edit.setPlaceholderText(self.tr("Nombre"))
        body.addWidget(self.name_edit)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton(self.tr("Cancelar"))
        set_button_variant(cancel, "secondary")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.btn_save = QPushButton(self.tr("Guardar"))
        set_button_variant(self.btn_save, "accent-solid")
        self.btn_save.clicked.connect(self.accept)
        buttons.addWidget(self.btn_save)
        body.addLayout(buttons)
        frame.addLayout(body)
        self.name_edit.textChanged.connect(self._on_name_changed)
        self._on_name_changed(default_name)

    def _on_name_changed(self, text: str):
        self.btn_save.setEnabled(bool(text.strip()))
        if not self._renaming:
            same = bool(self._current_id) and theme_io.slugify(text) == self._current_id
            self.btn_save.setText(self.tr("Guardar") if same else self.tr("Crear tema"))


class ThemeFromImageDialog(QDialog):
    """Al aceptar, result es (id, datos del tema, imagen de fondo o None). No guarda nada: la
    página de Apariencia lo deja como cambio pendiente, para revisarlo antes de aplicarlo."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Crear tema desde una imagen"))
        self.result_theme = None
        self._path = None
        self._file_name = None
        self._palette = None
        self._accent = None  # acento elegido a mano; None = el de la imagen
        self._variant = tp.VARIANT_TINTED
        self._cards = {}
        self._build_ui()
        general = bg.image_path(bg.PLACE_GENERAL)
        if general:
            self._load_image(general, bg.get_place(bg.PLACE_GENERAL)["name"])
        else:
            self._refresh()

    def _build_ui(self):
        # Sin marco de Windows, como el selector de color y los demás diálogos de DowP.
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.setSizeConstraint(QLayout.SetFixedSize)  # siempre el alto justo: nada se aprieta
        self.container = QFrame()
        self.container.setObjectName("themeFromImageContainer")
        set_themed_style(self.container, lambda: f"""
            QFrame#themeFromImageContainer {{
                background-color: {get_theme_token('fondo_secundario', '#121212')};
                border: 1px solid {get_theme_token('borde', '#2d2d2d')};
                border-radius: 6px;
            }}
        """)
        outer.addWidget(self.container)
        frame = QVBoxLayout(self.container)
        frame.setContentsMargins(0, 0, 0, 0)
        frame.setSpacing(0)
        self.title_bar = CustomTitleBar(self, self.windowTitle())
        self.title_bar.btn_min.hide()
        self.title_bar.btn_max.hide()
        self.title_bar.btn_close.clicked.disconnect()
        self.title_bar.btn_close.clicked.connect(self.reject)
        frame.addWidget(self.title_bar)
        # Título y botones siempre a la vista; lo del medio solo hace scroll si no cabe en la
        # pantalla (ver _fit_to_screen).
        self.body = QWidget()
        self.body.setObjectName("themeFromImageBody")
        self.body.setStyleSheet("QWidget#themeFromImageBody { background: transparent; }")
        root = QVBoxLayout(self.body)
        root.setContentsMargins(16, 8, 16, 8)
        root.setSpacing(14)
        self.body_scroll = QScrollArea()
        self.body_scroll.setWidgetResizable(True)
        self.body_scroll.setFrameShape(QFrame.NoFrame)
        self.body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.body_scroll.setWidget(self.body)
        self.body.installEventFilter(self)  # el contenido cambia de alto al elegir imagen
        frame.addWidget(self.body_scroll)

        top = QHBoxLayout()
        self.thumb = QLabel()
        self.thumb.setFixedSize(96, 96)
        self.thumb.setAlignment(Qt.AlignCenter)
        top.addWidget(self.thumb)
        info = QVBoxLayout()
        self.file_label = QLabel(self.tr("Elige una imagen para empezar."))
        self.file_label.setFixedWidth(_CONTENT_WIDTH - 96 - 12)
        info.addWidget(self.file_label)
        self.btn_choose = QPushButton(self.tr("Elegir imagen…"))
        self.btn_choose.setCursor(Qt.PointingHandCursor)
        set_button_variant(self.btn_choose, "secondary")
        self.btn_choose.clicked.connect(self._on_choose)
        info.addWidget(self.btn_choose, 0, Qt.AlignLeft)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setFixedWidth(_CONTENT_WIDTH - 96 - 12)
        set_themed_style(self.note, lambda: f"color: {get_theme_token('texto_tenue', '#888888')}; font-size: 11px;")
        info.addWidget(self.note)
        info.addStretch()
        top.addLayout(info, 1)
        root.addLayout(top)

        # En una fila, todas siempre visibles.
        cards = QHBoxLayout()
        cards.setSpacing(10)
        titles = {tp.VARIANT_NEUTRAL: self.tr("Neutro"), tp.VARIANT_TINTED: self.tr("Teñido"),
                  tp.VARIANT_SOFT: self.tr("Suave"), tp.VARIANT_DUO: self.tr("Dos colores"),
                  tp.VARIANT_INVERTED: self.tr("Invertido")}
        for key in tp.VARIANTS:
            card = _VariantCard(titles[key])
            card.clicked.connect(lambda k=key: self._on_variant(k))
            self._cards[key] = card
            cards.addWidget(card)
        cards.addStretch(1)
        root.addLayout(cards)

        accent_row = QHBoxLayout()
        accent_row.addWidget(QLabel(self.tr("Color de acento")))
        accent_row.addStretch()
        self.btn_accent = QPushButton()
        self.btn_accent.setFixedSize(60, 26)
        self.btn_accent.setCursor(Qt.PointingHandCursor)
        self.btn_accent.setToolTip(self.tr("Elegir otro color si el de la imagen no te convence"))
        self.btn_accent.clicked.connect(self._on_pick_accent)
        accent_row.addWidget(self.btn_accent)
        self.btn_accent_reset = QPushButton(self.tr("El de la imagen"))
        self.btn_accent_reset.setCursor(Qt.PointingHandCursor)
        set_button_variant(self.btn_accent_reset, "secondary")
        self.btn_accent_reset.clicked.connect(self._on_reset_accent)
        accent_row.addWidget(self.btn_accent_reset)
        root.addLayout(accent_row)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel(self.tr("Nombre del tema")))
        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(lambda _t: self._update_buttons())
        name_row.addWidget(self.name_edit, 1)
        root.addLayout(name_row)

        self.chk_background = QCheckBox(self.tr("Usar también esta imagen de fondo"))
        root.addWidget(self.chk_background)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.btn_cancel = QPushButton(self.tr("Cancelar"))
        set_button_variant(self.btn_cancel, "secondary")
        self.btn_cancel.clicked.connect(self.reject)
        buttons.addWidget(self.btn_cancel)
        self.btn_create = QPushButton(self.tr("Crear"))
        set_button_variant(self.btn_create, "accent-solid")
        self.btn_create.clicked.connect(self._on_create)
        buttons.addWidget(self.btn_create)
        buttons.setContentsMargins(16, 6, 16, 16)
        buttons.setSpacing(8)
        frame.addLayout(buttons)
        self._buttons_layout = buttons

    # ── Imagen ──────────────────────────────────────────────────────────────
    def _elide_file_name(self):
        if self._file_name:
            self.file_label.ensurePolished()
            self.file_label.setText(self.file_label.fontMetrics().elidedText(
                self._file_name, Qt.ElideMiddle, self.file_label.width()))

    def eventFilter(self, obj, event):
        if obj is self.body and event.type() == QEvent.LayoutRequest and self.isVisible():
            QTimer.singleShot(0, self._fit_to_screen)
        return super().eventFilter(obj, event)

    def _available_area(self) -> QRect:
        screen = self.screen() or QApplication.primaryScreen()
        return screen.availableGeometry()

    def _fit_to_screen(self):
        """Lo justo para el contenido; menos, con scroll, solo si no cabe en la pantalla."""
        self.body.ensurePolished()
        hint = self.body.sizeHint()
        area = self._available_area()
        chrome = self.title_bar.height() + self._buttons_layout.sizeHint().height() + 2
        height = min(hint.height(), area.height() - chrome)
        bar = self.body_scroll.verticalScrollBar().sizeHint().width() if height < hint.height() else 0
        size = QSize(min(hint.width() + bar, area.width() - 2), max(120, height))
        if size == self.body_scroll.size():
            return
        self.body_scroll.setFixedSize(size)
        self.adjustSize()
        # Si por crecer quedó fuera de la pantalla, adentro de nuevo.
        x = max(area.left(), min(self.x(), area.right() - self.width() + 1))
        y = max(area.top(), min(self.y(), area.bottom() - self.height() + 1))
        self.move(x, y)

    def showEvent(self, event):
        super().showEvent(event)
        self._elide_file_name()  # recién aquí la letra es la definitiva
        self._fit_to_screen()

    def _on_choose(self):
        path, _ = QFileDialog.getOpenFileName(self, self.tr("Elegir imagen"), os.path.expanduser("~"),
                                              self.tr("Imágenes") + f" ({_IMAGE_FILTER})")
        if path:
            self._load_image(path, os.path.basename(path))

    def _load_image(self, path: str, display_name: str):
        try:
            palette = tp.analyze_image(path)
        except Exception as e:
            QMessageBox.warning(self, self.tr("No se pudo leer la imagen"), str(e))
            return
        self._path, self._palette, self._accent = path, palette, None
        self._file_name = display_name
        self._elide_file_name()
        self.file_label.setToolTip(display_name)
        pix = QPixmap(path)
        if not pix.isNull():
            self.thumb.setPixmap(pix.scaled(self.thumb.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.note.setText("" if palette.has_color else self.tr(
            "Esta imagen casi no tiene color: se usa el acento de DowP. Puedes elegir otro abajo."))
        stem = " ".join(os.path.splitext(display_name)[0].replace("_", " ").replace("-", " ").split())
        self.name_edit.setText(stem[:40])
        is_current_bg = path == bg.image_path(bg.PLACE_GENERAL)
        self.chk_background.setChecked(False)
        self.chk_background.setVisible(not is_current_bg)
        self._refresh()

    # ── Variantes y acento ──────────────────────────────────────────────────
    def _colors_for(self, variant: str) -> dict:
        return tp.build_colors(self._palette, variant, self._accent)

    def _refresh(self):
        for key, card in self._cards.items():
            card.set_colors(self._colors_for(key) if self._palette else None)
            card.set_selected(key == self._variant)
        shown = (self._accent or self._palette.accent) if self._palette else get_theme_token("borde_sutil", "#333333")
        self.btn_accent.setStyleSheet(f"background-color: {shown}; border: 1px solid {get_theme_token('borde_sutil', '#333333')};")
        self._update_buttons()

    def _update_buttons(self):
        has = self._palette is not None
        self.btn_accent.setEnabled(has)
        self.btn_accent_reset.setEnabled(self._accent is not None)
        self.btn_create.setEnabled(has and bool(self.name_edit.text().strip()))

    def _on_variant(self, key: str):
        self._variant = key
        self._refresh()

    def _on_pick_accent(self):
        from gui.dialogs.dialogs import AdobeColorPickerDialog
        dialog = AdobeColorPickerDialog(self._accent or self._palette.accent, self)
        if dialog.exec():
            self._accent = dialog.get_color()
            self._refresh()

    def _on_reset_accent(self):
        self._accent = None
        self._refresh()

    # ── Crear ───────────────────────────────────────────────────────────────
    def _on_create(self):
        name = self.name_edit.text().strip()
        theme_id = theme_io.slugify(name)
        if theme_id in theme_io.builtin_theme_ids():
            theme_id = f"{theme_id}-imagen"  # los temas de DowP no se reemplazan
        if theme_io.is_user_theme(theme_id):
            answer = QMessageBox.question(self, self.windowTitle(),
                                          self.tr("Ya tienes un tema llamado «{0}». ¿Quieres reemplazarlo?").format(name))
            if answer != QMessageBox.Yes:
                return
        background = self._path if self.chk_background.isVisible() and self.chk_background.isChecked() else None
        self.result_theme = (theme_id, tp.build_theme(name, self._colors_for(self._variant)), background)
        self.accept()
