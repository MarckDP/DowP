# src/core/utils/hardware_detector.py
import os
import platform
import subprocess
import time
from core.logger.logger_manager import logger
from core.setup.setup_manager import get_dependency_env
from core.utils.config_manager import get_config, save_config
from PySide6.QtCore import QCoreApplication, QT_TRANSLATE_NOOP


def _get_os_name() -> str:
    """Obtiene el nombre comercial exacto del sistema operativo (ej. Windows 11 Pro)."""
    os_system = platform.system()
    arch = platform.architecture()[0]
    try:
        if os_system == "Windows":
            cmd = 'powershell -NoProfile -Command "(Get-CimInstance Win32_OperatingSystem).Caption"'
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=3, creationflags=flags)
            caption = res.stdout.strip()
            if caption:
                clean_name = caption.replace("Microsoft ", "").strip()
                return f"{clean_name} ({arch})"
            
            import sys
            winver = sys.getwindowsversion()
            if winver.major == 10 and winver.build >= 22000:
                return f"Windows 11 ({arch})"
            elif winver.major == 10:
                return f"Windows 10 ({arch})"
        elif os_system == "Darwin":
            res = subprocess.run(["sw_vers", "-productVersion"], capture_output=True, text=True, timeout=3)
            ver = res.stdout.strip()
            if ver:
                return f"macOS {ver} ({arch})"
        elif os_system == "Linux":
            if os.path.exists("/etc/os-release"):
                with open("/etc/os-release", "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("PRETTY_NAME="):
                            pretty = line.split("=")[1].strip().strip('"')
                            return f"{pretty} ({arch})"
    except Exception as e:
        logger.debug(f"HardwareDetector: Error detectando OS: {e}")

    return f"{os_system} {platform.release()} ({arch})"


def _get_cpu_name() -> str:
    """Obtiene el nombre exacto del procesador según el sistema operativo."""
    os_system = platform.system()
    try:
        if os_system == "Windows":
            cmd = 'powershell -NoProfile -Command "(Get-CimInstance Win32_Processor).Name"'
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=3, creationflags=flags)
            name = res.stdout.strip()
            if name:
                return name.split('\n')[0].strip()
        elif os_system == "Darwin":
            res = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, timeout=3)
            name = res.stdout.strip()
            if name:
                return name
        elif os_system == "Linux":
            with open("/proc/cpuinfo", "r", encoding="utf-8") as f:
                for line in f:
                    if "model name" in line:
                        return line.split(":")[1].strip()
    except Exception as e:
        logger.debug(f"HardwareDetector: Fallo detectando CPU: {e}")

    return platform.processor() or platform.machine() or "Procesador Estándar"


# Lo que devuelve _get_gpu_name() cuando no pudo averiguar nada: es un relleno,
# no un nombre real, y quien lo consuma debería poder distinguirlo.
UNKNOWN_GPU_NAME = "Gráficos integrados / Estándar"


def _get_gpu_name() -> str:
    """Obtiene el nombre de la tarjeta gráfica activa según el sistema operativo."""
    os_system = platform.system()
    try:
        if os_system == "Windows":
            cmd = 'powershell -NoProfile -Command "(Get-CimInstance Win32_VideoController).Name"'
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=3, creationflags=flags)
            lines = [line.strip() for line in res.stdout.strip().split('\n') if line.strip()]
            if lines:
                return " / ".join(lines)
        elif os_system == "Darwin":
            cmd = "system_profiler SPDisplaysDataType | grep 'Chipset Model'"
            res = subprocess.run(cmd, capture_output=True, text=True, shell=True, timeout=3)
            lines = [line.split(":")[1].strip() for line in res.stdout.strip().split('\n') if ":" in line]
            if lines:
                return " / ".join(lines)
            return "Apple Silicon GPU" if platform.processor() == "arm" or platform.machine().startswith("arm") else "macOS GPU"
        elif os_system == "Linux":
            res = subprocess.run("lspci | grep -i 'vga\\|3d'", capture_output=True, text=True, shell=True, timeout=3)
            lines = [line.split(":")[-1].strip() for line in res.stdout.strip().split('\n') if line.strip()]
            if lines:
                return " / ".join(lines)
    except Exception as e:
        logger.debug(f"HardwareDetector: Fallo detectando GPU: {e}")

    return UNKNOWN_GPU_NAME


