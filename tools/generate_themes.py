"""Genera los temas incluidos (Tokyo Night, Café Noir, Rubí, Nórdico) a partir de dowp.json.

- Grises de DowP -> gama de neutros tintados del tema (interpolando por luminosidad).
- Verdes de marca -> mismo brillo y saturación, con el tono del acento del tema.
- Colores con significado propio (éxito, IN, consola, descarga...) se mantienen.
- Los tokens clave se fijan a mano en "fijos".
Uso (desde la raíz del repo): .venv/Scripts/python.exe tools/generate_themes.py [ruta de gui/themes]
Sobrescribe los JSON de los temas listados en THEMES; dowp.json no se toca.
"""
import colorsys, json, os, sys

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "app", "src", "gui", "themes")
base = json.load(open(os.path.join(OUT, "dowp.json"), encoding="utf-8"))
dowp = base["colores"]

KEEP = {  # significado propio: no se recolorean
    "estado_exito",
    "boton_descarga_done_inicio", "boton_descarga_done_fin", "boton_marca_entrada", "boton_marca_salida",
    "consola_fondo", "consola_texto", "consola_debug", "consola_advertencia", "consola_error", "consola_critico",
    "etiqueta_combinado", "etiqueta_multi_idioma", "etiqueta_estrella", "etiqueta_peligro",
    "titulo_cerrar_hover", "titulo_cerrar_pulsado",
}


def hex2rgb(h):
    h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def rgb2hex(c):
    return "#" + "".join(f"{max(0, min(255, round(x * 255))):02x}" for x in c)


def lightness(h):
    return colorsys.rgb_to_hls(*hex2rgb(h))[1]


def classify(h):
    if not h.startswith("#") or len(h) != 7:
        return "other"
    hh, l, s = colorsys.rgb_to_hls(*hex2rgb(h))
    if s < 0.15 or l < 0.08 or l > 0.95:
        return "neutral"
    if 0.17 < hh < 0.42:
        return "green"
    return "other"


def ramp(anchors, L):
    anchors = sorted(anchors)
    if L <= anchors[0][0]:
        return anchors[0][1]
    for (l0, c0), (l1, c1) in zip(anchors, anchors[1:]):
        if l0 <= L <= l1:
            t = (L - l0) / (l1 - l0) if l1 > l0 else 0
            a, b = hex2rgb(c0), hex2rgb(c1)
            return rgb2hex(tuple(x + (y - x) * t for x, y in zip(a, b)))
    return anchors[-1][1]


def to_accent_hue(h, accent, max_sat):
    _, l, s = colorsys.rgb_to_hls(*hex2rgb(h))
    ah = colorsys.rgb_to_hls(*hex2rgb(accent))[0]
    return rgb2hex(colorsys.hls_to_rgb(ah, l, min(s, max_sat)))


def build(spec):
    colores = {}
    for key, value in dowp.items():
        pair = value if isinstance(value, list) else [value, value]
        out = []
        for i, mode in enumerate(("light", "dark")):
            v = pair[i]
            kind = classify(v)
            if key in KEEP or kind == "other":
                out.append(v)
            elif kind == "neutral":
                out.append(ramp(spec["neutros"][mode], lightness(v)))
            else:
                out.append(to_accent_hue(v, spec["acento"][mode], spec.get("saturacion_max", 1.0)))
        colores[key] = out[0] if out[0] == out[1] else out
    for key, value in spec["fijos"].items():
        assert key in dowp, key
        colores[key] = value
    # "Descargando" usa el degradado del botón principal (lleva el mismo texto encima)
    fijos = spec["fijos"]
    colores["boton_descarga_running_inicio"] = fijos.get("boton_descarga_running_inicio", fijos["boton_fondo_inicio"])
    colores["boton_descarga_running_fin"] = fijos.get("boton_descarga_running_fin", fijos["boton_fondo_fin"])
    return {
        "meta": {"nombre": spec["nombre"], "autor": "DowP Team", "version": "1.0", "formato": 2,
                 "descripcion": spec["descripcion"]},
        "formas": spec["formas"],
        "tipografia": {"tamano": 13},
        "colores": colores,
    }


