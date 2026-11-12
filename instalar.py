"""
Instalacao completa do NEBELL, do zero.

Roda com o Python do sistema, ANTES de existir qualquer ambiente, e
por isso nao importa nada fora da biblioteca padrao. Cada passo e
independente: um que falha e relatado no fim, nao derruba os outros.

Da para rodar de novo quantas vezes quiser -- ele pula o que ja esta
pronto.

    python instalar.py
    python instalar.py --sem-tesseract     (pula o OCR)
    python instalar.py --so-conferir       (nao instala, so relata)

Ou dois cliques no Instalar.bat, que e o caminho normal.
"""

import os
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent
VENV = AQUI / ".venv"
IS_WINDOWS = os.name == "nt"

MODELO = "qwen3.5:4b"

OLLAMA_URL = "https://ollama.com/download/OllamaSetup.exe"
OLLAMA_PAGINA = "https://ollama.com/download"

# O instalador do Tesseract muda de nome a cada versao. Tenta alguns
# e, se nenhum servir, manda a pessoa na pagina -- melhor do que
# fingir que deu certo.
TESSERACT_URLS = [
    "https://digi.bib.uni-mannheim.de/tesseract/tesseract-ocr-w64-setup-5.5.0.20241111.exe",
    "https://digi.bib.uni-mannheim.de/tesseract/tesseract-ocr-w64-setup-5.4.0.20240606.exe",
    "https://digi.bib.uni-mannheim.de/tesseract/tesseract-ocr-w64-setup-5.3.3.20231005.exe",
]
TESSERACT_PAGINA = "https://github.com/UB-Mannheim/tesseract/wiki"

# Em blocos, de propósito: se um pacote difícil falhar (o pyaudio é o
# costumeiro), os outros já entraram e o NEBELL abre mesmo assim, só
# sem aquele recurso.
BLOCOS = [
    ("voz e conversa", ["piper-tts", "requests"]),
    ("escuta por voz", ["faster-whisper", "SpeechRecognition"]),
    ("escuta na placa de vídeo", ["nvidia-cublas-cu12", "nvidia-cudnn-cu12"]),
    ("áudio do microfone", ["pyaudio"]),
    ("janela e medidores", ["pywebview", "psutil"]),
    ("internet e imagens", ["ddgs", "pillow", "pytesseract"]),
    ("documentos", ["pypdf", "python-docx", "openpyxl", "python-pptx",
                    "reportlab"]),
]

# modulo -> para que serve. Usado no relatorio do fim.
CONFERIR = [
    ("piper", "voz"),
    ("requests", "internet"),
    ("faster_whisper", "escuta por voz"),
    ("speech_recognition", "microfone"),
    ("pyaudio", "corte da fala"),
    ("webview", "janela"),
    ("psutil", "medidores da máquina"),
    ("ddgs", "busca na web"),
    ("PIL", "imagens e captura de tela"),
    ("pytesseract", "ler texto de imagem"),
    ("pypdf", "PDF"),
    ("docx", "Word"),
    ("openpyxl", "Excel"),
    ("pptx", "PowerPoint"),
    ("reportlab", "criar PDF"),
]

ESSENCIAIS = {"piper", "requests"}

recado = []

# Quantas vezes o instalador repete sozinho os passos que faltaram antes
# de desistir, e a pausa entre as repetições. Numa conexão instável um
# download cai no meio; repetir aproveita o que já entrou e termina o
# resto, sem a pessoa ter que reabrir o instalador.
MAX_PASSADAS = 6
PAUSA_ENTRE_PASSADAS = 3


def anotar(ok, texto):
    recado.append((ok, texto))


def titulo(texto):
    print()
    print("=" * 64)
    print(" " + texto)
    print("=" * 64)


def passo(texto):
    print()
    print(f"-- {texto}")


def tamanho_legivel(n):
    for unidade in ("B", "KB", "MB", "GB"):
        if n < 1024 or unidade == "GB":
            return f"{n:.0f} {unidade}" if unidade == "B" else f"{n:.1f} {unidade}"

        n /= 1024


