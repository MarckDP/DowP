"""Paquetes de tema (.dthmp): un zip con reglas que lleva el tema, sus imágenes y sus fuentes.

    manifest.json           {"tipo": "dowp-tema", "formato": 1}
    tema.json               colores, formas, tipografía y "apariencia"
    imagenes/<nombre>       png, jpg, webp
    fuentes/<nombre>        ttf, otf

Un paquete puede venir de cualquiera, así que al importarlo nada se usa tal cual: lo que no esté
en esa lista exacta rechaza el paquete, los tamaños se miden leyendo (lo que declara el zip puede
mentir), las imágenes se decodifican y se guardan de nuevo, y los valores se validan. DowP nunca
ejecuta nada de lo que hay dentro. Una vez instalado, el archivo original se puede borrar."""
import io
import json
import os
import re
import shutil
import stat
import zipfile
from dataclasses import dataclass, field

from PIL import Image
from PySide6.QtCore import QCoreApplication

from core.logger.logger_manager import logger
from core.utils import appearance_store, background_images as bg
from core.utils import theme_io, theme_loader as TL
from core.utils.config_manager import get_config
from core.utils.font_manager import get_font_file_path
from core.utils.paths import get_user_fonts_dir

EXTENSION = ".dthmp"
PACKAGE_TYPE = "dowp-tema"
PACKAGE_FORMAT = 1

MAX_PACKAGE_BYTES = 200 * 1024 * 1024
MAX_ENTRIES = 16
MAX_JSON_BYTES = 1024 * 1024
MAX_IMAGE_BYTES = 80 * 1024 * 1024
MAX_FONT_BYTES = 30 * 1024 * 1024

_ENTRY_RE = re.compile(r"^(manifest\.json|tema\.json|imagenes/[a-z0-9_]{1,40}\.(png|jpg|jpeg|webp)"
                       r"|fuentes/[A-Za-z0-9_-]{1,80}\.(ttf|otf))$")
_FONT_MAGIC = (b"\x00\x01\x00\x00", b"OTTO", b"true")
_TOP_LEVEL = ("meta", "colores", "formas", "tipografia", "apariencia")
_CHECKED_THEME_IDS = {appearance_store.PREVIOUS_ID}


def _tr(text: str) -> str:
    return QCoreApplication.translate("ThemePackage", text)


def _reject(text: str):
    raise theme_io.ThemeImportError(text)


@dataclass
class PackageContents:
    theme_id: str
    name: str
    data: dict
    report: dict
    images: dict = field(default_factory=dict)  # nombre -> bytes ya vueltos a codificar
    fonts: dict = field(default_factory=dict)   # nombre -> bytes

    @property
    def has_appearance(self) -> bool:
        return isinstance(self.data.get("apariencia"), dict)


# ── Exportar ────────────────────────────────────────────────────────────────
def is_user_font(family: str) -> bool:
    """Las fuentes que trae DowP viajan por nombre; las agregadas por el usuario, no."""
    path = get_font_file_path(family) if family else ""
    if not path:
        return False
    return os.path.normcase(os.path.dirname(os.path.abspath(path))) == os.path.normcase(os.path.abspath(get_user_fonts_dir()))


def active_family(theme_id: str) -> str:
    return (theme_io.build_export(theme_id).get("tipografia") or {}).get("familia", "")


def export_colors_only(theme_id: str, dest: str):
    full = theme_io.build_export(theme_id)
    with open(dest, "w", encoding="utf-8") as f:
        json.dump({"meta": full["meta"], "colores": full["colores"]}, f, ensure_ascii=False, indent=2)


def export_package(theme_id: str, dest: str):
    data = theme_io.build_export(theme_id)
    appearance = appearance_store.capture()
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps({"tipo": PACKAGE_TYPE, "formato": PACKAGE_FORMAT}))
        for place, settings in appearance["places"].items():
            source = bg.image_path(place)
            file_name = place + os.path.splitext(source)[1].lower()
            zf.write(source, f"imagenes/{file_name}")
            settings["file"] = file_name
        family = (data.get("tipografia") or {}).get("familia", "")
        if is_user_font(family):
            source = get_font_file_path(family)
            stem = re.sub(r"[^A-Za-z0-9_-]+", "_", os.path.splitext(os.path.basename(source))[0])[:80] or "fuente"
            zf.write(source, f"fuentes/{stem}{os.path.splitext(source)[1].lower()}")
        data["apariencia"] = appearance
        zf.writestr("tema.json", json.dumps(data, ensure_ascii=False, indent=2))
    logger.info(f"Temas: paquete de '{theme_id}' exportado a {dest}")


