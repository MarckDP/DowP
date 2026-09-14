# src/core/tabs/video_tools/compress_advisor.py
"""
Logica de recomendacion para la pestana "Comprimir" (modo Rapido): a partir de la
resolucion/bitrate real del archivo en preview (ffprobe), estima el peso resultante para
los 3 niveles (Ligero/Equilibrado/Agresivo) y sugiere cual conviene.

Soporta tanto archivos de Video (Video + Audio) como archivos de Solo Audio (WAV, FLAC,
MP3, AAC, OPUS, etc.), aplicando factores y estimaciones acordes a la naturaleza de cada medio.
"""
from core.tabs.video_tools.size_estimator import parse_duration_to_seconds, parse_kbps_from_label, estimate_size_mb
from core.tabs.video_tools.codec_profiles import build_custom_bitrate_args, build_custom_audio_bitrate_args
from core.utils.recode_guard import resolve_encoder
from PySide6.QtCore import QCoreApplication, QT_TRANSLATE_NOOP

LEVELS = ("ligero", "equilibrado", "agresivo")

LEVEL_LABELS = {
    "ligero": QT_TRANSLATE_NOOP("compress_advisor", "Ligero"),
    "equilibrado": QT_TRANSLATE_NOOP("compress_advisor", "Equilibrado"),
    "agresivo": QT_TRANSLATE_NOOP("compress_advisor", "Agresivo"),
}

def get_level_label(level: str) -> str:
    raw = LEVEL_LABELS.get(level, level)
    return QCoreApplication.translate("compress_advisor", raw)


# Fraccion del bitrate de video de origen (o de referencia) que apunta cada nivel.
LEVEL_FACTOR = {
    "ligero": 0.65,
    "equilibrado": 0.42,
    "agresivo": 0.25,
}

# Fraccion del bitrate de audio de origen cuando ya viene comprimido con perdida
AUDIO_LEVEL_FACTOR = {
    "ligero": 0.80,
    "equilibrado": 0.50,
    "agresivo": 0.30,
}

# Bitrates fijos sugeridos para Solo Audio (kbps)
AUDIO_LEVEL_DEFAULT_KBPS = {
    "ligero": 192,
    "equilibrado": 128,
    "agresivo": 96,
}

# Bitrate de video de referencia (kbps) por resolucion
_REFERENCE_BITRATE_BY_HEIGHT = [
    (2160, 35000),
    (1440, 16000),
    (1080, 8000),
    (720, 5000),
    (480, 2500),
    (360, 1200),
    (0, 800),
]

AUDIO_BITRATE_BY_LEVEL = {
    "ligero": 192,
    "equilibrado": 128,
    "agresivo": 96,
}

import os

# Extensiones estándar de solo audio
AUDIO_ONLY_EXTS = {".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a", ".opus", ".wma"}

# Piso duro para video y audio
_MIN_VIDEO_KBPS = 300
_MIN_AUDIO_KBPS = 32
_MAX_AUDIO_KBPS = 320


def is_audio_only(meta: dict, filepath: str | None = None) -> bool:
    """True si el medio o la metadata describe un archivo de solo audio (sin stream de video real)."""
    if filepath:
        ext = os.path.splitext(filepath)[1].lower()
        if ext in AUDIO_ONLY_EXTS:
            return True
    if not meta:
        return False
    wh = source_wh(meta)
    has_video = wh is not None or (source_video_kbps(meta) is not None)
    return not has_video


def reference_video_kbps(height: int | None) -> int:
    if not height or height <= 0:
        return 4000
    for min_h, kbps in _REFERENCE_BITRATE_BY_HEIGHT:
        if height >= min_h:
            return kbps
    return _REFERENCE_BITRATE_BY_HEIGHT[-1][1]


def source_wh(meta: dict) -> tuple[int, int] | None:
    raw = (meta or {}).get("resolución", "-")
    try:
        w_str, h_str = raw.lower().split("x")
        w, h = int(w_str), int(h_str)
        if w > 0 and h > 0:
            return w, h
    except (ValueError, AttributeError):
        pass
    return None


def source_video_kbps(meta: dict) -> float | None:
    return parse_kbps_from_label((meta or {}).get("bitrate_video"))


def source_audio_kbps(meta: dict) -> float | None:
    return parse_kbps_from_label((meta or {}).get("bitrate_audio"))


def baseline_video_kbps(meta: dict) -> float:
    """Bitrate base sobre el que se calculan los 3 niveles de video."""
    known = source_video_kbps(meta)
    if known:
        return known
    wh = source_wh(meta)
    height = wh[1] if wh else None
    return float(reference_video_kbps(height))


def target_video_kbps(meta: dict, level: str) -> int:
    base = baseline_video_kbps(meta)
    target = base * LEVEL_FACTOR[level]
    return max(_MIN_VIDEO_KBPS, round(target))


def target_audio_only_kbps(meta: dict, level: str) -> int:
    """Calcula el bitrate de audio objetivo (kbps) para un archivo de solo audio."""
    known = source_audio_kbps(meta)
    default_target = AUDIO_LEVEL_DEFAULT_KBPS[level]
    # Si viene de PCM/WAV/FLAC (> 500 kbps) o no se conoce, usamos el default curado
    if not known or known >= 500:
        return default_target
    
    # Si ya es un audio comprimido con perdida (ej. MP3 320k), calculamos fraccion
    target = known * AUDIO_LEVEL_FACTOR[level]
    return max(_MIN_AUDIO_KBPS, min(default_target, round(target)))


