# src/core/utils/gpu_adapters.py
"""Enumeración de los adaptadores gráficos del equipo por DXGI (solo Windows), para
poder decirle a DirectML CUÁL GPU usar en vez de aceptar la que le toque.

Por qué existe: onnxruntime-directml, si no se le pasa "device_id", usa el adaptador
DXGI 0. En un equipo híbrido (gráficos integrados + tarjeta dedicada) ese índice 0
suele ser el integrado, así que DowP venía pidiendo explícitamente la GPU más lenta --
reportado por un usuario con Intel + NVIDIA al que "no le funcionaba la NVIDIA". No era
una configuración suya: era este módulo faltando.

Por qué DXGI y no Win32_VideoController (lo que usa hardware_detector.py para mostrar
el nombre de la tarjeta): WMI da los nombres pero NO en el orden de DXGI, y lo que
DirectML necesita es justamente el índice de DXGI. El device_id del provider DML es el
índice de IDXGIFactory1::EnumAdapters1 tal cual -- onnxruntime lo pasa directo a esa
llamada y después rechaza el adaptador si resulta ser de software -- así que la única
forma de mapear "la NVIDIA" al device_id correcto es enumerar por DXGI nosotros mismos.

Todo aquí es de solo lectura: se enumera y se leen descriptores, nunca se crea un
dispositivo D3D ni se toca el driver. Y todo va envuelto en try/except -- si algo falla
se devuelve una lista vacía y quien llame se queda con el comportamiento de antes
(DirectML sin device_id), nunca con una excepción.
"""
import ctypes
import platform
import threading
from ctypes import POINTER, byref, c_void_p
from typing import NamedTuple

from core.logger.logger_manager import logger


class GpuAdapter(NamedTuple):
    """Un adaptador tal como lo ve DXGI. `index` es lo que hay que pasarle a
    DirectML como device_id; el resto es para elegir cuál y para poder escribirlo
    en el log cuando a alguien no le funcione la GPU que esperaba."""
    index: int
    name: str
    vendor_id: int
    dedicated_vram: int  # bytes
    is_software: bool

    @property
    def vendor_name(self) -> str:
        return _VENDOR_NAMES.get(self.vendor_id, f"0x{self.vendor_id:04X}")

    def describe(self) -> str:
        return (f"[{self.index}] {self.name} ({self.vendor_name}, "
                f"{self.dedicated_vram / (1024 ** 3):.1f} GB)")


# PCI vendor IDs. Microsoft (0x1414) es el del "Microsoft Basic Render Driver", el
# rasterizador por software que DXGI SIEMPRE enumera como un adaptador más -- en el
# equipo de pruebas ocupa el índice 1, justo el que alguien elegiría "a ojo" pensando
# que es la segunda tarjeta.
_VENDOR_NVIDIA = 0x10DE
_VENDOR_AMD = 0x1002
_VENDOR_AMD_ALT = 0x1022
_VENDOR_INTEL = 0x8086
_VENDOR_MICROSOFT = 0x1414

_VENDOR_NAMES = {
    _VENDOR_NVIDIA: "NVIDIA",
    _VENDOR_AMD: "AMD",
    _VENDOR_AMD_ALT: "AMD",
    _VENDOR_INTEL: "Intel",
    _VENDOR_MICROSOFT: "Microsoft",
}

# Prioridad de fabricante al elegir GPU, y por qué el fabricante pesa MÁS que la VRAM:
# en Windows x86 NVIDIA no fabrica gráficos integrados, así que si hay una NVIDIA en la
# lista es, con certeza práctica, la dedicada. Ordenar solo por VRAM fallaría en los
# portátiles Ryzen modernos, donde la BIOS puede reservarle 8 GB o más a la APU y
# dejarla por encima de una GPU dedicada de 6 GB. La VRAM entra como desempate, que es
# donde sí acierta: entre dos adaptadores del MISMO fabricante (APU AMD vs Radeon
# dedicada, o iGPU Intel vs Arc dedicada), el de más memoria dedicada es el discreto.
_VENDOR_PRIORITY = {
    _VENDOR_NVIDIA: 3,
    _VENDOR_AMD: 2,
    _VENDOR_AMD_ALT: 2,
    _VENDOR_INTEL: 1,
}

