document.addEventListener('DOMContentLoaded', async () => {
    const btnText = document.getElementById('btn-text');
    const mainBtn = document.getElementById('main-download-btn');

    // Configura la versión actual de la app aquí
    const VERSION = "1.9.1";
    const REPO_URL = "https://github.com/MarckDP/DowP/releases/download/v" + VERSION;
    // Sin build Intel por ahora: todo Mac recibe el .dmg de Apple Silicon.
    // Al volver a publicarlo, poner true y quitar el "hidden" de index.html.
    const MAC_INTEL_AVAILABLE = false;

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
        if (isAppleSilicon || !MAC_INTEL_AVAILABLE) {
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

// ── Contador de descargas (datos reales de la API de GitHub) ──────────────
// Suma las descargas de los instaladores (.exe/.dmg) de todos los releases.
// Si la API falla o se agota el cupo, el contador se queda en "------".
document.addEventListener('DOMContentLoaded', async () => {
    const counter = document.getElementById('download-counter');
    if (!counter) return;
    try {
        const res = await fetch('https://api.github.com/repos/MarckDP/DowP/releases?per_page=100');
        if (!res.ok) return;
        const releases = await res.json();
        let total = 0;
        for (const rel of releases) {
            for (const asset of rel.assets || []) {
                if (/\.(exe|dmg)$/i.test(asset.name)) total += asset.download_count;
            }
        }
        const digits = String(total).padStart(6, '0').split('');
        counter.textContent = '';
        for (const d of digits) {
            const span = document.createElement('span');
            span.textContent = d;
            counter.appendChild(span);
        }
        counter.setAttribute('aria-label', `${total} descargas`);
    } catch (e) { }
});

// ── Visor de capturas ─────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    const viewer = document.getElementById('viewer');
    if (!viewer || typeof viewer.showModal !== 'function') return;

    const img = document.getElementById('viewer-img');
    const caption = document.getElementById('viewer-caption');
    const title = document.getElementById('viewer-title');

    document.querySelectorAll('.shot').forEach((shot) => {
        shot.addEventListener('click', () => {
            img.src = shot.dataset.src;
            img.alt = shot.querySelector('img').alt;
            caption.textContent = shot.dataset.caption || '';
            title.textContent = shot.querySelector('span').textContent;
            viewer.showModal();
        });
    });

    document.getElementById('viewer-close').addEventListener('click', () => viewer.close());
    // Clic fuera de la ventana: cerrar
    viewer.addEventListener('click', (e) => { if (e.target === viewer) viewer.close(); });
});