def get_cached_gpu_name() -> str | None:
    """Nombre de la GPU del último escaneo, leído de la config, SIN lanzar uno
    nuevo. detect_hardware() puede tardar segundos (prueba encoders reales de ffmpeg
    uno por uno), así que para un dato puramente informativo -- como decirle al
    usuario qué GPU se está usando, o cuál se detectó pero no sirve para inferencia
    -- se usa lo que ya haya cacheado. None si nunca se escaneó o si el escaneo no
    pudo identificarla."""
    info = get_config().get("hardware_info", {}) or {}
    name = (info.get("gpu_name") or "").strip()
    return name if name and name != UNKNOWN_GPU_NAME else None


# Encoders candidatos por códec, en orden de prioridad de uso (hardware antes que software).
# backend: identificador corto usado en hardware_acceleration / UI badges.
CODEC_ENCODERS = {
    "h264": [
        ("h264_nvenc", "NVIDIA NVENC", "nvenc"),
        ("h264_videotoolbox", "Apple VideoToolbox", "videotoolbox"),
        ("h264_qsv", "Intel QuickSync", "qsv"),
        ("h264_amf", "AMD AMF", "amf"),
        ("h264_vaapi", "Linux VA-API", "vaapi"),
        ("libx264", "CPU Software (x264)", "software"),
    ],
    "hevc": [
        ("hevc_nvenc", "NVIDIA NVENC", "nvenc"),
        ("hevc_videotoolbox", "Apple VideoToolbox", "videotoolbox"),
        ("hevc_qsv", "Intel QuickSync", "qsv"),
        ("hevc_amf", "AMD AMF", "amf"),
        ("hevc_vaapi", "Linux VA-API", "vaapi"),
        ("libx265", "CPU Software (x265)", "software"),
    ],
    "av1": [
        ("av1_nvenc", "NVIDIA NVENC", "nvenc"),
        ("av1_qsv", "Intel QuickSync", "qsv"),
        ("av1_amf", "AMD AMF", "amf"),
        ("av1_vaapi", "Linux VA-API", "vaapi"),
        ("libsvtav1", "CPU Software (SVT-AV1)", "software"),
        ("libaom-av1", "CPU Software (aom)", "software"),
    ],
    "vp9": [
        ("vp9_vaapi", "Linux VA-API", "vaapi"),
        ("libvpx-vp9", "CPU Software (VP9)", "software"),
    ],
}

# Orden de prioridad de backend al elegir el "preferido" dentro de un códec.
_BACKEND_PRIORITY = ["nvenc", "videotoolbox", "qsv", "amf", "vaapi", "software"]


def _probe_encoder(ffmpeg_exe: str, env, encoder_code: str, backend: str) -> bool:
    """
    Confirma que un encoder listado en el binario realmente funciona en ESTE hardware.
    Que ffmpeg -encoders liste 'av1_nvenc' solo dice que el binario fue compilado con
    soporte NVENC AV1 — no que esta GPU en particular lo soporte (p. ej. NVENC AV1 recién
    existe desde RTX 40-series). Software (libx264, libx265, etc.) no se prueba: si el
    binario lo trae, siempre funciona, y probarlo solo agrega tiempo de escaneo.
    """
    if backend == "software":
        return True
    try:
        # 256x256: los encoders por hardware (NVENC, QSV, AMF) rechazan resoluciones muy
        # chicas (ej. NVENC exige un mínimo ~145x49) devolviendo "Frame Dimension less than
        # the minimum supported value" — con 64x64 el probe fallaba siempre por esto, no por
        # falta de soporte real.
        cmd = [
            ffmpeg_exe, "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.1",
            "-frames:v", "2", "-c:v", encoder_code, "-f", "null", "-",
        ]
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        res = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=6, creationflags=flags)
        return res.returncode == 0
    except Exception as e:
        logger.debug(f"HardwareDetector: Probe fallido para {encoder_code}: {e}")
        return False


