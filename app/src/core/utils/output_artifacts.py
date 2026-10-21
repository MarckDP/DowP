# src/core/utils/output_artifacts.py
"""
Reúne TODO lo que quedó en disco como resultado de una descarga (o de una descarga +
recodificación) para poder arrastrarlo a otra aplicación como si el usuario hubiera
entrado a la carpeta de salida y hubiera seleccionado esos archivos a mano — necesario
para editores que no exponen ninguna API de importación (CapCut, Filmora), donde el
drag-and-drop nativo del SO es la única vía (ver gui/widgets/native_file_drag.py).

Idea central: NO se intenta predecir qué archivos "debería" haber producido cada
combinación de casillas (conservar originales, conservar completo, miniatura,
subtítulos, fragmentos...). Se parte de las rutas EXACTAS que el proceso registró y se
descarta todo lo que ya no existe. Como los caminos que borran archivos son justamente
los que implementan esas casillas (file_conflict_manager.commit_backup cuando NO se
conservan los originales, DownloaderMaster._handle_local_cuts cuando el modo no es
KEEP_FULL, EmbedThumbnail cuando no se guarda la miniatura), el filtro de existencia
refleja automáticamente lo que el usuario eligió conservar, sin duplicar esa lógica aquí.

Los sidecars (miniatura, subtítulos, cortes de subtítulo) llegan por el manifiesto del
descargador (ver DownloaderMaster._note_artifact). Antes se deducían barriendo la
carpeta por nombre base, en los dos sentidos (descendientes y ancestros), y eso se
llevaba archivos de OTRAS descargas con nombre emparentado: el arrastre de un fragmento
del Modo Rápido incluía la descarga completa del Proceso Avanzado del mismo video, y al
revés. Ningún archivo entra por parecerse a otro.
"""
import os
import re
import unicodedata

from core.utils.file_conflict_manager import BACKUP_SUFFIX

# Caracteres que ningún sistema de archivos admite en un nombre. La almohadilla NO
# está: '#' es perfectamente legal en Windows, macOS y Linux, y quitarla solo servía
# para que el nombre predicho dejara de coincidir con el que escribe yt-dlp.
_FORBIDDEN_FILENAME_CHARS = re.compile(r'[\\/:\*\?"<>|]')

# Límites de nombre: 150 caracteres para que siga siendo legible, y 220 bytes UTF-8
# porque el límite real de la mayoría de sistemas de archivos se cuenta en bytes, no
# en caracteres (un título en japonés gasta 3 bytes por carácter).
_MAX_FILENAME_CHARS = 150
_MAX_FILENAME_BYTES = 220


def sanitize_filename(filename, fallback="video_descargado"):
    """Convierte un título en un nombre de archivo. ÚNICA fuente de verdad.

    Tiene que ser una sola función porque el nombre se calcula DOS veces por descarga,
    en dos sitios distintos, y ambos resultados deben ser idénticos:

      1. downloader_master lo mete en la plantilla -o de yt-dlp -> nombre REAL en disco.
      2. queue_manager lo usa para predecir job.final_filepath -> con lo que después se
         envía al editor y se abre la carpeta contenedora.

    Cuando divergían, el archivo se descargaba bien pero la ruta predicha apuntaba a
    algo que no existía: no se enviaba nada al editor y el botón de abrir la carpeta no
    hacía nada. Las dos versiones anteriores discrepaban en seis cosas —la almohadilla,
    la normalización NFC, los caracteres de control, los espacios múltiples, el punto
    final y los límites de longitud—, así que fallaban muchos más títulos que los que
    llevan '#'.
    """
    original = str(filename or "")

    # NFC: 'é' puede venir como un carácter o como 'e' + acento combinante. Sin
    # normalizar, dos títulos que se ven iguales producen nombres distintos.
    name = unicodedata.normalize('NFC', original)
    # Categoría 'C' = caracteres de control y de formato.
    name = ''.join(ch for ch in name if unicodedata.category(ch)[0] != 'C')
    name = _FORBIDDEN_FILENAME_CHARS.sub('', name)
    name = re.sub(r'\s+', ' ', name).strip()
    # Windows no admite nombres terminados en punto o espacio.
    name = name.rstrip('. ')

    if len(name) > _MAX_FILENAME_CHARS:
        name = name[:_MAX_FILENAME_CHARS].rstrip('. ')
    if len(name.encode('utf-8')) > _MAX_FILENAME_BYTES:
        name = name.encode('utf-8')[:_MAX_FILENAME_BYTES].decode('utf-8', errors='ignore').rstrip('. ')

    return name or fallback

