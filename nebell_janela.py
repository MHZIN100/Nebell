"""
Controle de janelas e teclado do NEBELL.

Tudo pelo ctypes falando direto com o user32 do Windows: nenhuma
biblioteca para instalar, nenhum grama de VRAM.

  janelas      listar, focar, minimizar, maximizar, restaurar, fechar
  organizar    meia tela esquerda/direita, quatro cantos, tela cheia
  teclado      digitar texto e mandar atalhos (ctrl+c, alt+tab, win+d)

Fora do Windows cada funcao devolve (None, motivo) em vez de estourar,
para dar para testar em qualquer maquina.
"""

import ctypes
import re
import sys
import time
import unicodedata

EH_WINDOWS = sys.platform.startswith("win")

FORA_DO_WINDOWS = "controle de janelas e teclado só funciona no Windows"

# ---- constantes do user32 ----
SW_NORMAL = 1
SW_MINIMIZAR = 6
SW_MAXIMIZAR = 3
SW_RESTAURAR = 9

WM_CLOSE = 0x0010
GW_OWNER = 4

VK = {
    "ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10,
    "win": 0x5B, "windows": 0x5B, "super": 0x5B,
    "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B,
    "escape": 0x1B, "espaco": 0x20, "space": 0x20, "backspace": 0x08,
    "delete": 0x2E, "del": 0x2E, "insert": 0x2D, "home": 0x24,
    "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "cima": 0x26, "up": 0x26, "baixo": 0x28, "down": 0x28,
    "esquerda": 0x25, "left": 0x25, "direita": 0x27, "right": 0x27,
    "printscreen": 0x2C, "print": 0x2C,
}

for _n in range(1, 13):
    VK[f"f{_n}"] = 0x6F + _n

for _c in "abcdefghijklmnopqrstuvwxyz":
    VK[_c] = ord(_c.upper())

for _c in "0123456789":
    VK[_c] = ord(_c)

ATALHOS_NOMEADOS = {
    "copiar": "ctrl+c",
    "colar": "ctrl+v",
    "cortar": "ctrl+x",
    "desfazer": "ctrl+z",
    "refazer": "ctrl+y",
    "salvar": "ctrl+s",
    "selecionar tudo": "ctrl+a",
    "localizar": "ctrl+f",
    "procurar": "ctrl+f",
    "imprimir": "ctrl+p",
    "nova aba": "ctrl+t",
    "fechar aba": "ctrl+w",
    "trocar janela": "alt+tab",
    "mostrar area de trabalho": "win+d",
    "area de trabalho": "win+d",
    "bloquear": "win+l",
    "explorador": "win+e",
    "executar": "win+r",
    "gerenciador de tarefas": "ctrl+shift+esc",
    "atualizar": "f5",
    "tela cheia": "f11",
    "renomear": "f2",
}

# Janelas de sistema que nao interessam em uma listagem.
RUIDO = re.compile(
    r"^(program manager|default ime|msctfime ui|windows input experience"
    r"|nvidia geforce overlay|settings)$",
    re.IGNORECASE,
)


