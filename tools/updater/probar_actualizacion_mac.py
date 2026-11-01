"""Prueba real de la actualizacion en macOS. La usa .github/workflows/probar-actualizacion-mac.yml.

Parte de un .app ya instalado de una version anterior y usa el codigo de cliente del
repo: consulta el manifiesto firmado, baja el .dmg verificado, lo abre y reemplaza la
app como lo haria el usuario. No publica nada. No cubre los clics en la ventana ni
Gatekeeper.
"""
import argparse
import os
import shutil
import subprocess
import sys
import time

ALIVE_SECONDS = 30
EXECUTABLE = os.path.join("Contents", "MacOS", "DowP")
VOLUME_APP = "/Volumes/DowP/DowP.app"


def step(text):
    print(f"\n=== {text}", flush=True)


def fail(text):
    print(f"FALLO: {text}", flush=True)
    sys.exit(1)


def count_symlinks(root):
    total = 0
    for folder, dirs, files in os.walk(root):
        total += sum(os.path.islink(os.path.join(folder, name)) for name in dirs + files)
    return total


def stop_app(exe):
    res = subprocess.run(["pgrep", "-f", exe], capture_output=True, text=True)
    for pid in res.stdout.split():
        if int(pid) != os.getpid():
            try:
                os.kill(int(pid), 9)
            except ProcessLookupError:
                pass
    time.sleep(2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", required=True)
    parser.add_argument("--from-version", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--downloads", required=True)
    args = parser.parse_args()
    os.makedirs(args.report, exist_ok=True)
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.insert(0, os.path.join(repo_root, "app", "src"))

    from core.updater.installer_fallback import download_installer, find_installer, open_installer
    from core.updater.manifest_client import fetch_and_verify_manifest
    from core.updater.update_checker import compute_diff
    from core.utils.paths import get_app_data_dir
    from core.version import UPDATE_REPO

    exe = os.path.join(args.app, EXECUTABLE)

    step(f"Consultar el manifiesto firmado desde la {args.from_version}")
    manifest = fetch_and_verify_manifest(UPDATE_REPO, channel="stable")
    target = manifest["app_version"]
    info = compute_diff(manifest, install_dir=args.app, current_version=args.from_version)
    print(f"Destino {target}, plataforma {info.platform_key}, disponible {info.available}, "
          f"instalador {info.must_full_install}, archivos por chunks {len(info.files_to_download)}")
    if not (info.available and info.must_full_install) or info.files_to_download:
        fail("no se ofrece el instalador")

    step("Bajar y verificar el .dmg")
    asset = find_installer(UPDATE_REPO, target, info.platform_key)
    print(f"{asset['name']}, {asset['size'] / 1048576:.1f} MB, {asset.get('digest')}")
    if not (asset.get("digest") or "").startswith("sha256:"):
        fail("GitHub no informa el sha256")
    path = download_installer(asset, args.downloads)
    print(f"Verificado: {path}")

    step("Abrir el .dmg")
    open_installer(path)
    deadline = time.monotonic() + 90
    while not os.path.isdir(VOLUME_APP) and time.monotonic() < deadline:
        time.sleep(1)
    if not os.path.isdir(VOLUME_APP):
        fail("el .dmg no se monto")
    print(f"Montado: {VOLUME_APP}")

    step("Reemplazar la app, como al arrastrarla a Aplicaciones")
    before = count_symlinks(args.app)
    shutil.rmtree(args.app)
    subprocess.run(["ditto", VOLUME_APP, args.app], check=True)
    subprocess.run(["hdiutil", "detach", "/Volumes/DowP"], check=True)
    after = count_symlinks(args.app)
    print(f"Enlaces: antes {before}, despues {after}")

    step("Comprobar la firma")
    signature = subprocess.run(["codesign", "--verify", "--deep", "--strict", args.app], capture_output=True, text=True)
    print(signature.stderr.strip() or "Firma valida")

    step("Abrir la app actualizada")
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
    if not after:
        problems.append("la app no conserva sus enlaces")
    if signature.returncode != 0:
        problems.append("firma invalida")
    if not alive:
        problems.append("la app se cerro sola")
    if not started:
        problems.append("el log no muestra la version nueva")
    if problems:
        fail("; ".join(problems))
    print(f"\nACTUALIZACION {args.from_version} -> {target} CON .DMG CORRECTA")


if __name__ == "__main__":
    main()