# Acompañantes de un medio: nunca son "el archivo descargado" salvo que no haya otro
# (modo "solo miniatura"). Ver QuickDownloadController._find_actual_downloaded_file.
SIDECAR_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".webp", ".gif",
    ".srt", ".vtt", ".ass", ".ssa", ".ttml", ".lrc",
    ".srv1", ".srv2", ".srv3", ".json3",
)

# Restos de trabajo de yt-dlp/ffmpeg que pueden convivir con los archivos buenos en la
# carpeta de salida y que jamás deben viajar en un arrastre.
_TEMP_SUFFIXES = (
    ".part", ".ytdl", ".temp", ".tmp", ".cut.temp", ".unstd", BACKUP_SUFFIX,
)


def _is_temp_artifact(name: str) -> bool:
    low = name.lower()
    if low.endswith(_TEMP_SUFFIXES):
        return True
    # Fragmentos intermedios de yt-dlp: "video.mp4.part-Frag12", "video.f137.mp4.part".
    return ".part-" in low or low.endswith(".part")


_INTERMEDIATE_STREAM = re.compile(r"^(.*)\.f[0-9A-Za-z_-]+$")


def collect_output_artifacts(known_paths) -> list:
    """
    Devuelve la lista ordenada y sin repetidos de los archivos EXISTENTES de un proceso.

    known_paths: rutas que el proceso registró con certeza (el medio bajado, cada
        fragmento, el completo conservado, miniatura y subtítulos del manifiesto, la
        salida recodificada). Las que ya no existan se descartan en silencio: es el caso
        normal de un original borrado por no marcar "mantener medios originales", de una
        miniatura que se borró tras incrustarla, o de los intermedios pre-fusión que yt-dlp
        reporta por el hook 'finished' y luego elimina.

    Un stream intermedio ('Título.f137.mp4') que siga en disco junto a su fusión
    ('Título.mp4', también registrada) se omite: queda porque los subtítulos fuerzan
    keepvideo (ver DownloaderMaster._prepare_opts), pero no es un resultado.
    """
    ordered, seen = [], set()
    existing = []
    for path in known_paths or []:
        if not path:
            continue
        try:
            if not os.path.isfile(path):
                continue
        except OSError:
            continue
        if _is_temp_artifact(os.path.basename(path)):
            continue
        absolute = os.path.abspath(path)
        key = os.path.normcase(absolute)
        if key in seen:
            continue
        seen.add(key)
        existing.append(absolute)

    stems = {os.path.normcase(os.path.splitext(p)[0]) for p in existing}
    for path in existing:
        match = _INTERMEDIATE_STREAM.match(os.path.splitext(path)[0])
        if match and os.path.normcase(match.group(1)) in stems:
            continue
        ordered.append(path)
    return ordered


