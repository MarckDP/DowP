# src/core/setup/hf_auth.py
"""Cuenta de Hugging Face para los modelos con licencia restringida ("gated"), como
RMBG 2.0 de Bria AI.

Cómo funciona Hugging Face con estos modelos:
  1. La cuenta del usuario tiene que ACEPTAR la licencia en la página del modelo, una
     sola vez. Eso es un clic en la web: no se puede automatizar.
  2. Las descargas tienen que llevar un token de acceso de esa cuenta.
Respuestas: sin token o con token inválido -> 401; token válido pero sin la licencia
aceptada -> 403 (ambos con X-Error-Code: GatedRepo); con acceso -> el archivo.

El token se guarda en config.json ("huggingface_token"), igual que las claves de
Freesound/Pexels/Pixabay. No se redistribuyen los modelos: la licencia de Bria no lo
permite, por eso cada usuario los descarga con su propia cuenta.
"""
import re

import requests
from PySide6.QtCore import QCoreApplication

from core.logger.logger_manager import logger

TOKENS_URL = "https://huggingface.co/settings/tokens"
_WHOAMI_URL = "https://huggingface.co/api/whoami-v2"
_TIMEOUT = 12
_HF_URL_RE = re.compile(r"https://huggingface\.co/([^/]+/[^/]+)/(?:tree|blob|resolve)/([^/?#]+)/?([^?#]*)")

# Resultado de check_access()
ACCESS_OK = "ok"
ACCESS_NO_TOKEN = "no_token"
ACCESS_INVALID_TOKEN = "invalid_token"
ACCESS_NEEDS_LICENSE = "needs_license"
ACCESS_ERROR = "error"


# ── Token ────────────────────────────────────────────────────────────────────
def get_token() -> str:
    from core.utils.config_manager import get_config
    return (get_config().get("huggingface_token") or "").strip()


def get_username() -> str:
    from core.utils.config_manager import get_config
    return (get_config().get("huggingface_user") or "").strip()


def save_token(token: str, username: str = ""):
    from core.utils.config_manager import get_config, save_config
    cfg = get_config()
    cfg["huggingface_token"] = (token or "").strip()
    cfg["huggingface_user"] = (username or "").strip() if token else ""
    save_config(cfg)


def auth_headers(token: str | None = None) -> dict:
    token = get_token() if token is None else token
    return {"Authorization": f"Bearer {token}"} if token else {}


def validate_token(token: str) -> tuple[bool, str]:
    """(True, nombre de usuario) o (False, mensaje para el usuario)."""
    token = (token or "").strip()
    if not token:
        return False, QCoreApplication.translate("hf_auth", "Pega tu token de acceso.")
    try:
        r = requests.get(_WHOAMI_URL, headers=auth_headers(token), timeout=_TIMEOUT)
    except requests.RequestException as e:
        logger.warning(f"Hugging Face: no se pudo validar el token: {e}")
        return False, QCoreApplication.translate("hf_auth", "No se pudo conectar con Hugging Face. Revisa tu conexión.")
    if r.status_code == 200:
        try:
            name = r.json().get("name") or ""
        except ValueError:
            name = ""
        return True, name
    if r.status_code == 401:
        return False, QCoreApplication.translate("hf_auth", "Hugging Face no reconoce ese token. Revisa que lo copiaste completo.")
    return False, QCoreApplication.translate("hf_auth", "Hugging Face respondió con un error ({0}).").format(r.status_code)


# ── Direcciones del catálogo ─────────────────────────────────────────────────
def _parse(model_info: dict):
    m = _HF_URL_RE.match((model_info or {}).get("url", ""))
    if not m:
        return None
    repo, revision, subpath = m.group(1), m.group(2), m.group(3).strip("/")
    return repo, revision, subpath


def is_hf_gated(model_info: dict) -> bool:
    """Los modelos del catálogo cuya URL es una carpeta de Hugging Face (no un
    archivo directo): son los que necesitan cuenta."""
    url = (model_info or {}).get("url", "")
    return "huggingface.co" in url and "/resolve/" not in url and "?download=" not in url and _parse(model_info) is not None


def resolve_url(model_info: dict) -> str:
    """URL de descarga directa del archivo del modelo."""
    repo, revision, subpath = _parse(model_info)
    path = f"{subpath}/{model_info['file']}" if subpath else model_info["file"]
    return f"https://huggingface.co/{repo}/resolve/{revision}/{path}"


def file_page_url(model_info: dict) -> str:
    """Página del archivo en Hugging Face (con su botón de descarga)."""
    repo, revision, subpath = _parse(model_info)
    path = f"{subpath}/{model_info['file']}" if subpath else model_info["file"]
    return f"https://huggingface.co/{repo}/blob/{revision}/{path}"


def license_page_url(model_info: dict) -> str:
    """Página principal del modelo: ahí se acepta la licencia."""
    return f"https://huggingface.co/{_parse(model_info)[0]}"


# ── Acceso ───────────────────────────────────────────────────────────────────
def check_access(model_info: dict, token: str | None = None) -> str:
    """¿La cuenta conectada puede descargar este modelo? Una petición HEAD rápida,
    sin descargar nada."""
    token = get_token() if token is None else token
    try:
        r = requests.head(resolve_url(model_info), headers=auth_headers(token),
                          timeout=_TIMEOUT, allow_redirects=False)
    except requests.RequestException as e:
        logger.warning(f"Hugging Face: no se pudo comprobar el acceso: {e}")
        return ACCESS_ERROR
    if r.status_code in (200, 302, 303, 307, 308):
        return ACCESS_OK
    if r.status_code == 401:
        return ACCESS_INVALID_TOKEN if token else ACCESS_NO_TOKEN
    if r.status_code == 403:
        return ACCESS_NEEDS_LICENSE
    logger.warning(f"Hugging Face: respuesta inesperada {r.status_code} al comprobar {resolve_url(model_info)}")
    return ACCESS_ERROR
