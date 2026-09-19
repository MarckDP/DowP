# src/core/utils/default_presets.py
"""
Preajustes que vienen EMPAQUETADOS con la app (ver conversación) - a diferencia de un
preajuste que un usuario guarda desde Avanzado en su propia máquina, estos se instalan en
la de cualquiera, así que:

- Los códecs de video con variante de hardware (h264/hevc) guardan SIEMPRE args de
  software (libx264/libx265): un preajuste empaquetado con "-c:v h264_nvenc" adentro
  rompería directo en cualquier PC sin esa GPU especifica. Los dos preajustes
  "Acelerado por GPU" (ver _gpu_auto_preset) no son la excepción: guardan los mismos
  args de software y, además, la intención ("este códec, este nivel de calidad, usa
  GPU si hay"), que se resuelve al aplicarlos en cada equipo. ProRes/DNxHR/CineForm no
  tienen ese problema (nunca tuvieron variante de hardware en ffmpeg, ver conversación).
- Los argumentos de cada perfil se toman llamando a codec_profiles.py (la misma tabla que
  ya usan Comprimir/Edición/Avanzado), nunca copiados a mano - si esos valores cambian
  algún día, estos preajustes los siguen automáticamente en la próxima build en vez de
  quedar desactualizados en silencio.

Namespace: todos van a "video_tools/avanzado" (el único namespace que hoy lee
PresetsPanel) - la categorización real para browsing/filtro es el campo "function" de
cada uno (ver preset_manager.PRESET_FUNCTIONS), no el namespace.
"""
from core.tabs.video_tools.codec_profiles import get_profiles, build_custom_audio_bitrate_args, recommend_audio_codec
from core.utils.audio_filter_builder import build_loudnorm_filter
from PySide6.QtCore import QCoreApplication

_NAMESPACE = "video_tools/avanzado"

# Versión de ESTE catálogo (no del preset individual): subir cuando se agregue/cambie un
# preajuste aquí, para que PresetManager sepa que hay defaults nuevos para sembrar sin
# resembrar (ni resucitar) los que el usuario ya haya modificado o borrado - ver
# PresetManager.seed_defaults().
DEFAULT_PRESETS_VERSION = 2


def _video_profile_args(encoder: str, label_hint: str) -> list[str]:
    """Los args del primer perfil de `encoder` (ver codec_profiles.get_profiles) cuyo
    label contenga `label_hint` (case-insensitive) - por substring, no por índice fijo,
    para no romperse si esa tabla cambia de orden (mismo criterio que
    editing_panel._quick_proxy_profile)."""
    for profile in get_profiles("video", encoder):
        if "args" in profile and label_hint.lower() in profile["label"].lower():
            return list(profile["args"])
    raise ValueError(f"No se encontró un perfil de '{encoder}' con '{label_hint}' en el label.")


def _compress_preset(name: str, video_encoder: str, crf_hint: str) -> dict:
    video_args = _video_profile_args(video_encoder, crf_hint)
    return {
        "namespace": _NAMESPACE,
        "name": name,
        "function": "comprimir",
        "job_type": "RECODE",
        "settings": {
            "stream_mode": "video+audio",
            "video_mode": "recode",
            "video_codec": "h264" if video_encoder == "libx264" else "hevc",
            "video_args": video_args,
            "audio_mode": "recode",
            "audio_codec": "aac",
            "audio_args": build_custom_audio_bitrate_args("aac", 128),
            "container": "mp4",
        },
    }


def _gpu_auto_preset(name: str, codec_id: str, software_encoder: str, label_hint: str) -> dict:
    """Preajuste que usa la GPU del equipo donde se APLICA, y cae a CPU si no hay.

    A diferencia del resto de los empaquetados (que fijan libx264/libx265 justamente
    para no romper en un PC sin esa GPU), aquí los args guardados son los de software
    PERO llevan "video_tier"/"video_engine_mode": al aplicarlos, PresetsPanel resuelve
    el encoder real contra la GPU detectada en ese equipo -- NVENC, AMF o QuickSync
    según la marca (ver presets_panel._resolve_engine_for_this_pc). Los args de
    software siguen ahí como respaldo: si el equipo no tiene GPU, o el preajuste se lee
    con una versión vieja de DowP, se usa el camino de siempre."""
    video_args = _video_profile_args(software_encoder, label_hint)
    return {
        "namespace": _NAMESPACE,
        "name": name,
        "function": "convertir",
        "job_type": "RECODE",
        "settings": {
            "stream_mode": "video+audio",
            "video_mode": "recode",
            "video_codec": codec_id,
            "video_args": video_args,
            "video_tier": "media",
            "video_engine_mode": "auto",
            "audio_mode": "recode",
            "audio_codec": "aac",
            "audio_args": build_custom_audio_bitrate_args("aac", 192),
            "container": "mp4",
        },
    }


