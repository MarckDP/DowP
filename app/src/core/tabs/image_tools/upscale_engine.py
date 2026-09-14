# src/core/tabs/image_tools/upscale_engine.py
from PySide6.QtCore import QCoreApplication
"""Motor de ejecución de "Reescalar IA" -- corre los binarios NCNN-Vulkan (Waifu2x/
SRMD/Upscayl) ya descargados vía Ajustes > Modelos (ver core/setup/models_setup.py).
Comandos exactos portados de DowP1 (video_upscaler.pyc decompilado, método
_build_ncnn_cmd) -- los 3 motores son binarios standalone que hacen todo el trabajo
solos, aquí solo se arma la línea de comandos correcta y se corre el proceso."""
import os
import re
import subprocess
import threading
import time
import multiprocessing

from core.logger.logger_manager import logger
from core.constants import (
    UPSCALING_TOOLS, WAIFU2X_MODELS, SRMD_MODELS, UPSCAYL_MODELS_MAP,
    UPSCAYL_SCALES, SRMD_SCALES,
)
from core.setup.models_setup import get_engine_exe_path
from core.utils.paths import get_models_dir

_POWER_THREADS = {
    "Seguro (Estabilidad)": "1:1:1",
    "Equilibrado": "1:2:1",
    "Máximo (Potente)": "2:4:2",
}

_VULKAN_OOM_HINTS = ("vkQueueSubmit failed", "vkAllocateMemory failed", "invalid gpu device", "out of gpu memory")

_POLL_INTERVAL_SEC = 0.2

# Upscayl (realesrgan-ncnn-vulkan) imprime "NN,NN%"/"NN.NN%" por stderr, una línea
# por mosaico procesado -- confirmado corriéndolo en vivo contra los 3 motores.
# Waifu2x y SRMD NO imprimen nada (solo el banner de la GPU al arrancar, después
# silencio hasta terminar) -- ahí no hay ninguna señal real que leer.
_UPSCAYL_PROGRESS_ENGINE = "Upscayl"
_PERCENT_RE = re.compile(r"(\d{1,3}[.,]\d{1,2})\s*%")


def _auto_threads() -> str:
    """"Automático": mismo criterio que _thread_args() de DowP1 -- conservador según
    núcleos disponibles, no el máximo posible."""
    try:
        cpu_count = multiprocessing.cpu_count()
    except NotImplementedError:
        cpu_count = 1
    return "1:2:1" if cpu_count >= 12 else "1:1:1"


def _resolve_threads(power_label: str) -> str:
    return _POWER_THREADS.get(power_label, _auto_threads())


# Rango de -n aceptado por cada motor, comprobado pasándole valores fuera de rango
# a los binarios: uno más y contestan "invalid noise argument" y se van con error.
_DENOISE_RANGE = {"Waifu2x": (-1, 3), "SRMD": (-1, 10)}


def _scale_int(text, default: int = 4) -> int:
    try:
        return int(str(text).strip().lower().rstrip("x"))
    except (TypeError, ValueError):
        return default


def _valid_scales(engine: str, model_key: str) -> list[int]:
    """Escalas que el binario acepta de verdad para esta combinación (ver el bloque
    de escalas en core/constants.py). Vacío = sin lista cerrada (Upscayl)."""
    if engine == "Waifu2x":
        info = WAIFU2X_MODELS.get(model_key) or next(iter(WAIFU2X_MODELS.values()))
        return [_scale_int(s) for s in info["scales"]]
    if engine == "SRMD":
        info = SRMD_MODELS.get(model_key)
        return [_scale_int(s) for s in (info["scales"] if info else SRMD_SCALES)]
    return []


