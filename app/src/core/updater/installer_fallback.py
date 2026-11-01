# src/core/updater/installer_fallback.py
"""Respaldo del actualizador: si no se puede actualizar por chunks, baja el instalador
completo de la misma version (.exe, .dmg o .tar.gz segun el sistema).

El instalador se comprueba contra el sha256 que informa GitHub. Eso detecta una
descarga corrupta, pero no equivale a la firma del manifiesto: por eso nunca se
ejecuta en silencio, siempre se le muestra al usuario.
"""
import hashlib
import os
import platform
import re
import subprocess

import requests

from core.logger.logger_manager import logger

API_BASE = "https://api.github.com"
TIMEOUT = 30
BLOCK_SIZE = 1024 * 1024

_INSTALLER_PATTERNS = {
    "windows-x64": r"^DowP_Setup_.*\.exe$",
    "macos-arm64": r"-arm64\.dmg$",
    "macos-x64": r"-x64\.dmg$",
    "linux-x64": r"-linux-x64\.tar\.gz$",
}


class InstallerError(Exception):
    """No hay instalador para este sistema, o la descarga no es valida."""


def select_installer(assets: list, platform_key: str) -> dict | None:
    pattern = _INSTALLER_PATTERNS.get(platform_key)
    if not pattern:
        return None
    return next((a for a in assets if re.search(pattern, a.get("name", ""), re.IGNORECASE)), None)


def find_installer(repo: str, version: str, platform_key: str) -> dict:
    res = requests.get(f"{API_BASE}/repos/{repo}/releases/tags/v{version}", timeout=TIMEOUT)
    res.raise_for_status()
    asset = select_installer(res.json().get("assets", []), platform_key)
    if asset is None:
        raise InstallerError(f"La version {version} no trae instalador para {platform_key}.")
    return asset


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(BLOCK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_valid(path: str, asset: dict) -> bool:
    if os.path.getsize(path) != asset.get("size"):
        return False
    expected = asset.get("digest") or ""
    return not expected.startswith("sha256:") or _sha256(path) == expected.split(":", 1)[1].lower()


def download_installer(asset: dict, dest_dir: str, progress_callback=None) -> str:
    """Devuelve la ruta del instalador. Usa un .part para que un corte no deje un
    archivo a medias con el nombre final, y reutiliza uno anterior si sigue valido."""
    name = os.path.basename(asset["name"])  # el nombre viene de la red: nunca una ruta
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, name)
    if os.path.exists(dest) and _is_valid(dest, asset):
        return dest

    part = dest + ".part"
    completed = 0
    with requests.get(asset["browser_download_url"], stream=True, timeout=TIMEOUT) as res:
        res.raise_for_status()
        with open(part, "wb") as f:
            for block in res.iter_content(BLOCK_SIZE):
                f.write(block)
                completed += len(block)
                if progress_callback:
                    progress_callback(completed, asset.get("size") or 0)

    if not _is_valid(part, asset):
        os.remove(part)
        raise InstallerError(f"La descarga de {name} no coincide con la publicada.")
    os.replace(part, dest)
    logger.info(f"Updater: instalador descargado en {dest}.")
    return dest


def open_installer(path: str) -> None:
    """Windows ejecuta el setup y macOS monta el .dmg. En Linux se abre la carpeta,
    porque un .tar.gz hay que extraerlo a mano."""
    system = platform.system()
    if system == "Windows":
        os.startfile(path)
    elif system == "Darwin":
        subprocess.Popen(["open", path], start_new_session=True)
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)], start_new_session=True)
