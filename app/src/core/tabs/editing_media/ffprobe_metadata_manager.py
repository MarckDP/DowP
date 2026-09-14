# src/core/tabs/editing_media/ffprobe_metadata_manager.py
import os
import json
import datetime
import subprocess
from PySide6.QtCore import QObject, Signal, QRunnable, QThreadPool, QMutex, QMutexLocker, QTimer, QCoreApplication
from core.logger.logger_manager import logger
from core.utils.paths import get_cache_dir
from core.setup.ffmpeg_setup import get_ffprobe_path, get_ffmpeg_dir, get_platform_info, check_ffmpeg
from core.tabs.editing_media.editing_media_logic import RAW_EXTS

CACHE_FILE = os.path.join(get_cache_dir(), "metadata_cache.json")

# Version del esquema de metadatos que devuelve _parse_ffprobe_json/_get_empty_meta.
# Subir este numero cada vez que se agregue/cambie un campo en ese dict - si no, una
# entrada de cache vieja (guardada con un esquema anterior, ej. sin "audio_streams")
# se sigue devolviendo tal cual por mtime/size aunque le falten campos nuevos, y la UI
# que los consume nunca los ve hasta que el usuario borra la cache a mano.
CACHE_SCHEMA_VERSION = 3

class FFprobeTask(QRunnable):
    """Tarea asíncrona para ejecutar ffprobe en un archivo multimedia."""

    def __init__(self, file_path: str, media_type: str):
        super().__init__()
        self.file_path = file_path
        self.media_type = media_type

    def run(self):
        try:
            meta = FFprobeMetadataManager.get_instance()._extract_ffprobe_json(self.file_path, self.media_type)
            if meta:
                FFprobeMetadataManager.get_instance()._on_task_completed(self.file_path, meta)
        except Exception as e:
            logger.error(f"FFprobeTask: Error procesando {self.file_path}: {e}")

