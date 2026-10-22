"""Desinstalación de binarios opcionales que instaló DowP; nunca de instalaciones del sistema."""
import platform
import shutil
from pathlib import Path

from core.utils.paths import get_bin_root_dir


def uninstall_optional(name, progress_callback=None):
    if name not in {"vtracer", "ghostscript"}:
        return False, "Dependencia opcional no reconocida."
    if name == "ghostscript" and platform.system() != "Windows":
        return False, "Ghostscript pertenece al sistema; desinstálalo con su gestor de paquetes."
    parent = (Path(get_bin_root_dir()) / "bin" / "dependences").resolve()
    target = parent / name
    try:
        if target.is_symlink() or target.resolve() != target:
            raise ValueError("La dependencia no está dentro de la carpeta gestionada por DowP.")
        if target.exists():
            shutil.rmtree(target)
        if progress_callback:
            progress_callback(100)
        return True, f"{name} desinstalado."
    except Exception as exc:
        return False, str(exc)