def python_do_venv():
    if IS_WINDOWS:
        return VENV / "Scripts" / "python.exe"

    return VENV / "bin" / "python"


def roda(comando, mostrar=True, tempo=None):
    """Roda e devolve (deu_certo, saida)."""
    try:
        r = subprocess.run(
            comando,
            capture_output=not mostrar,
            text=True,
            timeout=tempo,
            encoding="utf-8",
            errors="replace",
        )
        saida = (r.stdout or "") + (r.stderr or "") if not mostrar else ""
        return r.returncode == 0, saida

    except FileNotFoundError:
        return False, "não achei o programa"

    except subprocess.TimeoutExpired:
        return False, "demorou demais"

    except Exception as exc:
        return False, str(exc)


def existe_programa(nome):
    return shutil.which(nome) is not None


# ============================================================
# BAIXAR
# ============================================================

def baixar(url, destino, rotulo, tentativas=3):
    """
    Baixa mostrando o andamento. Devolve True só quando o arquivo chega
    INTEIRO (o tamanho bate com o que o servidor anunciou). Se a conexão
    cai no meio, tenta de novo algumas vezes, do zero -- é mais seguro
    para um .exe do que emendar um pedaço talvez corrompido.
    """
    print(f"   baixando {rotulo} ...")
    print(f"   {url}")

    contexto = ssl.create_default_context()
    falha = ""

    for tentativa in range(1, tentativas + 1):
        comecou = time.time()
        ultimo = [0.0]

        def andamento(feito, total):
            if total <= 0:
                return

            agora = time.time()

            if agora - ultimo[0] < 0.6 and feito < total:
                return

            ultimo[0] = agora
            feito = min(total, feito)
            pc = feito * 100 / total
            print(
                f"\r   {pc:5.1f}%  {tamanho_legivel(feito)} de "
                f"{tamanho_legivel(total)}      ",
                end="",
                flush=True,
            )

        try:
            pedido = urllib.request.Request(
                url, headers={"User-Agent": "NEBELL-instalador"}
            )

            with urllib.request.urlopen(
                pedido, context=contexto, timeout=60
            ) as f:
                total = int(f.headers.get("Content-Length") or 0)
                destino.parent.mkdir(parents=True, exist_ok=True)
                feito = 0

                with open(destino, "wb") as saida:
                    while True:
                        pedaco = f.read(65536)

                        if not pedaco:
                            break

                        saida.write(pedaco)
                        feito += len(pedaco)
                        andamento(feito, total)

            print()

            # Download cortado: o servidor disse um tamanho e veio menos.
            # Um .exe pela metade "instala" e falha de um jeito confuso.
            if total > 0 and feito < total:
                raise OSError(
                    f"veio só {tamanho_legivel(feito)} de "
                    f"{tamanho_legivel(total)}"
                )

            levou = time.time() - comecou
            print(f"   pronto: {tamanho_legivel(destino.stat().st_size)} "
                  f"em {levou:.0f}s")
            return True

        except Exception as exc:
            falha = str(exc)
            print()
            print(f"   não consegui baixar: {falha}")

            if destino.exists():
                try:
                    destino.unlink()
                except Exception:
                    pass

            if tentativa < tentativas:
                print(f"   tentando de novo ({tentativa + 1}/{tentativas})...")

    return False


# ============================================================
# PASSOS
# ============================================================

PYTHON_MINIMO = (3, 10)
PYTHON_MAXIMO = (3, 12)


def versao_serve(versao):
    """O pyaudio so tem versao pronta (sem compilador) ate o 3.12."""
    return PYTHON_MINIMO <= tuple(versao[:2]) <= PYTHON_MAXIMO


def versao_do_venv(vpy):
    ok, saida = roda(
        [str(vpy), "-c",
         "import sys; print(sys.version_info[0], sys.version_info[1])"],
        mostrar=False, tempo=60,
    )

    try:
        partes = saida.strip().split()[-2:]
        return (int(partes[0]), int(partes[1]))
    except Exception:
        return None


