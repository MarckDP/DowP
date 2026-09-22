# src/gui/tabs/image_tools/upscale_popover.py
from PySide6.QtCore import QCoreApplication
"""Contenido del popover "Reescalar IA" del Editor de Imagen: elegir motor (Waifu2x/
SRMD/Upscayl) y sus parámetros -- misma cascada y mismos controles que usaba DowP 1
(image_tools_tab.pyc, upscale_options_frame, líneas 854-900 y 1298-1410): Motor,
Modelo, Escala, Tile Size, Potencia (concurrencia), Reducir Ruido (oculto para
Upscayl, relabeled "Nivel Ruido/Blur" para SRMD) y TTA.

Escala y Reducir Ruido ya NO son listas fijas heredadas de DowP 1 (un 2x/3x/4x y un
-1..3 iguales para los tres motores): cada binario acepta un juego distinto de
valores, así que las dos listas se repueblan según el motor -- y, en Waifu2x, según
el modelo -- desde las tablas de core/constants.py, que salieron de correr los
propios ejecutables. Aquello dejaba escalas afuera (Upscayl llega a 16x, Waifu2x a
32x) y a la vez ofrecía un 3x que Waifu2x rechaza con "invalid scale argument".

DowP 1 no tiene ningún toggle de GPU/CPU para reescalado -- los 3 motores son
binarios NCNN-Vulkan, siempre por GPU (sin modo CPU). "Potencia" es lo más parecido
(concurrencia de hilos/carga GPU, no un on/off de hardware).

Los motores se pueden descargar desde aquí mismo: elegir uno que no esté instalado
abre el diálogo de confirmación con su peso real (ver confirm_model_download en
gui/widgets/model_download_prompt.py) y, si se acepta, la descarga corre en segundo
plano mostrando el porcentaje en la línea de estado de abajo. Ya no hace falta ir a
Ajustes > Modelos y volver -- la selección a medio hacer no se pierde.

Ojo con la unidad de descarga: en reescalado lo que se baja es el MOTOR completo
(binario + sus modelos, todo en el mismo zip), no un modelo suelto como en Eliminar
Fondo -- por eso el diálogo aparece al elegir el motor, y también al elegir un modelo
si su motor todavía falta.

Solo selección: no dispara ningún reescalado todavía, eso se conecta en un paso
aparte."""
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QCheckBox, QMessageBox,
)
from PySide6.QtCore import Signal, Qt, QTimer
from PySide6.QtGui import QFontMetrics

from gui.styles import get_theme_token
from gui.widgets.combo_box import AutoPopupComboBox
from gui.widgets.model_download_prompt import (
    ModelActionsRow, ModelStatusRow, confirm_model_download, model_download_key, model_downloads,
    format_model_label, open_models_settings,
)
from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon
from core.constants import (
    UPSCALING_TOOLS, WAIFU2X_MODELS, SRMD_MODELS, UPSCAYL_MODELS_MAP,
    UPSCAYL_SCALES, SRMD_SCALES, WAIFU2X_DENOISE_LEVELS, SRMD_DENOISE_LEVELS,
    AI_ENGINE_HOLDER, AI_MODEL_HOLDER,
)
from core.setup.models_setup import (
    is_upscaling_engine_installed, get_upscaling_engine_size_bytes, download_upscaling_engine,
    delete_upscaling_engine,
)

_TILE_TOOLTIP = QCoreApplication.translate(
    "UpscalePopoverContent",
    "Tamaño del bloque de procesamiento (VRAM).\n"
    "0 = Automático (Recomendado).\n"
    "Prueba 128 o 256 si tienes errores de GPU."
)
_POWER_TOOLTIP = QCoreApplication.translate(
    "UpscalePopoverContent",
    "Control de hilos (concurrencia).\n"
    "'Seguro' evita crashes en GPUs modestas.\n"
    "'Máximo' usa toda la potencia pero puede colgar el PC."
)
_SCALE_TOOLTIP = QCoreApplication.translate(
    "UpscalePopoverContent",
    "Cuánto se agranda la imagen.\n"
    "La lista cambia según el motor y el modelo: cada binario acepta\n"
    "un juego distinto de escalas y aquí solo se ofrecen las que ese\n"
    "motor soporta de verdad."
)

