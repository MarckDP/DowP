VIDEO_EXTENSIONS = {'mp4', 'mkv', 'webm', 'mov', 'flv', 'avi', 'gif'}
AUDIO_EXTENSIONS = {'m4a', 'mp3', 'ogg', 'opus', 'flac', 'wav'}
SINGLE_STREAM_AUDIO_CONTAINERS = {'.mp3', '.wav', '.flac', '.ac3'}

FORMAT_MUXER_MAP = {
    ".m4a": "mp4",
    ".wma": "asf"
}

LANG_CODE_MAP = {
    "es": "Español",
    "es-419": "Español (Latinoamérica)",
    "es-es": "Español (España)",
    "es_la": "Español (Latinoamérica)", 
    "en": "Inglés",
    "en-us": "Inglés (EE.UU.)",
    "en-gb": "Inglés (Reino Unido)",
    "en-orig": "Inglés (Original)",
    "ja": "Japonés",
    "fr": "Francés",
    "de": "Alemán",
    "it": "Italiano",
    "pt": "Portugués",
    "pt-br": "Portugués (Brasil)",
    "pt-pt": "Portugués (Portugal)",
    "ru": "Ruso",
    "zh": "Chino",
    "zh-cn": "Chino (Simplificado)",
    "zh-tw": "Chino (Tradicional)",
    "zh-hans": "Chino (Simplificado)", 
    "zh-hant": "Chino (Tradicional)", 
    "ko": "Coreano",
    "ar": "Árabe",
    "hi": "Hindi",
    "iw": "Hebreo (código antiguo)", 
    "he": "Hebreo",
    "fil": "Filipino", 
    "aa": "Afar",
    "ab": "Abjasio",
    "ae": "Avéstico",
    "af": "Afrikáans",
    "ak": "Akán",
    "am": "Amárico",
    "an": "Aragonés",
    "as": "Asamés",
    "av": "Avar",
    "ay": "Aimara",
    "az": "Azerí",
    "ba": "Baskir",
    "be": "Bielorruso",
    "bg": "Búlgaro",
    "bh": "Bhojpuri",
    "bho": "Bhojpuri", 
    "bi": "Bislama",
    "bm": "Bambara",
    "bn": "Bengalí",
    "bo": "Tibetano",
    "br": "Bretón",
    "bs": "Bosnio",
    "ca": "Catalán",
    "ce": "Checheno",
    "ceb": "Cebuano", 
    "ch": "Chamorro",
    "co": "Corso",
    "cr": "Cree",
    "cs": "Checo",
    "cu": "Eslavo eclesiástico",
    "cv": "Chuvash",
    "cy": "Galés",
    "da": "Danés",
    "dv": "Divehi",
    "dz": "Dzongkha",
    "ee": "Ewe",
    "el": "Griego",
    "eo": "Esperanto",
    "et": "Estonio",
    "eu": "Euskera",
    "fa": "Persa",
    "ff": "Fula",
    "fi": "Finlandés",
    "fj": "Fiyiano",
    "fo": "Feroés",
    "fy": "Frisón occidental",
    "ga": "Irlandés",
    "gd": "Gaélico escocés",
    "gl": "Gallego",
    "gn": "Guaraní",
    "gu": "Guyaratí",
    "gv": "Manés",
    "ha": "Hausa",
    "ht": "Haitiano",
    "hu": "Húngaro",
    "hy": "Armenio",
    "hz": "Herero",
    "ia": "Interlingua",
    "id": "Indonesio",
    "ie": "Interlingue",
    "ig": "Igbo",
    "ii": "Yi de Sichuán",
    "ik": "Inupiaq",
    "io": "Ido",
    "is": "Islandés",
    "iu": "Inuktitut",
    "jv": "Javanés",
    "ka": "Georgiano",
    "kg": "Kongo",
    "ki": "Kikuyu",
    "kj": "Kuanyama",
    "kk": "Kazajo",
    "kl": "Groenlandés",
    "km": "Jemer",
    "kn": "Canarés",
    "kr": "Kanuri",
    "ks": "Cachemiro",
    "ku": "Kurdo",
    "kv": "Komi",
    "kw": "Córnico",
    "ky": "Kirguís",
    "la": "Latín",
    "lb": "Luxemburgués",
    "lg": "Ganda",
    "li": "Limburgués",
    "ln": "Lingala",
    "lo": "Lao",
    "lt": "Lituano",
    "lu": "Luba-katanga",
    "lv": "Letón",
    "mg": "Malgache",
    "mh": "Marshalés",
    "mi": "Maorí",
    "mk": "Macedonio",
    "ml": "Malayalam",
    "mn": "Mongol",
    "mr": "Maratí",
    "ms": "Malayo",
    "mt": "Maltés",
    "my": "Birmano",
    "na": "Nauruano",
    "nb": "Noruego bokmål",
    "nd": "Ndebele del norte",
    "ne": "Nepalí",
    "ng": "Ndonga",
    "nl": "Neerlandés",
    "nn": "Noruego nynorsk",
    "no": "Noruego",
    "nr": "Ndebele del sur",
    "nv": "Navajo",
    "ny": "Chichewa",
    "oc": "Occitano",
    "oj": "Ojibwa",
    "om": "Oromo",
    "or": "Oriya",
    "os": "Osético",
    "pa": "Panyabí",
    "pi": "Pali",
    "pl": "Polaco",
    "ps": "Pastún",
    "qu": "Quechua",
    "rm": "Romanche",
    "rn": "Kirundi",
    "ro": "Rumano",
    "rw": "Kinyarwanda",
    "sa": "Sánscrito",
    "sc": "Sardo",
    "sd": "Sindhi",
    "se": "Sami septentrional",
    "sg": "Sango",
    "si": "Cingalés",
    "sk": "Eslovaco",
    "sl": "Esloveno",
    "sm": "Samoano",
    "sn": "Shona",
    "so": "Somalí",
    "sq": "Albanés",
    "sr": "Serbio",
    "ss": "Suazi",
    "st": "Sesotho",
    "su": "Sundanés",
    "sv": "Sueco",
    "sw": "Suajili",
    "ta": "Tamil",
    "te": "Telugu",
    "tg": "Tayiko",
    "th": "Tailandés",
    "ti": "Tigriña",
    "tk": "Turcomano",
    "tl": "Tagalo",
    "tn": "Setsuana",
    "to": "Tongano",
    "tr": "Turco",
    "ts": "Tsonga",
    "tt": "Tártaro",
    "tw": "Twi",
    "ty": "Tahitiano",
    "ug": "Uigur",
    "uk": "Ucraniano",
    "ur": "Urdu",
    "uz": "Uzbeko",
    "ve": "Venda",
    "vi": "Vietnamita",
    "vo": "Volapük",
    "wa": "Valón",
    "wo": "Wolof",
    "xh": "Xhosa",
    "yi": "Yidis",
    "yo": "Yoruba",
    "za": "Zhuang",
    "zu": "Zulú",
    "und": "No especificado",
    "alb-al": "Albanés (Albania)",
    "ara-sa": "Árabe (Arabia Saudita)",
    "aze-az": "Azerí (Azerbaiyán)",
    "ben-bd": "Bengalí (Bangladesh)",
    "bul-bg": "Búlgaro (Bulgaria)",
    "cat-es": "Catalán (España)",
    "ces-cz": "Checo (República Checa)",
    "cmn-hans-cn": "Chino Mandarín (Simplificado, China)",
    "cmn-hant-cn": "Chino Mandarín (Tradicional, China)",
    "crs": "Francés criollo seselwa",
    "dan-dk": "Danés (Dinamarca)",
    "deu-de": "Alemán (Alemania)",
    "ell-gr": "Griego (Grecia)",
    "est-ee": "Estonio (Estonia)",
    "fil-ph": "Filipino (Filipinas)",
    "fin-fi": "Finlandés (Finlandia)",
    "fra-fr": "Francés (Francia)",
    "gaa": "Ga",
    "gle-ie": "Irlandés (Irlanda)",
    "haw": "Hawaiano",
    "heb-il": "Hebreo (Israel)",
    "hin-in": "Hindi (India)",
    "hmn": "Hmong",
    "hrv-hr": "Croata (Croacia)",
    "hun-hu": "Húngaro (Hungría)",
    "ind-id": "Indonesio (Indonesia)",
    "isl-is": "Islandés (Islandia)",
    "ita-it": "Italiano (Italia)",
    "jav-id": "Javanés (Indonesia)",
    "jpn-jp": "Japonés (Japón)",
    "kaz-kz": "Kazajo (Kazajistán)",
    "kha": "Khasi",
    "khm-kh": "Jemer (Camboya)",
    "kor-kr": "Coreano (Corea del Sur)",
    "kri": "Krio",
    "lav-lv": "Letón (Letonia)",
    "lit-lt": "Lituano (Lituania)",
    "lua": "Luba-Lulua",
    "luo": "Luo",
    "mfe": "Morisyen",
    "msa-my": "Malayo (Malasia)",
    "mya-mm": "Birmano (Myanmar)",
    "new": "Newari",
    "nld-nl": "Neerlandés (Países Bajos)",
    "nob-no": "Noruego Bokmål (Noruega)",
    "nso": "Sotho del norte",
    "pam": "Pampanga",
    "pol-pl": "Polaco (Polonia)",
    "por-pt": "Portugués (Portugal)",
    "ron-ro": "Rumano (Rumania)",
    "rus-ru": "Ruso (Rusia)",
    "slk-sk": "Eslovaco (Eslovaquia)",
    "slv-si": "Esloveno (Eslovenia)",
    "spa-es": "Español (España)",
    "swa-sw": "Suajili", 
    "swe-se": "Sueco (Suecia)",
    "tha-th": "Tailandés (Tailandia)",
    "tum": "Tumbuka",
    "tur-tr": "Turco (Turquía)",
    "ukr-ua": "Ucraniano (Ucrania)",
    "urd-pk": "Urdu (Pakistán)",
    "uzb-uz": "Uzbeko (Uzbekistán)",
    "vie-vn": "Vietnamita (Vietnam)",
    "war": "Waray",
    "alb": "Albanés",
    "ara": "Árabe",
    "aze": "Azerí",
    "ben": "Bengalí",
    "bul": "Búlgaro",
    "cat": "Catalán",
    "ces": "Checo",
    "cmn": "Chino Mandarín",
    "dan": "Danés",
    "deu": "Alemán",
    "ell": "Griego",
    "est": "Estonio",
    "fin": "Finlandés",
    "fra": "Francés",
    "gle": "Irlandés",
    "heb": "Hebreo",
    "hin": "Hindi",
    "hrv": "Croata",
    "hun": "Húngaro",
    "ind": "Indonesio",
    "isl": "Islandés",
    "ita": "Italiano",
    "jav": "Javanés",
    "jpn": "Japonés",
    "kaz": "Kazajo",
    "khm": "Jemer",
    "kor": "Coreano",
    "lav": "Letón",
    "lit": "Lituano",
    "msa": "Malayo",
    "mya": "Birmano",
    "nld": "Neerlandés",
    "nob": "Noruego Bokmål",
    "pol": "Polaco",
    "por": "Portugués",
    "ron": "Rumano",
    "rus": "Ruso",
    "slk": "Eslovaco",
    "slv": "Esloveno",
    "spa": "Español",
    "swe": "Sueco",
    "swa": "Suajili",
    "tha": "Tailandés",
    "tur": "Turco",
    "ukr": "Ucraniano",
    "urd": "Urdu",
    "uzb": "Uzbeko",
    "vie": "Vietnamita",
}

