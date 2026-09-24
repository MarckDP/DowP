# main.py
import sys
import os

# Add 'src' to path to import modules
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

# ═══ Escalado ANTES de QApplication (obligatorio) ═══
from core.utils.scaling import apply_ui_scaling, flush_scaling_logs
ui_scale_factor = apply_ui_scaling()

from core.logger.logger_manager import logger

# Enviar los logs de escalado al logger real 
flush_scaling_logs()


from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase, QIcon
from core.utils.i18n import load_language
from core.utils.config_manager import get_config
from core.version import APP_VERSION as __version__

# pillow_heif (soporte HEIC/HEIF) se registra bajo demanda la primera vez que se
# necesita, en core/tabs/image_tools/image_converter.py -- no hace falta cargarlo
# aquí al arrancar, ahorrando ~5-10 MB de RAM para quien no use herramientas de imagen.

from PySide6.QtCore import QObject, QEvent, Qt
from PySide6.QtWidgets import QPushButton, QCheckBox, QRadioButton, QComboBox, QTabBar, QStyledItemDelegate


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

    def _setup_combo(self, combo: QComboBox):
        if type(combo.itemDelegate()) is _DEFAULT_COMBO_DELEGATE_TYPE or type(combo.itemDelegate()) is QStyledItemDelegate:
            combo.setItemDelegate(CheckmarkComboDelegate(combo))
        if combo.view() and combo.view().window():
            container = combo.view().window()
            container.setAttribute(Qt.WA_TranslucentBackground, True)
            container.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
            container.installEventFilter(self._mask_filter)

    def eventFilter(self, obj, event):
        ev_type = event.type()
        if ev_type == QEvent.Type.ChildAdded:
            child = event.child()
            if isinstance(child, QComboBox):
                self._setup_combo(child)
            if isinstance(child, self._TARGET_TYPES):
                child.setCursor(Qt.PointingHandCursor)
        elif ev_type in (QEvent.Type.Show, QEvent.Type.Polish):
            if isinstance(obj, QComboBox):
                self._setup_combo(obj)
        return False

def main():
    # 0. Reanudar un swap de actualizacion que quedo a medias por un corte de
    # luz, ANTES de tocar Qt. Si hay uno, se le vuelve a entregar al helper y
    # se sale enseguida -- seguir arrancando con archivos a medio reemplazar
    # es exactamente lo que este chequeo existe para evitar. En una
    # instalacion sana (el caso de siempre) esto no hace nada.
    from core.updater.launcher import resume_pending_swap
    if resume_pending_swap():
        sys.exit(0)

    # 1. Setup App y base
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # Estilo base multiplataforma que previene bugs de QComboBox en Windows

    # Arrancar la captura de la consola en vivo desde el boot
    from core.logger.console_log_handler import get_console_log_handler
    get_console_log_handler()

    # Instalar cursor pointer en widgets interactivos (ChildAdded, no Enter — más eficiente)
    app.installEventFilter(HandCursorInstaller(app))
    
    # Calculate absolute base directory
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Load Fonts (Lazy: solo fuente activa requerida)
    from core.utils.font_manager import init_fonts
    init_fonts()
    
    app.setApplicationName("DowP")
    app.setApplicationVersion(__version__)
    
    # Cargar Ícono Global de la Aplicación
    icon_path = os.path.join(base_dir, "src", "assets", "icons", "app", "DowP_Logo.svg")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    else:
        logger.warning(f"No se encontró el ícono de la app en: {icon_path}")
    
    logger.info(f"Starting DowP {__version__} application")
    
    config = get_config()
    load_language(app, config.get("language", "en"))

    # ── Splash Screen con verificación de dependencias integrada ──
    # Se instancia e inicia lo antes posible para feedback visual inmediato
    from gui.splash_screen import SplashScreen
    
    splash = SplashScreen()
    window_holder = [None]  # Usar lista para evitar GC
    
    def on_splash_ready(main_window):
        """Recibe la MainWindow ya construida desde el splash."""
        window_holder[0] = main_window
        main_window.show()
        splash.cleanup()
        logger.info("Application main window shown")

        # Novedades de la version: se muestran UNA sola vez por version instalada
        # (no en cada arranque). __version__ es APP_VERSION -- ver core/version.py.
        if config.get("last_seen_version", "") != __version__:
            from core.utils.config_manager import save_config
            from gui.dialogs.whats_new_dialog import WhatsNewDialog
            WhatsNewDialog(__version__, main_window).exec()
            config["last_seen_version"] = __version__
            save_config(config)
    
    def on_splash_failed():
        logger.error("Dependency installation failed. Exiting.")
        splash.cleanup()
        splash.show_failure_dialog()
        # app.exit(1), NO sys.exit(1): esto corre dentro del bucle de eventos, y sys.exit
        # cerraba Python con hilos todavía vivos (el despachador de la cola, los servicios
        # de editores) -> "QThread: Destroyed while thread is still running" y abort (visto
        # en macOS). Con app.exit, app.exec() termina, aboutToQuit (on_app_exit) detiene
        # esos servicios y el sys.exit(app.exec()) del final sale con código 1.
        app.exit(1)
    
    splash.ready.connect(on_splash_ready)
    splash.failed.connect(on_splash_failed)
    splash.start()

    # ── Tareas de fondo mientras el Splash Screen ya es visible al usuario ──

    # Recuperación de backups huérfanos (.dbak) de una sesión anterior
    from core.utils.file_conflict_manager import recover_orphaned_backups
    recovered = recover_orphaned_backups()
    if recovered:
        logger.info(f"Se restauraron {len(recovered)} archivo(s) tras un cierre inesperado: {recovered}")

    # Mantener al día el panel de Adobe para quien lo tenga instalado. NO instala nada
    # por su cuenta: si no hay panel, no hace nada. Instalarlo es siempre una decisión
    # del usuario desde Ajustes > Integraciones.
    from core.setup.importer_setup import sync_if_installed
    try:
        sync_if_installed()
    except Exception as e:
        logger.debug(f"No se pudo sincronizar el DowP Importer: {e}")

    # Iniciar Master Manager de Editores (Adobe, DaVinci, Vegas)
    from core.services.editor_integration_manager import EditorIntegrationManager
    from core.utils.queue_manager import get_queue_manager
    editor_manager = EditorIntegrationManager()
    editor_manager.start_all_services()
    editor_manager.connect_to_queue(get_queue_manager())

    def on_app_exit():
        logger.info("Cerrando servicios en segundo plano...")
        try:
            from core.utils.queue_manager import get_queue_manager
            get_queue_manager().stop_worker()
        except Exception as e:
            logger.debug(f"Error deteniendo QueueManager en salida: {e}")
        try:
            editor_manager.stop_all_services()
        except BaseException as e:
            logger.debug(f"Error deteniendo Editor Manager en salida: {e}")

    app.aboutToQuit.connect(on_app_exit)

    logger.info("Application event loop started")
    sys.exit(app.exec())

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.critical(f"Unhandled exception: {e}", exc_info=True)
