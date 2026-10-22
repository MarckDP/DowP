# src/core/setup/models_location.py
"""Cambiar la carpeta donde viven los modelos de IA (Ajustes > Modelos).

DowP se instala donde el usuario quiera, pero los modelos iban siempre a
%LOCALAPPDATA%/DowP2/bin/models, en el disco del sistema, y pueden sumar varios GB.
Aquí se valida la carpeta nueva y se mueven los modelos ya descargados. La ruta se
guarda en config.json ("models_dir") y la lee core/utils/paths.get_models_dir().
"""
import os
import shutil
import sys
import tempfile

from PySide6.QtCore import QCoreApplication

from core.logger.logger_manager import logger
from core.utils.paths import get_default_models_dir, get_models_dir, get_src_dir

# Subcarpetas que crean los modelos de DowP: sirven para reconocer una carpeta de
# modelos ya existente (por ejemplo, la de otra instalación o la que se usó antes).
KNOWN_MODEL_FOLDERS = {"rembg", "rembg_custom", "rmbg2", "depth", "normals", "upscayl",
                       "waifu2x", "srmd", "inspyrenet", "realesrgan", "whisper"}
SUBFOLDER_NAME = "DowP Modelos"


def install_dir() -> str:
    """Carpeta de la instalación: el actualizador la reemplaza entera, así que los
    modelos NUNCA pueden vivir ahí dentro."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(get_src_dir())


def _norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _is_inside(path: str, parent: str) -> bool:
    path, parent = _norm(path), _norm(parent)
    return path == parent or path.startswith(parent.rstrip("\\/") + os.sep)


def folder_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def has_models(path: str) -> bool:
    if not os.path.isdir(path):
        return False
    return any(os.path.isdir(os.path.join(path, d)) and os.listdir(os.path.join(path, d))
               for d in os.listdir(path))


def resolve_target(chosen: str) -> str:
    """La carpeta elegida, o una subcarpeta "DowP Modelos" dentro si la elegida ya
    tiene otras cosas: así no se mezclan los modelos con los archivos del usuario
    (por ejemplo al elegir "D:\\")."""
    chosen = os.path.abspath(chosen)
    if not os.path.isdir(chosen):
        return chosen
    entries = [e for e in os.listdir(chosen) if not e.startswith(".")]
    if not entries or set(entries) & KNOWN_MODEL_FOLDERS or os.path.basename(chosen) == SUBFOLDER_NAME:
        return chosen
    return os.path.join(chosen, SUBFOLDER_NAME)


def validate_target(target: str, current: str) -> tuple[bool, str]:
    """¿Se puede usar `target` como carpeta de modelos? (ok, mensaje para el usuario)."""
    if not target or not os.path.isabs(target):
        return False, QCoreApplication.translate("models_location", "Elige una carpeta válida.")
    if _norm(target) == _norm(current):
        return False, QCoreApplication.translate("models_location", "Esa ya es la carpeta de modelos actual.")
    if _is_inside(target, install_dir()):
        return False, QCoreApplication.translate("models_location", "No puede estar dentro de la carpeta donde está instalado DowP: "
                         "al actualizarse, esa carpeta se reemplaza entera y se perderían los modelos.")
    if _is_inside(target, current):
        return False, QCoreApplication.translate("models_location", "No puede estar dentro de la carpeta de modelos actual.")
    try:
        os.makedirs(target, exist_ok=True)
        fd, probe = tempfile.mkstemp(prefix=".dowp_prueba_", dir=target)
        os.close(fd)
        os.remove(probe)
    except OSError as e:
        return False, QCoreApplication.translate("models_location", "No se puede escribir en esa carpeta: {0}").format(e)
    return True, ""


def free_space(path: str) -> int:
    probe = path
    while probe and not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    try:
        return shutil.disk_usage(probe).free
    except OSError:
        return 0


def _same_device(a: str, b: str) -> bool:
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False


class MoveCancelled(Exception):
    pass


def move_models(src: str, dst: str, progress_callback=None, cancel_event=None) -> tuple[bool, str]:
    """Mueve todo lo que hay en `src` a `dst` (fusionando carpetas).

    Mismo disco: se renombra, es instantáneo. Otro disco: se copia todo primero y
    solo al final se borra el origen; si se cancela o falla a medias, se borra lo
    copiado y el origen queda intacto (los modelos nunca quedan partidos entre dos
    sitios). Un archivo que ya existe en el destino con el mismo tamaño no se copia."""
    if not os.path.isdir(src):
        return True, ""
    os.makedirs(dst, exist_ok=True)
    files = []
    for root, _dirs, names in os.walk(src):
        for name in names:
            full = os.path.join(root, name)
            files.append((full, os.path.join(dst, os.path.relpath(full, src))))
    total = sum(os.path.getsize(f) for f, _ in files) or 1

    def report(done):
        if progress_callback:
            progress_callback(int(done * 100 / total))

    if _same_device(src, dst):
        done, moved = 0, []
        try:
            for s_path, d_path in files:
                if cancel_event and cancel_event.is_set():
                    raise MoveCancelled()
                os.makedirs(os.path.dirname(d_path), exist_ok=True)
                size = os.path.getsize(s_path)
                os.replace(s_path, d_path)
                moved.append((s_path, d_path))
                done += size
                report(done)
        except (MoveCancelled, OSError) as e:
            # Deshacer: los modelos nunca quedan repartidos entre dos carpetas
            for s_path, d_path in reversed(moved):
                try:
                    os.makedirs(os.path.dirname(s_path), exist_ok=True)
                    os.replace(d_path, s_path)
                except OSError:
                    pass
            _remove_empty_dirs(dst)
            if isinstance(e, MoveCancelled):
                return False, QCoreApplication.translate("models_location", "Cancelado. Los modelos siguen en la carpeta anterior.")
            logger.error(f"Modelos IA: fallo moviendo modelos a {dst}: {e}")
            return False, QCoreApplication.translate("models_location", "No se pudieron mover los modelos: {0}. Siguen en la carpeta anterior.").format(e)
        _remove_empty_dirs(src)
        return True, ""

    if free_space(dst) < total:
        return False, QCoreApplication.translate("models_location", "No hay espacio suficiente en el destino (hacen falta {0:.1f} GB).").format(total / 1e9)

    created = []
    done = 0
    try:
        for s_path, d_path in files:
            size = os.path.getsize(s_path)
            if os.path.exists(d_path) and os.path.getsize(d_path) == size:
                done += size
                report(done)
                continue
            os.makedirs(os.path.dirname(d_path), exist_ok=True)
            created.append(d_path)
            with open(s_path, "rb") as fin, open(d_path, "wb") as fout:
                while True:
                    if cancel_event and cancel_event.is_set():
                        raise MoveCancelled()
                    chunk = fin.read(8 * 1024 * 1024)
                    if not chunk:
                        break
                    fout.write(chunk)
                    done += len(chunk)
                    report(done)
            shutil.copystat(s_path, d_path)
    except (MoveCancelled, OSError) as e:
        for path in created:
            try:
                os.remove(path)
            except OSError:
                pass
        _remove_empty_dirs(dst)
        if isinstance(e, MoveCancelled):
            return False, QCoreApplication.translate("models_location", "Cancelado. Los modelos siguen en la carpeta anterior.")
        logger.error(f"Modelos IA: fallo moviendo modelos a {dst}: {e}")
        return False, QCoreApplication.translate("models_location", "No se pudieron copiar los modelos: {0}. Siguen en la carpeta anterior.").format(e)

    for s_path, _d in files:
        try:
            os.remove(s_path)
        except OSError as e:
            logger.warning(f"Modelos IA: no se pudo borrar {s_path} tras copiarlo: {e}")
    _remove_empty_dirs(src)
    return True, ""


def _remove_empty_dirs(path: str):
    for root, dirs, files in os.walk(path, topdown=False):
        if root == path:
            continue
        try:
            if not os.listdir(root):
                os.rmdir(root)
        except OSError:
            pass


def set_models_dir(path: str):
    """Guarda la carpeta elegida ("" = volver a la de siempre)."""
    from core.utils.config_manager import get_config, save_config
    cfg = get_config()
    default = get_default_models_dir()
    cfg["models_dir"] = "" if (not path or _norm(path) == _norm(default)) else os.path.abspath(path)
    save_config(cfg)
    logger.info(f"Modelos IA: carpeta de modelos -> {get_models_dir()}")
