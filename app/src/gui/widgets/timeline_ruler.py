"""Widget de regla de tiempo profesional para el editor de subclips."""
from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QColor, QPen, QFont
from gui.styles import get_theme_token


class TimelineRulerWidget(QWidget):
    """Regla de tiempo adaptativa que se sincroniza con la waveform y el scroll.
    
    - Video/Video+Audio: muestra timecode HH:MM:SS:FF
    - Audio: muestra HH:MM:SS.ms (horas solo si duración >= 1h)
    """

    # Intervalos candidatos en segundos para las marcas principales
    _TIME_INTERVALS = [
        0.01, 0.02, 0.05, 0.1, 0.2, 0.5,
        1, 2, 5, 10, 15, 30,
        60, 120, 300, 600, 900, 1800, 3600
    ]

    def __init__(self, media_type: str = "audio", duration_sec: float = 1.0, fps: float = 30.0, parent=None):
        super().__init__(parent)
        self.media_type = media_type.lower()
        self.duration_sec = max(0.001, duration_sec)
        self.fps = fps if fps > 0 else 30.0
        self.is_video = self.media_type in ("video", "video+audio")
        self.show_hours = duration_sec >= 3600.0

        # 18px originales + ~10px extra: con ciertas fuentes del sistema, el texto de las
        # marcas principales (dibujado cerca del borde superior) quedaba cortado por arriba.
        self.setFixedHeight(28)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet("background: transparent;")

        # Estos se actualizan desde el diálogo
        self._scroll_offset = 0  # px de offset del scroll horizontal
        self._waveform_width = 1  # ancho total del widget de waveform (puede ser > viewport)
        self._viewport_width = 1  # ancho visible del viewport

    def set_sync(self, scroll_offset: int, waveform_width: int, viewport_width: int):
        """Actualiza la sincronización con el scroll area."""
        self._scroll_offset = scroll_offset
        self._waveform_width = max(1, waveform_width)
        self._viewport_width = max(1, viewport_width)
        self.update()

    def _choose_interval(self, pixels_per_second: float) -> float:
        """Elige el intervalo de tiempo que deja ~80-150px entre marcas."""
        target_px = 100  # Distancia ideal entre marcas
        target_sec = target_px / max(0.001, pixels_per_second)
        
        best = self._TIME_INTERVALS[-1]
        for interval in self._TIME_INTERVALS:
            if interval >= target_sec:
                best = interval
                break
        return best

    def _format_time(self, seconds: float) -> str:
        """Formatea el tiempo según el tipo de medio."""
        if seconds < 0:
            seconds = 0.0

        if self.is_video:
            # Timecode: HH:MM:SS:FF
            total_frames = int(round(seconds * self.fps))
            ff = total_frames % int(round(self.fps))
            total_sec = total_frames // int(round(self.fps))
            ss = total_sec % 60
            mm = (total_sec // 60) % 60
            hh = total_sec // 3600
            return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"
        else:
            # Tiempo: MM:SS.ms o HH:MM:SS.ms
            ms = int((seconds % 1) * 1000)
            total_sec = int(seconds)
            ss = total_sec % 60
            mm = (total_sec // 60) % 60
            hh = total_sec // 3600
            if self.show_hours:
                return f"{hh:02d}:{mm:02d}:{ss:02d}.{ms:03d}"
            else:
                return f"{mm:02d}:{ss:02d}.{ms:03d}"

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        w = self.width()
        h = self.height()
        if w <= 0 or h <= 0:
            return

        # Línea inferior (separador)
        painter.setPen(QPen(QColor(get_theme_token('onda_cuadricula', '#333333')), 1))
        painter.drawLine(0, h - 1, w, h - 1)

        # Calcular píxeles por segundo
        pixels_per_second = self._waveform_width / self.duration_sec if self.duration_sec > 0 else 1.0
        interval = self._choose_interval(pixels_per_second)

        # Calcular rango de tiempo visible
        time_start = (self._scroll_offset / self._waveform_width) * self.duration_sec if self._waveform_width > 0 else 0
        time_end = ((self._scroll_offset + self._viewport_width) / self._waveform_width) * self.duration_sec if self._waveform_width > 0 else self.duration_sec

        # Primera marca visible (alineada al intervalo)
        first_mark = int(time_start / interval) * interval
        if first_mark < 0:
            first_mark = 0

        # Fuente para texto
        font = QFont()
        font.setPointSize(7)
        font.setBold(False)
        painter.setFont(font)

        # Subdivisiones (4 o 5 sub-marcas entre cada marca principal)
        num_subs = 4
        if self.is_video:
            # Para video, subdividir según fps si el intervalo es 1 segundo
            if interval == 1.0 and self.fps <= 30:
                num_subs = int(round(self.fps)) if self.fps <= 10 else 5
        sub_interval = interval / num_subs

        # Dibujar marcas
        t = first_mark - interval  # Empezar un poco antes para cubrir bordes
        while t <= time_end + interval:
            # Posición en píxeles del waveform
            wave_x = (t / self.duration_sec) * self._waveform_width if self.duration_sec > 0 else 0
            # Posición en el viewport (restando el scroll)
            screen_x = wave_x - self._scroll_offset

            if -50 <= screen_x <= w + 50:
                # Verificar si es marca principal
                is_main = abs(t - round(t / interval) * interval) < (interval * 0.01)

                if is_main and t >= 0:
                    # Marca principal: línea alta + texto
                    painter.setPen(QPen(QColor(get_theme_token('texto_tenue', '#888888')), 1))
                    painter.drawLine(int(screen_x), h - 1, int(screen_x), h - 10)

                    text = self._format_time(t)
                    painter.setPen(QColor(get_theme_token('texto_gris', '#aaaaaa')))
                    painter.drawText(int(screen_x) + 3, h - 12, text)

            # Sub-marcas
            for si in range(1, num_subs):
                st = t + si * sub_interval
                if st < 0 or st > self.duration_sec:
                    continue
                sub_wave_x = (st / self.duration_sec) * self._waveform_width
                sub_screen_x = sub_wave_x - self._scroll_offset
                if 0 <= sub_screen_x <= w:
                    painter.setPen(QPen(QColor(get_theme_token('onda_cuadricula_fuerte', '#444444')), 1))
                    painter.drawLine(int(sub_screen_x), h - 1, int(sub_screen_x), h - 5)

            t += interval

        painter.end()
