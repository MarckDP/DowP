"""
Script de compilación multiplataforma para DowP 2.0 (Windows / macOS / Linux).

Compila para el sistema operativo actual usando PyInstaller en modo --onedir:
genera un .exe en Windows, un .app en macOS y un binario en Linux.

Uso:
    python build_cross_platform.py
"""
import os
import sys
import platform
import subprocess

import PyInstaller.__main__

APP_NAME = "DowP"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MAIN_SCRIPT = os.path.join(SCRIPT_DIR, "main.py")
HELPER_SCRIPT = os.path.join(SCRIPT_DIR, "updater_helper.py")
SRC_DIR = os.path.join(SCRIPT_DIR, "src")
# El importer es hermano de app/, no hijo: <repo>/importer
IMPORTER_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "importer")

# Firma ad-hoc de macOS consolidada en core/updater/ (la necesita tambien el
# helper de swap para volver a firmar el bundle tras aplicar una actualizacion).
sys.path.insert(0, SRC_DIR)
from core.updater.macos_sign import SigningError, adhoc_sign  # noqa: E402


def read_app_version():
    """Lee APP_VERSION de src/core/version.py sin importar el paquete entero (esto
    corre antes de que exista nada del entorno de la app). version.py no tiene imports
    a proposito, justamente para poder ejecutarlo aislado desde aqui."""
    version_file = os.path.join(SRC_DIR, "core", "version.py")
    namespace = {}
    with open(version_file, encoding="utf-8") as f:
        exec(compile(f.read(), version_file, "exec"), namespace)
    return namespace["APP_VERSION"]


def stamp_importer_version(version):
    """Reescribe el numero de version dentro del DowP Importer para que coincida con el
    de la app.

    La app y el panel comparten version porque el panel se instala DESDE la app y viaja
    dentro de su bundle: no tiene ciclo de publicacion propio. Estampar aqui en vez de
    editar a mano es lo que garantiza que no vuelvan a divergir, que es como acabaron
    en 2.0.0 y 1.3.0 respectivamente.

    Si algo no se puede estampar aborta el build: preferible eso a publicar un panel
    que reporta una version que no es la suya, porque la deteccion de "panel viejo"
    de importer_setup.py se basa en comparar exactamente esa cadena.
    """
    import re

    targets = [
        (os.path.join(IMPORTER_DIR, "CSXS", "manifest.xml"),
         [(r'(ExtensionBundleVersion=")[^"]*(")', 1),
          (r'(<Extension Id="com\.dowp\.importer" Version=")[^"]*(")', 1)]),
        (os.path.join(IMPORTER_DIR, "js", "main.js"),
         [(r'(const CURRENT_EXTENSION_VERSION\s*=\s*")[^"]*(")', 1)]),
    ]

    for path, patterns in targets:
        if not os.path.exists(path):
            print(f"ERROR: no se encontro {path} para estampar la version")
            sys.exit(1)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        for pattern, expected in patterns:
            content, count = re.subn(pattern, r"\g<1>" + version + r"\g<2>", content)
            if count != expected:
                print(f"ERROR: {path}: el patron {pattern!r} coincidio {count} veces, se esperaban {expected}")
                sys.exit(1)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
    print(f"DowP Importer estampado a v{version}")


