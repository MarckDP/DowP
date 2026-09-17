# src/core/tabs/video_tools/upscale_chain.py
"""Pieza compartida de "Reescalado IA encadenado con Recodificación" entre los
3 lugares que la necesitan: Herramientas Multimedia
(gui/tabs/video_tools/video_tools_view.py::_start_chained_jobs, construido
primero y no migrado a esto para no arriesgar código ya probado) y los dos
download_controller.py (Modo Rápido y Proceso Avanzado), que si usan esto
directo para no triplicar la misma lógica.

Solo arma y encola la ETAPA 1 (el job UPSCALE_VIDEO hacia un archivo
temporal) -- la etapa 2 (el RECODE que usa esa salida como entrada, armado
recién cuando la etapa 1 termina bien) la arma cada llamador con
core.utils.preset_manager.build_recode_output_path + su propio
QueueManager.add_job(..., "RECODE"), porque cada uno ya tiene su propio
mecanismo de seguimiento por job_id (distinto en cada lugar) y no tiene
sentido forzarlos a compartir esa parte."""
import os
import uuid


def parse_fps(fps_val) -> float:
    """Convierte 'NN.NN fps'/'NN fps' (formato de FFprobeMetadataManager) a
    float -- 30.0 por defecto si no se puede leer."""
    try:
        return float(str(fps_val).replace("fps", "").strip())
    except (ValueError, AttributeError):
        return 30.0


def probe_fps_and_duration(filepath: str, fallback_duration_sec: float = 0.0) -> tuple[float, float]:
    """fps real del archivo -- CRÍTICO para Reescalado IA (ver reassemble_video
    en este mismo paquete, se usa como -framerate de salida: un valor mal
    puesto no rompe nada visiblemente pero desincroniza la velocidad del
    resultado, confirmado con una corrida real). A diferencia de duration_sec
    (solo cosmético, nada más afecta el % de una barra de progreso), NO
    conviene resolver esto con
    `FFprobeMetadataManager.get_metadata_instant()`: ese método es SOLO-CACHÉ
    por diseño (ver su propio docstring) -- para un archivo recién creado
    (recién descargado, o un intermedio de cadena) NUNCA está en caché y
    devuelve '-' en el campo fps, en silencio, sin excepción -- confirmado con
    una corrida real: el reensamblado salía a 30fps fijo en vez del fps real
    de la fuente. `_extract_ffprobe_json()` es el sondeo SÍNCRONO real (más
    lento, bloquea un poco), el único que sirve para un archivo recién
    creado."""
    from core.tabs.editing_media.ffprobe_metadata_manager import FFprobeMetadataManager
    from core.tabs.video_tools.size_estimator import parse_duration_to_seconds

    meta = FFprobeMetadataManager.get_instance()._extract_ffprobe_json(filepath, "video")
    fps = parse_fps((meta or {}).get("fps", "30"))
    duration_sec = parse_duration_to_seconds((meta or {}).get("duración", "0")) or fallback_duration_sec
    return fps, duration_sec


def start_upscale_stage(qm, input_path: str, upscale_settings: dict, temp_dir: str,
                         fps: float, duration_sec: float, title: str | None = None,
                         extra_config: dict | None = None) -> tuple[str, str]:
    """Arma y encola SOLO la etapa de Reescalado IA, con salida hacia un
    archivo dentro de `temp_dir` (el llamador lo crea con tempfile.mkdtemp()
    y lo barre cuando ya no queda nada corriendo -- ver
    _chain_temp_dir/_check_all_finished en video_tools_view.py para el
    criterio a replicar). Devuelve (job_id, intermediate_path) para que el
    llamador registre su propio seguimiento (qué hacer cuando este job
    termine) -- acá no se sabe nada de eso.

    `extra_config` -- claves adicionales que el llamador necesite guardar en
    job.config (ej. una clave de fila propia, equivalente a
    "queue_entry_key" en video_tools_view.py)."""
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    intermediate_path = os.path.join(temp_dir, f"{uuid.uuid4().hex[:8]}_{base_name}.mp4")

    config = {
        "input_path": input_path,
        "output_path": intermediate_path,
        "upscale_options": upscale_settings,
        "fps": fps,
        "duration_sec": duration_sec,
        "title": title or f"Reescalado IA: {base_name}",
    }
    if extra_config:
        config.update(extra_config)

    job_id = qm.add_job(config, "UPSCALE_VIDEO")
    return job_id, intermediate_path
