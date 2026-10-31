import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QSizePolicy
)
from PySide6.QtCore import Qt, QRect, QPoint, Signal, QPropertyAnimation, QEasingCurve, QEvent
from PySide6.QtGui import QPainter, QPainterPath, QColor, QRegion

from gui.styles import theme_radius
from gui.styles import get_theme_token
from gui.styles import set_themed_style


class TutorialOverlay(QWidget):
    """
    Overlay que oscurece toda la ventana y recorta un "agujero" en la posición
    de un widget objetivo para crear un tutorial interactivo (onboarding).
    """
    
    finished = Signal()

    def __init__(self, parent, steps):
        """
        :param parent: QWidget principal sobre el que se dibujará (usualmente MainWindow).
        :param steps: Lista de diccionarios con la estructura:
                      {
                          "widgets": [QWidget, ...], # Lista de widgets a resaltar simultáneamente
                          "title": "Título del paso",
                          "desc": "Descripción detallada",
                          "on_enter": callable,      # (Opcional) Se llama al entrar al paso
                          "on_leave": callable       # (Opcional) Se llama al salir del paso
                      }
        """
        super().__init__(parent)
        self.steps = steps
        self.current_step_idx = 0
        self.is_skipping = False
        
        self.setObjectName("tutorialOverlay")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        # Asegurar que está por encima de todo
        self.raise_()
        
        if parent:
            parent.installEventFilter(self)
        
        # Tarjeta de información flotante
        self.card = QFrame(self)
        self.card.setObjectName("tutorialCard")
        self.card.setFixedWidth(320)
        
        # Estilos de la tarjeta
        
        set_themed_style(self.card, lambda: f"""
            QFrame#tutorialCard {{
                background-color: {get_theme_token('fondo_secundario', '#1e1e1e')};
                border: 2px solid {get_theme_token('acento_primario', '#B9E640')};
                border-radius: 10px;
            }}
            QLabel#tutTitle {{
                color: {get_theme_token('acento_primario', '#B9E640')};
                font-weight: bold;
                font-size: 16px;
                border: none;
            }}
            QLabel#tutDesc {{
                color: {get_theme_token('texto_primario', '#ffffff')};
                font-size: 13px;
                border: none;
            }}
            QLabel#tutCounter {{
                color: {get_theme_token('texto_secundario', '#a0a0a0')};
                font-size: 12px;
                border: none;
            }}
        """)
        
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(12)
        
        self.lbl_title = QLabel()
        self.lbl_title.setObjectName("tutTitle")
        self.lbl_title.setWordWrap(True)
        self.lbl_title.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        
        self.lbl_desc = QLabel()
        self.lbl_desc.setObjectName("tutDesc")
        self.lbl_desc.setWordWrap(True)
        self.lbl_desc.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        
        card_layout.addWidget(self.lbl_title)
        card_layout.addWidget(self.lbl_desc)
        
        # Botones
        buttons_layout = QHBoxLayout()
        
        self.lbl_counter = QLabel()
        self.lbl_counter.setObjectName("tutCounter")
        
        self.btn_skip = QPushButton(self.tr("Omitir"))
        self.btn_skip.setCursor(Qt.PointingHandCursor)
        set_themed_style(self.btn_skip, lambda: (
            f"background: transparent; color: {get_theme_token('texto_gris', '#aaaaaa')}; "
            "border: none; font-weight: bold; text-decoration: underline;"))
        self.btn_skip.clicked.connect(self.finish_tutorial)
        
        self.btn_next = QPushButton(self.tr("Siguiente"))
        self.btn_next.setCursor(Qt.PointingHandCursor)
        set_themed_style(self.btn_next, lambda: f"""
            QPushButton {{
                background-color: {get_theme_token('acento_primario', '#B9E640')};
                color: {get_theme_token('boton_acento_texto', '#000000')};
                border-radius: 4px;
                font-weight: bold;
                padding: 6px 12px;
            }}
            QPushButton:hover {{
                background-color: {get_theme_token('acento_secundario', '#1DC038')};
            }}
        """)
        self.btn_next.clicked.connect(self.next_step)
        
        buttons_layout.addWidget(self.lbl_counter)
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.btn_skip)
        buttons_layout.addWidget(self.btn_next)
        
        card_layout.addLayout(buttons_layout)
        
        # Iniciar primer paso
        self._load_step()

    def eventFilter(self, obj, event):
        if obj == self.parentWidget() and event.type() == QEvent.Resize:
            self.resize(event.size())
            self.update_card_position()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_card_position()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Crear un path que cubra toda la pantalla
        path = QPainterPath()
        path.addRect(self.rect())
        
        # Recortar los agujeros para los widgets del paso actual
        step = self.steps[self.current_step_idx]
        widgets = step.get("widgets", [])
        
        padding = 6
        hole_path = QPainterPath()
        
        for w in widgets:
            if not w or not w.isVisible():
                continue
            # Obtener rectángulo global del widget y mapearlo a nuestras coordenadas
            global_pos = w.mapToGlobal(QPoint(0, 0))
            local_pos = self.mapFromGlobal(global_pos)
            
            w_rect = QRect(local_pos, w.size())
            # Ajustar padding
            w_rect.adjust(-padding, -padding, padding, padding)
            
            hole_path.addRoundedRect(w_rect, theme_radius(8), theme_radius(8))
            
        # Restar los agujeros
        final_path = path.subtracted(hole_path)
        
        # Pintar el overlay semitransparente
        painter.fillPath(final_path, QColor(0, 0, 0, 200))
        
        # Dibujar un borde alrededor de los agujeros para resaltarlos más
        painter.setPen(QColor(get_theme_token("acento_primario", "#B9E640")))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(hole_path)

    def mousePressEvent(self, event):
        # Bloquear clics fuera de la tarjeta para que el usuario no interactúe con el fondo
        event.accept()

    def next_step(self):
        if self.current_step_idx < len(self.steps):
            step = self.steps[self.current_step_idx]
            if "on_leave" in step and callable(step.get("on_leave")):
                step["on_leave"]()
            
        self.current_step_idx += 1
        
        if self.current_step_idx >= len(self.steps):
            self.finish_tutorial()
        else:
            self._load_step()

    def finish_tutorial(self):
        self.is_skipping = True
        if self.current_step_idx < len(self.steps):
            step = self.steps[self.current_step_idx]
            if "on_leave" in step and callable(step.get("on_leave")):
                step["on_leave"]()
            
        self.finished.emit()
        self.deleteLater()

    def _load_step(self):
        step = self.steps[self.current_step_idx]
        
        if "on_enter" in step and callable(step["on_enter"]):
            step["on_enter"]()
            
        self.lbl_title.setText(step.get("title", ""))
        self.lbl_desc.setText(step.get("desc", ""))
        
        current = self.current_step_idx + 1
        total = len(self.steps)
        self.lbl_counter.setText(f"{current} / {total}")
        
        if self.current_step_idx == len(self.steps) - 1:
            self.btn_next.setText(self.tr("Finalizar"))
            self.btn_skip.hide()
        else:
            self.btn_next.setText(self.tr("Siguiente"))
            self.btn_skip.show()

        # Liberar cualquier restricción previa
        self.card.setMinimumHeight(0)
        self.card.setMaximumHeight(16777215)
        self.lbl_title.setMinimumHeight(0)
        self.lbl_desc.setMinimumHeight(0)

        # Forzar que el layout recalcule los tamaños con el texto nuevo -- SIN
        # bombear el event loop. QApplication.processEvents() aqui colgaba la
        # app: _load_step() corre desde __init__(), y la primera vez que se ve
        # un tutorial (flags "*_seen" en False) eso pasa durante la construccion
        # inicial de MainWindow, antes de que la ventana exista de verdad --
        # procesar eventos ahi reentra en pintado/resize de un arbol de widgets
        # a medio construir y puede quedarse colgado sin excepcion ni log.
        self.card.layout().invalidate()
        self.card.layout().activate()

        self.card.adjustSize()
        self.update()
        self.update_card_position()

    def update_card_position(self):
        step = self.steps[self.current_step_idx]
        widgets = step.get("widgets", [])
        
        if not widgets:
            # Centrar en pantalla
            self.card.move((self.width() - self.card.width()) // 2, (self.height() - self.card.height()) // 2)
            return
            
        # Posicionar cerca del primer widget
        w = widgets[0]
        global_pos = w.mapToGlobal(QPoint(0, 0))
        local_pos = self.mapFromGlobal(global_pos)
        
        w_rect = QRect(local_pos, w.size())
        
        # Intentar poner la tarjeta debajo
        card_x = w_rect.center().x() - (self.card.width() // 2)
        card_y = w_rect.bottom() + 15
        
        # Si se sale por abajo, intentar arriba
        if card_y + self.card.height() > self.height():
            card_y = w_rect.top() - self.card.height() - 15
            
        # Ajustar X si se sale de la pantalla
        if card_x < 10:
            card_x = 10
        elif card_x + self.card.width() > self.width() - 10:
            card_x = self.width() - self.card.width() - 10
            
        # Ajustar Y si se sale de la pantalla (arriba o abajo)
        if card_y < 10:
            card_y = 10
        elif card_y + self.card.height() > self.height() - 10:
            card_y = self.height() - self.card.height() - 10
            
        self.card.move(card_x, card_y)
