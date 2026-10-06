# src/gui/tabs/image_tools/image_convert_worker.py
import os
import threading
import tempfile
import img2pdf

from PySide6.QtCore import QThread, Signal

from core.logger.logger_manager import logger
from core.tabs.image_tools import depth_engine, normal_engine, rembg_engine
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
    file_failed = Signal(str)                 # input_path -- error real (no cancelación ni "omitido")
    # input_path, ancho, alto -- resolución a la que se calculó el Mapa de
    # Profundidad de ese archivo. Se emite ANTES de file_completed, así quien la
    # use ya la tiene al mostrar el resultado (ver ImageToolsTab._depth_process_sizes).
    file_depth_info = Signal(str, int, int)
    # Igual que file_depth_info, para Mapa de Normales (solo MoGe-2: DeepBump trabaja a
    # resolución completa y no emite nada).
    file_normal_info = Signal(str, int, int)
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
        elif self.options.get("normals_enabled", False):
            base_name = f"{base_name}_normal"
        filename = base_name + ext

        output_folder = (self.options.get("output_folder") or "").strip()
        if output_folder and os.path.isdir(output_folder):
            return os.path.join(output_folder, filename)
        return os.path.join(os.path.dirname(input_path), filename)

    def _desired_merged_pdf_path(self) -> str:
        custom_name = (self.options.get("pdf_merged_name") or "").strip()
        if custom_name:
            base_name = os.path.splitext(custom_name)[0].strip()
            for ch in r'<>:"/\|?*':
                base_name = base_name.replace(ch, "")
            base_name = base_name.strip()
            if not base_name:
                base_name = "combined"
            filename = f"{base_name}.pdf"
        else:
            first_fp = self.filepaths[0]
            first_stem = self.titles.get(first_fp) or os.path.splitext(os.path.basename(first_fp))[0]
            filename = f"{first_stem}_combined.pdf"

        output_folder = (self.options.get("output_folder") or "").strip()
        if output_folder and os.path.isdir(output_folder):
            return os.path.join(output_folder, filename)
        return os.path.join(os.path.dirname(self.filepaths[0]), filename)


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
        # (Profundidad y Normales son excluyentes: cuentan como un solo motor.)
        onnx_sessions.set_min_capacity(
            int(bool(self.options.get("rembg_enabled")))
            + int(bool(self.options.get("depth_enabled") or self.options.get("normals_enabled"))))
        rembg_engine.prepare_session(self.options)
        depth_engine.prepare_session(self.options)
        normal_engine.prepare_session(self.options)
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

        if (
            str(self.options.get("format", "")).upper() == "PDF"
            and self.options.get("pdf_merge", False)
        ):
            self._run_pdf_merge_batch()
            return

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
                self.file_failed.emit(filepath)
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
                normal_size = info.get("normal_process_size")
                if normal_size:
                    self.file_normal_info.emit(filepath, int(normal_size[0]), int(normal_size[1]))
                self.file_completed.emit(filepath, output_path)
            else:
                rollback_backup(backup_path)
                self.file_status_changed.emit(filepath, self.tr("Error: {0}").format(message))
                if not self.cancellation_event.is_set():
                    self.file_failed.emit(filepath)

        self.finished_signal.emit(completed, total)

    # ── Combinar en un solo PDF ──────────────────────────────────────────────
    # Claves de opciones que modifican la imagen: con cualquiera activa, cada página
    # tiene que pasar por ImageConverter. Sin ninguna (y sin ediciones a mano en
    # source_overrides), el archivo original se mete tal cual en el PDF.
    _EDIT_OPTIONS = ("resize_enabled", "upscale_enabled", "rembg_enabled",
                     "depth_enabled", "normals_enabled", "canvas_enabled")
    # Orientaciones EXIF que img2pdf resuelve solo (con /Rotate). Las de espejo
    # (2, 4, 5, 7) las rechaza: esas páginas se convierten.
    _IMG2PDF_ORIENTATIONS = (None, 1, 3, 6, 8)

    def _original_usable_as_page(self, filepath: str) -> bool:
        """True si el archivo puede ir al PDF sin decodificarlo ni recomprimirlo.

        Es lo que hace rápida la combinación: img2pdf copia un JPEG byte a byte (sin
        pérdida y casi sin costo), mientras que convertir cada foto a PNG primero la
        hacía ~8 veces más pesada y tardaba casi un minuto con 15 fotos."""
        if filepath in self.source_overrides:
            return False  # tiene formas/pincel/Canvas hechos a mano
        if any(self.options.get(key) for key in self._EDIT_OPTIONS):
            return False
        ext = os.path.splitext(filepath)[1].lower()
        if ext not in (".jpg", ".jpeg", ".png"):
            return False
        try:
            from PIL import Image
            with Image.open(filepath) as im:
                if ext in (".jpg", ".jpeg"):
                    if im.mode not in ("RGB", "L"):
                        return False  # CMYK y similares: mejor convertir
                    return im.getexif().get(0x0112) in self._IMG2PDF_ORIENTATIONS
                # PNG
                if im.mode.startswith("I") or im.mode == "F":
                    return False  # 16 bits
                has_alpha = im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info
                return not has_alpha or bool(self.options.get("pdf_transparency", False))
        except Exception:
            return False

    def _page_options_for(self, filepath: str) -> tuple[dict, str]:
        """Opciones para convertir UNA página y la extensión del temporal. Una foto
        (origen JPEG) va a JPEG de calidad alta: a PNG pesaría ~8 veces más sin ganar
        nada. El resto va a PNG con compresión normal, sin pérdida (capturas, texto,
        mapas de profundidad o transparencia)."""
        options = dict(self.options)
        keep_alpha = bool(self.options.get("pdf_transparency", False))
        is_photo = os.path.splitext(filepath)[1].lower() in (".jpg", ".jpeg")
        if is_photo and not keep_alpha:
            options.update({"format": "JPG", "jpg_quality": 95,
                            "jpg_subsampling": "4:4:4 (Máxima)", "jpg_progressive": False})
            return options, ".jpg"
        options.update({"format": "PNG", "png_transparency": keep_alpha,
                        "png_compression": 6, "png_optimize": False})
        return options, ".png"

    def _convert_page(self, filepath: str, read_path: str, tmp_dir: str, idx: int):
        """Convierte una página a un temporal. Devuelve (ok, mensaje, ruta, info)."""
        options, ext = self._page_options_for(filepath)
        temp_page = os.path.join(tmp_dir, f"page_{idx:05d}{ext}")

        def progress_cb(pct, stage="processing", _filepath=filepath):
            stage_str = str(stage) if stage else "processing"
            if pct is None:
                self.busy_indeterminate.emit(_filepath, True, stage_str)
            else:
                self.busy_indeterminate.emit(_filepath, False, stage_str)
                self.file_progress.emit(_filepath, int(round(pct)), stage_str)

        info = {}
        try:
            ok, msg = self._converter.convert_file(
                read_path, temp_page, options,
                progress_callback=progress_cb,
                cancellation_event=self.cancellation_event,
                info=info,
            )
        except Exception as e:
            logger.error(f"ImageConvertWorker: fallo procesando página {filepath} para PDF: {e}")
            ok, msg = False, str(e)
        ok = ok and os.path.exists(temp_page)
        return ok, msg, temp_page, info

    def _write_merged_pdf(self, entries: list[dict], output_path: str, tmp_dir: str):
        """Escribe el PDF final. `entries`, en orden: {"kind": "image", "path"} o
        {"kind": "pdf", "path"} (un documento PDF/AI: se copia su primera página).

        Solo imágenes -> img2pdf directo al archivo (outputstream: armarlo en memoria
        con 15 fotos ocupaba cientos de MB de RAM). Con documentos -> cada tramo de
        imágenes se arma con img2pdf y todo se une con pikepdf, que copia la página
        del documento tal cual: el texto sigue siendo seleccionable y los vectores
        nítidos (convertirla a imagen los perdía).

        Imágenes a 96 ppp, como antes: los JPEG originales traen su propia resolución
        (72, 300...) y sin esto cada página saldría de un tamaño físico distinto."""
        layout = img2pdf.get_fixed_dpi_layout_fun((96, 96))
        try:
            if all(e["kind"] == "image" for e in entries):
                with open(output_path, "wb") as f:
                    img2pdf.convert([e["path"] for e in entries], outputstream=f, layout_fun=layout)
                return

            import pikepdf
            dst = pikepdf.new()
            opened = []  # pikepdf necesita los originales abiertos hasta guardar
            try:
                run, parts = [], 0
                for e in entries + [{"kind": "end"}]:
                    if e["kind"] == "image":
                        run.append(e["path"])
                        continue
                    if run:
                        part = os.path.join(tmp_dir, f"tramo_{parts:04d}.pdf")
                        parts += 1
                        with open(part, "wb") as f:
                            img2pdf.convert(run, outputstream=f, layout_fun=layout)
                        src = pikepdf.open(part)
                        opened.append(src)
                        dst.pages.extend(src.pages)
                        run = []
                    if e["kind"] == "pdf":
                        src = pikepdf.open(e["path"])
                        opened.append(src)
                        dst.pages.append(src.pages[0])
                        page = dst.pages[-1]
                        # Datos privados de Illustrator: pesan mucho y no se ven
                        if "/PieceInfo" in page.obj:
                            del page.obj["/PieceInfo"]
                dst.save(output_path)
            finally:
                for src in opened:
                    src.close()
                dst.close()
        except Exception:
            try:
                os.remove(output_path)  # no dejar un PDF a medias
            except OSError:
                pass
            raise

    def _document_usable_as_page(self, filepath: str, read_path: str) -> bool:
        """PDF/AI sin ediciones: su página va al PDF final sin convertirla en imagen."""
        if read_path != filepath or filepath in self.source_overrides:
            return False
        if any(self.options.get(key) for key in self._EDIT_OPTIONS):
            return False
        if os.path.splitext(filepath)[1].lower() not in (".pdf", ".ai"):
            return False
        try:
            import pikepdf
            with pikepdf.open(filepath) as pdf:
                return len(pdf.pages) >= 1
        except Exception:
            return False  # .ai antiguos (PostScript), cifrados...: se convierten

    def _run_pdf_merge_batch(self):
        total = len(self.filepaths)
        if total == 0:
            self.finished_signal.emit(0, 0)
            return

        policy = self.options.get("conflict_policy", "conservar")
        desired_path = self._desired_merged_pdf_path()

        try:
            output_path, backup_path = resolve_conflict(desired_path, policy)
        except Exception as e:
            logger.error(f"ImageConvertWorker: fallo resolviendo destino de PDF merge: {e}")
            for fp in self.filepaths:
                self.file_status_changed.emit(fp, self.tr("Error: {0}").format(e))
                self.file_failed.emit(fp)
            self.finished_signal.emit(0, total)
            return

        if output_path is None:
            # "omitir" con conflicto
            for fp in self.filepaths:
                self.file_status_changed.emit(fp, self.tr("Omitido (ya existe)"))
            self.finished_signal.emit(0, total)
            return

        # Páginas del PDF final, en orden. "original" = se usa el archivo tal cual (si
        # algo lo rechaza al final, esa página se convierte y se reintenta una vez).
        entries = []
        done_files = []
        failed = False
        with tempfile.TemporaryDirectory(prefix="dowp_pdf_merge_") as tmp_dir:
            for idx, filepath in enumerate(self.filepaths):
                if self.cancellation_event.is_set():
                    break

                read_path = self.source_overrides.get(filepath, filepath)
                if backup_path and os.path.normpath(desired_path) == os.path.normpath(filepath):
                    read_path = backup_path

                if self._document_usable_as_page(filepath, read_path):
                    entries.append({"fp": filepath, "kind": "pdf", "path": filepath, "original": True})
                elif read_path == filepath and self._original_usable_as_page(filepath):
                    entries.append({"fp": filepath, "kind": "image", "path": filepath, "original": True})
                else:
                    self.file_status_changed.emit(filepath, self.tr("Procesando..."))
                    ok, msg, temp_page, info = self._convert_page(filepath, read_path, tmp_dir, idx)
                    if self.cancellation_event.is_set():
                        break
                    if not ok:
                        failed = True
                        self.file_status_changed.emit(filepath, self.tr("Error: {0}").format(msg))
                        self.file_failed.emit(filepath)
                        for remaining_fp in self.filepaths[idx + 1:]:
                            self.file_status_changed.emit(remaining_fp, self.tr("Cancelado"))
                        break
                    entries.append({"fp": filepath, "kind": "image", "path": temp_page, "original": False})
                    depth_size = info.get("depth_process_size")
                    if depth_size:
                        self.file_depth_info.emit(filepath, int(depth_size[0]), int(depth_size[1]))
                    normal_size = info.get("normal_process_size")
                    if normal_size:
                        self.file_normal_info.emit(filepath, int(normal_size[0]), int(normal_size[1]))
                self.file_status_changed.emit(filepath, self.tr("Completado"))
                done_files.append(filepath)

            cancelled = self.cancellation_event.is_set()
            if failed or cancelled or not entries:
                # No hay PDF: lo ya procesado NO puede quedar como "Completado"
                for fp in self.filepaths:
                    if cancelled:
                        self.file_status_changed.emit(fp, self.tr("Cancelado"))
                    elif fp in done_files:
                        self.file_status_changed.emit(fp, self.tr("No se creó el PDF"))
                rollback_backup(backup_path)
                self.finished_signal.emit(0, total)
                return

            self.busy_indeterminate.emit(self.filepaths[0], True, "merging")
            try:
                try:
                    self._write_merged_pdf(entries, output_path, tmp_dir)
                except Exception as e:
                    originals = [i for i, ent in enumerate(entries) if ent["original"]]
                    if not originals:
                        raise
                    logger.warning(f"ImageConvertWorker: un original no se pudo usar tal cual ({e}); "
                                   f"se convierten {len(originals)} página(s) y se reintenta")
                    for i in originals:
                        fp = entries[i]["fp"]
                        ok, msg, temp_page, _info = self._convert_page(fp, fp, tmp_dir, 100000 + i)
                        if not ok:
                            raise Exception(msg)
                        entries[i] = {"fp": fp, "kind": "image", "path": temp_page, "original": False}
                    self._write_merged_pdf(entries, output_path, tmp_dir)

                commit_backup(backup_path)
                n_orig = sum(1 for ent in entries if ent["original"])
                logger.info(f"ImageConvertWorker: PDF fusionado con éxito en {output_path} "
                            f"({len(entries)} páginas, {n_orig} sin recomprimir)")
                for fp in self.filepaths:
                    self.file_completed.emit(fp, output_path)
                self.finished_signal.emit(total, total)
            except Exception as e:
                logger.error(f"ImageConvertWorker: fallo al fusionar PDF: {e}")
                rollback_backup(backup_path)
                for fp in self.filepaths:
                    self.file_status_changed.emit(fp, self.tr("Error: {0}").format(e))
                    self.file_failed.emit(fp)
                self.finished_signal.emit(0, total)
