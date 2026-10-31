# src/gui/app_event_filters.py
"""Filtros de eventos instalados sobre QApplication, y cómo construir widgets sin pagarlos.

Un filtro sobre QApplication ve TODOS los eventos de TODOS los objetos de la app, y si
está escrito en Python cada uno cruza de C++ a Python. Construir la ventana principal
genera cientos de miles de eventos (ChildAdded, Polish, ParentChange...): con cinco
filtros así instalados se iba casi la mitad del arranque solo en eso. De ahí las dos
reglas de este módulo:

  - Un solo filtro para todos los "clic afuera cierra el popover" (OutsideClickHub), en
    vez de uno por pestaña/panel.
  - Mientras se construye un bloque grande de widgets (la ventana principal, una pestaña
    diferida), los filtros se quitan (build_without_app_filters) y al terminar se aplica
    de una pasada lo que HandCursorInstaller habría hecho widget por widget.
"""
import time
from contextlib import contextmanager

import shiboken6
from PySide6.QtCore import QObject, QEvent, Qt, QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QPushButton, QCheckBox, QRadioButton, QComboBox, QMenu,
    QTabBar, QStyledItemDelegate, QWidget
)

from core.utils.config_manager import get_config
from gui.styles import (
    glass_prepare_popup, paint_combo_scroll_frame, paint_combo_scroller_arrow, prepare_menu_window,
    set_combo_scroll_frame,
)
from gui.widgets.combo_box import CheckmarkComboDelegate


class _ComboPopupMaskFilter(QObject):
    """Mantiene la máscara del contenedor del popup (QComboBoxPrivateContainer) sincronizada
    con su tamaño en cada resize o show.

    Qt solo pinta el panel nativo opaco de menú (QStyle::PE_PanelMenu, reservado para los
    indicadores de scroll arriba/abajo) cuando `mask().isEmpty()` es verdadero.
    Asignarle cualquier máscara no vacía (su propio rect) hace que Qt se salte ese dibujado por completo."""

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            obj.setMask(obj.rect())
        return False


class _ComboScrollFrame(QObject):
    """Listas largas: Qt agrega franjas con flechas (QComboBoxPrivateScroller) afuera de la
    lista. Mientras haya alguna, lista y franjas se pintan como una sola pieza. Solo se
    cambia lo que se ve: desplazarse sigue siendo cosa de Qt. Si otra versión de Qt le
    cambia el nombre a esa clase, aquí no coincide nada y las franjas se ven como antes."""

    _SCROLLER_CLASS = "QComboBoxPrivateScroller"

    def _scrollers(self, container):
        return [w for w in container.findChildren(QWidget, options=Qt.FindDirectChildrenOnly)
                if w.metaObject().className() == self._SCROLLER_CLASS]

    def _sync(self, container):
        view = container.findChild(QAbstractItemView)
        if view is None:
            return
        set_combo_scroll_frame(view, any(not s.isHidden() for s in self._scrollers(container)))
        container.update()

    def eventFilter(self, obj, event):
        ev_type = event.type()
        if obj.metaObject().className() == self._SCROLLER_CLASS:
            if ev_type == QEvent.Type.Paint:
                paint_combo_scroller_arrow(obj, obj.y() > obj.parent().height() / 2)
                return True
            if ev_type in (QEvent.Type.Show, QEvent.Type.Hide):
                self._sync(obj.parent())
            elif ev_type in (QEvent.Type.Enter, QEvent.Type.Leave):
                obj.update()
            return False
        if ev_type == QEvent.Type.Paint:
            view = obj.findChild(QAbstractItemView)
            if view is not None and view.property("scrollFrame"):
                paint_combo_scroll_frame(obj)
        elif ev_type in (QEvent.Type.Show, QEvent.Type.Resize):
            for scroller in self._scrollers(obj):
                scroller.removeEventFilter(self)  # sin duplicar si se abre otra vez
                scroller.installEventFilter(self)
            self._sync(obj)
        return False


_DEFAULT_COMBO_DELEGATE_TYPE = None

