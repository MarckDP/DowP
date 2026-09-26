# src/core/utils/shortcuts.py
"""Registro central de atajos de teclado.

Cada acción tiene un id estable, un nombre visible, su(s) tecla(s) por defecto y la
sección donde vive (hoy solo el Editor de Imagen). Quien use un atajo no crea
QShortcuts a mano: llama a ShortcutBinder.bind(), que los arma desde este registro y
los rehace solos cuando el usuario cambia la tecla en Ajustes > Atajos de teclado.

En la configuración solo se guardan las acciones que el usuario cambió
("shortcuts": {id: ["Ctrl+Z", ...]}), así un cambio futuro de los valores por
defecto no pisa lo personalizado. Las teclas se guardan en PortableText
("Ctrl+Shift+Z"): Qt las traduce a Cmd en macOS."""
import sys
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Qt, Signal, QT_TRANSLATE_NOOP, QCoreApplication
from PySide6.QtGui import QKeySequence, QShortcut

from core.utils.config_manager import get_config, save_config

CONFIG_KEY = "shortcuts"
_CTX = "Shortcuts"

SECTION_IMAGE_EDITOR = "image_editor"
SECTIONS = {
    SECTION_IMAGE_EDITOR: QT_TRANSLATE_NOOP("Shortcuts", "Editor de Imagen"),
}


@dataclass(frozen=True)
class ShortcutAction:
    id: str
    section: str
    name: str                      # sin traducir (QT_TRANSLATE_NOOP); ver display_name()
    defaults: tuple = field(default_factory=tuple)
    editable: bool = True

    def display_name(self) -> str:
        return QCoreApplication.translate(_CTX, self.name)


ACTIONS = [
    ShortcutAction("editor.tool.select", SECTION_IMAGE_EDITOR, QT_TRANSLATE_NOOP("Shortcuts", "Seleccionar"), ("V",)),
    ShortcutAction("editor.tool.shapes_cycle", SECTION_IMAGE_EDITOR,
                   QT_TRANSLATE_NOOP("Shortcuts", "Herramientas de forma (cambia entre Rectángulo, Elipse y Línea)"), ("U",)),
    ShortcutAction("editor.tool.rect", SECTION_IMAGE_EDITOR, QT_TRANSLATE_NOOP("Shortcuts", "Rectángulo")),
    ShortcutAction("editor.tool.ellipse", SECTION_IMAGE_EDITOR, QT_TRANSLATE_NOOP("Shortcuts", "Elipse")),
    ShortcutAction("editor.tool.line", SECTION_IMAGE_EDITOR, QT_TRANSLATE_NOOP("Shortcuts", "Línea")),
    ShortcutAction("editor.tool.brush", SECTION_IMAGE_EDITOR, QT_TRANSLATE_NOOP("Shortcuts", "Pincel"), ("B",)),
    ShortcutAction("editor.tool.eraser", SECTION_IMAGE_EDITOR, QT_TRANSLATE_NOOP("Shortcuts", "Borrador"), ("E",)),
    ShortcutAction("editor.tool.text", SECTION_IMAGE_EDITOR, QT_TRANSLATE_NOOP("Shortcuts", "Texto"), ("T",)),
    ShortcutAction("editor.tool.canvas", SECTION_IMAGE_EDITOR, QT_TRANSLATE_NOOP("Shortcuts", "Canvas"), ("C",)),
    ShortcutAction("editor.layers_panel", SECTION_IMAGE_EDITOR, QT_TRANSLATE_NOOP("Shortcuts", "Mostrar u ocultar Capas"), ("F7",)),
    ShortcutAction("editor.size_down", SECTION_IMAGE_EDITOR, QT_TRANSLATE_NOOP("Shortcuts", "Achicar herramienta"), ("[",)),
    ShortcutAction("editor.size_up", SECTION_IMAGE_EDITOR, QT_TRANSLATE_NOOP("Shortcuts", "Agrandar herramienta"), ("]",)),
    ShortcutAction("editor.nudge_left", SECTION_IMAGE_EDITOR, QT_TRANSLATE_NOOP("Shortcuts", "Mover selección a la izquierda (1 px)"), ("Left",)),
    ShortcutAction("editor.nudge_right", SECTION_IMAGE_EDITOR, QT_TRANSLATE_NOOP("Shortcuts", "Mover selección a la derecha (1 px)"), ("Right",)),
    ShortcutAction("editor.nudge_up", SECTION_IMAGE_EDITOR, QT_TRANSLATE_NOOP("Shortcuts", "Mover selección arriba (1 px)"), ("Up",)),
    ShortcutAction("editor.nudge_down", SECTION_IMAGE_EDITOR, QT_TRANSLATE_NOOP("Shortcuts", "Mover selección abajo (1 px)"), ("Down",)),
    ShortcutAction("editor.nudge_left_10", SECTION_IMAGE_EDITOR, QT_TRANSLATE_NOOP("Shortcuts", "Mover selección a la izquierda (10 px)"), ("Shift+Left",)),
    ShortcutAction("editor.nudge_right_10", SECTION_IMAGE_EDITOR, QT_TRANSLATE_NOOP("Shortcuts", "Mover selección a la derecha (10 px)"), ("Shift+Right",)),
    ShortcutAction("editor.nudge_up_10", SECTION_IMAGE_EDITOR, QT_TRANSLATE_NOOP("Shortcuts", "Mover selección arriba (10 px)"), ("Shift+Up",)),
    ShortcutAction("editor.nudge_down_10", SECTION_IMAGE_EDITOR, QT_TRANSLATE_NOOP("Shortcuts", "Mover selección abajo (10 px)"), ("Shift+Down",)),
    ShortcutAction("editor.duplicate", SECTION_IMAGE_EDITOR, QT_TRANSLATE_NOOP("Shortcuts", "Duplicar capa seleccionada"), ("Ctrl+D",)),
    ShortcutAction("editor.undo", SECTION_IMAGE_EDITOR, QT_TRANSLATE_NOOP("Shortcuts", "Deshacer"), ("Ctrl+Z",)),
    ShortcutAction("editor.redo", SECTION_IMAGE_EDITOR, QT_TRANSLATE_NOOP("Shortcuts", "Rehacer"), ("Ctrl+Shift+Z", "Ctrl+Y")),
    ShortcutAction("editor.delete_layer", SECTION_IMAGE_EDITOR, QT_TRANSLATE_NOOP("Shortcuts", "Borrar capa"),
                   ("Del", "Backspace"), editable=False),
    ShortcutAction("editor.cancel", SECTION_IMAGE_EDITOR, QT_TRANSLATE_NOOP("Shortcuts", "Cancelar / cerrar panel"),
                   ("Esc",), editable=False),
]
_BY_ID = {a.id: a for a in ACTIONS}

