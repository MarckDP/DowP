import os
import requests
from PySide6.QtCore import QObject, Signal
from core.logger.logger_manager import logger
from core.utils.config_manager import get_config


class VegasIntegrationService(QObject):
    """
    Servicio para comunicarse con la extensión DowP Importer en VEGAS Pro
    mediante el micro-servidor HTTP local en http://127.0.0.1:18946.
    """
    connection_changed = Signal(bool)
    files_imported = Signal(int)
    files_pushed = Signal(list, str)

    _instance = None
    BASE_URL = "http://127.0.0.1:18946"

    def __init__(self):
        super().__init__()
        self.is_connected = False
        VegasIntegrationService._instance = self

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = VegasIntegrationService()
        return cls._instance

    def check_connection(self) -> bool:
        """Comprueba si la extensión DowP Importer en VEGAS Pro está escuchando."""
        try:
            r = requests.get(f"{self.BASE_URL}/status", timeout=1.5)
            if r.status_code == 200:
                data = r.json()
                ok = data.get("app") == "vegas"
                if ok != self.is_connected:
                    self.is_connected = ok
                    self.connection_changed.emit(ok)
                return ok
        except Exception:
            pass

        if self.is_connected:
            self.is_connected = False
            self.connection_changed.emit(False)
        return False

    def notify_linked(self, linked: bool) -> bool:
        """Notifica a la extensión de VEGAS Pro si está vinculada o desvinculada como editor activo."""
        try:
            r = requests.post(f"{self.BASE_URL}/set_linked", json={"linked": linked}, timeout=1.5)
            return r.status_code == 200
        except Exception:
            return False

    def send_files_to_vegas(self, files: list) -> bool:
        """
        Envía una lista de archivos a VEGAS Pro.
        files: lista de strings (rutas) o diccionarios file_package de DowP.
        """
        file_paths = []
        for f in files:
            if isinstance(f, dict):
                if "subclips" in f:
                    self.send_subclips_to_vegas(f)
                    continue
                # 1. Comprobar ruta directa
                p = f.get('path') or f.get('file_path')
                if p and isinstance(p, str) and (os.path.exists(p) or not os.path.isabs(p)):
                    if p not in file_paths:
                        file_paths.append(str(p))
                    continue
                # 2. Comprobar video o audio del paquete de medios
                media = f.get('video') or f.get('audio')
                if media and isinstance(media, str) and (os.path.exists(media) or not os.path.isabs(media)):
                    if media not in file_paths:
                        file_paths.append(str(media))
                # 3. Comprobar miniatura (si no hay video/audio, es una imagen o foto)
                elif f.get('thumbnail') and isinstance(f['thumbnail'], str) and (os.path.exists(f['thumbnail']) or not os.path.isabs(f['thumbnail'])):
                    if f['thumbnail'] not in file_paths:
                        file_paths.append(str(f['thumbnail']))
            elif isinstance(f, str) and (os.path.exists(f) or not os.path.isabs(f)):
                if f not in file_paths:
                    file_paths.append(f)

        if not file_paths:
            logger.warning("[VegasService] No se proporcionaron rutas de archivo válidas.")
            return False

        payload = {
            "files": file_paths
        }

        try:
            r = requests.post(f"{self.BASE_URL}/import", json=payload, timeout=5.0)
            if r.status_code == 200:
                res = r.json()
                count = res.get("importedCount", len(file_paths))
                logger.info(f"[VegasService] Importados {count} archivo(s) en VEGAS Pro.")
                self.files_imported.emit(count)
                return True
            else:
                logger.error(f"[VegasService] Error al importar en VEGAS Pro: HTTP {r.status_code}")
                return False
        except Exception as e:
            logger.error(f"[VegasService] Error conectando con VEGAS Pro: {e}")
            return False

    def send_subclips_to_vegas(self, payload: dict) -> bool:
        """
        Envía información de subclips (in/out) a VEGAS Pro.
        payload: {"filePath": str, "subclips": [{"name": str, "in": float, "out": float}]}
        """
        try:
            r = requests.post(f"{self.BASE_URL}/import_subclips", json=payload, timeout=5.0)
            if r.status_code == 200:
                logger.info("[VegasService] Subclips importados en VEGAS Pro exitosamente.")
                return True
            else:
                logger.error(f"[VegasService] Error importando subclips en VEGAS: HTTP {r.status_code}")
                return False
        except Exception as e:
            logger.error(f"[VegasService] Error al enviar subclips a VEGAS Pro: {e}")
            return False

    def attach_routes(self, app):
        """Registra las rutas REST de VEGAS Pro en el servidor aiohttp local."""
        from aiohttp import web

        async def handle_vegas_push(request):
            try:
                data = await request.json()
                raw_items = data.get('items', [])
                items = []
                for raw in raw_items:
                    if isinstance(raw, dict) and raw.get('path'):
                        item = {
                            'path': str(raw['path']),
                            'name': str(raw.get('name') or ''),
                            'has_trim': bool(raw.get('hasTrim') or raw.get('has_trim')),
                            'in': raw.get('in'),
                            'out': raw.get('out'),
                        }
                        try:
                            item['in'] = float(item['in']) if item['in'] is not None else None
                            item['out'] = float(item['out']) if item['out'] is not None else None
                        except (TypeError, ValueError):
                            item['in'] = item['out'] = None
                            item['has_trim'] = False
                        if item['in'] is None or item['out'] is None or item['out'] <= item['in']:
                            item['has_trim'] = False
                        items.append(item)
                logger.info(f"[VegasService] VEGAS envio {len(items)} elemento(s) a DowP.")
                if items:
                    self.files_pushed.emit(items, 'vegas')
                return web.json_response({'success': True, 'count': len(items)})
            except Exception as e:
                logger.error(f"[VegasService] Error procesando push de VEGAS: {e}")
                return web.json_response({'error': str(e)}, status=500)

        async def handle_vegas_status(request):
            from core.services.editor_integration_manager import EditorIntegrationManager
            mgr = EditorIntegrationManager.get_instance()
            active_editor = mgr.active_editor if mgr else None
            return web.json_response({
                'status': 'ok',
                'app': 'DowP',
                'activeEditor': active_editor,
                'isLinked': (active_editor == 'vegas')
            })

        async def handle_vegas_link(request):
            from core.services.editor_integration_manager import EditorIntegrationManager
            mgr = EditorIntegrationManager.get_instance()
            if not mgr:
                return web.json_response({'success': False, 'error': 'No editor manager'}, status=500)
            try:
                data = await request.json()
            except Exception:
                data = {}
            toggle = data.get('toggle', False)
            if toggle:
                new_state = (mgr.active_editor != 'vegas')
            else:
                new_state = bool(data.get('linked', True))

            target = 'vegas' if new_state else None
            mgr.force_adobe_target(target)
            return web.json_response({
                'success': True,
                'activeEditor': mgr.active_editor,
                'isLinked': (mgr.active_editor == 'vegas')
            })

        app.router.add_post('/api/vegas/push', handle_vegas_push)
        app.router.add_get('/api/vegas/status', handle_vegas_status)
        app.router.add_post('/api/vegas/link', handle_vegas_link)