def pick_family(prefer_compat: bool) -> str:
    """'h264' si se prioriza compatibilidad; si no, 'hevc' cuando hay un encoder real."""
    if prefer_compat:
        return "h264"
    encoder = resolve_encoder("hevc")
    return "hevc" if encoder else "h264"


def pick_audio_family(prefer_compat: bool) -> str:
    """'aac' si se prioriza compatibilidad universal; si no, 'opus' (mejor compresion)."""
    return "aac" if prefer_compat else "opus"


def build_level_video_args(meta: dict, level: str, encoder: str) -> list[str]:
    kbps = target_video_kbps(meta, level)
    return build_custom_bitrate_args(encoder, "vbr", kbps)


def build_level_audio_args(meta: dict, level: str, encoder: str) -> list[str]:
    kbps = target_audio_only_kbps(meta, level)
    return build_custom_audio_bitrate_args(encoder, kbps)


def estimate_level_size_mb(meta: dict, level: str) -> float | None:
    duration_sec = parse_duration_to_seconds((meta or {}).get("duración", "0"))
    if duration_sec <= 0:
        return None
    
    if is_audio_only(meta):
        audio_kbps = target_audio_only_kbps(meta, level)
        return estimate_size_mb(0, audio_kbps, duration_sec)

    video_kbps = target_video_kbps(meta, level)
    audio_kbps = AUDIO_BITRATE_BY_LEVEL[level]
    return estimate_size_mb(video_kbps, audio_kbps, duration_sec)


def source_size_mb(meta: dict) -> float | None:
    duration_sec = parse_duration_to_seconds((meta or {}).get("duración", "0"))
    if duration_sec <= 0:
        return None
    
    if is_audio_only(meta):
        a_kbps = source_audio_kbps(meta)
        if a_kbps is None:
            # Fallback a PCM estandar si es solo audio y no se informo bitrate
            a_kbps = 1411.2
        return estimate_size_mb(0, a_kbps, duration_sec)

    return estimate_size_mb(source_video_kbps(meta), source_audio_kbps(meta), duration_sec)


def analyze_source(meta: dict) -> dict:
    """Recomienda un nivel para el archivo en preview, adaptado para video o audio puro."""
    if not meta:
        return {"known": False, "recommended_level": "equilibrado", "note": ""}

    if is_audio_only(meta):
        known_kbps = source_audio_kbps(meta)
        if known_kbps is None:
            return {
                "known": False,
                "recommended_level": "equilibrado",
                "note": QCoreApplication.translate("compress_advisor", "Archivo de solo audio. Equilibrado (128 kbps) es la opción recomendada para distribución."),
            }
        if known_kbps >= 500:
            return {
                "known": True,
                "recommended_level": "equilibrado",
                "note": QCoreApplication.translate("compress_advisor", "Audio sin comprimir o lossless (~{0} kbps). Equilibrado (128 kbps) reducirá hasta un 90% del tamaño sin pérdida perceptible.").format(int(known_kbps)),
            }
        if known_kbps <= 128:
            return {
                "known": True,
                "recommended_level": "ligero",
                "note": QCoreApplication.translate("compress_advisor", "El audio ya está a bitrate bajo (~{0} kbps). Se sugiere Ligero para evitar artefactos de recodificación.").format(int(known_kbps)),
            }
        return {
            "known": True,
            "recommended_level": "equilibrado",
            "note": QCoreApplication.translate("compress_advisor", "Bitrate de audio de origen (~{0} kbps). Equilibrado ofrece una excelente relación calidad/tamaño.").format(int(known_kbps)),
        }

    known_kbps = source_video_kbps(meta)
    wh = source_wh(meta)
    height = wh[1] if wh else None
    reference = reference_video_kbps(height)

    if known_kbps is None:
        return {
            "known": False,
            "recommended_level": "equilibrado",
            "note": QCoreApplication.translate("compress_advisor", "No se pudo leer el bitrate de origen todavía; se sugiere Equilibrado por defecto."),
        }

    equilibrado_target = reference * LEVEL_FACTOR["equilibrado"]
    if known_kbps <= equilibrado_target:
        return {
            "known": True,
            "recommended_level": "ligero",
            "note": QCoreApplication.translate(
                "compress_advisor",
                "Este archivo ya está eficientemente comprimido para su resolución: "
                "recomprimirlo agresivamente ahorraría poco y perdería calidad. Se sugiere Ligero."
            ),
        }
    if known_kbps >= reference * 1.3:
        return {
            "known": True,
            "recommended_level": "agresivo",
            "note": QCoreApplication.translate(
                "compress_advisor",
                "El bitrate de origen está bastante por encima de lo necesario para su "
                "resolución: hay margen grande de ahorro. Se sugiere Agresivo."
            ),
        }
    return {
        "known": True,
        "recommended_level": "equilibrado",
        "note": QCoreApplication.translate("compress_advisor", "El bitrate de origen es razonable para su resolución. Equilibrado da un buen balance de ahorro/calidad."),
    }


def estimate_queue_totals(entries: list[dict], level: str) -> dict:
    """entries: lista de metadatos ffprobe (uno por archivo de la cola, mismo esquema que
    set_source_media). Devuelve el peso actual total vs el proyectado a ese nivel."""
    current_total = 0.0
    projected_total = 0.0
    counted = 0
    for meta in entries:
        cur = source_size_mb(meta)
        proj = estimate_level_size_mb(meta, level)
        if cur is not None:
            current_total += cur
        if proj is not None:
            projected_total += proj
            counted += 1
    return {
        "current_total_mb": current_total,
        "projected_total_mb": projected_total,
        "file_count": counted,
    }
