# 🚀 DowP Installer

<div align="center">
  <img width="1500" height="500" alt="DowP Banner" src="https://github.com/user-attachments/assets/2ad61b9d-a3c5-4268-a603-a19596b41f13" />
</div>

<div align="center">

![License](https://img.shields.io/badge/license-GPL%20v3-blue.svg)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)
![Status](https://img.shields.io/badge/status-Active-success.svg)

**Instalador oficial de DowP y su extensión para Adobe**

[📥 Descargar](#) • [📖 Manual](https://github.com/MarckDP/DowP_App_y_Extension/blob/main/Manual%20del%20DowP.md) • [☕ Apoyar](https://ko-fi.com/marckdbm)

</div>
---

## 📥 Instalación

1. **Descarga** el instalador desde [Releases](#)
2. **Ejecuta** el archivo `.exe`
3. **Sigue** el asistente de instalación
4. **Listo** - DowP se configurará automáticamente

### 🔧 **El instalador se encarga de:**
- ✅ Instalar la aplicación principal
- ✅ Configurar todas las herramientas necesarias
- ✅ Instalar la extensión de Adobe (opcional)
- ✅ Descargar modelos de IA básicos
- ✅ Crear accesos directos

> **Nota:** Los modelos de IA adicionales se descargan automáticamente la primera vez que los uses.
---

## 📦 ¿Qué incluye este instalador?

Este setup instala de forma automática y sin complicaciones:

### 🐍 **DowP** - Aplicación Principal
Programa gratuito y de código abierto para descargar, procesar y mejorar contenido multimedia.

**Repositorio:** [github.com/MarckDP/DowP_Downloader](https://github.com/MarckDP/DowP_Downloader)

### 🔌 **DowP Importer** - Extensión para Adobe
Extensión que conecta DowP con Premiere Pro y After Effects para importar automáticamente tus descargas.

**Repositorio:** [github.com/MarckDP/DowP_Importer-Adobe](https://github.com/MarckDP/DowP_Importer-Adobe)

### 🛠️ **Herramientas de Procesamiento**
Todas las dependencias necesarias pre-configuradas:
- **FFmpeg** - Conversión multimedia
- **yt-dlp** - Motor de descarga
- **Poppler** - Procesamiento de PDF
- **Inkscape** - Manejo de vectores SVG
- **Ghostscript** - PostScript y PDF
- **Deno** - Runtime JavaScript

---

## ✨ Características Principales de DowP

### 📥 **Descarga Multimedia**
- ✅ Videos y audio de múltiples plataformas web
- ✅ Selección de calidad y formato personalizado
- ✅ Descarga por lotes
- ✅ Extracción de subtítulos
- ✅ Descarga de miniaturas y metadatos

### 🎬 **Procesamiento de Video**
- ✅ Recodificación con control total de parámetros
- ✅ Conversión entre formatos (MP4, WebM, MKV, AVI, MOV, etc.)
- ✅ Ajuste de resolución y bitrate
- ✅ Extracción y conversión de audio
- ✅ Procesamiento de archivos locales

### 🎨 **Procesamiento de Imágenes con IA**
- ✅ **Eliminación de fondos** con múltiples modelos:
  - U2Net / U2NetP (rápido y ligero)
  - ISNet (alta precisión)
  - BiRefNet (bordes definidos)
  - RMBG 2.0 (calidad profesional)
- ✅ **Reescalado inteligente (Upscaling)** con IA:
  - Real-ESRGAN (uso general)
  - Waifu2x (optimizado para anime)
  - RealSR (fotografías reales)
  - SRMD (degradaciones múltiples)
- ✅ Conversión entre formatos de imagen
- ✅ Procesamiento por lotes

### 📄 **Conversión de Documentos**
- ✅ **PDF** → Imágenes (PNG, JPG, TIFF, BMP)
- ✅ **Imágenes RAW** → Formatos estándar
- ✅ **SVG** → Formatos rasterizados
- ✅ **PostScript/EPS** → PDF o imágenes
- ✅ Conversión masiva con configuración personalizada

---

## 🔌 Integración con Adobe (DowP Importer)

La extensión se conecta mediante WebSocket a la aplicación principal:

### ✨ **Características de la Extensión**

#### 📥 **Importación Automática**
- Importa directamente a tu proyecto todo lo descargado:
  - Videos, audios, imágenes
  - Subtítulos, miniaturas
  - Documentos convertidos
- Organización automática en carpeta `DowP Imports`

#### ⏱️ **Integración con Timeline**
- Envía medios directamente a la línea de tiempo
- Respeta puntos de entrada y duración
- Compatible con ambas aplicaciones:
  - ✅ Adobe Premiere Pro
  - ✅ Adobe After Effects

#### 🔄 **Comunicación Bidireccional**
- Exporta clips de tu timeline a DowP para procesarlos
- Re-importa automáticamente después del procesamiento
- Sincronización en tiempo real

---

## 💾 Requisitos del Sistema
- Windows 10/11 (64-bit)
- 8 GB RAM o más
- GPU compatible con Vulkan (para upscaling acelerado)
- Conexión a internet (para descargas y modelos de IA)

### **Para la Extensión**
- Adobe Premiere Pro 2020 o superior
- Adobe After Effects 2020 o superior

---

## 📖 Documentación

- 📘 **Manual Completo:** [Manual del DowP](https://github.com/MarckDP/DowP_App_y_Extension/blob/main/Manual%20del%20DowP.md)
- 🔧 **DowP App:** [Repositorio y documentación](https://github.com/MarckDP/DowP_Downloader)
- 🔌 **Extensión:** [Repositorio y documentación](https://github.com/MarckDP/DowP_Importer-Adobe)
- 📄 **Licencias:** [CREDITS.md](CREDITS.md)

---

## 🤝 Contribuir y Soporte

### 💖 Apoya el Proyecto
Si DowP te resulta útil, considera apoyar su desarrollo:

[![Ko-fi](https://img.shields.io/badge/Ko--fi-Support-ff5e5b?logo=ko-fi&logoColor=white)](https://ko-fi.com/marckdbm)

### 🐛 Reportar Problemas
¿Encontraste un bug o tienes una sugerencia?
- App principal: [Issues de DowP](https://github.com/MarckDP/DowP_Downloader/issues)
- Extensión: [Issues de DowP Importer](https://github.com/MarckDP/DowP_Importer-Adobe/issues)
- Instalador: [Issues de este repo](https://github.com/MarckDP/DowP_App_y_Extension/issues)

---

## 📜 Licencias

### **Componentes del Instalador**
- **DowP:** GPL v3 (incluye FFmpeg, Poppler, Inkscape, Ghostscript)
- **DowP Importer:** MIT
- **Script del Instalador:** GPL v3

Para información detallada sobre todas las licencias de componentes de terceros, consulta [CREDITS.md](CREDITS.md).

---

## ❓ Preguntas Frecuentes

<details>
<summary><b>¿Necesito instalar FFmpeg o yt-dlp por separado?</b></summary>

No, el instalador incluye todas las herramientas necesarias pre-configuradas.
</details>

<details>
<summary><b>¿Los modelos de IA requieren GPU?</b></summary>

No son obligatorios, pero los modelos de upscaling NCNN pueden aprovechar GPU Vulkan para acelerar el procesamiento.
</details>

<details>
<summary><b>¿Funciona sin conexión a internet?</b></summary>

Una vez instalado, puedes usar las funciones de procesamiento local sin internet. Las descargas web obviamente requieren conexión.
</details>

<details>
<summary><b>¿Puedo usar solo la app sin la extensión?</b></summary>

Sí, la extensión es completamente opcional. DowP funciona perfectamente de forma independiente.
</details>

<details>
<summary><b>¿Qué formatos de video soporta?</b></summary>

Todos los formatos que soporta FFmpeg: MP4, MKV, WebM, AVI, MOV, FLV, M4V, y muchos más.
</details>

---

## 🏗️ Repositorios del Proyecto

| Componente | Repositorio | Licencia |
|------------|-------------|----------|
| 🐍 **App Principal** | [DowP_Downloader](https://github.com/MarckDP/DowP_Downloader) | GPL v3 |
| 🔌 **Extensión Adobe** | [DowP_Importer-Adobe](https://github.com/MarckDP/DowP_Importer-Adobe) | MIT |
| 📦 **Instalador (este repo)** | [DowP_App_y_Extension](https://github.com/MarckDP/DowP_App_y_Extension) | GPL v3 |

---

<div align="center">

**Hecho con ❤️ por la comunidad**

[⭐ Star en GitHub](https://github.com/MarckDP/DowP_App_y_Extension) • [🐛 Reportar Bug](#) • [💡 Sugerir Feature](#)

---

*DowP es software libre. Si te resulta útil, considera [apoyar el proyecto](https://ko-fi.com/marckdbm).*

</div>
