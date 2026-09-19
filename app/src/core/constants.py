VIDEO_EXTENSIONS = {'mp4', 'mkv', 'webm', 'mov', 'flv', 'avi', 'gif'}
from PySide6.QtCore import QCoreApplication
AUDIO_EXTENSIONS = {'m4a', 'mp3', 'ogg', 'opus', 'flac', 'wav', 'adts', 'aac'}
SINGLE_STREAM_AUDIO_CONTAINERS = {'.mp3', '.wav', '.flac', '.ac3', '.adts', '.aac'}

# Dominios que funcionan bien con extracción plana (Modo Rápido)
FAST_MODE_SUPPORTED_DOMAINS = ["youtube.com", "youtu.be", "soundcloud.com", "x.com", "twitter.com", 
"instagram.com", "tiktok.com", "reddit.com", "facebook.com", "tumblr.com", "vimeo.com", 
"dailymotion.com", "bandcamp.com", "twitch.tv", "smugmug.com", "flickr.com", "metacafe.com", "vimeo.com", 
"archive.org", "archive.org", "archive.org", "archive.org", "archive.org", "archive.org", "archive.org"]

FORMAT_MUXER_MAP = {
    ".m4a": "mp4",
    ".wma": "asf"
}

LANG_CODE_MAP = {
    "es": QCoreApplication.translate("constants", "Español"),
    "es-419": QCoreApplication.translate("constants", "Español (Latinoamérica)"),
    "es-es": QCoreApplication.translate("constants", "Español (España)"),
    "es_la": QCoreApplication.translate("constants", "Español (Latinoamérica)"),
    "es-us": QCoreApplication.translate("constants", "Español (EE.UU.)"),
    "en": QCoreApplication.translate("constants", "Inglés"),
    "en-us": QCoreApplication.translate("constants", "Inglés (EE.UU.)"),
    "en-gb": QCoreApplication.translate("constants", "Inglés (Reino Unido)"),
    "en-orig": QCoreApplication.translate("constants", "Inglés (Original)"),
    "ja": QCoreApplication.translate("constants", "Japonés"),
    "fr": QCoreApplication.translate("constants", "Francés"),
    "de": QCoreApplication.translate("constants", "Alemán"),
    "it": QCoreApplication.translate("constants", "Italiano"),
    "pt": QCoreApplication.translate("constants", "Portugués"),
    "pt-br": QCoreApplication.translate("constants", "Portugués (Brasil)"),
    "pt-pt": QCoreApplication.translate("constants", "Portugués (Portugal)"),
    "ru": QCoreApplication.translate("constants", "Ruso"),
    "zh": QCoreApplication.translate("constants", "Chino"),
    "zh-cn": QCoreApplication.translate("constants", "Chino (Simplificado)"),
    "zh-tw": QCoreApplication.translate("constants", "Chino (Tradicional)"),
    "zh-hans": QCoreApplication.translate("constants", "Chino (Simplificado)"),
    "zh-hant": QCoreApplication.translate("constants", "Chino (Tradicional)"),
    "ko": QCoreApplication.translate("constants", "Coreano"),
    "ar": QCoreApplication.translate("constants", "Árabe"),
    "hi": QCoreApplication.translate("constants", "Hindi"),
    "iw": QCoreApplication.translate("constants", "Hebreo (código antiguo)"),
    "he": QCoreApplication.translate("constants", "Hebreo"),
    "fil": QCoreApplication.translate("constants", "Filipino"),
    "aa": QCoreApplication.translate("constants", "Afar"),
    "ab": QCoreApplication.translate("constants", "Abjasio"),
    "ae": QCoreApplication.translate("constants", "Avéstico"),
    "af": QCoreApplication.translate("constants", "Afrikáans"),
    "ak": QCoreApplication.translate("constants", "Akán"),
    "am": QCoreApplication.translate("constants", "Amárico"),
    "an": QCoreApplication.translate("constants", "Aragonés"),
    "as": QCoreApplication.translate("constants", "Asamés"),
    "av": QCoreApplication.translate("constants", "Avar"),
    "ay": QCoreApplication.translate("constants", "Aimara"),
    "az": QCoreApplication.translate("constants", "Azerí"),
    "ba": QCoreApplication.translate("constants", "Baskir"),
    "be": QCoreApplication.translate("constants", "Bielorruso"),
    "bg": QCoreApplication.translate("constants", "Búlgaro"),
    "bh": QCoreApplication.translate("constants", "Bhojpuri"),
    "bho": QCoreApplication.translate("constants", "Bhojpuri"),
    "bi": QCoreApplication.translate("constants", "Bislama"),
    "bm": QCoreApplication.translate("constants", "Bambara"),
    "bn": QCoreApplication.translate("constants", "Bengalí"),
    "bo": QCoreApplication.translate("constants", "Tibetano"),
    "br": QCoreApplication.translate("constants", "Bretón"),
    "bs": QCoreApplication.translate("constants", "Bosnio"),
    "ca": QCoreApplication.translate("constants", "Catalán"),
    "ce": QCoreApplication.translate("constants", "Checheno"),
    "ceb": QCoreApplication.translate("constants", "Cebuano"),
    "ch": QCoreApplication.translate("constants", "Chamorro"),
    "co": QCoreApplication.translate("constants", "Corso"),
    "cr": QCoreApplication.translate("constants", "Cree"),
    "cs": QCoreApplication.translate("constants", "Checo"),
    "cu": QCoreApplication.translate("constants", "Eslavo eclesiástico"),
    "cv": QCoreApplication.translate("constants", "Chuvash"),
    "cy": QCoreApplication.translate("constants", "Galés"),
    "da": QCoreApplication.translate("constants", "Danés"),
    "dv": QCoreApplication.translate("constants", "Divehi"),
    "dz": QCoreApplication.translate("constants", "Dzongkha"),
    "ee": QCoreApplication.translate("constants", "Ewe"),
    "el": QCoreApplication.translate("constants", "Griego"),
    "eo": QCoreApplication.translate("constants", "Esperanto"),
    "et": QCoreApplication.translate("constants", "Estonio"),
    "eu": QCoreApplication.translate("constants", "Euskera"),
    "fa": QCoreApplication.translate("constants", "Persa"),
    "ff": QCoreApplication.translate("constants", "Fula"),
    "fi": QCoreApplication.translate("constants", "Finlandés"),
    "fj": QCoreApplication.translate("constants", "Fiyiano"),
    "fo": QCoreApplication.translate("constants", "Feroés"),
    "fy": QCoreApplication.translate("constants", "Frisón occidental"),
    "ga": QCoreApplication.translate("constants", "Irlandés"),
    "gd": QCoreApplication.translate("constants", "Gaélico escocés"),
    "gl": QCoreApplication.translate("constants", "Gallego"),
    "gn": QCoreApplication.translate("constants", "Guaraní"),
    "gu": QCoreApplication.translate("constants", "Guyaratí"),
    "gv": QCoreApplication.translate("constants", "Manés"),
    "ha": QCoreApplication.translate("constants", "Hausa"),
    "ht": QCoreApplication.translate("constants", "Haitiano"),
    "hu": QCoreApplication.translate("constants", "Húngaro"),
    "hy": QCoreApplication.translate("constants", "Armenio"),
    "hz": QCoreApplication.translate("constants", "Herero"),
    "ia": QCoreApplication.translate("constants", "Interlingua"),
    "id": QCoreApplication.translate("constants", "Indonesio"),
    "ie": QCoreApplication.translate("constants", "Interlingue"),
    "ig": QCoreApplication.translate("constants", "Igbo"),
    "ii": QCoreApplication.translate("constants", "Yi de Sichuán"),
    "ik": QCoreApplication.translate("constants", "Inupiaq"),
    "io": QCoreApplication.translate("constants", "Ido"),
    "is": QCoreApplication.translate("constants", "Islandés"),
    "iu": QCoreApplication.translate("constants", "Inuktitut"),
    "jv": QCoreApplication.translate("constants", "Javanés"),
    "ka": QCoreApplication.translate("constants", "Georgiano"),
    "kg": QCoreApplication.translate("constants", "Kongo"),
    "ki": QCoreApplication.translate("constants", "Kikuyu"),
    "kj": QCoreApplication.translate("constants", "Kuanyama"),
    "kk": QCoreApplication.translate("constants", "Kazajo"),
    "kl": QCoreApplication.translate("constants", "Groenlandés"),
    "km": QCoreApplication.translate("constants", "Jemer"),
    "kn": QCoreApplication.translate("constants", "Canarés"),
    "kr": QCoreApplication.translate("constants", "Kanuri"),
    "ks": QCoreApplication.translate("constants", "Cachemiro"),
    "ku": QCoreApplication.translate("constants", "Kurdo"),
    "kv": QCoreApplication.translate("constants", "Komi"),
    "kw": QCoreApplication.translate("constants", "Córnico"),
    "ky": QCoreApplication.translate("constants", "Kirguís"),
    "la": QCoreApplication.translate("constants", "Latín"),
    "lb": QCoreApplication.translate("constants", "Luxemburgués"),
    "lg": QCoreApplication.translate("constants", "Ganda"),
    "li": QCoreApplication.translate("constants", "Limburgués"),
    "ln": QCoreApplication.translate("constants", "Lingala"),
    "lo": QCoreApplication.translate("constants", "Lao"),
    "lt": QCoreApplication.translate("constants", "Lituano"),
    "lu": QCoreApplication.translate("constants", "Luba-katanga"),
    "lv": QCoreApplication.translate("constants", "Letón"),
    "mg": QCoreApplication.translate("constants", "Malgache"),
    "mh": QCoreApplication.translate("constants", "Marshalés"),
    "mi": QCoreApplication.translate("constants", "Maorí"),
    "mk": QCoreApplication.translate("constants", "Macedonio"),
    "ml": QCoreApplication.translate("constants", "Malayalam"),
    "mn": QCoreApplication.translate("constants", "Mongol"),
    "mr": QCoreApplication.translate("constants", "Maratí"),
    "ms": QCoreApplication.translate("constants", "Malayo"),
    "mt": QCoreApplication.translate("constants", "Maltés"),
    "my": QCoreApplication.translate("constants", "Birmano"),
    "na": QCoreApplication.translate("constants", "Nauruano"),
    "nb": QCoreApplication.translate("constants", "Noruego bokmål"),
    "nd": QCoreApplication.translate("constants", "Ndebele del norte"),
    "ne": QCoreApplication.translate("constants", "Nepalí"),
    "ng": QCoreApplication.translate("constants", "Ndonga"),
    "nl": QCoreApplication.translate("constants", "Neerlandés"),
    "nn": QCoreApplication.translate("constants", "Noruego nynorsk"),
    "no": QCoreApplication.translate("constants", "Noruego"),
    "nr": QCoreApplication.translate("constants", "Ndebele del sur"),
    "nv": QCoreApplication.translate("constants", "Navajo"),
    "ny": QCoreApplication.translate("constants", "Chichewa"),
    "oc": QCoreApplication.translate("constants", "Occitano"),
    "oj": QCoreApplication.translate("constants", "Ojibwa"),
    "om": QCoreApplication.translate("constants", "Oromo"),
    "or": QCoreApplication.translate("constants", "Oriya"),
    "os": QCoreApplication.translate("constants", "Osético"),
    "pa": QCoreApplication.translate("constants", "Panyabí"),
    "pi": QCoreApplication.translate("constants", "Pali"),
    "pl": QCoreApplication.translate("constants", "Polaco"),
    "ps": QCoreApplication.translate("constants", "Pastún"),
    "qu": QCoreApplication.translate("constants", "Quechua"),
    "rm": QCoreApplication.translate("constants", "Romanche"),
    "rn": QCoreApplication.translate("constants", "Kirundi"),
    "ro": QCoreApplication.translate("constants", "Rumano"),
    "rw": QCoreApplication.translate("constants", "Kinyarwanda"),
    "sa": QCoreApplication.translate("constants", "Sánscrito"),
    "sc": QCoreApplication.translate("constants", "Sardo"),
    "sd": QCoreApplication.translate("constants", "Sindhi"),
    "se": QCoreApplication.translate("constants", "Sami septentrional"),
    "sg": QCoreApplication.translate("constants", "Sango"),
    "si": QCoreApplication.translate("constants", "Cingalés"),
    "sk": QCoreApplication.translate("constants", "Eslovaco"),
    "sl": QCoreApplication.translate("constants", "Esloveno"),
    "sm": QCoreApplication.translate("constants", "Samoano"),
    "sn": QCoreApplication.translate("constants", "Shona"),
    "so": QCoreApplication.translate("constants", "Somalí"),
    "sq": QCoreApplication.translate("constants", "Albanés"),
    "sr": QCoreApplication.translate("constants", "Serbio"),
    "ss": QCoreApplication.translate("constants", "Suazi"),
    "st": QCoreApplication.translate("constants", "Sesotho"),
    "su": QCoreApplication.translate("constants", "Sundanés"),
    "sv": QCoreApplication.translate("constants", "Sueco"),
    "sw": QCoreApplication.translate("constants", "Suajili"),
    "ta": QCoreApplication.translate("constants", "Tamil"),
    "te": QCoreApplication.translate("constants", "Telugu"),
    "tg": QCoreApplication.translate("constants", "Tayiko"),
    "th": QCoreApplication.translate("constants", "Tailandés"),
    "ti": QCoreApplication.translate("constants", "Tigriña"),
    "tk": QCoreApplication.translate("constants", "Turcomano"),
    "tl": QCoreApplication.translate("constants", "Tagalo"),
    "tn": QCoreApplication.translate("constants", "Setsuana"),
    "to": QCoreApplication.translate("constants", "Tongano"),
    "tr": QCoreApplication.translate("constants", "Turco"),
    "ts": QCoreApplication.translate("constants", "Tsonga"),
    "tt": QCoreApplication.translate("constants", "Tártaro"),
    "tw": QCoreApplication.translate("constants", "Twi"),
    "ty": QCoreApplication.translate("constants", "Tahitiano"),
    "ug": QCoreApplication.translate("constants", "Uigur"),
    "uk": QCoreApplication.translate("constants", "Ucraniano"),
    "ur": QCoreApplication.translate("constants", "Urdu"),
    "uz": QCoreApplication.translate("constants", "Uzbeko"),
    "ve": QCoreApplication.translate("constants", "Venda"),
    "vi": QCoreApplication.translate("constants", "Vietnamita"),
    "vo": QCoreApplication.translate("constants", "Volapük"),
    "wa": QCoreApplication.translate("constants", "Valón"),
    "wo": QCoreApplication.translate("constants", "Wolof"),
    "xh": QCoreApplication.translate("constants", "Xhosa"),
    "yi": QCoreApplication.translate("constants", "Yidis"),
    "yo": QCoreApplication.translate("constants", "Yoruba"),
    "za": QCoreApplication.translate("constants", "Zhuang"),
    "zu": QCoreApplication.translate("constants", "Zulú"),
    "und": QCoreApplication.translate("constants", "No especificado"),
    "alb-al": QCoreApplication.translate("constants", "Albanés (Albania)"),
    "ara-sa": QCoreApplication.translate("constants", "Árabe (Arabia Saudita)"),
    "aze-az": QCoreApplication.translate("constants", "Azerí (Azerbaiyán)"),
    "ben-bd": QCoreApplication.translate("constants", "Bengalí (Bangladesh)"),
    "bul-bg": QCoreApplication.translate("constants", "Búlgaro (Bulgaria)"),
    "cat-es": QCoreApplication.translate("constants", "Catalán (España)"),
    "ces-cz": QCoreApplication.translate("constants", "Checo (República Checa)"),
    "cmn-hans-cn": QCoreApplication.translate("constants", "Chino Mandarín (Simplificado, China)"),
    "cmn-hant-cn": QCoreApplication.translate("constants", "Chino Mandarín (Tradicional, China)"),
    "crs": QCoreApplication.translate("constants", "Francés criollo seselwa"),
    "dan-dk": QCoreApplication.translate("constants", "Danés (Dinamarca)"),
    "deu-de": QCoreApplication.translate("constants", "Alemán (Alemania)"),
    "ell-gr": QCoreApplication.translate("constants", "Griego (Grecia)"),
    "est-ee": QCoreApplication.translate("constants", "Estonio (Estonia)"),
    "fil-ph": QCoreApplication.translate("constants", "Filipino (Filipinas)"),
    "fin-fi": QCoreApplication.translate("constants", "Finlandés (Finlandia)"),
    "fra-fr": QCoreApplication.translate("constants", "Francés (Francia)"),
    "gaa": QCoreApplication.translate("constants", "Ga"),
    "gle-ie": QCoreApplication.translate("constants", "Irlandés (Irlanda)"),
    "haw": QCoreApplication.translate("constants", "Hawaiano"),
    "heb-il": QCoreApplication.translate("constants", "Hebreo (Israel)"),
    "hin-in": QCoreApplication.translate("constants", "Hindi (India)"),
    "hmn": QCoreApplication.translate("constants", "Hmong"),
    "hrv-hr": QCoreApplication.translate("constants", "Croata (Croacia)"),
    "hun-hu": QCoreApplication.translate("constants", "Húngaro (Hungría)"),
    "ind-id": QCoreApplication.translate("constants", "Indonesio (Indonesia)"),
    "isl-is": QCoreApplication.translate("constants", "Islandés (Islandia)"),
    "ita-it": QCoreApplication.translate("constants", "Italiano (Italia)"),
    "jav-id": QCoreApplication.translate("constants", "Javanés (Indonesia)"),
    "jpn-jp": QCoreApplication.translate("constants", "Japonés (Japón)"),
    "kaz-kz": QCoreApplication.translate("constants", "Kazajo (Kazajistán)"),
    "kha": QCoreApplication.translate("constants", "Khasi"),
    "khm-kh": QCoreApplication.translate("constants", "Jemer (Camboya)"),
    "kor-kr": QCoreApplication.translate("constants", "Coreano (Corea del Sur)"),
    "kri": QCoreApplication.translate("constants", "Krio"),
    "lav-lv": QCoreApplication.translate("constants", "Letón (Letonia)"),
    "lit-lt": QCoreApplication.translate("constants", "Lituano (Lituania)"),
    "lua": QCoreApplication.translate("constants", "Luba-Lulua"),
    "luo": QCoreApplication.translate("constants", "Luo"),
    "mfe": QCoreApplication.translate("constants", "Morisyen"),
    "msa-my": QCoreApplication.translate("constants", "Malayo (Malasia)"),
    "mya-mm": QCoreApplication.translate("constants", "Birmano (Myanmar)"),
    "new": QCoreApplication.translate("constants", "Newari"),
    "nld-nl": QCoreApplication.translate("constants", "Neerlandés (Países Bajos)"),
    "nob-no": QCoreApplication.translate("constants", "Noruego Bokmål (Noruega)"),
    "nso": QCoreApplication.translate("constants", "Sotho del norte"),
    "pam": QCoreApplication.translate("constants", "Pampanga"),
    "pol-pl": QCoreApplication.translate("constants", "Polaco (Polonia)"),
    "por-pt": QCoreApplication.translate("constants", "Portugués (Portugal)"),
    "ron-ro": QCoreApplication.translate("constants", "Rumano (Rumania)"),
    "rus-ru": QCoreApplication.translate("constants", "Ruso (Rusia)"),
    "slk-sk": QCoreApplication.translate("constants", "Eslovaco (Eslovaquia)"),
    "slv-si": QCoreApplication.translate("constants", "Esloveno (Eslovenia)"),
    "spa-es": QCoreApplication.translate("constants", "Español (España)"),
    "swa-sw": QCoreApplication.translate("constants", "Suajili"),
    "swe-se": QCoreApplication.translate("constants", "Sueco (Suecia)"),
    "tha-th": QCoreApplication.translate("constants", "Tailandés (Tailandia)"),
    "tum": QCoreApplication.translate("constants", "Tumbuka"),
    "tur-tr": QCoreApplication.translate("constants", "Turco (Turquía)"),
    "ukr-ua": QCoreApplication.translate("constants", "Ucraniano (Ucrania)"),
    "urd-pk": QCoreApplication.translate("constants", "Urdu (Pakistán)"),
    "uzb-uz": QCoreApplication.translate("constants", "Uzbeko (Uzbekistán)"),
    "vie-vn": QCoreApplication.translate("constants", "Vietnamita (Vietnam)"),
    "war": QCoreApplication.translate("constants", "Waray"),
    "alb": QCoreApplication.translate("constants", "Albanés"),
    "ara": QCoreApplication.translate("constants", "Árabe"),
    "aze": QCoreApplication.translate("constants", "Azerí"),
    "ben": QCoreApplication.translate("constants", "Bengalí"),
    "bul": QCoreApplication.translate("constants", "Búlgaro"),
    "cat": QCoreApplication.translate("constants", "Catalán"),
    "ces": QCoreApplication.translate("constants", "Checo"),
    "cmn": QCoreApplication.translate("constants", "Chino Mandarín"),
    "dan": QCoreApplication.translate("constants", "Danés"),
    "deu": QCoreApplication.translate("constants", "Alemán"),
    "ell": QCoreApplication.translate("constants", "Griego"),
    "est": QCoreApplication.translate("constants", "Estonio"),
    "fin": QCoreApplication.translate("constants", "Finlandés"),
    "fra": QCoreApplication.translate("constants", "Francés"),
    "gle": QCoreApplication.translate("constants", "Irlandés"),
    "heb": QCoreApplication.translate("constants", "Hebreo"),
    "hin": QCoreApplication.translate("constants", "Hindi"),
    "hrv": QCoreApplication.translate("constants", "Croata"),
    "hun": QCoreApplication.translate("constants", "Húngaro"),
    "ind": QCoreApplication.translate("constants", "Indonesio"),
    "isl": QCoreApplication.translate("constants", "Islandés"),
    "ita": QCoreApplication.translate("constants", "Italiano"),
    "jav": QCoreApplication.translate("constants", "Javanés"),
    "jpn": QCoreApplication.translate("constants", "Japonés"),
    "kaz": QCoreApplication.translate("constants", "Kazajo"),
    "khm": QCoreApplication.translate("constants", "Jemer"),
    "kor": QCoreApplication.translate("constants", "Coreano"),
    "lav": QCoreApplication.translate("constants", "Letón"),
    "lit": QCoreApplication.translate("constants", "Lituano"),
    "msa": QCoreApplication.translate("constants", "Malayo"),
    "mya": QCoreApplication.translate("constants", "Birmano"),
    "nld": QCoreApplication.translate("constants", "Neerlandés"),
    "nob": QCoreApplication.translate("constants", "Noruego Bokmål"),
    "pol": QCoreApplication.translate("constants", "Polaco"),
    "por": QCoreApplication.translate("constants", "Portugués"),
    "ron": QCoreApplication.translate("constants", "Rumano"),
    "rus": QCoreApplication.translate("constants", "Ruso"),
    "slk": QCoreApplication.translate("constants", "Eslovaco"),
    "slv": QCoreApplication.translate("constants", "Esloveno"),
    "spa": QCoreApplication.translate("constants", "Español"),
    "swe": QCoreApplication.translate("constants", "Sueco"),
    "swa": QCoreApplication.translate("constants", "Suajili"),
    "tha": QCoreApplication.translate("constants", "Tailandés"),
    "tur": QCoreApplication.translate("constants", "Turco"),
    "ukr": QCoreApplication.translate("constants", "Ucraniano"),
    "urd": QCoreApplication.translate("constants", "Urdu"),
    "uzb": QCoreApplication.translate("constants", "Uzbeko"),
    "vie": QCoreApplication.translate("constants", "Vietnamita"),
}

