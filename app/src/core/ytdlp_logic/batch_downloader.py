# src/core/ytdlp_logic/batch_downloader.py
from PySide6.QtCore import QCoreApplication
from core.ytdlp_logic.analyzer import get_video_info
from core.logger.logger_manager import logger

class BatchDownloader:
    """
    Agrupa utilidades específicas de yt-dlp para el procesamiento por lotes,
    como la extracción plana de listas de reproducción y la resolución de formatos.
    """
    
    @staticmethod
    def extract_playlist_items(playlist_url: str) -> tuple[list[dict], str | None]:
        """
        Realiza un análisis rápido (flat extraction) de una playlist.
        Retorna una lista de entradas simplificadas (con url, title, duration) y un error si ocurre.
        """
        logger.info(f"BatchDownloader: Iniciando extracción plana de playlist: {playlist_url}")
        
        # Opciones para extracción rápida (sin analizar formatos de cada video)
        extra_opts = {
            'extract_flat': True,
            'skip_download': True,
            'playlist_items': '1-1000' # Límite razonable de elementos para no saturar
        }
        
        info_dict, error = get_video_info(playlist_url, extra_opts)
        
        if error:
            logger.error(f"BatchDownloader: Error analizando playlist: {error}")
            return [], error
            
        if not info_dict:
            return [], QCoreApplication.translate("BatchDownloader", "No se pudo extraer información de la URL proporcionada.")
            
        entries = []
        # Comprobar si realmente es una playlist / contiene múltiples entradas
        if 'entries' in info_dict:
            for item in info_dict['entries']:
                if not item:
                    continue
                # yt-dlp flat extraction devuelve url o id/url_base
                url = item.get('url') or item.get('webpage_url')
                if not url and item.get('id'):
                    # Reconstruir url de youtube si es necesario
                    ie_key = item.get('ie_key') or info_dict.get('extractor_key', '')
                    if ie_key and ie_key.lower() == 'youtube':
                        url = f"https://www.youtube.com/watch?v={item['id']}"
                    else:
                        url = item['id'] # Como fallback
                
                if url:
                    entries.append({
                        'url': url,
                        'title': item.get('title') or "Video sin título",
                        'duration': item.get('duration'),
                        'thumbnail': item.get('thumbnail') or (item.get('thumbnails', [{}])[0].get('url') if item.get('thumbnails') else None),
                        'playlist_index': item.get('playlist_index')
                    })
            logger.info(f"BatchDownloader: Se extrajeron {len(entries)} elementos de la playlist.")
        else:
            # Si no era una playlist sino un video único, tratarlo como tal
            entries.append({
                'url': playlist_url,
                'title': info_dict.get('title') or "Video único",
                'duration': info_dict.get('duration'),
                'thumbnail': info_dict.get('thumbnail') or (info_dict.get('thumbnails', [{}])[0].get('url') if info_dict.get('thumbnails') else None),
                'playlist_index': 1
            })
            logger.info("BatchDownloader: La URL corresponde a un video único, añadido a la lista.")
            
        return entries, None

    @staticmethod
    def download_thumbnail_to_file(thumbnail_url: str, output_path: str) -> bool:
        """
        Descarga una miniatura desde una URL y la guarda directamente en un archivo local.
        """
        import requests
        try:
            logger.info(f"BatchDownloader: Descargando miniatura de: {thumbnail_url}")
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            resp = requests.get(thumbnail_url, headers=headers, timeout=15)
            if resp.status_code == 200:
                with open(output_path, 'wb') as f:
                    f.write(resp.content)
                logger.info(f"BatchDownloader: Miniatura guardada en {output_path}")
                return True
            else:
                logger.warning(f"BatchDownloader: No se pudo obtener la miniatura, código: {resp.status_code}")
        except Exception as e:
            logger.error(f"BatchDownloader: Error descargando miniatura: {e}")
        return False
