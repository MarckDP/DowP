# src/core/utils/paths.py
import os
import sys
import shutil
import platform
from core.logger.logger_manager import logger
from PySide6.QtCore import QCoreApplication


def get_src_dir() -> str:
    """
    Devuelve el equivalente de '<repo_root>/src' tanto en modo fuente como en
    el .exe compilado (--onedir). Es el ancla correcta para cualquier ruta a
    assets, iconos, temas, etc.

    No usar conteos de os.path.dirname(__file__) para esto: el número de
    niveles a subir depende de dónde vive cada módulo bajo src/, y en el .exe
    congelado PyInstaller aplana los paquetes fuera del árbol 'src'
    (_internal/gui/... en vez de _internal/src/gui/...), así que ese cálculo
    da un resultado distinto — y roto — según el módulo.
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, "src")
    # Este archivo vive en <repo_root>/src/core/utils/paths.py
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def get_bin_root_dir() -> str:
    """Carpeta que contiene bin/ (dependencias gestionadas -- ffmpeg/ghostscript/
    deno/yt-dlp/PO provider -- y modelos de IA descargados, que juntos pueden pasar
    los 2 GB).

    Congelado: el perfil de datos LOCAL del usuario (%LOCALAPPDATA%/DowP2 en Windows,
    ~/Library/Application Support/DowP2 en macOS, ~/.local/share/DowP2 en Linux).
    Modo fuente: la raíz del repo, o sea <repo>/bin, para que desarrollar no obligue
    a sacar los binarios del árbol de trabajo.

    Por qué NO sys._MEIPASS (eso es lo de get_src_dir(), y ahí está bien): en un
    --onedir moderno de PyInstaller (desde que separó --contents-directory en la 6.0)
    _MEIPASS apunta a _internal/, el árbol interno reemplazable del bundle. Sirve para
    assets de solo lectura (iconos, temas, .qm) pero no para datos que el usuario
    descarga y espera conservar entre actualizaciones.

    Por qué tampoco junto al ejecutable, que es donde vivía antes -- tres motivos que
    aparecen los tres a la vez al montar el sistema de actualizaciones:

      1. macOS: escribir gigabytes dentro de DowP.app viola la inmutabilidad del
         bundle, y rompe la firma ad-hoc (codesign -s -) que en Apple Silicon es
         obligatoria para que el binario siquiera arranque.
      2. Linux: si el empaquetado pasa a AppImage, dirname(sys.executable) cae en un
         squashfs de solo lectura y toda descarga falla.
      3. Actualizaciones: deja el directorio de instalación totalmente desechable. El
         updater puede reemplazarlo entero sin lista de exclusiones, y el desinstalador
         no tiene que elegir entre dejar 2 GB huérfanos o borrar los modelos del usuario.

    DOWP_BIN_DIR fuerza la ruta: sirve para probar el comportamiento congelado sin
    compilar, y como escape para quien quiera los binarios en otro disco.
    """
    override = os.environ.get("DOWP_BIN_DIR", "").strip()
    if override:
        root = os.path.abspath(os.path.expanduser(override))
        os.makedirs(root, exist_ok=True)
        return root
    if getattr(sys, "frozen", False):
        return get_local_app_data_dir()
    return os.path.dirname(get_src_dir())


def get_bundled_importer_dir() -> str:
    """Carpeta del DowP Importer que viaja DENTRO de la app (unos 500 KB de HTML/JS).

    Es el origen desde el que se copia al instalar el panel en la carpeta de
    extensiones de CEP. Que viaje dentro del bundle es lo que hace que el importer
    no necesite descarga, ni release propio, ni número de versión propio: se
    actualiza solo cuando se actualiza la app.

    Congelado: _internal/importer (lo pone --add-data en build_cross_platform.py).
    Modo fuente: <repo>/importer, que es hermano de app/, no hijo -- por eso sube
    dos niveles desde src/ y no uno como get_bin_root_dir().
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, "importer")
    return os.path.join(os.path.dirname(os.path.dirname(get_src_dir())), "importer")


def get_app_data_dir() -> str:
    r"""
    Retorna la ruta absoluta del directorio AppData del sistema para DowP2.
    - Windows: %APPDATA%/DowP2 (ej. C:\Users\<user>\AppData\Roaming\DowP2)
    - macOS: ~/Library/Application Support/DowP2
    - Linux/Otros: ~/.config/DowP2
    """
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("APPDATA") or os.path.expanduser("~/AppData/Roaming")
    elif system == "Darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    
    app_dir = os.path.join(base, "DowP2")
    os.makedirs(app_dir, exist_ok=True)
    return app_dir

