"""Transcripción local por subprocesos. Mismo contrato con la cola que los motores de IA de video.

FFmpeg extrae el audio en PCM mono; whisper-cli escribe su JSON completo (cada segmento y
cada fragmento de palabra con su tiempo) y DowP genera con él el formato elegido (ver
transcript_formats.py). Solo un trabajo terminado con éxito reemplaza el destino. Con
recorte, las marcas de tiempo son relativas al tramo.

Los subtítulos también pueden ir dentro del video (transcription_embed):
- "track": como pista de subtítulos, sin recodificar (salvo con recorte, ver _embed_command).
- "burn": quemados en la imagen con libass, con el estilo elegido; siempre recodifica.
"""
import os
import re
import subprocess
import tempfile
import threading
import time
from collections import deque
from pathlib import Path

from core.logger.logger_manager import logger
from core.setup.ffmpeg_setup import get_ffmpeg_path, get_ffprobe_path
from core.setup.whisper_setup import (runtime_path, model_path, model_ready, runtime_environment, vad_path,
                                      vad_local_version, select_binary, accel_runtime_path, accel_variant)
from core.tabs.video_tools import transcript_formats
from core.whisper_catalog import WHISPER_MODELS, WHISPER_LANGUAGES, VAD_MODEL, VAD_PRESETS, dtw_preset

# El vocabulario va como texto inicial (--prompt); whisper.cpp usa como mucho la mitad de su
# contexto, así que un texto muy largo no ayuda más.
_MAX_PROMPT_CHARS = 600

# Contenedores que aceptan una pista de subtítulos de texto, y en qué códec. Cualquier otro
# video (AVI, FLV, TS…) sale en MKV, que acepta todo.
_TRACK_CODECS = {"mkv": "srt", "mp4": "mov_text", "m4v": "mov_text", "mov": "mov_text", "webm": "webvtt"}
# Idioma de la pista: MP4 y MKV usan códigos ISO 639-2 (tres letras); whisper da dos.
_ISO639_2 = {"es": "spa", "en": "eng", "pt": "por", "fr": "fra", "de": "deu", "it": "ita", "ja": "jpn",
             "ko": "kor", "zh": "zho", "ru": "rus", "ar": "ara", "hi": "hin", "nl": "nld", "pl": "pol",
             "tr": "tur", "uk": "ukr", "sv": "swe", "ca": "cat", "gl": "glg", "eu": "eus", "id": "ind",
             "vi": "vie", "th": "tha", "he": "heb", "el": "ell", "cs": "ces", "ro": "ron", "hu": "hun",
             "fi": "fin", "da": "dan", "no": "nor"}


def embed_mode(settings) -> str:
    """"none", "track" o "burn". Solo en modo Subtítulos."""
    mode = (settings or {}).get("transcription_embed", "none")
    fmt = (settings or {}).get("container", "srt")
    return mode if mode in ("track", "burn") and transcript_formats.output_mode(fmt) == "subtitles" else "none"


def embed_extension(source_ext: str, mode: str) -> str:
    """Extensión del video de salida al incrustar. Quemados: siempre MP4 (H.264 + AAC, lo
    que reproduce todo). Como pista: el mismo contenedor si admite subtítulos, si no MKV."""
    if mode == "burn":
        return "mp4"
    ext = source_ext.lower().lstrip(".")
    return ext if ext in _TRACK_CODECS else "mkv"


def language_output_path(output_file, settings, language) -> str:
    """Nombre al estilo de yt-dlp: "video.es.srt", con el idioma que usó Whisper (el
    detectado, el elegido o "en" al traducir), así los reproductores lo cargan solos y no
    choca con un subtítulo del sitio en otro idioma. Si ya existe, se renombra salvo que
    se pida sobrescribir (transcription_overwrite)."""
    from core.utils.file_conflict_manager import find_available_rename
    if settings.get("transcription_task") == "translate":
        language = "en"
    language = language or settings.get("transcription_language")
    path = Path(output_file)
    if language and re.fullmatch(r"[a-z]{2,3}", str(language)):
        path = path.with_name(f"{path.stem}.{language}{path.suffix}")
    if path.exists() and not settings.get("transcription_overwrite"):
        path = Path(find_available_rename(str(path)))
    return str(path)


def _effective_format(settings) -> str:
    """El formato del archivo que se genera: al quemar siempre es ASS (lleva el estilo)."""
    return "ass" if embed_mode(settings) == "burn" else settings.get("container", "srt")


