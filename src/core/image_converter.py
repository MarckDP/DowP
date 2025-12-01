import os
import io
import tempfile
import threading
import subprocess
import pillow_avif

from src.core.constants import REALESRGAN_MODELS, WAIFU2X_MODELS, REALSR_MODELS, SRMD_MODELS
from src.core.constants import IMAGE_RASTER_FORMATS, IMAGE_INPUT_FORMATS, IMAGE_RAW_FORMATS
from main import BIN_DIR, REMBG_MODELS_DIR, MODELS_DIR

try:
    from pdf2image import convert_from_path, pdfinfo_from_path
    CAN_PDF = True
except ImportError:
    CAN_PDF = False
    print("ADVERTENCIA: 'pdf2image' no instalado. No se podrán convertir archivos .pdf, .ai, .eps")

from PIL import Image, ImageDraw, ImageChops
from src.core.exceptions import UserCancelledError

# Importar las librerías de conversión
try:
    import cairosvg
    CAN_SVG = True
except ImportError:
    CAN_SVG = False
    print("ADVERTENCIA: 'cairosvg' no instalado. No se podrán convertir archivos .svg")

try:
    from pdf2image import convert_from_path, pdfinfo_from_path
    CAN_PDF = True
except ImportError:
    CAN_PDF = False
    print("ADVERTENCIA: 'pdf2image' no instalado. No se podrán convertir archivos .pdf, .ai, .eps")

try:
    import img2pdf
    CAN_IMG2PDF = True
except ImportError:
    CAN_IMG2PDF = False
    print("ADVERTENCIA: 'img2pdf' no instalado. Conversión a PDF será más lenta")



