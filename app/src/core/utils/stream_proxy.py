# src/core/utils/stream_proxy.py
"""
Servidor HTTP proxy local para la vista previa del FragmentDialog.

Problema que resuelve:
  QMediaPlayer hace un GET directo a la URL del CDN sin las cabeceras
  que sitios como Bilibili requieren (Referer, Origin, User-Agent, cookies).
  El CDN responde 403. Este proxy intermedia con las cabeceras correctas.

Arquitectura:
  QMediaPlayer → http://127.0.0.1:{puerto}/stream?url=...&referer=...
               → (ThreadingHTTPServer en hilo daemon)
               → requests.get(cdn_url, headers=..., cookies=..., stream=True)
               → CDN

Puerto: dinámico en rango 9000-9100 (reservamos 7788 para Socket.IO futuro).
Ciclo de vida: singleton de módulo — arranca la primera vez y vive toda la sesión.
"""

import threading
import http.server
import http.cookiejar
import socket
import urllib.parse
from core.logger.logger_manager import logger

try:
    import requests as _requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

# ── Singleton ────────────────────────────────────────────────────────────────
_proxy_instance = None
_proxy_lock = threading.Lock()


def get_or_start_proxy():
    """
    Devuelve el singleton StreamProxyServer, arrancándolo si es necesario.
    Thread-safe.
    """
    global _proxy_instance
    with _proxy_lock:
        if _proxy_instance is None or not _proxy_instance.is_running():
            _proxy_instance = StreamProxyServer()
            _proxy_instance.start()
        return _proxy_instance


def abort_active_streams():
    """
    Aborta de inmediato cualquier streaming activo en el proxy local.
    Thread-safe.
    """
    global _proxy_instance
    with _proxy_lock:
        if _proxy_instance is not None and _proxy_instance.is_running():
            _proxy_instance.abort_active_streams()


def build_proxy_url(cdn_url: str, source_page_url: str) -> str:
    """
    Construye la URL local del proxy lista para pasar a QMediaPlayer.

    Args:
        cdn_url:        URL directa del CDN (stream de video).
        source_page_url: URL de la página original (ej. bilibili.com/video/...).
    Returns:
        http://127.0.0.1:{port}/stream?url=<encoded>&referer=<encoded>
    """
    server = get_or_start_proxy()
    if not cdn_url:
        return ""
    params = urllib.parse.urlencode({
        "url": cdn_url,
        "referer": source_page_url or "",
    })
    return f"http://127.0.0.1:{server.port}/stream?{params}"


# ── Cookie helpers ────────────────────────────────────────────────────────────

def _load_cookies_for_url(cdn_url: str) -> dict:
    """
    Carga solo las cookies aplicables al dominio de `cdn_url`, igual que un navegador.
    Usa MozillaCookieJar.add_cookie_header() que respeta dominio, path y flags
    de cada cookie — evita mandar cientos de cookies a CDNs que no las esperan.
    """
    try:
        from core.utils.config_manager import get_config
        config = get_config()
        mode = config.get("cookies_mode", "none")

        if mode == "file":
            cookie_file = config.get("cookies_file", "")
            if cookie_file:
                return _parse_cookies_for_url(cookie_file, cdn_url)

        return {}
    except Exception as e:
        logger.warning(f"StreamProxy: No se pudieron cargar las cookies: {e}")
        return {}


def _parse_cookies_for_url(file_path: str, cdn_url: str) -> dict:
    """
    Parsea el archivo cookies.txt y devuelve SOLO las cookies cuyo dominio
    y path coincidan con `cdn_url`. Usa urllib.request.Request como objeto
    auxiliar para que el jar aplique su lógica de matching nativa.
    """
    import urllib.request as _ureq
    try:
        jar = http.cookiejar.MozillaCookieJar(file_path)
        jar.load(ignore_discard=True, ignore_expires=True)

        # Simular una petición real al CDN para que el jar sólo inyecte
        # las cookies que apliquen a ese dominio/path.
        req = _ureq.Request(cdn_url)
        jar.add_cookie_header(req)

        cookie_header = req.get_header("Cookie") or ""
        if not cookie_header:
            logger.debug(f"StreamProxy: 0 cookies aplican para {cdn_url[:50]}...")
            return {}

        cookies = {}
        for part in cookie_header.split(";"):
            part = part.strip()
            if "=" in part:
                name, _, value = part.partition("=")
                cookies[name.strip()] = value.strip()

        logger.debug(f"StreamProxy: {len(cookies)} cookies para {cdn_url[:50]}...")
        return cookies
    except Exception as e:
        logger.warning(f"StreamProxy: Error filtrando cookies para URL: {e}")
        return {}


