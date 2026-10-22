import os
import sys

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                                 QStackedWidget, QButtonGroup, QPushButton, QFrame, QApplication)
from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from core.utils.i18n import logger

from core.updater.update_service import UpdateCheckWorker, UpdateDownloadWorker
from core.version import UPDATE_REPO, get_display_version
from gui.widgets.circular_progress import CircularProgress

from .pages.general_page import GeneralPage
from .pages.memory_cache_page import MemoryCachePage
from .pages.downloads_page import DownloadsPage
from .pages.cookies_page import CookiesPage
from .pages.deps_page import DependenciesPage
from .pages.labels_page import LabelsPage
from .pages.integrations_page import IntegrationsPage
from .pages.system_page import SystemPage
from .pages.models_page import ModelsPage
from .pages.console_page import ConsolePage
from .pages.shortcuts_page import ShortcutsPage
from gui.styles import apply_shapes

# Índices de las páginas dentro del QStackedWidget de abajo, en el mismo orden en
# que se añaden. Los usa SettingsModalOverlay.open_page() y cualquier parte de la app
# que quiera saltar directo a una página -- ver
# gui/widgets/model_download_prompt.py::open_models_settings, que es lo que hay
# detrás del botón "Administrar" de los popovers del Editor de Imagen. Si se
# reordenan las páginas hay que actualizar esto.
SETTINGS_PAGE_DEPENDENCIES = 4
SETTINGS_PAGE_MODELS = 8


class SidebarButton(QPushButton):
    """Custom button for sidebar to handle styling via objectName and QSS"""
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setObjectName("sidebarButton")
        self.setCheckable(True)
        self.setFixedHeight(36)
        self.setCursor(Qt.PointingHandCursor)

