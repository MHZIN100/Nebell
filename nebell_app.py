"""
Integração da NEBELL com o Windows como APP:

  - identidade de app (AppUserModelID): faz a janela e o atalho fixado
    na barra de tarefas agruparem sob o ÍCONE DA NEBELL, não sob o
    python/pythonw;
  - ícone na BANDEJA (área de notificação), com um menu rápido
    (Mostrar, Falar, Nova conversa, Sair).

Tudo é OPCIONAL e à prova de falha: fora do Windows, ou sem as
bibliotecas (pystray/Pillow), as funções simplesmente não fazem nada e
a NEBELL abre exatamente como antes. Nada aqui pode derrubar o arranque.
"""

import os
import threading
from pathlib import Path

AQUI = Path(__file__).resolve().parent
ICONE = AQUI / "nebell.ico"

# Identidade estável: enquanto não mudar, o Windows mantém o atalho
# fixado apontando para a NEBELL mesmo entre atualizações.
APP_ID = "MHZIN.NEBELL.AssistenteLocal"

_bandeja = None


def no_windows():
    return os.name == "nt"


def caminho_icone():
    """Caminho do .ico, ou None se não existir."""
    return str(ICONE) if ICONE.is_file() else None


def definir_identidade():
    """
    Diz ao Windows que este processo é a NEBELL (AppUserModelID). Sem
    isto, a janela aparece agrupada sob o Python e o ícone fixado na
    barra vira o do pythonw. Chamar cedo, antes de abrir a janela.
    """
    if not no_windows():
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def _chamar(acoes, chave):
    fn = (acoes or {}).get(chave)
    if not fn:
        return
    try:
        fn()
    except Exception:
        pass


def iniciar_bandeja(acoes, log=print):
    """
    Coloca o ícone da NEBELL na bandeja do Windows com um menu rápido.

    `acoes` é um dicionário com as funções: 'mostrar', 'falar', 'nova',
    'sair'. Roda numa thread própria e devolve o ícone (ou None se não
    deu para criar — sem bandeja, a NEBELL segue normal).
    """
    global _bandeja

    if not no_windows():
        return None

    try:
        import pystray
        from PIL import Image
    except Exception as exc:
        log(f"[Bandeja] indisponível (instale 'pystray'): {exc}")
        return None

    if not ICONE.is_file():
        log("[Bandeja] sem nebell.ico; a bandeja fica de fora.")
        return None

    try:
        img = Image.open(str(ICONE))
    except Exception as exc:
        log(f"[Bandeja] não consegui ler o ícone: {exc}")
        return None

    menu = pystray.Menu(
        pystray.MenuItem(
            "Mostrar a NEBELL",
            lambda icon, item: _chamar(acoes, "mostrar"),
            default=True,
        ),
        pystray.MenuItem(
            "Falar agora",
            lambda icon, item: _chamar(acoes, "falar"),
        ),
        pystray.MenuItem(
            "Nova conversa",
            lambda icon, item: _chamar(acoes, "nova"),
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            "Sair",
            lambda icon, item: (_chamar(acoes, "sair"), icon.stop()),
        ),
    )

    try:
        _bandeja = pystray.Icon("nebell", img, "N.E.B.E.L.L.", menu)
    except Exception as exc:
        log(f"[Bandeja] não consegui criar o ícone: {exc}")
        return None

    def rodar():
        try:
            _bandeja.run()
        except Exception as exc:
            log(f"[Bandeja] parou: {exc}")

    threading.Thread(target=rodar, daemon=True).start()
    return _bandeja


def parar_bandeja():
    """Tira o ícone da bandeja (no fim da sessão). Nunca levanta."""
    global _bandeja
    if _bandeja is not None:
        try:
            _bandeja.stop()
        except Exception:
            pass
        _bandeja = None