# Escalas mientras no hay motor elegido -- se reemplazan en cuanto se elige uno
# (ver _refresh_scale_items). Es lo que los tres motores tienen en común.
_FALLBACK_SCALES = ["2x", "3x", "4x"]


class UpscalePopoverContent(QFrame):
    """selection_changed(engine_key, model_key, is_valid) -- model_key es la clave
    amigable dentro del motor elegido (nombre de familia Waifu2x/SRMD, o nombre de
    archivo crudo de Upscayl tomado de UPSCAYL_MODELS_MAP). is_valid es False
    mientras Motor y/o Modelo sigan en su placeholder."""
    selection_changed = Signal(str, str, bool)
    # Lo emite el botón "Administrar" -- ver RembgPopoverContent.close_popover_requested.
    close_popover_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("upscalePopover")
        bg = get_theme_token('fondo_secundario', '#1e1e1e')
        border = get_theme_token('borde_normal', '#2d2d2d')
        self.setStyleSheet(f"""
            QFrame#upscalePopover {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 8px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        self._label_widgets = []

        title = QLabel(self.tr("Reescalar con IA"))
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(title)

        # Motor
        engine_row = QHBoxLayout()
        engine_row.addWidget(self._label(self.tr("Motor:")))
        self.combo_engine = AutoPopupComboBox(fit_contents=True)
        self.combo_engine.currentIndexChanged.connect(self._on_engine_changed)
        engine_row.addWidget(self.combo_engine, 1)
        layout.addLayout(engine_row)
        self._refresh_engine_items()

        # Modelo
        model_row = QHBoxLayout()
        model_row.addWidget(self._label(self.tr("Modelo:")))
        self.combo_model = AutoPopupComboBox(fit_contents=True)
        self.combo_model.addItem(AI_MODEL_HOLDER, None)
        self.combo_model.currentIndexChanged.connect(self._on_model_changed)
        model_row.addWidget(self.combo_model, 1)
        layout.addLayout(model_row)

        # Escala: la lista sale del motor + modelo elegidos (ver _refresh_scale_items).
        # Antes era un 2x/3x/4x fijo para los tres motores, que además de dejar
        # escalas afuera ofrecía un 3x que Waifu2x rechaza en el acto.
        scale_row = QHBoxLayout()
        scale_row.addWidget(self._label(self.tr("Escala:")))
        self.combo_scale = AutoPopupComboBox(fit_contents=True)
        self.combo_scale.addItems(_FALLBACK_SCALES)
        self.combo_scale.setCurrentText("4x")
        self.combo_scale.setToolTip(_SCALE_TOOLTIP)
        scale_row.addWidget(self.combo_scale)
        scale_row.addStretch()
        scale_row.addWidget(QLabel(self.tr("Tile Size:")))
        self.entry_tile = QLineEdit("0")
        self.entry_tile.setFixedWidth(60)
        self.entry_tile.setToolTip(_TILE_TOOLTIP)
        scale_row.addWidget(self.entry_tile)
        layout.addLayout(scale_row)

        # Potencia (concurrencia)
        power_row = QHBoxLayout()
        power_row.addWidget(self._label(self.tr("Potencia:")))
        self.combo_power = AutoPopupComboBox(fit_contents=True)
        for _pw_label, _pw_key in ((self.tr("Automático"), "Automático"),
                                  (self.tr("Seguro (Estabilidad)"), "Seguro (Estabilidad)"),
                                  (self.tr("Equilibrado"), "Equilibrado"),
                                  (self.tr("Máximo (Potente)"), "Máximo (Potente)")):
            self.combo_power.addItem(_pw_label, _pw_key)
        self.combo_power.setToolTip(_POWER_TOOLTIP)
        power_row.addWidget(self.combo_power, 1)
        layout.addLayout(power_row)

        # Reducir Ruido -- visibilidad/label cambia según el motor (ver _on_engine_changed)
        self.lbl_denoise = self._label(self.tr("Reducir Ruido:"))
        self.combo_denoise = AutoPopupComboBox(fit_contents=True)
        # Los niveles también cambian por motor (ver _refresh_denoise_items):
        # Waifu2x llega hasta 3, SRMD hasta 10.
        self.combo_denoise.addItems(WAIFU2X_DENOISE_LEVELS)
        self.combo_denoise.setCurrentText("2 (Alta)")
        denoise_row_layout = QHBoxLayout()
        denoise_row_layout.addWidget(self.lbl_denoise)
        denoise_row_layout.addWidget(self.combo_denoise, 1)
        layout.addLayout(denoise_row_layout)
        self._denoise_widgets = (self.lbl_denoise, self.combo_denoise)

        # TTA
        self.check_tta = QCheckBox(self.tr("TTA (Mejor calidad, muy lento)"))
        layout.addWidget(self.check_tta)

        # Estado del motor elegido (instalado / no descargado / descargando N%).
        # Las descargas en curso viven en el gestor común (model_downloads()), no en
        # el popover: volver a abrirlo -- o abrir Ajustes > Modelos -- tiene que
        # reencontrar su progreso, no arrancar de cero ni ofrecer descargar algo que
        # ya se está bajando desde otra pantalla. Aquí solo se recuerdan las claves
        # que lanzó ESTE popover: solo quien lanza una descarga avisa si falla.
        self._started_here: set[str] = set()
        model_downloads().started.connect(self._on_download_started)
        model_downloads().progress_changed.connect(self._on_download_progress)
        model_downloads().finished.connect(self._on_download_finished)

        # "Eliminar" borra el MOTOR entero (binario + sus modelos), que es como se
        # instaló -- los modelos de la lista de arriba no existen por separado.
        self.actions_row = ModelActionsRow(
            delete_tooltip=self.tr("Borrar del disco el motor seleccionado, con sus modelos"))
        self.actions_row.delete_requested.connect(self._on_delete_clicked)
        self.actions_row.manage_requested.connect(self._on_manage_clicked)
        layout.addWidget(self.actions_row)

        self.status_row = ModelStatusRow()
        self.status_row.clicked.connect(self._on_manage_clicked)
        layout.addWidget(self.status_row)

        self._set_denoise_visible(False)
        self._resize_label_column()

    def showEvent(self, event):
        """Al reabrir el popover, releer qué motores hay instalados -- puede
        haber cambiado desde Ajustes > Modelos (o desde aquí mismo) mientras estaba
        cerrado."""
        super().showEvent(event)
        self._refresh_engine_items()
        self._update_status()

    def _refresh_engine_items(self):
        """Repuebla el combo de motores conservando la selección actual. El
        estado instalado/no instalado va como icono SVG (y el peso, en el tooltip) en
        vez de un ✓/✗ pegado al nombre: el nombre queda limpio y el icono se tiñe con
        el color del tema, cosa que un emoji no hace."""
        current = self.combo_engine.currentData()
        self.combo_engine.blockSignals(True)
        self.combo_engine.clear()
        self.combo_engine.addItem(AI_ENGINE_HOLDER, None)
        for key, info in UPSCALING_TOOLS.items():
            if is_upscaling_engine_installed(info):
                icon = get_colored_svg_icon(
                    "check_circle.svg", get_theme_token('estado_exito', '#40d66b'), size=14)
                tooltip = self.tr("Instalado")
            else:
                icon = get_colored_svg_icon(
                    "download.svg", get_theme_token('texto_secundario', '#888888'), size=14)
                tooltip = self.tr("No descargado")
            # El peso que se muestra es el del MOTOR completo (binario + sus modelos),
            # que es la unidad que se descarga -- los modelos de la lista de abajo no
            # tienen descarga propia, vienen dentro de ese mismo zip.
            self.combo_engine.addItem(
                icon, format_model_label(info["name"], get_upscaling_engine_size_bytes(info)), key)
            self.combo_engine.setItemData(self.combo_engine.count() - 1, tooltip, Qt.ToolTipRole)
        idx = self.combo_engine.findData(current) if current else -1
        self.combo_engine.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo_engine.blockSignals(False)

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(self.tr(text))
        self._label_widgets.append(lbl)
        return lbl

    def _resize_label_column(self):
        """Ancho de columna calculado según la etiqueta más larga (incluye
        "Nivel Ruido/Blur:", que solo se ve con SRMD) en vez de un fijo arbitrario --
        antes 60px recortaba ese texto contra el combo de al lado, dando la sensación
        de que todo estaba "pegado". Con esto el cuadro directamente se agranda lo
        necesario (reposition() ya recalcula sizeHint() en cada apertura/resize)."""
        fm = QFontMetrics(self.font())
        candidates = [w.text() for w in self._label_widgets] + [self.tr("Nivel Ruido/Blur:")]
        width = max(fm.horizontalAdvance(t) for t in candidates) + 6
        for w in self._label_widgets:
            w.setFixedWidth(width)

    def _current_engine_key(self):
        return self.combo_engine.currentData()

    @staticmethod
    def _download_key(engine_key):
        """Clave del motor en el gestor de descargas -- la misma que usa Ajustes >
        Modelos (ver model_download_key), no el engine_key de este popover."""
        info = UPSCALING_TOOLS.get(engine_key)
        return model_download_key(info) if info else None

    def _is_current_download(self, key: str) -> bool:
        return self._download_key(self._current_engine_key()) == key

    def _set_denoise_visible(self, visible: bool):
        for w in self._denoise_widgets:
            w.setVisible(visible)

    def _add_model_items(self, models: dict):
        """Los modelos de Waifu2x/SRMD llevan sus escalas en el tooltip, no pegadas
        al nombre: la lista completa ("1x/2x/4x/8x/16x/32x") hacía el item más ancho
        que el propio popover y terminaba recortada con "...", justo el dato que
        pretendía mostrar. Ahora esas escalas son las que quedan cargadas en el combo
        "Escala" de abajo, que es donde se eligen."""
        for name, info in models.items():
            self.combo_model.addItem(name, name)
            self.combo_model.setItemData(
                self.combo_model.count() - 1,
                self.tr("Escalas: {0}").format(" / ".join(info["scales"])), Qt.ToolTipRole)

    def _current_scales(self) -> list[str]:
        """Escalas que ACEPTA de verdad la combinación motor+modelo elegida (ver el
        bloque de escalas en core/constants.py, sacado de correr los binarios). En
        Waifu2x dependen del modelo (models-cunet es el único con 1x), en Upscayl y
        SRMD son fijas por motor."""
        engine_key = self._current_engine_key()
        if engine_key == "Upscayl":
            return list(UPSCAYL_SCALES)
        if engine_key == "Waifu2x":
            info = WAIFU2X_MODELS.get(self.combo_model.currentData())
            # Sin modelo elegido todavía: la intersección de los tres, para no
            # ofrecer un 1x que solo vale con CU-Net.
            return list(info["scales"]) if info else [
                s for s in WAIFU2X_MODELS[self.tr("CU-Net (Alta Calidad)")]["scales"] if s != "1x"]
        if engine_key == "SRMD":
            info = SRMD_MODELS.get(self.combo_model.currentData())
            return list(info["scales"]) if info else list(SRMD_SCALES)
        return list(_FALLBACK_SCALES)

    def _refresh_scale_items(self):
        """Repuebla "Escala" conservando lo elegido si sigue siendo válido. Si no lo
        es (ej. 32x de Waifu2x al pasarse a SRMD, que llega hasta 4x), cae a la mayor
        escala disponible que no supere la que había -- no al default fijo: bajar de
        32x a 4x es lo esperable; saltar a 2x porque sí, no."""
        scales = self._current_scales()
        previous = self.combo_scale.currentText()
        if scales == [self.combo_scale.itemText(i) for i in range(self.combo_scale.count())]:
            return
        self.combo_scale.blockSignals(True)
        self.combo_scale.clear()
        self.combo_scale.addItems(scales)
        target = previous if previous in scales else self._closest_scale(previous, scales)
        self.combo_scale.setCurrentText(target)
        self.combo_scale.blockSignals(False)

    @staticmethod
    def _closest_scale(previous: str, scales: list[str]) -> str:
        def value(text):
            try:
                return int(text.rstrip("xX"))
            except ValueError:
                return 0
        wanted = value(previous) or 4
        below = [s for s in scales if value(s) <= wanted]
        return below[-1] if below else scales[0]

    def _refresh_denoise_items(self, levels: list[str]):
        """Repuebla "Reducir Ruido" conservando el NIVEL, no el texto: la misma
        intensidad se escribe distinto en cada motor ("2 (Alta)" en Waifu2x, "2" en
        SRMD), así que comparar cadenas perdería la selección en cada cambio."""
        current = [self.combo_denoise.itemText(i) for i in range(self.combo_denoise.count())]
        if current == levels:
            return
        previous_level = self.combo_denoise.currentText().split(" ")[0]
        self.combo_denoise.blockSignals(True)
        self.combo_denoise.clear()
        self.combo_denoise.addItems(levels)
        match = next((lvl for lvl in levels if lvl.split(" ")[0] == previous_level), None)
        self.combo_denoise.setCurrentText(match or levels[min(3, len(levels) - 1)])
        self.combo_denoise.blockSignals(False)

    def _on_engine_changed(self, _index: int):
        engine_key = self._current_engine_key()

        self.combo_model.blockSignals(True)
        self.combo_model.clear()
        self.combo_model.addItem(AI_MODEL_HOLDER, None)
        if engine_key == "Waifu2x":
            self._add_model_items(WAIFU2X_MODELS)
            self.lbl_denoise.setText(self.tr("Reducir Ruido:"))
            self._refresh_denoise_items(WAIFU2X_DENOISE_LEVELS)
            self._set_denoise_visible(True)
        elif engine_key == "SRMD":
            self._add_model_items(SRMD_MODELS)
            self.lbl_denoise.setText(self.tr("Nivel Ruido/Blur:"))
            self._refresh_denoise_items(SRMD_DENOISE_LEVELS)
            self._set_denoise_visible(True)
        elif engine_key == "Upscayl":
            for raw_name, friendly_name in UPSCAYL_MODELS_MAP.items():
                self.combo_model.addItem(friendly_name, raw_name)
            self._set_denoise_visible(False)
        else:
            self._set_denoise_visible(False)
        self.combo_model.blockSignals(False)

        self._refresh_scale_items()
        self._update_status()
        self._emit_selection()
        self._offer_download_if_missing(engine_key)

    def _on_model_changed(self, _index: int):
        # Antes que nada las escalas: en Waifu2x dependen del modelo (solo CU-Net
        # acepta 1x), así que cambiar de modelo puede invalidar la escala elegida.
        self._refresh_scale_items()
        self._emit_selection()
        # El modelo elegido no se baja aparte (viene dentro del zip del motor), pero
        # si el motor falta, elegir un modelo es igual de buen momento para ofrecerlo.
        if self.combo_model.currentData() is not None:
            self._offer_download_if_missing(self._current_engine_key())

    # ── Estado del motor y descarga ─────────────────────────────────────────
    def _update_status(self):
        engine_key = self._current_engine_key()
        info = UPSCALING_TOOLS.get(engine_key)
        if not info:
            self.status_row.clear()
            self.actions_row.set_delete_enabled(False)
            return
        downloading = model_downloads().is_downloading(self._download_key(engine_key))
        # Borrar a media descarga dejaría al worker extrayendo sobre una carpeta
        # recién borrada.
        self.actions_row.set_delete_enabled(
            is_upscaling_engine_installed(info) and not downloading)
        if downloading:
            # Descarga en curso: manda el porcentaje, no el estado en disco.
            self.status_row.show_progress(model_downloads().progress(self._download_key(engine_key)))
            return
        if is_upscaling_engine_installed(info):
            self.status_row.show_ready(self.tr("Motor instalado y listo para usar."))
        else:
            # Sin repetir el peso: ya está en el nombre del motor, en el combo
            # de arriba (ver _refresh_engine_items).
            self.status_row.show_missing(self.tr(
                "No descargado — vuelve a elegirlo en la lista para descargarlo."))

    def _on_manage_clicked(self):
        """Salta a Ajustes > Modelos y cierra este popover -- ver
        RembgPopoverContent._on_manage_clicked."""
        if open_models_settings(self):
            self.close_popover_requested.emit()

    def _on_delete_clicked(self):
        engine_key = self._current_engine_key()
        info = UPSCALING_TOOLS.get(engine_key)
        if not info or not is_upscaling_engine_installed(info):
            return
        if QMessageBox.question(
            self, self.tr("Eliminar motor"),
            self.tr("¿Eliminar '{0}' del disco?\n\nSe borra el motor completo, con todos "
                    "sus modelos. Puedes volver a descargarlo cuando quieras.").format(info["name"])
        ) != QMessageBox.Yes:
            return
        if not delete_upscaling_engine(info):
            self.status_row.show_error(self.tr("No se pudo eliminar el motor."))
            return
        self._refresh_engine_items()
        self._update_status()
        self._emit_selection()

    def _offer_download_if_missing(self, engine_key):
        """Ofrece descargar el motor que falta. Se difiere un ciclo de evento
        a propósito: esto sale de currentIndexChanged, con el desplegable del combo
        todavía cerrándose -- abrir un modal justo ahí deja el popup a medio cerrar
        por encima del diálogo."""
        info = UPSCALING_TOOLS.get(engine_key)
        if not info or model_downloads().is_downloading(model_download_key(info)) or is_upscaling_engine_installed(info):
            return
        QTimer.singleShot(0, lambda: self._ask_and_download(engine_key))

    def _ask_and_download(self, engine_key: str):
        info = UPSCALING_TOOLS.get(engine_key)
        # Revalidar: entre el singleShot y este momento el usuario pudo cambiar de
        # motor, o pudo terminar una descarga lanzada desde Ajustes > Modelos.
        if not info or model_downloads().is_downloading(model_download_key(info)) or is_upscaling_engine_installed(info):
            self._update_status()
            return
        if self._current_engine_key() != engine_key:
            return
        accepted = confirm_model_download(
            self, info["name"], get_upscaling_engine_size_bytes(info),
            subject=self.tr("motor"),
            extra_note=self.tr(
                "El motor trae sus propios modelos de reescalado adentro -- se "
                "descarga una sola vez y sirve para todos los modelos de esta lista."
            ),
        )
        if not accepted:
            self._update_status()
            return

        # Si ya se estaba bajando (lanzada desde otra pantalla), start() no hace nada
        # y el progreso llega igual por las señales del gestor.
        key = model_download_key(info)
        self._started_here.add(key)
        if not model_downloads().start(key, download_upscaling_engine, info):
            self._started_here.discard(key)

    def _on_download_started(self, key: str):
        if self._is_current_download(key):
            self._update_status()

    def _on_download_progress(self, pct: int, key: str):
        if self._is_current_download(key):
            self.status_row.show_progress(pct)

    def _on_download_finished(self, success: bool, message: str, key: str):
        started_here = key in self._started_here
        self._started_here.discard(key)
        self._refresh_engine_items()
        if success:
            self._update_status()
            return
        if self._is_current_download(key):
            self.status_row.show_error(self.tr("No se pudo descargar: {0}").format(message))
        if started_here:
            QMessageBox.warning(self, self.tr("Error de descarga"), message)

    def is_valid_selection(self) -> bool:
        return self.combo_engine.currentData() is not None and self.combo_model.currentData() is not None

    def is_active(self) -> bool:
        """API común a los tres popovers de la barra lateral (Reescalar/Eliminar
        Fondo/Redimensionar) para que ImageToolsTab pregunte "¿hay algo que
        desactivar?" sin conocer los internos de cada uno -- ver
        ImageToolsTab._deactivate_on_right_click."""
        return self.is_valid_selection()

    def deactivate(self):
        """Vuelve Motor a su placeholder -- dispara selection_changed(is_valid=False)
        vía la cascada existente (_on_engine_changed limpia Modelo también)."""
        self.combo_engine.setCurrentIndex(0)

    def _emit_selection(self):
        engine_key = self.combo_engine.currentData()
        model_key = self.combo_model.currentData()
        self.selection_changed.emit(engine_key or "", model_key or "", self.is_valid_selection())

    def current_selection(self) -> tuple[str, str]:
        return self.combo_engine.currentData(), self.combo_model.currentData()

    def get_settings(self) -> dict:
        """Mismo criterio que ResizePopoverContent.get_settings(): el popover solo
        junta la configuración, se aplica recién al apretar "Convertir" (ver
        ImageToolsTab._on_convert_clicked e ImageConverter._apply_ai_upscale).
        upscale_enabled = is_valid_selection() -- mismo criterio que ya usa
        _style_upscale_button() para pintar el botón verde/gris."""
        return {
            "upscale_enabled": self.is_valid_selection(),
            "upscale_engine": self.combo_engine.currentData(),
            "upscale_model": self.combo_model.currentData(),
            "upscale_scale": self.combo_scale.currentText(),
            "upscale_tile": self.entry_tile.text(),
            "upscale_power": self.combo_power.currentData() or self.combo_power.currentText(),
            "upscale_denoise": self.combo_denoise.currentText(),
            "upscale_tta": self.check_tta.isChecked(),
        }
