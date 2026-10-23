"""Formatos de salida de la transcripción, generados por DowP a partir del JSON completo de
whisper.cpp (whisper-cli -ojf).

Por qué no se usan los formatos de whisper-cli: no escribe ASS, sus subtítulos no se
pueden limitar por líneas y su texto no se agrupa en párrafos. Con el JSON completo (cada
segmento y cada fragmento de palabra con su tiempo), DowP arma todos los formatos con las
mismas opciones.

- Subtítulos: SRT, VTT, ASS, LRC, TTML y SBV. Largo máximo por línea, líneas por
  subtítulo y corte por frases, por palabras (de 1 a N por subtítulo) o karaoke (ASS y
  LRC). El ASS lleva
  el estilo elegido (fuente, tamaño, colores, posición), que también usa el quemado.
- Texto: TXT, Markdown, HTML, RTF, JSON y CSV. Párrafos (por pausas) o una línea por
  segmento, con o sin marcas de tiempo.
"""
import csv
import html
import io
import json
import re
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

SUBTITLE_FORMATS = ("srt", "vtt", "ass", "lrc", "ttml", "sbv")
TEXT_FORMATS = ("txt", "md", "html", "rtf", "json", "csv")
ALL_FORMATS = SUBTITLE_FORMATS + TEXT_FORMATS
# Formatos que entienden el resaltado por palabra (karaoke).
KARAOKE_FORMATS = ("ass", "lrc")

# Una pausa de al menos esto entre dos segmentos empieza un párrafo nuevo.
_PARAGRAPH_GAP = 1.0
# Palabra por palabra: duración mínima de cada subtítulo, para que no sea un parpadeo.
_MIN_WORD_DURATION = 0.12
_SENTENCE_END = re.compile(r"[.!?…:;]$")
_SPECIAL_TOKEN = re.compile(r"^\[_.*\]$")

# Estilo por defecto de los subtítulos ASS (y del quemado). Tamaño en píxeles para un
# video de 1080 de alto: se escala al alto real del video.
DEFAULT_STYLE = {"font": "Arial", "size": 64, "color": "#FFFFFF", "outline": "#000000",
                 "karaoke_color": "#FFD400", "position": "bottom", "bold": True, "box": False}
_ALIGNMENT = {"bottom": 2, "middle": 5, "top": 8}


def output_mode(fmt: str) -> str:
    """"subtitles" o "text" según el formato."""
    return "text" if fmt in TEXT_FORMATS else "subtitles"


def split_mode(fmt: str, split: str) -> str:
    """El corte que de verdad se usa: el karaoke solo existe en ASS y LRC."""
    return "sentences" if split == "karaoke" and fmt not in KARAOKE_FORMATS else split


# ── Lectura del JSON de whisper.cpp ──────────────────────────────────────────────
def _repair(text: str) -> str:
    """whisper.cpp escribe los fragmentos tal cual, y un carácter de varios bytes (una
    letra con tilde, un ideograma) puede quedar partido entre dos: el JSON se lee con
    surrogateescape y aquí, ya unidos, se vuelven a decodificar bien."""
    return text.encode("utf-8", "surrogateescape").decode("utf-8", "replace")


def _words(tokens: list, seg_start: float, seg_end: float) -> list:
    """Palabras del segmento con su inicio: se unen los fragmentos hasta el siguiente que
    empieza con espacio. Con -dtw el tiempo de cada fragmento es t_dtw (centésimas, más
    preciso); si no, el de sus marcas. El final de una palabra es el inicio de la siguiente."""
    words, current = [], None
    for token in tokens or []:
        text = token.get("text", "")
        if not text or _SPECIAL_TOKEN.match(text):
            continue
        t_dtw = token.get("t_dtw", -1)
        at = t_dtw / 100.0 if isinstance(t_dtw, (int, float)) and t_dtw >= 0 else \
            token.get("offsets", {}).get("from", 0) / 1000.0
        if current is None or text.startswith(" "):
            if current is not None:
                words.append(current)
            current = {"text": text, "start": at}
        else:
            current["text"] += text
    if current is not None:
        words.append(current)
    cleaned = []
    for word in words:
        word["text"] = _repair(word["text"]).strip()
        if word["text"]:
            word["start"] = min(max(word["start"], seg_start), seg_end)
            if cleaned and word["start"] < cleaned[-1]["start"]:
                word["start"] = cleaned[-1]["start"]
            cleaned.append(word)
    for index, word in enumerate(cleaned):
        nxt = cleaned[index + 1]["start"] if index + 1 < len(cleaned) else seg_end
        word["end"] = max(nxt, word["start"])
    return cleaned


