# src/core/tabs/image_tools/image_converter.py
from PySide6.QtCore import QCoreApplication
"""Motor de conversión de formatos de imagen para "Convertir" (Editor de Imagen).

Reemplaza los binarios externos que usaba DowP1 (Ghostscript/Poppler/Inkscape) por
librerías puro-pip con wheels para Windows/macOS/Linux -- ver la nota en
core/constants.py justo después de UPSCALING_TOOLS. Única excepción: EPS/PS no
tiene equivalente puro-pip (necesita un intérprete de PostScript real), así que
en Windows usa Ghostscript como dependencia OPCIONAL (ver
core/setup/ghostscript_setup.py y _load_eps_ps más abajo) -- en Mac/Linux todavía
no hay build bundleable, sigue sin soporte (ver el TODO en esa misma nota)."""
import io
import os

from PIL import Image, ImageOps

from core.logger.logger_manager import logger
from core.tabs.editing_media.editing_media_logic import RAW_EXTS
from core.constants import INTERPOLATION_METHODS, CANVAS_PRESET_SIZES
from core.tabs.image_tools.convert_options import OUTPUT_FORMATS

# Registro de plugins de Pillow -- opcionales a propósito (mismo criterio que
# CAN_SVG/CAN_PDF en el image_converter.py de DowP1): si faltan, solo se
# deshabilita ese formato puntual (AVIF de salida / HEIC de entrada), en vez de
# tirar abajo el arranque de toda la app con un ImportError a nivel de módulo.
try:
    import pillow_avif  # noqa: F401 -- registra el plugin AVIF de Pillow al importar.
    CAN_AVIF = True
except ImportError:
    CAN_AVIF = False
    logger.warning("Convertir: 'pillow-avif-plugin' no instalado -- no se podrá convertir a AVIF.")

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    logger.warning("Convertir: 'pillow-heif' no instalado -- no se podrán leer archivos HEIC/HEIF.")

_RESIZE_METHOD_MAP = {
    "LANCZOS": Image.Resampling.LANCZOS,
    "BICUBIC": Image.Resampling.BICUBIC,
    "BILINEAR": Image.Resampling.BILINEAR,
    "NEAREST": Image.Resampling.NEAREST,
}

_EPS_PS_EXTS = {".eps", ".ps"}
_SVG_EXTS = {".svg", ".svgz"}
_PDF_LIKE_EXTS = {".pdf", ".ai"}
_VECTOR_EXTS = _SVG_EXTS | _PDF_LIKE_EXTS

_DEFAULT_VECTOR_DPI = 300

_EXT_TO_PASSTHROUGH_FORMAT = {
    ".png": "PNG", ".jpg": "JPG", ".jpeg": "JPG", ".webp": "WEBP",
    ".tiff": "TIFF", ".tif": "TIFF", ".bmp": "BMP",
}


class UnsupportedFormatError(Exception):
    """Formato de entrada reconocido por la cola (ver VALID_VECTOR_EXTS en
    editing_media_logic.py) pero sin soporte de conversión todavía -- hoy: EPS/PS."""


