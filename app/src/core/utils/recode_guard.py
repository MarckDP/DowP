# src/core/utils/recode_guard.py
"""
"Colchon" de recodificacion: evalua si una combinacion (codec de video, codec de audio,
contenedor) es viable ANTES de lanzar un proceso de ffmpeg, para advertir o bloquear en
vez de dejar que el usuario se encuentre con un error de ffmpeg a mitad de un render.

Cuatro categorias de resultado por combinacion:
  - "ok":         verificado empiricamente, sin objeciones.
  - "warning":    o bien ffmpeg acepta el mux pero el estandar (Wikipedia) lo marca como
                  no estandar/parcial/privado (riesgo de que no reproduzca en todos lados),
                  o bien el codec de video solo tiene encoder por software en este equipo
                  (funciona, pero mas lento).
  - "unverified": no hay encoder en este ffmpeg para probarlo empiricamente; el dato es
                  documental (de Wikipedia) o directamente no existe.
  - "blocked":    ffmpeg rechaza el mux, o no hay ningun encoder (ni hardware ni software)
                  para ese codec en este equipo. No se debe permitir iniciar el proceso.

Combina tres fuentes independientes, cada una con su propio rol, sin fusionarlas en un
solo campo:
  - ffmpeg_codec_matrix.json: verificado empiricamente contra el ffmpeg empaquetado (ver
    tools/codec_matrix/). Fuente primaria: "¿este contenedor acepta este codec aca?".
    Incluye ademas "container_streams" (mismo archivo, eje independiente): "¿este
    contenedor acepta 2+ streams de audio simultaneos - solo-audio, o video+audio?" -
    ver container_supports_multi_audio(). No asumir que "contenedor de audio puro"
    implica "1 sola pista": el matrix confirmo que m4a/ogg/opus SI aceptan multipista,
    y que mp3/wav/flac (y ciertos codecs PCM en flv) NO.
  - codec_container_compatibility.json (Wikipedia): NO se usa para decidir bloqueo. Solo
    se consulta como señal secundaria de "riesgo de reproduccion" cuando ffmpeg ya acepto
    el mux, para casos donde el contenedor es permisivo (acepta cualquier FourCC) pero el
    estandar nunca contemplo esa combinacion.
  - hardware_detector.codec_status: verificado por probe-encode real en ESTE equipo.
    Responde "¿hay un encoder que funcione (hardware o software) para este codec aca?".
"""
from PySide6.QtCore import QT_TRANSLATE_NOOP
import json
import os

from core.logger.logger_manager import logger
from core.utils.hardware_detector import detect_hardware
from core.utils.paths import get_src_dir
from PySide6.QtCore import QCoreApplication

_DATA_DIR = os.path.join(get_src_dir(), "assets", "data")
_MATRIX_PATH = os.path.join(_DATA_DIR, "ffmpeg_codec_matrix.json")
_WIKI_PATH = os.path.join(_DATA_DIR, "codec_container_compatibility.json")
# NOTA: rutas relativas al arbol de codigo fuente. Cuando el proyecto tenga empaquetador
# (hoy no lo tiene, ver AGENTS.md), esta resolucion va a necesitar revisarse para leer
# desde el recurso empaquetado en vez del repo.

CONTAINER_ALIASES = {
    "mkv": "mkv", "mk3d": "mkv", "mka": "mkv", "mks": "mkv",
    "mp4": "mp4", "m4v": "mp4",
    # NOTA: "m4a" NO alias a "mp4" a proposito (a diferencia de m4v). El matrix ya prueba
    # "m4a" como id propio - ffmpeg elige el muxer "ipod" (mas restrictivo que "mp4") para
    # esa extension, y aliasarlo a "mp4" descartaba esa entrada real y mas estricta (ej.
    # HEVC entra en mp4 pero no en m4a: "[ipod] Could not find tag for codec hevc..." - ver
    # conversacion). Sin entrada aca, normalize_container("m4a") devuelve "m4a" tal cual.
    "mov": "qtff", "qt": "qtff",
    "asf": "asf", "wmv": "asf", "wma": "asf",
    "avi": "avi",
    "mxf": "mxf",
    "mpg": "ps", "mpeg": "ps", "m2p": "ps", "ps": "ps",
    "ts": "ts", "m2ts": "ts", "mts": "ts", "tsv": "ts",
    "3gp": "3gp",
    "3g2": "3g2",
}
# id de contenedor nuestro -> id de contenedor en el JSON de Wikipedia (que fusiona ps/ts).
_WIKI_CONTAINER_ID = {
    "ps": "ps_ts", "ts": "ps_ts",
    "mkv": "mkv", "mp4": "mp4", "qtff": "qtff", "asf": "asf",
    "avi": "avi", "mxf": "mxf", "3gp": "3gp", "3g2": "3g2",
}

