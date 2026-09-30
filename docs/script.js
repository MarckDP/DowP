// ── Internacionalización (i18n) ───────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    let lang = localStorage.getItem('dowp_lang');
    if (!lang) {
        const navLang = navigator.language.slice(0, 2);
        lang = (navLang === 'es' || navLang === 'pt') ? navLang : 'en'; // Default a inglés
        localStorage.setItem('dowp_lang', lang);
    }
    setLanguage(lang);

    document.querySelectorAll('[data-lang]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            const selectedLang = btn.getAttribute('data-lang');
            localStorage.setItem('dowp_lang', selectedLang);
            setLanguage(selectedLang);
        });
    });
});

function setLanguage(lang) {
    document.documentElement.lang = lang;
    
    document.querySelectorAll('[data-lang]').forEach(btn => {
        if (btn.getAttribute('data-lang') === lang) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });

    if (lang === 'es' || typeof translations === 'undefined' || !translations[lang]) {
        if (lang === 'es' && document.body.dataset.currentLang !== 'es') {
            if (document.body.dataset.currentLang) window.location.reload();
            document.body.dataset.currentLang = 'es';
        }
        return;
    }

    document.body.dataset.currentLang = lang;
    const dict = translations[lang];

    document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.getAttribute('data-i18n');
        if (dict[key]) {
            el.innerHTML = dict[key];
        }
    });

    document.querySelectorAll('[data-i18n-caption]').forEach(el => {
        const key = el.getAttribute('data-i18n-caption');
        if (dict[key]) {
            el.setAttribute('data-caption', dict[key]);
        }
    });

    // Reaplicar el número de versión dinámico si ya fue obtenido
    if (window.dowpLatestVersion) {
        document.querySelectorAll('.js-version').forEach((el) => { el.textContent = window.dowpLatestVersion; });
    }
}

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

    function setDynamicBtn(key) {
        btnText.setAttribute('data-i18n', key);
        const currentLang = document.documentElement.lang || 'es';
        if (translations[currentLang] && translations[currentLang][key]) {
            btnText.innerHTML = translations[currentLang][key];
        }
    }

    setDynamicBtn('dl_search');
    const releases = await releasesPromise;
    const latest = Array.isArray(releases) ? releases.find((r) => !r.draft && !r.prerelease) : null;

    const urlWindows = findAsset(latest, /\.exe$/i);
    const urlMacSilicon = findAsset(latest, /arm64\.dmg$/i);
    const urlMacIntel = findAsset(latest, /x64\.dmg$/i);

    if (latest) {
        // Número de versión en todos los textos marcados (hero, marquesina...).
        const version = String(latest.tag_name || "").replace(/^v/i, "");
        if (version) {
            window.dowpLatestVersion = version;
            document.querySelectorAll('.js-version').forEach((el) => { el.textContent = version; });
        }
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
            setDynamicBtn('dl_mac_silicon_btn');
            mainBtn.href = urlMacSilicon || RELEASES_PAGE;
        } else {
            setDynamicBtn('dl_mac_intel_btn');
            mainBtn.href = urlMacIntel;
        }
    } else if (osName === 'Windows') {
        setDynamicBtn('dl_win_btn');
        mainBtn.href = urlWindows || RELEASES_PAGE;
    } else {
        // Fallback genérico para Linux o desconocidos
        setDynamicBtn('dl_win_btn');
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

// ── Radio DowP (con fallback entre emisoras) ─────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    const audio = document.getElementById('radio-audio');
    const toggleBtn = document.getElementById('radio-toggle');
    const playIcon = document.getElementById('radio-icon');
    const playText = document.getElementById('radio-text');
    const led = document.getElementById('radio-led');
    const viz = document.getElementById('radio-viz');
    const volumeSlider = document.getElementById('radio-volume');
    const stationLabel = document.getElementById('radio-station');

    const prevBtn = document.getElementById('radio-prev');
    const nextBtn = document.getElementById('radio-next');

    if (!audio || !toggleBtn) return;

    // Lista de emisoras: si una falla, salta a la siguiente.
    const stations = [
        { name: 'SomaFM: Groove Salad',   url: 'https://ice1.somafm.com/groovesalad-128-mp3' },
        { name: 'SomaFM: Drone Zone',     url: 'https://ice1.somafm.com/dronezone-128-mp3' },
        { name: 'SomaFM: DEF CON Radio',  url: 'https://ice1.somafm.com/defcon-128-mp3' },
        { name: 'SomaFM: Space Station',  url: 'https://ice1.somafm.com/spacestation-128-mp3' },
    ];

    let currentIndex = 0;
    let isPlaying = false;
    let retryCount = 0;
    const maxRetries = stations.length;

    function setStation(index) {
        currentIndex = (index + stations.length) % stations.length;
        const st = stations[currentIndex];
        audio.src = st.url;
        if (stationLabel) stationLabel.textContent = st.name;
    }

    function setPlayingUI() {
        isPlaying = true;
        if (playIcon) playIcon.textContent = '⏸';
        if (playText) {
            playText.setAttribute('data-i18n', 'radio_pause');
            const currentLang = document.documentElement.lang || 'es';
            if (translations[currentLang] && translations[currentLang]['radio_pause']) {
                playText.textContent = translations[currentLang]['radio_pause'];
            } else {
                playText.textContent = 'Pausar';
            }
        }
        if (led) { led.classList.add('on'); led.title = 'Emisión en vivo'; }
        if (viz) viz.classList.add('playing');
    }

    function setStoppedUI(labelKey) {
        isPlaying = false;
        if (playIcon) playIcon.textContent = '▶';
        if (playText) {
            const key = labelKey || 'radio_play';
            playText.setAttribute('data-i18n', key);
            const currentLang = document.documentElement.lang || 'es';
            if (translations[currentLang] && translations[currentLang][key]) {
                playText.textContent = translations[currentLang][key];
            } else {
                playText.textContent = key === 'radio_err' ? 'Error de stream' : (key === 'radio_conn' ? 'Conectando...' : 'Play Radio');
            }
        }
        if (led) { led.classList.remove('on'); led.title = 'Emisión detenida'; }
        if (viz) viz.classList.remove('playing');
    }

    // Inicializar con la primera emisora
    setStation(0);

    if (volumeSlider) {
        audio.volume = parseFloat(volumeSlider.value) || 0.5;
        volumeSlider.addEventListener('input', (e) => {
            audio.volume = parseFloat(e.target.value);
        });
    }

    async function playCurrentStation() {
        setStoppedUI('radio_conn');
        try {
            audio.load();
            await audio.play();
            setPlayingUI();
        } catch (err) {
            tryNextStation();
        }
    }

    toggleBtn.addEventListener('click', () => {
        if (!isPlaying) {
            retryCount = 0;
            playCurrentStation();
        } else {
            audio.pause();
            setStoppedUI('radio_play');
        }
    });

    if (prevBtn) {
        prevBtn.addEventListener('click', () => {
            setStation(currentIndex - 1);
            if (isPlaying) {
                retryCount = 0;
                playCurrentStation();
            }
        });
    }

    if (nextBtn) {
        nextBtn.addEventListener('click', () => {
            setStation(currentIndex + 1);
            if (isPlaying) {
                retryCount = 0;
                playCurrentStation();
            }
        });
    }

    async function tryNextStation() {
        retryCount++;
        if (retryCount > maxRetries) {
            setStoppedUI('radio_err');
            return;
        }
        setStation(currentIndex + 1);
        setStoppedUI('radio_conn');
        try {
            audio.load();
            await audio.play();
            retryCount = 0;
            setPlayingUI();
        } catch (err) {
            tryNextStation();
        }
    }

    // Si el stream se corta mientras suena, intentar la siguiente
    audio.addEventListener('error', () => {
        if (isPlaying) {
            tryNextStation();
        } else {
            setStoppedUI('radio_err');
        }
    });

    // Si el stream se para (stall prolongado), intentar la siguiente
    let stallTimer = null;
    audio.addEventListener('stalled', () => {
        if (!isPlaying) return;
        stallTimer = setTimeout(() => {
            if (isPlaying) tryNextStation();
        }, 8000);
    });
    audio.addEventListener('playing', () => {
        if (stallTimer) { clearTimeout(stallTimer); stallTimer = null; }
    });
});
