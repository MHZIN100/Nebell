"""
Voz neural do NEBELL com o Kokoro (modelo de 82M parametros, em ONNX).

Muito mais natural que o Piper e mesmo assim leve: roda na CPU, em
onnxruntime (o mesmo motor que o NEBELL ja usa), sem disputar a placa
com o Ollama. A voz padrao e a "pf_dora": feminina, portugues do Brasil.

Os arquivos do modelo vem do GitHub (releases do kokoro-onnx), nao do
HuggingFace -- o mesmo tipo de lugar de onde o resto do NEBELL ja baixa,
e sem o 403 que o HuggingFace as vezes devolve para download automatico.

Se o kokoro-onnx (ou o numpy) nao estiver instalado, nada aqui estoura:
`biblioteca_ok()` devolve False e o NEBELL segue com o Piper. A ideia e
que a voz NUNCA quebre: qualquer tropeco aqui cai no Piper de reserva.
"""

import io
import threading
import wave
from pathlib import Path

try:
    import numpy as np
except Exception:
    np = None

try:
    from kokoro_onnx import Kokoro
except Exception:
    Kokoro = None


# ---- arquivos do modelo (≈350 MB somados) -----------------
# Ficam em voices/kokoro/. Sao dois: o modelo em si e o banco de vozes.
MODELO_ARQ = "kokoro-v1.0.onnx"
VOZES_ARQ = "voices-v1.0.bin"

BASE_RELEASE = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
    "model-files-v1.0/"
)
MODELO_URL = BASE_RELEASE + MODELO_ARQ
VOZES_URL = BASE_RELEASE + VOZES_ARQ

# Tamanho minimo de cada arquivo, para barrar um download cortado (o
# mesmo cuidado que o nebell_voz tem com a voz do Piper). O onnx tem
# ~325 MB e o banco de vozes ~28 MB.
MODELO_MINIMO = 200 * 1024 * 1024
VOZES_MINIMO = 5 * 1024 * 1024

# ---- vozes pt-BR do Kokoro --------------------------------
VOZES_PTBR = {
    "pf_dora": "feminina, pt-BR",
    "pm_alex": "masculina, pt-BR",
    "pm_santa": "masculina, pt-BR",
}

VOZ_PADRAO = "pf_dora"

# O Kokoro usa a fonetica do idioma para falar certo. "pt-br" e o codigo
# do portugues do Brasil.
IDIOMA = "pt-br"

# O Kokoro gera audio a 24 kHz.
TAXA = 24000


def pasta_modelo(voices_dir):
    return Path(voices_dir) / "kokoro"


def arquivos(voices_dir):
    pasta = pasta_modelo(voices_dir)
    return pasta / MODELO_ARQ, pasta / VOZES_ARQ


def biblioteca_ok():
    """True quando da para usar o Kokoro (kokoro-onnx e numpy presentes)."""
    return Kokoro is not None and np is not None


def modelo_presente(voices_dir):
    """True quando os dois arquivos do modelo existem e tem tamanho de gente."""
    modelo, vozes = arquivos(voices_dir)

    try:
        return (
            modelo.is_file() and modelo.stat().st_size >= MODELO_MINIMO
            and vozes.is_file() and vozes.stat().st_size >= VOZES_MINIMO
        )
    except Exception:
        return False


def disponivel(voices_dir):
    """Da para falar com o Kokoro agora? (biblioteca + modelo no disco)."""
    return biblioteca_ok() and modelo_presente(voices_dir)


def instalar(voices_dir, log=print, progresso=None):
    """
    Baixa os arquivos do modelo do Kokoro, se ainda nao estiverem aqui.

    Reaproveita o download com retomada do nebell_voz (grava em .parcial,
    continua de onde parou, so renomeia quando vem inteiro), entao uma
    queda de conexao no meio dos 325 MB nao recomeca do zero.

    Devolve (deu_certo, mensagem).
    """
    if not biblioteca_ok():
        return False, (
            "o kokoro-onnx não está instalado "
            "(pip install kokoro-onnx)"
        )

    if modelo_presente(voices_dir):
        return True, "O modelo de voz Kokoro já está instalado."

    try:
        from nebell_voz import baixar_arquivo
    except Exception as exc:
        return False, f"não consegui preparar o download: {exc}"

    pasta = pasta_modelo(voices_dir)
    pasta.mkdir(parents=True, exist_ok=True)

    modelo, vozes = arquivos(voices_dir)

    alvos = (
        (MODELO_URL, modelo, "modelo de voz"),
        (VOZES_URL, vozes, "banco de vozes"),
    )

    for url, destino, rotulo in alvos:
        if destino.is_file() and destino.stat().st_size > 0:
            continue

        log(f"[Voz] Baixando o {rotulo} do Kokoro. Isso acontece só uma vez.")
        deu, falha = baixar_arquivo(url, destino, progresso)

        if not deu:
            return False, f"não consegui baixar o {rotulo} do Kokoro: {falha}"

    if not modelo_presente(voices_dir):
        return False, "o download do Kokoro terminou incompleto"

    return True, f"Voz Kokoro instalada ({VOZ_PADRAO})."


def _para_wav(amostras, taxa):
    """
    Converte o audio do Kokoro (float32, -1..1) num WAV de 16 bits mono,
    o mesmo formato que o resto do NEBELL ja toca. Devolve (bytes, seg).
    """
    dados = np.asarray(amostras, dtype=np.float32).reshape(-1)
    dados = np.clip(dados, -1.0, 1.0)
    inteiros = (dados * 32767.0).astype("<i2")

    taxa = int(taxa) or TAXA

    buffer = io.BytesIO()

    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(taxa)
        wav.writeframes(inteiros.tobytes())

    return buffer.getvalue(), len(inteiros) / float(taxa)


class VozKokoro:
    """
    A voz do Kokoro carregada e pronta para falar.

    `sintetizar(texto)` devolve (bytes do WAV, duracao em segundos),
    exatamente como o caminho do Piper, entao a reproducao do NEBELL nao
    muda em nada.
    """

    def __init__(self, voices_dir, voz=VOZ_PADRAO, velocidade=1.0, log=print):
        if not biblioteca_ok():
            raise RuntimeError("kokoro-onnx não está instalado")

        modelo, vozes = arquivos(voices_dir)

        if not modelo_presente(voices_dir):
            raise RuntimeError("o modelo do Kokoro não está no disco")

        self.log = log
        self.voz = voz if voz in VOZES_PTBR else VOZ_PADRAO
        self.velocidade = float(velocidade) or 1.0
        self._lock = threading.Lock()
        self._k = Kokoro(str(modelo), str(vozes))

    def trocar_voz(self, voz):
        if voz in VOZES_PTBR:
            self.voz = voz
            return True
        return False

    def sintetizar(self, texto):
        texto = (texto or "").strip()

        if not texto:
            return b"", 0.0

        with self._lock:
            amostras, taxa = self._k.create(
                texto, voice=self.voz, speed=self.velocidade, lang=IDIOMA
            )

        return _para_wav(amostras, taxa)
