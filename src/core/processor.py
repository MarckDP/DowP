import json
import tempfile
import subprocess
import threading
import os
import re
import sys
import time
from .exceptions import UserCancelledError
from main import FFMPEG_BIN_DIR

CODEC_PROFILES = {
    "Video": {
        "H.264 (x264)": {
            "libx264": {
                "Alta Calidad (CRF 18)": ['-c:v', 'libx264', '-preset', 'slow', '-crf', '18', '-pix_fmt', 'yuv420p'],
                "Calidad Media (CRF 23)": ['-c:v', 'libx264', '-preset', 'medium', '-crf', '23', '-pix_fmt', 'yuv420p'],
                "Calidad Rápida (CRF 28)": ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '28', '-pix_fmt', 'yuv420p'],
                "Bitrate Personalizado (VBR)": "CUSTOM_BITRATE_VBR",
                "Bitrate Personalizado (CBR)": "CUSTOM_BITRATE_CBR"
            }, "container": ".mp4"
        },
        "H.265 (x265)": {
            "libx265": {
                "Calidad Alta (CRF 20)": ['-c:v', 'libx265', '-preset', 'slow', '-crf', '20', '-tag:v', 'hvc1'],
                "Calidad Media (CRF 24)": ['-c:v', 'libx265', '-preset', 'medium', '-crf', '24', '-tag:v', 'hvc1'],
                "Bitrate Personalizado (VBR)": "CUSTOM_BITRATE_VBR",
                "Bitrate Personalizado (CBR)": "CUSTOM_BITRATE_CBR"
            }, "container": ".mp4"
        },
        "Apple ProRes (prores_aw) (Velocidad)": {
            "prores_aw": {
                "422 Proxy":    ['-c:v', 'prores_aw', '-profile:v', '0', '-pix_fmt', 'yuv422p10le', '-threads', '0'],
                "422 LT":       ['-c:v', 'prores_aw', '-profile:v', '1', '-pix_fmt', 'yuv422p10le', '-threads', '0'],
                "422 Standard": ['-c:v', 'prores_aw', '-profile:v', '2', '-pix_fmt', 'yuv422p10le', '-threads', '0'],
                "422 HQ":       ['-c:v', 'prores_aw', '-profile:v', '3', '-pix_fmt', 'yuv422p10le', '-threads', '0'],
                "4444":         ['-c:v', 'prores_aw', '-profile:v', '4', '-pix_fmt', 'yuv444p10le', '-threads', '0'],
                "4444 XQ":      ['-c:v', 'prores_aw', '-profile:v', '5', '-pix_fmt', 'yuv444p10le', '-threads', '0']
            }, "container": ".mov"
        },
        "Apple ProRes (prores_ks) (Precisión)": {
            "prores_ks": {
                "422 Proxy":    ['-c:v', 'prores_ks', '-profile:v', '0', '-pix_fmt', 'yuv422p10le', '-threads', '0'],
                "422 LT":       ['-c:v', 'prores_ks', '-profile:v', '1', '-pix_fmt', 'yuv422p10le', '-threads', '0'],
                "422 Standard": ['-c:v', 'prores_ks', '-profile:v', '2', '-pix_fmt', 'yuv422p10le', '-threads', '0'],
                "422 HQ":       ['-c:v', 'prores_ks', '-profile:v', '3', '-pix_fmt', 'yuv422p10le', '-threads', '0'],
                "4444":         ['-c:v', 'prores_ks', '-profile:v', '4', '-pix_fmt', 'yuv444p10le', '-threads', '0'],
                "4444 XQ":      ['-c:v', 'prores_ks', '-profile:v', '5', '-pix_fmt', 'yuv444p10le', '-threads', '0']
            }, "container": ".mov"
        },
        "DNxHD (dnxhd)": {
            "dnxhd": {
                "1080p25 (145 Mbps)":     ['-c:v', 'dnxhd', '-b:v', '145M', '-pix_fmt', 'yuv422p'],
                "1080p29.97 (145 Mbps)":  ['-c:v', 'dnxhd', '-b:v', '145M', '-pix_fmt', 'yuv422p'],
                "1080i50 (120 Mbps)":     ['-c:v', 'dnxhd', '-b:v', '120M', '-pix_fmt', 'yuv422p', '-flags', '+ildct+ilme', '-top', '1'],
                "1080i59.94 (120 Mbps)":  ['-c:v', 'dnxhd', '-b:v', '120M', '-pix_fmt', 'yuv422p', '-flags', '+ildct+ilme', '-top', '1'],
                "720p50 (90 Mbps)":       ['-c:v', 'dnxhd', '-b:v', '90M', '-pix_fmt', 'yuv422p'],
                "720p59.94 (90 Mbps)":    ['-c:v', 'dnxhd', '-b:v', '90M', '-pix_fmt', 'yuv422p']
            }, "container": ".mov"
        },
        "DNxHR (dnxhd)": {
            "dnxhd": {
                "LB (8-bit 4:2:2)":    ['-c:v', 'dnxhd', '-profile:v', 'dnxhr_lb', '-pix_fmt', 'yuv422p'],
                "SQ (8-bit 4:2:2)":    ['-c:v', 'dnxhd', '-profile:v', 'dnxhr_sq', '-pix_fmt', 'yuv422p'],
                "HQ (8-bit 4:2:2)":    ['-c:v', 'dnxhd', '-profile:v', 'dnxhr_hq', '-pix_fmt', 'yuv422p'],
                "HQX (10-bit 4:2:2)":  ['-c:v', 'dnxhd', '-profile:v', 'dnxhr_hqx', '-pix_fmt', 'yuv422p10le'],
                "444 (10-bit 4:4:4)":  ['-c:v', 'dnxhd', '-profile:v', 'dnxhr_444', '-pix_fmt', 'yuv444p10le']
            }, "container": ".mov"
        },
        "VP8 (libvpx)": {
             "libvpx": {
                "Calidad Alta (CRF 10)": ['-c:v', 'libvpx', '-crf', '10', '-b:v', '0'],
                "Calidad Media (CRF 20)": ['-c:v', 'libvpx', '-crf', '20', '-b:v', '0'],
                "Bitrate Personalizado (VBR)": "CUSTOM_BITRATE_VBR"
             }, "container": ".webm"
        },
        "VP9 (libvpx-vp9)": {
            "libvpx-vp9": {
                "Calidad Alta (CRF 28)": ['-c:v', 'libvpx-vp9', '-crf', '28', '-b:v', '0'],
                "Calidad Media (CRF 33)": ['-c:v', 'libvpx-vp9', '-crf', '33', '-b:v', '0'],
                "Bitrate Personalizado (VBR)": "CUSTOM_BITRATE_VBR"
            }, "container": ".webm"
        },
        "AV1 (libaom-av1)": {
            "libaom-av1": {
                "Calidad Alta (CRF 28)": ['-c:v', 'libaom-av1', '-strict', 'experimental', '-cpu-used', '4', '-crf', '28'],
                "Calidad Media (CRF 35)": ['-c:v', 'libaom-av1', '-strict', 'experimental', '-cpu-used', '6', '-crf', '35'],
                "Bitrate Personalizado (VBR)": "CUSTOM_BITRATE_VBR"
            }, "container": ".mkv"
        },
        "H.264 (NVIDIA NVENC)": {
            "h264_nvenc": {
                # AÑADIDO: '-pix_fmt', 'yuv420p' al final de las listas
                "Calidad Alta (CQP 18)": ['-c:v', 'h264_nvenc', '-preset', 'p7', '-rc', 'vbr', '-cq', '18', '-pix_fmt', 'yuv420p'],
                "Calidad Media (CQP 23)": ['-c:v', 'h264_nvenc', '-preset', 'p5', '-rc', 'vbr', '-cq', '23', '-pix_fmt', 'yuv420p'],
                "Bitrate Personalizado (VBR)": "CUSTOM_BITRATE_VBR",
                "Bitrate Personalizado (CBR)": "CUSTOM_BITRATE_CBR"
            }, "container": ".mp4"
        },
        "H.265/HEVC (NVIDIA NVENC)": {
            "hevc_nvenc": {
                "Calidad Alta (CQP 20)": ['-c:v', 'hevc_nvenc', '-preset', 'p7', '-rc', 'vbr', '-cq', '20', '-pix_fmt', 'yuv420p'],
                "Calidad Media (CQP 24)": ['-c:v', 'hevc_nvenc', '-preset', 'p5', '-rc', 'vbr', '-cq', '24', '-pix_fmt', 'yuv420p'],
                "Bitrate Personalizado (VBR)": "CUSTOM_BITRATE_VBR",
                "Bitrate Personalizado (CBR)": "CUSTOM_BITRATE_CBR"
            }, "container": ".mp4"
        },
        "AV1 (NVENC)": {
            "av1_nvenc": {
                "Calidad Alta (CQP 24)": ['-c:v', 'av1_nvenc', '-preset', 'p7', '-rc', 'vbr', '-cq', '24'],
                "Calidad Media (CQP 28)": ['-c:v', 'av1_nvenc', '-preset', 'p5', '-rc', 'vbr', '-cq', '28'],
                "Bitrate Personalizado (VBR)": "CUSTOM_BITRATE_VBR",
                "Bitrate Personalizado (CBR)": "CUSTOM_BITRATE_CBR"
            }, "container": ".mp4"
        },
        "H.264 (AMD AMF)": {
            "h264_amf": {
                # AÑADIDO: '-pix_fmt', 'yuv420p'
                "Alta Calidad": ['-c:v', 'h264_amf', '-quality', 'quality', '-rc', 'cqp', '-qp_i', '18', '-qp_p', '18', '-pix_fmt', 'yuv420p'],
                "Calidad Balanceada": ['-c:v', 'h264_amf', '-quality', 'balanced', '-rc', 'cqp', '-qp_i', '23', '-qp_p', '23', '-pix_fmt', 'yuv420p'],
                "Bitrate Personalizado (VBR)": "CUSTOM_BITRATE_VBR",
                "Bitrate Personalizado (CBR)": "CUSTOM_BITRATE_CBR"
            }, "container": ".mp4"
        },
        "H.265/HEVC (Intel QSV)": {
            "hevc_qsv": {
                "Alta Calidad": ['-c:v', 'hevc_qsv', '-preset', 'veryslow', '-global_quality', '20', '-pix_fmt', 'yuv420p'],
                "Calidad Media": ['-c:v', 'hevc_qsv', '-preset', 'medium', '-global_quality', '24', '-pix_fmt', 'yuv420p'],
                "Bitrate Personalizado (VBR)": "CUSTOM_BITRATE_VBR",
                "Bitrate Personalizado (CBR)": "CUSTOM_BITRATE_CBR"
            }, "container": ".mp4"
        },
        "AV1 (AMF)": {
            "av1_amf": {
                "Alta Calidad": ['-c:v', 'av1_amf', '-quality', 'quality', '-rc', 'cqp', '-qp_i', '28', '-qp_p', '28'],
                "Calidad Balanceada": ['-c:v', 'av1_amf', '-quality', 'balanced', '-rc', 'cqp', '-qp_i', '32', '-qp_p', '32'],
                "Bitrate Personalizado (VBR)": "CUSTOM_BITRATE_VBR",
                "Bitrate Personalizado (CBR)": "CUSTOM_BITRATE_CBR"
            }, "container": ".mp4"
        },
        "H.264 (Intel QSV)": {
            "h264_qsv": {
                # AÑADIDO: '-pix_fmt', 'yuv420p'
                "Alta Calidad": ['-c:v', 'h264_qsv', '-preset', 'veryslow', '-global_quality', '18', '-pix_fmt', 'yuv420p'],
                "Calidad Media": ['-c:v', 'h264_qsv', '-preset', 'medium', '-global_quality', '23', '-pix_fmt', 'yuv420p'],
                "Bitrate Personalizado (VBR)": "CUSTOM_BITRATE_VBR",
                "Bitrate Personalizado (CBR)": "CUSTOM_BITRATE_CBR"
            }, "container": ".mp4"
        },
        "H.265/HEVC (Intel QSV)": {
            "hevc_qsv": {
                "Alta Calidad": ['-c:v', 'hevc_qsv', '-preset', 'veryslow', '-global_quality', '20'],
                "Calidad Media": ['-c:v', 'hevc_qsv', '-preset', 'medium', '-global_quality', '24'],
                "Bitrate Personalizado (VBR)": "CUSTOM_BITRATE_VBR",
                "Bitrate Personalizado (CBR)": "CUSTOM_BITRATE_CBR"
            }, "container": ".mp4"
        },
        "AV1 (QSV)": {
            "av1_qsv": {
                "Calidad Alta": ['-c:v', 'av1_qsv', '-global_quality', '25', '-preset', 'slow'],
                "Calidad Media": ['-c:v', 'av1_qsv', '-global_quality', '30', '-preset', 'medium'],
                "Bitrate Personalizado (VBR)": "CUSTOM_BITRATE_VBR",
                "Bitrate Personalizado (CBR)": "CUSTOM_BITRATE_CBR"
            }, "container": ".mp4"
        },
        "VP9 (QSV)": {
            "vp9_qsv": {
                "Calidad Alta": ['-c:v', 'vp9_qsv', '-global_quality', '25', '-preset', 'slow'],
                "Calidad Media": ['-c:v', 'vp9_qsv', '-global_quality', '30', '-preset', 'medium'],
                "Bitrate Personalizado (VBR)": "CUSTOM_BITRATE_VBR",
                "Bitrate Personalizado (CBR)": "CUSTOM_BITRATE_CBR"
            }, "container": ".mp4"
        },
        "H.264 (Apple VideoToolbox)": {
            "h264_videotoolbox": {
                "Alta Calidad": ['-c:v', 'h264_videotoolbox', '-profile:v', 'high', '-q:v', '70'],
                "Calidad Media": ['-c:v', 'h264_videotoolbox', '-profile:v', 'main', '-q:v', '50'],
                "Bitrate Personalizado (CBR)": "CUSTOM_BITRATE_CBR"
            }, "container": ".mp4"
        },
        "H.265/HEVC (Apple VideoToolbox)": {
            "hevc_videotoolbox": {
                "Alta Calidad": ['-c:v', 'hevc_videotoolbox', '-profile:v', 'main', '-q:v', '80'],
                "Calidad Media": ['-c:v', 'hevc_videotoolbox', '-profile:v', 'main', '-q:v', '65'],
                "Bitrate Personalizado (CBR)": "CUSTOM_BITRATE_CBR"
            }, "container": ".mp4"
        },
        "GIF (animado)": {
            "gif": { 
                "Baja Calidad (Rápido)": ['-vf', 'fps=15,scale=480:-1'],
                "Calidad Web (480p, 15fps)": ['-filter_complex', '[0:v] fps=15,scale=480:-1,split [a][b];[a] palettegen [p];[b][p] paletteuse'],
                "Calidad Media (540p, 24fps)": ['-filter_complex', '[0:v] fps=24,scale=540:-1,split [a][b];[a] palettegen [p];[b][p] paletteuse'],
                "Calidad Alta (720p, 30fps)": ['-filter_complex', '[0:v] fps=30,scale=720:-1,split [a][b];[a] palettegen [p];[b][p] paletteuse'],
                "Personalizado": "CUSTOM_GIF" 
            }, "container": ".gif"
        },
        "XDCAM HD422": {
            "mpeg2video": {
                "1080i50 (50 Mbps)": ['-c:v', 'mpeg2video', '-pix_fmt', 'yuv422p', '-b:v', '50M', '-flags', '+ildct+ilme', '-top', '1', '-minrate', '50M', '-maxrate', '50M'],
                "1080p25 (50 Mbps)": ['-c:v', 'mpeg2video', '-pix_fmt', 'yuv422p', '-b:v', '50M', '-minrate', '50M', '-maxrate', '50M'],
                "720p50 (50 Mbps)":  ['-c:v', 'mpeg2video', '-pix_fmt', 'yuv422p', '-b:v', '50M', '-minrate', '50M', '-maxrate', '50M']
            }, "container": ".mxf"
        },
        "XDCAM HD 35": {
            "mpeg2video": {
                "1080i50 (35 Mbps)": ['-c:v', 'mpeg2video', '-pix_fmt', 'yuv420p', '-b:v', '35M', '-flags', '+ildct+ilme', '-top', '1', '-minrate', '35M', '-maxrate', '35M'],
                "1080p25 (35 Mbps)": ['-c:v', 'mpeg2video', '-pix_fmt', 'yuv420p', '-b:v', '35M', '-minrate', '35M', '-maxrate', '35M'],
                "720p50 (35 Mbps)":  ['-c:v', 'mpeg2video', '-pix_fmt', 'yuv420p', '-b:v', '35M', '-minrate', '35M', '-maxrate', '35M']
            }, "container": ".mxf"
        },
        "AVC-Intra 100 (x264)": {
            "libx264": {
                "1080p (100 Mbps)": ['-c:v', 'libx264', '-preset', 'veryfast', '-profile:v', 'high422', '-level', '4.1', '-b:v', '100M', '-minrate', '100M', '-maxrate', '100M', '-bufsize', '2M', '-g', '1', '-keyint_min', '1', '-pix_fmt', 'yuv422p10le'],
                "720p (50 Mbps)":   ['-c:v', 'libx264', '-preset', 'veryfast', '-profile:v', 'high422', '-level', '3.1', '-b:v', '50M', '-minrate', '50M', '-maxrate', '50M', '-bufsize', '1M', '-g', '1', '-keyint_min', '1', '-pix_fmt', 'yuv422p10le']
            }, "container": ".mov"
        },
        "GoPro CineForm": {
            "cfhd": {
                "Baja": ['-c:v', 'cfhd', '-quality', '1'], "Media": ['-c:v', 'cfhd', '-quality', '4'], "Alta": ['-c:v', 'cfhd', '-quality', '6']
            }, "container": ".mov"
        },
        "QT Animation (qtrle)": { "qtrle": { "Estándar": ['-c:v', 'qtrle'] }, "container": ".mov" },
        "HAP": { "hap": { "Estándar": ['-c:v', 'hap'] }, "container": ".mov" },
    },
    "Audio": {
        "AAC": {
            "aac": {
                "Alta Calidad (~256kbps)": ['-c:a', 'aac', '-b:a', '256k'],
                "Buena Calidad (~192kbps)": ['-c:a', 'aac', '-b:a', '192k'],
                "Calidad Media (~128kbps)": ['-c:a', 'aac', '-b:a', '128k']
            }, "container": ".m4a"
        },
        "MP3 (libmp3lame)": {
            "libmp3lame": {
                "320kbps (CBR)": ['-c:a', 'libmp3lame', '-b:a', '320k'],
                "256kbps (VBR)": ['-c:a', 'libmp3lame', '-q:a', '0'],
                "192kbps (CBR)": ['-c:a', 'libmp3lame', '-b:a', '192k']
            }, "container": ".mp3"
        },
        "Opus (libopus)": {
            "libopus": {
                "Calidad Transparente (~256kbps)": ['-c:a', 'libopus', '-b:a', '256k'],
                "Calidad Alta (~192kbps)": ['-c:a', 'libopus', '-b:a', '192k'],
                "Calidad Media (~128kbps)": ['-c:a', 'libopus', '-b:a', '128k']
            }, "container": ".opus"
        },
        "Vorbis (libvorbis)": {
            "libvorbis": {
                "Calidad Muy Alta (q8)": ['-c:a', 'libvorbis', '-q:a', '8'],
                "Calidad Alta (q6)": ['-c:a', 'libvorbis', '-q:a', '6'],
                "Calidad Media (q4)": ['-c:a', 'libvorbis', '-q:a', '4']
            }, "container": ".ogg"
        },
        "AC-3 (Dolby Digital)": {
            "ac3": {
                "Stereo (192kbps)": ['-c:a', 'ac3', '-b:a', '192k'],
                "Stereo (256kbps)": ['-c:a', 'ac3', '-b:a', '256k'],
                "Surround 5.1 (448kbps)": ['-c:a', 'ac3', '-b:a', '448k', '-ac', '6'],
                "Surround 5.1 (640kbps)": ['-c:a', 'ac3', '-b:a', '640k', '-ac', '6']
            }, "container": ".ac3"
        },
        "ALAC (Apple Lossless)": {
            "alac": {
                "Estándar (Sin Pérdida)": ['-c:a', 'alac']
            }, "container": ".m4a"
        },
        "FLAC (Sin Pérdida)": {
            "flac": {
                "Nivel de Compresión 5": ['-c:a', 'flac', '-compression_level', '5'],
                "Nivel de Compresión 8 (Más Lento)": ['-c:a', 'flac', '-compression_level', '8']
            }, "container": ".flac"
        },
        "WAV (Sin Comprimir)": {
            "pcm_s16le": {
                "PCM 16-bit": ['-c:a', 'pcm_s16le'],
                "PCM 24-bit": ['-c:a', 'pcm_s24le']
            }, "container": ".wav"
        },
        "WMA v2 (Windows Media)": {
            "wmav2": {
                "Calidad Alta (192kbps)": ['-c:a', 'wmav2', '-b:a', '192k'],
                "Calidad Media (128kbps)": ['-c:a', 'wmav2', '-b:a', '128k']
            }, "container": ".wma"
        }
    }
}

