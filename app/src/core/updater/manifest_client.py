# src/core/updater/manifest_client.py
"""Descarga y verifica el manifiesto firmado del release mas reciente.

Repo publico: ni la consulta a la API ni la descarga de los assets necesitan
token (mismo patron ya usado en core/setup/ffmpeg_setup.py contra la API de
GitHub para las releases de FFmpeg).
"""
import json

import requests
from Cryptodome.PublicKey import ECC
from Cryptodome.Signature import eddsa

from core.logger.logger_manager import logger
from core.updater.public_key import UPDATER_PUBLIC_KEY_PEM

API_BASE = "https://api.github.com"
TIMEOUT = 30


class ManifestVerificationError(Exception):
    """La firma del manifiesto no verifico contra la clave publica embebida.

    Fallo cerrado a proposito: un manifiesto sin verificar NUNCA debe tratarse
    como equivalente a "no hay actualizacion disponible" -- eso enmascararia
    un manifiesto corrupto o manipulado como un simple "estas al dia"."""


def _verify_signature(data: bytes, signature: bytes) -> bool:
    key = ECC.import_key(UPDATER_PUBLIC_KEY_PEM)
    verifier = eddsa.new(key, mode="rfc8032")
    try:
        verifier.verify(data, signature)
        return True
    except ValueError:
        return False


def _list_assets(repo: str, release_id: int) -> list:
    """Todos los assets de un release, paginando de a 100 -- nunca confiar en
    el campo "assets" embebido en la respuesta de _get_latest_release() para
    saber que esta ahi de verdad (ver tools/updater/github_release.py, mismo
    criterio del lado del publicador: esa lista no demostro ser confiable en
    un release con muchos assets)."""
    assets = []
    page = 1
    while True:
        res = requests.get(
            f"{API_BASE}/repos/{repo}/releases/{release_id}/assets",
            params={"per_page": 100, "page": page}, timeout=TIMEOUT,
        )
        res.raise_for_status()
        batch = res.json()
        if not batch:
            break
        assets.extend(batch)
        page += 1
    return assets


def _find_asset(repo: str, release: dict, name: str) -> dict | None:
    for asset in _list_assets(repo, release["id"]):
        if asset["name"] == name:
            return asset
    return None


def _get_latest_release(repo: str, channel: str) -> dict:
    """El release mas nuevo de `repo`, segun el canal.

    "stable" usa /releases/latest -- GitHub EXCLUYE ahi cualquier release marcado
    prerelease, por diseño de su API. "beta" en cambio lista los releases (sin ese
    filtro, mas nuevo primero) y toma el primero, prerelease o no -- es la unica
    forma de que un cliente en canal beta vea builds marcados prerelease en GitHub.

    Sin token en ningun caso (repo publico, mismo criterio que el resto de este
    archivo). Lanza requests.HTTPError si no hay ninguno (equivalente al 404 de
    /latest) para que el llamador lo trate igual en los dos canales."""
    if channel == "beta":
        res = requests.get(
            f"{API_BASE}/repos/{repo}/releases", params={"per_page": 1}, timeout=TIMEOUT
        )
        res.raise_for_status()
        releases = res.json()
        if not releases:
            # La peticion en si tuvo éxito (200, lista vacia) -- no hay un 404 natural
            # que relanzar como en /latest. UpdateCheckWorker atrapa esto igual con su
            # except Exception generico, tratandolo como "sin novedades".
            raise requests.HTTPError(f"Sin releases todavia en {repo} (canal beta).")
        return releases[0]

    res = requests.get(f"{API_BASE}/repos/{repo}/releases/latest", timeout=TIMEOUT)
    res.raise_for_status()
    return res.json()


def fetch_and_verify_manifest(repo: str, channel: str = "stable") -> dict:
    """Descarga manifest.json + manifest.json.sig del release mas nuevo de
    `repo` ("owner/nombre") segun `channel` ("stable" | "beta", ver
    _get_latest_release) y devuelve el manifiesto ya parseado, solo si la
    firma es valida.

    Lanza ManifestVerificationError si la firma no verifica, y
    requests.HTTPError / requests.ConnectionError si falla la red -- ninguno
    de los dos casos debe interpretarse silenciosamente como "sin novedades"."""
    release = _get_latest_release(repo, channel)

    manifest_asset = _find_asset(repo, release, "manifest.json")
    sig_asset = _find_asset(repo, release, "manifest.json.sig")
    if manifest_asset is None or sig_asset is None:
        raise ManifestVerificationError(
            f"El release {release.get('tag_name')} de {repo} no trae manifest.json/.sig todavia."
        )

    manifest_bytes = requests.get(manifest_asset["browser_download_url"], timeout=TIMEOUT).content
    signature = requests.get(sig_asset["browser_download_url"], timeout=TIMEOUT).content

    if not _verify_signature(manifest_bytes, signature):
        raise ManifestVerificationError(
            f"La firma de manifest.json ({release.get('tag_name')}) no es valida."
        )

    logger.info(f"Updater: manifiesto de {repo}@{release.get('tag_name')} verificado correctamente.")
    return json.loads(manifest_bytes)
