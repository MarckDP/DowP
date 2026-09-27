# tools/codec_matrix/codec_specs.py
"""
Definicion de que codec probar con que encoder de ffmpeg, con que parametros, y contra
que contenedores. Es la unica fuente de "conocimiento curado" de esta herramienta: cual
encoder de software representa a cada codec, y que parametros minimos necesita cada uno
para que el fallo de un test refleje una incompatibilidad real, no un error de harness
(ej.: NVENC necesita >=256x256, H.263 exige resolucion QCIF fija, DNxHD exige bitrate
exacto por perfil, MXF exige audio a 48kHz little-endian, etc.).

Todos los encoders listados aca son de SOFTWARE: no dependen de la marca de GPU de quien
corra esto, dan el mismo resultado en cualquier maquina con el mismo build de ffmpeg.

Si en el futuro ffmpeg agrega/saca un encoder, o Wikipedia deja de ser la referencia,
este es el unico archivo que hay que tocar para agregar/quitar codecs de la matriz.
"""

# ─── Contenedores: id interno -> lista de (muxer ffmpeg, extension de archivo) ───
# ps_ts se prueba como dos entradas separadas (mpeg = Program Stream, mpegts = Transport
# Stream) porque son muxers distintos en ffmpeg con compatibilidad real distinta.
CONTAINERS = {
    "mkv":    [("matroska", "mkv")],
    "mp4":    [("mp4", "mp4")],
    "qtff":   [("mov", "mov")],
    "asf":    [("asf", "asf")],
    "avi":    [("avi", "avi")],
    "mxf":    [("mxf", "mxf")],
    "ps":     [("mpeg", "mpg")],
    "ts":     [("mpegts", "ts")],
    "3gp":    [("3gp", "3gp")],
    "3g2":    [("3g2", "3g2")],
    "webm":   [("webm", "webm")],
    "mp3":    [("mp3", "mp3")],
    "m4a":    [("ipod", "m4a")],
    "ogg":    [("ogg", "ogg")],
    "wav":    [("wav", "wav")],
    "flac":   [("flac", "flac")],
    "flv":    [("flv", "flv")],
    "apng":   [("apng", "apng")],
    "webp":   [("webp", "webp")],
    "gif":    [("gif", "gif")],
    "opus":   [("opus", "opus")],
}

# MXF exige un track de video como primero y unico, y audio a 48kHz. Si el codec bajo
# prueba es de audio, se lo empareja automaticamente con este video minimo valido.
MXF_COMPANION_VIDEO_ENCODER = "mpeg2video"
MXF_REQUIRED_AUDIO_RATE = 48000

