import sys
import os
import subprocess
import multiprocessing
import tempfile  
import atexit   
import tkinter as tk 
import pillow_avif

from tkinter import messagebox
from PIL import Image, ImageTk

APP_VERSION = "1.3.1"

if getattr(sys, 'frozen', False):
    PROJECT_ROOT = os.path.dirname(sys.executable)
else:
    PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

BIN_DIR = os.path.join(PROJECT_ROOT, "bin")
FFMPEG_BIN_DIR = os.path.join(BIN_DIR, "ffmpeg")
DENO_BIN_DIR = os.path.join(BIN_DIR, "deno")
POPPLER_BIN_DIR = os.path.join(BIN_DIR, "poppler")
INKSCAPE_BIN_DIR = os.path.join(BIN_DIR, "inkscape")
GHOSTSCRIPT_BIN_DIR = os.path.join(BIN_DIR, "ghostscript")

# --- NUEVO: Rutas para Modelos de IA ---
MODELS_DIR = os.path.join(BIN_DIR, "models")
REMBG_MODELS_DIR = os.path.join(MODELS_DIR, "rembg")
UPSCALING_DIR = os.path.join(MODELS_DIR, "upscaling")

# Configurar variable de entorno para que rembg use nuestra carpeta
os.environ["U2NET_HOME"] = REMBG_MODELS_DIR

