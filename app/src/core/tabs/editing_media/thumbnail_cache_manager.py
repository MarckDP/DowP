# src/core/tabs/editing_media/thumbnail_cache_manager.py
import os
import hashlib
import subprocess
import re
from PySide6.QtCore import QObject, Signal, QRunnable, Qt
from PySide6.QtGui import QImage, QPixmap, QIcon, QImageReader, QPainter, QColor
from core.logger.logger_manager import logger
from core.setup.ffmpeg_setup import get_ffmpeg_dir, get_platform_info, check_ffmpeg
from core.utils.paths import get_thumbnail_cache_dir
from core.tabs.editing_media.editing_media_logic import RAW_EXTS
from core.utils.media_task_pools import (
    get_background_pool,
    get_interactive_pool,
    PRIORITY_BACKGROUND,
    PRIORITY_INTERACTIVE,
)

CACHE_DIR = get_thumbnail_cache_dir()

def make_square_thumbnail_pixmap(src_pixmap: QPixmap, size=256) -> QPixmap:
    """Garantiza que la miniatura sea un lienzo cuadrado uniforme de 256x256 px centrado."""
    if src_pixmap.isNull():
        return src_pixmap
    if src_pixmap.width() == size and src_pixmap.height() == size:
        return src_pixmap

    out = QPixmap(size, size)
    out.fill(QColor("#1c1c1e"))

    scaled = src_pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.Antialiasing)
    x = (size - scaled.width()) // 2
    y = (size - scaled.height()) // 2
    painter.drawPixmap(x, y, scaled)
    painter.end()

    return out

class ThumbnailWorkerSignals(QObject):
    """Señales para el trabajador de miniaturas en segundo plano."""
    finished = Signal(str, str)  # (file_path, thumbnail_path)
    failed = Signal(str)        # (file_path)

class ThumbnailRunnable(QRunnable):
    """Tarea ejecutable en QThreadPool para generar miniaturas sin congelar la interfaz."""
    def __init__(self, file_path: str, media_type: str, manager: "ThumbnailCacheManager"):
        super().__init__()
        self.file_path = file_path
        self.media_type = media_type
        self.manager = manager
        self.signals = ThumbnailWorkerSignals()

    def run(self):
        try:
            thumb_path = self.manager._create_thumbnail(self.file_path, self.media_type)
            if thumb_path and os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
                self.signals.finished.emit(self.file_path, thumb_path)
            else:
                self.signals.failed.emit(self.file_path)
        except Exception as e:
            logger.error(f"ThumbnailRunnable: Error procesando {self.file_path}: {e}")
            self.signals.failed.emit(self.file_path)
        finally:
            self.manager._task_finished(self.file_path, self)


class PreviewWorkerSignals(QObject):
    """Señales para el trabajador de preview de alta resolución en segundo plano."""
    finished = Signal(str, str)  # (file_path, preview_path)
    failed = Signal(str)         # (file_path)

class PreviewRunnable(QRunnable):
    """Genera, con Pillow, una versión cacheada de resolución media para medios que
    Qt no puede decodificar directo (superan su límite de asignación de memoria —
    ver QImageReader.allocationLimit(), 256MB por defecto). Solo se dispara para el
    archivo que el usuario tiene abierto en el visor ahora mismo, nunca en generación
    masiva de fondo, así que siempre corre en el pool interactivo."""
    def __init__(self, file_path: str, manager: "ThumbnailCacheManager"):
        super().__init__()
        self.file_path = file_path
        self.manager = manager
        self.signals = PreviewWorkerSignals()

    def run(self):
        try:
            preview_path = self.manager._create_preview(self.file_path)
            if preview_path and os.path.exists(preview_path) and os.path.getsize(preview_path) > 0:
                self.signals.finished.emit(self.file_path, preview_path)
            else:
                self.signals.failed.emit(self.file_path)
        except Exception as e:
            logger.error(f"PreviewRunnable: Error procesando {self.file_path}: {e}")
            self.signals.failed.emit(self.file_path)
        finally:
            self.manager._preview_task_finished(self.file_path, self)

