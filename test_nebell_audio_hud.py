"""
Testes do gerenciador de microfones e da ponte da HUD.

Simula o PyAudio e o pywebview, inclusive o caso que mais importava:
um fone de ouvido ligado depois do programa ja estar aberto.

Uso:  python test_audio_hud.py
"""

import json
import re
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

import nebell_audio as A
import nebell_hud as H


# ============================================================
# PYAUDIO SIMULADO
# ============================================================

class FakePyAudio:
    """
    Reproduz o detalhe que causava o bug do fone: a lista de
    dispositivos e tirada uma vez, no nascimento da instancia. Quem
    reaproveita a instancia antiga nunca ve um fone novo.
    """

    criadas = 0

    def __init__(self, mundo):
        FakePyAudio.criadas += 1
        self._congelado = list(mundo.devices)
        self._padrao = mundo.default_index
        self.terminada = False

    def get_device_count(self):
        return len(self._congelado)

    def get_device_info_by_index(self, indice):
        if indice >= len(self._congelado):
            raise IOError("índice inválido")
        return self._congelado[indice]

    def get_default_input_device_info(self):
        if self._padrao is None:
            raise IOError("sem dispositivo padrão")
        return {"index": self._padrao}

    def terminate(self):
        self.terminada = True


class FakeWorld:
    """O 'sistema': quais microfones existem neste momento."""

    def __init__(self):
        self.devices = []
        self.default_index = None
        self.set([("Microfone (Realtek High Definition Audio)", 2)])

    def set(self, nomes_canais, default=0):
        self.devices = [
            {
                "name": nome,
                "maxInputChannels": canais,
                "defaultSampleRate": 44100.0,
                "index": i,
            }
            for i, (nome, canais) in enumerate(nomes_canais)
        ]
        self.default_index = default

    def plug_headset(self):
        """O usuario liga um fone: ele entra na lista e vira o padrão."""
        atuais = [(d["name"], d["maxInputChannels"]) for d in self.devices]
        atuais.append(("Fone de ouvido (Headset HyperX)", 1))
        self.set(atuais, default=len(atuais) - 1)

    def unplug(self, pedaco):
        atuais = [
            (d["name"], d["maxInputChannels"])
            for d in self.devices
            if pedaco.lower() not in d["name"].lower()
        ]
        self.set(atuais, default=0 if atuais else None)


class FakeMicrophone:
    """
    sr.Microphone simulado.

    Imita a restricao real: entrar no contexto duas vezes sem sair
    levanta erro ("already inside a context manager"). Era exatamente
    isso que o vigia de dispositivos provocava ao recalibrar no meio de
    uma escuta.
    """

    aberturas = 0

    def __init__(self, device_index=None, sample_rate=16000):
        self.device_index = device_index
        self.sample_rate = sample_rate
        self.entradas = 0
        self.aberto = False
        self.stream = types.SimpleNamespace(pyaudio_stream=None)

    def __enter__(self):
        if self.aberto:
            raise AssertionError(
                "This audio source is already inside a context manager"
            )

        self.aberto = True
        FakeMicrophone.aberturas += 1
        self.entradas += 1
        return self

    def __exit__(self, *args):
        self.aberto = False
        return False


class FakeRecognizer:
    def __init__(self):
        self.energy_threshold = 300
        self.dynamic_energy_threshold = True
        self.pause_threshold = 0.8
        self.non_speaking_duration = 0.5
        self.phrase_threshold = 0.3
        self.ambiente_medido = 0

    def adjust_for_ambient_noise(self, source, duration=1.0):
        self.ambiente_medido += 1
        # Simula um ambiente muito silencioso: limiar baixissimo.
        self.energy_threshold = 12.0

    def listen(self, source, timeout=None, phrase_time_limit=None):
        return b"audio"


def fake_sr(mundo):
    """Modulo speech_recognition simulado, amarrado a um 'mundo'."""
    modulo = types.SimpleNamespace()

    class Microphone(FakeMicrophone):
        @staticmethod
        def get_pyaudio():
            return types.SimpleNamespace(PyAudio=lambda: FakePyAudio(mundo))

    modulo.Microphone = Microphone
    modulo.Recognizer = FakeRecognizer
    modulo.WaitTimeoutError = type("WaitTimeoutError", (Exception,), {})
    modulo.UnknownValueError = type("UnknownValueError", (Exception,), {})
    modulo.RequestError = type("RequestError", (Exception,), {})
    return modulo


class AudioTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nebell_mic_"))
        self.mundo = FakeWorld()
        self.patch = mock.patch.object(A, "sr", fake_sr(self.mundo))
        self.patch.start()
        FakePyAudio.criadas = 0
        FakeMicrophone.aberturas = 0

    def tearDown(self):
        self.patch.stop()

    def manager(self, **kwargs):
        return A.MicManager(base_dir=self.tmp, log=lambda *a: None, **kwargs)


# ============================================================
# DESCOBERTA
# ============================================================