_HARDWARE_TRACKED_CODECS = {"h264", "hevc", "av1", "vp9"}

_matrix_cache = None
_wiki_cache = None


def _load_json(path, cache_attr):
    global _matrix_cache, _wiki_cache
    cached = globals()[cache_attr]
    if cached is not None:
        return cached
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"RecodeGuard: No se pudo cargar {path}: {e}")
        data = {}
    globals()[cache_attr] = data
    return data


def _load_matrix():
    return _load_json(_MATRIX_PATH, "_matrix_cache") or {"codecs": {}, "containers": []}


def _load_wiki():
    return _load_json(_WIKI_PATH, "_wiki_cache") or {}


def normalize_container(container: str) -> str:
    """Convierte una extension/alias de UI (ej. '.mov', 'MOV', 'mov') al id de la matriz."""
    key = container.lower().lstrip(".")
    return CONTAINER_ALIASES.get(key, key)



# Etiquetas de categoria traducidas UNA sola vez cada una y reutilizadas como valor en
# *_CATEGORIES y como clave en *_CATEGORY_ORDER (se muestran tal cual como encabezado de
# grupo en el combo, ver advanced_recode_panel.py::_reload_codec_lists). Traducir cada
# aparicion por separado (como estaba antes) permite que dos codecs de la misma categoria
# terminen con textos distintos si solo se edita una de las traducciones.
_CAT_WEB = QCoreApplication.translate("recode_guard", "Distribución / Web")
_CAT_PROFESIONAL = QCoreApplication.translate("recode_guard", "Edición Profesional")
_CAT_LOSSLESS = QCoreApplication.translate("recode_guard", "Sin Pérdida (Lossless)")
_CAT_ANTIGUOS_VIDEO = QCoreApplication.translate("recode_guard", "Formatos Antiguos")
_CAT_ANIMACIONES = QCoreApplication.translate("recode_guard", "Animaciones")
_CAT_ALTA_CALIDAD = QCoreApplication.translate("recode_guard", "Alta Calidad (Sin pérdida)")
_CAT_SURROUND = QCoreApplication.translate("recode_guard", "Cine / TV (Surround)")
_CAT_ANTIGUOS_AUDIO = QCoreApplication.translate("recode_guard", "Antiguos")
_CAT_OTROS = QCoreApplication.translate("recode_guard", "Otros")

VIDEO_CATEGORIES = {
    "h264": _CAT_WEB, "hevc": _CAT_WEB, "av1": _CAT_WEB, "vp9": _CAT_WEB,
    "prores": _CAT_PROFESIONAL, "dnxhd": _CAT_PROFESIONAL, "cfhd": _CAT_PROFESIONAL,
    "ffv1": _CAT_LOSSLESS, "utvideo": _CAT_LOSSLESS, "huffyuv": _CAT_LOSSLESS,
    "mpeg4": _CAT_ANTIGUOS_VIDEO, "mpeg2video": _CAT_ANTIGUOS_VIDEO, "msmpeg4v3": _CAT_ANTIGUOS_VIDEO,
    "wmv2": _CAT_ANTIGUOS_VIDEO, "wmv1": _CAT_ANTIGUOS_VIDEO, "theora": _CAT_ANTIGUOS_VIDEO, "vp8": _CAT_ANTIGUOS_VIDEO,
    "gif": _CAT_ANIMACIONES, "apng": _CAT_ANIMACIONES, "webp": _CAT_ANIMACIONES,
}
VIDEO_CATEGORY_ORDER = {_CAT_WEB: 1, _CAT_PROFESIONAL: 2, _CAT_LOSSLESS: 3, _CAT_ANIMACIONES: 4, _CAT_ANTIGUOS_VIDEO: 5, _CAT_OTROS: 6}

