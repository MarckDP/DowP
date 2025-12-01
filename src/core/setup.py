import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
import requests

from packaging import version
from main import PROJECT_ROOT, BIN_DIR, FFMPEG_BIN_DIR, REMBG_MODELS_DIR, UPSCALING_DIR
from src.core.constants import UPSCALING_TOOLS 

DENO_BIN_DIR = os.path.join(BIN_DIR, "deno")
POPPLER_BIN_DIR = os.path.join(BIN_DIR, "poppler") 
INKSCAPE_BIN_DIR = os.path.join(BIN_DIR, "inkscape")
GHOSTSCRIPT_BIN_DIR = os.path.join(BIN_DIR, "ghostscript")

DENO_VERSION_FILE = os.path.join(DENO_BIN_DIR, "deno_version.txt")
FFMPEG_VERSION_FILE = os.path.join(FFMPEG_BIN_DIR, "ffmpeg_version.txt")
POPPLER_VERSION_FILE = os.path.join(POPPLER_BIN_DIR, "poppler_version.txt")
INKSCAPE_VERSION_FILE = os.path.join(INKSCAPE_BIN_DIR, "inkscape_version.txt")

def check_and_install_python_dependencies(progress_callback):
    """Verifica e instala dependencias de Python, reportando el progreso."""
    progress_callback("Verificando dependencias de Python...", 5)
    try:
        import customtkinter
        import PIL
        import requests
        import yt_dlp
        import flask_socketio
        import gevent
        import py7zr 
        import rembg
        progress_callback("Dependencias de Python verificadas.", 15)
        return True
    except ImportError:
        progress_callback("Instalando dependencias necesarias...", 10)
    requirements_path = os.path.join(PROJECT_ROOT, "requirements.txt")
    if not os.path.exists(requirements_path):
        progress_callback("ERROR: No se encontró 'requirements.txt'.", -1)
        return False
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "pip", "install", "-r", requirements_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8'
        )
        stdout, stderr = process.communicate()
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, process.args, output=stdout, stderr=stderr)
        progress_callback("Dependencias instaladas.", 15)
        return True
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Falló la instalación de dependencias con pip: {e.stderr}")
        progress_callback(f"Error al instalar dependencias.", -1)
        return False

def get_latest_ffmpeg_info(progress_callback):
    """Consulta la API de GitHub para la última versión de FFMPEG."""
    progress_callback("Consultando la última versión de FFmpeg...", 5)
    try:
        api_url = "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases"
        response = requests.get(api_url, timeout=15)
        response.raise_for_status()
        releases = response.json()
        latest_release_data = next((r for r in releases if r['tag_name'] != 'latest'), None)
        if not latest_release_data:
            return None, None
        tag_name = latest_release_data["tag_name"]
        system = platform.system()
        file_identifier = ""
        if system == "Windows": file_identifier = "win64-gpl.zip"
        elif system == "Linux": file_identifier = "linux64-gpl.tar.xz"
        elif system == "Darwin": file_identifier = "osx64-gpl.zip"
        else: return None, None
        for asset in latest_release_data["assets"]:
            if file_identifier in asset["name"] and "shared" not in asset["name"]:
                progress_callback("Información de FFmpeg encontrada.", 10)
                return tag_name, asset["browser_download_url"]
        return tag_name, None
    except requests.RequestException as e:
        progress_callback(f"Error de red al buscar FFmpeg: {e}", -1)
        return None, None
    except (IndexError, KeyError) as e:
        progress_callback(f"Error en respuesta de API de FFmpeg: {e}", -1)
        return None, None