# ─── Codecs de video ───
# codec_id: identificador interno de ffmpeg (el que usa hardware_detector.py / -codecs).
# encoder: encoder de software a usar para generarlo. None = sin encoder en este build,
#          no verificable empiricamente (se documenta el motivo, no se asume nada).
VIDEO_CODECS = {
    "hevc":        dict(codec_id="hevc", wiki="MPEG-H HEVC (H.265)", encoder="libx265", size="256x256"),
    "h264":        dict(codec_id="h264", wiki="MPEG-4 AVC (H.264)", encoder="libx264", size="256x256"),
    "av1":         dict(codec_id="av1", wiki="AV1", encoder="libsvtav1", size="256x256"),
    "vp9":         dict(codec_id="vp9", wiki="VP9", encoder="libvpx-vp9", size="256x256"),
    "vp8":         dict(codec_id="vp8", wiki="VP8", encoder="libvpx", size="256x256"),
    "dirac":       dict(codec_id="dirac", wiki="Dirac", encoder="vc2", size="256x256",
                         note="Probado con vc2 (SMPTE VC-2, sucesor directo de Dirac)."),
    "mvc":         dict(codec_id="mvc", wiki="MVC", encoder=None, skip_reason="Sin encoder MVC en ffmpeg (decode-only)."),
    "mpeg1video":  dict(codec_id="mpeg1video", wiki="MPEG-1 Video", encoder="mpeg1video", size="256x256"),
    "mpeg2video":  dict(codec_id="mpeg2video", wiki="MPEG-2 Video", encoder="mpeg2video", size="256x256"),
    "mpeg4":       dict(codec_id="mpeg4", wiki="MPEG-4 Visual", encoder="mpeg4", size="256x256"),
    "msmpeg4v2":   dict(codec_id="msmpeg4v2", wiki="Microsoft MPEG4 V2", encoder="msmpeg4v2", size="256x256"),
    "vc1":         dict(codec_id="vc1", wiki="VC-1", encoder=None, skip_reason="Sin encoder VC-1 en ffmpeg (decode-only)."),
    "h263":        dict(codec_id="h263", wiki="H.263", encoder="h263", size="176x144",
                         note="H.263 baseline exige resoluciones fijas (QCIF/CIF)."),
    "theora":      dict(codec_id="theora", wiki="Theora", encoder="libtheora", size="256x256"),
    "cinepak":     dict(codec_id="cinepak", wiki="Cinepak", encoder="cinepak", size="256x256"),
    "svq1":        dict(codec_id="svq1", wiki="Sorenson", encoder="svq1", size="256x256", pix_fmt="yuv410p",
                         note="Sorenson Video 1. Sorenson Video 3 no tiene encoder en ffmpeg."),
    "rv10":        dict(codec_id="rv10", wiki="RealVideo", encoder="rv10", size="176x144",
                         note="Solo RealVideo 1.0. RV20 existe pero RV30/RV40/RV60 no tienen encoder en ffmpeg."),
    "vp6":         dict(codec_id="vp6", wiki="VP6", encoder=None, skip_reason="Sin encoder VP6 en ffmpeg (decode-only)."),
    "dvvideo":     dict(codec_id="dvvideo", wiki="DV", encoder="dvvideo", size="720x576", pix_fmt="yuv420p", fps="25",
                         note="Probado como DV25 PAL (720x576@25)."),
    "mjpeg":       dict(codec_id="mjpeg", wiki="M-JPEG", encoder="mjpeg", size="256x256", pix_fmt="yuvj420p"),
    "jpeg2000":    dict(codec_id="jpeg2000", wiki="MJ2", encoder="jpeg2000", size="256x256"),
    "prores":      dict(codec_id="prores", wiki="Apple ProRes", encoder="prores_ks", size="256x256", pix_fmt="yuv422p10le"),
    "huffyuv":     dict(codec_id="huffyuv", wiki="HuffYUV", encoder="huffyuv", size="256x256", pix_fmt="yuv422p"),
    "rawvideo":    dict(codec_id="rawvideo", wiki="YCbCr", encoder="rawvideo", size="256x256", pix_fmt="yuv422p10le",
                         note="Representa 'YCbCr sin comprimir' de forma generica (Wikipedia refiere variantes especificas como v210/SheerVideo)."),
    "dnxhd":       dict(codec_id="dnxhd", wiki=None, display_name="DNxHD / DNxHR", encoder="dnxhd", size="1920x1080", pix_fmt="yuv422p", fps="25",
                         extra=["-b:v", "36M"],
                         note="No esta en la tabla de Wikipedia original; agregado por relevancia para editores NLE. Perfil 1080p25@36Mbps."),
    "gif":         dict(codec_id="gif", wiki="GIF", encoder="gif", size="256x256"),
    # libwebp_anim y no libwebp: los dos producen WebP ANIMADO en el muxer webp, pero
    # _anim comprime entre fotogramas (~7% menos peso medido con ffmpeg 9.0.1).
    "webp":        dict(codec_id="webp", wiki="WebP", encoder="libwebp_anim", size="256x256"),
    "apng":        dict(codec_id="apng", wiki="APNG", encoder="apng", size="256x256"),
    "ffv1":        dict(codec_id="ffv1", wiki="FFV1", encoder="ffv1", size="256x256"),
    "utvideo":     dict(codec_id="utvideo", wiki="Ut Video", encoder="utvideo", size="256x256", pix_fmt="yuv420p"),
    "cfhd":        dict(codec_id="cfhd", wiki="CineForm HD", encoder="cfhd", size="256x256", pix_fmt="yuv422p10le"),
    "wmv1":        dict(codec_id="wmv1", wiki="Windows Media Video 7", encoder="wmv1", size="256x256"),
    "wmv2":        dict(codec_id="wmv2", wiki="Windows Media Video 8", encoder="wmv2", size="256x256"),
    "flv1":        dict(codec_id="flv1", wiki="Sorenson Spark", encoder="flv", size="256x256"),
    # Agregados por transparencia (canal alfa): los tres la conservan -- ver ALPHA_OVERRIDES.
    "qtrle":       dict(codec_id="qtrle", wiki=None, display_name="QuickTime Animation", encoder="qtrle",
                         size="256x256", note="Sin perdida (RLE). Clasico de After Effects/Premiere para video con alfa."),
    "png":         dict(codec_id="png", wiki=None, display_name="PNG (video)", encoder="png", size="256x256",
                         note="Cada fotograma es un PNG: sin perdida, con alfa, archivos grandes."),
    "hap":         dict(codec_id="hap", wiki=None, display_name="HAP (Vidvox)", encoder="hap", size="256x256",
                         extra=["-format", "hap"],
                         note="Para reproduccion en tiempo real (VJ, Resolume, TouchDesigner). Ancho y alto multiplos de 4."),
}