AUDIO_CATEGORIES = {
    "aac": _CAT_WEB, "libopus": _CAT_WEB, "opus": _CAT_WEB,
    "mp3": _CAT_WEB, "libmp3lame": _CAT_WEB, "vorbis": _CAT_WEB,
    "flac": _CAT_ALTA_CALIDAD, "alac": _CAT_ALTA_CALIDAD,
    "pcm_s16le": _CAT_ALTA_CALIDAD, "pcm_s24le": _CAT_ALTA_CALIDAD, "pcm_s32le": _CAT_ALTA_CALIDAD,
    "wavpack": _CAT_ALTA_CALIDAD,
    "ac3": _CAT_SURROUND, "eac3": _CAT_SURROUND, "dts": _CAT_SURROUND, "truehd": _CAT_SURROUND,
    "wmav2": _CAT_ANTIGUOS_AUDIO, "mp2": _CAT_ANTIGUOS_AUDIO,
}
AUDIO_CATEGORY_ORDER = {_CAT_WEB: 1, _CAT_ALTA_CALIDAD: 2, _CAT_SURROUND: 3, _CAT_ANTIGUOS_AUDIO: 4, _CAT_OTROS: 5}

def get_video_codecs(only_verified: bool = True) -> list[dict]:
    matrix = _load_matrix()
    out = []
    for codec_id, entry in matrix.get("codecs", {}).items():
        if entry.get("kind") != "video": continue
        if only_verified and not entry.get("verified"): continue
        cat = VIDEO_CATEGORIES.get(codec_id, _CAT_OTROS)
        out.append({
            "codec_id": codec_id, 
            "display_name": entry.get("display_name", codec_id), 
            "verified": entry.get("verified", False),
            "category": cat,
            "cat_order": VIDEO_CATEGORY_ORDER.get(cat, 99)
        })
    return sorted(out, key=lambda c: (c["cat_order"], c["display_name"].lower()))

def get_audio_codecs(only_verified: bool = True) -> list[dict]:
    matrix = _load_matrix()
    out = []
    for codec_id, entry in matrix.get("codecs", {}).items():
        if entry.get("kind") != "audio": continue
        if only_verified and not entry.get("verified"): continue
        cat = AUDIO_CATEGORIES.get(codec_id, _CAT_OTROS)
        out.append({
            "codec_id": codec_id, 
            "display_name": entry.get("display_name", codec_id), 
            "verified": entry.get("verified", False),
            "category": cat,
            "cat_order": AUDIO_CATEGORY_ORDER.get(cat, 99)
        })
    return sorted(out, key=lambda c: (c["cat_order"], c["display_name"].lower()))

def resolve_encoder(codec_id: str) -> str | None:
    """
    Devuelve el encoder de ffmpeg efectivo para un codec_id en ESTE equipo: para los
    codecs que hardware_detector.py rastrea (h264/hevc/av1/vp9) usa el backend elegido
    por probe-encode real (nvenc/qsv/amf/vaapi/software); para el resto, el encoder de
    software por defecto verificado en ffmpeg_codec_matrix.json.
    """
    if codec_id in _HARDWARE_TRACKED_CODECS:
        hw_info = detect_hardware()
        status = hw_info.get("codec_status", {}).get(codec_id)
        if status and status.get("encoder"):
            return status["encoder"]

    matrix = _load_matrix()
    entry = matrix.get("codecs", {}).get(codec_id)
    return entry.get("encoder") if entry else None


def software_encoder(codec_id: str | None) -> str | None:
    """Encoder de SOFTWARE (CPU, sin aceleracion por hardware) verificado para este
    codec_id, para cuando el usuario fuerza CPU a mano (ver gui/widgets/engine_badge.py)
    - a diferencia de resolve_encoder(), que prioriza hardware cuando esta disponible."""
    if not codec_id:
        return None
    matrix = _load_matrix()
    entry = matrix.get("codecs", {}).get(codec_id)
    return entry.get("encoder") if entry else None


def has_hardware_encoder(codec_id: str | None) -> bool:
    """True si HAY un encoder acelerado por hardware confirmado (probe-encode real, ver
    hardware_detector.py) para este codec_id en ESTE equipo."""
    if not codec_id or codec_id not in _HARDWARE_TRACKED_CODECS:
        return False
    hw_info = detect_hardware()
    status = hw_info.get("codec_status", {}).get(codec_id)
    return bool(status and status.get("status") == "full")


