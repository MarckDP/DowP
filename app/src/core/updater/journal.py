# src/core/updater/journal.py
"""El journal describe, paso a paso, lo que un swap tiene que hacer sobre la
instalacion real -- y cuanto de eso ya se hizo. Es lo que permite reanudar
tras un corte de luz a mitad de camino sin repetir trabajo ni perder de vista
que hacer.

Construido a partir de un UpdateInfo (core/updater/update_checker.py): cada
archivo en files_to_download es un "replace", cada archivo en
extra_local_files (esta en disco, ya no esta en el manifiesto) es un
"delete". Ejecutado por swap_executor.py -- este modulo solo construye y
persiste la estructura, no toca archivos de la instalacion.
"""
import json
import os
import time

JOURNAL_FILENAME = "journal.json"

# os.replace sobre journal.json falla en Windows con WinError 5 si otro proceso lo
# tiene abierto en ese instante: un antivirus escaneando el archivo recien escrito,
# el indexador... Es transitorio, y sin reintento abortaba el swap entero en la
# primera coincidencia (reproducido). ~4,5 s en total antes de rendirse.
_REPLACE_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.4, 0.8, 1.0, 1.0, 1.0)

STATUS_PENDING = "pending"
STATUS_SWAPPING = "swapping"
STATUS_DONE = "done"
STATUS_ROLLED_BACK = "rolled_back"


def journal_path(state_dir: str) -> str:
    return os.path.join(state_dir, JOURNAL_FILENAME)


def build_journal(update_info, install_dir: str, staging_dir: str, state_dir: str,
                   relaunch_exe: str) -> dict:
    """No escribe nada a disco -- ver write_journal(). `relaunch_exe` es lo que
    el helper lanza tras aplicar el swap con exito (ruta al .exe en Windows/
    Linux, al .app en macOS)."""
    backups_dir = os.path.join(state_dir, "backups")
    operations = []

    for relpath, entry in update_info.files_to_download.items():
        native_rel = relpath.replace("/", os.sep)
        operations.append({
            "relpath": relpath,
            "action": "replace",
            "source": os.path.join(staging_dir, native_rel),
            "backup": os.path.join(backups_dir, native_rel),
            "hash": entry["hash"],  # para reanudar: si el destino ya coincide, no repetir
            "done": False,
        })

    for relpath in update_info.extra_local_files:
        native_rel = relpath.replace("/", os.sep)
        operations.append({
            "relpath": relpath,
            "action": "delete",
            "source": None,
            "backup": os.path.join(backups_dir, native_rel),
            "done": False,
        })

    return {
        "status": STATUS_PENDING,
        "install_dir": install_dir,
        "relaunch_exe": relaunch_exe,
        # Para que el helper pueda vaciar el staging tras confirmar el swap (ver
        # swap_executor.purge_staging).
        "staging_dir": staging_dir,
        "operations": operations,
    }


def write_journal(journal: dict, state_dir: str) -> None:
    """Escribe con fsync antes de devolver el control -- el journal tiene que
    sobrevivir un corte de luz tanto como los archivos que describe."""
    os.makedirs(state_dir, exist_ok=True)
    path = journal_path(state_dir)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(journal, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    for delay in _REPLACE_RETRY_DELAYS:
        try:
            os.replace(tmp_path, path)
            return
        except PermissionError:
            time.sleep(delay)
    os.replace(tmp_path, path)  # ultimo intento: si sigue bloqueado, que llegue a quien llama


def read_journal(state_dir: str) -> dict | None:
    path = journal_path(state_dir)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def clear_journal(state_dir: str) -> None:
    """Borra journal.json. NO borra backups/ -- eso es responsabilidad de
    quien confirma o hace rollback (swap_executor.py), cada uno con su propio
    momento correcto para hacerlo."""
    path = journal_path(state_dir)
    if os.path.exists(path):
        os.remove(path)
