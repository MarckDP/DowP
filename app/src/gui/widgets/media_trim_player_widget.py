# -*- coding: utf-8 -*-
# src/gui/widgets/media_trim_player_widget.py
import os
import math
import array
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QFrame, QSizePolicy, QScrollArea, QSlider, QGraphicsView, QGraphicsScene,
    QToolButton, QMenu, QCheckBox, QGraphicsObject
)
from PySide6.QtCore import Qt, QUrl, QSize, QSizeF, QPointF, QTimer, Signal, QEvent, QRectF, QT_TRANSLATE_NOOP
from PySide6.QtGui import QPainter, QColor, QPen, QPainterPath, QPixmap, QImage, QFont, QFontMetricsF
from PySide6.QtMultimedia import (
    QMediaPlayer, QAudioOutput, QMediaMetaData, QAudioBufferOutput, QAudioFormat
)
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem

from gui.styles import get_theme_token, apply_player_play_button_style
from gui.tabs.editing_media.editing_media_icons import get_svg_icon, get_colored_svg_icon
from gui.widgets.timeline_ruler import TimelineRulerWidget
from gui.widgets.audio_meter import MultiChannelMeterWidget
from gui.widgets.volume_control import VolumeControlWidget
from core.tabs.editing_media.waveform_cache_manager import WaveformCacheManager
from core.tabs.video_tools.proxy_cache_manager import ProxyCacheManager
from core.logger.logger_manager import logger

# Opciones del selector de calidad de previsualización: (etiqueta, modo, divisor).
# modo "auto" recalcula el divisor según la resolución nativa real del video (ver
# _compute_auto_divisor); modo "manual" fuerza el divisor elegido por el usuario.
_QUALITY_OPTIONS = [
    (QT_TRANSLATE_NOOP("MediaTrimPlayerWidget", "Auto"), "auto", None),
    (QT_TRANSLATE_NOOP("MediaTrimPlayerWidget", "Completa"), "manual", 1),
    ("1/2", "manual", 2),
    ("1/4", "manual", 4),
    ("1/8", "manual", 8),
]

# (typecode, bytes_per_sample, offset, scale) para convertir muestras PCM crudas a -1.0..1.0
# según el QAudioFormat.SampleFormat que entregue el backend de Qt Multimedia en cada buffer.
_SAMPLE_FORMAT_INFO = {
    QAudioFormat.SampleFormat.UInt8: ('B', 1, 128.0, 128.0),
    QAudioFormat.SampleFormat.Int16: ('h', 2, 0.0, 32768.0),
    QAudioFormat.SampleFormat.Int32: ('i', 4, 0.0, 2147483648.0),
    QAudioFormat.SampleFormat.Float: ('f', 4, 0.0, 1.0),
}


def _channel_peaks_from_buffer(buf) -> list:
    """Calcula el pico lineal (0.0-1.0) de cada canal de un QAudioBuffer entregado en vivo
    durante la reproducción, respetando el conteo real de canales y el formato de muestra."""
    fmt = buf.format()
    channels = fmt.channelCount()
    if channels <= 0:
        return []

    info = _SAMPLE_FORMAT_INFO.get(fmt.sampleFormat())
    if info is None:
        return [0.0] * channels
    typecode, sample_bytes, offset, scale = info

    raw = bytes(buf.constData())
    usable_len = (len(raw) // sample_bytes) * sample_bytes
    if usable_len < sample_bytes * channels:
        return [0.0] * channels

    try:
        samples = array.array(typecode)
        samples.frombytes(raw[:usable_len])
    except Exception:
        return [0.0] * channels

    peaks = []
    for ch in range(channels):
        channel_samples = samples[ch::channels]
        if channel_samples:
            peak_raw = max(abs(max(channel_samples) - offset), abs(min(channel_samples) - offset))
            peaks.append(min(peak_raw / scale, 1.0))
        else:
            peaks.append(0.0)
    return peaks


class TrimWaveformWidget(QWidget):
    """Forma de onda profesional con pares min/max, estilo SoundQ/Premiere.

    Clic izquierdo: seek / arrastrar handles In-Out / arrastrar el rango completo.
    Clic derecho + arrastre: seleccionar un nuevo rango In-Out desde cero.
    """

    seek_requested = Signal(float)
    range_changed = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.in_ratio = 0.0
        self.out_ratio = 1.0
        self._drag_mode = "none"
        self._drag_offset = 0.0
        self.zoom_y = 1.0
        self._playback_ratio = 0.0

        # Datos de alta resolución: lista de tuplas (min, max) normalizadas -1..1
        self._hires_peaks = []  # Datos crudos de alta res
        self._display_peaks = []  # Re-muestreados al ancho actual

        # Rangos (in_ratio, out_ratio) de subclips ya guardados, para mostrarlos de fondo
        # con baja opacidad mientras se crea uno nuevo.
        self._saved_subclip_ratios = []

        self.is_loading = False
        self.loading_phase = 0.0
        self.audio_path = ""

        # Estados de descarga en alta calidad (medios remotos pendientes) y error
        self.is_downloading = False
        self.is_error = False
        self.error_message = ""

        self.setMinimumHeight(50)
        self.setMaximumHeight(16777215)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.loading_timer = QTimer(self)
        self.loading_timer.setInterval(30)
        self.loading_timer.timeout.connect(self._animate_loading)

    def set_loading(self, loading: bool):
        self.is_loading = loading
        if loading:
            self._hires_peaks = []
            self._display_peaks = []
            if not self.loading_timer.isActive():
                self.loading_timer.start()
        else:
            self.loading_timer.stop()
        self.update()

    def _animate_loading(self):
        self.loading_phase += 0.15
        if self.loading_phase > 2 * math.pi:
            self.loading_phase -= 2 * math.pi
        self.update()

    def set_downloading(self, downloading: bool):
        """Activa/desactiva la animación de 'descargando medio en alta calidad', distinta a la de carga de waveform local."""
        self.is_downloading = downloading
        if downloading:
            self.is_error = False
            self._hires_peaks = []
            self._display_peaks = []
            if not self.loading_timer.isActive():
                self.loading_timer.start()
        elif not self.is_loading:
            self.loading_timer.stop()
        self.update()

    def hideEvent(self, event):
        super().hideEvent(event)
        if hasattr(self, "loading_timer") and self.loading_timer.isActive():
            self.loading_timer.stop()

    def set_error(self, is_error: bool, message: str = ""):
        """Muestra un estado de error (p.ej. falló la descarga en alta calidad) en la zona de la waveform."""
        self.is_error = is_error
        self.error_message = message
        if is_error:
            self.is_downloading = False
            self.is_loading = False
            self.loading_timer.stop()
        self.update()

    def set_audio_path(self, path: str):
        self.audio_path = path or ""
        self._hires_peaks = []
        self._display_peaks = []
        if not path:
            self.set_loading(False)
        self.update()

    def set_hires_peaks(self, peaks: list):
        """Asigna picos min/max de alta resolución y re-muestrea."""
        self._hires_peaks = list(peaks) if peaks else []
        self._resample_to_width()
        self.set_loading(False)
        self.update()

    def _resample_to_width(self):
        """Re-muestrea _hires_peaks al número de columnas de píxeles del widget."""
        if not self._hires_peaks:
            self._display_peaks = []
            return
        w = self.width()
        if w <= 0:
            return
        n = len(self._hires_peaks)
        target = w  # 1 columna por píxel
        if n == target:
            self._display_peaks = list(self._hires_peaks)
            return

        self._display_peaks = []
        if target <= n:
            # Downsampling: tomar el pico mínimo y máximo del bloque
            for i in range(target):
                start_f = i * n / target
                end_f = (i + 1) * n / target
                start_idx = int(start_f)
                end_idx = max(start_idx + 1, int(end_f))
                end_idx = min(end_idx, n)

                block_min = 0.0
                block_max = 0.0
                for j in range(start_idx, end_idx):
                    mn, mx = self._hires_peaks[j]
                    if mn < block_min:
                        block_min = mn
                    if mx > block_max:
                        block_max = mx
                self._display_peaks.append((block_min, block_max))
        else:
            # Upsampling (Zoom in profundo): Interpolación lineal suave entre picos
            for i in range(target):
                pos = i * (n - 1) / max(1, target - 1)
                idx = int(pos)
                frac = pos - idx
                if idx >= n - 1:
                    self._display_peaks.append(self._hires_peaks[-1])
                else:
                    mn1, mx1 = self._hires_peaks[idx]
                    mn2, mx2 = self._hires_peaks[idx + 1]
                    interp_min = mn1 * (1.0 - frac) + mn2 * frac
                    interp_max = mx1 * (1.0 - frac) + mx2 * frac
                    self._display_peaks.append((interp_min, interp_max))

    def resizeEvent(self, event):
        self._resample_to_width()
        self.update()

    def set_range_ratios(self, in_r: float, out_r: float):
        self.in_ratio = max(0.0, min(in_r, 1.0))
        self.out_ratio = max(self.in_ratio, min(out_r, 1.0))
        self.update()

    def set_saved_subclip_ratios(self, ranges: list):
        """Actualiza los rangos (in_ratio, out_ratio) de los subclips ya guardados, dibujados
        de fondo con baja opacidad para poder ver cuántos hay y dónde están mientras se crean más."""
        self._saved_subclip_ratios = list(ranges) if ranges else []
        self.update()

    def set_playback_ratio(self, ratio: float):
        self._playback_ratio = max(0.0, min(ratio, 1.0))
        self.update()

    def get_playback_ratio(self) -> float:
        return self._playback_ratio

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            w = self.width()
            if w <= 0:
                return
            x = event.position().x()
            y = event.position().y()
            ratio = max(0.0, min(x / w, 1.0))

            x_in = self.in_ratio * w
            x_out = self.out_ratio * w

            if abs(x - x_in) <= 10:
                self._drag_mode = "in"
            elif abs(x - x_out) <= 10:
                self._drag_mode = "out"
            elif y <= 16 and x_in <= x <= x_out:
                # Arrastrar el rango de selección desde la barra/agarrador superior sin mover el playhead
                self._drag_mode = "range"
                self._drag_offset = ratio - self.in_ratio
            else:
                self._drag_mode = "none"
                self.seek_requested.emit(ratio)

        elif event.button() == Qt.RightButton:
            w = self.width()
            if w > 0:
                x = event.position().x()
                ratio = max(0.0, min(x / w, 1.0))
                self._drag_mode = "right_click_select"
                self._right_click_start = ratio
                self.in_ratio = ratio
                self.out_ratio = ratio
                self.range_changed.emit(self.in_ratio, self.out_ratio)
                self.update()

    def mouseMoveEvent(self, event):
        w = self.width()
        if w <= 0:
            return
        x = event.position().x()
        y = event.position().y()
        ratio = max(0.0, min(x / w, 1.0))
        x_in = self.in_ratio * w
        x_out = self.out_ratio * w

        if event.buttons() & Qt.LeftButton:
            if self._drag_mode == "in":
                self.in_ratio = min(ratio, self.out_ratio - 0.01)
                self.range_changed.emit(self.in_ratio, self.out_ratio)
                self.update()
            elif self._drag_mode == "out":
                self.out_ratio = max(ratio, self.in_ratio + 0.01)
                self.range_changed.emit(self.in_ratio, self.out_ratio)
                self.update()
            elif self._drag_mode == "range":
                range_span = self.out_ratio - self.in_ratio
                new_in = max(0.0, min(ratio - self._drag_offset, 1.0 - range_span))
                self.in_ratio = new_in
                self.out_ratio = new_in + range_span
                self.range_changed.emit(self.in_ratio, self.out_ratio)
                self.update()
            else:
                self.seek_requested.emit(ratio)
        elif event.buttons() & Qt.RightButton:
            if getattr(self, "_drag_mode", "") == "right_click_select":
                start_r = getattr(self, "_right_click_start", ratio)
                self.in_ratio = min(start_r, ratio)
                self.out_ratio = max(start_r, ratio)
                # Para evitar que el rango sea 0 si soltamos en el mismo pixel
                if self.in_ratio == self.out_ratio:
                    self.out_ratio = min(self.in_ratio + 0.001, 1.0)
                self.range_changed.emit(self.in_ratio, self.out_ratio)
                self.update()
        else:
            # Feedback visual de cursores al pasar por encima
            if abs(x - x_in) <= 10 or abs(x - x_out) <= 10:
                self.setCursor(Qt.SizeHorCursor)
            elif y <= 16 and x_in <= x <= x_out:
                self.setCursor(Qt.SizeAllCursor)
            else:
                self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.RightButton:
            if getattr(self, "_drag_mode", "") == "right_click_select":
                # Si el usuario solo hizo clic (sin arrastrar) reseteamos el In/Out
                if abs(self.in_ratio - self.out_ratio) < 0.005:
                    self.in_ratio = 0.0
                    self.out_ratio = 1.0
                    self.range_changed.emit(self.in_ratio, self.out_ratio)
                    self.update()
        self._drag_mode = "none"

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            w = self.width()
            if w <= 0:
                return
            x = event.position().x()
            y = event.position().y()

            x_in = self.in_ratio * w
            x_out = self.out_ratio * w

            # Si hace doble clic en el área del agarrador superior, resetear in/out
            if y <= 16 and x_in <= x <= x_out:
                self.in_ratio = 0.0
                self.out_ratio = 1.0
                self.range_changed.emit(self.in_ratio, self.out_ratio)
                self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)  # Líneas nítidas

        w = self.width()
        h = self.height()
        if w <= 0 or h <= 0:
            return

        # Autocorrección: si ya tenemos picos crudos pero todavía no se remuestrearon a
        # columnas de píxeles, es porque llegaron (set_hires_peaks) mientras el widget aún
        # no tenía un ancho real asignado por el layout (p.ej. primera carga, tab recién
        # mostrado). _resample_to_width() se queda callado en ese caso y nada lo reintentaba
        # después, dejando el waveform en blanco hasta la próxima carga. Como paintEvent solo
        # se dispara con un tamaño ya válido, es el lugar seguro para completar el remuestreo.
        if self._hires_peaks and not self._display_peaks:
            self._resample_to_width()

        if self._display_peaks and self.is_loading:
            self.is_loading = False
            if hasattr(self, "loading_timer") and self.loading_timer.isActive():
                self.loading_timer.stop()

        # Fondo oscuro
        painter.fillRect(0, 0, w, h, QColor("#0d0d0d"))

        mid_y = h / 2.0
        x_in = int(self.in_ratio * w)
        x_out = int(self.out_ratio * w)

        # Subclips ya guardados: franjas de baja opacidad de fondo, para ver cuántos hay
        # y dónde están mientras se crea uno nuevo.
        saved_color = QColor(64, 169, 230, 45)
        saved_border = QPen(QColor(64, 169, 230, 120), 1, Qt.DashLine)
        for sub_in_r, sub_out_r in self._saved_subclip_ratios:
            sx_in = int(sub_in_r * w)
            sx_out = int(sub_out_r * w)
            painter.fillRect(sx_in, 0, max(1, sx_out - sx_in), h, saved_color)
            painter.setPen(saved_border)
            painter.drawLine(sx_in, 0, sx_in, h)
            painter.drawLine(sx_out, 0, sx_out, h)

        # Fondo sutil de la zona seleccionada
        highlight = QColor(185, 230, 64, 15)
        painter.fillRect(x_in, 0, max(1, x_out - x_in), h, highlight)

        # Línea central (eje 0)
        painter.setPen(QPen(QColor(60, 60, 60), 1))
        painter.drawLine(0, int(mid_y), w, int(mid_y))

        if self.is_downloading:
            # Animación de "descargando medio en alta calidad" (distinta a la carga de waveform local):
            # barra de progreso indeterminada que recorre el ancho del widget.
            bar_h = 4
            bar_y = int(mid_y - bar_h / 2)
            painter.fillRect(0, bar_y, w, bar_h, QColor(40, 40, 40))
            sweep_w = max(40, int(w * 0.18))
            phase_ratio = (math.sin(self.loading_phase) + 1) / 2.0  # 0..1
            sweep_x = int(phase_ratio * max(1, w - sweep_w))
            painter.fillRect(sweep_x, bar_y, sweep_w, bar_h, QColor(get_theme_token('acento_primario', '#B9E640')))

            painter.setPen(QPen(QColor('#cdd6f4')))
            painter.drawText(self.rect(), Qt.AlignCenter, self.tr("Descargando medio en alta calidad..."))
        elif self.is_error:
            painter.setPen(QPen(QColor('#FF5555'), 1))
            painter.drawLine(0, int(mid_y), w, int(mid_y))
            painter.setPen(QPen(QColor('#FF8888')))
            msg = self.error_message or self.tr("Error al descargar el medio en alta calidad.")
            painter.drawText(self.rect(), Qt.AlignCenter, self.tr("Error al descargar el medio en alta calidad.\n{0}").format(msg) if self.error_message else msg)
        elif self.is_loading:
            # Animación de carga: onda sinusoidal
            pen = QPen(QColor(get_theme_token('acento_primario', '#B9E640')))
            pen.setWidth(1)
            for x in range(w):
                val = math.sin(x * 0.05 + self.loading_phase) * 0.3
                pulse = math.sin(self.loading_phase * 0.5) * 0.1 + 0.9
                amp = val * pulse * (h / 2.0) * 0.7
                col = QColor(get_theme_token('acento_primario', '#B9E640'))
                alpha = int(100 + 50 * math.sin(self.loading_phase + x * 0.02))
                col.setAlpha(max(30, min(alpha, 200)))
                pen.setColor(col)
                painter.setPen(pen)
                painter.drawLine(x, int(mid_y - amp), x, int(mid_y + amp))
        elif self._display_peaks:
            # Dibujar forma de onda profesional: línea vertical por píxel (solo las visibles en pantalla)
            acento = QColor(get_theme_token('acento_primario', '#B9E640'))
            dim_color = QColor(acento)
            dim_color.setAlpha(50)

            rect = event.rect()
            start_x = max(0, rect.left() - 2)
            end_x = min(len(self._display_peaks), rect.right() + 2)

            for x in range(start_x, end_x):
                mn, mx = self._display_peaks[x]

                # Aplicar zoom vertical
                mn_z = max(-1.0, mn * self.zoom_y)
                mx_z = min(1.0, mx * self.zoom_y)

                y_top = int(mid_y - mx_z * (h / 2.0 - 2))
                y_bot = int(mid_y - mn_z * (h / 2.0 - 2))

                # Asegurar al menos 1px de altura
                if y_top == y_bot:
                    y_top -= 1

                if x_in <= x <= x_out:
                    painter.setPen(QPen(acento, 1))
                else:
                    painter.setPen(QPen(dim_color, 1))

                painter.drawLine(x, y_top, x, y_bot)

        # Barra superior y Agarrador Central de Selección (Range Drag Handle)
        if x_out - x_in > 4:
            painter.fillRect(x_in, 0, x_out - x_in, 3, QColor(185, 230, 64, 200))
            center_x = (x_in + x_out) // 2
            pill_w = min(36, max(16, (x_out - x_in) - 8))
            pill_x = center_x - (pill_w // 2)

            if pill_w >= 14:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor('#B9E640'))
                painter.drawRoundedRect(pill_x, 0, pill_w, 10, 3, 3)

                # Muescas de agarre (|||) en el centro
                painter.setPen(QPen(QColor('#141414'), 1))
                painter.drawLine(center_x - 3, 3, center_x - 3, 7)
                painter.drawLine(center_x, 3, center_x, 7)
                painter.drawLine(center_x + 3, 3, center_x + 3, 7)

        # Línea de In (Verde con agarrador)
        pen_in = QPen(QColor('#1DC038'), 2, Qt.SolidLine)
        painter.setPen(pen_in)
        painter.drawLine(x_in, 0, x_in, h)
        painter.setBrush(QColor('#1DC038'))
        painter.drawRect(x_in - 3, 0, 6, 8)

        # Línea de Out (Rojo con agarrador)
        pen_out = QPen(QColor('#FF5555'), 2, Qt.SolidLine)
        painter.setPen(pen_out)
        painter.drawLine(x_out, 0, x_out, h)
        painter.setBrush(QColor('#FF5555'))
        painter.drawRect(x_out - 3, h - 8, 6, 8)

        # Playhead (Blanco)
        playhead_x = int(self._playback_ratio * w)
        pen_ph = QPen(QColor('#FFFFFF'), 2, Qt.SolidLine)
        painter.setPen(pen_ph)
        painter.drawLine(playhead_x, 0, playhead_x, h)

        painter.end()