# Mapeo contenedor -> extensión de archivo real, para los pocos casos donde el id de
# contenedor no coincide con su extensión (ej. "qtff" produce un .mov, no un .qtff).
# Cualquier contenedor no listado aquí usa su propio id como extensión tal cual. Unica
# fuente para esto (antes vivía duplicado dentro de video_tools_view.py).
CONTAINER_TO_EXTENSION = {
    "qtff": "mov",
    "asf": "wmv",
    "ps": "mpg",
}

# Etiquetas de UI por contenedor, para combos que listan TODOS los contenedores
# compatibles con un codec (ver get_compatible_containers) - no solo un subconjunto
# curado. Unica fuente para esto (antes vivia solo dentro de advanced_recode_panel.py).
CONTAINER_LABELS = {
    "qtff": "MOV",
    "mov": "MOV",
    "mp4": "MP4",
    "mkv": "MKV",
    "avi": "AVI",
    "asf": "WMV",
    "ps": "MPEG-PS",
    "ts": "MPEG-TS",
    "webm": "WEBM",
    "mxf": "MXF",
    "3gp": "3GP",
    "3g2": "3G2",
    "mp3": "MP3",
    "m4a": "M4A",
    "ogg": "OGG",
    "wav": "WAV",
    "flac": "FLAC",
    "flv": "FLV",
    "apng": "APNG",
    "webp": "WEBP",
    "gif": "GIF",
    "opus": "OPUS",
}


def get_compatible_containers(codec_ids: list[str]) -> list[str]:
    """Interseccion de contenedores soportados por todos los codec_id dados (ya verificados)."""
    matrix = _load_matrix()
    all_containers = set(matrix.get("containers", []))
    result = None
    for codec_id in codec_ids:
        entry = matrix.get("codecs", {}).get(codec_id)
        if not entry or not entry.get("verified"):
            continue
        supported = {c for c, info in entry["containers"].items() if info["supported"]}
        result = supported if result is None else (result & supported)
    if result is None:
        return sorted(all_containers)
    return sorted(result)


def get_compatible_codecs(container_id: str, kind: str) -> list[str]:
    """Inverso de get_compatible_containers: códecs (de video o audio, ver `kind`) que el
    matrix confirma EMPÍRICAMENTE que entran en ESTE contenedor. Fuente de verdad real
    para "¿qué códec le sirve a este contenedor?" en vez de una tabla curada a mano por
    contenedor - evita asumir cosas que el matrix ya sabe (o que resultan estar mal:
    ej. "ogg" parece audio-only por el nombre, pero el matrix confirma que sí acepta
    video Theora/VP8)."""
    matrix = _load_matrix()
    container_id = normalize_container(container_id)
    result = []
    for codec_id, entry in matrix.get("codecs", {}).items():
        if entry.get("kind") != kind or not entry.get("verified"):
            continue
        info = entry.get("containers", {}).get(container_id)
        if info and info.get("supported"):
            result.append(codec_id)
    return sorted(result)


def container_supports_video(container_id: str) -> bool:
    """True si el matrix confirma que ALGÚN códec de video entra en este contenedor - la
    forma real de saber si un contenedor es "de audio puro" (MP3/WAV/FLAC/...), en vez de
    asumirlo por convención/nombre de contenedor."""
    return bool(get_compatible_codecs(container_id, "video"))


def is_stream_copy_compatible(codec_id: str | None, container_id: str) -> bool:
    """True SOLO si el matrix confirma EMPÍRICAMENTE que este códec entra en este
    contenedor sin necesidad de remux (-c copy, sin pérdida de calidad).

    A diferencia de get_compatible_containers() -que a propósito es permisivo con
    códecs no verificados, para no ocultarle opciones al usuario en Avanzado- aquí
    conviene ser estricto: esto es la base para decidir si Convertir puede prometerle al
    usuario "esto se copia tal cual, sin pérdida" - un falso positivo ahí es mucho peor
    que un falso negativo (recodificar de más cuando en realidad hubiera andado igual)."""
    if not codec_id:
        return False
    matrix = _load_matrix()
    entry = matrix.get("codecs", {}).get(codec_id)
    if not entry or not entry.get("verified"):
        return False
    info = entry.get("containers", {}).get(normalize_container(container_id))
    return bool(info and info.get("supported"))


