# src/core/tabs/video_tools/alpha_policy.py
"""
Política de transparencia (canal alfa) compartida por las pestañas de Herramientas
Multimedia (Comprimir, Convertir, Edición y Avanzado).

Qué códec conserva el alfa en qué contenedor NO se decide aquí: sale del eje "alpha" de
ffmpeg_codec_matrix.json (ver recode_guard.get_alpha_support, verificado empíricamente
contra el ffmpeg empaquetado). Este módulo solo agrega las decisiones de PRODUCTO:

- Qué códecs se ofrecen para conservar transparencia en los modos simples (Rápido /
  Convertir / Comprimir): solo los de uso común. FFV1, UT Video, HuffYUV o JPEG 2000
  también conservan alfa, pero son formatos de archivo/intermedios poco esperados como
  resultado de "convertir" -- quedan para Avanzado, donde se elige el códec a mano.
- Con qué argumentos se codifica cada uno para que el alfa efectivamente sobreviva.

La marca que viaja en los settings es "keep_alpha": True = conservar (el motor fuerza el
decodificador y el formato de píxel con alfa), False = descartarla a propósito, ausente
= comportamiento automático (conservar si el códec elegido puede). El motor la aplica en
queue_manager._run_ffmpeg_command, solo a los archivos que realmente traen alfa.
"""
from core.utils.recode_guard import get_alpha_support, normalize_container
from core.tabs.video_tools.codec_profiles import (
    VIDEO_ENCODER_PROFILES, build_custom_quality_args, preferred_encoder,
)

# Formatos de píxel con canal alfa (mismo criterio que ia_video_common._ALPHA_PIX_FMTS).
_ALPHA_PIX_FMTS = {
    "rgba", "bgra", "argb", "abgr", "ya8", "ya16le", "ya16be",
    "rgba64le", "rgba64be", "bgra64le", "bgra64be",
}

# Códecs "de uso común" para conservar transparencia en los modos simples, en orden de
# preferencia: VP9 (web, buena compresión), ProRes 4444 (edición), VP8, CineForm, y los
# de animación (GIF de 1 bit, WebP y APNG), cada uno solo en su propio contenedor.
QUICK_ALPHA_CODECS = ["vp9", "prores", "vp8", "cfhd", "gif", "webp", "apng"]

_LABELS = {
    "vp9": "VP9", "vp8": "VP8", "prores": "ProRes 4444", "cfhd": "CineForm",
    "gif": "GIF", "webp": "WebP", "apng": "APNG",
    "h264": "H.264", "hevc": "HEVC (H.265)", "av1": "AV1", "dnxhd": "DNxHR", "ffv1": "FFV1",
    "mpeg4": "MPEG-4", "theora": "Theora",
    "qtrle": "QuickTime Animation", "png": "PNG", "hap": "HAP",
}


def meta_has_alpha(meta: dict | None) -> bool:
    """True si los metadatos del archivo dicen que el video trae transparencia. Usa
    "has_alpha" (ffprobe_metadata_manager, incluye WebM con alpha_mode=1); si falta
    (metadatos básicos sin ffprobe todavía), cae al formato de píxel."""
    if not meta:
        return False
    if "has_alpha" in meta:
        return bool(meta["has_alpha"])
    pix_fmt = str(meta.get("color") or "").lower()
    return pix_fmt in _ALPHA_PIX_FMTS or pix_fmt.startswith(("yuva", "gbrap"))


def keeps_alpha(codec_id: str | None, container: str | None) -> bool:
    return get_alpha_support(codec_id, container)["keeps_alpha"]


def is_one_bit(codec_id: str | None, container: str | None) -> bool:
    return get_alpha_support(codec_id, container)["status"] == "1bit"


def quick_alpha_codec(container: str | None) -> str | None:
    """Códec de uso común que conserva transparencia en este contenedor, o None si el
    contenedor no guarda transparencia con ninguno (ej. MP4)."""
    if not container:
        return None
    for codec_id in QUICK_ALPHA_CODECS:
        if keeps_alpha(codec_id, container):
            return codec_id
    return None


def codec_label(codec_id: str | None) -> str:
    return _LABELS.get(codec_id or "", (codec_id or "?").upper())