def prune_bundle(dist_root):
    """Quita del bundle YA CONSTRUIDO los __pycache__ que arrastra --add-data.

    El --add-data de src/ copia la carpeta entera, y con ella 182 archivos .pyc que no
    sirven de nada: el bytecode que la app ejecuta de verdad es el del PYZ embebido en
    el ejecutable, no estos. Son 4,2 MB de peso muerto.

    Ademas ensucian el updater: cada .pyc cambia cuando cambia su .py, asi que el
    manifiesto de actualizacion se llenaria de archivos que nadie usa.

    Actua sobre dist/, NO sobre el arbol de fuentes: borrar los __pycache__ del repo
    solo obligaria a Python a regenerarlos en el siguiente arranque, y ademas seria un
    efecto secundario desagradable de un script de build.
    """
    import shutil

    borrados, liberado = 0, 0
    for dirpath, dirnames, _files in os.walk(dist_root):
        if "__pycache__" not in dirnames:
            continue
        objetivo = os.path.join(dirpath, "__pycache__")
        for r, _d, fs in os.walk(objetivo):
            for f in fs:
                try:
                    liberado += os.path.getsize(os.path.join(r, f))
                except OSError:
                    pass
        shutil.rmtree(objetivo, ignore_errors=True)
        dirnames.remove("__pycache__")
        borrados += 1

    if borrados:
        print(f"Limpieza del bundle: {borrados} carpetas __pycache__ eliminadas "
              f"({liberado / 1048576:.1f} MB)")


def adhoc_sign_macos_bundle(path, deep=True):
    """Firma ad-hoc y verifica -- ver core/updater/macos_sign.py para el porque
    (NO es opcional en Apple Silicon) y para la implementacion real, compartida
    con el helper de swap, que tiene que volver a firmar el .app como ultimo
    paso tras aplicar una actualizacion."""
    print(f"Firmando ad-hoc {path} ...")
    try:
        adhoc_sign(path, deep=deep)
    except SigningError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    print("Firma ad-hoc aplicada y verificada.")


HELPER_NAME = "DowP_Updater"


def build_updater_helper(dist_root, work_root):
    """Compila el helper de swap como un segundo ejecutable, aparte de DowP.exe.

    Tiene que ser un binario DISTINTO al principal: en Windows un proceso no
    puede sobrescribir su propio .exe ni las DLLs que tiene cargadas, y
    DowP.exe cambia en casi todos los releases (ver core/updater/journal.py).

    --onefile en vez de --onedir: el helper corre una vez por actualizacion,
    asi que la extraccion a temp en cada arranque no importa, y evita meter
    un segundo _internal/ dentro del arbol de DowP.exe. Sin --add-data de
    src/ completo: el helper solo importa core.updater/.logger/.utils.paths
    (puro stdlib), no necesita temas ni el importer -- solo su propio icono
    (DowP_Updater.ico/.icns), pasado aparte via --icon, no --add-data.

    Sale DENTRO del mismo arbol que dist_root (junto a DowP.exe en Windows,
    dentro de Contents/MacOS en el .app de macOS): al vivir en el arbol que
    hashea tools/updater/publish.py, se publica y actualiza solo, sin
    tratamiento especial en el publicador ni en el cliente de descarga.
    """
    helper_exe_name = f"{HELPER_NAME}.exe" if IS_WINDOWS else HELPER_NAME
    print(f"\nCompilando {helper_exe_name} (helper de swap)...")

    helper_args = [
        HELPER_SCRIPT,
        "--name", HELPER_NAME,
        "--onefile",
        "--clean",
        "--noconfirm",
        "--distpath", dist_root,
        "--workpath", os.path.join(work_root, "helper"),
        "--specpath", os.path.join(work_root, "helper"),
        "--paths", SRC_DIR,
        # launcher.resume_pending_swap() importa core.utils.paths DENTRO de la funcion,
        # y paths.py importa PySide6: PyInstaller sigue ese import y metia Qt en el
        # helper (8,6 MB -> 28 MB). El helper nunca llama a esa funcion (verificado:
        # sus imports cargan con PySide6 bloqueado), asi que se excluye.
        "--exclude-module", "PySide6",
        "--exclude-module", "shiboken6",
    ]
    if HELPER_ICON_FILE and os.path.exists(HELPER_ICON_FILE):
        helper_args.extend(["--icon", HELPER_ICON_FILE])
    if not IS_MACOS:
        # En Windows suprime el flash de una consola al lanzar el helper. En
        # macOS, --onefile + --windowed hace que PyInstaller genere ADEMAS un
        # DowP_Updater.app anidado dentro de Contents/MacOS/ (mal formado --
        # "a required plist file or resource is malformed"), que rompe la
        # re-firma final de todo el bundle con --deep. El helper es un binario
        # de fondo sin ventana propia: no necesita --windowed en ningun SO,
        # pero en macOS directamente rompe el build si se incluye.
        helper_args.append("--windowed")

    PyInstaller.__main__.run(helper_args)

    helper_path = os.path.join(dist_root, helper_exe_name)
    if not os.path.exists(helper_path):
        print(f"ERROR: no se genero el helper esperado en {helper_path}")
        sys.exit(1)
    if IS_MACOS:
        # Binario Mach-O suelto (no un bundle): sin --deep, no trae dylibs anidadas.
        adhoc_sign_macos_bundle(helper_path, deep=False)
    print(f"Helper de swap listo en: {helper_path}")


