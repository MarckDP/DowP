# src/gui/widgets/history_panel.py
"""Panel lateral del historial de descargas (Modo Rápido y Proceso Avanzado).

Reutiliza CollapsiblePanel (el panel que se oculta de Herramientas Multimedia y el Editor
de Imagen) en modo overlay permanente, pegado al borde derecho: siempre empieza
cerrado, se abre con su pestaña del borde y se cierra con ella, al hacer clic fuera o al
cambiar de pestaña. Cada pestaña tiene su propio panel, pero los dos muestran los mismos
datos: el registro único de core/utils/download_history.py.

La lista es un QListView con modelo + delegate (no un widget por tarjeta, como la cola):
el usuario puede subir el límite del historial sin tope, y así solo se dibujan las
tarjetas visibles y se van pidiendo a la base por páginas (fetchMore).

Clic en una tarjeta: su URL REEMPLAZA lo que haya en el campo de URL de la pestaña donde
está el panel -- solo se pega, no se analiza.
"""
import time
from datetime import datetime
from urllib.parse import urlparse

from PySide6.QtCore import (
    QAbstractListModel, QCoreApplication, QEvent, QModelIndex, QObject, QRect, QSize, Qt,
    QUrl, Signal,
)
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontMetrics, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QListView, QMenu, QMessageBox, QPushButton,
    QStyle, QStyledItemDelegate, QVBoxLayout, QWidget,
)

from core.utils.download_history import (
    KIND_PLAYLIST, STATUS_DOWNLOADED, download_history,
)
from gui.styles import get_theme_token, set_button_variant
from gui.widgets.collapsible_panel import CollapsiblePanel

PANEL_WIDTH = 390
# Más ancha que la pestaña por defecto de CollapsiblePanel (20x90): es el único acceso al
# historial, así que se busca que se vea y se atine fácil.
EDGE_TAB_SIZE = (28, 120)
CARD_HEIGHT = 76
THUMB_W, THUMB_H = 96, 54
_ROLE_ENTRY = Qt.UserRole + 1


