# src/gui/tabs/settings/pages/shortcuts_page.py
"""Ajustes > Atajos de teclado: lista las acciones del registro central
(core/utils/shortcuts.py) por sección, con su tecla principal y una alternativa
opcional, y deja cambiarlas. Los cambios se aplican al momento en toda la app."""
from PySide6.QtCore import Qt, Signal, QEvent, QCoreApplication, QSize
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QScrollArea, QPushButton, QMessageBox,
)

from core.utils import shortcuts
from gui.styles import get_theme_token
from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon
from gui.widgets.top_aligned_layout import TopAlignedVBoxLayout

_MODIFIER_KEYS = {Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_AltGr, Qt.Key_CapsLock}


class KeyCaptureButton(QPushButton):
    """Muestra una tecla; al hacer clic espera la combinación nueva. Esc cancela y
    Retroceso deja la tecla vacía. Se captura el teclado entero mientras espera, así
    ninguna otra parte de la app reacciona a la combinación que se está grabando."""
    captured = Signal(str)   # PortableText; "" = vaciar

    def __init__(self, key: str, parent=None):
        super().__init__(parent)
        self._key = key
        self._capturing = False
        self.setFixedHeight(28)
        self.setMinimumWidth(96)
        self.setCursor(Qt.PointingHandCursor)
        self.clicked.connect(self._start_capture)
        self._refresh()

    def set_key(self, key: str):
        self._key = key
        self._refresh()

    def _refresh(self):
        if self._capturing:
            self.setText(self.tr("Presiona…"))
        else:
            self.setText(shortcuts.native_text(self._key) if self._key else "—")
        accent = get_theme_token('acento_primario', '#B9E640')
        border = accent if self._capturing else get_theme_token('borde', '#2d2d2d')
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {get_theme_token('fondo_secundario', '#1e1e1e')};
                color: {get_theme_token('texto_principal', '#ffffff')};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 2px 10px;
                font-weight: bold;
            }}
            QPushButton:hover {{ border-color: {accent}; }}
            QPushButton:disabled {{ color: #777777; background-color: transparent; }}
        """)

    def _start_capture(self):
        self._capturing = True
        self._refresh()
        self.setFocus()
        self.grabKeyboard()

    def _stop_capture(self):
        if self._capturing:
            self._capturing = False
            self.releaseKeyboard()
            self._refresh()

    def event(self, event):
        # Tab/Shift+Tab también se pueden asignar: sin esto Qt los usa para mover el foco.
        if self._capturing and event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Tab, Qt.Key_Backtab):
            self.keyPressEvent(event)
            return True
        return super().event(event)

    def keyPressEvent(self, event):
        if not self._capturing:
            super().keyPressEvent(event)
            return
        key = event.key()
        if key in _MODIFIER_KEYS or key == Qt.Key_unknown:
            return  # esperar la tecla "de verdad" de la combinación
        if key == Qt.Key_Escape and event.modifiers() == Qt.NoModifier:
            self._stop_capture()
            return
        if key == Qt.Key_Backspace and event.modifiers() == Qt.NoModifier:
            self._stop_capture()
            self.captured.emit("")
            return
        seq = QKeySequence(event.keyCombination()).toString(QKeySequence.PortableText)
        self._stop_capture()
        self.captured.emit(seq)

    def focusOutEvent(self, event):
        self._stop_capture()
        super().focusOutEvent(event)


class ShortcutRow(QWidget):
    def __init__(self, act: shortcuts.ShortcutAction, page, parent=None):
        super().__init__(parent)
        self.act = act
        self.page = page
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(8)

        self.lbl = QLabel(act.display_name())
        self.lbl.setWordWrap(True)
        self.lbl.setObjectName("settingsLabel")
        row.addWidget(self.lbl, 1)

        self.key_buttons = []
        for slot in range(shortcuts.MAX_KEYS_PER_ACTION):
            btn = KeyCaptureButton("")
            btn.captured.connect(lambda key, s=slot: self.page.on_key_captured(self.act, s, key))
            row.addWidget(btn)
            self.key_buttons.append(btn)

        # Icono y no "↺": ese carácter no existe en la fuente de la app (salía un cuadrado).
        self.btn_reset = QPushButton()
        icon_color = get_theme_token('texto_principal', '#ffffff')
        self.btn_reset.setIcon(get_colored_svg_icon("refresh.svg", icon_color, size=14))
        self.btn_reset.setIconSize(QSize(14, 14))
        self.btn_reset.setFixedSize(28, 28)
        self.btn_reset.setStyleSheet(f"""
            QPushButton {{
                background-color: {get_theme_token('fondo_secundario', '#1e1e1e')};
                border: 1px solid {get_theme_token('borde', '#2d2d2d')};
                border-radius: 6px;
                padding: 0px;
            }}
            QPushButton:hover {{ border-color: {get_theme_token('acento_primario', '#B9E640')}; }}
            QPushButton:disabled {{ background-color: transparent; border-color: transparent; }}
        """)
        self.btn_reset.setCursor(Qt.PointingHandCursor)
        self.btn_reset.setToolTip(self.tr("Restaurar el valor por defecto"))
        self.btn_reset.clicked.connect(lambda: shortcuts.reset(self.act.id))
        row.addWidget(self.btn_reset)
        self.refresh()

    def refresh(self):
        keys = shortcuts.get_keys(self.act.id)
        for slot, btn in enumerate(self.key_buttons):
            btn.set_key(keys[slot] if slot < len(keys) else "")
            btn.setEnabled(self.act.editable)
            if not self.act.editable:
                btn.setToolTip(self.tr("Atajo fijo"))
            else:
                btn.setToolTip(self.tr("Principal") if slot == 0 else self.tr("Alternativa (opcional)"))
        self.btn_reset.setVisible(self.act.editable)
        self.btn_reset.setEnabled(shortcuts.is_customized(self.act.id))


class ShortcutsPage(QWidget):
    def __init__(self):
        super().__init__()
        self._rows = []

        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(12)

        title = QLabel(self.tr("Atajos de teclado"))
        title.setObjectName("settingsTitle")
        main.addWidget(title)
        line = QFrame()
        line.setObjectName("settingsDivider")
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        main.addWidget(line)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")
        content = QWidget()
        content.setObjectName("settingsScrollContent")
        content.setStyleSheet("QWidget#settingsScrollContent { background-color: transparent; }")
        layout = TopAlignedVBoxLayout(content)
        layout.setContentsMargins(0, 10, 10, 0)
        layout.setSpacing(6)

        hint = QLabel(self.tr(
            "Haz clic en una tecla y presiona la combinación nueva. Retroceso la deja vacía y "
            "Esc cancela. Cada acción admite una tecla principal y una alternativa."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(hint)

        for section_id, section_name in shortcuts.SECTIONS.items():
            lbl = QLabel(QCoreApplication.translate("Shortcuts", section_name))
            lbl.setObjectName("settingsSectionTitle")
            layout.addWidget(lbl)
            for act in shortcuts.ACTIONS:
                if act.section == section_id:
                    row = ShortcutRow(act, self)
                    self._rows.append(row)
                    layout.addWidget(row)

        footer = QHBoxLayout()
        footer.addStretch()
        self.btn_reset_all = QPushButton(self.tr("Restaurar todos"))
        self.btn_reset_all.setCursor(Qt.PointingHandCursor)
        self.btn_reset_all.clicked.connect(self._on_reset_all)
        footer.addWidget(self.btn_reset_all)
        layout.addSpacing(8)
        layout.addLayout(footer)

        scroll.setWidget(content)
        main.addWidget(scroll)

        shortcuts.registry.changed.connect(self._refresh_rows)

    def _refresh_rows(self, *_):
        for row in self._rows:
            row.refresh()

    def _on_reset_all(self):
        reply = QMessageBox.question(
            self, self.tr("Restaurar todos"),
            self.tr("¿Volver todos los atajos a sus valores por defecto?"),
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
        if reply == QMessageBox.Yes:
            shortcuts.reset_all()

    def on_key_captured(self, act: shortcuts.ShortcutAction, slot: int, key: str):
        keys = list(shortcuts.get_keys(act.id))
        while len(keys) <= slot:
            keys.append("")
        previous = keys[slot]
        if key and any(QKeySequence(key) == QKeySequence(k) for i, k in enumerate(keys) if i != slot and k):
            return  # ya es la otra tecla de esta misma acción
        if key:
            other_id = shortcuts.find_conflict(act.section, key, exclude_id=act.id)
            if other_id is not None and not self._resolve_conflict(act, key, previous, other_id):
                return
        keys[slot] = key
        # Si se vacía la principal, la alternativa pasa a ser la principal.
        shortcuts.set_keys(act.id, [k for k in keys if k])

    def _resolve_conflict(self, act, key: str, previous: str, other_id: str) -> bool:
        """La tecla ya la usa otra acción de la misma sección. Fijas: no se tocan.
        Si no: quitársela a la otra, intercambiarlas (la otra recibe la tecla que
        tenía esta), o cancelar."""
        other = shortcuts.action(other_id)
        key_text = shortcuts.native_text(key)
        if not other.editable:
            QMessageBox.information(
                self, self.tr("Atajo reservado"),
                self.tr("«{0}» está reservada para «{1}» y no se puede reasignar.").format(
                    key_text, other.display_name()))
            return False
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle(self.tr("Atajo en uso"))
        box.setText(self.tr("«{0}» ya la usa «{1}».").format(key_text, other.display_name()))
        btn_take = box.addButton(self.tr("Asignarla aquí"), QMessageBox.AcceptRole)
        btn_swap = None
        if previous:
            box.setInformativeText(self.tr(
                "Puedes quitársela a «{0}», o intercambiarlas: «{0}» pasaría a usar «{1}».").format(
                other.display_name(), shortcuts.native_text(previous)))
            btn_swap = box.addButton(self.tr("Intercambiar"), QMessageBox.AcceptRole)
        else:
            box.setInformativeText(self.tr("Si la asignas aquí, «{0}» se quedará sin esa tecla.").format(
                other.display_name()))
        box.addButton(self.tr("Cancelar"), QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked not in (btn_take, btn_swap) or clicked is None:
            return False
        target = QKeySequence(key, QKeySequence.PortableText)
        other_keys = shortcuts.get_keys(other_id)
        replacement = previous if clicked is btn_swap else ""
        new_other = [replacement if QKeySequence(k, QKeySequence.PortableText) == target else k for k in other_keys]
        shortcuts.set_keys(other_id, [k for k in new_other if k])
        return True
