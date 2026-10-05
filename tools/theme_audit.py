"""Inventario de colores fijos en la interfaz de DowP (fase 0 del sistema de temas).

Recorre app/src/gui y clasifica cada color escrito a mano según DÓNDE aparece,
analizando el código con ast (no con búsquedas de texto sueltas):

  respaldo      Valor por defecto de get_theme_token(token, "#...") -> correcto, no se toca.
  estilo_local  Dentro de un setStyleSheet(...) -> el color no sigue al tema.
  dibujo        QColor(...) / Qt.white... en código que pinta -> no sigue al tema.
  icono         Color fijo al teñir un SVG (get_colored_svg_icon...) -> no sigue al tema.
  otro          Cualquier otro sitio (constantes, dicts...) -> revisar a mano.

Además cuenta los setStyleSheet que SÍ usan get_theme_token pero se evalúan una sola
vez al crear el widget ("congelados"): siguen el tema al arrancar, pero no al cambiarlo
en vivo.

Uso (desde la raíz del repo):
    python tools/theme_audit.py                 # resumen por consola
    python tools/theme_audit.py --md informe.md # además, informe detallado en Markdown
"""
import argparse
import ast
import io
import tokenize
import os
import re
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUI_DIR = os.path.join(ROOT, "app", "src", "gui")

HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
# Colores con nombre dentro de QSS ("color: white"). 'transparent' no cuenta: no es un color.
QSS_NAMED_RE = re.compile(r"(?:color|background(?:-color)?|border(?:-color)?)\s*:\s*(white|black|gray|grey|red|green|blue|yellow)\b", re.I)
QSS_RGB_RE = re.compile(r"rgba?\(\s*\d+\s*,\s*\d+\s*,\s*\d+")
QT_COLOR_NAMES = {"white", "black", "red", "green", "blue", "yellow", "gray", "darkGray",
                  "lightGray", "cyan", "magenta", "darkRed", "darkGreen", "darkBlue"}
ICON_FUNCS = {"get_colored_svg_icon", "generate_tinted_svg", "create_colored_circle_icon"}
TOKEN_FUNCS = {"get_theme_token"}

CATEGORIES = ("estilo_local", "dibujo", "icono", "otro", "respaldo")


def _call_name(node):
    f = node.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return ""


def _span(node):
    return (node.lineno, node.col_offset, node.end_lineno, node.end_col_offset)


def _inside(pos, span):
    (l, c), (sl, sc, el, ec) = pos, span
    if l < sl or l > el:
        return False
    if l == sl and c < sc:
        return False
    if l == el and c >= ec:
        return False
    return True


class FileScan:
    def __init__(self, path):
        self.path = path
        self.rel = os.path.relpath(path, ROOT).replace("\\", "/")
        with open(path, encoding="utf-8") as f:
            self.src = f.read()
        self.lines = self.src.splitlines()
        self.tree = ast.parse(self.src)
        self.style_calls = []      # spans de setStyleSheet(...)
        self.token_fallbacks = []  # spans del 2.º argumento de get_theme_token
        self.icon_calls = []
        self.qcolor_calls = []
        self.qt_named = []         # (line, col, nombre) de Qt.white...
        self.docstrings = set()    # líneas de docstrings/comentarios largos: se ignoran
        self.frozen_styles = 0
        self._collect()

    def _collect(self):
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
                body = getattr(node, "body", [])
                if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                        and isinstance(body[0].value.value, str):
                    d = body[0]
                    self.docstrings.update(range(d.lineno, d.end_lineno + 1))
            if isinstance(node, ast.Call):
                name = _call_name(node)
                if name == "setStyleSheet":
                    self.style_calls.append(_span(node))
                    if any(isinstance(n, ast.Call) and _call_name(n) in TOKEN_FUNCS for n in ast.walk(node)):
                        self.frozen_styles += 1
                elif name in TOKEN_FUNCS and len(node.args) >= 2:
                    self.token_fallbacks.append(_span(node.args[1]))
                elif name in ICON_FUNCS:
                    self.icon_calls.append(_span(node))
                elif name == "QColor":
                    self.qcolor_calls.append(_span(node))
            elif isinstance(node, ast.Attribute) and node.attr in QT_COLOR_NAMES:
                base = node.value
                if (isinstance(base, ast.Name) and base.id == "Qt") or \
                        (isinstance(base, ast.Attribute) and base.attr == "GlobalColor"):
                    self.qt_named.append((node.lineno, node.col_offset, f"Qt.{node.attr}"))

    def classify(self, line, col):
        pos = (line, col)
        if any(_inside(pos, s) for s in self.token_fallbacks):
            return "respaldo"
        if any(_inside(pos, s) for s in self.icon_calls):
            return "icono"
        if any(_inside(pos, s) for s in self.style_calls):
            return "estilo_local"
        if any(_inside(pos, s) for s in self.qcolor_calls):
            return "dibujo"
        return "otro"

    def findings(self):
        """Colores dentro de literales de cadena (también los de varias líneas), detectados
        con tokenize: un '#' fuera de una cadena es un comentario, no un color."""
        out = []
        for tok in tokenize.generate_tokens(io.StringIO(self.src).readline):
            if tok.type != tokenize.STRING or tok.start[0] in self.docstrings:
                continue
            (sl, sc), text = tok.start, tok.string
            for rx in (HEX_RE, QSS_RGB_RE, QSS_NAMED_RE):
                for m in rx.finditer(text):
                    before = text[:m.start()]
                    line = sl + before.count("\n")
                    col = (sc + m.start()) if line == sl else (m.start() - before.rfind("\n") - 1)
                    cat = self.classify(line, col)
                    out.append((cat, line, m.group(0), self.lines[line - 1].strip()))
        for line, col, name in self.qt_named:
            out.append(("dibujo", line, name, self.lines[line - 1].strip()))
        # QColor(r, g, b) numérico: no lo atrapa ninguna regex de arriba.
        for sl, sc, el, ec in self.qcolor_calls:
            snippet = self.lines[sl - 1][sc:]
            if re.match(r"QColor\(\s*\d", snippet):
                out.append(("dibujo", sl, "QColor(r,g,b)", self.lines[sl - 1].strip()))
        return out


