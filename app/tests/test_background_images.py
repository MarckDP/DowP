"""Imagen de fondo: copia de la imagen (transparencia, animadas, tamaño), modos de
ajuste y paneles translúcidos. Nada escribe en la config real ni en AppData."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("DOWP_NO_FILE_LOG", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtWidgets import QApplication, QFrame, QLineEdit, QPushButton, QWidget

app = QApplication.instance() or QApplication([])

from core.utils import background_images as bg
from gui import styles
from gui.widgets.background_canvas import target_rect


class _Sandbox(unittest.TestCase):
    """Config en memoria y carpeta de fondos temporal."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = {}
        self._patches = [
            patch.object(bg, "get_config", lambda: self.config),
            patch.object(bg, "save_config", lambda c: None),
            patch.object(bg, "backgrounds_dir", lambda: self.tmp.name),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.tmp.cleanup()

    def _img(self, name, mode="RGB", size=(200, 100), color=(200, 30, 30), **kw):
        path = os.path.join(self.tmp.name, "src_" + name)
        Image.new(mode, size, color).save(path, **kw)
        return path


class ImportTests(_Sandbox):
    def test_png_with_transparency_stays_png_with_alpha(self):
        path = os.path.join(self.tmp.name, "src_char.png")
        im = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
        im.paste((255, 0, 0, 255), (25, 25, 75, 75))
        im.save(path)
        name, animated = bg.import_image(bg.PLACE_GENERAL, path)
        self.assertFalse(animated)
        self.assertTrue(name.endswith(".png"))
        with Image.open(bg.image_path(bg.PLACE_GENERAL)) as out:
            self.assertEqual(out.mode, "RGBA")
            self.assertEqual(out.getpixel((0, 0))[3], 0)
            self.assertEqual(out.getpixel((50, 50))[3], 255)

    def test_opaque_alpha_channel_is_saved_as_jpeg(self):
        name, _ = bg.import_image(bg.PLACE_GENERAL, self._img("opaque.png", "RGBA", color=(1, 2, 3, 255)))
        self.assertTrue(name.endswith(".jpg"))

    def test_animated_gif_uses_first_frame(self):
        path = os.path.join(self.tmp.name, "src_anim.gif")
        frames = [Image.new("RGB", (60, 40), c) for c in ((255, 0, 0), (0, 255, 0), (0, 0, 255))]
        frames[0].save(path, save_all=True, append_images=frames[1:], duration=100, loop=0)
        _name, animated = bg.import_image(bg.PLACE_GENERAL, path)
        self.assertTrue(animated)
        with Image.open(bg.image_path(bg.PLACE_GENERAL)) as out:
            r, g, b = out.convert("RGB").getpixel((30, 20))
            self.assertGreater(r, 200)
            self.assertLess(g, 60)

    def test_huge_image_is_reduced(self):
        bg.import_image(bg.PLACE_GENERAL, self._img("big.jpg", size=(8000, 2000)))
        with Image.open(bg.image_path(bg.PLACE_GENERAL)) as out:
            self.assertEqual(max(out.size), bg.MAX_SIDE)
            self.assertAlmostEqual(out.size[0] / out.size[1], 4.0, places=1)

    def test_replacing_removes_old_copy_and_remove_clears(self):
        bg.import_image(bg.PLACE_GENERAL, self._img("a.jpg"))
        first = bg.image_path(bg.PLACE_GENERAL)
        bg.import_image(bg.PLACE_GENERAL, self._img("b.jpg", color=(0, 0, 200)))
        self.assertFalse(os.path.exists(first))
        bg.remove_image(bg.PLACE_GENERAL)
        self.assertIsNone(bg.image_path(bg.PLACE_GENERAL))
        self.assertEqual([f for f in os.listdir(self.tmp.name) if not f.startswith("src_")], [])

    def test_settings_are_sanitized(self):
        self.config["background_images"] = {"general": {"opacity": 500, "fit": "raro", "align": "x"}}
        s = bg.get_place(bg.PLACE_GENERAL)
        self.assertEqual((s["opacity"], s["fit"], s["align"]), (100, bg.FIT_FILL, "center-center"))

    def test_glass_alpha_only_with_image(self):
        self.assertIsNone(bg.glass_alpha())
        bg.import_image(bg.PLACE_GENERAL, self._img("c.jpg"))
        self.assertAlmostEqual(bg.glass_alpha(), bg.DEFAULT_PANEL_OPACITY / 100)
        bg.set_panel_opacity(100)
        self.assertIsNone(bg.glass_alpha())  # paneles al 100 %: nada que tocar
        bg.set_panel_opacity(5)
        self.assertEqual(bg.get_panel_opacity(), bg.MIN_PANEL_OPACITY)


class BlurTests(unittest.TestCase):
    """La copia desenfocada se calcula reducida (era la demora al abrir el primer panel
    flotante) pero conserva el tamaño lógico y la transparencia del original."""

    def test_blurred_copy_is_small_but_keeps_logical_size_and_alpha(self):
        from gui.widgets.background_canvas import _load_image
        tmp = tempfile.TemporaryDirectory()
        jpg = os.path.join(tmp.name, "foto.jpg")
        Image.new("RGB", (3840, 2400), (200, 40, 40)).save(jpg)
        png = os.path.join(tmp.name, "personaje.png")
        im = Image.new("RGBA", (1600, 2000), (0, 0, 0, 0)); im.paste((10, 200, 10, 255), (400, 400, 1200, 1600)); im.save(png)
        for path, (w, h) in ((jpg, (3840, 2400)), (png, (1600, 2000))):
            img = _load_image(path, True, 60)
            self.assertLessEqual(max(img.width(), img.height()), 60 * 8)
            self.assertAlmostEqual(img.width() / img.devicePixelRatio(), w, delta=2)
            self.assertAlmostEqual(img.height() / img.devicePixelRatio(), h, delta=4)
        img = _load_image(png, True, 60)
        self.assertEqual(img.pixelColor(2, 2).alpha(), 0)  # el borde transparente sigue transparente
        tmp.cleanup()


class TargetRectTests(unittest.TestCase):
    def test_modes(self):
        r = target_rect(200, 100, 400, 400, bg.FIT_FILL, "center-center")
        self.assertEqual((r.width(), r.height(), r.x(), r.y()), (800, 400, -200, 0))
        r = target_rect(200, 100, 400, 400, bg.FIT_FIT, "center-center")
        self.assertEqual((r.width(), r.height(), r.x(), r.y()), (400, 200, 0, 100))
        r = target_rect(200, 100, 400, 400, bg.FIT_STRETCH, "top-left")
        self.assertEqual((r.width(), r.height()), (400, 400))
        r = target_rect(200, 100, 400, 400, bg.FIT_ORIGINAL, "bottom-right")
        self.assertEqual((r.x(), r.y(), r.width(), r.height()), (200, 300, 200, 100))
        r = target_rect(200, 100, 400, 400, bg.FIT_FILL, "center-left")  # recorte: queda la izquierda
        self.assertEqual(r.x(), 0)

    def test_degenerate(self):
        self.assertTrue(target_rect(0, 100, 400, 400, bg.FIT_FILL, "center-center").isEmpty())


class GlassTests(unittest.TestCase):
    def test_color_transform(self):
        self.assertEqual(styles._glass_color("#1a1b26", 0.5), "rgba(26, 27, 38, 128)")
        self.assertEqual(styles._glass_color("rgba(255, 255, 255, 0.08)", 0.5), "rgba(255, 255, 255, 10)")
        self.assertEqual(styles._glass_color("rgba(10, 20, 30, 200)", 0.5), "rgba(10, 20, 30, 100)")
        for keep in ("#000000", "black", "transparent", "none", "url(x.png)"):
            self.assertIsNone(styles._glass_color(keep, 0.5), keep)
        # Degradados: translúcidos parada por parada, sin perder sus colores.
        grad = "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff0000, stop:1 #0000ff)"
        self.assertEqual(styles._glass_color(grad, 0.5, action_alpha=0.85),
                         "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(255, 0, 0, 217), stop:1 rgba(0, 0, 255, 217))")

    def test_selector_classification(self):
        k = styles._glass_kind
        self.assertEqual(k("QFrame#outputOptionsContainer"), "panel")
        self.assertEqual(k("QTabWidget::pane"), "panel")
        self.assertEqual(k("QTreeView"), "panel")
        self.assertEqual(k("QPushButton"), "control")
        self.assertEqual(k("QLineEdit:focus"), "control")
        self.assertEqual(k("QHeaderView::section"), "control")
        self.assertEqual(k("QComboBox"), "control")
        self.assertIsNone(k("QComboBox QAbstractItemView"))      # lista desplegable: otra ventana
        self.assertEqual(k('QPushButton[variant="danger"]'), "control")  # acción: copia propia
        self.assertEqual(k('QPushButton[variant="secondary"]'), "control")
        self.assertIsNone(k("QTreeView::item:selected"))
        self.assertEqual(k("QCheckBox::indicator"), "control")  # pedido del usuario
        self.assertIsNone(k("QSlider::handle"))
        self.assertIsNone(k("QFrame#queueItemCard"))             # tarjetas: sólidas
        self.assertIsNone(k("QFrame#panel QLabel"))
        self.assertIsNone(k("QMenu::item"))
        self.assertEqual(k("#algo"), "unknown")

    def test_control_alpha_formula(self):
        self.assertAlmostEqual(styles.glass_alpha_for("control", 0.5), 0.7)
        self.assertAlmostEqual(styles.glass_alpha_for("control", 0.8), 0.88)
        self.assertAlmostEqual(styles.glass_alpha_for("control", 0.3), 0.58)
        self.assertAlmostEqual(styles.glass_alpha_for("nested", 0.5), 0.15)
        self.assertAlmostEqual(styles.glass_alpha_for("frosted", 0.5), 0.5)

    def test_no_image_changes_nothing(self):
        with patch("core.utils.background_images.glass_alpha", return_value=None):
            qss = "QFrame { background-color: #123456; }"
            self.assertEqual(styles.apply_glass(qss, QFrame()), qss)
            self.assertEqual(styles.glass_main_rules(qss), "")

    def test_widget_rules_by_kind(self):
        from PySide6.QtWidgets import QCheckBox
        canvas = QWidget(); canvas.setObjectName(styles.GLASS_CANVAS_NAME)
        panel = QFrame(canvas); button = QPushButton(canvas); field = QLineEdit(canvas)
        outside = QFrame()  # p. ej. un diálogo
        solid = QFrame(canvas); solid.setObjectName("queueItemCard")
        check = QCheckBox(canvas)
        with patch("core.utils.background_images.glass_alpha", return_value=0.5):
            styles._glass_forget()
            self.assertIn("rgba(18, 52, 86, 128)", styles.apply_glass("background-color: #123456;", panel))
            ctrl = round(255 * 0.7)
            self.assertIn(f"rgba(18, 52, 86, {ctrl})", styles.apply_glass("background-color: #123456;", button))
            self.assertIn(f"rgba(18, 52, 86, {ctrl})", styles.apply_glass("background: #123456;", field))
            for w in (outside, solid):
                self.assertEqual(styles.apply_glass("background-color: #123456;", w), "background-color: #123456;")
            self.assertIn(f"rgba(18, 52, 86, {ctrl})", styles.apply_glass("background-color: #123456;", check))
            mixed = "QFrame#x { background-color: #123456; } QPushButton { background-color: #123456; }"
            out = styles.apply_glass(mixed, panel)
            self.assertIn("QFrame#x { background-color: rgba(18, 52, 86, 128); }", out)
            self.assertIn(f"QPushButton {{ background-color: rgba(18, 52, 86, {ctrl}); }}", out)

    def test_action_colors_stronger_and_tints_untouched_in_controls(self):
        from PySide6.QtGui import QColor
        canvas = QWidget(); canvas.setObjectName(styles.GLASS_CANVAS_NAME)
        button = QPushButton(canvas)
        accent = QColor(styles.get_theme_token("acento_primario", "#B9E640"))
        action = round(255 * 0.85)  # paneles al 50 % -> acción al 85 %
        with patch("core.utils.background_images.glass_alpha", return_value=0.5):
            styles._glass_forget()
            self.assertIn(f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, {action})",
                          styles.apply_glass(f"background-color: {accent.name()};", button))
            grad = f"background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {accent.name()}, stop:1 #102030);"
            self.assertIn(f"stop:1 rgba(16, 32, 48, {action})", styles.apply_glass(grad, button))
            tint = "background-color: rgba(187, 154, 247, 60);"
            self.assertEqual(styles.apply_glass(tint, button), tint)  # ya trae su transparencia

    def test_alternate_rows_get_lower_alpha(self):
        body = "background-color: #101010; alternate-background-color: #202020;"
        out = styles._glass_body(body, 0.5)
        self.assertIn("background-color: rgba(16, 16, 16, 128)", out)
        self.assertIn(f"alternate-background-color: rgba(32, 32, 32, {round(255 * 0.5 * 0.35)})", out)

    def test_main_rules_are_scoped_to_canvas_and_marks(self):
        qss = ("QFrame#outputOptionsContainer { background-color: #181818; border: 1px solid #333; }\n"
               "QPushButton { background-color: #181818; }\n"
               'QPushButton[variant="danger"] { background-color: #ff0000; }\n'
               "QFrame#videoContainer { background-color: #000000; }\n"
               "QFrame#detailsBox:hover { background-color: #202020; }\n"
               "QComboBox QAbstractItemView { background-color: #222222; }\n"
               "QFrame#resizePopover { background-color: #222222; }\n"
               'QFrame#collapsiblePanel[dockMode="overlay"] { background-color: #222222; }\n'
               "QTreeView, QListView { background: #121212; }")
        with patch("core.utils.background_images.glass_alpha", return_value=0.8):
            extra = styles.glass_main_rules(qss)
        self.assertIn('QWidget#dowpCanvas QFrame#outputOptionsContainer[glass="outer"] '
                      '{ background-color: rgba(24, 24, 24, 204); }', extra)
        self.assertIn('QWidget#dowpCanvas QFrame#outputOptionsContainer[glass="nested"] '
                      '{ background-color: rgba(24, 24, 24, 61); }', extra)  # 0.8 x 0.3
        self.assertIn('QWidget#dowpCanvas QPushButton[glass="control"] '
                      f'{{ background-color: rgba(24, 24, 24, {round(255 * 0.88)}); }}', extra)
        # Las reglas más específicas también tienen su copia (si no, la copia de la
        # regla general de botones les ganaba y se perdían degradados y colores).
        self.assertIn('QPushButton[variant="danger"][glass="control"]', extra)
        self.assertIn('QFrame#videoContainer[glass="outer"] { background-color: #000000; }', extra)  # copia igual
        self.assertIn('QFrame#resizePopover[glass="frosted"]', extra)
        self.assertIn('QFrame#collapsiblePanel[dockMode="overlay"][glass="frosted"]', extra)
        self.assertIn('QFrame#detailsBox[glass="outer"]:hover', extra)
        self.assertIn('QWidget#dowpCanvas QTreeView[glass="outer"], QWidget#dowpCanvas QListView[glass="outer"]', extra)
        self.assertIn("QWidget#dowpCanvas QHeaderView { background: transparent; }", extra)
        self.assertNotIn("QAbstractItemView", extra)
        self.assertIn("outputOptionsContainer", styles._GLASS_MAIN["names"])
        self.assertIn("QTreeView", styles._GLASS_MAIN["types"])

    def test_refresh_glass_reapplies_after_parenting(self):
        canvas = QWidget(); canvas.setObjectName(styles.GLASS_CANVAS_NAME)
        with patch("core.utils.background_images.glass_alpha", return_value=0.5):
            panel = QFrame()  # creado sin padre, como las pestañas
            styles.set_themed_style(panel, lambda: "QFrame { background-color: #123456; }")
            self.assertNotIn("rgba", panel.styleSheet())
            panel.setParent(canvas)
            self.assertEqual(styles.refresh_glass(canvas), 1)
            self.assertIn("rgba(18, 52, 86, 128)", panel.styleSheet())
        with patch("core.utils.background_images.glass_alpha", return_value=None):
            styles.refresh_glass(canvas)  # se quita la imagen: vuelve a ser sólido
            self.assertEqual(panel.styleSheet(), "QFrame { background-color: #123456; }")


