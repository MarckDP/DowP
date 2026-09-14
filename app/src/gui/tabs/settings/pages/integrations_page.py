from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                                 QFrame, QScrollArea, QPushButton, QSizePolicy, QCheckBox, QLineEdit, QFileDialog,
                                 QApplication)
from PySide6.QtCore import Qt, QSize, Signal, QThread
from PySide6.QtGui import QIcon, QPixmap
from core.services.editor_integration_manager import EditorIntegrationManager
from core.setup import importer_setup
from core.utils.config_manager import get_config, save_config
from core.utils.paths import get_src_dir
from gui.styles import apply_folder_browse_button_style, set_button_variant
import os
import platform


class _ElevatedRemovalThread(QThread):
    """Ejecuta el borrado con permisos de administrador fuera del hilo de la interfaz.

    No es por rapidez -- el borrado en sí es instantáneo -- sino porque entre medias
    aparece el diálogo de control de cuentas de usuario y el usuario puede tardar lo que
    quiera en responder. Hacerlo en el hilo principal dejaría la ventana congelada y
    Windows acabaría marcándola como "no responde"."""

    result_ready = Signal(bool, str)

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self._path = path

    def run(self):
        ok, msg = importer_setup.remove_system_install_elevated(self._path)
        self.result_ready.emit(ok, msg)