MAX_KEYS_PER_ACTION = 2  # tecla principal + alternativa


def action(action_id: str) -> ShortcutAction:
    return _BY_ID[action_id]


def _overrides() -> dict:
    return dict(get_config().get(CONFIG_KEY) or {})


def get_keys(action_id: str) -> list[str]:
    """Teclas actuales (PortableText) de la acción: las del usuario o las de fábrica."""
    act = _BY_ID[action_id]
    if act.editable:
        custom = _overrides().get(action_id)
        if custom is not None:
            return [k for k in custom if k][:MAX_KEYS_PER_ACTION]
    return list(act.defaults)


def get_sequences(action_id: str) -> list[QKeySequence]:
    return [QKeySequence(k, QKeySequence.PortableText) for k in get_keys(action_id)]


# Nombres de teclas para mostrar: Qt los da en inglés ("Del", "Backspace", "Left")
# porque la app no carga las traducciones propias de Qt. Las flechas van como símbolos,
# que se entienden en cualquier idioma.
_KEY_NAMES = {
    "Left": "←", "Right": "→", "Up": "↑", "Down": "↓",
    "Del": QT_TRANSLATE_NOOP("Shortcuts", "Supr"),
    "Backspace": QT_TRANSLATE_NOOP("Shortcuts", "Retroceso"),
    "Space": QT_TRANSLATE_NOOP("Shortcuts", "Espacio"),
    "Ins": QT_TRANSLATE_NOOP("Shortcuts", "Insert"),
    "PgUp": QT_TRANSLATE_NOOP("Shortcuts", "RePág"),
    "PgDown": QT_TRANSLATE_NOOP("Shortcuts", "AvPág"),
    "Home": QT_TRANSLATE_NOOP("Shortcuts", "Inicio"),
    "End": QT_TRANSLATE_NOOP("Shortcuts", "Fin"),
    "Return": "Enter",
}