# ── Importar ────────────────────────────────────────────────────────────────
def _read_entry(zf: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes:
    """Lee con tope real, sin creer el tamaño que declara el zip."""
    with zf.open(info) as f:
        content = f.read(limit + 1)
    if len(content) > limit:
        _reject(_tr("El paquete contiene un archivo demasiado grande."))
    return content


def _clean_image(name: str, content: bytes) -> tuple:
    """Decodifica de verdad y vuelve a guardar: lo que viniera escondido en el archivo no pasa."""
    try:
        with Image.open(io.BytesIO(content)) as im:
            if im.format not in ("PNG", "JPEG", "WEBP"):
                raise ValueError(im.format)
            im.seek(0)
            has_alpha = im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info)
            frame = im.convert("RGBA" if has_alpha else "RGB")
            out = io.BytesIO()
            frame.save(out, "PNG" if has_alpha else "JPEG", quality=92)
    except Exception:  # archivo corrupto, disfrazado, o tamaño desmedido: Pillow lanza muchas cosas
        _reject(_tr("Una imagen del paquete no es válida."))
    return os.path.splitext(name)[0] + (".png" if has_alpha else ".jpg"), out.getvalue()


def _check_font(content: bytes):
    if not content.startswith(_FONT_MAGIC):
        _reject(_tr("Una fuente del paquete no es válida."))
    from PySide6.QtGui import QFontDatabase
    font_id = QFontDatabase.addApplicationFontFromData(content)
    if font_id == -1:
        _reject(_tr("Una fuente del paquete no es válida."))
    QFontDatabase.removeApplicationFont(font_id)  # se carga de verdad solo al aplicar el tema


