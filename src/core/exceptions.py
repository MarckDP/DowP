class UserCancelledError(Exception):
    """Excepción lanzada cuando el usuario cancela una operación."""
    pass

class LocalRecodeFailedError(Exception):
    """Excepción para un fallo específico en la recodificación local."""
    def __init__(self, message, temp_filepath=None):
        super().__init__(message)
        self.temp_filepath = temp_filepath

class PlaylistDownloadError(Exception):
    """Excepción lanzada cuando yt-dlp falla al descargar un ítem de playlist."""
    pass