LANGUAGE_ORDER = {
    'en': 0,       # Inglés (General)
    'en-us': 1,    # Inglés EE.UU.
    'en-gb': 2,    # Inglés UK
    'en-orig': 3,  # Inglés (Original)
    'es': 4,       # Español (General)
    'es-419': 5,   # Español LATAM
    'es-es': 6,    # Español España
    'es_la': 7,    # Español (Latinoamérica)
    'es-us': 8,    # Español (EE.UU.)
    'ja': 9,       # Japonés 
    'fr': 10,       # Francés 
    'de': 11,      # Alemán 
    'pt': 12,      # Portugués
    'it': 13,      # Italiano
    'zh': 14,      # Chino
    'ko': 15,      # Coreano
    'ru': 16,      # Ruso
    'ar': 17,      # Árabe
    'hi': 18,      # Hindi
    'vi': 19,      # Vietnamita
    'th': 20,      # Tailandés
    'pl': 21,      # Polaco
    'id': 22,      # Indonesio
    'tr': 23,      # Turco
    'bn': 24,      # Bengalí
    'ta': 25,      # Tamil
    'te': 26,      # Telugu
    'pa': 27,      # Punjabi
    'mr': 28,      # Marathi
    'ca': 29,      # Catalán
    'gl': 30,      # Gallego
    'eu': 31,      # Euskera
    'und': 32,     # Indefinido
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
    ".wav": { "video": [], "audio": ["pcm_s16le", "pcm_s24le"] },
    ".adts": { "video": [], "audio": ["aac"] },
    ".aac": { "video": [], "audio": ["aac"] }
}

