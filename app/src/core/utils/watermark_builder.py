# src/core/utils/watermark_builder.py
"""
Construcción de filtros de ffmpeg para marca de agua (texto vía drawtext, imagen vía
overlay). Funciones puras, sin dependencias de Qt ni de la UI.

Posición: fx/fy son fracciones (0..1) de la esquina superior-izquierda de la marca de
agua respecto al espacio de arrastre disponible (0 = pegada al borde superior/izquierdo,
1 = pegada al inferior/derecho). Se traducen a expresiones de ffmpeg (nunca a píxeles
fijos precalculados) para que el mismo filtro sirva sin importar la resolución real de
cada archivo — mismo principio ya usado para el recorte con iw/ih (ver
advanced_recode_panel.py::_build_vf_expression_with_crop): esto es lo que permite que
la marca de agua funcione bien guardada en un preajuste y aplicada a toda la cola.
"""
import os
from PySide6.QtCore import QCoreApplication


def check_watermark_file(settings: dict) -> str | None:
    """Aviso listo para mostrar si la imagen de marca de agua de 'settings' ya no
    existe en disco. None si no hay marca de agua de imagen activa o el archivo está
    bien — usado tanto al evaluar el panel Avanzado como en Preajustes (al elegir un
    preset y al exportar/importar)."""
    path = settings.get("watermark_image_path")
    if not path:
        return None
    if os.path.exists(path):
        return None
    return QCoreApplication.translate("watermark_builder", "La imagen de marca de agua de este ajuste ya no existe: %1").replace("%1", path)


def _escape_drawtext_text(text: str) -> str:
    """Escapa un texto arbitrario para usar como valor 'text=' del filtro drawtext,
    envuelto en comillas simples. El orden importa: primero las barras invertidas
    literales; después los dos puntos — verificado empíricamente contra el ffmpeg
    empaquetado que SÍ hace falta escaparlos con '\\:' aunque el valor esté entre
    comillas simples, las comillas no alcanzan solas (sin esto, cualquier texto con
    ':', como una hora "3:00", rompía el parser del filtro); después el '%' (drawtext
    lo interpreta para expansiones de fecha/hora tipo strftime); y por último las
    comillas simples literales (truco estándar de ffmpeg: cerrar comillas, colar una
    comilla escapada, reabrir comillas — tiene que ir al final para no volver a tocar
    los backslashes que este mismo truco introduce). Como queue_manager.py pasa los
    argumentos a subprocess.Popen como lista (sin shell de por medio), no hace falta
    ningún escapado adicional de shell — solo el propio de la sintaxis de ffmpeg."""
    escaped = text.replace("\\", "\\\\")
    escaped = escaped.replace(":", "\\:")
    escaped = escaped.replace("%", "\\%")
    escaped = escaped.replace("'", "'\\''")
    escaped = escaped.replace("\r", "").replace("\n", "\\n")
    return escaped


def build_drawtext_filter(text: str, font_path: str, size_expr: str, color_hex: str,
                           opacity: float, fx: float, fy: float) -> str:
    """size_expr: expresión de ffmpeg para el tamaño de fuente en píxeles (ej. 'h*0.05'
    para 5% de la altura de salida) — no un número fijo, por la misma razón que el
    resto de expresiones de este módulo."""
    escaped_text = _escape_drawtext_text(text)
    # Mismo motivo que el texto: los ':' de "C:/..." rompen el parser aunque el valor
    # esté entre comillas simples — verificado empíricamente, hace falta el backslash
    # ADEMÁS de las comillas, no una cosa u otra.
    font_path_escaped = font_path.replace("\\", "/").replace(":", "\\:")
    x_expr = f"(w-tw)*{fx:.4f}"
    y_expr = f"(h-th)*{fy:.4f}"
    return (
        f"drawtext=fontfile='{font_path_escaped}':text='{escaped_text}'"
        f":fontsize={size_expr}:fontcolor={color_hex}@{opacity:.2f}"
        f":x={x_expr}:y={y_expr}"
    )


def build_image_overlay_filter(scale_pct: float, opacity: float, fx: float, fy: float,
                                image_aspect_hw: float) -> str:
    """Fragmento completo del segundo input (etiqueta [1:v] fija por convención: la
    imagen de marca de agua siempre es el input de índice 1 en queue_manager.py).
    Referencia [main] como la etiqueta del video ya escalado/recortado/con texto —
    queue_manager.py arma '[0:v]<vf>[main];' antes de concatenar esto.

    image_aspect_hw: alto/ancho NATIVO de la imagen (ej. 0.5 para un logo de 200x100).
    Necesario porque, dentro de scale2ref, la altura automática 'h=-1' NO preserva el
    aspecto de la imagen que se está escalando — usa el aspecto del input de
    REFERENCIA (el video) por el mismo motivo que 'iw'/'ih' cruzan al segundo input
    (ver nota abajo) — bug real, encontrado y corregido: un logo rectangular quedaba
    estirado para calzar con el aspecto del video. En vez de 'h=-1', el alto se calcula
    a mano como ancho_calculado * image_aspect_hw, así siempre respeta la forma real
    de la imagen sin importar el aspecto del video.

    scale_pct es un porcentaje del ANCHO DE SALIDA (main_w), no del ancho propio de la
    imagen — coincide con lo que ya muestra la vista previa interactiva. Para lograrlo
    hace falta 'scale2ref' en vez de un 'scale' común: un 'scale=iw*pct' aplicado
    directo sobre [1:v] escala respecto al ancho PROPIO de la imagen (bug real,
    encontrado y corregido: con una imagen de 1000px sobre un video de 1920px, "25%"
    terminaba siendo 250px reales — 13% del video, no 25% — y además desplazaba mal la
    posición, porque 'overlay_w' cambiaba con eso). scale2ref sí permite escalar UNA
    entrada usando las dimensiones de la OTRA como referencia — verificado
    empíricamente el detalle que no está claro en la documentación: dentro de sus
    expresiones w=/h=, 'iw'/'ih' se refieren al input de REFERENCIA (el segundo,
    [main] aquí), no al que se está escalando ('main_w'/'main_h' NO funcionan para
    esto, a pesar de lo que sugiere el nombre — se probó y no cruzan al segundo input).

    'shortest=1' en el overlay final es obligatorio — verificado empíricamente que sin
    él el proceso de ffmpeg queda corriendo para siempre. La imagen entra con
    '-loop 1' (stream infinito, para que dure lo mismo que el video), y el filtro
    overlay por defecto (eof_action=repeat, shortest=0) espera indefinidamente a que
    ESE input infinito también termine antes de cerrar la salida — nunca lo hace, así
    que el video principal se congela en su último frame y el encode no corta nunca.
    El flag global '-shortest' que agrega queue_manager.py NO alcanza para esto: es un
    ajuste de nivel de output/muxer, no se propaga al comportamiento interno del filtro."""
    scale_factor = max(0.01, scale_pct / 100.0)
    aspect = image_aspect_hw if image_aspect_hw and image_aspect_hw > 0 else 1.0
    w_expr = f"iw*{scale_factor:.4f}"
    h_expr = f"iw*{scale_factor:.4f}*{aspect:.6f}"
    x_expr = f"(main_w-overlay_w)*{fx:.4f}"
    y_expr = f"(main_h-overlay_h)*{fy:.4f}"
    return (
        f"[1:v][main]scale2ref=w={w_expr}:h={h_expr}[wmraw][main2];"
        f"[wmraw]format=rgba,colorchannelmixer=aa={opacity:.2f}[wm];"
        f"[main2][wm]overlay=x={x_expr}:y={y_expr}:shortest=1[vout]"
    )
