"""
Voz XTTS v2 (Coqui) para o NEBELL: a voz offline mais natural que roda
na maquina -- bem mais humana e expressiva que o Kokoro.

O preco e o peso: usa o PyTorch e um modelo de ~1.8 GB, entao carrega
devagar e a sintese leva alguns segundos por fala (ainda mais em CPU).
Depois de baixado roda 100% offline. A licenca do modelo e a Coqui
Public Model License (uso pessoal / nao-comercial).

Se o coqui-tts (que importa como `TTS`) nao estiver instalado, ou se o
modelo ainda nao tiver sido preparado, nada aqui estoura: as checagens
devolvem False e o NEBELL cai no Kokoro, e depois no Piper. A voz nunca
fica muda.

Fluxo pensado:
- o instalador roda `instalar()` uma vez (baixa o modelo, faz um teste e
  deixa um arquivo-marca);
- no dia a dia, `preparar()`/VozXtts so carregam se a marca existir, para
  o NEBELL nunca disparar um download de 1.8 GB no meio da abertura.
"""

import io
import os
import threading
import wave
from pathlib import Path

# O XTTS pede concordancia com a licenca na primeira carga. Sem isto ele
# faria uma pergunta no terminal e travaria o NEBELL esperando resposta.
os.environ.setdefault("COQUI_TOS_AGREED", "1")

# No Windows, o PyTorch e a janela (WebView2) carregam cada um a sua copia
# do OpenMP (libiomp5md.dll). As duas juntas abortam o processo sem erro
# nenhum no Python -- o NEBELL morria exatamente ao "Abrindo a interface".
# Esta variavel manda o OpenMP tolerar a copia duplicada. Precisa estar
# definida ANTES de o torch carregar, por isso fica aqui no topo.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

try:
    import numpy as np
except Exception:
    np = None


MODELO = "tts_models/multilingual/multi-dataset/xtts_v2"

# O XTTS fala varios idiomas; "pt" e o portugues.
IDIOMA = "pt"

# Ele gera audio a 24 kHz (confirmado em tempo de execucao pelo modelo).
TAXA = 24000

# Vozes embutidas (timbres de estudio) do XTTS. A padrao e feminina e
# quente; se o nome mudar entre versoes do modelo, a VozXtts cai para a
# primeira feminina disponivel, e so entao para qualquer uma.
FALANTE_PADRAO = "Ana Florence"
FALANTES_FEM = [
    "Ana Florence", "Sofia Hellen", "Alison Dietlinde", "Tammie Ema",
    "Daisy Studious", "Gracie Wise",
]

# Arquivo-marca: so existe depois que o instalador baixou e testou o XTTS.
MARCA = ".xtts_pronto"


def pasta(voices_dir):
    return Path(voices_dir) / "xtts"


def biblioteca_ok():
    """True quando da para usar o XTTS (coqui-tts e numpy presentes)."""
    if np is None:
        return False
    try:
        import TTS  # noqa: F401
        return True
    except Exception:
        return False


def instalado(voices_dir):
    """True quando o instalador já deixou o XTTS pronto (marca presente)."""
    try:
        return (pasta(voices_dir) / MARCA).is_file()
    except Exception:
        return False


def disponivel(voices_dir):
    """Da para falar com o XTTS agora? (biblioteca + ja preparado)."""
    return biblioteca_ok() and instalado(voices_dir)


def _marcar(voices_dir, falante):
    try:
        p = pasta(voices_dir)
        p.mkdir(parents=True, exist_ok=True)
        (p / MARCA).write_text(f"xtts_v2\n{falante}\n", encoding="utf-8")
    except Exception:
        pass


def _para_wav(amostras, taxa):
    """Converte o audio (float32, -1..1) num WAV 16 bits mono -- o mesmo
    formato que o resto do NEBELL ja toca. Devolve (bytes, segundos)."""
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


class VozXtts:
    """
    O XTTS carregado e pronto para falar.

    `sintetizar(texto)` devolve (bytes do WAV, duracao), igual ao Piper e
    ao Kokoro, entao a reproducao do NEBELL nao muda em nada.
    """

    def __init__(self, voices_dir, falante=FALANTE_PADRAO, usar_gpu=False,
                 log=print):
        if not biblioteca_ok():
            raise RuntimeError("coqui-tts não está instalado")

        from TTS.api import TTS

        self.log = log
        self._lock = threading.Lock()

        try:
            import torch
            tem_gpu = bool(torch.cuda.is_available())
        except Exception:
            tem_gpu = False

        # Por padrao roda na CPU de proposito: a placa de 6 GB ja e do
        # Ollama, e os dois juntos nao cabem. CPU e mais lento, mas nao
        # briga por memoria de video.
        usar_gpu = bool(usar_gpu and tem_gpu)

        self._tts = TTS(MODELO, gpu=usar_gpu)
        self.taxa = (
            getattr(self._tts.synthesizer, "output_sample_rate", TAXA) or TAXA
        )
        self.falante = self._escolher_falante(falante)

    def _escolher_falante(self, desejado):
        """Garante um falante valido: o pedido, senao uma feminina, senao
        a primeira que existir. Evita quebrar se o nome mudar de versao."""
        disponiveis = []
        try:
            gerente = self._tts.synthesizer.tts_model.speaker_manager
            disponiveis = list(gerente.name_to_id.keys())
        except Exception:
            disponiveis = []

        if not disponiveis:
            return desejado

        if desejado in disponiveis:
            return desejado

        for nome in FALANTES_FEM:
            if nome in disponiveis:
                return nome

        return disponiveis[0]

    def sintetizar(self, texto):
        texto = (texto or "").strip()

        if not texto:
            return b"", 0.0

        with self._lock:
            amostras = self._tts.tts(
                text=texto, language=IDIOMA, speaker=self.falante
            )

        return _para_wav(amostras, self.taxa)


def instalar(voices_dir, log=print):
    """
    Prepara o XTTS: baixa o modelo (~1.8 GB), faz uma síntese de teste e
    deixa o arquivo-marca. Chamado pelo instalador, uma vez.

    Devolve (deu_certo, mensagem). Opcional de propósito: se falhar, o
    NEBELL segue com o Kokoro.
    """
    if not biblioteca_ok():
        return False, "o coqui-tts não está instalado (pip install coqui-tts)"

    try:
        log("[Voz] Preparando o XTTS. O modelo tem ~1.8 GB e baixa só "
            "uma vez; pode demorar.")
        voz = VozXtts(voices_dir, log=log)

        dados, _ = voz.sintetizar("Pronto. A minha voz nova está funcionando.")

        if not dados:
            return False, "o XTTS carregou mas não gerou áudio"

        _marcar(voices_dir, voz.falante)
        return True, f"Voz XTTS instalada ({voz.falante})."

    except Exception as exc:
        return False, f"não consegui preparar o XTTS: {exc}"