# --- NUEVO: Definir formatos RAW ---
IMAGE_RAW_FORMATS = {".CR2", ".DNG", ".ARW", ".NEF", ".ORF", ".RW2", ".SR2", ".RAF", ".CR3", ".PEF"}
# --- CONSTANTES DE HERRAMIENTAS DE IMAGEN ---

# Actualizar los formatos de entrada permitidos sumando los RAW
IMAGE_INPUT_FORMATS = {".svg", ".eps", ".ai", ".pdf", ".ps"}.union(IMAGE_RAW_FORMATS)
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
    QCoreApplication.translate("constants", "Lanczos (Mejor Calidad)"): "LANCZOS",
    QCoreApplication.translate("constants", "Bicúbico (Rápido)"): "BICUBIC",
    QCoreApplication.translate("constants", "Bilineal (Muy Rápido)"): "BILINEAR",
    QCoreApplication.translate("constants", "Nearest (Pixelado)"): "NEAREST",
}

# --- CONSTANTES DE PLACEHOLDERS (IA) ---
AI_FAMILY_HOLDER = QCoreApplication.translate("constants", "Seleccione la familia...")
AI_ENGINE_HOLDER = QCoreApplication.translate("constants", "Seleccione el motor...")
AI_MODEL_HOLDER = QCoreApplication.translate("constants", "Seleccione el modelo...")

