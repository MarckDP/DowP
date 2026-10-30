# src/core/tabs/image_tools/pdf_tools.py
"""Tamaño de página y compresión de los PDF que arma "Convertir" -- todo con lo que ya
trae DowP (img2pdf + pikepdf + Pillow), sin Ghostscript.

Compresión: se arma el PDF como siempre (sin pérdida) y después compress_pdf()
recomprime sus imágenes a JPEG, reduciéndolas a un lado máximo en píxeles. Mismo
camino para imágenes -> PDF, para Fusionar y para un PDF que ya existe. Medido con
documentos reales (escaneos, títulos, fichas): Recomendada deja ~-90 % y el texto
y los vectores no se tocan. Ghostscript ganaba solo en PDF de texto chicos (KB).

Se limita por PÍXELES y no por ppp a propósito: el tamaño físico de la página queda
igual, solo baja la resolución de la imagen que va adentro."""
import io
import os
import zlib

from core.logger.logger_manager import logger

# ── Compresión ─────────────────────────────────────────────────────────────────
# Claves internas (el combo de la UI guarda estas en currentData, nunca el texto
# traducido -- ver memoria i18n, trampa #7).
COMPRESS_NONE = "none"
COMPRESS_LOW = "low"
COMPRESS_RECOMMENDED = "recommended"
COMPRESS_EXTREME = "extreme"
COMPRESS_CUSTOM = "custom"

# nivel -> (calidad JPEG, lado máximo en px)
COMPRESS_PRESETS = {
    COMPRESS_LOW: (85, 3000),
    COMPRESS_RECOMMENDED: (75, 2000),
    COMPRESS_EXTREME: (55, 1400),
}
# 0 = sin reducir
MAX_SIDE_OPTIONS = (0, 3000, 2000, 1600, 1200)
CUSTOM_DEFAULT_QUALITY = 75
CUSTOM_DEFAULT_MAX_SIDE = 2000

# Imágenes que no se tocan: codecs especiales (texto bitonal JBIG2/CCITT, JPEG 2000)
# y espacios de color que Pillow no pasa bien a RGB.
_SKIP_FILTERS = {"/JBIG2Decode", "/CCITTFaxDecode", "/JPXDecode"}
_OK_COLORSPACES = {"/DeviceRGB", "/DeviceGray", "/CalRGB", "/CalGray", "/ICCBased", "/Indexed"}


def compression_settings(options: dict) -> dict | None:
    """Ajustes de compresión de las opciones de Convertir, o None si no se comprime."""
    level = options.get("pdf_compression", COMPRESS_NONE)
    if level in COMPRESS_PRESETS:
        quality, max_side = COMPRESS_PRESETS[level]
        return {"quality": quality, "max_side": max_side, "grayscale": False,
                "keep_if_larger": True, "strip_metadata": False}
    if level == COMPRESS_CUSTOM:
        return {
            "quality": max(10, min(100, int(options.get("pdf_quality", CUSTOM_DEFAULT_QUALITY)))),
            "max_side": max(0, int(options.get("pdf_max_side", CUSTOM_DEFAULT_MAX_SIDE))),
            "grayscale": bool(options.get("pdf_grayscale", False)),
            "keep_if_larger": bool(options.get("pdf_keep_if_larger", True)),
            "strip_metadata": bool(options.get("pdf_strip_metadata", False)),
        }
    return None


def _name(obj) -> str:
    return str(obj) if obj is not None else ""


def _colorspace_ok(cs) -> tuple[bool, int]:
    """(se puede recomprimir, componentes del ICC o 0). CMYK, Lab, Separation y
    DeviceN quedan fuera: pasarlos a RGB cambia los colores."""
    import pikepdf
    if cs is None:
        return False, 0
    if isinstance(cs, pikepdf.Array):
        family = _name(cs[0])
        if family == "/ICCBased":
            n = int(cs[1].get("/N", 0))
            return n in (1, 3), n
        if family == "/Indexed":
            ok, _ = _colorspace_ok(cs[1])
            return ok, 0
        return family in _OK_COLORSPACES, 0
    return _name(cs) in _OK_COLORSPACES, 0


def _decode_mask(smask):
    """SMask -> imagen L de Pillow, o None si no se puede (o no conviene) tocar."""
    import pikepdf
    if "/Matte" in smask or _name(smask.get("/Filter")) in _SKIP_FILTERS:
        return None
    try:
        im = pikepdf.PdfImage(smask).as_pil_image()
    except Exception:
        return None
    return im.convert("L") if im.mode != "L" else im