# ─── Transparencia (canal alfa) ───
# Eje aparte del matrix (ver run_matrix.py::probe_alpha): para cada codec de video y cada
# contenedor donde el mux base ya paso, se codifica un origen RGBA con 3 franjas de alfa
# conocido (0 / 128 / 255), se DECODIFICA el resultado y se lee el alfa real. No se confia
# en el pix_fmt que reporta ffprobe: VP8/VP9 guardan el alfa aparte y ffprobe dice yuv420p.
#
# ALPHA_OVERRIDES: lo que un codec EXIGE para conservar alfa, verificado a mano contra
# ffmpeg 9.0.1 antes de volcarlo aca. Un codec sin entrada se prueba sin -pix_fmt: ffmpeg
# elige solo el formato mas cercano al RGBA de origen (con alfa si el encoder tiene uno),
# y si eso no codifica se reintenta con el pix_fmt del spec base -- asi no se esconde un
# soporte de alfa que nadie haya anotado todavia.
ALPHA_OVERRIDES = {
    "vp9":     dict(pix_fmt="yuva420p", extra=["-b:v", "0", "-crf", "30"]),
    # Sin -auto-alt-ref 0 libvpx (VP8) se niega a abrir: "Transparency encoding with
    # auto_alt_ref does not work".
    "vp8":     dict(pix_fmt="yuva420p", extra=["-b:v", "1M", "-auto-alt-ref", "0"]),
    # 4444 (perfil 4) con yuva: el spec base usa yuv422p10le (422, que no admite alfa).
    "prores":  dict(pix_fmt="yuva444p10le", extra=["-profile:v", "4"]),
    "cfhd":    dict(pix_fmt="gbrap12le"),
    "utvideo": dict(pix_fmt="gbrap"),
    "huffyuv": dict(pix_fmt="bgra"),
    "ffv1":    dict(pix_fmt="yuva420p"),
    "apng":    dict(pix_fmt="rgba"),
    "webp":    dict(pix_fmt="yuva420p"),
    "qtrle":   dict(pix_fmt="argb"),
    "png":     dict(pix_fmt="rgba"),
    # HAP normal (DXT1) no tiene alfa: hace falta la variante hap_alpha.
    "hap":     dict(pix_fmt=None, extra=["-format", "hap_alpha"]),
    # GIF: paleta de 256 colores con un indice reservado para "transparente" (lo que ya
    # hacen los perfiles Alta/Media de DowP). El resultado esperado es alfa de 1 bit.
    "gif":     dict(pix_fmt=None, extra=["-vf", "split[s0][s1];[s0]palettegen=stats_mode=full:max_colors=256"
                                                "[p];[s1][p]paletteuse=dither=floyd_steinberg"]),
}

# Decoder con el que hay que LEER el resultado para que el alfa aparezca: el decoder
# nativo de ffmpeg para VP8/VP9 ignora el canal alfa (lo descarta sin avisar).
ALPHA_DECODERS = {"vp9": "libvpx-vp9", "vp8": "libvpx"}

# Candidato con alfa que HOY no esta en VIDEO_CODECS: magicyuv (gbrap, AVI/MKV) -- no se
# agrego porque sin perdida ya estan UT Video, FFV1 y HuffYUV.

