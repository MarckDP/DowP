(function () {
    if (typeof JSON === "undefined" || typeof JSON.stringify === "undefined" || typeof JSON.parse === "undefined") {

        var LocalJSON = {};

        if (typeof JSON === "undefined") {
            JSON = {};
        }

        if (typeof JSON.stringify !== "function") {
            JSON.stringify = function (obj) {
                try {
                    if (obj === null) return "null";
                    if (obj === undefined) return "null";
                    if (typeof obj === "string") return '"' + obj.replace(/"/g, '\\"').replace(/\\/g, '\\\\') + '"';
                    if (typeof obj === "number") {
                        if (isNaN(obj) || !isFinite(obj)) return "null";
                        return obj.toString();
                    }
                    if (typeof obj === "boolean") return obj.toString();
                    if (obj instanceof Array) {
                        var arr = [];
                        for (var i = 0; i < obj.length; i++) {
                            arr.push(JSON.stringify(obj[i]));
                        }
                        return "[" + arr.join(",") + "]";
                    }
                    if (typeof obj === "object") {
                        var props = [];
                        for (var key in obj) {
                            if (obj.hasOwnProperty(key) && obj[key] !== undefined) {
                                props.push('"' + key.replace(/"/g, '\\"') + '":' + JSON.stringify(obj[key]));
                            }
                        }
                        return "{" + props.join(",") + "}";
                    }
                    return "null";
                } catch (e) {
                    return "null";
                }
            };
        }

        if (typeof JSON.parse !== "function") {
            JSON.parse = function (str) {
                try {
                    if (typeof str !== "string") return null;
                    if (str === "" || str === "undefined") return null;

                    str = str.replace(/^\s+|\s+$/g, '');
                    if (str === "") return null;

                    if (!/^[\[\{"]/.test(str) && !/^-?\d/.test(str) && !/^(true|false|null)$/.test(str)) {
                        console.error("JSON no válido, rechazando para seguridad");
                        return null;
                    }

                    try {
                        return new Function("return (" + str + ")")();
                    } catch (e) {
                        console.error("Error al parsear JSON:", e);
                        return null;
                    }
                } catch (e) {
                    return null;
                }
            };
        }
    }
})();

function getHostAppName() {
    // BridgeTalk.appName es el unico identificador que los tres hosts publican igual
    // ('photoshop', 'aftereffects', 'premierepro'), asi que va primero. Antes, Premiere
    // se deducia de que app.isDocumentOpen() devolviera true, lo que fallaba con el
    // proyecto recien abierto y no distinguia Photoshop de nada.
    try {
        if (typeof BridgeTalk !== 'undefined' && BridgeTalk.appName) {
            var bt = String(BridgeTalk.appName).toLowerCase();
            if (bt.indexOf("photoshop") === 0) return "Adobe Photoshop";
            if (bt.indexOf("aftereffects") === 0) return "Adobe After Effects";
            if (bt.indexOf("premiere") === 0) return "Adobe Premiere Pro";
        }
    } catch (eBT) {}

    try {
        if (typeof app !== 'undefined' && app.appName && app.appName.indexOf("After Effects") > -1) {
            return "Adobe After Effects";
        }
        if (typeof app !== 'undefined' && app.name && String(app.name).indexOf("Photoshop") > -1) {
            return "Adobe Photoshop";
        }
        if (typeof $ !== 'undefined' && $.global && $.global.app && $.global.app.isDocumentOpen && $.global.app.isDocumentOpen()) {
            return "Adobe Premiere Pro";
        }
        return "unknown";
    } catch (e) {
        return "unknown";
    }
}

// Extensiones que Photoshop puede abrir o colocar como capa. Todo lo demas que llegue
// (video, audio, subtitulos) se ignora ahi, porque DowP manda a Photoshop solo imagenes.
var PHOTOSHOP_IMAGE_EXTS = [
    ".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff", ".psd", ".psb",
    ".bmp", ".webp", ".heic", ".heif", ".raw", ".dng", ".cr2", ".nef",
    ".arw", ".exr", ".tga", ".ico", ".svg", ".pdf", ".eps"
];

function isPhotoshopImage(path) {
    try {
        var lower = String(path).toLowerCase();
        for (var i = 0; i < PHOTOSHOP_IMAGE_EXTS.length; i++) {
            var ext = PHOTOSHOP_IMAGE_EXTS[i];
            if (lower.length >= ext.length && lower.substring(lower.length - ext.length) === ext) {
                return true;
            }
        }
    } catch (e) {}
    return false;
}

function getPhotoshopActiveDocument() {
    // app.activeDocument LANZA excepcion cuando no hay ningun documento abierto, en vez
    // de devolver null: hay que mirar primero app.documents.length.
    try {
        if (!app.documents || app.documents.length === 0) return null;
        return app.activeDocument;
    } catch (e) {
        return null;
    }
}

function isMacOS() {
    try {
        return $.os.indexOf("Windows") === -1;
    } catch (e) {
        return false;
    }
}

function selectDowPExecutable() {
    try {
        if (isMacOS()) {
            // En macOS DowP es un bundle (DowP.app), que a nivel de sistema de
            // archivos es un directorio. File.openDialog puede devolverlo, pero
            // segun la version de ExtendScript el usuario acaba entrando dentro
            // del paquete; por eso se ofrece primero el selector de carpetas y
            // se repliega al binario interno si eso es lo que eligio.
            var folder = Folder.selectDlg("Selecciona DowP.app");
            if (folder) {
                var fpath = folder.fsName;
                var idx = fpath.indexOf(".app/Contents/MacOS");
                if (idx !== -1) { fpath = fpath.substring(0, idx + 4); }
                return fpath;
            }
            return "cancel";
        }

        var file = File.openDialog("Selecciona el ejecutable de DowP (DowP.exe)");
        if (file) { return file.fsName; }
        return "cancel";
    } catch (e) {
        // No disfrazar el fallo de "cancel": el panel lo mostraria como si el
        // usuario hubiera cerrado el dialogo y el error quedaria oculto.
        return "error: " + e.toString();
    }
}

function executeDowP(path, appIdentifier) {
    // NOTA: esta funcion es el ULTIMO recurso. El lanzamiento normal ocurre en
    // la capa CEP (js/platform.js), que usa Node child_process o
    // cep.process.createProcess y funciona igual en Windows y macOS.
    // ExtendScript solo puede lanzar procesos de forma muy limitada, y en macOS
    // no tiene ninguna via que acepte argumentos.
    $.writeln("DEBUG: executeDowP llamado (fallback)");
    $.writeln("  - Ruta: " + path);
    $.writeln("  - App: " + appIdentifier);

    try {
        if (!isMacOS()) {
            var exeFile = new File(path);
            if (!exeFile.exists) {
                $.writeln("ERROR: No existe: " + path);
                return "Error: no se encontro DowP en la ruta especificada: " + path;
            }

            var scriptFile = new File(Folder.temp.fsName + "/launch_dowp_temp.bat");
            var scriptContent = '@echo off\n' +
                'start "" "' + path + '" "' + appIdentifier + '"\n';

            scriptFile.open("w");
            scriptFile.encoding = "UTF-8";
            scriptFile.write(scriptContent);
            scriptFile.close();

            $.writeln("DEBUG: Ejecutando script batch: " + scriptFile.fsName);
            scriptFile.execute();
            return "success";
        }

        // ── macOS ──
        var isBundle = /\.app$/i.test(path);
        var bundle = isBundle ? new Folder(path) : null;
        var binary = isBundle ? null : new File(path);

        if (isBundle && !bundle.exists) {
            $.writeln("ERROR: No existe el bundle: " + path);
            return "Error: no se encontro DowP.app en: " + path;
        }
        if (!isBundle && !binary.exists) {
            $.writeln("ERROR: No existe: " + path);
            return "Error: no se encontro DowP en: " + path;
        }

        // 2a. After Effects expone system.callSystem(), que si ejecuta shell.
        //     Premiere Pro no lo tiene, de ahi el fallback siguiente.
        try {
            if (typeof system !== "undefined" && system && typeof system.callSystem === "function") {
                var quoted = path.replace(/'/g, "'\\''");
                var cmd = isBundle
                    ? "/usr/bin/open -a '" + quoted + "' --args " + appIdentifier
                    : "'" + quoted + "' " + appIdentifier + " &";
                $.writeln("DEBUG: system.callSystem -> " + cmd);
                system.callSystem(cmd);
                return "success";
            }
        } catch (eSys) {
            $.writeln("DEBUG: system.callSystem fallo: " + eSys.toString());
        }

        // 2b. Folder.execute() sobre un bundle: LaunchServices lo reconoce como
        //     aplicacion y la abre. No admite argumentos, pero DowP no los
        //     necesita para arrancar (el panel se registra despues por socket).
        if (isBundle) {
            $.writeln("DEBUG: Folder.execute() sobre el bundle");
            if (bundle.execute()) { return "success"; }
            return "Error: macOS bloqueo la apertura de DowP.app. Abrelo manualmente una vez para autorizarlo.";
        }

        $.writeln("DEBUG: File.execute() sobre el binario");
        if (binary.execute()) { return "success"; }
        return "Error: no se pudo ejecutar DowP en macOS.";

    } catch (e) {
        $.writeln("ERROR en executeDowP: " + e.toString());
        return "Error al intentar ejecutar DowP: " + e.toString();
    }
}

function bindSequenceEvents() {
    // Premiere puede avisar por evento cuando cambia la secuencia activa. Con esto el
    // panel se entera al instante y no depende solo del sondeo cada 1-2 s (que ademas no
    // puede correr mientras se importa). Es aditivo: si esta version del host no soporta
    // app.bind o el evento, se devuelve el error y el panel sigue sondeando igual.
    try {
        if (getHostAppName() !== "Adobe Premiere Pro") return "skipped";
        if ($.global.__dowpSequenceBound) return "already";

        app.bind("onActiveSequenceChanged", function () {
            try {
                new ExternalObject("lib:PlugPlugExternalObject");
                var ev = new CSXSEvent();
                ev.type = "com.dowp.sequenceChanged";
                ev.data = "";
                ev.dispatch();
            } catch (eDispatch) {}
        });

        $.global.__dowpSequenceBound = true;
        return "bound";
    } catch (e) {
        return "error: " + e.toString();
    }
}

function rememberActiveComp(comp) {
    try {
        if (comp && comp instanceof CompItem) {
            $.global.__dowpLastCompId = comp.id;
        }
    } catch (e) {}
}

function getActiveCompSticky() {
    // app.project.activeItem solo devuelve la composicion cuando su visor es el frontal:
    // si el usuario toca el panel de proyecto, otro visor, o el propio panel de DowP,
    // pasa a null o a un item que no es una CompItem, y el panel creia que ya no habia
    // linea de tiempo (casilla apagada a mitad de una importacion). Se recuerda la
    // ultima composicion valida y se usa como respaldo mientras siga existiendo en el
    // proyecto.
    var item = null;
    try {
        item = (app.project) ? app.project.activeItem : null;
    } catch (e) {
        item = null;
    }

    if (item && item instanceof CompItem) {
        rememberActiveComp(item);
        return item;
    }

    var lastId = null;
    try {
        lastId = $.global.__dowpLastCompId;
    } catch (e) {
        lastId = null;
    }
    if (!lastId) return null;

    var remembered = null;
    try {
        remembered = app.project.itemByID(lastId);
    } catch (e) {
        remembered = null;
    }
    if (!remembered) {
        // itemByID no esta disponible en todas las versiones: barrido manual.
        try {
            for (var i = 1; i <= app.project.numItems; i++) {
                var candidate = app.project.item(i);
                if (candidate && candidate.id === lastId) {
                    remembered = candidate;
                    break;
                }
            }
        } catch (e2) {
            remembered = null;
        }
    }

    return (remembered && remembered instanceof CompItem) ? remembered : null;
}

function getActiveTimelineInfo() {
    var info = {
        hasActiveTimeline: false,
        playheadTime: 0,
        playheadTicks: "0",
        timelineName: ""
    };

    try {
        var host = getHostAppName();
        if (host === "Adobe Premiere Pro") {
            if (app.project && app.project.activeSequence) {
                var sequence = app.project.activeSequence;
                info.hasActiveTimeline = true;
                info.playheadTime = sequence.getPlayerPosition().seconds;
                info.playheadTicks = sequence.getPlayerPosition().ticks;
                try { info.timelineName = sequence.name; } catch (eName) {}
            }
        } else if (host === "Adobe Photoshop") {
            // En Photoshop no hay linea de tiempo: el equivalente util es "hay un
            // documento abierto donde colocar la imagen". Asi, la misma casilla del panel
            // pasa a significar "colocar en el documento activo" sin tocar su maquinaria
            // (ver updateTimelineState en main.js).
            var psDoc = getPhotoshopActiveDocument();
            if (psDoc) {
                info.hasActiveTimeline = true;
                info.playheadTime = 0;
                try { info.timelineName = psDoc.name; } catch (ePS) {}
            }
        } else if (host === "Adobe After Effects") {
            var comp = getActiveCompSticky();
            if (comp) {
                try {
                    var currentTime = comp.time;
                    if (comp.width > 0 && comp.height > 0) {
                        info.hasActiveTimeline = true;
                        info.playheadTime = currentTime;
                        try { info.timelineName = comp.name; } catch (eName2) {}
                    }
                } catch (e) {
                    info.hasActiveTimeline = false;
                }
            }
        }
    } catch (e) {
    }

    try {
        return JSON.stringify(info);
    } catch (e) {
        return '{"hasActiveTimeline":false,"playheadTime":0}';
    }
}

function clearCacheForExistingItems(filePath, targetBin) {
    try {
        if (!filePath || !app.project) return;

        for (var i = 1; i <= app.project.numItems; i++) {
            var item = app.project.item(i);
            if (item && item.file && item.file.fsName === filePath) {
                item.replace(item.file);
            }
        }
    } catch (e) {
    }
}

function isFileRecentlyModified(filePath, thresholdMinutes) {
    try {
        var file = new File(filePath);
        if (!file.exists) return false;

        var now = new Date();
        var fileModified = new Date(file.modified);
        var diffMinutes = (now.getTime() - fileModified.getTime()) / (1000 * 60);

        return diffMinutes < (thresholdMinutes || 5);
    } catch (e) {
        return false;
    }
}

function importFiles(fileListJSON, addToTimeline, playheadTime, importImagesToTimeline, targetBinName) {
    try {
        var filePaths = null;

        if (!fileListJSON || fileListJSON === "undefined" || fileListJSON === "") {
            return "Error: La lista de archivos está vacía o es inválida.";
        }

        try {
            filePaths = JSON.parse(fileListJSON);
        } catch (e) {
            return "Error: JSON inválido - " + e.toString();
        }

        if (!filePaths || !filePaths.length || filePaths.length === 0) {
            return "Error: La lista de archivos está vacía.";
        }

        var host = getHostAppName();
        if (host === "Adobe After Effects") {
            return importForAfterEffects(filePaths, addToTimeline, playheadTime, importImagesToTimeline, targetBinName);
        } else if (host === "Adobe Premiere Pro") {
            return importForPremiere(filePaths, addToTimeline, playheadTime, importImagesToTimeline, targetBinName);
        } else if (host === "Adobe Photoshop") {
            return importForPhotoshop(filePaths, addToTimeline);
        } else {
            return "Error: Aplicación no soportada.";
        }
    } catch (error) {
        return "Error crítico en ExtendScript: " + error.toString();
    }
}

function placeInPhotoshopDocument(file) {
    // "Colocar incrustado": entra como objeto inteligente en el documento activo, que es
    // el equivalente a "anadir a la linea de tiempo" del resto de hosts. Se usa la accion
    // en vez de app.open para no abrir un documento nuevo por cada imagen.
    var desc = new ActionDescriptor();
    desc.putPath(charIDToTypeID("null"), file);
    desc.putEnumerated(charIDToTypeID("FTcs"), charIDToTypeID("QCSt"), charIDToTypeID("Qcsa"));
    desc.putBoolean(stringIDToTypeID("linked"), false);
    executeAction(charIDToTypeID("Plc "), desc, DialogModes.NO);
}

function importForPhotoshop(filePaths, placeInActiveDocument) {
    var imported = 0;
    var ignored = [];
    var errors = [];

    var doc = getPhotoshopActiveDocument();
    // Sin documento abierto no hay donde colocar nada: se abre cada imagen como
    // documento propio, que es el unico destino posible.
    var shouldPlace = placeInActiveDocument && doc !== null;

    for (var i = 0; i < filePaths.length; i++) {
        var path = filePaths[i];
        if (!isPhotoshopImage(path)) {
            ignored.push(path);
            continue;
        }

        var file = new File(path);
        if (!file.exists) {
            errors.push("no existe: " + path);
            continue;
        }

        try {
            if (shouldPlace) {
                placeInPhotoshopDocument(file);
            } else {
                app.open(file);
            }
            imported++;
        } catch (e) {
            errors.push(path + " (" + e.toString() + ")");
        }
    }

    if (imported === 0) {
        if (errors.length > 0) return "Error: " + errors.join(" | ");
        if (ignored.length > 0) return "Error: Photoshop solo acepta imágenes.";
        return "Error: No se importó ningún archivo.";
    }

    logToDowP("Photoshop: " + imported + " imagen(es) " +
              (shouldPlace ? "colocadas en el documento activo" : "abiertas como documento nuevo") +
              (ignored.length ? " | ignoradas (no son imágenes): " + ignored.length : ""), "info");
    return "success";
}

function logToDowP(msg, level) {
    try {
        var xmpLib = new ExternalObject("lib:PlugPlugExternalObject");
        if (xmpLib) {
            var eventObj = new CSXSEvent();
            eventObj.type = "com.dowp.log";
            eventObj.data = JSON.stringify({ message: msg, level: level });
            eventObj.dispatch();
        }
    } catch(e) {}
}

function importSubclips(filePath, subclipsJSON, addToTimeline, playheadTime, playheadTicks) {
    var host = getHostAppName();
    if (host === "Adobe After Effects") {
        return importSubclipsForAfterEffects(filePath, subclipsJSON, addToTimeline, playheadTime);
    } else if (host === "Adobe Premiere Pro") {
        return importSubclipsForPremiere(filePath, subclipsJSON, addToTimeline, playheadTime);
    } else {
        return "Error: Aplicación no soportada.";
    }
}

// --- Recorte de subclips en la línea de tiempo de After Effects ---
// AE no tiene equivalente a ProjectItem.createSubclip() (eso es exclusivo del DOM de Premiere).
// En cambio, se importa el footage completo UNA sola vez y, por cada subclip pedido,
// se crea una capa nueva a partir del mismo FootageItem, recortada con inPoint/outPoint.
function importSubclipsForAfterEffects(filePath, subclipsJSON, addToTimeline, playheadTime) {
    try {
        if (!app.project) return "Error: No hay un proyecto abierto en After Effects.";

        var subclips = JSON.parse(subclipsJSON);
        if (!subclips || !subclips.length) return "Error: Lista de subclips vacía.";

        // El recorte de subclips solo tiene sentido a nivel de capa en una
        // composición. Si no se pide timeline (o no hay comp activa), no se
        // descarta el medio: se importa completo al bin DowP Imports, igual
        // que un archivo normal, y ahí se queda para uso manual.
        var comp = getActiveCompSticky();
        var canTrimOnTimeline = addToTimeline && comp;

        app.beginUndoGroup("Importar subclips desde DowP");

        var project = app.project;
        var mainBinName = "DowP Imports";
        var mainBin = null;

        for (var i = 1; i <= project.numItems; i++) {
            var item = project.item(i);
            if (item.name === mainBinName && item instanceof FolderItem) {
                mainBin = item;
                break;
            }
        }
        if (mainBin === null) {
            mainBin = project.items.addFolder(mainBinName);
        }

        // Importar el footage base una sola vez (todas las capas de subclip
        // se generan a partir de este mismo FootageItem)
        var importedItem = null;
        try {
            var importOptions = new ImportOptions(new File(filePath));
            if (importOptions.canImportAs && importOptions.canImportAs(ImportAsType.FOOTAGE)) {
                importOptions.importAs = ImportAsType.FOOTAGE;
            }
            importOptions.sequence = false;
            importedItem = project.importFile(importOptions);
        } catch (eImp) {
            app.endUndoGroup();
            return "Error importando el archivo base: " + eImp.toString();
        }

        if (!importedItem) {
            app.endUndoGroup();
            return "Error: No se pudo importar el archivo base.";
        }

        var lowerPath = filePath.toLowerCase();
        var folderName = "Video";
        if (/\.(jpg|jpeg|png|gif|bmp|tiff|tif|svg|webp)$/i.test(lowerPath)) {
            folderName = "Imágenes";
        } else if (/\.(mp3|m4a|wav|flac|aac|ogg|opus|weba)$/i.test(lowerPath) || (importedItem.hasAudio && !importedItem.hasVideo)) {
            folderName = "Audio";
        }
        var subFolder = getOrCreateSubFolder(mainBin, folderName);
        importedItem.parentFolder = subFolder;

        if (importedItem.file && importedItem.file.exists) {
            try { importedItem.replace(importedItem.file); } catch (e_rep) { }
        }

        // Sin timeline activa (o sin comp activa): el medio ya quedó
        // importado completo en DowP Imports. No se recorta nada, pero
        // tampoco se descarta.
        if (!canTrimOnTimeline) {
            app.endUndoGroup();
            return "success";
        }

        var cursorTime = playheadTime || 0;
        var createdCount = 0;

        for (var s = 0; s < subclips.length; s++) {
            var sc = subclips[s];
            var inPt = sc["in"] || 0;
            var outPt = sc["out"] || 0;
            var duration = outPt - inPt;

            if (duration <= 0) continue;

            try {
                var newLayer = comp.layers.add(importedItem);

                // startTime es solo el punto de referencia teórico (frame 0 del
                // source); el recorte visible real lo definen inPoint/outPoint.
                newLayer.startTime = cursorTime - inPt;
                newLayer.inPoint = cursorTime;
                newLayer.outPoint = cursorTime + duration;

                if (sc.name) {
                    try { newLayer.name = sc.name; } catch (eName) { }
                }

                createdCount++;
                cursorTime += duration; // siguiente subclip, sin encimarse
            } catch (errLayer) {
                $.writeln("[AE Subclips] Error creando capa para subclip " + s + ": " + errLayer.toString());
            }
        }

        try { comp.openInViewer(); } catch (eView) { }

        app.endUndoGroup();

        if (createdCount === 0) {
            // El footage ya se importó igual; no lo tratamos como fallo total.
            return "success";
        }
        return "success";
    } catch (err) {
        try { app.endUndoGroup(); } catch (e) { }
        return "Error creando subclips en After Effects: " + err.toString();
    }
}

function importSubclipsForPremiere(filePath, subclipsJSON, addToTimeline, playheadTime, playheadTicks) {
    try {
        if (!app.project) return "Error: No hay un proyecto abierto en Premiere Pro.";
        
        logToDowP("Iniciando importSubclipsForPremiere", "info");

        var subclips = JSON.parse(subclipsJSON);
        if (!subclips || !subclips.length) return "Error: Lista de subclips vacía.";

        var project = app.project;
        var mainBinName = "DowP Imports";
        var mainBin = null;

        for (var i = 0; i < project.rootItem.children.numItems; i++) {
            var item = project.rootItem.children[i];
            if (item.name === mainBinName && item.type === ProjectItemType.BIN) {
                mainBin = item;
                break;
            }
        }
        if (!mainBin) {
            mainBin = project.rootItem.createBin(mainBinName);
        }

        var uidsBefore = getItemUIDs(mainBin);
        project.importFiles([filePath], true, mainBin, false);

        var importedMainItem = null;
        for (var j = 0; j < mainBin.children.numItems; j++) {
            var it = mainBin.children[j];
            if (!uidsBefore.hasOwnProperty(it.nodeId)) {
                importedMainItem = it;
                break;
            }
        }
        if (!importedMainItem) {
            var fname = filePath.substring(Math.max(filePath.lastIndexOf('/'), filePath.lastIndexOf('\\')) + 1);
            for (var k = 0; k < mainBin.children.numItems; k++) {
                if (mainBin.children[k].name === fname) {
                    importedMainItem = mainBin.children[k];
                    break;
                }
            }
        }

        if (!importedMainItem) return "Error: No se pudo importar el archivo base.";

        var createdCount = 0;
        var accumulatedTicks = 0;
        var TICKS_PER_SECOND = 254016000000;
        
        var basePlayheadTicks = playheadTicks ? parseInt(playheadTicks, 10) : Math.round(playheadTime * TICKS_PER_SECOND);
        logToDowP("Base Playhead Ticks: " + basePlayheadTicks, "info");

        // Determinar la pista destino UNA SOLA VEZ para todos los subclips
        var targetVideoTrackIndex = -1;
        var targetAudioTrackIndex = -1;
        var firstClipForDetection = importedMainItem;
        
        for (var s = 0; s < subclips.length; s++) {
            var sc = subclips[s];
            var scName = sc.name || ("Subclip_" + (s + 1));
            var inPt = sc.in || 0;
            var outPt = sc.out || 0;

            // Calcular la duración real de ESTE subclip en ticks
            var subclipDurationTicks = Math.round((outPt - inPt) * TICKS_PER_SECOND);

            try {
                var subclipItem = importedMainItem.createSubclip(scName, inPt, outPt, 1, 1, 1);
                if (subclipItem) {
                    createdCount++;
                    if (addToTimeline && project.activeSequence) {
                        var pTime = new Time();
                        var currentInsertTicks = basePlayheadTicks + accumulatedTicks;
                        pTime.ticks = String(currentInsertTicks);
                        logToDowP("Subclip " + s + " inserting at ticks: " + currentInsertTicks, "info");

                        // Para el primer subclip, encontrar la pista. Para los siguientes, reutilizar.
                        if (s === 0) {
                            var avDetection = detectAVviaXMP(subclipItem);
                            if (avDetection.video && avDetection.audio) {
                                // Buscar par AV, pero usando duración real del subclip
                                targetVideoTrackIndex = findAvailableAVPairWithDuration(project.activeSequence, pTime, outPt - inPt);
                                if (targetVideoTrackIndex >= 0) {
                                    logToDowP("Subclips: Pista AV seleccionada = V" + (targetVideoTrackIndex + 1), "info");
                                    project.activeSequence.videoTracks[targetVideoTrackIndex].overwriteClip(subclipItem, pTime);
                                } else {
                                    // Crear pista nueva
                                    handleMixedClipInsert(project.activeSequence, pTime, subclipItem);
                                    // Averiguar en qué pista quedó
                                    targetVideoTrackIndex = findTrackContainingClipAt(project.activeSequence, pTime);
                                    logToDowP("Subclips: Pista AV nueva = V" + (targetVideoTrackIndex + 1), "info");
                                }
                            } else if (avDetection.video) {
                                var vTrack = findAvailableVideoTrack(project.activeSequence, pTime, subclipItem);
                                if (vTrack) {
                                    vTrack.overwriteClip(subclipItem, pTime);
                                    for (var ti = 0; ti < project.activeSequence.videoTracks.numTracks; ti++) {
                                        if (project.activeSequence.videoTracks[ti] === vTrack) { targetVideoTrackIndex = ti; break; }
                                    }
                                }
                            } else if (avDetection.audio) {
                                var aTrack = findAvailableAudioTrack(project.activeSequence, pTime, subclipItem);
                                if (aTrack) {
                                    aTrack.overwriteClip(subclipItem, pTime);
                                    for (var ti = 0; ti < project.activeSequence.audioTracks.numTracks; ti++) {
                                        if (project.activeSequence.audioTracks[ti] === aTrack) { targetAudioTrackIndex = ti; break; }
                                    }
                                }
                            }
                        } else {
                            // Subclips posteriores: usar la misma pista
                            if (targetVideoTrackIndex >= 0 && project.activeSequence.videoTracks[targetVideoTrackIndex]) {
                                logToDowP("Subclip " + s + " -> misma pista V" + (targetVideoTrackIndex + 1), "info");
                                project.activeSequence.videoTracks[targetVideoTrackIndex].overwriteClip(subclipItem, pTime);
                            } else if (targetAudioTrackIndex >= 0 && project.activeSequence.audioTracks[targetAudioTrackIndex]) {
                                logToDowP("Subclip " + s + " -> misma pista A" + (targetAudioTrackIndex + 1), "info");
                                project.activeSequence.audioTracks[targetAudioTrackIndex].overwriteClip(subclipItem, pTime);
                            } else {
                                // Fallback: buscar pista como antes
                                handleMixedClipInsert(project.activeSequence, pTime, subclipItem);
                            }
                        }
                    }
                }
            } catch (errSub) {
                try {
                    importedMainItem.setInPoint(inPt, 4);
                    importedMainItem.setOutPoint(outPt, 4);
                    if (addToTimeline && project.activeSequence) {
                        var pTime = new Time();
                        var currentInsertTicks = basePlayheadTicks + accumulatedTicks;
                        pTime.ticks = String(currentInsertTicks);
                        logToDowP("Subclip " + s + " (fallback) inserting at ticks: " + currentInsertTicks, "info");

                        if (s === 0) {
                            var avDetection = detectAVviaXMP(importedMainItem);
                            if (avDetection.video && avDetection.audio) {
                                targetVideoTrackIndex = findAvailableAVPairWithDuration(project.activeSequence, pTime, outPt - inPt);
                                if (targetVideoTrackIndex >= 0) {
                                    logToDowP("Subclips (fallback): Pista AV seleccionada = V" + (targetVideoTrackIndex + 1), "info");
                                    project.activeSequence.videoTracks[targetVideoTrackIndex].overwriteClip(importedMainItem, pTime);
                                } else {
                                    handleMixedClipInsert(project.activeSequence, pTime, importedMainItem);
                                    targetVideoTrackIndex = findTrackContainingClipAt(project.activeSequence, pTime);
                                    logToDowP("Subclips (fallback): Pista AV nueva = V" + (targetVideoTrackIndex + 1), "info");
                                }
                            } else if (avDetection.video) {
                                var vTrack = findAvailableVideoTrack(project.activeSequence, pTime, importedMainItem);
                                if (vTrack) {
                                    vTrack.overwriteClip(importedMainItem, pTime);
                                    for (var ti = 0; ti < project.activeSequence.videoTracks.numTracks; ti++) {
                                        if (project.activeSequence.videoTracks[ti] === vTrack) { targetVideoTrackIndex = ti; break; }
                                    }
                                }
                            } else if (avDetection.audio) {
                                var aTrack = findAvailableAudioTrack(project.activeSequence, pTime, importedMainItem);
                                if (aTrack) {
                                    aTrack.overwriteClip(importedMainItem, pTime);
                                    for (var ti = 0; ti < project.activeSequence.audioTracks.numTracks; ti++) {
                                        if (project.activeSequence.audioTracks[ti] === aTrack) { targetAudioTrackIndex = ti; break; }
                                    }
                                }
                            }
                        } else {
                            if (targetVideoTrackIndex >= 0 && project.activeSequence.videoTracks[targetVideoTrackIndex]) {
                                logToDowP("Subclip " + s + " (fallback) -> misma pista V" + (targetVideoTrackIndex + 1), "info");
                                project.activeSequence.videoTracks[targetVideoTrackIndex].overwriteClip(importedMainItem, pTime);
                            } else if (targetAudioTrackIndex >= 0 && project.activeSequence.audioTracks[targetAudioTrackIndex]) {
                                logToDowP("Subclip " + s + " (fallback) -> misma pista A" + (targetAudioTrackIndex + 1), "info");
                                project.activeSequence.audioTracks[targetAudioTrackIndex].overwriteClip(importedMainItem, pTime);
                            } else {
                                handleMixedClipInsert(project.activeSequence, pTime, importedMainItem);
                            }
                        }
                    }
                    createdCount++;
                } catch (e2) { }
            }
            
            var addedTicks = Math.round((outPt - inPt) * TICKS_PER_SECOND);
            if (subclipItem) {
                try {
                    var iT = subclipItem.getInPoint();
                    var oT = subclipItem.getOutPoint();
                    if (iT && oT) addedTicks = parseInt(oT.ticks, 10) - parseInt(iT.ticks, 10);
                } catch(e) {}
            } else if (importedMainItem) {
                try {
                    var iT2 = importedMainItem.getInPoint();
                    var oT2 = importedMainItem.getOutPoint();
                    if (iT2 && oT2) addedTicks = parseInt(oT2.ticks, 10) - parseInt(iT2.ticks, 10);
                } catch(e) {}
            }
            logToDowP("Subclip " + s + " addedTicks: " + addedTicks, "info");
            accumulatedTicks += addedTicks;
        }

        // ── Limpieza post-inserción: eliminar fotogramas fantasma ──
        if (addToTimeline && project.activeSequence && targetVideoTrackIndex >= 0) {
            try {
                var expectedEndTicks = basePlayheadTicks + accumulatedTicks;
                var expectedEndSeconds = expectedEndTicks / TICKS_PER_SECOND;
                var cleanupTrack = project.activeSequence.videoTracks[targetVideoTrackIndex];
                var FRAME_THRESHOLD = 0.12; // ~3 fotogramas a 29.97fps

                logToDowP("Limpieza: Buscando fantasmas después de " + expectedEndSeconds + "s en V" + (targetVideoTrackIndex + 1), "info");

                // Recorrer clips del track de atrás hacia adelante para poder eliminar sin romper índices
                for (var c = cleanupTrack.clips.numItems - 1; c >= 0; c--) {
                    var tlClip = cleanupTrack.clips[c];
                    var clipStart = tlClip.start.seconds;
                    var clipDur = tlClip.end.seconds - clipStart;

                    // Solo buscar clips que empiecen en o después de la zona esperada de fin
                    if (clipStart >= expectedEndSeconds - FRAME_THRESHOLD && clipDur < FRAME_THRESHOLD) {
                        logToDowP("Limpieza: Eliminando fantasma '" + tlClip.name + "' (dur: " + clipDur.toFixed(4) + "s) en " + clipStart.toFixed(4) + "s", "info");
                        tlClip.remove(true, true);
                    }
                }

                // También limpiar la pista de audio correspondiente
                if (targetVideoTrackIndex < project.activeSequence.audioTracks.numTracks) {
                    var cleanupAudioTrack = project.activeSequence.audioTracks[targetVideoTrackIndex];
                    for (var c = cleanupAudioTrack.clips.numItems - 1; c >= 0; c--) {
                        var tlClip = cleanupAudioTrack.clips[c];
                        var clipStart = tlClip.start.seconds;
                        var clipDur = tlClip.end.seconds - clipStart;

                        if (clipStart >= expectedEndSeconds - FRAME_THRESHOLD && clipDur < FRAME_THRESHOLD) {
                            logToDowP("Limpieza Audio: Eliminando fantasma '" + tlClip.name + "' (dur: " + clipDur.toFixed(4) + "s)", "info");
                            tlClip.remove(true, true);
                        }
                    }
                }
            } catch (cleanupErr) {
                logToDowP("Limpieza: Error - " + cleanupErr.toString(), "error");
            }
        }

        return "success";
    } catch (err) {
        return "Error creando subclips en Premiere: " + err.toString();
    }
}

function getTrackIndex(trackCollection, track) {
    try {
        for (var i = 0; i < trackCollection.numTracks; i++) {
            if (trackCollection[i] === track) {
                return i;
            }
        }
    } catch (e) {
    }
    return -1;
}

function importForPremiere(filePaths, addToTimeline, playheadTime, importImagesToTimeline, targetBinName) {
    try {
        if (!app.project) return "Error: No hay un proyecto abierto en Premiere Pro.";

        var project = app.project;
        var mainBinName = "DowP Imports";
        var mainBin = null;

        for (var i = 0; i < project.rootItem.children.numItems; i++) {
            var item = project.rootItem.children[i];
            if (item.name === mainBinName && item.type === ProjectItemType.BIN) {
                mainBin = item;
                break;
            }
        }

        if (mainBin === null) {
            mainBin = project.rootItem.createBin(mainBinName);
        }

        var targetBin = mainBin;

        // Ignoramos targetBinName para evitar carpetas redundantes

        var importSucceeded = false;
        var maxRetries = 3;
        var retryDelay = 750; // 0.75 segundos de espera entre reintentos

        // Guardar los UIDs *antes* de cualquier intento
        var uidsBeforeImport = getItemUIDs(targetBin);

        for (var attempt = 1; attempt <= maxRetries; attempt++) {
            try {
                // Pausa preventiva. Aumenta en cada intento.
                // Intento 1: 500ms (para sumar al cooldown de Python)
                // Intento 2: 750ms
                // Intento 3: 1500ms
                var currentDelay = (attempt === 1) ? 500 : (retryDelay * (attempt - 1));
                $.sleep(currentDelay);

                $.writeln("[Premiere] Intento de importación en lote " + attempt + "/" + maxRetries + " (Pausa: " + currentDelay + "ms)");

                // El comando de importación en lote (el que queremos conservar)
                project.importFiles(filePaths, true, targetBin, false);

                // Si no lanzó una excepción, ¡éxito!
                importSucceeded = true;
                $.writeln("[Premiere] ¡Importación en lote exitosa en el intento " + attempt + "!");
                break; // Salir del bucle de reintento

            } catch (e) {
                $.writeln("[Premiere ERROR] Intento " + attempt + " falló: " + e.toString());
                if (attempt === maxRetries) {
                    // Si fallan todos los reintentos, lanzamos el error
                    throw new Error("Fallaron todos los reintentos de importación. Error: " + e.toString());
                }
                // Si no es el último intento, el bucle continuará y reintentará.
            }
        }

        if (!importSucceeded) {
            return "Error: La importación en lote falló después de " + maxRetries + " intentos.";
        }

        // 1. Identificar nuevos elementos importados
        var newItems = [];
        for (var k = 0; k < targetBin.children.numItems; k++) {
            var item = targetBin.children[k];
            if (!uidsBeforeImport.hasOwnProperty(item.nodeId)) {
                newItems.push(item);
            }
        }

        // 2. Insertar en Timeline (si se solicitó)
        if (addToTimeline && newItems.length > 0) {
            var sequence = app.project.activeSequence;
            if (sequence) {
                var playheadTimeObject = new Time();
                playheadTimeObject.seconds = playheadTime || 0;

                for (var n = 0; n < newItems.length; n++) {
                    var currentItem = newItems[n];
                    var avDetection = detectAVviaXMP(currentItem);

                    var mediaPath = "";
                    try { mediaPath = currentItem.getMediaPath().toLowerCase(); } catch (e) { mediaPath = ""; }
                    var isAudioFile = /\.(mp3|m4a|wav|flac|aac|ogg|opus|weba)$/i.test(mediaPath);
                    var isImage = /\.(jpg|jpeg|png|gif|bmp|tiff|tif|svg|webp)$/i.test(mediaPath);

                    if (avDetection.video && avDetection.audio) {
                        handleMixedClipInsert(sequence, playheadTimeObject, currentItem);
                    } else if (avDetection.video && !avDetection.audio) {
                        if (!importImagesToTimeline && isImage) {
                            continue;
                        }
                        var vTrack = findAvailableVideoTrack(sequence, playheadTimeObject, currentItem);
                        if (vTrack) {
                            vTrack.insertClip(currentItem, playheadTimeObject);
                        }
                    } else if (!avDetection.video && avDetection.audio) {
                        var aTrack = findAvailableAudioTrack(sequence, playheadTimeObject, currentItem);
                        if (aTrack) {
                            aTrack.insertClip(currentItem, playheadTimeObject);
                        }
                    } else if (!avDetection.video && !avDetection.audio) {
                        if (isAudioFile) {
                            var aTrack = findAvailableAudioTrack(sequence, playheadTimeObject, currentItem);
                            if (aTrack) {
                                aTrack.insertClip(currentItem, playheadTimeObject);
                            }
                        } else if (!isImage) {
                            var vTrack = findAvailableVideoTrack(sequence, playheadTimeObject, currentItem);
                            if (vTrack) {
                                vTrack.insertClip(currentItem, playheadTimeObject);
                            } else {
                                var aTrack2 = findAvailableAudioTrack(sequence, playheadTimeObject, currentItem);
                                if (aTrack2) {
                                    aTrack2.insertClip(currentItem, playheadTimeObject);
                                }
                            }
                        }
                    }
                }
            }
        }

        // 3. Organizar en subcarpetas inteligentes directamente en la raíz de DowP
        for (var m = 0; m < newItems.length; m++) {
            var itemToMove = newItems[m];
            var type = "Video";
            var av = detectAVviaXMP(itemToMove);

            var mPath = "";
            try { mPath = itemToMove.getMediaPath().toLowerCase(); } catch (e) { mPath = ""; }

            var isImageFile = /\.(jpg|jpeg|png|gif|bmp|tiff|tif|svg|webp)$/i.test(mPath);
            var isAudioExt = /\.(mp3|m4a|wav|flac|aac|ogg|opus|weba)$/i.test(mPath);

            if (isImageFile) {
                type = "Imágenes";
            } else if (isAudioExt || (av.audio && !av.video)) {
                type = "Audio";
            } else if (av.video) {
                type = "Video";
            }

            var subBin = getOrCreateSubBin(mainBin, type);
            if (subBin && subBin !== itemToMove.parentBin) {
                itemToMove.moveBin(subBin);
            }
        }

        return "success";
    } catch (error) {
        return "Error en importForPremiere: " + error.toString();
    }
}

function findAvailableVideoTrack(sequence, playheadTimeObject, mediaItem) {
    try {
        var clipDuration = getClipDuration(mediaItem);
        var clipEndTime = playheadTimeObject.seconds + clipDuration;

        for (var i = 0; i < sequence.videoTracks.numTracks; i++) {
            var currentTrack = sequence.videoTracks[i];
            var isRangeFree = true;
            for (var j = 0; j < currentTrack.clips.numItems; j++) {
                var currentClip = currentTrack.clips[j];
                var EPSILON = 0.04; // Aumentado a 40ms (1 fotograma)
                if (!(clipEndTime <= currentClip.start.seconds + EPSILON || playheadTimeObject.seconds >= currentClip.end.seconds - EPSILON)) {
                    logToDowP("Colisión Video V" + (i + 1) + " con clip '" + currentClip.name + "'. (Playhead: " + playheadTimeObject.seconds + ", End: " + currentClip.end.seconds + ")", "info");
                    isRangeFree = false;
                    break;
                }
            }
            if (isRangeFree) {
                logToDowP("findAvailableVideoTrack: Asignando a pista V" + (i + 1), "info");
                return currentTrack;
            } else {
                logToDowP("findAvailableVideoTrack: Pista V" + (i + 1) + " ocupada por colisión.", "info");
            }
        }

        var qeSequence = qe.project.getActiveSequence();
        if (qeSequence) {
            var currentVideoTrackCount = sequence.videoTracks.numTracks;
            qeSequence.addTracks(1, currentVideoTrackCount, 0, 0, 0);
            app.project.activeSequence = app.project.activeSequence;
            return sequence.videoTracks[currentVideoTrackCount];
        }
    } catch (e) {
        return null;
    }

    return null;
}

function findAvailableAVPairWithDuration(sequence, playheadTimeObject, durationSeconds) {
    try {
        var clipEndTime = playheadTimeObject.seconds + durationSeconds;
        var numV = sequence.videoTracks.numTracks;
        var numA = sequence.audioTracks.numTracks;
        var maxPairs = Math.min(numV, numA);

        for (var i = 0; i < maxPairs; i++) {
            var vTrack = sequence.videoTracks[i];
            var videoFree = true;
            for (var j = 0; j < vTrack.clips.numItems; j++) {
                var vClip = vTrack.clips[j];
                var EPSILON = 0.04;
                if (!(clipEndTime <= vClip.start.seconds + EPSILON || playheadTimeObject.seconds >= vClip.end.seconds - EPSILON)) {
                    logToDowP("findAVPairWD: Colisión V" + (i + 1) + " con '" + vClip.name + "' (ClipEnd:" + clipEndTime + " vs ClipStart:" + vClip.start.seconds + ", Playhead:" + playheadTimeObject.seconds + " vs ClipEnd:" + vClip.end.seconds + ")", "info");
                    videoFree = false;
                    break;
                }
            }
            if (!videoFree) continue;

            var aTrack = sequence.audioTracks[i];
            var audioFree = true;
            if (aTrack) {
                for (var k = 0; k < aTrack.clips.numItems; k++) {
                    var aClip = aTrack.clips[k];
                    var EPSILON = 0.04;
                    if (!(clipEndTime <= aClip.start.seconds + EPSILON || playheadTimeObject.seconds >= aClip.end.seconds - EPSILON)) {
                        logToDowP("findAVPairWD: Colisión A" + (i + 1) + " con '" + aClip.name + "'", "info");
                        audioFree = false;
                        break;
                    }
                }
            }
            if (audioFree) {
                logToDowP("findAVPairWD: Par libre en V" + (i + 1) + "/A" + (i + 1), "info");
                return i;
            }
        }
    } catch (e) {
        logToDowP("findAVPairWD: Error - " + e.toString(), "error");
        return -1;
    }
    logToDowP("findAVPairWD: No se encontró par libre.", "info");
    return -1;
}

function findTrackContainingClipAt(sequence, playheadTimeObject) {
    try {
        var EPSILON = 0.04;
        for (var i = sequence.videoTracks.numTracks - 1; i >= 0; i--) {
            var track = sequence.videoTracks[i];
            for (var j = 0; j < track.clips.numItems; j++) {
                var clip = track.clips[j];
                if (Math.abs(clip.start.seconds - playheadTimeObject.seconds) < EPSILON) {
                    return i;
                }
            }
        }
    } catch (e) {}
    return 0;
}

function detectNeededAudioTracks(projectItem) {
    try {
        var xmp = projectItem.getProjectMetadata() || "";
        var m = xmp.match(/(\d+)\s*(?:canal(es)?|channels?)/i);
        if (m && m[1]) {
            var count = parseInt(m[1], 10);
            if (!isNaN(count) && count > 0) {
                return (count <= 2) ? 1 : Math.ceil(count / 2);
            }
        }
        if (/stereo|estéreo|estereo/i.test(xmp)) return 1;
        if (/mono/i.test(xmp)) return 1;
        if (/5\.1|5.1/i.test(xmp)) return 1;
    } catch (e) {
    }
    return 1;
}

function findAvailableAVPair(sequence, playheadTimeObject, mediaItem) {
    try {
        var clipDuration = getClipDuration(mediaItem);
        var clipEndTime = playheadTimeObject.seconds + clipDuration;

        var numV = sequence.videoTracks.numTracks;
        var numA = sequence.audioTracks.numTracks;
        var neededAudioTracks = detectNeededAudioTracks(mediaItem);

        var maxPairs = Math.min(numV, Math.max(0, numA - (neededAudioTracks - 1)));

        for (var i = 0; i < maxPairs; i++) {
            var vTrack = sequence.videoTracks[i];
            var videoFree = true;
            for (var j = 0; j < vTrack.clips.numItems; j++) {
                var vClip = vTrack.clips[j];
                var EPSILON = 0.04;
                if (!(clipEndTime <= vClip.start.seconds + EPSILON || playheadTimeObject.seconds >= vClip.end.seconds - EPSILON)) {
                    logToDowP("Colisión AV-Video V" + (i + 1) + " con clip '" + vClip.name + "'. (Playhead: " + playheadTimeObject.seconds + ", End: " + vClip.end.seconds + ")", "info");
                    videoFree = false;
                    break;
                }
            }
            if (!videoFree) continue;

            var audioOk = true;
            for (var aOff = 0; aOff < neededAudioTracks; aOff++) {
                var ai = i + aOff;
                var aTrack = sequence.audioTracks[ai];
                if (!aTrack) {
                    audioOk = false;
                    break;
                }
                for (var k = 0; k < aTrack.clips.numItems; k++) {
                    var aClip = aTrack.clips[k];
                    var EPSILON = 0.04;
                    if (!(clipEndTime <= aClip.start.seconds + EPSILON || playheadTimeObject.seconds >= aClip.end.seconds - EPSILON)) {
                        logToDowP("Colisión AV-Audio A" + (ai + 1) + " con clip '" + aClip.name + "'. (Playhead: " + playheadTimeObject.seconds + ", End: " + aClip.end.seconds + ")", "info");
                        audioOk = false;
                        break;
                    }
                }
                if (!audioOk) {
                    logToDowP("findAvailableAVPair: Par AV (V" + (i + 1) + ") ocupado en pistas de audio.", "info");
                    break;
                }
            }
            if (audioOk) {
                logToDowP("findAvailableAVPair: Asignando par AV en V" + (i + 1), "info");
                return i;
            }
        }
    } catch (e) {
        logToDowP("findAvailableAVPair: Error interno - " + e.toString(), "error");
        return -1;
    }

    logToDowP("findAvailableAVPair: No se encontró par libre, se crearán pistas.", "info");
    return -1;
}

function handleMixedClipInsert(sequence, playheadTimeObject, mediaItem) {
    try {
        var qeSequence = null;
        try {
            qeSequence = qe.project.getActiveSequence();
        } catch (e) {
            qeSequence = null;
        }

        var neededAudioTracks = detectNeededAudioTracks(mediaItem);
        var freeIndex = findAvailableAVPair(sequence, playheadTimeObject, mediaItem);

        if (freeIndex >= 0) {
            sequence.videoTracks[freeIndex].insertClip(mediaItem, playheadTimeObject);
            return;
        }

        var numV = sequence.videoTracks.numTracks;
        var numA = sequence.audioTracks.numTracks;
        var desiredIndex = Math.max(numV, numA);

        var needVideoToAdd = Math.max(0, (desiredIndex + 1) - numV);
        var needAudioToAdd = Math.max(0, (desiredIndex + neededAudioTracks) - numA);

        if (qeSequence) {
            if (needVideoToAdd > 0) {
                qeSequence.addTracks(needVideoToAdd, numV, 0, 0, 0);
            }
            if (needAudioToAdd > 0) {
                var baseType = 1;
                var currentAudioCount = sequence.audioTracks.numTracks;
                qeSequence.addTracks(0, 0, needAudioToAdd, baseType, currentAudioCount);
            }
            app.project.activeSequence = app.project.activeSequence;
        }

        var newVIndex = Math.max(desiredIndex, sequence.videoTracks.numTracks - 1);
        sequence.videoTracks[newVIndex].insertClip(mediaItem, playheadTimeObject);
    } catch (e) {
    }
}

function findAvailableAudioTrack(sequence, playheadTimeObject, mediaItem) {
    try {
        var clipDuration = getClipDuration(mediaItem);
        var clipEndTime = playheadTimeObject.seconds + clipDuration;

        for (var i = 0; i < sequence.audioTracks.numTracks; i++) {
            var currentTrack = sequence.audioTracks[i];
            var isRangeFree = true;
            for (var j = 0; j < currentTrack.clips.numItems; j++) {
                var currentClip = currentTrack.clips[j];
                var EPSILON = 0.04;
                if (!(clipEndTime <= currentClip.start.seconds + EPSILON || playheadTimeObject.seconds >= currentClip.end.seconds - EPSILON)) {
                    logToDowP("Colisión Audio A" + (i + 1) + " con clip '" + currentClip.name + "'. (Playhead: " + playheadTimeObject.seconds + ", End: " + currentClip.end.seconds + ")", "info");
                    isRangeFree = false;
                    break;
                }
            }
            if (isRangeFree) {
                logToDowP("findAvailableAudioTrack: Asignando a pista A" + (i + 1), "info");
                return currentTrack;
            } else {
                logToDowP("findAvailableAudioTrack: Pista A" + (i + 1) + " ocupada por colisión.", "info");
            }
        }

        var qeSequence = qe.project.getActiveSequence();
        if (qeSequence) {
            var firstTrack = sequence.audioTracks[0];
            var baseType = firstTrack.audioTrackType;

            var audioTypeMap = {
                "Mono": 0,
                "Stereo": 1,
                "5.1": 2,
                "Adaptive": 3
            };

            var audioType = audioTypeMap[baseType] !== undefined ? audioTypeMap[baseType] : 1;

            var vCount = sequence.videoTracks.numTracks;
            var aCount = sequence.audioTracks.numTracks;

            qeSequence.addTracks(0, vCount, 1, audioType, aCount);

            return sequence.audioTracks[sequence.audioTracks.numTracks - 1];
        }
    } catch (e) {
        return null;
    }

    return null;
}

function importForAfterEffects(filePaths, addToTimeline, playheadTime, importImagesToTimeline, targetBinName) {
    try {
        if (!app.project) return "Error: No hay un proyecto abierto en After Effects.";

        app.beginUndoGroup("Importar desde DowP");
        var project = app.project;
        var mainBinName = "DowP Imports";
        var mainBin = null;

        for (var i = 1; i <= project.numItems; i++) {
            var item = project.item(i);
            if (item.name === mainBinName && item instanceof FolderItem) {
                mainBin = item;
                break;
            }
        }
        if (mainBin === null) {
            mainBin = project.items.addFolder(mainBinName);
        }

        var targetBin = mainBin;

        // Ignoramos targetBinName para evitar carpetas redundantes

        var mediaItems = [];
        var successfullyImportedCount = 0;

        for (var j = 0; j < filePaths.length; j++) {
            var currentPath = filePaths[j];
            var lowerPath = currentPath.toLowerCase();

            if (/\.(srt|vtt|ass|ssa|sub)$/i.test(lowerPath)) continue;

            // --- INICIO DE LA MODIFICACIÓN ---

            var importedItem = null;
            var maxRetries = 3;
            var retryDelay = 500; // Empezar con 500ms (0.5s) de retraso

            for (var attempt = 1; attempt <= maxRetries; attempt++) {
                try {
                    // Limpiar caché en CADA intento
                    clearCacheForExistingItems(currentPath, targetBin);

                    // Pausa preventiva. Aumenta en cada intento.
                    // Intento 1: 250ms
                    // Intento 2: 500ms
                    // Intento 3: 1000ms
                    $.sleep((attempt === 1) ? 250 : (retryDelay * (attempt - 1)));

                    var importOptions = new ImportOptions(new File(currentPath));

                    if (importOptions.canImportAs && importOptions.canImportAs(ImportAsType.FOOTAGE)) {
                        importOptions.importAs = ImportAsType.FOOTAGE;
                    }

                    importOptions.sequence = false;

                    importedItem = project.importFile(importOptions); // <--- Intento de importación

                    if (importedItem) {
                        // Determinar carpeta de destino inteligente directamente en mainBin
                        var folderName = "Video";
                        var isImageExt = /\.(jpg|jpeg|png|gif|bmp|tiff|tif|svg|webp)$/i.test(lowerPath);
                        var isAudioExt = /\.(mp3|m4a|wav|flac|aac|ogg|opus|weba)$/i.test(lowerPath);

                        if (isImageExt) {
                            folderName = "Imágenes";
                        } else if (isAudioExt || (importedItem.hasAudio && !importedItem.hasVideo)) {
                            folderName = "Audio";
                        }

                        // Usar siempre mainBin para evitar anidamiento excesivo
                        var subFolder = getOrCreateSubFolder(mainBin, folderName);
                        importedItem.parentFolder = subFolder;

                        // (Lógica de refresco de caché que ya tenías)
                        if (importedItem.file && importedItem.file.exists) {
                            try { importedItem.replace(importedItem.file); } catch (e_rep) { }
                        }

                        $.writeln("Importación exitosa en intento " + attempt + " para: " + currentPath);
                        break; // Salir del bucle de reintento
                    }

                } catch (e) {
                    // Imprime el error real en la consola de ExtendScript
                    $.writeln("[ERROR] Intento " + attempt + " falló para " + currentPath + ": " + e.toString());

                    if (attempt === maxRetries) {
                        // Si fallan todos los reintentos, registrar el error
                        $.writeln("ERROR: Fallaron todos los reintentos de importación para " + currentPath);
                        // 'importedItem' seguirá siendo null
                    }
                }
            } // Fin del bucle for (reintentos)


            // (Esta lógica ahora está FUERA del bloque try/catch de importación)
            if (importedItem) {

                var isImage = /\.(jpg|jpeg|png|gif|bmp|tiff|tif)$/i.test(lowerPath);
                var isAudio = /\.(mp3|m4a|wav|flac|aac|ogg|opus|weba)$/i.test(lowerPath);
                var isVideo = /\.(mp4|mkv|webm|mov|avi|flv|wmv|m4v)$/i.test(lowerPath);

                $.writeln("DEBUG: Importado - " + currentPath);
                $.writeln("  - hasVideo: " + importedItem.hasVideo);
                $.writeln("  - hasAudio: " + importedItem.hasAudio);
                $.writeln("  - isImage: " + isImage);
                $.writeln("  - isAudio: " + isAudio);
                $.writeln("  - isVideo: " + isVideo);

                var isImportable = importedItem.hasVideo || importedItem.hasAudio || isAudio || isVideo || isImage;

                if (importedItem && isImportable) {
                    successfullyImportedCount++; // Aumentamos el contador de archivos importados con éxito

                    if (isImage && !importImagesToTimeline) {
                        $.writeln("  - SALTADO (Timeline): Imagen y 'importImagesToTimeline' está desactivado.");
                        continue;
                    }

                    $.writeln("  - AÑADIDO a mediaItems (para timeline)");
                    mediaItems.push(importedItem);

                } else {
                    $.writeln("  - RECHAZADO: No tiene audio/video y no es extensión reconocida");
                }

            }

        }

        if (addToTimeline && mediaItems.length > 0) {
            var comp = getActiveCompSticky();
            if (comp) {
                for (var m = 0; m < mediaItems.length; m++) {
                    try {
                        var newLayer = comp.layers.add(mediaItems[m]);
                        newLayer.startTime = playheadTime || 0;
                        newLayer.moveToBeginning();

                        comp.displayStartTime = comp.displayStartTime;
                    } catch (e) {
                        continue;
                    }
                }

                try {
                    comp.openInViewer();
                } catch (e) {
                }
            }
        }

        app.endUndoGroup();

        if (successfullyImportedCount === 0) {
            return "Error: No se pudieron importar archivos. Verifica que los archivos sean válidos.";
        }

        return "success";
    } catch (error) {
        app.endUndoGroup();
        return "Error en importForAfterEffects: " + error.toString();
    }
}

function getClipDuration(mediaItem) {
    try {
        if (mediaItem.getOutPoint && mediaItem.getInPoint) {
            return mediaItem.getOutPoint().seconds - mediaItem.getInPoint().seconds;
        }
        if (mediaItem.duration) {
            return mediaItem.duration.seconds;
        }
        return 10.0;
    } catch (e) {
        return 10.0;
    }
}

function getItemUIDs(bin) {
    var uids = {};
    try {
        for (var i = 0; i < bin.children.numItems; i++) {
            uids[bin.children[i].nodeId] = true;
        }
    } catch (e) {
    }
    return uids;
}

function detectAVviaXMP(projectItem) {
    var hasVideo = false;
    var hasAudio = false;

    try {
        var xmp = projectItem.getProjectMetadata();

        if (xmp) {
            if (xmp.indexOf("VideoInfo") !== -1 ||
                xmp.indexOf("vcodec") !== -1 ||
                xmp.indexOf("width") !== -1 ||
                xmp.indexOf("height") !== -1) {
                hasVideo = true;
            }

            if (xmp.indexOf("AudioInfo") !== -1 ||
                xmp.indexOf("acodec") !== -1 ||
                xmp.indexOf("channels") !== -1 ||
                xmp.indexOf("audio") !== -1) {
                hasAudio = true;
            }

            $.writeln("DEBUG detectAVviaXMP:");
            $.writeln("  - hasVideo: " + hasVideo);
            $.writeln("  - hasAudio: " + hasAudio);
            $.writeln("  - XMP length: " + xmp.length);
            if (xmp.length > 0 && xmp.length < 500) {
                $.writeln("  - XMP content: " + xmp);
            }
        } else {
            $.writeln("DEBUG: No XMP metadata found for " + projectItem.name);
        }
    } catch (e) {
        $.writeln("ERROR in detectAVviaXMP: " + e.toString());
    }

    return { video: hasVideo, audio: hasAudio };
}

function getConfigFilePath() {
    try {
        var userFolder = Folder.userData;
        var configFolder = new Folder(userFolder.fsName + "/DowP_Importer");

        if (!configFolder.exists) {
            configFolder.create();
        }

        return configFolder.fsName + "/config.json";
    } catch (e) {
        return null;
    }
}

function saveConfig(key, value) {
    try {
        var configPath = getConfigFilePath();
        if (!configPath) return "error";

        var configFile = new File(configPath);
        var config = {};

        if (configFile.exists) {
            configFile.open("r");
            var content = configFile.read();
            configFile.close();

            if (content && content !== "") {
                try {
                    config = JSON.parse(content);
                } catch (e) {
                    config = {};
                }
            }
        }

        config[key] = value;

        configFile.open("w");
        configFile.encoding = "UTF-8";
        configFile.write(JSON.stringify(config, null, 2));
        configFile.close();

        return "success";
    } catch (e) {
        return "error: " + e.toString();
    }
}

function loadConfig(key) {
    try {
        var configPath = getConfigFilePath();
        if (!configPath) return null;

        var configFile = new File(configPath);

        if (!configFile.exists) {
            return null;
        }

        configFile.open("r");
        var content = configFile.read();
        configFile.close();

        if (!content || content === "") {
            return null;
        }

        var config = JSON.parse(content);
        return config[key] || null;
    } catch (e) {
        return null;
    }
}

function findDowPExecutable() {
    try {
        if (isMacOS()) {
            // Folder.userData en macOS = ~/Library/Application Support
            var appSupport = Folder.userData;
            var homeMac = appSupport.parent.parent;  // ~/Library -> ~

            var macCandidates = [
                "/Applications/DowP.app",
                homeMac.fsName + "/Applications/DowP.app",
                appSupport.fsName + "/DowP/DowP.app"
            ];

            for (var i = 0; i < macCandidates.length; i++) {
                // Un .app es un directorio: hay que comprobarlo como Folder,
                // File.exists devolveria false siempre.
                var bundle = new Folder(macCandidates[i]);
                if (bundle.exists) {
                    return bundle.fsName;
                }
            }

            return "not_found";
        }

        // ── Windows ──
        var userFolder = Folder.userData;            // %APPDATA% (Roaming)
        var localAppData = userFolder.parent.fsName + "\\Local";

        var winCandidates = [
            localAppData + "\\DowP\\DowP.exe",
            localAppData + "\\Programs\\DowP\\DowP.exe",
            "C:\\Program Files\\DowP\\DowP.exe"
        ];

        for (var j = 0; j < winCandidates.length; j++) {
            var exe = new File(winCandidates[j]);
            if (exe.exists) {
                return exe.fsName;
            }
        }

        return "not_found";
    } catch (e) {
        return "error: " + e.toString();
    }
}

function getSelectionForDowP() {
    // Devuelve la seleccion del usuario con el RECORTE de origen de cada clip, para que
    // DowP reciba el medio completo pero con el corte ya marcado en la waveform. Formato:
    //   { items: [{path, name, hasTrim, in, out}], skipped: ["nombre (motivo)"] }
    // Lo que no se pueda mandar se informa en 'skipped' en vez de desaparecer en silencio.
    var out = { items: [], skipped: [] };
    var seen = {};

    function skip(name, reason) {
        out.skipped.push((name || "(sin nombre)") + " - " + reason);
    }

    function addItem(path, inSec, outSec, name) {
        if (!path) { skip(name, "sin archivo en disco"); return; }
        var f = new File(path);
        if (!f.exists) { skip(name, "el archivo ya no existe"); return; }

        var hasTrim = (inSec !== null && outSec !== null &&
                       !isNaN(inSec) && !isNaN(outSec) && outSec > inSec);
        // Dos clips iguales con el MISMO corte son el mismo trabajo; con cortes distintos
        // son dos, y por eso la clave incluye el rango.
        var key = f.fsName + "|" + (hasTrim ? (inSec.toFixed(3) + "-" + outSec.toFixed(3)) : "full");
        if (seen[key]) return;
        seen[key] = true;

        out.items.push({
            path: f.fsName,
            name: name || f.name,
            hasTrim: hasTrim,
            "in": hasTrim ? inSec : null,
            "out": hasTrim ? outSec : null
        });
    }

    try {
        var host = getHostAppName();

        if (host === "Adobe Premiere Pro") {
            // 1) Clips seleccionados en la linea de tiempo: llevan recorte propio.
            try {
                if (app.project && app.project.activeSequence) {
                    var clips = app.project.activeSequence.getSelection();
                    for (var k = 0; k < clips.length; k++) {
                        var clip = clips[k];
                        var clipName = "clip";
                        try { clipName = clip.name || "clip"; } catch (eN) {}

                        var mediaPath = null;
                        try {
                            if (clip.projectItem && clip.projectItem.getMediaPath) {
                                mediaPath = clip.projectItem.getMediaPath();
                            }
                        } catch (eP) { mediaPath = null; }

                        if (!mediaPath) {
                            skip(clipName, "no es un medio de archivo (titulo, color, ajuste...)");
                            continue;
                        }

                        // Velocidad alterada o invertida: el rango de origen ya no
                        // corresponde 1:1 con lo que se ve en la linea de tiempo, asi que
                        // se manda el medio completo y se avisa, en vez de inventar un corte.
                        var speed = 1;
                        try { speed = clip.getSpeed(); } catch (eS) { speed = 1; }
                        if (speed !== 1) {
                            addItem(mediaPath, null, null, clipName);
                            skip(clipName, "velocidad alterada: va el medio completo, sin corte");
                            continue;
                        }

                        var inSec = null, outSec = null;
                        try {
                            inSec = clip.inPoint.seconds;
                            outSec = clip.outPoint.seconds;
                        } catch (eIO) { inSec = outSec = null; }

                        addItem(mediaPath, inSec, outSec, clipName);
                    }
                }
            } catch (eTl) {
                skip("linea de tiempo", "error leyendo la seleccion: " + eTl.toString());
            }

            // 2) Seleccion del panel de proyecto: medios completos, sin recorte.
            try {
                if (app.project && app.project.getSelection) {
                    var items = app.project.getSelection();
                    for (var i = 0; i < items.length; i++) {
                        var item = items[i];
                        if (!item) continue;
                        var itemName = "item";
                        try { itemName = item.name || "item"; } catch (eIN) {}
                        try {
                            if (item.type === ProjectItemType.BIN) {
                                skip(itemName, "es una carpeta");
                                continue;
                            }
                        } catch (eT) {}
                        var itemPath = null;
                        try {
                            if (item.getMediaPath) itemPath = item.getMediaPath();
                        } catch (eMP) { itemPath = null; }
                        if (!itemPath) { skip(itemName, "no tiene archivo en disco"); continue; }
                        addItem(itemPath, null, null, itemName);
                    }
                }
            } catch (ePr) {
                skip("panel de proyecto", "error leyendo la seleccion: " + ePr.toString());
            }

        } else if (host === "Adobe After Effects") {
            // 1) Capas seleccionadas de la composicion (la sticky, para que no dependa de
            //    que el visor de comp sea el frontal -- ver getActiveCompSticky).
            var comp = getActiveCompSticky();
            if (comp) {
                var layers = [];
                try { layers = comp.selectedLayers; } catch (eSL) { layers = []; }
                for (var m = 0; m < layers.length; m++) {
                    var layer = layers[m];
                    var layerName = "capa";
                    try { layerName = layer.name || "capa"; } catch (eLN) {}

                    var srcFile = null;
                    try {
                        if (layer.source && layer.source.file) srcFile = layer.source.file.fsName;
                    } catch (eSF) { srcFile = null; }
                    if (!srcFile) {
                        skip(layerName, "no es un medio de archivo (solido, texto, forma...)");
                        continue;
                    }

                    // inPoint/outPoint estan en tiempo de COMPOSICION. La conversion a
                    // tiempo de origen solo es valida sin remapeo y a velocidad normal;
                    // en cualquier otro caso se manda el medio completo y se avisa.
                    var remapped = false, stretch = 100;
                    try { remapped = layer.timeRemapEnabled; } catch (eR) {}
                    try { stretch = layer.stretch; } catch (eSt) {}

                    if (remapped || Math.abs(stretch - 100) > 0.001) {
                        addItem(srcFile, null, null, layerName);
                        skip(layerName, "tiene remapeo/estiramiento de tiempo: va el medio completo, sin corte");
                        continue;
                    }

                    var lIn = null, lOut = null;
                    try {
                        lIn = layer.inPoint - layer.startTime;
                        lOut = layer.outPoint - layer.startTime;
                        if (lIn < 0) lIn = 0;
                    } catch (eLIO) { lIn = lOut = null; }

                    addItem(srcFile, lIn, lOut, layerName);
                }
            }

            // 2) Seleccion del panel de proyecto: medios completos.
            try {
                var projSel = app.project ? app.project.selection : null;
                if (projSel) {
                    for (var n = 0; n < projSel.length; n++) {
                        var pItem = projSel[n];
                        var pName = "item";
                        try { pName = pItem.name || "item"; } catch (ePN) {}
                        if (pItem instanceof FolderItem) { skip(pName, "es una carpeta"); continue; }
                        if (pItem instanceof CompItem) { skip(pName, "es una composicion, no un archivo"); continue; }
                        if (pItem instanceof FootageItem && pItem.file) {
                            addItem(pItem.file.fsName, null, null, pName);
                        } else {
                            skip(pName, "no tiene archivo en disco");
                        }
                    }
                }
            } catch (ePj) {
                skip("panel de proyecto", "error leyendo la seleccion: " + ePj.toString());
            }
        } else if (host === "Adobe Photoshop") {
            // En Photoshop lo que se manda es el documento activo. Solo tiene sentido si
            // ya existe como archivo en disco: DowP trabaja sobre archivos, no sobre el
            // estado en memoria del editor.
            var psDoc = getPhotoshopActiveDocument();
            if (!psDoc) {
                skip("documento", "no hay ningun documento abierto");
            } else {
                var docName = "documento";
                try { docName = psDoc.name || "documento"; } catch (eDN) {}
                var docPath = null;
                try { docPath = psDoc.fullName ? psDoc.fullName.fsName : null; } catch (eFN) { docPath = null; }
                if (!docPath) {
                    skip(docName, "el documento no se ha guardado todavia");
                } else {
                    addItem(docPath, null, null, docName);
                }
            }
        } else {
            skip("aplicacion", "host no soportado: " + host);
        }
    } catch (e) {
        skip("seleccion", "error inesperado: " + e.toString());
    }

    try {
        return JSON.stringify(out);
    } catch (eJ) {
        return '{"items":[],"skipped":["error serializando la seleccion"]}';
    }
}

// FUNCIÓN DE DIAGNÓSTICO - Eliminar después de resolver el problema
function debugProjectSelection() {
    var report = [];

    try {
        if (!app.project) {
            return "ERROR: No hay proyecto abierto";
        }

        var selection = app.project.getSelection();
        report.push("=== DIAGNÓSTICO DE SELECCIÓN ===");
        report.push("Total items seleccionados: " + selection.length);
        report.push("");

        for (var i = 0; i < selection.length; i++) {
            var item = selection[i];
            report.push("--- Item " + i + " ---");
            report.push("name: " + (item.name || "undefined"));
            report.push("nodeId: " + (item.nodeId || "undefined"));

            // Tipo
            try {
                report.push("type: " + item.type);
            } catch (e) {
                report.push("type: ERROR - " + e.toString());
            }

            // Listar todas las propiedades disponibles
            report.push("Propiedades disponibles:");
            for (var prop in item) {
                try {
                    var value = item[prop];
                    var valueType = typeof value;
                    if (valueType === "function") {
                        report.push("  - " + prop + "() [función]");
                    } else {
                        report.push("  - " + prop + " = " + value + " [" + valueType + "]");
                    }
                } catch (e) {
                    report.push("  - " + prop + " [error al leer]");
                }
            }

            // Intentar todos los métodos conocidos para obtener ruta
            report.push("Intentos de obtener ruta:");

            try {
                if (item.getMediaPath) {
                    report.push("  getMediaPath(): " + item.getMediaPath());
                }
            } catch (e) {
                report.push("  getMediaPath(): ERROR - " + e.toString());
            }

            try {
                if (item.mediaPath) {
                    report.push("  mediaPath: " + item.mediaPath);
                }
            } catch (e) {
                report.push("  mediaPath: ERROR");
            }

            try {
                if (item.filePath) {
                    report.push("  filePath: " + item.filePath);
                }
            } catch (e) {
                report.push("  filePath: ERROR");
            }

            report.push("");
        }

        return report.join("\n");

    } catch (e) {
        return "ERROR CRÍTICO: " + e.toString();
    }
}

function getOrCreateSubBin(parentBin, binName) {
    try {
        if (!parentBin || !parentBin.children) return null;
        for (var i = 0; i < parentBin.children.numItems; i++) {
            var item = parentBin.children[i];
            if (item.name === binName && item.type === ProjectItemType.BIN) {
                return item;
            }
        }
        return parentBin.createBin(binName);
    } catch (e) {
        return parentBin;
    }
}

function getOrCreateSubFolder(parentFolder, folderName) {
    try {
        if (!parentFolder || !app.project) return null;
        for (var i = 1; i <= app.project.numItems; i++) {
            var item = app.project.item(i);
            if (item.name === folderName && item instanceof FolderItem && item.parentFolder === parentFolder) {
                return item;
            }
        }
        var newFolder = app.project.items.addFolder(folderName);
        newFolder.parentFolder = parentFolder;
        return newFolder;
    } catch (e) {
        return parentFolder;
    }
}