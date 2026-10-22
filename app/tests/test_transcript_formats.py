"""Formatos de transcripción, detector de voz e incrustado, sin whisper ni Internet: el JSON
de entrada imita el de whisper-cli -ojf (con DTW)."""
import csv
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from core.setup import whisper_setup as setup
from core.tabs.video_tools import transcript_formats as tf
from core.tabs.video_tools import transcription_engine as engine


def _token(text, start_ms, dtw_cs=-1):
    return {"text": text, "offsets": {"from": start_ms, "to": start_ms}, "t_dtw": dtw_cs}


# Como en el JSON real: palabras partidas en fragmentos (" O", "jal", "á"), signos pegados
# y fragmentos especiales "[_...]" que no son texto.
_WHISPER_JSON = {
    "result": {"language": "es"},
    "transcription": [
        {"offsets": {"from": 0, "to": 2000}, "text": " ¡Ojalá llueva hoy!",
         "tokens": [_token("[_BEG_]", 0), _token(" ¡", 0, 10), _token("O", 0, 12), _token("jal", 0, 20),
                    _token("á", 0, 30), _token(" llue", 0, 60), _token("va", 0, 70), _token(" hoy", 0, 120),
                    _token("!", 0, 150), _token("[_TT_100]", 2000)]},
        {"offsets": {"from": 2100, "to": 4000}, "text": " Sí, {claro} que sí.",
         "tokens": [_token(" Sí", 2100, 215), _token(",", 2100, 230), _token(" {claro}", 2100, 260),
                    _token(" que", 2100, 320), _token(" sí.", 2100, 360)]},
        # Más de un segundo de pausa: otro párrafo.
        {"offsets": {"from": 6000, "to": 9000}, "text": " Una frase bastante más larga que el límite de caracteres por línea elegido.",
         "tokens": []},
    ],
}


class TranscriptFormatsTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        path = Path(self.folder.name) / "out.json"
        path.write_text(json.dumps(_WHISPER_JSON, ensure_ascii=False), encoding="utf-8")
        self.transcript = tf.load_whisper_json(path)

    def tearDown(self):
        self.folder.cleanup()

    def test_words_join_fragments_and_use_dtw_times(self):
        words = self.transcript["segments"][0]["words"]
        self.assertEqual([w["text"] for w in words], ["¡Ojalá", "llueva", "hoy!"])
        self.assertEqual([w["start"] for w in words], [0.1, 0.6, 1.2])
        self.assertEqual(words[-1]["end"], 2.0)
        self.assertEqual(self.transcript["language"], "es")

    def test_lines_respect_length_and_count(self):
        cues = tf.build_cues(self.transcript["segments"], "sentences", max_chars=20, max_lines=2)
        for cue in cues:
            self.assertLessEqual(len(cue["lines"]), 2)
            for line in cue["lines"]:
                self.assertLessEqual(len(" ".join(w["text"] for w in line)), 20)
        # Sin tiempos por palabra, los trozos del segmento largo cubren todo su tramo.
        long = [c for c in cues if c["start"] >= 6.0]
        self.assertGreater(len(long), 1)
        self.assertAlmostEqual(long[0]["start"], 6.0)
        self.assertAlmostEqual(long[-1]["end"], 9.0)

    def test_word_by_word_never_overlaps(self):
        cues = tf.build_cues(self.transcript["segments"], "words")
        for previous, current in zip(cues, cues[1:]):
            self.assertLessEqual(previous["end"], current["start"] + 1e-9)
        self.assertTrue(all(c["end"] - c["start"] >= 0.12 - 1e-9 for c in cues))

    def test_words_per_subtitle_are_balanced_within_sentences(self):
        def texts(n):
            return [tf._cue_text(c) for c in tf.build_cues(self.transcript["segments"], "words", 42, 1, n)]
        self.assertEqual(texts(1)[:3], ["¡Ojalá", "llueva", "hoy!"])
        # "Sí, {claro} que sí." son 4 palabras: de a 3 quedan 2 + 2, no 3 + 1.
        self.assertIn("Sí, {claro}", texts(3))
        self.assertIn("que sí.", texts(3))
        # Nunca cruza el final de una frase.
        self.assertNotIn("hoy! Sí,", " | ".join(texts(5)))

    def test_default_subtitle_presets(self):
        from core.utils.default_presets import build_default_presets
        presets = {p["name"]: p for p in build_default_presets() if p.get("function") == "ia_transcripcion"}
        self.assertEqual(sorted(presets), ["Letras de canciones (karaoke)", "Redes: 1 palabra", "Redes: 3 palabras",
                                           "Redes: 5 palabras", "Subtítulos estándar (cine y TV)"])
        for preset in presets.values():
            settings = preset["settings"]
            self.assertNotIn("transcription_model", settings)   # usan el modelo del usuario
            self.assertIn(settings["container"], tf.SUBTITLE_FORMATS)
            self.assertFalse(settings["transcription_vad"])
            self.assertEqual(preset["job_type"], "TRANSCRIBE")
        self.assertEqual(presets["Redes: 3 palabras"]["settings"]["transcription_max_words"], 3)

    def test_every_format_renders(self):
        for fmt in tf.ALL_FORMATS:
            with self.subTest(fmt=fmt):
                self.assertIn("llueva", tf.render(self.transcript, fmt, {}, title="Prueba"))
        ET.fromstring(tf.render(self.transcript, "ttml", {}))
        data = json.loads(tf.render(self.transcript, "json", {}))
        self.assertEqual(data["segments"][0]["words"][0]["text"], "¡Ojalá")
        rows = list(csv.reader(io.StringIO(tf.render(self.transcript, "csv", {}))))
        self.assertEqual(rows[0], ["start", "end", "text"])
        self.assertTrue(tf.render(self.transcript, "sbv", {}).startswith("0:00:00.000,0:00:02.000\n"))

    def test_text_layout_and_timestamps(self):
        paragraphs = tf.render(self.transcript, "txt", {"transcription_timestamps": True})
        self.assertEqual(paragraphs.count("\n\n"), 1)
        self.assertTrue(paragraphs.startswith("[00:00] ¡Ojalá"))
        lines = tf.render(self.transcript, "txt", {"transcription_text_layout": "segments"})
        self.assertEqual(len(lines.strip().splitlines()), 3)

    def test_escaping_per_format(self):
        ass = tf.render(self.transcript, "ass", {})
        self.assertNotIn("{claro}", ass)
        self.assertIn("(claro)", ass)
        page = tf.render(self.transcript, "html", {}, title="<b>")
        self.assertIn("&lt;b&gt;", page)
        rtf = tf.render(self.transcript, "rtf", {}, title="ñ 🎤 {x}")
        self.assertIn("\\u241?", rtf)
        self.assertIn("\\u-10180?\\u-8284?", rtf)
        self.assertIn("\\{x\\}", rtf)

    def test_karaoke_only_where_supported(self):
        options = {"transcription_split": "karaoke"}
        ass = tf.render(self.transcript, "ass", options)
        self.assertIn("{\\kf", ass)
        lrc = tf.render(self.transcript, "lrc", options)
        self.assertIn("<00:00.60>llueva", lrc)
        self.assertEqual(tf.split_mode("srt", "karaoke"), "sentences")
        self.assertNotIn("\\kf", tf.render(self.transcript, "srt", options))

    def test_ass_style_and_resolution(self):
        options = {"transcription_style_color": "#112233", "transcription_style_position": "top",
                   "transcription_style_size": 60, "transcription_video_size": (1080, 1920)}
        header = tf.render(self.transcript, "ass", options)
        self.assertIn("PlayResY: 1920", header)
        style = next(line for line in header.splitlines() if line.startswith("Style:")).split(",")
        self.assertEqual(style[2], "107")            # 60 px a 1080 de alto -> 1920 de alto
        self.assertEqual(style[3], "&H00332211")     # #RRGGBB -> &HAABBGGRR
        self.assertEqual(style[18], "8")             # arriba

    def test_csv_written_with_bom(self):
        target = Path(self.folder.name) / "t.csv"
        tf.write(self.transcript, "csv", target, {})
        self.assertTrue(target.read_bytes().startswith(b"\xef\xbb\xbf"))


