# src/core/utils/http_download.py
"""Descarga HTTP común para dependencias y modelos de IA (NO para yt-dlp ni medios web).

Antes cada setup (yt-dlp, FFmpeg, Deno, Ghostscript, vtracer, modelos...) tenía su
propia copia del mismo bucle `requests.get(...).iter_content(8192)`, sin defensa
contra una red mala: la descarga iba bien o mal según el servidor de GitHub/Hugging
Face que le tocara a cada usuario, y cuando le tocaba uno malo se arrastraba hasta el
final. Concretamente, el bucle viejo:

  - No detectaba una conexión que se arrastra: el timeout de requests solo salta con
    N segundos SIN recibir nada, así que una conexión a 20 KB/s nunca lo dispara.
  - Ante un corte fallaba, o reintentaba desde el byte 0.
  - Usaba una sola conexión, que con latencia alta o pérdida de paquetes rinde muy por
    debajo de la línea.

Aquí, en cambio:

  - Cada conexión mide su velocidad por ventanas de STALL_WINDOW segundos; si queda por
    debajo de STALL_MIN_SPEED, se corta y se reconecta pidiendo con `Range` desde el
    byte donde iba (muchas veces la reconexión cae en otro servidor que va rápido).
  - Un corte también se retoma desde donde iba, no desde cero.
  - Los archivos grandes se bajan en PARALLEL_CONNECTIONS trozos en paralelo, si el
    servidor acepta `Range` (GitHub y Hugging Face lo aceptan).
  - Cada descarga deja una línea en el log con servidor, tamaño, tiempo y velocidad,
    para poder diagnosticar con el log de otro usuario.

El progreso se reporta siempre desde el hilo que llamó a download_file(), nunca desde
los hilos internos, y solo cuando cambia el porcentaje entero.
"""
import http.client
import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from urllib.parse import urlparse

import requests
import urllib3
from requests.adapters import HTTPAdapter

from core.logger.logger_manager import logger

CHUNK_SIZE = 256 * 1024
CONNECT_TIMEOUT = 15
READ_TIMEOUT = 30

# Una conexión que durante STALL_WINDOW segundos recibe menos de STALL_MIN_SPEED se da
# por atascada y se reconecta. El umbral es bajo a propósito: con una línea lenta de
# verdad, reconectar no la acelera, pero tampoco la rompe (se retoma donde iba).
STALL_WINDOW = 15
STALL_MIN_SPEED = 32 * 1024

# Intentos seguidos SIN recibir un solo byte antes de rendirse. Una reconexión que sí
# recibió datos (aunque luego se atascara) no cuenta: la descarga avanza.
MAX_EMPTY_ATTEMPTS = 6

PARALLEL_MIN_SIZE = 16 * 1024 * 1024
PARALLEL_CONNECTIONS = 4

PROGRESS_POLL_S = 0.25


class DownloadError(Exception):
    pass


class _Stalled(Exception):
    pass


class _RangeIgnored(DownloadError):
    """El servidor contestó el archivo entero a una petición con `Range`: retomar
    escribiría datos en el lugar equivocado, así que no se reintenta."""


class _State:
    """Contadores compartidos entre los hilos de una misma descarga."""

    def __init__(self):
        self._lock = threading.Lock()
        self.done = 0
        self.reconnects = 0
        self.cancelled = False

    def add(self, n: int):
        with self._lock:
            self.done += n

    def reconnected(self):
        with self._lock:
            self.reconnects += 1


def _is_fatal_http(e) -> bool:
    """4xx (salvo 408/429) no se arregla reintentando: el enlace está mal o ya no existe."""
    resp = getattr(e, "response", None)
    code = getattr(resp, "status_code", None)
    return code is not None and 400 <= code < 500 and code not in (408, 429)


def _iter_body(response):
    """Trozos del cuerpo tal como llegan de la red. iter_content(N) espera a juntar N
    bytes antes de devolver nada, así que con una conexión casi parada (1 KB/s) tardaría
    minutos en entregar el primer trozo y la detección de atascos no llegaría a medir.
    read1() devuelve lo que haya disponible (urllib3 2.x); si no existe, iter_content."""
    read1 = getattr(response.raw, "read1", None)
    if read1 is None:
        yield from response.iter_content(chunk_size=CHUNK_SIZE)
        return
    while True:
        chunk = read1(CHUNK_SIZE)
        if not chunk:
            return
        yield chunk


