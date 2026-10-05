# 🎨 Temas de DowP

Un tema es un archivo `.json` que define los **colores** (en modo claro y oscuro), las
**formas** (esquinas y bordes) y la **tipografía** de DowP. Funciona como los temas de
CustomTkinter: un mismo tema trae sus dos modos, y en **Ajustes → General → Modo** eliges
Oscuro, Claro o Según el sistema.

---

## Temas incluidos

| Tema | Estilo | Esquinas |
|---|---|---|
| **DowP** | Verde lima sobre negro (el de siempre) | Normales |
| **Tokyo Night** | Azul noche con morados y celestes | Algo más redondas |
| **Café Noir** | Cafés y crema, cálido y sobrio | Casi rectas |
| **Rubí** | Rojo carmesí sobre negro cálido | Normales |
| **Nórdico** | Grises azulados y tonos hielo | Normales, paneles más redondos |

Todos tienen modo claro y oscuro. Son buenos puntos de partida: expórtalos y edítalos.

---

## Empezar rápido

1. En **Ajustes → General**, pulsa el botón de carpeta junto a **Tema visual** y elige
   **Exportar tema actual…**. Se guarda el tema completo, con todos sus valores.
2. Abre ese `.json` con cualquier editor de texto y cambia lo que quieras.
3. Cámbiale el nombre en `meta.nombre` y vuelve a ese menú: **Importar tema…**.

El tema queda guardado en `%APPDATA%\DowP2\themes\` y aparece en la lista con
"(Usuario)". Desde el mismo menú puedes **eliminarlo** o **abrir la carpeta de temas**.

Si un valor está mal escrito, DowP lo ignora (y usa el de DowP) en lugar de romperse; el
detalle queda en la consola y en el log.

---

## Formato

```json
{
    "meta": {
        "nombre": "Mi tema",
        "autor": "Tu nombre",
        "formato": 2
    },
    "basado_en": "dowp",
    "formas": {
        "radio": 6,
        "radio_chico": 4,
        "radio_grande": 8,
        "borde": 1
    },
    "tipografia": {
        "familia": "Inter",
        "tamano": 13
    },
    "colores": {
        "acento_primario": ["#1DC038", "#B9E640"],
        "estado_error": "#ff6b5f"
    }
}
```

Todo es **opcional**. Lo que no definas se toma del tema base (`basado_en`, que por
defecto es `dowp`). Así, un tema puede ser tan corto como cambiar el color de acento.

### Colores

- **Pareja `["claro", "oscuro"]`**: el primer valor se usa en modo claro y el segundo en
  modo oscuro.
- **Un solo valor** (`"#ff6b5f"`): igual en los dos modos.
- Formatos admitidos: `#rgb`, `#rrggbb`, `#aarrggbb`, `rgb(r, g, b)`, `rgba(r, g, b, a)`
  y `transparent`.

Si al resolverse el tema (con lo que hereda de su base) todos los colores quedan iguales
en los dos modos, el tema es de un solo modo y el selector de Modo se desactiva mientras
esté elegido. Para un tema así, exporta un tema completo y deja un solo valor en cada
color.

### Formas

Valores en píxeles. Los estilos de DowP están diseñados con los valores por defecto y se
escalan en proporción a los tuyos.

| Clave | Para qué sirve | Por defecto | Rango |
|---|---|---|---|
| `radio` | Esquinas de botones, campos, menús y tarjetas | 6 | 0–14 |
| `radio_chico` | Esquinas de chips, muestras de color y botones pequeños | 4 | 0–8 |
| `radio_grande` | Esquinas de paneles, tarjetas grandes y diálogos | 8 | 0–20 |
| `borde` | Grosor de los bordes normales | 1 | 0–3 |

Los elementos redondos (botones de radio, botones "?", chips de búsqueda) siguen siendo
redondos con cualquier valor.

### Tipografía

| Clave | Para qué sirve | Por defecto | Rango |
|---|---|---|---|
| `familia` | Fuente del tema. Se usa cuando en Ajustes la fuente está en "Por defecto del tema" | — | — |
| `tamano` | Tamaño base del texto; el resto de tamaños se escala en proporción | 13 | 11–14 |

