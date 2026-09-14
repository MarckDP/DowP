# src/core/setup/models_setup.py
"""Descarga e instalación de modelos de IA (rembg, motores de upscaling NCNN-Vulkan).

A diferencia de las dependencias (ffmpeg, yt-dlp, etc., ver core/setup/ffmpeg_setup.py),
los modelos NUNCA se descargan solos al abrir la app -- solo cuando el usuario los pide
a mano, sea desde Ajustes > Modelos o desde los popovers del Editor de Imagen (ahí se
le pregunta primero, con el peso real por delante: ver
gui/widgets/model_download_prompt.py::confirm_model_download). Mismo patrón de
descarga que el resto de core/setup/*.py (requests streamed + callback de porcentaje,
sin checksum -- DowP 1 tampoco lo hacía)."""
import os
import re
import shutil
import sys
import tempfile
import zipfile
import requests
from core.constants import REMBG_MODEL_FAMILIES, UPSCAYL_LEGACY_MODEL_SOURCES
from core.logger.logger_manager import logger
from core.utils.paths import get_models_dir
from PySide6.QtCore import QCoreApplication


def _current_platform() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def _platform_value(value):
    """Resuelve un campo que puede ser un dict {"windows"/"macos"/"linux": ...} (motores
    de upscaling, un binario y una URL de release distintos por SO) o un string plano
    (modelos rembg: son .onnx, el mismo archivo sirve para los tres SO) -- devuelve
    directo el string, o None si el dict no tiene build para la plataforma actual."""
    if isinstance(value, dict):
        return value.get(_current_platform())
    return value


def _model_path(model_info: dict) -> str:
    return os.path.join(get_models_dir(), model_info["folder"], model_info["file"])


def is_rembg_model_installed(model_info: dict) -> bool:
    path = _model_path(model_info)
    return os.path.exists(path) and os.path.getsize(path) > 1024


def get_rembg_model_size_bytes(model_info: dict) -> int:
    """Peso real del .onnx a descargar, declarado en REMBG_MODEL_FAMILIES
    ("size_bytes", medido con un HEAD contra su URL). 0 si no se conoce -- caso de
    los modelos importados a mano, que ya están en disco y nunca se descargan."""
    return int(model_info.get("size_bytes") or 0)


def is_rembg_model_custom(model_info: dict) -> bool:
    """True para los .onnx que el usuario importó a mano.

    El discriminante es no tener URL: un modelo del catálogo (REMBG_MODEL_FAMILIES)
    siempre trae de dónde bajarse, y uno importado nunca —import_custom_rembg_model()
    lo guarda con url="" precisamente para marcarlo.

    Distinguirlos importa porque el resto de la interfaz da por hecho que "no está en
    disco" equivale a "se puede descargar", y para un importado eso es falso: no hay
    nada de donde bajarlo.
    """
    return not (model_info or {}).get("url")


def is_rembg_model_orphaned(model_info: dict) -> bool:
    """Modelo importado cuyo .onnx ya no está en disco porque el usuario lo borró por fuera.

    Su entrada sigue en config.json y hay que poder quitarla. Antes este caso se mostraba
    como "No descargado" con el botón de eliminar apagado, así que la entrada huérfana
    era imposible de eliminar desde la interfaz y el modelo se quedaba en la lista para
    siempre.
    """
    return is_rembg_model_custom(model_info) and not is_rembg_model_installed(model_info)


def is_rembg_model_gated(model_info: dict) -> bool:
    """True si la URL apunta a una página de HuggingFace (no a un archivo directo) --
    esos modelos necesitan descarga manual con cuenta, no se pueden bajar solos."""
    url = model_info.get("url", "")
    return "huggingface.co" in url and "/resolve/" not in url and "?download=" not in url