# Opciones de Canvas
CANVAS_OPTIONS = [
    "Sin ajuste",
    "Añadir Margen Externo",
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
    QCoreApplication.translate("constants", "Color Sólido"),
    QCoreApplication.translate("constants", "Degradado"),
    QCoreApplication.translate("constants", "Imagen de Fondo")
]

GRADIENT_DIRECTIONS = [
    QCoreApplication.translate("constants", "Horizontal (Izq → Der)"),
    QCoreApplication.translate("constants", "Vertical (Arr → Aba)"),
    QCoreApplication.translate("constants", "Diagonal (↘)"),
    QCoreApplication.translate("constants", "Diagonal (↙)"),
    QCoreApplication.translate("constants", "Radial (Centro)")
]

# Los formatos que soportan transparencia ya están definidos arriba.

# Catálogo de modelos rembg -- cada entrada es un "perfil" autocontenido: además
# de file/url/folder (descarga, ver models_setup.py), declara "input_size" (lado
# del cuadrado NxN que espera el modelo como entrada). Esto es a propósito: el
# motor de inferencia (core/tabs/image_tools/rembg_engine.py) NO tiene ningún
# if/elif por nombre de modelo -- lee "input_size" de aquí y ya sabe cómo correr
# cualquier entrada de este diccionario. Agregar un modelo nuevo es agregar una
# entrada con su input_size correcto, no tocar el motor. Todos comparten el
# mismo contrato entrada/salida (RGB -> máscara de 1 canal, normalización
# ImageNet) porque son arquitecturas de segmentación de la misma familia --
# si algún día entra un modelo con un contrato distinto, es el momento de
# sumarle un campo nuevo aquí, no de volver a bifurcar el motor por nombre.
#
# "size_bytes" es el peso REAL del archivo a descargar, medido con un HEAD a su
# URL (Content-Length) contra los releases de GitHub/HuggingFace -- no una
# estimación. Sirve para avisar cuánto pesa ANTES de bajarlo, tanto en Ajustes >
# Modelos como en el diálogo de descarga que sale al elegir un modelo que no está
# instalado desde los popovers del Editor de Imagen (ver
# gui/widgets/model_download_prompt.py). Si algún día se cambia una URL por otra
# versión del mismo modelo, hay que volver a medir este número: un valor viejo no
# rompe la descarga (el porcentaje real sale del Content-Length de la respuesta),
# pero le miente al usuario en el diálogo. Los modelos de RMBG 2.0 marcados como
# gated (URL a una página de HuggingFace, no a un archivo) llevan el tamaño que
# declara la API de HuggingFace para ese archivo.
REMBG_MODEL_FAMILIES = {
    QCoreApplication.translate("constants", "Rembg Standard (U2Net)"): {
        QCoreApplication.translate("constants", "isnet-general-use (Recomendado)"): {
            "file": "isnet-general-use.onnx",
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-general-use.onnx",
            "folder": "rembg",
            "size_bytes": 178648008,
            "input_size": (1024, 1024)
        },
        QCoreApplication.translate("constants", "u2netp (Rápido)"): {
            "file": "u2netp.onnx",
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx",
            "folder": "rembg",
            "size_bytes": 4574861,
            "input_size": (320, 320)
        },
        QCoreApplication.translate("constants", "u2net (Alta Precisión)"): {
            "file": "u2net.onnx",
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx",
            "folder": "rembg",
            "size_bytes": 175997641,
            "input_size": (320, 320)
        },
        QCoreApplication.translate("constants", "u2net_human_seg (Humanos)"): {
            "file": "u2net_human_seg.onnx",
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net_human_seg.onnx",
            "folder": "rembg",
            "size_bytes": 175997641,
            "input_size": (320, 320)
        },
        QCoreApplication.translate("constants", "isnet-anime (Anime)"): {
            "file": "isnet-anime.onnx",
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-anime.onnx",
            "folder": "rembg",
            "size_bytes": 176069933,
            "input_size": (1024, 1024)
        }
    },
    QCoreApplication.translate("constants", "BiRefNet (Next-Gen 2024)"): {
        # --- MODELOS GENERALES ---
        QCoreApplication.translate("constants", "General (Estándar)"): {
            "file": "birefnet-general.onnx",  # ✅ Nombre que rembg espera
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-general-epoch_244.onnx",
            "folder": "rembg",
            "size_bytes": 972666916,
            "input_size": (1024, 1024)
        },
        QCoreApplication.translate("constants", "General Lite (Rápido)"): {
            "file": "birefnet-general-lite.onnx",  # ✅ Cambiado
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx",
            "folder": "rembg",
            "size_bytes": 224005088,
            "input_size": (1024, 1024)
        },

        # --- ESPECIALIZADOS ---
        QCoreApplication.translate("constants", "Portrait (Retratos)"): {
            "file": "birefnet-portrait.onnx",  # ✅ Cambiado
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-portrait-epoch_150.onnx",
            "folder": "rembg",
            "size_bytes": 972666916,
            "input_size": (1024, 1024)
        },
        QCoreApplication.translate("constants", "DIS (Bordes Finos/Complejo)"): {
            "file": "birefnet-dis.onnx",  # ✅ Cambiado
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-DIS-epoch_590.onnx",
            "folder": "rembg",
            "size_bytes": 972666916,
            "input_size": (1024, 1024)
        },
        QCoreApplication.translate("constants", "COD (Objetos Camuflados)"): {
            "file": "birefnet-cod.onnx",  # ✅ Cambiado
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-COD-epoch_125.onnx",
            "folder": "rembg",
            "size_bytes": 972666916,
            "input_size": (1024, 1024)
        },
        QCoreApplication.translate("constants", "HRSOD (Alta Detección)"): {
            "file": "birefnet-hrsod.onnx",  # ✅ Cambiado
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-HRSOD_DHU-epoch_115.onnx",
            "folder": "rembg",
            "size_bytes": 972666916,
            "input_size": (1024, 1024)
        },

        # --- ALTA RESOLUCIÓN (HR) & MASIVOS ---
        QCoreApplication.translate("constants", "Massive (Entrenamiento Masivo)"): {
            "file": "birefnet-massive.onnx",  # ✅ Cambiado
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-massive-TR_DIS5K_TR_TEs-epoch_420.onnx",
            "folder": "rembg",
            "size_bytes": 972666916,
            "input_size": (1024, 1024)
        },
        QCoreApplication.translate("constants", "HR General (4K/8K)"): {
            "file": "birefnet-hr-general.onnx",  # ✅ Cambiado
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet_HR-general-epoch_130.onnx",
            "folder": "rembg",
            "size_bytes": 1098928953,
            "input_size": (1024, 1024)
        },
        QCoreApplication.translate("constants", "HR Matting (Recorte Ultra Fino)"): {
            "file": "birefnet-hr-matting.onnx",  # ✅ Cambiado
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet_HR-matting-epoch_135.onnx",
            "folder": "rembg",
            "size_bytes": 1098928867,
            "input_size": (1024, 1024)
        }
    },

    # --- NUEVO BLOQUE: RMBG 2.0 (Descarga Manual) ---
    QCoreApplication.translate("constants", "RMBG 2.0 (BriaAI)"): {
        QCoreApplication.translate("constants", "Standard (Automático)"): {
            "file": "rmbg2_gatis.onnx",
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/bria-rmbg-2.0.onnx",
            "folder": "rmbg2",
            "size_bytes": 1024331469,
            "input_size": (1024, 1024)
        },
        QCoreApplication.translate("constants", "Standard (Manual)"): {
            "file": "model.onnx",
            "url": "https://huggingface.co/briaai/RMBG-2.0/tree/main/onnx",
            "folder": "rmbg2",
            "size_bytes": 1024331469,
            "input_size": (1024, 1024)
        },
        QCoreApplication.translate("constants", "BnB4 (Recomendado)"): {
            "file": "model_bnb4.onnx",
            "url": "https://huggingface.co/briaai/RMBG-2.0/tree/main/onnx",
            "folder": "rmbg2",
            "size_bytes": 355288046,
            "input_size": (1024, 1024)
        },
        QCoreApplication.translate("constants", "FP16 (Media)"): {
            "file": "model_fp16.onnx",
            "url": "https://huggingface.co/briaai/RMBG-2.0/tree/main/onnx",
            "folder": "rmbg2",
            "size_bytes": 513576499,
            "input_size": (1024, 1024)
        },
        QCoreApplication.translate("constants", "Int8 (Rápido)"): {
            "file": "model_int8.onnx",
            "url": "https://huggingface.co/briaai/RMBG-2.0/tree/main/onnx",
            "folder": "rmbg2",
            "size_bytes": 366087445,
            "input_size": (1024, 1024)
        },
        "Quantized": {
            "file": "model_quantized.onnx",
            "url": "https://huggingface.co/briaai/RMBG-2.0/tree/main/onnx",
            "folder": "rmbg2",
            "size_bytes": 366087549,
            "input_size": (1024, 1024)
        }
    },

    QCoreApplication.translate("constants", "InSPyReNet (Ultra High Resolution)"): {
        QCoreApplication.translate("constants", "SwinB Plus Ultra (FP32)"): {
            "file": "inspyrenet_ultra.onnx",
            "url": "https://huggingface.co/OS-Software/InSPyReNet-SwinB-Plus-Ultra-ONNX/resolve/main/onnx/model.onnx?download=true",
            "folder": "inspyrenet",
            "size_bytes": 395316574,
            "input_size": (1024, 1024)
        },
        QCoreApplication.translate("constants", "SwinB Plus Ultra (FP16)"): {
            "file": "inspyrenet_ultra_fp16.onnx",
            "url": "https://huggingface.co/OS-Software/InSPyReNet-SwinB-Plus-Ultra-ONNX/resolve/main/onnx/model_fp16.onnx?download=true",
            "folder": "inspyrenet",
            "size_bytes": 199133027,
            "input_size": (1024, 1024)
        }
    }
}