class TestDescoberta(AudioTest):
    def test_lista_microfones(self):
        mic = self.manager()
        devices = mic.enumerate()
        self.assertEqual(len(devices), 1)
        self.assertIn("Realtek", devices[0].name)

    def test_ignora_dispositivos_de_saida(self):
        self.mundo.set([
            ("Microfone (Realtek)", 2),
            ("Alto-falantes (Realtek)", 0),       # sem canais de entrada
        ])
        mic = self.manager()
        self.assertEqual(len(mic.enumerate()), 1)

    def test_marca_o_padrao_do_windows(self):
        self.mundo.set([("Webcam", 1), ("Realtek", 2)], default=1)
        mic = self.manager()
        devices = mic.enumerate()
        self.assertFalse(devices[0].is_default)
        self.assertTrue(devices[1].is_default)

    def test_sem_microfone_nenhum(self):
        self.mundo.set([])
        mic = self.manager()
        self.assertEqual(mic.enumerate(), [])
        self.assertFalse(mic.open(announce=False))

    def test_cada_consulta_cria_um_pyaudio_novo(self):
        """
        O ponto central da correção: reaproveitar a instância antiga é
        justamente o que escondia um fone ligado depois.
        """
        mic = self.manager()
        mic.enumerate()
        mic.enumerate()
        self.assertGreaterEqual(FakePyAudio.criadas, 2)

    def test_reconhece_fone_pelo_nome(self):
        self.mundo.plug_headset()
        mic = self.manager()
        devices = mic.enumerate()
        fone = [d for d in devices if d.is_headset]
        self.assertEqual(len(fone), 1)
        self.assertIn("HyperX", fone[0].name)

    def test_reconhece_varios_nomes_de_fone(self):
        for nome in ["Headset Microphone", "Fone de Ouvido BT",
                     "AirPods Pro", "Hands-Free AG Audio", "Galaxy Buds"]:
            self.mundo.set([(nome, 1)])
            mic = self.manager()
            self.assertTrue(mic.enumerate()[0].is_headset, nome)

    def test_microfone_comum_nao_e_fone(self):
        """
        "fone" aparece dentro de "Microfone": sem limite de palavra,
        todo microfone interno era classificado como fone de ouvido.
        """
        for nome in ["Microfone (Realtek)", "Microfone interno",
                     "Microphone Array", "Microfone (USB Audio)"]:
            self.mundo.set([(nome, 1)])
            mic = self.manager()
            self.assertFalse(mic.enumerate()[0].is_headset, nome)

    def test_nome_curto_remove_a_placa(self):
        device = A.MicDevice(0, "Microfone (Realtek High Definition Audio)")
        self.assertEqual(device.short(), "Microfone")

    def test_evita_mixagem_estereo(self):
        self.mundo.set([("Mixagem estéreo (Realtek)", 2), ("Microfone (USB)", 1)])
        mic = self.manager()
        mic.enumerate()
        escolhido = mic.pick()
        self.assertIn("USB", escolhido.name)


# ============================================================
# ESCOLHA
# ============================================================

class TestNomesEDuplicatas(AudioTest):
    """O Windows corta nomes em 31 caracteres e repete cada microfone."""

    def test_nome_truncado_pelo_windows(self):
        device = A.MicDevice(0, "Grupo de microfones (Tecnologia")
        self.assertEqual(device.short(), "Grupo de microfones")

    def test_nome_com_parentese_fechado(self):
        device = A.MicDevice(0, "Microfone (Realtek High Definition Audio)")
        self.assertEqual(device.short(), "Microfone")

    def test_nome_sem_parentese(self):
        self.assertEqual(A.MicDevice(0, "Webcam C920").short(), "Webcam C920")

    def test_nome_que_e_so_parentese(self):
        device = A.MicDevice(0, "(Tecnologia Intel)")
        self.assertEqual(device.short(), "(Tecnologia Intel)")

    def test_duplicatas_entre_apis_de_audio(self):
        """
        O mesmo microfone aparece sob MME, WASAPI e WDM-KS. Mantém um.
        """
        self.mundo.set([
            ("Grupo de microfones (Tecnologia", 2),
            ("Grupo de microfones (Tecnologia Intel Smart Sound)", 2),
            ("Microfone (Realtek)", 2),
        ], default=1)

        mic = self.manager()
        devices = mic.enumerate()

        self.assertEqual(len(devices), 2)
        nomes = [d.name for d in devices]
        # Mantém o nome completo, não o cortado.
        self.assertIn("Grupo de microfones (Tecnologia Intel Smart Sound)", nomes)

    def test_duplicata_prefere_o_padrao_do_windows(self):
        self.mundo.set([
            ("Microfone (Realtek Audio)", 2),
            ("Microfone (Realtek", 2),
        ], default=1)

        mic = self.manager()
        devices = mic.enumerate()
        self.assertEqual(len(devices), 1)
        self.assertTrue(devices[0].is_default)

    def test_microfones_diferentes_nao_somem(self):
        self.mundo.set([
            ("Microfone (Realtek)", 2),
            ("Webcam C920", 1),
            ("Fone de ouvido (HyperX)", 1),
        ])
        mic = self.manager()
        self.assertEqual(len(mic.enumerate()), 3)


class TestTrocaIdempotente(AudioTest):
    """
    O seletor da interface mandava o mesmo microfone duas vezes, e ele
    reabria, recalibrava e repetia a mensagem a cada vez.
    """

    def test_trocar_para_o_mesmo_nao_reabre(self):
        self.mundo.set([("Webcam C920", 1), ("Microfone (Realtek)", 2)])
        mic = self.manager()
        mic.use("webcam")

        medicoes = mic.recognizer.ambiente_medido
        deu, msg = mic.use("webcam")

        self.assertTrue(deu)
        self.assertIn("Já estou usando", msg)
        self.assertEqual(mic.recognizer.ambiente_medido, medicoes)

    def test_trocar_para_o_mesmo_indice(self):
        self.mundo.set([("Webcam", 1), ("Realtek", 2)])
        mic = self.manager()
        mic.use("1")
        deu, msg = mic.use("1")
        self.assertIn("Já estou usando", msg)

    def test_nao_avisa_de_novo(self):
        avisos = []
        self.mundo.set([("Webcam C920", 1), ("Microfone (Realtek)", 2)])
        mic = self.manager(on_change=lambda m: avisos.append(m.device.name))

        mic.use("webcam")
        mic.use("webcam")
        mic.use("webcam")

        self.assertEqual(len(avisos), 1)

    def test_troca_de_verdade_ainda_avisa(self):
        avisos = []
        self.mundo.set([("Webcam C920", 1), ("Microfone (Realtek)", 2)])
        mic = self.manager(on_change=lambda m: avisos.append(m.device.name))

        mic.use("webcam")
        mic.use("realtek")

        self.assertEqual(len(avisos), 2)

    def test_auto_repetido_nao_reabre(self):
        mic = self.manager()
        mic.use("auto")
        medicoes = mic.recognizer.ambiente_medido
        deu, msg = mic.use("auto")
        self.assertTrue(deu)
        self.assertEqual(mic.recognizer.ambiente_medido, medicoes)


