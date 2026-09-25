# src/gui/tabs/video_tools/presets_panel.py
import os

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QFileDialog, QFrame
from PySide6.QtCore import Qt

from gui.styles import get_theme_token
from gui.widgets.mode_selector import ModeSelector
from gui.widgets.preset_bar import PresetBar
from gui.tabs.video_tools.advanced_recode_panel import _PRESET_NAMESPACE
from gui.tabs.video_tools.upscale_ia_panel import _PRESET_NAMESPACE as _UPSCALE_PRESET_NAMESPACE
from core.utils.preset_manager import IA_TOOL_FUNCTIONS, ia_tools_fit, recode_preset_fits
from core.utils.watermark_builder import check_watermark_file
from core.utils.recode_guard import normalize_container

# Modos del selector de arriba, en el orden de sus botones (mismas etiquetas que el
# ModeSelector de Proceso Avanzado). Es el mismo valor que guarda cada preajuste de
# Recodificación en "stream_mode", y el motor ya lo respeta (QueueWorker._execute_recode).
_STREAM_MODES = ("video+audio", "audio_only", "video_only")
# Contenedor de audio según el códec, para "Solo Audio" con un preajuste que conserva el
# contenedor del original (container "same", ej. Normalizar Audio) y un original de video.
_AUDIO_CONTAINER_BY_CODEC = {"aac": "m4a", "mp3": "mp3", "flac": "flac", "opus": "opus"}
_AUDIO_CONTAINERS = {"m4a", "mp3", "flac", "opus", "ogg", "wav", "aac", "wma"}


