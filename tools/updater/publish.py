# tools/updater/publish.py
"""El publicador real del sistema de actualizaciones: genera el manifiesto firmado
de una plataforma y lo sube, junto con los chunks nuevos, a un GitHub Release.

    python tools/updater/publish.py \
        --dist app/dist/DowP --platform windows-x64 \
        --repo MarckDP/DowP2 --private-key tools/updater/secrets/private_key.pem

    python tools/updater/publish.py --dist app/dist/DowP --platform windows-x64 \
        --private-key tools/updater/secrets/private_key.pem --dry-run

    # macOS: el .app COMPLETO, no Contents/MacOS -- el onedir real de un
    # bundle queda partido entre Contents/Frameworks y Contents/Resources
    # (symlinks cruzados entre ambas), y solo el .app entero cubre las dos
    # sin ambiguedad. Debe coincidir con lo que calcula
    # launcher.install_dir_from_executable() del lado del cliente.
    python tools/updater/publish.py --dist app/dist/DowP.app --platform macos-arm64 \
        --repo MarckDP/DowP2 --private-key tools/updater/secrets/private_key.pem

Ver ACTUALIZACIONES.md para el diseno completo y su historia: la v1 de este
sistema subia un objeto por archivo (~2600 objetos en un build de Windows) y
choco con el limite duro de GitHub de 1000 assets por release. La v2 agrupa
los CONTENIDOS UNICOS en ~200 "chunks" por hash de contenido (ver
core.updater.chunking) y sube un tar.zst por chunk -- lejos del limite de
GitHub, deduplicando de verdad (un mismo contenido bajo varias rutas, como los
symlinks Frameworks/Resources de macOS, se sube una sola vez), y una
actualizacion tipica solo invalida un puñado de chunks, no el build entero.
Simplificacion explicita: la reutilizacion de chunks ya subidos solo mira el
release inmediatamente anterior (`/releases/latest`), no todo el historial --
un chunk que cambio y volvio a un valor de hace varias versiones se resube
(correcto, solo suboptimo).
"""
import argparse
import json
import os
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

import github_release as gh
import objectstore
import signing

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
VERSION_FILE = os.path.join(REPO_ROOT, "app", "src", "core", "version.py")
STAGING_DIR = os.path.join(HERE, ".staging")
MANIFEST_FORMAT = 2  # v2: manifiesto por chunks (ver docstring del modulo)

# Un chunk a la vez tardaba mucho para los objetos de la v1 (~2600, del orden
# de una hora en serie); con ~200 chunks por plataforma la subida es mucho mas
# corta, pero se mantiene la concurrencia igual -- no cuesta nada y sigue
# siendo conservador contra el rate limiting secundario de GitHub (~100
# requests concurrentes documentados antes de que se dispare).
MAX_CONCURRENT_UPLOADS = 15

# app/src no se instala como paquete -- se importa por ruta, igual que hace
# main.py en runtime. get_platform_key()/chunk_id_for() viven ahi (no aqui)
# porque el cliente, que SI viaja dentro del bundle, tambien los necesita: que
# ambos calculen lo mismo es lo que hace que el manifiesto que arma el
# publicador y el diff que calcula el cliente hablen el mismo idioma.
sys.path.insert(0, os.path.join(REPO_ROOT, "app", "src"))
from core.updater.chunking import chunk_id_for, compute_chunk_hash  # noqa: E402
from core.updater.platform_key import get_platform_key  # noqa: E402
from core.updater.public_key import UPDATER_PUBLIC_KEY_PEM  # noqa: E402


