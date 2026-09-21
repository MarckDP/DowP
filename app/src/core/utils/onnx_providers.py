# src/core/utils/onnx_providers.py
"""Selección de execution providers de ONNX Runtime por SO, para Eliminar Fondo IA
(ver core/tabs/image_tools/rembg_engine.py) y cualquier otro motor ONNX futuro.

Windows -> onnxruntime-directml (DmlExecutionProvider): NVIDIA/AMD/Intel sin
depender de un toolkit CUDA instalado aparte (DirectX 12 ya viene con el SO).
macOS -> onnxruntime estándar, que ya trae compilado CoreMLExecutionProvider en
el wheel oficial (usa GPU/Neural Engine solo cuando conviene, sin config extra).
Linux -> CPUExecutionProvider nada más por ahora (sin toolkit CUDA/ROCm que
pedirle al usuario -- decisión de portabilidad, ver memoria de proyecto
"DowP ONNX Runtime GPU strategy"). requirements.txt ya instala el paquete
correcto por SO vía marcadores PEP 508 -- este módulo solo elige qué provider
pedirle a la sesión, nunca instala nada.
"""
import platform

from core.logger.logger_manager import logger
from core.utils.gpu_adapters import get_preferred_adapter, list_gpu_adapters

# DirectML: firmas de error conocidas de cuelgue/timeout del driver de GPU --
# 887A0007 es el HRESULT de DXGI_ERROR_DEVICE_HUNG. Confirmadas en producción
# por DowP1 (image_converter.pyc decompilado), que reintentaba por CPU al
# toparse con cualquiera de estas. Vive aquí (no en rembg_engine.py) porque es
# una propiedad del provider DirectML, no del motor de Eliminar Fondo en sí --
# cualquier motor ONNX futuro que use DML puede reusar esta misma lista.
DML_FAILURE_HINTS = ("DmlFusedNode", "887A0007", "Non-zero status")


def is_gpu_failure(error: Exception) -> bool:
    """True si `error` justifica reintentar por CPU un motor ONNX que corría por GPU.

    Además de las firmas de DirectML de DML_FAILURE_HINTS, un UnicodeDecodeError: con
    Windows en español, onnxruntime a veces no llega a entregar el mensaje de error de
    DirectML (trae acentos en la codificación de Windows, no en UTF-8) y Python lanza
    esto en su lugar -- visto en las pruebas de los modelos de profundidad. Sin esta
    comprobación, ese error no contiene ninguna de las firmas y el reintento por CPU no
    se activaba nunca."""
    if isinstance(error, UnicodeDecodeError):
        return True
    error_msg = repr(error)
    return any(hint in error_msg for hint in DML_FAILURE_HINTS)


# Una entrada de la lista de providers es el nombre a secas ("CPUExecutionProvider") o
# la tupla (nombre, opciones) que acepta onnxruntime para configurarlo -- que es como
# se le pasa el device_id a DirectML.
ExecutionProvider = str | tuple[str, dict]


def provider_name(entry: ExecutionProvider | None) -> str | None:
    """El nombre del provider, venga como cadena suelta o como tupla (nombre, opciones).
    Todo lo que compare contra "DmlExecutionProvider" y compañía tiene que pasar por
    aquí: desde que se le pasan opciones a DirectML, providers[0] ya no siempre es str."""
    if isinstance(entry, tuple):
        return entry[0]
    return entry


def _provider_device_id(entry: ExecutionProvider | None) -> int | None:
    if isinstance(entry, tuple):
        return entry[1].get("device_id")
    return None


def get_execution_providers(use_gpu: bool) -> list[ExecutionProvider]:
    """Lista de providers a pedirle a onnxruntime.InferenceSession, con
    CPUExecutionProvider siempre al final como fallback nativo de ONNX Runtime
    (si el primero no puede correr un nodo, cae solo al siguiente de la lista).

    En Windows se le pasa a DirectML el device_id del adaptador que elige
    gpu_adapters.get_preferred_adapter(). Sin ese device_id, DirectML usa el adaptador
    DXGI 0, que en los equipos híbridos es el integrado: ahí estaba el caso del usuario
    con Intel + NVIDIA al que la app le corría todo por la Intel. Si la enumeración
    falla o no encuentra nada utilizable se pide DirectML sin opciones, que es
    exactamente el comportamiento anterior -- peor default, pero nunca un error."""
    if not use_gpu:
        return ["CPUExecutionProvider"]

    try:
        import onnxruntime as ort
        available = ort.get_available_providers()
    except Exception as e:
        logger.warning(f"onnx_providers: no se pudo consultar onnxruntime, usando CPU: {e}")
        return ["CPUExecutionProvider"]

    system = platform.system()
    if system == "Windows" and "DmlExecutionProvider" in available:
        adapter = get_preferred_adapter()
        if adapter is None:
            return ["DmlExecutionProvider", "CPUExecutionProvider"]
        return [("DmlExecutionProvider", {"device_id": adapter.index}), "CPUExecutionProvider"]
    if system == "Darwin" and "CoreMLExecutionProvider" in available:
        return ["CoreMLExecutionProvider", "CPUExecutionProvider"]
    return ["CPUExecutionProvider"]


# Nombre corto de cada provider de GPU, para poder decirle al usuario QUÉ
# aceleración se detectó en vez de un "sí/no" a secas.
_GPU_PROVIDER_LABELS = {
    "DmlExecutionProvider": "DirectML",
    "CoreMLExecutionProvider": "CoreML",
}


