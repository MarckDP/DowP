# src/gui/tabs/advanced_process/recode_options.py
import sys
import os

if __name__ == "__main__":
    src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)

from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, QParallelAnimationGroup
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui.widgets.preset_bar import PresetBar
from gui.styles import get_theme_token
from core.utils.preset_manager import IA_POST_DOWNLOAD_FUNCTIONS, IA_TOOLS_NAMESPACE

_PRESET_NAMESPACE = "video_tools/avanzado"
_UPSCALE_PRESET_NAMESPACE = IA_TOOLS_NAMESPACE
_TITLE_STYLE_BASE = "font-weight: bold; font-size: 13px;"


class RecodeOptionsWidget(QFrame):
    """
    Tarjeta "Posprocesar" de Proceso Avanzado/Modo Rápido: dos secciones
    independientes y COMBINABLES -- Recodificación (switch + PresetBar sobre
    "video_tools/avanzado") y "Herramientas IA" (switch + PresetBar sobre
    "video_tools/ia_tools", namespace compartido -- ver
    core.utils.preset_manager.IA_POST_DOWNLOAD_FUNCTIONS: solo Reescalado; los
    preajustes de Mapa de Profundidad no se listan aquí porque solo corren en
    Herramientas Multimedia) -- elegir solo una corre solo esa al terminar la
    descarga; elegir las dos las encadena (Reescalado IA primero,
    Recodificación después, mismo orden y mismas razones que en Herramientas
    Multimedia -- ver core/tabs/video_tools/upscale_chain.py). Antes se
    llamaba "Recodificar" y tenía una sola sección -- renombrada al agregar
    la segunda, ya no describe una sola acción.

    Mismo molde visual que SubtitleOptionsWidget (misma pestaña, tarjeta hermana a su
    izquierda): QFrame de ancho fijo, header colapsable, cuerpo animado. No sabe nada de
    cómo se ejecuta nada de esto — eso lo maneja recode_controller.py (junta la
    configuración) y cada download_controller.py (la ejecuta).
    """
    COMPACT_WIDTH = 350
    COLLAPSED_HEIGHT = 38
    toggled_collapse = Signal(bool)
    # Emitida cuando cambia si hay una recodificación realmente activa (switch
    # encendido + preset elegido, no "Sin preset") - la usa quick_mode_view.py para
    # replicar el resaltado en su propia etiqueta "Recodificar" externa (aquí el
    # header vive oculto, ver show_header=False).
    header_highlight_changed = Signal(bool)

    def __init__(self, start_expanded: bool = False, show_header: bool = True):
        super().__init__()
        self.setObjectName("additionalOptionsContainer")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._show_header = show_header
        self._is_expanded = start_expanded
        self._anim_group = None

        self.init_ui()

        if not self._show_header:
            self.header_widget.setVisible(False)
        self._collapsed_height = self.COLLAPSED_HEIGHT if self._show_header else 0

        self.set_expanded(self._is_expanded, animate=False)

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(12, 8, 12, 8)
        self.main_layout.setSpacing(4)

        # ── 1. Cabecera Clicable ─────────────────────────────────
        self.header_widget = QWidget()
        self.header_widget.setObjectName("recodeHeaderWidget")
        self.header_widget.setCursor(Qt.PointingHandCursor)
        self.header_widget.setFixedHeight(22)
        header_layout = QHBoxLayout(self.header_widget)
        header_layout.setContentsMargins(4, 0, 4, 0)
        header_layout.setSpacing(0)

        self.title_label = QLabel(self.tr("Posprocesar"))
        self.title_label.setObjectName("sectionTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet(_TITLE_STYLE_BASE)
        header_layout.addWidget(self.title_label)

        self.header_widget.mousePressEvent = self._on_header_clicked
        self.main_layout.addWidget(self.header_widget)

        # ── 2. Cuerpo Desplegable ────────────────────────────────
        self.body_container = QWidget()
        body_layout = QVBoxLayout(self.body_container)
        body_layout.setContentsMargins(0, 4, 0, 0)
        body_layout.setSpacing(6)

        self.lbl_section_recode = QLabel(self.tr("Recodificación"))
        self.lbl_section_recode.setObjectName("sectionTitle")
        body_layout.addWidget(self.lbl_section_recode)

        # Texto propio del checkbox (no un QLabel aparte, ver conversación): el tema ya
        # define QCheckBox { spacing: 8px } para el hueco entre el indicador y su
        # texto - con un QLabel aparte más spacing de layout encima (arrastre de cuando
        # esto era un ToggleSwitch mucho más ancho), quedaban dos huecos sumados.
        switch_row = QHBoxLayout()
        switch_row.setContentsMargins(0, 0, 0, 0)
        self.switch_recode = QCheckBox(self.tr("Recodificar al finalizar"))
        self.switch_recode.setCursor(Qt.PointingHandCursor)
        switch_row.addWidget(self.switch_recode)
        switch_row.addStretch()
        body_layout.addLayout(switch_row)

        self.chk_keep_original = QCheckBox(self.tr("Mantener medios originales"))
        self.chk_keep_original.setCursor(Qt.PointingHandCursor)
        self.chk_keep_original.setChecked(True)
        self.chk_keep_original.setEnabled(False)
        self.chk_keep_original.setToolTip(self.tr(
            "Activado (por defecto): conserva el archivo descargado además del "
            "recodificado. Desactivado: al terminar con éxito la recodificación, se "
            "borra el original."
        ))
        body_layout.addWidget(self.chk_keep_original)

        self.preset_bar = PresetBar(
            _PRESET_NAMESPACE, get_settings=None, parent=self.body_container,
            show_picker=True, show_save_button=False,
        )
        self.preset_bar.setEnabled(False)
        self.preset_bar.preset_applied.connect(self._update_header_highlight)
        body_layout.addWidget(self.preset_bar)

        # Prefijo/Sufijo del archivo recodificado - vacíos por defecto (la app igual
        # evita colisiones sola, ver preset_manager.build_recode_output_path, si el
        # contenedor elegido no cambia la extensión del original), pero permiten
        # elegir un nombre propio en vez del automático "(recodificado)".
        naming_row = QHBoxLayout()
        naming_row.setContentsMargins(0, 0, 0, 0)
        naming_row.setSpacing(6)

        prefix_col = QVBoxLayout()
        prefix_col.setSpacing(2)
        self.lbl_prefix = QLabel(self.tr("Prefijo"))
        self.lbl_prefix.setObjectName("menuLabel")
        self.txt_prefix = QLineEdit()
        self.txt_prefix.setPlaceholderText(self.tr("(ninguno)"))
        self.txt_prefix.setEnabled(False)
        prefix_col.addWidget(self.lbl_prefix)
        prefix_col.addWidget(self.txt_prefix)
        naming_row.addLayout(prefix_col)

        suffix_col = QVBoxLayout()
        suffix_col.setSpacing(2)
        self.lbl_suffix = QLabel(self.tr("Sufijo"))
        self.lbl_suffix.setObjectName("menuLabel")
        self.txt_suffix = QLineEdit("_recoded")
        self.txt_suffix.setPlaceholderText(self.tr("(ninguno)"))
        self.txt_suffix.setEnabled(False)
        suffix_col.addWidget(self.lbl_suffix)
        suffix_col.addWidget(self.txt_suffix)
        naming_row.addLayout(suffix_col)

        body_layout.addLayout(naming_row)

        # ── Herramientas IA (hoy solo Reescalado) -- segunda sección, combinable con la de arriba ──
        # (ver docstring de la clase): mismo molde (switch + PresetBar +
        # prefijo/sufijo), namespace compartido "video_tools/ia_tools". El
        # prefijo/sufijo de acá solo se usa cuando Reescalado IA corre SOLO
        # (sin Recodificación) -- si las dos están activas, el archivo final
        # usa el prefijo/sufijo de Recodificación, el intermedio del
        # reescalado no tiene nombre visible (ver upscale_chain.py).
        divider = QFrame(self.body_container)
        divider.setFrameShape(QFrame.HLine)
        divider.setStyleSheet(f"background-color: {get_theme_token('borde_sutil', '#2d2d2d')};")
        divider.setFixedHeight(1)
        body_layout.addWidget(divider)

        self.lbl_section_upscale = QLabel(self.tr("Herramientas IA"))
        self.lbl_section_upscale.setObjectName("sectionTitle")
        body_layout.addWidget(self.lbl_section_upscale)

        switch_row_upscale = QHBoxLayout()
        switch_row_upscale.setContentsMargins(0, 0, 0, 0)
        self.switch_upscale = QCheckBox(self.tr("Reescalar con IA al finalizar"))
        self.switch_upscale.setCursor(Qt.PointingHandCursor)
        switch_row_upscale.addWidget(self.switch_upscale)
        switch_row_upscale.addStretch()
        body_layout.addLayout(switch_row_upscale)

        self.preset_bar_upscale = PresetBar(
            _UPSCALE_PRESET_NAMESPACE, get_settings=None, parent=self.body_container,
            show_picker=True, show_save_button=False,
            function_choices=IA_POST_DOWNLOAD_FUNCTIONS,
        )
        self.preset_bar_upscale.setEnabled(False)
        self.preset_bar_upscale.preset_applied.connect(self._update_header_highlight)
        body_layout.addWidget(self.preset_bar_upscale)

        naming_row_upscale = QHBoxLayout()
        naming_row_upscale.setContentsMargins(0, 0, 0, 0)
        naming_row_upscale.setSpacing(6)

        prefix_col_upscale = QVBoxLayout()
        prefix_col_upscale.setSpacing(2)
        self.lbl_upscale_prefix = QLabel(self.tr("Prefijo"))
        self.lbl_upscale_prefix.setObjectName("menuLabel")
        self.txt_upscale_prefix = QLineEdit()
        self.txt_upscale_prefix.setPlaceholderText(self.tr("(ninguno)"))
        self.txt_upscale_prefix.setEnabled(False)
        prefix_col_upscale.addWidget(self.lbl_upscale_prefix)
        prefix_col_upscale.addWidget(self.txt_upscale_prefix)
        naming_row_upscale.addLayout(prefix_col_upscale)

        suffix_col_upscale = QVBoxLayout()
        suffix_col_upscale.setSpacing(2)
        self.lbl_upscale_suffix = QLabel(self.tr("Sufijo"))
        self.lbl_upscale_suffix.setObjectName("menuLabel")
        self.txt_upscale_suffix = QLineEdit("_upscaled")
        self.txt_upscale_suffix.setPlaceholderText(self.tr("(ninguno)"))
        self.txt_upscale_suffix.setEnabled(False)
        suffix_col_upscale.addWidget(self.lbl_upscale_suffix)
        suffix_col_upscale.addWidget(self.txt_upscale_suffix)
        naming_row_upscale.addLayout(suffix_col_upscale)

        body_layout.addLayout(naming_row_upscale)

        self.switch_upscale.toggled.connect(self._on_switch_upscale_toggled)
        self.switch_upscale.toggled.connect(self._update_header_highlight)

        # Red de seguridad: _expanded_height() ya calcula el alto exacto del contenido
        # (ver conversación - antes esto era necesario porque EXPANDED_HEIGHT era un
        # número fijo con hueco de sobra, y sin stretch Qt centraba el contenido en vez
        # de pegarlo arriba), pero se deja igual por si algún redondeo/timing de
        # animación deja un resto de un par de píxeles.
        body_layout.addStretch(1)

        self.main_layout.addWidget(self.body_container)

        self.switch_recode.toggled.connect(self._on_switch_toggled)
        self.switch_recode.toggled.connect(self._update_header_highlight)
        self._update_header_highlight()

    def _on_switch_toggled(self, checked: bool):
        self.preset_bar.setEnabled(checked)
        self.txt_prefix.setEnabled(checked)
        self.txt_suffix.setEnabled(checked)
        self._update_keep_original_enabled()

    def _on_switch_upscale_toggled(self, checked: bool):
        self.preset_bar_upscale.setEnabled(checked)
        self.txt_upscale_prefix.setEnabled(checked)
        self.txt_upscale_suffix.setEnabled(checked)
        self._update_keep_original_enabled()

    def _update_keep_original_enabled(self):
        # "Mantener medios originales" se refiere al archivo ORIGINAL descargado,
        # antes de CUALQUIER etapa -- aplica si hay al menos una activa, no solo
        # Recodificación (antes esto era 1:1 con el único switch que existía).
        self.chk_keep_original.setEnabled(
            self.switch_recode.isChecked() or self.switch_upscale.isChecked()
        )

    def _update_header_highlight(self, *_args):
        """Ilumina el texto "Posprocesar" en el verde de acento cuando hay al
        menos una etapa (Recodificación y/o Reescalado IA) realmente activa
        (switch encendido + preset elegido, no "Sin preset" - ver conversación:
        dejar el switch prendido con "Sin preset" no hace nada, así que ese
        estado NO debe verse "activo")."""
        recode_active = self.switch_recode.isChecked() and bool(self.preset_bar.active_preset_name())
        upscale_active = self.switch_upscale.isChecked() and bool(self.preset_bar_upscale.active_preset_name())
        active = recode_active or upscale_active
        if active:
            accent = get_theme_token('acento_primario', '#B9E640')
            self.title_label.setStyleSheet(f"{_TITLE_STYLE_BASE} color: {accent};")
        else:
            self.title_label.setStyleSheet(_TITLE_STYLE_BASE)
        self.header_highlight_changed.emit(active)

    def _on_header_clicked(self, event):
        self.toggle_collapse()

    def toggle_collapse(self):
        self.set_expanded(not self._is_expanded, animate=True)

    @property
    def is_expanded(self) -> bool:
        """Estado lógico actual (se actualiza al instante en set_expanded, a
        diferencia de isVisible()/toggled_collapse, que con animate=True quedan
        atados a cuándo termina la animación de 220ms - ver quick_mode_view.py,
        que necesita el valor ya actualizado para no re-togglear en cada clic
        mientras el popover todavía se está colapsando)."""
        return self._is_expanded

    def _expanded_height(self) -> int:
        margins = self.main_layout.contentsMargins()
        header_h = self.header_widget.sizeHint().height() if self._show_header else 0
        spacing = self.main_layout.spacing() if self._show_header else 0
        return (
            header_h + spacing
            + self.body_container.sizeHint().height()
            + margins.top() + margins.bottom()
        )

    def set_expanded(self, expanded: bool, animate: bool = True):
        self._is_expanded = expanded

        expanded_h = self._expanded_height()
        start_h = self.height() if self.height() > 0 else (expanded_h if not expanded else self._collapsed_height)
        target_h = expanded_h if expanded else self._collapsed_height

        if not self._show_header:
            if expanded:
                self.setVisible(True)
                self.raise_()

        if not animate:
            if self._anim_group and self._anim_group.state() == QPropertyAnimation.Running:
                self._anim_group.stop()
            self.body_container.setVisible(expanded)
            self.setFixedHeight(target_h)
            if not self._show_header and not expanded:
                self.setVisible(False)
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
                if not self._show_header:
                    self.setVisible(False)
            self.setFixedHeight(target_h)
            self.toggled_collapse.emit(self._is_expanded)

        self._anim_group.finished.connect(on_finished)
        self._anim_group.start()


if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    from gui.styles import load_stylesheet
    app = QApplication(sys.argv)
    load_stylesheet(app, "dark")
    w = RecodeOptionsWidget(start_expanded=True)
    w.resize(350, 250)
    w.show()
    sys.exit(app.exec())
