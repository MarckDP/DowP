# src/core/utils/download_history.py
"""Historial de descargas compartido entre Modo Rápido y Proceso Avanzado.

Guarda una "tarjeta" por cada medio o playlist que se analizó o descargó: título, URL,
duración, si solo se analizó o también se descargó, y una miniatura chica. Es un
registro de lo que se hizo: una tarjeta "Descargado" lo sigue siendo aunque el archivo
ya no exista. Además guarda los archivos que produjo, para que el panel pueda ofrecer
abrirlos, mostrar su ubicación o arrastrarlos MIENTRAS sigan en disco (ver abajo).

Detalles de diseño:

  - SQLite (módulo estándar de Python) y no un JSON: el límite de entradas lo puede
    subir el usuario sin tope, y así cada cambio escribe una fila en vez de reescribir
    el archivo entero. Todas las operaciones de la base van por el hilo principal.
  - La miniatura del historial es SOLO del historial: tiene su propia descarga (la
    variante más chica que alcance, ver pick_small_thumbnail) y su propia carpeta,
    `<caché de miniaturas>/history/`. No toca ni reutiliza la lógica de miniaturas de
    las descargas (vista previa, "Guardar miniatura", carátula incrustada...).
    Se cuenta y se borra desde Ajustes > Memoria y Caché, dentro de "Caché de Imágenes
    y Miniaturas" (ver cache_manager.ImageThumbnailCacheProvider). Si se borra, la
    tarjeta la vuelve a pedir la próxima vez que se muestra (ensure_thumbnail), usando
    la URL guardada -- en sitios cuyos enlaces caducan ya no se podrá, y la tarjeta
    queda con el marcador genérico.
  - Archivos: se guardan las MISMAS dos listas que el arrastre de las pestañas
    (OutputArtifactTracker / fila de Modo Rápido): todas las rutas conocidas y cuáles
    sirven como nombre base para encontrar los hermanos (sidecars). "¿Sigue en disco?",
    "cuál es el medio principal" y "qué se arrastra" se resuelven igual que en la cola,
    con find_actual_downloaded_file / collect_output_artifacts, y nunca al dibujar: ver
    resolve_disk_files y el chequeo en segundo plano del panel.
  - Una tarjeta por OPERACIÓN, no por URL: descargar la misma URL 100 veces deja 100
    tarjetas. Cada análisis crea la suya (clave única), y la descarga que le sigue la
    pasa de "Analizado" a "Descargado" en vez de crear otra. Si esa misma tarjeta se
    vuelve a descargar (varias descargas desde un solo análisis en Proceso Avanzado, o
    un job de la cola que se reintenta), la nueva descarga sale en una tarjeta aparte
    (ver duplicate / mark_job_downloaded). Las tarjetas de una misma URL comparten el
    archivo de miniatura (se nombra por la URL de la imagen, no por la tarjeta).
"""
import hashlib
import os
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests
from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QImage

from core.logger.logger_manager import logger
from core.utils.config_manager import get_config, save_config
from core.utils.output_artifacts import collect_output_artifacts, find_actual_downloaded_file
from core.utils.paths import get_app_data_dir, get_thumbnail_cache_dir

STATUS_ANALYZED = "analyzed"
STATUS_DOWNLOADED = "downloaded"
KIND_MEDIA = "media"
KIND_PLAYLIST = "playlist"

DEFAULT_MAX_ENTRIES = 500
# Ancho con el que se guarda la miniatura: la tarjeta la dibuja a ~96 px, así que 240
# alcanza también para pantallas de alta densidad y pesa unos pocos KB en JPEG.
THUMB_SAVE_WIDTH = 240
THUMB_MIN_SOURCE_WIDTH = 240
THUMB_JPEG_QUALITY = 80

_COLUMNS = ("key", "url", "title", "duration", "kind", "item_count", "status",
            "thumb_url", "thumb_file", "output_path", "created_at", "updated_at")


def get_history_thumbnail_dir() -> str:
    d = os.path.join(get_thumbnail_cache_dir(), "history")
    os.makedirs(d, exist_ok=True)
    return d


