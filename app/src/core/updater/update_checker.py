# src/core/updater/update_checker.py
"""Compara un manifiesto ya verificado contra la instalacion actual. Sin red
a proposito: recibe el manifiesto como dict, para poder probarse con uno
fabricado a mano sin tocar GitHub (ver tools/updater/ para como se genera uno
de verdad).

El diff se calcula por CHUNK (ver core.updater.chunking), no archivo por
archivo: el manifiesto agrupa los archivos en ~200 chunks estables por hash de
ruta, y si algun archivo de un chunk no coincide (o falta), el chunk entero se
marca para descargar. files_to_download sigue siendo un dict archivo->entry
(mismo formato que la v1 de este sistema) para que journal.py/swap_executor.py
no necesiten saber nada de chunks -- solo downloader.py necesita
chunks_to_download para saber que URLs bajar."""
import os
import re
import sys
from dataclasses import dataclass, field

from core.version import APP_VERSION, MIN_UPDATABLE_VERSION
from core.updater.hash_tree import hash_tree
from core.updater.platform_key import get_platform_key

SUPPORTED_FORMAT = 2

# Archivos que NO son de la app sino del instalador: Inno Setup deja su desinstalador
# en la misma carpeta que DowP.exe ({app}). No estan en el manifiesto (se publica desde
# app/dist/DowP), asi que sin esta excepcion el diff los trataba como sobrantes y el
# swap los BORRABA -- "Desinstalar DowP" dejaba de funcionar tras la primera
# actualizacion (verificado con un swap real sobre una instalacion 1.9.0).
_INSTALLER_OWNED = re.compile(r"^unins\d{3}\.(exe|dat|msg)$", re.IGNORECASE)


def _is_installer_owned(relpath: str) -> bool:
    return bool(_INSTALLER_OWNED.match(relpath))


@dataclass
class UpdateInfo:
    available: bool
    must_full_install: bool
    current_version: str
    remote_version: str
    platform_key: str
    files_to_download: dict = field(default_factory=dict)   # relpath -> {"hash", "size", "chunk"}
    chunks_to_download: dict = field(default_factory=dict)  # chunk_id -> {"hash", "url", "compressed_size"}
    download_size: int = 0
    extra_local_files: list = field(default_factory=list)


def _version_tuple(v: str) -> tuple:
    """"2.10.1" -> (2, 10, 1). Suficiente para el esquema X.Y.Z de este
    proyecto (ver core/version.py) -- no hace falta packaging.version para eso."""
    return tuple(int(p) for p in v.split("."))


def compute_diff(manifest: dict, install_dir: str | None = None,
                  current_version: str | None = None) -> UpdateInfo:
    """install_dir por defecto es la raiz de la instalacion congelada -- el mismo
    arbol que hashea tools/updater al publicar (ver
    launcher.install_dir_from_executable(): en Windows/Linux es la carpeta del
    .exe, en macOS es el .app completo, no Contents/MacOS) -- en modo fuente no
    hay arbol congelado que hashear, asi que hay que pasarlo a mano (por
    ejemplo, app/dist/DowP o app/dist/DowP.app, para probar contra un build
    real sin instalar nada)."""
    current_version = current_version or APP_VERSION
    remote_version = manifest.get("app_version", "0.0.0")

    unsupported_format = manifest.get("format") != SUPPORTED_FORMAT
    below_min = _version_tuple(current_version) < _version_tuple(
        manifest.get("min_updatable_version", MIN_UPDATABLE_VERSION)
    )
    must_full_install = unsupported_format or below_min

    if _version_tuple(remote_version) <= _version_tuple(current_version):
        return UpdateInfo(
            available=False, must_full_install=False,
            current_version=current_version, remote_version=remote_version,
            platform_key=get_platform_key(),
        )

    platform_key = get_platform_key()
    plat_data = manifest.get("platforms", {}).get(platform_key)

    if must_full_install or plat_data is None:
        return UpdateInfo(
            available=plat_data is not None, must_full_install=must_full_install,
            current_version=current_version, remote_version=remote_version,
            platform_key=platform_key,
        )

    if install_dir is None:
        if getattr(sys, "frozen", False):
            from core.updater.launcher import install_dir_from_executable
            install_dir = install_dir_from_executable(sys.executable)
        else:
            raise ValueError(
                "compute_diff necesita install_dir explicito en modo fuente "
                "(no hay arbol --onedir congelado que hashear)."
            )

    manifest_files = plat_data.get("files", {})
    manifest_chunks = plat_data.get("chunks", {})
    local_files = hash_tree(install_dir)

    # Agrupar los archivos del manifiesto por chunk (el campo "chunk" de cada
    # entrada es la fuente de verdad -- viene firmada, no hace falta
    # recalcularlo con chunk_id_for aunque daria lo mismo).
    relpaths_by_chunk: dict = {}
    for relpath, entry in manifest_files.items():
        relpaths_by_chunk.setdefault(entry["chunk"], []).append(relpath)

    files_to_download: dict = {}
    chunks_to_download: dict = {}
    download_size = 0

    for chunk_id, relpaths in relpaths_by_chunk.items():
        dirty = any(
            local_files.get(relpath) is None or local_files[relpath]["hash"] != manifest_files[relpath]["hash"]
            for relpath in relpaths
        )
        if not dirty:
            continue
        chunks_to_download[chunk_id] = manifest_chunks[chunk_id]
        download_size += manifest_chunks[chunk_id]["compressed_size"]
        for relpath in relpaths:
            entry = manifest_files[relpath]
            files_to_download[relpath] = {"hash": entry["hash"], "size": entry["size"], "chunk": chunk_id}

    extra_local_files = sorted(
        relpath for relpath in set(local_files) - set(manifest_files)
        if not _is_installer_owned(relpath)
    )

    return UpdateInfo(
        available=True, must_full_install=False,
        current_version=current_version, remote_version=remote_version,
        platform_key=platform_key, files_to_download=files_to_download,
        chunks_to_download=chunks_to_download,
        download_size=download_size, extra_local_files=extra_local_files,
    )
