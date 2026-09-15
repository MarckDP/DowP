window.onload = function () {
    const csInterface = new CSInterface();
    const CURRENT_EXTENSION_VERSION = "1.9.1";
    const serverUrl = "http://127.0.0.1:7788";
    let thisAppName = "Desconocido";
    let thisAppIdentifier = "unknown";
    let socket = null;
    let toggleLinked = false;

    // Utility for remote logging to DowP
    function sendLogToDowP(message, level = 'info') {
        if (socket && socket.connected) {
            socket.emit('log_message', { level: level, message: message });
        }
    }

    // ✅ NUEVO: Estado de conexión centralizado
    const connectionState = {
        isConnecting: false,
        isLaunching: false,
        lastAttempt: 0,
        attemptCount: 0,
        connectionTimeout: null,
        maxRetries: 3
    };

    let isSocketRegistered = false;
    let unlinkingTimeout = null;

    let lastTimelineState = null;
    let checkingTimeline = false;
    let lastTimelineCheck = 0;
    const TIMELINE_CHECK_INTERVAL = 1500;

    let lastSuccessfulTimelineCheck = null;
    let timelineCheckFailureCount = 0;

    // Intencion del usuario sobre las casillas, separada de la disponibilidad real de la
    // linea de tiempo en el host. Sin esa separacion, un falso negativo momentaneo
    // borraba la eleccion del usuario y no se restauraba al recuperarse el estado.
    let panelReleased = false;
    let userWantsTimeline = false;
    let userWantsImages = false;
    let suppressIntentUpdate = false;

    // Importacion en curso: ExtendScript es de un solo hilo, asi que mientras importa no
    // puede responder a getActiveTimelineInfo().
    let importGuardCount = 0;
    let importGuardTimeout = null;

    // Identifica cada comprobacion para poder ignorar respuestas de llamadas viejas.
    let timelineCallSeq = 0;
    let currentTimelineCall = 0;

    let currentState = 'unconfigured';

    let messageQueue = [];
    let currentMessageType = 'info';
    let messageTimeout = null;
    let isShowingPersistentMessage = false;

    let isUpdateNoticeActive = false;
    let updateNoticeTimeout = null;

    const statusIndicator = document.getElementById('status-indicator');
    const logText = document.getElementById('log-text');
    const btnLink = document.getElementById('btn-check');
    const btnLaunch = document.getElementById('btn-launch');
    const btnSettings = document.getElementById('btn-settings');
    const btnSendToDowp = document.getElementById('btn-send-to-dowp');
    if (btnSendToDowp) btnSendToDowp.classList.add('is-disabled');
    const addToTimelineCheckbox = document.getElementById('add-to-timeline-checkbox');
    const addToTimelineContainer = document.getElementById('add-to-timeline-container');
    const importImagesCheckbox = document.getElementById('import-images-checkbox');
    const importImagesContainer = document.getElementById('import-images-container');

    const storage = {
        getDowpPath: () => {
            return new Promise((resolve) => {
                csInterface.evalScript('loadConfig("dowpPath")', (result) => {
                    if (result && result !== "null" && result !== "") {
                        resolve(result);
                    } else {
                        const legacy = localStorage.getItem('dowpPath');
                        if (legacy) {
                            storage.setDowpPath(legacy);
                            resolve(legacy);
                        } else {
                            resolve(null);
                        }
                    }
                });
            });
        },

        setDowpPath: (path) => {
            return new Promise((resolve) => {
                csInterface.evalScript(`saveConfig("dowpPath", "${path.replace(/\\/g, '\\\\')}")`, (result) => {
                    if (result === "success") {
                        localStorage.setItem('dowpPath', path);
                        resolve(true);
                    } else {
                        resolve(false);
                    }
                });
            });
        }
    };

    // ✅ NUEVO: Escuchar logs desde ExtendScript
    csInterface.addEventListener("com.dowp.log", function(event) {
        if (event.data) {
            try {
                var d = (typeof event.data === 'string') ? JSON.parse(event.data) : event.data;
                var msg = "[ExtendScript] " + d.message;
                console.log(msg);
                sendLogToDowP(msg, d.level || "info");
            } catch(e) {}
        }
    });

    function showMessage(text, type = 'info', persistent = false, duration = 0) {
        const DEFAULT_PERSISTENT_TIMEOUT = 8000;

        currentMessageType = type;
        logText.textContent = text;

        if (messageTimeout) {
            clearTimeout(messageTimeout);
            messageTimeout = null;
        }

        if (persistent) {
            isShowingPersistentMessage = true;
            const wait = (duration && duration > 0) ? duration : DEFAULT_PERSISTENT_TIMEOUT;
            messageTimeout = setTimeout(() => {
                isShowingPersistentMessage = false;
                messageTimeout = null;
                try { updateStatusMessage(); } catch (e) { }
            }, wait);
        } else {
            if (duration && duration > 0) {
                messageTimeout = setTimeout(() => {
                    if (logText.textContent === text) logText.textContent = '';
                    messageTimeout = null;
                    try { updateStatusMessage(); } catch (e) { }
                }, duration);
            }
        }
    }

    function updateStatusMessage() {
        if (isShowingPersistentMessage) return;

        if (isUpdateNoticeActive) {
            return;
        }

        switch (currentState) {
            case 'unconfigured':
                showMessage(`Hola, haz clic en ⚙️ para configurar DowP.`, 'info');
                break;
            case 'connecting':
                showMessage("Conectando con DowP...", 'info');
                break;
            case 'connected':
                showMessage(`✓ Enlazado con ${thisAppName}.`, 'success');
                break;
            case 'linked-elsewhere':
                showMessage("Conectado. Haz clic en 🔗 para enlazar.", 'info');
                break;
            case 'linked-other-app':
                const activeTarget = socket?.lastActiveTarget || 'otra aplicación';
                const otherAppName = activeTarget.charAt(0).toUpperCase() + activeTarget.slice(1);
                showMessage(`Enlazado con ${otherAppName}.`, 'warning');
                break;
            case 'dowp-closed':
                showMessage("DowP no está abierto.", 'warning');
                break;
            case 'disconnected':
            default:
                if (storage.getDowpPath()) {
                    showMessage("DowP no está abierto.", 'warning');
                } else {
                    showMessage(`Hola, haz clic en ⚙️ para configurar DowP.`, 'info');
                }
                break;
        }
    }

    function clearUpdateNotice() {
        if (isUpdateNoticeActive) {
            isUpdateNoticeActive = false;
            if (updateNoticeTimeout) {
                clearTimeout(updateNoticeTimeout);
                updateNoticeTimeout = null;
            }
            updateStatusMessage();
        }
    }

    function updateStatusIndicator() {
        let className = currentState;

        if (connectionState.isLaunching) {
            className = 'launching';
        } else if (currentState === 'linked-other-app') {
            className = 'linked-elsewhere';
        }

        statusIndicator.className = className;
    }

    function setState(newState, data = null) {
        const previousState = currentState;
        currentState = newState;

        if (newState === 'launching') {
            updateStatusIndicator();
            showMessage("Iniciando DowP...", 'info');
            return;
        }

        if (data && socket) {
            socket.lastActiveTarget = data.activeTarget;
        }

        if (previousState !== newState || newState === 'linked-elsewhere') {
            updateStatusIndicator();
            updateStatusMessage();
        }
    }

    function setLinkButtonState(state) {
        const btn = document.getElementById('btn-check');
        if (!btn) return;

        btn.classList.remove('state-disconnected', 'state-connecting', 'state-connected', 'state-linked-other', 'state-linked-me');
        btn.setAttribute('aria-pressed', 'false');

        switch (state) {
            case 'disconnected':
                btn.classList.add('state-disconnected');
                btn.title = 'DowP no está abierto';
                btn.innerHTML = '<span class="icon">⛔</span>';
                break;
            case 'connecting':
                btn.classList.add('state-connecting');
                btn.title = 'Conectando a DowP...';
                btn.innerHTML = '<span class="icon">⏳</span>';
                break;
            case 'connected':
                btn.classList.add('state-connected');
                btn.title = 'Conectado – pulsa para enlazar';
                btn.innerHTML = '<span class="icon">🔗</span>';
                break;
            case 'linked-other':
                btn.classList.add('state-linked-other');
                btn.title = 'Enlazado en otra aplicación';
                btn.innerHTML = '<span class="icon">🔒</span>';
                break;
            case 'linked-me':
                btn.classList.add('state-linked-me');
                btn.title = 'Enlazado contigo';
                btn.innerHTML = '<span class="icon">✅</span>';
                break;
            default:
                btn.classList.add('state-disconnected');
                btn.title = '';
                btn.innerHTML = '<span class="icon">❓</span>';
        }

        const btnSend = document.getElementById('btn-send-to-dowp');
        if (btnSend) {
            if (state === 'connected' || state === 'linked-me') {
                // Si estamos conectados, habilitar botón morado
                btnSend.classList.remove('is-disabled');
                btnSend.title = "Enviar selección a DowP";
            } else {
                // Si no, deshabilitar (gris)
                btnSend.classList.add('is-disabled');
                btnSend.title = "Conecta DowP para enviar archivos";
            }
        }
    }


    function setLaunchButtonState(state) {
        const btn = document.getElementById('btn-launch');
        if (!btn) return;
        btn.classList.remove('state-open', 'state-closed');

        if (state === 'open') {
            btn.classList.add('state-open');
            btn.title = 'DowP abierto';
            btn.setAttribute('aria-pressed', 'true');
        } else {
            btn.classList.add('state-closed');
            btn.title = 'Iniciar DowP';
            btn.setAttribute('aria-pressed', 'false');
        }
    }

    function _resolveTimelineElement() {
        return addToTimelineContainer || document.getElementById('add-to-timeline-container') || null;
    }

    function setTimelineActiveState(active, options = {}) {
        const el = _resolveTimelineElement();
        if (!el) return;

        el.classList.remove('glow-active', 'glow-strong', 'glow-pulse');

        const isStrong = options.strong || false;
        if (active && isStrong) {
            el.classList.add('glow-active', 'glow-strong', 'glow-pulse');
        }
    }

    // ✅ NUEVO: Función para resetear el estado de conexión
    function resetConnectionState() {
        connectionState.isConnecting = false;
        connectionState.attemptCount = 0;
        if (connectionState.connectionTimeout) {
            clearTimeout(connectionState.connectionTimeout);
            connectionState.connectionTimeout = null;
        }
    }

    // ✅ NUEVO: Verificar si podemos intentar conectar
    function canAttemptConnection() {
        const now = Date.now();
        const timeSinceLastAttempt = now - connectionState.lastAttempt;

        if (connectionState.isConnecting) {
            console.log("⏸️ Conexión ya en progreso");
            return false;
        }

        if (connectionState.isLaunching) {
            console.log("⏸️ DowP está iniciando");
            return false;
        }

        // ✅ CRÍTICO: Si ya alcanzamos el máximo de reintentos, NUNCA reintentar automáticamente
        if (connectionState.attemptCount >= connectionState.maxRetries) {
            console.log("🛑 Máximo de reintentos alcanzado. Se requiere acción manual.");
            return false;
        }

        if (timeSinceLastAttempt < 2000) {
            console.log("⏸️ Debounce: esperando 2s entre intentos");
            return false;
        }

        return true;
    }

    // ✅ REFACTORIZADO: Conexión al servidor con protecciones
    function connectToServer(forceConnection = false) {
        if (socket && socket.connected) {
            console.log("✅ Ya conectado al servidor");
            return;
        }

        if (!forceConnection && !canAttemptConnection()) {
            return;
        }

        console.log("🔌 Iniciando conexión al servidor...");

        connectionState.isConnecting = true;
        connectionState.lastAttempt = Date.now();
        connectionState.attemptCount++;

        if (!connectionState.isLaunching) {
            isShowingPersistentMessage = false;
            setState('connecting');
            updateStatusMessage();
            setLinkButtonState('connecting');
        }

        // ✅ CRÍTICO: Destruir socket anterior si existe
        if (socket) {
            console.log("🧹 Limpiando socket anterior");
            socket.removeAllListeners();
            socket.disconnect();
            socket = null;
        }

        // ✅ NUEVO: Timeout de seguridad (10 segundos)
        connectionState.connectionTimeout = setTimeout(() => {
            console.error("⏱️ Timeout de conexión alcanzado");
            resetConnectionState();

            if (!connectionState.isLaunching) {
                setState('dowp-closed');
                setLaunchButtonState('closed');
                setLinkButtonState('disconnected');
            }
        }, 10000);

        socket = io(serverUrl, {
            transports: ['polling', 'websocket'],
            reconnectionAttempts: 3,
            reconnectionDelay: 2000,
            timeout: 8000
        });

        socket.on('connect', () => {
            console.log("✅ Conectado al servidor");
            resetConnectionState();

            if (connectionState.isLaunching) {
                connectionState.isLaunching = false;
                showMessage("¡DowP iniciado correctamente!", 'success', true, 3000);
            }

            if (!isSocketRegistered) {
                socket.emit('register', { appIdentifier: thisAppIdentifier, extensionVersion: CURRENT_EXTENSION_VERSION });
                isSocketRegistered = true;
            }

            setLaunchButtonState('open');
            setLinkButtonState('connected');

            setTimeout(() => {
                socket.emit('get_active_target');
            }, 500);
        });

        socket.on('connect_error', (err) => {
            console.error("❌ Error de conexión:", err.message);
            resetConnectionState();

            if (!connectionState.isLaunching) {
                setState('dowp-closed');
                setLaunchButtonState('closed');
                setLinkButtonState('disconnected');
            }
        });

        socket.on('disconnect', (reason) => {
            console.log("🔌 Desconectado:", reason);
            isSocketRegistered = false;
            toggleLinked = false;
            resetConnectionState();

            if (!connectionState.isLaunching) {
                setState('disconnected');
                setLinkButtonState('disconnected');
                setLaunchButtonState('closed');
            }
        });

        socket.on('active_target_update', (data) => {
            if (unlinkingTimeout) {
                clearTimeout(unlinkingTimeout);
                unlinkingTimeout = null;
            }
            const activeTarget = data.activeTarget;
            if (!activeTarget) {
                toggleLinked = false;
                setState('linked-elsewhere', data);
                setLinkButtonState('connected');
            } else if (activeTarget === thisAppIdentifier) {
                toggleLinked = true;
                setState('connected', data);
                setLinkButtonState('linked-me');
            } else {
                toggleLinked = false;
                setState('linked-other-app', data);
                setLinkButtonState('linked-other');
            }
        });

        socket.on('dowp_version', (data) => {
            const appVersion = data && data.appVersion;
            if (!appVersion) return;
            if (appVersion === CURRENT_EXTENSION_VERSION) {
                console.log(`Panel y DowP sincronizados en v${appVersion}`);
                return;
            }
            console.warn(`Desfase de version: panel v${CURRENT_EXTENSION_VERSION}, DowP v${appVersion}`);
            showVersionMismatchNotice(appVersion);
        });

        socket.on('new_file', (data) => {
            if (data.filePackage) {
                importFileToProject(data.filePackage);
            }
        });

        socket.on('import_files', (data) => {
            if (data && data.files && data.files.length > 0) {
                console.log(`Recibido lote de ${data.files.length} elementos`);

                const normalFiles = [];

                data.files.forEach(pkg => {
                    if (pkg && pkg.filePath && pkg.subclips) {
                        // Subclips se procesan individualmente por ahora
                        importSubclipsToProject(pkg.filePath, pkg.subclips);
                    } else {
                        normalFiles.push(pkg);
                    }
                });

                if (normalFiles.length > 0) {
                    importBatchToProject(normalFiles, data.targetBin);
                }
            }
        });

        socket.on('import_subclips', (data) => {
            if (data && data.filePath && data.subclips && data.subclips.length > 0) {
                const msg = `Recibidos ${data.subclips.length} subclips para: ${data.filePath}`;
                console.log(msg);
                sendLogToDowP(msg, 'info');
                importSubclipsToProject(data.filePath, data.subclips);
            }
        });
    }

    function linkToThisApp() {
        clearUpdateNotice();

        // ✅ NUEVO: Al presionar el botón 🔗, resetear los contadores de reintento
        connectionState.attemptCount = 0;

        if (!socket || !socket.connected) {
            showMessage("Conectando y enlazando...", 'info', true);
            setLinkButtonState('connecting');

            if (socket) {
                socket.once('connect', () => {
                    socket.emit('set_active_target', { targetApp: thisAppIdentifier });
                });
            }

            connectToServer(true);
            return;
        }

        if (toggleLinked) {
            unlinkingTimeout = setTimeout(() => {
                showMessage('Desvinculando...', 'info', true, 2000);
            }, 500);
            socket.emit('clear_active_target');
            return;
        }

        socket.emit('set_active_target', { targetApp: thisAppIdentifier });
        setLinkButtonState('connecting');
    }

    function runImportScript(script, callback) {
        // Unico punto por el que se lanzan los scripts que IMPORTAN. Mientras uno corre,
        // ExtendScript (de un solo hilo) no puede contestar a getActiveTimelineInfo(), asi
        // que se suspenden las comprobaciones de linea de tiempo hasta que vuelva: sin
        // esto, la comprobacion vencia por tiempo y apagaba la casilla justo en el
        // instante de importar (ver checkActiveTimeline).
        beginImportGuard();
        let settled = false;
        csInterface.evalScript(script, (result) => {
            if (!settled) {
                settled = true;
                endImportGuard();
            }
            callback(result);
        });
    }

    function importFileToProject(filePackage) {
        const targetBinName = filePackage.targetBin || null;

        const AUDIO_EXTENSIONS = /\.(mp3|m4a|wav|flac|aac|ogg|opus|weba)$/i;
        const VIDEO_EXTENSIONS = /\.(mp4|mkv|webm|mov|avi|flv|wmv|m4v)$/i;
        // Incluye lo que exporta el Editor de Imagen de DowP (psd, avif, heic...): antes
        // caian en 'unknown' y no se importaban a ningun host.
        const IMAGE_EXTENSIONS = /\.(jpg|jpeg|png|gif|bmp|tiff|tif|webp|avif|heic|heif|psd|psb|svg|ico|tga)$/i;
        const SUBTITLE_EXTENSIONS = /\.(srt|vtt|ass|ssa|sub)$/i;

        const classifyFile = (path) => {
            if (AUDIO_EXTENSIONS.test(path)) return 'audio';
            if (VIDEO_EXTENSIONS.test(path)) return 'video';
            if (IMAGE_EXTENSIONS.test(path)) return 'image';
            if (SUBTITLE_EXTENSIONS.test(path)) return 'subtitle';
            return 'unknown';
        };

        const filesToImport = [];
        let hasAudio = false;
        let hasVideo = false;
        let hasImage = false;

        if (filePackage.video) {
            const type = classifyFile(filePackage.video);
            console.log("filePackage.video clasificado como:", type, filePackage.video);

            if (type === 'audio') {
                hasAudio = true;
                filesToImport.push(filePackage.video);
            } else if (type === 'video') {
                hasVideo = true;
                filesToImport.push(filePackage.video);
            } else if (type === 'image') {
                hasImage = true;
                filesToImport.push(filePackage.video);
            }
        }

        if (filePackage.thumbnail) {
            const type = classifyFile(filePackage.thumbnail);
            console.log("filePackage.thumbnail clasificado como:", type, filePackage.thumbnail);

            if (type !== 'subtitle') {
                filesToImport.push(filePackage.thumbnail);
                if (type === 'image') hasImage = true;
            }
        }

        if (filePackage.subtitle) {
            const type = classifyFile(filePackage.subtitle);
            console.log("filePackage.subtitle clasificado como:", type, filePackage.subtitle);

            if (type === 'subtitle') {
                filesToImport.push(filePackage.subtitle);
            }
        }

        console.log("Clasificación final - Audio:", hasAudio, "Video:", hasVideo, "Image:", hasImage);

        // Deduplicar array para evitar importar el mismo archivo dos veces si el video y la miniatura son el mismo
        const uniqueFilesToImport = [...new Set(filesToImport)];
        filesToImport.length = 0;
        filesToImport.push(...uniqueFilesToImport);

        console.log("Archivos a importar:", filesToImport);

        if (filesToImport.length === 0) {
            console.error("ERROR: filesToImport está vacío");
            console.error("filePackage.video:", filePackage.video);
            console.error("filePackage.thumbnail:", filePackage.thumbnail);
            console.error("filePackage.subtitle:", filePackage.subtitle);
            console.error("filePackage completo:", JSON.stringify(filePackage));
            showMessage("Error: DowP no envió ningún archivo. Verifica que la descarga fue exitosa.", 'error', true, 5000);
            return;
        }

        showMessage(`Importando ${filesToImport.length} archivo(s)...`, 'info', true);

        const escapeForExtendScript = (str) => {
            return str
                .replace(/\\/g, '\\\\')
                .replace(/"/g, '\\"')
                .replace(/'/g, "\\'");
        };

        const fileListJSON = JSON.stringify(filesToImport);
        const escapedJSON = escapeForExtendScript(fileListJSON);

        const shouldAddToTimeline = addToTimelineCheckbox.checked;
        const shouldImportImages = importImagesCheckbox.checked;

        const escapedBinName = targetBinName ? `"${escapeForExtendScript(targetBinName)}"` : "null";

        if (shouldAddToTimeline) {
            csInterface.evalScript('getActiveTimelineInfo()', (result) => {
                try {
                    const timelineInfo = JSON.parse(result);
                    if (timelineInfo.hasActiveTimeline) {
                        console.log("Timeline activa encontrada. Playhead:", timelineInfo.playheadTime);
                        runImportScript(
                            `importFiles("${escapedJSON}", true, ${timelineInfo.playheadTime}, ${shouldImportImages}, ${escapedBinName})`,
                            (importResult) => {
                                console.log("Resultado de importación:", importResult);
                                handleImportResult(importResult);
                            }
                        );
                    } else {
                        showMessage("Error: No hay secuencia/composición activa.", 'error', true, 5000);
                        console.error("No timeline activa");
                    }
                } catch (e) {
                    showMessage(`Error al procesar timeline: ${e.message}`, 'error', true, 5000);
                    console.error("Error procesando timeline:", e);
                }
            });
        } else {
            console.log("Importando sin timeline, archivo(s):", filesToImport);
            runImportScript(
                `importFiles("${escapedJSON}", false, 0, ${shouldImportImages}, ${escapedBinName})`,
                (importResult) => {
                    console.log("Resultado de importación (sin timeline):", importResult);
                    handleImportResult(importResult);
                }
            );
        }
    }

    function importSubclipsToProject(filePath, subclips) {
        showMessage(`Importando ${subclips.length} subclip(s)...`, 'info', true);

        const escapeForExtendScript = (str) => {
            return str
                .replace(/\\/g, '\\\\')
                .replace(/"/g, '\\"')
                .replace(/'/g, "\\'");
        };

        const escapedFilePath = escapeForExtendScript(filePath);
        const subclipsJSON = JSON.stringify(subclips);
        const escapedJSON = escapeForExtendScript(subclipsJSON);

        const shouldAddToTimeline = addToTimelineCheckbox.checked;

        if (shouldAddToTimeline) {
            csInterface.evalScript('getActiveTimelineInfo()', (result) => {
                try {
                    const timelineInfo = JSON.parse(result);
                    const playhead = (timelineInfo && timelineInfo.hasActiveTimeline) ? timelineInfo.playheadTime : 0;
                    const playheadTicks = (timelineInfo && timelineInfo.hasActiveTimeline) ? timelineInfo.playheadTicks : "0";
                    runImportScript(
                        `importSubclips("${escapedFilePath}", "${escapedJSON}", true, ${playhead}, "${playheadTicks}")`,
                        (importResult) => {
                            console.log("Resultado de importación de subclips:", importResult);
                            sendLogToDowP(`Resultado subclips (con timeline): ${importResult}`, importResult === 'success' ? 'info' : 'error');
                            handleImportResult(importResult);
                        }
                    );
                } catch (e) {
                    runImportScript(
                        `importSubclips("${escapedFilePath}", "${escapedJSON}", false, 0, "0")`,
                        (importResult) => handleImportResult(importResult)
                    );
                }
            });
        } else {
            runImportScript(
                `importSubclips("${escapedFilePath}", "${escapedJSON}", false, 0, "0")`,
                (importResult) => {
                    console.log("Resultado de importación de subclips (sin timeline):", importResult);
                    sendLogToDowP(`Resultado subclips (sin timeline): ${importResult}`, importResult === 'success' ? 'info' : 'error');
                    handleImportResult(importResult);
                }
            );
        }
    }

    function handleImportResult(result) {
        if (result === "success") {
            showMessage("¡Importado con éxito!", 'success', true, 3000);
        } else {
            showMessage(`Error al importar: ${result}`, 'error', true, 6000);
        }
    }

    function importBatchToProject(fileList, targetBinName) {
        const host = thisAppIdentifier;

        // Flatten fileList (array of filePackage objects) into an array of string paths
        const filesToImport = [];
        if (Array.isArray(fileList)) {
            fileList.forEach(filePackage => {
                if (typeof filePackage === 'string') {
                    // Backwards compatibility if it's already a string
                    filesToImport.push(filePackage);
                } else if (filePackage) {
                    if (filePackage.video) filesToImport.push(filePackage.video);
                    if (filePackage.thumbnail) filesToImport.push(filePackage.thumbnail);
                    if (filePackage.subtitle) filesToImport.push(filePackage.subtitle);
                }
            });
        }

        const uniqueFilesToImport = [...new Set(filesToImport)];
        const totalFiles = uniqueFilesToImport.length;

        const escapeForExtendScript = (str) => {
            return str
                .replace(/\\/g, '\\\\')
                .replace(/"/g, '\\"')
                .replace(/'/g, "\\'");
        };

        const escapedBinName = targetBinName ? `"${escapeForExtendScript(targetBinName)}"` : "null";
        const shouldAddToTimeline = addToTimelineCheckbox.checked;
        const shouldImportImages = importImagesCheckbox.checked;

        const executeBatchImport = (playheadTime) => {
            if (host === 'premiere') {
                showMessage(`Importando ${totalFiles} archivo(s) a Premiere...`, 'info', true);

                const fileListJSON = JSON.stringify(uniqueFilesToImport);
                const escapedJSON = escapeForExtendScript(fileListJSON);

                console.log("Importando lote a Premiere:", uniqueFilesToImport);

                runImportScript(
                    `importFiles("${escapedJSON}", ${shouldAddToTimeline}, ${playheadTime}, ${shouldImportImages}, ${escapedBinName})`,
                    (importResult) => {
                        console.log("Resultado de importación (lote Premiere):", importResult);
                        handleImportResult(importResult);
                    }
                );

            } else if (host === 'aftereffects' || host === 'photoshop') {
                // Photoshop, como AE, no tiene una llamada de lote: se importa de a una,
                // con una pausa entre archivos para no encolar acciones sobre un host que
                // todavia esta abriendo/colocando la anterior.
                console.log(`Importando lote a ${host} (uno por uno)...`);
                let importedCount = 0;
                let errorCount = 0;

                function importNext(index) {
                    if (index >= totalFiles) {
                        let finalMessage = `¡Importación a AE completada! (${importedCount} archivos)`;
                        if (errorCount > 0) {
                            finalMessage = `Importación a AE completada (${importedCount} archivos, ${errorCount} errores)`;
                        }
                        showMessage(finalMessage.replace('AE', host === 'photoshop' ? 'Photoshop' : 'AE'),
                                    errorCount > 0 ? 'warning' : 'success', true, 3000);
                        return;
                    }

                    const fileToImport = uniqueFilesToImport[index];
                    const fileListJSON = JSON.stringify([fileToImport]);
                    const escapedJSON = escapeForExtendScript(fileListJSON);

                    showMessage(`Importando ${index + 1} de ${totalFiles} a ${host === 'photoshop' ? 'Photoshop' : 'AE'}...`, 'info', true);

                    runImportScript(
                        `importFiles("${escapedJSON}", ${shouldAddToTimeline}, ${playheadTime}, ${shouldImportImages}, ${escapedBinName})`,
                        (importResult) => {
                            if (importResult === "success") {
                                importedCount++;
                            } else {
                                errorCount++;
                                console.warn(`Error al importar ${fileToImport}: ${importResult}`);
                            }

                            setTimeout(() => importNext(index + 1), 500);
                        }
                    );
                }

                importNext(0);
            } else {
                console.error(`Host desconocido '${host}', no se puede importar el lote.`);
            }
        }; // Fin de executeBatchImport

        if (shouldAddToTimeline) {
            csInterface.evalScript('getActiveTimelineInfo()', (result) => {
                try {
                    const timelineInfo = JSON.parse(result);
                    if (timelineInfo.hasActiveTimeline) {
                        console.log("Timeline activa encontrada (Batch). Playhead:", timelineInfo.playheadTime);
                        executeBatchImport(timelineInfo.playheadTime);
                    } else {
                        showMessage("Error: No hay secuencia/composición activa.", 'error', true, 5000);
                        console.error("No timeline activa");
                    }
                } catch (e) {
                    showMessage(`Error al procesar timeline: ${e.message}`, 'error', true, 5000);
                    console.error("Error procesando timeline:", e);
                }
            });
        } else {
            executeBatchImport(0);
        }
    }

    async function setDowPPath() {
        clearUpdateNotice();
        showMessage(`Selecciona ${DowPPlatform.targetLabel()}`, 'info', true);
        csInterface.evalScript('selectDowPExecutable()', async (result) => {
            if (result && result !== "cancel") {
                // En macOS el usuario puede acabar senalando el binario interno
                // del bundle; normalizeTarget lo repliega al .app.
                result = DowPPlatform.normalizeTarget(result);

                if (!DowPPlatform.pathExists(result)) {
                    showMessage(`No se encontro ${DowPPlatform.targetLabel()} en esa ruta.`, 'error', true, 5000);
                    return;
                }

                const saved = await storage.setDowpPath(result);
                if (saved) {
                    showMessage(`Ruta guardada correctamente.`, 'success', true, 3000);
                    btnLaunch.classList.remove('is-disabled');
                    btnLink.classList.remove('is-disabled');
                    setState('disconnected');
                    connectToServer();
                } else {
                    showMessage(`Error al guardar la configuración.`, 'error', true, 5000);
                }
            } else {
                showMessage("Configuración cancelada.", 'warning', true, 3000);
            }
        });
    }

    async function launchDowP() {
        clearUpdateNotice();
        const path = await storage.getDowpPath();
        if (!path) {
            showMessage("Primero configura la ruta de DowP con el icono ⚙️.", 'error', true, 5000);
            return;
        }

        // ✅ NUEVO: Al lanzar DowP, resetear los contadores de reintento
        connectionState.attemptCount = 0;
        connectionState.isLaunching = true;
        setState('launching');

        // El lanzamiento vive en la capa CEP (Node / cep.process), no en
        // ExtendScript: es el unico camino que existe en macOS, y de paso
        // evita el .bat temporal en Windows.
        DowPPlatform.launch(path, thisAppIdentifier, csInterface, (ok, detail) => {
            if (ok) {
                console.log(`[DowP] Lanzado via ${detail}`);
                return;
            }

            console.error(`[DowP] No se pudo lanzar: ${detail}`);
            connectionState.isLaunching = false;
            resetConnectionState();
            setState('disconnected');
            setLaunchButtonState('closed');
            showMessage(`No se pudo abrir DowP (${detail}). Revisa la ruta con la rueda dentada.`, 'error', true, 8000);
        });

        setTimeout(() => {
            if (connectionState.isLaunching) {
                connectToServer(true);
            }
        }, 2000);

        setTimeout(() => {
            if (connectionState.isLaunching) {
                connectionState.isLaunching = false;
                showMessage("Timeout al iniciar DowP. Verifica que la ruta sea correcta.", 'error', true, 8000);
                setState('disconnected');
                resetConnectionState();
            }
        }, 30000);
    }

    function beginImportGuard() {
        importGuardCount++;
        clearTimeout(importGuardTimeout);
        // Salvavidas: si algun callback de importacion nunca vuelve, el panel no puede
        // quedarse sin comprobar la linea de tiempo para siempre.
        importGuardTimeout = setTimeout(() => { importGuardCount = 0; }, 180000);
    }

    function endImportGuard() {
        importGuardCount = Math.max(0, importGuardCount - 1);
        if (importGuardCount > 0) return;
        clearTimeout(importGuardTimeout);
        importGuardTimeout = null;
        // Terminada la importacion, resincronizar ya, saltando el acelerador.
        lastTimelineCheck = 0;
        checkActiveTimeline();
    }

    function noteTimelineCheckFailure() {
        // Un fallo transitorio (host ocupado, respuesta lenta o ilegible) se tolera igual
        // que una respuesta negativa suelta. Antes, el vencimiento por tiempo apagaba el
        // estado a la primera, saltandose justo esta tolerancia.
        if (lastSuccessfulTimelineCheck && timelineCheckFailureCount < 5) {
            timelineCheckFailureCount++;
            return;
        }
        timelineCheckFailureCount = 0;
        lastSuccessfulTimelineCheck = null;
        updateTimelineState(false);
    }

    function checkActiveTimeline() {
        // Mientras una importacion corre, el motor de ExtendScript esta ocupado y no puede
        // contestar: la comprobacion venceria por tiempo y apagaria la casilla justo en el
        // instante de importar, que es el sintoma que se veia en Premiere y en AE.
        if (importGuardCount > 0) return;

        const now = Date.now();

        if (now - lastTimelineCheck < TIMELINE_CHECK_INTERVAL) {
            return;
        }
        lastTimelineCheck = now;

        if (checkingTimeline) return;

        checkingTimeline = true;
        const callId = ++timelineCallSeq;
        currentTimelineCall = callId;

        // Vencimiento blando: decide el estado CON tolerancia, pero no da por perdida la
        // llamada -- la respuesta real puede llegar despues y es la que manda.
        const softTimeout = setTimeout(() => {
            if (currentTimelineCall === callId) {
                noteTimelineCheckFailure();
            }
        }, 1000);

        // Vencimiento duro: solo para no quedar bloqueado si el host no responde nunca.
        const hardTimeout = setTimeout(() => {
            if (currentTimelineCall === callId) {
                checkingTimeline = false;
            }
        }, 15000);

        csInterface.evalScript('getActiveTimelineInfo()', (result) => {
            clearTimeout(softTimeout);
            clearTimeout(hardTimeout);

            if (currentTimelineCall !== callId) return; // respuesta de una llamada vieja
            checkingTimeline = false;

            try {
                const info = JSON.parse(result);

                if (info.hasActiveTimeline) {
                    lastSuccessfulTimelineCheck = info;
                    timelineCheckFailureCount = 0;
                    updateTimelineState(true, info);
                } else {
                    noteTimelineCheckFailure();
                }
            } catch (e) {
                noteTimelineCheckFailure();
            }
        });
    }

    // Photoshop no tiene linea de tiempo: la misma casilla pasa a significar "colocar en
    // el documento activo" (y si no hay documento, cada imagen se abre como documento
    // nuevo). La de "importar imagenes a la linea de tiempo" no tiene sentido ahi.
    function isPhotoshopHost() {
        return thisAppIdentifier === 'photoshop';
    }

    function timelineLabels(hasTarget, targetName) {
        if (isPhotoshopHost()) {
            return hasTarget
                ? (targetName ? `Colocar en: ${targetName}` : 'Colocar en el documento activo')
                : 'No hay ningún documento abierto (se abrirá uno nuevo)';
        }
        return hasTarget
            ? (targetName ? `Añadir a: ${targetName}` : 'Añadir a la línea de tiempo activa')
            : 'No hay una secuencia/composición activa';
    }

    function applyHostUiMode() {
        if (isPhotoshopHost() && importImagesContainer) {
            importImagesContainer.style.display = 'none';
        }
    }

    function unpersistPhotoshop() {
        // Contrario de makePhotoshopPersistent: devuelve la extension a su ciclo de vida
        // normal para que Photoshop pueda descargarla.
        if (!isPhotoshopHost()) return;
        try {
            const event = new CSEvent('com.adobe.PhotoshopUnPersistent', 'APPLICATION');
            event.extensionId = 'com.dowp.importer';
            csInterface.dispatchEvent(event);
            console.log('[DowP] Persistencia retirada en Photoshop.');
        } catch (e) {
            console.error('[DowP] No se pudo retirar la persistencia:', e);
        }
    }

    function releaseOnPanelClose() {
        // CERRAR el panel debe desconectar, como en Premiere y After Effects; MINIMIZARLO
        // no. Al cerrarlo, el host descarga la pagina y esto se dispara: se retira la
        // persistencia y se cierra el socket a proposito, para que DowP se entere en el
        // acto en vez de esperar a que caduque la conexion. Al minimizar no hay descarga,
        // asi que no pasa por aqui y la conexion sigue viva.
        if (panelReleased) return;
        panelReleased = true;
        unpersistPhotoshop();
        try {
            if (socket && socket.connected) {
                socket.emit('clear_active_target');
                socket.disconnect();
            }
        } catch (e) {}
    }

    function makePhotoshopPersistent() {
        // Photoshop DESCARGA la extension en cuanto su panel deja de estar visible
        // (minimizado, contraido o en una pestana de fondo): el contexto JS muere, el
        // socket se cae y DowP deja de ver a Photoshop como cliente, asi que tampoco se
        // puede vincular desde DowP. Premiere y After Effects no hacen esto, por eso solo
        // se notaba en Photoshop.
        //
        // La solucion oficial es declarar la extension como persistente: mientras lo
        // este, Photoshop la mantiene cargada aunque el panel no se vea. Es especifico de
        // Photoshop; en los otros hosts este evento no existe y no pasa nada.
        if (!isPhotoshopHost()) return;
        try {
            const event = new CSEvent('com.adobe.PhotoshopPersistent', 'APPLICATION');
            event.extensionId = 'com.dowp.importer';
            csInterface.dispatchEvent(event);
            console.log('[DowP] Extension declarada persistente en Photoshop.');
        } catch (e) {
            console.error('[DowP] No se pudo hacer persistente la extension:', e);
        }
    }

    function updateTimelineState(hasActiveTimeline, info) {
        const timelineName = (info && info.timelineName) ? info.timelineName : '';

        if (lastTimelineState !== hasActiveTimeline) {
            lastTimelineState = hasActiveTimeline;
            addToTimelineCheckbox.disabled = !hasActiveTimeline;

            // La casilla refleja "hay linea de tiempo Y el usuario la quiere". Al volver
            // la linea de tiempo se restaura sola la eleccion del usuario, en vez de
            // quedar habilitada pero apagada como pasaba antes.
            const shouldBeChecked = hasActiveTimeline && userWantsTimeline;
            if (addToTimelineCheckbox.checked !== shouldBeChecked) {
                suppressIntentUpdate = true;
                addToTimelineCheckbox.checked = shouldBeChecked;
                addToTimelineCheckbox.dispatchEvent(new Event('change'));
                suppressIntentUpdate = false;
            }
        }

        addToTimelineContainer.title = timelineLabels(hasActiveTimeline, timelineName);

        setTimelineActiveState(hasActiveTimeline, { strong: addToTimelineCheckbox.checked });
    }

    function reportPanelVisibility(source, eventData) {
        if (!isPhotoshopHost()) return;
        let windowVisible = 'n/d';
        try { windowVisible = String(csInterface.isWindowVisible()); } catch (e) {}
        sendLogToDowP(
            `Panel: ${source}=${eventData} | isWindowVisible=${windowVisible} | ` +
            `hidden=${document.hidden} | tamaño=${window.innerWidth}x${window.innerHeight}`,
            'info'
        );
    }

    function refreshTimelineNow() {
        lastTimelineCheck = 0;   // el host acaba de avisar: saltar el acelerador
        checkActiveTimeline();
    }

    function setupEventListeners() {
        // Premiere avisa cuando cambia la secuencia activa, asi que el estado se refresca
        // al instante en vez de esperar al siguiente sondeo. Es aditivo: si algun
        // identificador no existe en esta version del host, ese listener nunca se dispara
        // y el sondeo sigue cubriendo el caso.
        const HOST_TIMELINE_EVENTS = [
            'com.dowp.sequenceChanged',
            'com.adobe.PremierePro.event.ActiveSequenceChanged',
            'com.adobe.PremierePro.event.SequenceActivated',
            'com.adobe.PremierePro.event.SequenceSelectionChanged'
        ];
        HOST_TIMELINE_EVENTS.forEach((eventType) => {
            try {
                csInterface.addEventListener(eventType, () => {
                    refreshTimelineNow();
                });
            } catch (e) {}
        });

        if (thisAppIdentifier === 'premiere') {
            // Registra el enlace del lado de ExtendScript que emite 'com.dowp.sequenceChanged'.
            try {
                csInterface.evalScript('bindSequenceEvents()', (res) => {
                    console.log('[DowP] bindSequenceEvents ->', res);
                });
            } catch (e) {}
        }

        window.addEventListener('beforeunload', releaseOnPanelClose);
        window.addEventListener('unload', releaseOnPanelClose);

        // Diagnostico de visibilidad: CEP no ofrece ninguna forma de distinguir "panel
        // cerrado" de "panel minimizado/en pestana de fondo", asi que se dejan anotados en
        // el log de DowP los valores que SI podrian distinguirlos. Si algun dia cerrar no
        // desconectara (porque el host no descargue la pagina), estos numeros dicen que
        // criterio usar sin tener que adivinar.
        csInterface.addEventListener('com.adobe.csxs.events.WindowVisibilityChanged', (ev) => {
            reportPanelVisibility('WindowVisibilityChanged', ev && ev.data);
        });

        window.addEventListener('focus', () => {
            checkActiveTimeline();
        });

        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) {
                checkActiveTimeline();
                // Si el host suspendio el panel mientras estaba oculto, la conexion pudo
                // caerse sin que nadie lo notara: al volver, se reintenta.
                if (!socket || !socket.connected) {
                    connectToServer();
                }
            }
        });

        addToTimelineCheckbox.addEventListener('click', () => {
            checkActiveTimeline();
        });
    }

    addToTimelineCheckbox.addEventListener('change', () => {
        const isChecked = addToTimelineCheckbox.checked;

        // Solo cuenta como intencion del usuario si el cambio NO lo hizo el panel al
        // sincronizar con el estado del host (ver updateTimelineState).
        if (!suppressIntentUpdate) {
            userWantsTimeline = isChecked;
        }

        importImagesCheckbox.disabled = !isChecked;

        if (isChecked) {
            addToTimelineContainer.classList.add('is-active');
            importImagesContainer.classList.remove('is-disabled');
            // Devolver tambien la eleccion de "importar imagenes", que se apagaba en
            // cascada al perderse la linea de tiempo.
            if (importImagesCheckbox.checked !== userWantsImages) {
                const previousSuppress = suppressIntentUpdate;
                suppressIntentUpdate = true;
                importImagesCheckbox.checked = userWantsImages;
                importImagesCheckbox.dispatchEvent(new Event('change'));
                suppressIntentUpdate = previousSuppress;
            }
        } else {
            addToTimelineContainer.classList.remove('is-active');
            importImagesContainer.classList.add('is-disabled');
            if (importImagesCheckbox.checked) {
                importImagesCheckbox.checked = false;
                importImagesCheckbox.dispatchEvent(new Event('change'));
            }
        }
        setTimelineActiveState(lastTimelineState, { strong: isChecked });
    });

    importImagesCheckbox.addEventListener('change', () => {
        if (!suppressIntentUpdate) {
            userWantsImages = importImagesCheckbox.checked;
        }
        if (importImagesCheckbox.checked) {
            importImagesContainer.classList.add('is-active');
        } else {
            importImagesContainer.classList.remove('is-active');
        }
    });

    // ── Aviso de desfase de version ──
    // El panel y DowP comparten numero de version: el panel se instala DESDE la app,
    // viaja dentro de su bundle y no tiene canal de actualizacion propio. Por eso aqui
    // ya no se consulta ningun servidor: la version de la app llega por el socket en el
    // evento 'dowp_version', respuesta al 'register'. Si no coinciden es que quedo una
    // instalacion vieja del panel, y se arregla desde la propia app.
    //
    // Reutiliza isUpdateNoticeActive/updateNoticeTimeout, el mecanismo de aviso fijo que
    // hace que updateStatusMessage() no sobrescriba el mensaje mientras esta visible.
    function showVersionMismatchNotice(appVersion) {
        const logArea = document.getElementById('log-text');
        if (!logArea) return;

        if (updateNoticeTimeout) {
            clearTimeout(updateNoticeTimeout);
        }
        isUpdateNoticeActive = true;

        logArea.innerHTML =
            `⚠ Panel v${CURRENT_EXTENSION_VERSION} · DowP v${appVersion}. ` +
            `Reinstala el panel desde Ajustes &gt; Integraciones.`;

        updateNoticeTimeout = setTimeout(() => {
            if (isUpdateNoticeActive) {
                clearUpdateNotice();
            }
        }, 20000);
    }

    function sendSelectionToDowP() {
        if (!socket || !socket.connected) {
            showMessage("Error: No hay conexión con DowP.", 'error', true, 3000);
            return;
        }

        showMessage("Buscando archivos seleccionados...", 'info');

        csInterface.evalScript('getSelectionForDowP()', (result) => {
            try {
                const parsed = JSON.parse(result);
                const items = parsed.items || [];
                const skipped = parsed.skipped || [];

                if (items.length === 0) {
                    if (skipped.length > 0) {
                        // No se manda nada, pero el usuario tenia algo seleccionado: hay
                        // que decirle POR QUE, en vez de un "nada seleccionado" enganoso.
                        showMessage(`No se pudo enviar nada: ${skipped.join(' | ')}`, 'warning', true, 8000);
                        sendLogToDowP(`Seleccion descartada: ${skipped.join(' | ')}`, 'warning');
                    } else {
                        showMessage("⚠️ Nada seleccionado en Timeline o Proyecto.", 'warning', true, 3000);
                    }
                    return;
                }

                socket.emit('adobe_push_files', {
                    items: items,
                    skipped: skipped,
                    // Compatibilidad: solo las rutas, para cualquier consumidor viejo.
                    files: items.map((it) => it.path)
                });

                const trimmed = items.filter((it) => it.hasTrim).length;
                let msg = `🚀 Enviados ${items.length} elemento(s)`;
                if (trimmed > 0) msg += ` (${trimmed} con corte)`;
                if (skipped.length > 0) msg += `. Sin enviar: ${skipped.join(' | ')}`;
                showMessage(msg, skipped.length > 0 ? 'warning' : 'success', true, skipped.length > 0 ? 8000 : 4000);

                if (skipped.length > 0) {
                    sendLogToDowP(`Elementos no enviados: ${skipped.join(' | ')}`, 'warning');
                }
            } catch (e) {
                console.error("Error al parsear la seleccion:", e, result);
                showMessage("Error al leer selección: " + e.message, 'error', true, 4000);
            }
        });
    }

    // Autodeteccion de DowP. Se prueba primero desde la capa CEP porque ahi
    // se puede comprobar la existencia de un bundle .app (un directorio),
    // cosa que File.exists de ExtendScript nunca resuelve en macOS.
    function autoDetectDowP() {
        return new Promise((resolve) => {
            const candidates = DowPPlatform.defaultCandidates();
            for (let i = 0; i < candidates.length; i++) {
                if (DowPPlatform.pathExists(candidates[i])) {
                    resolve(candidates[i]);
                    return;
                }
            }

            // Sin Node no hay variables de entorno, asi que la lista puede
            // venir vacia: ahi ExtendScript si sabe resolver Folder.userData.
            csInterface.evalScript('findDowPExecutable()', (detected) => {
                if (detected && detected !== 'not_found' && detected.indexOf('error') !== 0) {
                    resolve(DowPPlatform.normalizeTarget(detected));
                } else {
                    resolve(null);
                }
            });
        });
    }

    async function initializeApp() {
        isUpdateNoticeActive = false;
        csInterface.evalScript('getHostAppName()', async (result) => {
            if (result && result !== "unknown") {
                thisAppName = result.replace("Adobe ", "");
                thisAppIdentifier = thisAppName.toLowerCase().replace(" pro", "").replace(" ", "");
            }

            // Diagnostico de arranque: deja constancia de que mecanismo de
            // lanzamiento hay disponible (critico al depurar en macOS).
            applyHostUiMode();
            makePhotoshopPersistent();

            const launcher = DowPPlatform.hasNode()
                ? 'node'
                : ((window.cep && window.cep.process) ? 'cep.process' : 'extendscript');
            console.log(`[DowP] SO: ${navigator.platform} | host: ${thisAppIdentifier} | lanzador: ${launcher}`);

            checkActiveTimeline();
            setupEventListeners();

            let dowpPath = await storage.getDowpPath();

            if (!dowpPath) {
                const detectedPath = await autoDetectDowP();
                if (detectedPath) {
                    dowpPath = detectedPath;
                    const saved = await storage.setDowpPath(dowpPath);
                    if (saved) {
                        showMessage("✓ DowP detectado automaticamente", 'success', true, 3000);
                        setState('disconnected');
                        setLinkButtonState('disconnected');
                        connectToServer();
                    }
                } else {
                    setState('unconfigured');
                    setLinkButtonState('disconnected');
                    btnLaunch.classList.add('is-disabled');
                    btnLink.classList.add('is-disabled');
                }
            } else {
                setState('disconnected');
                setLinkButtonState('disconnected');
                connectToServer();
            }

            setTimelineActiveState(Boolean(lastTimelineState), { strong: Boolean(addToTimelineCheckbox.checked) });

            // ✅ CRÍTICO: Intervalo de mantenimiento MÁS CONSERVADOR
            setInterval(() => {
                // ✅ BLOQUEADO: No reconectar automáticamente si ya fallamos 3 veces
                if (!socket || !socket.connected) {
                    // NO hacer nada automáticamente, solo actualizar UI
                    if (!connectionState.isLaunching) {
                        setState('dowp-closed');
                        setLinkButtonState('disconnected');
                        setLaunchButtonState('closed');
                    }
                } else {
                    socket.emit('get_active_target');

                    if (connectionState.attemptCount > 0) {
                        connectionState.attemptCount = 0;
                    }
                }

                if (!checkingTimeline) {
                    checkActiveTimeline();
                }
            }, 1000);
        });
    }

    btnLink.onclick = linkToThisApp;
    btnLaunch.onclick = launchDowP;
    btnSettings.onclick = setDowPPath;
    btnSendToDowp.onclick = sendSelectionToDowP;
    initializeApp();
};

// Agregar después de initializeApp() al final del archivo, TEMPORALMENTE
window.debugSelection = function () {
    csInterface.evalScript('debugProjectSelection()', (result) => {
        console.log("=== DIAGNÓSTICO COMPLETO ===");
        console.log(result);
        alert("Revisa la consola del navegador (F12)");
    });
};