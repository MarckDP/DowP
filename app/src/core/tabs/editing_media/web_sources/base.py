# src/core/tabs/editing_media/web_sources/base.py

class WebSourceProvider:
    """Interfaz común para un origen de medios web (Freesound, Wikimedia Commons, ...).

    Cada implementación traduce su API externa a los diccionarios de ítem que ya
    consume MediaTableModel/_update_media_list (claves como 'nombre', 'ruta', 'tipo',
    'es_remoto', 'license', 'library', 'description', etc.), para que el árbol, el
    modelo y los hilos de búsqueda/descarga sean agnósticos al origen.
    """

    id = ""
    display_name = ""
    requires_auth = False
    # Subconjunto de {"imagen", "audio", "video"} que este origen puede devolver.
    supported_media_types = {"audio"}
    # Lista de (bucket_key, label) para el combo de licencia. Vacía = el origen no ofrece
    # filtro de licencia (el combo se oculta). bucket_key es lo que normalize_license() debe
    # devolver para ese ítem.
    license_filter_options: list = []

    # Contrato opcional para orígenes con auth por API key simple (a diferencia de Freesound,
    # que usa OAuth2 con su propia página de login) -- ver
    # gui/tabs/editing_media/api_key_login_widget.py::ApiKeyLoginWidget, que reconfigura una
    # única instancia genérica con estos dos campos más set_api_key()/validate_api_key().
    api_key_url = ""
    api_key_instructions = ""

    def is_authenticated(self) -> bool:
        """True si no requiere sesión, o si ya hay una sesión activa."""
        return True

    def set_api_key(self, key: str):
        """Persiste la API key ya validada. Solo relevante si requires_auth y el origen usa
        el flujo genérico de API key (ver api_key_url arriba)."""
        raise NotImplementedError

    def validate_api_key(self, key: str) -> tuple:
        """Verifica la key contra la API real (una llamada mínima). Devuelve (ok, mensaje_error)."""
        raise NotImplementedError

    def normalize_license(self, raw_license: str) -> str:
        """Agrupa la licencia cruda del ítem en uno de los bucket_key de license_filter_options."""
        return ""

    def search(self, query: str, page: int = 1, **filters) -> dict:
        """Devuelve {'results': [item_normalizado, ...]}."""
        raise NotImplementedError

    def download(self, item_data: dict, dest_dir: str, fallback_name: str, progress_callback=None) -> str:
        """Descarga el archivo original/en alta calidad y devuelve la ruta final en disco."""
        raise NotImplementedError
