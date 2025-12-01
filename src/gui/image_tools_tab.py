import customtkinter as ctk
import queue
import os
import sys
import threading
import tkinter
import tempfile         
import requests         
import time  
import yt_dlp    
import time      
import gc
import uuid
import webbrowser
import subprocess

from urllib.parse import urlparse 
from PIL import ImageGrab, Image, ImageTk  
from tkinter import Menu, messagebox
from tkinter import Menu
from customtkinter import filedialog
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.core.exceptions import UserCancelledError
from .dialogs import Tooltip, MultiPageDialog, ManualDownloadDialog
from src.core.image_converter import ImageConverter
from src.core.image_processor import ImageProcessor
from src.core.setup import get_remote_file_size, format_size
from src.core.constants import (
    REMBG_MODEL_FAMILIES, REALESRGAN_MODELS, WAIFU2X_MODELS, REALSR_MODELS, SRMD_MODELS,
    IMAGE_RASTER_FORMATS, IMAGE_RAW_FORMATS
)
from main import REMBG_MODELS_DIR, MODELS_DIR, UPSCALING_DIR

try:
    from tkinterdnd2 import DND_FILES
except ImportError:
    print("ERROR: tkinterdnd2 no encontrado en image_tools_tab")
    DND_FILES = None

class InteractiveImageViewer(ctk.CTkCanvas):
    """
    Visor de imágenes avanzado con soporte para Zoom (Rueda) y Paneo (Clic Izquierdo).
    Mantiene la resolución original para inspección de calidad.
    """
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        
        # Configuración visual para integrarse con el tema oscuro
        self.configure(bg="#1D1D1D", highlightthickness=0)
        
        # Estado interno
        self.original_image = None  # La imagen PIL en resolución completa
        self.tk_image = None        # Referencia para evitar garbage collection
        
        # Transformación
        self.scale = 1.0
        self.pan_x = 0
        self.pan_y = 0
        
        # Variables para arrastre
        self._drag_data = {"x": 0, "y": 0}
        
        # --- Bindings (Eventos) ---
        
        # Paneo (Clic izquierdo y arrastrar)
        self.bind("<ButtonPress-1>", self._on_drag_start)
        self.bind("<B1-Motion>", self._on_drag_move)
        
        # Zoom (Rueda del mouse) - Soporte multiplataforma
        self.bind("<MouseWheel>", self._on_mouse_wheel) # Windows/MacOS
        self.bind("<Button-4>", self._on_mouse_wheel)   # Linux Subir
        self.bind("<Button-5>", self._on_mouse_wheel)   # Linux Bajar
        
        # Redibujar al cambiar tamaño de ventana
        self.bind("<Configure>", self._on_resize)

    def load_image(self, image_source):
        """
        Carga una imagen.
        Args:
            image_source: Puede ser un objeto PIL.Image o una ruta de archivo (str).
        """
        # Limpiar canvas
        self.delete("all")
        self.original_image = None
        
        if not image_source:
            return

        try:
            # Si es una ruta, cargarla (para obtener full res)
            if isinstance(image_source, str):
                if os.path.exists(image_source):
                    self.original_image = Image.open(image_source)
            # Si es un objeto imagen, usarlo directamente
            elif isinstance(image_source, Image.Image):
                self.original_image = image_source
            
            if self.original_image:
                # Resetear vista
                self.pan_x = 0
                self.pan_y = 0
                self.fit_image() # Ajustar inicial
        except Exception as e:
            print(f"ERROR InteractiveImageViewer: No se pudo cargar la imagen: {e}")

    def fit_image(self):
        """Ajusta la imagen para que quepa completamente en el visor (Zoom to Fit)"""
        if not self.original_image: return
        
        # ✅ CORRECCIÓN: Forzar actualización de geometría antes de leer dimensiones
        self.update_idletasks()
        
        # Obtener dimensiones del canvas (o usar defaults si aún no se dibuja)
        cw = self.winfo_width() or 400
        ch = self.winfo_height() or 300
        
        # ✅ VALIDACIÓN: Si el canvas todavía no tiene tamaño real, usar defaults razonables
        if cw < 50 or ch < 50:
            print("DEBUG: Canvas aún no renderizado, usando dimensiones default")
            cw, ch = 400, 300
        
        iw, ih = self.original_image.size
        
        # Calcular escala para ajustar
        scale_w = cw / iw
        scale_h = ch / ih
        self.scale = min(scale_w, scale_h) * 0.95  # 95% para dejar un pequeño margen
        
        # Centrar
        new_w = int(iw * self.scale)
        new_h = int(ih * self.scale)
        self.pan_x = (cw - new_w) / 2
        self.pan_y = (ch - new_h) / 2
        
        print(f"DEBUG: fit_image() → Canvas: {cw}×{ch}, Imagen: {iw}×{ih}, Escala: {self.scale:.2f}, Pan: ({self.pan_x:.0f}, {self.pan_y:.0f})")
        
        self._redraw()

    def _on_drag_start(self, event):
        """Inicia el arrastre"""
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y
        self.configure(cursor="fleur") # Cambiar cursor a 'mover'

    def _on_drag_move(self, event):
        """Calcula el desplazamiento"""
        if not self.original_image: return
        
        dx = event.x - self._drag_data["x"]
        dy = event.y - self._drag_data["y"]
        
        self.pan_x += dx
        self.pan_y += dy
        
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y
        
        self._redraw()
        
    def _on_mouse_wheel(self, event):
        """Maneja el zoom centrado en el cursor"""
        if not self.original_image: return
        
        # Determinar dirección del scroll
        if event.num == 5 or event.delta < 0:
            scale_factor = 0.9 # Alejar
        else:
            scale_factor = 1.1 # Acercar
            
        # Coordenadas del mouse (punto fijo del zoom)
        mouse_x = event.x
        mouse_y = event.y
        
        # Calcular qué punto de la imagen está bajo el mouse ANTES del zoom
        # Fórmula: img_x = (screen_x - pan_x) / current_scale
        img_x = (mouse_x - self.pan_x) / self.scale
        img_y = (mouse_y - self.pan_y) / self.scale
        
        # Aplicar nuevo zoom
        new_scale = self.scale * scale_factor
        
        # Límites de seguridad (evitar zoom infinito o microscópico)
        if new_scale < 0.01 or new_scale > 50.0:
            return
            
        self.scale = new_scale
        
        # Recalcular pan para mantener el punto bajo el mouse estático
        # Fórmula: new_pan = screen - (img * new_scale)
        self.pan_x = mouse_x - (img_x * self.scale)
        self.pan_y = mouse_y - (img_y * self.scale)
        
        self._redraw()

    def _on_resize(self, event):
        """Reajusta si cambia el tamaño de la ventana"""
        if self.original_image and self.tk_image is None:
            self.fit_image()
        else:
            self._redraw()

    def _redraw(self):
        """Dibuja la imagen redimensionada y recortada según el estado actual"""
        if not self.original_image: return
        
        self.delete("all")
        
        cw = self.winfo_width()
        ch = self.winfo_height()
        
        # Dimensiones finales teóricas
        final_w = int(self.original_image.width * self.scale)
        final_h = int(self.original_image.height * self.scale)
        
        # Optimización: Determinar la región visible (Viewport)
        # Inversa: (0,0) pantalla -> (-pan_x/scale, -pan_y/scale) imagen
        left = max(0, -self.pan_x / self.scale)
        top = max(0, -self.pan_y / self.scale)
        right = min(self.original_image.width, (cw - self.pan_x) / self.scale)
        bottom = min(self.original_image.height, (ch - self.pan_y) / self.scale)
        
        # Si no hay nada visible, salir
        if right <= left or bottom <= top:
            return

        # Coordenadas para recortar (Crop Box)
        crop_box = (int(left), int(top), int(right), int(bottom))
        
        # Tamaño en pantalla de ese recorte
        display_w = int((right - left) * self.scale)
        display_h = int((bottom - top) * self.scale)
        
        # Posición en pantalla donde dibujar
        screen_x = max(0, self.pan_x)
        screen_y = max(0, self.pan_y)
        
        if display_w > 0 and display_h > 0:
            # 1. Recortar la parte visible de la imagen original (Rápido)
            try:
                region = self.original_image.crop(crop_box)
                
                # 2. Redimensionar solo esa parte (Rápido)
                # Usamos NEAREST si está muy cerca (pixel art look) o BILINEAR para suavidad
                resample_method = Image.Resampling.NEAREST if self.scale > 3.0 else Image.Resampling.BILINEAR
                resized_region = region.resize((display_w, display_h), resample_method)
                
                # 3. Convertir a Tkinter y dibujar
                self.tk_image = ImageTk.PhotoImage(resized_region)
                self.create_image(screen_x, screen_y, anchor="nw", image=self.tk_image)
                
            except Exception as e:
                print(f"Error redibujando: {e}")
        
        self.configure(cursor="arrow") # Restaurar cursor

class ComparisonViewer(ctk.CTkCanvas):
    """
    Visor de comparación avanzado (Antes/Después) con Zoom y Paneo.
    - Rueda: Zoom
    - Clic en línea blanca: Mover Slider
    - Clic derecho (o Espacio + Clic): Paneo (Mover imagen)
    """
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(bg="#1D1D1D", highlightthickness=0)

        # Datos de imágenes (PIL)
        self.img_before = None # Original
        self.img_after = None  # Resultado
        self.tk_image_left = None
        self.tk_image_right = None
        self.checker_tile = None # Patrón de fondo

        # Estado de Vista
        self.scale = 1.0
        self.pan_x = 0
        self.pan_y = 0
        self.slider_pos = 0.5 # 0.0 a 1.0 (50% inicial)
        
        # Estado de Interacción
        self._drag_data = {"x": 0, "y": 0, "mode": None} # mode: 'slider' o 'pan'
        self.is_space_held = False

        # --- Bindings ---
        # Mouse
        self.bind("<ButtonPress-1>", self._on_left_down)
        self.bind("<B1-Motion>", self._on_left_drag)
        self.bind("<ButtonRelease-1>", self._on_left_up)
        
        self.bind("<ButtonPress-3>", self._on_right_down) # Paneo alternativo
        self.bind("<B3-Motion>", self._on_right_drag)

        # Zoom
        self.bind("<MouseWheel>", self._on_zoom)
        self.bind("<Button-4>", self._on_zoom)
        self.bind("<Button-5>", self._on_zoom)

        # Teclado (Espacio para mano)
        self.bind("<KeyPress-space>", self._on_space_down)
        self.bind("<KeyRelease-space>", self._on_space_up)
        
        # Redimensionar ventana
        self.bind("<Configure>", self._on_resize)
        
        # Foco para teclado
        self.bind("<Enter>", lambda e: self.focus_set())

    def load_images(self, img_original, img_result):
        """Carga las imágenes PIL (deben ser del mismo tamaño o se redimensionarán)."""
        self.delete("all")
        
        if not img_original or not img_result: return

        # Asegurar que ambas tengan el mismo tamaño (usar el tamaño del resultado)
        w, h = img_result.size
        if img_original.size != (w, h):
            self.img_before = img_original.resize((w, h), Image.Resampling.LANCZOS)
        else:
            self.img_before = img_original
            
        self.img_after = img_result
        
        # Generar patrón de ajedrez pequeño para el fondo
        self._create_checker_pattern()

        # Ajustar zoom inicial para ver todo ("Fit")
        self.fit_to_window()

    def fit_to_window(self):
        """Resetea el zoom y centra la imagen."""
        if not self.img_after: return
        
        cw = self.winfo_width() or 400
        ch = self.winfo_height() or 300
        iw, ih = self.img_after.size
        
        scale_w = cw / iw
        scale_h = ch / ih
        self.scale = min(scale_w, scale_h) * 0.95
        
        new_w = iw * self.scale
        new_h = ih * self.scale
        
        self.pan_x = (cw - new_w) / 2
        self.pan_y = (ch - new_h) / 2
        self.slider_pos = 0.5
        self._redraw()

    def _create_checker_pattern(self):
        """Crea un patrón de ajedrez para transparencia."""
        from PIL import ImageDraw
        size = 20
        checker = Image.new("RGB", (size*2, size*2), (200, 200, 200))
        draw = ImageDraw.Draw(checker)
        draw.rectangle([0, 0, size, size], fill=(255, 255, 255))
        draw.rectangle([size, size, size*2, size*2], fill=(255, 255, 255))
        self.checker_tile = ImageTk.PhotoImage(checker)

    def _on_resize(self, event):
        if self.img_after and not self.tk_image_left:
            self.fit_to_window()
        else:
            self._redraw()

    # --- LÓGICA DE DIBUJADO (EL NÚCLEO) ---
    def _redraw(self):
        if not self.img_after: return
        self.delete("all")

        cw = self.winfo_width()
        ch = self.winfo_height()
        iw, ih = self.img_after.size

        # 1. Coordenadas de la imagen en pantalla
        # (pan_x, pan_y) es la esquina superior izquierda de la imagen
        
        # 2. Determinar la línea divisoria en pantalla
        # La línea está en: pan_x + (ancho_imagen_escalado * slider_pos)
        scaled_w = iw * self.scale
        scaled_h = ih * self.scale
        screen_slider_x = self.pan_x + (scaled_w * self.slider_pos)

        # 3. Optimización: Calcular Viewport (qué parte de la imagen original ver)
        # Inversa: pantalla -> imagen
        # left_img = (0 - pan_x) / scale
        
        # Coordenadas visibles en la imagen original
        vis_left = max(0, -self.pan_x / self.scale)
        vis_top = max(0, -self.pan_y / self.scale)
        vis_right = min(iw, (cw - self.pan_x) / self.scale)
        vis_bottom = min(ih, (ch - self.pan_y) / self.scale)

        if vis_right <= vis_left or vis_bottom <= vis_top:
            return # Nada visible

        # Dibujar Fondo Ajedrez (Tiles)
        # Tkinter tilea automáticamente si la imagen es menor que el area
        # Pero para simplificar y rendimiento, dibujamos un rectángulo gris de fondo
        self.create_rectangle(0, 0, cw, ch, fill="#1D1D1D", width=0)
        
        # --- DIBUJAR IMAGEN IZQUIERDA (RESULTADO / AFTER) ---
        # Se ve desde el borde izquierdo de la imagen (0) hasta el slider
        # Pero recortado por el viewport
        
        # Límite en coordenadas de imagen del slider
        slider_img_x = iw * self.slider_pos
        
        # El recorte de la izquierda va desde vis_left hasta min(vis_right, slider_img_x)
        left_crop_r = min(vis_right, slider_img_x)
        
        if left_crop_r > vis_left:
            crop_l = (vis_left, vis_top, left_crop_r, vis_bottom)
            region_l = self.img_after.crop(crop_l)
            
            # Escalar al tamaño de pantalla
            disp_w_l = int((left_crop_r - vis_left) * self.scale)
            disp_h_l = int((vis_bottom - vis_top) * self.scale)
            
            if disp_w_l > 0 and disp_h_l > 0:
                # Usar Nearest para zoom muy cercano (ver píxeles)
                method = Image.Resampling.NEAREST if self.scale > 2.0 else Image.Resampling.BILINEAR
                region_l = region_l.resize((disp_w_l, disp_h_l), method)
                
                self.tk_image_left = ImageTk.PhotoImage(region_l)
                
                # Posición en pantalla: pan_x + (vis_left * scale)
                pos_x = self.pan_x + (vis_left * self.scale)
                pos_y = self.pan_y + (vis_top * self.scale)
                
                self.create_image(pos_x, pos_y, anchor="nw", image=self.tk_image_left)

        # --- DIBUJAR IMAGEN DERECHA (ORIGINAL / BEFORE) ---
        # Va desde slider hasta el borde derecho
        
        right_crop_l = max(vis_left, slider_img_x)
        
        if vis_right > right_crop_l:
            crop_r = (right_crop_l, vis_top, vis_right, vis_bottom)
            region_r = self.img_before.crop(crop_r)
            
            disp_w_r = int((vis_right - right_crop_l) * self.scale)
            disp_h_r = int((vis_bottom - vis_top) * self.scale)
            
            if disp_w_r > 0 and disp_h_r > 0:
                method = Image.Resampling.NEAREST if self.scale > 2.0 else Image.Resampling.BILINEAR
                region_r = region_r.resize((disp_w_r, disp_h_r), method)
                
                self.tk_image_right = ImageTk.PhotoImage(region_r)
                
                pos_x = self.pan_x + (right_crop_l * self.scale)
                pos_y = self.pan_y + (vis_top * self.scale)
                
                self.create_image(pos_x, pos_y, anchor="nw", image=self.tk_image_right)

        # --- DIBUJAR LÍNEA DEL SLIDER ---
        # Solo si está dentro de la pantalla
        if 0 <= screen_slider_x <= cw:
            # Línea
            self.create_line(screen_slider_x, 0, screen_slider_x, ch, fill="white", width=2)
            # Manija (Círculo)
            cy = ch / 2
            self.create_oval(screen_slider_x-6, cy-6, screen_slider_x+6, cy+6, fill="white", outline="gray")
            
            # Etiquetas flotantes
            if self.scale > 0.5: # Solo si no está muy alejado
                self.create_text(screen_slider_x - 10, cy - 20, text="Resultado", fill="white", anchor="e", font=("Arial", 10, "bold"))
                self.create_text(screen_slider_x + 10, cy - 20, text="Original", fill="white", anchor="w", font=("Arial", 10, "bold"))

    # --- EVENTOS ---

    def _on_zoom(self, event):
        if not self.img_after: return
        
        if event.num == 5 or event.delta < 0:
            factor = 0.9
        else:
            factor = 1.1
            
        mouse_x = event.x
        mouse_y = event.y
        
        # Punto bajo el mouse antes del zoom
        img_x = (mouse_x - self.pan_x) / self.scale
        img_y = (mouse_y - self.pan_y) / self.scale
        
        new_scale = self.scale * factor
        if new_scale < 0.05 or new_scale > 50.0: return
        
        self.scale = new_scale
        self.pan_x = mouse_x - (img_x * self.scale)
        self.pan_y = mouse_y - (img_y * self.scale)
        self._redraw()

    def _on_left_down(self, event):
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y
        
        # Detectar si clicamos cerca del slider
        if not self.img_after: return
        iw = self.img_after.width
        screen_slider_x = self.pan_x + (iw * self.scale * self.slider_pos)
        
        # Umbral de detección del slider (15px)
        if abs(event.x - screen_slider_x) < 15 and not self.is_space_held:
            self._drag_data["mode"] = "slider"
            self.configure(cursor="sb_h_double_arrow")
        else:
            # Si mantenemos espacio, siempre es pan. Si no, y estamos lejos, también puede ser pan (opcional)
            # Aquí hacemos: Espacio = Pan, Clic lejos = Pan (como pediste)
            self._drag_data["mode"] = "pan"
            self.configure(cursor="fleur")

    def _on_left_drag(self, event):
        if not self.img_after: return
        
        dx = event.x - self._drag_data["x"]
        dy = event.y - self._drag_data["y"]
        
        if self._drag_data["mode"] == "pan":
            self.pan_x += dx
            self.pan_y += dy
        
        elif self._drag_data["mode"] == "slider":
            # Convertir dx de pantalla a porcentaje de imagen
            # dx_img = dx / scale
            # slider_delta = dx_img / img_width
            img_w_screen = self.img_after.width * self.scale
            if img_w_screen > 0:
                self.slider_pos += dx / img_w_screen
                self.slider_pos = max(0.0, min(1.0, self.slider_pos))
        
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y
        self._redraw()

    def _on_left_up(self, event):
        self._drag_data["mode"] = None
        if self.is_space_held:
            self.configure(cursor="hand2")
        else:
            self.configure(cursor="arrow")

    # Paneo alternativo con clic derecho
    def _on_right_down(self, event):
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y
        self.configure(cursor="fleur")

    def _on_right_drag(self, event):
        dx = event.x - self._drag_data["x"]
        dy = event.y - self._drag_data["y"]
        self.pan_x += dx
        self.pan_y += dy
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y
        self._redraw()

    def _on_space_down(self, event):
        if not self.is_space_held:
            self.is_space_held = True
            self.configure(cursor="hand2")

    def _on_space_up(self, event):
        self.is_space_held = False
        self.configure(cursor="arrow")

