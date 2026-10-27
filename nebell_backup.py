"""
Backup da memoria do NEBELL.

O memoria.db e o unico arquivo insubstituivel do projeto: conversas,
fatos, projetos, lembretes e os comandos que o usuario ensinou. Todo o
resto se reescreve; aquilo, nao.

Tres decisoes que valem explicacao:

  1. O backup roda DURANTE a conversa, de tempo em tempo, nao so no
     encerramento. Processo morto no Gerenciador de Tarefas ou queda de
     energia nao executam codigo nenhum: nao existe gancho para isso.
     Salvar so no fim protegeria justamente o caso que nao precisa de
     protecao.

  2. A copia e feita pela API de backup do proprio SQLite, nao por
     copia de arquivo. Com WAL ligado, copiar o .db a mao enquanto
     alguem escreve produz um arquivo truncado que parece bom.

  3. A integridade e conferida ANTES de sobrescrever, e ficam duas
     geracoes anteriores. Backup unico sobrescrito as cegas tem uma
     armadilha: no dia em que o banco corromper, o backup bom e
     substituido pela copia ruim e nao sobra nada.

O relatorio em texto existe para o pior caso: se um dia nem o SQLite
abrir, as lembrancas ainda sao legiveis em um .txt comum.
"""

import os
import re
import shutil
import sqlite3
import threading
import time
import unicodedata
from datetime import datetime
from pathlib import Path

# De quanto em quanto tempo copiar, com a conversa em andamento.
INTERVALO = 5 * 60.0

# Quantas copias antigas guardar, alem da atual.
GERACOES = 2

NOME_BANCO = "memoria_backup.db"
NOME_RELATORIO = "memorias.txt"
NOME_REGISTRO = "backup.log"

# Um backup so vale a pena se o banco mudou desde o anterior.
MIN_SEGUNDOS_ENTRE_COPIAS = 20.0


