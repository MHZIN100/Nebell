"""
Voz online da Microsoft (Edge TTS) para o NEBELL.

Vozes neurais quase humanas em pt-BR, de graca e LEVES: nao baixam
modelo, nao usam PyTorch nem a placa de video. O unico custo e precisar
de internet na hora de falar.

Por isso ela nunca anda sozinha: a VozHibrida junta esta voz online com
uma voz offline (o Kokoro). Com internet, fala com a Microsoft; sem
internet, ou se a chamada falhar/demorar, cai sozinha no offline e volta
a tentar o online de tempos em tempos. A voz nunca fica muda.

A Microsoft entrega MP3; aqui converte-se para WAV 16 bits (o formato que
o NEBELL toca) com o soundfile, que ja veio junto com as outras vozes.

Se o edge-tts ou o soundfile nao estiverem instalados, biblioteca_ok()
devolve False e o NEBELL usa so o offline.
"""

import asyncio
import importlib.util
import io
import threading
import time
import wave

try:
    import numpy as np
except Exception:
    np = None

# IMPORTANTE: o edge_tts (puxa o aiohttp) e o soundfile (puxa o
# libsndfile) carregam bibliotecas nativas que, se importadas na abertura
# do NEBELL, brigam com a janela (WebView2) e o processo morre em
# "Abrindo a interface" -- o mesmo tipo de conflito do XTTS. Por isso NÃO
# são importados aqui no topo: entram só na hora de falar, dentro da
# thread de síntese, quando a janela já está de pé. Aqui só checamos se
# existem, sem carregá-los.


VOZ_PADRAO = "pt-BR-FranciscaNeural"

VOZES_PTBR = {
    "pt-BR-FranciscaNeural": "feminina, pt-BR",
    "pt-BR-ThalitaNeural": "feminina, pt-BR (mais nova)",
    "pt-BR-AntonioNeural": "masculina, pt-BR",
}

# Segundos que uma fala pode levar online antes de desistir e usar o
# offline. Curto de propósito: sem internet, a falha é rápida.
TEMPO_LIMITE = 8.0

# Quando o online falha, espera este tanto antes de tentar de novo, para
# não perder tempo com timeout a cada frase enquanto está sem internet.
ESPERA_APOS_FALHA = 30.0


def biblioteca_ok():
    """True quando dá para usar a voz online (edge-tts + soundfile + numpy).
    Checa pela presença dos módulos SEM importá-los (find_spec), para não
    carregar as DLLs nativas na abertura."""
    if np is None:
        return False
    try:
        return (
            importlib.util.find_spec("edge_tts") is not None
            and importlib.util.find_spec("soundfile") is not None
        )
    except Exception:
        return False


def _para_wav(amostras, taxa):
    """Audio (float, -1..1, mono ou estéreo) -> WAV 16 bits mono."""
    dados = np.asarray(amostras, dtype=np.float32)

    if dados.ndim == 2:            # estéreo -> média para mono
        dados = dados.mean(axis=1)

    dados = np.clip(dados.reshape(-1), -1.0, 1.0)
    inteiros = (dados * 32767.0).astype("<i2")

    taxa = int(taxa) or 24000

    buffer = io.BytesIO()

    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(taxa)
        wav.writeframes(inteiros.tobytes())

    return buffer.getvalue(), len(inteiros) / float(taxa)


class VozEdge:
    """A voz online. `sintetizar` pode levantar exceção se não houver
    internet — quem chama (a VozHibrida) trata isso e cai no offline."""

    def __init__(self, voz=VOZ_PADRAO, log=print):
        if not biblioteca_ok():
            raise RuntimeError("edge-tts ou soundfile não disponível")

        self.voz = voz if voz in VOZES_PTBR or voz.startswith("pt-") else VOZ_PADRAO
        self.log = log
        self._lock = threading.Lock()

    def _baixar_mp3(self, texto):
        import edge_tts   # só agora, com a janela já aberta (ver topo)

        async def gerar():
            com = edge_tts.Communicate(texto, self.voz)
            pedacos = bytearray()
            async for parte in com.stream():
                if parte.get("type") == "audio" and parte.get("data"):
                    pedacos += parte["data"]
            return bytes(pedacos)

        # Loop próprio: funciona em qualquer thread, sem depender de um
        # event loop já existente.
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                asyncio.wait_for(gerar(), TEMPO_LIMITE)
            )
        finally:
            loop.close()

    def sintetizar(self, texto):
        texto = (texto or "").strip()

        if not texto:
            return b"", 0.0

        with self._lock:
            mp3 = self._baixar_mp3(texto)

        if not mp3:
            raise RuntimeError("a Microsoft não devolveu áudio")

        import soundfile as sf   # idem: só agora, fora da abertura

        dados, taxa = sf.read(io.BytesIO(mp3), dtype="float32", always_2d=False)
        return _para_wav(dados, taxa)


class VozHibrida:
    """
    Junta uma voz online e uma offline. Tenta a online; se ela falhar
    (sem internet, timeout), usa a offline e segura novas tentativas
    online por um tempo. Avisa no log quando troca de modo.
    """

    def __init__(self, online, offline, log=print,
                 espera_apos_falha=ESPERA_APOS_FALHA):
        self.online = online
        self.offline = offline
        self.log = log
        self.voz = getattr(online, "voz", "")
        self._espera = espera_apos_falha
        self._proxima_tentativa = 0.0
        self._modo = None              # True=online, False=offline, None=indefinido

    def _avisar(self, online, detalhe=""):
        if self._modo is online:
            return
        self._modo = online
        if online:
            self.log("[Voz] Internet OK — falando com a voz online (Microsoft).")
        else:
            self.log(f"[Voz] Sem internet — usando a voz offline (Kokoro).{detalhe}")

    def sintetizar(self, texto):
        agora = time.monotonic()

        if self.online is not None and agora >= self._proxima_tentativa:
            try:
                dados = self.online.sintetizar(texto)
                self._avisar(True)
                return dados
            except Exception as exc:
                self._proxima_tentativa = agora + self._espera
                self._avisar(False, f" ({type(exc).__name__})")

        return self.offline.sintetizar(texto)
