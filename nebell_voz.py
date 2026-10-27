"""
Download e conferencia das vozes do NEBELL.

Fica separado para ter uma fonte unica: o nebell.py usa isto para
instalar a voz sozinho na primeira execucao, e o baixar_voz.py usa o
mesmo codigo quando voce quer baixar a mao.

Depois de instalada, a voz roda inteiramente no seu computador: nao
precisa de internet para falar.

A voz padrao e a "dii", feminina, portugues do Brasil:
https://huggingface.co/OpenVoiceOS/pipertts_pt-BR_dii
"""

import json
import urllib.error
import urllib.request
from pathlib import Path

VOZES = {
    "nebell": {
        "nome": "dii (feminina, pt-BR)",
        "pasta": "nebell",
        "modelo": (
            "https://huggingface.co/OpenVoiceOS/pipertts_pt-BR_dii/"
            "resolve/main/dii_pt-BR.onnx"
        ),
        "config": (
            "https://huggingface.co/OpenVoiceOS/pipertts_pt-BR_dii/"
            "resolve/main/dii_pt-BR.onnx.json"
        ),
        "amostra": (
            "https://huggingface.co/OpenVoiceOS/pipertts_pt-BR_dii/"
            "resolve/main/sample.wav"
        ),
    },
    "miro": {
        "nome": "miro (masculina, pt-BR)",
        "pasta": "miro",
        "modelo": (
            "https://huggingface.co/OpenVoiceOS/pipertts_pt-BR_miro/"
            "resolve/main/miro_pt-BR.onnx"
        ),
        "config": (
            "https://huggingface.co/OpenVoiceOS/pipertts_pt-BR_miro/"
            "resolve/main/miro_pt-BR.onnx.json"
        ),
        "amostra": None,
    },
}

VOZ_PADRAO = "nebell"

# Um modelo Piper tem dezenas de MB. Menos que isto e download cortado.
TAMANHO_MINIMO = 10 * 1024 * 1024

TEMPO_LIMITE = 90


def baixar_arquivo(url, destino, progresso=None):
    """
    Baixa um arquivo. Grava em .parcial e so renomeia no fim, para um
    download interrompido nunca virar um arquivo quebrado no lugar certo.

    `progresso` recebe (baixado, total) de vez em quando.
    """
    destino = Path(destino)
    parcial = destino.with_suffix(destino.suffix + ".parcial")
    destino.parent.mkdir(parents=True, exist_ok=True)

    try:
        pedido = urllib.request.Request(
            url, headers={"User-Agent": "NEBELL/1.0"}
        )

        with urllib.request.urlopen(pedido, timeout=TEMPO_LIMITE) as resposta:
            total = int(resposta.headers.get("Content-Length") or 0)
            baixado = 0
            ultimo_aviso = 0

            with open(parcial, "wb") as arquivo:
                while True:
                    bloco = resposta.read(262144)

                    if not bloco:
                        break

                    arquivo.write(bloco)
                    baixado += len(bloco)

                    if progresso and baixado - ultimo_aviso >= 2 * 1024 * 1024:
                        ultimo_aviso = baixado
                        progresso(baixado, total)

        if progresso:
            progresso(baixado, total or baixado)

        parcial.replace(destino)
        return True, ""

    except urllib.error.HTTPError as erro:
        falha = f"HTTP {erro.code}"
    except urllib.error.URLError as erro:
        falha = str(erro.reason)
    except Exception as erro:
        falha = str(erro)

    try:
        if parcial.exists():
            parcial.unlink()
    except Exception:
        pass

    return False, falha


def conferir(pasta):
    """Diz se o que esta na pasta e uma voz utilizavel."""
    pasta = Path(pasta)
    modelo = pasta / "model.onnx"
    config = pasta / "model.onnx.json"

    if not modelo.is_file() or not config.is_file():
        return False, "faltou algum arquivo"

    tamanho = modelo.stat().st_size

    if tamanho < TAMANHO_MINIMO:
        return False, (
            f"o modelo tem só {tamanho // 1024} KB; "
            "o download deve ter sido interrompido"
        )

    try:
        dados = json.loads(config.read_text(encoding="utf-8"))
    except Exception as erro:
        return False, f"a configuração não é um JSON válido ({erro})"

    taxa = dados.get("audio", {}).get("sample_rate")

    if not taxa:
        return False, "a configuração não traz a taxa de amostragem"

    return True, f"{taxa} Hz, {tamanho // (1024 * 1024)} MB"


def ja_instalada(voices_dir, chave=VOZ_PADRAO):
    pasta = Path(voices_dir) / VOZES[chave]["pasta"]
    certo, _ = conferir(pasta)
    return certo


def instalar(voices_dir, chave=VOZ_PADRAO, log=print, progresso=None,
             forcar=False):
    """
    Instala a voz em voices/<pasta>/model.onnx.

    Devolve (deu_certo, mensagem).
    """
    if chave not in VOZES:
        return False, f"Não conheço a voz {chave}."

    voz = VOZES[chave]
    pasta = Path(voices_dir) / voz["pasta"]

    if not forcar:
        certo, detalhe = conferir(pasta)

        if certo:
            return True, f"A voz {voz['nome']} já está instalada ({detalhe})."

    log(f"[Voz] Baixando {voz['nome']}. Isso acontece só uma vez.")

    def aviso(baixado, total):
        if progresso:
            progresso(baixado, total)
            return

        if total:
            log(f"[Voz] {baixado * 100 // total}%")
        else:
            log(f"[Voz] {baixado // (1024 * 1024)} MB")

    deu, falha = baixar_arquivo(voz["modelo"], pasta / "model.onnx", aviso)

    if not deu:
        return False, f"Não consegui baixar o modelo da voz: {falha}"

    deu, falha = baixar_arquivo(voz["config"], pasta / "model.onnx.json")

    if not deu:
        return False, f"Não consegui baixar a configuração da voz: {falha}"

    if voz.get("amostra"):
        baixar_arquivo(voz["amostra"], pasta / "amostra.wav")

    certo, detalhe = conferir(pasta)

    if not certo:
        return False, f"O download terminou estranho: {detalhe}"

    return True, f"Voz {voz['nome']} instalada ({detalhe})."