class HandCursorInstaller(QObject):
    """Instala cursor pointer en widgets interactivos y garantiza CheckmarkComboDelegate
    y máscara de recorte sin bordes nativos en QComboBoxes para soporte de hover y selección visual vía QSS."""
    _TARGET_TYPES = (QPushButton, QCheckBox, QRadioButton, QComboBox, QTabBar)

    def __init__(self, parent=None):
        super().__init__(parent)
        global _DEFAULT_COMBO_DELEGATE_TYPE
        if _DEFAULT_COMBO_DELEGATE_TYPE is None:
            _DEFAULT_COMBO_DELEGATE_TYPE = type(QComboBox().itemDelegate())
        self._mask_filter = _ComboPopupMaskFilter(self)
        self._scroll_frame = _ComboScrollFrame(self)

    def _setup_combo(self, combo: QComboBox):
        if type(combo.itemDelegate()) is _DEFAULT_COMBO_DELEGATE_TYPE or type(combo.itemDelegate()) is QStyledItemDelegate:
            combo.setItemDelegate(CheckmarkComboDelegate(combo))
        if combo.view() and combo.view().window():
            container = combo.view().window()
            container.setAttribute(Qt.WA_TranslucentBackground, True)
            container.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
            container.installEventFilter(self._mask_filter)
            container.installEventFilter(self._scroll_frame)

    def setup_existing(self, root: QWidget):
        """Lo mismo que el filtro hace al ver nacer cada widget (ChildAdded), aplicado de
        una pasada a `root` y todo lo que cuelga de él -- para lo construido con el filtro
        quitado (ver build_without_app_filters). Ningún botón/check/radio/combo/pestaña de
        la app pone otro cursor a mano, así que fijarlo después equivale a fijarlo al nacer."""
        for widget in [root, *root.findChildren(QWidget)]:
            if isinstance(widget, QComboBox):
                self._setup_combo(widget)
            if isinstance(widget, self._TARGET_TYPES) and widget.parentWidget() is not None:
                widget.setCursor(Qt.PointingHandCursor)

    def eventFilter(self, obj, event):
        ev_type = event.type()
        if ev_type == QEvent.Type.Wheel:
            combo = None
            if isinstance(obj, QComboBox):
                combo = obj
            elif isinstance(obj, QWidget) and isinstance(obj.parent(), QComboBox):
                combo = obj.parent()

            if combo is not None:
                # Si el popup está desplegado, permitir que el usuario scrollee la lista
                if combo.view() and combo.view().isVisible():
                    return False

                # Si el usuario activó la opción en Ajustes > General, permitir comportamiento nativo de Qt
                if get_config().get("combobox_wheel_scroll", False):
                    return False

                # Menú cerrado y opción desactivada (por defecto): no cambiar la opción del combo
                # y propagar el evento de rueda hacia los contenedores padre (QScrollArea, etc.)
                p = combo.parentWidget()
                while p:
                    pos = combo.mapTo(p, event.position().toPoint())
                    ev = QWheelEvent(
                        QPointF(pos),
                        event.globalPosition(),
                        event.pixelDelta(),
                        event.angleDelta(),
                        event.buttons(),
                        event.modifiers(),
                        event.phase(),
                        event.inverted()
                    )
                    ev.ignore()
                    if QApplication.sendEvent(p, ev) and ev.isAccepted():
                        break
                    p = p.parentWidget()
                return True

        if ev_type == QEvent.Type.ChildAdded:
            child = event.child()
            if isinstance(child, QComboBox):
                self._setup_combo(child)
            if isinstance(child, self._TARGET_TYPES):
                child.setCursor(Qt.PointingHandCursor)
        elif ev_type in (QEvent.Type.Show, QEvent.Type.Polish):
            if isinstance(obj, QComboBox):
                self._setup_combo(obj)
            elif ev_type == QEvent.Type.Polish:
                if isinstance(obj, QMenu):
                    prepare_menu_window(obj)
            else:
                # Imagen de fondo: vidrio recortado en menús y listas desplegables.
                if isinstance(obj, QMenu):
                    glass_prepare_popup(obj)
                elif isinstance(obj, QWidget) and obj.isWindow() and isinstance(obj.parent(), QComboBox):
                    glass_prepare_popup(obj, obj.parent().view())
        return False