class PresetsPanel(QWidget):
    """
    Pestaña 'Preajustes' de Herramientas Multimedia.

    Aquí el usuario ELIGE qué preset(s) usar para el próximo trabajo, sin
    pasar por la pestaña que los creó (ej. guardaste "422 Proxy" en Avanzado
    una vez; de ahí en más solo entras aquí, lo eliges, y presionas "Iniciar"
    directo). Dos secciones independientes -- Recodificación (la de siempre) y
    "Herramientas IA" (namespace compartido "video_tools/ia_tools", agrupado
    por función adentro -- ver core.utils.preset_manager.IA_TOOL_FUNCTIONS;
    hoy solo Reescalado, pensada para sumar más funciones de IA sin agregar
    tarjeta nueva -- ver upscale_ia_panel.py, que ahora solo guarda, el picker
    vive acá) -- **combinables**: elegir solo una corre solo ese proceso;
    elegir las dos encadena los dos (Reescalado IA primero,
    Recodificación después -- ver video_tools_view.py::_start_chained_jobs).
    Por eso expone get_settings()/is_valid() con la misma forma que
    AdvancedRecodePanel para el caso "solo Recodificación" (compatibilidad
    con el contrato genérico de EncodingOptionsWidget), más
    get_upscale_settings()/get_recode_settings() por separado para que
    video_tools_view.py pueda detectar la combinación.

    Selector "Video + Audio / Solo Audio / Solo Video" arriba de todo (como en el
    DowP original y en Proceso Avanzado): filtra las dos listas a lo que tiene sentido
    en ese modo (ver recode_preset_fits; en Solo Audio no hay Herramientas IA, que
    necesitan video) y, al lanzar, fuerza ese modo sobre el preajuste elegido sin
    tocar el guardado (ver get_recode_settings/get_upscale_settings). Así nunca se
    combina, por ejemplo, un Mapa de Normales con "Convertir a MP3".

    Cada preajuste de Recodificación puede pedir container="same" (ver
    core.utils.default_presets, ej. los de normalizar audio: no tiene sentido
    forzar un contenedor fijo si solo se está tocando el audio) - se resuelve
    aquí por archivo, igual que ya hacía compress_panel.py en Manual ("Mismo
    que el original"), porque get_recode_settings() recibe meta_override/
    filepath_override por archivo cuando video_tools_view.py arma el lote
    (ver needs_per_file_recompute).
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings_override = {}
        self._source_meta = None
        self._source_filepath = None
        self._warning_text = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Etiquetas por defecto del ModeSelector (Video + Audio / Solo Audio / Solo
        # Video); el modo se resuelve por posición (ver stream_mode), no por el texto.
        self.mode_selector = ModeSelector(self)
        self.mode_selector.mode_changed.connect(self._on_stream_mode_changed)
        layout.addWidget(self.mode_selector)

        frame_recode, rv = self._card_frame(self.tr("Preajustes de Recodificación"))
        # Un solo combo, agrupado por función adentro (ver PresetBar.refresh) - nada de
        # un filtro aparte más el picker (ver conversación).
        self.preset_bar_recode = PresetBar(
            _PRESET_NAMESPACE, get_settings=None, parent=frame_recode,
            show_picker=True, show_save_button=False,
        )
        rv.addWidget(self.preset_bar_recode)
        layout.addWidget(frame_recode)

        frame_upscale, uv = self._card_frame(self.tr("Preajustes de Herramientas IA"))
        self.preset_bar_upscale = PresetBar(
            _UPSCALE_PRESET_NAMESPACE, get_settings=None, parent=frame_upscale,
            show_picker=True, show_save_button=False,
            function_choices=IA_TOOL_FUNCTIONS,
        )
        uv.addWidget(self.preset_bar_upscale)
        layout.addWidget(frame_upscale)
        self.frame_upscale = frame_upscale

        # Aviso "la marca de agua de este preajuste ya no existe" + reparación puntual
        # (ver conversación): solo corrige la corrida actual, no reescribe el preajuste
        # guardado en disco. Solo aplica al preajuste de Recodificación (el único con
        # marca de agua).
        self.warning_container = QWidget(self)
        warn_layout = QVBoxLayout(self.warning_container)
        warn_layout.setContentsMargins(0, 0, 0, 0)
        warn_layout.setSpacing(6)
        self.lbl_watermark_warning = QLabel("", self.warning_container)
        self.lbl_watermark_warning.setWordWrap(True)
        warning_color = get_theme_token("estado_error", "#e06c75")
        self.lbl_watermark_warning.setStyleSheet(f"color: {warning_color}; font-weight: bold;")
        warn_layout.addWidget(self.lbl_watermark_warning)
        self.btn_fix_watermark = QPushButton(self.tr("Seleccionar otra imagen…"), self.warning_container)
        self.btn_fix_watermark.setObjectName("secondaryButton")
        self.btn_fix_watermark.setCursor(Qt.PointingHandCursor)
        self.btn_fix_watermark.clicked.connect(self._on_fix_watermark_clicked)
        warn_layout.addWidget(self.btn_fix_watermark)
        self.warning_container.setVisible(False)
        layout.addWidget(self.warning_container)

        layout.addStretch(1)

        self.preset_bar_recode.preset_applied.connect(self._on_recode_preset_applied)
        self.preset_bar_upscale.preset_applied.connect(self._on_upscale_preset_applied)
        self._apply_stream_mode()

    def stream_mode(self) -> str:
        for i, btn in enumerate(self.mode_selector.buttons):
            if btn.isChecked():
                return _STREAM_MODES[i]
        return _STREAM_MODES[0]

    def _on_stream_mode_changed(self, *_args):
        self._apply_stream_mode()
        # Reemite el estado aunque ningún preajuste haya cambiado: el texto del botón
        # "Iniciar" depende del modo (ver get_status).
        self.preset_bar_recode.preset_applied.emit(self.preset_bar_recode.active_preset_name() or "")

    def _apply_stream_mode(self):
        mode = self.stream_mode()
        self.preset_bar_recode.set_filter(lambda settings: recode_preset_fits(settings, mode))
        # Las Herramientas IA siempre producen video: en Solo Audio se ocultan (y su
        # preajuste elegido deja de contar, ver get_upscale_settings).
        self.frame_upscale.setVisible(ia_tools_fit(mode))

    def _card_frame(self, title: str):
        frame = QFrame(self)
        frame.setObjectName("advancedCard")
        border_color = get_theme_token('borde_sutil', '#2d2d2d')
        frame.setStyleSheet(f"""
            QFrame#advancedCard {{
                background-color: transparent;
                border: 1px solid {border_color};
                border-radius: 6px;
            }}
        """)
        v = QVBoxLayout(frame)
        v.setContentsMargins(12, 10, 12, 12)
        v.setSpacing(8)
        lbl = QLabel(title, frame)
        lbl.setObjectName("sectionTitle")
        lbl.setAlignment(Qt.AlignCenter)
        v.addWidget(lbl)
        return frame, v

    def _on_recode_preset_applied(self, _name: str):
        self._settings_override = {}
        self._refresh_watermark_warning()

    def _on_upscale_preset_applied(self, _name: str):
        # El de Reescalado IA no tiene marca de agua ni "settings_override" -- solo
        # hace falta reemitir el estado (válido/inválido, texto del botón "Iniciar").
        self._refresh_watermark_warning()

    def _refresh_watermark_warning(self):
        merged = dict(self.preset_bar_recode.current_preset_settings() or {})
        merged.update(self._settings_override)
        self._warning_text = check_watermark_file(merged)
        if self._warning_text:
            self.lbl_watermark_warning.setText(f"⚠ {self._warning_text}")
        self.warning_container.setVisible(bool(self._warning_text))

    def _on_fix_watermark_clicked(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Seleccionar imagen de marca de agua"), "",
            self.tr("Imágenes (*.png *.jpg *.jpeg *.webp *.bmp);;Todos los archivos (*.*)"),
        )
        if not file_path:
            return
        # Solo corrige la corrida actual — el preajuste guardado en disco no se toca.
        self._settings_override["watermark_image_path"] = file_path
        self._refresh_watermark_warning()
        # Reutiliza la señal que EncodingOptionsWidget ya escucha para refrescar el botón
        # "Iniciar" — ver preset_bar.py / encoding_options_widget.py.
        self.preset_bar_recode.preset_applied.emit(self.preset_bar_recode.active_preset_name() or "")

    def set_source_media(self, meta: dict, filepath: str):
        self._source_meta = meta or None
        self._source_filepath = filepath

    def get_upscale_settings(self) -> dict | None:
        """Ajustes del preajuste de Herramientas IA elegido, o None si el combo
        está en "Sin preset" o el modo es Solo Audio. Elegirlo del combo NO empuja
        valores a ningún control (mismo criterio que el resto de la app) -- este es
        el único lugar de donde leerlo. En Solo Video, sale sin audio."""
        mode = self.stream_mode()
        if mode == "audio_only":
            return None
        preset = self.preset_bar_upscale.current_preset_settings()
        if preset is None:
            return None
        settings = dict(preset)
        if mode == "video_only":
            settings["keep_audio"] = False
        return settings

    def get_recode_settings(self, meta_override: dict | None = None, filepath_override: str | None = None) -> dict | None:
        """Ajustes del preajuste de Recodificación elegido, o None si el
        combo está en "Sin preset" -- a diferencia de get_settings() (abajo),
        que existe solo por compatibilidad con el contrato genérico de
        EncodingOptionsWidget y nunca devuelve None."""
        preset = self.preset_bar_recode.current_preset_settings()
        if preset is None:
            return None
        settings = dict(preset)
        settings.update(self._settings_override)
        # El modo del selector manda sobre el del preajuste (la lista ya solo ofrece
        # preajustes compatibles, ver recode_preset_fits). Video + Audio no fuerza nada:
        # respeta lo que el preajuste decida (ej. un GIF, que nunca lleva audio).
        mode = self.stream_mode()
        if mode != "video+audio":
            settings["stream_mode"] = mode
        if settings.get("container") == "same":
            filepath = filepath_override if filepath_override is not None else self._source_filepath
            resolved = None
            if filepath:
                ext = os.path.splitext(filepath)[1]
                resolved = normalize_container(ext) if ext else None
            if settings.get("stream_mode") == "audio_only" and resolved not in _AUDIO_CONTAINERS:
                # Solo el audio de un video: no en su contenedor de video.
                resolved = _AUDIO_CONTAINER_BY_CODEC.get(settings.get("audio_codec"), "m4a")
            settings["container"] = resolved or ("m4a" if settings.get("stream_mode") == "audio_only" else "mp4")
        return settings

    def get_settings(self, meta_override: dict | None = None, filepath_override: str | None = None) -> dict:
        """Alias de get_recode_settings() para el contrato genérico de
        EncodingOptionsWidget (get_encoding_settings()) -- usado por
        video_tools_view.py solo en el caso "solo preajuste de
        Recodificación" (sin Reescalado IA elegido), que sigue el mismo loop
        de siempre sin cambios. Los casos "solo Reescalado IA" y "los dos
        combinados" se detectan ANTES, vía get_upscale_settings(), y nunca
        llegan a llamar esto -- ver _on_start_recoding_clicked."""
        return self.get_recode_settings(meta_override, filepath_override) or {}

    def is_valid(self) -> bool:
        return self.get_status()[0]

    def get_status(self) -> tuple[bool, str]:
        has_recode = self.preset_bar_recode.active_preset_name() is not None
        has_upscale = (self.preset_bar_upscale.active_preset_name() is not None
                       and self.stream_mode() != "audio_only")
        if not has_recode and not has_upscale:
            return False, self.tr("Selecciona al menos un preajuste")
        if has_recode and self._warning_text:
            return False, self.tr("Resuelve el aviso de la marca de agua")
        if has_upscale and not has_recode:
            # El mismo combo de IA trae preajustes de Reescalado y de los mapas
            # (ver upscale_ia_panel.ia_function_of).
            from gui.tabs.video_tools.upscale_ia_panel import FUNCTION_DEPTH, FUNCTION_NORMALS, ia_function_of
            function = ia_function_of(self.get_upscale_settings())
            if function == FUNCTION_DEPTH:
                return True, self.tr("Iniciar Mapa de Profundidad")
            if function == FUNCTION_NORMALS:
                return True, self.tr("Iniciar Mapa de Normales")
            return True, self.tr("Iniciar Reescalado")
        return True, self.tr("Iniciar Recodificación")