def quick_alpha_containers() -> list[str]:
    """Contenedores donde algún códec de uso común conserva transparencia (para el aviso
    "usa WebM, MOV, MKV..."). Orden fijo y legible, no el del matrix."""
    order = ["webm", "qtff", "mkv", "webp", "apng", "gif"]
    return [c for c in order if quick_alpha_codec(c)]


def alpha_video_args(codec_id: str, crf: int = 18) -> list[str]:
    """Args de video para codificar `codec_id` CONSERVANDO el alfa -- los mismos ajustes
    con los que el matrix lo verificó (formato de píxel con alfa, -auto-alt-ref 0 en VP8,
    paleta con transparente en GIF)."""
    if codec_id == "vp9":
        return build_custom_quality_args("libvpx-vp9", max(crf, 20)) + ["-b:v", "0", "-pix_fmt", "yuva420p"]
    if codec_id == "vp8":
        return ["-c:v", "libvpx", "-crf", str(max(crf, 10)), "-b:v", "2M",
                "-pix_fmt", "yuva420p", "-auto-alt-ref", "0"]
    if codec_id == "prores":
        encoder = preferred_encoder("prores", "prores_ks")
        profile = next((p for p in VIDEO_ENCODER_PROFILES.get(encoder, [])
                        if p.get("label") == "4444" and "args" in p), None)
        args = list(profile["args"]) if profile else ["-c:v", encoder, "-profile:v", "4"]
        return _set_pix_fmt(args, "yuva444p10le")
    if codec_id == "cfhd":
        return ["-c:v", "cfhd", "-quality", "high", "-pix_fmt", "gbrap12le"]
    if codec_id == "gif":
        profile = next((p for p in VIDEO_ENCODER_PROFILES.get("gif", []) if "args" in p), None)
        return list(profile["args"]) if profile else ["-c:v", "gif"]
    if codec_id == "webp":
        return ["-c:v", "libwebp_anim", "-pix_fmt", "yuva420p", "-quality", "90", "-loop", "0"]
    if codec_id == "apng":
        return ["-c:v", "apng", "-pix_fmt", "rgba", "-plays", "0"]
    if codec_id == "qtrle":
        return ["-c:v", "qtrle", "-pix_fmt", "argb"]
    return []


def _set_pix_fmt(args: list[str], pix_fmt: str) -> list[str]:
    args = list(args)
    for i in range(len(args) - 1):
        if args[i] == "-pix_fmt":
            args[i + 1] = pix_fmt
            return args
    return args + ["-pix_fmt", pix_fmt]


def container_key(container: str | None) -> str:
    return normalize_container(container or "")


def alpha_capable_codecs(codec_ids, containers) -> list:
    """De `codec_ids`, los que conservan transparencia en al menos uno de `containers`
    (según el eje de alfa del matrix). Para filtrar las listas cuando la casilla
    "Conservar transparencia" está activa."""
    return [c for c in codec_ids if any(keeps_alpha(c, cont) for cont in containers)]


def profile_keeps_alpha(codec_id: str | None, profile: dict | None) -> bool:
    """¿Este perfil de codec_profiles.py puede conservar el alfa? Solo ProRes y HAP tienen
    perfiles que no: ProRes 422 (solo 4444/4444 XQ, formato 4:4:4) y HAP/HAP Q (solo
    "HAP Alpha"). Los personalizados se dejan pasar."""
    if not profile or profile.get("custom"):
        return True
    args = [str(a) for a in (profile.get("args") or [])]
    if codec_id == "prores":
        return any(a.startswith(("yuv444", "yuva444")) for a in args)
    if codec_id == "hap":
        return "hap_alpha" in args
    return True


def queue_alpha_counts(entries_with_paths) -> tuple[int, int]:
    """(con transparencia, sin ella) entre los archivos de VIDEO de la cola. Los de solo
    audio no cuentan (una carátula no es "video sin transparencia")."""
    from core.utils.media_extensions import is_audio_only
    with_alpha = without = 0
    for path, meta in entries_with_paths or []:
        if not meta or is_audio_only(path) or str(meta.get("video_codec") or "-") in ("-", ""):
            continue
        if meta_has_alpha(meta):
            with_alpha += 1
        else:
            without += 1
    return with_alpha, without