def criar_ambiente():
    passo("Ambiente do projeto (.venv)")

    vpy = python_do_venv()

    if vpy.exists():
        ok, _ = roda([str(vpy), "-c", "import sys"], mostrar=False, tempo=60)

        versao = versao_do_venv(vpy) if ok else None

        if ok and (versao is None or versao_serve(versao)):
            print("   já existe e funciona.")
            anotar(True, "ambiente .venv")
            return vpy

        # Um .venv copiado de OUTRA maquina guarda o caminho do Python
        # de origem dentro de si e nao roda aqui. Guarda e refaz. O
        # mesmo vale para um .venv feito com um Python novo demais.
        if ok:
            print(f"   o .venv usa o Python {versao[0]}.{versao[1]}, e o "
                  "pyaudio (microfone)")
            print("   não tem versão pronta para ele. Vou refazer com o "
                  "Python certo.")
            print("   O antigo fica como .venv_antigo.")
        else:
            print("   o .venv que está aqui não roda nesta máquina (veio de")
            print("   outro computador). Guardando como .venv_antigo.")

        velho = AQUI / ".venv_antigo"

        try:
            if velho.exists():
                shutil.rmtree(velho)

            shutil.move(str(VENV), str(velho))
        except Exception as exc:
            print(f"   não consegui guardar o antigo: {exc}")

    print("   criando ...")
    ok, saida = roda([sys.executable, "-m", "venv", str(VENV)],
                     mostrar=False, tempo=300)

    if not ok or not vpy.exists():
        print(f"   falhou: {saida.strip()[:300]}")
        anotar(False, "ambiente .venv — sem ele nada mais entra")
        return None

    print("   criado.")
    anotar(True, "ambiente .venv")
    return vpy


def instalar_pacotes(vpy):
    passo("Pacotes do Python")

    roda([str(vpy), "-m", "pip", "install", "--upgrade", "pip"],
         mostrar=False, tempo=600)

    falharam = []

    for numero, (nome, pacotes) in enumerate(BLOCOS, start=1):
        print(f"\n   [{numero}/{len(BLOCOS)}] {nome}: {', '.join(pacotes)}")

        # Cada bloco é tentado mais de uma vez: numa conexão instável um
        # download do pip cai, mas o pip retoma o que já baixou, então
        # repetir costuma resolver sem precisar rodar o instalador de novo.
        # O --retries/--timeout fazem o próprio pip insistir em cada pacote.
        ok, saida = False, ""

        for tentativa in range(1, 4):
            ok, saida = roda(
                [str(vpy), "-m", "pip", "install",
                 "--retries", "5", "--timeout", "60", "--quiet", *pacotes],
                mostrar=False, tempo=1800,
            )

            if ok:
                break

            if tentativa < 3:
                print(f"   a conexão falhou; tentando de novo "
                      f"({tentativa + 1}/3)...")

        if ok:
            print("   ok")
        else:
            print("   não entrou, mesmo tentando 3 vezes. O resto continua.")
            ultimas = [l for l in saida.strip().split("\n") if l.strip()][-3:]

            for linha in ultimas:
                print(f"     {linha[:120]}")

            falharam.append(nome)

    if falharam:
        anotar(False, "pacotes que não entraram: " + ", ".join(falharam))
    else:
        anotar(True, "pacotes do Python")