class TestEscolha(AudioTest):
    def test_prefere_o_fone_quando_existe(self):
        self.mundo.set([("Microfone (Realtek)", 2)], default=0)
        self.mundo.plug_headset()
        mic = self.manager()
        mic.enumerate()
        self.assertTrue(mic.pick().is_headset)

    def test_sem_fone_usa_o_padrao(self):
        self.mundo.set([("Webcam C920", 1), ("Microfone (Realtek)", 2)], default=1)
        mic = self.manager()
        mic.enumerate()
        self.assertIn("Realtek", mic.pick().name)

    def test_escolhe_por_indice(self):
        self.mundo.set([("Webcam", 1), ("Realtek", 2)])
        mic = self.manager()
        mic.enumerate()
        mic.preference = "1"
        self.assertEqual(mic.pick().index, 1)

    def test_escolhe_por_parte_do_nome(self):
        self.mundo.set([("Webcam C920", 1), ("Microfone (Realtek)", 2)])
        mic = self.manager()
        mic.enumerate()
        mic.preference = "webcam"
        self.assertIn("Webcam", mic.pick().name)

    def test_busca_sem_acento_e_sem_caixa(self):
        self.mundo.set([("Fone de Ouvido (Realtek)", 1)])
        mic = self.manager()
        mic.enumerate()
        self.assertIsNotNone(mic.match("FONE DE OUVIDO"))
        self.assertIsNotNone(mic.match("fone"))

    def test_nome_que_nao_existe(self):
        mic = self.manager()
        mic.enumerate()
        self.assertIsNone(mic.match("microfone de marte"))

    def test_auto_volta_para_a_pontuacao(self):
        mic = self.manager()
        mic.enumerate()
        mic.preference = "auto"
        self.assertIsNotNone(mic.pick())


# ============================================================
# ABERTURA E CALIBRACAO
# ============================================================

class TestAberturaECalibracao(AudioTest):
    def test_abre_e_fica_pronto(self):
        mic = self.manager()
        self.assertTrue(mic.open(announce=False))
        self.assertTrue(mic.ready)
        self.assertIsNotNone(mic.device)

    def test_limiar_tem_piso(self):
        """
        Um ambiente silencioso levava o limiar a ~12, e aí qualquer
        respiração abria uma gravação. O piso evita isso.
        """
        mic = self.manager()
        mic.open(announce=False)
        self.assertGreaterEqual(mic.recognizer.energy_threshold, A.ENERGY_MIN)

    def test_limiar_tem_teto(self):
        mic = self.manager()
        mic.open(announce=False)
        mic.recognizer.adjust_for_ambient_noise = (
            lambda fonte, duration=1.0: setattr(
                mic.recognizer, "energy_threshold", 99999
            )
        )
        limiar = mic.calibrate()
        self.assertLessEqual(limiar, A.ENERGY_MAX)

    def test_ajuste_continuo_ligado(self):
        """
        Fica ligado. Ele só ajusta enquanto espera a fala começar, então
        não corta frases — e protege contra uma calibração ruim.
        """
        mic = self.manager()
        mic.open(announce=False)
        self.assertTrue(mic.recognizer.dynamic_energy_threshold)

    def test_pausa_mais_longa(self):
        mic = self.manager()
        self.assertGreaterEqual(mic.recognizer.pause_threshold, 0.8)

    def test_recalibra_ao_reabrir(self):
        mic = self.manager()
        mic.open(announce=False)
        antes = mic.recognizer.ambiente_medido
        mic.open(announce=False)
        self.assertGreater(mic.recognizer.ambiente_medido, antes)

    def test_taxa_de_amostragem_de_16k(self):
        mic = self.manager()
        mic.open(announce=False)
        self.assertEqual(mic.microphone.sample_rate, 16000)


# ============================================================
# O CASO DO FONE DE OUVIDO
# ============================================================

class TestTrocaDePorta(AudioTest):
    def test_fone_ligado_depois_e_detectado(self):
        """O caso relatado: fone plugado com o NEBELL já aberto."""
        mic = self.manager()
        mic.open(announce=False)
        self.assertIn("Realtek", mic.device.name)

        self.mundo.plug_headset()

        self.assertTrue(mic.check_devices())
        self.assertTrue(mic.device.is_headset)

    def test_sem_mudanca_nao_mexe_em_nada(self):
        mic = self.manager()
        mic.open(announce=False)
        antes = mic.device.index
        self.assertFalse(mic.check_devices())
        self.assertEqual(mic.device.index, antes)

    def test_fone_desligado_volta_para_o_interno(self):
        self.mundo.plug_headset()
        mic = self.manager()
        mic.open(announce=False)
        self.assertTrue(mic.device.is_headset)

        self.mundo.unplug("HyperX")

        self.assertTrue(mic.check_devices())
        self.assertFalse(mic.device.is_headset)

    def test_avisa_quem_estiver_ouvindo(self):
        avisos = []
        mic = self.manager(on_change=lambda m: avisos.append(m.device.name))
        mic.open(announce=False)
        self.mundo.plug_headset()
        mic.check_devices()
        self.assertEqual(len(avisos), 1)
        self.assertIn("HyperX", avisos[0])

    def test_escolha_manual_sobrevive_a_mudanca(self):
        self.mundo.set([("Webcam C920", 1), ("Microfone (Realtek)", 2)])
        mic = self.manager()
        mic.use("webcam")
        self.assertIn("Webcam", mic.device.name)

        self.mundo.plug_headset()
        mic.check_devices()

        # Mesmo com um fone novo, respeita o que o usuário escolheu.
        self.assertIn("Webcam", mic.device.name)

    def test_todos_desaparecem(self):
        mic = self.manager()
        mic.open(announce=False)
        self.mundo.set([])
        mic.check_devices()
        self.assertFalse(mic.ready)

    def test_volta_a_funcionar_quando_reaparecem(self):
        mic = self.manager()
        mic.open(announce=False)
        self.mundo.set([])
        mic.check_devices()
        self.mundo.set([("Microfone (USB)", 1)])
        self.assertTrue(mic.check_devices())
        self.assertTrue(mic.ready)


