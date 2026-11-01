"""Paquetes de tema (.dthmp): un zip con reglas que lleva el tema, sus imágenes y sus fuentes.

    manifest.json           {"tipo": "dowp-tema", "formato": 1}
    tema.json               colores, formas, tipografía y "apariencia"
    imagenes/<nombre>       png, jpg, webp
    fuentes/<nombre>        ttf, otf

Un paquete puede venir de cualquiera, así que al importarlo nada se usa tal cual: lo que no esté
en esa lista exacta rechaza el paquete, los tamaños se miden leyendo (lo que declara el zip puede
mentir), de las imágenes solo pasan los píxeles, y los valores se validan. DowP nunca
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
# Lo que entrega DowP al exportar: un paquete para compartir. Importar sigue admitiendo más.
SHARE_LIMIT_BYTES = 20 * 1024 * 1024
# (calidad, lado máximo del fondo). Primero la calidad, que casi no se nota; la resolución al final.
_SHARE_STEPS = ((None, None), (bg.IMAGE_QUALITY, None), (85, None), (75, None), (75, 2560), (75, 1920))

_ENTRY_RE = re.compile(r"^(manifest\.json|tema\.json|imagenes/[a-z0-9_]{1,40}\.(png|jpg|jpeg|webp)"
                       r"|fuentes/[A-Za-z0-9_-]{1,80}\.(ttf|otf))$")
_FONT_MAGIC = (b"\x00\x01\x00\x00", b"OTTO", b"true")


def _tr(text: str) -> str:
    return QCoreApplication.translate("ThemePackage", text)


def _reject(text: str):
    raise theme_io.ThemeImportError(text)


class PackageTooLarge(OSError):
    """Ni comprimiendo las imágenes cabe en SHARE_LIMIT_BYTES: lo que ocupa son las fuentes."""

    def __init__(self, fonts_bytes: int):
        super().__init__(_tr("El paquete no cabe en el límite de tamaño."))
        self.fonts_bytes = fonts_bytes


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


def _image_for_package(place: str, source: str, quality, side) -> tuple[bytes, str]:
    """quality None: la copia tal cual si respeta los tamaños, para no comprimirla otra vez."""
    with Image.open(source) as im:
        limit = min(side or bg.max_side(place), bg.max_side(place))
        if quality is None and max(im.size) <= limit:
            with open(source, "rb") as f:
                return f.read(), os.path.splitext(source)[1].lower()
        frame = bg.prepare_frame(im, limit)
    return bg.encode_frame(frame, quality or bg.IMAGE_QUALITY)


def _build_package(data: dict, appearance: dict, sources: dict, fonts: dict, quality, side) -> bytes:
    data, appearance = dict(data), dict(appearance, places={p: dict(s) for p, s in appearance["places"].items()})
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps({"tipo": PACKAGE_TYPE, "formato": PACKAGE_FORMAT}))
        for place, source in sources.items():
            content, extension = _image_for_package(place, source, quality, side)
            file_name = place + extension
            zf.writestr(f"imagenes/{file_name}", content)
            appearance["places"][place]["file"] = file_name
        for name, content in fonts.items():
            zf.writestr(f"fuentes/{name}", content)
        data["apariencia"] = appearance
        zf.writestr("tema.json", json.dumps(data, ensure_ascii=False, indent=2))
    return out.getvalue()


def export_package(theme_id: str, dest: str, with_fonts: bool = True) -> int:
    """Escribe un paquete que no pasa de SHARE_LIMIT_BYTES y devuelve cuánto pesa. Tus imágenes y
    tu tema no cambian: lo que se comprime es lo que va en el paquete."""
    data = theme_io.build_export(theme_id)
    appearance = appearance_store.capture()
    sources = {place: bg.image_path(place) for place in appearance["places"]}
    fonts = {}
    family = (data.get("tipografia") or {}).get("familia", "")
    if with_fonts and is_user_font(family):
        source = get_font_file_path(family)
        stem = re.sub(r"[^A-Za-z0-9_-]+", "_", os.path.splitext(os.path.basename(source))[0])[:80]
        with open(source, "rb") as f:
            fonts[f"{stem}{os.path.splitext(source)[1].lower()}"] = f.read()
    for quality, side in _SHARE_STEPS:
        package = _build_package(data, appearance, sources, fonts, quality, side)
        if len(package) <= SHARE_LIMIT_BYTES:
            with open(dest, "wb") as f:
                f.write(package)
            logger.info(f"Temas: paquete de '{theme_id}' exportado a {dest} ({len(package)} bytes, calidad {quality}, lado {side})")
            return len(package)
    raise PackageTooLarge(sum(len(c) for c in fonts.values()))


# ── Importar ────────────────────────────────────────────────────────────────
def _read_entry(zf: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes:
    """Lee con tope real, sin creer el tamaño que declara el zip."""
    with zf.open(info) as f:
        content = f.read(limit + 1)
    if len(content) > limit:
        _reject(_tr("El paquete contiene un archivo demasiado grande."))
    return content


def _clean_jpeg(content: bytes) -> bytes | None:
    """El JPEG sin metadatos ni nada tras la imagen, sin tocar sus píxeles. None si no se puede
    asegurar. Se conservan JFIF y Adobe, que indican cómo interpretar los colores."""
    if content[:2] != b"\xff\xd8":
        return None
    out, pos = bytearray(b"\xff\xd8"), 2
    while True:
        if content[pos:pos + 1] != b"\xff" or pos + 4 > len(content):
            return None
        marker = content[pos + 1]
        length = int.from_bytes(content[pos + 2:pos + 4], "big")
        if length < 2 or pos + 2 + length > len(content):
            return None
        if marker == 0xDA:  # los datos de la imagen: terminan en el primer EOI, y ahí debe acabar
            end = content.find(b"\xff\xd9", pos)
            return bytes(out + content[pos:end + 2]) if end != -1 and end + 2 == len(content) else None
        keep = marker in (0xE0, 0xEE) or not (0xE0 <= marker <= 0xEF or marker == 0xFE)
        if keep:
            out += content[pos:pos + 2 + length]
        pos += 2 + length


def _clean_webp(content: bytes) -> bytes | None:
    """Igual para WebP: solo los bloques de la imagen. None si trae algo más, o animación."""
    if content[:4] != b"RIFF" or content[8:12] != b"WEBP" or int.from_bytes(content[4:8], "little") + 8 != len(content):
        return None
    chunks, pos = [], 12
    while pos < len(content):
        kind, size = content[pos:pos + 4], int.from_bytes(content[pos + 4:pos + 8], "little")
        stop = pos + 8 + size + (size & 1)
        if pos + 8 > len(content) or stop > len(content):
            return None
        if kind in (b"VP8 ", b"VP8L", b"VP8X", b"ALPH"):
            chunks.append([kind, content[pos + 8:pos + 8 + size]])
        elif kind not in (b"EXIF", b"XMP ", b"ICCP"):
            return None
        pos = stop
    body = bytearray()
    for kind, data in chunks:
        if kind == b"VP8X":  # sin los avisos de metadatos que ya no están
            data = bytes([data[0] & 0b00010000]) + data[1:]
        body += kind + len(data).to_bytes(4, "little") + data + (b"\x00" if len(data) & 1 else b"")
    return b"RIFF" + (len(body) + 4).to_bytes(4, "little") + b"WEBP" + bytes(body)


def _already_clean(content: bytes, side: int) -> tuple | None:
    """(contenido, extensión) sin comprimir otra vez, si la imagen ya cumple las reglas: cada vuelta
    le quitaría calidad. Comprueba que se decodifica entera; cualquier duda devuelve None."""
    with Image.open(io.BytesIO(content)) as im:
        kind = im.format
        rotated = im.getexif().get(0x0112, 1) != 1
        animated = getattr(im, "is_animated", False)
        if rotated or animated or max(im.size) > side or im.mode not in ("RGB", "L", "RGBA"):
            return None
    if kind == "JPEG":
        clean, extension = _clean_jpeg(content), ".jpg"
    elif kind == "WEBP":
        clean, extension = _clean_webp(content), ".webp"
    else:
        return None
    if clean is None:
        return None
    with Image.open(io.BytesIO(clean)) as im:
        if im.format != kind:
            return None
        im.load()
    return clean, extension


def _clean_image(name: str, content: bytes) -> tuple:
    """Solo pasan los píxeles: lo que viniera escondido en el archivo se queda fuera. Lo que ya
    cumple las reglas se limpia sin comprimirlo otra vez; lo demás se decodifica y se guarda."""
    stem = os.path.splitext(name)[0]
    side = bg.max_side(stem)
    try:
        with Image.open(io.BytesIO(content)) as im:
            if im.format not in ("PNG", "JPEG", "WEBP"):
                raise ValueError(im.format)
        kept = _already_clean(content, side)
        if kept:
            return stem + kept[1], kept[0]
        with Image.open(io.BytesIO(content)) as im:
            frame = bg.prepare_frame(im, side)
        clean, extension = bg.encode_frame(frame)
    except Exception:  # archivo corrupto, disfrazado, o tamaño desmedido: Pillow lanza muchas cosas
        _reject(_tr("Una imagen del paquete no es válida."))
    return stem + extension, clean


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
             "preview_checker": raw.get("preview_checker") is not False,
             "radius_override": number("radius_override", 0, 14, None),
             "font_size_override": max(8, min(22, size)) if isinstance(size, int) and not isinstance(size, bool) else None,
             "font_family": theme_io.clean_font_name(family) or None,
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
            "file": file_name, "name": theme_io.clean_text(os.path.basename(name), 200) if isinstance(name, str) else file_name,
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

    report = theme_io.validate_theme(data)
    if report["valid"] == 0:
        _reject(_tr("El tema no tiene ningún color válido."))
    raw_appearance = data.get("apariencia")
    data = theme_io.clean_theme_data(data, report)
    data.pop("basado_en", None)  # un paquete trae sus colores completos
    appearance = _clean_appearance(raw_appearance, images, renamed)
    if appearance:
        data["apariencia"] = appearance
    stem = os.path.splitext(os.path.basename(path))[0]
    name = data["meta"]["nombre"] or theme_io.clean_text(stem, 60)
    data["meta"]["nombre"] = name
    theme_id = theme_io.slugify(name)
    if theme_id in theme_io.builtin_theme_ids():
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
