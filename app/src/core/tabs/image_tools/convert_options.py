# src/core/tabs/image_tools/convert_options.py
from PySide6.QtCore import QCoreApplication
"""Constantes y valores por defecto para "Convertir" (Editor de Imagen) -- sin Qt,
mismo rol que core/tabs/video_tools/convert_advisor.py para su propio Convertir,
pero sin lógica de "plan" (aquí no hay copy-vs-recode: cada archivo simplemente se
re-codifica al formato elegido, ver core/tabs/image_tools/image_converter.py).
Valores por defecto tomados 1:1 de los que usaba DowP1 (image_converter.pyc
decompilado) -- único agregado: avif_quality, que DowP1 no exponía en su UI pese a
que el motor ya lo soportaba."""

OUTPUT_FORMATS = [QCoreApplication.translate("convert_options", "No Convertir"), "PNG", "JPG", "WEBP", "AVIF", "PDF", "TIFF", "ICO", "ICNS", "BMP"]

JPG_SUBSAMPLING_OPTIONS = ["4:2:0 (Estándar)", "4:2:2 (Alta)", "4:4:4 (Máxima)"]
TIFF_COMPRESSION_OPTIONS = ["Ninguna", "LZW (Recomendada)", "Deflate (ZIP)", "PackBits"]

ICO_SIZES = (16, 32, 48, 64, 128, 256)
ICO_DEFAULT_SIZES = (32, 256)

ICNS_SIZES = (16, 32, 64, 128, 256, 512, 1024)
ICNS_DEFAULT_SIZES = (32, 128, 512, 1024)


def default_options_for_format(fmt: str) -> dict:
    """Valores por defecto para el formato de salida elegido -- se combinan con los
    valores que sí edita el usuario en ConvertPanel (ver get_settings())."""
    if fmt == "PNG":
        return {"png_transparency": True, "png_compression": 6}
    if fmt == "JPG":
        return {"jpg_quality": 90, "jpg_subsampling": JPG_SUBSAMPLING_OPTIONS[0], "jpg_progressive": False}
    if fmt == "WEBP":
        return {"webp_lossless": False, "webp_quality": 90, "webp_transparency": True, "webp_metadata": False}
    if fmt == "AVIF":
        return {"avif_quality": 80}
    if fmt == "TIFF":
        return {"tiff_compression": TIFF_COMPRESSION_OPTIONS[1], "tiff_transparency": True}
    if fmt == "ICO":
        return {"ico_sizes": {size: (size in ICO_DEFAULT_SIZES) for size in ICO_SIZES}}
    if fmt == "ICNS":
        return {"icns_sizes": {size: (size in ICNS_DEFAULT_SIZES) for size in ICNS_SIZES}}
    if fmt == "BMP":
        return {"bmp_rle": False}
    return {}
