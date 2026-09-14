# src/core/setup/wpc_setup.py
"""
Módulo de configuración para yt-dlp-getpot-wpc (WebPoClient PO Token Provider).

WPC no se instala vía pip: se descarga como wheel (.whl) desde GitHub Releases
y se descomprime como archivo suelto en bin/dependences/ytdlp/plugins/, en la
misma carpeta que bgutil. Esto es necesario porque el .exe compilado con
PyInstaller no tiene pip disponible en runtime.

nodriver y su cadena de dependencias (mss, wrapt, deprecated, websockets)
tampoco se instalan vía pip: se descargan desde PyPI y se descomprimen en esa
misma carpeta, que siempre se agrega a sys.path antes de importar yt_dlp. Como
son paquetes que funcionan en modo 100% Python (algunos, como wrapt o
websockets, tienen una extensión C opcional que se ignora a propósito — caen
solos a su fallback puro-Python si esa extensión no está presente), el import
funciona igual en modo fuente y en el .exe congelado sin necesitar que
PyInstaller los empaquete ni que haya un compilador disponible.

La mayoría se descargan como wheel universal (py3-none-any). websockets no
publica una — solo wheels compiladas por plataforma — así que se descarga su
sdist (.tar.gz) y se extrae únicamente el paquete .py puro que contiene.

Las versiones de nodriver/mss/deprecated están ancladas (no se auto-actualizan)
porque son dependencias de implementación, no el producto en sí — evita que un
cambio upstream de nodriver rompa WPC sin aviso. yt-dlp-getpot-wpc declara en
su propio wheel el nodriver exacto que espera (Requires-Dist: nodriver==X.Y.Z);
en cada instalación se compara ese pin contra el nuestro y se avisa por log si
difieren, para saber cuándo hay que subir NODRIVER_VERSION manualmente.

Extractor arg en yt-dlp (cuando WPC está activo):
    ydl_opts['extractor_args']['youtubepot-wpc'] = {'browser_path': ['/path/to/browser']}
"""
import io
import os
import re
import shutil
import platform
import tarfile
import zipfile
import requests
from core.logger.logger_manager import logger
from core.setup.potprovider_setup import get_plugin_dir
from PySide6.QtCore import QCoreApplication

WPC_API_URL = "https://api.github.com/repos/coletdjnz/yt-dlp-getpot-wpc/releases/latest"
WPC_PLUGIN_SENTINEL = os.path.join("yt_dlp_plugins", "extractor", "getpot_wpc.py")

# ─── Dependencias ancladas de nodriver ──────────────────────────────────────
# Si actualizas WPC y los logs avisan de un mismatch con estos pines
# (WPC declara Requires-Dist: nodriver==X en su wheel), súbelos aquí a mano.
NODRIVER_VERSION = "0.50.3"
MSS_VERSION = "10.2.0"
WRAPT_VERSION = "2.3.0"       # dependencia transitiva de 'deprecated'
DEPRECATED_VERSION = "1.3.1"
WEBSOCKETS_VERSION = "16.1"   # dependencia transitiva de 'nodriver' (requiere >=14)

# kind="wheel"      -> se descarga la wheel universal (py3-none-any) de PyPI.
# kind="sdist_pure" -> el paquete no publica wheel universal (solo compiladas
#                       por plataforma); se descarga el sdist y se extrae solo
#                       el código .py, que funciona vía su fallback puro-Python.
PINNED_DEPS = [
    {"pypi_name": "nodriver",    "import_name": "nodriver",    "version": NODRIVER_VERSION,    "kind": "wheel"},
    {"pypi_name": "mss",         "import_name": "mss",         "version": MSS_VERSION,         "kind": "wheel"},
    {"pypi_name": "wrapt",       "import_name": "wrapt",       "version": WRAPT_VERSION,       "kind": "wheel"},
    {"pypi_name": "Deprecated",  "import_name": "deprecated",  "version": DEPRECATED_VERSION,  "kind": "wheel"},
    {"pypi_name": "websockets",  "import_name": "websockets",  "version": WEBSOCKETS_VERSION,  "kind": "sdist_pure"},
]


# ─── Detección ────────────────────────────────────────────────────────────────

def _check_plugin_sentinel(plugin_dir: str) -> bool:
    return os.path.exists(os.path.join(plugin_dir, WPC_PLUGIN_SENTINEL))


def _dep_installed(plugin_dir: str, import_name: str) -> bool:
    return os.path.isdir(os.path.join(plugin_dir, import_name))


