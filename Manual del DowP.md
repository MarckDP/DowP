# Manual de Uso - DowP

## Tabla de Contenidos
1. [Descripción General](#descripción-general)
2. [Instalación](#instalación)
3. [Guía de Inicio Rápido](#guía-de-inicio-rápido)
4. [Modo URL](#modo-url)
5. [Modo Recodificación Local](#modo-recodificación-local)
6. [Configuración de Recodificación](#configuración-de-recodificación)
7. [Solución de Problemas](#solución-de-problemas)
8. [Preguntas Frecuentes](#preguntas-frecuentes)

---

## Descripción General

DowP es una interfaz gráfica (GUI) diseñada para simplificar el uso de **yt-dlp** y **ffmpeg**. Permite descargar videos de múltiples plataformas y recodificarlos para optimizar su compatibilidad con editores de video profesionales, especialmente **Adobe Premiere Pro**.

### Características Principales
- Descarga de videos desde múltiples plataformas
- Recodificación opcional para compatibilidad con editores
- Extracción y conversión de subtítulos
- Segmentación de videos
- Procesamiento de archivos locales
- Soporte para múltiples formatos y códecs

<div align="center">
  <img width="300" height="451" alt="image" src="https://github.com/user-attachments/assets/ac367935-bc6e-43ef-be37-fd9cb7e01d31" />
  <img width="300" height="451" alt="image" src="https://github.com/user-attachments/assets/fa4c0c7d-83c4-49e1-abd9-b215d6adb021" />
  <img width="300" height="451" alt="image" src="https://github.com/user-attachments/assets/c089d6fb-034b-4bb6-8b12-d2edc19063d3" />

</div>

---

## Instalación

Solo instala la app y su extension desde el Set-Up, si no quieres que se instale la extensión, pueden desmarcar la opcion de "Instalar la extensión para Adobe (DowP Importer)" y ya, asi solo usan el DowP como app. 

---

## Guía de Inicio Rápido

### Descarga Básica
1. Pega la URL del video en el campo correspondiente
2. Haz clic en "Analizar"
3. Selecciona la calidad deseada
4. Elige la carpeta de destino
5. Haz clic en "Iniciar Descarga"

### Recodificación Rápida
1. Marca las casillas "Recodificar Video" y/o "Recodificar Audio"
2. Selecciona los códecs deseados
3. Configura los parámetros según tu editor de video
4. Inicia el proceso

---

## Modo URL

El modo URL permite descargar contenido directamente desde internet utilizando cualquier URL compatible con yt-dlp.

### Panel Izquierdo

#### 🖼️ Gestión de Miniaturas
- **Visualización**: La miniatura del video se muestra automáticamente
- **Descarga individual**: Usa "Descargar Miniatura..." para obtener solo la imagen
- **Descarga conjunta**: Activa "Descargar miniatura con el video" para incluirla en la descarga principal

#### ✂️ Segmentación de Video
Permite extraer fragmentos específicos del contenido:

1. **Tiempo de inicio**: Configura hora, minutos y segundos
2. **Tiempo de fin**: Define el punto final del segmento
3. **Opción adicional**: Marca "Descargar también el video completo" si necesitas ambos

#### 📝 Subtítulos
Gestión completa de subtítulos disponibles:

**Selección de Idioma**
- Lista todos los idiomas disponibles

**Formatos**
- Muestra formatos por el idioma seleccionado

**Tipos de Subtítulos**
- **Manual**: Creados por el autor del video
- **Automático**: Generados por la plataforma

**Opciones de Descarga**
- Descarga individual de subtítulos
- Inclusión automática con el video
- **Conversión y estandarización a SRT**: Para formatos diferentes a SRT, se ofrece conversión al formato estándar SRT

#### 🍪 Configuración de Cookies
Para contenido que requiere autenticación:

**Método Manual**
- Usa un archivo de cookies exportado. Recomendado usar [Get Cookies LOCALLY](https://github.com/kairi003/Get-cookies.txt-LOCALLY) para extraer las cookies de tu navegador de preferencia

**Extracción desde Navegador**
- Extrae cookies directamente del navegador seleccionado
- **Recomendación**: Usar Firefox para mejor compatibilidad
- Evita navegadores basados en Chromium por problemas de seguridad (Chrome, Edge, Brave, Opera, etc)
  
> [!WARNING]
> Nunca compartas archivos cookies.txt, contienen tokens de sesión que permiten acceso a tu cuenta.

#### 🔧 Mantenimiento
Actualiza FFmpeg cuando sea necesario, especialmente después de rechazar actualizaciones automáticas.

### Panel Derecho

#### 📋 Gestión de Títulos
- **Visualización**: Muestra el título original del contenido
- **Personalización**: Permite modificar el nombre del archivo final
- **Compatibilidad**: Soporta cualquier carácter especial

#### 🎥 Modos de Descarga
**Video + Audio**
- Descarga completa con video y audio
- Menús separados para calidades de video y audio
- Información detallada de cada opción

**Solo Audio**
- Extracción únicamente del audio
- Ideal para podcasts o música
- Múltiples formatos disponibles

#### 📊 Selección de Calidades
Información detallada para cada opción disponible:
- Resolución y FPS
- Bitrate (Kbps)
- Códec utilizado
- Formato/contenedor
- Tamaño aproximado

**Indicadores de Compatibilidad**

| Símbolo | Descripción |
|---------|-------------|
| ✨ | Óptimo para Adobe Premiere Pro/After Effects |
| ⚠️ | Posibles problemas de compatibilidad (Revisar los mensajes de **Advertencias de Compatibilidad**)|
| `[Streaming]` | Alta calidad pero restrictiva (usar cookies) |
| `[Combinado]` | Video y audio en un solo archivo |
| `[Premium]` | Contenido premium (requiere cookies) |

> [!TIP]
> Las opciones marcadas con ✨ no requieren recodificación.
> Sitios como **X** o **Pinterest** suelen entregar siempre videos en codecs compatibles con Premiere o After Effects y no es necesario recodificar.

#### ⚠️ Advertencias de Compatibilidad
El sistema muestra alertas automáticas sobre:
- Compatibilidad con Adobe Premiere Pro / After Effects
- Necesidad de recodificación
- Recomendaciones específicas

---

## Modo Recodificación Local

Accede con el botón **"Importar Archivo Local para Recodificar"**.

### Cambios en la Interfaz
- **Miniatura**: Muestra fotograma inicial (🎵 para audio)
- **Secciones deshabilitadas**: Descarga de miniaturas y subtítulos
- **Información del archivo**: Los menús de calidad muestran datos del archivo importado
- **Múltiples pistas**: Selección individual de pistas de audio
- **Nueva opción**: "Guardar en la misma carpeta que el original"

### Funcionalidades Especiales
- Conversión entre formatos (ej: video → solo audio)
- Procesamiento de múltiples pistas de audio
- Preservación de metadatos

### Retorno al Modo URL
- Botón **"Limpiar y Volver a Modo URL"**
- O simplemente pega una nueva URL y analiza

---

## Configuración de Recodificación

### Modo "Video + Audio"

#### Opciones Básicas
- **Recodificar Video**: Procesa únicamente el componente visual
- **Recodificar Audio**: Procesa únicamente el componente sonoro
- **Mantener archivos originales**: Conserva o elimina archivos fuente

> [!WARNING]
> Desactivar "Mantener archivos originales" eliminará TODOS los archivos relacionados (video, miniatura, subtítulos).

#### Sistema de Advertencias
**Códigos de Color**
- 🟢 **Verde**: Combinación correcta y compatible
- 🟡 **Amarillo**: Posible incompatibilidad (bajo tu responsabilidad)
- 🔴 **Rojo**: Incompatibilidad total (bloquea el proceso)

#### Configuración de Video
**Tipos de Códecs**
- **GPU**: Aceleración por hardware (H.264, H.265, AV1, VP9)
  - Depende de tu tarjeta gráfica (NVIDIA, AMD, Intel)
- **CPU**: Códecs profesionales (Apple ProRes, DNxHD/HR, GoPro Cineform)

**Parámetros de Códec**
- **Perfil/Calidad**: Específico para cada códec
- **Bitrate**: Opciones CBR (constante) y VBR (variable)
- **Contenedor**: Formato final (MP4, MOV, WebM, etc.)

#### Opciones Avanzadas
**Forzar FPS Constantes (CFR)**
- Evita problemas de sincronización de audio
- Recomendado para edición profesional

**Cambio de Resolución**
- Presets disponibles o personalizada
- Mantener relación de aspecto
- Opción "No ampliar resolución"

> [!WARNING]
> **Importante**: El cambio de resolución estira el video, no lo recorta. Puede causar distorsión si no se respeta la relación de aspecto.

#### Configuración de Audio
- **Códec de Audio**: Solo códecs compatibles con el video seleccionado
- **Perfil de Audio**: Opciones específicas por códec
- **Procesamiento**: Siempre realizado por CPU

### Modo "Solo Audio"

#### Funcionalidades
- Conversión de video a audio
- Extracción de audio de videos existentes
- Recodificación de archivos de audio

#### Configuración
- **Activar Recodificación**: Habilita todas las opciones de procesamiento
- **Códecs Disponibles**: Acceso a todos los códecs de audio soportados
- **Mantener Archivos Originales**: Misma función que en modo video

---

## Opciones de Salida

### Configuración de Destino
- **Selector de Carpeta**: Usa "..." para navegar o escribe la ruta directamente
- **Botón 📂**: Se activa tras completar operaciones para abrir la carpeta de destino
- **Límite de Velocidad**: (Solo modo URL) Previene rechazos por "TOO MANY REQUESTS"

### Controles de Proceso
- **Botón Principal**: 
  - "Iniciar Descarga" (modo URL)
  - "Iniciar Proceso" (modo local)
  - Cambia a "Cancelar" durante operaciones activas

---

## Solución de Problemas

### Errores de Descarga Comunes

#### Problemas de Acceso
**Síntomas**: Errores de autenticación o contenido restringido
**Soluciones**:
1. Configura cookies apropiadas
2. Usa Firefox para extraer cookies del navegador
3. Verifica que tengas acceso al contenido

#### Límites de Velocidad
**Síntomas**: Errores "TOO MANY REQUESTS"
**Soluciones**:
1. Activa el límite de descarga
2. Usa cookies para autenticación
3. Espera entre descargas masivas

#### Problemas con Subtítulos
**Síntomas**: Fallos en descarga de subtítulos automáticos
**Soluciones**:
1. Prefiere subtítulos manuales del creador
2. Usa cookies para contenido restringido
3. Prueba diferentes formatos

### Sistema de Reintentos Automáticos

DowP implementa un sistema de recuperación de tres niveles:

1. **Primer Intento**: Según configuración solicitada
2. **Segundo Intento**: Calidad similar pero menos restrictiva
3. **Tercer Intento**: Método "mejor video + mejor audio" como último recurso
4. **Fallo Total**: Muestra error con recomendaciones específicas

### Problemas con Playlists

**Síntoma**: Error "No se puede encontrar la ruta del archivo"
**Causa**: URLs de playlist en sitios poco comunes
**Solución**: Usar URL del video/audio individual específico

> [!NOTE]
> Las descargas en cola se implementarán en futuras actualizaciones.

### Problemas de Recodificación

#### Errores de Códec
**Verificaciones**:
1. Compatibilidad entre códecs de video y audio
2. Soporte de hardware para códecs GPU
3. Configuración correcta de perfiles

#### Problemas de Rendimiento
**Optimizaciones**:
1. Usa códecs GPU para mejor rendimiento
2. Ajusta configuraciones de bitrate
3. Considera usar códecs CPU para máxima calidad

---

## Preguntas Frecuentes

### ¿Qué sitios son compatibles?
DowP soporta cualquier [sitio compatible](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md) con yt-dlp, incluyendo YouTube, Vimeo, Twitch, y muchos más.

### ¿Necesito configurar algo para Adobe Premiere?
Las opciones marcadas con ✨ son directamente compatibles. Para otras, usa las configuraciones de recodificación recomendadas.

### ¿Puedo procesar múltiples archivos?
Actualmente no. La funcionalidad de procesamiento en lote está planificada para futuras versiones.

### ¿Es seguro usar cookies?
Sí, siempre que no las compartas. Los archivos de cookies contienen tokens de sesión personales.

### ¿Qué hago si FFmpeg no funciona?
Verifica que FFmpeg esté en el PATH del sistema o copia los archivos a la carpeta del programa.

> 🚀 **Futuras Actualizaciones**: Se planean mejoras en procesamiento en lote, más códecs y optimizaciones de rendimiento.
