from PySide6.QtWidgets import QFileDialog
from core.logger.logger_manager import logger

def download_thumbnail(widget):
    """
    Descarga la miniatura actual mostrada en el widget VideoDetailsWidget.
    Abre un diálogo de guardado para que el usuario elija el destino y el formato.
    """
    if getattr(widget.thumb_container, '_pixmap', None) is None or widget.thumb_container._pixmap.isNull():
        return
        
    base_name = widget.title_input.text()
    for c in ['<', '>', ':', '"', '/', '\\', '|', '?', '*']:
        base_name = base_name.replace(c, '')
    if not base_name.strip():
        base_name = "miniatura"
        
    dialog = QFileDialog(widget)
    dialog.setWindowTitle(widget.tr("Guardar miniatura"))
    dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
    dialog.setDirectory("") 
    dialog.selectFile(f"{base_name}.png")
    dialog.setNameFilters([
        "PNG Image (*.png)",
        "JPEG Image (*.jpg *.jpeg)",
        "WebP Image (*.webp)",
        "All Files (*.*)"
    ])
    dialog.setDefaultSuffix("png")
    
    if dialog.exec() == QFileDialog.DialogCode.Accepted:
        save_path = dialog.selectedFiles()[0]
        if save_path:
            try:
                widget.thumb_container._pixmap.save(save_path)
                
                # Send to Adobe if integration is active
                from core.services.editor_integration_manager import EditorIntegrationManager
                editor_mgr = EditorIntegrationManager.get_instance()
                if editor_mgr and editor_mgr.is_auto_send_enabled:
                    editor_mgr.process_raw_download(save_path, None)
                    
                from gui.dialogs.dialogs import show_info
                show_info(widget, widget.tr("Éxito"), widget.tr("Miniatura guardada correctamente."))
            except Exception as e:
                logger.error(f"Error guardando miniatura: {e}")
                from gui.dialogs.dialogs import show_warning
                show_warning(widget, widget.tr("Error"), widget.tr("Hubo un error al guardar la miniatura."))

def send_thumbnail_to_image_tools(widget):
    """Guarda la miniatura actual en disco (silenciosamente, sin diálogo) y la envía
    a la cola de Editor de Imagen, cambiando de pestaña. A diferencia de
    download_thumbnail(), esto es un "enviar" de un solo clic, no un "guardar" con
    control de destino -- por eso no abre QFileDialog."""
    if getattr(widget.thumb_container, '_pixmap', None) is None or widget.thumb_container._pixmap.isNull():
        return

    base_name = widget.title_input.text()
    for c in ['<', '>', ':', '"', '/', '\\', '|', '?', '*']:
        base_name = base_name.replace(c, '')
    if not base_name.strip():
        base_name = "miniatura"

    import os
    import uuid
    from core.utils.paths import get_sent_thumbnails_dir
    save_path = os.path.join(get_sent_thumbnails_dir(), f"{base_name}_{uuid.uuid4().hex[:8]}.png")

    try:
        widget.thumb_container._pixmap.save(save_path)
    except Exception as e:
        logger.error(f"Error guardando miniatura para Editor de Imagen: {e}")
        return

    main_win = widget.window()
    if not main_win or not hasattr(main_win, "tab_image"):
        return
    main_win.tab_image.image_queue.add_files([save_path])
    main_win.tabs.setCurrentWidget(main_win.tab_image)
    logger.info(f"[VideoDetails] Miniatura enviada a Editor de Imagen: {save_path}")

from core.ytdlp_logic.analyzer import get_video_info

def analyze_media_for_queue(url, analyze_playlist=True, fast_mode=True, progress_callback=None,
                            cancellation_event=None):
    """
    Analiza una URL para la cola avanzada.
    - Sin playlist: fuerza un solo medio.
    - Playlist lenta: extrae entradas completas.
    - Playlist rápida: usa extracción flat para abrir selector de items.
    """
    opts = {
        'noplaylist': not analyze_playlist,
        'listsubtitles': False,
        'ignoreerrors': True,
    }
    if not analyze_playlist:
        opts.update({
            'playlist_items': '1',
            'playlistend': 1
        })
    elif fast_mode:
        opts['extract_flat'] = 'in_playlist'
    return get_video_info(url, extra_opts=opts, progress_callback=progress_callback,
                          cancellation_event=cancellation_event)

def analyze_single_media(url):
    """
    Analiza una URL asegurándose de obtener siempre un solo medio.
    Si la URL es una lista de reproducción o contiene múltiples medios,
    fuerza a yt-dlp a extraer únicamente el primer elemento o el video especificado.
    """
    opts = {
        'noplaylist': True,
        'playlist_items': '1',
        'playlistend': 1
    }
    return get_video_info(url, extra_opts=opts)
