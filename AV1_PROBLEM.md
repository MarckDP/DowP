# Problema con AV1 en las vistas previas

**Estado:** diagnosticado y con solución verificada. **No aplicada todavía** — decisión pendiente.
**Investigado:** 2026-09-20/21 · **PySide6 probado:** 6.11.2

---

## 1. El síntoma

Un vídeo con códec **AV1** se carga en cualquier reproductor de la app (Herramientas
Multimedia, vista previa de fragmentos, etc.) y:

- El **audio suena bien** y se puede desplazar por la pista con normalidad.
- El **vídeo no aparece nunca**: solo se ve el fondo de cuadrícula de transparencia.
- **No sale ningún mensaje de error** ni la pantalla de "sin medios".
- El mismo archivo **se convierte, recodifica y modifica sin ningún problema**.

Ocurre solo en ciertos equipos. En otros, el mismo archivo se previsualiza bien.

---

## 2. La causa

**El FFmpeg que Qt empaqueta dentro de PySide6 no incluye ningún decodificador AV1 por
software.** Está compilado únicamente con:

```
--enable-network --enable-pic --enable-shared --enable-zlib
```

Sin una sola librería de códec externa. Escaneando `PySide6/avcodec-61.dll`:

| Decodificador | ¿Presente? |
|---|---|
| `libdav1d` (software) | ❌ |
| `libaom-av1` (software) | ❌ |
| `av1` (nativo) | ✅ |
| `av1_d3d11va`, `av1_d3d12va` (hardware) | ✅ |
| h264, hevc, vp9, vp8 | ✅ (todos con decodificador software propio) |

Y aquí está la clave: **el decodificador `av1` nativo de FFmpeg no decodifica por
software.** Es un envoltorio que solo parsea el bitstream y se lo entrega a un
acelerador por hardware. Sin hardware compatible, no tiene a dónde ir.

Comprobado ejecutándolo:

```console
$ ffmpeg -hwaccel none -c:v av1 -i test_av1.mp4 -f null -
[av1] Your platform doesn't support hardware accelerated AV1 decoding.
[av1] Failed to get pixel format.
[av1] Error submitting packet to decoder: Function not implemented
frame=    0 ... Conversion failed!
```

| Ruta de decodificación | Fotogramas |
|---|---|
| `av1` nativo **sin** hardware | **0** — `Function not implemented` |
| `av1` nativo **con** hardware | 10 ✅ |
| `libdav1d` (software) | 10 ✅ |

**Por eso no "baja a CPU": no hay a qué bajar.** No es un fallo de la lógica de
respaldo, es un decodificador que no está en el binario.

### Por qué convierte pero no previsualiza

Son **dos FFmpeg distintos**:

| | Binario | AV1 por software |
|---|---|---|
| Convertir / recodificar | `app/bin/dependences/ffmpeg/ffmpeg.exe` (gyan 9.0.1, `--enable-libdav1d --enable-libaom --enable-libsvtav1`) | ✅ |
| Previsualizar | `PySide6/avcodec-61.dll` (Qt, n7.1.5, build mínimo) | ❌ |

### Por qué no aparece ningún mensaje de error

Medido con `QMediaPlayer`:

```
frames=0 | status=EndOfMedia | err=-
```

**Qt no reporta ningún error.** Considera que reprodujo el archivo entero y llegó al
final. Por eso no se dispara `_on_media_error` ni aparece el `fallback_label` de
`fragment_dialog.py`: para Qt no ha ocurrido nada malo. El usuario se queda mirando la
cuadrícula sin explicación.

> Implicación: si alguna vez se quisiera **detectar** este caso sin sustituir los DLL,
> el manejo de errores actual no sirve. Habría que reconocer el síntoma: llega
> `EndOfMedia` sin haber recibido ni un solo fotograma.

---

## 3. Qué equipos afecta

Exactamente los que **no tienen decodificación AV1 por hardware**:

