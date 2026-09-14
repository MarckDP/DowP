# src/gui/widgets/model_download_prompt.py
"""Descarga de modelos de IA desde el mismo sitio donde el usuario los elige.

Hasta ahora los modelos solo se podían bajar desde Ajustes > Modelos: el popover de
Reescalar/Eliminar Fondo detectaba que faltaba el modelo y lo único que hacía era
mandar al usuario a otra pantalla ("ve a Ajustes > Modelos"), perdiendo la selección
a medio hacer. Este módulo junta las tres piezas que hacen falta para resolverlo ahí
mismo, sin importar en qué parte de la app esté:

  - `confirm_model_download()`: el diálogo "esto pesa X, ¿lo descargo?" con dos
    salidas, Descargar y Cancelar. Nada se baja sin pasar por aquí -- mismo criterio
    que el resto de la app con los modelos (a diferencia de las dependencias, que sí
    se bajan solas al arrancar, ver core/setup/ffmpeg_setup.py).
  - `ModelDownloadWorker`: la descarga en un QThread, para que la UI siga viva. El
    worker no depende del popover que lo lanzó: si el usuario cierra el popover o se
    va a otra pestaña, la descarga sigue.
  - `ModelStatusRow`: la línea de estado (icono + texto) que dice si el modelo está
    o no, y que durante la descarga muestra el porcentaje.

Los iconos salen de assets/icons/svg (teñidos con el token de color que toque), NO
de emojis: un emoji se ve distinto en cada SO -- o directamente no se ve -- y no
respeta el color del tema.
"""
from PySide6.QtCore import QThread, Signal, Qt, QCoreApplication, QTimer
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QMessageBox, QPushButton

from core.logger.logger_manager import logger
from core.utils.cache_manager import format_bytes, format_bytes_compact
from gui.styles import get_theme_token, set_button_variant
from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon

_ICON_SIZE = 14

# Máximo de refrescos por segundo del porcentaje. Dos son de sobra para que se lea
# como algo vivo, y ponen un techo al trabajo que la descarga le genera a la UI:
# repintar un QLabel obliga a recalcular el layout del popover entero (el ancho de
# la fila de estado cambia con el texto), así que el coste no es el del texto en sí.
PROGRESS_REFRESH_MS = 500


def _tr(text: str) -> str:
    return QCoreApplication.translate("ModelDownloadPrompt", text)


def format_model_label(name: str, size_bytes: int) -> str:
    """Nombre de un modelo/motor con su peso pegado: "General (Estándar)
    (928 MB)". El peso sale siempre de "size_bytes" (core/constants.py), nunca
    escrito a mano dentro del nombre -- así no puede quedar desactualizado respecto
    del archivo que se baja de verdad.

    Sin peso conocido (modelos importados a mano, que ya están en disco y no se
    descargan) devuelve el nombre pelado, sin paréntesis vacíos."""
    compact = format_bytes_compact(size_bytes)
    return f"{name} ({compact})" if compact else name


def open_models_settings(widget) -> bool:
    """Abre Ajustes > Modelos desde donde sea que esté `widget`, subiendo hasta
    la ventana principal para pedirle su overlay de ajustes. Devuelve False si no
    lo encuentra (widget suelto en un test, o la ventana todavía sin construir),
    para que quien llame pueda avisar en vez de fallar en silencio.

    El import va adentro a propósito: settings_view importa models_page, que importa
    este módulo -- a nivel de módulo sería un ciclo."""
    from gui.tabs.settings.settings_view import SETTINGS_PAGE_MODELS

    overlay = getattr(widget.window(), "settings_overlay", None)
    if overlay is None:
        logger.warning("Modelos IA: no se encontró el overlay de Ajustes para abrir la página de Modelos.")
        return False
    overlay.open_page(SETTINGS_PAGE_MODELS)
    return True


class ModelActionsRow(QWidget):
    """Las dos acciones que un popover de IA ofrece sobre el modelo elegido:
    borrarlo del disco y saltar a la gestión completa en Ajustes > Modelos.

    Vive aquí y no en cada popover porque los dos (Reescalar y Eliminar Fondo)
    necesitan exactamente lo mismo; lo único que cambia es QUÉ se borra, y de eso se
    encarga quien conecta `delete_requested`."""
    delete_requested = Signal()
    manage_requested = Signal()

    def __init__(self, parent=None, delete_tooltip: str = ""):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Sin setFixedHeight: el QSS del tema ya le da a QPushButton un min-height
        # propio (32 px con la tipografía por defecto), y fijar un máximo más bajo
        # deja al botón con mínimo > máximo -- Qt lo dibuja con el alto del estilo
        # dentro del hueco más chico del layout y se le corta el borde de abajo.
        # Dejándolo libre, estos botones miden lo mismo que los del resto de la app.
        self.btn_delete = QPushButton(QCoreApplication.translate("ModelDownloadPrompt", "Eliminar"))
        self.btn_delete.setCursor(Qt.PointingHandCursor)
        set_button_variant(self.btn_delete, "danger")
        if delete_tooltip:
            self.btn_delete.setToolTip(delete_tooltip)
        self.btn_delete.clicked.connect(self.delete_requested.emit)
        layout.addWidget(self.btn_delete, 1)

        self.btn_manage = QPushButton(QCoreApplication.translate("ModelDownloadPrompt", "Administrar"))
        self.btn_manage.setCursor(Qt.PointingHandCursor)
        set_button_variant(self.btn_manage, "secondary")
        self.btn_manage.setToolTip(QCoreApplication.translate("ModelDownloadPrompt", "Abrir Ajustes > Modelos para descargar, reinstalar o importar modelos"))
        self.btn_manage.clicked.connect(self.manage_requested.emit)
        layout.addWidget(self.btn_manage, 1)

    def set_delete_enabled(self, enabled: bool):
        """Solo se puede borrar lo que está en disco -- con el placeholder
        elegido, un modelo sin descargar o una descarga en curso, el botón queda
        apagado en vez de fallar al pulsarlo."""
        self.btn_delete.setEnabled(enabled)


