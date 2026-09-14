# src/core/updater/swap_executor.py
"""Aplica y deshace un journal (core/updater/journal.py) sobre la instalacion
real. Solo stdlib + hash_tree -- este modulo lo ejecuta el helper de swap
(app/updater_helper.py), que no lleva ni requests ni zstandard ni
pycryptodomex: para cuando llega aqui, los objetos ya estan descargados,
descomprimidos y verificados en staging (pieza 2); esto solo los MUEVE.

Cada operacion se marca "done" y se persiste en el journal en cuanto se
completa -- la unidad de trabajo perdible ante un corte de luz es UNA
operacion, nunca el journal entero. Reanudar (llamar apply_journal otra vez
sobre un journal a medias) es seguro: las operaciones ya "done" se saltan, y
las que no lo estan se comprueban por hash antes de repetir nada.
"""
import os
import platform
import shutil

from core.logger.logger_manager import logger
from core.updater.hash_tree import hash_file
from core.updater.journal import STATUS_DONE, STATUS_ROLLED_BACK, STATUS_SWAPPING, write_journal


class SwapError(Exception):
    """Una operacion se aplico pero el resultado no coincide con lo esperado.
    Quien llama a apply_journal debe atrapar esto y llamar a
    rollback_journal -- nunca dejar la instalacion en un estado a medias."""


def find_app_bundle_root(path: str):
    """Busca un directorio *.app subiendo desde `path` (hasta 4 niveles) --
    cubre tanto install_dir == el propio .app como install_dir apuntando a
    Contents/MacOS dentro de el. Devuelve None si no encuentra ninguno.

    Publica (no `_privada`) porque `launcher.install_dir_from_executable()`
    tambien la usa: es la misma pregunta ("¿donde esta la raiz del bundle?")
    que resuelve tanto "que .app hay que re-firmar tras un swap" como "cual
    es el install_dir real de una instalacion macOS en marcha" (ver
    ACTUALIZACIONES.md, seccion de la particion Frameworks/Resources)."""
    current = os.path.abspath(path)
    for _ in range(4):
        if current.lower().endswith(".app"):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent
    return None


# Que hizo cada operacion sobre la instalacion, guardado en op["result"] -- es lo
# unico que rollback_journal usa para deshacer. Sin esto el rollback borraba el
# destino de TODA operacion "done" y solo restauraba si habia backup: los archivos
# que ya coincidian (noop, sin backup) desaparecian. En un diff por chunks son la
# mayoria -- verificado: un rollback real dejo 113 archivos borrados, Cryptodome
# incluido, y la instalacion inservible.
RESULT_NOOP = "noop"          # ya estaba correcto: no se toco nada
RESULT_CREATED = "created"    # no existia: se coloco uno nuevo (deshacer = quitarlo)
RESULT_REPLACED = "replaced"  # existia: el original quedo en backup (deshacer = restaurarlo)
RESULT_DELETED = "deleted"    # existia y se quito: el original quedo en backup


def _move_to_backup(dest: str, backup: str) -> None:
    os.makedirs(os.path.dirname(backup), exist_ok=True)
    if os.path.exists(backup):
        os.remove(backup)  # backup de un intento anterior a medias
    shutil.move(dest, backup)


def _apply_one(op: dict, install_dir: str) -> None:
    """Aplica una operacion y anota en op["result"] lo que hizo EN CUANTO lo hace,
    antes del paso siguiente: si esta misma operacion falla a mitad (colocar el
    archivo nuevo, hash que no coincide), rollback_journal igual sabe que el
    original quedo en backup y lo restaura."""
    dest = os.path.join(install_dir, op["relpath"].replace("/", os.sep))
    has_backup = os.path.exists(op["backup"])

    if op["action"] == "replace":
        if os.path.exists(dest) and hash_file(dest) == op["hash"]:
            # Ya esta correcto. Con backup presente es una reanudacion: un intento
            # anterior ya movio el original y coloco este -- hay que poder restaurarlo.
            op["result"] = RESULT_REPLACED if has_backup else RESULT_NOOP
            return
        if os.path.exists(dest):
            _move_to_backup(dest, op["backup"])
            op["result"] = RESULT_REPLACED
        elif has_backup:
            op["result"] = RESULT_REPLACED  # reanudacion: el original ya estaba en backup
        else:
            op["result"] = RESULT_CREATED
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(op["source"], dest)
        if hash_file(dest) != op["hash"]:
            raise SwapError(f"Hash no coincide tras colocar {op['relpath']}")
        return

    # action == "delete"
    if os.path.exists(dest):
        _move_to_backup(dest, op["backup"])
        op["result"] = RESULT_DELETED
    elif has_backup:
        op["result"] = RESULT_DELETED  # reanudacion: ya se habia movido a backup
    else:
        op["result"] = RESULT_NOOP


