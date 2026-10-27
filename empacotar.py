"""
Empacota o NEBELL em um zip para levar para outro computador.

O que NAO vai, e por que:

  .venv            guarda o caminho do Python de origem dentro de si.
                   Copiado para outra maquina, ele nao roda. O
                   Instalar_Pacotes.bat cria um novo no destino.
  microfone.json   e o numero do microfone DESTA maquina. No outro PC
                   aponta para o dispositivo errado, ou nenhum.
  __pycache__      codigo compilado, refeito sozinho.
  memoria.db-wal   diario do SQLite; sem o banco aberto nao serve.
  audio_temp       audio de passagem.
  backup           copia do banco que ja vai no zip.

O que vai sempre: o codigo, a voz, a memoria e a interface.

O modelo de escuta (meio giga) e opcional: ele se baixa sozinho na
primeira fala. Incluir deixa o zip pronto para usar sem internet;
deixar de fora deixa o zip dez vezes menor.

    .venv\\Scripts\\python.exe empacotar.py
    .venv\\Scripts\\python.exe empacotar.py --completo

Ou dois cliques no Empacotar.bat.
"""

import fnmatch
import os
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent

# Pastas que nunca entram.
PASTAS_FORA = {
    ".venv", ".venv_antigo", "__pycache__", "audio_temp", "backup",
    ".git", ".idea", ".vscode", "_lixo",
}

# Arquivos que nunca entram, por padrao de nome.
ARQUIVOS_FORA = (
    "microfone.json",       # o microfone e desta maquina
    "*.db-wal", "*.db-shm", # diario do SQLite
    "*.pyc", "*.pyo",
    "*.zip",                # nao empacotar pacote
    "nebell_dev.log",
    "*.bak",
    "memoria.antes_de_restaurar.db",
    "index.anterior.html",
)

# Pesado e opcional: se baixa sozinho quando falta.
PASTAS_OPCIONAIS = {"whisper_models"}

# Vozes: so a que ele usa entra no pacote enxuto. As outras sao
# alternativas de 63 MB cada que ficaram do tempo de escolher a voz.
VOZ_EM_USO = "nebell"


def sobras(raiz):
    """
    O que o limpar.py considera lixo, para nao mandar junto.

    Em vez de repetir a lista aqui (e as duas sairem do lugar com o
    tempo), e o proprio limpar.py quem diz. Se ele nao estiver ao lado,
    o pacote sai com as sobras dentro, que e chato mas nao quebra nada.
    """
    try:
        import limpar
    except Exception:
        print("  Aviso: não achei o limpar.py aqui do lado. O pacote vai")
        print("  sair com as sobras das versões antigas dentro.")
        print()
        return set()

    try:
        fora = set()

        for _, alvos in limpar.achar(raiz):
            for alvo in alvos:
                if alvo.is_dir():
                    fora.update(
                        d for d in alvo.rglob("*") if d.is_file()
                    )
                else:
                    fora.add(alvo)

        return fora

    except Exception as exc:
        print(f"  Aviso: não consegui ler a lista de sobras ({exc}).")
        print("  O pacote vai sair com elas dentro.")
        print()
        return set()


def onde_gravar():
    """
    Escolhe um lugar onde o pacote seja FACIL DE ACHAR.

    Antes ele caia dentro da propria pasta do NEBELL, no meio de
    quarenta arquivos, e quem rodava nao achava o zip. A area de
    trabalho e o primeiro lugar onde a pessoa olha; se nao der, fica
    ao lado da pasta, e so em ultimo caso dentro dela.
    """
    casa = Path.home()

    # O OneDrive vem primeiro: quando ele esta ligado, a area de
    # trabalho de verdade e a dele, e a outra fica velha e vazia.
    candidatos = [
        casa / "OneDrive" / "Desktop",
        casa / "OneDrive" / "Área de Trabalho",
        casa / "Desktop",
        casa / "Área de Trabalho",
        AQUI.parent,
        AQUI,
    ]

    for pasta in candidatos:
        try:
            if not pasta.is_dir():
                continue

            # Da para escrever mesmo? Pasta sincronizada pode recusar.
            teste = pasta / ".nebell_teste_de_escrita"
            teste.write_text("ok", encoding="utf-8")
            teste.unlink()
            return pasta

        except Exception:
            continue

    return AQUI


