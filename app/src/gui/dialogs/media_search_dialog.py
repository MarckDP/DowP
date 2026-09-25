# src/gui/dialogs/media_search_dialog.py
"""Ventana de búsqueda (lupa junto al campo de URL) de Modo Rápido y Proceso Avanzado.

Busca en YouTube o SoundCloud (core/ytdlp_logic/media_search.py) y devuelve SOLO los
ítems elegidos (dicts con 'url', 'title', 'is_live', ...). Cada pestaña trata esas URLs
igual que si el usuario las hubiera pegado: el análisis y la miniatura buena salen del flujo
normal, nunca de aquí -- las miniaturas de esta ventana son de baja calidad y viven en su
propia caché (core/utils/search_thumbnail_cache.py).

Mismo esquema visual que FragmentDialog: capa oscura sobre la ventana principal y una
tarjeta central con los colores del tema."""
import re

from PySide6.QtCore import (
    Qt, QPoint, QRect, QSize, QThread, QTimer, Signal, QCoreApplication, QItemSelectionModel,
)
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap, QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListView, QPushButton, QStackedWidget, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget,
)

from core.logger.logger_manager import logger
from core.utils.config_manager import get_config, save_config
from core.utils.search_thumbnail_cache import SearchThumbnailCache
from core.ytdlp_logic import media_search
from core.ytdlp_logic.media_search import KIND_VIDEO, KIND_PLAYLIST, KIND_CHANNEL
from gui.styles import get_theme_token
from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon
from gui.widgets.combo_box import AutoPopupComboBox

ITEM_ROLE = Qt.UserRole + 1

GRID_MIN_ITEM_WIDTH = 200
LIST_ITEM_HEIGHT = 88