class SettingsTab(QWidget):
    language_changed = Signal(str)
    theme_changed = Signal(str)
    font_changed = Signal(str)
    integrations_changed = Signal()
    labels_changed = Signal()
    update_status_changed = Signal(bool)  # True = hay una actualizacion pendiente (para el badge de main_window)

    def __init__(self):
        super().__init__()
        self._update_info = None      # UpdateInfo | None -- la ultima detectada
        self._update_state = "idle"   # "idle" | "checking" | "available" | "downloading"
        self._check_worker = None
        self._download_worker = None
        self.init_ui()

    def init_ui(self):
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # ---------------- LEFT SIDEBAR ----------------
        self.sidebar_frame = QFrame()
        self.sidebar_frame.setObjectName("settingsSidebar")
        self.sidebar_frame.setFixedWidth(185)

        sidebar_layout = QVBoxLayout(self.sidebar_frame)
        sidebar_layout.setContentsMargins(0, 16, 0, 16)
        sidebar_layout.setSpacing(4)

        # Title
        options_label = QLabel(self.tr("Opciones"))
        font = options_label.font()
        font.setBold(True)
        font.setPointSize(12)
        options_label.setFont(font)
        options_label.setAlignment(Qt.AlignCenter)
        sidebar_layout.addWidget(options_label)
        sidebar_layout.addSpacing(14)

        self.btn_group = QButtonGroup(self)
        self.btn_group.setExclusive(True)

        # Buttons
        self.btn_general = SidebarButton(self.tr("General"))
        self.btn_memory_cache = SidebarButton(self.tr("Memoria y Caché"))
        self.btn_downloads = SidebarButton(self.tr("Descargas"))
        self.btn_cookies = SidebarButton(self.tr("Cookies"))
        self.btn_deps = SidebarButton(self.tr("Dependencias"))
        self.btn_labels = SidebarButton(self.tr("Etiquetas"))
        self.btn_integrations = SidebarButton(self.tr("Integraciones"))
        self.btn_system = SidebarButton(self.tr("Acerca de"))
        self.btn_models = SidebarButton(self.tr("Modelos"))
        self.btn_console = SidebarButton(self.tr("Consola"))
        self.btn_shortcuts = SidebarButton(self.tr("Atajos de teclado"))

        self.btn_group.addButton(self.btn_general, 0)
        self.btn_group.addButton(self.btn_memory_cache, 1)
        self.btn_group.addButton(self.btn_downloads, 2)
        self.btn_group.addButton(self.btn_cookies, 3)
        self.btn_group.addButton(self.btn_deps, 4)
        self.btn_group.addButton(self.btn_labels, 5)
        self.btn_group.addButton(self.btn_integrations, 6)
        self.btn_group.addButton(self.btn_system, 7)
        self.btn_group.addButton(self.btn_models, 8)
        self.btn_group.addButton(self.btn_console, 9)
        self.btn_group.addButton(self.btn_shortcuts, 10)

        sidebar_layout.addWidget(self.btn_general)
        sidebar_layout.addWidget(self.btn_memory_cache)
        sidebar_layout.addWidget(self.btn_downloads)
        sidebar_layout.addWidget(self.btn_cookies)
        sidebar_layout.addWidget(self.btn_deps)
        sidebar_layout.addWidget(self.btn_labels)
        sidebar_layout.addWidget(self.btn_shortcuts)
        sidebar_layout.addWidget(self.btn_integrations)
        sidebar_layout.addWidget(self.btn_system)
        sidebar_layout.addWidget(self.btn_models)
        sidebar_layout.addWidget(self.btn_console)
        sidebar_layout.addStretch()

        # Version Label
        self.version_label = QLabel(f"v{get_display_version()}")
        self.version_label.setStyleSheet(apply_shapes("color: #555555; font-size: 11px; margin-bottom: 6px;"))
        self.version_label.setAlignment(Qt.AlignCenter)
        sidebar_layout.addWidget(self.version_label)

        # Botón de actualizaciones -- SIEMPRE visible, cambia de texto/estilo segun
        # self._update_state. El circulo de progreso ocupa su sitio mientras descarga
        # (reemplazo, no superposicion).
        self.update_button = QPushButton(self.tr("Buscar actualizaciones"))
        self.update_button.setObjectName("updateButton")
        self.update_button.setFixedHeight(30)
        self.update_button.setCursor(Qt.PointingHandCursor)
        self.update_button.clicked.connect(self._on_update_button_clicked)
        self._apply_update_button_style(gradient=False)
        from gui.theme_manager import get_theme_manager
        get_theme_manager().theme_changed.connect(
            lambda _tokens: self._apply_update_button_style(getattr(self, "_update_button_gradient", False)))
        sidebar_layout.addWidget(self.update_button, 0, Qt.AlignCenter)

        self.update_progress = CircularProgress(diameter=30)
        self.update_progress.hide()
        sidebar_layout.addWidget(self.update_progress, 0, Qt.AlignCenter)

        self.main_layout.addWidget(self.sidebar_frame)

        # ---------------- RIGHT CONTENT AREA ----------------
        self.content_area = QFrame()
        self.content_area.setObjectName("settingsContentArea")
        
        content_layout = QVBoxLayout(self.content_area)
        content_layout.setContentsMargins(22, 16, 22, 16)

        self.stacked_widget = QStackedWidget()

        # Pages. Cada una entra como un marcador vacío y se construye la primera vez que
        # se abre (_ensure_page): construirlas todas de entrada era casi 2 s del arranque
        # para un panel que está oculto. self.page_<nombre> existe recién desde que su
        # página se construye. La tarjeta de Ajustes mide lo mismo con una página
        # construida que con todas (su tamaño máximo manda), así que no cambia nada visible.
        self._page_specs = [
            ("page_general", GeneralPage),              # 0
            ("page_memory_cache", MemoryCachePage),     # 1
            ("page_downloads", DownloadsPage),          # 2
            ("page_cookies", CookiesPage),              # 3
            ("page_deps", DependenciesPage),            # 4
            ("page_labels", LabelsPage),                # 5
            ("page_integrations", IntegrationsPage),    # 6
            ("page_system", SystemPage),                # 7
            ("page_models", ModelsPage),                # 8
            ("page_console", ConsolePage),              # 9
            ("page_shortcuts", ShortcutsPage),          # 10
        ]
        self._page_built = [False] * len(self._page_specs)
        for _ in self._page_specs:
            placeholder = QWidget()
            placeholder_layout = QVBoxLayout(placeholder)
            placeholder_layout.setContentsMargins(0, 0, 0, 0)
            placeholder_layout.setSpacing(0)
            self.stacked_widget.addWidget(placeholder)

        content_layout.addWidget(self.stacked_widget)
        self.main_layout.addWidget(self.content_area, 1)

        # Connections
        self.btn_group.idClicked.connect(self._on_tab_changed)

        # Default selection
        self.btn_general.setChecked(True)
        self.stacked_widget.setCurrentIndex(0)

    def _ensure_page(self, index: int):
        """Construye la página `index` si todavía no existe y la devuelve."""
        attr, page_class = self._page_specs[index]
        if self._page_built[index]:
            return getattr(self, attr)
        from core.utils import startup_timer
        from gui.app_event_filters import build_without_app_filters
        with startup_timer.measure(f"página de Ajustes construida: {page_class.__name__}"):
            page = build_without_app_filters(page_class)
        setattr(self, attr, page)
        self._page_built[index] = True
        self.stacked_widget.widget(index).layout().addWidget(page)
        self._connect_page(attr, page)
        return page

    def _connect_page(self, attr: str, page):
        if attr == "page_general":
            # Pass signals from general page
            page.language_changed.connect(self.language_changed.emit)
            page.theme_changed.connect(self.theme_changed.emit)
            page.font_changed.connect(self.font_changed.emit)
            page.update_channel_changed.connect(self._on_update_channel_changed)
        elif attr == "page_labels":
            # Pass signal from labels page
            page.labels_changed.connect(self.labels_changed.emit)
        elif attr == "page_integrations":
            # Pass signal from integrations page
            page.integration_toggled.connect(lambda app_id, checked: self.integrations_changed.emit())

    def showEvent(self, event):
        # Red de seguridad: cualquier camino que muestre Ajustes ve su página construida
        # (open_page ya pasa por _on_tab_changed, que también lo hace).
        self._ensure_page(self.stacked_widget.currentIndex())
        super().showEvent(event)


    def _on_tab_changed(self, index: int):
        self._ensure_page(index)
        self.stacked_widget.setCurrentIndex(index)
        if index == 1:
            self.page_memory_cache.refresh_stats()
        elif index == SETTINGS_PAGE_MODELS:
            # Un modelo pudo instalarse o borrarse desde los popovers del Editor de
            # Imagen desde la última vez que se miró esta página. Cubre también el
            # salto directo del botón "Administrar": open_page() llega hasta aquí
            # porque hace click() sobre el botón lateral.
            self.page_models.refresh_rows()

    # ───────────────────────── Actualizaciones ─────────────────────────
    # Conecta las piezas 1-2 (manifiesto firmado + diff, ver core/updater/)
    # con la barra lateral. Todo el mecanismo es no-op en modo fuente (no
    # frozen): no existe un install_dir real que comparar corriendo desde el
    # codigo fuente -- mismo criterio que resume_pending_swap() de la pieza 3.

    def _apply_update_button_style(self, gradient: bool):
        from gui.styles import get_theme_token
        # Recordar el estado para reaplicarlo con el tema nuevo (ver __init__).
        self._update_button_gradient = gradient
        base = get_theme_token("boton_secundario_fondo", "#1b3b22")
        texto = get_theme_token("boton_secundario_texto", "#B9E640")
        hover = get_theme_token("boton_secundario_hover", "#224a2b")
        background = (
            f"qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {base}, stop:1 #3a7a45)"
            if gradient else base
        )
        hover_background = (
            f"qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {hover}, stop:1 #4a9456)"
            if gradient else hover
        )
        self.update_button.setStyleSheet(apply_shapes(f"""
            QPushButton#updateButton {{
                background: {background};
                color: {texto};
                border: none;
                border-radius: 6px;
                font-weight: bold;
                font-size: 11px;
                padding: 6px 16px;
            }}
            QPushButton#updateButton:hover {{
                background: {hover_background};
            }}
            QPushButton#updateButton:disabled {{
                color: #777777;
            }}
        """))

    def start_update_check(self):
        """Se llama al arrancar (una vez, desde main_window.py) y de nuevo cada
        vez que se pulsa el botón mientras está en estado "Buscar actualizaciones"."""
        if not getattr(sys, "frozen", False):
            return
        if self._update_state not in ("idle",):
            return
        self._update_state = "checking"
        self.update_button.setEnabled(False)
        self._check_worker = UpdateCheckWorker()
        self._check_worker.finished.connect(self._on_check_finished)
        self._check_worker.start()

    def _on_check_finished(self, update_info):
        self.update_button.setEnabled(True)
        self.set_update_info(update_info)

    def _on_update_channel_changed(self, channel):
        """GeneralPage ya guardo el canal en config -- si no hay nada en curso,
        volver a chequear con el canal nuevo (mismo criterio que
        DependenciesPage._on_channel_changed llamando a _refresh_status())."""
        logger.info(f"Updater: canal de actualizaciones cambiado a '{channel}', reintentando chequeo.")
        if self._update_state == "idle":
            self.start_update_check()

    def set_update_info(self, update_info):
        """update_info: UpdateInfo (hay algo que instalar) o None (nada nuevo /
        sin releases todavia / fallo de red -- todos indistinguibles a proposito
        para el usuario, ver update_service.UpdateCheckWorker)."""
        self._update_info = update_info

        if update_info is None:
            self._update_state = "idle"
            self.update_button.setText(self.tr("Buscar actualizaciones"))
            self.update_button.setToolTip("")
            self._apply_update_button_style(gradient=False)
            self.version_label.setText(f"v{get_display_version()}")
            self.update_status_changed.emit(False)
        elif update_info.must_full_install:
            # Version por debajo de min_updatable_version, o formato de manifiesto que
            # este cliente no entiende: el swap no puede expresar esta actualizacion.
            # Ofrecer "Actualizar" igual aplicaba un journal vacio, relanzaba la MISMA
            # version y la volvia a ofrecer en bucle -- aqui se manda al instalador.
            self._update_state = "full_install"
            self.update_button.setText(self.tr("Descargar instalador"))
            self.update_button.setToolTip(self.tr(
                "Esta versión no puede actualizarse sola: descarga e instala la nueva "
                "versión desde la página de releases."
            ))
            self._apply_update_button_style(gradient=True)
            self.version_label.setText(f"{update_info.current_version} - <b><i>{update_info.remote_version}</i></b>")
            self.update_status_changed.emit(True)
        else:
            self._update_state = "available"
            self.update_button.setText(self.tr("Actualizar"))
            self.update_button.setToolTip("")
            self._apply_update_button_style(gradient=True)
            self.version_label.setText(f"{update_info.current_version} - <b><i>{update_info.remote_version}</i></b>")
            self.update_status_changed.emit(True)

    def _on_update_button_clicked(self):
        if self._update_state == "available":
            self.start_update_download()
        elif self._update_state == "full_install":
            QDesktopServices.openUrl(QUrl(f"https://github.com/{UPDATE_REPO}/releases"))
        elif self._update_state == "idle":
            self.start_update_check()
        # "checking"/"downloading": el boton esta deshabilitado u oculto, no deberia poder llegar aqui

    def start_update_download(self):
        from core.utils.paths import get_update_staging_dir

        if self._update_info is None or self._update_info.must_full_install:
            return
        self._update_state = "downloading"
        self.update_button.hide()
        self.update_progress.setValue(0)
        self.update_progress.show()

        staging_dir = get_update_staging_dir()
        self._download_worker = UpdateDownloadWorker(self._update_info, staging_dir)
        self._download_worker.progress.connect(self._on_download_progress)
        self._download_worker.finished.connect(self._on_download_finished)
        self._download_worker.start()

    def _on_download_progress(self, completed: int, total: int):
        percent = int(completed / total * 100) if total else 0
        self.update_progress.setValue(percent)

    def _on_download_finished(self, ok: bool, error_message: str):
        if not ok:
            logger.error(f"Updater: descarga fallida, se puede reintentar: {error_message}")
            self._update_state = "available"
            self.update_progress.hide()
            self.update_button.show()
            return
        self._apply_update()

    def _apply_update(self):
        """Descarga verificada -- construye el journal, se lo entrega al helper
        de swap (pieza 3) y cierra la app para que pueda aplicarlo. Sin paso de
        confirmacion intermedio, tal como se acordó."""
        from core.updater import journal as journal_mod
        from core.updater.launcher import hand_off_to_helper, install_dir_from_executable
        from core.utils.paths import get_update_staging_dir, get_updater_state_dir

        # La MISMA raiz con la que compute_diff calculo las rutas del journal. En
        # Windows/Linux es la carpeta del .exe; en macOS es el .app entero, no
        # Contents/MacOS -- con dirname(sys.executable) los archivos acababan en
        # DowP.app/Contents/MacOS/Contents/... y la app real no cambiaba nunca.
        # relaunch_exe sigue siendo sys.executable a proposito: relanzar el .app via
        # 'open -n' le daria al helper el PID de 'open', que termina enseguida, y el
        # chequeo de arranque haria un rollback falso (ver launcher.spawn_detached).
        install_dir = install_dir_from_executable(sys.executable)
        state_dir = get_updater_state_dir()
        staging_dir = get_update_staging_dir()

        j = journal_mod.build_journal(
            self._update_info, install_dir, staging_dir, state_dir, relaunch_exe=sys.executable
        )
        journal_mod.write_journal(j, state_dir)

        logger.info("Updater: actualizacion descargada y verificada, entregando al helper y cerrando.")
        hand_off_to_helper(state_dir, install_dir, os.getpid(), sys.executable)
        QApplication.instance().quit()



