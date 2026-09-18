# src/gui/main_window.py
import sys
import os
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QTabWidget, 
                             QApplication, QHBoxLayout, QPushButton, QFrame, QLabel)
from PySide6.QtCore import Qt, QPoint, QSize
from PySide6.QtGui import QIcon
from core.logger.logger_manager import logger
from core.utils.paths import get_src_dir
from gui.styles import load_stylesheet
from gui.widgets.title_bar import CustomTitleBar
from gui.widgets.tab_drag_hover import TabBarDragHoverSwitcher
from gui.widgets.animated_tab_indicator import AnimatedTabIndicator
from core.utils.i18n import load_language
from core.utils.config_manager import get_config

# Import Tab Views
from gui.tabs.advanced_process.advanced_process_view import AdvancedProcessTab
from gui.tabs.quick_mode.quick_mode_view import QuickModeTab
from gui.tabs.image_tools.image_tools_view import ImageToolsTab
from gui.tabs.video_tools.video_tools_view import VideoToolsTab
from gui.tabs.editing_media.editing_media_view import EditingMediaTab
from gui.tabs.settings.settings_view import SettingsTab

from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QRadialGradient
from PySide6.QtCore import Qt, QPointF, QSize, QTimer

# ── Estructuras/constantes Win32 para el chrome nativo sin bordes (ver nativeEvent
# de MainWindow) -- definidas una sola vez a nivel de módulo, no en cada evento de
# mouse durante drag/resize. Windows-only a propósito: en Mac/Linux el snap de
# ventana ya se resuelve con QWindow.startSystemMove() (ver title_bar.py).
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long), ("top", ctypes.c_long),
            ("right", ctypes.c_long), ("bottom", ctypes.c_long),
        ]

    class _NCCALCSIZE_PARAMS(ctypes.Structure):
        _fields_ = [
            ("rgrc", _RECT * 3),
            ("lppos", ctypes.c_void_p),
        ]

    class _MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", _RECT),
            ("rcWork", _RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    _user32 = ctypes.windll.user32
    _user32.MonitorFromWindow.restype = ctypes.c_void_p
    _user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    _user32.GetMonitorInfoW.restype = wintypes.BOOL
    _user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MONITORINFO)]
    _user32.IsZoomed.restype = wintypes.BOOL
    _user32.IsZoomed.argtypes = [wintypes.HWND]

    _WM_NCCALCSIZE = 0x0083
    _WM_NCHITTEST = 0x0084
    _HTCLIENT = 1
    _HTCAPTION = 2
    _MONITOR_DEFAULTTONEAREST = 2


def make_led_icon(color_hex: str, size: int = 32, glow: bool = True) -> QIcon:
    """Genera un ícono de luz LED circular nítido con resplandor suave y reflejo especular."""
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)

    center = QPointF(size / 2.0, size / 2.0)
    base_color = QColor(color_hex)

    if glow:
        # Halo de resplandor difuso
        gradient = QRadialGradient(center, size / 2.0)
        c_glow = QColor(base_color)
        c_glow.setAlpha(95)
        c_transparent = QColor(base_color)
        c_transparent.setAlpha(0)
        gradient.setColorAt(0.0, c_glow)
        gradient.setColorAt(0.65, c_glow)
        gradient.setColorAt(1.0, c_transparent)
        painter.setBrush(gradient)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(center, size / 2.0 - 1, size / 2.0 - 1)

    # Núcleo sólido del LED
    core_radius = size * 0.28
    painter.setBrush(base_color)
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(center, core_radius, core_radius)

    # Reflejo especular (punto de luz 3D)
    specular_radius = core_radius * 0.35
    specular_offset = core_radius * 0.3
    spec_center = QPointF(center.x() - specular_offset, center.y() - specular_offset)
    spec_color = QColor(255, 255, 255, 170)
    painter.setBrush(spec_color)
    painter.drawEllipse(spec_center, specular_radius, specular_radius)

    painter.end()
    return QIcon(pix)


class HoverIconButton(QPushButton):
    """Botón totalmente transparente que agranda su ícono en hover sin recuadro de fondo."""
    def __init__(self, normal_size=(22, 22), hover_size=(26, 26), parent=None):
        super().__init__(parent)
        self.normal_icon_size = QSize(*normal_size)
        self.hover_icon_size = QSize(*hover_size)
        self.setIconSize(self.normal_icon_size)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("""
            QPushButton {
                background: transparent !important;
                background-color: transparent !important;
                border: none !important;
                padding: 0px !important;
                outline: none !important;
            }
            QPushButton:hover {
                background: transparent !important;
                background-color: transparent !important;
                border: none !important;
            }
            QPushButton:pressed {
                background: transparent !important;
                background-color: transparent !important;
                border: none !important;
            }
        """)

    def enterEvent(self, event):
        self.setIconSize(self.hover_icon_size)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setIconSize(self.normal_icon_size)
        super().leaveEvent(event)