def download_and_install_ffmpeg(tag, url, progress_callback):
    """Descarga e instala FFMPEG, reportando el progreso de forma optimizada."""
    try:
        file_name = url.split('/')[-1]
        archive_name = os.path.join(PROJECT_ROOT, file_name)
        last_reported_progress = -1
        with requests.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))
            downloaded_size = 0
            with open(archive_name, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    if total_size > 0:
                        progress = 40 + (downloaded_size / total_size) * 40
                        if int(progress) > last_reported_progress:
                            progress_callback(f"Descargando FFmpeg: {downloaded_size / 1024 / 1024:.1f}/{total_size / 1024 / 1024:.1f} MB", progress)
                            last_reported_progress = int(progress)
        progress_callback("Extrayendo archivos de FFmpeg...", 85)
        temp_extract_path = os.path.join(PROJECT_ROOT, "ffmpeg_temp_extract")
        if os.path.exists(temp_extract_path): shutil.rmtree(temp_extract_path)
        if archive_name.endswith(".zip"):
            with zipfile.ZipFile(archive_name, 'r') as zip_ref: zip_ref.extractall(temp_extract_path)
        else:
            with tarfile.open(archive_name, 'r:xz') as tar_ref: tar_ref.extractall(temp_extract_path)

        os.makedirs(FFMPEG_BIN_DIR, exist_ok=True)
        bin_content_path = os.path.join(temp_extract_path, os.listdir(temp_extract_path)[0], 'bin')

        # Mover archivos a FFMPEG_BIN_DIR
        for item in os.listdir(bin_content_path):
            dest_path = os.path.join(FFMPEG_BIN_DIR, item) 
            if os.path.exists(dest_path): os.remove(dest_path)
            shutil.move(os.path.join(bin_content_path, item), dest_path)

        # --- NUEVO: LIMPIEZA DE FFMPEG (LA DIETA) ---
        # 1. Eliminar ffplay.exe (No se usa)
        ffplay_path = os.path.join(FFMPEG_BIN_DIR, "ffplay.exe")
        if os.path.exists(ffplay_path):
            try:
                os.remove(ffplay_path)
                print("INFO: ffplay.exe eliminado para ahorrar espacio.")
            except Exception as e:
                print(f"ADVERTENCIA: No se pudo borrar ffplay.exe: {e}")

        shutil.rmtree(temp_extract_path)
        os.remove(archive_name)
        with open(FFMPEG_VERSION_FILE, "w") as f: f.write(tag)
        progress_callback(f"FFmpeg {tag} instalado.", 95)
        return True
    except Exception as e:
        progress_callback(f"Error al instalar FFmpeg: {e}", -1)
        return False
    

def get_latest_deno_info(progress_callback):
    """Consulta la API de GitHub para la última versión de Deno."""
    progress_callback("Consultando la última versión de Deno...", 5)
    try:
        api_url = "https://api.github.com/repos/denoland/deno/releases/latest"
        response = requests.get(api_url, timeout=15)
        response.raise_for_status()
        latest_release_data = response.json()
        
        tag_name = latest_release_data["tag_name"]
        
        system = platform.system()
        file_identifier = ""
        if system == "Windows": file_identifier = "deno-x86_64-pc-windows-msvc.zip"
        elif system == "Linux": file_identifier = "deno-x86_64-unknown-linux-gnu.zip"
        elif system == "Darwin": file_identifier = "deno-x86_64-apple-darwin.zip"
        else: return None, None
        
        for asset in latest_release_data["assets"]:
            if file_identifier in asset["name"]:
                progress_callback("Información de Deno encontrada.", 10)
                return tag_name, asset["browser_download_url"]
                
        return tag_name, None
    except requests.RequestException as e:
        progress_callback(f"Error de red al buscar Deno: {e}", -1)
        return None, None
    except (IndexError, KeyError) as e:
        progress_callback(f"Error en respuesta de API de Deno: {e}", -1)
        return None, None

def download_and_install_deno(tag, url, progress_callback):
    """Descarga e instala Deno en la carpeta bin/deno/."""
    try:
        file_name = url.split('/')[-1]
        archive_name = os.path.join(PROJECT_ROOT, file_name)
        last_reported_progress = -1
        
        with requests.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))
            downloaded_size = 0
            with open(archive_name, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if not chunk: continue
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    if total_size > 0:
                        progress = 40 + (downloaded_size / total_size) * 40
                        if int(progress) > last_reported_progress:
                            progress_callback(f"Descargando Deno: {downloaded_size / 1024 / 1024:.1f}/{total_size / 1024 / 1024:.1f} MB", progress)
                            last_reported_progress = int(progress)
                            
        progress_callback("Extrayendo archivos de Deno...", 85)
        
        # Crear el directorio de Deno (bin/deno/)
        os.makedirs(DENO_BIN_DIR, exist_ok=True)
        
        # Extraer el zip
        with zipfile.ZipFile(archive_name, 'r') as zip_ref:
            # El zip de Deno solo contiene el ejecutable (ej: deno.exe)
            for member in zip_ref.namelist():
                if member.lower().startswith('deno'):
                    zip_ref.extract(member, DENO_BIN_DIR)
                    # Moverlo si está en un subdirectorio (aunque Deno no suele hacerlo)
                    extracted_path = os.path.join(DENO_BIN_DIR, member)
                    final_path = os.path.join(DENO_BIN_DIR, os.path.basename(member))
                    if extracted_path != final_path:
                         shutil.move(extracted_path, final_path)
        
        os.remove(archive_name)
        with open(DENO_VERSION_FILE, "w") as f: f.write(tag)
        progress_callback(f"Deno {tag} instalado.", 95)
        return True
    except Exception as e:
        progress_callback(f"Error al instalar Deno: {e}", -1)
        return False
    
def get_latest_poppler_info(progress_callback):
    """Consulta la API de GitHub para la última versión de Poppler."""
    progress_callback("Consultando la última versión de Poppler...", 5)
    try:
        # Repositorio específico solicitado
        api_url = "https://api.github.com/repos/oschwartz10612/poppler-windows/releases/latest"
        response = requests.get(api_url, timeout=15)
        response.raise_for_status()
        latest_release_data = response.json()
        
        tag_name = latest_release_data["tag_name"]
        
        for asset in latest_release_data["assets"]:
            # Buscamos el archivo .zip (generalmente Release-XX.XX.X-0.zip)
            if asset["name"].endswith(".zip") and "Release" in asset["name"]:
                progress_callback("Información de Poppler encontrada.", 10)
                return tag_name, asset["browser_download_url"]
                
        return tag_name, None
    except requests.RequestException as e:
        progress_callback(f"Error de red al buscar Poppler: {e}", -1)
        return None, None
    except (IndexError, KeyError) as e:
        progress_callback(f"Error en respuesta de API de Poppler: {e}", -1)
        return None, None

def download_and_install_poppler(tag, url, progress_callback):
    """Descarga e instala Poppler en bin/poppler/."""
    try:
        file_name = url.split('/')[-1]
        archive_name = os.path.join(PROJECT_ROOT, file_name)
        last_reported_progress = -1
        
        with requests.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))
            downloaded_size = 0
            with open(archive_name, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if not chunk: continue
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    if total_size > 0:
                        progress = 40 + (downloaded_size / total_size) * 40
                        if int(progress) > last_reported_progress:
                            progress_callback(f"Descargando Poppler: {downloaded_size / 1024 / 1024:.1f}/{total_size / 1024 / 1024:.1f} MB", progress)
                            last_reported_progress = int(progress)
                            
        progress_callback("Extrayendo archivos de Poppler...", 85)
        
        # Limpiar/Crear directorio
        if os.path.exists(POPPLER_BIN_DIR): shutil.rmtree(POPPLER_BIN_DIR)
        os.makedirs(POPPLER_BIN_DIR, exist_ok=True)
        
        temp_extract_path = os.path.join(PROJECT_ROOT, "poppler_temp")
        if os.path.exists(temp_extract_path): shutil.rmtree(temp_extract_path)

        with zipfile.ZipFile(archive_name, 'r') as zip_ref:
            zip_ref.extractall(temp_extract_path)
            
        # Lógica para encontrar la carpeta 'Library/bin' dentro del zip extraído
        bin_source_path = None
        for root, dirs, files in os.walk(temp_extract_path):
            if "pdfinfo.exe" in files: # Buscamos un ejecutable clave
                bin_source_path = root
                break
        
        if bin_source_path:
            # Mover el contenido de esa carpeta bin a nuestro POPPLER_BIN_DIR
            for item in os.listdir(bin_source_path):
                shutil.move(os.path.join(bin_source_path, item), POPPLER_BIN_DIR)
        else:
            raise Exception("No se encontró la carpeta bin/ con ejecutables dentro del zip de Poppler.")

        # Limpieza
        shutil.rmtree(temp_extract_path)
        os.remove(archive_name)
        
        with open(POPPLER_VERSION_FILE, "w") as f: f.write(tag)
        progress_callback(f"Poppler {tag} instalado.", 95)
        return True
    except Exception as e:
        progress_callback(f"Error al instalar Poppler: {e}", -1)
        return False

def check_poppler_status(progress_callback):
    """Verifica el estado únicamente de Poppler."""
    try:
        poppler_exe = "pdfinfo.exe" if platform.system() == "Windows" else "pdfinfo"
        poppler_path = os.path.join(POPPLER_BIN_DIR, poppler_exe)
        poppler_exists = os.path.exists(poppler_path)

        local_tag = ""
        if os.path.exists(POPPLER_VERSION_FILE):
            with open(POPPLER_VERSION_FILE, 'r') as f:
                local_tag = f.read().strip()

        latest_tag, download_url = get_latest_poppler_info(progress_callback)

        return {
            "status": "success",
            "poppler_path_exists": poppler_exists,
            "local_poppler_version": local_tag,
            "latest_poppler_version": latest_tag,
            "poppler_download_url": download_url
        }
    except Exception as e:
        return {"status": "error", "message": f"Error en la verificación de Poppler: {e}"}

def check_environment_status(progress_callback, check_updates=True): # <--- NUEVO PARAMETRO
    """
    Verifica el estado del entorno.
    Si check_updates=False, salta las consultas lentas a GitHub.
    """
    try:
        # Importar dependencias (Esto es rápido si ya están instaladas)
        if not check_and_install_python_dependencies(progress_callback):
            return {"status": "error", "message": "Fallo crítico en dependencias Python."}
        
        # --- 1. Chequeo Local (Rápido) ---
        # Definir rutas (esto ya lo tienes, asegúrate de que coincida con tu código)
        ffmpeg_exe = "ffmpeg.exe" if platform.system() == "Windows" else "ffmpeg"
        ffmpeg_path = os.path.join(FFMPEG_BIN_DIR, ffmpeg_exe)
        ffmpeg_exists = os.path.exists(ffmpeg_path)
        
        local_tag = ""
        if os.path.exists(FFMPEG_VERSION_FILE):
            with open(FFMPEG_VERSION_FILE, 'r') as f: local_tag = f.read().strip()
        
        # --- 1. FFmpeg ---
        ffmpeg_path = os.path.join(FFMPEG_BIN_DIR, "ffmpeg.exe" if platform.system() == "Windows" else "ffmpeg")
        ffmpeg_exists = os.path.exists(ffmpeg_path)
        
        local_tag = ""
        if os.path.exists(FFMPEG_VERSION_FILE):
            with open(FFMPEG_VERSION_FILE, 'r') as f:
                local_tag = f.read().strip()
        # Deno...
        deno_exe = "deno.exe" if platform.system() == "Windows" else "deno"
        deno_path = os.path.join(DENO_BIN_DIR, deno_exe)
        deno_exists = os.path.exists(deno_path)
        local_deno_tag = ""
        if os.path.exists(DENO_VERSION_FILE):
            with open(DENO_VERSION_FILE, 'r') as f: local_deno_tag = f.read().strip()

        # Poppler...
        poppler_exe = "pdfinfo.exe" if platform.system() == "Windows" else "pdfinfo"
        poppler_path = os.path.join(POPPLER_BIN_DIR, poppler_exe)
        poppler_exists = os.path.exists(poppler_path)
        local_poppler_tag = ""
        if os.path.exists(POPPLER_VERSION_FILE):
            with open(POPPLER_VERSION_FILE, 'r') as f: local_poppler_tag = f.read().strip()

        # --- 2. Chequeo Remoto (Lento) - SOLO SI ES NECESARIO ---
        latest_tag, download_url = None, None
        latest_deno_tag, deno_download_url = None, None
        latest_poppler_tag, poppler_download_url = None, None

        if check_updates:
            # Solo consultamos GitHub si nos lo piden explícitamente
            latest_tag, download_url = get_latest_ffmpeg_info(progress_callback)
            latest_deno_tag, deno_download_url = get_latest_deno_info(progress_callback)
            latest_poppler_tag, poppler_download_url = get_latest_poppler_info(progress_callback)
        else:
            progress_callback("Verificación rápida de entorno completada.", 20)

        # --- Construir diccionario FINAL ---
        return {
            "status": "success", 
            
            # FFmpeg
            "ffmpeg_path_exists": ffmpeg_exists,
            "local_version": local_tag,
            "latest_version": latest_tag,     # Será None si check_updates=False
            "download_url": download_url,
            
            # Deno
            "deno_path_exists": deno_exists,
            "local_deno_version": local_deno_tag,
            "latest_deno_version": latest_deno_tag,
            "deno_download_url": deno_download_url,

            # Poppler 
            "poppler_path_exists": poppler_exists,
            "local_poppler_version": local_poppler_tag,
            "latest_poppler_version": latest_poppler_tag,
            "poppler_download_url": poppler_download_url
        }
        
    except Exception as e:
        return {"status": "error", "message": f"Error en la verificación del entorno: {e}"}
    
def check_and_download_rembg_models(progress_callback):
    """
    Verifica y descarga los modelos de rembg (u2netp, u2net, isnet-general-use)
    en la carpeta bin/models/rembg.
    """
    # Diccionario de modelos: Nombre archivo -> URL directa
    models_to_check = {
        "u2netp.onnx": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx",
        "isnet-general-use.onnx": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-general-use.onnx",
        "u2net.onnx": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx"
    }

    os.makedirs(REMBG_MODELS_DIR, exist_ok=True)
    
    total_models = len(models_to_check)
    downloaded_count = 0
    
    try:
        for i, (filename, url) in enumerate(models_to_check.items()):
            file_path = os.path.join(REMBG_MODELS_DIR, filename)
            
            # Verificar si existe y no está vacío
            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                print(f"INFO: Modelo IA encontrado: {filename}")
                continue
            
            # Si no existe, descargar
            progress_msg = f"Descargando modelo IA ({i+1}/{total_models}): {filename}..."
            print(f"INFO: {progress_msg}")
            # Usamos un valor base alto (50%) para que se note en la barra de carga inicial
            progress_callback(progress_msg, 50 + (i * 10))
            
            with requests.get(url, stream=True, timeout=120) as r:
                r.raise_for_status()
                total_size = int(r.headers.get('content-length', 0))
                downloaded_size = 0
                
                with open(file_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if not chunk: continue
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        # Opcional: Log detallado de progreso intra-archivo si fuera necesario
            
            print(f"INFO: ✅ {filename} descargado exitosamente.")
            downloaded_count += 1
            
        if downloaded_count > 0:
            progress_callback(f"Se descargaron {downloaded_count} modelos de IA.", 90)
        else:
            progress_callback("Todos los modelos de IA están listos.", 90)
            
        return True

    except Exception as e:
        print(f"ERROR CRÍTICO descargando modelos de IA: {e}")
        progress_callback(f"Error descargando modelos: {e}", -1)
        return False
    
def check_ffmpeg_status(progress_callback):
    """
    Verifica el estado únicamente de FFmpeg.
    """
    try:
        ffmpeg_path = os.path.join(FFMPEG_BIN_DIR, "ffmpeg.exe" if platform.system() == "Windows" else "ffmpeg")
        ffmpeg_exists = os.path.exists(ffmpeg_path)

        local_tag = ""
        if os.path.exists(FFMPEG_VERSION_FILE):
            with open(FFMPEG_VERSION_FILE, 'r') as f:
                local_tag = f.read().strip()

        latest_tag, download_url = get_latest_ffmpeg_info(progress_callback)

        return {
            "status": "success",
            "ffmpeg_path_exists": ffmpeg_exists,
            "local_version": local_tag,
            "latest_version": latest_tag,
            "download_url": download_url
        }
    except Exception as e:
        return {"status": "error", "message": f"Error en la verificación de FFmpeg: {e}"}

def check_deno_status(progress_callback):
    """
    Verifica el estado únicamente de Deno.
    """
    try:
        deno_exe_name = "deno.exe" if platform.system() == "Windows" else "deno"
        deno_path = os.path.join(DENO_BIN_DIR, deno_exe_name)
        deno_exists = os.path.exists(deno_path)

        local_deno_tag = ""
        if os.path.exists(DENO_VERSION_FILE):
            with open(DENO_VERSION_FILE, 'r') as f:
                local_deno_tag = f.read().strip()

        latest_deno_tag, deno_download_url = get_latest_deno_info(progress_callback)

        return {
            "status": "success",
            "deno_path_exists": deno_exists,
            "local_deno_version": local_deno_tag,
            "latest_deno_version": latest_deno_tag,
            "deno_download_url": deno_download_url
        }
    except Exception as e:
        return {"status": "error", "message": f"Error en la verificación de Deno: {e}"}
    
def check_app_update(current_version_str):
    """Consulta GitHub para ver si hay una nueva versión y busca el instalador LIGHT en ZIP."""
    print(f"INFO: Verificando actualizaciones para la versión actual: {current_version_str}")
    try:
        api_url = "https://api.github.com/repos/MarckDP/DowP/releases"

        response = requests.get(api_url, timeout=10)
        response.raise_for_status()
        releases = response.json()

        if not releases:
            return {"update_available": False}

        # Encontrar la release más reciente
        latest_release = None
        for r in releases:
            if not r.get("prerelease", False):
                latest_release = r
                break
        if not latest_release: 
            latest_release = releases[0]

        latest_version_str = latest_release.get("tag_name", "0.0.0").lstrip('v')
        release_url = latest_release.get("html_url")

        installer_url = None
        
        # --- CAMBIO: Buscamos el ZIP ---
        expected_suffix = "Light_setup.zip" 
        
        for asset in latest_release.get("assets", []):
            asset_name = asset.get("name", "")
            
            # Verificamos versión y sufijo
            if f"v{latest_version_str}" in asset_name and asset_name.endswith(expected_suffix):
                installer_url = asset.get("browser_download_url")
                print(f"INFO: Instalador Light (ZIP) encontrado: {asset_name}")
                break 
        
        # Fallback: Si no encuentra el Light ZIP, buscar cualquier .zip (Full o normal)
        if not installer_url:
             print("ADVERTENCIA: No se encontró ZIP 'Light', buscando ZIP genérico...")
             for asset in latest_release.get("assets", []):
                if asset.get("name", "").endswith(".zip") and "setup" in asset.get("name", "").lower():
                    installer_url = asset.get("browser_download_url")
                    break

        current_v = version.parse(current_version_str)
        latest_v = version.parse(latest_version_str)

        if latest_v > current_v:
            return {
                "update_available": True,
                "latest_version": latest_version_str,
                "release_url": release_url,
                "installer_url": installer_url, # URL del .zip
                "is_prerelease": latest_release.get("prerelease", False)
            }
        else:
            return {"update_available": False}

    except Exception as e:
        print(f"ERROR verificando actualización: {e}")
        return {"error": "Error al verificar."}
    
# --- FUNCIONES DE INKSCAPE (NUEVO) ---

def get_latest_inkscape_info(progress_callback):
    """Consulta la API de GitHub (Mirror oficial) para la última versión de Inkscape."""
    progress_callback("Consultando última versión de Inkscape (GitHub)...", 5)
    try:
        # ✅ CAMBIO: Usamos la API de GitHub en lugar de GitLab. 
        # Es mucho más fiable para obtener el enlace directo del .7z
        api_url = "https://api.github.com/repos/inkscape/inkscape/releases/latest"
        
        response = requests.get(api_url, timeout=15)
        response.raise_for_status()
        latest_release = response.json()
        
        tag_name = latest_release["tag_name"]
        download_url = None
        
        # Buscar el archivo .7z para Windows x64 en los assets de GitHub
        for asset in latest_release.get("assets", []):
            name = asset.get("name", "").lower()
            
            # Lógica de filtrado estricta:
            # 1. Debe ser .7z (portable)
            # 2. Debe ser x64 (64 bits)
            # 3. No debe ser un .exe ni .msi (instaladores)
            if "x64" in name and name.endswith(".7z") and "exe" not in name:
                download_url = asset.get("browser_download_url")
                break
        
        if download_url:
             progress_callback("Información de Inkscape encontrada.", 10)
             return tag_name, download_url
        
        # Si no se encuentra, lanzamos error para que la UI lo sepa
        progress_callback("No se encontró el archivo .7z en la release.", -1)
        return tag_name, None

    except Exception as e:
        progress_callback(f"Error al buscar Inkscape: {e}", -1)
        return None, None

def download_and_install_inkscape(tag, url, progress_callback):
    """Descarga e instala Inkscape (formato .7z)."""
    try:
        import py7zr # Importación tardía para asegurar que se instaló
        
        file_name = "inkscape_portable.7z"
        archive_name = os.path.join(PROJECT_ROOT, file_name)
        last_reported_progress = -1
        
        # 1. Descargar
        with requests.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))
            downloaded_size = 0
            with open(archive_name, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if not chunk: continue
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    if total_size > 0:
                        progress = 40 + (downloaded_size / total_size) * 40
                        if int(progress) > last_reported_progress:
                            progress_callback(f"Descargando Inkscape: {downloaded_size / 1024 / 1024:.1f}/{total_size / 1024 / 1024:.1f} MB", progress)
                            last_reported_progress = int(progress)

        progress_callback("Extrayendo Inkscape (esto puede tardar)...", 85)
        
        # 2. Preparar directorios
        if os.path.exists(INKSCAPE_BIN_DIR): shutil.rmtree(INKSCAPE_BIN_DIR)
        # No creamos el dir todavía, el extractor lo creará o extraerá una carpeta
        
        temp_extract_path = os.path.join(PROJECT_ROOT, "inkscape_temp")
        if os.path.exists(temp_extract_path): shutil.rmtree(temp_extract_path)
        os.makedirs(temp_extract_path, exist_ok=True)

        # 3. Extraer 7z
        with py7zr.SevenZipFile(archive_name, mode='r') as z:
            z.extractall(path=temp_extract_path)
            
        # 4. Organizar archivos
        # Inkscape suele extraerse en una carpeta tipo "inkscape-1.x.x-..."
        extracted_items = os.listdir(temp_extract_path)
        source_folder = None
        
        if len(extracted_items) == 1 and os.path.isdir(os.path.join(temp_extract_path, extracted_items[0])):
             source_folder = os.path.join(temp_extract_path, extracted_items[0])
        else:
             source_folder = temp_extract_path # Se extrajo suelto (raro en inkscape)

        # Mover todo a bin/inkscape
        shutil.move(source_folder, INKSCAPE_BIN_DIR)
        
        # 5. Limpieza
        if os.path.exists(temp_extract_path): shutil.rmtree(temp_extract_path)
        os.remove(archive_name)
        
        # Guardar versión
        with open(INKSCAPE_VERSION_FILE, "w") as f: f.write(tag)
        
        progress_callback(f"Inkscape {tag} instalado.", 100)
        return True
        
    except Exception as e:
        progress_callback(f"Error al instalar Inkscape: {e}", -1)
        print(f"ERROR DETALLADO INKSCAPE: {e}")
        return False
    
def check_inkscape_status(progress_callback):
    """
    Verifica si Inkscape está instalado manualmente en bin/inkscape.
    """
    progress_callback("Verificando Inkscape...", 10)
    try:
        # Buscamos el ejecutable principal
        inkscape_exe = "inkscape.exe" if platform.system() == "Windows" else "inkscape"
        inkscape_path = os.path.join(INKSCAPE_BIN_DIR, inkscape_exe)
        
        exists = os.path.exists(inkscape_path)
        
        if exists:
            progress_callback("Inkscape detectado.", 100)
            return {
                "status": "success",
                "exists": True,
                "path": inkscape_path
            }
        else:
            progress_callback("Inkscape no encontrado en bin/inkscape.", 100)
            return {
                "status": "success", # No es un error crítico, solo 'no encontrado'
                "exists": False,
                "path": None
            }
            
    except Exception as e:
        return {"status": "error", "message": f"Error verificando Inkscape: {e}"}

def check_ghostscript_status(progress_callback):
    """
    Verifica si Ghostscript está instalado manualmente en bin/ghostscript.
    Busca gswin64c.exe, gswin32c.exe o gs (Linux/Mac).
    """
    progress_callback("Verificando Ghostscript...", 10)
    try:
        # Nombres posibles del ejecutable
        if platform.system() == "Windows":
            gs_exes = ["gswin64c.exe", "gswin32c.exe", "gs.exe"]
        else:
            gs_exes = ["gs"]

        gs_path = None
        exists = False

        # Buscar cualquiera de los ejecutables
        for exe in gs_exes:
            potential_path = os.path.join(GHOSTSCRIPT_BIN_DIR, exe)
            if os.path.exists(potential_path):
                exists = True
                gs_path = potential_path
                break

        if exists:
            progress_callback("Ghostscript detectado.", 100)
            return {
                "status": "success",
                "exists": True,
                "path": gs_path
            }
        else:
            progress_callback("Ghostscript no encontrado en bin/ghostscript.", 100)
            return {
                "status": "success", # No es error crítico
                "exists": False,
                "path": None
            }
            
    except Exception as e:
        return {"status": "error", "message": f"Error verificando Ghostscript: {e}"}
    
def check_and_download_upscaling_tools(progress_callback, target_tool=None):
    """
    Verifica y descarga las herramientas de reescalado con reporte de porcentaje real.
    Si target_tool se especifica (ej: "Real-ESRGAN"), solo descarga esa.
    """
    os.makedirs(UPSCALING_DIR, exist_ok=True)
    
    # Filtrar herramientas si se especifica una
    tools_to_process = UPSCALING_TOOLS
    if target_tool:
        # Manejar coincidencia parcial (ej: "RealSR" coincide con la key "RealSR")
        # o búsqueda inversa si el nombre varía.
        if target_tool in UPSCALING_TOOLS:
            tools_to_process = {target_tool: UPSCALING_TOOLS[target_tool]}
        else:
            print(f"ERROR: Herramienta '{target_tool}' no encontrada en constantes.")
            return False

    total_tools = len(tools_to_process)
    processed_count = 0
    
    try:
        # Iteramos sobre el diccionario filtrado
        for key, info in tools_to_process.items():
            tool_name = info["name"]
            folder_name = info["folder"]
            exe_name = info["exe"]
            url = info["url"]
            
            target_folder = os.path.join(UPSCALING_DIR, folder_name)
            target_exe = os.path.join(target_folder, exe_name)
            
            # Verificar si ya existe
            if os.path.exists(target_exe):
                print(f"INFO: {tool_name} encontrado en {target_folder}")
                processed_count += 1
                continue
                
            # --- INICIO DESCARGA CON PROGRESO DETALLADO ---
            print(f"INFO: Iniciando descarga de {tool_name}...")
            
            # Descargar ZIP
            zip_filename = f"{folder_name}_temp.zip"
            zip_path = os.path.join(UPSCALING_DIR, zip_filename)
            
            try:
                with requests.get(url, stream=True, timeout=120) as r:
                    r.raise_for_status()
                    total_size = int(r.headers.get('content-length', 0))
                    downloaded_size = 0
                    last_reported_pct = -1
                    
                    with open(zip_path, 'wb') as f:
                        # Chunk de 64KB para velocidad
                        for chunk in r.iter_content(chunk_size=65536):
                            if chunk: 
                                f.write(chunk)
                                downloaded_size += len(chunk)
                                
                                # Calcular porcentaje
                                if total_size > 0:
                                    percent = int(downloaded_size * 100 / total_size)
                                    
                                    # Actualizar UI solo si cambió el porcentaje (para no saturar)
                                    if percent > last_reported_pct:
                                        last_reported_pct = percent
                                        
                                        dl_mb = downloaded_size / (1024 * 1024)
                                        tot_mb = total_size / (1024 * 1024)
                                        
                                        # Mensaje estilo: "⬇️ Real-ESRGAN: 45% (15.2/30.5 MB)"
                                        status_text = f"⬇️ {tool_name}: {percent}% ({dl_mb:.1f}/{tot_mb:.1f} MB)"
                                        
                                        # Valor numérico para barra de progreso global (opcional)
                                        progress_callback(status_text, percent)
                
                # --- EXTRACCIÓN ---
                progress_callback(f"Extrayendo {tool_name}...", 100)
                
                # Descomprimir
                temp_extract_dir = os.path.join(UPSCALING_DIR, f"{folder_name}_temp_extract")
                if os.path.exists(temp_extract_dir):
                    shutil.rmtree(temp_extract_dir) # Limpiar residuos anteriores
                    
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_extract_dir)
                
                # Mover contenido: Buscar la carpeta interna
                extracted_items = os.listdir(temp_extract_dir)
                source_path = temp_extract_dir
                
                # Si solo hay una carpeta dentro, entramos en ella
                if len(extracted_items) == 1 and os.path.isdir(os.path.join(temp_extract_dir, extracted_items[0])):
                    source_path = os.path.join(temp_extract_dir, extracted_items[0])
                
                # Mover a destino final (bin/models/upscaling/realesrgan)
                if os.path.exists(target_folder):
                    shutil.rmtree(target_folder)
                shutil.move(source_path, target_folder)
                
                print(f"INFO: ✅ {tool_name} instalado correctamente.")
                
                # Limpieza final
                os.remove(zip_path)
                if os.path.exists(temp_extract_dir):
                    shutil.rmtree(temp_extract_dir)
                    
            except Exception as e:
                print(f"ERROR descargando {tool_name}: {e}")
                # Limpiar en caso de error
                if os.path.exists(zip_path): 
                    try: os.remove(zip_path)
                    except: pass
                return False
            
            processed_count += 1
            
        return True

    except Exception as e:
        print(f"ERROR CRÍTICO gestionando herramientas de reescalado: {e}")
        progress_callback(f"Error en Upscaling: {e}", -1)
        return False
    
def get_remote_file_size(url):
    """Obtiene el tamaño de un archivo remoto en bytes sin descargarlo."""
    try:
        response = requests.head(url, allow_redirects=True, timeout=5)
        if response.status_code == 200:
            return int(response.headers.get('content-length', 0))
        return 0
    except Exception:
        return 0

def format_size(size_bytes):
    """Formatea bytes a MB/GB."""
    if size_bytes == 0:
        return "Desconocido"
    
    size_mb = size_bytes / (1024 * 1024)
    if size_mb >= 1024:
        return f"{size_mb / 1024:.2f} GB"
    return f"{size_mb:.1f} MB"