LANGUAGE_ORDER = {
    'es-419': 0,   # Español LATAM
    'es-es': 1,    # Español España
    'es': 2,       # Español general
    'en': 3,       # Inglés
    'ja': 4,       # Japonés 
    'fr': 5,       # Francés 
    'de': 6,       # Alemán 
    'pt': 7,       # Portugués
    'it': 8,       # Italiano
    'zh': 9,       # Chino
    'ko': 10,      # Coreano
    'ru': 11,      # Ruso
    'ar': 12,      # Árabe
    'hi': 13,      # Hindi
    'vi': 14,      # Vietnamita
    'th': 15,      # Tailandés
    'pl': 16,      # Polaco
    'id': 17,      # Indonesio
    'tr': 18,      # Turco
    'bn': 19,      # Bengalí
    'ta': 20,      # Tamil
    'te': 21,      # Telugu
    'pa': 22,      # Punjabi
    'mr': 23,      # Marathi
    'ca': 24,      # Catalán
    'gl': 25,      # Gallego
    'eu': 26,      # Euskera
    'und': 27,     # Indefinido
}

DEFAULT_PRIORITY = 99 

EDITOR_FRIENDLY_CRITERIA = {
    "compatible_vcodecs": [
        "h264", "avc1",  # H.264
        "hevc", "h265",  # H.265
        "prores",        # Apple ProRes
        "dnxhd", "dnxhr", # Avid DNxHD/HR
        "cfhd",          # GoPro CineForm
        "mpeg2video",    
        "dvvideo"        # Formato de cámaras MiniDV
    ],
    "compatible_acodecs": ["aac", "mp4a", "pcm_s16le", "pcm_s24le", "mp3", "ac3"],
    "compatible_exts": ["mp4", "mov", "mxf", "mts", "m2ts", "avi"],
}