def pick_small_thumbnail(info: dict):
    """URL de la variante MÁS CHICA de la miniatura que todavía alcance para la tarjeta
    (al menos THUMB_MIN_SOURCE_WIDTH px de ancho). Nunca la de mayor resolución: el
    historial solo necesita una imagen pequeña. Sin anchos conocidos, la primera de la
    lista (yt-dlp las ordena de menor a mayor preferencia) y, como último recurso,
    `thumbnail`."""
    thumbs = [t for t in (info.get("thumbnails") or []) if isinstance(t, dict) and t.get("url")]
    sized = sorted((t for t in thumbs if t.get("width")), key=lambda t: t["width"])
    for t in sized:
        if t["width"] >= THUMB_MIN_SOURCE_WIDTH:
            return t["url"]
    if sized:
        return sized[-1]["url"]
    if thumbs:
        return thumbs[0]["url"]
    return info.get("thumbnail")


def _playlist_thumbnail(info: dict):
    url = pick_small_thumbnail(info)
    if url:
        return url
    for entry in info.get("entries") or []:
        if isinstance(entry, dict):
            url = pick_small_thumbnail(entry)
            if url:
                return url
    return None


def _new_key() -> str:
    """Clave de una tarjeta: única por operación (ver docstring del módulo)."""
    return uuid.uuid4().hex


def _thumb_file_name(thumb_url: str) -> str:
    """Nombre del archivo de miniatura a partir de la URL de la imagen: todas las tarjetas
    de un mismo medio comparten un solo archivo en disco."""
    return hashlib.sha1(thumb_url.encode("utf-8")).hexdigest()[:20] + ".jpg"


def _is_playlist(info: dict) -> bool:
    entries = info.get("entries") or []
    return bool(entries) and (info.get("_type") in ("playlist", "multi_video") or len(entries) > 1)