# ─── Codecs de audio ───
AUDIO_CODECS = {
    "aac":        dict(codec_id="aac", wiki="AAC", encoder="aac"),
    "mp3":        dict(codec_id="mp3", wiki="MP3", encoder="libmp3lame"),
    "ac3":        dict(codec_id="ac3", wiki="AC-3", encoder="ac3"),
    "eac3":       dict(codec_id="eac3", wiki="E-AC-3", encoder="eac3"),
    "dts":        dict(codec_id="dts", wiki="DTS", encoder="dca", extra=["-strict", "-2"]),
    "wmav2":      dict(codec_id="wmav2", wiki="WMA", encoder="wmav2"),
    "opus":       dict(codec_id="opus", wiki="Opus", encoder="libopus"),
    "vorbis":     dict(codec_id="vorbis", wiki="Vorbis", encoder="libvorbis"),
    "mp2":        dict(codec_id="mp2", wiki="MP2", encoder="mp2"),
    "mp1":        dict(codec_id="mp1", wiki="MP1", encoder=None, skip_reason="Sin encoder MPEG-1 Layer 1 en ffmpeg."),
    "qdm2":       dict(codec_id="qdm2", wiki="QDesign Music 1 and 2", encoder=None, skip_reason="Sin encoder QDesign en ffmpeg (decode-only)."),
    "atrac3":     dict(codec_id="atrac3", wiki="ATRAC3", encoder=None, skip_reason="Sin encoder ATRAC3 en ffmpeg (decode-only)."),
    "flac":       dict(codec_id="flac", wiki="FLAC", encoder="flac"),
    "alac":       dict(codec_id="alac", wiki="ALAC", encoder="alac"),
    "wmalossless": dict(codec_id="wmalossless", wiki="WMA Lossless", encoder=None, skip_reason="Sin encoder WMA Lossless en ffmpeg."),
    "dts_hd":     dict(codec_id="dts_hd", wiki="DTS-HD", encoder=None, skip_reason="El encoder 'dca' solo produce DTS core, no la extension DTS-HD MA."),
    "truehd":     dict(codec_id="truehd", wiki="Dolby TrueHD", encoder="truehd", extra=["-strict", "-2"]),
    "mlp":        dict(codec_id="mlp", wiki="MLP", encoder="mlp", extra=["-strict", "-2"]),
    "mp4als":     dict(codec_id="mp4als", wiki="ALS", encoder=None, skip_reason="Sin encoder MPEG-4 ALS en ffmpeg."),
    "sls":        dict(codec_id="sls", wiki="SLS", encoder=None, skip_reason="Sin encoder MPEG-4 SLS en ffmpeg."),
    "pcm_s24le":  dict(codec_id="pcm_s24le", wiki="LPCM", encoder="pcm_s24le",
                        note="Representa LPCM generico, little-endian. Variantes big-endian (AIFF-style) pueden diferir por contenedor."),
    "pcm_alaw":   dict(codec_id="pcm_alaw", wiki="A-law PCM", encoder="pcm_alaw"),
    "pcm_mulaw":  dict(codec_id="pcm_mulaw", wiki="μ-law PCM", encoder="pcm_mulaw"),
    "pcm_f32le":  dict(codec_id="pcm_f32le", wiki="IEEE floating-point PCM", encoder="pcm_f32le"),
    "adpcm_ms":   dict(codec_id="adpcm_ms", wiki="Microsoft ADPCM", encoder="adpcm_ms"),
    "amr_nb":     dict(codec_id="amr_nb", wiki="AMR", encoder="libopencore_amrnb", ar=8000, ac=1,
                        note="AMR-NB (8kHz mono). AMR-WB no se prueba por separado."),
    "g728":       dict(codec_id="g728", wiki="G.728", encoder=None, skip_reason="Sin encoder G.728 en ffmpeg."),
    "speex":      dict(codec_id="speex", wiki="Speex", encoder="libspeex"),
    "qcelp":      dict(codec_id="qcelp", wiki="QCELP", encoder=None, skip_reason="Sin encoder QCELP en ffmpeg (decode-only)."),
    "pcm_s16le":  dict(codec_id="pcm_s16le", wiki="LPCM", encoder="pcm_s16le"),
    "wavpack":    dict(codec_id="wavpack", wiki="WavPack", encoder="wavpack"),
    "amr_wb":     dict(codec_id="amr_wb", wiki="AMR-WB", encoder="libvo_amrwbenc", ar=16000, ac=1),
}