class IntegrationsPage(QWidget):
    """Página de ajustes de Integraciones para NLEs."""

    integration_toggled = Signal(str, bool)  # (app_id, enabled)

    def __init__(self):
        super().__init__()
        self.init_ui()
        
        # Conectar al EditorIntegrationManager
        self.editor_mgr = EditorIntegrationManager.get_instance()
        if self.editor_mgr:
            self.editor_mgr.active_editor_changed.connect(self.update_adobe_status)
            self.update_adobe_status(self.editor_mgr.active_editor)

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(12)

        # Title
        self.title_label = QLabel(self.tr("Integraciones"))
        self.title_label.setObjectName("settingsTitle")
        self.main_layout.addWidget(self.title_label)

        # Divider
        line = QFrame()
        line.setObjectName("settingsDivider")
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        self.main_layout.addWidget(line)

        # Crear el QScrollArea
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")

        # Widget contenedor para el contenido del scroll
        self.scroll_content = QWidget()
        self.scroll_content.setObjectName("settingsScrollContent")
        self.scroll_content.setStyleSheet("QWidget#settingsScrollContent { background-color: transparent; }")

        # Layout para el contenido del scroll
        self.content_layout = QVBoxLayout(self.scroll_content)
        self.content_layout.setContentsMargins(0, 10, 10, 0)
        self.content_layout.setSpacing(20)
        self.content_layout.setAlignment(Qt.AlignTop)

        # --- SECCIÓN ADOBE (Premiere Pro / After Effects no existen en Linux) ---
        if platform.system() != "Linux":
            self.create_adobe_section()
            # Va después de la tarjeta de Adobe a propósito: solo tiene sentido leerla
            # habiendo visto antes qué aplicaciones hay configuradas.
            self.create_importer_section()

        # --- SECCIÓN DAVINCI (Windows, Mac y Linux) ---
        self.create_davinci_section()

        self.content_layout.addStretch(1)

        # Finalizar setup del scroll area
        self.scroll_area.setWidget(self.scroll_content)
        self.main_layout.addWidget(self.scroll_area)
        
    def create_card_frame(self):
        card = QFrame()
        card.setObjectName("settingsCard")
        return card

    def create_adobe_section(self):
        self.adobe_card = self.create_card_frame()
        card_layout = QVBoxLayout(self.adobe_card)
        card_layout.setContentsMargins(15, 15, 15, 15)
        card_layout.setSpacing(15)
        
        # Header (Title + Status)
        header_layout = QHBoxLayout()
        title = QLabel(self.tr("Adobe Premiere Pro & After Effects"))
        title.setObjectName("settingsSectionTitle")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        
        self.adobe_status_lbl = QLabel(self.tr("Desconectado"))
        self.adobe_status_lbl.setStyleSheet("color: #ff5555; font-weight: bold;")
        
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(self.adobe_status_lbl)
        card_layout.addLayout(header_layout)
        
        # Cargar configuración
        config = get_config()
        integrations = config.get('integrations', {})
        
        import platform
        is_mac = platform.system() == "Darwin"
        
        pr_detected = self.detect_adobe_path("premiere")
        ae_detected = self.detect_adobe_path("aftereffects")
        ps_detected = self.detect_adobe_path("photoshop")

        # Qué aplicaciones de Adobe hay realmente en la máquina. Lo usa la tarjeta del
        # importer para no insistirle con un panel de Adobe a quien no tiene Adobe.
        self._adobe_hosts_detected = [
            name for name, found in (
                ("Premiere Pro", pr_detected),
                ("After Effects", ae_detected),
                ("Photoshop", ps_detected),
            ) if found
        ]
        
        pr_hint = "/Applications/Adobe Premiere Pro [Versión]/Adobe Premiere Pro [Versión].app" if is_mac else r"C:\Program Files\Adobe\Adobe Premiere Pro [Versión]\Adobe Premiere Pro.exe"
        ae_hint = "/Applications/Adobe After Effects [Versión]/Adobe After Effects [Versión].app" if is_mac else r"C:\Program Files\Adobe\Adobe After Effects [Versión]\Support Files\AfterFX.exe"
        ps_hint = "/Applications/Adobe Photoshop [Versión]/Adobe Photoshop [Versión].app" if is_mac else r"C:\Program Files\Adobe\Adobe Photoshop [Versión]\Photoshop.exe"
        
        # Premiere Pro Settings
        pr_layout = self.create_app_setting(
            app_id="premiere",
            app_name="Adobe Premiere Pro",
            icon_name="premiere pro.svg",
            default_path=pr_detected,
            placeholder_hint=pr_hint,
            is_enabled=integrations.get('premiere_enabled', False),
            current_path=integrations.get('premiere_path', '')
        )
        card_layout.addLayout(pr_layout)
        
        card_layout.addSpacing(10)
        
        # After Effects Settings
        ae_layout = self.create_app_setting(
            app_id="aftereffects",
            app_name="Adobe After Effects",
            icon_name="after effects.svg",
            default_path=ae_detected,
            placeholder_hint=ae_hint,
            is_enabled=integrations.get('aftereffects_enabled', False),
            current_path=integrations.get('aftereffects_path', '')
        )
        card_layout.addLayout(ae_layout)
        
        card_layout.addSpacing(10)
        
        # Photoshop Settings
        ps_layout = self.create_app_setting(
            app_id="photoshop",
            app_name="Adobe Photoshop",
            icon_name="photoshop.svg",
            default_path=ps_detected,
            placeholder_hint=ps_hint,
            is_enabled=integrations.get('photoshop_enabled', False),
            current_path=integrations.get('photoshop_path', '')
        )
        card_layout.addLayout(ps_layout)
        
        # Description
        desc = QLabel(self.tr("Instala la extensión DowP Importer en Premiere, After Effects o Photoshop. Activa los interruptores arriba y configura la ruta para lanzar las aplicaciones desde DowP. A Photoshop solo se le envían imágenes."))
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #aaaaaa; margin-top: 10px;")
        card_layout.addWidget(desc)
        
        # Mantener referencias para estado visual (compatibilidad anterior por ahora)
        self.lbl_icon_pr = pr_layout.icon_lbl
        self.lbl_icon_ae = ae_layout.icon_lbl
        self.lbl_icon_ps = ps_layout.icon_lbl
        
        self.content_layout.addWidget(self.adobe_card)

    # ─────────────────────────────────────────────────────────────────────
    # DowP Importer (panel CEP de Adobe)
    # ─────────────────────────────────────────────────────────────────────

    def create_importer_section(self):
        """Tarjeta de instalación del DowP Importer.

        El panel viaja dentro de la app, así que instalarlo es copiar una carpeta al
        perfil del usuario: sin descarga, sin release aparte y sin permisos de
        administrador. Es opt-in a propósito, porque mucha gente usa DowP sin tocar
        Adobe; pero una vez instalado, la app lo mantiene al día sola en cada
        actualización (ver importer_setup.sync_if_installed())."""
        self.importer_card = self.create_card_frame()
        card_layout = QVBoxLayout(self.importer_card)
        card_layout.setContentsMargins(15, 15, 15, 15)
        card_layout.setSpacing(12)

        header_layout = QHBoxLayout()
        title = QLabel(self.tr("DowP Importer"))
        title.setObjectName("settingsSectionTitle")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.importer_status_lbl = QLabel()
        self.importer_status_lbl.setStyleSheet("font-weight: bold;")
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(self.importer_status_lbl)
        card_layout.addLayout(header_layout)

        self.importer_desc_lbl = QLabel()
        self.importer_desc_lbl.setWordWrap(True)
        self.importer_desc_lbl.setStyleSheet("color: #aaaaaa;")
        card_layout.addWidget(self.importer_desc_lbl)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.btn_importer_install = QPushButton()
        self.btn_importer_install.clicked.connect(self._on_install_importer)
        self.btn_importer_uninstall = QPushButton(self.tr("Desinstalar"))
        set_button_variant(self.btn_importer_uninstall, "secondary")
        self.btn_importer_uninstall.clicked.connect(self._on_uninstall_importer)
        actions.addWidget(self.btn_importer_install)
        actions.addWidget(self.btn_importer_uninstall)
        actions.addStretch()
        card_layout.addLayout(actions)

        # ── Aviso de copia antigua en la ubicación de sistema ──
        self.importer_conflict_frame = QFrame()
        self.importer_conflict_frame.setStyleSheet(
            "QFrame { border: 1px solid #ffa500; border-radius: 6px;"
            " background-color: rgba(255, 165, 0, 0.08); }"
            " QLabel { border: none; background: transparent; }"
        )
        conflict_layout = QVBoxLayout(self.importer_conflict_frame)
        conflict_layout.setContentsMargins(12, 10, 12, 10)
        conflict_layout.setSpacing(8)

        self.importer_conflict_lbl = QLabel()
        self.importer_conflict_lbl.setWordWrap(True)
        self.importer_conflict_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        conflict_layout.addWidget(self.importer_conflict_lbl)

        conflict_actions = QHBoxLayout()
        conflict_actions.setSpacing(10)
        self.btn_importer_remove_system = QPushButton(self.tr("Eliminar copia antigua"))
        set_button_variant(self.btn_importer_remove_system, "danger")
        self.btn_importer_remove_system.clicked.connect(self._on_remove_system_copy)
        self.btn_importer_copy_cmd = QPushButton(self.tr("Copiar comando"))
        set_button_variant(self.btn_importer_copy_cmd, "secondary")
        self.btn_importer_copy_cmd.clicked.connect(self._on_copy_removal_command)
        conflict_actions.addWidget(self.btn_importer_remove_system)
        conflict_actions.addWidget(self.btn_importer_copy_cmd)
        conflict_actions.addStretch()
        conflict_layout.addLayout(conflict_actions)

        card_layout.addWidget(self.importer_conflict_frame)

        self.content_layout.addWidget(self.importer_card)
        self.refresh_importer_card()

    def refresh_importer_card(self):
        """Relee el estado real del disco y repinta la tarjeta.

        Toda la lógica de decisión vive en importer_setup.get_status(); aquí solo se
        traduce a texto y botones."""
        if not hasattr(self, "importer_card"):
            return

        status = importer_setup.get_status()
        self._importer_status = status
        bundled = status["bundled_version"]
        state = status["state"]

        if state == "unsupported":
            self.importer_status_lbl.setText(self.tr("No disponible"))
            self.importer_status_lbl.setStyleSheet("color: #aaaaaa; font-weight: bold;")
            self.importer_desc_lbl.setText(
                self.tr("Las extensiones de Adobe no existen en este sistema."))
            self.btn_importer_install.setVisible(False)
            self.btn_importer_uninstall.setVisible(False)
            self.importer_conflict_frame.setVisible(False)
            return

        base_desc = self.tr(
            "Panel para Premiere Pro, After Effects y Photoshop. Se instala en tu perfil de "
            "usuario, sin permisos de administrador, y se actualiza junto con DowP."
        )
        no_adobe = not getattr(self, "_adobe_hosts_detected", [])

        if state == "not_installed":
            self.importer_status_lbl.setText(self.tr("No instalado"))
            self.importer_status_lbl.setStyleSheet("color: #aaaaaa; font-weight: bold;")
            self.btn_importer_uninstall.setVisible(False)
            if no_adobe:
                # Sin Adobe en la máquina el panel no sirve de nada: se deja disponible
                # pero sin empujar, que es justo lo contrario de un aviso insistente.
                self.btn_importer_install.setText(self.tr("Instalar de todos modos"))
                set_button_variant(self.btn_importer_install, "secondary")
                desc = base_desc + "\n\n" + self.tr(
                    "No se detectaron aplicaciones de Adobe en este equipo, así que "
                    "probablemente no lo necesites.")
            else:
                self.btn_importer_install.setText(self.tr("Instalar DowP Importer"))
                set_button_variant(self.btn_importer_install, "primary")
                desc = base_desc + "\n\n" + self.tr("Detectado: {0}.").format(
                    ", ".join(self._adobe_hosts_detected))

        elif state == "up_to_date":
            self.importer_status_lbl.setText(self.tr("Instalado · v{0}").format(bundled))
            self.importer_status_lbl.setStyleSheet("color: #55d17c; font-weight: bold;")
            self.btn_importer_install.setText(self.tr("Reinstalar"))
            set_button_variant(self.btn_importer_install, "secondary")
            self.btn_importer_uninstall.setVisible(True)
            desc = base_desc + "\n\n" + self.tr("Instalado en: {0}").format(status["install_dir"])

        else:  # outdated
            installed_ver = status["user_install"]["version"]
            self.importer_status_lbl.setText(self.tr("Desactualizado · v{0}").format(installed_ver))
            self.importer_status_lbl.setStyleSheet("color: #ffa500; font-weight: bold;")
            self.btn_importer_install.setText(self.tr("Actualizar a v{0}").format(bundled))
            set_button_variant(self.btn_importer_install, "primary")
            self.btn_importer_uninstall.setVisible(True)
            desc = base_desc + "\n\n" + self.tr(
                "El panel instalado es la v{0} y DowP trae la v{1}.").format(installed_ver, bundled)

        self.btn_importer_install.setVisible(True)
        self.importer_desc_lbl.setText(desc)

        system_installs = status["system_installs"]
        self.importer_conflict_frame.setVisible(bool(system_installs))
        if system_installs:
            paths = "\n".join(f"    {i['path']}  (v{i['version']})" for i in system_installs)
            self.importer_conflict_lbl.setText(
                self.tr("Hay una instalación antigua para todo el sistema. Declara el mismo "
                        "identificador que la nueva, así que Adobe podría cargar dos paneles a "
                        "la vez o quedarse con el viejo. Conviene quitarla:") + "\n" + paths)

    def _adobe_running_names(self):
        """Aplicaciones de Adobe abiertas ahora mismo, según el monitor de procesos que
        ya mantiene EditorIntegrationManager."""
        mgr = EditorIntegrationManager.get_instance()
        if not mgr:
            return []
        labels = {"premiere": "Premiere Pro", "aftereffects": "After Effects",
                  "photoshop": "Photoshop"}
        return [labels[key] for key, running in (mgr.process_status or {}).items()
                if running and key in labels]

    def _confirm_with_adobe_open(self, action_text):
        """Avisa si hay Adobe abierto antes de tocar la carpeta de extensiones.

        CEP lee el manifiesto al cargar la extensión y no lo relee hasta que se reinicia
        el host, así que cambiar los archivos con Adobe abierto deja el panel en un
        estado a medias hasta el siguiente arranque."""
        from gui.dialogs.dialogs import show_warning_confirm
        running = self._adobe_running_names()
        if not running:
            return True
        return show_warning_confirm(
            self,
            self.tr("Adobe está abierto"),
            self.tr("{0} está abierto. Para {1} conviene cerrarlo primero; si continúas, "
                    "tendrás que reiniciarlo de todos modos.\n\n¿Continuar?")
            .format(", ".join(running), action_text),
        )

    def _on_install_importer(self):
        from gui.dialogs.dialogs import show_info, show_warning
        if not self._confirm_with_adobe_open(self.tr("instalar el panel")):
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            ok, msg = importer_setup.install()
        finally:
            QApplication.restoreOverrideCursor()
        self.refresh_importer_card()
        (show_info if ok else show_warning)(self, self.tr("DowP Importer"), msg)

    def _on_uninstall_importer(self):
        from gui.dialogs.dialogs import show_info, show_warning, show_warning_confirm
        if not show_warning_confirm(
            self, self.tr("Desinstalar DowP Importer"),
            self.tr("Se eliminará el panel de Adobe. Podrás volver a instalarlo desde aquí "
                    "cuando quieras.\n\n¿Continuar?")
        ):
            return
        if not self._confirm_with_adobe_open(self.tr("desinstalar el panel")):
            return
        ok, msg = importer_setup.uninstall()
        self.refresh_importer_card()
        (show_info if ok else show_warning)(self, self.tr("DowP Importer"), msg)

    def _on_remove_system_copy(self):
        from gui.dialogs.dialogs import show_warning_confirm
        installs = (getattr(self, "_importer_status", {}) or {}).get("system_installs") or []
        if not installs:
            return
        path = installs[0]["path"]
        if not show_warning_confirm(
            self, self.tr("Eliminar copia antigua"),
            self.tr("Se pedirán permisos de administrador para eliminar:\n\n{0}\n\n"
                    "Es la única operación de DowP que los necesita.\n\n¿Continuar?").format(path)
        ):
            return
        self.btn_importer_remove_system.setEnabled(False)
        self.btn_importer_remove_system.setText(self.tr("Esperando permisos..."))
        self._removal_thread = _ElevatedRemovalThread(path, self)
        self._removal_thread.result_ready.connect(self._on_system_copy_removed)
        self._removal_thread.start()

    def _on_system_copy_removed(self, ok, msg):
        from gui.dialogs.dialogs import show_info, show_warning
        self.btn_importer_remove_system.setEnabled(True)
        self.btn_importer_remove_system.setText(self.tr("Eliminar copia antigua"))
        self.refresh_importer_card()
        (show_info if ok else show_warning)(self, self.tr("DowP Importer"), msg)

    def _on_copy_removal_command(self):
        from gui.dialogs.dialogs import show_info
        installs = (getattr(self, "_importer_status", {}) or {}).get("system_installs") or []
        if not installs:
            return
        cmd = importer_setup.get_elevated_removal_command(installs[0]["path"])
        QApplication.clipboard().setText(cmd)
        show_info(self, self.tr("Comando copiado"),
                  self.tr("Pégalo en una terminal abierta como administrador:\n\n{0}").format(cmd))

    def showEvent(self, event):
        """Reevalúa el estado del panel cada vez que se abre la página: pudo cambiar por
        una actualización de DowP o porque el usuario borró la carpeta a mano."""
        super().showEvent(event)
        self.refresh_importer_card()

    def create_davinci_section(self):
        self.davinci_card = self.create_card_frame()
        card_layout = QVBoxLayout(self.davinci_card)
        card_layout.setContentsMargins(15, 15, 15, 15)
        card_layout.setSpacing(15)
        
        # Header
        header_layout = QHBoxLayout()
        title = QLabel(self.tr("DaVinci Resolve"))
        title.setObjectName("settingsSectionTitle")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        
        self.davinci_status_lbl = QLabel(self.tr("Desconectado"))
        self.davinci_status_lbl.setStyleSheet("color: #ff5555; font-weight: bold;")
        
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(self.davinci_status_lbl)
        card_layout.addLayout(header_layout)
        
        # Cargar configuración
        config = get_config()
        integrations = config.get('integrations', {})
        
        sys_name = platform.system()
        dv_detected = self.detect_davinci_path()
        if sys_name == "Darwin":
            dv_hint = "/Applications/DaVinci Resolve/DaVinci Resolve.app"
        elif sys_name == "Linux":
            dv_hint = "/opt/resolve/bin/resolve"
        else:
            dv_hint = r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe"
        
        dv_layout = self.create_app_setting(
            app_id="davinci",
            app_name="DaVinci Resolve",
            icon_name="davinci resolve.svg",
            default_path=dv_detected or dv_hint,
            placeholder_hint=dv_hint,
            is_enabled=integrations.get('davinci_enabled', False),
            current_path=integrations.get('davinci_path', '')
        )
        card_layout.addLayout(dv_layout)
        
        # Configuración adicional de DaVinci (Timeline, Carpetas, etc)
        settings_layout = QVBoxLayout()
        settings_layout.setContentsMargins(40, 10, 0, 0)
        settings_layout.setSpacing(10)
        
        self.cb_dv_timeline = QCheckBox(self.tr("Importar automáticamente a la línea de tiempo (Playhead)"))
        self.cb_dv_timeline.setChecked(integrations.get('davinci_import_timeline', True))
        self.cb_dv_timeline.toggled.connect(lambda checked: self._save_integration_setting("davinci", "import_timeline", checked))
        settings_layout.addWidget(self.cb_dv_timeline)
        
        self.cb_dv_images_timeline = QCheckBox(self.tr("Importar también imágenes a la línea de tiempo"))
        self.cb_dv_images_timeline.setChecked(integrations.get('davinci_import_images_timeline', False))
        self.cb_dv_images_timeline.toggled.connect(lambda checked: self._save_integration_setting("davinci", "import_images_timeline", checked))
        settings_layout.addWidget(self.cb_dv_images_timeline)
        
        self.cb_dv_folders = QCheckBox(self.tr("Crear estructura de carpetas (DowP Imports / Audio / Video)"))
        self.cb_dv_folders.setChecked(integrations.get('davinci_create_folders', True))
        self.cb_dv_folders.toggled.connect(lambda checked: self._save_integration_setting("davinci", "create_folders", checked))
        settings_layout.addWidget(self.cb_dv_folders)
        
        card_layout.addLayout(settings_layout)
        
        desc = QLabel(self.tr("La integración de DaVinci usa la API nativa de scripting. Asegúrate de tener DaVinci abierto y permitir scripts (Preferencias -> Sistema -> General -> External scripting = Local)."))
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #aaaaaa; margin-top: 10px;")
        card_layout.addWidget(desc)
        
        self.content_layout.addWidget(self.davinci_card)
        self.lbl_icon_dv = dv_layout.icon_lbl
        
    def detect_adobe_path(self, app_id):
        """Busca y devuelve la versión instalada más reciente de Premiere Pro o After Effects."""
        import platform
        import re
        sys_name = platform.system()

        def extract_version_score(text, filepath=""):
            # 1. Buscar año de 4 dígitos (ej: 2026, 2025, 2024...)
            year_match = re.search(r'(20\d\d)', text)
            if year_match:
                return int(year_match.group(1)) * 1000
            # 2. Buscar versión numérica (ej: 25.0, 24.1...)
            ver_match = re.search(r'(\d+(?:\.\d+)?)', text)
            if ver_match:
                try:
                    return int(float(ver_match.group(1)) * 10)
                except ValueError:
                    pass
            # 3. Fallback a la fecha de modificación del archivo
            if filepath and os.path.exists(filepath):
                try:
                    return int(os.path.getmtime(filepath) // 86400)
                except Exception:
                    pass
            return 1000

        candidates = []

        # Datos por app en vez de ternarios encadenados: al sumar Photoshop, "el que no es
        # Premiere es After Effects" dejaba de ser cierto.
        ADOBE_APPS = {
            "premiere":     {"exe": "Adobe Premiere Pro.exe", "reg": "Adobe Premiere Pro.exe",
                             "keyword": "premiere pro", "mac": "Adobe Premiere Pro"},
            "aftereffects": {"exe": "Support Files\\AfterFX.exe", "reg": "AfterFX.exe",
                             "keyword": "after effects", "mac": "Adobe After Effects"},
            "photoshop":    {"exe": "Photoshop.exe", "reg": "Photoshop.exe",
                             "keyword": "photoshop", "mac": "Adobe Photoshop"},
        }
        app_info = ADOBE_APPS.get(app_id)
        if not app_info:
            return ""

        if sys_name == 'Windows':
            exe_name = app_info["exe"]
            target_keyword = app_info["keyword"]

            # Paso 1: Consultar el Registro de Windows (App Paths registra la versión activa principal)
            try:
                import winreg
                reg_exe = app_info["reg"]
                for root_key in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                    try:
                        with winreg.OpenKey(root_key, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{reg_exe}") as key:
                            val, _ = winreg.QueryValueEx(key, "")
                            if val:
                                val = val.strip('"\'' )
                                if os.path.exists(val):
                                    score = extract_version_score(val, val)
                                    candidates.append((score, val))
                    except Exception:
                        pass
            except Exception:
                pass

            # Paso 2: Escanear Program Files en discos comunes
            possible_roots = [os.environ.get("ProgramFiles", r"C:\Program Files")]
            for drive in ("C", "D", "E"):
                d_path = f"{drive}:\\Program Files"
                if d_path not in possible_roots and os.path.exists(d_path):
                    possible_roots.append(d_path)

            for pf in possible_roots:
                adobe_base = os.path.join(pf, "Adobe")
                if not os.path.exists(adobe_base):
                    continue
                try:
                    for item in os.listdir(adobe_base):
                        if target_keyword in item.lower():
                            full_exe = os.path.join(adobe_base, item, exe_name)
                            if os.path.exists(full_exe):
                                score = extract_version_score(item, full_exe)
                                candidates.append((score, full_exe))
                except Exception:
                    pass

        elif sys_name == 'Darwin':
            target_keyword = app_info["keyword"]

            # Paso 1: Spotlight (mdfind) para localizar bundles .app al instante
            try:
                import subprocess
                kw_query = app_info["mac"]
                out = subprocess.check_output(['mdfind', f'kMDItemFSName == "{kw_query}*.app"'], text=True, errors='ignore').strip()
                for line in out.splitlines():
                    path = line.strip()
                    if path.endswith(".app") and os.path.exists(path):
                        score = extract_version_score(path, path)
                        candidates.append((score, path))
            except Exception:
                pass

            # Paso 2: Escanear /Applications y ~/Applications
            for base_apps in ("/Applications", os.path.expanduser("~/Applications")):
                if not os.path.exists(base_apps):
                    continue
                try:
                    for item in os.listdir(base_apps):
                        if target_keyword in item.lower():
                            full_item = os.path.join(base_apps, item)
                            if item.endswith(".app") and os.path.exists(full_item):
                                score = extract_version_score(item, full_item)
                                candidates.append((score, full_item))
                            elif os.path.isdir(full_item):
                                for sub in os.listdir(full_item):
                                    if target_keyword in sub.lower() and sub.endswith(".app"):
                                        app_bundle = os.path.join(full_item, sub)
                                        score = extract_version_score(item + " " + sub, app_bundle)
                                        candidates.append((score, app_bundle))
                except Exception:
                    pass

        if candidates:
            # Eliminar duplicados y ordenar por versión/año descendente
            seen = set()
            unique_candidates = []
            for score, path in candidates:
                norm = os.path.normpath(path)
                if norm not in seen:
                    seen.add(norm)
                    unique_candidates.append((score, norm))
            unique_candidates.sort(key=lambda x: x[0], reverse=True)
            return unique_candidates[0][1]

        return ""

    def detect_davinci_path(self):
        sys_name = platform.system()
        if sys_name == 'Windows':
            candidates = [
                r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe",
            ]
            for c in candidates:
                if os.path.exists(c):
                    return c
        elif sys_name == 'Darwin':
            candidates = [
                "/Applications/DaVinci Resolve/DaVinci Resolve.app",
                "/Applications/DaVinci Resolve Studio/DaVinci Resolve Studio.app",
                "/Applications/DaVinci Resolve.app",
            ]
            for c in candidates:
                if os.path.exists(c):
                    return c
        elif sys_name == 'Linux':
            candidates = [
                "/opt/resolve/bin/resolve",
                "/home/resolve/bin/resolve",
            ]
            for c in candidates:
                if os.path.exists(c):
                    return c
        return ""
        
    def create_app_setting(self, app_id, app_name, icon_name, default_path, is_enabled, current_path, placeholder_hint=""):
        layout = QVBoxLayout()
        layout.setSpacing(8)
        
        # Top row: Checkbox + Icon
        top_row = QHBoxLayout()
        
        icon_lbl = QLabel()
        icon_lbl.setFixedSize(32, 32)
        self.set_icon(icon_lbl, icon_name, opacity=1.0 if is_enabled else 0.3)
        
        checkbox = QCheckBox(self.tr("Activar acceso directo a {0}").format(app_name))
        checkbox.setChecked(is_enabled)
        checkbox.setStyleSheet("font-weight: bold; font-size: 14px;")
        
        top_row.addWidget(icon_lbl)
        top_row.addWidget(checkbox)
        top_row.addStretch()
        layout.addLayout(top_row)
        
        # Bottom row: Path input
        path_row = QHBoxLayout()
        path_row.setContentsMargins(40, 0, 0, 0) # Indent
        
        path_input = QLineEdit()
        placeholder = default_path or placeholder_hint or self.tr("Seleccionar ruta...")
        path_input.setPlaceholderText(placeholder)
        path_input.setText(current_path)
        
        # Autodetect if empty and enabled and default_path exists on disk
        if is_enabled and not current_path and default_path and os.path.exists(default_path):
            path_input.setText(default_path)
            self._save_integration_setting(app_id, "path", default_path)
            
        path_input.textChanged.connect(lambda text: self._save_integration_setting(app_id, "path", text))
        
        btn_browse = QPushButton()
        btn_browse.setFixedSize(32, 32)
        btn_browse.setCursor(Qt.PointingHandCursor)
        apply_folder_browse_button_style(btn_browse, self.tr("Seleccionar ejecutable"))
        btn_browse.clicked.connect(lambda: self._browse_exe(app_id, path_input))
        
        path_row.addWidget(QLabel(self.tr("Ruta:")))
        path_row.addWidget(path_input, 1)
        path_row.addWidget(btn_browse)
        layout.addLayout(path_row)
        
        # Connect checkbox
        checkbox.toggled.connect(lambda checked: self._on_app_toggled(app_id, checked, icon_lbl, path_input, btn_browse, default_path))
        path_input.setEnabled(is_enabled)
        btn_browse.setEnabled(is_enabled)
        
        # Attach icon_lbl to layout object for later reference
        layout.icon_lbl = icon_lbl
        
        return layout
        
    def _browse_exe(self, app_id, line_edit):
        sys_name = platform.system()
        if sys_name == "Darwin":
            start_dir = "/Applications"
            filter_str = self.tr("Aplicaciones (*.app);;Todos los archivos (*)")
        elif sys_name == "Linux":
            start_dir = "/opt/resolve/bin" if os.path.exists("/opt/resolve/bin") else "/opt"
            filter_str = self.tr("Todos los archivos (*)")
        else:
            start_dir = "C:\\Program Files"
            filter_str = self.tr("Ejecutables (*.exe);;Todos los archivos (*.*)")
        file_path, _ = QFileDialog.getOpenFileName(self, self.tr("Seleccionar Ejecutable"), start_dir, filter_str)
        if file_path:
            file_path = os.path.normpath(file_path)
            line_edit.setText(file_path)
            self._save_integration_setting(app_id, "path", file_path)
            
    def _on_app_toggled(self, app_id, checked, icon_lbl, path_input, btn_browse, default_path):
        self._save_integration_setting(app_id, "enabled", checked)
        self.set_icon(icon_lbl, icon_lbl.property("icon_name") or f"{app_id}.svg", opacity=1.0 if checked else 0.3)
        path_input.setEnabled(checked)
        btn_browse.setEnabled(checked)
        
        # Auto-fill if enabling and empty and path exists
        if checked and not path_input.text() and default_path and os.path.exists(default_path):
            path_input.setText(default_path)

        # Notificar a la ventana principal para que el ícono en la esquina superior
        # derecha aparezca/desaparezca de inmediato, sin requerir reiniciar la app.
        self.integration_toggled.emit(app_id, checked)

    def _save_integration_setting(self, app_id, key, value):
        config = get_config()
        if 'integrations' not in config:
            config['integrations'] = {}
            
        config_key = f"{app_id}_{key}"
        config['integrations'][config_key] = value
        save_config(config)
        
    def set_icon(self, label, icon_name, opacity=1.0, size=32):
        # Asegurar que el icono existe
        label.setProperty("icon_name", icon_name) # Guardar nombre para restaurar luego
        icon_path = os.path.join(get_src_dir(), "assets", "icons", "svg", icon_name)
        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path).scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            label.setPixmap(pixmap)
            
            from PySide6.QtWidgets import QGraphicsOpacityEffect
            effect = QGraphicsOpacityEffect(label)
            effect.setOpacity(opacity)
            label.setGraphicsEffect(effect)

    # Apps Adobe con panel en esta tarjeta: id -> (etiqueta, atributo del icono, svg).
    # Antes esto eran ramas if/elif por app; con tres ya no escalaba.
    ADOBE_STATUS_APPS = {
        'premiere':     ("Premiere Pro",  'lbl_icon_pr', "premiere pro.svg"),
        'aftereffects': ("After Effects", 'lbl_icon_ae', "after effects.svg"),
        'photoshop':    ("Photoshop",     'lbl_icon_ps', "photoshop.svg"),
    }

    def update_adobe_status(self, active_editor):
        if not hasattr(self, 'lbl_icon_pr'):
            # Sección Adobe no creada (Linux: las apps de Adobe no existen)
            return

        info = self.ADOBE_STATUS_APPS.get(active_editor)
        if info:
            self.adobe_status_lbl.setText(self.tr("Conectado ({0})").format(info[0]))
            self.adobe_status_lbl.setStyleSheet("color: #55ff55; font-weight: bold;")
        else:
            self.adobe_status_lbl.setText(self.tr("Desconectado"))
            self.adobe_status_lbl.setStyleSheet("color: #ff5555; font-weight: bold;")

        for app_id, (_label, attr, svg) in self.ADOBE_STATUS_APPS.items():
            label = getattr(self, attr, None)
            if label is not None:
                self.set_icon(label, svg, opacity=1.0 if app_id == active_editor else 0.3)

    def force_target(self, target_app):
        from gui.dialogs.dialogs import show_info
        if self.editor_mgr:
            success = self.editor_mgr.force_adobe_target(target_app)
            if not success:
                show_info(self, self.tr("DowP Importer"), self.tr("No se detecta conexión con {0}. Asegúrate de tener la extensión abierta.").format(target_app))

