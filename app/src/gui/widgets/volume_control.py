# src/gui/widgets/volume_control.py
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QFrame, QPushButton, QSlider, QStyle, QStyleOptionSlider, QSizePolicy
from PySide6.QtCore import Qt, Signal, QSize, QPoint, QEvent, QTimer
from gui.styles import apply_volume_control_style
from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon


class ClickJumpSlider(QSlider):
    """
    QSlider personalizado que salta inmediatamente a la posición donde se hace clic o arrastra,
    en lugar de avanzar por bloques (pageStep).
    """
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            val = self._calc_value_from_pos(self._event_pos(event))
            self.setValue(val)
            event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            val = self._calc_value_from_pos(self._event_pos(event))
            self.setValue(val)
            event.accept()
        super().mouseMoveEvent(event)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        step = 5 if delta > 0 else -5
        self.setValue(self.value() + step)
        event.accept()

    def _event_pos(self, event) -> float:
        """Coordenada relevante según orientación: x para horizontal, y para vertical.
        Antes siempre usaba .x(), por eso un slider vertical (el popup de volumen)
        calculaba la posición con matemática de eje horizontal — se comportaba errático."""
        p = event.position() if hasattr(event, 'position') else event.pos()
        return p.y() if self.orientation() == Qt.Vertical else p.x()

    def _calc_value_from_pos(self, pos: float):
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        sr = self.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, self)

        is_vertical = self.orientation() == Qt.Vertical
        handle_extent = (sr.height() if is_vertical else sr.width()) if sr.isValid() and sr.width() > 0 and sr.height() > 0 else 10
        total_extent = self.height() if is_vertical else self.width()

        half_handle = handle_extent / 2.0

        if total_extent <= handle_extent:
            return self.minimum()

        usable_extent = total_extent - handle_extent
        clamped_pos = max(half_handle, min(float(pos), total_extent - half_handle))
        ratio = (clamped_pos - half_handle) / usable_extent

        # En un slider vertical, arriba = valor máximo (convención estándar de volumen),
        # así que el ratio calculado desde arriba (0) hay que invertirlo.
        if is_vertical:
            ratio = 1.0 - ratio
        if self.invertedAppearance():
            ratio = 1.0 - ratio

        val = round(self.minimum() + ratio * (self.maximum() - self.minimum()))
        return max(self.minimum(), min(self.maximum(), val))


