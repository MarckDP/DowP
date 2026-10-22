# Transcripción local — whisper.cpp

Herramientas IA → Transcripción acepta audio y video. El motor y cada modelo son
descargas opcionales; no se añade una dependencia a requirements.txt. Ajustes →
Dependencias administra el motor; Ajustes → Modelos → Transcripción → Whisper
administra los pesos. También se pueden descargar desde la propia herramienta.

La interfaz muestra Preajustes, Reescalado, Profundidad, Normales y Transcripción.
Cada función tiene su página permanente, con ajustes y scroll independientes.
Los modelos se descargan al elegir uno ausente, con el mismo diálogo y estado que
las otras herramientas. La lista agrupa Tiny, Base, Small, Medium, Large y Turbo,
con iconos de descarga o instalado. El botón de ajustes junto al motor abre
Ajustes → Dependencias y desplaza la vista a su tarjeta. Allí se puede descargar,
actualizar, importar, abrir la carpeta contenedora o desinstalar el ejecutable.
La desinstalación conserva los modelos. El botón usa el estilo compartido de rutas.
El panel separa Esenciales y Opcionales; whisper.cpp, vtracer y Ghostscript son
opcionales y no se descargan durante la instalación inicial.

## Alcance

- 33 archivos del repositorio oficial de conversiones GGML, con variantes
  originales y cuantizadas: tiny/base/small/medium (multilingües y `.en`),
  large-v1, large-v2, large-v3 y large-v3-turbo.
- Selector Motor + Modelo; cada modelo incluye su variante y tamaño. Hashes fijados en catálogo.
  No se incluyen derivados comunitarios ni el modelo experimental tinydiarize.
- Idioma automático o manual, transcripción y traducción a inglés cuando el modelo
  lo permite. Turbo y `.en` no ofrecen traducción.
- Una salida por trabajo, en dos modos (ver "Salida" abajo). Se elige una pista por número o Todas;
  Todas desglosa el archivo en una fila por pista, con resultados `_pista1`,
  `_pista2`, etc. Cada fila conserva su recorte y puede cancelarse. Los recortes se
  respetan y sus marcas temporales empiezan en cero.
- Cola pesada compartida, progreso, cancelación, nombres y conflictos habituales.
  El destino solo se reemplaza después del éxito; los temporales se limpian.
- Preajustes de transcripción dentro de Herramientas IA. Se excluyen de las cadenas
  de video/recodificación de Multimedia y posdescarga, que esperan un video.
- No hay diarización, OCR, traducción a otros destinos ni envío automático de texto
  al editor en esta primera integración. Los subtítulos se pueden arrastrar o revelar.

## Salida

whisper-cli siempre escribe su JSON completo (`-ojf`: cada segmento y cada fragmento de
palabra con su tiempo) y DowP genera el formato elegido en
`core/tabs/video_tools/transcript_formats.py`. Así todos los formatos comparten opciones.

- **Subtítulos:** SRT, VTT, ASS, LRC, TTML y SBV (el de YouTube).
  - Largo de línea (42 por defecto, 0 = sin límite) y 1 o 2 líneas por subtítulo.
  - Corte por frases, por palabras o karaoke. "Por palabras" agrupa de 1 a 10 palabras
    por subtítulo (`transcription_max_words`; 1 = palabra por palabra): un grupo nunca
    cruza el final de una frase ni una pausa de 1 s, y las palabras de cada frase se
    reparten parejas (6 de a 5 son 3 + 3). El karaoke resalta cada palabra cuando se
    dice: `\kf` en ASS y LRC "mejorado" (`<mm:ss.xx>` por palabra).
  - Por palabras y karaoke piden a whisper tiempos por palabra con DTW
    (`-dtw <modelo> -nfa`). Sin `-nfa` los tiempos salen vacíos; desactivar la flash
    attention lo hace algo más lento, por eso solo se activa en esos cortes.
- **Guardar como** (solo en Subtítulos):
  - Archivo de subtítulos.
  - Pista dentro del video: sin recodificar, salvo con recorte (cortar sin recodificar
    empieza en el fotograma clave anterior y desfasaría los subtítulos). MP4/MOV usan
    `mov_text`, WebM `webvtt` y MKV `srt` o `ass` (conserva el estilo). Otros contenedores
    salen en MKV. Se conservan las pistas de subtítulos del original que el contenedor
    admite tal cual, y la nueva lleva el idioma detectado (ISO 639-2).
  - Quemados en la imagen: libass dibuja un ASS con el estilo. Siempre recodifica a MP4
    (H.264 CRF 18 + AAC). Las fuentes de DowP se copian a una carpeta temporal
    (`fontsdir`), porque no están instaladas en el sistema.
  - Un archivo sin video no se puede incrustar: se omite en la cola.