def scan():
    results = []
    frozen = {}
    for base, _dirs, files in os.walk(GUI_DIR):
        if "__pycache__" in base:
            continue
        for fn in files:
            if not fn.endswith(".py") or fn == "theme_manager.py":
                continue
            fs = FileScan(os.path.join(base, fn))
            for item in fs.findings():
                results.append((fs.rel,) + item)
            if fs.frozen_styles:
                frozen[fs.rel] = fs.frozen_styles
    return results, frozen


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--md", help="Ruta del informe detallado en Markdown")
    args = ap.parse_args()

    results, frozen = scan()
    by_cat = Counter(r[1] for r in results)
    by_file = defaultdict(Counter)
    for rel, cat, *_ in results:
        by_file[rel][cat] += 1

    pending = [c for c in CATEGORIES if c != "respaldo"]
    print("Inventario de colores fijos (app/src/gui)\n")
    for c in CATEGORIES:
        print(f"  {c:<13} {by_cat.get(c, 0):>5}")
    print(f"  {'-' * 19}\n  {'pendientes':<13} {sum(by_cat.get(c, 0) for c in pending):>5}  (todo menos 'respaldo')")
    print(f"\nsetStyleSheet congelados (usan tokens, pero no se actualizan en vivo): {sum(frozen.values())}")
    ranking = sorted(by_file.items(), key=lambda kv: -sum(kv[1][c] for c in pending))
    print("\nArchivos con más colores pendientes:")
    for rel, cnt in ranking[:15]:
        total = sum(cnt[c] for c in pending)
        if total:
            detail = ", ".join(f"{c} {cnt[c]}" for c in pending if cnt[c])
            print(f"  {total:>4}  {rel}  ({detail})")

    if args.md:
        with open(args.md, "w", encoding="utf-8") as f:
            f.write("# Inventario de colores fijos\n\nGenerado con `tools/theme_audit.py`.\n\n")
            f.write("| Categoría | Cantidad |\n|---|---|\n")
            for c in CATEGORIES:
                f.write(f"| {c} | {by_cat.get(c, 0)} |\n")
            f.write(f"\n**setStyleSheet congelados:** {sum(frozen.values())}\n\n")
            f.write("## Por archivo\n\n| Archivo | " + " | ".join(pending) + " | congelados |\n|---|"
                    + "---|" * (len(pending) + 1) + "\n")
            for rel, cnt in ranking:
                if sum(cnt[c] for c in pending) or frozen.get(rel):
                    f.write(f"| `{rel}` | " + " | ".join(str(cnt[c]) for c in pending) + f" | {frozen.get(rel, 0)} |\n")
            f.write("\n## Detalle\n")
            current = None
            for rel, cat, line, value, text in sorted(results, key=lambda r: (r[0], r[2])):
                if cat == "respaldo":
                    continue
                if rel != current:
                    f.write(f"\n### `{rel}`\n\n")
                    current = rel
                f.write(f"- L{line} **{cat}** `{value}` — `{text[:110]}`\n")
        print(f"\nInforme detallado: {args.md}")


if __name__ == "__main__":
    sys.exit(main())
