"""Motor whisper.cpp opcional y descargas GGML verificadas, fuera del paquete de la app."""
import hashlib
import os
import platform
import re
from functools import lru_cache
import shutil
import stat
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path
import requests

from core.utils.paths import get_bin_root_dir, get_models_dir
from core.utils.http_download import download_file
from core.whisper_catalog import WHISPER_MODELS, VAD_MODEL

VERSION = "v1.9.5"
BUILD = "b5454"  # Binarios nativos que enlaza la publicación oficial v1.9.5.
ENGINE_INFO = {"folder": "whisper.cpp-runtime", "file": "", "name": "whisper.cpp"}
_ASSETS = {
    ("Windows", "x64"): ("whisper-bin-x64.zip", 8928640, "6ba69e3482d7826214f90a6a9c84ca07782aec1e1d0c6a7c30c994fd5d816ccb"),
    ("Windows", "arm64"): ("whisper-bin-win-cpu-arm64.zip", 4371193, "28c37e7b598c3d9bbfef94f3bd67f2ee6f12b7c86f3da5edcf5e4308d615ff6d"),
    ("Linux", "x64"): ("whisper-bin-ubuntu-x64.tar.gz", 10364195, "a72becf15d7917f990f6313867a52638b82b7f9ef237fb0c980dac56a135781c"),
    ("Linux", "arm64"): ("whisper-bin-ubuntu-arm64.tar.gz", 4608377, "6b95ebfc60447df48e70ef00a73bdc3f41679ed2d01ef465827206a2ff325149"),
}


def runtime_asset():
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64" if machine in ("amd64", "x86_64") else machine
    return _ASSETS.get((platform.system(), arch))


def runtime_dir():
    return Path(get_bin_root_dir()) / "bin" / "dependences" / "whisper.cpp"


def runtime_path():
    name = "whisper-cli.exe" if os.name == "nt" else "whisper-cli"
    root = runtime_dir()
    return next((str(p) for p in sorted(root.rglob(name)) if p.is_file()), "") if root.exists() else ""


def runtime_ready():
    return bool(runtime_path())


@lru_cache(maxsize=8)
def _binary_version(binary, modified, size):
    result = subprocess.run([binary, "--version"], capture_output=True, timeout=10,
                            env=runtime_environment(binary),
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    match = re.search(r"whisper\.cpp version:\s*(\d+\.\d+\.\d+)", output)
    return match.group(1) if match else None


def get_local_version():
    try:
        binary = runtime_path()
        if binary:
            info = Path(binary).stat()
            return _binary_version(binary, info.st_mtime_ns, info.st_size)
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def is_newer_version(remote, local):
    def parts(value):
        match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", value or "")
        return tuple(map(int, match.groups())) if match else None
    remote, local = parts(remote), parts(local)
    return bool(remote and local and remote > local)


def get_latest_release():
    """Las versiones estables pueden enlazar otra publicación aparte con los binarios nativos."""
    base = "https://api.github.com/repos/ggml-org/whisper.cpp/releases"
    def fetch(endpoint):
        response = requests.get(base + endpoint, timeout=20)
        response.raise_for_status()
        return response.json()
    release = fetch("/latest")
    version = release["tag_name"]
    if not re.fullmatch(r"v?\d+\.\d+\.\d+", version):
        raise ValueError("La publicación estable de whisper.cpp no tiene una versión reconocible.")
    result = {"version": version, "asset": None}
    native = runtime_asset()
    if not native:
        return result
    assets = release.get("assets", [])
    if not any(a.get("name") == native[0] for a in assets):
        match = re.search(r"https://github\.com/ggml-org/whisper\.cpp/releases/tag/(b\d+)\b", release.get("body", ""))
        if match:
            assets = fetch("/tags/" + match.group(1)).get("assets", [])
    for asset in assets:
        if asset.get("name") != native[0]:
            continue
        digest = asset.get("digest") or ""
        url = asset.get("browser_download_url", "")
        if (re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest)
                and url.startswith("https://github.com/ggml-org/whisper.cpp/releases/download/")):
            result["asset"] = {"name": native[0], "size": int(asset["size"]),
                               "sha256": digest[7:].lower(), "url": url}
        break
    return result


def model_path(info):
    return str(Path(get_models_dir()) / "whisper" / info["file"])


def model_ready(info):
    return bool(info) and os.path.isfile(model_path(info)) and os.path.getsize(model_path(info)) == info["size_bytes"]


def verify_file(path, size, sha):
    if os.path.getsize(path) != size:
        raise ValueError("El archivo descargado está incompleto.")
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != sha:
        raise ValueError("El archivo no coincide con el SHA-256 publicado.")