- **Estilo** (ASS y quemados): tamaño (para 1080 de alto; se escala a la resolución de
  cada video), posición, colores de texto, borde y karaoke, negrita y caja de fondo.
  - **Fuente:** solo aparece donde llega al resultado. Al quemar, libass dibuja con ella.
    En una pista ASS dentro de un MKV va adjunta (`-attach`, guardada solo con el nombre
    del archivo), y VLC, mpv y MPC la usan aunque no esté instalada. Un ASS suelto
    depende de las fuentes del equipo que lo reproduce: ahí se usa Arial.
  - Las pistas en MP4, MOV o WebM no conservan el estilo (`mov_text` y `webvtt` no lo
    admiten); la tarjeta lo avisa.
- **Texto:** TXT, Markdown, HTML, RTF, JSON (con las palabras y sus tiempos) y CSV (con
  BOM, para que Excel abra bien los acentos). Párrafos (se separan en pausas de 1 s o
  más) o una línea por segmento, con o sin marcas de tiempo.

## Opciones de audio

- **Vocabulario:** nombres propios, marcas o jerga, como texto inicial (`--prompt`,
  hasta 600 caracteres).
- **Saltar silencios (VAD):** whisper.cpp transcribe solo los tramos con voz detectados
  por Silero VAD: más rápido en audios largos y sin frases inventadas en silencios o
  música. Sensibilidad Normal, Alta (voces bajas), Estricta (música o ruido) o
  Personalizada (umbral `-vt`, silencio mínimo `-vsd`, voz mínima `-vspd`, margen `-vp`
  y tramo máximo `-vmsd`).

## Preajustes de subtítulos de fábrica

Catálogo v3 de `core/utils/default_presets.py`, en Herramientas IA (función
Transcripción): "Redes: 1 palabra", "Redes: 3 palabras", "Redes: 5 palabras" (SRT, una
línea), "Subtítulos estándar (cine y TV)" (SRT, 42 caracteres, 2 líneas) y "Letras de
canciones (karaoke)" (LRC).

- **Sin modelo ni idioma:** usan el modelo del usuario (Proceso Avanzado: el combo
  Modelo, que no se bloquea; Herramientas IA: el de la página Transcripción; Multimedia:
  `whisper_setup.default_model_id`, large-v3-turbo si está o el primero descargado). El
  idioma sale del video o se detecta.
- **Sin "Saltar silencios":** pediría descargar el detector la primera vez.
- Aparecen en Proceso Avanzado (Crear con IA), en Herramientas IA > Preajustes y en
  Herramientas Multimedia > Preajustes. En Multimedia no se encadenan con la
  Recodificación (no producen video): si hay preajuste de los dos, corren por separado
  sobre los mismos archivos.
- El combo de Crear con IA termina en "+ Crear preajuste...", que abre Herramientas IA en
  la página Transcripción; los preajustes nuevos aparecen al instante.

## Proceso Avanzado: Subtítulos > Crear con IA

La tarjeta Subtítulos tiene un selector **Del sitio | Crear con IA**. Siempre empieza en
"Del sitio" (no se recuerda entre medios ni sesiones).

- **Crear con IA** muestra Modelo, Idioma, Formato (SRT, VTT, ASS, LRC, TTML, SBV) y
  Preajuste. Oculta lo del sitio: idioma y formato del sitio, Descargar Subtítulos,
  Descargar con el medio, Limpiar y convertir a SRT y Recortar al fragmento.
  - **Idioma:** si el sitio informa el idioma del video y Whisper lo conoce, se marca
    "(del video)" y queda elegido; si no, "Detectar automáticamente".
  - **Preajuste:** solo los de Transcripción con formato de subtítulos. Con uno elegido,
    Modelo y Formato muestran los suyos y se bloquean; el idioma sigue editable. Lo
    avanzado (corte, karaoke, saltar silencios, vocabulario, estilo) solo llega así.
  - Siempre es un archivo suelto: sin pista ni quemado. Un ASS usa Arial (ver Estilo).
- **Cuándo corre:** cuando el archivo es definitivo (descargado y, si se pidió,
  recodificado o procesado con IA). Se encola un trabajo de transcripción por archivo
  (uno por fragmento), aparte de la cadena de posprocesado. La tarjeta (o la barra en
  SOLO) muestra "Creando subtítulos..." y el arrastre queda bloqueado hasta terminar.
  Si la recodificación falla, se transcribe el original restaurado.