def _clean_appearance(raw, images: dict, renamed: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None

    def number(key, low, high, default):
        value = raw.get(key)
        return max(low, min(high, value)) if isinstance(value, int) and not isinstance(value, bool) else default

    size = raw.get("font_size_override")
    family = raw.get("font_family")
    clean = {"panel_opacity": number("panel_opacity", bg.MIN_PANEL_OPACITY, 100, 100),
             "previews_transparent": raw.get("previews_transparent") is True,
             "radius_override": number("radius_override", 0, 14, None),
             "font_size_override": max(8, min(22, size)) if isinstance(size, int) and not isinstance(size, bool) else None,
             "font_family": family[:100] if isinstance(family, str) else None,
             "places": {}}
    places = raw.get("places") if isinstance(raw.get("places"), dict) else {}
    for place in bg.PLACES:
        settings = places.get(place)
        if not isinstance(settings, dict):
            continue
        file_name = renamed.get(settings.get("file"))
        if file_name not in images:
            continue
        name = settings.get("name")
        clean["places"][place] = {
            "file": file_name, "name": os.path.basename(name)[:200] if isinstance(name, str) else file_name,
            "opacity": _percent(settings.get("opacity")),
            "fit": settings.get("fit") if settings.get("fit") in bg.FITS else bg.FIT_FILL,
            "align": settings.get("align") if settings.get("align") in bg.ALIGNS else "center-center",
            "blur": settings.get("blur") is True}
    return clean


def _percent(value) -> int:
    return max(0, min(100, value)) if isinstance(value, int) and not isinstance(value, bool) else 100


def read_package(path: str) -> PackageContents:
    """Valida todo y lo deja en memoria. No escribe nada: si algo falla, no queda rastro."""
    try:
        if os.path.getsize(path) > MAX_PACKAGE_BYTES:
            _reject(_tr("El paquete es demasiado grande."))
        if not zipfile.is_zipfile(path):
            _reject(_tr("El archivo no es un paquete de tema válido."))
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ENTRIES:
                _reject(_tr("El paquete contiene demasiados archivos."))
            names = [i.filename for i in infos]
            if len(set(n.casefold() for n in names)) != len(names):
                _reject(_tr("El paquete contiene archivos repetidos."))
            for info in infos:
                if not _ENTRY_RE.match(info.filename):
                    _reject(_tr("El paquete contiene un archivo no permitido: {0}").format(info.filename[:80]))
                if stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 0x1:
                    _reject(_tr("El paquete contiene un archivo no permitido: {0}").format(info.filename[:80]))
            if "manifest.json" not in names or "tema.json" not in names:
                _reject(_tr("El archivo no es un paquete de tema válido."))
            by_name = {i.filename: i for i in infos}
            try:
                manifest = json.loads(_read_entry(zf, by_name["manifest.json"], MAX_JSON_BYTES).decode("utf-8"))
                data = json.loads(_read_entry(zf, by_name["tema.json"], MAX_JSON_BYTES).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                _reject(_tr("El archivo no es un paquete de tema válido."))
            if not isinstance(manifest, dict) or manifest.get("tipo") != PACKAGE_TYPE or not isinstance(data, dict):
                _reject(_tr("El archivo no es un paquete de tema válido."))
            version = manifest.get("formato")
            if not isinstance(version, int) or version < 1:
                _reject(_tr("El archivo no es un paquete de tema válido."))
            if version > PACKAGE_FORMAT:
                _reject(_tr("Este paquete se creó con una versión más nueva de DowP."))
            images, fonts, renamed = {}, {}, {}
            for info in infos:
                leaf = info.filename.split("/", 1)[-1]
                if info.filename.startswith("imagenes/"):
                    clean_name, clean = _clean_image(leaf, _read_entry(zf, info, MAX_IMAGE_BYTES))
                    images[clean_name] = clean
                    renamed[leaf] = clean_name
                elif info.filename.startswith("fuentes/"):
                    content = _read_entry(zf, info, MAX_FONT_BYTES)
                    _check_font(content)
                    fonts[leaf] = content
    except OSError as e:
        _reject(_tr("No se pudo leer el archivo: {0}").format(e))
    except zipfile.BadZipFile:
        _reject(_tr("El archivo no es un paquete de tema válido."))

    data = {k: data[k] for k in _TOP_LEVEL if k in data}
    report = theme_io.validate_theme(data)
    if report["valid"] == 0:
        _reject(_tr("El tema no tiene ningún color válido."))
    data["colores"] = {k: v for k, v in data["colores"].items() if k not in report["invalid"]}
    appearance = _clean_appearance(data.pop("apariencia", None), images, renamed)
    if appearance:
        data["apariencia"] = appearance
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    stem = os.path.splitext(os.path.basename(path))[0]
    name = meta["nombre"] if isinstance(meta.get("nombre"), str) and meta["nombre"].strip() else stem
    name = name.strip()[:60]
    data["meta"] = {"nombre": name, "autor": str(meta.get("autor", ""))[:60], "version": str(meta.get("version", "1.0"))[:10],
                    "formato": 2}
    theme_id = theme_io.slugify(name)
    if theme_id in theme_io.builtin_theme_ids() or theme_id in _CHECKED_THEME_IDS:
        theme_id = f"{theme_id}_importado"
    return PackageContents(theme_id, name, data, report, images, fonts)


def install(contents: PackageContents, with_assets: bool = True) -> str:
    """Lo instala en la carpeta de temas. Sin assets queda solo el tema, sin imágenes ni ajustes."""
    data = dict(contents.data)
    final = appearance_store.assets_dir(contents.theme_id)
    shutil.rmtree(final, ignore_errors=True)
    if with_assets and (contents.images or contents.fonts):
        os.makedirs(final)
        for name, content in contents.images.items():
            with open(os.path.join(final, name), "wb") as f:
                f.write(content)
        if contents.fonts:
            os.makedirs(os.path.join(final, appearance_store.FONTS_FOLDER))
            for name, content in contents.fonts.items():
                with open(os.path.join(final, appearance_store.FONTS_FOLDER, name), "wb") as f:
                    f.write(content)
    if not with_assets:
        data.pop("apariencia", None)
    theme_io.save_imported(contents.theme_id, data)
    return contents.theme_id