def download_rembg_model(model_info: dict, progress_callback=None) -> tuple[bool, str]:
    """Descarga un modelo rembg a bin/models/{folder}/{file}, con .part temporal y
    rename atómico al terminar (evita dejar un archivo corrupto a medias si se corta)."""
    part_path = None
    try:
        target_path = _model_path(model_info)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        part_path = target_path + ".part"

        logger.info(f"Descargando modelo rembg desde {model_info['url']}")
        r = requests.get(model_info["url"], stream=True, timeout=30)
        r.raise_for_status()

        total_size = int(r.headers.get("content-length", 0))
        downloaded = 0
        with open(part_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total_size > 0:
                        progress_callback(int((downloaded / total_size) * 100))

        if os.path.exists(target_path):
            os.remove(target_path)
        os.rename(part_path, target_path)

        if not is_rembg_model_installed(model_info):
            return False, QCoreApplication.translate("models_setup", "El archivo descargado quedó vacío o incompleto.")
        logger.info(f"Modelo rembg instalado en {target_path}")
        return True, QCoreApplication.translate("models_setup", "Modelo descargado correctamente.")
    except Exception as e:
        logger.error(f"Error descargando modelo rembg '{model_info.get('file')}': {e}")
        try:
            if part_path and os.path.exists(part_path):
                os.remove(part_path)
        except Exception:
            pass
        return False, str(e)


def delete_rembg_model(model_info: dict) -> bool:
    try:
        path = _model_path(model_info)
        if os.path.exists(path):
            os.remove(path)
        return True
    except Exception as e:
        logger.error(f"Error eliminando modelo rembg '{model_info.get('file')}': {e}")
        return False


# ═════════════════════════════════════════════════════════════════════════════
# MODELOS PERSONALIZADOS -- .onnx que el usuario importa a mano (Ajustes >
# Modelos > Importar modelo personalizado), para modelos que no vienen en el
# catálogo de REMBG_MODEL_FAMILIES (constants.py, parte del código fuente --
# no editable en runtime). Viven en su propia carpeta ("rembg_custom") y su
# propio registro en config.json, con la MISMA forma que una familia de
# REMBG_MODEL_FAMILIES ({nombre: {file, folder, input_size}}) -- así ni la UI
# (rembg_popover.py/models_page.py) ni el motor (rembg_engine.py) necesitan
# distinguir "modelo de catálogo" de "modelo importado", ver
# get_all_rembg_families() más abajo.
# ═════════════════════════════════════════════════════════════════════════════

CUSTOM_REMBG_FAMILY = "Personalizados (Importados)"
_CUSTOM_REMBG_FOLDER = "rembg_custom"
_CUSTOM_REMBG_CONFIG_KEY = "custom_rembg_models"


def get_custom_rembg_models() -> dict:
    """Modelos .onnx importados a mano, tal como quedaron guardados en config.json."""
    from core.utils.config_manager import get_config
    return dict(get_config().get(_CUSTOM_REMBG_CONFIG_KEY, {}))


def get_all_rembg_families() -> dict:
    """REMBG_MODEL_FAMILIES (catálogo fijo del código) + una familia sintética con
    los modelos importados, si hay alguno -- fuente única de verdad para listar
    familias/modelos en toda la app (UI y motor de inferencia)."""
    families = dict(REMBG_MODEL_FAMILIES)
    custom = get_custom_rembg_models()
    if custom:
        families[CUSTOM_REMBG_FAMILY] = custom
    return families


def probe_onnx_input_size(onnx_path: str) -> tuple[int, int] | None:
    """Intenta inferir el input_size (alto, ancho) leyendo la forma declarada del
    primer input del grafo -- best-effort: si el modelo tiene ejes dinámicos
    (dimensión simbólica en vez de un entero fijo, común en arquitecturas con
    atención deformable como RMBG 2.0) no hay nada concreto que leer, devuelve
    None y el usuario completa el tamaño a mano en el diálogo de importación."""
    try:
        import onnxruntime as ort
        session = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
        shape = session.get_inputs()[0].shape
        # Las dos dimensiones espaciales (alto/ancho) son, en cualquier layout
        # (NCHW o NHWC), las dos más grandes entre los ejes con valor entero fijo
        # -- batch es 1, canales es 1/3/4, alto/ancho de un modelo de segmentación
        # típico son >= 224.
        spatial = sorted((d for d in shape if isinstance(d, int) and d > 4), reverse=True)
        if len(spatial) >= 2:
            return spatial[0], spatial[1]
        return None
    except Exception as e:
        logger.debug(f"Modelos IA: no se pudo sondear input_size de '{onnx_path}': {e}")
        return None


def _safe_filename(name: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or "modelo"
    if not base.lower().endswith(".onnx"):
        base += ".onnx"
    return base


def import_custom_rembg_model(display_name: str, source_path: str, input_size: tuple[int, int]) -> tuple[bool, str]:
    """Copia un .onnx externo a bin/models/rembg_custom/ y lo registra en
    config.json bajo CUSTOM_REMBG_FAMILY -- a partir de aquí se comporta como
    cualquier otro modelo del catálogo (aparece en el popover de Eliminar Fondo,
    lo puede usar rembg_engine.py, se puede borrar desde Ajustes > Modelos)."""
    from core.utils.config_manager import get_config, save_config

    display_name = (display_name or "").strip()
    if not display_name:
        return False, QCoreApplication.translate("models_setup", "El modelo necesita un nombre.")
    if not source_path or not os.path.isfile(source_path):
        return False, QCoreApplication.translate("models_setup", "No se encontró el archivo: {0}").format(source_path)
    if not source_path.lower().endswith(".onnx"):
        return False, QCoreApplication.translate("models_setup", "El archivo elegido no es un .onnx.")

    target_dir = os.path.join(get_models_dir(), _CUSTOM_REMBG_FOLDER)
    os.makedirs(target_dir, exist_ok=True)

    filename = _safe_filename(os.path.splitext(os.path.basename(source_path))[0])
    target_path = os.path.join(target_dir, filename)
    # Evita pisar un archivo ya importado con otro nombre visible -- suma un
    # sufijo numérico hasta encontrar uno libre, mismo criterio simple que usa
    # file_conflict_manager para archivos de salida.
    stem, ext = os.path.splitext(filename)
    counter = 1
    while os.path.exists(target_path) and os.path.abspath(target_path) != os.path.abspath(source_path):
        filename = f"{stem}_{counter}{ext}"
        target_path = os.path.join(target_dir, filename)
        counter += 1

    try:
        if os.path.abspath(target_path) != os.path.abspath(source_path):
            shutil.copy2(source_path, target_path)
    except Exception as e:
        logger.error(f"Modelos IA: no se pudo copiar el modelo personalizado: {e}")
        return False, QCoreApplication.translate("models_setup", "No se pudo copiar el archivo: {0}").format(e)

    height, width = input_size
    cfg = get_config()
    custom = dict(cfg.get(_CUSTOM_REMBG_CONFIG_KEY, {}))
    custom[display_name] = {
        "file": filename,
        "folder": _CUSTOM_REMBG_FOLDER,
        "input_size": (height, width),
        "url": "",  # importado a mano -- nunca se descarga solo, no aplica get_install_info/gated.
    }
    cfg[_CUSTOM_REMBG_CONFIG_KEY] = custom
    save_config(cfg)
    logger.info(f"Modelos IA: modelo personalizado importado '{display_name}' ({filename}, input_size={input_size})")
    return True, QCoreApplication.translate("models_setup", "Modelo importado correctamente.")


def delete_custom_rembg_model(display_name: str) -> bool:
    """Borra el archivo y la entrada del registro de un modelo importado."""
    from core.utils.config_manager import get_config, save_config

    cfg = get_config()
    custom = dict(cfg.get(_CUSTOM_REMBG_CONFIG_KEY, {}))
    model_info = custom.pop(display_name, None)
    if model_info is None:
        return False

    try:
        path = _model_path(model_info)
        if os.path.exists(path):
            os.remove(path)
    except Exception as e:
        logger.error(f"Modelos IA: no se pudo borrar el archivo de '{display_name}': {e}")
        return False

    cfg[_CUSTOM_REMBG_CONFIG_KEY] = custom
    save_config(cfg)
    logger.info(f"Modelos IA: modelo personalizado eliminado '{display_name}'")
    return True


def _engine_dir(tool_info: dict) -> str:
    return os.path.join(get_models_dir(), tool_info["folder"])


def get_engine_exe_path(tool_info: dict) -> str | None:
    """Ruta completa al ejecutable del motor para la plataforma actual, o None si
    ese motor no tiene build para este SO (ver _platform_value) -- usada tanto para
    chequear instalación aquí como para invocarlo de verdad desde
    core/tabs/image_tools/upscale_engine.py."""
    exe_name = _platform_value(tool_info["exe"])
    if not exe_name:
        return None
    return os.path.join(_engine_dir(tool_info), exe_name)


def is_upscaling_engine_installed(tool_info: dict) -> bool:
    exe_path = get_engine_exe_path(tool_info)
    return exe_path is not None and os.path.exists(exe_path)


def get_upscaling_engine_size_bytes(tool_info: dict) -> int:
    """Peso real de TODO lo que baja download_upscaling_engine() para este motor en
    este SO: el zip del binario + (si lo tiene) el zip de modelos + los modelos
    legacy de Upscayl. Los legacy que ya están en disco no se suman -- se saltan en
    la descarga por su archivo canario, así que sumarlos exageraría el número que
    ve el usuario en el diálogo."""
    total = int(_platform_value(tool_info.get("size_bytes")) or 0)
    total += int(tool_info.get("models_size_bytes") or 0)
    if tool_info.get("folder") == "upscayl":
        models_dir = os.path.join(_engine_dir(tool_info), "models")
        for _name, _url, canary, size in UPSCAYL_LEGACY_MODEL_SOURCES:
            if not os.path.exists(os.path.join(models_dir, canary)):
                total += size
    return total


def _download_and_extract_zip(url: str, dest_dir: str, progress_callback=None, weight=(0, 100)):
    """Descarga un zip a un temporal, lo extrae, y fusiona su contenido en dest_dir --
    si el zip trae todo envuelto en una única subcarpeta (patrón común de releases de
    GitHub), fusiona esa subcarpeta directo en vez de crear un nivel de anidación extra."""
    start_pct, end_pct = weight
    span = end_pct - start_pct

    with tempfile.TemporaryDirectory() as tmp_dir:
        temp_zip = os.path.join(tmp_dir, "download.zip")
        r = requests.get(url, stream=True, timeout=30)
        r.raise_for_status()
        total_size = int(r.headers.get("content-length", 0))
        downloaded = 0
        with open(temp_zip, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total_size > 0:
                        pct = start_pct + int((downloaded / total_size) * span)
                        progress_callback(pct)

        extract_dir = os.path.join(tmp_dir, "extracted")
        with zipfile.ZipFile(temp_zip, "r") as zip_ref:
            zip_ref.extractall(extract_dir)

        # Si todo el contenido quedó envuelto en una única subcarpeta, fusionar esa
        # subcarpeta directo en vez de duplicar el nivel de anidación.
        entries = os.listdir(extract_dir)
        source_dir = extract_dir
        if len(entries) == 1 and os.path.isdir(os.path.join(extract_dir, entries[0])):
            source_dir = os.path.join(extract_dir, entries[0])

        os.makedirs(dest_dir, exist_ok=True)
        try:
            shutil.copytree(source_dir, dest_dir, dirs_exist_ok=True)
        except Exception as e:
            logger.warning(f"copytree falló fusionando en {dest_dir} ({e}), reintentando con rmtree+move")
            if os.path.exists(dest_dir):
                shutil.rmtree(dest_dir)
            shutil.move(source_dir, dest_dir)


# Upscayl es deliberadamente "más global" que el repo custom-models solo -- estos 2
# releases oficiales (Real-ESRGAN/RealSR, ver UPSCAYL_LEGACY_MODEL_SOURCES en
# core/constants.py) aportan modelos que custom-models no tiene. Un solo URL por
# fuente alcanza para los 3 SO: los .bin/.param son datos de pesos, idénticos sin
# importar qué build (windows/macos/ubuntu) del binario los acompañe -- confirmado
# contra el árbol real de ambos releases en GitHub, así que no hace falta
# _platform_value() ahí, a diferencia de UPSCALING_TOOLS (que sí baja un ejecutable
# real por SO).

# Ver sanitize_upscayl_models() en el setup.pyc decompilado de DowP1: purga estos 2
# modelos por inestabilidad conocida (no se ofrecen ni en UPSCAYL_MODELS_MAP ni aquí).
_UPSCAYL_UNSTABLE_MODELS = ("realesr-animevideov3-x2", "realesr-animevideov3-x3")


def _sanitize_upscayl_models(models_dir: str):
    """Purga modelos conocidos por causar errores/inestabilidad -- mismo criterio que
    sanitize_upscayl_models() en DowP1."""
    if not os.path.isdir(models_dir):
        return
    for name in _UPSCAYL_UNSTABLE_MODELS:
        for ext in (".bin", ".param"):
            path = os.path.join(models_dir, name + ext)
            if os.path.exists(path):
                try:
                    os.remove(path)
                    logger.info(f"Upscayl: modelo purgado por inestabilidad -- {name}{ext}")
                except OSError as e:
                    logger.warning(f"Upscayl: no se pudo purgar {name}{ext}: {e}")


def _download_upscayl_legacy_models(models_dir: str, progress_callback=None):
    """Descarga los modelos de Real-ESRGAN/RealSR que NO vienen en custom-models --
    mismo criterio que DowP1 (canario: si el archivo ya está, se salta la descarga
    completa, evita re-bajar ~60-80MB en cada instalación). Se filtran solo .bin/
    .param del zip completo (que también trae el ejecutable/LICENSE/README de ese
    proyecto, irrelevantes aquí)."""
    os.makedirs(models_dir, exist_ok=True)
    for name, url, canary, _size in UPSCAYL_LEGACY_MODEL_SOURCES:
        if os.path.exists(os.path.join(models_dir, canary)):
            logger.info(f"Upscayl: modelos de {name} ya presentes, se omite su descarga.")
            continue
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                extract_dir = os.path.join(tmp_dir, "extracted")
                logger.info(f"Upscayl: descargando modelos legacy de {name} desde {url}")
                _download_and_extract_zip(url, extract_dir, progress_callback)
                for root, _dirs, files in os.walk(extract_dir):
                    for fname in files:
                        if not fname.endswith((".bin", ".param")):
                            continue
                        dst_name = fname
                        parent_name = os.path.basename(root)
                        # El zip de RealSR trae sub-modelos nombrados genéricamente
                        # "x4.bin"/"x4.param" dentro de subcarpetas "models-DF2K"/
                        # "models-DF2K_JPEG" -- sin prefijo se pisarían entre sí, así
                        # que se renombran igual que hacía DowP1 (nombre de la
                        # subcarpeta sin el prefijo "models-" + "_" + nombre original).
                        if fname.startswith("x4") and parent_name.startswith("models-"):
                            dst_name = f"{parent_name[len('models-'):]}_{fname}"
                        dst_path = os.path.join(models_dir, dst_name)
                        if not os.path.exists(dst_path):
                            shutil.copy2(os.path.join(root, fname), dst_path)
        except Exception as e:
            logger.warning(f"Upscayl: no se pudieron descargar los modelos legacy de {name}: {e}")
    _sanitize_upscayl_models(models_dir)


def download_upscaling_engine(tool_info: dict, progress_callback=None) -> tuple[bool, str]:
    """Descarga e instala un motor de upscaling NCNN-Vulkan completo (ejecutable +
    modelos que trae el propio zip) en bin/models/{folder}. Si el motor además define
    `models_url` (ej. Upscayl), descarga ese zip de modelos aparte, directo en
    {folder}/ -- NO en {folder}/models/: el repo custom-models de Upscayl ya trae su
    propia carpeta "models/" adentro (una vez desenvuelto el wrapper de GitHub
    Archive, ver _download_and_extract_zip), así que fusionarlo en {folder}/models/
    duplicaba el nivel y dejaba los .param en {folder}/models/models/ -- confirmado
    con una descarga real (ver upscale_engine.py, que espera {folder}/models/*.param
    directo). El release de GitHub trae un .zip distinto por SO (windows/macos/
    linux) -- ver _platform_value()."""
    try:
        url = _platform_value(tool_info["url"])
        if not url:
            return False, QCoreApplication.translate("models_setup", "'{0}' no tiene una build disponible para este sistema operativo.").format(tool_info["name"])

        dest_dir = _engine_dir(tool_info)
        has_models_zip = bool(tool_info.get("models_url"))
        is_upscayl = tool_info.get("folder") == "upscayl"
        engine_weight = (0, 40) if has_models_zip else (0, 100)

        logger.info(f"Descargando motor de upscaling '{tool_info['name']}' desde {url}")
        _download_and_extract_zip(url, dest_dir, progress_callback, weight=engine_weight)

        if has_models_zip:
            logger.info(f"Descargando modelos de '{tool_info['name']}' desde {tool_info['models_url']}")
            _download_and_extract_zip(tool_info["models_url"], dest_dir, progress_callback,
                                       weight=(40, 70) if is_upscayl else (40, 100))

        if is_upscayl:
            _download_upscayl_legacy_models(os.path.join(dest_dir, "models"), progress_callback)

        if not is_upscaling_engine_installed(tool_info):
            return False, QCoreApplication.translate("models_setup", "No se encontró {0} tras la instalación.").format(_platform_value(tool_info["exe"]))

        if _current_platform() != "windows":
            # Los binarios de macOS/Linux necesitan el bit +x -- zipfile no siempre
            # preserva los permisos unix del zip al extraer, así que se fuerza aquí
            # en vez de depender de eso.
            exe_path = os.path.join(dest_dir, _platform_value(tool_info["exe"]))
            os.chmod(exe_path, 0o755)

        logger.info(f"Motor '{tool_info['name']}' instalado en {dest_dir}")
        return True, QCoreApplication.translate("models_setup", "Motor instalado correctamente.")
    except Exception as e:
        logger.error(f"Error instalando motor de upscaling '{tool_info.get('name')}': {e}")
        return False, str(e)


def delete_upscaling_engine(tool_info: dict) -> bool:
    try:
        dest_dir = _engine_dir(tool_info)
        if os.path.exists(dest_dir):
            shutil.rmtree(dest_dir)
        return True
    except Exception as e:
        logger.error(f"Error eliminando motor de upscaling '{tool_info.get('name')}': {e}")
        return False


def get_folder_size(path: str) -> int:
    """Suma recursiva del tamaño en disco de un archivo o carpeta (0 si no existe)."""
    if not os.path.exists(path):
        return 0
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for root, _dirs, files in os.walk(path):
        for fname in files:
            try:
                total += os.path.getsize(os.path.join(root, fname))
            except OSError:
                pass
    return total
