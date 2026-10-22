# src/gui/tabs/advanced_process/subtitle_options.py
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, QParallelAnimationGroup
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui.widgets.combo_box import AutoPopupComboBox
from gui.widgets.mode_selector import ModeSelector
from gui.styles import get_theme_token
from gui.styles import apply_shapes

_TITLE_STYLE_BASE = "font-weight: bold; font-size: 13px;"


class SubtitleOptionsWidget(QFrame):
    COMPACT_WIDTH = 350
    COLLAPSED_HEIGHT = 38
    toggled_collapse = Signal(bool)
    # True con "Crear con IA", False con "Del sitio" (ver subtitle_controller.py).
    source_changed = Signal(bool)

    def __init__(self, start_expanded: bool = False):
        super().__init__()
        self.setObjectName("additionalOptionsContainer")
        self.setAttribute(Qt.WA_StyledBackground, True)
        # COMPACT_WIDTH ya NO es ni ancho fijo ni mínimo: junto a la tarjeta de
        # Recodificar (ver conversación), esta tarjeta se estira Y se achica con la
        # ventana igual que video_details, sin piso propio - un setMinimumWidth aquí
        # (aunque fuera el mismo 350 "de siempre") le gana al ancho disponible en
        # ventanas chicas y hace desbordar todo el bloque en vez de comprimirse con
        # texto recortado, que es el comportamiento que tenía antes y se quiere
        # conservar (arreglarlo es un problema aparte, a futuro).
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        self._is_expanded = start_expanded
        self._anim_group = None

        self.init_ui()
        self.set_expanded(self._is_expanded, animate=False)

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(12, 8, 12, 8)
        self.main_layout.setSpacing(4)

        # ── 1. Cabecera Clicable (Delgada y Centrada) ───────────────────────
        self.header_widget = QWidget()
        self.header_widget.setObjectName("subtitleHeaderWidget")
        self.header_widget.setCursor(Qt.PointingHandCursor)
        self.header_widget.setFixedHeight(22)
        header_layout = QHBoxLayout(self.header_widget)
        header_layout.setContentsMargins(4, 0, 4, 0)
        header_layout.setSpacing(0)

        self.title_label = QLabel(self.tr("Subtítulos"))
        self.title_label.setObjectName("sectionTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet(apply_shapes(_TITLE_STYLE_BASE))

        header_layout.addWidget(self.title_label)

        self.header_widget.mousePressEvent = self._on_header_clicked
        self.main_layout.addWidget(self.header_widget)

        # ── 2. Contenedor de Opciones Desplegable ───────────────────────────
        self.body_container = QWidget()
        body_layout = QVBoxLayout(self.body_container)
        body_layout.setContentsMargins(0, 4, 0, 0)
        body_layout.setSpacing(6)

        # Idioma
        self.language_container = QWidget()
        language_layout = QHBoxLayout(self.language_container)
        language_layout.setContentsMargins(0, 0, 0, 0)
        language_layout.setSpacing(8)

        self.lbl_subtitle_language = QLabel(self.tr("Idioma"))
        self.lbl_subtitle_language.setObjectName("menuLabel")
        self.lbl_subtitle_language.setFixedWidth(58)
        self.combo_subtitle_language = AutoPopupComboBox()
        self.combo_subtitle_language.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.combo_subtitle_language.addItem(self.tr("Seleccionar idioma..."))

        language_layout.addWidget(self.lbl_subtitle_language)
        language_layout.addWidget(self.combo_subtitle_language, 1)

        # Formato
        self.format_container = QWidget()
        format_layout = QHBoxLayout(self.format_container)
        format_layout.setContentsMargins(0, 0, 0, 0)
        format_layout.setSpacing(8)

        self.lbl_subtitle_format = QLabel(self.tr("Formato"))
        self.lbl_subtitle_format.setObjectName("menuLabel")
        self.lbl_subtitle_format.setFixedWidth(58)
        self.combo_subtitle_format = AutoPopupComboBox()
        self.combo_subtitle_format.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.combo_subtitle_format.addItem("-")
        self.combo_subtitle_format.setEnabled(False)

        format_layout.addWidget(self.lbl_subtitle_format)
        format_layout.addWidget(self.combo_subtitle_format, 1)

        self.combo_subtitle_format.currentTextChanged.connect(self.update_standardize_visibility)

        # Botón Descargar Subtítulos
        self.btn_download_subtitles = QPushButton(self.tr("Descargar Subtítulos"))
        self.btn_download_subtitles.setObjectName("secondaryButton")
        self.btn_download_subtitles.setEnabled(False)

        # Switches
        self.chk_download_with_media = self._build_switch_row(self.tr("Descargar con el medio"))
        self.chk_standardize_srt = self._build_switch_row(self.tr("Limpiar y convertir a SRT"))
        self.chk_cut_to_fragment = self._build_switch_row(self.tr("Recortar al fragmento"))
        # Activa por defecto: el SRT tal como lo entrega YouTube puede traer las líneas
        # repetidas de un subtítulo con estilo y caracteres invisibles. Se recuerda la
        # última elección del usuario (solo con clic: al cambiar de medio en la cola el
        # estado de cada ítem se restaura con setChecked y no debe tocar la preferencia).
        from core.utils.config_manager import get_config
        self.chk_standardize_srt["switch"].setChecked(get_config().get("subtitle_clean_default", True))
        self.chk_standardize_srt["switch"].clicked.connect(self._remember_clean_default)
        clean_tip = self.tr(
            "Quita las líneas repetidas por el estilo del creador, las etiquetas y los caracteres "
            "invisibles, y entrega un SRT compatible con cualquier editor.\n"
            "Desactívalo para recibir el subtítulo tal como lo entrega YouTube."
        )
        self.chk_standardize_srt["container"].setToolTip(clean_tip)
        self.chk_standardize_srt["switch"].setToolTip(clean_tip)
        
        # Deshabilitados por defecto hasta que se seleccione un subtítulo válido
        self.chk_download_with_media["container"].setEnabled(False)
        self.chk_standardize_srt["container"].setEnabled(False)
        self.chk_cut_to_fragment["container"].setEnabled(False)
        
        # Tooltips
        tooltip_text = self.tr("Al recortar, el subtítulo se convertirá automáticamente a SRT para garantizar la compatibilidad y precisión del corte.")
        self.chk_cut_to_fragment["container"].setToolTip(tooltip_text)
        self.chk_cut_to_fragment["switch"].setToolTip(tooltip_text)
        
        # Origen de los subtítulos: los que ofrece el sitio, o crearlos con Whisper a partir
        # del medio descargado (ver subtitle_controller.py). Siempre empieza en "Del sitio".
        self.source_selector = ModeSelector(self.body_container, labels=[self.tr("Del sitio"), self.tr("Crear con IA")])
        self.source_selector.mode_changed.connect(lambda _text: self._on_source_changed())
        body_layout.addWidget(self.source_selector)

        self.site_container = QWidget()
        site_layout = QVBoxLayout(self.site_container)
        site_layout.setContentsMargins(0, 0, 0, 0)
        site_layout.setSpacing(6)
        site_layout.addWidget(self.language_container)
        site_layout.addWidget(self.format_container)
        site_layout.addWidget(self.btn_download_subtitles)
        site_layout.addWidget(self.chk_download_with_media["container"])
        site_layout.addWidget(self.chk_standardize_srt["container"])
        site_layout.addWidget(self.chk_cut_to_fragment["container"])
        body_layout.addWidget(self.site_container)

        # "Crear con IA": solo lo esencial; lo avanzado (corte, karaoke, detector de voz,
        # vocabulario, estilo del ASS) llega con un preajuste de Transcripción de
        # Herramientas IA. Con un preajuste, Modelo y Formato muestran los suyos y se
        # bloquean; el idioma sigue editable.
        self.ai_container = QWidget()
        ai_layout = QGridLayout(self.ai_container)
        ai_layout.setContentsMargins(0, 0, 0, 0)
        ai_layout.setHorizontalSpacing(8)
        ai_layout.setVerticalSpacing(6)
        ai_layout.setColumnStretch(1, 1)
        self.combo_ai_model = AutoPopupComboBox()
        self.combo_ai_language = AutoPopupComboBox()
        self.combo_ai_format = AutoPopupComboBox()
        self.combo_ai_preset = AutoPopupComboBox()
        self.combo_ai_preset.setToolTip(self.tr(
            "Preajustes de Transcripción guardados en Herramientas IA. Traen las opciones "
            "avanzadas (corte, karaoke, saltar silencios, vocabulario, estilo). Aquí siempre "
            "se crea un archivo de subtítulos."))
        rows = ((self.tr("Modelo"), self.combo_ai_model), (self.tr("Idioma"), self.combo_ai_language),
                (self.tr("Formato"), self.combo_ai_format), (self.tr("Preajuste"), self.combo_ai_preset))
        for row, (text, combo) in enumerate(rows):
            label = QLabel(text)
            label.setObjectName("menuLabel")
            label.setMinimumWidth(58)
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(8)
            ai_layout.addWidget(label, row, 0)
            ai_layout.addWidget(combo, row, 1)
        self.ai_container.setVisible(False)
        body_layout.addWidget(self.ai_container)

        # Red de seguridad (ver recode_options.py, mismo patrón): _expanded_height()
        # calcula el alto exacto del contenido, esto es solo por si algún redondeo dejara
        # un resto de un par de píxeles - sin esto, Qt centraría el contenido en vez de
        # pegarlo arriba.
        body_layout.addStretch(1)

        self.main_layout.addWidget(self.body_container)

    def is_ai_mode(self) -> bool:
        buttons = self.source_selector.buttons
        return len(buttons) > 1 and buttons[1].isChecked()

    def set_ai_mode(self, ai: bool):
        """Cambia el origen sin pasar por el clic (al cambiar de medio en la cola)."""
        if ai != self.is_ai_mode():
            self.source_selector.buttons[1 if ai else 0].click()
        else:
            self._apply_source_visibility()

    def _on_source_changed(self):
        self._apply_source_visibility()
        self.source_changed.emit(self.is_ai_mode())

    def _apply_source_visibility(self):
        ai = self.is_ai_mode()
        self.site_container.setVisible(not ai)
        self.ai_container.setVisible(ai)
        # El alto de la tarjeta se calcula según el contenido (ver _expanded_height).
        if self._is_expanded:
            self.setFixedHeight(self._expanded_height())

    def _on_header_clicked(self, event):
        self.toggle_collapse()

    def toggle_collapse(self):
        self.set_expanded(not self._is_expanded, animate=True)

    def set_header_active(self, active: bool):
        """Ilumina el título "Subtítulos" en el verde de acento cuando hay un
        subtítulo realmente seleccionado (no el placeholder "Seleccionar idioma...")
        - mismo patrón que RecodeOptionsWidget._update_header_highlight, disparado
        desde subtitle_controller.py::on_subtitle_selection_changed."""
        if active:
            accent = get_theme_token('acento_primario', '#B9E640')
            self.title_label.setStyleSheet(f"{_TITLE_STYLE_BASE} color: {accent};")
        else:
            self.title_label.setStyleSheet(apply_shapes(_TITLE_STYLE_BASE))

    def _expanded_height(self) -> int:
        """Alto real necesario para el cuerpo actual, calculado en vivo (con el tema/
        fuente ya aplicados) en vez de un número fijo ajustado a mano - ese número se
        desalinea cada vez que cambia el contenido del cuerpo (ver conversación: pasó
        al convertir los switches a checkboxes, más bajos, y quedó hueco de sobra)."""
        margins = self.main_layout.contentsMargins()
        return (
            self.header_widget.height() + self.main_layout.spacing()
            + self.body_container.sizeHint().height()
            + margins.top() + margins.bottom()
        )

    def set_expanded(self, expanded: bool, animate: bool = True):
        self._is_expanded = expanded

        expanded_h = self._expanded_height()
        start_h = self.height() if self.height() > 0 else (expanded_h if not expanded else self.COLLAPSED_HEIGHT)
        target_h = expanded_h if expanded else self.COLLAPSED_HEIGHT

        if not animate:
            if self._anim_group and self._anim_group.state() == QPropertyAnimation.Running:
                self._anim_group.stop()
            self.body_container.setVisible(expanded)
            self.setFixedHeight(target_h)
            self.toggled_collapse.emit(expanded)
            return

        if self._anim_group and self._anim_group.state() == QPropertyAnimation.Running:
            self._anim_group.stop()

        if expanded:
            self.body_container.show()

        anim_max = QPropertyAnimation(self, b"maximumHeight")
        anim_max.setDuration(220)
        anim_max.setStartValue(start_h)
        anim_max.setEndValue(target_h)
        anim_max.setEasingCurve(QEasingCurve.Type.OutCubic)

        anim_min = QPropertyAnimation(self, b"minimumHeight")
        anim_min.setDuration(220)
        anim_min.setStartValue(start_h)
        anim_min.setEndValue(target_h)
        anim_min.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._anim_group = QParallelAnimationGroup(self)
        self._anim_group.addAnimation(anim_max)
        self._anim_group.addAnimation(anim_min)

        def on_finished():
            if not self._is_expanded:
                self.body_container.hide()
            self.setFixedHeight(target_h)
            self.toggled_collapse.emit(self._is_expanded)

        self._anim_group.finished.connect(on_finished)
        self._anim_group.start()

    def _build_switch_row(self, text):
        # Nombre "switch" conservado (no "checkbox") aunque ahora sea un QCheckBox -
        # subtitle_controller.py y advanced_process_view.py acceden a esta clave por
        # todos lados (["switch"].isChecked()/.toggled/...) y QCheckBox comparte esa
        # misma API con ToggleSwitch, así que renombrarla sería puro churn sin motivo.
        #
        # Texto propio del checkbox (no un QLabel aparte, ver conversación): el tema ya
        # define QCheckBox { spacing: 8px } para el hueco entre el indicador y su
        # texto - con un QLabel aparte más spacing de layout encima (arrastre de cuando
        # esto era un ToggleSwitch mucho más ancho), quedaban dos huecos sumados.
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        switch = QCheckBox(text)
        switch.setCursor(Qt.PointingHandCursor)

        layout.addWidget(switch)
        layout.addStretch()

        return {"container": container, "switch": switch}

    def _remember_clean_default(self, checked):
        from core.utils.config_manager import get_config, save_config
        cfg = get_config()
        cfg["subtitle_clean_default"] = bool(checked)
        save_config(cfg)

    def default_clean_checked(self):
        """Estado inicial de 'Limpiar y convertir a SRT' para un medio sin opciones propias."""
        from core.utils.config_manager import get_config
        return bool(get_config().get("subtitle_clean_default", True))

    def update_standardize_visibility(self):
        """Habilita 'Limpiar y convertir a SRT' cuando hay un subtítulo seleccionado, también
        si ya es SRT: el SRT de YouTube puede traer líneas repetidas por el estilo. Sin
        subtítulo solo se deshabilita, sin desmarcar, para no perder el valor por defecto
        antes de que el usuario elija un idioma."""
        fmt_data = self.combo_subtitle_format.currentData()
        ext = (fmt_data.get("ext") or "").lower() if fmt_data else ""
        should_enable = bool(fmt_data) and ext != ""
        self.chk_standardize_srt["container"].setEnabled(should_enable)
