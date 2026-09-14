# src/gui/tabs/quick_mode/activity_panel.py
import os
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QPushButton,
)
from PySide6.QtCore import Qt, QSize, Signal, QEvent
from PySide6.QtGui import QIcon

from gui.styles import get_theme_token
from gui.tabs.quick_mode.download_row import QuickDownloadRow, PlaylistGroupRow
from gui.widgets.native_file_drag import start_native_file_drag
from core.logger.logger_manager import logger
from core.utils.paths import get_src_dir


class ActivityPanel(QFrame):
    """Panel de Actividad de Descargas con barra de scroll y lista de tarjetas."""
    row_close_requested = Signal(object)      # Emitido cuando una fila de descarga solicita cerrarse
    row_reveal_requested = Signal(object)     # Emitido cuando una fila solicita abrir carpeta
    clear_all_requested = Signal()            # Emitido cuando se hace clic en limpiar todo
    cancel_all_requested = Signal()           # Emitido cuando se hace clic en cancelar todo

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("activityPanel")
        self.item_rows = []
        # Tarjetas de grupo (una por playlist). Van aparte de item_rows porque item_rows
        # sigue siendo la lista PLANA de filas de ítem, que es contra la que trabajan la
        # selección, el arrastre y el reparto de progreso del controlador.
        self.group_rows = []
        self.item_keys = []
        self.current_item_pos = 0
        self.completed_items = 0
        # Ancla de la selección con Shift (última fila marcada sin Shift), igual que en
        # una lista del explorador de archivos.
        self._selection_anchor = None
        self.init_ui()

    def init_ui(self):
        # Aplicar el estilo de caja redondeada
        self.setAttribute(Qt.WA_StyledBackground, True)
        borde_color = get_theme_token('borde_normal', '#2d2d2d')
        fondo_color = get_theme_token('fondo_secundario', '#1e1e1e')
        self.setStyleSheet(f"""
            QFrame#activityPanel {{
                background-color: {fondo_color};
                border: 1px solid {borde_color};
                border-radius: 6px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # Barra de encabezado con título y botones de acción ("Cancelar todo" y "Limpiar")
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)
        
        self.lbl_title = QLabel(self.tr("Lista de descargas") if hasattr(self, "tr") else "Lista de descargas")
        self.lbl_title.setStyleSheet(f"color: {get_theme_token('texto_secundario', '#888888')}; font-size: 11px; font-weight: bold;")
        header_layout.addWidget(self.lbl_title)
        
        header_layout.addStretch(1)

        icon_dir = os.path.join(get_src_dir(), "assets", "icons", "svg")

        # Botón "Cancelar todo"
        self.btn_cancel_all = QPushButton(self.tr("Cancelar todo") if hasattr(self, "tr") else "Cancelar todo")
        self.btn_cancel_all.setFixedHeight(22)
        self.btn_cancel_all.setToolTip(self.tr("Cancelar todas las descargas en curso") if hasattr(self, "tr") else "Cancelar todas las descargas en curso")
        _close_icon = os.path.join(icon_dir, "close.svg")
        if os.path.exists(_close_icon):
            self.btn_cancel_all.setIcon(QIcon(_close_icon))
            self.btn_cancel_all.setIconSize(QSize(12, 12))
        self.btn_cancel_all.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {get_theme_token('texto_secundario', '#888888')};
                border: 1px solid {get_theme_token('borde', '#2d2d2d')};
                border-radius: 6px;
                padding: 2px 10px;
                font-size: 10px;
            }}
            QPushButton:hover {{
                background-color: {get_theme_token('fondo_hover', '#2a2a2a')};
                color: #ff6b6b;
                border-color: #ff6b6b;
            }}
        """)
        self.btn_cancel_all.clicked.connect(self.cancel_all_requested.emit)
        header_layout.addWidget(self.btn_cancel_all)

        # Botón "Limpiar"
        self.btn_clear_all = QPushButton(self.tr("Limpiar") if hasattr(self, "tr") else "Limpiar")
        self.btn_clear_all.setFixedHeight(22)
        self.btn_clear_all.setToolTip(self.tr("Limpiar la lista de descargas") if hasattr(self, "tr") else "Limpiar la lista de descargas")
        _delete_icon = os.path.join(icon_dir, "delete.svg")
        if os.path.exists(_delete_icon):
            self.btn_clear_all.setIcon(QIcon(_delete_icon))
            self.btn_clear_all.setIconSize(QSize(14, 14))
        self.btn_clear_all.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {get_theme_token('texto_secundario', '#888888')};
                border: 1px solid {get_theme_token('borde', '#2d2d2d')};
                border-radius: 6px;
                padding: 2px 10px;
                font-size: 10px;
            }}
            QPushButton:hover {{
                background-color: {get_theme_token('fondo_hover', '#2a2a2a')};
                color: {get_theme_token('texto_principal', '#ffffff')};
                border-color: {get_theme_token('borde_focus', '#007acc')};
            }}
        """)
        self.btn_clear_all.clicked.connect(self.clear_all_requested.emit)
        header_layout.addWidget(self.btn_clear_all)

        layout.addLayout(header_layout)
        
        # Línea separadora sutil
        self.header_line = QFrame()
        self.header_line.setFrameShape(QFrame.HLine)
        self.header_line.setFrameShadow(QFrame.Sunken)
        self.header_line.setStyleSheet(f"background-color: {get_theme_token('borde_normal', '#2d2d2d')};")
        self.header_line.setFixedHeight(1)
        layout.addWidget(self.header_line)

        # ScrollArea
        self.activity_scroll = QScrollArea()
        self.activity_scroll.setWidgetResizable(True)
        self.activity_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.activity_scroll.setStyleSheet("border: none; background: transparent;")

        self.activity_container = QWidget()
        self.activity_layout = QVBoxLayout(self.activity_container)
        self.activity_layout.setContentsMargins(0, 0, 0, 0)
        self.activity_layout.setSpacing(8)
        
        # Etiqueta de placeholder cuando no hay descargas
        self.empty_lbl = QLabel(self.tr("Aquí aparecerán tus descargas") if hasattr(self, "tr") else "Aquí aparecerán tus descargas")
        self.empty_lbl.setStyleSheet(f"color: {get_theme_token('texto_secundario', '#888888')}; font-size: 11px;")
        self.empty_lbl.setAlignment(Qt.AlignCenter)
        self.activity_layout.addWidget(self.empty_lbl)
        
        self.activity_layout.addStretch(1)
        self.activity_scroll.setWidget(self.activity_container)
        # Un clic en el hueco entre tarjetas no llega a mousePressEvent de este panel:
        # lo consume el viewport del QScrollArea. Con el filtro, deseleccionar hace clic
        # en cualquier zona vacía de la lista, como en el explorador de archivos.
        self.activity_container.installEventFilter(self)
        self.activity_scroll.viewport().installEventFilter(self)
        layout.addWidget(self.activity_scroll, 1)

    def add_activity_rows(self, entries, selected_indices, group_title=None):
        self.empty_lbl.hide()
        self.btn_cancel_all.show()
        self.btn_clear_all.show()
        
        new_rows = []
        new_keys = []

        # Con más de un elemento se trata de una playlist: sus filas van DENTRO de una
        # tarjeta de grupo plegable en vez de sueltas en la lista. Nueve vídeos ya no
        # inundan el panel, y desplegándola se sigue viendo el estado de cada uno.
        #
        # Lo que se devuelve no cambia: las mismas filas y las mismas claves de siempre.
        # Todo el reparto de progreso por ítem del controlador sigue funcionando sin
        # enterarse de que ahora están agrupadas.
        group = None
        if len(entries) > 1:
            group = PlaylistGroupRow(
                self._playlist_group_title(entries, group_title), len(entries),
                self.activity_container)
            group.close_requested.connect(self._on_group_close)
            group.drag_requested.connect(self._on_group_drag)
            self.activity_layout.insertWidget(self.activity_layout.count() - 1, group)
            self.group_rows.append(group)

        for idx, entry in enumerate(entries):
            title = entry.get("title") or entry.get("id") or entry.get("url") or (self.tr("Item {0}").format(idx + 1) if hasattr(self, "tr") else f"Item {idx + 1}")
            playlist_idx = entry.get("playlist_index") or (selected_indices[idx] + 1 if idx < len(selected_indices) else idx + 1)
            new_keys.append(playlist_idx)

            parent = group.items_container if group else self.activity_container
            row = QuickDownloadRow(str(title), parent)
            row.update_metadata_from_dict(entry)
            row.close_requested.connect(self.row_close_requested.emit)
            row.reveal_requested.connect(self.row_reveal_requested.emit)
            row.selection_requested.connect(self._on_row_selection)
            row.drag_requested.connect(self._on_row_drag)

            if group:
                group.add_row(row)
            else:
                self.activity_layout.insertWidget(self.activity_layout.count() - 1, row)
            self.item_rows.append(row)
            new_rows.append(row)

        if new_rows:
            # Intermitente, no 0%: hasta que llegue el primer byte no hay porcentaje que
            # enseñar, y en YouTube ese arranque tarda lo suficiente como para que una
            # barra parada parezca que la app se colgó.
            new_rows[0].set_waiting(self.tr("Preparando") if hasattr(self, "tr") else "Preparando")

        return new_rows, new_keys

    def _playlist_group_title(self, entries, group_title=None):
        """Nombre de la tarjeta de grupo.

        El título de la lista lo da quien llama, porque en una extracción plana vive en
        el nivel superior del análisis y NO en cada entrada: buscarlo en las entradas
        dejaba la tarjeta llamándose "Playlist" siempre. Se mantiene la búsqueda en las
        entradas como respaldo por si algún extractor sí lo pone ahí."""
        base = self.tr("Playlist") if hasattr(self, "tr") else "Playlist"
        titulo = group_title
        if not titulo:
            for entry in entries:
                titulo = (entry or {}).get("playlist_title") or (entry or {}).get("playlist")
                if titulo:
                    break
        return f'{base}: "{titulo}"' if titulo else base

    def _on_group_close(self, group):
        """La X del grupo cancela/quita sus ítems reutilizando la misma ruta que la X de
        una fila suelta -- así no hay dos lógicas de cancelación que mantener."""
        for row in group.rows():
            self.row_close_requested.emit(row)

    def clear_activity_rows(self):
        for row in self.item_rows:
            if hasattr(row, "destroy_row"):
                row.destroy_row()
            self.activity_layout.removeWidget(row)
            row.deleteLater()
        # Las tarjetas de grupo no están en item_rows (ver __init__): sin esto quedaban
        # en el panel como cascarones vacíos tras vaciar la lista.
        for group in self.group_rows:
            self.activity_layout.removeWidget(group)
            group.deleteLater()
        self.group_rows = []
        self.item_rows = []
        self.item_keys = []
        self.current_item_pos = 0
        self.completed_items = 0
        self._selection_anchor = None
        self.empty_lbl.show()
        self.btn_cancel_all.hide()
        self.btn_clear_all.hide()

    # ------------------------------------------------------------------
    # Selección múltiple y arrastre de resultados hacia otras aplicaciones
    # ------------------------------------------------------------------
    def selected_rows(self):
        return [r for r in self.item_rows if r.is_selected()]

    def clear_selection(self):
        for row in self.item_rows:
            row.set_selected(False)
        self._selection_anchor = None

    def mousePressEvent(self, event):
        """Un clic fuera de las tarjetas deselecciona todo. Los clics sobre una tarjeta
        no llegan aquí: QuickDownloadRow.mousePressEvent los acepta."""
        if event.button() == Qt.LeftButton:
            self.clear_selection()
        super().mousePressEvent(event)

    def eventFilter(self, obj, event):
        if (obj in (self.activity_container, self.activity_scroll.viewport())
                and event.type() == QEvent.MouseButtonPress
                and event.button() == Qt.LeftButton):
            self.clear_selection()
        return super().eventFilter(obj, event)

    def _on_row_selection(self, row, modifiers):
        ctrl = bool(modifiers & Qt.ControlModifier)
        shift = bool(modifiers & Qt.ShiftModifier)

        if shift and self._selection_anchor in self.item_rows:
            start = self.item_rows.index(self._selection_anchor)
            end = self.item_rows.index(row)
            low, high = (start, end) if start <= end else (end, start)
            span = self.item_rows[low:high + 1]
            for candidate in self.item_rows:
                if candidate in span:
                    candidate.set_selected(True)
                elif not ctrl:
                    candidate.set_selected(False)
            return

        if ctrl:
            row.set_selected(not row.is_selected())
            self._selection_anchor = row
            return

        for candidate in self.item_rows:
            candidate.set_selected(candidate is row)
        self._selection_anchor = row

    def _on_row_drag(self, row):
        """Arrastra el resultado completo de las filas terminadas: la que originó el
        gesto y, si formaba parte de una selección, todas las demás seleccionadas. Las
        filas que aún no terminaron (o fallaron) se descartan en vez de cancelar el
        arrastre entero."""
        rows = [r for r in self.selected_rows() if r.is_draggable()]
        if row not in rows:
            # Se arrastró una fila que no estaba seleccionada: manda ella sola.
            rows = [row] if row.is_draggable() else []
        self._start_drag_for_rows(row, rows)

    def _on_group_drag(self, group):
        """Arrastrar la tarjeta de una playlist manda TODOS sus ítems terminados.

        Se ignora la selección a propósito: el gesto es sobre la playlist entera, y es lo
        que se espera al arrastrarla plegada, que es cuando no se ven los ítems."""
        self._start_drag_for_rows(group, group.draggable_rows())

    def _start_drag_for_rows(self, source_widget, rows):
        """Única ruta de arrastre: la comparten una fila suelta y una tarjeta de
        playlist, para que ambas resuelvan los archivos y los duplicados igual."""
        if not rows:
            return

        files, seen = [], set()
        for candidate in rows:
            # Las demás filas de la lista pueden haber bajado a la misma carpeta con
            # nombres emparentados ('Cancion' y 'Cancion_2' en una playlist): sus rutas
            # se pasan para que cada archivo quede con su dueño.
            foreign = [p for other in self.item_rows if other is not candidate
                       for p in other.output_stems()]
            for path in candidate.collect_drag_files(foreign_stems=foreign):
                key = os.path.normcase(path)
                if key not in seen:
                    seen.add(key)
                    files.append(path)

        if not files:
            logger.warning("ActivityPanel: No queda ningún archivo en disco para arrastrar (¿se movieron o borraron?).")
            return

        badge = "" if len(files) == 1 else (
            self.tr("{0} archivos").format(len(files)) if hasattr(self, "tr") else f"{len(files)} archivos"
        )
        start_native_file_drag(source_widget, files, badge_text=badge)

    def _group_of(self, row):
        for group in self.group_rows:
            if row in group.rows():
                return group
        return None

    def _remove_group(self, group):
        if group in self.group_rows:
            self.group_rows.remove(group)
        self.activity_layout.removeWidget(group)
        group.deleteLater()

    def remove_row(self, row):
        if row not in self.item_rows:
            return
        idx = self.item_rows.index(row)
        self.item_rows.pop(idx)
        if self._selection_anchor is row:
            self._selection_anchor = None
        row.destroy_row()
        # Si la fila vivía dentro de una playlist hay que sacarla DE AHÍ: su layout es el
        # del grupo, no el del panel, así que este removeWidget no la tocaría y el grupo
        # seguiría contándola. Y una playlist sin ítems no debe dejar la tarjeta vacía.
        group = self._group_of(row)
        if group:
            group.remove_row(row)
        self.activity_layout.removeWidget(row)
        row.deleteLater()
        if group and group.is_empty():
            self._remove_group(group)

        if not self.item_rows:
            self.empty_lbl.show()
            self.btn_cancel_all.hide()
            self.btn_clear_all.hide()
