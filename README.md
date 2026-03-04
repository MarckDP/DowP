
# 🚀 DowP: Laboratorio Digital para Editores
<div align="center">
  <img width="1500" height="500" alt="DowP Banner" src="https://github.com/user-attachments/assets/2ad61b9d-a3c5-4268-a603-a19596b41f13" />
</div>

<div align="center">

![License](https://img.shields.io/badge/license-GPL%20v3-blue.svg)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)
![Status](https://img.shields.io/badge/status-Active-success.svg)

**La suite definitiva para descargar, procesar e importar contenido multimedia directamente a Adobe Premiere Pro y After Effects.**

[📥 Descargar Instalador](https://github.com/MarckDP/DowP/releases) • [📖 Manual del Usuario](https://github.com/MarckDP/DowP_App_y_Extension/blob/main/Manual%20del%20DowP.md) • [☕ Apoyar en Ko-fi](https://ko-fi.com/marckdbm)

</div>

---

## ✨ ¿Qué es DowP?

DowP no es solo un descargador; es un **Laboratorio Digital** diseñado por y para editores. Combina la potencia de herramientas industriales como `yt-dlp` y `FFmpeg` con una interfaz intuitiva y funciones de Inteligencia Artificial de vanguardia para acelerar tu flujo de trabajo creativo.

### 🧪 El Ecosistema DowP
El proyecto se divide en tres pilares fundamentales que este instalador configura automáticamente:
1. **DowP App (Python):** El motor principal de descarga y procesamiento.
2. **DowP Importer (CEP):** La extensión nativa que vive dentro de Premiere y After Effects.
3. **DowP Toolchain:** Un conjunto de dependencias pre-configuradas (FFmpeg, Deno, Poppler, etc.) que hacen posible la magia.

---

## 🎨 Características Principales

### 📥 Descarga de "Cirugía Digital"
- **Selección Precisa:** Analiza metadatos, elige códecs específicos y descarga solo el fragmento que necesitas.
- **Calidades Inteligentes:** Indicadores visuales (✨) para archivos listos para edición sin necesidad de recodificar.
- **Cookies y Login:** Soporte nativo para descargar contenido privado o con restricción de edad mediante sesiones de navegador.

### 🛠️ Procesamiento y Recodificación
- **Normalización de Media:** Convierte cualquier archivo a formatos profesionales (ProRes, DNxHD) para evitar lag en el timeline.
- **FPS Constantes (CFR):** Olvida los problemas de sincronización de audio para siempre.
- **Procesamiento por Lotes:** Normaliza carpetas enteras o playlists con un solo clic usando presets globales.

### 🧠 Laboratorio de Imágenes con IA
- **Background Remover 2.0:** Elimina fondos con modelos profesionales (RMBG, ISNet, BiRefNet). Ahora con sliders de **Suavizado** y **Expansión/Contracción** para bordes perfectos.
- **Upscaling Inteligente:** Mejora la resolución de fotos y videos usando motores Real-ESRGAN, Waifu2x y RealSR.
- **Visores Interactivos:** Compara el "Antes y Después" en tiempo real con zoom a nivel de píxel.

### 🔌 Integración con Adobe (CEP Extension)
- **Importación Directa:** Envía descargas automáticamente a tu proyecto y línea de tiempo.
- **Flujo Bidireccional:** Exporta clips de tu timeline directamente a DowP para procesarlos y gestiónalos de vuelta al instante.
- **Sincronización WebSocket:** Comunicación en tiempo real entre la App y Adobe.

---

## 🗃️ Herramientas Incluidas
El instalador se encarga de configurar este potente toolchain por ti:
- **yt-dlp:** El motor de descarga más avanzado.
- **FFmpeg:** El estándar de oro en procesamiento multimedia.
- **Poppler & Inkscape:** Para rasterizar PDF y vectores (AI, EPS, SVG) con precisión quirúrgica.
- **Ghostscript:** Manejo avanzado de postscript y archivos RAW.
- **Deno:** Runtime para procesos de backend ligeros.

---

## 📝 Requisitos del Sistema
- **SO:** Windows 10/11 (64-bit).
- **RAM:** 8 GB mínimo (16 GB recomendado para IA).
- **GPU:** Compatible con Vulkan/Nvidia para aceleración de IA (opcional pero recomendado).
- **Adobe:** Premiere Pro o After Effects 2020 o superior para la extensión.

---

## 🏗️ Estructura del Proyecto
DowP es un ecosistema de código abierto dividido en varios repositorios:

| Componente | Función | Repositorio |
|------------|---------|-------------|
| 🐍 **DowP App** | Aplicación de escritorio (Python/PyQt6) | [DowP_Downloader](https://github.com/MarckDP/DowP_Downloader) |
| 🔌 **Extensión** | Panel nativo para Adobe (JS/CEP) | [DowP_Importer-Adobe](https://github.com/MarckDP/DowP_Importer-Adobe) |
| 📦 **Instalador** | Setup y Web (este repo) | [DowP](https://github.com/MarckDP/DowP) |

---

## 📖 Documentación y Soporte
- 📘 **[Manual Completo](https://github.com/MarckDP/DowP/blob/main/Manual%20del%20DowP.md):** Guía paso a paso de todas las funciones.
- 💬 **[Reportar Problemas](https://github.com/MarckDP/DowP/issues):** ¿Encontraste un bug? Avísanos aquí.
- 📜 **[Licencias y Créditos](CREDITS.md):** Información sobre componentes de terceros.

---

<div align="center">

**Hecho con ❤️ por MarckDBM y la comunidad.**

[⭐ Star en GitHub](https://github.com/MarckDP/DowP_App_y_Extension) • [☕ Ko-fi](https://ko-fi.com/marckdbm)

*Este proyecto es Software Libre bajo licencia GPL v3. Úsalo, mejóralo y compártelo.*

</div>