# Catálogo de modelos de Mapa de Profundidad -- mismo criterio de "perfil
# autocontenido" que REMBG_MODEL_FAMILIES: el motor (core/tabs/image_tools/
# depth_engine.py) no tiene ningún if por nombre de modelo, todo lo que cambia
# entre modelos se declara aquí. Todos se probaron con DowP (onnxruntime 1.24,
# CPU y DirectML sobre una RTX 3060, 2026-09-19) antes de entrar al catálogo.
#
# Campos propios de estos modelos (además de file/url/folder/size_bytes):
#   - "extra_files": archivos que tienen que vivir junto al .onnx. Los Depth
#     Anything 3 de onnx-community guardan los pesos en un model.onnx_data
#     aparte, y el .onnx lo busca por ESE nombre exacto -- no se puede renombrar,
#     por eso cada modelo tiene su propia carpeta.
#   - "input_layout": "4d" = [lote, 3, alto, ancho]; "5d" = [lote, n_imágenes,
#     3, alto, ancho] (DA3 es multivista, aquí siempre se le pasa una imagen).
#   - "output_kind": "disparity" = cerca es un valor ALTO (DA2 y derivados);
#     "depth" = cerca es un valor BAJO (DA3), el motor lo pasa a 1/d para
#     entregar siempre la misma convención (cerca = blanco).
#   - "process_mode"/"process_size": "short_side" escala el lado corto a
#     process_size manteniendo la proporción (múltiplos de 14, lo que pide el
#     ViT); "square" aplasta a process_size x process_size. Los Distill-Any-Depth
#     de esta conversión se exportaron con tamaño FIJO (su segunda salida trae
#     1369 = 37x37 parches), así que cualquier otra proporción falla al correr.
#     La resolución de proceso NO se deja subir desde la UI a propósito: en la
#     prueba, DA3 Base a 1036 px en DirectML devolvió basura sin lanzar ningún
#     error (en CPU salía bien), y la VRAM pasaba de 3 a 10 GB.
#
# "size_bytes" es el peso real de cada archivo (medido contra el archivo
# descargado de cada URL); el peso que ve el usuario es la suma con extra_files.
_DEPTH_ANYTHING_URL = "https://huggingface.co/onnx-community/{0}/resolve/main/onnx/{1}"
_DEPTH_ANYTHING_V1_URL = "https://huggingface.co/Xenova/depth-anything-large-hf/resolve/main/onnx/{0}"

