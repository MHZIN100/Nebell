"""
Leitura de documentos do NEBELL: PDF, Word, Excel, PowerPoint, texto.

Este arquivo so EXTRAI o texto. Quem resume e o modelo de conversa, em
nebell.py, com o texto que sai daqui. Assim o resumo nao custa nada de
VRAM alem do que o modelo ja ocupa.

Para nao estourar o contexto de 8 mil tokens, `recortar_para_resumo`
pega o comeco, um pedaco do meio e o fim do documento: para um texto
longo isso vale muito mais que os primeiros capitulos sozinhos.

Instalar o que falta:
    pip install pypdf python-docx openpyxl python-pptx
"""

import csv
import io
import re
import unicodedata
from pathlib import Path

EXTENSOES = {
    ".pdf": "pdf",
    ".docx": "word", ".doc": "word",
    ".xlsx": "planilha", ".xlsm": "planilha", ".csv": "csv",
    ".pptx": "apresentacao",
    ".txt": "texto", ".md": "texto", ".log": "texto",
    ".json": "texto", ".xml": "texto", ".html": "texto", ".htm": "texto",
    ".py": "texto", ".js": "texto", ".ts": "texto", ".java": "texto",
    ".c": "texto", ".cpp": "texto", ".cs": "texto", ".rs": "texto",
    ".ini": "texto", ".cfg": "texto", ".yml": "texto", ".yaml": "texto",
    ".bat": "texto", ".ps1": "texto", ".sql": "texto", ".rtf": "texto",
}

MAX_BYTES = 80 * 1024 * 1024        # 80 MB: acima disso nem tento
MAX_CARACTERES = 400_000            # o que trago para a memoria
MAX_PAGINAS_PDF = 400
MAX_LINHAS_PLANILHA = 2000
LIMITE_RESUMO = 14_000              # o que cabe no contexto com folga

PACOTES = {
    "pdf": ("pypdf", "pip install pypdf"),
    "word": ("docx", "pip install python-docx"),
    "planilha": ("openpyxl", "pip install openpyxl"),
    "apresentacao": ("pptx", "pip install python-pptx"),
}