def format_duration(seconds):
    try:
        seconds = int(float(seconds))
    except (TypeError, ValueError):
        return ""
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def format_count(n):
    """2700000 -> '2.7M', 4320 -> '4.3K', 38 -> '38'."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return ""
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1000:.1f}".rstrip("0").rstrip(".") + "K"
    return f"{n / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"


def _clean_error(text: str) -> str:
    text = re.sub(r"\x1b\[[0-9;]*m", "", str(text or ""))
    text = re.sub(r"^ERROR:\s*", "", text.strip())
    return text.splitlines()[0] if text else QCoreApplication.translate("MediaSearchDialog", "Error desconocido")


def _wrap_lines(text, fm: QFontMetrics, width: int, max_lines: int) -> list:
    """Parte el texto en hasta max_lines líneas que caben en width; la última se recorta
    con '…' si sobra texto."""
    words = (text or "").split()
    lines, current = [], ""
    for i, word in enumerate(words):
        candidate = f"{current} {word}".strip()
        if fm.horizontalAdvance(candidate) <= width or not current:
            current = candidate
            continue
        lines.append(current)
        current = word
        if len(lines) == max_lines - 1:
            current = " ".join(words[i:])
            break
    if current:
        lines.append(current)
    lines = lines[:max_lines]
    if lines:
        lines[-1] = fm.elidedText(lines[-1], Qt.ElideRight, width)
    return lines


# ──────────────────────────────────────────────────────────────
# Búsqueda en segundo plano
# ──────────────────────────────────────────────────────────────
# Referencias fuertes a los hilos en curso: si la ventana se cierra antes de que yt-dlp
# responda, el hilo tiene que seguir vivo hasta terminar (destruir un QThread corriendo
# tumba la app). El resultado de un hilo huérfano simplemente se descarta.
_RUNNING_WORKERS = set()


class _SearchWorker(QThread):
    done = Signal(int, int, dict, str)  # (generación, página, resultado, error)

    def __init__(self, generation, page, fn, *args):
        super().__init__()
        self.generation = generation
        self.page = page
        self.fn = fn
        self.args = args

    def run(self):
        try:
            result = self.fn(*self.args)
            self.done.emit(self.generation, self.page, result, "")
        except Exception as e:
            logger.warning(f"MediaSearchDialog: Error en la búsqueda: {e}")
            self.done.emit(self.generation, self.page, {}, _clean_error(e))


# ──────────────────────────────────────────────────────────────
# Tarjetas
# ──────────────────────────────────────────────────────────────
class _ResultDelegate(QStyledItemDelegate):
    """Dibuja cada resultado como tarjeta: miniatura (con duración encima), título y canal.
    La geometría sale de layout() para que el clic en el canal (ver _ResultsView) use
    exactamente el mismo rectángulo que se dibuja."""

    def __init__(self, dialog):
        super().__init__(dialog)
        self.dialog = dialog
        self.c_card = QColor(get_theme_token("fondo_elemento", "#1a1a1a"))
        self.c_card_hover = QColor(get_theme_token("fondo_terciario", "#161616")).lighter(140)
        self.c_border = QColor(get_theme_token("borde_normal", "#222222"))
        self.c_accent = QColor(get_theme_token("acento_primario", "#B9E640"))
        self.c_text = QColor(get_theme_token("texto_principal", "#e0e0e0"))
        self.c_muted = QColor(get_theme_token("texto_secundario", "#666666"))
        self.c_placeholder = QColor(get_theme_token("fondo_terciario", "#161616"))
        self.c_live = QColor(get_theme_token("estado_error", "#ff6b5f"))
        self.c_on_accent = QColor(get_theme_token("boton_texto", "#000000"))

    # -- geometría ------------------------------------------------
    def _fonts(self, base_font):
        title_font = QFont(base_font)
        title_font.setBold(True)
        small_font = QFont(base_font)
        small_font.setPointSizeF(max(7.0, base_font.pointSizeF() - 1.5))
        return title_font, small_font

    def layout(self, rect: QRect, item: dict, base_font: QFont) -> dict:
        if item.get("kind") == KIND_CHANNEL:
            return self._layout_channel(rect, item, base_font)
        return self._layout_media(rect, item, base_font)

    def _layout_media(self, rect: QRect, item: dict, base_font: QFont) -> dict:
        """Video o playlist: misma geometría (miniatura + título + canal), solo cambia la
        insignia sobre la miniatura (ver paint())."""
        title_font, small_font = self._fonts(base_font)
        fm_title, fm_small = QFontMetrics(title_font), QFontMetrics(small_font)
        pad = 8
        if self.dialog.view_mode == "grid":
            thumb = QRect(rect.x() + pad, rect.y() + pad, rect.width() - 2 * pad, int((rect.width() - 2 * pad) * 9 / 16))
            text_x, text_w = thumb.x(), thumb.width()
            title_top = thumb.bottom() + 7
        else:
            thumb = QRect(rect.x() + pad, rect.y() + pad, 128, 72)
            text_x = thumb.right() + 12
            text_w = rect.right() - pad - text_x
            title_top = thumb.y() + 2
        title_lines = _wrap_lines(item.get("title", ""), fm_title, text_w, 2)
        title_rect = QRect(text_x, title_top, text_w, fm_title.height() * max(1, len(title_lines)))
        channel = item.get("channel") or ""
        channel_w = min(fm_small.horizontalAdvance(channel), text_w)
        channel_rect = QRect(text_x, title_rect.bottom() + 4, channel_w, fm_small.height())
        return {
            "thumb": thumb, "title_rect": title_rect, "title_lines": title_lines,
            "channel_rect": channel_rect, "title_font": title_font, "small_font": small_font,
        }

    def _layout_channel(self, rect: QRect, item: dict, base_font: QFont) -> dict:
        """Canal: avatar redondo + nombre + suscriptores, sin miniatura 16:9 -- se distingue
        a propósito de una tarjeta de video/playlist."""
        title_font, small_font = self._fonts(base_font)
        fm_title, fm_small = QFontMetrics(title_font), QFontMetrics(small_font)
        pad = 10
        name_h, sub_h, gap = fm_title.height(), fm_small.height(), 6
        if self.dialog.view_mode == "grid":
            avatar_size = max(40, min(64, rect.height() - (name_h + sub_h + gap * 2 + 2 * pad)))
            block_h = avatar_size + gap + name_h + sub_h
            top = rect.y() + max(pad, (rect.height() - block_h) // 2)
            cx = rect.x() + rect.width() // 2
            avatar = QRect(cx - avatar_size // 2, top, avatar_size, avatar_size)
            text_x, text_w = rect.x() + pad, rect.width() - 2 * pad
            align = Qt.AlignHCenter
        else:
            avatar_size = 56
            avatar = QRect(rect.x() + pad, rect.y() + (rect.height() - avatar_size) // 2, avatar_size, avatar_size)
            text_x = avatar.right() + 14
            text_w = rect.right() - pad - text_x
            top = rect.y() + (rect.height() - (name_h + gap + sub_h)) // 2
            align = Qt.AlignLeft
        name_rect = QRect(text_x, avatar.bottom() + gap if self.dialog.view_mode == "grid" else top, text_w, name_h)
        sub_rect = QRect(text_x, name_rect.bottom() + 2, text_w, sub_h)
        return {
            "avatar": avatar, "name_rect": name_rect, "sub_rect": sub_rect,
            "title_font": title_font, "small_font": small_font, "align": align,
        }

    def sizeHint(self, option, index):
        view = self.dialog.results_view
        available = view.viewport().width() - 2
        if self.dialog.view_mode != "grid":
            return QSize(max(300, available - 2 * view.spacing()), LIST_ITEM_HEIGHT)
        # Las columnas se estiran para llenar todo el ancho (sin hueco a la derecha).
        slot = GRID_MIN_ITEM_WIDTH + 2 * view.spacing()
        columns = max(1, available // slot)
        # En IconMode el espaciado va una vez entre tarjetas (más uno al borde).
        width = (available - view.spacing()) // columns - view.spacing()
        title_font, small_font = self._fonts(option.font)
        thumb_h = int((width - 16) * 9 / 16)
        height = 8 + thumb_h + 7 + 2 * QFontMetrics(title_font).height() + 4 + QFontMetrics(small_font).height() + 10
        return QSize(width, height)

    # -- pintado --------------------------------------------------
    def paint(self, painter, option, index):
        item = index.data(ITEM_ROLE) or {}
        rect = option.rect.adjusted(1, 1, -1, -1)
        hovered = bool(option.state & QStyle.State_MouseOver)

        if item.get("kind") == KIND_CHANNEL:
            self._paint_channel(painter, rect, item, option, hovered)
            return

        selected = bool(option.state & QStyle.State_Selected)
        geo = self.layout(rect, item, option.font)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        # Fondo de la tarjeta
        painter.setPen(QPen(self.c_accent if selected else self.c_border, 2 if selected else 1))
        painter.setBrush(self.c_card_hover if hovered else self.c_card)
        painter.drawRoundedRect(rect, 8, 8)

        # "Carpeta" de playlist: un par de bordes desplazados detrás de la miniatura real,
        # simulando hojas apiladas -- sin pedir fotos de otros videos (ver conversación).
        thumb = geo["thumb"]
        if item.get("kind") == KIND_PLAYLIST:
            # Una sola "hoja" desplazada detrás del thumb, con un color bastante más claro
            # que el fondo de la tarjeta -- un borde/relleno demasiado parecido al fondo
            # (probado: #222 sobre #1a1a1a) resultaba invisible en la práctica, no se leía
            # como "apilado" (ver conversación).
            stack_rect = thumb.translated(8, -8)
            stack_fill = QColor(self.c_border).lighter(160)
            painter.setPen(QPen(stack_fill.lighter(120), 1))
            painter.setBrush(stack_fill)
            painter.drawRoundedRect(stack_rect, 5, 5)
        clip = QPainterPath()
        clip.addRoundedRect(thumb, 6, 6)
        painter.save()
        painter.setClipPath(clip)
        pix = self.dialog.pixmap_for(item.get("thumb_url"))
        if pix is not None and not pix.isNull() and item.get("is_short"):
            # La miniatura chica de un Short es horizontal con el video vertical al centro
            # y relleno a los lados: se muestra solo esa franja 9:16, centrada.
            painter.fillRect(thumb, QColor(0, 0, 0))
            strip_w = int(pix.height() * 9 / 16)
            src = QRect((pix.width() - strip_w) // 2, 0, strip_w, pix.height())
            dst_w = int(thumb.height() * 9 / 16)
            dst = QRect(thumb.x() + (thumb.width() - dst_w) // 2, thumb.y(), dst_w, thumb.height())
            painter.drawPixmap(dst, pix, src)
        elif pix is not None and not pix.isNull():
            scaled = pix.scaled(thumb.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            sx = (scaled.width() - thumb.width()) // 2
            sy = (scaled.height() - thumb.height()) // 2
            painter.drawPixmap(thumb, scaled, QRect(sx, sy, thumb.width(), thumb.height()))
        else:
            painter.fillRect(thumb, self.c_placeholder)
        painter.restore()

        # Duración / EN VIVO / Short / Playlist, sobre la esquina inferior derecha
        if item.get("kind") == KIND_PLAYLIST:
            badge_text, badge_bg, badge_fg = QCoreApplication.translate("MediaSearchDialog", "Playlist"), QColor(0, 0, 0, 200), QColor("#ffffff")
        elif item.get("is_live"):
            badge_text, badge_bg, badge_fg = QCoreApplication.translate("MediaSearchDialog", "EN VIVO"), self.c_live, QColor("#ffffff")
        elif item.get("duration"):
            badge_text, badge_bg, badge_fg = format_duration(item["duration"]), QColor(0, 0, 0, 200), QColor("#ffffff")
        elif item.get("is_short"):
            badge_text, badge_bg, badge_fg = QCoreApplication.translate("MediaSearchDialog", "Short"), QColor(0, 0, 0, 200), QColor("#ffffff")
        else:
            badge_text = ""
        if badge_text:
            painter.setFont(geo["small_font"])
            fm = QFontMetrics(geo["small_font"])
            bw, bh = fm.horizontalAdvance(badge_text) + 10, fm.height() + 2
            badge = QRect(thumb.right() - bw - 4, thumb.bottom() - bh - 4, bw, bh)
            painter.setPen(Qt.NoPen)
            painter.setBrush(badge_bg)
            painter.drawRoundedRect(badge, 4, 4)
            painter.setPen(badge_fg)
            painter.drawText(badge, Qt.AlignCenter, badge_text)

        # Marca de seleccionado
        if selected:
            mark = QRect(thumb.x() + 6, thumb.y() + 6, 20, 20)
            painter.setPen(Qt.NoPen)
            painter.setBrush(self.c_accent)
            painter.drawEllipse(mark)
            painter.setPen(QPen(self.c_on_accent, 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPolyline([
                QPoint(mark.x() + 5, mark.y() + 10), QPoint(mark.x() + 9, mark.y() + 14), QPoint(mark.x() + 15, mark.y() + 6),
            ])

        # Título
        painter.setFont(geo["title_font"])
        painter.setPen(self.c_text)
        line_h = QFontMetrics(geo["title_font"]).height()
        for i, line in enumerate(geo["title_lines"]):
            r = QRect(geo["title_rect"].x(), geo["title_rect"].y() + i * line_h, geo["title_rect"].width(), line_h)
            painter.drawText(r, Qt.AlignLeft | Qt.AlignVCenter, line)

        # Canal (clicable solo si hay URL de canal, ver _ResultsView)
        channel = item.get("channel") or ""
        if channel:
            font = QFont(geo["small_font"])
            clickable = bool(item.get("channel_url"))
            link_hover = clickable and self.dialog.results_view.hover_channel_row == index.row()
            font.setUnderline(link_hover)
            painter.setFont(font)
            painter.setPen(self.c_accent if link_hover else self.c_muted)
            cr = geo["channel_rect"]
            text = QFontMetrics(font).elidedText(channel, Qt.ElideRight, cr.width())
            painter.drawText(cr, Qt.AlignLeft | Qt.AlignVCenter, text)

        painter.restore()

    def _paint_channel(self, painter, rect, item, option, hovered):
        """Tarjeta de canal: avatar redondo + nombre + suscriptores. Nunca se selecciona
        (ver _ResultsView) -- un clic en cualquier parte navega el canal, así que aquí no
        hay marca de "seleccionado" que dibujar."""
        geo = self._layout_channel(rect, item, option.font)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        painter.setPen(QPen(self.c_border, 1))
        painter.setBrush(self.c_card_hover if hovered else self.c_card)
        painter.drawRoundedRect(rect, 8, 8)

        avatar = geo["avatar"]
        pix = self.dialog.pixmap_for(item.get("thumb_url"))
        painter.setPen(Qt.NoPen)
        if pix is not None and not pix.isNull():
            clip = QPainterPath()
            clip.addEllipse(avatar)
            painter.save()
            painter.setClipPath(clip)
            scaled = pix.scaled(avatar.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            sx, sy = (scaled.width() - avatar.width()) // 2, (scaled.height() - avatar.height()) // 2
            painter.drawPixmap(avatar, scaled, QRect(sx, sy, avatar.width(), avatar.height()))
            painter.restore()
        else:
            painter.setBrush(self.c_placeholder)
            painter.drawEllipse(avatar)

        align = geo["align"] | Qt.AlignVCenter
        painter.setFont(geo["title_font"])
        painter.setPen(self.c_text)
        name = QFontMetrics(geo["title_font"]).elidedText(item.get("title", ""), Qt.ElideRight, geo["name_rect"].width())
        painter.drawText(geo["name_rect"], align, name)
        if item.get("is_verified"):
            # Palomita de verificado, pegada al nombre.
            fm = QFontMetrics(geo["title_font"])
            name_w = fm.horizontalAdvance(name)
            cy = geo["name_rect"].center().y()
            if geo["align"] == Qt.AlignHCenter:
                badge_x = geo["name_rect"].center().x() + name_w // 2 + 5
            else:
                badge_x = geo["name_rect"].x() + name_w + 5
            badge = QRect(badge_x, cy - 6, 13, 13)
            painter.setPen(Qt.NoPen)
            painter.setBrush(self.c_accent)
            painter.drawEllipse(badge)
            painter.setPen(QPen(self.c_on_accent, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPolyline([
                QPoint(badge.x() + 3, badge.y() + 7), QPoint(badge.x() + 5, badge.y() + 9), QPoint(badge.x() + 10, badge.y() + 4),
            ])

        subs = item.get("subscriber_count")
        if subs:
            text = QCoreApplication.translate("MediaSearchDialog", "{0} suscriptores").format(format_count(subs))
            painter.setFont(geo["small_font"])
            painter.setPen(self.c_muted)
            painter.drawText(geo["sub_rect"], align, text)

        painter.restore()


class _ResultsView(QListView):
    channel_clicked = Signal(dict)

    def __init__(self, dialog):
        super().__init__(dialog)
        self.dialog = dialog
        self.hover_channel_row = -1
        self.setMouseTracking(True)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setSpacing(6)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setObjectName("mediaSearchResults")

    def set_view_mode(self, mode):
        if mode == "grid":
            self.setViewMode(QListView.IconMode)
            self.setFlow(QListView.LeftToRight)
            self.setWrapping(True)
        else:
            self.setViewMode(QListView.ListMode)
            self.setFlow(QListView.TopToBottom)
            self.setWrapping(False)
        self.setMovement(QListView.Static)
        self.setResizeMode(QListView.Adjust)
        self.scheduleDelayedItemsLayout()

    def _row_item(self, pos):
        index = self.indexAt(pos)
        if not index.isValid():
            return None, None
        return index, (index.data(ITEM_ROLE) or {})

    def _channel_hit(self, pos):
        """Clic en el nombre del canal DEBAJO de un video/playlist (no en una tarjeta de
        canal completa, ver _whole_row_channel_hit)."""
        index, item = self._row_item(pos)
        if not item or item.get("kind") == KIND_CHANNEL:
            return None
        if not item.get("channel_url") or not item.get("channel"):
            return None
        rect = self.visualRect(index).adjusted(1, 1, -1, -1)
        geo = self.itemDelegate().layout(rect, item, self.font())
        return (index, item) if geo["channel_rect"].contains(pos) else None

    def _whole_row_channel_hit(self, pos):
        """Una tarjeta de canal completa: cualquier clic en ella navega el canal, nunca se
        selecciona (ver conversación)."""
        index, item = self._row_item(pos)
        if item and item.get("kind") == KIND_CHANNEL:
            return (index, item)
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            hit = self._whole_row_channel_hit(event.position().toPoint()) or self._channel_hit(event.position().toPoint())
            if hit:
                # No pasa a super(): un clic en el canal no debe marcar/desmarcar la tarjeta.
                self.channel_clicked.emit(hit[1])
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        hit = self._whole_row_channel_hit(pos) or self._channel_hit(pos)
        row = hit[0].row() if hit else -1
        if row != self.hover_channel_row:
            self.hover_channel_row = row
            if hit:
                self.viewport().setCursor(Qt.PointingHandCursor)
            else:
                self.viewport().unsetCursor()
            self.viewport().update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self.hover_channel_row != -1:
            self.hover_channel_row = -1
            self.viewport().unsetCursor()
            self.viewport().update()
        super().leaveEvent(event)


# ──────────────────────────────────────────────────────────────
# Ventana
# ──────────────────────────────────────────────────────────────
class MediaSearchDialog(QDialog):
    """multi_select=True: se marcan varias tarjetas y el botón dice 'Agregar a la cola (N)'.
    multi_select=False (Proceso Avanzado SOLO): una sola, doble clic la usa directamente.
    Tras exec() aceptado, selected_items tiene los ítems elegidos en el orden en que se
    marcaron."""

    FILTERS = [
        (media_search.FILTER_ALL, QCoreApplication.translate("MediaSearchDialog", "Todos")),
        (media_search.FILTER_VIDEOS, QCoreApplication.translate("MediaSearchDialog", "Videos")),
        (media_search.FILTER_SHORTS, QCoreApplication.translate("MediaSearchDialog", "Shorts")),
        (media_search.FILTER_LIVE, QCoreApplication.translate("MediaSearchDialog", "Directos")),
    ]

    def __init__(self, parent=None, multi_select=True, initial_query=""):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowTitle(self.tr("Buscar medios"))
        self.setModal(True)
        self.setObjectName("mediaSearchOverlay")

        self.multi_select = multi_select
        self.selected_items = []
        self._selected = {}  # url -> ítem (se conserva al pasar de la búsqueda a un canal)
        self._pixmaps = {}
        self._generation = 0
        self._loading = False
        self._has_more = False
        self._page = 1
        self._items = []
        self._error_text = ""

        config = get_config()
        self.view_mode = config.get("media_search_view", "grid")
        if self.view_mode not in ("grid", "list"):
            self.view_mode = "grid"

        # Estado de la búsqueda (para volver desde un canal) y del canal abierto.
        self._search_state = None
        self._channel = None  # {"url", "name"} mientras se navega un canal
        # Si no está vacío, el cuadro de búsqueda ya no busca en todo YouTube: busca DENTRO
        # de self._channel (ver conversación -- "búsqueda dentro de una búsqueda", mismo
        # cuadro de texto, comportamiento contextual). Se limpia al abrir otro canal, volver
        # o vaciar el cuadro.
        self._channel_query = ""
        self._search_filter = media_search.FILTER_ALL
        self._last_query = ""
        self._last_source = media_search.SOURCE_YOUTUBE

        self._thumb_cache = SearchThumbnailCache.get_instance()
        self._thumb_cache.thumbnail_ready.connect(self._on_thumbnail_ready)

        self._init_ui()
        source = config.get("media_search_source", media_search.SOURCE_YOUTUBE)
        idx = self.combo_source.findData(source)
        self.combo_source.setCurrentIndex(idx if idx >= 0 else 0)
        self._sync_filter_visibility()
        self._update_footer()

        if initial_query:
            self.search_input.setText(initial_query)
            QTimer.singleShot(0, self._start_new_search)
        else:
            QTimer.singleShot(0, self.search_input.setFocus)

    # ── Capa y posición (igual que FragmentDialog) ────────────────
    def showEvent(self, event):
        super().showEvent(event)
        win = self.parent().window() if self.parent() else None
        if win:
            pos = win.mapToGlobal(QPoint(0, 0))
            self.setGeometry(pos.x(), pos.y(), win.width(), win.height())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 185))
        painter.end()
        super().paintEvent(event)

    def keyPressEvent(self, event):
        # Evitar que la ventana se cierre al presionar Enter
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.accept()
            return
        super().keyPressEvent(event)

    # ── UI ────────────────────────────────────────────────────────
    def _icon(self, name, color_key="texto_principal", default="#e0e0e0", size=18):
        return get_colored_svg_icon(name, get_theme_token(color_key, default), size=size)

    def _init_ui(self):
        overlay_layout = QVBoxLayout(self)
        overlay_layout.setContentsMargins(16, 12, 16, 12)
        overlay_layout.setAlignment(Qt.AlignCenter)

        self.card = QFrame()
        self.card.setObjectName("mediaSearchCard")
        self.card.setMinimumSize(740, 480)
        self.card.setMaximumSize(980, 620)
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        # Barra de título
        title_bar = QWidget()
        title_bar.setObjectName("mediaSearchTitleBar")
        title_bar.setFixedHeight(38)
        tb_layout = QHBoxLayout(title_bar)
        tb_layout.setContentsMargins(16, 0, 10, 0)
        title_lbl = QLabel(self.tr("Buscar medios"))
        title_lbl.setObjectName("mediaSearchTitleLabel")
        tb_layout.addWidget(title_lbl)
        tb_layout.addStretch()
        btn_close = QPushButton()
        btn_close.setObjectName("modalCloseBtn")
        btn_close.setIcon(self._icon("close.svg", size=14))
        btn_close.setIconSize(QSize(14, 14))
        btn_close.setFixedSize(26, 26)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setToolTip(self.tr("Cerrar (Esc)"))
        btn_close.clicked.connect(self.reject)
        tb_layout.addWidget(btn_close)
        card_layout.addWidget(title_bar)

        content = QWidget()
        content.setObjectName("mediaSearchMainContainer")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(10)

        # Fila 1: fuente + texto + buscar + vista
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        self.combo_source = AutoPopupComboBox()
        self.combo_source.addItem("YouTube", media_search.SOURCE_YOUTUBE)
        self.combo_source.addItem("SoundCloud", media_search.SOURCE_SOUNDCLOUD)
        self.combo_source.setToolTip(self.tr("Sitio donde buscar"))
        self.combo_source.setMinimumWidth(130)
        self.combo_source.currentIndexChanged.connect(self._on_source_changed)
        row1.addWidget(self.combo_source)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(self.tr("Escribe lo que quieres buscar y presiona Enter"))
        self.search_input.setClearButtonEnabled(True)
        self.search_input.returnPressed.connect(self._start_new_search)
        self.search_input.textChanged.connect(self._on_search_text_changed)
        row1.addWidget(self.search_input, 1)

        self.btn_search = QPushButton()
        self.btn_search.setObjectName("analyzeButton")
        self.btn_search.setFixedSize(34, 32)
        self.btn_search.setIcon(self._icon("search.svg", "boton_texto", "#000000"))
        self.btn_search.setIconSize(QSize(18, 18))
        self.btn_search.setStyleSheet("padding: 0px;")
        self.btn_search.setToolTip(self.tr("Buscar"))
        self.btn_search.clicked.connect(self._start_new_search)
        row1.addWidget(self.btn_search)

        row1.addSpacing(6)
        self.btn_grid = QPushButton()
        self.btn_list = QPushButton()
        for btn, icon, tip in ((self.btn_grid, "grid_view.svg", self.tr("Vista en cuadrícula")),
                               (self.btn_list, "view_list.svg", self.tr("Vista en lista"))):
            btn.setCheckable(True)
            btn.setFixedSize(32, 32)
            btn.setIcon(self._icon(icon))
            btn.setIconSize(QSize(18, 18))
            btn.setToolTip(tip)
            btn.setObjectName("mediaSearchViewButton")
            btn.setCursor(Qt.PointingHandCursor)
            row1.addWidget(btn)
        view_group = QButtonGroup(self)
        view_group.setExclusive(True)
        view_group.addButton(self.btn_grid)
        view_group.addButton(self.btn_list)
        (self.btn_grid if self.view_mode == "grid" else self.btn_list).setChecked(True)
        self.btn_grid.clicked.connect(lambda: self._set_view_mode("grid"))
        self.btn_list.clicked.connect(lambda: self._set_view_mode("list"))
        layout.addLayout(row1)

        # Barra de canal (solo mientras se navega un canal)
        self.channel_bar = QWidget()
        cb_layout = QHBoxLayout(self.channel_bar)
        cb_layout.setContentsMargins(0, 0, 0, 0)
        cb_layout.setSpacing(10)
        self.btn_back = QPushButton()
        self.btn_back.setObjectName("secondaryButton")
        self.btn_back.setIcon(self._icon("arrow_back.svg", "boton_secundario_texto", "#B9E640", 16))
        self.btn_back.setIconSize(QSize(16, 16))
        self.btn_back.setFixedHeight(30)
        self.btn_back.setCursor(Qt.PointingHandCursor)
        self.btn_back.clicked.connect(self._back_to_search)
        cb_layout.addWidget(self.btn_back)
        self.channel_label = QLabel()
        self.channel_label.setObjectName("mediaSearchChannelLabel")
        cb_layout.addWidget(self.channel_label, 1)
        self.channel_bar.hide()
        layout.addWidget(self.channel_bar)

        # Fila 2: filtros
        self.filter_bar = QWidget()
        fb_layout = QHBoxLayout(self.filter_bar)
        fb_layout.setContentsMargins(0, 0, 0, 0)
        fb_layout.setSpacing(6)
        self.filter_group = QButtonGroup(self)
        self.filter_group.setExclusive(True)
        self.filter_buttons = {}
        for key, label in self.FILTERS:
            btn = QPushButton(self.tr(label))
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {get_theme_token('fondo_elemento', '#2d2d2d')};
                    border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                    padding: 4px 8px;
                    font-size: 11px;
                    border-radius: 6px;
                }}
                QPushButton:checked {{
                    background-color: {get_theme_token('acento_primario', '#B9E640')};
                    color: {get_theme_token('fondo_principal', '#0a0a0a')};
                    font-weight: bold;
                }}
            """)
            btn.clicked.connect(lambda _=False, k=key: self._on_filter_clicked(k))
            self.filter_group.addButton(btn)
            self.filter_buttons[key] = btn
            fb_layout.addWidget(btn)
        self.filter_buttons[media_search.FILTER_ALL].setChecked(True)
        fb_layout.addStretch()
        layout.addWidget(self.filter_bar)

        self.hint_label = QLabel()
        self.hint_label.setObjectName("mediaSearchHint")
        self.hint_label.setWordWrap(True)
        self.hint_label.hide()
        layout.addWidget(self.hint_label)

        # Resultados
        self.stack = QStackedWidget()
        self.message_label = QLabel(self.tr("Busca videos o audios por nombre, como en YouTube."))
        self.message_label.setObjectName("mediaSearchMessage")
        self.message_label.setAlignment(Qt.AlignCenter)
        self.message_label.setWordWrap(True)
        self.stack.addWidget(self.message_label)

        self.model = QStandardItemModel(self)
        self.results_view = _ResultsView(self)
        self.results_view.setModel(self.model)
        self.results_view.setItemDelegate(_ResultDelegate(self))
        self.results_view.setSelectionMode(
            QAbstractItemView.MultiSelection if self.multi_select else QAbstractItemView.SingleSelection
        )
        self.results_view.set_view_mode(self.view_mode)
        self.results_view.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.results_view.channel_clicked.connect(self._open_channel)
        self.results_view.doubleClicked.connect(self._on_double_clicked)
        self.results_view.verticalScrollBar().valueChanged.connect(self._on_scrolled)
        self.stack.addWidget(self.results_view)
        layout.addWidget(self.stack, 1)

        # Pie
        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.status_label = QLabel()
        self.status_label.setObjectName("mediaSearchStatus")
        footer.addWidget(self.status_label)
        self.btn_more = QPushButton(self.tr("Cargar más"))
        self.btn_more.setObjectName("secondaryButton")
        self.btn_more.setFixedHeight(30)
        self.btn_more.clicked.connect(self._load_more)
        self.btn_more.hide()
        footer.addWidget(self.btn_more)
        footer.addStretch()

        btn_cancel = QPushButton(self.tr("Cancelar"))
        btn_cancel.setObjectName("secondaryButton")
        btn_cancel.setFixedHeight(35)
        btn_cancel.setMinimumWidth(110)
        btn_cancel.clicked.connect(self.reject)
        footer.addWidget(btn_cancel)
        self.btn_accept = QPushButton()
        self.btn_accept.setObjectName("analyzeButton")
        self.btn_accept.setFixedHeight(35)
        self.btn_accept.setMinimumWidth(160)
        self.btn_accept.clicked.connect(self._accept_selection)
        footer.addWidget(self.btn_accept)
        layout.addLayout(footer)

        card_layout.addWidget(content, 1)
        overlay_layout.addWidget(self.card)

    # ── Vista ─────────────────────────────────────────────────────
    def _set_view_mode(self, mode):
        if mode == self.view_mode:
            return
        self.view_mode = mode
        self.results_view.set_view_mode(mode)
        config = get_config()
        config["media_search_view"] = mode
        save_config(config)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.results_view.scheduleDelayedItemsLayout()

    # ── Miniaturas ────────────────────────────────────────────────
    def pixmap_for(self, url):
        return self._pixmaps.get(url) if url else None

    def _request_thumbnails(self, items):
        for item in items:
            url = item.get("thumb_url")
            if not url or url in self._pixmaps:
                continue
            path = self._thumb_cache.request(url)
            if path:
                self._load_pixmap(url, path)
        self.results_view.viewport().update()

    def _load_pixmap(self, url, path):
        pix = QPixmap(path)
        if not pix.isNull():
            self._pixmaps[url] = pix

    def _on_thumbnail_ready(self, url, path):
        if url in self._pixmaps:
            return
        if any(item.get("thumb_url") == url for item in self._items):
            self._load_pixmap(url, path)
            self.results_view.viewport().update()

    # ── Fuente y filtros ─────────────────────────────────────────
    def _current_source(self):
        return self.combo_source.currentData() or media_search.SOURCE_YOUTUBE

    def _current_filter(self):
        for key, btn in self.filter_buttons.items():
            if btn.isChecked():
                return key
        return media_search.FILTER_ALL

    def _set_filter(self, key):
        btn = self.filter_buttons.get(key)
        if btn:
            btn.setChecked(True)

    def _sync_filter_visibility(self):
        youtube = self._current_source() == media_search.SOURCE_YOUTUBE
        self.filter_bar.setVisible(youtube or self._channel is not None)
        # Un canal no tiene sección "Todos".
        self.filter_buttons[media_search.FILTER_ALL].setVisible(self._channel is None)

    def _on_source_changed(self):
        config = get_config()
        config["media_search_source"] = self._current_source()
        save_config(config)
        if self._channel is not None:
            self._back_to_search()
        self._sync_filter_visibility()
        if self.search_input.text().strip():
            self._start_new_search()

    def _on_filter_clicked(self, key):
        if self._channel is not None:
            self._start_channel_page(1)
        elif self.search_input.text().strip():
            self._start_new_search()

    # ── Búsqueda ─────────────────────────────────────────────────
    def _start_new_search(self):
        query = self.search_input.text().strip()
        if not query:
            return
        if self._channel is not None:
            # Buscar DENTRO del canal actual, sin salir de él (ver conversación).
            self._channel_query = query
            self._update_channel_label()
            self._run(1)
            return
        self._last_query = query
        self._last_source = self._current_source()
        self._search_filter = self._current_filter()
        self._run(1)

    def _on_search_text_changed(self, text):
        # Vaciar el cuadro mientras se busca dentro de un canal vuelve a mostrar esa
        # sección del canal tal cual (Videos/Shorts/Directos), sin salir de él.
        if self._channel is not None and self._channel_query and not text.strip():
            self._channel_query = ""
            self._update_channel_label()
            self._start_channel_page(1)

    def _load_more(self):
        if not self._loading and self._has_more:
            self._run(self._page + 1)

    def _on_scrolled(self, value):
        # Llegar al final de la lista también carga la página siguiente.
        bar = self.results_view.verticalScrollBar()
        if value >= bar.maximum() - 40 and bar.maximum() > 0:
            self._load_more()

    def _run(self, page):
        self._generation += 1
        self._loading = True
        if self._channel is not None:
            if self._channel_query:
                worker = _SearchWorker(self._generation, page, media_search.search_in_channel,
                                       self._channel["url"], self._channel_query, self._current_filter(), page)
            else:
                worker = _SearchWorker(self._generation, page, media_search.browse_channel,
                                       self._channel["url"], self._current_filter(), page)
        else:
            worker = _SearchWorker(self._generation, page, media_search.search,
                                   self._last_query, self._last_source, self._current_filter(), page)
        worker.done.connect(self._on_search_done)
        worker.finished.connect(lambda w=worker: _RUNNING_WORKERS.discard(w))
        _RUNNING_WORKERS.add(worker)

        if page == 1:
            self._set_items([])
            self.hint_label.hide()
            self.message_label.setText(self.tr("Buscando..."))
            self.stack.setCurrentIndex(0)
        self._error_text = ""
        self.status_label.setText(self.tr("Buscando..."))
        self.btn_more.setEnabled(False)
        worker.start()

    def _on_search_done(self, generation, page, result, error):
        if generation != self._generation:
            return  # respuesta de una búsqueda vieja
        self._loading = False
        self.btn_more.setEnabled(True)

        if error:
            self._has_more = False
            msg = self.tr("Error al buscar: {0}").format(error)
            self._error_text = msg
            if not self._items:
                self.message_label.setText(msg)
                self.stack.setCurrentIndex(0)
            self.status_label.setText(msg)
            self._update_footer()
            return

        self._page = page
        self._has_more = bool(result.get("has_more"))
        known = {item["id"] for item in self._items}
        new_items = [item for item in result.get("results", []) if item["id"] not in known]
        self._append_items(new_items)
        self._show_hint(result.get("hint", ""))

        if not self._items:
            if self._channel is not None:
                self.message_label.setText(self.tr("Este canal no tiene contenido en esta sección."))
            else:
                self.message_label.setText(self.tr("No se encontraron resultados."))
            self.stack.setCurrentIndex(0)
        else:
            self.stack.setCurrentIndex(1)
        self._update_footer()

    def _show_hint(self, hint):
        tag = media_search.shorts_hashtag(self._last_query)
        if self._channel is None and hint == "hashtag":
            self.hint_label.setText(self.tr("Los Shorts se buscan por hashtag: #{0}").format(tag))
            self.hint_label.show()
        elif self._channel is None and hint == "fallback":
            self.hint_label.setText(self.tr(
                "No hay Shorts con el hashtag #{0}; se muestran los del filtro de Shorts de YouTube, "
                "que suele traer pocos resultados."
            ).format(tag))
            self.hint_label.show()
        elif self._page == 1:
            self.hint_label.hide()

    # ── Modelo y selección ───────────────────────────────────────
    def _set_items(self, items):
        # clear() no debe tocar self._selected: lo marcado en la búsqueda se conserva al
        # entrar a un canal y al volver.
        sel_model = self.results_view.selectionModel()
        sel_model.blockSignals(True)
        self.model.clear()
        sel_model.blockSignals(False)
        self._items = []
        self._append_items(items)

    def _append_items(self, items):
        if not items:
            return
        sel_model = self.results_view.selectionModel()
        sel_model.blockSignals(True)
        for item in items:
            row = QStandardItem()
            row.setData(item, ITEM_ROLE)
            row.setToolTip(self._tooltip_for(item))
            row.setEditable(False)
            if item.get("kind") == KIND_CHANNEL:
                # Nunca seleccionable: un clic en la tarjeta navega el canal (ver
                # _ResultsView._whole_row_channel_hit), no lo agrega a la cola.
                row.setFlags(row.flags() & ~Qt.ItemIsSelectable)
            self.model.appendRow(row)
            self._items.append(item)
            if item["url"] in self._selected:
                sel_model.select(row.index(), QItemSelectionModel.Select)
        sel_model.blockSignals(False)
        self.results_view.viewport().update()
        self._request_thumbnails(items)

    def _tooltip_for(self, item):
        parts = [item.get("title", "")]
        if item.get("kind") == KIND_CHANNEL:
            if item.get("subscriber_count"):
                parts.append(self.tr("{0} suscriptores").format(format_count(item["subscriber_count"])))
            return "\n".join(parts)
        if item.get("kind") == KIND_PLAYLIST:
            parts.append(self.tr("Playlist"))
        if item.get("channel"):
            parts.append(item["channel"])
        if item.get("is_live"):
            parts.append(self.tr("Directo en curso"))
        return "\n".join(parts)

    def _on_selection_changed(self, selected, deselected):
        for index in deselected.indexes():
            item = index.data(ITEM_ROLE) or {}
            self._selected.pop(item.get("url"), None)
        for index in selected.indexes():
            item = index.data(ITEM_ROLE) or {}
            if not item.get("url"):
                continue
            if not self.multi_select:
                self._selected.clear()
            self._selected[item["url"]] = item
        self._update_footer()

    def _update_footer(self):
        count = len(self._selected)
        if self.multi_select:
            self.btn_accept.setText(self.tr("Agregar a la cola ({0})").format(count))
        else:
            self.btn_accept.setText(self.tr("Usar este video"))
        self.btn_accept.setEnabled(count > 0)
        self.btn_more.setVisible(bool(self._items) and self._has_more)
        if self._loading:
            return
        if self._error_text:
            self.status_label.setText(self._error_text)
        elif self._items:
            if self.multi_select and count:
                self.status_label.setText(self.tr("{0} resultados · {1} seleccionados").format(len(self._items), count))
            else:
                self.status_label.setText(self.tr("{0} resultados").format(len(self._items)))
        else:
            self.status_label.setText("")

    def _on_double_clicked(self, index):
        if not self.multi_select and index.isValid():
            self._accept_selection()

    # ── Canal ────────────────────────────────────────────────────
    def _open_channel(self, item):
        # Dos orígenes posibles: una tarjeta de canal completa (su propia URL vive en
        # "url") o el nombre de canal debajo de un video/playlist ("channel_url").
        if item.get("kind") == KIND_CHANNEL:
            channel_url, channel_name = item.get("url"), item.get("title") or ""
        else:
            channel_url, channel_name = item.get("channel_url"), item.get("channel") or ""
        if not channel_url:
            return
        if self._channel is None:
            # Guardar la búsqueda tal cual para "Volver" sin repetirla.
            self._search_state = {
                "items": list(self._items),
                "page": self._page,
                "has_more": self._has_more,
                "filter": self._current_filter(),
                "scroll": self.results_view.verticalScrollBar().value(),
                "hint": self.hint_label.text() if self.hint_label.isVisible() else "",
            }
        self._channel = {"url": channel_url, "name": channel_name}
        self._channel_query = ""
        self.btn_back.setText(self.tr("Volver a “{0}”").format(self._last_query))
        self.search_input.blockSignals(True)
        self.search_input.clear()
        self.search_input.blockSignals(False)
        self.search_input.setPlaceholderText(self.tr("Buscar dentro de este canal..."))
        self._update_channel_label()
        self.channel_bar.show()
        self.hint_label.hide()
        if self._current_filter() == media_search.FILTER_ALL:
            self._set_filter(media_search.FILTER_VIDEOS)
        self._sync_filter_visibility()
        self._start_channel_page(1)

    def _update_channel_label(self):
        name = self._channel["name"] if self._channel else ""
        if self._channel_query:
            self.channel_label.setText(
                self.tr("Buscando “{0}” en: {1}").format(self._channel_query, name))
        else:
            self.channel_label.setText(self.tr("Canal: {0}").format(name))

    def _start_channel_page(self, page):
        self._run(page)

    def _back_to_search(self):
        state = self._search_state
        self._channel = None
        self._channel_query = ""
        self._search_state = None
        self.channel_bar.hide()
        self.search_input.setPlaceholderText(self.tr("Escribe lo que quieres buscar y presiona Enter"))
        # Restaurar el texto de la búsqueda de afuera (se vació al entrar al canal, ver
        # _open_channel) sin disparar _on_search_text_changed de paso.
        self.search_input.blockSignals(True)
        self.search_input.setText(self._last_query)
        self.search_input.blockSignals(False)
        self._generation += 1  # descarta cualquier carga del canal en curso
        self._loading = False
        if state:
            self._set_filter(state["filter"])
        self._sync_filter_visibility()
        if not state:
            self._set_items([])
            self.stack.setCurrentIndex(0)
            self._update_footer()
            return
        self._page = state["page"]
        self._has_more = state["has_more"]
        self._set_items(state["items"])
        if state["hint"]:
            self.hint_label.setText(state["hint"])
            self.hint_label.show()
        self.stack.setCurrentIndex(1 if self._items else 0)
        self.btn_more.setEnabled(True)
        self._update_footer()
        QTimer.singleShot(0, lambda: self.results_view.verticalScrollBar().setValue(state["scroll"]))

    # ── Cierre ───────────────────────────────────────────────────
    def _accept_selection(self):
        if not self._selected:
            return
        self.selected_items = list(self._selected.values())
        self.accept()

    def done(self, result):
        self._generation += 1
        try:
            self._thumb_cache.thumbnail_ready.disconnect(self._on_thumbnail_ready)
        except (RuntimeError, TypeError):
            pass
        super().done(result)
        main_win = self.parent().window() if self.parent() else None
        if main_win:
            main_win.activateWindow()
            main_win.raise_()