def _get_codec_support_map() -> dict:
    """
    Inspecciona el ffmpeg empaquetado y arma un mapa {códec: {backend: info}} con
    verificación real por probe-encode, cubriendo H.264, HEVC, AV1 y VP9 —no solo H.264.
    """
    env = get_dependency_env()
    ffmpeg_exe = "ffmpeg"
    codec_support: dict = {}

    try:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        res = subprocess.run([ffmpeg_exe, "-encoders"], capture_output=True, text=True, env=env, timeout=4, creationflags=flags)
        stdout = res.stdout
    except Exception as e:
        logger.warning(f"HardwareDetector: Error al ejecutar ffmpeg -encoders: {e}")
        stdout = ""

    for codec, encoders in CODEC_ENCODERS.items():
        codec_support[codec] = {}
        for enc_code, label, backend in encoders:
            listed = bool(stdout) and (
                f"V..... {enc_code}" in stdout or f"V....D {enc_code}" in stdout or enc_code in stdout
            )
            probed_ok = _probe_encoder(ffmpeg_exe, env, enc_code, backend) if listed else False
            entry = {
                "encoder": enc_code,
                "label": label,
                "listed_in_binary": listed,
                "probed_ok": probed_ok,
                "supported": listed and probed_ok,
            }
            # Dos codecs (ej. av1: libsvtav1 y libaom-av1) pueden compartir el mismo
            # backend "software". Se respeta el orden de CODEC_ENCODERS como prioridad:
            # el primero que funcione gana la ranura; uno posterior solo la toma si la
            # ranura seguia vacia o el candidato anterior no funcionaba.
            existing = codec_support[codec].get(backend)
            if existing is None or (not existing["supported"] and entry["supported"]):
                codec_support[codec][backend] = entry

    return codec_support


def _flatten_supported_encoders(codec_support: dict) -> tuple[list[str], str]:
    """
    Deriva la lista plana de encoders soportados y el preferido de H.264 (compatibilidad
    con la UI existente, que solo muestra badges de H.264 por ahora).
    """
    supported = []
    for codec, backends in codec_support.items():
        for backend, info in backends.items():
            if info["supported"]:
                supported.append(info["encoder"])

    if not supported:
        supported = ["libx264"]

    h264 = codec_support.get("h264", {})
    preferred = "libx264"
    for backend in _BACKEND_PRIORITY:
        info = h264.get(backend)
        if info and info["supported"]:
            preferred = info["encoder"]
            break

    return supported, preferred


def _summarize_codec_status(codec_support: dict) -> dict:
    """
    Reduce el detalle por-backend a un estado único por códec, pensado para consumo
    directo desde la UI de exportación: full (acelerado por hardware, confirmado),
    partial (solo por software, funcional pero lento), none (ni hardware ni software
    disponibles en ESTE build de ffmpeg instalado).
    """
    summary = {}
    for codec, backends in codec_support.items():
        hw_ok = {b: info for b, info in backends.items() if b != "software" and info["supported"]}
        hw_listed_but_failed = any(
            info["listed_in_binary"] and not info["supported"]
            for b, info in backends.items() if b != "software"
        )
        sw_info = backends.get("software")
        sw_ok = bool(sw_info and sw_info["supported"])

        chosen = None
        for backend in _BACKEND_PRIORITY:
            if backend in hw_ok:
                chosen = (backend, hw_ok[backend])
                break

        if chosen:
            backend, info = chosen
            summary[codec] = {
                "status": "full",
                "encoder": info["encoder"],
                "backend": backend,
                "note": QT_TRANSLATE_NOOP("HardwareDetector", "Codificación acelerada por hardware, confirmada en este equipo."),
            }
        elif sw_ok:
            note = QT_TRANSLATE_NOOP("HardwareDetector", "Solo disponible por software (CPU): funcional pero más lento.")
            if hw_listed_but_failed:
                note = QT_TRANSLATE_NOOP("HardwareDetector", "El hardware detectado no confirmó aceleración; se usará software (CPU), más lento.")
            summary[codec] = {
                "status": "partial",
                "encoder": sw_info["encoder"],
                "backend": "software",
                "note": note,
            }
        else:
            summary[codec] = {
                "status": "none",
                "encoder": None,
                "backend": "none",
                "note": QT_TRANSLATE_NOOP("HardwareDetector", "Este build de ffmpeg no trae ningún encoder funcional para este códec."),
            }

    return summary