COMPATIBILITY_RULES = {
    ".gif": {
        "video": ["gif"],  
        "audio": []       
    },
    ".mov": {
        "video": ["prores_aw", "prores_ks", "dnxhd", "cfhd", "qtrle", "hap", "h264_videotoolbox", "libx264"],
        "audio": ["pcm_s16le", "pcm_s24le", "alac"]
    },
    ".mp4": {
        "video": ["libx264", "libx265", "h264_nvenc", "hevc_nvenc", "h264_amf", "hevc_amf", "av1_nvenc", "av1_amf", "h264_qsv", "hevc_qsv", "av1_qsv", "vp9_qsv"],
        "audio": ["aac", "mp3", "ac3", "opus"]
    },
    ".mkv": {
        "video": ["libx264", "libx265", "libvpx", "libvpx-vp9", "libaom-av1", "h264_nvenc", "hevc_nvenc", "av1_nvenc"],
        "audio": ["aac", "mp3", "opus", "flac", "libvorbis", "ac3", "pcm_s16le"]
    },
    ".webm": { "video": ["libvpx", "libvpx-vp9", "libaom-av1"], "audio": ["libopus", "libvorbis"] },
    ".ogg": { "video": [], "audio": ["libvorbis", "libopus"] },
    ".ac3": { "video": [], "audio": ["ac3"] },
    ".wma": { "video": [], "audio": ["wmav2"] },
    ".mxf": { "video": ["mpeg2video", "dnxhd"], "audio": ["pcm_s16le", "pcm_s24le"] },
    ".flac": { "video": [], "audio": ["flac"] },
    ".mp3": { "video": [], "audio": ["libmp3lame"] },
    ".m4a": { "video": [], "audio": ["aac", "alac"] },
    ".opus": { "video": [], "audio": ["libopus"] },
    ".wav": { "video": [], "audio": ["pcm_s16le", "pcm_s24le"] }
}

