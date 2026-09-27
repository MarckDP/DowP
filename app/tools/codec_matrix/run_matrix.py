# tools/codec_matrix/run_matrix.py
"""
Corre la matriz de compatibilidad codec<->contenedor contra un ffmpeg real, con mux de
prueba (no encode completo). Pensado para re-correrse cada vez que se actualiza el
ffmpeg empaquetado de DowP, o antes de una release grande, para detectar regresiones.

Para audio, ademas de "¿el contenedor acepta el codec?" prueba canales (mono/estereo/
5.1) en dos niveles: a nivel de encoder puro ("channels" del codec) y cruzado con cada
contenedor ("channels" dentro de cada entrada de "containers"), para casos donde el
muxer en si restringe canales aunque el encoder los soporte (ej. 3GP/AMR).

Uso:
    python tools/codec_matrix/run_matrix.py
    python tools/codec_matrix/run_matrix.py --ffmpeg "C:\\ruta\\a\\otro\\ffmpeg.exe"

Guarda el resultado crudo en tools/codec_matrix/runs/<version_ffmpeg>.json (y una copia
en runs/latest.json), listo para build_runtime_json.py o diff_runs.py.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from codec_specs import (
    CONTAINERS, VIDEO_CODECS, AUDIO_CODECS, MXF_COMPANION_VIDEO_ENCODER, MXF_REQUIRED_AUDIO_RATE,
    ALPHA_OVERRIDES, ALPHA_DECODERS,
)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_FFMPEG = os.path.join(REPO_ROOT, "bin", "dependences", "ffmpeg", "ffmpeg.exe")
RUNS_DIR = os.path.join(os.path.dirname(__file__), "runs")
TMP_DIR = os.path.join(os.path.dirname(__file__), "_tmp_probe")

TIMEOUT = 10

_BOILERPLATE_PREFIXES = (
    "Error sending frames to consumers", "Task finished with error code",
    "Terminating thread with return code", "Nothing was written into output file",
    "Could not open encoder before EOF", "encoded 0 frames",
)
# Banners informativos/de progreso de encoders (x265, SVT-AV1, aom, etc.) - formatos
# como "x265 [info]: ...", "Svt[info]: ...", "Svt [config]: ...". Nunca son el motivo
# real de un fallo de mux, asi que se descartan sin importar mayusculas/formato exacto.
_INFO_BANNER_RE = re.compile(r"^[A-Za-z0-9_.\-]*\s?\[(info|warning|config|version|build)\]", re.IGNORECASE)


def _first_meaningful_line(stderr_text):
    for line in stderr_text.splitlines():
        line = line.strip()
        if not line:
            continue
        if _INFO_BANNER_RE.match(line):
            continue
        if any(p in line for p in _BOILERPLATE_PREFIXES):
            continue
        return line
    return stderr_text.splitlines()[0].strip() if stderr_text.strip() else None


def _run(cmd):
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
        return res.returncode, (res.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return -1, "timeout"
    except Exception as e:
        return -1, str(e)


def _video_source_cmd(ffmpeg, spec):
    size = spec.get("size", "256x256")
    fps = spec.get("fps", "25")
    cmd = [ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=black:s={size}:r={fps}:d=0.4"]
    if spec.get("pix_fmt"):
        cmd += ["-pix_fmt", spec["pix_fmt"]]
    cmd += ["-frames:v", "5", "-c:v", spec["encoder"]]
    cmd += spec.get("extra", [])
    return cmd


def _audio_source_cmd(ffmpeg, spec, ar_override=None):
    ar = ar_override or spec.get("ar", 44100)
    ac = spec.get("ac", 2)
    cmd = [ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=1000:duration=0.4:sample_rate={ar}", "-ac", str(ac)]
    cmd += ["-c:a", spec["encoder"]]
    cmd += spec.get("extra", [])
    return cmd


def _audio_paired_mxf_cmd(ffmpeg, spec):
    """MXF exige un track de video primero y audio a 48kHz. Se arma un mux con
    companion de video valido para poder juzgar el codec de audio en si."""
    ar = spec.get("ar") or MXF_REQUIRED_AUDIO_RATE
    ac = spec.get("ac", 2)
    cmd = [
        ffmpeg, "-y", "-v", "error",
        "-f", "lavfi", "-i", "color=c=black:s=256x256:r=25:d=0.4",
        "-f", "lavfi", "-i", f"sine=frequency=1000:duration=0.4:sample_rate={ar}",
        "-map", "0:v", "-map", "1:a",
        "-c:v", MXF_COMPANION_VIDEO_ENCODER,
        "-ac", str(ac), "-c:a", spec["encoder"],
    ]
    cmd += spec.get("extra", [])
    return cmd


_CHANNEL_COUNTS = (1, 2, 6)


def _channels_probe_cmd(ffmpeg, spec, cont_id, muxer, out_path, ac):
    """Arma el comando de mux para un (codec, contenedor, canales) puntual. Reusa el
    companion de video de MXF cuando corresponde, igual que el mux "base" del contenedor."""
    spec_copy = dict(spec)
    spec_copy["ac"] = ac
    if cont_id == "mxf":
        base_cmd = _audio_paired_mxf_cmd(ffmpeg, spec_copy)
    else:
        base_cmd = _audio_source_cmd(ffmpeg, spec_copy)
    return base_cmd + ["-f", muxer, out_path]


def _passing_codecs(results, kind, cont_id):
    """Nombres (clave en VIDEO_CODECS/AUDIO_CODECS, no codec_id) de TODOS los codecs de
    este tipo que el matrix YA confirmo (loop principal, arriba en el mismo run) que
    entran en este contenedor con 1 sola pista - la base real sobre la que tiene sentido
    probar multipista (probar 2 streams de un codec que ni siquiera entra con 1 solo
    confundiria "el contenedor rechaza 2 pistas" con "este codec nunca entro aca"). A
    proposito NO se recorta a uno "representativo": el usuario quiere el dato real por
    cada codec, no una muestra adivinada."""
    key = f"{kind}_codecs"
    return [
        name
        for name, entry in results[key].items()
        if entry.get("testable") and entry["containers"].get(cont_id, {}).get("result") == "pass"
    ]


def _multi_audio_only_cmd(ffmpeg, spec, muxer, out_path, ar_override=None):
    """Mux de 2 streams de audio independientes del MISMO codec (sin video) - para saber
    si el CONTENEDOR en si (no el codec) acepta multipista, o si por diseño/estandar solo
    admite un stream elemental (ej. MP3/WAV/FLAC clasicos). Reusa ar/ac/extra del spec
    real del codec (igual que _audio_source_cmd) - sin esto, codecs con requisitos propios
    (DTS necesita '-strict -2', AMR-WB necesita 16kHz) fallarian por un parametro de
    encoder faltante, no por una restriccion real del contenedor."""
    ar = ar_override or spec.get("ar", 44100)
    ac = spec.get("ac", 2)
    cmd = [
        ffmpeg, "-y", "-v", "error",
        "-f", "lavfi", "-i", f"sine=frequency=1000:duration=0.4:sample_rate={ar}",
        "-f", "lavfi", "-i", f"sine=frequency=1500:duration=0.4:sample_rate={ar}",
        "-map", "0:a", "-map", "1:a", "-ac", str(ac), "-c:a", spec["encoder"],
    ]
    cmd += spec.get("extra", [])
    cmd += ["-f", muxer, out_path]
    return cmd


def _multi_audio_with_video_cmd(ffmpeg, video_spec, audio_spec, muxer, out_path, ar_override=None):
    """Mux de 1 video + 2 audio (ej. OBS: microfono + audio del sistema) - eje DISTINTO
    del anterior: un contenedor puede aceptar 2 audios solos pero no junto a video (o
    viceversa), asi que se prueban por separado en vez de asumir que uno implica el otro.
    Reusa size/pix_fmt/fps/extra del spec real de CADA codec (igual que
    _video_source_cmd/_audio_source_cmd), por el mismo motivo que en
    _multi_audio_only_cmd - varios codecs de video del matrix exigen resolucion/pix_fmt
    fijos (H.263 = QCIF, ProRes = yuv422p10le, DV = 720x576@25, etc.)."""
    size = video_spec.get("size", "256x256")
    fps = video_spec.get("fps", "25")
    ar = ar_override or audio_spec.get("ar", 44100)
    ac = audio_spec.get("ac", 2)
    # Los 3 -i van TODOS primero, seguidos de TODAS las opciones de salida (-map, -pix_fmt,
    # -c:v, -c:a...) - a diferencia de _video_source_cmd (que solo tiene 1 input, asi que
    # poner "-pix_fmt" justo despues de su unico -i ya lo deja correctamente del lado de
    # salida), aca intercalar "-pix_fmt" entre el -i de video y los -i de audio hace que
    # ffmpeg lo reinterprete como opcion de ENTRADA del siguiente -i (el primer audio), que
    # no tiene ese AVOption -> "Option pixel_format not found". Agrupar todos los -i antes
    # que cualquier opcion de salida evita la ambiguedad sin depender de este detalle fino.
    cmd = [
        ffmpeg, "-y", "-v", "error",
        "-f", "lavfi", "-i", f"color=c=black:s={size}:r={fps}:d=0.4",
        "-f", "lavfi", "-i", f"sine=frequency=1000:duration=0.4:sample_rate={ar}",
        "-f", "lavfi", "-i", f"sine=frequency=1500:duration=0.4:sample_rate={ar}",
        "-map", "0:v", "-map", "1:a", "-map", "2:a",
    ]
    if video_spec.get("pix_fmt"):
        cmd += ["-pix_fmt", video_spec["pix_fmt"]]
    cmd += ["-frames:v", "5", "-c:v", video_spec["encoder"]]
    cmd += video_spec.get("extra", [])
    cmd += ["-ac", str(ac), "-c:a", audio_spec["encoder"]]
    cmd += audio_spec.get("extra", [])
    cmd += ["-f", muxer, out_path]
    return cmd


def probe_container_streams(ffmpeg, results, cont_id, muxer, ext):
    """Prueba, para UN contenedor, si acepta 2 streams de audio simultaneos - en 2
    escenarios independientes (solo-audio, y video+audio). A diferencia de un primer
    intento con "un codec representativo", esto prueba TODOS los codecs que el matrix ya
    confirmo como validos (1 sola pista) en este contenedor - el usuario quiere el dato
    real por codec, no una muestra: es perfectamente posible que un contenedor acepte 2
    pistas de AAC pero no 2 de AC-3, por ejemplo, y adivinar con uno solo ocultaria eso.

    Returns: {"audio_only_multi": {codec_name: {result,error}, ...},
              "video_audio_multi": {"video+audio": {result,error}, ...}}
    Un contenedor sin NINGUN codec de audio (GIF/WEBP/APNG) devuelve dicts vacios en vez
    de intentar nada - no hay con que probar."""
    result = {"audio_only_multi": {}, "video_audio_multi": {}}
    audio_names = _passing_codecs(results, "audio", cont_id)

    if cont_id == "mxf":
        # MXF no tiene un modo "solo audio" real (el muxer exige un track de video como
        # primero y unico "track" propiamente dicho) - se prueba directo video+audio, con
        # el mismo companion/framerate que ya usa el resto del matrix para audio en MXF
        # (ver _audio_paired_mxf_cmd), cruzado igual con TODOS los codecs de audio validos.
        mxf_video_spec = {"encoder": MXF_COMPANION_VIDEO_ENCODER, "size": "256x256", "fps": "25"}
        for a_name in audio_names:
            a_spec = AUDIO_CODECS[a_name]
            out_path = os.path.join(TMP_DIR, f"multi_{cont_id}_mxf_{a_name}.{ext}")
            cmd = _multi_audio_with_video_cmd(
                ffmpeg, mxf_video_spec, a_spec, muxer, out_path, ar_override=MXF_REQUIRED_AUDIO_RATE,
            )
            rc, err = _run(cmd)
            ok = (rc == 0) and os.path.exists(out_path) and os.path.getsize(out_path) > 0
            result["video_audio_multi"][f"{MXF_COMPANION_VIDEO_ENCODER}+{a_name}"] = {
                "result": "pass" if ok else "fail",
                "error": None if ok else (_first_meaningful_line(err) or f"exit code {rc}"),
            }
            if os.path.exists(out_path):
                try:
                    os.remove(out_path)
                except OSError:
                    pass
        return result

    for a_name in audio_names:
        a_spec = AUDIO_CODECS[a_name]
        out_path = os.path.join(TMP_DIR, f"multi_{cont_id}_audioonly_{a_name}.{ext}")
        cmd = _multi_audio_only_cmd(ffmpeg, a_spec, muxer, out_path)
        rc, err = _run(cmd)
        ok = (rc == 0) and os.path.exists(out_path) and os.path.getsize(out_path) > 0
        result["audio_only_multi"][a_name] = {
            "result": "pass" if ok else "fail",
            "error": None if ok else (_first_meaningful_line(err) or f"exit code {rc}"),
        }
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except OSError:
                pass

    video_names = _passing_codecs(results, "video", cont_id)
    for v_name in video_names:
        v_spec = VIDEO_CODECS[v_name]
        for a_name in audio_names:
            a_spec = AUDIO_CODECS[a_name]
            out_path = os.path.join(TMP_DIR, f"multi_{cont_id}_va_{v_name}_{a_name}.{ext}")
            cmd = _multi_audio_with_video_cmd(ffmpeg, v_spec, a_spec, muxer, out_path)
            rc, err = _run(cmd)
            ok = (rc == 0) and os.path.exists(out_path) and os.path.getsize(out_path) > 0
            result["video_audio_multi"][f"{v_name}+{a_name}"] = {
                "result": "pass" if ok else "fail",
                "error": None if ok else (_first_meaningful_line(err) or f"exit code {rc}"),
            }
            if os.path.exists(out_path):
                try:
                    os.remove(out_path)
                except OSError:
                    pass

    return result


def _probe_dimension_alignment(ffmpeg, spec):
    """Prueba si el encoder de un codec de VIDEO acepta ancho impar y alto impar por
    separado (perturbando en -1 el 'size' que ya tiene el spec), directo a '-f null -' sin
    contenedor de por medio — mismo estilo liviano que las pruebas de canales de audio a
    nivel de encoder. Para codecs de tamano fijo obligatorio (QCIF, DV PAL, DNxHD 1080p) el
    encoder va a rechazar el tamano alterado igual (por motivo distinto a paridad), y el
    resultado por defecto queda 'par requerido' - lado seguro, y no importa en la practica
    porque esos codecs no se usan con resolucion Personalizada de todos modos."""
    w, h = (int(x) for x in spec.get("size", "256x256").split("x"))
    odd_w = w if w % 2 == 1 else w - 1
    odd_h = h if h % 2 == 1 else h - 1

    def _accepts(size_str):
        spec_copy = dict(spec)
        spec_copy["size"] = size_str
        cmd = _video_source_cmd(ffmpeg, spec_copy) + ["-f", "null", "-"]
        rc, _ = _run(cmd)
        return rc == 0

    return {
        "width_even_required": not _accepts(f"{odd_w}x{h}"),
        "height_even_required": not _accepts(f"{w}x{odd_h}"),
    }


# ─── Transparencia (canal alfa) ───────────────────────────────────────────────
# Clasificacion del alfa leido en las 3 franjas (0 / 128 / 255):
#   "full"       alfa completo (la franja semitransparente sigue semitransparente)
#   "1bit"       solo transparente u opaco (GIF): la semitransparente pasa a 0 o 255
#   "lost"       todo opaco: el alfa se descarto
#   "partial"    otro patron (se guarda el alfa leido para revisarlo a mano)
#   "write_error" el encoder/muxer no pudo escribir el archivo con alfa
#   "unreadable" se escribio, pero ffmpeg no puede volver a leerlo
_ALPHA_STRIPES = (0, 128, 255)


def _alpha_source(spec):
    size = spec.get("size", "256x256")
    fps = spec.get("fps", "25")
    geq = "geq=r='255':g='0':b='0':a='if(lt(X,W/3),0,if(lt(X,2*W/3),128,255))'"
    return ["-f", "lavfi", "-i", f"color=c=red:s={size}:r={fps}:d=1,format=rgba,{geq}"]


def _alpha_encode_cmd(ffmpeg, spec, override, pix_fmt, muxer, out_path):
    cmd = [ffmpeg, "-y", "-v", "error", *_alpha_source(spec)]
    if pix_fmt:
        cmd += ["-pix_fmt", pix_fmt]
    # 12 fotogramas, no 3: con muy pocos, MPEG-TS/PS no llegan a exponer los parametros
    # del codec al releer (H.264 en TS con 3 fotogramas da "could not find codec
    # parameters", con 12 se lee bien) y el resultado seria un falso "unreadable".
    cmd += ["-frames:v", "12", "-c:v", spec["encoder"]]
    extra = override.get("extra") if override else spec.get("extra", [])
    cmd += list(extra or [])
    cmd += ["-f", muxer, out_path]
    return cmd


def _read_alpha(ffmpeg, path, size, decoder=None):
    """Alfa real del primer fotograma en el centro de cada franja, o None si no se puede
    decodificar."""
    w, h = (int(x) for x in size.split("x"))
    cmd = [ffmpeg, "-v", "error"]
    if decoder:
        cmd += ["-c:v", decoder]
    cmd += ["-i", path, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgba", "-"]
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT)
    except Exception:
        return None
    data = res.stdout
    if len(data) < w * h * 4:
        return None
    y = h // 2
    return [data[(y * w + x) * 4 + 3] for x in (w // 6, w // 2, (5 * w) // 6)]


def _opaque_readable(ffmpeg, spec, muxer, out_path, size):
    cmd = [ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i",
           f"testsrc=s={size}:r={spec.get('fps', '25')}:d=1"]
    if spec.get("pix_fmt"):
        cmd += ["-pix_fmt", spec["pix_fmt"]]
    cmd += ["-frames:v", "12", "-c:v", spec["encoder"], *spec.get("extra", []), "-f", muxer, out_path]
    rc, _ = _run(cmd)
    if rc != 0 or not os.path.exists(out_path):
        return False
    return _read_alpha(ffmpeg, out_path, size) is not None


def _classify_alpha(values):
    if values is None:
        return "unreadable"
    t, m, o = values
    if t <= 10 and o >= 245 and 90 <= m <= 166:
        return "full"
    if t <= 10 and o >= 245 and (m <= 10 or m >= 245):
        return "1bit"
    if min(values) >= 245:
        return "lost"
    return "partial"


def probe_alpha(ffmpeg, name, spec, base_containers):
    """¿Este codec conserva transparencia, y en que contenedores? Solo se prueban los
    contenedores donde el mux base ya paso (si el codec no entra, no hay alfa que medir).
    Devuelve lo que se uso para codificar (pix_fmt/extra/decoder) junto al resultado, para
    que la app pueda repetir exactamente lo que se verifico."""
    override = ALPHA_OVERRIDES.get(name)
    decoder = ALPHA_DECODERS.get(name)
    size = spec.get("size", "256x256")
    if override is not None:
        pix_candidates = [override.get("pix_fmt")]
    else:
        # Sin -pix_fmt primero (ffmpeg negocia desde RGBA, con alfa si el encoder tiene),
        # y el del spec base como respaldo si eso no codifica.
        pix_candidates = [None] + ([spec["pix_fmt"]] if spec.get("pix_fmt") else [])
        # Ultimo intento SIN alfa: si pedir alfa hace fallar al encoder (x265 de este build:
        # "does not support alpha layer encoding") pero codifica normal, el resultado real
        # para la app es "lost" (se codifica, sin transparencia), no "write_error".
        if "yuv420p" not in pix_candidates:
            pix_candidates.append("yuv420p")

    containers = {}
    used_pix_fmt = pix_candidates[0]
    for cont_id, c in base_containers.items():
        if c.get("result") != "pass":
            continue
        muxer, ext = CONTAINERS[cont_id][0]
        out_path = os.path.join(TMP_DIR, f"alpha_{name}_{cont_id}.{ext}".replace(" ", "_"))
        entry = None
        first_error = None
        for pix_fmt in pix_candidates:
            rc, err = _run(_alpha_encode_cmd(ffmpeg, spec, override, pix_fmt, muxer, out_path))
            ok = rc == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0
            if not ok:
                first_error = first_error or (_first_meaningful_line(err) or f"exit code {rc}")
                entry = {"result": "write_error", "error": first_error}
                continue
            values = _read_alpha(ffmpeg, out_path, size, decoder)
            result = _classify_alpha(values)
            entry = {"result": result, "error": None, "pix_fmt": pix_fmt}
            if result == "unreadable":
                # ¿Ilegible por el alfa, o el contenedor directamente no sabe releer este
                # codec? Se repite SIN alfa: si tampoco se lee, la combinacion no sirve
                # para nada (el mux base la marca "pass" porque solo mira que se escriba).
                entry["opaque_readable"] = _opaque_readable(ffmpeg, spec, muxer, out_path, size)
            if first_error:
                # Por que no hubo alfa aunque el codec codifique (ej. x265 sin capa alfa).
                entry["alpha_error"] = first_error
            if result in ("partial", "unreadable"):
                entry["alpha_read"] = values
            used_pix_fmt = pix_fmt
            break
        containers[cont_id] = entry
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except OSError:
                pass

    return {
        "pix_fmt": used_pix_fmt,
        "extra": list((override or {}).get("extra") or []) if override else list(spec.get("extra", [])),
        "decoder": decoder,
        "containers": containers,
    }


def probe_video_codec_multi_audio(ffmpeg, results, v_name, container_streams):
    """Multipista "1 video + 2 audios" SOLO para un codec de video (ver
    probe_container_streams, que lo hace para todos): la usa --codecs para sumar un codec
    nuevo sin rehacer el matrix completo. Mezcla los resultados en container_streams."""
    v_spec = VIDEO_CODECS[v_name]
    for cont_id, c in results["video_codecs"][v_name]["containers"].items():
        if c.get("result") != "pass" or cont_id == "mxf":
            continue
        muxer, ext = CONTAINERS[cont_id][0]
        entry = container_streams.setdefault(cont_id, {"audio_only_multi": {}, "video_audio_multi": {}})
        for a_name in _passing_codecs(results, "audio", cont_id):
            out_path = os.path.join(TMP_DIR, f"multi_{cont_id}_va_{v_name}_{a_name}.{ext}")
            rc, err = _run(_multi_audio_with_video_cmd(ffmpeg, v_spec, AUDIO_CODECS[a_name], muxer, out_path))
            ok = (rc == 0) and os.path.exists(out_path) and os.path.getsize(out_path) > 0
            entry["video_audio_multi"][f"{v_name}+{a_name}"] = {
                "result": "pass" if ok else "fail",
                "error": None if ok else (_first_meaningful_line(err) or f"exit code {rc}"),
            }
            if os.path.exists(out_path):
                try:
                    os.remove(out_path)
                except OSError:
                    pass


def run_alpha_axis(ffmpeg, results):
    """Agrega results["video_codecs"][name]["alpha"] a una corrida ya hecha."""
    names = [n for n, e in results["video_codecs"].items() if e.get("testable")]
    t0 = time.time()
    for i, name in enumerate(names, 1):
        print(f"  [{i}/{len(names)}] alfa: {name}", file=sys.stderr)
        entry = results["video_codecs"][name]
        entry["alpha"] = probe_alpha(ffmpeg, name, VIDEO_CODECS[name], entry["containers"])
    return round(time.time() - t0, 1)


def probe(ffmpeg, kind, name, spec):
    if not spec.get("encoder"):
        return {"testable": False, "skip_reason": spec.get("skip_reason", "Sin encoder disponible."), "containers": {}}

    # Canales a nivel de ENCODER (sin contenedor de por medio, "-f null -"). Es el limite
    # mas basico: si el encoder no puede producir N canales, ningun contenedor va a poder
    # tampoco, asi que este resultado se usa para saltear pruebas de mux redundantes abajo.
    channels_out = {}
    if kind == "audio":
        for ac in _CHANNEL_COUNTS:
            spec_copy = dict(spec)
            spec_copy["ac"] = ac
            cmd = _audio_source_cmd(ffmpeg, spec_copy) + ["-f", "null", "-"]
            rc, err = _run(cmd)
            ok = (rc == 0)
            channels_out[str(ac)] = {
                "result": "pass" if ok else "fail",
                "error": None if ok else (_first_meaningful_line(err) or f"exit code {rc}"),
            }

    containers_out = {}
    for cont_id, muxer_list in CONTAINERS.items():
        muxer, ext = muxer_list[0]
        out_path = os.path.join(TMP_DIR, f"{kind}_{name}_{cont_id}.{ext}".replace(" ", "_").replace("/", "_"))

        if kind == "audio" and cont_id == "mxf":
            base_cmd = _audio_paired_mxf_cmd(ffmpeg, spec)
        elif kind == "video":
            base_cmd = _video_source_cmd(ffmpeg, spec)
        else:
            base_cmd = _audio_source_cmd(ffmpeg, spec)

        cmd = base_cmd + ["-f", muxer, out_path]
        rc, err = _run(cmd)
        ok = (rc == 0) and os.path.exists(out_path) and os.path.getsize(out_path) > 0
        containers_out[cont_id] = {
            "result": "pass" if ok else "fail",
            "error": None if ok else (_first_meaningful_line(err) or f"exit code {rc}"),
        }
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except OSError:
                pass

        # Canales por CONTENEDOR: solo tiene sentido probarlo si el mux base ya paso (si el
        # contenedor ni siquiera acepta el codec, ningun conteo de canales lo va a arreglar)
        # y si el encoder ya demostro poder producir ese numero de canales arriba. Esto evita
        # cientos de pruebas de mux inutiles en combinaciones ya descartadas.
        if kind == "audio" and ok:
            per_container_channels = {}
            for ac in _CHANNEL_COUNTS:
                if channels_out.get(str(ac), {}).get("result") != "pass":
                    per_container_channels[str(ac)] = {
                        "result": "fail",
                        "error": "No soportado por el encoder en si (ver 'channels' a nivel de codec).",
                    }
                    continue
                ch_out_path = os.path.join(
                    TMP_DIR, f"{kind}_{name}_{cont_id}_ch{ac}.{ext}".replace(" ", "_").replace("/", "_")
                )
                ch_cmd = _channels_probe_cmd(ffmpeg, spec, cont_id, muxer, ch_out_path, ac)
                ch_rc, ch_err = _run(ch_cmd)
                ch_ok = (ch_rc == 0) and os.path.exists(ch_out_path) and os.path.getsize(ch_out_path) > 0
                per_container_channels[str(ac)] = {
                    "result": "pass" if ch_ok else "fail",
                    "error": None if ch_ok else (_first_meaningful_line(ch_err) or f"exit code {ch_rc}"),
                }
                if os.path.exists(ch_out_path):
                    try:
                        os.remove(ch_out_path)
                    except OSError:
                        pass
            containers_out[cont_id]["channels"] = per_container_channels

    result = {"testable": True, "skip_reason": None, "containers": containers_out, "channels": channels_out}
    if kind == "video":
        result["dimension_alignment"] = _probe_dimension_alignment(ffmpeg, spec)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", default=DEFAULT_FFMPEG, help="Ruta al ejecutable de ffmpeg a verificar.")
    parser.add_argument("--out-dir", default=RUNS_DIR, help="Carpeta donde guardar el resultado.")
    parser.add_argument("--codecs", metavar="NOMBRES",
                        help="Solo estos codecs de video (separados por coma, claves de VIDEO_CODECS), "
                             "sumados a runs/latest.json: contenedores, medidas, alfa y multipista. Para "
                             "agregar un codec nuevo sin rehacer el matrix completo.")
    parser.add_argument("--only-alpha", metavar="RUN_JSON", nargs="?", const=os.path.join(RUNS_DIR, "latest.json"),
                        help="Solo el eje de transparencia, sumado a una corrida existente (por defecto "
                             "runs/latest.json) -- sin repetir el matrix completo.")
    args = parser.parse_args()

    if not os.path.exists(args.ffmpeg):
        print(f"No se encontro ffmpeg en: {args.ffmpeg}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(TMP_DIR, exist_ok=True)
    os.makedirs(args.out_dir, exist_ok=True)

    if args.codecs:
        run_path = os.path.join(args.out_dir, "latest.json")
        with open(run_path, "r", encoding="utf-8") as f:
            run = json.load(f)
        names = [n.strip() for n in args.codecs.split(",") if n.strip()]
        unknown = [n for n in names if n not in VIDEO_CODECS]
        if unknown:
            print(f"No estan en VIDEO_CODECS: {', '.join(unknown)}", file=sys.stderr)
            sys.exit(1)
        container_streams = run.setdefault("container_streams", {})
        for i, name in enumerate(names, 1):
            spec = VIDEO_CODECS[name]
            print(f"[{i}/{len(names)}] video: {name}", file=sys.stderr)
            r = probe(args.ffmpeg, "video", name, spec)
            r["codec_id"] = spec.get("codec_id", name)
            r["wiki"] = spec.get("wiki")
            r["encoder"] = spec.get("encoder")
            r["display_name"] = spec.get("display_name") or spec.get("wiki") or spec.get("codec_id", name)
            if spec.get("note"):
                r["note"] = spec["note"]
            run["results"]["video_codecs"][name] = r
            if r.get("testable"):
                r["alpha"] = probe_alpha(args.ffmpeg, name, spec, r["containers"])
                probe_video_codec_multi_audio(args.ffmpeg, run["results"], name, container_streams)
        run["meta"]["codecs_updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", run["meta"].get("ffmpeg_version", "unknown"))
        for p in (run_path, os.path.join(args.out_dir, f"{safe}.json")):
            with open(p, "w", encoding="utf-8") as f:
                json.dump(run, f, indent=2, ensure_ascii=False)
            print(f"Escrito: {p}", file=sys.stderr)
        return

    if args.only_alpha:
        with open(args.only_alpha, "r", encoding="utf-8") as f:
            run = json.load(f)
        this_version = subprocess.run([args.ffmpeg, "-version"], capture_output=True, text=True).stdout.splitlines()[0]
        if run["meta"].get("ffmpeg_version_full") != this_version:
            print("Aviso: la corrida es de otro ffmpeg; el eje de alfa se mide con el ffmpeg indicado.",
                  file=sys.stderr)
        print("Probando transparencia (canal alfa) por codec y contenedor...", file=sys.stderr)
        run["meta"]["alpha_elapsed_sec"] = run_alpha_axis(args.ffmpeg, run["results"])
        run["meta"]["alpha_generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        targets = [args.only_alpha]
        # Igual que la corrida completa: latest.json y la copia con nombre de version van juntas.
        if os.path.basename(args.only_alpha) == "latest.json":
            safe = re.sub(r"[^A-Za-z0-9._-]", "_", run["meta"].get("ffmpeg_version", "unknown"))
            targets.append(os.path.join(os.path.dirname(args.only_alpha), f"{safe}.json"))
        for p in targets:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(run, f, indent=2, ensure_ascii=False)
            print(f"Escrito: {p}", file=sys.stderr)
        return

    version_line = subprocess.run([args.ffmpeg, "-version"], capture_output=True, text=True).stdout.splitlines()[0]
    version_match = re.search(r"ffmpeg version (\S+)", version_line)
    version_str = version_match.group(1) if version_match else "unknown"

    results = {"video_codecs": {}, "audio_codecs": {}}
    all_specs = [("video", VIDEO_CODECS), ("audio", AUDIO_CODECS)]
    total = sum(len(specs) for _, specs in all_specs)
    done = 0
    t0 = time.time()

    for kind, specs in all_specs:
        key = f"{kind}_codecs"
        for name, spec in specs.items():
            done += 1
            print(f"[{done}/{total}] {kind}: {name}", file=sys.stderr)
            r = probe(args.ffmpeg, kind, name, spec)
            r["codec_id"] = spec.get("codec_id", name)
            r["wiki"] = spec.get("wiki")
            r["encoder"] = spec.get("encoder")
            r["display_name"] = spec.get("display_name") or spec.get("wiki") or spec.get("codec_id", name)
            if spec.get("note"):
                r["note"] = spec["note"]
            results[key][name] = r

    elapsed_codecs = round(time.time() - t0, 1)
    print(f"Matrix codec x contenedor lista en {elapsed_codecs}s", file=sys.stderr)

    # Multipista (audio solo, y video+audio): eje aparte del matrix codec x contenedor de
    # arriba, corrido DESPUES porque necesita sus resultados ya completos (ver
    # _passing_codecs: solo tiene sentido probar 2 streams de un codec que ya paso con 1).
    print("Probando multipista (audio solo + video/audio) por contenedor...", file=sys.stderr)
    t1 = time.time()
    container_streams = {}
    cont_items = list(CONTAINERS.items())
    for i, (cont_id, muxer_list) in enumerate(cont_items, 1):
        muxer, ext = muxer_list[0]
        print(f"  [{i}/{len(cont_items)}] {cont_id}", file=sys.stderr)
        container_streams[cont_id] = probe_container_streams(args.ffmpeg, results, cont_id, muxer, ext)
    elapsed_streams = round(time.time() - t1, 1)
    print(f"Multipista lista en {elapsed_streams}s", file=sys.stderr)

    # Transparencia: eje aparte, tambien DESPUES del loop principal (solo se prueba el
    # alfa en los contenedores donde el mux base ya paso).
    print("Probando transparencia (canal alfa) por codec y contenedor...", file=sys.stderr)
    elapsed_alpha = run_alpha_axis(args.ffmpeg, results)
    print(f"Transparencia lista en {elapsed_alpha}s", file=sys.stderr)

    elapsed = round(time.time() - t0, 1)
    print(f"Listo en {elapsed}s", file=sys.stderr)

    output = {
        "meta": {
            "ffmpeg_version": version_str,
            "ffmpeg_version_full": version_line,
            "ffmpeg_path": args.ffmpeg,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "method": "mux real contra ffmpeg instalado, con encoders de software (agnostico a marca de GPU)",
            "elapsed_sec": elapsed,
        },
        "results": results,
        "container_streams": container_streams,
    }

    safe_version = re.sub(r"[^A-Za-z0-9._-]", "_", version_str)
    versioned_path = os.path.join(args.out_dir, f"{safe_version}.json")
    latest_path = os.path.join(args.out_dir, "latest.json")
    for p in (versioned_path, latest_path):
        with open(p, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"Escrito: {versioned_path}", file=sys.stderr)
    print(f"Escrito: {latest_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