def get_models_dir() -> str:
    """Retorna bin/models (junto a bin/dependences), donde se instalan los modelos de
    IA (rembg, motores de upscaling). A diferencia de las dependencias, los modelos
    NUNCA se descargan solos al abrir la app -- solo cuando el usuario los pide."""
    models_dir = os.path.join(get_bin_root_dir(), "bin", "models")
    os.makedirs(models_dir, exist_ok=True)
    return models_dir

def get_cache_dir() -> str:
    """Retorna el directorio principal de caché persistente de disco (ej. AppData/DowP2/cache)."""
    cache_dir = os.path.join(get_app_data_dir(), "cache")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir

def get_thumbnail_cache_dir() -> str:
    """Retorna el directorio de caché para miniaturas de imágenes y videos."""
    thumb_dir = os.path.join(get_cache_dir(), "thumbnails")
    os.makedirs(thumb_dir, exist_ok=True)
    return thumb_dir

def get_freesound_cache_dir() -> str:
    """Retorna el directorio de caché para previas de audio de Freesound (máximo 10 archivos LRU)."""
    fs_dir = os.path.join(get_cache_dir(), "freesound_previews")
    os.makedirs(fs_dir, exist_ok=True)
    return fs_dir

def get_waveform_cache_dir() -> str:
    """Retorna el directorio de caché para las ondas de audio cacheadas (waveforms)."""
    wf_dir = os.path.join(get_cache_dir(), "waveforms")
    os.makedirs(wf_dir, exist_ok=True)
    return wf_dir

def get_remote_thumbnail_cache_dir() -> str:
    """Retorna el directorio de caché para miniaturas ya renderizadas por un origen web
    (ej. thumburl de Wikimedia) — imágenes chicas descargadas tal cual, sin ffmpeg."""
    rt_dir = os.path.join(get_cache_dir(), "remote_thumbnails")
    os.makedirs(rt_dir, exist_ok=True)
    return rt_dir

def get_search_thumbnail_cache_dir() -> str:
    """Retorna el directorio de caché para las miniaturas chicas de la ventana de búsqueda
    (lupa de Modo Rápido/Proceso Avanzado). Separado a propósito de get_thumbnail_cache_dir():
    estas miniaturas son de baja calidad y nunca deben terminar en una descarga."""
    st_dir = os.path.join(get_cache_dir(), "search_thumbnails")
    os.makedirs(st_dir, exist_ok=True)
    return st_dir

def get_local_app_data_dir() -> str:
    r"""
    Retorna un directorio de datos NO itinerante (no roaming) para lo que pesa: bin/
    (dependencias y modelos de IA) y la caché de proxies de previsualización.
    - Windows: %LOCALAPPDATA%/DowP2 (a diferencia de get_app_data_dir(), que usa
      %APPDATA%, sincronizado por red en perfiles de Windows corporativos)
    - macOS: ~/Library/Application Support/DowP2 (coincide con get_app_data_dir(),
      no existe la distinción roaming/local ahí)
    - Linux: $XDG_DATA_HOME/DowP2, o ~/.local/share/DowP2. A propósito NO coincide
      con get_app_data_dir(), que es ~/.config/DowP2: el estándar XDG reserva
      .config para configuración y .local/share para datos, y aquí caben varios GB.
    """
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/AppData/Local")
    elif system == "Darwin":
        return get_app_data_dir()
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")

    app_dir = os.path.join(base, "DowP2")
    os.makedirs(app_dir, exist_ok=True)
    return app_dir


def get_proxy_cache_dir() -> str:
    """Retorna el directorio de caché para los proxies de previsualización (video de baja
    resolución generado para hacer scrubbing fluido de medios pesados/RAW). A diferencia del
    resto de cachés (thumbnails, waveforms, metadatos), vive en el perfil LOCAL (no roaming)
    porque estos archivos pueden pesar cientos de MB o varios GB por sesión de trabajo."""
    proxy_dir = os.path.join(get_local_app_data_dir(), "cache", "proxies")
    os.makedirs(proxy_dir, exist_ok=True)
    return proxy_dir

def get_updater_state_dir() -> str:
    """Retorna el directorio donde vive el journal del swap en curso
    (journal.json) y los backups de los archivos que reemplaza o borra --
    hermano de get_update_staging_dir() (que solo guarda los objetos ya
    descargados y verificados, listos para aplicar). Separado a proposito:
    staging_dir es "lo que hay que poner", este directorio es "lo que habia
    antes, por si hay que deshacer" -- vidas distintas, se limpian en
    momentos distintos."""
    state_dir = os.path.join(get_local_app_data_dir(), "updater_state")
    os.makedirs(state_dir, exist_ok=True)
    return state_dir