# --- NUEVO: Definir formatos RAW ---
IMAGE_RAW_FORMATS = {".CR2", ".DNG", ".ARW", ".NEF", ".ORF", ".RW2", ".SR2", ".RAF", ".CR3", ".PEF"}
# --- CONSTANTES DE HERRAMIENTAS DE IMAGEN ---

# Actualizar los formatos de entrada permitidos sumando los RAW
IMAGE_INPUT_FORMATS = {".svg", ".eps", ".ai", ".pdf", ".ps", ".avif"}.union(IMAGE_RAW_FORMATS)
IMAGE_EXPORT_FORMATS = ["PNG", "JPG", "JPEG", "WEBP", "AVIF", "BMP", "PDF", "TIFF"]

# Agrupar formatos por tipo para mejor manejo en la lógica y la UI
IMAGE_RASTER_FORMATS = {"PNG", "JPG", "JPEG", "WEBP", "BMP", "TIFF", "AVIF"}
IMAGE_VECTOR_FORMATS = {"PDF"} 
FORMATS_WITH_TRANSPARENCY = {"PNG", "WEBP", "TIFF", "ICO", "PDF", "AVIF"}

# DPI por defecto para rasterización (de PDF, SVG, etc.)
DEFAULT_RASTER_DPI = 300

# Límites de seguridad para escalado
MAX_RECOMMENDED_DPI = 600
MAX_SAFE_DIMENSION = 8192  # Píxeles (8K)
CRITICAL_DPI_THRESHOLD = 1200
CRITICAL_DIMENSION_THRESHOLD = 16384  # 16K

# Métodos de interpolación para escalado de raster
INTERPOLATION_METHODS = {
    "Lanczos (Mejor Calidad)": "LANCZOS",
    "Bicúbico (Rápido)": "BICUBIC", 
    "Bilineal (Muy Rápido)": "BILINEAR",
    "Nearest (Pixelado)": "NEAREST"
}

# Opciones de Canvas
CANVAS_OPTIONS = [
    "Sin ajuste",
    "Añadir Margen Externo",
    "Añadir Margen Interno",
    "Instagram Post (1080×1080)",
    "Instagram Story (1080×1920)",
    "YouTube Thumbnail (1280×720)",
    "Twitter Header (1500×500)",
    "Facebook Cover (820×312)",
    "Personalizado..."
]

