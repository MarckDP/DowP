# Separación de stems (BS-Roformer SW) con ONNX: investigación

Estado: **aparcado** (2026-09-24). Funciona y la calidad es la de UVR, pero en GPU con
DirectML es **2 a 4 veces más lento** que UVR con PyTorch y CUDA. Todo lo de abajo está
probado en la RTX 3060 (Windows, onnxruntime-directml 1.24.4). No se tocó código de DowP.

Idea original: una función "Separar stems" en **Herramientas Multimedia → Herramientas IA**
(y su categoría de preajustes de IA), usando los mismos modelos que UVR pero en ONNX, sin
PyTorch.

---

## 1. Modelos evaluados

Todos son **el mismo modelo**: BS-Roformer SW "Fixed" de jarredou, con 6 stems en este
orden: `bass, drums, other, vocals, guitar, piano`. Es el que en UVR aparece como
`BS-Rofo-SW-Fixed.ckpt`, alias "BS Roformer 1" en mi instalación (699 MB).

| Exportación | Tamaño | CPU | GPU (DirectML) | Bloque |
|---|---|---|---|---|
| [bdsqlsz/BS-ROFO-SW-Fixed-ONNX](https://huggingface.co/bdsqlsz/BS-ROFO-SW-Fixed-ONNX) `model.onnx` | 706 MB | ✔ correcto | ✔ **correcto** (igual que la CPU) | variable |
| [elicwhite/bs-roformer-sw-6stem-onnx](https://huggingface.co/elicwhite/bs-roformer-sw-6stem-onnx) fp32 | 701 MB | ✔ idéntico a PyTorch | ✘ **basura** (rápido pero incorrecto) | fijo 4 s |
| elicwhite fp16 | 353 MB | ✔ (calcula en fp32, **misma velocidad**) | ✘ basura | fijo 4 s |

- **La única que sirve para DowP es la de bdsqlsz.** Las de elicwhite están retocadas para
  onnxruntime-web/WebGPU (Split/Concat partidos en árboles, ejes positivos) y algo de eso
  hace que DirectML calcule mal **sin dar error**. Tampoco mejora sin optimizaciones de
  grafo (se probó `ORT_DISABLE_ALL` y `ORT_ENABLE_BASIC`).
- ⚠ Lección general: **cada modelo nuevo hay que validarlo en GPU contra la CPU** antes de
  meterlo al catálogo. `is_gpu_failure` no detecta una salida incorrecta sin excepción.
- fp16 de elicwhite solo ahorra descarga: los pesos se guardan en fp16 y se convierten a
  fp32 al cargar.
- El repo original `jarredou/BS-ROFO-SW-Fixed` **ya no es accesible** (la API de HF devuelve
  error de acceso). bdsqlsz es una resubida de terceros: si desaparece, no hay de dónde
  descargar.
- **Licencia:** elicwhite avisa de que los pesos fueron resubidos por jarredou **sin licencia
  declarada ni procedencia conocida**. El código (lucidrains, ZFTurbo, elicwhite) es MIT.

### Contrato del ONNX de bdsqlsz (`model.json` del repo)

- Entrada `stft_features`: `[batch, frames, 4100]` float32.
  4100 = 1025 frecuencias × 2 canales × 2 (real/imag).
- Salida `mask`: `[batch, 6, 2050, frames, 2]`, una **máscara compleja** por stem.
- **La STFT y la iSTFT van fuera del modelo:** n_fft 2048, hop 512, ventana Hann de 2048,
  `center=True`, sin normalizar, 44,1 kHz estéreo.
- `chunk_size` de exportación: 563 200 muestras. En la práctica acepta cualquier número de
  fotogramas.

---

## 2. Implementación probada (numpy puro, sin dependencias nuevas)

STFT/iSTFT en numpy: **error de 1,8e-7 frente a `torch.stft`**, con la referencia de
elicwhite.

```python
N_FFT, HOP = 2048, 512
WIN = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(N_FFT) / N_FFT)).astype(np.float32)  # Hann periódica

def stft(x):                     # (canales, muestras) -> (canales, 1025, T) complejo
    pad = N_FFT // 2
    x = np.pad(x, ((0, 0), (pad, pad)), mode="reflect")
    frames = 1 + (x.shape[1] - N_FFT) // HOP
    idx = np.arange(N_FFT)[None, :] + HOP * np.arange(frames)[:, None]
    return np.fft.rfft(x[:, idx] * WIN, axis=-1).transpose(0, 2, 1)

def istft(spec, length):         # (canales, 1025, T) -> (canales, length)
    frames = np.fft.irfft(spec.transpose(0, 2, 1), n=N_FFT, axis=-1) * WIN
    T = spec.shape[2]; total = N_FFT + HOP * (T - 1)
    out = np.zeros((spec.shape[0], total)); norm = np.zeros(total)
    for t in range(T):
        out[:, t*HOP:t*HOP+N_FFT] += frames[:, t]; norm[t*HOP:t*HOP+N_FFT] += WIN ** 2
    pad = N_FFT // 2
    return (out / np.maximum(norm, 1e-8))[:, pad:pad + length].astype(np.float32)
```

Organización de la entrada y aplicación de la máscara (igual que el `forward` de
BS-Roformer en ZFTurbo): `b s f t c -> b (f s) t c -> b t (f s c)`.

```python
def model_chunk(session, part):                      # (2, C) -> (6, 2, C)
    spec = stft(part)                                                 # (s, f, t)
    ri = np.stack([spec.real, spec.imag], -1).astype(np.float32)      # (s, f, t, c)
    fs = ri.transpose(1, 0, 2, 3).reshape(1025 * 2, -1, 2)            # ((f s), t, c)
    feats = fs.transpose(1, 0, 2).reshape(1, fs.shape[1], -1)         # (1, t, 4100)
    mask = session.run(None, {"stft_features": feats})[0][0]          # (6, (f s), t, c)
    mix = (fs[..., 0] + 1j * fs[..., 1])[None]
    out = (mix * (mask[..., 0] + 1j * mask[..., 1])).reshape(6, 1025, 2, -1).transpose(0, 2, 1, 3)
    return np.stack([istft(out[i], part.shape[1]) for i in range(6)])
```

Troceado ("demix"), el mismo algoritmo de ZFTurbo/UVR para Roformer:

- bloques de `chunk` muestras que avanzan `chunk // overlap`;
- ventana con fundido de `chunk // 10` en los bordes (sin fundido al principio del primer
  bloque ni al final del último);
- relleno reflejado de `chunk - step` al principio y al final;
- suma ponderada de los bloques y división por la suma de las ventanas.

**Instrumental = mezcla − voz.** Comprobado: el "Instrumental" que guarda UVR coincide con
`mezcla - voz` a 66,5 dB.

Audio de entrada: `ffmpeg -i <archivo> -f f32le -ac 2 -ar 44100 -` por tubería. Salida: un
ffmpeg por stem (`-f f32le ... -c:a pcm_s16le`, o FLAC/MP3).

Los scripts completos de prueba quedaron en la carpeta temporal de la sesión, que no es
permanente: `separate_test.py`, `compare_uvr.py`, `probe*.py`, `batch.py`. Lo esencial
está copiado arriba.

---

## 3. Configuración de UVR para este modelo

`UVR/models/MDX_Net_Models/model_data/mdx_c_configs/BS-Rofo-SW-Fixed.yaml`:

- `audio.chunk_size: 588800` (**13,35 s** por bloque), `n_fft 2048`, 44,1 kHz, estéreo.
- `inference.num_overlap: 2`, `normalize: false`.
- En la interfaz de UVR el "Overlap" (`overlap_mdx23`) es **cuántas veces se calcula cada
  trozo**: el avance es `chunk / overlap`. **El tiempo crece en proporción directa al
  overlap.** Yo lo tenía en 10.

---

## 4. Prueba con una canción real

"Loop of love - Los Retros" (2:44; batería, piano y voz, grabación limpia). Comparada con
la salida de UVR (bloques de 13,35 s y, probablemente, overlap 8).

| | Tiempo | Voz vs UVR | Instrumental vs UVR |
|---|---|---|---|
| UVR, CUDA, overlap 4 | **1:55** | — | — |
| UVR, CUDA, overlap 8 | 3:41 | referencia | referencia |
| ONNX, DirectML, bloque 8 s, overlap 4 | 7:24 (+30 s de carga) | 35,7 dB | 45,5 dB |
| ONNX, DirectML, bloque 8 s, overlap 2 | 3:46 (+30 s de carga) | 33,8 dB | 43,6 dB |

- **Calidad = la de UVR.** Por encima de 30 dB la diferencia es inaudible en la práctica,
  y no hay desfase. Las pequeñas diferencias vienen de usar bloques de 8 s en vez de 13,35 s.
- **Overlap 2 frente a 4 (ONNX):** voz, batería y piano casi iguales (34 a 38 dB). Bajo,
  guitarra y "other" cambian más (8 a 13 dB), pero en esta canción son pistas casi vacías
  (solo restos). Al oído no se distinguen overlap 4 y 8 en UVR.

---

## 5. Rendimiento (el problema)

Reparto del tiempo en un bloque de 8 s: STFT 0,06 s · **modelo 4,5 a 5,5 s** · máscara
0,06 s · iSTFT ×6 0,27 s. **El modelo es el 95 %.** Durante el proceso la GPU se veía al
~11 % de uso.

Coste del modelo por segundo de audio y por pasada:

| Bloque | DirectML | CPU |
|---|---|---|
| 4 s | 0,53 s | ~2,4 s |
| 6 s | 0,64 s | |
| 8 s | 0,62 s | |
| 10 s | 0,65 s | |
| 12,8 s | **5,9 s** (se atasca: más lento que la CPU) | 3,2 s |
| UVR, CUDA, PyTorch (deducido de sus tiempos) | **~0,17 s** | |

- **Agrupar bloques no ayuda:** con bloques de 4 s el coste queda igual; con bloques de
  8 s se dispara (lote de 2: 2,6 s/s; lote de 4: 8,7 s/s).
- Por eso no se pueden usar los bloques de 13,35 s de UVR en DirectML. Hay que usar 8 a
  10 s.
- Cargar el modelo (706 MB, fp32) en DirectML tarda unos 30 s. En DowP se pagaría una vez
  por sesión (`onnx_sessions` guarda la sesión en caché).
- Estimación para 4 minutos de canción en la 3060: overlap 2 ≈ 5 a 6 min, overlap 4 ≈ 10
  a 11 min. En CPU (Mac, PCs sin GPU), más de 25 min incluso con overlap 2.

---

## 6. Otras familias de UVR

- **MDX-Net** (`UVR-MDX-NET-Inst_HQ_3`, `Kim_Vocal_2`, `UVR-MDX-NET-Voc_FT`…): **UVR ya los
  distribuye en ONNX** (~67 MB cada uno) desde
  `https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/<nombre>.onnx`.
  - Inst HQ 3 probado: entrada `[batch, 4, 3072, 256]`. **GPU y CPU dan el mismo
    resultado.** 0,13 s por bloque de ~6 s en DirectML y 2,5 s en CPU. Muy rápido.
  - Solo separa en 2 (voz/instrumental), con calidad inferior a Roformer.
  - Cada modelo tiene sus propios parámetros (n_fft, dim_f, compensación) en el
    `model_data.json` de UVR.
- Otros modelos que tengo instalados en UVR (todos `.ckpt`, habría que buscar si existen
  en ONNX): `MelBandRoformer.ckpt` (Kim), `mel_band_roformer_karaoke_aufr33_viperx`,
  `melband_roformer_instvoc_duality_v1`, `model_bs_roformer_ep_317_sdr_12.9755` (Viperx).
- Pendiente: armar un top 5 de los mejores modelos actuales y comprobar cuáles existen en
  ONNX y **cuáles funcionan bien en DirectML**.

---

## 7. Opciones para retomarlo

1. **Aceptar la velocidad** con overlap 2 por defecto (el doble de lo que tarda UVR con
   overlap 4, con calidad equivalente). Niveles: Rápido = 2, Equilibrado = 4,
   Máxima = 8. En CPU, solo razonable "Rápido".
2. **Exportación propia en fp16 real** (pesos y cálculo a media precisión), desde el
   `.ckpt`, con PyTorch en un entorno aparte (fuera de DowP y de su `requirements.txt`).
   Podría rondar el doble de velocidad en RTX con DirectML; **no está garantizado**.
   Además permitiría alojar el modelo nosotros (por ejemplo, en las releases de GitHub) y
   no depender de bdsqlsz.
3. **onnxruntime con CUDA**, solo NVIDIA. Probablemente iguala a UVR, pero implica
   **cambiar dependencias** (requiere permiso), descargar CUDA/cuDNN (más de 1 GB) como
   paquete opcional, y no ayuda a AMD, Intel ni Mac.
4. Ofrecer también **MDX-Net** como opción rápida de voz/instrumental.

## 8. Qué habría que construir en DowP (complejidad: media)

**Se reutiliza:**
- descarga de modelos con progreso (`ModelDownloadManager`), Ajustes > Modelos y
  licencias;
- `onnx_sessions` con paso a CPU;
- cola de trabajos pesados, recorte, preajustes de IA y filtro por modo
  (se ofrecería en Solo Audio y Video + Audio).

**Nuevo:**
- motor de separación: ffmpeg → bloques con solape → STFT → modelo → iSTFT → un ffmpeg
  por stem, escribiendo mientras avanza;
- **varios archivos de salida** por entrada (`cancion_vocals.wav`…). La cola y el
  historial ya aceptan varias salidas por trabajo;
- opciones: qué stems exportar (o "voz + instrumental"), formato (WAV/FLAC/MP3), overlap;
- **aceptar archivos de solo audio** en Herramientas IA (hoy se omiten con
  "Omitido (sin video)");
- cuarta función en el selector de Herramientas IA y categoría de preajustes;
- validación de cada modelo en GPU antes de añadirlo al catálogo.
