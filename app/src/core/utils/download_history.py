# src/core/utils/download_history.py
"""Historial de descargas compartido entre Modo Rápido y Proceso Avanzado.

Guarda una "tarjeta" por cada medio o playlist que se analizó o descargó: título, URL,
duración, si solo se analizó o también se descargó, y una miniatura chica. Es un
registro de lo que se hizo, NO un gestor de archivos: no comprueba si lo descargado
sigue en disco. Aun así guarda la ruta del resultado (`output_path`) para que más
adelante se pueda ofrecer "abrir carpeta" sin perder las entradas viejas.

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
  - Una misma URL/medio no se duplica: la clave es "extractor:id" de yt-dlp; volver a
    analizarlo actualiza su tarjeta y la sube arriba. El estado solo avanza
    (analyzed -> downloaded), nunca retrocede.
"""
import hashlib
import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests
from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QImage

from core.logger.logger_manager import logger
from core.utils.config_manager import get_config, save_config
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


def entry_key(info: dict, source_url: str = "") -> str:
    """Clave estable de una tarjeta. "extractor:id" identifica el medio aunque la URL
    venga con parámetros distintos (?t=, &si=, etc.); sin eso, la URL."""
    extractor = info.get("extractor_key") or info.get("ie_key") or info.get("extractor")
    media_id = info.get("id")
    if extractor and media_id:
        return f"{str(extractor).lower()}:{media_id}"
    url = info.get("webpage_url") or info.get("original_url") or source_url or ""
    return f"url:{url}"


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
        self._db.commit()

        # job_id de la cola (Proceso Avanzado) -> clave de su tarjeta.
        self._job_keys: dict[str, str] = {}
        # Miniaturas pedidas y todavía en curso (o que ya fallaron en esta sesión): evita
        # repetir la descarga cada vez que la tarjeta se repinta.
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
        """Registra (o sube arriba) la tarjeta de un análisis. `as_playlist` None =
        decidirlo por el propio resultado. Devuelve la clave, o None si el historial está
        desactivado o no hay datos útiles."""
        if not info or not self.is_enabled():
            return None
        playlist = _is_playlist(info) if as_playlist is None else (as_playlist and _is_playlist(info))
        key = entry_key(info, source_url)
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

        existing = self._db.execute("SELECT status, thumb_url FROM entries WHERE key = ?", (key,)).fetchone()
        if existing:
            self._db.execute(
                """UPDATE entries SET url = ?, title = ?, duration = COALESCE(?, duration),
                   kind = ?, item_count = COALESCE(?, item_count),
                   thumb_url = COALESCE(?, thumb_url), updated_at = ? WHERE key = ?""",
                (url, title, duration, KIND_PLAYLIST if playlist else KIND_MEDIA, item_count,
                 thumb_url, now, key))
        else:
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
        """Pasa la tarjeta a "Descargado" (y la sube arriba). La ruta se guarda pero el
        historial nunca la comprueba."""
        if not key or not self.is_enabled():
            return
        cur = self._db.execute(
            """UPDATE entries SET status = ?, output_path = COALESCE(?, output_path),
               updated_at = ? WHERE key = ?""",
            (STATUS_DOWNLOADED, output_path, time.time(), key))
        self._db.commit()
        if cur.rowcount:
            self.entries_changed.emit()

    def bind_job(self, job_id: str, key: str):
        if job_id and key:
            self._job_keys[job_id] = key

    def key_for_job(self, job_id: str):
        return self._job_keys.get(job_id)

    def mark_job_downloaded(self, job_id: str, output_path: str = None):
        self.mark_downloaded(self._job_keys.get(job_id), output_path)

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
    def _delete_thumb_files(self, rows):
        for row in rows:
            name = row["thumb_file"]
            if name:
                try:
                    os.remove(os.path.join(get_history_thumbnail_dir(), name))
                except OSError:
                    pass

    def remove(self, key: str):
        rows = self._db.execute("SELECT thumb_file FROM entries WHERE key = ?", (key,)).fetchall()
        self._delete_thumb_files(rows)
        self._db.execute("DELETE FROM entries WHERE key = ?", (key,))
        self._db.commit()
        self.entries_changed.emit()

    def clear(self):
        """Borra TODO el historial y sus miniaturas."""
        rows = self._db.execute("SELECT thumb_file FROM entries").fetchall()
        self._delete_thumb_files(rows)
        self._db.execute("DELETE FROM entries")
        self._db.commit()
        self._job_keys.clear()
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
        self._delete_thumb_files(rows)
        self._db.executemany("DELETE FROM entries WHERE key = ?", [(r["key"],) for r in rows])
        self._db.commit()
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
        pide en segundo plano -- una sola vez por sesión y clave."""
        entry = self.get(key)
        if not entry or not entry.get("thumb_url") or self.thumbnail_path(entry):
            return
        with self._thumb_lock:
            if key in self._thumb_requested:
                return
            self._thumb_requested.add(key)
        self._pool.submit(self._download_thumbnail, key, entry["thumb_url"])

    def _download_thumbnail(self, key: str, url: str):
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
            name = hashlib.sha1(key.encode("utf-8")).hexdigest()[:20] + ".jpg"
            path = os.path.join(get_history_thumbnail_dir(), name)
            if not img.save(path, "JPG", THUMB_JPEG_QUALITY):
                raise OSError("no se pudo guardar")
            self._thumbnail_done.emit(key, name)
        except Exception as e:
            logger.debug(f"DownloadHistory: sin miniatura para {urlparse(url).netloc} ({e})")

    def _on_thumbnail_done(self, key: str, name: str):
        with self._thumb_lock:
            self._thumb_requested.discard(key)
        cur = self._db.execute("UPDATE entries SET thumb_file = ? WHERE key = ?", (name, key))
        self._db.commit()
        if cur.rowcount:
            self.entry_updated.emit(key)
        else:
            # La entrada se borró mientras se descargaba su miniatura.
            try:
                os.remove(os.path.join(get_history_thumbnail_dir(), name))
            except OSError:
                pass

    def forget_thumbnails(self):
        """Llamado al vaciar la caché de miniaturas desde Ajustes: los archivos ya se
        borraron; se permite volver a pedirlos cuando las tarjetas se muestren."""
        with self._thumb_lock:
            self._thumb_requested.clear()
        self.entries_changed.emit()


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