def check_wpc() -> bool:
    """Verifica que el plugin WPC y todas sus dependencias ancladas estén presentes."""
    plugin_dir = get_plugin_dir()
    if not _check_plugin_sentinel(plugin_dir):
        return False
    return all(_dep_installed(plugin_dir, dep["import_name"]) for dep in PINNED_DEPS)


def get_local_version(force_check: bool = False) -> str | None:
    """
    Devuelve la versión instalada de WPC, leída directamente de la carpeta
    dist-info que quedó de descomprimir su wheel (no depende de pip ni de config.json).
    """
    if not check_wpc():
        return None
    plugin_dir = get_plugin_dir()
    try:
        for name in os.listdir(plugin_dir):
            m = re.match(r"yt_dlp_getpot_wpc-([\d.]+)\.dist-info$", name)
            if m:
                return m.group(1)
    except Exception as e:
        logger.debug(f"WPC: Error leyendo versión local: {e}")
    return None


def get_latest_remote_version() -> str | None:
    """Consulta la API de GitHub para obtener la última versión disponible de WPC."""
    try:
        response = requests.get(WPC_API_URL, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("tag_name", "").lstrip("v")
    except Exception as e:
        logger.debug(f"WPC: Error obteniendo versión remota de GitHub: {e}")
        return None


# ─── Instalación ──────────────────────────────────────────────────────────────

def _download_and_extract_wheel(url: str, dest_dir: str) -> None:
    """Descarga una wheel (.whl) en memoria y la descomprime (es un ZIP) en dest_dir."""
    r = requests.get(url, stream=True, timeout=60)
    r.raise_for_status()
    buf = io.BytesIO()
    for chunk in r.iter_content(chunk_size=8192):
        if chunk:
            buf.write(chunk)
    buf.seek(0)
    with zipfile.ZipFile(buf) as zf:
        zf.extractall(dest_dir)


def _is_universal_wheel(filename: str) -> bool:
    """
    Verifica si un nombre de wheel es universal (abi=none, plataforma=any y
    compatible con Python 3), leyendo sus tags según el formato del wheel:
    {name}-{version}(-{build})?-{python_tag}-{abi_tag}-{platform_tag}.whl

    No basta con comparar un sufijo fijo tipo "-py3-none-any.whl": paquetes
    como 'Deprecated' publican tags "legacy" como "py2.py3-none-any.whl"
    (compatibles con Python 2 y 3 a la vez), que también son universales
    mono-plataforma pero no terminan exactamente en "-py3-none-any.whl".
    """
    if not filename.endswith(".whl"):
        return False
    parts = filename[:-len(".whl")].split("-")
    if len(parts) < 3:
        return False
    python_tag, abi_tag, platform_tag = parts[-3], parts[-2], parts[-1]
    return (
        abi_tag == "none"
        and platform_tag == "any"
        and "py3" in python_tag.split(".")
    )


def _get_pinned_wheel_url(pypi_name: str, version: str) -> str | None:
    """
    Consulta PyPI para la URL de la wheel *universal* de una versión exacta de
    un paquete. Paquetes con extensión C (p.ej. wrapt) publican además decenas
    de wheels por plataforma/versión de Python — se ignoran a propósito,
    porque este flujo debe funcionar igual en Windows/Mac/Linux y en el .exe
    congelado, sin compilar nada.
    """
    try:
        resp = requests.get(f"https://pypi.org/pypi/{pypi_name}/{version}/json", timeout=15)
        resp.raise_for_status()
        data = resp.json()
        for url_info in data.get("urls", []):
            filename = url_info.get("filename", "")
            if url_info.get("packagetype") == "bdist_wheel" and _is_universal_wheel(filename):
                return url_info.get("url")
        logger.error(f"WPC: {pypi_name}=={version} no tiene wheel universal en PyPI.")
    except Exception as e:
        logger.error(f"WPC: Error consultando PyPI para {pypi_name}=={version}: {e}")
    return None


def _get_pinned_sdist_url(pypi_name: str, version: str) -> str | None:
    """Consulta PyPI para la URL del sdist (.tar.gz) de una versión exacta de un paquete."""
    try:
        resp = requests.get(f"https://pypi.org/pypi/{pypi_name}/{version}/json", timeout=15)
        resp.raise_for_status()
        data = resp.json()
        for url_info in data.get("urls", []):
            if url_info.get("packagetype") == "sdist":
                return url_info.get("url")
        logger.error(f"WPC: {pypi_name}=={version} no tiene sdist en PyPI.")
    except Exception as e:
        logger.error(f"WPC: Error consultando PyPI para {pypi_name}=={version}: {e}")
    return None


def _download_and_extract_sdist_package(url: str, dest_dir: str, import_name: str) -> None:
    """
    Descarga un sdist (.tar.gz) y extrae únicamente el paquete <import_name>/
    que contiene (sin importar si está anidado en un layout 'src/' u otro),
    ignorando fuentes de extensiones C (.c/.pyx) que no hacen falta porque el
    paquete cae a su fallback puro-Python si esa extensión no está compilada.
    """
    r = requests.get(url, stream=True, timeout=60)
    r.raise_for_status()
    buf = io.BytesIO()
    for chunk in r.iter_content(chunk_size=8192):
        if chunk:
            buf.write(chunk)
    buf.seek(0)

    with tarfile.open(fileobj=buf, mode="r:gz") as tf:
        marker = f"/{import_name}/__init__.py"
        root_member = next(
            (m for m in tf.getmembers()
             if m.name.endswith(marker) or m.name == f"{import_name}/__init__.py"),
            None
        )
        if root_member is None:
            raise RuntimeError(QCoreApplication.translate("wpc_setup", "No se encontró {0}/__init__.py dentro del sdist descargado.").format(import_name))

        prefix = root_member.name[:-len("__init__.py")]  # ".../<import_name>/"
        target_root = os.path.normpath(os.path.join(dest_dir, import_name))

        for member in tf.getmembers():
            if not member.isfile() or not member.name.startswith(prefix):
                continue
            if member.name.endswith((".c", ".pyx", ".pyi")):
                continue

            rel_path = member.name[len(prefix):]
            dest_path = os.path.normpath(os.path.join(target_root, rel_path))
            if not (dest_path == target_root or dest_path.startswith(target_root + os.sep)):
                continue  # ruta sospechosa fuera de target_root, se ignora

            extracted = tf.extractfile(member)
            if extracted is None:
                continue
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with open(dest_path, "wb") as f:
                f.write(extracted.read())


def _verify_nodriver_pin(plugin_dir: str) -> None:
    """
    Compara el nodriver que este release de WPC declara necesitar (Requires-Dist
    en su propio METADATA) contra el pin fijado en NODRIVER_VERSION, y avisa por
    log si difieren. No falla la instalación: es solo una alerta para el desarrollador.
    """
    try:
        dist_info_dirs = [
            d for d in os.listdir(plugin_dir)
            if re.match(r"yt_dlp_getpot_wpc-.+\.dist-info$", d)
        ]
        if not dist_info_dirs:
            return
        metadata_path = os.path.join(plugin_dir, dist_info_dirs[0], "METADATA")
        if not os.path.exists(metadata_path):
            return
        with open(metadata_path, "r", encoding="utf-8") as f:
            for line in f:
                m = re.match(r"Requires-Dist:\s*nodriver\s*==\s*([\d.]+)", line.strip())
                if m:
                    required = m.group(1)
                    if required != NODRIVER_VERSION:
                        logger.warning(
                            f"WPC: esta versión de WPC requiere nodriver=={required}, pero el "
                            f"pin actual en wpc_setup.py (NODRIVER_VERSION) es {NODRIVER_VERSION}. "
                            f"Actualiza el pin para evitar incompatibilidades."
                        )
                    else:
                        logger.debug(f"WPC: pin de nodriver verificado, coincide ({required}).")
                    return
    except Exception as e:
        logger.debug(f"WPC: no se pudo verificar el pin de nodriver declarado por WPC: {e}")


def install_wpc(progress_callback=None) -> tuple:
    """
    Descarga e instala WPC (plugin) + nodriver/mss/deprecated (dependencias ancladas)
    como archivos sueltos en bin/dependences/ytdlp/plugins/.
    Devuelve (success: bool, message: str).
    """
    plugin_dir = get_plugin_dir()
    logger.info(f"WPC: instalando en {plugin_dir}...")

    try:
        if progress_callback:
            progress_callback(5)

        # ── Paso 1: plugin WPC desde GitHub Releases ──
        logger.info(f"WPC: consultando release desde {WPC_API_URL}")
        response = requests.get(WPC_API_URL, timeout=15)
        response.raise_for_status()
        data = response.json()

        wheel_url = next(
            (a["browser_download_url"] for a in data.get("assets", []) if a["name"].endswith(".whl")),
            None
        )
        if not wheel_url:
            logger.error("WPC: no se encontró un asset .whl en el último release")
            return False, QCoreApplication.translate("wpc_setup", "No se encontró el archivo .whl de WPC en el último release.")

        logger.info(f"WPC: descargando plugin desde {wheel_url}")
        _download_and_extract_wheel(wheel_url, plugin_dir)

        if not _check_plugin_sentinel(plugin_dir):
            return False, QCoreApplication.translate("wpc_setup", "El plugin de WPC no se encontró tras la extracción.")

        if progress_callback:
            progress_callback(30)

        _verify_nodriver_pin(plugin_dir)

        # ── Paso 2: dependencias ancladas (nodriver y su cadena transitiva) desde PyPI ──
        total = len(PINNED_DEPS)
        for i, dep in enumerate(PINNED_DEPS):
            pypi_name, import_name, version, kind = dep["pypi_name"], dep["import_name"], dep["version"], dep["kind"]

            if _dep_installed(plugin_dir, import_name):
                logger.debug(f"WPC: {import_name} ya presente, se omite descarga.")
            elif kind == "wheel":
                dep_url = _get_pinned_wheel_url(pypi_name, version)
                if not dep_url:
                    return False, QCoreApplication.translate("wpc_setup", "No se encontró la wheel de {0}=={1} en PyPI.").format(pypi_name, version)
                logger.info(f"WPC: descargando {pypi_name}=={version} (wheel) desde {dep_url}")
                _download_and_extract_wheel(dep_url, plugin_dir)
            else:  # "sdist_pure"
                dep_url = _get_pinned_sdist_url(pypi_name, version)
                if not dep_url:
                    return False, QCoreApplication.translate("wpc_setup", "No se encontró el sdist de {0}=={1} en PyPI.").format(pypi_name, version)
                logger.info(f"WPC: descargando {pypi_name}=={version} (sdist) desde {dep_url}")
                _download_and_extract_sdist_package(dep_url, plugin_dir, import_name)

            if progress_callback:
                progress_callback(30 + int(((i + 1) / total) * 65))

        if not check_wpc():
            return False, QCoreApplication.translate("wpc_setup", "Faltan dependencias de WPC tras la instalación.")

        version = get_local_version()
        msg = f"WPC instalado correctamente: v{version}" if version else "WPC instalado correctamente"
        logger.info(f"WPC: {msg}")
        if progress_callback:
            progress_callback(100)
        return True, msg

    except Exception as e:
        logger.error(f"WPC: excepción instalando: {e}")
        return False, str(e)


# ─── Navegador ────────────────────────────────────────────────────────────────

def _build_search_paths():
    """Construye las rutas de búsqueda según el SO actual."""
    return {
        "Windows": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Chromium\Application\chrome.exe",
        ],
        "Darwin": [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ],
        "Linux": [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/usr/bin/brave-browser",
            "/usr/bin/microsoft-edge",
            "/snap/bin/chromium",
        ]
    }


