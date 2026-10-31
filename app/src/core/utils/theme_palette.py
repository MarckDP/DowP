"""Crear un tema a partir de una imagen.

No se inventan los más de cien colores de un tema: se parte de la escalera de fondos, textos
y bordes de un tema hecho a mano (Rubí, teñido en claro y en oscuro) y solo se le cambian tono
y saturación según la imagen. Los colores de estado siguen las reglas de los temas de DowP:

  - El tono se queda en su familia (un error nunca es azul).
  - La saturación acompaña al acento (Nórdico apagado, Tokyo Night vivo).
  - El error se aleja del acento si chocan (Rubí: acento rojo, error naranja).

Lo que es igual en todos los temas (consola, etiquetas, botón de cerrar...) no se genera: se
hereda de DowP con "basado_en".
"""
import colorsys
import math
from dataclasses import dataclass

from PIL import Image, ImageOps
from PySide6.QtCore import QCoreApplication

from core.utils import theme_loader

TEMPLATE_THEME = "rubi"
FALLBACK_ACCENT = "#B9E640"  # imagen sin color: el acento de DowP
_MIN_CHROMA = 0.22  # por debajo, un color no sirve como acento tal cual

VARIANT_NEUTRAL = "neutral"  # fondos casi grises, como DowP
VARIANT_TINTED = "tinted"    # fondos teñidos con el acento, como Rubí o Café Noir
VARIANT_SOFT = "soft"        # fondos más claros y poca saturación, como Nórdico
VARIANT_DUO = "duo"          # degradados entre dos colores, como Tokyo Night
VARIANT_INVERTED = "inverted"  # los colores de la imagen invertida
VARIANTS = (VARIANT_NEUTRAL, VARIANT_TINTED, VARIANT_SOFT, VARIANT_DUO, VARIANT_INVERTED)

_TEMPLATE_HUE = 351
_DARK, _LIGHT = 1, 0  # posición de cada modo en el par [claro, oscuro] del JSON

# Texto de botones cuyo fondo no cambia entre temas: se heredan de DowP.
_INHERITED = {"boton_solo_texto", "boton_importar_texto", "boton_fragmentos_texto", "boton_descarga_pausar_texto"}
_SECOND_COLOR = {"acento_secundario", "boton_fondo_fin", "boton_descarga_fin", "boton_descarga_running_fin", "progreso_fin"}

# (familia de tono, luz en claro, luz en oscuro)
_STATES = {"estado_exito": (135, 0.33, 0.56), "estado_aviso": (42, 0.33, 0.62),
           "estado_error": (5, 0.43, 0.67), "estado_progreso": (205, 0.40, 0.65)}

# (color, sobre qué fondos, contraste mínimo): lo que debe leerse en cualquier tema generado.
_READABLE = (("texto_principal", ("fondo_principal", "fondo_secundario", "panel_fondo"), 7.0),
             ("texto_secundario", ("fondo_principal", "fondo_secundario"), 2.0),
             ("acento_primario", ("fondo_principal", "fondo_secundario"), 3.0),
             ("seleccion_texto", ("seleccion_fondo",), 3.5),
             ("badge_texto", ("badge_fondo",), 3.0),
             ("boton_texto", ("boton_fondo_inicio", "boton_fondo_fin"), 3.0),
             ("boton_descarga_texto", ("boton_descarga_inicio", "boton_descarga_fin"), 3.0),
             ("estado_exito", ("fondo_secundario",), 3.0),
             ("estado_aviso", ("fondo_secundario",), 3.0),
             ("estado_error", ("fondo_secundario",), 3.0),
             ("estado_progreso", ("fondo_secundario",), 3.0))


@dataclass
class ImagePalette:
    accent: str           # el color más vistoso
    second: str | None    # otro color vistoso, de otro tono (None si la imagen no lo tiene)
    dominant_hue: float   # tono de lo que más ocupa, en grados
    has_color: bool       # False: imagen casi gris
    inverted: str | None = None  # el color más vistoso de la imagen invertida


def _to_hls(color: str) -> tuple:
    c = color.lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return h * 360, l, s


def _to_hex(h: float, l: float, s: float) -> str:
    r, g, b = colorsys.hls_to_rgb((h % 360) / 360, max(0.0, min(1.0, l)), max(0.0, min(1.0, s)))
    return "#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255))