# ============================================================
# TROCA PELO USUARIO E MEMORIA DA ESCOLHA
# ============================================================

class TestTrocaManual(AudioTest):
    def test_troca_por_nome(self):
        self.mundo.set([("Webcam C920", 1), ("Microfone (Realtek)", 2)])
        mic = self.manager()
        mic.open(announce=False)
        ok, msg = mic.use("realtek")
        self.assertTrue(ok)
        self.assertIn("Microfone", msg)

    def test_troca_por_indice(self):
        self.mundo.set([("Webcam", 1), ("Realtek", 2)])
        mic = self.manager()
        ok, _ = mic.use("1")
        self.assertTrue(ok)
        self.assertEqual(mic.device.index, 1)

    def test_nome_inexistente_lista_as_opcoes(self):
        mic = self.manager()
        ok, msg = mic.use("microfone de marte")
        self.assertFalse(ok)
        self.assertIn("Realtek", msg)

    def test_escolha_e_guardada_em_disco(self):
        self.mundo.set([("Webcam C920", 1), ("Microfone (Realtek)", 2)])
        mic = self.manager()
        mic.use("webcam")

        dados = json.loads((self.tmp / A.CONFIG_NAME).read_text(encoding="utf-8"))
        self.assertEqual(dados["preferencia"], "webcam")

    def test_escolha_e_lida_na_proxima_vez(self):
        self.mundo.set([("Webcam C920", 1), ("Microfone (Realtek)", 2)])
        primeiro = self.manager()
        primeiro.use("webcam")

        segundo = self.manager()
        segundo.load_preference()
        segundo.open(announce=False)
        self.assertIn("Webcam", segundo.device.name)

    def test_voltar_para_automatico(self):
        self.mundo.set([("Webcam C920", 1), ("Microfone (Realtek)", 2)])
        mic = self.manager()
        mic.use("webcam")
        ok, _ = mic.use("auto")
        self.assertTrue(ok)
        self.assertEqual(mic.preference, "auto")

    def test_config_corrompida_nao_derruba(self):
        (self.tmp / A.CONFIG_NAME).write_text("{isso não é json", encoding="utf-8")
        mic = self.manager()
        self.assertEqual(mic.load_preference(), "auto")


# ============================================================
# RELATORIOS E RECUPERACAO
# ============================================================