THEMES = {
    "tokyo_night": {
        "nombre": "Tokyo Night",
        "descripcion": "Azul noche con acentos morados y celestes, inspirado en Tokyo Night. Esquinas algo más redondas.",
        "formas": {"radio": 9, "radio_chico": 6, "radio_grande": 12, "borde": 1},
        "acento": {"light": "#7847bd", "dark": "#bb9af7"},
        "neutros": {
            "dark": [(0.0, "#0f0f14"), (0.04, "#16161e"), (0.07, "#1a1b26"), (0.10, "#1f2335"), (0.13, "#24283b"),
                     (0.20, "#292e42"), (0.33, "#414868"), (0.6, "#737aa2"), (0.88, "#c0caf5"), (1.0, "#e9edff")],
            "light": [(0.0, "#1f2335"), (0.1, "#343b58"), (0.33, "#565a6e"), (0.6, "#8990b3"), (0.85, "#c4c8da"),
                      (0.93, "#d5d6db"), (0.97, "#e1e2e7"), (1.0, "#e9eaf0")],
        },
        "fijos": {
            "acento_primario": ["#7847bd", "#bb9af7"], "acento_secundario": ["#2e7de9", "#7aa2f7"],
            "boton_fondo_inicio": ["#9854f1", "#bb9af7"], "boton_fondo_fin": ["#2e7de9", "#7aa2f7"],
            "boton_texto": ["#ffffff", "#1a1b26"], "boton_acento_texto": ["#ffffff", "#1a1b26"],
            "seleccion_fondo": ["#d0d5e3", "#283457"], "seleccion_texto": ["#7847bd", "#bb9af7"],
            "progreso_inicio": ["#9854f1", "#bb9af7"], "progreso_fin": ["#2e7de9", "#7aa2f7"],
            "estado_exito": ["#587539", "#9ece6a"], "estado_error": ["#f52a65", "#f7768e"],
            "estado_aviso": ["#8c6c3e", "#e0af68"], "estado_progreso": ["#007197", "#7dcfff"],
            "texto_clave": ["#2e7de9", "#7aa2f7"], "texto_valor": ["#343b58", "#c0caf5"],
            "texto_suave": ["#565a6e", "#a9b1d6"], "borde_focus": ["#2e7de9", "#7aa2f7"],
            # Botón de iniciar (descargar / procesar / recodificar): celeste -> azul
            "boton_descarga_inicio": ["#0db9d7", "#7dcfff"], "boton_descarga_fin": ["#2e7de9", "#7aa2f7"],
            "boton_descarga_texto": ["#ffffff", "#1a1b26"],
        },
    },
    "cafe_noir": {
        "nombre": "Café Noir",
        "descripcion": "Cafés y crema, cálido y sobrio. Esquinas casi rectas.",
        "formas": {"radio": 2, "radio_chico": 1, "radio_grande": 3, "borde": 1},
        "acento": {"light": "#8b5a2b", "dark": "#d4a373"},
        "saturacion_max": 0.55,
        "neutros": {
            "dark": [(0.0, "#0b0907"), (0.04, "#14100d"), (0.07, "#1a1511"), (0.10, "#201a15"), (0.13, "#271f19"),
                     (0.20, "#33291f"), (0.33, "#54443a"), (0.6, "#9a8a7a"), (0.88, "#e8dccb"), (1.0, "#f7efe3")],
            "light": [(0.0, "#1a110b"), (0.1, "#2b1d14"), (0.33, "#5e4a3a"), (0.6, "#a38c73"), (0.85, "#d6c6ae"),
                      (0.93, "#e6dac8"), (0.97, "#efe6d8"), (1.0, "#f6f0e6")],
        },
        "fijos": {
            "acento_primario": ["#8b5a2b", "#d4a373"], "acento_secundario": ["#6f4518", "#a9744f"],
            "boton_fondo_inicio": ["#9c6b3e", "#d4a373"], "boton_fondo_fin": ["#6f4518", "#a9744f"],
            "boton_texto": ["#fff8ef", "#1a110b"], "boton_acento_texto": ["#fff8ef", "#1a110b"],
            "seleccion_fondo": ["#ead9c2", "#3a2c22"], "seleccion_texto": ["#6f4518", "#d4a373"],
            "progreso_inicio": ["#b07a47", "#d4a373"], "progreso_fin": ["#6f4518", "#8b5a2b"],
            "estado_exito": ["#4f7a2c", "#8fbf6a"], "estado_error": ["#b03a2e", "#e06c5a"],
            "estado_aviso": ["#946b1d", "#e0b062"], "estado_progreso": ["#3c6e91", "#7fa7c9"],
            "texto_clave": ["#8b5a2b", "#d4a373"], "texto_valor": ["#2b1d14", "#e8dccb"],
            "texto_suave": ["#5e4a3a", "#b8a48e"], "borde_focus": ["#8b5a2b", "#d4a373"],
            "boton_descarga_inicio": ["#b8864f", "#e0b97a"], "boton_descarga_fin": ["#7a4a1f", "#c08552"],
            "boton_descarga_texto": ["#fff8ef", "#1a110b"],
        },
    },
    "rubi": {
        "nombre": "Rubí",
        "descripcion": "Rojo carmesí sobre negro cálido, elegante y con contraste.",
        "formas": {"radio": 6, "radio_chico": 4, "radio_grande": 8, "borde": 1},
        "acento": {"light": "#b3132f", "dark": "#e0435a"},
        "neutros": {
            "dark": [(0.0, "#0a0607"), (0.04, "#120b0d"), (0.07, "#170e11"), (0.10, "#1c1215"), (0.13, "#22171a"),
                     (0.20, "#2e1f23"), (0.33, "#4d3439"), (0.6, "#9c8286"), (0.88, "#f0e2e4"), (1.0, "#fff5f6")],
            "light": [(0.0, "#14080b"), (0.1, "#26141a"), (0.33, "#5c3d43"), (0.6, "#a8898e"), (0.85, "#e0cdd0"),
                      (0.93, "#efe3e5"), (0.97, "#f7f0f1"), (1.0, "#fcf8f8")],
        },
        "fijos": {
            "acento_primario": ["#b3132f", "#e0435a"], "acento_secundario": ["#7d0d22", "#a8172f"],
            "boton_fondo_inicio": ["#c41e3a", "#e0435a"], "boton_fondo_fin": ["#8a1028", "#a8172f"],
            "boton_texto": "#ffffff", "boton_acento_texto": "#ffffff",
            "seleccion_fondo": ["#f5dde1", "#3a1a22"], "seleccion_texto": ["#b3132f", "#f07a8a"],
            "progreso_inicio": ["#c41e3a", "#e0435a"], "progreso_fin": ["#7d0d22", "#7d0d22"],
            # El error no puede confundirse con el acento: va hacia el naranja
            "estado_error": ["#c2410c", "#ff8a65"], "estado_exito": ["#1e874b", "#4fbf7a"],
            "estado_aviso": ["#9a6a00", "#e8b04a"], "estado_progreso": ["#2563b0", "#6aa8e8"],
            "boton_descarga_error_inicio": ["#e0662f", "#ff8a65"], "boton_descarga_error_fin": ["#b8461a", "#c2410c"],
            "texto_clave": ["#b3132f", "#f07a8a"], "texto_valor": ["#26141a", "#f0e2e4"],
            "texto_suave": ["#5c3d43", "#c9aeb2"], "borde_focus": ["#b3132f", "#e0435a"],
            "boton_descarga_inicio": ["#d63a55", "#ee6b7f"], "boton_descarga_fin": ["#8a1028", "#b3132f"],
            "boton_descarga_texto": "#ffffff",
        },
    },
    "nordico": {
        "nombre": "Nórdico",
        "descripcion": "Grises azulados y tonos hielo, tranquilo y de bajo contraste, inspirado en Nord.",
        "formas": {"radio": 6, "radio_chico": 4, "radio_grande": 10, "borde": 1},
        "acento": {"light": "#5e81ac", "dark": "#88c0d0"},
        "neutros": {
            "dark": [(0.0, "#1f232b"), (0.04, "#242933"), (0.07, "#2b303b"), (0.10, "#2e3440"), (0.13, "#353c4a"),
                     (0.20, "#3b4252"), (0.33, "#4c566a"), (0.6, "#7b88a1"), (0.88, "#e5e9f0"), (1.0, "#eceff4")],
            "light": [(0.0, "#242933"), (0.1, "#2e3440"), (0.33, "#4c566a"), (0.6, "#7b88a1"), (0.85, "#c7cfdd"),
                      (0.93, "#d8dee9"), (0.97, "#e5e9f0"), (1.0, "#eceff4")],
        },
        "fijos": {
            "acento_primario": ["#5e81ac", "#88c0d0"], "acento_secundario": ["#4c6a91", "#5e81ac"],
            "boton_fondo_inicio": ["#5e81ac", "#88c0d0"], "boton_fondo_fin": ["#4c6a91", "#5e81ac"],
            "boton_texto": ["#ffffff", "#2e3440"], "boton_acento_texto": ["#ffffff", "#2e3440"],
            "seleccion_fondo": ["#d8dee9", "#434c5e"], "seleccion_texto": ["#4c6a91", "#88c0d0"],
            "progreso_inicio": ["#5e81ac", "#88c0d0"], "progreso_fin": ["#4c6a91", "#5e81ac"],
            "estado_exito": ["#4f7a3a", "#a3be8c"], "estado_error": ["#a33b45", "#bf616a"],
            "estado_aviso": ["#8a6d1f", "#ebcb8b"], "estado_progreso": ["#3b6ea8", "#81a1c1"],
            "texto_clave": ["#4c6a91", "#88c0d0"], "texto_valor": ["#2e3440", "#e5e9f0"],
            "texto_suave": ["#4c566a", "#d8dee9"], "borde_focus": ["#5e81ac", "#88c0d0"],
            "boton_descarga_inicio": ["#5e9ea0", "#8fbcbb"], "boton_descarga_fin": ["#4c6a91", "#88c0d0"],
            "boton_descarga_texto": ["#ffffff", "#2e3440"],
        },
    },
}

for theme_id, spec in THEMES.items():
    data = build(spec)
    with open(os.path.join(OUT, f"{theme_id}.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        f.write("\n")
    print(theme_id, len(data["colores"]), "colores")
