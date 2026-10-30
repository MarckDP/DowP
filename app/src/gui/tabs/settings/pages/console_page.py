# src/gui/tabs/settings/pages/console_page.py
import json
import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QFileDialog, QApplication
)

from core.utils.config_manager import get_config, save_config
from core.logger.logger_manager import logger
from gui.styles import set_button_variant
from gui.widgets.toggle_switch import ToggleSwitch
from gui.widgets.console_view_widget import ConsoleViewWidget
from gui.styles import get_theme_token
from gui.styles import set_themed_style


class ConsolePage(QWidget):
    """Pestaña de Ajustes con la consola en vivo de la app: captura de logs en tiempo real,
    activable/desactivable, con opción de ajustar el texto al ancho de la ventana, y acciones de
    Copiar/Exportar/Limpiar sobre el historial acumulado."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_loading = True
        self.init_ui()
        self._load_settings()
        self._is_loading = False

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(12)

        self.title_label = QLabel(self.tr("Consola"))
        self.title_label.setObjectName("settingsTitle")
        self.main_layout.addWidget(self.title_label)

        line = QFrame()
        line.setObjectName("settingsDivider")
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        self.main_layout.addWidget(line)

        # ---- Fila de cabecera: switches a la izquierda, acciones a la derecha ----
        header_row = QHBoxLayout()
        header_row.setSpacing(20)

        self.active_label = QLabel(self.tr("Consola activada"))
        self.active_label.setObjectName("settingsLabel")
        self.active_switch = ToggleSwitch()
        header_row.addWidget(self.active_label)
        header_row.addWidget(self.active_switch)

        self.wrap_label = QLabel(self.tr("Ajuste de línea"))
        self.wrap_label.setObjectName("settingsLabel")
        self.wrap_switch = ToggleSwitch()
        header_row.addWidget(self.wrap_label)
        header_row.addWidget(self.wrap_switch)

        header_row.addStretch()

        self.btn_copy = QPushButton(self.tr("Copiar"))
        self.btn_export = QPushButton(self.tr("Exportar"))
        self.btn_clear = QPushButton(self.tr("Limpiar"))
        for btn in (self.btn_copy, self.btn_export, self.btn_clear):
            btn.setFixedHeight(32)
        set_button_variant(self.btn_copy, "accent-solid")
        set_button_variant(self.btn_export, "accent-solid")
        set_button_variant(self.btn_clear, "danger")

        actions_row = QHBoxLayout()
        actions_row.setSpacing(8)
        actions_row.addWidget(self.btn_copy)
        actions_row.addWidget(self.btn_export)
        actions_row.addWidget(self.btn_clear)
        header_row.addLayout(actions_row)

        self.main_layout.addLayout(header_row)

        self.active_desc = QLabel(self.tr(
            "Desactivarla solo apaga esta vista — los logs se siguen guardando igual en el "
            "archivo de log."
        ))
        self.active_desc.setWordWrap(True)
        set_themed_style(self.active_desc, lambda: f"color: {get_theme_token('texto_tenue', '#888888')}; font-size: 11px;")
        self.main_layout.addWidget(self.active_desc)

        # Visor de la consola
        self.console_view = ConsoleViewWidget()
        self.main_layout.addWidget(self.console_view, 1)

        self.active_switch.toggled.connect(self.on_active_toggled)
        self.wrap_switch.toggled.connect(self.on_wrap_toggled)
        self.btn_copy.clicked.connect(self.on_copy_clicked)
        self.btn_export.clicked.connect(self.on_export_clicked)
        self.btn_clear.clicked.connect(self.on_clear_clicked)

    def _load_settings(self):
        config = get_config()
        active = config.get("console_capture_enabled", True)
        wrap = config.get("console_wrap_enabled", True)

        self.active_switch.setChecked(active)
        self.wrap_switch.setChecked(wrap)
        self.console_view.set_capturing(active)
        self.console_view.set_wrap_enabled(wrap)

    def on_active_toggled(self, checked):
        self.console_view.set_capturing(checked)
        if self._is_loading:
            return
        config = get_config()
        config["console_capture_enabled"] = checked
        save_config(config)
        logger.info(f"ConsolePage: Consola en vivo cambiada a: {checked}")

    def on_wrap_toggled(self, checked):
        self.console_view.set_wrap_enabled(checked)
        if self._is_loading:
            return
        config = get_config()
        config["console_wrap_enabled"] = checked
        save_config(config)

    def on_copy_clicked(self):
        entries = self.console_view.get_export_lines()
        text = "\n".join(e["line"] for e in entries)
        QApplication.clipboard().setText(text)

    def on_export_clicked(self):
        # Ruta completa: con un nombre suelto el diálogo lo resuelve contra la carpeta de
        # trabajo, que en la .app de macOS es "/" (solo lectura: "[Errno 30] Read-only
        # file system: '/dowp_console.txt'").
        from core.tabs.advanced_process.output_logic import get_default_download_path
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            self.tr("Exportar consola"),
            os.path.join(get_default_download_path(), "dowp_console.txt"),
            self.tr("Texto plano (*.txt);;JSON (*.json)")
        )
        if not path:
            return

        entries = self.console_view.get_export_lines()
        is_json = path.lower().endswith(".json") or "json" in selected_filter.lower()

        try:
            if is_json:
                if not path.lower().endswith(".json"):
                    path += ".json"
                data = [
                    {"timestamp": e["timestamp"], "level": e["level"], "message": e["message"]}
                    for e in entries
                ]
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
            else:
                if not path.lower().endswith(".txt"):
                    path += ".txt"
                with open(path, "w", encoding="utf-8") as f:
                    f.write("\n".join(e["line"] for e in entries))
            logger.info(f"ConsolePage: Consola exportada a {path}")
        except Exception as e:
            logger.error(f"ConsolePage: Error exportando la consola: {e}")

    def on_clear_clicked(self):
        self.console_view.clear_all()