APP_VERSION = read_app_version()

CURRENT_SYSTEM = platform.system()
CURRENT_ARCH = platform.machine()
IS_WINDOWS = CURRENT_SYSTEM == "Windows"
IS_MACOS = CURRENT_SYSTEM == "Darwin"

if IS_WINDOWS:
    ICON_FILE = os.path.join(SRC_DIR, "assets", "icons", "app", "DowP_Logo.ico")
    HELPER_ICON_FILE = os.path.join(SRC_DIR, "assets", "icons", "app", "DowP_Updater.ico")
elif IS_MACOS:
    ICON_FILE = os.path.join(SRC_DIR, "assets", "icons", "app", "DowP_Logo.icns")
    # Cosmetico nada mas: el helper se compila --onefile SIN --windowed en macOS
    # (ver build_updater_helper()), asi que no hay .app/Info.plist que lo asocie
    # a este icono -- Finder le sigue mostrando el generico de ejecutable Unix.
    # Se pasa de todas formas por si un PyInstaller futuro lo aprovecha, y por
    # paridad con Windows, donde si se ve en el Explorador.
    HELPER_ICON_FILE = os.path.join(SRC_DIR, "assets", "icons", "app", "DowP_Updater.icns")
else:
    ICON_FILE = None  # PyInstaller no soporta --icon nativamente en Linux
    HELPER_ICON_FILE = None

if not os.path.exists(MAIN_SCRIPT):
    print(f"ERROR: no se encontro main.py en {MAIN_SCRIPT}")
    sys.exit(1)

DIST_DIR = os.path.join(SCRIPT_DIR, "dist")
BUILD_DIR = os.path.join(SCRIPT_DIR, "build")
path_sep = ";" if IS_WINDOWS else ":"

# ─────────────────────────────────────────────────────────────────────────
# Módulos de PySide6 confirmados como NO usados (grep sobre src/: solo se
# importan QtCore, QtGui, QtWidgets, QtMultimedia, QtMultimediaWidgets,
# QtSvg y QtSvgWidgets). Se excluyen explícitamente para no arrastrar
# QtWebEngine (trae su propio Chromium embebido), QtQml/Quick, Qt3D, etc.
#
# Si agregas una feature que use un módulo de esta lista, quítalo de aquí
# (o vuelve a correr un grep de "from PySide6" sobre src/ para confirmar
# qué se usa realmente antes del próximo build).
# ─────────────────────────────────────────────────────────────────────────
UNUSED_QT_MODULES = [
    "Qt3DAnimation", "Qt3DCore", "Qt3DExtras", "Qt3DInput", "Qt3DLogic", "Qt3DRender",
    "QtAxContainer", "QtBluetooth", "QtCanvasPainter", "QtCharts", "QtConcurrent",
    "QtDBus", "QtDataVisualization", "QtDesigner", "QtGraphs", "QtGraphsWidgets",
    "QtHelp", "QtHttpServer", "QtLocation", "QtNetworkAuth", "QtNfc",
    "QtPositioning", "QtQml", "QtQuick", "QtQuick3D",
    "QtQuickControls2", "QtQuickTest", "QtQuickWidgets", "QtRemoteObjects",
    "QtScxml", "QtSensors", "QtSerialBus", "QtSerialPort", "QtSpatialAudio",
    "QtSql", "QtStateMachine", "QtTest", "QtTextToSpeech", "QtUiTools",
    "QtWebChannel", "QtWebEngineCore", "QtWebEngineQuick", "QtWebEngineWidgets",
    "QtWebSockets", "QtWebView", "QtXml",
]

