# src/core/utils/scaling.py
"""
Sistema de Escalado Inteligente para DowP 2.0 (Cross-Platform)
===============================================================
Detecta resolucion + DPI en Windows, macOS y Linux, y aplica
QT_SCALE_FACTOR para que la UI se vea bien en cualquier monitor.

DEBE llamarse ANTES de crear QApplication.

Formula universal:
    qt_scale = (native_h - taskbar) / (comfort_h * dpi_scale)
    clamped entre 0.65 y 1.0
"""
import os
import sys
import re
import subprocess

_log_lines: list[tuple] = []

def _log(level: str, msg: str):
    _log_lines.append((level, msg))

def flush_scaling_logs():
    """Envia logs acumulados al logger real. Llamar DESPUES de crear el logger."""
    from core.logger.logger_manager import logger
    for level, msg in _log_lines:
        fn = {"WARN": logger.warning, "DEBUG": logger.debug}.get(level, logger.info)
        fn(f"[Scaling] {msg}")
    _log_lines.clear()


# ========================================================================
#  Deteccion por plataforma
# ========================================================================

def _detect_windows() -> tuple[int, int, float]:
    """Windows: resolucion nativa + DPI con multiples APIs fallback."""
    import ctypes
    import ctypes.wintypes
    native_w, native_h, dpi_scale = 1920, 1080, 1.0

    # Silenciar advertencia benigna de Qt al configurar DPI context en Windows
    if "QT_LOGGING_RULES" not in os.environ:
        os.environ["QT_LOGGING_RULES"] = "qt.qpa.window.warning=false"

    # Hacer DPI-aware para obtener metricas reales
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        _log("DEBUG", "SetProcessDpiAwareness(2) exitoso")
    except OSError:
        _log("DEBUG", "SetProcessDpiAwareness ya fue llamado (normal)")
    except AttributeError:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass

    # Resolucion nativa
    try:
        native_w = ctypes.windll.user32.GetSystemMetrics(0)
        native_h = ctypes.windll.user32.GetSystemMetrics(1)
    except Exception as e:
        _log("WARN", f"GetSystemMetrics fallo: {e}")

    # DPI: intentar multiples metodos (de mas confiable a menos)
    dpi = 96

    # Metodo 1: GetDpiForSystem (Windows 10 1607+, el mas confiable)
    try:
        dpi = ctypes.windll.user32.GetDpiForSystem()
        _log("DEBUG", f"DPI via GetDpiForSystem: {dpi}")
    except (AttributeError, OSError):
        _log("DEBUG", "GetDpiForSystem no disponible")

        # Metodo 2: Leer del registro de Windows (siempre disponible)
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Control Panel\Desktop\WindowMetrics"
            )
            # AppliedDPI tiene el DPI actual del monitor principal
            dpi_reg, _ = winreg.QueryValueEx(key, "AppliedDPI")
            winreg.CloseKey(key)
            dpi = dpi_reg
            _log("DEBUG", f"DPI via Registro (AppliedDPI): {dpi}")
        except (FileNotFoundError, OSError):
            _log("DEBUG", "AppliedDPI no encontrado en registro")

            # Metodo 3: GetDeviceCaps (fallback clasico)
            try:
                hdc = ctypes.windll.user32.GetDC(0)
                dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)
                ctypes.windll.user32.ReleaseDC(0, hdc)
                _log("DEBUG", f"DPI via GetDeviceCaps: {dpi}")
            except Exception as e:
                _log("WARN", f"Todos los metodos DPI fallaron: {e}")

    dpi_scale = dpi / 96.0
    return native_w, native_h, dpi_scale


