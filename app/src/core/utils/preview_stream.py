# src/core/utils/preview_stream.py
"""Elige, entre los formatos que devuelve yt-dlp, uno que sirva para VISTA PREVIA (no
para descargar): con audio y video juntos (QMediaPlayer no combina pistas separadas
sobre la marcha), sin RTMP (no lo soporta) y en una resolución intermedia para que la
vista previa no tarde en cargar. Mismo criterio para el corte de fragmentos
(download_controller.py) y para la vista previa de la ventana de búsqueda
(media_search_dialog.py) -- antes vivía duplicado solo en el primero."""


def pick_preview_stream_url(formats):
    formats = formats or []
    preview_format = None
    for f in formats:
        if f.get("url") and not f.get("url", "").startswith("rtmp") and f.get("acodec") != "none" and f.get("vcodec") != "none":
            h = f.get("height") or 0
            if 360 <= h <= 720:
                preview_format = f
                break
    if not preview_format:
        for f in formats:
            if f.get("url") and f.get("vcodec") != "none":
                preview_format = f
                break
    return preview_format.get("url", "") if preview_format else ""
