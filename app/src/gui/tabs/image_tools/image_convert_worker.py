# src/gui/tabs/image_tools/image_convert_worker.py
import os
import threading

from PySide6.QtCore import QThread, Signal

from core.logger.logger_manager import logger
from core.tabs.image_tools import depth_engine, rembg_engine
from core.tabs.image_tools.image_converter import ImageConverter
from core.utils import onnx_sessions
from core.utils.config_manager import get_config
from core.utils.file_conflict_manager import resolve_conflict, commit_backup, rollback_backup

# Extensión de salida por formato -- "No Convertir" no está aquí a propósito, se
# resuelve en _desired_output_path() mirando la extensión de cada archivo de origen.
_EXT_BY_FORMAT = {
    "PNG": ".png", "JPG": ".jpg", "WEBP": ".webp", "AVIF": ".avif",
    "PDF": ".pdf", "SVG": ".svg", "TIFF": ".tiff", "ICO": ".ico", "ICNS": ".icns", "BMP": ".bmp",
}
_PASSTHROUGH_KEEP_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".tiff", ".tif", ".bmp"}


class ImageConvertWorker(QThread):
    """Convierte un lote de imágenes con las mismas opciones -- mismo patrón que
    ModelDownloadWorker (gui/widgets/model_download_prompt.py) pero iterando N
    archivos en vez de un solo item. El destino (carpeta + qué hacer si el archivo
    ya existe) se resuelve con core/utils/file_conflict_manager.resolve_conflict,
    la misma utilidad que ya usa el resto de la app (descargas) -- mismo respaldo
    reversible si la política es "sobrescribir": se confirma (se borra el .dbak) si
    la conversión de ESE archivo salió bien, o se revierte si falló/se canceló."""

    file_progress = Signal(str, int, str)          # filepath, %, stage
    # filepath, True/False, stage -- "no hay porcentaje real que mostrar ahora"
    # (Waifu2x/SRMD/rembg). Señal separada de file_progress con la etapa actual.
    busy_indeterminate = Signal(str, bool, str)
    file_status_changed = Signal(str, str)    # filepath, texto de estado
    file_completed = Signal(str, str)         # input_path, output_path -- solo en éxito
    # input_path, ancho, alto -- resolución a la que se calculó el Mapa de
    # Profundidad de ese archivo. Se emite ANTES de file_completed, así quien la
    # use ya la tiene al mostrar el resultado (ver ImageToolsTab._depth_process_sizes).
    file_depth_info = Signal(str, int, int)
    finished_signal = Signal(int, int)        # completados, total

    def __init__(self, filepaths: list[str], options: dict, titles: dict | None = None,
                 source_overrides: dict[str, str] | None = None, parent=None):
        super().__init__(parent)
        self.filepaths = list(filepaths)
        self.options = options
        self.titles = titles or {}
        # Fase 3 -- formas/pincel/Canvas manual ya aplanados a un PNG temporal por
        # ImageToolsTab._build_source_overrides (input_path original -> PNG con las
        # ediciones "horneadas"); ese PNG es lo que en realidad se lee/convierte
        # para esos archivos puntuales, el resto de la cola sigue leyendo del
        # archivo original sin pasar por aquí.
        self.source_overrides = source_overrides or {}
        self.cancellation_event = threading.Event()
        self._converter = ImageConverter()

    def cancel(self):
        self.cancellation_event.set()

    def _desired_output_path(self, input_path: str) -> str:
        fmt = self.options.get("format", "No Convertir")
        input_ext = os.path.splitext(input_path)[1].lower()
        if fmt == self.tr("No Convertir"):
            ext = input_ext if input_ext in _PASSTHROUGH_KEEP_EXTS else ".png"
        else:
            ext = _EXT_BY_FORMAT.get(fmt, ".png")

        base_name = self.titles.get(input_path) or os.path.splitext(os.path.basename(input_path))[0]
        # Reescalar IA: el nombre final siempre lleva la escala usada (ej. "_x4"),
        # así se distingue el resultado sin tener que abrirlo -- mismo criterio que
        # se charló con el usuario (solo escala, sin nombre de modelo -- eso puede
        # quedar largo/feo, ver core/constants.py::UPSCAYL_MODELS_MAP).
        if self.options.get("upscale_enabled", False):
            scale = str(self.options.get("upscale_scale") or "").strip().lower().replace("x", "")
            if scale:
                base_name = f"{base_name}_x{scale}"
        # Mapa de Profundidad: el resultado ya no es la foto sino un mapa en
        # grises, así que lleva "_depth" -- mismo criterio que la escala de
        # arriba, y evita que con "No Convertir" en la misma carpeta el mapa
        # choque con el nombre del original. Sufijo fijo en inglés, como "_x4":
        # es parte del nombre de archivo, no texto de la interfaz.
        if self.options.get("depth_enabled", False):
            base_name = f"{base_name}_depth"
        filename = base_name + ext

        output_folder = (self.options.get("output_folder") or "").strip()
        if output_folder and os.path.isdir(output_folder):
            return os.path.join(output_folder, filename)
        return os.path.join(os.path.dirname(input_path), filename)

    def run(self):
        # Precarga la sesión ONNX de Eliminar Fondo antes del lote (si aplica) --
        # así la primera imagen no paga sola el costo de inicialización. Por
        # defecto se libera al terminar el lote (éxito, error o cancelación); si
        # el usuario tildó "Mantener los modelos de IA cargados en memoria" en
        # Ajustes > Modelos, queda cargada para el próximo lote también -- evita
        # repetir la compilación inicial del grafo en GPU (la parte que más tarda
        # y más traba la pantalla) en cada conversión. Ver rembg_engine.py y
        # models_page.py::_on_persist_sessions_toggled (ese desmarcado libera al
        # toque, no hace falta esperar aquí a que corra otro lote).
        #
        # Si el lote usa los dos motores ONNX (Eliminar Fondo + Mapa de
        # Profundidad), la caché compartida tiene que poder tener los dos modelos
        # a la vez durante el lote -- con el límite por defecto de 1, cada imagen
        # cargaría y tiraría ambos (ver onnx_sessions.set_min_capacity).
        onnx_sessions.set_min_capacity(
            int(bool(self.options.get("rembg_enabled"))) + int(bool(self.options.get("depth_enabled"))))
        rembg_engine.prepare_session(self.options)
        depth_engine.prepare_session(self.options)
        try:
            self._run_batch()
        finally:
            onnx_sessions.set_min_capacity(0)
            if not get_config().get("rembg_persist_sessions", False):
                rembg_engine.clear_sessions()

    def _run_batch(self):
        total = len(self.filepaths)
        completed = 0
        policy = self.options.get("conflict_policy", "conservar")

        for filepath in self.filepaths:
            if self.cancellation_event.is_set():
                self.file_status_changed.emit(filepath, self.tr("Cancelado"))
                continue

            desired_path = self._desired_output_path(filepath)
            try:
                output_path, backup_path = resolve_conflict(desired_path, policy)
            except Exception as e:
                logger.error(f"ImageConvertWorker: fallo resolviendo destino de {filepath}: {e}")
                self.file_status_changed.emit(filepath, self.tr("Error: {0}").format(e))
                continue

            if output_path is None:
                # "omitir" con conflicto -- no es un error, el usuario eligió esto.
                self.file_status_changed.emit(filepath, self.tr("Omitido (ya existe)"))
                continue

            self.file_status_changed.emit(filepath, self.tr("Procesando..."))

            # Caso "sobrescribir" cuando la salida cae justo en el mismo path que el
            # ORIGEN (ej. "No Convertir" con destino = misma carpeta y mismo formato):
            # resolve_conflict() ya renombró ese archivo a backup_path antes de que
            # lleguemos aquí -- filepath ya no existe en ese momento, así que hay que
            # leer desde el backup en vez de desde filepath.
            read_path = self.source_overrides.get(filepath, filepath)
            if backup_path and os.path.normpath(desired_path) == os.path.normpath(filepath):
                read_path = backup_path

            def progress_cb(pct, stage="processing", _filepath=filepath):
                stage_str = str(stage) if stage else "processing"
                if pct is None:
                    self.busy_indeterminate.emit(_filepath, True, stage_str)
                else:
                    self.busy_indeterminate.emit(_filepath, False, stage_str)
                    self.file_progress.emit(_filepath, int(round(pct)), stage_str)

            info = {}
            try:
                success, message = self._converter.convert_file(
                    read_path, output_path, self.options,
                    progress_callback=progress_cb,
                    cancellation_event=self.cancellation_event,
                    info=info,
                )
            except Exception as e:
                logger.error(f"ImageConvertWorker: fallo inesperado con {filepath}: {e}")
                success, message = False, str(e)

            if success:
                commit_backup(backup_path)
                completed += 1
                self.file_status_changed.emit(filepath, self.tr("Completado"))
                depth_size = info.get("depth_process_size")
                if depth_size:
                    self.file_depth_info.emit(filepath, int(depth_size[0]), int(depth_size[1]))
                self.file_completed.emit(filepath, output_path)
            else:
                rollback_backup(backup_path)
                self.file_status_changed.emit(filepath, self.tr("Error: {0}").format(message))

        self.finished_signal.emit(completed, total)