class ImageConverter:
    """Convierte un archivo de imagen a otro formato/tamaño. Sin estado propio entre
    llamadas -- una instancia se puede reusar para todo un lote (ver
    gui/tabs/image_tools/image_convert_worker.py)."""

    def convert_file(self, input_path: str, output_path: str, options: dict,
                      progress_callback=None, cancellation_event=None,
                      info: dict | None = None) -> tuple[bool, str]:
        """`info`, si se pasa, se rellena con datos del proceso de ESTE archivo
        que quien llama puede querer mostrar -- hoy solo "depth_process_size"
        ((ancho, alto) al que se calculó el Mapa de Profundidad, ver
        ImageConvertWorker.file_depth_info). Va por parámetro y no como
        atributo porque esta clase es adrede sin estado entre llamadas."""
        def report(pct, stage="processing"):
            if progress_callback:
                try:
                    progress_callback(pct, stage)
                except TypeError:
                    progress_callback(pct)

        try:
            report(5, "loading")
            if cancellation_event and cancellation_event.is_set():
                return False, QCoreApplication.translate("ImageConverter", "Cancelado por el usuario.")

            input_ext = os.path.splitext(input_path)[1].lower()
            output_format = options.get("format", OUTPUT_FORMATS[0]).upper()
            logger.info(f"Convertir: {input_path} -> {output_format} ({output_path})")

            resize_enabled = options.get("resize_enabled", False)
            target_size = None
            maintain_aspect = options.get("resize_maintain_aspect", True)
            if resize_enabled:
                width, height = options.get("resize_width"), options.get("resize_height")
                if width and height:
                    target_size = (int(width), int(height))

            img = self._load_image(input_path, input_ext, target_size, maintain_aspect, options)
            try:
                report(40, "loading")
                if cancellation_event and cancellation_event.is_set():
                    return False, QCoreApplication.translate("ImageConverter", "Cancelado por el usuario.")

                # Los formatos vectoriales ya se renderizaron directo al tamaño objetivo
                # dentro de _load_image (DPI/escala calculados ahí) -- un resize posterior
                # solo aplica a raster/RAW, que se cargan siempre a tamaño nativo.
                if resize_enabled and target_size and input_ext not in _VECTOR_EXTS:
                    report(45, "resize")
                    img = self._resize_raster_image(img, target_size, maintain_aspect, options)
                    report(55, "resize")
                if cancellation_event and cancellation_event.is_set():
                    return False, QCoreApplication.translate("ImageConverter", "Cancelado por el usuario.")

                # Eliminar Fondo IA -- mismo orden que usaba DowP1 (Redimensionar ->
                # Eliminar Fondo -> Reescalar IA): se corta el fondo ANTES de reescalar,
                # así el reescalado IA trabaja sobre el recorte, no sobre fondo que se
                # va a tirar.
                if options.get("rembg_enabled", False):
                    report(55, "rembg")
                    img = self._apply_rembg(img, options, report)
                    report(70, "rembg")
                if cancellation_event and cancellation_event.is_set():
                    return False, QCoreApplication.translate("ImageConverter", "Cancelado por el usuario.")

                # Mapa de Profundidad -- DESPUÉS de Eliminar Fondo a propósito: el
                # recorte solo toca el alfa, así que el modelo sigue viendo la
                # escena completa y el mapa hereda ese alfa (solo la profundidad
                # del sujeto). Antes de Reescalar/Canvas, que trabajan sobre lo
                # que salga de aquí.
                if options.get("depth_enabled", False):
                    report(70, "depth")
                    img, process_size = self._apply_depth(img, options, report)
                    if info is not None:
                        info["depth_process_size"] = process_size
                    report(72, "depth")
                if cancellation_event and cancellation_event.is_set():
                    return False, QCoreApplication.translate("ImageConverter", "Cancelado por el usuario.")

                # Reescalar IA -- son ejes independientes de Eliminar Fondo, no se
                # descartan entre sí (se puede recortar Y reescalar en el mismo lote).
                if options.get("upscale_enabled", False):
                    report(72, "upscale")
                    # Los motores de reescalado trabajan con imágenes de 8 bits.
                    img = self._downconvert_16bit(img)
                    img = self._apply_ai_upscale(img, options, cancellation_event, report)
                    report(85, "upscale")

                # Canvas (preset del menú, ajuste de lote) -- último paso antes de
                # guardar, mismo orden que DowP1 (resize -> upscale IA -> canvas).
                if options.get("canvas_enabled", False):
                    report(85, "canvas")
                    img = self._apply_canvas(self._downconvert_16bit(img), options)
                    report(92, "canvas")

                report(93, "saving")
                if output_format == OUTPUT_FORMATS[0].upper():
                    self._save_passthrough(img, input_ext, output_path, options)
                else:
                    self._save_as(img, output_format, output_path, options)

                report(100, "saving")
                logger.info(f"Convertir: {input_path} -> OK ({output_path})")
                return True, QCoreApplication.translate("image_converter", "Conversión completada.")
            finally:
                # Cerrar la imagen PIL explícitamente para liberar file handles y buffers
                # mapeados en memoria (decodificadores HEIC/RAW/PSD retienen bloques
                # grandes). Sin esto, quedan vivos hasta que el GC los recoja, que en
                # lotes de muchas imágenes puede ser mucho después.
                try:
                    img.close()
                except Exception:
                    pass
        except UnsupportedFormatError as e:
            logger.warning(f"Convertir: {input_path} -> {e}")
            return False, str(e)
        except Exception as e:
            logger.error(f"Convertir: fallo al procesar {input_path}: {e}")
            return False, str(e)

    # ------------------------------------------------------------------
    # Carga
    # ------------------------------------------------------------------
    def _load_image(self, filepath, ext, target_size, maintain_aspect, options):
        if ext in RAW_EXTS:
            return self._load_raw(filepath)
        if ext in _EPS_PS_EXTS:
            return self._load_eps_ps(filepath, target_size, maintain_aspect, options)
        if ext in _SVG_EXTS:
            return self._load_svg(filepath, target_size, maintain_aspect, options)
        if ext in _PDF_LIKE_EXTS:
            return self._load_pdf_like(filepath, target_size, maintain_aspect, options)
        return Image.open(filepath)

    def _load_raw(self, filepath):
        """Revela RAW con rawpy/LibRaw -- mismos parámetros que ya usaba DowP1."""
        import rawpy
        with rawpy.imread(filepath) as raw:
            rgb = raw.postprocess(
                use_camera_wb=True, half_size=False, no_auto_bright=False,
                output_bps=8, output_color=rawpy.ColorSpace.sRGB,
                demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD, use_auto_wb=False,
                gamma=(2.222, 4.5), bright=1.0, highlight_mode=rawpy.HighlightMode.Blend,
            )
        img = Image.fromarray(rgb)
        return ImageOps.exif_transpose(img)

    def _load_svg(self, filepath, target_size, maintain_aspect, options):
        """Renderiza SVG con resvg_py -- reemplaza CairoSVG+fallback Inkscape de
        DowP1, sin depender de libcairo del sistema (wheel autocontenido)."""
        import resvg_py
        kwargs = {"svg_path": filepath}
        if target_size:
            width, height = target_size
            kwargs["width"] = width
            if not maintain_aspect:
                kwargs["height"] = height
        png_bytes = bytes(resvg_py.svg_to_bytes(**kwargs))
        img = Image.open(io.BytesIO(png_bytes))
        img.load()
        if target_size:
            # resvg ya renderiza cerca del tamaño pedido, pero el ancho/alto exacto
            # (con proporción mantenida) se corrige aquí -- mismo criterio que DowP1
            # aplicaba sobre la salida de CairoSVG.
            img = self._resize_raster_image(img, target_size, maintain_aspect, options)
        return img

    def _load_pdf_like(self, filepath, target_size, maintain_aspect, options, transparent=True):
        """Renderiza PDF/AI con pypdfium2 -- reemplaza Poppler (vía pdf2image) de
        DowP1. La inmensa mayoría de .ai modernos (Illustrator 9+) son PDF válido
        por dentro; los .ai pre-PDF (PostScript puro) caen en UnsupportedFormatError,
        mismo bucket que EPS/PS.
        `transparent`: True (por defecto) para la conversión real -- el área sin
        tinta del PDF sale sin fondo, tal cual DowP1 con "PDF Transparente". La
        vista previa (preview_panel.py) pide transparent=False para verse como un
        documento normal (fondo blanco), la transparencia real solo importa en el
        archivo final."""
        import pypdfium2 as pdfium
        try:
            pdf = pdfium.PdfDocument(filepath)
        except Exception as e:
            raise UnsupportedFormatError(
                QCoreApplication.translate(
                    "image_converter",
                    "No se pudo abrir como PDF ({0}): {1}. "
                    "Los .ai muy antiguos (pre-PDF, PostScript puro) no están soportados."
                ).format(os.path.basename(filepath), e)
            )
        try:
            page = pdf[0]
            try:
                if target_size:
                    scale = self._calculate_optimal_dpi(page, target_size, maintain_aspect) / 72.0
                else:
                    scale = _DEFAULT_VECTOR_DPI / 72.0
                fill_color = (0, 0, 0, 0) if transparent else (255, 255, 255, 255)
                bitmap = page.render(scale=scale, fill_color=fill_color)
                img = bitmap.to_pil()
            finally:
                page.close()
        finally:
            pdf.close()
        if target_size:
            img = self._resize_raster_image(img, target_size, maintain_aspect, options)
        return img

    def _load_eps_ps(self, filepath, target_size, maintain_aspect, options):
        """EPS/PS -> PDF temporal vía Ghostscript (dependencia opcional, solo
        Windows por ahora -- ver core/setup/ghostscript_setup.py), reusando
        _load_pdf_like para el renderizado en sí -- mismo comando que usaba
        DowP1 (image_converter.pyc decompilado, líneas 592-594)."""
        from core.setup.ghostscript_setup import check_ghostscript, get_gs_exe_path, get_install_info

        if not check_ghostscript():
            import platform as _platform
            if _platform.system() == "Windows":
                hint = QCoreApplication.translate("ImageConverter", "instálalo desde Ajustes > Dependencias, o acepta la descarga que te ofrece Convertir.")
            else:
                label, cmd = get_install_info()
                hint = QCoreApplication.translate("image_converter", "instálalo desde tu terminal vía {0}: {1}").format(label, cmd)
            raise UnsupportedFormatError(
                f"{os.path.splitext(filepath)[1].upper()} necesita Ghostscript -- {hint}"
            )

        import subprocess
        import tempfile

        gs_exe = get_gs_exe_path()
        with tempfile.TemporaryDirectory(prefix="dowp_eps_") as tmp_dir:
            temp_pdf = os.path.join(tmp_dir, "converted.pdf")
            cmd = [
                gs_exe, "-dNOPAUSE", "-dBATCH", "-dSAFER", "-sDEVICE=pdfwrite",
                "-dEPSCrop", f"-sOutputFile={temp_pdf}", filepath,
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if result.returncode != 0 or not os.path.exists(temp_pdf):
                raise UnsupportedFormatError(
                    QCoreApplication.translate(
                        "image_converter",
                        "Ghostscript no pudo convertir {0}: {1}"
                    ).format(os.path.basename(filepath), result.stderr[:300])
                )
            return self._load_pdf_like(temp_pdf, target_size, maintain_aspect, options)

    def _calculate_optimal_dpi(self, page, target_size, maintain_aspect) -> float:
        """Sondea el tamaño real de la página (puntos, 72/pulgada) para calcular el
        DPI que rasteriza justo al tamaño objetivo -- pypdfium2 devuelve esto directo
        con page.get_size(), a diferencia de DowP1, que tenía que parsear el texto de
        pdfinfo (Poppler) con una regex."""
        target_width, target_height = target_size
        doc_width_pts, doc_height_pts = page.get_size()
        doc_width_pts = max(1.0, doc_width_pts)
        doc_height_pts = max(1.0, doc_height_pts)
        dpi_width = target_width / (doc_width_pts / 72.0)
        dpi_height = target_height / (doc_height_pts / 72.0)
        optimal_dpi = min(dpi_width, dpi_height) if maintain_aspect else max(dpi_width, dpi_height)
        return max(72.0, min(optimal_dpi, 4800.0))

    def _resize_raster_image(self, img, target_size, maintain_aspect, options):
        """Reescala una imagen raster con el método de interpolación elegido --
        portado 1:1 de DowP1, reusa INTERPOLATION_METHODS ya definido en
        core/constants.py."""
        target_width, target_height = target_size
        original_width, original_height = img.size
        method_label = options.get("interpolation_method", "Lanczos (Mejor Calidad)")
        method_key = INTERPOLATION_METHODS.get(method_label, "LANCZOS")
        resampling = _RESIZE_METHOD_MAP.get(method_key, Image.Resampling.LANCZOS)

        if not maintain_aspect:
            return img.resize((target_width, target_height), resampling)

        original_aspect = original_width / original_height
        target_aspect = target_width / target_height
        if original_aspect > target_aspect:
            new_width, new_height = target_width, int(target_width / original_aspect)
        else:
            new_height, new_width = target_height, int(target_height * original_aspect)
        if new_width > target_width:
            new_width, new_height = target_width, int(target_width / original_aspect)
        if new_height > target_height:
            new_height, new_width = target_height, int(target_height * original_aspect)
        return img.resize((new_width, new_height), resampling)

    def _apply_ai_upscale(self, img, options: dict, cancellation_event=None, progress_callback=None):
        """Corre el motor de Reescalar IA (Waifu2x/SRMD/Upscayl, ver
        core/tabs/image_tools/upscale_engine.py) sobre `img` -- los 3 son binarios
        externos (archivo-a-archivo), así que hay que volcar la imagen a un PNG
        temporal, invocar el motor, y recargar el resultado como PIL.Image.

        Este paso suele ser el más lento de todo convert_file() (inferencia por
        GPU) -- antes quedaba "clavado" en el 70% del progreso general mientras
        corría, sin ningún indicio de que seguía trabajando. Aquí se mapea el
        progreso propio del motor (0-100, ver run_upscale) al tramo 70-85 del
        progreso general (después de Eliminar Fondo, ver _apply_rembg), mismo
        criterio que usaba DowP1 para el reescalado de video (video_upscaler.pyc:
        `pct = 15 + done/total*70`, un sub-rango del progreso total). run_upscale()
        llama con `None` en vez de un número cuando el motor no imprime progreso
        real (Waifu2x/SRMD, confirmado corriéndolos) -- se reenvía tal cual, es
        responsabilidad de quien consume el progress_callback general mostrar un
        estado indeterminado en ese caso en vez de inventar un porcentaje."""
        import tempfile
        from core.tabs.image_tools.upscale_engine import run_upscale

        def upscale_progress(pct, *args):
            if not progress_callback:
                return
            if pct is None:
                try:
                    progress_callback(None, "upscale")
                except TypeError:
                    progress_callback(None)
            else:
                mapped = 70 + (pct / 100.0) * 15
                try:
                    progress_callback(mapped, "upscale")
                except TypeError:
                    progress_callback(mapped)

        with tempfile.TemporaryDirectory(prefix="dowp_upscale_") as tmp_dir:
            temp_in = os.path.join(tmp_dir, "in.png")
            temp_out = os.path.join(tmp_dir, "out.png")
            img.save(temp_in, "PNG")

            success, message = run_upscale(
                temp_in, temp_out, options, cancellation_event,
                progress_callback=upscale_progress,
            )
            if not success:
                raise Exception(f"Reescalar IA: {message}")

            result = Image.open(temp_out)
            result.load()
            return result

    def _apply_rembg(self, img, options: dict, progress_callback=None):
        """Corre Eliminar Fondo IA (ver core/tabs/image_tools/rembg_engine.py) sobre
        `img` y aplica el post-procesado de borde (suavizado/expansión) si el
        usuario configuró alguno en el popover -- mismo orden que DowP1
        (remove_background, después _apply_alpha_postprocess)."""
        from core.tabs.image_tools.rembg_engine import apply_alpha_postprocess, remove_background

        def rembg_cb(pct=None, *args):
            if progress_callback:
                try:
                    progress_callback(pct, "rembg")
                except TypeError:
                    progress_callback(pct)

        img = remove_background(img, options, progress_callback=rembg_cb)
        smooth = int(options.get("rembg_smooth", 0) or 0)
        expand = int(options.get("rembg_expand", 0) or 0)
        return apply_alpha_postprocess(img, smooth, expand)

    def _apply_depth(self, img, options: dict, progress_callback=None):
        """Corre Mapa de Profundidad (ver core/tabs/image_tools/depth_engine.py)
        sobre `img`. Devuelve (mapa, (ancho, alto) de proceso)."""
        from core.tabs.image_tools.depth_engine import estimate_depth

        def depth_cb(pct=None, *args):
            if progress_callback:
                try:
                    progress_callback(pct, "depth")
                except TypeError:
                    progress_callback(pct)

        # Una fuente de 16 bits (PNG/TIFF en gris) se baja a 8 bits antes: el
        # convert("RGB") del motor recortaría sus valores en vez de escalarlos.
        return estimate_depth(self._downconvert_16bit(img), options, progress_callback=depth_cb)

    @staticmethod
    def _downconvert_16bit(img):
        """Gris de 16 bits (el Mapa de Profundidad con "Salida de 16 bits") ->
        gris de 8 bits. Hace falta en todo paso que no sea guardar en PNG/TIFF:
        el convert("RGB"/"L") de Pillow sobre "I;16" RECORTA los valores a 255 en
        vez de escalarlos, y el mapa saldría casi entero en blanco."""
        if img.mode not in ("I;16", "I;16L", "I;16B", "I"):
            return img
        import numpy as np
        values = np.asarray(img, dtype=np.float64)
        max_value = 65535.0 if img.mode.startswith("I;16") else max(1.0, float(values.max()))
        return Image.fromarray(np.clip(values / max_value * 255 + 0.5, 0, 255).astype(np.uint8))

    def _apply_canvas(self, img, options: dict):
        """Canvas como ajuste de LOTE (preset elegido en el popover, clic derecho) --
        puerto directo de _apply_canvas_by_option/_calculate_canvas_position de
        DowP1 (image_converter.pyc decompilado), PIL puro. Cada archivo del lote
        adapta el mismo preset a su propio tamaño nativo -- no es una posición/
        tamaño fijo, se recalcula aquí por imagen. El Canvas editado a mano sobre el
        archivo actualmente abierto (clic izquierdo, en vivo) es un concepto
        separado -- ver la nota de Fase 3 en el plan, no pasa por aquí."""
        img_width, img_height = img.size
        if img.mode != "RGBA":
            img = img.convert("RGBA")

        canvas_option = options.get("canvas_option", "Sin ajuste")
        if canvas_option in ("Añadir Margen Externo", "Add External Margin", QCoreApplication.translate("ImageConverter", "Añadir Margen Externo")):
            margin = int(options.get("canvas_margin", 100))
            canvas_width, canvas_height = img_width + margin * 2, img_height + margin * 2
        elif canvas_option in ("Añadir Margen Interno", "Add Internal Margin", QCoreApplication.translate("ImageConverter", "Añadir Margen Interno")):
            margin = int(options.get("canvas_margin", 100))
            canvas_width, canvas_height = img_width, img_height
            new_width, new_height = max(1, img_width - margin * 2), max(1, img_height - margin * 2)
            if new_width < img_width or new_height < img_height:
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                img_width, img_height = new_width, new_height
        elif canvas_option in CANVAS_PRESET_SIZES:
            canvas_width, canvas_height = CANVAS_PRESET_SIZES[canvas_option]
        elif canvas_option in ("Personalizado...", "Custom..."):
            canvas_width = int(options.get("canvas_width", img_width))
            canvas_height = int(options.get("canvas_height", img_height))
        else:
            return img

        if canvas_option not in (
            "Añadir Margen Externo", "Add External Margin", QCoreApplication.translate("ImageConverter", "Añadir Margen Externo"),
            "Añadir Margen Interno", "Add Internal Margin", QCoreApplication.translate("ImageConverter", "Añadir Margen Interno"),
        ):
            if img_width > canvas_width or img_height > canvas_height:
                overflow_mode = options.get("canvas_overflow_mode", "Centrar (puede recortar)")
                if overflow_mode in ("Advertir y no procesar", "Warn and do not process"):
                    raise Exception(
                        QCoreApplication.translate(
                            "image_converter",
                            "La imagen ({0}×{1}) excede el canvas ({2}×{3})."
                        ).format(img_width, img_height, canvas_width, canvas_height)
                    )
                elif overflow_mode in (
                    "Reducir hasta que quepa", "Scale to fit", "Reduce until it fits",
                    QCoreApplication.translate("ImageConverter", "Reducir hasta que quepa")
                ):
                    scale = min(canvas_width / img_width, canvas_height / img_height)
                    img = img.resize((int(img_width * scale), int(img_height * scale)), Image.Resampling.LANCZOS)
                    img_width, img_height = img.size
                elif overflow_mode in (
                    "Recortar al canvas", "Crop to canvas",
                    "Centrar (puede recortar)", "Center (may crop)",
                    QCoreApplication.translate("ImageConverter", "Recortar al canvas")
                ):
                    left = max(0, (img_width - canvas_width) // 2)
                    top = max(0, (img_height - canvas_height) // 2)
                    img = img.crop((left, top, left + canvas_width, top + canvas_height))
                    img_width, img_height = img.size

        canvas = Image.new("RGBA", (canvas_width, canvas_height), (0, 0, 0, 0))
        position = options.get("canvas_position", "Centro")
        x, y = self._calculate_canvas_position(canvas_width, canvas_height, img_width, img_height, position)
        canvas.paste(img, (x, y), img)
        return canvas

    def _calculate_canvas_position(self, canvas_w, canvas_h, img_w, img_h, position: str):
        """Misma fórmula que canvas_popover.py::calc_position (duplicada a
        propósito -- ese vive en gui/, core/ no depende de gui/)."""
        position_map = {
            "Centro": ("center", "center"), "Arriba Izquierda": ("left", "top"),
            "Arriba Centro": ("center", "top"), "Arriba Derecha": ("right", "top"),
            "Centro Izquierda": ("left", "center"), "Centro Derecha": ("right", "center"),
            "Abajo Izquierda": ("left", "bottom"), "Abajo Centro": ("center", "bottom"),
            "Abajo Derecha": ("right", "bottom"),
            "Center": ("center", "center"), "Top Left": ("left", "top"),
            "Top Center": ("center", "top"), "Top Right": ("right", "top"),
            "Center Left": ("left", "center"), "Center Right": ("right", "center"),
            "Bottom Left": ("left", "bottom"), "Bottom Center": ("center", "bottom"),
            "Bottom Right": ("right", "bottom"),
        }
        h_align, v_align = position_map.get(position, ("center", "center"))
        x = 0 if h_align == "left" else (canvas_w - img_w) // 2 if h_align == "center" else canvas_w - img_w
        y = 0 if v_align == "top" else (canvas_h - img_h) // 2 if v_align == "center" else canvas_h - img_h
        return int(x), int(y)

    # ------------------------------------------------------------------
    # Guardado -- todo Pillow/img2pdf, sin binarios externos.
    # ------------------------------------------------------------------
    def _save_passthrough(self, img, input_ext, output_path, options):
        """"No Convertir": mantiene el formato original si es un raster con escritor
        propio (solo aplica resize); si el origen era vectorial/RAW/algo sin
        escritor, cae a PNG -- mismo comportamiento que DowP1."""
        fmt = _EXT_TO_PASSTHROUGH_FORMAT.get(input_ext, "PNG")
        self._save_as(img, fmt, output_path, options)

    def _save_as(self, img, output_format, output_path, options):
        writers = {
            "PNG": self._save_as_png, "JPG": self._save_as_jpg, "JPEG": self._save_as_jpg,
            "WEBP": self._save_as_webp, "AVIF": self._save_as_avif, "PDF": self._save_as_pdf,
            "SVG": self._save_as_svg,
            "TIFF": self._save_as_tiff, "ICO": self._save_as_ico, "ICNS": self._save_as_icns,
            "BMP": self._save_as_bmp,
        }
        writer = writers.get(output_format)
        if not writer:
            raise Exception(QCoreApplication.translate("image_converter", "Formato de salida no soportado: {0}").format(output_format))
        # Solo PNG y TIFF guardan gris de 16 bits; el resto recibe la versión de
        # 8 bits bien escalada (ver _downconvert_16bit).
        if output_format not in ("PNG", "TIFF"):
            img = self._downconvert_16bit(img)
        writer(img, output_path, options)

    def _flatten_to_rgb_white(self, img):
        """Aplana a RGB componiendo sobre fondo blanco -- usado cuando el usuario
        desmarca "mantener transparencia". `img.convert("RGB")` directo NO sirve
        para esto: descarta el canal alfa sin componer nada, y en un RGBA típico
        el RGB de los píxeles transparentes suele ser (0,0,0) -- el resultado
        salía negro en vez de con fondo blanco (bug real, reportado por el
        usuario). Mismo criterio que ya usaba _save_as_jpg, ahora compartido."""
        img = self._downconvert_16bit(img)
        if img.mode in ("RGBA", "LA", "PA"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[-1])
            return background
        return img.convert("RGB")

    def _save_as_png(self, img, output_path, options):
        if img.mode.startswith("I;16") or img.mode == "L":
            # Escala de grises (el Mapa de Profundidad, en 8 o 16 bits): se guarda
            # tal cual. _flatten_to_rgb_white la pasaría a RGB -- tres canales
            # idénticos, el triple de peso, y los de 16 bits bajados a 8.
            img.save(output_path, "PNG", compress_level=options.get("png_compression", 6))
            return
        if options.get("png_transparency", True) and img.mode in ("RGBA", "LA", "PA"):
            save_img = img
        else:
            save_img = self._flatten_to_rgb_white(img)
        save_img.save(output_path, "PNG", compress_level=options.get("png_compression", 6), optimize=True)

    def _save_as_jpg(self, img, output_path, options):
        save_img = self._flatten_to_rgb_white(img)
        subsampling_map = {"4:2:0 (Estándar)": "4:2:0", "4:2:2 (Alta)": "4:2:2", "4:4:4 (Máxima)": "4:4:4"}
        subsampling = subsampling_map.get(options.get("jpg_subsampling", "4:2:0 (Estándar)"), "4:2:0")
        save_img.save(
            output_path, "JPEG",
            quality=options.get("jpg_quality", 90),
            subsampling=subsampling,
            progressive=options.get("jpg_progressive", False),
            optimize=True,
        )

    def _save_as_webp(self, img, output_path, options):
        if options.get("webp_transparency", True) and img.mode in ("RGBA", "LA", "PA"):
            save_img = img
        else:
            save_img = self._flatten_to_rgb_white(img)
        kwargs = {"format": "WEBP", "lossless": options.get("webp_lossless", False)}
        if not kwargs["lossless"]:
            kwargs["quality"] = options.get("webp_quality", 90)
        if options.get("webp_metadata", False) and "exif" in img.info:
            kwargs["exif"] = img.info["exif"]
        save_img.save(output_path, **kwargs)

    def _save_as_avif(self, img, output_path, options):
        if not CAN_AVIF:
            raise Exception(QCoreApplication.translate("ImageConverter", "No se puede guardar como AVIF -- falta instalar 'pillow-avif-plugin'."))
        save_img = img if img.mode in ("RGBA", "RGB") else img.convert("RGBA" if "A" in img.mode else "RGB")
        save_img.save(output_path, "AVIF", quality=options.get("avif_quality", 80))

    def _save_as_pdf(self, img, output_path, options):
        import img2pdf
        keep_transparency = options.get("pdf_transparency", False) and "A" in img.getbands()
        if keep_transparency:
            save_img = img if img.mode == "RGBA" else img.convert("RGBA")
        else:
            save_img = img if img.mode in ("RGB", "L") else self._flatten_to_rgb_white(img)
        temp_png = output_path + ".tmp.png"
        try:
            save_img.save(temp_png, "PNG")
            with open(output_path, "wb") as f:
                f.write(img2pdf.convert(temp_png))
        finally:
            if os.path.exists(temp_png):
                os.remove(temp_png)

    def _save_as_svg(self, img, output_path, options):
        """Vectoriza con vtracer (dependencia opcional -- ver
        core/setup/vtracer_setup.py). Mismo patrón que _load_eps_ps con
        Ghostscript: si falta el binario, se corta acá con un mensaje de ayuda --
        la UI ya debería haber ofrecido descargarlo antes de llegar a este punto
        (ver image_tools_view.py::_confirm_vtracer_if_needed), esto es la red de
        seguridad por si igual faltara (ej. se desinstaló a mano entre medio)."""
        from core.setup.vtracer_setup import check_vtracer, get_vtracer_path

        if not check_vtracer():
            raise UnsupportedFormatError(
                QCoreApplication.translate(
                    "ImageConverter",
                    "SVG necesita vtracer -- instálalo desde Ajustes > Dependencias, "
                    "o acepta la descarga que te ofrece Convertir."
                )
            )

        import subprocess
        import tempfile

        # vtracer traza por color RGB, pero NO trata el alfa como "esto es
        # fondo, ignorar" -- si se le pasa el RGBA crudo, un logo con fondo
        # transparente (donde el canal RGB del fondo suele ser negro, (0,0,0),
        # igual que muchos logos oscuros) sale como un cuadro negro sólido: para
        # vtracer el fondo transparente y el logo opaco son el mismo color.
        # Mismo bug que ya arreglamos en PNG/WEBP/TIFF/PDF/BMP (_flatten_to_rgb_
        # white) -- acá componemos sobre blanco ANTES de vectorizar, no hay
        # (todavía) una opción de "mantener transparencia" para SVG en la UI.
        save_img = self._flatten_to_rgb_white(img).convert("RGBA")

        with tempfile.TemporaryDirectory(prefix="dowp_vtracer_") as tmp_dir:
            temp_png = os.path.join(tmp_dir, "in.png")
            save_img.save(temp_png, "PNG")

            # vtracer escribe el SVG directo en output_path -- no hace falta un
            # paso intermedio de copiar/mover.
            cmd = [get_vtracer_path(), "-i", temp_png, "-o", output_path, "--optimize", "2"]

            if options.get("svg_mode", "quick") == "quick":
                cmd += ["--preset", options.get("svg_preset", "photo")]
            else:
                clustering = options.get("svg_clustering", "color-cluster")
                cmd += [
                    "--mode", options.get("svg_curve_mode", "spline"),
                    "--clustering", clustering,
                    "--color-precision", str(options.get("svg_color_precision", 6)),
                    "--filter-speckle", str(options.get("svg_filter_speckle", 4)),
                ]
                simplify = options.get("svg_simplify", 0.0)
                if simplify:
                    cmd += ["--simplify", str(simplify)]
                if clustering == "bw":
                    if options.get("svg_adaptive", False):
                        cmd += ["--adaptive"]
                    else:
                        cmd += ["--threshold", str(options.get("svg_threshold", 128))]

            logger.info(f"Convertir SVG: {' '.join(cmd)}")
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if result.returncode != 0 or not os.path.exists(output_path):
                raise Exception(
                    QCoreApplication.translate(
                        "ImageConverter", "vtracer no pudo vectorizar: {0}"
                    ).format(result.stderr[:300])
                )
            if result.stdout.strip():
                logger.info(f"Convertir SVG: vtracer -> {result.stdout.strip()}")

    def _save_as_tiff(self, img, output_path, options):
        if img.mode.startswith("I;16") or img.mode == "L":
            save_img = img  # Escala de grises, ver _save_as_png.
        elif options.get("tiff_transparency", True) and img.mode in ("RGBA", "LA", "PA"):
            save_img = img
        else:
            save_img = self._flatten_to_rgb_white(img)
        compression_map = {
            "Ninguna": None, "LZW (Recomendada)": "tiff_lzw",
            "Deflate (ZIP)": "tiff_deflate", "PackBits": "packbits",
        }
        compression = compression_map.get(options.get("tiff_compression", "LZW (Recomendada)"))
        kwargs = {"format": "TIFF"}
        if compression:
            kwargs["compression"] = compression
        save_img.save(output_path, **kwargs)

    def _save_as_ico(self, img, output_path, options):
        save_img = img if img.mode == "RGBA" else img.convert("RGBA")
        sizes_dict = options.get("ico_sizes", {})
        selected = [size for size, on in sizes_dict.items() if on] or [32, 256]
        save_img.save(output_path, "ICO", sizes=[(s, s) for s in selected])

    def _save_as_icns(self, img, output_path, options):
        save_img = img if img.mode == "RGBA" else img.convert("RGBA")
        # ICNS requiere imágenes cuadradas. Si no lo es, rellenamos con transparente.
        w, h = save_img.size
        if w != h:
            side = max(w, h)
            square_img = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            square_img.paste(save_img, ((side - w) // 2, (side - h) // 2))
            save_img = square_img
            
        sizes_dict = options.get("icns_sizes", {})
        # Pillow genera las variaciones internamente para ICNS si provees la original.
        # Aquí proveemos la imagen base al mayor tamaño seleccionado y Pillow se encarga,
        # o podemos generar la lista de imágenes explícitamente para asegurar compatibilidad.
        selected = sorted([size for size, on in sizes_dict.items() if on], reverse=True)
        if not selected:
            selected = [1024, 512, 128, 32]
            
        # Generar las distintas resoluciones
        images = []
        for s in selected:
            if s == save_img.size[0]:
                images.append(save_img)
            else:
                images.append(save_img.resize((s, s), Image.Resampling.LANCZOS))
                
        # Guardar (la primera es la principal, append_images provee las resoluciones extra)
        if images:
            images[0].save(output_path, "ICNS", append_images=images[1:])

    def _save_as_bmp(self, img, output_path, options):
        self._flatten_to_rgb_white(img).save(output_path, "BMP")