def normalize(texto):
    texto = unicodedata.normalize("NFD", str(texto).lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", texto).strip()


def _user32():
    if not EH_WINDOWS:
        return None

    try:
        return ctypes.windll.user32
    except Exception:
        return None


# ============================================================
# LISTAR
# ============================================================

def listar(incluir_minimizadas=True):
    """
    As janelas abertas agora.

    Devolve (lista de dicionarios, None) ou (None, erro). Cada item tem
    identificador, titulo, minimizada, maximizada, em_foco, largura,
    altura.
    """
    user32 = _user32()

    if user32 is None:
        return None, FORA_DO_WINDOWS

    from ctypes import wintypes

    achadas = []
    foco = user32.GetForegroundWindow()

    TIPO = ctypes.WINFUNCTYPE(
        ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p
    )

    def visitar(janela, _extra):
        try:
            if not user32.IsWindowVisible(janela):
                return True

            # Janelas filhas e caixas de dialogo de outra janela: fora.
            if user32.GetWindow(janela, GW_OWNER):
                return True

            tamanho = user32.GetWindowTextLengthW(janela)

            if tamanho <= 0:
                return True

            buffer = ctypes.create_unicode_buffer(tamanho + 1)
            user32.GetWindowTextW(janela, buffer, tamanho + 1)
            titulo = buffer.value.strip()

            if not titulo or RUIDO.match(titulo):
                return True

            minimizada = bool(user32.IsIconic(janela))

            if minimizada and not incluir_minimizadas:
                return True

            retangulo = wintypes.RECT()
            user32.GetWindowRect(janela, ctypes.byref(retangulo))

            achadas.append({
                "identificador": int(janela),
                "titulo": titulo,
                "minimizada": minimizada,
                "maximizada": bool(user32.IsZoomed(janela)),
                "em_foco": int(janela) == int(foco or 0),
                "largura": retangulo.right - retangulo.left,
                "altura": retangulo.bottom - retangulo.top,
            })

        except Exception:
            pass

        return True

    try:
        user32.EnumWindows(TIPO(visitar), 0)
    except Exception as exc:
        return None, f"não consegui listar as janelas: {exc}"

    achadas.sort(key=lambda j: (not j["em_foco"], j["minimizada"],
                                normalize(j["titulo"])))
    return achadas, None


def descrever_janelas(limite=12):
    """Uma frase falavel com as janelas abertas."""
    janelas, erro = listar()

    if erro:
        return None, erro

    if not janelas:
        return "Não há nenhuma janela aberta.", None

    partes = []

    for janela in janelas[:limite]:
        nota = ""

        if janela["em_foco"]:
            nota = " (em foco)"
        elif janela["minimizada"]:
            nota = " (minimizada)"

        partes.append(janela["titulo"] + nota)

    texto = f"{len(janelas)} janelas abertas: " + "; ".join(partes)

    if len(janelas) > limite:
        texto += f"; e outras {len(janelas) - limite}"

    return texto + ".", None


def achar(alvo, janelas=None):
    """
    Acha a janela pelo pedaco do titulo que a pessoa falou.

    Devolve (janela, None), (None, erro) ou, quando mais de uma casa
    igual, a primeira em foco.
    """
    if janelas is None:
        janelas, erro = listar()

        if erro:
            return None, erro

    procurado = normalize(alvo)

    if not procurado:
        return None, "diga qual janela"

    exatas = [j for j in janelas if normalize(j["titulo"]) == procurado]

    if exatas:
        return exatas[0], None

    comeca = [j for j in janelas if normalize(j["titulo"]).startswith(procurado)]

    if comeca:
        return comeca[0], None

    dentro = [j for j in janelas if procurado in normalize(j["titulo"])]

    if dentro:
        return dentro[0], None

    # Ultima tentativa: todas as palavras do pedido aparecem no titulo.
    palavras = [p for p in procurado.split() if len(p) > 2]

    if palavras:
        for janela in janelas:
            titulo = normalize(janela["titulo"])

            if all(p in titulo for p in palavras):
                return janela, None

    abertas = ", ".join(j["titulo"] for j in janelas[:6]) or "nenhuma"
    return None, f"não achei uma janela de '{alvo}'. Abertas: {abertas}"


# ============================================================
# AGIR SOBRE UMA JANELA
# ============================================================

def _identificador(alvo):
    """Aceita um numero, um dicionario de `listar` ou um titulo."""
    if isinstance(alvo, dict):
        return alvo.get("identificador"), alvo.get("titulo", "a janela"), None

    if isinstance(alvo, int):
        return alvo, "a janela", None

    janela, erro = achar(alvo)

    if erro:
        return None, None, erro

    return janela["identificador"], janela["titulo"], None


def focar(alvo):
    """Traz a janela para a frente, desminimizando se preciso."""
    user32 = _user32()

    if user32 is None:
        return None, FORA_DO_WINDOWS

    janela, titulo, erro = _identificador(alvo)

    if erro:
        return None, erro

    try:
        if user32.IsIconic(janela):
            user32.ShowWindow(janela, SW_RESTAURAR)

        # O Windows recusa SetForegroundWindow de um processo que nao
        # tem o foco; o alt sintetico libera a troca.
        _tecla_crua(user32, VK["alt"], soltar=False)
        user32.SetForegroundWindow(janela)
        _tecla_crua(user32, VK["alt"], soltar=True)

        user32.BringWindowToTop(janela)

    except Exception as exc:
        return None, f"não consegui focar {titulo}: {exc}"

    return titulo, f"{titulo} está na frente."


def mudar_estado(alvo, estado):
    """estado: minimizar, maximizar, restaurar."""
    user32 = _user32()

    if user32 is None:
        return None, FORA_DO_WINDOWS

    codigos = {
        "minimizar": SW_MINIMIZAR, "minimiza": SW_MINIMIZAR,
        "maximizar": SW_MAXIMIZAR, "maximiza": SW_MAXIMIZAR,
        "restaurar": SW_RESTAURAR, "restaura": SW_RESTAURAR,
        "normal": SW_NORMAL,
    }

    codigo = codigos.get(normalize(estado))

    if codigo is None:
        return None, (
            f"não sei o que é '{estado}'. "
            "Posso minimizar, maximizar ou restaurar."
        )

    janela, titulo, erro = _identificador(alvo)

    if erro:
        return None, erro

    try:
        user32.ShowWindow(janela, codigo)
    except Exception as exc:
        return None, f"não consegui mexer em {titulo}: {exc}"

    verbo = {
        SW_MINIMIZAR: "minimizei", SW_MAXIMIZAR: "maximizei",
        SW_RESTAURAR: "restaurei", SW_NORMAL: "restaurei",
    }[codigo]

    return titulo, f"{verbo.capitalize()} {titulo}."


def fechar(alvo):
    """
    Pede para a janela fechar (WM_CLOSE), do mesmo jeito que o X.

    O programa ainda pode perguntar se quer salvar: e de proposito,
    nada e morto a forca.
    """
    user32 = _user32()

    if user32 is None:
        return None, FORA_DO_WINDOWS

    janela, titulo, erro = _identificador(alvo)

    if erro:
        return None, erro

    try:
        user32.PostMessageW(janela, WM_CLOSE, 0, 0)
    except Exception as exc:
        return None, f"não consegui fechar {titulo}: {exc}"

    return titulo, (
        f"Pedi para {titulo} fechar. Se houver algo sem salvar, "
        "o programa vai perguntar."
    )


def minimizar_tudo():
    """Mostra a area de trabalho."""
    return atalho("win+d")


# ============================================================
# ORGANIZAR NA TELA
# ============================================================

POSICOES = (
    "esquerda", "direita", "cima", "baixo", "tela cheia",
    "canto superior esquerdo", "canto superior direito",
    "canto inferior esquerdo", "canto inferior direito",
    "centro",
)


def tamanho_da_tela():
    user32 = _user32()

    if user32 is None:
        return None, None

    try:
        return (int(user32.GetSystemMetrics(0)),
                int(user32.GetSystemMetrics(1)))
    except Exception:
        return None, None


def calcular_area(posicao, largura_tela, altura_tela):
    """
    O retangulo de uma posicao.

    Devolve (x, y, largura, altura) ou None quando a posicao e
    desconhecida. Separado de `posicionar` para dar para testar sem
    Windows.
    """
    pedido = normalize(posicao)
    meia_largura = largura_tela // 2
    meia_altura = altura_tela // 2

    areas = {
        "esquerda": (0, 0, meia_largura, altura_tela),
        "direita": (meia_largura, 0, largura_tela - meia_largura, altura_tela),
        "cima": (0, 0, largura_tela, meia_altura),
        "baixo": (0, meia_altura, largura_tela, altura_tela - meia_altura),
        "tela cheia": (0, 0, largura_tela, altura_tela),
        "canto superior esquerdo": (0, 0, meia_largura, meia_altura),
        "canto superior direito": (meia_largura, 0,
                                   largura_tela - meia_largura, meia_altura),
        "canto inferior esquerdo": (0, meia_altura, meia_largura,
                                    altura_tela - meia_altura),
        "canto inferior direito": (meia_largura, meia_altura,
                                   largura_tela - meia_largura,
                                   altura_tela - meia_altura),
        "centro": (largura_tela // 4, altura_tela // 4,
                   meia_largura, meia_altura),
    }

    if pedido in areas:
        return areas[pedido]

    # Sinonimos soltos da fala.
    for chave, valor in areas.items():
        if chave in pedido or pedido in chave:
            return valor

    if "metade" in pedido and "esquerd" in pedido:
        return areas["esquerda"]

    if "metade" in pedido and "direit" in pedido:
        return areas["direita"]

    return None


def posicionar(alvo, posicao):
    """Joga a janela para uma metade, um canto ou a tela cheia."""
    user32 = _user32()

    if user32 is None:
        return None, FORA_DO_WINDOWS

    largura_tela, altura_tela = tamanho_da_tela()

    if not largura_tela:
        return None, "não consegui medir a tela"

    area = calcular_area(posicao, largura_tela, altura_tela)

    if area is None:
        return None, (
            f"não sei a posição '{posicao}'. Posso: " + ", ".join(POSICOES)
        )

    janela, titulo, erro = _identificador(alvo)

    if erro:
        return None, erro

    x, y, largura, altura = area

    try:
        if user32.IsIconic(janela) or user32.IsZoomed(janela):
            user32.ShowWindow(janela, SW_RESTAURAR)
            time.sleep(0.05)

        user32.MoveWindow(janela, x, y, largura, altura, True)

    except Exception as exc:
        return None, f"não consegui mover {titulo}: {exc}"

    return titulo, f"Coloquei {titulo} em {normalize(posicao)}."


# ============================================================
# TECLADO
# ============================================================

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
INPUT_KEYBOARD = 1

LIMITE_DIGITACAO = 5000

# Acima disto, digitar tecla por tecla fica lento de doer: 400
# caracteres a 4 milissegundos cada ja passam de um segundo e meio, e
# qualquer tecla que a pessoa aperte no meio entra na frase. A partir
# daqui vai pela area de transferencia, que e instantanea.
LIMITE_PARA_COLAR = 400


def _tecla_crua(user32, codigo, soltar):
    """keybd_event: simples e suficiente para modificadores."""
    try:
        user32.keybd_event(codigo, 0, KEYEVENTF_KEYUP if soltar else 0, 0)
        return True
    except Exception:
        return False


def interpretar_atalho(texto):
    """
    "ctrl+shift+n", "copiar", "alt tab" → lista de codigos de tecla.

    Devolve (codigos, None) ou (None, erro).
    """
    pedido = normalize(texto)
    pedido = ATALHOS_NOMEADOS.get(pedido, pedido)

    pecas = [p for p in re.split(r"[+\s,]+", pedido) if p]

    if not pecas:
        return None, "diga qual atalho"

    codigos = []

    for peca in pecas:
        codigo = VK.get(peca)

        if codigo is None:
            return None, f"não conheço a tecla '{peca}'"

        codigos.append(codigo)

    if len(codigos) > 4:
        return None, "esse atalho tem teclas demais"

    return codigos, None


def atalho(texto):
    """Manda um atalho de teclado para quem esta em foco."""
    user32 = _user32()

    if user32 is None:
        return None, FORA_DO_WINDOWS

    codigos, erro = interpretar_atalho(texto)

    if erro:
        return None, erro

    try:
        for codigo in codigos:
            _tecla_crua(user32, codigo, soltar=False)
            time.sleep(0.01)

        for codigo in reversed(codigos):
            _tecla_crua(user32, codigo, soltar=True)
            time.sleep(0.01)

    except Exception as exc:
        return None, f"o atalho falhou: {exc}"

    return normalize(texto), f"Mandei {normalize(texto)}."


def _estrutura_de_entrada():
    """A struct INPUT do Windows, montada na hora para nao pesar."""
    from ctypes import wintypes

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class UNIAO(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("preenchimento", ctypes.c_byte * 32)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("uniao", UNIAO)]

    return INPUT, KEYBDINPUT, UNIAO


def colar_texto(texto):
    """
    Alternativa mais rapida para textos grandes: area de transferencia
    mais ctrl+v. Devolve (quantidade, mensagem) ou (None, erro).
    """
    user32 = _user32()

    if user32 is None:
        return None, FORA_DO_WINDOWS

    try:
        import subprocess

        subprocess.run(
            ["clip"], input=str(texto).encode("utf-16-le"),
            check=True, timeout=10,
        )

    except Exception as exc:
        return None, f"não consegui usar a área de transferência: {exc}"

    enviado, erro = atalho("ctrl+v")

    if enviado is None:
        return None, erro

    return len(str(texto)), "Colei o texto na janela em foco."


def digitar(texto, intervalo=0.004, forcar_tecla=False):
    """
    Escreve o texto na janela que esta em foco.

    Usa SendInput em modo unicode, entao acento e cedilha saem certos
    em qualquer layout de teclado. Texto longo vai pela area de
    transferencia, que e instantanea; passe forcar_tecla para obrigar a
    digitacao tecla por tecla (campos que recusam colar).
    """
    user32 = _user32()

    if user32 is None:
        return None, FORA_DO_WINDOWS

    texto = str(texto or "")

    if not texto:
        return None, "não disse o que escrever"

    if len(texto) > LIMITE_DIGITACAO:
        return None, (
            f"isso tem {len(texto)} caracteres; digito até {LIMITE_DIGITACAO} "
            "de uma vez"
        )

    if len(texto) > LIMITE_PARA_COLAR and not forcar_tecla:
        quantos, mensagem = colar_texto(texto)

        if quantos:
            return quantos, mensagem

        # A area de transferencia falhou: segue digitando, mais devagar
        # mas sem deixar de escrever.

    try:
        INPUT, KEYBDINPUT, UNIAO = _estrutura_de_entrada()

        for caractere in texto:
            if caractere == "\n":
                _tecla_crua(user32, VK["enter"], soltar=False)
                _tecla_crua(user32, VK["enter"], soltar=True)
                time.sleep(intervalo)
                continue

            for soltar in (False, True):
                tecla = KEYBDINPUT(
                    wVk=0,
                    wScan=ord(caractere),
                    dwFlags=KEYEVENTF_UNICODE | (
                        KEYEVENTF_KEYUP if soltar else 0
                    ),
                    time=0,
                    dwExtraInfo=None,
                )

                entrada = INPUT(type=INPUT_KEYBOARD, uniao=UNIAO(ki=tecla))

                user32.SendInput(
                    1, ctypes.byref(entrada), ctypes.sizeof(INPUT)
                )

            time.sleep(intervalo)

    except Exception as exc:
        return None, f"não consegui digitar: {exc}"

    return len(texto), f"Digitei {len(texto)} caracteres."
