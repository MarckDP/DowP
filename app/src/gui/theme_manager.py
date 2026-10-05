# src/gui/theme_manager.py
"""Aplica el tema activo a toda la aplicación.

- Resuelve el tema y el modo de la configuración ('theme' + 'theme_mode': light /
  dark / system) con core/utils/theme_loader.py.
- Aplica la hoja de estilos a la ventana principal (set_style_target). NO a nivel de
  QApplication: medido con la app completa (~3400 widgets), hacerlo así duplicaba el
  arranque y cada cambio de tema tardaba ~11 s en vez de ~2 s, sin ganar nada -- todos
  los widgets salvo dos cuelgan de la ventana principal (desplegables y menús incluidos).
- Define la QPalette a nivel de QApplication (cuesta ~10 ms): es lo que usan los
  elementos nativos de Qt a los que no llega la hoja de estilos (selector de archivos,
  menús contextuales, tooltips) y los pocos diálogos sin padre.
- Sigue al modo del sistema operativo cuando 'theme_mode' es 'system'.
- Emite `theme_changed(tokens)` tras cada cambio. Los widgets que pintan a mano o
  tienen estilos propios se conectan aquí para actualizarse en vivo (fase 2).
"""
from PySide6.QtCore import QObject, Signal, Qt, QRectF, QEventLoop, QCoreApplication
from PySide6.QtGui import QColor, QPalette, QGuiApplication, QPainter, QFont
from PySide6.QtWidgets import QApplication, QWidget

from core.logger.logger_manager import logger
from core.utils import theme_loader
from core.utils.config_manager import get_config, save_config


