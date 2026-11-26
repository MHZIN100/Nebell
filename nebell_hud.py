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

# Versao da pagina. Sobe a cada mudanca em hud_fonte/ (os arquivos da
# pagina). A 15 marca a troca da pagina de um unico arquivo embutido
# para os arquivos separados (conteudo identico, so reorganizado).
#
# Existe porque `ensure_html` so gravava a pagina quando ela NAO existia:
# quem ja tinha um hud/index.html de uma versao anterior nunca recebia
# as mudancas novas. Foi o que aconteceu com o botao ARQUIVO, que estava
# no codigo e nao aparecia na janela.
HUD_VERSAO = 27
MARCA_DE_VERSAO = "nebell-hud-versao"
WINDOW_WIDTH = 1180
WINDOW_HEIGHT = 720
BACKGROUND = "#02070d"

# Fonte da pagina: HTML/CSS/JS em arquivos de verdade (faceis de editar),
# em hud_fonte/, ao lado deste modulo. No arranque, a HUD COPIA estes
# arquivos para hud/. O HUD_HTML (mais abaixo) e so uma costura destes
# mesmos arquivos num arquivo unico -- para um fallback e para os testes,
# que conferem marcadores nessa string. Assim a string nunca discorda do
# que roda de verdade.
FONTE_DIR = Path(__file__).resolve().parent / "hud_fonte"
_ASSETS = ("index.html", "estilo.css", "formas.js", "app.js")

# Animacao de abertura (big bang): as particulas nascem num ponto e se
# expandem. Ligada por padrao; o nebell.py a desliga a partir do
# nebell_config.json (big_bang). O valor entra no data-bigbang do body
# quando a pagina e gravada. (prefers-reduced-motion ja desliga no lado
# da pagina, independente disto.)
BIG_BANG = True