def _hue_distance(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


def _luminance(color: str) -> float:
    c = color.lstrip("#")

    def channel(v):
        v = int(v, 16) / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(c[0:2]) + 0.7152 * channel(c[2:4]) + 0.0722 * channel(c[4:6])


def contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _complement(color: str) -> str:
    h, l, s = _to_hls(color)
    return _to_hex(h + 180, l, s)


def analyze_image(path: str) -> ImagePalette:
    """Los colores de una imagen y los de su versión invertida."""
    with Image.open(path) as source:
        im = source.convert("RGBA")
    im.thumbnail((200, 200))
    palette = _analyze(im)
    r, g, b, a = im.split()
    flipped = Image.merge("RGBA", (*ImageOps.invert(Image.merge("RGB", (r, g, b))).split(), a))
    inverted = _analyze(flipped)
    palette.inverted = inverted.accent if inverted.has_color else _complement(palette.accent)
    return palette


def _analyze(im: Image.Image) -> ImagePalette:
    """Las zonas transparentes de un PNG no cuentan."""
    alpha = im.getchannel("A")
    opaque = Image.new("RGB", im.size, (0, 0, 0))
    opaque.paste(im, mask=alpha)
    quant = opaque.quantize(32, method=Image.Quantize.MEDIANCUT)
    palette = quant.getpalette()
    counts = [0] * 256
    for index, a in zip(quant.getdata(), alpha.getdata()):
        if a >= 128:
            counts[index] += 1
    total = sum(counts)
    if not total:
        return ImagePalette(FALLBACK_ACCENT, None, _to_hls(FALLBACK_ACCENT)[0], False)

    swatches = []
    for i, count in enumerate(counts):
        if count:
            color = "#{:02x}{:02x}{:02x}".format(*palette[i * 3:i * 3 + 3])
            swatches.append((color, *_to_hls(color), count / total))

    # La familia de tono que más ocupa, sin contar grises ni casi negros (ahí el tono es ruido).
    families = {}
    for _, h, l, s, weight in swatches:
        if s >= 0.12 and 0.03 <= l <= 0.95:
            families.setdefault(round(h / 30) % 12, []).append((weight, h))
    family_weight = lambda members: sum(w for w, _ in members)
    if not families or sum(family_weight(m) for m in families.values()) < 0.03:
        hue = _to_hls(FALLBACK_ACCENT)[0]
        return ImagePalette(FALLBACK_ACCENT, None, hue, False)
    main = max(families.values(), key=family_weight)
    dominant_hue = max(main)[1]

    def chroma(entry):
        # Cuánto color se ve de verdad. La saturación sola engaña: un azul casi blanco o un
        # morado casi negro pueden dar "70 %" y apenas tener color.
        _, _, l, s, _ = entry
        return (1 - abs(2 * l - 1)) * s

    def score(entry):
        return chroma(entry) * (0.35 + math.sqrt(entry[4]))

    vivid = sorted((e for e in swatches if chroma(e) >= _MIN_CHROMA), key=score, reverse=True)
    if vivid:
        best = vivid[0]
        accent, accent_hue = best[0], best[1]
    else:
        # Nada vistoso (imagen muy oscura o muy pálida): su tono, con luz de acento.
        accent, accent_hue = _to_hex(dominant_hue, 0.6, 0.6), dominant_hue
    second = next((e[0] for e in vivid if _hue_distance(e[1], accent_hue) >= 40 and e[2] <= 0.8), None)
    return ImagePalette(accent, second, dominant_hue, True)


def _pair(value) -> list:
    return list(value) if isinstance(value, list) else [value, value]


def _template() -> tuple:
    """Los colores de la plantilla que cambian entre temas, y a qué familia pertenecen."""
    own = theme_loader.read_theme(TEMPLATE_THEME).get("colores", {})
    base = theme_loader.read_theme(theme_loader.DEFAULT_THEME).get("colores", {})
    neutral, accent = {}, {}
    for key, value in own.items():
        if value == base.get(key) or key in _STATES or key in _INHERITED or key.startswith("boton_descarga_error"):
            continue
        pair = _pair(value)
        if not all(theme_loader.is_valid_color(v) and str(v).startswith("#") and len(str(v)) == 7 for v in pair):
            continue
        h, l, s = _to_hls(pair[_DARK])
        if s >= 0.35 and 0.2 <= l <= 0.85 and _hue_distance(h, _TEMPLATE_HUE) <= 20:
            accent[key] = pair
        elif s < 0.35 or l < 0.2 or l > 0.85:
            neutral[key] = pair
    return neutral, accent


def _state_hue(key: str, accent_hue: float) -> float:
    family = _STATES[key][0]
    if key == "estado_error" and _hue_distance(accent_hue, family) < 40:
        # Como Rubí: un acento rojo o rosa manda el error al naranja; uno naranja, al rojo.
        return 16 if not 8 <= accent_hue <= 45 else 350
    if key == "estado_aviso" and _hue_distance(accent_hue, family) < 12:
        return 54 if accent_hue < family else 34
    return family


def _ensure_contrast(color: str, backgrounds: list, ratio: float) -> str:
    """Mueve la luz del color lo justo para que se lea sobre todos esos fondos."""
    h, l, s = _to_hls(color)
    darker_bg = sum(_luminance(b) for b in backgrounds) / len(backgrounds) < 0.25
    for _ in range(60):
        if all(contrast(color, b) >= ratio for b in backgrounds):
            return color
        l = l + 0.015 if darker_bg else l - 0.015
        if l < 0 or l > 1:
            break
        color = _to_hex(h, l, s)
    return "#ffffff" if darker_bg else "#000000"


def _button_text(backgrounds: list, tint_hue: float, dark_tint_saturation=0.3) -> str:
    """Blanco o casi negro, el que mejor se lea sobre el botón (como los temas de DowP)."""
    light, dark = "#ffffff", _to_hex(tint_hue, 0.08, dark_tint_saturation)
    worst = lambda c: min(contrast(c, b) for b in backgrounds)
    return light if worst(light) >= worst(dark) else dark


def build_colors(palette: ImagePalette, variant: str, accent_override: str | None = None) -> dict:
    """Los colores del tema, como pares [claro, oscuro], para el JSON."""
    neutral, accents = _template()
    accent = accent_override or palette.accent
    if variant == VARIANT_INVERTED:
        # Con un acento elegido a mano, invertido es su opuesto.
        accent = _complement(accent_override) if accent_override else (palette.inverted or _complement(accent))
    a_hue, _, a_sat = _to_hls(accent)
    # Sin segundo color en la imagen, sale del opuesto: "Dos colores" siempre es distinta.
    second = (palette.second or palette.inverted or _complement(accent)) if variant == VARIANT_DUO else None
    if variant == VARIANT_NEUTRAL:
        bg_hue, bg_factor = a_hue, 0.1
    elif variant == VARIANT_SOFT:
        bg_hue, bg_factor = (palette.dominant_hue if palette.has_color else a_hue), 0.7
    else:
        bg_hue, bg_factor = a_hue, 1.0
    if variant == VARIANT_SOFT:
        a_sat *= 0.65
    a_sat = max(a_sat, 0.28)

    colors = {}
    for key, pair in neutral.items():
        out = []
        for mode in (_LIGHT, _DARK):
            _, l, s = _to_hls(pair[mode])
            # Suave: en oscuro los fondos suben a gris azulado, como Nórdico.
            if variant == VARIANT_SOFT and mode == _DARK and l < 0.3:
                l += 0.09
            out.append(_to_hex(bg_hue, l, s * bg_factor))
        colors[key] = out

    ref = theme_loader.read_theme(TEMPLATE_THEME)["colores"]["acento_primario"]
    ref_light = [_to_hls(_pair(ref)[_LIGHT]), _to_hls(_pair(ref)[_DARK])]
    target = [max(0.36, min(0.50, _to_hls(accent)[1])), max(0.57, min(0.75, _to_hls(accent)[1]))]
    for key, pair in accents.items():
        out = []
        for mode in (_LIGHT, _DARK):
            _, l, s = _to_hls(pair[mode])
            hue = a_hue
            if second and key in _SECOND_COLOR:
                hue = _to_hls(second)[0]
            shifted = l + target[mode] - ref_light[mode][1]
            out.append(_to_hex(hue, shifted, s / max(ref_light[mode][2], 0.01) * a_sat))
        colors[key] = out

    state_sat = max(0.40, min(0.85, 0.40 + 0.5 * a_sat))
    for key, (_, light_l, dark_l) in _STATES.items():
        hue = _state_hue(key, a_hue)
        colors[key] = [_to_hex(hue, light_l, state_sat), _to_hex(hue, dark_l, state_sat)]
    error_hue = _state_hue("estado_error", a_hue)
    colors["boton_descarga_error_inicio"] = [_to_hex(error_hue, 0.55, 0.75), _to_hex(error_hue, 0.68, 0.95)]
    colors["boton_descarga_error_fin"] = [_to_hex(error_hue, 0.38, 0.85), _to_hex(error_hue, 0.40, 0.85)]

    for key, backgrounds in (("boton_texto", ("boton_fondo_inicio", "boton_fondo_fin")),
                             ("boton_descarga_texto", ("boton_descarga_inicio", "boton_descarga_fin"))):
        colors[key] = [_button_text([colors[b][m] for b in backgrounds], a_hue) for m in (_LIGHT, _DARK)]
        # Tonos medios o degradados entre dos colores: ni blanco ni negro alcanzan en los
        # dos extremos, así que se corre el fondo del botón hasta que el texto se lea.
        for b in backgrounds:
            colors[b] = [_ensure_contrast(colors[b][m], [colors[key][m]], 3.1) for m in (_LIGHT, _DARK)]
    if "acento_secundario" in colors:  # botones sólidos
        colors["boton_acento_texto"] = [_button_text([colors["acento_primario"][m], colors["acento_secundario"][m]], a_hue)
                                        for m in (_LIGHT, _DARK)]

    for key, backgrounds, ratio in _READABLE:
        if key in colors and not key.startswith("boton_"):
            colors[key] = [_ensure_contrast(colors[key][m], [colors[b][m] for b in backgrounds if b in colors], ratio)
                           for m in (_LIGHT, _DARK)]
    return colors


# ── Editor de colores: los básicos arrastran a su familia ────────────────────
_FONDOS = ("fondo_principal", "fondo_secundario", "fondo_terciario", "fondo_elemento", "fondo_campo", "fondo_control",
           "fondo_control_hover", "fondo_hover", "fondo_miniatura", "panel_fondo", "tarjeta_lista_fondo",
           "tarjeta_futura_fondo", "cabecera_dialogo", "onda_fondo", "barra_scroll_fondo", "progreso_fondo",
           "checkbox_fondo", "boton_neutro_fondo", "boton_neutro_hover", "miniatura_relleno_fondo", "ajedrez_c1", "ajedrez_c2")
_TEXTOS = ("texto_principal", "texto_secundario", "texto_deshabilitado", "texto_activo", "texto_suave", "texto_valor",
           "texto_titulo", "texto_fuerte", "texto_medio", "texto_gris", "texto_tenue", "texto_primario", "texto_apagado",
           "tab_texto_inactivo", "icono_principal", "icono_tenue", "flecha_control")
_ACENTOS = ("acento_primario", "badge_texto", "seleccion_texto", "boton_fondo_inicio", "boton_descarga_inicio",
            "boton_descarga_running_inicio", "titulo_settings", "divisor_settings", "boton_secundario_texto",
            "boton_secundario_fondo", "boton_secundario_hover", "checkbox_checked", "progreso_inicio", "texto_clave",
            "borde_focus")
_BORDES = ("borde_normal", "borde_sutil", "borde_fuerte", "borde_campo", "borde", "divisor", "checkbox_borde",
           "switch_borde", "tarjeta_lista_borde", "boton_neutro_borde")
BASIC_COLORS = {
    "fondo_principal": _FONDOS,
    "texto_principal": _TEXTOS,
    "texto_secundario": ("texto_secundario", "texto_gris", "texto_tenue", "texto_apagado"),
    "acento_primario": _ACENTOS,
    "acento_secundario": ("acento_secundario", *sorted(_SECOND_COLOR - {"acento_secundario"})),
    "borde_normal": _BORDES,
    "seleccion_fondo": ("seleccion_fondo", "badge_fondo"),
    "estado_exito": ("estado_exito",),
    "estado_aviso": ("estado_aviso",),
    "estado_error": ("estado_error", "boton_descarga_error_inicio", "boton_descarga_error_fin"),
    "estado_progreso": ("estado_progreso",),
}
# Sobre qué fondo debe leerse cada básico, y con cuánto contraste.
_BASIC_CHECKS = {"texto_principal": ("fondo_secundario", 4.5), "texto_secundario": ("fondo_secundario", 2.0),
                 "acento_primario": ("fondo_secundario", 3.0),
                 "fondo_principal": ("texto_principal", 4.5), "seleccion_fondo": ("seleccion_texto", 3.0),
                 "estado_exito": ("fondo_secundario", 3.0), "estado_aviso": ("fondo_secundario", 3.0),
                 "estado_error": ("fondo_secundario", 3.0), "estado_progreso": ("fondo_secundario", 3.0)}


def _is_hex(color) -> bool:
    return isinstance(color, str) and color.startswith("#") and len(color) == 7


def basic_family(key: str, tokens: dict) -> list:
    """Los colores que cambian junto con un básico, de los que tiene el tema."""
    return [t for t in BASIC_COLORS[key] if t in tokens]


def basic_low_contrast(key: str, tokens: dict) -> bool:
    check = _BASIC_CHECKS.get(key)
    if not check or not _is_hex(tokens.get(key)) or not _is_hex(tokens.get(check[0])):
        return False
    return contrast(tokens[key], tokens[check[0]]) < check[1]


def _shift_family(tokens: dict, key: str, color: str) -> dict:
    """La familia de `key` pasa al tono de `color` y conserva la distancia de luz y saturación
    que tenía con `key`, así la escalera se mantiene."""
    _, ref_l, ref_s = _to_hls(tokens[key]) if _is_hex(tokens.get(key)) else (0, 0.5, 0.5)
    hue, light, sat = _to_hls(color)
    changes = {}
    for token in basic_family(key, tokens):
        if token == key:
            changes[token] = color
        elif _is_hex(tokens[token]):
            _, l, s = _to_hls(tokens[token])
            changes[token] = _to_hex(hue, l + light - ref_l, sat * (s / ref_s) if ref_s > 0.02 else sat)
    return changes


def derive_basic(tokens: dict, key: str, color: str) -> dict:
    """Los colores que cambian al poner `color` en un básico."""
    changes = _shift_family(tokens, key, color)
    hue = _to_hls(color)[0]
    if key == "acento_primario" and _is_hex(tokens.get("acento_secundario")) and _is_hex(tokens.get(key)):
        # Los botones sólidos usan el segundo acento: lo acompaña, a la misma distancia de luz.
        # Quien quiera otro tono se lo elige después.
        _, ref_l, ref_s = _to_hls(tokens[key])
        _, second_l, second_s = _to_hls(tokens["acento_secundario"])
        _, light, sat = _to_hls(color)
        second = _to_hex(hue, second_l + light - ref_l, sat * (second_s / ref_s) if ref_s > 0.02 else sat)
        changes.update(_shift_family(tokens, "acento_secundario", second))
    # Si cambia un botón de acento, su texto debe seguir leyéndose.
    if key in ("acento_primario", "acento_secundario"):
        merged = {**tokens, **changes}
        for text, backgrounds in (("boton_texto", ("boton_fondo_inicio", "boton_fondo_fin")),
                                  ("boton_descarga_texto", ("boton_descarga_inicio", "boton_descarga_fin")),
                                  ("boton_acento_texto", ("acento_primario", "acento_secundario"))):
            if text in tokens and all(_is_hex(merged.get(b)) for b in backgrounds):
                changes[text] = _button_text([merged[b] for b in backgrounds], hue)
    return changes


def contrast_failures(colors: dict) -> list:
    """Lo que no se llegaría a leer. Vacío en un tema correcto (lo comprueban los tests)."""
    failures = []
    for key, backgrounds, ratio in _READABLE:
        for mode, label in ((_LIGHT, "claro"), (_DARK, "oscuro")):
            for b in backgrounds:
                value = contrast(colors[key][mode], colors[b][mode])
                if value < ratio - 0.01:
                    failures.append((label, key, b, round(value, 2), ratio))
    return failures


def build_theme(name: str, colors: dict) -> dict:
    """El tema completo, listo para theme_io.save_imported."""
    return {"meta": {"nombre": name, "autor": "DowP", "version": "1.0", "formato": 2,
                     "descripcion": QCoreApplication.translate("ThemePalette", "Creado a partir de una imagen.")},
            "basado_en": theme_loader.DEFAULT_THEME,
            "formas": dict(theme_loader.read_theme(TEMPLATE_THEME).get("formas", {})),
            "colores": colors}
