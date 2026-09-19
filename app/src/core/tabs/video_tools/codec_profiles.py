# src/core/tabs/video_tools/codec_profiles.py
"""
Perfiles/preajustes de calidad por encoder de ffmpeg, para el combobox "Perfil" de la
pestaña Avanzado (ej. Apple ProRes -> 422 Proxy / LT / Standard / HQ / 4444 / 4444 XQ;
H.264 -> Alta/Media/Rapida calidad, etc.).

Es conocimiento curado a mano (igual que lo era en DowP Lite), no datos verificados
empiricamente como ffmpeg_codec_matrix.json - los valores de CRF/CQ/bitrate son
recomendaciones razonables, no una garantia de que ese codec exista en este ffmpeg (eso
ya lo resuelve recode_guard.py por separado).

Cada perfil es {"label": str, "args": [...]} con los flags de ffmpeg a agregar, o
{"label": str, "custom": "vbr"/"cbr"} para las opciones de bitrate manual (la UI debe
pedir el valor aparte; todavia no hay campo numerico conectado para esto).

Los codecs sin tabla curada todavia devuelven un unico perfil "Predeterminado" con los
flags minimos (-c:v/-c:a <encoder>), para no romper la UI mientras se amplia esta lista.
"""
from PySide6.QtCore import QCoreApplication
# Nota: pyside6-lupdate extrae strings buscando llamadas textuales a tr(...)/
# translate(...)/QT_TR_NOOP(...)/QT_TRANSLATE_NOOP(...) -- un alias como
# "_tr = lambda ctx, txt: QCoreApplication.translate(...)" NO lo reconoce (no es un
# nombre de función que sepa buscar), así que ninguna llamada QCoreApplication.translate(...) se extraía nunca.
# Por eso todo este archivo llama QCoreApplication.translate(...) directo.