# Mapeo de presets fijos
CANVAS_PRESET_SIZES = {
    "Instagram Post (1080×1080)": (1080, 1080),
    "Instagram Story (1080×1920)": (1080, 1920),
    "YouTube Thumbnail (1280×720)": (1280, 720),
    "Twitter Header (1500×500)": (1500, 500),
    "Facebook Cover (820×312)": (820, 312)
}

# Posiciones para el contenido en el canvas
CANVAS_POSITIONS = [
    "Centro",
    "Arriba Izquierda",
    "Arriba Centro",
    "Arriba Derecha",
    "Centro Izquierda",
    "Centro Derecha",
    "Abajo Izquierda",
    "Abajo Centro",
    "Abajo Derecha"
]

# Modos de manejo cuando la imagen excede el canvas
CANVAS_OVERFLOW_MODES = [
    "Reducir hasta que quepa",           
    "Centrar (puede recortar)",
    "Recortar al canvas",
    "Advertir y no procesar"
]

# Opciones de cambio de fondo
BACKGROUND_TYPES = [
    "Color Sólido",
    "Degradado",
    "Imagen de Fondo"
]

GRADIENT_DIRECTIONS = [
    "Horizontal (Izq → Der)",
    "Vertical (Arr → Aba)",
    "Diagonal (↘)",
    "Diagonal (↙)",
    "Radial (Centro)"
]

# Formatos que soportan transparencia
FORMATS_WITH_TRANSPARENCY = {"PNG", "WEBP", "TIFF", "ICO", "PDF"}

REMBG_MODEL_FAMILIES = {
    "Rembg Standard (U2Net)": {
        "isnet-general-use (Recomendado)": {
            "file": "isnet-general-use.onnx",
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-general-use.onnx",
            "folder": "rembg" 
        },
        "u2netp (Rápido)": {
            "file": "u2netp.onnx",
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx",
            "folder": "rembg"
        },
        "u2net (Alta Precisión)": {
            "file": "u2net.onnx",
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx",
            "folder": "rembg"
        },
        "u2net_human_seg (Humanos)": {
            "file": "u2net_human_seg.onnx",
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net_human_seg.onnx",
            "folder": "rembg"
        },
        "isnet-anime (Anime)": {
            "file": "isnet-anime.onnx",
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-anime.onnx",
            "folder": "rembg"
        }
    },
    "BiRefNet (Next-Gen 2024)": {
        # --- MODELOS GENERALES ---
        "General (Estándar)": {
            "file": "birefnet-general.onnx",  # ✅ Nombre que rembg espera
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-general-epoch_244.onnx",
            "folder": "rembg"
        },
        "General Lite (Rápido)": {
            "file": "birefnet-general-lite.onnx",  # ✅ Cambiado
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx",
            "folder": "rembg"
        },
        
        # --- ESPECIALIZADOS ---
        "Portrait (Retratos)": {
            "file": "birefnet-portrait.onnx",  # ✅ Cambiado
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-portrait-epoch_150.onnx",
            "folder": "rembg"
        },
        "DIS (Bordes Finos/Complejo)": {
            "file": "birefnet-dis.onnx",  # ✅ Cambiado
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-DIS-epoch_590.onnx",
            "folder": "rembg"
        },
        "COD (Objetos Camuflados)": {
            "file": "birefnet-cod.onnx",  # ✅ Cambiado
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-COD-epoch_125.onnx",
            "folder": "rembg"
        },
        "HRSOD (Alta Detección)": {
            "file": "birefnet-hrsod.onnx",  # ✅ Cambiado
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-HRSOD_DHU-epoch_115.onnx",
            "folder": "rembg"
        },
        
        # --- ALTA RESOLUCIÓN (HR) & MASIVOS ---
        "Massive (Entrenamiento Masivo)": {
            "file": "birefnet-massive.onnx",  # ✅ Cambiado
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-massive-TR_DIS5K_TR_TEs-epoch_420.onnx",
            "folder": "rembg"
        },
        "HR General (4K/8K)": {
            "file": "birefnet-hr-general.onnx",  # ✅ Cambiado
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet_HR-general-epoch_130.onnx",
            "folder": "rembg"
        },
        "HR Matting (Recorte Ultra Fino)": {
            "file": "birefnet-hr-matting.onnx",  # ✅ Cambiado
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet_HR-matting-epoch_135.onnx",
            "folder": "rembg"
        }
    },

    # --- NUEVO BLOQUE: RMBG 2.0 (Descarga Manual) ---
    "RMBG 2.0 (BriaAI)": {
        "Standard (Automático - 977 MB)": {
            "file": "rmbg2_gatis.onnx", 
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/bria-rmbg-2.0.onnx",
            "folder": "rmbg2"
        },
        "Standard (1.02 GB)": {
            "file": "model.onnx", 
            "url": "https://huggingface.co/briaai/RMBG-2.0/tree/main/onnx",
            "folder": "rmbg2" 
        },
        "BnB4 (Recomendado - 355 MB)": {
            "file": "model_bnb4.onnx",
            "url": "https://huggingface.co/briaai/RMBG-2.0/tree/main/onnx",
            "folder": "rmbg2"
        },
        "FP16 (Media - 514 MB)": {
            "file": "model_fp16.onnx",
            "url": "https://huggingface.co/briaai/RMBG-2.0/tree/main/onnx",
            "folder": "rmbg2"
        },
        "Int8 (Rápido - 366 MB)": {
            "file": "model_int8.onnx",
            "url": "https://huggingface.co/briaai/RMBG-2.0/tree/main/onnx",
            "folder": "rmbg2"
        },
        "Quantized (366 MB)": {
            "file": "model_quantized.onnx",
            "url": "https://huggingface.co/briaai/RMBG-2.0/tree/main/onnx",
            "folder": "rmbg2"
        }
    }
}