class ImageConverter:
    """
    Motor de conversión de imágenes que soporta múltiples formatos
    de entrada/salida con opciones avanzadas.
    """
    
    def __init__(self, poppler_path=None, inkscape_path=None, ffmpeg_processor=None):
        self.poppler_path = poppler_path
        self.inkscape_path = inkscape_path
        self.ffmpeg_processor = ffmpeg_processor

        # --- Variables para Lazy Loading de IA ---
        self.rembg_module = None   # Aquí guardaremos la librería cargada
        self.rembg_sessions = {}   # Aquí guardaremos las sesiones de modelos
        
        # --- Asignar correctamente las variables ---
        self.gs_dir, self.gs_exe = self._find_local_ghostscript()
        if self.gs_exe:
            print(f"INFO: Ghostscript local detectado: {self.gs_exe}")
        else:
            print("ADVERTENCIA: Ghostscript no encontrado. Conversión EPS/PS limitada.")
        
        # Formatos de entrada soportados
        self.RASTER_FORMATS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif", ".gif", ".avif")
        self.VECTOR_FORMATS = (".pdf", ".svg", ".eps", ".ai", ".ps")
        self.OTHER_FORMATS = (".psd", ".tga", ".jp2", ".ico")

        # Importar constantes de interpolación
        from src.core.constants import INTERPOLATION_METHODS
        self.INTERPOLATION_METHODS = INTERPOLATION_METHODS

        # Importar constantes de canvas
        from src.core.constants import CANVAS_POSITIONS, CANVAS_OVERFLOW_MODES
        self.CANVAS_POSITIONS = CANVAS_POSITIONS
        self.CANVAS_OVERFLOW_MODES = CANVAS_OVERFLOW_MODES

    def _find_local_ghostscript(self):
        """Busca Ghostscript y devuelve (carpeta_bin, ruta_exe)."""
        try:
            base_path = os.getcwd()
            possible_dirs = [
                os.path.join(base_path, "bin", "ghostscript", "bin"),
                os.path.join(base_path, "bin", "ghostscript"),
                os.path.join(base_path, "bin", "gs", "bin"),
            ]
            binaries = ["gswin64c.exe", "gswin32c.exe", "gs.exe", "gs"]

            for folder in possible_dirs:
                if os.path.exists(folder):
                    for binary in binaries:
                        full_path = os.path.join(folder, binary)
                        if os.path.exists(full_path):
                            print(f"DEBUG: Ghostscript encontrado en: {full_path}")
                            return folder, full_path
            
            print("DEBUG: Ghostscript no encontrado en rutas locales")
            return None, None
        except Exception as e:
            print(f"ERROR buscando Ghostscript: {e}")
            return None, None
        
    def _load_rembg_lazy(self, progress_callback=None):
        """
        Intenta cargar la librería rembg solo cuando se solicita.
        Retorna True si se cargó (o ya estaba cargada), False si falló.
        """
        if self.rembg_module is not None:
            return True # Ya estaba cargado en memoria

        print("INFO: Inicializando motor de IA (Rembg)...")
        
        if progress_callback:
            try:
                # Enviamos None en porcentaje para no mover la barra, solo cambiar el texto
                progress_callback(None, "Inicializando Motor IA (esto puede tardar unos segundos)...")
            except Exception:
                pass 
        try:
            import rembg
            self.rembg_module = rembg
            return True
        except ImportError as e:
            print(f"ERROR CRÍTICO: No se pudo cargar el módulo 'rembg': {e}")
            return False
        except Exception as e:
            print(f"ERROR INESPERADO cargando rembg: {e}")
            return False
        
    def clear_ai_sessions(self):
        """Libera la memoria de los modelos de IA cargados."""
        if self.rembg_sessions:
            print(f"DEBUG: Liberando {len(self.rembg_sessions)} sesiones de IA de la memoria.")
            self.rembg_sessions.clear()
            
        # Forzar al recolector de basura de Python
        import gc
        gc.collect()
        
    def _process_rmbg2(self, pil_image, model_path, use_gpu=True): # <--- CAMBIO 1: Agregado argumento
        """
        Ejecuta la inferencia específica para RMBG 2.0 usando ONNX Runtime.
        Replica la lógica de normalización y redimensión a 1024x1024.
        """
        try:
            import numpy as np
            import onnxruntime as ort
            
            # 1. Gestión de Sesión (Clave única por hardware)
            session_key = f"{model_path}_{'gpu' if use_gpu else 'cpu'}" # <--- CAMBIO 2: Clave única
            
            if session_key not in self.rembg_sessions:
                hw_label = 'GPU' if use_gpu else 'CPU'
                print(f"DEBUG: Cargando RMBG 2.0 en [{hw_label}]: {os.path.basename(model_path)}")
                
                sess_opts = ort.SessionOptions()
                
                if use_gpu:
                    # --- MODO GPU (Seguro) ---
                    providers = ['DmlExecutionProvider', 'CPUExecutionProvider']
                    sess_opts.enable_mem_pattern = False
                else:
                    # --- MODO CPU (Rápido) ---
                    providers = ['CPUExecutionProvider']
                    sess_opts.enable_cpu_mem_arena = True
                    sess_opts.execution_mode = ort.ExecutionMode.ORT_PARALLEL
                
                self.rembg_sessions[session_key] = ort.InferenceSession(model_path, providers=providers, sess_options=sess_opts)
            
            session = self.rembg_sessions[session_key]

            # 2. Preprocesamiento
            # Convertir a RGB y guardar tamaño original
            original_image = pil_image.convert("RGB")
            orig_w, orig_h = original_image.size
            
            # Redimensionar a 1024x1024 (Requisito estricto de RMBG 2.0)
            img_resized = original_image.resize((1024, 1024), Image.Resampling.BILINEAR)
            
            # Convertir a Numpy y Normalizar (0-1)
            img_np = np.array(img_resized).astype(np.float32) / 255.0
            
            # Estandarización (ImageNet mean/std)
            # IMPORTANTE: Definir explícitamente como float32 para evitar que Numpy use float64 (double)
            mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
            std  = np.array([0.229, 0.224, 0.225], dtype=np.float32)
            
            img_np = (img_np - mean) / std
            
            # Asegurar tipo final float32 antes de enviar al modelo
            img_np = img_np.astype(np.float32)
            
            # Transponer a (Batch, Channel, Height, Width) -> (1, 3, 1024, 1024)
            img_np = img_np.transpose(2, 0, 1)
            img_np = np.expand_dims(img_np, 0)

            # 3. Inferencia
            input_name = session.get_inputs()[0].name
            result = session.run(None, {input_name: img_np})
            mask = result[0][0, 0] # Obtener la máscara (quitando batch y channel)

            # 4. Postprocesamiento
            # Normalizar máscara a 0-255 y convertir a entero
            mask = (mask * 255).clip(0, 255).astype(np.uint8)
            
            # Convertir máscara de numpy a Imagen PIL
            mask_img = Image.fromarray(mask, mode='L')
            
            # Redimensionar máscara al tamaño ORIGINAL de la imagen
            mask_img = mask_img.resize((orig_w, orig_h), Image.Resampling.LANCZOS)

            # 5. Aplicar al canal Alfa
            # Si la imagen original no tiene alfa, agregarlo
            final_image = pil_image.convert("RGBA")
            final_image.putalpha(mask_img)
            
            return final_image

        except ImportError:
            print("ERROR: Faltan librerías 'numpy' o 'onnxruntime' para RMBG 2.0")
            return pil_image
        except Exception as e:
            print(f"ERROR en inferencia RMBG 2.0: {e}")
            return pil_image
        
    def _process_onnx_manual(self, pil_image, session, target_size):
        """
        Inferencia manual universal con corrección matemática para BiRefNet.
        """
        import numpy as np
        
        # 1. Preprocesamiento
        original_image = pil_image.convert("RGB")
        orig_w, orig_h = original_image.size
        
        # Redimensionar (BiRefNet/IsNet requieren 1024, U2Net 320)
        img_resized = original_image.resize(target_size, Image.Resampling.BILINEAR)
        
        # Normalización estándar (ImageNet)
        img_np = np.array(img_resized).astype(np.float32) / 255.0
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        std  = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        img_np = (img_np - mean) / std
        
        img_np = img_np.transpose(2, 0, 1)
        img_np = np.expand_dims(img_np, 0)

        # 2. Inferencia
        input_name = session.get_inputs()[0].name
        result = session.run(None, {input_name: img_np})
        
        # Obtener máscara (Batch, 1, H, W) -> (H, W)
        # Algunos modelos devuelven una lista, tomamos el primer tensor
        raw_mask = result[0][0, 0]

        # 3. Postprocesamiento Inteligente (CORRECCIÓN BIREFNET)
        
        # Detectar si necesitamos Sigmoide:
        # Si los valores salen del rango [0, 1] (ej: -5 a +5), son Logits.
        min_val, max_val = raw_mask.min(), raw_mask.max()
        
        if min_val < -1.0 or max_val > 1.5:
            # Aplicar Sigmoide: 1 / (1 + e^-x)
            # Esto convierte los "fantasmas" en negro/blanco puro
            mask = 1 / (1 + np.exp(-raw_mask))
        else:
            # Ya son probabilidades, usar tal cual
            mask = raw_mask

        # Normalización final para asegurar rango 0-255 sólido
        mask = (mask - mask.min()) / (mask.max() - mask.min() + 1e-8)
        mask = (mask * 255).astype(np.uint8)
        
        # 4. Redimensionar y Aplicar
        mask_img = Image.fromarray(mask, mode='L')
        mask_img = mask_img.resize((orig_w, orig_h), Image.Resampling.LANCZOS)

        final_image = pil_image.convert("RGBA")
        final_image.putalpha(mask_img)
        
        return final_image
        
    def remove_background(self, pil_image, model_filename="u2netp.onnx", progress_callback=None, use_gpu=True):
        """
        Elimina el fondo.
        Args:
            use_gpu (bool): True = GPU (DirectML Anti-Freeze), False = CPU (Full Performance)
        """
        
        from main import MODELS_DIR
        import onnxruntime as ort 
        
        # --- BLOQUE RMBG 2.0 ---
        rmbg2_names = [
            "bria-rmbg-2.0.onnx", "model.onnx", "model_bnb4.onnx", "model_fp16.onnx", 
            "model_int8.onnx", "model_quantized.onnx", "model_q4.onnx",
            "model_q4f16.onnx", "model_uint8.onnx"
        ]
        rmbg2_path = os.path.join(MODELS_DIR, "rmbg2", model_filename)

        if model_filename in rmbg2_names or os.path.exists(rmbg2_path):
            if not os.path.exists(rmbg2_path):
                print(f"ERROR: El modelo RMBG 2.0 no se encuentra en: {rmbg2_path}")
                return pil_image
            # Pasamos use_gpu aquí también
            return self._process_rmbg2(pil_image, rmbg2_path, use_gpu=use_gpu)

        # --- CARGA LAZY DE REMBG ---
        if not self._load_rembg_lazy(progress_callback):
            print("ERROR: La librería de IA no pudo cargarse.")
            return pil_image

        try:
            # 1. Definir clave de caché única (Nombre + GPU/CPU)
            session_key = f"{model_filename}_{'gpu' if use_gpu else 'cpu'}"

            # 2. Cargar sesión ONNX si no existe
            if session_key not in self.rembg_sessions:
                # Construir ruta completa
                full_model_path = os.path.join(REMBG_MODELS_DIR, model_filename)
                
                # Si no está en la carpeta REMBG, buscar en la raíz de models (fallback)
                if not os.path.exists(full_model_path):
                    full_model_path = os.path.join(MODELS_DIR, "rembg", model_filename)
                
                if not os.path.exists(full_model_path):
                    print(f"ERROR: No encuentro el modelo {model_filename}")
                    return pil_image

                hw_label = 'GPU' if use_gpu else 'CPU'
                print(f"DEBUG: Cargando Manualmente {model_filename} en [{hw_label}]")
                
                sess_opts = ort.SessionOptions()

                if use_gpu:
                    # CONFIG GPU (DirectML Anti-Freeze)
                    providers = ['DmlExecutionProvider', 'CPUExecutionProvider']
                    sess_opts.enable_mem_pattern = False 
                    sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
                    sess_opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
                    sess_opts.inter_op_num_threads = 1 
                    sess_opts.intra_op_num_threads = 1
                else:
                    # CONFIG CPU (Máxima Velocidad)
                    providers = ['CPUExecutionProvider']
                    sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                    sess_opts.execution_mode = ort.ExecutionMode.ORT_PARALLEL
                
                # Cargamos la sesión "cruda" de ONNX Runtime
                self.rembg_sessions[session_key] = ort.InferenceSession(
                    full_model_path, 
                    providers=providers, 
                    sess_options=sess_opts
                )
            
            # 3. Obtener sesión
            session = self.rembg_sessions[session_key]
            
            # 4. Determinar resolución (CORREGIDO SEGÚN LOGS)
            model_lower = model_filename.lower()
            
            # Reglas basadas en tus errores:
            # - BiRefNet: SIEMPRE 1024
            # - IsNet (General/Anime): SIEMPRE 1024 (El log dice Expected: 1024)
            # - U2Net (Standard/Human/P): 320
            
            if "birefnet" in model_lower:
                size = (1024, 1024)
            elif "isnet" in model_lower: # <-- CAMBIO CLAVE: IsNet a 1024
                size = (1024, 1024)
            elif "u2net" in model_lower:
                size = (320, 320)
            else:
                # Ante la duda, hoy en día los modelos modernos usan 1024
                size = (1024, 1024) 
            
            # 5. Ejecutar inferencia MANUAL
            output_image = self._process_onnx_manual(pil_image, session, target_size=size)
            
            return output_image
            
        except Exception as e:
            print(f"ERROR CRÍTICO al procesar IA ({model_filename}): {e}")
            import traceback
            traceback.print_exc()
            return pil_image
    
    def convert_file(self, input_path, output_path, options, page_number=None, progress_callback=None, cancellation_event=None):
        """
        Convierte un archivo de imagen al formato especificado.
        
        Args:
            input_path (str): Ruta del archivo de entrada
            output_path (str): Ruta del archivo de salida
            page_number (int, optional): La página específica a procesar
            options (dict): Diccionario con opciones de conversión:
                - format: str - Formato de salida ("PNG", "JPG", "WEBP", etc.)
                - png_transparency: bool
                - png_compression: int (0-9)
                - jpg_quality: int (1-100)
                - jpg_subsampling: str
                - jpg_progressive: bool
                - webp_lossless: bool
                - webp_quality: int (1-100)
                - webp_transparency: bool
                - webp_metadata: bool
                - pdf_combine: bool (manejado fuera)
                - tiff_compression: str
                - tiff_transparency: bool
                - ico_sizes: list[int]
                - bmp_rle: bool
                - resize_enabled: bool (si está activo el escalado)
                - resize_width: int (ancho objetivo)
                - resize_height: int (alto objetivo)
                - resize_maintain_aspect: bool (mantener proporción)
                - interpolation_method: str (método de interpolación para raster)
                - canvas_enabled: bool (si está activo el canvas)
                - canvas_width: int (ancho del canvas)
                - canvas_height: int (alto del canvas)
                - canvas_margin: int (margen interno en píxeles)
                - canvas_position: str (posición del contenido)
                - canvas_overflow_mode: str (qué hacer si imagen > espacio disponible)
        
        Returns:
            bool: True si la conversión fue exitosa
        """
        try:
            # Reporte inicial: Inicio (0-10%)
            if progress_callback: progress_callback(5)

            input_ext = os.path.splitext(input_path)[1].lower()
            output_format = options.get("format", "PNG").upper()
            
            resize_enabled = options.get("resize_enabled", False)
            target_size = None
            maintain_aspect = True
            
            if resize_enabled:
                target_width = options.get("resize_width")
                target_height = options.get("resize_height")
                maintain_aspect = options.get("resize_maintain_aspect", True)
                
                if target_width and target_height:
                    target_size = (int(target_width), int(target_height))
            
            # 1. Cargar imagen
            if cancellation_event and cancellation_event.is_set(): raise UserCancelledError("Cancelado por usuario") # ✅ CHEQUEO
            
            pil_image = self._load_image(input_path, input_ext, target_size, maintain_aspect, options, page_number=page_number)
            
            if not pil_image:
                raise Exception(f"No se pudo cargar la imagen desde {input_path}")
            
            # Reporte: Cargado (30%)
            if progress_callback: progress_callback(30)
            
            if cancellation_event and cancellation_event.is_set(): raise UserCancelledError("Cancelado por usuario") # ✅ CHEQUEO

            # 2. Resize raster
            if resize_enabled and target_size and input_ext not in self.VECTOR_FORMATS:
                pil_image = self._resize_raster_image(pil_image, target_size, maintain_aspect, options)
            
            # Reporte: Resize listo (40%)
            if progress_callback: progress_callback(40)

            if cancellation_event and cancellation_event.is_set(): raise UserCancelledError("Cancelado por usuario") # ✅ CHEQUEO

            # 2.5 Eliminar fondo con IA
            if options.get("rembg_enabled", False):
                model_name = options.get("rembg_model", "u2netp")
                
                # NUEVO: Leer opción de GPU (Default: True)
                use_gpu = options.get("rembg_gpu", True)
                
                print(f"INFO: Eliminando fondo con IA ({model_name} en {'GPU' if use_gpu else 'CPU'})...")
                
                # Reporte con texto para la UI
                if progress_callback: 
                    progress_callback(45, f"Preparando IA ({'GPU' if use_gpu else 'CPU'})...")
                
                # Pasamos el callback y la opción use_gpu
                pil_image = self.remove_background(pil_image, model_name, progress_callback, use_gpu=use_gpu)
                
                # Reporte: IA Terminada (80%)
                if progress_callback: progress_callback(80)
            
            if cancellation_event and cancellation_event.is_set(): raise UserCancelledError("Cancelado por usuario") # ✅ CHEQUEO

            # --- 2.6 REESCALADO CON IA (NUEVO BLOQUE) ---
            if options.get("upscale_enabled", False):
                print("INFO: Iniciando reescalado con IA...")
                if progress_callback: progress_callback(50, f"Reescalando ({options['upscale_engine']})...")
                
                # ✅ CAMBIO: Pasamos el evento de cancelación al upscaler
                pil_image = self._upscale_image_ai(pil_image, options, cancellation_event)
                
                if progress_callback: progress_callback(60)

            if cancellation_event and cancellation_event.is_set(): raise UserCancelledError("Cancelado por usuario") # ✅ CHEQUEO
            
            # 3. Canvas
            canvas_enabled = options.get("canvas_enabled", False)
            if canvas_enabled:
                canvas_option = options.get("canvas_option", "Sin ajuste")
                if canvas_option != "Sin ajuste":
                    pil_image = self._apply_canvas_by_option(pil_image, canvas_option, options)

            # 4. Fondo
            background_enabled = options.get("background_enabled", False)
            if background_enabled:
                pil_image = self._apply_background(pil_image, options)
            
            # Reporte: Preparando guardado (85%)
            if progress_callback: progress_callback(85)
            
            # 5. Guardar (Conversión final)
            if output_format == "NO CONVERTIR":
                input_ext = os.path.splitext(input_path)[1].lower()
                if input_ext in self.RASTER_FORMATS:
                    if input_ext in (".jpg", ".jpeg"): self._save_as_jpg(pil_image, output_path, options)
                    elif input_ext == ".png": self._save_as_png(pil_image, output_path, options)
                    elif input_ext == ".webp": self._save_as_webp(pil_image, output_path, options)
                    elif input_ext in (".tiff", ".tif"): self._save_as_tiff(pil_image, output_path, options)
                    elif input_ext == ".bmp": self._save_as_bmp(pil_image, output_path, options)
                    else: pil_image.save(output_path)
                else:
                    self._save_as_png(pil_image, output_path, options)
            
            elif output_format == "PNG": self._save_as_png(pil_image, output_path, options)
            elif output_format in ["JPG", "JPEG"]: self._save_as_jpg(pil_image, output_path, options)
            elif output_format == "WEBP": self._save_as_webp(pil_image, output_path, options)
            elif output_format == "AVIF": self._save_as_avif(pil_image, output_path, options)
            elif output_format == "PDF": self._save_as_pdf(pil_image, output_path, options)
            elif output_format == "TIFF": self._save_as_tiff(pil_image, output_path, options)
            elif output_format == "ICO": self._save_as_ico(pil_image, output_path, options)
            elif output_format == "BMP": self._save_as_bmp(pil_image, output_path, options)
            else:
                raise Exception(f"Formato de salida no soportado: {output_format}")
            
            # Reporte: Finalizado (100%)
            if progress_callback: progress_callback(100)
            
            return True
            
        except UserCancelledError:
            print(f"INFO: Conversión cancelada para {input_path}")
            return False # Retorna falso para detener
        except Exception as e:
            print(f"ERROR: Fallo la conversión de {input_path}: {e}")
            return False
        
    def _load_raw_with_rawpy(self, filepath):
        """
        Revela archivos RAW usando rawpy (LibRaw).
        ✅ CORREGIDO: Gamma y espacio de color correctos para PNG.
        """
        try:
            import rawpy
            import numpy as np
            
            print(f"INFO: Revelando RAW de alta calidad: {os.path.basename(filepath)}")
            
            with rawpy.imread(filepath) as raw:
                # 🎨 Configuración CORREGIDA (sRGB + Gamma 2.2)
                rgb = raw.postprocess(
                    use_camera_wb=True,           # Balance de blancos original
                    half_size=False,              # Resolución completa
                    no_auto_bright=False,         # ✅ Auto brillo activado
                    output_bps=8,                 # ✅ 8 bits (suficiente para PNG)
                    output_color=rawpy.ColorSpace.sRGB,  # ✅ sRGB (estándar web/PNG)
                    demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD,  # Balance calidad/velocidad
                    use_auto_wb=False,            # No cambiar WB
                    gamma=(2.222, 4.5),           # ✅ Gamma sRGB estándar
                    bright=1.0,                   # Brillo 100%
                    highlight_mode=rawpy.HighlightMode.Blend  # ✅ Blend highlights (más natural)
                )
            
            # Convertir a PIL
            img = Image.fromarray(rgb)
            
            # 🔄 Aplicar rotación EXIF
            try:
                from PIL import ImageOps
                img = ImageOps.exif_transpose(img)
            except:
                pass
            
            print(f"✅ RAW revelado: {img.size[0]}x{img.size[1]} píxeles")
            return img
            
        except ImportError:
            raise Exception(
                "❌ rawpy no está instalado.\n\n"
                "Ejecuta en tu terminal:\n"
                "pip install rawpy imageio\n\n"
                "O descarga desde: https://pypi.org/project/rawpy/"
            )
        except rawpy.LibRawFileUnsupportedError:
            raise Exception(f"Formato RAW no soportado por LibRaw: {os.path.splitext(filepath)[1]}")
        except rawpy.LibRawIOError:
            raise Exception("Archivo RAW corrupto o inaccesible")
        except Exception as e:
            raise Exception(f"Error al revelar RAW: {e}")
    
    def _load_image(self, filepath, ext, target_size=None, maintain_aspect=True, options=None, page_number=None):
        """
        Carga una imagen desde cualquier formato soportado.
        🔧 MEJORADO: Manejo robusto de errores para SVG y PNG corruptos
        """
        
        # Guardar el PATH original
        original_path = os.environ.get('PATH', '')

        # Añadir un fallback por si 'options' no se pasa
        if options is None:
            options = {}
            
        try:
            # --- NUEVO: RAW DE CÁMARA ---
            if ext.upper() in IMAGE_RAW_FORMATS:
                return self._load_raw_with_rawpy(filepath) 

            # --- RASTER: Carga directa con Pillow ---
            elif ext in self.RASTER_FORMATS or ext in self.OTHER_FORMATS:
                try:
                    # 🔧 NUEVO: Aumentar límite de texto en PNG para archivos con muchos metadatos
                    from PIL import PngImagePlugin
                    PngImagePlugin.MAX_TEXT_CHUNK = 10 * (1024**2)  # 10 MB (antes era 1 MB)
                    
                    return Image.open(filepath)
                except Exception as e:
                    # Si falla por metadatos, intentar cargar sin verificación estricta
                    print(f"ADVERTENCIA: Error al cargar {os.path.basename(filepath)}: {e}")
                    print(f"  → Intentando carga sin verificación de metadatos...")
                    
                    try:
                        img = Image.open(filepath)
                        img.load()  # Forzar carga completa
                        return img
                    except Exception as e2:
                        raise Exception(f"No se pudo cargar la imagen raster: {e2}")
            
            # --- SVG: Usar CairoSVG ---
            elif ext == ".svg" and CAN_SVG:
                
                # 🔧 NUEVO: Pre-procesar SVG para corregir atributos inválidos
                try:
                    fixed_svg_path = self._fix_svg_attributes(filepath)
                    svg_to_use = fixed_svg_path if fixed_svg_path else filepath
                    
                    is_no_convert = options.get("format", "PNG") == "NO CONVERTIR"

                    if target_size and not is_no_convert:
                        width, height = target_size
                        
                        if maintain_aspect:
                            # Primero rasterizar sin tamaño para obtener dimensiones originales
                            try:
                                temp_png_data = cairosvg.svg2png(url=svg_to_use)
                            except (ValueError, TypeError) as e:
                                # Si CairoSVG falla, usar Inkscape como fallback
                                print(f"DEBUG: CairoSVG falló para {os.path.basename(filepath)}: {e}")
                                print(f"  → Usando Inkscape como fallback...")
                                if fixed_svg_path and os.path.exists(fixed_svg_path):
                                    try: os.remove(fixed_svg_path)
                                    except: pass
                                return self._convert_with_inkscape(filepath, target_size, maintain_aspect, page_number)
                            
                            temp_img = Image.open(io.BytesIO(temp_png_data))
                            original_width, original_height = temp_img.size
                            
                            # Calcular tamaño manteniendo aspecto
                            original_aspect = original_width / original_height
                            target_aspect = width / height
                            
                            if original_aspect > target_aspect:
                                final_width = width
                                final_height = int(width / original_aspect)
                            else:
                                final_height = height
                                final_width = int(height * original_aspect)
                            
                            # Asegurar que no exceda los límites
                            if final_width > width:
                                final_width = width
                                final_height = int(width / original_aspect)
                            if final_height > height:
                                final_height = height
                                final_width = int(height * original_aspect)
                            
                            print(f"SVG escalado: {original_width}×{original_height} → {final_width}×{final_height}")
                            png_data = cairosvg.svg2png(url=svg_to_use, output_width=final_width, output_height=final_height)
                        else:
                            # Forzar dimensiones exactas
                            png_data = cairosvg.svg2png(url=svg_to_use, output_width=width, output_height=height)
                    else:
                        png_data = cairosvg.svg2png(url=svg_to_use)
                    
                    # Limpiar archivo temporal si existe
                    if fixed_svg_path and os.path.exists(fixed_svg_path):
                        try: os.remove(fixed_svg_path)
                        except: pass
                    
                    return Image.open(io.BytesIO(png_data))
                    
                except Exception as e:
                    print(f"ERROR: Fallo completo en SVG {os.path.basename(filepath)}: {e}")
                    print(f"  → Intentando Inkscape como último recurso...")
                    # Limpiar archivo temporal si existe
                    try:
                        if fixed_svg_path and os.path.exists(fixed_svg_path):
                            os.remove(fixed_svg_path)
                    except: pass
                    # Último intento con Inkscape
                    return self._convert_with_inkscape(filepath, target_size, maintain_aspect, page_number)
            
            # --- VECTORIALES: Usar Inkscape o pdf2image ---
            elif ext in self.VECTOR_FORMATS:
                
                # ✅ CAMBIO: Forzar Inkscape para .ai y .eps
                if ext in (".ai", ".eps", ".ps"): 
                    try:
                        # Intentar primero con Inkscape (Mejor calidad)
                        return self._convert_with_inkscape(filepath, target_size, maintain_aspect, page_number)
                    except Exception as e:
                        print(f"⚠️ Inkscape falló ({e}). Usando respaldo de Pillow/Ghostscript...")
                        # Si falla, usar el método de respaldo
                        return self._load_eps_with_pillow(filepath, target_size)
                
                # Para PDF estándar, seguimos usando Poppler (es más rápido para documentos)
                elif ext == ".pdf" and CAN_PDF:
                    if page_number is None:
                        page_number = 1
                    
                    is_no_convert = options.get("format", "PNG") == "NO CONVERTIR"
                    dpi = 300
                    if target_size and not is_no_convert:
                        dpi = self._calculate_optimal_dpi(filepath, ext, target_size, maintain_aspect)

                    print(f"DEBUG: Rasterizando PDF página {page_number} con DPI {dpi}")
                    
                    images = convert_from_path(filepath, first_page=page_number, last_page=page_number, dpi=dpi, poppler_path=self.poppler_path)
                    if images:
                        pdf_img = images[0]
                        
                        # Si maintain_aspect, ajustar el tamaño después de rasterizar
                        if target_size and maintain_aspect:
                            original_width, original_height = pdf_img.size
                            target_width, target_height = target_size
                            original_aspect = original_width / original_height
                            target_aspect = target_width / target_height
                            
                            if original_aspect > target_aspect:
                                new_width = target_width
                                new_height = int(target_width / original_aspect)
                            else:
                                new_height = target_height
                                new_width = int(target_height * original_aspect)
                            
                            if new_width > target_width:
                                new_width = target_width
                                new_height = int(target_width / original_aspect)
                            if new_height > target_height:
                                new_height = target_height
                                new_width = int(target_height * original_aspect)
                            
                            from PIL import Image as PILImage
                            pdf_img = pdf_img.resize((new_width, new_height), PILImage.Resampling.LANCZOS)
                        
                        return pdf_img
            
                else:
                    # Fallback: Intentar con Pillow
                    return Image.open(filepath)
        
        finally:
            # Restaurar el PATH original
            os.environ['PATH'] = original_path

    # --- NUEVO MÉTODO DE RESPALDO ---
    def _load_eps_with_pillow(self, filepath, target_size=None):
        """Respaldo: Carga EPS calculando la escala exacta para HD/4K."""
        try:
            # 1. Abrir sin cargar (lazy) para leer dimensiones base (en puntos)
            img = Image.open(filepath)
            base_width, base_height = img.size
            
            # 2. Calcular escala necesaria
            scale = 4 # Default alto
            
            if target_size and base_width > 0 and base_height > 0:
                target_w, target_h = target_size
                
                # ¿Cuánto tengo que multiplicar el ancho base para llegar al objetivo?
                scale_x = target_w / base_width
                scale_y = target_h / base_height
                
                # Usamos el mayor para que sobre calidad (supersampling) y luego reducimos
                # Añadimos un 20% extra (* 1.2) para antialiasing perfecto al reducir
                required_scale = max(scale_x, scale_y) * 1.2
                
                # Pillow necesita un entero, mínimo 1
                scale = int(max(1, round(required_scale)))
                
                # Límite de seguridad para no explotar la RAM con escalas absurdas
                if scale > 50: scale = 50 

            print(f"DEBUG: Renderizando EPS con escala x{scale} para alcanzar objetivo.")

            # 3. Cargar con la escala calculada
            img.load(scale=scale)
            
            if img.mode != "RGBA": img = img.convert("RGBA")
            
            # 4. Auto-Crop (Quitar bordes blancos)
            bg = Image.new(img.mode, img.size, (255, 255, 255, 0))
            diff = ImageChops.difference(img, bg)
            bbox = diff.getbbox()
            if bbox: img = img.crop(bbox)
            
            return img
            
        except Exception as e:
            raise Exception(f"Fallo total (Inkscape y Pillow): {e}")

    def _convert_with_inkscape(self, filepath, target_size=None, maintain_aspect=True, page_number=1):
        """
        Convierte usando Inkscape con estrategia de DPI Alto + Redimensionado.
        ✅ CORREGIDO: Verifica Ghostscript antes de intentar conversión EPS/PS.
        """
        import subprocess
        import tempfile
        
        ext = os.path.splitext(filepath)[1].lower()
        temp_pdf_path = None  # Para limpieza en finally
        
        # ✅ NUEVO: Convertir EPS/PS a PDF temporal primero
        if ext in (".eps", ".ps"):
            if not self.gs_exe or not os.path.exists(self.gs_exe):
                error_msg = f"Ghostscript no disponible. gs_exe={self.gs_exe}"
                print(f"ERROR: {error_msg}")
                raise Exception(error_msg)
            
            # Crear PDF temporal
            temp_pdf = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
            temp_pdf.close()
            temp_pdf_path = temp_pdf.name
            
            try:
                print(f"DEBUG: Convirtiendo {ext.upper()} a PDF temporal con Ghostscript...")
                print(f"DEBUG: Usando Ghostscript: {self.gs_exe}")
                
                # Comando Ghostscript para EPS→PDF (conserva vectores)
                gs_cmd = [
                    self.gs_exe,
                    '-dNOPAUSE',
                    '-dBATCH',
                    '-dSAFER',
                    '-sDEVICE=pdfwrite',
                    '-dEPSCrop',  # ✅ Recorta al BoundingBox del EPS
                    f'-sOutputFile={temp_pdf_path}',
                    filepath
                ]
                
                print(f"DEBUG: Comando GS: {' '.join(gs_cmd)}")
                
                result = subprocess.run(
                    gs_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=30,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                )
                
                if result.returncode != 0:
                    stderr = result.stderr.decode('utf-8', errors='ignore')
                    raise Exception(f"Ghostscript falló (código {result.returncode}): {stderr[:300]}")
                
                if not os.path.exists(temp_pdf_path):
                    raise Exception("Ghostscript no generó archivo de salida")
                
                pdf_size = os.path.getsize(temp_pdf_path)
                if pdf_size == 0:
                    raise Exception("Ghostscript generó un PDF vacío")
                
                print(f"✅ PDF temporal creado: {temp_pdf_path} ({pdf_size} bytes)")
                
                # Ahora usar este PDF en lugar del EPS original
                filepath_to_process = temp_pdf_path
                
            except Exception as e:
                # Limpiar archivo temporal
                if temp_pdf_path and os.path.exists(temp_pdf_path):
                    try: os.remove(temp_pdf_path)
                    except: pass
                raise Exception(f"Conversión EPS→PDF falló: {e}")
        else:
            filepath_to_process = filepath

        # Crear PNG de salida temporal
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_file:
            temp_png = tmp_file.name

        try:
            # Construir comando base (ahora filepath_to_process puede ser PDF temporal)
            cmd = self._build_inkscape_command(filepath_to_process, temp_png, page_number, dpi=300)

            # Si hay un tamaño objetivo, inyectar comandos de escalado vectorial
            if target_size:
                width, height = target_size
                
                # Eliminar argumentos de DPI si existen para evitar conflictos
                cmd = [c for c in cmd if not c.startswith("--export-dpi")]
                
                if maintain_aspect:
                    cmd.insert(2, f"--export-width={width}")
                else:
                    cmd.insert(2, f"--export-width={width}")
                    cmd.insert(3, f"--export-height={height}")
                
                print(f"DEBUG: Forzando renderizado vectorial a {width}px")

            print(f"DEBUG: Ejecutando Inkscape: {' '.join(cmd[:5])}...")

            # Preparar entorno con Ghostscript
            env = os.environ.copy()
            
            if self.gs_dir and self.gs_exe:
                env["PATH"] = f"{self.gs_dir};{env.get('PATH', '')}"
                env["GS_PROG"] = self.gs_exe

            # Ejecutar Inkscape
            result = subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            )
            
            # Verificar que el archivo se creó
            if not os.path.exists(temp_png) or os.path.getsize(temp_png) == 0:
                stderr = result.stderr.decode('utf-8', errors='ignore')
                raise Exception(f"Inkscape no generó salida. STDERR: {stderr[:500]}")
            
            print(f"✅ Inkscape generó PNG: {os.path.getsize(temp_png)} bytes")
            
            # Cargar imagen resultante
            img = Image.open(temp_png)
            img.load()
            
            # Aplicar el tamaño exacto solicitado
            if target_size:
                if maintain_aspect:
                    img.thumbnail(target_size, Image.Resampling.LANCZOS)
                else:
                    img = img.resize(target_size, Image.Resampling.LANCZOS)

            return img
        
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode('utf-8', errors='ignore')
            
            # Fallback a Poppler para archivos PDF-like
            if CAN_PDF and ext in (".ai", ".pdf"):
                print(f"DEBUG: Inkscape falló, usando Poppler para página {page_number}")
                try:
                    images = convert_from_path(
                        filepath_to_process,
                        first_page=page_number,
                        last_page=page_number,
                        dpi=300,
                        poppler_path=self.poppler_path
                    )
                    if images:
                        img = images[0]
                        if target_size:
                            if maintain_aspect:
                                img.thumbnail(target_size, Image.Resampling.LANCZOS)
                            else:
                                img = img.resize(target_size, Image.Resampling.LANCZOS)
                        return img
                except Exception as fallback_error:
                    print(f"ERROR en fallback Poppler: {fallback_error}")
            
            raise Exception(f"Inkscape CLI falló: {stderr[:300]}")
        except Exception as e:
            raise Exception(f"Error Inkscape: {e}")
        finally:
            # Limpiar archivos temporales
            if os.path.exists(temp_png):
                try: os.remove(temp_png)
                except: pass
            
            # Limpiar PDF temporal si existe
            if temp_pdf_path and os.path.exists(temp_pdf_path):
                try: 
                    os.remove(temp_pdf_path)
                    print(f"DEBUG: PDF temporal eliminado")
                except: pass

    def _fix_svg_attributes(self, svg_path):
        """
        Lee un SVG y corrige atributos width/height inválidos.
        🔧 MEJORADO: Maneja casos más complejos como height="px" sin número
        """
        try:
            import re
            import tempfile
            
            # Leer el contenido del SVG
            with open(svg_path, 'r', encoding='utf-8') as f:
                svg_content = f.read()
            
            # Buscar el tag <svg> y sus atributos
            svg_tag_pattern = r'<svg([^>]*)>'
            match = re.search(svg_tag_pattern, svg_content, re.IGNORECASE)
            
            if not match:
                return None  # No se encontró el tag <svg>
            
            svg_attributes = match.group(1)
            needs_fix = False
            fixed_attributes = svg_attributes
            
            # 🔧 Patrones simples primero
            simple_patterns = [
                (r'width\s*=\s*"px"', 'width="180"'),
                (r'width\s*=\s*""', 'width="180"'),
                (r'width\s*=\s*"\s*px\s*"', 'width="180"'),
                (r'height\s*=\s*"px"', 'height="180"'),
                (r'height\s*=\s*""', 'height="180"'),
                (r'height\s*=\s*"\s*px\s*"', 'height="180"'),
            ]
            
            # Aplicar patrones simples
            for pattern, replacement in simple_patterns:
                if re.search(pattern, fixed_attributes, re.IGNORECASE):
                    fixed_attributes = re.sub(pattern, replacement, fixed_attributes, flags=re.IGNORECASE)
                    needs_fix = True
            
            # 🔧 Manejar "180px" → "180" (quitar solo el "px")
            def clean_px_width(match):
                value = match.group(0).split('"')[1]
                value_clean = value.replace('px', '').strip()
                return f'width="{value_clean}"'
            
            def clean_px_height(match):
                value = match.group(0).split('"')[1]
                value_clean = value.replace('px', '').strip()
                return f'height="{value_clean}"'
            
            # Aplicar limpieza de "px"
            if re.search(r'width\s*=\s*"\d+px"', fixed_attributes, re.IGNORECASE):
                fixed_attributes = re.sub(r'width\s*=\s*"\d+px"', clean_px_width, fixed_attributes, flags=re.IGNORECASE)
                needs_fix = True
            
            if re.search(r'height\s*=\s*"\d+px"', fixed_attributes, re.IGNORECASE):
                fixed_attributes = re.sub(r'height\s*=\s*"\d+px"', clean_px_height, fixed_attributes, flags=re.IGNORECASE)
                needs_fix = True
            
            if not needs_fix:
                return None
            
            # Reconstruir el SVG
            fixed_svg_content = re.sub(
                svg_tag_pattern, 
                f'<svg{fixed_attributes}>', 
                svg_content, 
                count=1, 
                flags=re.IGNORECASE
            )
            
            # Guardar en archivo temporal
            temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.svg', delete=False, encoding='utf-8')
            temp_file.write(fixed_svg_content)
            temp_file.close()
            
            print(f"DEBUG: ✅ SVG corregido guardado: {temp_file.name}")
            return temp_file.name
            
        except Exception as e:
            print(f"ADVERTENCIA: No se pudo preprocesar el SVG: {e}")
            return None

    def _quote_path_if_needed(self, path):
        """Envuelve la ruta en comillas si contiene espacios (solo para debugging)."""
        if ' ' in path and not path.startswith('"'):
            return f'"{path}"'
        return path
        
    def _build_inkscape_command(self, filepath, output_path, page_number=1, dpi=96, artboard_id=None):
        """
        Construye el comando de Inkscape según el tipo de archivo.
        CORREGIDO: Detecta automáticamente si el .ai tiene múltiples páginas.
        """
        ink_exe = "inkscape.exe" if os.name == "nt" else "inkscape"
        if self.inkscape_path:
            ink_cmd = os.path.join(self.inkscape_path, ink_exe)
        else:
            ink_cmd = ink_exe
        
        ext = os.path.splitext(filepath)[1].lower()
        
        cmd = [
            ink_cmd,
            filepath,
            f"--export-filename={output_path}",
            f"--export-dpi={dpi}",
            "--export-type=png"
        ]
        
        # ✅ Estrategia por tipo de archivo
        if ext == ".ai":
            # 🔧 NUEVO: Detectar si el .ai tiene múltiples páginas
            try:
                from pdf2image import pdfinfo_from_path
                info = pdfinfo_from_path(filepath, poppler_path=self.poppler_path)
                page_count = int(info.get('Pages', 1))
            except Exception:
                page_count = 1
            
            # Solo usar --pages si hay múltiples páginas
            if page_count > 1:
                cmd.insert(2, "--pdf-poppler")
                cmd.insert(2, f"--pages={page_number}")
                cmd.insert(4, "--export-area-page")
                print(f"DEBUG: .ai con {page_count} páginas → usando --pages={page_number}")
            else:
                # Archivo de una sola página: tratarlo como EPS simple
                cmd.insert(2, "--export-area-page")
                print(f"DEBUG: .ai de 1 página → sin --pages")
        
        elif ext in (".eps", ".ps"):
            # EPS/PS: Solo export-area-page
            cmd.insert(2, "--export-area-page")
        
        elif ext == ".svg" and artboard_id:
            # SVG con artboard específico
            cmd.insert(2, f"--export-id={artboard_id}")
            cmd.insert(3, "--export-id-only")
        
        else:
            # Default
            cmd.insert(2, "--export-area-page")
        
        return cmd
    
    # ========================================================================
    # MÉTODOS DE GUARDADO POR FORMATO
    # ========================================================================
    
    def _save_as_png(self, img, output_path, options):
        """Guarda como PNG con opciones optimizadas para imágenes grandes."""
        
        # 1. Gestionar transparencia
        if options.get("png_transparency", True) and img.mode in ("RGBA", "LA", "PA"):
            save_img = img
        else:
            save_img = img.convert("RGB")
        
        # 2. Obtener nivel de compresión del usuario
        compression = options.get("png_compression", 6)
        
        # 3. Lógica inteligente para imágenes gigantes (Upscaling)
        width, height = save_img.size
        total_pixels = width * height
        is_huge_image = total_pixels > (3840 * 2160) # Más grande que 4K
        
        use_optimize = True
        
        if is_huge_image:
            print(f"DEBUG: Imagen gigante detectada ({width}x{height}). Optimizando velocidad de guardado...")
            # Desactivar optimización extra de Pillow (es muy lenta en 8K)
            use_optimize = False 
            # Si la compresión es muy alta, bajarla un poco para no congelar la app
            if compression > 3:
                print(f"DEBUG: Reduciendo compresión de {compression} a 3 para velocidad.")
                compression = 3

        # 4. Guardar UNA SOLA VEZ
        # Eliminamos el bloque try/except de "regeneración" porque save_img.save ya escribe los metadatos básicos
        # y la doble escritura es lo que mata el rendimiento.
        try:
            save_img.save(output_path, "PNG", compress_level=compression, optimize=use_optimize)
            
            # Flush explícito para asegurar escritura
            with open(output_path, 'r+b') as f:
                f.flush()
                os.fsync(f.fileno())
                
        except Exception as e:
            print(f"ERROR al guardar PNG: {e}")
    
    def _save_as_jpg(self, img, output_path, options):
        """Guarda como JPG con opciones."""
        # JPG no soporta transparencia
        if img.mode in ("RGBA", "LA", "PA"):
            # Crear fondo blanco
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "RGBA":
                background.paste(img, mask=img.split()[3])
            else:
                background.paste(img)
            save_img = background
        else:
            save_img = img.convert("RGB")
        
        # Opciones de calidad
        quality = options.get("jpg_quality", 90)
        
        # Subsampling de croma
        subsampling_map = {
            "4:2:0 (Estándar)": "4:2:0",
            "4:2:2 (Alta)": "4:2:2",
            "4:4:4 (Máxima)": "4:4:4"
        }
        subsampling_str = options.get("jpg_subsampling", "4:2:0 (Estándar)")
        subsampling = subsampling_map.get(subsampling_str, "4:2:0")
        
        # Progresivo
        progressive = options.get("jpg_progressive", False)
        
        # 🔧 MODIFICADO: Guardar con parámetros explícitos
        save_img.save(
            output_path, 
            "JPEG", 
            quality=quality,
            subsampling=subsampling,
            progressive=progressive,
            optimize=True
        )
        
        # 🔧 NUEVO: Re-abrir y re-guardar para regenerar metadatos
        try:
            temp_img = Image.open(output_path)
            temp_img.load()
            temp_img.save(
                output_path, 
                "JPEG", 
                quality=quality,
                subsampling=subsampling,
                progressive=progressive,
                optimize=True
            )
            temp_img.close()
            print(f"✅ JPG regenerado: {os.path.basename(output_path)}")
        except Exception as e:
            print(f"⚠️ Advertencia al regenerar JPG: {e}")
    
    def _save_as_webp(self, img, output_path, options):
        """Guarda como WEBP con opciones."""
        # Mantener transparencia si está activado
        if options.get("webp_transparency", True) and img.mode in ("RGBA", "LA", "PA"):
            save_img = img
        else:
            save_img = img.convert("RGB")
        
        save_kwargs = {
            "format": "WEBP",
            "lossless": options.get("webp_lossless", False)
        }
        
        # Calidad solo si no es lossless
        if not save_kwargs["lossless"]:
            save_kwargs["quality"] = options.get("webp_quality", 90)
        
        # Metadatos EXIF
        if options.get("webp_metadata", False) and hasattr(img, 'info') and 'exif' in img.info:
            save_kwargs["exif"] = img.info['exif']
        
        save_img.save(output_path, **save_kwargs)

        # 🔧 NUEVO: Forzar flush al disco (Windows)
        try:
            with open(output_path, 'r+b') as f:
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            pass  # No crítico si falla
    
    def _save_as_pdf(self, img, output_path, options):
        """Guarda como PDF."""
        # PDF requiere RGB
        if img.mode not in ("RGB", "L"):
            save_img = img.convert("RGB")
        else:
            save_img = img
        
        # Usar img2pdf si está disponible (más rápido y mejor calidad)
        if CAN_IMG2PDF:
            # Guardar imagen temporal
            temp_png = tempfile.mktemp(suffix='.png')
            save_img.save(temp_png, "PNG")
            
            try:
                with open(output_path, "wb") as f:
                    f.write(img2pdf.convert(temp_png))
                os.remove(temp_png)
            except Exception as e:
                if os.path.exists(temp_png):
                    os.remove(temp_png)
                raise e
        else:
            # Fallback: Usar Pillow
            save_img.save(output_path, "PDF", resolution=100.0)

            # 🔧 NUEVO: Forzar flush al disco (Windows)
            try:
                with open(output_path, 'r+b') as f:
                    f.flush()
                    os.fsync(f.fileno())
            except Exception:
                pass  # No crítico si falla
    
    def _save_as_tiff(self, img, output_path, options):
        """Guarda como TIFF con opciones."""
        # Mantener transparencia si está activado
        if options.get("tiff_transparency", True) and img.mode in ("RGBA", "LA", "PA"):
            save_img = img
        else:
            save_img = img.convert("RGB")
        
        # Mapeo de compresión
        compression_map = {
            "Ninguna": None,
            "LZW (Recomendada)": "tiff_lzw",
            "Deflate (ZIP)": "tiff_deflate",
            "PackBits": "packbits"
        }
        compression_str = options.get("tiff_compression", "LZW (Recomendada)")
        compression = compression_map.get(compression_str)
        
        save_kwargs = {"format": "TIFF"}
        if compression:
            save_kwargs["compression"] = compression
        
        save_img.save(output_path, **save_kwargs)

        # 🔧 NUEVO: Forzar flush al disco (Windows)
        try:
            with open(output_path, 'r+b') as f:
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            pass  # No crítico si falla
    
    def _save_as_ico(self, img, output_path, options):
        """Guarda como ICO con múltiples tamaños."""
        # ICO requiere RGBA
        if img.mode != "RGBA":
            save_img = img.convert("RGBA")
        else:
            save_img = img
        
        # Obtener tamaños seleccionados
        ico_sizes_dict = options.get("ico_sizes", {})
        selected_sizes = [size for size, selected in ico_sizes_dict.items() if selected]
        
        if not selected_sizes:
            # Por defecto: 32x32 y 256x256
            selected_sizes = [32, 256]
        
        # Crear imágenes redimensionadas
        sizes_list = [(size, size) for size in selected_sizes]
        
        save_img.save(output_path, "ICO", sizes=sizes_list)

        # 🔧 NUEVO: Forzar flush al disco (Windows)
        try:
            with open(output_path, 'r+b') as f:
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            pass  # No crítico si falla
    
    def _save_as_bmp(self, img, output_path, options):
        """Guarda como BMP con opciones."""
        # BMP no soporta transparencia (normalmente)
        if img.mode in ("RGBA", "LA", "PA"):
            save_img = img.convert("RGB")
        else:
            save_img = img.convert("RGB")
        
        # Compresión RLE (solo para BMP de 8 bits)
        # Pillow no soporta RLE automáticamente, así que lo ignoramos
        # (La mayoría de apps modernas no usan BMP con RLE)
        
        save_img.save(output_path, "BMP")

        # 🔧 NUEVO: Forzar flush al disco (Windows)
        try:
            with open(output_path, 'r+b') as f:
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            pass  # No crítico si falla

    # ========================================================================
    # MÉTODOS DE ESCALADO
    # ========================================================================
    
    def _calculate_optimal_dpi(self, filepath, ext, target_size, maintain_aspect):
        """
        Calcula el DPI óptimo para rasterizar un vector al tamaño objetivo.
        """
        # Aquí implementarás la lógica de cálculo de DPI
        # Por ahora, placeholder:
        target_width, target_height = target_size
        
        # Asumir tamaño de documento estándar (8.5x11 pulgadas - carta)
        # Esto es un placeholder, idealmente deberías leer las dimensiones reales del PDF
        doc_width_inches = 8.5
        doc_height_inches = 11.0
        
        dpi_width = target_width / doc_width_inches
        dpi_height = target_height / doc_height_inches
        
        if maintain_aspect:
            # Usar el menor para mantener proporción
            optimal_dpi = min(dpi_width, dpi_height)
        else:
            # Usar un promedio
            optimal_dpi = (dpi_width + dpi_height) / 2
        
        # Limitar DPI a un rango razonable
        optimal_dpi = max(72, min(optimal_dpi, 2400))
        
        print(f"DPI calculado: {optimal_dpi:.0f} para {target_size}")
        return int(optimal_dpi)
    
    def _resize_raster_image(self, img, target_size, maintain_aspect, options):
        """
        Reescala una imagen raster usando el método de interpolación especificado.
        """
        from PIL import Image as PILImage
        
        target_width, target_height = target_size
        original_width, original_height = img.size
        
        # Obtener método de interpolación
        interp_method_name = options.get("interpolation_method", "Lanczos (Mejor Calidad)")
        
        # Mapear al enum de Pillow
        method_map = {
            "LANCZOS": PILImage.Resampling.LANCZOS,
            "BICUBIC": PILImage.Resampling.BICUBIC,
            "BILINEAR": PILImage.Resampling.BILINEAR,
            "NEAREST": PILImage.Resampling.NEAREST
        }
        
        # Obtener el valor del enum desde el nombre del método
        from src.core.constants import INTERPOLATION_METHODS
        method_key = INTERPOLATION_METHODS.get(interp_method_name, "LANCZOS")
        resampling = method_map.get(method_key, PILImage.Resampling.LANCZOS)
        
        if maintain_aspect:
            # Calcular nuevo tamaño manteniendo aspecto
            # Usamos el MENOR lado del límite como referencia
            original_aspect = original_width / original_height
            target_aspect = target_width / target_height
            
            if original_aspect > target_aspect:
                # Imagen más ancha que el límite → usar target_width
                new_width = target_width
                new_height = int(target_width / original_aspect)
            else:
                # Imagen más alta que el límite → usar target_height
                new_height = target_height
                new_width = int(target_height * original_aspect)
            
            # Asegurar que no exceda los límites
            if new_width > target_width:
                new_width = target_width
                new_height = int(target_width / original_aspect)
            if new_height > target_height:
                new_height = target_height
                new_width = int(target_height * original_aspect)
            
            return img.resize((new_width, new_height), resampling)
        else:
            # Forzar dimensiones exactas (puede distorsionar)
            return img.resize((target_width, target_height), resampling)
    
    def validate_target_size(self, target_size):
        """
        Valida el tamaño objetivo y retorna warnings si es necesario.
        Returns: (is_safe, warning_message)
        """
        from src.core.constants import (
            MAX_RECOMMENDED_DPI, MAX_SAFE_DIMENSION,
            CRITICAL_DPI_THRESHOLD, CRITICAL_DIMENSION_THRESHOLD
        )
        
        width, height = target_size
        max_dimension = max(width, height)
        
        # Crítico (muy peligroso)
        if max_dimension > CRITICAL_DIMENSION_THRESHOLD:
            return (False, f"⚠️ ADVERTENCIA: Resolución muy alta ({width}×{height}).\n\n"
                          f"Esto puede causar:\n"
                          f"• Consumo excesivo de RAM (>4GB)\n"
                          f"• Posible crasheo de la aplicación\n"
                          f"• Tiempo de procesamiento muy largo\n\n"
                          f"Recomendación: Usar máximo {CRITICAL_DIMENSION_THRESHOLD}×{CRITICAL_DIMENSION_THRESHOLD}.")
        
        # Alto (advertencia)
        elif max_dimension > MAX_SAFE_DIMENSION:
            return (True, f"⚠️ Resolución alta ({width}×{height}).\n\n"
                         f"Puede requerir bastante RAM.\n"
                         f"Tiempo estimado: 30s-2min por archivo.\n\n"
                         f"¿Continuar?")
        
        # Seguro
        return (True, None)
    
    def _apply_canvas_by_option(self, img, canvas_option, options):
        """
        Aplica canvas según la opción seleccionada.
        ✅ CORREGIDO: Mantiene transparencia correctamente.
        """
        from PIL import Image as PILImage
        from src.core.constants import CANVAS_PRESET_SIZES
        
        img_width, img_height = img.size
        
        # ✅ CRÍTICO: Asegurar que la imagen esté en RGBA antes de cualquier cosa
        if img.mode != "RGBA":
            print(f"DEBUG: Convirtiendo imagen de {img.mode} a RGBA para canvas")
            img = img.convert("RGBA")
        
        # Determinar el tamaño del canvas según la opción
        if canvas_option == "Añadir Margen Externo":
            margin = options.get("canvas_margin", 100)
            canvas_width = img_width + (margin * 2)
            canvas_height = img_height + (margin * 2)
            print(f"Margen Externo: Canvas expandido a {canvas_width}×{canvas_height} (margen: {margin}px)")
        
        elif canvas_option == "Añadir Margen Interno":
            margin = options.get("canvas_margin", 100)
            canvas_width = img_width
            canvas_height = img_height
            
            new_width = max(1, img_width - (margin * 2))
            new_height = max(1, img_height - (margin * 2))
            
            if new_width < img_width or new_height < img_height:
                img = img.resize((new_width, new_height), PILImage.Resampling.LANCZOS)
                img_width, img_height = new_width, new_height
                print(f"Margen Interno: Imagen reducida a {new_width}×{new_height} (margen: {margin}px)")
            else:
                print(f"ADVERTENCIA: Margen interno ({margin}px) demasiado grande, imagen no reducida")
        
        elif canvas_option in CANVAS_PRESET_SIZES:
            canvas_width, canvas_height = CANVAS_PRESET_SIZES[canvas_option]
            print(f"Preset aplicado: Canvas {canvas_width}×{canvas_height}")
        
        elif canvas_option == "Personalizado...":
            canvas_width = int(options.get("canvas_width", img_width))
            canvas_height = int(options.get("canvas_height", img_height))
            print(f"Canvas personalizado: {canvas_width}×{canvas_height}")
        
        else:
            return img
        
        # 🔥 Verificar si la imagen excede el canvas (solo para presets y personalizado)
        if canvas_option not in ["Añadir Margen Externo", "Añadir Margen Interno"]:
            exceeds_canvas = img_width > canvas_width or img_height > canvas_height
            
            if exceeds_canvas:
                overflow_mode = options.get("canvas_overflow_mode", "Centrar (puede recortar)")
                
                if overflow_mode == "Advertir y no procesar":
                    raise Exception(
                        f"La imagen ({img_width}×{img_height}) excede el canvas ({canvas_width}×{canvas_height}). "
                        f"Activa 'Cambiar Tamaño' para escalar primero."
                    )
                
                elif overflow_mode == "Reducir hasta que quepa":
                    scale_w = canvas_width / img_width
                    scale_h = canvas_height / img_height
                    scale = min(scale_w, scale_h)
                    
                    new_w = int(img_width * scale)
                    new_h = int(img_height * scale)
                    
                    img = img.resize((new_w, new_h), PILImage.Resampling.LANCZOS)
                    img_width, img_height = new_w, new_h
                    print(f"Imagen escalada manteniendo aspecto: {new_w}×{new_h}")
                
                elif overflow_mode in ["Recortar al canvas", "Centrar (puede recortar)"]:
                    left = max(0, (img_width - canvas_width) // 2)
                    top = max(0, (img_height - canvas_height) // 2)
                    right = left + canvas_width
                    bottom = top + canvas_height
                    
                    img = img.crop((left, top, right, bottom))
                    img_width, img_height = img.size
                    print(f"Imagen recortada a {img_width}×{img_height} para ajustar al canvas")
        
        # ✅ CORRECCIÓN CRÍTICA: Crear canvas TRANSPARENTE siempre que la imagen sea RGBA
        print(f"DEBUG: Creando canvas RGBA transparente de {canvas_width}×{canvas_height}")
        canvas = PILImage.new("RGBA", (canvas_width, canvas_height), (0, 0, 0, 0))
        
        # Calcular posición
        position = options.get("canvas_position", "Centro")
        x, y = self._calculate_canvas_position(canvas_width, canvas_height, img_width, img_height, position)
        
        # Pegar imagen en el canvas usando el canal alpha
        print(f"DEBUG: Pegando imagen RGBA en posición ({x}, {y})")
        canvas.paste(img, (x, y), img)  # El tercer parámetro usa el canal alpha de img como máscara
        
        print(f"Canvas final: {canvas_width}×{canvas_height} con imagen {img_width}×{img_height} en posición {position}")
        print(f"✅ Modo del canvas resultante: {canvas.mode}")
        
        return canvas

    def _calculate_canvas_position(self, canvas_w, canvas_h, img_w, img_h, position):
        """
        Calcula las coordenadas X,Y para colocar la imagen en el canvas.
        
        Args:
            canvas_w, canvas_h: Dimensiones del canvas
            img_w, img_h: Dimensiones de la imagen
            position: str - Posición deseada
        
        Returns:
            (x, y): Coordenadas para pegar la imagen
        """
        # Mapeo de posiciones
        position_map = {
            "Centro": ("center", "center"),
            "Arriba Izquierda": ("left", "top"),
            "Arriba Centro": ("center", "top"),
            "Arriba Derecha": ("right", "top"),
            "Centro Izquierda": ("left", "center"),
            "Centro Derecha": ("right", "center"),
            "Abajo Izquierda": ("left", "bottom"),
            "Abajo Centro": ("center", "bottom"),
            "Abajo Derecha": ("right", "bottom")
        }
        
        h_align, v_align = position_map.get(position, ("center", "center"))
        
        # Calcular coordenada X
        if h_align == "left":
            x = 0
        elif h_align == "center":
            x = (canvas_w - img_w) // 2
        else:  # right
            x = canvas_w - img_w
        
        # Calcular coordenada Y
        if v_align == "top":
            y = 0
        elif v_align == "center":
            y = (canvas_h - img_h) // 2
        else:  # bottom
            y = canvas_h - img_h
        
        return (x, y)
    
    def _apply_background(self, img, options):
        """
        Reemplaza el fondo transparente de una imagen con un color, degradado o imagen.
        
        Args:
            img: PIL.Image - Imagen con transparencia
            options: dict - Opciones de fondo
        
        Returns:
            PIL.Image - Imagen con fondo aplicado
        """
        from PIL import Image as PILImage, ImageDraw
        
        # Si la imagen no tiene transparencia, no hacer nada
        if img.mode not in ("RGBA", "LA", "PA"):
            print("ADVERTENCIA: La imagen no tiene canal de transparencia, no se aplica fondo")
            return img
        
        background_type = options.get("background_type", "Color Sólido")
        width, height = img.size
        
        # Crear el fondo según el tipo
        if background_type == "Color Sólido":
            bg_color_hex = options.get("background_color", "#FFFFFF")
            bg_color = self._hex_to_rgb(bg_color_hex)
            background = PILImage.new("RGB", (width, height), bg_color)
            print(f"Fondo sólido aplicado: {bg_color_hex}")
        
        elif background_type == "Degradado":
            color1_hex = options.get("background_gradient_color1", "#FF0000")
            color2_hex = options.get("background_gradient_color2", "#0000FF")
            direction = options.get("background_gradient_direction", "Horizontal (Izq → Der)")
            
            background = self._create_gradient(width, height, color1_hex, color2_hex, direction)
            print(f"Degradado aplicado: {color1_hex} → {color2_hex} ({direction})")
        
        elif background_type == "Imagen de Fondo":
            bg_image_path = options.get("background_image_path")
            
            if not bg_image_path or not os.path.exists(bg_image_path):
                print("ADVERTENCIA: Ruta de imagen de fondo no válida, usando blanco")
                background = PILImage.new("RGB", (width, height), (255, 255, 255))
            else:
                try:
                    bg_img = PILImage.open(bg_image_path)
                    # Redimensionar/recortar la imagen de fondo al tamaño de la imagen
                    background = bg_img.resize((width, height), PILImage.Resampling.LANCZOS)
                    if background.mode != "RGB":
                        background = background.convert("RGB")
                    print(f"Imagen de fondo aplicada: {os.path.basename(bg_image_path)}")
                except Exception as e:
                    print(f"ERROR: No se pudo cargar imagen de fondo: {e}")
                    background = PILImage.new("RGB", (width, height), (255, 255, 255))
        
        else:
            # Fallback: fondo blanco
            background = PILImage.new("RGB", (width, height), (255, 255, 255))
        
        # Pegar la imagen sobre el fondo usando el canal alpha como máscara
        background.paste(img, (0, 0), img)
        
        return background

    def _hex_to_rgb(self, hex_color):
        """Convierte un color hexadecimal (#RRGGBB) a tupla RGB."""
        hex_color = hex_color.lstrip('#')
        try:
            return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        except:
            print(f"ADVERTENCIA: Color hexadecimal inválido '{hex_color}', usando blanco")
            return (255, 255, 255)

    def _create_gradient(self, width, height, color1_hex, color2_hex, direction):
        """
        Crea un degradado entre dos colores.
        
        Args:
            width, height: Dimensiones de la imagen
            color1_hex, color2_hex: Colores en formato hexadecimal
            direction: Dirección del degradado
        
        Returns:
            PIL.Image - Imagen con degradado
        """
        from PIL import Image as PILImage, ImageDraw
        
        color1 = self._hex_to_rgb(color1_hex)
        color2 = self._hex_to_rgb(color2_hex)
        
        base = PILImage.new("RGB", (width, height), color1)
        draw = ImageDraw.Draw(base)
        
        if direction == "Horizontal (Izq → Der)":
            for x in range(width):
                ratio = x / width
                r = int(color1[0] * (1 - ratio) + color2[0] * ratio)
                g = int(color1[1] * (1 - ratio) + color2[1] * ratio)
                b = int(color1[2] * (1 - ratio) + color2[2] * ratio)
                draw.line([(x, 0), (x, height)], fill=(r, g, b))
        
        elif direction == "Vertical (Arr → Aba)":
            for y in range(height):
                ratio = y / height
                r = int(color1[0] * (1 - ratio) + color2[0] * ratio)
                g = int(color1[1] * (1 - ratio) + color2[1] * ratio)
                b = int(color1[2] * (1 - ratio) + color2[2] * ratio)
                draw.line([(0, y), (width, y)], fill=(r, g, b))
        
        elif direction == "Diagonal (↘)":
            for i in range(width + height):
                ratio = i / (width + height)
                r = int(color1[0] * (1 - ratio) + color2[0] * ratio)
                g = int(color1[1] * (1 - ratio) + color2[1] * ratio)
                b = int(color1[2] * (1 - ratio) + color2[2] * ratio)
                draw.line([(0, i), (i, 0)], fill=(r, g, b), width=2)
        
        elif direction == "Diagonal (↙)":
            for i in range(width + height):
                ratio = i / (width + height)
                r = int(color1[0] * (1 - ratio) + color2[0] * ratio)
                g = int(color1[1] * (1 - ratio) + color2[1] * ratio)
                b = int(color1[2] * (1 - ratio) + color2[2] * ratio)
                draw.line([(width, i), (width - i, 0)], fill=(r, g, b), width=2)
        
        elif direction == "Radial (Centro)":
            center_x, center_y = width // 2, height // 2
            max_radius = int(((width/2)**2 + (height/2)**2)**0.5)
            
            for radius in range(max_radius, 0, -1):
                ratio = radius / max_radius
                r = int(color1[0] * (1 - ratio) + color2[0] * ratio)
                g = int(color1[1] * (1 - ratio) + color2[1] * ratio)
                b = int(color1[2] * (1 - ratio) + color2[2] * ratio)
                draw.ellipse(
                    [(center_x - radius, center_y - radius), 
                    (center_x + radius, center_y + radius)],
                    fill=(r, g, b)
                )
        
        return base
    
    # ========================================================================
    # UTILIDADES
    # ========================================================================
    
    def combine_pdfs(self, pdf_paths, output_path):
        """
        Combina múltiples PDFs en uno solo.
        Requiere PyPDF2.
        """
        try:
            import PyPDF2
            
            pdf_writer = PyPDF2.PdfWriter()
            
            for pdf_path in pdf_paths:
                if not os.path.exists(pdf_path):
                    print(f"ADVERTENCIA: {pdf_path} no existe, omitiendo")
                    continue
                
                try:
                    with open(pdf_path, "rb") as f:
                        pdf_reader = PyPDF2.PdfReader(f)
                        for page_num in range(len(pdf_reader.pages)):
                            pdf_writer.add_page(pdf_reader.pages[page_num])
                except Exception as e:
                    print(f"ERROR: No se pudo leer {pdf_path}: {e}")
            
            # Guardar el PDF combinado
            with open(output_path, "wb") as f:
                pdf_writer.write(f)
            
            return True
        
        except ImportError:
            print("ERROR: PyPDF2 no está instalado. No se pueden combinar PDFs.")
            return False
        except Exception as e:
            print(f"ERROR: Falló la combinación de PDFs: {e}")
            return False
        
    # ==================================================================
    # --- FUNCIONES DE CONVERTIR A VIDEO
    # ==================================================================

    def _parse_video_resolution(self, options):
        """Parsea la opción de resolución y devuelve una tupla (width, height)."""
        res_str = options.get("video_resolution", "1920x1080 (1080p)")
        
        if res_str == "Personalizado...":
            try:
                width = int(options.get("video_custom_width", "1920"))
                height = int(options.get("video_custom_height", "1080"))
                return (width, height)
            except ValueError:
                return (1920, 1080) # Fallback
        
        # Parsear (ej. "1920x1080 (1080p)")
        try:
            width_str, height_str = res_str.split(" ")[0].split("x")
            return (int(width_str), int(height_str))
        except Exception:
            return (1920, 1080) # Fallback

    def _create_background_canvas(self, target_size, options):
        """Crea un canvas de fondo con las opciones de 'Cambiar Fondo'."""
        
        # Si el fondo no está habilitado, devolver un canvas negro
        if not options.get("background_enabled", False):
            return Image.new("RGB", target_size, (0, 0, 0))
        
        # Reutilizar la lógica de _apply_background creando un canvas vacío
        # y pasándolo a la función
        empty_canvas = Image.new("RGBA", target_size, (0, 0, 0, 0))
        
        # _apply_background reemplazará la transparencia con el fondo elegido
        # y lo convertirá a RGB
        background_canvas = self._apply_background(empty_canvas, options)
        
        return background_canvas

    def _apply_video_fit_mode(self, fg_image, target_size, fit_mode):
        """
        Escala la imagen (fg_image) según el modo de ajuste para
        encajar en el target_size (ej. 1920x1080).
        """
        from PIL import Image as PILImage
        
        img_w, img_h = fg_image.size
        target_w, target_h = target_size
        
        if fit_mode == "Mantener Tamaño Original":
            # No hacer nada, devolver la imagen tal cual
            return fg_image
        
        elif fit_mode == "Ajustar al Fotograma (Barras)":
            # Modo "Contain" (disminuir)
            ratio = min(target_w / img_w, target_h / img_h)
            
            # Solo escalar si la imagen es más grande que el contenedor
            if ratio < 1.0:
                new_w = int(img_w * ratio)
                new_h = int(img_h * ratio)
                return fg_image.resize((new_w, new_h), PILImage.Resampling.LANCZOS)
            else:
                return fg_image # La imagen ya cabe, no escalar

        elif fit_mode == "Ajustar al Marco (Recortar)":
            # Modo "Cover" (aumentar)
            img_aspect = img_w / img_h
            target_aspect = target_w / target_h
            
            if img_aspect > target_aspect:
                # Imagen más ancha: ajustar a la altura del target
                new_h = target_h
                new_w = int(new_h * img_aspect)
            else:
                # Imagen más alta: ajustar al ancho del target
                new_w = target_w
                new_h = int(new_w / img_aspect)

            # Escalar
            scaled_img = fg_image.resize((new_w, new_h), PILImage.Resampling.LANCZOS)
            
            # Recortar desde el centro
            left = (new_w - target_w) / 2
            top = (new_h - target_h) / 2
            right = (new_w + target_w) / 2
            bottom = (new_h + target_h) / 2
            
            return scaled_img.crop((left, top, right, bottom))
        
        return fg_image # Fallback

    def _composite_images(self, bg_canvas, fg_image):
        """
        Pega la imagen (fg_image) en el centro del lienzo (bg_canvas).
        """
        canvas_w, canvas_h = bg_canvas.size
        img_w, img_h = fg_image.size
        
        # Calcular posición central
        x = (canvas_w - img_w) // 2
        y = (canvas_h - img_h) // 2
        
        # Pegar usando máscara si la imagen tiene transparencia
        if fg_image.mode in ("RGBA", "LA", "PA"):
            bg_canvas.paste(fg_image, (x, y), fg_image)
        else:
            bg_canvas.paste(fg_image, (x, y))
            
        return bg_canvas

    def _build_ffmpeg_video_options(self, options, input_fps):
        """Construye el comando de FFmpeg basado en las opciones de la UI."""
        
        video_format = options.get("format")
        output_fps = options.get("video_fps", "30")
        
        # Opciones base de FFmpeg
        # -r {input_fps} : FPS de entrada (imágenes)
        # -i ... : Input (los frames)
        # -r {output_fps} : FPS de salida (video)
        # -y : Sobrescribir
        
        pre_params = ['-r', str(input_fps)]
        
        # Parámetros post-input
        final_params = ['-r', str(output_fps)]
        
        # Aplicar códec según el formato
        if video_format == ".mp4 (H.264)":
            final_params.extend(['-c:v', 'libx264', '-pix_fmt', 'yuv420p'])
        
        elif video_format == ".mov (ProRes)":
            # Usar un preset de ProRes rápido y de calidad
            final_params.extend(['-c:v', 'prores_ks', '-profile:v', '3', '-pix_fmt', 'yuv422p10le'])
        
        elif video_format == ".webm (VP9)":
            final_params.extend(['-c:v', 'libvpx-vp9', '-b:v', '0', '-crf', '30'])
        
        elif video_format == ".gif (Animado)":
            # Filtro complejo para crear una paleta de GIF de alta calidad
            final_params.extend([
                '-filter_complex', 
                "[0:v] split [a][b];[a] palettegen [p];[b][p] paletteuse"
            ])
        else:
            # Fallback (no debería ocurrir)
            final_params.extend(['-c:v', 'libx264', '-pix_fmt', 'yuv420p'])
            
        return pre_params, final_params

    def create_video_from_images(self, file_data_list, output_path, options, progress_callback, cancellation_event):
        """
        Motor principal para convertir una lista de imágenes a un video.
        ✅ VERSIÓN BLINDADA: Limpieza garantizada y cancelación instantánea.
        """
        if not self.ffmpeg_processor:
            raise Exception("FFmpeg processor no está inicializado.")
        
        import tempfile
        import shutil
        
        temp_frame_dir = None
        try:
            # --- FASE A: ESTANDARIZACIÓN DE FRAMES ---
            
            # 1. Crear directorio temporal para los frames
            temp_frame_dir = tempfile.mkdtemp(prefix="dowp_frames_")
            print(f"INFO: Creando frames temporales en: {temp_frame_dir}")
            
            # 2. Obtener opciones
            target_size = self._parse_video_resolution(options)
            fit_mode = options.get("video_fit_mode", "Ajustar al Fotograma (Barras)")
            total_files = len(file_data_list)
            
            for i, (filepath, page_num) in enumerate(file_data_list):
                
                # ✅ 1. CHEQUEO DE CANCELACIÓN (Dentro del bucle)
                if cancellation_event.is_set():
                    print("DEBUG: Cancelación detectada durante generación de frames.")
                    raise UserCancelledError("Proceso cancelado por el usuario.")
                
                # --- LÓGICA DE PROGRESO ---
                base_progress = (i / total_files) * 100
                step_size = 100 / total_files
                
                current_pct = base_progress + (step_size * 0.1)
                progress_callback("Standardizing", current_pct, f"Procesando: {os.path.basename(filepath)}")
                
                try:
                    # 2.2. Crear el fondo
                    bg_canvas = self._create_background_canvas(target_size, options)
                    
                    # 2.3. Cargar la imagen
                    fg_image = self._load_image(filepath, os.path.splitext(filepath)[1].lower(), 
                                                page_number=page_num, options=options)
                    
                    if not fg_image:
                        continue

                    # --- IA REMBG ---
                    if options.get("rembg_enabled", False):
                        # ✅ 2. CHEQUEO DE CANCELACIÓN (Antes de IA pesada)
                        if cancellation_event.is_set(): raise UserCancelledError("Cancelado")

                        current_pct = base_progress + (step_size * 0.3)
                        model_name = options.get("rembg_model", "u2netp")
                        use_gpu = options.get("rembg_gpu", True) # <--- NUEVO
                        
                        progress_callback("Standardizing", current_pct, f"🤖 IA ({'GPU' if use_gpu else 'CPU'}): {os.path.basename(filepath)}")
                        
                        # Adaptador de callback
                        def temp_callback(p, m):
                            progress_callback("Standardizing", current_pct, m)

                        fg_image = self.remove_background(
                            pil_image=fg_image, 
                            model_filename=model_name, 
                            progress_callback=temp_callback,
                            use_gpu=use_gpu # <--- PASAR OPCIÓN
                        )
                    
                    # ✅ 3. CHEQUEO DE CANCELACIÓN (Después de IA)
                    if cancellation_event.is_set(): raise UserCancelledError("Cancelado")

                    current_pct = base_progress + (step_size * 0.8)
                    progress_callback("Standardizing", current_pct, f"Componiendo: {os.path.basename(filepath)}")
                        
                    # 2.4. Aplicar escalado
                    scaled_fg_image = self._apply_video_fit_mode(fg_image, target_size, fit_mode)
                    
                    # 2.5. Componer
                    final_frame = self._composite_images(bg_canvas, scaled_fg_image)
                    
                    # 2.6. Guardar
                    frame_path = os.path.join(temp_frame_dir, f"frame_{i:06d}.png")
                    final_frame.save(frame_path, "PNG")
                    
                except UserCancelledError:
                    raise # Re-lanzar para salir del bucle inmediatamente
                except Exception as e:
                    print(f"ERROR: Falló frame {filepath}: {e}")
                    continue
            
            # --- FASE B: CODIFICACIÓN DE VIDEO (FFMPEG) ---
            
            # ✅ 4. CHEQUEO DE CANCELACIÓN (Antes de FFmpeg)
            if cancellation_event.is_set(): raise UserCancelledError("Cancelado antes de codificar.")

            print("INFO: Fase A completada. Iniciando FFmpeg...")
            
            try:
                output_fps = int(options.get("video_fps", "30"))
                duration_frames = int(options.get("video_frame_duration", "3"))
                input_fps = output_fps / duration_frames
            except ValueError:
                raise Exception("FPS y Duración deben ser números válidos")
                
            pre_params, final_params = self._build_ffmpeg_video_options(options, input_fps)
            
            input_pattern = os.path.join(temp_frame_dir, "frame_%06d.png")
            
            ffmpeg_options = {
                "input_file": input_pattern,
                "output_file": output_path,
                "duration": total_files / input_fps,
                "ffmpeg_params": final_params,
                "pre_params": pre_params,
                "mode": "Video+Audio"
            }
            
            # 7. Ejecutar FFmpeg (Pasamos el evento de cancelación)
            self.ffmpeg_processor.execute_recode(
                ffmpeg_options,
                lambda p, m: progress_callback("Encoding", p, m),
                cancellation_event # ✅ FFmpegProcessor se encargará de matar el proceso si esto se activa
            )
            
            return output_path
        
        except UserCancelledError as e:
            print(f"DEBUG: Cancelación capturada en create_video_from_images: {e}")
            raise e # Re-lanzar para la UI
            
        finally:
            # ✅ LIMPIEZA GARANTIZADA
            # Este bloque se ejecuta SIEMPRE: si termina bien, si falla, o si se cancela.
            if temp_frame_dir and os.path.exists(temp_frame_dir):
                try:
                    print(f"INFO: Limpiando carpeta temporal de frames: {temp_frame_dir}")
                    shutil.rmtree(temp_frame_dir) # Borra la carpeta y todo su contenido
                except Exception as e:
                    print(f"ADVERTENCIA: No se pudo eliminar carpeta temporal inmediatamente: {e}")
                    # Intento secundario asíncrono (para Windows a veces bloquea archivos un segundo)
                    def retry_delete():
                        import time
                        time.sleep(2)
                        try:
                            if os.path.exists(temp_frame_dir):
                                shutil.rmtree(temp_frame_dir)
                                print("INFO: Limpieza diferida completada.")
                        except: pass
                    threading.Thread(target=retry_delete, daemon=True).start()

    def _save_as_avif(self, img, output_path, options):
        """Guarda como AVIF con opciones avanzadas."""
        # Mantener transparencia si está activado
        if options.get("avif_transparency", True) and img.mode in ("RGBA", "LA", "PA"):
            save_img = img
        else:
            save_img = img.convert("RGB")
        
        save_kwargs = {
            "format": "AVIF",
            "lossless": options.get("avif_lossless", False),
            "speed": options.get("avif_speed", 6)
        }
        
        # Calidad solo si no es lossless
        if not save_kwargs["lossless"]:
            save_kwargs["quality"] = options.get("avif_quality", 80)
        
        save_img.save(output_path, **save_kwargs)

        # Flush para asegurar escritura en disco
        try:
            with open(output_path, 'r+b') as f:
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            pass
    
    def _upscale_image_ai(self, img, options, cancellation_event=None):
        """
        Ejecuta Real-ESRGAN o Waifu2x nativamente.
        Versión blindada contra errores de variables no definidas.
        """
        import subprocess
        import tempfile
        import multiprocessing
        
        # 1. Inicializar variables para evitar errores en 'finally'
        temp_input_path = None
        temp_output_path = None
        
        try:
            engine = options.get("upscale_engine")
            friendly_model = options.get("upscale_model_friendly")
            
            # Obtener el nombre interno del modelo
            if engine == "Real-ESRGAN":
                model_info = REALESRGAN_MODELS.get(friendly_model, {})
                internal_model_name = model_info.get("model", "realesr-animevideov3")
            elif "RealSR" in engine:
                model_info = REALSR_MODELS.get(friendly_model, {})
                internal_model_name = model_info.get("model", "models-DF2K")
            elif "SRMD" in engine: # <-- NUEVO
                model_info = SRMD_MODELS.get(friendly_model, {})
                internal_model_name = model_info.get("model", "models-srmd")
            else:
                model_info = WAIFU2X_MODELS.get(friendly_model, {})
                internal_model_name = model_info.get("model", "models-cunet")

            scale = options.get("upscale_scale", "2")
            tile_size = options.get("upscale_tile", "0") or "0"
            
            # --- MEJORA 1: Tile Size "Upscayl" ---
            # Si es 0 (Auto), NCNN es muy lento. 200 es el estándar de velocidad.
            if tile_size == "0":
                tile_size = "200" 

            denoise = options.get("upscale_denoise", "0")
            use_tta = options.get("upscale_tta", False)
            
            # --- MEJORA 2: Input JPG (Más rápido si no hay transparencia) ---
            ext_temp = ".png"
            if img.mode != "RGBA" and img.mode != "LA":
                ext_temp = ".jpg" # JPG es más rápido para el pipeline
            
            # 2. Crear archivos temporales
            with tempfile.NamedTemporaryFile(suffix=ext_temp, delete=False) as temp_in:
                temp_input_path = temp_in.name
            
            if ext_temp == ".jpg":
                # Guardar como JPG máxima calidad (sin subsampling)
                img.convert("RGB").save(temp_input_path, "JPEG", quality=100, subsampling=0)
            else:
                img.save(temp_input_path, "PNG")

            # El output SIEMPRE será PNG (lo decide el ejecutable)
            temp_output_path = os.path.splitext(temp_input_path)[0] + "_out.png"
            
            # --- MEJORA 3: Calcular Hilos de Tubería (Pipeline) ---
            # Formato NCNN: "load:proc:save"
            # Upscayl usa estrategias agresivas aquí para saturar la GPU.
            cpu_count = multiprocessing.cpu_count()
            if cpu_count >= 8:
                threads_arg = "2:4:2" # CPUs potentes
            elif cpu_count >= 4:
                threads_arg = "1:2:2" # CPUs medias
            else:
                threads_arg = "1:1:1" # CPUs básicas

            models_root = os.path.join(BIN_DIR, "models", "upscaling")
            cmd = []
            
            if engine == "Real-ESRGAN":
                exe_path = os.path.join(models_root, "realesrgan", "realesrgan-ncnn-vulkan.exe")
                
                cmd = [
                    exe_path,
                    "-i", temp_input_path,
                    "-o", temp_output_path,
                    "-n", internal_model_name,
                    "-s", scale,
                    "-t", tile_size,
                    "-f", "png",
                    "-j", threads_arg # <--- NUEVO: Inyectar hilos
                ]
                if use_tta: cmd.append("-x")

            elif "RealSR" in engine:
                exe_path = os.path.join(models_root, "realsr", "realsr-ncnn-vulkan.exe")
                
                full_model_path = os.path.join(models_root, "realsr", internal_model_name)
                
                # SEGURIDAD: RealSR solo soporta escala 4x. 
                # Si la UI envió otro valor por error, lo forzamos a 4 para evitar imagen rota.
                forced_scale = "4"
                
                cmd = [
                    exe_path,
                    "-i", temp_input_path,
                    "-o", temp_output_path,
                    "-m", full_model_path,
                    "-s", forced_scale, # Usamos la escala forzada
                    "-t", tile_size,
                    "-f", "png",
                    "-j", threads_arg
                ]
                if use_tta: cmd.append("-x")

            elif "SRMD" in engine: # <-- NUEVO BLOQUE COMPLETO
                exe_path = os.path.join(models_root, "srmd", "srmd-ncnn-vulkan.exe")
                full_model_path = os.path.join(models_root, "srmd", internal_model_name)
                
                cmd = [
                    exe_path,
                    "-i", temp_input_path,
                    "-o", temp_output_path,
                    "-m", full_model_path,
                    "-n", denoise, # Usa el valor del menú (-1 a 3)
                    "-s", scale,
                    "-t", tile_size,
                    "-f", "png"
                    "-j", threads_arg
                ]
                if use_tta: cmd.append("-x")
                    
            elif engine == "Waifu2x":
                exe_path = os.path.join(models_root, "waifu2x", "waifu2x-ncnn-vulkan.exe")
                full_model_path = os.path.join(models_root, "waifu2x", internal_model_name)
                
                cmd = [
                    exe_path,
                    "-i", temp_input_path,
                    "-o", temp_output_path,
                    "-m", full_model_path,
                    "-n", denoise,
                    "-s", scale,
                    "-t", tile_size,
                    "-f", "png",
                    "-j", threads_arg
                ]
                if use_tta: cmd.append("-x")

            # 3. Ejecutar
            if not os.path.exists(exe_path):
                print(f"ERROR: No se encontró el ejecutable: {exe_path}")
                return img

            print(f"DEBUG: Ejecutando Upscale ({engine}): {' '.join(cmd)}")
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            
            # ✅ CAMBIO: Usar Popen para poder cancelar
            process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                text=True, 
                creationflags=creationflags
            )
            
            # Bucle de espera que vigila el botón de cancelar
            while process.poll() is None:
                if cancellation_event and cancellation_event.is_set():
                    print("DEBUG: Cancelación detectada durante Upscaling. Matando proceso...")
                    process.kill()
                    raise UserCancelledError("Reescalado cancelado por usuario")
                
                # Esperar un poco para no saturar CPU
                import time
                time.sleep(0.1)
            
            # Verificar resultado
            if process.returncode != 0 or not os.path.exists(temp_output_path):
                stderr = process.stderr.read()
                print(f"ERROR Upscaling CLI: {stderr}")
                return img

            # 4. Cargar resultado
            upscaled_img = Image.open(temp_output_path)
            upscaled_img.load()
            
            print(f"INFO: Reescalado finalizado. Tamaño: {upscaled_img.size}")
            return upscaled_img

        except Exception as e:
            print(f"ERROR CRÍTICO en reescalado: {e}")
            return img
            
        finally:
            # Limpieza SEGURA: Verificar que la variable no sea None antes de usarla
            if temp_input_path and os.path.exists(temp_input_path):
                try: os.remove(temp_input_path) 
                except: pass
                
            if temp_output_path and os.path.exists(temp_output_path):
                try: os.remove(temp_output_path) 
                except: pass
