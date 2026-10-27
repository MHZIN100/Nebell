"""
Memoria de longo prazo do NEBELL.

Guarda em um banco SQLite tudo o que vale lembrar entre uma execucao e
outra:

  conversas   cada sessao, com resumo do que foi tratado
  mensagens   o que foi dito, com busca por texto
  fatos       o que ele sabe sobre voce e como voce prefere as coisas
  projetos    no que voce esta trabalhando, com anotacoes
  arquivos    o que voce mandou ou pediu para ele olhar
  comandos    ordens que voce ensinou, com o que ele deve fazer

Usa apenas a biblioteca padrao: nenhuma instalacao a mais. Quando o
SQLite tem FTS5, a busca nas mensagens e por indice de texto; quando
nao tem, ela cai para LIKE, mais lenta mas com o mesmo resultado.

A conexao e compartilhada entre as threads do programa (despachante,
escuta, vigias), protegida por um lock.
"""

import json
import re
import sqlite3
import threading
import time
import unicodedata
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = 1

# Limites para a memoria nao crescer sem controle.
MAX_MESSAGE_CHARS = 4000
MAX_FACTS_IN_PROMPT = 25
MAX_MESSAGES_KEPT = 20000


def agora():
    return datetime.now().isoformat(timespec="seconds")


def normalize(texto):
    texto = unicodedata.normalize("NFD", str(texto).lower())
    texto = "".join(
        c for c in texto if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", texto).strip()


def quando(iso):
    """Transforma a data em algo falavel: 'hoje', 'ontem', '3 dias'."""
    try:
        momento = datetime.fromisoformat(iso)
    except Exception:
        return "em algum momento"

    dias = (datetime.now().date() - momento.date()).days

    if dias <= 0:
        return f"hoje às {momento.strftime('%H:%M')}"

    if dias == 1:
        return f"ontem às {momento.strftime('%H:%M')}"

    if dias < 7:
        return f"há {dias} dias"

    if dias < 30:
        return f"há {dias // 7} semana(s)"

    return momento.strftime("em %d/%m/%Y")


class Memoria:
    """Banco de memoria do NEBELL."""

    def __init__(self, caminho, log=print):
        self.caminho = Path(caminho)
        self.log = log
        self.conexao = None
        self.fts = False
        self.conversa_id = None
        self.disponivel = False
        self._lock = threading.RLock()

    # --------------------------------------------------------
    # Abertura
    # --------------------------------------------------------

    def abrir(self):
        try:
            self.caminho.parent.mkdir(parents=True, exist_ok=True)

            self.conexao = sqlite3.connect(
                str(self.caminho), check_same_thread=False, timeout=10
            )
            self.conexao.row_factory = sqlite3.Row
            self.conexao.execute("PRAGMA journal_mode=WAL")
            self.conexao.execute("PRAGMA synchronous=NORMAL")
            self.conexao.execute("PRAGMA foreign_keys=ON")

            self.criar_tabelas()
            self.disponivel = True
            return True

        except Exception as exc:
            self.log(f"[Memória] Não consegui abrir o banco: {exc}")
            self.disponivel = False
            return False

    def criar_tabelas(self):
        with self._lock:
            script = """
            CREATE TABLE IF NOT EXISTS conversas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                inicio TEXT NOT NULL,
                fim TEXT,
                modo TEXT,
                titulo TEXT,
                resumo TEXT,
                total INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS mensagens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversa_id INTEGER,
                papel TEXT NOT NULL,
                conteudo TEXT NOT NULL,
                criado_em TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_mensagens_conversa
                ON mensagens(conversa_id);

            CREATE TABLE IF NOT EXISTS fatos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                texto TEXT NOT NULL UNIQUE,
                chave TEXT NOT NULL,
                categoria TEXT DEFAULT 'geral',
                criado_em TEXT NOT NULL,
                usos INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS projetos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL UNIQUE,
                chave TEXT NOT NULL,
                descricao TEXT,
                status TEXT DEFAULT 'ativo',
                caminho TEXT,
                criado_em TEXT NOT NULL,
                atualizado_em TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS notas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                projeto_id INTEGER,
                texto TEXT NOT NULL,
                criado_em TEXT NOT NULL,
                FOREIGN KEY (projeto_id) REFERENCES projetos(id)
                    ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_notas_projeto
                ON notas(projeto_id);

            CREATE TABLE IF NOT EXISTS arquivos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                caminho TEXT NOT NULL UNIQUE,
                nome TEXT NOT NULL,
                chave TEXT NOT NULL,
                tamanho INTEGER,
                resumo TEXT,
                projeto_id INTEGER,
                visto_em TEXT NOT NULL,
                vezes INTEGER DEFAULT 1,
                FOREIGN KEY (projeto_id) REFERENCES projetos(id)
                    ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS comandos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gatilho TEXT NOT NULL UNIQUE,
                chave TEXT NOT NULL,
                acao TEXT NOT NULL,
                tipo TEXT DEFAULT 'instrucao',
                ferramenta TEXT,
                argumentos TEXT,
                criado_em TEXT NOT NULL,
                usos INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS meta (
                chave TEXT PRIMARY KEY,
                valor TEXT
            );
            """
            self.conexao.executescript(script)

            self.conexao.execute(
                "INSERT OR IGNORE INTO meta (chave, valor) VALUES (?, ?)",
                ("schema", str(SCHEMA_VERSION)),
            )

            # Indice de texto para a busca nas mensagens.
            try:
                self.conexao.executescript(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS mensagens_fts
                        USING fts5(conteudo, content='mensagens',
                                   content_rowid='id');

                    CREATE TRIGGER IF NOT EXISTS mensagens_ai
                    AFTER INSERT ON mensagens BEGIN
                        INSERT INTO mensagens_fts(rowid, conteudo)
                        VALUES (new.id, new.conteudo);
                    END;

                    CREATE TRIGGER IF NOT EXISTS mensagens_ad
                    AFTER DELETE ON mensagens BEGIN
                        INSERT INTO mensagens_fts(mensagens_fts, rowid, conteudo)
                        VALUES ('delete', old.id, old.conteudo);
                    END;
                    """
                )
                self.fts = True
            except Exception:
                # SQLite sem FTS5: a busca usa LIKE.
                self.fts = False

            self.conexao.commit()

    def fechar(self):
        with self._lock:
            if self.conexao is not None:
                try:
                    self.conexao.commit()
                    self.conexao.close()
                except Exception:
                    pass

            self.conexao = None
            self.disponivel = False

    def executar(self, sql, parametros=(), commit=True):
        """Roda uma instrucao, engolindo falhas: memoria nunca derruba."""
        if not self.disponivel:
            return None

        with self._lock:
            try:
                cursor = self.conexao.execute(sql, parametros)

                if commit:
                    self.conexao.commit()

                return cursor
            except Exception as exc:
                self.log(f"[Memória] {exc}")
                return None

    def consultar(self, sql, parametros=()):
        cursor = self.executar(sql, parametros, commit=False)
        return cursor.fetchall() if cursor is not None else []

    # --------------------------------------------------------
    # Conversas e mensagens
    # --------------------------------------------------------

    def iniciar_conversa(self, modo="texto"):
        cursor = self.executar(
            "INSERT INTO conversas (inicio, modo) VALUES (?, ?)",
            (agora(), modo),
        )

        if cursor is not None:
            self.conversa_id = cursor.lastrowid

        return self.conversa_id

    def encerrar_conversa(self, resumo=None, titulo=None):
        if self.conversa_id is None:
            return

        self.executar(
            "UPDATE conversas SET fim = ?, resumo = COALESCE(?, resumo), "
            "titulo = COALESCE(?, titulo) WHERE id = ?",
            (agora(), resumo, titulo, self.conversa_id),
        )

    def registrar_mensagem(self, papel, conteudo):
        """Guarda uma fala. Conteudo gigante e cortado."""
        if not self.disponivel:
            return False

        conteudo = (conteudo or "").strip()

        if not conteudo or papel not in ("user", "assistant"):
            return False

        if self.conversa_id is None:
            self.iniciar_conversa()

        self.executar(
            "INSERT INTO mensagens (conversa_id, papel, conteudo, criado_em) "
            "VALUES (?, ?, ?, ?)",
            (self.conversa_id, papel, conteudo[:MAX_MESSAGE_CHARS], agora()),
        )
        self.executar(
            "UPDATE conversas SET total = total + 1 WHERE id = ?",
            (self.conversa_id,),
        )
        return True

    def buscar_mensagens(self, texto, limite=6, incluir_atual=False):
        """Procura no que já foi dito, em todas as conversas."""
        texto = (texto or "").strip()

        if not texto:
            return []

        filtro = "" if incluir_atual else (
            "AND m.conversa_id IS NOT ?" if self.conversa_id else ""
        )
        extra = () if incluir_atual or not self.conversa_id else (self.conversa_id,)

        if self.fts:
            # Cada palavra entra como prefixo, o que acha "projeto" em
            # "projetos" e tolera a fala do reconhecimento de voz.
            termos = [p for p in re.findall(r"\w+", texto) if len(p) > 2]

            if not termos:
                return []

            consulta = " OR ".join(f'"{p}"*' for p in termos)

            linhas = self.consultar(
                f"""
                SELECT m.papel, m.conteudo, m.criado_em, m.conversa_id,
                       c.titulo, c.resumo
                FROM mensagens_fts f
                JOIN mensagens m ON m.id = f.rowid
                LEFT JOIN conversas c ON c.id = m.conversa_id
                WHERE mensagens_fts MATCH ? {filtro}
                ORDER BY bm25(mensagens_fts), m.id DESC
                LIMIT ?
                """,
                (consulta,) + extra + (limite,),
            )

            if linhas:
                return [dict(linha) for linha in linhas]

        padrao = f"%{texto}%"
        linhas = self.consultar(
            f"""
            SELECT m.papel, m.conteudo, m.criado_em, m.conversa_id,
                   c.titulo, c.resumo
            FROM mensagens m
            LEFT JOIN conversas c ON c.id = m.conversa_id
            WHERE m.conteudo LIKE ? {filtro}
            ORDER BY m.id DESC
            LIMIT ?
            """,
            (padrao,) + extra + (limite,),
        )
        return [dict(linha) for linha in linhas]

    def conversas_recentes(self, limite=3, com_resumo=True):
        condicao = "WHERE resumo IS NOT NULL AND resumo != ''" if com_resumo else ""
        atual = ""
        parametros = []

        if self.conversa_id is not None:
            atual = ("AND" if condicao else "WHERE") + " id != ?"
            parametros.append(self.conversa_id)

        parametros.append(limite)

        linhas = self.consultar(
            f"""
            SELECT id, inicio, fim, titulo, resumo, total
            FROM conversas {condicao} {atual}
            ORDER BY id DESC LIMIT ?
            """,
            tuple(parametros),
        )
        return [dict(linha) for linha in linhas]

    def transcricao(self, conversa_id, limite=40):
        linhas = self.consultar(
            "SELECT papel, conteudo, criado_em FROM mensagens "
            "WHERE conversa_id = ? ORDER BY id LIMIT ?",
            (conversa_id, limite),
        )
        return [dict(linha) for linha in linhas]

    def material_para_resumo(self, limite=30):
        """O que foi dito nesta sessao, para pedir um resumo ao modelo."""
        if self.conversa_id is None:
            return []

        return self.transcricao(self.conversa_id, limite)

    # --------------------------------------------------------
    # Fatos e preferencias
    # --------------------------------------------------------

    def guardar_fato(self, texto, categoria="geral"):
        texto = (texto or "").strip()

        if not texto:
            return False, "Nada para guardar."

        chave = normalize(texto)

        existente = self.consultar(
            "SELECT id FROM fatos WHERE chave = ?", (chave,)
        )

        if existente:
            return False, "Isso já está na memória."

        self.executar(
            "INSERT INTO fatos (texto, chave, categoria, criado_em) "
            "VALUES (?, ?, ?, ?)",
            (texto, chave, categoria, agora()),
        )
        return True, f"Guardado: {texto}"

    def esquecer_fato(self, assunto):
        alvo = normalize(assunto)

        if not alvo:
            return 0

        linhas = self.consultar(
            "SELECT id, chave FROM fatos WHERE chave LIKE ?", (f"%{alvo}%",)
        )

        for linha in linhas:
            self.executar("DELETE FROM fatos WHERE id = ?", (linha["id"],))

        return len(linhas)

    def listar_fatos(self, categoria=None, limite=60):
        if categoria:
            linhas = self.consultar(
                "SELECT texto, categoria FROM fatos WHERE categoria = ? "
                "ORDER BY id LIMIT ?",
                (categoria, limite),
            )
        else:
            linhas = self.consultar(
                "SELECT texto, categoria FROM fatos ORDER BY id LIMIT ?",
                (limite,),
            )

        return [dict(linha) for linha in linhas]

    # --------------------------------------------------------
    # Projetos
    # --------------------------------------------------------

    def salvar_projeto(self, nome, descricao=None, status=None, caminho=None):
        nome = (nome or "").strip()

        if not nome:
            return False, "Informe o nome do projeto."

        chave = normalize(nome)
        existente = self.consultar(
            "SELECT id FROM projetos WHERE chave = ?", (chave,)
        )

        if existente:
            self.executar(
                "UPDATE projetos SET descricao = COALESCE(?, descricao), "
                "status = COALESCE(?, status), caminho = COALESCE(?, caminho), "
                "atualizado_em = ? WHERE id = ?",
                (descricao, status, caminho, agora(), existente[0]["id"]),
            )
            return True, f"Projeto {nome} atualizado."

        self.executar(
            "INSERT INTO projetos (nome, chave, descricao, status, caminho, "
            "criado_em, atualizado_em) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (nome, chave, descricao, status or "ativo", caminho,
             agora(), agora()),
        )
        return True, f"Projeto {nome} criado."

    def achar_projeto(self, nome):
        """
        Acha o projeto pelo nome exato, por um pedaco do nome ou por
        semelhanca.

        A semelhanca importa na pratica: voce registra "Carro seguidor
        de linha" e depois chama de "carrinho". Sem ela, ele responderia
        que nao conhece o projeto.
        """
        chave = normalize(nome)

        if not chave:
            return None

        linhas = self.consultar(
            "SELECT * FROM projetos WHERE chave = ?", (chave,)
        )

        if linhas:
            return dict(linhas[0])

        # Busca por pedaco so a partir de tres letras: com "de" ou "um"
        # qualquer projeto casaria.
        if len(chave) >= 3:
            linhas = self.consultar(
                "SELECT * FROM projetos WHERE chave LIKE ? ORDER BY "
                "atualizado_em DESC, id DESC LIMIT 1",
                (f"%{chave}%",),
            )

            if linhas:
                return dict(linhas[0])

        return self.projeto_parecido(chave)

    def projeto_parecido(self, chave, corte=0.75):
        """Compara palavra por palavra e devolve o projeto mais proximo."""
        from difflib import SequenceMatcher

        procuradas = [p for p in chave.split() if len(p) > 3]

        if not procuradas:
            return None

        melhor = None
        melhor_nota = 0.0

        for projeto in self.listar_projetos(limite=100):
            palavras = [p for p in normalize(projeto["nome"]).split() if len(p) > 3]

            for procurada in procuradas:
                for palavra in palavras:
                    nota = SequenceMatcher(None, procurada, palavra).ratio()

                    if nota > melhor_nota:
                        melhor_nota = nota
                        melhor = projeto

        return melhor if melhor_nota >= corte else None

    def listar_projetos(self, status=None, limite=20):
        if status:
            linhas = self.consultar(
                "SELECT * FROM projetos WHERE status = ? "
                "ORDER BY atualizado_em DESC, id DESC LIMIT ?",
                (status, limite),
            )
        else:
            linhas = self.consultar(
                "SELECT * FROM projetos ORDER BY atualizado_em DESC, "
                "id DESC LIMIT ?",
                (limite,),
            )

        return [dict(linha) for linha in linhas]

    def anotar_projeto(self, nome, texto):
        projeto = self.achar_projeto(nome)

        if projeto is None:
            deu, _ = self.salvar_projeto(nome)

            if not deu:
                return False, "Não consegui registrar o projeto."

            projeto = self.achar_projeto(nome)

        self.executar(
            "INSERT INTO notas (projeto_id, texto, criado_em) VALUES (?, ?, ?)",
            (projeto["id"], texto.strip(), agora()),
        )
        self.executar(
            "UPDATE projetos SET atualizado_em = ? WHERE id = ?",
            (agora(), projeto["id"]),
        )
        return True, f"Anotado no projeto {projeto['nome']}."

    def notas_do_projeto(self, nome, limite=12):
        projeto = self.achar_projeto(nome)

        if projeto is None:
            return None, []

        linhas = self.consultar(
            "SELECT texto, criado_em FROM notas WHERE projeto_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (projeto["id"], limite),
        )
        return projeto, [dict(linha) for linha in linhas]

    def projeto_mais_recente(self):
        linhas = self.consultar(
            "SELECT * FROM projetos WHERE status = 'ativo' "
            "ORDER BY atualizado_em DESC, id DESC LIMIT 1"
        )
        return dict(linhas[0]) if linhas else None

    # --------------------------------------------------------
    # Arquivos
    # --------------------------------------------------------

    def registrar_arquivo(self, caminho, resumo=None, projeto=None):
        caminho = str(caminho).strip()

        if not caminho:
            return False, "Informe o arquivo."

        alvo = Path(caminho)
        nome = alvo.name or caminho
        tamanho = None

        try:
            if alvo.is_file():
                tamanho = alvo.stat().st_size
        except Exception:
            pass

        projeto_id = None

        if projeto:
            encontrado = self.achar_projeto(projeto)
            projeto_id = encontrado["id"] if encontrado else None

        existente = self.consultar(
            "SELECT id, vezes FROM arquivos WHERE caminho = ?", (caminho,)
        )

        if existente:
            self.executar(
                "UPDATE arquivos SET visto_em = ?, vezes = vezes + 1, "
                "resumo = COALESCE(?, resumo), "
                "projeto_id = COALESCE(?, projeto_id) WHERE id = ?",
                (agora(), resumo, projeto_id, existente[0]["id"]),
            )
            return True, f"Arquivo {nome} atualizado na memória."

        self.executar(
            "INSERT INTO arquivos (caminho, nome, chave, tamanho, resumo, "
            "projeto_id, visto_em) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (caminho, nome, normalize(nome), tamanho, resumo,
             projeto_id, agora()),
        )
        return True, f"Arquivo {nome} guardado na memória."

    def buscar_arquivos(self, termo="", limite=12):
        termo = normalize(termo)

        if termo:
            linhas = self.consultar(
                """
                SELECT a.*, p.nome AS projeto
                FROM arquivos a LEFT JOIN projetos p ON p.id = a.projeto_id
                WHERE a.chave LIKE ? OR a.caminho LIKE ?
                   OR COALESCE(a.resumo, '') LIKE ?
                ORDER BY a.visto_em DESC, a.id DESC LIMIT ?
                """,
                (f"%{termo}%", f"%{termo}%", f"%{termo}%", limite),
            )
        else:
            linhas = self.consultar(
                """
                SELECT a.*, p.nome AS projeto
                FROM arquivos a LEFT JOIN projetos p ON p.id = a.projeto_id
                ORDER BY a.visto_em DESC, a.id DESC LIMIT ?
                """,
                (limite,),
            )

        return [dict(linha) for linha in linhas]

    # --------------------------------------------------------
    # Comandos aprendidos
    # --------------------------------------------------------

    def ensinar_comando(self, gatilho, acao, ferramenta=None, argumentos=None):
        gatilho = (gatilho or "").strip()
        acao = (acao or "").strip()

        if not gatilho or not acao:
            return False, "Preciso do gatilho e do que fazer."

        chave = normalize(gatilho)

        if len(chave) < 3:
            return False, "O gatilho é curto demais; use pelo menos uma palavra."

        tipo = "ferramenta" if ferramenta else "instrucao"
        payload = None

        if argumentos:
            payload = (
                argumentos if isinstance(argumentos, str)
                else json.dumps(argumentos, ensure_ascii=False)
            )

        existente = self.consultar(
            "SELECT id FROM comandos WHERE chave = ?", (chave,)
        )

        if existente:
            self.executar(
                "UPDATE comandos SET acao = ?, tipo = ?, ferramenta = ?, "
                "argumentos = ? WHERE id = ?",
                (acao, tipo, ferramenta, payload, existente[0]["id"]),
            )
            return True, f"Comando '{gatilho}' atualizado."

        self.executar(
            "INSERT INTO comandos (gatilho, chave, acao, tipo, ferramenta, "
            "argumentos, criado_em) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (gatilho, chave, acao, tipo, ferramenta, payload, agora()),
        )
        return True, f"Comando aprendido: ao ouvir '{gatilho}', {acao}."

    def esquecer_comando(self, gatilho):
        chave = normalize(gatilho)
        linhas = self.consultar(
            "SELECT id, gatilho FROM comandos WHERE chave LIKE ?",
            (f"%{chave}%",),
        )

        for linha in linhas:
            self.executar("DELETE FROM comandos WHERE id = ?", (linha["id"],))

        return len(linhas)

    def listar_comandos(self, limite=40):
        linhas = self.consultar(
            "SELECT gatilho, acao, tipo, ferramenta, argumentos, usos "
            "FROM comandos ORDER BY usos DESC, id LIMIT ?",
            (limite,),
        )
        return [dict(linha) for linha in linhas]

    def casar_comando(self, texto):
        """
        Acha o comando aprendido que combina com o que foi dito.

        Prefere o gatilho mais longo: 'abrir o projeto do carrinho' ganha
        de 'abrir o projeto', que e mais generico.
        """
        alvo = normalize(texto)

        if not alvo:
            return None

        candidatos = []

        for comando in self.listar_comandos(limite=200):
            chave = normalize(comando["gatilho"])

            if not chave:
                continue

            if chave in alvo:
                candidatos.append((len(chave), comando))
                continue

            palavras = [p for p in chave.split() if len(p) > 2]

            if palavras and all(p in alvo for p in palavras):
                candidatos.append((len(chave) - 1, comando))

        if not candidatos:
            return None

        candidatos.sort(key=lambda item: -item[0])
        escolhido = candidatos[0][1]

        self.executar(
            "UPDATE comandos SET usos = usos + 1 WHERE gatilho = ?",
            (escolhido["gatilho"],),
        )
        return escolhido

    # --------------------------------------------------------
    # Resumo para o prompt
    # --------------------------------------------------------

    def briefing(self):
        """
        Texto curto para entrar no prompt do sistema: o que ele sabe de
        voce, no que voce esta trabalhando e o que ficou da ultima vez.
        """
        if not self.disponivel:
            return ""

        partes = []

        fatos = self.listar_fatos(limite=MAX_FACTS_IN_PROMPT)

        if fatos:
            preferencias = [f["texto"] for f in fatos if f["categoria"] == "preferencia"]
            outros = [f["texto"] for f in fatos if f["categoria"] != "preferencia"]

            if outros:
                partes.append(
                    "O que você já sabe sobre o usuário:\n"
                    + "\n".join(f"- {t}" for t in outros)
                )

            if preferencias:
                partes.append(
                    "Preferências dele, que você deve seguir:\n"
                    + "\n".join(f"- {t}" for t in preferencias)
                )

        projetos = self.listar_projetos(status="ativo", limite=5)

        if projetos:
            linhas = []

            for projeto in projetos:
                descricao = f": {projeto['descricao']}" if projeto["descricao"] else ""
                linhas.append(f"- {projeto['nome']}{descricao}")

            partes.append("Projetos em andamento:\n" + "\n".join(linhas))

        recentes = self.conversas_recentes(limite=2)

        if recentes:
            linhas = [
                f"- {quando(c['inicio'])}: {c['resumo']}"
                for c in recentes if c.get("resumo")
            ]

            if linhas:
                partes.append(
                    "Do que vocês trataram antes:\n" + "\n".join(linhas)
                )

        comandos = self.listar_comandos(limite=15)

        if comandos:
            linhas = [
                f"- quando ele disser \"{c['gatilho']}\": {c['acao']}"
                for c in comandos
            ]
            partes.append(
                "Comandos que ele ensinou e você deve obedecer:\n"
                + "\n".join(linhas)
            )

        if not partes:
            return ""

        return (
            "\n=== MEMÓRIA DE LONGO PRAZO ===\n"
            + "\n\n".join(partes)
            + "\nUse isso naturalmente, sem anunciar que consultou a memória. "
            "Para detalhes de conversas antigas, use a ferramenta recordar.\n"
        )

    # --------------------------------------------------------
    # Manutencao e numeros
    # --------------------------------------------------------

    def numeros(self):
        def contar(tabela):
            linhas = self.consultar(f"SELECT COUNT(*) AS n FROM {tabela}")
            return linhas[0]["n"] if linhas else 0

        return {
            "conversas": contar("conversas"),
            "mensagens": contar("mensagens"),
            "fatos": contar("fatos"),
            "projetos": contar("projetos"),
            "arquivos": contar("arquivos"),
            "comandos": contar("comandos"),
            "fts": self.fts,
            "arquivo": str(self.caminho),
        }

    def podar(self):
        """Corta as mensagens mais antigas quando o banco fica grande."""
        linhas = self.consultar("SELECT COUNT(*) AS n FROM mensagens")

        if not linhas or linhas[0]["n"] <= MAX_MESSAGES_KEPT:
            return 0

        excesso = linhas[0]["n"] - MAX_MESSAGES_KEPT

        self.executar(
            "DELETE FROM mensagens WHERE id IN "
            "(SELECT id FROM mensagens ORDER BY id LIMIT ?)",
            (excesso,),
        )
        return excesso

    def importar_json_antigo(self, caminho):
        """Traz os fatos do memoria.json da versao anterior."""
        caminho = Path(caminho)

        if not caminho.is_file():
            return 0

        try:
            dados = json.loads(caminho.read_text(encoding="utf-8"))
        except Exception:
            return 0

        trazidos = 0

        for fato in dados.get("fatos", []):
            deu, _ = self.guardar_fato(str(fato), categoria="geral")

            if deu:
                trazidos += 1

        if trazidos:
            try:
                caminho.rename(caminho.with_suffix(".json.importado"))
            except Exception:
                pass

        return trazidos