def _load_container_streams() -> dict:
    return _load_matrix().get("container_streams", {})


def container_supports_multi_audio(
    container_id: str,
    audio_codec_id: str | None = None,
    video_codec_id: str | None = None,
) -> bool:
    """True si el matrix confirma EMPIRICAMENTE que este contenedor acepta 2+ streams de
    audio simultaneos (ej. microfono + audio de sistema de OBS) - eje INDEPENDIENTE de
    "¿este codec entra en este contenedor?" (is_stream_copy_compatible/
    get_compatible_codecs): un contenedor puede aceptar un codec con 1 sola pista y
    rechazarlo con 2 (ej. mp3/wav/flac, que son de 1 sola pista SIEMPRE, sin importar el
    codec) - o aceptar 2 pistas con un codec puntual y no con otro (ej. flv rechaza
    multipista con ciertos PCM pero no con AAC/MP3). Nunca asumir por el nombre/convencion
    del contenedor: el matrix confirmo que m4a/ogg/opus SI aceptan multipista pese a ser
    "de audio puro", y que HEVC en particular es lo unico irregular de m4a (ver
    container_supports_video / is_stream_copy_compatible para esa otra restriccion).

    Args:
        container_id: extension o alias de contenedor (ej. "mp3", ".m4a", "mkv").
        audio_codec_id: si se pasa, la pregunta es especifica a ESE codec de audio (mas
            estricto - recomendado cuando ya se sabe con que codec se va a exportar,
            ej. antes de decidir si hace falta el fallback a "solo la pista 1"). Sin
            esto, la pregunta es permisiva: True si ALGUN codec de audio ya confirmado
            para este contenedor acepta multipista (util solo para listados de UI).
        video_codec_id: si se pasa (junto con audio_codec_id), pregunta por el escenario
            "1 video + 2 audio" en vez de "solo audio" - los dos escenarios se probaron
            por separado porque no son equivalentes (ver
            tools/codec_matrix/run_matrix.py::probe_container_streams).

    Returns:
        False tambien si el contenedor no tiene NINGUN dato para este eje (ej. video_codec_id
        en un contenedor que nunca acepta video, como mp3/wav/flac) - "no aplica" y "no
        soportado" devuelven lo mismo aca a proposito: en ambos casos no hay que ofrecer
        multipista.
    """
    container_id = normalize_container(container_id)
    streams = _load_container_streams().get(container_id, {})

    if video_codec_id is not None:
        entries = streams.get("video_audio_multi", {})
        if audio_codec_id is None:
            return any(e.get("supported") for k, e in entries.items() if k.startswith(f"{video_codec_id}+"))
        entry = entries.get(f"{video_codec_id}+{audio_codec_id}")
        return bool(entry and entry.get("supported"))

    entries = streams.get("audio_only_multi", {})
    if audio_codec_id is None:
        return any(e.get("supported") for e in entries.values())
    entry = entries.get(audio_codec_id)
    return bool(entry and entry.get("supported"))


def get_dimension_alignment(codec_id: str | None) -> dict:
    """
    Requisito de paridad de ancho/alto para un códec de video, según
    ffmpeg_codec_matrix.json (ver tools/codec_matrix/run_matrix.py::_probe_dimension_alignment,
    que prueba directo contra el encoder si acepta ancho/alto impar).

    A diferencia de get_channel_support(), aquí el faltante de dato NO es permisivo: si el
    códec no está verificado o no tiene este campo relevado, se asume que hace falta par en
    los dos ejes (el caso más común, YUV 4:2:0) — al revés de "permitir todo por defecto"
    sería dejar pasar una resolución que en la práctica hace fallar el export.

    Returns: {"width_even_required": bool, "height_even_required": bool}
    """
    default = {"width_even_required": True, "height_even_required": True}
    if not codec_id:
        return default
    matrix = _load_matrix()
    entry = matrix.get("codecs", {}).get(codec_id)
    if not entry or not entry.get("verified"):
        return default
    return entry.get("dimension_alignment") or default