def looks_like_url(text: str) -> bool:
    """True si el texto parece una URL (para decidir si Enter analiza o abre la búsqueda)."""
    text = (text or "").strip()
    if not text:
        return False
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", text):
        return True
    # Dominios pegados sin esquema (ej. youtu.be/xxxx, www.youtube.com/watch?v=...)
    return " " not in text and re.match(r"^[\w-]+(\.[\w-]+)+(/|$)", text) is not None


def confirm_live_download(parent, live_count, cut_enabled=False, total=1):
    """Aviso antes de descargar directos en curso. Con un solo video, 'No' cancela; con
    varios, 'No' omite solo los directos y sigue con el resto."""
    from gui.dialogs.dialogs import show_warning_confirm
    if total <= 1:
        text = QCoreApplication.translate(
            "MediaSearchDialog",
            "Este es un directo en curso. La descarga continuará hasta que termine la "
            "transmisión o la canceles.")
        question = QCoreApplication.translate("MediaSearchDialog", "¿Quieres continuar?")
    else:
        text = QCoreApplication.translate(
            "MediaSearchDialog",
            "{0} de los videos elegidos son directos en curso. Su descarga continuará "
            "hasta que termine la transmisión o la canceles.").format(live_count)
        question = QCoreApplication.translate(
            "MediaSearchDialog", "¿Quieres incluirlos? Si eliges No, se descargará solo el resto.")
    if cut_enabled:
        text += "\n\n" + QCoreApplication.translate(
            "MediaSearchDialog", "Los directos en curso no se pueden recortar: se descargarán completos.")
    title = QCoreApplication.translate("MediaSearchDialog", "Directo en curso")
    return show_warning_confirm(parent, title, text + "\n\n" + question)