- **Playlists:** la opción vale para toda la playlist (job.config) y cada ítem se
  transcribe inline después de su recodificación (`QueueWorker._transcribe_playlist_item`).
- **Nombre:** como yt-dlp, `video.<idioma>.<formato>` junto al video, con el idioma que
  usó Whisper (el detectado, el elegido o `en` al traducir). El idioma solo se conoce al
  terminar, así que el motor elige el nombre al final (`transcription_name_language`).
  Si ya existe, "Sobrescribir" lo reemplaza; si no, se renombra (`video.es (1).srt`).
- **Antes de empezar** se comprueban el motor, el modelo y el detector de voz (si el
  preajuste lo usa), con el aviso de descarga habitual.

## Detector de voz (Silero VAD)

Complemento de whisper.cpp, en su misma tarjeta de Ajustes → Dependencias. El archivo
(885 KB, MIT) se guarda en la carpeta de modelos (`whisper/ggml-silero-v<versión>.bin`)
y solo se conserva una versión.

- La versión probada (`VAD_MODEL` en `core/whisper_catalog.py`, v6.2.0 con whisper.cpp
  1.9.5) es la que instala la casilla "Saltar silencios" sin consultar la red.
- Buscar Actualizaciones consulta `https://huggingface.co/api/models/ggml-org/whisper-vad?blobs=true`,
  elige la versión más alta, la fija a la revisión consultada y verifica tamaño y SHA-256.
- Si whisper falla con una versión más nueva que la probada, el error explica cómo
  volver a ella (eliminarla y volver a marcar la casilla).
- Los preajustes con "Saltar silencios" piden descargar el detector si falta.

## Distribución del motor y límite de los binarios oficiales

El paquete de respaldo es whisper.cpp v1.9.5, cuya publicación enlaza los assets b5454.
Buscar Actualizaciones consulta la última versión estable oficial y, si enlaza una
publicación de binarios separada, resuelve sus assets. La tarjeta compara con la
versión del ejecutable instalado; Actualizar descarga el paquete encontrado y
verifica su tamaño y SHA-256 publicado. Si no existe un asset nativo verificable,
se informa y se mantiene la importación manual. Los paquetes importados que no
informan su versión se muestran como desconocidos, sin afirmar que están al día.
Windows x64/ARM64: CLI CPU oficial; Linux x64/ARM64: paquete Ubuntu oficial
(su compatibilidad con otras distribuciones debe probarse). Los archivos se
comprueban por tamaño y SHA-256 antes de extraerlos e instalarse.

Esa publicación NO ofrece CLI macOS ni paquete Windows Vulkan. El XCFramework de
Apple no se puede ejecutar como whisper-cli. No se inventan enlaces ni se compila
en el equipo del usuario. En esas plataformas se puede importar un ZIP/tar.gz con
whisper-cli y sus bibliotecas; la instalación valida que el CLI pueda ejecutarse.

`tools/build_whisper_runtime.py` prepara paquetes en la máquina del publicador:

```text
python tools/build_whisper_runtime.py --backend metal --output scratch/whisper-metal
python tools/build_whisper_runtime.py --backend vulkan --output scratch/whisper-vulkan
```

Ejecutar cada compilación en su SO/arquitectura, con CMake, compilador C++ y, para
Vulkan, el SDK correspondiente. El script no instala dependencias, no publica y
no toca Git. La compilación estática evita llevar libwhisper/ggml aparte.
Antes de distribuir: probar en máquina limpia, comprobar GPU/CPU y dependencias
del SO, incluir licencias y publicar el paquete validado con hash. Entonces se
puede agregar su URL real a `whisper_setup.py`. Estos paquetes Metal/Vulkan aún
no están publicados ni verificados en sus plataformas.

## Fuentes

- https://github.com/ggml-org/whisper.cpp/releases/tag/v1.9.5
- https://github.com/ggml-org/whisper.cpp/releases/tag/b5454
- https://huggingface.co/ggerganov/whisper.cpp

## Comprobación local

```text
python -m unittest discover -s app/tests -v
```

`test_transcript_formats.py` cubre los formatos, el karaoke, el estilo, el detector de
voz y los comandos de incrustado con un JSON de whisper simulado. La prueba real debe
usar además un modelo descargado y audio conocido, comprobar cada formato, palabra por
palabra, pista y quemado (con y sin recorte), silencio, archivo sin audio y cancelación.
Las pruebas unitarias no descargan modelos ni acceden a Internet.