Las fuentes que no estén instaladas en el sistema pueden ponerse en
`%APPDATA%\DowP2\fonts\` (botón de carpeta junto a **Tipografía / Fuente**).

---

## Temas de DowP 1

Los temas de DowP 1 (los de CustomTkinter, con secciones como `CTkButton` o
`CustomColors`) se pueden importar directamente con **Importar tema…**: DowP los
convierte al formato nuevo. Se traducen los colores principales (fondos, texto, acento,
botones, campos, casillas, interruptores, barras de progreso, estados, consola y
cuadrícula de transparencia), las esquinas y la fuente. Lo que no tiene equivalente se
toma de DowP.

---

## Referencia de colores

Los valores son los del tema DowP. Los de la sección "Otros" son colores de piezas
concretas que casi nunca hace falta cambiar.

### Fondos

| Token | Para qué sirve | Claro / Oscuro |
|---|---|---|
| `fondo_principal` | Fondo de la ventana | `#ffffff` / `#0a0a0a` |
| `fondo_secundario` | Campos, listas y contenedores | `#f8f8f8` / `#121212` |
| `fondo_terciario` | Menús desplegables y tooltips | `#f5f5f5` / `#161616` |
| `panel_fondo` | Paneles laterales | `#f3f3f3` / `#181818` |
| `fondo_elemento` | Elementos dentro de listas | `#f9f9f9` / `#1a1a1a` |
| `fondo_campo` | Campos de texto | `#ffffff` / `#1e1e1e` |
| `fondo_control` |  | `#ececec` / `#2a2a2a` |
| `fondo_control_hover` |  | `#e0e0e0` / `#3a3a3a` |
| `fondo_hover` |  | `#ececec` / `#2a2a2a` |
| `fondo_miniatura` |  | `#eeeeee` / `#151515` |
| `tarjeta_fondo` |  | `rgba(0, 0, 0, 0.025)` / `rgba(255, 255, 255, 0.035)` |
| `tarjeta_lista_fondo` |  | `#f7f7f7` / `#171717` |
| `cabecera_dialogo` |  | `#f2f2f2` / `#0d0d0d` |

### Texto

| Token | Para qué sirve | Claro / Oscuro |
|---|---|---|
| `texto_principal` | Texto general | `#1a1a1a` / `#e0e0e0` |
| `texto_secundario` | Texto de menor importancia | `#999999` / `#666666` |
| `texto_activo` | Máximo contraste (opción elegida, campos) | `#000000` / `#ffffff` |
| `texto_deshabilitado` | Texto de controles desactivados | `#aaaaaa` / `#555555` |
| `texto_titulo` |  | `#111111` / `#eeeeee` |
| `texto_fuerte` |  | `#222222` / `#dddddd` |
| `texto_medio` |  | `#333333` / `#cccccc` |
| `texto_suave` |  | `#55586b` / `#a6adc8` |
| `texto_gris` |  | `#555555` / `#aaaaaa` |
| `texto_tenue` |  | `#777777` / `#888888` |
| `texto_apagado` |  | `#8c8c8c` / `#777777` |
| `texto_clave` |  | `#1d5fc4` / `#89b4fa` |
| `texto_valor` |  | `#2b2f40` / `#cdd6f4` |
| `texto_primario` |  | `#000000` / `#ffffff` |

### Acentos e iconos

| Token | Para qué sirve | Claro / Oscuro |
|---|---|---|
| `acento_primario` | Color de marca: pestaña activa, casillas, interruptores | `#1DC038` / `#B9E640` |
| `acento_secundario` | Acento alternativo (botones sólidos) | `#02852A` / `#1DC038` |
| `acento_audio` |  | `#b4407f` / `#f5c2e7` |
| `icono_principal` | Iconos monocromos (barra de título, árbol, tarjetas) | `#3a3a3a` / `#e3e3e3` |
| `icono_tenue` |  | `#8a8ea0` / `#6c7086` |
| `icono_vacio` |  | `#c4c4c4` / `#444444` |

### Bordes

| Token | Para qué sirve | Claro / Oscuro |
|---|---|---|
| `borde_normal` | Borde estándar | `#eeeeee` / `#222222` |
| `borde_sutil` | Borde suave | `#f0f0f0` / `#333333` |
| `borde_fuerte` |  | `#bbbbbb` / `#555555` |
| `borde_campo` |  | `#cccccc` / `#444444` |
| `borde` |  | `#d6d6d6` / `#2d2d2d` |
| `borde_focus` |  | `#007acc` (ambos) |
| `divisor` |  | `#eeeeee` / `#222222` |
| `divisor_settings` |  | `#1DC038` / `#017B28` |

### Selección

| Token | Para qué sirve | Claro / Oscuro |
|---|---|---|
| `seleccion_fondo` | Fondo del elemento elegido o bajo el ratón | `#f0fdf0` / `#222222` |
| `seleccion_texto` | Texto del elemento elegido | `#02852A` / `#B9E640` |
| `resaltado_hover` |  | `rgba(0, 0, 0, 0.05)` / `rgba(255, 255, 255, 0.05)` |

### Botones

