const translations = {
    en: {
        // Generales
        "site_desc": "DowP: download video and audio, edit images, encode and organize your media, and send them directly to Premiere, After Effects, or DaVinci.",
        "nav_download": "» Download",
        "nav_screenshots": "» Screenshots",
        "nav_whatis": "» What is DowP?",
        "nav_features": "» Features",
        "nav_faq": "» FAQ",
        "nav_credits": "» Credits",
        "menu_title": "Menu",
        
        // Cabecera
        "masthead_sub": "download · convert · <span class=\"nowrap\">organize · <span class=\"blink\">_</span></span>",
        
        // Ticker
        "ticker_text": "★ DowP <span class=\"js-version\">1.9.1</span> IS OUT! ★ new interface ★ quick mode ★ integrated search ★ AI for image and video ★ now in english and portuguese ★ self-updating ★",
        
        // Stats & Support
        "counter_title": "Counter",
        "counter_desc": "total downloads",
        "counter_note": "real data from GitHub",
        "support_title": "Support DowP",
        "support_text": "DowP is free and always will be. If you find it useful, you can buy me a coffee.",
        "support_kofi": "☕ Ko-fi",
        "support_other": "Other ways (Binance Pay)",
        
        // Status
        "status_title": "Status",
        "status_mac_beta": "<em class=\"tag\">beta</em>",
        "status_mac_soon": "<em class=\"tag\">soon</em>",
        "status_linux": "<em class=\"tag\">someday</em>",
        
        // Download Section
        "dl_title": "Download",
        "dl_hero": "Version <strong class=\"js-version\">1.9.1</strong> <span class=\"new\">NEW!</span>",
        "dl_detecting": "Detecting your system...",
        "dl_other": "Other versions:",
        "dl_win": "Windows <span>.exe</span>",
        "dl_mac_silicon": "macOS Apple Silicon <span>.dmg</span>",
        "dl_mac_intel": "macOS Intel <span>.dmg</span>",
        "dl_note": "Install once: DowP updates itself afterwards. All versions on <a href=\"https://github.com/MarckDP/DowP/releases\" target=\"_blank\" rel=\"noopener\">GitHub Releases</a>.",
        
        // Screenshots
        "shot_title": "Screenshots",
        "shot_1_cap": "Quick Mode: paste link and done.",
        "shot_1_text": "Quick Mode",
        "shot_2_cap": "Advanced Process: quality, subs, thumbnails and batch.",
        "shot_2_text": "Advanced Process",
        "shot_3_cap": "Image Editor: convert, crop, draw and remove bg with AI.",
        "shot_3_text": "Image Editor",
        "shot_4_cap": "Media Tools: re-encode and crop with waveform.",
        "shot_4_text": "Media Tools",
        "shot_5_cap": "Media Manager: your library, plus Freesound, Wikimedia, Openverse, Pixabay and Pexels.",
        "shot_5_text": "Media Manager",
        "shot_note": "(click to enlarge)",
        
        // What is DowP
        "what_title": "¿What is DowP?",
        "what_p1": "<strong>DowP</strong> is a GUI designed to squeeze the most out of open source tools like <a href=\"https://github.com/yt-dlp/yt-dlp\" target=\"_blank\" rel=\"noopener\">yt-dlp</a> and <a href=\"https://ffmpeg.org/\" target=\"_blank\" rel=\"noopener\">FFmpeg</a>, combined with <strong>ONNX</strong> models for background removal, depth maps, and normal maps (photo and video), along with <strong>NCNN Vulkan</strong> models for AI upscaling. All processed <strong>100% locally</strong>: no telemetry, no tracking, no accounts or subscriptions.",
        "what_p2": "Designed for daily editing, it lets you <strong>index your favorite resource folders</strong> to have them at hand instantly, or search for free media directly from the app in popular libraries: <a href=\"https://commons.wikimedia.org/\" target=\"_blank\" rel=\"noopener\">Wikimedia Commons</a>, <a href=\"https://freesound.org/\" target=\"_blank\" rel=\"noopener\">Freesound</a>, <a href=\"https://openverse.org/\" target=\"_blank\" rel=\"noopener\">Openverse</a>, <a href=\"https://pixabay.com/\" target=\"_blank\" rel=\"noopener\">Pixabay</a>, and <a href=\"https://pexels.com/\" target=\"_blank\" rel=\"noopener\">Pexels</a>.",
        "what_p3": "And most importantly: <strong>it connects directly with your workflow</strong>. Send media to <strong>Premiere Pro</strong>, <strong>After Effects</strong>, <strong>Photoshop</strong>, and <strong>DaVinci Resolve</strong>, sending what you need to the project or directly to the timeline thanks to the <a href=\"#preguntas-importer\"><strong>DowP Importer</strong></a>.",
        "what_p4": "Don't use those programs or prefer your own method? Everything inside DowP is <strong>draggable</strong>: grab the file from the app and drop it straight into your favorite editor, without opening File Explorer or Finder.",
        "story_sum": "A little history (or how I ended up here)",
        "story_p1": "DowP originally started as a simple yt-dlp script to solve a personal headache: downloading media that was actually compatible with Premiere Pro and After Effects, re-encoding on the fly when Adobe got picky with certain containers and codecs.",
        "story_p2": "Slowly it grew, adding features and more capabilities (some perhaps unnecessary, but fun). After several stumbles and fighting with AI a thousand times to get the code out, I achieved a first version... <strong>which I later foolishly deleted on purpose in a moment of rage.</strong>",
        "story_p3": "After starting from scratch and redoing it with a cooler head, there is finally something much more stable and functional. Always free and open source. Hope you find it useful.",
        
        // Features
        "feat_title": "Features",
        "f_1": "[01] Quick Mode", "f_1_d": "Paste a link, choose video or audio, and download. No hassle.",
        "f_2": "[02] Advanced Process", "f_2_d": "Choose video/audio quality, subs, thumbnails; trim clips and batch download whole playlists.",
        "f_3": "[03] Built-in Search", "f_3_d": "Search YouTube and SoundCloud videos, channels, and playlists without leaving DowP.",
        "f_4": "[04] Image Editor", "f_4_d": "Convert formats (incl. HEIC, AVIF, PSD, RAW), PDF to images, vectorize to SVG, and remove bg with AI.",
        "f_5": "[05] AI Image/Video", "f_5_d": "Depth and normal maps for images and video, multiple models, and AI video upscaling.",
        "f_6": "[06] Media Tools", "f_6_d": "Re-encode video/audio with presets and trim precisely over the waveform.",
        "f_7": "[07] Media Manager", "f_7_d": "Index folders, create collections/subclips, search free media on Freesound, Wikimedia, Openverse, Pixabay, Pexels.",
        "f_8": "[08] Straight to Editor", "f_8_d": "Send media to Premiere Pro, After Effects, Photoshop, DaVinci Resolve, or drag to any editor.",
        "f_9": "[09] History", "f_9_d": "Everything you downloaded, in one place.",
        "f_10": "[10] Auto-updates", "f_10_d": "Only downloads what changed; if something fails, it rolls back to the previous version.",
        "f_11": "[11] Three languages", "f_11_d": "Spanish, English, and Portuguese (Brazil).",
        
        // FAQ
        "faq_title": "FAQ",
        "q_1": "Why does it say 'Beta'?", "a_1": "Because 1.9 is the prelude to DowP 2.0. It's ready for daily use, but might have undiscovered bugs. Fixes arrive automatically.",
        "q_2": "My Mac says it can't verify the developer", "a_2": "It's normal: DowP isn't notarized by Apple. Go to <em>System Settings → Privacy & Security</em> and click <em>Open Anyway</em>. Or in Terminal:",
        "q_3": "What about my Intel Mac?", "a_3": "No Intel version yet. Check back soon: it will appear right here.",
        "q_4": "How do I connect DowP to Premiere, After Effects, or Photoshop?", "a_4": "In DowP, go to <em>Settings → Integrations</em> and install the <strong>DowP Importer</strong> panel. Restart your Adobe program and find it in <em>Window → Extensions</em>.",
        "q_5": "I found a bug / have an idea", "a_5": "Tell us in the <a href=\"https://github.com/MarckDP/DowP/issues\" target=\"_blank\" rel=\"noopener\">guestbook (GitHub issues)</a>. We read them all.",
        
        // Sidebars
        "radio_title": "Radio",
        "radio_play": "Play Radio",
        "radio_pause": "Pause",
        "radio_conn": "Connecting...",
        "radio_err": "Stream error",
        "radio_desc": "chill/ambient music for editing",
        "chat_title": "Live Chat",
        "link_title": "Link me",
        "link_desc": "Have a website? Copy the button and link us, like in the old days.",
        
        // Footer
        "foot_made": "made with",
        "foot_credits": "credits and licenses",
        "foot_best": "best viewed in any browser at 800×600 or more",
        "foot_const": "🚧 always under construction 🚧",
        
        // Botones dinámicos
        "dl_search": "Searching for latest version...",
        "dl_mac_silicon_btn": "Download for macOS (Apple Silicon)",
        "dl_mac_intel_btn": "Download for macOS (Intel)",
        "dl_win_btn": "Download for Windows",
        "dl_linux_btn": "Download for Linux",
        
        // Credits Page
        "cred_sub": "credits · acknowledgments · <span class=\"nowrap\">licenses · <span class=\"blink\">_</span></span>",
        "cred_back": "« Back to home",
        "cred_me_title": "DowP is made by <strong>MarckDP</strong>, with AI help. Follow or support the project here:",
        "cred_coffee": "Buy me a coffee on Ko-fi",
        "cred_binance": "Binance Pay — Binance ID (UID): <strong>345789454</strong> <span class=\"muted\">(Binance app only)</span>",
        "cred_thx_title": "Acknowledgments",
        "cred_thx_sub": "DowP wouldn't be the same without these people:",
        "cred_thx_1": "<span class=\"muted\">— The community: guinea pigs in every version</span>",
        "cred_thx_2": "<span class=\"muted\">— For huge support to the project</span>",
        "cred_thx_3": "<span class=\"muted\">— Ideas and bug reports</span>",
        "cred_thx_4": "<span class=\"muted\">— Testing and feedback</span>",
        "cred_thx_5": "<span class=\"muted\">— Made DowP on Mac possible</span>",
        "cred_thx_6": "<span class=\"muted\">— Ideas and moral support</span>",
        "cred_thx_7": "<span class=\"muted\">— Ideas and testing</span>",
        "cred_lic_title": "Credits and licenses",
        "cred_lic_p": "DowP is free software under the <a href=\"https://github.com/MarckDP/DowP/blob/main/LICENSE\" target=\"_blank\" rel=\"noopener\">GPL-3.0</a> license, and exists thanks to these open source projects. Thanks to all the people who make them possible.",
        "cred_dl": "Downloads"
    },
    pt: {
        // Generales
        "site_desc": "DowP: baixe vídeo e áudio, edite imagens, recodifique e organize suas mídias, enviando tudo direto para Premiere, After Effects ou DaVinci.",
        "nav_download": "» Baixar",
        "nav_screenshots": "» Capturas",
        "nav_whatis": "» O que é DowP?",
        "nav_features": "» Funções",
        "nav_faq": "» Perguntas",
        "nav_credits": "» Créditos",
        "menu_title": "Menu",
        
        // Cabecera
        "masthead_sub": "baixa · converte · <span class=\"nowrap\">organiza · <span class=\"blink\">_</span></span>",
        
        // Ticker
        "ticker_text": "★ DowP <span class=\"js-version\">1.9.1</span> JÁ SAIU! ★ interface nova ★ modo rápido ★ busca integrada ★ IA para imagem e vídeo ★ agora em inglês e português ★ atualiza sozinho ★",
        
        // Stats & Support
        "counter_title": "Contador",
        "counter_desc": "downloads totais",
        "counter_note": "dados reais do GitHub",
        "support_title": "Apoie o DowP",
        "support_text": "O DowP é grátis e sempre será. Se for útil pra você, me pague um café.",
        "support_kofi": "☕ Ko-fi",
        "support_other": "Outras formas (Binance Pay)",
        
        // Status
        "status_title": "Status",
        "status_mac_beta": "<em class=\"tag\">beta</em>",
        "status_mac_soon": "<em class=\"tag\">em breve</em>",
        "status_linux": "<em class=\"tag\">um dia</em>",
        
        // Download Section
        "dl_title": "Baixar",
        "dl_hero": "Versão <strong class=\"js-version\">1.9.1</strong> <span class=\"new\">NOVO!</span>",
        "dl_detecting": "Detectando seu sistema...",
        "dl_other": "Outras versões:",
        "dl_win": "Windows <span>.exe</span>",
        "dl_mac_silicon": "macOS Apple Silicon <span>.dmg</span>",
        "dl_mac_intel": "macOS Intel <span>.dmg</span>",
        "dl_note": "Instale uma vez: o DowP se atualiza sozinho depois. Todas as versões no <a href=\"https://github.com/MarckDP/DowP/releases\" target=\"_blank\" rel=\"noopener\">GitHub Releases</a>.",
        
        // Screenshots
        "shot_title": "Capturas",
        "shot_1_cap": "Modo Rápido: cole o link e pronto.",
        "shot_1_text": "Modo Rápido",
        "shot_2_cap": "Processo Avançado: qualidade, legendas, miniaturas e em lote.",
        "shot_2_text": "Processo Avançado",
        "shot_3_cap": "Editor de Imagem: converta, corte, desenhe e remova fundos com IA.",
        "shot_3_text": "Editor de Imagem",
        "shot_4_cap": "Ferramentas Multimídia: recodifique e corte com waveform.",
        "shot_4_text": "Ferramentas Multimídia",
        "shot_5_cap": "Gestor de Mídia: sua biblioteca, mais Freesound, Wikimedia, Openverse, Pixabay e Pexels.",
        "shot_5_text": "Gestor de Mídia",
        "shot_note": "(clique para ampliar)",
        
        // What is DowP
        "what_title": "O que é DowP?",
        "what_p1": "<strong>DowP</strong> é uma interface gráfica pensada para extrair o máximo de ferramentas de código aberto como <a href=\"https://github.com/yt-dlp/yt-dlp\" target=\"_blank\" rel=\"noopener\">yt-dlp</a> e <a href=\"https://ffmpeg.org/\" target=\"_blank\" rel=\"noopener\">FFmpeg</a>, combinadas com modelos <strong>ONNX</strong> para remoção de fundo, mapas de profundidade e mapas normais (foto e vídeo), e modelos <strong>NCNN Vulkan</strong> para upscaling com IA. Tudo processado <strong>100% localmente</strong>: sem telemetria, sem registros, contas ou assinaturas.",
        "what_p2": "Desenhado para o dia a dia da edição, permite <strong>indexar suas pastas de recursos favoritas</strong> para tê-las sempre à mão, ou buscar material livre direto do app nas bibliotecas mais conhecidas: <a href=\"https://commons.wikimedia.org/\" target=\"_blank\" rel=\"noopener\">Wikimedia Commons</a>, <a href=\"https://freesound.org/\" target=\"_blank\" rel=\"noopener\">Freesound</a>, <a href=\"https://openverse.org/\" target=\"_blank\" rel=\"noopener\">Openverse</a>, <a href=\"https://pixabay.com/\" target=\"_blank\" rel=\"noopener\">Pixabay</a> e <a href=\"https://pexels.com/\" target=\"_blank\" rel=\"noopener\">Pexels</a>.",
        "what_p3": "E o mais importante: <strong>conecta-se diretamente ao seu fluxo de trabalho</strong>. Envie mídias para <strong>Premiere Pro</strong>, <strong>After Effects</strong>, <strong>Photoshop</strong> e <strong>DaVinci Resolve</strong>, mandando para o projeto ou direto para a linha do tempo graças ao <a href=\"#preguntas-importer\"><strong>DowP Importer</strong></a>.",
        "what_p4": "Não usa esses programas ou prefere seu método? Tudo no DowP é <strong>arrastável</strong>: pegue o arquivo do app e solte direto no seu editor favorito, sem precisar abrir o Explorador de Arquivos ou Finder.",
        "story_sum": "Um pouco de história (ou como vim parar aqui)",
        "story_p1": "O DowP nasceu como um simples script de yt-dlp para resolver uma dor de cabeça: baixar mídias realmente compatíveis com Premiere Pro e After Effects, recodificando na hora quando a Adobe não gostava de certos codecs.",
        "story_p2": "Aos poucos foi crescendo, ganhando funções. Depois de vários tropeços e de brigar com a IA mil vezes para o código sair, cheguei numa primeira versão... <strong>que depois apaguei de propósito feito idiota num momento de raiva.</strong>",
        "story_p3": "Depois de recomeçar do zero de cabeça fria, finalmente há algo muito mais estável e funcional. Sempre grátis e de código aberto. Espero que seja útil.",
        
        // Features
        "feat_title": "Funções",
        "f_1": "[01] Modo Rápido", "f_1_d": "Cole um link, escolha vídeo ou áudio e baixe. Sem enrolação.",
        "f_2": "[02] Processo Avançado", "f_2_d": "Escolha qualidade de vídeo/áudio, legendas, thumbs; corte trechos e baixe playlists em lote.",
        "f_3": "[03] Busca Integrada", "f_3_d": "Busque vídeos, canais e listas do YouTube e SoundCloud sem sair do DowP.",
        "f_4": "[04] Editor de Imagem", "f_4_d": "Converta formatos (incl. HEIC, AVIF, PSD, RAW), PDF para imagens, vetorize em SVG e remova fundos com IA.",
        "f_5": "[05] IA para Imagem/Vídeo", "f_5_d": "Mapas de profundidade e normais, vários modelos, e upscaling de vídeo com IA.",
        "f_6": "[06] Ferramentas Multimídia", "f_6_d": "Recodifique vídeo/áudio com presets e corte com precisão na waveform.",
        "f_7": "[07] Gestor de Mídia", "f_7_d": "Indexe pastas, crie coleções/subclips, busque mídia livre no Freesound, Wikimedia, Openverse, Pixabay, Pexels.",
        "f_8": "[08] Direto no Editor", "f_8_d": "Envie mídia para Premiere Pro, After Effects, Photoshop, DaVinci Resolve, ou arraste.",
        "f_9": "[09] Histórico", "f_9_d": "Tudo o que você baixou, num só lugar.",
        "f_10": "[10] Atualização auto", "f_10_d": "Só baixa o que mudou; se der erro, reverte para a versão anterior.",
        "f_11": "[11] Três idiomas", "f_11_d": "Espanhol, Inglês e Português (Brasil).",
        
        // FAQ
        "faq_title": "Perguntas",
        "q_1": "Por que diz 'Beta'?", "a_1": "Porque a 1.9 é a antesala do DowP 2.0. Já pode ser usado no dia a dia, mas pode ter algum bug oculto. Correções chegam sozinhas.",
        "q_2": "Meu Mac diz que não pode verificar o desenvolvedor", "a_2": "É normal: o DowP não é notarizado pela Apple. Vá em <em>Ajustes do Sistema → Privacidade e Segurança</em> e clique em <em>Abrir Mesmo Assim</em>. Ou no Terminal:",
        "q_3": "E o meu Mac com Intel?", "a_3": "Ainda não há versão para Intel. Volte em breve: vai aparecer bem aqui.",
        "q_4": "Como conecto o DowP ao Premiere, After Effects ou Photoshop?", "a_4": "No DowP, vá em <em>Configurações → Integrações</em> e instale o painel <strong>DowP Importer</strong>. Reinicie o programa da Adobe e busque em <em>Janela → Extensões</em>.",
        "q_5": "Encontrei um erro / tenho uma ideia", "a_5": "Conte-nos no <a href=\"https://github.com/MarckDP/DowP/issues\" target=\"_blank\" rel=\"noopener\">livro de visitas (issues do GitHub)</a>. Lemos todos.",
        
        // Sidebars
        "radio_title": "Rádio",
        "radio_play": "Tocar Rádio",
        "radio_pause": "Pausar",
        "radio_conn": "Conectando...",
        "radio_err": "Erro no stream",
        "radio_desc": "música chill/ambient para editar",
        "chat_title": "Chat ao Vivo",
        "link_title": "Me linke",
        "link_desc": "Tem um site? Copie o botão e nos linke, como nos velhos tempos.",
        
        // Footer
        "foot_made": "feito com",
        "foot_credits": "créditos e licenças",
        "foot_best": "melhor visualizado em qualquer navegador a 800×600 ou mais",
        "foot_const": "🚧 sempre em construção 🚧",
        
        // Botones dinámicos
        "dl_search": "Buscando a última versão...",
        "dl_mac_silicon_btn": "Baixar para macOS (Apple Silicon)",
        "dl_mac_intel_btn": "Baixar para macOS (Intel)",
        "dl_win_btn": "Baixar para Windows",
        "dl_linux_btn": "Baixar para Linux",
        
        // Credits Page
        "cred_sub": "créditos · agradecimentos · <span class=\"nowrap\">licenças · <span class=\"blink\">_</span></span>",
        "cred_back": "« Voltar ao início",
        "cred_me_title": "DowP é feito por <strong>MarckDP</strong>, com ajuda de IA. Siga ou apoie o projeto aqui:",
        "cred_coffee": "Pague-me um café no Ko-fi",
        "cred_binance": "Binance Pay — Binance ID (UID): <strong>345789454</strong> <span class=\"muted\">(só pelo app da Binance)</span>",
        "cred_thx_title": "Agradecimentos",
        "cred_thx_sub": "DowP não seria o mesmo sem essas pessoas:",
        "cred_thx_1": "<span class=\"muted\">— A comunidade: cobaias em cada versão</span>",
        "cred_thx_2": "<span class=\"muted\">— Por um apoio enorme ao projeto</span>",
        "cred_thx_3": "<span class=\"muted\">— Ideias e relato de erros</span>",
        "cred_thx_4": "<span class=\"muted\">— Testes e feedback</span>",
        "cred_thx_5": "<span class=\"muted\">— Tornou possível o DowP no Mac</span>",
        "cred_thx_6": "<span class=\"muted\">— Ideias e apoio moral</span>",
        "cred_thx_7": "<span class=\"muted\">— Ideias e testes</span>",
        "cred_lic_title": "Créditos e licenças",
        "cred_lic_p": "DowP é software livre sob a licença <a href=\"https://github.com/MarckDP/DowP/blob/main/LICENSE\" target=\"_blank\" rel=\"noopener\">GPL-3.0</a>, e existe graças a esses projetos de código aberto. Obrigado a todos que os tornam possíveis.",
        "cred_dl": "Downloads"
    },
    es: {
        "dl_search": "Buscando la última versión...",
        "dl_mac_silicon_btn": "Descargar para macOS (Apple Silicon)",
        "dl_mac_intel_btn": "Descargar para macOS (Intel)",
        "dl_win_btn": "Descargar para Windows",
        "dl_linux_btn": "Descargar para Linux"
    }
};
