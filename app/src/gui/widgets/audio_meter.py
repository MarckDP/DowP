import math
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QColor, QLinearGradient
from gui.styles import get_theme_token

_MIN_DB = -60.0

def _linear_to_db_ratio(linear_val: float, min_db: float = _MIN_DB) -> float:
    """Convierte un valor de amplitud lineal (0.0 a 1.0) a una posición normalizada (0.0 a 1.0)
    en una escala logarítmica de decibelios (dBFS) estilo Premiere Pro / DaVinci Resolve."""
    if linear_val <= 0.00001:
        return 0.0
    try:
        db = 20.0 * math.log10(linear_val)
    except Exception:
        return 0.0
    if db <= min_db:
        return 0.0
    if db >= 0.0:
        return 1.0
    return (db - min_db) / (0.0 - min_db)


class AudioVolumeMeterWidget(QWidget):
    """Medidor de volumen vertical en decibelios (simulado)."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(36)
        self.setMinimumHeight(50)
        self._level = 0.0  # 0.0 a 1.0
        self._peak = 0.0
        self._peak_decay = 0.0

    def set_level(self, level: float):
        """Asigna el nivel de volumen lineal (0.0 a 1.0)."""
        self._level = max(0.0, min(level, 1.0))
        if self._level >= self._peak:
            self._peak = self._level
            self._peak_decay = 0.01
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        w = self.width()
        h = self.height()
        
        if h <= 0:
            return
            
        bar_w = 14
        bar_x = w - bar_w - 2 # A la derecha
        
        # Borde
        painter.setPen(QColor(get_theme_token('borde', '#2d2d2d')))
        painter.drawRect(bar_x, 0, bar_w, h - 1)
            
        # Gradiente profesional calibrado en dB
        grad = QLinearGradient(0, h, 0, 0)
        grad.setColorAt(0.0, QColor("#1DC038"))   # Verde en -60 dB
        grad.setColorAt(0.70, QColor("#1DC038"))  # Verde hasta -18 dB
        grad.setColorAt(0.85, QColor(get_theme_token('estado_aviso', '#FFC107')))  # Amarillo en -9 dB
        grad.setColorAt(0.95, QColor("#FF8800"))  # Naranja en -3 dB
        grad.setColorAt(1.0, QColor("#FF4444"))   # Rojo en 0 dB
        
        # Dibujar nivel actual calibrado logarítmicamente
        ratio = _linear_to_db_ratio(self._level)
        level_h = ratio * h
        y_level = h - level_h
        if level_h > 0:
            painter.fillRect(bar_x + 1, int(y_level), bar_w - 1, int(level_h), grad)
        
        # Caída de pico
        if self._peak > 0:
            peak_ratio = _linear_to_db_ratio(self._peak)
            if peak_ratio > 0:
                y_peak = int(h - peak_ratio * h)
                painter.fillRect(bar_x + 1, y_peak, bar_w - 1, 2, QColor(get_theme_token('cabezal', '#FFFFFF')))
            
            # Decaimiento del pico para animación suave
            if self._peak > self._level:
                self._peak -= 0.015
                if self._peak < self._level:
                    self._peak = self._level

        # Dibujar marcas y texto (dB) exactamente calibradas en la escala logarítmica
        font = painter.font()
        font.setPointSize(6)
        font.setBold(False)
        painter.setFont(font)

        # Sub-ticks cada 3 dB
        painter.setPen(QColor(get_theme_token('onda_cuadricula_fuerte', '#444444')))
        for db_sub in range(0, int(_MIN_DB), -3):
            if db_sub % 6 != 0:
                r_sub = (db_sub - _MIN_DB) / (0.0 - _MIN_DB)
                y_sub = int(h - (r_sub * h))
                if 2 <= y_sub <= h - 2:
                    painter.drawLine(bar_x - 2, y_sub, bar_x, y_sub)

        # Ticks principales cada 6 dB equidistantes
        db_marks = [0, -6, -12, -18, -24, -30, -36, -42, -48, -54]
        for db_val in db_marks:
            r = (db_val - _MIN_DB) / (0.0 - _MIN_DB)
            y = int(h - (r * h))
            if y >= h - 1: y = h - 2
            if y <= 5: y = 7

            painter.setPen(QColor(get_theme_token('texto_apagado', '#777777')))
            painter.drawLine(bar_x - 4, y, bar_x, y)

            text = str(db_val)
            painter.setPen(QColor(get_theme_token('texto_gris', '#999999')))
            text_rect = painter.boundingRect(0, y - 5, bar_x - 5, 10, Qt.AlignRight | Qt.AlignVCenter, text)
            painter.drawText(text_rect, Qt.AlignRight | Qt.AlignVCenter, text)


class MultiChannelMeterWidget(QWidget):
    """Medidor de volumen con una barra vertical POR CANAL calibrado en escala profesional dBFS:
    1 barra si el audio es mono, 2 si es estéreo, 6 si es 5.1, 8 si es 7.1, etc.

    La escala en dB se dibuja una sola vez a la izquierda (compartida por todas las barras)
    para no repetir el texto por cada canal y mantener el widget compacto."""

    _LABEL_W = 24
    _BAR_W = 10
    _BAR_GAP = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self._channel_count = 2
        self._levels = [0.0, 0.0]
        self._peaks = [0.0, 0.0]
        self.setMinimumHeight(50)
        self._update_fixed_width()

    def channel_count(self) -> int:
        return self._channel_count

    def set_channel_count(self, count: int):
        count = max(1, int(count))
        if count == self._channel_count:
            return
        self._channel_count = count
        self._levels = [0.0] * count
        self._peaks = [0.0] * count
        self._update_fixed_width()
        self.update()

    def _update_fixed_width(self):
        self.setFixedWidth(self._LABEL_W + self._channel_count * (self._BAR_W + self._BAR_GAP))

    def set_levels(self, levels):
        """Asigna el nivel lineal (0.0 a 1.0) de cada canal. Si `levels` trae menos valores
        que canales tiene el medidor, los canales sobrantes se consideran en silencio."""
        for i in range(self._channel_count):
            lvl = max(0.0, min(levels[i], 1.0)) if i < len(levels) else 0.0
            self._levels[i] = lvl
            if lvl >= self._peaks[i]:
                self._peaks[i] = lvl
        self.update()

    def reset_levels(self):
        """Silencia el medidor (p.ej. al pausar/detener la reproducción)."""
        self._levels = [0.0] * self._channel_count
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()

        if h <= 0:
            return

        # Gradiente profesional calibrado en dB (0 a -60 dBFS)
        grad = QLinearGradient(0, h, 0, 0)
        grad.setColorAt(0.0, QColor("#1DC038"))   # Verde en -60 dB
        grad.setColorAt(0.70, QColor("#1DC038"))  # Verde hasta -18 dB
        grad.setColorAt(0.85, QColor(get_theme_token('estado_aviso', '#FFC107')))  # Amarillo en -9 dB
        grad.setColorAt(0.95, QColor("#FF8800"))  # Naranja en -3 dB
        grad.setColorAt(1.0, QColor("#FF4444"))   # Rojo en 0 dB

        # Escala en dB, compartida a la izquierda de todas las barras
        font = painter.font()
        font.setPointSize(6)
        font.setBold(False)
        painter.setFont(font)

        bar_x = self._LABEL_W

        # Dibujar sub-ticks cada 3 dB para aspecto de regla milimétrica profesional
        painter.setPen(QColor(get_theme_token('onda_cuadricula_fuerte', '#444444')))
        for db_sub in range(0, int(_MIN_DB), -3):
            if db_sub % 6 != 0:
                r_sub = (db_sub - _MIN_DB) / (0.0 - _MIN_DB)
                y_sub = int(h - (r_sub * h))
                if 2 <= y_sub <= h - 2:
                    painter.drawLine(bar_x - 2, y_sub, bar_x, y_sub)

        # Ticks principales cada 6 dB equidistantes con sus números
        db_marks = [0, -6, -12, -18, -24, -30, -36, -42, -48, -54]
        for db_val in db_marks:
            r = (db_val - _MIN_DB) / (0.0 - _MIN_DB)
            y = int(h - (r * h))
            if y >= h - 1: y = h - 2
            if y <= 5: y = 7

            painter.setPen(QColor(get_theme_token('texto_apagado', '#777777')))
            painter.drawLine(bar_x - 4, y, bar_x, y)

            text = str(db_val)
            painter.setPen(QColor(get_theme_token('texto_gris', '#999999')))
            text_rect = painter.boundingRect(0, y - 5, self._LABEL_W - 5, 10, Qt.AlignRight | Qt.AlignVCenter, text)
            painter.drawText(text_rect, Qt.AlignRight | Qt.AlignVCenter, text)

        # Una barra por canal
        for i in range(self._channel_count):
            bar_x = self._LABEL_W + i * (self._BAR_W + self._BAR_GAP)

            # Fondo / borde de la barra
            painter.setPen(QColor(get_theme_token('borde', '#2d2d2d')))
            painter.drawRect(bar_x, 0, self._BAR_W, h - 1)

            # Dibujar nivel en dB
            level = self._levels[i]
            ratio = _linear_to_db_ratio(level)
            level_h = ratio * h
            y_level = h - level_h
            if level_h > 0:
                painter.fillRect(bar_x + 1, int(y_level), self._BAR_W - 1, int(level_h), grad)

            # Marca de pico (peak decay)
            peak = self._peaks[i]
            if peak > 0:
                peak_ratio = _linear_to_db_ratio(peak)
                if peak_ratio > 0:
                    y_peak = int(h - peak_ratio * h)
                    painter.fillRect(bar_x + 1, y_peak, self._BAR_W - 1, 2, QColor(get_theme_token('cabezal', '#FFFFFF')))

                if peak > level:
                    self._peaks[i] -= 0.015
                    if self._peaks[i] < level:
                        self._peaks[i] = level
