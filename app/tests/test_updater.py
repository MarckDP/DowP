"""Actualizador: comparador de versiones con sufijo (-beta.N), elección del release
según el canal y descarga de chunks en paralelo.

Nada toca GitHub: la API se simula y los chunks se sirven desde un servidor local.
"""
import hashlib
import io
import os
import sys
import tarfile
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("DOWP_NO_FILE_LOG", "1")

import zstandard

from core.updater import downloader, manifest_client
from core.updater.update_checker import (
    SUPPORTED_FORMAT, UpdateInfo, compute_diff, is_prerelease_version, version_key,
)


class VersionKeyTests(unittest.TestCase):
    def test_order(self):
        ordered = ["1.9.3", "1.9.4", "1.9.5-alpha.1", "1.9.5-beta.1", "1.9.5-beta.2",
                   "1.9.5-beta.10", "1.9.5-rc.1", "1.9.5", "1.9.10", "1.10.0", "2.0.0-beta.3", "2.0.0"]
        keys = [version_key(v) for v in ordered]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(len(set(keys)), len(keys))

    def test_equivalences(self):
        self.assertEqual(version_key("1.9"), version_key("1.9.0"))
        self.assertEqual(version_key("v1.9.4"), version_key("1.9.4"))
        self.assertEqual(version_key("2.0.0-rc1"), version_key("2.0.0-rc.1"))
        self.assertEqual(version_key("1.9.5-BETA.2"), version_key("1.9.5-beta.2"))

    def test_unparseable_never_raises_and_sorts_lowest(self):
        for bad in ("", None, "abc", "1.9.x", "1.9.4-nightly", "DowP2-1.9.0"):
            self.assertLess(version_key(bad), version_key("0.0.1"), bad)
            self.assertFalse(is_prerelease_version(bad))

    def test_is_prerelease(self):
        self.assertTrue(is_prerelease_version("1.9.5-beta.1"))
        self.assertTrue(is_prerelease_version("v2.0.0-rc1"))
        self.assertFalse(is_prerelease_version("1.9.4"))
        self.assertFalse(is_prerelease_version("v1.9.4"))


class ComputeDiffVersionTests(unittest.TestCase):
    """Solo la decisión por versión. Con un formato distinto al soportado, compute_diff
    contesta sin hashear la instalación (instalación completa obligatoria)."""

    def _diff(self, remote, current, min_updatable="1.9.0", fmt=SUPPORTED_FORMAT + 99):
        from core.updater.platform_key import get_platform_key
        manifest = {"app_version": remote, "format": fmt, "min_updatable_version": min_updatable,
                    "platforms": {get_platform_key(): {"files": {}, "chunks": {}}}}
        return compute_diff(manifest, install_dir="no-se-usa", current_version=current)

    def test_beta_is_newer_than_previous_stable(self):
        self.assertTrue(self._diff("1.9.5-beta.1", "1.9.4").available)

    def test_stable_is_newer_than_its_betas(self):
        self.assertTrue(self._diff("1.9.5", "1.9.5-beta.2").available)

    def test_next_beta_is_newer(self):
        self.assertTrue(self._diff("1.9.5-beta.2", "1.9.5-beta.1").available)

    def test_older_or_equal_is_not_offered(self):
        self.assertFalse(self._diff("1.9.5-beta.1", "1.9.5").available)
        self.assertFalse(self._diff("1.9.4", "1.9.4").available)
        self.assertFalse(self._diff("1.9.3", "1.9.4").available)

    def test_garbage_remote_is_never_offered(self):
        self.assertFalse(self._diff("basura", "1.9.4").available)

    def test_below_min_with_beta_current(self):
        info = self._diff("1.9.6", "1.9.5-beta.1", min_updatable="1.9.5", fmt=SUPPORTED_FORMAT)
        self.assertTrue(info.must_full_install)  # 1.9.5-beta.1 < 1.9.5


# ── Elección del release (API de GitHub simulada) ────────────────────────────
class _Resp:
    def __init__(self, data=None, status=200, content=b""):
        self._data, self.status_code, self.content = data, status, content

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}")


def _release(rid, tag, prerelease=False, manifest=True, draft=False):
    return {"id": rid, "tag_name": tag, "prerelease": prerelease, "draft": draft, "_manifest": manifest}