def normalize(texto):
    texto = unicodedata.normalize("NFD", str(texto).lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", texto).strip()


def tipo_de(caminho):
    return EXTENSOES.get(Path(caminho).suffix.lower())


def limpar(texto):
    """Tira espaco repetido e linha vazia demais, preservando paragrafos."""
    texto = str(texto or "").replace("\r\n", "\n").replace("\r", "\n")
    texto = re.sub(r"[ \t\x0b\f]+", " ", texto)
    texto = re.sub(r" *\n *", "\n", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def _importar(tipo):
    """Importa o pacote do tipo, devolvendo (modulo, None) ou (None, erro)."""
    nome, comando = PACOTES[tipo]

    try:
        return __import__(nome), None
    except Exception:
        return None, (
            f"preciso de um pacote para ler {tipo}. Instale com: {comando}"
        )


# ============================================================
# EXTRATORES
# ============================================================

def ler_pdf(caminho):
    pypdf, erro = _importar("pdf")

    if erro:
        return None, erro

    try:
        leitor = pypdf.PdfReader(str(caminho))

        if getattr(leitor, "is_encrypted", False):
            try:
                leitor.decrypt("")
            except Exception:
                return None, "esse PDF está protegido por senha"

        paginas = leitor.pages
        total = len(paginas)
        pedacos = []

        for numero, pagina in enumerate(paginas[:MAX_PAGINAS_PDF], start=1):
            try:
                texto = pagina.extract_text() or ""
            except Exception:
                texto = ""

            if texto.strip():
                pedacos.append(f"[página {numero}]\n{texto.strip()}")

            if sum(len(p) for p in pedacos) > MAX_CARACTERES:
                break

    except Exception as exc:
        return None, f"não consegui abrir o PDF: {exc}"

    if not pedacos:
        return None, (
            "esse PDF não tem texto, só imagem (é um documento escaneado). "
            "Posso tentar ler por OCR se você pedir"
        )

    corpo = limpar("\n\n".join(pedacos))

    return {
        "tipo": "pdf", "texto": corpo, "paginas": total,
        "lidas": min(total, MAX_PAGINAS_PDF),
    }, None


def ler_word(caminho):
    docx, erro = _importar("word")

    if erro:
        return None, erro

    if Path(caminho).suffix.lower() == ".doc":
        return None, (
            "o formato .doc antigo não dá para ler direto. "
            "Abra no Word e salve como .docx"
        )

    try:
        from docx import Document

        documento = Document(str(caminho))
        linhas = []

        for paragrafo in documento.paragraphs:
            texto = (paragrafo.text or "").strip()

            if not texto:
                continue

            estilo = getattr(
                getattr(paragrafo, "style", None), "name", ""
            ) or ""

            if normalize(estilo).startswith(("heading", "titulo", "title")):
                linhas.append(f"\n## {texto}")
            else:
                linhas.append(texto)

        for numero, tabela in enumerate(documento.tables, start=1):
            linhas.append(f"\n[tabela {numero}]")

            for linha in tabela.rows[:60]:
                celulas = [
                    (c.text or "").strip().replace("\n", " ")
                    for c in linha.cells
                ]

                if any(celulas):
                    linhas.append(" | ".join(celulas))

    except Exception as exc:
        return None, f"não consegui abrir o documento: {exc}"

    corpo = limpar("\n".join(linhas))

    if not corpo:
        return None, "esse documento está vazio"

    return {
        "tipo": "word", "texto": corpo,
        "paragrafos": len(documento.paragraphs),
        "tabelas": len(documento.tables),
    }, None


def ler_planilha(caminho):
    openpyxl, erro = _importar("planilha")

    if erro:
        return None, erro

    try:
        livro = openpyxl.load_workbook(
            str(caminho), read_only=True, data_only=True
        )

        partes = []
        folhas = []

        for folha in livro.worksheets:
            folhas.append(folha.title)
            partes.append(f"\n[planilha: {folha.title}]")
            vazias = 0

            for numero, linha in enumerate(
                folha.iter_rows(values_only=True), start=1
            ):
                if numero > MAX_LINHAS_PLANILHA:
                    partes.append(
                        f"... (parei na linha {MAX_LINHAS_PLANILHA})"
                    )
                    break

                valores = [
                    "" if v is None else str(v).strip() for v in linha
                ]

                if not any(valores):
                    vazias += 1

                    if vazias > 20:
                        break

                    continue

                vazias = 0
                partes.append(" | ".join(valores).rstrip(" |"))

        livro.close()

    except Exception as exc:
        return None, f"não consegui abrir a planilha: {exc}"

    corpo = limpar("\n".join(partes))

    if not corpo:
        return None, "essa planilha está vazia"

    return {"tipo": "planilha", "texto": corpo, "folhas": folhas}, None


def ler_csv(caminho):
    try:
        bruto = Path(caminho).read_bytes()[:MAX_CARACTERES * 2]
        texto = bruto.decode("utf-8-sig", "replace")

        amostra = texto[:4000]

        try:
            dialeto = csv.Sniffer().sniff(amostra, delimiters=",;\t|")
            separador = dialeto.delimiter
        except Exception:
            separador = ";" if amostra.count(";") > amostra.count(",") else ","

        leitor = csv.reader(io.StringIO(texto), delimiter=separador)
        linhas = []

        for numero, linha in enumerate(leitor, start=1):
            if numero > MAX_LINHAS_PLANILHA:
                linhas.append(f"... (parei na linha {MAX_LINHAS_PLANILHA})")
                break

            if any(c.strip() for c in linha):
                linhas.append(" | ".join(c.strip() for c in linha))

    except Exception as exc:
        return None, f"não consegui ler o CSV: {exc}"

    if not linhas:
        return None, "esse arquivo está vazio"

    return {
        "tipo": "csv", "texto": limpar("\n".join(linhas)),
        "linhas": len(linhas), "separador": separador,
    }, None


def ler_apresentacao(caminho):
    pptx, erro = _importar("apresentacao")

    if erro:
        return None, erro

    try:
        from pptx import Presentation

        apresentacao = Presentation(str(caminho))
        partes = []

        for numero, slide in enumerate(apresentacao.slides, start=1):
            linhas = []

            for forma in slide.shapes:
                texto = (getattr(forma, "text", "") or "").strip()

                if texto:
                    linhas.append(texto)

            if linhas:
                partes.append(f"[slide {numero}]\n" + "\n".join(linhas))

        total = len(apresentacao.slides._sldIdLst)

    except Exception as exc:
        return None, f"não consegui abrir a apresentação: {exc}"

    corpo = limpar("\n\n".join(partes))

    if not corpo:
        return None, "essa apresentação não tem texto"

    return {"tipo": "apresentacao", "texto": corpo, "slides": total}, None


def ler_texto_simples(caminho):
    caminho = Path(caminho)

    try:
        bruto = caminho.read_bytes()[:MAX_CARACTERES * 2]
    except Exception as exc:
        return None, f"não consegui ler o arquivo: {exc}"

    for codificacao in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            texto = bruto.decode(codificacao)
            break
        except UnicodeDecodeError:
            continue
    else:
        texto = bruto.decode("utf-8", "replace")

    # Texto e codigo vao COMO ESTAO. O `limpar` existe para documento
    # do Word, onde espaco repetido e lixo de formatacao; aqui ele
    # apagaria a indentacao, e um .py relido e regravado sem indentacao
    # simplesmente nao roda.
    corpo = texto.replace("\r\n", "\n").replace("\r", "\n")

    if not corpo.strip():
        return None, "esse arquivo está vazio"

    if len(corpo) > MAX_CARACTERES:
        corpo = corpo[:MAX_CARACTERES]

    return {
        "tipo": "texto", "texto": corpo,
        "linhas": corpo.count("\n") + 1,
    }, None


LEITORES = {
    "pdf": ler_pdf,
    "word": ler_word,
    "planilha": ler_planilha,
    "csv": ler_csv,
    "apresentacao": ler_apresentacao,
    "texto": ler_texto_simples,
}


# ============================================================
# PORTA DE ENTRADA
# ============================================================

def ler(caminho):
    """
    Le qualquer documento conhecido.

    Devolve (dicionario com texto e metadados, None) ou (None, erro).
    """
    caminho = Path(str(caminho).strip().strip('"').strip("'")).expanduser()

    if not caminho.exists():
        return None, f"não encontrei {caminho}"

    if caminho.is_dir():
        return None, f"{caminho} é uma pasta, não um documento"

    tamanho = caminho.stat().st_size

    if tamanho == 0:
        return None, "esse arquivo está vazio"

    if tamanho > MAX_BYTES:
        return None, (
            f"esse arquivo tem {tamanho / 1024 / 1024:.0f} megabytes, "
            "é grande demais para eu ler de uma vez"
        )

    tipo = tipo_de(caminho)

    if tipo is None:
        return None, (
            f"não sei ler arquivos {caminho.suffix or 'sem extensão'}. "
            "Leio PDF, Word, Excel, CSV, PowerPoint e texto"
        )

    dados, erro = LEITORES[tipo](caminho)

    if erro:
        return None, erro

    dados["caminho"] = str(caminho)
    dados["nome"] = caminho.name
    dados["tamanho_bytes"] = tamanho
    dados["caracteres"] = len(dados["texto"])
    dados["palavras"] = len(dados["texto"].split())

    return dados, None


def recortar_para_resumo(texto, limite=LIMITE_RESUMO):
    """
    Corta o texto para caber no contexto sem perder o fim.

    Pega o inicio, um pedaco do meio e o fim: o fim de um documento
    costuma ter a conclusao, que e justamente o que interessa em um
    resumo.
    """
    texto = str(texto or "")

    if len(texto) <= limite:
        return texto

    marca_meio = "\n\n[...parte do meio omitida...]\n\n"
    marca_fim = "\n\n[...parte omitida...]\n\n"

    sobra = max(300, limite - len(marca_meio) - len(marca_fim))

    inicio = int(sobra * 0.55)
    meio = int(sobra * 0.2)
    fim = sobra - inicio - meio

    centro = len(texto) // 2

    return (
        texto[:inicio]
        + marca_meio
        + texto[centro - meio // 2:centro + meio // 2]
        + marca_fim
        + texto[-fim:]
    )


def ficha(dados):
    """Uma linha falavel descrevendo o documento lido."""
    partes = [dados["nome"]]

    if dados["tipo"] == "pdf":
        partes.append(f"{dados['paginas']} páginas")

        if dados["lidas"] < dados["paginas"]:
            partes.append(f"li as {dados['lidas']} primeiras")

    elif dados["tipo"] == "apresentacao":
        partes.append(f"{dados['slides']} slides")

    elif dados["tipo"] == "planilha":
        folhas = dados.get("folhas") or []
        partes.append(
            f"{len(folhas)} planilha" + ("s" if len(folhas) != 1 else "")
        )

    partes.append(f"{dados['palavras']} palavras")

    return ", ".join(partes)


def pedido_de_resumo(dados, pergunta=None):
    """
    O texto que vai para o modelo.

    Quando a pessoa fez uma pergunta sobre o documento, a pergunta
    manda; senao, e um resumo mesmo.
    """
    corpo = recortar_para_resumo(dados["texto"])

    cabeca = f"Documento: {ficha(dados)}\n\n{corpo}\n\n"

    if pergunta:
        return cabeca + (
            f"Com base apenas no documento acima, responda em português: "
            f"{pergunta}"
        )

    return cabeca + (
        "Resuma o documento acima em português do Brasil: diga do que se "
        "trata em uma frase, depois os pontos principais em até cinco "
        "itens curtos, e no fim o que fica pendente ou precisa de decisão, "
        "se houver. Não invente nada que não esteja no documento."
    )


def procurar_dentro(dados, termo, contexto=160):
    """Acha onde um termo aparece no documento, com o trecho em volta."""
    texto = dados["texto"]
    procurado = normalize(termo)

    if not procurado:
        return []

    plano = normalize(texto)
    achados = []
    posicao = 0

    while len(achados) < 8:
        posicao = plano.find(procurado, posicao)

        if posicao < 0:
            break

        inicio = max(0, posicao - contexto // 2)
        fim = min(len(texto), posicao + len(procurado) + contexto // 2)
        achados.append(texto[inicio:fim].replace("\n", " ").strip())
        posicao += len(procurado)

    return achados


# ============================================================
# CRIAR DOCUMENTOS
# ============================================================
# Word, Excel, PowerPoint e PDF nao sao texto: gravar com write_text
# produz um arquivo que o programa recusa abrir. Aqui o conteudo vem
# como texto simples, com uma marcacao minima, e cada formato monta o
# arquivo de verdade.

CRIAVEIS = {
    ".docx": "word",
    ".xlsx": "planilha",
    ".pptx": "apresentacao",
    ".pdf": "pdf",
}

PACOTES_PARA_CRIAR = {
    "word": ("docx", "pip install python-docx"),
    "planilha": ("openpyxl", "pip install openpyxl"),
    "apresentacao": ("pptx", "pip install python-pptx"),
    "pdf": ("reportlab", "pip install reportlab"),
}

# Quanto cabe em uma pagina de PDF, em linhas.
LINHAS_POR_PAGINA = 48


def da_para_criar(caminho):
    """O tipo de documento desta extensao, ou None quando e texto puro."""
    return CRIAVEIS.get(Path(caminho).suffix.lower())


def _importar_para_criar(tipo):
    nome, comando = PACOTES_PARA_CRIAR[tipo]

    try:
        return __import__(nome), None
    except Exception:
        return None, (
            f"para criar {tipo} eu preciso de um pacote. Instale com: "
            f"{comando}"
        )


def separar_linhas(conteudo):
    return str(conteudo or "").replace("\r\n", "\n").split("\n")


def criar_word(caminho, conteudo):
    """
    Monta um .docx.

    Entende uma marcacao minima, a mesma que o modelo ja escreve
    naturalmente: "# titulo", "## subtitulo", "- item" e linha em
    branco separando paragrafos.
    """
    _, erro = _importar_para_criar("word")

    if erro:
        return None, erro

    try:
        from docx import Document

        documento = Document()

        for linha in separar_linhas(conteudo):
            texto = linha.strip()

            if not texto:
                continue

            if texto.startswith("### "):
                documento.add_heading(texto[4:].strip(), level=3)
            elif texto.startswith("## "):
                documento.add_heading(texto[3:].strip(), level=2)
            elif texto.startswith("# "):
                documento.add_heading(texto[2:].strip(), level=1)
            elif texto.startswith(("- ", "* ")):
                documento.add_paragraph(texto[2:].strip(), style="List Bullet")
            elif re.match(r"^\d+[.)]\s", texto):
                documento.add_paragraph(
                    re.sub(r"^\d+[.)]\s*", "", texto), style="List Number"
                )
            else:
                documento.add_paragraph(texto)

        if not documento.paragraphs:
            documento.add_paragraph("")

        documento.save(str(caminho))
        return caminho, None

    except Exception as exc:
        return None, f"não consegui montar o documento: {exc}"


def criar_planilha(caminho, conteudo):
    """
    Monta um .xlsx.

    Cada linha do conteudo e uma linha da planilha; as colunas vem
    separadas por ponto e virgula, tabulacao ou barra vertical. Numero
    entra como numero, para a soma do Excel funcionar.
    """
    _, erro = _importar_para_criar("planilha")

    if erro:
        return None, erro

    try:
        import openpyxl

        livro = openpyxl.Workbook()
        folha = livro.active

        linhas = [l for l in separar_linhas(conteudo) if l.strip()]
        separador = None

        for candidato in ("|", ";", "\t", ","):
            if any(candidato in linha for linha in linhas):
                separador = candidato
                break

        for numero, linha in enumerate(linhas, start=1):
            if separador:
                celulas = [c.strip() for c in linha.split(separador)]
            else:
                celulas = [linha.strip()]

            folha.append([_numero_ou_texto(c) for c in celulas])

            if numero == 1:
                for celula in folha[1]:
                    celula.font = openpyxl.styles.Font(bold=True)

        _ajustar_larguras(folha)
        livro.save(str(caminho))
        return caminho, None

    except Exception as exc:
        return None, f"não consegui montar a planilha: {exc}"


def _numero_ou_texto(valor):
    """"1234,56" vira numero; o resto fica texto."""
    texto = str(valor).strip()

    if not texto:
        return None

    limpo = texto.replace("R$", "").replace("%", "").strip()
    limpo = limpo.replace(".", "").replace(",", ".") \
        if re.fullmatch(r"-?[\d.]*\d(?:,\d+)?", limpo) else limpo

    try:
        numero = float(limpo)
        return int(numero) if numero.is_integer() else numero
    except ValueError:
        return texto


def _ajustar_larguras(folha, maximo=60):
    larguras = {}

    for linha in folha.iter_rows():
        for celula in linha:
            if celula.value is None:
                continue

            tamanho = len(str(celula.value))
            coluna = celula.column_letter

            if tamanho > larguras.get(coluna, 0):
                larguras[coluna] = tamanho

    for coluna, tamanho in larguras.items():
        folha.column_dimensions[coluna].width = min(maximo, tamanho + 2)


def criar_apresentacao(caminho, conteudo):
    """
    Monta um .pptx.

    Cada "# titulo" comeca um slide; as linhas seguintes entram como
    topicos dele. Tambem aceita "---" como separador de slide.
    """
    _, erro = _importar_para_criar("apresentacao")

    if erro:
        return None, erro

    try:
        from pptx import Presentation

        apresentacao = Presentation()
        slides = _separar_slides(conteudo)

        for titulo, topicos in slides:
            if topicos:
                slide = apresentacao.slides.add_slide(
                    apresentacao.slide_layouts[1]
                )
                slide.shapes.title.text = titulo
                quadro = slide.placeholders[1].text_frame
                quadro.text = topicos[0]

                for topico in topicos[1:]:
                    paragrafo = quadro.add_paragraph()
                    paragrafo.text = topico
                    paragrafo.level = 0
            else:
                slide = apresentacao.slides.add_slide(
                    apresentacao.slide_layouts[5]
                )
                slide.shapes.title.text = titulo

        apresentacao.save(str(caminho))
        return caminho, None

    except Exception as exc:
        return None, f"não consegui montar a apresentação: {exc}"


def _separar_slides(conteudo):
    """Devolve [(titulo, [topicos]), ...]."""
    slides = []
    titulo = None
    topicos = []

    for linha in separar_linhas(conteudo):
        texto = linha.strip()

        if not texto:
            continue

        if texto in ("---", "***", "___"):
            if titulo is not None:
                slides.append((titulo, topicos))

            titulo, topicos = None, []
            continue

        if texto.startswith("#"):
            if titulo is not None:
                slides.append((titulo, topicos))

            titulo = texto.lstrip("#").strip()
            topicos = []
            continue

        if titulo is None:
            titulo = texto
            continue

        topicos.append(re.sub(r"^[-*]\s*", "", texto))

    if titulo is not None:
        slides.append((titulo, topicos))

    return slides or [("Sem título", [])]


def criar_pdf(caminho, conteudo):
    """
    Monta um .pdf.

    Texto simples paginado, com "# titulo" em negrito e maior. Nao e
    diagramacao fina, mas e um PDF de verdade, que abre em qualquer
    lugar e da para imprimir.
    """
    _, erro = _importar_para_criar("pdf")

    if erro:
        return None, erro

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas as canvas_pdf

        largura, altura = A4
        margem = 20 * mm
        folha = canvas_pdf.Canvas(str(caminho), pagesize=A4)
        folha.setTitle(Path(caminho).stem)

        y = altura - margem
        linhas = separar_linhas(conteudo) or [""]

        for linha in linhas:
            texto = linha.rstrip()

            if y < margem:
                folha.showPage()
                y = altura - margem

            if not texto:
                y -= 6 * mm
                continue

            if texto.lstrip().startswith("#"):
                nivel = len(texto) - len(texto.lstrip("#"))
                folha.setFont("Helvetica-Bold", 16 if nivel <= 1 else 13)
                texto = texto.lstrip("#").strip()
                y -= 2 * mm
            else:
                folha.setFont("Helvetica", 11)

            # Quebra o que nao cabe na largura da pagina.
            for pedaco in _quebrar(
                texto, folha, largura - 2 * margem
            ):
                if y < margem:
                    folha.showPage()
                    y = altura - margem
                    folha.setFont("Helvetica", 11)

                folha.drawString(margem, y, pedaco)
                y -= 6 * mm

        folha.save()
        return caminho, None

    except Exception as exc:
        return None, f"não consegui montar o PDF: {exc}"


def _quebrar(texto, folha, largura_util):
    """Parte a linha no espaco para caber na largura da pagina."""
    palavras = texto.split()

    if not palavras:
        return [""]

    linhas = []
    atual = palavras[0]

    for palavra in palavras[1:]:
        tentativa = f"{atual} {palavra}"

        if folha.stringWidth(tentativa) <= largura_util:
            atual = tentativa
        else:
            linhas.append(atual)
            atual = palavra

    linhas.append(atual)
    return linhas


MONTADORES = {
    "word": criar_word,
    "planilha": criar_planilha,
    "apresentacao": criar_apresentacao,
    "pdf": criar_pdf,
}


def criar(caminho, conteudo):
    """
    Monta um documento de escritorio a partir de texto.

    Devolve (caminho, None) ou (None, erro). Quem chama ja conferiu a
    permissao do caminho.
    """
    caminho = Path(caminho)
    tipo = da_para_criar(caminho)

    if tipo is None:
        return None, (
            f"não sei montar {caminho.suffix or 'esse tipo'}. "
            "Posso: " + ", ".join(sorted(CRIAVEIS))
        )

    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return None, f"não consegui criar a pasta: {exc}"

    return MONTADORES[tipo](caminho, conteudo)