class SplashScreen:
    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True) # Quita bordes
        
        # Configuración visual
        bg_color = "#2B2B2B"
        text_color = "#FFFFFF"
        self.root.configure(bg=bg_color)
        
        # Dimensiones
        width = 350  # Un poco más ancha para que quepa el icono y la versión
        height = 100
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width // 2) - (width // 2)
        y = (screen_height // 2) - (height // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        
        # --- CARGAR ICONO ---
        self.tk_image = None
        try:
            # Buscar la ruta del icono (funciona en dev y exe)
            base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
            icon_path = os.path.join(base_path, "DowP-icon.ico")
            
            if os.path.exists(icon_path):
                # Cargar y redimensionar con Pillow (Alta calidad)
                pil_img = Image.open(icon_path).resize((40, 40), Image.Resampling.LANCZOS)
                self.tk_image = ImageTk.PhotoImage(pil_img)
                
                # También ponerlo en la barra de tareas (aunque no tenga borde)
                self.root.iconbitmap(icon_path)
        except Exception as e:
            print(f"No se pudo cargar el icono en Splash: {e}")

        # --- ETIQUETA PRINCIPAL (Icono + Texto) ---
        main_label = tk.Label(
            self.root, 
            text=f"Iniciando DowP v{APP_VERSION}", # <--- Texto con versión
            image=self.tk_image,                   # <--- Imagen
            compound="left",                       # <--- Imagen a la IZQUIERDA del texto
            padx=15,                               # Espacio extra
            font=("Segoe UI", 14, "bold"),
            bg=bg_color, 
            fg=text_color
        )
        main_label.pack(expand=True, fill="both", pady=(15, 0))
        
        # Etiqueta de Estado
        self.status_label = tk.Label(
            self.root, 
            text="Cargando...", 
            font=("Segoe UI", 9),
            bg=bg_color, 
            fg="#AAAAAA"
        )
        self.status_label.pack(side="bottom", pady=(0, 15))
        
        self.root.update()

    def update_status(self, text):
        if self.root:
            self.status_label.config(text=text)
            self.root.update()

    def destroy(self):
        if self.root:
            self.root.destroy()
            self.root = None
class SingleInstance:
    def __init__(self):
        self.lockfile = os.path.join(tempfile.gettempdir(), 'dowp.lock')
        if os.path.exists(self.lockfile):
            try:
                with open(self.lockfile, 'r') as f:
                    pid = int(f.read())
                if self._is_pid_running(pid):
                    messagebox.showwarning("DowP ya está abierto",
                                           f"Ya hay una instancia de DowP en ejecución (Proceso ID: {pid}).\n\n"
                                           "Por favor, busca la ventana existente.")
                    sys.exit(1)
                else:
                    print("INFO: Se encontró un archivo de cerrojo obsoleto. Eliminándolo.")
                    os.remove(self.lockfile)
            except Exception as e:
                print(f"ADVERTENCIA: No se pudo verificar el archivo de cerrojo. Eliminándolo. ({e})")
                try:
                    os.remove(self.lockfile)
                except OSError:
                    pass
        with open(self.lockfile, 'w') as f:
            f.write(str(os.getpid()))
        atexit.register(self.cleanup)

    def _is_pid_running(self, pid):
        """
        Comprueba si un proceso con un PID dado está corriendo Y si
        coincide con el nombre de este ejecutable.
        """
        try:
            if sys.platform == "win32":
                # Obtenemos el nombre del ejecutable actual (ej: "dowp.exe" o "python.exe")
                image_name = os.path.basename(sys.executable)
                
                # Comando de tasklist MEJORADO:
                # Filtra por PID Y por nombre de imagen.
                command = ['tasklist', '/fi', f'PID eq {pid}', '/fi', f'IMAGENAME eq {image_name}']
                
                # Usamos creationflags=0x08000000 para (CREATE_NO_WINDOW) y evitar que aparezca una consola
                output = subprocess.check_output(command, 
                                                 stderr=subprocess.STDOUT, 
                                                 text=True, 
                                                 creationflags=0x08000000)
                
                # Si el proceso (PID + Nombre) se encuentra, el PID estará en la salida.
                return str(pid) in output
            else: 
                try:
                    # 1. Comprobación rápida de existencia del PID
                    os.kill(pid, 0)
                    
                    # 2. Si existe, comprobar la identidad del proceso
                    expected_name = os.path.basename(sys.executable)
                    command = ['ps', '-p', str(pid), '-o', 'comm=']
                    
                    output = subprocess.check_output(command, 
                                                     stderr=subprocess.STDOUT, 
                                                     text=True)
                    
                    process_name = output.strip()
                    
                    # Compara el nombre del proceso (ej: 'python3' o 'dowp')
                    return process_name == expected_name
                    
                except (OSError, subprocess.CalledProcessError):
                    # OSError: "No such process" (el PID no existe)
                    # CalledProcessError: 'ps' falló
                    return False
        except (subprocess.CalledProcessError, FileNotFoundError):
            # CalledProcessError: Ocurre si el PID no existe (en Windows)
            # FileNotFoundError: tasklist/ps no encontrado (muy raro)
            return False
        except Exception as e:
            # Captura cualquier otro error inesperado
            print(f"Error inesperado en _is_pid_running: {e}")
            return False
        
    def cleanup(self):
        """Borra el archivo de cerrojo al cerrar."""
        try:
            if os.path.exists(self.lockfile):
                os.remove(self.lockfile)
        except Exception as e:
            print(f"ADVERTENCIA: No se pudo limpiar el archivo de cerrojo: {e}")

if __name__ == "__main__":
    # 1. Mostrar Splash INMEDIATAMENTE
    splash = SplashScreen()
    splash.update_status("Verificando instancia única...")

    SingleInstance()
    multiprocessing.freeze_support()

    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)

    # 2. Actualizar estado mientras configuras el entorno
    splash.update_status("Configurando entorno y rutas...")

    # Añadir el directorio 'bin' principal
    if os.path.isdir(BIN_DIR) and BIN_DIR not in os.environ['PATH']:
        os.environ['PATH'] = BIN_DIR + os.pathsep + os.environ['PATH']
    
    # Añadir el subdirectorio de FFmpeg
    if os.path.isdir(FFMPEG_BIN_DIR) and FFMPEG_BIN_DIR not in os.environ['PATH']:
        os.environ['PATH'] = FFMPEG_BIN_DIR + os.pathsep + os.environ['PATH']

    # Añadir el subdirectorio de Deno 
    if os.path.isdir(DENO_BIN_DIR) and DENO_BIN_DIR not in os.environ['PATH']:
        os.environ['PATH'] = DENO_BIN_DIR + os.pathsep + os.environ['PATH']

    # Añadir el subdirectorio de Poppler
    if os.path.isdir(POPPLER_BIN_DIR) and POPPLER_BIN_DIR not in os.environ['PATH']:
        os.environ['PATH'] = POPPLER_BIN_DIR + os.pathsep + os.environ['PATH']

    # Añadir Inkscape al PATH (para tu instalación manual)
    if os.path.isdir(INKSCAPE_BIN_DIR) and INKSCAPE_BIN_DIR not in os.environ['PATH']:
        print(f"INFO: Añadiendo Inkscape al PATH: {INKSCAPE_BIN_DIR}")
        os.environ['PATH'] = INKSCAPE_BIN_DIR + os.pathsep + os.environ['PATH']

    # Añadir el subdirectorio de Ghostscript (para .eps y .ai)
    if os.path.isdir(GHOSTSCRIPT_BIN_DIR) and GHOSTSCRIPT_BIN_DIR not in os.environ['PATH']:
        os.environ['PATH'] = GHOSTSCRIPT_BIN_DIR + os.pathsep + os.environ['PATH']

    print("Iniciando la aplicación...")
    launch_target = sys.argv[1] if len(sys.argv) > 1 else None
    
    # 3. Actualizar justo antes de la carga pesada
    splash.update_status("Cargando módulos e interfaz...")
    
    # Aquí ocurre la "pausa" de carga, pero el usuario verá la ventana flotante
    from src.gui.main_window import MainWindow 
    
    # 4. Pasar la referencia 'splash' a la ventana principal
    app = MainWindow(launch_target=launch_target, 
                     project_root=PROJECT_ROOT, 
                     poppler_path=POPPLER_BIN_DIR,
                     inkscape_path=INKSCAPE_BIN_DIR,
                     splash_screen=splash,
                     app_version=APP_VERSION)
    
    app.mainloop()