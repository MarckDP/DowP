"""Optional runtime management: no network or real installation modifications."""
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from core.setup import whisper_setup as whisper, optional_dependencies as optional


class OptionalDependencyTests(unittest.TestCase):
    def test_stable_release_resolves_linked_build_and_requires_digest(self):
        name = "whisper-bin-x64.zip"
        stable = {"tag_name": "v1.10.0", "assets": [], "body":
                  "**Nightly build:** [b6000](https://github.com/ggml-org/whisper.cpp/releases/tag/b6000)"}
        asset = {"name": name, "size": 3, "digest": "sha256:" + "a" * 64,
                 "browser_download_url": "https://github.com/ggml-org/whisper.cpp/releases/download/b6000/" + name}
        response = lambda data: SimpleNamespace(raise_for_status=lambda: None, json=lambda: data)
        with patch.object(whisper, "runtime_asset", return_value=(name, 1, "old")), patch.object(whisper.requests, "get", side_effect=[response(stable), response({"assets": [asset]})]) as get:
            release = whisper.get_latest_release()
        self.assertEqual(release["version"], "v1.10.0")
        self.assertIn("b6000", release["asset"]["url"])
        self.assertTrue(get.call_args.args[0].endswith("/tags/b6000"))
        asset.pop("digest")
        stable["assets"] = [asset]
        with patch.object(whisper, "runtime_asset", return_value=(name, 1, "old")), patch.object(whisper.requests, "get", return_value=response(stable)):
            self.assertIsNone(whisper.get_latest_release()["asset"])
        self.assertTrue(whisper.is_newer_version("v1.10.0", "1.9.5"))
        self.assertFalse(whisper.is_newer_version("v1.9.5", "1.10.0"))
        self.assertFalse(whisper.is_newer_version("v1.10.0", None))

    def test_update_downloads_detected_asset_and_verifies_before_install(self):
        release = {"version": "v1.10.0", "asset": {"name": "runtime.zip", "size": 3,
                   "sha256": hashlib.sha256(b"new").hexdigest(), "url": "https://example.invalid/new.zip"}}
        def download(url, dest, **kwargs):
            self.assertEqual(url, release["asset"]["url"])
            Path(dest).write_bytes(b"new")
        with patch.object(whisper, "download_file", side_effect=download), patch.object(whisper, "install_archive") as install:
            self.assertTrue(whisper.download_runtime({"release": release})[0])
            install.assert_called_once()
            release["asset"]["sha256"] = "0" * 64
            install.reset_mock()
            self.assertFalse(whisper.download_runtime({"release": release})[0])
            install.assert_not_called()

    def test_optional_removal_is_confined_to_managed_directory(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(optional, "get_bin_root_dir", return_value=folder), patch.object(optional.platform, "system", return_value="Windows"):
            parent = Path(folder) / "bin" / "dependences"
            for name in ("vtracer", "ghostscript", "whisper.cpp", "ffmpeg"):
                (parent / name).mkdir(parents=True)
                (parent / name / "binary").write_text("test")
            self.assertTrue(optional.uninstall_optional("vtracer")[0])
            self.assertTrue(optional.uninstall_optional("ghostscript")[0])
            self.assertFalse(optional.uninstall_optional("../ffmpeg")[0])
            self.assertTrue((parent / "ffmpeg" / "binary").exists())
            self.assertTrue((parent / "whisper.cpp" / "binary").exists())
            with patch.object(optional.platform, "system", return_value="Linux"), patch.object(optional.shutil, "rmtree") as remove:
                self.assertFalse(optional.uninstall_optional("ghostscript")[0])
                remove.assert_not_called()


class OptionalDependencyUIContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_gear_navigates_to_dependencies_without_inline_runtime(self):
        from gui.tabs.ai_tools.transcription_panel import TranscriptionPanel, WhisperRuntimeCard
        from gui.tabs.settings.settings_view import SETTINGS_PAGE_DEPENDENCIES
        panel = TranscriptionPanel()
        panel.settings_overlay = Mock()
        try:
            panel.runtime_toggle.click()
            panel.settings_overlay.open_page.assert_called_once_with(SETTINGS_PAGE_DEPENDENCIES)
            panel.settings_overlay.settings_tab.page_deps.focus_dependency.assert_called_once_with("whisper")
            self.assertEqual(panel.findChildren(WhisperRuntimeCard), [])
        finally:
            panel.deleteLater()

    def test_whisper_card_uses_detected_release_and_disables_unavailable_package(self):
        from gui.tabs.ai_tools.transcription_panel import WhisperRuntimeCard
        with patch.object(whisper, "runtime_ready", return_value=True), patch.object(whisper, "get_local_version", return_value="1.9.5"):
            card = WhisperRuntimeCard(dependency_card=True)
            try:
                release = {"version": "v1.10.0", "asset": {"size": 123}}
                card.set_update_available(release)
                self.assertEqual(card.download.text(), "Actualizar")
                with patch.object(card, "_can_modify", return_value=True), patch("gui.tabs.ai_tools.transcription_panel.confirm_model_download", return_value=True), patch("gui.tabs.ai_tools.transcription_panel.model_downloads") as manager:
                    card._download()
                    self.assertEqual(manager.return_value.start.call_args.args[2]["release"], release)
                card.set_update_available({"version": "v1.10.0", "asset": None})
                self.assertFalse(card.download.isEnabled())
                self.assertTrue(card.import_button.isEnabled())
                card.set_update_available(None)
                self.assertIn("No se pudo comprobar", card.version.text())
            finally:
                card.deleteLater()

    def test_global_update_search_includes_whisper_and_routes_result(self):
        from gui.tabs.settings.pages import deps_page as deps
        page = Mock()
        page.gs_panel.is_installed = False
        with patch.object(deps, "UpdateCheckWorker") as worker, patch.object(deps, "check_wpc", return_value=False), patch.object(deps, "check_potprovider", return_value=False):
            deps.DependenciesPage.check_all_updates(page)
            configs = worker.call_args.args[0]
            config = next(c for c in configs if c["id"] == "whisper")
            self.assertIs(config["remote_func"], whisper.get_latest_release)
        release = {"version": "v1.10.0", "asset": None}
        deps.DependenciesPage.on_update_check_finished(page, {"whisper": {"local": "1.9.5", "remote": release}})
        page.whisper_panel.set_update_available.assert_called_once_with(release)

    def test_optional_buttons_disable_during_operation_and_survive_update_result(self):
        from gui.tabs.settings.pages import deps_page as deps
        with patch.object(deps, "check_vtracer", return_value=True), patch.object(deps, "vtracer_local", return_value="1.0"), patch.object(deps, "check_ghostscript", return_value=True), patch.object(deps, "gs_local", return_value="10.0"), patch.object(deps.platform, "system", return_value="Windows"):
            for cls in (deps.VtracerCardPanel, deps.GhostscriptCardPanel):
                card = cls()
                try:
                    received = []
                    card.uninstall_requested.connect(received.append)
                    card._btn_remove.click()
                    self.assertEqual(received, [card.dep_id])
                    card.set_downloading_state(True)
                    card.set_update_available("99.0")
                    self.assertFalse(card._btn_remove.isEnabled())
                    self.assertFalse(card._btn_action.isEnabled())
                    card.set_downloading_state(False)
                    self.assertTrue(card._btn_remove.isEnabled())
                finally:
                    card.deleteLater()


if __name__ == "__main__":
    unittest.main()
