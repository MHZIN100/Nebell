"""
Sentinela do NEBELL: olha o hardware e avisa antes de dar problema.

Em um notebook com 8 GB de memoria e uma 3050 mobile, o que de fato
causa travamento e sempre um destes: memoria no limite, disco cheio,
temperatura alta ou a placa sem VRAM. A sentinela olha isso a cada
minuto e so abre a boca quando passa de um limite.

Regras do aviso, para nao virar barulho:
  - cada assunto avisa uma vez e so volta a avisar depois de 20 minutos
  - voltar ao normal nao gera aviso, apenas rearma o assunto
  - o primeiro ciclo nao avisa nada: serve para medir a linha de base
"""

import re
import shutil
import subprocess
import sys
import time
import unicodedata

try:
    import psutil
except Exception:
    psutil = None

EH_WINDOWS = sys.platform.startswith("win")

INTERVALO = 60.0
SILENCIO_POR_ASSUNTO = 20 * 60      # 20 minutos
PRIMEIRO_CICLO_CALADO = True
MAX_ASSUNTOS_POR_VOLTA = 2          # nao despejar sete avisos de uma vez

LIMITES = {
    "memoria_porcento": 90,
    "memoria_livre_mb": 600,
    "disco_livre_gb": 5,
    "disco_porcento": 94,
    "cpu_temperatura": 92,
    "gpu_temperatura": 85,
    "gpu_vram_porcento": 95,
    "bateria_porcento": 12,
    "processo_memoria_mb": 2500,
}

CRIACAO_SEM_JANELA = 0x08000000 if EH_WINDOWS else 0

# A temperatura pelo WMI custa caro: abre um PowerShell inteiro, perto
# de um segundo de processador. A maioria dos notebooks nem publica esse
# sensor, e ai era um PowerShell por minuto, para sempre, em troca de
# nada. Depois de duas tentativas sem resposta, desiste de vez, e a
# sentinela simplesmente deixa de olhar esse limite.
TENTATIVAS_DE_TEMPERATURA = 2
_temperatura_tentativas = [0]
_temperatura_desistiu = [False]