class VolumeControlWidget(QWidget):
    """
    Widget unificado para el control de volumen en reproductores.
    Incluye un botón de Mute con íconos dinámicos y un QSlider horizontal.
    """
    volume_changed = Signal(float)       # Emite valor flotante (0.0 a 1.0)
    volume_value_changed = Signal(int)   # Emite valor entero (0 a 100)

    def __init__(self, parent=None, initial_volume=70, slider_width=75):
        super().__init__(parent)
        self._last_non_zero_volume = initial_volume if initial_volume > 0 else 70
        self._is_muted = False
        self._compact_mode = False  # True cuando el slider horizontal está oculto (ancho angosto)

        # Fixed en ambos ejes: con Preferred (default), Qt le da a este widget más ancho
        # del que pide su sizeHint cuando conviven con otros widgets de stretch=0 en el
        # mismo layout, corriendo el botón de mute hacia la derecha y dando la ilusión de
        # que el margen respecto al botón de play "se estira" con el tamaño de la ventana.
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # 1. Botón Mute / Alternador de Volumen
        self.btn_mute = QPushButton(self)
        self.btn_mute.setFixedSize(24, 24)
        self.btn_mute.setToolTip(self.tr("Silenciar / Activar sonido"))
        self.btn_mute.clicked.connect(self.toggle_mute)
        self.btn_mute.installEventFilter(self)
        layout.addWidget(self.btn_mute)

        # 2. Slider de Volumen
        self.slider = ClickJumpSlider(Qt.Horizontal, self)
        self.slider.setRange(0, 100)
        self.slider.setFixedWidth(slider_width)
        self.slider.setValue(initial_volume)
        self.slider.valueChanged.connect(self._on_slider_value_changed)
        layout.addWidget(self.slider)

        # 3. Popup flotante con slider vertical: cuando el slider horizontal está oculto
        # (ver set_slider_visible), pasar el mouse sobre el botón de mute (o click) lo
        # muestra — mismo patrón que ya usa Gestor de Medios para el popup de tamaño de
        # cuadrícula (grid_scale_popup), aquí aplicado al volumen.
        self._build_popup()

        # Aplicar estilo inicial de temas
        self._update_ui()

    def _build_popup(self):
        self._popup = QFrame(self, Qt.Tool | Qt.FramelessWindowHint)
        self._popup.setObjectName("volumePopup")
        self._popup.setAttribute(Qt.WA_TranslucentBackground)
        self._popup.installEventFilter(self)
        self._popup.setStyleSheet("""
            QFrame#volumePopup {
                background-color: #181818;
                border: 1px solid #333333;
                border-radius: 10px;
            }
        """)
        popup_layout = QVBoxLayout(self._popup)
        popup_layout.setContentsMargins(4, 10, 4, 10)

        self.popup_slider = ClickJumpSlider(Qt.Vertical, self._popup)
        self.popup_slider.setRange(0, 100)
        self.popup_slider.setFixedHeight(90)
        self.popup_slider.setValue(self.slider.value())
        self.popup_slider.setCursor(Qt.PointingHandCursor)
        self.popup_slider.valueChanged.connect(self.slider.setValue)
        popup_layout.addWidget(self.popup_slider, 0, Qt.AlignHCenter)

        self._popup.hide()

        self._popup_hide_timer = QTimer(self)
        self._popup_hide_timer.setSingleShot(True)
        self._popup_hide_timer.setInterval(400)
        self._popup_hide_timer.timeout.connect(self._popup.hide)

    def set_volume(self, value: int):
        """Establece el nivel de volumen (0 a 100) programáticamente."""
        self.slider.setValue(max(0, min(100, value)))

    def get_volume(self) -> int:
        """Devuelve el nivel actual del slider (0 a 100)."""
        return self.slider.value()

    def set_slider_visible(self, visible: bool):
        """Muestra u oculta el slider horizontal (útil para vistas muy compactas). Al
        ocultarlo, pasar el mouse (o hacer click) sobre el botón de mute muestra un popup
        flotante con un slider vertical, para poder seguir ajustando el volumen sin
        reservarle espacio horizontal permanente a la fila."""
        self.slider.setVisible(visible)
        self._compact_mode = not visible
        if visible:
            self._popup_hide_timer.stop()
            self._popup.hide()

    def is_muted(self) -> bool:
        """Devuelve si el audio está actualmente silenciado."""
        return self._is_muted

    def toggle_mute(self):
        """Alterna el estado de silencio (Mute ON / OFF) con 1 clic."""
        if self._is_muted:
            # Desilenciar: restaurar volumen anterior
            self._is_muted = False
            restore_vol = self._last_non_zero_volume if self._last_non_zero_volume > 0 else 70
            self.slider.setValue(restore_vol)
        else:
            # Silenciar: guardar volumen actual y poner en 0
            curr_vol = self.slider.value()
            if curr_vol > 0:
                self._last_non_zero_volume = curr_vol
            self._is_muted = True
            self.slider.setValue(0)

    def _on_slider_value_changed(self, value: int):
        if value > 0:
            self._last_non_zero_volume = value
            self._is_muted = False
        else:
            self._is_muted = True

        if hasattr(self, "popup_slider") and self.popup_slider.value() != value:
            self.popup_slider.blockSignals(True)
            self.popup_slider.setValue(value)
            self.popup_slider.blockSignals(False)

        self._update_ui()
        self.volume_changed.emit(value / 100.0)
        self.volume_value_changed.emit(value)

    def eventFilter(self, obj, event):
        if obj is self.btn_mute and self._compact_mode:
            if event.type() == QEvent.Enter:
                self._popup_hide_timer.stop()
                self._show_popup()
            elif event.type() == QEvent.Leave:
                self._popup_hide_timer.start()
        elif obj is self._popup:
            if event.type() == QEvent.Enter:
                self._popup_hide_timer.stop()
            elif event.type() == QEvent.Leave:
                self._popup_hide_timer.start()
        return super().eventFilter(obj, event)

    def _show_popup(self):
        self.popup_slider.blockSignals(True)
        self.popup_slider.setValue(self.slider.value())
        self.popup_slider.blockSignals(False)
        self._popup.adjustSize()
        anchor = self.btn_mute.mapToGlobal(QPoint(0, 0))
        x = anchor.x() - (self._popup.width() - self.btn_mute.width()) // 2
        y = anchor.y() - self._popup.height() - 6
        self._popup.move(x, y)
        self._popup.show()
        self._popup.raise_()

    def _update_ui(self):
        """Actualiza el ícono del botón y aplica los estilos del tema."""
        val = self.slider.value()

        if self._is_muted or val == 0:
            icon_name = "volume_off.svg" if self._is_muted else "volume_mute.svg"
            icon_color = "#6c7086"
        elif val < 50:
            icon_name = "volume_down.svg"
            icon_color = "#cdd6f4"
        else:
            icon_name = "volume_up.svg"
            icon_color = "#cdd6f4"

        self.btn_mute.setIcon(get_colored_svg_icon(icon_name, icon_color, size=16))
        self.btn_mute.setIconSize(QSize(16, 16))

        # Aplicar estilos unificados de tema desde styles.py
        apply_volume_control_style(self.btn_mute, self.slider)
