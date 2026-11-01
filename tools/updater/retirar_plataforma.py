"""Quita una plataforma del manifiesto de un release y lo vuelve a firmar, para que los
clientes de esa plataforma dejen de recibir esa actualizacion. Las demas plataformas y
todos los archivos del release quedan intactos.

Uso (raiz del repo, con GITHUB_TOKEN en el entorno):
    python tools/updater/retirar_plataforma.py --version 1.9.4 --platform macos-arm64 ^
        --repo MarckDP/DowP --private-key tools/updater/secrets/private_key.pem
"""
import argparse
import json
import os
import sys
import tempfile

import github_release as gh
import publish
import signing


def retire(repo, version, platform_key, private_key, token):
    tag = f"v{version}"
    release = gh.get_release_by_tag(repo, tag, token)
    if release is None:
        sys.exit(f"ERROR: no existe el release {tag}.")
    manifest = publish.fetch_manifest_json(repo, release, token)
    if manifest is None:
        sys.exit(f"ERROR: {tag} no tiene manifiesto.")
    platforms = manifest.get("platforms", {})
    if platform_key not in platforms:
        print(f"{platform_key} ya no esta en el manifiesto de {tag}: {sorted(platforms)}")
        return manifest
    del platforms[platform_key]
    if not platforms:
        sys.exit("ERROR: el manifiesto quedaria sin plataformas; no se cambio nada.")

    with tempfile.TemporaryDirectory() as folder:
        manifest_path = os.path.join(folder, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(manifest, f, indent=2, sort_keys=True, ensure_ascii=False)
            f.write("\n")
        sig_path = manifest_path + ".sig"
        with open(sig_path, "wb") as f:
            f.write(signing.sign_file(private_key, manifest_path))
        gh.replace_asset(release, manifest_path, "manifest.json", repo, token, content_type="application/json")
        gh.replace_asset(release, sig_path, "manifest.json.sig", repo, token)
    print(f"{platform_key} retirado de {tag}. Quedan: {sorted(platforms)}")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--private-key", required=True)
    args = parser.parse_args()
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("ERROR: falta GITHUB_TOKEN en el entorno.")
    publish.check_private_key_matches_client(args.private_key)
    retire(args.repo, args.version, args.platform, args.private_key, token)


if __name__ == "__main__":
    main()