_NAME_MAP = {
    "chrome": "Google Chrome",
    "brave": "Brave",
    "msedge": "Microsoft Edge",
    "chromium": "Chromium",
    "edge": "Microsoft Edge",
}


def detect_system_browser():
    """
    Auto-detecta el primer navegador Chromium disponible en el sistema.
    Devuelve (path, nombre_amigable) o (None, None) si no se encuentra.
    """
    plat = platform.system()
    search_paths = _build_search_paths()
    paths = search_paths.get(plat, [])

    for path in paths:
        if path and os.path.isfile(path):
            exe_lower = os.path.basename(path).lower()
            name = next((v for k, v in _NAME_MAP.items() if k in exe_lower), "Chromium")
            logger.debug(f"WPC: Navegador detectado → {name} ({path})")
            return path, name

    # Fallback: buscar en PATH del sistema
    for cmd in ("google-chrome", "chromium", "chromium-browser", "brave-browser", "microsoft-edge"):
        found = shutil.which(cmd)
        if found:
            name = next((v for k, v in _NAME_MAP.items() if k in cmd), "Chromium")
            logger.debug(f"WPC: Navegador en PATH → {name} ({found})")
            return found, name

    return None, None


def get_browser_path() -> str:
    """
    Devuelve la ruta del navegador a usar con WPC.
    Prioridad: config.json → auto-detect → '' (vacío = nodriver decide)
    """
    from core.utils.config_manager import get_config
    configured = get_config().get("pot_wpc_browser_path", "").strip()
    if configured and os.path.isfile(configured):
        return configured
    path, _ = detect_system_browser()
    return path or ""


def get_browser_display_name() -> str:
    """Devuelve el nombre amigable del navegador que se usaría con WPC."""
    from core.utils.config_manager import get_config
    configured = get_config().get("pot_wpc_browser_path", "").strip()
    if configured and os.path.isfile(configured):
        exe = os.path.basename(configured).lower()
        return next((v for k, v in _NAME_MAP.items() if k in exe), os.path.basename(configured))
    _, name = detect_system_browser()
    return name or "No detectado"