def _clamp_scale(engine: str, model_key: str, requested: str) -> str:
    """Último filtro antes de armar el comando. El popover ya solo ofrece escalas
    válidas, pero las opciones también llegan desde ajustes guardados y desde la cola
    de conversión, y un valor viejo (ej. el 3x que la app ofrecía para los tres
    motores por igual, que Waifu2x rechaza) haría fallar el reescalado entero en vez
    de reescalar con lo más parecido que sí existe."""
    wanted = _scale_int(requested)
    if engine == "Upscayl":
        # Sin lista cerrada: acepta cualquier entero >= 1. Se topea en la mayor que
        # se ofrece porque más allá son varias pasadas del modelo por imagen.
        return str(max(1, min(wanted, _scale_int(UPSCAYL_SCALES[-1]))))
    allowed = _valid_scales(engine, model_key)
    if wanted in allowed:
        return str(wanted)
    below = [s for s in allowed if s <= wanted]
    chosen = below[-1] if below else min(allowed)
    logger.warning(
        f"Reescalar IA: {engine} no acepta escala x{wanted} con el modelo "
        f"'{model_key}' -- se usa x{chosen} en su lugar.")
    return str(chosen)


def _clamp_denoise(engine: str, requested) -> str:
    low, high = _DENOISE_RANGE.get(engine, (-1, 3))
    try:
        value = int(str(requested).strip().split(" ")[0])
    except (TypeError, ValueError):
        value = 2
    return str(max(low, min(value, high)))


def _model_dir_for(engine: str, model_key: str) -> str:
    """Directorio -m para Waifu2x/SRMD -- carpeta propia por familia de modelo
    (ej. models-cunet), a diferencia de Upscayl que comparte una sola carpeta."""
    tool_info = UPSCALING_TOOLS[engine]
    models_lookup = WAIFU2X_MODELS if engine == "Waifu2x" else SRMD_MODELS
    default_dir = "models-cunet" if engine == "Waifu2x" else "models-srmd"
    internal = models_lookup.get(model_key, {}).get("model", default_dir)
    return os.path.join(get_models_dir(), tool_info["folder"], internal)


def _build_cmd(exe: str, input_path: str, output_path: str, options: dict) -> list[str]:
    engine = options["upscale_engine"]
    model_key = options.get("upscale_model") or ""
    scale = _clamp_scale(engine, model_key, options.get("upscale_scale") or "4x")
    tile = str(options.get("upscale_tile") or "0")
    threads = _resolve_threads(options.get("upscale_power", "Automático"))
    tta = bool(options.get("upscale_tta"))

    if engine == "Upscayl":
        # UPSCAYL_MODELS_MAP: clave = nombre crudo del archivo, valor = etiqueta
        # amigable -- el popover guarda la clave cruda en currentData(), así que aquí
        # ya viene resuelto (no hace falta invertir el mapa).
        # "models" RELATIVO a propósito -- a diferencia de Waifu2x/SRMD (que sí
        # aceptan -m absoluto, confirmado con una corrida real), upscayl-bin resuelve
        # -m relativo a la carpeta de SU PROPIO ejecutable sin chequear si el valor ya
        # es una ruta absoluta -- pasarle una absoluta la duplica y falla
        # ("Failed to open .../upscayl/C:/.../upscayl/models/...param"), confirmado
        # también con una corrida real.
        model_dir = "models"
        cmd = [exe, "-i", input_path, "-o", output_path, "-n", model_key, "-m", model_dir,
               "-s", scale, "-f", "png", "-j", threads]
        if tile != "0":
            cmd += ["-t", tile]
        z_match = None
        for digit in ("2", "3"):
            if f"x{digit}" in model_key.lower():
                z_match = digit
                break
        if z_match:
            cmd += ["-z", z_match]
        if tta:
            cmd += ["-x"]
        return cmd

    # Waifu2x y SRMD -- misma forma (-n es nivel de ruido, no nombre de modelo).
    model_dir = _model_dir_for(engine, model_key)
    denoise = _clamp_denoise(engine, options.get("upscale_denoise", "2 (Alta)"))
    cmd = [exe, "-i", input_path, "-o", output_path, "-m", model_dir, "-n", denoise,
           "-s", scale, "-t", tile, "-f", "png", "-j", threads]
    if tta:
        cmd += ["-x"]
    return cmd