VIDEO_ENCODER_PROFILES = {
    "libx264": [
        {"label": QCoreApplication.translate("codec_profiles", "Alta Calidad (CRF 18)"), "tier": "alta", "args": ["-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Media (CRF 23)"), "tier": "media", "args": ["-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Rápida (CRF 28)"), "tier": "rapida", "args": ["-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Constante Personalizada (CRF/CQ)"), "custom": "cq"},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado (VBR)"), "custom": "vbr"},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado (CBR)"), "custom": "cbr"},
    ],
    "h264_nvenc": [
        {"label": QCoreApplication.translate("codec_profiles", "Alta Calidad (CQ 18)"), "tier": "alta", "args": ["-c:v", "h264_nvenc", "-preset", "p7", "-rc", "vbr", "-cq", "18", "-pix_fmt", "yuv420p"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Media (CQ 23)"), "tier": "media", "args": ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "23", "-pix_fmt", "yuv420p"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Constante Personalizada (CRF/CQ)"), "custom": "cq"},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado (VBR)"), "custom": "vbr"},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado (CBR)"), "custom": "cbr"},
    ],
    "h264_qsv": [
        {"label": QCoreApplication.translate("codec_profiles", "Alta Calidad"), "tier": "alta", "args": ["-c:v", "h264_qsv", "-preset", "veryslow", "-global_quality", "18", "-pix_fmt", "yuv420p"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Media"), "tier": "media", "args": ["-c:v", "h264_qsv", "-preset", "medium", "-global_quality", "23", "-pix_fmt", "yuv420p"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Constante Personalizada (CRF/CQ)"), "custom": "cq"},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado (VBR)"), "custom": "vbr"},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado (CBR)"), "custom": "cbr"},
    ],
    "h264_amf": [
        {"label": QCoreApplication.translate("codec_profiles", "Alta Calidad"), "tier": "alta", "args": ["-c:v", "h264_amf", "-quality", "quality", "-rc", "cqp", "-qp_i", "18", "-qp_p", "18", "-pix_fmt", "yuv420p"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Balanceada"), "tier": "media", "args": ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "cqp", "-qp_i", "23", "-qp_p", "23", "-pix_fmt", "yuv420p"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Constante Personalizada (CRF/CQ)"), "custom": "cq"},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado (VBR)"), "custom": "vbr"},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado (CBR)"), "custom": "cbr"},
    ],
    "h264_videotoolbox": [
        {"label": QCoreApplication.translate("codec_profiles", "Alta Calidad"), "tier": "alta", "args": ["-c:v", "h264_videotoolbox", "-profile:v", "high", "-q:v", "70"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Media"), "tier": "media", "args": ["-c:v", "h264_videotoolbox", "-profile:v", "main", "-q:v", "50"]},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado (CBR)"), "custom": "cbr"},
    ],
    "libx265": [
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Alta (CRF 20)"), "tier": "alta", "args": ["-c:v", "libx265", "-preset", "slow", "-crf", "20", "-tag:v", "hvc1"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Media (CRF 24)"), "tier": "media", "args": ["-c:v", "libx265", "-preset", "medium", "-crf", "24", "-tag:v", "hvc1"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Constante Personalizada (CRF/CQ)"), "custom": "cq"},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado (VBR)"), "custom": "vbr"},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado (CBR)"), "custom": "cbr"},
    ],
    "hevc_nvenc": [
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Alta (CQ 20)"), "tier": "alta", "args": ["-c:v", "hevc_nvenc", "-preset", "p7", "-rc", "vbr", "-cq", "20", "-pix_fmt", "yuv420p"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Media (CQ 24)"), "tier": "media", "args": ["-c:v", "hevc_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "24", "-pix_fmt", "yuv420p"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Constante Personalizada (CRF/CQ)"), "custom": "cq"},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado (VBR)"), "custom": "vbr"},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado (CBR)"), "custom": "cbr"},
    ],
    "hevc_qsv": [
        {"label": QCoreApplication.translate("codec_profiles", "Alta Calidad"), "tier": "alta", "args": ["-c:v", "hevc_qsv", "-preset", "veryslow", "-global_quality", "20"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Media"), "tier": "media", "args": ["-c:v", "hevc_qsv", "-preset", "medium", "-global_quality", "24"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Constante Personalizada (CRF/CQ)"), "custom": "cq"},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado (VBR)"), "custom": "vbr"},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado (CBR)"), "custom": "cbr"},
    ],
    "hevc_amf": [
        {"label": QCoreApplication.translate("codec_profiles", "Alta Calidad"), "tier": "alta", "args": ["-c:v", "hevc_amf", "-quality", "quality", "-rc", "cqp", "-qp_i", "20", "-qp_p", "20", "-pix_fmt", "yuv420p"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Balanceada"), "tier": "media", "args": ["-c:v", "hevc_amf", "-quality", "balanced", "-rc", "cqp", "-qp_i", "24", "-qp_p", "24", "-pix_fmt", "yuv420p"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Constante Personalizada (CRF/CQ)"), "custom": "cq"},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado (VBR)"), "custom": "vbr"},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado (CBR)"), "custom": "cbr"},
    ],
    "hevc_videotoolbox": [
        {"label": QCoreApplication.translate("codec_profiles", "Alta Calidad"), "tier": "alta", "args": ["-c:v", "hevc_videotoolbox", "-profile:v", "main", "-q:v", "80"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Media"), "tier": "media", "args": ["-c:v", "hevc_videotoolbox", "-profile:v", "main", "-q:v", "65"]},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado (CBR)"), "custom": "cbr"},
    ],
    "libsvtav1": [
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Alta (CRF 28)"), "tier": "alta", "args": ["-c:v", "libsvtav1", "-preset", "4", "-crf", "28"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Media (CRF 35)"), "tier": "media", "args": ["-c:v", "libsvtav1", "-preset", "6", "-crf", "35"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Constante Personalizada (CRF/CQ)"), "custom": "cq"},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado (VBR)"), "custom": "vbr"},
    ],
    "libaom-av1": [
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Alta (CRF 28)"), "tier": "alta", "args": ["-c:v", "libaom-av1", "-cpu-used", "4", "-crf", "28"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Media (CRF 35)"), "tier": "media", "args": ["-c:v", "libaom-av1", "-cpu-used", "6", "-crf", "35"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Constante Personalizada (CRF/CQ)"), "custom": "cq"},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado (VBR)"), "custom": "vbr"},
    ],
    "av1_nvenc": [
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Alta (CQ 24)"), "tier": "alta", "args": ["-c:v", "av1_nvenc", "-preset", "p7", "-rc", "vbr", "-cq", "24"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Media (CQ 28)"), "tier": "media", "args": ["-c:v", "av1_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "28"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Constante Personalizada (CRF/CQ)"), "custom": "cq"},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado (VBR)"), "custom": "vbr"},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado (CBR)"), "custom": "cbr"},
    ],
    "av1_qsv": [
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Alta"), "tier": "alta", "args": ["-c:v", "av1_qsv", "-global_quality", "25", "-preset", "slow"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Media"), "tier": "media", "args": ["-c:v", "av1_qsv", "-global_quality", "30", "-preset", "medium"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Constante Personalizada (CRF/CQ)"), "custom": "cq"},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado (VBR)"), "custom": "vbr"},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado (CBR)"), "custom": "cbr"},
    ],
    "av1_amf": [
        {"label": QCoreApplication.translate("codec_profiles", "Alta Calidad"), "tier": "alta", "args": ["-c:v", "av1_amf", "-quality", "quality", "-rc", "cqp", "-qp_i", "28", "-qp_p", "28"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Balanceada"), "tier": "media", "args": ["-c:v", "av1_amf", "-quality", "balanced", "-rc", "cqp", "-qp_i", "32", "-qp_p", "32"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Constante Personalizada (CRF/CQ)"), "custom": "cq"},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado (VBR)"), "custom": "vbr"},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado (CBR)"), "custom": "cbr"},
    ],
    "libvpx-vp9": [
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Alta (CRF 28)"), "tier": "alta", "args": ["-c:v", "libvpx-vp9", "-crf", "28", "-b:v", "0"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Media (CRF 33)"), "tier": "media", "args": ["-c:v", "libvpx-vp9", "-crf", "33", "-b:v", "0"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Constante Personalizada (CRF/CQ)"), "custom": "cq"},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado (VBR)"), "custom": "vbr"},
    ],
    "vp9_qsv": [
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Alta"), "tier": "alta", "args": ["-c:v", "vp9_qsv", "-global_quality", "25", "-preset", "slow"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Media"), "tier": "media", "args": ["-c:v", "vp9_qsv", "-global_quality", "30", "-preset", "medium"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Constante Personalizada (CRF/CQ)"), "custom": "cq"},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado (VBR)"), "custom": "vbr"},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado (CBR)"), "custom": "cbr"},
    ],
    "libvpx": [
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Alta (CRF 10)"), "args": ["-c:v", "libvpx", "-crf", "10", "-b:v", "0"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Media (CRF 20)"), "args": ["-c:v", "libvpx", "-crf", "20", "-b:v", "0"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Constante Personalizada (CRF/CQ)"), "custom": "cq"},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado (VBR)"), "custom": "vbr"},
    ],
    "prores_ks": [
        {"label": QCoreApplication.translate("codec_profiles", "422 Proxy"), "quick_proxy": True, "args": ["-c:v", "prores_ks", "-profile:v", "0", "-pix_fmt", "yuv422p10le", "-threads", "0"]},
        {"label": "422 LT", "args": ["-c:v", "prores_ks", "-profile:v", "1", "-pix_fmt", "yuv422p10le", "-threads", "0"]},
        {"label": QCoreApplication.translate("codec_profiles", "422 Standard"), "args": ["-c:v", "prores_ks", "-profile:v", "2", "-pix_fmt", "yuv422p10le", "-threads", "0"]},
        {"label": "422 HQ", "args": ["-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le", "-threads", "0"]},
        {"label": "4444", "args": ["-c:v", "prores_ks", "-profile:v", "4", "-pix_fmt", "yuv444p10le", "-threads", "0"]},
        {"label": "4444 XQ", "args": ["-c:v", "prores_ks", "-profile:v", "5", "-pix_fmt", "yuv444p10le", "-threads", "0"]},
    ],
    "prores_aw": [
        {"label": QCoreApplication.translate("codec_profiles", "422 Proxy"), "quick_proxy": True, "args": ["-c:v", "prores_aw", "-profile:v", "0", "-pix_fmt", "yuv422p10le", "-threads", "0"]},
        {"label": "422 LT", "args": ["-c:v", "prores_aw", "-profile:v", "1", "-pix_fmt", "yuv422p10le", "-threads", "0"]},
        {"label": QCoreApplication.translate("codec_profiles", "422 Standard"), "args": ["-c:v", "prores_aw", "-profile:v", "2", "-pix_fmt", "yuv422p10le", "-threads", "0"]},
        {"label": "422 HQ", "args": ["-c:v", "prores_aw", "-profile:v", "3", "-pix_fmt", "yuv422p10le", "-threads", "0"]},
        {"label": "4444", "args": ["-c:v", "prores_aw", "-profile:v", "4", "-pix_fmt", "yuv444p10le", "-threads", "0"]},
        {"label": "4444 XQ", "args": ["-c:v", "prores_aw", "-profile:v", "5", "-pix_fmt", "yuv444p10le", "-threads", "0"]},
    ],
    "dnxhd": [
        {"label": QCoreApplication.translate("codec_profiles", "DNxHD 1080p25 (145 Mbps)"), "args": ["-c:v", "dnxhd", "-b:v", "145M", "-pix_fmt", "yuv422p"]},
        {"label": QCoreApplication.translate("codec_profiles", "DNxHD 1080p29.97 (145 Mbps)"), "args": ["-c:v", "dnxhd", "-b:v", "145M", "-pix_fmt", "yuv422p"]},
        {"label": QCoreApplication.translate("codec_profiles", "DNxHD 1080i50 (120 Mbps)"), "args": ["-c:v", "dnxhd", "-b:v", "120M", "-pix_fmt", "yuv422p", "-flags", "+ildct+ilme", "-top", "1"]},
        {"label": QCoreApplication.translate("codec_profiles", "DNxHD 720p50 (90 Mbps)"), "args": ["-c:v", "dnxhd", "-b:v", "90M", "-pix_fmt", "yuv422p"]},
        {"label": QCoreApplication.translate("codec_profiles", "DNxHR LB (8-bit 4:2:2)"), "quick_proxy": True, "args": ["-c:v", "dnxhd", "-profile:v", "dnxhr_lb", "-pix_fmt", "yuv422p"]},
        {"label": QCoreApplication.translate("codec_profiles", "DNxHR SQ (8-bit 4:2:2)"), "args": ["-c:v", "dnxhd", "-profile:v", "dnxhr_sq", "-pix_fmt", "yuv422p"]},
        {"label": QCoreApplication.translate("codec_profiles", "DNxHR HQ (8-bit 4:2:2)"), "args": ["-c:v", "dnxhd", "-profile:v", "dnxhr_hq", "-pix_fmt", "yuv422p"]},
        {"label": QCoreApplication.translate("codec_profiles", "DNxHR HQX (10-bit 4:2:2)"), "args": ["-c:v", "dnxhd", "-profile:v", "dnxhr_hqx", "-pix_fmt", "yuv422p10le"]},
        {"label": QCoreApplication.translate("codec_profiles", "DNxHR 444 (10-bit 4:4:4)"), "args": ["-c:v", "dnxhd", "-profile:v", "dnxhr_444", "-pix_fmt", "yuv444p10le"]},
    ],
    "cfhd": [
        # Nombres y orden = los 13 niveles reales de "-quality" del encoder cfhd de este
        # ffmpeg (ver `ffmpeg -h encoder=cfhd`), curados a 6 representativos (mismo
        # criterio que prores_ks/dnxhd: no todos los valores posibles, los puntos de
        # referencia reales de la escala) - "Film Scan" es el nombre que usa el propio
        # SDK de CineForm para sus niveles mas altos (grado masterización/escaneo de
        # película), no una etiqueta inventada.
        {"label": QCoreApplication.translate("codec_profiles", "Low (Proxy)"), "quick_proxy": True, "args": ["-c:v", "cfhd", "-quality", "low"]},
        {"label": QCoreApplication.translate("codec_profiles", "Medium"), "args": ["-c:v", "cfhd", "-quality", "medium"]},
        {"label": QCoreApplication.translate("codec_profiles", "High"), "args": ["-c:v", "cfhd", "-quality", "high"]},
        {"label": QCoreApplication.translate("codec_profiles", "Film Scan 1"), "args": ["-c:v", "cfhd", "-quality", "film1"]},
        {"label": QCoreApplication.translate("codec_profiles", "Film Scan 2"), "args": ["-c:v", "cfhd", "-quality", "film2"]},
        {"label": QCoreApplication.translate("codec_profiles", "Film Scan 3+ (Máxima)"), "args": ["-c:v", "cfhd", "-quality", "film3+"]},
    ],
    "gif": [
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Alta"), "args": ["-vf", "split[s0][s1];[s0]palettegen=stats_mode=full:max_colors=256[p];[s1][p]paletteuse=dither=floyd_steinberg", "-c:v", "gif", "-loop", "0"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Media"), "args": ["-vf", "split[s0][s1];[s0]palettegen=stats_mode=full:max_colors=256[p];[s1][p]paletteuse=dither=bayer:bayer_scale=2", "-c:v", "gif", "-loop", "0"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Baja"), "args": ["-vf", "fps=15,scale=480:-1:flags=lanczos,split[s0][s1];[s0]palettegen=stats_mode=full:max_colors=128[p];[s1][p]paletteuse=dither=bayer:bayer_scale=2", "-c:v", "gif", "-loop", "0"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Rápida"), "args": ["-vf", "fps=12,scale=480:-1:flags=lanczos", "-c:v", "gif", "-loop", "0"]},
        {"label": QCoreApplication.translate("codec_profiles", "Personalizado (GIF)"), "custom": "gif"},
    ],
}