class FFmpegProcessor:
    def __init__(self):
        ffmpeg_exe_name = "ffmpeg.exe" if os.name == 'nt' else "ffmpeg"
        self.ffmpeg_path = os.path.join(FFMPEG_BIN_DIR, ffmpeg_exe_name)

        self.gpu_vendor = None
        self.is_detection_complete = False
        self.available_encoders = {"CPU": {"Video": {}, "Audio": {}}, "GPU": {"Video": {}}}
        self.current_process = None
    def cancel_current_process(self):
        """
        Cancela el proceso de FFmpeg que se esté ejecutando actualmente.
        """
        if self.current_process and self.current_process.poll() is None:
            print("DEBUG: Enviando señal de terminación al proceso de FFmpeg...")
            try:
                self.current_process.terminate()
                self.current_process.wait(timeout=5) 
                print("DEBUG: Proceso de FFmpeg terminado.")
            except Exception as e:
                print(f"ERROR: No se pudo terminar el proceso de FFmpeg: {e}")
            self.current_process = None

    def run_detection_async(self, callback):
        threading.Thread(target=self._detect_encoders, args=(callback,), daemon=True).start()

    def _detect_encoders(self, callback):
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            
            subprocess.check_output(
                [self.ffmpeg_path, '-version'], 
                stderr=subprocess.STDOUT, 
                creationflags=creationflags,
                cwd=os.path.dirname(self.ffmpeg_path) 
            )
            
            all_encoders_output = subprocess.check_output(
                [self.ffmpeg_path, '-encoders'], 
                text=True, 
                encoding='utf-8', 
                stderr=subprocess.STDOUT, 
                creationflags=creationflags,
                cwd=os.path.dirname(self.ffmpeg_path)
            )
            
            try:
                if getattr(sys, 'frozen', False):
                    base_path = os.path.dirname(sys.executable)
                else:
                    base_path = os.path.dirname(os.path.abspath(__file__))
                log_path = os.path.join(base_path, "ffmpeg_encoders_log.txt")
                with open(log_path, "w", encoding="utf-8") as f:
                    f.write("--- ENCODERS DETECTADOS POR FFmpeg ---\n")
                    f.write(all_encoders_output)
                print(f"DEBUG: Se ha guardado un registro de los códecs de FFmpeg en {log_path}")
            except Exception as e:
                print(f"ADVERTENCIA: No se pudo escribir el log de códecs de FFmpeg: {e}")
                
            for category, codecs in CODEC_PROFILES.items():
                for friendly_name, details in codecs.items():
                    ffmpeg_codec_name = next((key for key in details if key != 'container'), None)
                    if not ffmpeg_codec_name:
                        continue 
                    search_pattern = r"^\s[A-Z\.]{6}\s+" + re.escape(ffmpeg_codec_name) + r"\s"
                    if re.search(search_pattern, all_encoders_output, re.MULTILINE):
                        proc_type = "GPU" if "nvenc" in ffmpeg_codec_name or "qsv" in ffmpeg_codec_name or "amf" in ffmpeg_codec_name or "videotoolbox" in ffmpeg_codec_name else "CPU"
                        if proc_type == "GPU" and self.gpu_vendor is None:
                            if "nvenc" in ffmpeg_codec_name: self.gpu_vendor = "NVIDIA"
                            elif "qsv" in ffmpeg_codec_name: self.gpu_vendor = "Intel"
                            elif "amf" in ffmpeg_codec_name: self.gpu_vendor = "AMD"
                            elif "videotoolbox" in ffmpeg_codec_name: self.gpu_vendor = "Apple"
                        target_category = self.available_encoders[proc_type].get(category, {})
                        target_category[friendly_name] = details
                        self.available_encoders[proc_type][category] = target_category
                        
            self.is_detection_complete = True
            callback(True, "Detección completada.")
            
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
            self.is_detection_complete = True
            callback(False, "Error: ffmpeg no está instalado o no se encuentra en el PATH.")
        except Exception as e:
            self.is_detection_complete = True
            callback(False, f"Error inesperado durante la detección: {e}")

    def extract_audio(self, input_file, output_file, duration, progress_callback, cancellation_event: threading.Event):
        """
        Extrae la pista de audio de un archivo de video sin recodificar.
        Usa '-c:a copy' para una operación extremadamente rápida.
        """
        process = None
        try:
            if cancellation_event.is_set():
                raise UserCancelledError("Extracción de audio cancelada antes de iniciar.")

            command = [
                self.ffmpeg_path, '-y', '-nostdin', '-progress', '-', '-i', input_file,
                '-vn',  
                '-c:a', 'copy',  
                '-map_metadata', '-1', 
                '-acodec', 'copy',
                output_file
            ]

            print("--- Comando FFmpeg para extracción de audio ---")
            print(" ".join(command))
            print("---------------------------------------------")

            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            error_output_buffer = []
            process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding='utf-8', errors='ignore', creationflags=creationflags
            )
            self.current_process = process

            def read_stream_into_buffer(stream, buffer):
                for line in iter(stream.readline, ''):
                    buffer.append(line.strip())
            stdout_thread = threading.Thread(target=self._read_stdout_for_progress, args=(process.stdout, progress_callback, cancellation_event, duration), daemon=True)
            stderr_thread = threading.Thread(target=read_stream_into_buffer, args=(process.stderr, error_output_buffer), daemon=True)
            stdout_thread.start()
            stderr_thread.start()
            while process.poll() is None:
                if cancellation_event.is_set():
                    self.cancel_current_process()
                    raise UserCancelledError("Extracción de audio cancelada por el usuario.")
                time.sleep(0.1)
            stdout_thread.join()
            stderr_thread.join()
            if process.returncode != 0:
                raise Exception(f"FFmpeg falló al extraer audio: {' '.join(error_output_buffer)}")
            return output_file
        except UserCancelledError as e:
            raise e
        except Exception as e:
            self.cancel_current_process()
            raise e
        finally:
            if process:
                if process.stdout: process.stdout.close()
                if process.stderr: process.stderr.close()
            self.current_process = None

    def execute_recode(self, options, progress_callback, cancellation_event: threading.Event):
        process = None
        try:
            if cancellation_event.is_set():
                raise UserCancelledError("Recodificación cancelada por el usuario antes de iniciar.")
            input_file = options['input_file']
            output_file = os.path.normpath(options['output_file'])
            try:
                media_info = self.get_local_media_info(input_file)
                actual_duration = float(media_info['format']['duration'])
            except (Exception, KeyError, TypeError):
                actual_duration = options.get('duration', 0) 
            
            command = [self.ffmpeg_path, '-y', '-nostdin', '-progress', '-']
            duration = options.get('duration', 0)
            command = [self.ffmpeg_path, '-y', '-nostdin', '-progress', '-']
            pre_params = options.get('pre_params', [])
            if pre_params:
                command.extend(pre_params)
            final_params = options['ffmpeg_params']
            video_idx = options.get('selected_video_stream_index')
            audio_idx = options.get('selected_audio_stream_index')
            mode = options.get('mode')
            command.extend(['-i', input_file])
            if mode == "Video+Audio":
                if video_idx is not None:
                    command.extend(['-map', f'0:{video_idx}'])
                if audio_idx == "all":
                    command.extend(['-map', '0:a'])
                elif audio_idx is not None:
                    command.extend(['-map', f'0:{audio_idx}'])
            elif mode == "Solo Audio":
                if audio_idx == "all":
                    command.extend(['-map', '0:a'])
                elif audio_idx is not None:
                    command.extend(['-map', f'0:{audio_idx}'])
            command.extend(final_params)
            command.append(output_file)
            print("--- Comando FFmpeg a ejecutar ---")
            print(" ".join(command))
            print("---------------------------------")
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            error_output_buffer = []
            process = subprocess.Popen(command,stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore', creationflags=creationflags)
            self.current_process = process

            def read_stream_into_buffer(stream, buffer):
                """Lee línea por línea de un stream y lo guarda en una lista."""
                for line in iter(stream.readline, ''):
                    buffer.append(line.strip())
            stdout_reader_thread = threading.Thread(target=self._read_stdout_for_progress, args=(process.stdout, progress_callback, cancellation_event, actual_duration), daemon=True)
            stderr_reader_thread = threading.Thread(target=read_stream_into_buffer, args=(process.stderr, error_output_buffer), daemon=True)
            stdout_reader_thread.start()
            stderr_reader_thread.start()
            while process.poll() is None:
                if cancellation_event.is_set():
                    # ESTA ES LA LÓGICA DE CANCELACIÓN DE single_tab
                    self.cancel_current_process()
                    raise UserCancelledError("Recodificación cancelada por el usuario.")
                time.sleep(0.1) # Usar un tiempo de espera más corto
            # ... (código anterior dentro de execute_recode) ...

            stdout_reader_thread.join()
            stderr_reader_thread.join()

            # --- INICIO DE LA MODIFICACIÓN ---
            if process.returncode != 0 and not cancellation_event.is_set():
                # 1. Unir las líneas con saltos de línea para procesarlas mejor
                full_error_log_text = "\n".join(error_output_buffer)
                
                # Imprimir en consola para debug completo (como antes)
                print(f"\n--- ERROR DETALLADO DE FFmpeg ---\n{full_error_log_text}\n---------------------------------\n")
                
                # 2. Filtrar/Extraer las líneas más relevantes para el usuario
                # FFmpeg suele poner el error crítico al final. Tomamos las últimas 10 líneas.
                lines = full_error_log_text.split('\n')
                
                # Eliminamos líneas vacías al final
                lines = [L for L in lines if L.strip()]
                
                # Tomamos las últimas líneas (ej. 8 líneas) para dar contexto sin llenar toda la pantalla
                relevant_lines = lines[-8:] if len(lines) > 8 else lines
                error_summary = "\n".join(relevant_lines)

                # 3. Lanzar la excepción con el resumen del error real
                raise Exception(f"FFmpeg falló. Detalles:\n\n{error_summary}")
            # --- FIN DE LA MODIFICACIÓN ---

            if cancellation_event.is_set():
                raise UserCancelledError("Recodificación cancelada por el usuario.")
            return output_file

# ... (resto del código) ...
        except UserCancelledError as e:
            self.cancel_current_process()
            raise e
        except Exception as e:
            self.cancel_current_process()
            raise Exception(f"Error en recodificación: {e}")
        finally:
            if process:
                if process.stdout: process.stdout.close()
                if process.stderr: process.stderr.close()
            self.current_process = None

    def _read_stdout_for_progress(self, stream, progress_callback, cancellation_event, duration):
        """Lee el stdout de FFmpeg para el progreso, actualizando menos frecuentemente."""
        last_reported_percentage = -1.0
        for line in iter(stream.readline, ''):
            if cancellation_event.is_set():
                break
            if 'out_time_ms=' in line:
                try:
                    progress_us = int(line.strip().split('=')[1])
                    if duration > 0:
                        progress_seconds = progress_us / 1_000_000
                        percentage = (progress_seconds / duration) * 100
                        if percentage >= last_reported_percentage + 1.0 or percentage >= 99.9 or percentage <= 0.1:
                            progress_callback(percentage, f"Recodificando... {percentage:.1f}%")
                            last_reported_percentage = percentage
                except ValueError:
                    pass

    def get_local_media_info(self, input_file):
        """
        Usa ffprobe para obtener información detallada de un archivo local.
        Esta versión usa Popen para un manejo más robusto de timeouts y streams.
        """
        ffprobe_exe_name = "ffprobe.exe" if os.name == 'nt' else "ffprobe"
        ffprobe_path = os.path.join(os.path.dirname(self.ffmpeg_path), ffprobe_exe_name)
        
        command = [
            ffprobe_path, # <--- Usar la ruta recién construida
            '-v', 'quiet',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_format',
            '-show_streams',
            input_file
        ]
        print(f"DEBUG: Ejecutando comando ffprobe con Popen: {' '.join(command)}")
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='ignore',
                creationflags=creationflags
            )
            stdout, stderr = process.communicate(timeout=60)
            if process.returncode != 0:
                print("--- ERROR DETALLADO DE FFPROBE (Popen) ---")
                print(f"El proceso ffprobe falló con el código de salida: {process.returncode}")
                print(f"Salida estándar (stdout):\n{stdout}")
                print(f"Salida de error (stderr):\n{stderr}")
                print("-----------------------------------------")
                return None
            return json.loads(stdout)
        except subprocess.TimeoutExpired:
            print("--- ERROR: TIMEOUT DE FFPROBE ---")
            print("La operación de análisis del archivo local tardó demasiado (más de 60s) y fue cancelada.")
            if 'process' in locals() and process:
                process.kill() 
                process.communicate()
            print("---------------------------------")
            return None
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"ERROR: No se pudo obtener información de '{input_file}' con ffprobe: {e}")
            return None

    def get_frame_from_video(self, input_file, duration=0):
        """
        Extrae un fotograma de un video en un punto de tiempo seguro.
        CORREGIDO: Usa el orden de argumentos más robusto para FFmpeg.
        """
        if duration > 0:
            seek_time_seconds = min(duration / 2, 5.0)
            at_time = f"{seek_time_seconds:.3f}"
        else:
            at_time = '00:00:01' 

        temp_dir = tempfile.gettempdir()
        output_path = os.path.join(temp_dir, f"dowp_thumbnail_{os.path.basename(input_file)}.jpg")
        
        command = [
            self.ffmpeg_path,
            '-y',
            '-i', input_file,    
            '-ss', at_time,      
            '-vframes', '1',
            '-q:v', '2',
            output_path
        ]
        
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            subprocess.run(command, check=True, capture_output=True, creationflags=creationflags)
            return output_path
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"ERROR: No se pudo extraer el fotograma: {e}")
            return None
        
    def execute_video_to_images(self, options, progress_callback, cancellation_event: threading.Event):
            """
            Convierte un archivo de video en una secuencia de imágenes (ej. JPG o PNG).
            """
            process = None
            try:
                if cancellation_event.is_set():
                    raise UserCancelledError("Extracción cancelada por el usuario antes de iniciar.")
                    
                input_file = options['input_file']
                output_folder = os.path.normpath(options['output_folder'])
                image_format = options.get('image_format', 'png')
                fps = options.get('fps')
                jpg_quality = options.get('jpg_quality', '2')  # String por defecto

                # Validar calidad JPG
                try:
                    jpg_quality_int = int(jpg_quality)
                    if not (1 <= jpg_quality_int <= 31):
                        jpg_quality = '2'  # Fallback a calidad alta
                except (ValueError, TypeError):
                    jpg_quality = '2'

                # 1. Asegurarse de que la carpeta de salida exista
                os.makedirs(output_folder, exist_ok=True)
                
                # 2. Construir el comando
                command = [self.ffmpeg_path, '-y', '-nostdin', '-progress', '-']
                
                pre_params = options.get('pre_params', [])
                if pre_params:
                    command.extend(pre_params)
                
                command.extend(['-i', input_file])
                
                final_params = []
                
                # 3. Añadir filtro de FPS (si se especificó)
                if fps:
                    try:
                        fps_value = float(fps)
                        final_params.extend(['-vf', f"fps={fps_value}"])
                        print(f"INFO: Extrayendo a {fps_value} FPS.")
                    except (ValueError, TypeError):
                        print("INFO: FPS inválido, extrayendo todos los fotogramas.")
                else:
                    print("INFO: Extrayendo todos los fotogramas (FPS no especificado).")
                
                # 4. Añadir opciones de formato de imagen
                if image_format == 'jpg':
                    final_params.extend(['-q:v', str(jpg_quality)])
                    output_pattern = "frame_%06d.jpg"
                else:  # PNG
                    output_pattern = "frame_%06d.png"

                command.extend(final_params)
                command.append(os.path.join(output_folder, output_pattern))
                
                print("--- Comando FFmpeg para Extracción de Imágenes ---")
                print(" ".join(command))
                print("-------------------------------------------------")
                
                # 5. Obtener duración
                try:
                    media_info = self.get_local_media_info(input_file)
                    actual_duration = float(media_info['format']['duration'])
                except Exception:
                    actual_duration = options.get('duration', 0)

                # 6. Ejecutar el proceso
                creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                error_output_buffer = []
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.PIPE, 
                    text=True, 
                    encoding='utf-8', 
                    errors='ignore', 
                    creationflags=creationflags
                )
                self.current_process = process

                def read_stream_into_buffer(stream, buffer):
                    for line in iter(stream.readline, ''):
                        buffer.append(line.strip())
                
                stdout_reader_thread = threading.Thread(
                    target=self._read_stdout_for_progress, 
                    args=(process.stdout, progress_callback, cancellation_event, actual_duration), 
                    daemon=True
                )
                stderr_reader_thread = threading.Thread(
                    target=read_stream_into_buffer, 
                    args=(process.stderr, error_output_buffer), 
                    daemon=True
                )
                
                stdout_reader_thread.start()
                stderr_reader_thread.start()
                
                while process.poll() is None:
                    if cancellation_event.is_set():
                        self.cancel_current_process()
                        raise UserCancelledError("Extracción cancelada por el usuario.")
                    time.sleep(0.1)
                
                stdout_reader_thread.join()
                stderr_reader_thread.join()
                
                if process.returncode != 0 and not cancellation_event.is_set():
                    full_error_log = " ".join(error_output_buffer)
                    print(f"\n--- ERROR DETALLADO DE FFmpeg ---\n{full_error_log}\n---------------------------------\n")
                    raise Exception(f"FFmpeg falló (ver consola para detalles técnicos).")
                
                if cancellation_event.is_set():
                    raise UserCancelledError("Extracción cancelada por el usuario.")
                
                # 7. Éxito: Devolver la RUTA DE LA CARPETA
                return output_folder
                
            except UserCancelledError as e:
                self.cancel_current_process()
                raise e
            except Exception as e:
                self.cancel_current_process()
                raise Exception(f"Error en extracción de imágenes: {e}")
            finally:
                if process:
                    if process.stdout: process.stdout.close()
                    if process.stderr: process.stderr.close()
                self.current_process = None