def get_channel_support(codec_id: str | None, container: str | None) -> dict:
    """
    Soporte de canales (mono/estéreo/5.1) de un codec de audio en un contenedor dado.

    Cruza dos datos de ffmpeg_codec_matrix.json (ver tools/codec_matrix/run_matrix.py):
    el límite del encoder en sí (codecs[id].channels) y el límite propio del muxer del
    contenedor si fue relevado (codecs[id].containers[cont].channels) — este último tiene
    prioridad porque hay casos donde el encoder soporta N canales pero el contenedor no
    (ej. AMR-NB en 3GP: el encoder ya rechaza estéreo, pero podría haber muxers con su
    propia restricción independiente).

    Permisivo ante falta de dato (codec no verificado, combinación no relevada, o
    codec_id/container ausentes): devuelve supported=True para no ocultar/bloquear
    opciones de UI sin evidencia empírica real.

    Returns: {"1": {"supported": bool, "reason": str|None},
              "2": {...}, "6": {...}}
    """
    result = {ch: {"supported": True, "reason": None} for ch in ("1", "2", "6")}
    if not codec_id or not container:
        return result

    matrix = _load_matrix()
    entry = matrix.get("codecs", {}).get(codec_id)
    if not entry or not entry.get("verified"):
        return result

    container_id = normalize_container(container)
    codec_channels = entry.get("channels") or {}
    cont_info = entry.get("containers", {}).get(container_id) or {}
    cont_channels = cont_info.get("channels") or {}

    for ch in ("1", "2", "6"):
        info = cont_channels.get(ch) or codec_channels.get(ch)
        if info is None:
            continue
        result[ch] = {"supported": info.get("supported", True), "reason": info.get("ffmpeg_error")}
    return result


def _check_container_support(codec_id: str) -> dict:
    matrix = _load_matrix()
    codec_entry = matrix.get("codecs", {}).get(codec_id)
    if codec_entry is None:
        return {"level": "unverified", "message": QT_TRANSLATE_NOOP("RecodeMessages", "'%1' no esta en la matriz verificada."), "message_args": [codec_id]}
    if not codec_entry.get("verified"):
        return {"level": "unverified", "message": codec_entry.get("skip_reason") or QT_TRANSLATE_NOOP("RecodeMessages", "No se pudo verificar empiricamente con este ffmpeg.")}
    return {"level": "verified", "message": None, "entry": codec_entry}


def _check_playback_risk(codec_entry: dict, container_id: str) -> dict | None:
    """Solo se llama cuando ffmpeg YA acepto el mux. Cruza con Wikipedia para detectar
    casos donde el contenedor fue permisivo (acepto cualquier FourCC) pero el estandar
    nunca contemplo esa combinacion.

    Devuelve datos ESTRUCTURADOS, no un mensaje ya armado: este modulo no es un QObject
    y no tiene acceso a .tr(), asi que el texto final (traducible) se compone en
    advanced_recode_panel.py::_format_playback_risk_message, que si es un QWidget.
    None si no hay objecion (nivel "full") o no hay dato de Wikipedia para cruzar.

    Returns: {"level": str, "via": str|None, "requires": str|None, "note": str|None}
    """
    wiki_name = codec_entry.get("wikipedia_name")
    if not wiki_name:
        return None

    wiki = _load_wiki()
    wiki_cont_id = _WIKI_CONTAINER_ID.get(container_id, container_id)
    kind = codec_entry.get("kind")
    wiki_section = wiki.get("video_codecs" if kind == "video" else "audio_codecs", {})
    wiki_codec = wiki_section.get(wiki_name)
    if not wiki_codec:
        return None

    support = wiki_codec.get("container_support", {}).get(wiki_cont_id)
    if not support:
        return None

    level = support.get("level")
    if level == "full":
        return None

    return {
        "level": level,
        "via": support.get("via"),
        "requires": support.get("requires"),
        "note": support.get("note"),
    }


def _check_hardware_support(codec_id: str) -> dict:
    if codec_id not in _HARDWARE_TRACKED_CODECS:
        return {"level": "not_tracked", "reason": None}

    hw_info = detect_hardware()
    status = hw_info.get("codec_status", {}).get(codec_id)
    if status is None:
        return {"level": "unverified", "reason": QCoreApplication.translate("recode_guard", "Sin datos de hardware para este codec (correr deteccion de hardware).")}

    if status["status"] == "none":
        return {"level": "blocked", "reason": status["note"]}
    if status["status"] == "partial":
        return {"level": "warning", "reason": status["note"]}
    return {"level": "ok", "reason": None}