class _CheckerboardFrame(QFrame):
    """Contenedor del área de video que pinta una cuadrícula tipo 'transparencia' (estilo
    Photoshop) de fondo cuando se reproduce un video, o un fondo oscuro sólido si no hay medio o es solo audio."""

    SQUARE = 10

    def __init__(self, border_color: str, radius: int = 6, parent=None):
        super().__init__(parent)
        self._border_color = QColor(border_color)
        self._radius = radius
        self._show_checkerboard = False

    def set_checkerboard_visible(self, visible: bool):
        if self._show_checkerboard != visible:
            self._show_checkerboard = visible
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)
        painter.setClipPath(path)

        if self._show_checkerboard:
            c1_hex = get_theme_token('ajedrez_c1', '#2a2a2a')
            c2_hex = get_theme_token('ajedrez_c2', '#181818')
            color_a = QColor(c1_hex)
            color_b = QColor(c2_hex)
            size = self.SQUARE
            cols = int(rect.width() // size) + 2
            rows = int(rect.height() // size) + 2
            for row in range(rows):
                for col in range(cols):
                    color = color_a if (row + col) % 2 == 0 else color_b
                    painter.fillRect(col * size, row * size, size, size, color)
        else:
            bg_dark = get_theme_token('fondo_principal', '#0a0a0a')
            painter.fillRect(rect, QColor(bg_dark))

        painter.setClipping(False)
        painter.setRenderHint(QPainter.Antialiasing, True)
        borde_color = get_theme_token('borde_normal', '#222222')
        painter.setPen(QPen(QColor(borde_color), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
        painter.end()


class _TransparentVideoView(QGraphicsView):
    """QGraphicsView de fondo transparente que aloja un QGraphicsVideoItem, ajustado y
    centrado manteniendo su proporción de aspecto (letterbox/pillarbox) al redimensionar.

    Soporta:
    - Zoom interactivo con la rueda del ratón (centrado bajo el cursor).
    - Paneo / arrastre manteniendo presionado el clic cuando hay zoom (> 1.0x).
    - Doble clic para restablecer el zoom a 1.0x (Fit to Window).
    """

    video_rect_changed = Signal(QRectF)  # rect (pos+size) del video_item en coords de escena

    def __init__(self, scene: QGraphicsScene, video_item: QGraphicsVideoItem, parent=None):
        super().__init__(scene, parent)
        self._video_item = video_item
        self._zoom_level = 1.0
        self._min_zoom = 1.0
        self._max_zoom = 10.0
        self._is_panning = False
        self._pan_start = None
        self._crop_edit_mode = False

        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet("QGraphicsView { background: transparent; border: none; }")
        self.viewport().setAutoFillBackground(False)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.refit()

    def refit(self):
        """Centra y escala el ítem de video dentro del viewport."""
        vp_w = self.viewport().width()
        vp_h = self.viewport().height()
        if vp_w <= 0 or vp_h <= 0:
            return

        self.scene().setSceneRect(0, 0, vp_w, vp_h)

        native = self._video_item.nativeSize()
        if native.isEmpty() or native.width() <= 0 or native.height() <= 0:
            self._video_item.setSize(QSizeF(vp_w, vp_h))
            self._video_item.setPos(0, 0)
        else:
            scale = min(vp_w / native.width(), vp_h / native.height())
            scaled_w = native.width() * scale
            scaled_h = native.height() * scale
            self._video_item.setSize(QSizeF(scaled_w, scaled_h))
            self._video_item.setPos((vp_w - scaled_w) / 2.0, (vp_h - scaled_h) / 2.0)

        pos = self._video_item.pos()
        size = self._video_item.size()
        self.video_rect_changed.emit(QRectF(pos.x(), pos.y(), size.width(), size.height()))

    def set_crop_edit_mode(self, enabled: bool):
        """Mientras el modo de recorte interactivo está activo, un clic con zoom > 1.0 no
        debe iniciar el paneo de la vista — el rectángulo de recorte necesita recibir esos
        eventos de mouse (ver _CropOverlayItem)."""
        self._crop_edit_mode = enabled

    def reset_zoom(self):
        """Restablece el zoom y centra el video (1.0x Fit)."""
        self._zoom_level = 1.0
        self._is_panning = False
        self._pan_start = None
        self.resetTransform()
        self.refit()
        self.setCursor(Qt.ArrowCursor)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0:
            return

        factor = 1.18 if delta > 0 else 1.0 / 1.18
        new_zoom = max(self._min_zoom, min(self._zoom_level * factor, self._max_zoom))

        # Si está muy cerca de 1.0x, encajar a 1.0x exacto
        if abs(new_zoom - 1.0) < 0.05 and delta < 0:
            new_zoom = 1.0

        if new_zoom != self._zoom_level:
            scale_step = new_zoom / self._zoom_level
            self._zoom_level = new_zoom

            if self._zoom_level <= 1.0:
                self.reset_zoom()
            else:
                self.scale(scale_step, scale_step)
                self.setCursor(Qt.OpenHandCursor)

        event.accept()

    def mousePressEvent(self, event):
        if not self._crop_edit_mode and event.button() in (Qt.LeftButton, Qt.MiddleButton):
            if self._zoom_level > 1.0:
                self._is_panning = True
                self._pan_start = event.position().toPoint()
                self.setCursor(Qt.ClosedHandCursor)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._is_panning and self._pan_start is not None:
            delta = event.position().toPoint() - self._pan_start
            self._pan_start = event.position().toPoint()

            h_bar = self.horizontalScrollBar()
            v_bar = self.verticalScrollBar()
            h_bar.setValue(h_bar.value() - delta.x())
            v_bar.setValue(v_bar.value() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() in (Qt.LeftButton, Qt.MiddleButton):
            if self._is_panning:
                self._is_panning = False
                self._pan_start = None
                self.setCursor(Qt.OpenHandCursor if self._zoom_level > 1.0 else Qt.ArrowCursor)
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.reset_zoom()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._zoom_level <= 1.0:
            self.refit()


class _CropOverlayItem(QGraphicsObject):
    """Rectángulo de recorte interactivo — cada lado (y cada esquina) se arrastra libre e
    independientemente, sin aspecto bloqueado: el tamaño resultante se refleja en vivo en
    los campos Ancho/Alto del panel (ver AdvancedRecodePanel.sync_dimensions_from_crop).
    Dibujado como ítem hermano de video_item en video_scene — así hereda gratis el
    zoom/paneo de _TransparentVideoView sin ningún código extra.

    El ítem no usa pos()/transform propios (queda siempre en el origen de la escena), así
    que todas las coordenadas de _video_rect/_crop_rect usadas aquí son directamente
    coordenadas de escena, sin necesidad de mapToScene/mapFromScene.
    """

    changed = Signal()  # se emite al final de cada arrastre/resize que modificó el recorte

    _HANDLE_SIZE = 12.0
    _MIN_SIZE_RATIO = 0.15  # tamaño mínimo del recorte, como fracción del lado de video_rect
    _CURSORS = {
        "nw": Qt.SizeFDiagCursor, "se": Qt.SizeFDiagCursor,
        "ne": Qt.SizeBDiagCursor, "sw": Qt.SizeBDiagCursor,
        "n": Qt.SizeVerCursor, "s": Qt.SizeVerCursor,
        "e": Qt.SizeHorCursor, "w": Qt.SizeHorCursor,
        "move": Qt.SizeAllCursor,
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._video_rect = QRectF()
        self._crop_rect = QRectF()
        self._min_w = 20.0
        self._min_h = 20.0
        self._drag_mode = None
        self._drag_start_mouse = QPointF()
        self._drag_start_rect = QRectF()
        self._touched = False
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.LeftButton)
        self.setZValue(10)

    def boundingRect(self):
        return self._video_rect

    def is_touched(self) -> bool:
        return self._touched

    def hide_and_reset(self):
        self.setVisible(False)
        self._touched = False

    def set_video_rect(self, rect: QRectF):
        """Llamado en cada refit() de la vista. Reescala el recorte actual manteniendo sus
        fracciones respecto al cuadro de video en vez de resetearlo (para que sobreviva a
        cambios de tamaño de ventana/zoom mientras se está editando)."""
        self.prepareGeometryChange()
        old_rect = self._video_rect
        self._video_rect = QRectF(rect)
        if old_rect.width() > 0 and old_rect.height() > 0 and not self._crop_rect.isEmpty():
            fx = (self._crop_rect.x() - old_rect.x()) / old_rect.width()
            fy = (self._crop_rect.y() - old_rect.y()) / old_rect.height()
            fw = self._crop_rect.width() / old_rect.width()
            fh = self._crop_rect.height() / old_rect.height()
            self._apply_fraction(fx, fy, fw, fh)
        self._update_min_size()
        self.update()

    def _update_min_size(self):
        if self._video_rect.isEmpty():
            return
        self._min_w = max(20.0, self._video_rect.width() * self._MIN_SIZE_RATIO)
        self._min_h = max(20.0, self._video_rect.height() * self._MIN_SIZE_RATIO)

    def activate(self, fw: float, fh: float):
        """Activa el overlay centrado con el tamaño fraccional (fw, fh) dado — se usa al
        entrar en modo recorte interactivo (siempre que la resolución sea personalizada y
        el ajuste sea "Recortar")."""
        self._touched = False
        vr = self._video_rect
        if vr.isEmpty():
            return
        fw = min(max(fw, 0.02), 1.0)
        fh = min(max(fh, 0.02), 1.0)
        w, h = fw * vr.width(), fh * vr.height()
        x = vr.x() + (vr.width() - w) / 2.0
        y = vr.y() + (vr.height() - h) / 2.0
        self.prepareGeometryChange()
        self._crop_rect = QRectF(x, y, w, h)
        self._update_min_size()
        self.update()

    def resize_keep_center(self, fw: float, fh: float):
        """Redimensiona el recorte activo a un tamaño fraccional específico mantenido su
        centro actual — se usa cuando el usuario tipea Ancho/Alto a mano mientras el modo
        interactivo ya está activo (dirección opuesta a get_crop_fraction)."""
        vr = self._video_rect
        if vr.isEmpty() or self._crop_rect.isEmpty():
            return
        fw = min(max(fw, 0.02), 1.0)
        fh = min(max(fh, 0.02), 1.0)
        w, h = fw * vr.width(), fh * vr.height()
        cx, cy = self._crop_rect.center().x(), self._crop_rect.center().y()
        x = min(max(cx - w / 2.0, vr.left()), vr.right() - w)
        y = min(max(cy - h / 2.0, vr.top()), vr.bottom() - h)
        self.prepareGeometryChange()
        self._crop_rect = QRectF(x, y, w, h)
        self._update_min_size()
        self.update()

    def _apply_fraction(self, fx, fy, fw, fh):
        vr = self._video_rect
        self._crop_rect = QRectF(vr.x() + fx * vr.width(), vr.y() + fy * vr.height(),
                                  fw * vr.width(), fh * vr.height())

    def get_crop_rect_scene(self) -> QRectF:
        """Rect actual del recorte en coordenadas de escena — usado por
        MediaTrimPlayerWidget para saber cuál es el "cuadro de salida efectivo" donde
        pueden moverse las marcas de agua (ver _effective_output_rect)."""
        return QRectF(self._crop_rect)

    def get_crop_fraction(self):
        vr = self._video_rect
        if vr.isEmpty() or vr.width() <= 0 or vr.height() <= 0 or self._crop_rect.isEmpty():
            return None
        fx = (self._crop_rect.x() - vr.x()) / vr.width()
        fy = (self._crop_rect.y() - vr.y()) / vr.height()
        fw = self._crop_rect.width() / vr.width()
        fh = self._crop_rect.height() / vr.height()
        return (fx, fy, fw, fh)

    # ------------------------------------------------------------------
    # Dibujo
    # ------------------------------------------------------------------
    def paint(self, painter, option, widget=None):
        if self._video_rect.isEmpty() or self._crop_rect.isEmpty():
            return
        painter.setRenderHint(QPainter.Antialiasing, True)

        vr, cr = self._video_rect, self._crop_rect
        mask_color = QColor(0, 0, 0, 140)
        painter.fillRect(QRectF(vr.left(), vr.top(), vr.width(), cr.top() - vr.top()), mask_color)
        painter.fillRect(QRectF(vr.left(), cr.bottom(), vr.width(), vr.bottom() - cr.bottom()), mask_color)
        painter.fillRect(QRectF(vr.left(), cr.top(), cr.left() - vr.left(), cr.height()), mask_color)
        painter.fillRect(QRectF(cr.right(), cr.top(), vr.right() - cr.right(), cr.height()), mask_color)

        scale = self._current_scale()
        painter.setPen(QPen(QColor("#1DC038"), 2.0 / scale))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(cr)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#B9E640"))
        handle_size = self._HANDLE_SIZE / scale
        half = handle_size / 2.0
        for hx, hy in self._handle_centers():
            painter.drawRect(QRectF(hx - half, hy - half, handle_size, handle_size))

    def _handle_centers(self):
        cr = self._crop_rect
        return [
            (cr.left(), cr.top()), (cr.right(), cr.top()),
            (cr.left(), cr.bottom()), (cr.right(), cr.bottom()),
        ]

    def _current_scale(self) -> float:
        """Factor de zoom actual de la vista que contiene esta escena. El ítem vive en
        coordenadas de escena, así que sin esto las manijas (dibujadas con un tamaño fijo
        en esas coordenadas) crecen junto con el zoom y terminan tapando la imagen — se usa
        para achicar su tamaño en escena proporcionalmente, y que el tamaño EN PANTALLA se
        mantenga constante sin importar el zoom."""
        scene = self.scene()
        if scene:
            views = scene.views()
            if views:
                scale = views[0].transform().m11()
                if scale > 0:
                    return scale
        return 1.0

    def _zone_at(self, pos: QPointF) -> str | None:
        """Determina qué parte del recorte hay bajo el cursor: una esquina (resize
        diagonal libre), un lado (resize de un solo eje), el cuerpo (mover), o nada."""
        cr = self._crop_rect
        if cr.isEmpty():
            return None
        m = self._HANDLE_SIZE / self._current_scale()
        near_left = abs(pos.x() - cr.left()) <= m
        near_right = abs(pos.x() - cr.right()) <= m
        near_top = abs(pos.y() - cr.top()) <= m
        near_bottom = abs(pos.y() - cr.bottom()) <= m
        within_x = cr.left() - m <= pos.x() <= cr.right() + m
        within_y = cr.top() - m <= pos.y() <= cr.bottom() + m

        if near_top and near_left and within_x and within_y:
            return "nw"
        if near_top and near_right and within_x and within_y:
            return "ne"
        if near_bottom and near_left and within_x and within_y:
            return "sw"
        if near_bottom and near_right and within_x and within_y:
            return "se"
        if near_top and within_x:
            return "n"
        if near_bottom and within_x:
            return "s"
        if near_left and within_y:
            return "w"
        if near_right and within_y:
            return "e"
        if cr.contains(pos):
            return "move"
        return None

    # ------------------------------------------------------------------
    # Interacción de mouse
    # ------------------------------------------------------------------
    def hoverMoveEvent(self, event):
        zone = self._zone_at(event.pos())
        cursor = self._CURSORS.get(zone) if zone else None
        if cursor is not None:
            self.setCursor(cursor)
        else:
            self.unsetCursor()
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event):
        zone = self._zone_at(event.pos())
        if not zone:
            self._drag_mode = None
            event.ignore()
            return
        self._drag_mode = zone
        self._drag_start_mouse = event.pos()
        self._drag_start_rect = QRectF(self._crop_rect)
        event.accept()

    def mouseMoveEvent(self, event):
        if not self._drag_mode:
            event.ignore()
            return
        delta = event.pos() - self._drag_start_mouse
        if self._drag_mode == "move":
            new_rect = self._clamp_move(self._drag_start_rect.translated(delta))
        else:
            new_rect = self._resize_rect(self._drag_mode, delta)
        if new_rect != self._crop_rect:
            self.prepareGeometryChange()
            self._crop_rect = new_rect
            if delta.x() or delta.y():
                self._touched = True
            self.update()
            self.changed.emit()
        event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_mode = None
        event.accept()

    def _clamp_move(self, rect: QRectF) -> QRectF:
        vr = self._video_rect
        dx = dy = 0.0
        if rect.left() < vr.left():
            dx = vr.left() - rect.left()
        elif rect.right() > vr.right():
            dx = vr.right() - rect.right()
        if rect.top() < vr.top():
            dy = vr.top() - rect.top()
        elif rect.bottom() > vr.bottom():
            dy = vr.bottom() - rect.bottom()
        return rect.translated(dx, dy)

    def _resize_rect(self, zone: str, delta: QPointF) -> QRectF:
        """Redimensiona SOLO los lados que forman parte de 'zone' (uno para un lado, dos
        para una esquina), sin ninguna relación de aspecto entre ancho y alto."""
        start = self._drag_start_rect
        vr = self._video_rect
        left, top, right, bottom = start.left(), start.top(), start.right(), start.bottom()

        if "w" in zone:
            left = min(start.right() - self._min_w, start.left() + delta.x())
        if "e" in zone:
            right = max(start.left() + self._min_w, start.right() + delta.x())
        if "n" in zone:
            top = min(start.bottom() - self._min_h, start.top() + delta.y())
        if "s" in zone:
            bottom = max(start.top() + self._min_h, start.bottom() + delta.y())

        left = max(left, vr.left())
        top = max(top, vr.top())
        right = min(right, vr.right())
        bottom = min(bottom, vr.bottom())

        # El clamp contra los bordes del video puede haber apretado por debajo del mínimo
        # (ej. arrastrando "w" hasta pegarse al borde izquierdo) — se reaplica el mínimo
        # empujando el lado que SÍ se está moviendo, nunca el lado fijo opuesto.
        if right - left < self._min_w:
            if "w" in zone:
                left = right - self._min_w
            else:
                right = left + self._min_w
        if bottom - top < self._min_h:
            if "n" in zone:
                top = bottom - self._min_h
            else:
                bottom = top + self._min_h

        return QRectF(QPointF(left, top), QPointF(right, bottom))


class _DraggableWatermarkItem(QGraphicsObject):
    """Base para las marcas de agua interactivas (texto/imagen) sobre la vista previa:
    se pueden MOVER (arrastrando el cuerpo) y REDIMENSIONAR (arrastrando la manija de
    la esquina inferior-derecha, con la esquina superior-izquierda fija como ancla —
    igual convención que arrastrar el borde de una ventana), dentro del "cuadro de
    salida efectivo" (el recorte si está activo, si no el cuadro de video completo —
    ver MediaTrimPlayerWidget._effective_output_rect). Misma convención que
    _CropOverlayItem: sin pos()/transform propios, todo en coordenadas de escena, y la
    manija se dibuja a tamaño constante en pantalla dividiendo por el zoom actual
    (_current_scale) — mismo arreglo que ya se aplicó al recorte para que no tape la
    imagen al hacer zoom.

    fx/fy son la posición de la esquina superior-izquierda como fracción del espacio de
    arrastre disponible (0 = pegado arriba/izquierda, 1 = pegado abajo/derecha) — mismo
    fx/fy que consume watermark_builder.py para armar las expresiones de ffmpeg
    (w-tw)*fx / (h-th)*fy, así que lo que se ve aquí corresponde 1 a 1 con la fórmula
    que realmente va a aplicar ffmpeg. El "tamaño" (size_pct de texto, scale_pct de
    imagen) también se puede arrastrar aquí, y se sincroniza en vivo con el slider del
    panel — ver AdvancedRecodePanel.set_text_watermark_size/set_image_watermark_size."""

    changed = Signal()  # se emite al final de cada arrastre real (mover o redimensionar)

    _HANDLE_SIZE = 12.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._output_rect = QRectF()
        self._fx = 0.9
        self._fy = 0.9
        self._drag_mode = None  # None | "move" | "resize"
        self._drag_start_mouse = QPointF()
        self._drag_start_fx = 0.9
        self._drag_start_fy = 0.9
        self._drag_start_size_value = 0.0
        self._drag_anchor = QPointF()  # esquina superior-izquierda fija durante el resize
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.LeftButton)
        self.setZValue(20)

    def _item_size(self) -> QSizeF:
        raise NotImplementedError

    def _size_value(self) -> float:
        """Tamaño ajustable por arrastre (size_pct de texto o scale_pct de imagen)."""
        raise NotImplementedError

    def _set_size_value(self, value: float):
        raise NotImplementedError

    def _resize_delta_to_value(self, delta: QPointF) -> float:
        raise NotImplementedError

    def get_size_pct(self) -> float:
        return self._size_value()

    def _current_scale(self) -> float:
        scene = self.scene()
        if scene:
            views = scene.views()
            if views:
                scale = views[0].transform().m11()
                if scale > 0:
                    return scale
        return 1.0

    def set_output_rect(self, rect: QRectF):
        self.prepareGeometryChange()
        self._output_rect = QRectF(rect)
        self.update()

    def get_position_fraction(self) -> tuple[float, float]:
        return (self._fx, self._fy)

    def _item_rect(self) -> QRectF:
        size = self._item_size()
        avail_w = max(0.0, self._output_rect.width() - size.width())
        avail_h = max(0.0, self._output_rect.height() - size.height())
        x = self._output_rect.x() + self._fx * avail_w
        y = self._output_rect.y() + self._fy * avail_h
        return QRectF(x, y, size.width(), size.height())

    def _handle_center(self) -> QPointF:
        rect = self._item_rect()
        return QPointF(rect.right(), rect.bottom())

    def boundingRect(self):
        if self._output_rect.isEmpty():
            return QRectF()
        return self._item_rect().adjusted(-4, -4, 4, 4)

    def _paint_resize_handle(self, painter):
        m = self._HANDLE_SIZE / self._current_scale()
        center = self._handle_center()
        painter.setOpacity(1.0)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#B9E640"))
        painter.drawRect(QRectF(center.x() - m / 2.0, center.y() - m / 2.0, m, m))

    def _zone_at(self, pos: QPointF) -> str | None:
        m = self._HANDLE_SIZE / self._current_scale()
        center = self._handle_center()
        if abs(pos.x() - center.x()) <= m and abs(pos.y() - center.y()) <= m:
            return "resize"
        if self._item_rect().contains(pos):
            return "move"
        return None

    def hoverMoveEvent(self, event):
        zone = self._zone_at(event.pos())
        if zone == "resize":
            self.setCursor(Qt.SizeFDiagCursor)
        elif zone == "move":
            self.setCursor(Qt.SizeAllCursor)
        else:
            self.unsetCursor()
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event):
        zone = self._zone_at(event.pos())
        if not zone:
            self._drag_mode = None
            event.ignore()
            return
        self._drag_mode = zone
        self._drag_start_mouse = event.pos()
        self._drag_start_fx, self._drag_start_fy = self._fx, self._fy
        self._drag_start_size_value = self._size_value()
        self._drag_anchor = self._item_rect().topLeft()
        event.accept()

    def mouseMoveEvent(self, event):
        if not self._drag_mode:
            event.ignore()
            return
        delta = event.pos() - self._drag_start_mouse
        changed = False
        if self._drag_mode == "move":
            size = self._item_size()
            avail_w = max(1e-6, self._output_rect.width() - size.width())
            avail_h = max(1e-6, self._output_rect.height() - size.height())
            new_fx = min(max(self._drag_start_fx + delta.x() / avail_w, 0.0), 1.0)
            new_fy = min(max(self._drag_start_fy + delta.y() / avail_h, 0.0), 1.0)
            if new_fx != self._fx or new_fy != self._fy:
                self.prepareGeometryChange()
                self._fx, self._fy = new_fx, new_fy
                changed = True
        else:  # resize: la esquina superior-izquierda (_drag_anchor) queda fija en
               # coordenadas de escena; la de abajo-a-la-derecha sigue al cursor.
            new_value = self._resize_delta_to_value(delta)
            if new_value != self._size_value():
                self.prepareGeometryChange()
                self._set_size_value(new_value)
                new_size = self._item_size()
                avail_w = max(1e-6, self._output_rect.width() - new_size.width())
                avail_h = max(1e-6, self._output_rect.height() - new_size.height())
                self._fx = min(max((self._drag_anchor.x() - self._output_rect.x()) / avail_w, 0.0), 1.0)
                self._fy = min(max((self._drag_anchor.y() - self._output_rect.y()) / avail_h, 0.0), 1.0)
                changed = True
        if changed:
            self.update()
            if delta.x() or delta.y():
                self.changed.emit()
        event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_mode = None
        event.accept()


class _TextWatermarkOverlayItem(_DraggableWatermarkItem):
    """Aproxima visualmente el resultado de drawtext: dibuja el texto real con la
    fuente/tamaño elegidos, para que arrastrar en la vista previa sea WYSIWYG."""

    _MIN_SIZE_PCT = 1.0
    _MAX_SIZE_PCT = 60.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""
        self._font_family = "Arial"
        self._weight = 400
        self._size_pct = 5.0  # % de la altura del cuadro de salida
        self._color = QColor("#FFFFFF")
        self._opacity = 1.0

    def set_style(self, text: str, font_family: str, weight: int, size_pct: float, color: QColor, opacity: float):
        self.prepareGeometryChange()
        self._text = text or ""
        self._font_family = font_family or self._font_family
        self._weight = weight or 400
        self._size_pct = max(self._MIN_SIZE_PCT, size_pct)
        self._color = QColor(color) if color else self._color
        self._opacity = opacity
        self.update()

    def _size_value(self) -> float:
        return self._size_pct

    def _set_size_value(self, value: float):
        self._size_pct = min(max(value, self._MIN_SIZE_PCT), self._MAX_SIZE_PCT)

    def _resize_delta_to_value(self, delta: QPointF) -> float:
        if self._output_rect.isEmpty() or self._output_rect.height() <= 0:
            return self._drag_start_size_value
        start_px = self._output_rect.height() * (self._drag_start_size_value / 100.0)
        new_px = max(6.0, start_px + delta.y())
        return (new_px / self._output_rect.height()) * 100.0

    def _font(self) -> QFont:
        size_px = 12
        if not self._output_rect.isEmpty():
            size_px = max(6, int(self._output_rect.height() * (self._size_pct / 100.0)))
        font = QFont(self._font_family)
        font.setPixelSize(size_px)
        font.setWeight(QFont.Weight(self._weight))
        return font

    def _item_size(self) -> QSizeF:
        if not self._text:
            return QSizeF(1.0, 1.0)
        rect = QFontMetricsF(self._font()).boundingRect(self._text)
        return QSizeF(max(1.0, rect.width()), max(1.0, rect.height()))

    def paint(self, painter, option, widget=None):
        if self._output_rect.isEmpty() or not self._text:
            return
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setFont(self._font())
        color = QColor(self._color)
        color.setAlphaF(max(0.0, min(1.0, self._opacity)))
        painter.setPen(color)
        painter.drawText(self._item_rect(), Qt.AlignLeft | Qt.AlignTop, self._text)
        self._paint_resize_handle(painter)


class _ImageWatermarkOverlayItem(_DraggableWatermarkItem):
    """Dibuja la imagen elegida escalada al % configurado, para arrastre WYSIWYG."""

    _MIN_SCALE_PCT = 1.0
    _MAX_SCALE_PCT = 100.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = QPixmap()
        self._scale_pct = 15.0  # % del ancho del cuadro de salida
        self._opacity = 1.0

    def set_style(self, image_path: str, scale_pct: float, opacity: float):
        self.prepareGeometryChange()
        self._pixmap = QPixmap(image_path) if image_path else QPixmap()
        self._scale_pct = max(self._MIN_SCALE_PCT, scale_pct)
        self._opacity = opacity
        self.update()

    def _size_value(self) -> float:
        return self._scale_pct

    def _set_size_value(self, value: float):
        self._scale_pct = min(max(value, self._MIN_SCALE_PCT), self._MAX_SCALE_PCT)

    def _resize_delta_to_value(self, delta: QPointF) -> float:
        if self._output_rect.isEmpty() or self._output_rect.width() <= 0:
            return self._drag_start_size_value
        start_px = self._output_rect.width() * (self._drag_start_size_value / 100.0)
        new_px = max(8.0, start_px + delta.x())
        return (new_px / self._output_rect.width()) * 100.0

    def _item_size(self) -> QSizeF:
        if self._pixmap.isNull() or self._output_rect.isEmpty() or self._pixmap.width() <= 0:
            return QSizeF(1.0, 1.0)
        target_w = max(1.0, self._output_rect.width() * (self._scale_pct / 100.0))
        aspect = self._pixmap.height() / self._pixmap.width()
        return QSizeF(target_w, target_w * aspect)

    def paint(self, painter, option, widget=None):
        if self._output_rect.isEmpty() or self._pixmap.isNull():
            return
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setOpacity(max(0.0, min(1.0, self._opacity)))
        painter.drawPixmap(self._item_rect(), self._pixmap, QRectF(self._pixmap.rect()))
        self._paint_resize_handle(painter)


class MediaTrimPlayerWidget(QWidget):
    """
    Reproductor de video/audio con extractor de waveform de alta resolución y selección de
    rango In/Out (recorte). Extraído de la columna izquierda del editor de Subclips
    (gui/dialogs/subclip_dialog.py) para poder reutilizarse en otros lugares (p.ej. la pestaña
    de Herramientas Multimedia) sin arrastrar la columna de subclips guardados / envío a editor.

    Expone `self.ctrl_bar` (QHBoxLayout) para que quien lo use pueda insertar controles propios
    adicionales (p.ej. un botón "Añadir subclip") en la barra de controles inferior.
    """

    range_changed = Signal(float, float)  # in_sec, out_sec
    playing_changed = Signal(bool)
    audio_track_selection_changed = Signal()  # ver get_audio_track_selection()
    crop_rect_changed = Signal()
    text_watermark_changed = Signal()
    image_watermark_changed = Signal()

    def __init__(self, parent=None, card_style: bool = False):
        super().__init__(parent)
        self.media_path = ""
        self.media_type = "video"
        self.duration_sec = 1.0
        self.fps = 30.0
        self.in_sec = 0.0
        self.out_sec = 1.0
        self.pending_download = False
        # Rango (in_sec, out_sec) que se está previsualizando en bucle; None si no hay ninguno activo.
        self._preview_loop_range = None
        self._hires_signal_connected = False
        self._first_frame_rendered = False
        self._card_style = card_style
        self._active_audio_track = 0
        self._pending_audio_track_selection = None
        self._pending_waveform_track = 0

        # Calidad de previsualización (proxies para scrubbing fluido de medios pesados/RAW).
        self._proxy_mode = "auto"    # "auto" | "manual"
        self._proxy_divisor = 1      # divisor que se está reproduciendo ahora mismo (1 = original)
        self._pending_proxy_divisor = None  # divisor en curso de generación, si hay uno
        self._manual_divisor = 1     # último divisor elegido manualmente (persiste entre archivos)
        self._native_size_known = False
        self._native_size = None
        self._proxy_signal_connected = False
        self._pending_source_restore = None  # (pos_ms, was_playing) pendiente de aplicar tras un swap de fuente

        self.setFocusPolicy(Qt.StrongFocus)

        self._init_ui()
        self._init_media_player()

    # ------------------------------------------------------------------
    # Construcción de la interfaz
    # ------------------------------------------------------------------
    def _init_ui(self):
        left_layout = QVBoxLayout(self)
        # Guardado como atributo para permitir extraer secciones del layout más tarde
        # (ver extract_timeline_container) sin afectar el uso normal de este widget.
        self._root_layout = left_layout
        if self._card_style:
            # Tarjeta con el mismo fondo/borde/radio que el resto de paneles de la app
            # (p.ej. la cola de medios o el panel de opciones en Herramientas Multimedia).
            self.setObjectName("mediaTrimPlayerWidget")
            self.setAttribute(Qt.WA_StyledBackground, True)
            bg_color = get_theme_token('fondo_secundario', '#1e1e1e')
            border_color = get_theme_token('borde_normal', '#2d2d2d')
            self.setStyleSheet(f"""
                QWidget#mediaTrimPlayerWidget {{
                    background-color: {bg_color};
                    border: 1px solid {border_color};
                    border-radius: 6px;
                }}
            """)
            left_layout.setContentsMargins(8, 8, 8, 8)
        else:
            left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        # Área de Video / Vista Previa
        borde_norm = get_theme_token('borde_normal', '#2d2d2d')
        self.preview_container = _CheckerboardFrame(borde_norm, radius=6)
        prev_layout = QVBoxLayout(self.preview_container)
        prev_layout.setContentsMargins(0, 0, 0, 0)

        # QGraphicsView + QGraphicsVideoItem en vez de QVideoWidget: así las franjas de
        # letterbox/pillarbox quedan transparentes y dejan ver la cuadrícula de fondo.
        self.video_scene = QGraphicsScene(self)
        self.video_scene.setBackgroundBrush(Qt.NoBrush)
        self.video_item = QGraphicsVideoItem()
        self.video_scene.addItem(self.video_item)
        self.video_item.nativeSizeChanged.connect(self._on_video_native_size_changed)

        self.video_widget = _TransparentVideoView(self.video_scene, self.video_item)
        self.video_widget.setVisible(False)
        prev_layout.addWidget(self.video_widget)

        # Rectángulo de recorte interactivo: ítem hermano de video_item en la misma escena,
        # oculto hasta que se active el modo de edición visual desde AdvancedRecodePanel.
        self._current_video_rect = QRectF()
        self.crop_overlay = _CropOverlayItem()
        self.crop_overlay.setVisible(False)
        self.video_scene.addItem(self.crop_overlay)
        self.video_widget.video_rect_changed.connect(self._on_video_rect_changed)
        self.crop_overlay.changed.connect(self._on_crop_overlay_changed)

        # Marcas de agua interactivas (texto/imagen): mismo patrón que el recorte, pero
        # solo se mueven (el tamaño lo controla un slider del panel) y se ubican dentro
        # del "cuadro de salida efectivo" (el recorte si está activo, si no el video
        # completo — ver _effective_output_rect). A diferencia del recorte, NO se
        # resetean al cambiar de archivo: la posición es una regla del lote entero.
        self.text_watermark_overlay = _TextWatermarkOverlayItem()
        self.text_watermark_overlay.setVisible(False)
        self.video_scene.addItem(self.text_watermark_overlay)
        self.text_watermark_overlay.changed.connect(self.text_watermark_changed.emit)

        self.image_watermark_overlay = _ImageWatermarkOverlayItem()
        self.image_watermark_overlay.setVisible(False)
        self.video_scene.addItem(self.image_watermark_overlay)
        self.image_watermark_overlay.changed.connect(self.image_watermark_changed.emit)

        self.lbl_audio_art = QLabel(self.tr("Vista Previa de Audio"))
        self.lbl_audio_art.setAlignment(Qt.AlignCenter)
        self.lbl_audio_art.setStyleSheet("color: #89b4fa; font-weight: bold; font-size: 16px; background: transparent;")
        self.lbl_audio_art.setVisible(False)
        prev_layout.addWidget(self.lbl_audio_art, 1)

        # Widget para estado vacío cuando no hay medio cargado
        self.empty_preview_widget = QWidget(self.preview_container)
        self.empty_preview_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        empty_outer = QVBoxLayout(self.empty_preview_widget)
        empty_outer.setContentsMargins(0, 0, 0, 0)
        empty_outer.setSpacing(0)
        empty_outer.addStretch(1)

        empty_inner = QWidget()
        empty_layout = QVBoxLayout(empty_inner)
        empty_layout.setAlignment(Qt.AlignCenter)
        empty_layout.setContentsMargins(10, 0, 10, 0)
        empty_layout.setSpacing(6)

        lbl_empty_icon = QLabel()
        lbl_empty_icon.setAlignment(Qt.AlignCenter)
        icon_color = get_theme_token('texto_deshabilitado', '#555555')
        empty_ico = get_colored_svg_icon("play_arrow.svg", icon_color, size=36)
        if not empty_ico.isNull():
            lbl_empty_icon.setPixmap(empty_ico.pixmap(36, 36))
        empty_layout.addWidget(lbl_empty_icon)

        self.lbl_empty_title = QLabel(self.tr("Vista Previa y Recorte"))
        self.lbl_empty_title.setAlignment(Qt.AlignCenter)
        self.lbl_empty_title.setStyleSheet(f"font-weight: bold; font-size: 13px; color: {get_theme_token('texto_secundario', '#777777')}; background: transparent;")
        empty_layout.addWidget(self.lbl_empty_title)

        self.lbl_empty_subtitle = QLabel(self.tr("Carga o selecciona un medio para previsualizarlo y ajustar sus puntos In / Out"))
        self.lbl_empty_subtitle.setAlignment(Qt.AlignCenter)
        # Sin wrap, Qt exige el ancho de la oración completa como mínimo (~400px) solo para
        # este texto de ayuda — con wrap, se acomoda en más líneas en layouts angostos.
        self.lbl_empty_subtitle.setWordWrap(True)
        self.lbl_empty_subtitle.setStyleSheet(f"font-size: 11px; color: {get_theme_token('texto_deshabilitado', '#555555')}; background: transparent;")
        empty_layout.addWidget(self.lbl_empty_subtitle)

        empty_outer.addWidget(empty_inner, 0, Qt.AlignCenter)
        empty_outer.addStretch(1)

        prev_layout.addWidget(self.empty_preview_widget, 1)

        # Reloj global: franja delgada al pie de la vista previa (antes vivía en ctrl_bar,
        # abajo del todo, separado del video — se movió aquí adentro porque ya hay espacio
        # y queda junto a lo que representa).
        self.lbl_time_info = QLabel("00:00:00.000 / 00:00:00.000")
        self.lbl_time_info.setAlignment(Qt.AlignCenter)
        self.lbl_time_info.setFixedHeight(20)
        self.lbl_time_info.setStyleSheet("""
            QLabel {
                background-color: #000000;
                color: #cdd6f4;
                font-size: 11px;
                font-weight: bold;
            }
        """)
        prev_layout.addWidget(self.lbl_time_info)

        # Botón flotante para selección de resolución de previsualización (esquina superior derecha del visor)
        self.btn_quality = QToolButton(self.preview_container)
        self.btn_quality.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.btn_quality.setPopupMode(QToolButton.InstantPopup)
        self.btn_quality.setCursor(Qt.PointingHandCursor)
        self.btn_quality.setToolTip(self.tr("Resolución de previsualización (no afecta la exportación final)"))
        self.btn_quality.setFixedHeight(20)
        self.btn_quality.setStyleSheet("""
            QToolButton {
                background-color: rgba(20, 20, 20, 200);
                border: 1px solid #444;
                border-radius: 6px;
                color: #cdd6f4;
                font-size: 10px;
                font-weight: bold;
                padding: 2px 6px;
            }
            QToolButton:hover { background-color: rgba(185, 230, 64, 200); color: #141414; border-color: #B9E640; }
            QToolButton::menu-indicator { image: none; }
        """)
        self.quality_menu = QMenu(self.btn_quality)
        self.btn_quality.setMenu(self.quality_menu)
        self.btn_quality.setVisible(False)
        self._init_quality_menu()

        left_layout.addWidget(self.preview_container, 1)

        # Contenedor horizontal: Columna de herramientas/waveform a la izquierda y Vúmetro completo a la derecha
        wave_container = QHBoxLayout()
        wave_container.setContentsMargins(0, 0, 0, 0)
        wave_container.setSpacing(8)
        self._wave_layout = wave_container

        # Columna izquierda: Controles Zoom arriba + Timeline Ruler al medio + Waveform abajo
        timeline_waveform_col = QVBoxLayout()
        timeline_waveform_col.setContentsMargins(0, 0, 0, 0)
        timeline_waveform_col.setSpacing(4)

        # 1. Controles de Zoom
        zoom_bar = QHBoxLayout()
        zoom_bar.setContentsMargins(0, 0, 0, 0)

        lbl_zoom_icon = QLabel()
        icon_zoom = get_svg_icon("zoom_in.svg")
        if not icon_zoom.isNull():
            lbl_zoom_icon.setPixmap(icon_zoom.pixmap(16, 16))
        else:
            lbl_zoom_icon.setText("🔍")
        zoom_bar.addWidget(lbl_zoom_icon)

        self.slider_zoom_x = QSlider(Qt.Horizontal)
        self.slider_zoom_x.setRange(100, 5000)
        self.slider_zoom_x.setValue(100)
        self.slider_zoom_x.setFixedWidth(70)
        self.slider_zoom_x.setCursor(Qt.PointingHandCursor)
        self.slider_zoom_x.setToolTip("Zoom Horizontal")
        self.slider_zoom_x.valueChanged.connect(self._on_zoom_x_changed)
        zoom_bar.addWidget(self.slider_zoom_x)

        zoom_bar.addSpacing(16)

        lbl_zoom_y_icon = QLabel("dB")
        lbl_zoom_y_icon.setStyleSheet("color: #888; font-size: 11px; font-weight: bold;")
        zoom_bar.addWidget(lbl_zoom_y_icon)

        self.slider_zoom_y = QSlider(Qt.Horizontal)
        self.slider_zoom_y.setRange(10, 1000)
        self.slider_zoom_y.setValue(100)
        self.slider_zoom_y.setFixedWidth(60)
        self.slider_zoom_y.setCursor(Qt.PointingHandCursor)
        self.slider_zoom_y.setToolTip("Ganancia Visual (Zoom Y)")
        self.slider_zoom_y.valueChanged.connect(self._on_zoom_y_changed)
        zoom_bar.addWidget(self.slider_zoom_y)

        zoom_bar.addStretch()

        # Controles de multipista a la derecha de la barra de zoom
        self.btn_audio_track = QToolButton()
        self.btn_audio_track.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.btn_audio_track.setPopupMode(QToolButton.InstantPopup)
        self.btn_audio_track.setCursor(Qt.PointingHandCursor)
        self.btn_audio_track.setToolTip(self.tr("Seleccionar pista de audio para previsualización"))
        self.btn_audio_track.setFixedHeight(22)
        self.btn_audio_track.setStyleSheet("""
            QToolButton {
                background-color: rgba(30, 30, 30, 220);
                border: 1px solid #444;
                border-radius: 4px;
                color: #cdd6f4;
                font-size: 11px;
                font-weight: 500;
                padding: 2px 8px;
            }
            QToolButton:hover {
                background-color: rgba(185, 230, 64, 30);
                color: #B9E640;
                border-color: #B9E640;
            }
            QToolButton::menu-indicator { image: none; }
        """)
        self.audio_track_menu = QMenu(self.btn_audio_track)
        self.btn_audio_track.setMenu(self.audio_track_menu)
        self.btn_audio_track.setVisible(False)
        zoom_bar.addWidget(self.btn_audio_track)

        zoom_bar.addSpacing(6)

        self.chk_all_tracks = QCheckBox(self.tr("Procesar todas las pistas"))
        self.chk_all_tracks.setChecked(True)
        self.chk_all_tracks.setCursor(Qt.PointingHandCursor)
        self.chk_all_tracks.setToolTip(
            self.tr("Si está marcado, se procesarán y conservarán todas las pistas de audio del archivo. "
                    "Si se desmarca, solo se procesará la pista seleccionada.")
        )
        self.chk_all_tracks.setVisible(False)
        self.chk_all_tracks.toggled.connect(lambda _checked: self.audio_track_selection_changed.emit())
        zoom_bar.addWidget(self.chk_all_tracks)

        timeline_waveform_col.addLayout(zoom_bar)

        # 2. Regla de tiempo (Timeline Ruler) — alineada únicamente sobre la waveform
        self.timeline_ruler = TimelineRulerWidget(
            media_type=self.media_type,
            duration_sec=self.duration_sec,
            fps=self.fps
        )
        timeline_waveform_col.addWidget(self.timeline_ruler)

        # 3. Waveform con scroll
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setFixedHeight(90)
        self.scroll_area.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollBar:horizontal {
                border: none; background: #222; height: 10px; margin: 0px 0px 0 0px; border-radius: 5px;
            }
            QScrollBar::handle:horizontal {
                background: #555; min-width: 20px; border-radius: 5px;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                border: none; background: none; width: 0px;
            }
        """)

        self.waveform_widget = TrimWaveformWidget()
        self.waveform_widget.seek_requested.connect(self._on_waveform_seek)
        self.waveform_widget.range_changed.connect(self._on_waveform_range_changed)
        self.scroll_area.setWidget(self.waveform_widget)

        timeline_waveform_col.addWidget(self.scroll_area)
        wave_container.addLayout(timeline_waveform_col, 1)

        self.scroll_area.viewport().installEventFilter(self)
        # Sincronizar la regla de tiempo con el scroll
        self.scroll_area.horizontalScrollBar().valueChanged.connect(self._sync_ruler)

        # Medidor de audio a la derecha abarcando toda la altura (zoom_bar + ruler + waveform ~ 140px)
        self.audio_meter = MultiChannelMeterWidget()
        self.audio_meter.setFixedHeight(140)
        wave_container.addWidget(self.audio_meter)

        left_layout.addLayout(wave_container)

        # Barra de Controles e Información de Tiempos
        self.ctrl_bar = QHBoxLayout()
        self.ctrl_bar.setContentsMargins(0, 4, 0, 0)
        self.ctrl_bar.setSpacing(6)

        # Botón Play/Pause
        self.btn_play = QPushButton()
        self.btn_play.setFixedSize(32, 32)
        self.btn_play.setIconSize(QSize(18, 18))
        self.btn_play.clicked.connect(self.toggle_play_pause)
        apply_player_play_button_style(self.btn_play, is_playing=False, icon_size=18)
        self.ctrl_bar.addWidget(self.btn_play)

        # Margen fijo (no elástico): el volumen queda siempre pegado al botón de play a
        # esta distancia constante, sin importar el ancho disponible.
        self.ctrl_bar.addSpacing(10)

        # Volume control
        self.volume_control = VolumeControlWidget(initial_volume=100, slider_width=60)
        self.volume_control.volume_changed.connect(self._on_volume_changed)
        self.ctrl_bar.addWidget(self.volume_control)

        # Margen mínimo garantizado antes del stretch: el stretch se colapsa a 0px cuando
        # no sobra espacio, y sin este margen fijo el mango del slider (que Qt suele
        # dibujar un poco más allá de su rect lógico) terminaba tapado por el botón "In".
        self.ctrl_bar.addSpacing(8)
        self.ctrl_bar.addStretch()

        # Botones In [I] y Out [O] and inputs
        self.btn_set_in = QPushButton()
        self.btn_set_in.setIcon(get_svg_icon("arrow_menu_open.svg"))
        self.btn_set_in.setIconSize(QSize(20, 20))
        self.btn_set_in.setFixedSize(32, 32)
        self.btn_set_in.setToolTip(self.tr("Establecer punto de entrada (Tecla I)"))
        self.btn_set_in.setStyleSheet("""
            QPushButton {
                background-color: #1a271a;
                border: 1px solid #1DC038;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #1DC038; }
        """)
        self.btn_set_in.clicked.connect(self.set_in_point)
        self.ctrl_bar.addWidget(self.btn_set_in)

        _time_style = f"font-size: 12px; padding: 4px 6px; border-radius: 6px; background: {get_theme_token('fondo_elemento', '#1a1a1a')}; border: 1px solid {get_theme_token('borde_normal', '#222222')}; color: {get_theme_token('texto_activo', '#ffffff')};"
        self.input_time_start = QLineEdit(self._format_seconds_ms(self.in_sec))
        self.input_time_start.setFixedSize(90, 32)
        self.input_time_start.setAlignment(Qt.AlignCenter)
        self.input_time_start.setStyleSheet(_time_style)
        self.input_time_start.editingFinished.connect(self._on_time_input_changed)
        self.ctrl_bar.addWidget(self.input_time_start)

        sep = QLabel("—")
        sep.setAlignment(Qt.AlignCenter)
        # Ancho fijo reservado: sin esto, el label dependía de su sizeHint natural (muy
        # angosto para un solo guion) y bajo presión terminaba compartiendo espacio con
        # el campo de tiempo de al lado en vez de tener su propio hueco garantizado.
        sep.setFixedWidth(20)
        sep.setStyleSheet("color: #666; font-size: 15px;")
        self.ctrl_bar.addWidget(sep)

        self.input_time_end = QLineEdit(self._format_seconds_ms(self.out_sec))
        self.input_time_end.setFixedSize(90, 32)
        self.input_time_end.setAlignment(Qt.AlignCenter)
        self.input_time_end.setStyleSheet(_time_style)
        self.input_time_end.editingFinished.connect(self._on_time_input_changed)
        self.ctrl_bar.addWidget(self.input_time_end)

        self.btn_set_out = QPushButton()
        self.btn_set_out.setIcon(get_svg_icon("arrow_menu_close.svg"))
        self.btn_set_out.setIconSize(QSize(20, 20))
        self.btn_set_out.setFixedSize(32, 32)
        self.btn_set_out.setToolTip(self.tr("Establecer punto de salida (Tecla O)"))
        self.btn_set_out.setStyleSheet("""
            QPushButton {
                background-color: #2b1a1a;
                border: 1px solid #FF5555;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #FF5555; }
        """)
        self.btn_set_out.clicked.connect(self.set_out_point)
        self.ctrl_bar.addWidget(self.btn_set_out)

        self.ctrl_bar.addStretch()

        left_layout.addLayout(self.ctrl_bar)

    def extract_timeline_container(self) -> QWidget:
        """Saca la waveform/regla/vúmetro y la barra de controles de este widget y las
        devuelve envueltas en un QWidget aparte, dejando aquí solo el preview de video.

        Pensado exclusivamente para VideoToolsTab, que necesita mostrar el timeline en una
        fila separada del preview (layout tipo Premiere). NO llamar desde subclip_dialog.py:
        ese diálogo depende de que ctrl_bar y la waveform sigan viviendo dentro de este mismo
        widget (inserta botones propios directamente en self.ctrl_bar por índice).
        """
        timeline_container = QFrame()
        if self._card_style:
            timeline_container.setObjectName("mediaTrimTimelineContainer")
            timeline_container.setAttribute(Qt.WA_StyledBackground, True)
            bg_color = get_theme_token('fondo_secundario', '#1e1e1e')
            border_color = get_theme_token('borde_normal', '#2d2d2d')
            timeline_container.setStyleSheet(f"""
                QFrame#mediaTrimTimelineContainer {{
                    background-color: {bg_color};
                    border: 1px solid {border_color};
                    border-radius: 6px;
                }}
            """)
        timeline_layout = QVBoxLayout(timeline_container)
        timeline_layout.setContentsMargins(8, 8, 8, 8)
        timeline_layout.setSpacing(self._root_layout.spacing())

        self._root_layout.removeItem(self._wave_layout)
        timeline_layout.addLayout(self._wave_layout)

        self._root_layout.removeItem(self.ctrl_bar)
        timeline_layout.addLayout(self.ctrl_bar)

        # A partir de aquí, ctrl_bar/zoom_bar viven en timeline_container (no en self), así
        # que el recálculo de controles compactos debe seguir SU ancho, no el de self.
        self._timeline_container = timeline_container
        timeline_container.installEventFilter(self)
        self._recalculate_compact_controls(timeline_container.width())

        return timeline_container

    def _recalculate_compact_controls(self, width: int):
        """Oculta el slider de volumen y los sliders de zoom/dB (dejando solo su ícono)
        cuando el ancho disponible no alcanza — mismo criterio que ya usa
        VolumeControlWidget.set_slider_visible()/editing_media_view.py para la fila de
        controles de audio.

        El umbral de volumen (500) es más alto que el de editing_media_view.py (260) a
        propósito: ctrl_bar aquí tiene más contenido fijo a la derecha (botones In/Out +
        2 campos de tiempo), y ese contenido empezaba a superponerse con el slider de
        volumen bastante antes de los 260px — con el popup vertical de respaldo (ver
        VolumeControlWidget), esconder el slider antes ya no pierde funcionalidad."""
        if hasattr(self, "volume_control"):
            self.volume_control.set_slider_visible(width >= 500)
        if hasattr(self, "slider_zoom_x"):
            self.slider_zoom_x.setVisible(width >= 320)
        if hasattr(self, "slider_zoom_y"):
            self.slider_zoom_y.setVisible(width >= 320)

    def _init_media_player(self):
        self.media_player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.setVideoOutput(self.video_item)

        self.media_player.positionChanged.connect(self._on_player_position_changed)
        self.media_player.durationChanged.connect(self._on_player_duration_changed)
        self.media_player.mediaStatusChanged.connect(self._on_media_status_changed)
        self.media_player.tracksChanged.connect(self._rebuild_audio_track_menu)

        # Medidor de volumen en vivo: QAudioBufferOutput entrega los buffers de audio reales
        # que se están reproduciendo (con su conteo real de canales), en vez de estimar el
        # nivel a partir de la waveform pre-calculada (que siempre es mono/mezclada).
        self.audio_buffer_output = QAudioBufferOutput(self)
        self.media_player.setAudioBufferOutput(self.audio_buffer_output)
        self.audio_buffer_output.audioBufferReceived.connect(self._on_audio_buffer_received)

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------
    def load_media(self, media_path: str, media_type: str = "video", duration_sec: float = 0.0, fps: float = 30.0,
                    initial_in_sec: float = None, initial_out_sec: float = None,
                    initial_audio_track_selection: str | int | None = None):
        """Carga un nuevo archivo multimedia (detiene el anterior y reinicia waveform/rango).

        `initial_audio_track_selection` (None/"all"/int) se aplica recién en
        _rebuild_audio_track_menu(), cuando el reproductor termina de detectar las pistas
        reales de ESTE archivo (es asíncrono) - aquí solo se deja pendiente."""
        self.cleanup(stop_only=True)

        self.media_path = media_path or ""
        self.media_type = (media_type or "video").lower()
        self.duration_sec = duration_sec if duration_sec and duration_sec > 0 else 1.0
        self.fps = fps if fps and fps > 0 else 30.0
        self.in_sec = initial_in_sec if initial_in_sec is not None else 0.0
        self.out_sec = initial_out_sec if initial_out_sec is not None else self.duration_sec
        self.pending_download = False
        self._preview_loop_range = None
        self._first_frame_rendered = False
        self._active_audio_track = 0
        self._pending_audio_track_selection = initial_audio_track_selection
        self.btn_audio_track.setVisible(False)
        self.chk_all_tracks.setVisible(False)
        self.audio_track_menu.clear()

        # Calidad de previsualización: se reinicia por archivo, pero el modo elegido por el
        # usuario (Auto o una resolución manual) se mantiene entre archivos.
        self._proxy_divisor = 1
        self._pending_proxy_divisor = None
        self._native_size_known = False
        self._native_size = None

        # El recorte interactivo es por archivo, igual que in_sec/out_sec: no debe
        # sobrevivir al cambiar de archivo previsualizado.
        self.crop_overlay.hide_and_reset()

        has_media = bool(self.media_path and os.path.exists(self.media_path))
        is_video = has_media and self.media_type in ("video", "video+audio", "imagen")
        is_audio = has_media and not is_video

        if hasattr(self, "empty_preview_widget"):
            self.empty_preview_widget.setVisible(not has_media)
        self.video_widget.setVisible(is_video)
        self.lbl_audio_art.setVisible(is_audio)
        if hasattr(self, "preview_container"):
            self.preview_container.set_checkerboard_visible(is_video)

        if is_audio:
            filename = os.path.basename(self.media_path)
            self.lbl_audio_art.setText(self.tr("Pista de Audio") + f": {filename}" if filename else self.tr("Vista Previa de Audio"))
        self.btn_quality.setVisible(is_video)
        self._update_quality_button_text()

        self.timeline_ruler.media_type = self.media_type
        self.timeline_ruler.is_video = is_video
        self.timeline_ruler.duration_sec = max(0.001, self.duration_sec)
        self.timeline_ruler.fps = self.fps
        self.timeline_ruler.show_hours = self.duration_sec >= 3600.0
        self.timeline_ruler.update()
        self.video_widget.reset_zoom()

        if self.media_path and os.path.exists(self.media_path):
            self.media_player.setSource(QUrl.fromLocalFile(self.media_path))
            if is_video:
                QTimer.singleShot(50, self._render_initial_frame)
                # Si el usuario ya había elegido una resolución manual, se re-aplica al nuevo
                # archivo. El modo Auto se evalúa aparte, en cuanto se conozca la resolución
                # real del video (_on_video_native_size_changed).
                if self._proxy_mode == "manual" and self._manual_divisor > 1:
                    self._apply_proxy_divisor(self._manual_divisor)

        self._update_waveform_range()
        self._update_time_label()
        self.load_waveform()
        QTimer.singleShot(100, self._sync_ruler)

    def clear(self):
        """Detiene la reproducción y vacía el reproductor (sin archivo seleccionado)."""
        self.cleanup(stop_only=True)
        self.media_path = ""
        self.media_player.setSource(QUrl())
        self.video_widget.reset_zoom()
        self.video_widget.setVisible(False)
        self.lbl_audio_art.setVisible(False)
        if hasattr(self, "empty_preview_widget"):
            self.empty_preview_widget.setVisible(True)
        if hasattr(self, "preview_container"):
            self.preview_container.set_checkerboard_visible(False)
        self.waveform_widget.set_audio_path("")
        self.waveform_widget.set_saved_subclip_ratios([])
        self.lbl_time_info.setText("00:00:00.000 / 00:00:00.000")
        if hasattr(self, "btn_audio_track"):
            self.btn_audio_track.setVisible(False)
        if hasattr(self, "chk_all_tracks"):
            self.chk_all_tracks.setVisible(False)
        if hasattr(self, "btn_quality"):
            self.btn_quality.setVisible(False)

    def set_fps(self, fps: float):
        if fps and fps > 0:
            self.fps = fps
            self.timeline_ruler.fps = fps
            self.timeline_ruler.update()

    def get_in_out(self):
        return self.in_sec, self.out_sec

    # ------------------------------------------------------------------
    # Recorte interactivo (crop)
    # ------------------------------------------------------------------
    def _on_video_rect_changed(self, rect: QRectF):
        """Llamado en cada refit() de la vista (resize/zoom). Actualiza el recorte y,
        como el cuadro de video cambió, también el "cuadro de salida efectivo" que usan
        las marcas de agua para posicionarse (ver _effective_output_rect)."""
        self._current_video_rect = QRectF(rect)
        self.crop_overlay.set_video_rect(rect)
        self._refresh_watermark_output_rect()

    def _effective_output_rect(self) -> QRectF:
        """El cuadro que realmente sobrevive al export: el recorte activo si está
        visible, si no el cuadro de video completo. Las marcas de agua se posicionan
        siempre relativas a esto, nunca al video sin recortar."""
        if self.crop_overlay.isVisible():
            return self.crop_overlay.get_crop_rect_scene()
        return self._current_video_rect

    def _refresh_watermark_output_rect(self):
        out_rect = self._effective_output_rect()
        self.text_watermark_overlay.set_output_rect(out_rect)
        self.image_watermark_overlay.set_output_rect(out_rect)

    def _on_crop_overlay_changed(self):
        self._refresh_watermark_output_rect()
        self.crop_rect_changed.emit()

    def set_crop_editing_enabled(self, enabled: bool, fw: float | None = None, fh: float | None = None):
        """Activa/desactiva el rectángulo de recorte interactivo sobre el video. Al
        activarlo arranca centrado con el tamaño fraccional (fw, fh) dado (fracción del
        cuadro de video) — normalmente el que corresponde al Ancho/Alto elegidos."""
        self.video_widget.set_crop_edit_mode(enabled)
        if enabled and fw and fh:
            self.crop_overlay.activate(fw, fh)
            self.crop_overlay.setVisible(True)
        else:
            self.crop_overlay.hide_and_reset()
        self._refresh_watermark_output_rect()

    def update_crop_size(self, fw: float, fh: float):
        """Redimensiona el recorte activo a un tamaño fraccional específico, manteniendo
        su centro — se llama cuando el usuario tipea Ancho/Alto a mano mientras el modo
        interactivo ya está activo (dirección opuesta a get_crop_rect)."""
        if self.crop_overlay.isVisible() and fw and fh:
            self.crop_overlay.resize_keep_center(fw, fh)
            self._refresh_watermark_output_rect()

    def get_crop_rect(self):
        """(fx, fy, fw, fh) del recorte activo, como fracción del cuadro de video, o None
        si el modo interactivo está desactivado."""
        if not self.crop_overlay.isVisible():
            return None
        return self.crop_overlay.get_crop_fraction()

    def has_custom_crop(self) -> bool:
        """True si el usuario efectivamente arrastró/redimensionó el recorte (no solo
        activó el modo de edición)."""
        return self.crop_overlay.isVisible() and self.crop_overlay.is_touched()

    # ------------------------------------------------------------------
    # Marcas de agua interactivas (texto / imagen)
    # ------------------------------------------------------------------
    def set_text_watermark(self, enabled: bool, text: str = "", font_family: str = "", weight: int = 400,
                            size_pct: float = 5.0, color: QColor = None, opacity: float = 1.0):
        if enabled and text:
            self.text_watermark_overlay.set_style(text, font_family, weight, size_pct, color, opacity)
            self.text_watermark_overlay.set_output_rect(self._effective_output_rect())
            self.text_watermark_overlay.setVisible(True)
        else:
            self.text_watermark_overlay.setVisible(False)

    def set_image_watermark(self, enabled: bool, image_path: str = "",
                             scale_pct: float = 15.0, opacity: float = 1.0):
        if enabled and image_path:
            self.image_watermark_overlay.set_style(image_path, scale_pct, opacity)
            self.image_watermark_overlay.set_output_rect(self._effective_output_rect())
            self.image_watermark_overlay.setVisible(True)
        else:
            self.image_watermark_overlay.setVisible(False)

    def get_text_watermark_position(self):
        """(fx, fy) de la marca de agua de texto, o None si está desactivada."""
        if not self.text_watermark_overlay.isVisible():
            return None
        return self.text_watermark_overlay.get_position_fraction()

    def get_image_watermark_position(self):
        """(fx, fy) de la marca de agua de imagen, o None si está desactivada."""
        if not self.image_watermark_overlay.isVisible():
            return None
        return self.image_watermark_overlay.get_position_fraction()

    def get_text_watermark_size_pct(self):
        """% de tamaño actual (puede haber cambiado por arrastre de la manija), o None
        si la marca de agua de texto está desactivada."""
        if not self.text_watermark_overlay.isVisible():
            return None
        return self.text_watermark_overlay.get_size_pct()

    def get_image_watermark_size_pct(self):
        """% de escala actual (puede haber cambiado por arrastre de la manija), o None
        si la marca de agua de imagen está desactivada."""
        if not self.image_watermark_overlay.isVisible():
            return None
        return self.image_watermark_overlay.get_size_pct()

    def set_in_out(self, in_sec: float, out_sec: float):
        self.in_sec = max(0.0, in_sec)
        self.out_sec = max(self.in_sec, out_sec)
        self._update_waveform_range()
        self._update_time_label()
        self.range_changed.emit(self.in_sec, self.out_sec)

    def is_playing(self) -> bool:
        return self.media_player.playbackState() == QMediaPlayer.PlayingState

    def set_pending(self, pending: bool):
        """Activa/desactiva el modo 'pendiente de descarga': deshabilita controles de edición
        y muestra el estado especial de descarga en la waveform (usado para medios remotos)."""
        self.pending_download = pending
        for w in (self.btn_play, self.btn_set_in, self.btn_set_out):
            w.setEnabled(not pending)
        self.waveform_widget.set_downloading(pending)

    def set_resolved_media_path(self, local_path: str, fps: float = None):
        """Reemplaza el medio pendiente por el archivo real ya descargado en alta calidad."""
        logger.info(f"[MediaTrimPlayerWidget] Medio resuelto en alta calidad: {local_path}")
        self.media_path = local_path
        if fps:
            self.set_fps(fps)
        self._first_frame_rendered = False
        self.media_player.setSource(QUrl.fromLocalFile(local_path))
        if self.media_type == "video":
            QTimer.singleShot(50, self._render_initial_frame)
        self.set_pending(False)
        self.load_waveform()

    def set_resolve_error(self, message: str):
        logger.error(f"[MediaTrimPlayerWidget] Error resolviendo el medio en alta calidad: {message}")
        self.waveform_widget.set_error(True, message)

    def set_saved_ranges(self, ranges: list):
        """Muestra en la waveform, de fondo, rangos ya guardados en otra parte (p.ej. subclips)."""
        self.waveform_widget.set_saved_subclip_ratios(ranges)

    def cleanup(self, stop_only: bool = False):
        """Desconecta señales del caché global de waveform y detiene reproducción/timers."""
        self._pending_source_restore = None
        if not stop_only and self._hires_signal_connected:
            try:
                mgr = WaveformCacheManager.get_instance()
                mgr.hires_waveform_loaded.disconnect(self._on_hires_waveform_loaded)
            except Exception:
                pass
            self._hires_signal_connected = False

        self.waveform_widget.set_loading(False)
        self.waveform_widget.set_downloading(False)

        try:
            self.media_player.stop()
        except Exception:
            pass

        apply_player_play_button_style(self.btn_play, is_playing=False, icon_size=18)
        self.audio_meter.reset_levels()

    # ------------------------------------------------------------------
    # Reproducción
    # ------------------------------------------------------------------
    def _on_video_native_size_changed(self, size: QSizeF):
        """Se dispara cuando se conoce (o cambia) la resolución real del video: reajusta el
        QGraphicsView para que el fotograma quede centrado y a escala manteniendo su
        proporción de aspecto real (vertical, cuadrado u horizontal)."""
        self.video_widget.refit()

        # Ojo: este mismo evento se vuelve a disparar (con una resolución MENOR) en cuanto se
        # cambia a un proxy. Por eso solo se usa para decidir la calidad "Auto" la primera vez
        # que se conoce el tamaño real del archivo ORIGINAL — si no, entraría en bucle
        # (proxy pequeño -> Auto decide "completa" -> vuelve al original -> Auto decide proxy
        # otra vez -> ...).
        if not self._native_size_known and not size.isEmpty():
            self._native_size_known = True
            self._native_size = (size.width(), size.height())
            if self._proxy_mode == "auto":
                self._apply_proxy_divisor(self._compute_auto_divisor(size.width(), size.height()))

    def _init_quality_menu(self):
        """Inicializa las opciones del menú emergente de resolución de previsualización."""
        self.quality_menu.clear()
        for idx, (label, mode, divisor) in enumerate(_QUALITY_OPTIONS):
            action = self.quality_menu.addAction(self.tr(label))
            action.setCheckable(True)
            action.setChecked(idx == 0)
            action.triggered.connect(lambda checked=False, i=idx: self._on_quality_option_changed(i))
        self._update_quality_button_text(0)

    def _update_quality_button_text(self, index: int = None, status_text: str = ""):
        """Actualiza el texto del botón chip de calidad y marca la acción activa en el menú."""
        if index is None:
            index = 0
            for i, (l, m, d) in enumerate(_QUALITY_OPTIONS):
                if m == self._proxy_mode and (m != "manual" or d == self._manual_divisor):
                    index = i
                    break
        if index < 0 or index >= len(_QUALITY_OPTIONS):
            index = 0
        label = self.tr(_QUALITY_OPTIONS[index][0])
        for i, action in enumerate(self.quality_menu.actions()):
            action.setChecked(i == index)

        display = f"{label}"
        if status_text:
            display += f" ({status_text})"
        self.btn_quality.setText(f"{display} ▾")
        self._reposition_quality_button()

    def _reposition_quality_button(self):
        """Posiciona el botón de calidad en la esquina superior derecha del contenedor de video."""
        if hasattr(self, "btn_quality") and self.btn_quality and hasattr(self, "preview_container"):
            self.btn_quality.adjustSize()
            x = self.preview_container.width() - self.btn_quality.width() - 8
            self.btn_quality.move(max(0, x), 8)
            self.btn_quality.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_quality_button()
        # Si extract_timeline_container() ya se llamó (VideoToolsTab), ctrl_bar/zoom_bar ya
        # no viven en self — su ancho real se sigue por separado vía eventFilter sobre
        # _timeline_container (ver más abajo), no aquí.
        if getattr(self, "_timeline_container", None) is None:
            self._recalculate_compact_controls(self.width())

    # ------------------------------------------------------------------
    # Calidad de previsualización (proxies para medios pesados/RAW)
    # ------------------------------------------------------------------
    def _compute_auto_divisor(self, width: float, height: float) -> int:
        """Heurística simple para el modo Auto: cuanto más pesado (grande) es el video nativo,
        más se reduce la previsualización. No mira el códec, solo la resolución."""
        long_side = max(width, height)
        if long_side >= 3840:   # 4K y superiores
            return 4
        if long_side >= 2560:   # ~1440p/2K
            return 2
        return 1                # 1080p o menos: no hace falta proxy

    def _on_quality_option_changed(self, index: int):
        if index < 0 or index >= len(_QUALITY_OPTIONS):
            return
        _label, mode, divisor = _QUALITY_OPTIONS[index]
        self._proxy_mode = mode
        self._update_quality_button_text(index)
        if mode == "manual":
            self._manual_divisor = divisor
            self._apply_proxy_divisor(divisor)
        elif self._native_size_known:
            w, h = self._native_size
            self._apply_proxy_divisor(self._compute_auto_divisor(w, h))

    def _apply_proxy_divisor(self, divisor: int):
        """Cambia (o solicita) la resolución de previsualización activa. No reemplaza nunca el
        archivo original: solo afecta qué decodifica el reproductor mientras se previsualiza."""
        divisor = divisor or 1
        if not self.media_path or divisor == self._proxy_divisor:
            return

        if divisor <= 1:
            self._proxy_divisor = 1
            self._pending_proxy_divisor = None
            self._update_quality_button_text()
            self._swap_playback_source(self.media_path)
            return

        mgr = ProxyCacheManager.get_instance()
        cached = mgr.get_cached_proxy_path(self.media_path, divisor, self._active_audio_track)
        if cached:
            self._proxy_divisor = divisor
            self._pending_proxy_divisor = None
            self._update_quality_button_text()
            self._swap_playback_source(cached)
            return

        # Aún no existe en caché: se pide en segundo plano y se sigue reproduciendo lo que
        # esté activo ahora mismo (no se interrumpe la vista previa) hasta que esté listo.
        if not self._proxy_signal_connected:
            mgr.proxy_ready.connect(self._on_proxy_ready)
            mgr.proxy_failed.connect(self._on_proxy_failed)
            self._proxy_signal_connected = True
        self._pending_proxy_divisor = divisor
        mgr.request_proxy(self.media_path, divisor, self._active_audio_track)
        self._update_quality_button_text(status_text=self.tr("generando…"))

    def _on_proxy_ready(self, file_path: str, divisor: int, audio_track: int, proxy_path: str):
        if (file_path == self.media_path and audio_track == self._active_audio_track
                and divisor == self._pending_proxy_divisor):
            self._proxy_divisor = divisor
            self._pending_proxy_divisor = None
            self._update_quality_button_text()
            self._swap_playback_source(proxy_path)

    def _on_proxy_failed(self, file_path: str, divisor: int, audio_track: int):
        if (file_path == self.media_path and audio_track == self._active_audio_track
                and divisor == self._pending_proxy_divisor):
            self._pending_proxy_divisor = None
            self._update_quality_button_text(status_text=self.tr("no disp."))

    def _swap_playback_source(self, path: str):
        """Cambia la fuente del reproductor manteniendo posición y estado de reproducción.
        La waveform, el medidor y la selección de pista de audio no se ven afectados: siguen
        operando sobre self.media_path (el archivo original), no sobre el proxy."""
        if not path or not os.path.exists(path):
            return
        was_playing = self.media_player.playbackState() == QMediaPlayer.PlayingState
        pos_ms = self.media_player.position()
        # No alcanza con llamar setPosition()/play() justo después de setSource(): QMediaPlayer
        # carga la nueva fuente de forma asíncrona y, al terminar, resetea la posición a 0 por su
        # cuenta — pisando silenciosamente el setPosition() hecho antes de tiempo. Por eso cambiar
        # de calidad "reiniciaba" la reproducción. Se guarda el estado a restaurar y se aplica
        # recién en _on_media_status_changed, cuando el nuevo origen ya terminó de cargar.
        self._pending_source_restore = (pos_ms, was_playing)
        self.media_player.setSource(QUrl.fromLocalFile(path))

    def _render_initial_frame(self):
        """Forzar al reproductor de video a decodificar y presentar el primer fotograma en QVideoWidget."""
        if self.media_type == "video" and self.media_player:
            state = self.media_player.playbackState()
            if state == QMediaPlayer.PlaybackState.StoppedState:
                pos_ms = self._clamp_seek_ms(self.in_sec) if self.in_sec > 0 else 0
                self.media_player.pause()
                self.media_player.setPosition(pos_ms)

    def _on_media_status_changed(self, status):
        if status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia):
            if self._pending_source_restore is not None:
                pending = self._pending_source_restore
                self._pending_source_restore = None
                # setPosition() justo aquí a veces no alcanza: el backend FFmpeg de Qt Multimedia
                # reporta LoadedMedia/BufferedMedia un instante antes de terminar su propia
                # inicialización interna (tabla de seek, primer frame), y puede pisar nuestro
                # setPosition() con su propio arranque en 0. Un pequeño delay le da tiempo a
                # asentarse antes de imponer la posición real.
                QTimer.singleShot(60, lambda p=pending: self._apply_source_restore(p))
            if self.media_type == "video" and not self._first_frame_rendered:
                self._first_frame_rendered = True
                self._render_initial_frame()
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._on_end_of_media()

    def _on_end_of_media(self):
        """Al terminar la reproducción, restaura el estado visual de los controles."""
        apply_player_play_button_style(self.btn_play, is_playing=False, icon_size=18)
        self.audio_meter.reset_levels()
        self.playing_changed.emit(False)

    def _apply_source_restore(self, pending):
        pos_ms, was_playing = pending
        if was_playing:
            self.media_player.setPosition(pos_ms)
            self.media_player.play()
        else:
            self.media_player.pause()
            self.media_player.setPosition(pos_ms)

    # ------------------------------------------------------------------
    # Selección de pista de audio (medios multipista)
    # ------------------------------------------------------------------
    def _rebuild_audio_track_menu(self):
        """Reconstruye el menú de pistas de audio disponibles; los controles multipista
        solo se muestran cuando el medio tiene más de una pista (caso normal: quedan ocultos)."""
        tracks = self.media_player.audioTracks()
        count = len(tracks)
        if count <= 1:
            if hasattr(self, "btn_audio_track"):
                self.btn_audio_track.setVisible(False)
            if hasattr(self, "chk_all_tracks"):
                self.chk_all_tracks.setVisible(False)
            self._pending_audio_track_selection = None
            return

        # Selección restaurada por load_media() (ver caché por archivo en
        # video_tools_view.py) - se aplica una sola vez, aquí, que es cuando recién se
        # conocen las pistas REALES de este archivo (tracksChanged es asíncrono).
        pending = self._pending_audio_track_selection
        self._pending_audio_track_selection = None

        if isinstance(pending, int) and 0 <= pending < count:
            active = pending
            self.media_player.setActiveAudioTrack(active)
            want_all_tracks = False
        else:
            active = self.media_player.activeAudioTrack()
            if active < 0:
                active = 0
            want_all_tracks = True if pending is None else (pending == "all")

        self.audio_track_menu.clear()
        for i, meta in enumerate(tracks):
            action = self.audio_track_menu.addAction(self._describe_audio_track(i, meta))
            action.setCheckable(True)
            action.setChecked(i == active)
            action.triggered.connect(lambda checked=False, idx=i: self._on_audio_track_selected(idx))

        track_changed = active != self._active_audio_track
        self._active_audio_track = active
        self.btn_audio_track.setText(self.tr("Pista {0} ▾").format(active + 1))
        self.btn_audio_track.adjustSize()
        self.btn_audio_track.setVisible(True)
        # blockSignals: esto es una restauración interna, no una elección del usuario -
        # no debe disparar audio_track_selection_changed (evita un guardado redundante en
        # el caché, y evita reentradas si el handler externo reacciona a la señal).
        self.chk_all_tracks.blockSignals(True)
        self.chk_all_tracks.setChecked(want_all_tracks)
        self.chk_all_tracks.blockSignals(False)
        self.chk_all_tracks.setVisible(True)
        if track_changed:
            # QMediaPlayer tarda en detectar las pistas del medio (tracksChanged es
            # asíncrono), así que load_waveform() ya pudo haber pedido la extracción para la
            # pista 0 asumida por defecto antes de saber que la realmente activa es otra. Se
            # vuelve a pedir para la pista correcta, igual que al cambiarla manualmente
            # (_on_audio_track_selected) — si no, esa primera extracción llega etiquetada con
            # la pista vieja, ya no coincide, y se descarta dejando la waveform pegada en la
            # animación de carga para siempre.
            self.load_waveform()

    def _describe_audio_track(self, index: int, meta: QMediaMetaData) -> str:
        title = str(meta.stringValue(QMediaMetaData.Key.Title) or "").strip()
        lang = str(meta.stringValue(QMediaMetaData.Key.Language) or "").strip()
        codec = str(meta.stringValue(QMediaMetaData.Key.AudioCodec) or "").strip()

        label = self.tr("Pista {0}").format(index + 1)
        extra = title or lang
        if extra:
            label += f" — {extra}"
        if codec:
            label += f" ({codec})"
        return label

    def _on_audio_track_selected(self, index: int):
        if index == self._active_audio_track:
            return
        self.media_player.setActiveAudioTrack(index)
        self._active_audio_track = index
        self.btn_audio_track.setText(self.tr("Pista {0} ▾").format(index + 1))
        self.btn_audio_track.adjustSize()
        for i, action in enumerate(self.audio_track_menu.actions()):
            action.setChecked(i == index)
        # La waveform y el medidor reflejan la pista seleccionada: volver a extraerla.
        self.load_waveform()
        self.audio_track_selection_changed.emit()

    def get_audio_track_selection(self) -> str | int | None:
        """Retorna la selección de pistas de audio para el trabajo de recodificación:
        - None: Si el medio tiene solo 1 pista o no es multipista.
        - 'all': Si tiene multipista y 'Procesar todas las pistas' está marcado.
        - int (0-based): Si tiene multipista y se debe procesar solo la pista activa seleccionada.
        """
        if not hasattr(self, "chk_all_tracks") or not self.chk_all_tracks.isVisible():
            return None
        if self.chk_all_tracks.isChecked():
            return "all"
        return self._active_audio_track

    def has_multiple_audio_tracks(self) -> bool:
        """Indica si el medio actualmente cargado tiene 2 o más pistas de audio."""
        return hasattr(self, "chk_all_tracks") and self.chk_all_tracks.isVisible()

    def eventFilter(self, obj, event):
        if obj is getattr(self, "_timeline_container", None) and event.type() == QEvent.Type.Resize:
            self._recalculate_compact_controls(obj.width())
            return super().eventFilter(obj, event)
        if not hasattr(self, "scroll_area") or self.scroll_area is None:
            return super().eventFilter(obj, event)
        if obj == self.scroll_area.viewport() and event.type() == QEvent.Type.Wheel:
            modifiers = event.modifiers()
            # Scroll normal -> Zoom X
            if modifiers == Qt.NoModifier:
                delta = event.angleDelta().y()
                if delta != 0:
                    old_zoom = self.slider_zoom_x.value()
                    step_val = max(20, int(old_zoom * 0.15))
                    zoom_step = step_val if delta > 0 else -step_val
                    new_zoom = max(self.slider_zoom_x.minimum(), min(old_zoom + zoom_step, self.slider_zoom_x.maximum()))
                    if new_zoom != old_zoom:
                        is_playing = self.media_player.playbackState() == QMediaPlayer.PlayingState
                        if is_playing:
                            self.slider_zoom_x.setValue(new_zoom)
                            QTimer.singleShot(0, self._center_scroll_on_playhead)
                        else:
                            # Zoom enfocado en la posición del ratón cuando está pausado
                            h_bar = self.scroll_area.horizontalScrollBar()
                            mouse_x = event.position().x()
                            old_w = self.waveform_widget.width()
                            old_wave_x = h_bar.value() + mouse_x
                            target_ratio = old_wave_x / old_w if old_w > 0 else 0.5

                            self.slider_zoom_x.setValue(new_zoom)
                            QTimer.singleShot(0, lambda r=target_ratio, mx=mouse_x: self._center_scroll_on_ratio(r, mx))
                    return True
            # Alt/Shift + Scroll -> Pan Horizontal
            elif modifiers in (Qt.ShiftModifier, Qt.AltModifier):
                h_bar = self.scroll_area.horizontalScrollBar()
                delta = event.angleDelta().y()
                if delta != 0:
                    h_bar.setValue(h_bar.value() - delta)
                    return True
        return super().eventFilter(obj, event)

    def _center_scroll_on_playhead(self):
        """Centra la vista del scroll area sobre el cabezal de reproducción."""
        h_bar = self.scroll_area.horizontalScrollBar()
        viewport_w = self.scroll_area.viewport().width()
        new_waveform_w = self.waveform_widget.width()
        new_playhead_x = self.waveform_widget._playback_ratio * new_waveform_w
        target_scroll = int(new_playhead_x - viewport_w / 2)
        h_bar.setValue(max(0, min(target_scroll, h_bar.maximum())))
        self._sync_ruler()

    def _center_scroll_on_ratio(self, ratio: float, mouse_x: float):
        """Mantiene exactamente bajo el puntero del ratón el punto del audio donde se hizo zoom."""
        h_bar = self.scroll_area.horizontalScrollBar()
        new_waveform_w = self.waveform_widget.width()
        new_mouse_x = ratio * new_waveform_w
        target_scroll = int(new_mouse_x - mouse_x)
        h_bar.setValue(max(0, min(target_scroll, h_bar.maximum())))
        self._sync_ruler()

    def _on_zoom_x_changed(self, value):
        zoom = value / 100.0
        base_width = self.scroll_area.viewport().width()
        new_width = int(base_width * zoom)
        self.waveform_widget.setMinimumWidth(new_width)
        # Sincronizar la regla después del cambio de zoom
        QTimer.singleShot(0, self._sync_ruler)

    def _sync_ruler(self):
        """Sincroniza la regla de tiempo con el scroll y el tamaño del waveform."""
        self.timeline_ruler.set_sync(
            scroll_offset=self.scroll_area.horizontalScrollBar().value(),
            waveform_width=self.waveform_widget.width(),
            viewport_width=self.scroll_area.viewport().width()
        )

    def _on_zoom_y_changed(self, value):
        zoom = value / 100.0
        self.waveform_widget.zoom_y = zoom
        self.waveform_widget.update()

    def _on_audio_buffer_received(self, buffer):
        """Actualiza el medidor multicanal con los niveles reales del buffer de audio que se
        está reproduciendo en este instante (llega solo mientras hay reproducción activa)."""
        if self.media_player.playbackState() != QMediaPlayer.PlayingState:
            return
        peaks = _channel_peaks_from_buffer(buffer)
        if not peaks:
            return
        self.audio_meter.set_channel_count(len(peaks))
        self.audio_meter.set_levels(peaks)

    def load_waveform(self):
        if not self.media_path:
            self.waveform_widget.set_audio_path("")
            return
        self.waveform_widget.set_audio_path(self.media_path)
        mgr = WaveformCacheManager.get_instance()
        # Se fija en una variable aparte la pista con la que se pide esta extracción en
        # concreto: `self._active_audio_track` puede cambiar por su cuenta poco después (ver
        # _rebuild_audio_track_menu, que se dispara de forma asíncrona en cuanto QMediaPlayer
        # termina de detectar las pistas del archivo). Si el filtro de _on_hires_waveform_loaded
        # comparara contra el valor "en vivo" de _active_audio_track en vez de este snapshot,
        # una extracción en curso pedida como pista 0 llegaría después con ese cambio ya hecho,
        # no coincidiría, y sus picos se descartarían en silencio — dejando la waveform pegada
        # en la animación de carga para siempre (solo "arreglable" cambiando de ítem o
        # reabriendo el diálogo, porque ahí sí entra por el camino de caché ya resuelta).
        requested_track = self._active_audio_track
        self._pending_waveform_track = requested_track
        # Intentar cargar alta resolución primero (de la pista de audio solicitada)
        hires = mgr.get_cached_hires_peaks(self.media_path, requested_track)
        if hires is not None:
            self.waveform_widget.set_hires_peaks(hires)
        else:
            self.waveform_widget.set_loading(True)
            if not self._hires_signal_connected:
                try:
                    mgr.hires_waveform_loaded.connect(self._on_hires_waveform_loaded)
                    self._hires_signal_connected = True
                except Exception:
                    pass
            mgr.request_hires_waveform(self.media_path, audio_track=requested_track)

    def _same_path(self, p1: str, p2: str) -> bool:
        if not p1 or not p2:
            return False
        try:
            return os.path.normpath(os.path.abspath(p1)).lower() == os.path.normpath(os.path.abspath(p2)).lower()
        except Exception:
            return p1 == p2

    def _on_hires_waveform_loaded(self, path: str, peaks: list, audio_track: int = 0):
        # Descarta resultados de una pista que el usuario ya dejó de tener seleccionada
        # (p.ej. si cambió de pista mientras la anterior todavía se estaba extrayendo). Se
        # compara contra la pista que efectivamente se pidió (_pending_waveform_track), no
        # contra self._active_audio_track: ese último puede haber cambiado solo, de forma
        # asíncrona, después de pedir la extracción (ver load_waveform).
        if self._same_path(path, self.media_path) and audio_track == self._pending_waveform_track:
            self.waveform_widget.set_hires_peaks(peaks)
            QTimer.singleShot(0, self._sync_ruler)

    def keyPressEvent(self, event):
        """Maneja los atajos de teclado I (In), O (Out) y Espacio (Play/Pause)."""
        key = event.key()
        if key == Qt.Key_I:
            self.set_in_point()
        elif key == Qt.Key_O:
            self.set_out_point()
        elif key == Qt.Key_Space:
            self.toggle_play_pause()
        else:
            super().keyPressEvent(event)

    def toggle_play_pause(self):
        # Salir siempre de la previsualización en bucle de un rango guardado al usar el play/pause normal.
        self._preview_loop_range = None
        if self.pending_download:
            return
        if self.media_player.playbackState() == QMediaPlayer.PlayingState:
            self.media_player.pause()
            apply_player_play_button_style(self.btn_play, is_playing=False, icon_size=18)
            self.audio_meter.reset_levels()
        else:
            self.media_player.play()
            apply_player_play_button_style(self.btn_play, is_playing=True, icon_size=18)
        self.playing_changed.emit(self.media_player.playbackState() == QMediaPlayer.PlayingState)

    def _clamp_seek_ms(self, sec: float) -> int:
        """Convierte segundos a milisegundos para setPosition dejando siempre un colchon de
        al menos un fotograma antes del final real del medio para evitar caer fuera de rango."""
        frame_ms = 1000.0 / self.fps if self.fps and self.fps > 0 else 33.0
        max_ms = max(0, int(self.duration_sec * 1000) - int(frame_ms))
        ms = int(sec * 1000)
        return max(0, min(ms, max_ms))

    def preview_range(self, in_sec: float, out_sec: float):
        """Reproduce en bucle dentro de un rango dado hasta que el usuario mueva el cabezal manualmente."""
        self._preview_loop_range = (in_sec, out_sec)
        self.media_player.setPosition(self._clamp_seek_ms(in_sec))
        self.media_player.play()
        apply_player_play_button_style(self.btn_play, is_playing=True, icon_size=18)

    def set_in_point(self):
        pos_sec = self.media_player.position() / 1000.0
        if pos_sec >= self.out_sec:
            pos_sec = max(0.0, self.out_sec - 0.5)
        self.in_sec = pos_sec
        self._update_waveform_range()
        self._update_time_label()
        self.range_changed.emit(self.in_sec, self.out_sec)

    def set_out_point(self):
        pos_sec = self.media_player.position() / 1000.0
        if pos_sec <= self.in_sec:
            pos_sec = min(self.duration_sec, self.in_sec + 0.5)
        self.out_sec = pos_sec
        self._update_waveform_range()
        self._update_time_label()
        self.range_changed.emit(self.in_sec, self.out_sec)

    def _update_waveform_range(self):
        if self.duration_sec > 0:
            in_r = self.in_sec / self.duration_sec
            out_r = self.out_sec / self.duration_sec
            self.waveform_widget.set_range_ratios(in_r, out_r)

    def _on_waveform_seek(self, ratio: float):
        if self.duration_sec > 0:
            pos_sec = ratio * self.duration_sec
            if self._preview_loop_range is not None:
                lo, hi = self._preview_loop_range
                if pos_sec < lo or pos_sec > hi:
                    self._preview_loop_range = None
            self.media_player.setPosition(self._clamp_seek_ms(pos_sec))

    def _on_waveform_range_changed(self, in_r: float, out_r: float):
        if self.duration_sec > 0:
            self.in_sec = in_r * self.duration_sec
            self.out_sec = out_r * self.duration_sec
            self._update_time_label()
            self.range_changed.emit(self.in_sec, self.out_sec)

    def _on_player_position_changed(self, pos_ms: int):
        pos_sec = pos_ms / 1000.0

        # Previsualizacion en bucle de un rango guardado
        if self._preview_loop_range is not None:
            lo, hi = self._preview_loop_range
            frame_sec = (1000.0 / self.fps if self.fps and self.fps > 0 else 33.0) / 1000.0
            if pos_sec >= hi - frame_sec:
                self.media_player.setPosition(self._clamp_seek_ms(lo))
                return

        if self.duration_sec > 0:
            ratio = pos_sec / self.duration_sec
            self.waveform_widget.set_playback_ratio(ratio)
        self._update_time_label()

    def _on_player_duration_changed(self, dur_ms: int):
        if dur_ms > 0:
            new_dur = dur_ms / 1000.0
            # Si out_sec estaba "al final" de la duración anterior, o es inválido, actualizarlo al nuevo final
            if abs(self.out_sec - self.duration_sec) < 0.05 or self.out_sec > new_dur or self.out_sec <= 0:
                self.out_sec = new_dur
            self.duration_sec = new_dur
            self.timeline_ruler.duration_sec = max(0.001, new_dur)
            self.timeline_ruler.show_hours = new_dur >= 3600.0
            self._update_waveform_range()
            self._update_time_label()

    def _update_time_label(self):
        pos_sec = self.media_player.position() / 1000.0
        cur_fmt = self._format_seconds_ms(pos_sec)
        dur_fmt = self._format_seconds_ms(self.duration_sec)

        self.lbl_time_info.setText(f"{cur_fmt} / {dur_fmt}")
        if not self.input_time_start.hasFocus():
            self.input_time_start.setText(self._format_seconds_ms(self.in_sec))
        if not self.input_time_end.hasFocus():
            self.input_time_end.setText(self._format_seconds_ms(self.out_sec))

    def _format_seconds_ms(self, seconds: float) -> str:
        ms = int((seconds % 1) * 1000)
        s = int(seconds) % 60
        m = (int(seconds) // 60) % 60
        h = int(seconds) // 3600
        return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"

    def _parse_time_ms(self, time_str: str):
        try:
            parts = time_str.split(":")
            if len(parts) == 3:
                h = float(parts[0])
                m = float(parts[1])
                s = float(parts[2])
                return h * 3600 + m * 60 + s
        except Exception:
            pass
        return None

    def _on_time_input_changed(self):
        new_in = self._parse_time_ms(self.input_time_start.text())
        new_out = self._parse_time_ms(self.input_time_end.text())

        if new_in is not None:
            self.in_sec = max(0.0, min(new_in, self.duration_sec))
        if new_out is not None:
            self.out_sec = max(0.0, min(new_out, self.duration_sec))

        if self.in_sec >= self.out_sec:
            self.in_sec = max(0.0, self.out_sec - 0.5)

        self._update_waveform_range()
        self._update_time_label()
        self.range_changed.emit(self.in_sec, self.out_sec)

    def _on_volume_changed(self, value):
        float_val = value if isinstance(value, float) else value / 100.0
        self.audio_output.setVolume(float_val)