class TestEscutaConcorrente(AudioTest):
    """
    O bug: o vigia de dispositivos recalibrava no meio de uma escuta,
    e o speech_recognition recusa dois contextos ao mesmo tempo.
    """

    def test_escutar_devolve_audio(self):
        mic = self.manager()
        mic.open(announce=False)
        self.assertEqual(mic.escutar(timeout=1), b"audio")

    def test_fluxo_fica_aberto_entre_escutas(self):
        mic = self.manager()
        mic.open(announce=False)

        antes = FakeMicrophone.aberturas
        mic.escutar(timeout=1)
        mic.escutar(timeout=1)
        mic.escutar(timeout=1)

        # Uma abertura para as três escutas, não três.
        self.assertEqual(FakeMicrophone.aberturas - antes, 1)

    def test_vigia_nao_mexe_durante_a_escuta(self):
        mic = self.manager()
        mic.open(announce=False)
        mic.capturando.set()
        try:
            self.mundo.plug_headset()
            # Mesmo com dispositivo novo, não troca agora.
            self.assertFalse(mic.check_devices())
        finally:
            mic.capturando.clear()

        # Terminada a escuta, a troca acontece.
        self.assertTrue(mic.check_devices())
        self.assertTrue(mic.device.is_headset)

    def test_escuta_e_troca_em_paralelo_nao_quebram(self):
        mic = self.manager()
        mic.open(announce=False)

        erros = []

        def escutando():
            for _ in range(25):
                try:
                    mic.escutar(timeout=1)
                except Exception as exc:
                    erros.append(("escuta", exc))

        def trocando():
            for i in range(25):
                try:
                    if i % 2:
                        self.mundo.plug_headset()
                    else:
                        self.mundo.unplug("HyperX")
                    mic.check_devices()
                except Exception as exc:
                    erros.append(("vigia", exc))

        threads = [
            threading.Thread(target=escutando),
            threading.Thread(target=trocando),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(erros, [])

    def test_calibrar_durante_fluxo_aberto(self):
        """Calibrar tem de fechar o fluxo antes de medir."""
        mic = self.manager()
        mic.open(announce=False)
        mic.escutar(timeout=1)          # deixa o fluxo aberto
        self.assertIsNotNone(mic.calibrate())

    def test_release_fecha_o_fluxo(self):
        mic = self.manager()
        mic.open(announce=False)
        mic.escutar(timeout=1)
        microfone = mic.microphone
        mic.release()
        self.assertFalse(microfone.aberto)

    def test_escutar_sem_microfone_levanta(self):
        self.mundo.set([])
        mic = self.manager()
        mic.open(announce=False)
        with self.assertRaises(RuntimeError):
            mic.escutar(timeout=1)

    def test_nivel_e_medido(self):
        mic = self.manager()
        mic.open(announce=False)

        audio = mock.Mock()
        audio.get_raw_data.return_value = (3000).to_bytes(2, "little", signed=True) * 100
        self.assertGreater(mic.medir_nivel(audio), 0)

    def test_nivel_com_audio_estranho(self):
        mic = self.manager()
        audio = mock.Mock()
        audio.get_raw_data.side_effect = Exception("sem dados")
        mic.medir_nivel(audio)          # não deve levantar


class TestAjusteDoLimiar(AudioTest):
    def test_ajuste_automatico_fica_ligado(self):
        """
        Eu havia desligado isto por uma razão errada. O ajuste só
        acontece enquanto espera a fala, nunca durante a frase, e sem
        ele um limiar mal calibrado trava a sessão inteira.
        """
        mic = self.manager()
        self.assertTrue(mic.recognizer.dynamic_energy_threshold)
        self.assertTrue(A.DYNAMIC_ENERGY)

    def test_parametros_do_ajuste(self):
        mic = self.manager()
        self.assertEqual(
            mic.recognizer.dynamic_energy_adjustment_damping, A.DYNAMIC_DAMPING
        )
        self.assertEqual(mic.recognizer.dynamic_energy_ratio, A.DYNAMIC_RATIO)

    def test_piso_e_so_o_ponto_de_partida(self):
        mic = self.manager()
        mic.open(announce=False)
        # A calibração mediu 12 (ambiente silencioso) e o piso subiu.
        self.assertGreaterEqual(mic.recognizer.energy_threshold, A.ENERGY_MIN)
        # E o automático continua ligado para ajustar depois.
        self.assertTrue(mic.recognizer.dynamic_energy_threshold)


class TestRelatorios(AudioTest):
    def test_lista_marca_o_que_esta_em_uso(self):
        self.mundo.set([("Webcam", 1), ("Realtek", 2)])
        mic = self.manager()
        mic.open(announce=False)
        texto = mic.describe_devices()
        self.assertIn("em uso", texto)
        self.assertEqual(texto.count("["), 2)

    def test_lista_vazia(self):
        self.mundo.set([])
        mic = self.manager()
        self.assertIn("Nenhum microfone", mic.describe_devices())

    def test_status_mostra_o_limiar(self):
        mic = self.manager()
        mic.open(announce=False)
        self.assertIn("limiar", mic.status())

    def test_status_quando_indisponivel(self):
        self.mundo.set([])
        mic = self.manager()
        mic.open(announce=False)
        self.assertIn("indisponível", mic.status())

    def test_recupera_depois_de_perder_o_dispositivo(self):
        mic = self.manager()
        mic.open(announce=False)
        self.mundo.set([("Microfone (USB novo)", 1)])
        self.assertTrue(mic.recover())
        self.assertIn("USB", mic.device.name)

    def test_source_sem_microfone_levanta(self):
        self.mundo.set([])
        mic = self.manager()
        mic.open(announce=False)
        with self.assertRaises(RuntimeError):
            mic.source()


class TestSemSpeechRecognition(unittest.TestCase):
    def test_modulo_importa_sem_a_biblioteca(self):
        with mock.patch.object(A, "sr", None):
            mic = A.MicManager(log=lambda *a: None)
            self.assertEqual(mic.enumerate(), [])
            self.assertFalse(mic.open(announce=False))
            self.assertIn("indisponível", mic.status())


# ============================================================
# PONTE DA HUD
# ============================================================

class FakeWindow:
    def __init__(self, escolhidos=None, estourar=False):
        self.executados = []
        self.destruida = False
        self.escolhidos = escolhidos
        self.estourar = estourar
        self.dialogos = []

    def evaluate_js(self, codigo):
        self.executados.append(codigo)
        return None

    def create_file_dialog(self, tipo, allow_multiple=False, **kwargs):
        self.dialogos.append((tipo, allow_multiple))

        if self.estourar:
            raise RuntimeError("sem seletor neste sistema")

        return self.escolhidos

    def destroy(self):
        self.destruida = True


class HudTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nebell_hud_"))
        self.html = self.tmp / "hud" / "index.html"
        self.bridge = H.HudBridge(self.html, log=lambda *a: None)
        self.window = FakeWindow()
        self.bridge.window = self.window
        self.bridge.active = True


class TestPagina(HudTest):
    def test_grava_a_pagina_se_nao_existir(self):
        self.assertFalse(self.html.exists())
        self.bridge.ensure_html()
        self.assertTrue(self.html.exists())
        self.assertIn("N.E.B.E.L.L.", self.html.read_text(encoding="utf-8"))

    def test_pagina_antiga_e_atualizada_guardando_a_anterior(self):
        # Antes isto NUNCA sobrescrevia, e por isso quem já tinha um
        # hud/index.html nunca recebia as mudanças novas: foi o que
        # deixou o botão ARQUIVO fora da janela. Agora atualiza, mas
        # guarda a anterior do lado.
        self.html.parent.mkdir(parents=True, exist_ok=True)
        self.html.write_text("<html>minha versão</html>", encoding="utf-8")

        self.bridge.ensure_html()

        atual = self.html.read_text(encoding="utf-8")
        self.assertIn('id="file"', atual)
        self.assertEqual(
            self.html.with_suffix(".anterior.html").read_text(encoding="utf-8"),
            "<html>minha versão</html>",
        )

    def test_pagina_da_versao_atual_nao_e_tocada(self):
        # Quem editou a página E manteve a marca de versão está dizendo
        # "esta é minha": não se mexe.
        self.bridge.ensure_html()
        minha = self.html.read_text(encoding="utf-8").replace(
            "REGISTRO", "MEU REGISTRO"
        )
        self.html.write_text(minha, encoding="utf-8")

        self.bridge.ensure_html()

        self.assertEqual(self.html.read_text(encoding="utf-8"), minha)

    def test_versao_no_disco(self):
        self.bridge.ensure_html()
        self.assertEqual(self.bridge.versao_no_disco(), H.HUD_VERSAO)

    def test_pagina_sem_marca_conta_como_a_mais_velha(self):
        self.html.parent.mkdir(parents=True, exist_ok=True)
        self.html.write_text("<html>sem marca</html>", encoding="utf-8")
        self.assertEqual(self.bridge.versao_no_disco(), 0)

    def test_arquivo_ilegivel_nao_derruba(self):
        self.html.parent.mkdir(parents=True, exist_ok=True)
        self.html.write_bytes(b"\xff\xfe\x00binario")
        self.assertEqual(self.bridge.versao_no_disco(), 0)

    def test_a_marca_do_html_bate_com_a_constante(self):
        # Esquecer de subir uma das duas faria a página nunca atualizar.
        achado = re.search(
            r'nebell-hud-versao"\s+content="(\d+)"', H.HUD_HTML
        )
        self.assertIsNotNone(achado)
        self.assertEqual(int(achado.group(1)), H.HUD_VERSAO)

    def test_nao_sobrescreve_quando_nao_consegue_gravar(self):
        self.html.parent.mkdir(parents=True, exist_ok=True)
        self.html.write_text("<html>velha</html>", encoding="utf-8")

        with mock.patch.object(
            H.Path, "write_text", side_effect=OSError("somente leitura")
        ):
            devolvido = self.bridge.ensure_html()

        self.assertEqual(devolvido, self.html)
        self.assertEqual(
            self.html.read_text(encoding="utf-8"), "<html>velha</html>"
        )

    def test_pagina_tem_as_pecas_que_o_python_usa(self):
        for peca in ["nebellUI", "setMics", "setStats", "setLevel",
                     "pywebview", "b.ready", "set_mic", "#halt"]:
            self.assertIn(peca, H.HUD_HTML, peca)

    def test_pagina_tem_os_campos_novos(self):
        for campo in ['id="micV"', 'id="stt"', 'id="loc"', 'id="mic"']:
            self.assertIn(campo, H.HUD_HTML, campo)


class TestChamadasParaAPagina(HudTest):
    def test_guarda_antes_de_a_pagina_abrir(self):
        self.bridge.set_state("listening")
        self.assertEqual(self.window.executados, [])
        self.assertEqual(len(self.bridge._pending), 1)

    def test_solta_o_que_estava_guardado(self):
        self.bridge.set_state("listening")
        self.bridge.add_message("user", "oi")
        self.bridge.flush()
        self.assertEqual(len(self.window.executados), 2)

    def test_depois_de_pronta_envia_direto(self):
        self.bridge.flush()
        self.bridge.set_state("thinking")
        self.assertEqual(len(self.window.executados), 1)
        self.assertIn("setState", self.window.executados[0])

    def test_estado_repetido_nao_e_reenviado(self):
        self.bridge.flush()
        self.bridge.set_state("speaking")
        self.bridge.set_state("speaking")
        self.assertEqual(len(self.window.executados), 1)

    def test_texto_com_acento_e_aspas(self):
        self.bridge.flush()
        self.bridge.add_message("nebell", 'São 10h, "senhor" \\ fim')
        codigo = self.window.executados[0]
        self.assertIn("São", codigo)
        # O conteudo tem de ser JSON valido dentro da chamada.
        dentro = codigo[codigo.index("addMessage(") + len("addMessage("):-1]
        papel, texto = json.loads("[" + dentro + "]")
        self.assertEqual(texto, 'São 10h, "senhor" \\ fim')

    def test_mensagem_vazia_e_ignorada(self):
        self.bridge.flush()
        self.bridge.add_message("nebell", "   ")
        self.assertEqual(self.window.executados, [])

    def test_estatisticas_sem_valores_nulos(self):
        self.bridge.flush()
        self.bridge.set_stats(cpu=42, ram=None, mic="Realtek")
        codigo = self.window.executados[0]
        self.assertIn("cpu", codigo)
        self.assertNotIn("ram", codigo)

    def test_estatisticas_vazias_nao_viram_chamada(self):
        self.bridge.flush()
        self.bridge.set_stats()
        self.assertEqual(self.window.executados, [])

    def test_lista_de_microfones(self):
        self.bridge.flush()
        self.bridge.set_mics(
            [{"index": 0, "name": "Realtek", "is_headset": False}], 0
        )
        self.assertIn("setMics", self.window.executados[0])

    def test_janela_que_morreu_nao_levanta(self):
        self.bridge.flush()

        def explode(codigo):
            raise RuntimeError("janela fechada")

        self.window.evaluate_js = explode
        self.bridge.set_state("idle")       # não deve levantar

    def test_fila_guardada_nao_cresce_sem_limite(self):
        for i in range(500):
            self.bridge.add_message("user", f"mensagem {i}")
        self.assertLessEqual(len(self.bridge._pending), 200)

    def test_inativo_nao_faz_nada(self):
        self.bridge.active = False
        self.bridge.set_state("idle")
        self.assertEqual(self.window.executados, [])


class TestApiDaPagina(HudTest):
    def test_texto_digitado_chega_ao_python(self):
        recebidos = []
        self.bridge.on_submit = recebidos.append

        api = H.HudBridge.Api(self.bridge)
        api.send("que horas são")

        for _ in range(100):
            if recebidos:
                break
            import time
            time.sleep(0.01)

        self.assertEqual(recebidos, ["que horas são"])

    def test_troca_de_microfone_chega_ao_python(self):
        recebidos = []
        self.bridge.on_set_mic = recebidos.append

        H.HudBridge.Api(self.bridge).set_mic("2")

        for _ in range(100):
            if recebidos:
                break
            import time
            time.sleep(0.01)

        self.assertEqual(recebidos, ["2"])

    def test_botao_parar(self):
        chamado = []
        self.bridge.on_stop = lambda: chamado.append(True)
        H.HudBridge.Api(self.bridge).stop()
        self.assertEqual(chamado, [True])

    def test_ready_solta_a_fila(self):
        self.bridge.set_state("idle")
        H.HudBridge.Api(self.bridge).ready()
        self.assertTrue(self.bridge.page_ready)
        self.assertEqual(len(self.window.executados), 1)

    def test_api_sem_ninguem_escutando(self):
        api = H.HudBridge.Api(self.bridge)
        self.assertTrue(api.send("oi"))
        self.assertTrue(api.set_mic("auto"))
        self.assertTrue(api.stop())

    def test_destroy(self):
        self.bridge.destroy()
        self.assertTrue(self.window.destruida)
        self.assertFalse(self.bridge.active)


class TestSemPywebview(unittest.TestCase):
    def test_disponivel_reflete_o_import(self):
        with mock.patch.object(H, "webview", None):
            self.assertFalse(H.available())

        with mock.patch.object(H, "webview", object()):
            self.assertTrue(H.available())

    def test_create_sem_pywebview(self):
        with mock.patch.object(H, "webview", None):
            bridge = H.HudBridge(Path("/tmp/x/index.html"), log=lambda *a: None)
            self.assertFalse(bridge.create())
            self.assertFalse(bridge.active)


# ============================================================
# BOTAO DE ENVIAR ARQUIVO
# ============================================================

class TestSeletorDeArquivo(HudTest):
    def com_janela(self, escolhidos=None, estourar=False):
        self.window = FakeWindow(escolhidos=escolhidos, estourar=estourar)
        self.bridge.window = self.window

        # O modulo pode nao ter o pywebview instalado; o seletor usa a
        # constante OPEN_DIALOG dele.
        if H.webview is None:
            self.falso_webview = types.SimpleNamespace(OPEN_DIALOG=10)
            self.patch = mock.patch.object(H, "webview", self.falso_webview)
            self.patch.start()
            self.addCleanup(self.patch.stop)

        return self.window

    def test_devolve_os_caminhos_escolhidos(self):
        self.com_janela(escolhidos=("C:\\x\\a.py", "C:\\x\\b.png"))
        caminhos = self.bridge.escolher_arquivos()

        self.assertEqual(caminhos, ["C:\\x\\a.py", "C:\\x\\b.png"])

    def test_pede_selecao_multipla(self):
        janela = self.com_janela(escolhidos=("a",))
        self.bridge.escolher_arquivos()

        self.assertTrue(janela.dialogos[0][1])

    def test_um_texto_so_vira_lista(self):
        # Versoes diferentes do pywebview devolvem tupla, lista ou um
        # texto so.
        self.com_janela(escolhidos="C:\\x\\a.py")
        self.assertEqual(self.bridge.escolher_arquivos(), ["C:\\x\\a.py"])

    def test_cancelar_devolve_lista_vazia(self):
        self.com_janela(escolhidos=None)
        self.assertEqual(self.bridge.escolher_arquivos(), [])

    def test_lista_vazia_do_seletor(self):
        self.com_janela(escolhidos=())
        self.assertEqual(self.bridge.escolher_arquivos(), [])

    def test_seletor_que_estoura_nao_derruba(self):
        self.com_janela(estourar=True)
        self.assertEqual(self.bridge.escolher_arquivos(), [])

    def test_sem_janela_devolve_vazio(self):
        self.bridge.window = None
        self.assertEqual(self.bridge.escolher_arquivos(), [])

    def test_a_api_da_pagina_avisa_o_python(self):
        self.com_janela(escolhidos=("C:\\x\\a.py",))

        recebidos = []
        pronto = threading.Event()

        def anotar(caminhos):
            recebidos.extend(caminhos)
            pronto.set()

        self.bridge.on_files = anotar
        devolvidos = self.bridge.Api(self.bridge).pick_files()

        self.assertEqual(devolvidos, ["C:\\x\\a.py"])
        self.assertTrue(pronto.wait(timeout=5))
        self.assertEqual(recebidos, ["C:\\x\\a.py"])

    def test_cancelar_nao_avisa_o_python(self):
        self.com_janela(escolhidos=None)

        recebidos = []
        self.bridge.on_files = recebidos.extend

        self.assertEqual(self.bridge.Api(self.bridge).pick_files(), [])
        self.assertEqual(recebidos, [])

    def test_sem_callback_nao_estoura(self):
        self.com_janela(escolhidos=("a",))
        self.bridge.on_files = None

        self.assertEqual(self.bridge.Api(self.bridge).pick_files(), ["a"])


class TestBotaoNaPagina(HudTest):
    def test_a_pagina_tem_o_botao(self):
        html = H.HUD_HTML
        self.assertIn('id="file"', html)
        self.assertIn("ARQUIVO", html)

    def test_o_botao_chama_o_seletor_nativo(self):
        self.assertIn("pick_files", H.HUD_HTML)

    def test_o_botao_nao_usa_input_file(self):
        # O <input type=file> do HTML nao entrega o caminho no disco, e
        # sem caminho o NEBELL nao consegue editar o arquivo depois.
        self.assertNotIn('type="file"', H.HUD_HTML)

    def test_o_botao_tem_estilo_proprio(self):
        self.assertIn("#file{", H.HUD_HTML)

    def test_o_parar_continua_la(self):
        self.assertIn('id="halt"', H.HUD_HTML)


# ============================================================
# A NUVEM DE PARTICULAS NA PAGINA
# ============================================================

class TestNuvemNaPagina(unittest.TestCase):
    """
    O nucleo da janela e a nuvem de particulas, e cada forma e um
    estado. O que importa aqui e que os dois lados -- o Python e a
    pagina -- nao saiam do lugar um sem o outro.
    """

    def test_o_motor_esta_embutido(self):
        # Tem de ir dentro da pagina: a pasta precisa rodar offline,
        # e um arquivo .js solto nao sobreviveria ao empacotamento.
        self.assertIn("NebellFormas", H.HUD_HTML)
        self.assertIn("NebellFormas.criar", H.HUD_HTML)

    def test_a_pagina_nao_busca_nada_de_fora_para_o_nucleo(self):
        corpo = H.HUD_HTML
        self.assertNotIn("three.min.js", corpo)
        self.assertNotIn("cdn.jsdelivr", corpo)
        self.assertNotIn("unpkg.com", corpo)

    def test_a_ponte_da_pagina_tem_o_que_o_python_chama(self):
        for metodo in (
            "setState", "paraFerramenta", "setEsforco", "setLevel",
            "addMessage", "streamMessage", "fecharStream",
            "trabalhando", "setStats", "setMics",
        ):
            self.assertIn(metodo, H.HUD_HTML, metodo)

    def test_o_desenho_antigo_saiu(self):
        # Se os dois ficassem na pagina, os dois desenhariam no mesmo
        # canvas e um apagaria o outro.
        self.assertNotIn("const ST={idle:", H.HUD_HTML)
        self.assertNotIn("barsK", H.HUD_HTML)

    def test_o_esforco_sai_da_carga_da_maquina(self):
        self.assertIn("daCarga", H.HUD_HTML)
        self.assertIn("setEsforco", H.HUD_HTML)

    # ---- os dois lados batem ----

    def estados_da_pagina(self):
        """Os nomes dos estados declarados no motor dentro da pagina."""
        trecho = re.search(
            r"const ESTADOS = \{(.+?)\n  \};", H.HUD_HTML, re.S
        )
        self.assertIsNotNone(trecho, "não achei a tabela de estados")
        return set(re.findall(r"^\s*(\w+):\s*\{", trecho.group(1), re.M))

    def mapa_da_pagina(self):
        """ferramenta -> estado, como a pagina enxerga."""
        trecho = re.search(
            r"const DA_FERRAMENTA = \{(.+?)\n  \};", H.HUD_HTML, re.S
        )
        self.assertIsNotNone(trecho, "não achei o mapa das ferramentas")
        return dict(
            re.findall(r'(\w+):\s*"(\w+)"', trecho.group(1))
        )

    def formas_da_pagina(self):
        trecho = re.search(
            r"const FORMAS = \{(.+?)\n  \};", H.HUD_HTML, re.S
        )
        self.assertIsNotNone(trecho, "não achei as formas")
        return set(re.findall(r"^\s*(\w+)[:(]", trecho.group(1), re.M))

    def test_toda_ferramenta_do_nebell_tem_forma(self):
        """
        O teste que importa.

        Se ele criar uma ferramenta nova no nebell.py e esquecer de
        dar uma forma a ela, a janela cai calada no 'pensando' e
        ninguem percebe. Aqui a falta aparece.
        """
        import nebell as J

        mapa = self.mapa_da_pagina()
        sem_forma = sorted(set(J.O_QUE_ESTA_FAZENDO) - set(mapa))

        self.assertEqual(
            sem_forma, [],
            "estas ferramentas não têm forma na janela: "
            + ", ".join(sem_forma),
        )

    def test_o_mapa_nao_aponta_para_ferramenta_que_nao_existe(self):
        import nebell as J

        mapa = self.mapa_da_pagina()
        fantasmas = sorted(set(mapa) - set(J.O_QUE_ESTA_FAZENDO))

        self.assertEqual(
            fantasmas, [],
            "a janela mapeia ferramentas que o NEBELL não tem: "
            + ", ".join(fantasmas),
        )

    def test_todo_estado_apontado_existe(self):
        estados = self.estados_da_pagina()

        for ferramenta, estado in self.mapa_da_pagina().items():
            self.assertIn(estado, estados, f"{ferramenta} -> {estado}")

    def test_todo_estado_tem_uma_forma_de_verdade(self):
        formas = self.formas_da_pagina()
        declaradas = re.findall(r'forma:\s*"(\w+)"', H.HUD_HTML)

        self.assertTrue(declaradas)

        for nome in set(declaradas):
            self.assertIn(nome, formas, nome)

    def test_os_quatro_nomes_antigos_continuam_valendo(self):
        # O nebell.py ainda manda idle/listening/thinking/speaking.
        for antigo in ("idle", "listening", "thinking", "speaking"):
            self.assertIn(antigo, H.HUD_HTML, antigo)


class TestPonteDaNuvem(unittest.TestCase):
    """Os métodos novos da ponte, sem abrir janela nenhuma."""

    def setUp(self):
        self.ponte = H.HudBridge.__new__(H.HudBridge)
        self.ponte.chamadas = []
        self.ponte._last_state = None
        self.ponte.call = lambda m, *a: self.ponte.chamadas.append((m, a))

    def test_para_ferramenta_manda_o_nome(self):
        self.ponte.para_ferramenta("ler_tela")
        self.assertEqual(self.ponte.chamadas, [("paraFerramenta", ("ler_tela",))])

    def test_nao_repete_a_mesma_ferramenta(self):
        self.ponte.para_ferramenta("ler_tela")
        self.ponte.para_ferramenta("ler_tela")
        self.assertEqual(len(self.ponte.chamadas), 1)

    def test_ferramenta_vazia_nao_manda_nada(self):
        self.ponte.para_ferramenta("")
        self.ponte.para_ferramenta(None)
        self.assertEqual(self.ponte.chamadas, [])

    def test_trocar_de_estado_destrava_a_ferramenta(self):
        self.ponte.para_ferramenta("ler_tela")
        self.ponte.set_state("idle")
        self.ponte.para_ferramenta("ler_tela")
        self.assertEqual(len(self.ponte.chamadas), 3)

    def test_esforco_vai_como_numero(self):
        self.ponte.set_esforco(0.5)
        self.assertEqual(self.ponte.chamadas, [("setEsforco", (0.5,))])


if __name__ == "__main__":
    unittest.main(verbosity=2)