class ImageToolsTab(ctk.CTkFrame):
    """
    Pestaña de Herramientas de Imagen, diseñada para la conversión
    y procesamiento de lotes grandes de archivos.
    """

    # Extensiones de entrada compatibles
    COMPATIBLE_EXTENSIONS = (
        # Raster (Pillow)
        ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif", ".gif", ".avif",
        # Vectoriales
        ".pdf", ".svg", ".eps", ".ai", ".ps",
        # Otros
        ".psd", ".tga", ".jp2", ".ico",
        # --- NUEVO: Formatos RAW de cámara ---
        ".cr2", ".dng", ".arw", ".nef", ".orf", ".rw2", ".sr2", ".raf", ".cr3", ".pef"
    )
    
    # Colores de botones (copiados de tus otras pestañas para consistencia)
    PROCESS_BTN_COLOR = "#6F42C1"        
    PROCESS_BTN_HOVER = "#59369A"        
    DISABLED_TEXT_COLOR = "#D3D3D3"
    DISABLED_FG_COLOR = "#565b5f" 

    def __init__(self, master, app, poppler_path=None, inkscape_path=None): 
        super().__init__(master, fg_color="transparent")
        self.pack(expand=True, fill="both")
        
        self.app = app
        self.file_list_data = []

        # 🔧 NUEVO: Flag para sincronización con importación
        self.conversion_complete_event = threading.Event()

        # Crear la instancia del motor de procesamiento
        # --- NUEVO: Pasamos ffmpeg_path ---
        self.image_processor = ImageProcessor(
            poppler_path=poppler_path, 
            inkscape_path=inkscape_path,
            ffmpeg_path=self.app.ffmpeg_processor.ffmpeg_path
        )
        
        # Crear la instancia del conversor
        self.image_converter = ImageConverter(poppler_path=poppler_path,
                                            inkscape_path=inkscape_path,
                                            ffmpeg_processor=self.app.ffmpeg_processor)
        
        # Variable para rastrear la última miniatura solicitada
        self.last_preview_path = None
        
        # ⭐ Sistema de caché de miniaturas
        self.thumbnail_cache = {}
        self.thumbnail_queue = queue.Queue()
        self.active_thumbnail_thread = None
        self.thumbnail_lock = threading.Lock()

        self.temp_image_dir = self._get_temp_dir()
        self.is_analyzing_url = False
        self.last_processed_output_dir = None
        self.current_selected_output_path = None

        # --- 1. Diseño de la Rejilla Principal (3 Zonas) ---
        
        # Fila 0: Contenido principal (Izquierda 50%, Derecha 50%)
        self.grid_rowconfigure(0, weight=1)
        # Fila 1: Panel de Salida (Altura fija)
        self.grid_rowconfigure(1, weight=0)
        # Fila 2: Panel de Progreso (Altura fija)
        self.grid_rowconfigure(2, weight=0) 
        
        # ✅ CORRECCIÓN CRÍTICA: Pesos EXACTAMENTE iguales + sin minsize
        # El minsize puede causar desbalance si una columna crece más que la otra
        self.grid_columnconfigure(0, weight=1, uniform="cols")
        self.grid_columnconfigure(1, weight=1, uniform="cols")
        
        # --- 2. Crear los Paneles ---
        self._create_left_panel()
        self._create_right_panel()
        self._create_bottom_panel()
        self._create_progress_panel()

        # --- 3. Cargar Configuración Inicial ---
        self._initialize_ui_settings()

    # ==================================================================
    # --- CREACIÓN DE PANELES DE UI ---
    # ==================================================================

    def _create_left_panel(self):
        """Crea el panel izquierdo (40%) para la URL, botones y lista de archivos."""
        
        self.left_panel = ctk.CTkFrame(self)
        self.left_panel.grid(row=0, column=0, padx=(10, 5), pady=(10, 5), sticky="nsew")
        
        # Expandir la fila 2 (donde va la lista) para que ocupe el espacio vertical
        self.left_panel.grid_rowconfigure(2, weight=1) 
        self.left_panel.grid_columnconfigure(0, weight=1)

        # --- 1. Zona de URL (Fila 0) ---
        self.url_frame = ctk.CTkFrame(self.left_panel)
        self.url_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        self.url_frame.grid_columnconfigure(0, weight=1)
        
        self.url_entry = ctk.CTkEntry(self.url_frame, placeholder_text="Pegar URL de imagen o PDF...")
        self.url_entry.bind("<Button-3>", lambda e: self.create_entry_context_menu(self.url_entry))
        self.url_entry.grid(row=0, column=0, padx=(0, 5), pady=0, sticky="ew")

        self.analyze_button = ctk.CTkButton(
            self.url_frame, text="Añadir", width=80, 
            command=self._on_analyze_url
        )
        self.analyze_button.grid(row=0, column=1, padx=(0, 0), pady=0)

        # --- 2. Barra de Herramientas Unificada (Fila 1) ---
        self.buttons_frame = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        self.buttons_frame.grid(row=1, column=0, padx=10, pady=(0, 5), sticky="ew")
        
        # Configurar 4 columnas con peso igual
        self.buttons_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        # Botón 1: Importar (Con Menú)
        self.import_button = ctk.CTkButton(
            self.buttons_frame, 
            text="Importar ▼", 
            width=80,
            command=self._show_import_menu
        )
        self.import_button.grid(row=0, column=0, padx=(0, 3), sticky="ew")

        # Botón 2: Pegar
        self.paste_button = ctk.CTkButton(
            self.buttons_frame, 
            text="Pegar", 
            width=60,
            command=self._on_paste_list
        )
        self.paste_button.grid(row=0, column=1, padx=3, sticky="ew")
        
        # Botón 3: Limpiar
        self.clear_button = ctk.CTkButton(
            self.buttons_frame, 
            text="Limpiar", 
            width=60,
            command=self._on_clear_list
        )
        self.clear_button.grid(row=0, column=2, padx=3, sticky="ew")

        # Botón 4: Borrar (Rojo)
        self.delete_button = ctk.CTkButton(
            self.buttons_frame, 
            text="Borrar", 
            width=60,
            fg_color="#DC3545", 
            hover_color="#C82333",
            command=self._on_delete_selected, 
            state="disabled"
        )
        self.delete_button.grid(row=0, column=3, padx=(3, 0), sticky="ew")

        # --- 3. Zona de Lista de Archivos (Fila 2) ---
        # Frame contenedor que se expande
        self.list_frame = ctk.CTkFrame(self.left_panel)
        self.list_frame.grid(row=2, column=0, padx=10, pady=5, sticky="nsew")
        self.list_frame.grid_columnconfigure(0, weight=1)
        self.list_frame.grid_rowconfigure(0, weight=1)

        # Scrollbar Vertical
        self.file_list_scrollbar_y = ctk.CTkScrollbar(self.list_frame)
        self.file_list_scrollbar_y.grid(row=0, column=1, sticky="ns")
        
        # Scrollbar Horizontal
        self.file_list_scrollbar_x = ctk.CTkScrollbar(self.list_frame, orientation="horizontal")
        self.file_list_scrollbar_x.grid(row=1, column=0, sticky="ew")

        # Listbox Nativo
        self.file_list_box = tkinter.Listbox(
            self.list_frame,
            font=ctk.CTkFont(size=12),
            bg="#1D1D1D",
            fg="#FFFFFF",
            selectbackground="#1F6AA5",
            selectforeground="#FFFFFF",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground="#565B5E",
            activestyle="none",
            selectmode="extended",
            exportselection=False,
            yscrollcommand=self.file_list_scrollbar_y.set,
            xscrollcommand=self.file_list_scrollbar_x.set,
        )
        self.file_list_box.grid(row=0, column=0, sticky="nsew")

        # Conectar scrollbars
        self.file_list_scrollbar_y.configure(command=self.file_list_box.yview)
        self.file_list_scrollbar_x.configure(command=self.file_list_box.xview)

        # Etiqueta de "Arrastra aquí" (Empty State)
        self.drag_hint_label = ctk.CTkLabel(
            self.list_frame,
            text="Arrastra archivos o carpetas aquí\no usa 'Importar Archivos'",
            text_color="gray",
            bg_color="#1D1D1D",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.drag_hint_label.place(relx=0.5, rely=0.5, anchor="center")

        # Configurar Drag & Drop
        if DND_FILES:
            try:
                # Registrar lista y etiqueta
                self.file_list_box.drop_target_register(DND_FILES)
                self.file_list_box.dnd_bind('<<Drop>>', self._on_image_list_drop)
                
                self.drag_hint_label.drop_target_register(DND_FILES)
                self.drag_hint_label.dnd_bind('<<Drop>>', self._on_image_list_drop)
                
                print("DEBUG: Drag & Drop activado en la lista de imágenes")
            except Exception as e:
                print(f"ADVERTENCIA: No se pudo activar DnD en la lista: {e}")

        # Bindings
        self.file_list_box.bind("<ButtonRelease-1>", self._on_file_select)
        self.file_list_box.bind("<Up>", self._on_file_select)
        self.file_list_box.bind("<Down>", self._on_file_select)
        self.file_list_box.bind("<Prior>", self._on_file_select)
        self.file_list_box.bind("<Next>", self._on_file_select)
        self.file_list_box.bind("<Home>", self._on_file_select)
        self.file_list_box.bind("<End>", self._on_file_select)
        self.file_list_box.bind("<Button-3>", self._create_list_context_menu)
        self.file_list_box.bind("<Delete>", self._on_delete_selected)
        self.file_list_box.bind("<BackSpace>", self._on_delete_selected)

        # --- 4. Etiqueta de Conteo (Fila 3) ---
        self.list_status_label = ctk.CTkLabel(self.left_panel, text="0 archivos", font=ctk.CTkFont(size=11), text_color="gray")
        self.list_status_label.grid(row=3, column=0, padx=10, pady=(0, 5), sticky="w")

    def _create_right_panel(self):
        """Crea el panel derecho (60%) para el visor y las opciones."""
        
        self.right_panel = ctk.CTkFrame(self)
        self.right_panel.grid(row=0, column=1, padx=(5, 10), pady=(10, 5), sticky="nsew")

        # CORRECCIÓN: Usar proporciones para que el visor no sea gigante.
        # weight=2 (Visor) vs weight=3 (Opciones) da un reparto aprox de 40% / 60%
        self.right_panel.grid_rowconfigure(0, weight=2) 
        self.right_panel.grid_rowconfigure(1, weight=0) 
        self.right_panel.grid_rowconfigure(2, weight=3) 
        self.right_panel.grid_columnconfigure(0, weight=1)

        # --- 1. Zona de Visor (Fila 0) ---
        self.viewer_frame = ctk.CTkFrame(self.right_panel, fg_color="#1D1D1D")
        self.viewer_frame.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="nsew")
        
        # CAMBIO: Quitamos la configuración interna de grid, usaremos .place()
        self.viewer_frame.grid_propagate(False) 

        self.viewer_placeholder = ctk.CTkLabel(
            self.viewer_frame, 
            text="Selecciona un archivo de la lista para previsualizarlo",
            text_color="gray"
        )
        # CAMBIO: Usar place para centrar perfectamente
        self.viewer_placeholder.place(relx=0.5, rely=0.5, anchor="center")

        # --- 2. Zona de Título (Fila 1) ---
        self.title_frame = ctk.CTkFrame(self.right_panel)
        self.title_frame.grid(row=1, column=0, padx=10, pady=5, sticky="ew")
        self.title_frame.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(self.title_frame, text="Título:").grid(row=0, column=0, padx=(10, 5))
        self.title_entry = ctk.CTkEntry(self.title_frame, placeholder_text="Nombre del archivo de salida...")
        self.title_entry.bind("<Button-3>", lambda e: self.create_entry_context_menu(self.title_entry))
        
        # ✅ NUEVO: Guardar título al escribir (KeyRelease)
        self.title_entry.bind("<KeyRelease>", self._on_title_entry_change)
        
        self.title_entry.grid(row=0, column=1, padx=(0, 10), sticky="ew")

        # ✅ NUEVO: Botón Copiar Resultado
        self.copy_result_button = ctk.CTkButton(
            self.title_frame, 
            text="Copiar", 
            width=60, 
            state="disabled", # Nace deshabilitado
            command=self._copy_result_to_clipboard,
            fg_color="#555555", 
            hover_color="#444444"
        )
        self.copy_result_button.grid(row=0, column=2, padx=(0, 5), sticky="e")
        
        Tooltip(self.copy_result_button, "Copia la imagen procesada al portapapeles.", delay_ms=1000)

        # --- 3. Zona de Opciones (Fila 2) ---
        self.options_frame = ctk.CTkScrollableFrame(
            self.right_panel, 
            label_text="Opciones de Procesamiento"
        )
        self.options_frame.grid(row=2, column=0, padx=10, pady=(5, 10), sticky="nsew")
        self.options_frame.grid_columnconfigure(0, weight=1)
        
        
        # --- (INICIO DE LA CORRECCIÓN DE JERARQUÍA) ---
        
        # 3.1: Módulo "Cuadrito" Maestro de Formato
        # Usamos el color de fondo de las opciones para que se vea integrado
        self.format_master_frame = ctk.CTkFrame(self.options_frame, fg_color="#2B2B2B")
        self.format_master_frame.pack(fill="x", padx=5, pady=(5, 0))
        
        # 3.1a: Frame para el Menú (DENTRO del "cuadrito" maestro)
        self.format_menu_frame = ctk.CTkFrame(self.format_master_frame, fg_color="transparent")
        self.format_menu_frame.pack(fill="x", padx=5, pady=(5, 0)) # Padding interno
        self.format_menu_frame.grid_columnconfigure(1, weight=1) 

        self.format_label = ctk.CTkLabel(self.format_menu_frame, text="Formato de Salida:", width=120, anchor="w")
        self.format_label.grid(row=0, column=0, padx=(5, 5), pady=5, sticky="w") # Padding interno
        
        self.export_formats = [
            "No Convertir", 
            "PNG", "JPG", "WEBP", "AVIF", "PDF", "TIFF", "ICO", "BMP",
            "--- Video ---",
            ".mp4 (H.264)",
            ".mov (ProRes)",
            ".webm (VP9)",
            ".gif (Animado)"
        ]
        
        self.format_menu = ctk.CTkOptionMenu(
            self.format_menu_frame, 
            values=self.export_formats, 
            command=self._on_format_changed
        )
        self.format_menu.grid(row=0, column=1, padx=(0, 5), pady=5, sticky="ew") # Padding interno

        # --- NUEVO TOOLTIP ---
        Tooltip(self.format_menu, "Selecciona el formato de archivo final.\n• Nota: Formatos como JPG no soportan transparencia (se pondrá fondo blanco o el que elijas).", delay_ms=1000)

        # 3.1b: Contenedor de Opciones (DENTRO del "cuadrito" maestro)
        self.options_container = ctk.CTkFrame(self.format_master_frame, fg_color="transparent")
        self.options_container.pack(fill="x", expand=True, padx=5, pady=0, after=self.format_menu_frame)

        # 3.2: Separador (Sigue igual, entre los dos "cuadritos")
        ctk.CTkFrame(self.options_frame, height=2, fg_color="#333333").pack(fill="x", padx=10, pady=5)

        # 3.3: Módulo "Cuadrito" Maestro de Escalado (Sigue igual)
        self.resize_master_frame = ctk.CTkFrame(self.options_frame)
        self.resize_master_frame.pack(fill="x", padx=5, pady=(0, 5))
        self.resize_master_frame.grid_columnconfigure(0, weight=1)

        self.resize_checkbox = ctk.CTkCheckBox(
            self.resize_master_frame,
            text="Cambiar Tamaño (Escalar)",
            command=self._on_toggle_resize_frame
        )
        self.resize_checkbox.pack(fill="x", padx=10, pady=5)

        # --- NUEVO TOOLTIP ---
        Tooltip(self.resize_checkbox, "Redimensiona la imagen a una resolución específica (ej: 1920x1080).\nÚtil para aumentar el tamaño de archivos vectoriales antes de convertirlos.", delay_ms=1000)

        self.resize_options_frame = ctk.CTkFrame(self.resize_master_frame, fg_color="transparent")
        self.resize_options_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self.resize_options_frame, text="Preset de Escalado:").grid(row=0, column=0, padx=(10, 5), pady=5, sticky="w")
        self.resize_preset_menu = ctk.CTkOptionMenu(
            self.resize_options_frame,
            values=[
                "No escalar (Original)",
                "4K UHD (Máx: 3840×2160)",
                "2K QHD (Máx: 2560×1440)",
                "1080p FHD (Máx: 1920×1080)",
                "720p HD (Máx: 1280×720)",
                "480p SD (Máx: 854×480)",
                "Personalizado..."
            ],
            command=self._on_resize_preset_changed
        )
        self.resize_preset_menu.grid(row=0, column=1, padx=(0, 10), pady=5, sticky="ew")

        # Menú de interpolación (solo para raster)
        self.interpolation_frame = ctk.CTkFrame(self.resize_options_frame, fg_color="transparent")
        self.interpolation_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky="ew")
        self.interpolation_frame.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(self.interpolation_frame, text="Interpolación (Solo Rasters):").grid(row=0, column=0, padx=(10, 5), sticky="w")
        
        from src.core.constants import INTERPOLATION_METHODS
        self.interpolation_menu = ctk.CTkOptionMenu(
            self.interpolation_frame,
            values=list(INTERPOLATION_METHODS.keys())
        )
        self.interpolation_menu.set("Lanczos (Mejor Calidad)")
        self.interpolation_menu.grid(row=0, column=1, padx=(0, 10), sticky="ew")
        Tooltip(self.interpolation_menu, "Método para reescalar imágenes raster (PNG, JPG). No afecta vectoriales.", delay_ms=500)
        
        # Ajustar la row del custom frame
        self.resize_custom_frame = ctk.CTkFrame(self.resize_options_frame, fg_color="transparent")
        self.resize_custom_frame.grid(row=2, column=0, columnspan=2, padx=10, pady=5, sticky="ew")  # Cambiar de row=1 a row=2
        self.resize_custom_frame.grid_columnconfigure((1, 3), weight=1)

        ctk.CTkLabel(self.resize_custom_frame, text="Ancho:").grid(row=0, column=0, padx=(0, 5), sticky="e")
        self.resize_width_entry = ctk.CTkEntry(self.resize_custom_frame, width=80, placeholder_text="1920")
        self.resize_width_entry.grid(row=0, column=1, sticky="w")
        
        self.resize_aspect_lock = ctk.CTkCheckBox(
            self.resize_custom_frame, 
            text="",    
            width=28    
        )
        self.resize_aspect_lock.grid(row=0, column=2, padx=10, pady=5)
        self.resize_aspect_lock.select() 

        Tooltip(
            self.resize_aspect_lock, 
            text="Mantener Proporción", 
            delay_ms=100
        )
        
        ctk.CTkLabel(self.resize_custom_frame, text="Alto:").grid(row=0, column=3, padx=(0, 5), sticky="e")
        self.resize_height_entry = ctk.CTkEntry(self.resize_custom_frame, width=80, placeholder_text="1080")
        self.resize_height_entry.grid(row=0, column=4, sticky="w")

        # 3.4: Módulo "Cuadrito" Maestro de Canvas (después del de Resize)
        self.canvas_master_frame = ctk.CTkFrame(self.options_frame)
        self.canvas_master_frame.pack(fill="x", padx=5, pady=(0, 5))
        self.canvas_master_frame.grid_columnconfigure(0, weight=1)

        self.canvas_checkbox = ctk.CTkCheckBox(
            self.canvas_master_frame,
            text="Ajustar Canvas (Lienzo)",
            command=self._on_toggle_canvas_frame
        )
        self.canvas_checkbox.pack(fill="x", padx=10, pady=5)

        # --- NUEVO TOOLTIP ---
        Tooltip(self.canvas_checkbox, "Cambia el tamaño del área de trabajo sin deformar la imagen.\nPermite añadir márgenes, bordes o centrar la imagen en un tamaño fijo (ej: Post de Instagram).", delay_ms=1000)

        self.canvas_options_frame = ctk.CTkFrame(self.canvas_master_frame, fg_color="transparent")
        self.canvas_options_frame.grid_columnconfigure(1, weight=1)

        # Opciones de Canvas
        ctk.CTkLabel(self.canvas_options_frame, text="Opciones de Canvas:").grid(row=0, column=0, padx=(10, 5), pady=5, sticky="w")
        
        from src.core.constants import CANVAS_OPTIONS
        self.canvas_option_menu = ctk.CTkOptionMenu(
            self.canvas_options_frame,
            values=CANVAS_OPTIONS,
            command=self._on_canvas_option_changed
        )
        self.canvas_option_menu.set("Sin ajuste")
        self.canvas_option_menu.grid(row=0, column=1, padx=(0, 10), pady=5, sticky="ew")

        # Frame para margen (aparece con "Añadir Margen...")
        self.canvas_margin_frame = ctk.CTkFrame(self.canvas_options_frame, fg_color="transparent")
        self.canvas_margin_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky="ew")
        
        ctk.CTkLabel(self.canvas_margin_frame, text="Margen:", width=80, anchor="w").grid(row=0, column=0, padx=(10, 5), sticky="w")
        self.canvas_margin_entry = ctk.CTkEntry(self.canvas_margin_frame, width=80, placeholder_text="100")
        self.canvas_margin_entry.insert(0, "100")
        self.canvas_margin_entry.grid(row=0, column=1, sticky="w", padx=(0, 5))
        ctk.CTkLabel(self.canvas_margin_frame, text="px").grid(row=0, column=2, sticky="w")

        # Tooltip explicativo
        Tooltip(
            self.canvas_margin_entry, 
            text="Espacio que se añadirá en cada lado de la imagen.\n"
                 "Ejemplo: 100px = 100px arriba + 100px abajo + 100px izquierda + 100px derecha.\n\n"
                 "• Margen Externo: El canvas crece (imagen + margen).\n"
                 "• Margen Interno: La imagen se reduce (canvas - margen).",
            delay_ms=1000
        )

        # Frame para dimensiones personalizadas (aparece con "Personalizado...")
        self.canvas_custom_frame = ctk.CTkFrame(self.canvas_options_frame, fg_color="transparent")
        self.canvas_custom_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky="ew")
        self.canvas_custom_frame.grid_columnconfigure((1, 3), weight=1)

        ctk.CTkLabel(self.canvas_custom_frame, text="Ancho:").grid(row=0, column=0, padx=(10, 5), sticky="e")
        self.canvas_width_entry = ctk.CTkEntry(self.canvas_custom_frame, width=80, placeholder_text="1080")
        self.canvas_width_entry.grid(row=0, column=1, sticky="w")
        
        ctk.CTkLabel(self.canvas_custom_frame, text="Alto:").grid(row=0, column=2, padx=(10, 5), sticky="e")
        self.canvas_height_entry = ctk.CTkEntry(self.canvas_custom_frame, width=80, placeholder_text="1080")
        self.canvas_height_entry.grid(row=0, column=3, sticky="w")

        # Posición del contenido
        ctk.CTkLabel(self.canvas_options_frame, text="Posición del contenido:").grid(row=2, column=0, padx=(10, 5), pady=5, sticky="w")
        
        from src.core.constants import CANVAS_POSITIONS
        self.canvas_position_menu = ctk.CTkOptionMenu(
            self.canvas_options_frame,
            values=CANVAS_POSITIONS
        )
        self.canvas_position_menu.set("Centro")
        self.canvas_position_menu.grid(row=2, column=1, padx=(0, 10), pady=5, sticky="ew")

        # Modo de overflow (solo visible para presets fijos y personalizado)
        self.canvas_overflow_frame = ctk.CTkFrame(self.canvas_options_frame, fg_color="transparent")
        self.canvas_overflow_frame.grid(row=3, column=0, columnspan=2, padx=0, pady=0, sticky="ew")
        self.canvas_overflow_frame.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(self.canvas_overflow_frame, text="Si imagen excede espacio:").grid(row=0, column=0, padx=(10, 5), pady=5, sticky="w")
        
        from src.core.constants import CANVAS_OVERFLOW_MODES
        self.canvas_overflow_menu = ctk.CTkOptionMenu(
            self.canvas_overflow_frame,
            values=CANVAS_OVERFLOW_MODES
        )
        self.canvas_overflow_menu.set("Centrar (puede recortar)")
        self.canvas_overflow_menu.grid(row=0, column=1, padx=(0, 10), pady=5, sticky="ew")

        # Ocultar todo por defecto
        self.canvas_options_frame.pack_forget()
        self.canvas_margin_frame.grid_forget()
        self.canvas_custom_frame.grid_forget()
        self.canvas_overflow_frame.grid_forget()
        
        self.option_frames = {}

        # 3.4.5: Módulo "Cuadrito" Maestro de Eliminar Fondo (IA)
        self.rembg_master_frame = ctk.CTkFrame(self.options_frame)
        self.rembg_master_frame.pack(fill="x", padx=5, pady=(0, 5))
        self.rembg_master_frame.grid_columnconfigure(0, weight=1)

        self.rembg_checkbox = ctk.CTkCheckBox(
            self.rembg_master_frame,
            text="Eliminar Fondo (IA)",
            command=self._on_toggle_rembg_frame,
            fg_color="#E04F5F", hover_color="#C03949"
        )
        self.rembg_checkbox.pack(fill="x", padx=10, pady=5)

        Tooltip(self.rembg_checkbox, "Usa Inteligencia Artificial para eliminar el fondo automáticamente.\nRequiere descargar modelos adicionales.", delay_ms=1000)

        self.rembg_options_frame = ctk.CTkFrame(self.rembg_master_frame, fg_color="transparent")
        self.rembg_options_frame.grid_columnconfigure(1, weight=1)

        # --- NUEVO: Checkbox de GPU (Fila 0) ---
        self.rembg_gpu_checkbox = ctk.CTkCheckBox(
            self.rembg_options_frame, 
            text="Aceleración de Hardware (GPU)"
        )
        self.rembg_gpu_checkbox.select() # Activado por defecto
        self.rembg_gpu_checkbox.grid(row=0, column=0, columnspan=2, padx=10, pady=(5, 5), sticky="w")
        
        Tooltip(self.rembg_gpu_checkbox, "Si está activo, usa la tarjeta gráfica (GPU).\nSi se desactiva, usará el procesador (CPU) a máxima potencia.\nDesactívalo si tienes problemas de drivers o cuelgues.", delay_ms=1000)

        # --- MENÚ 1: FAMILIA (Ahora Fila 1) ---
        ctk.CTkLabel(self.rembg_options_frame, text="Motor:").grid(row=1, column=0, padx=(10, 5), pady=5, sticky="w")
        
        self.rembg_family_menu = ctk.CTkOptionMenu(
            self.rembg_options_frame,
            values=list(REMBG_MODEL_FAMILIES.keys()),
            command=self._on_rembg_family_change
        )
        self.rembg_family_menu.grid(row=1, column=1, padx=(0, 10), pady=5, sticky="ew")
        
        # --- MENÚ 2: MODELO (Ahora Fila 2) ---
        ctk.CTkLabel(self.rembg_options_frame, text="Modelo:").grid(row=2, column=0, padx=(10, 5), pady=5, sticky="w")
        
        self.rembg_model_menu = ctk.CTkOptionMenu(
            self.rembg_options_frame,
            values=["-"], # Se llena dinámicamente
            command=self._on_rembg_model_change
        )
        self.rembg_model_menu.grid(row=2, column=1, padx=(0, 10), pady=5, sticky="ew")
        
        # (Ahora Fila 3)
        self.rembg_status_label = ctk.CTkLabel(self.rembg_options_frame, text="", font=ctk.CTkFont(size=10))
        self.rembg_status_label.grid(row=3, column=0, columnspan=2, padx=10, pady=(0, 5), sticky="ew")

        # (Ahora Fila 4)
        self.rembg_actions_frame = ctk.CTkFrame(self.rembg_options_frame, fg_color="transparent")
        self.rembg_actions_frame.grid(row=4, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="ew")
        self.rembg_actions_frame.grid_columnconfigure((0, 1), weight=1)

        self.rembg_open_btn = ctk.CTkButton(
            self.rembg_actions_frame, 
            text="Abrir", 
            height=24,
            fg_color="#555555", hover_color="#444444",
            command=lambda: self._open_model_folder("rembg")
        )
        self.rembg_open_btn.grid(row=0, column=0, padx=(0, 5), sticky="ew")

        self.rembg_delete_btn = ctk.CTkButton(
            self.rembg_actions_frame, 
            text="Borrar", 
            height=24,
            fg_color="#DC3545", hover_color="#C82333",
            command=lambda: self._delete_current_model("rembg")
        )
        self.rembg_delete_btn.grid(row=0, column=1, padx=(5, 0), sticky="ew")
        # --------------------------------------------------

        self.rembg_options_frame.pack_forget()
        
        # Inicializar menús con el default
        default_family = "Rembg Standard (U2Net)"
        self.rembg_family_menu.set(default_family)

        # ---------------------------------------------------------
        # 3.4.6: Módulo "Cuadrito" Maestro de Reescalado IA (NUEVO)
        # ---------------------------------------------------------
        self.upscale_master_frame = ctk.CTkFrame(self.options_frame)
        self.upscale_master_frame.pack(fill="x", padx=5, pady=(0, 5))
        self.upscale_master_frame.grid_columnconfigure(0, weight=1)

        self.upscale_checkbox = ctk.CTkCheckBox(
            self.upscale_master_frame,
            text="Reescalado con IA",
            command=self._on_toggle_upscale_frame,
            fg_color="#2cc985", hover_color="#229e68" # Un verde distintivo
        )
        self.upscale_checkbox.pack(fill="x", padx=10, pady=5)

        Tooltip(self.upscale_checkbox, "Aumenta la resolución y mejora la calidad usando Redes Neuronales (Real-ESRGAN / Waifu2x).", delay_ms=1000)

        self.upscale_options_frame = ctk.CTkFrame(self.upscale_master_frame, fg_color="transparent")
        
        # Configurar columnas para que se repartan bien el espacio
        # Col 0: Label "Motor" | Col 1: Menu Motor | Col 2: Label "Tile" | Col 3: Entry Tile
        self.upscale_options_frame.grid_columnconfigure((1, 3), weight=1)

        # --- FILA 0: Motor ---
        ctk.CTkLabel(self.upscale_options_frame, text="Motor:").grid(row=0, column=0, padx=(10, 5), pady=5, sticky="w")
        self.upscale_engine_menu = ctk.CTkOptionMenu(
            self.upscale_options_frame,
            values=["Real-ESRGAN", "Waifu2x", "RealSR (Fotos Reales)", "SRMD (Enfoque/Deblur)"], # <-- Añadido
            command=self._on_upscale_engine_change
        )
        self.upscale_engine_menu.grid(row=0, column=1, columnspan=3, padx=(0, 10), pady=5, sticky="ew")

        # --- FILA 1: Modelo ---
        ctk.CTkLabel(self.upscale_options_frame, text="Modelo:").grid(row=1, column=0, padx=(10, 5), pady=5, sticky="w")
        self.upscale_model_menu = ctk.CTkOptionMenu(
            self.upscale_options_frame, 
            values=["-"],
            command=self._on_upscale_model_change  # ✅ Esto debe estar
        )
        self.upscale_model_menu.grid(row=1, column=1, columnspan=3, padx=(0, 10), pady=5, sticky="ew")

        # --- FILA 2: Escala (Izq) y Tile Size (Der) ---
        
        # Escala
        ctk.CTkLabel(self.upscale_options_frame, text="Escala:").grid(row=2, column=0, padx=(10, 5), pady=5, sticky="w")
        self.upscale_scale_menu = ctk.CTkOptionMenu(
            self.upscale_options_frame, 
            values=["2x", "3x", "4x"], 
            width=70 # Hacemos este menú más pequeño
        )
        self.upscale_scale_menu.set("2x")
        self.upscale_scale_menu.grid(row=2, column=1, padx=(0, 10), pady=5, sticky="w") # Sticky W para que no se estire

        # Tile Size (Movido aquí arriba)
        ctk.CTkLabel(self.upscale_options_frame, text="Tile Size:").grid(row=2, column=2, padx=(5, 5), pady=5, sticky="e")
        self.upscale_tile_entry = ctk.CTkEntry(self.upscale_options_frame, width=60, placeholder_text="0")
        self.upscale_tile_entry.insert(0, "0") # 0 = Auto
        self.upscale_tile_entry.grid(row=2, column=3, padx=(0, 10), pady=5, sticky="w") # Sticky W
        
        Tooltip(self.upscale_tile_entry, "Tamaño del bloque de procesamiento.\nDéjalo en 0 para Auto.\nSi la app se cierra sola (Crash), prueba con 200 o 100 (consume menos VRAM).", delay_ms=1000)

        # --- FILA 3: Reducción de Ruido (Solo Waifu2x) ---
        self.upscale_denoise_label = ctk.CTkLabel(self.upscale_options_frame, text="Reducir Ruido:")
        self.upscale_denoise_label.grid(row=3, column=0, padx=(10, 5), pady=5, sticky="w")
        
        self.upscale_denoise_menu = ctk.CTkOptionMenu(
            self.upscale_options_frame, 
            values=["-1 (Ninguna)", "0 (Baja)", "1 (Media)", "2 (Alta)", "3 (Máxima)"],
            # Ahora tiene toda la fila para él solo si quiere
        )
        self.upscale_denoise_menu.set("2 (Alta)")
        self.upscale_denoise_menu.grid(row=3, column=1, columnspan=3, padx=(0, 10), pady=5, sticky="ew")

        # --- FILA 4: TTA ---
        self.upscale_tta_check = ctk.CTkCheckBox(self.upscale_options_frame, text="TTA (Mejor calidad, muy lento)")
        self.upscale_tta_check.grid(row=4, column=0, columnspan=4, padx=10, pady=5, sticky="w")

        # --- FILA 5: Label de Estado ---
        self.upscale_status_label = ctk.CTkLabel(self.upscale_options_frame, text="", font=ctk.CTkFont(size=10))
        self.upscale_status_label.grid(row=5, column=0, columnspan=4, padx=10, pady=(5, 5), sticky="ew")

        # --- FILA 6: Botones de Gestión ---
        self.upscale_actions_frame = ctk.CTkFrame(self.upscale_options_frame, fg_color="transparent")
        self.upscale_actions_frame.grid(row=6, column=0, columnspan=4, padx=10, pady=(0, 10), sticky="ew")
        self.upscale_actions_frame.grid_columnconfigure((0, 1), weight=1)

        self.upscale_open_btn = ctk.CTkButton(
            self.upscale_actions_frame, 
            text="Abrir", 
            height=24,
            fg_color="#555555", hover_color="#444444",
            command=lambda: self._open_model_folder("upscale")
        )
        self.upscale_open_btn.grid(row=0, column=0, padx=(0, 5), sticky="ew")

        self.upscale_delete_btn = ctk.CTkButton(
            self.upscale_actions_frame, 
            text="Borrar", 
            height=24,
            fg_color="#DC3545", hover_color="#C82333",
            command=lambda: self._delete_current_model("upscale")
        )
        self.upscale_delete_btn.grid(row=0, column=1, padx=(5, 0), sticky="ew")

        self.upscale_options_frame.pack_forget()
        
        # Inicializar lógica del menú (SILENCIOSAMENTE)
        self._on_upscale_engine_change("Real-ESRGAN", silent=True)

        # 3.5: Módulo "Cuadrito" Maestro de Cambio de Fondo
        self.background_master_frame = ctk.CTkFrame(self.options_frame)
        self.background_master_frame.pack(fill="x", padx=5, pady=(0, 5))
        self.background_master_frame.grid_columnconfigure(0, weight=1)

        self.background_checkbox = ctk.CTkCheckBox(
            self.background_master_frame,
            text="Cambiar Fondo (Transparente)",
            command=self._on_toggle_background_frame
        )
        self.background_checkbox.pack(fill="x", padx=10, pady=5)

        # --- NUEVO TOOLTIP ---
        Tooltip(self.background_checkbox, "Reemplaza las áreas transparentes de la imagen con un color sólido, un degradado o una imagen personalizada.", delay_ms=1000)

        self.background_options_frame = ctk.CTkFrame(self.background_master_frame, fg_color="transparent")
        self.background_options_frame.grid_columnconfigure(1, weight=1)

        # Tipo de fondo
        ctk.CTkLabel(self.background_options_frame, text="Tipo de Fondo:").grid(row=0, column=0, padx=(10, 5), pady=5, sticky="w")
        
        from src.core.constants import BACKGROUND_TYPES
        self.background_type_menu = ctk.CTkOptionMenu(
            self.background_options_frame,
            values=BACKGROUND_TYPES,
            command=self._on_background_type_changed
        )
        self.background_type_menu.set("Color Sólido")
        self.background_type_menu.grid(row=0, column=1, padx=(0, 10), pady=5, sticky="ew")

        # Frame para Color Sólido
        self.bg_solid_frame = ctk.CTkFrame(self.background_options_frame, fg_color="transparent")
        self.bg_solid_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky="ew")
        
        ctk.CTkLabel(self.bg_solid_frame, text="Color:", width=80, anchor="w").grid(row=0, column=0, padx=(10, 5), sticky="w")
        
        self.bg_color_button = ctk.CTkButton(
            self.bg_solid_frame, text="🎨", width=40,
            command=self._pick_solid_color
        )
        self.bg_color_button.grid(row=0, column=1, sticky="w", padx=(0, 5))
        
        self.bg_color_entry = ctk.CTkEntry(self.bg_solid_frame, width=100, placeholder_text="#FFFFFF")
        self.bg_color_entry.insert(0, "#FFFFFF")
        self.bg_color_entry.grid(row=0, column=2, sticky="w")
        
        Tooltip(self.bg_color_entry, "Color de fondo en formato hexadecimal (#RRGGBB)", delay_ms=1000)

        # Frame para Degradado
        self.bg_gradient_frame = ctk.CTkFrame(self.background_options_frame, fg_color="transparent")
        self.bg_gradient_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky="ew")
        
        # Color 1
        ctk.CTkLabel(self.bg_gradient_frame, text="Color 1:", width=80, anchor="w").grid(row=0, column=0, padx=(10, 5), sticky="w")
        self.bg_gradient_color1_button = ctk.CTkButton(
            self.bg_gradient_frame, text="🎨", width=40,
            command=lambda: self._pick_gradient_color(1)
        )
        self.bg_gradient_color1_button.grid(row=0, column=1, sticky="w", padx=(0, 5))
        self.bg_gradient_color1_entry = ctk.CTkEntry(self.bg_gradient_frame, width=100, placeholder_text="#FF0000")
        self.bg_gradient_color1_entry.insert(0, "#FF0000")
        self.bg_gradient_color1_entry.grid(row=0, column=2, sticky="w")
        
        # Color 2
        ctk.CTkLabel(self.bg_gradient_frame, text="Color 2:", width=80, anchor="w").grid(row=1, column=0, padx=(10, 5), pady=(5, 0), sticky="w")
        self.bg_gradient_color2_button = ctk.CTkButton(
            self.bg_gradient_frame, text="🎨", width=40,
            command=lambda: self._pick_gradient_color(2)
        )
        self.bg_gradient_color2_button.grid(row=1, column=1, sticky="w", padx=(0, 5), pady=(5, 0))
        self.bg_gradient_color2_entry = ctk.CTkEntry(self.bg_gradient_frame, width=100, placeholder_text="#0000FF")
        self.bg_gradient_color2_entry.insert(0, "#0000FF")
        self.bg_gradient_color2_entry.grid(row=1, column=2, sticky="w", pady=(5, 0))
        
        # Dirección
        ctk.CTkLabel(self.bg_gradient_frame, text="Dirección:", width=80, anchor="w").grid(row=2, column=0, padx=(10, 5), pady=(5, 0), sticky="w")
        
        from src.core.constants import GRADIENT_DIRECTIONS
        self.bg_gradient_direction_menu = ctk.CTkOptionMenu(
            self.bg_gradient_frame,
            values=GRADIENT_DIRECTIONS,
            width=200
        )
        self.bg_gradient_direction_menu.set("Horizontal (Izq → Der)")
        self.bg_gradient_direction_menu.grid(row=2, column=1, columnspan=2, sticky="w", pady=(5, 0))

        # Frame para Imagen de Fondo
        self.bg_image_frame = ctk.CTkFrame(self.background_options_frame, fg_color="transparent")
        self.bg_image_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky="ew")
        self.bg_image_frame.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(self.bg_image_frame, text="Imagen:", width=80, anchor="w").grid(row=0, column=0, padx=(10, 5), sticky="w")
        self.bg_image_entry = ctk.CTkEntry(self.bg_image_frame, placeholder_text="Selecciona una imagen...")
        self.bg_image_entry.grid(row=0, column=1, sticky="ew", padx=(0, 5))
        self.bg_image_button = ctk.CTkButton(
            self.bg_image_frame, text="📁", width=40,
            command=self._select_background_image
        )
        self.bg_image_button.grid(row=0, column=2, sticky="w")

        # Ocultar todo por defecto
        self.background_master_frame.pack_forget()  # El módulo completo se oculta
        self.background_options_frame.pack_forget()
        self.bg_solid_frame.grid_forget()
        self.bg_gradient_frame.grid_forget()
        self.bg_image_frame.grid_forget()

        self._create_png_options()
        self._create_jpg_options()
        self._create_webp_options()
        self._create_avif_options()
        self._create_pdf_options()
        self._create_tiff_options()
        self._create_ico_options()
        self._create_bmp_options()
        
        # --- NUEVO: Crear el frame de opciones de Video ---
        self._create_video_options()
        
        # Mapear los formatos de video al mismo frame de opciones
        video_frame = self.option_frames.get("VIDEO")
        if video_frame:
            self.option_frames[".mp4 (H.264)"] = video_frame
            self.option_frames[".mov (ProRes)"] = video_frame
            self.option_frames[".webm (VP9)"] = video_frame
            self.option_frames[".gif (Animado)"] = video_frame

        self.resize_options_frame.pack_forget()
        self.resize_custom_frame.grid_forget()
        self.interpolation_frame.grid_forget()
        
        self._on_format_changed(self.format_menu.get())
        
    def _create_bottom_panel(self):
        """
        Crea el panel de salida inferior, copiando la estructura de 
        batch_download_tab.py (sin límite de velocidad).
        """
        self.bottom_panel = ctk.CTkFrame(self)
        self.bottom_panel.grid(row=1, column=0, columnspan=2, padx=10, pady=(5, 5), sticky="ew")
        
        # --- Fila 1 del panel (Ruta de salida) ---
        line1_frame = ctk.CTkFrame(self.bottom_panel, fg_color="transparent")
        line1_frame.pack(fill="x", padx=0, pady=(0, 5))
        line1_frame.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(line1_frame, text="Carpeta de Salida:").grid(row=0, column=0, padx=(10, 5), pady=5, sticky="w")
        
        self.output_path_entry = ctk.CTkEntry(line1_frame, placeholder_text="Selecciona una carpeta...")
        self.output_path_entry.bind("<Button-3>", lambda e: self.create_entry_context_menu(self.output_path_entry))
        self.output_path_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        
        self.select_folder_button = ctk.CTkButton(
            line1_frame, text="...", width=40, 
            command=self.select_output_folder
        )
        self.select_folder_button.grid(row=0, column=2, padx=(0, 5), pady=5)
        
        self.open_folder_button = ctk.CTkButton(
            line1_frame, text="📁", width=40, font=ctk.CTkFont(size=16), 
            command=self._open_batch_output_folder, state="disabled"
        )
        self.open_folder_button.grid(row=0, column=3, padx=(0, 10), pady=5)
        
        # (Se omite el límite de velocidad, como se solicitó)

        # --- Fila 2 del panel (Opciones y Botón de Inicio) ---
        line2_frame = ctk.CTkFrame(self.bottom_panel, fg_color="transparent")
        line2_frame.pack(fill="x", padx=0, pady=0)
        line2_frame.grid_columnconfigure(5, weight=1) # Columna de espacio flexible
        
        conflict_label = ctk.CTkLabel(line2_frame, text="Si existe:")
        conflict_label.grid(row=0, column=0, padx=(10, 5), pady=5, sticky="w")

        self.conflict_policy_menu = ctk.CTkOptionMenu(
            line2_frame, width=120,
            values=["Sobrescribir", "Renombrar", "Omitir"]
        )
        self.conflict_policy_menu.set("Renombrar")
        self.conflict_policy_menu.grid(row=0, column=1, padx=(0, 10), pady=5, sticky="w")
        
        Tooltip(conflict_label, "Determina qué hacer si un archivo con el mismo nombre ya existe.", delay_ms=1000)
        Tooltip(self.conflict_policy_menu, "Determina qué hacer si un archivo con el mismo nombre ya existe.", delay_ms=1000)
        
        self.create_subfolder_checkbox = ctk.CTkCheckBox(
            line2_frame, text="Crear carpeta", 
            command=self._toggle_subfolder_name_entry
        )
        self.create_subfolder_checkbox.grid(row=0, column=2, padx=(5, 5), pady=5, sticky="w")
        Tooltip(self.create_subfolder_checkbox, "Guarda todos los archivos en una subcarpeta dedicada.", delay_ms=1000)

        self.subfolder_name_entry = ctk.CTkEntry(line2_frame, width=120, placeholder_text="DowP Imágenes")
        self.subfolder_name_entry.bind("<Button-3>", lambda e: self.create_entry_context_menu(self.subfolder_name_entry))
        self.subfolder_name_entry.grid(row=0, column=3, padx=(0, 10), pady=5, sticky="w")
        self.subfolder_name_entry.configure(state="disabled")
        
        # (Se omite Auto-descarga)
        
        self.auto_import_checkbox = ctk.CTkCheckBox(
            line2_frame, text="Import Adobe", 
            command=self.save_settings,
            text_color="#FFC792", fg_color="#C17B42", hover_color="#9A6336"
        )
        self.auto_import_checkbox.grid(row=0, column=4, padx=5, pady=5, sticky="w")
        Tooltip(self.auto_import_checkbox, "Importa automáticamente los archivos procesados a Premiere o After Effects.", delay_ms=1000)
        
        self.start_process_button = ctk.CTkButton(
            line2_frame, text="Iniciar Proceso", 
            state="disabled", command=self._on_start_process, 
            fg_color=self.PROCESS_BTN_COLOR, hover_color=self.PROCESS_BTN_HOVER, 
            text_color_disabled=self.DISABLED_TEXT_COLOR, width=140
        )
        self.start_process_button.grid(row=0, column=6, padx=(5, 10), pady=5, sticky="e") 

    def _create_progress_panel(self):
        """Crea el panel de progreso inferior."""
        self.progress_frame = ctk.CTkFrame(self)
        self.progress_frame.grid(row=2, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="ew")
        
        self.progress_label = ctk.CTkLabel(self.progress_frame, text="Listo. Añade archivos para empezar.")
        self.progress_label.pack(pady=(5,0))
        
        self.progress_bar = ctk.CTkProgressBar(self.progress_frame)
        self.progress_bar.set(0)
        self.progress_bar.pack(pady=(0,5), padx=10, fill="x")


    # ==================================================================
    # --- LÓGICA DE OPCIONES DINÁMICAS (PANEL DERECHO) ---
    # ==================================================================

    def _on_format_changed(self, selected_format):
        """Oculta todos los frames de opciones y muestra solo el relevante."""
        
        # 1. Ocultar todos los frames de opciones específicas
        for frame in self.option_frames.values():
            if frame: frame.pack_forget()
        
        is_video_format = selected_format.startswith(".") or selected_format == "--- Video ---"
        
        if is_video_format:
            # Si es VIDEO: Deshabilitar Escalado y Canvas
            self.resize_checkbox.configure(state="disabled")
            self.canvas_checkbox.configure(state="disabled")
            self.background_checkbox.configure(state="normal")
        else: 
            # Si es IMAGEN ("PNG", "JPG", etc.) o "No Convertir": Habilitar todo
            self.resize_checkbox.configure(state="normal")
            self.canvas_checkbox.configure(state="normal")
            self.background_checkbox.configure(state="normal")


        # 2. Mostrar/Ocultar el contenedor de opciones y el frame correcto
        if selected_format == "No Convertir" or selected_format == "--- Video ---":
            self.options_container.pack_forget()
        else:
            self.options_container.pack(fill="x", expand=True, padx=5, pady=0, after=self.format_menu_frame)
            
            frame_to_show = self.option_frames.get(selected_format)
            if frame_to_show:
                frame_to_show.pack(fill="x", expand=True, padx=5, pady=5)
        
        # 3. Mostrar/ocultar el módulo de cambio de fondo
        from src.core.constants import FORMATS_WITH_TRANSPARENCY, IMAGE_INPUT_FORMATS

        show_background_module = False
        
        # Mostrar si es "No Convertir", video, o un formato de imagen transparente
        if selected_format == "No Convertir" or is_video_format:
            show_background_module = True
        elif selected_format in FORMATS_WITH_TRANSPARENCY:
            show_background_module = True
        
        if selected_format == "WEBP" and hasattr(self, 'webp_transparency') and self.webp_transparency.get() == 0:
            show_background_module = False
        if selected_format == "TIFF" and hasattr(self, 'tiff_transparency') and self.tiff_transparency.get() == 0:
            show_background_module = False
            
        if selected_format == "AVIF" and hasattr(self, 'avif_transparency') and self.avif_transparency.get() == 0:
            show_background_module = False

        if show_background_module:
            self.background_master_frame.pack(fill="x", padx=5, pady=(0, 5), after=self.canvas_master_frame)
        else:
            self.background_master_frame.pack_forget()

    def _create_slider_with_label(self, parent, text, min_val, max_val, default_val, step=1):
        """
        Helper para crear un slider con un label de valor numérico a la derecha.
        Cumple con tu requisito de UI.
        """
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", padx=10, pady=5, anchor="w")
        
        label = ctk.CTkLabel(frame, text=text, width=120, anchor="w") # Label a la izquierda
        label.pack(side="left")
        
        # Entry a la derecha (para mostrar el valor)
        value_entry = ctk.CTkEntry(frame, width=45, justify="center")
        value_entry.pack(side="right", padx=(10, 0))
        
        # Callback para actualizar el Entry en vivo
        def slider_callback(value):
            int_value = int(value / step) * step
            value_entry.configure(state="normal")
            value_entry.delete(0, "end")
            value_entry.insert(0, f"{int_value}")
            value_entry.configure(state="disabled") # Deshabilitado para que actúe como label
        
        slider = ctk.CTkSlider(
            frame, 
            from_=min_val, 
            to=max_val,
            number_of_steps=(max_val - min_val) // step if step != 0 else 100,
            command=slider_callback
        )
        slider.set(default_val)
        
        slider_callback(default_val) # Llamada inicial
        
        slider.pack(side="left", fill="x", expand=True) # Slider en el medio
        
        return slider, value_entry # Devolvemos los widgets por si los necesitamos

    def _create_png_options(self):
        """Crea el frame de opciones para PNG."""
        png_frame = ctk.CTkFrame(self.options_container, fg_color="#2B2B2B")
        
        self.png_transparency = ctk.CTkCheckBox(png_frame, text="Mantener Transparencia")
        self.png_transparency.pack(fill="x", padx=10, pady=5)
        self.png_transparency.select() # Por defecto, mantener transparencia

        self.png_compression_slider, self.png_compression_label = self._create_slider_with_label(
            parent=png_frame,
            text="Compresión (0-9):",
            min_val=0, max_val=9, default_val=6, step=1
        )
        
        self.option_frames["PNG"] = png_frame

    def _create_jpg_options(self):
        """Crea el frame de opciones para JPG/JPEG."""
        jpg_frame = ctk.CTkFrame(self.options_container, fg_color="#2B2B2B")
        
        self.jpg_quality_slider, self.jpg_quality_label = self._create_slider_with_label(
            parent=jpg_frame,
            text="Calidad (1-100):",
            min_val=1, max_val=100, default_val=90, step=1
        )
        
        sub_frame = ctk.CTkFrame(jpg_frame, fg_color="transparent")
        sub_frame.pack(fill="x", padx=10, pady=5, anchor="w")
        ctk.CTkLabel(sub_frame, text="Subsampling Croma:", width=120, anchor="w").pack(side="left")
        self.jpg_subsampling = ctk.CTkOptionMenu(
            sub_frame, 
            values=["4:2:0 (Estándar)", "4:2:2 (Alta)", "4:4:4 (Máxima)"],
            width=200
        )
        self.jpg_subsampling.pack(side="left", fill="x", expand=True)

        self.jpg_progressive = ctk.CTkCheckBox(jpg_frame, text="Escaneo Progresivo (Web)")
        self.jpg_progressive.pack(fill="x", padx=10, pady=5)
        
        self.option_frames["JPG"] = jpg_frame
        self.option_frames["JPEG"] = jpg_frame # Ambos apuntan al mismo frame

    def _create_webp_options(self):
        """Crea el frame de opciones para WEBP."""
        webp_frame = ctk.CTkFrame(self.options_container, fg_color="#2B2B2B")
        
        self.webp_lossless = ctk.CTkCheckBox(
            webp_frame, 
            text="Compresión sin Pérdida (Lossless)",
            command=self._toggle_webp_quality # Llama a la función de UI
        )
        self.webp_lossless.pack(fill="x", padx=10, pady=5)

        # Guardamos el frame del slider para poder ocultarlo/mostrarlo
        self.webp_quality_frame = ctk.CTkFrame(webp_frame, fg_color="transparent")
        self.webp_quality_frame.pack(fill="x", expand=True)
        
        self.webp_quality_slider, self.webp_quality_label = self._create_slider_with_label(
            parent=self.webp_quality_frame,
            text="Calidad (1-100):",
            min_val=1, max_val=100, default_val=90, step=1
        )

        self.webp_transparency = ctk.CTkCheckBox(
            webp_frame, 
            text="Mantener Transparencia",
            command=lambda: self._on_format_changed(self.format_menu.get())
        )
        self.webp_transparency.pack(fill="x", padx=10, pady=5)
        self.webp_transparency.select()

        self.webp_metadata = ctk.CTkCheckBox(webp_frame, text="Guardar Metadatos (EXIF, XMP)")
        self.webp_metadata.pack(fill="x", padx=10, pady=5)
        
        self.option_frames["WEBP"] = webp_frame

    def _create_avif_options(self):
        """Crea el frame de opciones para AVIF."""
        avif_frame = ctk.CTkFrame(self.options_container, fg_color="#2B2B2B")
        
        self.avif_lossless = ctk.CTkCheckBox(
            avif_frame, 
            text="Sin Pérdida (Lossless)",
            command=self._toggle_avif_quality
        )
        self.avif_lossless.pack(fill="x", padx=10, pady=5)

        # Frame de Calidad (se oculta si es Lossless)
        self.avif_quality_frame = ctk.CTkFrame(avif_frame, fg_color="transparent")
        self.avif_quality_frame.pack(fill="x", expand=True)
        
        self.avif_quality_slider, _ = self._create_slider_with_label(
            parent=self.avif_quality_frame,
            text="Calidad (1-100):",
            min_val=1, max_val=100, default_val=80, step=1
        )

        # Slider de Velocidad (0-10)
        self.avif_speed_slider, _ = self._create_slider_with_label(
            parent=avif_frame,
            text="Velocidad (0-10):",
            min_val=0, max_val=10, default_val=6, step=1
        )
        Tooltip(self.avif_speed_slider, "Compresión: 0=Lento/Mejor, 10=Rápido/Peor. Default: 6", delay_ms=1000)

        self.avif_transparency = ctk.CTkCheckBox(
            avif_frame, 
            text="Mantener Transparencia",
            command=lambda: self._on_format_changed(self.format_menu.get())
        )
        self.avif_transparency.pack(fill="x", padx=10, pady=5)
        self.avif_transparency.select()
        
        self.option_frames["AVIF"] = avif_frame

    def _toggle_avif_quality(self):
        """Muestra u oculta slider calidad según lossless."""
        if self.avif_lossless.get() == 1:
            self.avif_quality_frame.pack_forget()
        else:
            self.avif_quality_frame.pack(fill="x", expand=True, after=self.avif_lossless)

    def _toggle_webp_quality(self):
        """Muestra u oculta el slider de calidad de WEBP."""
        if self.webp_lossless.get() == 1:
            # Si es Lossless, ocultar calidad
            self.webp_quality_frame.pack_forget()
        else:
            # Si NO es Lossless, mostrar calidad
            self.webp_quality_frame.pack(fill="x", expand=True, after=self.webp_lossless)
        # Actualizar visibilidad del módulo de fondo
        self._on_format_changed(self.format_menu.get())

    def _toggle_pdf_title_entry(self):
        """Muestra u oculta el entry de título del PDF combinado."""
        if self.pdf_combine.get() == 1:
            # Mostrar el campo de título
            self.pdf_title_frame.pack(fill="x", padx=10, pady=5, after=self.pdf_combine)
        else:
            # Ocultar el campo de título
            self.pdf_title_frame.pack_forget()

    def _on_toggle_canvas_frame(self):
        """Muestra u oculta el frame de opciones de canvas."""
        if self.canvas_checkbox.get() == 1:
            # Mostrar el frame de opciones
            self.canvas_options_frame.pack(fill="x", padx=5, pady=0, after=self.canvas_checkbox)
            # Aplicar la opción seleccionada actualmente
            self._on_canvas_option_changed(self.canvas_option_menu.get())
        else:
            # Ocultar todos los frames
            self.canvas_options_frame.pack_forget()
            self.canvas_margin_frame.grid_forget()
            self.canvas_custom_frame.grid_forget()
            self.canvas_overflow_frame.grid_forget()

    def _on_canvas_option_changed(self, selection):
        """Maneja el cambio de opción de canvas."""
        from src.core.constants import CANVAS_PRESET_SIZES
        
        # Ocultar todos los frames opcionales primero
        self.canvas_margin_frame.grid_forget()
        self.canvas_custom_frame.grid_forget()
        self.canvas_overflow_frame.grid_forget()
        
        if selection == "Sin ajuste":
            # No mostrar nada adicional
            pass
        
        elif selection in ["Añadir Margen Externo", "Añadir Margen Interno"]:
            # Mostrar campo de margen
            self.canvas_margin_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky="ew")
        
        elif selection == "Personalizado...":
            # Mostrar campos de dimensiones y overflow
            self.canvas_custom_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky="ew")
            self.canvas_overflow_frame.grid(row=3, column=0, columnspan=2, padx=0, pady=0, sticky="ew")
        
        elif selection in CANVAS_PRESET_SIZES:
            # Preset fijo: llenar dimensiones y mostrar overflow
            width, height = CANVAS_PRESET_SIZES[selection]
            self.canvas_width_entry.delete(0, "end")
            self.canvas_width_entry.insert(0, str(width))
            self.canvas_height_entry.delete(0, "end")
            self.canvas_height_entry.insert(0, str(height))
            
            # 🔥 NUEVO: Mostrar overflow SOLO para presets (NO para personalizado)
            self.canvas_overflow_frame.grid(row=3, column=0, columnspan=2, padx=0, pady=0, sticky="ew")
            
            print(f"Preset de canvas aplicado: {width}×{height}")

    def _on_toggle_background_frame(self):
        """Muestra u oculta el frame de opciones de fondo."""
        if self.background_checkbox.get() == 1:
            self.background_options_frame.pack(fill="x", padx=5, pady=0, after=self.background_checkbox)
            self._on_background_type_changed(self.background_type_menu.get())
        else:
            self.background_options_frame.pack_forget()
            self.bg_solid_frame.grid_forget()
            self.bg_gradient_frame.grid_forget()
            self.bg_image_frame.grid_forget()

    def _on_background_type_changed(self, selection):
        """Muestra el frame correspondiente al tipo de fondo seleccionado."""
        # Ocultar todos
        self.bg_solid_frame.grid_forget()
        self.bg_gradient_frame.grid_forget()
        self.bg_image_frame.grid_forget()
        
        # Mostrar el correcto
        if selection == "Color Sólido":
            self.bg_solid_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky="ew")
        elif selection == "Degradado":
            self.bg_gradient_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky="ew")
        elif selection == "Imagen de Fondo":
            self.bg_image_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky="ew")

    def _pick_solid_color(self):
        """Abre un color picker para el fondo sólido."""
        try:
            from tkinter import colorchooser
            color = colorchooser.askcolor(title="Seleccionar Color de Fondo", initialcolor=self.bg_color_entry.get())
            if color[1]:  # color[1] es el valor hexadecimal
                self.bg_color_entry.delete(0, "end")
                self.bg_color_entry.insert(0, color[1].upper())
        except Exception as e:
            print(f"Error al abrir el color picker: {e}")

    def _pick_gradient_color(self, color_num):
        """Abre un color picker para el degradado."""
        try:
            from tkinter import colorchooser
            entry = self.bg_gradient_color1_entry if color_num == 1 else self.bg_gradient_color2_entry
            color = colorchooser.askcolor(title=f"Seleccionar Color {color_num}", initialcolor=entry.get())
            if color[1]:
                entry.delete(0, "end")
                entry.insert(0, color[1].upper())
        except Exception as e:
            print(f"Error al abrir el color picker: {e}")

    def _select_background_image(self):
        """Abre un diálogo para seleccionar una imagen de fondo."""
        from customtkinter import filedialog
        filepath = filedialog.askopenfilename(
            title="Seleccionar Imagen de Fondo",
            filetypes=[
                ("Imágenes", "*.png *.jpg *.jpeg *.webp *.bmp"),
                ("Todos los archivos", "*.*")
            ]
        )
        self.app.lift()
        self.app.focus_force()
        
        if filepath:
            self.bg_image_entry.delete(0, "end")
            self.bg_image_entry.insert(0, filepath)

    def _create_pdf_options(self):
        """Crea el frame de opciones para PDF."""
        pdf_frame = ctk.CTkFrame(self.options_container, fg_color="#2B2B2B")
        
        self.pdf_combine = ctk.CTkCheckBox(
            pdf_frame, 
            text="Combinar todos en un solo PDF",
            command=self._toggle_pdf_title_entry
        )
        self.pdf_combine.pack(fill="x", padx=10, pady=5)
        
        # Frame para el título del PDF combinado
        self.pdf_title_frame = ctk.CTkFrame(pdf_frame, fg_color="transparent")
        self.pdf_title_frame.pack(fill="x", padx=10, pady=5)
        self.pdf_title_frame.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(self.pdf_title_frame, text="Nombre del PDF:", width=120, anchor="w").grid(row=0, column=0, padx=(0, 5), sticky="w")
        
        self.pdf_combined_title_entry = ctk.CTkEntry(
            self.pdf_title_frame, 
            placeholder_text="combined_output"
        )
        self.pdf_combined_title_entry.bind("<Button-3>", lambda e: self.create_entry_context_menu(self.pdf_combined_title_entry))
        self.pdf_combined_title_entry.grid(row=0, column=1, sticky="ew")
        
        # Ocultar por defecto
        self.pdf_title_frame.pack_forget()
        
        self.option_frames["PDF"] = pdf_frame

    def _create_tiff_options(self):
        """Crea el frame de opciones para TIFF."""
        tiff_frame = ctk.CTkFrame(self.options_container, fg_color="#2B2B2B")
        
        comp_frame = ctk.CTkFrame(tiff_frame, fg_color="transparent")
        comp_frame.pack(fill="x", padx=10, pady=5, anchor="w")
        ctk.CTkLabel(comp_frame, text="Compresión:", width=120, anchor="w").pack(side="left")
        self.tiff_compression = ctk.CTkOptionMenu(
            comp_frame, 
            values=["Ninguna", "LZW (Recomendada)", "Deflate (ZIP)", "PackBits"],
            width=200
        )
        self.tiff_compression.set("LZW (Recomendada)")
        self.tiff_compression.pack(side="left", fill="x", expand=True)
        
        self.tiff_multipago = ctk.CTkCheckBox(tiff_frame, text="Guardar Multipágina (unir cola)")
        self.tiff_multipago.pack(fill="x", padx=10, pady=5)

        self.tiff_transparency = ctk.CTkCheckBox(
            tiff_frame, 
            text="Mantener Transparencia",
            command=lambda: self._on_format_changed(self.format_menu.get())
        )
        self.tiff_transparency.pack(fill="x", padx=10, pady=5)
        self.tiff_transparency.select()
        
        self.option_frames["TIFF"] = tiff_frame

    def _create_ico_options(self):
        """Crea el frame de opciones para ICO."""
        ico_frame = ctk.CTkFrame(self.options_container, fg_color="#2B2B2B")
        
        ctk.CTkLabel(ico_frame, text="Tamaños a incluir en el .ico:").pack(fill="x", padx=10, pady=5)
        
        self.ico_sizes = {}
        sizes_frame = ctk.CTkFrame(ico_frame, fg_color="transparent")
        sizes_frame.pack(fill="x", padx=10, pady=5)
        sizes = [16, 32, 48, 64, 128, 256]
        
        # Configurar las columnas para que tengan un 'pad' (espaciado)
        # y peso para que se distribuyan uniformemente.
        sizes_frame.grid_columnconfigure((0, 1, 2), weight=1, pad=5)
        # --- FIN DE CORRECCIÓN ---

        for i, size in enumerate(sizes):
            # Colocar en 2 filas y 3 columnas
            row = i // 3
            col = i % 3
            
            chk = ctk.CTkCheckBox(sizes_frame, text=f"{size}x{size}")
            # Marcar 32 y 256 por defecto
            if size in [32, 256]:
                chk.select()
            
            # --- CORRECCIÓN ---
            # Quitar el 'padx' y 'pady' de aquí para que
            # el 'grid_columnconfigure' controle el espaciado.
            chk.grid(row=row, column=col, sticky="w")
            self.ico_sizes[size] = chk # Guardar el widget
            
        self.option_frames["ICO"] = ico_frame

    def _create_bmp_options(self):
        """Crea el frame de opciones para BMP."""
        bmp_frame = ctk.CTkFrame(self.options_container, fg_color="#2B2B2B")
        
        self.bmp_rle = ctk.CTkCheckBox(bmp_frame, text="Comprimir (RLE)")
        self.bmp_rle.pack(fill="x", padx=10, pady=5)
        
        self.option_frames["BMP"] = bmp_frame

    # --- Lógica de Reescalado UI ---

    def _on_toggle_upscale_frame(self):
        """Muestra/Oculta opciones de reescalado."""
        if self.upscale_checkbox.get() == 1:
            self.upscale_options_frame.pack(fill="x", padx=5, pady=0, after=self.upscale_checkbox)
        else:
            self.upscale_options_frame.pack_forget()

    def _on_upscale_engine_change(self, engine, silent=False):
        """Carga modelos y ajusta visibilidad según el motor."""
        
        # 🔍 DEBUG
        print(f"DEBUG: Cambiando a motor: {engine}")
        
        if engine == "Real-ESRGAN":
            models_list = list(REALESRGAN_MODELS.keys())
            self.upscale_model_menu.configure(values=models_list)
            self.upscale_model_menu.set(models_list[0])
            
            # Ocultar Denoise
            self.upscale_denoise_label.grid_remove()
            self.upscale_denoise_menu.grid_remove()
            
        elif engine == "Waifu2x":
            models_list = list(WAIFU2X_MODELS.keys())
            self.upscale_model_menu.configure(values=models_list)
            self.upscale_model_menu.set(models_list[0])
            
            # Mostrar Denoise
            self.upscale_denoise_label.grid()
            self.upscale_denoise_menu.grid()

        elif "RealSR" in engine:
            models_list = list(REALSR_MODELS.keys())
            self.upscale_model_menu.configure(values=models_list)
            self.upscale_model_menu.set(models_list[0])
            
            # Ocultar Denoise
            self.upscale_denoise_label.grid_remove()
            self.upscale_denoise_menu.grid_remove()

        elif "SRMD" in engine:
            models_list = list(SRMD_MODELS.keys())
            self.upscale_model_menu.configure(values=models_list)
            self.upscale_model_menu.set(models_list[0])
            
            # Mostrar Denoise
            self.upscale_denoise_label.configure(text="Nivel Ruido/Blur:")
            self.upscale_denoise_label.grid()
            self.upscale_denoise_menu.grid()
        
        # ✅ CRÍTICO: Pasar el motor y el flag silent explícitamente
        selected_model = self.upscale_model_menu.get()
        # Pasamos silent=silent para que la cadena de silencio continúe
        self._on_upscale_model_change(selected_model, engine=engine, silent=silent)

    def _on_upscale_model_change(self, selected_model_friendly, engine=None, silent=False):
        """
        Actualiza escalas y verifica si el motor de upscaling está instalado.
        Combina tu lógica de escalas con la nueva lógica de gestión de archivos.
        """
        # 1. Si la herramienta no está activa, no hacer nada
        if self.upscale_checkbox.get() != 1: return
        
        # 2. Si no se pasa el motor explícitamente, leerlo del menú
        if engine is None:
            engine = self.upscale_engine_menu.get()
            
        # ==============================================================================
        # PARTE A: VERIFICACIÓN DE INSTALACIÓN (NUEVO)
        # ==============================================================================
        
        # Mapeo para saber qué archivo ejecutable buscar según el motor
        engine_map = {
            "Real-ESRGAN": ("realesrgan", "realesrgan-ncnn-vulkan.exe"),
            "Waifu2x": ("waifu2x", "waifu2x-ncnn-vulkan.exe"),
            "RealSR": ("realsr", "realsr-ncnn-vulkan.exe"),
            "SRMD": ("srmd", "srmd-ncnn-vulkan.exe")
        }
        
        # Obtener carpeta y ejecutable (fallback a vacíos si no encuentra)
        # Nota: El .split(" ")[0] es por si el nombre tiene espacios extra, ej: "RealSR (Fotos)" -> "RealSR"
        engine_key = engine.split(" ")[0]
        folder, exe = engine_map.get(engine_key, ("upscaling", ""))
        
        # Construir ruta completa: bin/models/upscaling/{carpeta}/{exe}
        target_dir = os.path.join(UPSCALING_DIR, folder)
        exe_path = os.path.join(target_dir, exe)
        
        is_installed = os.path.exists(exe_path)
        
        # --- Actualizar UI (Botones y Estado) ---
        if is_installed:
            self.upscale_status_label.configure(text="✅ Motor listo", text_color="gray")
            self.start_process_button.configure(state="normal")
            
            # Activar botones de gestión
            if hasattr(self, 'upscale_open_btn'):
                self.upscale_open_btn.configure(state="normal")
                
                # --- CAMBIO AQUÍ: HABILITAR EL BOTÓN ---
                self.upscale_delete_btn.configure(state="normal") 
                # Antes decía: self.upscale_delete_btn.configure(state="disabled") 
        else:
            self.upscale_status_label.configure(text="⚠️ Motor no instalado", text_color="orange")
            
            if hasattr(self, 'upscale_open_btn'):
                self.upscale_open_btn.configure(state="normal") # Permitir abrir para ver dónde instalar
                self.upscale_delete_btn.configure(state="disabled")

            # --- Lógica de Descarga Automática (Solo si NO es silencioso) ---
            if not silent:
                # Importaciones locales para evitar ciclos
                from src.core.setup import get_remote_file_size, format_size, check_and_download_upscaling_tools
                from src.core.constants import UPSCALING_TOOLS
                
                # Buscar info de descarga en las constantes
                tool_info = UPSCALING_TOOLS.get(engine_key)
                
                if tool_info:
                    # 1. Mostrar "Consultando..."
                    self.upscale_status_label.configure(text="Consultando tamaño...", text_color="#52a2f2")
                    self.update()
                    
                    # 2. Obtener peso remoto (HEAD request)
                    file_size = get_remote_file_size(tool_info["url"])
                    size_str = format_size(file_size)
                    
                    # 3. Preguntar al usuario
                    user_response = messagebox.askyesno(
                        "Descargar Motor IA",
                        f"El motor '{engine_key}' no está instalado.\n\n"
                        f"Tamaño de descarga: {size_str}\n\n"
                        "¿Deseas descargarlo ahora?"
                    )
                    
                    if user_response:
                        self.upscale_status_label.configure(text="Iniciando descarga...", text_color="#52a2f2")
                        
                        # Función interna para el hilo de descarga
                        def download_thread():
                            # Callback para actualizar la barra de progreso
                            def progress_cb(text, val):
                                self.app.ui_update_queue.put((
                                    lambda t=text: self.upscale_status_label.configure(text=t), ()
                                ))

                            # ✅ CORRECCIÓN: Pasamos la herramienta específica para que solo descargue esa
                            # engine_key ya contiene "Real-ESRGAN", "Waifu2x", etc.
                            success = check_and_download_upscaling_tools(progress_cb, target_tool=engine_key)
                            
                            if success:
                                # Si termina bien, volvemos a llamar a esta función (silent=True) para refrescar botones
                                self.app.ui_update_queue.put((
                                    lambda: self._on_upscale_model_change(selected_model_friendly, engine, silent=True), ()
                                ))
                            else:
                                self.app.ui_update_queue.put((
                                    lambda: self.upscale_status_label.configure(text="❌ Error descarga", text_color="red"), ()
                                ))

                        threading.Thread(target=download_thread, daemon=True).start()
                    else:
                        self.upscale_status_label.configure(text="⚠️ Descarga cancelada", text_color="orange")

        # ==============================================================================
        # PARTE B: TU CÓDIGO ORIGINAL (ACTUALIZAR MENÚ DE ESCALAS)
        # ==============================================================================
        
        # 🔍 DEBUG: Imprimir para ver qué está pasando
        print(f"DEBUG Upscale: Motor={engine}, Modelo={selected_model_friendly}")
        
        valid_scales = []
        
        if engine == "Real-ESRGAN":
            if selected_model_friendly in REALESRGAN_MODELS:
                valid_scales = REALESRGAN_MODELS[selected_model_friendly]["scales"]
            else:
                print(f"⚠️ ADVERTENCIA: Modelo '{selected_model_friendly}' no encontrado en REALESRGAN_MODELS")
                
        elif engine == "Waifu2x":
            if selected_model_friendly in WAIFU2X_MODELS:
                valid_scales = WAIFU2X_MODELS[selected_model_friendly]["scales"]
                
        elif "RealSR" in engine:
            if selected_model_friendly in REALSR_MODELS:
                valid_scales = REALSR_MODELS[selected_model_friendly]["scales"]
                
        elif "SRMD" in engine:
            if selected_model_friendly in SRMD_MODELS:
                valid_scales = SRMD_MODELS[selected_model_friendly]["scales"]
        
        if not valid_scales:
            print(f"⚠️ ADVERTENCIA: No se encontraron escalas válidas. Usando fallback ['4x']")
            valid_scales = ["4x"]  # Fallback seguro
        
        # ✅ Actualizar el menú con las escalas válidas
        self.upscale_scale_menu.configure(values=valid_scales)
        
        # ✅ Si la escala actual no está en las válidas, cambiar a la primera
        current_scale = self.upscale_scale_menu.get()
        if current_scale not in valid_scales:
            print(f"DEBUG: Cambiando escala de '{current_scale}' a '{valid_scales[0]}'")
            self.upscale_scale_menu.set(valid_scales[0])

    # ==================================================================
    # --- NUEVA LÓGICA DE UI DE ESCALADO ---
    # ==================================================================

    def _on_toggle_resize_frame(self):
        """Muestra u oculta el frame de opciones de escalado."""
        if self.resize_checkbox.get() == 1:
            # Mostrar el frame de opciones
            self.resize_options_frame.pack(fill="x", padx=5, pady=0, after=self.resize_checkbox)
            # Asegurarse de que el frame "Personalizado" se muestre (o no)
            self._on_resize_preset_changed(self.resize_preset_menu.get())
            # Mostrar interpolación DESPUÉS de llamar al preset (para que siempre esté visible)
            if hasattr(self, 'interpolation_frame'):
                self.interpolation_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky="ew")
        else:
            # Ocultar todos los frames
            self.resize_options_frame.pack_forget()
            self.resize_custom_frame.grid_forget()
            if hasattr(self, 'interpolation_frame'):
                self.interpolation_frame.grid_forget()

    def _on_resize_preset_changed(self, selection):
        """Aplica el preset seleccionado o muestra el frame personalizado."""
        # Mapeo de presets a dimensiones (basado en el lado más largo)
        preset_map = {
            "4K UHD (Máx: 3840×2160)": (3840, 2160),
            "2K QHD (Máx: 2560×1440)": (2560, 1440),
            "1080p FHD (Máx: 1920×1080)": (1920, 1080),
            "720p HD (Máx: 1280×720)": (1280, 720),
            "480p SD (Máx: 854×480)": (854, 480),
            "No escalar (Original)": None
        }
        
        if selection == "Personalizado...":
            # Mostrar campos personalizados
            self.resize_custom_frame.grid(row=2, column=0, columnspan=2, padx=10, pady=5, sticky="ew")
        else:
            # Ocultar campos personalizados
            self.resize_custom_frame.grid_forget()
            
            # Aplicar preset automáticamente
            if selection in preset_map:
                dimensions = preset_map[selection]
                if dimensions:
                    width, height = dimensions
                    # Llenar los campos (aunque estén ocultos, se usarán internamente)
                    self.resize_width_entry.delete(0, "end")
                    self.resize_width_entry.insert(0, str(width))
                    self.resize_height_entry.delete(0, "end")
                    self.resize_height_entry.insert(0, str(height))
                    
                    # 🔥 NUEVO: FORZAR checkbox de proporción para presets
                    self.resize_aspect_lock.select()  # ✅ Siempre activado para presets
                    self.resize_aspect_lock.configure(state="disabled")  # 🔒 Bloqueado
                    
                    print(f"Preset aplicado: {width}×{height} (Proporción forzada)")
                else:
                    # "No escalar" - limpiar campos y desbloquear checkbox
                    self.resize_width_entry.delete(0, "end")
                    self.resize_height_entry.delete(0, "end")
                    self.resize_aspect_lock.configure(state="normal")  # 🔓 Desbloquear

    # ==================================================================
    # --- FUNCIONES DE CONVERTIR A VIDEO ---
    # ==================================================================

    def _create_video_options(self):
        """Crea el frame de opciones para 'Convertir a Video'."""
        video_frame = ctk.CTkFrame(self.options_container, fg_color="#2B2B2B")
        
        # --- 0. NUEVO: Nombre del Video ---
        self.video_name_frame = ctk.CTkFrame(video_frame, fg_color="transparent")
        self.video_name_frame.pack(fill="x", padx=10, pady=5, anchor="w")
        self.video_name_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self.video_name_frame, text="Nombre Video:", width=120, anchor="w").grid(row=0, column=0, sticky="w")
        
        self.video_filename_entry = ctk.CTkEntry(
            self.video_name_frame, 
            placeholder_text="Opcional (Auto: Primera Imagen)"
        )
        self.video_filename_entry.bind("<Button-3>", lambda e: self.create_entry_context_menu(self.video_filename_entry))
        self.video_filename_entry.grid(row=0, column=1, sticky="ew")

        Tooltip(self.video_filename_entry, "Nombre del archivo de video final.\nSi lo dejas vacío, se usará el nombre de la primera imagen de la lista.", delay_ms=1000)
        
        # --- 1. Resolución ---
        self.res_frame = ctk.CTkFrame(video_frame, fg_color="transparent")
        self.res_frame.pack(fill="x", padx=10, pady=5, anchor="w")
        self.res_frame.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(self.res_frame, text="Resolución:", width=120, anchor="w").grid(row=0, column=0, sticky="w")
        
        # Inicializamos con valores temporales, se actualizará inmediatamente
        self.video_resolution_menu = ctk.CTkOptionMenu(
            self.res_frame,
            values=["Usar la primera (Auto)", "1920x1080 (1080p)"],
            command=self._on_video_resolution_changed
        )
        self.video_resolution_menu.grid(row=0, column=1, sticky="ew")

        # Frame para resolución personalizada
        self.video_custom_res_frame = ctk.CTkFrame(video_frame, fg_color="transparent")
        # Aquí le decimos que se empaquete DESPUÉS del frame de resolución
        self.video_custom_res_frame.pack(fill="x", padx=10, pady=0, anchor="w", after=self.res_frame)
        self.video_custom_res_frame.grid_columnconfigure((1, 3), weight=1)

        ctk.CTkLabel(self.video_custom_res_frame, text="Ancho:").grid(row=0, column=0, padx=(10, 5), sticky="e")
        self.video_custom_width_entry = ctk.CTkEntry(self.video_custom_res_frame, width=80, placeholder_text="1920")
        self.video_custom_width_entry.grid(row=0, column=1, sticky="w")
        
        ctk.CTkLabel(self.video_custom_res_frame, text="Alto:").grid(row=0, column=2, padx=(10, 5), sticky="e")
        self.video_custom_height_entry = ctk.CTkEntry(self.video_custom_res_frame, width=80, placeholder_text="1080")
        self.video_custom_height_entry.grid(row=0, column=3, sticky="w")
        
        # Ocultar frame personalizado por defecto
        self.video_custom_res_frame.pack_forget()
        
        # --- 2. FPS y Duración ---
        fps_frame = ctk.CTkFrame(video_frame, fg_color="transparent")
        fps_frame.pack(fill="x", padx=10, pady=5, anchor="w")
        fps_frame.grid_columnconfigure((1, 3), weight=1)
        
        ctk.CTkLabel(fps_frame, text="FPS del Video:").grid(row=0, column=0, padx=(0, 5), sticky="e")
        self.video_fps_entry = ctk.CTkEntry(fps_frame, width=80, placeholder_text="30")
        self.video_fps_entry.insert(0, "30")
        self.video_fps_entry.grid(row=0, column=1, sticky="w")

        ctk.CTkLabel(fps_frame, text="Duración (frames):").grid(row=0, column=2, padx=(10, 5), sticky="e")
        self.video_frame_duration_entry = ctk.CTkEntry(fps_frame, width=80, placeholder_text="3")
        self.video_frame_duration_entry.insert(0, "3")
        self.video_frame_duration_entry.grid(row=0, column=3, sticky="w")
        Tooltip(self.video_frame_duration_entry, "Cuántos fotogramas durará cada imagen en pantalla.", delay_ms=1000)

        # --- 3. Modo de Ajuste ---
        fit_frame = ctk.CTkFrame(video_frame, fg_color="transparent")
        fit_frame.pack(fill="x", padx=10, pady=5, anchor="w")
        fit_frame.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(fit_frame, text="Modo de Ajuste:", width=120, anchor="w").grid(row=0, column=0, sticky="w")
        self.video_fit_mode_menu = ctk.CTkOptionMenu(
            fit_frame,
            values=[
                "Mantener Tamaño Original",
                "Ajustar al Fotograma (Barras)",
                "Ajustar al Marco (Recortar)",
            ]
        )
        self.video_fit_mode_menu.grid(row=0, column=1, sticky="ew")

        # Guardar el frame principal
        self.option_frames["VIDEO"] = video_frame

    def _on_video_resolution_changed(self, selection):
        """Muestra u oculta los campos de resolución de video personalizada."""
        # Si seleccionamos "Usar la primera...", ocultamos el personalizado
        if selection == "Personalizado...":
            self.video_custom_res_frame.pack(fill="x", padx=10, pady=0, anchor="w", after=self.res_frame)
        else:
            self.video_custom_res_frame.pack_forget()

    def _process_batch_as_video(self, output_dir, options):
        """
        Prepara la UI e inicia el hilo para la conversión a video.
        """
        # Validaciones específicas de video
        try:
            fps = int(options.get("video_fps", "30"))
            duration = int(options.get("video_frame_duration", "3"))
            if fps <= 0 or duration <= 0:
                raise ValueError("FPS y Duración deben ser positivos")
        except ValueError:
            messagebox.showerror("Valores Inválidos", "FPS y Duración (frames) deben ser números enteros positivos.")
            return

        if options["video_resolution"] == "Personalizado...":
            try:
                width = int(options.get("video_custom_width", "1920"))
                height = int(options.get("video_custom_height", "1080"))
                if width <= 0 or height <= 0:
                    raise ValueError("Dimensiones inválidas")
            except ValueError:
                messagebox.showerror("Resolución Inválida", "El Ancho y Alto personalizados deben ser números enteros positivos.")
                return

        # Preparar UI para procesamiento
        self.is_processing = True
        self.cancel_processing = False
        self.pause_event = threading.Event()
        self.pause_event.set()
        
        self.start_process_button.configure(state="normal", text="Cancelar", 
                                        fg_color="#DC3545", hover_color="#C82333")
        self.import_button.configure(state="disabled")
        
        
        # Iniciar el hilo de video
        threading.Thread(
            target=self._video_thread_target,
            args=(output_dir, options),
            daemon=True
        ).start()

    def _video_thread_target(self, output_dir, options, cancel_event): # <-- ACEPTAR EVENTO
        """
        (HILO DE TRABAJO) Llama al conversor para crear el video
        y maneja los callbacks de la UI.
        """
        # 1. Definir el callback de progreso que el conversor usará
        def progress_callback(phase, progress_pct, message):
            if cancel_event.is_set(): # Chequeo rápido en el callback
                raise UserCancelledError("Proceso cancelado por el usuario.")

            if phase == "Standardizing":
                # Fase A: Estandarizando imágenes
                self.app.after(0, lambda: self.progress_label.configure(text=f"[Fase 1/2] Estandarizando: {message}"))
                self.app.after(0, lambda: self.progress_bar.set(progress_pct / 100.0 * 0.5)) # 0% a 50%
            
            elif phase == "Encoding":
                # Fase B: Codificando video
                self.app.after(0, lambda: self.progress_label.configure(text=f"[Fase 2/2] Codificando: {message}"))
                self.app.after(0, lambda: self.progress_bar.set(0.5 + (progress_pct / 100.0 * 0.5))) # 50% a 100%

        final_video_path = None
        try:
            
            # 1. Obtener el nombre personalizado
            custom_title = options.get("video_custom_title", "")
            
            if custom_title:
                # Si el usuario escribió algo, usarlo
                base_name = custom_title
            else:
                # Si está vacío, usar el nombre de la primera imagen
                if self.file_list_data:
                    
                    # ✅ CORRECCIÓN: Acceder directamente al índice 0
                    first_file_path = self.file_list_data[0][0] 
                    
                    base_name = os.path.splitext(os.path.basename(first_file_path))[0]
                    base_name += "_video" 
                else:
                    base_name = "video_output"

            # 2. Sanitizar el nombre (quitar caracteres prohibidos)
            import re
            base_name = re.sub(r'[<>:"/\\|?*]', '_', base_name)
            
            # 3. Obtener extensión
            video_format_str = options.get("format")
            # Extraer extensión del string ".mp4 (H.264)" -> ".mp4"
            video_format_ext = video_format_str.split(" ")[0].lower() if video_format_str else ".mp4"
            
            output_filename = f"{base_name}{video_format_ext}"
            output_path = os.path.join(output_dir, output_filename)
            
            # 3. Manejar conflicto (El resto del código sigue igual)
            conflict_policy = self.conflict_policy_menu.get()
            if os.path.exists(output_path):
                action = self._handle_conflict(output_path, conflict_policy)
                if action == "skip":
                    raise Exception("Omitido: El archivo de video ya existe.")
                elif action == "rename":
                    output_path = self._get_unique_filename(output_path)
            
            # ✅ CORRECCIÓN CRÍTICA: Sanitizar la lista de datos para el convertidor de video
            # ImageConverter espera [(ruta, pagina), ...], no listas de 4 elementos.
            clean_file_list = []
            for item in self.file_list_data:
                # Extraemos solo los dos primeros elementos
                clean_file_list.append((item[0], item[1]))

            # 4. Iniciar el proceso pasando la LISTA LIMPIA
            final_video_path = self.image_converter.create_video_from_images(
                file_data_list=clean_file_list, # <--- USAR LA LISTA LIMPIA
                output_path=output_path,
                options=options,
                progress_callback=progress_callback,
                cancellation_event=cancel_event
            )
            
            # 5. Importar a Adobe si está activado
            if not cancel_event.is_set() and self.auto_import_checkbox.get():
                self.app.after(500, self._import_to_adobe, [final_video_path])

            # 6. Mostrar resumen
            if not cancel_event.is_set():
                summary = f"✅ Video Creado: {os.path.basename(final_video_path)}"
                self.app.after(0, lambda s=summary: self.progress_label.configure(text=s))
                self.app.after(0, lambda: self.progress_bar.set(1.0))
                self.app.after(0, lambda: messagebox.showinfo("Proceso Completado", summary))
            else:
                self.app.after(0, lambda: self.progress_label.configure(text="⚠️ Proceso de video cancelado."))

        except UserCancelledError:
             self.app.after(0, lambda: self.progress_label.configure(text="⚠️ Proceso de video cancelado."))
        except Exception as e:
            error_msg = f"Error al crear video: {e}"
            print(f"ERROR: {error_msg}")
            self.app.after(0, lambda: messagebox.showerror("Error", error_msg))
            self.app.after(0, lambda: self.progress_bar.set(0))
            
        finally:
            # REACTIVAR BOTONES Y RESTAURAR TEXTO
            self.is_processing = False
            
            # Restaurar botón de inicio
            self.app.after(0, lambda: self.start_process_button.configure(
                state="normal", text="Iniciar Proceso", 
                fg_color=self.PROCESS_BTN_COLOR, hover_color=self.PROCESS_BTN_HOVER))
            
            # ✅ CORRECCIÓN: Reactivar el botón único de importar
            if hasattr(self, 'import_button'):
                self.app.after(0, lambda: self.import_button.configure(state="normal"))

    # ==================================================================
    # --- FUNCIONES DE INICIALIZACIÓN Y LÓGICA (STUBS) ---
    # ==================================================================

    def _initialize_ui_settings(self):
        """Carga la configuración guardada en la UI al iniciar."""
        
        # 1. Rutas y Auto-Import (Código existente)
        image_path = self.app.image_output_path
        if image_path:
            self.output_path_entry.delete(0, 'end')
            self.output_path_entry.insert(0, image_path)
            self.last_processed_output_dir = image_path 
            self.open_folder_button.configure(state="normal")
        else:
            try:
                from pathlib import Path
                downloads_path = str(Path.home() / "Downloads")
                self.output_path_entry.insert(0, downloads_path)
                self.app.image_output_path = downloads_path
                self.open_folder_button.configure(state="normal")
            except: pass
        
        if self.app.image_auto_import_saved:
            self.auto_import_checkbox.select()
        else:
            self.auto_import_checkbox.deselect()

        # 2. Cargar Herramientas de Imagen
        settings = getattr(self.app, 'image_settings', {})
        
        # --- CORRECCIÓN CRÍTICA: NO RETORNAR SI ESTÁ VACÍO ---
        # Antes había un "if not settings: return" aquí. Lo quitamos.
        # Si settings está vacío, usaremos diccionarios vacíos {} para cargar los defaults.
        # -----------------------------------------------------
        
        try:
            # -- Formato --
            saved_format = settings.get("format", "PNG") # Default PNG
            self.format_menu.set(saved_format)
            self._on_format_changed(saved_format)

            # -- Resize --
            res = settings.get("resize", {})
            if res.get("enabled"): self.resize_checkbox.select()
            else: self.resize_checkbox.deselect()
            
            if res.get("preset"): self.resize_preset_menu.set(res["preset"])
            if res.get("width"): 
                self.resize_width_entry.delete(0, 'end')
                self.resize_width_entry.insert(0, res["width"])
            if res.get("height"):
                self.resize_height_entry.delete(0, 'end')
                self.resize_height_entry.insert(0, res["height"])
            if res.get("lock"): self.resize_aspect_lock.select()
            else: self.resize_aspect_lock.deselect()
            if res.get("interpolation"): self.interpolation_menu.set(res["interpolation"])
            
            self._on_toggle_resize_frame()
            # Solo aplicar preset si hay uno guardado, si no, dejar default
            if res.get("preset"):
                self._on_resize_preset_changed(res.get("preset"))

            # -- Canvas --
            can = settings.get("canvas", {})
            if can.get("enabled"): self.canvas_checkbox.select()
            else: self.canvas_checkbox.deselect()
            
            if can.get("option"): self.canvas_option_menu.set(can["option"])
            if can.get("margin"):
                self.canvas_margin_entry.delete(0, 'end')
                self.canvas_margin_entry.insert(0, can["margin"])
            if can.get("width"):
                self.canvas_width_entry.delete(0, 'end')
                self.canvas_width_entry.insert(0, can["width"])
            if can.get("height"):
                self.canvas_height_entry.delete(0, 'end')
                self.canvas_height_entry.insert(0, can["height"])
            if can.get("position"): self.canvas_position_menu.set(can["position"])
            if can.get("overflow"): self.canvas_overflow_menu.set(can["overflow"])
            
            self._on_toggle_canvas_frame()

            # -- Background --
            bg = settings.get("background", {})
            if bg.get("enabled"): self.background_checkbox.select()
            else: self.background_checkbox.deselect()
            
            if bg.get("type"): self.background_type_menu.set(bg["type"])
            if bg.get("color"):
                self.bg_color_entry.delete(0, 'end')
                self.bg_color_entry.insert(0, bg["color"])
            if bg.get("grad_c1"):
                self.bg_gradient_color1_entry.delete(0, 'end')
                self.bg_gradient_color1_entry.insert(0, bg["grad_c1"])
            if bg.get("grad_c2"):
                self.bg_gradient_color2_entry.delete(0, 'end')
                self.bg_gradient_color2_entry.insert(0, bg["grad_c2"])
            if bg.get("direction"): self.bg_gradient_direction_menu.set(bg["direction"])
            
            self._on_toggle_background_frame()

            # CORRECCIÓN: Asegurar inicialización incluso sin settings
            # -- Rembg (IA) --
            rem = settings.get("rembg", {})
            
            # 1. Restaurar estado del checkbox principal
            if rem.get("enabled"): 
                self.rembg_checkbox.select()
            else: 
                self.rembg_checkbox.deselect()
            
            # NUEVO: Restaurar estado de GPU (Default True si no existe)
            if rem.get("gpu", True):
                self.rembg_gpu_checkbox.select()
            else:
                self.rembg_gpu_checkbox.deselect()

            # 2. Obtener familia guardada o usar default
            saved_family = rem.get("family", "Rembg Standard (U2Net)")
            self.rembg_family_menu.set(saved_family)
            
            # 3. CRÍTICO: Forzar la población del menú de modelos AHORA (SILENCIOSAMENTE)
            # Esto llenará el segundo menú con los valores correctos basados en la familia
            self._on_rembg_family_change(saved_family, silent=True)
            
            # 4. Establecer el modelo específico (si existe y es válido)
            saved_model = rem.get("model")
            if saved_model:
                current_values = self.rembg_model_menu.cget("values")
                if current_values and saved_model in current_values:
                    self.rembg_model_menu.set(saved_model)
                    # ✅ ESTO ES CORRECTO: Pasamos silent=True para no activar popups al inicio
                    self._on_rembg_model_change(saved_model, silent=True)
            
            # -- Rembg (IA) --            
            # 5. Mostrar u ocultar el panel (CON SILENCIO)
            self._on_toggle_rembg_frame(silent=True) 

            # -- Upscaling (IA) --
            if settings.get("upscale_enabled"): self.upscale_checkbox.select()
            else: self.upscale_checkbox.deselect()
            
            if settings.get("upscale_engine"): 
                self.upscale_engine_menu.set(settings["upscale_engine"])
                # Importante: Actualizar los modelos disponibles para este motor (CON SILENCIO)
                self._on_upscale_engine_change(settings["upscale_engine"], silent=True) 
                
            if settings.get("upscale_model_friendly"):
                current_models = self.upscale_model_menu.cget("values")
                if settings["upscale_model_friendly"] in current_models:
                    self.upscale_model_menu.set(settings["upscale_model_friendly"])
                    # Actualizar escalas y botones (CON SILENCIO)
                    self._on_upscale_model_change(settings["upscale_model_friendly"], silent=True) 

            if settings.get("upscale_scale"): self.upscale_scale_menu.set(settings["upscale_scale"])
            if settings.get("upscale_denoise"): self.upscale_denoise_menu.set(settings["upscale_denoise"])
            if settings.get("upscale_tile"): 
                self.upscale_tile_entry.delete(0, "end")
                self.upscale_tile_entry.insert(0, settings["upscale_tile"])
            if settings.get("upscale_tta"): self.upscale_tta_check.select()
            else: self.upscale_tta_check.deselect()
            
            self._on_toggle_upscale_frame()
            
        except Exception as e:
            print(f"ERROR al restaurar configuración de imágenes: {e}")

    def save_settings(self):
        """Guarda la configuración de esta pestaña en la app principal."""
        if not hasattr(self, 'app'):
            return
            
        # Guardar ruta y auto-import (ya existían)
        self.app.image_output_path = self.output_path_entry.get()
        if hasattr(self, 'auto_import_checkbox'):
             self.app.image_auto_import_saved = self.auto_import_checkbox.get() == 1
        
        # --- NUEVO: Guardar estado de herramientas ---
        current_settings = {
            "format": self.format_menu.get(),
            
            "resize": {
                "enabled": self.resize_checkbox.get(),
                "preset": self.resize_preset_menu.get(),
                "width": self.resize_width_entry.get(),
                "height": self.resize_height_entry.get(),
                "lock": self.resize_aspect_lock.get(),
                "interpolation": self.interpolation_menu.get()
            },
            
            "canvas": {
                "enabled": self.canvas_checkbox.get(),
                "option": self.canvas_option_menu.get(),
                "margin": self.canvas_margin_entry.get(),
                "width": self.canvas_width_entry.get(),
                "height": self.canvas_height_entry.get(),
                "position": self.canvas_position_menu.get(),
                "overflow": self.canvas_overflow_menu.get()
            },
            
            "background": {
                "enabled": self.background_checkbox.get(),
                "type": self.background_type_menu.get(),
                "color": self.bg_color_entry.get(),
                "grad_c1": self.bg_gradient_color1_entry.get(),
                "grad_c2": self.bg_gradient_color2_entry.get(),
                "direction": self.bg_gradient_direction_menu.get()
                # No guardamos la ruta de imagen de fondo porque puede cambiar/borrarse
            },
            
            "rembg": {
                "enabled": self.rembg_checkbox.get() == 1,
                "gpu": self.rembg_gpu_checkbox.get() == 1,
                "family": self.rembg_family_menu.get(),
                "model": self.rembg_model_menu.get()
            },
            
            # --- NUEVAS OPCIONES DE REESCALADO (Asegúrate de que esto también esté guardado si no lo estaba) ---
            "upscale_enabled": self.upscale_checkbox.get() == 1,
            "upscale_engine": self.upscale_engine_menu.get(),
            "upscale_model_friendly": self.upscale_model_menu.get(), 
            "upscale_scale": self.upscale_scale_menu.get(),
            "upscale_denoise": self.upscale_denoise_menu.get(),
            "upscale_tile": self.upscale_tile_entry.get(),
            "upscale_tta": self.upscale_tta_check.get() == 1
        }
        
        # Enviar a la app principal
        self.app.image_settings = current_settings

    # ==================================================================
    # --- LÓGICA DE LA LISTA DE ARCHIVOS (PANEL IZQUIERDO) ---
    # ==================================================================

    def _get_temp_dir(self):
        """Crea y devuelve un directorio temporal dedicado para imágenes web."""
        try:
            path = os.path.join(tempfile.gettempdir(), "dowp_images")
            os.makedirs(path, exist_ok=True)
            print(f"INFO: Carpeta temporal de imágenes en: {path}")
            return path
        except Exception as e:
            print(f"ADVERTENCIA: No se pudo crear la carpeta temporal, usando 'temp': {e}")
            return tempfile.gettempdir()

    def _on_analyze_url(self):
        """Inicia el hilo de análisis de URL."""
        url = self.url_entry.get().strip()
        if not url or self.is_analyzing_url:
            return

        self.is_analyzing_url = True
        self.analyze_button.configure(state="disabled", text="...")
        self.progress_label.configure(text=f"Analizando URL: {url[:50]}...")
        
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()

        # Iniciar el análisis en un hilo para no congelar la UI
        threading.Thread(
            target=self._analyze_url_thread,
            args=(url,),
            daemon=True
        ).start()

    def _get_thumbnail_from_url(self, url):
        """
        (HILO DE TRABAJO) Llama a yt-dlp con opciones GENÉRICAS
        para extraer solo la miniatura.
        """
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'noplaylist': True,
            'ignoreerrors': True,
            'timeout': 20, # 20 segundos de tiempo límite
        }
        
        # Re-usar la lógica de cookies de la pestaña de descarga única
        # (Esto es crucial para videos privados o con restricción de edad)
        try:
            single_tab = self.app.single_tab
            cookie_mode = single_tab.cookie_mode_menu.get()
            
            if cookie_mode == "Archivo Manual..." and single_tab.cookie_path_entry.get():
                ydl_opts['cookiefile'] = single_tab.cookie_path_entry.get()
            elif cookie_mode != "No usar":
                browser_arg = single_tab.browser_var.get()
                profile = single_tab.browser_profile_entry.get()
                if profile:
                    browser_arg += f":{profile}"
                ydl_opts['cookiesfrombrowser'] = (browser_arg,)
        except Exception as e:
            print(f"ADVERTENCIA: No se pudieron cargar las cookies: {e}")

        try:
            # Extraer información
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
            
            if not info or not info.get('thumbnail'):
                return None, "No se encontró miniatura (info dict vacío)."
                
            # Éxito: retorna la URL de la miniatura
            return info.get('thumbnail'), None 

        except Exception as e:
            print(f"DEBUG: _get_thumbnail_from_url falló: {e}")
            return None, str(e)

    def _analyze_url_thread(self, url):
        """
        (Hilo de trabajo) Implementa la lógica híbrida:
        1. Intenta descargar como imagen directa.
        2. Si falla, usa yt-dlp para obtener la miniatura.
        """
        try:
            # --- Opción 1: Intentar como imagen directa ---
            direct_image_exts = ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.svg', '.pdf')
            parsed_path = urlparse(url).path
            
            # --- CORRECCIÓN: Generar nombre ÚNICO ---
            original_name = os.path.basename(parsed_path)
            name, ext = os.path.splitext(original_name)
            if not ext: ext = ".jpg" # Fallback si no hay extensión
            
            # Crear nombre único: nombre_uuid.ext
            unique_suffix = str(uuid.uuid4())[:8]
            filename = f"{name}_{unique_suffix}{ext}"
            # ----------------------------------------
            
            if url.lower().endswith(direct_image_exts):
                print(f"INFO: Detectada URL de imagen directa: {filename}")
                temp_filepath = os.path.join(self.temp_image_dir, filename)
                
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                
                with open(temp_filepath, 'wb') as f:
                    f.write(response.content)
                
                self.app.after(0, self._process_imported_files, [temp_filepath])
                self.app.after(0, lambda fn=filename: self.progress_label.configure(text=f"Añadido: {fn}"))
                self.app.after(0, lambda: self.progress_bar.set(1.0))
            
            else:
                # --- Opción 2: Es una página multimedia (usar yt-dlp) ---
                print(f"INFO: URL no directa. Usando yt-dlp para buscar miniatura...")
                self.app.after(0, lambda: self.progress_label.configure(text="Buscando miniatura con yt-dlp..."))
                
                thumbnail_url, error_msg = self._get_thumbnail_from_url(url)
                
                if error_msg or not thumbnail_url:
                    if error_msg and "is not a valid URL" in error_msg:
                         raise Exception(f"La URL no es válida: {url[:50]}...")
                    raise Exception(error_msg or "No se encontró una miniatura en esta URL.")

                # --- CORRECCIÓN: Generar nombre ÚNICO para la miniatura ---
                original_thumb_name = os.path.basename(urlparse(thumbnail_url).path)
                if '?' in original_thumb_name:
                    original_thumb_name = original_thumb_name.split('?')[0]
                
                name, ext = os.path.splitext(original_thumb_name)
                if not ext: ext = ".jpg"
                
                # Crear nombre único: thumbnail_timestamp_uuid.ext
                # Esto evita que 'maxresdefault.jpg' se repita
                unique_id = f"{int(time.time())}_{str(uuid.uuid4())[:6]}"
                thumb_filename = f"{name}_{unique_id}{ext}"
                # ----------------------------------------------------------

                print(f"INFO: Miniatura encontrada. Descargando como: {thumb_filename}")
                temp_filepath = os.path.join(self.temp_image_dir, thumb_filename)
                
                response = requests.get(thumbnail_url, timeout=10)
                response.raise_for_status()
                
                with open(temp_filepath, 'wb') as f:
                    f.write(response.content)
                
                self.app.after(0, self._process_imported_files, [temp_filepath])
                self.app.after(0, lambda tfn=thumb_filename: self.progress_label.configure(text=f"Añadida miniatura: {tfn}"))
                self.app.after(0, lambda: self.progress_bar.set(1.0))

        except Exception as e:
            print(f"ERROR: No se pudo añadir desde URL: {e}")
            error_msg = str(e) 
            self.app.after(0, lambda: self.progress_label.configure(text=f"Error: {error_msg}"))
            self.app.after(0, lambda: self.progress_bar.set(0))
        
        finally:
            self.is_analyzing_url = False
            self.app.after(0, lambda: self.analyze_button.configure(state="normal", text="Añadir"))
            self.app.after(0, lambda: self.url_entry.delete(0, "end"))
            
            self.app.after(0, self.progress_bar.stop)
            self.app.after(0, lambda: self.progress_bar.configure(mode="determinate"))

    def _on_image_list_drop(self, event):
        """
        Maneja archivos Y carpetas soltados.
        Lanza un hilo para no congelar la UI si la carpeta es grande.
        """
        try:
            # Obtener las rutas crudas
            paths = self.tk.splitlist(event.data)
            
            if not paths:
                return

            print(f"INFO: Drop detectado con {len(paths)} elementos. Iniciando escaneo...")
            
            # Mostrar feedback visual inmediato
            if hasattr(self, 'list_status_label'):
                self.list_status_label.configure(text="⏳ Escaneando carpeta(s)...")
            
            # IMPORTANTE: Lanzar el escaneo en un hilo aparte
            # para no congelar la ventana si la carpeta es gigante
            threading.Thread(
                target=self._scan_and_import_dropped_paths,
                args=(paths,),
                daemon=True
            ).start()
            
        except Exception as e:
            print(f"ERROR en Drag & Drop: {e}")
            import traceback
            traceback.print_exc()

    def _on_import_files(self):
        """Abre el diálogo para seleccionar MÚLTIPLES ARCHIVOS."""
        filetypes = [
            ("Archivos de Imagen Compatibles", " ".join(self.COMPATIBLE_EXTENSIONS)),
            ("Todos los archivos", "*.*")
        ]
        
        filepaths = filedialog.askopenfilenames(
            title="Importar Archivos de Imagen",
            filetypes=filetypes
        )
        self.app.lift()
        self.app.focus_force()
        
        if filepaths:
            print(f"INFO: Importando {len(filepaths)} archivos...")
            self._process_imported_files(filepaths)

    def _on_import_folder(self):
        """Abre el diálogo para seleccionar UNA CARPETA y la escanea recursivamente."""
        folder_path = filedialog.askdirectory(
            title="Importar Carpeta (se escaneará recursivamente)"
        )
        self.app.lift()
        self.app.focus_force()
        
        if not folder_path:
            return

        print(f"INFO: Escaneando carpeta: {folder_path}")
        self._toggle_import_buttons("disabled") # Deshabilitar botones
        self.list_status_label.configure(text="Escaneando carpeta...")
        
        # Iniciar el escaneo en un hilo separado para no congelar la UI
        threading.Thread(
            target=self._search_folder_thread, 
            args=(folder_path,), 
            daemon=True
        ).start()

    def _show_import_menu(self):
        """Despliega el menú de opciones de importación."""
        menu = Menu(self, tearoff=0)
        menu.add_command(label="Seleccionar Archivos...", command=self._on_import_files)
        menu.add_command(label="Escanear Carpeta...", command=self._on_import_folder)
        
        # Calcular posición debajo del botón
        try:
            x = self.import_button.winfo_rootx()
            y = self.import_button.winfo_rooty() + self.import_button.winfo_height()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _process_imported_files(self, filepaths):
        """
        Procesa una lista de archivos. Muestra el diálogo de multi-página
        si es necesario antes de añadirlos a la lista.
        """
        files_to_add = [] # Esta será la lista de (filepath, page_num)
        
        for path in filepaths:
            # 1. Usar el "Radar" para contar páginas
            page_count = self.image_processor.get_document_page_count(path)
            
            if page_count == 1:
                # 2a. Si solo tiene 1 página, añadirlo como antes
                files_to_add.append( (path, 1) )
                
            else:
                # 2b. Si tiene múltiples páginas, mostrar el diálogo
                filename = os.path.basename(path)
                dialog = MultiPageDialog(self, filename, page_count)
                range_string = dialog.get_result() # Esto PAUSA la función
                
                if range_string:
                    # 3. El usuario aceptó. Parsear el rango.
                    page_numbers = self._parse_page_range(range_string, page_count)
                    
                    if not page_numbers:
                        messagebox.showerror("Rango Inválido", f"El rango '{range_string}' no es válido.", parent=self)
                        continue # Saltar este archivo

                    # 4. Añadir cada página como un item separado
                    for page_num in page_numbers:
                        files_to_add.append( (path, page_num) )
        
        # 5. Añadir todos los items recopilados a la lista de la UI
        if files_to_add:
            self._add_files_to_list(files_to_add)

    def _parse_page_range(self, range_string, max_pages):
        """
        Convierte un string como "1-3, 5, 8-10" en una lista [1, 2, 3, 5, 8, 9, 10].
        """
        pages = set()
        try:
            parts = range_string.split(',')
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                
                if '-' in part:
                    # Es un rango (ej: "5-10")
                    start_str, end_str = part.split('-')
                    start = int(start_str.strip())
                    end = int(end_str.strip())
                    
                    if start <= 0 or end > max_pages or start > end:
                        raise ValueError(f"Rango inválido {start}-{end}")
                        
                    for i in range(start, end + 1):
                        pages.add(i)
                else:
                    # Es un número único (ej: "8")
                    page = int(part)
                    if page <= 0 or page > max_pages:
                         raise ValueError(f"Página inválida {page}")
                    pages.add(page)
                    
            return sorted(list(pages))
        except Exception as e:
            print(f"Error parseando el rango '{range_string}': {e}")
            return None # Devuelve None si hay un error

    def _search_folder_thread(self, folder_path):
        """(Hilo de trabajo) Recorre recursivamente la carpeta y encuentra archivos."""
        found_files = []
        try:
            for root, _, files in os.walk(folder_path, topdown=True):
                for file in files:
                    # Comprobar si la extensión es compatible
                    if file.lower().endswith(self.COMPATIBLE_EXTENSIONS):
                        full_path = os.path.join(root, file)
                        found_files.append(full_path)
        except Exception as e:
            print(f"ERROR: Falló el escaneo de carpeta: {e}")
            
        print(f"INFO: Escaneo completo. Se encontraron {len(found_files)} archivos.")
        
        # Enviar los archivos encontrados de vuelta al hilo principal (UI)
        if found_files:
            # En lugar de llamar a _add_files_to_list, el hilo
            # llama al nuevo procesador en la UI principal
            self.app.after(0, self._process_imported_files, found_files)
        
        # Reactivar botones en el hilo principal
        self.app.after(0, self._toggle_import_buttons, "normal")

    def _toggle_import_buttons(self, state):
        """Habilita o deshabilita el botón de menú de importación."""
        if hasattr(self, 'import_button'):
            self.import_button.configure(state=state)

    def _on_paste_list(self):
        """
        Pega el contenido del portapapeles.
        Prioridad 1: Datos de imagen (pixeles).
        Prioridad 2: Texto (rutas de archivo).
        """
        try:
            # --- Prioridad 1: Intentar obtener DATOS DE IMAGEN ---
            img = ImageGrab.grabclipboard()
            
            if img:
                print("INFO: Detectada imagen en el portapapeles.")
                # Generar un nombre de archivo único
                filename = f"clipboard_{int(time.time())}.png"
                temp_filepath = os.path.join(self.temp_image_dir, filename)
                
                # Guardar como PNG para preservar transparencia
                img.save(temp_filepath, "PNG")
                print(f"INFO: Imagen de portapapeles guardada en: {temp_filepath}")
                
                self._process_imported_files([temp_filepath])
                return # ¡Éxito! Terminar aquí.

        except Exception as e:
            # Esto puede fallar si el clipboard no contiene una imagen
            print(f"DEBUG: No se pudo obtener imagen de clipboard ({e}). Probando texto...")
        
        # --- Prioridad 2: Fallback a TEXTO (Rutas de archivo) ---
        try:
            content = self.clipboard_get()
            filepaths = [path.strip() for path in content.splitlines() if path.strip()]
            
            valid_files = [path for path in filepaths if os.path.exists(path) and path.lower().endswith(self.COMPATIBLE_EXTENSIONS)]
            
            if valid_files:
                print(f"INFO: Pegando {len(valid_files)} rutas de archivo válidas desde el portapapeles.")
                self._process_imported_files(valid_files)
            else:
                print("INFO: No se encontraron rutas de archivo válidas en el portapapeles.")
                
        except Exception as e:
            print(f"ERROR: No se pudo pegar desde el portapapeles: {e}")

    def _on_clear_list(self):
        """Limpia la lista de archivos y los datos internos."""
        print("Lógica para limpiar la lista...")
        self.file_list_data.clear()
        self.file_list_box.delete(0, "end")
        
        # Limpiar caché de miniaturas
        with self.thumbnail_lock:
            self.thumbnail_cache.clear()
        
        # Limpiar el visor (recrear el placeholder)
        for widget in self.viewer_frame.winfo_children():
            widget.destroy()
        
        self.viewer_placeholder = ctk.CTkLabel(
            self.viewer_frame, 
            text="Selecciona un archivo de la lista para previsualizarlo",
            text_color="gray"
        )
        self.viewer_placeholder.place(relx=0.5, rely=0.5, anchor="center")
        
        # Limpiar el título
        self.title_entry.delete(0, "end")
        
        # Actualizar estado
        self._update_list_status()
        self._update_video_resolution_menu_options()

    def _on_delete_selected(self, event=None):
        """Elimina los ítems seleccionados de la lista (optimizado)."""
        
        selected_indices = self.file_list_box.curselection()
        
        if not selected_indices:
            print("INFO: No hay nada seleccionado para borrar.")
            return

        print(f"INFO: Borrando {len(selected_indices)} ítems seleccionados.")

        # ⭐ NUEVO: Borrar del caché usando la CLAVE CORRECTA
        with self.thumbnail_lock:
            for index in selected_indices:
                if index < len(self.file_list_data):
                    # 1. Obtener los datos del ítem (que ahora es una lista [ruta, pag, out, titulo])
                    item_data = self.file_list_data[index]
                    
                    # 2. Extraer la ruta y la página (soportando tuplas antiguas o listas nuevas)
                    if isinstance(item_data, (list, tuple)):
                        file_path = item_data[0]
                        page_num = item_data[1]
                    else:
                        file_path = item_data
                        page_num = 1 # Default
                    
                    # 3. Reconstruir la clave de texto única que usa el caché
                    cache_key = f"{file_path}::{page_num}"
                    
                    # 4. Eliminar usando esa clave
                    if cache_key in self.thumbnail_cache:
                        self.thumbnail_cache.pop(cache_key, None)
        
        # CRÍTICO: Debemos iterar en reversa para no arruinar los índices al borrar
        for index in reversed(selected_indices):
            self.file_list_box.delete(index)
            self.file_list_data.pop(index)
        
        # Limpiar visor si borramos el seleccionado actual
        if not self.file_list_data:
            self.title_entry.delete(0, "end")
            self._display_thumbnail_in_viewer(None, None)
            if hasattr(self, 'copy_result_button'):
                self.copy_result_button.configure(state="disabled")
        
        # Llamar a la función de estado centralizada
        self._update_list_status()
        self._update_video_resolution_menu_options()
    
    def _on_file_select(self, event=None):
        """
        Se activa al hacer clic o usar las flechas.
        Carga la vista previa/título y actualiza el estado de los botones.
        """
        # 1. Actualizar estado de botones generales (Borrar, etc)
        self._update_list_status()
        
        selected_indices = self.file_list_box.curselection()
        
        if not selected_indices:
            self.title_entry.delete(0, "end")
            self._display_thumbnail_in_viewer(None, None)
            # Deshabilitar copiar si no hay selección
            if hasattr(self, 'copy_result_button'):
                self.copy_result_button.configure(state="disabled")
            self.current_selected_output_path = None
            return
            
        # 2. Lógica para el Visor, Título y BOTÓN DE COPIAR
        first_index = selected_indices[0]
        try:
            # Obtener datos del ítem seleccionado
            item_data = self.file_list_data[first_index]
            
            filepath = item_data[0]
            page_num = item_data[1]
            
            # ✅ CORRECCIÓN: Lectura segura de índices
            output_path = item_data[2] if len(item_data) > 2 else None
            saved_title = item_data[3] if len(item_data) > 3 else None  # <--- BLINDAJE AQUÍ
            
            self.current_selected_output_path = output_path

            # Actualizar estado del botón COPIAR
            if hasattr(self, 'copy_result_button'):
                if output_path and os.path.exists(output_path):
                    # Verificar si es una imagen copiable
                    ext = os.path.splitext(output_path)[1].lower()
                    if ext in [".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp", ".ico"] and os.path.isfile(output_path):
                        # ✅ CAMBIO AQUÍ: Usar el color MORADO (Process Color)
                        self.copy_result_button.configure(
                            state="normal", 
                            fg_color=self.PROCESS_BTN_COLOR,      # Morado (#6F42C1)
                            hover_color=self.PROCESS_BTN_HOVER    # Morado oscuro (#59369A)
                        )
                    else:
                        # Deshabilitar (Gris oscuro estándar de disabled)
                        self.copy_result_button.configure(state="disabled")
                else:
                    self.copy_result_button.configure(state="disabled")
            
            # Si ya tenemos un output procesado, mostrarlo en el comparador
            if output_path and os.path.exists(output_path):
                self._start_comparison_viewer(filepath, output_path, page_num)
                
                # Si hay título guardado, usarlo. Si no, usar nombre del archivo de salida
                if saved_title:
                    title_to_show = saved_title
                else:
                    title_to_show = os.path.splitext(os.path.basename(output_path))[0]
                
                self.title_entry.delete(0, "end")
                self.title_entry.insert(0, title_to_show) 
                return
                        
            # ✅ LÓGICA DE TÍTULO MEJORADA
            if saved_title:
                # Si el usuario escribió algo antes, restaurarlo
                title_to_show = saved_title
            else:
                # Si no, generar el default (Nombre archivo + pág)
                title_no_ext = os.path.splitext(os.path.basename(filepath))[0]
                if page_num and self.image_processor.get_document_page_count(filepath) > 1:
                     title_to_show = f"{title_no_ext}_p{page_num}"
                else:
                     title_to_show = title_no_ext

            self.title_entry.delete(0, "end")
            self.title_entry.insert(0, title_to_show)
            
            # 4. La clave de caché AHORA debe incluir la página
            cache_key = f"{filepath}::{page_num}"
            
            # 5. Guardar esta CLAVE ÚNICA como la "última solicitada"
            self.last_preview_path = cache_key

            # 6. Verificar si ya está en caché
            with self.thumbnail_lock:
                if cache_key in self.thumbnail_cache:
                    # ✅ Está en caché, mostrar inmediatamente
                    cached_image = self.thumbnail_cache[cache_key]
                    self._display_cached_thumbnail(cached_image, cache_key)
                    return

            # Vaciar la cola antes de agregar (cancelar solicitudes obsoletas)
            try:
                while True: self.thumbnail_queue.get_nowait()
            except queue.Empty: pass

            # No está en caché, agregar a la cola
            self.thumbnail_queue.put( (filepath, page_num) )
            self._display_thumbnail_in_viewer(None, None, is_loading=True)
            self._start_thumbnail_worker()
            
        except Exception as e:
            print(f"ERROR: No se pudo seleccionar el ítem en el índice {first_index}: {e}")
            self._display_thumbnail_in_viewer(None, None)
    
    def _on_title_entry_change(self, event=None):
        """Guarda el texto del título en la estructura de datos del ítem seleccionado."""
        selected_indices = self.file_list_box.curselection()
        if not selected_indices:
            return
            
        index = selected_indices[0]
        current_text = self.title_entry.get().strip()
        
        # Si el texto está vacío, guardamos None (para que se regenere el default luego)
        value_to_save = current_text if current_text else None
        
        # Guardar en la posición 3 (CustomTitle)
        # Estructura: [path, page, output, title]
        if index < len(self.file_list_data):
            self.file_list_data[index][3] = value_to_save

    def _on_start_process(self):
        """Inicia o cancela el procesamiento de archivos."""
        
        # --- LÓGICA DE CANCELACIÓN (COMO SINGLE_TAB) ---
        if hasattr(self, 'is_processing') and self.is_processing:
            if hasattr(self, 'cancel_event') and self.cancel_event:
                self.cancel_event.set()
            
            self.start_process_button.configure(state="disabled", text="Cancelando...")
            self.progress_label.configure(text="Cancelando proceso...")
            return

        if self.image_converter.gs_exe:
            existe = os.path.exists(self.image_converter.gs_exe)

            if existe:
                import stat

        else:
            print("   ⚠️ gs_exe es None o vacío")
        print("="*60)
        
        # --- ADVERTENCIA DE RASTERIZACIÓN ---
        try:
            if self.format_menu.get() == "No Convertir":
                is_raster_op = (self.resize_checkbox.get() == 1 or
                                self.canvas_checkbox.get() == 1 or
                                self.background_checkbox.get() == 1)
                if is_raster_op:
                    from src.core.constants import IMAGE_INPUT_FORMATS
                    has_vectors = False
                    
                    # 🔴 ERROR ANTERIOR: for f_path, page in self.file_list_data:
                    # ✅ CORRECCIÓN: Iterar el ítem y extraer por índice
                    for item_data in self.file_list_data:
                        # Soportar tupla vieja o lista nueva
                        f_path = item_data[0] 
                        
                        ext = os.path.splitext(f_path)[1].lower()
                        if ext in IMAGE_INPUT_FORMATS:
                            has_vectors = True
                            break
                    if has_vectors:
                        response = messagebox.askyesno(
                            "Advertencia de Conversión",
                            "Tu lista contiene archivos vectoriales (SVG, PDF, AI, etc.) y has seleccionado 'No Convertir', pero también has activado una operación de píxeles (Escalado, Canvas o Fondo).\n\n"
                            "Para aplicar estos efectos, los vectores DEBEN ser convertidos a PNG.\n\n"
                            "¿Deseas continuar?"
                        )
                        if not response:
                            print("INFO: Proceso cancelado por el usuario.")
                            return
        except Exception as e:
            print(f"Error durante la comprobación de advertencia: {e}")
            
        # --- VALIDACIONES ---
        if not self.file_list_data:
            messagebox.showwarning("Sin archivos", "No hay archivos para procesar.")
            return
        
        output_dir = self.output_path_entry.get()
        if not output_dir:
            messagebox.showwarning("Sin carpeta de salida", "Selecciona una carpeta de salida.")
            return
        
        if not os.path.exists(output_dir):
            try: os.makedirs(output_dir, exist_ok=True)
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo crear la carpeta de salida:\n{e}")
                return
        
        if self.create_subfolder_checkbox.get():
            subfolder_name = self.subfolder_name_entry.get() or "DowP Imágenes"
            output_dir = os.path.join(output_dir, subfolder_name)
            try: os.makedirs(output_dir, exist_ok=True)
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo crear la subcarpeta:\n{e}")
                return
        
        self.last_processed_output_dir = output_dir
        self.open_folder_button.configure(state="normal")

        # Validar tamaño objetivo si el escalado está activado
        if self.resize_checkbox.get():
            try:
                width = int(self.resize_width_entry.get())
                height = int(self.resize_height_entry.get())
                
                if width <= 0 or height <= 0:
                    messagebox.showwarning("Dimensiones inválidas", 
                                         "El ancho y alto deben ser mayores a 0.")
                    return
                
                # Validar con el conversor
                is_safe, warning_msg = self.image_converter.validate_target_size((width, height))
                
                if warning_msg:
                    if not is_safe:
                        # Crítico: mostrar error y no continuar
                        messagebox.showerror("Resolución Crítica", warning_msg)
                        return
                    else:
                        # Alto: pedir confirmación
                        response = messagebox.askyesno("Advertencia de Resolución", warning_msg)
                        if not response:
                            return
            
            except ValueError:
                messagebox.showwarning("Dimensiones inválidas", 
                                     "Ingresa valores numéricos válidos para ancho y alto.")
                return
            
        # Validar canvas si está activado
        if self.canvas_checkbox.get():
            canvas_option = self.canvas_option_menu.get()
            
            if canvas_option == "Personalizado...":
                try:
                    canvas_width = int(self.canvas_width_entry.get())
                    canvas_height = int(self.canvas_height_entry.get())
                    
                    if canvas_width <= 0 or canvas_height <= 0:
                        messagebox.showwarning("Dimensiones inválidas", 
                                             "El ancho y alto del canvas deben ser mayores a 0.")
                        return
                    
                    # Validar con el conversor
                    is_safe, warning_msg = self.image_converter.validate_target_size((canvas_width, canvas_height))
                    
                    if warning_msg:
                        if not is_safe:
                            messagebox.showerror("Resolución de Canvas Crítica", warning_msg)
                            return
                        else:
                            response = messagebox.askyesno("Advertencia de Canvas", warning_msg)
                            if not response:
                                return
                
                except ValueError:
                    messagebox.showwarning("Dimensiones inválidas", 
                                         "Ingresa valores numéricos válidos para el canvas.")
                    return
            
            elif canvas_option in ["Añadir Margen Externo", "Añadir Margen Interno"]:
                # Validar margen
                margin_str = self.canvas_margin_entry.get()
                if not margin_str or not margin_str.strip():
                    messagebox.showwarning("Margen inválido", "Ingresa un valor para el margen.")
                    return
                
                try:
                    margin = int(margin_str)
                    if margin <= 0:
                        messagebox.showwarning("Margen inválido", "El margen debe ser mayor a 0.")
                        return
                except ValueError:
                    messagebox.showwarning("Margen inválido", "Ingresa un valor numérico válido para el margen.")
                    return
        
        options = self._gather_conversion_options()
        is_video_export = options.get("format", "").startswith(".")
        
        if is_video_export:
            try:
                fps = int(options.get("video_fps", "30"))
                duration = int(options.get("video_frame_duration", "3"))
                if fps <= 0 or duration <= 0: raise ValueError("FPS/Duración debe ser > 0")
            except ValueError:
                messagebox.showerror("Valores Inválidos", "FPS y Duración (frames) deben ser números enteros positivos.")
                return

            if options["video_resolution"] == "Personalizado...":
                try:
                    width = int(options.get("video_custom_width", "1920"))
                    height = int(options.get("video_custom_height", "1080"))
                    if width <= 0 or height <= 0: raise ValueError("Dimensiones inválidas")
                except ValueError:
                    messagebox.showerror("Resolución Inválida", "El Ancho y Alto personalizados deben ser números enteros positivos.")
                    return

        # --- PREPARAR E INICIAR PROCESO ---
        self.is_processing = True
        self.cancel_event = threading.Event() # <-- EVENTO DE CANCELACIÓN REAL
        self.cancel_event.clear() # No está cancelado
        
        self.start_process_button.configure(state="normal", text="Cancelar", 
                                        fg_color="#DC3545", hover_color="#C82333")
        
        # ✅ CORRECCIÓN: Deshabilitar el nuevo botón único
        self.import_button.configure(state="disabled")
        
        # Iniciar procesamiento en hilo separado...
        threading.Thread(
            target=self._process_files_thread,
            args=(output_dir, self.cancel_event), # <-- PASAR EL EVENTO REAL
            daemon=True
        ).start()

    def _copy_result_to_clipboard(self):
        """
        Copia el archivo SELECCIONADO al portapapeles usando la API nativa de Windows.
        """
        # ✅ CAMBIO: Usar la variable vinculada a la selección actual
        if not hasattr(self, 'current_selected_output_path') or not self.current_selected_output_path:
            return

        file_path = os.path.abspath(self.current_selected_output_path)
        
        if not os.path.exists(file_path):
            messagebox.showerror("Error", "El archivo ya no existe en el disco.")
            # Deshabilitar botón visualmente ya que falló
            self.copy_result_button.configure(state="disabled")
            return

        import ctypes
        from ctypes import wintypes

        try:
            # --- DEFINICIÓN DE TIPOS (CRÍTICO PARA 64-BITS) ---
            kernel32 = ctypes.windll.kernel32
            user32 = ctypes.windll.user32

            kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
            kernel32.GlobalAlloc.restype = ctypes.c_void_p
            kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalLock.restype = ctypes.c_void_p
            kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalUnlock.restype = wintypes.BOOL
            user32.OpenClipboard.argtypes = [ctypes.c_void_p]
            user32.OpenClipboard.restype = wintypes.BOOL
            user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
            user32.SetClipboardData.restype = ctypes.c_void_p
            user32.EmptyClipboard.argtypes = []
            user32.EmptyClipboard.restype = wintypes.BOOL
            user32.CloseClipboard.argtypes = []
            user32.CloseClipboard.restype = wintypes.BOOL

            CF_HDROP = 15
            GHND = 0x0042
            
            class DROPFILES(ctypes.Structure):
                _fields_ = [
                    ("pFiles", ctypes.c_uint32),
                    ("pt_x", ctypes.c_long),
                    ("pt_y", ctypes.c_long),
                    ("fNC", ctypes.c_int),
                    ("fWide", ctypes.c_int),
                ]

            files_list = [file_path]
            file_data = ("\0".join(files_list) + "\0\0").encode("utf-16-le")
            dropfiles_struct_size = ctypes.sizeof(DROPFILES)
            total_size = dropfiles_struct_size + len(file_data)

            hGlobal = kernel32.GlobalAlloc(GHND, total_size)
            if not hGlobal: raise MemoryError("GlobalAlloc falló.")

            ptr = kernel32.GlobalLock(hGlobal)
            if not ptr:
                kernel32.GlobalFree(hGlobal)
                raise Exception("GlobalLock falló.")

            try:
                df = DROPFILES()
                df.pFiles = dropfiles_struct_size 
                df.fWide = 1 
                ctypes.memmove(ptr, ctypes.byref(df), dropfiles_struct_size)
                ctypes.memmove(ptr + dropfiles_struct_size, file_data, len(file_data))
            finally:
                kernel32.GlobalUnlock(hGlobal)

            if not user32.OpenClipboard(None):
                kernel32.GlobalFree(hGlobal)
                raise Exception("OpenClipboard falló.")

            try:
                user32.EmptyClipboard()
                if not user32.SetClipboardData(CF_HDROP, hGlobal):
                    raise Exception("SetClipboardData falló.")
            except Exception as e_clip:
                user32.CloseClipboard()
                kernel32.GlobalFree(hGlobal)
                raise e_clip
            
            user32.CloseClipboard()

            # Feedback visual
            original_text = self.copy_result_button.cget("text")
            original_fg = self.copy_result_button.cget("fg_color")
            self.copy_result_button.configure(text="¡Copiado!", fg_color="#28A745")
            self.after(1500, lambda: self.copy_result_button.configure(text=original_text, fg_color=original_fg))

        except Exception as e:
            print(f"ERROR NATIVO al copiar: {e}")
            messagebox.showerror("Error de Portapapeles", f"No se pudo copiar el archivo:\n{e}")

    def _process_files_thread(self, output_dir, cancel_event):
        """Hilo de trabajo que procesa todos los archivos."""
        
        total_files = len(self.file_list_data)
        processed = 0
        skipped = 0
        errors = 0
        
        # 🔧 NUEVO: Lista detallada de errores
        error_details = []
        
        # 🔧 NUEVO: Resetear el flag al inicio
        self.conversion_complete_event.clear()
        
        # Obtener opciones de conversión
        options = self._gather_conversion_options()

        # --- NUEVO ROUTER: VIDEO vs IMÁGENES ---
        is_video_export = options.get("format", "").startswith(".")
        
        if is_video_export:
            # Llamar a la nueva lógica de video
            self._video_thread_target(output_dir, options, cancel_event)
            return
        # --- FIN DEL ROUTER ---

        # Política de conflictos
        conflict_policy = self.conflict_policy_menu.get()
        
        # Lista de PDFs generados (para combinar al final)
        generated_pdfs = []

        # 🔧 NUEVO: Señalizar que la conversión terminó COMPLETAMENTE
        self.conversion_complete_event.set()
        
        # Lista de archivos exitosos
        successfully_processed_paths = []
        
        try:
            for i, item_data in enumerate(self.file_list_data):
                
                if cancel_event.is_set():
                    print("INFO: Proceso cancelado por el usuario")
                    self.app.after(0, lambda p=processed: self.progress_label.configure(
                        text=f"Cancelado: {p} archivos procesados antes de cancelar"))
                    break
                
                # ✅ CORRECCIÓN: Extracción segura por índices
                # item_data ahora tiene 4 elementos: [input, page, output, title]
                input_path = item_data[0]
                page_num = item_data[1]
                # Ignoramos el resto aquí si no se usan inmediatamente
                
                # Lógica para título personalizado (ya la pusimos antes, pero verifica)
                custom_title = item_data[3] if len(item_data) > 3 else None
                
                filename = os.path.basename(input_path)
                
                # --- CALLBACK DE PROGRESO FINO ---
                def internal_callback(file_pct, message=None):
                    # file_pct: 0 a 100 (puede ser None si solo es mensaje)
                    
                    # Solo actualizar la barra si hay un porcentaje numérico
                    if file_pct is not None:
                        weight_per_file = 100 / total_files
                        base_progress = i * weight_per_file
                        current_contribution = (file_pct / 100.0) * weight_per_file
                        total_global = base_progress + current_contribution
                        
                        self.app.after(0, lambda p=total_global: self.progress_bar.set(p / 100.0))
                    
                    # Actualizar el texto si se proporciona
                    if message:
                        self.app.after(0, lambda t=message: self.progress_label.configure(text=t))
                
                # Actualizar texto inicial del archivo
                self.app.after(0, lambda t=f"Procesando ({i+1}/{total_files}): {filename}": 
                            self.progress_label.configure(text=t))
                
                # 2. Generar el nombre de salida PASANDO EL TÍTULO
                output_filename = self._get_output_filename(input_path, options, page_num, custom_title)
                output_path = os.path.join(output_dir, output_filename)
                
                # Manejar conflictos
                if os.path.exists(output_path):
                    action = self._handle_conflict(output_path, conflict_policy)
                    if action == "skip":
                        print(f"INFO: Omitiendo {filename} (ya existe)")
                        skipped += 1
                        continue
                    elif action == "rename":
                        output_path = self._get_unique_filename(output_path)

                # Convertir archivo CON CALLBACK
                try:
                    success = self.image_converter.convert_file(
                        input_path, 
                        output_path, 
                        options,
                        page_number=page_num,
                        progress_callback=internal_callback,
                        cancellation_event=cancel_event 
                    )
                    
                    if success:
                        processed += 1
                        print(f"✅ Convertido: {filename} → {os.path.basename(output_path)}")
                        
                        # --- CORRECCIÓN: Actualizar solo el output sin romper la estructura ---
                        # La estructura es [input, page, output, title]
                        # Solo actualizamos el índice 2 (output)
                        if i < len(self.file_list_data):
                            # Asegurarnos de que sea una lista mutable
                            if isinstance(self.file_list_data[i], tuple):
                                self.file_list_data[i] = list(self.file_list_data[i])
                            
                            # Si la lista es vieja (3 elementos), la extendemos
                            while len(self.file_list_data[i]) < 4:
                                self.file_list_data[i].append(None)
                                
                            # Guardar la ruta de salida
                            self.file_list_data[i][2] = output_path
                        # ---------------------------------------------------------------------

                        successfully_processed_paths.append(output_path)

                        # Si es PDF y se va a combinar, guardar ruta
                        if options["format"] == "PDF" and options.get("pdf_combine", False):
                            generated_pdfs.append(output_path)
                    else:
                        errors += 1
                        error_details.append((filename, "Error desconocido durante la conversión"))
                        print(f"❌ Error al convertir: {filename}")
                
                except Exception as e:
                    errors += 1
                    error_message = str(e)
                    
                    # 🔧 NUEVO: Categorizar errores comunes
                    if "decompression bomb" in error_message.lower():
                        error_type = "Archivo demasiado grande (posible ataque de descompresión)"
                    elif "could not convert string to float" in error_message.lower():
                        error_type = "SVG corrupto (atributos inválidos)"
                    elif "MAX_TEXT_CHUNK" in error_message:
                        error_type = "Metadatos demasiado grandes (límite de seguridad)"
                    elif "timeout" in error_message.lower():
                        error_type = "Tiempo de espera agotado (archivo muy complejo)"
                    else:
                        error_type = error_message[:100]  # Primeros 100 caracteres
                    
                    error_details.append((filename, error_type))
                    print(f"❌ Error al procesar {filename}: {e}")
            
            # Combinar PDFs si está activado
            if not cancel_event.is_set() and options["format"] == "PDF" and options.get("pdf_combine", False) and len(generated_pdfs) > 1:
                self.app.after(0, lambda: self.progress_label.configure(
                    text=f"Combinando {len(generated_pdfs)} PDFs..."))
                
                # Obtener el nombre personalizado del PDF combinado
                pdf_title = options.get("pdf_combined_title", "combined_output")
                if not pdf_title or pdf_title.strip() == "":
                    pdf_title = "combined_output"

                # Eliminar caracteres inválidos para nombres de archivo
                import re
                pdf_title = re.sub(r'[<>:"/\\|?*]', '_', pdf_title)

                # Asegurar que no tenga extensión .pdf (la añadimos nosotros)
                if pdf_title.lower().endswith(".pdf"):
                    pdf_title = pdf_title[:-4]

                combined_pdf_path = os.path.join(output_dir, f"{pdf_title}.pdf")
                
                # Manejar conflicto del PDF combinado
                if os.path.exists(combined_pdf_path):
                    combined_pdf_path = self._get_unique_filename(combined_pdf_path)
                
                if self.image_converter.combine_pdfs(generated_pdfs, combined_pdf_path):
                    print(f"✅ PDF combinado creado: {os.path.basename(combined_pdf_path)}")
                    
                    # Actualizar nuestra lista de archivos exitosos:
                    for pdf_path in generated_pdfs:
                        if pdf_path in successfully_processed_paths:
                            successfully_processed_paths.remove(pdf_path)
                        
                        try:
                            os.remove(pdf_path)
                        except Exception as e:
                            print(f"ADVERTENCIA: No se pudo eliminar {pdf_path}: {e}")
                    
                    # Añadir el nuevo PDF combinado a la lista
                    successfully_processed_paths.append(combined_pdf_path)
            
            # 🔧 NUEVO: Señalizar que la conversión terminó COMPLETAMENTE
            self.conversion_complete_event.set()
            print("DEBUG: ✅ Todas las conversiones completadas. Señal enviada.")
            
            # Importar a Adobe
            if not cancel_event.is_set() and self.auto_import_checkbox.get():
                print(f"DEBUG: Proceso finalizado. Programando importación a Adobe.")
                self.app.after(0, self._import_to_adobe, successfully_processed_paths)

            # 🔧 NUEVO: Mostrar resumen mejorado
            if not cancel_event.is_set():
                summary = f"✅ Completado: {processed} archivos"
                if skipped > 0:
                    summary += f" ({skipped} omitidos)"
                if errors > 0:
                    summary += f" ({errors} errores)"
                
                # Actualizar la etiqueta inferior (Feedback visual suficiente)
                self.app.after(0, lambda s=summary: self.progress_label.configure(text=s))
                self.app.after(0, lambda: self.progress_bar.set(1.0))
                
                # 🔴 CAMBIO: Solo mostrar el diálogo si hubo ERRORES
                if errors > 0:
                     self.app.after(0, lambda: self._show_process_summary(processed, skipped, errors, error_details))
                else:
                     print(f"INFO: Proceso terminado exitosamente. Resumen: {summary}")

        except Exception as e:
            error_msg = f"Error crítico durante el procesamiento: {e}"
            print(f"ERROR: {error_msg}")
            self.app.after(0, lambda: messagebox.showerror("Error", error_msg))
        
        finally:
            # REACTIVAR BOTONES Y RESTAURAR TEXTO
            self.is_processing = False
            
            # Restaurar botón de inicio
            self.app.after(0, lambda: self.start_process_button.configure(
                state="normal", text="Iniciar Proceso", 
                fg_color=self.PROCESS_BTN_COLOR, hover_color=self.PROCESS_BTN_HOVER))
            
            # ✅ CORRECCIÓN: Reactivar el botón único de importar
            if hasattr(self, 'import_button'):
                self.app.after(0, lambda: self.import_button.configure(state="normal"))

            self.image_converter.clear_ai_sessions()

    def _show_process_summary(self, processed, skipped, errors, error_details):
        """
        Muestra un diálogo de resumen del proceso (Texto plano, sin sugerencias).
        """
        # Construir mensaje base
        detail_msg = f"Convertidos exitosamente: {processed}"
        
        if skipped > 0:
            detail_msg += f"\nOmitidos (ya existían): {skipped}"
        
        if errors > 0:
            detail_msg += f"\n\nErrores encontrados: {errors}"
            
            if error_details:
                detail_msg += "\n\nDetalles de los errores:\n"
                detail_msg += "-" * 50 + "\n"
                
                # Agrupar errores por tipo
                error_groups = {}
                for filename, error_type in error_details:
                    if error_type not in error_groups:
                        error_groups[error_type] = []
                    error_groups[error_type].append(filename)
                
                # Mostrar errores agrupados (Solo descripción y archivos)
                for error_type, files in error_groups.items():
                    detail_msg += f"\n{error_type}\n"
                    for file in files[:3]:  # Mostrar máximo 3 archivos por tipo
                        detail_msg += f"  - {file}\n"
                    if len(files) > 3:
                        detail_msg += f"  ... y {len(files) - 3} más\n"
        
        # Mostrar el diálogo
        messagebox.showinfo("Resumen del Proceso", detail_msg)

    def _wait_for_file_ready(self, filepath, timeout=2.0):
        """
        Espera hasta que un archivo esté completamente escrito y accesible.
        Crítico para importación inmediata en Adobe Premiere.
        """
        import time
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                # Intentar abrir y leer el archivo
                with open(filepath, 'rb') as f:
                    f.read(1)  # Leer el primer byte
                
                # Si llegamos aquí, el archivo está listo
                return True
                
            except (IOError, OSError, PermissionError):
                # Archivo aún no está listo, esperar
                time.sleep(0.05)  # 50ms entre reintentos
        
        # Timeout alcanzado
        print(f"⚠️ ADVERTENCIA: Timeout esperando que esté listo: {os.path.basename(filepath)}")
        return False

    def _gather_conversion_options(self):
        format_selected = self.format_menu.get()
        
        vid_res_selection = self.video_resolution_menu.get() if hasattr(self, 'video_resolution_menu') else "1920x1080 (1080p)"
        
        # Valores por defecto
        vid_width = "1920"
        vid_height = "1080"
        
        if vid_res_selection == "Personalizado...":
            if hasattr(self, 'video_custom_width_entry'):
                vid_width = self.video_custom_width_entry.get()
                vid_height = self.video_custom_height_entry.get()
        
        elif vid_res_selection.startswith("Usar la primera"):
            # Intentar extraer (WxH) del paréntesis
            import re
            match = re.search(r'\((\d+)x(\d+)\)', vid_res_selection)
            if match:
                vid_width = match.group(1)
                vid_height = match.group(2)
            else:
                # Si dice (Auto) o falla, intentamos leerlo en caliente
                dims = self._get_first_image_dimensions()
                if dims:
                    vid_width, vid_height = map(str, dims)
                else:
                    # Fallback extremo si no hay imágenes
                    vid_width, vid_height = "1920", "1080"
        
        else:
            # Es un preset fijo como "1280x720 (720p)"
            try:
                # Tomamos la primera parte antes del espacio "1280x720"
                res_part = vid_res_selection.split(" ")[0]
                vid_width, vid_height = res_part.split("x")
            except:
                pass # Mantener default 1920x1080
        
        # Lógica para obtener el nombre real del archivo para rembg
        selected_family = self.rembg_family_menu.get() if hasattr(self, 'rembg_family_menu') else None
        selected_model_label = self.rembg_model_menu.get() if hasattr(self, 'rembg_model_menu') else None
        
        real_model_name = "u2netp" # Fallback
        
        if selected_family and selected_model_label:
            model_data = REMBG_MODEL_FAMILIES.get(selected_family, {}).get(selected_model_label)
            if model_data:
                # Rembg usa el nombre del archivo SIN extensión como ID de sesión
                # OJO: Para BiRefNet hay que tener cuidado, pero por ahora pasamos el nombre base.
                real_model_name = model_data["file"] 
        
        options = {
            "format": format_selected,
            # Opciones de escalado
            "resize_enabled": self.resize_checkbox.get() == 1,
            "resize_width": self.resize_width_entry.get() if hasattr(self, 'resize_width_entry') and self.resize_width_entry.get() else None,
            "resize_height": self.resize_height_entry.get() if hasattr(self, 'resize_height_entry') and self.resize_height_entry.get() else None,
            "resize_maintain_aspect": self.resize_aspect_lock.get() == 1,
            "interpolation_method": self.interpolation_menu.get() if hasattr(self, 'interpolation_menu') else "Lanczos (Mejor Calidad)",
            # Opciones de canvas
            "canvas_enabled": self.canvas_checkbox.get() == 1 if hasattr(self, 'canvas_checkbox') else False,
            "canvas_option": self.canvas_option_menu.get() if hasattr(self, 'canvas_option_menu') else "Sin ajuste",
            "canvas_width": self.canvas_width_entry.get() if hasattr(self, 'canvas_width_entry') and self.canvas_width_entry.get() else None,
            "canvas_height": self.canvas_height_entry.get() if hasattr(self, 'canvas_height_entry') and self.canvas_height_entry.get() else None,
            "canvas_margin": int(self.canvas_margin_entry.get()) if hasattr(self, 'canvas_margin_entry') and self.canvas_margin_entry.get() and self.canvas_margin_entry.get().isdigit() else 100,
            "canvas_position": self.canvas_position_menu.get() if hasattr(self, 'canvas_position_menu') else "Centro",
            "canvas_overflow_mode": self.canvas_overflow_menu.get() if hasattr(self, 'canvas_overflow_menu') else "Centrar (puede recortar)",
            # Opciones de fondo
            "background_enabled": self.background_checkbox.get() == 1 if hasattr(self, 'background_checkbox') else False,
            "background_type": self.background_type_menu.get() if hasattr(self, 'background_type_menu') else "Color Sólido",
            "background_color": self.bg_color_entry.get() if hasattr(self, 'bg_color_entry') and self.bg_color_entry.get() else "#FFFFFF",
            "background_gradient_color1": self.bg_gradient_color1_entry.get() if hasattr(self, 'bg_gradient_color1_entry') and self.bg_gradient_color1_entry.get() else "#FF0000",
            "background_gradient_color2": self.bg_gradient_color2_entry.get() if hasattr(self, 'bg_gradient_color2_entry') and self.bg_gradient_color2_entry.get() else "#0000FF",
            "background_gradient_direction": self.bg_gradient_direction_menu.get() if hasattr(self, 'bg_gradient_direction_menu') else "Horizontal (Izq → Der)",
            "background_image_path": self.bg_image_entry.get() if hasattr(self, 'bg_image_entry') and self.bg_image_entry.get() else None,
            # PNG
            "png_transparency": self.png_transparency.get() if hasattr(self, 'png_transparency') else True,
            "png_compression": int(self.png_compression_slider.get()) if hasattr(self, 'png_compression_slider') else 6,
            # JPG
            "jpg_quality": int(self.jpg_quality_slider.get()) if hasattr(self, 'jpg_quality_slider') else 90,
            "jpg_subsampling": self.jpg_subsampling.get() if hasattr(self, 'jpg_subsampling') else "4:2:0 (Estándar)",
            "jpg_progressive": self.jpg_progressive.get() if hasattr(self, 'jpg_progressive') else False,
            # WEBP
            "webp_lossless": self.webp_lossless.get() if hasattr(self, 'webp_lossless') else False,
            "webp_quality": int(self.webp_quality_slider.get()) if hasattr(self, 'webp_quality_slider') else 90,
            "webp_transparency": self.webp_transparency.get() if hasattr(self, 'webp_transparency') else True,
            "webp_metadata": self.webp_metadata.get() if hasattr(self, 'webp_metadata') else False,
            # AVIF
            "avif_lossless": self.avif_lossless.get() if hasattr(self, 'avif_lossless') else False,
            "avif_quality": int(self.avif_quality_slider.get()) if hasattr(self, 'avif_quality_slider') else 80,
            "avif_speed": int(self.avif_speed_slider.get()) if hasattr(self, 'avif_speed_slider') else 6,
            "avif_transparency": self.avif_transparency.get() if hasattr(self, 'avif_transparency') else True,
            # PDF
            "pdf_combine": self.pdf_combine.get() if hasattr(self, 'pdf_combine') else False,
            "pdf_combined_title": self.pdf_combined_title_entry.get() if hasattr(self, 'pdf_combined_title_entry') else "combined_output",
            # TIFF
            "tiff_compression": self.tiff_compression.get() if hasattr(self, 'tiff_compression') else "LZW (Recomendada)",
            "tiff_transparency": self.tiff_transparency.get() if hasattr(self, 'tiff_transparency') else True,
            # ICO
            "ico_sizes": {size: checkbox.get() for size, checkbox in self.ico_sizes.items()} if hasattr(self, 'ico_sizes') else {},
            # BMP
            "bmp_rle": self.bmp_rle.get() if hasattr(self, 'bmp_rle') else False,
            
            # --- NUEVAS OPCIONES DE VIDEO ---
            "video_custom_title": self.video_filename_entry.get().strip() if hasattr(self, 'video_filename_entry') else "",
            "video_resolution": "Personalizado...", 
            "video_custom_width": vid_width, 
            "video_custom_height": vid_height,
            "video_fps": self.video_fps_entry.get() if hasattr(self, 'video_fps_entry') else "30",
            "video_frame_duration": self.video_frame_duration_entry.get() if hasattr(self, 'video_frame_duration_entry') else "3",
            "video_fit_mode": self.video_fit_mode_menu.get() if hasattr(self, 'video_fit_mode_menu') else "Mantener Tamaño Original",
            # Opciones de rembg
            "rembg_enabled": self.rembg_checkbox.get() == 1,
            "rembg_gpu": self.rembg_gpu_checkbox.get() == 1, # <--- NUEVO: Enviar opción
            "rembg_model": real_model_name,
            
            # --- NUEVAS OPCIONES DE REESCALADO ---
            "upscale_enabled": self.upscale_checkbox.get() == 1,
            "upscale_engine": self.upscale_engine_menu.get(),
            "upscale_model_friendly": self.upscale_model_menu.get(), # Pasamos nombre amigable, el converter lo traduce
            "upscale_scale": self.upscale_scale_menu.get().replace("x", ""),
            "upscale_denoise": self.upscale_denoise_menu.get().split(" ")[0], # "-1", "0", etc.
            "upscale_tile": self.upscale_tile_entry.get(),
            "upscale_tta": self.upscale_tta_check.get() == 1
        }
        
        return options
    
    def _get_first_image_dimensions(self):
        """Obtiene (ancho, alto) del primer ítem de la lista. Retorna None si falla."""
        if not self.file_list_data:
            return None
        
        # SOLUCIÓN: Tomamos el ítem completo y extraemos solo lo que necesitamos (índice 0)
        item_data = self.file_list_data[0]
        filepath = item_data[0]
        # Ignoramos el resto (page_num o output_path) porque aquí no hacen falta
        
        try:
            # Usamos Pillow en modo 'lazy' (solo lee cabeceras)
            with Image.open(filepath) as img:
                return img.size # (width, height)
        except Exception:
            # Si es un PDF/Vectorial o falla Pillow, intentamos usar valores por defecto
            # o podríamos usar poppler, pero por velocidad retornamos None (Auto)
            return None
        
    def _update_video_resolution_menu_options(self):
        """Actualiza las opciones del menú de resolución con el valor de la primera imagen."""
        
        # 1. Obtener dimensiones actuales
        dims = self._get_first_image_dimensions()
        
        # 2. Crear el texto dinámico
        if dims:
            w, h = dims
            first_option = f"Usar la primera ({w}x{h})"
        else:
            first_option = "Usar la primera (Auto)"
            
        # 3. Lista base de opciones
        base_options = [
            "1920x1080 (1080p)",
            "1280x720 (720p)",
            "3840x2160 (4K UHD)",
            "Personalizado..."
        ]
        
        # 4. Combinar
        new_values = [first_option] + base_options
        
        # 5. Actualizar el menú
        # Guardamos la selección actual para intentar restaurarla si no era la dinámica
        current_selection = self.video_resolution_menu.get()
        
        self.video_resolution_menu.configure(values=new_values)
        
        # Si la selección actual ya no existe (porque cambiaron las dimensiones),
        # o si era la opción "Usar la primera...", actualizamos a la nueva cadena.
        if current_selection.startswith("Usar la primera") or current_selection not in base_options:
            self.video_resolution_menu.set(first_option)
        else:
            # Si estaba en 1080p o Personalizado, lo mantenemos
            self.video_resolution_menu.set(current_selection)

    def _get_output_filename(self, input_path, options, page_num=None, custom_title=None):
        """Genera el nombre del archivo de salida."""
        from src.core.constants import IMAGE_INPUT_FORMATS
        from urllib.parse import unquote
        import re

        # ✅ PRIORIDAD 1: Usar el título personalizado si existe
        if custom_title:
            base_name = custom_title
        else:
            # Fallback: Generar nombre basado en archivo original
            base_name = os.path.splitext(os.path.basename(input_path))[0]
            base_name = unquote(base_name)
            if page_num and self.image_processor.get_document_page_count(input_path) > 1:
                base_name = f"{base_name}_p{page_num}"
        
        # Sanitizar siempre (por si el usuario puso caracteres raros)
        base_name = re.sub(r'[<>:"/\\|?*]', '_', base_name)
        
        # Añadir el sufijo de página SI existe y si el original tenía varias páginas
        if page_num and self.image_processor.get_document_page_count(input_path) > 1:
            base_name = f"{base_name}_p{page_num}"
            
        output_format_str = options["format"]

        # --- INICIO DE MODIFICACIÓN ---
        if output_format_str == "No Convertir":
            input_ext = os.path.splitext(input_path)[1].lower()
            
            # Si el original era un vector, se rasterizará a PNG
            if input_ext in IMAGE_INPUT_FORMATS: # .svg, .pdf, .ai, .eps
                extension = "png"
            else:
                # Mantener la extensión original para rasters
                extension = input_ext.lstrip('.')
        
        else:
            extension = output_format_str.lower()
            # Casos especiales
            if extension in ["jpg", "jpeg"]:
                extension = "jpg"
        # --- FIN DE MODIFICACIÓN ---
        
        return f"{base_name}.{extension}"

    def _handle_conflict(self, output_path, policy):
        """
        Maneja conflictos de archivos existentes.
        Returns: "overwrite", "rename", "skip"
        """
        if policy == "Sobrescribir":
            return "overwrite"
        elif policy == "Renombrar":
            return "rename"
        elif policy == "Omitir":
            return "skip"
        else:
            return "overwrite"  # Por defecto

    def _get_unique_filename(self, filepath):
        """Genera un nombre único para evitar sobrescribir."""
        directory = os.path.dirname(filepath)
        filename = os.path.basename(filepath)
        name, ext = os.path.splitext(filename)
        
        counter = 1
        while True:
            new_name = f"{name} ({counter}){ext}"
            new_path = os.path.join(directory, new_name)
            if not os.path.exists(new_path):
                return new_path
            counter += 1

    def _import_to_adobe(self, processed_filepaths: list):
        """
        Importa los archivos procesados a Adobe (Premiere/After Effects).
        CORREGIDO: Ahora recibe una lista de archivos para no re-escanear.
        """
        try:
            # 1. Obtener el objetivo activo
            active_target_sid = self.app.ACTIVE_TARGET_SID_accessor()
            
            if not active_target_sid:
                print("INFO: No hay aplicación Adobe vinculada para importación automática")
                return
            
            # 2. Determinar la papelera (bin) de destino
            target_bin_name = None
            if self.create_subfolder_checkbox.get():
                # Usar el nombre de la subcarpeta como nombre del bin
                target_bin_name = self.subfolder_name_entry.get() or "DowP Imágenes"

            # 3. Lista de formatos compatibles (excluyendo WEBP)
            compatible_formats = {".png", ".jpg", ".jpeg", ".pdf", ".tiff", ".tif", ".ico", ".bmp"}
            
            files_to_import = []

            # 4. Iterar sobre la LISTA RECIBIDA (esta es la corrección)
            print(f"DEBUG: Preparando {len(processed_filepaths)} archivos para importar.")
            
            for filepath in processed_filepaths:
                file_ext = os.path.splitext(filepath)[1].lower()
                
                # Validar que el archivo exista y sea compatible
                if os.path.isfile(filepath) and file_ext in compatible_formats:
                    files_to_import.append(filepath.replace('\\', '/'))
                elif file_ext not in compatible_formats:
                    # Omitir silenciosamente formatos no compatibles (como .webp)
                    print(f"INFO: [ImgTools] Omitiendo importación de {os.path.basename(filepath)} (no compatible).")
            
            if not files_to_import:
                print("ADVERTENCIA: No se encontraron archivos compatibles en la lista procesada para importar.")
                return
            
            # 5. Verificar que TODOS los archivos sean accesibles
            print(f"DEBUG: Verificando accesibilidad de {len(files_to_import)} archivos...")
            verified_files = []
            for filepath in files_to_import:
                try:
                    # Verificar que existe y es accesible
                    if not os.path.exists(filepath):
                        print(f"  ❌ {os.path.basename(filepath)} - No existe")
                        continue
                    
                    size = os.path.getsize(filepath)
                    with open(filepath, 'rb') as f:
                        f.read(1)  # Leer primer byte
                    
                    verified_files.append(filepath)
                    print(f"  ✅ {os.path.basename(filepath)} ({size} bytes)")
                except Exception as e:
                    print(f"  ❌ {os.path.basename(filepath)} - ERROR: {e}")
            
            if not verified_files:
                print("ERROR: Ningún archivo pasó la verificación de accesibilidad")
                return
            
            # 6. Armar el PAQUETE ÚNICO (con archivos verificados)
            import_package = {
                "files": verified_files,
                "targetBin": target_bin_name
            }
            
            # 7. Enviar el paquete en UN SOLO MENSAJE
            print(f"INFO: [ImgTools] Enviando paquete de lote a CEP: {len(verified_files)} archivos a la papelera '{target_bin_name}'")
            self.app.socketio.emit('import_files', 
                                   import_package,
                                   to=active_target_sid)
        
        except Exception as e:
            print(f"ERROR: Falló la importación automática a Adobe: {e}")
        
    def _toggle_subfolder_name_entry(self):
        """Habilita/deshabilita el entry de nombre de carpeta."""
        if self.create_subfolder_checkbox.get():
            self.subfolder_name_entry.configure(state="normal")
        else:
            self.subfolder_name_entry.configure(state="disabled")

    def _update_list_status(self):
        """
        Helper para actualizar la etiqueta de conteo y el estado de los botones.
        Esta es ahora la ÚNICA fuente de verdad para el estado de los botones.
        """
        count = len(self.file_list_data)
        self.list_status_label.configure(text=f"{count} archivos")
        
        # ✅ NUEVO: Controlar visibilidad de la etiqueta de ayuda
        if hasattr(self, 'drag_hint_label'):
            if count == 0:
                self.drag_hint_label.place(relx=0.5, rely=0.5, anchor="center")
            else:
                self.drag_hint_label.place_forget()
        
        # 1. Estado del botón "Iniciar Proceso"
        if count == 0:
            self.start_process_button.configure(state="disabled")
            self.title_entry.delete(0, "end")
        else:
            self.start_process_button.configure(state="normal")

        # 2. Estado del botón "Borrar" (basado en la selección actual)
        if self.file_list_box.curselection():
            self.delete_button.configure(state="normal")
        else:
            self.delete_button.configure(state="disabled")

    def _create_list_context_menu(self, event):
        """Crea el menú de clic derecho para la lista de archivos."""
        menu = Menu(self, tearoff=0)
        
        # ✅ NUEVA OPCIÓN
        menu.add_command(label="Abrir ubicación del archivo", command=self._open_selected_file_location)
        menu.add_separator() # Separador visual
        
        menu.add_command(label="Copiar nombre de archivo", command=self._copy_selected_filename)
        menu.add_command(label="Copiar ruta completa", command=self._copy_selected_filepath)
        menu.add_separator()
        menu.add_command(label="Borrar selección", command=self._on_delete_selected)
        
        # Habilitar opciones solo si hay una selección válida
        if self.file_list_box.curselection():
            menu.entryconfigure("Abrir ubicación del archivo", state="normal") # ✅
            menu.entryconfigure("Copiar nombre de archivo", state="normal")
            menu.entryconfigure("Copiar ruta completa", state="normal")
            menu.entryconfigure("Borrar selección", state="normal")
        else:
            # Auto-seleccionar bajo el cursor (Lógica existente)
            self.file_list_box.selection_clear(0, "end")
            nearest_index = self.file_list_box.nearest(event.y)
            self.file_list_box.selection_set(nearest_index)
            self.file_list_box.activate(nearest_index)
            self.app.after(10, self._on_file_select)

        menu.tk_popup(event.x_root, event.y_root)

    def _get_selected_list_items(self, get_all=False):
        """
        Helper para obtener las rutas y nombres de los archivos seleccionados.
        CORREGIDO: Soporta tanto tuplas (antiguas) como listas (nuevas editables).
        """
        filepaths = []
        filenames = []
        
        # Índices a procesar
        if get_all:
            indices = range(len(self.file_list_data))
        else:
            indices = self.file_list_box.curselection()
            if not indices:
                return [], []
            
        for index in indices:
            # 1. Obtener los datos (puede ser tupla o lista)
            item_data = self.file_list_data[index]
            
            # 2. Extraer SOLO la ruta (primer elemento)
            # ✅ CORRECCIÓN: Comprobar si es list O tuple
            if isinstance(item_data, (list, tuple)):
                file_path = item_data[0]
            else:
                file_path = item_data # Fallback por seguridad
                
            filepaths.append(file_path)
            
            # 3. Obtener el nombre visual de la lista
            filenames.append(self.file_list_box.get(index))
                
        return filepaths, filenames
    def _copy_selected_filename(self):
        filepaths, filenames = self._get_selected_list_items()
        if filenames:
            self.clipboard_clear()
            self.clipboard_append("\n".join(filenames))

    def _copy_selected_filepath(self):
        filepaths, filenames = self._get_selected_list_items()
        if filepaths:
            self.clipboard_clear()
            self.clipboard_append("\n".join(filepaths))

    def _open_selected_file_location(self):
        """Abre el explorador de archivos seleccionando el ítem."""
        filepaths, _ = self._get_selected_list_items()
        
        if not filepaths:
            return
            
        # Abrir solo el primero de la selección para no abrir 50 ventanas
        path = os.path.normpath(filepaths[0])
        
        if not os.path.exists(path):
            print(f"ERROR: El archivo no existe: {path}")
            return
            
        try:
            import subprocess
            import platform
            
            system = platform.system()
            if system == "Windows":
                subprocess.Popen(['explorer', '/select,', path])
            elif system == "Darwin": # Mac
                subprocess.Popen(['open', '-R', path])
            else: # Linux
                subprocess.Popen(['xdg-open', os.path.dirname(path)])
                
        except Exception as e:
            print(f"ERROR al abrir ubicación: {e}")

    def _add_files_to_list(self, file_tuples: list):
        """Helper para añadir archivos a la lista. Normaliza la estructura de datos."""
        
        new_files_added = 0
        for (file_path, page_num) in file_tuples:
            
            # Verificar duplicados basándonos solo en path y página
            # (Buscamos manualmente porque la estructura de datos ahora es más compleja)
            is_duplicate = any(
                item[0] == file_path and item[1] == page_num 
                for item in self.file_list_data
            )
            
            if not is_duplicate:
                # ✅ ESTRUCTURA NUEVA: [Input, Page, Output, CustomTitle]
                # Usamos una LISTA (mutable), no una tupla
                self.file_list_data.append([file_path, page_num, None, None])
                
                # El nombre en la UI debe ser descriptivo
                file_name = os.path.basename(file_path)
                if page_num and self.image_processor.get_document_page_count(file_path) > 1:
                    display_name = f"{file_name} (pág. {page_num})"
                else:
                    display_name = file_name 
                    
                self.file_list_box.insert("end", display_name)
                new_files_added += 1
        
        if new_files_added > 0:
            print(f"INFO: Añadidos {new_files_added} archivos nuevos a la lista.")
        
        # Llamar a la función de estado centralizada
        self._update_list_status()
        self._update_video_resolution_menu_options()
        
    def _toggle_subfolder_name_entry(self):
        """Habilita/deshabilita el entry de nombre de carpeta."""
        if self.create_subfolder_checkbox.get():
            self.subfolder_name_entry.configure(state="normal")
        else:
            self.subfolder_name_entry.configure(state="disabled")

    def select_output_folder(self):
        """Abre el diálogo para seleccionar la carpeta de salida."""
        folder_path = filedialog.askdirectory()
        self.app.lift()
        self.app.focus_force()
        if folder_path:
            self.output_path_entry.delete(0, 'end')
            self.output_path_entry.insert(0, folder_path)
            self.save_settings() # Guardar la ruta
            self.last_processed_output_dir = folder_path
            self.open_folder_button.configure(state="normal")

    def _open_batch_output_folder(self):
        """
        Abre la carpeta de salida del ÚLTIMO proceso ejecutado,
        que puede ser la principal o la subcarpeta creada.
        """
        
        path_to_open = self.last_processed_output_dir
        
        # Fallback a la carpeta de salida principal si no se ha procesado nada
        if not path_to_open:
            path_to_open = self.output_path_entry.get()

        if not path_to_open or not os.path.isdir(path_to_open):
            print(f"ERROR: La carpeta de salida '{path_to_open}' no es válida.")
            return

        try:
            if os.name == "nt":
                os.startfile(os.path.normpath(path_to_open))
            elif sys.platform == "darwin":
                subprocess.Popen(['open', path_to_open])
            else:
                subprocess.Popen(['xdg-open', path_to_open])
        except Exception as e:
            print(f"Error al intentar abrir la carpeta: {e}")

    def create_entry_context_menu(self, widget):
        """Crea un menú contextual simple para los Entry widgets."""
        menu = Menu(self, tearoff=0)
        
        def copy_text():
            try:
                selected_text = widget.selection_get()
                if selected_text:
                    widget.clipboard_clear()
                    widget.clipboard_append(selected_text)
            except Exception: pass
        
        def cut_text():
            try:
                selected_text = widget.selection_get()
                if selected_text:
                    widget.clipboard_clear()
                    widget.clipboard_append(selected_text)
                    widget.delete("sel.first", "sel.last")
            except Exception: pass

        def paste_text():
            try:
                if widget.selection_get():
                    widget.delete("sel.first", "sel.last")
            except Exception: pass
            try:
                widget.insert("insert", self.clipboard_get())
            except Exception: pass
                
        menu.add_command(label="Cortar", command=cut_text)
        menu.add_command(label="Copiar", command=copy_text)
        menu.add_command(label="Pegar", command=paste_text)
        menu.add_separator()
        menu.add_command(label="Seleccionar todo", command=lambda: widget.select_range(0, 'end'))
        
        menu.tk_popup(widget.winfo_pointerx(), widget.winfo_pointery())

    def _load_thumbnail_thread(self, filepath):
        """
        (Hilo de trabajo) Llama al procesador para generar la miniatura.
        """
        # Obtener el tamaño del contenedor del visor
        # Lo hacemos aquí para que el hilo tenga el tamaño más actual
        try:
            # Damos un pequeño margen de 10px
            width = self.viewer_frame.winfo_width() - 10
            height = self.viewer_frame.winfo_height() - 10
            if width < 50 or height < 50: # Fallback si el frame está colapsado
                width, height = 400, 400
        except Exception:
            width, height = 400, 400 # Fallback
            
        # Llamar al "motor" de procesamiento
        pil_image = self.image_processor.generate_thumbnail(filepath, size=(width, height))
        
        # Enviar la imagen (o None) de vuelta al hilo principal (UI)
        self.app.after(0, self._display_thumbnail_in_viewer, pil_image, filepath)

    def _display_thumbnail_in_viewer(self, pil_image, original_filepath, is_loading=False):
        """
        (Hilo de UI) Muestra la imagen en el visor interactivo.
        ✅ CORREGIDO: Fuerza centrado correcto en el primer load
        """
        # 1. Limpiar el frame
        for widget in self.viewer_frame.winfo_children():
            widget.destroy()

        # 2. Comprobar obsolescencia
        if original_filepath is not None and original_filepath != self.last_preview_path:
            return

        if is_loading:
            self.viewer_placeholder = ctk.CTkLabel(
                self.viewer_frame, text="Cargando...", text_color="gray"
            )
            self.viewer_placeholder.place(relx=0.5, rely=0.5, anchor="center")
        
        elif pil_image or (original_filepath and os.path.exists(original_filepath)):
            # 3. Instanciar Visor Interactivo
            self.image_viewer = InteractiveImageViewer(self.viewer_frame)
            self.image_viewer.pack(expand=True, fill="both")
            
            # ✅ CRÍTICO: Forzar actualización de geometría ANTES de cargar
            self.image_viewer.update_idletasks()
            
            # Detectar formato
            ext = os.path.splitext(original_filepath)[1].lower().lstrip('.').upper() if original_filepath else ""
            if ext == "JPG": ext = "JPEG"
            
            is_raster_compatible = ext in IMAGE_RASTER_FORMATS
            
            # Cargar imagen
            if original_filepath and os.path.exists(original_filepath) and is_raster_compatible:
                print(f"DEBUG: Visor cargando Raster desde disco: {original_filepath}")
                self.image_viewer.load_image(original_filepath)
            elif pil_image:
                print(f"DEBUG: Visor cargando Vector/Miniatura desde memoria")
                self.image_viewer.load_image(pil_image)
            else:
                self.viewer_placeholder = ctk.CTkLabel(self.viewer_frame, text="Error al cargar imagen", text_color="orange")
                self.viewer_placeholder.place(relx=0.5, rely=0.5, anchor="center")
                return
            
            # ✅ CORRECCIÓN: Programar un segundo fit después de que Tk termine de renderizar
            # Esto garantiza que las dimensiones sean las correctas
            def delayed_fit():
                if hasattr(self, 'image_viewer') and self.image_viewer.winfo_exists():
                    self.image_viewer.fit_image()
            
            self.after(100, delayed_fit)  # 100ms después

        else:
            # 4. Placeholder por defecto
            self.viewer_placeholder = ctk.CTkLabel(
                self.viewer_frame, 
                text="Selecciona un archivo de la lista para previsualizarlo",
                text_color="gray"
            )
            self.viewer_placeholder.place(relx=0.5, rely=0.5, anchor="center")

    def _start_thumbnail_worker(self):
        """Inicia el hilo worker de miniaturas si no está activo"""
        if self.active_thumbnail_thread and self.active_thumbnail_thread.is_alive():
            return  # Ya hay un worker activo
        
        self.active_thumbnail_thread = threading.Thread(
            target=self._thumbnail_worker_loop,
            daemon=True
        )
        self.active_thumbnail_thread.start()

    def _thumbnail_worker_loop(self):
        """
        Worker que procesa la cola de miniaturas una a la vez.
        """
        while True:
            try:
                (filepath, page_num) = self.thumbnail_queue.get(timeout=3.0)
                cache_key = f"{filepath}::{page_num}"
            except queue.Empty:
                break
            
            if cache_key != self.last_preview_path:
                continue
            
            try:
                # Obtener el tamaño del contenedor del visor
                try:
                    width = self.viewer_frame.winfo_width() - 20
                    height = self.viewer_frame.winfo_height() - 20
                    if width < 50 or height < 50:
                        width, height = 400, 300
                except Exception:
                    width, height = 400, 300
                
                # 4. Llamar al procesador CON el número de página
                pil_image = self.image_processor.generate_thumbnail(
                    filepath, 
                    size=(width, height),
                    page_number=page_num # <-- ¡EL NUEVO ARGUMENTO!
                )
                
                # 5. Verificar de nuevo si sigue siendo relevante
                if cache_key != self.last_preview_path:
                    print(f"DEBUG: Miniatura de '{os.path.basename(filepath)}' (pág. {page_num}) descartada después de generar")
                    continue
                
                if pil_image:
                    # Crear CTkImage para la lista
                    ctk_image = ctk.CTkImage(
                        light_image=pil_image,
                        dark_image=pil_image,
                        size=(pil_image.width, pil_image.height)
                    )
                    
                    # --- CORRECCIÓN AQUÍ: Guardar como DICCIONARIO ---
                    cache_data = {
                        'ctk': ctk_image,  # Para mostrar rápido
                        'pil': pil_image   # Para el visor interactivo (Zoom)
                    }
                    
                    with self.thumbnail_lock:
                        # 1. Limpieza: Si el caché es muy grande, borrar el más antiguo
                        if len(self.thumbnail_cache) > 50: # Límite de 50 imágenes
                            # Borrar el primer elemento (el más viejo insertado)
                            oldest_key = next(iter(self.thumbnail_cache))
                            del self.thumbnail_cache[oldest_key]
                            
                        self.thumbnail_cache[cache_key] = cache_data
                    
                    self.app.after(0, self._display_cached_thumbnail, cache_data, cache_key)
                
            except Exception as e:
                print(f"ERROR: No se pudo generar miniatura para {filepath} (pág {page_num}): {e}")
                # 8. Mostrar error en la UI
                self.app.after(0, self._display_thumbnail_in_viewer, None, cache_key)

    def _display_cached_thumbnail(self, cache_data, original_filepath):
        """
        Muestra una miniatura desde la caché.
        CORREGIDO: Lee correctamente el diccionario {'ctk', 'pil'} para permitir zoom en vectores.
        """
        # Verificar obsolescencia
        if original_filepath != self.last_preview_path:
            return
        
        # Limpiar
        for widget in self.viewer_frame.winfo_children():
            widget.destroy()
            
        # Instanciar Visor
        self.image_viewer = InteractiveImageViewer(self.viewer_frame)
        self.image_viewer.pack(expand=True, fill="both")
        
        # Obtener la ruta real
        key_parts = original_filepath.split("::")
        real_path = key_parts[0]
        
        # --- LÓGICA DE CARGA ---
        
        # 1. Detectar si es Raster (JPG, PNG...) -> Cargar desde disco (Mejor calidad)
        ext = os.path.splitext(real_path)[1].lower().lstrip('.').upper()
        if ext == "JPG": ext = "JPEG"
        
        is_raster_compatible = ext in IMAGE_RASTER_FORMATS
        
        if os.path.exists(real_path) and os.path.isfile(real_path) and is_raster_compatible:
             print(f"DEBUG: Cargando imagen local Full Res desde caché: {real_path}")
             self.image_viewer.load_image(real_path)
             
        else:
             # 2. Es Vector (SVG, PDF) -> Usar la imagen PIL guardada en memoria
             # 'cache_data' puede venir directo del worker (dict) o ser un CTkImage antiguo
             
             pil_image_to_show = None
             
             # Si nos pasaron el dict directamente (desde worker)
             if isinstance(cache_data, dict) and 'pil' in cache_data:
                 pil_image_to_show = cache_data['pil']
                 
             # Si no, buscar en self.thumbnail_cache
             elif original_filepath in self.thumbnail_cache:
                 stored = self.thumbnail_cache[original_filepath]
                 if isinstance(stored, dict) and 'pil' in stored:
                     pil_image_to_show = stored['pil']
            
             if pil_image_to_show:
                 print(f"DEBUG: Cargando vector desde memoria (PIL): {real_path}")
                 self.image_viewer.load_image(pil_image_to_show)
             else:
                 print("ERROR: No se encontraron datos de imagen en la caché.")

    def import_folder_from_path(self, folder_path):
        """
        (API PÚBLICA)
        Inicia un escaneo de carpeta desde una llamada externa (ej. SingleDownloadTab).
        """
        if not os.path.isdir(folder_path):
            print(f"ERROR: [ImageTools] La ruta {folder_path} no es una carpeta válida.")
            return
            
        print(f"INFO: [ImageTools] Importando programáticamente desde: {folder_path}")
        
        # 1. Cambiar a esta pestaña
        self.app.tab_view.set("Herramientas de Imagen")
        
        # 2. Bloquear botones y mostrar estado
        self._toggle_import_buttons("disabled")
        self.list_status_label.configure(text=f"Importando desde {os.path.basename(folder_path)}...")
        
        # 3. Reutilizar tu lógica de escaneo de carpeta existente
        threading.Thread(
            target=self._search_folder_thread, 
            args=(folder_path,), 
            daemon=True
        ).start()

    def _scan_and_import_dropped_paths(self, paths):
        """
        (HILO DE TRABAJO) Recorre los items arrastrados.
        Si es archivo: lo valida.
        Si es carpeta: la escanea recursivamente (os.walk).
        """
        files_to_process = []
        
        try:
            for path in paths:
                # Limpiar comillas si las hubiera
                path = path.strip('"')
                
                if os.path.isfile(path):
                    # CASO 1: Es un archivo
                    if path.lower().endswith(self.COMPATIBLE_EXTENSIONS):
                        files_to_process.append(path)
                
                elif os.path.isdir(path):
                    # CASO 2: Es una carpeta -> Escaneo Recursivo
                    print(f"DEBUG: Escaneando carpeta arrastrada: {path}")
                    for root, _, filenames in os.walk(path):
                        for f in filenames:
                            if f.lower().endswith(self.COMPATIBLE_EXTENSIONS):
                                full_path = os.path.join(root, f)
                                files_to_process.append(full_path)
            
            # Volver al hilo principal para procesar la lista final
            if files_to_process:
                print(f"INFO: Escaneo de drop finalizado. {len(files_to_process)} archivos encontrados.")
                self.app.after(0, self._process_imported_files, files_to_process)
            else:
                print("INFO: No se encontraron archivos compatibles en lo arrastrado.")
                self.app.after(0, lambda: self.list_status_label.configure(text="No se encontraron archivos compatibles."))

        except Exception as e:
            print(f"ERROR escaneando drop: {e}")
            self.app.after(0, lambda: messagebox.showerror("Error", f"Fallo al leer archivos arrastrados:\n{e}"))

    # ==================================================================
    # --- LÓGICA DE ELIMINAR FONDO (REMBG) ---
    # ==================================================================

    def _on_toggle_rembg_frame(self, silent=False):
        """Muestra u oculta las opciones de rembg."""
        if self.rembg_checkbox.get() == 1:
            self.rembg_options_frame.pack(fill="x", padx=5, pady=0, after=self.rembg_checkbox)
            # Verificar el modelo seleccionado actualmente (pasando silent)
            self._on_rembg_model_change(self.rembg_model_menu.get(), silent=silent)
        else:
            self.rembg_options_frame.pack_forget()

    def _get_model_path(self, category, model_name):
        """Helper para obtener la ruta y URL de un modelo seleccionado."""
        from main import REMBG_MODELS_DIR, MODELS_DIR
        
        file_path = None
        url = None
        
        if category == "rembg":
            family = self.rembg_family_menu.get()
            info = REMBG_MODEL_FAMILIES.get(family, {}).get(model_name)
            if info:
                folder = info.get("folder", "rembg")
                target_dir = os.path.join(MODELS_DIR, folder)
                file_path = os.path.join(target_dir, info["file"])
                url = info["url"]
                
        elif category == "upscale":
            engine = self.upscale_engine_menu.get()
            info = None
            
            # Buscar en el diccionario correcto según el motor
            if engine == "Real-ESRGAN" and model_name in REALESRGAN_MODELS:
                # Nota: Real-ESRGAN son binarios/modelos internos, usualmente no son archivos .onnx sueltos fáciles de borrar individualmente
                # Si la estructura es compleja, quizás quieras deshabilitar el borrado para este motor.
                # Asumiremos que NO se pueden borrar individualmente por ahora para evitar romper el binario.
                return None, None 
                
            elif engine == "Waifu2x" and model_name in WAIFU2X_MODELS:
                # Waifu2x usa carpetas de modelos. 
                # Implementación simplificada: No permitimos borrar modelos base del sistema por seguridad
                return None, None

            # Para BiRefNet u otros futuros que sean archivos únicos .onnx/pth sí funcionaría.
            # Por ahora, limitaremos la función de borrar a REMBG que es lo que más ocupa espacio variable.
            
        return file_path, url

    def _open_model_folder(self, category):
        """Abre la carpeta contenedora del modelo seleccionado."""
        # Para Rembg
        if category == "rembg":
            # Usamos la variable global importada de main
            target_dir = REMBG_MODELS_DIR
            # Si el modelo es RMBG 2.0, está en otra subcarpeta
            family = self.rembg_family_menu.get()
            if "RMBG 2.0" in family:
                target_dir = os.path.join(MODELS_DIR, "rmbg2")
                
        elif category == "upscale":
            engine = self.upscale_engine_menu.get()
            folder_map = {
                "Real-ESRGAN": "realesrgan",
                "Waifu2x": "waifu2x",
                "RealSR": "realsr",
                "SRMD": "srmd"
            }
            folder = folder_map.get(engine.split(" ")[0], "upscaling")
            target_dir = os.path.join(UPSCALING_DIR, folder)
        
        if os.path.exists(target_dir):
            try:
                if os.name == 'nt': os.startfile(target_dir)
                elif sys.platform == 'darwin': subprocess.Popen(['open', target_dir])
                else: subprocess.Popen(['xdg-open', target_dir])
            except Exception as e:
                print(f"Error abriendo carpeta: {e}")

    def _delete_current_model(self, category):
        """Borra el archivo o motor seleccionado tras confirmación."""
        if category == "rembg":
            # (El código de rembg se mantiene igual, ya que son archivos individuales)
            model_name = self.rembg_model_menu.get()
            path, _ = self._get_model_path("rembg", model_name)
            
            if path and os.path.exists(path):
                size_mb = os.path.getsize(path) / (1024 * 1024)
                
                confirm = messagebox.askyesno(
                    "Confirmar Eliminación", 
                    f"¿Estás seguro de que deseas eliminar el modelo '{model_name}'?\n\n"
                    f"Liberarás {size_mb:.1f} MB de espacio."
                )
                
                if confirm:
                    try:
                        os.remove(path)
                        print(f"INFO: Modelo eliminado: {path}")
                        self._on_rembg_model_change(model_name, silent=True)
                    except Exception as e:
                        messagebox.showerror("Error", f"No se pudo eliminar el archivo:\n{e}")
        
        elif category == "upscale":
            # --- LÓGICA CORREGIDA: BORRAR MOTOR COMPLETO ---
            import shutil
            from main import UPSCALING_DIR

            engine = self.upscale_engine_menu.get()
            
            target_path = None
            folder_name = None

            # Mapeo simple: Nombre del motor -> Nombre de su carpeta
            if engine == "Waifu2x":
                folder_name = "waifu2x"
            elif "RealSR" in engine:
                folder_name = "realsr"
            elif "SRMD" in engine:
                folder_name = "srmd"
            elif engine == "Real-ESRGAN":
                folder_name = "realesrgan"
            
            if folder_name:
                target_path = os.path.join(UPSCALING_DIR, folder_name)

            if target_path and os.path.exists(target_path):
                # Calcular el tamaño total para informar al usuario
                total_size = 0
                for dirpath, _, filenames in os.walk(target_path):
                    for f in filenames:
                        fp = os.path.join(dirpath, f)
                        total_size += os.path.getsize(fp)
                size_mb = total_size / (1024 * 1024)

                confirm = messagebox.askyesno(
                    "Desinstalar Motor", 
                    f"¿Estás seguro de que deseas eliminar el motor '{engine}' completo?\n\n"
                    f"Esto borrará la carpeta entera y todos sus modelos.\n"
                    f"Espacio liberado: {size_mb:.1f} MB\n\n"
                    "Tendrás que volver a descargarlo para usarlo."
                )
                
                if confirm:
                    try:
                        # Borrar la carpeta completa recursivamente
                        shutil.rmtree(target_path)
                        print(f"INFO: Motor Upscale eliminado: {target_path}")
                        
                        # Actualizar UI para reflejar que ya no está instalado
                        # Usamos el modelo actual solo para refrescar la vista
                        current_model = self.upscale_model_menu.get()
                        self._on_upscale_model_change(current_model, engine=engine, silent=True)
                        
                    except Exception as e:
                        messagebox.showerror("Error", f"No se pudo eliminar la carpeta:\n{e}")
            else:
                messagebox.showwarning("Error", "No se encontró la carpeta del motor para borrar.")

    def _on_rembg_family_change(self, selected_family, silent=False):
        """Actualiza el menú de modelos basado en la familia seleccionada."""
        models_dict = REMBG_MODEL_FAMILIES.get(selected_family, {})
        model_names = list(models_dict.keys())
        
        if model_names:
            self.rembg_model_menu.configure(values=model_names)
            # Intentar seleccionar el "general" o "recomendado" por defecto
            default_model = next((m for m in model_names if "General" in m or "Recomendado" in m), model_names[0])
            self.rembg_model_menu.set(default_model)
            # ✅ PASAMOS EL SILENCIO AQUÍ
            self._on_rembg_model_change(default_model, silent=silent)
        else:
            self.rembg_model_menu.configure(values=["-"])
            self.rembg_model_menu.set("-")

    def _on_rembg_model_change(self, selected_model, silent=False):
        """
        Verifica si el modelo está descargado.
        Si silent=True (arranque), no descarga, solo verifica.
        Si silent=False (usuario), pregunta antes de descargar mostrando el peso.
        """
        if self.rembg_checkbox.get() != 1: return
        if selected_model == "-" or not selected_model: return

        family = self.rembg_family_menu.get()
        model_info = REMBG_MODEL_FAMILIES.get(family, {}).get(selected_model)
        if not model_info: return

        filename = model_info["file"]
        folder = model_info.get("folder", "rembg")
        target_dir = os.path.join(MODELS_DIR, folder)
        file_path = os.path.join(target_dir, filename)
        
        # 1. Verificar existencia
        is_installed = os.path.exists(file_path) and os.path.getsize(file_path) > 1024
        
        # 2. Actualizar Botones de Gestión
        if is_installed:
            self.rembg_status_label.configure(text="✅ Modelo listo", text_color="gray")
            self.start_process_button.configure(state="normal")
            
            # Habilitar botones
            if hasattr(self, 'rembg_delete_btn'):
                self.rembg_delete_btn.configure(state="normal")
                self.rembg_open_btn.configure(state="normal")
        else:
            self.rembg_status_label.configure(text="⚠️ No instalado", text_color="orange")
            
            # Deshabilitar botones (no puedes borrar lo que no tienes)
            if hasattr(self, 'rembg_delete_btn'):
                self.rembg_delete_btn.configure(state="disabled")
                # El botón abrir lo dejamos activo para facilitar la instalación manual si quieren
                self.rembg_open_btn.configure(state="normal") 

            # 3. Lógica de Descarga (Solo si NO es silencioso)
            if not silent:
                # Caso especial: Descarga Manual Obligatoria (RMBG 2.0 privado)
                if family == "RMBG 2.0 (BriaAI)" and "danielgatis" not in model_info["url"]:
                    # ... (Tu lógica de diálogo manual existente se mantiene aquí) ...
                    def on_manual_success():
                        self.rembg_status_label.configure(text="✅ Modelo listo (Manual)", text_color="green")
                        self.start_process_button.configure(state="normal")
                        self.rembg_delete_btn.configure(state="normal")

                    ManualDownloadDialog(self.app, model_info, target_dir, filename, on_manual_success)
                    return

                # Caso normal: Descarga Automática con PREGUNTA DE PESO
                # Obtener peso remoto
                self.rembg_status_label.configure(text="Consultando tamaño...", text_color="#52a2f2")
                self.update() # Refrescar UI momentáneamente
                
                # Hacemos esto en un hilo rápido o directo (HEAD es rápido)
                # Para no bloquear, lo ideal sería hilo, pero por simplicidad:
                file_size = get_remote_file_size(model_info["url"])
                size_str = format_size(file_size)
                
                user_response = messagebox.askyesno(
                    "Descargar Modelo IA",
                    f"El modelo '{selected_model}' no está instalado.\n\n"
                    f"Tamaño de descarga: {size_str}\n\n"
                    "¿Deseas descargarlo ahora?"
                )
                
                if user_response:
                    self.rembg_status_label.configure(text="Iniciando descarga...", text_color="#52a2f2")
                    threading.Thread(
                        target=self._download_rembg_model_thread,
                        args=(model_info, file_path),
                        daemon=True
                    ).start()
                else:
                    self.rembg_status_label.configure(text="⚠️ Descarga cancelada", text_color="orange")

    def _download_rembg_model_thread(self, model_info, file_path):
        """
        Descarga optimizada para velocidad (Buffer grande).
        """
        url = model_info["url"]
        
        # Asegurar que la carpeta existe
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        # Configurar sesión robusta
        session = requests.Session()
        retries = Retry(total=5, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retries)
        session.mount('http://', adapter)
        session.mount('https://', adapter)

        temp_path = file_path + ".part"

        try:
            # CORRECCIÓN: Usar la cola de la app principal para actualizar la UI
            self.app.ui_update_queue.put((
                lambda: self.rembg_status_label.configure(text="🚀 Conectando...", text_color="#52a2f2"),
                ()
            ))
            
            # Stream=True es vital
            response = session.get(url, stream=True, timeout=(10, 120))
            response.raise_for_status()
            
            total_length = int(response.headers.get('content-length', 0))
            
            # --- OPTIMIZACIÓN DE VELOCIDAD ---
            chunk_size = 4 * 1024 * 1024  # 4 MB
            
            dl = 0
            last_percent = -1
            
            with open(temp_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        dl += len(chunk)
                        
                        if total_length > 0:
                            percent = int(100 * dl / total_length)
                            # Solo actualizar UI si cambió el porcentaje para no congelar
                            if percent > last_percent:
                                last_percent = percent
                                downloaded_mb = dl / (1024 * 1024)
                                total_mb = total_length / (1024 * 1024)
                                status_text = f"⬇️ {percent}% ({downloaded_mb:.1f}/{total_mb:.1f} MB)"
                                
                                # CORRECCIÓN: Usar la cola para actualizar el texto de progreso
                                self.app.ui_update_queue.put((
                                    lambda t=status_text: self.rembg_status_label.configure(text=t),
                                    ()
                                ))

            # Renombrar al finalizar
            if os.path.exists(file_path):
                os.remove(file_path)
            os.rename(temp_path, file_path)

            # Verificación final
            if total_length > 0 and os.path.getsize(file_path) != total_length:
                raise Exception("Tamaño de archivo incorrecto tras descarga.")

            # CORRECCIÓN: Usar la cola para éxito
            self.app.ui_update_queue.put((
                lambda: self.rembg_status_label.configure(text="✅ Instalado", text_color="green"),
                ()
            ))
            self.app.ui_update_queue.put((
                lambda: self.start_process_button.configure(state="normal"),
                ()
            ))
            
            self.app.ui_update_queue.put((
                lambda: self.rembg_delete_btn.configure(state="normal"),
                ()
            ))
            
        except Exception as e:
            print(f"ERROR descarga: {e}")
            if os.path.exists(temp_path):
                try: os.remove(temp_path)
                except: pass
                
            # CORRECCIÓN: Usar la cola para error
            self.app.ui_update_queue.put((
                lambda: self.rembg_status_label.configure(text="❌ Error descarga", text_color="red"),
                ()
            ))
            self.app.ui_update_queue.put((
                lambda: messagebox.showerror("Error", f"Fallo al descargar:\n{e}"),
                ()
            ))
        
        finally:
            session.close()
            # CORRECCIÓN: Usar la cola para cleanup
            self.app.ui_update_queue.put((
                lambda: self.rembg_model_menu.configure(state="normal"),
                ()
            ))
            self.app.ui_update_queue.put((
                lambda: self.rembg_family_menu.configure(state="normal"),
                ()
            ))

    def _create_checkerboard(self, w, h, size=10):
        """Crea una imagen de fondo tipo ajedrez para transparencia."""
        img = Image.new("RGB", (w, h), (200, 200, 200)) # Gris claro
        pixels = img.load()
        for y in range(h):
            for x in range(w):
                if ((x // size) + (y // size)) % 2 == 0:
                    pixels[x, y] = (255, 255, 255) # Blanco
        return img

    def _start_comparison_viewer(self, input_path, output_path, page_num):
        """Inicia el modo de comparación con Zoom y Paneo real."""
        
        # 1. Limpiar el frame
        for widget in self.viewer_frame.winfo_children():
            widget.destroy()

        try:
            ext = os.path.splitext(input_path)[1].lower()
            vector_exts = (".pdf", ".ai", ".eps", ".svg", ".ps")
            is_vector = ext in vector_exts
            
            # 🔥 NUEVO: Detectar si es RAW
            raw_exts = tuple(f.lower() for f in IMAGE_RAW_FORMATS)
            is_raw = ext in raw_exts
            
            img_before = None
            
            # --- CASO 1: Archivos RAW ---
            if is_raw:
                print(f"DEBUG: Cargando RAW para comparación: {os.path.basename(input_path)}")
                try:
                    import rawpy
                    import numpy as np
                    
                    with rawpy.imread(input_path) as raw:
                        rgb = raw.postprocess(
                            use_camera_wb=True,
                            half_size=True,
                            no_auto_bright=False,
                            output_bps=8,
                            output_color=rawpy.ColorSpace.sRGB,
                            demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD
                        )
                    
                    img_before = Image.fromarray(rgb).convert("RGBA")
                    
                    try:
                        from PIL import ImageOps
                        img_before = ImageOps.exif_transpose(img_before)
                    except:
                        pass
                        
                except ImportError:
                    print("⚠️ rawpy no disponible para vista previa RAW")
                    img_before = None
                except Exception as e:
                    print(f"❌ Error cargando RAW para comparación: {e}")
                    img_before = None
            
            # --- CASO 2: Vectoriales ---
            elif is_vector:
                print("DEBUG: Renderizando vector a alta resolución para comparación...")
                try:
                    img_before = self.image_processor.generate_thumbnail(
                        input_path, size=(3000, 3000), page_number=page_num
                    )
                except Exception as e:
                    print(f"ADVERTENCIA: Falló renderizado HQ vector: {e}")
            
            # --- CASO 3: Raster normal ---
            if img_before is None and not is_raw:
                print("DEBUG: Cargando imagen original directa (Raster o Fallback)")
                img_before = Image.open(input_path).convert("RGBA")

            # Cargar Resultado
            img_after = Image.open(output_path).convert("RGBA")
            
            # ✅ Validación: Si no hay imagen "antes", usar la de salida
            if not img_before:
                print("⚠️ No se pudo cargar original, mostrando solo resultado")
                img_before = img_after.copy()
            
            if not img_after: 
                print("ERROR: No se pudieron cargar las imágenes para comparar")
                return

            # ✅ CORRECCIÓN: Ajustar la imagen BEFORE al tamaño de AFTER manteniendo aspecto
            # Esto evita el estiramiento forzado
            if img_before.size != img_after.size:
                print(f"DEBUG: Redimensionando 'antes' de {img_before.size} a {img_after.size} (manteniendo aspecto)")
                
                # Crear un canvas transparente del tamaño del resultado
                canvas_before = Image.new("RGBA", img_after.size, (0, 0, 0, 0))
                
                # Calcular el tamaño que debería tener la imagen original para caber
                original_w, original_h = img_before.size
                target_w, target_h = img_after.size
                
                # Calcular escala manteniendo proporción (fit)
                scale_w = target_w / original_w
                scale_h = target_h / original_h
                scale = min(scale_w, scale_h)  # Usar el menor para que quepa completamente
                
                new_w = int(original_w * scale)
                new_h = int(original_h * scale)
                
                # Redimensionar manteniendo calidad
                img_before_resized = img_before.resize((new_w, new_h), Image.Resampling.LANCZOS)
                
                # Centrar en el canvas
                x = (target_w - new_w) // 2
                y = (target_h - new_h) // 2
                
                canvas_before.paste(img_before_resized, (x, y), img_before_resized if img_before_resized.mode == 'RGBA' else None)
                
                img_before = canvas_before
                print(f"✅ Imagen 'antes' ajustada correctamente: {img_before.size}")

            # 3. Instanciar nuestro visor avanzado
            self.compare_viewer = ComparisonViewer(self.viewer_frame)
            self.compare_viewer.place(relx=0, rely=0, relwidth=1, relheight=1)
            
            # 4. Cargar las imágenes en el visor
            self.compare_viewer.load_images(img_before, img_after)
            
            # 5. Mostrar instrucciones flotantes
            self._show_comparison_instructions()

        except Exception as e:
            print(f"Error iniciando comparación: {e}")
            import traceback
            traceback.print_exc()

    def _show_comparison_instructions(self):
        """Muestra una etiqueta temporal sobre cómo usar el visor."""
        info_label = ctk.CTkLabel(
            self.viewer_frame, 
            text="🔍 Rueda: Zoom  |  🖱️ Clic + Arrastre: Mover Imagen  |  📏 Línea Blanca: Slider",
            fg_color="#333333", text_color="white", corner_radius=5,
            font=ctk.CTkFont(size=11)
        )
        info_label.place(relx=0.5, rely=0.95, anchor="center")
        
        # Ocultar después de 5 segundos
        self.after(5000, info_label.destroy)

    def _on_slider_drag(self, event):
        """Calcula la posición X relativa a la imagen."""
        local_x = event.x - self.img_x
        width = self.pil_after_source.width
        local_x = max(0, min(local_x, width))
        self._update_slider_crop(local_x)

    def _update_slider_crop(self, x):
        """Recorta ambas imágenes para evitar superposición (Transparencia correcta)."""
        from PIL import ImageTk
        width = self.pil_after_source.width
        height = self.pil_after_source.height
        
        # Mover línea
        self.compare_canvas.coords(self.line_id, self.img_x + x, self.img_y, self.img_x + x, self.img_y + height)
        
        # Recortar AFTER (Izquierda -> X)
        if x > 0:
            crop = self.pil_after_source.crop((0, 0, x, height))
            self.photo_after_crop = ImageTk.PhotoImage(crop)
            self.compare_canvas.itemconfig("after", image=self.photo_after_crop)
            self.compare_canvas.coords("after", self.img_x, self.img_y)
        else:
            self.compare_canvas.itemconfig("after", image="")

        # Recortar BEFORE (X -> Derecha)
        if x < width:
            crop = self.pil_before_source.crop((x, 0, width, height))
            self.photo_before_crop = ImageTk.PhotoImage(crop)
            self.compare_canvas.itemconfig("before", image=self.photo_before_crop)
            self.compare_canvas.coords("before", self.img_x + x, self.img_y)
        else:
            self.compare_canvas.itemconfig("before", image="")

    # Test rápido en cualquier parte de tu código
    def test_raw_support():
        try:
            import rawpy
            print("✅ rawpy instalado correctamente")
            print(f"   Versión LibRaw: {rawpy.libraw_version}")
            
            # Mostrar algunos formatos soportados
            formats = ['.dng', '.cr2', '.cr3', '.nef', '.arw', '.orf']
            print(f"   Formatos RAW soportados: {', '.join(formats)}")
            return True
        except ImportError:
            print("❌ rawpy NO está instalado")
            return False

    # Llamar al inicio de tu app
    test_raw_support()