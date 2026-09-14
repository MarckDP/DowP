# src/gui/widgets/mode_selector.py
from PySide6.QtWidgets import QFrame, QWidget, QHBoxLayout, QPushButton
from PySide6.QtCore import Signal, QPropertyAnimation, QEasingCurve, QRect, QT_TRANSLATE_NOOP
from core.logger.logger_manager import logger

class ModeSelector(QFrame):
    mode_changed = Signal(str)

    # Etiquetas por defecto: preserva 1:1 el selector de 3 botones que ya usa la pestaña
    # Avanzado (Video+Audio/Solo Audio/Solo Video) para quien no pase `labels` explicito.
    _DEFAULT_LABELS = (QT_TRANSLATE_NOOP("ModeSelector", "Video + Audio"), QT_TRANSLATE_NOOP("ModeSelector", "Solo Audio"), QT_TRANSLATE_NOOP("ModeSelector", "Solo Video"))
    _DEFAULT_COMPACT_LABELS = ("V + A", "A", "V")

    def __init__(self, parent=None, labels: list[str] | None = None, compact_labels: list[str] | None = None):
        super().__init__(parent)
        # Las etiquetas por defecto se traducen aquí (mismo comportamiento de siempre); las
        # etiquetas pasadas por el llamador ya vienen traducidas por ese widget (su propio
        # self.tr()) - envolverlas de nuevo aquí las buscaría en el contexto de traduccion
        # equivocado (ModeSelector, no el widget que las definio).
        self._labels = list(labels) if labels else [self.tr(l) for l in self._DEFAULT_LABELS]
        if compact_labels:
            self._compact_labels = list(compact_labels)
        elif not labels:
            self._compact_labels = list(self._DEFAULT_COMPACT_LABELS)
        else:
            self._compact_labels = list(self._labels)
        self._is_compact = False
        self.init_ui()

    def init_ui(self):
        self.setObjectName("modeSelectorContainer")
        self.setFixedHeight(38)

        # Indicator frame that slides
        self.bg_indicator = QFrame(self)
        self.bg_indicator.setObjectName("modeIndicator")
        self.bg_indicator.hide() # Hidden until first layout/resize

        # Layout for buttons
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)

        self.buttons = []
        for label in self._labels:
            btn = QPushButton(label, self)
            btn.setObjectName("modeButton")
            btn.setCheckable(True)
            btn.setFixedHeight(30)
            btn.setToolTip(label)
            btn.clicked.connect(self.on_button_clicked)
            layout.addWidget(btn)
            self.buttons.append(btn)

        # Alias retrocompatibles: codigo existente (AdvancedRecodePanel) referencia estos
        # 3 nombres directo en vez de indexar self.buttons.
        if len(self.buttons) >= 3:
            self.btn_video_audio, self.btn_audio, self.btn_video = self.buttons[:3]

        if self.buttons:
            self.buttons[0].setChecked(True)
            self.buttons[0].setProperty("active", "true")

        self.animation = None

    def _update_labels_for_size(self):
        if not self.buttons or self._compact_labels == self._labels:
            return
        fm = self.fontMetrics()
        # Ancho necesario para mostrar todas las etiquetas completas holgadamente
        total_full_w = sum(fm.horizontalAdvance(l) + 24 for l in self._labels) + 12
        use_compact = self.width() > 0 and self.width() < total_full_w

        if use_compact != self._is_compact:
            self._is_compact = use_compact
            texts = self._compact_labels if use_compact else self._labels
            for i, btn in enumerate(self.buttons):
                btn.setText(texts[i])
                btn.setToolTip(self._labels[i])

    def on_button_clicked(self):
        sender = self.sender()
        if not sender: return
        
        idx = -1
        for i, btn in enumerate(self.buttons):
            is_active = (btn == sender)
            btn.setChecked(is_active)
            btn.setProperty("active", "true" if is_active else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            if is_active:
                idx = i
        
        self.animate_indicator(sender)
        if idx >= 0 and idx < len(self._labels):
            self.mode_changed.emit(self._labels[idx])

    def animate_indicator(self, button):
        self.bg_indicator.show()
        if self.animation:
            self.animation.stop()
            
        self.animation = QPropertyAnimation(self.bg_indicator, b"geometry")
        self.animation.setDuration(250)
        self.animation.setStartValue(self.bg_indicator.geometry())
        self.animation.setEndValue(button.geometry())
        self.animation.setEasingCurve(QEasingCurve.InOutCubic)
        self.animation.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_labels_for_size()
        # Snap indicator to the active button immediately on resize
        for btn in self.buttons:
            if btn.isChecked():
                self.bg_indicator.setGeometry(btn.geometry())
                self.bg_indicator.show()
                break

    def showEvent(self, event):
        super().showEvent(event)
        self._update_labels_for_size()
        for btn in self.buttons:
            if btn.isChecked():
                self.bg_indicator.setGeometry(btn.geometry())
                self.bg_indicator.show()
                break

    def current_mode(self):
        for i, btn in enumerate(self.buttons):
            if btn.isChecked():
                return self._labels[i]
        return self._labels[0] if self._labels else ""

    def set_mode(self, mode_text: str):
        for i, btn in enumerate(self.buttons):
            if (self._labels[i] == mode_text or 
                (i < len(self._compact_labels) and self._compact_labels[i] == mode_text) or 
                btn.text() == mode_text):
                btn.click()
                break