def _recompress_image(raw, smask_ids: set, settings: dict) -> bool:
    """Recomprime una imagen del PDF en el lugar. True si la cambió."""
    import pikepdf
    from PIL import Image

    if raw.objgen in smask_ids:
        return False  # es la transparencia de otra imagen: va con ella
    filt = raw.get("/Filter")
    filters = {_name(f) for f in filt} if isinstance(filt, pikepdf.Array) else {_name(filt)}
    if (raw.get("/ImageMask") or int(raw.get("/BitsPerComponent", 8)) != 8
            or filters & _SKIP_FILTERS or "/Decode" in raw):
        return False
    # Transparencia por color clave (/Mask [rangos]): el JPEG corre los colores y el
    # fondo que tenía que ser transparente aparece (medido: 50 % -> 0,5 %).
    if isinstance(raw.get("/Mask"), pikepdf.Array):
        return False
    cs = raw.get("/ColorSpace")
    cs_ok, icc_n = _colorspace_ok(cs)
    if not cs_ok:
        return False

    try:
        im = pikepdf.PdfImage(raw).as_pil_image()
    except Exception:
        return False
    # Con /SMask, pikepdf ya devuelve la imagen combinada con su transparencia
    # (RGBA/LA). Acá solo interesan los colores: la máscara sigue siendo un objeto
    # aparte y se trata más abajo.
    if im.mode in ("RGBA", "LA"):
        im = im.convert(im.mode[:-1])
    if im.mode not in ("L", "RGB", "P"):
        return False

    gray = settings["grayscale"] or im.mode == "L"
    im = im.convert("L" if gray else "RGB")
    w, h = im.size
    max_side = settings["max_side"]
    resized = bool(max_side) and max(w, h) > max_side
    if resized:
        f = max_side / max(w, h)
        im = im.resize((max(1, round(w * f)), max(1, round(h * f))), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=settings["quality"], optimize=True)
    data = buf.getvalue()
    if settings["keep_if_larger"] and len(data) >= len(raw.read_raw_bytes()):
        return False

    smask = raw.get("/SMask")
    mask_img = None
    if resized and isinstance(smask, pikepdf.Stream):
        mask_img = _decode_mask(smask)

    raw.write(data, filter=pikepdf.Name.DCTDecode)
    raw.Width, raw.Height = im.size
    raw.BitsPerComponent = 8
    # El perfil ICC se conserva si sigue valiendo (mismos componentes): así los
    # colores no se corren. Si no, el equivalente Device.
    wanted_n = 1 if gray else 3
    if icc_n != wanted_n:
        raw.ColorSpace = pikepdf.Name.DeviceGray if gray else pikepdf.Name.DeviceRGB
    if "/DecodeParms" in raw:
        del raw["/DecodeParms"]

    # La transparencia se reduce junto con la imagen. Una SMask de otro tamaño es
    # válida, así que si reducida no pesa menos (img2pdf la guarda con predictor
    # PNG, que en máscaras suaves comprime mejor), queda la original.
    if mask_img is not None:
        mask_img = mask_img.resize(im.size, Image.Resampling.LANCZOS)
        mask_data = zlib.compress(mask_img.tobytes(), 9)
        if len(mask_data) >= len(smask.read_raw_bytes()):
            return True
        smask.write(mask_data, filter=pikepdf.Name.FlateDecode)
        smask.Width, smask.Height = mask_img.size
        smask.ColorSpace = pikepdf.Name.DeviceGray
        smask.BitsPerComponent = 8
        if "/DecodeParms" in smask:
            del smask["/DecodeParms"]
    return True


