"""
Lançador da NEBELL — vira o NEBELL.exe.

Um executável LEVE: ele só abre a NEBELL sem console (usando o
pythonw do .venv ao lado). NÃO empacota a NEBELL inteira — é só o
ícone/atalho que você dá dois cliques e fixa na barra.

Gerar o .exe (na máquina Windows): dois cliques em
app_exe\\build_exe.bat  (ele chama o PyInstaller e deixa o NEBELL.exe
na pasta da NEBELL).
"""

import os
import subprocess
import sys

APP_ID = "MHZIN.NEBELL.AssistenteLocal"
CREATE_NO_WINDOW = 0x08000000


def pasta_base():
    """A pasta onde o NEBELL.exe (ou este script) está — a raiz da NEBELL."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _aviso(texto):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, texto, "N.E.B.E.L.L.", 0x10)
    except Exception:
        pass


def main():
    # A raiz é a pasta do .exe; quando rodado solto do app_exe/, sobe uma.
    base = pasta_base()
    if not os.path.exists(os.path.join(base, "nebell.py")):
        acima = os.path.dirname(base)
        if os.path.exists(os.path.join(acima, "nebell.py")):
            base = acima

    alvo = os.path.join(base, "nebell.py")
    if not os.path.exists(alvo):
        _aviso("Não encontrei o nebell.py ao lado do NEBELL.exe.")
        return

    pyw = os.path.join(base, ".venv", "Scripts", "pythonw.exe")
    if not os.path.exists(pyw):
        pyw = "pythonw.exe"   # último recurso: o pythonw do sistema

    # Mesma identidade de app do nebell_app, para a barra agrupar certo.
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass

    try:
        subprocess.Popen(
            [pyw, alvo], cwd=base,
            creationflags=CREATE_NO_WINDOW, close_fds=True,
        )
    except Exception as exc:
        _aviso(f"Não consegui abrir a NEBELL:\n{exc}")


if __name__ == "__main__":
    main()