class TranscriptionOptionsTests(unittest.TestCase):
    def settings(self, **kwargs):
        return {"transcription_model": "small", "container": "srt", **kwargs}

    def test_dtw_only_for_word_timings(self):
        plain = engine.whisper_command("cli", "m", "a", "o", self.settings())
        self.assertNotIn("-dtw", plain)
        self.assertIn("-ojf", plain)
        for fmt, split, expected in (("srt", "words", True), ("ass", "karaoke", True), ("srt", "karaoke", False),
                                     ("txt", "words", False)):
            with self.subTest(fmt=fmt, split=split):
                cmd = engine.whisper_command("cli", "m", "a", "o", self.settings(container=fmt, transcription_split=split))
                self.assertEqual("-dtw" in cmd, expected)
        burn = engine.whisper_command("cli", "m", "a", "o", self.settings(transcription_split="karaoke", transcription_embed="burn"))
        self.assertEqual(burn[burn.index("-dtw") + 1], "small")
        self.assertIn("-nfa", burn)

    def test_prompt_and_vad(self):
        cmd = engine.whisper_command("cli", "m", "a", "o", self.settings(transcription_prompt="  DowP,\n MoGe "))
        self.assertEqual(cmd[cmd.index("--prompt") + 1], "DowP, MoGe")
        with patch.object(engine, "vad_path", return_value=None):
            with self.assertRaises(ValueError):
                engine.whisper_command("cli", "m", "a", "o", self.settings(transcription_vad=True))
        with patch.object(engine, "vad_path", return_value="vad.bin"):
            cmd = engine.whisper_command("cli", "m", "a", "o", self.settings(transcription_vad=True,
                                                                             transcription_vad_preset="strict"))
        self.assertEqual(cmd[cmd.index("-vm") + 1], "vad.bin")
        self.assertEqual(cmd[cmd.index("-vt") + 1], "0.65")

    def test_vad_custom_values_are_clamped(self):
        args = engine.vad_arguments({"transcription_vad_preset": "custom", "transcription_vad_threshold": 2,
                                     "transcription_vad_pad_ms": -5, "transcription_vad_max_speech_s": 12})
        self.assertEqual(args[args.index("-vt") + 1], "0.95")
        self.assertEqual(args[args.index("-vp") + 1], "0")
        self.assertEqual(args[args.index("-vmsd") + 1], "12")
        self.assertNotIn("-vmsd", engine.vad_arguments({}))

    def test_installed_vad_prefers_newest_and_skips_incomplete(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(setup, "get_models_dir", return_value=folder):
            whisper = Path(folder) / "whisper"
            whisper.mkdir()
            (whisper / "ggml-silero-v6.2.0.bin").write_bytes(b"incompleto")
            self.assertIsNone(setup.installed_vad())
            (whisper / "ggml-silero-v10.0.0.bin").write_bytes(b"x")
            (whisper / "ggml-silero-v9.1.0.bin").write_bytes(b"x")
            self.assertEqual(setup.vad_local_version(), "10.0.0")
            self.assertTrue(setup.vad_is_newer({"variant": "v10.1.0"}, "10.0.0"))
            self.assertFalse(setup.vad_is_newer({"variant": "v9.9.9"}, "10.0.0"))

    def test_embed_container_and_mode(self):
        self.assertEqual(engine.embed_extension(".MP4", "track"), "mp4")
        self.assertEqual(engine.embed_extension(".avi", "track"), "mkv")
        self.assertEqual(engine.embed_extension(".mkv", "burn"), "mp4")
        self.assertEqual(engine.embed_mode(self.settings(container="txt", transcription_embed="burn")), "none")
        self.assertEqual(engine.embed_mode(self.settings(transcription_embed="track")), "track")

    def test_embed_commands(self):
        with patch.object(engine, "_probe_codecs", return_value=["mov_text", "hdmv_pgs_subtitle"]):
            cmd, _ = engine._embed_command("ffmpeg", "in.mp4", "subs.srt", "out.mp4", "track", {}, "es")
        self.assertIn("copy", cmd)
        self.assertIn("0:s:0", cmd)               # mov_text se conserva
        self.assertNotIn("0:s:1", cmd)            # PGS no cabe en MP4
        self.assertEqual(cmd[cmd.index("-c:s:1") + 1], "mov_text")
        self.assertIn("language=spa", cmd)
        trimmed, _ = engine._embed_command("ffmpeg", "in.mkv", "subs.ass", "out.mkv", "track", {}, None, 3, 5)
        self.assertIn("libx264", trimmed)         # recortar sin recodificar desfasaría los subtítulos
        self.assertEqual(trimmed[trimmed.index("-c:s:0") + 1], "ass")
        burn, style = engine._embed_command("ffmpeg", "in.mov", "subs.ass", "out.mp4", "burn", {}, "es")
        self.assertEqual(burn[burn.index("-vf") + 1], "ass=subs.ass:fontsdir=fonts")
        self.assertIsNotNone(style)

    def test_language_in_name_like_ytdlp(self):
        with tempfile.TemporaryDirectory() as folder:
            out = str(Path(folder) / "video.srt")
            self.assertEqual(Path(engine.language_output_path(out, {}, "es")).name, "video.es.srt")
            translate = {"transcription_task": "translate"}
            self.assertEqual(Path(engine.language_output_path(out, translate, "es")).name, "video.en.srt")
            # Sin idioma detectado usa el elegido; uno inválido no entra en el nombre.
            self.assertEqual(Path(engine.language_output_path(out, {"transcription_language": "pt"}, None)).name, "video.pt.srt")
            self.assertEqual(Path(engine.language_output_path(out, {}, "auto")).name, "video.srt")
            (Path(folder) / "video.es.srt").write_text("previo")
            self.assertEqual(Path(engine.language_output_path(out, {}, "es")).name, "video.es (1).srt")
            self.assertEqual(Path(engine.language_output_path(out, {"transcription_overwrite": True}, "es")).name, "video.es.srt")

    def test_playlist_item_subtitles(self):
        from core.utils import queue_manager

        class Signal:
            def __init__(self):
                self.calls = []

            def emit(self, *args):
                self.calls.append(args)

        class Worker:
            job_progress_changed = Signal()

            def tr(self, text):
                return text

        class Job:
            job_id = "p1"
            progress = 0
            config = {"ai_subtitles_settings": {"transcription_model": "small", "container": "vtt"},
                      "conflict_policy": "sobrescribir"}
            outputs = []

            def add_output_files(self, paths, is_stem_source=True):
                self.outputs.extend(paths)

        def fake_run(media, out, settings, **kwargs):
            kwargs["progress_callback"](50, None)
            settings["_final_output_path"] = out.replace(".vtt", ".es.vtt")
            seen.update(media=media, out=out, overwrite=settings["transcription_overwrite"])
            return True, ""

        seen = {}
        with tempfile.TemporaryDirectory() as folder:
            media = Path(folder) / "01 - Video.mp4"
            media.write_bytes(b"x")
            job = Job()
            with patch("core.tabs.video_tools.transcription_engine.run_transcription", side_effect=fake_run):
                queue_manager.QueueWorker._transcribe_playlist_item(Worker(), job, str(media), 10, None,
                                                                    item_pos=2, item_total=4)
            self.assertEqual(seen["out"], str(Path(folder) / "01 - Video.vtt"))
            self.assertTrue(seen["overwrite"])
            self.assertEqual(job.outputs, [str(Path(folder) / "01 - Video.es.vtt")])
            self.assertIn("[2/4]", Worker.job_progress_changed.calls[-1][2])
            # Los ajustes del job no se tocan (cada ítem parte de los mismos).
            self.assertNotIn("_final_output_path", job.config["ai_subtitles_settings"])

    def test_mkv_ass_track_attaches_font_by_name(self):
        with tempfile.TemporaryDirectory() as folder:
            font = Path(folder) / "Fuente-Bold.ttf"
            font.write_bytes(b"ttf")
            settings = {"transcription_style_font_file": str(font)}
            with patch.object(engine, "_probe_codecs", return_value=[]), \
                    patch.object(engine, "_probe_count", return_value=2):
                cmd, _ = engine._embed_command("ffmpeg", "in.mkv", "subs.ass", "out.mkv", "track", settings, "es")
                self.assertEqual(cmd[cmd.index("-attach") + 1], str(font))
                self.assertIn("mimetype=application/x-truetype-font", cmd)
                self.assertIn("-metadata:s:t:2", cmd)         # después de los 2 adjuntos que ya tenía
                self.assertIn("filename=Fuente-Bold.ttf", cmd)  # sin la ruta del equipo
                # En MP4 (mov_text, sin estilo) o con SRT no tiene sentido adjuntarla.
                mp4, _ = engine._embed_command("ffmpeg", "in.mp4", "subs.srt", "out.mp4", "track", settings, "es")
                srt, _ = engine._embed_command("ffmpeg", "in.mkv", "subs.srt", "out.mkv", "track", settings, "es")
            self.assertNotIn("-attach", mp4)
            self.assertNotIn("-attach", srt)


if __name__ == "__main__":
    unittest.main()
