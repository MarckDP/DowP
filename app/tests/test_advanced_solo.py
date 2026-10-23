"""Final de una descarga en modo SOLO de Proceso Avanzado: el posprocesado (recodificación,
IA) y "Crear con IA" tienen que arrancar con el título real del medio.

Regresión: el commit 9c56619 borró la definición de `title` en on_solo_finished pero no sus
usos, y todo el posprocesado en SOLO fallaba en silencio con un NameError (desde v1.9.1).
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
# Las pruebas no escriben en el log real del usuario (ver logger_manager).
os.environ.setdefault("DOWP_NO_FILE_LOG", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from gui.tabs.advanced_process import download_controller as dc

REAL_TITLE = "Video real (1)"


class FakeWorker(QObject):
    """Como DownloadWorker, pero termina en cuanto arranca. Como DownloaderMaster, cambia el
    título del request_data por el definitivo (aquí, por un conflicto de nombre)."""
    progress = Signal(dict)
    job_finished = Signal(bool, str)
    finished = Signal()

    def __init__(self, request_data, cancellation_event=None):
        super().__init__()
        self.request_data = dict(request_data, title=REAL_TITLE)

    def start(self):
        self.job_finished.emit(True, "")
        self.finished.emit()


class FakeTab(QObject):
    pass


class AdvancedSoloFinishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def run_solo(self, request_data):
        tab = FakeTab()
        tab.queue_mgr = MagicMock()
        tab._collect_request_data = lambda: dict(request_data)
        tab.recode_controller = MagicMock()
        tab.recode_controller.ensure_ai_models_ready.return_value = True
        tab.url_bar = MagicMock()
        tab.output_options = MagicMock()
        tab.taskbar_manager = None
        tab._current_video_data = {"duration": 5}
        tab._current_history_key = None
        controller = dc.DownloadController(tab)
        errors = []
        previous = sys.excepthook
        # Un error dentro del final de la descarga (un slot de Qt) no se propaga: llega aquí.
        sys.excepthook = lambda *exc: errors.append(exc[1])
        try:
            with patch.object(dc, "DownloadWorker", FakeWorker), \
                    patch.object(dc, "download_history"), patch.object(dc, "get_sound_notifier"), \
                    patch.object(controller, "_ai_subtitles_ready", return_value=True), \
                    patch.object(controller, "_resolve_final_download_path", return_value="C:/v/Video real (1).mp4"), \
                    patch.object(controller, "_resolve_fragment_download_paths", return_value=[]), \
                    patch.object(controller, "_send_to_editor_if_enabled"), \
                    patch.object(controller, "_history_sync"), \
                    patch.object(controller, "_start_ai_subtitles") as subtitles, \
                    patch.object(controller, "_start_post_download_recode") as recode:
                controller.start_solo_download()
        finally:
            sys.excepthook = previous
        self.assertEqual(errors, [], f"El final de la descarga falló: {errors}")
        return subtitles, recode

    def test_ai_subtitles_start_with_the_real_title(self):
        subtitles, recode = self.run_solo({"title": "Video", "ai_subtitles": True})
        recode.assert_not_called()
        subtitles.assert_called_once()
        self.assertEqual(subtitles.call_args.args[1], ["C:/v/Video real (1).mp4"])
        self.assertEqual(subtitles.call_args.args[4], REAL_TITLE)

    def test_recode_starts_with_the_real_title(self):
        _subtitles, recode = self.run_solo({"title": "Video", "recode_enabled": True})
        recode.assert_called_once()
        self.assertEqual(recode.call_args.kwargs["title"], REAL_TITLE)


if __name__ == "__main__":
    unittest.main()