AUDIO_ENCODER_PROFILES = {
    "aac": [
        {"label": QCoreApplication.translate("codec_profiles", "Alta Calidad (~256kbps)"), "args": ["-c:a", "aac", "-b:a", "256k"]},
        {"label": QCoreApplication.translate("codec_profiles", "Buena Calidad (~192kbps)"), "args": ["-c:a", "aac", "-b:a", "192k"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Media (~128kbps)"), "args": ["-c:a", "aac", "-b:a", "128k"]},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado"), "custom": "audio_bitrate"},
    ],
    "libmp3lame": [
        {"label": QCoreApplication.translate("codec_profiles", "320kbps (CBR)"), "args": ["-c:a", "libmp3lame", "-b:a", "320k"]},
        {"label": QCoreApplication.translate("codec_profiles", "256kbps aprox. (VBR)"), "args": ["-c:a", "libmp3lame", "-q:a", "0"]},
        {"label": QCoreApplication.translate("codec_profiles", "192kbps (CBR)"), "args": ["-c:a", "libmp3lame", "-b:a", "192k"]},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado"), "custom": "audio_bitrate"},
    ],
    "libopus": [
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Transparente (~256kbps)"), "args": ["-c:a", "libopus", "-b:a", "256k"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Alta (~192kbps)"), "args": ["-c:a", "libopus", "-b:a", "192k"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Media (~128kbps)"), "args": ["-c:a", "libopus", "-b:a", "128k"]},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado"), "custom": "audio_bitrate"},
    ],
    "libvorbis": [
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Muy Alta (q8)"), "args": ["-c:a", "libvorbis", "-q:a", "8"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Alta (q6)"), "args": ["-c:a", "libvorbis", "-q:a", "6"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Media (q4)"), "args": ["-c:a", "libvorbis", "-q:a", "4"]},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado"), "custom": "audio_bitrate"},
    ],
    "ac3": [
        {"label": QCoreApplication.translate("codec_profiles", "Stereo (192kbps)"), "args": ["-c:a", "ac3", "-b:a", "192k"]},
        {"label": QCoreApplication.translate("codec_profiles", "Stereo (256kbps)"), "args": ["-c:a", "ac3", "-b:a", "256k"]},
        {"label": QCoreApplication.translate("codec_profiles", "Surround 5.1 (448kbps)"), "args": ["-c:a", "ac3", "-b:a", "448k", "-ac", "6"]},
        {"label": QCoreApplication.translate("codec_profiles", "Surround 5.1 (640kbps)"), "args": ["-c:a", "ac3", "-b:a", "640k", "-ac", "6"]},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado"), "custom": "audio_bitrate"},
    ],
    "alac": [
        {"label": QCoreApplication.translate("codec_profiles", "Estándar (sin pérdida)"), "args": ["-c:a", "alac"]},
    ],
    "flac": [
        {"label": QCoreApplication.translate("codec_profiles", "Compresión nivel 5"), "args": ["-c:a", "flac", "-compression_level", "5"]},
        {"label": QCoreApplication.translate("codec_profiles", "Compresión nivel 8 (más lento)"), "args": ["-c:a", "flac", "-compression_level", "8"]},
    ],
    "pcm_s24le": [
        {"label": QCoreApplication.translate("codec_profiles", "PCM 16-bit"), "args": ["-c:a", "pcm_s16le"]},
        {"label": QCoreApplication.translate("codec_profiles", "PCM 24-bit"), "args": ["-c:a", "pcm_s24le"]},
    ],
    "wmav2": [
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Alta (192kbps)"), "args": ["-c:a", "wmav2", "-b:a", "192k"]},
        {"label": QCoreApplication.translate("codec_profiles", "Calidad Media (128kbps)"), "args": ["-c:a", "wmav2", "-b:a", "128k"]},
        {"label": QCoreApplication.translate("codec_profiles", "Bitrate Personalizado"), "custom": "audio_bitrate"},
    ],
}


