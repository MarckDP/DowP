"""Regression checks without Internet, real weights, or changes to user settings."""
import hashlib
import io
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from core.setup import whisper_setup as setup
from core.tabs.video_tools import transcription_engine as engine
from core.whisper_catalog import WHISPER_MODELS


class TranscriptionTests(unittest.TestCase):
    def settings(self, **kwargs):
        return dict(transcription_model="small", container="srt", **kwargs)

    def test_model_task_constraints(self):
        for model in ("small.en", "large-v3-turbo", "large-v3-turbo-q5_0"):
            settings = self.settings(transcription_task="translate")
            settings["transcription_model"] = model
            with self.assertRaises(ValueError):
                engine.whisper_command("cli", "model", "audio", "output", settings)
        cmd = engine.whisper_command("cli", "model", "audio", "output", self.settings(transcription_task="translate"))
        self.assertIn("-tr", cmd)

    def test_english_only_and_literal_paths(self):
        settings = self.settings(transcription_language="es")
        settings["transcription_model"] = "small.en"
        with self.assertRaises(ValueError):
            engine.whisper_command("cli", "model", "audio", "output", settings)
        settings["transcription_language"] = "auto"
        cmd = engine.whisper_command("cli", "model path", "audio & name.wav", "output", settings, cpu=True)
        self.assertEqual(cmd[cmd.index("-l")+1], "en")
        self.assertIn("audio & name.wav", cmd)
        self.assertIn("-ng", cmd)

    def test_corrupt_download_preserves_existing_model(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "model.bin"
            target.write_bytes(b"old good model")
            info = {"file": target.name, "url": "https://example.invalid", "size_bytes": 3,
                    "sha256": hashlib.sha256(b"new").hexdigest()}
            def download(url, dest, **kwargs):
                Path(dest).write_bytes(b"bad")
            with patch.object(setup, "model_path", return_value=str(target)), patch.object(setup, "download_file", side_effect=download):
                self.assertFalse(setup.download_model(info)[0])
            self.assertEqual(target.read_bytes(), b"old good model")
            self.assertFalse(Path(str(target)+".part").exists())

    def test_uninstall_preserves_models_and_rejects_outside_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "bin" / "dependences" / "whisper.cpp"
            runtime.mkdir(parents=True)
            (runtime / "whisper-cli.exe").write_bytes(b"runtime")
            models = root / "bin" / "models" / "whisper"
            models.mkdir(parents=True)
            model = models / "ggml-tiny.bin"
            model.write_bytes(b"model")
            with patch.object(setup, "get_bin_root_dir", return_value=tmp):
                self.assertTrue(setup.uninstall_runtime()[0])
                self.assertFalse(runtime.exists())
                self.assertEqual(model.read_bytes(), b"model")
                with patch.object(setup, "runtime_dir", return_value=models):
                    self.assertFalse(setup.uninstall_runtime()[0])
                self.assertTrue(model.exists())

    def test_archive_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "bad.zip"
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("../escape", "bad")
            with self.assertRaises(ValueError):
                setup._extract(archive, Path(folder)/"extract")
            self.assertFalse((Path(folder)/"escape").exists())

    def test_tar_libraries_materialized_and_escape_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder)/"libs.tar.gz"
            with tarfile.open(archive,"w:gz") as t:
                for name, target in (("lib.so", "lib.so.1"), ("lib.so.1", "lib.so.1.2")):
                    entry=tarfile.TarInfo(name); entry.type=tarfile.SYMTYPE; entry.linkname=target; t.addfile(entry)
                entry=tarfile.TarInfo("lib.so.1.2"); entry.size=3; t.addfile(entry, io.BytesIO(b"lib"))
            setup._extract(archive, Path(folder)/"extract")
            self.assertEqual((Path(folder)/"extract/lib.so").read_bytes(),b"lib")
            with tarfile.open(archive,"w:gz") as t:
                entry=tarfile.TarInfo("bad"); entry.type=tarfile.SYMTYPE; entry.linkname="../escape"; t.addfile(entry)
            with self.assertRaises(ValueError):
                setup._extract(archive, Path(folder)/"other")

    def test_cancel_terminates_subprocess(self):
        event = threading.Event()
        timer = threading.Timer(.25, event.set)
        timer.start()
        started = time.monotonic()
        try:
            ok, _ = engine._run([sys.executable, "-c", "import time; time.sleep(30)"], event)
        finally:
            timer.cancel()
        self.assertFalse(ok)
        self.assertLess(time.monotonic()-started, 5)

    def test_pipeline_trim_and_failed_output_are_atomic(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/"audio.wav"; source.write_bytes(b"audio")
            target=Path(folder)/"out.srt"; target.write_text("previous")
            ffmpeg=Path(folder)/"ffmpeg"; ffmpeg.touch()
            commands=[]
            def run(cmd, *args):
                commands.append(cmd)
                if len(commands)==1:
                    Path(cmd[-1]).touch()
                    return True, ""
                return False, "decode failed"
            with patch.object(engine,"runtime_path",return_value="cli"), patch.object(engine,"model_ready",return_value=True), patch.object(engine,"get_ffmpeg_path",return_value=str(ffmpeg)), patch.object(engine,"_run",side_effect=run):
                ok,error=engine.run_transcription(str(source),str(target),self.settings(transcription_audio_track=1),trim_in=3,trim_out=9)
            self.assertFalse(ok)
            self.assertIn("decode failed",error)
            self.assertEqual(target.read_text(),"previous")
            self.assertEqual(commands[0][commands[0].index("-map")+1],"0:a:1")
            self.assertEqual(commands[0][commands[0].index("-ss")+1],"3.0")
            self.assertEqual(commands[0][commands[0].index("-t")+1],"6.0")
            self.assertFalse(list(Path(folder).glob("dowp-transcription-*")))


if __name__ == "__main__":
    unittest.main()
