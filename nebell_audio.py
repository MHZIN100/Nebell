"""
Gerenciamento de microfones do NEBELL.

Resolve tres problemas do reconhecimento de voz:

1. Fone de ouvido que nao funciona. O speech_recognition cria a sua
   propria instancia do PyAudio ao montar o Microphone, e o PyAudio
   enumera os dispositivos uma unica vez, na abertura. Um fone ligado
   depois disso simplesmente nao existe para ele. A correcao e refazer
   o Microphone (e com ele o PyAudio) sempre que a lista mudar.

2. Troca de porta sem avisar. Um vigia compara a lista de dispositivos
   a cada poucos segundos; quando ela muda, o microfone e reaberto e
   recalibrado, sem reiniciar o programa.

3. Calibracao ruim. O limiar de energia calculado no silencio pode
   ficar tao baixo que a respiracao vira fala, ou tao alto que a voz
   nao passa. Aqui ele e preso entre um minimo e um maximo.

O modulo nao depende do resto do NEBELL e importa sem erro em qualquer
sistema: sem PyAudio ou sem speech_recognition, ele apenas informa que
nao ha microfone.
"""

import json
import re
import threading
import time
import unicodedata
from pathlib import Path

try:
    import speech_recognition as sr
except Exception:
    sr = None


# ============================================================
# CONFIGURACAO
# ============================================================

# Limites do limiar de energia (o quanto de som conta como fala).
# Sem o piso, um ambiente muito silencioso faz o limiar cair tanto que
# qualquer respiracao abre uma gravacao; sem o teto, um fone com ruido
# deixa o limiar tao alto que a sua voz nunca passa.
ENERGY_MIN = 90
ENERGY_MAX = 2600
ENERGY_MARGIN = 1.35          # folga sobre o ruido medido

# Ajuste continuo do limiar. LIGADO, e tem de ficar ligado.
#
# Eu havia desligado isto achando que o limiar subia no meio da frase e
# cortava o fim. Estava errado: o speech_recognition so ajusta o limiar
# enquanto ESPERA a fala comecar, nunca durante a frase. Desligado, um
# unico calculo feito na abertura vale para a sessao inteira, e se
# naquele instante havia um ventilador, um video ou a propria voz dele
# tocando, o limiar trava alto e ele passa a nao ouvir mais nada.
DYNAMIC_ENERGY = True

# Limites do ajuste automatico (valores do speech_recognition).
DYNAMIC_DAMPING = 0.15
DYNAMIC_RATIO = 1.5

# Mantem o fluxo de audio aberto entre as escutas, em vez de abrir e
# fechar a cada vez. Abrir o fluxo custa tempo e come o comeco da fala.
# Isso NAO atrapalha a deteccao de fone novo: a lista de dispositivos e
# lida com uma instancia nova do PyAudio, independente deste fluxo.
KEEP_STREAM_OPEN = True

# Quanto silencio encerra a frase. O valor antigo (0,6 s) cortava quem
# fala pausado; 0,9 s deixa respirar sem perder o fim da frase.
PAUSE_THRESHOLD = 0.9
NON_SPEAKING_DURATION = 0.4
PHRASE_THRESHOLD = 0.2

CALIBRATION_SECONDS = 1.0
DEVICE_WATCH_SECONDS = 3.0

# Nomes que indicam fone de ouvido ou headset, em portugues e ingles.
# Usa limite de palavra: sem isso, "fone" casa dentro de "Microfone" e
# todo microfone comum seria tratado como fone de ouvido.
HEADSET_RE = re.compile(
    r"\b(?:fone|fones|headset|headsets|headphone|headphones|earphone|"
    r"earphones|earbud|earbuds|hands?-?free|airpod|airpods|buds)\b"
)

# Dispositivos que costumam existir mas nao servem para falar.
AVOID_HINTS = (
    "mapeador de som", "sound mapper", "mixagem estereo",
    "stereo mix", "what u hear", "saida", "output",
    "line in", "entrada de linha", "spdif", "wave out",
)

CONFIG_NAME = "microfone.json"


def normalize(text):
    text = unicodedata.normalize("NFD", str(text).lower())
    text = "".join(
        char for char in text if unicodedata.category(char) != "Mn"
    )
    return re.sub(r"\s+", " ", text).strip()