args = [
    MAIN_SCRIPT,

    "--name", APP_NAME,
    "--onedir",
    "--windowed",
    "--clean",
    "--noconfirm",

    "--distpath", DIST_DIR,
    "--workpath", BUILD_DIR,
    "--specpath", BUILD_DIR,

    # main.py hace sys.path.append(.../src) en runtime, pero eso no ayuda al
    # análisis estático de PyInstaller (no ejecuta el script) — sin esto no
    # resolvería imports como "from gui.main_window import MainWindow".
    "--paths", SRC_DIR,

    # ── Datos: toda la carpeta src/ (fuentes, iconos, .qm, jsons de datos) ──
    # Los módulos de la app resuelven assets como base_dir/src/assets/...,
    # con base_dir derivado de __file__ de main.py — en modo --onedir
    # congelado eso cae dentro de _internal/, así que la carpeta destino
    # debe llamarse "src" para que esas rutas seguan resolviendo sin tocar
    # el código de la app.
    f"--add-data={SRC_DIR}{path_sep}src",

    # ── El DowP Importer viaja dentro de la app (~500 KB) ──
    # core/setup/importer_setup.py lo copia desde aqui a la carpeta de extensiones de
    # CEP cuando el usuario pulsa "Instalar" en Integraciones. Ir dentro del bundle es
    # lo que hace que el panel no necesite descarga, ni release propio, ni version
    # propia: se actualiza junto con la app. Destino "importer" a secas, que es donde
    # lo busca get_bundled_importer_dir() bajo sys._MEIPASS.
    f"--add-data={IMPORTER_DIR}{path_sep}importer",

    # python-engineio resuelve su driver async con importlib.import_module()
    # a partir de un string armado en runtime ('engineio.async_drivers.' +
    # async_mode) — invisible para el análisis estático de PyInstaller, así
    # que sin este hidden-import falla con "Invalid async_mode specified" en
    # el .exe aunque funcione perfecto desde fuente. adobe_socket_server.py
    # pide explícitamente async_mode='aiohttp'.
    "--hidden-import=engineio.async_drivers.aiohttp",

    # ── Dependencias de yt-dlp, invisibles para el análisis estático ──
    # yt-dlp NO se instala vía pip: se descarga como .zip en runtime y se
    # importa vía sys.path (ver ytdlp_setup.py). Como nada en el código
    # propio de la app hace "import curl_cffi" / "import mutagen" / etc.
    # directamente, PyInstaller nunca ve esos imports — solo existen dentro
    # del .zip descargado, invisible al analizador. Confirmado empíricamente
    # importando yt_dlp de verdad y revisando qué módulos externos toca.
    # optparse (stdlib) es el parser de CLI interno de yt-dlp; el resto son
    # sus dependencias opcionales reales, ya en requirements.txt pero nunca
    # alcanzadas por el grafo de imports estático.
    "--hidden-import=optparse",
    "--hidden-import=pyexpat",
    "--hidden-import=sqlite3",  # usado por yt-dlp para --cookies-from-browser
    "--hidden-import=fileinput",
    "--hidden-import=textwrap",
    "--hidden-import=gettext",
    "--hidden-import=getpass",
    "--hidden-import=shlex",
    "--hidden-import=netrc",
    "--hidden-import=mimetypes",
    "--hidden-import=csv",
    "--hidden-import=secrets",
    "--hidden-import=hmac",
    "--hidden-import=calendar",
    "--hidden-import=stringprep",
    "--hidden-import=unicodedata",
    "--hidden-import=quopri",
    "--hidden-import=nturl2path",
    "--collect-submodules=xml",
    "--collect-submodules=html",
    "--collect-submodules=email",
    "--collect-submodules=http",
    "--collect-submodules=urllib",
    "--collect-submodules=concurrent",
    "--collect-submodules=importlib",
    "--collect-submodules=asyncio",
    "--collect-submodules=ctypes",
    "--collect-submodules=encodings",
    "--collect-all=curl_cffi",
    "--collect-all=mutagen",
    "--collect-all=Cryptodome",
    "--collect-all=brotli",
    "--collect-all=websockets",
    "--collect-all=PIL",
    "--collect-all=pillow_heif",
    "--collect-all=psd_tools",
    "--collect-all=rawpy",

    # onnxruntime (rembg / futuros modelos de IA) trae binarios nativos pesados
    # (DirectML.dll en Windows, dylibs de CoreML en macOS, .so en Linux) que el
    # análisis estático de PyInstaller no siempre detecta -- collect-all los
    # arrastra completos. No hace falta ramificar por SO aquí: requirements.txt
    # ya resuelve con marcadores de entorno que este venv tenga instalado
    # onnxruntime-directml en Windows u onnxruntime estándar en Mac/Linux (ver
    # ese archivo), así que este --collect-all siempre apunta al paquete
    # correcto para el SO en el que se está compilando.
    "--collect-all=onnxruntime",
]