def apply_journal(journal: dict, state_dir: str) -> None:
    """Lanza SwapError (o cualquier excepcion de E/S) si algo falla -- quien
    llama debe capturarla y ejecutar rollback_journal sobre el mismo journal."""
    journal["status"] = STATUS_SWAPPING
    write_journal(journal, state_dir)

    install_dir = journal["install_dir"]
    for op in journal["operations"]:
        if op["done"]:
            continue
        _apply_one(op, install_dir)
        op["done"] = True
        write_journal(journal, state_dir)

    if platform.system() == "Darwin":
        from core.updater.macos_sign import SigningError, adhoc_sign
        bundle = find_app_bundle_root(install_dir)
        if bundle:
            try:
                adhoc_sign(bundle)
            except SigningError as e:
                raise SwapError(f"No se pudo re-firmar {bundle} tras el swap: {e}")
        else:
            logger.warning(f"Updater: no se encontro un .app dentro de {install_dir}, se omite la re-firma.")

    journal["status"] = STATUS_DONE
    write_journal(journal, state_dir)


def _rollback_one(op: dict, install_dir: str) -> None:
    dest = os.path.join(install_dir, op["relpath"].replace("/", os.sep))
    result = op.get("result")

    if result == RESULT_NOOP:
        return
    if result is None:
        # Journal escrito por una version que no guardaba "result": no se sabe si el
        # archivo existia antes. Regla segura -- nunca borrar sin tener con que
        # reponerlo: solo se deshace si hay backup.
        if not os.path.exists(op["backup"]):
            return
        result = RESULT_REPLACED

    if result in (RESULT_CREATED, RESULT_REPLACED) and os.path.exists(dest):
        os.remove(dest)
    if result in (RESULT_REPLACED, RESULT_DELETED) and os.path.exists(op["backup"]):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.exists(dest):
            os.remove(dest)
        shutil.move(op["backup"], dest)


def rollback_journal(journal: dict, state_dir: str) -> None:
    """Deshace, en orden inverso, exactamente lo que registro op["result"]. Cubre
    tambien la operacion que fallo a mitad (tiene "result" pero no "done").
    Idempotente: una operacion ya deshecha pierde "done" y "result" y se salta."""
    install_dir = journal["install_dir"]
    for op in reversed(journal["operations"]):
        if not op["done"] and "result" not in op:
            continue  # nunca llego a tocarse
        _rollback_one(op, install_dir)
        op["done"] = False
        op.pop("result", None)

    journal["status"] = STATUS_ROLLED_BACK
    write_journal(journal, state_dir)


def purge_backups(state_dir: str) -> None:
    """Confirma un swap exitoso: borra los backups, ya no hacen falta."""
    backups_dir = os.path.join(state_dir, "backups")
    if os.path.exists(backups_dir):
        shutil.rmtree(backups_dir, ignore_errors=True)


def purge_staging(journal: dict) -> None:
    """Confirma un swap exitoso: vacia el staging de descarga. Ahi quedaban los
    archivos que se bajaron por venir en un chunk "sucio" pero que ya coincidian con
    la instalacion (_apply_one no los mueve) -- medido: 923 archivos, 84 MB tras una
    sola actualizacion, acumulandose en cada una.

    Solo borra una carpeta llamada exactamente "update_staging" (la de
    core.utils.paths.get_update_staging_dir): un journal sin esa clave, o con una
    ruta inesperada, no borra nada."""
    staging_dir = journal.get("staging_dir")
    if not staging_dir or os.path.basename(os.path.normpath(staging_dir)) != "update_staging":
        return
    if os.path.isdir(staging_dir):
        shutil.rmtree(staging_dir, ignore_errors=True)
