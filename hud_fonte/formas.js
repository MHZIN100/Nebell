// ============================================================
//  NEBELL — GEOMETRIA VIVA
// ============================================================
//
//  30.000 particulas com fisica que se reorganizam entre 19 formas.
//  Cada forma e um ESTADO: bater o olho na janela e saber o que ela
//  esta fazendo, sem ler nada.
//
//  O mapa saiu do proprio codigo dela -- os quatro estados base mais
//  as familias das 27 ferramentas que o nebell.py ja descreve em
//  O_QUE_ESTA_FAZENDO. Entao o lado Python manda o nome da
//  ferramenta que esta rodando e a janela acha a forma sozinha.
//
//  A paleta nao e enfeite: a profundidade pinta o volume (longe
//  azul, perto vermelho) e a energia acende por cima, entao a nuvem
//  pega fogo na travessia e esfria quando assenta. Cada estado ainda
//  empurra a paleta para o seu lado.
//
//  Canvas 2D, sem WebGL e sem biblioteca: a placa tem 6 GB e divide
//  com o Ollama.
// ============================================================

(function (global) {
  "use strict";

  // Azul -> roxo -> vermelho.
  const PALETA = [
    [40, 110, 255],
    [150, 60, 245],
    [255, 48, 92],
  ];

  const PADRAO = {
    particulas: 30000,
    minimo: 7000,
    escala: 0.8,
    foco: 3.2,
    segundosNaDemo: 5.5,
  };

  const PHI = (1 + Math.sqrt(5)) / 2;

  function naEsfera() {
    const u = Math.random() * 2 - 1;
    const a = Math.random() * 6.283185307;
    const r = Math.sqrt(1 - u * u);
    return [r * Math.cos(a), u, r * Math.sin(a)];
  }

  function icosaedro() {
    const v = [];

    for (const s1 of [-1, 1]) {
      for (const s2 of [-1, 1]) {
        v.push([0, s1, s2 * PHI]);
        v.push([s1, s2 * PHI, 0]);
        v.push([s2 * PHI, 0, s1]);
      }
    }

    return v.map(([x, y, z]) => {
      const d = Math.hypot(x, y, z);
      return [x / d, y / d, z / d];
    });
  }

  function arestasDe(vertices) {
    let menor = Infinity;

    for (let i = 0; i < vertices.length; i++) {
      for (let j = i + 1; j < vertices.length; j++) {
        const d = Math.hypot(
          vertices[i][0] - vertices[j][0],
          vertices[i][1] - vertices[j][1],
          vertices[i][2] - vertices[j][2]
        );
        if (d < menor) menor = d;
      }
    }

    const pares = [];

    for (let i = 0; i < vertices.length; i++) {
      for (let j = i + 1; j < vertices.length; j++) {
        const d = Math.hypot(
          vertices[i][0] - vertices[j][0],
          vertices[i][1] - vertices[j][1],
          vertices[i][2] - vertices[j][2]
        );
        if (d <= menor * 1.08) pares.push([i, j]);
      }
    }

    return pares;
  }

  // Superformula de Gielis: uma familia inteira de solidos a partir
  // de quatro numeros. E dela que saem as formas sem nome.
  function superRaio(ang, m, n1, n2, n3) {
    const t = m * ang / 4;
    const r = Math.pow(
      Math.pow(Math.abs(Math.cos(t)), n2) + Math.pow(Math.abs(Math.sin(t)), n3),
      -1 / n1
    );
    return isFinite(r) ? Math.min(r, 3) : 0;
  }

  function superforma(p1, p2) {
    return function () {
      const theta = Math.random() * 6.283185307 - 3.1416;
      const phi = Math.random() * 3.1416 - 1.5708;
      const r1 = superRaio(theta, p1[0], p1[1], p1[2], p1[3]);
      const r2 = superRaio(phi, p2[0], p2[1], p2[2], p2[3]);
      return [
        r1 * Math.cos(theta) * r2 * Math.cos(phi),
        r2 * Math.sin(phi),
        r1 * Math.sin(theta) * r2 * Math.cos(phi),
      ];
    };
  }

  const ICO = icosaedro();
  const ICO_ARESTAS = arestasDe(ICO);

  const TAU = 6.283185307;

  function tremor(e) {
    return (Math.random() - 0.5) * e;
  }

  // ---- as formas -------------------------------------------
  //
  //  Cada uma e o rosto de um ESTADO. A ideia: bater o olho na
  //  janela e saber o que ela esta fazendo, sem ler nada.

  const FORMAS = {
    // -- parada: tres aneis girando devagar, sem pressa --
    giroscopio() {
      const anel = (Math.random() * 3) | 0;
      const a = Math.random() * TAU;
      const r = 0.8 + tremor(0.035);
      const x = Math.cos(a) * r, y = Math.sin(a) * r, e = tremor(0.035);
      if (anel === 0) return [x, y, e];
      if (anel === 1) return [x, e, y];
      return [e, x, y];
    },

    // -- ouvindo: aneis abrindo para fora, como som chegando --
    ondas() {
      const anel = (Math.random() * 6) | 0;
      const r = 0.16 + anel * 0.135;
      const a = Math.random() * TAU;
      return [
        Math.cos(a) * r + tremor(0.02),
        Math.sin(anel * 1.25) * 0.13 + tremor(0.02),
        Math.sin(a) * r + tremor(0.02),
      ];
    },

    // -- pensando: o no, que passa por dentro de si mesmo --
    no() {
      const t = Math.random() * TAU;
      const r = 0.52 + 0.22 * Math.cos(3 * t);
      const [ex, ey, ez] = naEsfera();
      return [
        r * Math.cos(2 * t) + ex * 0.055,
        0.3 * Math.sin(3 * t) + ey * 0.055,
        r * Math.sin(2 * t) + ez * 0.055,
      ];
    },

    // -- falando: a onda da voz, com harmonicos --
    onda() {
      const x = Math.random() * 2 - 1;
      const env = 1 - x * x * 0.55;
      const y = (Math.sin(x * 7.5) * 0.52 + Math.sin(x * 17) * 0.17) * env * 0.5;
      return [x * 0.92, y + tremor(0.03), tremor(0.22)];
    },

    // -- internet: globo de malha, meridiano e paralelo --
    rede() {
      if (Math.random() < 0.5) {
        const lat = (((Math.random() * 7) | 0) - 3) * 0.37;
        const a = Math.random() * TAU;
        const r = Math.cos(lat);
        return [Math.cos(a) * r, Math.sin(lat), Math.sin(a) * r];
      }

      const lon = ((Math.random() * 8) | 0) * (TAU / 8);
      const lat = Math.random() * Math.PI - Math.PI / 2;
      const r = Math.cos(lat);
      return [Math.cos(lon) * r, Math.sin(lat), Math.sin(lon) * r];
    },

    // -- documento: folhas empilhadas, levemente giradas --
    camadas() {
      const k = (Math.random() * 7) | 0;
      const y = -0.6 + k * 0.2;
      const g = k * 0.14;
      const u = (Math.random() * 2 - 1) * 0.62;
      const v = (Math.random() * 2 - 1) * 0.46;
      const borda = Math.random() < 0.55;
      const a = borda ? (Math.random() < 0.5 ? Math.sign(u) * 0.62 : u) : u;
      const b = borda ? (Math.abs(a) >= 0.61 ? v : Math.sign(v) * 0.46) : v;
      return [
        a * Math.cos(g) - b * Math.sin(g),
        y + tremor(0.012),
        a * Math.sin(g) + b * Math.cos(g),
      ];
    },

    // -- visao: um olho. anel de fora, iris raiada, pupila vazia --
    olho() {
      const p = Math.random();

      if (p < 0.3) {
        // contorno amendoado
        const a = Math.random() * TAU;
        return [Math.cos(a) * 0.92, Math.sin(a) * 0.46, tremor(0.04)];
      }

      if (p < 0.4) {
        // anel da iris
        const a = Math.random() * TAU;
        return [Math.cos(a) * 0.4, Math.sin(a) * 0.4, 0.12 + tremor(0.03)];
      }

      // raios da iris, deixando a pupila oca
      const a = (((Math.random() * 44) | 0) / 44) * TAU + tremor(0.05);
      const r = 0.16 + Math.random() * 0.24;
      return [Math.cos(a) * r, Math.sin(a) * r, 0.1 + tremor(0.05)];
    },

    // -- gravando: o cubo em grade, se montando --
    grade() {
      const n = 4, passo = 2 / n;
      const eixo = (Math.random() * 3) | 0;
      const a = -1 + ((Math.random() * (n + 1)) | 0) * passo;
      const b = -1 + ((Math.random() * (n + 1)) | 0) * passo;
      const c = Math.random() * 2 - 1;
      const p = eixo === 0 ? [c, a, b] : eixo === 1 ? [a, c, b] : [a, b, c];
      return [p[0] * 0.62 + tremor(0.01), p[1] * 0.62 + tremor(0.01),
              p[2] * 0.62 + tremor(0.01)];
    },

    // -- procurando no disco: funil, puxando para baixo --
    vortice() {
      const r = Math.sqrt(Math.random());

      // Metade nos bracos da espiral (que dao o giro) e metade
      // espalhada na parede do funil (que da o corpo). So os bracos
      // viravam um risco fino na tela.
      const a = Math.random() < 0.55
        ? r * 9.5 + tremor(0.5)
        : Math.random() * TAU;

      return [
        Math.cos(a) * r * 0.85,
        (0.52 - r) * 0.95 + tremor(0.04),
        Math.sin(a) * r * 0.85,
      ];
    },

    // -- programas: favo de mel --
    colmeia() {
      const col = ((Math.random() * 5) | 0) - 2;
      const lin = ((Math.random() * 5) | 0) - 2;
      const cx = col * 0.3;
      const cy = lin * 0.26 + (col % 2 ? 0.13 : 0);
      const lado = ((Math.random() * 6) | 0) * (TAU / 6);
      const prox = lado + TAU / 6;
      const t = Math.random();
      const r = 0.15;
      return [
        cx + (Math.cos(lado) + (Math.cos(prox) - Math.cos(lado)) * t) * r,
        cy + (Math.sin(lado) + (Math.sin(prox) - Math.sin(lado)) * t) * r,
        tremor(0.05),
      ];
    },

    // -- executando: tres setas em fila, apontando para cima --
    seta() {
      const fila = ((Math.random() * 3) | 0) - 1;
      const t = Math.random() * 2 - 1;
      const grossura = (Math.random() < 0.5 ? 0 : 0.075);
      return [
        t * 0.62 + tremor(0.012),
        (0.52 - Math.abs(t) * 0.62) + fila * 0.42 - grossura + tremor(0.012),
        tremor(0.06),
      ];
    },

    // -- maquina: cascas concentricas, como um reator --
    nucleo() {
      const casca = (Math.random() * 3) | 0;
      const r = 0.3 + casca * 0.26;
      const [x, y, z] = naEsfera();
      return [x * r, y * r, z * r];
    },

    // -- backup: ampulheta, com grao caindo no meio --
    ampulheta() {
      if (Math.random() < 0.12) {
        return [tremor(0.06), Math.random() * 1.4 - 0.7, tremor(0.06)];
      }

      const h = Math.random() * 2 - 1;
      const r = Math.abs(h) * 0.56 + 0.03;
      const a = Math.random() * TAU;
      return [Math.cos(a) * r, h * 0.78, Math.sin(a) * r];
    },

    // -- memoria: a helice dupla --
    helice() {
      const t = Math.random() * TAU * 2.2;
      const altura = (t / (TAU * 2.2)) * 1.7 - 0.85;
      const fita = Math.random();

      if (fita < 0.78) {
        const lado = fita < 0.39 ? 0 : Math.PI;
        return [Math.cos(t + lado) * 0.42 + tremor(0.03), altura,
                Math.sin(t + lado) * 0.42 + tremor(0.03)];
      }

      const s = Math.random() * 2 - 1;
      return [Math.cos(t) * 0.42 * s, altura, Math.sin(t) * 0.42 * s];
    },

    // -- agenda: mostrador com marcas e dois ponteiros --
    relogio() {
      const p = Math.random();

      if (p < 0.45) {
        const a = Math.random() * TAU;
        return [Math.cos(a) * 0.85, Math.sin(a) * 0.85, tremor(0.03)];
      }

      if (p < 0.78) {
        const marca = ((Math.random() * 12) | 0) * (TAU / 12);
        const r = 0.68 + Math.random() * 0.13;
        return [Math.cos(marca) * r, Math.sin(marca) * r, tremor(0.03)];
      }

      const ponteiro = Math.random() < 0.5 ? 1.1 : 2.6;
      const r = Math.random() * (ponteiro > 2 ? 0.5 : 0.68);
      return [Math.cos(ponteiro) * r, Math.sin(ponteiro) * r, tremor(0.02)];
    },

    // -- alerta: estrela de pontas, agressiva --
    estrela: superforma([7, 0.2, 1.7, 1.7], [7, 0.2, 1.7, 1.7]),

    // -- erro: o icosaedro, quebrado em arestas soltas --
    icosaedro() {
      const [i, j] = ICO_ARESTAS[(Math.random() * ICO_ARESTAS.length) | 0];
      const t = Math.random();
      return [
        ICO[i][0] + (ICO[j][0] - ICO[i][0]) * t + tremor(0.012),
        ICO[i][1] + (ICO[j][1] - ICO[i][1]) * t + tremor(0.012),
        ICO[i][2] + (ICO[j][2] - ICO[i][2]) * t + tremor(0.012),
      ];
    },

    // -- encerrando: tudo recolhendo para um ponto --
    ponto() {
      const [x, y, z] = naEsfera();
      const r = Math.pow(Math.random(), 3) * 0.3;
      return [x * r, y * r, z * r];
    },

    toro() {
      const u = Math.random() * TAU, v = Math.random() * TAU;
      return [(0.72 + 0.27 * Math.cos(v)) * Math.cos(u),
              0.27 * Math.sin(v),
              (0.72 + 0.27 * Math.cos(v)) * Math.sin(u)];
    },

    flor: superforma([6, 1, 1, 1], [3, 1, 1, 1]),
  };

  // ---- os estados ------------------------------------------
  //
  //  Saiu do proprio codigo do NEBELL: os quatro estados base mais
  //  as familias das 27 ferramentas que ele ja descreve em texto.
  //  `matiz` empurra a paleta (negativo = mais azul, positivo = mais
  //  vermelho); `pressa` e `ruido` dao o temperamento.

  const ESTADOS = {
    espera:     { forma: "giroscopio", rotulo: "EM ESPERA",       diz: "aguardando você",             matiz: -0.22, ruido: 0.36, pressa: 0.75, brilho: 0.98 },
    ouvindo:    { forma: "ondas",      rotulo: "OUVINDO",         diz: "pode falar",                  matiz: -0.10, ruido: 0.9, pressa: 1.15, brilho: 1.12 },
    pensando:   { forma: "no",         rotulo: "PENSANDO",        diz: "montando a resposta",         matiz: 0.16,  ruido: 1.7, pressa: 2.00, brilho: 1.08 },
    falando:    { forma: "onda",       rotulo: "FALANDO",         diz: "respondendo",                 matiz: 0.02,  ruido: 1.0, pressa: 1.35, brilho: 1.22 },

    internet:   { forma: "rede",       rotulo: "NA INTERNET",     diz: "pesquisando, lendo página, clima, cotação", matiz: -0.16, ruido: 1.1, pressa: 1.5, brilho: 1.05 },
    documento:  { forma: "camadas",    rotulo: "NO DOCUMENTO",    diz: "resumindo ou procurando no documento",      matiz: -0.05, ruido: 0.7, pressa: 1.0, brilho: 1.0 },
    visao:      { forma: "olho",       rotulo: "OLHANDO",         diz: "lendo a tela, imagem ou captura",           matiz: 0.08,  ruido: 0.6, pressa: 0.9, brilho: 1.18 },
    gravando:   { forma: "grade",      rotulo: "GRAVANDO",        diz: "escrevendo arquivo ou criando pasta",       matiz: 0.0,   ruido: 0.8, pressa: 1.25, brilho: 1.05 },
    disco:      { forma: "vortice",    rotulo: "NO DISCO",        diz: "procurando arquivos, analisando pasta",     matiz: 0.10,  ruido: 1.3, pressa: 1.7, brilho: 1.0 },
    programas:  { forma: "colmeia",    rotulo: "PROGRAMAS",       diz: "listando ou abrindo programa",              matiz: -0.12, ruido: 0.7, pressa: 1.1, brilho: 1.0 },
    comando:    { forma: "seta",       rotulo: "EXECUTANDO",      diz: "rodando o comando",                         matiz: 0.22,  ruido: 1.0, pressa: 1.8, brilho: 1.1 },
    maquina:    { forma: "nucleo",     rotulo: "NA MÁQUINA",      diz: "medindo a placa, liberando memória",        matiz: 0.05,  ruido: 0.9, pressa: 1.2, brilho: 1.05 },
    backup:     { forma: "ampulheta",  rotulo: "BACKUP",          diz: "guardando a memória",                       matiz: -0.18, ruido: 0.5, pressa: 0.85, brilho: 0.98 },
    memoria:    { forma: "helice",     rotulo: "NA MEMÓRIA",      diz: "procurando o que ficou guardado",           matiz: -0.08, ruido: 0.8, pressa: 1.1, brilho: 1.05 },
    agenda:     { forma: "relogio",    rotulo: "NA AGENDA",       diz: "mexendo nos lembretes",                     matiz: -0.14, ruido: 0.6, pressa: 1.0, brilho: 1.0 },
    janelas:    { forma: "toro",       rotulo: "NAS JANELAS",     diz: "vendo o que está aberto",                   matiz: -0.1,  ruido: 0.8, pressa: 1.2, brilho: 1.0 },

    alerta:     { forma: "estrela",    rotulo: "ALERTA",          diz: "a máquina pediu atenção",                   matiz: 0.42,  ruido: 2.2, pressa: 2.4, brilho: 1.3 },
    erro:       { forma: "icosaedro",  rotulo: "DEU ERRO",        diz: "alguma coisa falhou",                       matiz: 0.3,   ruido: 1.6, pressa: 1.6, brilho: 1.0 },
    encerrando: { forma: "ponto",      rotulo: "ENCERRANDO",      diz: "soltando a máquina",                        matiz: -0.3,  ruido: 0.3, pressa: 0.6, brilho: 0.8 },
  };

  // Da ferramenta para o estado. Os nomes sao os mesmos que o
  // nebell.py ja usa em O_QUE_ESTA_FAZENDO, entao o lado Python nao
  // precisa inventar nada: manda o nome da ferramenta e pronto.
  const DA_FERRAMENTA = {
    pesquisar_web: "internet", ler_pagina: "internet",
    clima: "internet", cotacao: "internet",
    resumir_documento: "documento", procurar_no_documento: "documento",
    ler_tela: "visao", capturar_tela: "visao",
    ler_imagem: "visao", editar_imagem: "visao",
    escrever_arquivo: "gravando", acrescentar_arquivo: "gravando",
    criar_pasta: "gravando", editar_arquivo: "gravando",
    buscar_arquivos: "disco", analisar_pasta: "disco",
    listar_programas: "programas", abrir_programa: "programas",
    executar_comando: "comando", executar_cmd: "comando",
    info_gpu: "maquina", estado_maquina: "maquina",
    liberar_maquina: "maquina",
    backup: "backup", recordar: "memoria", lembrete: "agenda",
    listar_janelas: "janelas",
  };

  // Formas CHATAS: vivem num plano. Com a nuvem girando sem parar
  // elas apareciam de perfil, e um olho visto de lado nao serve de
  // sinal nenhum. Nestas o giro livre e trocado por um balanco leve,
  // e elas ficam viradas para quem olha.
  const PLANAS = new Set(["onda", "olho", "colmeia", "seta", "relogio"]);

  const NOMES = Object.keys(ESTADOS);

  // =========================================================
  //  O MOTOR
  // =========================================================

  function criar(canvas, opcoes) {
    const cfg = Object.assign({}, PADRAO, opcoes || {});
    const ctx = canvas.getContext("2d", { alpha: false });
    const devagar = global.matchMedia
      && global.matchMedia("(prefers-reduced-motion:reduce)").matches;

    const N = Math.max(cfg.minimo, cfg.particulas | 0);

    // Os alvos sao feitos SOB DEMANDA e guardados. Montar as 19
    // formas na abertura seriam 570 mil pontos de uma vez, e a
    // janela nasceria travada. Assim so paga quem aparece.
    const cache = {};

    function alvosDe(nome) {
      if (cache[nome]) return cache[nome];

      const fabrica = FORMAS[nome] || FORMAS.giroscopio;
      const xs = new Float32Array(N);
      const ys = new Float32Array(N);
      const zs = new Float32Array(N);

      for (let i = 0; i < N; i++) {
        const p = fabrica();
        xs[i] = p[0]; ys[i] = p[1]; zs[i] = p[2];
      }

      // Iguala o tamanho de todas, senao a troca da um salto de
      // escala feio.
      let maior = 0;

      for (let i = 0; i < N; i++) {
        const d = Math.hypot(xs[i], ys[i], zs[i]);
        if (d > maior) maior = d;
      }

      if (maior > 0) {
        const k = 0.78 / maior;
        for (let i = 0; i < N; i++) { xs[i] *= k; ys[i] *= k; zs[i] *= k; }
      }

      cache[nome] = [xs, ys, zs];
      return cache[nome];
    }

    const px = new Float32Array(N), py = new Float32Array(N), pz = new Float32Array(N);
    const vx = new Float32Array(N), vy = new Float32Array(N), vz = new Float32Array(N);

    for (let i = 0; i < N; i++) {
      const [x, y, z] = naEsfera();
      px[i] = x * 2.6; py[i] = y * 2.6; pz[i] = z * 2.6;
    }

    // 3.11 Big Bang: a nuvem nasce de um ponto e se expande ate preencher
    // a HUD. Nao mexe na fisica -- so na PROJECAO: `entrada` multiplica a
    // posicao na tela, entao em 0 tudo se projeta no centro (um ponto) e
    // em 1 fica no lugar normal. A fisica roda igual por baixo; a nuvem
    // ja esta formada quando a expansao termina. So por config
    // (cfg.bigBang === false) ela fica desligada -- e uma animacao curta,
    // de proposito, entao nao segue o prefers-reduced-motion.
    let entrada = (cfg.bigBang !== false) ? 0 : 1;

    // A expansao so comeca quando a JANELA aparece de verdade (ganha foco
    // ou fica visivel). Sem isso, ela rodaria enquanto a janela ainda
    // esta sendo aberta e a pessoa perderia os ~0,9 s. Rede de seguranca:
    // se nenhum evento vier, comeca sozinha depois de 5 s.
    let comecouAbertura = entrada >= 1;

    function dispararAbertura() { comecouAbertura = true; }
    function pularAbertura() { entrada = 1; comecouAbertura = true; }

    if (entrada < 1) {
      global.addEventListener("keydown", pularAbertura, { once: true });
      global.addEventListener("pointerdown", pularAbertura, { once: true });
      // Caso normal: a janela ja aparece antes de a pagina carregar,
      // entao se ja esta visivel, comeca agora.
      if (!global.document || global.document.visibilityState === "visible") {
        dispararAbertura();
      }
      // Reserva, para quando a pagina carrega escondida e aparece depois.
      global.addEventListener("focus", dispararAbertura, { once: true });
      if (global.document) {
        global.document.addEventListener("visibilitychange", function ov() {
          if (!global.document.hidden) {
            dispararAbertura();
            global.document.removeEventListener("visibilitychange", ov);
          }
        });
      }
      global.setTimeout(dispararAbertura, 5000);
    }

    // --- tela ---
    let L = 1, A = 1, buffer = null, buf32 = null;
    let acc = null, calor = null, tocados = null, nTocados = 0;

    function medir() {
      const caixa = canvas.getBoundingClientRect();
      const d = Math.min(global.devicePixelRatio || 1, 2) * cfg.escala;
      L = Math.max(1, Math.round((caixa.width || 300) * d));
      A = Math.max(1, Math.round((caixa.height || 300) * d));
      canvas.width = L; canvas.height = A;
      buffer = ctx.createImageData(L, A);
      buf32 = new Uint32Array(buffer.data.buffer);
      acc = new Float32Array(L * A);
      calor = new Float32Array(L * A);
      tocados = new Int32Array(N * 6);
      nTocados = 0;
    }

    if (global.ResizeObserver) new global.ResizeObserver(medir).observe(canvas);
    else global.addEventListener("resize", medir);

    medir();

    // --- campo de fluxo, grade grossa lida com mistura ---
    const GRADE = 22;
    const campoX = new Float32Array(GRADE * GRADE);
    const campoY = new Float32Array(GRADE * GRADE);
    const campoZ = new Float32Array(GRADE * GRADE);

    function moerCampo(t) {
      for (let j = 0; j < GRADE; j++) {
        const v = (j / GRADE) * 6.2832;

        for (let i = 0; i < GRADE; i++) {
          const u = (i / GRADE) * 6.2832;
          const k = j * GRADE + i;
          campoX[k] = Math.sin(v * 1.7 + t * 0.9) * Math.cos(u * 1.1 - t * 0.6);
          campoY[k] = Math.sin(u * 1.3 - t * 0.7) * Math.cos(v * 1.9 + t * 0.5);
          campoZ[k] = Math.sin((u + v) * 0.9 + t * 1.1);
        }
      }
    }

    // --- rastro do cursor ---
    const TRILHA = 48;
    const trilha = new Float32Array(TRILHA * TRILHA);
    const trilhaX = new Float32Array(TRILHA * TRILHA);
    const trilhaY = new Float32Array(TRILHA * TRILHA);

    let alvoGiroY = 0, alvoGiroX = 0;
    const ondas = [];

    function depositar(x, y, forca) {
      const ci = (((x + 0.9) / 1.8) * TRILHA) | 0;
      const cj = (((0.9 - y) / 1.8) * TRILHA) | 0;

      for (let j = cj - 3; j <= cj + 3; j++) {
        if (j < 0 || j >= TRILHA) continue;

        for (let i = ci - 3; i <= ci + 3; i++) {
          if (i < 0 || i >= TRILHA) continue;

          const d = Math.hypot(i - ci, j - cj);
          if (d > 3) continue;

          const k = j * TRILHA + i;
          const v = (1 - d / 3) * forca;

          if (v > trilha[k]) {
            trilha[k] = v;
            trilhaX[k] = (i - ci) / 3;
            trilhaY[k] = -(j - cj) / 3;
          }
        }
      }
    }

    function tela2mundo(cx, cy) {
      const caixa = canvas.getBoundingClientRect();
      const R = Math.min(caixa.width, caixa.height) * 0.62;
      return [
        (cx - caixa.left - caixa.width / 2) / R,
        -(cy - caixa.top - caixa.height / 2) / R,
      ];
    }

    canvas.addEventListener("pointermove", (ev) => {
      const [x, y] = tela2mundo(ev.clientX, ev.clientY);
      depositar(x, y, 1);
      alvoGiroY = Math.max(-0.9, Math.min(0.9, x * 1.2));
      alvoGiroX = Math.max(-0.5, Math.min(0.5, -y * 0.8));
    });

    canvas.addEventListener("pointerleave", () => {
      alvoGiroY = 0; alvoGiroX = 0;
    });

    canvas.addEventListener("pointerdown", (ev) => {
      const [x, y] = tela2mundo(ev.clientX, ev.clientY);
      ondas.push({ x, y, idade: 0 });
      if (ondas.length > 3) ondas.shift();
      depositar(x, y, 2.4);
    });

    // --- estado ---
    let estado = "espera";
    let destino = "espera";
    let troca = 1;

    let ruido = ESTADOS.espera.ruido;
    let pressa = ESTADOS.espera.pressa;
    let brilhoEstado = ESTADOS.espera.brilho;
    let matiz = ESTADOS.espera.matiz;

    let demo = false, relogioDemo = 0, k = 0;
    let esforco = 0, esforcoAlvo = 0;
    let nivel = 0, nivelAlvo = 0, nivelExterno = false, nivelEm = 0;

    let giroY = 0, giroX = 0, rodaY = 0;
    let t = 0, rodando = true;

    let usadas = N;
    let somaMs = 0, quadros = 0, ultimoAjuste = 0;

    alvosDe(ESTADOS.espera.forma);

    function pintar(x, y, forca, quente, largo) {
      const ix = x | 0, iy = y | 0;
      if (ix < 2 || iy < 2 || ix >= L - 2 || iy >= A - 2) return;

      const base = iy * L + ix;
      acc[base] += forca;
      calor[base] += forca * quente;
      tocados[nTocados++] = base;

      const meio = forca * (largo ? 0.46 : 0.26);
      const mq = meio * quente;

      acc[base - 1] += meio; calor[base - 1] += mq; tocados[nTocados++] = base - 1;
      acc[base + 1] += meio; calor[base + 1] += mq; tocados[nTocados++] = base + 1;
      acc[base - L] += meio; calor[base - L] += mq; tocados[nTocados++] = base - L;
      acc[base + L] += meio; calor[base + L] += mq; tocados[nTocados++] = base + L;
    }

    function quadro() {
      if (!rodando) return;
      global.requestAnimationFrame(quadro);
      if (global.document && global.document.hidden) return;

      const comeco = (global.performance || Date).now();
      const dt = 0.016;
      t += dt;

      // Big Bang: avanca a expansao (~0,9 s) e suaviza com smoothstep.
      // So comeca quando a janela aparece (comecouAbertura).
      if (entrada < 1 && comecouAbertura)
        entrada = Math.min(1, entrada + dt / 0.9);
      const ent = entrada < 1 ? entrada * entrada * (3 - 2 * entrada) : 1;

      const cfgDest = ESTADOS[destino] || ESTADOS.espera;
      ruido += (cfgDest.ruido - ruido) * 0.04;
      pressa += (cfgDest.pressa - pressa) * 0.04;
      brilhoEstado += (cfgDest.brilho - brilhoEstado) * 0.05;
      matiz += (cfgDest.matiz - matiz) * 0.04;
      esforco += (esforcoAlvo - esforco) * 0.05;

      if (nivelExterno && comeco - nivelEm > 900) nivelExterno = false;

      if (!nivelExterno) {
        nivelAlvo = (destino === "falando" || destino === "ouvindo")
          ? 0.3 + 0.3 * Math.abs(Math.sin(t * 6.2) * Math.sin(t * 2.3))
          : 0;
      }

      nivel += (nivelAlvo - nivel) * 0.2;

      if (troca < 1) {
        troca = Math.min(1, troca + dt * 0.55 * Math.min(2, pressa));
        if (troca >= 1) estado = destino;
      } else if (demo) {
        relogioDemo += dt;

        if (relogioDemo > cfg.segundosNaDemo) {
          relogioDemo = 0;
          k = (k + 1) % NOMES.length;
          destino = NOMES[k];
          troca = 0;
        }
      }

      // Na metade da travessia elas se revoltam, e so depois assentam.
      const revolta = troca < 1 ? Math.sin(troca * Math.PI) : 0;

      giroY += (alvoGiroY - giroY) * 0.045;
      giroX += (alvoGiroX - giroX) * 0.045;

      const kk = devagar ? 0.3 : 1;
      const chata = PLANAS.has(cfgDest.forma);

      if (chata) {
        // Volta a face para a frente, pela volta inteira mais
        // proxima, e fica so balancando.
        const frente = Math.round(rodaY / 6.283185307) * 6.283185307;
        rodaY += (frente - rodaY) * 0.05;
      } else {
        rodaY += dt * 0.17 * pressa * kk;
      }

      const oy = giroY + rodaY
        + (chata ? Math.sin(t * 0.5) * 0.24 * kk : 0);
      const ox = giroX + Math.sin(t * 0.21 * kk) * (chata ? 0.07 : 0.14);
      const cosY = Math.cos(oy), senY = Math.sin(oy);
      const cosX = Math.cos(ox), senX = Math.sin(ox);

      moerCampo(t);

      for (let i = 0; i < trilha.length; i++) trilha[i] *= 0.93;

      for (let o = ondas.length - 1; o >= 0; o--) {
        ondas[o].idade += dt;
        if (ondas[o].idade > 1.5) ondas.splice(o, 1);
      }

      acc.fill(0);
      calor.fill(0);
      nTocados = 0;

      const cx = L / 2, cy = A / 2;
      const R = Math.min(L, A) * 0.62;
      const foco = cfg.foco;

      const de = alvosDe((ESTADOS[estado] || ESTADOS.espera).forma);
      const para = alvosDe(cfgDest.forma);
      const ax = de[0], ay = de[1], az = de[2];
      const bx = para[0], by = para[1], bz = para[2];
      const misturando = troca < 1;

      // Respiro continuo: mesmo assentada, a forma pulsa e se torce. A
      // respiracao de repouso e lenta e um pouco mais funda (vida sem
      // poluir), e a voz faz a nuvem AVANCAR de verdade -- so se move
      // quando ha som, entao nao vira ruido visual.
      const pulso = 1 + Math.sin(t * 0.62) * 0.055 + nivel * 0.24;
      const torcao = Math.sin(t * 0.37) * 0.35;

      const mola = 0.085 * Math.min(2.2, pressa);
      const amort = 0.905;
      const forcaRuido = (0.0006 + esforco * 0.0022) * ruido;
      const passoP = usadas >= N ? 1 : N / usadas;

      for (let s = 0, ff = 0; s < usadas; s++, ff += passoP) {
        const i = ff | 0;

        let tx = ax[i], ty = ay[i], tz = az[i];

        if (misturando) {
          tx += (bx[i] - tx) * troca;
          ty += (by[i] - ty) * troca;
          tz += (bz[i] - tz) * troca;
        }

        const ang = torcao * ty;
        const ca = Math.cos(ang), sa = Math.sin(ang);
        const rx2 = tx * ca - tz * sa;
        const rz2 = tx * sa + tz * ca;

        tx = rx2 * pulso;
        ty = ty * pulso;
        tz = rz2 * pulso;

        let fx = (tx - px[i]) * mola;
        let fy = (ty - py[i]) * mola;
        let fz = (tz - pz[i]) * mola;

        // campo de fluxo, interpolado entre as quatro celulas: lendo
        // a celula inteira, a malha aparecia na tela como grade.
        const fu = (px[i] + 1.1) * 0.4545 * GRADE;
        const fv = (py[i] + 1.1) * 0.4545 * GRADE;
        const ci = fu | 0, cj = fv | 0;

        if (ci >= 0 && ci < GRADE - 1 && cj >= 0 && cj < GRADE - 1) {
          const su = fu - ci, sv = fv - cj;
          const k0 = cj * GRADE + ci, k1 = k0 + 1;
          const k2 = k0 + GRADE, k3 = k2 + 1;
          const a0 = (1 - su) * (1 - sv), a1 = su * (1 - sv);
          const a2 = (1 - su) * sv, a3 = su * sv;
          const g = forcaRuido * (1 + revolta * 3.2);

          fx += (campoX[k0] * a0 + campoX[k1] * a1
               + campoX[k2] * a2 + campoX[k3] * a3) * g;
          fy += (campoY[k0] * a0 + campoY[k1] * a1
               + campoY[k2] * a2 + campoY[k3] * a3) * g;
          fz += (campoZ[k0] * a0 + campoZ[k1] * a1
               + campoZ[k2] * a2 + campoZ[k3] * a3) * g * 0.6;
        }

        const ti = (((px[i] + 0.9) / 1.8) * TRILHA) | 0;
        const tj = (((0.9 - py[i]) / 1.8) * TRILHA) | 0;

        if (ti >= 0 && ti < TRILHA && tj >= 0 && tj < TRILHA) {
          const kt = tj * TRILHA + ti;
          const v = trilha[kt];

          if (v > 0.01) {
            fx -= trilhaX[kt] * v * 0.026;
            fy -= trilhaY[kt] * v * 0.026;
            fz += v * 0.020;
          }
        }

        for (let o = 0; o < ondas.length; o++) {
          const w = ondas[o];
          const raio = w.idade * 1.6;
          const dx = px[i] - w.x, dy = py[i] - w.y;
          const d = Math.sqrt(dx * dx + dy * dy) + 0.0001;
          const faixa = Math.abs(d - raio);

          if (faixa < 0.15) {
            const f2 = (1 - faixa / 0.15) * (1 - w.idade / 1.5) * 0.034;
            fx += (dx / d) * f2;
            fy += (dy / d) * f2;
          }
        }

        vx[i] = (vx[i] + fx) * amort;
        vy[i] = (vy[i] + fy) * amort;
        vz[i] = (vz[i] + fz) * amort;

        px[i] += vx[i];
        py[i] += vy[i];
        pz[i] += vz[i];

        const x = px[i], y = py[i], z = pz[i];
        const qx = x * cosY + z * senY;
        let qz = -x * senY + z * cosY;
        const qy = y * cosX - qz * senX;
        qz = y * senX + qz * cosX;

        const escala = foco / (foco + qz);
        const sx = cx + qx * escala * R * ent;
        const sy = cy - qy * escala * R * ent;

        // A COR soma tres coisas: a profundidade pinta o volume
        // (longe azul, perto vermelho), a energia acende quem esta
        // voando, e o estado empurra a paleta para o seu lado.
        const vel = Math.abs(vx[i]) + Math.abs(vy[i]) + Math.abs(vz[i]);
        let energia = vel * 24;
        if (energia > 1) energia = 1;

        let quente = (0.92 - qz) * 0.50 + energia * 0.62 + matiz;
        if (quente < 0) quente = 0;
        else if (quente > 1) quente = 1;

        const desfoque = Math.abs(qz - 0.05);
        const perto = (1.25 - qz) * 0.5;

        pintar(
          sx, sy,
          (0.17 + perto * 0.56) * escala * brilhoEstado / (1 + desfoque * 1.2),
          quente,
          desfoque > 0.5 || energia > 0.5
        );
      }

      buf32.fill(0xff000000);

      const c0r = PALETA[0][0], c0g = PALETA[0][1], c0b = PALETA[0][2];
      const c1r = PALETA[1][0], c1g = PALETA[1][1], c1b = PALETA[1][2];
      const c2r = PALETA[2][0], c2g = PALETA[2][1], c2b = PALETA[2][2];

      for (let n = 0; n < nTocados; n++) {
        const p = tocados[n];
        const v = acc[p];
        if (v <= 0.004) continue;

        const h = calor[p] / v;
        acc[p] = 0;
        calor[p] = 0;

        let cr, cg, cb;

        if (h < 0.5) {
          const u = h * 2;
          cr = c0r + (c1r - c0r) * u;
          cg = c0g + (c1g - c0g) * u;
          cb = c0b + (c1b - c0b) * u;
        } else {
          const u = (h - 0.5) * 2;
          cr = c1r + (c2r - c1r) * u;
          cg = c1g + (c2g - c1g) * u;
          cb = c1b + (c2b - c1b) * u;
        }

        const base = v > 1 ? 1 : v;
        const extra = v > 1 ? (v - 1) * 0.45 : 0;
        const e = extra > 1 ? 1 : extra;

        const r = cr * base + 255 * e;
        const g = cg * base + 255 * e;
        const b = cb * base + 255 * e;

        buf32[p] = 0xff000000
          | ((b > 255 ? 255 : b) << 16)
          | ((g > 255 ? 255 : g) << 8)
          | (r > 255 ? 255 : r);
      }

      ctx.putImageData(buffer, 0, 0);

      somaMs += (global.performance || Date).now() - comeco;
      quadros++;

      if (quadros >= 45) {
        const media = somaMs / quadros;
        somaMs = 0; quadros = 0;

        if (comeco - ultimoAjuste > 1500) {
          if (media > 12 && usadas > cfg.minimo) {
            usadas = Math.max(cfg.minimo, (usadas * 0.75) | 0);
            ultimoAjuste = comeco;
          } else if (media < 6 && usadas < N) {
            usadas = Math.min(N, (usadas * 1.15) | 0);
            ultimoAjuste = comeco;
          }
        }
      }
    }

    global.requestAnimationFrame(quadro);

    function ir(nome) {
      if (!ESTADOS[nome] || nome === destino) return false;

      // Ja prepara os alvos ANTES de comecar a viagem: montar 30 mil
      // pontos no meio da travessia daria um engasgo bem na hora em
      // que a animacao precisa estar lisa.
      alvosDe(ESTADOS[nome].forma);

      destino = nome;
      troca = 0;
      relogioDemo = 0;
      k = NOMES.indexOf(nome);
      return true;
    }

    return {
      /** Um dos 19 estados. */
      setEstado: ir,

      /**
       * O nome da ferramenta que esta rodando, igual ao que o
       * nebell.py ja usa. Desconhecida cai em "pensando".
       */
      paraFerramenta(nome) {
        return ir(DA_FERRAMENTA[nome] || "pensando");
      },

      // nomes antigos, para o Python nao precisar mudar
      setState(nome) {
        const de = {
          idle: "espera", listening: "ouvindo",
          thinking: "pensando", speaking: "falando",
        };
        return ir(de[nome] || nome);
      },

      setLevel(v) {
        nivelExterno = true;
        nivelEm = (global.performance || Date).now();
        nivelAlvo = Math.max(0, Math.min(1, Number(v) || 0));
      },

      setEsforco(v) { esforcoAlvo = Math.max(0, Math.min(1, Number(v) || 0)); },

      demonstrar(ligado) {
        demo = !!ligado;
        relogioDemo = 0;
      },

      proximo() {
        k = (NOMES.indexOf(destino) + 1) % NOMES.length;
        ir(NOMES[k]);
      },

      explodir(x, y) {
        ondas.push({ x: x || 0, y: y || 0, idade: 0 });
        if (ondas.length > 3) ondas.shift();
      },

      medir,
      parar() { rodando = false; },

      get numeros() {
        const c = ESTADOS[destino] || ESTADOS.espera;
        return {
          total: N, usadas, demo,
          estado: destino,
          rotulo: c.rotulo,
          diz: c.diz,
          forma: c.forma,
          viajando: troca < 1,
          prontas: Object.keys(cache).length,
        };
      },
    };
  }

  global.NebellFormas = {
    criar, ESTADOS, FORMAS, PALETA,
    nomes: NOMES,
    daFerramenta: DA_FERRAMENTA,
  };
})(typeof window !== "undefined" ? window : this);
