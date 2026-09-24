# src/core/utils/preset_manager.py
import json
import os

from PySide6.QtCore import QObject, Signal

from core.logger.logger_manager import logger
from core.utils.paths import get_app_data_dir
from PySide6.QtCore import QCoreApplication, QT_TRANSLATE_NOOP


def _get_presets_path() -> str:
    """Retorna la ruta al archivo JSON donde se persisten todos los presets."""
    return os.path.join(get_app_data_dir(), "presets.json")


# Categorias de "que hace" un preset RECODE, independientes de que pestaña/modulo lo
# creo (ver conversación: pensado para un futuro menú universal de "qué hacer con este
# archivo" - ej. despues de una descarga en Proceso Avanzado - donde a nadie le importa
# si el preajuste se armó en Convertir o en Avanzado, sino qué va a hacer). Registro
# abierto a propósito: agregar una función nueva (ej. "gif", "extraer_fotogramas" el día
# que existan) es sumar una entrada aquí, no reestructurar nada de lo guardado.
#
# Deliberadamente SIN nada de IA acá (ver IA_TOOL_FUNCTIONS abajo): mezclar categorías de
# recodificación con las de IA en el mismo combo de SavePresetDialog confundía al guardar
# -- un preset de Reescalado IA no "convierte" ni "comprime", y al revés, un preset de
# Recodificación no tiene nada que ver con "Reescalado". Cada PresetBar recibe el
# diccionario que le corresponde según su propio job_type (ver PresetBar.__init__).
PRESET_FUNCTIONS = {
    "convertir": QT_TRANSLATE_NOOP("preset_manager", "Convertir"),
    "comprimir": QT_TRANSLATE_NOOP("preset_manager", "Comprimir"),
    "edicion": QT_TRANSLATE_NOOP("preset_manager", "Edición / Proxy"),
    "gif": QT_TRANSLATE_NOOP("preset_manager", "GIF"),
    "audio": QT_TRANSLATE_NOOP("preset_manager", "Normalizar Audio"),
    "otro": QT_TRANSLATE_NOOP("preset_manager", "Otro"),
}

# Categorías de presets de IA -- namespace compartido "video_tools/ia_tools" (ver
# gui/tabs/video_tools/upscale_ia_panel.py), pensado a propósito para que TODA futura
# función de IA (quitar fondo, vectorizar, etc.) vaya sumando una entrada acá y
# apareciendo como un grupo más dentro del MISMO combo/tarjeta "Herramientas IA", en vez
# de crear un namespace y una pestaña de Preajustes nueva por cada una (ver
# conversación). Corta a propósito ("Reescalado", no "Reescalado IA"): el encabezado ya
# vive bajo la tarjeta "Preajustes de Herramientas IA", repetir "IA" ahí es ruido.
IA_TOOL_FUNCTIONS = {
    "ia_reescalar": QT_TRANSLATE_NOOP("preset_manager", "Reescalado"),
    "ia_profundidad": QT_TRANSLATE_NOOP("preset_manager", "Mapa de profundidad"),
}

# Solo las funciones de IA que Modo Rápido y Proceso Avanzado saben ejecutar después de
# una descarga (hoy, el Reescalado: ver core/tabs/video_tools/upscale_chain.py). Sus
# pickers usan esta lista, así un preajuste de Mapa de Profundidad (que solo corre en
# Herramientas Multimedia) no aparece ahí: PresetBar solo lista las funciones que recibe.
IA_POST_DOWNLOAD_FUNCTIONS = {
    "ia_reescalar": IA_TOOL_FUNCTIONS["ia_reescalar"],
}

# Namespace único (ver PresetManager) para TODO preset de IA -- constante acá, no un
# literal repetido en cada módulo que lo lee/escribe (quick_mode/download_controller.py,
# advanced_process/download_controller.py, recode_options.py, upscale_ia_panel.py,
# presets_panel.py): un namespace desincronizado en un solo lugar deja presets guardados
# que la ejecución real nunca encuentra, sin error visible.
IA_TOOLS_NAMESPACE = "video_tools/ia_tools"

# Grupo (dentro del mismo combo, no un filtro aparte - ver conversación) para presets sin
# función asignada: migrados de antes de que este campo existiera, o importados de un
# .json que no lo traía. Nunca es algo que se elija al GUARDAR (no está en
# PRESET_FUNCTIONS) - solo un encabezado más en el combo picker (ver PresetBar.refresh).
UNSPECIFIED_FUNCTION_LABEL = QT_TRANSLATE_NOOP("preset_manager", "Preajustes de Usuario")