def run_upscale(input_path: str, output_path: str, options: dict, cancellation_event=None,
                 progress_callback=None) -> tuple[bool, str]:
    """Corre el motor de "upscale_engine" (Waifu2x/SRMD/Upscayl) sobre UNA imagen.
    Siempre escribe PNG (-f png, igual que DowP1) -- quien llame se encarga de volver
    a cargar el resultado y seguir el pipeline de guardado al formato final.

    `progress_callback(pct)` se llama con un float 0-100 mientras Upscayl (el único
    de los 3 motores que imprime progreso real, confirmado corriéndolo en vivo) va
    terminando mosaicos -- o con `None` para Waifu2x/SRMD (sin ninguna señal real
    que leer: no hay que inventar un número, es responsabilidad de quien llama
    mostrar un estado "trabajando" indeterminado en ese caso)."""
    engine = options.get("upscale_engine")
    tool_info = UPSCALING_TOOLS.get(engine)
    if tool_info is None:
        return False, QCoreApplication.translate("upscale_engine", "Motor de reescalado desconocido: {0}").format(engine)

    exe = get_engine_exe_path(tool_info)
    if not exe or not os.path.exists(exe):
        return False, QCoreApplication.translate("upscale_engine", "'{0}' no está instalado -- ve a Ajustes > Modelos para descargarlo.").format(tool_info["name"])

    cmd = _build_cmd(exe, input_path, output_path, options)
    logger.info(f"Reescalar IA: {' '.join(cmd)}")

    reports_progress = engine == _UPSCAYL_PROGRESS_ENGINE

    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
            # encoding/errors explícitos -- confirmado con una corrida real: upscayl-bin
            # imprime bytes que no son válidos en cp1252 (la codificación default de
            # Popen(text=True) en Windows), y eso hacía crashear communicate() con
            # UnicodeDecodeError en vez de simplemente reportar el error del motor.
            encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except Exception as e:
        return False, QCoreApplication.translate("upscale_engine", "No se pudo iniciar el motor '{0}': {1}").format(tool_info["name"], e)

    if progress_callback:
        progress_callback(0.0 if reports_progress else None)

    # stderr se lee en un hilo aparte, continuamente, mientras el proceso corre --
    # antes se leía todo de golpe con communicate() recién cuando el proceso ya
    # había terminado, así que cualquier progreso que Upscayl fuera imprimiendo en
    # el camino (confirmado que lo hace, ver _PERCENT_RE) se perdía por completo.
    # De paso, evita el riesgo clásico de deadlock de no drenar stderr mientras el
    # hijo puede estar bloqueado esperando que alguien lea su buffer.
    stderr_lines: list[str] = []

    def _read_stderr():
        try:
            for line in proc.stderr:
                stderr_lines.append(line)
                if reports_progress and progress_callback:
                    match = _PERCENT_RE.search(line)
                    if match:
                        pct = float(match.group(1).replace(",", "."))
                        logger.info(f"Progreso Upscayl: {pct}%")
                        progress_callback(pct)
        except Exception as e:
            logger.error(f"Reescalar IA: error leyendo stderr en vivo: {e}")

    reader_thread = threading.Thread(target=_read_stderr, daemon=True)
    reader_thread.start()

    try:
        while proc.poll() is None:
            if cancellation_event and cancellation_event.is_set():
                proc.kill()
                proc.wait(timeout=2.0)
                return False, QCoreApplication.translate("upscale_engine", "Cancelado por el usuario.")
            time.sleep(_POLL_INTERVAL_SEC)
    except Exception as e:
        proc.kill()
        return False, QCoreApplication.translate("upscale_engine", "Error esperando al motor '{0}': {1}").format(tool_info["name"], e)

    proc.wait()
    reader_thread.join(timeout=2.0)
    stderr_output = "".join(stderr_lines)

    if proc.returncode != 0:
        tail = stderr_output[-500:]
        if any(hint in stderr_output for hint in _VULKAN_OOM_HINTS):
            return False, QCoreApplication.translate(
                "upscale_engine",
                "'{0}' se quedó sin memoria de GPU -- prueba bajar el "
                "Tile Size a 128 o 64. Detalle: {1}"
            ).format(tool_info["name"], tail)
        return False, QCoreApplication.translate("upscale_engine", "'{0}' falló (código {1}): {2}").format(tool_info["name"], proc.returncode, tail)

    if not os.path.exists(output_path) or os.path.getsize(output_path) < 100:
        return False, QCoreApplication.translate("upscale_engine", "'{0}' no generó una salida válida.").format(tool_info["name"])

    if progress_callback and reports_progress:
        progress_callback(100.0)

    return True, QCoreApplication.translate("upscale_engine", "Reescalado completado.")
