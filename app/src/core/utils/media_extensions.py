# src/core/utils/media_extensions.py
"""Extensiones que acepta Herramientas Multimedia (cola de archivos, detección de solo
audio, Comprimir). Antes había tres copias de la lista de audio (media_queue_widget,
video_tools_view, compress_advisor) que se desincronizaban: un formato agregado en una
sola entraba a la cola pero se trataba como video, o al revés.

ffmpeg reconoce el formato por el contenido, no por la extensión: esta lista solo decide
qué se deja entrar y si se trata como audio o video."""
import os

VIDEO_EXTS = {
    ".mp4", ".m4v", ".mkv", ".mov", ".avi", ".webm", ".flv", ".f4v", ".wmv", ".asf",
    ".mpg", ".mpeg", ".m2v", ".vob", ".ts", ".mts", ".m2ts", ".mxf", ".dv",
    ".3gp", ".3g2", ".ogv", ".rm", ".rmvb", ".divx", ".nut", ".y4m",
    # Animaciones
    ".gif", ".apng",
    # ".webp" solo si es animado: ver is_accepted_media()
}

AUDIO_EXTS = {
    ".mp3", ".wav", ".aac", ".flac", ".ogg", ".oga", ".m4a", ".m4b", ".opus", ".wma",
    ".aiff", ".aif", ".aifc", ".caf", ".au", ".ac3", ".eac3", ".dts", ".thd", ".mlp",
    ".amr", ".3ga", ".ape", ".wv", ".tta", ".mka", ".weba", ".spx", ".mp2", ".mpa",
    ".ra", ".dsf", ".gsm", ".voc", ".adts", ".mpc", ".w64", ".shn",
    # MP3 de Jamendo: Openverse informa su formato como "mp32" (ver openverse_provider.py,
    # que ya los guarda como .mp3); se aceptan los que se hayan descargado antes.
    ".mp31", ".mp32",
}


def is_animated_webp(path: str) -> bool:
    """WebP animado: contenedor RIFF/WEBP con bloque VP8X y el bit de animación (0x02).
    Un WebP estático es una imagen: va a Herramientas de Imagen, no a esta cola."""
    try:
        with open(path, "rb") as f:
            head = f.read(21)
    except OSError:
        return False
    return (len(head) == 21 and head[:4] == b"RIFF" and head[8:12] == b"WEBP"
            and head[12:16] == b"VP8X" and bool(head[20] & 0x02))


def is_accepted_media(path: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".webp":
        return is_animated_webp(path)
    return ext in VIDEO_EXTS or ext in AUDIO_EXTS


def is_audio_only(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in AUDIO_EXTS


def file_dialog_patterns() -> str:
    """Patrones para el filtro de QFileDialog ("*.mp4 *.mkv ...")."""
    return " ".join(f"*{e}" for e in sorted(VIDEO_EXTS | {".webp"}) + sorted(AUDIO_EXTS))
