import os
import sys
import socketio
import asyncio
from aiohttp import web
from PySide6.QtCore import QThread, Signal
from core.logger.logger_manager import logger
from core.version import APP_VERSION


def _launchable_path():
    """
    Lo que el panel debe abrir para lanzar esta misma instalación de DowP, o None
    si corremos desde fuente (ahí sys.executable es el python del venv).
    En Mac se devuelve el bundle .app, no el binario de dentro: `open` lanza el
    bundle con su entorno correcto, y es lo que el usuario reconoce en /Applications.
    """
    if not getattr(sys, "frozen", False):
        return None
    exe = sys.executable
    if sys.platform == "darwin":
        idx = exe.find(".app/Contents/MacOS")
        if idx == -1:
            return None
        return exe[:idx + len(".app")]
    return os.path.abspath(exe)


class AdobeSocketServer(QThread):
    # Signals to communicate with the PySide6 UI if needed
    client_connected = Signal(str)
    client_disconnected = Signal(str)
    active_target_changed = Signal(object)
    # Medios enviados DESDE el editor con el boton "Enviar a DowP": lista de dicts
    # {path, in, out, has_trim, name} + el identificador de la app que los mando.
    files_pushed = Signal(list, str)

    _instance = None

    def __init__(self, host='127.0.0.1', port=7788):
        super().__init__()
        self.host = host
        self.port = port
        self.loop = None
        self._runner = None
        
        # aiohttp async mode
        self.sio = socketio.AsyncServer(async_mode='aiohttp', cors_allowed_origins='*')
        self.app = web.Application()
        self.sio.attach(self.app)
        
        self.active_target_sid = None
        self.clients = {}  # sid -> appIdentifier
        
        self._setup_handlers()
        
        # Singleton-like behavior for easy access from outside
        AdobeSocketServer._instance = self

    @classmethod
    def get_instance(cls):
        return cls._instance

    def _setup_handlers(self):
        @self.sio.event
        async def connect(sid, environ):
            logger.info(f"[Socket.IO] Client connected: {sid}")
            self.clients[sid] = "unknown"
            self.client_connected.emit(sid)

        @self.sio.event
        async def disconnect(sid):
            logger.info(f"[Socket.IO] Client disconnected: {sid}")
            if self.active_target_sid == sid:
                self.active_target_sid = None
                await self.sio.emit('active_target_update', {'activeTarget': None})
                self.active_target_changed.emit(None)
            
            if sid in self.clients:
                del self.clients[sid]
            self.client_disconnected.emit(sid)

        @self.sio.event
        async def register(sid, data):
            app_id = data.get('appIdentifier', 'unknown')
            panel_version = data.get('extensionVersion') or 'desconocida'
            logger.info(f"[Socket.IO] Client {sid} registered as {app_id} (panel v{panel_version})")
            self.clients[sid] = app_id

            # Respond with current active target
            active_app = self.clients.get(self.active_target_sid) if self.active_target_sid else None
            await self.sio.emit('active_target_update', {'activeTarget': active_app}, to=sid)

            # ── Handshake de versión ──
            # El panel no consulta ningún servidor de actualizaciones: comparte número de
            # versión con la app, viaja dentro de su bundle y se instala desde ella. Por
            # eso esta respuesta es la única fuente de verdad para "tu panel quedó viejo",
            # y sustituye al chequeo contra GitHub que tenía el panel (muerto desde hacía
            # tiempo, y apuntando a un repositorio que ya no existe).
            # Un desfase aquí significa que quedó una instalación antigua del panel: se
            # arregla reinstalándolo desde Ajustes > Integraciones.
            if panel_version != APP_VERSION:
                logger.warning(
                    f"[Socket.IO] Desfase de versión con {app_id}: panel v{panel_version}, "
                    f"app v{APP_VERSION}. El panel debería reinstalarse desde Integraciones.")
            await self.sio.emit('dowp_version', {'appVersion': APP_VERSION}, to=sid)

            # Ruta lanzable de esta instalación: el panel la guarda y habilita "Iniciar"
            # sin que el usuario tenga que buscar el ejecutable a mano con el ⚙️.
            launch_path = _launchable_path()
            if launch_path:
                await self.sio.emit('dowp_path', {'path': launch_path}, to=sid)

        @self.sio.event
        async def get_active_target(sid):
            active_app = self.clients.get(self.active_target_sid) if self.active_target_sid else None
            await self.sio.emit('active_target_update', {'activeTarget': active_app}, to=sid)

        @self.sio.event
        async def set_active_target(sid, data):
            self.active_target_sid = sid
            active_app = self.clients.get(sid)
            logger.info(f"[Socket.IO] Active target set to: {active_app} ({sid})")
            
            # Broadcast to everyone
            await self.sio.emit('active_target_update', {'activeTarget': active_app})
            self.active_target_changed.emit(active_app)

        @self.sio.event
        async def clear_active_target(sid):
            if self.active_target_sid == sid:
                self.active_target_sid = None
                logger.info(f"[Socket.IO] Active target cleared by {sid}")
                await self.sio.emit('active_target_update', {'activeTarget': None})
                self.active_target_changed.emit(None)

        @self.sio.event
        async def adobe_push_files(sid, data):
            """El usuario pulso "Enviar a DowP" en el panel con algo seleccionado en la
            linea de tiempo o en el proyecto. El panel manda cada elemento con su recorte
            de origen (in/out en segundos) cuando lo tiene; DowP decide a que pestana va
            cada archivo segun su tipo (ver MainWindow._on_media_pushed_from_editor).

            Se acepta tanto el formato nuevo ({items: [...]}) como el viejo de DowP 1
            ({files: ["ruta", ...]}), para que un panel sin actualizar siga funcionando
            aunque sin informacion de corte."""
            app_id = self.clients.get(sid, 'unknown')
            items = []

            raw_items = (data or {}).get('items')
            if not isinstance(raw_items, list):
                raw_items = None

            if raw_items is None:
                # Formato antiguo: solo rutas, sin recorte.
                raw_items = [{'path': f} for f in ((data or {}).get('files') or []) if f]

            for raw in raw_items:
                if isinstance(raw, str):
                    raw = {'path': raw}
                if not isinstance(raw, dict):
                    continue
                path = raw.get('path')
                if not path:
                    continue
                item = {
                    'path': str(path),
                    'name': str(raw.get('name') or ''),
                    'has_trim': bool(raw.get('hasTrim') or raw.get('has_trim')),
                    'in': raw.get('in'),
                    'out': raw.get('out'),
                }
                try:
                    item['in'] = float(item['in']) if item['in'] is not None else None
                    item['out'] = float(item['out']) if item['out'] is not None else None
                except (TypeError, ValueError):
                    item['in'] = item['out'] = None
                    item['has_trim'] = False
                if item['in'] is None or item['out'] is None or item['out'] <= item['in']:
                    item['has_trim'] = False
                items.append(item)

            logger.info(f"[Socket.IO] {app_id} envio {len(items)} elemento(s) a DowP.")
            if items:
                self.files_pushed.emit(items, app_id)

        @self.sio.event
        async def log_message(sid, data):
            level = data.get('level', 'info').upper()
            msg = data.get('message', '')
            app_id = self.clients.get(sid, 'Adobe')
            formatted_msg = f"[{app_id.upper()}] {msg}"
            if level == 'ERROR':
                logger.error(formatted_msg)
            elif level == 'WARNING':
                logger.warning(formatted_msg)
            else:
                logger.info(formatted_msg)

    def force_active_target(self, app_identifier):
        """Forces the active target to the given app_identifier if it is currently connected. Pass None to disconnect."""
        if app_identifier is None:
            self.active_target_sid = None
            logger.info("[Socket.IO] Active target forced to: None")
            if self.loop and self.loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self.sio.emit('active_target_update', {'activeTarget': None}),
                    self.loop
                )
            self.active_target_changed.emit(None)
            return True
            
        target_sid = None
        for sid, app_id in self.clients.items():
            if app_id == app_identifier:
                target_sid = sid
                break
                
        if target_sid:
            self.active_target_sid = target_sid
            logger.info(f"[Socket.IO] Active target forced to: {app_identifier} ({target_sid})")
            
            if self.loop and self.loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self.sio.emit('active_target_update', {'activeTarget': app_identifier}),
                    self.loop
                )
            self.active_target_changed.emit(app_identifier)
            return True
        else:
            logger.warning(f"[Socket.IO] Cannot force target to {app_identifier}, not connected.")
            return False

    def send_file_to_adobe(self, file_package):
        """
        Sends a new file package to the active Adobe application.
        This method is called synchronously from the main thread.
        """
        if not self.active_target_sid:
            logger.warning("[Socket.IO] Attempted to send file, but no active target is linked.")
            return False
            
        if not self.loop or not self.loop.is_running():
            logger.error("[Socket.IO] Event loop is not running.")
            return False
            
        logger.info(f"[Socket.IO] Sending file to active target ({self.clients.get(self.active_target_sid)})")
        asyncio.run_coroutine_threadsafe(
            self.sio.emit('new_file', {'filePackage': file_package}, to=self.active_target_sid),
            self.loop
        )
        return True
        
    def send_batch_to_adobe(self, files, target_bin=None):
        """
        Sends a batch of files to the active Adobe application.
        This method is called synchronously from the main thread.
        """
        if not self.active_target_sid:
            logger.warning("[Socket.IO] Attempted to send batch, but no active target is linked.")
            return False
            
        if not self.loop or not self.loop.is_running():
            logger.error("[Socket.IO] Event loop is not running.")
            return False
            
        logger.info(f"[Socket.IO] Sending batch to active target ({self.clients.get(self.active_target_sid)})")
        
        asyncio.run_coroutine_threadsafe(
            self.sio.emit('import_files', {'files': files, 'targetBin': target_bin}, to=self.active_target_sid),
            self.loop
        )
        return True

    def send_subclips_to_adobe(self, payload):
        """
        Sends subclips (in/out points) payload to active Adobe application.
        """
        if not self.active_target_sid:
            logger.warning("[Socket.IO] Attempted to send subclips, but no active target is linked.")
            return False
            
        if not self.loop or not self.loop.is_running():
            logger.error("[Socket.IO] Event loop is not running.")
            return False
            
        logger.info(f"[Socket.IO] Sending subclips to active target ({self.clients.get(self.active_target_sid)})")
        asyncio.run_coroutine_threadsafe(
            self.sio.emit('import_subclips', payload, to=self.active_target_sid),
            self.loop
        )
        return True

    def run(self):
        """
        Runs the aiohttp server in this QThread.
        """
        logger.info(f"[Socket.IO] Starting aiohttp server on {self.host}:{self.port}...")
        
        # Create a new event loop for this thread
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        # Setup runner (non-blocking setup for graceful shutdown)
        self._runner = web.AppRunner(self.app, access_log=None)
        self.loop.run_until_complete(self._runner.setup())
        
        site = web.TCPSite(self._runner, self.host, self.port, reuse_address=True)
        try:
            self.loop.run_until_complete(site.start())
        except OSError as e:
            logger.warning(f"[Socket.IO] No se pudo vincular el servidor en {self.host}:{self.port} (puerto ocupado o en espera): {e}")
            return
        
        try:
            self.loop.run_forever()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[Socket.IO] Server error: {e}", exc_info=True)

    def stop(self):
        """
        Stops the QThread and the aiohttp server gracefully.
        """
        logger.info("[Socket.IO] Stopping server...")
        if self.loop and self.loop.is_running():
            # Schedule cleanup
            async def cleanup():
                if self._runner:
                    await self._runner.cleanup()
                self.loop.stop()
                
            asyncio.run_coroutine_threadsafe(cleanup(), self.loop)
        
        try:
            self.wait(2000) # Wait up to 2 seconds for thread to finish
        except BaseException:
            pass
            
        if self.isRunning():
            self.terminate()
            try:
                self.wait()
            except BaseException:
                pass