def _marcar_pagina(conteudo):
    """Troca os marcadores do index.html pelos valores desta sessao."""
    return (conteudo
            .replace("__VERSAO__", str(HUD_VERSAO))
            .replace("__BIGBANG__", "1" if BIG_BANG else "0"))


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
        self.on_set_esforco = None
        self.on_set_voz = None
        self.on_escutar = None          # HUD->Python: clique no microfone (falar)
        self.on_abrir_conversa = None   # HUD->Python: continuar uma conversa
        self.on_nova_conversa = None    # HUD->Python: comecar uma conversa nova
        self.obter_conversas = None     # HUD->Python: lista para o historico

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

        def set_esforco(self, nivel):
            """O botao ESFORCO da pagina: rapido / normal / alto."""
            bridge = self._bridge

            if bridge.on_set_esforco:
                threading.Thread(
                    target=bridge.on_set_esforco, args=(str(nivel),),
                    daemon=True,
                ).start()

            return True

        def set_voz(self, chave):
            """O seletor de voz da pagina: muda a voz em tempo real."""
            bridge = self._bridge

            if bridge.on_set_voz:
                threading.Thread(
                    target=bridge.on_set_voz, args=(str(chave),), daemon=True
                ).start()

            return True

        def escutar(self):
            """O botao de microfone (clique-para-falar) da pagina: abre a
            escuta por UMA fala; clicar de novo enquanto ouve cancela. A
            NEBELL nao escuta sozinha fora disso."""
            bridge = self._bridge

            if bridge.on_escutar:
                threading.Thread(
                    target=bridge.on_escutar, daemon=True
                ).start()

            return True

        def pedir_conversas(self):
            """A pagina pede a lista de conversas para o painel de
            historico. Devolve a lista na hora (como o pick_files)."""
            fn = self._bridge.obter_conversas

            try:
                return list(fn()) if fn else []
            except Exception:
                return []

        def abrir_conversa(self, id):
            """A pagina pediu para continuar uma conversa antiga."""
            bridge = self._bridge

            try:
                cid = int(id)
            except Exception:
                return False

            if bridge.on_abrir_conversa:
                threading.Thread(
                    target=bridge.on_abrir_conversa, args=(cid,), daemon=True
                ).start()

            return True

        def nova_conversa(self):
            """A pagina pediu para comecar uma conversa nova."""
            if self._bridge.on_nova_conversa:
                threading.Thread(
                    target=self._bridge.on_nova_conversa, daemon=True
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
        Garante que a pagina no disco (hud/) seja a desta versao.

        A pagina agora sao quatro arquivos (index.html, estilo.css,
        formas.js, app.js), copiados de hud_fonte/. Quando a do disco e
        mais velha, o index antigo e guardado ao lado como
        .anterior.html antes da troca: se a pessoa editou a mao, o
        trabalho dela nao se perde.
        """
        destino = self.html_path.parent
        no_disco = self.versao_no_disco() if self.html_path.is_file() else 0

        if no_disco >= HUD_VERSAO:
            return self.html_path

        if self.html_path.is_file():
            guardada = self.html_path.with_suffix(".anterior.html")
            try:
                shutil.copy2(self.html_path, guardada)
            except Exception as exc:
                self.log(f"[HUD] Não consegui guardar a página antiga: {exc}")

        try:
            destino.mkdir(parents=True, exist_ok=True)
            for nome in _ASSETS:
                conteudo = (FONTE_DIR / nome).read_text(encoding="utf-8")
                if nome == "index.html":
                    conteudo = _marcar_pagina(conteudo)
                (destino / nome).write_text(conteudo, encoding="utf-8")
        except Exception as exc:
            self.log(f"[HUD] Não consegui atualizar a página: {exc}")
            return self.html_path

        if no_disco:
            self.log(
                f"[HUD] Página atualizada (versão {no_disco} -> {HUD_VERSAO}). "
                f"A anterior ficou em {self.html_path.stem}.anterior.html."
            )
        return self.html_path

    def create(self):
        if not available():
            return False

        self.ensure_html()

        comum = dict(
            url=self.html_path.resolve().as_uri(),
            js_api=self.Api(self),
            width=WINDOW_WIDTH,
            height=WINDOW_HEIGHT,
            background_color=BACKGROUND,
            text_select=True,
        )

        # Abre MAXIMIZADA (tela cheia, com barra de título). O crash que
        # antes parecia ser disto era, na verdade, a corrida do PyAudio
        # (já corrigida com o cadeado), então dá para voltar o maximizado.
        # 'maximized' só existe no pywebview recente; num antigo cai no
        # tamanho normal sem quebrar.
        try:
            self.window = webview.create_window(
                WINDOW_TITLE, maximized=True, **comum
            )
        except TypeError:
            self.window = webview.create_window(WINDOW_TITLE, **comum)

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

    def mostrar(self):
        """Traz a janela para a frente (usado pelo ícone da bandeja).
        Tenta restaurar e mostrar; versões diferentes do pywebview têm
        um ou outro método, então tenta os que existirem, sem quebrar."""
        if self.window is None:
            return
        for metodo in ("restore", "show"):
            try:
                fn = getattr(self.window, metodo, None)
                if fn:
                    fn()
            except Exception:
                pass

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

    def set_esforco_nivel(self, nivel):
        """O rótulo do botão ESFORÇO (rapido / normal / alto)."""
        self.call("setEsforcoNivel", str(nivel))

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

    def set_vozes(self, lista, atual=None):
        """Preenche o seletor de voz do painel SISTEMA."""
        self.call("setVozes", lista, atual)

    def set_voz_atual(self, chave):
        """Marca no seletor qual voz esta em uso agora."""
        self.call("setVozAtual", str(chave or ""))

    def mostrar_escutando(self, ligado):
        """Reflete na janela se o microfone esta aberto ouvindo agora."""
        self.call("setEscutando", bool(ligado))

    def set_conversas(self, lista):
        """Entrega a lista de conversas antigas ao painel de historico."""
        self.call("setConversas", lista)

    def limpar_conversa(self):
        """Esvazia o log da janela, para repintar outra conversa."""
        self.call("limparLog")

    def notice(self, texto):
        self.add_message("nebell", texto)


# ============================================================
# PAGINA PADRAO
# ============================================================
# Mantem o desenho original da HUD. As adicoes sao o seletor de
# microfone, os botoes ARQUIVO e PARAR no rodape, as linhas de
# microfone, reconhecimento e GPU no painel da esquerda, e o aviso
# ready() ao Python.

def _ler_fonte(nome):
    return (FONTE_DIR / nome).read_text(encoding="utf-8")


def _montar_html_embutido():
    """Costura os arquivos-fonte de volta numa pagina de arquivo unico.

    A fonte da verdade sao os arquivos em hud_fonte/. Esta string so
    existe para um fallback e para os testes (que conferem marcadores
    nela). Monta-la a partir dos arquivos garante que ela nunca discorde
    do que roda de verdade. A versao sai da constante, nao de um numero
    digitado dentro do HTML.
    """
    def corte(s):
        return s[:-1] if s.endswith("\n") else s

    idx = _ler_fonte("index.html")
    idx = idx.replace(
        '<link rel="stylesheet" href="estilo.css">',
        f'<style>\n{corte(_ler_fonte("estilo.css"))}\n</style>', 1)
    idx = idx.replace(
        '<script src="formas.js"></script>',
        f'<script>\n{corte(_ler_fonte("formas.js"))}\n</script>', 1)
    idx = idx.replace(
        '<script src="app.js"></script>',
        f'<script>\n{corte(_ler_fonte("app.js"))}\n</script>', 1)
    return _marcar_pagina(idx)


try:
    HUD_HTML = _montar_html_embutido()
except Exception:            # hud_fonte ausente: a HUD some, o resto roda
    HUD_HTML = ""