# ── Request handler ───────────────────────────────────────────────────────────

class ProxyRequestHandler(http.server.BaseHTTPRequestHandler):
    """
    Maneja GET /stream?url=...&referer=...

    Proxea el stream del CDN con las cabeceras correctas y pasa los
    Range headers de QMediaPlayer para que el seek funcione.
    """

    CHUNK_SIZE = 1024 * 64  # 64 KB por chunk

    def __init__(self, *args, **kwargs):
        self._aborted = False
        self._current_resp = None
        super().__init__(*args, **kwargs)

    def abort(self):
        """Corta la transmisión inmediatamente y cierra la conexión del cliente."""
        self._aborted = True
        resp = self._current_resp
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            self.connection.close()
        except Exception:
            pass

    # ── Silenciar los logs de acceso del servidor (muy verbosos con un player) ──
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if not _REQUESTS_OK:
            self._send_error(500, "requests no disponible")
            return

        server_instance = getattr(self.server, 'proxy_parent', None)
        if server_instance:
            server_instance.register_handler(self)

        try:
            # Parsear ruta y parámetros
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/stream":
                self._send_error(404, "Not found")
                return

            params = urllib.parse.parse_qs(parsed.query)
            cdn_url = params.get("url", [""])[0]
            referer = params.get("referer", [""])[0]

            if not cdn_url:
                self._send_error(400, "Falta parámetro 'url'")
                return

            if self._aborted:
                return

            logger.debug(f"StreamProxy: Proxeando -> {cdn_url[:80]}...")

            # Construir headers para el CDN
            headers = self._build_headers(referer)

            # Pasar Range header si QMediaPlayer lo envió (para seek)
            range_header = self.headers.get("Range")
            if range_header:
                headers["Range"] = range_header
                logger.debug(f"StreamProxy: Range request: {range_header}")

            # Cargar solo las cookies que apliquen al dominio del CDN
            cookies = _load_cookies_for_url(cdn_url)

            # Hacer la petición al CDN
            try:
                resp = _requests.get(
                    cdn_url,
                    headers=headers,
                    cookies=cookies if cookies else None,
                    stream=True,
                    timeout=20,
                    allow_redirects=True,
                )
                self._current_resp = resp
            except _requests.exceptions.Timeout:
                if not self._aborted:
                    logger.error("StreamProxy: Timeout conectando al CDN")
                    self._send_error(504, "Gateway Timeout")
                return
            except Exception as e:
                if not self._aborted:
                    logger.error(f"StreamProxy: Error al conectar al CDN: {e}")
                    self._send_error(502, f"Bad Gateway: {e}")
                return

            if self._aborted:
                try:
                    resp.close()
                except Exception:
                    pass
                return

            # Transmitir respuesta
            self._relay_response(resp)
        finally:
            if server_instance:
                server_instance.unregister_handler(self)

    # ── Helpers privados ──────────────────────────────────────────────────────

    def _build_headers(self, referer: str) -> dict:
        """Construye las cabeceras HTTP que los CDNs restrictivos esperan."""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
            "Accept-Encoding": "identity",   # Evitar compresión para streaming
            "Connection": "keep-alive",
        }
        if referer:
            headers["Referer"] = referer
            # Extraer Origin desde el Referer
            try:
                p = urllib.parse.urlparse(referer)
                if p.scheme and p.netloc:
                    headers["Origin"] = f"{p.scheme}://{p.netloc}"
            except Exception:
                pass
        return headers

    def _relay_response(self, resp):
        """Retransmite la respuesta del CDN a QMediaPlayer."""
        # Determinar código de estado a reenviar
        status = resp.status_code
        if status not in (200, 206):
            logger.warning(f"StreamProxy: CDN respondió {status}")

        # Cabeceras a reenviar
        forward_headers = {}
        for key in ("Content-Type", "Content-Length", "Content-Range",
                    "Accept-Ranges", "Last-Modified", "ETag"):
            val = resp.headers.get(key)
            if val:
                forward_headers[key] = val

        # Si no viene Content-Type, asumir video genérico
        if "Content-Type" not in forward_headers:
            forward_headers["Content-Type"] = "video/mp4"

        # Cerrar conexión de forma limpia en cada Range request
        if "Connection" not in forward_headers:
            forward_headers["Connection"] = "close"

        # Enviar encabezados de respuesta
        try:
            self.send_response(status)
            for k, v in forward_headers.items():
                self.send_header(k, v)
            self.end_headers()
        except Exception:
            return

        # Streaming del cuerpo
        try:
            for chunk in resp.iter_content(chunk_size=self.CHUNK_SIZE):
                if self._aborted:
                    break
                if chunk:
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError, OSError):
            # QMediaPlayer cerró la conexión (seek, pausa, cierre del diálogo)
            pass
        except Exception as e:
            if not self._aborted:
                logger.debug(f"StreamProxy: Streaming interrumpido: {e}")
        finally:
            try:
                resp.close()
            except Exception:
                pass

    def _send_error(self, code: int, message: str):
        try:
            self.send_response(code)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(message.encode())
        except Exception:
            pass


