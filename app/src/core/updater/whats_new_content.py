# src/core/updater/whats_new_content.py
"""Contenido de la ventana de "Novedades" -- una entrada por version, que se
muestra una sola vez tras actualizar (ver core/updater/launcher y
gui/dialogs/whats_new_dialog.py) y de forma permanente en Ajustes > Acerca de.

No es una clase Qt (vive en core/, no en gui/), asi que las cadenas no pueden
usar self.tr() -- se usa QCoreApplication.translate(contexto, texto), la via
estandar de Qt para marcar cadenas traducibles fuera de un QObject.

El contexto ("WhatsNewContent") va como STRING LITERAL en cada llamada, nunca
como variable/constante: el escaneo de pyside6-lupdate es estatico (no
ejecuta el codigo), asi que QCoreApplication.translate(UNA_VARIABLE, "...")
no lo detecta -- confirmado empiricamente, ver ACTUALIZACIONES.md.
"""
from PySide6.QtCore import QCoreApplication

from core.version import IS_BETA
from PySide6.QtCore import QCoreApplication


def get_whats_new_items(version: str) -> list:
    """Devuelve [(titulo, descripcion), ...] para `version`, o [] si esa
    version no tiene novedades registradas (nunca deberia pasar para una
    version publicada, pero evita un IndexError/KeyError si se llama con
    algo inesperado).

    "1.9.0", "1.9.1" y "2.0.0" comparten el mismo contenido comparativo contra
    DowP 1: la 1.9.1 es el primer release publico (el de la 1.9.0 se retiro), asi
    que quien la instala viene de DowP 1, igual que en la 2.0.0 -- lo unico
    que cambia es el aviso de beta, agregado arriba segun IS_BETA. Cuando
    salgan mas betas (1.9.2, 1.9.3...) van a necesitar contenido propio, no
    reusar esto sin mas (ver ACTUALIZACIONES.md, "Lo que falta")."""
    if version == "1.9.4":
        # Quien la ve viene de la 1.9.3. El problema conocido sigue al final.
        return [
            (
                QCoreApplication.translate("WhatsNewContent", "Nueva pestaña Herramientas IA"),
                QCoreApplication.translate("WhatsNewContent", "Reescalado, profundidad, normales y transcripción de video en su propia pestaña, con vista previa y recorte de tramos como en el Gestor de Medios. Los procesos de IA esperan su turno para no competir por la GPU con otras tareas."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Transcripción con IA"),
                QCoreApplication.translate("WhatsNewContent", "Convierte el audio de un video en subtítulos o texto, directamente en tu equipo: SRT, VTT, ASS, LRC, TXT, Markdown, JSON o CSV, como archivo, como pista o quemados en el video. Aprovecha tu GPU y puede saltarse los silencios. En Proceso Avanzado también puedes crear los subtítulos con IA al descargar."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Nueva página Apariencia"),
                QCoreApplication.translate("WhatsNewContent", "Todo el aspecto de DowP en un solo lugar: tus temas en una galería, una vista previa al momento y un botón Aplicar que junta todos los cambios en una sola recarga."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Crea tus propios temas"),
                QCoreApplication.translate("WhatsNewContent", "Crea un tema a partir de una imagen: DowP saca sus colores y te propone variantes para revisar antes de aplicar. También puedes cambiar cualquier color a mano, desde los básicos hasta la lista completa, y ajustar la redondez de la interfaz."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Guarda y comparte tu apariencia"),
                QCoreApplication.translate("WhatsNewContent", "Guarda colores, imágenes, opacidades, letra y redondez en un tema, y vuelve a todo eligiéndolo en la galería. Exporta el tema completo, solo sus colores o un paquete .dthmp con sus imágenes y fuentes. Si algo va a reemplazar tu aspecto, DowP guarda antes una copia como Apariencia anterior."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Imagen de fondo"),
                QCoreApplication.translate("WhatsNewContent", "Pon una imagen tuya detrás de la ventana, con paneles translúcidos y vidrio en los menús. También puedes elegir otra para las vistas previas vacías."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "PDF más livianos"),
                QCoreApplication.translate("WhatsNewContent", "Nueva opción Compresión al convertir a PDF: Baja, Recomendada, Extrema o Personalizado. Un documento escaneado puede pesar hasta 10 veces menos, sin tocar el texto ni la transparencia. También puedes elegir el tamaño de página (A4, Carta u Oficio), y un PDF convertido a PDF conserva todas sus páginas."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Arranque mucho más rápido"),
                QCoreApplication.translate("WhatsNewContent", "DowP abre en un par de segundos: las pestañas y las páginas de Ajustes se cargan cuando hacen falta."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Ajustes > Modelos renovado"),
                QCoreApplication.translate("WhatsNewContent", "Los modelos van agrupados en secciones plegables, con buscador y filtro de descargados. Los modelos importados ya no se copian, y al eliminarlos eliges si quitarlos de la lista o mandarlos a la Papelera. Si a un preajuste le falta su modelo, DowP te ofrece descargarlo."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Potencia del reescalado"),
                QCoreApplication.translate("WhatsNewContent", "Automático ajusta el reescalado a tu GPU, Bajo consumo es para equipos con poca memoria de video, y Personalizado permite elegir los hilos a mano. Si no hay una GPU compatible, DowP te lo dice claramente."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Subtítulos de YouTube sin líneas repetidas"),
                QCoreApplication.translate("WhatsNewContent", "La opción \"Limpiar y convertir a SRT\" quita las líneas duplicadas que traen algunos subtítulos con estilo, sin borrar diálogos reales. Si prefieres el archivo original, desmárcala: DowP recuerda tu elección."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Correcciones en Mac"),
                QCoreApplication.translate("WhatsNewContent", "Los fragmentos ya no fallan al cortarlos, desaparecen las líneas raras de la interfaz, y DowP ya no se cierra de golpe al recodificar por GPU."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Correcciones"),
                QCoreApplication.translate("WhatsNewContent", "Recodificar un video con carátula ya no falla. En Proceso Avanzado, la recodificación y la IA después de descargar un solo video vuelven a funcionar. Arrastrar una descarga o abrirla desde el historial ya no mezcla archivos de otras descargas. Al exportar la consola o un preajuste, DowP propone tu carpeta de descargas o tu carpeta personal."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Problema conocido: subtítulos de YouTube"),
                QCoreApplication.translate("WhatsNewContent", "Sin cookies, YouTube a veces limita la descarga de subtítulos (error 429) y eso cancela toda la descarga, no solo los subtítulos. Mientras lo solucionamos: espera unos minutos antes de reintentar, usa las cookies de tu navegador (Ajustes > Cookies), o descarga el video sin subtítulos y bájalos después con el botón \"Descargar subtítulos\"."),
            ),
        ]

    if version == "1.9.3":
        # Quien la ve viene de la 1.9.2. Las novedades de esta versión se agregan arriba
        # del problema conocido, que conviene dejar al final.
        return [
            (
                QCoreApplication.translate("WhatsNewContent", "Integración con VEGAS Pro"),
                QCoreApplication.translate("WhatsNewContent", "Nueva extensión acoplable para VEGAS Pro (versiones 14 a 22). Envía tus descargas, fragmentos y subclips directamente a la línea de tiempo o al depósito de medios de Vegas con un solo clic. Configúrala desde Ajustes > Integraciones."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Temas con modo claro y oscuro"),
                QCoreApplication.translate("WhatsNewContent", "Cada tema trae su modo claro y su modo oscuro: elige Oscuro, Claro o Según el sistema en Ajustes > General. El modo claro se revisó en toda la app y el cambio se aplica al momento, sin reiniciar."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Cuatro temas nuevos"),
                QCoreApplication.translate("WhatsNewContent", "Tokyo Night, Café Noir, Rubí y Nórdico, cada uno con su modo claro y oscuro. Elígelos en Ajustes > General > Tema visual."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Crea e importa tus temas"),
                QCoreApplication.translate("WhatsNewContent", "Con el botón junto a Tema visual puedes importar, exportar y eliminar temas. Un tema define colores, esquinas, bordes y tamaño de letra, y los temas de DowP 1 se convierten solos al importarlos."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Elige dónde guardar los modelos de IA"),
                QCoreApplication.translate("WhatsNewContent", "Los modelos pueden ocupar varios GB: ahora puedes guardarlos en otro disco desde Ajustes > Modelos, y DowP mueve los que ya tienes descargados."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "RMBG 2.0 con tu cuenta de Hugging Face"),
                QCoreApplication.translate("WhatsNewContent", "Conecta tu cuenta de Hugging Face para descargar desde DowP los modelos de RMBG 2.0, o descárgalos a mano y DowP los instala. Nuevo modelo recomendado: Q4F16, el más liviano y con resultados excelentes. Además, las listas de modelos ahora van ordenadas de mejor a más antiguo."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Combinar imágenes en un PDF, mucho más rápido"),
                QCoreApplication.translate("WhatsNewContent", "Combinar fotos en un PDF pasa de casi un minuto a menos de un segundo, sin perder calidad ni congelar la app. Las páginas de PDF conservan el texto seleccionable, y al importar un TIFF o un AI de varias páginas eliges cuáles quieres."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Correcciones"),
                QCoreApplication.translate("WhatsNewContent", "Ya puedes cortar un solo fragmento sin pulsar \"+\". La miniatura \"junto al medio\" se guarda en JPG. La consola ya no salta al final mientras la lees. Añadir un medio a una colección ya no te saca de donde estabas, y la vista previa del Gestor de Medios ya no crece sin límite."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Problema conocido: subtítulos de YouTube"),
                QCoreApplication.translate("WhatsNewContent", "Sin cookies, YouTube a veces limita la descarga de subtítulos (error 429) y eso cancela toda la descarga, no solo los subtítulos. Mientras lo solucionamos: espera unos minutos antes de reintentar, usa las cookies de tu navegador (Ajustes > Cookies), o descarga el video sin subtítulos y bájalos después con el botón \"Descargar subtítulos\"."),
            ),
        ]

    if version == "1.9.2":
        # Quien la ve viene de la 1.9.1 (se actualiza sola): solo lo nuevo de esta versión.
        return [
            (
                QCoreApplication.translate("WhatsNewContent", "Sonido al terminar"),
                QCoreApplication.translate("WhatsNewContent", "Un sonido avisa cuando termina una descarga o un proceso, y otro distinto si algo falla. Puedes elegir tus propios sonidos en Ajustes > General."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Colas independientes"),
                QCoreApplication.translate("WhatsNewContent", "Cada pestaña maneja su propia cola: analizar en Proceso Avanzado ya no empieza a descargar mientras el Modo Rápido procesa otra cosa."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Crear preajustes desde Posprocesar"),
                QCoreApplication.translate("WhatsNewContent", "Nueva opción \"+ Crear preajuste...\" en los menús de Posprocesar, que te lleva directo a crearlo en Herramientas Multimedia."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Etiquetas más compactas"),
                QCoreApplication.translate("WhatsNewContent", "Los menús de etiquetas ocupan menos espacio, y Herramientas de Imagen ahora también tiene etiquetas."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Búsqueda más precisa"),
                QCoreApplication.translate("WhatsNewContent", "En la ventana de búsqueda ya no se marcan resultados por accidente al mover el ratón mientras haces clic."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Créditos y apoyo"),
                QCoreApplication.translate("WhatsNewContent", "Nueva sección en Ajustes > Acerca de con agradecimientos, créditos y licencias, y formas de apoyar DowP."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Correcciones"),
                QCoreApplication.translate("WhatsNewContent", "DowP ya no termina con un error al cerrarse (en Mac aparecía el aviso de cierre inesperado), y se corrigió un fallo del Gestor de Medios con los favoritos web."),
            ),
        ]

    if version not in ("1.9.0", "1.9.1", "2.0.0"):
        return []

    items = []
    if IS_BETA:
        items.append((
            QCoreApplication.translate("WhatsNewContent", "Estás probando una Beta"),
            QCoreApplication.translate(
                "WhatsNewContent",
                "Esta es una versión de prueba, previa al lanzamiento oficial de DowP 2.0.0 "
                "-- puede tener errores todavía sin detectar. Vas a recibir actualizaciones "
                "seguidas mientras se termina de pulir, sin que tengas que reinstalar nada.",
            ),
        ))

    items.extend([
            (
                QCoreApplication.translate("WhatsNewContent", "Interfaz renovada"),
                QCoreApplication.translate("WhatsNewContent", "Rediseño visual completo de la aplicación."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Modo Rápido"),
                QCoreApplication.translate("WhatsNewContent", "Nueva forma de descargar en segundos, sin pasar por el proceso avanzado."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Proceso Avanzado unificado"),
                QCoreApplication.translate("WhatsNewContent", "Proceso único y proceso por lotes ahora viven en una sola pestaña."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Herramientas de Imagen mejoradas"),
                QCoreApplication.translate("WhatsNewContent", "Interfaz renovada para las herramientas de imagen."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Herramientas de IA"),
                QCoreApplication.translate("WhatsNewContent", "Mapas de profundidad y mapas de normales para imágenes y videos, con varios modelos a elegir, y reescalado de video con IA."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Más conversiones de imagen"),
                QCoreApplication.translate("WhatsNewContent", "Convierte PDF a imágenes y vectoriza imágenes a SVG."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Recodificación mejorada"),
                QCoreApplication.translate("WhatsNewContent", "Proceso de recodificación con su propia pestaña dentro de Herramientas Multimedia."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Organizador de medios"),
                QCoreApplication.translate("WhatsNewContent", "Nueva ventana para organizar archivos, cortar fragmentos y buscar medios en Wikimedia, Freesound, Pexels y Pixabay."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Buscador integrado"),
                QCoreApplication.translate("WhatsNewContent", "Busca videos, canales y listas de reproducción de YouTube y SoundCloud sin salir de DowP."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Historial de descargas"),
                QCoreApplication.translate("WhatsNewContent", "Consulta todo lo que has descargado desde un solo lugar."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Envío a editores mejorado"),
                QCoreApplication.translate("WhatsNewContent", "Sistema mejorado para mandar medios a los editores compatibles (Premiere, After Effects, DaVinci...)."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Arrastre universal"),
                QCoreApplication.translate("WhatsNewContent", "Arrastra fragmentos, medios locales o descargas directamente a cualquier editor, como si arrastraras desde una carpeta."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Nuevos idiomas"),
                QCoreApplication.translate("WhatsNewContent", "La aplicación ahora está completamente traducida al inglés y al portugués (Brasil)."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Multiplataforma"),
                QCoreApplication.translate("WhatsNewContent", "Ahora compatible con macOS, y en teoría con Linux."),
            ),
    ])
    return items
