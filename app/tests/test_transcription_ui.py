"""UI integration contracts without media downloads or changes to user presets."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
# Las pruebas no escriben en el log real del usuario (ver logger_manager).
os.environ.setdefault("DOWP_NO_FILE_LOG", "1")
from PySide6.QtWidgets import QApplication
from core.utils.preset_manager import PresetManager, IA_TOOLS_NAMESPACE, IA_POST_DOWNLOAD_FUNCTIONS
from gui.tabs.ai_tools.ai_tools_view import AIToolsOptions, AIToolsTab


class TranscriptionUIContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        from gui.styles import load_stylesheet
        cls.app.setStyleSheet(load_stylesheet())

    def test_tabs_and_saved_preset_keep_track_selection(self):
        previous = PresetManager._instance
        with tempfile.TemporaryDirectory() as folder, patch("core.utils.preset_manager._get_presets_path", return_value=str(Path(folder)/"presets.json")):
            PresetManager._instance = None
            options = AIToolsOptions()
            try:
                self.assertEqual([options.tabs.tabText(i) for i in range(5)],
                                 ["Preajustes", "Reescalado", "Profundidad", "Normales", "Transcripción"])
                options.tabs.setCurrentIndex(4)
                content = options.panel.transcription_content
                content.model.setCurrentIndex(content.model.findData("small"))
                content.set_audio_tracks([{"language": "en"}, {"language": "es"}])
                content.track.setCurrentIndex(content.track.findData(1))
                settings = options.get_ia_settings()
                manager = PresetManager.get_instance()
                manager.save_preset(IA_TOOLS_NAMESPACE, "Pista 2", settings,
                                    function="ia_transcripcion", job_type="TRANSCRIBE")
                # Reload from disk, then use the actual preset picker.
                manager._data = None
                self.assertEqual(manager.get_settings(IA_TOOLS_NAMESPACE, "Pista 2"), settings)
                bar = options.preset_bar_ia
                options.tabs.setCurrentIndex(0)
                bar.combo.blockSignals(True)
                bar.combo.setCurrentIndex(bar.combo.findData("Pista 2"))
                bar._active_name = "Pista 2"
                bar.combo.blockSignals(False)
                self.assertEqual(options.get_ia_settings()["transcription_audio_track"], 1)
                self.assertIsNone(options.get_recode_settings())
                self.assertNotIn("ia_transcripcion", IA_POST_DOWNLOAD_FUNCTIONS)
                options.tabs.setCurrentIndex(1)
                self.assertEqual(options.get_ia_settings()["ia_function"], "upscale")
                options.tabs.setCurrentIndex(4)
                self.assertEqual(options.get_ia_settings(), settings)
            finally:
                options.deleteLater()
                PresetManager._instance = previous

    def test_pages_keep_independent_options_and_natural_height(self):
        previous = PresetManager._instance
        PresetManager._instance = PresetManager()
        PresetManager._instance._data = {}
        options = AIToolsOptions()
        try:
            options.resize(600, 950)
            options.show()
            self.app.processEvents()
            parents = {key: page.parentWidget() for key, page in options.pages.items()}
            depth = options.pages["depth"]
            normals = options.pages["normals"]
            with patch.object(normals.normal_content, "_offer_download_if_missing"):
                normals.normal_content.combo_family.setCurrentIndex(1)
                normals.normal_content.combo_model.setCurrentIndex(1)
            depth.combo_smoothing.setCurrentIndex(3)
            normals.combo_smoothing.setCurrentIndex(1)
            depth.chk_recode.setChecked(True)
            options.tabs.setCurrentIndex(4)
            for index in (1, 2, 3, 4, 0, 3):
                options.tabs.setCurrentIndex(index)
                self.app.processEvents()
                for key, page in options.pages.items():
                    self.assertIs(page.parentWidget(), parents[key])
            self.assertEqual(depth.get_settings()["depth_smoothing"], "high")
            self.assertEqual(normals.get_settings()["normals_smoothing"], "low")
            self.assertTrue(depth.chk_recode.isChecked())
            self.assertFalse(normals.chk_recode.isChecked())
            content = normals.normal_content
            self.assertLessEqual(content.height(), content.heightForWidth(content.width()) + 2)
        finally:
            options.close()
            options.deleteLater()
            PresetManager._instance = previous

    def test_model_groups_icons_and_theme_refresh_preserve_selection(self):
        from PySide6.QtCore import Qt
        from core.whisper_catalog import WHISPER_MODELS
        from gui.tabs.ai_tools.transcription_panel import TranscriptionPanel
        from gui.styles import refresh_themed_styles
        with patch("gui.tabs.ai_tools.transcription_panel.setup.model_ready", return_value=False):
            panel = TranscriptionPanel()
            try:
                combo = panel.model
                headers = [combo.itemText(i) for i in range(combo.count()) if not combo.model().item(i).isEnabled()]
                self.assertEqual(len(headers), 6)
                ids = [combo.itemData(i) for i in range(combo.count()) if combo.itemData(i)]
                self.assertEqual(set(ids), set(WHISPER_MODELS))
                self.assertEqual(len(ids), len(WHISPER_MODELS))
                for i in range(combo.count()):
                    if combo.itemData(i):
                        self.assertFalse(combo.itemIcon(i).isNull())
                combo.setCurrentIndex(combo.findData("small"))
                self.assertIn("No descargado", combo.currentData(Qt.ToolTipRole))
                with patch("gui.tabs.ai_tools.transcription_panel.setup.model_ready", return_value=True):
                    panel._models_changed()
                    self.assertIn("Instalado", combo.currentData(Qt.ToolTipRole))
                    refresh_themed_styles()
                self.assertEqual(combo.currentData(), "small")
                panel.show()
                self.app.processEvents()
                self.assertEqual(panel.runtime_toggle.size().toTuple(), (32, 32))
                self.assertEqual(panel.runtime_toggle.text(), "")
                self.assertFalse(panel.runtime_toggle.icon().isNull())
            finally:
                panel.close()
                panel.deleteLater()

    def test_all_tracks_expand_once_and_keep_trim(self):
        class Queue:
            def __init__(self): self.keys = ["source.mkv"]; self.labels = {}
            def get_all_filepaths(self): return list(self.keys)
            def add_files(self, paths, allow_duplicates):
                keys = [f"track-{n}" for n in range(len(paths))]
                self.keys.extend(keys)
                return keys
            def remove_entries(self, keys): self.keys = [k for k in self.keys if k not in keys]
            def set_entry_label(self, key, label): self.labels[key] = label
        queue = Queue()
        view = SimpleNamespace(queue_widget=queue, _transcription_tracks={},
                               _trim_cache={"source.mkv": (2, 8)}, _clip_names={}, tr=lambda text: text)
        probe = SimpleNamespace(_extract_ffprobe_json=lambda *args: {"audio_streams": [{}, {}]})
        settings = {"transcription_audio_track": "all"}
        with patch("gui.tabs.ai_tools.ai_tools_view.FFprobeMetadataManager.get_instance", return_value=probe):
            entries = AIToolsTab._prepare_transcription_entries(view, queue.get_all_filepaths(), settings)
            self.assertEqual(len(entries), 2)
            self.assertEqual([view._transcription_tracks[e] for e in entries], [0, 1])
            self.assertTrue(all(view._trim_cache[e] == (2, 8) for e in entries))
            self.assertEqual(AIToolsTab._prepare_transcription_entries(view, entries, settings), entries)
            self.assertEqual(len(queue.keys), 2)


if __name__ == "__main__":
    unittest.main()
