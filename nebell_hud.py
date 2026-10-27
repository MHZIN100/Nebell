"""
Ponte entre o NEBELL e a interface HUD.

A interface e uma pagina HTML aberta em uma janela do pywebview. Este
modulo cuida dos dois lados da conversa:

  Python -> pagina   estado, mensagens, estatisticas, lista de microfones
  pagina -> Python   texto digitado, troca de microfone, botao de parar

Se o pywebview nao estiver instalado, nada aqui falha: `available()`
devolve False e o NEBELL segue no console como antes.

O arquivo hud/index.html e gravado apenas quando nao existe, para que
voce possa editar a interface sem que a proxima execucao sobrescreva.
"""

import json
import re
import shutil
import threading
import time
from pathlib import Path

try:
    import webview
except Exception:
    webview = None


WINDOW_TITLE = "N.E.B.E.L.L."

# Versao da pagina embutida. Sobe a cada mudanca na HUD_HTML.
#
# Existe porque `ensure_html` so gravava a pagina quando ela NAO existia:
# quem ja tinha um hud/index.html de uma versao anterior nunca recebia
# as mudancas novas. Foi o que aconteceu com o botao ARQUIVO, que estava
# no codigo e nao aparecia na janela.
HUD_VERSAO = 6
MARCA_DE_VERSAO = "nebell-hud-versao"
WINDOW_WIDTH = 1180
WINDOW_HEIGHT = 720
BACKGROUND = "#02070d"


def available():
    return webview is not None