class ModelDownloadWorker(QThread):
    """Descarga un modelo/motor sin bloquear la UI. `row_id` viaja en ambas señales
    para que varias descargas puedan convivir sin cruzar su progreso (Ajustes >
    Modelos tiene una fila por modelo; los popovers, una descarga por motor/modelo
    elegido)."""
    finished_signal = Signal(bool, str, str)    # success, message, row_id
    numeric_progress_signal = Signal(int, str)  # percent, row_id

    def __init__(self, row_id: str, download_func, info: dict, parent=None):
        super().__init__(parent)
        self.row_id = row_id
        self.download_func = download_func
        self.info = info

    def run(self):
        try:
            # El callback de descarga se llama una vez por chunk de 8 KB, así que un
            # modelo de ~930 MB lo llama unas 119.000 veces -- pero solo hay 101
            # valores enteros posibles. Sin este filtro se emiten 119.000 señales
            # entre hilos, cada una despertando al hilo de la UI para repintar lo
            # mismo. Se filtra aquí, en el hilo de la descarga, que es donde sale
            # barato: comparar dos enteros.
            last = -1

            def cb(pct):
                nonlocal last
                if pct != last:
                    last = pct
                    self.numeric_progress_signal.emit(pct, self.row_id)

            success, msg = self.download_func(self.info, progress_callback=cb)
            self.finished_signal.emit(success, msg, self.row_id)
        except Exception as e:
            logger.error(f"ModelDownloadWorker: Error descargando '{self.row_id}': {e}")
            self.finished_signal.emit(False, str(e), self.row_id)


def confirm_model_download(parent, display_name: str, size_bytes: int,
                           subject: str = "", extra_note: str = "") -> bool:
    """Pregunta antes de bajar, mostrando el peso real (ver "size_bytes" en
    core/constants.py). Devuelve True solo si el usuario apretó Descargar --
    cerrar el diálogo con Escape o la X cuenta como Cancelar.

    `subject` es cómo llamar a lo que se baja en el título/texto ("modelo",
    "motor"); `extra_note` permite sumar una aclaración propia de quien pregunta
    (ej. que el motor de upscaling trae sus modelos adentro)."""
    subject = subject or QCoreApplication.translate("ModelDownloadPrompt", "modelo")
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Question)
    box.setWindowTitle(QCoreApplication.translate("ModelDownloadPrompt", "Descargar {0}").format(subject))
    box.setText(QCoreApplication.translate("ModelDownloadPrompt", "'{0}' no está descargado todavía.").format(display_name))

    if size_bytes > 0:
        note = QCoreApplication.translate("ModelDownloadPrompt", "Tamaño de la descarga: {0}").format(format_bytes(size_bytes))
    else:
        note = QCoreApplication.translate("ModelDownloadPrompt", "No se pudo calcular el tamaño de la descarga por adelantado.")
    note += QCoreApplication.translate("ModelDownloadPrompt", "\nSe guarda una sola vez: la próxima vez ya estará listo para usar.")
    if extra_note:
        note += "\n\n" + extra_note
    box.setInformativeText(note)

    btn_download = box.addButton(QCoreApplication.translate("ModelDownloadPrompt", "Descargar"), QMessageBox.AcceptRole)
    box.addButton(QCoreApplication.translate("ModelDownloadPrompt", "Cancelar"), QMessageBox.RejectRole)
    box.setDefaultButton(btn_download)
    box.exec()
    return box.clickedButton() is btn_download