def compress_pdf(src: str, dst: str, settings: dict, cancellation_event=None) -> tuple[int, int] | None:
    """Recomprime las imágenes de `src` y guarda en `dst` (puede ser el mismo
    archivo). Devuelve (bytes antes, bytes después), o None si se canceló. Si el
    resultado no es más chico, `dst` queda con el contenido original.

    Recorre TODOS los objetos imagen del documento, no solo los de cada página: así
    también entran las que van anidadas en Form XObjects (sellos, firmas, páginas
    importadas), que page.images no veía."""
    import pikepdf

    before = os.path.getsize(src)
    tmp = dst + ".dowp_tmp.pdf"
    changed = skipped = 0
    try:
        with pikepdf.open(src) as pdf:
            images = [o for o in pdf.objects
                      if isinstance(o, pikepdf.Stream) and o.get("/Subtype") == "/Image"]
            smask_ids = {o.SMask.objgen for o in images if isinstance(o.get("/SMask"), pikepdf.Stream)}
            for raw in images:
                if cancellation_event and cancellation_event.is_set():
                    return None
                try:
                    if _recompress_image(raw, smask_ids, settings):
                        changed += 1
                    elif raw.objgen not in smask_ids:
                        skipped += 1
                except Exception as e:
                    skipped += 1
                    logger.warning(f"PDF: imagen {raw.objgen} sin recomprimir ({e})")

            # Datos privados de Illustrator: pesan mucho y no se ven.
            for page in pdf.pages:
                if "/PieceInfo" in page.obj:
                    del page.obj["/PieceInfo"]
            if settings.get("strip_metadata"):
                if "/Metadata" in pdf.Root:
                    del pdf.Root["/Metadata"]
                if "/Info" in pdf.trailer:
                    del pdf.trailer["/Info"]

            pdf.save(tmp, compress_streams=True, recompress_flate=True,
                     object_stream_mode=pikepdf.ObjectStreamMode.generate)

        after = os.path.getsize(tmp)
        if after < before:
            os.replace(tmp, dst)
        else:
            os.remove(tmp)
            if os.path.normpath(src) != os.path.normpath(dst):
                import shutil
                shutil.copyfile(src, dst)
            after = before
        logger.info(f"PDF: compresión q{settings['quality']}/{settings['max_side'] or 'original'}px: "
                    f"{before} -> {after} bytes ({changed} imágenes recomprimidas, {skipped} sin tocar)")
        return before, after
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def copy_document(src: str, dst: str):
    """PDF/AI -> PDF sin comprimir: el documento entero tal cual (todas las páginas,
    texto seleccionable, vectores nítidos). Solo se quitan los datos privados de
    Illustrator, que pesan mucho y no se ven."""
    import pikepdf
    with pikepdf.open(src) as pdf:
        for page in pdf.pages:
            if "/PieceInfo" in page.obj:
                del page.obj["/PieceInfo"]
        pdf.save(dst)


def savings_text(before: int, after: int) -> str:
    """'27.3 MB → 2.1 MB (−92 %)' para el estado de la cola."""
    from core.tabs.editing_media.editing_media_logic import format_size
    pct = round(100 * (1 - after / before)) if before else 0
    return f"{format_size(before)} → {format_size(after)} (−{pct} %)"


# ── Tamaño de página ───────────────────────────────────────────────────────────
PAGE_SIZE_IMAGE = "image"
PAGE_SIZE_A4 = "A4"
PAGE_SIZE_LETTER = "Letter"
PAGE_SIZE_LEGAL = "Legal"

# Ppp que se respetan tal como vienen en la imagen. Los escáneres guardan 150-600 y
# así la página sale de su tamaño real (un A4 a 300 ppp mide 21 x 29,7 cm). Las
# fotos de celular suelen decir 72 (una de 4032 px saldría de 142 cm) y muchas
# imágenes no dicen nada: esas siguen a 96, como siempre.
_DPI_RANGE = (150, 1200)
_FALLBACK_DPI = 96


def _layout_by_image_dpi(imgwidthpx, imgheightpx, ndpi):
    dpi_x, dpi_y = ndpi
    lo, hi = _DPI_RANGE
    if not (lo <= dpi_x <= hi and lo <= dpi_y <= hi):
        dpi_x = dpi_y = _FALLBACK_DPI
    w = imgwidthpx * 72.0 / dpi_x
    h = imgheightpx * 72.0 / dpi_y
    return w, h, w, h


def page_layout(options: dict):
    """layout_fun de img2pdf según "Tamaño de página". Con una hoja fija, la imagen
    se ajusta adentro sin deformarse y la hoja gira sola si la imagen es apaisada."""
    import img2pdf
    key = options.get("pdf_page_size", PAGE_SIZE_IMAGE)
    sizes = {
        PAGE_SIZE_A4: (img2pdf.mm_to_pt(210), img2pdf.mm_to_pt(297)),
        PAGE_SIZE_LETTER: (img2pdf.in_to_pt(8.5), img2pdf.in_to_pt(11)),
        PAGE_SIZE_LEGAL: (img2pdf.in_to_pt(8.5), img2pdf.in_to_pt(14)),
    }
    if key in sizes:
        return img2pdf.get_layout_fun(pagesize=sizes[key], fit=img2pdf.FitMode.into, auto_orient=True)
    return _layout_by_image_dpi
