# src/core/tabs/video_tools/ia_video_common.py
"""Piezas comunes de las Herramientas IA de video (Reescalado IA y Mapa de Profundidad):
sondeo de la fuente, recorte y elección del códec de salida.

Vive aparte porque las dos funciones tienen que resolver EXACTAMENTE igual estas tres
cosas -- si cada una las decidiera por su cuenta, el recorte o la transparencia se
comportarían distinto según la función elegida.

Formatos de salida (ver build_video_encode_args):
  - Por defecto: H.264 con -pix_fmt yuv420p. Sin forzarlo, ffmpeg elige yuv444p al
    recibir fotogramas RGB (PNG/JPG), y un H.264 4:4:4 no se reproduce en muchos
    reproductores, navegadores ni móviles.
  - "Conservar transparencia" + MOV + fuente con alfa: ProRes 4444 con alfa, el formato
    estándar de video con transparencia de Premiere/After Effects/DaVinci/Final Cut.
  - 16 bits (solo Mapa de Profundidad): FFV1 en MKV o PNG dentro de MOV, sin pérdida.
"""
import json
import os
import subprocess

from core.logger.logger_manager import logger
from core.setup.ffmpeg_setup import get_ffprobe_path

# Formatos de píxel con canal alfa que puede entregar un decodificador de ffmpeg.
_ALPHA_PIX_FMTS = {
    "rgba", "bgra", "argb", "abgr", "ya8", "ya16le", "ya16be", "rgba64le", "rgba64be",
    "bgra64le", "bgra64be", "pal8",
}

# Contenedores que admiten 16 bits sin pérdida (Mapa de Profundidad), en orden de
# preferencia cuando el elegido no sirve.
CONTAINERS_16BIT = ("mkv", "mov")


def _startupinfo():
    if os.name != "nt":
        return None
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return info


def _parse_rate(value) -> float:
    try:
        if isinstance(value, str) and "/" in value:
            num, den = value.split("/", 1)
            return float(num) / float(den) if float(den) else 0.0
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def probe_video_source(path: str) -> dict:
    """Datos del primer stream de video: ancho, alto, fps, formato de píxel, si trae
    transparencia y, si hace falta, qué decodificador usar para no perderla.

    WebM VP8/VP9 guarda el alfa aparte (etiqueta alpha_mode=1) y el formato de píxel
    que informa es "yuv420p": el decodificador nativo de ffmpeg lo descarta en
    silencio, solo libvpx lo entrega. Por eso `decoder_args` trae "-c:v libvpx..." en
    ese caso, para ponerlo ANTES del -i de la fuente."""
    info = {"width": 0, "height": 0, "fps": 0.0, "pix_fmt": "", "has_alpha": False,
            "decoder_args": [], "has_audio": False}
    ffprobe = get_ffprobe_path()
    if not ffprobe or not os.path.exists(ffprobe):
        return info
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_streams", "-of", "json", path],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
            startupinfo=_startupinfo(),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        ).stdout
        streams = json.loads(out or "{}").get("streams", [])
    except Exception as e:
        logger.warning(f"IA video: no se pudo sondear {path}: {e}")
        return info

    info["has_audio"] = any(s.get("codec_type") == "audio" for s in streams)
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not (s.get("disposition") or {}).get("attached_pic")), None)
    if not video:
        return info
    pix_fmt = video.get("pix_fmt") or ""
    info.update(
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        fps=_parse_rate(video.get("avg_frame_rate")) or _parse_rate(video.get("r_frame_rate")),
        pix_fmt=pix_fmt,
    )
    codec = (video.get("codec_name") or "").lower()
    tags = {str(k).lower(): str(v) for k, v in (video.get("tags") or {}).items()}
    if codec in ("vp8", "vp9") and tags.get("alpha_mode") == "1":
        info["has_alpha"] = True
        info["decoder_args"] = ["-c:v", "libvpx-vp9" if codec == "vp9" else "libvpx"]
    else:
        info["has_alpha"] = (pix_fmt in _ALPHA_PIX_FMTS or pix_fmt.startswith(("yuva", "gbrap")))
    return info


def trim_input_args(trim_in, trim_out) -> list:
    """-ss/-to como opciones de ENTRADA (antes del -i), igual que la Recodificación
    normal (ver QueueWorker._execute_recode): el recorte de Herramientas Multimedia es
    un solo tramo [inicio, fin] en segundos del archivo original."""
    args = []
    if trim_in is not None and trim_in > 0:
        args += ["-ss", f"{trim_in:.3f}"]
    if trim_out is not None and trim_out > 0:
        args += ["-to", f"{trim_out:.3f}"]
    return args


def trimmed_duration(duration_sec: float, trim_in, trim_out) -> float:
    """Duración real de lo que se va a procesar (para progreso y estimaciones)."""
    start = trim_in if trim_in and trim_in > 0 else 0.0
    end = trim_out if trim_out and trim_out > 0 else duration_sec
    return max(0.0, (end or 0.0) - start)


def container_of(path: str) -> str:
    return os.path.splitext(path)[1].lower().lstrip(".")


def build_video_encode_args(container: str, alpha: bool = False, depth16: bool = False,
                            with_filter: bool = True) -> list:
    """Argumentos del códec de video de salida según contenedor, transparencia y 16 bits.

    - depth16 (Mapa de Profundidad): MKV -> FFV1 gris de 16 bits (o YUVA 16 bits con
      alfa); MOV -> PNG gris de 16 bits (o gris+alfa). Sin pérdida.
    - alpha en MOV: ProRes 4444 con alfa (10 bits).
    - resto: H.264 yuv420p. yuv420p exige ancho y alto pares: el filtro de escala los
      redondea hacia abajo (a lo sumo se pierde una fila/columna) en vez de fallar.
      with_filter=False lo omite, para quien arma su propio -filter_complex (no se
      pueden combinar con -vf) y ya entrega los lados pares -- ver video_depth_engine.
    """
    container = (container or "mp4").lower()
    if depth16:
        if container == "mov":
            return ["-c:v", "png", "-pix_fmt", "ya16be" if alpha else "gray16be"]
        return ["-c:v", "ffv1", "-level", "3", "-pix_fmt", "yuva444p16le" if alpha else "gray16le"]
    if alpha and container == "mov":
        return ["-c:v", "prores_ks", "-profile:v", "4", "-pix_fmt", "yuva444p10le",
                "-vendor", "apl0"]
    even = ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2"] if with_filter else []
    return [*even, "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p"]