for mod in UNUSED_QT_MODULES:
    args.append(f"--exclude-module=PySide6.{mod}")

if IS_MACOS:
    args.extend([
        "--target-arch", CURRENT_ARCH,
        f"--osx-bundle-identifier=com.dowp.{APP_NAME.lower()}",
    ])

if ICON_FILE and os.path.exists(ICON_FILE):
    args.extend(["--icon", ICON_FILE])
else:
    print(f"Icono no encontrado para {CURRENT_SYSTEM} ({ICON_FILE}), se compila sin --icon.")

stamp_importer_version(APP_VERSION)

print(f"Compilando {APP_NAME} v{APP_VERSION} para {CURRENT_SYSTEM} ({CURRENT_ARCH})...")
PyInstaller.__main__.run(args)

# ── Resultado ────────────────────────────────────────────────────────────
if IS_MACOS:
    final_target = os.path.join(DIST_DIR, f"{APP_NAME}.app")
else:
    exe_name = f"{APP_NAME}.exe" if IS_WINDOWS else APP_NAME
    final_target = os.path.join(DIST_DIR, APP_NAME, exe_name)

if os.path.exists(final_target):
    # Limpiar ANTES de firmar: en macOS la firma cubre el contenido del bundle, asi que
    # tocar archivos despues de firmarla la invalidaria.
    prune_bundle(os.path.join(DIST_DIR, f"{APP_NAME}.app") if IS_MACOS
                 else os.path.join(DIST_DIR, APP_NAME))

    # El helper de swap se compila y coloca DENTRO del mismo arbol que DowP.exe
    # -- en macOS, best-effort: Contents/MacOS/ es donde PyInstaller pone el
    # ejecutable principal del bundle, pero esta ruta no se ha podido validar
    # en un Mac real (ver riesgos abiertos en ACTUALIZACIONES.md).
    helper_dist_root = (
        os.path.join(final_target, "Contents", "MacOS") if IS_MACOS
        else os.path.join(DIST_DIR, APP_NAME)
    )
    build_updater_helper(helper_dist_root, BUILD_DIR)

    # Firmar SIEMPRE despues de que el helper ya este dentro del bundle: la
    # firma del .app cubre todo su contenido, incluido el helper.
    if IS_MACOS:
        adhoc_sign_macos_bundle(final_target)
    print(f"\nBuild lista en: {final_target}")
else:
    print(f"\nADVERTENCIA: no se encontro el resultado esperado en {final_target}")
    sys.exit(1)