| Token | Para qué sirve | Claro / Oscuro |
|---|---|---|
| `boton_fondo_inicio` | Degradado de los botones principales (arriba) | `#1DC038` / `#B9E640` |
| `boton_fondo_fin` | Degradado de los botones principales (abajo) | `#02852A` / `#1DC038` |
| `boton_texto` | Texto de los botones principales | `#ffffff` / `#000000` |
| `boton_acento_texto` | Texto e iconos sobre botones de acento | `#ffffff` / `#000000` |
| `boton_secundario_fondo` |  | `#e6f5e9` / `#1b3b22` |
| `boton_secundario_texto` |  | `#02852A` / `#B9E640` |
| `boton_secundario_hover` |  | `#d4ebd9` / `#224a2b` |
| `boton_neutro_fondo` |  | `#e8e8e8` / `#333333` |
| `boton_neutro_borde` |  | `#c8c8c8` / `#4a4a4a` |
| `boton_neutro_hover` |  | `#dcdcdc` / `#3d3d3d` |

### Casillas e interruptores

| Token | Para qué sirve | Claro / Oscuro |
|---|---|---|
| `checkbox_fondo` |  | `#ffffff` / `#121212` |
| `checkbox_borde` |  | `#cccccc` / `#333333` |
| `checkbox_checked` |  | `#1DC038` / `#B9E640` |
| `switch_apagado` | Interruptor apagado | `#d6d6d6` / `#333333` |
| `switch_borde` |  | `#bdbdbd` / `#444444` |
| `switch_perilla` | Círculo del interruptor | `#ffffff` / `#ffffff` |

### Barras de progreso

| Token | Para qué sirve | Claro / Oscuro |
|---|---|---|
| `progreso_fondo` |  | `#ffffff` / `#0f0f0f` |
| `progreso_inicio` |  | `#7b1fa2` / `#6a1b9a` |
| `progreso_fin` |  | `#4a148c` (ambos) |
| `progreso_texto` |  | `#1a1a1a` / `#ffffff` |

### Estados

| Token | Para qué sirve | Claro / Oscuro |
|---|---|---|
| `estado_espera` | En espera | `#777777` / `#aaaaaa` |
| `estado_progreso` | En curso | `#3498db` (ambos) |
| `estado_exito` | Completado | `#168f41` / `#40d66b` |
| `estado_aviso` | Advertencia | `#9a7a00` / `#d8c94a` |
| `estado_error` | Error o cancelado | `#bf2f29` / `#ff6b5f` |

### Cuadrícula de transparencia

| Token | Para qué sirve | Claro / Oscuro |
|---|---|---|
| `ajedrez_c1` | Cuadros claros de la cuadrícula | `#e0e0e0` / `#2a2a2a` |
| `ajedrez_c2` | Cuadros oscuros de la cuadrícula | `#c8c8c8` / `#181818` |

### Consola

| Token | Para qué sirve | Claro / Oscuro |
|---|---|---|
| `consola_fondo` | Fondo de la consola | `#000000` (ambos) |
| `consola_texto` |  | `#ffffff` (ambos) |
| `consola_debug` |  | `#4da6ff` (ambos) |
| `consola_advertencia` |  | `#ffd60a` (ambos) |
| `consola_error` |  | `#ff6b5f` (ambos) |
| `consola_critico` |  | `#ff1744` (ambos) |

### Otros (botones y piezas concretas)

Colores de botones, tarjetas, reproductor y diálogos específicos. Normalmente no hace falta tocarlos: si no los defines, se toman de DowP.

