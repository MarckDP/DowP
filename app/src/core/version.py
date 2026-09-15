# src/core/version.py
"""Fuente única de la versión de DowP.

La app y el DowP Importer comparten número de versión a propósito: el panel de
Adobe se instala desde la app y viaja dentro de su bundle, así que no tiene ciclo
de publicación propio ni canal de actualización propio. Que ambos digan lo mismo
es lo que permite detectar "el panel instalado quedó viejo" con una comparación
de cadenas y nada más.

Quien consume este valor:
  - main.py                    -> QApplication.applicationVersion
  - build_cross_platform.py    -> nombre del build y estampado del importer
  - core/setup/importer_setup  -> versión que se instala y con la que se compara
  - importer/CSXS/manifest.xml -> estampado en el build (ExtensionBundleVersion)
  - importer/js/main.js        -> estampado en el build (CURRENT_EXTENSION_VERSION)

Los dos últimos son archivos generados en cuanto al número: no los edites a mano,
el build los reescribe desde aquí y falla si no puede.
"""

APP_VERSION = "1.9.1"

# Fase beta previa a la 2.0.0 oficial: se reparte a un grupo reducido mientras se
# termina el resto de la app, subiendo APP_VERSION en cada push (1.9.0, 1.9.1, ...).
# A PROPOSITO por debajo de 2.0.0: asi, cuando salga la 2.0.0 real, es un numero MAYOR
# que cualquier beta anterior y el updater SI la ofrece como actualizacion a todo el
# mundo. Si las betas usaran algo como "2.0.0.3", la 2.0.0 real quedaria por debajo
# numericamente y nunca se ofreceria como update a quien ya tiene una beta instalada.
#
# Apagar (poner en False) al compilar/publicar la 2.0.0 oficial -- eso cambia sola dos
# cosas: get_display_version() empieza a mostrar el numero real en vez de BETA_LABEL, y
# el default de "update_channel" en config_manager.py pasa de "beta" a "stable" para
# instalaciones NUEVAS (quien ya tenia "beta" guardado a mano no se mueve solo).
IS_BETA = True
BETA_LABEL = "Beta"


def get_display_version() -> str:
    """Lo que ve el usuario en reposo (version_label, "Acerca de", etc.): BETA_LABEL
    mientras IS_BETA es True, el numero real despues. Puramente cosmetico -- todo lo
    que compara o publica versiones (compute_diff, applicationVersion(), publish.py)
    sigue usando APP_VERSION tal cual, nunca esto."""
    return BETA_LABEL if IS_BETA else APP_VERSION


# Primera versión que incluye el sistema de actualizaciones. Un usuario por debajo
# de esta no puede autoactualizarse (no tiene el updater dentro) y necesita bajar el
# instalador completo. Se sube solo ante un cambio estructural que el updater no
# pueda expresar, como mover el directorio de instalación.
#
# Coincide con APP_VERSION (no con "2.0.0"): es la primera version de la serie que
# tiene el updater, punto -- si se dejara en "2.0.0" ninguna beta 1.9.x podria
# autoactualizarse a la siguiente beta (below_min bloquearia el diff en
# update_checker.compute_diff, forzando descarga completa en cada push).
MIN_UPDATABLE_VERSION = "1.9.0"

# Repo de GitHub donde tools/updater/publish.py sube los releases y de donde el
# cliente de descarga (core/updater/) los lee. Única fuente -- evita que el "--repo"
# del publicador y el que consulta la app real diverjan.
UPDATE_REPO = "MarckDP/DowP"