# Licencia de los pesos de cada modelo, tal como la declara el repositorio ORIGINAL (no la
# conversión ONNX, que a veces copia la etiqueta de otra variante: la conversión de DA3
# Large dice Apache y deriva de un checkpoint CC BY-NC). Verificada en la API de Hugging
# Face y en los repositorios oficiales el 2026-09-19. Solo se MUESTRA (etiqueta pequeña
# en el popover y en Ajustes > Modelos, y una nota al descargar): DowP no aloja ningún
# peso, cada usuario los baja directamente de Hugging Face. "license_note", si existe,
# es una aclaración que sale como tooltip de esa etiqueta.
LICENSE_APACHE = "Apache 2.0"
LICENSE_MIT = "MIT"
LICENSE_CC_NC = "CC BY-NC 4.0"

DEPTH_MODEL_FAMILIES = {
    "Depth Anything V2": {
        QCoreApplication.translate("constants", "Small (Recomendado)"): {
            "file": "model.onnx",
            "url": _DEPTH_ANYTHING_URL.format("depth-anything-v2-small", "model.onnx"),
            "folder": "depth/da2-small",
            "size_bytes": 99060839,
            "license": LICENSE_APACHE,
            "input_layout": "4d",
            "output_kind": "disparity",
            "process_mode": "short_side",
            "process_size": 518,
        },
        QCoreApplication.translate("constants", "Small FP16 (Ligero, ideal con GPU)"): {
            "file": "model_fp16.onnx",
            "url": _DEPTH_ANYTHING_URL.format("depth-anything-v2-small", "model_fp16.onnx"),
            "folder": "depth/da2-small",
            "size_bytes": 49642442,
            "license": LICENSE_APACHE,
            "input_layout": "4d",
            "output_kind": "disparity",
            "process_mode": "short_side",
            "process_size": 518,
        },
        QCoreApplication.translate("constants", "Base"): {
            "file": "model.onnx",
            "url": _DEPTH_ANYTHING_URL.format("depth-anything-v2-base", "model.onnx"),
            "folder": "depth/da2-base",
            "size_bytes": 388917010,
            "license": LICENSE_CC_NC,
            "input_layout": "4d",
            "output_kind": "disparity",
            "process_mode": "short_side",
            "process_size": 518,
        },
        QCoreApplication.translate("constants", "Base FP16 (Ligero, ideal con GPU)"): {
            "file": "model_fp16.onnx",
            "url": _DEPTH_ANYTHING_URL.format("depth-anything-v2-base", "model_fp16.onnx"),
            "folder": "depth/da2-base",
            "size_bytes": 194570657,
            "license": LICENSE_CC_NC,
            "input_layout": "4d",
            "output_kind": "disparity",
            "process_mode": "short_side",
            "process_size": 518,
        },
        QCoreApplication.translate("constants", "Large"): {
            "file": "model.onnx",
            "url": _DEPTH_ANYTHING_URL.format("depth-anything-v2-large", "model.onnx"),
            "folder": "depth/da2-large",
            "size_bytes": 1336922232,
            "license": LICENSE_CC_NC,
            "input_layout": "4d",
            "output_kind": "disparity",
            "process_mode": "short_side",
            "process_size": 518,
        },
        QCoreApplication.translate("constants", "Large FP16 (Ligero, ideal con GPU)"): {
            "file": "model_fp16.onnx",
            "url": _DEPTH_ANYTHING_URL.format("depth-anything-v2-large", "model_fp16.onnx"),
            "folder": "depth/da2-large",
            "size_bytes": 668656405,
            "license": LICENSE_CC_NC,
            "input_layout": "4d",
            "output_kind": "disparity",
            "process_mode": "short_side",
            "process_size": 518,
        },
    },
    "Depth Anything 3": {
        QCoreApplication.translate("constants", "Small (Rápido)"): {
            "file": "model.onnx",
            "url": _DEPTH_ANYTHING_URL.format("depth-anything-v3-small", "model.onnx"),
            "folder": "depth/da3-small",
            "size_bytes": 640691,
            "extra_files": [
                {"file": "model.onnx_data",
                 "url": _DEPTH_ANYTHING_URL.format("depth-anything-v3-small", "model.onnx_data"),
                 "size_bytes": 104702464},
            ],
            "license": LICENSE_APACHE,
            "input_layout": "5d",
            "output_kind": "depth",
            "process_mode": "short_side",
            "process_size": 518,
        },
        QCoreApplication.translate("constants", "Base (Separa mejor los planos)"): {
            "file": "model.onnx",
            "url": _DEPTH_ANYTHING_URL.format("depth-anything-v3-base", "model.onnx"),
            "folder": "depth/da3-base",
            "size_bytes": 646912,
            "extra_files": [
                {"file": "model.onnx_data",
                 "url": _DEPTH_ANYTHING_URL.format("depth-anything-v3-base", "model.onnx_data"),
                 "size_bytes": 412068352},
            ],
            "license": LICENSE_APACHE,
            "input_layout": "5d",
            "output_kind": "depth",
            "process_mode": "short_side",
            "process_size": 518,
        },
        QCoreApplication.translate("constants", "Large (Más potente)"): {
            "file": "model.onnx",
            "url": _DEPTH_ANYTHING_URL.format("depth-anything-v3-large", "model.onnx"),
            "folder": "depth/da3-large",
            "size_bytes": 1093118,
            "extra_files": [
                {"file": "model.onnx_data",
                 "url": _DEPTH_ANYTHING_URL.format("depth-anything-v3-large", "model.onnx_data"),
                 "size_bytes": 1381741568},
            ],
            "license": LICENSE_CC_NC,
            "license_note": QCoreApplication.translate(
                "constants",
                "La conversión ONNX indica Apache 2.0, pero deriva del modelo DA3-Large "
                "original, que es CC BY-NC 4.0."),
            "input_layout": "5d",
            "output_kind": "depth",
            "process_mode": "short_side",
            "process_size": 518,
        },
    },
    "Depth Anything V1": {
        QCoreApplication.translate("constants", "Large"): {
            "file": "model.onnx",
            "url": _DEPTH_ANYTHING_V1_URL.format("model.onnx"),
            "folder": "depth/da1-large",
            "size_bytes": 1337136946,
            "license": LICENSE_APACHE,
            "input_layout": "4d",
            "output_kind": "disparity",
            "process_mode": "short_side",
            "process_size": 518,
        },
        QCoreApplication.translate("constants", "Large FP16 (Ligero, ideal con GPU)"): {
            "file": "model_fp16.onnx",
            "url": _DEPTH_ANYTHING_V1_URL.format("model_fp16.onnx"),
            "folder": "depth/da1-large",
            "size_bytes": 669066744,
            "license": LICENSE_APACHE,
            "input_layout": "4d",
            "output_kind": "disparity",
            "process_mode": "short_side",
            "process_size": 518,
        },
    },
    "Distill-Any-Depth": {
        QCoreApplication.translate("constants", "Base (Más relieve)"): {
            "file": "model.onnx",
            "url": "https://huggingface.co/FuryTMP/Distill-Any-Depth-Base-onnx/resolve/main/Distill%20Any%20Depth%20Base/model.onnx",
            "folder": "depth/dad-base",
            "size_bytes": 388874697,
            "license": LICENSE_MIT,
            "input_layout": "4d",
            "output_kind": "disparity",
            "process_mode": "square",
            "process_size": 518,
        },
        QCoreApplication.translate("constants", "Large (Máximo detalle)"): {
            "file": "model.onnx",
            "url": "https://huggingface.co/FuryTMP/Distill-Any-Depth-Large-onnx/resolve/main/Distill%20Any%20Depth%20Large/model.onnx",
            "folder": "depth/dad-large",
            "size_bytes": 1336858580,
            "license": LICENSE_MIT,
            "input_layout": "4d",
            "output_kind": "disparity",
            "process_mode": "square",
            "process_size": 518,
        },
    },
}

