from flask import Flask, jsonify, request
from flask_socketio import SocketIO
import threading
import webbrowser
from tkinter import messagebox
import tkinter
import customtkinter as ctk
from customtkinter import filedialog
from PIL import Image
import requests
from io import BytesIO
import queue
import gc
import os
import re
import sys
from pathlib import Path
import subprocess
import json
import time
import shutil
import platform
import yt_dlp
import io
from packaging import version

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    TKDND_AVAILABLE = True
    
    # ✅ CORRECCIÓN: Heredar de CTk y usar el Wrapper de DnD
    # Esto asegura que la ventana tenga los atributos de escalado de CTk
    class TkBase(ctk.CTk, TkinterDnD.DnDWrapper):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.TkdndVersion = TkinterDnD._require(self)
    
except ImportError:
    TKDND_AVAILABLE = False
    print("ADVERTENCIA: tkinterdnd2 no instalado. Drag & Drop deshabilitado.")
    
    # Fallback a CTk normal
    TkBase = ctk.CTk

from datetime import datetime, timedelta
from src.core.downloader import get_video_info, download_media
from src.core.processor import FFmpegProcessor, CODEC_PROFILES
from src.core.exceptions import UserCancelledError, LocalRecodeFailedError
from src.core.processor import clean_and_convert_vtt_to_srt
from contextlib import redirect_stdout
from .batch_download_tab import BatchDownloadTab
from .single_download_tab import SingleDownloadTab
from .image_tools_tab import ImageToolsTab

from .dialogs import ConflictDialog, LoadingWindow, CompromiseDialog, SimpleMessageDialog, SavePresetDialog, PlaylistErrorDialog
from src.core.constants import (
    VIDEO_EXTENSIONS, AUDIO_EXTENSIONS, SINGLE_STREAM_AUDIO_CONTAINERS,
    FORMAT_MUXER_MAP, LANG_CODE_MAP, LANGUAGE_ORDER, DEFAULT_PRIORITY,
    EDITOR_FRIENDLY_CRITERIA, COMPATIBILITY_RULES
)