def instalar_ollama(permitir_gui=True):
    """
    O Ollama e quem pensa. Sem ele o NEBELL abre mas nao responde.

    O instalador e Inno Setup e aceita instalacao silenciosa, mas isso
    nao esta documentado -- entao aqui ele e TESTADO: se o silencio
    nao funcionar, o instalador abre na tela para a pessoa clicar, em
    vez de o script dizer que deu certo sem ter dado.
    """
    passo("Ollama (o motor que pensa)")

    if existe_programa("ollama"):
        ok, saida = roda(["ollama", "--version"], mostrar=False, tempo=30)

        if ok:
            print(f"   já instalado: {saida.strip().splitlines()[0][:60]}")
            anotar(True, "Ollama")
            return True

    if not IS_WINDOWS:
        print("   fora do Windows, instale pelo site: " + OLLAMA_PAGINA)
        anotar(False, "Ollama — instale manualmente")
        return False

    destino = AQUI / "_download" / "OllamaSetup.exe"

    if not baixar(OLLAMA_URL, destino, "o instalador do Ollama"):
        print(f"   baixe na mão em {OLLAMA_PAGINA} e rode isto de novo.")
        # O endereco vai no RESUMO tambem: quem roda isso le o resumo
        # no fim, nao o que passou voando no meio.
        anotar(False, "Ollama — não consegui baixar. Pegue em " + OLLAMA_PAGINA)
        return False

    print("   instalando em silêncio ...")
    roda([str(destino), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
         mostrar=False, tempo=900)

    # O PATH desta janela nao enxerga o que acabou de ser instalado;
    # procura no lugar onde o instalador poe.
    achou = achar_ollama()

    if not achou and permitir_gui:
        print()
        print("   A instalação silenciosa não pegou. Vou abrir o")
        print("   instalador na tela: clique em avançar até o fim e")
        print("   depois volte aqui.")
        print()

        try:
            subprocess.run([str(destino)], timeout=1800)
        except Exception as exc:
            print(f"   não consegui abrir: {exc}")

        achou = achar_ollama()

    if achou:
        print(f"   instalado: {achou}")
        anotar(True, "Ollama")
        return True

    print("   não encontrei o Ollama depois de instalar.")
    anotar(False, "Ollama — instale por " + OLLAMA_PAGINA)
    return False


def achar_ollama():
    """O ollama.exe, venha do PATH ou do lugar padrao do instalador."""
    caminho = shutil.which("ollama")

    if caminho:
        return caminho

    candidatos = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama"
        / "ollama.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Ollama" / "ollama.exe",
    ]

    for c in candidatos:
        if c.is_file():
            # Deixa visivel para o resto desta execucao.
            os.environ["PATH"] = str(c.parent) + os.pathsep + os.environ["PATH"]
            return str(c)

    return None


def baixar_modelo():
    passo(f"Modelo {MODELO} (uns 2,5 GB)")

    ollama = achar_ollama()

    if not ollama:
        print("   sem o Ollama não dá. Pulei.")
        anotar(False, f"modelo {MODELO} — falta o Ollama")
        return False

    ok, saida = roda([ollama, "list"], mostrar=False, tempo=120)

    if ok and MODELO.split(":")[0] in saida and MODELO in saida:
        print("   já está baixado.")
        anotar(True, f"modelo {MODELO}")
        return True

    print("   baixando. Isso demora; o Ollama mostra o andamento.")
    print()

    # O download sao ~2,5 GB. Se a conexao oscila, o pull cai no meio
    # e deixa so parte dos blobs. O "ollama pull" retoma de onde parou,
    # entao vale a pena tentar de novo algumas vezes antes de desistir.
    for tentativa in range(1, 4):
        ok, _ = roda([ollama, "pull", MODELO], mostrar=True, tempo=7200)

        if ok:
            anotar(True, f"modelo {MODELO}")
            return True

        if tentativa < 3:
            print()
            print(f"   o download caiu. Tentando retomar "
                  f"({tentativa + 1}/3)...")
            print()

    print()
    print(f"   não deu, mesmo tentando 3 vezes. Depois rode na mão (ele")
    print(f"   retoma de onde parou):  ollama pull {MODELO}")
    anotar(False, f"modelo {MODELO} — rode: ollama pull {MODELO}")
    return False


def baixar_voz(vpy):
    passo("Voz do Piper")

    voz = AQUI / "voices" / "nebell" / "model.onnx"

    if voz.is_file() and voz.stat().st_size > 1_000_000:
        print("   já está aqui.")
        anotar(True, "voz")
        return True

    script = AQUI / "baixar_voz.py"

    if not script.is_file():
        print("   não achei o baixar_voz.py.")
        anotar(False, "voz — falta o baixar_voz.py")
        return False

    ok, _ = roda([str(vpy), str(script)], mostrar=True, tempo=1800)

    if ok and voz.is_file():
        anotar(True, "voz")
        return True

    print("   não deu. Depois: dois cliques no Baixar_Voz.bat")
    anotar(False, "voz — rode o Baixar_Voz.bat")
    return False


