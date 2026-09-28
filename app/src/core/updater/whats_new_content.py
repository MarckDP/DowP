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
                QCoreApplication.translate("WhatsNewContent", "Los menús de etiquetas ocupan menos espacio, y el Editor de Imagen ahora también tiene etiquetas."),
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
                QCoreApplication.translate("WhatsNewContent", "Editor de Imagen mejorado"),
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
