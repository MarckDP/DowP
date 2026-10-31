# main.py
import sys
import os

# Add 'src' to path to import modules
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

# Primero que nada: el reloj de las marcas "Arranque: ..." del log empieza aquí.
from core.utils import startup_timer

# ═══ Escalado ANTES de QApplication (obligatorio) ═══
from core.utils.scaling import apply_ui_scaling, flush_scaling_logs
ui_scale_factor = apply_ui_scaling()

from core.logger.logger_manager import logger, install_exception_logging
# Errores no capturados (en eventos de Qt o hilos) también al log: el .exe no tiene consola.
install_exception_logging()

# Enviar los logs de escalado al logger real
flush_scaling_logs()

# macOS: certificados para el OpenSSL estático de ffmpeg (fragmentos por https). Antes de
# lanzar cualquier subproceso, para que todos lo hereden.
from core.utils.tls_certs import ensure_ssl_cert_file
ensure_ssl_cert_file()


from core.utils.i18n import load_language
from core.utils.config_manager import get_config
from core.version import APP_VERSION as __version__

# pillow_heif (soporte HEIC/HEIF) se registra bajo demanda la primera vez que se
# necesita, en core/tabs/image_tools/image_converter.py -- no hace falta cargarlo
# aquí al arrancar, ahorrando ~5-10 MB de RAM para quien no use herramientas de imagen.

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

startup_timer.mark("imports base listos")


def main():
    # 0. Reanudar un swap de actualizacion que quedo a medias por un corte de
    # luz, ANTES de tocar Qt. Si hay uno, se le vuelve a entregar al helper y
    # se sale enseguida -- seguir arrancando con archivos a medio reemplazar
    # es exactamente lo que este chequeo existe para evitar. En una
    # instalacion sana (el caso de siempre) esto no hace nada.
    from core.updater.launcher import resume_pending_swap
    if resume_pending_swap():
        sys.exit(0)

    # Marca de reinicio (ver core/utils/app_restart.py). Se quita de sys.argv para que
    # no llegue a Qt ni se arrastre a un reinicio posterior (que reenvía sys.argv[1:]).
    from core.utils.app_restart import RESTART_FLAG
    restarted = RESTART_FLAG in sys.argv
    if restarted:
        sys.argv = [a for a in sys.argv if a != RESTART_FLAG]

    # 1. Setup App y base
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # Estilo base multiplataforma que previene bugs de QComboBox en Windows
    startup_timer.mark("QApplication creada")

    # ── Candado de Instancia Única Multiplataforma (Windows / macOS / Linux) ──
    from PySide6.QtNetwork import QLocalSocket, QLocalServer

    SINGLE_INSTANCE_KEY = "com.dowp.app.single_instance"

    # Reinicio (cambio de idioma/tema): la instancia vieja sigue cerrándose y respondiendo
    # al candado unos segundos. En vez de rendirse ante ella, se espera a que suelte el
    # candado (ver core/utils/app_restart.py). Con límite: si no termina de cerrarse,
    # se cae al comportamiento normal (activar la existente y salir).
    if restarted:
        import time
        wait_start = time.monotonic()
        while time.monotonic() - wait_start < 20:
            probe = QLocalSocket()
            probe.connectToServer(SINGLE_INSTANCE_KEY)
            if not probe.waitForConnected(300):
                break
            probe.abort()
            time.sleep(0.3)
        logger.info(f"Reinicio: esperando a que se cierre la instancia anterior -- "
                    f"{time.monotonic() - wait_start:.1f}s")

    local_socket = QLocalSocket()
    local_socket.connectToServer(SINGLE_INSTANCE_KEY)
    if local_socket.waitForConnected(500):
        # Ya existe una instancia activa en este equipo (sea Windows, macOS o Linux)
        logger.info("Otra instancia de DowP ya está en ejecución. Activando la ventana existente...")
        local_socket.write(b"ACTIVATE\n")
        local_socket.flush()
        local_socket.disconnectFromServer()
        sys.exit(0)

    # Si no conectó, somos la primera instancia: limpiamos cualquier residuo huérfano y escuchamos
    QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
    instance_server = QLocalServer(app)
    if not instance_server.listen(SINGLE_INSTANCE_KEY):
        logger.warning(f"No se pudo iniciar el servidor de instancia única: {instance_server.errorString()}")
    else:
        def _on_new_instance_connection():
            client = instance_server.nextPendingConnection()
            if not client:
                return
            def _on_client_ready_read():
                try:
                    data = client.readAll().data().decode("utf-8", errors="ignore")
                    if "ACTIVATE" in data:
                        logger.info("Petición de activación recibida de otra instancia.")
                        main_win = window_holder[0]
                        if main_win:
                            if main_win.isMinimized():
                                main_win.showNormal()
                            main_win.show()
                            main_win.raise_()
                            main_win.activateWindow()
                except Exception as e:
                    logger.debug(f"Error procesando activación de instancia: {e}")
            client.readyRead.connect(_on_client_ready_read)
        instance_server.newConnection.connect(_on_new_instance_connection)

    # Arrancar la captura de la consola en vivo desde el boot
    from core.logger.console_log_handler import get_console_log_handler
    get_console_log_handler()

    # Filtros globales: cursor pointer en widgets interactivos (ChildAdded, no Enter — más
    # eficiente) y el filtro compartido de "clic afuera cierra el popover". La ventana
    # principal se construye con ellos quitados (ver gui/app_event_filters.py).
    from gui.app_event_filters import install_app_filters
    install_app_filters(app)
    
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
        startup_timer.mark("ventana principal visible")
        # Lo que queda tras el show() (primer pintado, layouts diferidos) se ve en la
        # marca siguiente, que llega cuando el bucle de eventos vuelve a estar libre.
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: startup_timer.finish("ventana principal pintada"))

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
    startup_timer.mark("splash visible")

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
    startup_timer.mark("servicios de editores iniciados")

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
        try:
            if instance_server and instance_server.isListening():
                instance_server.close()
            QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
        except Exception as e:
            logger.debug(f"Error cerrando servidor de instancia única: {e}")

    app.aboutToQuit.connect(on_app_exit)

    logger.info("Application event loop started")
    exit_code = app.exec()

    # Salida directa, sin la limpieza final del interprete. En el build congelado,
    # al finalizar Python PySide6 destruye los widgets que siguen vivos y Qt todavia
    # llama a los eventFilter de Python instalados sobre QApplication (HandCursorInstaller
    # y OutsideClickHub, ver gui/app_event_filters.py) con el interprete a medio
    # apagar: crash en cada cierre (0xC0000005 en Windows, SIGSEGV y el aviso de
    # "se cerro inesperadamente" en macOS). Para este punto on_app_exit (aboutToQuit)
    # ya detuvo los servicios; solo queda volcar logs y salidas.
    #
    # os._exit no espera a los hilos no-daemon como si hace la salida normal de
    # Python (p. ej. un guardado a disco a medias): se les da ese margen aqui, con
    # tope, para no cortar escrituras sin arriesgarse a colgar el cierre.
    import logging
    import threading
    import time
    deadline = time.monotonic() + 10
    for t in threading.enumerate():
        if t is threading.main_thread() or t.daemon:
            continue
        t.join(max(0.0, deadline - time.monotonic()))
    logging.shutdown()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    from core.utils.process_exit import hard_exit
    hard_exit(exit_code)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.critical(f"Unhandled exception: {e}", exc_info=True)