| Token | Claro / Oscuro |
|---|---|
| `badge_fondo` | `#eeeeee` / `#222222` |
| `badge_texto` | `#02852A` / `#B9E640` |
| `boton_solo_inicio` | `#70a1ff` / `#00c6ff` |
| `boton_solo_fin` | `#1e90ff` / `#0072ff` |
| `boton_solo_texto` | `#ffffff` (ambos) |
| `boton_importar_inicio` | `#35c9b0` / `#35d6b8` |
| `boton_importar_fin` | `#087c70` / `#138f7d` |
| `boton_importar_texto` | `#ffffff` / `#001a16` |
| `boton_descarga_inicio` | `#d4bd2f` / `#d8c94a` |
| `boton_descarga_fin` | `#2fbd43` / `#4ccf46` |
| `boton_descarga_texto` | `#101400` / `#111400` |
| `boton_descarga_running_inicio` | `#1DC038` / `#B9E640` |
| `boton_descarga_running_fin` | `#02852A` / `#1DC038` |
| `boton_descarga_done_inicio` | `#31ba63` / `#40d66b` |
| `boton_descarga_done_fin` | `#168f41` (ambos) |
| `boton_descarga_error_inicio` | `#e85b50` / `#ff6b5f` |
| `boton_descarga_error_fin` | `#bf2f29` / `#c7352f` |
| `boton_descarga_pausar_inicio` | `#f39c12` / `#f5af19` |
| `boton_descarga_pausar_fin` | `#d35400` / `#e65100` |
| `boton_descarga_pausar_texto` | `#ffffff` (ambos) |
| `tab_texto_inactivo` | `#999999` / `#666666` |
| `tab_fondo_seleccionado` | `#f8f8f8` / `#161616` |
| `titulo_settings` | `#02852A` / `#1DC038` |
| `boton_fragmentos_inicio` | `#e85b50` / `#ff6b5f` |
| `boton_fragmentos_fin` | `#e07b00` / `#FF8C00` |
| `boton_fragmentos_texto` | `#ffffff` (ambos) |
| `etiqueta_combinado` | `#3498db` (ambos) |
| `etiqueta_multi_idioma` | `#9b59b6` (ambos) |
| `etiqueta_estrella` | `#f1c40f` (ambos) |
| `etiqueta_peligro` | `#e74c3c` (ambos) |
| `combo_flecha_fondo` | `rgba(0, 0, 0, 0.06)` / `rgba(0, 0, 0, 0.4)` |
| `tarjeta_destacada_inicio` | `#f6f7f8` / `#25282a` |
| `tarjeta_destacada_fin` | `#eef0f2` / `#1c1d1f` |
| `tarjeta_destacada_borde` | `#d5d9dc` / `#383c40` |
| `tarjeta_futura_fondo` | `#f7f7f7` / `#181818` |
| `onda_fondo` | `#f2f2f2` / `#0d0d0d` |
| `onda_cuadricula` | `#d4d4d4` / `#333333` |
| `onda_cuadricula_fuerte` | `#bdbdbd` / `#444444` |
| `onda_barra` | `#e4e4e4` / `#282828` |
| `onda_linea` | `#c8c8c8` / `#3c3c3c` |
| `cabezal` | `#1a1a1a` / `#ffffff` |
| `contorno_marcador` | `#ffffff` / `#141414` |
| `pista_slider` | `#cfcfcf` / `#3e3e3e` |
| `barra_scroll_fondo` | `#e6e6e6` / `#222222` |
| `barra_scroll_tirador` | `#b5b5b5` / `#555555` |
| `boton_marca_entrada` | `#e3f5e5` / `#1a271a` |
| `boton_marca_salida` | `#f8e3e3` / `#2b1a1a` |
| `borde_muestra_color` | `#333333` / `#ffffff` |
| `flecha_control` | `#555555` / `#d0d0d0` |
| `tarjeta_lista_borde` | `#dddddd` / `#2e2e2e` |
| `titulo_boton_hover` | `#dff0e2` / `#1e3a1e` |
| `titulo_boton_pulsado` | `#cfe6d3` / `#163016` |
| `titulo_cerrar_hover` | `#f6d4d4` / `#4a1010` |
| `titulo_cerrar_pulsado` | `#eebcbc` / `#3a0a0a` |
| `miniatura_relleno_fondo` | `#ececee` / `#1c1c1e` |
| `miniatura_relleno_borde` | `#d4d4d8` / `#2d2d32` |

---

## Notas para desarrolladores

- **Archivos**: `gui/themes/_base.qss` (plantilla con `{{token}}`), `gui/themes/dowp.json`
  (tema por defecto), `core/utils/theme_loader.py` (lectura, herencia y validación),
  `core/utils/theme_io.py` (importar, exportar, eliminar y conversor de DowP 1),
  `gui/theme_manager.py` (aplica el tema y emite `theme_changed`).
- **Colores en código**: usa `get_theme_token("token", "#respaldo")`, nunca un color fijo.
  Si es un token nuevo, añádelo a `dowp.json` con su pareja `[claro, oscuro]`.
- **Estilos que cambian en vivo**: aplica las hojas con
  `set_themed_style(widget, lambda: f"...")`. Para estilos que dependen de un estado (un
  botón activo o inactivo, un icono teñido), registra el método con
  `register_theme_callback(widget, "clave", lambda: self._aplicar(estado))`. Lo que se
  pinta con `QPainter` debe leer los tokens dentro de `paintEvent`.
- **Iconos**: `themed_icon("nombre.svg")` devuelve un SVG teñido con `icono_principal`.
- **Formas y tamaño de letra**: `apply_shapes(qss)` adapta una hoja al tema activo;
  `set_themed_style` y la hoja principal ya lo hacen solos. Con los valores por defecto
  no cambia nada.
- **Compatibilidad**: la clave `theme` de `config.json` se mantiene en `dark`/`light`
  para versiones anteriores a la 1.9.3; el tema elegido va en `theme_id` y el modo en
  `theme_mode`.