def _proxy_preset(name: str, codec_id: str, encoder: str, label_hint: str) -> dict:
    video_args = _video_profile_args(encoder, label_hint)
    audio_codec = recommend_audio_codec(codec_id)  # pcm_s24le para los 3 (ver codec_profiles.RECOMMENDED_AUDIO_CODEC)
    return {
        "namespace": _NAMESPACE,
        "name": name,
        "function": "edicion",
        "job_type": "RECODE",
        "settings": {
            "stream_mode": "video+audio",
            "video_mode": "recode",
            "video_codec": codec_id,
            "video_args": video_args,
            "audio_mode": "recode",
            "audio_codec": audio_codec,
            "audio_args": ["-c:a", audio_codec],
            "container": "qtff",
        },
    }


def _gif_preset(name: str, label_hint: str) -> dict:
    video_args = _video_profile_args("gif", label_hint)
    return {
        "namespace": _NAMESPACE,
        "name": name,
        "function": "gif",
        "job_type": "RECODE",
        "settings": {
            "stream_mode": "video_only",
            "video_mode": "recode",
            "video_codec": "gif",
            "video_args": video_args,
            "audio_mode": "none",
            "audio_codec": None,
            "audio_args": [],
            "container": "gif",
        },
    }


def _loudness_preset(name: str, integrated_lufs: float) -> dict:
    """Solo toca audio (video_mode: copy) - container "same" para no forzar un
    contenedor distinto al del archivo de origen (ver conversación: soporte agregado a
    PresetsPanel.get_settings() para que esto funcione con presets, no solo con
    Comprimir/Manual que ya lo tenía)."""
    loudnorm_filter = build_loudnorm_filter(integrated_lufs=integrated_lufs, true_peak_dbtp=-1.0, lra_lu=11.0)
    return {
        "namespace": _NAMESPACE,
        "name": name,
        "function": "audio",
        "job_type": "RECODE",
        "settings": {
            "stream_mode": "video+audio",
            "video_mode": "copy",
            "video_codec": None,
            "video_args": [],
            "audio_mode": "recode",
            "audio_codec": "aac",
            "audio_args": ["-af", loudnorm_filter, "-c:a", "aac", "-b:a", "256k"],
            "container": "same",
        },
    }


def build_default_presets() -> list[dict]:
    """Catálogo completo de preajustes empaquetados - ver PresetManager.seed_defaults()
    para cómo (y cuándo) se instalan en presets.json."""
    return [
        _compress_preset("H264 Equilibrado", "libx264", "Media (CRF 23)"),
        _compress_preset("H265 Equilibrado", "libx265", "Media (CRF 24)"),

        _gpu_auto_preset("H264 Acelerado por GPU", "h264", "libx264", "Media (CRF 23)"),
        _gpu_auto_preset("H265 Acelerado por GPU", "hevc", "libx265", "Media (CRF 24)"),

        _proxy_preset("Proxy Apple ProRes", "prores", "prores_aw", "422 Proxy"),
        _proxy_preset("Proxy DNxHR", "dnxhd", "dnxhd", "DNxHR LB"),
        _proxy_preset("Proxy GoPro CineForm", "cfhd", "cfhd", "Low (Proxy)"),

        _gif_preset("GIF Alto", "Calidad Alta"),
        _gif_preset("GIF Medio", "Calidad Media"),
        _gif_preset("GIF Bajo", "Calidad Baja"),

        # Objetivos de LUFS mas citados de la industria (EBU R128 para broadcast, Apple
        # Podcasts para voz, Spotify/YouTube/Amazon Music para streaming/musica) - ver
        # conversación: esto es conocimiento de dominio, no algo verificable con una
        # herramienta local como el resto de esta sesión.
        _loudness_preset("Normalizar Audio - Broadcast (-23 LUFS)", -23.0),
        _loudness_preset("Normalizar Audio - Podcast (-16 LUFS)", -16.0),
        _loudness_preset("Normalizar Audio - Streaming (-14 LUFS)", -14.0),

        {
            "namespace": _NAMESPACE, "name": "Convertir a MP4", "function": "convertir", "job_type": "RECODE",
            "settings": {
                "stream_mode": "video+audio", "video_mode": "recode", "video_codec": "h264",
                "video_args": _video_profile_args("libx264", "Media (CRF 23)"),
                "audio_mode": "recode", "audio_codec": "aac",
                "audio_args": build_custom_audio_bitrate_args("aac", 192),
                "container": "mp4",
            },
        },
        {
            "namespace": _NAMESPACE, "name": "Convertir a MP3", "function": "convertir", "job_type": "RECODE",
            "settings": {
                "stream_mode": "audio_only", "video_mode": "none", "video_codec": None, "video_args": [],
                "audio_mode": "recode", "audio_codec": "mp3",
                "audio_args": build_custom_audio_bitrate_args("libmp3lame", 192),
                "container": "mp3",
            },
        },
    ]
