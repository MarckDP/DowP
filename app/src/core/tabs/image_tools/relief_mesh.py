# src/core/tabs/image_tools/relief_mesh.py
"""Malla 3D (.obj) a partir de un Mapa de Profundidad -- opción "Exportar malla 3D" del
popover de profundidad (ver DepthPopoverContent). Dos tipos:

  - Relieve (export_relief, cualquier modelo): una lámina del tamaño de la imagen empujada
    hacia adelante según la profundidad (el típico efecto 2.5D para parallax). Los modelos
    de profundidad relativa no dan escala ni cámara, así que la "Intensidad" es a ojo.
  - Escena 3D (export_scene, solo MoGe-2): cada píxel va a su posición 3D real, en metros,
    vista desde la cámara (que queda en el origen). MoGe-2 estima la cámara y la escala por
    su cuenta (ver normal_engine.moge_outputs).

Qué se escribe, junto a la imagen de salida (ver mesh_paths):
  - <nombre>_relieve.obj / <nombre>_escena.obj: vértices, coordenadas de textura y caras;
  - el .mtl con el mismo nombre: un material con la textura;
  - <nombre>_..._textura.png: la imagen que vio el modelo (con su alfa si lo tenía).

Ejes: Y arriba, y lo que está delante de la cámara hacia -Z en la escena (la cámara mira
hacia -Z, como en Blender) y hacia +Z en el relieve (la lámina mira hacia quien la ve). Es
lo que esperan Blender (importador OBJ con sus ejes por defecto) y After Effects. La lámina
del relieve mide 2 unidades de ancho, como el plano por defecto de Blender.

Los vértices y las caras se arman con numpy de una vez (sin bucles por píxel) y se
escriben con np.savetxt: con densidad Alta (1024 px) son ~700 mil vértices."""
import os

import numpy as np
from PIL import Image

# Lado mayor de la cuadrícula de vértices según la densidad. La textura va siempre a
# resolución completa, así que una malla más gruesa se sigue viendo nítida.
RELIEF_DENSITY = {"low": 256, "medium": 512, "high": 1024}
# Cuánto sale hacia adelante lo más cercano, en fracción del ancho de la lámina.
RELIEF_STRENGTH = {"soft": 0.10, "medium": 0.25, "strong": 0.50}
# "Separar en los bordes" del relieve: no se crean caras en un cuadro cuya profundidad
# (0..1) cambia más que esto entre sus esquinas. Un degradado normal cambia muy poco por
# cuadro; el salto entre una persona y la pared de atrás, bastante más.
_EDGE_JUMP = 0.08
# Lo mismo en la escena, pero relativo a la distancia (más lejos, más separación entre
# vértices vecinos): se corta si la z más lejana del cuadro supera a la más cercana en
# esta fracción por cada píxel de la cuadrícula de MoGe que abarca el cuadro.
_SCENE_EDGE_RTOL = 0.03
_PLANE_WIDTH = 2.0


def mesh_paths(output_path: str, kind: str = "relieve") -> tuple[str, str, str]:
    """(.obj, .mtl, textura) junto a `output_path`; kind es "relieve" o "escena". Se le
    quita el "_depth" que le pone ImageConvertWorker al mapa: "foto_depth.png" ->
    "foto_relieve.obj"."""
    folder = os.path.dirname(output_path)
    stem = os.path.splitext(os.path.basename(output_path))[0]
    if stem.endswith("_depth"):
        stem = stem[:-len("_depth")]
    base = os.path.join(folder, f"{stem}_{kind}")
    return base + ".obj", base + ".mtl", base + "_textura.png"


def _grid_size(width: int, height: int, density: str) -> tuple[int, int]:
    longest = min(RELIEF_DENSITY.get(density, RELIEF_DENSITY["medium"]), max(width, height))
    scale = longest / max(width, height)
    return max(2, round(width * scale)), max(2, round(height * scale))


def _corners(a: np.ndarray) -> np.ndarray:
    """Las 4 esquinas de cada cuadro de la cuadrícula: arriba-izq., arriba-der.,
    abajo-izq., abajo-der."""
    return np.stack([a[:-1, :-1], a[:-1, 1:], a[1:, :-1], a[1:, 1:]])


def _alpha_keep(texture: Image.Image, grid_w: int, grid_h: int) -> np.ndarray:
    """Cuadros con las 4 esquinas visibles según el alfa de la textura (el recorte de
    Eliminar Fondo): así la malla sale solo con el sujeto."""
    if texture.mode not in ("RGBA", "LA", "PA"):
        return np.ones((grid_h - 1, grid_w - 1), dtype=bool)
    alpha = np.asarray(texture.getchannel("A").resize((grid_w, grid_h), Image.Resampling.BILINEAR)) >= 128
    return _corners(alpha).all(axis=0)


