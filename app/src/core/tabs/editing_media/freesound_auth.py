# src/core/tabs/editing_media/freesound_auth.py
"""
Módulo de autenticación OAuth2 para Freesound.
Maneja el flujo completo: abrir navegador → capturar callback → intercambiar tokens.
"""
import base64
import time
import threading
import webbrowser
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from PySide6.QtCore import QObject, Signal

from core.logger.logger_manager import logger
from PySide6.QtCore import QCoreApplication

# ─── Credenciales de la App (ofuscadas) ─────────────────────────────────────
# Estas identifican a DowP como aplicación ante Freesound.
# NO son credenciales de usuario — cada usuario se autentica por separado vía OAuth2.
_KEY = 0x5A  # XOR key para ofuscación básica

def _obfuscate(plain: str) -> str:
    """Ofusca un string con XOR + base64 (para no tener secrets en texto plano)."""
    xored = bytes(b ^ _KEY for b in plain.encode("utf-8"))
    return base64.b64encode(xored).decode("utf-8")

def _deobfuscate(encoded: str) -> str:
    """Revierte la ofuscación."""
    xored = base64.b64decode(encoded.encode("utf-8"))
    return bytes(b ^ _KEY for b in xored).decode("utf-8")

# Pre-computados con _obfuscate():
_CLIENT_ID_OBF = _obfuscate("KAPdvIqXPkmyuwMseeK8")
_CLIENT_SECRET_OBF = _obfuscate("Cj5vkSMJISSSp2auOIeW9s6FyPoOVd2kDV9UNCrb")

def _get_client_id() -> str:
    return _deobfuscate(_CLIENT_ID_OBF)

def _get_client_secret() -> str:
    return _deobfuscate(_CLIENT_SECRET_OBF)


# ─── Constantes OAuth2 ──────────────────────────────────────────────────────
REDIRECT_PORT = 29170
REDIRECT_URI = f"http://127.0.0.1:{REDIRECT_PORT}/callback"
AUTHORIZE_URL = "https://freesound.org/apiv2/oauth2/authorize/"
TOKEN_URL = "https://freesound.org/apiv2/oauth2/access_token/"
ME_URL = "https://freesound.org/apiv2/me/"


