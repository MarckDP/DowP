# src/gui/widgets/background_canvas.py
"""Lienzo que dibuja la imagen de fondo elegida por el usuario detrás de un área (hoy,
el widget central de la ventana: ver core/utils/background_images.py).

Capas, de abajo hacia arriba: el color de fondo del tema, la imagen con su opacidad
(un PNG con transparencia deja ver ese color), y encima los paneles, que con un fondo
puesto llevan la transparencia que eligió el usuario (gui/styles.py, apply_glass).
Sin imagen no pinta nada: la ventana queda exactamente como siempre.

La imagen escalada se guarda lista y solo se recalcula si cambia el tamaño o un
ajuste. Mientras se arrastra el borde de la ventana se dibuja con escalado rápido, y
al soltar (150 ms sin cambios) se recalcula con buena calidad."""

import weakref

from PySide6.QtCore import QEvent, QObject, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QGuiApplication, QColor, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QWidget

from core.logger.logger_manager import logger
from core.utils import background_images as bg
from gui.styles import _inside_glass_area, get_theme_token

_RESIZE_SETTLE_MS = 150


class _Notifier(QObject):
    changed = Signal(str)  # lugar


_notifier = None


def background_notifier() -> _Notifier:
    """Avisa a los lienzos que cambió la imagen o un ajuste de un lugar."""
    global _notifier
    if _notifier is None:
        _notifier = _Notifier()
    return _notifier


def _factors(align: str) -> tuple[float, float]:
    vertical, horizontal = align.split("-")
    fx = {"left": 0.0, "center": 0.5, "right": 1.0}[horizontal]
    fy = {"top": 0.0, "center": 0.5, "bottom": 1.0}[vertical]
    return fx, fy


def target_rect(img_w: float, img_h: float, area_w: float, area_h: float, fit: str, align: str) -> QRectF:
    """Dónde va la imagen (en coordenadas del área) según el modo y la posición. La
    posición decide qué parte queda a la vista al recortar (Rellenar, Tamaño original)
    o dónde se ubica (Ajustar, Tamaño original). Mosaico se dibuja aparte."""
    if img_w <= 0 or img_h <= 0 or area_w <= 0 or area_h <= 0:
        return QRectF()
    if fit == bg.FIT_STRETCH:
        return QRectF(0, 0, area_w, area_h)
    if fit == bg.FIT_FILL:
        s = max(area_w / img_w, area_h / img_h)
    elif fit == bg.FIT_FIT:
        s = min(area_w / img_w, area_h / img_h)
    else:  # original (o mosaico, que usa el tamaño original de cada pieza)
        s = 1.0
    w, h = img_w * s, img_h * s
    fx, fy = _factors(align)
    return QRectF((area_w - w) * fx, (area_h - h) * fy, w, h)


