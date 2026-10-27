"""
Diz o que o NEBELL enxerga nesta maquina.

Rodado pelo Instalar_Pacotes.bat no fim da instalacao, e util a
qualquer momento para saber por que algo nao funciona:

    .venv\\Scripts\\python.exe conferir_pacotes.py
"""

import importlib.util
import shutil
import sys
from pathlib import Path

# (modulo a importar, nome no pip, para que serve, obrigatorio?)
# O nome do modulo e o do pacote quase nunca sao iguais: quem importa
# "docx" instala "python-docx". Sem essa coluna a mensagem do fim
# mandaria instalar um pacote que nao existe.
PACOTES = [
    ("piper", "piper-tts", "voz (Piper)", True),
    ("requests", "requests", "internet", True),
    ("faster_whisper", "faster-whisper", "escuta por voz", False),
    ("speech_recognition", "SpeechRecognition", "microfone", False),
    ("pyaudio", "pyaudio", "áudio e corte da fala", False),
    ("webview", "pywebview", "interface em janela (HUD)", False),
    ("psutil", "psutil", "monitoramento de hardware", False),
    ("ddgs", "ddgs", "busca na web", False),
    ("PIL", "pillow", "imagens e captura de tela", False),
    ("pytesseract", "pytesseract", "ler texto de imagem (OCR)", False),
    ("pypdf", "pypdf", "PDF", False),
    ("docx", "python-docx", "Word", False),
    ("openpyxl", "openpyxl", "Excel", False),
    ("pptx", "python-pptx", "PowerPoint", False),
    ("reportlab", "reportlab", "criar PDF", False),
]

MODULOS_DO_PROJETO = (
    "nebell.py", "nebell_audio.py", "nebell_hud.py", "nebell_memoria.py",
    "nebell_web.py", "nebell_voz.py", "nebell_agenda.py", "nebell_visao.py",
    "nebell_janela.py", "nebell_docs.py", "nebell_sentinela.py",
    "nebell_backup.py",
)


def existe(modulo):
    try:
        return importlib.util.find_spec(modulo) is not None
    except (ImportError, ValueError):
        return False


def tesseract():
    achado = shutil.which("tesseract")

    if achado:
        return achado

    for caminho in (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ):
        if Path(caminho).is_file():
            return caminho

    return ""


def ollama():
    try:
        import urllib.request

        with urllib.request.urlopen(
            "http://127.0.0.1:11434/api/tags", timeout=3
        ) as resposta:
            import json

            dados = json.loads(resposta.read().decode("utf-8", "replace"))

        return [m.get("name", "?") for m in dados.get("models", [])]

    except Exception:
        return None


def main():
    print()
    print("=" * 60)
    print(" NEBELL - o que esta pronto nesta maquina")
    print("=" * 60)
    print(f" Python: {sys.version.split()[0]}  ({sys.executable})")
    print()

    faltando_obrigatorio = []
    faltando_opcional = []

    for modulo, no_pip, para_que, obrigatorio in PACOTES:
        if existe(modulo):
            print(f"  ok       {para_que}")
        else:
            print(f"  FALTA    {para_que}  ({no_pip})")

            if obrigatorio:
                faltando_obrigatorio.append(no_pip)
            else:
                faltando_opcional.append(no_pip)

    print()
    programa = tesseract()
    print(
        f"  ok       Tesseract em {programa}" if programa
        else "  FALTA    Tesseract (sem ele não leio a tela nem imagens)"
    )

    modelos = ollama()

    if modelos is None:
        print("  FALTA    Ollama não está respondendo (abra com: ollama serve)")
    elif modelos:
        print(f"  ok       Ollama com: {', '.join(modelos[:6])}")
    else:
        print("  FALTA    Ollama sem modelo (baixe com: ollama pull qwen3.5:4b)")

    print()
    aqui = Path(__file__).resolve().parent
    ausentes = [
        nome for nome in MODULOS_DO_PROJETO if not (aqui / nome).is_file()
    ]

    if ausentes:
        print(f"  FALTA    arquivos do projeto: {', '.join(ausentes)}")
    else:
        print(f"  ok       os {len(MODULOS_DO_PROJETO)} arquivos do projeto")

    print()
    print("=" * 60)

    if faltando_obrigatorio:
        print(" Sem isto o NEBELL não abre:")
        print("     pip install " + " ".join(faltando_obrigatorio))
    elif faltando_opcional:
        print(" O NEBELL abre, mas sem algumas funções. Para completar:")
        print("     pip install " + " ".join(faltando_opcional))
    else:
        print(" Tudo no lugar.")

    print("=" * 60)
    print()
    return 1 if faltando_obrigatorio else 0


if __name__ == "__main__":
    sys.exit(main())