def whisper_command(binary, model, audio, output_base, settings, cpu=False):
    info = WHISPER_MODELS.get(settings.get("transcription_model"))
    if not info:
        raise ValueError("Modelo de transcripción desconocido.")
    language = settings.get("transcription_language", "auto")
    task = settings.get("transcription_task", "transcribe")
    fmt = settings.get("container", "srt")
    if fmt not in transcript_formats.ALL_FORMATS:
        raise ValueError("Formato de transcripción no válido.")
    if language != "auto" and language not in WHISPER_LANGUAGES:
        raise ValueError("Idioma de transcripción no válido.")
    if info["english_only"]:
        if language not in ("auto", "en"):
            raise ValueError("El modelo elegido solo reconoce inglés.")
        language = "en"
    if task not in ("transcribe", "translate") or (task == "translate" and not info["translate"]):
        raise ValueError("El modelo elegido no permite esta tarea de traducción.")
    threads = max(1, min(64, int(settings.get("transcription_threads", min(8, os.cpu_count() or 4)))))
    # Siempre el JSON completo: el formato final lo escribe DowP (transcript_formats.py).
    cmd = [binary, "-m", model, "-f", audio, "-l", language, "-t", str(threads),
           "-pp", "-ojf", "-of", output_base]
    if task == "translate":
        cmd.append("-tr")
    if cpu or settings.get("transcription_device") == "cpu":
        cmd.append("-ng")
    prompt = " ".join(str(settings.get("transcription_prompt") or "").split())[:_MAX_PROMPT_CHARS]
    if prompt:
        cmd += ["--prompt", prompt]
    if settings.get("transcription_vad"):
        vad = vad_path()
        if not vad:
            raise ValueError("Falta el modelo de detección de voz para saltar silencios.")
        cmd += ["--vad", "-vm", vad] + vad_arguments(settings)
    # Palabra por palabra: tiempos precisos por palabra con DTW. Solo ahí, porque exige
    # desactivar la flash attention (comprobado: con ella t_dtw sale -1), que es más lenta.
    # El karaoke también los necesita.
    split = transcript_formats.split_mode(_effective_format(settings), settings.get("transcription_split", "sentences"))
    if transcript_formats.output_mode(fmt) == "subtitles" and split in ("words", "karaoke") and dtw_preset(info):
        cmd += ["-dtw", dtw_preset(info), "-nfa"]
    return cmd