def load_whisper_json(path) -> dict:
    """{"language": "es" | None, "segments": [{"start", "end", "text", "words"}]} (segundos)."""
    raw = Path(path).read_bytes().decode("utf-8", "surrogateescape")
    data = json.loads(raw)
    segments = []
    for seg in data.get("transcription", []):
        offsets = seg.get("offsets", {})
        start, end = offsets.get("from", 0) / 1000.0, offsets.get("to", 0) / 1000.0
        text = re.sub(r"\s+", " ", _repair(seg.get("text", ""))).strip()
        if not text:
            continue
        segments.append({"start": start, "end": max(end, start), "text": text,
                         "words": _words(seg.get("tokens"), start, max(end, start))})
    return {"language": (data.get("result") or {}).get("language"), "segments": segments}


# ── Subtítulos: armado de los cues ───────────────────────────────────────────────
# Un cue es {"start", "end", "lines": [[palabra, ...], ...]} y cada palabra
# {"text", "start", "end"} (sin tiempos si whisper no los dio). Así el karaoke sabe dónde
# cae cada palabra y los demás formatos solo unen el texto.
def _wrap(words: list, max_chars: int) -> list:
    """Reparte las palabras en líneas de hasta max_chars, cortando entre palabras."""
    if max_chars <= 0:
        return [words] if words else []
    lines, line, length = [], [], 0
    for word in words:
        extra = len(word["text"]) + (1 if line else 0)
        if line and length + extra > max_chars:
            lines.append(line)
            line, length = [word], len(word["text"])
        else:
            line.append(word)
            length += extra
    if line:
        lines.append(line)
    return lines


def _chunks(segment: dict, limit: int) -> list:
    """Parte un segmento en trozos de hasta `limit` caracteres (0 = sin límite),
    prefiriendo cortar después de un signo de puntuación. Con tiempos por palabra, cada
    trozo toma los suyos; si no hay, se reparten en proporción al texto.
    Devuelve [(inicio, fin, palabras)]."""
    timed = bool(segment["words"])
    words = segment["words"] or [{"text": w} for w in segment["text"].split()]
    if not limit or len(segment["text"]) <= limit:
        groups = [words]
    else:
        groups, current = [], []
        for word in words:
            text = " ".join(w["text"] for w in current + [word])
            if current and len(text) > limit:
                groups.append(current)
                current = [word]
                continue
            current.append(word)
            if len(text) >= limit * 0.6 and _SENTENCE_END.search(word["text"]):
                groups.append(current)
                current = []
        if current:
            groups.append(current)
    total = sum(len(w["text"]) + 1 for w in words) or 1
    span = segment["end"] - segment["start"]
    result, cursor = [], segment["start"]
    for index, group in enumerate(groups):
        if timed:
            start = group[0]["start"] if index else segment["start"]
            end = groups[index + 1][0]["start"] if index + 1 < len(groups) else segment["end"]
        else:
            start = cursor
            end = start + span * (sum(len(w["text"]) + 1 for w in group) / total)
            cursor = end
        result.append((start, max(end, start), group))
    return result