def instalar_tesseract(pular):
    """
    OCR: so serve para ela LER A SUA TELA. Tudo o mais funciona sem.
    Por isso e opcional e um tropeco aqui nao estraga a instalacao.
    """
    passo("Tesseract (ler texto da tela) — opcional")

    if pular:
        print("   pulado a pedido.")
        return False

    if existe_programa("tesseract"):
        print("   já instalado.")
        anotar(True, "Tesseract (OCR)")
        return True

    padrao = Path(os.environ.get("PROGRAMFILES", "")) / "Tesseract-OCR" \
        / "tesseract.exe"

    if padrao.is_file():
        print(f"   já instalado: {padrao}")
        anotar(True, "Tesseract (OCR)")
        return True

    if not IS_WINDOWS:
        anotar(False, "Tesseract — instale pelo gerenciador do sistema")
        return False

    # Primeiro pelo winget, que vem no Windows 10/11: ele baixa o
    # Tesseract pela via oficial, sem passar pelo mirror que anda
    # recusando download automático (403).
    if existe_programa("winget"):
        print("   instalando pelo winget (gerenciador do Windows) ...")
        roda(
            ["winget", "install", "--id", "UB-Mannheim.TesseractOCR",
             "-e", "--silent", "--accept-source-agreements",
             "--accept-package-agreements"],
            mostrar=True, tempo=1200,
        )

        if padrao.is_file() or existe_programa("tesseract"):
            print("   instalado pelo winget.")
            print("   Obs.: se ele não ler em português, abra o instalador")
            print("   do Tesseract e marque 'Portuguese' nos idiomas.")
            anotar(True, "Tesseract (OCR)")
            return True

        print("   o winget não concluiu; vou tentar baixar direto.")

    destino = AQUI / "_download" / "tesseract.exe"
    veio = False

    for url in TESSERACT_URLS:
        # Uma tentativa por versão: se o mirror recusa (403), insistir na
        # mesma não muda nada; é melhor passar para a próxima versão.
        if baixar(url, destino, "o instalador do Tesseract", tentativas=1):
            veio = True
            break

        print("   tentando outra versão ...")
        time.sleep(2)

    if not veio:
        print("   não consegui baixar o Tesseract (o servidor dele recusou).")
        print("   Como é opcional, o resto da NEBELL funciona sem ele.")
        print("   Para ter OCR depois, no PowerShell:")
        print("      winget install UB-Mannheim.TesseractOCR")
        print(f"   ou baixe na mão em: {TESSERACT_PAGINA}")
        anotar(False, "Tesseract (opcional) — winget install "
               "UB-Mannheim.TesseractOCR")
        return False

    print("   instalando em silêncio (com o idioma português) ...")
    roda([str(destino), "/S"], mostrar=False, tempo=900)

    if padrao.is_file() or existe_programa("tesseract"):
        print("   instalado.")
        print("   Obs.: se ele não ler em português, rode o instalador de")
        print("   novo e marque 'Portuguese' na lista de idiomas.")
        anotar(True, "Tesseract (OCR)")
        return True

    print("   não pegou. Isso só afeta ler a tela; o resto funciona.")
    anotar(False, "Tesseract (opcional) — " + TESSERACT_PAGINA)
    return False


def conferir(vpy):
    passo("Conferindo o que ficou pronto")

    codigo = (
        "import importlib.util as u\n"
        "mods = %r\n"
        "print('|'.join(m for m in mods if u.find_spec(m) is not None))"
        % [m for m, _ in CONFERIR]
    )

    ok, saida = roda([str(vpy), "-c", codigo], mostrar=False, tempo=120)
    presentes = set(saida.strip().split("|")) if ok and saida.strip() else set()

    for modulo, para_que in CONFERIR:
        marca = "ok     " if modulo in presentes else "FALTA  "
        print(f"   {marca}{para_que}")

    faltando_essencial = ESSENCIAIS - presentes

    if faltando_essencial:
        anotar(False, "falta o essencial: " + ", ".join(faltando_essencial))

    return presentes


