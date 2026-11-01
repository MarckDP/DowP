# tools/updater/objectstore.py
"""Hasheo de un arbol de build y almacen de chunks direccionado por contenido.

hash_tree() es la misma logica que ya tenia manifest.py (blake2b por archivo,
para detectar que cambio entre dos builds), extraida aqui para que la comparta
publish.py sin duplicarla. stage_chunk() empaqueta un grupo de archivos (un
chunk, ver core.updater.chunking) en un tar comprimido con zstd, nombrado por
el hash combinado del chunk -- ese es el objeto real que se sube a GitHub, ya
no un archivo suelto por objeto (ver ACTUALIZACIONES.md: un objeto por archivo
choca con el limite de 1000 assets/release de GitHub apenas el build supera
esa cantidad de archivos)."""
import hashlib
import os
import tarfile

import zstandard

IO_CHUNK_SIZE = 1 << 20  # 1 MiB, tamano de bloque de lectura/escritura -- no
                         # confundir con un "chunk" de archivos (grupo de
                         # objetos, ver core.updater.chunking.NUM_CHUNKS)


def hash_tree(root: str) -> dict:
    """Recorre root y devuelve {ruta_relativa_posix: {"hash": blake2b_hex, "size": int}}."""
    out = {}
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace("\\", "/")
            out[rel] = {"hash": hash_file(full), "size": os.path.getsize(full)}
    return out


def hash_file(path: str) -> str:
    """blake2b-256 (digest_size=32) de un archivo, en hex. Streaming: los archivos
    del bundle pueden pesar cientos de MB (el .exe, modelos), no se cargan enteros."""
    h = hashlib.blake2b(digest_size=32)
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(IO_CHUNK_SIZE), b""):
            h.update(block)
    return h.hexdigest()


def chunk_asset_name(chunk_hash: str) -> str:
    """Nombre del asset del release para un chunk: <hash_combinado>.tar.zst."""
    return f"{chunk_hash}.tar.zst"


def stage_chunk(hash_to_path: dict, chunk_hash: str, staging_dir: str) -> tuple[str, int]:
    """Empaqueta el CONTENIDO UNICO de cada entrada de hash_to_path (hash hex
    -> ruta absoluta de un archivo real con ese contenido -- cualquiera de
    los que compartan hash sirve, ver publish.py) en un tar, comprimido en
    streaming con zstd, nombrado por chunk_hash -- el hash combinado del
    grupo (ver core.updater.chunking.compute_chunk_hash).

    Cada archivo se guarda en el tar con su propio HASH como nombre (arcname),
    no con su relpath original: el mismo contenido puede corresponder a
    varias rutas distintas del lado del cliente (symlinks Frameworks/
    Resources en macOS, ver ACTUALIZACIONES.md), y empaquetar/desempaquetar
    por hash en vez de por ruta es lo que permite escribirlo en todas esas
    rutas sin subirlo mas de una vez.

    Devuelve (ruta_del_chunk_comprimido, tamano_comprimido). Si el chunk ya
    esta en staging (misma corrida re-ejecutada tras un corte), no lo vuelve
    a empaquetar."""
    os.makedirs(staging_dir, exist_ok=True)
    dst_path = os.path.join(staging_dir, chunk_asset_name(chunk_hash))
    if os.path.exists(dst_path):
        return dst_path, os.path.getsize(dst_path)

    compressor = zstandard.ZstdCompressor(level=19)
    tmp_path = dst_path + ".tmp"
    with open(tmp_path, "wb") as dst, compressor.stream_writer(dst) as zdst:
        # dereference: en macOS y Linux la ruta puede ser un symlink, y el cliente solo
        # extrae archivos reales. Sin esto, el chunk llevaba solo el enlace.
        with tarfile.open(fileobj=zdst, mode="w|", dereference=True) as tar:
            for file_hash in sorted(hash_to_path):
                tar.add(hash_to_path[file_hash], arcname=file_hash)
    os.replace(tmp_path, dst_path)
    return dst_path, os.path.getsize(dst_path)


def mb(n: float) -> str:
    return f"{n / 1048576:.1f} MB"
