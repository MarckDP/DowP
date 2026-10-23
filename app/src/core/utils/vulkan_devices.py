"""GPU que ve Vulkan, para la transcripción con whisper.cpp (paquete Vulkan de dowp-runtimes).

Por qué existe: whisper.cpp cuenta como GPU tanto las dedicadas como las integradas, en el
orden en que Vulkan las lista, y usa la primera. En un portátil Intel + NVIDIA esa puede ser
la integrada. DowP elige la dedicada y se la pasa a whisper.cpp con GGML_VK_VISIBLE_DEVICES,
que usa justo este índice de Vulkan (ver gpu_env).

Todo es de solo lectura: se crea una instancia de Vulkan, se enumeran los dispositivos y se
leen sus propiedades; nunca se crea un dispositivo lógico. Solo usa ctypes y la biblioteca
de Vulkan que instala el driver de la GPU (vulkan-1.dll en Windows, libvulkan.so.1 en
Linux). Si algo falla, devuelve una lista vacía: sin Vulkan no hay aceleración, nada más.
"""
import ctypes
import ctypes.util
import os
import platform
from functools import lru_cache
from typing import NamedTuple

from core.logger.logger_manager import logger

_VENDORS = {0x10DE: "NVIDIA", 0x1002: "AMD", 0x1022: "AMD", 0x8086: "Intel", 0x106B: "Apple"}
# VkPhysicalDeviceType
_DISCRETE, _INTEGRATED, _VIRTUAL, _CPU = 2, 1, 3, 4
_VK_SUCCESS = 0
_VK_INCOMPLETE = 5
_VK_STRUCTURE_TYPE_APPLICATION_INFO = 0
_VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO = 1
_VK_API_VERSION_1_1 = (1 << 22) | (1 << 12)


class VulkanDevice(NamedTuple):
    index: int          # índice de vkEnumeratePhysicalDevices (el de GGML_VK_VISIBLE_DEVICES)
    name: str
    vendor_id: int
    device_type: int    # 1 integrada, 2 dedicada, 3 virtual, 4 CPU

    @property
    def vendor(self) -> str:
        return _VENDORS.get(self.vendor_id, f"0x{self.vendor_id:04X}")

    @property
    def is_discrete(self) -> bool:
        return self.device_type == _DISCRETE

    @property
    def is_gpu(self) -> bool:
        return self.device_type in (_DISCRETE, _INTEGRATED)


class _AppInfo(ctypes.Structure):
    _fields_ = [("sType", ctypes.c_uint32), ("pNext", ctypes.c_void_p), ("pApplicationName", ctypes.c_char_p),
                ("applicationVersion", ctypes.c_uint32), ("pEngineName", ctypes.c_char_p),
                ("engineVersion", ctypes.c_uint32), ("apiVersion", ctypes.c_uint32)]


class _InstanceInfo(ctypes.Structure):
    _fields_ = [("sType", ctypes.c_uint32), ("pNext", ctypes.c_void_p), ("flags", ctypes.c_uint32),
                ("pApplicationInfo", ctypes.POINTER(_AppInfo)), ("enabledLayerCount", ctypes.c_uint32),
                ("ppEnabledLayerNames", ctypes.c_void_p), ("enabledExtensionCount", ctypes.c_uint32),
                ("ppEnabledExtensionNames", ctypes.c_void_p)]


def _load_library():
    system = platform.system()
    if system == "Windows":
        names = ["vulkan-1.dll"]
    elif system == "Linux":
        names = ["libvulkan.so.1", ctypes.util.find_library("vulkan")]
    else:
        return None  # en macOS whisper.cpp usa Metal
    for name in names:
        if not name:
            continue
        try:
            return ctypes.CDLL(name)
        except OSError:
            continue
    return None


@lru_cache(maxsize=1)
def list_vulkan_devices() -> tuple:
    """Los dispositivos de Vulkan del equipo, en su orden. Vacío si no hay Vulkan."""
    library = _load_library()
    if library is None:
        return ()
    instance = ctypes.c_void_p()
    try:
        create = library.vkCreateInstance
        create.restype = ctypes.c_int32
        create.argtypes = [ctypes.POINTER(_InstanceInfo), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        enumerate_devices = library.vkEnumeratePhysicalDevices
        enumerate_devices.restype = ctypes.c_int32
        enumerate_devices.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
        properties = library.vkGetPhysicalDeviceProperties
        properties.restype = None
        properties.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        destroy = library.vkDestroyInstance
        destroy.restype = None
        destroy.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

        app = _AppInfo(_VK_STRUCTURE_TYPE_APPLICATION_INFO, None, b"DowP", 1, b"DowP", 1, _VK_API_VERSION_1_1)
        info = _InstanceInfo(_VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, None, 0, ctypes.pointer(app), 0, None, 0, None)
        if create(ctypes.byref(info), None, ctypes.byref(instance)) != _VK_SUCCESS:
            return ()
        try:
            count = ctypes.c_uint32(0)
            if enumerate_devices(instance, ctypes.byref(count), None) not in (_VK_SUCCESS, _VK_INCOMPLETE):
                return ()
            handles = (ctypes.c_void_p * count.value)()
            enumerate_devices(instance, ctypes.byref(count), handles)
            devices = []
            for index in range(count.value):
                # VkPhysicalDeviceProperties: apiVersion, driverVersion, vendorID, deviceID,
                # deviceType (desplazamiento 16) y deviceName[256] (desplazamiento 20). El
                # resto (límites) no hace falta: se reserva de sobra y no se interpreta.
                buffer = ctypes.create_string_buffer(4096)
                properties(handles[index], buffer)
                vendor_id = int.from_bytes(buffer.raw[8:12], "little")
                device_type = int.from_bytes(buffer.raw[16:20], "little")
                name = buffer.raw[20:276].split(b"\0", 1)[0].decode("utf-8", "replace")
                devices.append(VulkanDevice(index, name, vendor_id, device_type))
            return tuple(devices)
        finally:
            destroy(instance, None)
    except Exception as exc:
        logger.warning(f"Vulkan: no se pudieron enumerar los dispositivos: {exc}")
        return ()


def preferred_gpu():
    """La GPU que conviene usar: la primera dedicada; si no hay, la primera integrada."""
    gpus = [d for d in list_vulkan_devices() if d.is_gpu]
    return next((d for d in gpus if d.is_discrete), gpus[0] if gpus else None)


def gpu_env(env=None) -> dict:
    """Entorno para whisper-cli con Vulkan: GGML_VK_VISIBLE_DEVICES apuntando a la GPU
    preferida, para que no tome la integrada en un equipo con dos. Si el usuario ya lo
    definió, se respeta."""
    env = dict(os.environ if env is None else env)
    gpu = preferred_gpu()
    if gpu is not None and "GGML_VK_VISIBLE_DEVICES" not in env:
        env["GGML_VK_VISIBLE_DEVICES"] = str(gpu.index)
    return env