def limpar_downloads():
    pasta = AQUI / "_download"

    if not pasta.is_dir():
        return

    try:
        shutil.rmtree(pasta)
        print("\n-- Apaguei os instaladores baixados.")
    except Exception:
        print(f"\n-- Os instaladores ficaram em {pasta}; pode apagar.")


# ============================================================

def main():
    sem_tesseract = "--sem-tesseract" in sys.argv
    so_conferir = "--so-conferir" in sys.argv

    titulo("NEBELL — instalação completa")
    print(f" Pasta:  {AQUI}")
    print(f" Python: {sys.version.split()[0]}  ({sys.executable})")

    if sys.version_info < (3, 9):
        print()
        print(" Este Python é antigo demais. Instale o 3.12 em")
        print(" https://www.python.org/downloads/ e rode de novo.")
        return 1

    if not versao_serve(sys.version_info):
        print()
        print(" Atenção: este Python é o "
              f"{sys.version_info[0]}.{sys.version_info[1]}. O microfone "
              "(pyaudio) não tem")
        print(" versão pronta para ele e a instalação provavelmente vai "
              "falhar nesse pedaço.")
        print(" O certo é rodar pelo Instalar.bat, que usa o Python 3.12 "
              "(e o instala se faltar).")

    if so_conferir:
        vpy = python_do_venv()

        if not vpy.exists():
            print("\n Não há ambiente ainda. Rode sem --so-conferir.")
            return 1

        conferir(vpy)
        return 0

    vpy = criar_ambiente()

    if vpy is None:
        titulo("PAREI AQUI")
        print(" Sem o ambiente do Python não dá para seguir.")
        return 1

    # Repete os passos que faltaram até tudo entrar. Cada passo já pula
    # o que está pronto (o pip nem rebaixa o que instalou), então repetir
    # só retoma o que a conexão derrubou. Para cedo quando uma passada
    # inteira não avança nada -- aí não é conexão, é algo que insistir
    # não resolve, e o resumo no fim diz o que foi.
    progresso_antes = -1

    for passada in range(1, MAX_PASSADAS + 1):
        recado.clear()

        instalar_pacotes(vpy)
        tem_ollama = instalar_ollama(permitir_gui=(passada == 1))

        if tem_ollama:
            baixar_modelo()
        else:
            anotar(False, f"modelo {MODELO} — pulado, falta o Ollama")

        baixar_voz(vpy)
        instalar_tesseract(sem_tesseract)
        presentes = conferir(vpy)

        faltas = [t for ok, t in recado if not ok]

        if not faltas:
            break

        # Mediu progresso pelo nº de módulos já presentes. Se não subiu
        # desde a última passada, insistir não está adiantando.
        progresso = len(presentes)

        if progresso <= progresso_antes:
            break

        progresso_antes = progresso

        if passada < MAX_PASSADAS:
            titulo(f"Ainda faltou coisa — repetindo sozinho "
                   f"(passada {passada + 1} de {MAX_PASSADAS})")
            print(" Costuma ser a conexão caindo no meio de um download.")
            print(" O que já entrou fica; só o que faltou é baixado de novo.")
            print(" Não precisa reabrir o instalador — ele continua.")
            time.sleep(PAUSA_ENTRE_PASSADAS)

    limpar_downloads()

    # ---- relatorio ----
    titulo("RESUMO")

    prontos = [t for ok, t in recado if ok]
    faltas = [t for ok, t in recado if not ok]

    for t in prontos:
        print(f"   ok      {t}")

    for t in faltas:
        print(f"   FALTA   {t}")

    print()

    if not faltas:
        print(" Está tudo pronto.")
    elif any("ambiente" in t or "essencial" in t for t in faltas):
        print(" Faltou coisa importante. Veja as linhas FALTA acima.")
    else:
        print(" O NEBELL já abre. O que faltou está nas linhas acima,")
        print(" e cada uma diz como resolver.")

    print()
    print(" Para usar:  dois cliques em  Iniciar_NEBELL.bat")
    print()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n Cancelado. Pode rodar de novo quando quiser.\n")
        sys.exit(1)