def mostrar_no_explorer(caminho):
    """Abre a pasta com o arquivo selecionado, para ele ver na hora."""
    if os.name != "nt":
        return False

    try:
        subprocess.Popen(
            ["explorer", f"/select,{caminho}"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True

    except Exception:
        return False


def tamanho_legivel(bytes_):
    for unidade in ("B", "KB", "MB", "GB"):
        if bytes_ < 1024 or unidade == "GB":
            return f"{bytes_:.0f} {unidade}" if unidade == "B" else \
                   f"{bytes_:.1f} {unidade}"

        bytes_ /= 1024


def fora_por_nome(nome):
    return any(fnmatch.fnmatch(nome, padrao) for padrao in ARQUIVOS_FORA)


def escolher(raiz, completo=False, todas_as_vozes=False):
    """
    O que entra no pacote.

    Devolve (lista de (caminho, nome_no_zip), lista de motivos do que
    ficou fora).
    """
    entram = []
    ficaram = {}
    lixo = sobras(raiz)

    def anotar(caminho, motivo):
        try:
            ficaram[motivo] = ficaram.get(motivo, 0) + caminho.stat().st_size
        except Exception:
            ficaram[motivo] = ficaram.get(motivo, 0)

    for caminho in sorted(raiz.rglob("*")):
        if not caminho.is_file():
            continue

        relativo = caminho.relative_to(raiz)
        partes = set(relativo.parts[:-1])

        if partes & PASTAS_FORA:
            anotar(caminho, "pastas de trabalho e ambiente")
            continue

        if fora_por_nome(caminho.name):
            anotar(caminho, "arquivos desta máquina")
            continue

        if caminho in lixo:
            anotar(caminho, "sobras das versões antigas")
            continue

        if partes & PASTAS_OPCIONAIS and not completo:
            anotar(caminho, "modelo de escuta (baixa sozinho)")
            continue

        # Vozes alternativas.
        if relativo.parts and relativo.parts[0] == "voices" and not todas_as_vozes:
            dentro = relativo.parts[1] if len(relativo.parts) > 2 else ""

            if dentro and dentro != VOZ_EM_USO:
                anotar(caminho, "vozes que ele não usa")
                continue

            # Voz solta na raiz de voices (faber), que tambem nao e a
            # usada.
            if not dentro and relativo.name.endswith((".onnx", ".onnx.json")):
                anotar(caminho, "vozes que ele não usa")
                continue

        entram.append((caminho, str(relativo).replace("\\", "/")))

    return entram, ficaram


LEIA_ME = """NEBELL - como por para funcionar neste computador
============================================================

1. INSTALE O PYTHON, se ainda nao tiver
   https://www.python.org/downloads/
   Marque "Add python.exe to PATH" na PRIMEIRA tela.

2. DOIS CLIQUES EM  Instalar_Pacotes.bat
   Ele cria o ambiente do projeto e baixa o que precisa.
   Leva alguns minutos na primeira vez.
   No fim ele mostra uma lista do que esta pronto e do que falta.

3. INSTALE O OLLAMA, que e quem pensa
   https://ollama.com/download
   Depois abra o Prompt de Comando e rode:
       ollama pull qwen3.5:4b

4. TESSERACT, so se quiser que ele leia a sua tela
   https://github.com/UB-Mannheim/tesseract/wiki
   Marque "Portuguese" na lista de idiomas adicionais.

5. DOIS CLIQUES EM  Iniciar_NEBELL.bat


POR QUE NAO VEIO O .venv NO PACOTE
------------------------------------------------------------
Um ambiente Python guarda dentro de si o caminho do Python que
o criou. Copiado para outro computador, ele aponta para um lugar
que nao existe e nao roda. O Instalar_Pacotes.bat cria um novo,
certo para esta maquina.


O QUE VEIO JUNTO
------------------------------------------------------------
A memoria dele (memoria.db) veio, com as conversas e o que ele
aprendeu. Se voce quer comecar limpo nesta maquina, apague o
memoria.db antes de abrir: ele cria um novo vazio.

O microfone NAO veio escolhido de proposito, porque o numero do
dispositivo muda de maquina para maquina. Na primeira vez ele
escolhe sozinho, e voce pode trocar no seletor da janela.

Se o modelo de escuta (whisper_models) nao veio, ele baixa
sozinho na primeira vez que voce falar. Precisa de internet
nessa primeira vez; depois roda offline.


PARA CONFERIR O QUE ESTA FALTANDO, A QUALQUER MOMENTO
------------------------------------------------------------
    .venv\\Scripts\\python.exe conferir_pacotes.py
"""


def main():
    completo = "--completo" in sys.argv
    todas = "--todas-as-vozes" in sys.argv

    print()
    print("=" * 60)
    print(" NEBELL - empacotar para levar")
    print("=" * 60)
    print()

    entram, ficaram = escolher(AQUI, completo, todas)

    if not entram:
        print("  Não achei nada para empacotar.")
        return 1

    total = sum(c.stat().st_size for c, _ in entram)

    print(f"  Pasta: {AQUI}")
    print(f"  Entram: {len(entram)} arquivos, {tamanho_legivel(total)}")
    print()

    if ficaram:
        print("  Ficam de fora:")

        for motivo, bytes_ in sorted(
            ficaram.items(), key=lambda x: -x[1]
        ):
            print(f"    {tamanho_legivel(bytes_):>9}  {motivo}")

        print()

    if not completo:
        print("  Para incluir o modelo de escuta:  empacotar.py --completo")
        print()

    marca = datetime.now().strftime("%Y-%m-%d")
    pasta = onde_gravar()
    destino = pasta / f"NEBELL_{marca}{'_completo' if completo else ''}.zip"

    print(f"  Gravando em {destino} ...")

    try:
        with zipfile.ZipFile(
            destino, "w", zipfile.ZIP_DEFLATED, compresslevel=6
        ) as pacote:
            for numero, (caminho, nome) in enumerate(entram, start=1):
                pacote.write(caminho, f"NEBELL/{nome}")

                if numero % 50 == 0 or numero == len(entram):
                    print(f"    {numero}/{len(entram)}")

            pacote.writestr("NEBELL/LEIA-ME.txt", LEIA_ME)

    except Exception as exc:
        print(f"\n  Não consegui gravar o pacote: {exc}\n")
        return 1

    final = destino.stat().st_size

    print()
    print("=" * 60)
    print(" PRONTO. O pacote está em:")
    print()
    print(f"     {destino}")
    print()
    print(f" {tamanho_legivel(final)} compactado")
    print()

    if mostrar_no_explorer(destino):
        print(" Abri a pasta com ele selecionado.")
        print()

    print(" No outro PC: descompacte e leia o LEIA-ME.txt que está")
    print(" dentro do pacote. Em resumo: Instalar_Pacotes.bat,")
    print(" instalar o Ollama, e Iniciar_NEBELL.bat.")
    print("=" * 60)
    print()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n  Cancelado.\n")
        sys.exit(1)