class FrostedTests(unittest.TestCase):
    """Vidrio recortado con el lienzo real: el popover muestra la imagen esmerilada que
    tiene detrás, no lo que tapa."""

    def test_popover_shows_backdrop_not_what_is_below(self):
        from PySide6.QtGui import QImage
        from PySide6.QtWidgets import QVBoxLayout
        from gui.widgets.background_canvas import BackgroundCanvas
        tmp = tempfile.TemporaryDirectory()
        Image.new("RGB", (400, 300), (255, 0, 0)).save(os.path.join(tmp.name, "rojo.png"))
        config = {"background_images": {"general": {"file": "rojo.png", "opacity": 100, "fit": "stretch"}},
                  "background_panel_opacity": 50}
        with patch.object(bg, "get_config", lambda: config), patch.object(bg, "backgrounds_dir", lambda: tmp.name):
            canvas = BackgroundCanvas(); canvas.setObjectName(styles.GLASS_CANVAS_NAME)
            QVBoxLayout(canvas)
            canvas.resize(400, 300)
            below = QFrame(canvas); canvas.layout().addWidget(below)  # lo que el popover tapa
            below.setStyleSheet("background-color: #00ff00;")
            pop = QFrame(canvas); pop.setObjectName("testPopover"); pop.setGeometry(100, 100, 150, 100)
            styles.set_themed_style(pop, lambda: "QFrame#testPopover { background-color: #0000ff; border-radius: 0px; }")
            styles.refresh_glass(canvas)
            canvas.show(); pop.raise_()
            for _ in range(5):
                app.processEvents()
            shot = QImage(canvas.size(), QImage.Format_ARGB32)
            canvas.render(shot)
            c = shot.pixelColor(175, 150)
            status = styles.glass_status(pop)
        tmp.cleanup()
        self.assertEqual(status, "frosted")
        # Mitad rojo (la imagen de atrás) y mitad azul (su tinte al 50 %); nada del verde que tapa.
        self.assertGreater(c.red(), 90)
        self.assertGreater(c.blue(), 90)
        self.assertLess(c.green(), 40)