# DXGI_ADAPTER_FLAG_SOFTWARE: marca al adaptador emulado por software. Es la forma
# fiable de descartar el Basic Render Driver, mejor que comparar el nombre (que está
# traducido en algunos idiomas de Windows).
_DXGI_ADAPTER_FLAG_SOFTWARE = 2

# HRESULT con el que EnumAdapters1 avisa "ya no hay más adaptadores": es el fin normal
# del bucle, no un error.
_DXGI_ERROR_NOT_FOUND = 0x887A0002

# Tope de seguridad del bucle de enumeración: ningún equipo real tiene tantos
# adaptadores, y evita quedarse colgado si EnumAdapters1 devolviera S_OK para siempre.
_MAX_ADAPTERS = 16

# Índices de los métodos en la vtable COM. COM no tiene introspección: hay que contar
# las posiciones heredadas. IDXGIFactory1: IUnknown (0-2) + IDXGIObject (3-6) +
# IDXGIFactory (7-11) + EnumAdapters1 (12). IDXGIAdapter1: IUnknown (0-2) +
# IDXGIObject (3-6) + IDXGIAdapter (7-9) + GetDesc1 (10).
_VT_RELEASE = 2
_VT_ENUM_ADAPTERS1 = 12
_VT_GET_DESC1 = 10


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]


class _LUID(ctypes.Structure):
    _fields_ = [("LowPart", ctypes.c_uint32), ("HighPart", ctypes.c_int32)]


class _DXGI_ADAPTER_DESC1(ctypes.Structure):
    """Espejo exacto de DXGI_ADAPTER_DESC1 (dxgi.h). El orden y los tipos importan:
    ctypes calcula el relleno de alineación solo, pero si un campo estuviera de más o
    de menos se leerían bytes corridos y saldrían nombres y tamaños basura. Son 312
    bytes en x64 -- comprobado contra el valor real de ctypes.sizeof()."""
    _fields_ = [("Description", ctypes.c_wchar * 128),
                ("VendorId", ctypes.c_uint32), ("DeviceId", ctypes.c_uint32),
                ("SubSysId", ctypes.c_uint32), ("Revision", ctypes.c_uint32),
                ("DedicatedVideoMemory", ctypes.c_size_t),
                ("DedicatedSystemMemory", ctypes.c_size_t),
                ("SharedSystemMemory", ctypes.c_size_t),
                ("AdapterLuid", _LUID), ("Flags", ctypes.c_uint32)]


_IID_IDXGIFactory1 = _GUID(0x770AAE78, 0xF26F, 0x4DBA,
                           (ctypes.c_ubyte * 8)(0xA8, 0x29, 0x25, 0x3C,
                                                0x83, 0xD1, 0xB3, 0x87))

# Clave de config, a propósito SIN interfaz, para forzar una GPU concreta cuando la
# heurística de get_preferred_adapter() no acierte (dos tarjetas dedicadas, o alguien
# que quiera la integrada a propósito para dejar libre la dedicada o para gastar menos
# batería). Se guarda el NOMBRE del adaptador y no su índice: los índices DXGI se
# reordenan al actualizar el driver, al conectar un dock o al enchufar una eGPU, y un
# índice guardado terminaría apuntando a otra tarjeta sin avisar. Acepta el nombre
# completo o un trozo ("nvidia", "intel"), sin distinguir mayúsculas.
GPU_OVERRIDE_CONFIG_KEY = "ai_gpu_adapter"

_adapters_cache: list[GpuAdapter] | None = None
_cache_lock = threading.Lock()

# Valores de la config que ya se avisó que no coinciden con ninguna GPU. Sin esto, el
# aviso saldría en cada carga de modelo y ensuciaría el log justo cuando hace falta
# leerlo para entender qué GPU se eligió.
_warned_overrides: set[str] = set()