def check_private_key_matches_client(private_key_path: str) -> None:
    """Aborta si la clave privada no corresponde a la publica embebida en la app.

    Un manifiesto firmado con otra clave no lo acepta NINGUN cliente, y el cliente
    lo reporta en silencio como "sin actualizaciones" -- publicar asi pasaria por
    exito aqui y fallaria para todo el mundo alla. Mejor fallar ruidosamente antes
    de subir nada (clave rotada a medias, secrets/ equivocado, etc.)."""
    from Cryptodome.PublicKey import ECC

    with open(private_key_path, "rt", encoding="utf-8") as f:
        derived = ECC.import_key(f.read()).public_key().export_key(format="DER")
    embedded = ECC.import_key(UPDATER_PUBLIC_KEY_PEM).export_key(format="DER")
    if derived != embedded:
        print("ERROR: la clave privada no corresponde a la clave publica embebida en "
              "app/src/core/updater/public_key.py. Ningun cliente aceptaria este manifiesto.")
        sys.exit(1)


def read_version_module() -> dict:
    """Ejecuta version.py aislado, igual que build_cross_platform.py -- ese archivo
    no tiene imports a proposito para poder leerse asi desde herramientas externas."""
    namespace = {}
    with open(VERSION_FILE, encoding="utf-8") as f:
        exec(compile(f.read(), VERSION_FILE, "exec"), namespace)
    return namespace


def iter_manifest_chunks(manifest: dict | None):
    """Yield (platform, chunk_id, entry) para cada chunk de cada plataforma de
    un manifiesto ya cargado. No-op si manifest es None (no habia release
    anterior, o esta version todavia no tiene manifest.json)."""
    if not manifest:
        return
    for platform, plat_data in manifest.get("platforms", {}).items():
        for chunk_id, entry in plat_data.get("chunks", {}).items():
            yield platform, chunk_id, entry


def iter_manifest_files(manifest: dict | None):
    """Yield (platform, relpath, entry) para cada archivo de cada plataforma --
    solo se usa para el resumen de "cuanto cambio" (prev_file_hashes), la
    descarga real va por chunk."""
    if not manifest:
        return
    for platform, plat_data in manifest.get("platforms", {}).items():
        for relpath, entry in plat_data.get("files", {}).items():
            yield platform, relpath, entry


def find_asset_paginated(repo: str, release: dict, name: str, token: str) -> dict | None:
    """Busca un asset por nombre paginando de verdad (github_release.list_release_assets)
    en vez de confiar en el campo "assets" embebido en el release -- ver
    ACTUALIZACIONES.md, esa lista embebida no demostro ser confiable como
    fuente de "que esta subido ya" cuando un release tiene muchos assets."""
    for asset in gh.list_release_assets(repo, release["id"], token):
        if asset["name"] == name:
            return asset
    return None


def fetch_manifest_json(repo: str, release: dict | None, token: str) -> dict | None:
    """Descarga y parsea manifest.json de un release, o None si el release no
    existe o no tiene ese asset todavia (release recien creado por otra plataforma
    en la misma corrida de publicacion multi-plataforma)."""
    if release is None:
        return None
    asset = find_asset_paginated(repo, release, "manifest.json", token)
    if asset is None:
        return None
    return json.loads(gh.download_asset_content(asset, token))


