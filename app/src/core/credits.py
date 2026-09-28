# src/core/credits.py
"""Enlaces, formas de apoyo, agradecimientos y créditos de terceros.

Una sola fuente para Ajustes > Acerca de (gui/tabs/settings/pages/system_page.py)
y la ventana de "Créditos y licencias" (gui/dialogs/about_dialogs.py). La página
web (docs/creditos.html) repite este contenido a mano: si cambias algo aquí,
cámbialo también allí.

Las licencias se comprobaron el 2026-09-28 en cada fuente (metadatos del paquete
instalado, API de GitHub o de Hugging Face). Los textos van con
QCoreApplication.translate("Credits", ...) donde se muestran, no aquí: esto son
solo datos, así lupdate los encuentra en un único lugar -- ver QT_TRANSLATE_NOOP.
"""
from PySide6.QtCore import QT_TRANSLATE_NOOP

# ── Enlaces del autor y del proyecto ─────────────────────────────────────────
AUTHOR_X_URL = "https://x.com/MarcklaX"
PROJECT_GITHUB_URL = "https://github.com/MarckDP/DowP"
PROJECT_WEBSITE_URL = "https://marckdp.github.io/DowP/"
KOFI_URL = "https://ko-fi.com/marckdbm"

# Binance Pay: el QR va dentro de la app (assets), nunca descargado, para que no
# se pueda cambiar desde fuera; el UID se muestra también en texto para poder
# comprobarlo o pagar sin escanear.
BINANCE_UID = "345789454"
BINANCE_QR_RELPATH = ("assets", "images", "donate", "binance_pay_qr.png")

# ── Agradecimientos (orden pedido: la comunidad, Cry y después el resto) ─────
# (nombre, aporte, enlace o "")
ACKNOWLEDGEMENTS = [
    (QT_TRANSLATE_NOOP("Credits", "Servidor de Buisco Editor"),
     QT_TRANSLATE_NOOP("Credits", "La comunidad: sujetos de prueba en cada versión"),
     "https://discord.gg/enZFNbj5T8"),
    ("Cry", QT_TRANSLATE_NOOP("Credits", "Por un apoyo enorme al proyecto"), ""),
    ("JhonV", QT_TRANSLATE_NOOP("Credits", "Ideas y reporte de errores"), "https://x.com/JhonV__"),
    ("Lozada", QT_TRANSLATE_NOOP("Credits", "Pruebas y comentarios"), "https://www.instagram.com/soy_lozada"),
    ("Equinox", QT_TRANSLATE_NOOP("Credits", "Hizo posible DowP en Mac"),
     "https://equinox-editor.equinox-dgrafico.chatgpt.site/"),
    ("BlackBull", QT_TRANSLATE_NOOP("Credits", "Ideas y apoyo moral"), "https://blackbulldesigner.carrd.co/"),
    ("Nuan", QT_TRANSLATE_NOOP("Credits", "Ideas y pruebas"), "https://x.com/SoyNuan"),
]

# ── Créditos de terceros ──────────────────────────────────────────────────────
# (grupo, [(nombre, para qué, licencia, enlace)])
_DL = QT_TRANSLATE_NOOP("Credits", "Descargas")
_MM = QT_TRANSLATE_NOOP("Credits", "Video y audio")
_IMG = QT_TRANSLATE_NOOP("Credits", "Imagen y documentos")
_AI = QT_TRANSLATE_NOOP("Credits", "Inteligencia artificial")
_UI = QT_TRANSLATE_NOOP("Credits", "Interfaz y sistema")
_ADOBE = QT_TRANSLATE_NOOP("Credits", "Panel para Adobe")
_SND = QT_TRANSLATE_NOOP("Credits", "Sonidos")