UPSCALING_TOOLS = {
    "Waifu2x": {
        "name": "Waifu2x",
        "folder": "waifu2x",
        # exe/url por plataforma -- ver core/setup/models_setup.py:_platform_value().
        # Mismo release (20250915), un asset .zip distinto por SO en GitHub.
        "exe": {
            "windows": "waifu2x-ncnn-vulkan.exe",
            "macos": "waifu2x-ncnn-vulkan",
            "linux": "waifu2x-ncnn-vulkan",
        },
        "url": {
            "windows": "https://github.com/nihui/waifu2x-ncnn-vulkan/releases/download/20250915/waifu2x-ncnn-vulkan-20250915-windows.zip",
            "macos": "https://github.com/nihui/waifu2x-ncnn-vulkan/releases/download/20250915/waifu2x-ncnn-vulkan-20250915-macos.zip",
            "linux": "https://github.com/nihui/waifu2x-ncnn-vulkan/releases/download/20250915/waifu2x-ncnn-vulkan-20250915-linux.zip",
        },
        "size_bytes": {
            "windows": 35497352,
            "macos": 41706129,
            "linux": 36658685,
        },
    },
    "SRMD": {
        "name": "SRMD",
        "folder": "srmd",
        "exe": {
            "windows": "srmd-ncnn-vulkan.exe",
            "macos": "srmd-ncnn-vulkan",
            "linux": "srmd-ncnn-vulkan",
        },
        "url": {
            "windows": "https://github.com/nihui/srmd-ncnn-vulkan/releases/download/20220728/srmd-ncnn-vulkan-20220728-windows.zip",
            "macos": "https://github.com/nihui/srmd-ncnn-vulkan/releases/download/20220728/srmd-ncnn-vulkan-20220728-macos.zip",
            "linux": "https://github.com/nihui/srmd-ncnn-vulkan/releases/download/20220728/srmd-ncnn-vulkan-20220728-ubuntu.zip",
        },
        "size_bytes": {
            "windows": 19208707,
            "macos": 24612116,
            "linux": 19716383,
        },
    },
    "Upscayl": {
        "name": "Upscayl (Global Engine)",
        "folder": "upscayl",
        "exe": {
            "windows": "upscayl-bin.exe",
            "macos": "upscayl-bin",
            "linux": "upscayl-bin",
        },
        "url": {
            "windows": "https://github.com/upscayl/upscayl-ncnn/releases/download/20251207-174704/upscayl-bin-20251207-174704-windows.zip",
            "macos": "https://github.com/upscayl/upscayl-ncnn/releases/download/20251207-174704/upscayl-bin-20251207-174704-macos.zip",
            "linux": "https://github.com/upscayl/upscayl-ncnn/releases/download/20251207-174704/upscayl-bin-20251207-174704-linux.zip",
        },
        "size_bytes": {
            "windows": 2421760,
            "macos": 9338240,
            "linux": 3952825,
        },
        "models_size_bytes": 319059567,
        # Modelos (custom-models): mismo zip para los tres SO, no cambia.
        "models_url": "https://github.com/upscayl/custom-models/archive/refs/heads/main.zip"
    }
}

# --- NOTA: soporte EPS/PS en ImageConverter ---
# EPS/PS (PostScript puro, pre-PDF) necesita un intérprete real -- no existe
# equivalente puro-pip multiplataforma (a diferencia de SVG/PDF/AI, que se
# resuelven con resvg_py/pypdfium2 sin binarios externos). En Windows, Ghostscript
# es una dependencia OPCIONAL (Ajustes > Dependencias, no se descarga sola) --
# ver core/setup/ghostscript_setup.py para el detalle de cómo se instala (el
# release oficial es un instalador NSIS, no un zip portable, y desde la 10.01.0
# no admite instalación silenciosa -- se extrae con 7-Zip sin ejecutarlo) y
# core/tabs/image_tools/image_converter.py::_load_eps_ps para la conversión en
# sí (EPS/PS -> PDF temporal vía Ghostscript, reusando el renderizador PDF ya
# existente).
#
# En Linux/macOS no hay build bundleable (Linux: paquete Snap, no un tarball
# suelto; macOS: sin build precompilado) -- en vez de bundlear, se detecta un
# Ghostscript ya instalado por el propio usuario (binario `gs`, típicamente a
# un `apt install ghostscript` / `brew install ghostscript` de distancia,
# ver ghostscript_setup.py::_find_system_gs/get_install_info) y se habilita
# EPS/PS ahí si existe. La tarjeta de Ajustes > Dependencias (deps_page.py::
# GhostscriptCardPanel) le sugiere al usuario el comando correcto según el SO
# y el gestor de paquetes detectado, con un botón para copiarlo y otro para
# re-verificar tras instalarlo a mano (no hay forma de automatizar la
# instalación en sí: brew/apt piden sudo/interacción de terminal).

