# src/core/utils/subtitle_manager.py
import os
import re
from core.logger.logger_manager import logger

class SubtitleProcessor:
    """
    Clase modular para procesar, limpiar y estandarizar subtítulos.
    """

    @staticmethod
    def vtt_to_srt_timestamp(vtt_timestamp):
        """Convierte timestamps de VTT (00:00:00.000) a SRT (00:00:00,000)."""
        return vtt_timestamp.replace('.', ',')

    @staticmethod
    def strip_vtt_tags(content):
        """Elimina etiquetas de formato específicas de VTT (<c>, <v>, <ruby>, etc.)."""
        # Eliminar etiquetas HTML/VTT generales
        content = re.sub(r'<[^>]+>', '', content)
        # Eliminar etiquetas de estilo/color tipo { ... }
        content = re.sub(r'\{[^}]+\}', '', content)
        return content

    @staticmethod
    def fix_karaoke_overlaps(content):
        """Elimina marcas de tiempo internas (tipo <00:00:00.000>) que causan solapamientos en YouTube."""
        # Detectar y eliminar marcas de tiempo embebidas en el texto
        return re.sub(r'<\d{2}:\d{2}:\d{2}\.\d{3}>', '', content)

    # Caracteres invisibles con los que algunos subtítulos con estilo rellenan cada línea
    # (espacio de ancho cero, unión/no unión, palabra-unión y BOM). En un editor de video
    # aparecen como espacios raros o cuadros.
    _INVISIBLE_CHARS_RE = re.compile('[​‌‍⁠﻿]')

    @staticmethod
    def standardize_to_srt(input_path, output_path=None, is_auto=False):
        """
        Versión fiel a la lógica del DowP viejo:
        Lee línea a línea, limpia etiquetas y reconstruye el SRT desde cero.

        Limpieza de duplicados:
        - Siempre: un bloque con el mismo tiempo y el mismo texto que el anterior. Los
          subtítulos con estilo (contorno, sombra) repiten cada línea una vez por capa, y
          al convertirlos a SRT/VTT YouTube las aplana en bloques idénticos.
        - Solo en subtítulos automáticos (is_auto): las líneas que ya estaban en el
          bloque anterior. Los automáticos de YouTube "ruedan": cada bloque repite la
          línea previa y agrega una nueva. En los manuales esa regla se comía diálogo
          real (un "No." seguido de otro "No.").
        """
        if not os.path.exists(input_path):
            return None

        if output_path is None:
            output_path = os.path.splitext(input_path)[0] + ".srt"

        try:
            # Leer con utf-8-sig para saltar automáticamente el BOM si existe
            with open(input_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
                content = f.read()

            lines = content.split('\n')
            cleaned_lines = []
            
            # 1. Primera pasada: Limpieza de etiquetas y filtrado
            skip_style = False
            for line in lines:
                l = line.strip()
                if not l:
                    if not cleaned_lines or cleaned_lines[-1] != "":
                        cleaned_lines.append("")
                    continue
                
                if l.startswith(('WEBVTT', 'Kind:', 'Language:', 'STYLE')):
                    if l.startswith('STYLE'): skip_style = True
                    continue
                
                if skip_style:
                    if l == "": skip_style = False
                    continue

                if '-->' in l:
                    # Limpiar línea de tiempo (Soportar MM:SS.mmm, HH:MM:SS.mmm, y comas/puntos)
                    # Regex flexible para capturar timestamps de 2 o 3 partes
                    times = re.findall(r'(\d{1,2}:)?(\d{1,2}:\d{2}[\.,]\d{3})', l)
                    if len(times) >= 2:
                        # Reconstruir timestamps normalizados
                        formatted_times = []
                        for t_parts in times[:2]:
                            hours = t_parts[0].replace(':', '') if t_parts[0] else "00"
                            rest = t_parts[1].replace('.', ',')
                            # Asegurar formato HH:MM:SS,mmm
                            if hours.isdigit() and len(hours) == 1: hours = "0" + hours
                            formatted_times.append(f"{hours}:{rest}")
                        
                        cleaned_lines.append(f"{formatted_times[0]} --> {formatted_times[1]}")
                    continue

                # Limpiar texto (Remover etiquetas HTML/VTT y marcas de karaoke <00:00:00.000>)
                l = re.sub(r'<[^>]+>', '', l)
                l = re.sub(r'<\d{1,2}:?\d{0,2}:?\d{2}[\.,]\d{3}>', '', l)
                l = SubtitleProcessor._INVISIBLE_CHARS_RE.sub('', l)
                l = re.sub(r'[ \t]{2,}', ' ', l).strip()
                if l:
                    cleaned_lines.append(l)

            # Verificación de seguridad: Si no se detectaron líneas de tiempo, el archivo podría no ser compatible
            if not any('-->' in line for line in lines):
                logger.warning(f"SubtitleProcessor: No se detectaron bloques de tiempo en {input_path}. Saltando estandarización.")
                return input_path

            # 2. Segunda pasada: Reconstrucción y Deduplicación Inteligente
            final_srt_blocks = []
            counter = 1
            i = 0
            
            # Memoria para deduplicación
            last_text_lines = []
            last_times = ""

            while i < len(cleaned_lines):
                line = cleaned_lines[i]
                if '-->' in line:
                    times = line
                    i += 1
                    block_text_lines = []
                    while i < len(cleaned_lines) and '-->' not in cleaned_lines[i] and cleaned_lines[i] != "":
                        # Limpiar ruido extra de VTT (posicionamientos tipo :top)
                        text_line = re.sub(r'&nbsp;', ' ', cleaned_lines[i])
                        text_line = re.sub(r' align:.*| size:.*| position:.*| line:.*', '', text_line)
                        if text_line.strip():
                            block_text_lines.append(text_line.strip())
                        i += 1
                    
                    if not block_text_lines:
                        continue

                    # Capa repetida de un subtítulo con estilo: mismo tiempo y mismo texto.
                    if times == last_times and block_text_lines == last_text_lines:
                        continue

                    # --- Deduplicación de líneas acumulativas (solo automáticos) ---
                    # Si las líneas de este bloque ya estaban en el anterior, las quitamos
                    if is_auto:
                        filtered_lines = [l for l in block_text_lines if l not in last_text_lines]
                    else:
                        filtered_lines = block_text_lines

                    # Si después de filtrar no queda nada, es un bloque redundante (ej: micro-transiciones)
                    if not filtered_lines:
                        continue

                    text = '\n'.join(filtered_lines).strip()
                    
                    # Bloque SRT estándar con saltos de línea Windows
                    final_srt_blocks.append(f"{counter}\r\n{times}\r\n{text}\r\n")
                    counter += 1
                    
                    # Actualizar memoria (Guardamos las líneas originales para comparar con el siguiente)
                    last_text_lines = block_text_lines
                    last_times = times
                else:
                    i += 1

            # 3. Guardar con saltos de línea Windows y sin BOM
            with open(output_path, 'w', encoding='utf-8', newline='') as f:
                f.write('\r\n'.join(final_srt_blocks))

            if os.path.normpath(input_path) != os.path.normpath(output_path):
                try: os.remove(input_path)
                except: pass

            return output_path

        except Exception as e:
            logger.error(f"SubtitleProcessor: Error en estandarización: {e}")
            return input_path

    @staticmethod
    def _ms_to_ffmpeg_time(ms):
        """Convierte milisegundos a formato HH:MM:SS.mmm para FFmpeg."""
        seconds = int(ms // 1000)
        milliseconds = int(ms % 1000)
        minutes = seconds // 60
        seconds = seconds % 60
        hours = minutes // 60
        minutes = minutes % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"

    @staticmethod
    def cut_subtitle(input_path, start_ms, end_ms, output_path=None):
        """
        Recorta un archivo de subtítulos usando FFmpeg (Formato de tiempo preciso).
        """
        if not os.path.exists(input_path):
            return None

        if output_path is None:
            base, ext = os.path.splitext(input_path)
            output_path = f"{base}_cut{ext}"

        try:
            import subprocess
            from core.setup.ffmpeg_setup import get_ffmpeg_dir
            
            # Detectar ejecutable según plataforma
            ffmpeg_name = "ffmpeg.exe" if os.name == 'nt' else "ffmpeg"
            ffmpeg_exe = os.path.join(get_ffmpeg_dir(), ffmpeg_name)
            
            # Si no está en el directorio bin, intentar en el PATH del sistema
            if not os.path.exists(ffmpeg_exe):
                ffmpeg_exe = ffmpeg_name 

            # CRÍTICO: Usar formato HH:MM:SS.mmm en lugar de segundos decimales
            # FFmpeg es mucho más estable con este formato en subtítulos
            ss_str = SubtitleProcessor._ms_to_ffmpeg_time(start_ms)
            duration_ms = end_ms - start_ms
            t_str = SubtitleProcessor._ms_to_ffmpeg_time(duration_ms)
            import shutil
            import tempfile
            
            # Usar un directorio temporal con nombres "seguros" (ASCII) para evitar problemas de codificación en Windows
            with tempfile.TemporaryDirectory() as tmpdir:
                in_ext = os.path.splitext(input_path)[1]
                out_ext = os.path.splitext(output_path)[1]
                
                tmp_input = os.path.join(tmpdir, f"input{in_ext}")
                tmp_output = os.path.join(tmpdir, f"output{out_ext}")
                
                try:
                    shutil.copy2(input_path, tmp_input)
                    
                    # Mapeo de extensiones a formatos de FFmpeg
                    ext_map = {
                        '.srt': 'srt',
                        '.vtt': 'webvtt',
                        '.ass': 'ass',
                        '.ssa': 'ass',
                    }
                    ff_format = ext_map.get(out_ext.lower(), 'srt')

                    cmd = [
                        ffmpeg_exe, "-y",
                        "-ss", ss_str,
                        "-i", tmp_input,
                        "-t", t_str,
                        "-f", ff_format,
                        tmp_output
                    ]
                    
                    logger.debug(f"SubtitleProcessor: Ejecutando corte seguro en {tmpdir}")
                    
                    creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                    process = subprocess.run(
                        cmd, 
                        capture_output=True,
                        text=True,
                        encoding='utf-8', 
                        creationflags=creationflags
                    )
                    
                    if process.returncode != 0:
                        logger.error(f"SubtitleProcessor: FFmpeg falló (code {process.returncode}). Error: {process.stderr}")
                        return None
                    
                    if os.path.exists(tmp_output):
                        shutil.copy2(tmp_output, output_path)
                        return output_path
                        
                except Exception as e:
                    logger.error(f"SubtitleProcessor: Error durante el procesamiento temporal: {e}")
                    return None
                    
            return None

        except Exception as e:
            logger.error(f"SubtitleProcessor: Error al recortar subtítulo: {e}")
            return None