def build_platform_manifest(dist_dir: str, chunk_reuse_map: dict, staging_dir: str,
                             find_existing_chunk_asset) -> tuple[dict, dict, list, int, int]:
    """Hashea dist_dir, agrupa los CONTENIDOS UNICOS en chunks (chunk_id_for,
    por hash de contenido -- no de ruta, ver core.updater.chunking) y arma las
    entradas de esta plataforma.

    chunk_reuse_map: chunk_hash -> {"url": ..., "compressed_size": ...} de chunks
    que ya estan subidos en algun release (esta version por otra plataforma, o la
    version anterior) y se pueden referenciar sin volver a empaquetar ni subir.
    find_existing_chunk_asset(asset_name) -> asset dict o None: el chunk ya existe
    FISICAMENTE como asset del release actual (idempotencia ante un reintento tras
    un corte a medias), con su "browser_download_url" real.

    Un chunk realmente nuevo (ni en chunk_reuse_map ni ya subido) todavia no sabe
    su URL final -- eso se decide recien al subirlo en main(), asi que su "url"
    queda en None aqui y se completa despues.

    Devuelve (files_dict, chunks_dict, pendientes_de_subir, cambia_bytes, total_bytes),
    donde pendientes_de_subir es [(chunk_hash, ruta_comprimida, nombre_asset), ...].
    """
    local_files = objectstore.hash_tree(dist_dir)

    # Un representante (cualquiera) por cada contenido unico -- de donde leer
    # los bytes reales al empaquetar, sin importar cuantos relpaths compartan
    # ese mismo hash (symlinks Frameworks/Resources en macOS, por ejemplo).
    hash_to_relpath: dict[str, str] = {}
    files = {}
    total_bytes = 0
    by_chunk: dict[str, set] = {}
    for relpath, info in local_files.items():
        file_hash = info["hash"]
        hash_to_relpath.setdefault(file_hash, relpath)
        cid = chunk_id_for(file_hash)
        files[relpath] = {"hash": file_hash, "size": info["size"], "chunk": cid}
        by_chunk.setdefault(cid, set()).add(file_hash)
        total_bytes += info["size"]

    chunks, pending, changed_bytes = {}, [], 0

    for cid, hashes in sorted(by_chunk.items()):
        chunk_hash = compute_chunk_hash(hashes)
        chunk_size = sum(local_files[hash_to_relpath[h]]["size"] for h in hashes)

        if chunk_hash in chunk_reuse_map:
            reused = chunk_reuse_map[chunk_hash]
            chunks[cid] = {
                "hash": chunk_hash, "compressed_size": reused["compressed_size"], "url": reused["url"],
            }
            continue

        changed_bytes += chunk_size
        asset_name = objectstore.chunk_asset_name(chunk_hash)

        existing_asset = find_existing_chunk_asset(asset_name)
        if existing_asset is not None:
            # Ya subido de verdad (esta corrida u otra anterior interrumpida):
            # no hace falta empaquetar de nuevo, solo referenciarlo con su URL real.
            chunks[cid] = {
                "hash": chunk_hash, "compressed_size": existing_asset["size"],
                "url": existing_asset["browser_download_url"],
            }
            continue

        hash_to_path = {h: os.path.join(dist_dir, hash_to_relpath[h].replace("/", os.sep)) for h in hashes}
        staged_path, compressed_size = objectstore.stage_chunk(hash_to_path, chunk_hash, staging_dir)
        chunks[cid] = {"hash": chunk_hash, "compressed_size": compressed_size, "url": None}
        pending.append((chunk_hash, staged_path, asset_name))

    return files, chunks, pending, changed_bytes, total_bytes


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dist", required=True,
                         help="Carpeta del build (ej. app/dist/DowP; en macOS el .app completo, "
                              "ej. app/dist/DowP.app -- no Contents/MacOS)")
    parser.add_argument("--platform", help="ej. windows-x64, macos-arm64, linux-x64. "
                         "Por defecto, autodetectada con get_platform_key() del SO donde corre esto")
    parser.add_argument("--repo", help="owner/repo en GitHub. Obligatorio salvo con --dry-run")
    parser.add_argument("--private-key", required=True, help="Ruta al PEM de la clave privada Ed25519")
    parser.add_argument("--version", help="Por defecto, APP_VERSION de app/src/core/version.py")
    parser.add_argument("--min-updatable", help="Por defecto, MIN_UPDATABLE_VERSION de version.py")
    parser.add_argument("--dry-run", action="store_true",
                         help="No toca GitHub: hashea, comprime y firma en local para validar el flujo")
    parser.add_argument("--prerelease", action="store_true",
                         help="Marca el release como pre-release de GitHub -- invisible para clientes "
                              "en canal 'stable' (usan /releases/latest), solo lo ven quienes tengan "
                              "el canal 'beta' activado en Ajustes. NO es lo mismo que el canal "
                              "'beta' de la app en sí (ver core/version.py IS_BETA) -- esto es "
                              "puramente el flag de GitHub, para builds que no quieres que le lleguen "
                              "a todo el mundo en canal beta automaticamente.")
    args = parser.parse_args()

    if not os.path.isdir(args.dist):
        print(f"ERROR: no existe la carpeta de build {args.dist}")
        sys.exit(1)

    check_private_key_matches_client(args.private_key)

    platform_key = args.platform or get_platform_key()

    version_ns = read_version_module()
    version = args.version or version_ns["APP_VERSION"]
    min_updatable = args.min_updatable or version_ns["MIN_UPDATABLE_VERSION"]
    tag = f"v{version}"

    if not args.dry_run and not args.repo:
        print("ERROR: --repo es obligatorio salvo en --dry-run")
        sys.exit(1)

    token = os.environ.get("GITHUB_TOKEN", "") if not args.dry_run else ""
    if not args.dry_run and not token:
        print("ERROR: falta la variable de entorno GITHUB_TOKEN (permiso 'repo' o "
              "'contents: write' en un fine-grained token). No se loggea ni se pide por otro medio.")
        sys.exit(1)

    staging_dir = os.path.join(STAGING_DIR, tag)
    os.makedirs(staging_dir, exist_ok=True)

    # Log persistente en disco, ademas de stdout -- si la ventana de la consola se
    # cierra sola a mitad de una corrida larga, el traceback impreso se pierde con
    # ella. Esto deja rastro igual, sin cambiar nada de lo que ya se imprime por
    # pantalla.
    log_path = os.path.join(staging_dir, "publish_log.txt")

    def log(msg: str) -> None:
        print(msg)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(msg + "\n")

    current_release, prev_release = None, None
    current_manifest, prev_manifest = None, None

    if not args.dry_run:
        current_release = gh.get_release_by_tag(args.repo, tag, token)
        current_manifest = fetch_manifest_json(args.repo, current_release, token)

        prev_release = gh.get_latest_release(args.repo, token)
        if prev_release and prev_release.get("tag_name") != tag:
            prev_manifest = fetch_manifest_json(args.repo, prev_release, token)

    # chunk_hash -> {url, compressed_size} de chunks ya subidos en algun release
    # (esta version parcialmente publicada por otra plataforma, o la version
    # anterior) -- evita volver a empaquetar/subir un chunk sin cambios.
    chunk_reuse_map = {}
    for _plat, _cid, entry in iter_manifest_chunks(current_manifest):
        chunk_reuse_map[entry["hash"]] = {"url": entry["url"], "compressed_size": entry["compressed_size"]}
    prev_file_hashes = set()
    for _plat, _rp, entry in iter_manifest_files(prev_manifest):
        prev_file_hashes.add(entry["hash"])
    for _plat, _cid, entry in iter_manifest_chunks(prev_manifest):
        chunk_reuse_map.setdefault(entry["hash"], {"url": entry["url"], "compressed_size": entry["compressed_size"]})

    # Fuente de verdad real de "que chunk esta subido ya", paginada -- ver
    # find_asset_paginated. Con ~200 chunks por plataforma nunca se acerca al
    # limite de 1000 assets/release de GitHub, asi que (a diferencia de la v1)
    # no hace falta repartir en releases aparte: todo vive en el release de la
    # version, junto a manifest.json/.sig.
    existing_chunks_by_name = {}
    if not args.dry_run and current_release is not None:
        existing_chunks_by_name = {
            a["name"]: a for a in gh.list_release_assets(args.repo, current_release["id"], token)
        }

    def find_existing_chunk_asset(asset_name: str):
        return existing_chunks_by_name.get(asset_name)

    files, chunks, pending, changed_bytes, total_bytes = build_platform_manifest(
        args.dist, chunk_reuse_map, staging_dir, find_existing_chunk_asset,
    )

    # Reutilizados-de-verdad (sin cambios respecto a la version anterior) vs el
    # resto, para el resumen -- a nivel de ARCHIVO individual (independiente de
    # en que chunk haya caido), para que el numero siga significando lo mismo
    # que en la v1 de este sistema.
    unchanged = sum(1 for e in files.values() if e["hash"] in prev_file_hashes)
    download_bytes = sum(e["size"] for e in files.values() if e["hash"] not in prev_file_hashes)

    if args.dry_run:
        # Nunca se sube nada, asi que no hay release real donde caeria un chunk
        # nuevo -- placeholder solo para que el manifiesto local quede completo
        # e inspeccionable, no una URL que vaya a existir de verdad.
        for entry in chunks.values():
            if entry["url"] is None:
                entry["url"] = (f"https://github.com/{args.repo or '<repo>'}/releases/download/"
                                 f"{tag}/{objectstore.chunk_asset_name(entry['hash'])}")

    if not args.dry_run:
        if current_release is None:
            current_release = gh.create_release(args.repo, tag, token, prerelease=args.prerelease)

        if pending:
            log(f"Subiendo {len(pending)} chunk(s) nuevo(s) de {len(chunks)} totales "
                f"(hasta {MAX_CONCURRENT_UPLOADS} en simultaneo). Log en: {log_path}")
            done = 0
            with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_UPLOADS) as pool:
                futures = {
                    pool.submit(gh.upload_asset, current_release, staged_path, asset_name, token): asset_name
                    for _chunk_hash, staged_path, asset_name in pending
                }
                for future in as_completed(futures):
                    asset_name = futures[future]
                    try:
                        future.result()
                    except Exception:
                        # Se deja constancia de CUAL chunk fallo y el traceback
                        # completo en el log antes de relanzar -- si la ventana
                        # se cierra sola, esto sigue en disco.
                        log(f"FALLO subiendo {asset_name}:\n{traceback.format_exc()}")
                        raise
                    done += 1
                    if done % 20 == 0 or done == len(pending):
                        log(f"  {done}/{len(pending)}")
            log("Subida completa.")

        chunk_hash_to_url = {
            chunk_hash: f"https://github.com/{args.repo}/releases/download/{tag}/{asset_name}"
            for chunk_hash, _staged_path, asset_name in pending
        }
        for entry in chunks.values():
            if entry["url"] is None:
                entry["url"] = chunk_hash_to_url[entry["hash"]]

    final_manifest = current_manifest or {}
    final_manifest["format"] = MANIFEST_FORMAT
    final_manifest["app_version"] = version
    final_manifest["min_updatable_version"] = min_updatable
    final_manifest.setdefault("platforms", {})[platform_key] = {"files": files, "chunks": chunks}

    manifest_path = os.path.join(staging_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(final_manifest, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")

    signature = signing.sign_file(args.private_key, manifest_path)
    sig_path = manifest_path + ".sig"
    with open(sig_path, "wb") as f:
        f.write(signature)

    print(f"\nPlataforma: {platform_key}  |  Version: {version}  |  Tag: {tag}")
    print(f"  Archivos totales   : {len(files):>6}  ({objectstore.mb(total_bytes)})")
    print(f"  Chunks totales     : {len(chunks):>6}")
    print(f"  Sin cambios        : {unchanged:>6} archivo(s)")
    print(f"  Nuevos/modificados : {len(files) - unchanged:>6} archivo(s)  ({objectstore.mb(download_bytes)})")
    print(f"  Chunks a subir     : {len(pending):>6}")
    print(f"  Manifiesto         : {manifest_path}")
    print(f"  Firma              : {sig_path}")

    if args.dry_run:
        print("\n[--dry-run] No se toco GitHub. Chunks comprimidos en:", staging_dir)
        return

    gh.replace_asset(current_release, manifest_path, "manifest.json", args.repo, token,
                      content_type="application/json")
    gh.replace_asset(current_release, sig_path, "manifest.json.sig", args.repo, token)
    print(f"\nPublicado en https://github.com/{args.repo}/releases/tag/{tag}")


if __name__ == "__main__":
    main()
