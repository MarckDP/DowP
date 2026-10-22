"""Compila un paquete opcional e importable de whisper.cpp en el sistema de destino.

Requiere CMake y un compilador C++ nativo; con Vulkan, además, su SDK. Es una herramienta
de quien publica: nunca hace commit, push ni subidas, ni cambia el Python de DowP.
Ejemplo: python tools/build_whisper_runtime.py --backend vulkan --output scratch/whisper-build
En Apple Silicon: --backend metal. Se ejecuta por separado en cada arquitectura de destino.
"""
import argparse
import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
import urllib.request
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("cpu", "metal", "vulkan"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    version = "v1.9.5"
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    archive = root / "source.zip"
    if not archive.exists():
        urllib.request.urlretrieve(f"https://github.com/ggml-org/whisper.cpp/archive/refs/tags/{version}.zip", archive)
    with zipfile.ZipFile(archive) as package:
        for entry in package.infolist():
            if not (root / entry.filename).resolve().is_relative_to(root):
                raise ValueError("Unsafe source archive")
        package.extractall(root)
    source = root / f"whisper.cpp-{version[1:]}"
    build = root / ("build-" + args.backend)
    subprocess.run(["cmake", "-S", str(source), "-B", str(build), "-DCMAKE_BUILD_TYPE=Release",
                    "-DBUILD_SHARED_LIBS=OFF", "-DGGML_BACKEND_DL=OFF", "-DGGML_NATIVE=OFF",
                    "-DWHISPER_BUILD_TESTS=OFF", "-DWHISPER_BUILD_EXAMPLES=ON",
                    "-DGGML_METAL_EMBED_LIBRARY=ON",
                    "-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded",
                    f"-DGGML_METAL={'ON' if args.backend == 'metal' else 'OFF'}",
                    f"-DGGML_VULKAN={'ON' if args.backend == 'vulkan' else 'OFF'}"], check=True)
    subprocess.run(["cmake", "--build", str(build), "--config", "Release", "--target", "whisper-cli", "-j", "4"], check=True)
    executable = "whisper-cli.exe" if os.name == "nt" else "whisper-cli"
    binary = next(build.rglob(executable))
    result = subprocess.run([str(binary), "--help"], capture_output=True)
    if b"--output-srt" not in result.stdout + result.stderr:
        raise RuntimeError("Built CLI did not pass its smoke check")
    staging = root / f"whisper-{version}-{platform.system().lower()}-{platform.machine().lower()}-{args.backend}"
    staging.mkdir(exist_ok=True)
    shutil.copy2(binary, staging / executable)
    shutil.copy2(source / "LICENSE", staging / "LICENSE")
    # DLL auxiliares, si el compilador las genera pese a compilar ggml/whisper estáticos.
    for library in binary.parent.glob("*.dll"):
        shutil.copy2(library, staging / library.name)
    (staging / "BUILD.txt").write_text(f"whisper.cpp {version}\nBackend: {args.backend}\n", encoding="utf-8")
    output = shutil.make_archive(str(staging), "zip", staging)
    digest = hashlib.sha256(Path(output).read_bytes()).hexdigest()
    Path(output + ".sha256").write_text(digest + "  " + Path(output).name + "\n", encoding="utf-8")
    print(output)
    print("SHA-256:", digest)


if __name__ == "__main__":
    main()
