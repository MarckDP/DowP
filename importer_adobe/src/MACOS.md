# DowP Importer en macOS

Notas de porteo. El panel usa exactamente el mismo código en Windows y macOS;
lo único que cambia es el mecanismo de lanzamiento, resuelto en `js/platform.js`.

## Por qué antes no funcionaba

`executeDowP()` en `js/extendscript.js` solo tenía camino real para Windows: escribía
un `.bat` en la carpeta temporal y lo lanzaba con `File.execute()`. La rama de macOS
hacía `new File(path).execute()`, que no podía funcionar por tres motivos:

1. `DowP.app` es un **directorio** (bundle), así que `new File("/Applications/DowP.app").exists`
   siempre devuelve `false` y la función salía con error antes de intentar nada.
2. `File.execute()` delega en LaunchServices y **no acepta argumentos**.
3. Aunque se apuntara al binario interno (`DowP.app/Contents/MacOS/DowP`), heredaría
   las variables `DYLD_*` y `QT_PLUGIN_PATH` de Premiere/After Effects, que hacen
   que una app PySide6 congelada con PyInstaller cargue dylibs y plugins equivocados
   y muera al arrancar.

La conclusión no es que macOS impida invocar programas desde CEP: es que **ExtendScript**
no puede. La capa CEP sí, y de forma idéntica en ambos sistemas.

## Cómo funciona ahora

`DowPPlatform.launch()` prueba tres mecanismos en cascada:

| Orden | Mecanismo | Windows | macOS |
|-------|-----------|---------|-------|
| 1 | Node `child_process.spawn` | `DowP.exe <appId>` | `/usr/bin/open -a DowP.app --args <appId>` |
| 2 | `cep.process.createProcess` | igual | `/usr/bin/env -u DYLD_… /usr/bin/open -a …` |
| 3 | ExtendScript `executeDowP()` | `.bat` de siempre | `system.callSystem` (solo AE) o `Folder.execute()` |

En los dos primeros caminos se limpian las variables de entorno tóxicas heredadas
del host Adobe (lista `TOXIC_ENV_VARS` en `js/platform.js`).

Usar `open -a` en lugar del binario interno tiene dos ventajas: el proceso arranca
vía LaunchServices con entorno limpio y, si DowP ya está abierto, lo trae al frente
en vez de abrir una segunda instancia que no podría enlazar el puerto 7788.

Node se habilita con `--enable-nodejs` en `CSXS/manifest.xml`. **No** se activa
`--mixed-context` a propósito: definiría `module`/`exports` globales y el UMD de
`js/socket.io.js` dejaría de publicar `window.io`, rompiendo toda la conexión.
Sin ese flag, CEP expone Node en `window.cep_node`.

## Instalación para desarrollo

1. **Activar PlayerDebugMode** (obligatorio mientras la extensión no esté firmada de nuevo).
   Una línea por cada versión de CSXS que tengas instalada — para CC 2020 en adelante
   suelen ser de la 9 a la 12:

   ```bash
   for v in 9 10 11 12; do
       defaults write com.adobe.CSXS.$v PlayerDebugMode 1
   done
   killall cfprefsd
   ```

2. **Copiar la extensión** a la carpeta de extensiones CEP:

   ```bash
   mkdir -p ~/Library/Application\ Support/Adobe/CEP/extensions
   cp -R "DowP Importer" ~/Library/Application\ Support/Adobe/CEP/extensions/com.dowp.importer
   ```

3. **Reiniciar** Premiere Pro o After Effects. El panel aparece en
   `Ventana > Extensiones > DowP Importer`.

## Instalación de DowP

Coloca `DowP.app` en `/Applications` o en `~/Applications` y el panel lo detecta solo
(`DowPPlatform.defaultCandidates()`). Si está en otro sitio, usa el botón ⚙️.

Si la app viene descargada de internet, macOS le pone el atributo de cuarentena y
Gatekeeper bloquea la primera apertura. Ábrela **una vez a mano** (clic derecho >
Abrir) o quita el atributo:

```bash
xattr -dr com.apple.quarantine /Applications/DowP.app
```

## Para distribuir

`META-INF/signatures.xml` corresponde al paquete anterior. Cualquier cambio en los
archivos invalida esa firma, y macOS es más estricto que Windows al respecto: sin
PlayerDebugMode, una extensión con firma inválida no carga. Hay que volver a firmar
con `ZXPSignCmd` antes de empaquetar el `.zxp`.

## Diagnóstico

Con `.debug` presente, el panel es depurable desde Chrome en
`http://localhost:8089` (Premiere) o `http://localhost:8088` (After Effects).

En la consola, al abrir el panel, se registra qué mecanismo de lanzamiento hay
disponible:

```
[DowP] SO: MacIntel | host: premiere | lanzador: node
```

Si dice `lanzador: extendscript`, Node no se activó: revisa el bloque
`<CEFCommandLine>` del manifest y que PlayerDebugMode esté puesto.
