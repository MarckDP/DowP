# src/core/setup/manager.py
import os
from .ytdlp_setup import check_ytdlp, download_ytdlp, get_ytdlp_path
from .ffmpeg_setup import check_ffmpeg, download_ffmpeg, get_ffmpeg_dir
from .deno_setup import check_deno, download_deno, get_deno_dir
from .potprovider_setup import (
    check_all as check_potprovider,
    download_potprovider,
    get_potprovider_dir,
)
from .wpc_setup import check_wpc, install_wpc
from core.logger.logger_manager import logger

def get_ytdlp_base_args():
    """
    Returns a list of base arguments for yt-dlp, including dependency paths.
    """
    args = []
    
    # 1. External Dependencies Paths
    ffmpeg_dir = get_ffmpeg_dir()
    if check_ffmpeg():
        args.extend(["--ffmpeg-location", ffmpeg_dir])
        
    return args

def get_dependency_env():
    """
    Returns an environment dictionary with dependencies added to PATH.
    """
    env = os.environ.copy()
    
    # Add Deno, FFmpeg y PotProvider al PATH para que yt-dlp los encuentre como subprocesos
    paths = [get_deno_dir(), get_ffmpeg_dir(), get_potprovider_dir()]
    
    # Filter only existing paths
    existing_paths = [p for p in paths if os.path.exists(p)]
    
    if existing_paths:
        new_path = os.pathsep.join(existing_paths) + os.pathsep + env.get("PATH", "")
        env["PATH"] = new_path
        logger.debug(f"Environment PATH updated with: {existing_paths}")
        
    return env

def verify_all_dependencies():
    """
    Verifies all dependencies and returns a dictionary of their status.
    """
    logger.info("Verifying all dependencies...")
    status = {
        "yt-dlp": check_ytdlp(),
        "ffmpeg": check_ffmpeg(),
        "deno": check_deno(),
        "potprovider": check_potprovider(),
        # Respaldo con token del navegador (ver client_profiles). Opcional: si no se
        # puede instalar, DowP arranca igual.
        "wpc": check_wpc(),
    }
    for dep, exists in status.items():
        logger.info(f"Dependency {dep}: {'Found' if exists else 'Missing'}")
    return status

def download_missing_dependencies():
    """
    Downloads any missing dependencies.
    """
    logger.info("Starting download of missing dependencies...")
    results = []
    
    if not check_ytdlp():
        logger.info("yt-dlp is missing. Downloading...")
        results.append(("yt-dlp", download_ytdlp()))
    
    if not check_ffmpeg():
        logger.info("ffmpeg is missing. Downloading...")
        results.append(("ffmpeg", download_ffmpeg()))

    if not check_deno():
        logger.info("deno is missing. Downloading...")
        results.append(("deno", download_deno()))

    if not check_potprovider():
        logger.info("PO Token Provider is missing. Downloading...")
        results.append(("potprovider", download_potprovider()))

    if not check_wpc():
        logger.info("WPC is missing. Downloading...")
        results.append(("wpc", install_wpc()))

    return results

if __name__ == "__main__":
    logger.info("Manual dependency check initiated")
    status = verify_all_dependencies()
    
    if not all(status.values()):
        results = download_missing_dependencies()
        for dep, (success, msg) in results:
            if success:
                logger.info(f"{dep}: {msg}")
            else:
                logger.error(f"{dep}: {msg}")
    else:
        logger.info("All dependencies are already satisfied.")