def clean_and_convert_vtt_to_srt(input_path):
    """
    Convierte un archivo VTT a SRT limpio, o limpia un SRT existente.
    Elimina etiquetas de formato, marcas de tiempo duplicadas y texto de karaoke.
    """
    import re
    
    output_path = input_path
    is_vtt = input_path.lower().endswith('.vtt')
    
    # Si es VTT, cambiar la extensión a SRT
    if is_vtt:
        output_path = os.path.splitext(input_path)[0] + '.srt'
    
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        lines = content.split('\n')
        cleaned_lines = []
        counter = 1
        skip_next = False
        
        for i, line in enumerate(lines):
            # Saltar el encabezado WEBVTT
            if line.strip().startswith('WEBVTT') or line.strip().startswith('Kind:') or line.strip().startswith('Language:'):
                continue
            
            # Saltar líneas de estilo
            if line.strip().startswith('STYLE') or '::cue' in line:
                skip_next = True
                continue
            
            if skip_next:
                if line.strip() == '':
                    skip_next = False
                continue
            
            # 🔧 CRÍTICO: Limpiar texto de karaoke y etiquetas HTML
            if line.strip() and '-->' not in line and not line.strip().isdigit():
                # Eliminar etiquetas de formato VTT como <c>, <v>, etc.
                cleaned = re.sub(r'<[^>]+>', '', line)
                # Eliminar marcas de tiempo embebidas (karaoke)
                cleaned = re.sub(r'<\d{2}:\d{2}:\d{2}\.\d{3}>', '', cleaned)
                # Eliminar etiquetas de color y estilo
                cleaned = re.sub(r'\{[^}]+\}', '', cleaned)
                cleaned = cleaned.strip()
                
                if cleaned:
                    cleaned_lines.append(cleaned)
                continue
            
            # Mantener timestamps y números de secuencia
            if '-->' in line or line.strip().isdigit() or line.strip() == '':
                cleaned_lines.append(line.strip())
        
        # Reconstruir el archivo SRT
        srt_content = []
        i = 0
        while i < len(cleaned_lines):
            line = cleaned_lines[i]
            
            # Si es un timestamp
            if '-->' in line:
                # Agregar número de secuencia
                srt_content.append(str(counter))
                # Convertir formato de tiempo VTT a SRT si es necesario
                timestamp = line.replace('.', ',')  # VTT usa punto, SRT usa coma
                srt_content.append(timestamp)
                
                # Recoger todas las líneas de texto hasta la siguiente línea vacía
                i += 1
                text_lines = []
                while i < len(cleaned_lines) and cleaned_lines[i].strip() != '':
                    if '-->' not in cleaned_lines[i]:
                        text_lines.append(cleaned_lines[i])
                    else:
                        i -= 1
                        break
                    i += 1
                
                if text_lines:
                    srt_content.extend(text_lines)
                
                srt_content.append('')  # Línea vacía entre subtítulos
                counter += 1
            
            i += 1
        
        # Guardar el archivo limpio
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(srt_content))
        
        # Si era VTT, eliminar el archivo original
        if is_vtt and output_path != input_path:
            try:
                os.remove(input_path)
            except:
                pass
        
        print(f"DEBUG: Subtítulo limpiado y guardado en: {output_path}")
        return output_path
        
    except Exception as e:
        print(f"ERROR al limpiar subtítulo: {e}")
        return input_path
    