from PySide6.QtCore import Qt, QPointF, QSize, QTimer, QRectF, QVariantAnimation, QEasingCurve

class EditorAppWidget(QWidget):
    """Widget de editor NLE con icono nítido, animación de respiración al iniciar y línea verde cuando está conectado."""
    def __init__(self, app_id, svg_name, app_name, exe_path, icons_dir, parent_corner, parent=None):
        super().__init__(parent)
        self.app_id = app_id
        self.svg_name = svg_name
        self.app_name = app_name
        self.exe_path = exe_path
        self.icons_dir = icons_dir
        self.parent_corner = parent_corner
        self.icon_path = os.path.join(icons_dir, svg_name)

        self.setFixedSize(30, 38)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("background: transparent !important; border: none !important;")

        self._state = 1  # 1=Cerrado, 2=Abierto, 3=Conectado
        self._is_active = False
        self._is_running = False
        self._is_hovered = False
        self._is_launching = False
        self._pulse_opacity = 0.35

        # Animación de respiración suave (pulso de opacidad)
        self._pulse_anim = QVariantAnimation(self)
        self._pulse_anim.setStartValue(0.30)
        self._pulse_anim.setKeyValueAt(0.5, 1.0)
        self._pulse_anim.setEndValue(0.30)
        self._pulse_anim.setDuration(1200)
        self._pulse_anim.setEasingCurve(QEasingCurve.InOutSine)
        self._pulse_anim.setLoopCount(-1)
        self._pulse_anim.valueChanged.connect(self._on_pulse_value)

        self._update_tooltip()

    def _on_pulse_value(self, val):
        self._pulse_opacity = float(val)
        self.update()

    def start_launching_animation(self):
        """Inicia el efecto de respiración al lanzar la app."""
        self._is_launching = True
        self._pulse_anim.start()
        self._update_tooltip()
        # Timeout de seguridad de 60s
        QTimer.singleShot(60000, self.stop_launching_animation)

    def stop_launching_animation(self):
        """Detiene el efecto de respiración una vez abierta o por timeout."""
        if self._is_launching:
            self._is_launching = False
            self._pulse_anim.stop()
            self._update_tooltip()
            self.update()

    def set_app_status(self, is_active: bool, is_running: bool):
        if is_running or is_active:
            self.stop_launching_animation()
        self._is_active = is_active
        self._is_running = is_running
        if is_active:
            self._state = 3
        elif is_running:
            self._state = 2
        else:
            if not self._is_launching:
                self._state = 1
        self._update_tooltip()
        self.update()

    def _update_tooltip(self):
        if self._is_launching:
            self.setToolTip(self.tr("{0} (Iniciando...)").format(self.app_name))
        elif self._state == 3:
            self.setToolTip(self.tr("{0} (Conectado y Vinculado)").format(self.app_name))
        elif self._state == 2:
            self.setToolTip(self.tr("{0} (Abierto - Sin vincular)").format(self.app_name))
        else:
            self.setToolTip(self.tr("{0} (Cerrado - Clic para abrir)").format(self.app_name))

    def enterEvent(self, event):
        self._is_hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._is_hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.parent_corner._show_app_icon_context_menu(self, event.globalPosition().toPoint())
        else:
            self.parent_corner.on_app_icon_clicked(self)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        # 1. Opacidad según estado
        if self._is_launching:
            opacity = self._pulse_opacity
        elif self._state == 3:
            opacity = 1.0
        elif self._state == 2:
            opacity = 1.0 if self._is_hovered else 0.85
        else:
            opacity = 0.65 if self._is_hovered else 0.35
        painter.setOpacity(opacity)

        # 2. Dibujar Icono SVG (tamaño amplio y nítido)
        icon_size = 30 if self._is_hovered else 27
        if os.path.exists(self.icon_path):
            pix = QPixmap(self.icon_path).scaled(icon_size, icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            x = (self.width() - icon_size) / 2.0
            y = (self.height() - 5 - icon_size) / 2.0
            painter.drawPixmap(int(x), int(y), pix)

        # 3. Línea indicadora verde brillante en la parte inferior si está conectado
        if self._is_active:
            painter.setOpacity(1.0)
            painter.setBrush(QColor("#00e676"))
            painter.setPen(Qt.NoPen)
            line_w = 20
            line_h = 2.5
            line_x = (self.width() - line_w) / 2.0
            line_y = self.height() - line_h - 1
            painter.drawRoundedRect(QRectF(line_x, line_y, line_w, line_h), 1.25, 1.25)

        painter.end()


class EditorStatusCornerWidget(QWidget):
    """Widget de la esquina superior derecha para el control global de NLEs y acceso a Ajustes."""
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        
        self.icons_dir = os.path.join(get_src_dir(), "assets", "icons", "svg")

        # Layout principal de la esquina
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(6, 0, 10, 0)
        self.layout.setSpacing(16)  # Separación generosa entre el bloque de editores y Ajustes
        self.layout.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
        
        # Subcontenedor para el grupo de Editores (Luz indicadora + Íconos de programas juntos y compactos)
        self.editors_container = QWidget()
        self.editors_layout = QHBoxLayout(self.editors_container)
        self.editors_layout.setContentsMargins(0, 0, 0, 0)
        self.editors_layout.setSpacing(1)  # Íconos muy juntos
        self.editors_layout.setAlignment(Qt.AlignVCenter | Qt.AlignRight)

        # 1. Luz LED / Indicador compacto
        self.btn_toggle = HoverIconButton(normal_size=(14, 14), hover_size=(16, 16))
        self.btn_toggle.setCheckable(True)
        self.btn_toggle.setChecked(True)
        self.btn_toggle.setFixedSize(QSize(20, 20))
        self.btn_toggle.setToolTip(self.tr("Auto-enviar"))

        # 2. Botón de Ajustes (más grande, separado a la derecha)
        self.btn_settings = HoverIconButton(normal_size=(25, 25), hover_size=(29, 29))
        self.btn_settings.setFixedSize(QSize(38, 38))
        self.btn_settings.setIcon(QIcon(os.path.join(self.icons_dir, "settings.svg")))
        self.btn_settings.setToolTip(self.tr("Ajustes"))

        # Punto rojo de "hay una actualización" -- hijo del propio botón para no
        # necesitar reposicionarlo si el layout cambia; oculto hasta que
        # set_update_badge_visible(True) diga lo contrario (ver
        # SettingsTab.update_status_changed, conectado desde MainWindow).
        self.update_badge = QLabel(self.btn_settings)
        self.update_badge.setFixedSize(10, 10)
        self.update_badge.setStyleSheet("""
            background-color: #e74c3c;
            border-radius: 5px;
            border: 1.5px solid #1a1a1a;
        """)
        self.update_badge.move(26, 0)
        self.update_badge.hide()

        # Íconos LED cacheados
        self._led_green = make_led_icon("#00e676", size=32, glow=True)   # Verde: conectado
        self._led_yellow = make_led_icon("#f1c40f", size=32, glow=True)  # Amarillo: abierto sin vincular
        self._led_gray = make_led_icon("#707070", size=32, glow=False)   # Gris: ningún editor abierto
        self._led_red = make_led_icon("#ff4d4d", size=32, glow=True)     # Rojo: pausado

        self.btn_toggle.toggled.connect(self.on_toggle)
        self.btn_settings.clicked.connect(self.on_settings_clicked)

        # Añadir Luz al subcontenedor de editores
        self.editors_layout.addWidget(self.btn_toggle)

        # Añadir subcontenedor de editores y botón de Ajustes al layout principal
        self.layout.addWidget(self.editors_container)
        self.layout.addWidget(self.btn_settings)

        self.app_icons = {}
        self._build_app_icons()

        self._active_editor = None
        self._process_status = {}
        self.update_ui_state()

    def _build_app_icons(self):
        """Crea (o recrea) los íconos de apps habilitadas en Integraciones."""
        config = get_config()
        integrations = config.get('integrations', {})

        apps = [
            ("premiere", "premiere pro.svg", "Adobe Premiere Pro"),
            ("aftereffects", "after effects.svg", "Adobe After Effects"),
            ("photoshop", "photoshop.svg", "Adobe Photoshop"),
            ("davinci", "davinci resolve.svg", "DaVinci Resolve")
        ]

        for app_id, svg_name, app_name in apps:
            is_enabled = integrations.get(f"{app_id}_enabled", False)
            exe_path = integrations.get(f"{app_id}_path", "")
            existing_widget = self.app_icons.get(app_id)

            if is_enabled and existing_widget is None:
                widget = EditorAppWidget(
                    app_id=app_id,
                    svg_name=svg_name,
                    app_name=app_name,
                    exe_path=exe_path,
                    icons_dir=self.icons_dir,
                    parent_corner=self
                )
                self.editors_layout.addWidget(widget)
                self.app_icons[app_id] = widget
            elif is_enabled and existing_widget is not None:
                existing_widget.exe_path = exe_path
            elif not is_enabled and existing_widget is not None:
                self.editors_layout.removeWidget(existing_widget)
                existing_widget.deleteLater()
                del self.app_icons[app_id]

        # Visibilidad condicional: ocultar todo el contenedor de editores si no hay programas
        has_apps = len(self.app_icons) > 0
        self.editors_container.setVisible(has_apps)

    def refresh_app_icons(self):
        """Se llama cuando el usuario activa/desactiva una integración en Ajustes."""
        self._build_app_icons()
        self.update_ui_state()

    def late_init(self):
        """Llamado después de que EditorIntegrationManager se inicializa en main.py"""
        from core.services.editor_integration_manager import EditorIntegrationManager
        self.editor_manager = EditorIntegrationManager.get_instance()
        if self.editor_manager:
            self.editor_manager.active_editor_changed.connect(self.on_editor_changed)
            self.editor_manager.process_status_changed.connect(self.on_process_changed)
            
            self._active_editor = self.editor_manager.active_editor
            self._process_status = self.editor_manager.process_status
            self.btn_toggle.setChecked(self.editor_manager.is_auto_send_enabled)
        self.update_ui_state()

    def on_editor_changed(self, editor_name):
        self._active_editor = editor_name
        self.update_ui_state()

    def on_process_changed(self, status_dict):
        self._process_status = status_dict
        self.update_ui_state()

    def on_toggle(self, checked):
        if hasattr(self, 'editor_manager') and self.editor_manager:
            self.editor_manager.is_auto_send_enabled = checked
        self.update_ui_state()

    def update_ui_state(self):
        # 1. Visibilidad condicional del grupo de editores
        has_apps = len(self.app_icons) > 0
        self.editors_container.setVisible(has_apps)

        # 2. Actualizar estado de la luz LED
        is_on = self.btn_toggle.isChecked()
        if not is_on:
            self.btn_toggle.setIcon(self._led_red)
            self.btn_toggle.setToolTip(self.tr("Auto-enviar: DESACTIVADO / PAUSADO (Clic para activar)"))
        else:
            if self._active_editor:
                self.btn_toggle.setIcon(self._led_green)
                self.btn_toggle.setToolTip(self.tr("Auto-enviar a {0}: ACTIVO Y CONECTADO").format(self._active_editor))
            elif any(self._process_status.values()):
                self.btn_toggle.setIcon(self._led_yellow)
                self.btn_toggle.setToolTip(self.tr("Auto-enviar: Editor detectado (sin vincular)"))
            else:
                self.btn_toggle.setIcon(self._led_gray)
                self.btn_toggle.setToolTip(self.tr("Auto-enviar: Ningún editor abierto (En espera)"))

        # 3. Actualizar estado de los widgets de apps
        for app_id, widget in self.app_icons.items():
            is_running = self._process_status.get(app_id, False)
            is_active = (self._active_editor == app_id)
            widget.set_app_status(is_active=is_active, is_running=is_running)

    def _show_app_icon_context_menu(self, widget, global_pos):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        act_configure = menu.addAction(self.tr("Configurar integración"))
        act_configure.triggered.connect(lambda: self._open_integration_settings())
        menu.exec(global_pos)

    def _open_integration_settings(self):
        self.main_window.settings_overlay.open_page(6)

    def on_app_icon_clicked(self, widget):
        import subprocess
        import os

        state = widget._state
        app_id = widget.app_id
        exe_path = widget.exe_path

        if state == 1:
            if exe_path and os.path.exists(exe_path):
                widget.start_launching_animation()
                from core.logger.logger_manager import logger
                from PySide6.QtCore import QProcess
                import platform
                logger.info(f"Lanzando editor (modo desvinculado): {exe_path}")
                try:
                    if platform.system() == "Darwin":
                        # En macOS, un .app es un bundle directorio que se arranca con 'open'
                        subprocess.Popen(["open", exe_path])
                    else:
                        success = QProcess.startDetached(exe_path)
                        if not success:
                            if hasattr(os, 'startfile'):
                                os.startfile(exe_path)
                            else:
                                subprocess.Popen(exe_path, creationflags=getattr(subprocess, 'DETACHED_PROCESS', 0))
                except Exception as e:
                    logger.error(f"Error lanzando {app_id}: {e}")
                    widget.stop_launching_animation()
            else:
                from gui.dialogs.dialogs import show_warning
                show_warning(self.main_window, self.tr("Ruta no encontrada"), self.tr("No se encontró el ejecutable en:\n{0}\nConfigura la ruta en Ajustes -> Integraciones.").format(exe_path))
        elif state == 2:
            if hasattr(self, 'editor_manager') and self.editor_manager:
                success = self.editor_manager.force_adobe_target(app_id)
                if not success:
                    from gui.dialogs.dialogs import show_info
                    show_info(self.main_window, "DowP Importer", self.tr("La extensión no está respondiendo. Abre el panel de DowP en tu editor para conectar."))
        elif state == 3:
            if hasattr(self, 'editor_manager') and self.editor_manager:
                self.editor_manager.force_adobe_target(None)

    def on_settings_clicked(self):
        self.main_window.settings_overlay.open_page(0)

    def set_update_badge_visible(self, visible: bool):
        self.update_badge.setVisible(visible)


class SettingsModalOverlay(QWidget):
    """Capa modal superpuesta con fondo oscurecido para los Ajustes."""
    def __init__(self, main_window, settings_tab, parent=None):
        super().__init__(parent or main_window)
        self.main_window = main_window
        self.settings_tab = settings_tab
        
        self.setObjectName("settingsModalOverlay")
        self.setAttribute(Qt.WA_StyledBackground, True)

        # Layout del overlay (centrado)
        overlay_layout = QVBoxLayout(self)
        overlay_layout.setContentsMargins(24, 16, 24, 16)
        overlay_layout.setAlignment(Qt.AlignCenter)

        # Tarjeta modal central (compacta y elegante)
        self.card = QFrame()
        self.card.setObjectName("settingsModalCard")
        self.card.setMinimumSize(740, 480)
        self.card.setMaximumSize(980, 660)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        # Barra de cabecera con botón de cerrar "X"
        header = QWidget()
        header.setObjectName("settingsModalHeader")
        header.setFixedHeight(38)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 2, 10, 2)
        
        title_lbl = QLabel(self.tr("Ajustes"))
        title_lbl.setObjectName("settingsModalTitle")
        header_layout.addWidget(title_lbl)
        header_layout.addStretch()

        close_icon_path = os.path.join(get_src_dir(), "assets", "icons", "svg", "close.svg")
        self.btn_close = QPushButton()
        self.btn_close.setObjectName("modalCloseBtn")
        self.btn_close.setIcon(QIcon(close_icon_path))
        self.btn_close.setIconSize(QSize(14, 14))
        self.btn_close.setFixedSize(26, 26)
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.setToolTip(self.tr("Cerrar (Esc)"))
        self.btn_close.clicked.connect(self.close_overlay)
        header_layout.addWidget(self.btn_close)

        card_layout.addWidget(header)
        card_layout.addWidget(self.settings_tab, 1)

        overlay_layout.addWidget(self.card)
        self.hide()

    def open_page(self, page_index: int = 0):
        # Seleccionar subpestaña correspondiente
        buttons = [
            self.settings_tab.btn_general,
            self.settings_tab.btn_memory_cache,
            self.settings_tab.btn_downloads,
            self.settings_tab.btn_cookies,
            self.settings_tab.btn_deps,
            self.settings_tab.btn_labels,
            self.settings_tab.btn_integrations,
            self.settings_tab.btn_system,
            self.settings_tab.btn_models,
            self.settings_tab.btn_console
        ]
        if 0 <= page_index < len(buttons):
            buttons[page_index].click()

        if self.parent():
            self.setGeometry(0, 0, self.parent().width(), self.parent().height())
        self.raise_()
        self.show()
        self.setFocus()

    def close_overlay(self):
        self.hide()

    def mousePressEvent(self, event):
        # Clic en el backdrop oscuro exterior cierra el modal
        if not self.card.geometry().contains(event.pos()):
            self.close_overlay()
        else:
            super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close_overlay()
        else:
            super().keyPressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        logger.debug("MainWindow: Inicializando sistema de pestañas")

        # Puente para el diálogo modal de conflicto de archivo (modo SOLO): debe
        # crearse aquí, en el hilo principal, antes de que pueda arrancar cualquier
        # descarga que lo necesite (ver gui/dialogs/conflict_bridge.py).
        from gui.dialogs.conflict_bridge import ConflictDialogBridge
        self._conflict_bridge = ConflictDialogBridge()

        # ── Barra de título personalizada ─────────────────────────────────────
        if sys.platform == "win32":
            # Sin Qt.FramelessWindowHint a propósito, solo en Windows: se necesita el
            # frame nativo real (WS_CAPTION | WS_THICKFRAME, lo que Qt crea por
            # defecto sin este flag) para que Windows ofrezca snap de bordes, Aero
            # Shake y sombra DWM -- sin esos estilos nativos, Windows nunca ofrece
            # snap sin importar cómo se mueva la ventana (confirmado: QTBUG-84466).
            # El aspecto sin bordes se logra interceptando WM_NCCALCSIZE en
            # nativeEvent() más abajo, no quitando el frame a nivel de Qt.
            pass
        else:
            # Mac/Linux: aquí el frame sí se saca a nivel de Qt (como siempre) --
            # WM_NCCALCSIZE es Windows-only, así que sin este flag quedaría el título
            # nativo del sistema apilado encima del CustomTitleBar propio. El snap de
            # bordes en estas plataformas ya se resuelve en title_bar.py con
            # QWindow.startSystemMove(), que no depende de tener el frame nativo.
            self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, False)

        # Cargar tema inicial
        config = get_config()
        initial_theme = config.get("theme", "dark")

        version = QApplication.instance().applicationVersion()
        self.setWindowTitle(f"DowP {version}")
        self.setMinimumSize(800, 600)
        self.resize(1100, 750)
        self.setStyleSheet(load_stylesheet(initial_theme))

        # ── Layout principal ──────────────────────────────────────────────────
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.main_layout = QVBoxLayout(central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # Barra de título arriba del todo
        self.title_bar = CustomTitleBar(self, title=self.windowTitle())
        self.main_layout.addWidget(self.title_bar)

        # ── Pestañas ──────────────────────────────────────────────────────────
        self.tabs = QTabWidget()
        self.tabs.setObjectName("mainTabs")

        # 1. Modo Rápido
        self.tab_quick = QuickModeTab()
        self.tabs.addTab(self.tab_quick, self.tr("Modo Rápido"))

        # 2. Proceso Avanzado
        self.tab_single = AdvancedProcessTab()
        self.tabs.addTab(self.tab_single, self.tr("Proceso Avanzado"))

        # 3. Editor de Imagen
        self.tab_image = ImageToolsTab()
        self.tabs.addTab(self.tab_image, self.tr("Editor de Imagen"))

        # 4. Herramientas Multimedia
        self.tab_video = VideoToolsTab()
        self.tabs.addTab(self.tab_video, self.tr("Herramientas Multimedia"))

        # 5. Gestor de Medios
        self.tab_editing = EditingMediaTab()
        self.tabs.addTab(self.tab_editing, self.tr("Gestor de Medios"))

        # Permite que arrastrar archivos desde Gestor de Medios y sostenerlos sobre la
        # cabecera de Editor de Imagen / Herramientas Multimedia cambie de pestaña solo,
        # ya que un QTabWidget solo muestra una pestaña a la vez (ver tab_drag_hover.py).
        self._tab_drag_hover = TabBarDragHoverSwitcher(
            self.tabs,
            hoverable_indices={self.tabs.indexOf(self.tab_image), self.tabs.indexOf(self.tab_video)},
        )

        # Corner Widget (Editor Status & Ajustes)
        self.editor_status_widget = EditorStatusCornerWidget(self)
        self.tabs.setCornerWidget(self.editor_status_widget, Qt.TopRightCorner)

        self.main_layout.addWidget(self.tabs)

        self._main_tabs_indicator = AnimatedTabIndicator(self.tabs)

        # ── Modal Overlay de Ajustes ──────────────────────────────────────────
        self.tab_settings = SettingsTab()
        self.settings_overlay = SettingsModalOverlay(self, self.tab_settings, parent=central_widget)

        # ── Conexiones ────────────────────────────────────────────────────────
        self.tab_settings.theme_changed.connect(self.update_theme)
        self.tab_settings.font_changed.connect(self.update_font)
        self.tab_settings.integrations_changed.connect(self.editor_status_widget.refresh_app_icons)
        self.tab_settings.labels_changed.connect(self.refresh_labels)
        self.tab_settings.update_status_changed.connect(self.editor_status_widget.set_update_badge_visible)
        self.tabs.currentChanged.connect(self.on_tab_changed)

        # Chequeo de actualizaciones: diferido al siguiente ciclo del event loop
        # (no bloquea, y evita competir con el resto de la construccion de la
        # ventana). No-op en modo fuente -- ver SettingsTab.start_update_check().
        QTimer.singleShot(0, self.tab_settings.start_update_check)

        logger.info("MainWindow: Sistema de pestañas inicializado")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'settings_overlay') and self.settings_overlay:
            self.settings_overlay.setGeometry(0, 0, self.centralWidget().width(), self.centralWidget().height())

    def on_tab_changed(self, index):
        """Se ejecuta al cambiar de pestaña."""
        if hasattr(self, "tab_editing") and self.tab_editing and hasattr(self.tab_editing, "pause_playback"):
            self.tab_editing.pause_playback()

        if self.tabs.widget(index) == self.tab_single:
            logger.info("MainWindow: Recargando etiquetas en Proceso Avanzado")
            self.tab_single.video_details.load_labels()

        if self.tabs.widget(index) == self.tab_quick and hasattr(self.tab_quick, "load_labels"):
            logger.info("MainWindow: Recargando etiquetas en Modo Rápido")
            self.tab_quick.load_labels()

        if self.tabs.widget(index) == self.tab_video and hasattr(self.tab_video, "load_labels"):
            logger.info("MainWindow: Recargando etiquetas en Herramientas Multimedia")
            self.tab_video.load_labels()

        from core.utils.clipboard_monitor import ClipboardURLMonitor
        ClipboardURLMonitor.instance().check_clipboard(force=True)

    def showEvent(self, event):
        super().showEvent(event)
        from core.utils.clipboard_monitor import ClipboardURLMonitor
        ClipboardURLMonitor.instance().check_clipboard(force=True)
        # Conectar el corner widget al EditorManager (que ya fue inicializado en main.py)
        if hasattr(self, 'editor_status_widget') and not getattr(self, '_editor_status_initialized', False):
            self.editor_status_widget.late_init()
            self._editor_status_initialized = True
        # Recepcion de medios desde el editor (boton "Enviar a DowP" del panel). Se
        # conecta aca por lo mismo que el corner widget: EditorIntegrationManager se
        # crea en main.py despues de construir la ventana.
        if not getattr(self, '_editor_push_connected', False):
            from core.services.editor_integration_manager import EditorIntegrationManager
            editor_mgr = EditorIntegrationManager.get_instance()
            if editor_mgr:
                editor_mgr.media_pushed_from_editor.connect(self._on_media_pushed_from_editor)
                self._editor_push_connected = True

    def _on_media_pushed_from_editor(self, items: list, app_id: str):
        """Reparte lo que el usuario mando desde Premiere/After Effects: audio y video a
        Herramientas Multimedia (con su recorte, si el clip venia cortado en la linea de
        tiempo) e imagenes al Editor de Imagen. Se salta a la pestana que mas elementos
        recibio y se trae la ventana al frente, porque el gesto arranco en OTRA app."""
        from gui.tabs.video_tools.media_queue_widget import SUPPORTED_EXTENSIONS as MEDIA_EXTS
        from gui.tabs.image_tools.image_queue_widget import SUPPORTED_EXTENSIONS as IMAGE_EXTS

        media_items, image_items, unsupported = [], [], []
        for item in items or []:
            ext = os.path.splitext(item.get("path", ""))[1].lower()
            if ext in MEDIA_EXTS:
                media_items.append(item)
            elif ext in IMAGE_EXTS:
                image_items.append(item)
            else:
                unsupported.append(item.get("path", ""))

        added_media = self.tab_video.receive_media_from_editor(media_items) if media_items else 0
        added_images = self.tab_image.receive_media_from_editor(image_items) if image_items else 0

        if unsupported:
            logger.warning(
                f"MainWindow: {len(unsupported)} elemento(s) de {app_id} no son medios "
                f"compatibles y se ignoraron: {unsupported}"
            )
        logger.info(
            f"MainWindow: Recibidos de {app_id} -> {added_media} a Herramientas Multimedia, "
            f"{added_images} al Editor de Imagen."
        )

        if added_media or added_images:
            target = self.tab_video if added_media >= added_images else self.tab_image
            self.tabs.setCurrentWidget(target)
            self.show()
            self.raise_()
            self.activateWindow()

    def update_theme(self, theme_name):
        logger.info(f"MainWindow: Cambiando tema a {theme_name}")
        self.setStyleSheet(load_stylesheet(theme_name))

    def update_font(self, font_name):
        logger.info(f"MainWindow: Cambiando tipografía activa a {font_name}")
        config = get_config()
        theme_name = config.get("theme", "dark")
        self.setStyleSheet(load_stylesheet(theme_name))

    def refresh_labels(self):
        """Fuerza la recarga de las etiquetas en todas las pestañas relevantes."""
        logger.info("MainWindow: Recargando etiquetas globalmente por cambio en Ajustes")
        if hasattr(self, "tab_single") and self.tab_single and hasattr(self.tab_single, "video_details"):
            self.tab_single.video_details.load_labels()
        if hasattr(self, "tab_quick") and self.tab_quick and hasattr(self.tab_quick, "load_labels"):
            self.tab_quick.load_labels()
        if hasattr(self, "tab_video") and self.tab_video and hasattr(self.tab_video, "load_labels"):
            self.tab_video.load_labels()

    def _handle_nccalcsize(self, msg):
        """WM_NCCALCSIZE: el área de cliente pasa a ocupar toda la ventana (si no,
        Windows reserva espacio para el título/bordes nativos que no dibujamos).
        Estando maximizada hay que recortar al área de trabajo del monitor (rcWork,
        sin la taskbar) -- si no se hace esto, la ventana maximizada queda ~7-8px más
        grande que el monitor y tapa la taskbar o invade el monitor vecino (bug
        clásico de este patrón)."""
        if msg.wParam == 0:
            # FALSE: lParam apunta directo a un RECT, no a NCCALCSIZE_PARAMS -- no
            # hace falta tocar nada, el cliente ya queda igual a lo propuesto.
            return True, 0
        params = _NCCALCSIZE_PARAMS.from_address(msg.lParam)
        # IsZoomed(hWnd) en vez de self.isMaximized(): este mensaje nativo llega
        # DURANTE la transición maximizada<->normal, y el estado que Qt cree tener
        # (isMaximized()) puede no estar actualizado todavía en ese instante --
        # usarlo aquí hacía que, al restaurar, siguiéramos recortando al área del
        # monitor (pensado solo para maximizada) sobre el tamaño ya restaurado,
        # rompiendo visualmente toda la UI hasta minimizar/restaurar de nuevo.
        # IsZoomed() consulta el estado nativo real en el momento exacto del mensaje.
        if _user32.IsZoomed(msg.hWnd):
            hmonitor = _user32.MonitorFromWindow(msg.hWnd, _MONITOR_DEFAULTTONEAREST)
            if hmonitor:
                mi = _MONITORINFO()
                mi.cbSize = ctypes.sizeof(_MONITORINFO)
                if _user32.GetMonitorInfoW(hmonitor, ctypes.byref(mi)):
                    params.rgrc[0] = mi.rcWork
        return True, 0

    def nativeEvent(self, eventType, message):
        """Maneja eventos nativos de Windows para: 1) dibujar la ventana sin bordes
        pese a tener el frame nativo real (WM_NCCALCSIZE, ver _handle_nccalcsize) y
        2) redimensionar desde los bordes + que la barra de título custom se
        comporte como una caption nativa de verdad -- arrastre, snap de bordes,
        doble-clic para maximizar y Aero Shake los maneja Windows solo
        (WM_NCHITTEST devolviendo HTCAPTION), sin código Python adicional."""
        if sys.platform == "win32":
            try:
                msg = wintypes.MSG.from_address(int(message))

                if msg.message == _WM_NCCALCSIZE:
                    return self._handle_nccalcsize(msg)

                if msg.message == _WM_NCHITTEST:
                    # Usa QCursor.pos() porque Qt ya se encarga de normalizar las
                    # coordenadas a nivel lógico para todos los monitores
                    # independientemente de su DPI.
                    from PySide6.QtGui import QCursor
                    local_pos = self.mapFromGlobal(QCursor.pos())
                    x, y = local_pos.x(), local_pos.y()
                    is_maximized = bool(_user32.IsZoomed(msg.hWnd))

                    if not is_maximized:
                        w, h = self.width(), self.height()
                        border = 6  # Grosor del borde para redimensionar
                        left = x < border
                        right = x >= w - border
                        top = y < border
                        bottom = y >= h - border
                        if left and top: return True, 13  # HTTOPLEFT
                        if right and top: return True, 14  # HTTOPRIGHT
                        if left and bottom: return True, 16  # HTBOTTOMLEFT
                        if right and bottom: return True, 17  # HTBOTTOMRIGHT
                        if left: return True, 10  # HTLEFT
                        if right: return True, 11  # HTRIGHT
                        if top: return True, 12  # HTTOP
                        if bottom: return True, 15  # HTBOTTOM

                    # Franja de la barra de título custom: se devuelve como caption
                    # nativa salvo sobre los botones minimizar/maximizar/cerrar, que
                    # deben seguir recibiendo clics normales de Qt. childAt() ya
                    # recorre title_bar recursivamente y respeta
                    # WA_TransparentForMouseEvents del title_label.
                    if y < self.title_bar.height():
                        child = self.childAt(x, y)
                        if isinstance(child, QPushButton):
                            return True, _HTCLIENT
                        return True, _HTCAPTION
            except Exception as e:
                logger.debug(f"MainWindow.nativeEvent error: {e}")

        return super().nativeEvent(eventType, message)


if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