def download_model(info, progress_callback=None):
    target = Path(model_path(info))
    target.parent.mkdir(parents=True, exist_ok=True)
    part = str(target) + ".part"
    try:
        download_file(info["url"], part, progress_callback=progress_callback, progress_range=(0, 95))
        verify_file(part, info["size_bytes"], info["sha256"])
        os.replace(part, target)
        if progress_callback:
            progress_callback(100)
        return True, "Modelo descargado y verificado."
    except Exception as exc:
        return False, str(exc)
    finally:
        if os.path.exists(part):
            os.remove(part)


def default_model_id():
    """Modelo para un preajuste que no trae el suyo (los de subtítulos de fábrica):
    large-v3-turbo si está descargado; si no, el primero descargado del catálogo; None
    si no hay ninguno."""
    installed = [ident for ident, info in WHISPER_MODELS.items() if model_ready(info)]
    return "large-v3-turbo" if "large-v3-turbo" in installed else (installed[0] if installed else None)


def delete_model(info):
    try:
        Path(model_path(info)).unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _extract(archive, destination):
    """Extrae solo archivos que quedan dentro del destino; los enlaces internos a bibliotecas del tar se
    materializan como copias."""
    destination = Path(destination).resolve()
    def safe(name):
        path = (destination / name.replace("\\", "/")).resolve()
        if not path.is_relative_to(destination):
            raise ValueError("Ruta no válida dentro del paquete.")
        return path
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as package:
            for entry in package.infolist():
                target = safe(entry.filename)
                if stat.S_ISLNK(entry.external_attr >> 16):
                    raise ValueError("Enlace no permitido dentro del paquete.")
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with package.open(entry) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
    else:
        with tarfile.open(archive) as package:
            links = []
            for entry in package:
                target = safe(entry.name)
                if entry.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif entry.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with package.extractfile(entry) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    target.chmod(entry.mode & 0o777)
                elif entry.issym() or entry.islnk():
                    source = safe(str(Path(entry.name).parent / entry.linkname) if entry.issym() else entry.linkname)
                    links.append((target, source))
                else:
                    raise ValueError("Tipo de archivo no permitido dentro del paquete.")
            # Los enlaces .so con versión pueden apuntar a otro enlace que aparece más adelante.
            while links:
                pending = []
                for target, source in links:
                    if source.is_file():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, target)
                    else:
                        pending.append((target, source))
                if len(pending) == len(links):
                    raise ValueError("Enlace sin archivo de destino dentro del paquete.")
                links = pending


