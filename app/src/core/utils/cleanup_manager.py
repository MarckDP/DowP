# src/core/utils/cleanup_manager.py
import os
import time
import gc
from core.logger.logger_manager import logger

class DownloadCancelledError(Exception):
    """Excepción lanzada cuando el usuario cancela una descarga."""
    pass

class CleanupManager:
    """
    Gestor centralizado para la limpieza de residuos de descargas y procesos de FFmpeg.
    """

    @staticmethod
    def safe_remove(path: str, max_retries: int = 3) -> bool:
        """
        Borra un archivo con reintentos ante bloqueos temporales (ej. un proceso que
        recién cerró el handle, o un antivirus escaneando el archivo). Reutilizado tanto
        por la limpieza de temporales de yt-dlp como por la confirmación de backups
        (ver file_conflict_manager.commit_backup). Devuelve True si se borró (o ya no
        existía), False si falló tras agotar los reintentos.
        """
        if not os.path.exists(path):
            return True
        for attempt in range(max_retries):
            try:
                gc.collect()  # Liberar handles si es posible
                if attempt > 0:
                    time.sleep(0.5 * (2 ** attempt))
                os.remove(path)
                return True
            except (PermissionError, OSError) as e:
                if attempt == max_retries - 1:
                    logger.warning(f"CleanupManager: No se pudo eliminar (bloqueado) '{path}': {e}")
        return False