# ─── Callback HTTP Server ───────────────────────────────────────────────────
class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Maneja el redirect de Freesound capturando el authorization code."""

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == "/callback":
            if "code" in params:
                self.server.auth_code = params["code"][0]
                self.server.auth_error = None
                self._send_success_page()
            elif "error" in params:
                self.server.auth_code = None
                self.server.auth_error = params.get("error", ["unknown"])[0]
                self._send_error_page()
            else:
                self.server.auth_code = None
                self.server.auth_error = "no_code_received"
                self._send_error_page()
        else:
            self.send_response(404)
            self.end_headers()

    def _send_success_page(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        html = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>DowP - Autorización Exitosa</title>
<style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           background: #121212; color: #e0e0e0; display: flex; align-items: center;
           justify-content: center; min-height: 100vh; margin: 0; }
    .card { text-align: center; background: #1e1e1e; padding: 40px 60px;
            border-radius: 16px; border: 1px solid #2d2d2d; }
    h1 { color: #B9E640; font-size: 24px; margin-bottom: 8px; }
    p { color: #aaa; font-size: 14px; }
</style></head>
<body><div class="card">
    <h1>✅ Autorización exitosa</h1>
    <p>Puedes cerrar esta pestaña y volver a DowP.</p>
</div></body></html>"""
        self.wfile.write(html.encode("utf-8"))

    def _send_error_page(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        html = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>DowP - Error</title>
<style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           background: #121212; color: #e0e0e0; display: flex; align-items: center;
           justify-content: center; min-height: 100vh; margin: 0; }
    .card { text-align: center; background: #1e1e1e; padding: 40px 60px;
            border-radius: 16px; border: 1px solid #2d2d2d; }
    h1 { color: #e74c3c; font-size: 24px; margin-bottom: 8px; }
    p { color: #aaa; font-size: 14px; }
</style></head>
<body><div class="card">
    <h1>❌ Autorización denegada</h1>
    <p>No se concedió acceso. Puedes cerrar esta pestaña.</p>
</div></body></html>"""
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, format, *args):
        """Silenciar logs del servidor HTTP."""
        logger.debug(f"FreesoundAuth callback: {args}")


# ─── Señales Qt para comunicar resultado al hilo principal ───────────────────
class FreesoundAuthSignals(QObject):
    """Señales para comunicar el resultado del flujo OAuth2 al thread principal."""
    auth_success = Signal(dict)   # {access_token, refresh_token, expires_at, username}
    auth_error = Signal(str)      # mensaje de error


# ─── Clase principal de autenticación ────────────────────────────────────────
class FreesoundAuth:
    """Gestiona el flujo OAuth2 completo con Freesound."""

    def __init__(self):
        self.signals = FreesoundAuthSignals()
        self._server = None
        self._server_thread = None

    def start_oauth_flow(self):
        """Inicia el flujo OAuth2: abre navegador y espera callback en localhost."""
        # Iniciar servidor local en un thread para no bloquear la UI
        self._server_thread = threading.Thread(target=self._run_callback_server, daemon=True)
        self._server_thread.start()

        # Abrir navegador del sistema con la URL de autorización
        client_id = _get_client_id()
        auth_url = f"{AUTHORIZE_URL}?client_id={client_id}&response_type=code"
        logger.info(f"FreesoundAuth: Abriendo navegador para autorización OAuth2")
        webbrowser.open(auth_url)

    def _run_callback_server(self):
        """Levanta un servidor HTTP temporal para capturar el callback de OAuth2."""
        try:
            self._server = HTTPServer(("127.0.0.1", REDIRECT_PORT), _OAuthCallbackHandler)
            self._server.auth_code = None
            self._server.auth_error = None
            self._server.timeout = 120  # Timeout de 2 minutos esperando al usuario

            logger.info(f"FreesoundAuth: Servidor callback escuchando en {REDIRECT_URI}")

            # Esperar UNA sola request (el callback de Freesound)
            self._server.handle_request()

            if self._server.auth_code:
                logger.info("FreesoundAuth: Authorization code recibido, intercambiando por token...")
                self._exchange_code(self._server.auth_code)
            elif self._server.auth_error:
                logger.warning(f"FreesoundAuth: Autorización denegada: {self._server.auth_error}")
                self.signals.auth_error.emit(QCoreApplication.translate("FreesoundAuth", "Acceso denegado por el usuario: {0}").format(self._server.auth_error))
            else:
                logger.warning("FreesoundAuth: No se recibió código de autorización (timeout)")
                self.signals.auth_error.emit(QCoreApplication.translate("FreesoundAuth", "Tiempo de espera agotado. Intente de nuevo."))

        except OSError as e:
            logger.error(f"FreesoundAuth: Error al iniciar servidor callback: {e}")
            self.signals.auth_error.emit(
                QCoreApplication.translate(
                    "FreesoundAuth",
                    "No se pudo iniciar el servidor local (puerto {0} en uso). "
                    "Cierre otras instancias de DowP e intente de nuevo."
                ).format(REDIRECT_PORT)
            )
        except Exception as e:
            logger.error(f"FreesoundAuth: Error inesperado: {e}")
            self.signals.auth_error.emit(f"Error inesperado: {e}")
        finally:
            if self._server:
                try:
                    self._server.server_close()
                except Exception:
                    pass
                self._server = None

    def _exchange_code(self, code: str):
        """Intercambia el authorization code por access_token + refresh_token."""
        try:
            response = requests.post(TOKEN_URL, data={
                "client_id": _get_client_id(),
                "client_secret": _get_client_secret(),
                "grant_type": "authorization_code",
                "code": code,
            }, timeout=15)

            if response.status_code != 200:
                error_detail = response.text
                logger.error(f"FreesoundAuth: Error en token exchange: {response.status_code} - {error_detail}")
                self.signals.auth_error.emit(QCoreApplication.translate("FreesoundAuth", "Error al obtener token: {0}").format(error_detail))
                return

            data = response.json()
            access_token = data.get("access_token", "")
            refresh_token = data.get("refresh_token", "")
            expires_in = data.get("expires_in", 86399)
            expires_at = time.time() + expires_in

            # Obtener username del usuario autenticado
            username = self._fetch_username(access_token)

            auth_data = {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": expires_at,
                "username": username,
            }
            logger.info(f"FreesoundAuth: Autenticación exitosa para usuario '{username}'")
            self.signals.auth_success.emit(auth_data)

        except requests.exceptions.RequestException as e:
            logger.error(f"FreesoundAuth: Error de red en token exchange: {e}")
            self.signals.auth_error.emit(QCoreApplication.translate("FreesoundAuth", "Error de red al obtener token: {0}").format(e))

    def _fetch_username(self, access_token: str) -> str:
        """Obtiene el nombre de usuario del usuario autenticado via /me/."""
        try:
            response = requests.get(ME_URL, headers={
                "Authorization": f"Bearer {access_token}"
            }, timeout=10)
            if response.status_code == 200:
                return response.json().get("username", "usuario")
        except Exception as e:
            logger.warning(f"FreesoundAuth: No se pudo obtener username: {e}")
        return "usuario"

    def cancel(self):
        """Cancela el flujo de autenticación cerrando el servidor local."""
        if self._server:
            try:
                self._server.server_close()
            except Exception:
                pass

    # ─── Métodos estáticos para manejo de tokens ────────────────────────────

    @staticmethod
    def is_token_expired(auth_data: dict) -> bool:
        """Verifica si el access token ha expirado."""
        expires_at = auth_data.get("expires_at", 0)
        # Considerar expirado 5 minutos antes para evitar edge cases
        return time.time() >= (expires_at - 300)

    @staticmethod
    def refresh_access_token(auth_data: dict) -> dict | None:
        """Renueva el access_token usando el refresh_token.
        
        Returns:
            dict actualizado con nuevo access_token, refresh_token y expires_at,
            o None si el refresh falla.
        """
        refresh_token = auth_data.get("refresh_token", "")
        if not refresh_token:
            logger.warning("FreesoundAuth: No hay refresh_token disponible")
            return None

        try:
            response = requests.post(TOKEN_URL, data={
                "client_id": _get_client_id(),
                "client_secret": _get_client_secret(),
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }, timeout=15)

            if response.status_code != 200:
                logger.error(f"FreesoundAuth: Error en refresh: {response.status_code} - {response.text}")
                return None

            data = response.json()
            new_auth = dict(auth_data)  # Preservar username y otros campos
            new_auth["access_token"] = data.get("access_token", "")
            new_auth["refresh_token"] = data.get("refresh_token", refresh_token)
            new_auth["expires_at"] = time.time() + data.get("expires_in", 86399)

            logger.info("FreesoundAuth: Token refrescado exitosamente")
            return new_auth

        except requests.exceptions.RequestException as e:
            logger.error(f"FreesoundAuth: Error de red al refrescar token: {e}")
            return None

    @staticmethod
    def get_valid_token(auth_data: dict, save_callback=None) -> str | None:
        """Obtiene un token válido, refrescando automáticamente si es necesario.
        
        Args:
            auth_data: Dict con los datos de autenticación OAuth2.
            save_callback: Función opcional para persistir los tokens actualizados.
            
        Returns:
            El access_token válido, o None si no hay sesión o el refresh falla.
        """
        if not auth_data or not auth_data.get("access_token"):
            return None

        if not FreesoundAuth.is_token_expired(auth_data):
            return auth_data["access_token"]

        # Token expirado — intentar refresh
        logger.info("FreesoundAuth: Token expirado, intentando refresh...")
        refreshed = FreesoundAuth.refresh_access_token(auth_data)
        if refreshed:
            # Actualizar el dict in-place para que el caller vea los cambios
            auth_data.update(refreshed)
            if save_callback:
                save_callback()
            return refreshed["access_token"]

        # Refresh falló — el usuario debe re-autenticarse
        logger.warning("FreesoundAuth: Refresh falló, se requiere re-autenticación")
        return None
