# tools/updater/keygen.py
"""Genera el par de claves Ed25519 del updater. Se corre UNA vez.

    python tools/updater/keygen.py

La privada va a secrets/private_key.pem (gitignored -- guardala tambien en un
secret de GitHub Actions para cuando exista la pieza 6, CI). La publica se
escribe DIRECTAMENTE dentro del paquete de la app, como constante en
app/src/core/updater/public_key.py: el cliente de descarga la necesita embebida
para verificar el manifiesto antes de aplicar nada, y como modulo de Python viaja
siempre dentro del ejecutable congelado (un .pem suelto no -- ver el docstring de
ese modulo). El publicador (este mismo tools/updater/) nunca la usa para firmar,
pero publish.py SI comprueba que la privada corresponda a ella antes de publicar.
"""
import os
import re
import shutil
import sys
import tempfile

from signing import generate_keypair

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
PRIVATE_KEY_PATH = os.path.join(HERE, "secrets", "private_key.pem")
PUBLIC_KEY_MODULE = os.path.join(REPO_ROOT, "app", "src", "core", "updater", "public_key.py")

_CONSTANT_RE = re.compile(r'UPDATER_PUBLIC_KEY_PEM = """.*?"""', re.DOTALL)


if __name__ == "__main__":
    with open(PUBLIC_KEY_MODULE, "r", encoding="utf-8") as f:
        module_src = f.read()
    if len(_CONSTANT_RE.findall(module_src)) != 1:
        print(f"ERROR: no se encontro UPDATER_PUBLIC_KEY_PEM (exactamente una vez) en {PUBLIC_KEY_MODULE}")
        sys.exit(1)

    tmp_dir = tempfile.mkdtemp()
    try:
        tmp_public = os.path.join(tmp_dir, "public_key.pem")
        try:
            generate_keypair(PRIVATE_KEY_PATH, tmp_public)
        except FileExistsError as e:
            print(f"ERROR: {e}")
            sys.exit(1)
        with open(tmp_public, "r", encoding="utf-8") as f:
            public_pem = f.read().strip()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    new_src = _CONSTANT_RE.sub(lambda _m: f'UPDATER_PUBLIC_KEY_PEM = """{public_pem}\n"""', module_src)
    with open(PUBLIC_KEY_MODULE, "w", encoding="utf-8", newline="\n") as f:
        f.write(new_src)

    print(f"Clave privada: {PRIVATE_KEY_PATH}  (NO commitear -- ya esta en .gitignore)")
    print(f"Clave publica: {PUBLIC_KEY_MODULE}  (commitear -- el cliente la necesita)")
