# src/core/tabs/image_tools/pdf_pages.py
"""Rango de páginas al importar un PDF (Editor de Imagen) -- sin Qt, mismo
espíritu que DowP1: al arrastrar/agregar un PDF de varias páginas se pregunta
cuáles importar y se extrae cada una a su propio PDF de 1 página, que es lo que
en realidad entra a la cola (ver ImageQueueWidget._resolve_pdf_pages en
gui/tabs/image_tools/image_queue_widget.py). Así el resto del pipeline
(miniatura, vista previa, conversión) no necesita saber nada de páginas --
_load_pdf_like ya renderiza pdf[0], que en un PDF de 1 página ES la elegida."""
import os
import re

from PySide6.QtCore import QCoreApplication


def get_pdf_page_count(filepath: str) -> int:
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(filepath)
    try:
        return len(doc)
    finally:
        doc.close()


def parse_page_range(text: str, max_page: int) -> list[int]:
    """"1-5, 8, 10-12" o con ";" en vez de "," (no está claro cuál usaba DowP1,
    se aceptan los dos) -> lista de páginas 1-based, ordenada y sin repetidos.
    Levanta ValueError con un mensaje traducido listo para mostrar en el diálogo."""
    pages: set[int] = set()
    tokens = [t.strip() for t in re.split(r"[,;]", text) if t.strip()]
    if not tokens:
        raise ValueError(QCoreApplication.translate("pdf_pages", "Ingresa al menos una página."))

    for token in tokens:
        m = re.fullmatch(r"(\d+)-(\d+)", token)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            if lo > hi:
                lo, hi = hi, lo
        elif re.fullmatch(r"\d+", token):
            lo = hi = int(token)
        else:
            raise ValueError(
                QCoreApplication.translate("pdf_pages", "\"{0}\" no es una página ni un rango válido.").format(token)
            )
        if lo < 1 or hi > max_page:
            raise ValueError(
                QCoreApplication.translate(
                    "pdf_pages", "\"{0}\" está fuera de rango (el documento tiene {1} página(s))."
                ).format(token, max_page)
            )
        pages.update(range(lo, hi + 1))

    return sorted(pages)


def extract_pdf_pages(filepath: str, pages: list[int], out_dir: str) -> list[str]:
    """Extrae cada página (1-based) de `filepath` a su propio PDF de 1 página
    dentro de `out_dir`, nombrado "{nombre}_p{N}.pdf". Devuelve las rutas en el
    mismo orden que `pages`."""
    import pypdfium2 as pdfium

    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(filepath))[0]
    src = pdfium.PdfDocument(filepath)
    out_paths = []
    try:
        for page in pages:
            new_doc = pdfium.PdfDocument.new()
            try:
                new_doc.import_pages(src, pages=[page - 1])
                out_path = os.path.join(out_dir, f"{stem}_p{page}.pdf")
                new_doc.save(out_path)
                out_paths.append(out_path)
            finally:
                new_doc.close()
    finally:
        src.close()
    return out_paths