class OutsideClickHub(QObject):
    """Un único filtro global para todos los paneles que se cierran al hacer clic afuera
    (popover de Posprocesar en Modo Rápido, popovers del Editor de Imagen, cajón del
    Historial). Cada uno registra un handler(obj, event) que recibe SOLO los
    MouseButtonPress de toda la app -- lo mismo que antes veía con su propio filtro
    global, pero pagando el cruce a Python una vez por evento y no una por panel."""

    _instance = None

    @classmethod
    def instance(cls) -> "OutsideClickHub":
        if cls._instance is None:
            cls._instance = cls(QApplication.instance())
        return cls._instance

    @classmethod
    def register(cls, owner: QObject, handler) -> None:
        """`handler` deja de llamarse cuando `owner` se destruye."""
        hub = cls.instance()
        hub._handlers.append((owner, handler))
        owner.destroyed.connect(lambda *_: hub._unregister(owner))

    def __init__(self, parent=None):
        super().__init__(parent)
        self._handlers = []

    def _unregister(self, owner):
        self._handlers = [(o, h) for o, h in self._handlers if o is not owner]

    def eventFilter(self, obj, event):
        etype = event.type()
        if etype in _USER_INPUT_EVENTS:
            global _last_user_input
            _last_user_input = time.monotonic()
            if etype == QEvent.Type.MouseButtonPress:
                for _owner, handler in list(self._handlers):
                    handler(obj, event)
        return False


# Eventos que cuentan como "el usuario está usando la app" (ver seconds_since_user_input).
# Se anotan aquí porque este filtro ya recibe todos los eventos de la app de todos modos.
_USER_INPUT_EVENTS = frozenset((
    QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease, QEvent.Type.MouseMove,
    QEvent.Type.KeyPress, QEvent.Type.Wheel, QEvent.Type.HoverMove,
))
_last_user_input = time.monotonic()


def seconds_since_user_input() -> float:
    """Segundos desde el último clic, tecla, rueda o movimiento del mouse sobre la app.
    MainWindow lo usa para construir las pestañas diferidas solo mientras el usuario no
    está haciendo nada: cada construcción congela la interfaz un momento."""
    return time.monotonic() - _last_user_input


_hand_cursor: HandCursorInstaller | None = None
_installed_filters: list = []
_suspend_depth = 0


def install_app_filters(app: QApplication) -> None:
    """Instala los filtros globales de la app. main.py lo llama una vez, al arrancar."""
    global _hand_cursor
    _hand_cursor = HandCursorInstaller(app)
    _installed_filters[:] = [_hand_cursor, OutsideClickHub.instance()]
    for f in _installed_filters:
        app.installEventFilter(f)


@contextmanager
def app_filters_suspended():
    """Quita los filtros globales mientras dura el bloque y los vuelve a poner al salir.
    Admite anidarse (una pestaña diferida que se construye dentro de otra construcción):
    solo el bloque más externo los quita y los repone. Lo construido adentro NO recibe el
    cursor de mano ni el delegado de combos: para eso está build_without_app_filters."""
    global _suspend_depth
    app = QApplication.instance()
    if _suspend_depth == 0:
        for f in _installed_filters:
            app.removeEventFilter(f)
    _suspend_depth += 1
    try:
        yield
    finally:
        _suspend_depth -= 1
        if _suspend_depth == 0:
            for f in _installed_filters:
                app.installEventFilter(f)


def _cpp_ptr(widget) -> int:
    # Puntero C++ y no id(): PySide puede devolver un wrapper Python distinto para el
    # mismo widget en cada llamada a topLevelWidgets().
    return shiboken6.getCppPointer(widget)[0]


def build_without_app_filters(factory):
    """Llama a factory() (que construye y devuelve un widget) con los filtros globales
    quitados, y después le aplica a ese widget -- y a cualquier ventana suelta que se
    haya creado en el camino, como los popovers sin padre -- lo que HandCursorInstaller
    habría hecho al ver nacer cada hijo."""
    before = {_cpp_ptr(w) for w in QApplication.topLevelWidgets()}
    with app_filters_suspended():
        widget = factory()
    if _hand_cursor is not None:
        _hand_cursor.setup_existing(widget)
        for top in QApplication.topLevelWidgets():
            if _cpp_ptr(top) not in before and top is not widget:
                _hand_cursor.setup_existing(top)
    return widget
