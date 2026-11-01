// Página de temas: galería, subida y consulta del estado.
// Todo lo que viene de un tema se escribe como texto, nunca como HTML.
(() => {
    const GALERIA = "https://marckdp.github.io/dowp-temas/";
    const WORKER = "https://dowp-temas.nody18.workers.dev/";
    const MAX_BYTES = 20 * 1024 * 1024;
    const MAX_CAPTURAS = 3;
    const MAX_CAPTURA_BYTES = 8 * 1024 * 1024;

    const lista = document.getElementById("temas-lista");
    const aviso = document.getElementById("temas-aviso");
    const salida = document.getElementById("temas-salida");
    const progreso = document.getElementById("temas-progreso");
    const progresoTexto = document.getElementById("temas-progreso-texto");
    const form = document.getElementById("temas-form");
    let temas = null;
    let filtro = "todos";

    function t(key) {
        const lang = document.documentElement.lang;
        const dict = (typeof translations !== "undefined" && translations[lang]) || translations.es;
        return dict[key] || translations.es[key] || key;
    }

    function show(element, text, kind) {
        element.textContent = text;
        element.hidden = false;
        element.dataset.tipo = kind || "";
    }

    // Los temas antiguos se guardaron como tema.dthmp: se descargan con el nombre del tema.
    function downloadName(tema) {
        if (!/^tema\./.test(tema.archivo)) return tema.archivo;
        const stem = String(tema.nombre).toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "-").replace(/^-+|-+$/g, "");
        return `${stem || "tema"}${tema.archivo.endsWith(".json") ? ".json" : ".dthmp"}`;
    }

    function card(tema) {
        const ruta = `${GALERIA}temas/${encodeURIComponent(tema.id)}/`;
        const article = document.createElement("article");
        article.className = "tema-tarjeta";
        article.tabIndex = 0;
        article.setAttribute("role", "button");
        article.addEventListener("click", () => { location.hash = `tema=${encodeURIComponent(tema.id)}`; });
        article.addEventListener("keydown", (event) => {
            if (event.key === "Enter" && event.target === article) location.hash = `tema=${encodeURIComponent(tema.id)}`;
        });
        const img = document.createElement("img");
        img.src = `${ruta}vista.jpg`;
        img.alt = "";
        img.loading = "lazy";
        img.width = 640;
        img.height = 360;
        const name = document.createElement("h3");
        name.textContent = tema.nombre;
        const details = document.createElement("p");
        details.className = "muted";
        details.textContent = `${t("temas_by")} ${tema.autor || t("temas_anonymous")} · ${sizeText(tema.bytes)}`;
        const link = document.createElement("a");
        link.className = "big-btn temas-boton";
        link.href = `${ruta}${encodeURIComponent(tema.archivo)}`;
        link.download = downloadName(tema);
        link.textContent = t("temas_download");
        link.addEventListener("click", (event) => event.stopPropagation());
        article.append(img, name, details, link);
        return article;
    }

    function renderGallery() {
        if (temas === null) return;
        const visibles = temas.filter((tema) => {
            if (filtro === "imagenes") return tema.imagenes && tema.imagenes.length > 0;
            if (filtro === "colores") return !tema.imagenes || tema.imagenes.length === 0;
            return true;
        });
        lista.replaceChildren(...visibles.map(card));
        aviso.hidden = visibles.length > 0;
        aviso.removeAttribute("data-i18n");
        aviso.textContent = t(temas.length ? "temas_empty_filter" : "temas_empty");
    }

    // ── Indicador de la última subida. Se recuerda solo en este navegador.
    const CLAVE = "dowp_tema_subido";
    const PASOS = ["recibido", "comprobado", "revision", "publicado"];
    let consulta = null;

    function lastCode(value) {
        try {
            if (value === undefined) return localStorage.getItem(CLAVE);
            if (value) localStorage.setItem(CLAVE, value);
            else localStorage.removeItem(CLAVE);
        } catch (e) {}
        return value;
    }

    function drawProgress(paso, texto, tipo) {
        const hasta = PASOS.indexOf(paso);
        progreso.querySelectorAll("li").forEach((li) => {
            const posicion = PASOS.indexOf(li.dataset.paso);
            li.classList.toggle("hecho", posicion <= hasta);
            li.classList.toggle("fallo", tipo === "error" && posicion === hasta + 1);
        });
        progresoTexto.textContent = texto;
        progresoTexto.dataset.tipo = tipo || "";
        progreso.hidden = false;
    }

    async function checkProgress(code) {
        clearTimeout(consulta);
        let data = null;
        try {
            const res = await fetch(`${WORKER}estado/${encodeURIComponent(code)}`);
            data = await res.json();
        } catch (e) {}
        if (lastCode() !== code) return;
        const estado = data && data.estado;
        if (estado === "publicado") drawProgress("publicado", t("temas_state_published"), "ok");
        else if (estado === "revision") drawProgress("revision", t("temas_state_review"));
        else if (estado === "rechazado") {
            const motivo = data.motivo ? `${t("temas_state_rejected_why")} ${data.motivo}` : t("temas_state_rejected");
            drawProgress(data.motivo ? "recibido" : "revision", motivo, "error");
        } else if (estado === "error") drawProgress("recibido", t("temas_state_error"), "error");
        else if (estado === "desconocido") { lastCode(""); progreso.hidden = true; return; }
        else drawProgress("recibido", t("temas_state_processing"));
        // Mientras se comprueba, cada 15 s; en revisión, cada minuto. Lo demás ya no cambia.
        if (estado === "procesando" || !estado) consulta = setTimeout(() => checkProgress(code), 15000);
        else if (estado === "revision") consulta = setTimeout(() => checkProgress(code), 60000);
    }

    // ── Ficha de un tema. Tiene su dirección (#tema=id), así se puede compartir y Atrás la cierra.
    const detalle = document.getElementById("tema-detalle");
    const detalleImagen = document.getElementById("tema-detalle-imagen");
    const detalleEnlace = document.getElementById("tema-detalle-enlace");
    const miniaturas = document.getElementById("tema-detalle-miniaturas");
    let fotos = [];
    let fotoActual = 0;

    function showPhoto(index) {
        if (!fotos.length) return;
        fotoActual = (index + fotos.length) % fotos.length;
        detalleImagen.src = fotos[fotoActual];
        detalleEnlace.href = fotos[fotoActual];
        [...miniaturas.children].forEach((button, i) => button.classList.toggle("active", i === fotoActual));
    }

    function includesText(tema) {
        const imagenes = tema.imagenes || [];
        const partes = [];
        if (imagenes.some((n) => n.startsWith("general"))) partes.push(t("temas_includes_background"));
        if (imagenes.some((n) => n.startsWith("previews"))) partes.push(t("temas_includes_preview"));
        return partes.length ? `${t("temas_includes")} ${partes.join(", ")}.` : t("temas_includes_colors");
    }

    function openDetail(tema) {
        const ruta = `${GALERIA}temas/${encodeURIComponent(tema.id)}/`;
        const total = Number.isInteger(tema.capturas) ? Math.min(Math.max(tema.capturas, 0), MAX_CAPTURAS) : 0;
        fotos = total ? Array.from({ length: total }, (_, i) => `${ruta}captura${i + 1}.jpg`) : [`${ruta}vista.jpg`];
        document.getElementById("tema-detalle-nombre").textContent = tema.nombre;
        document.getElementById("tema-detalle-datos").textContent =
            `${t("temas_by")} ${tema.autor || t("temas_anonymous")} · ${sizeText(tema.bytes)}${tema.fecha ? ` · ${tema.fecha}` : ""}`;
        document.getElementById("tema-detalle-incluye").textContent = includesText(tema);
        const colores = document.getElementById("tema-detalle-colores");
        colores.replaceChildren(...(tema.muestra || []).filter((c) => /^#[0-9a-f]{6}$/i.test(c)).map((color) => {
            const chip = document.createElement("span");
            chip.style.backgroundColor = color;
            chip.title = color;
            return chip;
        }));
        miniaturas.hidden = fotos.length < 2;
        miniaturas.replaceChildren(...fotos.map((foto, i) => {
            const button = document.createElement("button");
            button.type = "button";
            button.setAttribute("aria-label", `${i + 1}`);
            const small = document.createElement("img");
            small.src = foto;
            small.alt = "";
            button.append(small);
            button.addEventListener("click", () => showPhoto(i));
            return button;
        }));
        const descargar = document.getElementById("tema-detalle-descargar");
        descargar.href = `${ruta}${encodeURIComponent(tema.archivo)}`;
        descargar.download = downloadName(tema);
        descargar.textContent = t("temas_download");
        showPhoto(0);
        if (!detalle.open) detalle.showModal();
    }

    function syncDetail() {
        const match = location.hash.match(/^#tema=(.+)$/);
        if (!match) {
            if (detalle.open) detalle.close();
            return;
        }
        if (temas === null) return;
        const id = decodeURIComponent(match[1]);
        const tema = temas.find((item) => item.id === id);
        if (tema) openDetail(tema);
        else location.hash = "galeria";
    }

    document.getElementById("tema-detalle-cerrar").addEventListener("click", () => detalle.close());
    detalle.addEventListener("click", (event) => { if (event.target === detalle) detalle.close(); });
    detalle.addEventListener("close", () => {
        if (location.hash.startsWith("#tema=")) location.hash = "galeria";
    });
    detalle.addEventListener("keydown", (event) => {
        if (event.key === "ArrowLeft") showPhoto(fotoActual - 1);
        if (event.key === "ArrowRight") showPhoto(fotoActual + 1);
    });
    window.addEventListener("hashchange", syncDetail);

    // ── Pestañas: una sola a la vista. La dirección (#subir) permite enlazar a cada una.
    function showPanel() {
        const wanted = location.hash.slice(1);
        const panels = [...document.querySelectorAll(".temas-panel")];
        const current = panels.some((panel) => panel.id === wanted) ? wanted : "galeria";
        panels.forEach((panel) => { panel.hidden = panel.id !== current; });
        document.querySelectorAll(".temas-pestana").forEach((tab) => {
            const active = tab.dataset.panel === current;
            tab.classList.toggle("active", active);
            tab.setAttribute("aria-selected", String(active));
        });
    }
    window.addEventListener("hashchange", showPanel);
    showPanel();

    // ── Zona para arrastrar o elegir el archivo
    const zona = document.getElementById("temas-zona");
    const elegido = document.getElementById("temas-elegido");
    const input = document.getElementById("temas-archivo");
    let archivo = null;

    function sizeText(bytes) {
        return bytes < 1048576 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1048576).toFixed(1)} MB`;
    }

    function chooseFile(file) {
        archivo = file || null;
        elegido.hidden = !archivo;
        zona.classList.toggle("con-archivo", Boolean(archivo));
        salida.hidden = true;
        if (archivo) elegido.textContent = `${archivo.name} · ${sizeText(archivo.size)}`;
    }

    input.addEventListener("change", () => chooseFile(input.files[0]));
    ["dragenter", "dragover"].forEach((name) => zona.addEventListener(name, (event) => {
        event.preventDefault();
        zona.classList.add("arrastrando");
    }));
    ["dragleave", "drop"].forEach((name) => zona.addEventListener(name, (event) => {
        event.preventDefault();
        zona.classList.remove("arrastrando");
    }));
    zona.addEventListener("drop", (event) => {
        if (event.dataTransfer.files.length) chooseFile(event.dataTransfer.files[0]);
    });
    // Soltar fuera de la zona no debe hacer que el navegador abra el archivo.
    ["dragover", "drop"].forEach((name) => window.addEventListener(name, (event) => event.preventDefault()));

    // ── Capturas: el tema y sus capturas viajan juntos en un solo envío (ver validar_tema.py).
    const zonaCapturas = document.getElementById("temas-zona-capturas");
    const inputCapturas = document.getElementById("temas-capturas");
    const listaCapturas = document.getElementById("temas-capturas-lista");
    let capturas = [];

    function drawCaptures() {
        listaCapturas.hidden = capturas.length === 0;
        listaCapturas.replaceChildren(...capturas.map((file, i) => {
            const item = document.createElement("li");
            const label = document.createElement("span");
            label.textContent = `${file.name} · ${sizeText(file.size)}`;
            const remove = document.createElement("button");
            remove.type = "button";
            remove.textContent = "×";
            remove.setAttribute("aria-label", t("temas_remove"));
            remove.addEventListener("click", () => { capturas.splice(i, 1); drawCaptures(); });
            item.append(label, remove);
            return item;
        }));
    }

    function addCaptures(files) {
        salida.hidden = true;
        for (const file of files) {
            if (!/\.(png|jpe?g|webp)$/i.test(file.name)) { show(salida, t("temas_error_capture_type"), "error"); continue; }
            if (file.size > MAX_CAPTURA_BYTES) { show(salida, t("temas_error_capture_big"), "error"); continue; }
            if (capturas.length >= MAX_CAPTURAS) { show(salida, t("temas_error_capture_many"), "error"); break; }
            capturas.push(file);
        }
        inputCapturas.value = "";
        drawCaptures();
    }

    inputCapturas.addEventListener("change", () => addCaptures(inputCapturas.files));
    ["dragenter", "dragover"].forEach((name) => zonaCapturas.addEventListener(name, (event) => {
        event.preventDefault();
        zonaCapturas.classList.add("arrastrando");
    }));
    ["dragleave", "drop"].forEach((name) => zonaCapturas.addEventListener(name, (event) => {
        event.preventDefault();
        zonaCapturas.classList.remove("arrastrando");
    }));
    zonaCapturas.addEventListener("drop", (event) => addCaptures(event.dataTransfer.files));

    function buildEnvelope(file) {
        if (!capturas.length) return file;
        const head = new TextEncoder().encode(JSON.stringify({ tema: file.size, capturas: capturas.map((c) => c.size) }));
        const size = new Uint8Array(4);
        new DataView(size.buffer).setUint32(0, head.length);
        return new Blob([new TextEncoder().encode("DOWPENV1"), size, head, file, ...capturas], { type: "application/octet-stream" });
    }

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const file = archivo;
        const nick = document.getElementById("temas-nick").value.trim();
        if (!file) { show(salida, t("temas_error_nofile"), "error"); return; }
        if (!/\.(dthmp|json)$/i.test(file.name)) { show(salida, t("temas_error_type"), "error"); return; }
        if (file.size > MAX_BYTES) { show(salida, t("temas_error_big"), "error"); return; }
        const token = typeof turnstile !== "undefined" ? turnstile.getResponse() : "";
        if (!token) { show(salida, t("temas_error_human"), "error"); return; }

        const button = document.getElementById("temas-subir");
        button.disabled = true;
        show(salida, t("temas_uploading"));
        try {
            const res = await fetch(WORKER, {
                method: "POST",
                headers: { "Content-Type": "application/octet-stream", "X-Turnstile": token, "X-Nick": encodeURIComponent(nick) },
                body: buildEnvelope(file),
            });
            const data = await res.json();
            if (data.ok) {
                salida.hidden = true;
                form.reset();
                chooseFile(null);
                capturas = [];
                drawCaptures();
                lastCode(data.codigo);
                checkProgress(data.codigo);
            } else {
                show(salida, t(data.error === "grande" ? "temas_error_big" : data.error === "antibots" ? "temas_error_human" : data.error === "limite" ? "temas_error_limit" : data.error === "ocupado" ? "temas_error_busy" : "temas_network_error"), "error");
            }
        } catch (e) {
            show(salida, t("temas_network_error"), "error");
        }
        button.disabled = false;
        if (typeof turnstile !== "undefined") turnstile.reset();
    });

    document.querySelectorAll(".temas-filtro").forEach((button) => {
        button.addEventListener("click", () => {
            filtro = button.dataset.filtro;
            document.querySelectorAll(".temas-filtro").forEach((b) => b.classList.toggle("active", b === button));
            renderGallery();
        });
    });

    // Al cambiar de idioma, script.js solo traduce lo que ya está en el HTML.
    document.querySelectorAll("[data-lang]").forEach((button) => {
        button.addEventListener("click", () => setTimeout(() => {
            renderGallery();
            syncDetail();
            if (lastCode()) checkProgress(lastCode());
        }, 0));
    });

    if (lastCode()) checkProgress(lastCode());

    fetch(`${GALERIA}temas.json`, { cache: "no-cache" })
        .then((res) => (res.ok ? res.json() : []))
        .catch(() => null)
        .then((data) => {
            if (data === null) {
                aviso.removeAttribute("data-i18n");
                aviso.textContent = t("temas_gallery_error");
                return;
            }
            temas = Array.isArray(data) ? data : [];
            renderGallery();
            syncDetail();
        });
})();