def _make_multi_state_icon(pix: QPixmap) -> QIcon:
    if pix.isNull():
        return QIcon()
    icon = QIcon()
    icon.addPixmap(pix, QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(pix, QIcon.Mode.Normal, QIcon.State.On)
    icon.addPixmap(pix, QIcon.Mode.Selected, QIcon.State.Off)
    icon.addPixmap(pix, QIcon.Mode.Selected, QIcon.State.On)
    icon.addPixmap(pix, QIcon.Mode.Active, QIcon.State.Off)
    icon.addPixmap(pix, QIcon.Mode.Active, QIcon.State.On)
    return icon

class ThumbnailCacheManager(QObject):
    """Gestor de caché de miniaturas en disco y memoria (RAM) con cola optimizada."""
    thumbnail_loaded = Signal(str, str)  # (file_path, thumbnail_path)
    preview_loaded = Signal(str, str)    # (file_path, preview_path)

    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = ThumbnailCacheManager()
        return cls._instance

    def __init__(self, parent=None):
        super().__init__(parent)
        os.makedirs(CACHE_DIR, exist_ok=True)

        # Caché en RAM para acceso instantáneo (0ms I/O)
        self._qicon_cache: dict[str, QIcon] = {}
        self._hash_cache: dict[str, str] = {}
        # Separados a propósito (no un solo set compartido): si una miniatura ya está
        # pendiente en el pool de fondo y luego el usuario selecciona ese mismo archivo,
        # la solicitud interactiva NO debe descartarse solo porque "ya hay algo pendiente"
        # — si lo hiciera, quedaría atada a la cola de fondo, que además puede estar
        # pausada por completo mientras hay reproducción activa (ver set_background_throttled).
        self._pending_background = set()
        self._pending_interactive = set()
        self._failed_files = set()
        # Referencias fuertes a los workers en curso, igual que WaveformCacheManager: sin
        # esto nada en el lado Python los mantiene vivos una vez que request_thumbnail()
        # retorna, y también hace falta tener el objeto worker a mano para poder cancelarlo
        # con QThreadPool.tryTake() en purge_stale_background() si todavía no arrancó.
        self._active_workers: dict[str, set] = {}

        # Estado equivalente para el segundo nivel de caché (preview de resolución
        # media para medios pesados) -- separado del de miniaturas porque vive en su
        # propio archivo en disco y solo se pide de forma interactiva.
        self._pending_preview = set()
        self._active_preview_workers: dict[str, set] = {}

    def _get_hash_key(self, file_path: str) -> str:
        """Genera un hash SHA256 único y lo mantiene en memoria para evitar os.stat repetidos."""
        if file_path in self._hash_cache:
            return self._hash_cache[file_path]

        try:
            stat = os.stat(file_path)
            raw = f"{os.path.abspath(file_path)}_{stat.st_mtime}_{stat.st_size}_v3"
        except Exception:
            raw = f"{os.path.abspath(file_path)}_v3"
        hash_val = hashlib.sha256(raw.encode('utf-8')).hexdigest()
        self._hash_cache[file_path] = hash_val
        return hash_val

    def get_cached_qicon(self, file_path: str, size: int = 256) -> QIcon | None:
        """Obtiene directamente el QIcon desde la memoria RAM (super rápido y 100% cuadrado).
        `size` permite pedir una miniatura pequeña (p.ej. en modo lista) sin inflar la altura
        de la fila con el ícono de 256px pensado para la cuadrícula."""
        cache_key = (file_path, size)
        if cache_key in self._qicon_cache:
            return self._qicon_cache[cache_key]

        thumb_path = self.get_cached_thumbnail_path(file_path)
        if thumb_path:
            pix = QPixmap(thumb_path)
            if not pix.isNull():
                sq_pix = make_square_thumbnail_pixmap(pix, size)
                icon = _make_multi_state_icon(sq_pix)
                self._qicon_cache[cache_key] = icon
                return icon

        return None

    def get_cached_thumbnail_path(self, file_path: str) -> str | None:
        """Devuelve la ruta de la miniatura en disco si ya existe y es válida."""
        hash_key = self._get_hash_key(file_path)
        target_path = os.path.join(CACHE_DIR, f"{hash_key}.jpg")
        if os.path.exists(target_path) and os.path.getsize(target_path) > 0:
            return target_path
        return None

    def request_thumbnail(self, file_path: str, media_type: str, size: int = 256, interactive: bool = False):
        """Solicita una miniatura de forma no bloqueante.

        `interactive=True` indica que el usuario está esperando este resultado ahora
        mismo (p.ej. la carátula del audio recién seleccionado): se ejecuta en un pool
        dedicado, separado del de generación masiva por scroll, para que nunca quede
        esperando detrás de una cola de tareas de fondo."""
        cache_key = (file_path, size)
        if cache_key in self._qicon_cache:
            return

        if file_path in self._failed_files:
            return

        # Deduplicar dentro del MISMO carril: una solicitud interactiva repetida no debe
        # lanzar un segundo worker interactivo, pero SÍ debe proceder aunque ya haya una
        # tarea de fondo pendiente para ese archivo (ver comentario en __init__).
        pending_set = self._pending_interactive if interactive else self._pending_background
        if file_path in pending_set:
            return

        cached_path = self.get_cached_thumbnail_path(file_path)
        if cached_path:
            pix = QPixmap(cached_path)
            if not pix.isNull():
                sq_pix = make_square_thumbnail_pixmap(pix, size)
                icon = _make_multi_state_icon(sq_pix)
            else:
                icon = _make_multi_state_icon(QPixmap(cached_path))
            self._qicon_cache[cache_key] = icon
            self.thumbnail_loaded.emit(file_path, cached_path)
            return

        pending_set.add(file_path)
        worker = ThumbnailRunnable(file_path, media_type, self)
        # Set en vez de asignación directa: con los carriles separados, un mismo file_path
        # puede tener a la vez un worker de fondo y uno interactivo corriendo en paralelo
        # (duplicado inofensivo, ver comentario en __init__); una asignación simple perdería
        # la referencia del primero en cuanto arrancara el segundo.
        self._active_workers.setdefault(file_path, set()).add(worker)
        worker.signals.finished.connect(self._on_worker_finished)
        worker.signals.failed.connect(self._on_worker_failed)
        if interactive:
            get_interactive_pool().start(worker, PRIORITY_INTERACTIVE)
        else:
            get_background_pool().start(worker, PRIORITY_BACKGROUND)

    def _on_worker_finished(self, file_path: str, thumb_path: str):
        pix = QPixmap(thumb_path)
        if not pix.isNull():
            sq_pix = make_square_thumbnail_pixmap(pix, 256)
            icon = _make_multi_state_icon(sq_pix)
        else:
            icon = _make_multi_state_icon(QPixmap(thumb_path))
        self._qicon_cache[(file_path, 256)] = icon
        self.thumbnail_loaded.emit(file_path, thumb_path)

    def _on_worker_failed(self, file_path: str):
        self._failed_files.add(file_path)

    def _task_finished(self, file_path: str, worker=None):
        # Se limpia de ambos carriles sin condicional: discard() no falla si no está
        # presente, y como mucho un archivo pudo quedar pendiente en los dos a la vez
        # (una tarea de fondo y otra interactiva corriendo en paralelo para el mismo
        # archivo — duplicado inofensivo, ver comentario en __init__).
        self._pending_background.discard(file_path)
        self._pending_interactive.discard(file_path)
        workers = self._active_workers.get(file_path)
        if workers is not None:
            workers.discard(worker)
            if not workers:
                self._active_workers.pop(file_path, None)

    def get_cached_preview_path(self, file_path: str) -> str | None:
        """Devuelve la ruta del preview cacheado en disco si ya existe y es válido."""
        hash_key = self._get_hash_key(file_path)
        target_path = os.path.join(CACHE_DIR, f"{hash_key}_preview.png")
        if os.path.exists(target_path) and os.path.getsize(target_path) > 0:
            return target_path
        return None

    def request_preview(self, file_path: str):
        """Pide, sin bloquear, el preview cacheado de un archivo demasiado pesado
        como para que Qt lo decodifique directo (ver PreviewRunnable). Si ya existe
        en disco, emite `preview_loaded` de inmediato; si no, lo genera en el pool
        interactivo y emite la señal cuando esté listo. Uso exclusivamente
        interactivo (el archivo abierto ahora mismo en el visor) — nunca se llama
        para generación masiva de fondo."""
        cached = self.get_cached_preview_path(file_path)
        if cached:
            self.preview_loaded.emit(file_path, cached)
            return
        if file_path in self._pending_preview:
            return
        self._pending_preview.add(file_path)
        worker = PreviewRunnable(file_path, self)
        self._active_preview_workers.setdefault(file_path, set()).add(worker)
        worker.signals.finished.connect(self._on_preview_worker_finished)
        worker.signals.failed.connect(self._on_preview_worker_failed)
        get_interactive_pool().start(worker, PRIORITY_INTERACTIVE)

    def _on_preview_worker_finished(self, file_path: str, preview_path: str):
        self.preview_loaded.emit(file_path, preview_path)

    def _on_preview_worker_failed(self, file_path: str):
        pass  # Sin caché de "fallidos" propia: request_preview() se puede reintentar sin costo (isNull de Qt ya filtró antes de llamar).

    def _preview_task_finished(self, file_path: str, worker=None):
        self._pending_preview.discard(file_path)
        workers = self._active_preview_workers.get(file_path)
        if workers is not None:
            workers.discard(worker)
            if not workers:
                self._active_preview_workers.pop(file_path, None)

    def _create_preview(self, file_path: str) -> str | None:
        """Decodifica `file_path` completo con Pillow (sin el límite de asignación
        artificial de Qt) y guarda una versión reducida (hasta 1600px de lado largo,
        PNG para conservar transparencia) en la caché de disco. Se paga este costo
        una sola vez por archivo — nunca se toca el original."""
        target_path = os.path.join(CACHE_DIR, f"{self._get_hash_key(file_path)}_preview.png")
        try:
            from PIL import Image
            with Image.open(file_path) as im:
                # No-op en formatos que no sean JPEG; para JPEG deja que libjpeg
                # decodifique directo en baja resolución en vez de a tamaño completo.
                im.draft("RGB", (1600, 1600))
                rgb_im = im.convert("RGBA")
                rgb_im.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
                rgb_im.save(target_path, "PNG")
            if os.path.exists(target_path) and os.path.getsize(target_path) > 0:
                return target_path
        except Exception as e:
            logger.error(f"ThumbnailCacheManager: Error generando preview cacheado de {file_path}: {e}")
        return None

    def purge_stale_background(self):
        """Cancela las tareas de fondo aún NO iniciadas para archivos que ya no son
        relevantes tras un cambio real de carpeta/colección/filtro/búsqueda (no una carga
        incremental de más del mismo listado).

        Usa QThreadPool.tryTake() en vez de QThreadPool.clear(): el pool de fondo lo
        comparten ThumbnailCacheManager y WaveformCacheManager (ver media_task_pools.py),
        así que un .clear() a secas también borraría de golpe las tareas del otro gestor
        sin que este se entere, dejando sus propios diccionarios de seguimiento (y sus
        referencias fuertes a workers) apuntando a runnables ya destruidos por Qt.
        tryTake() en cambio cancela un worker puntual (y devuelve False sin tocar nada si
        ya arrancó a correr o si pertenece a otro pool/gestor), así que es seguro llamarlo
        aquí sin coordinarse con WaveformCacheManager. Las tareas que ya estaban corriendo
        (como mucho las que ocupan los hilos del pool ahora mismo) se dejan terminar solas
        — nada se pierde en disco, y si el archivo vuelve a ser visible más adelante
        simplemente se vuelve a pedir."""
        pool = get_background_pool()
        for file_path in list(self._pending_background):
            workers = self._active_workers.get(file_path)
            if workers:
                for w in list(workers):
                    if pool.tryTake(w):
                        workers.discard(w)
                if not workers:
                    self._active_workers.pop(file_path, None)
            self._pending_background.discard(file_path)

    def _create_thumbnail(self, file_path: str, media_type: str) -> str | None:
        """Genera la miniatura según el tipo de medio y la guarda en CACHE_DIR."""
        hash_key = self._get_hash_key(file_path)
        target_path = os.path.join(CACHE_DIR, f"{hash_key}.jpg")
        ext = os.path.splitext(file_path)[1].lower()

        if ext in (".svg", ".svgz"):
            return self._generate_svg_thumbnail(file_path, target_path)
        elif ext in (".pdf", ".ai"):
            return self._generate_pdf_thumbnail(file_path, target_path)
        elif ext in (".eps", ".ps"):
            return self._generate_eps_thumbnail(file_path, target_path)
        elif ext == ".psd":
            return self._generate_psd_thumbnail(file_path, target_path)
        elif ext in RAW_EXTS:
            return self._generate_raw_thumbnail(file_path, target_path)
        elif media_type == "imagen":
            return self._generate_image_thumbnail(file_path, target_path)
        elif media_type == "video":
            return self._generate_video_thumbnail(file_path, target_path)
        elif media_type == "audio":
            return self._generate_audio_thumbnail(file_path, target_path)
        return None

    def _generate_svg_thumbnail(self, src_path: str, target_path: str) -> str | None:
        try:
            from PySide6.QtSvg import QSvgRenderer
            from PySide6.QtCore import QRectF, QSize
            renderer = QSvgRenderer(src_path)
            if not renderer.isValid():
                return None

            default_size = renderer.defaultSize()
            if default_size.isEmpty() or default_size.width() <= 0 or default_size.height() <= 0:
                default_size = QSize(256, 256)

            scaled_size = default_size.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio)
            img = QImage(256, 256, QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(QColor("#1c1c1e"))

            painter = QPainter(img)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            x = (256 - scaled_size.width()) // 2
            y = (256 - scaled_size.height()) // 2
            renderer.render(painter, QRectF(x, y, scaled_size.width(), scaled_size.height()))
            painter.end()

            if img.save(target_path, "JPG", 85):
                return target_path
        except Exception as e:
            logger.error(f"ThumbnailCacheManager: Error en miniatura SVG {src_path}: {e}")
        return None

    def _generate_pdf_thumbnail(self, src_path: str, target_path: str) -> str | None:
        try:
            from PySide6.QtPdf import QPdfDocument
            from PySide6.QtCore import QSize
            # Sin parent porque corre en hilo de trabajo secundario
            doc = QPdfDocument()
            doc.load(src_path)
            if doc.pageCount() > 0:
                page_size = doc.pagePointSize(0)
                if page_size.isValid() and page_size.width() > 0 and page_size.height() > 0:
                    w, h = page_size.width(), page_size.height()
                    scale = min(256.0 / w, 256.0 / h)
                    render_w = max(1, int(w * scale))
                    render_h = max(1, int(h * scale))
                    page_img = doc.render(0, QSize(render_w, render_h))
                    if not page_img.isNull():
                        out_img = QImage(256, 256, QImage.Format.Format_RGB32)
                        out_img.fill(QColor("#1c1c1e"))
                        painter = QPainter(out_img)
                        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                        x = (256 - render_w) // 2
                        y = (256 - render_h) // 2
                        painter.drawImage(x, y, page_img)
                        painter.end()
                        doc.close()
                        if out_img.save(target_path, "JPG", 85):
                            return target_path
            doc.close()
        except Exception as e:
            logger.error(f"ThumbnailCacheManager: Error en miniatura PDF/AI {src_path}: {e}")
        return None

    def _generate_psd_thumbnail(self, src_path: str, target_path: str) -> str | None:
        try:
            # 1. Recurso de thumbnail embebido por Photoshop (psd-tools). No compone capas
            # ni decodifica los píxeles del documento: lee directamente la vista previa
            # de baja resolución que Photoshop ya guarda dentro del archivo, así que su
            # costo es independiente del número de capas o de la resolución del PSD.
            try:
                from psd_tools import PSDImage
                psd = PSDImage.open(src_path)
                embedded = psd.thumbnail()
                if embedded is not None:
                    rgb_im = embedded.convert('RGB')
                    rgb_im.thumbnail((256, 256))
                    rgb_im.save(target_path, "JPEG", quality=85)
                    return target_path
            except Exception:
                pass

            # 2. QImageReader habitual (gratis: falla al instante si Qt no tiene plugin PSD).
            reader = QImageReader(src_path)
            if reader.canRead():
                img = reader.read()
                if not img.isNull():
                    scaled = img.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    out_img = QImage(256, 256, QImage.Format.Format_RGB32)
                    out_img.fill(QColor("#1c1c1e"))
                    painter = QPainter(out_img)
                    x = (256 - scaled.width()) // 2
                    y = (256 - scaled.height()) // 2
                    painter.drawImage(x, y, scaled)
                    painter.end()
                    if out_img.save(target_path, "JPG", 85):
                        return target_path

            # 3. Pillow (in-process, sin costo de arranque de subproceso). Compone todas
            # las capas del documento, por eso va antes de FFmpeg pero después del
            # thumbnail embebido: solo se llega aquí si el PSD no traía vista previa
            # guardada (poco común, pero pasa con archivos generados por otras herramientas).
            try:
                from PIL import Image
                with Image.open(src_path) as im:
                    im.thumbnail((256, 256))
                    rgb_im = im.convert('RGB')
                    rgb_im.save(target_path, "JPEG", quality=85)
                    return target_path
            except Exception:
                pass

            # 4. FFmpeg como último recurso: paga el costo de lanzar un proceso nuevo
            # (arranque + posible escaneo de antivirus en Windows), así que solo vale la
            # pena si los tres intentos anteriores fallaron.
            if check_ffmpeg():
                info = get_platform_info()
                ffmpeg_exe = os.path.join(get_ffmpeg_dir(), info["binary_name"])
                startupinfo = None
                if os.name == 'nt':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

                cmd = [
                    ffmpeg_exe,
                    "-i", src_path,
                    "-vframes", "1",
                    "-vf", "scale=256:256:force_original_aspect_ratio=decrease",
                    "-y", target_path
                ]
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    startupinfo=startupinfo,
                    text=True,
                    encoding='utf-8',
                    errors='ignore'
                )
                process.communicate(timeout=6)
                if os.path.exists(target_path) and os.path.getsize(target_path) > 0:
                    return target_path
        except Exception as e:
            logger.error(f"ThumbnailCacheManager: Error en miniatura PSD {src_path}: {e}")
        return None

    def _generate_raw_thumbnail(self, src_path: str, target_path: str) -> str | None:
        """Miniatura de RAW de cámara (CR2/NEF/ARW/DNG/...). Casi todos los RAW traen un
        preview JPEG (a veces casi resolución completa) embebido por la propia cámara --
        leerlo con rawpy.extract_thumb() es órdenes de magnitud más rápido que revelar el
        RAW completo (demosaico a resolución completa). El revelado completo
        (raw.postprocess()) queda solo como último recurso para el puñado de archivos que
        no traen ese preview embebido."""
        try:
            import rawpy
            with rawpy.imread(src_path) as raw:
                try:
                    thumb = raw.extract_thumb()
                    if thumb.format == rawpy.ThumbFormat.JPEG:
                        import io
                        from PIL import Image
                        im = Image.open(io.BytesIO(thumb.data))
                    elif thumb.format == rawpy.ThumbFormat.BITMAP:
                        from PIL import Image
                        im = Image.fromarray(thumb.data)
                    else:
                        im = None
                except (rawpy.LibRawNoThumbnailError, rawpy.LibRawUnsupportedThumbnailError):
                    im = None

                if im is None:
                    # Sin preview embebido (raro): revelar el RAW completo como último recurso.
                    rgb = raw.postprocess(
                        use_camera_wb=True, output_bps=8,
                        output_color=rawpy.ColorSpace.sRGB,
                        demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD,
                    )
                    from PIL import Image
                    im = Image.fromarray(rgb)

            # El JPEG embebido viene en la orientación nativa del sensor, con un tag
            # EXIF aparte indicando cómo rotarlo para verse derecho -- Pillow no lo
            # aplica solo. Sin esto, las fotos tomadas en vertical salen de costado.
            try:
                from PIL import ImageOps
                im = ImageOps.exif_transpose(im)
            except Exception:
                pass

            rgb_im = im.convert("RGB")
            rgb_im.thumbnail((256, 256))
            rgb_im.save(target_path, "JPEG", quality=85)
            return target_path
        except Exception as e:
            logger.error(f"ThumbnailCacheManager: Error en miniatura RAW {src_path}: {e}")
        return None

    def _generate_eps_thumbnail(self, src_path: str, target_path: str) -> str | None:
        try:
            import struct
            import re
            # 1. Intentar extraer preview TIFF incrustado en cabecera binaria DOS EPS
            with open(src_path, "rb") as f:
                raw_head = f.read(4096)
                if len(raw_head) >= 28 and raw_head[:4] in (b'\xC5\xD0\xD3\xC6', b'\xC6\xD3\xD0\xC5'):
                    tiff_start, tiff_len = struct.unpack("<II", raw_head[20:28])
                    if tiff_len > 0:
                        f.seek(tiff_start)
                        tiff_bytes = f.read(tiff_len)
                        if tiff_bytes:
                            tiff_img = QImage.fromData(tiff_bytes)
                            if not tiff_img.isNull():
                                scaled = tiff_img.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                                out_img = QImage(256, 256, QImage.Format.Format_RGB32)
                                out_img.fill(QColor("#1c1c1e"))
                                painter = QPainter(out_img)
                                x = (256 - scaled.width()) // 2
                                y = (256 - scaled.height()) // 2
                                painter.drawImage(x, y, scaled)
                                painter.end()
                                if out_img.save(target_path, "JPG", 85):
                                    return target_path

            # 2. Intentar cargar como PDF/AI
            try:
                from PySide6.QtPdf import QPdfDocument
                from PySide6.QtCore import QSize
                doc = QPdfDocument()
                doc.load(src_path)
                if doc.pageCount() > 0:
                    sz = doc.pagePointSize(0)
                    if sz.isValid() and sz.width() > 0:
                        scale = min(256.0 / sz.width(), 256.0 / sz.height())
                        render_w = max(1, int(sz.width() * scale))
                        render_h = max(1, int(sz.height() * scale))
                        page_img = doc.render(0, QSize(render_w, render_h))
                        if not page_img.isNull():
                            out_img = QImage(256, 256, QImage.Format.Format_RGB32)
                            out_img.fill(QColor("#1c1c1e"))
                            painter = QPainter(out_img)
                            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                            x = (256 - render_w) // 2
                            y = (256 - render_h) // 2
                            painter.drawImage(x, y, page_img)
                            painter.end()
                            doc.close()
                            if out_img.save(target_path, "JPG", 85):
                                return target_path
                    doc.close()
            except Exception:
                pass

            # 3. Intentar con FFmpeg
            if check_ffmpeg():
                try:
                    info = get_platform_info()
                    ffmpeg_exe = os.path.join(get_ffmpeg_dir(), info["binary_name"])
                    startupinfo = None
                    if os.name == 'nt':
                        startupinfo = subprocess.STARTUPINFO()
                        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

                    cmd = [
                        ffmpeg_exe,
                        "-i", src_path,
                        "-vframes", "1",
                        "-vf", "scale=256:256:force_original_aspect_ratio=decrease",
                        "-y", target_path
                    ]
                    proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        startupinfo=startupinfo,
                        text=True,
                        encoding='utf-8',
                        errors='ignore'
                    )
                    proc.communicate(timeout=4)
                    if os.path.exists(target_path) and os.path.getsize(target_path) > 0:
                        return target_path
                except Exception:
                    pass

            # 4. Fallback visual: Crear miniatura estilizada tipo tarjeta vectorial con BoundingBox
            dim_str = ""
            with open(src_path, "rb") as f:
                header_text = f.read(4096).decode("latin-1", errors="ignore")
                match = re.search(r"%%(?:HiRes)?BoundingBox:\s*([-\d\.]+)\s+([-\d\.]+)\s+([-\d\.]+)\s+([-\d\.]+)", header_text)
                if match:
                    x1, y1, x2, y2 = map(float, match.groups())
                    w = int(round(abs(x2 - x1)))
                    h = int(round(abs(y2 - y1)))
                    if w > 0 and h > 0:
                        dim_str = f"{w}x{h}"

            out_img = QImage(256, 256, QImage.Format.Format_RGB32)
            out_img.fill(QColor("#18181a"))
            painter = QPainter(out_img)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

            from PySide6.QtGui import QPen, QBrush, QFont
            from PySide6.QtCore import QRectF
            pen = QPen(QColor("#2d2d30"), 2)
            painter.setPen(pen)
            painter.setBrush(QBrush(QColor("#202024")))
            painter.drawRoundedRect(16, 16, 224, 224, 12, 12)

            from core.utils.font_manager import system_ui_family
            ui_family = system_ui_family()
            ext_label = "EPS" if src_path.lower().endswith(".eps") else "PS"
            font_badge = QFont(ui_family, 26, QFont.Weight.Bold)
            painter.setFont(font_badge)
            painter.setPen(QColor("#e67e22"))
            painter.drawText(QRectF(16, 50, 224, 45), Qt.AlignmentFlag.AlignCenter, ext_label)

            if dim_str:
                font_dim = QFont(ui_family, 12)
                painter.setFont(font_dim)
                painter.setPen(QColor("#aaaaaa"))
                painter.drawText(QRectF(16, 110, 224, 30), Qt.AlignmentFlag.AlignCenter, dim_str)

            font_desc = QFont(ui_family, 10)
            painter.setFont(font_desc)
            painter.setPen(QColor("#666666"))
            painter.drawText(QRectF(16, 155, 224, 24), Qt.AlignmentFlag.AlignCenter, "Vector PostScript")

            painter.end()
            if out_img.save(target_path, "JPG", 85):
                return target_path

        except Exception as e:
            logger.error(f"ThumbnailCacheManager: Error en miniatura EPS/PS {src_path}: {e}")
        return None

    def _generate_image_thumbnail(self, src_path: str, target_path: str) -> str | None:
        try:
            reader = QImageReader(src_path)
            reader.setAutoTransform(True)
            orig_size = reader.size()
            if orig_size.isValid() and orig_size.width() > 0 and orig_size.height() > 0:
                # Escalar durante la lectura para ahorrar memoria y tiempo de procesamiento
                if orig_size.width() > 256 or orig_size.height() > 256:
                    scaled_size = orig_size.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio)
                    reader.setScaledSize(scaled_size)
            
            img = reader.read()
            if img.isNull():
                # Qt rechazó la imagen por superar su límite de asignación de memoria
                # (QImageReader.allocationLimit(), 256MB por defecto) -- típico en PNG/
                # TIFF muy grandes, que a diferencia de JPEG no soportan decodificar
                # directo en baja resolución. Pillow no tiene ese techo artificial.
                return self._generate_image_thumbnail_with_pillow(src_path, target_path)
            if img.save(target_path, "JPG", 85):
                return target_path
        except Exception as e:
            logger.error(f"ThumbnailCacheManager: Error en miniatura de imagen {src_path}: {e}")
        return None

    def _generate_image_thumbnail_with_pillow(self, src_path: str, target_path: str) -> str | None:
        """Respaldo para imágenes que Qt rechaza por ser demasiado grandes/pesadas."""
        try:
            from PIL import Image
            with Image.open(src_path) as im:
                im.draft("RGB", (256, 256))  # sin efecto salvo en JPEG; ahí evita decodificar a tamaño completo
                rgb_im = im.convert("RGB")
                rgb_im.thumbnail((256, 256))
                rgb_im.save(target_path, "JPEG", quality=85)
                return target_path
        except Exception as e:
            logger.error(f"ThumbnailCacheManager: Pillow tampoco pudo generar miniatura de {src_path}: {e}")
        return None

    def _generate_video_thumbnail(self, src_path: str, target_path: str) -> str | None:
        """Extrae una miniatura de video en el 10% de su duración usando FFmpeg."""
        if not check_ffmpeg():
            return None

        try:
            info = get_platform_info()
            ffmpeg_exe = os.path.join(get_ffmpeg_dir(), info["binary_name"])

            duration_secs = self._get_video_duration_seconds(ffmpeg_exe, src_path)
            target_time = max(0.0, duration_secs * 0.10) if duration_secs > 0 else 0.0

            hours = int(target_time // 3600)
            mins = int((target_time % 3600) // 60)
            secs = target_time % 60
            timestamp_str = f"{hours:02d}:{mins:02d}:{secs:06.3f}"

            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            cmd = [
                ffmpeg_exe,
                "-ss", timestamp_str,
                "-i", src_path,
                "-vframes", "1",
                "-vf", "scale=256:256:force_original_aspect_ratio=decrease",
                "-y", target_path
            ]

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=startupinfo,
                text=True,
                encoding='utf-8',
                errors='ignore'
            )
            process.communicate(timeout=8)

            if os.path.exists(target_path) and os.path.getsize(target_path) > 0:
                return target_path

            # Fallback: si el salto temporal al 10% no produjo fotograma (video ultra-corto o sin keyframe intermedio), capturar el primer fotograma (0.0s)
            if target_time > 0:
                fallback_cmd = [
                    ffmpeg_exe,
                    "-ss", "00:00:00.000",
                    "-i", src_path,
                    "-vframes", "1",
                    "-vf", "scale=256:256:force_original_aspect_ratio=decrease",
                    "-y", target_path
                ]
                fallback_proc = subprocess.Popen(
                    fallback_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    startupinfo=startupinfo,
                    text=True,
                    encoding='utf-8',
                    errors='ignore'
                )
                fallback_proc.communicate(timeout=6)

                if os.path.exists(target_path) and os.path.getsize(target_path) > 0:
                    return target_path
        except Exception as e:
            logger.error(f"ThumbnailCacheManager: Error extrayendo fotograma de video {src_path}: {e}")
        return None

    def _get_video_duration_seconds(self, ffmpeg_exe: str, src_path: str) -> float:
        """Obtiene la duración aproximada en segundos de un archivo mediante FFmpeg."""
        try:
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            cmd = [ffmpeg_exe, "-hide_banner", "-i", src_path]
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=startupinfo,
                text=True,
                encoding='utf-8',
                errors='ignore'
            )
            _, stderr = process.communicate(timeout=3)
            match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
            if match:
                hours = float(match.group(1))
                mins = float(match.group(2))
                secs = float(match.group(3))
                return hours * 3600 + mins * 60 + secs
        except Exception:
            pass
        return 0.0

    def _generate_audio_thumbnail(self, src_path: str, target_path: str) -> str | None:
        """Extrae la portada incrustada del archivo de audio si existe mediante Mutagen."""
        try:
            from mutagen import File as MutagenFile
            audio = MutagenFile(src_path)
            if audio is not None and hasattr(audio, 'tags') and audio.tags:
                image_data = None
                for key in audio.tags.keys():
                    if key.startswith("APIC"):
                        image_data = audio.tags[key].data
                        break
                if not image_data and hasattr(audio, 'pictures') and audio.pictures:
                    image_data = audio.pictures[0].data

                if image_data:
                    img = QImage.fromData(image_data)
                    if not img.isNull():
                        scaled = img.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                        if scaled.save(target_path, "JPG", 85):
                            return target_path
        except Exception as e:
            logger.debug(f"ThumbnailCacheManager: Sin portada incrustada para audio {src_path}: {e}")
        return None

    def clear_cache(self) -> int:
        """Borra todos los archivos de caché de miniaturas y vacía las memorias en RAM."""
        count = 0
        self._qicon_cache.clear()
        self._hash_cache.clear()
        self._failed_files.clear()
        if os.path.exists(CACHE_DIR):
            for fname in os.listdir(CACHE_DIR):
                fpath = os.path.join(CACHE_DIR, fname)
                if os.path.isfile(fpath):
                    try:
                        os.remove(fpath)
                        count += 1
                    except Exception as e:
                        logger.error(f"ThumbnailCacheManager: Error eliminando {fpath}: {e}")
        logger.info(f"ThumbnailCacheManager: Se eliminaron {count} miniaturas en caché.")
        return count