class MicDevice:
    """Um microfone visto pelo sistema."""

    def __init__(self, index, name, channels=1, rate=16000, is_default=False):
        self.index = index
        self.name = name
        self.channels = channels
        self.rate = rate
        self.is_default = is_default

    @property
    def is_headset(self):
        return bool(HEADSET_RE.search(normalize(self.name)))

    @property
    def is_undesirable(self):
        texto = normalize(self.name)
        return any(pista in texto for pista in AVOID_HINTS)

    def short(self):
        """
        Nome curto e legivel.

        O Windows corta o nome do dispositivo em 31 caracteres na API
        MME, o que deixa um parentese aberto no fim, como em
        "Grupo de microfones (Tecnologia". Tira o parentese inteiro,
        fechado ou nao.
        """
        nome = re.sub(r"\s*\([^)]*\)?\s*$", "", self.name).strip()
        return nome or self.name.strip()

    def describe(self):
        marcas = []

        if self.is_default:
            marcas.append("padrão do Windows")

        if self.is_headset:
            marcas.append("fone")

        extra = f" ({', '.join(marcas)})" if marcas else ""
        return f"[{self.index}] {self.name}{extra}"

    def to_dict(self):
        return {
            "index": self.index,
            "name": self.name,
            "channels": self.channels,
            "rate": self.rate,
            "is_default": self.is_default,
            "is_headset": self.is_headset,
        }