class GlassLayoutTests(unittest.TestCase):
    """Capas anidadas, flotantes y ventanas aparte, con widgets reales en layouts."""

    def setUp(self):
        from PySide6.QtWidgets import QVBoxLayout
        self.p = patch("core.utils.background_images.glass_alpha", return_value=0.5)
        self.p.start()
        self.canvas = QWidget(); self.canvas.setObjectName(styles.GLASS_CANVAS_NAME)
        QVBoxLayout(self.canvas)

    def tearDown(self):
        self.p.stop()

    def _panel(self, parent, name=""):
        from PySide6.QtWidgets import QVBoxLayout
        f = QFrame(parent)
        if name:
            f.setObjectName(name)
        if parent.layout() is not None:
            parent.layout().addWidget(f)
        QVBoxLayout(f)
        return f

    def _style(self, w):
        styles.set_themed_style(w, lambda: "QFrame { background-color: #123456; }")

    def test_nested_panels_get_much_lower_opacity(self):
        outer = self._panel(self.canvas); inner = self._panel(outer); deeper = self._panel(inner)
        for w in (outer, inner, deeper):
            self._style(w)
        styles.refresh_glass(self.canvas)
        self.assertEqual(styles.glass_status(outer), "outer")
        self.assertEqual(styles.glass_status(inner), "nested")
        self.assertEqual(styles.glass_status(deeper), "nested")
        self.assertIn("rgba(18, 52, 86, 128)", outer.styleSheet())   # 0.5
        self.assertIn("rgba(18, 52, 86, 38)", inner.styleSheet())    # 0.5 x 0.3
        self.assertEqual(outer.property("glass"), "outer")
        self.assertEqual(inner.property("glass"), "nested")

    def test_transparent_parent_does_not_count_as_layer(self):
        holder = self._panel(self.canvas)  # sin fondo propio
        child = self._panel(holder)
        self._style(child)
        styles.refresh_glass(self.canvas)
        self.assertEqual(styles.glass_status(child), "outer")

    def test_floating_things(self):
        floating = QFrame(self.canvas)  # posicionado a mano, fuera del layout: sólido
        popover = QFrame(self.canvas); popover.setObjectName("resizePopover")  # tampoco está en el layout
        overlay = QFrame(self.canvas); overlay.setProperty("dockMode", "overlay")
        docked = self._panel(self.canvas); docked.setProperty("dockMode", "docked")
        for w in (floating, popover, overlay, docked):
            self._style(w)
        styles.refresh_glass(self.canvas)
        self.assertIsNone(styles.glass_status(floating))
        self.assertNotIn("rgba", floating.styleSheet())
        for w in (popover, overlay):
            self.assertEqual(styles.glass_status(w), "frosted")
            self.assertIn("rgba(18, 52, 86, 128)", w.styleSheet())
            self.assertIn(w, styles._GLASS_FROSTED_HOOKED)
        self.assertEqual(styles.glass_status(docked), "outer")

    def test_controls_inside_panels(self):
        from PySide6.QtWidgets import QCheckBox, QLabel
        outer = self._panel(self.canvas); self._style(outer)
        button = QPushButton(outer); outer.layout().addWidget(button)
        check = QCheckBox(outer); outer.layout().addWidget(check)
        label = QLabel("x", outer); outer.layout().addWidget(label)
        styles.refresh_glass(self.canvas)
        self.assertEqual(styles.glass_status(button), "control")
        self.assertEqual(styles.glass_status(check), "control")
        self.assertIsNone(styles.glass_status(label))
        self.assertEqual(button.property("glass"), "control")

    def test_checkboxes_previews_and_cut_button(self):
        from PySide6.QtWidgets import QCheckBox, QLabel
        from gui.styles import apply_cut_button_style
        outer = self._panel(self.canvas); self._style(outer)
        check = QCheckBox(outer); outer.layout().addWidget(check)
        thumb = QLabel(outer); thumb.setObjectName("thumbnailLabel"); outer.layout().addWidget(thumb)
        cut = QPushButton(outer); outer.layout().addWidget(cut)
        styles.refresh_glass(self.canvas)
        self.assertEqual(styles.glass_status(check), "control")
        self.assertEqual(styles.glass_status(thumb), "nested")  # vista previa: se comporta como panel
        self.assertEqual(styles._glass_kind("QCheckBox::indicator"), "control")
        self.assertEqual(styles._glass_kind("QLabel#thumbnailLabel"), "panel")
        apply_cut_button_style(cut, "normal", shape="square")
        self.assertIn("rgba(", cut.styleSheet())
        apply_cut_button_style(cut, "saved", shape="square")  # estado de color: más fuerte
        bg_line = [l for l in cut.styleSheet().splitlines() if "background-color" in l][0]
        self.assertIn(f", {round(255 * 0.85)})", bg_line)

    def test_glass_fill_for_hand_painted_widgets(self):
        from PySide6.QtGui import QColor
        outer = self._panel(self.canvas); self._style(outer)
        inner = QWidget(outer); outer.layout().addWidget(inner)
        loose = QWidget(self.canvas); self.canvas.layout().addWidget(loose)
        styles.refresh_glass(self.canvas)
        self.assertEqual(styles.glass_fill(loose, "#102030").alpha(), round(255 * 0.5))
        self.assertEqual(styles.glass_fill(inner, "#102030").alpha(), round(255 * 0.5 * 0.3))
        self.assertEqual(styles.glass_fill(inner, "#102030", "control").alpha(), round(255 * 0.7))
        self.assertEqual(styles.glass_fill(QWidget(), "#102030").alpha(), 255)  # fuera del lienzo
        with patch("core.utils.background_images.glass_alpha", return_value=None):
            styles._glass_forget()
            self.assertEqual(styles.glass_fill(loose, QColor("#102030")).alpha(), 255)
        styles._glass_forget()

    def test_splitter_children_are_not_floating(self):
        from PySide6.QtWidgets import QSplitter
        split = QSplitter(self.canvas); self.canvas.layout().addWidget(split)
        a = QFrame(); split.addWidget(a)
        self.assertFalse(styles._is_floating(a))

    def test_popup_window_is_outside_the_canvas(self):
        """Como la lista de un combo: una ventana emergente cuyo padre está en el lienzo."""
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QVBoxLayout
        popup = QWidget(self.canvas, Qt.Popup)
        QVBoxLayout(popup)
        lst = self._panel(popup)
        self._style(lst)
        styles.refresh_glass(self.canvas)
        self.assertFalse(styles._inside_glass_area(lst))
        self.assertIsNone(styles.glass_status(lst))
        self.assertNotIn("rgba", lst.styleSheet())

    def test_removing_image_clears_marks(self):
        outer = self._panel(self.canvas); self._style(outer)
        styles.refresh_glass(self.canvas)
        self.assertEqual(outer.property("glass"), "outer")
        with patch("core.utils.background_images.glass_alpha", return_value=None):
            styles.refresh_glass(self.canvas)
        self.assertFalse(outer.property("glass"))
        self.assertEqual(outer.styleSheet(), "QFrame { background-color: #123456; }")


if __name__ == "__main__":
    unittest.main()
