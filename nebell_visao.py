"""
Visao do NEBELL: ler a tela, ler imagens e editar imagens.

Nada aqui gasta VRAM nem precisa de um modelo de visao, o que importa
em uma maquina com 6 GB de placa e 8 GB de memoria: o modelo de
conversa continua sozinho na placa.

  captura    Pillow (ImageGrab), nativo do Windows
  OCR        Tesseract pelo pytesseract: le o texto que esta na imagem
  edicao     Pillow: redimensionar, recortar, girar, converter, comprimir

O OCR resolve 90 por cento do "o que diz aqui na tela": mensagem de
erro, texto de pagina, numero em um print. Descrever uma FOTO ("e um
cachorro na praia") e outra coisa e precisaria de um modelo de visao;
isso fica como opcional, descrito no fim do arquivo.
"""

import re
import shutil
import unicodedata
from pathlib import Path

try:
    from PIL import Image, ImageEnhance, ImageFilter, ImageGrab, ImageOps
except Exception:
    Image = ImageEnhance = ImageFilter = ImageGrab = ImageOps = None

try:
    import pytesseract
except Exception:
    pytesseract = None


# Caminhos onde o Tesseract costuma ficar no Windows.
TESSERACT_CAMINHOS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)

IDIOMA_OCR = "por+eng"       # portugues e ingles juntos
MAX_TEXTO = 4000

FORMATOS = {
    ".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP",
    ".bmp": "BMP", ".gif": "GIF", ".tiff": "TIFF", ".ico": "ICO",
}

_tesseract_pronto = [None]


