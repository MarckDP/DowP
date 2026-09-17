# src/gui/tabs/advanced_process/recode_controller.py
from PySide6.QtCore import QObject


class RecodeController(QObject):
    """
    Contraparte de SubtitleController para la tarjeta "Posprocesar": no descarga ni
    ejecuta nada por sí mismo, solo traduce entre los widgets de recode_options.py y las
    claves que viajan en request_data (descarga individual) o job.config (playlist, ver
    advanced_process_view.py::_save_current_job_options) - "recode_enabled",
    "recode_preset_name", "recode_keep_original", "recode_filename_prefix",
    "recode_filename_suffix" para la sección de Recodificación, más
    "upscale_enabled", "upscale_preset_name", "upscale_filename_prefix",
    "upscale_filename_suffix" para la de Reescalado IA (mismo criterio,
    sección aparte, combinable -- ver recode_options.py). La ejecución real
    (encolar los jobs RECODE/UPSCALE_VIDEO, cuarentena/backup, encadenado si
    corresponde) vive en cada download_controller.py -- ver
    core/tabs/video_tools/upscale_chain.py para la parte compartida.
    """
    def __init__(self, tab):
        super().__init__()
        self.tab = tab

    def collect_recode_data(self) -> dict:
        widget = self.tab.recode_options
        recode_enabled = widget.switch_recode.isChecked()
        upscale_enabled = widget.switch_upscale.isChecked()
        return {
            "recode_enabled": recode_enabled,
            "recode_preset_name": widget.preset_bar.active_preset_name() if recode_enabled else None,
            "recode_keep_original": widget.chk_keep_original.isChecked(),
            "recode_filename_prefix": widget.txt_prefix.text().strip(),
            "recode_filename_suffix": widget.txt_suffix.text().strip(),
            "upscale_enabled": upscale_enabled,
            "upscale_preset_name": widget.preset_bar_upscale.active_preset_name() if upscale_enabled else None,
            "upscale_filename_prefix": widget.txt_upscale_prefix.text().strip(),
            "upscale_filename_suffix": widget.txt_upscale_suffix.text().strip(),
        }

    def restore_recode_to_ui(self, data: dict):
        widget = self.tab.recode_options
        widget.switch_recode.blockSignals(True)
        widget.switch_recode.setChecked(bool(data.get("recode_enabled", False)))
        widget.switch_recode.blockSignals(False)
        widget._on_switch_toggled(widget.switch_recode.isChecked())

        preset_name = data.get("recode_preset_name")
        if preset_name:
            widget.preset_bar.refresh(select_name=preset_name)
        else:
            widget.preset_bar.clear_selection()

        widget.chk_keep_original.setChecked(bool(data.get("recode_keep_original", True)))
        widget.txt_prefix.setText(data.get("recode_filename_prefix", "") or "")
        if "recode_filename_suffix" in data:
            widget.txt_suffix.setText(data.get("recode_filename_suffix") if data.get("recode_filename_suffix") is not None else "_recoded")
        else:
            widget.txt_suffix.setText("_recoded")

        widget.switch_upscale.blockSignals(True)
        widget.switch_upscale.setChecked(bool(data.get("upscale_enabled", False)))
        widget.switch_upscale.blockSignals(False)
        widget._on_switch_upscale_toggled(widget.switch_upscale.isChecked())

        upscale_preset_name = data.get("upscale_preset_name")
        if upscale_preset_name:
            widget.preset_bar_upscale.refresh(select_name=upscale_preset_name)
        else:
            widget.preset_bar_upscale.clear_selection()

        widget.txt_upscale_prefix.setText(data.get("upscale_filename_prefix", "") or "")
        if "upscale_filename_suffix" in data:
            widget.txt_upscale_suffix.setText(data.get("upscale_filename_suffix") if data.get("upscale_filename_suffix") is not None else "_upscaled")
        else:
            widget.txt_upscale_suffix.setText("_upscaled")

        # preset_bar.refresh()/clear_selection() no emiten preset_applied (bloquean
        # señales), así que el resaltado del header hay que refrescarlo a mano aquí.
        widget._update_header_highlight()

    def reset_to_defaults(self):
        self.restore_recode_to_ui({
            "recode_enabled": False,
            "recode_preset_name": None,
            "recode_keep_original": True,
            "recode_filename_prefix": "",
            "recode_filename_suffix": "_recoded",
            "upscale_enabled": False,
            "upscale_preset_name": None,
            "upscale_filename_prefix": "",
            "upscale_filename_suffix": "_upscaled",
        })
