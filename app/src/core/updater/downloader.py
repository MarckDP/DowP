# src/core/updater/downloader.py
"""Descarga y extrae a un staging local los chunks que update_checker
determino que hacen falta. No aplica nada sobre la instalacion real -- eso es
el helper de swap (journal.py + swap_executor.py).

Cada chunk es un tar comprimido con zstd (ver tools/updater/objectstore.py)
con un miembro POR CONTENIDO UNICO, nombrado por su hash (no por ruta) -- el
mismo contenido puede corresponder a varias rutas locales distintas (symlinks
Frameworks/Resources en macOS, ver ACTUALIZACIONES.md). Se descarga y
descomprime en streaming (nunca se carga entero en memoria), se verifica el
hash de cada miembro extraido, y se copia a TODAS las rutas locales que lo
referencian antes de aceptarlo."""
import os
import shutil
import tarfile
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import requests
import zstandard

from core.logger.logger_manager import logger
from core.updater.hash_tree import hash_file

TIMEOUT = 30
CHUNK_SIZE = 1 << 20  # 1 MiB
# 6 rindio igual que 8 contra GitHub (2,4 s frente a 2,5 s con 40 chunks).
PARALLEL_DOWNLOADS = 6


@dataclass
class DownloadResult:
    ok: bool
    failed_files: list = field(default_factory=list)


def _download_and_extract_chunk(url: str, expected_files: dict, staging_dir: str, session=None) -> None:
    """Descarga url en streaming, la descomprime con zstd tambien en streaming
    y extrae cada miembro del tar (nombrado por su hash, ver
    tools/updater/objectstore.stage_chunk) a TODAS las rutas locales de
    expected_files (relpath -> {"hash", ...}) que compartan ese hash,
    verificandolo antes de aceptarlo. Escribe a un .part y hace os.replace()
    al final para la primera ruta, y copia desde ahi al resto -- mismo
    criterio de resistencia a cortes que la v1 de este sistema.

    Lanza si algun contenido esperado no aparece en el tar, o si algun hash
    no coincide -- el llamador decide como tratarlo (todo el chunk se
    descarta)."""
    by_hash: dict[str, list] = {}
    for relpath, entry in expected_files.items():
        by_hash.setdefault(entry["hash"], []).append(relpath)

    decompressor = zstandard.ZstdDecompressor()
    seen = set()
    with (session or requests).get(url, stream=True, timeout=TIMEOUT) as r:
        r.raise_for_status()
        r.raw.decode_content = True
        with decompressor.stream_reader(r.raw) as zstream, tarfile.open(fileobj=zstream, mode="r|") as tar:
            for member in tar:
                if not member.isfile() or member.name not in by_hash:
                    continue
                relpaths = by_hash[member.name]
                first_dest = os.path.join(staging_dir, relpaths[0].replace("/", os.sep))
                os.makedirs(os.path.dirname(first_dest) or ".", exist_ok=True)
                tmp_path = first_dest + ".part"
                src = tar.extractfile(member)
                with open(tmp_path, "wb") as out:
                    while True:
                        block = src.read(CHUNK_SIZE)
                        if not block:
                            break
                        out.write(block)

                if hash_file(tmp_path) != member.name:
                    os.remove(tmp_path)
                    raise ValueError(f"hash no coincide para el contenido {member.name} dentro del chunk")

                os.replace(tmp_path, first_dest)
                seen.add(member.name)
                for relpath in relpaths[1:]:
                    dest_path = os.path.join(staging_dir, relpath.replace("/", os.sep))
                    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
                    shutil.copy2(first_dest, dest_path)

    missing = set(by_hash) - seen
    if missing:
        raise ValueError(f"el chunk no traia {len(missing)} contenido(s) esperado(s): {sorted(missing)}")


def download_update(update_info, staging_dir: str, progress_callback=None) -> "DownloadResult":
    """progress_callback(bytes_completados, bytes_totales), en unidades de
    bytes EN LA RED (compressed_size de cada chunk) -- es lo que de verdad
    avanza mientras se descarga, a diferencia del tamano descomprimido.

    Idempotente: un chunk cuyos archivos ya estan en staging_dir con el hash
    correcto no se vuelve a descargar (permite reanudar tras cerrar la app a
    medias).

    Varios chunks a la vez (PARALLEL_DOWNLOADS), cada hilo con su propia conexion
    reutilizada. Medido contra los chunks reales de la v1.9.3: cada descarga
    suelta pagaba ~1,1 s de conexion + redireccion de GitHub aunque el chunk
    pesara 66 KB, asi que 40 chunks tardaban ~46 s; asi tardan ~2,5 s. Es seguro
    en paralelo porque cada archivo pertenece a un solo chunk: dos hilos nunca
    escriben la misma ruta. La verificacion de hashes no cambia."""
    total = sum(entry["compressed_size"] for entry in update_info.chunks_to_download.values())
    files_by_chunk: dict[str, dict] = {}
    for relpath, entry in update_info.files_to_download.items():
        files_by_chunk.setdefault(entry["chunk"], {})[relpath] = entry

    lock = threading.Lock()
    local = threading.local()
    state = {"completed": 0}
    failed_relpaths = []
    sessions = []  # para cerrarlas al final

    def _session():
        if getattr(local, "session", None) is None:
            local.session = requests.Session()
            sessions.append(local.session)
        return local.session

    def _one(chunk_id, chunk_entry):
        expected_files = files_by_chunk.get(chunk_id, {})
        already_ok = all(
            os.path.exists(os.path.join(staging_dir, relpath.replace("/", os.sep)))
            and hash_file(os.path.join(staging_dir, relpath.replace("/", os.sep))) == entry["hash"]
            for relpath, entry in expected_files.items()
        )
        failed = False
        if not already_ok:
            try:
                _download_and_extract_chunk(chunk_entry["url"], expected_files, staging_dir, _session())
            except (requests.RequestException, tarfile.TarError, ValueError, OSError) as e:
                logger.error(f"Updater: fallo descargando el chunk {chunk_id}: {e}")
                failed = True
        with lock:  # el aviso tambien adentro: asi el progreso nunca retrocede
            if failed:
                failed_relpaths.extend(expected_files)
            state["completed"] += chunk_entry["compressed_size"]
            if progress_callback:
                progress_callback(state["completed"], total)

    try:
        with ThreadPoolExecutor(max_workers=PARALLEL_DOWNLOADS) as pool:
            futures = [pool.submit(_one, cid, entry) for cid, entry in update_info.chunks_to_download.items()]
            for future in futures:
                future.result()  # _one ya atrapa lo esperable; lo inesperado sube igual que antes
    finally:
        for s in sessions:
            s.close()

    if failed_relpaths:
        logger.error(f"Updater: {len(failed_relpaths)} archivo(s) no se pudieron descargar/verificar "
                      f"(via chunks): {failed_relpaths}")
    return DownloadResult(ok=not failed_relpaths, failed_files=failed_relpaths)