def normalize(texto):
    texto = unicodedata.normalize("NFD", str(texto).lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", texto).strip()


def _rodar(comando, timeout=6):
    try:
        resultado = subprocess.run(
            comando, capture_output=True, text=True, timeout=timeout,
            creationflags=CRIACAO_SEM_JANELA,
        )

        if resultado.returncode == 0:
            return (resultado.stdout or "").strip()

    except Exception:
        pass

    return ""


# ============================================================
# MEDIDAS
# ============================================================

def medir_gpu():
    """
    Temperatura e VRAM pela nvidia-smi.

    Devolve um dicionario ou None quando nao ha placa NVIDIA visivel.
    """
    saida = _rodar([
        "nvidia-smi",
        "--query-gpu=name,temperature.gpu,memory.used,memory.total,"
        "utilization.gpu",
        "--format=csv,noheader,nounits",
    ])

    if not saida:
        return None

    primeira = saida.splitlines()[0]
    campos = [c.strip() for c in primeira.split(",")]

    if len(campos) < 5:
        return None

    def numero(texto):
        try:
            return float(texto)
        except (TypeError, ValueError):
            return None

    usada = numero(campos[2])
    total = numero(campos[3])

    dados = {
        "nome": campos[0],
        "temperatura": numero(campos[1]),
        "vram_usada_mb": usada,
        "vram_total_mb": total,
        "uso_porcento": numero(campos[4]),
    }

    if usada is not None and total:
        dados["vram_porcento"] = round(usada * 100 / total, 1)

    return dados


def medir_memoria():
    if psutil is None:
        return None

    try:
        virtual = psutil.virtual_memory()

        return {
            "porcento": virtual.percent,
            "livre_mb": round(virtual.available / 1024 / 1024),
            "total_mb": round(virtual.total / 1024 / 1024),
        }

    except Exception:
        return None


def medir_disco(caminho=None):
    if caminho is None:
        caminho = "C:\\" if EH_WINDOWS else "/"

    try:
        uso = shutil.disk_usage(caminho)

        return {
            "caminho": str(caminho),
            "livre_gb": round(uso.free / 1024 ** 3, 1),
            "total_gb": round(uso.total / 1024 ** 3, 1),
            "porcento": round(uso.used * 100 / uso.total, 1),
        }

    except Exception:
        return None


def medir_cpu():
    if psutil is None:
        return None

    dados = {}

    try:
        dados["uso_porcento"] = psutil.cpu_percent(interval=0.3)
    except Exception:
        pass

    try:
        temperaturas = psutil.sensors_temperatures()

        for chave in ("coretemp", "k10temp", "acpitz", "cpu_thermal"):
            if chave in temperaturas and temperaturas[chave]:
                graus = [
                    s.current for s in temperaturas[chave]
                    if s.current
                ]

                if graus:
                    dados["temperatura"] = round(max(graus), 1)
                    break

    except Exception:
        pass

    if not dados.get("temperatura") and EH_WINDOWS:
        dados["temperatura"] = _temperatura_windows()

    return dados or None


def _temperatura_windows():
    """
    O WMI do Windows da a temperatura em decimos de kelvin, quando a
    placa-mae publica o sensor. Muitos notebooks nao publicam; nesse
    caso fica sem, e a sentinela simplesmente nao olha esse limite.
    """
    if _temperatura_desistiu[0]:
        return None

    _temperatura_tentativas[0] += 1

    saida = _rodar([
        "powershell", "-NoProfile", "-Command",
        "(Get-CimInstance -Namespace root/wmi "
        "-ClassName MSAcpi_ThermalZoneTemperature "
        "-ErrorAction SilentlyContinue "
        "| Measure-Object -Property CurrentTemperature -Maximum"
        ").Maximum",
    ], timeout=12)

    try:
        decimos = float(saida.strip())

        if decimos > 0:
            return round(decimos / 10 - 273.15, 1)

    except (TypeError, ValueError):
        pass

    if _temperatura_tentativas[0] >= TENTATIVAS_DE_TEMPERATURA:
        _temperatura_desistiu[0] = True

    return None


def medir_bateria():
    if psutil is None:
        return None

    try:
        bateria = psutil.sensors_battery()

        if bateria is None:
            return None

        return {
            "porcento": round(bateria.percent, 1),
            "na_tomada": bool(bateria.power_plugged),
            "minutos": (
                round(bateria.secsleft / 60)
                if bateria.secsleft and bateria.secsleft > 0
                else None
            ),
        }

    except Exception:
        return None


def maiores_processos(quantos=5):
    """Quem esta comendo a memoria."""
    if psutil is None:
        return []

    achados = []

    try:
        for processo in psutil.process_iter(["name", "memory_info"]):
            try:
                informacao = processo.info
                memoria = informacao.get("memory_info")

                if not memoria:
                    continue

                achados.append({
                    "nome": informacao.get("name") or "?",
                    "memoria_mb": round(memoria.rss / 1024 / 1024),
                })

            except Exception:
                continue

    except Exception:
        return []

    achados.sort(key=lambda p: p["memoria_mb"], reverse=True)
    return achados[:quantos]


def medir_tudo():
    """Uma foto do hardware agora."""
    return {
        "memoria": medir_memoria(),
        "disco": medir_disco(),
        "cpu": medir_cpu(),
        "gpu": medir_gpu(),
        "bateria": medir_bateria(),
        "quando": time.time(),
    }


# ============================================================
# AVISOS
# ============================================================

def avaliar(foto, limites=None):
    """
    Decide o que merece aviso.

    Devolve uma lista de (assunto, gravidade, frase). Gravidade e
    "aviso" ou "perigo". Funcao pura: da para testar com uma foto
    inventada.
    """
    limites = {**LIMITES, **(limites or {})}
    achados = []

    memoria = foto.get("memoria") or {}

    if memoria:
        if (memoria.get("porcento") or 0) >= limites["memoria_porcento"] or (
            memoria.get("livre_mb") is not None
            and memoria["livre_mb"] <= limites["memoria_livre_mb"]
        ):
            achados.append((
                "memoria", "perigo",
                f"A memória está em {memoria.get('porcento', '?')} por cento, "
                f"com {memoria.get('livre_mb', '?')} megabytes livres. "
                "Se abrir mais coisa a máquina vai travar."
            ))

    disco = foto.get("disco") or {}

    if disco:
        if (disco.get("livre_gb") is not None
                and disco["livre_gb"] <= limites["disco_livre_gb"]):
            achados.append((
                "disco", "perigo",
                f"O disco {disco.get('caminho', '')} está com só "
                f"{disco['livre_gb']} gigabytes livres."
            ))

        elif (disco.get("porcento") or 0) >= limites["disco_porcento"]:
            achados.append((
                "disco", "aviso",
                f"O disco está {disco['porcento']} por cento cheio."
            ))

    cpu = foto.get("cpu") or {}
    temperatura_cpu = cpu.get("temperatura")

    if temperatura_cpu and temperatura_cpu >= limites["cpu_temperatura"]:
        achados.append((
            "cpu_temperatura", "perigo",
            f"O processador está em {temperatura_cpu} graus. "
            "Vale conferir a ventilação."
        ))

    gpu = foto.get("gpu") or {}
    temperatura_gpu = gpu.get("temperatura")

    if temperatura_gpu and temperatura_gpu >= limites["gpu_temperatura"]:
        achados.append((
            "gpu_temperatura", "perigo",
            f"A placa de vídeo está em {temperatura_gpu} graus."
        ))

    if (gpu.get("vram_porcento") or 0) >= limites["gpu_vram_porcento"]:
        achados.append((
            "gpu_vram", "aviso",
            f"A memória da placa está em {gpu['vram_porcento']} por cento. "
            "Se eu ficar lento, é por isso."
        ))

    bateria = foto.get("bateria") or {}

    if (bateria and not bateria.get("na_tomada")
            and (bateria.get("porcento") or 100)
            <= limites["bateria_porcento"]):
        frase = f"A bateria está em {bateria['porcento']} por cento"

        if bateria.get("minutos"):
            frase += f", cerca de {bateria['minutos']} minutos"

        achados.append(("bateria", "perigo", frase + ". Ligue na tomada."))

    return achados


class Sentinela:
    """
    Olha o hardware em uma thread e chama `ao_avisar(frase, gravidade)`
    quando algo passa do limite.
    """

    def __init__(self, ao_avisar=None, log=print, limites=None,
                 intervalo=INTERVALO):
        self.ao_avisar = ao_avisar
        self.log = log
        self.limites = {**LIMITES, **(limites or {})}
        self.intervalo = intervalo

        self.ultimo_aviso = {}
        self.ligada = False
        self.primeira_volta = True
        self.ultima_foto = None

        self._thread = None
        self._parar = None

    # ---- consulta sob demanda ----

    def relatorio(self):
        """Frase falavel com o estado do hardware agora."""
        foto = medir_tudo()
        self.ultima_foto = foto

        partes = []

        memoria = foto.get("memoria")

        if memoria:
            partes.append(
                f"memória em {memoria['porcento']} por cento, "
                f"{memoria['livre_mb']} megabytes livres"
            )

        cpu = foto.get("cpu") or {}

        if cpu.get("uso_porcento") is not None:
            frase = f"processador em {cpu['uso_porcento']} por cento"

            if cpu.get("temperatura"):
                frase += f" a {cpu['temperatura']} graus"

            partes.append(frase)

        gpu = foto.get("gpu")

        if gpu:
            frase = f"placa {gpu['nome']}"

            if gpu.get("uso_porcento") is not None:
                frase += f" em {gpu['uso_porcento']} por cento"

            if gpu.get("vram_usada_mb") is not None and gpu.get("vram_total_mb"):
                frase += (
                    f", {gpu['vram_usada_mb']:.0f} de "
                    f"{gpu['vram_total_mb']:.0f} megabytes de vídeo"
                )

            if gpu.get("temperatura"):
                frase += f" a {gpu['temperatura']} graus"

            partes.append(frase)

        disco = foto.get("disco")

        if disco:
            partes.append(
                f"disco com {disco['livre_gb']} gigabytes livres de "
                f"{disco['total_gb']}"
            )

        bateria = foto.get("bateria")

        if bateria:
            estado = "na tomada" if bateria["na_tomada"] else "na bateria"
            partes.append(f"bateria em {bateria['porcento']} por cento, {estado}")

        if not partes:
            return (
                "Não consegui medir o hardware. Instale o psutil com "
                "pip install psutil."
            )

        problemas = avaliar(foto, self.limites)

        texto = "Estado da máquina: " + "; ".join(partes) + "."

        if problemas:
            texto += " Atenção: " + " ".join(f for _, _, f in problemas)
        else:
            texto += " Tudo dentro do normal."

        return texto

    # ---- vigilancia ----

    def conferir(self, agora=None):
        """
        Uma rodada. Devolve a lista de frases que mereceram aviso.

        Respeita o silencio por assunto, para o mesmo problema nao ser
        repetido a cada minuto.
        """
        agora = agora if agora is not None else time.time()

        foto = medir_tudo()
        self.ultima_foto = foto

        problemas = avaliar(foto, self.limites)
        assuntos_agora = {assunto for assunto, _, _ in problemas}

        # Assunto que voltou ao normal: rearma, sem avisar nada.
        for assunto in list(self.ultimo_aviso):
            if assunto not in assuntos_agora:
                self.ultimo_aviso.pop(assunto, None)

        if self.primeira_volta and PRIMEIRO_CICLO_CALADO:
            self.primeira_volta = False
            return []

        self.primeira_volta = False
        falar = []

        # Perigo primeiro: se houver corte, que caia o menos urgente.
        problemas.sort(key=lambda p: 0 if p[1] == "perigo" else 1)
        contados = 0

        for assunto, gravidade, frase in problemas:
            anterior = self.ultimo_aviso.get(assunto)

            if anterior and agora - anterior < SILENCIO_POR_ASSUNTO:
                continue

            if contados >= MAX_ASSUNTOS_POR_VOLTA:
                # Fica para a volta seguinte, sem marcar como avisado.
                break

            contados += 1
            self.ultimo_aviso[assunto] = agora
            falar.append((assunto, gravidade, frase))

            if assunto == "memoria":
                maiores = maiores_processos(3)

                if maiores:
                    nomes = ", ".join(
                        f"{p['nome']} com {p['memoria_mb']} megabytes"
                        for p in maiores
                    )
                    falar.append((
                        "memoria_detalhe", gravidade,
                        f"O que está pesando: {nomes}."
                    ))

        if self.ao_avisar:
            for _, gravidade, frase in falar:
                try:
                    self.ao_avisar(frase, gravidade)
                except Exception as exc:
                    self.log(f"[Sentinela] não consegui avisar: {exc}")

        return [frase for _, _, frase in falar]

    def vigiar(self):
        while not self._parar.is_set():
            try:
                self.conferir()
            except Exception as exc:
                self.log(f"[Sentinela] erro ao conferir: {exc}")

            self._parar.wait(self.intervalo)

    def iniciar(self):
        import threading

        if self.ligada:
            return False

        self._parar = threading.Event()
        self._thread = threading.Thread(
            target=self.vigiar, name="nebell-sentinela", daemon=True
        )
        self._thread.start()
        self.ligada = True
        return True

    def parar(self):
        if self._parar is not None:
            self._parar.set()

        self.ligada = False
