# src/core/tabs/single_process/fragment_logic.py
import re
from PySide6.QtCore import QCoreApplication

class FragmentManager:
    """
    Clase encargada de la lógica pura de fragmentos: tiempos, validaciones y estados.
    Separada de la GUI para mayor mantenibilidad.
    """
    
    @staticmethod
    def format_time(ms):
        """Convierte milisegundos a formato HH:MM:SS.mmm."""
        ms = int(ms)
        s, ms_r = divmod(ms, 1000)
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}.{ms_r:03d}"

    @staticmethod
    def parse_time(text):
        """Convierte un string de tiempo (HH:MM:SS:mmm o variantes) a milisegundos."""
        if not text:
            return None
        
        # Normalizar separadores
        text = text.strip().replace(",", ":").replace(".", ":")
        parts = text.split(":")
        
        try:
            if len(parts) == 1: # Segundos
                return int(parts[0]) * 1000
            elif len(parts) == 2: # MM:SS
                return (int(parts[0]) * 60 + int(parts[1])) * 1000
            elif len(parts) == 3: # HH:MM:SS
                return (int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])) * 1000
            elif len(parts) >= 4: # HH:MM:SS:mmm
                h, m, s, ms = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
                return ((h * 3600 + m * 60 + s) * 1000) + ms
        except (ValueError, IndexError):
            pass
        return None

    @staticmethod
    def validate_range(start_ms, end_ms, duration_ms=None):
        """Valida que el rango de inicio sea menor que el de fin y esté dentro de la duración."""
        if start_ms is None or end_ms is None:
            return False, QCoreApplication.translate("FragmentManager", "Valores de tiempo inválidos.")
        
        if start_ms >= end_ms:
            return False, QCoreApplication.translate("FragmentManager", "El tiempo de inicio debe ser menor al fin.")
        
        if duration_ms is not None and end_ms > duration_ms:
            # Tolerancia pequeña para errores de redondeo o duración de stream
            if end_ms > duration_ms + 1000:
                return False, QCoreApplication.translate("FragmentManager", "El tiempo de fin excede la duración del video.")
        
        return True, ""

    @staticmethod
    def get_ytdlp_section_string(start_ms, end_ms):
        """Genera el string compatible con yt-dlp: '*start-end'."""
        start_fmt = FragmentManager.format_time(start_ms).replace(":", "\\:").replace(".", "\\.")
        # Nota: yt-dlp espera formatos de tiempo específicos, usualmente HH:MM:SS.ms
        # pero la sintaxis *start-end acepta formatos de tiempo estándar.
        
        # Para compatibilidad extrema con yt-dlp:
        s_sec = start_ms / 1000.0
        e_sec = end_ms / 1000.0
        return f"*{s_sec}-{e_sec}"

class FragmentState:
    """Gestiona el estado actual de los cortes y opciones de descarga."""
    PRECISE = "precise"
    DOWNLOAD_THEN_CUT = "download_cut"
    KEEP_FULL = "keep_full"

    def __init__(self):
        self.fragments = [] # Lista de tuplas (start_ms, end_ms, suffix)
        self.mode = None
        self.is_modified = False

    def add_fragment(self, start_ms, end_ms):
        self.fragments.append((start_ms, end_ms))
        self.is_modified = True

    def remove_fragment(self, index):
        if 0 <= index < len(self.fragments):
            self.fragments.pop(index)
            self.is_modified = True

    def clear(self):
        self.fragments = []
        self.is_modified = True

    def set_mode(self, mode):
        if mode != self.mode:
            self.mode = mode
            self.is_modified = True