def _detect_macos() -> tuple[int, int, float]:
    """macOS: resolucion LOGICA via system_profiler. DPI=1.0 (Qt maneja Retina)."""
    import json as _json
    native_w, native_h = 1440, 900  # Default seguro (MacBook Air)
    dpi_scale = 1.0  # Qt maneja Retina nativamente

    try:
        result = subprocess.run(
            ["system_profiler", "SPDisplaysDataType", "-json"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            data = _json.loads(result.stdout)
            for gpu in data.get("SPDisplaysDataType", []):
                for disp in gpu.get("spdisplays_ndrvs", []):
                    res = disp.get("_spdisplays_resolution", "")
                    m = re.search(r"(\d+)\s*x\s*(\d+)", res)
                    if m:
                        native_w, native_h = int(m.group(1)), int(m.group(2))
                        _log("INFO", f"macOS display: {res}")
                        return native_w, native_h, dpi_scale
    except Exception as e:
        _log("WARN", f"system_profiler fallo: {e}")

    return native_w, native_h, dpi_scale


def _detect_linux() -> tuple[int, int, float]:
    """Linux: resolucion via xrandr, DPI via xdpyinfo o GDK_SCALE."""
    native_w, native_h = 1920, 1080
    dpi_scale = 1.0

    # 1. Resolucion via xrandr
    try:
        result = subprocess.run(
            ["xrandr", "--current"],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if " connected" in line:
                    m = re.search(r"(\d+)x(\d+)\+", line)
                    if m:
                        native_w, native_h = int(m.group(1)), int(m.group(2))
                        break
    except FileNotFoundError:
        _log("DEBUG", "xrandr no disponible (Wayland?)")
    except Exception as e:
        _log("WARN", f"xrandr fallo: {e}")

    # 2. DPI via xdpyinfo
    try:
        result = subprocess.run(
            ["xdpyinfo"], capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if "dots per inch" in line:
                    m = re.search(r"(\d+)x(\d+)", line)
                    if m:
                        dpi_scale = int(m.group(1)) / 96.0
                        break
    except (FileNotFoundError, Exception):
        pass

    # 3. Env vars del DE (GDK_SCALE para GNOME, etc.)
    gdk = os.environ.get("GDK_SCALE")
    if gdk:
        try:
            dpi_scale = max(dpi_scale, float(gdk))
        except ValueError:
            pass

    return native_w, native_h, dpi_scale


def _detect_screen_info() -> tuple[int, int, float]:
    """Dispatcher: detecta (native_w, native_h, dpi_scale) segun la plataforma."""
    if sys.platform == "win32":
        return _detect_windows()
    elif sys.platform == "darwin":
        return _detect_macos()
    else:
        return _detect_linux()


# ========================================================================
#  Logica principal
# ========================================================================

# Alto mínimo de la ventana principal (setMinimumSize(800, 600) en main_window.py; las
# pestañas piden menos, ~500, medido con minimumSizeHint).
MACOS_MIN_WINDOW_HEIGHT = 600


def apply_ui_scaling() -> float:
    """
    Calcula y aplica QT_SCALE_FACTOR optimo. LLAMAR ANTES de QApplication.

    Formula universal:
        qt_scale = (native_h - TASKBAR) / (COMFORT_H * dpi_scale)

    Donde COMFORT_H = 780px es la altura "comoda" de la UI.

    Ejemplos:
        1080p @ 100%  -> (1080-80)/(780*1.0) = 1.28 -> 1.0
        1080p @ 175%  -> (1080-80)/(780*1.75) = 0.73 -> 0.73
        768p  @ 100%  -> (768-80)/(780*1.0)   = 0.88 -> 0.88
        768p  @ 125%  -> (768-80)/(780*1.25)  = 0.71 -> 0.71
        1440p @ 125%  -> (1440-80)/(780*1.25) = 1.39 -> 1.0
        4K    @ 150%  -> (2160-80)/(780*1.5)  = 1.78 -> 1.0
        4K    @ 200%  -> (2160-80)/(780*2.0)  = 1.33 -> 1.0
        macOS 900p    -> (900-80)/(780*1.0)   = 1.05 -> 1.0
    """
    # 0. Si el usuario ya definio QT_SCALE_FACTOR, respetarlo
    existing = os.environ.get("QT_SCALE_FACTOR")
    if existing:
        _log("INFO", f"QT_SCALE_FACTOR ya definido por el usuario/SO: {existing}. Respetando.")
        return float(existing)

    # 1. Detectar pantalla
    native_w, native_h, dpi_scale = _detect_screen_info()
    platform = {"win32": "Windows", "darwin": "macOS"}.get(sys.platform, "Linux")
    _log("INFO", f"Plataforma: {platform}")
    _log("INFO", f"Resolucion nativa: {native_w}x{native_h}")
    _log("INFO", f"Escala DPI del SO: {dpi_scale:.2f}x ({dpi_scale:.0%})")

    # 2. Formula universal
    TASKBAR_MARGIN = 80   # Pixeles reservados para barra de tareas
    COMFORT_HEIGHT = 900  # Altura "comoda" de la UI (alineada al tamano minimo de 860px + margen de seguridad)

    raw_scale = (native_h - TASKBAR_MARGIN) / (COMFORT_HEIGHT * dpi_scale)
    qt_scale = min(1.0, max(0.65, round(raw_scale, 2)))

    _log("INFO", f"Calculo: ({native_h}-{TASKBAR_MARGIN}) / ({COMFORT_HEIGHT}*{dpi_scale:.2f}) "
                  f"= {raw_scale:.3f} -> clamped {qt_scale}")

    # macOS: escala 1 mientras la ventana quepa. En Retina (2 píxeles por punto)
    # cualquier escala < 1 deja una proporción fraccionaria (0.97 -> 1.94) y los bordes
    # caen entre píxeles: la UI se llenaba de líneas (confirmado en una MacBook Air de
    # 1470x956, que con QT_SCALE_FACTOR=1 se veía bien y entraba entera). La resolución
    # de macOS ya es lógica, elegida por el usuario en Ajustes > Pantallas, y la ventana
    # mínima (800x600, ver main_window.py) cabe en cualquier Mac; solo se escala si no.
    if sys.platform == "darwin" and qt_scale < 1.0:
        if native_h - TASKBAR_MARGIN >= MACOS_MIN_WINDOW_HEIGHT:
            _log("INFO", f"macOS: la ventana cabe a escala 1 ({native_h}-{TASKBAR_MARGIN} >= "
                          f"{MACOS_MIN_WINDOW_HEIGHT}); sin escala propia para no dejar líneas en Retina")
            qt_scale = 1.0

    # 3. Aplicar
    os.environ["QT_SCALE_FACTOR"] = str(qt_scale)
    _log("INFO", f"QT_SCALE_FACTOR = {qt_scale}")

    return qt_scale
