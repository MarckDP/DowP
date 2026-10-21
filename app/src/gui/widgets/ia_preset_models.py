# src/gui/widgets/ia_preset_models.py
"""
¿Está en disco el modelo de un preajuste de IA? Y si no, ofrecer descargarlo.

Lo usan todos los menús de preajustes de IA (Herramientas IA > Preajustes, Multimedia >
Preajustes y Posprocesar de Modo Rápido / Proceso Avanzado): al elegir un preajuste
cuyo modelo falta sale el mismo aviso que en los controles del modelo, con un botón
más, "Administrar", que abre Ajustes > Modelos (desde un menú de preajustes no están a
mano los controles del modelo).

La descarga va al gestor de siempre (model_downloads()), con la misma clave que usan
los popovers y Ajustes > Modelos, así se ve el progreso en todos lados.
"""
from PySide6.QtCore import QCoreApplication

from gui.widgets.model_download_prompt import ask_model_download, model_download_key, model_downloads


def preset_model(settings: dict | None) -> dict | None:
    """Lo necesario para hablar del motor/modelo de un preajuste y descargarlo:
    {name, info, key, installed, size, download, subject, note}. None si el preajuste
    no nombra un modelo conocido (ej. uno que ya no existe en la lista)."""
    from core.setup import models_setup
    settings = settings or {}
    function = settings.get("ia_function") or "upscale"
    if function == "upscale":
        from core.constants import UPSCALING_TOOLS
        info = UPSCALING_TOOLS.get(settings.get("upscale_engine"))
        if not info:
            return None
        return {
            "name": info["name"], "info": info, "key": model_download_key(info),
            "installed": models_setup.is_upscaling_engine_installed(info),
            "size": models_setup.get_upscaling_engine_size_bytes(info),
            "download": models_setup.download_upscaling_engine,
            "subject": QCoreApplication.translate("IAPresetModels", "motor"),
            "note": QCoreApplication.translate("IAPresetModels", "El motor trae sus propios modelos de reescalado adentro -- se "
                        "descarga una sola vez y sirve para todos los modelos de esta lista."),
        }
    if function == "depth":
        name = settings.get("depth_model")
        info = models_setup.get_depth_families().get(settings.get("depth_family"), {}).get(name)
        installed = info and models_setup.is_depth_model_installed(info)
        size = info and models_setup.get_depth_model_size_bytes(info)
        download = models_setup.download_depth_model
    else:
        name = settings.get("normals_model")
        info = models_setup.get_normal_families().get(settings.get("normals_family"), {}).get(name)
        installed = info and models_setup.is_normal_model_installed(info)
        size = info and models_setup.get_normal_model_size_bytes(info)
        download = models_setup.download_normal_model
    if not info:
        return None
    note = ""
    if models_setup.is_depth_model_noncommercial(info):
        note = QCoreApplication.translate("IAPresetModels", "Licencia {0}: solo permite uso no comercial.").format(models_setup.get_depth_model_license(info))
    return {"name": name, "info": info, "key": model_download_key(info), "installed": bool(installed),
            "size": size or 0, "download": download, "subject": QCoreApplication.translate("IAPresetModels", "modelo"), "note": note}


def preset_model_ready(settings: dict | None) -> bool:
    """El modelo del preajuste está en disco y no a medio descargar."""
    model = preset_model(settings)
    return bool(model) and model["installed"] and not model_downloads().is_downloading(model["key"])


def offer_preset_model_download(parent, settings: dict | None, notify_downloading: bool = False) -> bool:
    """True si el modelo del preajuste ya está listo. Si falta, pregunta (Descargar /
    Administrar / Cancelar), arranca la descarga si se pide, y devuelve False: hasta que
    termine no se puede iniciar el proceso. Si ya se está descargando no pregunta nada;
    con `notify_downloading` (al pulsar Iniciar/Descargar) avisa que hay que esperar."""
    model = preset_model(settings)
    if model is None or model["installed"]:
        return model is not None
    if model_downloads().is_downloading(model["key"]):
        if notify_downloading:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                parent, QCoreApplication.translate("IAPresetModels", "Descargando el modelo"),
                QCoreApplication.translate("IAPresetModels", "'{0}' se está descargando ({1}%). Podrás iniciar cuando termine.").format(
                    model["name"], model_downloads().progress(model["key"])))
        return False
    kind = {"upscale": "upscaling"}.get((settings or {}).get("ia_function") or "upscale",
                                        (settings or {}).get("ia_function"))
    choice = ask_model_download(parent, model["name"], model["size"], subject=model["subject"],
                                extra_note=model["note"], offer_manage=True,
                                manage_focus=model["info"], manage_kind=kind)
    if choice == "download":
        model_downloads().start(model["key"], model["download"], model["info"])
    return False
