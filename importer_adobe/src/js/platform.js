/*
 * platform.js — Capa de abstracción multiplataforma para DowP Importer.
 *
 * Motivo: ExtendScript no puede lanzar procesos en macOS. `File.execute()` usa
 * LaunchServices, no acepta argumentos, y un bundle `.app` es un directorio,
 * así que `new File("/Applications/DowP.app").exists` siempre es false.
 * El lanzamiento se hace por tanto desde la capa CEP, que sí tiene APIs
 * equivalentes en Windows y macOS:
 *
 *   1. Node.js  (window.cep_node.require) — requiere --enable-nodejs en el manifest
 *   2. cep.process.createProcess()        — disponible con RequiredScriptAccess=full
 *   3. ExtendScript (executeDowP)         — último recurso
 *
 * Todo lo que expone este archivo es síncrono salvo `launch`, que usa callback.
 */
var DowPPlatform = (function () {

    // ── Detección de SO ─────────────────────────────────────────────────
    // navigator.platform reporta "MacIntel" también en Apple Silicon.
    var _plat = (navigator && navigator.platform) ? navigator.platform : "";
    var IS_MAC = /Mac/i.test(_plat);
    var IS_WIN = !IS_MAC && /Win/i.test(_plat);

    // ── Acceso a Node (opcional) ────────────────────────────────────────
    // Con --enable-nodejs y SIN --mixed-context, CEP inyecta window.cep_node.
    // No usamos --mixed-context a propósito: definiría `module`/`exports`
    // globales y el UMD de socket.io.js dejaría de publicar `window.io`.
    function nodeRequire(mod) {
        try {
            if (window.cep_node && typeof window.cep_node.require === 'function') {
                return window.cep_node.require(mod);
            }
            if (typeof require === 'function') {
                return require(mod);
            }
        } catch (e) { }
        return null;
    }

    function hasNode() {
        return nodeRequire('child_process') !== null;
    }

    function nodeEnv() {
        try {
            if (window.cep_node && window.cep_node.process) return window.cep_node.process.env;
            if (typeof process !== 'undefined' && process.env) return process.env;
        } catch (e) { }
        return null;
    }

    // ── Entorno contaminado por el host Adobe ───────────────────────────
    // Premiere/AE exportan sus propias rutas de librerías y plugins de Qt.
    // Heredarlas hace que una app PySide6 congelada con PyInstaller cargue
    // dylibs/plugins equivocados y muera al arrancar. Se eliminan siempre.
    var TOXIC_ENV_VARS = [
        'DYLD_LIBRARY_PATH', 'DYLD_FRAMEWORK_PATH', 'DYLD_INSERT_LIBRARIES',
        'DYLD_FALLBACK_LIBRARY_PATH', 'DYLD_FALLBACK_FRAMEWORK_PATH',
        'LD_LIBRARY_PATH', 'LD_PRELOAD',
        'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'QT_QPA_PLATFORM',
        'QML2_IMPORT_PATH', 'QML_IMPORT_PATH',
        'PYTHONHOME', 'PYTHONPATH', 'PYTHONEXECUTABLE', 'PYTHONSTARTUP',
        'SSL_CERT_FILE', 'SSL_CERT_DIR', 'OPENSSL_CONF'
    ];

    function cleanEnv() {
        var src = nodeEnv();
        if (!src) return undefined;

        var out = {};
        for (var k in src) {
            if (!src.hasOwnProperty(k)) continue;
            if (TOXIC_ENV_VARS.indexOf(k) !== -1) continue;
            out[k] = src[k];
        }
        return out;
    }

    // ── Existencia de rutas (funciona con bundles .app) ─────────────────
    function pathExists(p) {
        if (!p) return false;

        var fs = nodeRequire('fs');
        if (fs) {
            try { return fs.existsSync(p); } catch (e) { }
        }

        // cep.fs.stat sí resuelve directorios, a diferencia de File.exists.
        try {
            if (window.cep && window.cep.fs && typeof window.cep.fs.stat === 'function') {
                var r = window.cep.fs.stat(p);
                return !!(r && r.err === 0);
            }
        } catch (e) { }

        return true; // Sin forma de comprobar: no bloquear al usuario.
    }

    // ── Normalización de la ruta elegida por el usuario ─────────────────
    // En macOS el usuario puede acabar señalando el binario interno del
    // bundle. Lo replegamos al .app para poder lanzarlo con `open`.
    function normalizeTarget(p) {
        if (!p) return p;
        p = String(p).replace(/[\/\\]+$/, '');
        if (!IS_MAC) return p;

        var i = p.indexOf('.app/Contents/MacOS/');
        if (i !== -1) return p.substring(0, i + 4);
        return p;
    }

    function isAppBundle(p) {
        return IS_MAC && /\.app$/i.test(String(p || ''));
    }

    // ── Autodetección ───────────────────────────────────────────────────
    function defaultCandidates() {
        var env = nodeEnv() || {};

        if (IS_MAC) {
            var home = env.HOME || '';
            var mac = ['/Applications/DowP.app'];
            if (home) {
                mac.push(home + '/Applications/DowP.app');
                mac.push(home + '/Library/Application Support/DowP/DowP.app');
            }
            return mac;
        }

        var win = [];
        if (env.LOCALAPPDATA) {
            win.push(env.LOCALAPPDATA + '\\DowP\\DowP.exe');
            win.push(env.LOCALAPPDATA + '\\Programs\\DowP\\DowP.exe');
        }
        if (env.ProgramFiles) win.push(env.ProgramFiles + '\\DowP\\DowP.exe');
        return win;
    }

    // Etiqueta para los mensajes de la UI.
    function targetLabel() { return IS_MAC ? 'DowP.app' : 'DowP.exe'; }

    // ── Lanzamiento ─────────────────────────────────────────────────────
    // callback(ok:boolean, detail:string) — `detail` nombra el mecanismo usado
    // o el motivo del fallo, para que quede en el log del panel.

    function buildCommand(target, appId) {
        if (IS_MAC && isAppBundle(target)) {
            // `open -a` lanza vía LaunchServices: entorno limpio y, si DowP
            // ya está abierto, lo trae al frente en lugar de duplicarlo.
            return { cmd: '/usr/bin/open', args: ['-a', target, '--args', appId] };
        }
        // Windows (.exe) o binario suelto en macOS/Linux.
        return { cmd: target, args: [appId] };
    }

    function launchViaNode(target, appId) {
        var cp = nodeRequire('child_process');
        if (!cp) return false;

        var c = buildCommand(target, appId);
        var child = cp.spawn(c.cmd, c.args, {
            detached: true,
            stdio: 'ignore',
            env: cleanEnv(),
            // Sin cwd dentro de la carpeta de la extensión: evita que el
            // proceso hijo mantenga un handle abierto sobre ella.
            cwd: IS_MAC ? '/' : undefined
        });
        child.unref();
        return true;
    }

    function launchViaCepProcess(target, appId) {
        if (!(window.cep && window.cep.process && typeof window.cep.process.createProcess === 'function')) {
            return false;
        }

        var argv;
        if (IS_MAC && isAppBundle(target)) {
            // createProcess no permite fijar el entorno, así que se limpian las
            // variables tóxicas delegando en /usr/bin/env -u.
            argv = ['/usr/bin/env'];
            for (var i = 0; i < TOXIC_ENV_VARS.length; i++) {
                argv.push('-u', TOXIC_ENV_VARS[i]);
            }
            argv.push('/usr/bin/open', '-a', target, '--args', appId);
        } else {
            var c = buildCommand(target, appId);
            argv = [c.cmd].concat(c.args);
        }

        var res = window.cep.process.createProcess.apply(window.cep.process, argv);
        return !!(res && res.err === 0);
    }

    function launch(target, appId, csInterface, callback) {
        callback = callback || function () { };
        target = normalizeTarget(target);

        if (!target) {
            callback(false, 'ruta vacia');
            return;
        }

        if (!pathExists(target)) {
            callback(false, 'no se encontro ' + target);
            return;
        }

        try {
            if (launchViaNode(target, appId)) { callback(true, 'node'); return; }
        } catch (e) {
            console.warn('[DowP] Lanzamiento por Node fallo:', e);
        }

        try {
            if (launchViaCepProcess(target, appId)) { callback(true, 'cep.process'); return; }
        } catch (e) {
            console.warn('[DowP] Lanzamiento por cep.process fallo:', e);
        }

        // Último recurso: ExtendScript. En Windows sigue siendo el .bat de
        // siempre; en macOS intenta system.callSystem (solo AE) y Folder.execute.
        if (csInterface) {
            var esc = String(target).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
            csInterface.evalScript('executeDowP("' + esc + '", "' + appId + '")', function (result) {
                if (result === 'success') callback(true, 'extendscript');
                else callback(false, 'extendscript: ' + result);
            });
            return;
        }

        callback(false, 'sin mecanismo de lanzamiento disponible');
    }

    return {
        isMac: function () { return IS_MAC; },
        isWindows: function () { return IS_WIN; },
        hasNode: hasNode,
        nodeRequire: nodeRequire,
        pathExists: pathExists,
        normalizeTarget: normalizeTarget,
        isAppBundle: isAppBundle,
        defaultCandidates: defaultCandidates,
        targetLabel: targetLabel,
        launch: launch
    };
})();
