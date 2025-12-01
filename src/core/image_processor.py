import os
import io
import re  # Moved to top-level for better performance
from PIL import Image, ImageChops

# Import conversion libraries
try:
    import cairosvg
    CAN_SVG = True
except ImportError:
    CAN_SVG = False
    print("ADVERTENCIA: 'cairosvg' no instalado. No se podrán previsualizar archivos .svg")

try:
    from pdf2image import convert_from_path, pdfinfo_from_path
    CAN_PDF = True
except ImportError:
    CAN_PDF = False
    print("ADVERTENCIA: 'pdf2image' no instalado. No se podrán previsualizar archivos .pdf, .ai, .eps")

# Import format constants
from src.core.constants import (
    IMAGE_RASTER_FORMATS, IMAGE_INPUT_FORMATS, IMAGE_RAW_FORMATS
)

# Convert sets to tuples for .endswith()
RASTER_EXT = tuple(f.lower() for f in IMAGE_RASTER_FORMATS)
VECTOR_EXT = tuple(f.lower() for f in IMAGE_INPUT_FORMATS)

class ImageProcessor:
    def __init__(self, poppler_path=None, inkscape_path=None, ffmpeg_path=None):
        self.poppler_path = poppler_path
        self.inkscape_path = inkscape_path
        self.ffmpeg_path = ffmpeg_path
        
        # ✅ NUEVO: Caché para almacenar el conteo de páginas y evitar bloqueos
        self._page_count_cache = {}
        
        if CAN_PDF and self.poppler_path:
            print(f"INFO: ImageProcessor usará Poppler desde: {self.poppler_path}")
        
        if self.inkscape_path:
            print(f"INFO: ImageProcessor usará Inkscape desde: {self.inkscape_path}")
        else:
            print("ADVERTENCIA: Inkscape no configurado. Archivos vectoriales dependerán del PATH.")

    def _command_exists(self, cmd):
        """Verifica si un comando está disponible en el PATH."""
        import shutil
        return shutil.which(cmd) is not None

    def _fix_svg_attributes(self, svg_path):
        """
        Lee un SVG y corrige atributos width/height inválidos.
        """
        try:
            import tempfile
            
            with open(svg_path, 'r', encoding='utf-8') as f:
                svg_content = f.read()
            
            svg_tag_pattern = r'<svg([^>]*)>'
            match = re.search(svg_tag_pattern, svg_content, re.IGNORECASE)
            
            if not match:
                return None
            
            svg_attributes = match.group(1)
            needs_fix = False
            fixed_attributes = svg_attributes
            
            simple_patterns = [
                (r'width\s*=\s*"px"', 'width="180"'),
                (r'width\s*=\s*""', 'width="180"'),
                (r'width\s*=\s*"\s*px\s*"', 'width="180"'),
                (r'height\s*=\s*"px"', 'height="180"'),
                (r'height\s*=\s*""', 'height="180"'),
                (r'height\s*=\s*"\s*px\s*"', 'height="180"'),
            ]
            
            for pattern, replacement in simple_patterns:
                if re.search(pattern, fixed_attributes, re.IGNORECASE):
                    fixed_attributes = re.sub(pattern, replacement, fixed_attributes, flags=re.IGNORECASE)
                    needs_fix = True
            
            def clean_px_width(match):
                value = match.group(0).split('"')[1]
                value_clean = value.replace('px', '').strip()
                return f'width="{value_clean}"'
            
            def clean_px_height(match):
                value = match.group(0).split('"')[1]
                value_clean = value.replace('px', '').strip()
                return f'height="{value_clean}"'
            
            if re.search(r'width\s*=\s*"\d+px"', fixed_attributes, re.IGNORECASE):
                fixed_attributes = re.sub(r'width\s*=\s*"\d+px"', clean_px_width, fixed_attributes, flags=re.IGNORECASE)
                needs_fix = True
            
            if re.search(r'height\s*=\s*"\d+px"', fixed_attributes, re.IGNORECASE):
                fixed_attributes = re.sub(r'height\s*=\s*"\d+px"', clean_px_height, fixed_attributes, flags=re.IGNORECASE)
                needs_fix = True
            
            if not needs_fix:
                return None
            
            fixed_svg_content = re.sub(
                svg_tag_pattern, 
                f'<svg{fixed_attributes}>', 
                svg_content, 
                count=1, 
                flags=re.IGNORECASE
            )
            
            temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.svg', delete=False, encoding='utf-8')
            temp_file.write(fixed_svg_content)
            temp_file.close()
            
            print(f"DEBUG: SVG corregido guardado en: {temp_file.name}")
            return temp_file.name
            
        except Exception as e:
            print(f"ADVERTENCIA: No se pudo preprocesar el SVG: {e}")
            return None

    def get_document_page_count(self, filepath):
        """
        Obtiene el número de páginas de un documento con caché para evitar bloqueos.
        """
        # ✅ 1. Verificar caché primero (Operación O(1) instantánea)
        if filepath in self._page_count_cache:
            return self._page_count_cache[filepath]

        ext = os.path.splitext(filepath)[1].lower()
        count = 1  # Valor por defecto

        try:
            # --- CASO 1: Archivos PDF (Usar Poppler) ---
            if ext == ".pdf":
                try:
                    info = pdfinfo_from_path(filepath, poppler_path=self.poppler_path)
                    count = int(info.get('Pages', 1))
                except Exception as e:
                    print(f"ADVERTENCIA: Poppler falló leyendo PDF {filepath}: {e}")
                    count = 1

            # --- CASO 2: Archivos EPS, AI, PS (Leer cabecera PostScript) ---
            elif ext in (".eps", ".ai", ".ps"):
                try:
                    with open(filepath, 'rb') as f:
                        header = f.read(4096).decode('latin-1', errors='ignore')
                        
                        # Buscar patrón "%%Pages: (número)"
                        match = re.search(r'%%Pages:\s*(\d+)', header)
                        if match:
                            count = max(1, int(match.group(1)))
                            
                        # Si es un .ai moderno (PDF), intentar Poppler si la cabecera falla o es ambigua
                        if ext == ".ai" and b"%PDF" in header.encode('latin-1'):
                            try:
                                info = pdfinfo_from_path(filepath, poppler_path=self.poppler_path)
                                count = int(info.get('Pages', 1))
                                print(f"DEBUG: Archivo .ai detectado como PDF con {count} página(s)")
                            except Exception as e:
                                print(f"DEBUG: .ai no pudo leerse como PDF: {e}")
                                # Mantener el count que teníamos o 1
                                pass

                except Exception as e:
                    print(f"DEBUG: No se pudo leer cabecera EPS/AI de {filepath}: {e}")
                    count = 1
            
            # ✅ 2. Guardar en caché antes de retornar
            self._page_count_cache[filepath] = count
            return count

        except Exception as e:
            print(f"ERROR CRÍTICO obteniendo páginas: {e}")
            return 1

    def generate_thumbnail(self, filepath, size=(400, 400), page_number=None):
        """
        Genera una miniatura (PIL.Image) para un archivo.
        OPTIMIZADO: Prioriza velocidad sobre calidad.
        """
        original_path = os.environ.get('PATH', '')

        try:
            ext = os.path.splitext(filepath)[1].lower()
            pil_image = None

            # ===== NUEVO: RAW DE CÁMARA (RAWPY) =====
            if ext.upper() in IMAGE_RAW_FORMATS:
                try:
                    import rawpy
                    import numpy as np
                    
                    print(f"DEBUG: Revelando RAW con LibRaw: {filepath}")
                    
                    with rawpy.imread(filepath) as raw:
                        # 🎨 Revelar con configuración óptima para previsualización
                        rgb = raw.postprocess(
                            use_camera_wb=True,      # Balance de blancos de cámara
                            half_size=True,          # 🚀 RÁPIDO: Usar 1/4 de resolución para thumbnails
                            no_auto_bright=False,    # Auto exposición
                            output_bps=8,            # 8 bits (suficiente para preview)
                            output_color=rawpy.ColorSpace.sRGB,  # Espacio de color estándar
                            demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD  # Mejor calidad/velocidad
                        )
                    
                    # Convertir numpy array a PIL Image
                    pil_image = Image.fromarray(rgb)
                    
                    # Aplicar rotación EXIF si existe
                    try:
                        from PIL import ImageOps
                        pil_image = ImageOps.exif_transpose(pil_image)
                    except:
                        pass
                    
                except ImportError:
                    print("⚠️ rawpy no instalado. Ejecuta: pip install rawpy")
                    pil_image = None
                except Exception as e:
                    print(f"❌ ERROR al revelar RAW: {e}")
                    pil_image = None

            # ===== RASTER: Carga directa (RÁPIDO) =====
            elif ext in RASTER_EXT: 
                pil_image = Image.open(filepath)
            
            # ===== SVG: CairoSVG primero (MUY RÁPIDO) =====
            elif ext == ".svg" and CAN_SVG:
                temp_svg = None
                try:
                    png_data = cairosvg.svg2png(url=filepath, output_width=size[0], output_height=size[1])
                    pil_image = Image.open(io.BytesIO(png_data))
                except (ValueError, TypeError) as e:
                    print(f"DEBUG: CairoSVG falló: {e}. Intentando corrección...")
                    temp_svg = self._fix_svg_attributes(filepath)
                    if temp_svg:
                        try:
                            png_data = cairosvg.svg2png(url=temp_svg, output_width=size[0], output_height=size[1])
                            pil_image = Image.open(io.BytesIO(png_data))
                        except Exception:
                            pil_image = self._generate_thumbnail_with_inkscape(temp_svg, size, 1)
                    else:
                        pil_image = self._generate_thumbnail_with_inkscape(filepath, size, 1)
                finally:
                    if temp_svg and os.path.exists(temp_svg):
                        try: os.remove(temp_svg)
                        except: pass

            # ===== PDF/AI: Poppler (Diferenciado) =====
            elif ext in (".pdf", ".ai") and CAN_PDF:
                if page_number is None: page_number = 1
                
                # --- LÓGICA DIFERENCIADA ---
                if ext == ".ai":
                    # MODO DISEÑO: Alta calidad, PNG, Transparencia
                    render_dpi = 300
                    render_fmt = "png"
                    use_transparent = True
                    print(f"DEBUG: Generando miniatura AI (Alta Calidad, Transparente)...")
                else:
                    # MODO DOCUMENTO (PDF): Velocidad, JPEG, Fondo Blanco (Opaco)
                    render_dpi = 110  # 110 DPI es suficiente para miniaturas y muy rápido
                    render_fmt = "jpeg" # JPEG es más rápido de decodificar y fuerza fondo opaco
                    use_transparent = False
                    print(f"DEBUG: Generando miniatura PDF (Velocidad, Fondo Blanco)...")

                try:
                    images = convert_from_path(
                        filepath, 
                        first_page=page_number,
                        last_page=page_number,
                        dpi=render_dpi,
                        fmt=render_fmt, 
                        transparent=use_transparent,
                        poppler_path=self.poppler_path
                    )
                    
                    if images:
                        pil_image = images[0]
                        
                        # Convertir a RGBA para consistencia en la UI (aunque venga como RGB/JPEG)
                        if pil_image.mode != 'RGBA':
                            pil_image = pil_image.convert('RGBA')
                        
                        # Redimensionar
                        pil_image.thumbnail(size, Image.Resampling.LANCZOS)
                        
                except Exception as e:
                    # Fallback genérico si falla la configuración específica
                    print(f"ADVERTENCIA: Error optimizado Poppler ({e}). Reintentando modo seguro...")
                    try:
                        images = convert_from_path(
                            filepath, first_page=page_number, last_page=page_number,
                            poppler_path=self.poppler_path
                        )
                        if images:
                            pil_image = images[0].convert("RGBA")
                            pil_image.thumbnail(size, Image.Resampling.LANCZOS)
                    except:
                         # Último recurso: Inkscape (solo útil para .ai corruptos o pdfs raros)
                         pil_image = self._generate_thumbnail_with_inkscape(filepath, size, page_number)
            
            # ===== EPS/PS: Prioridad Ghostscript (Velocidad) -> Fallback Inkscape =====
            elif ext in (".eps", ".ps"):
                if page_number is None: page_number = 1
                pil_image = None
                
                # 1. Intentar Ghostscript (Pillow) PRIMERO
                # Es mucho más rápido para generar vistas previas.
                try:
                    print(f"DEBUG: Intentando EPS con Ghostscript (Pillow) para velocidad...")
                    pil_image = Image.open(filepath)
                    
                    # ✅ TRUCO 1: Escala x10. 
                    # Ghostscript renderiza vectores. Al pedirle x10, generamos una imagen gigante.
                    # Esto elimina COMPLETAMENTE los dientes de sierra al reducirla después.
                    pil_image.load(scale=5)
                    
                    # Asegurar modo RGB para poder detectar el blanco
                    if pil_image.mode not in ('RGB', 'RGBA'):
                        pil_image = pil_image.convert('RGB')

                    # ✅ TRUCO 2: Auto-Crop (Recorte Inteligente de la Mesa de Trabajo)
                    # Creamos una imagen blanca pura para comparar
                    bg = Image.new(pil_image.mode, pil_image.size, (255, 255, 255))
                    # Calculamos la diferencia entre la imagen y el fondo blanco
                    diff = ImageChops.difference(pil_image, bg)
                    # Obtenemos la caja delimitadora (bounding box) del contenido real (lo que no es blanco)
                    bbox = diff.getbbox()
                    
                    if bbox:
                        # Recortamos la imagen para quedarnos SOLO con el dibujo
                        # Esto elimina los márgenes gigantes y hace que la miniatura se vea grande.
                        pil_image = pil_image.crop(bbox)
                        print(f"DEBUG: EPS recortado al contenido (bbox: {bbox})")

                    # Convertir a RGBA para consistencia
                    pil_image = pil_image.convert('RGBA')
                    
                    # Finalmente reducimos al tamaño de la miniatura (con antialiasing de alta calidad)
                    pil_image.thumbnail(size, Image.Resampling.LANCZOS)
                    print(f"DEBUG: ✅ EPS generado con Ghostscript")
                    
                except Exception as e:
                    print(f"DEBUG: Ghostscript falló ({e}). Probando fallback con Inkscape...")
                    pil_image = None

                # 2. Si Ghostscript falló, usar Inkscape (Más lento, pero máxima compatibilidad)
                if not pil_image:
                     pil_image = self._generate_thumbnail_with_inkscape(filepath, size, page_number)

            # ===== Fallback General (Raster, JP2, BMP, etc) =====
            else:
                try:
                    # Image.open es "lazy" (no lee datos), hay que llamar a load() para detectar corrupción
                    temp_img = Image.open(filepath)
                    temp_img.load() # <--- AQUÍ es donde salta el error de "broken data stream"
                    pil_image = temp_img
                except OSError as e:
                    # Capturar errores de archivos corruptos (ej. el JP2 roto)
                    print(f"ADVERTENCIA: Archivo corrupto o ilegible '{os.path.basename(filepath)}': {e}")
                    return None # Retornar None para que la UI muestre el icono de error ❌
                except Exception as e:
                    # Otros errores
                    print(f"ADVERTENCIA: Formato no soportado o error desconocido en '{filepath}': {e}")
                    return None

            if not pil_image:
                return None

            if pil_image.mode != "RGBA":
                pil_image = pil_image.convert("RGBA")

            pil_image.thumbnail(size, Image.Resampling.LANCZOS)
            return pil_image

        except Exception as e:
            print(f"ERROR: No se pudo generar miniatura para {filepath}: {e}")
            return None
        finally:
            os.environ['PATH'] = original_path

    def _generate_thumbnail_with_inkscape(self, filepath, size, page_number):
        """Helper para generar miniaturas con Inkscape (DPI bajo)."""
        import subprocess
        import tempfile
        
        try:
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_png:
                tmp_png_path = tmp_png.name
            
            cmd = self._build_inkscape_command(
                filepath, tmp_png_path, page_number, dpi=150 
            )
            
            subprocess.run(
                cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=30, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            )
            
            if not os.path.exists(tmp_png_path) or os.path.getsize(tmp_png_path) == 0:
                return None
            
            pil_image = Image.open(tmp_png_path)
            pil_image.load()
            pil_image.thumbnail(size, Image.Resampling.LANCZOS)
            
            if os.path.exists(tmp_png_path):
                try: os.remove(tmp_png_path)
                except: pass
            
            return pil_image
            
        except Exception as e:
            print(f"ERROR Inkscape miniatura: {e}")
            return None
        
    def _build_inkscape_command(self, filepath, output_path, page_number=1, dpi=96, artboard_id=None):
        """Construye el comando de Inkscape."""
        ink_exe = "inkscape.exe" if os.name == "nt" else "inkscape"
        ink_cmd = os.path.join(self.inkscape_path, ink_exe) if self.inkscape_path else ink_exe
        ext = os.path.splitext(filepath)[1].lower()
        
        cmd = [ink_cmd, filepath, f"--export-filename={output_path}", f"--export-dpi={dpi}", "--export-type=png"]
        
        if ext == ".ai":
            # Detección rápida de páginas para comando
            if filepath in self._page_count_cache and self._page_count_cache[filepath] > 1:
                cmd.insert(2, "--pdf-poppler")
                cmd.insert(2, f"--pages={page_number}")
                # Si es multipágina, mantenemos 'page' para respetar la maquetación del documento
                cmd.insert(4, "--export-area-page")
            else:
                # ✅ CAMBIO: Para archivo único, recortar al dibujo (quita el espacio blanco extra)
                cmd.insert(2, "--export-area-drawing")

        elif ext in (".eps", ".ps"):
            # ✅ CAMBIO: EPS siempre al dibujo (BoundingBox)
            cmd.insert(2, "--export-area-drawing")
            
        elif ext == ".svg" and artboard_id:
            cmd.insert(2, f"--export-id={artboard_id}")
            cmd.insert(3, "--export-id-only")
        else:
            # ✅ CAMBIO: SVG genérico también al dibujo para que se vea grande
            cmd.insert(2, "--export-area-drawing")
        
        return cmd
    
    def _get_ai_artboard_ids(self, filepath):
        """
        Obtiene los IDs de las mesas de trabajo de un archivo .ai.
        Busca patrones como 'layer-MCN' o 'pageN'.
        """
        import subprocess
        import re
        
        try:
            ink_exe = "inkscape.exe" if os.name == "nt" else "inkscape"
            if self.inkscape_path:
                ink_cmd = os.path.join(self.inkscape_path, ink_exe)
            else:
                ink_cmd = ink_exe
            
            # Obtener lista de todos los objetos
            cmd = [ink_cmd, filepath, "--query-all"]
            
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            )
            
            # ✅ Decodificar con UTF-8 e ignorar errores
            stdout = result.stdout.decode('utf-8', errors='ignore')
            stderr = result.stderr.decode('utf-8', errors='ignore')
            
            if result.returncode != 0:
                print(f"DEBUG: --query-all falló (código {result.returncode})")
                if stderr:
                    print(f"DEBUG: STDERR: {stderr[:200]}")
                return None
            
            # Parsear la salida para encontrar artboards
            artboard_ids = []
            
            for line in stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                
                # Formato: ID,X,Y,WIDTH,HEIGHT
                parts = line.split(',')
                if len(parts) >= 5:
                    obj_id = parts[0]
                    
                    # ✅ PATRÓN 1: "layer-MCN" (donde N es el número)
                    match = re.match(r'^layer-MC(\d+)$', obj_id)
                    if match:
                        page_num = int(match.group(1))
                        artboard_ids.append((page_num, obj_id))
                        continue
                    
                    # ✅ PATRÓN 2: "pageN" (fallback)
                    match = re.match(r'^page(\d+)$', obj_id)
                    if match:
                        page_num = int(match.group(1))
                        artboard_ids.append((page_num, obj_id))
            
            if artboard_ids:
                # Ordenar por número de página
                artboard_ids.sort(key=lambda x: x[0])
                # Retornar solo los IDs (sin el número)
                sorted_ids = [obj_id for _, obj_id in artboard_ids]
                print(f"DEBUG: ✅ {len(sorted_ids)} artboards encontrados: {sorted_ids[:5]}...")
                return sorted_ids
            
            print(f"DEBUG: No se encontraron artboards con patrón 'layer-MCN' o 'pageN'")
            
            # ✅ FALLBACK: Buscar grupos principales grandes (estrategia de área)
            print(f"DEBUG: Intentando detectar por tamaño de objetos...")
            objects = []
            
            for line in stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                
                parts = line.split(',')
                if len(parts) >= 5:
                    obj_id = parts[0]
                    try:
                        width = float(parts[3])
                        height = float(parts[4])
                        area = width * height
                        
                        # Filtrar objetos pequeños (probablemente no son artboards)
                        if area > 100:  # Umbral bajo para capturar todo
                            objects.append((obj_id, area, width, height))
                    except (ValueError, IndexError):
                        continue
            
            if not objects:
                print(f"DEBUG: No se encontraron objetos válidos en --query-all")
                return None
            
            # Ordenar por área (descendente)
            objects.sort(key=lambda x: x[1], reverse=True)
            
            # Imprimir los 10 objetos más grandes para diagnóstico
            print(f"DEBUG: Top 10 objetos más grandes:")
            for i, (obj_id, area, w, h) in enumerate(objects[:10]):
                print(f"  {i+1}. {obj_id}: {w:.1f}x{h:.1f} (área: {area:.1f})")
            
            # Estrategia: Los artboards suelen tener tamaños similares
            # Agrupar objetos con tamaños similares (±20% de variación)
            if objects:
                # Usar el objeto más grande como referencia
                ref_area = objects[0][1]
                threshold = ref_area * 0.2  # ±20%
                
                candidate_artboards = []
                for obj_id, area, w, h in objects:
                    if abs(area - ref_area) <= threshold:
                        candidate_artboards.append(obj_id)
                
                if candidate_artboards:
                    print(f"DEBUG: ✅ {len(candidate_artboards)} candidatos detectados por área similar")
                    return candidate_artboards[:40]  # Limitar a 40 (el número que reportó Poppler)
            
            print(f"DEBUG: No se pudieron detectar artboards automáticamente")
            return None
            
        except Exception as e:
            print(f"DEBUG: Error obteniendo artboards: {e}")
            import traceback
            traceback.print_exc()
            return None