def find_actual_downloaded_file(filepath, fallback_to_dir=False):
    """
    Resuelve la ruta REAL de un archivo descargado a partir de la pista que dejó yt-dlp,
    que a menudo ya no existe: el hook de progreso reporta el stream intermedio
    ('Título.f137.mp4') o un temporal ('Título.mp4.part'), y ffmpeg los borra al fusionar.

    A igualdad de nombre base, el medio SIEMPRE gana sobre su sidecar: con "guardar
    miniatura" o subtítulos activados, 'Título.jpg' y 'Título.mp4' comparten nombre y el
    orden alfabético de os.scandir devolvía la imagen — con lo que una recodificación
    post-descarga intentaba recodificar el .jpg y el envío al editor mandaba la miniatura
    como si fuera el video. El sidecar solo se devuelve si no hay nada más (modo "solo
    miniatura", donde la imagen SÍ es el archivo descargado).

    fallback_to_dir=True devuelve la carpeta contenedora cuando no se encontró nada, para
    quien la usa solo para abrir el explorador; el resto recibe None.
    """
    if not filepath:
        return None
    if os.path.exists(filepath):
        return filepath

    parent_dir = os.path.dirname(filepath)
    if not parent_dir or not os.path.exists(parent_dir):
        return None

    base_name = os.path.splitext(os.path.basename(filepath))[0]
    for temp_ext in ('.temp', '.ytdl', '.part'):
        if base_name.endswith(temp_ext):
            base_name = base_name[: -len(temp_ext)]
    import re
    base_name = re.sub(r'\.f[a-zA-Z0-9-_]+$', '', base_name)

    # rango 0: mismo nombre y no es sidecar | 1: mismo nombre, sidecar
    #        2: cuelga del nombre, no sidecar | 3: cuelga del nombre, sidecar
    candidates = {}
    try:
        for entry in os.scandir(parent_dir):
            if not entry.is_file():
                continue
            entry_base, entry_ext = os.path.splitext(entry.name)
            if _is_temp_artifact(entry.name):
                continue
            if entry_base == base_name:
                rank = 0 if entry_ext.lower() not in SIDECAR_EXTENSIONS else 1
            elif entry_base.startswith(base_name):
                rank = 2 if entry_ext.lower() not in SIDECAR_EXTENSIONS else 3
            else:
                continue
            candidates.setdefault(rank, entry.path)
    except OSError:
        pass

    for rank in (0, 1, 2, 3):
        if rank in candidates:
            return candidates[rank]

    return parent_dir if fallback_to_dir else None


class OutputArtifactTracker:
    """
    Acumula las rutas que un proceso fue produciendo, para poder arrastrar su resultado
    completo cuando termine. Es la misma pareja de listas que lleva cada fila de Modo
    Rápido (ver gui/tabs/quick_mode/download_row.py), extraída aquí porque en Proceso
    Avanzado hace falta en dos sitios más: colgada de cada Job de la cola (modo LOTES) y
    en el controlador de la descarga directa (modo SOLO).

    Nunca se filtra por existencia al registrar: eso se resuelve recién en collect(),
    porque entre medio el pipeline puede borrar el original (no marcar "mantener medios
    originales") o el usuario puede mover los archivos.
    """

    def __init__(self):
        self._known = []
        self._stems = []

    def add(self, paths, is_stem_source=True):
        """is_stem_source=True para lo DESCARGADO (el historial lo usa para saber cuál es
        el medio principal, ver download_history.resolve_disk_files); False para lo
        procesado (recodificado) y los sidecars del manifiesto."""
        if isinstance(paths, str):
            paths = [paths]
        for path in paths or []:
            if not path:
                continue
            # Varios resolutores caen a la CARPETA contenedora cuando no encuentran el
            # archivo (ver find_actual_downloaded_file con fallback_to_dir): una carpeta
            # no es un resultado que se pueda arrastrar.
            try:
                if os.path.isdir(path):
                    continue
            except OSError:
                continue
            if path not in self._known:
                self._known.append(path)
            if is_stem_source and path not in self._stems:
                self._stems.append(path)

    def stems(self):
        """Rutas de lo descargado (no procesado ni sidecars): de ahí sale el medio
        principal en el historial."""
        return list(self._stems)

    def known(self):
        """Todas las rutas registradas (el historial de descargas las copia tal cual, ver
        core/utils/download_history.py::record_outputs)."""
        return list(self._known)

    def collect(self):
        return collect_output_artifacts(self._known)

    def clear(self):
        self._known = []
        self._stems = []

    def __bool__(self):
        return bool(self._known)