def _vtable_call(interface: c_void_p, slot: int, restype, argtypes, *args):
    """Invoca el método `slot` de la vtable de un objeto COM.

    Un puntero a interfaz COM apunta a un puntero a la vtable, que es un array de
    punteros a función; de ahí el doble cast. Todo método COM recibe el propio
    puntero como primer argumento (el `this` implícito de C++), por eso va delante
    en la firma de WINFUNCTYPE."""
    vtable = ctypes.cast(interface, POINTER(POINTER(c_void_p)))[0]
    func = ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)(vtable[slot])
    return func(interface, *args)


def _release(interface: c_void_p) -> None:
    """IUnknown::Release. COM cuenta referencias a mano: sin esto, cada escaneo
    dejaría el factory y los adaptadores vivos hasta cerrar la app."""
    try:
        _vtable_call(interface, _VT_RELEASE, ctypes.c_ulong, ())
    except Exception as e:
        logger.debug(f"gpu_adapters: fallo al liberar interfaz COM: {e}")


def _enumerate_dxgi_adapters() -> list[GpuAdapter]:
    """Recorre IDXGIFactory1::EnumAdapters1 y devuelve los adaptadores en el mismo
    orden en que los ve DirectML. Lista vacía si algo sale mal."""
    dxgi = ctypes.WinDLL("dxgi")
    dxgi.CreateDXGIFactory1.argtypes = (POINTER(_GUID), POINTER(c_void_p))
    dxgi.CreateDXGIFactory1.restype = ctypes.c_long

    factory = c_void_p()
    hr = dxgi.CreateDXGIFactory1(byref(_IID_IDXGIFactory1), byref(factory))
    if hr != 0 or not factory:
        logger.warning(f"gpu_adapters: CreateDXGIFactory1 falló (hr=0x{hr & 0xFFFFFFFF:08X})")
        return []

    adapters: list[GpuAdapter] = []
    try:
        for index in range(_MAX_ADAPTERS):
            adapter = c_void_p()
            hr = _vtable_call(factory, _VT_ENUM_ADAPTERS1, ctypes.c_long,
                              (ctypes.c_uint, POINTER(c_void_p)), index, byref(adapter))
            if hr != 0 or not adapter:
                if (hr & 0xFFFFFFFF) != _DXGI_ERROR_NOT_FOUND:
                    logger.debug(f"gpu_adapters: EnumAdapters1({index}) -> "
                                 f"hr=0x{hr & 0xFFFFFFFF:08X}")
                break
            try:
                desc = _DXGI_ADAPTER_DESC1()
                hr = _vtable_call(adapter, _VT_GET_DESC1, ctypes.c_long,
                                  (POINTER(_DXGI_ADAPTER_DESC1),), byref(desc))
                if hr != 0:
                    logger.debug(f"gpu_adapters: GetDesc1({index}) -> "
                                 f"hr=0x{hr & 0xFFFFFFFF:08X}")
                    continue
                adapters.append(GpuAdapter(
                    index=index,
                    name=desc.Description.strip() or f"Adaptador {index}",
                    vendor_id=desc.VendorId,
                    dedicated_vram=int(desc.DedicatedVideoMemory),
                    is_software=bool(desc.Flags & _DXGI_ADAPTER_FLAG_SOFTWARE)
                    or desc.VendorId == _VENDOR_MICROSOFT,
                ))
            finally:
                _release(adapter)
    finally:
        _release(factory)

    return adapters


