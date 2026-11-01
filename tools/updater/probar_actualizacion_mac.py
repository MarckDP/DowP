"""Prueba real de la actualizacion en macOS. La usa .github/workflows/probar-actualizacion-mac.yml.

Parte de un .app ya instalado y lo actualiza con el codigo de cliente de ESA version y
su DowP_Updater real, como lo haria la app. No publica nada. Lo que no cubre: los clics
en la ventana y Gatekeeper.
"""
import argparse
import os
import shutil
import subprocess
import sys
import threading
import time

WAIT_HELPER_SECONDS = 300
ALIVE_SECONDS = 30
EXECUTABLE = os.path.join("Contents", "MacOS", "DowP")


def step(text):
    print(f"\n=== {text}", flush=True)


def fail(text):
    print(f"FALLO: {text}", flush=True)
    sys.exit(1)


def running_pids(exe):
    res = subprocess.run(["pgrep", "-f", exe], capture_output=True, text=True)
    return [int(p) for p in res.stdout.split() if int(p) != os.getpid()]


def stop_app(exe):
    for pid in running_pids(exe):
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass
    time.sleep(2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", required=True)
    parser.add_argument("--client-src", required=True, help="app/src de la version instalada")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    os.makedirs(args.report, exist_ok=True)
    sys.path.insert(0, args.client_src)

    from core.updater import journal as journal_mod
    from core.updater.downloader import download_update
    from core.updater.hash_tree import hash_tree
    from core.updater.launcher import hand_off_to_helper
    from core.updater.manifest_client import fetch_and_verify_manifest
    from core.updater.update_checker import compute_diff
    from core.utils.paths import get_app_data_dir, get_update_staging_dir, get_updater_state_dir
    from core.version import APP_VERSION, UPDATE_REPO

    exe = os.path.join(args.app, EXECUTABLE)

    step(f"Consultar el manifiesto firmado desde la {APP_VERSION}")
    manifest = fetch_and_verify_manifest(UPDATE_REPO, channel="stable")
    target = manifest["app_version"]
    info = compute_diff(manifest, install_dir=args.app, current_version=APP_VERSION)
    print(f"Destino {target}, plataforma {info.platform_key}, disponible {info.available}, "
          f"{len(info.chunks_to_download)} chunks, {len(info.files_to_download)} archivos, "
          f"{len(info.extra_local_files)} sobrantes, {info.download_size / 1048576:.1f} MB")
    if not info.available or info.must_full_install:
        fail("no se ofrece una actualizacion aplicable")

    step("Descargar y verificar los chunks")
    staging = get_update_staging_dir()
    start = time.monotonic()
    result = download_update(info, staging)
    print(f"Tardo {time.monotonic() - start:.0f} s, fallidos: {len(result.failed_files)}")
    if not result.ok:
        fail(f"no se pudieron verificar {len(result.failed_files)} archivos: {result.failed_files[:10]}")

    step("Reemplazar los archivos con el DowP_Updater real")
    state = get_updater_state_dir()
    journal = journal_mod.build_journal(info, args.app, staging, state, relaunch_exe=exe)
    journal_mod.write_journal(journal, state)
    # Hace de app que se cierra: el helper espera a que termine este PID.
    closing_app = subprocess.Popen(["sleep", "3"])
    threading.Thread(target=closing_app.wait, daemon=True).start()
    hand_off_to_helper(state, args.app, closing_app.pid, exe)

    deadline = time.monotonic() + WAIT_HELPER_SECONDS
    while os.path.exists(journal_mod.journal_path(state)) and time.monotonic() < deadline:
        time.sleep(2)
    leftover = journal_mod.read_journal(state)
    if leftover is not None:
        shutil.copy(journal_mod.journal_path(state), args.report)
        pending = sum(1 for op in leftover["operations"] if not op["done"])
        fail(f"el helper no termino: estado {leftover['status']}, {pending} operaciones pendientes")
    print("El helper aplico el swap y confirmo que la version nueva arranco.")

    step("Comparar la instalacion con el manifiesto")
    expected = manifest["platforms"][info.platform_key]["files"]
    local = hash_tree(args.app)
    missing = sorted(set(expected) - set(local))
    different = sorted(p for p in expected if p in local and local[p]["hash"] != expected[p]["hash"])
    extra = sorted(set(local) - set(expected))
    print(f"Manifiesto {len(expected)}, faltan {len(missing)}, distintos {len(different)}, sobrantes {len(extra)}")
    for label, items in (("Faltan", missing), ("Distintos", different), ("Sobrantes", extra)):
        if items:
            print(f"{label}: {items[:20]}")

    step("Comprobar la firma")
    signature = subprocess.run(["codesign", "--verify", "--deep", "--strict", args.app], capture_output=True, text=True)
    print(signature.stderr.strip() or "Firma valida")

    step("Abrir la app actualizada desde cero")
    stop_app(exe)
    log_path = os.path.join(get_app_data_dir(), "logs", "dowp.log")
    app = subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    time.sleep(ALIVE_SECONDS)
    alive = app.poll() is None
    print(f"Sigue abierta a los {ALIVE_SECONDS} s: {alive}")
    stop_app(exe)

    log_text = ""
    if os.path.exists(log_path):
        shutil.copy(log_path, args.report)
        with open(log_path, encoding="utf-8", errors="replace") as f:
            log_text = f.read()
    started = f"Starting DowP {target}" in log_text
    print(f"El log confirma la version {target}: {started}")

    problems = []
    if missing:
        problems.append(f"faltan {len(missing)} archivos")
    if different:
        problems.append(f"{len(different)} archivos distintos")
    if signature.returncode != 0:
        problems.append("firma invalida")
    if not alive:
        problems.append("la app se cerro sola")
    if not started:
        problems.append("el log no muestra la version nueva")
    if problems:
        fail("; ".join(problems))
    print(f"\nACTUALIZACION {APP_VERSION} -> {target} CORRECTA")


if __name__ == "__main__":
    main()