class HudBridge:
    """
    Fala com a pagina. Todas as chamadas sao seguras de usar mesmo
    quando a janela ainda nao abriu ou nunca vai abrir: elas ficam
    guardadas e saem quando a pagina avisar que esta pronta.
    """

    def __init__(self, html_path, log=print):
        self.html_path = Path(html_path)
        self.log = log

        self.window = None
        self.active = False
        self.page_ready = False

        self.on_submit = None
        self.on_set_mic = None
        self.on_stop = None
        self.on_ready = None
        self.on_files = None

        self._pending = []
        self._lock = threading.Lock()
        self._last_state = None

    # --------------------------------------------------------
    # Lado da pagina chamando o Python
    # --------------------------------------------------------

    class Api:
        def __init__(self, bridge):
            self._bridge = bridge

        def send(self, text):
            bridge = self._bridge

            if bridge.on_submit:
                threading.Thread(
                    target=bridge.on_submit, args=(str(text),), daemon=True
                ).start()

            return True

        def set_mic(self, spec):
            bridge = self._bridge

            if bridge.on_set_mic:
                threading.Thread(
                    target=bridge.on_set_mic, args=(str(spec),), daemon=True
                ).start()

            return True

        def stop(self):
            if self._bridge.on_stop:
                self._bridge.on_stop()

            return True

        def pick_files(self):
            """
            Abre o seletor de arquivos do sistema.

            Tem de ser o seletor NATIVO: o <input type=file> do HTML
            entrega o conteudo ao navegador, mas nao o caminho no disco,
            e sem o caminho o NEBELL nao consegue editar o arquivo
            depois. Devolve a lista de caminhos para a pagina mostrar.
            """
            bridge = self._bridge
            caminhos = bridge.escolher_arquivos()

            if caminhos and bridge.on_files:
                threading.Thread(
                    target=bridge.on_files, args=(caminhos,), daemon=True
                ).start()

            return caminhos

        def ready(self):
            """A pagina chama isto quando termina de carregar."""
            self._bridge.flush()

            if self._bridge.on_ready:
                threading.Thread(
                    target=self._bridge.on_ready, daemon=True
                ).start()

            return True

    # --------------------------------------------------------
    # Janela
    # --------------------------------------------------------

    def versao_no_disco(self):
        """
        A versao da pagina que esta gravada. 0 quando nao ha marca.

        Pagina sem marca e de antes deste controle existir, entao conta
        como a mais velha de todas.
        """
        try:
            texto = self.html_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return 0

        achado = re.search(
            rf'{MARCA_DE_VERSAO}"\s+content="(\d+)"', texto
        )

        return int(achado.group(1)) if achado else 0

    def ensure_html(self):
        """
        Garante que a pagina no disco seja a desta versao.

        Quando a do disco e mais velha, ela e guardada ao lado como
        .anterior.html antes de ser trocada: se a pessoa tinha editado a
        pagina a mao, o trabalho dela nao se perde.
        """
        if not self.html_path.is_file():
            self.html_path.parent.mkdir(parents=True, exist_ok=True)
            self.html_path.write_text(HUD_HTML, encoding="utf-8")
            return self.html_path

        no_disco = self.versao_no_disco()

        if no_disco >= HUD_VERSAO:
            return self.html_path

        guardada = self.html_path.with_suffix(".anterior.html")

        try:
            shutil.copy2(self.html_path, guardada)
        except Exception as exc:
            self.log(f"[HUD] Não consegui guardar a página antiga: {exc}")

        try:
            self.html_path.write_text(HUD_HTML, encoding="utf-8")
        except Exception as exc:
            self.log(f"[HUD] Não consegui atualizar a página: {exc}")
            return self.html_path

        self.log(
            f"[HUD] Página atualizada (versão {no_disco or 'antiga'} -> "
            f"{HUD_VERSAO}). A anterior ficou em {guardada.name}."
        )
        return self.html_path

    def create(self):
        if not available():
            return False

        self.ensure_html()

        self.window = webview.create_window(
            WINDOW_TITLE,
            url=self.html_path.resolve().as_uri(),
            js_api=self.Api(self),
            width=WINDOW_WIDTH,
            height=WINDOW_HEIGHT,
            background_color=BACKGROUND,
            text_select=True,
        )
        self.active = True
        return True

    def run(self, worker):
        """
        Abre a janela e roda `worker` em paralelo.

        O pywebview exige a thread principal, por isso o NEBELL passa a
        viver na thread de trabalho.
        """
        if not self.active:
            return False

        # Rede de seguranca: se a pagina nao chamar ready(), libera
        # as mensagens guardadas depois de um instante.
        def destravar():
            time.sleep(2.5)
            self.flush()

        threading.Thread(target=destravar, daemon=True).start()

        webview.start(worker, self.window, debug=False)
        return True

    def escolher_arquivos(self):
        """
        Abre o seletor nativo e devolve os caminhos escolhidos.

        Lista vazia quando a pessoa cancela ou quando a janela nao esta
        de pe. Devolve CAMINHOS, nao conteudo: e o caminho que permite
        ao NEBELL ler, editar e gravar o arquivo depois.
        """
        if self.window is None or webview is None:
            return []

        try:
            escolhidos = self.window.create_file_dialog(
                webview.OPEN_DIALOG, allow_multiple=True
            )

        except Exception as exc:
            self.log(f"[HUD] Não consegui abrir o seletor: {exc}")
            return []

        if not escolhidos:
            return []

        # Versões diferentes devolvem tupla, lista ou um texto só.
        if isinstance(escolhidos, (str, bytes)):
            escolhidos = [escolhidos]

        return [str(caminho) for caminho in escolhidos if caminho]

    def destroy(self):
        self.active = False

        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass

    # --------------------------------------------------------
    # Python chamando a pagina
    # --------------------------------------------------------

    def _run_js(self, codigo):
        if not (self.active and self.window is not None):
            return False

        try:
            self.window.evaluate_js(codigo)
            return True
        except Exception:
            return False

    def call(self, metodo, *args):
        """Chama window.nebellUI.<metodo>(...) na pagina."""
        if not self.active:
            return False

        argumentos = ",".join(json.dumps(a, ensure_ascii=False) for a in args)
        codigo = (
            f"window.nebellUI&&window.nebellUI.{metodo}"
            f"&&window.nebellUI.{metodo}({argumentos})"
        )

        with self._lock:
            if not self.page_ready:
                self._pending.append(codigo)

                if len(self._pending) > 200:
                    del self._pending[:-200]

                return True

        return self._run_js(codigo)

    def flush(self):
        """Solta o que ficou guardado antes da pagina abrir."""
        with self._lock:
            if self.page_ready:
                return

            self.page_ready = True
            guardados = list(self._pending)
            self._pending.clear()

        for codigo in guardados:
            self._run_js(codigo)

    # --------------------------------------------------------
    # Atalhos
    # --------------------------------------------------------

    def set_state(self, estado):
        if estado == self._last_state:
            return

        self._last_state = estado
        self.call("setState", estado)

    def add_message(self, papel, texto):
        texto = (texto or "").strip()

        if texto:
            self.call("addMessage", papel, texto)

    def set_level(self, valor):
        self.call("setLevel", float(valor))

    def para_ferramenta(self, nome):
        """
        Mostra a forma da ferramenta que esta rodando agora.

        O nome e o mesmo que o nebell.py ja usa em
        O_QUE_ESTA_FAZENDO, entao nao ha tabela nova para manter:
        quem nao conhece cai em "pensando".
        """
        nome = (nome or "").strip()

        if not nome or nome == self._last_state:
            return

        self._last_state = nome
        self.call("paraFerramenta", nome)

    def set_esforco(self, valor):
        """0 = folgada, 1 = penando. A nuvem ferve conforme sobe."""
        self.call("setEsforco", float(valor))

    def stream_message(self, texto):
        """
        Mostra o texto que esta sendo gerado, na hora.

        A bolha e criada na primeira chamada e so atualizada nas
        seguintes, em vez de uma mensagem nova por pedaco.
        """
        self.call("streamMessage", str(texto or ""))

    def fechar_stream(self):
        """Fecha a bolha em andamento, tirando o cursor piscando."""
        self.call("fecharStream")

    def trabalhando(self, texto=""):
        """A linha de 'trabalhando nisso'. Texto vazio apaga a linha."""
        self.call("trabalhando", str(texto or ""))

    def set_stats(self, **campos):
        dados = {k: v for k, v in campos.items() if v is not None}

        if dados:
            self.call("setStats", dados)

    def set_mics(self, dispositivos, atual=None):
        self.call("setMics", dispositivos, atual)

    def notice(self, texto):
        self.add_message("nebell", texto)


