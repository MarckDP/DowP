# src/core/utils/onnx_sessions.py
"""Caché de sesiones ONNX compartida por todos los motores de IA del Editor de
Imagen (Eliminar Fondo, ver core/tabs/image_tools/rembg_engine.py, y Mapa de
Profundidad, ver depth_engine.py).

Vivía dentro de rembg_engine.py. Se sacó aquí al entrar el segundo motor ONNX
porque las opciones de Ajustes > Modelos ("Mantener los modelos de IA cargados
en memoria", "Cantidad máxima de modelos en memoria", "Liberar") hablan de "los
modelos de IA", no de uno en particular: con dos cachés separadas, "Liberar"
habría dejado cargado el modelo de profundidad y el límite de memoria se habría
aplicado dos veces.

Sesiones cacheadas por (ruta_modelo, gpu|cpu) -- evita recargar los pesos en
cada imagen de un lote. Vive a nivel de módulo: dura lo que dura el proceso de
la app, no una instancia puntual de ImageConverter."""
import gc
import os
import threading

from core.logger.logger_manager import logger
from core.utils.onnx_providers import build_session_options, get_execution_providers

_sessions: dict = {}
_sessions_lock = threading.Lock()

# Piso temporal del límite de sesiones, para que un mismo lote que usa DOS
# motores (Eliminar Fondo + Mapa de Profundidad) no se desaloje a sí mismo en
# cada imagen con el límite por defecto de 1 -- cargaría y tiraría los dos
# modelos una vez por archivo. Lo fija ImageConvertWorker al empezar el lote y
# lo vuelve a 0 al terminar (ver set_min_capacity).
_min_capacity = 0


def set_min_capacity(count: int) -> None:
    global _min_capacity
    with _sessions_lock:
        _min_capacity = max(0, int(count))


def _max_sessions() -> int:
    from core.utils.config_manager import get_config
    configured = int(get_config().get("rembg_max_cached_sessions", 1))
    return max(1, configured, _min_capacity)


def get_session(model_path: str, use_gpu: bool, label: str = "IA"):
    """Devuelve la sesión cacheada o la crea.

    Si la sesión no se puede crear con la optimización de grafo al máximo, se
    reintenta una vez con ORT_ENABLE_EXTENDED. Caso real: el Depth Anything V2
    FP16 de onnx-community no carga en CPU con ORT_ENABLE_ALL (la fusión
    SimplifiedLayerNormFusion busca un nodo que no existe) y sí con EXTENDED --
    probado con onnxruntime 1.24. Para el resto de modelos el primer intento
    funciona y este reintento nunca corre."""
    key = f"{model_path}_{'gpu' if use_gpu else 'cpu'}"
    with _sessions_lock:
        session = _sessions.get(key)
        if session is not None:
            return session

        # Cada sesión ONNX puede pesar 200-900 MB en RAM/VRAM -- acumular sin
        # límite haría explotar la memoria. Cuando se excede, se desaloja la más
        # antigua (FIFO: primer key del dict, que conserva orden de inserción).
        max_sessions = _max_sessions()
        while len(_sessions) >= max_sessions:
            oldest_key = next(iter(_sessions))
            logger.info(f"{label}: desalojando sesión antigua "
                        f"({os.path.basename(oldest_key.rsplit('_', 1)[0])}) "
                        f"para respetar el límite de {max_sessions} modelo(s) en memoria")
            del _sessions[oldest_key]

        import onnxruntime as ort
        providers = get_execution_providers(use_gpu)
        sess_options = build_session_options(providers)
        logger.info(f"{label}: cargando sesión ONNX ({providers[0]}): {os.path.basename(model_path)}")
        try:
            session = ort.InferenceSession(model_path, providers=providers, sess_options=sess_options)
        except Exception as e:
            if sess_options.graph_optimization_level != ort.GraphOptimizationLevel.ORT_ENABLE_ALL:
                raise
            logger.warning(f"{label}: la sesión no cargó con optimización completa ({e}) "
                           f"-- reintentando con ORT_ENABLE_EXTENDED.")
            sess_options = build_session_options(providers)
            sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED
            session = ort.InferenceSession(model_path, providers=providers, sess_options=sess_options)
        _sessions[key] = session
        return session


def loaded_session_count() -> int:
    """Cuántas sesiones ONNX hay cargadas ahora mismo -- lo consulta Ajustes >
    Modelos para decir qué se liberó al apretar "Liberar"."""
    with _sessions_lock:
        return len(_sessions)


def clear_sessions() -> int:
    """Libera las sesiones ONNX cacheadas (memoria de GPU/CPU) y devuelve
    cuántas eran -- se llama al terminar un lote (ver ImageConvertWorker.run) y
    también a mano desde Ajustes > Modelos, donde ese número es lo que se le
    muestra al usuario."""
    with _sessions_lock:
        freed = len(_sessions)
        if not freed:
            return 0
        logger.debug(f"Modelos IA: liberando {freed} sesión(es) ONNX.")
        _sessions.clear()

    # gc.collect() doble: Python usa 3 generaciones de recolección; el segundo
    # pase recoge objetos que quedaron en la generación siguiente tras el primero.
    gc.collect()
    gc.collect()

    # En Windows, forzar al OS a reclamar las páginas de memoria que el proceso ya
    # no usa (quedan mapeadas pero inactivas tras liberar la sesión ONNX). Esto
    # baja el "Working Set" visible en Task Manager sin costo funcional: si el
    # proceso vuelve a necesitar esas páginas, el OS las trae de vuelta del pagefile
    # con un page fault transparente.
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            # Tipos declarados a mano: sin ellos ctypes pasa el pseudo-handle y
            # los -1 como int de 32 bits, y en Windows de 64 bits la llamada
            # puede fallar en silencio (pasó igual con GetProcessMemoryInfo en
            # la prueba de modelos de profundidad).
            k32 = ctypes.windll.kernel32
            k32.GetCurrentProcess.restype = wintypes.HANDLE
            k32.SetProcessWorkingSetSize.argtypes = (wintypes.HANDLE, ctypes.c_size_t, ctypes.c_size_t)
            k32.SetProcessWorkingSetSize(k32.GetCurrentProcess(), ctypes.c_size_t(-1).value,
                                         ctypes.c_size_t(-1).value)
        except Exception as e:
            logger.debug(f"Modelos IA: no se pudo recortar el working set: {e}")

    return freed
