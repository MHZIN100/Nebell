"""
Baixa a voz do NEBELL a mao.

Normalmente nao e preciso: o NEBELL instala a voz sozinho na primeira
vez que abre. Este script serve para forcar o download, trocar de voz
ou refazer uma instalacao que deu errado.

Uso:  python baixar_voz.py
      python baixar_voz.py --voz miro      (a voz masculina antiga)
      python baixar_voz.py --forcar        (baixa de novo)
"""

import argparse
import sys
from pathlib import Path

import nebell_voz

BASE_DIR = Path(__file__).resolve().parent
VOICES_DIR = BASE_DIR / "voices"


def barra(baixado, total):
    if total:
        porcento = baixado * 100 // total
        cheio = porcento // 4
        print(
            f"\r  [{'#' * cheio}{'.' * (25 - cheio)}] {porcento:3d}%"
            f"  {baixado // (1024 * 1024)}/{total // (1024 * 1024)} MB",
            end="", flush=True,
        )
    else:
        print(f"\r  {baixado // (1024 * 1024)} MB", end="", flush=True)


def main():
    analisador = argparse.ArgumentParser(description="Baixa a voz do NEBELL.")
    analisador.add_argument(
        "--voz", default=nebell_voz.VOZ_PADRAO, choices=sorted(nebell_voz.VOZES),
        help="nebell (feminina, padrão) ou miro (masculina)",
    )
    analisador.add_argument(
        "--forcar", action="store_true", help="baixa de novo mesmo se já existir"
    )
    argumentos = analisador.parse_args()

    voz = nebell_voz.VOZES[argumentos.voz]

    print("=" * 52)
    print("            VOZ DO N.E.B.E.L.L.")
    print("=" * 52)
    print(f"Voz:   {voz['nome']}")
    print(f"Pasta: {VOICES_DIR / voz['pasta']}")
    print()

    deu_certo, mensagem = nebell_voz.instalar(
        VOICES_DIR, argumentos.voz, log=print,
        progresso=barra, forcar=argumentos.forcar,
    )

    print()
    print(mensagem)

    if deu_certo:
        amostra = VOICES_DIR / voz["pasta"] / "amostra.wav"

        if amostra.is_file():
            print(f"Para ouvir antes: {amostra}")

        print("\nDepois disso a voz roda local, sem internet.")
        return 0

    print("\nConfira a internet e tente de novo.")
    return 1


if __name__ == "__main__":
    codigo = main()

    try:
        input("\nPressione Enter para sair.")
    except (EOFError, KeyboardInterrupt):
        pass

    sys.exit(codigo)
