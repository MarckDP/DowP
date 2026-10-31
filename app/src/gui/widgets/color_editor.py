"""Editor de colores de Ajustes > Apariencia: unos pocos colores que arrastran a los demás
(core/utils/theme_palette.py, BASIC_COLORS) y, plegados, todos los del tema con un buscador.
Solo avisa de los cambios: guardarlos es cosa de la página, al pulsar Aplicar."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from core.utils import theme_palette as tp
from gui.styles import get_theme_token, set_button_variant, set_themed_style
from gui.widgets.color_names import color_label


class _Swatch(QPushButton):
    def __init__(self, tooltip: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(44, 24)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tooltip)

    def show_color(self, color: str):
        self.setStyleSheet(f"QPushButton {{ background-color: {color}; "
                           f"border: 1px solid {get_theme_token('borde_fuerte', '#555555')}; border-radius: 4px; }}")


class ColorEditor(QWidget):
    edited = Signal(dict)     # {color: valor} que cambian
    reverted = Signal(list)   # colores que vuelven a lo guardado

    # Primera palabra del nombre de cada color -> grupo de la lista completa.
    _GROUP_OF = {"fondo": 0, "panel": 0, "tarjeta": 0, "cabecera": 0, "ajedrez": 0, "miniatura": 0, "onda": 0,
                 "texto": 1, "tab": 1, "titulo": 1, "icono": 1, "flecha": 1,
                 "acento": 2, "seleccion": 2, "badge": 2, "resaltado": 2,
                 "boton": 3, "checkbox": 3, "switch": 3, "combo": 3,
                 "borde": 4, "divisor": 4, "contorno": 4,
                 "estado": 5, "etiqueta": 5, "progreso": 5, "consola": 5}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tokens = {}
        self._edited = set()
        self._basic = {}
        self._rows = {}  # color -> (fila, muestra, deshacer)
        self._group_labels = []
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        titles = {"fondo_principal": self.tr("Fondo"), "texto_principal": self.tr("Texto"),
                  "texto_secundario": self.tr("Texto secundario"),
                  "acento_primario": self.tr("Acento"), "acento_secundario": self.tr("Segundo acento"),
                  "borde_normal": self.tr("Bordes"), "seleccion_fondo": self.tr("Selección"),
                  "estado_exito": self.tr("Éxito"), "estado_aviso": self.tr("Aviso"),
                  "estado_error": self.tr("Error"), "estado_progreso": self.tr("En progreso")}
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(4, 1)
        for i, key in enumerate(tp.BASIC_COLORS):
            row, col = i // 2, (i % 2) * 4
            label = QLabel(titles[key])
            label.setObjectName("settingsLabel")
            warning = QLabel(self.tr("Poco contraste"))
            warning.setToolTip(self.tr("Con este color puede costar leer. Puedes dejarlo si te gusta."))
            set_themed_style(warning, lambda: f"color: {get_theme_token('estado_aviso', '#d8c94a')}; font-size: 10px;")
            warning.hide()
            undo = QPushButton(self.tr("Deshacer"))
            undo.setCursor(Qt.PointingHandCursor)
            set_button_variant(undo, "ghost")
            undo.clicked.connect(lambda _c=False, k=key: self.reverted.emit(tp.basic_family(k, self._tokens)))
            undo.hide()
            swatch = _Swatch(key)
            swatch.clicked.connect(lambda _c=False, k=key: self._pick_basic(k))
            grid.addWidget(label, row, col)
            grid.addWidget(warning, row, col + 1)
            grid.addWidget(undo, row, col + 2)
            grid.addWidget(swatch, row, col + 3)
            self._basic[key] = (swatch, warning, undo)
        root.addLayout(grid)

        self.btn_all = QPushButton(self.tr("Mostrar todos los colores"))
        self.btn_all.setCursor(Qt.PointingHandCursor)
        set_button_variant(self.btn_all, "secondary")
        self.btn_all.clicked.connect(self._toggle_all)
        root.addWidget(self.btn_all, 0, Qt.AlignLeft)

        self.all_panel = QWidget()
        self._all_layout = QVBoxLayout(self.all_panel)
        self._all_layout.setContentsMargins(0, 0, 0, 0)
        self._all_layout.setSpacing(4)
        self.search = QLineEdit()
        self.search.setPlaceholderText(self.tr("Buscar un color..."))
        self.search.textChanged.connect(self._apply_filter)
        self._all_layout.addWidget(self.search)
        self.all_panel.hide()
        root.addWidget(self.all_panel)

    # ── Datos ───────────────────────────────────────────────────────────────
    def set_state(self, tokens: dict, edited: set):
        """tokens: los colores tal como quedarían; edited: los que tienen cambios sin aplicar."""
        self._tokens, self._edited = tokens, edited
        for key, (swatch, warning, undo) in self._basic.items():
            swatch.show_color(tokens.get(key, "#808080"))
            warning.setVisible(tp.basic_low_contrast(key, tokens))
            undo.setVisible(bool(edited & set(tp.basic_family(key, tokens))))
        for token, (_row, swatch, undo) in self._rows.items():
            swatch.show_color(tokens.get(token, "#808080"))
            undo.setVisible(token in edited)

    def _choose(self, current: str) -> str | None:
        from gui.dialogs.dialogs import AdobeColorPickerDialog
        dialog = AdobeColorPickerDialog(current, self.window())
        return dialog.get_color() if dialog.exec() else None

    def _pick_basic(self, key: str):
        color = self._choose(self._tokens.get(key, "#808080"))
        if color:
            self.edited.emit(tp.derive_basic(self._tokens, key, color))

    def _pick_token(self, token: str):
        color = self._choose(self._tokens.get(token, "#808080"))
        if color:
            self.edited.emit({token: color})

    # ── Lista completa ──────────────────────────────────────────────────────
    def _toggle_all(self):
        showing = self.all_panel.isHidden()
        if showing and not self._rows:
            self._build_all_rows()  # más de cien filas: solo si alguien las pide
        self.all_panel.setVisible(showing)
        self.btn_all.setText(self.tr("Ocultar todos los colores") if showing else self.tr("Mostrar todos los colores"))

    def _build_all_rows(self):
        titles = (self.tr("Fondos"), self.tr("Textos e iconos"), self.tr("Acento y selección"),
                  self.tr("Botones y controles"), self.tr("Bordes"), self.tr("Estados"), self.tr("Otros"))
        groups = [[] for _ in titles]
        for token in sorted(self._tokens):
            groups[self._GROUP_OF.get(token.split("_")[0], 6)].append(token)
        for title, tokens in zip(titles, groups):
            if not tokens:
                continue
            header = QLabel(title)
            header.setObjectName("settingsLabel")
            set_themed_style(header, lambda: "font-weight: bold;")
            self._all_layout.addWidget(header)
            members = []
            for token in tokens:
                row = QWidget()
                layout = QHBoxLayout(row)
                layout.setContentsMargins(8, 0, 0, 0)
                layout.addWidget(QLabel(color_label(token)))
                layout.addStretch()
                undo = QPushButton(self.tr("Deshacer"))
                undo.setCursor(Qt.PointingHandCursor)
                set_button_variant(undo, "ghost")
                undo.clicked.connect(lambda _c=False, t=token: self.reverted.emit([t]))
                layout.addWidget(undo)
                swatch = _Swatch(token)
                swatch.clicked.connect(lambda _c=False, t=token: self._pick_token(t))
                layout.addWidget(swatch)
                self._all_layout.addWidget(row)
                self._rows[token] = (row, swatch, undo)
                members.append(token)
            self._group_labels.append((header, members))
        self.set_state(self._tokens, self._edited)
        self._apply_filter(self.search.text())

    def _apply_filter(self, text: str):
        # Por el nombre que se ve o por la clave del tema (la que trae el JSON).
        needle = text.strip().casefold()
        matches = lambda token: needle in color_label(token).casefold() or needle.replace(" ", "_") in token
        for token, (row, _swatch, _undo) in self._rows.items():
            row.setVisible(matches(token))
        for header, members in self._group_labels:
            header.setVisible(any(matches(t) for t in members))