def resource_path(relative_path):
    """ Obtiene la ruta absoluta al recurso, funciona para desarrollo y para PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

from main import PROJECT_ROOT, BIN_DIR

flask_app = Flask(__name__)
socketio = SocketIO(flask_app, async_mode='gevent', cors_allowed_origins='*')
main_app_instance = None

LATEST_FILE_PATH = None
LATEST_FILE_LOCK = threading.Lock()
ACTIVE_TARGET_SID = None  
CLIENTS = {}
AUTO_LINK_DONE = False

@socketio.on('connect')
def handle_connect():
    """Se ejecuta cuando un panel de extensión se conecta."""
    print(f"INFO: Nuevo cliente conectado con SID: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    """Se ejecuta cuando un panel de extensión se desconecta."""
    global ACTIVE_TARGET_SID
    if request.sid in CLIENTS:
        print(f"INFO: Cliente '{CLIENTS[request.sid]}' (SID: {request.sid}) se ha desconectado.")
        if request.sid == ACTIVE_TARGET_SID:
            ACTIVE_TARGET_SID = None
            print("INFO: El objetivo activo se ha desconectado. Ningún objetivo está enlazado.")
            socketio.emit('active_target_update', {'activeTarget': None})
        del CLIENTS[request.sid]

@socketio.on('register')
def handle_register(data):
    """
    Cuando un cliente se registra, comprobamos si es el que lanzó la app
    para enlazarlo automáticamente.
    
    CORREGIDO: Ahora valida si el cliente ya está registrado para evitar duplicados.
    """
    global ACTIVE_TARGET_SID, AUTO_LINK_DONE
    app_id = data.get('appIdentifier')
    
    if app_id:
        # ✅ NUEVA VALIDACIÓN: Solo registra si es la primera vez
        if request.sid not in CLIENTS:
            CLIENTS[request.sid] = app_id
            print(f"INFO: Cliente SID {request.sid} registrado como '{app_id}'.")
            
            # Solo intenta auto-enlace si es la primera vez
            if main_app_instance and not AUTO_LINK_DONE and app_id == main_app_instance.launch_target:
                ACTIVE_TARGET_SID = request.sid
                AUTO_LINK_DONE = True 
                print(f"INFO: Auto-enlace exitoso con '{app_id}' (SID: {request.sid}).")
                socketio.emit('active_target_update', {'activeTarget': CLIENTS[ACTIVE_TARGET_SID]})
            else:
                active_app = CLIENTS.get(ACTIVE_TARGET_SID)
                socketio.emit('active_target_update', {'activeTarget': active_app}, to=request.sid)
        else:
            # ✅ OPCIONAL: Si ya estaba registrado, solo envía el estado actual
            # Sin imprimir nada (evita spam en logs)
            active_app = CLIENTS.get(ACTIVE_TARGET_SID)
            socketio.emit('active_target_update', {'activeTarget': active_app}, to=request.sid)

@socketio.on('get_active_target')
def handle_get_active_target():
    """
    Un cliente pregunta quién es el objetivo activo.
    (Usado para la actualización periódica del estado en el panel).
    """
    active_app = CLIENTS.get(ACTIVE_TARGET_SID)
    socketio.emit('active_target_update', {'activeTarget': active_app}, to=request.sid)

@socketio.on('set_active_target')
def handle_set_active_target(data):
    """Un cliente solicita ser el nuevo objetivo activo."""
    global ACTIVE_TARGET_SID
    target_app_id = data.get('targetApp')
    sid_to_set = None
    for sid, app_id in CLIENTS.items():
        if app_id == target_app_id:
            sid_to_set = sid
            break
    if sid_to_set:
        ACTIVE_TARGET_SID = sid_to_set
        print(f"INFO: Nuevo objetivo activo establecido: '{CLIENTS[ACTIVE_TARGET_SID]}' (SID: {ACTIVE_TARGET_SID})")
        socketio.emit('active_target_update', {'activeTarget': CLIENTS[ACTIVE_TARGET_SID]})

@socketio.on('clear_active_target')
def handle_clear_active_target():
    """Un cliente solicita desvincularse sin desconectarse."""
    global ACTIVE_TARGET_SID

    if request.sid == ACTIVE_TARGET_SID:
        print(f"INFO: El objetivo activo '{CLIENTS.get(request.sid, 'desconocido')}' (SID: {request.sid}) se ha desvinculado.")

        ACTIVE_TARGET_SID = None

        socketio.emit('active_target_update', {'activeTarget': None})

# ==========================================
# ✅ NUEVO: Escuchar archivos desde Adobe
# ==========================================
@socketio.on('adobe_push_files')
def handle_adobe_push_files(data):
    """Recibe una lista de archivos desde Premiere/AE y los procesa."""
    files = data.get('files', [])
    if files and main_app_instance:
        print(f"INFO: Recibidos {len(files)} archivos desde Adobe.")
        # Usamos .after para ejecutar la lógica en el hilo principal de la UI
        main_app_instance.after(0, main_app_instance.handle_adobe_files, files)

def run_flask_app():
    """Función que corre el servidor. Usa gevent para WebSockets."""
    print("INFO: Iniciando servidor de integración en el puerto 7788 con WebSockets.")
    socketio.run(flask_app, host='0.0.0.0', port=7788, log_output=False)

if getattr(sys, 'frozen', False):
    APP_BASE_PATH = os.path.dirname(sys.executable)
else:
    APP_BASE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

class LoadingWindow(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Iniciando...")
        self.geometry("350x120")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", lambda: None) 
        self.transient(master) 
        self.lift()
        self.error_state = False
        win_width = 350
        win_height = 120
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        pos_x = (screen_width // 2) - (win_width // 2)
        pos_y = (screen_height // 2) - (win_height // 2)
        self.geometry(f"{win_width}x{win_height}+{pos_x}+{pos_y}")
        self.label = ctk.CTkLabel(self, text="Preparando la aplicación, por favor espera...", wraplength=320)
        self.label.pack(pady=(20, 10), padx=20)
        self.progress_bar = ctk.CTkProgressBar(self)
        self.progress_bar.set(0)
        self.progress_bar.pack(pady=10, padx=20, fill="x")
        self.grab_set() 

    def update_progress(self, text, value):
        if not self.winfo_exists():
            return
        self.label.configure(text=text)
        if value >= 0:
            self.progress_bar.set(value)
        else: 
            self.error_state = True 
            self.progress_bar.configure(progress_color="red")
            self.progress_bar.set(1)

class MainWindow(TkBase):
        
    def _get_best_available_info(self, url, options):
        """
        Ejecuta una simulación usando la API de yt-dlp para obtener información
        sobre el mejor formato disponible cuando la selección del usuario falla.
        """
        try:
            mode = options.get("mode", "Video+Audio")
            
            ydl_opts = {
                'no_warnings': True,
                'noplaylist': True,
                'quiet': True,
                'ffmpeg_location': self.ffmpeg_processor.ffmpeg_path
            }
            
            # Determinar el selector según el modo
            if mode == "Solo Audio":
                ydl_opts['format'] = 'ba/best'
            else:
                # Intentar con audio si está disponible, sino solo video
                ydl_opts['format'] = 'bv+ba/bv/best'

            # Configurar cookies
            cookie_mode = options.get("cookie_mode")
            if cookie_mode == "Archivo Manual..." and options.get("cookie_path"):
                ydl_opts['cookiefile'] = options["cookie_path"]
            elif cookie_mode != "No usar":
                browser_arg = options.get("selected_browser", "chrome")
                if options.get("browser_profile"):
                    browser_arg += f":{options['browser_profile']}"
                ydl_opts['cookiesfrombrowser'] = (browser_arg,)

            # Extraer información
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

            if not info:
                return "No se pudo obtener información del video."

            # Construir mensaje detallado según el modo
            if mode == "Solo Audio":
                abr = info.get('abr') or info.get('tbr', 0)
                acodec = info.get('acodec', 'desconocido')
                if acodec and acodec != 'none':
                    acodec = acodec.split('.')[0].upper()
                
                ext = info.get('ext', 'N/A')
                filesize = info.get('filesize') or info.get('filesize_approx')
                
                message = f"🎵 Mejor audio disponible:\n\n"
                message += f"• Bitrate: ~{abr:.0f} kbps\n"
                message += f"• Códec: {acodec}\n"
                message += f"• Formato: {ext}\n"
                
                if filesize:
                    size_mb = filesize / (1024 * 1024)
                    message += f"• Tamaño: ~{size_mb:.1f} MB\n"
                
                return message
            
            else:  # Video+Audio
                # Información de video
                width = info.get('width', 'N/A')
                height = info.get('height', 'N/A')
                vcodec = info.get('vcodec', 'desconocido')
                if vcodec and vcodec != 'none':
                    vcodec = vcodec.split('.')[0].upper()
                
                fps = info.get('fps', 'N/A')
                vext = info.get('ext', 'N/A')
                
                # Información de audio
                acodec = info.get('acodec', 'desconocido')
                if acodec and acodec != 'none':
                    acodec = acodec.split('.')[0].upper()
                else:
                    acodec = "Sin audio"
                
                abr = info.get('abr') or info.get('tbr', 0)
                
                # Tamaño
                filesize = info.get('filesize') or info.get('filesize_approx')
                
                message = f"🎬 Mejor calidad disponible:\n\n"
                message += f"📹 Video:\n"
                message += f"   • Resolución: {width}x{height}\n"
                message += f"   • Códec: {vcodec}\n"
                
                if fps != 'N/A':
                    message += f"   • FPS: {fps}\n"
                
                message += f"   • Formato: {vext}\n\n"
                
                message += f"🔊 Audio:\n"
                message += f"   • Códec: {acodec}\n"
                
                if acodec != "Sin audio":
                    message += f"   • Bitrate: ~{abr:.0f} kbps\n"
                
                if filesize:
                    size_mb = filesize / (1024 * 1024)
                    message += f"\n📦 Tamaño estimado: ~{size_mb:.1f} MB"
                
                return message

        except Exception as e:
            error_msg = str(e)
            print(f"ERROR: Falló la simulación de descarga: {error_msg}")
            
            # Mensaje más amigable para el usuario
            return (
                "❌ No se pudieron obtener los detalles del formato alternativo.\n\n"
                f"Razón: {error_msg[:100]}...\n\n"
                "Puedes intentar:\n"
                "• Verificar la URL\n"
                "• Configurar cookies si el video es privado\n"
                "• Intentar más tarde si hay límite de peticiones"
            )

    def __init__(self, launch_target=None, project_root=None, poppler_path=None, inkscape_path=None, splash_screen=None, app_version="0.0.0"):
        super().__init__()
        
        # Guardamos la versión que recibimos de main.py
        self.APP_VERSION = app_version 
        print(f"DEBUG: MainWindow recibió la versión: {self.APP_VERSION}")

        # --- CORRECCIÓN CRÍTICA: Registrar este Root INMEDIATAMENTE ---
        import tkinter
        tkinter._default_root = self

        self.splash_screen = splash_screen 
        if self.splash_screen:
            self.splash_screen.update_status("Inicializando componentes...")

        # ✅ NUEVO: Ocultar ventana durante inicialización
        self.withdraw()
        
        # 📏 ESCALADO INTELIGENTE PARA MONITORES PEQUEÑOS
        # Si la altura de la pantalla es menor a 900px (ej: laptops 1366x768),
        # reducimos la interfaz al 85% para que quepa todo.
        screen_height = self.winfo_screenheight()
        if screen_height < 900:
            print(f"INFO: Monitor pequeño detectado ({screen_height}px). Aplicando escala 0.85x.")
            ctk.set_widget_scaling(0.85)  # Reduce el tamaño de los widgets
            ctk.set_window_scaling(0.85)  # Reduce el tamaño de la ventana
        else:
            ctk.set_widget_scaling(1.0)
            ctk.set_window_scaling(1.0)

        # Aplicar estilos de CustomTkinter manualmente
        if TKDND_AVAILABLE:
            ctk.set_appearance_mode("Dark")
            ctk.set_default_color_theme("blue")
            self.configure(bg="#2B2B2B")

        self.VIDEO_EXTENSIONS = VIDEO_EXTENSIONS
        self.AUDIO_EXTENSIONS = AUDIO_EXTENSIONS
        self.SINGLE_STREAM_AUDIO_CONTAINERS = SINGLE_STREAM_AUDIO_CONTAINERS
        self.FORMAT_MUXER_MAP = FORMAT_MUXER_MAP
        self.LANG_CODE_MAP = LANG_CODE_MAP
        self.LANGUAGE_ORDER = LANGUAGE_ORDER
        self.DEFAULT_PRIORITY = DEFAULT_PRIORITY
        self.EDITOR_FRIENDLY_CRITERIA = EDITOR_FRIENDLY_CRITERIA
        self.COMPATIBILITY_RULES = COMPATIBILITY_RULES

        global main_app_instance, ACTIVE_TARGET_SID, LATEST_FILE_LOCK, socketio
        main_app_instance = self

        # --- Adjuntar globales para pasarlos a las pestañas ---
        self.ACTIVE_TARGET_SID_accessor = lambda: ACTIVE_TARGET_SID
        self.LATEST_FILE_LOCK = LATEST_FILE_LOCK
        self.socketio = socketio

        # --- ¡AQUÍ ESTÁ LA CORRECCIÓN! ---
        # 2. Determina la ruta base (PARA LOS BINARIOS)
        if getattr(sys, 'frozen', False):
            # Modo .exe: la ruta es el directorio del ejecutable
            self.APP_BASE_PATH = os.path.dirname(sys.executable)
        elif project_root:
            # Modo Dev: usamos la ruta pasada desde main.py
            self.APP_BASE_PATH = project_root
        else:
            # Fallback (no debería usarse, pero es seguro tenerlo)
            self.APP_BASE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

        # 3. Define las rutas de configuración (PARA LOS DATOS DE USUARIO)
        
        # --- INICIO DE LA MODIFICACIÓN (LA BUENA) ---
        # 1. Definir la carpeta de datos del usuario en %APPDATA%
        self.APP_DATA_DIR = os.path.join(os.path.expandvars('%APPDATA%'), 'DowP')

        # 2. Asegurarse de que esa carpeta exista
        try:
            os.makedirs(self.APP_DATA_DIR, exist_ok=True)
        except Exception as e:
            print(f"ERROR: No se pudo crear la carpeta de datos en %APPDATA%: {e}")
            # Fallback a la carpeta antigua si %APPDATA% falla
            self.APP_DATA_DIR = self.APP_BASE_PATH

        # 3. Definir las rutas usando la nueva carpeta de datos
        self.SETTINGS_FILE = os.path.join(self.APP_DATA_DIR, "app_settings.json")
        self.PRESETS_FILE = os.path.join(self.APP_DATA_DIR, "presets.json") 
        # --- FIN DE LA MODIFICACIÓN ---

        self.ui_update_queue = queue.Queue()
        self._process_ui_queue()

        self.launch_target = launch_target
        self.is_shutting_down = False
        self.cancellation_event = threading.Event()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.title(f"DowP {self.APP_VERSION}")
        self.iconbitmap(resource_path("DowP-icon.ico"))
        
        # Obtener dimensiones de pantalla
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()

        # Margen de seguridad para Barra de Tareas (abajo) y Barra de Título (arriba)
        # 100px es seguro para Windows/Mac/Linux
        safe_height = screen_height - 100

        # --- LÓGICA DE ADAPTACIÓN DE PANTALLA ---
        # Umbral subido a 1020px para capturar resoluciones 1440x900 y 1280x1024
        if screen_height < 1020:  
            print(f"INFO: Pantalla compacta detectada ({screen_width}x{screen_height}). Ajustando.")
            
            # 1. Escalado: Si es muy pequeña (768p), 0.75x. Si es mediana (900p), 0.85x.
            if screen_height < 800:
                scale_factor = 0.75
            else:
                scale_factor = 0.85 # Un poco más grande para 900p
            
            ctk.set_widget_scaling(scale_factor)  
            ctk.set_window_scaling(scale_factor)
            
            # 2. Dimensiones: Usar el ALTO SEGURO calculado
            win_width = 800
            win_height = safe_height # <--- ESTO GARANTIZA QUE NO SE CORTE
            
            # 3. Posición: Pegado arriba (Y=10) para aprovechar espacio
            pos_x = (screen_width // 2) - (win_width // 2)
            pos_y = 10 
            
            # 4. Minsize permisivo
            min_w, min_h = 750, 500
            
        else: # Monitores grandes (1080p o más)
            win_width = 835
            win_height = 950
            
            # Centrado vertical estándar
            pos_x = (screen_width // 2) - (win_width // 2)
            pos_y = (screen_height // 2) - (win_height // 2)
            
            min_w, min_h = 835, 700
            
            # Escalado normal
            ctk.set_widget_scaling(1.0)
            ctk.set_window_scaling(1.0)

        # Aplicar
        self.geometry(f"{win_width}x{win_height}+{int(pos_x)}+{int(pos_y)}")
        self.minsize(min_w, min_h)
        
        self.is_updating_dimension = False
        self.current_aspect_ratio = None
        
        # Aplicar límite mínimo calculado
        self.minsize(min_w, min_h)
        
        ctk.set_appearance_mode("Dark")
        server_thread = threading.Thread(target=run_flask_app, daemon=True)
        server_thread.start()
        print("INFO: Servidor de integración iniciado en el puerto 7788.")
        
        self.ui_request_event = threading.Event()
        self.ui_request_data = {}
        self.ui_response_event = threading.Event()
        self.ui_response_data = {}
        
        # --- INICIALIZAR VALORES POR DEFECTO ---
        # Define todos los atributos ANTES del bloque try
        self.default_download_path = ""
        self.batch_download_path = ""
        self.image_output_path = ""
        self.cookies_path = ""
        self.cookies_mode_saved = "No usar"
        self.selected_browser_saved = "firefox"
        self.browser_profile_saved = ""
        self.ffmpeg_update_snooze_until = None
        self.custom_presets = []
        self.batch_playlist_analysis_saved = True
        self.batch_auto_import_saved = True
        self.image_auto_import_saved = True
        self.batch_fast_mode_saved = True 
        self.quick_preset_saved = ""
        self.recode_settings = {}
        self.apply_quick_preset_checkbox_state = False
        self.keep_original_quick_saved = True
        self.image_settings = {}
        
        # --- INTENTAR CARGAR CONFIGURACIÓN GUARDADA ---
        try:
            print(f"DEBUG: Intentando cargar configuración desde: {self.SETTINGS_FILE}")
            if os.path.exists(self.SETTINGS_FILE):
                with open(self.SETTINGS_FILE, 'r') as f:
                    settings = json.load(f)
                    # Sobrescribe los valores por defecto con los que están guardados
                    self.default_download_path = settings.get("default_download_path", self.default_download_path)
                    self.batch_download_path = settings.get("batch_download_path", self.batch_download_path)
                    self.image_output_path = settings.get("image_output_path", self.image_output_path)
                    self.cookies_path = settings.get("cookies_path", self.cookies_path)
                    self.cookies_mode_saved = settings.get("cookies_mode", self.cookies_mode_saved)
                    self.selected_browser_saved = settings.get("selected_browser", self.selected_browser_saved)
                    self.browser_profile_saved = settings.get("browser_profile", self.browser_profile_saved)
                    snooze_str = settings.get("ffmpeg_update_snooze_until")
                    self.batch_playlist_analysis_saved = settings.get("batch_playlist_analysis", self.batch_playlist_analysis_saved)
                    self.batch_auto_import_saved = settings.get("batch_auto_import", self.batch_auto_import_saved)
                    self.image_auto_import_saved = settings.get("image_auto_import", self.image_auto_import_saved) 
                    self.batch_fast_mode_saved = settings.get("batch_fast_mode", self.batch_fast_mode_saved)
                    self.quick_preset_saved = settings.get("quick_preset_saved", self.quick_preset_saved)
                    if snooze_str:
                        self.ffmpeg_update_snooze_until = datetime.fromisoformat(snooze_str)
                    self.recode_settings = settings.get("recode_settings", self.recode_settings)
                
                    self.apply_quick_preset_checkbox_state = settings.get("apply_quick_preset_enabled", self.apply_quick_preset_checkbox_state)
                    self.keep_original_quick_saved = settings.get("keep_original_quick_enabled", self.keep_original_quick_saved)
                    self.image_settings = settings.get("image_settings", {})
                print(f"DEBUG: Configuración cargada exitosamente.")
            else:
                print("DEBUG: Archivo de configuración no encontrado. Usando valores por defecto.")
        except (json.JSONDecodeError, IOError) as e:
            print(f"ERROR: Fallo al cargar configuración: {e}. Usando valores por defecto.")
            # No se necesita 'pass' porque los valores por defecto ya están establecidos

        self.ffmpeg_processor = FFmpegProcessor()
        self.tab_view = ctk.CTkTabview(self, anchor="nw")
        self.tab_view.pack(expand=True, fill="both", padx=5, pady=5)
        
        # (Cargará la clase de nuestro nuevo archivo)
        self.tab_view.add("Proceso Único")
        self.single_tab = SingleDownloadTab(master=self.tab_view.tab("Proceso Único"), app=self)
        
        # Añadir la pestaña de Lotes (como placeholder)
        self.tab_view.add("Proceso por Lotes")
        self.batch_tab = BatchDownloadTab(master=self.tab_view.tab("Proceso por Lotes"), app=self)

        # Añadir la pestaña de Herramientas de Imagen
        self.tab_view.add("Herramientas de Imagen")
        self.image_tab = ImageToolsTab(master=self.tab_view.tab("Herramientas de Imagen"), 
                                       app=self, 
                                       poppler_path=poppler_path,
                                       inkscape_path=inkscape_path)

        self.run_initial_setup()
        self._check_for_ui_requests()
        self._last_clipboard_check = "" 
        self.bind("<FocusIn>", self._on_app_focus)
        self.after(100, self._show_window_when_ready)

    def _process_ui_queue(self):
        """Revisa la cola de actualizaciones y ejecuta las acciones en el hilo principal."""
        try:
            while True:
                # Obtener tarea sin bloquear
                task = self.ui_update_queue.get_nowait()
                func, args = task
                try:
                    func(*args)
                except Exception as e:
                    print(f"ERROR al procesar tarea de UI: {e}")
        except queue.Empty:
            pass
        finally:
            # Reprogramar la revisión
            self.after(100, self._process_ui_queue)
    
    def run_initial_setup(self):
        """
        Inicia la aplicación, configura la UI y lanza las comprobaciones.
        AHORA INCLUYE LA DESCARGA DE MODELOS DE IA.
        """
        print("INFO: Configurando UI y lanzando comprobaciones de inicio...")

        # 1. Comprobación de actualización de la app
        from src.core.setup import check_app_update
        
        # ✅ CORRECCIÓN: Usar función wrapper y la cola para seguridad de hilos
        def run_update_check_thread():
            try:
                result = check_app_update(self.APP_VERSION)
                # Enviar el resultado al hilo principal a través de la cola
                self.ui_update_queue.put((self.on_update_check_complete, (result,)))
            except Exception as e:
                print(f"ERROR en chequeo de actualización: {e}")

        threading.Thread(
            target=run_update_check_thread,
            daemon=True
        ).start()

        # 2. Verificación de Inkscape (Segundo plano)
        from src.core.setup import check_inkscape_status
        
        def run_inkscape_check():
            result = check_inkscape_status(lambda t, v: None)
            # Encolar la actualización en lugar de llamar a after
            self.ui_update_queue.put((self.on_inkscape_check_complete, (result,)))

        threading.Thread(target=run_inkscape_check, daemon=True).start()

        # 3. Verificación de Ghostscript (Segundo plano)
        from src.core.setup import check_ghostscript_status
        
        def run_ghostscript_check():
            result = check_ghostscript_status(lambda t, v: None)
            # Encolar
            self.ui_update_queue.put((self.on_ghostscript_check_complete, (result,)))

        threading.Thread(target=run_ghostscript_check, daemon=True).start()
        
        # 4. COMPROBACIÓN PRINCIPAL (Solo entorno base en LoadingWindow)
        from src.core.setup import check_environment_status 
        # Nota: Ya NO importamos check_and_download_rembg_models aquí para el hilo bloqueante

        def initial_check_task():
            # 1. Comprobación Rápida de Existencia (Sin Internet)
            # Definimos nombres de ejecutables
            import platform
            exe_ext = ".exe" if platform.system() == "Windows" else ""
            
            ffmpeg_ok = os.path.exists(os.path.join(BIN_DIR, "ffmpeg", f"ffmpeg{exe_ext}"))
            deno_ok = os.path.exists(os.path.join(BIN_DIR, "deno", f"deno{exe_ext}"))
            poppler_ok = os.path.exists(os.path.join(BIN_DIR, "poppler", f"pdfinfo{exe_ext}"))
            
            # Si falta algo, forzamos el chequeo de actualizaciones (que descargará lo que falte)
            # Si todo está bien, saltamos el chequeo de red
            should_check_online = not (ffmpeg_ok and deno_ok and poppler_ok)
            
            if should_check_online:
                print("INFO: Faltan componentes. Iniciando verificación ONLINE.")
            else:
                print("INFO: Componentes detectados. Inicio RÁPIDO (Offline).")

            # A. Verificar Entorno
            env_status = check_environment_status(
                lambda text, val: self.update_setup_progress(text, val),
                check_updates=should_check_online
            )
            
            # B. (ELIMINADO) La descarga de IA ahora es bajo demanda en la pestaña correspondiente.
            
            # C. Finalizar
            self.after(0, lambda: self.on_status_check_complete(env_status))
            self.after(0, lambda: self.update_setup_progress("Iniciando...", 100))

        # ---------------------------------------------------------------
        # 5. GESTIÓN DE MODELOS IA (MODO LAZY - BAJO DEMANDA)
        # ---------------------------------------------------------------
        # Ya no descargamos nada al inicio para reducir peso y tiempo de carga.
        
        def rembg_background_task():
            # Solo actualizamos la UI para decir que el sistema está listo para usarse cuando se necesite
            self.ui_update_queue.put((
                lambda: self.single_tab.rembg_status_label.configure(text="Modelos IA: Bajo Demanda\n(Se descargarán al usar)"),
                ()
            ))

        # Lanzar hilo simple para actualizar la etiqueta sin bloquear
        threading.Thread(target=rembg_background_task, daemon=True).start()
        
        # 2. Definir rutas
        ffmpeg_exe_name = "ffmpeg.exe" if platform.system() == "Windows" else "ffmpeg"
        ffmpeg_path = os.path.join(BIN_DIR, ffmpeg_exe_name)
        
        deno_exe_name = "deno.exe" if platform.system() == "Windows" else "deno"
        DENO_BIN_DIR = os.path.join(BIN_DIR, "deno")
        deno_path = os.path.join(DENO_BIN_DIR, deno_exe_name)

        poppler_exe_name = "pdfinfo.exe" if platform.system() == "Windows" else "pdfinfo"
        POPPLER_BIN_DIR = os.path.join(BIN_DIR, "poppler")
        poppler_path = os.path.join(POPPLER_BIN_DIR, poppler_exe_name)

        inkscape_exe_name = "inkscape.exe" if platform.system() == "Windows" else "inkscape"
        INKSCAPE_BIN_DIR = os.path.join(BIN_DIR, "inkscape")

        # 3. Comprobar si TODOS existen
        if not os.path.exists(ffmpeg_path) or not os.path.exists(deno_path) or not os.path.exists(poppler_path):
            # 4a. NO EXISTE (alguno de los dos): ...
            print("INFO: FFmpeg o Deno no detectados. Ejecutando comprobador de entorno completo...")
            threading.Thread(
                target=lambda: self.on_status_check_complete(check_environment_status(lambda text, val: None)),
                daemon=True
            ).start()
        else:
            # 4b. SÍ EXISTE: Cargar solo la versión local, sin llamar a la API.
            print("INFO: FFmpeg detectado localmente. Omitiendo la comprobación de API de GitHub.")
            
            local_version = "Desconocida"
            version_file = os.path.join(BIN_DIR, "ffmpeg_version.txt")
            if os.path.exists(version_file):
                try:
                    with open(version_file, 'r') as f:
                        local_version = f.read().strip()
                except Exception as e:
                    print(f"ADVERTENCIA: No se pudo leer el archivo de versión de FFmpeg: {e}")
            
            # 5. Actualizar la UI directamente con la info local
            self.single_tab.ffmpeg_status_label.configure(text=f"FFmpeg: {local_version} \n(Instalado)")
            self.single_tab.update_ffmpeg_button.configure(state="normal", text="Buscar Actualizaciones de FFmpeg")

            # --- AÑADIR Lógica de Deno ---
            local_deno_version = "Desconocida"
            deno_version_file = os.path.join(DENO_BIN_DIR, "deno_version.txt")
            if os.path.exists(deno_version_file):
                try:
                    with open(deno_version_file, 'r') as f:
                        local_deno_version = f.read().strip()
                except Exception as e:
                    print(f"ADVERTENCIA: No se pudo leer el archivo de versión de Deno: {e}")
            
            self.single_tab.deno_status_label.configure(text=f"Deno: {local_deno_version} \n(Instalado)")
            self.single_tab.update_deno_button.configure(state="normal", text="Buscar Actualizaciones de Deno")

            # --- AÑADIR Lógica de Poppler ---
            local_poppler_version = "Desconocida"
            poppler_version_file = os.path.join(POPPLER_BIN_DIR, "poppler_version.txt")
            if os.path.exists(poppler_version_file):
                try:
                    with open(poppler_version_file, 'r') as f:
                        local_poppler_version = f.read().strip()
                except Exception as e:
                    print(f"ADVERTENCIA: No se pudo leer el archivo de versión de Poppler: {e}")
            
            self.single_tab.poppler_status_label.configure(text=f"Poppler: {local_poppler_version} \n(Instalado)")
            self.single_tab.update_poppler_button.configure(state="normal", text="Buscar Actualizaciones de Poppler")

            # --- AÑADIR Lógica de Inkscape ---
            local_ink_version = "Desconocida"
            ink_version_file = os.path.join(INKSCAPE_BIN_DIR, "inkscape_version.txt")
            if os.path.exists(ink_version_file):
                try:
                     with open(ink_version_file, 'r') as f: local_ink_version = f.read().strip()
                except: pass
            
            self.single_tab.inkscape_status_label.configure(text=f"Inkscape: {local_ink_version} \n(Instalado)")
            self.single_tab.update_inkscape_button.configure(state="normal", text="Buscar Actualizaciones de Inkscape")
        
        # 6. Detección de códecs (esto se ejecuta siempre, pero es local, no usa API)
        self.ffmpeg_processor.run_detection_async(self.on_ffmpeg_detection_complete) # CORREGIDO
        
    def on_update_check_complete(self, update_info):
        """Callback que se ejecuta cuando la comprobación de versión termina. Ahora inicia la descarga."""
        def _ui_task():
            if update_info.get("update_available"):
                latest_version = update_info.get("latest_version")
                self.single_tab.release_page_url = update_info.get("release_url") # Guardamos por si acaso

                is_prerelease = update_info.get("is_prerelease", False)
                version_type = "Pre-release" if is_prerelease else "versión"
                status_text = f"¡Nueva {version_type} {latest_version} disponible!"

                self.single_tab.app_status_label.configure(text=status_text, text_color="#52a2f2")

                # --- CAMBIO: INICIA EL PROCESO DE ACTUALIZACIÓN ---
                installer_url = update_info.get("installer_url")
                if installer_url:
                    # Preguntar al usuario si quiere actualizar AHORA
                    user_response = messagebox.askyesno(
                        "Actualización Disponible",
                        f"Hay una nueva {version_type} ({latest_version}) de DowP disponible.\n\n"
                        "¿Deseas descargarla e instalarla ahora?\n\n"
                        "(DowP se cerrará para completar la instalación)"
                    )
                    self.lift() # Asegura que la ventana principal esté al frente
                    self.focus_force()

                    if user_response:
                        # Llamar a la nueva función para descargar y ejecutar
                        # Pasamos la URL y la versión para mostrar en el progreso
                        self._iniciar_auto_actualizacion(installer_url, latest_version)
                    else:
                        # El usuario dijo NO, solo configuramos el botón para que pueda hacerlo manualmente
                        self.single_tab.update_app_button.configure(text=f"Descargar v{latest_version}", state="normal", fg_color=self.single_tab.DOWNLOAD_BTN_COLOR)
                else:
                    # No se encontró el .exe, solo habilitar el botón para ir a la página
                    print("ADVERTENCIA: Se detectó una nueva versión pero no se encontró el instalador .exe en los assets.")
                    self.single_tab.update_app_button.configure(text=f"Ir a Descargas (v{latest_version})", state="normal", fg_color=self.single_tab.DOWNLOAD_BTN_COLOR)


            elif "error" in update_info:
                self.single_tab.app_status_label.configure(text=f"DowP v{self.APP_VERSION} - Error al verificar", text_color="orange")
                self.single_tab.update_app_button.configure(text="Reintentar", state="normal", fg_color="gray")
            else:
                self.single_tab.app_status_label.configure(text=f"DowP v{self.APP_VERSION} - Estás al día ✅")
                self.single_tab.update_app_button.configure(text="Sin actualizaciones", state="disabled")
        self.after(0, _ui_task)


    def on_status_check_complete(self, status_info, force_check=False):
        """
        Callback FINAL que gestiona el estado de FFmpeg.
        """
        status = status_info.get("status")
        
        self.single_tab.update_ffmpeg_button.configure(state="normal", text="Buscar Actualizaciones de FFmpeg")
        self.single_tab.update_deno_button.configure(state="normal", text="Buscar Actualizaciones de Deno")

        if status == "error":
            messagebox.showerror("Error Crítico de Entorno", status_info.get("message"))
            return

        # --- Variables de FFmpeg ---
        local_version = status_info.get("local_version") or "No encontrado"
        latest_version = status_info.get("latest_version")
        download_url = status_info.get("download_url")
        ffmpeg_exists = status_info.get("ffmpeg_path_exists")
        
        # --- Variables de Deno ---
        local_deno_version = status_info.get("local_deno_version") or "No encontrado"
        latest_deno_version = status_info.get("latest_deno_version")
        deno_download_url = status_info.get("deno_download_url")
        deno_exists = status_info.get("deno_path_exists")
        
        should_download = False
        should_download_deno = False

        # --- Variables de Poppler ---
        local_poppler_version = status_info.get("local_poppler_version") or "No encontrado"
        latest_poppler_version = status_info.get("latest_poppler_version")
        poppler_download_url = status_info.get("poppler_download_url")
        poppler_exists = status_info.get("poppler_path_exists")
        
        should_download_poppler = False # <--- IMPORTANTE
        
        # --- Lógica de descarga de FFmpeg (CORREGIDA) ---
        if not ffmpeg_exists:
            # CORRECCIÓN: Solo auto-descargar si NO es un chequeo manual
            if not force_check:
                print("INFO: FFmpeg no encontrado. Iniciando descarga automática.")
                self.single_tab.update_progress(0, "FFmpeg no encontrado. Iniciando descarga automática...")
                should_download = True
            else:
                # El usuario presionó "buscar" pero no está instalado. Preguntar.
                print("INFO: Comprobación manual de FFmpeg. No está instalado.")
                user_response = messagebox.askyesno(
                    "FFmpeg no está instalado",
                    f"No se encontró FFmpeg. Es necesario para todas las descargas y recodificaciones.\n\n"
                    f"Versión más reciente disponible: {latest_version}\n\n"
                    "¿Deseas descargarlo e instalarlo ahora?"
                )
                self.lift()
                if user_response:
                    should_download = True
                else:
                    self.single_tab.ffmpeg_status_label.configure(text=f"FFmpeg: {local_version} \n(Instalación cancelada)")
        else:
            # FFmpeg *está* instalado. Comprobar actualizaciones.
            update_available = False
            try:
                # CORRECCIÓN: Usar version.parse para una comparación robusta
                if latest_version: # Solo comparar si obtuvimos respuesta de GitHub
                    # Extraer números de versión (ej: "v6.1" de "ffmpeg-v6.1-...")
                    local_v_str = re.search(r'v?(\d+\.\d+(\.\d+)?)', local_version).group(1) if local_version and re.search(r'v?(\d+\.\d+(\.\d+)?)', local_version) else "0"
                    latest_v_str = re.search(r'v?(\d+\.\d+(\.\d+)?)', latest_version).group(1) if latest_version and re.search(r'v?(\d+\.\d+(\.\d+)?)', latest_version) else "0"
                    
                    local_v = version.parse(local_v_str)
                    latest_v = version.parse(latest_v_str)
                    
                    if latest_v > local_v:
                        update_available = True
            except (version.InvalidVersion, AttributeError):
                print(f"ADVERTENCIA: No se pudo comparar la versión de FFmpeg (Local: '{local_version}', Remota: '{latest_version}'). Usando '!=' fallback.")
                update_available = local_version != latest_version # Fallback a la lógica antigua
            except Exception as e:
                print(f"ERROR comparando versiones de FFmpeg: {e}")
                update_available = False
            
            snoozed = self.ffmpeg_update_snooze_until and datetime.now() < self.ffmpeg_update_snooze_until
                        
            if update_available and force_check and not snoozed:
                user_response = messagebox.askyesno(
                    "Actualización Disponible",
                    f"Hay una nueva versión de FFmpeg disponible.\n\n"
                    f"Versión Actual: {local_version}\n"
                    f"Versión Nueva: {latest_version}\n\n"
                    "¿Deseas actualizar ahora?"
                )
                self.lift() 
                if user_response:
                    should_download = True
                    self.ffmpeg_update_snooze_until = None 
                else:
                    self.ffmpeg_update_snooze_until = datetime.now() + timedelta(days=15)
                    self.single_tab.ffmpeg_status_label.configure(text=f"FFmpeg: {local_version} \n(Actualización pospuesta)") 
                
                # Guardar la decisión de "snooze"
                self.save_settings()
                
            elif update_available and (not force_check or snoozed):
                if snoozed:
                    print(f"DEBUG: Actualización de FFmpeg omitida. Snooze activo hasta {self.ffmpeg_update_snooze_until}.")
                    self.single_tab.ffmpeg_status_label.configure(text=f"FFmpeg: {local_version} \n(Actualización pospuesta)") 
                else:
                    self.single_tab.ffmpeg_status_label.configure(text=f"FFmpeg: {local_version} \n(Actualización disponible)") 
            else:
                self.single_tab.ffmpeg_status_label.configure(text=f"FFmpeg: {local_version} \n(Actualizado)") 

        # --- Lógica de descarga de Deno (CORREGIDA) ---
        if not deno_exists:
            # CORRECCIÓN: Solo auto-descargar si NO es un chequeo manual
            if not force_check:
                print("INFO: Deno no encontrado. Iniciando descarga automática.")
                self.single_tab.update_progress(0, "Deno (requerido por YouTube) no encontrado. Iniciando descarga...")
                should_download_deno = True
            else:
                # El usuario presionó "buscar" pero no está instalado. Preguntar.
                print("INFO: Comprobación manual de Deno. No está instalado.")
                user_response = messagebox.askyesno(
                    "Deno no está instalado",
                    f"No se encontró Deno. Es necesario para algunas descargas.\n\n"
                    f"Versión más reciente disponible: {latest_deno_version}\n\n"
                    "¿Deseas descargarlo e instalarlo ahora?"
                )
                self.lift()
                if user_response:
                    should_download_deno = True
                else:
                    self.single_tab.deno_status_label.configure(text=f"Deno: {local_deno_version} \n(Instalación cancelada)")
        
        else:
            # Deno *está* instalado. Comprobar actualizaciones.
            deno_update_available = False
            try:
                # CORRECCIÓN: Usar version.parse para una comparación robusta
                if latest_deno_version: # Solo comparar si obtuvimos respuesta de GitHub
                    # Quitar la 'v' del inicio (ej: "v1.40.0" -> "1.40.0")
                    local_v = version.parse(local_deno_version.lstrip('v'))
                    latest_v = version.parse(latest_deno_version.lstrip('v'))
                    
                    if latest_v > local_v:
                        deno_update_available = True
            except version.InvalidVersion:
                print(f"ADVERTENCIA: No se pudo comparar la versión de Deno (Local: '{local_deno_version}', Remota: '{latest_deno_version}'). Usando '!=' fallback.")
                deno_update_available = local_deno_version != latest_deno_version # Fallback
            except Exception as e:
                print(f"ERROR comparando versiones de Deno: {e}")
                deno_update_available = False
            
            if deno_update_available and force_check:
                # Esta es la lógica que querías: pregunta al usuario
                user_response = messagebox.askyesno(
                    "Actualización de Deno Disponible",
                    f"Hay una nueva versión de Deno disponible.\n\n"
                    f"Versión Actual: {local_deno_version}\n"
                    f"Versión Nueva: {latest_deno_version}\n\n"
                    "¿Deseas actualizar ahora?"
                )
                self.lift() 
                if user_response:
                    should_download_deno = True
            elif deno_update_available:
                 # No es un chequeo forzado, solo notificar
                 self.single_tab.deno_status_label.configure(text=f"Deno: {local_deno_version} \n(Actualización disponible)")
            else:
                 # Está actualizado
                self.single_tab.deno_status_label.configure(text=f"Deno: {local_deno_version} \n(Actualizado)")

        # --- Lógica de descarga de Poppler ---
        if not poppler_exists:
            # Si NO es un chequeo manual (arranque de la app), descargar automáticamente
            if not force_check:
                print("INFO: Poppler no encontrado. Iniciando descarga automática.")
                self.single_tab.update_progress(0, "Poppler no encontrado. Iniciando descarga...")
                should_download_poppler = True
            else:
                # Si es manual (botón), preguntar
                print("INFO: Comprobación manual de Poppler. No está instalado.")
                user_response = messagebox.askyesno(
                    "Poppler no está instalado",
                    f"No se encontró Poppler. Es necesario para procesar imágenes.\n\n"
                    f"Versión disponible: {latest_poppler_version}\n\n"
                    "¿Deseas descargarlo e instalarlo ahora?"
                )
                self.lift()
                if user_response:
                    should_download_poppler = True
                else:
                    self.single_tab.poppler_status_label.configure(text=f"Poppler: {local_poppler_version} \n(Cancelado)")
        
        else:
            # Poppler existe, comprobar actualizaciones
            poppler_update_available = False
            try:
                if latest_poppler_version and local_poppler_version != latest_poppler_version:
                    poppler_update_available = True
            except Exception:
                pass

            if poppler_update_available and force_check:
                user_response = messagebox.askyesno(
                    "Actualización de Poppler Disponible",
                    f"Hay una nueva versión de Poppler disponible.\n\n"
                    f"Actual: {local_poppler_version}\nNueva: {latest_poppler_version}\n\n"
                    "¿Actualizar ahora?"
                )
                self.lift()
                if user_response:
                    should_download_poppler = True
            elif poppler_update_available:
                 self.single_tab.poppler_status_label.configure(text=f"Poppler: {local_poppler_version} \n(Update disp.)")
            else:
                self.single_tab.poppler_status_label.configure(text=f"Poppler: {local_poppler_version} \n(Instalado)")
                if force_check:
                    messagebox.showinfo("Poppler", "Poppler está actualizado.")

        # --- Hilo de Descarga de FFmpeg (Sin cambios) ---
        if should_download:
            if not download_url:
                messagebox.showerror("Error", "No se pudo obtener la URL de descarga para FFmpeg.")
                return

            self.single_tab.update_setup_download_progress('ffmpeg', f"Iniciando descarga de FFmpeg {latest_version}...", 0.01)
            from src.core.setup import download_and_install_ffmpeg

            def download_task():
                # Usar un callback seguro para el progreso
                def progress_safe(text, val):
                    self.ui_update_queue.put((self.single_tab.update_setup_download_progress, ('ffmpeg', text, val)))

                success = download_and_install_ffmpeg(latest_version, download_url, progress_safe) 

                if success:
                    ffmpeg_bin_path = os.path.join(BIN_DIR, "ffmpeg")
                    if ffmpeg_bin_path not in os.environ['PATH']:
                        os.environ['PATH'] = ffmpeg_bin_path + os.pathsep + os.environ['PATH']

                    # USAR COLA PARA TODO
                    self.ui_update_queue.put((
                        self.ffmpeg_processor.run_detection_async, 
                        (lambda s, m: self.on_ffmpeg_detection_complete(s, m, show_ready_message=True),)
                    ))
                    self.ui_update_queue.put((
                        lambda: self.single_tab.ffmpeg_status_label.configure(text=f"FFmpeg: {latest_version} \n(Instalado)"), 
                        ()
                    ))
                    self.ui_update_queue.put((
                        self.single_tab.update_setup_download_progress, 
                        ('ffmpeg', f"✅ FFmpeg {latest_version} instalado.", 100)
                    ))
                else:
                    self.ui_update_queue.put((
                        self.single_tab.update_setup_download_progress, 
                        ('ffmpeg', "Falló la descarga de FFmpeg.", 0)
                    ))

            threading.Thread(target=download_task, daemon=True).start()

        # --- Hilo de Descarga de Deno (MODIFICADO) ---
        if should_download_deno:
            if not deno_download_url:
                messagebox.showerror("Error", "No se pudo obtener la URL de descarga para Deno.")
                return

            self.single_tab.update_setup_download_progress('deno', f"Iniciando descarga de Deno {latest_deno_version}...", 0.01)
            from src.core.setup import download_and_install_deno

            def download_deno_task():
                def progress_safe(text, val):
                    self.ui_update_queue.put((self.single_tab.update_setup_download_progress, ('deno', text, val)))

                success = download_and_install_deno(latest_deno_version, deno_download_url, progress_safe) 

                if success:
                    deno_bin_path = os.path.join(BIN_DIR, "deno")
                    if deno_bin_path not in os.environ['PATH']:
                        os.environ['PATH'] = deno_bin_path + os.pathsep + os.environ['PATH']

                    self.ui_update_queue.put((
                        lambda: self.single_tab.deno_status_label.configure(text=f"Deno: {latest_deno_version} \n(Instalado)"), 
                        ()
                    ))
                    self.ui_update_queue.put((
                        self.single_tab.update_setup_download_progress, 
                        ('deno', f"✅ Deno {latest_deno_version} instalado.", 100)
                    ))
                else:
                    self.ui_update_queue.put((
                        self.single_tab.update_setup_download_progress, 
                        ('deno', "Falló la descarga de Deno.", 0)
                    ))

            threading.Thread(target=download_deno_task, daemon=True).start()

        # --- Hilo de Descarga de Poppler ---
        if should_download_poppler:
            if not poppler_download_url:
                if force_check: messagebox.showerror("Error", "No se pudo obtener la URL de Poppler.")
                return

            self.single_tab.update_setup_download_progress('poppler', f"Descargando Poppler {latest_poppler_version}...", 0.01)
            from src.core.setup import download_and_install_poppler

            def download_poppler_task():
                def progress_safe(text, val):
                    self.ui_update_queue.put((self.single_tab.update_setup_download_progress, ('poppler', text, val)))

                success = download_and_install_poppler(latest_poppler_version, poppler_download_url, progress_safe) 
                
                if success:
                    poppler_bin_path = os.path.join(BIN_DIR, "poppler")
                    if poppler_bin_path not in os.environ['PATH']:
                        os.environ['PATH'] = poppler_bin_path + os.pathsep + os.environ['PATH']
                    
                    self.ui_update_queue.put((
                        lambda: self.single_tab.poppler_status_label.configure(text=f"Poppler: {latest_poppler_version} \n(Instalado)"),
                        ()
                    )) 
                    self.ui_update_queue.put((
                        self.single_tab.update_setup_download_progress, 
                        ('poppler', f"✅ Poppler instalado.", 100)
                    ))
                else:
                    self.ui_update_queue.put((
                        self.single_tab.update_setup_download_progress, 
                        ('poppler', "Falló la descarga de Poppler.", 0)
                    ))

            threading.Thread(target=download_poppler_task, daemon=True).start()

    def on_ffmpeg_detection_complete(self, success, message, show_ready_message=False):
        # 1. Definir la lógica de actualización
        def update_ui():
            if success:
                self.single_tab.recode_video_checkbox.configure(text="Recodificar Video", state="normal") 
                self.single_tab.recode_audio_checkbox.configure(text="Recodificar Audio", state="normal")
                self.single_tab.apply_quick_preset_checkbox.configure(text="Activar recodificación Rápida", state="normal")
                
                if self.ffmpeg_processor.gpu_vendor:
                    self.single_tab.gpu_radio.configure(text="GPU", state="normal")
                    self.single_tab.cpu_radio.pack_forget() 
                    self.single_tab.gpu_radio.pack_forget() 
                    self.single_tab.gpu_radio.pack(side="left", padx=10) 
                    self.single_tab.cpu_radio.pack(side="left", padx=20) 
                else:
                    self.single_tab.gpu_radio.configure(text="GPU (No detectada)")
                    self.single_tab.proc_type_var.set("CPU") 
                    self.single_tab.gpu_radio.configure(state="disabled") 
                
                self.single_tab.update_codec_menu()
                
                if show_ready_message:
                    self.single_tab.update_progress(100, "✅ FFmpeg instalado correctamente. Listo para usar.") 
            else:
                print(f"FFmpeg detection error: {message}")
                self.single_tab.recode_video_checkbox.configure(text="Recodificación no disponible", state="disabled") 
                self.single_tab.recode_audio_checkbox.configure(text="(Error FFmpeg)", state="disabled") 
                self.single_tab.apply_quick_preset_checkbox.configure(text="Recodificación no disponible (Error FFmpeg)", state="disabled") 
                self.single_tab.apply_quick_preset_checkbox.deselect() 

        # 2. SOLUCIÓN: Usar la cola en lugar de self.after
        self.ui_update_queue.put((update_ui, ()))

    def _iniciar_auto_actualizacion(self, installer_url, version_str):
        """
        Descarga el ZIP en Descargas, lo extrae en Temp y ejecuta el instalador.
        """
        print(f"INFO: Iniciando descarga de actualización v{version_str} (ZIP)...")

        self.single_tab.update_app_button.configure(text=f"Descargando v{version_str}...", state="disabled")
        self.single_tab.update_ffmpeg_button.configure(state="disabled")
        self.single_tab.download_button.configure(state="disabled")

        self.single_tab.update_progress(0, f"Descargando actualización v{version_str}...")

        def download_and_run():
            try:
                import requests
                import subprocess
                import os
                import zipfile
                import tempfile
                from pathlib import Path

                # 1. Definir ruta en Descargas (Visible para el usuario)
                downloads_path = Path.home() / "Downloads"
                os.makedirs(downloads_path, exist_ok=True)

                zip_filename = os.path.basename(installer_url) # Ej: DowP_v1.3.0_Light_setup.zip
                zip_path = downloads_path / zip_filename

                # Manejo de duplicados en Descargas
                if zip_path.exists():
                    try:
                        os.remove(zip_path)
                    except Exception:
                        import time
                        zip_filename = f"{int(time.time())}_{zip_filename}"
                        zip_path = downloads_path / zip_filename

                print(f"INFO: Descargando ZIP en: {zip_path}")

                # 2. Descargar el ZIP
                with requests.get(installer_url, stream=True, timeout=180) as r:
                    r.raise_for_status()
                    total_size = int(r.headers.get('content-length', 0))
                    downloaded_size = 0
                    
                    with open(zip_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=8192 * 4):
                            if not chunk: continue
                            f.write(chunk)
                            downloaded_size += len(chunk)
                            if total_size > 0:
                                progress_percent = (downloaded_size / total_size) * 100
                                self.after(0, self.single_tab.update_progress, progress_percent / 100.0,
                                           f"Descargando: {downloaded_size / (1024*1024):.1f} MB")

                self.after(0, self.single_tab.update_progress, 1.0, "Extrayendo instalador...")
                
                # 3. Extraer en carpeta TEMPORAL (Oculta)
                # No extraemos en Descargas para no ensuciar la carpeta del usuario
                extract_dir = tempfile.mkdtemp(prefix="dowp_setup_extract_")
                
                print(f"INFO: Extrayendo en: {extract_dir}")
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(extract_dir)

                # 4. Buscar el .exe dentro de la carpeta extraída
                setup_exe_path = None
                for root, dirs, files in os.walk(extract_dir):
                    for file in files:
                        if file.endswith(".exe"):
                            setup_exe_path = os.path.join(root, file)
                            break
                    if setup_exe_path: break
                
                if not setup_exe_path:
                    raise Exception("No se encontró ningún archivo .exe dentro del ZIP de actualización.")

                self.after(0, self.single_tab.update_progress, 1.0, "Abriendo instalador...")
                print(f"INFO: Ejecutando instalador: {setup_exe_path}")

                # 5. Ejecutar y Cerrar
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
                subprocess.Popen([setup_exe_path], creationflags=creationflags)

                print("INFO: Instalador iniciado. Cerrando DowP...")
                self.after(1000, self.destroy)

            except Exception as e:
                print(f"ERROR: Falló la actualización: {e}")
                self.after(0, lambda: messagebox.showerror("Error", f"No se pudo actualizar:\n{e}"))
                self.after(0, self._reset_buttons_to_original_state)
                self.after(0, lambda: self.single_tab.update_progress(0, "❌ Error en actualización."))

        threading.Thread(target=download_and_run, daemon=True).start()

    def _check_for_ui_requests(self):
        """
        Verifica si un hilo secundario ha solicitado una acción de UI.
        """
        if self.ui_request_event.is_set(): # CORREGIDO
            self.ui_request_event.clear() # CORREGIDO
            request_type = self.ui_request_data.get("type") # CORREGIDO

            if request_type == "ask_yes_no":
                title = self.ui_request_data.get("title", "Confirmar") # CORREGIDO
                message = self.ui_request_data.get("message", "¿Estás seguro?") # CORREGIDO
                
                result = messagebox.askyesno(title, message)
                
                self.ui_response_data["result"] = result # CORREGIDO
                self.lift() # CORREGIDO
                self.ui_response_event.set() # CORREGIDO

            elif request_type == "ask_conflict":
                filename = self.ui_request_data.get("filename", "") # CORREGIDO
                dialog = ConflictDialog(self, filename)


                self.wait_window(dialog) # CORREGIDO
                self.lift() # CORREGIDO
                self.focus_force() # CORREGIDO
                self.ui_response_data["result"] = dialog.result # CORREGIDO
                self.ui_response_event.set() # CORREGIDO
                
            elif request_type == "ask_compromise":
                details = self.ui_request_data.get("details", "Detalles no disponibles.") 
                dialog = CompromiseDialog(self, details)
                self.wait_window(dialog) 
                self.lift() 
                self.focus_force() 
                self.ui_response_data["result"] = dialog.result 
                self.ui_response_event.set() 
            
            elif request_type == "ask_playlist_error":
                url_fragment = self.ui_request_data.get("filename", "esta URL")
                dialog = PlaylistErrorDialog(self, url_fragment)
                
                self.wait_window(dialog)
                self.lift()
                self.focus_force()
                self.ui_response_data["result"] = dialog.result
                self.ui_response_event.set()
                
        self.after(100, self._check_for_ui_requests) # CORREGIDO

    def save_settings(self):
        """
        Recopila todos los ajustes de la app y los guarda en app_settings.json.
        Esta es la ÚNICA función que debe escribir en el archivo.
        """
        # en los ajustes globales (como default_download_path).
        current_tab = self.tab_view.get()
        if current_tab == "Proceso Único":
             if hasattr(self, 'batch_tab'): self.batch_tab.save_settings()
             if hasattr(self, 'image_tab'): self.image_tab.save_settings() # <--- AÑADIR
             if hasattr(self, 'single_tab'): self.single_tab.save_settings()
        elif current_tab == "Proceso por Lotes": # <--- MODIFICAR ESTE ELIF
             if hasattr(self, 'single_tab'): self.single_tab.save_settings()
             if hasattr(self, 'image_tab'): self.image_tab.save_settings() # <--- AÑADIR
             if hasattr(self, 'batch_tab'): self.batch_tab.save_settings()
        else: # <--- AÑADIR ESTE BLOQUE ELSE
             if hasattr(self, 'single_tab'): self.single_tab.save_settings()
             if hasattr(self, 'batch_tab'): self.batch_tab.save_settings()
             if hasattr(self, 'image_tab'): self.image_tab.save_settings()

        # 3. Crear el diccionario de configuración final
        settings_to_save = {
            "default_download_path": self.default_download_path,
            "batch_download_path": self.batch_download_path,
            "image_output_path": self.image_output_path,
            "ffmpeg_update_snooze_until": self.ffmpeg_update_snooze_until.isoformat() if self.ffmpeg_update_snooze_until else None,
            "custom_presets": self.custom_presets,

            # Cookies
            "cookies_path": self.cookies_path,
            "cookies_mode": self.cookies_mode_saved,
            "selected_browser": self.selected_browser_saved,
            "browser_profile": self.browser_profile_saved,

            # Pestaña Individual (Modo Rápido)
            "apply_quick_preset_enabled": self.apply_quick_preset_checkbox_state,
            "keep_original_quick_enabled": self.keep_original_quick_saved,
            "quick_preset_saved": self.quick_preset_saved,

            # Pestaña Individual (Modo Manual)
            "recode_settings": self.recode_settings,

            # Pestaña de Lotes
            "batch_playlist_analysis": self.batch_playlist_analysis_saved,
            "batch_auto_import": self.batch_auto_import_saved,
            "batch_fast_mode": self.batch_fast_mode_saved,

            # Pestaña de Herramientas de Imagen
            "image_auto_import": self.image_auto_import_saved,
            "image_settings": self.image_settings
        }

        # 4. Escribir en el archivo
        try:
            with open(self.SETTINGS_FILE, 'w') as f:
                json.dump(settings_to_save, f, indent=4)
        except IOError as e:
            print(f"ERROR: Fallo al guardar configuración central: {e}")

    def on_closing(self):
        """
        Se ejecuta cuando el usuario intenta cerrar la ventana.
        Gestiona la cancelación, limpieza y confirmación de forma robusta.
        """
        if self.single_tab.active_operation_thread and self.single_tab.active_operation_thread.is_alive():
            if messagebox.askokcancel("Confirmar Salida", "Hay una operación en curso. ¿Estás seguro de que quieres salir?"):
                self.is_shutting_down = True 
                self.attributes("-disabled", True)
                self.single_tab.progress_label.configure(text="Cancelando y limpiando, por favor espera...")
                self.cancellation_event.set()
                self.after(100, self._wait_for_thread_to_finish_and_destroy)
        else:
            self.save_settings() 
            self.destroy()

    def _wait_for_thread_to_finish_and_destroy(self):
        """
        Vigilante que comprueba si el hilo de trabajo ha terminado.
        Una vez que termina (después de su limpieza), cierra la ventana.
        """
        if self.single_tab.active_operation_thread and self.single_tab.active_operation_thread.is_alive():
            self.after(100, self._wait_for_thread_to_finish_and_destroy)
        else:
            self.save_settings() 
            self.destroy()

    # --- AÑADIR ESTA NUEVA FUNCIÓN (disparador con retraso) ---
    def _on_app_focus(self, event=None):
        """
        Se llama cuando la ventana de la aplicación gana el foco.
        Espera 50ms para que la UI (como el cambio de pestaña) se estabilice
        antes de comprobar el portapapeles.
        """
        self.after(50, self._check_clipboard_and_paste)

    # --- ESTA ES LA FUNCIÓN ANTERIOR RENOMBRADA ---
    def _check_clipboard_and_paste(self):
        """
        Comprueba el portapapeles y pega automáticamente si es una URL.
        """
        try:
            clipboard_content = self.clipboard_get()
        except (tkinter.TclError, Exception):
            clipboard_content = "" # Portapapeles vacío o con datos no-texto

        # 1. Evitar re-pegar si el contenido no ha cambiado
        if not clipboard_content or clipboard_content == self._last_clipboard_check:
            return
        
        # 2. Actualizar el contenido "visto"
        self._last_clipboard_check = clipboard_content

        # 3. Validar si es una URL (regex simple)
        url_regex = re.compile(r'^(https|http)://[^\s/$.?#].[^\s]*$')
        if not url_regex.match(clipboard_content):
            return # No es una URL válida

        # 4. Determinar qué pestaña está activa (AHORA SÍ FUNCIONA)
        active_tab_name = self.tab_view.get()
        target_entry = None

        if active_tab_name == "Proceso Único":
            target_entry = self.single_tab.url_entry
        elif active_tab_name == "Proceso por Lotes":
            target_entry = self.batch_tab.url_entry
        elif active_tab_name == "Herramientas de Imagen":
            # (Asegúrate de que tu pestaña de imagen se llame self.image_tab)
            target_entry = self.image_tab.url_entry

        # 5. Pegar la URL, REEMPLAZANDO el contenido
        if target_entry:
            # Si el texto ya es el mismo, no hacer nada (evita re-pegar)
            if target_entry.get() == clipboard_content:
                return

            print(f"DEBUG: URL detectada en portapapeles. Reemplazando en '{active_tab_name}'.")
            target_entry.delete(0, 'end') # BORRAR contenido actual
            target_entry.insert(0, clipboard_content) # INSERTAR nuevo contenido
            
            # Actualizar el estado del botón en la pestaña individual
            if active_tab_name == "Proceso Único":
                self.single_tab.update_download_button_state()

    def on_ffmpeg_check_complete(self, status_info):
        """
        Callback que maneja la comprobación MANUAL de FFmpeg.
        """
        self.single_tab.update_ffmpeg_button.configure(state="normal", text="Buscar Actualizaciones de FFmpeg")

        status = status_info.get("status")
        if status == "error":
            messagebox.showerror("Error Crítico de FFmpeg", status_info.get("message"))
            return

        local_version = status_info.get("local_version") or "No encontrado"
        latest_version = status_info.get("latest_version")
        download_url = status_info.get("download_url")
        ffmpeg_exists = status_info.get("ffmpeg_path_exists")
        should_download = False

        if not ffmpeg_exists:
            print("INFO: Comprobación manual de FFmpeg. No está instalado.")
            user_response = messagebox.askyesno(
                "FFmpeg no está instalado",
                f"No se encontró FFmpeg. Es necesario para todas las descargas y recodificaciones.\n\n"
                f"Versión más reciente disponible: {latest_version}\n\n"
                "¿Deseas descargarlo e instalarlo ahora?"
            )
            self.lift()
            if user_response:
                should_download = True
            else:
                self.single_tab.ffmpeg_status_label.configure(text=f"FFmpeg: {local_version} \n(Instalación cancelada)")
        else:
            update_available = False
            try:
                if latest_version:
                    local_v_str = re.search(r'v?(\d+\.\d+(\.\d+)?)', local_version).group(1) if local_version and re.search(r'v?(\d+\.\d+(\.\d+)?)', local_version) else "0"
                    latest_v_str = re.search(r'v?(\d+\.\d+(\.\d+)?)', latest_version).group(1) if latest_version and re.search(r'v?(\d+\.\d+(\.\d+)?)', latest_version) else "0"
                    local_v = version.parse(local_v_str)
                    latest_v = version.parse(latest_v_str)
                    if latest_v > local_v:
                        update_available = True
            except (version.InvalidVersion, AttributeError):
                update_available = local_version != latest_version

            snoozed = self.ffmpeg_update_snooze_until and datetime.now() < self.ffmpeg_update_snooze_until

            if update_available and not snoozed:
                user_response = messagebox.askyesno(
                    "Actualización Disponible",
                    f"Hay una nueva versión de FFmpeg disponible.\n\n"
                    f"Versión Actual: {local_version}\n"
                    f"Versión Nueva: {latest_version}\n\n"
                    "¿Deseas actualizar ahora?"
                )
                self.lift() 
                if user_response:
                    should_download = True
                    self.ffmpeg_update_snooze_until = None 
                else:
                    self.ffmpeg_update_snooze_until = datetime.now() + timedelta(days=15)
                    self.single_tab.ffmpeg_status_label.configure(text=f"FFmpeg: {local_version} \n(Actualización pospuesta)") 
                self.save_settings()
            elif update_available and snoozed:
                self.single_tab.ffmpeg_status_label.configure(text=f"FFmpeg: {local_version} \n(Actualización pospuesta)") 
                messagebox.showinfo("Actualización Pos puesta", "Hay una nueva versión de FFmpeg, pero la pospusiste. Puedes volver a comprobarla más tarde.")
            else:
                self.single_tab.ffmpeg_status_label.configure(text=f"FFmpeg: {local_version} \n(Actualizado)")
                messagebox.showinfo("FFmpeg", "Ya tienes la última versión de FFmpeg instalada.")

        if should_download:
            if not download_url:
                messagebox.showerror("Error", "No se pudo obtener la URL de descarga para FFmpeg.")
                return

            self.single_tab.update_setup_download_progress('ffmpeg', f"Iniciando descarga de FFmpeg {latest_version}...", 0.01)
            from src.core.setup import download_and_install_ffmpeg

            def download_task():
                success = download_and_install_ffmpeg(latest_version, download_url, 
                    lambda text, val: self.single_tab.update_setup_download_progress('ffmpeg', text, val)) 
                if success:
                    ffmpeg_bin_path = os.path.join(BIN_DIR, "ffmpeg")
                    if ffmpeg_bin_path not in os.environ['PATH']:
                        os.environ['PATH'] = ffmpeg_bin_path + os.pathsep + os.environ['PATH']
                    self.after(0, self.ffmpeg_processor.run_detection_async,  
                            lambda s, m: self.on_ffmpeg_detection_complete(s, m, show_ready_message=True))
                    self.after(0, lambda: self.single_tab.ffmpeg_status_label.configure(text=f"FFmpeg: {latest_version} \n(Instalado)")) 
                    self.after(0, self.single_tab.update_setup_download_progress, 'ffmpeg', f"✅ FFmpeg {latest_version} instalado.", 100)
                else:
                    self.after(0, self.single_tab.update_setup_download_progress, 'ffmpeg', "Falló la descarga de FFmpeg.", 0)

            threading.Thread(target=download_task, daemon=True).start()

    def on_deno_check_complete(self, status_info):
        """
        Callback que maneja la comprobación MANUAL de Deno.
        """
        self.single_tab.update_deno_button.configure(state="normal", text="Buscar Actualizaciones de Deno")

        status = status_info.get("status")
        if status == "error":
            messagebox.showerror("Error Crítico de Deno", status_info.get("message"))
            return

        local_deno_version = status_info.get("local_deno_version") or "No encontrado"
        latest_deno_version = status_info.get("latest_deno_version")
        deno_download_url = status_info.get("deno_download_url")
        deno_exists = status_info.get("deno_path_exists")
        should_download_deno = False

        if not deno_exists:
            print("INFO: Comprobación manual de Deno. No está instalado.")
            user_response = messagebox.askyesno(
                "Deno no está instalado",
                f"No se encontró Deno. Es necesario para algunas descargas.\n\n"
                f"Versión más reciente disponible: {latest_deno_version}\n\n"
                "¿Deseas descargarlo e instalarlo ahora?"
            )
            self.lift()
            if user_response:
                should_download_deno = True
            else:
                self.single_tab.deno_status_label.configure(text=f"Deno: {local_deno_version} \n(Instalación cancelada)")
        else:
            deno_update_available = False
            try:
                if latest_deno_version:
                    local_v = version.parse(local_deno_version.lstrip('v'))
                    latest_v = version.parse(latest_deno_version.lstrip('v'))
                    if latest_v > local_v:
                        deno_update_available = True
            except version.InvalidVersion:
                deno_update_available = local_deno_version != latest_deno_version

            if deno_update_available:
                user_response = messagebox.askyesno(
                    "Actualización de Deno Disponible",
                    f"Hay una nueva versión de Deno disponible.\n\n"
                    f"Versión Actual: {local_deno_version}\n"
                    f"Versión Nueva: {latest_deno_version}\n\n"
                    "¿Deseas actualizar ahora?"
                )
                self.lift() 
                if user_response:
                    should_download_deno = True
            else:
                self.single_tab.deno_status_label.configure(text=f"Deno: {local_deno_version} \n(Actualizado)")
                messagebox.showinfo("Deno", "Ya tienes la última versión de Deno instalada.")

        if should_download_deno:
            if not deno_download_url:
                messagebox.showerror("Error", "No se pudo obtener la URL de descarga para Deno.")
                return

            self.single_tab.update_setup_download_progress('deno', f"Iniciando descarga de Deno {latest_deno_version}...", 0.01)
            from src.core.setup import download_and_install_deno 

            def download_deno_task():
                success = download_and_install_deno(latest_deno_version, deno_download_url, 
                    lambda text, val: self.single_tab.update_setup_download_progress('deno', text, val)) 
                if success:
                    deno_bin_path = os.path.join(BIN_DIR, "deno")
                    if deno_bin_path not in os.environ['PATH']:
                        os.environ['PATH'] = deno_bin_path + os.pathsep + os.environ['PATH']
                    self.after(0, lambda: self.single_tab.deno_status_label.configure(text=f"Deno: {latest_deno_version} \n(Instalado)")) 
                    self.after(0, self.single_tab.update_setup_download_progress, 'deno', f"✅ Deno {latest_deno_version} instalado.", 100)
                else:
                    self.after(0, self.single_tab.update_setup_download_progress, 'deno', "Falló la descarga de Deno.", 0)

            threading.Thread(target=download_deno_task, daemon=True).start()

    def _show_window_when_ready(self):
        """
        Muestra la ventana principal cuando todo está listo.
        Previene el parpadeo negro inicial.
        """
        try:
            # Forzar actualización de la geometría
            self.update_idletasks()
            
            # Mostrar la ventana principal
            self.deiconify()
            
            # 1. Cerrar la Splash Screen AHORA
            if self.splash_screen:
                self.splash_screen.destroy()
                self.splash_screen = None
            
            # (Ya no necesitamos reasignar el root aquí, lo hicimos en __init__)

            # Llevar al frente
            self.lift()
            self.focus_force()
            
            print("DEBUG: ✅ Ventana principal mostrada y Splash cerrado")
            
        except Exception as e:
            if self.splash_screen:
                try: self.splash_screen.destroy()
                except: pass
            print(f"ERROR mostrando ventana: {e}")
            self.deiconify()

    def on_poppler_check_complete(self, status_info):
        """Callback que maneja la comprobación MANUAL de Poppler."""
        self.single_tab.update_poppler_button.configure(state="normal", text="Buscar Actualizaciones de Poppler")

        status = status_info.get("status")
        if status == "error":
            messagebox.showerror("Error Crítico de Poppler", status_info.get("message"))
            return

        local_version = status_info.get("local_poppler_version") or "No encontrado"
        latest_version = status_info.get("latest_poppler_version")
        download_url = status_info.get("poppler_download_url")
        poppler_exists = status_info.get("poppler_path_exists")
        should_download = False

        if not poppler_exists:
            print("INFO: Comprobación manual de Poppler. No está instalado.")
            user_response = messagebox.askyesno(
                "Poppler no está instalado",
                f"No se encontró Poppler. Es necesario para procesar imágenes y PDFs.\n\n"
                f"Versión más reciente disponible: {latest_version}\n\n"
                "¿Deseas descargarlo e instalarlo ahora?"
            )
            self.lift()
            if user_response: should_download = True
            else: self.single_tab.poppler_status_label.configure(text=f"Poppler: {local_version} \n(Instalación cancelada)")
        else:
            # Lógica simple de comparación de strings para Poppler (sus tags son vXX.XX.X-X)
            update_available = local_version != latest_version
            
            if update_available:
                user_response = messagebox.askyesno(
                    "Actualización de Poppler Disponible",
                    f"Hay una nueva versión de Poppler disponible.\n\n"
                    f"Versión Actual: {local_version}\n"
                    f"Versión Nueva: {latest_version}\n\n"
                    "¿Deseas actualizar ahora?"
                )
                self.lift()
                if user_response: should_download = True
            else:
                self.single_tab.poppler_status_label.configure(text=f"Poppler: {local_version} \n(Actualizado)")
                messagebox.showinfo("Poppler", "Ya tienes la última versión de Poppler instalada.")

        if should_download:
            if not download_url:
                messagebox.showerror("Error", "No se pudo obtener la URL de descarga para Poppler.")
                return

            self.single_tab.update_setup_download_progress('poppler', f"Iniciando descarga de Poppler {latest_version}...", 0.01)
            from src.core.setup import download_and_install_poppler 

            def download_task():
                success = download_and_install_poppler(latest_version, download_url, 
                    lambda text, val: self.single_tab.update_setup_download_progress('poppler', text, val)) 
                if success:
                    poppler_bin_path = os.path.join(BIN_DIR, "poppler")
                    if poppler_bin_path not in os.environ['PATH']:
                        os.environ['PATH'] = poppler_bin_path + os.pathsep + os.environ['PATH']
                    self.after(0, lambda: self.single_tab.poppler_status_label.configure(text=f"Poppler: {latest_version} \n(Instalado)")) 
                    self.after(0, self.single_tab.update_setup_download_progress, 'poppler', f"✅ Poppler {latest_version} instalado.", 100)
                else:
                    self.after(0, self.single_tab.update_setup_download_progress, 'poppler', "Falló la descarga de Poppler.", 0)

            threading.Thread(target=download_task, daemon=True).start()

    def on_inkscape_check_complete(self, status_info):
        """Callback tras verificar Inkscape."""
        self.single_tab.check_inkscape_button.configure(state="normal", text="Verificar Inkscape")
        
        if status_info.get("status") == "error":
            self.single_tab.inkscape_status_label.configure(text="Inkscape: Error al verificar")
            print(f"ERROR Inkscape: {status_info.get('message')}")
            return

        exists = status_info.get("exists")
        if exists:
            # Verde o texto normal indicando éxito
            self.single_tab.inkscape_status_label.configure(
                text="Inkscape: Detectado ✅\n(Manual)"
            )
            self.single_tab.check_inkscape_button.configure(state="disabled", text="Instalado")
        else:
            # Rojo o aviso
            self.single_tab.inkscape_status_label.configure(
                text="Inkscape: No encontrado ❌\n(Requerido para vectores)"
            )

    def on_ghostscript_check_complete(self, status_info):
        """Callback tras verificar Ghostscript."""
        self.single_tab.check_ghostscript_button.configure(state="normal", text="Verificar Ghostscript")
        
        if status_info.get("status") == "error":
            self.single_tab.ghostscript_status_label.configure(text="Ghostscript: Error al verificar")
            print(f"ERROR Ghostscript: {status_info.get('message')}")
            return

        exists = status_info.get("exists")
        if exists:
            # Texto verde/normal
            self.single_tab.ghostscript_status_label.configure(
                text="Ghostscript: Detectado ✅\n(Manual)"
            )
            self.single_tab.check_ghostscript_button.configure(state="disabled", text="Instalado")
        else:
            # Texto de aviso
            self.single_tab.ghostscript_status_label.configure(
                text="Ghostscript: No encontrado ❌\n(Requerido para EPS/AI)"
            )

    def update_setup_progress(self, text, value):
        """
        Actualiza la ventana emergente de carga (LoadingWindow).
        Recibe texto y valor (0-100).
        """
        # Verificar que la ventana de carga exista antes de actualizarla
        if hasattr(self, 'loading_window') and self.loading_window and self.loading_window.winfo_exists():
            # Usamos lambda para asegurar que se ejecute en el hilo de la UI
            self.after(0, lambda: self.loading_window.update_progress(text, value / 100.0))
        
        # Si llega al 100%, cerrar
        if value >= 100:
            self.after(500, self.on_setup_complete)

    def on_setup_complete(self):
        """
        Se ejecuta cuando la configuración inicial (hilos) ha terminado.
        Cierra la ventana de carga y habilita la UI principal.
        """
        # 1. Gestionar la ventana de carga
        if hasattr(self, 'loading_window') and self.loading_window and self.loading_window.winfo_exists():
            if not self.loading_window.error_state:
                self.loading_window.update_progress("Configuración completada.", 1.0)
                # Dar un momento para leer "Completado" antes de cerrar
                self.after(800, self.loading_window.destroy)
            else:
                # Si hubo error crítico, quizás quieras dejarla abierta, 
                # pero por defecto la cerramos para no bloquear.
                self.loading_window.destroy()

        # 2. Habilitar la ventana principal
        self.attributes('-disabled', False)
        self.lift()
        self.focus_force()

        # 3. Aplicar configuraciones guardadas a la UI de la pestaña Single
        # (Como la lógica ahora está en MainWindow, debemos empujar los datos a single_tab)
        try:
            # Rutas
            self.single_tab.output_path_entry.delete(0, 'end')
            self.single_tab.output_path_entry.insert(0, self.default_download_path)
            
            # Cookies
            self.single_tab.cookie_mode_menu.set(self.cookies_mode_saved)
            if self.cookies_path:
                self.single_tab.cookie_path_entry.delete(0, 'end')
                self.single_tab.cookie_path_entry.insert(0, self.cookies_path)
            
            # Navegador
            self.single_tab.browser_var.set(self.selected_browser_saved)
            self.single_tab.browser_profile_entry.delete(0, 'end')
            self.single_tab.browser_profile_entry.insert(0, self.browser_profile_saved)
            
            # Refrescar visibilidad de opciones de cookies
            self.single_tab.on_cookie_mode_change(self.cookies_mode_saved)

            # Recodificación
            if self.recode_settings.get("keep_original", True):
                self.single_tab.keep_original_checkbox.select()
            else:
                self.single_tab.keep_original_checkbox.deselect()

            self.single_tab.recode_video_checkbox.deselect()
            self.single_tab.recode_audio_checkbox.deselect()
            self.single_tab._toggle_recode_panels()
            
        except Exception as e:
            print(f"ADVERTENCIA: Error al restaurar configuración en UI: {e}")

        # 4. Detección final de códecs (si no se ha hecho)
        self.ffmpeg_processor.run_detection_async(self.on_ffmpeg_detection_complete)

    # ==========================================
    # ✅ NUEVA FUNCIÓN: Router de Archivos Adobe
    # ==========================================
    def handle_adobe_files(self, file_paths):
        """
        Clasifica y envía los archivos recibidos a la pestaña correcta.
        """
        # 1. Normalizar rutas y verificar existencia
        valid_paths = [os.path.normpath(p) for p in file_paths if os.path.exists(p)]
        
        if not valid_paths:
            print("ADVERTENCIA: Ninguno de los archivos recibidos existe.")
            return

        images = []
        media = [] # Video y Audio

        # 2. Clasificar
        # Obtenemos extensiones de imagen de la pestaña (si existe) o usamos un set básico
        img_exts = self.image_tab.COMPATIBLE_EXTENSIONS if hasattr(self, 'image_tab') else ('.png', '.jpg', '.jpeg')
        
        for path in valid_paths:
            ext = os.path.splitext(path)[1].lower()
            
            # Es imagen?
            if ext in img_exts:
                images.append(path)
            # Es video o audio? (Usamos las constantes globales de la app)
            elif ext.lstrip('.') in self.VIDEO_EXTENSIONS or ext.lstrip('.') in self.AUDIO_EXTENSIONS:
                media.append(path)

        # 3. Enrutar IMÁGENES -> Herramientas de Imagen
        if images:
            print(f"INFO: Enviando {len(images)} imágenes a Herramientas de Imagen.")
            self.tab_view.set("Herramientas de Imagen")
            self.image_tab._process_imported_files(images)
            
            # Si SOLO había imágenes, terminamos aquí
            if not media:
                return

        # 4. Enrutar MEDIA (Video/Audio)
        if media:
            count = len(media)
            
            if count == 1:
                # CASO A: 1 Archivo -> Proceso Único
                print(f"INFO: Enviando 1 archivo a Proceso Único: {media[0]}")
                self.tab_view.set("Proceso Único")
                # Llamamos a la nueva función pública que crearemos en el Paso 2
                self.single_tab.import_local_file_from_path(media[0])
                
            else:
                # CASO B: 2+ Archivos -> Proceso por Lotes
                print(f"INFO: Enviando {count} archivos a Proceso por Lotes.")
                self.tab_view.set("Proceso por Lotes")
                # Usamos la función existente que maneja Drops
                self.batch_tab._handle_dropped_batch_files(media)
        
        # Traer ventana al frente
        self.deiconify()
        self.lift()
        self.focus_force()