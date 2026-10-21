# src/gui/widgets/lazy_tab_widget.py
"""QTabWidget con pestañas que se construyen después de mostrar la ventana.

Las pestañas pesadas (Herramientas Multimedia, Editor de Imagen, Gestor de Medios) eran
buena parte del arranque. Aquí cada una entra primero como un marcador vacío y se
construye la primera vez que hace falta: al seleccionarla, cuando alguien la pide por
código (MainWindow.tab_video y compañía son propiedades que la construyen), o en los
ratos libres justo después del arranque (ver MainWindow._build_next_deferred).

Para que el resto de la app no note la diferencia, indexOf/setCurrentWidget aceptan la
pestaña real (no solo el marcador) y widget/currentWidget devuelven la pestaña real si
ya existe: código como `main_win.tabs.setCurrentWidget(main_win.tab_image)` sigue
funcionando igual.
"""
from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from core.utils import startup_timer
from gui.app_event_filters import build_without_app_filters


class LazyTabWidget(QTabWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._factories = {}   # marcador -> (nombre para el log, factory) de lo no construido
        self._built = {}       # marcador -> pestaña real
        # Conectado antes que cualquier otro slot de currentChanged (MainWindow conecta
        # el suyo después): cuando esos corren, la pestaña ya existe.
        self.currentChanged.connect(self._on_current_changed)

    def add_lazy_tab(self, factory, label: str, name: str) -> QWidget:
        """Agrega una pestaña cuyo contenido es factory(marcador), construido más tarde.
        Devuelve el marcador, que es la clave para ensure_built().

        factory recibe el marcador por si la pestaña admite construirse ya con él como
        padre: una pestaña construida sin padre y metida después en la ventana obliga a
        Qt a re-aplicar la hoja de estilos a todo su árbol (~0,4 s en el Gestor de
        Medios). No a todas les conviene -- en Herramientas Multimedia el costo solo se
        mueve a la construcción --, por eso lo decide quien la agrega."""
        placeholder = QWidget()
        layout = QVBoxLayout(placeholder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._factories[placeholder] = (name, factory)
        self.addTab(placeholder, label)
        return placeholder

    def ensure_built(self, placeholder: QWidget) -> QWidget:
        real = self._built.get(placeholder)
        if real is not None:
            return real
        name, factory = self._factories.pop(placeholder)
        # Una página oculta mide 640x480 (Qt no dimensiona las que no se ven), y las
        # pestañas con panel lateral adaptativo (Multimedia, Imagen) se creían en una
        # ventana estrecha: pasaban el panel a superpuesto y al mostrarse lo volvían a
        # acoplar -- cada cambio, ~0,5 s con la interfaz congelada. Con el tamaño real
        # del contenedor de páginas eligen el modo correcto desde el principio.
        stack = placeholder.parentWidget()
        if stack is not None:
            placeholder.resize(stack.size())
        with startup_timer.measure(f"pestaña diferida construida: {name}"):
            real = build_without_app_filters(lambda: factory(placeholder))
        real.resize(placeholder.size())
        self._built[placeholder] = real
        placeholder.layout().addWidget(real)
        return real

    def built_tab(self, placeholder: QWidget) -> QWidget | None:
        """La pestaña real si ya se construyó, None si no -- para quien solo quiere
        avisarle algo si existe, sin forzar su construcción."""
        return self._built.get(placeholder)

    def pending_tabs(self) -> list:
        return list(self._factories)

    def _on_current_changed(self, index: int):
        page = super().widget(index)
        if page in self._factories:
            self.ensure_built(page)

    # ── Traducción pestaña real <-> marcador ──────────────────────────────────

    def _to_page(self, widget):
        for placeholder, real in self._built.items():
            if real is widget:
                return placeholder
        return widget

    def _to_real(self, page):
        return self._built.get(page, page) if page is not None else None

    def widget(self, index: int):
        return self._to_real(super().widget(index))

    def currentWidget(self):
        return self._to_real(super().currentWidget())

    def indexOf(self, widget) -> int:
        return super().indexOf(self._to_page(widget))

    def setCurrentWidget(self, widget):
        super().setCurrentWidget(self._to_page(widget))