class MicManager:
    """
    Descobre, escolhe, abre e vigia os microfones.

    Uso:
        mic = MicManager(base_dir)
        mic.start()                      # abre e comeca a vigiar
        with mic.source() as fonte:      # para o recognizer.listen
            ...
    """

    def __init__(self, base_dir=None, on_change=None, log=print):
        self.base_dir = Path(base_dir) if base_dir else None
        self.on_change = on_change
        self.log = log

        self.recognizer = None
        self.microphone = None
        self.device = None
        self.devices = []
        self.ready = False
        self.preference = "auto"      # "auto", um indice ou parte do nome
        self.last_error = ""

        # Um unico lock para tudo que toca o microfone: escuta,
        # calibracao e troca de dispositivo. Com locks separados, o vigia
        # podia recalibrar no meio de uma escuta, e o speech_recognition
        # levanta "already inside a context manager" nesse caso.
        self.lock = threading.RLock()
        self.capturando = threading.Event()
        self.ultimo_nivel = 0

        self._fonte = None
        self._signature = None
        self._watching = False
        self._stop = threading.Event()

        if sr is not None:
            self.recognizer = sr.Recognizer()
            self.apply_recognizer_settings()

    # --------------------------------------------------------
    # Ajustes do reconhecedor
    # --------------------------------------------------------

    def apply_recognizer_settings(self):
        if self.recognizer is None:
            return

        self.recognizer.dynamic_energy_threshold = DYNAMIC_ENERGY
        self.recognizer.dynamic_energy_adjustment_damping = DYNAMIC_DAMPING
        self.recognizer.dynamic_energy_ratio = DYNAMIC_RATIO
        self.recognizer.pause_threshold = PAUSE_THRESHOLD
        self.recognizer.non_speaking_duration = NON_SPEAKING_DURATION
        self.recognizer.phrase_threshold = PHRASE_THRESHOLD

    # --------------------------------------------------------
    # Memoria da escolha
    # --------------------------------------------------------

    @property
    def config_path(self):
        return self.base_dir / CONFIG_NAME if self.base_dir else None

    def load_preference(self):
        caminho = self.config_path

        if not caminho or not caminho.is_file():
            return self.preference

        try:
            dados = json.loads(caminho.read_text(encoding="utf-8"))
            valor = dados.get("preferencia")

            if valor:
                self.preference = str(valor)
        except Exception:
            pass

        return self.preference

    def save_preference(self):
        caminho = self.config_path

        if not caminho:
            return False

        try:
            caminho.parent.mkdir(parents=True, exist_ok=True)
            caminho.write_text(
                json.dumps(
                    {
                        "preferencia": self.preference,
                        "ultimo_nome": self.device.name if self.device else None,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            return True
        except Exception:
            return False

    # --------------------------------------------------------
    # Descoberta
    # --------------------------------------------------------

    def enumerate(self):
        """
        Lista os microfones de entrada agora.

        Cria e descarta uma instancia do PyAudio de proposito: ela
        enumera os dispositivos ao nascer, entao reaproveitar a antiga
        esconderia um fone ligado depois.
        """
        if sr is None:
            self.devices = []
            return self.devices

        encontrados = []
        audio = None

        try:
            audio = sr.Microphone.get_pyaudio().PyAudio()

            try:
                padrao = audio.get_default_input_device_info().get("index")
            except Exception:
                padrao = None

            for indice in range(audio.get_device_count()):
                try:
                    info = audio.get_device_info_by_index(indice)
                except Exception:
                    continue

                if int(info.get("maxInputChannels") or 0) < 1:
                    continue

                encontrados.append(
                    MicDevice(
                        index=indice,
                        name=str(info.get("name") or f"dispositivo {indice}"),
                        channels=int(info.get("maxInputChannels") or 1),
                        rate=int(info.get("defaultSampleRate") or 16000),
                        is_default=(indice == padrao),
                    )
                )

        except Exception as exc:
            self.last_error = str(exc)
        finally:
            if audio is not None:
                try:
                    audio.terminate()
                except Exception:
                    pass

        self.devices = self.deduplicar(encontrados)
        return self.devices

    def deduplicar(self, encontrados):
        """
        O mesmo microfone fisico aparece varias vezes, uma por API de
        audio do Windows (MME, WASAPI, WDM-KS). Mantem um de cada,
        preferindo o que o Windows marcou como padrao e, depois, o de
        nome mais completo (a MME corta em 31 caracteres).
        """
        if not encontrados:
            return encontrados

        melhores = {}

        for device in encontrados:
            chave = normalize(device.short())[:28]

            if not chave:
                chave = f"indice-{device.index}"

            atual = melhores.get(chave)

            if atual is None:
                melhores[chave] = device
                continue

            # Desempate: padrao do Windows, depois nome mais completo.
            if device.is_default and not atual.is_default:
                melhores[chave] = device
            elif (
                device.is_default == atual.is_default
                and len(device.name) > len(atual.name)
            ):
                melhores[chave] = device

        return sorted(melhores.values(), key=lambda d: d.index)

    def signature(self, devices=None):
        """Identidade da lista de dispositivos, para notar mudancas."""
        lista = self.devices if devices is None else devices
        return tuple(
            (d.index, d.name, d.is_default) for d in lista
        )

    # --------------------------------------------------------
    # Escolha
    # --------------------------------------------------------

    def score(self, device):
        """Quanto maior, melhor. Usado quando a preferencia e automatica."""
        pontos = 0

        if device.is_undesirable:
            pontos -= 60

        if device.is_headset:
            pontos += 30          # fone costuma captar melhor que a webcam

        if device.is_default:
            pontos += 20

        if device.channels >= 1:
            pontos += 2

        return pontos

    def match(self, spec, devices=None):
        """Acha um dispositivo por indice ou por parte do nome."""
        lista = self.devices if devices is None else devices

        if not lista:
            return None

        texto = str(spec).strip()

        if not texto or normalize(texto) in ("auto", "automatico", "padrao"):
            return None

        if re.fullmatch(r"\d+", texto):
            indice = int(texto)

            for device in lista:
                if device.index == indice:
                    return device

            return None

        procurado = normalize(texto)

        for device in lista:
            if normalize(device.name) == procurado:
                return device

        for device in lista:
            if procurado in normalize(device.name):
                return device

        # Ultima tentativa: alguma palavra em comum.
        palavras = [p for p in procurado.split() if len(p) > 2]

        for device in lista:
            nome = normalize(device.name)
            if palavras and all(p in nome for p in palavras):
                return device

        return None

    def pick(self):
        """Decide qual microfone usar agora."""
        if not self.devices:
            return None

        escolhido = self.match(self.preference)

        if escolhido is not None:
            return escolhido

        return max(self.devices, key=self.score)

    # --------------------------------------------------------
    # Abertura e calibracao
    # --------------------------------------------------------

    def build_microphone(self, device):
        taxa = 16000 if device.rate >= 16000 else device.rate

        return sr.Microphone(
            device_index=device.index, sample_rate=taxa
        )

    def calibrate(self, duration=CALIBRATION_SECONDS):
        """
        Mede o ruido do ambiente e define o ponto de partida do limiar.

        Com o ajuste automatico ligado, isto e so o ponto de partida: o
        speech_recognition continua acertando o limiar enquanto espera
        voce falar. Os limites existem para o inicio nao ser absurdo.
        """
        if not (self.recognizer and self.microphone):
            return None

        try:
            with self.lock:
                self.fechar_fluxo()

                with self.microphone as fonte:
                    self.recognizer.adjust_for_ambient_noise(
                        fonte, duration=duration
                    )

            medido = self.recognizer.energy_threshold
            limiar = max(ENERGY_MIN, min(ENERGY_MAX, medido * ENERGY_MARGIN))
            self.recognizer.energy_threshold = limiar
            return limiar

        except Exception as exc:
            self.last_error = str(exc)
            return None

    def open(self, announce=True):
        """Abre o microfone escolhido. Devolve True se der certo."""
        with self.lock:
            if sr is None:
                self.ready = False
                self.last_error = "speech_recognition não instalado"

                if announce:
                    self.log(f"Microfone indisponível: {self.last_error}")

                return False

            self.release()
            self.enumerate()

            if not self.devices:
                self.ready = False
                self.last_error = self.last_error or "nenhum microfone encontrado"

                if announce:
                    self.log(f"Microfone indisponível: {self.last_error}")

                return False

            device = self.pick()

            if device is None:
                self.ready = False
                self.last_error = "nenhum microfone compatível"
                return False

            try:
                self.microphone = self.build_microphone(device)
            except Exception as exc:
                self.last_error = str(exc)
                self.ready = False

                if announce:
                    self.log(f"Não consegui abrir o microfone: {exc}")

                return False

            self.device = device
            self._signature = self.signature()
            self.apply_recognizer_settings()

            limiar = self.calibrate()
            self.ready = True

            if announce:
                extra = f", limiar {int(limiar)}" if limiar else ""
                self.log(f"Microfone: {device.short()}{extra}")

            return True

    def release(self):
        """Fecha o que estiver aberto, sem apagar a escolha."""
        with self.lock:
            self.fechar_fluxo()
            self.microphone = None
            self.ready = False

    def use(self, spec, persist=True):
        """
        Troca de microfone. `spec` pode ser "auto", um indice ou um
        pedaco do nome ("fone", "realtek", "webcam").

        Se o microfone pedido ja e o que esta em uso, nao reabre nem
        recalibra: o seletor da interface manda o mesmo valor mais de uma
        vez, e antes isso refazia tudo e repetia a mensagem.
        """
        with self.lock:
            self.enumerate()

            texto = str(spec).strip()
            automatico = (
                not texto
                or normalize(texto) in ("auto", "automatico", "padrao")
            )

            if not automatico and self.match(texto) is None:
                return False, (
                    f"Não encontrei um microfone chamado {texto}. "
                    + self.describe_devices()
                )

            anterior_pref = self.preference
            self.preference = "auto" if automatico else texto

            # Qual dispositivo essa preferencia escolheria agora.
            alvo = self.pick()

            if (
                alvo is not None
                and self.ready
                and self.device is not None
                and alvo.index == self.device.index
            ):
                if persist:
                    self.save_preference()

                return True, f"Já estou usando {self.device.short()}."

            if not self.open(announce=False):
                self.preference = anterior_pref
                return False, (
                    f"Não consegui abrir o microfone: {self.last_error}"
                )

            if persist:
                self.save_preference()

            self.notify()
            return True, f"Microfone agora é {self.device.short()}."

    # --------------------------------------------------------
    # Uso durante a escuta
    # --------------------------------------------------------

    def abrir_fluxo(self):
        """Abre o fluxo de audio e o deixa aberto entre as escutas."""
        if self.microphone is None:
            raise RuntimeError("microfone indisponível")

        if not KEEP_STREAM_OPEN:
            return self.microphone

        if self._fonte is None:
            self._fonte = self.microphone.__enter__()

        return self._fonte

    def fechar_fluxo(self):
        if self._fonte is not None:
            try:
                self.microphone.__exit__(None, None, None)
            except Exception:
                pass

            self._fonte = None

    def limpar_buffer(self, fonte):
        """
        Joga fora o audio que ficou guardado desde a ultima escuta.

        Com o fluxo aberto, o que o NEBELL acabou de falar fica no buffer
        da placa e seria transcrito como se fosse voce.
        """
        try:
            fluxo = getattr(fonte, "stream", None)
            pyaudio_stream = getattr(fluxo, "pyaudio_stream", None)

            if pyaudio_stream is None:
                return

            pedaco = getattr(fonte, "CHUNK", 1024)
            disponivel = pyaudio_stream.get_read_available()

            while disponivel > 0:
                pyaudio_stream.read(
                    min(disponivel, pedaco), exception_on_overflow=False
                )
                disponivel = pyaudio_stream.get_read_available()

        except Exception:
            pass

    def medir_nivel(self, audio):
        """Volume medio do que foi gravado, para o diagnostico."""
        try:
            bruto = audio.get_raw_data()

            try:
                import audioop
                self.ultimo_nivel = audioop.rms(bruto, 2)
            except Exception:
                import array
                amostras = array.array("h")
                amostras.frombytes(bruto[:len(bruto) - len(bruto) % 2])

                if amostras:
                    soma = sum(v * v for v in amostras)
                    self.ultimo_nivel = int((soma / len(amostras)) ** 0.5)

        except Exception:
            pass

        return self.ultimo_nivel

    def escutar(self, timeout=6, phrase_time_limit=15, limpar=True):
        """
        Grava uma fala.

        Tudo acontece sob o mesmo lock do resto da classe, para o vigia
        de dispositivos nao recalibrar no meio da gravacao.
        """
        if not self.ready:
            raise RuntimeError("microfone indisponível")

        self.capturando.set()

        try:
            with self.lock:
                fonte = self.abrir_fluxo()

                if KEEP_STREAM_OPEN:
                    if limpar:
                        self.limpar_buffer(fonte)

                    audio = self.recognizer.listen(
                        fonte, timeout=timeout,
                        phrase_time_limit=phrase_time_limit,
                    )
                else:
                    with self.microphone as aberta:
                        audio = self.recognizer.listen(
                            aberta, timeout=timeout,
                            phrase_time_limit=phrase_time_limit,
                        )

            self.medir_nivel(audio)
            return audio

        finally:
            self.capturando.clear()

    def source(self):
        """Compatibilidade: devolve o microfone para uso em contexto."""
        if not self.ready or self.microphone is None:
            raise RuntimeError("microfone indisponível")

        return self.microphone

    def recover(self):
        """Depois de um erro de leitura, tenta reabrir uma vez."""
        self.log("[Microfone] Perdi o dispositivo; procurando de novo...")

        if self.open(announce=True):
            self.notify()
            return True

        return False

    # --------------------------------------------------------
    # Vigia de mudanca de porta
    # --------------------------------------------------------

    def check_devices(self):
        """
        Olha se a lista mudou. Devolve True quando reabriu o microfone.

        Nao faz nada enquanto uma escuta esta em andamento: reabrir o
        microfone naquele instante derrubaria a gravacao.
        """
        if self.capturando.is_set():
            return False

        with self.lock:
            anterior = self._signature
            atual = self.signature(self.enumerate())

            if atual == anterior:
                return False

            antigo = self.device.name if self.device else None
            self.log("\n[Microfone] A lista de dispositivos mudou.")

            if self.open(announce=True):
                if self.device and self.device.name != antigo:
                    self.log(f"[Microfone] Passei a usar: {self.device.short()}")

                self.notify()
                return True

            self._signature = atual
            return False

    def watch(self):
        """Laco do vigia. Rode em uma thread propria."""
        self._watching = True

        while not self._stop.is_set():
            try:
                self.check_devices()
            except Exception:
                pass

            self._stop.wait(DEVICE_WATCH_SECONDS)

        self._watching = False

    def start(self, watch=True):
        aberto = self.load_preference() is not None and self.open()

        if watch and sr is not None:
            self._stop.clear()
            threading.Thread(target=self.watch, daemon=True).start()

        return aberto

    def stop(self):
        self._stop.set()
        self.release()

    def notify(self):
        if self.on_change:
            try:
                self.on_change(self)
            except Exception:
                pass

    # --------------------------------------------------------
    # Relatorios
    # --------------------------------------------------------

    def describe_devices(self):
        self.enumerate()

        if not self.devices:
            return "Nenhum microfone encontrado."

        linhas = []

        for device in self.devices:
            marca = " <= em uso" if (
                self.device and device.index == self.device.index
            ) else ""
            linhas.append("  " + device.describe() + marca)

        return "Microfones disponíveis:\n" + "\n".join(linhas)

    def status(self):
        if not self.ready:
            return f"Microfone indisponível: {self.last_error or 'desconhecido'}"

        limiar = int(self.recognizer.energy_threshold) if self.recognizer else 0
        return (
            f"Microfone em uso: {self.device.short()} "
            f"(entrada {self.device.index}, limiar {limiar}, "
            f"{len(self.devices)} disponíveis)"
        )