def _parse_content_range_total(value: str):
    """'bytes 0-99/1234' -> 1234; None si el total no viene ('*') o no se entiende."""
    try:
        total = value.rsplit("/", 1)[1].strip()
        return int(total) if total != "*" else None
    except (IndexError, ValueError):
        return None


def _new_session(headers, pool_size: int) -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = "DowP2"
    # Sin compresión: con gzip, los bytes que entrega iter_content no coinciden con
    # los offsets de `Range` y retomar escribiría en el lugar equivocado.
    session.headers["Accept-Encoding"] = "identity"
    if headers:
        session.headers.update(headers)
    adapter = HTTPAdapter(pool_connections=pool_size, pool_maxsize=pool_size)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _fetch_range(session, url, path, start, end, state, ranges_ok, first_response=None):
    """Baja los bytes [start, end] (end inclusivo; None = hasta el final) a `path`,
    que ya existe. Reconecta si la conexión se corta o se atasca, retomando con
    `Range` desde donde iba (o desde `start` si el servidor no acepta rangos).
    Devuelve la posición final (= bytes escritos hasta ahí, contando desde 0)."""
    pos = start
    empty_attempts = 0
    response = first_response

    while True:
        if state.cancelled or (end is not None and pos > end):
            return pos
        received = 0
        try:
            if response is None:
                req_headers = {}
                if ranges_ok and (pos > 0 or end is not None):
                    req_headers["Range"] = f"bytes={pos}-{'' if end is None else end}"
                # Siempre la URL original, no la redirigida: los enlaces firmados de
                # GitHub/Hugging Face caducan, y el original da uno nuevo en cada intento.
                response = session.get(url, headers=req_headers, stream=True,
                                       timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
                response.raise_for_status()
                if req_headers and response.status_code != 206:
                    raise _RangeIgnored(f"El servidor ignoró el rango pedido (HTTP {response.status_code}).")

            with response, open(path, "r+b") as f:
                f.seek(pos)
                window_start = time.monotonic()
                window_bytes = 0
                for chunk in _iter_body(response):
                    if state.cancelled:
                        return pos
                    if not chunk:
                        continue
                    if end is not None and pos + len(chunk) > end + 1:
                        chunk = chunk[:end + 1 - pos]
                    f.write(chunk)
                    pos += len(chunk)
                    received += len(chunk)
                    window_bytes += len(chunk)
                    state.add(len(chunk))
                    if end is not None and pos > end:
                        break
                    now = time.monotonic()
                    elapsed = now - window_start
                    if elapsed >= STALL_WINDOW:
                        if window_bytes / elapsed < STALL_MIN_SPEED:
                            raise _Stalled(f"{window_bytes / elapsed / 1024:.0f} KB/s")
                        window_start, window_bytes = now, 0
            response = None

            if end is None or pos > end:
                return pos
            raise DownloadError("La conexión terminó antes de tiempo.")

        except (_Stalled, DownloadError, requests.RequestException, urllib3.exceptions.HTTPError,
                http.client.HTTPException, OSError) as e:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
                response = None
            if state.cancelled:
                return pos
            if isinstance(e, _RangeIgnored) or _is_fatal_http(e):
                raise
            empty_attempts = 0 if received else empty_attempts + 1
            if empty_attempts >= MAX_EMPTY_ATTEMPTS:
                raise DownloadError(f"No se pudo descargar tras {MAX_EMPTY_ATTEMPTS} intentos: {e}") from e
            if not ranges_ok:
                # Sin `Range` no hay forma de retomar: se vuelve a empezar el trozo.
                state.add(-(pos - start))
                pos = start
            state.reconnected()
            reason = "conexión lenta" if isinstance(e, _Stalled) else "conexión cortada"
            logger.warning(f"Descarga de {urlparse(url).netloc}: {reason} ({e}); "
                           f"reconectando desde el byte {pos}.")
            time.sleep(min(2 * max(empty_attempts, 1), 10))


def download_file(url: str, dest_path: str, progress_callback=None, progress_range=(0, 100),
                  headers=None, connections: int = PARALLEL_CONNECTIONS) -> int:
    """Descarga `url` a `dest_path` (lo crea o sobrescribe). Devuelve el tamaño bajado.

    `progress_callback(pct)` recibe enteros dentro de `progress_range` -- sirve para que
    una descarga ocupe solo un tramo de la barra cuando es una fase de algo más grande
    (ej. el motor de reescalado + sus modelos extra). Solo se llama si el servidor
    informa el tamaño, y solo cuando el porcentaje cambia.

    Lanza DownloadError / requests.RequestException si falla; en ese caso borra lo que
    haya quedado a medias en `dest_path`."""
    host = urlparse(url).netloc
    name = os.path.basename(urlparse(url).path) or url
    start_pct, end_pct = progress_range
    state = _State()
    t0 = time.monotonic()
    session = _new_session(headers, max(1, connections))

    try:
        # Una sola petición para saber el tamaño y si acepta rangos: pedir "bytes=0-"
        # responde 206 + Content-Range si los acepta, o 200 con el archivo entero si no.
        # La respuesta se reaprovecha como el primer trozo de la descarga.
        for attempt in range(1, 4):
            try:
                probe = session.get(url, headers={"Range": "bytes=0-"}, stream=True,
                                    timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
                probe.raise_for_status()
                break
            except requests.RequestException as e:
                if attempt == 3 or _is_fatal_http(e):
                    raise
                logger.warning(f"Descarga de {host}: no se pudo conectar ({e}); reintentando.")
                time.sleep(2 * attempt)
        if probe.status_code == 206:
            ranges_ok = True
            total = _parse_content_range_total(probe.headers.get("Content-Range", ""))
        else:
            ranges_ok = False
            total = int(probe.headers.get("Content-Length", 0)) or None
        final_host = urlparse(probe.url).netloc

        os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
        with open(dest_path, "wb") as f:
            if total:
                f.truncate(total)

        n = connections if (ranges_ok and total and total >= PARALLEL_MIN_SIZE) else 1
        if n > 1:
            size = total // n
            segments = [(i * size, total - 1 if i == n - 1 else (i + 1) * size - 1) for i in range(n)]
        else:
            # Con el tamaño conocido se pide hasta el último byte: si la conexión se
            # cierra antes, se detecta y se retoma en vez de dar el archivo por bueno.
            segments = [(0, total - 1 if total else None)]

        with ThreadPoolExecutor(max_workers=n, thread_name_prefix="dl") as pool:
            futures = [
                # El primer trozo reaprovecha la respuesta de sondeo; los demás abren
                # su propia conexión.
                pool.submit(_fetch_range, session, url, dest_path, s, e, state, ranges_ok,
                            probe if i == 0 else None)
                for i, (s, e) in enumerate(segments)
            ]
            last_pct = None
            try:
                while True:
                    done, pending = wait(futures, timeout=PROGRESS_POLL_S)
                    for fut in done:
                        if fut.exception() is not None:
                            raise fut.exception()
                    if progress_callback and total:
                        pct = start_pct + int(min(state.done, total) / total * (end_pct - start_pct))
                        if pct != last_pct:
                            last_pct = pct
                            progress_callback(pct)
                    if not pending:
                        break
            except BaseException:
                state.cancelled = True
                raise
            final_pos = futures[0].result()

        if total is None:
            with open(dest_path, "r+b") as f:
                f.truncate(final_pos)
        size = os.path.getsize(dest_path)
        if total is not None and size != total:
            raise DownloadError(f"Tamaño incorrecto: {size} de {total} bytes.")

        secs = max(time.monotonic() - t0, 0.001)
        logger.info(f"Descarga OK: {name} desde {final_host or host} -- {size / 1e6:.1f} MB en "
                    f"{secs:.1f} s ({size / secs / 1e6:.2f} MB/s), {n} conexión(es), "
                    f"{state.reconnects} reconexión(es).")
        return size

    except BaseException as e:
        secs = time.monotonic() - t0
        logger.error(f"Descarga FALLIDA: {name} desde {host} tras {secs:.1f} s "
                     f"({state.done / 1e6:.1f} MB bajados, {state.reconnects} reconexión(es)): {e}")
        try:
            if os.path.exists(dest_path):
                os.remove(dest_path)
        except OSError:
            pass
        raise
    finally:
        session.close()


def download_bytes(url: str, headers=None) -> bytes:
    """download_file() para archivos pequeños que se procesan en memoria (ej. las
    wheels de PyPI del plugin WPC): mismas reconexiones y reintentos, sin dejar nada
    en disco."""
    fd, tmp_path = tempfile.mkstemp(prefix="dowp_dl_")
    os.close(fd)
    try:
        download_file(url, tmp_path, headers=headers)
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
