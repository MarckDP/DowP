// ── Últimos datos de GitHub (una sola consulta para toda la página) ───────
// De la lista de releases salen: la última versión publicada (no borrador ni
// pre-release, igual que /releases/latest), sus instaladores reales y el total de
// descargas. Así no hay que tocar este archivo al publicar una versión nueva.
// Sin API (sin red o cupo de 60 consultas/hora agotado): los botones llevan a la
// página de Releases, donde siempre está todo.
const RELEASES_PAGE = "https://github.com/MarckDP/DowP/releases";
const releasesPromise = fetch("https://api.github.com/repos/MarckDP/DowP/releases?per_page=100")
    .then((res) => (res.ok ? res.json() : null))
    .catch(() => null);

function findAsset(release, pattern) {
    const asset = (release && release.assets || []).find((a) => pattern.test(a.name));
    return asset ? asset.browser_download_url : null;
}

// ── Botones de descarga ───────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    const btnText = document.getElementById('btn-text');
    const mainBtn = document.getElementById('main-download-btn');
    const linkWin = document.getElementById('link-win');
    const linkSilicon = document.getElementById('link-mac-silicon');
    const linkIntel = document.getElementById('link-mac-intel');

    // Mientras llega la respuesta (o si falla), todo lleva a Releases.
    for (const el of [mainBtn, linkWin, linkSilicon, linkIntel]) el.href = RELEASES_PAGE;

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

    btnText.textContent = 'Buscando la última versión...';
    const releases = await releasesPromise;
    const latest = Array.isArray(releases) ? releases.find((r) => !r.draft && !r.prerelease) : null;

    const urlWindows = findAsset(latest, /\.exe$/i);
    const urlMacSilicon = findAsset(latest, /arm64\.dmg$/i);
    const urlMacIntel = findAsset(latest, /x64\.dmg$/i);

    if (latest) {
        // Número de versión en todos los textos marcados (hero, marquesina...).
        const version = String(latest.tag_name || "").replace(/^v/i, "");
        if (version) document.querySelectorAll('.js-version').forEach((el) => { el.textContent = version; });
    }
    if (urlWindows) linkWin.href = urlWindows;
    if (urlMacSilicon) linkSilicon.href = urlMacSilicon;
    // La tarjeta de Mac Intel solo aparece si esa versión trae su .dmg.
    if (urlMacIntel) {
        linkIntel.href = urlMacIntel;
        linkIntel.hidden = false;
    }

    // Configurar botón principal
    if (osName === 'Mac') {
        // Sin .dmg de Intel, todo Mac recibe el de Apple Silicon (Safari no deja
        // distinguir bien el chip, y un Intel sin versión propia no tiene otra opción).
        if (isAppleSilicon || !urlMacIntel) {
            btnText.textContent = 'Descargar para macOS (Apple Silicon)';
            mainBtn.href = urlMacSilicon || RELEASES_PAGE;
        } else {
            btnText.textContent = 'Descargar para macOS (Intel)';
            mainBtn.href = urlMacIntel;
        }
    } else if (osName === 'Windows') {
        btnText.textContent = 'Descargar para Windows';
        mainBtn.href = urlWindows || RELEASES_PAGE;
    } else {
        // Fallback genérico para Linux o desconocidos
        btnText.textContent = 'Descargar DowP (Windows)';
        mainBtn.href = urlWindows || RELEASES_PAGE;
    }
});

// ── Contador de descargas (misma respuesta de GitHub) ─────────────────────
// Suma las descargas de los instaladores (.exe/.dmg) de todos los releases.
// Si la API falla o se agota el cupo, el contador se queda en "------".
document.addEventListener('DOMContentLoaded', async () => {
    const counter = document.getElementById('download-counter');
    if (!counter) return;
    const releases = await releasesPromise;
    if (!Array.isArray(releases)) return;
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