class _ThemeBusyOverlay(QWidget):
    """Aviso "Aplicando tema…" sobre la ventana mientras se recalculan los estilos.

    Ese trabajo bloquea el hilo de la interfaz unos segundos y no se puede llevar a
    otro hilo (Qt solo permite tocar widgets desde el principal). Por eso el aviso se
    pinta de forma síncrona ANTES de empezar: queda visible y quieto hasta el final,
    en lugar de que la ventana parezca colgada sin explicación."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self._title = QCoreApplication.translate("ThemeManager", "Aplicando tema…")
        self._subtitle = QCoreApplication.translate("ThemeManager", "Esto tarda unos segundos.")
        # Colores del tema que se está dejando: el aviso se pinta antes del cambio
        self._card = QColor(theme_loader.get_active_token("fondo_terciario", "#161616"))
        self._border = QColor(theme_loader.get_active_token("acento_primario", "#B9E640"))
        self._text = QColor(theme_loader.get_active_token("texto_principal", "#e0e0e0"))
        self._muted = QColor(theme_loader.get_active_token("texto_tenue", "#888888"))

    def show_now(self):
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self.repaint()
        # Que el sistema llegue a mostrarlo antes del bloqueo (sin atender clics)
        QCoreApplication.processEvents(QEventLoop.ExcludeUserInputEvents)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(0, 0, 0, 120))

        title_font = QFont(self.font()); title_font.setPixelSize(16); title_font.setBold(True)
        sub_font = QFont(self.font()); sub_font.setPixelSize(12); sub_font.setBold(False)
        p.setFont(title_font)
        text_w = p.fontMetrics().horizontalAdvance(self._title)
        p.setFont(sub_font)
        text_w = max(text_w, p.fontMetrics().horizontalAdvance(self._subtitle))
        w = max(text_w, 220) + 80
        card = QRectF((self.width() - w) / 2, (self.height() - 96) / 2, w, 96)
        p.setPen(self._border)
        p.setBrush(self._card)
        p.drawRoundedRect(card, 10, 10)

        p.setFont(title_font); p.setPen(self._text)
        p.drawText(card.adjusted(0, 18, 0, -46), Qt.AlignHCenter | Qt.AlignVCenter, self._title)
        p.setFont(sub_font); p.setPen(self._muted)
        p.drawText(card.adjusted(0, 50, 0, -16), Qt.AlignHCenter | Qt.AlignVCenter, self._subtitle)
        p.end()


class ThemeManager(QObject):
    theme_changed = Signal(dict)

    def __init__(self):
        super().__init__()
        self._applied_once = False
        self._style_target = None
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(self._on_system_scheme_changed)

    # ── Consultas ─────────────────────────────────────────────────────────
    @staticmethod
    def current_theme() -> str:
        return get_config().get("theme_id", theme_loader.DEFAULT_THEME)

    @staticmethod
    def current_mode_setting() -> str:
        return get_config().get("theme_mode", "dark")

    def current_mode(self) -> str:
        """Modo efectivo ('light' o 'dark'), resolviendo 'system'."""
        return theme_loader.effective_mode(self.current_mode_setting())

    # ── Cambios ───────────────────────────────────────────────────────────
    def set_style_target(self, widget):
        """Widget que recibe la hoja de estilos (la ventana principal)."""
        self._style_target = widget

    def set_theme(self, theme_id: str):
        config = get_config()
        if config.get("theme_id") != theme_id:
            config["theme_id"] = theme_id
            theme_loader.sync_legacy_theme_key(config)
            save_config(config)
        self.apply()

    def set_mode(self, mode: str):
        if mode not in theme_loader.MODES + (theme_loader.MODE_SYSTEM,):
            return
        config = get_config()
        if config.get("theme_mode") != mode:
            config["theme_mode"] = mode
            theme_loader.sync_legacy_theme_key(config)
            save_config(config)
        self.apply()

    def apply(self):
        """Resuelve el tema activo y lo aplica a toda la app. En los cambios hechos con
        la app ya abierta muestra un aviso mientras dura (ver _ThemeBusyOverlay)."""
        target = self._style_target
        if not self._applied_once or target is None or not target.isVisible():
            self._apply_now()
            return
        overlay = _ThemeBusyOverlay(target)
        overlay.show_now()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._apply_now()
        finally:
            QApplication.restoreOverrideCursor()
            overlay.hide()
            overlay.deleteLater()

    def _apply_now(self):
        from gui.styles import load_stylesheet

        theme_id = self.current_theme()
        mode = self.current_mode()
        tokens = theme_loader.resolve_theme(theme_id, mode)
        theme_loader.set_active_tokens(tokens)
        theme_loader.set_active_shapes(theme_loader.resolve_shapes(theme_id))

        app = QApplication.instance()
        if app is None:
            return
        app.setPalette(self._build_palette(tokens))
        qss = load_stylesheet(theme_id, tokens=tokens)
        if self._style_target is not None:
            self._style_target.setStyleSheet(qss)
        else:
            app.setStyleSheet(qss)  # sin ventana principal (herramientas aisladas, pruebas)
        logger.info(f"Temas: aplicado '{theme_id}' en modo {mode}"
                    f"{' (según el sistema)' if self.current_mode_setting() == theme_loader.MODE_SYSTEM else ''}")

        # El primer apply() es el del arranque: nada que actualizar todavía.
        if self._applied_once:
            from gui.styles import refresh_themed_styles
            n = refresh_themed_styles()
            logger.debug(f"Temas: {n} estilos de widgets recalculados en vivo")
            self.theme_changed.emit(tokens)
        self._applied_once = True

    def _on_system_scheme_changed(self, _scheme):
        if self.current_mode_setting() == theme_loader.MODE_SYSTEM:
            logger.info("Temas: el sistema cambió de modo claro/oscuro; se reaplica el tema")
            self.apply()

    # ── Paleta ────────────────────────────────────────────────────────────
    @staticmethod
    def _build_palette(t: dict) -> QPalette:
        def c(key, fallback):
            color = QColor(t.get(key, fallback))
            return color if color.isValid() else QColor(fallback)

        window = c("fondo_principal", "#0a0a0a")
        base = c("fondo_secundario", "#121212")
        alt = c("fondo_terciario", "#161616")
        text = c("texto_principal", "#e0e0e0")
        text_dim = c("texto_secundario", "#666666")
        disabled = c("texto_deshabilitado", "#555555")
        accent = c("acento_primario", "#B9E640")
        button = c("fondo_elemento", "#1a1a1a")

        p = QPalette()
        for group in (QPalette.Active, QPalette.Inactive):
            p.setColor(group, QPalette.Window, window)
            p.setColor(group, QPalette.WindowText, text)
            p.setColor(group, QPalette.Base, base)
            p.setColor(group, QPalette.AlternateBase, alt)
            p.setColor(group, QPalette.Text, text)
            p.setColor(group, QPalette.Button, button)
            p.setColor(group, QPalette.ButtonText, text)
            p.setColor(group, QPalette.BrightText, c("estado_error", "#ff6b5f"))
            p.setColor(group, QPalette.Highlight, accent)
            p.setColor(group, QPalette.HighlightedText, c("boton_texto", "#000000"))
            p.setColor(group, QPalette.ToolTipBase, alt)
            p.setColor(group, QPalette.ToolTipText, text)
            p.setColor(group, QPalette.PlaceholderText, text_dim)
            p.setColor(group, QPalette.Link, accent)
            p.setColor(group, QPalette.LinkVisited, c("acento_secundario", "#1DC038"))
            p.setColor(group, QPalette.Light, c("borde_sutil", "#333333"))
            p.setColor(group, QPalette.Midlight, c("borde_normal", "#222222"))
            p.setColor(group, QPalette.Mid, c("borde_normal", "#222222"))
            p.setColor(group, QPalette.Dark, window)
            p.setColor(group, QPalette.Shadow, QColor(0, 0, 0))
        p.setColor(QPalette.Disabled, QPalette.Window, window)
        p.setColor(QPalette.Disabled, QPalette.Base, base)
        p.setColor(QPalette.Disabled, QPalette.Button, button)
        for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText, QPalette.PlaceholderText):
            p.setColor(QPalette.Disabled, role, disabled)
        p.setColor(QPalette.Disabled, QPalette.Highlight, c("borde_sutil", "#333333"))
        p.setColor(QPalette.Disabled, QPalette.HighlightedText, disabled)
        return p


_instance = None


def get_theme_manager() -> ThemeManager:
    global _instance
    if _instance is None:
        _instance = ThemeManager()
    return _instance
