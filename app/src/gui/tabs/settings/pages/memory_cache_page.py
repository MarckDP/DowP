# src/gui/tabs/settings/pages/memory_cache_page.py
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QScrollArea,
    QPushButton, QMessageBox, QProgressBar, QSizePolicy, QLineEdit, QFileDialog
)
from PySide6.QtCore import Qt
from core.utils.i18n import logger
from core.utils.cache_manager import CacheManager, format_bytes
from gui.styles import apply_folder_browse_button_style


class CacheCard(QFrame):
    """Tarjeta individual para representar y controlar un proveedor de caché específico."""

    def __init__(self, key: str, name: str, description: str, on_clear_callback, parent=None):
        super().__init__(parent)
        self.key = key
        self.name = name
        self.description = description
        self.on_clear_callback = on_clear_callback

        self.setObjectName("settingsCard")
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        # Información (Izquierda)
        info_vbox = QVBoxLayout()
        info_vbox.setSpacing(4)

        self.lbl_title = QLabel(self.name)
        self.lbl_title.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 13px;")

        self.lbl_desc = QLabel(self.description)
        self.lbl_desc.setWordWrap(True)
        self.lbl_desc.setStyleSheet("color: #888888; font-size: 11px;")

        self.lbl_stats = QLabel("Calculando...")
        self.lbl_stats.setStyleSheet("color: #4CAF50; font-size: 11px; font-weight: bold;")

        info_vbox.addWidget(self.lbl_title)
        info_vbox.addWidget(self.lbl_desc)
        info_vbox.addWidget(self.lbl_stats)

        # Botón de acción (Derecha)
        self.btn_clear = QPushButton(self.tr("Limpiar"))
        self.btn_clear.setFixedHeight(30)
        self.btn_clear.setFixedWidth(90)
        self.btn_clear.setCursor(Qt.PointingHandCursor)
        self.btn_clear.setProperty("variant", "danger")
        self.btn_clear.clicked.connect(lambda: self.on_clear_callback(self.key, self.name))

        layout.addLayout(info_vbox, 1)
        layout.addWidget(self.btn_clear, 0, Qt.AlignVCenter)

    def update_stats(self, file_count: int, size_bytes: int):
        formatted_size = format_bytes(size_bytes)
        self.lbl_stats.setText(self.tr("{0} archivos  |  Tamaño: {1}").format(file_count, formatted_size))


