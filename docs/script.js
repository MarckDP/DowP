document.addEventListener('DOMContentLoaded', async () => {
    const btnText = document.getElementById('btn-text');
    const mainBtn = document.getElementById('main-download-btn');

    // Configura la versión actual de la app aquí
    const VERSION = "1.9.0";
    const REPO_URL = "https://github.com/MarckDP/DowP/releases/download/v" + VERSION;

    const urlWindows = `${REPO_URL}/DowP_Setup_${VERSION}.exe`;
    const urlMacSilicon = `${REPO_URL}/DowP-${VERSION}-arm64.dmg`;
    const urlMacIntel = `${REPO_URL}/DowP-${VERSION}-x64.dmg`;

    // Asignar URLs a las tarjetas
    document.getElementById('link-win').href = urlWindows;
    document.getElementById('link-mac-silicon').href = urlMacSilicon;
    document.getElementById('link-mac-intel').href = urlMacIntel;

    // Detección de OS
    let osName = "Unknown";
    const userAgent = window.navigator.userAgent;
    const platform = window.navigator.platform || "";
    const macosPlatforms = ['Macintosh', 'MacIntel', 'MacPPC', 'Mac68K'];
    const windowsPlatforms = ['Win32', 'Win64', 'Windows', 'WinCE'];

    if (macosPlatforms.indexOf(platform) !== -1 || userAgent.includes("Mac")) {
        osName = 'Mac';
    } else if (windowsPlatforms.indexOf(platform) !== -1 || userAgent.includes("Win")) {
        osName = 'Windows';
    }

    // Detección de arquitectura para Mac
    let isAppleSilicon = false;

    if (osName === 'Mac') {
        // Truco 1: UserAgentData API (Chromium-based)
        if (navigator.userAgentData && navigator.userAgentData.getHighEntropyValues) {
            try {
                const ua = await navigator.userAgentData.getHighEntropyValues(["architecture"]);
                if (ua.architecture === 'arm') {
                    isAppleSilicon = true;
                }
            } catch (e) { }
        }

        // Truco 2: WebGL Renderer (Safari, Firefox y fallback)
        if (!isAppleSilicon) {
            try {
                const canvas = document.createElement('canvas');
                const gl = canvas.getContext('webgl');
                if (gl) {
                    const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
                    if (debugInfo) {
                        const renderer = gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL);
                        // Los procesadores de Apple Silicon tienen "Apple M" en el renderer (ej: Apple M1)
                        if (renderer && renderer.match(/Apple M/i)) {
                            isAppleSilicon = true;
                        }
                    }
                }
            } catch (e) { }
        }
    }

    // Configurar botón principal
    if (osName === 'Windows') {
        btnText.textContent = 'Descargar para Windows';
        mainBtn.href = urlWindows;
    } else if (osName === 'Mac') {
        if (isAppleSilicon) {
            btnText.textContent = 'Descargar para macOS (Apple Silicon)';
            mainBtn.href = urlMacSilicon;
        } else {
            btnText.textContent = 'Descargar para macOS (Intel)';
            mainBtn.href = urlMacIntel;
        }
    } else {
        // Fallback genérico para Linux o desconocidos
        btnText.textContent = 'Descargar DowP (Windows)';
        mainBtn.href = urlWindows;
    }
});
