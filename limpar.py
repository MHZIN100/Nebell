"""
Limpa o que nao serve mais na pasta do NEBELL.

Por padrao MOVE para uma pasta _lixo em vez de apagar, para dar para
desfazer. Apagar de vez e uma escolha a parte, que a pessoa confirma.

Sobre os arquivos "jarvis": eles NAO sao renomeados para nebell, e isso
e de proposito. Eles sao as VERSOES ANTIGAS do programa, de antes da
troca de nome, e o equivalente nebell_*.py ja existe ao lado, maior e
atual. Renomear jarvis.py para nebell.py destruiria o programa de hoje.
O certo e descartar.

    .venv\\Scripts\\python.exe limpar.py

Ou dois cliques no Limpar.bat.
"""

import fnmatch
import shutil
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent

# ---- o que sai, por grupo, com o motivo --------------------

GRUPOS = [
    (
        "versões antigas do programa (viraram os nebell_*.py)",
        ["jarvis*.py"],
    ),
    (
        "testes das versões antigas",
        ["test_jarvis*.py", "test_audio_hud.py"],
    ),
    (
        "atalhos antigos",
        ["Iniciar_JARVIS.bat", "Renomear_Antigos.bat"],
    ),
    (
        "scripts soltos de quando a voz estava sendo escolhida",
        [
            "ajustar_voz.py", "grave.py", "medir_velocidade.py",
            "teste_piper_direto.py", "teste_piper_persistente.py",
        ],
    ),
    (
        "áudios de teste das vozes",
        ["*.wav"],
    ),
    (
        "sobras de trabalho",
        [
            "*.bak", "*.pyc", "nebell_dev.log",
            "memoria.antes_de_restaurar.db",
        ],
    ),
]

# Pastas inteiras que saem.
PASTAS = [
    ("código compilado, refeito sozinho", "__pycache__"),
    ("ambiente antigo, de outra máquina", ".venv_antigo"),
]

# As vozes que ele nao usa. Perguntadas a parte: sao grandes, e pode
# ser que a pessoa queira guardar para trocar de voz depois.
VOZ_EM_USO = "nebell"

# Nunca, em hipotese alguma. Rede de seguranca contra um padrao mal
# escrito aqui em cima apagar o programa.
PROTEGIDOS = (
    "nebell*.py", "test_nebell*.py", "memoria.db",
    "conferir_pacotes.py", "liberar_maquina.py", "restaurar_memoria.py",
    "baixar_voz.py", "empacotar.py", "limpar.py", "microfone.json",
    "LEIA-ME.txt",
    # Os atalhos de hoje, um por um. Nao da para proteger "*.bat" em
    # bloco: os atalhos antigos tambem terminam em .bat e precisam
    # poder sair.
    "Instalar.bat", "instalar.py",
    "_Python.bat", "Instalar_Pacotes.bat", "Iniciar_NEBELL.bat",
    "Testar_NEBELL.bat", "Empacotar.bat", "Limpar.bat",
    "Baixar_Voz.bat", "Liberar_Maquina.bat", "Restaurar_Memoria.bat",
)

# O -wal e o -shm do SQLite NAO entram na limpeza de proposito: se o
# NEBELL estiver aberto, eles guardam escritas que ainda nao foram para
# o banco, e apagar perde memoria. Sao 32 KB; nao vale o risco.


def protegido(caminho):
    return any(fnmatch.fnmatch(caminho.name, p) for p in PROTEGIDOS)


def tamanho_legivel(bytes_):
    for unidade in ("B", "KB", "MB", "GB"):
        if bytes_ < 1024 or unidade == "GB":
            return f"{bytes_:.0f} {unidade}" if unidade == "B" \
                else f"{bytes_:.1f} {unidade}"

        bytes_ /= 1024


def peso(caminho):
    if caminho.is_file():
        return caminho.stat().st_size

    total = 0

    for dentro in caminho.rglob("*"):
        if dentro.is_file():
            try:
                total += dentro.stat().st_size
            except Exception:
                pass

    return total


def achar(raiz=None):
    """Devolve [(motivo, [caminhos])] do que pode sair."""
    raiz = Path(raiz) if raiz is not None else AQUI
    achados = []

    ja_listados = set()

    for motivo, padroes in GRUPOS:
        alvos = []

        for padrao in padroes:
            for caminho in sorted(raiz.glob(padrao)):
                if not caminho.is_file() or protegido(caminho):
                    continue

                # Dois padroes podem pegar o mesmo arquivo; cada um
                # entra uma vez so.
                if caminho in ja_listados:
                    continue

                ja_listados.add(caminho)
                alvos.append(caminho)

        if alvos:
            achados.append((motivo, alvos))

    for motivo, nome in PASTAS:
        caminho = raiz / nome

        if caminho.is_dir():
            achados.append((motivo, [caminho]))

    return achados