def runtime_environment(binary):
    env = os.environ.copy()
    if platform.system() == "Linux":
        folder = str(Path(binary).parent)
        env["LD_LIBRARY_PATH"] = folder + (os.pathsep + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
    return env


def _validate_runtime(folder):
    name = "whisper-cli.exe" if os.name == "nt" else "whisper-cli"
    binary = next(Path(folder).rglob(name), None)
    if binary is None:
        raise ValueError("El paquete no contiene whisper-cli para este sistema.")
    if os.name != "nt":
        binary.chmod(binary.stat().st_mode | 0o111)
    result = subprocess.run([str(binary), "--help"], capture_output=True, timeout=30,
                            env=runtime_environment(binary),
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    if "--output-srt" not in output or "--model" not in output:
        raise ValueError("whisper-cli no pudo ejecutarse. Comprueba arquitectura y bibliotecas del paquete.")


def install_archive(archive):
    root = runtime_dir()
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="whisper-install-", dir=root.parent) as temporary:
        staged = Path(temporary) / "runtime"
        staged.mkdir()
        _extract(archive, staged)
        _validate_runtime(staged)
        backup = Path(temporary) / "previous"
        if root.exists():
            root.rename(backup)
        try:
            staged.rename(root)
        except Exception:
            if backup.exists():
                backup.rename(root)
            raise


def download_runtime(_info=None, progress_callback=None):
    release = (_info or {}).get("release")
    asset = release.get("asset") if release else None
    if release is None and runtime_asset():
        name, size, sha = runtime_asset()
        asset = {"name": name, "size": size, "sha256": sha,
                 "url": f"https://github.com/ggml-org/whisper.cpp/releases/download/{BUILD}/{name}"}
    if not asset:
        return False, "No hay un CLI oficial descargable para este sistema. Importa un paquete nativo de whisper.cpp."
    try:
        with tempfile.TemporaryDirectory(prefix="dowp-whisper-") as temporary:
            archive = Path(temporary) / asset["name"]
            download_file(asset["url"],
                          str(archive), progress_callback=progress_callback, progress_range=(0, 90))
            verify_file(archive, asset["size"], asset["sha256"])
            install_archive(archive)
        if progress_callback:
            progress_callback(100)
        return True, "whisper.cpp instalado."
    except Exception as exc:
        return False, str(exc)


def uninstall_runtime(_info=None, progress_callback=None):
    """Quita solo el motor que administra DowP; los modelos, que viven en otra carpeta, se conservan."""
    root = runtime_dir()
    expected_parent = (Path(get_bin_root_dir()) / "bin" / "dependences").resolve()
    try:
        if root.is_symlink() or root.resolve() != expected_parent / "whisper.cpp":
            raise ValueError("La ruta del motor no está dentro de la carpeta de dependencias.")
        if root.exists():
            shutil.rmtree(root)
        if progress_callback:
            progress_callback(100)
        return True, "Motor desinstalado. Los modelos se conservaron."
    except Exception as exc:
        return False, str(exc)


# ── Detector de voz (VAD, Silero) ────────────────────────────────────────────────
# Complemento de whisper.cpp para "Saltar silencios". Se guarda en la carpeta de modelos
# (models/whisper) con la versión en el nombre; solo se conserva una. VAD_MODEL es la
# versión probada: la que se instala sin consultar la red.
_VAD_REPO = "ggml-org/whisper-vad"
_VAD_FILE = re.compile(r"ggml-silero-v(\d+(?:\.\d+)*)\.bin")


def _version_tuple(version):
    return tuple(int(part) for part in str(version).lstrip("v").split("."))


def installed_vad():
    """(versión, ruta) del VAD instalado, o None. Si hubiera varios, el más nuevo."""
    folder = Path(get_models_dir()) / "whisper"
    found = []
    if folder.is_dir():
        for path in folder.iterdir():
            match = _VAD_FILE.fullmatch(path.name)
            if match and path.is_file() and path.stat().st_size > 0:
                # La versión probada tiene tamaño conocido: si no coincide, está incompleta.
                if path.name == VAD_MODEL["file"] and path.stat().st_size != VAD_MODEL["size_bytes"]:
                    continue
                found.append((_version_tuple(match.group(1)), match.group(1), str(path)))
    if not found:
        return None
    _, version, path = max(found)
    return version, path


def vad_ready():
    """El modelo de detección de voz ("Saltar silencios") está en disco."""
    return installed_vad() is not None


def vad_path():
    installed = installed_vad()
    return installed[1] if installed else None


def vad_local_version():
    installed = installed_vad()
    return installed[0] if installed else None


def vad_is_newer(remote_info, local_version):
    try:
        return bool(remote_info and local_version and
                    _version_tuple(remote_info["variant"]) > _version_tuple(local_version))
    except (ValueError, KeyError):
        return False


def get_latest_vad():
    """La versión más reciente de Silero publicada en el repositorio oficial, con su tamaño
    y SHA-256, fijada a la revisión consultada (el archivo no puede cambiar entre la
    consulta y la descarga). Mismo formato que VAD_MODEL."""
    response = requests.get(f"https://huggingface.co/api/models/{_VAD_REPO}", params={"blobs": "true"}, timeout=20)
    response.raise_for_status()
    data = response.json()
    revision = data.get("sha", "")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("El repositorio del detector de voz no tiene una revisión reconocible.")
    best = None
    for sibling in data.get("siblings", []):
        match = _VAD_FILE.fullmatch(sibling.get("rfilename", ""))
        lfs = sibling.get("lfs") or {}
        if not match or not re.fullmatch(r"[0-9a-f]{64}", lfs.get("sha256", "")) or not lfs.get("size"):
            continue
        if best is None or _version_tuple(match.group(1)) > _version_tuple(best[0]):
            best = (match.group(1), sibling["rfilename"], int(lfs["size"]), lfs["sha256"])
    if best is None:
        raise ValueError("No se encontró ningún detector de voz publicado.")
    version, name, size, sha = best
    return dict(VAD_MODEL, id=f"silero-v{version}", variant=f"v{version}", file=name,
                url=f"https://huggingface.co/{_VAD_REPO}/resolve/{revision}/{name}",
                size_bytes=size, sha256=sha)


def download_vad(info=None, progress_callback=None):
    """Descarga y verifica el VAD (por defecto la versión probada) y borra las demás."""
    info = info or VAD_MODEL
    ok, message = download_model(info, progress_callback)
    if ok:
        for path in (Path(get_models_dir()) / "whisper").iterdir():
            if _VAD_FILE.fullmatch(path.name) and path.name != info["file"]:
                path.unlink(missing_ok=True)
        message = "Detector de voz descargado y verificado."
    return ok, message


def delete_vad():
    try:
        folder = Path(get_models_dir()) / "whisper"
        if folder.is_dir():
            for path in folder.iterdir():
                if _VAD_FILE.fullmatch(path.name):
                    path.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def settings_ready(settings):
    settings = settings or {}
    info = WHISPER_MODELS.get(settings.get("transcription_model"))
    if settings.get("transcription_vad") and not vad_ready():
        return False
    return runtime_ready() and model_ready(info)