def confirm_playlist_mode(parent, playlist_count):
    """Hay playlists entre lo seleccionado y el modo playlist de esa pestaña está apagado.
    Sí = lo activa (Modo Rápido abre su selector; Proceso Avanzado sigue lo que ya tenga
    configurado -- rápido con selector, o lento agregando todo). No = cada playlist se
    descarga solo con su primer video, igual que hace SOLO."""
    if playlist_count <= 1:
        text = QCoreApplication.translate(
            "MediaSearchDialog", "Elegiste una playlist. ¿Quieres activar el modo playlist?")
    else:
        text = QCoreApplication.translate(
            "MediaSearchDialog", "Elegiste {0} playlists. ¿Quieres activar el modo playlist?"
        ).format(playlist_count)
    text += "\n\n" + QCoreApplication.translate(
        "MediaSearchDialog",
        "Si eliges No, cada playlist se descargará solo con su primer video.")
    from gui.dialogs.dialogs import show_warning_confirm
    title = QCoreApplication.translate("MediaSearchDialog", "Playlist seleccionada")
    return show_warning_confirm(parent, title, text)


def ask_cut_one_by_one(parent):
    """Recorte activado + varios videos de la búsqueda: Sí abre el recorte de cada uno en
    secuencia, No los descarga completos."""
    from PySide6.QtWidgets import QMessageBox
    from gui.dialogs.dialogs import _apply_dialog_styles
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Icon.Question)
    msg.setWindowTitle(QCoreApplication.translate("MediaSearchDialog", "Corte de fragmentos"))
    msg.setText(QCoreApplication.translate(
        "MediaSearchDialog", "Tienes el corte de fragmentos activado. ¿Quieres recortar cada video uno por uno?"))
    msg.setInformativeText(QCoreApplication.translate(
        "MediaSearchDialog", "Si eliges No, los videos se descargarán completos."))
    msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    msg.setDefaultButton(QMessageBox.StandardButton.Yes)
    _apply_dialog_styles(msg)
    return msg.exec() == QMessageBox.StandardButton.Yes
