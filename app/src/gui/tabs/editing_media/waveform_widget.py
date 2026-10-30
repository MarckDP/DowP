# src/gui/tabs/editing_media/waveform_widget.py
import math
from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QColor, QPen

from gui.styles import get_theme_token, glass_fill

class AudioWaveformWidget(QWidget):
    """Widget que dibuja una forma de onda de audio real e interactiva con barra de reproducción."""
    
    # Señal emitida cuando el usuario hace clic para cambiar la posición del audio (seek)
    seek_requested = Signal(float)  # Retorna el porcentaje (0.0 a 1.0)

    # Señal emitida cuando el usuario arrastra desde dentro de la selección rápida (lite subclip)
    # y NO hay editor conectado: se ofrece el medio completo como arrastre nativo del SO
    # (a una carpeta, o a un editor sin integración en vivo). Se dispara al cruzar el umbral
    # de arrastre de Qt, como cualquier drag nativo (el archivo solo se transfiere al soltar).
    subclip_drag_started = Signal()

    # Señal emitida cuando el usuario suelta el mouse tras arrastrar desde dentro de la selección
    # rápida y SÍ hay un editor conectado: se envía la info del subclip (in/out) por la integración
    # en vivo ya existente, sin arrastre nativo del SO y sin cortar el archivo. Se dispara recién en
    # mouseReleaseEvent (nunca antes ni durante el gesto).
    subclip_send_requested = Signal()

    # Selección rápida terminada (al soltar el clic derecho): (in_ratio, out_ratio), o
    # (-1.0, -1.0) si quedó vacía. El Gestor no la usa; Herramientas IA la toma como el
    # tramo a procesar.
    lite_selection_changed = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(70)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        # Posición de reproducción (0.0 a 1.0)
        self._playback_ratio = 0.0
        self.audio_path = ""
        self.peaks = []  # Almacena las amplitudes reales
        self.is_loading = False
        self.loading_phase = 0.0

        # Selección rápida (lite subclip)
        self._lite_start_ratio = None
        self._lite_end_ratio = None

        # Timer para animación de carga
        from PySide6.QtCore import QTimer
        self.loading_timer = QTimer(self)
        self.loading_timer.setInterval(30)  # ~33 FPS
        self.loading_timer.timeout.connect(self._animate_loading)

    def set_loading(self, loading: bool):
        """Activa o desactiva la animación de carga."""
        self.is_loading = loading
        if loading:
            self.peaks = []
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

    def set_video_only(self, is_video_only: bool, duration: float = 0.0, fps: float = 30.0):
        """Activa el modo de solo video (dibuja una regla de tiempo en lugar de picos)."""
        self.is_video_only = is_video_only
        self.duration_sec = duration
        self.fps = fps
        if is_video_only:
            self.peaks = []
            self.set_loading(False)
        self.update()

    def set_audio_path(self, path: str):
        """Asocia la ruta del archivo de audio."""
        self.audio_path = path or ""
        self.peaks = []  # Reiniciar picos para forzar recálculo asíncrono
        if not path:
            self.set_loading(False)
        self.update()

    def set_peaks(self, peaks: list):
        """Asigna los picos reales extraídos del audio y repinta."""
        self._raw_peaks = list(peaks) if peaks else []
        self.peaks = self._raw_peaks
        self.set_loading(False)  # Detener animación cuando se asignan picos
        self.clear_lite_selection()
        self.update()

    def get_lite_selection(self):
        """Devuelve una tupla (in_ratio, out_ratio) si existe una selección, o (None, None)."""
        if self._lite_start_ratio is not None and self._lite_end_ratio is not None:
            if self._lite_start_ratio == self._lite_end_ratio:
                return None, None
            return min(self._lite_start_ratio, self._lite_end_ratio), max(self._lite_start_ratio, self._lite_end_ratio)
        return None, None

    def set_lite_selection(self, in_ratio: float, out_ratio: float):
        """Marca una selección rápida desde fuera (sin emitir lite_selection_changed)."""
        self._lite_start_ratio = max(0.0, min(in_ratio, 1.0))
        self._lite_end_ratio = max(0.0, min(out_ratio, 1.0))
        self.update()

    def clear_lite_selection(self):
        """Limpia la selección rápida."""
        self._lite_start_ratio = None
        self._lite_end_ratio = None
        self.update()

    def _is_ratio_inside_lite_selection(self, ratio: float) -> bool:
        in_ratio, out_ratio = self.get_lite_selection()
        if in_ratio is None:
            return False
        return in_ratio <= ratio <= out_ratio

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_raw_peaks") and self._raw_peaks and not self.is_loading:
            self.peaks = self._raw_peaks
            self.update()

    def _resample_peaks(self, peaks: list, target_count: int) -> list:
        if not peaks or target_count <= 0 or len(peaks) == target_count:
            return peaks
        n = len(peaks)
        resampled = []
        for i in range(target_count):
            pos = i * (n - 1) / max(1, target_count - 1)
            idx = int(pos)
            frac = pos - idx
            if idx >= n - 1:
                resampled.append(peaks[-1])
            else:
                val = peaks[idx] * (1.0 - frac) + peaks[idx + 1] * frac
                resampled.append(val)
        return resampled

    def set_playback_ratio(self, ratio: float):
        """Actualiza la posición del cabezal y repinta el widget."""
        self._playback_ratio = max(0.0, min(ratio, 1.0))
        self.update()

    def get_playback_ratio(self) -> float:
        return self._playback_ratio

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        width = self.width()
        height = self.height()
        acento = get_theme_token('acento_primario', '#B9E640')
        fondo_normal = get_theme_token('fondo_principal', '#0a0a0a')

        # Fondo del espectro
        painter.fillRect(0, 0, width, height, glass_fill(self, fondo_normal))  # con imagen de fondo: translúcido

        # Highlight de selección rápida (lite subclip)
        in_ratio, out_ratio = self.get_lite_selection()
        if in_ratio is not None and out_ratio is not None:
            sel_start_x = 10
            sel_span = max(1, (width - 10) - sel_start_x)
            sel_x = sel_start_x + in_ratio * sel_span
            sel_w = (out_ratio - in_ratio) * sel_span
            
            # Fondo de la selección
            sel_color = QColor(acento)
            sel_color.setAlpha(30)
            painter.fillRect(int(sel_x), 0, int(sel_w), height, sel_color)
            
            # Bordes de la selección
            pen_border = QPen(QColor(acento), 1)
            painter.setPen(pen_border)
            painter.drawLine(int(sel_x), 0, int(sel_x), height)
            painter.drawLine(int(sel_x + sel_w), 0, int(sel_x + sel_w), height)

        mid_y = height / 2

        # Usamos una cantidad constante de barras
        target_num_bars = 120

        # 1. Determinar el set de picos a renderizar (reales o animados de carga)
        if self.is_loading:
            peaks_to_draw = []
            num_sim_bars = target_num_bars
            for i in range(num_sim_bars):
                # Onda oscilante dinámica
                val = math.sin(i * 0.15 + self.loading_phase) * 0.25 + 0.35
                pulse = math.sin(self.loading_phase * 0.5) * 0.1 + 0.9
                peaks_to_draw.append(max(0.05, min(val * pulse, 0.95)))
        elif not self.peaks and not getattr(self, "is_video_only", False):
            # Si no hay picos y no está cargando, dejar vacío (evita confusión)
            return
        else:
            peaks_to_draw = self.peaks

        # Rango horizontal para dibujar
        start_x = 10
        end_x = width - 10
        span = max(1, end_x - start_x)
        
        # Cabezal de reproducción
        playhead_x = start_x + self._playback_ratio * span

        if getattr(self, "is_video_only", False):
            # Dibujar regla de tiempo para video sin audio
            painter.setPen(QPen(QColor(get_theme_token('onda_cuadricula', '#333333')), 1))
            painter.drawLine(start_x, int(mid_y), end_x, int(mid_y))
            
            duration = getattr(self, "duration_sec", 1.0)
            if duration <= 0: duration = 1.0
            fps = getattr(self, "fps", 30.0)
            
            pixels_per_second = span / duration
            intervals = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600]
            interval = 3600
            for inv in intervals:
                if (span / max(0.001, pixels_per_second)) <= inv or (inv * pixels_per_second) >= 80:
                    interval = inv
                    break
                    
            from PySide6.QtGui import QFont
            font = QFont()
            font.setPointSize(7)
            painter.setFont(font)
            
            t = 0.0
            while t <= duration:
                x = start_x + (t / duration) * span
                if 0 <= x <= width:
                    painter.setPen(QPen(QColor(get_theme_token('texto_tenue', '#888888')), 1))
                    painter.drawLine(int(x), int(mid_y), int(x), int(mid_y) - 6)
                    
                    total_frames = int(round(t * fps))
                    ff = total_frames % int(round(fps))
                    total_sec = total_frames // int(round(fps))
                    ss = total_sec % 60
                    mm = (total_sec // 60) % 60
                    hh = total_sec // 3600
                    text = f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}" if duration >= 3600 else f"{mm:02d}:{ss:02d}:{ff:02d}"
                    
                    painter.setPen(QColor(get_theme_token('texto_gris', '#aaaaaa')))
                    painter.drawText(int(x) + 2, int(mid_y) - 8, text)
                
                num_subs = 4 if fps > 30 or interval != 1.0 else int(round(fps)) if fps <= 10 else 5
                sub_interval = interval / num_subs
                for si in range(1, num_subs):
                    st = t + si * sub_interval
                    if st > duration: continue
                    sub_x = start_x + (st / duration) * span
                    painter.setPen(QPen(QColor(get_theme_token('onda_cuadricula_fuerte', '#444444')), 1))
                    painter.drawLine(int(sub_x), int(mid_y), int(sub_x), int(mid_y) - 3)
                
                t += interval
        else:
            num_bars = len(peaks_to_draw)
            if num_bars > 0:
                # Calcular ancho de barra y espaciado basándose STRICTAMENTE en la cantidad real de picos a dibujar
                step = span / (num_bars - 1) if num_bars > 1 else span
                bar_width = max(1, min(int(step * 0.6), 8))
        
                # Configurar pincel para las barras
                pen = QPen()
                pen.setWidth(bar_width)
                pen.setCapStyle(Qt.RoundCap)
        
                # Para que QPainter con Antialiasing no difumine las líneas, debemos alinearlas
                # a los centros de los píxeles (offset=0.5) si el grosor es impar.
                offset = 0.5 if bar_width % 2 != 0 else 0.0
        
                # 2. Dibujar las barras de amplitudes
                for i, peak in enumerate(peaks_to_draw):
                    x = start_x + i * step
                    if x >= width:
                        break
        
                    wave_h = peak * (height - 14)
                    wave_h = max(2, wave_h)
        
                    # Color según si ya fue reproducido o no
                    col = QColor(acento)
                    if self.is_loading:
                        # Efecto shimmer/glimmer en la transparencia durante la carga
                        alpha = int(100 + 50 * math.sin(self.loading_phase + i * 0.15))
                        col.setAlpha(max(20, min(alpha, 255)))
                        pen.setColor(col)
                    elif x <= playhead_x:
                        # Ya reproducido: color acento brillante
                        pen.setColor(col)
                    else:
                        # No reproducido: semi-transparente
                        col.setAlpha(60)
                        pen.setColor(col)
        
                    painter.setPen(pen)
                    x_coord = int(x) + offset
                    from PySide6.QtCore import QPointF
                    painter.drawLine(QPointF(x_coord, mid_y - wave_h / 2), QPointF(x_coord, mid_y + wave_h / 2))

        # 3. Dibujar cabezal de reproducción (línea vertical roja)
        if (self.audio_path or self.peaks or getattr(self, "is_video_only", False)) and not self.is_loading:
            pen_head = QPen(QColor("#ff6c6b"), 2)
            painter.setPen(pen_head)
            painter.drawLine(int(playhead_x), 4, int(playhead_x), height - 4)

    def mousePressEvent(self, event):
        """Permite hacer click en la onda para buscar posiciones (seeking) o iniciar selección (clic derecho).
        Si el clic izquierdo cae dentro de una selección rápida (lite subclip) ya existente, además
        se arma como un posible inicio de arrastre nativo (ver mouseMoveEvent)."""
        x = event.position().x()
        start_x = 10
        end_x = self.width() - 10
        span = end_x - start_x
        if span > 0:
            ratio = (x - start_x) / span
            ratio = max(0.0, min(ratio, 1.0))

            if event.button() == Qt.LeftButton:
                self._drag_press_pos = event.position()
                self._pending_subclip_drag = self._is_ratio_inside_lite_selection(ratio)
                self._armed_for_editor_send = False
                self.seek_requested.emit(ratio)
                self.set_playback_ratio(ratio)
            elif event.button() == Qt.RightButton:
                self._lite_start_ratio = ratio
                self._lite_end_ratio = ratio
                self.update()

    def mouseMoveEvent(self, event):
        """Permite arrastrar el cabezal de reproducción (scrubbing) o la selección (clic derecho) a través de la
        onda. Si el clic izquierdo comenzó dentro de la selección rápida y el mouse se mueve más allá del umbral
        de arrastre de Qt, se interpreta como intención de arrastrar el subclip. Con un editor conectado no se
        dispara nada todavía (se espera a mouseReleaseEvent); sin editor conectado se arma el arrastre nativo
        del SO del medio completo de inmediato, ya que ese mecanismo exige iniciarse con el botón aún presionado."""
        if event.buttons() & Qt.LeftButton and getattr(self, "_pending_subclip_drag", False):
            from PySide6.QtWidgets import QApplication
            if (event.position() - self._drag_press_pos).manhattanLength() >= QApplication.startDragDistance():
                self._pending_subclip_drag = False
                from core.services.editor_integration_manager import EditorIntegrationManager
                editor_mgr = EditorIntegrationManager.get_instance()
                if editor_mgr and editor_mgr.active_editor:
                    self._armed_for_editor_send = True
                else:
                    self.subclip_drag_started.emit()
            return

        x = event.position().x()
        start_x = 10
        end_x = self.width() - 10
        span = end_x - start_x
        if span > 0:
            ratio = (x - start_x) / span
            ratio = max(0.0, min(ratio, 1.0))

            if event.buttons() & Qt.LeftButton:
                self.seek_requested.emit(ratio)
                self.set_playback_ratio(ratio)
            elif event.buttons() & Qt.RightButton:
                self._lite_end_ratio = ratio
                self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """Finaliza la selección o la limpia si fue solo un clic."""
        if event.button() == Qt.RightButton:
            if self._lite_start_ratio is not None and self._lite_end_ratio is not None:
                if abs(self._lite_start_ratio - self._lite_end_ratio) < 0.005:
                    self.clear_lite_selection()
            in_ratio, out_ratio = self.get_lite_selection()
            self.lite_selection_changed.emit(-1.0 if in_ratio is None else in_ratio,
                                             -1.0 if out_ratio is None else out_ratio)
        elif event.button() == Qt.LeftButton:
            self._pending_subclip_drag = False
            if getattr(self, "_armed_for_editor_send", False):
                self._armed_for_editor_send = False
                self.subclip_send_requested.emit()
        super().mouseReleaseEvent(event)