def list_gpu_adapters(force_refresh: bool = False) -> list[GpuAdapter]:
    """Los adaptadores DXGI del equipo, cacheados a nivel de módulo.

    Se cachea porque esto se consulta al crear cada sesión ONNX, y porque el hardware
    gráfico no cambia mientras la app corre (enchufar una eGPU o actualizar el driver
    reordena la lista, pero eso pide reiniciar de todas formas -- Resolve y Blender
    también lo piden).

    Fuera de Windows devuelve [] siempre: DXGI es una API de Windows, y en macOS
    (CoreML) y Linux (solo CPU) no hay device_id que elegir."""
    global _adapters_cache
    if platform.system() != "Windows":
        return []

    with _cache_lock:
        if _adapters_cache is not None and not force_refresh:
            return _adapters_cache
        try:
            adapters = _enumerate_dxgi_adapters()
        except Exception as e:
            logger.warning(f"gpu_adapters: no se pudo enumerar por DXGI ({e!r}) -- "
                           f"se dejará que DirectML elija el adaptador por su cuenta.")
            adapters = []
        if adapters:
            logger.info("gpu_adapters: adaptadores DXGI detectados -- " + "; ".join(
                a.describe() + (" [software]" if a.is_software else "") for a in adapters))
        _adapters_cache = adapters
        return _adapters_cache


def _resolve_override(adapters: list[GpuAdapter]) -> GpuAdapter | None:
    """El adaptador que pide GPU_OVERRIDE_CONFIG_KEY, o None si no hay preferencia
    guardada o si no se corresponde con ninguna GPU real.

    El resultado NO se cachea a propósito: así editar config.json tiene efecto en la
    siguiente sesión ONNX sin reiniciar la app, porque la caché de onnx_sessions lleva
    el device_id en la clave y un device_id distinto crea una sesión nueva.

    Un valor que no coincide con nada no es motivo para quedarse sin GPU: se avisa en
    el log con la lista de nombres válidos y se sigue con la elección automática."""
    from core.utils.config_manager import get_config
    wanted = str(get_config().get(GPU_OVERRIDE_CONFIG_KEY) or "").strip()
    if not wanted:
        return None

    needle = wanted.casefold()
    # Exacto antes que parcial: con "Intel Arc A770" e "Intel Arc Graphics" en el mismo
    # equipo, el nombre completo tiene que ganarle a la coincidencia por trozo.
    matches = ([a for a in adapters if a.name.casefold() == needle]
               or [a for a in adapters if needle in a.name.casefold()])

    if not matches:
        if wanted not in _warned_overrides:
            _warned_overrides.add(wanted)
            names = ", ".join(f'"{a.name}"' for a in adapters) or "ninguna"
            logger.warning(f'gpu_adapters: la config ({GPU_OVERRIDE_CONFIG_KEY}) pide la '
                           f'GPU "{wanted}", que no coincide con ninguna del equipo '
                           f'({names}) -- se elige automáticamente.')
        return None

    chosen = matches[0]
    if chosen.is_software:
        if wanted not in _warned_overrides:
            _warned_overrides.add(wanted)
            logger.warning(f'gpu_adapters: la config pide "{wanted}", que es el adaptador '
                           f'de software "{chosen.name}" -- DirectML lo rechaza y la '
                           f'inferencia acabaría en CPU. Se elige automáticamente.')
        return None

    logger.debug(f"gpu_adapters: GPU forzada por config -> {chosen.describe()}")
    return chosen


def get_preferred_adapter() -> GpuAdapter | None:
    """El adaptador que debería usar la inferencia por GPU, o None si no hay ninguno
    utilizable (o si la enumeración falló, en cuyo caso quien llame debe seguir con el
    comportamiento por defecto de DirectML).

    Manda la preferencia guardada en la config si la hay (ver GPU_OVERRIDE_CONFIG_KEY).
    Si no, se descartan los adaptadores de software y se ordena por (prioridad de
    fabricante, VRAM dedicada) -- ver el comentario de _VENDOR_PRIORITY para por qué
    ese orden y no al revés."""
    adapters = list_gpu_adapters()
    override = _resolve_override(adapters)
    if override is not None:
        return override
    usable = [a for a in adapters if not a.is_software]
    if not usable:
        return None
    return max(usable, key=lambda a: (_VENDOR_PRIORITY.get(a.vendor_id, 0), a.dedicated_vram))