# --- MAPEOC DE NOMBRES AMIGABLES PARA UPSCAYL ---
# Upscayl es deliberadamente "más global" que solo el repo custom-models -- DowP1 ya
# sumaba modelos de otras 2 fuentes (ver setup.pyc decompilado,
# check_and_download_upscaling_tools/_UPSCAYL_LEGACY_MODEL_SOURCES en
# core/setup/models_setup.py): realesrgan-x4plus/-anime vienen del release oficial de
# xinntao/Real-ESRGAN, DF2K_x4/DF2K_JPEG_x4 del release oficial de nihui/realsr-ncnn-
# vulkan. NO son parte de custom-models -- por eso "faltaban" ahí. Las variantes
# realesr-animevideov3-x2/x3 quedan afuera a propósito: DowP1 las purga por
# inestabilidad conocida (sanitize_upscayl_models -- ver _sanitize_upscayl_models en
# models_setup.py), solo se ofrece la x4.
# Modelos que Upscayl necesita y que NO vienen en el repo custom-models -- se bajan
# de los releases oficiales de Real-ESRGAN/RealSR (ver _download_upscayl_legacy_models
# en core/setup/models_setup.py, que es quien los consume). Cada entrada es
# (nombre, url, archivo-canario, peso real en bytes): el canario es el archivo que,
# si ya está en disco, permite saltarse esa descarga entera. Un solo URL por fuente
# alcanza para los 3 SO: los .bin/.param son datos de pesos, idénticos sin importar
# qué build del binario los acompañe.
UPSCAYL_LEGACY_MODEL_SOURCES = [
    ("Real-ESRGAN", "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip", "realesrgan-x4plus.bin", 45474481),
    ("RealSR", "https://github.com/nihui/realsr-ncnn-vulkan/releases/download/20220728/realsr-ncnn-vulkan-20220728-windows.zip", "DF2K_x4.bin", 64005701),
]

UPSCAYL_MODELS_MAP = {
    "realesrgan-x4plus": QCoreApplication.translate("constants", "Real-ESRGAN (General / Fotografía)"),
    "realesrgan-x4plus-anime": QCoreApplication.translate("constants", "Real-ESRGAN (Anime / Ilustración)"),
    "realesr-animevideov3-x4": QCoreApplication.translate("constants", "Anime Video V3 (x4)"),
    "RealESRGAN_General_x4_v3": QCoreApplication.translate("constants", "Real-ESRGAN V3 (Ligero y Rápido)"),
    "RealESRGAN_General_WDN_x4_v3": QCoreApplication.translate("constants", "Real-ESRGAN V3 WDN (Red Profunda)"),
    "4xHFA2k": QCoreApplication.translate("constants", "HFA2k (Texturas de Alta Frecuencia)"),
    "4xLSDIR": QCoreApplication.translate("constants", "LSDIR (Fotografía Realista)"),
    "4xLSDIRCompactC3": QCoreApplication.translate("constants", "LSDIR Compacto (Procesamiento Rápido)"),
    "4xLSDIRplusC": QCoreApplication.translate("constants", "LSDIR PlusC (Alta Fidelidad)"),
    "4xNomos8kSC": QCoreApplication.translate("constants", "Nomos8k (Detalles a Escala 8k)"),
    "4x_NMKD-Siax_200k": QCoreApplication.translate("constants", "NMKD Siax (Universal / Calidad JPEG)"),
    "4x_NMKD-Superscale-SP_178000_G": QCoreApplication.translate("constants", "NMKD Superscale (Fotos sin Artefactos)"),
    "uniscale_restore": QCoreApplication.translate("constants", "Uniscale Restore (Restauración de Daños)"),
    "unknown-2.0.1": QCoreApplication.translate("constants", "The Unknown (Experimental / Nitidez Extrema)"),
    "DF2K_x4": QCoreApplication.translate("constants", "RealSR (Detalle de Texturas)"),
    "DF2K_JPEG_x4": QCoreApplication.translate("constants", "RealSR JPEG (Reduce Compresión)"),
}

# --- CONSTANTES DE REESCALADO (IA) ---

# Escalas y niveles de ruido REALES de cada motor. No salen de la documentación:
# se sacaron corriendo cada binario con -h y después probando valor por valor
# contra una imagen de prueba, porque las dos fuentes se contradicen y el binario
# es el que manda. Lo que se encontró:
#
#   - upscayl-bin: su -h dice "custom output scale (can be 2, 3, 4)", pero es
#     mentira -- acepta cualquier entero >= 1 (probados 1,2,3,4,5,6,7,8,16,32,
#     todos devuelven la imagen al tamaño exacto pedido). Internamente repite
#     pasadas del modelo x4 hasta pasarse y remuestrea hacia abajo, por eso las
#     escalas altas cuestan varias pasadas. El 0 sí es inválido: el proceso
#     termina con código 0 pero deja un archivo corrupto.
#   - waifu2x-ncnn-vulkan: 1/2/4/8/16/32 y nada más -- el 3x que la app venía
#     ofreciendo para los tres motores por igual moría con "invalid scale
#     argument". Atencion con el 1x (solo denoise, sin agrandar): necesita los
#     modelos noiseN_model.param, que SOLO trae models-cunet -- las dos carpetas
#     upconv_7_* traen únicamente noiseN_scale2.0x_model, así que ahí 1x falla.
#     Por eso las escalas van por modelo y no por motor.
#   - srmd-ncnn-vulkan: 2/3/4 (lo único que ya estaba bien) y ruido -1 a 10 --
#     la app solo ofrecía hasta 3, dejando 7 niveles afuera.

UPSCAYL_SCALES = ["1x", "2x", "3x", "4x", "6x", "8x", "16x"]

_WAIFU2X_SCALES = ["1x", "2x", "4x", "8x", "16x", "32x"]
# Sin 1x: ver arriba (upconv_7_* no trae modelos de solo-denoise).
_WAIFU2X_SCALES_UPCONV = ["2x", "4x", "8x", "16x", "32x"]

SRMD_SCALES = ["2x", "3x", "4x"]

# Etiquetas de -n. La escala de Waifu2x es corta y con nombre; la de SRMD llega a
# 10 y es un continuo, así que solo se nombran los extremos.
WAIFU2X_DENOISE_LEVELS = [QCoreApplication.translate("constants", "-1 (Ninguna)"), QCoreApplication.translate("constants", "0 (Baja)"), QCoreApplication.translate("constants", "1 (Media)"), QCoreApplication.translate("constants", "2 (Alta)"), QCoreApplication.translate("constants", "3 (Máxima)")]
SRMD_DENOISE_LEVELS = (
    [QCoreApplication.translate("constants", "-1 (Ninguna)"), QCoreApplication.translate("constants", "0 (Baja)")]
    + [str(n) for n in range(1, 10)]
    + [QCoreApplication.translate("constants", "10 (Máxima)")]
)

WAIFU2X_MODELS = {
    QCoreApplication.translate("constants", "CU-Net (Alta Calidad)"): {
        "model": "models-cunet",
        "scales": _WAIFU2X_SCALES
    },
    QCoreApplication.translate("constants", "Anime Style Art (Clásico)"): {
        "model": "models-upconv_7_anime_style_art_rgb",
        "scales": _WAIFU2X_SCALES_UPCONV
    },
    QCoreApplication.translate("constants", "Photo (Fotos Reales)"): {
        "model": "models-upconv_7_photo",
        "scales": _WAIFU2X_SCALES_UPCONV
    },
}

SRMD_MODELS = {
    QCoreApplication.translate("constants", "Estándar (General)"): {
        "model": "models-srmd",
        "scales": SRMD_SCALES
    }
}