class ModelStatusRow(QWidget):
    """Línea de estado de un modelo: icono SVG teñido + texto, en una sola fila.

    Es la "zona donde avisa si existe o no el modelo" de los popovers del Editor de
    Imagen, y también la que muestra el avance mientras se descarga -- un porcentaje
    plano de 0 a 100%, sin barra: el popover es angosto y una barra ahí obliga a
    recalcular su alto en mitad de la descarga.

    Los mensajes que mandan al usuario a otro sitio ("ve a Ajustes > Modelos") se
    pintan como enlace y emiten `clicked` al pulsarlos: si el texto dice a dónde ir,
    lo mínimo es llevarlo ahí en vez de obligarlo a buscarlo a mano."""
    clicked = Signal()

    def __init__(self, parent=None, font_size: int = 11):
        super().__init__(parent)
        self._font_size = font_size
        self._clickable = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.lbl_icon = QLabel()
        self.lbl_icon.setFixedSize(_ICON_SIZE, _ICON_SIZE)
        self.lbl_icon.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        layout.addWidget(self.lbl_icon, 0, Qt.AlignTop)

        self.lbl_text = QLabel()
        self.lbl_text.setWordWrap(True)
        layout.addWidget(self.lbl_text, 1)

        # El texto se parte en varias líneas según el ancho, así que el alto de esta
        # fila depende del ancho. QWidget no propaga eso solo: QWidgetItem mira
        # sizePolicy().hasHeightForWidth() del widget, no el del layout de adentro,
        # así que sin esta línea el layout de arriba cree que la fila mide siempre
        # una línea y el popover corta la segunda (ver PopoverTriggerButton.reposition,
        # que es quien pregunta el alto).
        policy = self.sizePolicy()
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

        # Limitador del porcentaje a PROGRESS_REFRESH_MS (ver show_progress): el
        # primer valor se pinta al instante y a partir de ahí manda el temporizador.
        self._pending_pct = None
        self._painted_pct = None
        self._progress_timer = QTimer(self)
        self._progress_timer.setSingleShot(True)
        self._progress_timer.setInterval(PROGRESS_REFRESH_MS)
        self._progress_timer.timeout.connect(self._flush_progress)

        self.setVisible(False)

    def _set(self, icon_name: str, token: str, fallback: str, text: str, clickable: bool = False):
        color = get_theme_token(token, fallback)
        icon = get_colored_svg_icon(icon_name, color, size=_ICON_SIZE)
        self.lbl_icon.setPixmap(icon.pixmap(_ICON_SIZE, _ICON_SIZE))
        self.lbl_text.setText(text)
        decoration = "text-decoration: underline;" if clickable else ""
        self.lbl_text.setStyleSheet(f"color: {color}; font-size: {self._font_size}px; {decoration}")
        self._clickable = clickable
        self.setCursor(Qt.PointingHandCursor if clickable else Qt.ArrowCursor)
        self.setVisible(True)

    def mouseReleaseEvent(self, event):
        if self._clickable and event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def show_ready(self, text: str):
        self._stop_progress()
        self._set("check_circle.svg", "estado_exito", "#40d66b", text)

    def show_missing(self, text: str):
        self._stop_progress()
        self._set("download.svg", "estado_aviso", "#d8c94a", text)

    def show_locked(self, text: str, clickable: bool = False):
        """Modelos que necesitan cuenta/login externo (ver is_rembg_model_gated) --
        no hay descarga automática que ofrecer, así que el mensaje lleva al único
        sitio donde se pueden instalar a mano."""
        self._stop_progress()
        self._set("login.svg", "estado_aviso", "#d8c94a", text, clickable=clickable)

    def show_progress(self, pct: int):
        """Porcentaje de la descarga, repintado como mucho 1000/PROGRESS_REFRESH_MS
        veces por segundo. El valor recibido siempre se guarda; lo que se limita es
        cuántas veces se toca la pantalla, así que ningún avance se "pierde": el
        temporalizador pinta el último valor recibido en cuanto le toca.

        El primer valor de una descarga se pinta de inmediato (si no, el usuario
        acepta el diálogo y la fila se queda muda medio segundo, que se lee como que
        no arrancó)."""
        self._pending_pct = max(0, min(100, int(pct)))
        if self._progress_timer.isActive():
            return
        self._paint_progress()
        self._progress_timer.start()

    def _flush_progress(self):
        """Fin de ventana: si entretanto llegó un valor nuevo, se pinta y se
        abre otra ventana. Si no llegó nada, el limitador queda en reposo para que la
        siguiente actualización se vea al instante en vez de esperar su turno."""
        if self._pending_pct is not None and self._pending_pct != self._painted_pct:
            self._paint_progress()
            self._progress_timer.start()

    def _paint_progress(self):
        self._painted_pct = self._pending_pct
        self._set("download.svg", "estado_progreso", "#3498db",
                  QCoreApplication.translate("ModelDownloadPrompt", "Descargando... {0}%").format(self._painted_pct))

    def _stop_progress(self):
        """Corta el limitador al pasar a cualquier otro estado -- si no, un
        refresco pendiente puede pisar un "Modelo listo" con un "Descargando... 99%"
        medio segundo después de que la descarga ya terminó."""
        self._progress_timer.stop()
        self._pending_pct = None
        self._painted_pct = None

    def show_error(self, text: str):
        self._stop_progress()
        self._set("error.svg", "estado_error", "#ff6b5f", text)

    def clear(self):
        self._stop_progress()
        self.setVisible(False)
