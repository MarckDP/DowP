# 📦 DowP: Créditos y Licencias

DowP es un proyecto **open-source**, **no comercial** y con su código completamente público. Esto permite cumplir de forma correcta con todas las licencias incluidas, incluso aquellas que requieren copyleft (GPL y AGPL).

---

## 🏗️ Ecosistema del Proyecto

| Componente | Función | Licencia | Repositorio |
|------------|---------|----------|-------------|
| 🐍 **DowP App** | Aplicación Principal (Python) | [GPL v3](https://www.gnu.org/licenses/gpl-3.0.html) | [DowP_Downloader](https://github.com/MarckDP/DowP_Downloader) |
| 🔌 **DowP Extension** | Extensión nativa Adobe (CEP) | [MIT](https://opensource.org/licenses/MIT) | [DowP_Importer-Adobe](https://github.com/MarckDP/DowP_Importer-Adobe) |
| 📦 **Instalador** | Setup y Web | [GPL v3](https://www.gnu.org/licenses/gpl-3.0.html) | [DowP](https://github.com/MarckDP/DowP) |

---

## 🧰 Herramientas y Motores (Toolchain)

Este instalador empaqueta y configura automáticamente las siguientes herramientas de código abierto:

| Herramienta | Función | Licencia | Fuente |
|-------------|---------|----------|--------|
| **yt-dlp** | Motor de descarga | Unlicense | [GitHub](https://github.com/yt-dlp/yt-dlp) |
| **FFmpeg** | Procesamiento multimedia | GPL v3 | [BtbN Builds](https://github.com/BtbN/FFmpeg-Builds) |
| **Poppler** | Renderizado PDF | GPL v2 | [GitHub](https://github.com/oschwartz10612/poppler-windows) |
| **Inkscape** | Vectores (SVG/AI/EPS) | GPL v2+ | [GitLab](https://gitlab.com/inkscape/inkscape) |
| **Ghostscript** | PostScript y PDF | AGPL v3 | [GitHub](https://github.com/ArtifexSoftware/ghostpdl-downloads) |
| **Deno** | JavaScript Runtime | MIT | [GitHub](https://github.com/denoland/deno) |

---

## 🤖 Inteligencia Artificial

DowP utiliza modelos avanzados para tareas de procesamiento de imagen:

### **Eliminación de Fondos**
- **U2Net / ISNet:** Licencia [Apache 2.0](https://github.com/xuebinqin/U-2-Net).
- **BiRefNet:** Licencia [MIT](https://github.com/ZhengPeng7/BiRefNet).
- **RMBG 2.0 (Daniel Gatis):** Licencia [MIT](https://github.com/danielgatis/rembg). Versión incluida automáticamente.
- **RMBG 2.0 Oficial (BriaAI):** Licencia [CC BY-NC 4.0](https://huggingface.co/briaai/RMBG-2.0) (No Comercial). **No incluida**; requiere descarga manual para cumplimiento de licencia.

### **Reescalado (Upscaling)**
- **Real-ESRGAN:** Licencia [BSD-3-Clause](https://github.com/xinntao/Real-ESRGAN).
- **Waifu2x / RealSR / SRMD:** Licencia [MIT](https://github.com/nihui/waifu2x-ncnn-vulkan).

---

## 🐍 Librerías de Python (Librerías Clave)

La aplicación principal hace uso de las siguientes librerías de terceros:

- **Pillow / pillow-avif:** (HPND/BSD-3) Procesamiento de imágenes.
- **CustomTkinter:** (MIT) Interfaz gráfica moderna.
- **rawpy:** (MIT) Lectura de imágenes de cámaras RAW.
- **Flask / Flask-SocketIO:** (BSD/MIT) Comunicación App-Extensión.
- **cairosvg / img2pdf:** (LGPL) Conversión de formatos.

---

## ⚖️ Declaración de Cumplimiento

DowP cumple con los términos de las licencias GPL/AGPL de los componentes incluidos mediante:
1. La **transparencia total** del código fuente en GitHub.
2. El mantenimiento de **todas las atribuciones** y licencias de terceros.
3. El carácter **no comercial** y gratuito del proyecto.

**Si redistribuyes este instalador:** Debes mantener este archivo intacto, proporcionar acceso al código fuente y no añadir restricciones adicionales a las licencias copyleft incluidas.

---

**Todas las marcas registradas, logos y tecnologías mencionadas pertenecen a sus respectivos propietarios.**

**Última actualización:** Marzo 2026