class _CacheSaveTask(QRunnable):
    """Escribe un snapshot de la caché a disco en un hilo de QThreadPool -- nunca en
    el de UI. Recibe una copia (dict) en vez de la referencia viva de
    FFprobeMetadataManager.cache justo para no necesitar el mutex durante el I/O
    (ver _flush_cache)."""

    def __init__(self, cache_snapshot: dict):
        super().__init__()
        self._snapshot = cache_snapshot

    def run(self):
        try:
            os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
            with open(CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(self._snapshot, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"FFprobeMetadataManager: Error al guardar caché: {e}")


class FFprobeMetadataManager(QObject):
    metadata_ready = Signal(str, dict)  # file_path, metadata_dict
    # Señal interna -- ver _on_task_completed/_flush_cache. Se emite desde CUALQUIER
    # hilo (los workers de self.pool), pero como el receptor (_save_timer.start) vive
    # en el hilo dueño de este QObject, Qt la entrega en cola automáticamente ahí --
    # es la forma segura de reiniciar un QTimer desde otro hilo (QTimer.start() no es
    # thread-safe llamado directo).
    _save_requested = Signal()

    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = FFprobeMetadataManager()
        return cls._instance

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mutex = QMutex()
        self.cache: dict[str, dict] = {}
        self.pending_tasks: set[str] = set()
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(4)

        # Guardado de caché DEBOUNCED y fuera del hilo de UI -- antes, cada ffprobe
        # individual que terminaba reescribía el archivo de caché COMPLETO a disco
        # (self._save_cache(), ver git blame) mientras tenía tomado self.mutex. Con
        # una importación grande (miles de archivos nuevos, ej. 4000 videos) eso es
        # I/O que crece cuadráticamente (se reescribe TODA la caché en cada una de
        # las 4000 finalizaciones) más el hilo de UI bloqueándose cada vez que
        # get_metadata_instant() (llamado en loop por _on_queue_changed,
        # video_tools_view.py) pisaba el mismo mutex mientras un hilo de fondo
        # estaba en medio de esa escritura -- eso era el cuelgue de varios segundos
        # (o directamente sin reaccionar) reportado con 4000 videos. Ahora: cada
        # archivo terminado solo actualiza el dict en memoria (rápido, ver
        # _on_task_completed) y pide un guardado; el guardado real se dispara una
        # sola vez tras 1.5s de inactividad (se reinicia en cada pedido nuevo) y
        # corre en un QRunnable aparte (_CacheSaveTask), nunca en el hilo de UI ni
        # reteniendo el mutex durante el I/O.
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(1500)
        self._save_timer.timeout.connect(self._flush_cache)
        self._save_requested.connect(self._save_timer.start)

        self._load_cache()

    def _flush_cache(self):
        with QMutexLocker(self.mutex):
            snapshot = dict(self.cache)
        self.pool.start(_CacheSaveTask(snapshot))

    def _load_cache(self):
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                    self.cache = json.load(f)
            except Exception as e:
                logger.error(f"FFprobeMetadataManager: Error al cargar caché: {e}")
                self.cache = {}

    def clear_cache(self) -> int:
        """Limpia la caché de metadatos en memoria y disco, retornando la cantidad de entradas eliminadas."""
        with QMutexLocker(self.mutex):
            count = len(self.cache)
            self.cache.clear()
            if os.path.exists(CACHE_FILE):
                try:
                    os.remove(CACHE_FILE)
                except Exception as e:
                    logger.error(f"FFprobeMetadataManager: Error al eliminar archivo de caché: {e}")
            logger.info(f"FFprobeMetadataManager: Se eliminaron {count} entradas de metadatos en caché.")
            return count

    def get_metadata_instant(self, path: str, tipo: str) -> dict:
        """
        Retorna metadatos de forma INSTANTÁNEA (0ms):
        1. Si está en caché de disco y coincide el mtime/size, retorna los metadatos completos.
        2. Si no está en caché, retorna metadatos básicos de os.stat y encola ffprobe en segundo plano.
        """
        if not os.path.exists(path):
            return self._get_empty_meta()

        try:
            stat_info = os.stat(path)
            file_mtime = stat_info.st_mtime
            file_size = stat_info.st_size
        except Exception:
            return self._get_empty_meta()

        # Verificar si la caché en memoria/disco es válida
        with QMutexLocker(self.mutex):
            if path in self.cache:
                entry = self.cache[path]
                if (
                    entry.get("mtime") == file_mtime
                    and entry.get("size") == file_size
                    and entry.get("schema") == CACHE_SCHEMA_VERSION
                ):
                    return entry.get("data", {})

        # No está en caché -> Crear metadatos básicos rápidos (Tier 1)
        meta = self._get_basic_stat_meta(path, stat_info, tipo)

        # Encolar la extracción enriquecida con ffprobe en segundo plano (Tier 2/3)
        self.request_async_extraction(path, tipo, priority=True)

        return meta

    def request_async_extraction(self, path: str, tipo: str, priority=False):
        """Encola una tarea de ffprobe en segundo plano si no está en proceso."""
        with QMutexLocker(self.mutex):
            if path in self.pending_tasks:
                return
            self.pending_tasks.add(path)

        task = FFprobeTask(path, tipo)
        if priority:
            self.pool.start(task, priority=1)
        else:
            self.pool.start(task)

    def _on_task_completed(self, path: str, meta: dict):
        if not os.path.exists(path):
            with QMutexLocker(self.mutex):
                self.pending_tasks.discard(path)
            return

        try:
            stat_info = os.stat(path)
            entry = {
                "mtime": stat_info.st_mtime,
                "size": stat_info.st_size,
                "schema": CACHE_SCHEMA_VERSION,
                "data": meta
            }
            with QMutexLocker(self.mutex):
                self.cache[path] = entry
                self.pending_tasks.discard(path)
            self._save_requested.emit()
        except Exception as e:
            logger.error(f"FFprobeMetadataManager: Error al guardar entrada de caché: {e}")

        # Emitir señal a la UI para actualizar suavemente
        self.metadata_ready.emit(path, meta)

    def _get_empty_meta(self) -> dict:
        return {
            "creado": "-", "modificado": "-", "duración": "-", "resolución": "-",
            "video_codec": "-", "video_profile": "-", "fps": "-", "aspecto": "-",
            "bitrate_video": "-", "color": "-", "audio_codec": "-", "samplerate": "-",
            "canales": "-", "bitrate_audio": "-",
            # Lista completa de pistas de audio (a diferencia de los campos escalares de
            # arriba, que solo reflejan la PRIMERA pista, por compatibilidad con el resto
            # de la UI). Cada entrada: {"codec", "channels", "channel_layout", "language"}.
            # "language" puede ser None si el stream no trae tag de idioma.
            "audio_streams": [],
        }

    def _get_basic_stat_meta(self, path: str, stat_info: os.stat_result, tipo: str) -> dict:
        meta = self._get_empty_meta()
        try:
            mtime = datetime.datetime.fromtimestamp(stat_info.st_mtime)
            meta["modificado"] = mtime.strftime("%Y-%m-%d %H:%M:%S")
            ctime = datetime.datetime.fromtimestamp(stat_info.st_ctime)
            meta["creado"] = ctime.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass

        if tipo == "imagen":
            ext = os.path.splitext(path)[1].lower()
            if ext in (".svg", ".svgz"):
                try:
                    from PySide6.QtSvg import QSvgRenderer
                    renderer = QSvgRenderer(path)
                    if renderer.isValid():
                        sz = renderer.defaultSize()
                        if sz.isValid() and sz.width() > 0 and sz.height() > 0:
                            meta["resolución"] = f"{int(sz.width())}x{int(sz.height())}"
                        meta["video_codec"] = "SVG"
                except Exception:
                    pass
            elif ext in (".pdf", ".ai"):
                try:
                    from PySide6.QtPdf import QPdfDocument
                    doc = QPdfDocument()
                    doc.load(path)
                    pages = doc.pageCount()
                    if pages > 0:
                        sz = doc.pagePointSize(0)
                        pag_txt = (QCoreApplication.translate("ffprobe_metadata_manager", "{0} pág").format(pages)
                                   if pages == 1 else
                                   QCoreApplication.translate("ffprobe_metadata_manager", "{0} págs").format(pages))
                        if sz.isValid() and sz.width() > 0 and sz.height() > 0:
                            meta["resolución"] = f"{int(sz.width())}x{int(sz.height())} ({pag_txt})"
                        else:
                            meta["resolución"] = pag_txt
                        meta["video_codec"] = "PDF" if ext == ".pdf" else "AI"
                except Exception:
                    pass
            elif ext in (".eps", ".ps"):
                try:
                    import re
                    meta["video_codec"] = "EPS" if ext == ".eps" else "PS"
                    with open(path, "rb") as f:
                        header_sample = f.read(4096).decode("latin-1", errors="ignore")
                        match = re.search(r"%%(?:HiRes)?BoundingBox:\s*([-\d\.]+)\s+([-\d\.]+)\s+([-\d\.]+)\s+([-\d\.]+)", header_sample)
                        if match:
                            x1, y1, x2, y2 = map(float, match.groups())
                            w = int(round(abs(x2 - x1)))
                            h = int(round(abs(y2 - y1)))
                            if w > 0 and h > 0:
                                meta["resolución"] = f"{w}x{h}"
                except Exception:
                    pass

            elif ext == ".psd":
                meta["video_codec"] = "PSD"
                try:
                    from PIL import Image
                    with Image.open(path) as im:
                        meta["resolución"] = f"{im.width}x{im.height}"
                except Exception:
                    pass

            elif ext in RAW_EXTS:
                meta["video_codec"] = "RAW"
                try:
                    import rawpy
                    with rawpy.imread(path) as raw:
                        # .sizes da las dimensiones leyendo solo la cabecera -- sin
                        # decodificar el thumbnail embebido ni revelar el RAW.
                        meta["resolución"] = f"{raw.sizes.width}x{raw.sizes.height}"
                except Exception:
                    pass

            if not meta.get("resolución") or meta.get("resolución") == "-":
                from PySide6.QtGui import QImageReader
                try:
                    reader = QImageReader(path)
                    if reader.canRead():
                        sz = reader.size()
                        if sz.width() > 0 and sz.height() > 0:
                            meta["resolución"] = f"{sz.width()}x{sz.height()}"
                            fmt = reader.format().data().decode('utf-8', errors='ignore').upper()
                            if fmt:
                                meta["video_codec"] = fmt
                except Exception:
                    pass

            if not meta.get("resolución") or meta.get("resolución") == "-":
                # Qt no pudo (formato sin plugin nativo -- JPEG2000, DDS, APNG, HEIC/HEIF
                # una vez registrado pillow-heif). Pillow sí los sabe leer.
                try:
                    from PIL import Image
                    with Image.open(path) as im:
                        meta["resolución"] = f"{im.width}x{im.height}"
                        if im.format:
                            meta["video_codec"] = im.format
                except Exception:
                    pass
        return meta

    def _extract_ffprobe_json(self, path: str, tipo: str) -> dict:
        meta = self._get_basic_stat_meta(path, os.stat(path), tipo)

        if tipo not in ("video", "audio"):
            return meta

        probe_exe = get_ffprobe_path()
        if probe_exe:
            cmd = [
                probe_exe,
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                path
            ]
            try:
                startupinfo = None
                if os.name == 'nt':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

                res = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='ignore',
                    startupinfo=startupinfo,
                    timeout=8
                )

                if res.returncode == 0 and res.stdout:
                    data = json.loads(res.stdout)
                    self._parse_ffprobe_json(data, meta)
                    return meta
            except Exception as e:
                logger.error(f"FFprobeMetadataManager: Error al ejecutar ffprobe en {path}: {e}")

        # Fallback a ffmpeg -i si ffprobe falla o no está instalado
        self._fallback_ffmpeg_i(path, meta)
        return meta

    def _parse_ffprobe_json(self, data: dict, meta: dict):
        fmt = data.get("format", {})
        streams = data.get("streams", [])

        # Duración
        try:
            duration_sec = float(fmt.get("duration", 0))
            if duration_sec > 0:
                total_sec = int(duration_sec)
                hrs = total_sec // 3600
                mins = (total_sec % 3600) // 60
                secs = total_sec % 60
                if hrs > 0:
                    meta["duración"] = f"{hrs:02d}:{mins:02d}:{secs:02d}"
                else:
                    meta["duración"] = f"{mins:02d}:{secs:02d}"
        except Exception:
            pass

        # Bitrate general del formato
        try:
            bit_rate = int(fmt.get("bit_rate", 0))
        except Exception:
            bit_rate = 0

        for st in streams:
            codec_type = st.get("codec_type")
            disposition = st.get("disposition", {}) or {}
            is_attached_pic = bool(disposition.get("attached_pic", 0))
            if codec_type == "video" and not is_attached_pic and meta["video_codec"] == "-":
                width = st.get("width")
                height = st.get("height")
                if width and height:
                    meta["resolución"] = f"{width}x{height}"

                codec_name = st.get("codec_name", "").upper()
                meta["video_codec"] = codec_name

                profile = st.get("profile")
                if profile and profile != "unknown":
                    meta["video_profile"] = str(profile)

                # Parsear FPS
                r_fps = st.get("r_frame_rate", "")
                if "/" in r_fps:
                    try:
                        num, den = map(float, r_fps.split("/"))
                        if den > 0:
                            fps_val = num / den
                            meta["fps"] = f"{fps_val:.2f} fps" if fps_val % 1 != 0 else f"{int(fps_val)} fps"
                    except Exception:
                        pass
                elif r_fps:
                    meta["fps"] = f"{r_fps} fps"

                # Aspect Ratio
                dar = st.get("display_aspect_ratio")
                if dar and dar != "N/A":
                    meta["aspecto"] = f"DAR {dar}"
                else:
                    sar = st.get("sample_aspect_ratio")
                    if sar and sar != "N/A":
                        meta["aspecto"] = f"SAR {sar}"

                # Color / Pixel Format
                pix_fmt = st.get("pix_fmt")
                if pix_fmt:
                    meta["color"] = str(pix_fmt)

                # Bitrate
                v_bitrate = 0
                try:
                    v_bitrate = int(st.get("bit_rate", 0)) or bit_rate
                except Exception:
                    v_bitrate = bit_rate

                if v_bitrate > 0:
                    kbps = v_bitrate / 1000.0
                    if kbps >= 1000:
                        meta["bitrate_video"] = f"{kbps/1000.0:.2f} Mb/s"
                    else:
                        meta["bitrate_video"] = f"{int(kbps)} kb/s"

            elif codec_type == "audio":
                codec_name = st.get("codec_name", "").upper()
                channels = st.get("channels")
                channel_layout = st.get("channel_layout")
                language = (st.get("tags") or {}).get("language")

                # Registrar SIEMPRE esta pista en la lista completa, sin importar si ya
                # se registraron los campos escalares de abajo (esos solo reflejan la
                # primera pista, ver _get_empty_meta). El índice en esta lista es el
                # índice RELATIVO de audio (0, 1, 2...), que es lo que espera el
                # specifier "0:a:N" de ffmpeg al armar el -map en queue_manager.py.
                meta["audio_streams"].append({
                    "codec": codec_name,
                    "channels": channels,
                    "channel_layout": channel_layout,
                    "language": language,
                })

                if meta["audio_codec"] != "-":
                    continue

                meta["audio_codec"] = codec_name

                sample_rate = st.get("sample_rate")
                if sample_rate:
                    try:
                        sr = int(sample_rate)
                        if sr >= 1000:
                            meta["samplerate"] = f"{sr/1000.0:.1f} kHz"
                        else:
                            meta["samplerate"] = f"{sr} Hz"
                    except Exception:
                        meta["samplerate"] = str(sample_rate)

                if channels:
                    layout_str = f" ({channel_layout})" if channel_layout else ""
                    meta["canales"] = f"{channels}{layout_str}"

                try:
                    a_bitrate = int(st.get("bit_rate", 0))
                    if a_bitrate > 0:
                        meta["bitrate_audio"] = f"{int(a_bitrate / 1000.0)} kb/s"
                except Exception:
                    pass

    def _fallback_ffmpeg_i(self, path: str, meta: dict):
        if not check_ffmpeg():
            return
        info = get_platform_info()
        ffmpeg_exe = os.path.join(get_ffmpeg_dir(), info["binary_name"])
        cmd = [ffmpeg_exe, "-hide_banner", "-i", path]
        try:
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo, text=True, encoding='utf-8', errors='ignore')
            _, stderr = proc.communicate(timeout=5)
            import re
            dur_m = re.search(r"Duration:\s*(\d{2}:\d{2}:\d{2}(?:\.\d+)?)", stderr)
            if dur_m:
                meta["duración"] = dur_m.group(1).split('.')[0]
            video_m = re.search(r"Stream #\d+:\d+.*Video:\s*([^\n]+)", stderr)
            if video_m:
                v_info = video_m.group(1)
                parts = [p.strip() for p in v_info.split(',')]
                meta["video_codec"] = re.sub(r"\s*\([^)]*\)", "", parts[0]).upper()
                for p in parts:
                    res = re.search(r"\b(\d{2,5})x(\d{2,5})\b", p)
                    if res: meta["resolución"] = res.group(0)
                    if "fps" in p: meta["fps"] = p
                    if "kb/s" in p: meta["bitrate_video"] = p
            audio_m = re.search(r"Stream #\d+:\d+.*Audio:\s*([^\n]+)", stderr)
            if audio_m:
                a_info = audio_m.group(1)
                parts = [p.strip() for p in a_info.split(',')]
                meta["audio_codec"] = re.sub(r"\s*\([^)]*\)", "", parts[0]).upper()
                if len(parts) > 1: meta["samplerate"] = parts[1]
                if len(parts) > 2: meta["canales"] = parts[2]
        except Exception:
            pass