# ── Server class ──────────────────────────────────────────────────────────────

class StreamProxyServer:
    """
    Servidor HTTP local de proxy para streams de video.

    Usa ThreadingHTTPServer para manejar múltiples peticiones simultáneas
    (el QMediaPlayer puede abrir varias conexiones para buffering + Range).
    """

    PORT_RANGE_START = 9000
    PORT_RANGE_END   = 9100

    def __init__(self):
        self.port = self._find_free_port()
        self._server = None
        self._thread = None
        self._running = False
        self._active_handlers = set()
        self._handlers_lock = threading.Lock()

    def register_handler(self, handler):
        with self._handlers_lock:
            self._active_handlers.add(handler)

    def unregister_handler(self, handler):
        with self._handlers_lock:
            self._active_handlers.discard(handler)

    def abort_active_streams(self):
        """Interrumpe inmediatamente todas las transmisiones activas y cierra sus sockets."""
        with self._handlers_lock:
            handlers = list(self._active_handlers)
            self._active_handlers.clear()
        for h in handlers:
            try:
                h.abort()
            except Exception:
                pass

    def _find_free_port(self) -> int:
        """Busca el primer puerto libre en el rango definido."""
        for port in range(self.PORT_RANGE_START, self.PORT_RANGE_END):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(("127.0.0.1", port))
                    return port
            except OSError:
                continue
        raise RuntimeError(
            f"StreamProxy: No hay puertos libres en el rango "
            f"{self.PORT_RANGE_START}-{self.PORT_RANGE_END}"
        )

    def start(self):
        """Arranca el servidor en un hilo daemon."""
        if self._running:
            return

        try:
            self._server = http.server.ThreadingHTTPServer(
                ("127.0.0.1", self.port),
                ProxyRequestHandler,
            )
            self._server.proxy_parent = self
            self._thread = threading.Thread(
                target=self._server.serve_forever,
                daemon=True,
                name="StreamProxyServer",
            )
            self._thread.start()
            self._running = True
            logger.info(f"StreamProxy: Servidor iniciado en http://127.0.0.1:{self.port}")
        except Exception as e:
            logger.error(f"StreamProxy: Error al iniciar el servidor: {e}")
            self._running = False

    def stop(self):
        """Detiene el servidor (libera el puerto)."""
        if self._server and self._running:
            self.abort_active_streams()
            self._server.shutdown()
            self._running = False
            logger.info("StreamProxy: Servidor detenido")

    def is_running(self) -> bool:
        return self._running and (self._thread is not None) and self._thread.is_alive()
