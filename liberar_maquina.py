"""
Libera a maquina sem abrir o NEBELL.

Serve para quando o NEBELL foi fechado de um jeito torto (travou, o
Windows reiniciou a sessao, a janela foi morta pelo gerenciador de
tarefas) e o modelo ficou preso na memoria da placa.

    .venv\\Scripts\\python.exe liberar_maquina.py

Ou, mais facil, dois cliques no Liberar_Maquina.bat.
"""

import json
import subprocess
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:11434"
EH_WINDOWS = sys.platform.startswith("win")
SEM_JANELA = 0x08000000 if EH_WINDOWS else 0


def pedir(caminho, corpo=None, timeout=10):
    """Fala com o Ollama. Devolve o dicionario da resposta ou None."""
    try:
        dados = json.dumps(corpo).encode("utf-8") if corpo else None

        pedido = urllib.request.Request(
            BASE + caminho,
            data=dados,
            headers={"Content-Type": "application/json"},
        )

        with urllib.request.urlopen(pedido, timeout=timeout) as resposta:
            bruto = resposta.read().decode("utf-8", "replace")

        return json.loads(bruto) if bruto.strip() else {}

    except Exception:
        return None


def carregados():
    """Modelos na memoria agora: lista de (nome, megabytes)."""
    dados = pedir("/api/ps", timeout=4)

    if not dados:
        return []

    achados = []

    for modelo in dados.get("models", []):
        tamanho = modelo.get("size_vram") or modelo.get("size") or 0
        achados.append((modelo.get("name", "?"), round(tamanho / 1024 / 1024)))

    return achados


def descarregar(nome):
    pedir("/api/generate", {"model": nome, "keep_alive": 0, "prompt": ""})


def derrubar_ollama():
    if not EH_WINDOWS:
        print("  (fora do Windows eu não derrubo o Ollama por aqui)")
        return False

    parou = False

    # O "app" primeiro: ele torna a subir o servidor se ficar vivo.
    for alvo in ("ollama app.exe", "ollama.exe"):
        try:
            resultado = subprocess.run(
                ["taskkill", "/IM", alvo, "/F"],
                capture_output=True, text=True, timeout=12,
                creationflags=SEM_JANELA,
            )

            if resultado.returncode == 0:
                print(f"  fechei {alvo}")
                parou = True

        except Exception as exc:
            print(f"  não consegui fechar {alvo}: {exc}")

    return parou


def main():
    print()
    print("=" * 60)
    print(" NEBELL - liberando a máquina")
    print("=" * 60)
    print()

    antes = carregados()

    if antes is None or not antes:
        if pedir("/api/tags", timeout=3) is None:
            print("  O Ollama já não está rodando. Nada preso na placa.")
            print()
            print("=" * 60)
            return 0

        print("  A placa já estava livre: nenhum modelo carregado.")
    else:
        total = sum(megas for _, megas in antes)
        print(f"  Carregado agora: {total} megabytes de memória de vídeo")

        for nome, megas in antes:
            print(f"    - {nome}: {megas} MB")

        print()

        for nome, _ in antes:
            print(f"  soltando {nome}...")
            descarregar(nome)

        for _ in range(8):
            if not carregados():
                break
            time.sleep(0.5)

        sobrou = carregados()

        if sobrou:
            print(f"  ainda aparecem carregados: "
                  f"{', '.join(n for n, _ in sobrou)}")
        else:
            print("  placa livre.")

    print()
    resposta = input("  Fechar o Ollama também? [S/n] ").strip().lower()

    if resposta in ("", "s", "sim", "y", "yes"):
        derrubar_ollama()
    else:
        print("  deixei o Ollama de pé.")

    print()
    print("=" * 60)
    print(" Pronto. A máquina está livre.")
    print("=" * 60)
    print()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ncancelado.")
        sys.exit(1)
