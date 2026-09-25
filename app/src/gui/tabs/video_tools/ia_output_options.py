# src/gui/tabs/video_tools/ia_output_options.py
"""Casillas de salida comunes a las Herramientas IA de video (Reescalado IA, Mapa de
Profundidad y Mapa de Normales), debajo del combo de contenedor de cada panel:

  - "16 bits" (solo en los mapas): salida sin pérdida. Quien lo usa filtra su combo de
    contenedores a los que admiten 16 bits (ver CONTAINERS_16BIT).
  - "Conservar transparencia": solo tiene efecto si el video de origen la trae. Visible
    solo con un contenedor que pueda llevarla (ver ia_video_common.alpha_supported).
  - "Conservar audio": marcada por defecto.
  - Mapa de Normales en MP4: un aviso, porque H.264 deforma las direcciones.

Cómo se codifica cada combinación: core/tabs/video_tools/ia_video_common.py.
"""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QLabel, QVBoxLayout, QWidget

from core.tabs.video_tools.ia_video_common import alpha_supported
from gui.styles import get_theme_token


class VideoIAOutputOptions(QWidget):
    changed = Signal()
    depth16_toggled = Signal(bool)

    def __init__(self, parent=None, allow_16bit: bool = False):
        super().__init__(parent)
        self._container = "mp4"
        self._kind = "color"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 0)
        layout.setSpacing(6)

        self.chk_16bit = None
        if allow_16bit:
            self.chk_16bit = QCheckBox(self.tr("16 bits (sin pérdida)"))
            self.chk_16bit.setToolTip(self.tr(
                "Guarda el mapa con 16 bits de precisión y sin compresión con pérdida, para "
                "composición o 3D. Solo MKV (FFV1) y MOV (PNG) lo admiten, y los archivos "
                "ocupan mucho más."))
            self.chk_16bit.toggled.connect(self._on_16bit_toggled)
            layout.addWidget(self.chk_16bit)

        self.chk_alpha = QCheckBox()
        self.chk_alpha.setChecked(False)
        self.chk_alpha.toggled.connect(lambda _c: self.changed.emit())
        layout.addWidget(self.chk_alpha)

        self.chk_audio = QCheckBox(self.tr("Conservar audio"))
        self.chk_audio.setChecked(True)
        self.chk_audio.setToolTip(self.tr("Copia el audio del video original, sin recodificarlo."))
        self.chk_audio.toggled.connect(lambda _c: self.changed.emit())
        layout.addWidget(self.chk_audio)

        self.lbl_warning = QLabel(self.tr(
            "MP4 (H.264) deforma las normales: úsalo solo como vista previa. Para usar el "
            "mapa, elige MOV o MKV."))
        self.lbl_warning.setWordWrap(True)
        self.lbl_warning.setStyleSheet(
            f"color: {get_theme_token('estado_aviso', '#d8c94a')}; font-size: 11px;")
        layout.addWidget(self.lbl_warning)

        self._refresh_alpha()

    def is_16bit(self) -> bool:
        return bool(self.chk_16bit and self.chk_16bit.isChecked())

    def set_container(self, container: str):
        self._container = (container or "mp4").lower()
        self._refresh_alpha()

    def set_kind(self, kind: str):
        """Qué produce la función elegida: "color" (Reescalado), "gray" (Profundidad) o
        "normals" (Normales) -- cambia dónde cabe la transparencia y el aviso de MP4."""
        self._kind = kind
        self._refresh_alpha()

    def _on_16bit_toggled(self, checked: bool):
        self._refresh_alpha()
        self.depth16_toggled.emit(checked)
        self.changed.emit()

    def _refresh_alpha(self):
        """La transparencia solo cabe en MOV (ProRes 4444, o PNG en 16 bits) y en MKV
        (FFV1) en 16 bits o con normales. Con otro contenedor la casilla se oculta."""
        visible = alpha_supported(self._container, self.is_16bit(), self._kind)
        if self._container == "mov" and not self.is_16bit():
            text = self.tr("Conservar transparencia (ProRes 4444)")
        else:
            text = self.tr("Conservar transparencia (sin pérdida)")
        self.chk_alpha.setText(text)
        self.chk_alpha.setToolTip(self.tr(
            "Solo si el video original tiene transparencia; si no la tiene, se genera un "
            "archivo normal. Los archivos con transparencia ocupan mucho más."))
        self.chk_alpha.setVisible(visible)
        self.lbl_warning.setVisible(self._kind == "normals" and self._container == "mp4")

    def get_settings(self) -> dict:
        # isHidden(), no isVisible(): este último también es False mientras el panel
        # entero está oculto (otra pestaña), y la casilla se leería como desmarcada.
        return {
            "keep_alpha": not self.chk_alpha.isHidden() and self.chk_alpha.isChecked(),
            "keep_audio": self.chk_audio.isChecked(),
            "depth_16bit": self.is_16bit(),
        }