def vozes_sem_uso(raiz=None):
    """As vozes que o NEBELL nao esta usando."""
    raiz = Path(raiz) if raiz is not None else AQUI
    pasta = raiz / "voices"

    if not pasta.is_dir():
        return []

    alvos = []

    for dentro in sorted(pasta.iterdir()):
        if dentro.is_dir() and dentro.name != VOZ_EM_USO:
            alvos.append(dentro)
        elif dentro.is_file() and dentro.name.endswith(
            (".onnx", ".onnx.json")
        ):
            # Voz solta na raiz de voices, do tempo em que nao havia
            # uma pasta por voz.
            alvos.append(dentro)

    return alvos


def mover_ou_apagar(alvos, apagar):
    """Devolve (quantos, bytes, erros)."""
    lixo = AQUI / "_lixo"
    feitos = 0
    liberado = 0
    erros = []

    for caminho in alvos:
        tamanho = peso(caminho)

        try:
            if apagar:
                if caminho.is_dir():
                    shutil.rmtree(caminho)
                else:
                    caminho.unlink()
            else:
                lixo.mkdir(exist_ok=True)
                destino = lixo / caminho.name

                if destino.exists():
                    if destino.is_dir():
                        shutil.rmtree(destino)
                    else:
                        destino.unlink()

                shutil.move(str(caminho), str(destino))

            feitos += 1
            liberado += tamanho

        except Exception as exc:
            erros.append(f"{caminho.name}: {exc}")

    return feitos, liberado, erros


def perguntar(pergunta, padrao_sim=True):
    sufixo = "[S/n]" if padrao_sim else "[s/N]"

    try:
        resposta = input(f"  {pergunta} {sufixo} ").strip().lower()
    except EOFError:
        # Sem ninguem para responder (janela sem teclado, saida
        # redirecionada). Nao mexer e sempre a escolha segura.
        print()
        return False

    if not resposta:
        return padrao_sim

    return resposta in ("s", "si", "sim", "y", "yes")


def main():
    print()
    print("=" * 62)
    print(" NEBELL - limpar o que não serve mais")
    print("=" * 62)
    print()

    achados = achar()

    if not achados:
        print("  A pasta já está limpa.")
        print()
        return 0

    total = 0

    for motivo, alvos in achados:
        bytes_ = sum(peso(c) for c in alvos)
        total += bytes_
        print(f"  {motivo}  ({tamanho_legivel(bytes_)})")

        for caminho in alvos[:6]:
            marca = "\\" if caminho.is_dir() else ""
            print(f"      {caminho.name}{marca}")

        if len(alvos) > 6:
            print(f"      e outros {len(alvos) - 6}")

        print()

    print(f"  Total: {tamanho_legivel(total)}")
    print()
    print("  Nada disso é usado pelo NEBELL de hoje. Os arquivos jarvis")
    print("  são as versões ANTIGAS do programa; os nebell_*.py que")
    print("  estão ao lado são as atuais. Por isso eles são descartados")
    print("  e não renomeados: renomear jarvis.py para nebell.py")
    print("  apagaria o programa de hoje.")
    print()

    if not perguntar("Pode limpar?"):
        print("\n  Não mexi em nada.\n")
        return 0

    print()
    apagar = perguntar(
        "Apagar de vez? (não = mover para a pasta _lixo)", padrao_sim=False
    )

    todos = [c for _, alvos in achados for c in alvos]
    feitos, liberado, erros = mover_ou_apagar(todos, apagar)

    print()
    print(
        f"  {feitos} item(ns), {tamanho_legivel(liberado)} "
        + ("apagados." if apagar else "movidos para _lixo.")
    )

    for erro in erros:
        print(f"    não consegui: {erro}")

    # --- as vozes, a parte ---
    vozes = vozes_sem_uso()

    if vozes:
        bytes_ = sum(peso(c) for c in vozes)
        print()
        print("-" * 62)
        print(f"  Além disso: {len(vozes)} voz(es) que ele não usa, "
              f"{tamanho_legivel(bytes_)}")

        for caminho in vozes:
            print(f"      {caminho.name}")

        print()
        print("  Ele usa a voz 'nebell'. Estas são alternativas do tempo")
        print("  em que a voz estava sendo escolhida. Se apagar e quiser")
        print("  uma delas depois, dá para baixar de novo.")
        print()

        if perguntar("Limpar as vozes sem uso também?", padrao_sim=False):
            feitos, liberado, erros = mover_ou_apagar(vozes, apagar)
            print()
            print(
                f"  {feitos} voz(es), {tamanho_legivel(liberado)} "
                + ("apagadas." if apagar else "movidas para _lixo.")
            )

            for erro in erros:
                print(f"    não consegui: {erro}")
        else:
            print("\n  Deixei as vozes como estão.")

    if not apagar:
        print()
        print("  Confira a pasta _lixo e apague quando tiver certeza.")

    print()
    print("=" * 62)
    print()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n  Cancelado. Nada foi mexido.\n")
        sys.exit(1)