# Codecs con mas de una implementacion de encoder valida en ffmpeg, sin que haya una
# "mejor" objetiva para todos los casos (a diferencia de hardware vs software, donde
# hardware_detector.py ya elige el mejor real por probe-encode). Se ofrecen ambas y que
# el usuario elija. IMPORTANTE (corregido tras verificar contra este ffmpeg real, ver
# conversacion - el comentario anterior tenia esto al reves): "-c:v prores" (el nombre
# generico, sin sufijo) es un alias de prores_aw, NO de prores_ks - confirmado
# comparando bitrate/tamano de archivo byte a byte, identicos entre "prores" y
# "prores_aw", y distintos de "prores_ks". prores_ks (Kostya Shishkov) SI es mas preciso
# en la practica (bitrate consistentemente mas alto/menos comprimido a igual perfil,
# confirmado con benchmark real) pero NO es "el default" de ffmpeg como se creia; y
# prores_aw SI soporta los perfiles 4444/4444 XQ pese a que su "-h encoder=" no lista un
# "-profile" con nombres como si lo hace ks (confirmado con el FourCC real grabado en el
# archivo: ap4h/ap4x en ambos, igual de validos) - no asumir lo contrario por eso. En
# Windows, prores_aw ademas resulto ~8x mas rapido que prores_ks en el mismo benchmark
# (ver WINDOWS_PREFERRED_ENCODER) - la misma logica de "mas de una implementacion, sin
# ganador objetivo unico" aplicaria a libsvtav1 vs libaom-av1 en AV1 (hoy
# hardware_detector.py elige libsvtav1 automaticamente como "software" preferido, sin
# ofrecer el combo).
ENCODER_VARIANTS = {
    "prores": [
        ("prores_ks", QCoreApplication.translate("codec_profiles", "Preciso (prores_ks)")),
        ("prores_aw", QCoreApplication.translate("codec_profiles", "Rápido (prores_aw)")),
    ],
}

