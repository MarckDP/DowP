import os
import platform
import shutil
from core.logger.logger_manager import logger
from core.utils.paths import get_bundled_vegas_importer_dir


def is_supported() -> bool:
    """VEGAS Pro solo existe en Windows."""
    return platform.system() == "Windows"


def get_vegas_extensions_dir() -> str:
    """Ruta de extensiones de aplicación de VEGAS Pro del usuario actual."""
    if not is_supported():
        return ""
    base = os.environ.get("APPDATA") or os.path.expanduser("~/AppData/Roaming")
    return os.path.join(base, "VEGAS Pro", "Application Extensions")


def find_vegas_installations() -> list:
    """Busca instalaciones conocidas de VEGAS Pro en el sistema."""
    if not is_supported():
        return []

    installations = []
    # Carpetas comunes
    roots = [
        r"C:\Program Files\BorisFX",
        r"C:\Program Files\VEGAS",
        r"C:\Program Files\Sony",
        r"C:\Program Files (x86)\VEGAS",
        r"C:\Program Files (x86)\Sony"
    ]

    for root in roots:
        if not os.path.isdir(root):
            continue
        try:
            for item in os.listdir(root):
                folder_path = os.path.join(root, item)
                if os.path.isdir(folder_path) and ("vegas" in item.lower() or "borisfx" in root.lower()):
                    for file_name in os.listdir(folder_path):
                        if file_name.lower().startswith("vegas") and file_name.lower().endswith(".exe"):
                            installations.append(os.path.join(folder_path, file_name))
        except Exception:
            pass

    return installations


def is_vegas_installed() -> bool:
    """Retorna True si se detecta al menos una instalación de VEGAS Pro."""
    return len(find_vegas_installations()) > 0


def is_extension_installed() -> bool:
    """Retorna True si DowPImporter.dll está presente en la carpeta de extensiones."""
    ext_dir = get_vegas_extensions_dir()
    if not ext_dir:
        return False
    dll_path = os.path.join(ext_dir, "DowPImporter.dll")
    return os.path.isfile(dll_path)


def get_vegas_version_icon() -> str:
    """Retorna el nombre del archivo SVG del icono de VEGAS Pro basado en la versión instalada."""
    installations = find_vegas_installations()
    if not installations:
        return "vegas pro.svg"

    max_version = 0
    import re
    for inst in installations:
        filename = os.path.basename(inst).lower()
        match = re.search(r'vegas(\d{2,3})\.exe', filename)
        if match:
            v_str = match.group(1)
            # If 160 -> 16, if 210 -> 21
            v = int(v_str[:2]) if len(v_str) == 3 else int(v_str)
            if v > max_version:
                max_version = v

    if max_version >= 25:
        return "vegas pro 25.svg"
    elif max_version >= 19:
        return "vegas pro 19.svg"
    elif max_version > 0:
        return "vegas pro 18.svg"

    return "vegas pro.svg"


def install_vegas_extension() -> tuple[bool, str]:
    """Copia la DLL compilada y su archivo .config al directorio de extensiones de VEGAS."""
    if not is_supported():
        return False, "VEGAS Pro solo está disponible en Windows."

    src_dir = get_bundled_vegas_importer_dir()
    src_dll = os.path.join(src_dir, "DowPImporter.dll")
    src_cfg = os.path.join(src_dir, "DowPImporter.dll.config")

    if not os.path.isfile(src_dll):
        return False, f"No se encontró el binario compilado de la extensión en: {src_dir}"

    dest_dir = get_vegas_extensions_dir()
    try:
        os.makedirs(dest_dir, exist_ok=True)
        shutil.copy2(src_dll, dest_dir)
        if os.path.isfile(src_cfg):
            shutil.copy2(src_cfg, dest_dir)
        elif os.path.isfile(os.path.join(dest_dir, "DowPImporter.dll.config")):
            # Previous builds shipped a redirect to VEGAS 2026.  It prevents a
            # single DLL from being portable across host versions.
            os.remove(os.path.join(dest_dir, "DowPImporter.dll.config"))

        logger.info(f"[VegasSetup] Extensión instalada exitosamente en: {dest_dir}")
        return True, "DowP Importer para VEGAS Pro instalado correctamente."
    except Exception as e:
        logger.error(f"[VegasSetup] Error al instalar la extensión: {e}")
        return False, str(e)


def remove_vegas_extension() -> tuple[bool, str]:
    """Elimina la extensión de la carpeta de extensiones de VEGAS."""
    if not is_supported():
        return False, "VEGAS Pro solo está disponible en Windows."

    dest_dir = get_vegas_extensions_dir()
    dll_path = os.path.join(dest_dir, "DowPImporter.dll")
    cfg_path = os.path.join(dest_dir, "DowPImporter.dll.config")

    try:
        if os.path.isfile(dll_path):
            os.remove(dll_path)
        if os.path.isfile(cfg_path):
            os.remove(cfg_path)
        logger.info("[VegasSetup] Extensión desinstalada exitosamente.")
        return True, "DowP Importer desinstalado de VEGAS Pro."
    except Exception as e:
        logger.error(f"[VegasSetup] Error al desinstalar la extensión: {e}")
        return False, str(e)