def build_cues(segments: list, split: str = "sentences", max_chars: int = 42, max_lines: int = 2,
               max_words: int = 1) -> list:
    """Los subtítulos ya cortados. Ver la forma de un cue arriba."""
    cues = []
    if split == "words":
        words = [w for segment in segments for w in
                 (segment["words"] or [{"text": segment["text"], "start": segment["start"], "end": segment["end"]}])]
        # Grupos de hasta `max_words` palabras (1 = palabra por palabra, el estilo de
        # TikTok o Reels). Un grupo no cruza el final de una frase ni una pausa larga: si
        # no, mostraría palabras antes de que se digan. Dentro de cada frase se reparten
        # parejos: 6 palabras de a 5 son 3 + 3, no 5 + una sola suelta.
        size = max(1, int(max_words or 1))
        runs, current = [], []
        for word in words:
            if current and word["start"] - current[-1]["end"] >= _PARAGRAPH_GAP:
                runs.append(current)
                current = []
            current.append(word)
            if _SENTENCE_END.search(word["text"]):
                runs.append(current)
                current = []
        if current:
            runs.append(current)
        groups = []
        for run in runs:
            count = -(-len(run) // size)
            base, extra = divmod(len(run), count)
            position = 0
            for index in range(count):
                length = base + (1 if index < extra else 0)
                groups.append(run[position:position + length])
                position += length
        # Cada subtítulo dura al menos _MIN_WORD_DURATION (si no, sería un parpadeo): si
        # choca con el siguiente, ese empieza un poco después. Nunca se solapan.
        previous_end = 0.0
        for group in groups:
            start = max(group[0]["start"], previous_end)
            end = max(group[-1]["end"], start + _MIN_WORD_DURATION)
            cues.append({"start": start, "end": end, "lines": _wrap(group, max_chars) if size > 1 else [group]})
            previous_end = end
        return cues
    max_lines = max(1, int(max_lines or 1))
    limit = max_chars * max_lines if max_chars > 0 else 0
    for segment in segments:
        for start, end, group in _chunks(segment, limit):
            # Cada trozo ya mide como mucho max_chars × max_lines; si al repartir en líneas
            # sale una de más (palabras muy largas), se deja antes que perder texto.
            cues.append({"start": start, "end": end, "lines": _wrap(group, max_chars)})
    return cues


def _cue_text(cue: dict, joiner: str = "\n") -> str:
    return joiner.join(" ".join(w["text"] for w in line) for line in cue["lines"])


def _clock(seconds: float, sep: str = ",", hours_digits: int = 2) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    secs, ms = divmod(ms, 1000)
    return f"{hours:0{hours_digits}d}:{minutes:02d}:{secs:02d}{sep}{ms:03d}"


def _write_srt(cues, **_) -> str:
    return "".join(f"{i}\n{_clock(c['start'])} --> {_clock(c['end'])}\n{_cue_text(c)}\n\n"
                   for i, c in enumerate(cues, 1))


def _write_vtt(cues, **_) -> str:
    return "WEBVTT\n\n" + "".join(f"{_clock(c['start'], '.')} --> {_clock(c['end'], '.')}\n{_cue_text(c)}\n\n"
                                  for c in cues)


def _write_sbv(cues, **_) -> str:
    """Formato de subtítulos de YouTube: "0:00:01.000,0:00:03.500" y el texto."""
    return "".join(f"{_clock(c['start'], '.', 1)},{_clock(c['end'], '.', 1)}\n{_cue_text(c)}\n\n" for c in cues)


def _write_ttml(cues, language=None, **_) -> str:
    """TTML (W3C): el formato de subtítulos de Netflix, Adobe y la radiodifusión."""
    lang = f' xml:lang="{xml_escape(language)}"' if language else ""
    body = "".join(
        f'      <p begin="{_clock(c["start"], ".")}" end="{_clock(c["end"], ".")}">'
        + "<br/>".join(xml_escape(" ".join(w["text"] for w in line)) for line in c["lines"]) + "</p>\n"
        for c in cues)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<tt xmlns="http://www.w3.org/ns/ttml"{lang}>\n  <body>\n    <div>\n{body}    </div>\n  </body>\n</tt>\n')


def _ass_clock(seconds: float) -> str:
    cs = int(round(max(0.0, seconds) * 100))
    hours, cs = divmod(cs, 360_000)
    minutes, cs = divmod(cs, 6000)
    secs, cs = divmod(cs, 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{cs:02d}"


def _ass_color(hex_color: str, alpha: int = 0) -> str:
    """#RRGGBB -> &HAABBGGRR (ASS guarda los colores al revés y con transparencia)."""
    value = (hex_color or "#FFFFFF").lstrip("#")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", value):
        value = "FFFFFF"
    r, g, b = value[0:2], value[2:4], value[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def style_from(options: dict) -> dict:
    """El estilo de los subtítulos según los ajustes de la transcripción."""
    style = dict(DEFAULT_STYLE)
    for key in style:
        value = options.get("transcription_style_" + key)
        if value is not None and value != "":
            style[key] = value
    return style


def _ass_header(style: dict, video_size=None, karaoke: bool = False, burn: bool = False) -> str:
    """Encabezado con el estilo. La resolución del guion es la del video (si se conoce)
    para que el tamaño y los márgenes caigan donde se ven en la vista previa. El tamaño
    elegido es para 1080 en el lado CORTO: un vertical 1080x1920 usa la misma letra que un
    horizontal 1920x1080 (escalar por la altura la agrandaba tanto que se salía por los
    costados)."""
    width, height = video_size if video_size and all(video_size) else (1920, 1080)
    scale = min(width, height) / 1080.0
    size = max(8, round(float(style["size"]) * scale))
    outline = max(1, round(3 * scale))
    margin_v = round(60 * scale)
    margin_h = round(80 * scale)
    font = str(style["font"]).replace(",", " ")
    # En karaoke la palabra cantada toma el color principal y la que falta, el secundario.
    primary = _ass_color(style["karaoke_color"] if karaoke else style["color"])
    secondary = _ass_color(style["color"])
    if style["box"] and burn:
        # Al quemar (libass): BorderStyle 4, una sola caja por línea con el color de fondo y
        # el borde normal alrededor del texto. Con 3, el karaoke parte la caja en cada
        # palabra y se ven cortes. 4 es propio de libass: los ASS sueltos usan 3.
        border_style, outline_color, back = 4, _ass_color(style["outline"]), _ass_color("#000000", 0x60)
    elif style["box"]:
        # BorderStyle 3: caja opaca detrás del texto; su color es el del borde.
        border_style, outline_color, back = 3, _ass_color("#000000", 0x60), _ass_color("#000000", 0x60)
        outline = max(2, round(10 * scale))
    else:
        border_style, outline_color, back = 1, _ass_color(style["outline"]), _ass_color("#000000", 0x80)
    return (
        # WrapStyle 0: libass también corta las líneas que no caben en el ancho (además de
        # los saltos que pone DowP), así nada se sale del cuadro con cualquier largo de línea.
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding\n"
        f"Style: Default,{font},{size},{primary},{secondary},{outline_color},{back},{-1 if style['bold'] else 0},"
        f"0,0,0,100,100,0,0,{border_style},{outline},0,{_ALIGNMENT.get(style['position'], 2)},"
        f"{margin_h},{margin_h},{margin_v},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")


def _ass_text(text: str) -> str:
    # Las llaves abren etiquetas de estilo en ASS: no pueden quedar en el texto.
    return text.replace("{", "(").replace("}", ")")


def _ass_karaoke(cue: dict) -> str:
    """Cada palabra con {\\kf<centésimas>}: se va pintando mientras suena. Lo que pasa
    entre el inicio del subtítulo y la primera palabra es un \\k sin texto."""
    parts, cursor = [], cue["start"]
    for line_index, line in enumerate(cue["lines"]):
        if line_index:
            parts.append("\\N")
        for word_index, word in enumerate(line):
            start = word.get("start", cursor)
            end = word.get("end", start)
            if start > cursor + 0.005:
                parts.append(f"{{\\k{round((start - cursor) * 100)}}}")
            parts.append(f"{{\\kf{max(1, round((end - max(start, cursor)) * 100))}}}"
                         + ("" if word_index == 0 else " ") + _ass_text(word["text"]))
            cursor = max(cursor, end)
    return "".join(parts)


def _write_ass(cues, style=None, video_size=None, karaoke=False, burn=False, **_) -> str:
    style = style or dict(DEFAULT_STYLE)
    lines = []
    for c in cues:
        text = _ass_karaoke(c) if karaoke else _ass_text(_cue_text(c, "\\N"))
        lines.append(f"Dialogue: 0,{_ass_clock(c['start'])},{_ass_clock(c['end'])},Default,,0,0,0,,{text}\n")
    return _ass_header(style, video_size, karaoke, burn) + "".join(lines)


def _lrc_stamp(seconds: float, brackets: str = "[]") -> str:
    cs = int(round(max(0.0, seconds) * 100))
    minutes, cs = divmod(cs, 6000)
    return f"{brackets[0]}{minutes:02d}:{cs // 100:02d}.{cs % 100:02d}{brackets[1]}"


def _write_lrc(cues, karaoke=False, **_) -> str:
    """LRC: una línea por verso. En karaoke es el LRC "mejorado": <mm:ss.xx> antes de
    cada palabra, que leen reproductores como MusicBee, Poweramp o foobar2000."""
    out = []
    for c in cues:
        if karaoke:
            words = [w for line in c["lines"] for w in line]
            text = " ".join(_lrc_stamp(w.get("start", c["start"]), "<>") + w["text"] for w in words)
        else:
            text = _cue_text(c, " ")
        out.append(f"{_lrc_stamp(c['start'])}{text}\n")
    return "".join(out)


# ── Texto ────────────────────────────────────────────────────────────────────────
def _paragraphs(segments: list) -> list:
    """[(inicio, texto)] uniendo segmentos hasta una pausa larga."""
    paragraphs = []
    for segment in segments:
        if paragraphs and segment["start"] - paragraphs[-1]["end"] < _PARAGRAPH_GAP:
            paragraphs[-1]["text"] += " " + segment["text"]
            paragraphs[-1]["end"] = segment["end"]
        else:
            paragraphs.append({"start": segment["start"], "end": segment["end"], "text": segment["text"]})
    return [(p["start"], p["text"]) for p in paragraphs]


def _short_clock(seconds: float) -> str:
    total = int(max(0.0, seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def _blocks(segments, layout, timestamps):
    """[(marca de tiempo o "", texto)] por párrafo o por segmento."""
    blocks = _paragraphs(segments) if layout == "paragraphs" else [(s["start"], s["text"]) for s in segments]
    return [(_short_clock(start) if timestamps else "", text) for start, text in blocks]


def _write_txt(segments, layout, timestamps, **_):
    joiner = "\n\n" if layout == "paragraphs" else "\n"
    body = joiner.join((f"[{stamp}] " if stamp else "") + text for stamp, text in _blocks(segments, layout, timestamps))
    return body + "\n" if body else ""


def _write_md(segments, layout, timestamps, title="", language=None):
    head = f"# {title}\n\n" if title else ""
    if language:
        head += f"*{language}*\n\n"
    joiner = "\n\n" if layout == "paragraphs" else "  \n"
    body = joiner.join((f"**[{stamp}]** " if stamp else "") + text
                       for stamp, text in _blocks(segments, layout, timestamps))
    return head + body + ("\n" if body else "")


_HTML_PAGE = """<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{ font-family: system-ui, -apple-system, "Segoe UI", sans-serif; max-width: 46rem;
         margin: 2.5rem auto; padding: 0 1rem; line-height: 1.65; color: #1d1d1f; background: #fff; }}
  h1 {{ font-size: 1.6rem; margin-bottom: 1.5rem; }}
  p {{ margin: {gap}; }}
  .t {{ color: #8a8a8e; font-variant-numeric: tabular-nums; margin-right: .5em; font-size: .9em; }}
  @media (prefers-color-scheme: dark) {{ body {{ color: #e8e8ea; background: #161617; }} }}
</style>
</head>
<body>
{heading}{body}
</body>
</html>
"""


def _write_html(segments, layout, timestamps, title="", language=None):
    """Página lista para abrir en el navegador o pegar en un blog."""
    body = "\n".join(f'<p>{f"<span class=t>[{stamp}]</span>" if stamp else ""}{html.escape(text)}</p>'
                     for stamp, text in _blocks(segments, layout, timestamps))
    return _HTML_PAGE.format(lang=html.escape(language or ""), title=html.escape(title or "Transcripción"),
                             gap="0 0 1em" if layout == "paragraphs" else "0 0 .3em",
                             heading=f"<h1>{html.escape(title)}</h1>\n" if title else "", body=body)


def _rtf_escape(text: str) -> str:
    """Texto para RTF: barras y llaves escapadas; lo que no es ASCII como \\uN? (UTF-16,
    con signo, y pares sustitutos para emojis y otros fuera del plano básico)."""
    out = []
    for char in text:
        if char in "\\{}":
            out.append("\\" + char)
        elif ord(char) < 128:
            out.append(char)
        else:
            data = char.encode("utf-16-le")
            for i in range(0, len(data), 2):
                unit = int.from_bytes(data[i:i + 2], "little")
                out.append(f"\\u{unit - 65536 if unit > 32767 else unit}?")
    return "".join(out)


def _write_rtf(segments, layout, timestamps, title="", **_):
    """Documento que abren Word, LibreOffice y WordPad con formato (título y marcas)."""
    paragraph_end = "\\par\\par\n" if layout == "paragraphs" else "\\par\n"
    parts = ["{\\rtf1\\ansi\\deff0{\\fonttbl{\\f0\\fswiss Calibri;}}{\\colortbl;\\red128\\green128\\blue128;}\n",
             "\\f0\\fs24\n"]
    if title:
        parts.append(f"{{\\b\\fs32 {_rtf_escape(title)}}}\\par\\par\n")
    for stamp, text in _blocks(segments, layout, timestamps):
        prefix = f"{{\\cf1 [{stamp}]}} " if stamp else ""
        parts.append(prefix + _rtf_escape(text) + paragraph_end)
    parts.append("}\n")
    return "".join(parts)


def _write_json(segments, language=None, **_):
    return json.dumps({
        "language": language,
        "segments": [{"start": round(s["start"], 3), "end": round(s["end"], 3), "text": s["text"],
                      "words": [{"start": round(w["start"], 3), "end": round(w["end"], 3), "text": w["text"]}
                                for w in s["words"]]} for s in segments],
    }, ensure_ascii=False, indent=2) + "\n"


def _write_csv(segments, **_):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["start", "end", "text"])
    for s in segments:
        writer.writerow([f"{s['start']:.3f}", f"{s['end']:.3f}", s["text"]])
    return buffer.getvalue()


_SUBTITLE_WRITERS = {"srt": _write_srt, "vtt": _write_vtt, "ass": _write_ass, "lrc": _write_lrc,
                     "ttml": _write_ttml, "sbv": _write_sbv}
_TEXT_WRITERS = {"txt": _write_txt, "md": _write_md, "html": _write_html, "rtf": _write_rtf,
                 "json": _write_json, "csv": _write_csv}


# ── Entrada única ────────────────────────────────────────────────────────────────
def render(transcript: dict, fmt: str, options: dict | None = None, title: str = "") -> str:
    """Texto del archivo final en `fmt`, con las opciones de la transcripción."""
    options = options or {}
    segments, language = transcript["segments"], transcript.get("language")
    if fmt in SUBTITLE_FORMATS:
        split = split_mode(fmt, options.get("transcription_split", "sentences"))
        karaoke = split == "karaoke"
        cues = build_cues(segments, "sentences" if karaoke else split,
                          int(options.get("transcription_max_chars", 42) or 0),
                          int(options.get("transcription_max_lines", 2) or 1),
                          int(options.get("transcription_max_words", 1) or 1))
        return _SUBTITLE_WRITERS[fmt](cues, style=style_from(options), language=language, karaoke=karaoke,
                                      burn=options.get("transcription_embed") == "burn",
                                      video_size=options.get("transcription_video_size"))
    if fmt in TEXT_FORMATS:
        return _TEXT_WRITERS[fmt](segments, layout=options.get("transcription_text_layout", "paragraphs"),
                                  timestamps=bool(options.get("transcription_timestamps")),
                                  title=title, language=language)
    raise ValueError(f"Formato de transcripción no válido: {fmt}")


def write(transcript: dict, fmt: str, path, options: dict | None = None, title: str = "") -> None:
    """Escribe el archivo. CSV con BOM, para que Excel lo abra con los acentos bien."""
    encoding = "utf-8-sig" if fmt == "csv" else "utf-8"
    Path(path).write_text(render(transcript, fmt, options, title), encoding=encoding, newline="\n")