def _split_portable(key: str) -> list[str]:
    # "Ctrl++" es Ctrl y la tecla "+": no se puede partir a ciegas por "+".
    if key == "+":
        return ["+"]
    if key.endswith("++"):
        return key[:-2].split("+") + ["+"]
    return key.split("+")


def native_text(key: str) -> str:
    """Tecla tal como se muestra al usuario: símbolos del sistema en macOS (⌘ ⇧),
    y en el resto "Ctrl+Shift+Z" con los nombres de teclas traducidos."""
    if sys.platform == "darwin":
        return QKeySequence(key, QKeySequence.PortableText).toString(QKeySequence.NativeText)
    parts = _split_portable(key)
    shown = []
    for part in parts:
        name = _KEY_NAMES.get(part)
        shown.append(QCoreApplication.translate(_CTX, name) if name else part)
    return "+".join(shown)


def display_keys(action_id: str) -> str:
    return " / ".join(native_text(k) for k in get_keys(action_id))


def is_customized(action_id: str) -> bool:
    return action_id in _overrides()


def find_conflict(section: str, key: str, exclude_id: str | None = None) -> str | None:
    """Id de otra acción de la misma sección que ya usa `key`, o None."""
    target = QKeySequence(key, QKeySequence.PortableText)
    for act in ACTIONS:
        if act.section != section or act.id == exclude_id:
            continue
        if any(QKeySequence(k, QKeySequence.PortableText) == target for k in get_keys(act.id)):
            return act.id
    return None


class _Registry(QObject):
    """Avisa de cambios para que los atajos vivos se rehagan sin reiniciar."""
    changed = Signal(str)   # id de la acción ("" = todas)


registry = _Registry()


def set_keys(action_id: str, keys: list[str]):
    act = _BY_ID[action_id]
    if not act.editable:
        return
    keys = [k for k in keys if k][:MAX_KEYS_PER_ACTION]
    config = get_config()
    overrides = dict(config.get(CONFIG_KEY) or {})
    if keys == list(act.defaults):
        overrides.pop(action_id, None)
    else:
        overrides[action_id] = keys
    config[CONFIG_KEY] = overrides
    save_config(config)
    registry.changed.emit(action_id)


def reset(action_id: str):
    set_keys(action_id, list(_BY_ID[action_id].defaults))


def reset_all():
    config = get_config()
    config[CONFIG_KEY] = {}
    save_config(config)
    registry.changed.emit("")


class ShortcutBinder(QObject):
    """Crea los QShortcut de un widget desde el registro y los mantiene al día.

    bind(action_id, owners, slot): un QShortcut por (owner, tecla), con contexto
    WidgetWithChildrenShortcut -- solo responden con el foco dentro de `owner`, y
    los campos de texto se quedan con las teclas que usan (ShortcutOverride).
    set_enabled(False) los apaga todos a la vez (ej. mientras se escribe texto
    sobre la imagen)."""

    def __init__(self, parent: QObject):
        super().__init__(parent)
        self._bindings = []  # [action_id, owners, slot, auto_repeat, [QShortcut]]
        self._enabled = True
        registry.changed.connect(self._on_registry_changed)

    def bind(self, action_id: str, owners, slot, auto_repeat: bool = True):
        if not isinstance(owners, (list, tuple)):
            owners = [owners]
        entry = [action_id, list(owners), slot, auto_repeat, []]
        self._bindings.append(entry)
        self._build(entry)

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        for entry in self._bindings:
            for sc in entry[4]:
                sc.setEnabled(enabled)

    def _build(self, entry):
        action_id, owners, slot, auto_repeat, shortcuts = entry
        for sc in shortcuts:
            sc.setEnabled(False)
            sc.deleteLater()
        shortcuts.clear()
        for owner in owners:
            for seq in get_sequences(action_id):
                if seq.isEmpty():
                    continue
                sc = QShortcut(seq, owner)
                sc.setContext(Qt.WidgetWithChildrenShortcut)
                sc.setAutoRepeat(auto_repeat)
                sc.setEnabled(self._enabled)
                sc.activated.connect(slot)
                shortcuts.append(sc)

    def _on_registry_changed(self, action_id: str):
        for entry in self._bindings:
            if not action_id or entry[0] == action_id:
                self._build(entry)