# ============================================================
# PAGINA PADRAO
# ============================================================
# Mantem o desenho original da HUD. As adicoes sao o seletor de
# microfone, os botoes ARQUIVO e PARAR no rodape, as linhas de
# microfone, reconhecimento e GPU no painel da esquerda, e o aviso
# ready() ao Python.

HUD_HTML = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="nebell-hud-versao" content="__VERSAO__">
<title>N.E.B.E.L.L.</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700&family=Share+Tech+Mono&display=swap">
<style>
:root{--bg:#04030c;--panel:rgba(26,10,52,.5);--line:rgba(150,60,245,.28);--text:#d8c8ff;--dim:#8a76b8;--acc:#9b4bff;
 box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#04030c;--text:#d8c8ff}}
:root[data-theme="dark"]{--bg:#04030c;--text:#d8c8ff}
html{scroll-padding-top:env(safe-area-inset-top,0px)}
*{box-sizing:border-box}
html,body{height:100%;margin:0}
body{background:var(--bg);color:var(--text);font:14px/1.45 "Share Tech Mono",ui-monospace,Consolas,monospace;overflow:hidden;position:relative}
body::before{content:"";position:absolute;inset:0;background:
 radial-gradient(ellipse at center,rgba(90,30,170,.22),transparent 65%),
 linear-gradient(rgba(150,60,245,.045) 1px,transparent 1px) 0 0/48px 48px,
 linear-gradient(90deg,rgba(150,60,245,.045) 1px,transparent 1px) 0 0/48px 48px;pointer-events:none}
body::after{content:"";position:absolute;inset:0;background:repeating-linear-gradient(transparent 0 2px,rgba(0,0,0,.18) 2px 3px);pointer-events:none}
body[data-state="thinking"]{--acc:#ff4d7a;--line:rgba(255,77,122,.35)}
body[data-state="trabalhando"]{--acc:#4a86ff;--line:rgba(74,134,255,.32)}
body[data-state="alerta"]{--acc:#ff305c;--line:rgba(255,48,92,.42)}
.app{position:relative;z-index:1;height:100%;display:grid;grid-template-rows:auto 1fr auto;gap:12px;padding:14px 18px}
header{display:flex;justify-content:space-between;align-items:center;font-family:Orbitron,sans-serif;letter-spacing:.3em}
header h1{margin:0;font-size:20px;font-weight:700;color:var(--acc);text-shadow:0 0 14px var(--acc)}
.clock{text-align:right;font-size:12px;color:var(--dim);letter-spacing:.15em}.clock b{display:block;font-size:18px;color:var(--text);font-weight:500}
main{display:grid;grid-template-columns:250px 1fr 310px;gap:16px;min-height:0}
.panel{position:relative;background:var(--panel);border:1px solid var(--line);padding:14px;backdrop-filter:blur(4px);min-height:0;display:flex;flex-direction:column}
.panel::before,.panel::after{content:"";position:absolute;width:14px;height:14px;border:2px solid var(--acc)}
.panel::before{top:-1px;left:-1px;border-right:0;border-bottom:0}.panel::after{bottom:-1px;right:-1px;border-left:0;border-top:0}
.panel h2{margin:0 0 12px;font:500 11px Orbitron,sans-serif;letter-spacing:.25em;color:var(--acc)}
.stat{margin-bottom:14px}.stat div{display:flex;justify-content:space-between;gap:8px;font-size:12px;color:var(--dim)}
.stat span+span{color:var(--text);text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar{height:6px;margin-top:5px;background:rgba(150,60,245,.14);position:relative}
.bar i{position:absolute;inset:0 auto 0 0;width:0;background:var(--acc);box-shadow:0 0 10px var(--acc);transition:width .8s}
#gpu{background:linear-gradient(90deg,#286eff,#963cf5,#ff305c)}
.center{display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:0}
#hud{width:100%;flex:1;min-height:0}
#state{font:700 15px Orbitron,sans-serif;letter-spacing:.45em;color:var(--acc);text-shadow:0 0 12px var(--acc);margin:4px 0 2px}
#sub{color:var(--dim);font-size:12px;letter-spacing:.2em}
#log{flex:1;overflow:auto;display:flex;flex-direction:column;gap:10px;font-size:13px;padding-right:4px}
.msg{border-left:2px solid var(--line);padding-left:10px}.msg small{display:block;color:var(--dim);font-size:10px;letter-spacing:.2em}
.msg.nebell{border-color:var(--acc)}.msg.nebell small{color:var(--acc)}
/* Bolha ainda sendo escrita: cursor piscando no fim do texto. */
.msg.streaming>div:last-child::after{content:"\u258a";color:var(--acc);animation:pisca 1s steps(2) infinite}
@keyframes pisca{50%{opacity:0}}
@media (prefers-reduced-motion:reduce){.msg.streaming>div:last-child::after{animation:none}}
/* Linha de "trabalhando nisso", abaixo do estado no centro. */
#work{margin-top:8px;color:var(--warn,#ffb020);font-size:12px;letter-spacing:.12em;min-height:16px;opacity:0;transition:opacity .2s}
#work.on{opacity:1}
footer{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.in{flex:1;min-width:240px;display:flex;align-items:center;gap:10px;border:1px solid var(--line);background:var(--panel);padding:0 14px}
.in span{color:var(--acc)}
input{flex:1;background:none;border:0;outline:0;color:var(--text);font:inherit;padding:13px 0}
button{background:var(--panel);color:var(--acc);border:1px solid var(--line);font:500 11px Orbitron,sans-serif;letter-spacing:.15em;padding:12px 14px;cursor:pointer}
button:hover{background:rgba(150,60,245,.2)}
#file{border-color:rgba(150,60,245,.5)}
#file:hover{background:rgba(150,60,245,.2)}
#file:disabled{opacity:.5;cursor:default}
#halt{border-color:rgba(255,120,120,.5);color:#ff9b9b}
#halt:hover{background:rgba(255,120,120,.15)}
select{background:var(--panel);color:var(--text);border:1px solid var(--line);font:11px "Share Tech Mono",monospace;padding:12px 10px;max-width:280px;outline:0;cursor:pointer}
select:focus{border-color:var(--acc)}
#demo{display:flex;gap:6px;flex-wrap:wrap}#demo button{padding:9px 10px;font-size:10px}
@media (max-width:860px){body{overflow:auto}.app{height:auto;min-height:100%}main{grid-template-columns:1fr}.center{order:-1}#hud{flex:none;aspect-ratio:1;max-height:70vh}.panel{min-height:200px}#log{max-height:260px}footer{flex-wrap:wrap}}
@media (prefers-reduced-motion:reduce){.bar i{transition:none}}
</style>
</head>
<body data-state="idle">
<div class="app">
 <header><h1>N.E.B.E.L.L.</h1><div class="clock"><b id="clk">--:--:--</b><span id="dt"></span></div></header>
 <main>
  <section class="panel"><h2>SISTEMA</h2>
   <div class="stat"><div><span>CPU</span><span id="cpuV">--</span></div><div class="bar"><i id="cpu"></i></div></div>
   <div class="stat"><div><span>MEMÓRIA</span><span id="ramV">--</span></div><div class="bar"><i id="ram"></i></div></div>
   <div class="stat"><div><span>GPU</span><span id="gpuV">--</span></div><div class="bar"><i id="gpu"></i></div></div>
   <div class="stat"><div><span>REDE</span><span id="netV">--</span></div><div class="bar"><i id="net"></i></div></div>
   <div class="stat"><div><span>MODELO</span><span id="mdl">qwen3.5:4b</span></div></div>
   <div class="stat"><div><span>VOZ</span><span id="voz">Piper · nebell</span></div></div>
   <div class="stat"><div><span>RECONHECIMENTO</span><span id="stt">--</span></div></div>
   <div class="stat"><div><span>MICROFONE</span><span id="micV">--</span></div></div>
   <div class="stat"><div><span>LOCAL</span><span id="loc">--</span></div></div>
  </section>
  <section class="center"><canvas id="hud"></canvas><div id="state">EM ESPERA</div><div id="sub">DIGA "NEBELL" PARA COMEÇAR</div><div id="work"></div></section>
  <section class="panel"><h2>REGISTRO</h2><div id="log"></div></section>
 </main>
 <footer>
  <div class="in"><span>&gt;</span><input id="txt" placeholder="Digite uma mensagem e pressione Enter" autocomplete="off"></div>
  <select id="mic" title="Microfone de entrada"><option value="auto">MICROFONE: AUTOMÁTICO</option></select>
  <button id="file" title="Enviar um arquivo ou imagem para o NEBELL">ARQUIVO</button>
  <button id="halt" title="Interrompe a fala e a geração">PARAR</button>
 </footer>
</div>
<script>
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
    espera:     { forma: "giroscopio", rotulo: "EM ESPERA",       diz: "aguardando você",             matiz: -0.22, ruido: 0.5, pressa: 0.75, brilho: 0.92 },
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

      // Respiro continuo: mesmo assentada, a forma pulsa e se torce.
      const pulso = 1 + Math.sin(t * 0.8) * 0.045 + nivel * 0.1;
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
        const sx = cx + qx * escala * R;
        const sy = cy - qy * escala * R;

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
</script>
<script>
(()=>{
const $=s=>document.querySelector(s), cv=$('#hud');
const reduce=matchMedia('(prefers-reduced-motion:reduce)').matches;
// O nucleo e a nuvem de particulas: cada forma e um estado, e o
// mapa das ferramentas sai do proprio nebell.py.
const nucleo=NebellFormas.criar(cv,{particulas:30000});
let demo=true;

// Para o fundo da janela mudar de cor junto com o estado.
const FAMILIA={espera:'idle',ouvindo:'listening',pensando:'thinking',
 falando:'speaking',alerta:'alerta',erro:'alerta',encerrando:'idle'};

function bridge(){return window.pywebview&&window.pywebview.api?window.pywebview.api:null}

function setState(s){
 if(!nucleo.setState(s))return;
 const n=nucleo.numeros;
 $('#state').textContent=n.rotulo;
 $('#sub').textContent=n.diz;
 document.body.dataset.state=FAMILIA[n.estado]||'trabalhando'}
function addMessage(role,text){fecharStream();const d=document.createElement('div');d.className='msg '+(role==='user'?'user':'nebell');
 const t=new Date().toLocaleTimeString('pt-BR');const sm=document.createElement('small');sm.textContent=(role==='user'?'VOCÊ':'NEBELL')+' · '+t;
 const p=document.createElement('div');p.textContent=text;d.append(sm,p);const log=$('#log');log.append(d);
 while(log.children.length>60)log.firstChild.remove();log.scrollTop=log.scrollHeight}

// Bolha que se preenche enquanto ele gera. Antes o texto so aparecia
// no fim, depois de ele terminar de falar: quem olhava a janela nao
// sabia se tinha algo acontecendo.
let streamP=null;
function streamMessage(text){
 const log=$('#log');
 if(!streamP){
  const d=document.createElement('div');d.className='msg nebell streaming';
  const t=new Date().toLocaleTimeString('pt-BR');
  const sm=document.createElement('small');sm.textContent='NEBELL · '+t;
  streamP=document.createElement('div');
  d.append(sm,streamP);log.append(d);
  while(log.children.length>60)log.firstChild.remove();
 }
 streamP.textContent=text;
 log.scrollTop=log.scrollHeight}
function fecharStream(){
 if(streamP){const d=streamP.parentElement;if(d)d.classList.remove('streaming');streamP=null}}
function trabalhando(text){
 const el=$('#work');
 if(!el)return;
 if(text){el.textContent=text;el.classList.add('on')}
 else{el.textContent='';el.classList.remove('on')}}
function setStats(o){for(const k of['cpu','ram','net','gpu']){if(o[k]==null)continue;const v=Math.max(0,Math.min(100,o[k]));
 $('#'+k).style.width=v+'%';
 const rotulo=o[k+'Label'];$('#'+k+'V').textContent=rotulo||Math.round(v)+'%'}
 if(o.netLabel&&o.net==null)$('#netV').textContent=o.netLabel;
 if(o.gpuLabel&&o.gpu==null)$('#gpuV').textContent=o.gpuLabel;
 if(o.model)$('#mdl').textContent=o.model;
 if(o.voice)$('#voz').textContent=o.voice;
 if(o.stt)$('#stt').textContent=o.stt;
 if(o.mic)$('#micV').textContent=o.mic;
 if(o.location)$('#loc').textContent=o.location}
function setMics(list,current){const sel=$('#mic');if(!Array.isArray(list))return;
 sel.textContent='';const auto=document.createElement('option');auto.value='auto';auto.textContent='MICROFONE: AUTOMÁTICO';sel.append(auto);
 for(const d of list){const o=document.createElement('option');o.value=String(d.index);
  o.textContent=(d.is_headset?'FONE · ':'')+(d.name||('entrada '+d.index));sel.append(o)}
 if(current!=null)sel.value=String(current)}
function submit(text){text=text.trim();if(!text)return;addMessage('user',text);
 const b=bridge();
 if(b&&b.send){demo=false;setState('pensando');b.send(text)}
 else if(api.onSubmit)api.onSubmit(text);
 else{setState('pensando');setTimeout(()=>{setState('falando');addMessage('nebell','Modo demonstração, senhor. Estou pronto para ser conectado.');setTimeout(()=>setState('espera'),2200)},1100)}}
const api={
 setState:s=>{demo=false;setState(s)},
 // O Python manda o NOME DA FERRAMENTA que esta rodando; a forma
 // sai do mapa que ja existe no nebell.py.
 paraFerramenta:nome=>{demo=false;
  if(nucleo.paraFerramenta(nome)){const n=nucleo.numeros;
   $('#state').textContent=n.rotulo;$('#sub').textContent=n.diz;
   document.body.dataset.state=FAMILIA[n.estado]||'trabalhando'}},
 setEsforco:v=>nucleo.setEsforco(v),
 setLevel:v=>nucleo.setLevel(v),
 addMessage,streamMessage,fecharStream,trabalhando,setStats,setMics,
 onSubmit:null,setDemo:v=>{demo=!!v}};
window.nebellUI=api;


// relógio e estatísticas simuladas (o Python substitui via setStats)
const days=['DOMINGO','SEGUNDA','TERÇA','QUARTA','QUINTA','SEXTA','SÁBADO'];
function tick(){const n=new Date();$('#clk').textContent=n.toLocaleTimeString('pt-BR');$('#dt').textContent=days[n.getDay()]+' · '+n.toLocaleDateString('pt-BR')}
tick();setInterval(tick,1000);
let fake=true;const _s=setStats;
// O ESFORCO da nuvem nao e inventado: sai da CPU e da placa que o
// Python ja manda para o painel. Penando, ela ferve.
function daCarga(o){
 const cpu=typeof o.cpu==='number'?o.cpu:null;
 const gpu=typeof o.gpu==='number'?o.gpu:null;
 if(cpu==null&&gpu==null)return;
 const pior=Math.max(cpu==null?0:cpu,gpu==null?0:gpu);
 nucleo.setEsforco(Math.max(0,Math.min(1,(pior-35)/55)))}
api.setStats=o=>{fake=false;_s(o);daCarga(o)};
setInterval(()=>{if(fake)_s({cpu:15+Math.random()*40,ram:45+Math.random()*10,gpu:5+Math.random()*50,net:10+Math.random()*60,netLabel:'24 ms'})},1500);

// controles
$('#txt').addEventListener('keydown',e=>{if(e.key==='Enter'){submit(e.target.value);e.target.value=''}});
$('#mic').addEventListener('change',e=>{const b=bridge();if(b&&b.set_mic)b.set_mic(e.target.value)});
$('#halt').addEventListener('click',()=>{const b=bridge();if(b&&b.stop)b.stop()});
// O seletor e o NATIVO, do lado do Python: o <input type=file> do HTML
// nao entrega o caminho no disco, e sem caminho o NEBELL nao consegue
// editar o arquivo depois.
$('#file').addEventListener('click',async()=>{
 const b=bridge(),bt=$('#file');
 if(!b||!b.pick_files){addMessage('nebell','O seletor de arquivos só funciona na janela do NEBELL, senhor.');return}
 bt.disabled=true;bt.textContent='ABRINDO...';
 try{
  const caminhos=await b.pick_files();
  if(caminhos&&caminhos.length){
   const nomes=caminhos.map(c=>String(c).split(/[\\/]/).pop());
   addMessage('user','Enviei: '+nomes.join(', '));
   setState('pensando');
  }
 }catch(e){addMessage('nebell','Não consegui abrir o seletor: '+e)}
 finally{bt.disabled=false;bt.textContent='ARQUIVO'}});
// Esc também interrompe
addEventListener('keydown',e=>{if(e.key==='Escape'){const b=bridge();if(b&&b.stop)b.stop()}});

// avisa o Python que a página carregou
function announce(){const b=bridge();if(b&&b.ready){demo=false;b.ready();return true}return false}
if(!announce()){let n=0;const h=setInterval(()=>{if(announce()||++n>40)clearInterval(h)},150)}

// demonstração: só roda enquanto o Python não assume
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{while(true){if(!demo){await sleep(500);continue}
 setState('espera');await sleep(2600);if(!demo)continue;
 setState('ouvindo');await sleep(2400);if(!demo)continue;
 addMessage('user','Nebell, que horas são?');setState('pensando');await sleep(1700);if(!demo)continue;
 setState('falando');addMessage('nebell','São dez horas e quinze minutos, senhor.');await sleep(3000);if(!demo)continue;
 setState('internet');await sleep(2200);if(!demo)continue;
 setState('visao');await sleep(2200);if(!demo)continue;
 setState('gravando');await sleep(2200)}})();
})();
</script>
</body>
</html>
"""


# A versao na pagina sai da constante, nao de um numero digitado
# dentro do HTML. Ja aconteceu de eu subir a constante e esquecer a
# marca, e aí a pagina nova nunca substituia a antiga no disco --
# ficava tudo igual sem explicacao. Agora nao da para discordarem.
HUD_HTML = HUD_HTML.replace("__VERSAO__", str(HUD_VERSAO))

