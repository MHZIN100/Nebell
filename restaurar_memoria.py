"""
Devolve a memoria do NEBELL a partir do backup.

Rode com o NEBELL FECHADO. Trocar o banco com o programa aberto
substituiria o arquivo embaixo de uma conexao viva, o que corrompe as
duas pontas.

    .venv\\Scripts\\python.exe restaurar_memoria.py

Ou dois cliques no Restaurar_Memoria.bat.
"""

import sys
from datetime import datetime
from pathlib import Path

try:
    import nebell_backup as B
except Exception as exc:
    print(f"Não achei o nebell_backup.py: {exc}")
    sys.exit(1)

AQUI = Path(__file__).resolve().parent
BANCO = AQUI / "memoria.db"
PASTA = AQUI / "backup"


def quando(caminho):
    try:
        return datetime.fromtimestamp(
            caminho.stat().st_mtime
        ).strftime("%d/%m/%Y às %H:%M")
    except Exception:
        return "?"


def tamanho(caminho):
    try:
        return f"{caminho.stat().st_size // 1024} KB"
    except Exception:
        return "?"


def nebell_esta_aberto():
    """
    Um -wal ou -shm vivo indica banco aberto por alguem.

    Nao e prova (eles sobram depois de uma queda), mas vale o aviso.
    """
    return any(
        Path(str(BANCO) + sufixo).is_file() for sufixo in ("-wal", "-shm")
    )


def copias():
    """As copias disponiveis, da mais nova para a mais velha."""
    achadas = []
    atual = PASTA / B.NOME_BANCO

    if atual.is_file():
        achadas.append(("a mais recente", atual))

    for numero in range(1, B.GERACOES + 1):
        anterior = atual.with_suffix(f".{numero}.db")

        if anterior.is_file():
            achadas.append((f"anterior {numero}", anterior))

    return achadas


def main():
    print()
    print("=" * 62)
    print(" NEBELL - restaurar a memória")
    print("=" * 62)
    print()

    disponiveis = copias()

    if not disponiveis:
        print(f"  Não há nenhum backup em {PASTA}")
        print()
        return 1

    print(f"  Banco atual: {BANCO}")
    print(f"    {'existe, ' + tamanho(BANCO) if BANCO.is_file() else 'NÃO EXISTE'}"
          f"{', de ' + quando(BANCO) if BANCO.is_file() else ''}")

    if BANCO.is_file():
        sao, motivo = B.banco_esta_sao(BANCO)
        print(f"    integridade: {'ok' if sao else motivo}")

    print()
    print("  Cópias disponíveis:")

    for numero, (rotulo, caminho) in enumerate(disponiveis, start=1):
        sao, motivo = B.banco_esta_sao(caminho)
        print(
            f"    {numero}. {rotulo}: {quando(caminho)}, "
            f"{tamanho(caminho)}, {'íntegra' if sao else motivo}"
        )

    print()

    if nebell_esta_aberto():
        print("  ATENÇÃO: o NEBELL parece estar aberto (há arquivos -wal")
        print("  ou -shm ao lado do banco). Feche-o antes de continuar,")
        print("  senão a restauração pode corromper tudo.")
        print()

    escolha = input(
        f"  Qual cópia restaurar? [1-{len(disponiveis)}, ou Enter para sair] "
    ).strip()

    if not escolha:
        print("\n  Cancelado. Nada foi mexido.\n")
        return 0

    try:
        indice = int(escolha)

        if not 1 <= indice <= len(disponiveis):
            raise ValueError

    except ValueError:
        print("\n  Não entendi a escolha. Nada foi mexido.\n")
        return 1

    rotulo, escolhida = disponiveis[indice - 1]

    print()
    print(f"  Vou colocar a cópia {rotulo} ({quando(escolhida)}) no lugar")
    print(f"  do banco atual. O atual será guardado como")
    print(f"  memoria.antes_de_restaurar.db, então nada se perde.")
    print()

    if input("  Confirma? [s/N] ").strip().lower() not in ("s", "sim", "y"):
        print("\n  Cancelado. Nada foi mexido.\n")
        return 0

    # A funcao do modulo restaura a copia principal; para uma geracao
    # anterior, ela e promovida a principal antes.
    if escolhida != PASTA / B.NOME_BANCO:
        import shutil

        principal = PASTA / B.NOME_BANCO
        guardada = PASTA / (B.NOME_BANCO + ".trocada")

        try:
            if principal.is_file():
                shutil.move(str(principal), str(guardada))

            shutil.copy2(escolhida, principal)

        except Exception as exc:
            print(f"\n  Não consegui preparar a cópia: {exc}\n")
            return 1

    deu_certo, mensagem = B.restaurar(PASTA, BANCO)

    print()
    print(f"  {mensagem}")
    print()

    if deu_certo:
        print("  Abra o NEBELL e peça para ele listar a memória, para")
        print("  conferir que as lembranças voltaram.")

    print()
    return 0 if deu_certo else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n  Cancelado.\n")
        sys.exit(1)