class FakeGitHub:
    """Responde /releases/latest, /releases y /releases/{id}/assets como GitHub:
    /latest excluye prereleases y borradores, y es el más reciente POR FECHA (el
    orden de la lista `releases`, del más nuevo al más viejo)."""

    def __init__(self, releases):
        self.releases = releases
        self.calls = []

    def get(self, url, params=None, timeout=None, **_kw):
        self.calls.append(url)
        if url.endswith("/releases/latest"):
            stable = [r for r in self.releases if not r["prerelease"] and not r["draft"]]
            return _Resp(stable[0]) if stable else _Resp(status=404)
        if url.endswith("/releases"):
            return _Resp(list(self.releases))
        if "/assets" in url:
            if (params or {}).get("page", 1) > 1:
                return _Resp([])
            rid = int(url.split("/releases/")[1].split("/")[0])
            rel = next(r for r in self.releases if r["id"] == rid)
            names = ["DowP_Setup.exe"] + (["manifest.json", "manifest.json.sig"] if rel["_manifest"] else [])
            return _Resp([{"name": n, "browser_download_url": f"https://x/{rid}/{n}"} for n in names])
        if url.startswith("https://x/"):
            rid = url.split("/")[3]
            tag = next(r["tag_name"] for r in self.releases if str(r["id"]) == rid)
            return _Resp(content=('{"app_version": "%s"}' % tag.lstrip("v")).encode())
        raise AssertionError(f"URL inesperada: {url}")


class ReleaseChoiceTests(unittest.TestCase):
    def _fetch(self, releases, channel, signature_ok=True):
        gh = FakeGitHub(releases)
        with patch.object(manifest_client.requests, "get", gh.get), \
                patch.object(manifest_client, "_verify_signature", return_value=signature_ok):
            return manifest_client.fetch_and_verify_manifest("o/r", channel=channel)["app_version"], gh

    def test_stable_normal_case_uses_latest(self):
        version, gh = self._fetch([_release(3, "v1.9.5-beta.1", prerelease=True), _release(2, "v1.9.4"),
                                   _release(1, "v1.9.3")], "stable")
        self.assertEqual(version, "1.9.4")
        self.assertFalse(any(c.endswith("/releases") for c in gh.calls))  # sin listar
        # Una sola pasada por los assets: página 1 + la página vacía que corta (antes eran 4).
        self.assertEqual(sum("/assets" in c for c in gh.calls), 2)

    def test_stable_ignores_beta_published_without_prerelease_flag(self):
        version, _ = self._fetch([_release(3, "v1.9.5-beta.1"), _release(2, "v1.9.4")], "stable")
        self.assertEqual(version, "1.9.4")

    def test_stable_skips_release_without_manifest(self):
        version, _ = self._fetch([_release(3, "v1.9.5", manifest=False), _release(2, "v1.9.4")], "stable")
        self.assertEqual(version, "1.9.4")

    def test_beta_takes_highest_version(self):
        version, _ = self._fetch([_release(4, "v1.9.4"), _release(3, "v1.9.5-beta.2", prerelease=True),
                                  _release(2, "v1.9.5-beta.1", prerelease=True)], "beta")
        self.assertEqual(version, "1.9.5-beta.2")  # aunque la 1.9.4 sea más reciente por fecha

    def test_beta_setup_only_falls_back_to_stable(self):
        version, _ = self._fetch([_release(3, "v1.9.5-beta.1", prerelease=True, manifest=False),
                                  _release(2, "v1.9.4")], "beta")
        self.assertEqual(version, "1.9.4")

    def test_beta_stable_after_its_betas_wins(self):
        version, _ = self._fetch([_release(5, "v1.9.5"), _release(4, "v1.9.5-beta.2", prerelease=True)], "beta")
        self.assertEqual(version, "1.9.5")

    def test_drafts_are_ignored(self):
        version, _ = self._fetch([_release(9, "v9.9.9", draft=True), _release(2, "v1.9.4")], "beta")
        self.assertEqual(version, "1.9.4")

    def test_invalid_signature_stops_without_falling_back(self):
        with self.assertRaises(manifest_client.ManifestVerificationError):
            self._fetch([_release(2, "v1.9.4"), _release(1, "v1.9.3")], "stable", signature_ok=False)

    def test_no_release_with_manifest_raises(self):
        with self.assertRaises(manifest_client.ManifestVerificationError):
            self._fetch([_release(2, "v1.9.4", manifest=False)], "beta")

    def test_no_releases_at_all_raises(self):
        with self.assertRaises(manifest_client.ManifestVerificationError):
            self._fetch([], "stable")


# ── Descarga de chunks contra un servidor local ──────────────────────────────
def _blake(data: bytes) -> str:
    return hashlib.blake2b(data, digest_size=32).hexdigest()