_SEVERITY_ORDER = {"blocked": 3, "warning": 2, "unverified": 1, "ok": 0}


def evaluate_recode(video_codec: str | None, audio_codec: str | None, container: str) -> dict:
    """
    Evalua una combinacion de recodificacion antes de lanzar ffmpeg.

    Args:
        video_codec: codec_id (ej. "h264") o None si el video se copia / no hay video.
        audio_codec: codec_id (ej. "aac") o None si el audio se copia / no hay audio.
        container: extension o alias de contenedor (ej. "mp4", ".mov", "mkv").

    Returns:
        {
            "verdict": "ok" | "warning" | "unverified" | "blocked",
            "container": <id normalizado>,
            "issues": [
                # container / hardware: mensaje ya armado (ver limitacion de .tr() en el
                # docstring del modulo).
                {"scope": "video"/"audio", "check": "container"/"hardware",
                 "severity": "warning"/"unverified"/"blocked", "message": str},
                # playback_risk: datos estructurados en vez de mensaje, para que la GUI
                # arme el texto traducible (ver _check_playback_risk).
                {"scope": "video"/"audio", "check": "playback_risk", "severity": "warning",
                 "risk": {"level": str, "via": str|None, "requires": str|None, "note": str|None}},
            ]
        }

    Nota: si video_codec/audio_codec es None (stream copiado o ausente), no se evalua ese
    stream — quien llame debe resolver el codec real del archivo fuente (ej. via ffprobe)
    si quiere validar un stream en modo "copiar".
    """
    container_id = normalize_container(container)
    issues = []

    for scope, codec_id in (("video", video_codec), ("audio", audio_codec)):
        if not codec_id:
            continue

        container_check = _check_container_support(codec_id)
        if container_check["level"] == "unverified":
            issues.append({"scope": scope, "check": "container", "severity": "unverified", "message": container_check["message"], "message_args": container_check.get("message_args", [])})
        else:
            codec_entry = container_check["entry"]
            cont_info = codec_entry["containers"].get(container_id)
            if cont_info is None:
                issues.append({"scope": scope, "check": "container", "severity": "unverified",
                                "message": QT_TRANSLATE_NOOP("RecodeMessages", "Contenedor '%1' no evaluado para '%2'."), "message_args": [container_id, codec_id]})
            elif not cont_info["supported"]:
                issues.append({"scope": scope, "check": "container", "severity": "blocked",
                                "message": cont_info.get("ffmpeg_error") or QT_TRANSLATE_NOOP("RecodeMessages", "Este contenedor no acepta este codec en el ffmpeg instalado.")})
            else:
                risk = _check_playback_risk(codec_entry, container_id)
                if risk:
                    issues.append({"scope": scope, "check": "playback_risk", "severity": "warning", "risk": risk})

        if scope == "video":
            hw_check = _check_hardware_support(codec_id)
            if hw_check["level"] in ("blocked", "warning"):
                issues.append({"scope": scope, "check": "hardware", "severity": hw_check["level"], "message": hw_check["reason"]})

    if issues:
        worst = max(issues, key=lambda i: _SEVERITY_ORDER[i["severity"]])
        verdict = worst["severity"]
    else:
        verdict = "ok"

    return {"verdict": verdict, "container": container_id, "issues": issues}


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

    cases = [
        ("h264", "aac", "mp4"),
        ("hevc", "aac", "mxf"),
        ("hevc", "pcm_s24le", "mxf"),
        ("av1", "opus", "mov"),
        ("vp8", "vorbis", "mkv"),
        ("h264", "opus", "qtff"),
        ("h264", None, "ts"),
        ("prores", "pcm_s24le", "mkv"),
    ]
    for v, a, c in cases:
        result = evaluate_recode(v, a, c)
        print(f"\n{v} + {a} -> .{c}  =>  {result['verdict'].upper()}")
        for issue in result["issues"]:
            detail = issue.get("message") or issue.get("risk")
            print(f"  [{issue['severity']}] ({issue['scope']}/{issue['check']}) {detail}")