def _load_image(path: str, blur: bool, strength: int = 120) -> QImage:
    if not blur:
        return QImage(path)
    # El desenfoque se calcula una sola vez por imagen (nada de efectos en vivo, que en
    # Qt son lentos). `strength`: lado mayor / radio (más chico = más desenfocado), así
    # se ve igual en cualquier imagen.
    #
    # Se desenfoca una copia reducida (radio final ~8 px) y se dibuja escalada: con un
    # radio tan grande el detalle que se pierde al achicar no se ve, y es decenas de
    # veces más rápido (3840 px: 880 ms -> unos ms; era la demora al abrir el primer
    # panel flotante). El devicePixelRatio de la copia conserva el tamaño lógico del
    # original, así "Tamaño original" y "Mosaico" no cambian.
    from PIL import Image, ImageFilter
    with Image.open(path) as im:
        original_w = im.size[0]
        small_side = strength * 8
        if max(im.size) > small_side:
            im.draft("RGB", (small_side, small_side))  # JPEG: se decodifica ya reducido
            im.thumbnail((small_side, small_side), Image.Resampling.BILINEAR)
        im = im.convert("RGBA")
        radius = max(4, max(im.size) // strength)
        out = im.filter(ImageFilter.GaussianBlur(radius))
        w, h = out.size
        image = QImage(out.tobytes("raw", "RGBA"), w, h, w * 4, QImage.Format_RGBA8888).copy()
    image.setDevicePixelRatio(w / original_w)
    return image


def _screen_cover_size() -> tuple[int, int]:
    """Ancho y alto (en píxeles reales) que abarcan cualquiera de las pantallas."""
    screens = QGuiApplication.screens()
    return (max((round(s.size().width() * s.devicePixelRatio()) for s in screens), default=0),
            max((round(s.size().height() * s.devicePixelRatio()) for s in screens), default=0))


def _fit_source(image: QImage, cover: tuple[int, int]) -> QImage:
    """Copia reducida lo justo para seguir cubriendo `cover`: una foto de 3840 px ocupa
    37 MB y en una pantalla de 1920 nunca se ve entera. Como en _load_image, el
    devicePixelRatio conserva el tamaño lógico del original."""
    w, h = image.width(), image.height()
    scale = max(cover[0] / max(w, 1), cover[1] / max(h, 1))
    if scale <= 0 or scale >= 1:
        return image
    small = image.scaled(max(1, round(w * scale)), max(1, round(h * scale)),
                         Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    small.setDevicePixelRatio(small.width() / w)
    return small


# Vidrio recortado (popovers, paneles superpuestos): más desenfocado que la opción
# "Desenfocar", como el vidrio esmerilado, para que lo que flota se distinga.
_FROSTED_STRENGTH = 60


# ── Imagen de las vistas previas vacías ───────────────────────────────────────
_PREVIEW = {"key": None, "source": None, "scaled": {}}
_PREVIEW_WATCHED = weakref.WeakSet()
_PREVIEW_HINTS = weakref.WeakSet()
_PREVIEW_CONNECTED = [False]


def _preview_source(path: str, settings: dict) -> QPixmap | None:
    """Una sola copia para todas las vistas previas; se vuelve a cargar si cambia."""
    reduce = settings["fit"] in (bg.FIT_FILL, bg.FIT_FIT, bg.FIT_STRETCH) and not settings["blur"]
    key = (path, settings["blur"], reduce)
    if _PREVIEW["key"] != key:
        image = _load_image(path, settings["blur"])
        if image.isNull():
            logger.warning(f"Fondo: no se pudo cargar {path}")
        elif reduce:
            image = _fit_source(image, _screen_cover_size())
        _PREVIEW.update(key=key, source=None if image.isNull() else QPixmap.fromImage(image), scaled={})
    return _PREVIEW["source"]


def paint_preview_image(painter: QPainter, area: QRectF, widget: QWidget):
    """Dibuja en `area` la imagen elegida para las vistas previas vacías, si hay. Solo
    dentro de la ventana principal: los diálogos de trabajo quedan como siempre."""
    path = bg.image_path(bg.PLACE_PREVIEWS)
    if path is None or area.isEmpty() or not _inside_glass_area(widget):
        return
    settings = bg.get_place(bg.PLACE_PREVIEWS)
    source = _preview_source(path, settings)
    if source is None:
        return
    dpr = widget.devicePixelRatioF()
    fit = settings["fit"]
    painter.save()
    painter.setOpacity(settings["opacity"] / 100.0)
    if fit == bg.FIT_TILE:
        piece = source
        if abs(dpr - 1.0) > 1e-3:
            piece = QPixmap(source)
            piece.setDevicePixelRatio(source.devicePixelRatioF() * dpr)
        painter.drawTiledPixmap(area.toRect(), piece)
    else:
        src_w = source.width() / source.devicePixelRatioF()
        src_h = source.height() / source.devicePixelRatioF()
        if fit == bg.FIT_ORIGINAL:
            src_w, src_h = src_w / dpr, src_h / dpr
        rect = target_rect(src_w, src_h, area.width(), area.height(), fit, settings["align"])
        rect.translate(area.topLeft())
        key = (round(rect.width() * dpr), round(rect.height() * dpr))
        pix = _PREVIEW["scaled"].get(key)
        if pix is None:
            if len(_PREVIEW["scaled"]) >= 4:  # una por cada tamaño de vista previa
                _PREVIEW["scaled"].clear()
            pix = source.scaled(key[0], key[1], Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            pix.setDevicePixelRatio(dpr)
            _PREVIEW["scaled"][key] = pix
        painter.drawPixmap(rect.topLeft(), pix)
    painter.restore()


def _on_preview_place_changed(place: str):
    if place == bg.PLACE_PREVIEWS:
        for widget in list(_PREVIEW_WATCHED):
            widget.update()
        for hint in list(_PREVIEW_HINTS):
            hint.setVisible(bg.image_path(bg.PLACE_PREVIEWS) is None)


def _connect_preview_notifier():
    if not _PREVIEW_CONNECTED[0]:
        background_notifier().changed.connect(_on_preview_place_changed)
        _PREVIEW_CONNECTED[0] = True


def watch_preview_image(widget: QWidget):
    """Repinta `widget` cuando cambian la imagen o los ajustes de las vistas previas."""
    _connect_preview_notifier()
    _PREVIEW_WATCHED.add(widget)


def hide_with_preview_image(hint: QWidget):
    """El texto de ayuda de una vista previa vacía se oculta mientras haya imagen: caería
    encima de ella. Llamar con `hint` ya dentro de su layout: mostrar un widget suelto
    abriría una ventana."""
    _connect_preview_notifier()
    _PREVIEW_HINTS.add(hint)
    hint.setVisible(bg.image_path(bg.PLACE_PREVIEWS) is None)


class _PreviewBackdropFilter(QObject):
    """Pinta la imagen debajo del contenido de un widget que solo se ve estando vacío. Un
    widget que además muestra otras cosas la apaga con la propiedad "previewBackdropOff"."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Paint and not obj.property("previewBackdropOff"):
            from core.utils.theme_loader import get_active_shapes
            area = QRectF(obj.rect()).adjusted(1, 1, -1, -1)  # sin tapar el borde del contenedor
            radius = get_active_shapes()["radio"]
            path = QPainterPath()
            path.addRoundedRect(area, radius, radius)
            p = QPainter(obj)
            p.setRenderHint(QPainter.Antialiasing)
            p.setClipPath(path)
            paint_preview_image(p, area, obj)
            p.end()
        return False


_PREVIEW_FILTER = None


def install_preview_backdrop(widget: QWidget):
    global _PREVIEW_FILTER
    if _PREVIEW_FILTER is None:
        _PREVIEW_FILTER = _PreviewBackdropFilter()
    widget.installEventFilter(_PREVIEW_FILTER)
    watch_preview_image(widget)


class BackgroundCanvas(QWidget):
    def __init__(self, place: str = bg.PLACE_GENERAL, parent=None):
        super().__init__(parent)
        self._place = place
        self._settings = bg.default_settings()
        self._source: QPixmap | None = None
        self._cache: tuple | None = None  # (clave, QPixmap ya escalado)
        self._frosted_source: QPixmap | None = None  # la imagen esmerilada (se calcula al pedirla)
        self._backdrop: tuple | None = None          # (clave, lienzo entero esmerilado)
        self._resizing = False
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(_RESIZE_SETTLE_MS)
        self._settle.timeout.connect(self._on_resize_settled)
        background_notifier().changed.connect(self._on_changed)
        QGuiApplication.instance().screenAdded.connect(self._on_screen_added)
        self.reload()

    # ── Datos ───────────────────────────────────────────────────────────────
    def has_image(self) -> bool:
        return self._source is not None and not self._source.isNull()

    def reload(self):
        self._settings = bg.get_place(self._place)
        self._cache = None
        self._backdrop = None
        self._frosted_source = None
        path = bg.image_path(self._place)
        self._path = path
        self._source = None
        if path:
            image = _load_image(path, self._settings["blur"])
            # "Tamaño original" y "Mosaico" muestran los píxeles tal cual: esos no se tocan.
            if (not image.isNull() and not self._settings["blur"]
                    and self._settings["fit"] in (bg.FIT_FILL, bg.FIT_FIT, bg.FIT_STRETCH)):
                image = _fit_source(image, _screen_cover_size())
            if image.isNull():
                logger.warning(f"Fondo: no se pudo cargar {path}")
            else:
                self._source = QPixmap.fromImage(image)
        self.update()

    def _on_screen_added(self, _screen):
        if self.has_image():  # puede ser más grande: la copia reducida ya no alcanzaría
            self.reload()

    def _on_changed(self, place: str):
        if place == self._place:
            self.reload()

    # ── Dibujo ──────────────────────────────────────────────────────────────
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.has_image():
            self._resizing = True
            self._settle.start()

    def _on_resize_settled(self):
        self._resizing = False
        self.update()

    def _scaled(self, rect: QRectF) -> QPixmap:
        """La imagen ya escalada a `rect` con buena calidad (en píxeles reales de la
        pantalla), guardada mientras no cambie nada."""
        dpr = self.devicePixelRatioF()
        key = (round(rect.width() * dpr), round(rect.height() * dpr), self._settings["fit"])
        if self._cache is None or self._cache[0] != key:
            pix = self._source.scaled(key[0], key[1], Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            pix.setDevicePixelRatio(dpr)
            self._cache = (key, pix)
        return self._cache[1]

    def paintEvent(self, event):
        if not self.has_image():
            return  # sin imagen: igual que siempre (la ventana ya pinta el fondo del tema)
        p = QPainter(self)
        self._paint_image(p, self._source, fast=self._resizing, cached=True)
        self._paint_frosted_header(p)
        p.end()

    def _paint_image(self, p: QPainter, source: QPixmap, fast: bool = False, cached: bool = False):
        """Fondo del tema + `source` con la opacidad, el ajuste y la posición elegidos,
        sobre todo el lienzo."""
        p.fillRect(self.rect(), QColor(get_theme_token("fondo_principal", "#0a0a0a")))
        p.setOpacity(self._settings["opacity"] / 100.0)
        dpr = self.devicePixelRatioF()
        src_w = source.width() / source.devicePixelRatioF()
        src_h = source.height() / source.devicePixelRatioF()
        fit = self._settings["fit"]

        if fit == bg.FIT_TILE:
            # Piezas a su tamaño real en la pantalla (como Tamaño original).
            piece = source
            if abs(dpr - 1.0) > 1e-3:
                piece = QPixmap(source)
                # La copia desenfocada ya trae su propio devicePixelRatio (ver _load_image).
                piece.setDevicePixelRatio(source.devicePixelRatioF() * dpr)
            p.drawTiledPixmap(self.rect(), piece)
        else:
            if fit == bg.FIT_ORIGINAL:
                src_w, src_h = src_w / dpr, src_h / dpr  # un píxel de la imagen = uno de la pantalla
            rect = target_rect(src_w, src_h, self.width(), self.height(), fit, self._settings["align"])
            if cached and fit == bg.FIT_ORIGINAL:
                p.drawPixmap(rect.topLeft(), self._scaled(rect) if abs(dpr - 1.0) > 1e-3 else source)
            elif cached and not fast:
                p.drawPixmap(rect.topLeft(), self._scaled(rect))
            else:
                if not fast:
                    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
                p.drawPixmap(rect, source, QRectF(source.rect()))
        p.setOpacity(1.0)

    # ── Vidrio recortado ────────────────────────────────────────────────────
    def _frosted_backdrop(self) -> QPixmap:
        """El lienzo entero con la imagen esmerilada, armado una vez por tamaño y ajustes."""
        if self._frosted_source is None:
            try:
                image = _load_image(self._path, True, _FROSTED_STRENGTH) if self._path else QImage()
            except OSError as e:  # se borró o reemplazó: esto corre al pintar y no debe romperlo
                logger.warning(f"Fondo: no se pudo leer {self._path}: {e}")
                image = QImage()
            self._frosted_source = QPixmap.fromImage(image) if not image.isNull() else self._source
        dpr = self.devicePixelRatioF()
        key = (self.width(), self.height(), dpr, tuple(sorted(self._settings.items())),
               get_theme_token("fondo_principal", "#0a0a0a"))
        if self._backdrop is None or self._backdrop[0] != key:
            pix = QPixmap(round(self.width() * dpr), round(self.height() * dpr))
            pix.setDevicePixelRatio(dpr)
            pix.fill(Qt.transparent)
            bp = QPainter(pix)
            self._paint_image(bp, self._frosted_source)
            bp.end()
            self._backdrop = (key, pix)
        return self._backdrop[1]

    def _draw_backdrop_region(self, painter: QPainter, target: QRectF, canvas_rect: QRectF):
        dpr = self.devicePixelRatioF()
        src = QRectF(canvas_rect.x() * dpr, canvas_rect.y() * dpr, canvas_rect.width() * dpr, canvas_rect.height() * dpr)
        painter.drawPixmap(target, self._frosted_backdrop(), src)

    def paint_backdrop(self, painter: QPainter, widget: QWidget):
        """Pinta en `widget` (con `painter` ya abierto sobre él) el pedazo del lienzo
        que tiene detrás, con la imagen esmerilada: así un panel que flota encima del
        contenido se ve transparente al fondo, pero no a la interfaz que tapa."""
        if not self.has_image():
            return
        origin = widget.mapTo(self, widget.rect().topLeft())
        self._draw_backdrop_region(painter, QRectF(widget.rect()),
                                   QRectF(origin.x(), origin.y(), widget.width(), widget.height()))

    def paint_backdrop_for_popup(self, painter: QPainter, popup: QWidget):
        """Como paint_backdrop, para una ventana aparte (menú, lista desplegable): su
        lugar en el lienzo sale de la posición en pantalla. Lo que queda fuera de la
        ventana principal toma la imagen esmerilada reflejada contra el borde: a los dos
        lados del borde hay los mismos colores, así que no se ve el corte."""
        if not self.has_image():
            return
        backdrop = self._frosted_backdrop()
        cw, ch = self.width(), self.height()
        if cw <= 0 or ch <= 0:
            return
        origin = self.mapFromGlobal(popup.mapToGlobal(popup.rect().topLeft()))
        x0, y0 = origin.x(), origin.y()
        w, h = popup.width(), popup.height()
        painter.save()
        painter.setClipRect(popup.rect(), Qt.IntersectClip)  # respeta el recorte de quien llama
        for iy in range(y0 // ch, (y0 + h - 1) // ch + 1):
            for ix in range(x0 // cw, (x0 + w - 1) // cw + 1):
                painter.save()
                painter.translate(ix * cw - x0, iy * ch - y0)
                if ix % 2:  # pieza reflejada en horizontal
                    painter.translate(cw, 0)
                    painter.scale(-1, 1)
                if iy % 2:  # pieza reflejada en vertical
                    painter.translate(0, ch)
                    painter.scale(1, -1)
                painter.drawPixmap(QRectF(0, 0, cw, ch), backdrop, QRectF(backdrop.rect()))
                painter.restore()
        painter.restore()

    # ── Barra superior esmerilada ───────────────────────────────────────────
    def set_frosted_header(self, bottom_fn):
        """La franja de arriba (barra de título y pestañas) va con la imagen esmerilada y
        un tinte, como los paneles flotantes: así se leen los nombres de las pestañas no
        seleccionadas sobre cualquier imagen. bottom_fn() -> alto de la franja."""
        self._header_bottom = bottom_fn
        self.update()

    def _paint_frosted_header(self, p: QPainter):
        bottom_fn = getattr(self, "_header_bottom", None)
        height = bottom_fn() if bottom_fn else 0
        if height <= 0:
            return
        rect = QRectF(0, 0, self.width(), height)
        self._draw_backdrop_region(p, rect, rect)
        from core.utils.background_images import glass_alpha
        alpha = glass_alpha()
        tint = QColor(get_theme_token("fondo_principal", "#0a0a0a"))
        tint.setAlphaF(1.0 if alpha is None else alpha)
        p.fillRect(rect, tint)
