# src/core/setup/deno_setup.py
import os
import requests
import zipfile
import shutil
import platform
import stat
from core.logger.logger_manager import logger
from core.utils.http_download import download_file
from core.utils.paths import get_bin_root_dir

DENO_API_URL = "https://api.github.com/repos/denoland/deno/releases/latest"

def get_platform_info():
    """Determines the correct Deno asset and binary name based on the OS and architecture."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    
    # Normalize architecture
    if machine in ["amd64", "x86_64"]:
        arch = "x86_64"
    elif machine in ["arm64", "aarch64"]:
        arch = "aarch64"
    else:
        arch = "x86_64" # Default to x86_64 if unknown

    if system == "windows":
        asset_name = f"deno-{arch}-pc-windows-msvc.zip"
        binary_name = "deno.exe"
    elif system == "darwin":
        asset_name = f"deno-{arch}-apple-darwin.zip"
        binary_name = "deno"
    elif system == "linux":
        asset_name = f"deno-{arch}-unknown-linux-gnu.zip"
        binary_name = "deno"
    else:
        # Fallback to linux x86_64
        asset_name = "deno-x86_64-unknown-linux-gnu.zip"
        binary_name = "deno"

    return asset_name, binary_name

def get_deno_dir():
    """Returns the directory path for Deno."""
    deno_dir = os.path.join(get_bin_root_dir(), "bin", "dependences", "deno")
    if not os.path.exists(deno_dir):
        logger.info(f"Creating directory: {deno_dir}")
        os.makedirs(deno_dir)
    return deno_dir

def get_deno_path() -> str:
    """Devuelve la ruta absoluta al binario ejecutable de Deno según la plataforma actual."""
    _, binary_name = get_platform_info()
    return os.path.join(get_deno_dir(), binary_name)

_deno_checked = False

def check_deno():
    """Verifies if the Deno binary exists in the deno folder."""
    global _deno_checked
    _, binary_name = get_platform_info()
    deno_exe = get_deno_path()
    exists = os.path.exists(deno_exe)
    if not _deno_checked:
        logger.debug(f"Checking {binary_name} existence: {exists}")
        _deno_checked = True
    return exists

def download_deno(progress_callback=None):
    """Downloads, extracts, and cleans up Deno."""
    try:
        asset_name, binary_name = get_platform_info()
        logger.info(f"Fetching latest Deno release info from {DENO_API_URL} for {asset_name}")
        response = requests.get(DENO_API_URL, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        download_url = None
        for asset in data.get("assets", []):
            if asset["name"] == asset_name:
                download_url = asset["browser_download_url"]
                break
        
        if not download_url:
            logger.error(f"Deno asset '{asset_name}' not found in release assets")
            return False, "Deno asset not found."

        deno_dir = get_deno_dir()
        temp_zip = os.path.join(deno_dir, "deno_temp.zip")
        
        # 1. Download
        logger.info(f"Downloading Deno from {download_url}")
        download_file(download_url, temp_zip, progress_callback=progress_callback)
        
        # 2. Extraction
        logger.info("Extracting Deno package...")
        with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
            zip_ref.extractall(deno_dir)
        
        # 3. Unix Permissions
        deno_exe = os.path.join(deno_dir, binary_name)
        if os.path.exists(deno_exe) and platform.system().lower() != "windows":
            logger.info("Setting executable permissions for Deno binary...")
            st = os.stat(deno_exe)
            os.chmod(deno_exe, st.st_mode | stat.S_IEXEC)

        # 4. Cleanup
        logger.info("Cleaning up temporary zip file...")
        os.remove(temp_zip)
        
        if not check_deno():
            logger.error(f"{binary_name} was not found after extraction")
            return False, f"{binary_name} missing after extraction."

        logger.info("Deno setup completed successfully.")
        return True, "Deno downloaded and configured."
    except Exception as e:
        logger.error(f"Error setting up Deno: {e}")
        return False, str(e)

import subprocess
from core.utils.config_manager import get_config, save_config

def get_local_version(force_check=False):
    """Runs the local Deno to get its version, caching it in config.json to avoid lag."""
    if not check_deno():
        return None
        
    config = get_config()
    versions = config.get("dependency_versions", {})
    if not force_check and "deno" in versions:
        return versions["deno"]
        
    try:
        _, binary_name = get_platform_info()
        deno_exe = os.path.join(get_deno_dir(), binary_name)
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        result = subprocess.run(
            [deno_exe, "--version"], 
            capture_output=True, text=True, check=True, creationflags=flags
        )
        # Expected output format: 'deno 1.42.1 (release, x86_64-pc-windows-msvc)\nv8 ...'
        first_line = result.stdout.strip().split('\n')[0]
        version = first_line.split()[1] # Returns '1.42.1'
        
        # Save to config
        versions["deno"] = version
        config["dependency_versions"] = versions
        save_config(config)
        
        return version
    except Exception as e:
        logger.error(f"Error getting local Deno version: {e}")
        return None

def get_latest_remote_version():
    """Fetches the latest version string from GitHub API."""
    try:
        response = requests.get(DENO_API_URL, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("tag_name", "").lstrip("v")
    except Exception as e:
        logger.error(f"Error getting remote Deno version: {e}")
        return None

if __name__ == "__main__":
    if not check_deno():
        success, msg = download_deno()
        logger.info(msg)
    else:
        logger.info("Deno is already configured.")