def normalize(texto):
    texto = unicodedata.normalize("NFD", str(texto).lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", texto).strip()


def agora_legivel():
    return datetime.now().strftime("%d/%m/%Y às %H:%M")


# ============================================================
# CONFERIR E COPIAR
# ============================================================

def banco_esta_sao(caminho, timeout=10):
    """
    Diz se o banco esta inteiro.

    Devolve (esta_sao, motivo). Isto roda antes de sobrescrever o
    backup: copiar um banco corrompido por cima do bom e a unica forma
    de um backup piorar a situacao.
    """
    caminho = Path(caminho)

    if not caminho.is_file():
        return False, "o banco não existe"

    if caminho.stat().st_size == 0:
        return False, "o banco está vazio"

    conexao = None

    try:
        conexao = sqlite3.connect(
            f"file:{caminho}?mode=ro", uri=True, timeout=timeout
        )

        # quick_check pega corrupcao de pagina sem varrer o banco todo.
        linha = conexao.execute("PRAGMA quick_check").fetchone()
        resultado = (linha[0] if linha else "").strip().lower()

        if resultado != "ok":
            return False, f"o banco está corrompido ({resultado[:80]})"

        # Tem de ter as tabelas que importam.
        nomes = {
            l[0] for l in conexao.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }

        if "fatos" not in nomes or "conversas" not in nomes:
            return False, "o banco não tem as tabelas da memória"

        return True, ""

    except Exception as exc:
        return False, f"não consegui abrir o banco: {exc}"

    finally:
        if conexao is not None:
            try:
                conexao.close()
            except Exception:
                pass


def copiar_banco(origem, destino, timeout=15):
    """
    Copia o banco pela API de backup do SQLite.

    E a unica forma correta de copiar um banco em uso: ela conversa com
    o WAL e devolve um arquivo consistente. Devolve (deu_certo, erro).
    """
    origem = Path(origem)
    destino = Path(destino)

    de = para = None

    try:
        destino.parent.mkdir(parents=True, exist_ok=True)

        de = sqlite3.connect(
            f"file:{origem}?mode=ro", uri=True, timeout=timeout
        )
        para = sqlite3.connect(str(destino), timeout=timeout)

        de.backup(para)
        para.commit()

        # Um backup tem de ser UM arquivo. Como a copia herda o modo
        # WAL da origem, sem isto sobram um -wal e um -shm ao lado, e
        # quem copiasse so o .db levaria um banco incompleto.
        try:
            para.execute("PRAGMA journal_mode=DELETE")
            para.commit()
        except Exception:
            pass

        return True, ""

    except Exception as exc:
        return False, str(exc)

    finally:
        for conexao in (para, de):
            if conexao is not None:
                try:
                    conexao.close()
                except Exception:
                    pass


def rodar_geracoes(atual, quantas=GERACOES):
    """
    Empurra o backup atual para tras antes de gravar o novo.

    memoria_backup.db -> .1.db -> .2.db, e a mais velha sai. Assim o
    pedido de "substituir sempre" continua valendo (o arquivo principal
    e sempre o mais novo) sem que um banco corrompido apague a historia.
    """
    atual = Path(atual)

    if not atual.is_file():
        return

    for numero in range(quantas, 0, -1):
        anterior = atual.with_suffix(f".{numero}.db")

        if numero == quantas and anterior.is_file():
            try:
                anterior.unlink()
            except Exception:
                pass

        origem = (
            atual if numero == 1 else atual.with_suffix(f".{numero - 1}.db")
        )

        if origem.is_file():
            try:
                shutil.move(str(origem), str(anterior))
            except Exception:
                pass


# ============================================================
# RELATORIO LEGIVEL
# ============================================================

def montar_relatorio(memoria):
    """
    O que e importante, em texto que qualquer um le.

    Se um dia nem o SQLite abrir, isto ainda e um .txt comum com as
    lembrancas, os projetos e os comandos ensinados.
    """
    linhas = [
        "=" * 64,
        " MEMÓRIAS DO NEBELL",
        f" Cópia de {agora_legivel()}",
        "=" * 64,
        "",
    ]

    try:
        numeros = memoria.numeros()
        linhas += [
            "RESUMO",
            f"  {numeros['conversas']} conversa(s), "
            f"{numeros['mensagens']} mensagem(ns)",
            f"  {numeros['fatos']} lembrança(s) guardada(s)",
            f"  {numeros['projetos']} projeto(s)",
            f"  {numeros['arquivos']} arquivo(s) registrado(s)",
            f"  {numeros['comandos']} comando(s) ensinado(s)",
            f"  banco: {numeros['arquivo']}",
            "",
        ]
    except Exception as exc:
        linhas += [f"RESUMO  (não consegui contar: {exc})", ""]

    linhas += _secao_fatos(memoria)
    linhas += _secao_projetos(memoria)
    linhas += _secao_comandos(memoria)
    linhas += _secao_lembretes(memoria)
    linhas += _secao_conversas(memoria)
    linhas += _secao_arquivos(memoria)

    linhas += [
        "=" * 64,
        " Este arquivo é gerado automaticamente. Para restaurar a",
        " memória de verdade, copie o memoria_backup.db por cima do",
        " memoria.db na pasta do NEBELL, com o programa fechado.",
        "=" * 64,
        "",
    ]

    return "\n".join(linhas)


def _secao(titulo, itens, vazio="(nada registrado)"):
    linhas = [titulo, "-" * len(titulo)]

    if itens:
        linhas += itens
    else:
        linhas.append(f"  {vazio}")

    linhas.append("")
    return linhas


def _secao_fatos(memoria):
    try:
        fatos = memoria.listar_fatos(limite=200)
    except Exception as exc:
        return _secao("O QUE ELE SABE SOBRE VOCÊ", [f"  (erro: {exc})"])

    por_categoria = {}

    for fato in fatos:
        categoria = fato.get("categoria") or "geral"
        por_categoria.setdefault(categoria, []).append(fato)

    itens = []

    for categoria in sorted(por_categoria):
        itens.append(f"  [{categoria}]")

        for fato in por_categoria[categoria]:
            itens.append(f"    - {fato.get('texto', '')}")

    return _secao("O QUE ELE SABE SOBRE VOCÊ", itens)


def _secao_projetos(memoria):
    try:
        projetos = memoria.listar_projetos(limite=60)
    except Exception as exc:
        return _secao("PROJETOS", [f"  (erro: {exc})"])

    itens = []

    for projeto in projetos:
        nome = projeto.get("nome", "?")
        status = projeto.get("status") or "sem status"
        itens.append(f"  - {nome}  [{status}]")

        descricao = (projeto.get("descricao") or "").strip()

        if descricao:
            itens.append(f"      {descricao}")

        caminho = (projeto.get("caminho") or "").strip()

        if caminho:
            itens.append(f"      pasta: {caminho}")

        try:
            # Devolve (projeto, notas), nao a lista direto.
            _, notas = memoria.notas_do_projeto(nome, limite=20)
        except Exception:
            notas = []

        for nota in notas or []:
            itens.append(f"      · {nota.get('texto', '')}")

    return _secao("PROJETOS", itens)


def _secao_comandos(memoria):
    try:
        comandos = memoria.listar_comandos(limite=200)
    except Exception as exc:
        return _secao("COMANDOS QUE VOCÊ ENSINOU", [f"  (erro: {exc})"])

    itens = [
        f"  - quando eu disser \"{c.get('gatilho', '')}\" "
        f"-> {c.get('acao', '')}"
        for c in comandos
    ]
    return _secao("COMANDOS QUE VOCÊ ENSINOU", itens)


def _secao_lembretes(memoria):
    try:
        linhas = memoria.consultar(
            "SELECT texto, quando, recorrencia FROM lembretes "
            "WHERE ativo = 1 ORDER BY quando LIMIT 60"
        )
    except Exception:
        # A tabela so existe depois de a agenda abrir uma vez.
        return []

    itens = []

    for linha in linhas:
        quando = str(linha["quando"]).replace("T", " às ")
        marca = ""

        if linha["recorrencia"] == "diario":
            marca = "  (todos os dias)"
        elif linha["recorrencia"]:
            marca = "  (toda semana)"

        itens.append(f"  - {linha['texto']}: {quando}{marca}")

    return _secao("LEMBRETES MARCADOS", itens) if itens else []


def _secao_conversas(memoria):
    try:
        conversas = memoria.conversas_recentes(limite=10, com_resumo=True)
    except Exception as exc:
        return _secao("CONVERSAS ANTERIORES", [f"  (erro: {exc})"])

    itens = []

    for conversa in conversas:
        quando = str(conversa.get("inicio", "")).replace("T", " às ")
        itens.append(f"  - {quando}")

        resumo = (conversa.get("resumo") or "").strip()

        if resumo:
            for pedaco in resumo.split("\n"):
                if pedaco.strip():
                    itens.append(f"      {pedaco.strip()}")

    return _secao("CONVERSAS ANTERIORES", itens)


def _secao_arquivos(memoria):
    try:
        arquivos = memoria.buscar_arquivos("", limite=40)
    except Exception as exc:
        return _secao("ARQUIVOS QUE PASSARAM POR AQUI", [f"  (erro: {exc})"])

    itens = []

    for arquivo in arquivos:
        caminho = arquivo.get("caminho", "?")
        resumo = (arquivo.get("resumo") or "").strip()
        itens.append(f"  - {caminho}" + (f"  ({resumo})" if resumo else ""))

    return _secao("ARQUIVOS QUE PASSARAM POR AQUI", itens)


# ============================================================
# O GUARDIAO
# ============================================================

class Backup:
    """
    Mantem a pasta de backup sempre atualizada.

    Copia a cada `intervalo` enquanto a conversa corre, e mais uma vez
    no encerramento. O arquivo principal e sempre o mais novo, como
    pedido; as geracoes anteriores sao a rede de seguranca.
    """

    def __init__(self, banco, pasta, memoria=None, log=print,
                 intervalo=INTERVALO, geracoes=GERACOES):
        self.banco = Path(banco)
        self.pasta = Path(pasta)
        self.memoria = memoria
        self.log = log
        self.intervalo = intervalo
        self.geracoes = geracoes

        self.ligado = False
        self.ultima_copia = 0.0
        self.ultimo_erro = ""
        self.copias_feitas = 0

        self._thread = None
        self._parar = threading.Event()
        self._lock = threading.Lock()

    # --------------------------------------------------------

    @property
    def destino_banco(self):
        return self.pasta / NOME_BANCO

    @property
    def destino_relatorio(self):
        return self.pasta / NOME_RELATORIO

    def mudou_desde_a_ultima(self):
        """O banco mudou? Sem mudanca nao vale copiar."""
        try:
            if not self.destino_banco.is_file():
                return True

            return (
                self.banco.stat().st_mtime
                > self.destino_banco.stat().st_mtime + 1
            )

        except Exception:
            return True

    def escrever_relatorio(self):
        """
        Grava o relatorio legivel.

        Publico de proposito: o encerramento precisa gravar ANTES de
        fechar o banco. Gerado depois do fechamento, todas as secoes
        saem vazias, porque cada consulta bate em uma conexao morta.
        """
        return self._escrever_relatorio()

    def copiar(self, forcar=False, motivo="", com_relatorio=True):
        """
        Uma rodada de backup.

        Devolve (deu_certo, mensagem). Protegido por lock: o pedido
        periodico e o do encerramento podem chegar juntos.
        """
        with self._lock:
            agora = time.time()

            if not forcar:
                if agora - self.ultima_copia < MIN_SEGUNDOS_ENTRE_COPIAS:
                    return True, "copiado há pouco"

                if not self.mudou_desde_a_ultima():
                    return True, "nada mudou desde a última cópia"

            sao, motivo_recusa = banco_esta_sao(self.banco)

            if not sao:
                # Este e o ponto que salva: NAO sobrescrever o backup
                # bom com uma copia ruim.
                self.ultimo_erro = motivo_recusa
                self._registrar(f"RECUSADO: {motivo_recusa}")
                return False, (
                    f"Não fiz o backup porque {motivo_recusa}. "
                    "A cópia anterior está intacta."
                )

            try:
                self.pasta.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                self.ultimo_erro = str(exc)
                return False, f"não consegui criar a pasta de backup: {exc}"

            # Grava ao lado e so depois troca: se faltar energia no meio,
            # o backup antigo continua inteiro.
            provisorio = self.pasta / (NOME_BANCO + ".novo")

            deu_certo, erro = copiar_banco(self.banco, provisorio)

            if not deu_certo:
                self.ultimo_erro = erro
                self._registrar(f"FALHOU: {erro}")

                try:
                    provisorio.unlink()
                except Exception:
                    pass

                return False, f"não consegui copiar: {erro}"

            sao, motivo_recusa = banco_esta_sao(provisorio)

            if not sao:
                self.ultimo_erro = motivo_recusa
                self._registrar(f"COPIA RUIM: {motivo_recusa}")

                try:
                    provisorio.unlink()
                except Exception:
                    pass

                return False, (
                    f"a cópia saiu ruim ({motivo_recusa}); "
                    "mantive a anterior"
                )

            rodar_geracoes(self.destino_banco, self.geracoes)

            try:
                shutil.move(str(provisorio), str(self.destino_banco))
            except Exception as exc:
                self.ultimo_erro = str(exc)
                return False, f"não consegui trocar o backup: {exc}"

            # Restos do provisório, se o SQLite tiver deixado algum.
            for sufixo in ("-wal", "-shm"):
                resto = Path(str(provisorio) + sufixo)

                try:
                    if resto.is_file():
                        resto.unlink()
                except Exception:
                    pass

            self.ultima_copia = agora
            self.copias_feitas += 1

            tamanho = self.destino_banco.stat().st_size

            # com_relatorio=False na copia do encerramento: o banco ja
            # esta fechado ali, e reescrever o relatorio apagaria o bom,
            # gravado antes do fechamento.
            if com_relatorio:
                self._escrever_relatorio()
            self._registrar(
                f"ok ({tamanho // 1024} KB){f' - {motivo}' if motivo else ''}"
            )

            return True, (
                f"Backup atualizado em {self.destino_banco} "
                f"({tamanho // 1024} KB)."
            )

    def _escrever_relatorio(self):
        if self.memoria is None:
            return False

        try:
            texto = montar_relatorio(self.memoria)

            # Um relatorio que saiu zerado e sinal de banco fechado.
            # Melhor manter o anterior, que tinha conteudo, do que
            # cobri-lo com uma folha em branco.
            if "0 conversa(s), 0 mensagem(ns)" in texto and (
                self.destino_relatorio.is_file()
            ):
                self._registrar(
                    "relatório saiu vazio (banco fechado?); mantive o anterior"
                )
                return False

            self.destino_relatorio.write_text(texto, encoding="utf-8")
            return True

        except Exception as exc:
            self._registrar(f"relatório falhou: {exc}")
            return False

    def _registrar(self, mensagem):
        """Uma linha por tentativa, para dar para auditar depois."""
        try:
            self.pasta.mkdir(parents=True, exist_ok=True)

            with (self.pasta / NOME_REGISTRO).open(
                "a", encoding="utf-8", errors="replace"
            ) as saida:
                saida.write(
                    f"{datetime.now().isoformat(timespec='seconds')}  "
                    f"{mensagem}\n"
                )

        except Exception:
            pass

    # --------------------------------------------------------

    def vigiar(self):
        while not self._parar.is_set():
            # Espera primeiro: no comeco da sessao o banco acabou de ser
            # aberto e nao ha nada novo para copiar.
            self._parar.wait(self.intervalo)

            if self._parar.is_set():
                break

            try:
                self.copiar(motivo="periódico")
            except Exception as exc:
                self.log(f"[Backup] erro no ciclo: {exc}")

    def iniciar(self):
        if self.ligado:
            return False

        self._parar.clear()
        self._thread = threading.Thread(
            target=self.vigiar, name="nebell-backup", daemon=True
        )
        self._thread.start()
        self.ligado = True
        return True

    def parar(self):
        self._parar.set()
        self.ligado = False

    def numeros(self):
        existe = self.destino_banco.is_file()

        return {
            "pasta": str(self.pasta),
            "existe": existe,
            "tamanho_kb": (
                self.destino_banco.stat().st_size // 1024 if existe else 0
            ),
            "quando": (
                datetime.fromtimestamp(
                    self.destino_banco.stat().st_mtime
                ).strftime("%d/%m/%Y às %H:%M") if existe else ""
            ),
            "copias_na_sessao": self.copias_feitas,
            "geracoes": sum(
                1 for n in range(1, self.geracoes + 1)
                if self.destino_banco.with_suffix(f".{n}.db").is_file()
            ),
            "ultimo_erro": self.ultimo_erro,
        }

    def descrever(self):
        """Frase falavel sobre o estado do backup."""
        dados = self.numeros()

        if not dados["existe"]:
            if dados["ultimo_erro"]:
                return (
                    f"Ainda não há backup: {dados['ultimo_erro']}."
                )

            return (
                f"Ainda não há backup nesta sessão. A pasta é "
                f"{dados['pasta']}."
            )

        texto = (
            f"Backup de {dados['quando']}, {dados['tamanho_kb']} kilobytes, "
            f"em {dados['pasta']}"
        )

        if dados["geracoes"]:
            texto += f", com {dados['geracoes']} cópia(s) anterior(es)"

        if dados["ultimo_erro"]:
            texto += f". A última tentativa falhou: {dados['ultimo_erro']}"

        return texto + "."


# ============================================================
# RESTAURAR
# ============================================================

def restaurar(pasta, banco, log=print):
    """
    Devolve o backup para o lugar do banco.

    Guarda o banco atual como .antes_de_restaurar antes de trocar: se a
    pessoa restaurar por engano, nada se perde. O NEBELL precisa estar
    fechado, e quem chama confere isso.
    """
    pasta = Path(pasta)
    banco = Path(banco)
    copia = pasta / NOME_BANCO

    sao, motivo = banco_esta_sao(copia)

    if not sao:
        return False, f"o backup não serve: {motivo}"

    try:
        if banco.is_file():
            guardado = banco.with_suffix(".antes_de_restaurar.db")

            if guardado.is_file():
                guardado.unlink()

            shutil.move(str(banco), str(guardado))

        # Os arquivos de WAL do banco antigo nao servem para o novo.
        for sufixo in ("-wal", "-shm"):
            resto = Path(str(banco) + sufixo)

            if resto.is_file():
                resto.unlink()

        shutil.copy2(copia, banco)
        return True, f"Memória restaurada de {copia}."

    except Exception as exc:
        return False, f"não consegui restaurar: {exc}"