def normalize(texto):
    texto = unicodedata.normalize("NFD", str(texto).lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", texto).strip()


def tem_pillow():
    return Image is not None


def achar_tesseract():
    """Acha o executavel do Tesseract e deixa o pytesseract pronto."""
    if _tesseract_pronto[0] is not None:
        return _tesseract_pronto[0]

    if pytesseract is None:
        _tesseract_pronto[0] = ""
        return ""

    encontrado = shutil.which("tesseract")

    if not encontrado:
        for caminho in TESSERACT_CAMINHOS:
            if Path(caminho).is_file():
                encontrado = caminho
                break

    if encontrado:
        try:
            pytesseract.pytesseract.tesseract_cmd = encontrado
        except Exception:
            pass

    _tesseract_pronto[0] = encontrado or ""
    return _tesseract_pronto[0]


def falta_o_que(para_ocr=False):
    """Diz o que precisa instalar, com o comando pronto."""
    faltando = []

    if not tem_pillow():
        faltando.append("pip install pillow")

    if para_ocr:
        if pytesseract is None:
            faltando.append("pip install pytesseract")

        if not achar_tesseract():
            faltando.append(
                "instalar o Tesseract: "
                "https://github.com/UB-Mannheim/tesseract/wiki "
                "(marque o idioma Portuguese na instalação)"
            )

    return faltando


# ============================================================
# CAPTURA DE TELA
# ============================================================

def capturar_tela(destino, regiao=None, monitor_inteiro=True):
    """
    Tira um print. `regiao` e (x1, y1, x2, y2) quando quiser um pedaco.

    Devolve (caminho, None) ou (None, erro).
    """
    if not tem_pillow():
        return None, (
            "Preciso do Pillow para ver a tela. Instale com: pip install pillow"
        )

    destino = Path(destino)

    try:
        destino.parent.mkdir(parents=True, exist_ok=True)

        if regiao:
            imagem = ImageGrab.grab(bbox=tuple(regiao))
        else:
            # all_screens pega os dois monitores quando existem.
            try:
                imagem = ImageGrab.grab(all_screens=monitor_inteiro)
            except TypeError:
                imagem = ImageGrab.grab()

        imagem.save(destino)
        return destino, None

    except Exception as exc:
        return None, f"não consegui capturar a tela: {exc}"


def janela_em_foco_retangulo():
    """
    O retangulo da janela que esta na frente, para capturar so ela.

    Devolve (x1, y1, x2, y2) ou None.
    """
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        janela = user32.GetForegroundWindow()

        if not janela:
            return None

        retangulo = wintypes.RECT()
        user32.GetWindowRect(janela, ctypes.byref(retangulo))

        if retangulo.right <= retangulo.left:
            return None

        return (
            retangulo.left, retangulo.top, retangulo.right, retangulo.bottom
        )

    except Exception:
        return None


# ============================================================
# OCR
# ============================================================

def preparar_para_ocr(imagem):
    """
    Deixa a imagem mais legivel para o OCR.

    Tons de cinza, aumento de escala e contraste: numa captura de tela
    a fonte e pequena, e isso melhora bastante o acerto.
    """
    try:
        trabalho = imagem.convert("L")

        largura, altura = trabalho.size

        if max(largura, altura) < 2600:
            escala = 2
            trabalho = trabalho.resize(
                (largura * escala, altura * escala), Image.LANCZOS
            )

        trabalho = ImageEnhance.Contrast(trabalho).enhance(1.6)
        trabalho = trabalho.filter(ImageFilter.SHARPEN)
        return trabalho

    except Exception:
        return imagem


def ler_texto(caminho_ou_imagem, idioma=IDIOMA_OCR, preparar=True):
    """
    Le o texto escrito em uma imagem.

    Devolve (texto, None) ou (None, erro).
    """
    faltando = falta_o_que(para_ocr=True)

    if faltando:
        return None, (
            "Para ler o que está escrito na imagem preciso de: "
            + "; ".join(faltando)
        )

    try:
        if isinstance(caminho_ou_imagem, (str, Path)):
            caminho = Path(caminho_ou_imagem)

            if not caminho.is_file():
                return None, f"não encontrei o arquivo {caminho}"

            imagem = Image.open(caminho)
        else:
            imagem = caminho_ou_imagem

        alvo = preparar_para_ocr(imagem) if preparar else imagem

        texto = pytesseract.image_to_string(alvo, lang=idioma)

    except Exception as exc:
        # Idioma nao instalado: tenta so o ingles antes de desistir.
        if "por" in str(idioma) and "lang" in str(exc).lower():
            try:
                texto = pytesseract.image_to_string(alvo, lang="eng")
            except Exception as outro:
                return None, f"o OCR falhou: {outro}"
        else:
            return None, f"o OCR falhou: {exc}"

    limpo = re.sub(r"[ \t]+", " ", texto or "")
    limpo = re.sub(r"\n\s*\n\s*\n+", "\n\n", limpo).strip()

    if not limpo:
        return None, "não há texto legível nessa imagem"

    return limpo[:MAX_TEXTO], None


def ler_tela(pasta_temporaria, apenas_janela=False):
    """
    Captura e le o que esta escrito na tela agora.

    Devolve (texto, None) ou (None, erro).
    """
    regiao = janela_em_foco_retangulo() if apenas_janela else None
    destino = Path(pasta_temporaria) / "tela_ocr.png"

    caminho, erro = capturar_tela(destino, regiao=regiao)

    if erro:
        return None, erro

    texto, erro = ler_texto(caminho)

    try:
        caminho.unlink()
    except Exception:
        pass

    return texto, erro


# ============================================================
# INFORMACAO E EDICAO DE IMAGEM
# ============================================================

def informacao(caminho):
    """Dados basicos de uma imagem, sem precisar de modelo nenhum."""
    if not tem_pillow():
        return None, "Preciso do Pillow: pip install pillow"

    caminho = Path(caminho)

    if not caminho.is_file():
        return None, f"não encontrei {caminho}"

    try:
        with Image.open(caminho) as imagem:
            dados = {
                "nome": caminho.name,
                "formato": imagem.format,
                "modo": imagem.mode,
                "largura": imagem.width,
                "altura": imagem.height,
                "tamanho_bytes": caminho.stat().st_size,
            }

            # Cor media: da para dizer se e clara ou escura.
            try:
                pequena = imagem.convert("RGB").resize((1, 1))
                dados["cor_media"] = pequena.getpixel((0, 0))
            except Exception:
                pass

        return dados, None

    except Exception as exc:
        return None, f"não consegui abrir a imagem: {exc}"


def descrever(caminho):
    """Uma frase falavel sobre a imagem."""
    dados, erro = informacao(caminho)

    if erro:
        return None, erro

    megapixels = (dados["largura"] * dados["altura"]) / 1_000_000
    kb = dados["tamanho_bytes"] / 1024

    partes = [
        f"{dados['nome']}: {dados['largura']} por {dados['altura']} pixels",
        f"{dados['formato']}",
    ]

    if megapixels >= 0.5:
        partes.append(f"{megapixels:.1f} megapixels")

    partes.append(
        f"{kb / 1024:.1f} megabytes" if kb > 1024 else f"{kb:.0f} kilobytes"
    )

    cor = dados.get("cor_media")

    if cor:
        brilho = sum(cor) / 3
        partes.append("imagem escura" if brilho < 90 else
                      "imagem clara" if brilho > 170 else "tom médio")

    return ". ".join(partes) + ".", None


def destino_para(origem, sufixo, formato=None):
    """Nome do arquivo de saida, ao lado do original."""
    origem = Path(origem)
    extensao = f".{formato.lower()}" if formato else origem.suffix
    return origem.with_name(f"{origem.stem}_{sufixo}{extensao}")


def editar(caminho, acao, valor=None, destino=None):
    """
    Edita a imagem e grava um arquivo NOVO, nunca em cima do original.

    Acoes: redimensionar, recortar, girar, espelhar, cinza, comprimir,
    converter, clarear, escurecer, borrar, nitidez, contorno.

    Devolve (caminho_novo, mensagem) ou (None, erro).
    """
    if not tem_pillow():
        return None, "Preciso do Pillow: pip install pillow"

    origem = Path(caminho)

    if not origem.is_file():
        return None, f"não encontrei {origem}"

    acao = normalize(acao)

    try:
        with Image.open(origem) as aberta:
            imagem = aberta.copy()
            formato_origem = aberta.format

    except Exception as exc:
        return None, f"não consegui abrir a imagem: {exc}"

    qualidade = 85
    sufixo = acao or "editada"
    novo_formato = None

    try:
        if acao in ("redimensionar", "redimensiona", "tamanho", "escala"):
            imagem, sufixo = _redimensionar(imagem, valor)

        elif acao in ("recortar", "recorta", "cortar", "corta"):
            imagem, sufixo = _recortar(imagem, valor)

        elif acao in ("girar", "gira", "rotacionar", "rodar"):
            graus = _para_numero(valor, 90)
            imagem = imagem.rotate(-graus, expand=True)
            sufixo = f"girada{int(graus)}"

        elif acao in ("espelhar", "espelha", "inverter"):
            vertical = bool(valor) and normalize(valor).startswith("vert")
            imagem = ImageOps.flip(imagem) if vertical else ImageOps.mirror(imagem)
            sufixo = "espelhada"

        elif acao in ("cinza", "preto e branco", "pb", "monocromatico"):
            imagem = imagem.convert("L")
            sufixo = "cinza"

        elif acao in ("comprimir", "comprime", "reduzir peso", "otimizar"):
            qualidade = int(max(20, min(95, _para_numero(valor, 60))))
            novo_formato = "JPEG"

            if imagem.mode in ("RGBA", "P", "LA"):
                imagem = imagem.convert("RGB")

            sufixo = "comprimida"

        elif acao in ("converter", "converte", "formato"):
            pedido = normalize(valor or "png").lstrip(".")
            novo_formato = FORMATOS.get(f".{pedido}")

            if novo_formato is None:
                return None, (
                    f"não sei converter para {pedido}. "
                    "Posso: " + ", ".join(sorted(
                        {v.lower() for v in FORMATOS.values()}
                    ))
                )

            if novo_formato == "JPEG" and imagem.mode in ("RGBA", "P", "LA"):
                imagem = imagem.convert("RGB")

            sufixo = "convertida"

        elif acao in ("clarear", "clareia", "mais claro"):
            imagem = ImageEnhance.Brightness(imagem).enhance(
                1 + _para_numero(valor, 30) / 100
            )
            sufixo = "clara"

        elif acao in ("escurecer", "escurece", "mais escuro"):
            imagem = ImageEnhance.Brightness(imagem).enhance(
                max(0.1, 1 - _para_numero(valor, 30) / 100)
            )
            sufixo = "escura"

        elif acao in ("contraste",):
            imagem = ImageEnhance.Contrast(imagem).enhance(
                1 + _para_numero(valor, 40) / 100
            )
            sufixo = "contraste"

        elif acao in ("borrar", "borra", "desfocar"):
            imagem = imagem.filter(
                ImageFilter.GaussianBlur(_para_numero(valor, 4))
            )
            sufixo = "borrada"

        elif acao in ("nitidez", "aguçar", "aguçada", "sharpen"):
            imagem = imagem.filter(ImageFilter.SHARPEN)
            sufixo = "nitida"

        elif acao in ("contorno", "bordas"):
            imagem = imagem.convert("L").filter(ImageFilter.FIND_EDGES)
            sufixo = "contorno"

        elif acao in ("miniatura", "thumbnail"):
            lado = _para_numero(valor, 320)
            imagem.thumbnail((lado, lado), Image.LANCZOS)
            sufixo = "miniatura"

        else:
            return None, (
                f"não conheço a edição '{acao}'. Posso: redimensionar, "
                "recortar, girar, espelhar, cinza, comprimir, converter, "
                "clarear, escurecer, contraste, borrar, nitidez, contorno, "
                "miniatura."
            )

    except ValueError as exc:
        return None, str(exc)
    except Exception as exc:
        return None, f"a edição falhou: {exc}"

    saida = Path(destino) if destino else destino_para(
        origem, sufixo, novo_formato
    )

    try:
        saida.parent.mkdir(parents=True, exist_ok=True)

        if novo_formato == "JPEG" or saida.suffix.lower() in (".jpg", ".jpeg"):
            if imagem.mode in ("RGBA", "P", "LA"):
                imagem = imagem.convert("RGB")

            imagem.save(saida, "JPEG", quality=qualidade, optimize=True)
        else:
            imagem.save(saida)

    except Exception as exc:
        return None, f"não consegui gravar: {exc}"

    antes = origem.stat().st_size
    depois = saida.stat().st_size

    mensagem = f"Gravei {saida.name} ({imagem.width} por {imagem.height} pixels"

    if acao.startswith("comprim") and antes:
        diferenca = 100 - depois * 100 // antes

        if diferenca > 0:
            mensagem += f", {diferenca} por cento menor"
        else:
            mensagem += ", mas não ficou menor: o original já estava enxuto"

    return saida, mensagem + ")."


def _para_numero(valor, padrao):
    if valor is None or valor == "":
        return padrao

    try:
        return float(str(valor).replace(",", ".").strip().rstrip("%px "))
    except ValueError:
        achado = re.search(r"-?\d+(?:[.,]\d+)?", str(valor))

        if achado:
            return float(achado.group(0).replace(",", "."))

        return padrao


def _redimensionar(imagem, valor):
    """Aceita "800x600", "50%", "800" (largura) ou "metade"."""
    pedido = normalize(valor or "50%")

    if pedido in ("metade", "meio"):
        pedido = "50%"
    elif pedido in ("dobro", "duas vezes"):
        pedido = "200%"

    par = re.search(r"(\d+)\s*[x×por]+\s*(\d+)", pedido)

    if par:
        largura, altura = int(par.group(1)), int(par.group(2))
    elif "%" in pedido:
        fator = _para_numero(pedido, 50) / 100

        if fator <= 0:
            raise ValueError("a porcentagem tem de ser maior que zero")

        largura = max(1, int(imagem.width * fator))
        altura = max(1, int(imagem.height * fator))
    else:
        largura = int(_para_numero(pedido, imagem.width))

        if largura <= 0:
            raise ValueError("a largura tem de ser maior que zero")

        altura = max(1, round(imagem.height * largura / imagem.width))

    if largura > 20000 or altura > 20000:
        raise ValueError("esse tamanho é grande demais")

    return imagem.resize((largura, altura), Image.LANCZOS), f"{largura}x{altura}"


def _recortar(imagem, valor):
    """Aceita "x,y,largura,altura" ou "centro 50%"."""
    pedido = normalize(valor or "centro 80%")

    numeros = [int(n) for n in re.findall(r"\d+", pedido)]

    if "centro" in pedido or len(numeros) == 1:
        fator = (numeros[0] if numeros else 80) / 100

        if not 0 < fator <= 1:
            raise ValueError("a porcentagem do recorte tem de ficar entre 1 e 100")

        largura = int(imagem.width * fator)
        altura = int(imagem.height * fator)
        esquerda = (imagem.width - largura) // 2
        topo = (imagem.height - altura) // 2
        caixa = (esquerda, topo, esquerda + largura, topo + altura)

    elif len(numeros) >= 4:
        x, y, largura, altura = numeros[:4]
        caixa = (x, y, min(x + largura, imagem.width),
                 min(y + altura, imagem.height))
    else:
        raise ValueError(
            "diga o recorte como 'centro 60%' ou 'x, y, largura, altura'"
        )

    if caixa[2] <= caixa[0] or caixa[3] <= caixa[1]:
        raise ValueError("esse recorte não sobra nada da imagem")

    return imagem.crop(caixa), "recortada"


# ============================================================
# OPCIONAL: ENTENDER O CONTEUDO DA IMAGEM
# ============================================================
# Descrever uma foto ("um cachorro na praia") exige um modelo de visao.
# O menor que presta e o moondream, com cerca de 1,7 GB. Em uma placa
# de 6 GB ele nao cabe junto com o modelo de conversa: o Ollama troca
# um pelo outro, o que custa alguns segundos a cada troca.
#
# Para ligar:   ollama pull moondream
# e em nebell.py:   VISION_MODEL = "moondream"
#
# Sem isso, o OCR ja le tudo que esta ESCRITO, que e o caso de uso mais
# comum: mensagem de erro, texto de pagina, numero em um print.

def descrever_com_modelo(caminho, url_ollama, modelo, timeout=120):
    """
    Pede a um modelo de visao para descrever a imagem.

    Usado so quando VISION_MODEL esta configurado.
    """
    import base64
    import json
    import urllib.request

    caminho = Path(caminho)

    if not caminho.is_file():
        return None, f"não encontrei {caminho}"

    try:
        dados = base64.b64encode(caminho.read_bytes()).decode("ascii")

        corpo = json.dumps({
            "model": modelo,
            "prompt": (
                "Descreva esta imagem em português, em duas frases, "
                "dizendo o que aparece nela."
            ),
            "images": [dados],
            "stream": False,
        }).encode("utf-8")

        pedido = urllib.request.Request(
            url_ollama.replace("/api/chat", "/api/generate"),
            data=corpo,
            headers={"Content-Type": "application/json"},
        )

        with urllib.request.urlopen(pedido, timeout=timeout) as resposta:
            resultado = json.loads(resposta.read().decode("utf-8", "replace"))

        texto = (resultado.get("response") or "").strip()

        if not texto:
            return None, "o modelo de visão não devolveu nada"

        return texto, None

    except Exception as exc:
        return None, f"o modelo de visão falhou: {exc}"
