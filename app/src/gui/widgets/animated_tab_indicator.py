# src/gui/widgets/animated_tab_indicator.py
from PySide6.QtWidgets import QFrame, QTabWidget, QToolButton
from PySide6.QtCore import QPropertyAnimation, QEasingCurve, QEvent, QTimer, QRect, QSize, Qt

from gui.styles import get_theme_token
from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon

# Nombres internos que Qt le da a los dos QToolButton que arma QTabBar cuando
# usesScrollButtons() está activo (confirmado en runtime, no documentado
# oficialmente pero estable hace muchas versiones de Qt) -- se usan para
# identificar cuál es cuál y pintarles un ícono propio en vez del nativo.
_SCROLL_BUTTON_ICONS = {
    "ScrollLeftButton": "arrow_back.svg",
    "ScrollRightButton": "play_arrow.svg",
}
_SCROLL_BUTTON_ICON_SIZE = 18
# Margen libre entre el botón derecho y el borde de la propia barra de pestañas --
# lo más chico posible sin volver a cortarse, para acercarlos al borde tanto como
# se pueda (ver _reposition_scroll_buttons).
_SCROLL_BUTTON_RIGHT_MARGIN = 1


class AnimatedTabIndicator(QFrame):
    """Barra de 3px que reemplaza el border-bottom estático de QTabBar::tab:selected
    por uno animado -- misma técnica que ModeSelector.bg_indicator
    (widgets/mode_selector.py), adaptada a un QTabBar real: en vez de animar entre
    geometrías de QPushButton propios, se anima entre tab_bar.tabRect(index).

    Requiere que la QSS del QTabWidget objetivo saque el border-bottom de
    QTabBar::tab:selected (si no, queda una línea estática duplicada debajo de la
    animada) -- ver objectName #animatedTabIndicator ya estilado en _base.qss."""

    _HEIGHT = 3

    def __init__(self, tab_widget: QTabWidget):
        super().__init__(tab_widget.tabBar())
        self.setObjectName("animatedTabIndicator")
        self._tab_widget = tab_widget
        self._bar = tab_widget.tabBar()
        self._anim = None
        self._scroll_buttons = []
        self._bar.installEventFilter(self)
        tab_widget.currentChanged.connect(self._on_current_changed)
        self._style_scroll_buttons()
        # La geometría real del tab bar recién existe después del primer layout.
        QTimer.singleShot(0, self._snap_to_current)

    def _style_scroll_buttons(self):
        """Reemplaza el ícono nativo (flecha dibujada por el estilo de Qt) de los
        botones de scroll del tab bar por íconos propios de DowP, pintados del
        verde de acento -- mismo mecanismo que get_colored_svg_icon usa en el resto
        de la app (ej. image_tools_view.py). Nota: el color se lee una sola vez acá
        (no sigue un cambio de tema en caliente) -- mismo criterio ya usado hoy en
        encoding_options_widget.py para su acento local."""
        color = get_theme_token('acento_primario', '#B9E640')
        icon_size = QSize(_SCROLL_BUTTON_ICON_SIZE, _SCROLL_BUTTON_ICON_SIZE)
        for btn in self._bar.findChildren(QToolButton):
            icon_name = _SCROLL_BUTTON_ICONS.get(btn.objectName())
            if icon_name:
                # Clave: sin sacar el arrowType, QCommonStyle dibuja la flecha nativa
                # (PE_IndicatorArrowLeft/Right) y se salta el ícono por completo, sin
                # importar que esté bien seteado -- por eso antes "funcionaba" en el
                # test (icon() no era null) pero no se veía nada distinto en pantalla.
                btn.setArrowType(Qt.NoArrow)
                btn.setIcon(get_colored_svg_icon(icon_name, color, size=_SCROLL_BUTTON_ICON_SIZE))
                btn.setIconSize(icon_size)
                if btn not in self._scroll_buttons:
                    # QTabBarPrivate reconfigura estos botones (tamaño, a veces
                    # arrowType) en su propio pase de layout/polish interno -- un
                    # eventFilter puesto directo en CADA botón, no solo en la barra,
                    # agarra esos resets apenas pasan (Polish/EnabledChange, que se
                    # dispara justo cuando el botón habilitado/deshabilitado cambia
                    # al scrollear a un extremo) en vez de depender solo de que
                    # _snap_to_current() vuelva a correr después.
                    btn.installEventFilter(self)
                    self._scroll_buttons.append(btn)

    def eventFilter(self, obj, event):
        if obj in self._scroll_buttons and event.type() in (QEvent.Polish, QEvent.EnabledChange):
            self._style_scroll_buttons()
            self._reposition_scroll_buttons()
        elif obj is self._bar and event.type() == QEvent.Resize:
            # Reflow de pestañas (resize de ventana, textos compactos, scroll) --
            # reposicionar sin animar, es un reajuste de layout, no un cambio real.
            # Diferido: dentro del propio resizeEvent, Qt todavía no recalculó los
            # tabRect() nuevos (el layout interno de QTabBar se resuelve después,
            # no en el mismo tick) -- snapear ahí mismo agarraba geometría vieja.
            QTimer.singleShot(0, self._snap_to_current)
        return super().eventFilter(obj, event)

    def _target_geometry(self, index) -> QRect:
        r = self._bar.tabRect(index)
        return QRect(r.left(), r.bottom() - self._HEIGHT + 1, r.width(), self._HEIGHT)

    def _reposition_scroll_buttons(self):
        """Ancla los botones al borde derecho de la barra en vez de confiar en dónde
        los deja QTabBarPrivate: internamente reserva su posición asumiendo el ancho
        chico original (~16px) -- al agrandarlos a 28px (ver _base.qss) el botón
        derecho terminaba sobresaliendo de la barra y se recortaba contra su propio
        borde (Qt clipea a sus hijos por su rect). Calculado siempre desde
        bar.width() (no desde la posición actual del botón), así que no hay deriva
        aunque se llame varias veces seguidas."""
        left_btn = right_btn = None
        for btn in self._scroll_buttons:
            if btn.objectName() == "ScrollLeftButton":
                left_btn = btn
            elif btn.objectName() == "ScrollRightButton":
                right_btn = btn
        if not left_btn or not right_btn:
            return
        right_x = self._bar.width() - _SCROLL_BUTTON_RIGHT_MARGIN - right_btn.width()
        right_btn.move(right_x, right_btn.y())
        left_btn.move(right_x - left_btn.width(), left_btn.y())

    def _snap_to_current(self):
        # Reafirmar el ícono/arrowType/posición acá también: QTabBarPrivate
        # reconstruye/reconfigura sus botones de scroll en su propio pase de layout
        # interno (después de la construcción, o en cada resize), pisando lo que
        # hayamos seteado antes -- este método ya corre en cada uno de esos momentos
        # (singleShot tras el show inicial, y tras cada resize), así que reaplicar
        # acá gana la carrera contra ese reset interno.
        self._style_scroll_buttons()
        self._reposition_scroll_buttons()
        idx = self._tab_widget.currentIndex()
        if idx < 0:
            self.hide()
            return
        self.setGeometry(self._target_geometry(idx))
        self.show()
        self.raise_()

    def _on_current_changed(self, index):
        if index < 0 or not self.isVisible():
            self._snap_to_current()
            return
        if self._anim:
            self._anim.stop()
        self._anim = QPropertyAnimation(self, b"geometry")
        self._anim.setDuration(220)
        self._anim.setStartValue(self.geometry())
        self._anim.setEndValue(self._target_geometry(index))
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._anim.start()
