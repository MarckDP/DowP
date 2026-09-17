from PySide6.QtCore import Qt, Signal, QCoreApplication
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QFileDialog,
    QMessageBox,
)

import os

from gui.widgets.combo_box import AutoPopupComboBox
from gui.dialogs.dialogs import SavePresetDialog
from core.logger.logger_manager import logger
from core.utils.preset_manager import get_preset_manager, PRESET_FUNCTIONS, UNSPECIFIED_FUNCTION_LABEL
from core.utils.watermark_builder import check_watermark_file

_NO_PRESET_DATA = None  # dato del item "Sin preset" (siempre el primero del combo)


class PresetBar(QWidget):
    """
    Barra reutilizable de presets, en dos modos según quién la use (se pueden
    combinar los dos flags, pero en la práctica cada pestaña usa uno u otro):

    - `show_save_button=True, show_picker=False` (ej. AdvancedRecodePanel): la
      pestaña donde el usuario ARMA la configuración a mano. Solo aparece el
      botón "Guardar como preajuste", que abre un diálogo para nombrarlo y lo
      guarda vía `get_settings()`. No hay combo aquí - esta pestaña nunca
      "aplica" un preset a sus propios controles.

    - `show_picker=True, show_save_button=False` (ej. PresetsPanel, la pestaña
      central "Preajustes"): la pestaña donde el usuario ELIGE qué preset usar
      para el próximo trabajo, sin pasar por la pestaña que lo creó. Aquí
      aparecen el combo (solo selección, no editable) + Exportar/Importar/
      Eliminar, pero no "Guardar" (esta pestaña no arma configuraciones
      propias, solo administra las que otras pestañas ya guardaron).

    Elegir un preset del combo NO modifica ningún otro control de la app: el
    panel host debe consultar `current_preset_settings()` al armar su trabajo
    real y usar ese diccionario tal cual si no es None.

    No sabe nada del contenido de los ajustes: cualquier panel que exponga
    `get_settings() -> dict` puede usarla para guardar, solo cambia el
    namespace (ej. "video_tools/avanzado").
    """
    preset_applied = Signal(str)  # nombre del preset activo, o "" si se deseleccionó

    def __init__(self, namespace: str, get_settings=None, parent=None,
                 show_picker: bool = True, show_save_button: bool = True,
                 default_function: str | None = None, job_type: str = "RECODE",
                 function_choices: dict | None = None):
        super().__init__(parent)
        self.namespace = namespace
        self._get_settings = get_settings
        # Metadata de categorización para lo que esta barra GUARDE (ver
        # core.utils.preset_manager.PRESET_FUNCTIONS) - default_function precarga (pero
        # no fija) la categoría en el diálogo de guardado cuando esta barra vive en una
        # pestaña con una función fija conocida (ej. una futura Convertir con guardado
        # propio pasaría "convertir" aquí); None (ej. Avanzado, que arma cualquier cosa)
        # deja el combo del diálogo sin preseleccionar nada en particular.
        self._default_function = default_function
        self._job_type = job_type
        # Qué diccionario de función ofrecer/agrupar (ver core.utils.preset_manager) --
        # None usa PRESET_FUNCTIONS (categorías de Recodificación, el caso de siempre).
        # Una barra sobre un namespace de IA (ej. "video_tools/ia_tools") pasa
        # IA_TOOL_FUNCTIONS acá para no ofrecer "Convertir"/"Comprimir" al guardar, y
        # para agrupar el picker por las categorías correctas (ver refresh()).
        self._function_choices = function_choices or PRESET_FUNCTIONS
        self._active_name = None
        self._is_picker = show_picker  # NO usar combo.isVisible(): una pestaña
        # inactiva del QTabWidget reporta isVisible()==False aunque este
        # configurada para mostrar el combo, y eso rompería el auto-refresh.

        self._init_ui(show_picker, show_save_button)
        if show_picker:
            self.refresh()
        get_preset_manager().presets_changed.connect(self._on_presets_changed)

    def _init_ui(self, show_picker: bool, show_save_button: bool):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.combo = AutoPopupComboBox(self)
        # Construido con el parent directo al constructor: el ChildAdded del filtro global de
        # cursor (HandCursorInstaller, main.py) nunca se dispara en ese caso (ver
        # advanced_recode_panel.py::_setup_fixed_combo) — se fija a mano.
        self.combo.setCursor(Qt.PointingHandCursor)
        self.combo.currentIndexChanged.connect(self._on_combo_changed)
        self.combo.setVisible(show_picker)
        layout.addWidget(self.combo)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self.btn_save = QPushButton(self.tr("Guardar como preajuste"), self)
        self.btn_save.setObjectName("secondaryButton")
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.clicked.connect(self._on_save_clicked)
        self.btn_save.setVisible(show_save_button)
        btn_row.addWidget(self.btn_save)

        self.btn_export = QPushButton(self.tr("Exportar"), self)
        self.btn_export.setObjectName("secondaryButton")
        self.btn_export.setCursor(Qt.PointingHandCursor)
        self.btn_export.clicked.connect(self._on_export_clicked)
        self.btn_export.setVisible(show_picker)
        btn_row.addWidget(self.btn_export)

        self.btn_import = QPushButton(self.tr("Importar"), self)
        self.btn_import.setObjectName("secondaryButton")
        self.btn_import.setCursor(Qt.PointingHandCursor)
        self.btn_import.clicked.connect(self._on_import_clicked)
        self.btn_import.setVisible(show_picker)
        btn_row.addWidget(self.btn_import)

        self.btn_delete = QPushButton(self.tr("Eliminar"), self)
        self.btn_delete.setObjectName("redButton")
        self.btn_delete.setCursor(Qt.PointingHandCursor)
        self.btn_delete.clicked.connect(self._on_delete_clicked)
        self.btn_delete.setVisible(show_picker)
        btn_row.addWidget(self.btn_delete)

        layout.addLayout(btn_row)

    # ─── Estado / API pública ────────────────────────────────────

    def current_preset_settings(self):
        """Ajustes del preset activo, o None si no hay ninguno seleccionado
        ("Sin preset"). El panel host debe preferir esto sobre leer sus
        propios widgets al armar un trabajo real."""
        if not self._active_name:
            return None
        return get_preset_manager().get_settings(self.namespace, self._active_name)

    def active_preset_name(self):
        return self._active_name

    def clear_selection(self):
        """Vuelve a 'Sin preset' sin disparar guardado ni nada."""
        if self.combo.currentIndex() == 0:
            return
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(0)
        self.combo.blockSignals(False)
        self._active_name = None

    # ─── Internos ────────────────────────────────────────────────

    def _add_group_header(self, title: str):
        """Encabezado no seleccionable dentro del MISMO combo (mismo patrón que
        convert_panel.py::_populate_container_combo para agrupar VIDEO/SOLO AUDIO) - a
        propósito UN solo menú con secciones adentro, no un combo de filtro aparte más
        el picker (ver conversación)."""
        self.combo.addItem(f"─── {title} ───")
        item = self.combo.model().item(self.combo.count() - 1)
        item.setEnabled(False)
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        item.setTextAlignment(Qt.AlignCenter)

    def refresh(self, select_name: str = ""):
        """Recarga la lista de presets desde el manager, agrupada por función (ver
        self._function_choices, pasado al constructor) dentro del mismo combo - un grupo
        se omite si no tiene ningún preset."""
        target = select_name or self._active_name
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem(self.tr("Sin preset"), _NO_PRESET_DATA)

        presets = get_preset_manager().list_presets(self.namespace)
        by_function = {}
        for preset in presets:
            by_function.setdefault(preset.get("function"), []).append(preset["name"])

        group_order = list(self._function_choices.items()) + [(None, UNSPECIFIED_FUNCTION_LABEL)]
        for func_id, label in group_order:
            names = by_function.get(func_id)
            if not names:
                continue
            header_text = QCoreApplication.translate("preset_manager", label)
            self._add_group_header(header_text)
            for name in names:
                display_name = QCoreApplication.translate("default_presets", name)
                if display_name == name:
                    display_name = self.tr(name)
                self.combo.addItem(f"  {display_name}", name)

        if target:
            idx = self.combo.findData(target)
            self.combo.setCurrentIndex(idx if idx >= 0 else 0)
        else:
            self.combo.setCurrentIndex(0)
        self._active_name = self.combo.currentData()
        self.combo.blockSignals(False)

    def _on_presets_changed(self, namespace: str):
        if namespace == self.namespace and self._is_picker:
            self.refresh()

    def _on_combo_changed(self, index: int):
        self._active_name = self.combo.itemData(index)
        if self._active_name:
            logger.info(f"PresetBar [{self.namespace}]: Preset '{self._active_name}' seleccionado.")
        self.preset_applied.emit(self._active_name or "")

    def _on_save_clicked(self):
        manager = get_preset_manager()
        existing = manager.list_names(self.namespace)
        dialog = SavePresetDialog(
            self, existing_names=existing, default_function=self._default_function,
            function_choices=self._function_choices,
        )
        if not dialog.exec() or not dialog.result_name:
            return
        name = dialog.result_name
        manager.save_preset(
            self.namespace, name, self._get_settings(),
            function=dialog.result_function, job_type=self._job_type,
        )

    def _on_export_clicked(self):
        if not self._active_name:
            QMessageBox.information(
                self, self.tr("Sin preset"), self.tr("Selecciona un preset de la lista para exportarlo.")
            )
            return
        name = self._active_name
        file_path, _ = QFileDialog.getSaveFileName(
            self, self.tr("Exportar Preset"), f"{name}.json", self.tr("Preset JSON (*.json)")
        )
        if file_path:
            get_preset_manager().export_preset(self.namespace, name, file_path)
            watermark_path = get_preset_manager().get_settings(self.namespace, name).get("watermark_image_path")
            if watermark_path:
                QMessageBox.information(
                    self, self.tr("Marca de agua no incluida"),
                    self.tr(
                        "Este preset usa una imagen de marca de agua ({0}); el archivo de "
                        "imagen no viaja dentro del .json exportado — compártelo aparte si "
                        "vas a usar este preset en otra PC."
                    ).format(os.path.basename(watermark_path)),
                )

    def _on_import_clicked(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Importar Preset"), "", self.tr("Preset JSON (*.json)")
        )
        if not file_path:
            return
        name = get_preset_manager().import_preset(self.namespace, file_path)
        if name:
            self.refresh(select_name=name)
            warning = check_watermark_file(get_preset_manager().get_settings(self.namespace, name))
            if warning:
                QMessageBox.warning(self, self.tr("Marca de agua no encontrada"), warning)
        else:
            QMessageBox.warning(
                self, self.tr("Error"), self.tr("No se pudo importar el preset desde el archivo seleccionado.")
            )

    def _on_delete_clicked(self):
        if not self._active_name:
            QMessageBox.information(
                self, self.tr("Sin preset"), self.tr("Selecciona un preset de la lista para eliminarlo.")
            )
            return
        name = self._active_name
        resp = QMessageBox.question(
            self,
            self.tr("Eliminar preset"),
            self.tr("¿Eliminar el preset '{0}'?").format(name),
        )
        if resp == QMessageBox.Yes:
            get_preset_manager().delete_preset(self.namespace, name)