def vad_arguments(settings):
    """Opciones de sensibilidad del VAD: las de un preajuste o, en "custom", las del
    usuario (acotadas a rangos válidos)."""
    preset = settings.get("transcription_vad_preset", "normal")
    values = dict(VAD_PRESETS.get(preset, VAD_PRESETS["normal"]))
    if preset == "custom":
        for key in values:
            value = settings.get("transcription_vad_" + key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values[key] = value
    threshold = min(0.95, max(0.05, float(values["threshold"])))
    args = ["-vt", f"{threshold:.2f}",
            "-vspd", str(max(0, int(values["min_speech_ms"]))),
            "-vsd", str(max(0, int(values["min_silence_ms"]))),
            "-vp", str(max(0, int(values["pad_ms"])))]
    if float(values["max_speech_s"]) > 0:
        args += ["-vmsd", f"{float(values['max_speech_s']):g}"]
    return args


def _whisper_progress(line):
    match = re.search(r"progress\s*=\s*(\d+)%", line)
    return int(match.group(1)) if match else None


def _ffmpeg_progress(total_seconds):
    """Lee el avance de "ffmpeg -progress pipe:1" (out_time_us, en microsegundos)."""
    def parse(line):
        match = re.match(r"out_time_(?:us|ms)=(\d+)", line)
        if match and total_seconds > 0:
            return min(100, int(int(match.group(1)) / 1_000_000 / total_seconds * 100))
        return None
    return parse


def _probe_count(input_file, kind):
    """Cuántas pistas de un tipo tiene el archivo (los adjuntos pueden no tener códec)."""
    ffprobe = get_ffprobe_path()
    if not ffprobe or not os.path.isfile(ffprobe):
        return 0
    result = subprocess.run([ffprobe, "-v", "error", "-select_streams", kind, "-show_entries",
                             "stream=index", "-of", "csv=p=0", input_file],
                            capture_output=True, timeout=60,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    return sum(1 for line in result.stdout.decode("utf-8", "replace").splitlines() if line.strip())


# Tipos MIME de fuentes que reconocen libass, mpv y VLC en los adjuntos de MKV.
_FONT_MIMETYPES = {".ttf": "application/x-truetype-font", ".otf": "application/vnd.ms-opentype",
                   ".ttc": "application/x-truetype-font"}


def _probe_codecs(input_file, kind):
    """Códecs de las pistas de un tipo ("v", "s") del archivo, en orden."""
    ffprobe = get_ffprobe_path()
    if not ffprobe or not os.path.isfile(ffprobe):
        return []
    result = subprocess.run([ffprobe, "-v", "error", "-select_streams", kind, "-show_entries",
                             "stream=codec_name", "-of", "csv=p=0", input_file],
                            capture_output=True, timeout=60,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    return [line.strip() for line in result.stdout.decode("utf-8", "replace").splitlines() if line.strip()]


def _font_folder(settings, folder):
    """Copia la fuente elegida, si es una de las de DowP, para que libass la encuentre al
    quemar (no están instaladas en el sistema); las del sistema las busca solo. La ruta la
    resuelve el panel en el hilo de la interfaz (font_manager usa QFontDatabase, que no se
    puede tocar desde este hilo)."""
    os.makedirs(folder, exist_ok=True)
    source = settings.get("transcription_style_font_file")
    if source and os.path.isfile(source):
        import shutil
        shutil.copy2(source, os.path.join(folder, os.path.basename(source)))


def _embed_command(ffmpeg, input_file, subtitle_file, output_file, mode, settings, language,
                   trim_in=None, length=None):
    """Comando de FFmpeg para incrustar. Las rutas de los subtítulos son relativas a la
    carpeta temporal (cwd): así el filtro de libass no tiene que escapar rutas de Windows.

    Como pista sin recorte, todo se copia tal cual. Con recorte se recodifica: cortar sin
    recodificar empieza en el fotograma clave anterior y los subtítulos quedarían corridos."""
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-progress", "pipe:1", "-nostats"]
    if trim_in is not None:
        cmd += ["-ss", str(max(0, float(trim_in)))]
    cmd += ["-i", input_file]
    if length is not None:
        cmd += ["-t", str(length)]
    ext = Path(output_file).suffix.lower().lstrip(".")
    webm = ext == "webm"
    reencode_video = (["-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0", "-row-mt", "1"] if webm else
                      ["-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p"])
    reencode_audio = ["-c:a", "libopus", "-b:a", "160k"] if webm else ["-c:a", "aac", "-b:a", "192k"]
    if mode == "burn":
        style = transcript_formats.style_from(settings)
        filter_arg = f"ass={subtitle_file}:fontsdir=fonts"
        cmd += ["-vf", filter_arg, "-map", "0:v:0", "-map", "0:a?"] + reencode_video + reencode_audio
        cmd += ["-movflags", "+faststart", output_file]
        return cmd, style
    cmd += ["-i", subtitle_file, "-map", "0:v?", "-map", "0:a?"]
    # Se conservan las pistas de subtítulos que ya tenía, si el contenedor las admite tal cual.
    kept = 0
    if trim_in is None and length is None:
        codec = _TRACK_CODECS.get(ext, "srt")
        for index, existing in enumerate(_probe_codecs(input_file, "s")):
            if ext == "mkv" or existing == codec:
                cmd += ["-map", f"0:s:{index}"]
                kept += 1
        if ext == "mkv":
            cmd += ["-map", "0:t?"]
        cmd += ["-c", "copy"]
    else:
        cmd += reencode_video + reencode_audio
    new_codec = "ass" if ext == "mkv" and Path(subtitle_file).suffix == ".ass" else _TRACK_CODECS.get(ext, "srt")
    cmd += ["-map", "1:0", f"-c:s:{kept}", new_codec, f"-metadata:s:s:{kept}", "title=Whisper"]
    if language in _ISO639_2:
        cmd += [f"-metadata:s:s:{kept}", f"language={_ISO639_2[language]}"]
    # Pista ASS en MKV: la fuente va adjunta, así los reproductores la usan aunque no esté
    # instalada (como en los MKV de anime). Los adjuntos que ya tenía se copian antes.
    font = settings.get("transcription_style_font_file")
    mimetype = _FONT_MIMETYPES.get(Path(font or "").suffix.lower())
    if new_codec == "ass" and font and mimetype and os.path.isfile(font):
        attached = _probe_count(input_file, "t") if trim_in is None and length is None else 0
        # Sin "filename", FFmpeg guarda la ruta completa del equipo dentro del video.
        cmd += ["-attach", font, f"-metadata:s:t:{attached}", f"mimetype={mimetype}",
                f"-metadata:s:t:{attached}", f"filename={Path(font).name}"]
    if ext in ("mp4", "m4v", "mov"):
        cmd += ["-movflags", "+faststart"]
    cmd.append(output_file)
    return cmd, None


_GPU_NAME = re.compile(r"ggml_vulkan: \d+ = (.+?) \(|^\s*Device \d+: (.+?), compute capability")
_GPU_BACKEND = re.compile(r"whisper_backend_init_gpu: (?:using (\S+) backend|(no GPU found))")


def _device_used(lines):
    """Con qué calculó whisper.cpp, sacado de su propia salida: "GPU Vulkan0 (AMD Radeon
    RX 6600)" o "CPU". Con el binario Vulkan sin un driver que exponga la GPU, whisper.cpp
    calcula con la CPU sin dar error: solo esta línea lo deja ver en el log de un tester."""
    names = [m.group(1) or m.group(2) for m in map(_GPU_NAME.search, lines) if m]
    for line in lines:
        m = _GPU_BACKEND.search(line)
        if m and m.group(1):
            return f"GPU {m.group(1)}" + (f" ({', '.join(names)})" if names else "")
        if m:
            break
    return "CPU" + (f" (GPU visible sin usar: {', '.join(names)})" if names else "")


def _run(cmd, cancellation_event, report=None, cwd=None, parse=_whisper_progress, seen=None):
    """seen: lista donde se guardan las líneas del dispositivo (ver _device_used), que
    salen al principio y no quedan en la cola de 25 líneas para los errores."""
    if cancellation_event.is_set():
        return False, "Cancelado"
    tail = deque(maxlen=25)
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               stdin=subprocess.DEVNULL, cwd=cwd,
                               env=runtime_environment(cmd[0]),
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    def drain():
        for raw in iter(process.stdout.readline, b""):
            line = raw.decode("utf-8", errors="replace").strip()
            tail.append(line)
            if seen is not None and (_GPU_NAME.search(line) or _GPU_BACKEND.search(line)):
                seen.append(line)
            if report:
                value = parse(line)
                if value is not None:
                    report(value)
    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    try:
        while process.poll() is None:
            if cancellation_event.wait(0.1):
                process.kill()
                break
        process.wait()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        reader.join()
        process.stdout.close()
    return process.returncode == 0 and not cancellation_event.is_set(), "\n".join(tail)


def run_transcription(input_file, output_file, settings, fps=0, duration_sec=0,
                      trim_in=None, trim_out=None, cancellation_event=None,
                      progress_callback=None, worker_ref=None):
    cancellation_event = cancellation_event or threading.Event()
    started = time.monotonic()
    def progress(pct):
        eta = (time.monotonic() - started) * (100 - pct) / pct if pct > 0 else None
        if progress_callback:
            progress_callback(pct, eta)
    try:
        # "Aceleración de Hardware (GPU)" marcada: el de CUDA si está instalado; si no, CPU.
        prefer_gpu = settings.get("transcription_device") != "cpu"
        binary = select_binary(prefer_gpu)
        info = WHISPER_MODELS.get(settings.get("transcription_model"))
        if not binary or not model_ready(info):
            return False, "Descarga el motor whisper.cpp y el modelo antes de iniciar."
        ffmpeg = get_ffmpeg_path()
        if not ffmpeg or not os.path.isfile(ffmpeg):
            return False, "FFmpeg no está instalado."
        if not input_file or not os.path.isfile(input_file):
            return False, "El archivo de origen no existe."
        mode = embed_mode(settings)
        if mode != "none" and not _probe_codecs(input_file, "v"):
            return False, "El archivo no tiene video para incrustar los subtítulos."
        with tempfile.TemporaryDirectory(prefix="dowp-transcription-", dir=os.path.dirname(os.path.abspath(output_file))) as temporary:
            wav = str(Path(temporary) / "audio.wav")
            output_base = str(Path(temporary) / "transcript")
            # Validar los ajustes antes de extraer lo que pueden ser horas de audio.
            cmd = whisper_command(binary, model_path(info), wav, output_base, settings)
            extract = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
            if trim_in is not None:
                extract += ["-ss", str(max(0, float(trim_in)))]
            extract += ["-i", input_file]
            if trim_out is not None:
                length = float(trim_out) - float(trim_in or 0)
                if length <= 0:
                    return False, "El intervalo de transcripción no es válido."
                extract += ["-t", str(length)]
            track = settings.get("transcription_audio_track", 0)
            if isinstance(track, bool) or not isinstance(track, int) or track < 0:
                return False, "La pista de audio debe ser un índice válido; Todas se expande en la cola."
            extract += ["-map", f"0:a:{track}", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav]
            progress(0)
            ok, error = _run(extract, cancellation_event)
            if not ok:
                return False, "No se pudo extraer el audio. " + error
            progress(10)
            # Al quemar, la recodificación del video se lleva buena parte del tiempo.
            whisper_span = {"none": 89, "track": 80, "burn": 50}[mode]
            device_lines = []
            whisper_started = time.monotonic()
            ok, error = _run(cmd, cancellation_event, lambda p: progress(10 + p * whisper_span / 100),
                             os.path.dirname(binary), seen=device_lines)
            engine = "acelerado (" + (accel_variant() or "?") + ")" if binary == accel_runtime_path() else "base"
            cpu_binary = runtime_path()
            if (not ok and not cancellation_event.is_set() and binary == accel_runtime_path()
                    and cpu_binary and cpu_binary != binary):
                # Respaldo: si la aceleración falla (driver, memoria de video, una GPU sin
                # probar), se repite con el motor base
                # en vez de entregar un error. El subtítulo sale igual, solo más lento.
                logger.warning(f"Transcripción: whisper.cpp con aceleración por GPU falló, se repite con el motor base. {error[-300:]}")
                cmd = whisper_command(cpu_binary, model_path(info), wav, output_base, settings, cpu=True)
                device_lines.clear()
                whisper_started = time.monotonic()
                engine = "base (respaldo)"
                ok, error = _run(cmd, cancellation_event, lambda p: progress(10 + p * whisper_span / 100),
                                 os.path.dirname(cpu_binary), seen=device_lines)
            if not ok:
                version = vad_local_version() if settings.get("transcription_vad") else None
                if version and "v" + version != VAD_MODEL["variant"] and not cancellation_event.is_set():
                    error += (f"\n\nSe usó el detector de voz {version}, más nuevo que el probado "
                              f"({VAD_MODEL['variant']}). Si el error sigue, elimínalo en Ajustes > Dependencias "
                              "y vuelve a marcar Saltar silencios para instalar la versión probada.")
                return False, "whisper.cpp: " + error
            if cancellation_event.is_set():
                return False, "Cancelado"
            # Para los testers de GPU: qué motor y qué dispositivo se usaron, y cuánto tardó.
            logger.info(f"Transcripción: motor {engine} · {_device_used(device_lines)} · "
                        f"modelo {settings.get('transcription_model')} · "
                        f"whisper {time.monotonic() - whisper_started:.1f} s")
            produced = output_base + ".json"
            # Un resultado vacío es válido (silencio); que falte el archivo no es un éxito.
            if not os.path.isfile(produced):
                return False, "whisper.cpp no generó el archivo de salida."
            transcript = transcript_formats.load_whisper_json(produced)
            staged = str(Path(temporary) / ("final" + Path(output_file).suffix))
            if mode == "none":
                transcript_formats.write(transcript, settings.get("container", "srt"), staged,
                                         settings, title=Path(input_file).stem)
            else:
                # Pista en MKV: ASS si se eligió ASS (conserva el estilo); si no, SRT, que
                # MP4 y WebM convierten a su códec. Quemados: siempre ASS con el estilo.
                ext = Path(output_file).suffix.lower().lstrip(".")
                fmt = _effective_format(settings)
                if mode == "track":
                    fmt = "ass" if ext == "mkv" and fmt == "ass" else "vtt" if ext == "webm" else "srt"
                subtitle_name = "subs." + fmt
                transcript_formats.write(transcript, fmt, os.path.join(temporary, subtitle_name),
                                         dict(settings, container=fmt), title=Path(input_file).stem)
                length = float(trim_out) - float(trim_in or 0) if trim_out is not None else None
                embed, style = _embed_command(ffmpeg, os.path.abspath(input_file), subtitle_name, staged, mode,
                                              settings, transcript.get("language"), trim_in, length)
                if style is not None:
                    _font_folder(settings, os.path.join(temporary, "fonts"))
                total = length if length is not None else float(duration_sec or 0)
                start = 10 + whisper_span
                ok, error = _run(embed, cancellation_event, lambda p: progress(start + p * (99 - start) / 100),
                                 temporary, parse=_ffmpeg_progress(total))
                if not ok:
                    return False, ("No se pudieron incrustar los subtítulos. " + error) if not cancellation_event.is_set() else "Cancelado"
            # Con transcription_name_language el nombre final depende del idioma, que solo
            # se conoce ahora: se devuelve en los ajustes para que la cola lo registre.
            final_output = output_file
            if settings.get("transcription_name_language"):
                final_output = language_output_path(output_file, settings, transcript.get("language"))
                settings["_final_output_path"] = final_output
            os.replace(staged, final_output)
            progress(100)
            return True, ""
    except Exception as exc:
        return False, str(exc)