def get_gpu_provider() -> str | None:
    """El provider de GPU realmente utilizable en este equipo, o None si solo
    hay CPU. No es una detección de hardware aparte: se le pregunta a
    get_execution_providers() (la misma función que arma la sesión de verdad), así
    que la UI no puede afirmar algo distinto de lo que va a pasar al procesar.

    En la práctica: Windows con un equipo DirectX 12 -> DirectML; macOS -> CoreML;
    Linux -> None siempre, porque ahí no instalamos onnxruntime-gpu a propósito
    (ver la nota de arriba). Un Windows sin GPU compatible tampoco expone
    DmlExecutionProvider, así que también cae en None."""
    providers = get_execution_providers(use_gpu=True)
    primary = provider_name(providers[0]) if providers else None
    return primary if primary and primary != "CPUExecutionProvider" else None


def get_gpu_provider_label() -> str | None:
    """Nombre presentable del provider de GPU detectado ("DirectML", "CoreML"),
    o None si no hay."""
    provider = get_gpu_provider()
    if provider is None:
        return None
    return _GPU_PROVIDER_LABELS.get(provider, provider)


def has_gpu_acceleration() -> bool:
    return get_gpu_provider() is not None


def get_gpu_adapter_name() -> str | None:
    """Nombre de la tarjeta CONCRETA en la que va a correr la inferencia por GPU, o
    None si no se puede saber cuál es.

    Existe porque hardware_detector.get_cached_gpu_name() une con " / " todas las
    tarjetas que ve el sistema: en un equipo híbrido devuelve "NVIDIA GeForce RTX 3060
    / Intel UHD Graphics", que es justo lo que NO responde la pregunta "¿cuál está
    usando?". Aquí se devuelve solo el adaptador que se le pidió a DirectML.

    None en macOS (CoreML reparte entre GPU y Neural Engine por su cuenta, no hay una
    tarjeta que nombrar), en Linux (sin ruta de GPU) y si la enumeración DXGI falló --
    en todos esos casos quien llame debería caer al nombre genérico de siempre."""
    providers = get_execution_providers(use_gpu=True)
    device_id = _provider_device_id(providers[0]) if providers else None
    if device_id is None:
        return None
    adapter = next((a for a in list_gpu_adapters() if a.index == device_id), None)
    return adapter.name if adapter else None


def describe_providers(providers: list[ExecutionProvider]) -> str:
    """Texto del provider principal para los logs: "DirectML (device_id=0, NVIDIA
    GeForce RTX 3060)" en vez de la tupla cruda. Es lo que deja en el log de qué GPU
    se está usando de verdad -- el dato que hacía falta para diagnosticar el caso del
    equipo híbrido sin tener el equipo delante."""
    if not providers:
        return "sin providers"
    name = provider_name(providers[0])
    label = _GPU_PROVIDER_LABELS.get(name, name)
    device_id = _provider_device_id(providers[0])
    if device_id is None:
        return label
    adapter = next((a for a in list_gpu_adapters() if a.index == device_id), None)
    detail = f"device_id={device_id}" + (f", {adapter.name}" if adapter else "")
    return f"{label} ({detail})"


def providers_signature(providers: list[ExecutionProvider]) -> str:
    """Firma estable del provider principal, para la clave de caché de sesiones (ver
    onnx_sessions.get_session). Tiene que incluir el device_id: dos sesiones del mismo
    modelo en dos GPU distintas no son intercambiables, y con la clave vieja ("gpu" a
    secas) cambiar de GPU habría devuelto la sesión de la anterior. Sin guiones bajos
    a propósito, que la clave de caché los usa como separador."""
    if not providers:
        return "none"
    name = provider_name(providers[0])
    device_id = _provider_device_id(providers[0])
    return name if device_id is None else f"{name}:{device_id}"


def build_session_options(providers: list[ExecutionProvider]):
    """SessionOptions afinado según el provider principal -- portado de DowP1
    (image_converter.pyc), que llegó a esta configuración específica para evitar
    cuelgues reales de driver con DirectML en producción:
      - DirectML: enable_mem_pattern=False (workaround conocido de DML) +
        ejecución secuencial de un solo hilo -- corre menos rápido en el papel,
        pero es lo que dejó de colgar el driver de GPU en los equipos de los
        usuarios de DowP1.
      - CPU: al revés, ejecución paralela + todas las optimizaciones de grafo,
        no hay ningún driver de por medio que se pueda colgar.
      - CoreML (macOS): sin tuning propio todavía -- no hay evidencia de que
        necesite el mismo workaround que DirectML (nunca corrió en producción
        ahí), se deja el SessionOptions por defecto."""
    import onnxruntime as ort
    opts = ort.SessionOptions()
    primary = provider_name(providers[0]) if providers else None

    # Desactivar el arena allocator de CPU en todos los providers: el BFC arena
    # retiene bloques grandes de memoria para reutilizarlos entre runs, lo cual es
    # bueno para rendimiento en inferencia repetida pero impide que la memoria se
    # devuelva al OS al destruir la sesión (el síntoma: la RAM no vuelve a bajar
    # tras presionar "Liberar"). Sin arena, cada run es ~5-10% más lento pero la
    # memoria se libera de verdad al hacer clear_sessions().
    opts.enable_cpu_mem_arena = False

    if primary == "DmlExecutionProvider":
        opts.enable_mem_pattern = False
        opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        # DirectML usa buffers de staging CPU↔GPU que también quedan retenidos --
        # enable_mem_reuse=False fuerza a que se liberen tras cada sesión, mismo
        # tradeoff (un poco más lento, pero la memoria vuelve al OS de verdad).
        try:
            opts.enable_mem_reuse = False
        except AttributeError:
            pass  # Disponible desde ORT ≥1.17, ignorar en versiones anteriores
    elif primary == "CPUExecutionProvider":
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.execution_mode = ort.ExecutionMode.ORT_PARALLEL

    return opts