def get_update_staging_dir() -> str:
    """Retorna el directorio donde el cliente de descarga del updater deja los
    objetos ya descomprimidos y verificados, listos para que el helper de swap
    (pieza 3, todavia no implementada) los aplique. Vive en el perfil LOCAL
    (no roaming) por el mismo motivo que get_proxy_cache_dir(): puede pesar
    cientos de MB por actualizacion pendiente."""
    staging_dir = os.path.join(get_local_app_data_dir(), "update_staging")
    os.makedirs(staging_dir, exist_ok=True)
    return staging_dir

def get_subclips_dir() -> str:
    """Retorna el directorio para guardar subclips rápidos de medios cuando no hay editores conectados."""
    from core.utils.config_manager import get_default_subclip_dir
    return get_default_subclip_dir()

def get_sent_thumbnails_dir() -> str:
    """Retorna el directorio para miniaturas guardadas al enviarlas a Editor de Imagen
    desde "Enviar a H.I". Deliberadamente separado de get_thumbnail_cache_dir()/
    get_remote_thumbnail_cache_dir(): esos son cachés con eviction gestionados por
    cache_manager.py que el usuario puede vaciar manualmente desde Ajustes > Caché —
    un archivo ahí podría desaparecer mientras sigue en la cola de Editor de Imagen."""
    d = os.path.join(get_app_data_dir(), "sent_thumbnails")
    os.makedirs(d, exist_ok=True)
    return d

def get_pasted_images_dir() -> str:
    """Retorna el directorio donde se materializan las imágenes pegadas desde el
    portapapeles al Editor de Imagen. Un bitmap del portapapeles no es un archivo, y
    toda la cola del Editor trabaja con rutas en disco, así que hay que escribirlo a
    algún lado.

    Mismo criterio que get_sent_thumbnails_dir() y por el mismo motivo: NO puede ser
    una caché de las que gestiona cache_manager.py, porque el usuario puede vaciarlas
    desde Ajustes > Caché y se llevaría por delante una imagen que sigue en la cola,
    todavía sin convertir."""
    d = os.path.join(get_app_data_dir(), "pasted_images")
    os.makedirs(d, exist_ok=True)
    return d

def get_default_download_dir() -> str:
    """Retorna el directorio predeterminado de descargas del usuario."""
    from core.tabs.advanced_process.output_logic import get_default_download_path
    return get_default_download_path()



def get_user_fonts_dir() -> str:
    """Retorna el directorio de fuentes personalizadas del usuario (%APPDATA%/DowP2/fonts)."""
    fonts_dir = os.path.join(get_app_data_dir(), "fonts")
    os.makedirs(fonts_dir, exist_ok=True)
    return fonts_dir


def get_user_themes_dir() -> str:
    """Retorna el directorio de temas personalizados del usuario (%APPDATA%/DowP2/themes)."""
    themes_dir = os.path.join(get_app_data_dir(), "themes")
    os.makedirs(themes_dir, exist_ok=True)
    return themes_dir


def get_config_path() -> str:
    """Retorna la ruta al archivo de configuración general config.json."""
    return os.path.join(get_app_data_dir(), "config.json")

def get_indexed_media_path() -> str:
    """Retorna la ruta al archivo de base de datos de medios indexados indexed_media.json."""
    return os.path.join(get_app_data_dir(), "indexed_media.json")

def _dir_has_files(path: str) -> bool:
    """True si el árbol contiene al menos un archivo (no solo carpetas vacías)."""
    for _root, _dirs, files in os.walk(path):
        if files:
            return True
    return False


def _merge_tree(src: str, dst: str) -> None:
    """Mueve el contenido de src dentro de dst archivo por archivo, sin pisar lo que
    ya exista en destino, y borra src al terminar.

    Lo que ya está en destino gana a propósito: si hay algo ahí es porque una
    migración anterior se cortó a medias o porque la app ya descargó esa dependencia
    en la ubicación nueva, y en ambos casos la copia nueva es la buena.

    Usa shutil.move (no os.rename) porque este camino es justamente el que se toma
    cuando origen y destino están en volúmenes distintos, donde rename falla."""
    for root, _dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        target_root = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(target_root, exist_ok=True)
        for name in files:
            src_file = os.path.join(root, name)
            dst_file = os.path.join(target_root, name)
            if os.path.exists(dst_file):
                try:
                    os.remove(src_file)
                except OSError:
                    pass
                continue
            shutil.move(src_file, dst_file)
    shutil.rmtree(src, ignore_errors=True)