class FutureCacheCard(QFrame):
    """Tarjeta reservada para futuras cachés de la aplicación."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("futureCacheCard")
        self.setStyleSheet("""
            QFrame#futureCacheCard {
                background-color: #181818;
                border: 1px dashed #3a3a3a;
                border-radius: 6px;
                padding: 12px;
            }
        """)
        init_layout = QHBoxLayout(self)
        init_layout.setContentsMargins(12, 10, 12, 10)

        vbox = QVBoxLayout()
        vbox.setSpacing(4)

        lbl_title = QLabel(self.tr("Espacio reservado para más cachés"))
        lbl_title.setStyleSheet("color: #aaaaaa; font-weight: bold; font-size: 12px;")


        lbl_desc = QLabel(self.tr("Aquí se integrarán automáticamente las nuevas cachés del sistema a medida que se añadan nuevas funciones (descargas de red, ondas de audio, etc.)."))
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("color: #666666; font-size: 11px;")

        vbox.addWidget(lbl_title)
        vbox.addWidget(lbl_desc)
        init_layout.addLayout(vbox)


class MemoryCachePage(QWidget):
    """Pestaña de ajustes para centralizar el monitoreo y limpieza de la memoria y caché de la app."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cache_cards: dict[str, CacheCard] = {}
        self.init_ui()
        self.refresh_stats()

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(12)

        # ---------------- TÍTULO Y SEPARADOR ----------------
        self.title_label = QLabel(self.tr("Memoria y Caché"))
        self.title_label.setObjectName("settingsTitle")
        self.main_layout.addWidget(self.title_label)

        line = QFrame()
        line.setObjectName("settingsDivider")
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        self.main_layout.addWidget(line)

        # ---------------- SCROLL AREA ----------------
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")

        self.scroll_content = QWidget()
        self.scroll_content.setObjectName("settingsScrollContent")
        self.scroll_content.setStyleSheet("QWidget#settingsScrollContent { background-color: transparent; }")

        self.content_layout = QVBoxLayout(self.scroll_content)
        self.content_layout.setContentsMargins(0, 10, 10, 0)
        self.content_layout.setSpacing(16)
        self.content_layout.setAlignment(Qt.AlignTop)

        # ---------------- TARJETA RESUMEN TOTAL / MEDIDOR GLOBAL ----------------
        self.total_card = QFrame()
        self.total_card.setObjectName("totalCacheCard")
        self.total_card.setStyleSheet("""
            QFrame#totalCacheCard {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #25282a, stop:1 #1c1d1f);
                border: 1px solid #383c40;
                border-radius: 6px;
                padding: 16px;
            }
        """)

        total_layout = QVBoxLayout(self.total_card)
        total_layout.setSpacing(10)

        # Encabezado del total
        header_hbox = QHBoxLayout()
        lbl_total_title = QLabel(self.tr("Uso Total de Caché"))
        lbl_total_title.setStyleSheet("color: #ffffff; font-size: 14px; font-weight: bold;")
        
        self.lbl_total_size = QLabel("0 B")
        self.lbl_total_size.setStyleSheet("color: #B9E640; font-size: 18px; font-weight: bold;")
        
        header_hbox.addWidget(lbl_total_title)
        header_hbox.addStretch()
        header_hbox.addWidget(self.lbl_total_size)
        total_layout.addLayout(header_hbox)

        # Medidor / Barra de progreso global
        self.meter_bar = QProgressBar()
        self.meter_bar.setFixedHeight(8)
        self.meter_bar.setTextVisible(False)
        self.meter_bar.setRange(0, 100)
        self.meter_bar.setValue(0)
        self.meter_bar.setStyleSheet("""
            QProgressBar {
                background-color: #121212;
                border-radius: 4px;
                border: none;
            }
            QProgressBar::chunk {
                background-color: #B9E640;
                border-radius: 4px;
            }
        """)
        total_layout.addWidget(self.meter_bar)

        # Subtítulo de resumen y botón de borrar todo
        action_hbox = QHBoxLayout()
        self.lbl_total_details = QLabel(self.tr("Calculando uso de memoria y archivos..."))
        self.lbl_total_details.setStyleSheet("color: #aaaaaa; font-size: 11px;")

        self.btn_clear_all = QPushButton(self.tr("Borrar toda la caché"))
        self.btn_clear_all.setFixedHeight(34)
        self.btn_clear_all.setCursor(Qt.PointingHandCursor)
        self.btn_clear_all.setProperty("variant", "danger")
        self.btn_clear_all.clicked.connect(self.on_clear_all_clicked)

        action_hbox.addWidget(self.lbl_total_details)
        action_hbox.addStretch()
        action_hbox.addWidget(self.btn_clear_all)
        total_layout.addLayout(action_hbox)

        # Límite de Caché
        from PySide6.QtWidgets import QDoubleSpinBox, QAbstractSpinBox
        from core.utils.config_manager import get_config
        
        limit_hbox = QHBoxLayout()
        self.lbl_limit = QLabel(self.tr("Límite máximo:"))
        self.lbl_limit.setStyleSheet("color: #aaaaaa; font-size: 13px;")
        
        self.limit_spinbox = QDoubleSpinBox()
        self.limit_spinbox.setRange(0.0, 999.0)
        self.limit_spinbox.setDecimals(1)
        self.limit_spinbox.setSingleStep(1.0)
        self.limit_spinbox.setSuffix(self.tr(" GB"))
        self.limit_spinbox.setSpecialValueText(self.tr("Sin límite"))
        self.limit_spinbox.setFixedWidth(140)
        self.limit_spinbox.setButtonSymbols(QAbstractSpinBox.PlusMinus)
        self.limit_spinbox.setStyleSheet("""
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
                font-size: 9px;
                padding: 0px;
            }
        """)
        
        # Cargar valor inicial
        current_limit = get_config().get("max_cache_size_gb", 0.0)
        self.limit_spinbox.setValue(current_limit)
        self.limit_spinbox.valueChanged.connect(self.on_limit_changed)

        limit_hbox.addWidget(self.lbl_limit)
        limit_hbox.addWidget(self.limit_spinbox)
        limit_hbox.addStretch()

        total_layout.addLayout(limit_hbox)

        self.content_layout.addWidget(self.total_card)

        # ---------------- SECCIÓN DE CACHÉS INDIVIDUALES ----------------
        lbl_sec_title = QLabel(self.tr("Cachés de la Aplicación"))
        lbl_sec_title.setObjectName("settingsSectionTitle")
        lbl_sec_title.setStyleSheet("color: #dddddd; font-size: 13px; font-weight: bold; margin-top: 8px;")
        self.content_layout.addWidget(lbl_sec_title)

        # Construir tarjetas de proveedores registrados en CacheManager
        cache_mgr = CacheManager.get_instance()
        for provider in cache_mgr.get_providers():
            card = CacheCard(
                key=provider.key,
                name=provider.name,
                description=provider.description,
                on_clear_callback=self.on_clear_single_clicked,
                parent=self.scroll_content
            )
            self.cache_cards[provider.key] = card
            self.content_layout.addWidget(card)

        # Tarjeta reservada para futuras cachés
        self.content_layout.addWidget(FutureCacheCard(parent=self.scroll_content))

        # ---------------- ADMINISTRADOR DE MEDIOS (carpeta de descargas por defecto) ----------------
        lbl_media_title = QLabel(self.tr("Administrador de Medios"))
        lbl_media_title.setObjectName("settingsSectionTitle")
        lbl_media_title.setStyleSheet("color: #dddddd; font-size: 13px; font-weight: bold; margin-top: 8px;")
        self.content_layout.addWidget(lbl_media_title)

        self.download_dir_card = QFrame()
        self.download_dir_card.setObjectName("settingsCard")
        dl_layout = QVBoxLayout(self.download_dir_card)
        dl_layout.setContentsMargins(12, 10, 12, 10)
        dl_layout.setSpacing(8)

        lbl_dl_title_row = QLabel(self.tr("Carpeta de descargas por defecto (medios web sin etiqueta)"))
        lbl_dl_title_row.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 13px;")
        dl_layout.addWidget(lbl_dl_title_row)

        lbl_dl_desc = QLabel(self.tr(
            "Carpeta donde se guardan las descargas de medios web (p. ej. Freesound, Wikimedia) cuando no "
            "seleccionaste ninguna etiqueta. Por defecto se usa la carpeta Downloads del sistema."
        ))
        lbl_dl_desc.setWordWrap(True)
        lbl_dl_desc.setStyleSheet("color: #888888; font-size: 11px;")
        dl_layout.addWidget(lbl_dl_desc)

        dl_path_hbox = QHBoxLayout()
        dl_path_hbox.setSpacing(8)

        self.download_dir_input = QLineEdit()
        self.download_dir_input.textChanged.connect(self._on_download_dir_text_changed)

        self.btn_browse_download_dir = QPushButton()
        self.btn_browse_download_dir.setFixedSize(32, 32)
        self.btn_browse_download_dir.setCursor(Qt.PointingHandCursor)
        apply_folder_browse_button_style(self.btn_browse_download_dir, self.tr("Examinar carpeta de descargas"))
        self.btn_browse_download_dir.clicked.connect(self.on_browse_download_dir_clicked)

        self.btn_reset_download_dir = QPushButton(self.tr("Restablecer"))
        self.btn_reset_download_dir.setFixedHeight(30)
        self.btn_reset_download_dir.setCursor(Qt.PointingHandCursor)
        self.btn_reset_download_dir.setProperty("variant", "secondary")
        self.btn_reset_download_dir.clicked.connect(self.on_reset_download_dir_clicked)

        dl_path_hbox.addWidget(self.download_dir_input, 1)
        dl_path_hbox.addWidget(self.btn_browse_download_dir)
        dl_path_hbox.addWidget(self.btn_reset_download_dir)
        dl_layout.addLayout(dl_path_hbox)

        self._refresh_download_dir_label()

        self.content_layout.addWidget(self.download_dir_card)

        # ---------------- CARPETA DE SUBCLIPS RÁPIDOS (sin editor conectado) ----------------
        self.subclip_dir_card = QFrame()
        self.subclip_dir_card.setObjectName("settingsCard")
        sub_layout = QVBoxLayout(self.subclip_dir_card)
        sub_layout.setContentsMargins(12, 10, 12, 10)
        sub_layout.setSpacing(8)

        lbl_sub_title_row = QLabel(self.tr("Carpeta de subclips rápidos (sin editor conectado)"))
        lbl_sub_title_row.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 13px;")
        sub_layout.addWidget(lbl_sub_title_row)

        lbl_sub_desc = QLabel(self.tr(
            "Carpeta donde se guardan los recortes rápidos de subclips cuando no hay un editor de video "
            "conectado. Por defecto se guardan en 'Documentos/DowP2/Subclips'."
        ))
        lbl_sub_desc.setWordWrap(True)
        lbl_sub_desc.setStyleSheet("color: #888888; font-size: 11px;")
        sub_layout.addWidget(lbl_sub_desc)

        sub_path_hbox = QHBoxLayout()
        sub_path_hbox.setSpacing(8)

        self.subclip_dir_input = QLineEdit()
        self.subclip_dir_input.textChanged.connect(self._on_subclip_dir_text_changed)

        self.btn_browse_subclip_dir = QPushButton()
        self.btn_browse_subclip_dir.setFixedSize(32, 32)
        self.btn_browse_subclip_dir.setCursor(Qt.PointingHandCursor)
        apply_folder_browse_button_style(self.btn_browse_subclip_dir, self.tr("Examinar carpeta de subclips"))
        self.btn_browse_subclip_dir.clicked.connect(self.on_browse_subclip_dir_clicked)

        self.btn_reset_subclip_dir = QPushButton(self.tr("Restablecer"))
        self.btn_reset_subclip_dir.setFixedHeight(30)
        self.btn_reset_subclip_dir.setCursor(Qt.PointingHandCursor)
        self.btn_reset_subclip_dir.setProperty("variant", "secondary")
        self.btn_reset_subclip_dir.clicked.connect(self.on_reset_subclip_dir_clicked)

        sub_path_hbox.addWidget(self.subclip_dir_input, 1)
        sub_path_hbox.addWidget(self.btn_browse_subclip_dir)
        sub_path_hbox.addWidget(self.btn_reset_subclip_dir)
        sub_layout.addLayout(sub_path_hbox)

        # Fila de estadísticas + borrado manual de subclips físicos. Deliberadamente NO forma
        # parte de CacheManager/"Borrar toda la caché": son medios reales que el usuario puede
        # tener enlazados en un proyecto de edición externo, así que solo se borran aquí, a mano
        # y con confirmación explícita.
        sub_stats_hbox = QHBoxLayout()
        sub_stats_hbox.setSpacing(8)

        self.lbl_subclip_stats = QLabel(self.tr("Calculando..."))
        self.lbl_subclip_stats.setStyleSheet("color: #4CAF50; font-size: 11px; font-weight: bold;")

        self.btn_clear_subclips = QPushButton(self.tr("Borrar subclips"))
        self.btn_clear_subclips.setFixedHeight(30)
        self.btn_clear_subclips.setCursor(Qt.PointingHandCursor)
        self.btn_clear_subclips.setProperty("variant", "danger")
        self.btn_clear_subclips.clicked.connect(self.on_clear_subclips_clicked)

        sub_stats_hbox.addWidget(self.lbl_subclip_stats, 1)
        sub_stats_hbox.addWidget(self.btn_clear_subclips)
        sub_layout.addLayout(sub_stats_hbox)

        self._refresh_subclip_dir_label()

        self.content_layout.addWidget(self.subclip_dir_card)

        # Finalizar setup del scroll area
        self.scroll_area.setWidget(self.scroll_content)
        self.main_layout.addWidget(self.scroll_area)

    def refresh_stats(self):
        """Obtiene las estadísticas actualizadas de CacheManager y refresca la UI."""
        stats = CacheManager.get_instance().get_all_stats()

        total_files = stats.get("total_files", 0)
        total_bytes = stats.get("total_bytes", 0)
        formatted_total = stats.get("formatted_total_size", "0 B")

        self.lbl_total_size.setText(formatted_total)
        self.lbl_total_details.setText(
            self.tr("Archivos acumulados en caché: {0}  •  Almacenamiento total: {1}").format(total_files, formatted_total)
        )

        # Actualizar medidor (barra visual)
        from core.utils.config_manager import get_config
        limit_gb = get_config().get("max_cache_size_gb", 0.0)

        if limit_gb > 0:
            max_reference_bytes = limit_gb * 1024 * 1024 * 1024
        else:
            import os
            import shutil
            try:
                # Obtenemos el espacio libre del disco donde está AppData
                app_data = os.getenv('APPDATA', 'C:\\')
                total, used, free = shutil.disk_usage(app_data)
                # El tamaño visual máximo será el caché actual + el espacio libre que le queda al disco
                max_reference_bytes = total_bytes + free
            except Exception:
                max_reference_bytes = 100 * 1024 * 1024

        percentage = min(100, int((total_bytes / max_reference_bytes) * 100)) if max_reference_bytes > 0 else 0
        self.meter_bar.setValue(percentage if total_bytes > 0 else 0)

        # Actualizar tarjetas individuales
        for p_stat in stats.get("providers", []):
            key = p_stat.get("key")
            if key in self.cache_cards:
                self.cache_cards[key].update_stats(
                    file_count=p_stat.get("file_count", 0),
                    size_bytes=p_stat.get("size_bytes", 0)
                )

        self._compute_subclip_dir_stats()

    def on_clear_single_clicked(self, key: str, name: str):
        """Elimina la caché de un proveedor específico previa confirmación."""
        reply = QMessageBox.question(
            self,
            self.tr("Confirmar Limpieza"),
            self.tr("¿Estás seguro de que deseas vaciar la '{0}'?").format(name),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            res = CacheManager.get_instance().clear_provider(key)
            freed_str = format_bytes(res.get("bytes_freed", 0))
            QMessageBox.information(
                self,
                self.tr("Caché Limpiada"),
                self.tr("Se ha limpiado la '{0}' correctamente.\nSe eliminaron {1} archivos y se liberaron {2}.").format(name, res.get('files_removed', 0), freed_str)
            )
            self.refresh_stats()

    def on_clear_all_clicked(self):
        """Elimina absolutamente todas las cachés del sistema."""
        reply = QMessageBox.question(
            self,
            self.tr("Confirmar Limpieza Total"),
            self.tr("¿Deseas eliminar TODA la caché de la aplicación (imágenes, miniaturas y metadatos)?\nEsta acción liberará espacio de almacenamiento."),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            res = CacheManager.get_instance().clear_all()
            if res:
                QMessageBox.information(
                    self,
                    self.tr("Caché Total Limpiada"),
                    self.tr("Limpieza total completada con éxito.\nSe eliminaron {0} archivos y se liberaron {1}.").format(res.get('files_removed', 0), res.get('formatted_freed', '0 B'))
                )
                self.refresh_stats()

    def on_limit_changed(self, value):
        from core.utils.config_manager import get_config, save_config
        config = get_config()
        config["max_cache_size_gb"] = value
        save_config(config)
        # Refrescar la barra para que recalcule de inmediato con el nuevo límite
        self.refresh_stats()

    def _refresh_download_dir_label(self):
        from core.utils.config_manager import get_config
        current_dir = get_config().get("default_web_download_dir", "")
        default_placeholder = os.path.expanduser("~/Downloads")
        self.download_dir_input.setPlaceholderText(self.tr("(Por defecto: {0})").format(default_placeholder))
        if self.download_dir_input.text() != current_dir:
            self.download_dir_input.setText(current_dir)

    def _on_download_dir_text_changed(self, text: str):
        from core.utils.config_manager import get_config, save_config
        config = get_config()
        config["default_web_download_dir"] = text.strip()
        save_config(config)

    def on_browse_download_dir_clicked(self):
        from core.utils.config_manager import get_config, save_config
        config = get_config()
        current_dir = config.get("default_web_download_dir") or os.path.expanduser("~/Downloads")
        folder = QFileDialog.getExistingDirectory(
            self,
            self.tr("Seleccionar carpeta de descargas por defecto"),
            current_dir
        )
        if folder:
            self.download_dir_input.setText(folder)

    def on_reset_download_dir_clicked(self):
        self.download_dir_input.setText("")

    def _refresh_subclip_dir_label(self):
        from core.utils.config_manager import get_config
        from core.utils.paths import get_subclips_dir
        current_dir = get_config().get("default_subclip_dir", "")
        default_path = get_subclips_dir()
        self.subclip_dir_input.setPlaceholderText(self.tr("(Por defecto: {0})").format(default_path))
        if self.subclip_dir_input.text() != current_dir:
            self.subclip_dir_input.setText(current_dir)
        self._compute_subclip_dir_stats()

    def _resolve_effective_subclip_dir(self) -> str:
        from core.utils.config_manager import get_config
        from core.utils.paths import get_subclips_dir
        return get_config().get("default_subclip_dir") or get_subclips_dir()

    def _compute_subclip_dir_stats(self):
        """Calcula archivos y tamaño de la carpeta de subclips físicos actual y refresca la
        etiqueta. Solo cuenta archivos de nivel superior (no hay subcarpetas en uso normal)."""
        target_dir = self._resolve_effective_subclip_dir()
        file_count = 0
        total_size = 0
        if os.path.exists(target_dir):
            try:
                for entry in os.scandir(target_dir):
                    if entry.is_file():
                        file_count += 1
                        try:
                            total_size += entry.stat().st_size
                        except Exception:
                            pass
            except Exception as e:
                logger.error(f"MemoryCachePage: Error calculando tamaño de la carpeta de subclips: {e}")

        self.lbl_subclip_stats.setText(self.tr("{0} archivos  |  Tamaño: {1}").format(file_count, format_bytes(total_size)))
        self.btn_clear_subclips.setEnabled(file_count > 0)

    def on_clear_subclips_clicked(self):
        """Borra a mano los subclips físicos ya cortados, previa confirmación explícita.
        Deliberadamente independiente de CacheManager: son medios reales, no una caché
        regenerable, así que nunca se borran junto con 'Borrar toda la caché'."""
        target_dir = self._resolve_effective_subclip_dir()
        file_count = 0
        total_size = 0
        files_to_remove = []
        if os.path.exists(target_dir):
            for entry in os.scandir(target_dir):
                if entry.is_file():
                    file_count += 1
                    try:
                        total_size += entry.stat().st_size
                    except Exception:
                        pass
                    files_to_remove.append(entry.path)

        if file_count == 0:
            QMessageBox.information(
                self,
                self.tr("Sin subclips"),
                self.tr("No hay subclips guardados en esta carpeta.")
            )
            return

        formatted_size = format_bytes(total_size)
        reply = QMessageBox.warning(
            self,
            self.tr("Borrar subclips físicos"),
            self.tr(
                "Vas a eliminar permanentemente {0} subclips guardados en esta carpeta ({1}).\n\n"
                "Estos son archivos de medios reales, no una caché regenerable: si ya usaste alguno en un "
                "proyecto de edición (Premiere, DaVinci, etc.) que no esté conectado en vivo a DowP en este "
                "momento, ese proyecto se quedará con el enlace roto al perder el archivo.\n\n"
                "¿Deseas continuar?"
            ).format(file_count, formatted_size),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        removed = 0
        freed = 0
        for fpath in files_to_remove:
            try:
                size = os.path.getsize(fpath)
                os.remove(fpath)
                removed += 1
                freed += size
            except Exception as e:
                logger.error(f"MemoryCachePage: Error borrando subclip '{fpath}': {e}")

        self._sync_subclips_collection_after_clear()

        QMessageBox.information(
            self,
            self.tr("Subclips Borrados"),
            self.tr("Se eliminaron {0} archivos y se liberaron {1}.").format(removed, format_bytes(freed))
        )
        self._compute_subclip_dir_stats()

    def _sync_subclips_collection_after_clear(self):
        """Tras borrar los archivos físicos, vacía también sus entradas en la colección virtual
        'Subclips' para no dejar enlaces rotos. Si la pestaña de Edición de medios ya está viva en
        esta sesión, pasa por su instancia real (evita que un save_data() posterior de esa
        instancia sobrescriba nuestro cambio con su estado en memoria desactualizado). Si no,
        edita indexed_media.json directamente: es seguro porque no hay ninguna instancia viva que
        pueda pisar ese cambio."""
        try:
            from core.tabs.editing_media.editing_media_logic import EditingMediaController
            live_controller = EditingMediaController.get_instance()
            if live_controller:
                live_controller.clear_collection_entries("Subclips")
            else:
                self._prune_subclips_collection_on_disk()
        except Exception as e:
            logger.error(f"MemoryCachePage: Error sincronizando la colección 'Subclips' tras el borrado: {e}")

    def _prune_subclips_collection_on_disk(self):
        import json
        from core.utils.paths import get_indexed_media_path
        db_path = get_indexed_media_path()
        if not os.path.exists(db_path):
            return
        with open(db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        collections = data.get("collections", {})
        if "Subclips" not in collections or not collections["Subclips"]:
            return
        collections["Subclips"] = []
        data["collections"] = collections
        with open(db_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    def _on_subclip_dir_text_changed(self, text: str):
        from core.utils.config_manager import get_config, save_config
        config = get_config()
        config["default_subclip_dir"] = text.strip()
        save_config(config)

    def on_browse_subclip_dir_clicked(self):
        from core.utils.config_manager import get_config, save_config
        from core.utils.paths import get_subclips_dir
        config = get_config()
        current_dir = config.get("default_subclip_dir") or get_subclips_dir()
        folder = QFileDialog.getExistingDirectory(
            self,
            self.tr("Seleccionar carpeta para subclips rápidos"),
            current_dir
        )
        if folder:
            self.subclip_dir_input.setText(folder)

    def on_reset_subclip_dir_clicked(self):
        self.subclip_dir_input.setText("")