def _get_ram_info() -> str:
    """Obtiene la memoria RAM total instalada en el sistema."""
    os_system = platform.system()
    try:
        if os_system == "Windows":
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                gb = stat.ullTotalPhys / (1024 ** 3)
                return f"{gb:.1f} GB"
        elif os_system == "Darwin":
            try:
                res = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=3)
                if res.returncode == 0 and res.stdout.strip().isdigit():
                    gb = int(res.stdout.strip()) / (1024 ** 3)
                    return f"{gb:.1f} GB"
            except Exception as e:
                logger.error(f"HardwareDetector: Error al obtener RAM en macOS: {e}")
        elif os_system == "Linux":
            with open("/proc/meminfo", "r", encoding="utf-8") as f:
                for line in f:
                    if "MemTotal" in line:
                        kb = int(line.split(":")[1].replace("kB", "").strip())
                        gb = kb / (1024 ** 2)
                        return f"{gb:.1f} GB"
    except Exception as e:
        logger.debug(f"HardwareDetector: Error detectando RAM: {e}")

    return "No detectada"


def _generate_ffmpeg_log_files(codec_support: dict, codec_status: dict, supported_encoders: list, preferred_encoder: str) -> tuple[str, str]:
    """
    Genera el log de capacidades en formato JSON (ffmpeg_encoders_log.json)
    y el informe estructurado (ffmpeg_capabilities.json) en AppData.
    """
    import json
    from core.utils.paths import get_app_data_dir
    app_data = get_app_data_dir()
    log_json_path = os.path.join(app_data, "ffmpeg_encoders_log.json")
    json_path = os.path.join(app_data, "ffmpeg_capabilities.json")
    env = get_dependency_env()

    # Estado de aceleración por hardware a nivel global: True si CUALQUIER códec tiene
    # ese backend confirmado por probe. Se mantiene por compatibilidad con la UI actual.
    hw_accel_status = {
        backend: any(
            codec_support.get(codec, {}).get(backend, {}).get("supported", False)
            for codec in codec_support
        )
        for backend in ("nvenc", "videotoolbox", "qsv", "amf", "vaapi")
    }

    capabilities_json = {
        "schema_version": "2.0",
        # Campos legacy: se mantienen para no romper system_page.py y otros consumidores existentes.
        "preferred_encoder": preferred_encoder,
        "supported_video_encoders": supported_encoders,
        "hardware_acceleration": hw_accel_status,
        "is_gpu_accelerated": preferred_encoder != "libx264",
        # Mapa detallado: fuente de verdad por-backend para diagnóstico.
        "codec_support": codec_support,
        # Resumen directo para la UI: qué códecs puede, puede parcialmente, o no puede
        # producir ESTE ffmpeg instalado, sin importar de qué build/versión venga.
        "codec_status": codec_status,
        "last_scan_timestamp": int(time.time()),
    }

    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(capabilities_json, f, indent=2, ensure_ascii=False)
        logger.info(f"HardwareDetector: Archivo JSON de capacidades creado en: {json_path}")
    except Exception as e:
        logger.error(f"HardwareDetector: No se pudo escribir ffmpeg_capabilities.json: {e}")

    # 2. Generar JSON completo de capacidades
    full_log_data = {
        "app_info": QCoreApplication.translate("hardware_detector", "DowP 2.0 - Informe Completo de Capacidades de FFmpeg"),
        "diagnostic_date": time.strftime('%Y-%m-%d %H:%M:%S'),
        "detected_preferred_encoder": preferred_encoder,
        "supported_encoders_summary": supported_encoders,
        "capabilities": {}
    }

    sections = {
        "version": ["ffmpeg", "-version"],
        "encoders": ["ffmpeg", "-encoders"],
        "decoders": ["ffmpeg", "-decoders"],
        "formats": ["ffmpeg", "-formats"],
        "filters": ["ffmpeg", "-filters"],
        "muxers": ["ffmpeg", "-muxers"],
        "demuxers": ["ffmpeg", "-demuxers"],
        "codecs": ["ffmpeg", "-codecs"],
        "hwaccels": ["ffmpeg", "-hwaccels"],
        "protocols": ["ffmpeg", "-protocols"],
        "bsfs": ["ffmpeg", "-bsfs"],
        "layouts": ["ffmpeg", "-layouts"],
        "colors": ["ffmpeg", "-colors"]
    }

    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    for key, cmd in sections.items():
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=5, creationflags=flags)
            output = res.stdout or res.stderr or ""
            full_log_data["capabilities"][key] = [line for line in output.split("\n") if line.strip()]
        except Exception as e:
            full_log_data["capabilities"][key] = [f"Error al ejecutar {' '.join(cmd)}: {e}"]

    try:
        with open(log_json_path, "w", encoding="utf-8") as f:
            json.dump(full_log_data, f, indent=2, ensure_ascii=False)
        logger.info(f"HardwareDetector: Log de capacidades de FFmpeg generado en: {log_json_path}")
    except Exception as e:
        logger.error(f"HardwareDetector: No se pudo escribir ffmpeg_encoders_log.json: {e}")

    return log_json_path, json_path