def migrate_bin_to_local_appdata(status_callback=None) -> bool:
    """Mueve el bin/ que las versiones anteriores dejaban junto al ejecutable al perfil
    de datos local del usuario (ver get_bin_root_dir() para el porqué del cambio).

    Devuelve True solo si movió algo. Es idempotente: si ya se hizo, o si no hay nada
    que mover, sale enseguida y no cuesta nada llamarla en cada arranque.

    TIENE que correr antes de la primera verificación de dependencias. Si no, los
    check_*() de core/setup/ miran la ubicación nueva, la encuentran vacía y la app se
    pone a redescargar los cientos de MB (o los GB de modelos) que el usuario ya tenía.

    En modo fuente no hace nada: ahí bin/ vive en el repo y se queda donde está.
    """
    if not getattr(sys, "frozen", False):
        return False

    try:
        legacy_bin = os.path.join(os.path.dirname(sys.executable), "bin")
        new_bin = os.path.join(get_bin_root_dir(), "bin")

        if os.path.abspath(legacy_bin) == os.path.abspath(new_bin):
            return False
        if not os.path.isdir(legacy_bin):
            return False

        if not _dir_has_files(legacy_bin):
            # Solo carpetas vacías: las crean los get_*_dir() con makedirs al arrancar.
            shutil.rmtree(legacy_bin, ignore_errors=True)
            return False

        logger.info(f"Paths: migrando bin/ de {legacy_bin} -> {new_bin}")
        if status_callback:
            status_callback(QCoreApplication.translate("paths", "Moviendo dependencias a la nueva ubicación..."))

        # Mismo caso que arriba, del otro lado: si el destino solo tiene el esqueleto
        # de carpetas vacías, se borra para poder usar el rename de golpe.
        if os.path.isdir(new_bin) and not _dir_has_files(new_bin):
            shutil.rmtree(new_bin, ignore_errors=True)

        if not os.path.exists(new_bin):
            os.makedirs(os.path.dirname(new_bin), exist_ok=True)
            try:
                os.rename(legacy_bin, new_bin)
                # El caso normal en Windows: instalación en %LOCALAPPDATA%\Programs y
                # datos en %LOCALAPPDATA%, mismo volumen -- son 2 GB movidos al instante.
                logger.info("Paths: bin/ movido con rename (mismo volumen), instantáneo")
                return True
            except OSError as e:
                logger.info(f"Paths: rename no fue posible ({e}); se fusiona archivo por archivo")

        _merge_tree(legacy_bin, new_bin)
        logger.info("Paths: bin/ migrado y origen eliminado")
        return True

    except Exception as e:
        # Nunca debe impedir el arranque: si falla, las dependencias simplemente se
        # vuelven a descargar en la ubicación nueva y el bin/ viejo queda huérfano.
        logger.error(f"Paths: error migrando bin/ al perfil local: {e}", exc_info=True)
        return False


def migrate_legacy_data():
    """Migra archivos de configuración y caché antiguos desde bin/ al nuevo directorio AppData/DowP2 si existen."""
    try:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        legacy_bin = os.path.join(project_root, "bin")
        if not os.path.exists(legacy_bin):
            return

        # 1. Migrar config.json
        legacy_config = os.path.join(legacy_bin, "config.json")
        new_config = get_config_path()
        if os.path.exists(legacy_config) and not os.path.exists(new_config):
            shutil.copy2(legacy_config, new_config)
            logger.info(f"Paths: Migrado {legacy_config} -> {new_config}")

        # 2. Migrar indexed_media.json
        legacy_indexed = os.path.join(legacy_bin, "indexed_media.json")
        new_indexed = get_indexed_media_path()
        if os.path.exists(legacy_indexed) and not os.path.exists(new_indexed):
            shutil.copy2(legacy_indexed, new_indexed)
            logger.info(f"Paths: Migrado {legacy_indexed} -> {new_indexed}")

        # 3. Migrar miniaturas en caché
        legacy_thumb_dir = os.path.join(legacy_bin, "cache", "thumbnails")
        new_thumb_dir = get_thumbnail_cache_dir()
        if os.path.exists(legacy_thumb_dir):
            for file_name in os.listdir(legacy_thumb_dir):
                old_file = os.path.join(legacy_thumb_dir, file_name)
                new_file = os.path.join(new_thumb_dir, file_name)
                if os.path.isfile(old_file) and not os.path.exists(new_file):
                    shutil.copy2(old_file, new_file)
            logger.info(f"Paths: Migradas miniaturas desde {legacy_thumb_dir} -> {new_thumb_dir}")

    except Exception as e:
        logger.error(f"Paths: Error al migrar datos legacy: {e}")

# Ejecutar migración legacy al cargar el módulo por primera vez
migrate_legacy_data()