def _format_duration(seconds) -> str:
    try:
        total = int(round(float(seconds)))
    except (TypeError, ValueError):
        return ""
    if total <= 0:
        return ""
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _relative_time(ts) -> str:
    try:
        delta = time.time() - float(ts)
    except (TypeError, ValueError):
        return ""
    if delta < 60:
        return QCoreApplication.translate("HistoryPanel", "hace un momento")
    if delta < 3600:
        return QCoreApplication.translate("HistoryPanel", "hace {0} min").format(int(delta // 60))
    if delta < 86400:
        return QCoreApplication.translate("HistoryPanel", "hace {0} h").format(int(delta // 3600))
    days = int(delta // 86400)
    if days == 1:
        return QCoreApplication.translate("HistoryPanel", "ayer")
    if days < 7:
        return QCoreApplication.translate("HistoryPanel", "hace {0} días").format(days)
    return datetime.fromtimestamp(float(ts)).strftime("%d/%m/%Y")


def _domain(url: str) -> str:
    host = urlparse(url or "").netloc
    return host[4:] if host.startswith("www.") else host


class HistoryListModel(QAbstractListModel):
    PAGE_SIZE = 200

    def __init__(self, parent=None):
        super().__init__(parent)
        self._history = download_history()
        self._rows: list = []
        self._total = 0
        self._search = ""
        self._history.entries_changed.connect(self.reload)
        self._history.entry_updated.connect(self._on_entry_updated)
        self.reload()

    def reload(self):
        self.beginResetModel()
        self._total = self._history.count(self._search)
        self._rows = self._history.fetch(0, self.PAGE_SIZE, self._search)
        self.endResetModel()

    def set_search(self, text: str):
        text = (text or "").strip()
        if text != self._search:
            self._search = text
            self.reload()

    def search_text(self) -> str:
        return self._search

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def canFetchMore(self, parent=QModelIndex()):
        return not parent.isValid() and len(self._rows) < self._total

    def fetchMore(self, parent=QModelIndex()):
        more = self._history.fetch(len(self._rows), self.PAGE_SIZE, self._search)
        if not more:
            self._total = len(self._rows)
            return
        self.beginInsertRows(QModelIndex(), len(self._rows), len(self._rows) + len(more) - 1)
        self._rows.extend(more)
        self.endInsertRows()

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        entry = self._rows[index.row()]
        if role == _ROLE_ENTRY:
            return entry
        if role == Qt.DisplayRole:
            return entry.get("title")
        if role == Qt.ToolTipRole:
            return f"{entry.get('title') or ''}\n{entry.get('url') or ''}"
        return None

    def _on_entry_updated(self, key: str):
        for i, entry in enumerate(self._rows):
            if entry.get("key") == key:
                fresh = self._history.get(key)
                if fresh:
                    self._rows[i] = fresh
                    idx = self.index(i)
                    self.dataChanged.emit(idx, idx)
                return


class HistoryCardDelegate(QStyledItemDelegate):
    """Dibuja cada entrada como una tarjeta: miniatura con la duración encima, título en
    hasta 2 líneas, dominio + fecha relativa, y el estado (Analizado / Descargado)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._history = download_history()
        self._pixmaps: dict = {}
        self._history.entries_changed.connect(self._pixmaps.clear)
        self._history.entry_updated.connect(lambda key: self._pixmaps.pop(key, None))
        # Los tokens se leen una vez: get_theme_token relee la config en cada llamada y
        # paint() corre por cada tarjeta visible en cada repintado.
        # Mismo recuadro que las tarjetas de Opciones de Herramientas Multimedia
        # (presets_panel.py::_card_frame): sin relleno, borde borde_sutil, 6 px.
        self.c_card = QColor(Qt.transparent)
        self.c_hover = QColor(get_theme_token("fondo_elemento", "#1a1a1a"))
        self.c_border = QColor(get_theme_token("borde_sutil", "#333333"))
        self.c_thumb_bg = QColor(get_theme_token("fondo_elemento", "#1a1a1a"))
        self.c_text = QColor(get_theme_token("texto_principal", "#ffffff"))
        self.c_muted = QColor(get_theme_token("texto_secundario", "#888888"))
        self.c_done = QColor(get_theme_token("estado_exito", "#40d66b"))
        self.c_analyzed = QColor(get_theme_token("estado_progreso", "#3498db"))

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), CARD_HEIGHT)

    def _thumbnail(self, entry: dict):
        key = entry.get("key")
        if key in self._pixmaps:
            return self._pixmaps[key]
        path = self._history.thumbnail_path(entry)
        if not path:
            self._history.ensure_thumbnail(key)
            return None
        pix = QPixmap(path)
        if pix.isNull():
            return None
        # Recorte al centro en 16:9, para que todas las tarjetas queden parejas.
        pix = pix.scaled(THUMB_W * 2, THUMB_H * 2, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        x = (pix.width() - THUMB_W * 2) // 2
        y = (pix.height() - THUMB_H * 2) // 2
        pix = pix.copy(x, y, THUMB_W * 2, THUMB_H * 2)
        pix.setDevicePixelRatio(2.0)
        self._pixmaps[key] = pix
        return pix

    @staticmethod
    def _two_lines(fm: QFontMetrics, text: str, width: int) -> list:
        words = (text or "").split()
        first = ""
        rest_start = len(words)
        for i, word in enumerate(words):
            candidate = f"{first} {word}".strip()
            if fm.horizontalAdvance(candidate) > width:
                rest_start = i
                break
            first = candidate
        if not first:
            return [fm.elidedText(text or "", Qt.ElideRight, width)]
        rest = " ".join(words[rest_start:])
        return [first, fm.elidedText(rest, Qt.ElideRight, width)] if rest else [first]

    def paint(self, painter: QPainter, option, index):
        entry = index.data(_ROLE_ENTRY)
        if not entry:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        card = option.rect.adjusted(2, 3, -2, -3)
        hovered = bool(option.state & QStyle.State_MouseOver)
        painter.setPen(self.c_border)
        painter.setBrush(self.c_hover if hovered else self.c_card)
        painter.drawRoundedRect(card, 6, 6)

        # Miniatura (o marcador si todavía no está / no se pudo bajar).
        thumb_rect = QRect(card.left() + 6, card.top() + (card.height() - THUMB_H) // 2, THUMB_W, THUMB_H)
        clip = QPainterPath()
        clip.addRoundedRect(thumb_rect, 4, 4)
        painter.save()
        painter.setClipPath(clip)
        painter.fillRect(thumb_rect, self.c_thumb_bg)
        pix = self._thumbnail(entry)
        if pix is not None:
            painter.drawPixmap(thumb_rect, pix)
        else:
            painter.setPen(self.c_muted)
            painter.drawText(thumb_rect, Qt.AlignCenter, "▶")
        painter.restore()

        # Esquina de la miniatura: duración, o número de elementos si es una playlist.
        if entry.get("kind") == KIND_PLAYLIST:
            count = entry.get("item_count") or 0
            badge = QCoreApplication.translate("HistoryPanel", "{0} elementos").format(count) if count else QCoreApplication.translate("HistoryPanel", "Playlist")
        else:
            badge = _format_duration(entry.get("duration"))
        if badge:
            small = QFont(option.font)
            small.setPointSizeF(max(7.0, option.font.pointSizeF() - 2))
            small.setBold(True)
            painter.setFont(small)
            bfm = QFontMetrics(small)
            bw, bh = bfm.horizontalAdvance(badge) + 8, bfm.height() + 2
            brect = QRect(thumb_rect.right() - bw - 2, thumb_rect.bottom() - bh - 2, bw, bh)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(0, 0, 0, 190))
            painter.drawRoundedRect(brect, 3, 3)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(brect, Qt.AlignCenter, badge)

        # Textos.
        text_left = thumb_rect.right() + 10
        text_width = card.right() - 8 - text_left
        title_font = QFont(option.font)
        title_font.setBold(True)
        painter.setFont(title_font)
        tfm = QFontMetrics(title_font)
        y = card.top() + 7
        painter.setPen(self.c_text)
        for line in self._two_lines(tfm, entry.get("title") or "", text_width):
            painter.drawText(QRect(text_left, y, text_width, tfm.height()), Qt.AlignLeft | Qt.AlignVCenter, line)
            y += tfm.height()

        meta_font = QFont(option.font)
        meta_font.setPointSizeF(max(7.0, option.font.pointSizeF() - 1.5))
        painter.setFont(meta_font)
        mfm = QFontMetrics(meta_font)

        downloaded = entry.get("status") == STATUS_DOWNLOADED
        status_text = QCoreApplication.translate("HistoryPanel", "Descargado") if downloaded else QCoreApplication.translate("HistoryPanel", "Analizado")
        status_color = self.c_done if downloaded else self.c_analyzed
        sw, sh = mfm.horizontalAdvance(status_text) + 12, mfm.height() + 2
        bottom = card.bottom() - 6
        srect = QRect(card.right() - 8 - sw, bottom - sh, sw, sh)
        painter.setPen(status_color)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(srect, sh / 2, sh / 2)
        painter.drawText(srect, Qt.AlignCenter, status_text)

        meta = " · ".join(p for p in (_domain(entry.get("url")), _relative_time(entry.get("updated_at"))) if p)
        meta_width = srect.left() - 6 - text_left
        painter.setPen(self.c_muted)
        painter.drawText(QRect(text_left, bottom - sh, meta_width, sh), Qt.AlignLeft | Qt.AlignVCenter,
                         mfm.elidedText(meta, Qt.ElideRight, meta_width))
        painter.restore()


class HistoryPanelContent(QFrame):
    """Contenido del panel: buscador, lista de tarjetas y "Borrar historial".

    Misma "tarjeta" que el panel de Opciones de Herramientas Multimedia
    (EncodingOptionsWidget): fondo_secundario con borde borde_normal y esquinas de 6 px,
    sobre el fondo_principal que CollapsiblePanel da al overlay (ver _base.qss)."""
    url_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._history = download_history()
        self.setObjectName("historyPanelContent")
        border_color = get_theme_token('borde_normal', '#222222')
        self.setStyleSheet(f"""
            QFrame#historyPanelContent {{
                background-color: {get_theme_token('fondo_secundario', '#121212')};
                border: 1px solid {border_color};
                border-radius: 6px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        # Título con el aspecto de la pestaña activa de Opciones (Preajustes, Comprimir...):
        # texto blanco, subrayado de 3 px en acento_primario (el mismo grosor que
        # AnimatedTabIndicator) y, debajo, la línea del borde superior del panel.
        header_box = QVBoxLayout()
        header_box.setContentsMargins(0, 0, 0, 0)
        header_box.setSpacing(0)
        header = QLabel(self.tr("Historial"))
        header.setStyleSheet(
            f"color: {get_theme_token('texto_activo', '#ffffff')}; padding: 8px 18px; background: transparent; border: none;")
        underline = QFrame()
        underline.setFixedHeight(3)
        underline.setStyleSheet(f"background-color: {get_theme_token('acento_primario', '#B9E640')}; border: none;")
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        tab = QVBoxLayout()
        tab.setContentsMargins(0, 0, 0, 0)
        tab.setSpacing(0)
        tab.addWidget(header)
        tab.addWidget(underline)
        header_row.addLayout(tab)
        header_row.addStretch(1)
        header_box.addLayout(header_row)
        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background-color: {border_color}; border: none;")
        header_box.addWidget(divider)
        layout.addLayout(header_box)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(self.tr("Buscar por título o URL"))
        self.search_input.setClearButtonEnabled(True)
        layout.addWidget(self.search_input)

        self.model = HistoryListModel(self)
        self.list_view = QListView()
        self.list_view.setModel(self.model)
        self.list_view.setItemDelegate(HistoryCardDelegate(self.list_view))
        self.list_view.setMouseTracking(True)
        self.list_view.setUniformItemSizes(True)
        self.list_view.setSelectionMode(QListView.NoSelection)
        self.list_view.setVerticalScrollMode(QListView.ScrollPerPixel)
        self.list_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_view.setCursor(Qt.PointingHandCursor)
        self.list_view.setStyleSheet("QListView { background: transparent; border: none; }")
        self.list_view.clicked.connect(self._on_clicked)
        self.list_view.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.list_view, 1)

        self.empty_label = QLabel()
        self.empty_label.setWordWrap(True)
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet(f"color: {get_theme_token('texto_secundario', '#888888')}; font-size: 11px;")
        layout.addWidget(self.empty_label, 1)

        self.btn_clear = QPushButton(self.tr("Borrar historial"))
        self.btn_clear.setCursor(Qt.PointingHandCursor)
        set_button_variant(self.btn_clear, "danger")
        self.btn_clear.clicked.connect(self._on_clear_clicked)
        layout.addWidget(self.btn_clear)

        self.search_input.textChanged.connect(self.model.set_search)
        self.model.modelReset.connect(self._update_empty_state)
        self.model.rowsInserted.connect(self._update_empty_state)
        self._update_empty_state()

    def refresh(self):
        """Al abrir el panel: el interruptor de Ajustes pudo cambiar mientras estaba cerrado."""
        self._update_empty_state()

    def _update_empty_state(self, *args):
        empty = self.model.rowCount() == 0
        self.list_view.setVisible(not empty)
        self.empty_label.setVisible(empty)
        self.btn_clear.setEnabled(self._history.count() > 0)
        if not empty:
            return
        if self.model.search_text():
            self.empty_label.setText(self.tr("No hay resultados para esta búsqueda."))
        elif not self._history.is_enabled():
            self.empty_label.setText(self.tr(
                "El historial está desactivado. Puedes activarlo en Ajustes > Descargas."))
        else:
            self.empty_label.setText(self.tr(
                "Aquí aparecerán los medios y playlists que analices o descargues."))

    def _on_clicked(self, index):
        entry = index.data(_ROLE_ENTRY)
        if entry and entry.get("url"):
            self.url_selected.emit(entry["url"])

    def _on_context_menu(self, pos):
        index = self.list_view.indexAt(pos)
        entry = index.data(_ROLE_ENTRY) if index.isValid() else None
        if not entry:
            return
        menu = QMenu(self)
        act_copy = menu.addAction(self.tr("Copiar URL"))
        act_open = menu.addAction(self.tr("Abrir en el navegador"))
        menu.addSeparator()
        act_remove = menu.addAction(self.tr("Quitar del historial"))
        chosen = menu.exec(self.list_view.viewport().mapToGlobal(pos))
        if chosen is act_copy:
            QApplication.clipboard().setText(entry["url"])
        elif chosen is act_open:
            QDesktopServices.openUrl(QUrl(entry["url"]))
        elif chosen is act_remove:
            self._history.remove(entry["key"])

    def _on_clear_clicked(self):
        answer = QMessageBox.question(
            self, self.tr("Borrar historial"),
            self.tr("¿Borrar todo el historial de descargas?\n\nNo borra ningún archivo "
                    "descargado, solo las tarjetas del historial. No se puede deshacer."))
        if answer == QMessageBox.Yes:
            self._history.clear()


class HistoryDrawer(QObject):
    """Monta el panel del historial sobre `host` (la pestaña entera), desde su borde
    derecho, y lo conecta con su campo de URL. Se cierra al hacer clic fuera de él, al
    cambiar de pestaña (el host se oculta) y con su propia pestaña del borde."""

    def __init__(self, host: QWidget, url_input: QLineEdit):
        super().__init__(host)
        self._host = host
        self._url_input = url_input
        self.content = HistoryPanelContent()
        self.panel = CollapsiblePanel(self.content, edge="right",
                                      docked_size=PANEL_WIDTH, overlay_max_width=PANEL_WIDTH)
        self.panel.edge_tab.setFixedSize(*EDGE_TAB_SIZE)
        # CollapsiblePanel espera un layout donde "acoplarse"; este panel nunca se acopla,
        # así que recibe uno propio que no pertenece a ninguna ventana.
        self._unused_dock_layout = QHBoxLayout()
        self.panel.configure_container(host, self._unused_dock_layout, 0)
        self.panel.set_mode(False)
        self.panel.edge_tab.setToolTip(QCoreApplication.translate("HistoryPanelContent", "Historial"))
        self.panel.opened.connect(self.content.refresh)
        self.content.url_selected.connect(self._on_url_selected)

        host.installEventFilter(self)
        QApplication.instance().installEventFilter(self)

    def _on_url_selected(self, url: str):
        # Reemplaza lo que hubiera: setText (no insert). No emite textEdited, así que no
        # dispara el autoanálisis por pegado de las pestañas.
        self._url_input.setText(url)
        self._url_input.setCursorPosition(0)

    @staticmethod
    def _is_inside(widget, ancestor) -> bool:
        while widget is not None:
            if widget is ancestor:
                return True
            widget = widget.parentWidget()
        return False

    def eventFilter(self, obj, event):
        etype = event.type()
        if obj is self._host:
            if etype == QEvent.Resize:
                self.panel.sync_overlay_geometry()
                self.panel.edge_tab.raise_()
            elif etype == QEvent.Hide:
                self.panel.close_overlay()
            return False

        if etype == QEvent.MouseButtonPress and self.panel.is_overlay_open() and isinstance(obj, QWidget):
            # Menús/combos desplegados y diálogos (ej. confirmar "Borrar historial") son
            # otras ventanas: un clic ahí no es "fuera del panel".
            if QApplication.activePopupWidget() is not None:
                return False
            # Se mira el widget que está BAJO EL CURSOR, no `obj`: un widget que no acepta
            # el "press" (como la pestaña del borde, que actúa al soltar) lo deja subir a
            # su padre, y este filtro lo volvía a ver con obj = el host. Eso cerraba el
            # panel al presionar, y al soltar la pestaña lo reabría: "no se deja cerrar".
            target = QApplication.widgetAt(event.globalPosition().toPoint())
            if target is None or target.window() is not self._host.window():
                return False
            if not (self._is_inside(target, self.panel) or self._is_inside(target, self.panel.edge_tab)):
                self.panel.close_overlay()
        return False