def _make_chunk(files: dict[str, bytes]) -> bytes:
    """tar (miembros nombrados por hash del contenido) comprimido con zstd, como
    tools/updater/objectstore.stage_chunk."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        for data in {_blake(d): d for d in files.values()}.values():
            info = tarfile.TarInfo(_blake(data))
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return zstandard.ZstdCompressor().compress(raw.getvalue())


class _Server:
    DELAY = 0.15  # latencia por petición, como la redirección de GitHub

    def __init__(self, blobs: dict[str, bytes]):
        server_self = self
        self.requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                server_self.requests.append(self.path)
                time.sleep(server_self.DELAY)
                body = blobs.get(self.path.lstrip("/"))
                if body is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_a):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}/"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class DownloaderTests(unittest.TestCase):
    N_CHUNKS = 24

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.staging = self.tmp.name
        files, chunks, blobs = {}, {}, {}
        for c in range(self.N_CHUNKS):
            cid = f"{c:04d}"
            content = {f"carpeta{c % 3}/archivo_{c}_{i}.bin": os.urandom(2000 + 500 * i) for i in range(3)}
            if c == 5:  # el mismo contenido bajo dos rutas (como los symlinks de macOS)
                content["otra/copia.bin"] = content["carpeta2/archivo_5_0.bin"]
            blob = _make_chunk(content)
            blobs[f"{cid}.tar.zst"] = blob
            for rel, data in content.items():
                files[rel] = {"hash": _blake(data), "size": len(data), "chunk": cid}
            chunks[cid] = {"hash": cid, "compressed_size": len(blob), "url": None}
        self.server = _Server(blobs)
        for cid in chunks:
            chunks[cid]["url"] = f"{self.server.base}{cid}.tar.zst"
        self.info = UpdateInfo(available=True, must_full_install=False, current_version="1.9.4",
                               remote_version="1.9.5", platform_key="test",
                               files_to_download=files, chunks_to_download=chunks)

    def tearDown(self):
        self.server.close()
        self.tmp.cleanup()

    def _check_all_files(self):
        from core.updater.hash_tree import hash_file
        for rel, entry in self.info.files_to_download.items():
            path = os.path.join(self.staging, rel.replace("/", os.sep))
            self.assertTrue(os.path.isfile(path), rel)
            self.assertEqual(hash_file(path), entry["hash"], rel)

    def test_parallel_download_is_correct_and_faster(self):
        progress = []
        t = time.perf_counter()
        result = downloader.download_update(self.info, self.staging, lambda d, tot: progress.append((d, tot)))
        elapsed = time.perf_counter() - t
        self.assertTrue(result.ok, result.failed_files)
        self._check_all_files()
        total = sum(c["compressed_size"] for c in self.info.chunks_to_download.values())
        self.assertEqual(len(progress), self.N_CHUNKS)
        self.assertEqual(progress[-1], (total, total))
        self.assertEqual([d for d, _ in progress], sorted(d for d, _ in progress))  # nunca retrocede
        sequential = self.N_CHUNKS * _Server.DELAY
        self.assertLess(elapsed, sequential / 2, f"{elapsed:.2f}s frente a {sequential:.2f}s uno por uno")

    def test_resume_skips_chunks_already_in_staging(self):
        downloader.download_update(self.info, self.staging)
        before = len(self.server.requests)
        result = downloader.download_update(self.info, self.staging)
        self.assertTrue(result.ok)
        self.assertEqual(len(self.server.requests), before)  # nada se volvió a pedir

    def test_bad_chunks_fail_alone(self):
        bad_hash = "0003"
        bad_404 = "0010"
        first_rel = next(r for r, e in self.info.files_to_download.items() if e["chunk"] == bad_hash)
        self.info.files_to_download[first_rel] = dict(self.info.files_to_download[first_rel], hash="f" * 64)
        self.info.chunks_to_download[bad_404]["url"] = f"{self.server.base}no-existe.tar.zst"
        result = downloader.download_update(self.info, self.staging)
        self.assertFalse(result.ok)
        expected = {r for r, e in self.info.files_to_download.items() if e["chunk"] in (bad_hash, bad_404)}
        self.assertEqual(set(result.failed_files), expected)
        from core.updater.hash_tree import hash_file
        for rel, entry in self.info.files_to_download.items():
            if entry["chunk"] in (bad_hash, bad_404):
                continue
            self.assertEqual(hash_file(os.path.join(self.staging, rel.replace("/", os.sep))), entry["hash"])


if __name__ == "__main__":
    unittest.main()