# Preferencia de encoder por defecto en Windows para codecs con mas de una
# implementacion valida (ver ENCODER_VARIANTS de arriba): no es un dato verificado por
# probe-encode como el resto de hardware_detector.py, es una preferencia medida a mano
# (benchmark real en Windows con este ffmpeg: prores_aw ~8x mas rapido que prores_ks a
# igual perfil/resolucion, ver conversacion) - no se probo en Linux/macOS, asi que ahi se
# deja el orden original (ks primero) tal cual. Sigue siendo 100% reversible: quien
# consuma esto (Avanzado, Edicion) sigue dejando elegir el otro encoder donde corresponda.
WINDOWS_PREFERRED_ENCODER = {"prores": "prores_aw"}


def ordered_encoder_variants(codec_id: str, variants: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """`variants` (de ENCODER_VARIANTS) reordenada para que el preferido en ESTE sistema
    quede primero (ver WINDOWS_PREFERRED_ENCODER) - util para que un combo poblado con
    esta lista quede con el mejor por defecto ya seleccionado (índice 0) sin tener que
    buscarlo aparte."""
    import platform
    preferred = WINDOWS_PREFERRED_ENCODER.get(codec_id) if platform.system() == "Windows" else None
    if not preferred:
        return variants
    return sorted(variants, key=lambda item: item[0] != preferred)


def preferred_encoder(codec_id: str, fallback_encoder: str) -> str:
    """El encoder que corresponde usar por defecto para este codec en ESTE sistema, ya
    aplicada la preferencia de plataforma - a diferencia de recode_guard.resolve_encoder
    (que devuelve el que el matrix usó para VERIFICAR, no necesariamente el mejor para
    el usuario final cuando hay mas de una implementacion valida, ver ENCODER_VARIANTS).
    `fallback_encoder` se usa tal cual si este codec no tiene variantes registradas."""
    variants = ENCODER_VARIANTS.get(codec_id)
    if not variants:
        return fallback_encoder
    return ordered_encoder_variants(codec_id, variants)[0][0]


# Audio recomendado por codec de video, para autocompletar y agilizar el flujo. No es
# una regla tecnica (varios funcionarian) sino la pareja mas convencional/segura por
# familia: entrega web/consumo -> AAC (o Opus para la familia libre VP8/VP9/AV1), NLE
# profesional (ProRes/DNxHR) -> PCM sin comprimir. Los codecs sin entrada usan "aac" por
# ser el mas ampliamente compatible.
RECOMMENDED_AUDIO_CODEC = {
    "h264": "aac",
    "hevc": "aac",
    "av1": "opus",
    "vp9": "opus",
    "vp8": "opus",
    "theora": "vorbis",
    "prores": "pcm_s24le",
    "dnxhd": "pcm_s24le",
    "cfhd": "pcm_s24le",
    "mpeg2video": "ac3",
}
DEFAULT_RECOMMENDED_AUDIO_CODEC = "aac"


def recommend_audio_codec(video_codec_id: str | None) -> str:
    return RECOMMENDED_AUDIO_CODEC.get(video_codec_id, DEFAULT_RECOMMENDED_AUDIO_CODEC)


# Encoders donde el mecanismo clasico de 2 pasadas de ffmpeg (-pass 1 / -pass 2) tiene
# sentido: encoders de software orientados a bitrate objetivo. Los de hardware (NVENC/
# QSV/AMF) tienen sus propios mecanismos de multipass no equivalentes a este flag, asi
# que no se ofrecen aca para no prometer algo no verificado.
TWO_PASS_CAPABLE_ENCODERS = {"libx264", "libx265", "libvpx", "libvpx-vp9", "libaom-av1", "libsvtav1"}


def encoder_is_two_pass_capable(encoder: str | None) -> bool:
    return bool(encoder) and encoder in TWO_PASS_CAPABLE_ENCODERS


def supports_two_pass(encoder: str | None, profile: dict | None) -> bool:
    """2 pasadas solo tiene sentido cuando hay un bitrate objetivo (VBR/CBR, sea
    personalizado o un perfil con '-b:v' fijo) - con CRF/CQ no hay nada que converger."""
    if not encoder or encoder not in TWO_PASS_CAPABLE_ENCODERS or not profile:
        return False
    if profile.get("custom"):
        return True
    return "-b:v" in profile.get("args", [])


def build_pass_args(base_args: list[str], pass_num: int) -> list[str]:
    return [*base_args, "-pass", str(pass_num)]



def build_custom_quality_args(encoder: str, cq_value: int) -> list[str]:
    base = ["-c:v", encoder]
    if "nvenc" in encoder:
        return base + ["-rc", "vbr", "-cq", str(cq_value)]
    if "qsv" in encoder:
        return base + ["-global_quality", str(cq_value)]
    if "amf" in encoder:
        return base + ["-rc", "cqp", "-qp_i", str(cq_value), "-qp_p", str(cq_value)]
    return base + ["-crf", str(cq_value)]

def build_custom_bitrate_args(encoder: str, mode: str, bitrate_kbps: int) -> list[str]:
    """
    Arma los flags de ffmpeg para un bitrate de video elegido a mano.
    mode: "vbr" (deja margen con maxrate/bufsize) o "cbr" (fuerza min=max=bitrate).
    """
    b = f"{bitrate_kbps}k"
    if mode == "cbr":
        return ["-c:v", encoder, "-b:v", b, "-minrate", b, "-maxrate", b, "-bufsize", b]
    maxrate = f"{int(bitrate_kbps * 1.5)}k"
    bufsize = f"{bitrate_kbps * 2}k"
    return ["-c:v", encoder, "-b:v", b, "-maxrate", maxrate, "-bufsize", bufsize]


def build_custom_audio_bitrate_args(encoder: str, bitrate_kbps: int) -> list[str]:
    """
    Arma los flags de ffmpeg para un bitrate de audio elegido a mano.
    """
    return ["-c:a", encoder, "-b:a", f"{bitrate_kbps}k"]


def build_custom_gif_args(dither: str = "floyd_steinberg", stats_mode: str = "full", max_colors: int = 256, fps: int | float | None = None) -> list[str]:
    """
    Arma los flags de ffmpeg para un GIF animado con paleta, dithering y FPS personalizados.
    """
    max_colors = max(2, min(256, int(max_colors)))
    palettegen_opts = f"stats_mode={stats_mode}:max_colors={max_colors}"
    paletteuse_opts = f"dither={dither}"
    if dither == "bayer":
        paletteuse_opts += ":bayer_scale=2"
    
    fps_prefix = f"fps={fps}," if (fps and float(fps) > 0) else ""
    vf_filter = f"{fps_prefix}split[s0][s1];[s0]palettegen={palettegen_opts}[p];[s1][p]paletteuse={paletteuse_opts}"
    return ["-vf", vf_filter, "-c:v", "gif", "-loop", "0"]


def extract_bitrate_kbps(args: list[str], flag: str = "-b:v") -> float | None:
    """Extrae un valor kbps de una lista de args de ffmpeg (ej. '-b:v 145M' -> 145000.0)."""
    if not args or flag not in args:
        return None
    try:
        raw = args[args.index(flag) + 1]
    except IndexError:
        return None
    raw = raw.strip().lower()
    try:
        if raw.endswith("k"):
            return float(raw[:-1])
        if raw.endswith("m"):
            return float(raw[:-1]) * 1000
        return float(raw) / 1000
    except ValueError:
        return None


def _default_profile(kind: str, encoder: str) -> list[dict]:
    flag = "-c:v" if kind == "video" else "-c:a"
    return [{"label": QCoreApplication.translate("codec_profiles", "Predeterminado"), "args": [flag, encoder]}]


# Niveles de calidad comparables ENTRE encoders distintos, de mejor a peor. Cada perfil
# de los codecs con variante de hardware (h264/hevc/av1/vp9) lleva su "tier": es lo que
# permite guardar un preajuste como "H.264, calidad media" y resolverlo al usarlo con el
# encoder que tenga ESE equipo, en vez de dejar escrito "-c:v h264_nvenc" y que falle en
# una AMD (ver recode_guard.resolve_video_encoding). No todos los encoders tienen los
# tres: x264 llega a "rapida", NVENC/AMF/QSV se quedan en "media", así que al pedir un
# nivel que no existe se cae al más cercano hacia arriba.
QUALITY_TIERS = ("alta", "media", "rapida")


def profile_for_tier(encoder: str | None, tier: str) -> dict | None:
    """El perfil de `encoder` para ese nivel de calidad, o el más cercano disponible.
    None si el encoder no tiene perfiles con nivel (ej. ProRes, que se organiza por
    perfiles propios 422/4444, no por calidad)."""
    perfiles = [p for p in get_profiles("video", encoder) if p.get("tier")]
    if not perfiles:
        return None
    exacto = next((p for p in perfiles if p["tier"] == tier), None)
    if exacto:
        return exacto
    # El pedido no existe en este encoder: se elige el más cercano, priorizando el
    # inmediatamente MEJOR (más calidad) antes que uno peor.
    orden = list(QUALITY_TIERS)
    objetivo = orden.index(tier) if tier in orden else 1
    return min(perfiles, key=lambda p: (abs(orden.index(p["tier"]) - objetivo),
                                        orden.index(p["tier"]) > objetivo))


def tier_of_args(encoder: str | None, args: list | None) -> str | None:
    """Nivel de calidad de unos args ya armados, comparando con la tabla de perfiles --
    se usa al guardar un preajuste desde Avanzado para saber qué nivel eligió el usuario
    sin tener que arrastrar el índice del combo."""
    if not args:
        return None
    for perfil in get_profiles("video", encoder):
        if perfil.get("tier") and list(perfil.get("args") or []) == list(args):
            return perfil["tier"]
    return None


def get_profiles(kind: str, encoder: str | None) -> list[dict]:
    """Lista de perfiles disponibles para un encoder. 'kind' es 'video' o 'audio'."""
    if not encoder:
        return []
    table = VIDEO_ENCODER_PROFILES if kind == "video" else AUDIO_ENCODER_PROFILES
    return table.get(encoder) or _default_profile(kind, encoder)