UPSCALING_TOOLS = {
    "Real-ESRGAN": {
        "name": "Real-ESRGAN",
        "folder": "realesrgan",
        "exe": "realesrgan-ncnn-vulkan.exe",
        "url": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip"
    },
    "Waifu2x": {
        "name": "Waifu2x",
        "folder": "waifu2x",
        "exe": "waifu2x-ncnn-vulkan.exe",
        "url": "https://github.com/nihui/waifu2x-ncnn-vulkan/releases/download/20250915/waifu2x-ncnn-vulkan-20250915-windows.zip"
    },
    "RealSR": {
        "name": "RealSR",
        "folder": "realsr",
        "exe": "realsr-ncnn-vulkan.exe",
        "url": "https://github.com/nihui/realsr-ncnn-vulkan/releases/download/20220728/realsr-ncnn-vulkan-20220728-windows.zip"
    },
    "SRMD": {
        "name": "SRMD",
        "folder": "srmd",
        "exe": "srmd-ncnn-vulkan.exe",
        "url": "https://github.com/nihui/srmd-ncnn-vulkan/releases/download/20220728/srmd-ncnn-vulkan-20220728-windows.zip"
    }
}

# --- CONSTANTES DE REESCALADO (IA) ---

# Definimos el modelo interno y las escalas permitidas para cada opción
REALESRGAN_MODELS = {
    "Anime Video v3 (Rápido, Multi-escala)": {
        "model": "realesr-animevideov3",
        "scales": ["2x", "3x", "4x"]
    },
    "x4 Plus (Fotos / General)": {
        "model": "realesrgan-x4plus",
        "scales": ["4x"]  # Solo nativo 4x
    },
    "x4 Plus Anime (Ilustraciones)": {
        "model": "realesrgan-x4plus-anime",
        "scales": ["4x"]  # Solo nativo 4x
    },
}

WAIFU2X_MODELS = {
    "CU-Net (Alta Calidad)": {
        "model": "models-cunet",
        "scales": ["1x", "2x", "4x", "8x", "16x", "32x"]
    },
    "Anime Style Art (Clásico)": {
        "model": "models-upconv_7_anime_style_art_rgb",
        "scales": ["1x", "2x", "4x", "8x", "16x", "32x"]
    },
    "Photo (Fotos Reales)": {
        "model": "models-upconv_7_photo",
        "scales": ["1x", "2x", "4x", "8x", "16x", "32x"]
    },
}

REALSR_MODELS = {
    "Estándar (DF2K)": {
        "model": "models-DF2K",
        "scales": ["4x"]
    },
    "Reparar JPEG (DF2K_JPEG)": {
        "model": "models-DF2K_JPEG",
        "scales": ["4x"]
    }
}

SRMD_MODELS = {
    "Estándar (General)": {
        "model": "models-srmd",
        "scales": ["2x", "3x", "4x"]
    }
}