THIRD_PARTY = [
    (_DL, [
        ("yt-dlp", QT_TRANSLATE_NOOP("Credits", "Motor de descargas"), "Unlicense", "https://github.com/yt-dlp/yt-dlp"),
        ("Deno", QT_TRANSLATE_NOOP("Credits", "Resuelve los retos de JavaScript de YouTube"), "MIT", "https://github.com/denoland/deno"),
        ("bgutil-ytdlp-pot-provider-rs", QT_TRANSLATE_NOOP("Credits", "Tokens PO para YouTube"), "GPL-3.0", "https://github.com/jim60105/bgutil-ytdlp-pot-provider-rs"),
        ("yt-dlp-getpot-wpc", QT_TRANSLATE_NOOP("Credits", "Tokens PO desde el navegador"), "MIT", "https://github.com/coletdjnz/yt-dlp-getpot-wpc"),
        ("curl_cffi", "", "MIT", "https://github.com/lexiforest/curl_cffi"),
        ("Requests", "", "Apache-2.0", "https://github.com/psf/requests"),
    ]),
    (_MM, [
        ("FFmpeg", QT_TRANSLATE_NOOP("Credits", "Conversión, recorte y recodificación (compilaciones GPL de gyan.dev y BtbN)"), "GPL-3.0", "https://ffmpeg.org"),
        ("mutagen", QT_TRANSLATE_NOOP("Credits", "Metadatos de audio"), "GPL-2.0-or-later", "https://github.com/quodlibet/mutagen"),
    ]),
    (_IMG, [
        ("Pillow", "", "MIT-CMU", "https://github.com/python-pillow/Pillow"),
        ("pillow-heif", "", "BSD-3-Clause", "https://github.com/bigcat88/pillow_heif"),
        ("pillow-avif-plugin", "", "MIT", "https://github.com/fdintino/pillow-avif-plugin"),
        ("psd-tools", "", "MIT", "https://github.com/psd-tools/psd-tools"),
        ("rawpy", "", "MIT", "https://github.com/letmaik/rawpy"),
        ("pypdfium2", "", "Apache-2.0 / BSD-3-Clause", "https://github.com/pypdfium2-team/pypdfium2"),
        ("img2pdf", "", "LGPL-3.0", "https://gitlab.mister-muffin.de/josch/img2pdf"),
        ("pikepdf", "", "MPL-2.0", "https://github.com/pikepdf/pikepdf"),
        ("resvg-py", "", "MIT", "https://github.com/baseplate-admin/resvg-py"),
        ("VTracer", QT_TRANSLATE_NOOP("Credits", "Vectorizar a SVG"), "MIT", "https://github.com/visioncortex/vtracer"),
        ("Ghostscript", QT_TRANSLATE_NOOP("Credits", "PDF y PostScript (se descarga aparte)"), "AGPL-3.0", "https://www.ghostscript.com"),
    ]),
    (_AI, [
        ("ONNX Runtime", QT_TRANSLATE_NOOP("Credits", "Ejecuta los modelos de IA"), "MIT", "https://github.com/microsoft/onnxruntime"),
        ("NumPy", "", "BSD-3-Clause", "https://github.com/numpy/numpy"),
        ("rembg", QT_TRANSLATE_NOOP("Credits", "Modelos U²-Net e IS-Net para quitar fondos"), "MIT", "https://github.com/danielgatis/rembg"),
        ("BiRefNet", QT_TRANSLATE_NOOP("Credits", "Quitar fondos"), "MIT", "https://github.com/ZhengPeng7/BiRefNet"),
        ("InSPyReNet", QT_TRANSLATE_NOOP("Credits", "Quitar fondos"), "MIT", "https://github.com/plemeri/InSPyReNet"),
        ("RMBG-2.0 (Bria AI)", QT_TRANSLATE_NOOP("Credits", "Quitar fondos"), QT_TRANSLATE_NOOP("Credits", "Licencia de Bria AI, uso no comercial"), "https://huggingface.co/briaai/RMBG-2.0"),
        ("Depth Anything (V1, V2, V3)", QT_TRANSLATE_NOOP("Credits", "Mapas de profundidad"), QT_TRANSLATE_NOOP("Credits", "Apache-2.0; algunos modelos, CC BY-NC 4.0"), "https://github.com/DepthAnything/Depth-Anything-V2"),
        ("Distill-Any-Depth", QT_TRANSLATE_NOOP("Credits", "Mapas de profundidad"), "MIT", "https://github.com/Westlake-AGI-Lab/Distill-Any-Depth"),
        ("MoGe-2", QT_TRANSLATE_NOOP("Credits", "Mapas de normales"), "MIT", "https://github.com/microsoft/MoGe"),
        ("DeepBump", QT_TRANSLATE_NOOP("Credits", "Mapas de normales"), "GPL-3.0", "https://github.com/HugoTini/DeepBump"),
        ("Real-ESRGAN", QT_TRANSLATE_NOOP("Credits", "Reescalado"), "BSD-3-Clause", "https://github.com/xinntao/Real-ESRGAN"),
        ("Upscayl NCNN", QT_TRANSLATE_NOOP("Credits", "Reescalado"), "AGPL-3.0", "https://github.com/upscayl/upscayl-ncnn"),
        ("waifu2x / SRMD / RealSR ncnn", QT_TRANSLATE_NOOP("Credits", "Reescalado (por nihui)"), "MIT", "https://github.com/nihui/waifu2x-ncnn-vulkan"),
    ]),
    (_UI, [
        ("PySide6 / Qt", QT_TRANSLATE_NOOP("Credits", "Interfaz"), "LGPL-3.0", "https://www.qt.io/qt-for-python"),
        ("Material Symbols", QT_TRANSLATE_NOOP("Credits", "Íconos (Google)"), "Apache-2.0", "https://github.com/google/material-design-icons"),
        ("Google Sans Flex, Inter, JetBrains Mono, Outfit, Plus Jakarta Sans, Raleway, Roboto",
         QT_TRANSLATE_NOOP("Credits", "Tipografías"), "SIL OFL 1.1", "https://fonts.google.com"),
        ("python-socketio / aiohttp / websockets", QT_TRANSLATE_NOOP("Credits", "Conexión con los editores"), "MIT / Apache-2.0 / BSD-3-Clause", "https://github.com/miguelgrinberg/python-socketio"),
        ("watchdog", "", "Apache-2.0", "https://github.com/gorakhargosh/watchdog"),
        ("zstandard / Brotli", QT_TRANSLATE_NOOP("Credits", "Compresión"), "BSD-3-Clause / MIT", "https://github.com/indygreg/python-zstandard"),
        ("PyCryptodome", QT_TRANSLATE_NOOP("Credits", "Firma de las actualizaciones"), "BSD-2-Clause / Public Domain", "https://github.com/Legrandin/pycryptodome"),
        ("fontTools", "", "MIT", "https://github.com/fonttools/fonttools"),
        ("PyInstaller", QT_TRANSLATE_NOOP("Credits", "Empaquetado de la app"), QT_TRANSLATE_NOOP("Credits", "GPL-2.0-or-later con excepción"), "https://pyinstaller.org"),
    ]),
    (_ADOBE, [
        ("Socket.IO", "", "MIT", "https://github.com/socketio/socket.io"),
        ("CSInterface (Adobe CEP)", "", QT_TRANSLATE_NOOP("Credits", "Licencia de Adobe"), "https://github.com/Adobe-CEP/CEP-Resources"),
    ]),
    (_SND, [
        ("Electric bass guitar loop 2 — josefpres", QT_TRANSLATE_NOOP("Credits", "Sonido de éxito"), "CC0", "https://freesound.org/people/josefpres/sounds/483145/"),
        ("bass suspended chord 2 — CVLTIV8R", QT_TRANSLATE_NOOP("Credits", "Sonido de error"), "CC0", "https://freesound.org/people/CVLTIV8R/sounds/799096/"),
    ]),
]
