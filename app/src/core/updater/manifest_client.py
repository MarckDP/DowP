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
from core.updater.update_checker import is_prerelease_version, version_key

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
    el campo "assets" embebido en la respuesta de la API de releases para
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


def _manifest_assets(repo: str, release: dict) -> tuple[dict, dict] | None:
    """(manifest.json, manifest.json.sig) del release, o None si no los trae (por
    ejemplo, una beta publicada solo con instaladores). Una sola pasada por los
    assets: antes se listaban dos veces, y con ~400 assets eso eran ~10 llamadas
    a la API (el limite sin token es de 60 por hora)."""
    by_name = {asset["name"]: asset for asset in _list_assets(repo, release["id"])}
    manifest, sig = by_name.get("manifest.json"), by_name.get("manifest.json.sig")
    if manifest is None or sig is None:
        return None
    return manifest, sig


# Cuantos releases se prueban como mucho buscando uno con manifiesto.
_MAX_CANDIDATES = 5


def _list_releases(repo: str) -> list:
    """Releases publicados (sin borradores), de la version mas alta a la mas baja
    segun su etiqueta -- no por fecha: una estable publicada despues de una beta
    mas alta no debe pasar por delante de ella en el canal beta, ni al reves."""
    res = requests.get(f"{API_BASE}/repos/{repo}/releases", params={"per_page": 30}, timeout=TIMEOUT)
    res.raise_for_status()
    releases = [r for r in res.json() if not r.get("draft")]
    releases.sort(key=lambda r: version_key(r.get("tag_name", "")), reverse=True)
    return releases


def _candidate_releases(repo: str, channel: str):
    """Releases a probar, en orden, segun el canal.

    "stable": primero /releases/latest (GitHub EXCLUYE ahi los marcados prerelease),
    que es el caso normal y cuesta una sola llamada. Solo si ese no sirve (no trae
    manifiesto, o su etiqueta es una beta subida sin marcar como prerelease) se
    listan los releases y se prueban las estables de version mas alta.

    "beta": la version mas alta de todas, estable o prerelease. Si no trae
    manifiesto (una beta solo con instaladores), la siguiente: asi el canal beta
    nunca se queda sin las estables.

    Sin token en ningun caso (repo publico)."""
    tried = set()
    if channel != "beta":
        res = requests.get(f"{API_BASE}/repos/{repo}/releases/latest", timeout=TIMEOUT)
        if res.status_code != 404:
            res.raise_for_status()
            latest = res.json()
            if not is_prerelease_version(latest.get("tag_name", "")):
                tried.add(latest["id"])
                yield latest

    count = len(tried)
    for release in _list_releases(repo):
        if count >= _MAX_CANDIDATES:
            return
        if release["id"] in tried:
            continue
        if channel != "beta" and (release.get("prerelease")
                                  or is_prerelease_version(release.get("tag_name", ""))):
            continue
        count += 1
        yield release


def fetch_and_verify_manifest(repo: str, channel: str = "stable") -> dict:
    """Descarga manifest.json + manifest.json.sig del release que corresponde a
    `repo` ("owner/nombre") segun `channel` ("stable" | "beta", ver
    _candidate_releases) y devuelve el manifiesto ya parseado, solo si la
    firma es valida.

    Lanza ManifestVerificationError si la firma no verifica o si ningun release
    trae manifiesto, y requests.HTTPError / requests.ConnectionError si falla la
    red -- ninguno de los casos debe interpretarse silenciosamente como "sin
    novedades". Una firma invalida corta la busqueda: nunca se cae a un release
    mas viejo por eso."""
    release = None
    assets = None
    for candidate in _candidate_releases(repo, channel):
        assets = _manifest_assets(repo, candidate)
        if assets is not None:
            release = candidate
            break
        logger.info(f"Updater: {candidate.get('tag_name')} no trae manifiesto (solo instaladores); se prueba el siguiente.")
    if release is None:
        raise ManifestVerificationError(f"Ningun release de {repo} trae manifest.json/.sig (canal {channel}).")
    manifest_asset, sig_asset = assets

    manifest_bytes = requests.get(manifest_asset["browser_download_url"], timeout=TIMEOUT).content
    signature = requests.get(sig_asset["browser_download_url"], timeout=TIMEOUT).content

    if not _verify_signature(manifest_bytes, signature):
        raise ManifestVerificationError(
            f"La firma de manifest.json ({release.get('tag_name')}) no es valida."
        )

    logger.info(f"Updater: manifiesto de {repo}@{release.get('tag_name')} verificado correctamente.")
    return json.loads(manifest_bytes)