def detect_hardware(force_refresh: bool = False) -> dict:
    """
    Realiza la detección completa del hardware y la guarda en la configuración.
    Si force_refresh es False y ya existe hardware_info en la config y el archivo log existe, lo devuelve directamente.
    """
    config = get_config()
    cached_info = config.get("hardware_info", {})
    from core.utils.paths import get_app_data_dir
    log_path = os.path.join(get_app_data_dir(), "ffmpeg_encoders_log.json")

    if (
        not force_refresh
        and cached_info
        and cached_info.get("cpu_name")
        and cached_info.get("ram_size")
        and cached_info.get("codec_support")
        and os.path.exists(log_path)
    ):
        return cached_info

    logger.info("HardwareDetector: Iniciando escaneo de hardware del sistema...")
    start_time = time.time()
    
    cpu_name = _get_cpu_name()
    gpu_name = _get_gpu_name()
    ram_size = _get_ram_info()
    codec_support = _get_codec_support_map()
    codec_status = _summarize_codec_status(codec_support)
    supported_encoders, preferred_encoder = _flatten_supported_encoders(codec_support)
    txt_log_path, json_log_path = _generate_ffmpeg_log_files(codec_support, codec_status, supported_encoders, preferred_encoder)
    
    os_name = _get_os_name()
    
    hardware_info = {
        "os_name": os_name,
        "cpu_name": cpu_name,
        "gpu_name": gpu_name,
        "ram_size": ram_size,
        "preferred_encoder": preferred_encoder,
        "supported_encoders": supported_encoders,
        "codec_support": codec_support,
        "codec_status": codec_status,
        "ffmpeg_log_path": txt_log_path,
        "ffmpeg_json_path": json_log_path,
        "last_checked": int(time.time()),
        "scan_duration_sec": round(time.time() - start_time, 2)
    }

    config["hardware_info"] = hardware_info
    save_config(config)
    logger.info(f"HardwareDetector: Escaneo finalizado. RAM: {ram_size} | Encoder preferido: '{preferred_encoder}' en {hardware_info['scan_duration_sec']}s")
    
    return hardware_info