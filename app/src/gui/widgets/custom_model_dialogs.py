# src/gui/widgets/custom_model_dialogs.py
"""
Eliminar un modelo importado a mano (Eliminar Fondo): lo usan Ajustes > Modelos y el
popover de Eliminar Fondo, para que en los dos sitios se pregunte lo mismo.

Un importado puede apuntar al archivo del usuario (donde él lo tiene) o ser una copia
que DowP guardó al importarlo (los de antes, o si se marcó "Copiar a la carpeta de
modelos"). En los dos casos se ofrece:
  - "Quitar de la lista" (por defecto): no toca ningún archivo.
  - "Eliminar del disco" / "Eliminar la copia de DowP": manda el archivo a la Papelera;
    si la Papelera no está disponible, pregunta antes de borrarlo para siempre.
Si el archivo ya no existe, solo se ofrece quitarlo de la lista.
"""
import os

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QMessageBox

from core.setup.models_setup import (
    get_custom_rembg_models, get_rembg_model_path, is_custom_rembg_model_external,
    remove_custom_rembg_model,
)


def confirm_remove_custom_model(parent, display_name: str) -> bool:
    """Pregunta y quita el modelo importado `display_name`. True si se quitó."""
    info = get_custom_rembg_models().get(display_name)
    if info is None:
        return False
    path = get_rembg_model_path(info)
    exists = os.path.exists(path)
    external = is_custom_rembg_model_external(info)

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Question)
    box.setWindowTitle(QCoreApplication.translate("CustomModelDialogs", "Eliminar modelo"))
    box.setText(QCoreApplication.translate("CustomModelDialogs", "Eliminar \"{0}\"").format(display_name))
    if not exists:
        box.setInformativeText(QCoreApplication.translate(
            "CustomModelDialogs", "El archivo ya no está en:\n{0}\n\nSolo se puede quitar de la lista.").format(path))
    elif external:
        box.setInformativeText(QCoreApplication.translate(
            "CustomModelDialogs",
            "Archivo: {0}\n\n\"Quitar de la lista\" no toca el archivo. \"Eliminar del disco\" "
            "lo manda a la Papelera.").format(path))
    else:
        box.setInformativeText(QCoreApplication.translate(
            "CustomModelDialogs",
            "Archivo: {0}\n\nEs la copia que DowP guardó al importarlo: tu archivo original, "
            "si todavía lo tienes, no se toca.").format(path))

    btn_remove = box.addButton(QCoreApplication.translate("CustomModelDialogs", "Quitar de la lista"), QMessageBox.AcceptRole)
    btn_delete = None
    if exists:
        label = (QCoreApplication.translate("CustomModelDialogs", "Eliminar del disco") if external
                 else QCoreApplication.translate("CustomModelDialogs", "Eliminar la copia de DowP"))
        btn_delete = box.addButton(label, QMessageBox.DestructiveRole)
        btn_delete.setProperty("variant", "danger")
    box.addButton(QCoreApplication.translate("CustomModelDialogs", "Cancelar"), QMessageBox.RejectRole)
    box.setDefaultButton(btn_remove)
    box.exec()

    clicked = box.clickedButton()
    if clicked is btn_remove:
        return remove_custom_rembg_model(display_name)[0]
    if btn_delete is None or clicked is not btn_delete:
        return False

    ok, reason = remove_custom_rembg_model(display_name, delete_file=True)
    if ok:
        return True
    if reason == "no_trash":
        answer = QMessageBox.question(
            parent, QCoreApplication.translate("CustomModelDialogs", "Eliminar modelo"),
            QCoreApplication.translate(
                "CustomModelDialogs",
                "No se pudo mandar el archivo a la Papelera (por ejemplo, en una unidad de red).\n\n"
                "¿Borrarlo para siempre?\n{0}").format(path))
        if answer == QMessageBox.Yes:
            ok, reason = remove_custom_rembg_model(display_name, delete_file=True, permanent=True)
            if ok:
                return True
        else:
            return False
    QMessageBox.warning(parent, QCoreApplication.translate("CustomModelDialogs", "Eliminar modelo"),
                        QCoreApplication.translate("CustomModelDialogs", "No se pudo eliminar el archivo: {0}").format(reason))
    return False