class DownloadHistory(QObject):
    """Registro único del historial para toda la app (ver download_history())."""

    # Cambió la lista (entrada nueva, reordenada, borrada, historial vaciado): las vistas
    # tienen que volver a consultar.
    entries_changed = Signal()
    # Cambiaron los datos de UNA entrada ya visible (estado, miniatura lista...).
    entry_updated = Signal(str)
    # Uso interno: la miniatura se descarga en otro hilo y vuelve por aquí al principal.
    _thumbnail_done = Signal(str, str)

    def __init__(self, db_path: str = None, parent=None):
        super().__init__(parent)
        self._db_path = db_path or os.path.join(get_app_data_dir(), "download_history.db")
        self._db = sqlite3.connect(self._db_path)
        self._db.row_factory = sqlite3.Row
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS entries (
                key TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                title TEXT,
                duration REAL,
                kind TEXT NOT NULL DEFAULT 'media',
                item_count INTEGER,
                status TEXT NOT NULL DEFAULT 'analyzed',
                thumb_url TEXT,
                thumb_file TEXT,
                output_path TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )""")
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_entries_updated ON entries(updated_at DESC)")
        # Archivos de cada tarjeta. is_stem = 1: su nombre base sirve para barrer hermanos
        # (el medio descargado); 0: no (la salida recodificada, sidecars sueltos).
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS entry_files (
                key TEXT NOT NULL,
                path TEXT NOT NULL,
                is_stem INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (key, path)
            )""")
        self._db.commit()

        # job_id de la cola (Proceso Avanzado) -> clave de su tarjeta.
        self._job_keys: dict[str, str] = {}
        # Jobs que ya marcaron su tarjeta como descargada: si el mismo job vuelve a
        # completarse (se reintentó), esa descarga va a una tarjeta nueva.
        self._jobs_marked: set[str] = set()
        # Archivos de miniatura pedidos y todavía en curso (o que ya fallaron en esta
        # sesión): evita repetir la descarga cada vez que una tarjeta se repinta.
        self._thumb_requested: set[str] = set()
        self._thumb_lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="history_thumb")
        self._thumbnail_done.connect(self._on_thumbnail_done, Qt.QueuedConnection)

    # ── Configuración ────────────────────────────────────────────────────────
    @staticmethod
    def is_enabled() -> bool:
        return bool(get_config().get("history_enabled", True))

    @staticmethod
    def set_enabled(enabled: bool):
        config = get_config()
        config["history_enabled"] = bool(enabled)
        save_config(config)

    @staticmethod
    def max_entries() -> int:
        """0 = sin límite."""
        try:
            return max(0, int(get_config().get("history_max_entries", DEFAULT_MAX_ENTRIES)))
        except (TypeError, ValueError):
            return DEFAULT_MAX_ENTRIES

    def set_max_entries(self, value: int):
        config = get_config()
        config["history_max_entries"] = max(0, int(value))
        save_config(config)
        self.enforce_limit()

    # ── Registro ─────────────────────────────────────────────────────────────
    def record_analysis(self, info: dict, source_url: str = "", as_playlist: bool = None):
        """Crea la tarjeta de un análisis -- SIEMPRE una nueva, aunque la URL ya esté en
        el historial. `as_playlist` None = decidirlo por el propio resultado. Devuelve la
        clave, o None si el historial está desactivado o no hay datos útiles."""
        if not info or not self.is_enabled():
            return None
        playlist = _is_playlist(info) if as_playlist is None else (as_playlist and _is_playlist(info))
        key = _new_key()
        if playlist:
            url = info.get("original_url") or info.get("webpage_url") or source_url
            thumb_url = _playlist_thumbnail(info)
            duration = None
            item_count = len(info.get("entries") or []) or info.get("playlist_count")
        else:
            url = info.get("webpage_url") or info.get("original_url") or source_url
            thumb_url = pick_small_thumbnail(info)
            duration = info.get("duration")
            item_count = None
        if not url:
            return None
        title = info.get("title") or url
        now = time.time()

        self._db.execute(
            """INSERT INTO entries (key, url, title, duration, kind, item_count, status,
               thumb_url, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (key, url, title, duration, KIND_PLAYLIST if playlist else KIND_MEDIA,
             item_count, STATUS_ANALYZED, thumb_url, now, now))
        self._db.commit()
        self.enforce_limit(emit=False)
        self.entries_changed.emit()
        self.ensure_thumbnail(key)
        return key

    def mark_downloaded(self, key: str, output_path: str = None):
        """Pasa la tarjeta a "Descargado" (y la sube arriba). Los archivos llegan aparte,
        por record_outputs, con el mismo rastro que usa el arrastre de las pestañas."""
        if not key or not self.is_enabled():
            return
        cur = self._db.execute(
            "UPDATE entries SET status = ?, updated_at = ? WHERE key = ?",
            (STATUS_DOWNLOADED, time.time(), key))
        self._db.commit()
        if output_path:
            self.record_outputs(key, [output_path], [output_path])
        if cur.rowcount:
            self.entries_changed.emit()

    def record_outputs(self, key: str, known_paths, stem_paths=None):
        """Suma los archivos de una tarjeta: las rutas que el proceso fue registrando
        (incluidas las pistas intermedias de yt-dlp, que se resuelven al consultarlas) y
        cuáles sirven como nombre base. Se puede llamar varias veces (al terminar la
        descarga y otra vez al terminar la recodificación): solo agrega."""
        if not key or not self.is_enabled():
            return
        stems = set(p for p in (stem_paths if stem_paths is not None else known_paths) or [] if p)
        rows = [(key, p, 1 if p in stems else 0) for p in dict.fromkeys(known_paths or []) if p]
        if not rows:
            return
        if not self._db.execute("SELECT 1 FROM entries WHERE key = ?", (key,)).fetchone():
            return
        self._db.executemany(
            """INSERT INTO entry_files (key, path, is_stem) VALUES (?, ?, ?)
               ON CONFLICT(key, path) DO UPDATE SET is_stem = MAX(is_stem, excluded.is_stem)""",
            rows)
        self._db.commit()
        self.entry_updated.emit(key)

    def files_for(self, key: str):
        """(rutas conocidas, rutas base) de la tarjeta. Las tarjetas anteriores a la tabla
        entry_files solo tienen output_path: se usa como única ruta."""
        rows = self._db.execute(
            "SELECT path, is_stem FROM entry_files WHERE key = ? ORDER BY rowid", (key,)).fetchall()
        if rows:
            return [r["path"] for r in rows], [r["path"] for r in rows if r["is_stem"]]
        row = self._db.execute("SELECT output_path FROM entries WHERE key = ?", (key,)).fetchone()
        legacy = row["output_path"] if row else None
        return ([legacy], [legacy]) if legacy else ([], [])

    def duplicate(self, key: str):
        """Tarjeta nueva ("Analizado") con los mismos datos que `key`, sin sus archivos:
        para una descarga más desde un análisis que ya se descargó. Devuelve la clave
        nueva (o la misma si el historial está apagado o `key` ya no existe)."""
        row = self.get(key) if key else None
        if not row or not self.is_enabled():
            return key
        new_key = _new_key()
        now = time.time()
        self._db.execute(
            """INSERT INTO entries (key, url, title, duration, kind, item_count, status,
               thumb_url, thumb_file, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (new_key, row["url"], row["title"], row["duration"], row["kind"], row["item_count"],
             STATUS_ANALYZED, row["thumb_url"], row["thumb_file"], now, now))
        self._db.commit()
        self.enforce_limit(emit=False)
        self.entries_changed.emit()
        return new_key

    def key_for_new_download(self, key: str):
        """La clave a la que debe ir una descarga que EMPIEZA ahora desde el análisis
        `key`: la misma si esa tarjeta todavía no se descargó, o una copia nueva si ya."""
        row = self.get(key) if key else None
        if row and row["status"] == STATUS_DOWNLOADED:
            return self.duplicate(key)
        return key

    def bind_job(self, job_id: str, key: str):
        if job_id and key:
            self._job_keys[job_id] = key
            self._jobs_marked.discard(job_id)

    def key_for_job(self, job_id: str):
        return self._job_keys.get(job_id)

    def mark_job_downloaded(self, job_id: str, output_path: str = None):
        key = self._job_keys.get(job_id)
        if key and job_id in self._jobs_marked:
            # El mismo job se completó otra vez (se reintentó): es otra descarga.
            key = self.duplicate(key)
            self._job_keys[job_id] = key
        self._jobs_marked.add(job_id)
        self.mark_downloaded(key, output_path)

    # ── Consulta ─────────────────────────────────────────────────────────────
    @staticmethod
    def _search_clause(search: str):
        search = (search or "").strip()
        if not search:
            return "", ()
        like = f"%{search}%"
        return " WHERE title LIKE ? OR url LIKE ?", (like, like)

    def count(self, search: str = "") -> int:
        where, args = self._search_clause(search)
        return self._db.execute(f"SELECT COUNT(*) FROM entries{where}", args).fetchone()[0]

    def fetch(self, offset: int = 0, limit: int = 200, search: str = "") -> list:
        where, args = self._search_clause(search)
        rows = self._db.execute(
            f"SELECT * FROM entries{where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            args + (limit, offset)).fetchall()
        return [dict(r) for r in rows]

    def get(self, key: str):
        row = self._db.execute("SELECT * FROM entries WHERE key = ?", (key,)).fetchone()
        return dict(row) if row else None

    # ── Borrado ──────────────────────────────────────────────────────────────
    def _drop_unreferenced_thumbs(self, names):
        """Borra los archivos de miniatura que ya no use NINGUNA tarjeta: varias tarjetas
        de una misma URL comparten el mismo archivo. Llamar después de borrar las filas."""
        for name in set(n for n in names if n):
            if self._db.execute("SELECT 1 FROM entries WHERE thumb_file = ? LIMIT 1", (name,)).fetchone():
                continue
            try:
                os.remove(os.path.join(get_history_thumbnail_dir(), name))
            except OSError:
                pass

    def remove(self, key: str):
        names = [r["thumb_file"] for r in
                 self._db.execute("SELECT thumb_file FROM entries WHERE key = ?", (key,)).fetchall()]
        self._db.execute("DELETE FROM entries WHERE key = ?", (key,))
        self._db.execute("DELETE FROM entry_files WHERE key = ?", (key,))
        self._db.commit()
        self._drop_unreferenced_thumbs(names)
        self.entries_changed.emit()

    def clear(self):
        """Borra TODO el historial y sus miniaturas."""
        names = [r["thumb_file"] for r in self._db.execute("SELECT thumb_file FROM entries").fetchall()]
        self._db.execute("DELETE FROM entries")
        self._db.execute("DELETE FROM entry_files")
        self._db.commit()
        self._drop_unreferenced_thumbs(names)
        self._job_keys.clear()
        self._jobs_marked.clear()
        with self._thumb_lock:
            self._thumb_requested.clear()
        logger.info("DownloadHistory: historial borrado.")
        self.entries_changed.emit()

    def entries_over_limit(self, limit: int = None) -> int:
        """Cuántas entradas se borrarían con ese límite (para confirmar antes en Ajustes)."""
        limit = self.max_entries() if limit is None else limit
        if limit <= 0:
            return 0
        return max(0, self.count() - limit)

    def enforce_limit(self, emit: bool = True):
        limit = self.max_entries()
        if limit <= 0:
            return
        rows = self._db.execute(
            "SELECT key, thumb_file FROM entries ORDER BY updated_at DESC LIMIT -1 OFFSET ?",
            (limit,)).fetchall()
        if not rows:
            return
        self._db.executemany("DELETE FROM entries WHERE key = ?", [(r["key"],) for r in rows])
        self._db.executemany("DELETE FROM entry_files WHERE key = ?", [(r["key"],) for r in rows])
        self._db.commit()
        self._drop_unreferenced_thumbs([r["thumb_file"] for r in rows])
        logger.info(f"DownloadHistory: {len(rows)} entrada(s) antiguas borradas por el límite de {limit}.")
        if emit:
            self.entries_changed.emit()

    # ── Miniaturas (exclusivas del historial) ───────────────────────────────
    def thumbnail_path(self, entry: dict):
        """Ruta de la miniatura si existe en disco; None si falta (nunca la pide)."""
        name = entry.get("thumb_file")
        if not name:
            return None
        path = os.path.join(get_history_thumbnail_dir(), name)
        return path if os.path.isfile(path) else None

    def ensure_thumbnail(self, key: str):
        """Si la tarjeta no tiene su miniatura en disco (nueva, o se vació la caché), la
        consigue: si otra tarjeta del mismo medio ya la tiene, la comparte; si no, la pide
        en segundo plano -- una sola vez por sesión y archivo."""
        entry = self.get(key)
        if not entry or not entry.get("thumb_url") or self.thumbnail_path(entry):
            return
        url = entry["thumb_url"]
        name = _thumb_file_name(url)
        if os.path.isfile(os.path.join(get_history_thumbnail_dir(), name)):
            self._on_thumbnail_done(url, name)
            return
        with self._thumb_lock:
            if name in self._thumb_requested:
                return
            self._thumb_requested.add(name)
        self._pool.submit(self._download_thumbnail, url, name)

    def _download_thumbnail(self, url: str, name: str):
        """Hilo aparte: baja la imagen, la reduce a THUMB_SAVE_WIDTH y la guarda como JPEG.
        QImage (a diferencia de QPixmap) se puede usar fuera del hilo principal."""
        try:
            resp = requests.get(url, timeout=(10, 15), headers={"User-Agent": "DowP2"})
            resp.raise_for_status()
            img = QImage.fromData(resp.content)
            if img.isNull():
                raise ValueError("imagen no reconocida")
            if img.width() > THUMB_SAVE_WIDTH:
                img = img.scaledToWidth(THUMB_SAVE_WIDTH, Qt.SmoothTransformation)
            path = os.path.join(get_history_thumbnail_dir(), name)
            if not img.save(path, "JPG", THUMB_JPEG_QUALITY):
                raise OSError("no se pudo guardar")
            self._thumbnail_done.emit(url, name)
        except Exception as e:
            logger.debug(f"DownloadHistory: sin miniatura para {urlparse(url).netloc} ({e})")

    def _on_thumbnail_done(self, url: str, name: str):
        """La miniatura `name` está en disco: la toman TODAS las tarjetas de esa imagen."""
        with self._thumb_lock:
            self._thumb_requested.discard(name)
        keys = [r["key"] for r in self._db.execute(
            "SELECT key FROM entries WHERE thumb_url = ? AND (thumb_file IS NULL OR thumb_file != ?)",
            (url, name)).fetchall()]
        if keys:
            self._db.execute(
                "UPDATE entries SET thumb_file = ? WHERE thumb_url = ?", (name, url))
            self._db.commit()
            for key in keys:
                self.entry_updated.emit(key)
        else:
            # Las tarjetas se borraron mientras se descargaba su miniatura.
            self._drop_unreferenced_thumbs([name])

    def forget_thumbnails(self):
        """Llamado al vaciar la caché de miniaturas desde Ajustes: los archivos ya se
        borraron; se permite volver a pedirlos cuando las tarjetas se muestren."""
        with self._thumb_lock:
            self._thumb_requested.clear()
        self.entries_changed.emit()


# Extensiones de archivos que acompañan al medio (miniatura, subtítulos, metadatos).
_SIDECAR_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".srt", ".vtt", ".ass", ".ssa", ".lrc",
                 ".json", ".description"}


def _is_sidecar(path: str) -> bool:
    return os.path.splitext(path or "")[1].lower() in _SIDECAR_EXTS


def resolve_disk_files(known_paths, stem_paths):
    """Estado en disco de una tarjeta: (medio principal, archivos a arrastrar).

    - Medio principal: el DESCARGADO, resuelto con find_actual_downloaded_file igual que
      las pestañas (la pista de yt-dlp suele ser un intermedio que ffmpeg borra al
      fusionar). Si ya no existe, lo procesado (la salida recodificada). Un sidecar solo
      cuenta como principal si lo descargado ERA ese tipo de archivo (modo "solo
      miniatura"): una miniatura huérfana no significa que el video siga en disco.
      None = nada de esta tarjeta sigue en disco.
    - Arrastre: todo lo que aún existe, como en la cola (collect_output_artifacts: medio,
      procesados, miniatura, subtítulos), con el principal primero.

    Toca el disco: nunca llamarla al dibujar. Es segura fuera del hilo principal."""
    primary = None
    for path in stem_paths or []:
        real = find_actual_downloaded_file(path)
        if real and os.path.isfile(real) and not (_is_sidecar(real) and not _is_sidecar(path)):
            primary = os.path.abspath(real)
            break
    if primary is None:
        stems = set(stem_paths or [])
        for path in known_paths or []:
            if path not in stems and path and os.path.isfile(path) and not _is_sidecar(path):
                primary = os.path.abspath(path)
                break
    if primary is None:
        return None, []
    drag = collect_output_artifacts(known_paths, stem_paths=stem_paths)
    first = os.path.normcase(primary)
    drag = [primary] + [p for p in drag if os.path.normcase(p) != first]
    return primary, drag


_history = None


def download_history() -> DownloadHistory:
    """El DownloadHistory de la app (se crea al primer uso, con la QApplication ya en
    marcha)."""
    global _history
    if _history is None:
        _history = DownloadHistory()
    return _history


def history_thumbnail_stats() -> tuple[int, int]:
    """(archivos, bytes) de las miniaturas del historial, para Memoria y Caché."""
    count = size = 0
    d = get_history_thumbnail_dir()
    for entry in os.scandir(d):
        if entry.is_file():
            count += 1
            try:
                size += entry.stat().st_size
            except OSError:
                pass
    return count, size


def clear_history_thumbnails() -> int:
    """Borra los archivos de miniatura del historial (NO las entradas). Devuelve cuántos."""
    removed = 0
    d = get_history_thumbnail_dir()
    for entry in os.scandir(d):
        if entry.is_file():
            try:
                os.remove(entry.path)
                removed += 1
            except OSError:
                pass
    if _history is not None:
        _history.forget_thumbnails()
    return removed