def _write_mesh(positions: np.ndarray, uu: np.ndarray, vv: np.ndarray, keep: np.ndarray,
                texture: Image.Image, output_path: str, kind: str) -> str:
    """Escribe .obj + .mtl + textura. positions: (alto, ancho, 3) de la cuadrícula; uu/vv:
    (alto, ancho) con la posición en la imagen (0..1, vv = 0 arriba); keep: (alto-1,
    ancho-1), qué cuadros llevan caras."""
    if not keep.any():
        raise ValueError("no quedó ninguna superficie para la malla (¿la imagen es toda transparente o cielo?)")
    obj_path, mtl_path, tex_path = mesh_paths(output_path, kind)
    grid_h, grid_w = uu.shape

    # Índices de las esquinas de cada cuadro (a b / c d), dos triángulos en sentido
    # antihorario vistos desde +Z: (a, c, d) y (a, d, b). En los dos tipos quien mira está
    # del lado +Z (delante de la lámina, o en la cámara, en el origen), así que miran hacia él.
    index = np.arange(grid_w * grid_h).reshape(grid_h, grid_w)
    a, b, c, d = (q[keep] for q in _corners(index))
    faces = np.concatenate([np.stack([a, c, d], axis=1), np.stack([a, d, b], axis=1)])

    # Solo los vértices que usa alguna cara, renumerados desde 1 (así se cuenta en OBJ).
    used = np.zeros(grid_w * grid_h, dtype=bool)
    used[faces.ravel()] = True
    remap = np.cumsum(used) * used
    faces = remap[faces]
    positions = positions.reshape(-1, 3)[used]
    uvs = np.stack([uu.ravel(), 1.0 - vv.ravel()], axis=1)[used]     # en OBJ la V crece hacia arriba

    texture.save(tex_path, "PNG")
    with open(mtl_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# DowP -- malla 3D ({kind})\nnewmtl {kind}\nKa 1 1 1\nKd 1 1 1\nKs 0 0 0\nillum 1\n")
        f.write(f"map_Kd {os.path.basename(tex_path)}\n")
    with open(obj_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# DowP -- malla 3D ({kind}, {grid_w}x{grid_h})\n")
        f.write(f"mtllib {os.path.basename(mtl_path)}\no {kind}\n")
        np.savetxt(f, positions, fmt="v %.5f %.5f %.5f")
        np.savetxt(f, uvs, fmt="vt %.5f %.5f")
        f.write(f"usemtl {kind}\ns 1\n")
        np.savetxt(f, np.repeat(faces, 2, axis=1), fmt="f %d/%d %d/%d %d/%d")
    return obj_path


def export_relief(near: np.ndarray, texture: Image.Image, output_path: str, options: dict) -> str:
    """Relieve de `near` (mapa 2D float 0..1, cerca = 1, a cualquier tamaño) con `texture`
    encima. options: depth_relief_strength ("soft"/"medium"/"strong"),
    depth_relief_density ("low"/"medium"/"high"), depth_relief_split (bool). Devuelve la
    ruta del .obj."""
    grid_w, grid_h = _grid_size(texture.width, texture.height, options.get("depth_relief_density", "medium"))
    strength = RELIEF_STRENGTH.get(options.get("depth_relief_strength", "medium"), RELIEF_STRENGTH["medium"])

    depth = np.asarray(Image.fromarray(np.ascontiguousarray(near, dtype=np.float32)).resize(
        (grid_w, grid_h), Image.Resampling.BICUBIC), dtype=np.float32).clip(0.0, 1.0)

    # La lámina va de -1 a 1 en X y conserva la proporción de la imagen en Y.
    plane_h = _PLANE_WIDTH * texture.height / texture.width
    uu, vv = np.meshgrid(np.linspace(0.0, 1.0, grid_w, dtype=np.float32),
                         np.linspace(0.0, 1.0, grid_h, dtype=np.float32))   # fila 0 = arriba
    positions = np.stack([(uu - 0.5) * _PLANE_WIDTH, (0.5 - vv) * plane_h,
                          depth * strength * _PLANE_WIDTH], axis=-1)

    keep = _alpha_keep(texture, grid_w, grid_h)
    if options.get("depth_relief_split", False):
        quad = _corners(depth)
        keep &= (quad.max(axis=0) - quad.min(axis=0)) <= _EDGE_JUMP
    return _write_mesh(positions, uu, vv, keep, texture, output_path, "relieve")


def export_scene(points: np.ndarray, mask: np.ndarray, texture: Image.Image, output_path: str,
                 options: dict) -> str:
    """Escena 3D de MoGe-2. points: (alto, ancho, 3) en metros, ejes de cámara OpenCV (x
    derecha, y abajo, z > 0 hacia dentro); mask: (alto, ancho) bool, dónde hay superficie
    (el cielo no). Los dos al tamaño de trabajo de MoGe, que tiene la misma proporción que
    `texture`. options: depth_relief_density, depth_relief_split (ver export_relief).
    Devuelve la ruta del .obj."""
    height, width = mask.shape
    grid_w, grid_h = _grid_size(width, height, options.get("depth_relief_density", "medium"))

    # Se toman los puntos tal cual en la cuadrícula (sin interpolar): promediar la posición
    # de una persona con la de la pared de atrás inventaría puntos flotando entre las dos.
    rows = np.round(np.linspace(0, height - 1, grid_h)).astype(int)
    cols = np.round(np.linspace(0, width - 1, grid_w)).astype(int)
    pts = points[rows][:, cols]
    valid = mask[rows][:, cols]
    uu, vv = np.meshgrid(cols / max(1, width - 1), rows / max(1, height - 1))

    # OpenCV (y abajo, z hacia dentro) -> Y arriba, cámara mirando hacia -Z
    positions = np.stack([pts[..., 0], -pts[..., 1], -pts[..., 2]], axis=-1)

    keep = _corners(valid).all(axis=0) & _alpha_keep(texture, grid_w, grid_h)
    if options.get("depth_relief_split", False):
        z = _corners(np.where(valid, pts[..., 2], 1.0))
        step = max(width / grid_w, height / grid_h)
        keep &= z.max(axis=0) <= z.min(axis=0) * (1.0 + _SCENE_EDGE_RTOL * step)
    return _write_mesh(positions, uu.astype(np.float32), vv.astype(np.float32), keep, texture,
                       output_path, "escena")