class PresetManager(QObject):
    """
    Gestor genérico de presets (sin UI): guarda/carga/lista/borra preajustes con nombre,
    agrupados por namespace (ej. "video_tools/comprimir").

    El namespace es la clave de reutilización: cada pestaña o módulo de la app usa el
    suyo, y todos comparten el mismo archivo presets.json en AppData. Cada preajuste es
    un SOBRE con metadata de categorización aparte de los ajustes en si (ver
    conversación: "función" - qué hace, ver PRESET_FUNCTIONS - y "job_type" - qué tipo de
    trabajo hay que crear para ejecutarlo, ver core.utils.queue_manager.Job - son datos
    para decidir CÓMO MOSTRAR/EJECUTAR el preajuste, no parte de los ajustes de ffmpeg en
    sí, así que no se mezclan con `settings`):
        { "<namespace>": { "<nombre_preset>": {
            "function": "convertir"|"comprimir"|"edicion"|"otro"|None,
            "job_type": "RECODE",  # hoy el único tipo real; reservado para cuando
                                    # existan otros (ver conversación)
            "settings": { ...ajustes reales, lo que ya devolvía get_settings() antes... }
        } } }

    Compatibilidad: un archivo guardado ANTES de este envoltorio (ajustes pelados sin
    "settings" alrededor) se migra solo en memoria y se reescribe a disco la primera vez
    que se carga (ver _migrate_legacy_shape) - function=None, job_type="RECODE".

    Emite `presets_changed(namespace)` en cada mutación (guardar/eliminar/
    importar), para que cualquier PresetBar abierto se refresque solo sin
    necesidad de llamadas cruzadas manuales entre widgets.
    """
    _instance = None

    presets_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self._data = None  # caché en memoria, se carga lazy desde disco

    @classmethod
    def get_instance(cls) -> "PresetManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load(self):
        if self._data is not None:
            return
        path = _get_presets_path()
        self._data = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._data = data
            except Exception as e:
                logger.error(f"PresetManager: Error al leer presets.json: {e}")
        self._migrate_legacy_shape()
        self._migrate_renamed_namespaces()
        self._seed_defaults()

    def _migrate_legacy_shape(self):
        """Convierte en memoria (y reescribe a disco) cualquier preset guardado ANTES
        del sobre {function, job_type, settings} - se distingue por no tener la clave
        "settings" (ningún dict de ajustes real usa ese nombre de clave, así que no hay
        falsos positivos). function queda None (nunca se preguntó al guardarlo) y
        job_type "RECODE" (el único tipo que existía)."""
        changed = False
        for namespace, presets in self._data.items():
            if not isinstance(presets, dict):
                continue
            for name, entry in presets.items():
                if isinstance(entry, dict) and "settings" not in entry:
                    presets[name] = {"function": None, "job_type": "RECODE", "settings": entry}
                    changed = True
        if changed:
            logger.info("PresetManager: Presets guardados en formato anterior migrados al nuevo sobre.")
            self._save_to_disk()

    # Namespaces renombrados a lo largo de la vida de la app: {viejo: nuevo}. Se
    # fusiona en memoria (y se reescribe a disco) la primera vez que se carga, para que
    # presets ya guardados por el usuario bajo el nombre viejo no queden huérfanos (ver
    # conversación: "video_tools/upscale_ia" -> "video_tools/ia_tools" al generalizar la
    # tarjeta de Reescalado IA a "Herramientas IA").
    _RENAMED_NAMESPACES = {
        "video_tools/upscale_ia": "video_tools/ia_tools",
    }

    def _migrate_renamed_namespaces(self):
        changed = False
        for old_ns, new_ns in self._RENAMED_NAMESPACES.items():
            old_presets = self._data.pop(old_ns, None)
            if not old_presets:
                continue
            new_presets = self._data.setdefault(new_ns, {})
            for name, entry in old_presets.items():
                if name not in new_presets:  # no pisar uno ya guardado a mano bajo el nuevo nombre
                    new_presets[name] = entry
            changed = True
        if changed:
            logger.info("PresetManager: Namespace(s) renombrado(s) migrados en presets.json.")
            self._save_to_disk()

    # Clave reservada para metadata de siembra de defaults - "_" al frente para que
    # nunca choque con un namespace real (todos son del estilo "video_tools/algo").
    _SEED_META_KEY = "_default_presets_meta"

    def _seed_defaults(self):
        """Instala los preajustes empaquetados (ver core.utils.default_presets) la
        primera vez, y de nuevo cada vez que ese catálogo suba de versión - pero SOLO
        agrega lo que sea nuevo en esa versión, nunca resucita uno que el usuario haya
        borrado a mano (ver conversación). Se distingue "nunca sembrado" de "sembrado y
        borrado" guardando la lista completa de nombres ya sembrados en algún momento,
        no solo la versión."""
        try:
            from core.utils.default_presets import build_default_presets, DEFAULT_PRESETS_VERSION
        except Exception as e:
            logger.error(f"PresetManager: No se pudo cargar el catálogo de preajustes por defecto: {e}")
            return

        meta = self._data.get(self._SEED_META_KEY) or {}
        stored_version = meta.get("version", 0)
        if stored_version >= DEFAULT_PRESETS_VERSION:
            return

        seeded_before = set(meta.get("seeded_names", []))
        seeded_now = set(seeded_before)
        added = 0
        for preset in build_default_presets():
            namespace, name = preset["namespace"], preset["name"]
            key = f"{namespace}::{name}"
            seeded_now.add(key)
            if key in seeded_before:
                continue  # ya se sembró en una version anterior - se dejo tal cual esta (el usuario pudo haberlo editado o borrado a proposito)
            existing = self._data.get(namespace, {})
            if name in existing:
                continue  # ya existe un preset con ese nombre (creado a mano) - no lo pisamos
            self._data.setdefault(namespace, {})[name] = {
                "function": preset.get("function"),
                "job_type": preset.get("job_type", "RECODE"),
                "settings": preset["settings"],
            }
            added += 1

        self._data[self._SEED_META_KEY] = {"version": DEFAULT_PRESETS_VERSION, "seeded_names": sorted(seeded_now)}
        self._save_to_disk()
        logger.info(f"PresetManager: {added} preajuste(s) por defecto sembrado(s) (catálogo v{DEFAULT_PRESETS_VERSION}).")

    def _save_to_disk(self):
        try:
            with open(_get_presets_path(), "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"PresetManager: Error al escribir presets.json: {e}")

    def list_names(self, namespace: str) -> list:
        """Lista los nombres de presets de un namespace, ordenados alfabéticamente. Para
        UI que solo necesita nombres (ej. el combo simple de PresetBar) - si hace falta
        filtrar/agrupar por función, usar list_presets."""
        self._load()
        return sorted(self._data.get(namespace, {}).keys())

    def get_settings(self, namespace: str, name: str) -> dict:
        """Ajustes EJECUTABLES del preset (lo que ya consumía queue_manager antes de
        este cambio) - sin la metadata de categorización. Dict vacío si no existe."""
        self._load()
        entry = self._data.get(namespace, {}).get(name)
        if not isinstance(entry, dict):
            return {}
        settings = entry.get("settings", {})
        if not isinstance(settings, dict):
            return {}
        # El encoder de video de un preajuste "portable" se resuelve aquí, contra la GPU
        # de ESTE equipo (ver recode_guard.resolve_preset_for_this_pc). Se hace en
        # get_settings y no en cada pantalla porque los preajustes se ejecutan desde
        # varias (Preajustes, Modo Rápido, Proceso Avanzado): en una sola de ellas, las
        # otras seguirían usando el encoder del PC donde se guardó el preajuste.
        from core.utils.recode_guard import resolve_preset_for_this_pc
        return resolve_preset_for_this_pc(dict(settings))

    def get_preset(self, namespace: str, name: str) -> dict | None:
        """El sobre completo ({function, job_type, settings}) - para UI de
        exploración/filtrado (ver PresetsPanel). None si no existe. Usar get_settings()
        en cambio para ejecutar el preajuste (arrancar un job con sus ajustes)."""
        self._load()
        entry = self._data.get(namespace, {}).get(name)
        if not isinstance(entry, dict):
            return None
        return {
            "function": entry.get("function"),
            "job_type": entry.get("job_type", "RECODE"),
            "settings": dict(entry.get("settings") or {}),
        }

    def list_presets(self, namespace: str) -> list[dict]:
        """Todos los presets de un namespace como sobres completos ({name, function,
        job_type, settings}), ordenados alfabéticamente por nombre - para UI que
        necesita filtrar/agrupar por función (ver PresetsPanel)."""
        self._load()
        result = []
        for name in sorted(self._data.get(namespace, {}).keys()):
            preset = self.get_preset(namespace, name)
            if preset is not None:
                preset["name"] = name
                result.append(preset)
        return result

    def save_preset(self, namespace: str, name: str, settings: dict,
                     function: str | None = None, job_type: str = "RECODE"):
        """Guarda (o sobrescribe) un preset. `function` es la categoría para
        browsing/filtro (ver PRESET_FUNCTIONS) - None si no se especificó. `job_type` es
        el tipo de trabajo que hay que crear para ejecutarlo (hoy siempre "RECODE" -
        reservado para cuando existan otros tipos de acción, ver conversación)."""
        self._load()
        self._data.setdefault(namespace, {})[name] = {
            "function": function,
            "job_type": job_type,
            "settings": dict(settings),
        }
        self._save_to_disk()
        logger.info(f"PresetManager: Preset '{name}' guardado en '{namespace}' (función={function}).")
        self.presets_changed.emit(namespace)

    def delete_preset(self, namespace: str, name: str) -> bool:
        """Elimina un preset. Retorna True si existía."""
        self._load()
        presets = self._data.get(namespace, {})
        if name not in presets:
            return False
        del presets[name]
        self._save_to_disk()
        logger.info(f"PresetManager: Preset '{name}' eliminado de '{namespace}'.")
        self.presets_changed.emit(namespace)
        return True

    def export_preset(self, namespace: str, name: str, file_path: str) -> bool:
        """Exporta un preset a un archivo JSON independiente, con su función/job_type
        (ver import_preset: un archivo exportado ANTES de este cambio no los trae, y se
        importa igual con function=None/job_type="RECODE")."""
        preset = self.get_preset(namespace, name)
        if not preset or not preset["settings"]:
            return False
        payload = {
            "nombre": name, "namespace": namespace,
            "function": preset["function"], "job_type": preset["job_type"],
            "ajustes": preset["settings"],
        }
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            logger.info(f"PresetManager: Preset '{name}' exportado a {file_path}.")
            return True
        except Exception as e:
            logger.error(f"PresetManager: Error al exportar preset: {e}")
            return False

    def import_preset(self, namespace: str, file_path: str) -> str:
        """
        Importa un preset desde un archivo JSON al namespace indicado.
        Acepta tanto el formato de exportación ({nombre, ajustes}) como un
        dict plano de ajustes (usa el nombre del archivo en ese caso).
        Retorna el nombre del preset importado, o "" si falló.
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError(self.tr("El archivo no contiene un objeto JSON"))
            if "ajustes" in data and isinstance(data["ajustes"], dict):
                name = str(data.get("nombre") or os.path.splitext(os.path.basename(file_path))[0])
                settings = data["ajustes"]
                function = data.get("function")
                job_type = data.get("job_type", "RECODE")
            else:
                name = os.path.splitext(os.path.basename(file_path))[0]
                settings = data
                function = None
                job_type = "RECODE"
            self.save_preset(namespace, name, settings, function=function, job_type=job_type)
            return name
        except Exception as e:
            logger.error(f"PresetManager: Error al importar preset desde {file_path}: {e}")
            return ""


def get_preset_manager() -> PresetManager:
    """Acceso global al PresetManager (singleton)."""
    return PresetManager.get_instance()


_RECODE_COLLISION_SUFFIX = " (recodificado)"


def build_recode_output_path(input_path: str, namespace: str, preset_name: str | None,
                              prefix: str = "", suffix: str = "") -> tuple[dict | None, str | None]:
    """
    Resuelve un preset guardado en un (settings, out_file) listos para un job RECODE (ver
    QueueWorker._execute_recode / run_ffmpeg_recode en core.utils.queue_manager), a partir
    de la ruta de un archivo ya existente. Único punto que traduce "el usuario eligió el
    preset X" en "esto es lo que hay que ejecutar y dónde va a quedar" — usado tanto por la
    recodificación síncrona de cada hijo de una playlist (queue_manager._execute_playlist)
    como por la asíncrona de una descarga individual (advanced_process/download_controller.py),
    para no repetir esta traducción en cada lugar.

    input_path es siempre la ruta LIMPIA (antes de ponerla en cuarentena con
    quarantine_for_recode - el llamador es quien decide eso después) - prefix/suffix (de
    la tarjeta "Recodificar") se aplican al nombre base, y la extensión cambia según el
    contenedor del preset (ver core.utils.recode_guard.CONTAINER_TO_EXTENSION).

    Salvaguarda: si el resultado sin prefijo/sufijo terminaría siendo IDÉNTICO a
    input_path (mismo contenedor, sin texto elegido), se fuerza un sufijo por defecto -
    si no, "mantener medios originales" restauraría el .dbak sobre ese mismo nombre y
    borraría el recodificado recién creado (ver rollback_backup), que quedó ocupando esa
    ruta mientras el original estaba en cuarentena.

    Devuelve (None, None) si el preset no existe o no tiene ajustes.
    """
    if not preset_name:
        return None, None
    settings = get_preset_manager().get_settings(namespace, preset_name)
    if not settings:
        return None, None

    from core.utils.recode_guard import CONTAINER_TO_EXTENSION

    base, original_ext = os.path.splitext(input_path)
    base_dir, base_name = os.path.split(base)
    container = settings.get("container") or "same"
    ext = original_ext.lstrip(".") if container == "same" else CONTAINER_TO_EXTENSION.get(container, container)

    new_base_name = f"{prefix}{base_name}{suffix}"
    out_file = os.path.join(base_dir, f"{new_base_name}.{ext}") if ext else input_path

    if os.path.normcase(os.path.normpath(out_file)) == os.path.normcase(os.path.normpath(input_path)):
        out_file = os.path.join(base_dir, f"{new_base_name}{_RECODE_COLLISION_SUFFIX}.{ext}")

    return settings, out_file