| Fabricante | Tiene AV1 por hardware desde | No lo tiene |
|---|---|---|
| **NVIDIA** | Ampere (RTX 30, A-series) | Turing, Pascal y anteriores — **incluidas todas las Quadro** |
| **Intel** | Tiger Lake (11ª gen, gráficos Xe), Arc | UHD 630 y anteriores |
| **AMD** | RDNA2 (RX 6000) | Anteriores |
| **Apple** | M3 / A17 Pro | **M1, M2 y todos los Mac Intel** |

> NVIDIA retiró la marca *Quadro* justo al pasar a Ampere. Por eso **cualquier tarjeta
> que diga "Quadro" es Turing o anterior y no puede decodificar AV1.**

**macOS está peor que Windows:** en un MacBook M1 o M2 no hay ninguna GPU que pueda
salvar el caso, así que AV1 falla **siempre**. De hecho, la incidencia original de Qt se
reportó en Apple Silicon.

---

## 4. No es un fallo de DowP

Es una limitación conocida de Qt, reconocida y **sin resolver**:

**[QTBUG-119711](https://bugreports.qt.io/browse/QTBUG-119711)** — *"Add support for AV1
decoding with the FFmpeg backend in online installer"*. Abierta el **2023-12-04**, última
actualización 2025-11-21, estado **Reported**, prioridad *Not Evaluated*. Texto de Qt:

> *"The FFmpeg multimedia backend that comes with the online installer does not support
> decoding AV1 video files. It is, however, possible to configure FFmpeg to enable the
> libdav1d decoder (...) and enable AV1 playback with a custom build of the FFmpeg media
> backend. (...) AV1 playback is supported with for example the Windows backend."*

**[QTBUG-117118](https://bugreports.qt.io/browse/QTBUG-117118)** — la incidencia
original, con **los mismos mensajes de error** reproducidos aquí. Cerrada como *Moved*
hacia la anterior.

### Cómo lo resuelven otros programas

| Programa | Estrategia |
|---|---|
| **VLC** | Empaqueta **dav1d** desde la 3.0.5 (2018). Software siempre disponible. |
| **Chrome / Edge / Firefox** | Igual, dav1d incluido. |
| **Shutter Encoder** | **No usa ningún framework multimedia.** Lanza su propio ffmpeg como subproceso pidiéndole fotogramas crudos (`-c:v rawvideo -f rawvideo -`), los pinta en Java y corre un segundo proceso para el audio. Es un *servidor de fotogramas*, no un reproductor. |
| **Reproductores de Windows** | Media Foundation + la extensión *AV1 Video Extension* de la Store. |
| **DaVinci Resolve** | **Tiene el mismo problema.** En Windows su decodificación AV1 es por GPU; el consejo estándar cuando falla es transcodificar a DNxHR/ProRes antes de editar. |

El patrón es: **o empaquetas dav1d, o mandas a transcodificar.** Qt es el raro por
empaquetar un FFmpeg sin ninguna librería de códec.

---

## 5. La solución verificada

Sustituir los 5 DLL de FFmpeg de PySide6 por un build **de la misma versión** compilado
con dav1d. **No requiere ni una línea de código en DowP.**

| | Qt / PySide6 6.11.2 | Build LGPL compartido de BtbN |
|---|---|---|
| Versión FFmpeg | **n7.1.5** | **n7.1.5** (idéntica) |
| DLL | avcodec-61, avformat-61, avutil-59, swresample-5, swscale-8 | **los 5, mismos nombres** |
| `libdav1d` | ❌ | ✅ |
| hwaccels AV1 | solo d3d11va/d3d12va | + qsv, cuvid, nvdec, vulkan |
| Licencia | LGPL | **LGPL** (existe también variante GPL — **esa no sirve**, ver §8) |
| Tamaño | 18,9 MB | 92,3 MB (**+73,4 MB**) |

### Resultados de las pruebas

Simulando una GPU sin decodificación AV1 con `QT_FFMPEG_DECODING_HW_DEVICE_TYPES=""`:

| Caso (hardware desactivado) | DLL originales | DLL con dav1d |
|---|---|---|
| **AV1 4K (3840×2160)** | **0 fotogramas** ❌ | **178** ✅ |
| **AV1 + Opus (.webm)** | **0 fotogramas** ❌ | **178** ✅ |
| H.264 4K | 178 ✅ | 178 ✅ |
| HEVC + AAC | 178 ✅ | 178 ✅ |
| VP9 + Opus | 177 ✅ | 178 ✅ |
| MP3 (solo audio) | 0 vídeo (correcto) | 0 vídeo (correcto) |

**Ninguna regresión.** Con hardware activado, antes y después: AV1 172→173, H.264 171→172.

### Búsqueda (seek) y precisión de fotograma

Vídeo 1080p AV1, 20 s, GOP 60, 10 saltos incluyendo hacia atrás:

| Configuración | Latencia de salto |
|---|---|
| **dav1d por CPU** | **8,2 – 99,0 ms** |
| d3d11va, DLL nuevos | 2,0 – 28,6 ms |
| d3d11va, DLL originales | 1,4 – 31,6 ms |

Los 30 saltos respetaron la posición pedida. Precisión de fotograma: **desfase máximo de
1 fotograma (33 ms), idéntico antes y después** — es el comportamiento propio de Qt, no
algo que introduzca el cambio. Exacto en keyframes; un fotograma antes en posiciones que
caen en frontera de fotograma sin ser keyframe.

**Las 30 capturas de las tres configuraciones son idénticas bit a bit** (SHA-256). dav1d
por CPU y d3d11va por GPU producen exactamente los mismos píxeles, como corresponde a un
decodificador AV1 conforme a norma. El cambio es **funcionalmente inerte salvo por
arreglar AV1**.

### Rendimiento de la decodificación por CPU

Medido en un Ryzen 7 3700X con material 4K30 AV1 a 13 Mbps:

| Operación | Velocidad |
|---|---|
| Decodificar AV1 (libdav1d) | 253 fps — **8,44× tiempo real** |
| Transcodificar a 720p H.264 (NVENC) | 212 fps — 7,06× tiempo real |
| Transcodificar a 720p H.264 (x264 ultrafast) | 213 fps — 7,09× tiempo real |

El cuello de botella es la decodificación, no la codificación. A 8,4× tiempo real, la
CPU decodifica 4K AV1 de sobra para reproducción fluida.

---

## 6. Prueba manual en el equipo de un usuario afectado

Esto **no** modifica DowP: solo sustituye 5 archivos dentro de su instalación. Es
reversible haciendo copia de seguridad antes.

### Paso 1 — Descargar

```
https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-07-31-14-10/ffmpeg-n7.1.5-12-g1fdbca85aa-win64-lgpl-shared-7.1.zip
```

(~62 MB. Es la variante **`lgpl-shared`** de la rama **7.1** — no sirve ninguna otra,
ver §8.)

### Paso 2 — Extraer

Dentro del ZIP, los archivos están en:

```
ffmpeg-n7.1.5-12-g1fdbca85aa-win64-lgpl-shared-7.1/bin/
```

Solo hacen falta **estos 5**:

| Archivo | Tamaño | SHA-256 |
|---|---|---|
| `avcodec-61.dll` | 66.260.480 | `30ec40e6210e592d02e626589a9997e3f793e83dac078aaa3ed410fcbdb20723` |
| `avformat-61.dll` | 21.862.912 | `3ef409dc46aea8cb163068637546033cfa6c2c92b9d0c0a1e1eee011027168a0` |
| `avutil-59.dll` | 2.838.528 | `99cb38dcb14027a74651eae812d9dd992ec4d0e66d19c2fc55c24af6c66e9a54` |
| `swresample-5.dll` | 671.232 | `3906fac6b66139bd1a526f83cfcfd81cdb047a0ea9fc97b5761b7e7bf2722eb0` |
| `swscale-8.dll` | 705.024 | `8a74ed235b17980e7f41de482c95b9ec8426c6d41235cab56c0eb74183b7d1e0` |

El resto del ZIP (`ffmpeg.exe`, `avfilter`, `avdevice`…) **no se usa**.

### Paso 3 — Localizar la carpeta destino

```
C:\Users\<USUARIO>\AppData\Local\Programs\DowP\_internal\PySide6\
```

> ⚠️ Es **`_internal\PySide6\`**, no `_internal\` a secas. Si la instalación se hizo en
> otra ruta, buscar la carpeta que contiene `DowP.exe` y entrar en
> `_internal\PySide6\`.

Para llegar rápido: pegar esto en la barra de direcciones del Explorador.

```
%LOCALAPPDATA%\Programs\DowP\_internal\PySide6
```

Debe contener ya los 5 archivos con estos tamaños (los que se van a reemplazar):

| Archivo | Tamaño original |
|---|---|
| `avcodec-61.dll` | 14.064.952 |
| `avformat-61.dll` | 2.648.888 |
| `avutil-59.dll` | 1.174.328 |
| `swresample-5.dll` | 243.512 |
| `swscale-8.dll` | 757.560 |

### Paso 4 — Copia de seguridad

**Con DowP cerrado**, copiar esos 5 archivos a una carpeta aparte (por ejemplo
`Escritorio\dll_originales_dowp\`). Sin esto no hay vuelta atrás fácil.

### Paso 5 — Reemplazar

Copiar los 5 del ZIP sobre la carpeta, aceptando sobrescribir. La carpeta pasará de
~18,9 MB a ~92,3 MB en esos archivos.

### Paso 6 — Probar

Abrir DowP y cargar el vídeo AV1 que fallaba. Debería verse la imagen.

### Para revertir

Cerrar DowP y volver a copiar los 5 archivos de la copia de seguridad.

---

## 7. Si se decide integrarlo en las compilaciones

Notas recogidas durante la investigación, **no implementadas**:

- **Sustituir después de compilar**, sobre `dist\DowP\_internal\PySide6\`. Hacerlo antes
  (en el `.venv`) expone un DLL de 66 MB al `upx=True` del spec. Hoy no comprime nada
  (comprobado), pero si UPX aparece en el PATH de la máquina de compilación, sí lo haría.
- **La trampa silenciosa:** el número de ABI va en el propio nombre del archivo
  (`avcodec-**61**`). Si PySide6 pasa a FFmpeg 8, empaquetará `avcodec-62.dll` y los
  archivos `-61` quedarían ignorados **sin ningún error** — de vuelta al fallo original
  sin enterarse. Cualquier script debe comparar el **conjunto de nombres** contra el de
  PySide6 y **romper la compilación** si no coincide, nunca limitarse a avisar.
- **Verificar por defecto, descargar solo a mano.** BtbN retira las ramas antiguas: la
  7.1 ya no aparece en su release *latest*, hubo que ir a `autobuild-2026-07-31-14-10`.
  Un build que descargue automáticamente se romperá el día que esa URL desaparezca.
- **Los binarios fuera de git, la receta dentro.** 92 MB en el repositorio serían
  permanentes. Mejor un manifiesto (nombres exigidos, versión esperada, tag del release,
  SHA-256) más el script, y los binarios ignorados — así también funciona en el runner
  de GitHub Actions.
- **En desarrollo no hace falta tocar el `.venv`.** Está verificado que precargar los DLL
  desde una carpeta externa con `os.add_dll_directory()` + `ctypes.WinDLL()` **antes** de
  importar `QtMultimedia` hace que Qt los use (confirmado con `GetModuleFileNameW`). Hay
  que respetar el orden de dependencias: `avutil` → `swresample` / `swscale` → `avcodec`
  → `avformat`. Eso sí, exige código en `main.py`, así que sirve como herramienta de
  desarrollo, no como mecanismo de producción.
- **macOS es un flujo aparte.** Harían falta los `.dylib` equivalentes, y sustituir
  archivos dentro de un `.app` **rompe la firma**: habría que hacerlo *antes* de firmar,
  al contrario que en Windows. Ver §3 — en M1/M2 AV1 falla siempre.

### Alternativas descartadas

| Alternativa | Por qué se descartó |
|---|---|
| **Pre-transcodificar el archivo entero** | 4 horas de 4K AV1 tardarían ~34 min (medido a 7,06×), y más de una hora con material real. Inaceptable para una vista previa. |
| **Transcodificar bajo demanda** (modelo Shutter Encoder) | Técnicamente viable y rápido (salto a cualquier punto en ~0,35 s, ventana de 2 s reproducible en ~0,5 s; el tiempo de salto no crece con la posición). Pero exige escribir un pipeline de medios completo: un flujo transcodificado en vivo no es buscable, y `QMediaPlayer` espera una fuente HTTP con soporte de `Range`. |
| **`QT_MEDIA_BACKEND=windows`** | Qt afirma que su backend de Windows sí reproduce AV1, y es solo una variable de entorno. Pero cambia el backend multimedia de toda la app; el de FFmpeg es el predeterminado por ser más consistente entre plataformas. **Sin probar.** |
| **Builds de gyan.dev en vez de BtbN** | Ver §8. |

---

## 8. Por qué BtbN y no gyan.dev

Tres bloqueos independientes; cualquiera descalifica a gyan:

1. **Licencia.** Gyan declara *"All builds are 64-bit, static and licensed as GPLv3"*. No
   publica variantes LGPL (el LGPLv3 de su web corresponde a herramientas auxiliares).
   Estos DLL se cargan **dentro** del proceso de DowP, así que el GPL afectaría a toda la
   aplicación — a diferencia de `ffmpeg.exe`, que es un ejecutable separado y por eso no
   plantea ese problema.
2. **Versión.** Gyan solo publica la última release (9.0.2) y git master. Qt necesita la
   rama **7.1** (`avcodec-61`); FFmpeg 9 usa otro número de ABI y Qt no lo cargaría.
3. **Formato.** `.7z`, que requiere 7-zip. BtbN entrega `.zip`.

**Obligación de licencia:** al distribuir el build LGPL hay que incluir el aviso y el
texto de la licencia, y permitir que el usuario sustituya la librería (lo cual se cumple
solo por ser DLL sueltos).

---

## 9. Estado y decisión pendiente

- El diagnóstico está **cerrado y verificado**.
- La solución está **probada y medida**, pero **no aplicada**.
- Sigue abierto si compensa: hasta ahora hay **un solo caso reportado**, y surgió de
  refilón mientras se probaba otra cosa.
- **Disparador razonable para retomarlo:** un segundo reporte de AV1, o cualquier usuario
  de Mac con Apple Silicon M1/M2, donde el fallo es sistemático.

---

## Referencias

- [QTBUG-119711](https://bugreports.qt.io/browse/QTBUG-119711) — Qt reconoce que su FFmpeg no decodifica AV1 (sin resolver)
- [QTBUG-117118](https://bugreports.qt.io/browse/QTBUG-117118) — incidencia original, mismos errores
- [Advanced FFmpeg Configuration — Qt 6](https://doc.qt.io/qt-6/advanced-ffmpeg-configuration.html) — variables `QT_FFMPEG_DECODING_HW_DEVICE_TYPES` y afines
- [BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds) — builds usados
- [dav1d — VideoLAN](https://www.videolan.org/projects/dav1d.html)
- [shutter-encoder](https://github.com/paulpacifico/shutter-encoder) — `src/shutterencoder/ui/videoplayer/VideoPlayerCore.java`
