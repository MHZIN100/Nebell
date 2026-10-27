"""
Bateria de testes do nebell.

Simula Piper, microfone, Ollama e a internet, para que toda a logica
possa ser verificada sem depender do Windows nem de modelos baixados.

Uso:  python test_nebell.py
"""

import importlib.util
import io
import json
import queue
import re
import shutil
import sys
import tempfile
import threading
import time
import types
import unittest
import wave
from pathlib import Path
from unittest import mock

import requests

import numpy          # noqa: F401  (fica no sys.modules)
import nebell as J


# ============================================================
# DUBLES
# ============================================================

class FakeVoice:
    """Piper simulado: gera um WAV curto e valido."""

    def __init__(self):
        self.config = types.SimpleNamespace(
            length_scale=1.0, noise_scale=0.6, noise_w_scale=0.75
        )
        self.spoken = []

    def synthesize_wav(self, text, wav_file, syn_config=None):
        self.spoken.append(text)
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes(b"\x00\x00" * 220)   # 10 ms


class FakeResponse:
    """Resposta HTTP em streaming, no formato NDJSON do Ollama."""

    def __init__(self, chunks=(), status_code=200, text=""):
        self._chunks = list(chunks)
        self.status_code = status_code
        self.text = text

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_content(self, chunk_size=None):
        for chunk in self._chunks:
            yield chunk

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"status {self.status_code}")


class FakeSession:
    """Guarda o que foi enviado e devolve respostas em fila."""

    def __init__(self, responses=()):
        self.responses = list(responses)
        self.payloads = []

    def post(self, url, json=None, stream=False, timeout=None, **kwargs):
        self.payloads.append(json)

        if not self.responses:
            return FakeResponse([b'{"done":true}\n'])

        return self.responses.pop(0)

    def get(self, url, timeout=None, **kwargs):
        return FakeResponse()


def ndjson(*messages):
    """Transforma dicionarios em pedacos de bytes como o Ollama envia."""
    return [json.dumps(m).encode("utf-8") + b"\n" for m in messages]


def text_chunk(content, done=False):
    return {"message": {"content": content}, "done": done}


def tool_chunk(name, args, done=True):
    return {
        "message": {
            "content": "",
            "tool_calls": [{"function": {"name": name, "arguments": args}}],
        },
        "done": done,
    }


# ============================================================
# PREPARO GLOBAL
# ============================================================

TMP = None
fake_voice = None


def setUpModule():
    global TMP, fake_voice

    TMP = Path(tempfile.mkdtemp(prefix="nebell_test_"))

    J.BASE_DIR = TMP
    J.WORKSPACE_DIR = TMP / "workspace"
    J.MEMORY_DB = TMP / "memoria.db"
    J.LEGACY_MEMORY_FILE = TMP / "memoria.json"
    J.WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

    fake_voice = FakeVoice()
    J.voice = fake_voice
    J.METRICS = False
    J.audio_backend = "nenhum"      # sem placa de som nos testes

    # As duas etapas da voz rodam de verdade, so que com o Piper simulado.
    garantir_trabalhadores()


trabalhadores = []


def garantir_trabalhadores():
    """
    Deixa a sintese e a reproducao de pe.

    Precisa ser refeito porque os testes do encerramento mandam o
    shutdown_event e uma mensagem de parada na fila, e isso mata os dois
    trabalhadores. Sem religa-los, qualquer teste seguinte que falasse
    algo ficaria esperando para sempre por uma fila que ninguem mais
    esvazia.
    """
    J.shutdown_event.clear()
    J.encerramento_feito.clear()

    vivos = [t for t in trabalhadores if t.is_alive()]

    if len(vivos) == 2:
        return

    for thread in vivos:
        # Um sozinho nao serve: para os dois e recomeca o par.
        J.shutdown_event.set()
        J.speech_queue.put(None)
        thread.join(timeout=2)

    J.shutdown_event.clear()
    drenar_filas()

    trabalhadores.clear()

    for alvo in (J.synth_worker, J.player_worker):
        thread = threading.Thread(target=alvo, daemon=True)
        thread.start()
        trabalhadores.append(thread)


def drenar_filas():
    """
    Esvazia as filas pelo `drain` do proprio NEBELL.

    Esvaziar na mao com get_nowait deixa o contador interno da fila
    sem o task_done correspondente, e dai qualquer join() seguinte
    espera para sempre: o teste travava no primeiro aviso falado.
    """
    for fila in (J.speech_queue, J.audio_queue, J.request_queue):
        J.drain(fila)


NO_WINDOWS = J.IS_WINDOWS


def tem(modulo):
    """
    Diz se o pacote esta instalado nesta maquina.

    Os testes de documento precisam disto: sem o python-docx nao ha o
    que testar, e um teste que FALHA por pacote ausente esconde os
    bugs de verdade no meio do barulho. Pular e a resposta honesta.
    """
    try:
        return importlib.util.find_spec(modulo) is not None
    except (ImportError, ValueError):
        return False


TEM_WORD = tem("docx")
TEM_PLANILHA = tem("openpyxl")
TEM_APRESENTACAO = tem("pptx")
TEM_PDF = tem("reportlab")

PRECISA_WORD = unittest.skipUnless(TEM_WORD, "precisa do python-docx")
PRECISA_PLANILHA = unittest.skipUnless(TEM_PLANILHA, "precisa do openpyxl")
PRECISA_APRESENTACAO = unittest.skipUnless(
    TEM_APRESENTACAO, "precisa do python-pptx"
)
PRECISA_PDF = unittest.skipUnless(TEM_PDF, "precisa do reportlab")


def caminho_de_sistema():
    """Um caminho que a proteção tem de recusar, nesta plataforma."""
    return Path(r"C:\Windows\System32\drivers\etc\hosts") if NO_WINDOWS \
        else Path("/etc/passwd")


def caminho_impossivel():
    """Um caminho onde não se consegue criar arquivo, nesta plataforma."""
    return r"Z:\nao\existe\x.db" if NO_WINDOWS else "/proc/impossivel/x.db"


def abrir_memoria_de_teste():
    """Memória nova em cada teste, para um não contaminar o outro."""
    import nebell_memoria

    if J.memoria is not None:
        J.memoria.fechar()

    caminho = TMP / "memoria.db"

    for sufixo in ("", "-wal", "-shm"):
        alvo = Path(str(caminho) + sufixo)
        if alvo.exists():
            alvo.unlink()

    J.memoria = nebell_memoria.Memoria(caminho, log=lambda *a: None)
    J.memoria.abrir()
    J.memoria.iniciar_conversa("teste")
    return J.memoria


def flush_speech():
    J.wait_for_speech()
    spoken = list(fake_voice.spoken)
    fake_voice.spoken.clear()
    return spoken


class NebellTest(unittest.TestCase):
    def setUp(self):
        garantir_trabalhadores()
        abrir_memoria_de_teste()
        J.reset_history()
        J.first_chunk_pending = True
        J.tools_supported = True
        J.interaction_mode = "text"
        J.synthesis_config = None
        J.cancel_event.clear()
        J.busy_event.clear()
        # Uma sessão resume uma vez só; cada teste é uma sessão nova.
        J.resumo_feito.clear()
        J.stop_speaking()
        fake_voice.spoken.clear()


# ============================================================
# TEXTO E COMANDOS
# ============================================================

class TestNormalizacao(NebellTest):
    def test_remove_acentos_e_espacos(self):
        self.assertEqual(J.normalize("  Configurações   ÚNICAS "), "configuracoes unicas")

    def test_aceita_nao_texto(self):
        self.assertEqual(J.normalize(123), "123")

    def test_modo_por_voz(self):
        self.assertEqual(J.parse_mode_choice("quero por voz"), "voice")
        self.assertEqual(J.parse_mode_choice("vou digitar"), "text")
        self.assertEqual(J.parse_mode_choice("pode encerrar"), "exit")
        self.assertIsNone(J.parse_mode_choice("bom dia"))

    def test_prioridade_do_encerrar(self):
        # "sair" vence mesmo com a palavra "voz" na frase.
        self.assertEqual(J.parse_mode_choice("sair do modo voz"), "exit")

    def test_comandos_de_voz(self):
        self.assertEqual(J.parse_voice_command("voltar ao menu"), "menu")
        self.assertEqual(J.parse_voice_command("modo texto por favor"), "text")
        self.assertEqual(J.parse_voice_command("modo voz"), "voice")
        self.assertEqual(J.parse_voice_command("pode desligar"), "exit")
        self.assertIsNone(J.parse_voice_command("que horas sao"))

    def test_palavra_de_ativacao(self):
        for palavra in ("nebell", "nebel", "nebela", "rebel", "nevel"):
            self.assertTrue(J.WAKE_RE.search(palavra), palavra)

        # Palavras comuns que não devem acordá-lo.
        for palavra in ("javascript", "nebulosa", "rebelde", "novela"):
            self.assertFalse(J.WAKE_RE.search(palavra), palavra)

    def test_alucinacoes_do_whisper(self):
        self.assertTrue(J.HALLUCINATION_RE.search("Legendas pela comunidade Amara.org"))
        self.assertTrue(J.HALLUCINATION_RE.search("Inscreva-se no canal"))
        self.assertFalse(J.HALLUCINATION_RE.search("qual a cotacao do dolar"))


# ============================================================
# FILTRO <think>
# ============================================================

class TestThinkFilter(NebellTest):
    def test_prefixo_no_fim(self):
        self.assertEqual(J.tail_prefix_length("ola <th", "<think>"), 3)
        self.assertEqual(J.tail_prefix_length("ola mundo", "<think>"), 0)
        self.assertEqual(J.tail_prefix_length("tudo <", "<think>"), 1)

    def test_remove_bloco_inteiro(self):
        f = J.ThinkFilter()
        out = f.feed("<think>raciocinio secreto</think>Bom dia, senhor.")
        self.assertEqual(out, "Bom dia, senhor.")
        self.assertEqual(f.finish(), "")

    def test_tag_dividida_entre_pedacos(self):
        f = J.ThinkFilter()
        saida = "".join([
            f.feed("Ola <thi"),
            f.feed("nk>oculto</thi"),
            f.feed("nk> senhor."),
        ])
        self.assertEqual(saida + f.finish(), "Ola  senhor.")

    def test_nao_segura_texto_sem_tag(self):
        # Esse era o gargalo antigo: seis caracteres ficavam retidos
        # em cada pedaco, atrasando o inicio da fala.
        f = J.ThinkFilter()
        self.assertEqual(f.feed("Bom dia, senhor"), "Bom dia, senhor")

    def test_segura_apenas_o_que_pode_ser_tag(self):
        f = J.ThinkFilter()
        self.assertEqual(f.feed("Tudo certo <"), "Tudo certo ")
        self.assertEqual(f.feed("3 graus."), "<3 graus.")

    def test_think_nao_fechado_e_descartado(self):
        f = J.ThinkFilter()
        f.feed("ola <think>pensando sem fim")
        self.assertEqual(f.finish(), "")


# ============================================================
# PREPARO DO TEXTO FALADO
# ============================================================

class TestTextoFalado(NebellTest):
    def test_limpeza(self):
        texto = J.clean_for_speech(
            "**Hoje** faz 25°C, 30% de chuva e custa R$ 15,90. "
            "Veja https://exemplo.com e M&S ```codigo```"
        )
        self.assertNotIn("**", texto)
        self.assertNotIn("http", texto)
        self.assertIn("graus Celsius", texto)
        self.assertIn("por cento", texto)
        self.assertIn("15,90 reais", texto)
        self.assertIn(" e ", texto)

    def test_fim_de_frase_real(self):
        self.assertTrue(J.is_sentence_end("Bom dia.", 7))
        self.assertFalse(J.is_sentence_end("custa 3.5 reais", 7))
        self.assertFalse(J.is_sentence_end("o Sr. Silva", 4))

    def test_encontra_fim_de_frase(self):
        self.assertEqual(J.find_sentence_end("Bom dia. Tudo bem?"), 9)
        self.assertEqual(J.find_sentence_end("A taxa e de 3.5 por cento e"), -1)

    def test_primeiro_trecho_sai_na_virgula(self):
        J.first_chunk_pending = True
        resto = J.queue_sentences("Claro senhor, o tempo hoje esta")
        falado = flush_speech()
        self.assertEqual(falado, ["Claro senhor,"])
        self.assertEqual(resto, "o tempo hoje esta")

    def test_frase_completa_tem_prioridade(self):
        J.first_chunk_pending = False
        resto = J.queue_sentences("Sao vinte graus. E deve")
        self.assertEqual(flush_speech(), ["Sao vinte graus."])
        self.assertEqual(resto, "E deve")

    def test_nao_corta_em_abreviacao(self):
        J.first_chunk_pending = False
        texto = "O Sr. Silva confirmou que o valor e de 3.5 por cento"
        resto = J.queue_sentences(texto)
        for falado in flush_speech():
            self.assertNotIn("Sr.", falado.split()[-1:])
        self.assertNotIn("3.5", "".join(flush_speech()))

    def test_force_despacha_o_resto(self):
        J.first_chunk_pending = False
        resto = J.queue_sentences("sem pontuacao final", force=True)
        self.assertEqual(resto, "")
        self.assertEqual(flush_speech(), ["sem pontuacao final"])

    def test_trecho_longo_sem_pontuacao(self):
        J.first_chunk_pending = False
        longo = "palavra " * 30
        resto = J.queue_sentences(longo)
        self.assertTrue(flush_speech())
        self.assertLess(len(resto), len(longo))


# ============================================================
# PIPELINE DE VOZ
# ============================================================

class TestPipelineDeVoz(NebellTest):
    def test_fala_passa_pelo_piper(self):
        J.speak("Bom dia, senhor.")
        self.assertEqual(flush_speech(), ["Bom dia, senhor."])

    def test_texto_vazio_e_ignorado(self):
        J.speak("   ")
        self.assertEqual(flush_speech(), [])

    def test_duracao_do_wav(self):
        data, seconds = J.synthesize_to_bytes("teste")
        self.assertGreater(len(data), 44)
        self.assertAlmostEqual(seconds, 220 / 22050, places=3)

    def test_cache_de_frases_fixas(self):
        J._filler_cache.clear()
        J.warm_up_voice()
        self.assertIn("Um momento.", J._filler_cache)

        antes = len(fake_voice.spoken)
        J.synthesize_cached("Um momento.")
        self.assertEqual(len(fake_voice.spoken), antes)   # nao sintetizou de novo

    def test_stop_speaking_esvazia_as_filas(self):
        for _ in range(5):
            J.speech_queue.put("frase longa de teste")
        J.stop_speaking()
        J.wait_for_speech()
        self.assertTrue(J.speech_queue.empty())
        self.assertTrue(J.audio_queue.empty())
        self.assertFalse(J.stop_speaking_event.is_set())


# ============================================================
# SEGURANCA
# ============================================================

class TestSeguranca(NebellTest):
    def test_comandos_destrutivos_bloqueados(self):
        """Só o que destrói o disco ou o Windows fica barrado."""
        perigosos = [
            "format C: /q", "diskpart", "bcdedit /set safeboot",
            "cipher /w:C", "Clear-Disk -Number 0", "vssadmin delete shadows",
            "Remove-Item C:\\ -Recurse",
        ]
        for comando in perigosos:
            self.assertTrue(J.BLOCKED_COMMANDS.search(comando), comando)

    def test_comandos_sensiveis_passam_com_aviso(self):
        """Funcionam, mas com confirmação reforçada."""
        sensiveis = [
            "shutdown /s /t 0", "reg delete HKLM\\Software\\X",
            "Set-ExecutionPolicy Bypass", "schtasks /create /tn backup",
            "net user teste /add",
        ]
        for comando in sensiveis:
            self.assertFalse(J.BLOCKED_COMMANDS.search(comando), comando)
            self.assertTrue(J.SENSITIVE_COMMANDS.search(comando), comando)

    def test_comandos_permitidos(self):
        for comando in ["Get-Date", "Get-ChildItem", "Get-Process | Select -First 5",
                        "ipconfig /all", "Start-Process notepad",
                        "iwr https://exemplo.com", "curl https://exemplo.com"]:
            self.assertFalse(J.BLOCKED_COMMANDS.search(comando), comando)

    def test_caminho_permitido(self):
        ok, _ = J.path_is_allowed(J.WORKSPACE_DIR / "notas.txt")
        self.assertTrue(ok)

    def test_caminho_de_sistema_negado(self):
        ok, motivo = J.path_is_allowed(caminho_de_sistema())
        self.assertFalse(ok)
        self.assertTrue(motivo)

    def test_pasta_sensivel_negada(self):
        ok, _ = J.path_is_allowed(Path.home() / ".ssh" / "config")
        self.assertFalse(ok)

    def test_arquivo_sensivel_negado(self):
        ok, _ = J.path_is_allowed(J.WORKSPACE_DIR / "id_rsa")
        self.assertFalse(ok)

    def test_leitura_fora_da_area_e_recusada(self):
        self.assertIn(
            "protegid", J.tool_ler_arquivo(str(caminho_de_sistema())).lower()
        )

    def test_caminho_relativo_vai_para_a_pasta_de_trabalho(self):
        self.assertEqual(J.resolve_path("notas.txt"), J.WORKSPACE_DIR / "notas.txt")

    def test_comando_bloqueado_nao_pede_confirmacao(self):
        with mock.patch.object(J, "confirm_action") as confirm:
            resultado = J.tool_executar_comando("format C: /q")
        confirm.assert_not_called()
        self.assertIn("bloqueado", resultado)


# ============================================================
# FERRAMENTAS DE ARQUIVO
# ============================================================

class TestArquivos(NebellTest):
    def test_listar_pasta(self):
        (J.WORKSPACE_DIR / "a.txt").write_text("x", encoding="utf-8")
        (J.WORKSPACE_DIR / "sub").mkdir(exist_ok=True)
        saida = J.tool_listar_pasta(".")
        self.assertIn("[arquivo] a.txt", saida)
        self.assertIn("[pasta] sub", saida)

    def test_listar_pasta_inexistente(self):
        self.assertIn("não encontrada", J.tool_listar_pasta("nao_existe_123"))

    def test_ler_arquivo(self):
        (J.WORKSPACE_DIR / "leitura.txt").write_text("conteúdo", encoding="utf-8")
        self.assertEqual(J.tool_ler_arquivo("leitura.txt"), "conteúdo")

    def test_ler_arquivo_inexistente(self):
        self.assertIn("não encontrado", J.tool_ler_arquivo("sumiu.txt"))

    def test_escrever_com_autorizacao(self):
        with mock.patch.object(J, "confirm_action", return_value=True):
            resultado = J.tool_escrever_arquivo("novo.txt", "primeiro")
        self.assertIn("gravado", resultado)
        self.assertEqual((J.WORKSPACE_DIR / "novo.txt").read_text(encoding="utf-8"), "primeiro")

    def test_escrever_faz_backup(self):
        with mock.patch.object(J, "confirm_action", return_value=True):
            J.tool_escrever_arquivo("bkp.txt", "versao 1")
            J.tool_escrever_arquivo("bkp.txt", "versao 2")

        self.assertEqual((J.WORKSPACE_DIR / "bkp.txt").read_text(encoding="utf-8"), "versao 2")
        self.assertEqual(
            (J.WORKSPACE_DIR / "bkp.txt.bak").read_text(encoding="utf-8"), "versao 1"
        )

    def test_escrever_negado(self):
        with mock.patch.object(J, "confirm_action", return_value=False):
            resultado = J.tool_escrever_arquivo("negado.txt", "nada")
        self.assertIn("negou", resultado)
        self.assertFalse((J.WORKSPACE_DIR / "negado.txt").exists())


# ============================================================
# FERRAMENTAS DO COMPUTADOR
# ============================================================

class TestComputador(NebellTest):
    def test_abrir_programa_conhecido(self):
        with mock.patch.object(J.subprocess, "Popen") as popen:
            resultado = J.tool_abrir_programa("bloco de notas")
        popen.assert_called_once()
        self.assertIn("bloco de notas", resultado)

    def test_abrir_programa_por_apelido(self):
        with mock.patch.object(J.subprocess, "Popen"):
            self.assertIn("chrome", J.tool_abrir_programa("google chrome"))

    def test_abrir_programa_desconhecido(self):
        with mock.patch.object(J.subprocess, "Popen") as popen, \
             mock.patch.object(J, "listar_apps_instalados", return_value=[]), \
             mock.patch.object(J.shutil, "which", return_value=None):
            resultado = J.tool_abrir_programa("photoshop")

        popen.assert_not_called()
        self.assertIn("Não encontrei", resultado)

    def test_nome_curto_nao_casa_por_acidente(self):
        # "e" nao pode abrir "bloco de notas".
        self.assertEqual(J.find_app("e"), (None, None))

    def test_abrir_site_completa_o_https(self):
        # Sem forçar o navegador padrão, este teste abria o Brave de
        # verdade na máquina de quem rodasse a suíte.
        with mock.patch.object(J, "achar_navegador", return_value=None), \
             mock.patch.object(J.webbrowser, "open") as abrir:
            J.tool_abrir_site("exemplo.com")

        abrir.assert_called_once_with("https://exemplo.com")

    def test_data_hora(self):
        saida = J.tool_data_hora()
        self.assertRegex(saida, r"\d{2}/\d{2}/\d{4}")
        self.assertRegex(saida, r"\d{2}:\d{2}")

    @unittest.skipIf(NO_WINDOWS, "no Windows o volume funciona de verdade")
    def test_volume_fora_do_windows(self):
        resultado = J.tool_controlar_volume("aumentar")
        self.assertIn("Não consegui", resultado)

    def test_volume_sem_sistema_que_suporte(self):
        """Independente da plataforma: sem a tecla de mídia, avisa."""
        with mock.patch.object(J, "press_media_key", return_value=False):
            self.assertIn("Não consegui", J.tool_controlar_volume("aumentar"))

    def test_volume_passos(self):
        with mock.patch.object(J, "press_media_key", return_value=True) as tecla:
            J.tool_controlar_volume("aumentar", 10)
        tecla.assert_called_once_with(J.VK_VOLUME_UP, 5)

    def test_volume_definir(self):
        with mock.patch.object(J, "press_media_key", return_value=True) as tecla:
            resultado = J.tool_controlar_volume("definir", 50)
        self.assertEqual(tecla.call_args_list[0][0], (J.VK_VOLUME_DOWN, 50))
        self.assertIn("50", resultado)

    def test_volume_acao_desconhecida(self):
        self.assertIn("desconhecida", J.tool_controlar_volume("girar"))

    def test_musica_youtube(self):
        with mock.patch.object(J.webbrowser, "open") as abrir:
            resultado = J.tool_tocar_musica("Legiao Urbana", "youtube")
        self.assertIn("music.youtube.com", abrir.call_args[0][0])
        self.assertIn("Legiao Urbana", resultado)

    def test_musica_sem_nome(self):
        self.assertIn("Informe", J.tool_tocar_musica(""))


# ============================================================
# INTERNET
# ============================================================

class TestInternet(NebellTest):
    """A internet agora vive no nebell_web; aqui só a ligação."""

    def test_pesquisa_devolve_o_material(self):
        falso = ("Resultados para: dólar\n1. Dólar hoje\n   R$ 5,40", None)

        with mock.patch.object(J.nebell_web, "buscar", return_value=falso):
            resultado = J.tool_pesquisar_web("cotação do dólar")

        self.assertIn("5,40", resultado)
        self.assertIn("dado concreto", resultado)

    def test_pesquisa_com_erro(self):
        with mock.patch.object(
            J.nebell_web, "buscar", return_value=(None, "sem rede")
        ):
            self.assertIn("sem rede", J.tool_pesquisar_web("x"))

    def test_sem_modulo_de_internet(self):
        with mock.patch.object(J, "nebell_web", None):
            for resultado in (J.tool_pesquisar_web("x"), J.tool_clima(),
                              J.tool_cotacao(), J.tool_ler_pagina("http://x")):
                self.assertIn("não está disponível", resultado)

    def test_ler_pagina(self):
        with mock.patch.object(
            J.nebell_web, "ler_pagina", return_value=("Texto da página", None)
        ):
            self.assertEqual(
                J.tool_ler_pagina("https://x.com"), "Texto da página"
            )

    def test_ler_pagina_com_erro(self):
        with mock.patch.object(
            J.nebell_web, "ler_pagina", return_value=(None, "não abriu")
        ):
            self.assertIn("não abriu", J.tool_ler_pagina("https://x.com"))

    def test_clima_usa_a_cidade_do_usuario(self):
        J.location_info.update({
            "cidade": "Cachoeira", "lat": -12.6, "lon": -38.96,
        })
        J.location_fetched_at = time.time()

        with mock.patch.object(
            J.nebell_web, "clima",
            return_value=("Agora em Cachoeira faz 28 graus, céu limpo.", {}),
        ) as clima:
            resultado = J.tool_clima()

        self.assertIn("28 graus", resultado)
        self.assertEqual(clima.call_args[0][0], -12.6)

    def test_clima_sem_coordenadas(self):
        with mock.patch.object(J, "detect_location", return_value={}):
            self.assertIn("Diga a cidade", J.tool_clima())

    def test_clima_de_outra_cidade(self):
        J.location_info.update({
            "cidade": "Cachoeira", "lat": -12.6, "lon": -38.96,
        })
        J.location_fetched_at = time.time()

        geo = {"results": [{"latitude": -23.5, "longitude": -46.6,
                            "name": "São Paulo"}]}

        with mock.patch.object(J.nebell_web, "pegar_json", return_value=geo), \
             mock.patch.object(
                 J.nebell_web, "clima",
                 return_value=("Agora em São Paulo faz 19 graus.", {}),
             ) as clima:
            resultado = J.tool_clima("São Paulo")

        self.assertIn("São Paulo", resultado)
        self.assertEqual(clima.call_args[0][0], -23.5)

    def test_cotacao(self):
        with mock.patch.object(
            J.nebell_web, "cotacao",
            return_value=("O dólar está a 5,42 reais.", {}),
        ):
            self.assertIn("5,42", J.tool_cotacao("dolar"))

    def test_cotacao_com_erro(self):
        with mock.patch.object(
            J.nebell_web, "cotacao", return_value=(None, "fora do ar")
        ):
            self.assertIn("fora do ar", J.tool_cotacao())


class TestAtalhosDeClimaECotacao(NebellTest):
    """
    Clima e cotação respondem sem passar pelo modelo: eram os dois
    pedidos em que ele mais falhava, dizendo "veja em tal site".
    """

    def test_clima_nao_chama_o_modelo(self):
        fake = FakeSession()

        with mock.patch.object(J, "session", fake), \
             mock.patch.object(J, "tool_clima", return_value="Faz 28 graus."):
            J.ask_nebell("como está o clima")

        self.assertEqual(fake.payloads, [])
        self.assertIn("28 graus", " ".join(flush_speech()))

    def test_cotacao_nao_chama_o_modelo(self):
        fake = FakeSession()

        with mock.patch.object(J, "session", fake), \
             mock.patch.object(
                 J, "tool_cotacao", return_value="O dólar está a 5,42 reais."
             ):
            J.ask_nebell("qual a cotação do dólar")

        self.assertEqual(fake.payloads, [])
        self.assertIn("5,42", " ".join(flush_speech()))

    def test_frases_que_viram_clima(self):
        for frase in ["como está o clima", "vai chover hoje",
                      "quantos graus faz", "qual a temperatura",
                      "está chovendo", "faz frio"]:
            self.assertTrue(J.CLIMA_RE.search(J.normalize(frase)), frase)

    def test_frases_que_viram_cotacao(self):
        for frase in ["qual a cotação do dólar", "quanto está o euro",
                      "quanto vale o bitcoin", "valor do dólar",
                      "câmbio hoje"]:
            self.assertTrue(J.COTACAO_RE.search(J.normalize(frase)), frase)

    def test_perguntas_comuns_nao_sao_desviadas(self):
        for frase in ["me explique o que é um transistor", "abre o brave",
                      "quanto é dois mais dois", "quem descobriu o brasil"]:
            alvo = J.normalize(frase)
            self.assertFalse(J.CLIMA_RE.search(alvo), frase)
            self.assertFalse(J.COTACAO_RE.search(alvo), frase)


class TestRunTool(NebellTest):
    def test_ferramenta_desconhecida(self):
        self.assertIn("desconhecida", J.run_tool("voar", {}))

    def test_argumento_de_nome_estranho_e_aproveitado(self):
        """
        Antes isso virava "Argumentos inválidos" e o modelo repassava o
        erro ao usuário. Com um único obrigatório, o valor é aproveitado.
        """
        resultado = J.run_tool("ler_arquivo", {"xyz": "notas.txt"})
        self.assertIn("notas.txt", resultado)

    def test_ferramenta_sem_como_adivinhar(self):
        resultado = J.run_tool("editar_arquivo", {"aaa": 1, "bbb": 2, "ccc": 3})
        self.assertIn("precisa de", resultado)

    def test_erro_interno_e_capturado(self):
        with mock.patch.dict(J.TOOL_FUNCTIONS, {"quebra": lambda: 1 / 0}):
            self.assertIn("Erro ao executar", J.run_tool("quebra", {}))

    def test_resultado_e_truncado(self):
        with mock.patch.dict(J.TOOL_FUNCTIONS, {"grande": lambda: "x" * 99999}):
            self.assertEqual(len(J.run_tool("grande", {})), J.TOOL_RESULT_MAX)

    def test_args_nao_dicionario(self):
        self.assertIn("data", J.run_tool("data_hora", "lixo").lower() + "data")

    def test_toda_ferramenta_tem_schema(self):
        nomes = {s["function"]["name"] for s in J.TOOL_SCHEMAS}
        self.assertEqual(nomes, set(J.TOOL_FUNCTIONS))

    def test_parse_tool_call_com_json_em_texto(self):
        nome, args = J.parse_tool_call(
            {"function": {"name": "pesquisar_web", "arguments": '{"consulta": "dolar"}'}}
        )
        self.assertEqual(nome, "pesquisar_web")
        self.assertEqual(args, {"consulta": "dolar"})

    def test_parse_tool_call_com_json_quebrado(self):
        nome, args = J.parse_tool_call({"function": {"name": "x", "arguments": "{{{"}})
        self.assertEqual(args, {})


# ============================================================
# MEMORIA ENTRE SESSOES
# ============================================================

class TestMemoria(NebellTest):
    """Agora a memória é um banco SQLite, não mais um JSON."""

    def test_lembrar_e_persistir(self):
        J.tool_lembrar("prefere respostas curtas", "preferencia")
        self.assertTrue(J.MEMORY_DB.exists())

        textos = [f["texto"] for f in J.memoria.listar_fatos()]
        self.assertIn("prefere respostas curtas", textos)

    def test_nao_duplica(self):
        J.tool_lembrar("gosta de café")
        resultado = J.tool_lembrar("Gosta de Café")
        self.assertIn("já está", resultado)
        self.assertEqual(len(J.memoria.listar_fatos()), 1)

    def test_categoria_invalida_vira_geral(self):
        J.tool_lembrar("algo", "categoria inventada")
        self.assertEqual(J.memoria.listar_fatos()[0]["categoria"], "geral")

    def test_esquecer(self):
        J.tool_lembrar("tem um carro seguidor de linha")
        self.assertIn("Removi", J.tool_esquecer("seguidor de linha"))
        self.assertEqual(J.memoria.listar_fatos(), [])

    def test_esquecer_sem_achar(self):
        self.assertIn("Não encontrei", J.tool_esquecer("nada disso"))

    def test_memoria_entra_no_prompt(self):
        J.tool_lembrar("mora na Bahia")
        self.assertIn("mora na Bahia", J.build_system_prompt())
        self.assertIn("mora na Bahia", J.history[0]["content"])

    def test_preferencia_entra_como_preferencia(self):
        J.tool_lembrar("respostas de uma frase", "preferencia")
        self.assertIn("Preferências", J.build_system_prompt())

    def test_listar_memoria_vazia(self):
        self.assertIn("vazia", J.tool_listar_memoria())

    def test_listar_mostra_os_numeros(self):
        J.tool_lembrar("algo")
        self.assertIn("conversas", J.tool_listar_memoria())

    def test_sem_banco_as_ferramentas_avisam(self):
        guardado = J.memoria
        J.memoria = None
        try:
            for resultado in (J.tool_lembrar("x"), J.tool_recordar("x"),
                              J.tool_listar_projetos(), J.tool_listar_comandos(),
                              J.tool_arquivos_anteriores()):
                self.assertIn("não está disponível", resultado)
        finally:
            J.memoria = guardado


class TestConversaGravada(NebellTest):
    def test_pergunta_e_resposta_ficam_guardadas(self):
        fake = FakeSession([FakeResponse(ndjson(text_chunk("São dez horas.", True)))])

        with mock.patch.object(J, "session", fake):
            J.ask_nebell("me explique como funciona um capacitor")

        falas = J.memoria.material_para_resumo()
        papeis = [f["papel"] for f in falas]
        self.assertIn("user", papeis)
        self.assertIn("assistant", papeis)
        self.assertIn("São dez horas.", [f["conteudo"] for f in falas])
        flush_speech()

    def test_atalho_local_tambem_e_guardado(self):
        fake = FakeSession()

        with mock.patch.object(J, "session", fake):
            J.ask_nebell("que horas são")

        self.assertEqual(len(J.memoria.material_para_resumo()), 2)
        flush_speech()

    def test_recordar_acha_conversa_antiga(self):
        J.memoria.encerrar_conversa(resumo="falamos do carrinho")
        J.memoria.iniciar_conversa("teste")
        J.memoria.registrar_mensagem("user", "o driver HW-095 esquenta muito")
        J.memoria.encerrar_conversa(resumo="driver esquentando")
        J.memoria.iniciar_conversa("teste")

        resultado = J.tool_recordar("HW-095")
        self.assertIn("esquenta", resultado)
        self.assertIn("você disse", resultado)

    def test_recordar_sem_achar_e_honesto(self):
        resultado = J.tool_recordar("submarino nuclear")
        self.assertIn("primeira vez", resultado)

    def test_conversas_anteriores(self):
        J.memoria.encerrar_conversa(resumo="ajustamos a voz do Piper")
        J.memoria.iniciar_conversa("teste")
        self.assertIn("Piper", J.tool_conversas_anteriores())

    def test_sem_resumo_ainda(self):
        self.assertIn("Ainda não tenho", J.tool_conversas_anteriores())

    def test_resumo_da_sessao_usa_o_modelo(self):
        for i in range(3):
            J.memoria.registrar_mensagem("user", f"pergunta {i}")
            J.memoria.registrar_mensagem("assistant", f"resposta {i}")

        resposta = mock.Mock()
        resposta.json.return_value = {
            "message": {"content": "Tratamos do carrinho e do driver."}
        }
        resposta.raise_for_status = mock.Mock()

        with mock.patch.object(J.session, "post", return_value=resposta):
            resumo = J.resumir_sessao()

        self.assertIn("carrinho", resumo)

    def test_resumo_cai_para_reserva_sem_o_modelo(self):
        for i in range(3):
            J.memoria.registrar_mensagem("user", f"pergunta sobre o tema {i}")
            J.memoria.registrar_mensagem("assistant", f"resposta {i}")

        with mock.patch.object(J.session, "post", side_effect=Exception("off")):
            resumo = J.resumir_sessao()

        self.assertIn("Conversamos sobre", resumo)

    def test_conversa_curta_nao_gera_resumo(self):
        J.memoria.registrar_mensagem("user", "oi")

        with mock.patch.object(J.session, "post") as post:
            self.assertIsNone(J.resumir_sessao())

        post.assert_not_called()

    def test_limpa_o_pensamento_do_resumo(self):
        for i in range(3):
            J.memoria.registrar_mensagem("user", f"p{i}")
            J.memoria.registrar_mensagem("assistant", f"r{i}")

        resposta = mock.Mock()
        resposta.json.return_value = {
            "message": {"content": "<think>deixa eu ver</think> Resumo limpo."}
        }
        resposta.raise_for_status = mock.Mock()

        with mock.patch.object(J.session, "post", return_value=resposta):
            resumo = J.resumir_sessao()

        self.assertNotIn("deixa eu ver", resumo)
        self.assertIn("Resumo limpo", resumo)


class TestProjetosEArquivos(NebellTest):
    def test_salvar_e_ver_projeto(self):
        J.tool_salvar_projeto("Carro seguidor de linha", "Arduino com HW-095")
        resultado = J.tool_ver_projeto("seguidor")
        self.assertIn("HW-095", resultado)

    def test_projeto_entra_no_prompt(self):
        J.tool_salvar_projeto("Site Zeon", "loja virtual")
        self.assertIn("Site Zeon", J.build_system_prompt())

    def test_anotar_e_listar(self):
        J.tool_anotar_projeto("Carrinho", "o sensor da direita falha")
        self.assertIn("sensor", J.tool_ver_projeto("carrinho"))
        self.assertIn("Carrinho", J.tool_listar_projetos())

    def test_projeto_inexistente(self):
        self.assertIn("Não tenho um projeto", J.tool_ver_projeto("nada disso"))

    def test_listar_sem_projetos(self):
        self.assertIn("Nenhum projeto", J.tool_listar_projetos())

    def test_guardar_e_buscar_arquivo(self):
        alvo = J.WORKSPACE_DIR / "esquema.txt"
        alvo.write_text("ligações do motor", encoding="utf-8")

        J.tool_guardar_arquivo(alvo, resumo="esquema de ligação do motor")
        resultado = J.tool_arquivos_anteriores("esquema")
        self.assertIn("esquema.txt", resultado)
        self.assertIn("ligação", resultado)

    def test_avisa_que_o_arquivo_sumiu(self):
        J.tool_guardar_arquivo("C:\\sumiu\\antigo.pdf", resumo="nota antiga")
        self.assertIn("não está mais no disco", J.tool_arquivos_anteriores("antigo"))

    def test_arquivo_ligado_ao_projeto(self):
        J.tool_salvar_projeto("Carrinho")
        J.tool_guardar_arquivo("C:\\x\\sensor.ino", projeto="carrinho")
        self.assertIn("Carrinho", J.tool_arquivos_anteriores("sensor"))

    def test_sem_arquivos(self):
        self.assertIn("Ainda não registrei", J.tool_arquivos_anteriores())


class TestComandosAprendidos(NebellTest):
    def test_ensinar_e_aplicar_como_instrucao(self):
        J.tool_ensinar_comando("modo foco", "responda em uma frase só")

        direto, instrucao = J.aplicar_comando_aprendido("Nebell, ativa o modo foco")
        self.assertIsNone(direto)
        self.assertIn("uma frase só", instrucao)

    def test_comando_entra_no_prompt(self):
        J.tool_ensinar_comando("modo foco", "seja breve")
        self.assertIn("modo foco", J.build_system_prompt())

    def test_comando_com_ferramenta_executa_direto(self):
        J.tool_ensinar_comando(
            "boa noite", "desligue o bluetooth",
            ferramenta="bluetooth", argumentos={"acao": "desligar"},
        )

        with mock.patch.dict(
            J.TOOL_FUNCTIONS, {"bluetooth": lambda **k: "Bluetooth desligado."}
        ):
            direto, instrucao = J.aplicar_comando_aprendido("boa noite")

        self.assertEqual(direto, "Bluetooth desligado.")
        self.assertIn("já foi executado", instrucao)

    def test_ferramenta_que_nao_existe_e_recusada(self):
        resultado = J.tool_ensinar_comando(
            "faz mágica", "voe", ferramenta="voar"
        )
        self.assertIn("Não existe uma ferramenta", resultado)

    def test_argumentos_em_texto_json(self):
        J.tool_ensinar_comando(
            "meu som", "toque rock", ferramenta="tocar_musica",
            argumentos='{"busca": "rock classico"}',
        )
        comando = J.memoria.casar_comando("meu som")
        self.assertIn("rock classico", comando["argumentos"])

    def test_argumentos_invalidos_nao_derrubam(self):
        J.tool_ensinar_comando(
            "teste ruim", "faça algo", ferramenta="data_hora",
            argumentos="{isso não é json",
        )

        with mock.patch.dict(J.TOOL_FUNCTIONS, {"data_hora": lambda: "ok"}):
            direto, _ = J.aplicar_comando_aprendido("teste ruim")

        self.assertEqual(direto, "ok")

    def test_frase_comum_nao_dispara(self):
        J.tool_ensinar_comando("modo foco", "seja breve")
        direto, instrucao = J.aplicar_comando_aprendido("qual a capital do Chile")
        self.assertIsNone(direto)
        self.assertIsNone(instrucao)

    def test_listar_e_esquecer(self):
        J.tool_ensinar_comando("modo foco", "seja breve")
        self.assertIn("modo foco", J.tool_listar_comandos())
        self.assertIn("Esqueci", J.tool_esquecer_comando("foco"))
        self.assertIn("ainda não me ensinou", J.tool_listar_comandos())

    def test_esquecer_o_que_nao_existe(self):
        self.assertIn("Não encontrei", J.tool_esquecer_comando("nada"))

    def test_sem_comandos(self):
        self.assertIn("ainda não me ensinou", J.tool_listar_comandos())

    def test_comando_aprendido_pula_o_atalho_local(self):
        """
        Se o usuário ensinou algo para "que horas são", a ordem dele
        tem de valer mais que o atalho embutido.
        """
        J.tool_ensinar_comando(
            "que horas", "diga a hora e lembre do compromisso das nove"
        )

        fake = FakeSession([FakeResponse(ndjson(text_chunk("São oito.", True)))])

        with mock.patch.object(J, "session", fake):
            J.ask_nebell("que horas são")

        self.assertEqual(len(fake.payloads), 1)
        enviado = [m["content"] for m in fake.payloads[0]["messages"]]
        self.assertTrue(any("compromisso das nove" in c for c in enviado))
        flush_speech()

    def test_comando_aprendido_chega_ao_modelo(self):
        J.tool_ensinar_comando("modo foco", "responda em uma frase só")

        fake = FakeSession([FakeResponse(ndjson(text_chunk("Certo.", True)))])

        with mock.patch.object(J, "session", fake):
            J.ask_nebell("entra em modo foco")

        papeis = [m["role"] for m in fake.payloads[0]["messages"]]
        self.assertIn("system", papeis[1:])
        flush_speech()


# ============================================================
# HISTORICO
# ============================================================

class TestHistorico(NebellTest):
    def test_mantem_o_sistema(self):
        for i in range(60):
            J.history.append({"role": "user", "content": f"p{i}"})
            J.history.append({"role": "assistant", "content": f"r{i}"})

        J.trim_history()
        self.assertEqual(J.history[0]["role"], "system")
        self.assertLessEqual(len(J.history), J.MAX_HISTORY_MESSAGES + 1)

    def test_nao_comeca_em_ferramenta_orfa(self):
        J.history.append({"role": "user", "content": "x"})
        for i in range(40):
            J.history.append({"role": "assistant", "content": "", "tool_calls": [{}]})
            J.history.append({"role": "tool", "tool_name": "t", "content": "r"})

        J.trim_history()
        self.assertEqual(J.history[1]["role"], "user")

    def test_historico_curto_fica_intacto(self):
        J.history.append({"role": "user", "content": "oi"})
        antes = list(J.history)
        J.trim_history()
        self.assertEqual(J.history, antes)


# ============================================================
# LEITURA DO STREAM DO OLLAMA
# ============================================================

class TestStream(NebellTest):
    def test_linhas_completas(self):
        resposta = FakeResponse(ndjson(text_chunk("Oi"), text_chunk(" senhor", True)))
        dados = list(J.iter_stream_json(resposta))
        self.assertEqual(len(dados), 2)
        self.assertEqual(dados[1]["message"]["content"], " senhor")

    def test_json_partido_entre_pacotes(self):
        bruto = b"".join(ndjson(text_chunk("Bom"), text_chunk(" dia", True)))
        pedacos = [bruto[:10], bruto[10:25], bruto[25:]]
        dados = list(J.iter_stream_json(FakeResponse(pedacos)))
        self.assertEqual([d["message"]["content"] for d in dados], ["Bom", " dia"])

    def test_linha_invalida_e_ignorada(self):
        resposta = FakeResponse([b"isso nao e json\n", b'{"done":true}\n'])
        dados = list(J.iter_stream_json(resposta))
        self.assertEqual(dados, [{"done": True}])

    def test_ultima_linha_sem_quebra(self):
        dados = list(J.iter_stream_json(FakeResponse([b'{"done":true}'])))
        self.assertEqual(dados, [{"done": True}])


# ============================================================
# CICLO COMPLETO COM O MODELO
# ============================================================

class TestModelo(NebellTest):
    def test_resposta_simples_e_falada(self):
        fake = FakeSession([
            FakeResponse(ndjson(
                text_chunk("Claro senhor, "),
                text_chunk("são vinte graus."),
                {"done": True},
            ))
        ])

        with mock.patch.object(J, "session", fake):
            J.ask_nebell("me explique o que é um transistor")

        falas = flush_speech()
        self.assertIn("Claro senhor,", falas[0])
        self.assertIn("são vinte graus.", " ".join(falas))
        self.assertEqual(J.history[-1]["role"], "assistant")

    def test_aquecimento_manda_o_prompt_do_sistema(self):
        """
        Mandar a lista vazia carregava o modelo mas não preparava o
        cache de atenção; a primeira pergunta pagava tudo de novo.
        """
        fake = FakeSession([FakeResponse(ndjson(text_chunk("ok", True)))])

        with mock.patch.object(J, "session", fake):
            J.warm_up_model()

        mensagens = fake.payloads[0]["messages"]
        self.assertTrue(mensagens)
        self.assertEqual(mensagens[0]["role"], "system")
        self.assertIn("NEBELL", mensagens[0]["content"])
        self.assertEqual(fake.payloads[0]["options"]["num_predict"], 1)

    def test_opcoes_sao_sempre_as_mesmas(self):
        fake = FakeSession([FakeResponse(ndjson(text_chunk("ok", True)))])

        with mock.patch.object(J, "session", fake):
            J.ask_nebell("oi")
            J.warm_up_model()

        # O aquecimento só difere no num_predict (gera 1 token de
        # propósito); todo o resto tem de ser idêntico, senão o Ollama
        # descarrega e recarrega o modelo na primeira pergunta.
        pergunta = dict(fake.payloads[0]["options"])
        aquecimento = dict(fake.payloads[1]["options"])
        pergunta.pop("num_predict", None)
        aquecimento.pop("num_predict", None)
        self.assertEqual(pergunta, aquecimento)
        self.assertEqual(fake.payloads[0]["model"], fake.payloads[1]["model"])
        self.assertEqual(
            fake.payloads[0]["keep_alive"], fake.payloads[1]["keep_alive"]
        )

    def test_pensamento_nao_e_falado(self):
        fake = FakeSession([
            FakeResponse(ndjson(
                text_chunk("<think>vou calcular</think>"),
                text_chunk("São quatro.", True),
            ))
        ])

        with mock.patch.object(J, "session", fake):
            J.ask_nebell("dois mais dois")

        falado = " ".join(flush_speech())
        self.assertNotIn("calcular", falado)
        self.assertIn("São quatro.", falado)

    def test_ciclo_com_ferramenta(self):
        fake = FakeSession([
            FakeResponse(ndjson(tool_chunk("data_hora", {}))),
            FakeResponse(ndjson(text_chunk("Agora são dez horas.", True))),
        ])

        with mock.patch.object(J, "session", fake):
            J.ask_nebell("me diga o horário completo por favor")

        papeis = [m["role"] for m in J.history]
        self.assertIn("tool", papeis)
        self.assertIn("Agora são dez horas.", " ".join(flush_speech()))
        # A segunda chamada ja leva o resultado da ferramenta no historico.
        self.assertEqual(len(fake.payloads), 2)

    def test_limite_de_rodadas_de_ferramenta(self):
        respostas = [
            FakeResponse(ndjson(tool_chunk("data_hora", {})))
            for _ in range(J.MAX_TOOL_ROUNDS)
        ]
        respostas.append(FakeResponse(ndjson(text_chunk("Pronto.", True))))
        fake = FakeSession(respostas)

        with mock.patch.object(J, "session", fake):
            J.ask_nebell("faça algo repetido sem parar por favor")

        self.assertLessEqual(len(fake.payloads), J.MAX_TOOL_ROUNDS + 1)
        # A ultima rodada vai sem ferramentas, para forcar uma resposta.
        self.assertNotIn("tools", fake.payloads[-1])

    def test_modelo_sem_suporte_a_ferramentas(self):
        fake = FakeSession([
            FakeResponse([], status_code=400, text="model does not support tools"),
            FakeResponse(ndjson(text_chunk("Posso conversar.", True))),
        ])

        with mock.patch.object(J, "session", fake):
            J.ask_nebell("oi")

        self.assertFalse(J.tools_supported)
        self.assertIn("Posso conversar.", " ".join(flush_speech()))

    def test_ollama_fora_do_ar(self):
        fake = mock.Mock()
        fake.post.side_effect = requests.exceptions.ConnectionError()

        with mock.patch.object(J, "session", fake):
            J.ask_nebell("oi")

        self.assertIn("Ollama", " ".join(flush_speech()))

    def test_timeout(self):
        fake = mock.Mock()
        fake.post.side_effect = requests.exceptions.Timeout()

        with mock.patch.object(J, "session", fake):
            J.ask_nebell("oi")

        self.assertIn("demorou", " ".join(flush_speech()))

    def test_resposta_vazia(self):
        fake = FakeSession([FakeResponse(ndjson({"done": True}))])

        with mock.patch.object(J, "session", fake):
            J.ask_nebell("oi")

        self.assertIn("Não consegui gerar", " ".join(flush_speech()))

    def test_pergunta_vazia_nao_chama_o_modelo(self):
        fake = FakeSession()

        with mock.patch.object(J, "session", fake):
            J.ask_nebell("   ")

        self.assertEqual(fake.payloads, [])


# ============================================================
# ATALHOS LOCAIS
# ============================================================

class TestAtalhos(NebellTest):
    def test_hora(self):
        resposta = J.local_fast_answer("Nebell, que horas são?")
        self.assertIsNotNone(resposta)
        self.assertIn("horas", resposta)

    def test_data(self):
        resposta = J.local_fast_answer("que dia é hoje")
        self.assertIn("Hoje é", resposta)

    def test_abrir_programa(self):
        with mock.patch.object(J.subprocess, "Popen"):
            resposta = J.local_fast_answer("abra a calculadora")
        self.assertIn("calculadora", resposta)

    def test_abrir_programa_desconhecido_vai_para_o_modelo(self):
        self.assertIsNone(J.local_fast_answer("abra o photoshop"))

    def test_volume(self):
        with mock.patch.object(J, "press_media_key", return_value=True):
            self.assertIn("aumentado", J.local_fast_answer("aumenta o volume"))
            self.assertIn("reduzido", J.local_fast_answer("abaixa o volume"))

    def test_pergunta_normal_passa_direto(self):
        self.assertIsNone(J.local_fast_answer("me explique o que é um transistor"))

    def test_atalho_nao_chama_o_modelo(self):
        fake = FakeSession()

        with mock.patch.object(J, "session", fake):
            J.ask_nebell("que horas são")

        self.assertEqual(fake.payloads, [])
        self.assertTrue(flush_speech())
        self.assertEqual(J.history[-1]["role"], "assistant")

    def test_desligar_o_atalho(self):
        J.FAST_PATH = False
        try:
            self.assertIsNone(J.local_fast_answer("que horas são"))
        finally:
            J.FAST_PATH = True


# ============================================================
# CONFIRMACAO
# ============================================================

class TestConfirmacao(NebellTest):
    def test_texto_aceita_s(self):
        with mock.patch("builtins.input", return_value="s"):
            self.assertTrue(J.confirm_action("Vou criar um arquivo."))
        flush_speech()

    def test_texto_recusa(self):
        with mock.patch("builtins.input", return_value="n"):
            self.assertFalse(J.confirm_action("Vou criar um arquivo."))
        flush_speech()

    def test_ctrl_c_cancela(self):
        with mock.patch("builtins.input", side_effect=KeyboardInterrupt):
            self.assertFalse(J.confirm_action("Vou criar um arquivo."))
        flush_speech()

    def test_voz_aceita(self):
        J.interaction_mode = "voice"
        try:
            with mock.patch.object(J, "listen", return_value="sim, pode"), \
                 mock.patch.object(J, "microphone_available", return_value=True):
                self.assertTrue(J.confirm_action("Vou executar."))
        finally:
            J.interaction_mode = "text"
        flush_speech()

    def test_voz_recusa(self):
        J.interaction_mode = "voice"
        try:
            with mock.patch.object(J, "listen", return_value="não, cancela"), \
                 mock.patch.object(J, "microphone_available", return_value=True):
                self.assertFalse(J.confirm_action("Vou executar."))
        finally:
            J.interaction_mode = "text"
        flush_speech()

    def test_voz_sem_resposta_cancela(self):
        J.interaction_mode = "voice"
        try:
            with mock.patch.object(J, "listen", return_value=None), \
                 mock.patch.object(J, "microphone_available", return_value=True):
                self.assertFalse(J.confirm_action("Vou executar."))
        finally:
            J.interaction_mode = "text"
        flush_speech()


# ============================================================
# MICROFONE
# ============================================================

class TestSimbolosEEmojis(NebellTest):
    def test_emojis_de_varias_faixas_somem(self):
        # Faces, bandeiras, dingbats, letras cercadas, simbolos de
        # marca e setas: a faixa fixa da versao anterior deixava
        # metade disso passar.
        texto = "Pronto 😀 ✅ 🇧🇷 ™ ℹ ↔ 🆗 ⚙️ 👍🏽 👨‍👩‍👧 senhor"
        limpo = J.clean_for_speech(texto)
        self.assertEqual(limpo, "Pronto senhor")

    def test_nenhum_simbolo_grafico_sobrevive(self):
        import unicodedata as ud

        suspeitos = [
            chr(c) for c in range(0x2000, 0x3000)
            if ud.category(chr(c)) in ("So", "Sk", "Sm")
        ][:400]
        limpo = J.clean_for_speech("teste " + "".join(suspeitos) + " fim")

        for char in limpo:
            self.assertNotIn(
                ud.category(char), ("So", "Sk", "Cf", "Me"), repr(char)
            )

    def test_asteriscos_somem(self):
        self.assertEqual(
            J.clean_for_speech("**Importante**: o *valor* é alto"),
            "Importante: o valor é alto",
        )

    def test_lista_com_asterisco(self):
        limpo = J.clean_for_speech("* primeiro item\n* segundo item")
        self.assertEqual(limpo, "primeiro item segundo item")

    def test_titulos_e_citacoes(self):
        self.assertEqual(
            J.clean_for_speech("### Resumo\n> algo citado"),
            "Resumo algo citado",
        )

    def test_tabela_e_linha_horizontal(self):
        limpo = J.clean_for_speech("| a | b |\n|---|---|\n---\nfim")
        self.assertNotIn("|", limpo)
        self.assertNotIn("-", limpo.replace("fim", ""))

    def test_codigo_entre_crases(self):
        self.assertEqual(
            J.clean_for_speech("rode `pip install ddgs` agora"), "rode agora"
        )

    def test_acentos_sao_preservados(self):
        self.assertEqual(
            J.clean_for_speech("São Paulo, coração, ânsia, até"),
            "São Paulo, coração, ânsia, até",
        )

    def test_acentos_decompostos_sobrevivem(self):
        import unicodedata as ud

        decomposto = ud.normalize("NFD", "São João")
        self.assertEqual(
            ud.normalize("NFC", J.clean_for_speech(decomposto)), "São João"
        )

    def test_simbolos_uteis_viram_palavras(self):
        limpo = J.clean_for_speech("2 + 2 = 4 e 10 × 3")
        self.assertIn("mais", limpo)
        self.assertIn("igual a", limpo)
        self.assertIn("vezes", limpo)

    def test_pontuacao_repetida(self):
        self.assertEqual(J.clean_for_speech("Puxa!!! Sério??"), "Puxa! Sério?")

    def test_hifen_do_portugues_fica(self):
        self.assertIn("segunda-feira", J.clean_for_speech("hoje é segunda-feira"))

    def test_reais_continua_funcionando(self):
        self.assertIn("15,90 reais", J.clean_for_speech("custa R$ 15,90."))


class TestLocalizacao(NebellTest):
    def setUp(self):
        super().setUp()
        J.location_info.clear()
        J.location_fetched_at = 0.0

    def _resposta(self, dados):
        resposta = mock.Mock()
        resposta.json.return_value = dados
        resposta.raise_for_status = mock.Mock()
        return resposta

    def test_detecta_pelo_ip_api(self):
        dados = {
            "status": "success", "city": "Cachoeira", "regionName": "Bahia",
            "country": "Brasil", "lat": -12.6, "lon": -38.9,
            "isp": "Provedor X", "query": "200.1.2.3",
        }
        with mock.patch.object(J.requests, "get", return_value=self._resposta(dados)):
            info = J.detect_location()

        self.assertEqual(info["cidade"], "Cachoeira")
        self.assertEqual(J.describe_location(), "Cachoeira, Bahia, Brasil")

    def test_formato_do_ipinfo(self):
        dados = {
            "city": "Salvador", "region": "Bahia", "country": "BR",
            "loc": "-12.97,-38.50", "ip": "200.9.9.9", "org": "AS123 Net",
        }
        with mock.patch.object(J.requests, "get", return_value=self._resposta(dados)):
            info = J.detect_location()

        self.assertEqual(info["cidade"], "Salvador")
        self.assertAlmostEqual(info["lat"], -12.97)

    def test_cai_para_o_segundo_servico(self):
        bom = self._resposta({"city": "Recife", "region": "PE", "country": "BR"})

        with mock.patch.object(
            J.requests, "get", side_effect=[Exception("fora do ar"), bom]
        ):
            info = J.detect_location()

        self.assertEqual(info["cidade"], "Recife")

    def test_sem_internet_nao_quebra(self):
        # O cache tem de ser limpo: sem isso, a localização descoberta
        # por um teste anterior (ou pela máquina real) mascara o caso.
        J.location_info.clear()
        J.location_fetched_at = 0.0

        with mock.patch.object(
            J.requests, "get", side_effect=Exception("sem rede")
        ):
            self.assertEqual(J.detect_location(), {})
            self.assertIn("Não consegui", J.tool_minha_localizacao())

    def test_usa_o_cache(self):
        dados = {"status": "success", "city": "Feira de Santana", "country": "Brasil"}

        with mock.patch.object(J.requests, "get", return_value=self._resposta(dados)) as get:
            J.detect_location()
            J.detect_location()

        self.assertEqual(get.call_count, 1)

    def test_forcar_atualizacao_ignora_o_cache(self):
        dados = {"status": "success", "city": "Ilhéus", "country": "Brasil"}

        with mock.patch.object(J.requests, "get", return_value=self._resposta(dados)) as get:
            J.detect_location()
            J.detect_location(force=True)

        self.assertEqual(get.call_count, 2)

    def test_entra_no_prompt_do_sistema(self):
        J.location_info.update({"cidade": "Cachoeira", "regiao": "Bahia", "pais": "Brasil"})
        J.refresh_system_prompt()
        self.assertIn("Cachoeira, Bahia, Brasil", J.history[0]["content"])

    def test_atalho_responde_sem_o_modelo(self):
        J.location_info.update({"cidade": "Cachoeira", "pais": "Brasil"})
        J.location_fetched_at = time.time()
        resposta = J.local_fast_answer("Nebell, onde eu estou?")
        self.assertIn("Cachoeira", resposta)


class TestLocalizacaoNaHora(NebellTest):
    """O caso que falhou de verdade: perguntar do clima logo na abertura."""

    def setUp(self):
        super().setUp()
        J.location_info.clear()
        J.location_fetched_at = 0.0
        J.location_errors.clear()

    def _resposta(self, dados):
        resposta = mock.Mock()
        resposta.json.return_value = dados
        resposta.raise_for_status = mock.Mock()
        return resposta

    def test_pergunta_de_clima_busca_a_localizacao_antes(self):
        dados = {"success": True, "city": "Cachoeira", "region": "Bahia",
                 "country": "Brasil", "latitude": -12.6, "longitude": -38.9}

        fake = FakeSession([FakeResponse(ndjson(text_chunk("Vou verificar.", True)))])

        with mock.patch.object(J.requests, "get", return_value=self._resposta(dados)), \
             mock.patch.object(J, "session", fake):
            J.ask_nebell("tem alguma farmácia perto de mim agora")

        enviado = fake.payloads[0]["messages"][0]["content"]
        self.assertIn("Cachoeira", enviado)
        flush_speech()

    def test_pergunta_comum_nao_dispara_busca(self):
        fake = FakeSession([FakeResponse(ndjson(text_chunk("Claro.", True)))])

        with mock.patch.object(J.requests, "get") as get, \
             mock.patch.object(J, "session", fake):
            J.ask_nebell("me explique o que é um capacitor")

        get.assert_not_called()
        flush_speech()

    def test_assuntos_que_dependem_do_lugar(self):
        for frase in ["como está o clima", "vai chover hoje", "qual a temperatura",
                      "tem farmácia perto de mim", "como está o trânsito"]:
            self.assertTrue(
                J.LOCATION_DEPENDENT_RE.search(J.normalize(frase)), frase
            )

    def test_assuntos_que_nao_dependem(self):
        for frase in ["quem descobriu o brasil", "crie um arquivo de notas"]:
            self.assertFalse(
                J.LOCATION_DEPENDENT_RE.search(J.normalize(frase)), frase
            )

    def test_nao_busca_duas_vezes(self):
        J.location_info.update({"cidade": "Salvador"})
        J.location_fetched_at = time.time()

        with mock.patch.object(J.requests, "get") as get:
            J.ensure_location("como está o clima")

        get.assert_not_called()

    def test_formato_do_ipwho(self):
        dados = {"success": True, "city": "Cachoeira", "region": "Bahia",
                 "country": "Brasil", "latitude": -12.6, "longitude": -38.9,
                 "ip": "200.1.1.1", "connection": {"isp": "Provedor Y"}}

        with mock.patch.object(J.requests, "get", return_value=self._resposta(dados)):
            info = J.detect_location()

        self.assertEqual(info["cidade"], "Cachoeira")
        self.assertEqual(info["provedor"], "Provedor Y")
        self.assertAlmostEqual(info["lat"], -12.6)

    def test_formato_do_ipapi_co(self):
        dados = {"city": "Recife", "region": "Pernambuco",
                 "country_name": "Brasil", "latitude": -8.0, "longitude": -34.9}

        with mock.patch.object(J.requests, "get", return_value=self._resposta(dados)):
            info = J.detect_location()

        self.assertEqual(info["pais"], "Brasil")

    def test_servico_que_recusa_e_pulado(self):
        ruim = self._resposta({"success": False, "message": "quota"})
        bom = self._resposta({"city": "Natal", "country": "Brasil"})

        with mock.patch.object(J.requests, "get", side_effect=[ruim, bom]):
            self.assertEqual(J.detect_location()["cidade"], "Natal")

    def test_cidade_manual_quando_tudo_falha(self):
        J.LOCATION_FALLBACK = "Cachoeira, Bahia, Brasil"
        try:
            with mock.patch.object(J.requests, "get", side_effect=Exception("sem rede")):
                info = J.detect_location()
        finally:
            J.LOCATION_FALLBACK = ""

        self.assertEqual(info["cidade"], "Cachoeira")
        self.assertEqual(J.describe_location(), "Cachoeira, Bahia, Brasil")

    def test_erros_ficam_registrados(self):
        with mock.patch.object(J.requests, "get", side_effect=Exception("timeout")):
            J.detect_location()

        self.assertTrue(J.location_errors)
        self.assertIn("timeout", J.location_errors[0])

    def test_prompt_avisa_quando_nao_sabe(self):
        J.refresh_system_prompt()
        self.assertIn("minha_localizacao", J.history[0]["content"])


class TestRede(NebellTest):
    def test_info_rede(self):
        J.location_info.update({"ip": "200.1.2.3", "provedor": "Provedor X"})
        J.location_fetched_at = time.time()

        with mock.patch.object(J, "local_ip_address", return_value="192.168.0.10"), \
             mock.patch.object(J, "wifi_name", return_value="MinhaRede"), \
             mock.patch.object(J.requests, "get", return_value=mock.Mock()):
            saida = J.tool_info_rede()

        self.assertIn("192.168.0.10", saida)
        self.assertIn("MinhaRede", saida)
        self.assertIn("200.1.2.3", saida)
        self.assertIn("ativa", saida)

    def test_info_rede_sem_internet(self):
        with mock.patch.object(J, "local_ip_address", return_value="192.168.0.10"), \
             mock.patch.object(J, "wifi_name", return_value=None), \
             mock.patch.object(J.requests, "get", side_effect=Exception("off")):
            self.assertIn("sem resposta", J.tool_info_rede())

    def test_testar_rede(self):
        saida = "4 pacotes transmitidos, 0% de perda\nMédia = 23ms"
        with mock.patch.object(
            J.subprocess, "run", return_value=mock.Mock(stdout=saida)
        ):
            resultado = J.tool_testar_rede("google.com")

        self.assertIn("23", resultado)
        self.assertIn("0 por cento", resultado)

    def test_destino_e_higienizado(self):
        with mock.patch.object(
            J.subprocess, "run", return_value=mock.Mock(stdout="")
        ) as run:
            J.tool_testar_rede("google.com; rm -rf /")

        comando = run.call_args[0][0]
        self.assertNotIn(";", " ".join(comando))


class TestAcessoAoPC(NebellTest):
    def test_disco_inteiro_liberado(self):
        ok, _ = J.path_is_allowed(Path("/var/log/app.log"))
        self.assertTrue(ok)

    def test_segredos_continuam_protegidos(self):
        ok, motivo = J.path_is_allowed(Path.home() / ".ssh" / "id_rsa")
        self.assertFalse(ok)
        self.assertIn("protegid", motivo)

    def test_pasta_do_sistema_protegida(self):
        ok, _ = J.path_is_allowed(caminho_de_sistema())
        self.assertFalse(ok)

    def test_pode_desligar_a_protecao(self):
        J.PROTECT_SECRETS = False
        try:
            ok, _ = J.path_is_allowed(Path.home() / ".ssh" / "id_rsa")
            self.assertTrue(ok)
        finally:
            J.PROTECT_SECRETS = True

    def test_tamanho_legivel(self):
        self.assertEqual(J.human_size(512), "512 bytes")
        self.assertEqual(J.human_size(2048), "2.0 KB")
        self.assertEqual(J.human_size(5 * 1024 ** 3), "5.0 GB")

    def test_info_sistema(self):
        saida = J.tool_info_sistema()
        self.assertIn("Sistema:", saida)
        self.assertIn("Disco", saida)

    def test_listar_processos(self):
        saida = J.tool_listar_processos(limite=5)
        self.assertTrue(saida.startswith("Processos:"))
        self.assertLessEqual(len(saida.splitlines()), 6)

    def test_listar_processos_com_filtro_sem_resultado(self):
        self.assertIn("Nenhum processo", J.tool_listar_processos("zzz_inexistente"))

    def test_buscar_arquivos(self):
        (J.WORKSPACE_DIR / "relatorio_final.txt").write_text("x", encoding="utf-8")
        (J.WORKSPACE_DIR / "sub").mkdir(exist_ok=True)
        (J.WORKSPACE_DIR / "sub" / "relatorio_antigo.txt").write_text("y", encoding="utf-8")

        saida = J.tool_buscar_arquivos("relatorio", J.WORKSPACE_DIR)
        self.assertIn("relatorio_final.txt", saida)
        self.assertIn("relatorio_antigo.txt", saida)

    def test_buscar_sem_resultado(self):
        self.assertIn("Nada encontrado", J.tool_buscar_arquivos("zzz", J.WORKSPACE_DIR))

    def test_buscar_sem_padrao(self):
        self.assertIn("Informe", J.tool_buscar_arquivos("  "))

    def test_analisar_pasta(self):
        pasta = J.WORKSPACE_DIR / "analise"
        pasta.mkdir(exist_ok=True)
        (pasta / "a.txt").write_text("a" * 100, encoding="utf-8")
        (pasta / "b.md").write_text("b" * 50, encoding="utf-8")

        saida = J.tool_analisar_pasta(pasta)
        self.assertIn("2 arquivos", saida)
        self.assertIn(".txt", saida)
        self.assertIn("150 bytes", saida)

    def test_editar_arquivo(self):
        alvo = J.WORKSPACE_DIR / "config.txt"
        alvo.write_text("porta=8080\nhost=local", encoding="utf-8")

        with mock.patch.object(J, "confirm_action", return_value=True):
            resultado = J.tool_editar_arquivo(alvo, "8080", "9090")

        self.assertIn("1 trecho", resultado)
        self.assertIn("9090", alvo.read_text(encoding="utf-8"))
        self.assertTrue(alvo.with_name("config.txt.bak").exists())

    def test_editar_sem_encontrar(self):
        alvo = J.WORKSPACE_DIR / "vazio.txt"
        alvo.write_text("nada aqui", encoding="utf-8")
        self.assertIn("Não encontrei", J.tool_editar_arquivo(alvo, "xyz", "abc"))

    def test_editar_negado(self):
        alvo = J.WORKSPACE_DIR / "negar.txt"
        alvo.write_text("original", encoding="utf-8")

        with mock.patch.object(J, "confirm_action", return_value=False):
            J.tool_editar_arquivo(alvo, "original", "trocado")

        self.assertEqual(alvo.read_text(encoding="utf-8"), "original")

    def test_copiar(self):
        origem = J.WORKSPACE_DIR / "origem.txt"
        origem.write_text("dados", encoding="utf-8")

        with mock.patch.object(J, "confirm_action", return_value=True):
            J.tool_copiar_arquivo(origem, J.WORKSPACE_DIR / "copia.txt")

        self.assertEqual(
            (J.WORKSPACE_DIR / "copia.txt").read_text(encoding="utf-8"), "dados"
        )
        self.assertTrue(origem.exists())

    def test_mover(self):
        origem = J.WORKSPACE_DIR / "mover.txt"
        origem.write_text("dados", encoding="utf-8")

        with mock.patch.object(J, "confirm_action", return_value=True):
            J.tool_mover_arquivo(origem, J.WORKSPACE_DIR / "movido.txt")

        self.assertFalse(origem.exists())
        self.assertTrue((J.WORKSPACE_DIR / "movido.txt").exists())

    def test_mover_para_pasta_mantem_o_nome(self):
        origem = J.WORKSPACE_DIR / "nota.txt"
        origem.write_text("x", encoding="utf-8")
        destino = J.WORKSPACE_DIR / "guardado"
        destino.mkdir(exist_ok=True)

        with mock.patch.object(J, "confirm_action", return_value=True):
            J.tool_mover_arquivo(origem, destino)

        self.assertTrue((destino / "nota.txt").exists())

    def test_renomear(self):
        alvo = J.WORKSPACE_DIR / "antigo.txt"
        alvo.write_text("x", encoding="utf-8")

        with mock.patch.object(J, "confirm_action", return_value=True):
            J.tool_renomear_arquivo(alvo, "novo.txt")

        self.assertTrue((J.WORKSPACE_DIR / "novo.txt").exists())

    def test_renomear_para_nome_existente(self):
        a = J.WORKSPACE_DIR / "um.txt"
        b = J.WORKSPACE_DIR / "dois.txt"
        a.write_text("1", encoding="utf-8")
        b.write_text("2", encoding="utf-8")
        self.assertIn("Já existe", J.tool_renomear_arquivo(a, "dois.txt"))

    def test_renomear_nao_aceita_caminho(self):
        alvo = J.WORKSPACE_DIR / "seguro.txt"
        alvo.write_text("x", encoding="utf-8")

        with mock.patch.object(J, "confirm_action", return_value=True):
            J.tool_renomear_arquivo(alvo, "../fora.txt")

        self.assertFalse((J.WORKSPACE_DIR.parent / "fora.txt").exists())

    def test_apagar_vai_para_a_lixeira(self):
        alvo = J.WORKSPACE_DIR / "descartar.txt"
        alvo.write_text("x", encoding="utf-8")

        with mock.patch.object(J, "confirm_action", return_value=True):
            resultado = J.tool_apagar_arquivo(alvo)

        self.assertFalse(alvo.exists())
        self.assertIn("ixeira", resultado)

    def test_apagar_negado(self):
        alvo = J.WORKSPACE_DIR / "manter.txt"
        alvo.write_text("x", encoding="utf-8")

        with mock.patch.object(J, "confirm_action", return_value=False):
            J.tool_apagar_arquivo(alvo)

        self.assertTrue(alvo.exists())

    def test_apagar_segredo_e_recusado(self):
        self.assertIn(
            "protegid", J.tool_apagar_arquivo(Path.home() / ".ssh" / "id_rsa")
        )


class FakeWinsound:
    """
    winsound do Windows, com as mesmas restrições do de verdade.

    A principal: SND_MEMORY junto com SND_ASYNC é recusado. Foi esse
    detalhe que derrubou o áudio inteiro, e é por isso que ele está
    reproduzido aqui.
    """

    SND_MEMORY = 4
    SND_ASYNC = 1
    SND_FILENAME = 0x20000
    SND_PURGE = 0x40

    def __init__(self):
        self.tocados = []
        self.purgado = 0

    def PlaySound(self, som, flags):
        if flags & self.SND_PURGE:
            self.purgado += 1
            return

        if (flags & self.SND_MEMORY) and (flags & self.SND_ASYNC):
            raise RuntimeError("Cannot play asynchronously from memory")

        if flags & self.SND_FILENAME:
            if not Path(som).is_file():
                raise RuntimeError("arquivo de som não encontrado")
            self.tocados.append(("arquivo", som))
            return

        self.tocados.append(("memoria", len(som)))

    def Beep(self, frequencia, duracao):
        pass


class FakeStream:
    def __init__(self):
        self.escrito = bytearray()
        self.parado = 0

    def write(self, dados):
        self.escrito.extend(dados)

    def stop_stream(self):
        self.parado += 1

    def start_stream(self):
        pass

    def close(self):
        pass


class FakePyAudioModule(types.ModuleType):
    def __init__(self):
        super().__init__("pyaudio")
        self.streams = []

        modulo = self

        class PyAudio:
            def get_device_count(self):
                return 2

            def get_format_from_width(self, largura):
                return largura

            def open(self, **kwargs):
                stream = FakeStream()
                modulo.streams.append(stream)
                return stream

            def terminate(self):
                pass

        self.PyAudio = PyAudio


class TestReproducaoDeAudio(NebellTest):
    def setUp(self):
        super().setUp()
        J.audio_backend = "nenhum"
        J._output_stream = None
        J._output_format = None
        J._pyaudio = None
        J.TEMP_AUDIO_DIR = TMP / "audio_temp"

    def tearDown(self):
        J.audio_backend = "nenhum"
        J._output_stream = None
        J._pyaudio = None

    def test_winsound_recusa_memoria_assincrona(self):
        """O bug original: tocar da memória em modo assíncrono é proibido."""
        falso = FakeWinsound()
        with self.assertRaises(RuntimeError):
            falso.PlaySound(b"dados", falso.SND_MEMORY | falso.SND_ASYNC)

    def test_backend_de_arquivo_nao_usa_memoria_assincrona(self):
        falso = FakeWinsound()
        dados, segundos = J.synthesize_to_bytes("teste")

        with mock.patch.object(J, "winsound", falso):
            J.audio_backend = "winsound_file"
            J.play_audio(dados, segundos)

        self.assertEqual(len(falso.tocados), 1)
        self.assertEqual(falso.tocados[0][0], "arquivo")

    def test_arquivo_temporario_e_apagado(self):
        falso = FakeWinsound()
        dados, segundos = J.synthesize_to_bytes("teste")

        with mock.patch.object(J, "winsound", falso):
            J.audio_backend = "winsound_file"
            J.play_audio(dados, segundos)

        sobras = list(J.TEMP_AUDIO_DIR.glob("*.wav"))
        self.assertEqual(sobras, [])

    def test_pyaudio_toca_todos_os_quadros(self):
        modulo = FakePyAudioModule()
        dados, segundos = J.synthesize_to_bytes("teste")
        canais, largura, taxa, quadros = J.wav_parts(dados)

        with mock.patch.dict(sys.modules, {"pyaudio": modulo}):
            J.audio_backend = "pyaudio"
            J.play_audio(dados, segundos)

        self.assertEqual(bytes(modulo.streams[0].escrito), quadros)

    def test_pyaudio_para_no_meio(self):
        modulo = FakePyAudioModule()
        dados, _ = J.synthesize_to_bytes("teste")
        _, _, _, quadros = J.wav_parts(dados)

        J.stop_speaking_event.set()
        try:
            with mock.patch.dict(sys.modules, {"pyaudio": modulo}):
                J.audio_backend = "pyaudio"
                J.play_audio(dados, 1.0)
        finally:
            J.stop_speaking_event.clear()

        self.assertEqual(len(modulo.streams[0].escrito), 0)
        self.assertEqual(modulo.streams[0].parado, 1)

    def test_stream_e_reaproveitado(self):
        modulo = FakePyAudioModule()
        dados, segundos = J.synthesize_to_bytes("teste")

        with mock.patch.dict(sys.modules, {"pyaudio": modulo}):
            J.audio_backend = "pyaudio"
            J.play_audio(dados, segundos)
            J.play_audio(dados, segundos)

        self.assertEqual(len(modulo.streams), 1)

    def test_cai_para_o_winsound_se_o_pyaudio_falhar(self):
        falso = FakeWinsound()
        dados, segundos = J.synthesize_to_bytes("teste")

        with mock.patch.object(J, "play_with_pyaudio", side_effect=Exception("sem placa")), \
             mock.patch.object(J, "winsound", falso):
            J.audio_backend = "pyaudio"
            J.play_audio(dados, segundos)

        self.assertEqual(J.audio_backend, "winsound_file")
        self.assertEqual(falso.tocados[0][0], "arquivo")

    def test_escolha_automatica_prefere_pyaudio(self):
        modulo = FakePyAudioModule()

        with mock.patch.dict(sys.modules, {"pyaudio": modulo}):
            J._pyaudio = None
            self.assertEqual(J.detect_audio_backend(), "pyaudio")

    def test_sem_pyaudio_usa_winsound_por_arquivo(self):
        falso = FakeWinsound()

        with mock.patch.dict(sys.modules, {"pyaudio": None}), \
             mock.patch.object(J, "winsound", falso):
            J._pyaudio = None
            self.assertEqual(J.detect_audio_backend(), "winsound_file")

    def test_sem_audio_nenhum(self):
        with mock.patch.dict(sys.modules, {"pyaudio": None}), \
             mock.patch.object(J, "winsound", None):
            J._pyaudio = None
            self.assertEqual(J.detect_audio_backend(), "nenhum")

    def test_backend_forcado_na_configuracao(self):
        J.AUDIO_BACKEND = "winsound_memory"
        try:
            self.assertEqual(J.detect_audio_backend(), "winsound_memory")
        finally:
            J.AUDIO_BACKEND = "auto"

    def test_wav_parts(self):
        dados, _ = J.synthesize_to_bytes("teste")
        canais, largura, taxa, quadros = J.wav_parts(dados)
        self.assertEqual((canais, largura, taxa), (1, 2, 22050))
        self.assertEqual(len(quadros), 220 * 2)

    def test_pais_em_portugues(self):
        J.location_info.update({"cidade": "Cachoeira", "regiao": "Bahia",
                                "pais": "Brazil"})
        self.assertEqual(J.describe_location(), "Cachoeira, Bahia, Brasil")
        J.location_info.clear()


class TestInterrupcao(NebellTest):
    def setUp(self):
        super().setUp()
        J.cancel_event.clear()
        J.busy_event.clear()

    def test_cancelar_so_vale_quando_ocupado(self):
        self.assertFalse(J.cancel_current())
        J.busy_event.set()
        self.assertTrue(J.cancel_current())
        self.assertTrue(J.cancel_event.is_set())
        J.busy_event.clear()
        J.cancel_event.clear()

    def test_nao_cancela_duas_vezes(self):
        J.busy_event.set()
        J.cancel_current()
        self.assertFalse(J.cancel_current())
        J.busy_event.clear()
        J.cancel_event.clear()

    def test_geracao_para_no_meio(self):
        """A tecla chega enquanto o modelo ainda está mandando texto."""
        pedacos = ndjson(
            text_chunk("Primeira parte da resposta. "),
            text_chunk("Segunda parte que não deve ser falada. "),
            text_chunk("Terceira parte.", True),
        )

        class RespostaQueInterrompe(FakeResponse):
            def iter_content(self, chunk_size=None):
                for i, pedaco in enumerate(self._chunks):
                    if i == 1:
                        J.cancel_current("teste")
                    yield pedaco

        fake = FakeSession([RespostaQueInterrompe(pedacos)])

        with mock.patch.object(J, "session", fake):
            J.ask_nebell("me explique uma coisa longa")

        falado = " ".join(flush_speech())
        self.assertNotIn("Terceira parte", falado)
        self.assertFalse(J.busy_event.is_set())

    def test_historico_fica_coerente_apos_interromper(self):
        pedacos = ndjson(text_chunk("Começando a resp"), text_chunk("osta.", True))

        class RespostaQueInterrompe(FakeResponse):
            def iter_content(self, chunk_size=None):
                J.cancel_current("teste")
                for pedaco in self._chunks:
                    yield pedaco

        fake = FakeSession([RespostaQueInterrompe(pedacos)])

        with mock.patch.object(J, "session", fake):
            J.ask_nebell("pergunta qualquer")

        ultima = J.history[-1]
        self.assertEqual(ultima["role"], "assistant")
        self.assertIn("interrompido", ultima["content"])
        # Sem chamada de ferramenta pendurada, senão o Ollama recusa a próxima.
        self.assertNotIn("tool_calls", ultima)
        flush_speech()

    def test_ferramentas_nao_rodam_apos_interromper(self):
        class RespostaQueInterrompe(FakeResponse):
            def iter_content(self, chunk_size=None):
                J.cancel_current("teste")
                for pedaco in self._chunks:
                    yield pedaco

        fake = FakeSession([
            RespostaQueInterrompe(ndjson(tool_chunk("apagar_arquivo", {"caminho": "x"})))
        ])

        with mock.patch.object(J, "session", fake), \
             mock.patch.object(J, "run_tool") as run:
            J.ask_nebell("apague uma coisa qualquer")

        run.assert_not_called()
        flush_speech()

    def test_a_fala_na_fila_e_descartada(self):
        J.busy_event.set()
        for _ in range(4):
            J.speech_queue.put("frase que não deve ser falada")

        J.cancel_current("teste")
        J.wait_for_speech()

        self.assertTrue(J.speech_queue.empty())
        self.assertTrue(J.audio_queue.empty())
        J.busy_event.clear()
        J.cancel_event.clear()

    def test_ctrl_c_nao_derruba_o_programa(self):
        fake = mock.Mock()
        fake.post.side_effect = KeyboardInterrupt()

        with mock.patch.object(J, "session", fake):
            J.ask_nebell("pergunta")        # não pode levantar

        self.assertFalse(J.busy_event.is_set())
        flush_speech()

    def test_pergunta_seguinte_funciona_normalmente(self):
        J.busy_event.set()
        J.cancel_current("teste")

        fake = FakeSession([FakeResponse(ndjson(text_chunk("Tudo certo.", True)))])

        with mock.patch.object(J, "session", fake):
            J.ask_nebell("e agora?")

        self.assertIn("Tudo certo.", " ".join(flush_speech()))
        self.assertFalse(J.cancel_event.is_set())

    def test_palavras_de_parada(self):
        for frase in ["pare", "pare nebell", "chega", "cancela isso"]:
            self.assertTrue(J.STOP_WORDS_RE.search(J.normalize(frase)), frase)

    def test_frase_comum_nao_e_parada(self):
        self.assertIsNone(J.STOP_WORDS_RE.search(J.normalize("qual a capital do para")))


class TestConfiguracaoDaVoz(NebellTest):
    def test_usa_synthesis_config_quando_existe(self):
        class FalsaConfig:
            def __init__(self, length_scale=None, noise_scale=None, noise_w_scale=None):
                self.length_scale = length_scale
                self.noise_scale = noise_scale
                self.noise_w_scale = noise_w_scale

        with mock.patch.object(J, "SynthesisConfig", FalsaConfig):
            config = J.build_synthesis_config()

        self.assertEqual(config.length_scale, J.VOICE_LENGTH_SCALE)
        self.assertEqual(config.noise_w_scale, J.VOICE_NOISE_W_SCALE)

    def test_piper_antigo_cai_para_o_voice_config(self):
        J.voice.config.length_scale = 0.0

        with mock.patch.object(J, "SynthesisConfig", None):
            self.assertIsNone(J.build_synthesis_config())

        self.assertEqual(J.voice.config.length_scale, J.VOICE_LENGTH_SCALE)

    def test_config_e_passada_na_sintese(self):
        marcador = object()
        recebido = {}

        def espiao(text, wav_file, syn_config=None):
            recebido["syn_config"] = syn_config
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            wav_file.writeframes(b"\x00\x00" * 10)

        J.synthesis_config = marcador
        try:
            with mock.patch.object(J.voice, "synthesize_wav", espiao):
                J.synthesize_to_bytes("teste")
        finally:
            J.synthesis_config = None

        self.assertIs(recebido["syn_config"], marcador)


class TestTrabalhadorDaHud(NebellTest):
    """
    O pywebview chama o trabalhador passando a janela. Sem o parâmetro,
    a thread morria na hora e a HUD abria inerte: sem despachante, sem
    escuta, sem painel.
    """

    def test_trabalhador_aceita_a_janela(self):
        import inspect

        fonte = Path(J.__file__).read_text(encoding="utf-8")
        inicio = fonte.index("def trabalhador(")
        assinatura = fonte[inicio:fonte.index(")", inicio) + 1]

        # Tem de aceitar pelo menos um argumento posicional.
        self.assertNotEqual(assinatura, "def trabalhador()")
        self.assertIn("janela", assinatura)

    def test_trabalhador_roda_com_a_janela(self):
        """Chama como o pywebview chama: func(window)."""
        capturado = {}

        falso_hud = mock.Mock()
        falso_hud.active = True

        def guardar(worker):
            capturado["worker"] = worker
            return True

        falso_hud.create.return_value = True
        falso_hud.run.side_effect = guardar

        with mock.patch.object(J, "nebell_hud") as modulo, \
             mock.patch.object(J, "dispatcher_loop", lambda: None), \
             mock.patch.object(J, "atualizar_estatisticas", lambda: None), \
             mock.patch.object(J, "microphone_available", return_value=False):
            modulo.HudBridge.return_value = falso_hud
            J.run_hud_mode()

        worker = capturado.get("worker")
        self.assertIsNotNone(worker)

        # O pywebview passa a janela; não pode levantar TypeError.
        worker(object())
        flush_speech()
        J.hud = None

    def test_falha_no_trabalhador_e_relatada(self):
        falso_hud = mock.Mock()
        falso_hud.active = True
        falso_hud.create.return_value = True
        capturado = {}
        falso_hud.run.side_effect = lambda w: capturado.update(worker=w)

        with mock.patch.object(J, "nebell_hud") as modulo, \
             mock.patch.object(J, "dispatcher_loop",
                               side_effect=Exception("falhou")), \
             mock.patch.object(J, "microphone_available", return_value=False):
            modulo.HudBridge.return_value = falso_hud
            J.run_hud_mode()
            # Não pode propagar a exceção para a thread.
            capturado["worker"](None)

        flush_speech()
        J.hud = None


class TestWhisperCaiParaCpu(NebellTest):
    """
    O ctranslate2 só carrega as bibliotecas CUDA na primeira
    transcrição. Com o aquecimento fora da tentativa, o erro de
    cublas64_12.dll escapava e ele ia direto para o Google, em vez de
    usar o processador.
    """

    def preparar(self, falhar_em_cuda_no_aquecimento=True):
        import types

        tentativas = []

        class FalsoModelo:
            def __init__(self, nome, device=None, compute_type=None,
                         download_root=None):
                self.device = device
                tentativas.append((device, compute_type))

            def transcribe(self, *a, **k):
                if self.device == "cuda" and falhar_em_cuda_no_aquecimento:
                    raise RuntimeError(
                        "Library cublas64_12.dll is not found or cannot be loaded"
                    )
                return iter([]), None

            def __repr__(self):
                return f"<FalsoModelo {self.device}>"

        modulo = types.ModuleType("faster_whisper")
        modulo.WhisperModel = FalsoModelo

        ct = types.ModuleType("ctranslate2")
        ct.get_cuda_device_count = lambda: 1

        return modulo, ct, tentativas

    def test_erro_no_aquecimento_cai_para_cpu(self):
        modulo, ct, tentativas = self.preparar()

        J.whisper_model = None

        try:
            with mock.patch.dict(sys.modules,
                                 {"faster_whisper": modulo, "ctranslate2": ct}), \
                 mock.patch.object(J, "WHISPER_DEVICE", "auto"), \
                 mock.patch.object(J, "WHISPER_COMPUTE", "auto"):
                J.load_whisper()

                self.assertEqual(tentativas[0][0], "cuda")
                self.assertEqual(tentativas[1], ("cpu", "int8"))
                self.assertIsNotNone(J.whisper_model)
                self.assertEqual(J.WHISPER_BEAM_SIZE, J.WHISPER_BEAM_CPU)
        finally:
            J.whisper_model = None

    def test_gpu_boa_fica_na_gpu(self):
        modulo, ct, tentativas = self.preparar(
            falhar_em_cuda_no_aquecimento=False
        )

        J.whisper_model = None

        try:
            with mock.patch.dict(sys.modules,
                                 {"faster_whisper": modulo, "ctranslate2": ct}), \
                 mock.patch.object(J, "WHISPER_DEVICE", "auto"), \
                 mock.patch.object(J, "WHISPER_COMPUTE", "auto"):
                J.load_whisper()

                self.assertEqual(len(tentativas), 1)
                self.assertEqual(J.WHISPER_BEAM_SIZE, J.WHISPER_BEAM_GPU)
                self.assertIsNotNone(J.whisper_model)
        finally:
            J.whisper_model = None

    def test_cpu_que_falha_nao_entra_em_laco(self):
        import types

        class SempreFalha:
            def __init__(self, *a, **k):
                raise RuntimeError("sem biblioteca nenhuma")

        modulo = types.ModuleType("faster_whisper")
        modulo.WhisperModel = SempreFalha

        ct = types.ModuleType("ctranslate2")
        ct.get_cuda_device_count = lambda: 0

        J.whisper_model = None

        with mock.patch.dict(sys.modules,
                             {"faster_whisper": modulo, "ctranslate2": ct}), \
             mock.patch.object(J, "WHISPER_DEVICE", "auto"):
            J.load_whisper()          # não deve levantar
            self.assertIsNone(J.whisper_model)


class TestSelecaoDeFerramentas(NebellTest):
    """
    Mandar as 44 ferramentas em cada pergunta consumia ~3700 tokens —
    mais que a janela de contexto inteira de 4096. O Ollama cortava a
    conversa, e era por isso que ele não lembrava da mensagem anterior.
    """

    def test_cabe_na_janela_de_contexto(self):
        import json

        sistema = len(J.build_system_prompt())
        esquemas = len(json.dumps(
            J.selecionar_ferramentas("como está o clima"), ensure_ascii=False
        ))
        tokens = (sistema + esquemas) // 4

        # Tem de sobrar a maior parte da janela para a conversa.
        self.assertLess(tokens, J.NUM_CTX // 3)

    def test_todas_as_ferramentas_mandadas_eram_demais(self):
        import json

        todas = len(json.dumps(J.TOOL_SCHEMAS, ensure_ascii=False))
        poucas = len(json.dumps(
            J.selecionar_ferramentas("abre o brave"), ensure_ascii=False
        ))
        self.assertLess(poucas, todas // 3)

    def test_respeita_o_limite(self):
        pedido = (
            "abre o brave e pesquisa o clima e toca música e vê o volume "
            "e lista os processos e o projeto e a rede e o microfone"
        )
        self.assertLessEqual(
            len(J.selecionar_ferramentas(pedido)), J.MAX_TOOLS_POR_PEDIDO
        )

    def test_basicas_vao_sempre(self):
        nomes = [
            e["function"]["name"]
            for e in J.selecionar_ferramentas("oi, tudo bem?")
        ]
        for basica in J.TOOL_SEMPRE:
            self.assertIn(basica, nomes)

    def test_pedido_de_clima_leva_a_pesquisa(self):
        nomes = [
            e["function"]["name"]
            for e in J.selecionar_ferramentas("como está o clima agora")
        ]
        self.assertIn("pesquisar_web", nomes)
        self.assertIn("minha_localizacao", nomes)

    def test_pedido_de_abrir_leva_as_de_abrir(self):
        nomes = [
            e["function"]["name"]
            for e in J.selecionar_ferramentas("abre o brave")
        ]
        self.assertIn("abrir_programa", nomes)

    def test_pedido_de_lixeira_leva_apagar_e_comando(self):
        nomes = [
            e["function"]["name"]
            for e in J.selecionar_ferramentas("limpe minha lixeira")
        ]
        self.assertTrue(
            "apagar_arquivo" in nomes or "executar_comando" in nomes
        )

    def test_toda_ferramenta_tem_como_ser_escolhida(self):
        for nome in J.TOOL_FUNCTIONS:
            self.assertTrue(
                nome in J.TOOL_SEMPRE or nome in J.TOOL_GATILHOS,
                f"{nome} não tem gatilho e nunca seria oferecida",
            )

    def test_extras_entram_na_lista(self):
        nomes = [
            e["function"]["name"]
            for e in J.selecionar_ferramentas("oi", extras=["bluetooth"])
        ]
        self.assertIn("bluetooth", nomes)

    def test_o_pedido_manda_as_ferramentas_certas_ao_modelo(self):
        fake = FakeSession([FakeResponse(ndjson(text_chunk("Já vejo.", True)))])

        with mock.patch.object(J, "session", fake):
            J.ask_nebell("abre o brave")

        enviadas = [
            f["function"]["name"] for f in fake.payloads[0]["tools"]
        ]
        self.assertIn("abrir_programa", enviadas)
        self.assertLessEqual(len(enviadas), J.MAX_TOOLS_POR_PEDIDO)
        flush_speech()


class TestApelidosDeArgumento(NebellTest):
    """
    O modelo chamava pesquisar_web(query=...) em vez de consulta, a
    ferramenta recusava, e ele dizia ao usuário que não conseguia
    pesquisar. Era por isso que a internet "não funcionava".
    """

    def test_query_vira_consulta(self):
        self.assertEqual(
            J.ajustar_argumentos("pesquisar_web", {"query": "clima"}),
            {"consulta": "clima"},
        )

    def test_busca_vira_consulta(self):
        self.assertEqual(
            J.ajustar_argumentos("pesquisar_web", {"busca": "dólar hoje"}),
            {"consulta": "dólar hoje"},
        )

    def test_nome_desconhecido_com_um_obrigatorio(self):
        self.assertEqual(
            J.ajustar_argumentos("pesquisar_web", {"xpto": "notícias"}),
            {"consulta": "notícias"},
        )

    def test_nome_certo_e_preservado(self):
        self.assertEqual(
            J.ajustar_argumentos("pesquisar_web", {"consulta": "a"}),
            {"consulta": "a"},
        )

    def test_path_vira_caminho(self):
        self.assertEqual(
            J.ajustar_argumentos("ler_arquivo", {"path": "C:/x.txt"}),
            {"caminho": "C:/x.txt"},
        )

    def test_ferramenta_de_dois_argumentos(self):
        ajustado = J.ajustar_argumentos(
            "escrever_arquivo", {"path": "a.txt", "content": "oi"}
        )
        self.assertEqual(ajustado, {"caminho": "a.txt", "conteudo": "oi"})

    def test_argumento_a_mais_e_descartado(self):
        ajustado = J.ajustar_argumentos(
            "pesquisar_web", {"consulta": "x", "formato": "json"}
        )
        self.assertEqual(ajustado, {"consulta": "x"})

    def test_pesquisa_funciona_com_o_nome_errado(self):
        """O caso do registro, de ponta a ponta: query em vez de consulta."""
        material = (
            "Resultados para: clima Cachoeira\n1. Clima agora\n"
            "   28 graus, céu limpo.",
            None,
        )

        with mock.patch.object(
            J.nebell_web, "buscar", return_value=material
        ) as buscar:
            resultado = J.run_tool("pesquisar_web", {"query": "clima Cachoeira"})

        self.assertIn("28 graus", resultado)
        # O valor chegou à função com o nome certo.
        self.assertEqual(buscar.call_args[0][0], "clima Cachoeira")

    def test_ferramenta_sem_argumento_nenhum(self):
        self.assertEqual(J.ajustar_argumentos("data_hora", {"x": 1}), {})


class TestEco(NebellTest):
    """
    O microfone capta o alto-falante. No registro, ele transcreveu a
    própria saudação como se fosse o usuário e respondeu a si mesmo.
    """

    def setUp(self):
        super().setUp()
        J.ultimas_falas.clear()
        J.falando_agora.clear()
        J.ultima_fala_em[0] = 0.0

    def test_a_saudacao_dele_e_reconhecida_como_eco(self):
        J.speak("Sistemas online. Como posso ajudar?")
        flush_speech()
        self.assertTrue(J.parece_eco("sistemas online como posso"))

    def test_resposta_longa_dele_tambem(self):
        J.speak(
            "Para que eu possa ajudar com sistemas online, preciso saber "
            "exatamente sobre o que você deseja informações ou ajuda"
        )
        flush_speech()
        self.assertTrue(J.parece_eco(
            "Para que eu possa ajudar com os sistemas. Online, preciso "
            "saber exatamente sobre o que você deseja de informações"
        ))

    def test_fala_legitima_passa(self):
        J.speak("Sistemas online. Como posso ajudar?")
        flush_speech()

        for pedido in ["bom dia", "como está o clima", "abre o brave",
                       "quanto é dois mais dois", "limpe minha lixeira"]:
            self.assertFalse(J.parece_eco(pedido), pedido)

    def test_sem_nada_dito_nao_ha_eco(self):
        self.assertFalse(J.parece_eco("qualquer coisa"))

    def test_extrair_pedido_descarta_o_eco(self):
        J.speak("Sistemas online. Como posso ajudar?")
        flush_speech()
        self.assertIsNone(J.extrair_pedido("sistemas online como posso"))

    def test_speak_marca_que_esta_falando(self):
        J.falando_agora.clear()
        J.speak("falando agora")
        self.assertTrue(J.falando_agora.is_set())
        flush_speech()
        self.assertFalse(J.falando_agora.is_set())

    def test_so_guarda_as_ultimas_falas(self):
        for i in range(40):
            J.speak(f"frase número {i}")
        flush_speech()
        self.assertLessEqual(len(J.ultimas_falas), 12)

    def test_stop_speaking_libera_a_escuta(self):
        J.speak("algo longo")
        J.stop_speaking()
        self.assertFalse(J.falando_agora.is_set())


class TestConfirmacaoNaJanela(NebellTest):
    """
    O usuário respondeu "faça" e a ação foi cancelada, porque a palavra
    não estava na lista — e a mensagem dele foi engolida.
    """

    def setUp(self):
        super().setUp()
        self.hud = mock.Mock()
        self.hud.active = True
        J.hud = self.hud
        J.interaction_mode = "text"
        while not J.request_queue.empty():
            J.request_queue.get_nowait()

    def tearDown(self):
        J.hud = None

    def test_faca_autoriza(self):
        J.request_queue.put(("hud", "faça"))
        self.assertTrue(J.confirm_action("Vou limpar a lixeira."))
        flush_speech()

    def test_varias_formas_de_sim(self):
        for palavra in ("sim", "pode", "manda", "ok", "beleza", "isso",
                        "faz", "vai", "autorizo", "prossiga"):
            J.request_queue.put(("hud", palavra))
            self.assertTrue(J.confirm_action("Ação."), palavra)
            flush_speech()

    def test_varias_formas_de_nao(self):
        for palavra in ("não", "cancela", "deixa", "esquece", "negativo"):
            J.request_queue.put(("hud", palavra))
            self.assertFalse(J.confirm_action("Ação."), palavra)
            flush_speech()

    def test_mensagem_que_nao_e_resposta_volta_para_a_fila(self):
        """O ponto principal: a mensagem do usuário não pode sumir."""
        J.request_queue.put(("hud", "abre o brave"))

        self.assertFalse(J.confirm_action("Vou limpar a lixeira."))

        # A mensagem tem de estar de volta na fila, para ser atendida.
        self.assertFalse(J.request_queue.empty())
        self.assertEqual(J.request_queue.get_nowait(), ("hud", "abre o brave"))
        flush_speech()

    def test_sem_resposta_cancela(self):
        with mock.patch.object(J, "CONFIRM_TIMEOUT", 0.2):
            self.assertFalse(J.confirm_action("Ação."))
        flush_speech()

    def test_pedido_de_sair_nao_e_consumido(self):
        J.request_queue.put(("sair", ""))
        self.assertFalse(J.confirm_action("Ação."))
        self.assertEqual(J.request_queue.get_nowait(), ("sair", ""))
        flush_speech()


class TestAbrirProgramas(NebellTest):
    def apps(self):
        return [
            ("Brave", "Brave.exe"),
            ("WhatsApp", "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App"),
            ("Discord", "com.squirrel.Discord.Discord"),
            ("Bloco de Notas", "Microsoft.Windows.Notepad_8wekyb3d8bbwe!App"),
        ]

    def test_abre_o_brave_pelo_menu_iniciar(self):
        with mock.patch.object(J, "listar_apps_instalados", return_value=self.apps()), \
             mock.patch.object(J.subprocess, "Popen") as popen:
            resultado = J.tool_abrir_programa("brave")

        self.assertIn("Brave", resultado)
        popen.assert_called_once()
        self.assertIn("shell:AppsFolder", popen.call_args[0][0][1])

    def test_abre_app_da_store(self):
        with mock.patch.object(J, "listar_apps_instalados", return_value=self.apps()), \
             mock.patch.object(J.subprocess, "Popen"):
            self.assertIn("WhatsApp", J.tool_abrir_programa("whatsapp"))

    def test_tolera_erro_de_fala(self):
        """"whattzap" foi o que o reconhecimento entendeu."""
        with mock.patch.object(J, "listar_apps_instalados", return_value=self.apps()), \
             mock.patch.object(J.subprocess, "Popen"):
            self.assertIn("WhatsApp", J.tool_abrir_programa("whattzap"))

    def test_lista_curta_tem_prioridade(self):
        with mock.patch.object(J.subprocess, "Popen") as popen:
            resultado = J.tool_abrir_programa("bloco de notas")

        self.assertIn("bloco de notas", resultado)
        # Usa o comando direto, não o shell:AppsFolder.
        self.assertEqual(popen.call_args[0][0], "notepad")

    def test_sugere_parecidos_quando_nao_acha(self):
        with mock.patch.object(J, "listar_apps_instalados", return_value=self.apps()), \
             mock.patch.object(J.shutil, "which", return_value=None), \
             mock.patch.object(J.subprocess, "Popen"):
            resultado = J.tool_abrir_programa("discordia")

        self.assertIn("Discord", resultado)

    def test_listar_programas(self):
        with mock.patch.object(J, "listar_apps_instalados", return_value=self.apps()):
            resultado = J.tool_listar_programas()

        self.assertIn("Brave", resultado)
        self.assertIn("4 programa", resultado)

    def test_listar_com_filtro(self):
        with mock.patch.object(J, "listar_apps_instalados", return_value=self.apps()):
            self.assertIn("WhatsApp", J.tool_listar_programas("whats"))

    def test_nome_vazio(self):
        self.assertIn("Informe", J.tool_abrir_programa("  "))


class TestCaminhoDoReconhecimento(NebellTest):
    """
    O bug que derrubava tudo: `transcribe` chamava um `recognizer`
    global que deixou de existir. Como o faster-whisper não está
    instalado, TODA fala caía ali e estourava NameError — parecia que
    ele "entendia mal", mas estava falhando em cada frase.

    Os testes antigos trocavam `transcribe` por um dublê e nunca
    passavam por esta linha. Agora passam.
    """

    def falso_gerenciador(self, texto="texto reconhecido"):
        import types

        class FalsoReconhecedor:
            energy_threshold = 300.0
            dynamic_energy_threshold = True

            def recognize_google(self, audio, language=None):
                return f"  {texto}  "

        falso = mock.Mock()
        falso.ready = True
        falso.recognizer = FalsoReconhecedor()
        falso.escutar.return_value = b"audio"
        falso.ultimo_nivel = 1200
        falso.capturando = threading.Event()
        return falso

    def test_google_funciona_sem_whisper(self):
        falso = self.falso_gerenciador()
        J.whisper_ready.set()

        with mock.patch.object(J, "mic_manager", falso), \
             mock.patch.object(J, "whisper_model", None):
            self.assertEqual(J.transcribe(b"audio"), "texto reconhecido")

    def test_listen_completo_sem_whisper(self):
        falso = self.falso_gerenciador("abra o navegador")
        J.whisper_ready.set()

        with mock.patch.object(J, "mic_manager", falso), \
             mock.patch.object(J, "whisper_model", None):
            self.assertEqual(J.listen(timeout=1), "abra o navegador")

    def test_sem_microfone_erro_claro(self):
        J.whisper_ready.set()

        with mock.patch.object(J, "mic_manager", None), \
             mock.patch.object(J, "whisper_model", None):
            with self.assertRaises(RuntimeError) as capturado:
                J.transcribe(b"audio")

        self.assertIn("indisponível", str(capturado.exception))

    def test_whisper_com_falha_cai_para_o_google(self):
        falso = self.falso_gerenciador("veio do google")

        with mock.patch.object(J, "mic_manager", falso), \
             mock.patch.object(J, "whisper_model", object()), \
             mock.patch.object(J, "transcribe_whisper",
                               side_effect=Exception("modelo quebrado")):
            self.assertEqual(J.transcribe(b"audio"), "veio do google")

    def test_whisper_tem_prioridade(self):
        falso = self.falso_gerenciador("google")

        with mock.patch.object(J, "mic_manager", falso), \
             mock.patch.object(J, "whisper_model", object()), \
             mock.patch.object(J, "transcribe_whisper", return_value="whisper"):
            self.assertEqual(J.transcribe(b"audio"), "whisper")

    def test_nenhuma_variavel_global_orfa(self):
        """
        Varre o módulo em busca de nomes usados e não definidos — é o
        que teria pegado o `recognizer` solto.
        """
        import ast
        import builtins

        fonte = Path(J.__file__).read_text(encoding="utf-8")
        arvore = ast.parse(fonte)

        definidos = set(dir(builtins)) | set(vars(J))

        for no in ast.walk(arvore):
            if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
                definidos.add(no.name)
            elif isinstance(no, ast.ClassDef):
                definidos.add(no.name)

        faltando = set()

        for no in ast.walk(arvore):
            if isinstance(no, ast.Name) and isinstance(no.ctx, ast.Load):
                if no.id not in definidos:
                    faltando.add(no.id)

        # Os globais que eu removi em refatorações anteriores não podem
        # ter sobrado como referência solta em lugar nenhum.
        for orfao in ("recognizer", "microphone", "_mic_entered",
                      "mic_lock", "memory_facts", "MEMORY_FILE",
                      "load_memory", "save_memory", "KEEP_MIC_OPEN",
                      "EMOJI_RE", "jarvis_audio", "jarvis_hud"):
            self.assertNotIn(orfao, faltando, f"{orfao} ficou órfão")


class TestEscutaDireta(NebellTest):
    """Sem exigir a palavra de ativação, mas aceitando-a."""

    def test_fala_direta_vira_pedido(self):
        self.assertEqual(
            J.extrair_pedido("que horas são agora"), "que horas são agora"
        )

    def test_nome_na_frente_e_removido(self):
        self.assertEqual(
            J.extrair_pedido("Nebell, abra o chrome"), "abra o chrome"
        )

    def test_nome_sozinho_pede_o_resto(self):
        self.assertEqual(J.extrair_pedido("nebell"), "")
        self.assertEqual(J.extrair_pedido("Nebell!"), "")

    def test_ruido_curto_e_descartado(self):
        for ruido in ["ã", "hmm", "eh", "ah", "é", "oi", "  "]:
            self.assertIsNone(J.extrair_pedido(ruido), ruido)

    def test_palavra_de_parada_vale_mesmo_curta(self):
        self.assertEqual(J.extrair_pedido("pare"), "pare")
        self.assertEqual(J.extrair_pedido("chega"), "chega")

    def test_comandos_de_modo_passam_mesmo_curtos(self):
        for comando in ("menu", "encerrar", "modo texto", "modo voz"):
            self.assertEqual(J.extrair_pedido(comando), comando, comando)

    def test_vazio_e_nulo(self):
        self.assertIsNone(J.extrair_pedido(""))
        self.assertIsNone(J.extrair_pedido(None))

    def test_com_exigencia_ligada_volta_ao_antigo(self):
        J.REQUIRE_WAKE_WORD = True
        try:
            self.assertIsNone(J.extrair_pedido("que horas são agora"))
            self.assertEqual(
                J.extrair_pedido("Nebell, que horas são"), "que horas são"
            )
        finally:
            J.REQUIRE_WAKE_WORD = False

    def test_pontuacao_solta_e_limpa(self):
        self.assertEqual(
            J.extrair_pedido("abra o navegador, por favor."),
            "abra o navegador, por favor",
        )

    def test_saudacao_existe_e_e_curta(self):
        self.assertIn("Sistemas online", J.SAUDACAO)
        self.assertIn("ajudar", J.SAUDACAO)
        self.assertLess(len(J.SAUDACAO), 60)


class TestDiagnosticoDoMicrofone(NebellTest):
    def test_sem_microfone_avisa(self):
        with mock.patch.object(J, "mic_manager", None):
            self.assertIn("indisponível", J.diagnosticar_microfone())

    def falso_gerenciador(self, nivel=3000, texto="teste de voz"):
        import types

        reconhecedor = types.SimpleNamespace(
            energy_threshold=300.0, dynamic_energy_threshold=True
        )
        audio = mock.Mock()
        audio.get_raw_data.return_value = b"\x00\x01" * 16000
        audio.sample_rate = 16000
        audio.sample_width = 2

        falso = mock.Mock()
        falso.ready = True
        falso.recognizer = reconhecedor
        falso.device.describe.return_value = "[1] Microfone (Realtek)"
        falso.escutar.return_value = audio
        falso.ultimo_nivel = nivel
        return falso

    def test_relatorio_completo(self):
        falso = self.falso_gerenciador()

        with mock.patch.object(J, "mic_manager", falso), \
             mock.patch.object(J, "transcribe", return_value="teste de voz"), \
             mock.patch.object(J, "whisper_model", object()):
            relatorio = J.diagnosticar_microfone(4)

        for parte in ("Microfone:", "Limiar", "Volume medido",
                      "Gravei", "Entendi"):
            self.assertIn(parte, relatorio)
        flush_speech()

    def test_avisa_volume_baixo(self):
        falso = self.falso_gerenciador(nivel=50)

        with mock.patch.object(J, "mic_manager", falso), \
             mock.patch.object(J, "transcribe", return_value=""):
            relatorio = J.diagnosticar_microfone(4)

        self.assertIn("volume muito baixo", relatorio)
        flush_speech()

    def test_recalibra_quando_a_voz_fica_abaixo_do_limiar(self):
        falso = self.falso_gerenciador(nivel=250)
        falso.recognizer.energy_threshold = 900.0

        with mock.patch.object(J, "mic_manager", falso), \
             mock.patch.object(J, "transcribe", return_value="algo"):
            relatorio = J.diagnosticar_microfone(4)

        self.assertIn("abaixo do limiar", relatorio)
        falso.calibrate.assert_called_once()
        flush_speech()

    def test_avisa_que_esta_no_google(self):
        falso = self.falso_gerenciador()

        with mock.patch.object(J, "mic_manager", falso), \
             mock.patch.object(J, "whisper_model", None), \
             mock.patch.object(J, "transcribe", return_value="algo"):
            relatorio = J.diagnosticar_microfone(4)

        self.assertIn("faster-whisper", relatorio)
        flush_speech()

    def test_nada_entendido_aponta_o_motor(self):
        falso = self.falso_gerenciador()

        with mock.patch.object(J, "mic_manager", falso), \
             mock.patch.object(J, "transcribe", return_value=""), \
             mock.patch.object(J, "whisper_model", object()):
            relatorio = J.diagnosticar_microfone(4)

        self.assertIn("motor de reconhecimento", relatorio)
        flush_speech()

    def test_erro_na_gravacao_e_relatado(self):
        falso = self.falso_gerenciador()
        falso.escutar.side_effect = Exception("fluxo fechado")

        with mock.patch.object(J, "mic_manager", falso):
            self.assertIn("Não gravei nada", J.diagnosticar_microfone(4))
        flush_speech()

    def test_ferramenta_limita_os_segundos(self):
        with mock.patch.object(J, "diagnosticar_microfone") as diag:
            J.tool_testar_microfone(99)
            J.tool_testar_microfone("abc")

        self.assertEqual(diag.call_args_list[0].args[0], 10)
        self.assertEqual(diag.call_args_list[1].args[0], 5)


class TestVoz(NebellTest):
    """A voz agora é descoberta na pasta, não fixa no código."""

    def preparar(self, estrutura):
        import tempfile, shutil
        base = Path(tempfile.mkdtemp(prefix="voz_"))
        voices = base / "voices"
        voices.mkdir()

        for caminho in estrutura:
            alvo = voices / caminho
            alvo.parent.mkdir(parents=True, exist_ok=True)
            alvo.write_bytes(b"modelo falso")

        return base, voices

    def descobrir(self, estrutura):
        base, voices = self.preparar(estrutura)
        guardado = J.VOICES_DIR
        try:
            J.VOICES_DIR = voices
            return J.descobrir_voz().relative_to(base).as_posix()
        finally:
            J.VOICES_DIR = guardado

    def test_prefere_a_voz_do_nebell(self):
        achado = self.descobrir(
            ["miro/model.onnx", "nebell/model.onnx", "cadu/model.onnx"]
        )
        self.assertEqual(achado, "voices/nebell/model.onnx")

    def test_usa_a_antiga_enquanto_a_nova_nao_chegou(self):
        achado = self.descobrir(["miro/model.onnx"])
        self.assertEqual(achado, "voices/miro/model.onnx")

    def test_aceita_o_nome_original_do_download(self):
        achado = self.descobrir(["nebell/dii_pt-BR.onnx"])
        self.assertEqual(achado, "voices/nebell/dii_pt-BR.onnx")

    def test_acha_voz_solta_na_pasta(self):
        achado = self.descobrir(["dii_pt-BR.onnx"])
        self.assertEqual(achado, "voices/dii_pt-BR.onnx")

    def test_voz_desconhecida_serve_de_ultimo_recurso(self):
        achado = self.descobrir(["uma_voz_qualquer.onnx"])
        self.assertEqual(achado, "voices/uma_voz_qualquer.onnx")

    def test_pasta_vazia_devolve_o_caminho_esperado(self):
        achado = self.descobrir([])
        self.assertEqual(achado, "voices/nebell/model.onnx")

    def test_ordem_da_preferencia_e_respeitada(self):
        achado = self.descobrir(["cadu/model.onnx", "dii/model.onnx"])
        self.assertEqual(achado, "voices/dii/model.onnx")

    def test_ajuste_da_voz_e_aplicado(self):
        class FalsaConfig:
            def __init__(self, length_scale=None, noise_scale=None,
                         noise_w_scale=None):
                self.length_scale = length_scale
                self.noise_scale = noise_scale
                self.noise_w_scale = noise_w_scale

        with mock.patch.object(J, "SynthesisConfig", FalsaConfig):
            config = J.build_synthesis_config()

        self.assertEqual(config.length_scale, J.VOICE_LENGTH_SCALE)
        self.assertEqual(config.noise_scale, J.VOICE_NOISE_SCALE)

    def test_painel_mostra_o_nome_da_voz(self):
        dados = J.coletar_estatisticas()
        self.assertIn("Piper", dados["voice"])


class TestModoHud(NebellTest):
    """Fluxo da janela: texto e voz entram na mesma fila de pedidos."""

    def setUp(self):
        super().setUp()
        self.hud = mock.Mock()
        self.hud.active = True
        J.hud = self.hud
        while not J.request_queue.empty():
            J.request_queue.get_nowait()
        J.shutdown_event.clear()

    def tearDown(self):
        J.hud = None
        J.shutdown_event.set()

    def test_texto_da_janela_entra_na_fila(self):
        J.hud_submit("  que horas são  ")
        self.assertEqual(J.request_queue.get_nowait(), ("hud", "que horas são"))

    def test_texto_vazio_e_ignorado(self):
        J.hud_submit("   ")
        self.assertTrue(J.request_queue.empty())

    def test_despachante_atende_um_pedido(self):
        J.request_queue.put(("hud", "oi"))
        J.request_queue.put(("sair", ""))

        with mock.patch.object(J, "ask_nebell") as perguntar:
            J.dispatcher_loop()

        perguntar.assert_called_once_with("oi")
        flush_speech()

    def test_pedido_por_voz_aparece_no_registro(self):
        J.request_queue.put(("voz", "que horas são"))
        J.request_queue.put(("sair", ""))

        with mock.patch.object(J, "ask_nebell"):
            J.dispatcher_loop()

        self.hud.add_message.assert_any_call("user", "que horas são")
        flush_speech()

    def test_erro_em_um_pedido_nao_mata_o_despachante(self):
        J.request_queue.put(("hud", "quebra"))
        J.request_queue.put(("hud", "segundo"))
        J.request_queue.put(("sair", ""))

        chamadas = []

        def falso(texto):
            chamadas.append(texto)
            if texto == "quebra":
                raise RuntimeError("falhou")

        with mock.patch.object(J, "ask_nebell", falso):
            J.dispatcher_loop()

        self.assertEqual(chamadas, ["quebra", "segundo"])
        self.assertFalse(J.busy_event.is_set())
        flush_speech()

    def test_sair_encerra_e_fecha_a_janela(self):
        J.request_queue.put(("sair", ""))
        J.dispatcher_loop()
        self.assertTrue(J.shutdown_event.is_set())
        self.hud.destroy.assert_called_once()
        flush_speech()

    def test_botao_parar_interrompe(self):
        J.busy_event.set()
        try:
            J.hud_stop()
            self.assertTrue(J.cancel_event.is_set())
        finally:
            J.busy_event.clear()
            J.cancel_event.clear()

    def test_parar_sem_nada_tocando_so_volta_ao_repouso(self):
        J.hud_stop()
        self.hud.set_state.assert_any_call("idle")

    def test_estados_durante_a_resposta(self):
        fake = FakeSession([FakeResponse(ndjson(text_chunk("Pronto.", True)))])

        with mock.patch.object(J, "session", fake):
            J.ask_nebell("faça algo")

        estados = [c.args[0] for c in self.hud.set_state.call_args_list]
        self.assertIn("thinking", estados)
        self.assertEqual(estados[-1], "idle")
        flush_speech()

    def test_resposta_vai_para_o_registro(self):
        # A resposta chega na janela pela bolha que se preenche, não
        # mais como uma mensagem única no fim. Mandar as duas coisas
        # mostraria o mesmo texto duas vezes.
        fake = FakeSession([FakeResponse(ndjson(text_chunk("Tudo certo.", True)))])

        with mock.patch.object(J, "session", fake):
            J.ask_nebell("e aí")

        enviados = [
            c.args[0] for c in self.hud.stream_message.call_args_list
        ]
        self.assertIn("Tudo certo.", enviados)
        self.hud.add_message.assert_not_called()
        self.hud.fechar_stream.assert_called()
        flush_speech()

    def test_confirmacao_pela_janela_aceita(self):
        J.request_queue.put(("hud", "sim"))
        self.assertTrue(J.confirm_action("Vou criar um arquivo."))
        flush_speech()

    def test_confirmacao_pela_janela_recusa(self):
        J.request_queue.put(("hud", "não"))
        self.assertFalse(J.confirm_action("Vou criar um arquivo."))
        flush_speech()

    def test_confirmacao_sem_resposta_cancela(self):
        with mock.patch.object(J, "CONFIRM_TIMEOUT", 0.1):
            self.assertFalse(J.confirm_action("Vou criar um arquivo."))
        flush_speech()

    def test_estatisticas_tem_os_campos_do_painel(self):
        dados = J.coletar_estatisticas()
        for campo in ("model", "voice", "stt", "mic"):
            self.assertIn(campo, dados)

    def test_estatisticas_avisam_que_o_whisper_falta(self):
        with mock.patch.object(J, "whisper_model", None):
            self.assertIn("faster-whisper", J.coletar_estatisticas()["stt"])

    def test_nivel_de_audio_vai_para_a_janela(self):
        import struct
        quadro = struct.pack("<8h", *([9000] * 8))
        J._level_sent_at = 0
        J.feed_level(quadro)
        self.hud.set_level.assert_called_once()
        self.assertGreater(self.hud.set_level.call_args.args[0], 0.5)

    def test_nivel_nao_e_enviado_toda_hora(self):
        import struct
        quadro = struct.pack("<8h", *([3000] * 8))
        J._level_sent_at = 0
        J.feed_level(quadro)
        J.feed_level(quadro)
        self.assertEqual(self.hud.set_level.call_count, 1)

    def test_troca_de_microfone_pela_janela(self):
        falso = mock.Mock()
        falso.use.return_value = (True, "Microfone agora é Fone.")

        with mock.patch.object(J, "mic_manager", falso):
            J.hud_set_mic("fone")

        falso.use.assert_called_once_with("fone")
        self.hud.add_message.assert_any_call("nebell", "Microfone agora é Fone.")


class TestOllamaAutomatico(NebellTest):
    """O Ollama tem de subir junto, sem o usuário abrir à mão."""

    def test_nao_inicia_se_ja_esta_rodando(self):
        with mock.patch.object(J, "ollama_vivo", return_value=True), \
             mock.patch.object(J.subprocess, "Popen") as popen:
            self.assertTrue(J.garantir_ollama())

        popen.assert_not_called()

    def test_inicia_quando_esta_fechado(self):
        estados = [False, False, True]

        with mock.patch.object(J, "ollama_vivo", side_effect=estados), \
             mock.patch.object(J.subprocess, "Popen") as popen, \
             mock.patch.object(J.time, "sleep"):
            self.assertTrue(J.garantir_ollama(espera=10))

        popen.assert_called_once()
        self.assertIn("ollama", popen.call_args[0][0])

    def test_comando_ollama_ausente(self):
        with mock.patch.object(J, "ollama_vivo", return_value=False), \
             mock.patch.object(
                 J.subprocess, "Popen", side_effect=FileNotFoundError()
             ):
            self.assertFalse(J.garantir_ollama(espera=1))

    def test_nao_espera_para_sempre(self):
        with mock.patch.object(J, "ollama_vivo", return_value=False), \
             mock.patch.object(J.subprocess, "Popen"), \
             mock.patch.object(J.time, "sleep"):
            self.assertFalse(J.garantir_ollama(espera=2))

    def test_avisa_modelo_que_falta(self):
        resposta = mock.Mock()
        resposta.json.return_value = {"models": [{"name": "llama3:8b"}]}
        resposta.raise_for_status = mock.Mock()

        with mock.patch.object(J.session, "get", return_value=resposta):
            tem, instalados = J.modelo_disponivel()

        self.assertFalse(tem)
        self.assertIn("llama3:8b", instalados)

    def test_modelo_presente(self):
        resposta = mock.Mock()
        resposta.json.return_value = {"models": [{"name": J.MODEL_NAME}]}
        resposta.raise_for_status = mock.Mock()

        with mock.patch.object(J.session, "get", return_value=resposta):
            self.assertTrue(J.modelo_disponivel()[0])

    def test_ollama_sem_resposta_nao_atrapalha(self):
        with mock.patch.object(J.session, "get", side_effect=Exception("off")):
            self.assertTrue(J.modelo_disponivel()[0])


class TestNavegadorBrave(NebellTest):
    def setUp(self):
        super().setUp()
        J._navegador_achado[0] = None

    def tearDown(self):
        J._navegador_achado[0] = None

    def test_acha_o_brave_no_path(self):
        with mock.patch.object(
            J.shutil, "which", side_effect=lambda n: r"C:\x\brave.exe"
        ):
            self.assertIn("brave", J.achar_navegador())

    def test_abre_o_site_no_brave(self):
        with mock.patch.object(J, "achar_navegador", return_value=r"C:\x\brave.exe"), \
             mock.patch.object(J.subprocess, "Popen") as popen:
            resultado = J.tool_abrir_site("exemplo.com")

        self.assertIn("Brave", resultado)
        self.assertEqual(
            popen.call_args[0][0], [r"C:\x\brave.exe", "https://exemplo.com"]
        )

    def test_cai_para_o_navegador_padrao(self):
        with mock.patch.object(J, "achar_navegador", return_value=None), \
             mock.patch.object(J.webbrowser, "open") as abrir:
            resultado = J.tool_abrir_site("exemplo.com")

        abrir.assert_called_once_with("https://exemplo.com")
        self.assertIn("padrão", resultado)

    def test_brave_que_falha_cai_para_o_padrao(self):
        with mock.patch.object(J, "achar_navegador", return_value="brave.exe"), \
             mock.patch.object(
                 J.subprocess, "Popen", side_effect=Exception("não abriu")
             ), \
             mock.patch.object(J.webbrowser, "open") as abrir:
            resultado = J.tool_abrir_site("exemplo.com")

        abrir.assert_called_once()
        self.assertIn("padrão", resultado)

    def test_url_vazia(self):
        self.assertIn("Informe", J.tool_abrir_site("  "))

    def test_pesquisa_no_navegador(self):
        with mock.patch.object(J, "tool_abrir_site", return_value="abri") as abrir:
            J.tool_pesquisar_no_navegador("gato fofo")

        self.assertIn("google.com/search", abrir.call_args[0][0])
        self.assertIn("gato", abrir.call_args[0][0])

    def test_pesquisa_no_youtube(self):
        with mock.patch.object(J, "tool_abrir_site", return_value="abri") as abrir:
            J.tool_pesquisar_no_navegador("música", site="youtube")

        self.assertIn("youtube.com/results", abrir.call_args[0][0])

    def test_pesquisa_sem_termos(self):
        self.assertIn("Informe", J.tool_pesquisar_no_navegador(""))


class TestLixeira(NebellTest):
    @unittest.skipIf(NO_WINDOWS, "no Windows a Lixeira existe")
    def test_fora_do_windows(self):
        self.assertIn("só existe no Windows", J.tool_lixeira("status"))

    def test_sem_windows_avisa(self):
        """Independente da plataforma: sem Windows, recusa."""
        with mock.patch.object(J, "IS_WINDOWS", False):
            self.assertIn("só existe no Windows", J.tool_lixeira("status"))

    def test_status_com_itens(self):
        with mock.patch.object(J, "IS_WINDOWS", True), \
             mock.patch.object(
                 J, "powershell_json", return_value=([{"Quantidade": 42}], "")
             ):
            self.assertIn("42 item", J.tool_lixeira("status"))

    def test_status_vazia(self):
        with mock.patch.object(J, "IS_WINDOWS", True), \
             mock.patch.object(
                 J, "powershell_json", return_value=([{"Quantidade": 0}], "")
             ):
            self.assertIn("vazia", J.tool_lixeira("status"))

    def test_esvaziar_usa_o_comando_certo(self):
        """
        Clear-RecycleBin precisa de -Force E -Confirm:$false. Sem os
        dois ele fica esperando uma resposta que nunca chega.
        """
        with mock.patch.object(J, "IS_WINDOWS", True), \
             mock.patch.object(
                 J, "powershell_json", return_value=([{"Quantidade": 5}], "")
             ), \
             mock.patch.object(J, "confirm_action", return_value=True), \
             mock.patch.object(J, "rodar_shell", return_value="pronto") as rodar:
            resultado = J.tool_lixeira("esvaziar")

        self.assertIn("esvaziada", resultado)
        comando = " ".join(rodar.call_args[0][0])
        self.assertIn("Clear-RecycleBin", comando)
        self.assertIn("-Force", comando)
        self.assertIn("-Confirm:$false", comando)

    def test_esvaziar_vazia_nao_pergunta(self):
        with mock.patch.object(J, "IS_WINDOWS", True), \
             mock.patch.object(
                 J, "powershell_json", return_value=([{"Quantidade": 0}], "")
             ), \
             mock.patch.object(J, "confirm_action") as confirmar:
            self.assertIn("já está vazia", J.tool_lixeira("esvaziar"))

        confirmar.assert_not_called()

    def test_esvaziar_negado(self):
        with mock.patch.object(J, "IS_WINDOWS", True), \
             mock.patch.object(
                 J, "powershell_json", return_value=([{"Quantidade": 3}], "")
             ), \
             mock.patch.object(J, "confirm_action", return_value=False), \
             mock.patch.object(J, "rodar_shell") as rodar:
            self.assertIn("negou", J.tool_lixeira("esvaziar"))

        rodar.assert_not_called()

    def test_tem_plano_de_reserva(self):
        chamadas = []

        def falso_shell(args, *a, **k):
            chamadas.append(" ".join(args))
            return "pronto" if "Recycle.Bin" in " ".join(args) else "erro"

        with mock.patch.object(J, "IS_WINDOWS", True), \
             mock.patch.object(
                 J, "powershell_json", return_value=([{"Quantidade": 3}], "")
             ), \
             mock.patch.object(J, "confirm_action", return_value=True), \
             mock.patch.object(J, "rodar_shell", side_effect=falso_shell):
            resultado = J.tool_lixeira("esvaziar")

        self.assertIn("esvaziada", resultado)
        self.assertEqual(len(chamadas), 2)

    def test_comando_da_lixeira_nao_esta_bloqueado(self):
        self.assertFalse(J.BLOCKED_COMMANDS.search("Clear-RecycleBin -Force"))

    def test_acao_desconhecida(self):
        with mock.patch.object(J, "IS_WINDOWS", True):
            self.assertIn("status ou esvaziar", J.tool_lixeira("dançar"))


class TestGpu(NebellTest):
    def setUp(self):
        super().setUp()
        J._gpu_disponivel[0] = None
        J._gpu_cache[0] = 0.0
        J._gpu_cache[1] = None

    def tearDown(self):
        J._gpu_disponivel[0] = None
        J._gpu_cache[0] = 0.0
        J._gpu_cache[1] = None

    def saida_nvidia(self):
        return "37, 2048, 6144, 54, NVIDIA GeForce RTX 4050 Laptop GPU"

    def test_le_o_nvidia_smi(self):
        with mock.patch.object(
            J.subprocess, "run",
            return_value=mock.Mock(stdout=self.saida_nvidia()),
        ):
            gpu = J.ler_gpu()

        self.assertEqual(gpu["uso"], 37.0)
        self.assertEqual(gpu["memoria_total"], 6144.0)
        self.assertEqual(gpu["temperatura"], 54.0)
        self.assertIn("RTX", gpu["nome"])

    def test_frase_para_falar(self):
        with mock.patch.object(
            J.subprocess, "run",
            return_value=mock.Mock(stdout=self.saida_nvidia()),
        ):
            texto = J.tool_info_gpu()

        self.assertIn("37 por cento", texto)
        self.assertIn("54 graus", texto)

    def test_sem_nvidia_smi(self):
        with mock.patch.object(
            J.subprocess, "run", side_effect=FileNotFoundError()
        ):
            self.assertIsNone(J.ler_gpu())
            self.assertIn("Não encontrei", J.tool_info_gpu())

    def test_usa_cache_entre_leituras(self):
        """Cada leitura abre um processo; não vale repetir a cada ciclo."""
        with mock.patch.object(
            J.subprocess, "run",
            return_value=mock.Mock(stdout=self.saida_nvidia()),
        ) as rodar:
            J.ler_gpu()
            J.ler_gpu()
            J.ler_gpu()

        self.assertEqual(rodar.call_count, 1)

    def test_cache_expira(self):
        with mock.patch.object(
            J.subprocess, "run",
            return_value=mock.Mock(stdout=self.saida_nvidia()),
        ) as rodar:
            J.ler_gpu()
            J._gpu_cache[0] = J.time.time() - J.GPU_INTERVALO - 1
            J.ler_gpu()

        self.assertEqual(rodar.call_count, 2)

    def test_nao_tenta_de_novo_depois_de_falhar(self):
        with mock.patch.object(
            J.subprocess, "run", side_effect=FileNotFoundError()
        ) as rodar:
            J.ler_gpu()
            J.ler_gpu()
            J.ler_gpu()

        self.assertEqual(rodar.call_count, 1)

    def test_saida_estranha(self):
        with mock.patch.object(
            J.subprocess, "run", return_value=mock.Mock(stdout="lixo")
        ):
            self.assertIsNone(J.ler_gpu())

    def test_gpu_entra_no_painel(self):
        with mock.patch.object(
            J.subprocess, "run",
            return_value=mock.Mock(stdout=self.saida_nvidia()),
        ):
            dados = J.coletar_estatisticas()

        self.assertEqual(dados["gpu"], 37.0)
        self.assertIn("37%", dados["gpuLabel"])
        self.assertIn("6.0GB", dados["gpuLabel"])

    def test_painel_sem_gpu(self):
        with mock.patch.object(
            J.subprocess, "run", side_effect=FileNotFoundError()
        ):
            dados = J.coletar_estatisticas()

        self.assertIn("sem GPU", dados["gpuLabel"])


class TestMicrofone(NebellTest):
    def test_listen_sem_microfone(self):
        with mock.patch.object(J, "microphone_available", return_value=False):
            self.assertIsNone(J.listen())

    def test_comando_bloqueado_mantem_a_mensagem(self):
        with mock.patch.object(J, "confirm_action") as confirm:
            resultado = J.tool_executar_comando("format C: /q")
        confirm.assert_not_called()
        self.assertIn("bloqueado", resultado)


# ============================================================
# MODULOS NOVOS LIGADOS AO NEBELL
# ============================================================

class TestRegistroDasFerramentas(NebellTest):
    def nomes(self):
        return {e["function"]["name"] for e in J.TOOL_SCHEMAS}

    def test_toda_ferramenta_declarada_tem_funcao(self):
        self.assertEqual(self.nomes() - set(J.TOOL_FUNCTIONS), set())

    def test_toda_funcao_tem_esquema(self):
        self.assertEqual(set(J.TOOL_FUNCTIONS) - self.nomes(), set())

    def test_todo_gatilho_aponta_para_uma_ferramenta(self):
        self.assertEqual(set(J.TOOL_GATILHOS) - self.nomes(), set())

    def test_as_ferramentas_novas_estao_registradas(self):
        for nome in (
            "lembrete", "ler_tela", "capturar_tela", "ler_imagem",
            "editar_imagem", "info_imagem", "listar_janelas", "janela",
            "posicionar_janela", "digitar", "atalho", "resumir_documento",
            "procurar_no_documento", "estado_maquina", "perfil",
            "modo_desenvolvedor", "diagnostico",
        ):
            self.assertIn(nome, self.nomes(), nome)

    def test_nenhum_esquema_repetido(self):
        nomes = [e["function"]["name"] for e in J.TOOL_SCHEMAS]
        self.assertEqual(len(nomes), len(set(nomes)))

    def test_obrigatorios_existem_nas_propriedades(self):
        for esquema in J.TOOL_SCHEMAS:
            parametros = esquema["function"]["parameters"]

            for obrigatorio in parametros.get("required", []):
                self.assertIn(
                    obrigatorio, parametros["properties"],
                    esquema["function"]["name"],
                )

    def test_argumentos_das_funcoes_batem_com_o_esquema(self):
        import inspect

        for nome, funcao in J.TOOL_FUNCTIONS.items():
            esperados = set(inspect.signature(funcao).parameters)
            declarados = set(
                J.TOOL_POR_NOME[nome]["function"]["parameters"]["properties"]
            )
            self.assertEqual(declarados - esperados, set(), nome)


class TestSelecaoComAsNovas(NebellTest):
    def selecionar(self, texto):
        return [
            e["function"]["name"] for e in J.selecionar_ferramentas(texto)
        ]

    def test_lembrete_entra_no_pedido_de_lembrete(self):
        self.assertIn(
            "lembrete", self.selecionar("me lembra de pagar a luz amanha as 8")
        )

    def test_tela_entra_no_pedido_sobre_a_tela(self):
        self.assertIn("ler_tela", self.selecionar("o que ta escrito na tela"))

    def test_documento_entra_no_pedido_de_resumo(self):
        self.assertIn(
            "resumir_documento", self.selecionar("resume esse pdf do contrato")
        )

    def test_hardware_entra_no_pedido_de_temperatura(self):
        self.assertIn(
            "estado_maquina", self.selecionar("qual a temperatura da placa")
        )

    def test_perfil_entra_no_modo_jogo(self):
        self.assertIn("perfil", self.selecionar("muda pro modo jogo"))

    def test_edicao_de_imagem(self):
        self.assertIn(
            "editar_imagem", self.selecionar("deixa essa foto menor, 50%")
        )

    def test_atalho(self):
        self.assertIn("atalho", self.selecionar("aperta ctrl s pra mim"))

    def test_continua_respeitando_o_limite(self):
        self.assertLessEqual(
            len(self.selecionar(
                "abre o brave e pesquisa o clima e a cotacao do dolar e "
                "resume o pdf e le a tela e lembra de pagar a luz amanha"
            )),
            J.MAX_TOOLS_POR_PEDIDO,
        )


class TestPerfis(NebellTest):
    def setUp(self):
        super().setUp()
        self.perfil_antes = J.perfil_atual
        J.perfil_atual = "equilibrado"
        J.NUM_CTX = J.PERFIS["equilibrado"]["num_ctx"]
        J.MODEL_OPTIONS["num_ctx"] = J.NUM_CTX

    def tearDown(self):
        J.perfil_atual = self.perfil_antes

    def test_contexto_cabe_na_placa_de_seis_gigas(self):
        # 16384 de contexto custa perto de um giga de VRAM, que e o que
        # falta para o Whisper caber junto.
        self.assertLessEqual(J.PERFIS["equilibrado"]["num_ctx"], 8192)

    def test_todos_os_perfis_tem_as_mesmas_chaves(self):
        esperadas = set(J.PERFIS["equilibrado"])

        for nome, dados in J.PERFIS.items():
            self.assertEqual(set(dados), esperadas, nome)

    def test_perfil_padrao_existe(self):
        self.assertIn(J.PERFIL_PADRAO, J.PERFIS)

    def test_trocar_para_jogo_alivia_a_placa(self):
        with mock.patch.object(J.threading, "Thread"):
            deu, mensagem = J.aplicar_perfil("jogo")

        self.assertTrue(deu)
        self.assertEqual(J.perfil_atual, "jogo")
        self.assertEqual(J.WHISPER_DEVICE, "cpu")
        self.assertEqual(J.MODEL_OPTIONS["num_ctx"], J.PERFIS["jogo"]["num_ctx"])

    def test_apelidos_de_fala(self):
        for dito, esperado in (
            ("vou jogar", None), ("game", "jogo"), ("gamer", "jogo"),
            ("normal", "equilibrado"), ("bateria", "economia"),
            ("estudar", "estudo"),
        ):
            if esperado is None:
                continue

            J.perfil_atual = "equilibrado"

            with mock.patch.object(J.threading, "Thread"):
                deu, _ = J.aplicar_perfil(dito)

            self.assertTrue(deu, dito)
            self.assertEqual(J.perfil_atual, esperado, dito)

    def test_perfil_inexistente_lista_os_que_existem(self):
        deu, mensagem = J.aplicar_perfil("turbo")
        self.assertFalse(deu)
        self.assertIn("equilibrado", mensagem)

    def test_trocar_para_o_mesmo_nao_recarrega_nada(self):
        with mock.patch.object(J.threading, "Thread") as thread:
            deu, mensagem = J.aplicar_perfil("equilibrado")

        self.assertTrue(deu)
        thread.assert_not_called()
        self.assertIn("Já estou", mensagem)

    def test_a_escuta_so_recarrega_quando_muda(self):
        J.WHISPER_MODEL = J.PERFIS["estudo"]["whisper"]
        J.WHISPER_DEVICE = J.PERFIS["estudo"]["whisper_device"]

        with mock.patch.object(J, "iniciar_sentinela"), \
                mock.patch.object(J.threading, "Thread") as thread:
            J.aplicar_perfil("estudo")

        thread.assert_not_called()

    def test_perfil_sem_nome_lista_tudo(self):
        texto = J.tool_perfil()
        self.assertIn(J.perfil_atual, texto)

        for nome in J.PERFIS:
            self.assertIn(nome, texto)

    def test_atalho_local_troca_o_perfil(self):
        with mock.patch.object(J.threading, "Thread"):
            resposta = J.local_fast_answer("ativa o modo jogo")

        self.assertIsNotNone(resposta)
        self.assertEqual(J.perfil_atual, "jogo")

    def test_atalho_local_responde_qual_perfil(self):
        self.assertIn("equilibrado", J.local_fast_answer("qual o perfil"))


class TestModoDesenvolvedor(NebellTest):
    def setUp(self):
        super().setUp()
        J.dev_mode = False
        J.DEV_LOG_FILE = TMP / "dev.log"

        if J.DEV_LOG_FILE.exists():
            J.DEV_LOG_FILE.unlink()

    def tearDown(self):
        J.dev_mode = False

    def test_desligado_nao_grava_nada(self):
        J.dev_log("qualquer coisa")
        self.assertFalse(J.DEV_LOG_FILE.exists())

    def test_ligar_e_desligar(self):
        self.assertIn("ligado", J.tool_modo_desenvolvedor("ligar"))
        self.assertTrue(J.dev_mode)

        self.assertIn("desligado", J.tool_modo_desenvolvedor("desligar"))
        self.assertFalse(J.dev_mode)

    def test_grava_quando_ligado(self):
        J.tool_modo_desenvolvedor("ligar")
        J.dev_log("chamei a ferramenta clima")

        self.assertIn("clima", J.DEV_LOG_FILE.read_text(encoding="utf-8"))

    def test_status(self):
        self.assertIn("desligado", J.tool_modo_desenvolvedor("status"))

    def test_log_vazio(self):
        self.assertIn("vazio", J.tool_modo_desenvolvedor("log"))

    def test_log_traz_as_ultimas_linhas(self):
        J.dev_mode = True

        for numero in range(40):
            J.dev_log(f"linha {numero}")

        texto = J.tool_modo_desenvolvedor("log")
        self.assertIn("linha 39", texto)
        self.assertNotIn("linha 1 ", texto)

    def test_run_tool_registra_a_chamada(self):
        J.dev_mode = True
        J.run_tool("data_hora", {})

        registro = J.DEV_LOG_FILE.read_text(encoding="utf-8")
        self.assertIn("data_hora", registro)
        self.assertIn("devolveu", registro)

    def test_run_tool_registra_a_correcao_de_argumento(self):
        J.dev_mode = True

        with mock.patch.object(J, "tool_pesquisar_web", lambda consulta: "ok"), \
                mock.patch.dict(
                    J.TOOL_FUNCTIONS, {"pesquisar_web": lambda consulta: "ok"}
                ):
            J.run_tool("pesquisar_web", {"query": "dolar hoje"})

        self.assertIn("corrigidos", J.DEV_LOG_FILE.read_text(encoding="utf-8"))

    def test_erro_de_ferramenta_vai_para_o_registro(self):
        J.dev_mode = True

        with mock.patch.dict(
            J.TOOL_FUNCTIONS, {"data_hora": lambda: 1 / 0}
        ):
            resultado = J.run_tool("data_hora", {})

        self.assertIn("Erro", resultado)
        self.assertIn("estourou", J.DEV_LOG_FILE.read_text(encoding="utf-8"))

    def test_prompt_avisa_o_modelo(self):
        J.dev_mode = True
        self.assertIn("MODO DESENVOLVEDOR", J.build_system_prompt())


class TestFerramentasDeLembrete(NebellTest):
    def setUp(self):
        super().setUp()
        import nebell_agenda

        self.falas = []
        J.agenda = nebell_agenda.Agenda(
            J.memoria, ao_disparar=self.falas.append, log=lambda *a: None
        )
        J.agenda.criar_tabela()

    def tearDown(self):
        if J.agenda is not None:
            J.agenda.parar()

        J.agenda = None

    def test_criar(self):
        resposta = J.tool_lembrete("criar", "pagar a luz", "amanha as 8")
        self.assertIn("pagar a luz", resposta)

    def test_criar_sem_assunto(self):
        self.assertIn("Diga", J.tool_lembrete("criar", "", "amanha as 8"))

    def test_criar_sem_hora(self):
        self.assertIn("quando", J.tool_lembrete("criar", "algo", ""))

    def test_listar_vazio(self):
        self.assertIn("nada", J.tool_lembrete("listar").lower())

    def test_listar_depois_de_criar(self):
        J.tool_lembrete("criar", "pagar a luz", "amanha as 8")
        self.assertIn("pagar a luz", J.tool_lembrete("listar"))

    def test_acao_desconhecida_lista(self):
        J.tool_lembrete("criar", "pagar a luz", "amanha as 8")
        self.assertIn("pagar a luz", J.tool_lembrete("abracadabra"))

    def test_cancelar(self):
        J.tool_lembrete("criar", "pagar a luz", "amanha as 8")
        self.assertIn("Cancelei", J.tool_lembrete("cancelar", "luz"))

    def test_cancelar_sem_assunto(self):
        self.assertIn("qual", J.tool_lembrete("cancelar", ""))

    def test_sem_agenda_explica(self):
        J.agenda = None
        self.assertIn("agenda", J.tool_lembrete("listar").lower())

    def test_prompt_do_sistema_traz_os_lembretes(self):
        J.tool_lembrete("criar", "pagar a luz", "amanha as 8")
        self.assertIn("pagar a luz", J.build_system_prompt())

    def test_atalho_local_lista_os_lembretes(self):
        J.tool_lembrete("criar", "pagar a luz", "amanha as 8")
        self.assertIn("pagar a luz", J.local_fast_answer("meus lembretes"))

    def test_aviso_fora_de_hora_fala_e_registra(self):
        J.avisar_do_nada("Lembrete: pagar a luz.")
        J.wait_for_speech()

        self.assertTrue(any(
            "pagar a luz" in fala for fala in fake_voice.spoken
        ))

    def test_aviso_de_perigo_vem_com_atencao(self):
        J.avisar_do_nada("A memória está no limite.", "perigo")
        J.wait_for_speech()

        self.assertTrue(any("Atenção" in fala for fala in fake_voice.spoken))

    def test_aviso_nao_sai_depois_do_encerramento(self):
        J.shutdown_event.set()

        try:
            J.avisar_do_nada("isso não deve sair")
            J.wait_for_speech()
            self.assertEqual(fake_voice.spoken, [])
        finally:
            J.shutdown_event.clear()


class TestFerramentasDeVisaoEJanela(NebellTest):
    def test_sem_modulo_de_visao_explica(self):
        with mock.patch.object(J, "nebell_visao", None):
            for resposta in (
                J.tool_ler_tela(), J.tool_capturar_tela(),
                J.tool_ler_imagem("x.png"),
                J.tool_editar_imagem("x.png", "cinza"),
                J.tool_info_imagem("x.png"),
            ):
                self.assertIn("visão", resposta)

    def test_sem_modulo_de_janela_explica(self):
        with mock.patch.object(J, "nebell_janela", None):
            for resposta in (
                J.tool_listar_janelas(), J.tool_janela("focar", "x"),
                J.tool_posicionar_janela("esquerda", "x"),
                J.tool_digitar("oi"), J.tool_atalho("ctrl+c"),
            ):
                self.assertIn("janelas", resposta)

    def test_sem_modulo_de_documentos_explica(self):
        with mock.patch.object(J, "nebell_docs", None):
            self.assertIn("documentos", J.tool_resumir_documento("x.pdf"))
            self.assertIn("documentos", J.tool_procurar_no_documento("x"))

    def test_fora_do_windows_a_janela_recusa(self):
        if not J.IS_WINDOWS:
            self.assertIn("Windows", J.tool_listar_janelas())

    def test_editar_imagem_respeita_a_protecao(self):
        resposta = J.tool_editar_imagem(
            str(caminho_de_sistema()), "cinza"
        )
        self.assertNotIn("Gravei", resposta)

    def test_resumir_documento_respeita_a_protecao(self):
        resposta = J.tool_resumir_documento(str(caminho_de_sistema()))
        self.assertNotIn("Resuma", resposta)

    def test_resumir_documento_monta_o_pedido(self):
        alvo = J.WORKSPACE_DIR / "nota.txt"
        alvo.write_text("o prazo é novembro", encoding="utf-8")

        resposta = J.tool_resumir_documento(str(alvo))
        self.assertIn("novembro", resposta)
        self.assertIn("Resuma", resposta)

    def test_resumir_com_pergunta(self):
        alvo = J.WORKSPACE_DIR / "nota2.txt"
        alvo.write_text("o prazo é novembro", encoding="utf-8")

        resposta = J.tool_resumir_documento(str(alvo), "qual o prazo?")
        self.assertIn("qual o prazo?", resposta)

    def test_documento_inexistente(self):
        resposta = J.tool_resumir_documento(
            str(J.WORKSPACE_DIR / "nao_existe.pdf")
        )
        self.assertIn("não", resposta.lower())

    def test_procurar_sem_documento_aberto(self):
        J.guardar_documento_em_foco({})
        self.assertIn("documento", J.tool_procurar_no_documento("prazo"))

    def test_procurar_no_documento_lido(self):
        alvo = J.WORKSPACE_DIR / "nota3.txt"
        alvo.write_text("o prazo é novembro e o valor é 300", encoding="utf-8")

        J.tool_resumir_documento(str(alvo))
        resposta = J.tool_procurar_no_documento("prazo")
        self.assertIn("novembro", resposta)

    def test_procurar_termo_ausente(self):
        alvo = J.WORKSPACE_DIR / "nota4.txt"
        alvo.write_text("o prazo é novembro", encoding="utf-8")

        J.tool_resumir_documento(str(alvo))
        self.assertIn("não aparece", J.tool_procurar_no_documento("foguete"))

    def test_documento_lido_fica_registrado_na_memoria(self):
        alvo = J.WORKSPACE_DIR / "nota5.txt"
        alvo.write_text("conteudo qualquer", encoding="utf-8")

        J.tool_resumir_documento(str(alvo))
        self.assertTrue(J.memoria.buscar_arquivos("nota5", limite=5))


class TestSentinelaLigada(NebellTest):
    def tearDown(self):
        if J.sentinela is not None:
            J.sentinela.parar()

        J.sentinela = None

    def test_estado_da_maquina_e_falavel(self):
        texto = J.tool_estado_maquina()
        self.assertIsInstance(texto, str)
        self.assertTrue(texto)

    def test_atalho_local_responde_o_estado(self):
        resposta = J.local_fast_answer("como esta minha maquina")
        self.assertIsNotNone(resposta)

    def test_sem_modulo_explica(self):
        with mock.patch.object(J, "nebell_sentinela", None):
            self.assertIn("monitoramento", J.tool_estado_maquina())

    def test_iniciar_e_parar(self):
        self.assertTrue(J.iniciar_sentinela())
        self.assertTrue(J.sentinela.ligada)

        J.fechar_extras()
        self.assertFalse(J.sentinela.ligada)

    def test_perfil_estudo_desliga_a_vigilancia(self):
        J.iniciar_sentinela()
        J.perfil_atual = "equilibrado"

        with mock.patch.object(J.threading, "Thread"):
            J.aplicar_perfil("estudo")

        self.assertFalse(J.sentinela.ligada)
        J.perfil_atual = "equilibrado"


class TestDiagnostico(NebellTest):
    def test_lista_os_modulos(self):
        texto = J.tool_diagnostico()

        for nome in ("nebell_audio", "nebell_memoria", "nebell_agenda",
                     "nebell_visao", "nebell_janela", "nebell_docs",
                     "nebell_sentinela"):
            self.assertIn(nome, texto)

    def test_mostra_o_modelo_e_o_perfil(self):
        texto = J.tool_diagnostico()
        self.assertIn(J.MODEL_NAME, texto)
        self.assertIn(J.perfil_atual, texto)

    def test_aponta_modulo_faltando(self):
        with mock.patch.object(J, "nebell_visao", None):
            self.assertIn("FALTANDO", J.tool_diagnostico())

    def test_atalho_local(self):
        self.assertIsNotNone(J.local_fast_answer("faz um diagnostico"))


# ============================================================
# LIBERAR A MAQUINA
# ============================================================

class RespostaFalsa:
    """Imita o que o requests devolve, com o json que a gente quiser."""

    def __init__(self, dados=None):
        self._dados = dados if dados is not None else {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._dados


class ProcessoFalso:
    def __init__(self, morto=False):
        self.morto = morto
        self.pedidos = []

    def poll(self):
        return 0 if self.morto else None

    def terminate(self):
        self.pedidos.append("terminate")
        self.morto = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.pedidos.append("kill")
        self.morto = True


class OllamaFalso:
    """
    Um Ollama de mentira que de fato responde /api/ps e descarrega.

    Serve para o teste cobrar o resultado (a placa ficou livre?) e nao
    apenas que a chamada aconteceu.
    """

    def __init__(self, carregado=True):
        self.carregado = carregado
        self.descarregou = []

    def get(self, url, timeout=None, **kwargs):
        if "/api/ps" in url:
            modelos = (
                [{"name": J.MODEL_NAME, "size_vram": 3_100_000_000}]
                if self.carregado else []
            )
            return RespostaFalsa({"models": modelos})

        return RespostaFalsa({"models": [{"name": J.MODEL_NAME}]})

    def post(self, url, json=None, timeout=None, **kwargs):
        if json and json.get("keep_alive") == 0:
            self.descarregou.append(json.get("model"))
            self.carregado = False

        return RespostaFalsa({})


class LiberarTest(NebellTest):
    def setUp(self):
        super().setUp()
        self.ollama = OllamaFalso()
        J.ollama_nosso[0] = None
        J.ollama_estava_de_pe[0] = False
        J.encerramento_feito.clear()
        J.maquina_liberada.clear()
        J.whisper_soltado[0] = False

    def falando_com_ollama(self):
        return mock.patch.multiple(
            J.session, get=self.ollama.get, post=self.ollama.post
        )


class TestModelosCarregados(LiberarTest):
    def test_le_o_que_esta_na_placa(self):
        with self.falando_com_ollama():
            carregados = J.modelos_carregados()

        self.assertEqual(len(carregados), 1)
        nome, megabytes = carregados[0]
        self.assertEqual(nome, J.MODEL_NAME)
        self.assertGreater(megabytes, 2000)

    def test_placa_vazia(self):
        self.ollama.carregado = False

        with self.falando_com_ollama():
            self.assertEqual(J.modelos_carregados(), [])

    def test_ollama_sem_resposta_nao_estoura(self):
        def recusar(*a, **k):
            raise OSError("sem conexão")

        with mock.patch.object(J.session, "get", recusar):
            self.assertEqual(J.modelos_carregados(), [])


class TestDescarregarModelo(LiberarTest):
    def test_solta_a_vram_e_confere(self):
        with self.falando_com_ollama():
            deu_certo, mensagem = J.descarregar_modelo()

        self.assertTrue(deu_certo)
        self.assertIn(J.MODEL_NAME, mensagem)
        self.assertEqual(self.ollama.descarregou, [J.MODEL_NAME])
        self.assertFalse(self.ollama.carregado)

    def test_usa_keep_alive_zero(self):
        enviados = []

        def anotar(url, json=None, timeout=None, **kwargs):
            enviados.append(json)
            self.ollama.carregado = False
            return RespostaFalsa({})

        with mock.patch.multiple(
            J.session, get=self.ollama.get, post=anotar
        ):
            J.descarregar_modelo()

        self.assertEqual(enviados[0]["keep_alive"], 0)

    def test_placa_ja_livre(self):
        self.ollama.carregado = False

        with self.falando_com_ollama():
            deu_certo, mensagem = J.descarregar_modelo()

        self.assertTrue(deu_certo)
        self.assertIn("já estava livre", mensagem)

    def test_sem_ollama_nao_tenta(self):
        with mock.patch.object(J, "ollama_vivo", lambda timeout=2: False):
            deu_certo, mensagem = J.descarregar_modelo()

        self.assertFalse(deu_certo)
        self.assertEqual(self.ollama.descarregou, [])

    def test_modelo_que_nao_solta_e_denunciado(self):
        # O Ollama responde, mas o modelo continua aparecendo: nao vale
        # dizer que liberou.
        def nao_solta(url, json=None, timeout=None, **kwargs):
            return RespostaFalsa({})

        with mock.patch.multiple(
            J.session, get=self.ollama.get, post=nao_solta
        ), mock.patch.object(J.time, "sleep", lambda s: None):
            deu_certo, mensagem = J.descarregar_modelo()

        self.assertFalse(deu_certo)
        self.assertIn("ainda aparece", mensagem)

    def test_erro_de_rede_vira_mensagem(self):
        def recusar(*a, **k):
            raise OSError("caiu")

        with mock.patch.multiple(
            J.session, get=self.ollama.get, post=recusar
        ):
            deu_certo, mensagem = J.descarregar_modelo()

        self.assertFalse(deu_certo)
        self.assertIn("Não consegui", mensagem)


class TestPararOllama(LiberarTest):
    def test_modo_nunca(self):
        parou, mensagem = J.parar_ollama("nunca")
        self.assertFalse(parou)
        self.assertIn("de pé", mensagem)

    def test_modo_se_eu_abri_respeita_o_ollama_de_outro(self):
        J.ollama_estava_de_pe[0] = True
        parou, mensagem = J.parar_ollama("se_eu_abri")
        self.assertFalse(parou)
        self.assertIn("já estava aberto", mensagem)

    def test_encerra_o_processo_que_abrimos(self):
        processo = ProcessoFalso()
        J.ollama_nosso[0] = processo

        parou, mensagem = J.parar_ollama("sempre")

        self.assertTrue(parou)
        self.assertIn("terminate", processo.pedidos)
        self.assertIsNone(J.ollama_nosso[0])

    def test_mata_se_o_terminate_nao_resolver(self):
        class Teimoso(ProcessoFalso):
            def wait(self, timeout=None):
                raise RuntimeError("não morreu")

        processo = Teimoso()
        J.ollama_nosso[0] = processo

        parou, _ = J.parar_ollama("sempre")

        self.assertTrue(parou)
        self.assertIn("kill", processo.pedidos)

    def test_processo_ja_morto_cai_no_taskkill(self):
        J.ollama_nosso[0] = ProcessoFalso(morto=True)
        chamadas = []

        def falso_run(comando, **kwargs):
            chamadas.append(comando)
            return mock.Mock(returncode=0)

        with mock.patch.object(J, "IS_WINDOWS", True), \
                mock.patch.object(J.subprocess, "run", falso_run):
            parou, _ = J.parar_ollama("sempre")

        self.assertTrue(parou)
        self.assertTrue(any("taskkill" in c[0] for c in chamadas))

    def test_taskkill_fecha_o_icone_antes_do_servidor(self):
        # O "ollama app.exe" torna a subir o servidor se ficar vivo,
        # entao ele tem de cair primeiro.
        alvos = []

        def falso_run(comando, **kwargs):
            alvos.append(comando[2])
            return mock.Mock(returncode=0)

        with mock.patch.object(J, "IS_WINDOWS", True), \
                mock.patch.object(J.subprocess, "run", falso_run):
            J.parar_ollama("sempre")

        self.assertEqual(alvos, ["ollama app.exe", "ollama.exe"])

    def test_nada_rodando(self):
        with mock.patch.object(J, "IS_WINDOWS", True), \
                mock.patch.object(
                    J.subprocess, "run",
                    lambda *a, **k: mock.Mock(returncode=128)
                ):
            parou, mensagem = J.parar_ollama("sempre")

        self.assertFalse(parou)
        self.assertIn("Não achei", mensagem)

    def test_fora_do_windows_nao_mata_nada(self):
        with mock.patch.object(J, "IS_WINDOWS", False):
            parou, mensagem = J.parar_ollama("sempre")

        self.assertFalse(parou)

    def test_se_eu_abri_sem_o_processo_em_maos(self):
        parou, mensagem = J.parar_ollama("se_eu_abri")
        self.assertFalse(parou)
        self.assertIn("processo", mensagem)


class TestLiberarWhisper(LiberarTest):
    def tearDown(self):
        J.whisper_model = None
        J.whisper_soltado[0] = False

    def test_sem_modelo_nao_faz_nada(self):
        J.whisper_model = None
        self.assertFalse(J.liberar_whisper())

    def test_solta_e_marca_para_recarregar(self):
        J.whisper_model = object()

        self.assertTrue(J.liberar_whisper())
        self.assertIsNone(J.whisper_model)
        self.assertTrue(J.whisper_soltado[0])
        self.assertFalse(J.whisper_ready.is_set())

    def test_a_escuta_volta_na_proxima_fala(self):
        J.whisper_model = object()
        J.liberar_whisper()

        criadas = []

        class ThreadFalsa:
            def __init__(self, target=None, daemon=None, **kwargs):
                criadas.append(target)

            def start(self):
                pass

        with mock.patch.object(J.threading, "Thread", ThreadFalsa), \
                mock.patch.object(J, "get_recognizer", lambda: None), \
                mock.patch.object(J, "WHISPER_WAIT_SECONDS", 0):
            try:
                J.transcribe(b"audio")
            except Exception:
                pass

        self.assertIn(J.load_whisper, criadas)
        self.assertFalse(J.whisper_soltado[0])


class TestLiberarMaquina(LiberarTest):
    def test_solta_a_placa_sem_derrubar_o_ollama(self):
        with self.falando_com_ollama():
            feito = J.liberar_maquina(derrubar_ollama=False)

        self.assertTrue(self.ollama.descarregou)
        self.assertTrue(J.maquina_liberada.is_set())
        self.assertTrue(any("placa" in f for f in feito))

    def test_derruba_o_ollama_quando_pedido(self):
        processo = ProcessoFalso()
        J.ollama_nosso[0] = processo

        with self.falando_com_ollama():
            feito = J.liberar_maquina(derrubar_ollama=True)

        self.assertIn("terminate", processo.pedidos)
        self.assertTrue(any("Ollama" in f for f in feito))

    def test_configuracao_desligada_nao_descarrega(self):
        with mock.patch.object(J, "DESCARREGAR_MODELO_AO_SAIR", False), \
                self.falando_com_ollama():
            J.liberar_maquina(derrubar_ollama=False)

        self.assertEqual(self.ollama.descarregou, [])

    def test_a_ferramenta_conta_quanto_soltou(self):
        with self.falando_com_ollama():
            resposta = J.tool_liberar_maquina("nao")

        self.assertIn("megabytes", resposta)

    def test_a_ferramenta_fecha_o_ollama_por_padrao(self):
        processo = ProcessoFalso()
        J.ollama_nosso[0] = processo

        with self.falando_com_ollama():
            resposta = J.tool_liberar_maquina()

        self.assertIn("terminate", processo.pedidos)
        self.assertIn("próxima pergunta", resposta)

    def test_a_ferramenta_respeita_o_nao(self):
        processo = ProcessoFalso()
        J.ollama_nosso[0] = processo

        with self.falando_com_ollama():
            J.tool_liberar_maquina("não")

        self.assertEqual(processo.pedidos, [])

    def test_atalho_local_libera(self):
        with self.falando_com_ollama():
            resposta = J.local_fast_answer("libera a placa de video")

        self.assertIsNotNone(resposta)
        self.assertTrue(self.ollama.descarregou)

    def test_atalho_local_fecha_o_ollama(self):
        with self.falando_com_ollama():
            resposta = J.local_fast_answer("fecha o ollama")

        self.assertIsNotNone(resposta)

    def test_pedido_comum_nao_cai_no_atalho(self):
        # "liberar" aparece em frases que nao tem nada a ver com a placa.
        for frase in ("quem libertou os escravos", "libera meu acesso",
                      "o que e memoria ram"):
            with self.falando_com_ollama():
                self.assertIsNone(
                    J.local_fast_answer(frase), frase
                )


class TestEncerrar(LiberarTest):
    def setUp(self):
        super().setUp()
        self.chamados = []

    def espionar(self):
        """Troca cada passo do encerramento por um que apenas anota."""
        def anotar(nome, devolve=None):
            def passo(*a, **k):
                self.chamados.append(nome)
                return devolve

            return passo

        return mock.patch.multiple(
            J,
            wait_for_speech=anotar("fala"),
            fechar_extras=anotar("extras"),
            fechar_memoria=anotar("memoria"),
            close_microphone=anotar("microfone"),
            fechar_audio=anotar("audio"),
            limpar_audios_temporarios=anotar("temporarios"),
            liberar_maquina=anotar("maquina", []),
        )

    def test_passa_por_todos_os_passos(self):
        with self.espionar():
            J.encerrar()

        for passo in ("fala", "extras", "memoria", "microfone", "audio",
                      "temporarios", "maquina"):
            self.assertIn(passo, self.chamados)

    def test_a_placa_e_liberada_por_ultimo(self):
        with self.espionar():
            J.encerrar()

        self.assertEqual(self.chamados[-1], "maquina")

    def test_a_memoria_fecha_antes_da_placa(self):
        # O resumo da sessao tem de ser gravado antes de derrubar nada.
        with self.espionar():
            J.encerrar()

        self.assertLess(
            self.chamados.index("memoria"), self.chamados.index("maquina")
        )

    def test_nao_encerra_duas_vezes(self):
        with self.espionar():
            J.encerrar()
            J.encerrar()

        self.assertEqual(self.chamados.count("maquina"), 1)

    def test_um_passo_que_falha_nao_impede_os_outros(self):
        def explodir(*a, **k):
            raise RuntimeError("quebrou")

        with self.espionar(), mock.patch.object(
            J, "fechar_memoria", explodir
        ):
            J.encerrar()

        # O que importa: a placa foi liberada mesmo assim.
        self.assertIn("maquina", self.chamados)

    def test_a_placa_e_liberada_mesmo_se_tudo_falhar(self):
        def explodir(*a, **k):
            raise RuntimeError("quebrou")

        with mock.patch.multiple(
            J,
            wait_for_speech=explodir,
            fechar_extras=explodir,
            fechar_memoria=explodir,
            close_microphone=explodir,
            fechar_audio=explodir,
            limpar_audios_temporarios=explodir,
        ), self.falando_com_ollama():
            J.encerrar()

        self.assertTrue(self.ollama.descarregou)

    def test_marca_o_encerramento(self):
        with self.espionar():
            J.encerrar()

        self.assertTrue(J.encerramento_feito.is_set())
        self.assertTrue(J.shutdown_event.is_set())

    def test_espera_as_threads_que_recebeu(self):
        class ThreadFalsa:
            def __init__(self):
                self.esperou = False

            def join(self, timeout=None):
                self.esperou = True

        uma, outra = ThreadFalsa(), ThreadFalsa()

        with self.espionar():
            J.encerrar((uma, outra, None))

        self.assertTrue(uma.esperou)
        self.assertTrue(outra.esperou)

    def test_thread_que_nao_termina_nao_trava_o_resto(self):
        class Travada:
            def join(self, timeout=None):
                raise RuntimeError("não terminou")

        with self.espionar():
            J.encerrar((Travada(),))

        self.assertIn("maquina", self.chamados)

    def test_configuracao_nunca_deixa_o_ollama_de_pe(self):
        processo = ProcessoFalso()
        J.ollama_nosso[0] = processo

        with mock.patch.object(J, "PARAR_OLLAMA_AO_SAIR", "nunca"), \
                self.falando_com_ollama(), \
                mock.patch.object(J, "wait_for_speech", lambda *a: None), \
                mock.patch.object(J, "fechar_memoria", lambda *a: None), \
                mock.patch.object(J, "close_microphone", lambda *a: None), \
                mock.patch.object(J, "fechar_audio", lambda *a: None), \
                mock.patch.object(
                    J, "limpar_audios_temporarios", lambda *a: None):
            J.encerrar()

        self.assertEqual(processo.pedidos, [])
        self.assertTrue(self.ollama.descarregou)


class TestOllamaFoiNosso(NebellTest):
    def setUp(self):
        super().setUp()
        J.ollama_nosso[0] = None
        J.ollama_estava_de_pe[0] = False

    def test_ollama_ja_de_pe_e_anotado(self):
        with mock.patch.object(J, "ollama_vivo", lambda *a, **k: True):
            self.assertTrue(J.garantir_ollama())

        self.assertTrue(J.ollama_estava_de_pe[0])
        self.assertIsNone(J.ollama_nosso[0])

    def test_guarda_o_processo_que_abriu(self):
        processo = ProcessoFalso()
        vivo = {"agora": False}

        def abrir(comando, **kwargs):
            vivo["agora"] = True
            return processo

        with mock.patch.object(
            J, "ollama_vivo", lambda *a, **k: vivo["agora"]
        ), mock.patch.object(J.subprocess, "Popen", abrir):
            J.garantir_ollama(espera=2)

        self.assertIs(J.ollama_nosso[0], processo)
        self.assertFalse(J.ollama_estava_de_pe[0])


# ============================================================
# PERFIL E SENTINELA JUNTOS
# ============================================================

class TestPerfilEIntervaloDaSentinela(NebellTest):
    def setUp(self):
        super().setUp()
        self.perfil_antes = J.perfil_atual
        J.perfil_atual = "equilibrado"

    def tearDown(self):
        J.perfil_atual = self.perfil_antes

        if J.sentinela is not None:
            J.sentinela.parar()

        J.sentinela = None

    def test_todo_perfil_diz_o_intervalo(self):
        for nome, dados in J.PERFIS.items():
            self.assertIn("sentinela_intervalo", dados, nome)
            self.assertGreaterEqual(dados["sentinela_intervalo"], 60, nome)

    def test_modo_jogo_espaca_a_vigilancia(self):
        self.assertGreater(
            J.PERFIS["jogo"]["sentinela_intervalo"],
            J.PERFIS["equilibrado"]["sentinela_intervalo"],
        )

    def test_trocar_de_perfil_ajusta_o_intervalo(self):
        J.iniciar_sentinela()

        with mock.patch.object(J.threading, "Thread"):
            J.aplicar_perfil("jogo")

        self.assertEqual(
            J.sentinela.intervalo, J.PERFIS["jogo"]["sentinela_intervalo"]
        )


class TestPainelDaHud(NebellTest):
    def setUp(self):
        super().setUp()
        self.antes = J.hud

    def tearDown(self):
        J.hud = self.antes

    def hud_falsa(self, ativa=True):
        falsa = mock.Mock()
        falsa.active = ativa
        J.hud = falsa
        return falsa

    def test_sem_hud_nao_faz_nada(self):
        J.hud = None
        J.atualizar_estatisticas(uma_vez=True)       # nao pode estourar

    def test_alimenta_o_painel(self):
        falsa = self.hud_falsa()

        with mock.patch.object(J, "medir_latencia", lambda: (20, 95)):
            J.atualizar_estatisticas(uma_vez=True)

        falsa.set_stats.assert_called_once()

    def test_janela_escondida_nao_chama_a_nvidia_smi(self):
        self.hud_falsa(ativa=False)
        chamadas = []

        with mock.patch.object(
            J, "coletar_estatisticas", lambda: chamadas.append(1) or {}
        ), mock.patch.object(J, "medir_latencia", lambda: (20, 95)):
            # Uma volta so: com a janela escondida ele espera e volta.
            J.shutdown_event.set()
            J.atualizar_estatisticas()
            J.shutdown_event.clear()

        self.assertEqual(chamadas, [])

    def test_uma_vez_coleta_mesmo_com_a_janela_escondida(self):
        # O painel e preenchido uma vez na abertura, antes de a janela
        # se declarar ativa.
        self.hud_falsa(ativa=False)

        with mock.patch.object(J, "medir_latencia", lambda: (20, 95)):
            J.atualizar_estatisticas(uma_vez=True)

        J.hud.set_stats.assert_called_once()

    def test_todo_perfil_diz_o_intervalo_do_painel(self):
        for nome, dados in J.PERFIS.items():
            self.assertIn("painel_intervalo", dados, nome)
            self.assertGreaterEqual(dados["painel_intervalo"], 4, nome)

    def test_modo_jogo_atualiza_o_painel_menos_vezes(self):
        self.assertGreater(
            J.PERFIS["jogo"]["painel_intervalo"],
            J.PERFIS["equilibrado"]["painel_intervalo"],
        )

    def test_latencia_usa_a_sessao_e_nao_abre_conexao_nova(self):
        with mock.patch.object(J.session, "get") as pedido:
            J.medir_latencia()

        pedido.assert_called_once()

    def test_latencia_sem_rede(self):
        def recusar(*a, **k):
            raise OSError("sem rede")

        with mock.patch.object(J.session, "get", recusar):
            ms, qualidade = J.medir_latencia()

        self.assertIsNone(ms)
        self.assertEqual(qualidade, 0)


# ============================================================
# PEDIDO DE ENCERRAR
# ============================================================

class TestPedidoDeEncerrar(NebellTest):
    def test_a_palavra_sozinha(self):
        for frase in ("encerrar", "encerra", "encerre", "sair", "sai",
                      "finalizar", "tchau", "adeus", "fecha", "desliga"):
            self.assertTrue(J.pedido_de_encerrar(frase), frase)

    def test_sem_o_r_no_fim(self):
        # "encerra" e "encerre" sao o que mais sai na fala, e eram
        # justamente os que nao casavam.
        self.assertTrue(J.pedido_de_encerrar("encerra"))
        self.assertTrue(J.pedido_de_encerrar("encerre"))

    def test_com_as_pontas_da_fala(self):
        for frase in ("ta bom, encerrar", "tá bom, encerrar",
                      "ok encerrar", "pode encerrar", "encerrar por favor",
                      "nebell, encerrar", "ja pode encerrar o nebell",
                      "então encerra aí", "beleza, pode fechar"):
            self.assertTrue(J.pedido_de_encerrar(frase), frase)

    def test_despedidas(self):
        for frase in ("ate mais", "até logo", "boa noite"):
            self.assertTrue(J.pedido_de_encerrar(frase), frase)

    def test_comandos_de_barra(self):
        for frase in ("/sair", "/encerrar", "/exit", "/fechar"):
            self.assertTrue(J.pedido_de_encerrar(frase), frase)

    def test_outra_coisa_que_se_desliga(self):
        # Este e o risco real do conserto: "desliga" e "fecha" valem
        # para muita coisa que nao e o programa.
        for frase in ("desliga o bluetooth", "desligar o wifi",
                      "desliga o computador", "fecha a janela do brave",
                      "fecha essa aba", "fecha o spotify",
                      "fecha o arquivo", "encerra o processo do ollama",
                      "fecha o jogo", "desliga o monitor",
                      "desliga o volume"):
            self.assertFalse(J.pedido_de_encerrar(frase), frase)

    def test_pergunta_sobre_encerrar_nao_encerra(self):
        for frase in ("como encerrar um processo no windows",
                      "o que e encerrar", "por que encerrar o ollama"):
            self.assertFalse(J.pedido_de_encerrar(frase), frase)

    def test_frase_comum_com_a_palavra_dentro(self):
        for frase in ("de onde sai o dinheiro do governo",
                      "qual horario que sai o jogo hoje",
                      "me fala sobre o fechamento da bolsa",
                      "qual a capital do para"):
            self.assertFalse(J.pedido_de_encerrar(frase), frase)

    def test_vazio(self):
        self.assertFalse(J.pedido_de_encerrar(""))
        self.assertFalse(J.pedido_de_encerrar(None))

    def test_o_menu_usa_o_mesmo_reconhecedor(self):
        self.assertEqual(J.parse_mode_choice("encerra"), "exit")
        self.assertEqual(J.parse_mode_choice("ta bom, encerrar"), "exit")

    def test_o_modo_voz_usa_o_mesmo_reconhecedor(self):
        self.assertEqual(J.parse_voice_command("encerra"), "exit")
        self.assertEqual(J.parse_voice_command("tchau"), "exit")

    def test_o_menu_nao_confunde_com_a_escolha_de_modo(self):
        self.assertEqual(J.parse_mode_choice("voz"), "voice")
        self.assertEqual(J.parse_mode_choice("texto"), "text")

    def test_a_janela_encerra_com_texto_digitado(self):
        # O bug: digitar "encerrar" na HUD virava mensagem para o
        # modelo e o programa seguia aberto.
        J.shutdown_event.clear()
        J.drain(J.request_queue)
        J.request_queue.put(("hud", "encerrar"))

        atendidos = []

        with mock.patch.object(
            J, "ask_nebell", lambda t: atendidos.append(t)
        ), mock.patch.object(J, "wait_for_speech", lambda: None), \
                mock.patch.object(J, "hud", None):
            J.dispatcher_loop()

        self.assertEqual(atendidos, [])
        self.assertTrue(J.shutdown_event.is_set())
        J.shutdown_event.clear()

    def test_a_janela_atende_o_resto_normalmente(self):
        J.shutdown_event.clear()
        J.drain(J.request_queue)
        J.request_queue.put(("hud", "que horas são"))

        atendidos = []

        def atender(texto):
            atendidos.append(texto)
            J.shutdown_event.set()

        with mock.patch.object(J, "ask_nebell", atender), \
                mock.patch.object(J, "hud", None):
            J.dispatcher_loop()

        self.assertEqual(atendidos, ["que horas são"])
        J.shutdown_event.clear()


# ============================================================
# ONDE GRAVAR
# ============================================================

class TestPastasDoUsuario(NebellTest):
    def test_nomes_falados_viram_pastas_reais(self):
        casa = Path.home()

        for falado, esperado in (
            ("downloads", "Downloads"),
            ("Downloads", "Downloads"),
            ("area de trabalho", "Desktop"),
            ("Área de Trabalho", "Desktop"),
            ("desktop", "Desktop"),
            ("documentos", "Documents"),
            ("imagens", "Pictures"),
            ("fotos", "Pictures"),
        ):
            destino = J.pasta_do_usuario(falado)
            self.assertIsNotNone(destino, falado)
            self.assertIn(
                esperado.lower(), str(destino).lower(), falado
            )

    def test_pasta_pessoal(self):
        self.assertEqual(J.pasta_do_usuario("casa"), Path.home())

    def test_nome_desconhecido(self):
        self.assertIsNone(J.pasta_do_usuario("pasta do zeca"))
        self.assertIsNone(J.pasta_do_usuario(""))

    def test_prefere_o_onedrive_quando_existe(self):
        # Com o OneDrive ligado, a Area de Trabalho de verdade fica
        # dentro dele; a de fora pode nem existir.
        casa = Path(tempfile.mkdtemp(prefix="nebell_casa_"))
        (casa / "OneDrive" / "Desktop").mkdir(parents=True)
        (casa / "Desktop").mkdir()

        with mock.patch.object(J.Path, "home", staticmethod(lambda: casa)):
            destino = J.pasta_do_usuario("area de trabalho")

        self.assertEqual(destino, casa / "OneDrive" / "Desktop")

    def test_onedrive_da_empresa_tambem_conta(self):
        casa = Path(tempfile.mkdtemp(prefix="nebell_casa_"))
        (casa / "OneDrive - Empresa" / "Documents").mkdir(parents=True)

        with mock.patch.object(J.Path, "home", staticmethod(lambda: casa)):
            destino = J.pasta_do_usuario("documentos")

        self.assertEqual(destino, casa / "OneDrive - Empresa" / "Documents")

    def test_pasta_que_nao_existe_ainda_vem_da_pasta_pessoal(self):
        casa = Path(tempfile.mkdtemp(prefix="nebell_casa_"))

        with mock.patch.object(J.Path, "home", staticmethod(lambda: casa)):
            destino = J.pasta_do_usuario("downloads")

        self.assertEqual(destino, casa / "Downloads")


class TestResolverCaminho(NebellTest):
    def test_nome_de_pasta_conhecida(self):
        self.assertEqual(
            J.resolve_path("downloads"), J.pasta_do_usuario("downloads")
        )

    def test_pasta_conhecida_com_arquivo(self):
        self.assertEqual(
            J.resolve_path("downloads/nota.txt"),
            J.pasta_do_usuario("downloads") / "nota.txt",
        )

    def test_aceita_barra_invertida_do_windows(self):
        self.assertEqual(
            J.resolve_path(r"downloads\nota.txt"),
            J.pasta_do_usuario("downloads") / "nota.txt",
        )

    def test_frase_inteira_como_caminho(self):
        # O modelo as vezes manda "na pasta downloads" no argumento.
        for frase in ("na pasta downloads", "em Downloads",
                      "pra pasta de downloads",
                      "na minha pasta de downloads"):
            self.assertEqual(
                J.resolve_path(frase), J.pasta_do_usuario("downloads"), frase
            )

    def test_area_de_trabalho_com_subpasta(self):
        self.assertEqual(
            J.resolve_path("area de trabalho/Projetos"),
            J.pasta_do_usuario("area de trabalho") / "Projetos",
        )

    def test_caminho_absoluto_manda(self):
        alvo = caminho_de_sistema()
        self.assertEqual(J.resolve_path(str(alvo)), alvo)

    def test_til_vira_pasta_pessoal(self):
        self.assertEqual(
            J.resolve_path("~/teste.txt"), Path.home() / "teste.txt"
        )

    def test_nome_solto_fica_na_pasta_de_trabalho(self):
        # Sem nenhuma pista de lugar, a pasta do NEBELL continua certa.
        self.assertEqual(
            J.resolve_path("nota.txt"), J.WORKSPACE_DIR / "nota.txt"
        )

    def test_subpasta_desconhecida_fica_na_pasta_de_trabalho(self):
        self.assertEqual(
            J.resolve_path("relatorios/final.txt"),
            J.WORKSPACE_DIR / "relatorios" / "final.txt",
        )

    def test_vazio_vira_a_pasta_de_trabalho(self):
        self.assertEqual(J.resolve_path(""), J.WORKSPACE_DIR)

    def test_tira_as_aspas_que_o_modelo_manda(self):
        self.assertEqual(
            J.resolve_path('"downloads/nota.txt"'),
            J.pasta_do_usuario("downloads") / "nota.txt",
        )

    def test_o_prompt_diz_as_pastas_reais(self):
        prompt = J.build_system_prompt()
        self.assertIn("ONDE GRAVAR", prompt)
        self.assertIn(str(J.pasta_do_usuario("downloads")), prompt)
        self.assertIn("criar_pasta", prompt)


class TestCriarPasta(NebellTest):
    def test_cria_de_verdade_uma_pasta(self):
        alvo = J.WORKSPACE_DIR / "pasta_nova"

        with mock.patch.object(J, "confirm_action", return_value=True):
            resposta = J.tool_criar_pasta(str(alvo))

        self.assertTrue(alvo.is_dir())
        self.assertIn("Pasta criada", resposta)

    def test_cria_com_pastas_intermediarias(self):
        alvo = J.WORKSPACE_DIR / "a" / "b" / "c"

        with mock.patch.object(J, "confirm_action", return_value=True):
            J.tool_criar_pasta(str(alvo))

        self.assertTrue(alvo.is_dir())

    def test_entende_o_nome_falado_do_lugar(self):
        casa = Path(tempfile.mkdtemp(prefix="nebell_casa_"))

        with mock.patch.object(J.Path, "home", staticmethod(lambda: casa)), \
                mock.patch.object(J, "confirm_action", return_value=True):
            resposta = J.tool_criar_pasta("area de trabalho/Projetos")

        self.assertTrue((casa / "Desktop" / "Projetos").is_dir())
        self.assertIn("Projetos", resposta)

    def test_pasta_que_ja_existe(self):
        with mock.patch.object(J, "confirm_action", return_value=True):
            resposta = J.tool_criar_pasta(str(J.WORKSPACE_DIR))

        self.assertIn("já existe", resposta)

    def test_nome_ocupado_por_arquivo(self):
        arquivo = J.WORKSPACE_DIR / "ocupado.txt"
        arquivo.write_text("x", encoding="utf-8")

        with mock.patch.object(J, "confirm_action", return_value=True):
            resposta = J.tool_criar_pasta(str(arquivo))

        self.assertIn("arquivo", resposta)

    def test_respeita_o_nao_do_usuario(self):
        alvo = J.WORKSPACE_DIR / "negada"

        with mock.patch.object(J, "confirm_action", return_value=False):
            resposta = J.tool_criar_pasta(str(alvo))

        self.assertFalse(alvo.exists())
        self.assertIn("negou", resposta)

    def test_respeita_a_protecao_do_sistema(self):
        with mock.patch.object(J, "confirm_action", return_value=True):
            resposta = J.tool_criar_pasta(str(caminho_de_sistema() / "x"))

        self.assertNotIn("Pasta criada", resposta)

    def test_a_ferramenta_esta_registrada(self):
        self.assertIn("criar_pasta", J.TOOL_FUNCTIONS)
        self.assertIn(
            "criar_pasta",
            {e["function"]["name"] for e in J.TOOL_SCHEMAS},
        )

    def test_o_pedido_de_pasta_traz_a_ferramenta_certa(self):
        escolhidas = [
            e["function"]["name"] for e in J.selecionar_ferramentas(
                "cria uma pasta na area de trabalho chamada Projetos"
            )
        ]
        self.assertIn("criar_pasta", escolhidas)


# ============================================================
# CRIAR ARQUIVO DE QUALQUER TIPO
# ============================================================

class TestExtensaoPedida(NebellTest):
    def test_nome_da_linguagem(self):
        for dito, esperado in (
            ("java", ".java"), ("python", ".py"), ("c#", ".cs"),
            ("c sharp", ".cs"), ("csharp", ".cs"), ("cpp", ".cpp"),
            ("c++", ".cpp"), ("c", ".c"), ("javascript", ".js"),
            ("typescript", ".ts"), ("html", ".html"), ("sql", ".sql"),
            ("rust", ".rs"), ("go", ".go"), ("kotlin", ".kt"),
            ("bash", ".sh"), ("powershell", ".ps1"), ("batch", ".bat"),
            ("arduino", ".ino"), ("markdown", ".md"),
        ):
            self.assertEqual(J.extensao_pedida(dito), esperado, dito)

    def test_formatos_de_escritorio(self):
        self.assertEqual(J.extensao_pedida("word"), ".docx")
        self.assertEqual(J.extensao_pedida("excel"), ".xlsx")
        self.assertEqual(J.extensao_pedida("planilha"), ".xlsx")
        self.assertEqual(J.extensao_pedida("powerpoint"), ".pptx")
        self.assertEqual(J.extensao_pedida("pdf"), ".pdf")

    def test_com_ponto_e_com_maiuscula(self):
        self.assertEqual(J.extensao_pedida(".java"), ".java")
        self.assertEqual(J.extensao_pedida("Java"), ".java")
        self.assertEqual(J.extensao_pedida("PYTHON"), ".py")

    def test_dentro_de_uma_frase(self):
        for dito in ("em Python", "arquivo C#", "um codigo cpp",
                     "classe java", "script em bash"):
            self.assertIsNotNone(J.extensao_pedida(dito), dito)

    def test_desconhecido(self):
        self.assertIsNone(J.extensao_pedida("banana"))
        self.assertIsNone(J.extensao_pedida(""))


class TestAjustarExtensao(NebellTest):
    def test_completa_pelo_tipo(self):
        self.assertEqual(
            J.ajustar_extensao(Path("/x/Pessoa"), "java"),
            Path("/x/Pessoa.java"),
        )

    def test_o_que_a_pessoa_falou_manda(self):
        # "um arquivo Java chamado nota.txt" tem de sair .java.
        self.assertEqual(
            J.ajustar_extensao(Path("/x/nota.txt"), "java"),
            Path("/x/nota.java"),
        )

    def test_mantem_a_extensao_quando_nao_ha_tipo(self):
        self.assertEqual(
            J.ajustar_extensao(Path("/x/script.py")), Path("/x/script.py")
        )

    def test_sem_nada_vira_txt(self):
        self.assertEqual(
            J.ajustar_extensao(Path("/x/notas")), Path("/x/notas.txt")
        )

    def test_tipo_desconhecido_nao_estraga_a_extensao(self):
        self.assertEqual(
            J.ajustar_extensao(Path("/x/script.py"), "banana"),
            Path("/x/script.py"),
        )


class TestClasseJava(NebellTest):
    def test_renomeia_o_arquivo_para_a_classe(self):
        path, aviso = J.conferir_classe_java(
            Path("/x/Errado.java"), "public class Certo { }"
        )
        self.assertEqual(path.name, "Certo.java")
        self.assertIn("Java", aviso)

    def test_nome_que_ja_casa_fica_quieto(self):
        path, aviso = J.conferir_classe_java(
            Path("/x/Aluno.java"), "public class Aluno { }"
        )
        self.assertEqual(path.name, "Aluno.java")
        self.assertEqual(aviso, "")

    def test_interface_e_enum_tambem(self):
        for codigo, esperado in (
            ("public interface Forma { }", "Forma.java"),
            ("public enum Cor { AZUL }", "Cor.java"),
            ("public record Ponto(int x, int y) { }", "Ponto.java"),
            ("public final class Util { }", "Util.java"),
            ("public abstract class Base { }", "Base.java"),
        ):
            path, _ = J.conferir_classe_java(Path("/x/Qualquer.java"), codigo)
            self.assertEqual(path.name, esperado, codigo)

    def test_classe_sem_public_nao_obriga_nada(self):
        path, aviso = J.conferir_classe_java(
            Path("/x/Qualquer.java"), "class Interna { }"
        )
        self.assertEqual(path.name, "Qualquer.java")

    def test_outras_linguagens_nao_sao_mexidas(self):
        path, aviso = J.conferir_classe_java(
            Path("/x/qualquer.py"), "class Outra: pass"
        )
        self.assertEqual(path.name, "qualquer.py")
        self.assertEqual(aviso, "")


class EscreverTest(NebellTest):
    def setUp(self):
        super().setUp()
        self.aceitar = mock.patch.object(
            J, "confirm_action", return_value=True
        )
        self.aceitar.start()

    def tearDown(self):
        self.aceitar.stop()

    def criar(self, caminho, conteudo="", tipo=""):
        return J.tool_escrever_arquivo(
            str(J.WORKSPACE_DIR / caminho), conteudo, tipo
        )


class TestEscreverCodigo(EscreverTest):
    def test_grava_python_que_roda(self):
        self.criar("calc.py", "print(2 + 2)")
        alvo = J.WORKSPACE_DIR / "calc.py"

        self.assertTrue(alvo.exists())
        self.assertEqual(alvo.read_text(encoding="utf-8"), "print(2 + 2)")

    def test_cada_linguagem_grava_com_a_sua_extensao(self):
        for tipo, extensao in (
            ("java", ".java"), ("python", ".py"), ("c#", ".cs"),
            ("cpp", ".cpp"), ("c", ".c"), ("javascript", ".js"),
            ("html", ".html"), ("sql", ".sql"), ("bash", ".sh"),
            ("powershell", ".ps1"),
        ):
            self.criar("Teste", "", tipo)
            self.assertTrue(
                (J.WORKSPACE_DIR / f"Teste{extensao}").exists(), tipo
            )

    def test_esqueleto_quando_nao_vem_conteudo(self):
        resposta = self.criar("Pessoa", "", "java")
        codigo = (J.WORKSPACE_DIR / "Pessoa.java").read_text(encoding="utf-8")

        self.assertIn("public class Pessoa", codigo)
        self.assertIn("esqueleto", resposta)

    def test_esqueleto_de_python_tem_o_guarda(self):
        self.criar("roda", "", "python")
        codigo = (J.WORKSPACE_DIR / "roda.py").read_text(encoding="utf-8")
        self.assertIn('if __name__ == "__main__":', codigo)

    def test_conteudo_dado_nao_e_trocado_por_esqueleto(self):
        self.criar("meu", "x = 1" + chr(10), "python")
        self.assertEqual(
            (J.WORKSPACE_DIR / "meu.py").read_text(encoding="utf-8"),
            "x = 1" + chr(10),
        )

    def test_java_renomeia_pela_classe(self):
        resposta = self.criar("Errado.java", "public class Certo { }")

        self.assertTrue((J.WORKSPACE_DIR / "Certo.java").exists())
        self.assertFalse((J.WORKSPACE_DIR / "Errado.java").exists())
        self.assertIn("Renomeei", resposta)

    def test_quebra_de_linha_do_codigo_fica_intacta(self):
        # Com o newline padrao, no Windows cada quebra viraria CR LF e
        # o arquivo de código sairia com fim de linha misturado.
        quebra = chr(10)
        self.criar("x.py", f"a = 1{quebra}b = 2{quebra}")
        bruto = (J.WORKSPACE_DIR / "x.py").read_bytes()

        self.assertNotIn(b"\r\n", bruto)

    def test_acento_no_codigo(self):
        quebra = chr(10)
        self.criar(
            "acento.py", f'# coração{quebra}print("ação"){quebra}'
        )
        self.assertIn(
            "coração",
            (J.WORKSPACE_DIR / "acento.py").read_text(encoding="utf-8"),
        )

    def test_conta_as_linhas_na_resposta(self):
        quebra = chr(10)
        resposta = self.criar("tres.py", f"a{quebra}b{quebra}c")
        self.assertIn("3 linha", resposta)

    def test_sem_extensao_e_sem_tipo_vira_txt(self):
        self.criar("recado", "oi")
        self.assertTrue((J.WORKSPACE_DIR / "recado.txt").exists())

    def test_copia_de_seguranca_antes_de_sobrescrever(self):
        self.criar("v.py", "primeira")
        self.criar("v.py", "segunda")

        self.assertEqual(
            (J.WORKSPACE_DIR / "v.py.bak").read_text(encoding="utf-8"),
            "primeira",
        )

    def test_grava_no_lugar_falado(self):
        casa = Path(tempfile.mkdtemp(prefix="nebell_casa_"))

        with mock.patch.object(J.Path, "home", staticmethod(lambda: casa)):
            J.tool_escrever_arquivo("downloads/script.py", "print(1)")

        self.assertTrue((casa / "Downloads" / "script.py").exists())

    def test_respeita_o_nao_do_usuario(self):
        self.aceitar.stop()

        with mock.patch.object(J, "confirm_action", return_value=False):
            resposta = self.criar("negado.py", "x")

        self.aceitar.start()
        self.assertFalse((J.WORKSPACE_DIR / "negado.py").exists())
        self.assertIn("negou", resposta)

    def test_respeita_a_protecao_do_sistema(self):
        resposta = J.tool_escrever_arquivo(
            str(caminho_de_sistema()), "invasao"
        )
        self.assertNotIn("gravado", resposta)

    def test_conteudo_nulo_nao_estoura(self):
        resposta = self.criar("vazio.txt", None)
        self.assertIn("gravado", resposta)


class TestEscreverDocumento(EscreverTest):
    def ler_de_volta(self, nome):
        import nebell_docs

        dados, erro = nebell_docs.ler(J.WORKSPACE_DIR / nome)
        self.assertIsNone(erro, erro)
        return dados

    @PRECISA_WORD
    def test_cria_word_que_abre(self):
        resposta = self.criar(
            "rel.docx", "# Relatório\n## Resumo\n- primeiro\n- segundo"
        )

        self.assertIn("Criei", resposta)
        texto = self.ler_de_volta("rel.docx")["texto"]
        self.assertIn("Relatório", texto)
        self.assertIn("primeiro", texto)

    @PRECISA_PLANILHA
    def test_cria_excel_com_numero_somavel(self):
        self.criar("gastos.xlsx", "Item;Valor\nLuz;300\nInternet;120,50")

        import openpyxl

        livro = openpyxl.load_workbook(J.WORKSPACE_DIR / "gastos.xlsx")
        folha = livro.active

        self.assertEqual(folha["A1"].value, "Item")
        self.assertEqual(folha["B2"].value, 300)
        self.assertAlmostEqual(folha["B3"].value, 120.50, places=2)
        livro.close()

    @PRECISA_PLANILHA
    def test_o_cabecalho_da_planilha_fica_em_negrito(self):
        self.criar("t.xlsx", "Nome;Nota\nAna;10")

        import openpyxl

        livro = openpyxl.load_workbook(J.WORKSPACE_DIR / "t.xlsx")
        self.assertTrue(livro.active["A1"].font.bold)
        livro.close()

    @PRECISA_APRESENTACAO
    def test_cria_powerpoint_com_um_slide_por_titulo(self):
        self.criar(
            "deck.pptx",
            "# Primeiro\n- ponto um\n# Segundo\n- ponto dois",
        )

        dados = self.ler_de_volta("deck.pptx")
        self.assertEqual(dados["slides"], 2)
        self.assertIn("ponto dois", dados["texto"])

    @PRECISA_PDF
    def test_cria_pdf_que_abre(self):
        self.criar("rel.pdf", "# Título\nUm parágrafo de teste.")

        dados = self.ler_de_volta("rel.pdf")
        self.assertGreaterEqual(dados["paginas"], 1)
        self.assertIn("Título", dados["texto"])

    @PRECISA_PDF
    def test_pdf_longo_vira_varias_paginas(self):
        self.criar("longo.pdf", "\n".join(f"linha {n}" for n in range(200)))

        self.assertGreater(self.ler_de_volta("longo.pdf")["paginas"], 1)

    @PRECISA_PLANILHA
    def test_documento_pelo_tipo_falado(self):
        self.criar("orcamento", "Item;Valor\nLuz;300", "excel")
        self.assertTrue((J.WORKSPACE_DIR / "orcamento.xlsx").exists())

    def test_pacote_faltando_explica_o_comando(self):
        import nebell_docs

        with mock.patch.object(
            nebell_docs, "_importar_para_criar",
            lambda tipo: (None, "preciso de um pacote: pip install python-docx")
        ):
            resposta = self.criar("x.docx", "# oi")

        self.assertIn("pip install", resposta)

    def test_sem_o_modulo_de_documentos(self):
        # Sem o módulo, gravar .docx como texto daria um arquivo
        # corrompido com o nome certo: o pior resultado possível.
        with mock.patch.object(J, "nebell_docs", None):
            resposta = self.criar("x.docx", "# oi")

        self.assertIn("não vou gravar", resposta)
        self.assertFalse((J.WORKSPACE_DIR / "x.docx").exists())

    def test_sem_o_modulo_o_texto_continua_funcionando(self):
        with mock.patch.object(J, "nebell_docs", None):
            resposta = self.criar("ainda.py", "print(1)")

        self.assertIn("gravado", resposta)

    def test_extensao_que_nao_sei_montar(self):
        import nebell_docs

        feito, erro = nebell_docs.criar(J.WORKSPACE_DIR / "x.odt", "a")
        self.assertIsNone(feito)
        self.assertIn("odt", erro)


class TestSelecaoParaCodigo(NebellTest):
    def selecionar(self, texto):
        return [
            e["function"]["name"] for e in J.selecionar_ferramentas(texto)
        ]

    def test_pedido_de_codigo_traz_a_ferramenta(self):
        for pedido in (
            "cria um arquivo java chamado Pessoa",
            "me faz um script em python pra somar",
            "escreve uma classe c# de cliente",
            "faz um programa em c++ que ordena",
            "cria um html da minha pagina",
            "escreve uma query sql de relatorio",
        ):
            self.assertIn("escrever_arquivo", self.selecionar(pedido), pedido)

    def test_pedido_de_documento_traz_a_ferramenta(self):
        for pedido in (
            "monta uma planilha de gastos no excel",
            "cria um documento word do relatorio",
            "faz uma apresentacao em powerpoint",
            "gera um pdf com esse texto",
        ):
            self.assertIn("escrever_arquivo", self.selecionar(pedido), pedido)

    def test_pedido_de_pasta_continua_indo_para_criar_pasta(self):
        self.assertIn(
            "criar_pasta", self.selecionar("cria uma pasta chamada Projetos")
        )

    def test_o_prompt_do_sistema_cita_codigo_e_documento(self):
        esquema = J.TOOL_POR_NOME["escrever_arquivo"]["function"]
        self.assertIn(".java", esquema["description"])
        self.assertIn(".docx", esquema["description"])
        self.assertIn("criar_pasta", esquema["description"])


# ============================================================
# ARQUIVO ENVIADO PELA JANELA
# ============================================================

class TestReceberArquivo(NebellTest):
    def setUp(self):
        super().setUp()
        J.arquivo_em_foco = {}
        self.pedidos = []

        self.calar = mock.patch.multiple(
            J, speak=lambda t: None, ui_message=lambda *a: None
        )
        self.calar.start()

        self.atender = mock.patch.object(
            J, "ask_nebell",
            lambda texto, resumo=None: self.pedidos.append((texto, resumo)),
        )
        self.atender.start()

    def tearDown(self):
        self.calar.stop()
        self.atender.stop()
        J.arquivo_em_foco = {}

    def enviar(self, nome, conteudo="", binario=None):
        alvo = J.WORKSPACE_DIR / nome

        if binario is not None:
            alvo.write_bytes(binario)
        else:
            alvo.write_text(conteudo, encoding="utf-8")

        J.receber_arquivo(str(alvo))
        return alvo

    def test_o_botao_enfileira_o_caminho(self):
        J.drain(J.request_queue)
        J.hud_files(["C:\\x\\a.py", "C:\\x\\b.png"])

        itens = [J.request_queue.get_nowait() for _ in range(2)]
        self.assertEqual(
            itens, [("arquivo", "C:\\x\\a.py"), ("arquivo", "C:\\x\\b.png")]
        )

    def test_o_botao_limita_quantos_de_uma_vez(self):
        J.drain(J.request_queue)
        J.hud_files([f"a{n}.py" for n in range(20)])

        self.assertLessEqual(J.request_queue.qsize(), 5)

    def test_lista_vazia_nao_faz_nada(self):
        J.drain(J.request_queue)
        J.hud_files([])
        J.hud_files(None)

        self.assertTrue(J.request_queue.empty())

    def test_arquivo_de_codigo_vai_para_o_modelo_com_caminho(self):
        alvo = self.enviar("script.py", "def soma(a, b):\n    return a + b\n")

        self.assertEqual(len(self.pedidos), 1)
        pedido, resumo = self.pedidos[0]

        self.assertIn(str(alvo), pedido)
        self.assertIn("def soma", pedido)
        self.assertIn("script.py", resumo)

    def test_a_indentacao_chega_intacta_ao_modelo(self):
        # Se o conteúdo chegar sem indentação, o modelo reescreve o
        # arquivo quebrado.
        self.enviar("ident.py", "def f():\n    return 1\n")
        pedido, _ = self.pedidos[0]

        self.assertIn("    return 1", pedido)

    def test_o_arquivo_fica_em_foco(self):
        alvo = self.enviar("foco.py", "x = 1")

        self.assertEqual(J.arquivo_em_foco["caminho"], str(alvo))
        self.assertTrue(J.arquivo_em_foco["ficha"])

    def test_o_prompt_do_sistema_aponta_o_arquivo(self):
        alvo = self.enviar("prompt.py", "x = 1")
        prompt = J.build_system_prompt()

        self.assertIn(str(alvo), prompt)
        self.assertIn("acrescentar_arquivo", prompt)

    def test_fica_registrado_na_memoria(self):
        self.enviar("memoria.py", "x = 1")

        self.assertTrue(J.memoria.buscar_arquivos("memoria.py", limite=5))

    def test_a_memoria_guarda_a_frase_curta(self):
        # O prompt cheio não deve entupir o histórico da conversa.
        self.enviar("curta.py", "x = 1")
        _, resumo = self.pedidos[0]

        self.assertLess(len(resumo), 60)

    @PRECISA_WORD
    def test_documento_vem_com_o_conteudo(self):
        import nebell_docs

        alvo = J.WORKSPACE_DIR / "r.docx"
        nebell_docs.criar(alvo, "# Relatório\nA receita subiu.")

        J.receber_arquivo(str(alvo))
        pedido, _ = self.pedidos[0]

        self.assertIn("receita subiu", pedido)

    def test_arquivo_inexistente_avisa_sem_estourar(self):
        J.receber_arquivo(str(J.WORKSPACE_DIR / "nao_existe.py"))
        self.assertEqual(self.pedidos, [])

    def test_respeita_a_protecao_do_sistema(self):
        J.receber_arquivo(str(caminho_de_sistema()))
        self.assertEqual(self.pedidos, [])

    def test_arquivo_binario_desconhecido_nao_estoura(self):
        self.enviar("coisa.bin", binario=b"\x00\x01\x02" * 50)
        self.assertEqual(len(self.pedidos), 1)

    def test_o_despachante_atende_a_origem_arquivo(self):
        alvo = J.WORKSPACE_DIR / "despacho.py"
        alvo.write_text("x = 1", encoding="utf-8")

        J.shutdown_event.clear()
        J.drain(J.request_queue)
        J.request_queue.put(("arquivo", str(alvo)))

        recebidos = []

        def receber(caminho):
            recebidos.append(caminho)
            J.shutdown_event.set()

        with mock.patch.object(J, "receber_arquivo", receber), \
                mock.patch.object(J, "hud", None):
            J.dispatcher_loop()

        J.shutdown_event.clear()
        self.assertEqual(recebidos, [str(alvo)])

    def test_erro_ao_receber_nao_derruba_o_despachante(self):
        J.shutdown_event.clear()
        J.drain(J.request_queue)
        J.request_queue.put(("arquivo", "qualquer"))

        def explodir(caminho):
            J.shutdown_event.set()
            raise RuntimeError("quebrou")

        with mock.patch.object(J, "receber_arquivo", explodir), \
                mock.patch.object(J, "hud", None):
            J.dispatcher_loop()

        J.shutdown_event.clear()


class TestAcrescentarArquivo(NebellTest):
    def setUp(self):
        super().setUp()
        self.aceitar = mock.patch.object(
            J, "confirm_action", return_value=True
        )
        self.aceitar.start()

    def tearDown(self):
        self.aceitar.stop()

    def test_acrescenta_no_fim(self):
        alvo = J.WORKSPACE_DIR / "a.py"
        alvo.write_text("def um():\n    pass\n", encoding="utf-8")

        J.tool_acrescentar_arquivo(str(alvo), "def dois():\n    pass\n")
        texto = alvo.read_text(encoding="utf-8")

        self.assertTrue(texto.startswith("def um():"))
        self.assertIn("def dois():", texto)

    def test_poe_a_quebra_quando_falta(self):
        alvo = J.WORKSPACE_DIR / "b.py"
        alvo.write_text("primeira", encoding="utf-8")

        J.tool_acrescentar_arquivo(str(alvo), "segunda")

        self.assertEqual(
            alvo.read_text(encoding="utf-8"), "primeira\nsegunda"
        )

    def test_nao_duplica_a_quebra(self):
        alvo = J.WORKSPACE_DIR / "c.py"
        alvo.write_text("primeira\n", encoding="utf-8")

        J.tool_acrescentar_arquivo(str(alvo), "segunda")

        self.assertEqual(
            alvo.read_text(encoding="utf-8"), "primeira\nsegunda"
        )

    def test_faz_copia_de_seguranca(self):
        alvo = J.WORKSPACE_DIR / "d.py"
        alvo.write_text("antes", encoding="utf-8")

        J.tool_acrescentar_arquivo(str(alvo), "depois")

        self.assertEqual(
            (J.WORKSPACE_DIR / "d.py.bak").read_text(encoding="utf-8"), "antes"
        )

    def test_arquivo_que_nao_existe(self):
        resposta = J.tool_acrescentar_arquivo(
            str(J.WORKSPACE_DIR / "nao.py"), "x"
        )
        self.assertIn("escrever_arquivo", resposta)

    def test_recusa_arquivo_binario(self):
        alvo = J.WORKSPACE_DIR / "e.docx"
        alvo.write_bytes(b"PK\x03\x04")

        resposta = J.tool_acrescentar_arquivo(str(alvo), "texto")
        self.assertIn("binário", resposta)

    def test_conteudo_vazio(self):
        alvo = J.WORKSPACE_DIR / "f.py"
        alvo.write_text("x", encoding="utf-8")

        self.assertIn(
            "Não disse", J.tool_acrescentar_arquivo(str(alvo), "")
        )

    def test_respeita_o_nao(self):
        alvo = J.WORKSPACE_DIR / "g.py"
        alvo.write_text("antes", encoding="utf-8")

        self.aceitar.stop()

        with mock.patch.object(J, "confirm_action", return_value=False):
            J.tool_acrescentar_arquivo(str(alvo), "depois")

        self.aceitar.start()
        self.assertEqual(alvo.read_text(encoding="utf-8"), "antes")

    def test_respeita_a_protecao(self):
        resposta = J.tool_acrescentar_arquivo(
            str(caminho_de_sistema()), "invasao"
        )
        self.assertNotIn("Acrescentei", resposta)

    def test_esta_registrada(self):
        self.assertIn("acrescentar_arquivo", J.TOOL_FUNCTIONS)
        self.assertIn(
            "acrescentar_arquivo",
            {e["function"]["name"] for e in J.TOOL_SCHEMAS},
        )

    def test_o_pedido_de_adicionar_traz_a_ferramenta(self):
        escolhidas = [
            e["function"]["name"] for e in J.selecionar_ferramentas(
                "adiciona uma função nesse arquivo"
            )
        ]
        self.assertIn("acrescentar_arquivo", escolhidas)


class TestFerramentaDeBackup(NebellTest):
    def setUp(self):
        super().setUp()
        import nebell_backup

        self.pasta = TMP / "backup_tool"
        shutil.rmtree(self.pasta, ignore_errors=True)

        J.backup = nebell_backup.Backup(
            TMP / "memoria.db", self.pasta, memoria=J.memoria,
            log=lambda *a: None,
        )

    def tearDown(self):
        if J.backup is not None:
            J.backup.parar()

        J.backup = None

    def test_status_sem_copia(self):
        self.assertIn("Ainda não há backup", J.tool_backup("status"))

    def test_copiar_agora(self):
        resposta = J.tool_backup("copiar")
        self.assertIn("Backup atualizado", resposta)
        self.assertTrue((self.pasta / "memoria_backup.db").is_file())

    def test_status_depois_da_copia(self):
        J.tool_backup("copiar")
        self.assertIn("Backup de", J.tool_backup("status"))

    def test_restaurar_explica_que_precisa_fechar(self):
        J.tool_backup("copiar")
        resposta = J.tool_backup("restaurar")

        self.assertIn("Restaurar_Memoria.bat", resposta)
        self.assertIn("programa aberto", resposta)

    def test_sem_backup_ligado(self):
        J.backup = None

        with mock.patch.object(J, "nebell_backup", object()):
            self.assertIn("desligado", J.tool_backup())

    def test_sem_o_modulo(self):
        J.backup = None

        with mock.patch.object(J, "nebell_backup", None):
            self.assertIn("backup", J.tool_backup().lower())

    def test_o_pedido_sobre_memoria_salva_traz_a_ferramenta(self):
        escolhidas = [
            e["function"]["name"] for e in J.selecionar_ferramentas(
                "minhas memórias estão salvas? tem backup?"
            )
        ]
        self.assertIn("backup", escolhidas)

    def test_a_copia_do_fim_e_forcada(self):
        pedidos = []

        with mock.patch.object(
            J.backup, "copiar",
            lambda forcar=False, motivo="", com_relatorio=True: pedidos.append(
                (forcar, motivo, com_relatorio)
            ) or (True, "ok"),
        ):
            J.copiar_memoria_no_fim()

        # com_relatorio=False: o relatório já foi gravado com o banco
        # aberto, e reescrevê-lo agora o zeraria.
        self.assertEqual(pedidos, [(True, "encerramento", False)])

    def test_sem_backup_o_fim_nao_estoura(self):
        J.backup = None
        J.copiar_memoria_no_fim()

    def test_fechar_extras_para_o_backup(self):
        J.backup.iniciar()
        J.fechar_extras()

        self.assertFalse(J.backup.ligado)


# ============================================================
# CODIGO QUE VEM NA RESPOSTA
# ============================================================
# Este e o conserto do pedido que nao respondia nada: "faça um arquivo
# em java sobre herança e explique cada ponto".

RESPOSTA_DE_HERANCA = """Claro, senhor. A lógica: Animal concentra o que
todo animal tem, e as filhas só mudam o que é próprio delas.

```java
/**
 * Animal: a classe base. Guarda o que TODO animal tem.
 */
public class Animal {
    protected String nome;

    public Animal(String nome) {
        this.nome = nome;
    }

    public String emitirSom() {
        return "algum som";
    }
}
```

E a filha:

```java
/**
 * Cachorro HERDA de Animal com extends.
 */
public class Cachorro extends Animal {

    public Cachorro(String nome) {
        super(nome);
    }

    @Override
    public String emitirSom() {
        return "Au au";
    }
}
```

O extends cria a herança e o super passa o nome ao construtor do pai.
"""


class TestExtrairBlocos(NebellTest):
    def test_acha_a_linguagem_e_o_codigo(self):
        blocos = J.extrair_blocos_de_codigo(RESPOSTA_DE_HERANCA)

        self.assertEqual(len(blocos), 2)
        self.assertEqual(blocos[0][0], "java")
        self.assertIn("public class Animal", blocos[0][1])

    def test_bloco_sem_linguagem(self):
        blocos = J.extrair_blocos_de_codigo("antes\n```\nx = 1\n```\ndepois")

        self.assertEqual(len(blocos), 1)
        self.assertEqual(blocos[0][0], "")

    def test_resposta_sem_bloco(self):
        self.assertEqual(J.extrair_blocos_de_codigo("só conversa"), [])

    def test_bloco_vazio_e_ignorado(self):
        self.assertEqual(J.extrair_blocos_de_codigo("```java\n\n```"), [])

    def test_texto_nulo(self):
        self.assertEqual(J.extrair_blocos_de_codigo(None), [])

    def test_crase_no_meio_da_frase_nao_conta(self):
        self.assertEqual(
            J.extrair_blocos_de_codigo("use o `extends` aqui"), []
        )


class TestExtensaoDoBloco(NebellTest):
    def test_pelo_rotulo(self):
        for rotulo, esperado in (
            ("java", ".java"), ("python", ".py"), ("py", ".py"),
            ("javascript", ".js"), ("js", ".js"), ("csharp", ".cs"),
            ("c#", ".cs"), ("cpp", ".cpp"), ("c++", ".cpp"),
            ("bash", ".sh"), ("powershell", ".ps1"), ("html", ".html"),
            ("sql", ".sql"), ("md", ".md"),
        ):
            self.assertEqual(
                J.extensao_do_bloco(rotulo), esperado, rotulo
            )

    def test_adivinha_java_pelo_corpo(self):
        # Modelo pequeno abre ``` sem dizer a linguagem.
        self.assertEqual(
            J.extensao_do_bloco("", "public class Pessoa {\n}"), ".java"
        )

    def test_distingue_csharp_de_java(self):
        self.assertEqual(
            J.extensao_do_bloco("", "using System;\npublic class P {}"), ".cs"
        )

    def test_adivinha_python(self):
        self.assertEqual(
            J.extensao_do_bloco("", "def soma(a, b):\n    return a + b"), ".py"
        )

    def test_adivinha_c_e_cpp(self):
        self.assertEqual(
            J.extensao_do_bloco("", "#include <stdio.h>\nint main(){}"), ".c"
        )
        self.assertEqual(
            J.extensao_do_bloco("", "#include <iostream>\nint main(){}"),
            ".cpp",
        )

    def test_adivinha_html_e_sql(self):
        self.assertEqual(
            J.extensao_do_bloco("", "<!doctype html>\n<html>"), ".html"
        )
        self.assertEqual(
            J.extensao_do_bloco("", "SELECT * FROM clientes;"), ".sql"
        )

    def test_nao_adivinha_o_que_nao_da(self):
        self.assertEqual(J.extensao_do_bloco("", "só um texto solto"), "")


class TestNomeDoCodigo(NebellTest):
    def test_java_usa_a_classe_publica(self):
        self.assertEqual(
            J.nome_para_o_codigo(
                ".java", "public class Animal {\n}", "faz um java"
            ),
            "Animal.java",
        )

    def test_java_com_abstract_e_final(self):
        for codigo, esperado in (
            ("public abstract class Base {}", "Base.java"),
            ("public final class Util {}", "Util.java"),
            ("public interface Forma {}", "Forma.java"),
            ("public enum Cor { AZUL }", "Cor.java"),
        ):
            self.assertEqual(
                J.nome_para_o_codigo(".java", codigo), esperado, codigo
            )

    def test_csharp_tambem(self):
        self.assertEqual(
            J.nome_para_o_codigo(".cs", "public sealed class Cliente {}"),
            "Cliente.cs",
        )

    def test_python_usa_a_classe_ou_a_funcao(self):
        self.assertEqual(
            J.nome_para_o_codigo(".py", "class Pessoa:\n    pass"),
            "Pessoa.py",
        )
        self.assertEqual(
            J.nome_para_o_codigo(".py", "def calcular_media(n):\n    pass"),
            "calcular_media.py",
        )

    def test_main_nao_serve_de_nome(self):
        nome = J.nome_para_o_codigo(
            ".py", "def main():\n    pass", "faz um script de backup"
        )
        self.assertNotEqual(nome, "main.py")

    def test_cai_para_o_assunto_do_pedido(self):
        nome = J.nome_para_o_codigo(
            ".py", "print(1)", "faça um arquivo sobre lista encadeada"
        )
        self.assertTrue(nome.endswith(".py"))
        self.assertIn("lista", nome)

    def test_sem_nada_tem_nome_generico(self):
        self.assertEqual(J.nome_para_o_codigo(".py", "print(1)", ""), "codigo.py")


class TestPediuArquivo(NebellTest):
    def test_pedidos_que_criam(self):
        for pedido in (
            "faça arquivo em java sobre herança",
            "cria um script em python",
            "escreve uma classe c# de cliente",
            "me faz um programa em c++",
            "gera um arquivo html",
            "implementa uma classe de pilha em java",
        ):
            self.assertTrue(J.pediu_para_criar_arquivo(pedido), pedido)

    def test_pedidos_que_so_explicam(self):
        # Não espalhar arquivo pelo disco quando ninguém pediu arquivo.
        for pedido in (
            "me explica herança em java",
            "o que é polimorfismo",
            "qual a diferença entre classe e objeto",
            "como funciona o extends",
        ):
            self.assertFalse(J.pediu_para_criar_arquivo(pedido), pedido)


class TestSalvarCodigoDaResposta(NebellTest):
    def setUp(self):
        super().setUp()
        J.arquivo_em_foco = {}

        # Pasta limpa por teste: a de trabalho é compartilhada, e um
        # Animal.java deixado por outro teste faria este passar ou
        # falhar por engano.
        self.antes = J.WORKSPACE_DIR
        J.WORKSPACE_DIR = Path(tempfile.mkdtemp(prefix="nebell_cod_"))

    def tearDown(self):
        J.WORKSPACE_DIR = self.antes

    def test_grava_as_duas_classes_com_o_nome_certo(self):
        feitos = J.salvar_codigo_da_resposta(
            "faça arquivo em java sobre herança e explique cada ponto",
            RESPOSTA_DE_HERANCA,
        )

        self.assertEqual(len(feitos), 2)
        self.assertTrue((J.WORKSPACE_DIR / "Animal.java").is_file())
        self.assertTrue((J.WORKSPACE_DIR / "Cachorro.java").is_file())

    def test_o_codigo_gravado_e_o_do_bloco(self):
        J.salvar_codigo_da_resposta(
            "faça arquivo em java sobre herança", RESPOSTA_DE_HERANCA
        )
        codigo = (J.WORKSPACE_DIR / "Animal.java").read_text(encoding="utf-8")

        self.assertTrue(codigo.startswith("/**"))
        self.assertIn("protected String nome;", codigo)
        self.assertNotIn("```", codigo)

    def test_a_explicacao_em_comentario_fica_no_arquivo(self):
        # É isso que o usuário pediu: a explicação dentro do código.
        J.salvar_codigo_da_resposta(
            "faça arquivo em java sobre herança", RESPOSTA_DE_HERANCA
        )
        codigo = (J.WORKSPACE_DIR / "Cachorro.java").read_text(encoding="utf-8")

        self.assertIn("HERDA de Animal", codigo)

    def test_a_indentacao_sobrevive(self):
        J.salvar_codigo_da_resposta(
            "faça arquivo em java sobre herança", RESPOSTA_DE_HERANCA
        )
        codigo = (J.WORKSPACE_DIR / "Animal.java").read_text(encoding="utf-8")

        self.assertIn("        this.nome = nome;", codigo)

    def test_nao_grava_quando_so_pediram_explicacao(self):
        feitos = J.salvar_codigo_da_resposta(
            "me explica herança em java", RESPOSTA_DE_HERANCA
        )

        self.assertEqual(feitos, [])
        self.assertFalse((J.WORKSPACE_DIR / "Animal.java").exists())

    def test_trecho_curto_nao_vira_arquivo(self):
        feitos = J.salvar_codigo_da_resposta(
            "cria um arquivo java", "```java\nint x = 1;\n```"
        )
        self.assertEqual(feitos, [])

    def test_resposta_sem_bloco(self):
        self.assertEqual(
            J.salvar_codigo_da_resposta("cria um arquivo java", "nada aqui"), []
        )

    def test_o_arquivo_fica_em_foco(self):
        J.salvar_codigo_da_resposta(
            "faça arquivo em java sobre herança", RESPOSTA_DE_HERANCA
        )
        self.assertIn("Cachorro.java", J.arquivo_em_foco.get("caminho", ""))

    def test_fica_registrado_na_memoria(self):
        J.salvar_codigo_da_resposta(
            "faça arquivo em java sobre herança", RESPOSTA_DE_HERANCA
        )
        self.assertTrue(J.memoria.buscar_arquivos("Animal", limite=5))

    def test_grava_no_lugar_que_o_pedido_citou(self):
        casa = Path(tempfile.mkdtemp(prefix="nebell_casa_"))
        (casa / "Desktop").mkdir()

        with mock.patch.object(J.Path, "home", staticmethod(lambda: casa)):
            J.salvar_codigo_da_resposta(
                "faça um arquivo java na area de trabalho sobre herança",
                RESPOSTA_DE_HERANCA,
            )

        self.assertTrue((casa / "Desktop" / "Animal.java").is_file())

    def test_copia_de_seguranca_se_o_arquivo_existia(self):
        alvo = J.WORKSPACE_DIR / "Animal.java"
        alvo.write_text("versão antiga", encoding="utf-8")

        J.salvar_codigo_da_resposta(
            "faça arquivo em java sobre herança", RESPOSTA_DE_HERANCA
        )

        self.assertEqual(
            (J.WORKSPACE_DIR / "Animal.java.bak").read_text(encoding="utf-8"),
            "versão antiga",
        )

    def test_respeita_a_protecao_do_sistema(self):
        with mock.patch.object(
            J, "lugar_pedido", lambda t: caminho_de_sistema().parent
        ):
            feitos = J.salvar_codigo_da_resposta(
                "faça arquivo em java sobre herança", RESPOSTA_DE_HERANCA
            )

        self.assertTrue(
            all("Gravei" not in f for f in feitos), feitos
        )

    def test_bloco_repetido_grava_uma_vez(self):
        resposta = RESPOSTA_DE_HERANCA + RESPOSTA_DE_HERANCA
        feitos = J.salvar_codigo_da_resposta(
            "faça arquivo em java sobre herança", resposta
        )
        self.assertEqual(len(feitos), 2)


class TestLugarPedido(NebellTest):
    def test_acha_a_pasta_citada(self):
        self.assertEqual(
            J.lugar_pedido("faz um java na area de trabalho"),
            J.pasta_do_usuario("area de trabalho"),
        )
        self.assertEqual(
            J.lugar_pedido("salva em downloads"),
            J.pasta_do_usuario("downloads"),
        )

    def test_sem_lugar_citado(self):
        self.assertIsNone(J.lugar_pedido("faz um arquivo em java"))


class TestLimiteDeResposta(NebellTest):
    def test_pedido_de_codigo_ganha_espaco(self):
        # A causa real do "não respondeu nada": 320 tokens cortavam a
        # geração no meio do arquivo.
        opcoes = J.opcoes_do_pedido(
            "faça arquivo em java sobre herança e explique cada ponto"
        )
        self.assertGreaterEqual(opcoes["num_predict"], 2048)

    def test_conversa_comum_fica_curta(self):
        for pedido in ("que horas são", "como está o clima",
                       "abre o brave", "esvazia a lixeira"):
            self.assertEqual(
                J.opcoes_do_pedido(pedido)["num_predict"],
                J.MODEL_OPTIONS["num_predict"],
                pedido,
            )

    def test_nao_mexe_no_dicionario_original(self):
        antes = dict(J.MODEL_OPTIONS)
        J.opcoes_do_pedido("faz um java")
        self.assertEqual(J.MODEL_OPTIONS, antes)

    def test_nunca_reduz_o_que_o_perfil_deu(self):
        with mock.patch.dict(J.MODEL_OPTIONS, {"num_predict": 4000}):
            self.assertEqual(
                J.opcoes_do_pedido("faz um java")["num_predict"], 4000
            )

    def test_o_contexto_do_perfil_e_preservado(self):
        opcoes = J.opcoes_do_pedido("faz um java")
        self.assertEqual(opcoes["num_ctx"], J.MODEL_OPTIONS["num_ctx"])

    def test_sem_texto_usa_o_padrao(self):
        self.assertEqual(
            J.opcoes_do_pedido()["num_predict"],
            J.MODEL_OPTIONS["num_predict"],
        )

    def test_as_regras_de_codigo_entram_so_quando_e_codigo(self):
        self.assertIn("crase tripla", J.build_system_prompt(True))
        self.assertNotIn("crase tripla", J.build_system_prompt(False))

    def test_o_prompt_de_conversa_e_menor(self):
        self.assertLess(
            len(J.build_system_prompt(False)), len(J.build_system_prompt(True))
        )


# ============================================================
# O ARQUIVO NAO PODE TER DEFINICAO DUPLICADA
# ============================================================
# Este bloco existe por causa de um defeito real: conviviam duas
# geracoes de codigo de backup no nebell.py. O Python mantinha a
# ultima de cada, entao nada estourava, mas abrir_backup era CHAMADA
# duas vezes, e um passo do encerramento chamava um metodo que nao
# existia mais e falhava calado em toda saida.

class TestSemDuplicata(NebellTest):
    def arvore(self):
        import ast

        caminho = Path(J.__file__)
        return ast.parse(caminho.read_text(encoding="utf-8")), ast

    def test_nenhuma_funcao_definida_duas_vezes(self):
        import collections

        arvore, ast = self.arvore()
        contagem = collections.Counter(
            no.name for no in arvore.body
            if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        repetidas = [nome for nome, n in contagem.items() if n > 1]

        self.assertEqual(repetidas, [], f"definidas duas vezes: {repetidas}")

    def test_nenhuma_classe_definida_duas_vezes(self):
        import collections

        arvore, ast = self.arvore()
        contagem = collections.Counter(
            no.name for no in arvore.body if isinstance(no, ast.ClassDef)
        )
        self.assertEqual([n for n, c in contagem.items() if c > 1], [])

    def test_nenhuma_constante_atribuida_duas_vezes(self):
        import collections

        arvore, ast = self.arvore()
        contagem = collections.Counter(
            alvo.id
            for no in arvore.body if isinstance(no, ast.Assign)
            for alvo in no.targets
            if isinstance(alvo, ast.Name) and alvo.id.isupper()
        )
        repetidas = [nome for nome, n in contagem.items() if n > 1]

        self.assertEqual(repetidas, [], f"atribuídas duas vezes: {repetidas}")

    def test_os_passos_do_encerramento_existem(self):
        # O passo morto chamava backup_final, que chamava backup.fazer:
        # um método que o módulo não tem. Falhava em toda saída.
        self.assertFalse(hasattr(J, "backup_final"))

    def test_nada_chama_metodo_que_o_modulo_nao_tem(self):
        import nebell_backup

        fonte = Path(J.__file__).read_text(encoding="utf-8")
        metodos = {
            m for m in dir(nebell_backup.Backup) if not m.startswith("_")
        }

        for chamada in re.findall(r"\bbackup\.(\w+)\(", fonte):
            self.assertIn(chamada, metodos, f"backup.{chamada}() não existe")


# ============================================================
# RELATORIO DA MEMORIA NO ENCERRAMENTO
# ============================================================

class TestRelatorioNoEncerramento(NebellTest):
    def setUp(self):
        super().setUp()
        import nebell_backup

        self.pasta = Path(tempfile.mkdtemp(prefix="nebell_rel_"))
        J.backup = nebell_backup.Backup(
            TMP / "memoria.db", self.pasta, memoria=J.memoria,
            log=lambda *a: None,
        )

        J.memoria.guardar_fato("gosta de café sem açúcar", "preferencia")
        J.memoria.registrar_mensagem("user", "oi")

    def tearDown(self):
        if J.backup is not None:
            J.backup.parar()

        J.backup = None

    @property
    def relatorio(self):
        return (self.pasta / "memorias.txt").read_text(encoding="utf-8")

    def test_o_relatorio_sai_com_conteudo(self):
        with mock.patch.object(J, "resumir_sessao", lambda: None), \
                mock.patch.object(J.memoria, "fechar", lambda: None):
            J.fechar_memoria()

        self.assertIn("café sem açúcar", self.relatorio)
        self.assertNotIn("0 conversa(s), 0 mensagem(ns)", self.relatorio)

    def test_e_gravado_antes_de_o_banco_fechar(self):
        # A prova da ordem: no momento do fechar, o relatório já existe.
        quando_fechou = {}

        def fechar_falso():
            quando_fechou["existia"] = (self.pasta / "memorias.txt").is_file()

        with mock.patch.object(J, "resumir_sessao", lambda: None), \
                mock.patch.object(J.memoria, "fechar", fechar_falso):
            J.fechar_memoria()

        self.assertTrue(quando_fechou.get("existia"))

    def test_a_copia_final_nao_apaga_o_relatorio(self):
        with mock.patch.object(J, "resumir_sessao", lambda: None), \
                mock.patch.object(J.memoria, "fechar", lambda: None):
            J.fechar_memoria()

        bom = self.relatorio
        J.memoria.fechar()          # agora sim, fechado de verdade
        J.copiar_memoria_no_fim()

        self.assertEqual(self.relatorio, bom)

    def test_relatorio_zerado_nao_cobre_o_bom(self):
        # Rede de segurança: mesmo que a ordem se perca algum dia, um
        # relatório de zeros não substitui um que tinha conteúdo.
        J.backup.copiar(forcar=True)
        bom = self.relatorio

        J.memoria.fechar()
        self.assertFalse(J.backup.escrever_relatorio())
        self.assertEqual(self.relatorio, bom)

    def test_sem_backup_o_fechar_nao_estoura(self):
        J.backup = None

        with mock.patch.object(J, "resumir_sessao", lambda: None), \
                mock.patch.object(J.memoria, "fechar", lambda: None):
            J.fechar_memoria()

    def test_relatorio_que_falha_nao_impede_o_fechamento(self):
        fechou = []

        with mock.patch.object(J, "resumir_sessao", lambda: None), \
                mock.patch.object(
                    J.backup, "escrever_relatorio",
                    side_effect=RuntimeError("quebrou")
                ), \
                mock.patch.object(
                    J.memoria, "fechar", lambda: fechou.append(True)
                ):
            J.fechar_memoria()

        self.assertTrue(fechou)


class TestBackupAbreUmaVezSo(NebellTest):
    def test_a_abertura_copia_uma_vez(self):
        # Antes, abrir_backup era chamada duas vezes e gravava duas
        # cópias idênticas, gastando uma geração do histórico.
        import nebell_backup

        pasta = Path(tempfile.mkdtemp(prefix="nebell_ab_"))
        copias = []

        class BackupFalso:
            def __init__(self, *a, **k):
                pass

            def copiar(self, forcar=False, motivo="", com_relatorio=True):
                copias.append(motivo)
                return True, "ok"

            def iniciar(self):
                return True

            def parar(self):
                return None

        with mock.patch.object(nebell_backup, "Backup", BackupFalso), \
                mock.patch.object(J, "BACKUP_DIR", pasta):
            J.abrir_backup()

        J.backup = None
        self.assertEqual(copias, ["abertura"])

    def test_a_fonte_chama_abrir_backup_uma_vez(self):
        fonte = Path(J.__file__).read_text(encoding="utf-8")
        chamadas = re.findall(r"^\s*abrir_backup\(\)", fonte, re.M)
        self.assertEqual(len(chamadas), 1)


# ============================================================
# TEXTO NA JANELA DURANTE A GERACAO
# ============================================================

class HudEspia:
    """Uma janela de mentira que anota tudo que recebe."""

    def __init__(self):
        self.active = True
        self.chamadas = []

    def stream_message(self, texto):
        self.chamadas.append(("stream", texto))

    def fechar_stream(self):
        self.chamadas.append(("fechar", None))

    def trabalhando(self, texto):
        self.chamadas.append(("trabalhando", texto))

    def add_message(self, papel, texto):
        self.chamadas.append(("msg", texto))

    def set_state(self, estado):
        pass

    def set_stats(self, **campos):
        pass

    def de(self, tipo):
        return [t for k, t in self.chamadas if k == tipo]


class JanelaTest(NebellTest):
    def setUp(self):
        super().setUp()
        self.antes = J.hud
        self.espia = HudEspia()
        J.hud = self.espia
        J.texto_na_janela[0] = False
        J._stream_em[0] = 0.0
        J._fazendo_agora[0] = ""

    def tearDown(self):
        J.hud = self.antes
        J.texto_na_janela[0] = False
        J._fazendo_agora[0] = ""


class TestTextoEmTempoReal(JanelaTest):
    def test_o_texto_vai_para_a_janela_enquanto_sai(self):
        J.ui_stream("Olá", forcar=True)
        self.assertEqual(self.espia.de("stream"), ["Olá"])

    def test_manda_o_texto_inteiro_nao_o_pedaco(self):
        # A bolha é substituída, não acumulada: mandar só o pedaço novo
        # apagaria o que já estava escrito.
        J.ui_stream("Olá", forcar=True)
        J.ui_stream("Olá, senhor", forcar=True)
        self.assertEqual(self.espia.de("stream")[-1], "Olá, senhor")

    def test_limita_a_frequencia(self):
        # Uma chamada de JS por token travaria a janela.
        for n in range(50):
            J.ui_stream("x" * n)

        self.assertLess(len(self.espia.de("stream")), 10)

    def test_forcar_passa_pelo_limite(self):
        J.ui_stream("primeiro")
        quantas = len(self.espia.de("stream"))
        J.ui_stream("final", forcar=True)

        self.assertEqual(len(self.espia.de("stream")), quantas + 1)

    def test_marca_que_apareceu_texto(self):
        self.assertFalse(J.texto_na_janela[0])
        J.ui_stream("algo", forcar=True)
        self.assertTrue(J.texto_na_janela[0])

    def test_texto_vazio_nao_vai(self):
        J.ui_stream("", forcar=True)
        self.assertEqual(self.espia.de("stream"), [])

    def test_sem_janela_nao_estoura(self):
        J.hud = None
        J.ui_stream("algo", forcar=True)
        J.ui_fechar_stream()
        J.ui_trabalhando("x")

    def test_fecha_a_bolha(self):
        J.ui_fechar_stream()
        self.assertEqual(len(self.espia.de("fechar")), 1)


class TestNaoDuplicaABolha(JanelaTest):
    def responder(self, texto):
        """Um pedido inteiro, com o modelo devolvendo este texto."""
        with mock.patch.object(
            J, "run_model_round", return_value=(texto, [])
        ), mock.patch.object(J, "speak", lambda t: None), \
                mock.patch.object(J, "wait_for_speech", lambda: None):
            J.ask_nebell("me diz algo")

    def responder_com_streaming(self, texto):
        """
        Um pedido em que o texto sai letra por letra, como no real.

        A bandeira de "já apareceu texto" é zerada no começo de cada
        pedido, então marcá-la por fora não valeria de nada: o
        streaming tem de acontecer DENTRO da rodada.
        """
        def rodada(allow_tools, opcoes=None):
            J.ui_stream(texto, forcar=True)
            return texto, []

        with mock.patch.object(J, "run_model_round", rodada), \
                mock.patch.object(J, "speak", lambda t: None), \
                mock.patch.object(J, "wait_for_speech", lambda: None):
            J.ask_nebell("me diz algo")

    def test_bolha_preenchida_nao_vira_mensagem_nova(self):
        # O defeito a evitar: o texto apareceria duas vezes, uma na
        # bolha e outra como mensagem nova no fim.
        self.responder_com_streaming("resposta inteira")

        mensagens = [m for m in self.espia.de("msg") if "resposta" in m]
        self.assertEqual(mensagens, [])
        self.assertTrue(self.espia.de("fechar"))

    def test_o_texto_chegou_pela_bolha(self):
        self.responder_com_streaming("resposta inteira")
        self.assertIn("resposta inteira", self.espia.de("stream"))

    def test_sem_streaming_a_mensagem_final_aparece(self):
        # Atalho local e resposta sem streaming continuam aparecendo.
        self.responder("resposta curta")
        self.assertTrue(
            any("resposta curta" in m for m in self.espia.de("msg"))
        )


class TestAvisoDeTrabalho(JanelaTest):
    def rodar_vigia(self, segundos=0.3, avisar_em=0.1):
        J.busy_event.set()

        with mock.patch.object(J, "SEGUNDOS_PARA_AVISAR", avisar_em), \
                mock.patch.object(J, "INTERVALO_DO_AVISO", 0.05):
            fio = threading.Thread(
                target=J.vigia_do_trabalho,
                args=(time.monotonic(),), daemon=True,
            )
            fio.start()
            time.sleep(segundos)
            J.busy_event.clear()
            fio.join(timeout=3)

    def avisos(self):
        return [t for t in self.espia.de("trabalhando") if t]

    def test_avisa_quando_nada_aparece(self):
        self.rodar_vigia()
        self.assertTrue(self.avisos())
        self.assertIn("trabalhando nisso", self.avisos()[0])

    def test_mostra_o_tempo_correndo(self):
        self.rodar_vigia()
        self.assertRegex(self.avisos()[0], r"\d+s$")

    def test_nunca_mostra_zero_segundos(self):
        for aviso in self.avisos() + ["x"]:
            self.assertNotIn("0s", aviso)

        self.rodar_vigia()

        for aviso in self.avisos():
            self.assertNotIn("... 0s", aviso)

    def test_diz_qual_ferramenta_esta_rodando(self):
        J.descrever_trabalho("pesquisar_web")
        self.rodar_vigia()

        self.assertIn("pesquisando na internet", self.avisos()[-1])

    def test_ferramenta_desconhecida_tem_frase_generica(self):
        J.descrever_trabalho("ferramenta_inventada")
        self.assertIn("ferramenta_inventada", J._fazendo_agora[0])

    def test_nao_avisa_enquanto_o_texto_esta_saindo(self):
        # A própria bolha já mostra que há algo acontecendo.
        J.texto_na_janela[0] = True
        self.rodar_vigia()

        self.assertEqual(self.avisos(), [])

    def test_apaga_o_aviso_no_fim(self):
        self.rodar_vigia()
        self.assertEqual(self.espia.de("trabalhando")[-1], "")

    def test_nao_avisa_antes_do_tempo(self):
        self.rodar_vigia(segundos=0.15, avisar_em=5.0)
        self.assertEqual(self.avisos(), [])

    def test_sem_janela_o_vigia_sai_na_hora(self):
        J.hud = None
        J.busy_event.set()

        try:
            J.vigia_do_trabalho(time.monotonic())   # não pode travar
        finally:
            J.busy_event.clear()

    def test_toda_ferramenta_citada_existe(self):
        for nome in J.O_QUE_ESTA_FAZENDO:
            self.assertIn(nome, J.TOOL_FUNCTIONS, nome)

    def test_as_ferramentas_lentas_estao_descritas(self):
        # As que fazem o usuário esperar são as que mais precisam.
        for nome in ("pesquisar_web", "ler_pagina", "resumir_documento",
                     "ler_tela", "buscar_arquivos", "estado_maquina"):
            self.assertIn(nome, J.O_QUE_ESTA_FAZENDO, nome)


class TestPaginaDaJanelaTemONecessario(NebellTest):
    def test_a_pagina_sabe_fazer_o_streaming(self):
        import nebell_hud

        for parte in ("streamMessage", "fecharStream", "trabalhando",
                      'id="work"', ".msg.streaming"):
            self.assertIn(parte, nebell_hud.HUD_HTML, parte)

    def test_a_ponte_tem_os_metodos(self):
        import nebell_hud

        for metodo in ("stream_message", "fechar_stream", "trabalhando"):
            self.assertTrue(
                hasattr(nebell_hud.HudBridge, metodo), metodo
            )

    def test_a_versao_da_pagina_subiu(self):
        import nebell_hud

        self.assertGreaterEqual(nebell_hud.HUD_VERSAO, 5)

# ============================================================
# A MARCA DE "ESTOU FALANDO"
# ============================================================

class TestMarcaDeFala(NebellTest):
    """
    O microfone abria e logo morria.

    `falando_agora` para a escuta enquanto ele fala, para ela nao gravar
    o alto-falante. O defeito: quem ligava a marca era o speak(), e quem
    desligava era o wait_for_speech() -- que o chamador tinha de lembrar
    de chamar. A saudacao da abertura nao chamava. Resultado: a marca
    ficava ligada para sempre, a escuta dormia 0,2 s em laco e o
    microfone nao voltava pelo resto da sessao.

    Agora quem termina a fala e que desliga a marca, nos dois
    trabalhadores, em todos os caminhos.
    """

    def setUp(self):
        super().setUp()
        J.falando_agora.clear()
        J.zerar_falas()
        J.ultima_fala_em[0] = 0.0

    def esperar_fim_da_fala(self, limite=5.0):
        """Espera a fala acabar SEM chamar wait_for_speech."""
        fim = time.time() + limite

        while time.time() < fim:
            if J.falas_em_curso[0] == 0 and J.speech_queue.empty() \
                    and J.audio_queue.empty():
                # Um instante para o trabalhador sair do finally.
                time.sleep(0.05)

                if J.falas_em_curso[0] == 0:
                    return True

            time.sleep(0.02)

        return False

    # ---- o caso dele ----

    def test_a_saudacao_sozinha_nao_mata_o_microfone(self):
        # Exatamente o que a abertura faz: fala e nao espera.
        J.speak(J.SAUDACAO)

        self.assertTrue(
            self.esperar_fim_da_fala(), "a fala não terminou"
        )
        self.assertFalse(
            J.falando_agora.is_set(),
            "a marca ficou ligada: a escuta não voltaria",
        )

    def test_a_escuta_volta_depois_da_saudacao(self):
        # O teste de verdade: a condicao que o laco de escuta usa.
        J.speak(J.SAUDACAO)
        self.esperar_fim_da_fala()

        J.ultima_fala_em[0] = time.time() - J.ECO_CARENCIA - 0.1

        parada = (
            J.busy_event.is_set()
            or J.falando_agora.is_set()
        )
        self.assertFalse(parada, "o laço continuaria dormindo")

    def test_aviso_de_fundo_tambem_libera(self):
        # Lembrete da agenda, alerta da sentinela: falam e vao embora.
        J.speak("Atenção: a placa está em oitenta e cinco graus.")
        self.esperar_fim_da_fala()
        self.assertFalse(J.falando_agora.is_set())

    # ---- a contagem ----

    def test_liga_na_primeira_e_conta(self):
        J.speak("primeiro")
        self.assertTrue(J.falando_agora.is_set())
        self.assertGreaterEqual(J.falas_em_curso[0], 1)

    def test_fica_ligada_ate_o_ultimo_trecho(self):
        for trecho in ("um.", "dois.", "três.", "quatro."):
            J.speak(trecho)

        self.assertTrue(J.falando_agora.is_set())
        self.assertTrue(self.esperar_fim_da_fala())
        self.assertFalse(J.falando_agora.is_set())
        self.assertEqual(J.falas_em_curso[0], 0)

    def test_a_contagem_nao_fica_negativa(self):
        J.zerar_falas()
        J.fala_terminou()
        J.fala_terminou()
        self.assertEqual(J.falas_em_curso[0], 0)

    def test_fala_vazia_nao_conta(self):
        J.speak("   ")
        self.assertEqual(J.falas_em_curso[0], 0)
        self.assertFalse(J.falando_agora.is_set())

    # ---- os caminhos que nao chegam a tocar ----

    def test_texto_que_vira_nada_depois_de_limpo(self):
        # clean_for_speech pode esvaziar o trecho (so pontuacao, so
        # emoji). Antes isso vazava: ninguem descontava.
        J.speak("...")
        self.assertTrue(self.esperar_fim_da_fala())
        self.assertFalse(J.falando_agora.is_set())

    def test_erro_na_sintese_nao_deixa_a_marca_presa(self):
        with mock.patch.object(
            J, "synthesize_cached", side_effect=RuntimeError("piper caiu")
        ):
            J.speak("alguma coisa")
            self.assertTrue(self.esperar_fim_da_fala())

        self.assertFalse(J.falando_agora.is_set())

    def test_erro_ao_tocar_nao_deixa_a_marca_presa(self):
        with mock.patch.object(
            J, "play_audio", side_effect=RuntimeError("placa de som caiu")
        ):
            J.speak("alguma coisa")
            self.assertTrue(self.esperar_fim_da_fala())

        self.assertFalse(J.falando_agora.is_set())

    # ---- quem corta e quem espera ----

    def test_parar_a_fala_zera_a_contagem(self):
        for trecho in ("um.", "dois.", "três."):
            J.speak(trecho)

        J.stop_speaking()
        self.assertEqual(J.falas_em_curso[0], 0)
        self.assertFalse(J.falando_agora.is_set())

    def test_esperar_a_fala_zera_a_contagem(self):
        J.speak("alguma coisa")
        J.wait_for_speech()
        self.assertEqual(J.falas_em_curso[0], 0)
        self.assertFalse(J.falando_agora.is_set())

    def test_parar_no_meio_nao_deixa_contagem_pendurada(self):
        # O tocador em curso ainda vai passar pelo finally depois do
        # corte; isso nao pode derrubar a contagem abaixo de zero nem
        # religar a marca.
        J.speak("um.")
        J.stop_speaking()
        self.esperar_fim_da_fala(limite=2.0)
        self.assertEqual(J.falas_em_curso[0], 0)
        self.assertFalse(J.falando_agora.is_set())

    # ---- a carencia do eco ----

    def test_marca_a_hora_no_fim_para_a_carencia_valer(self):
        J.ultima_fala_em[0] = 0.0
        J.speak("alguma coisa")
        self.esperar_fim_da_fala()

        # A hora tem de ser do FIM da fala, nao do comeco: e dela que
        # sai a carencia que evita o eco.
        self.assertGreater(J.ultima_fala_em[0], 0.0)
        self.assertLess(time.time() - J.ultima_fala_em[0], 2.0)

    def test_logo_depois_de_falar_a_escuta_ainda_espera(self):
        J.speak("alguma coisa")
        self.esperar_fim_da_fala()

        desde = time.time() - J.ultima_fala_em[0]
        self.assertLess(desde, J.ECO_CARENCIA)


class TestNinguemDependeDoWaitForSpeech(unittest.TestCase):
    """
    Guarda contra a volta do defeito: a marca nao pode voltar a
    depender de alguem lembrar de chamar wait_for_speech().
    """

    def test_a_marca_e_desligada_pelos_trabalhadores(self):
        fonte = Path(J.__file__).read_text(encoding="utf-8")

        corpo = fonte[fonte.index("def player_worker"):]
        corpo = corpo[:corpo.index("\ndef ", 1)]
        self.assertIn("fala_terminou", corpo)

        corpo = fonte[fonte.index("def synth_worker"):]
        corpo = corpo[:corpo.index("\ndef ", 1)]
        self.assertIn("fala_terminou", corpo)

    def test_o_speak_nao_liga_a_marca_na_mao(self):
        fonte = Path(J.__file__).read_text(encoding="utf-8")
        corpo = fonte[fonte.index("def speak("):]
        corpo = corpo[:corpo.index("\ndef ", 1)]

        self.assertIn("fala_comecou", corpo)
        self.assertNotIn("falando_agora.set()", corpo)

    def test_a_abertura_fala_a_saudacao_sem_esperar(self):
        # Isto e de proposito: a janela nao pode travar esperando a
        # saudacao. Por isso a marca tem de se desligar sozinha.
        fonte = Path(J.__file__).read_text(encoding="utf-8")
        corpo = fonte[fonte.index("def run_hud_mode"):]
        corpo = corpo[:corpo.index("\ndef ", 1)]

        self.assertIn("speak(SAUDACAO)", corpo)

class TestEscutaNaoDesiste(NebellTest):
    """
    Sem microfone, a escuta nao pode morrer para a sessao toda.

    Antes o laco subia so se o microfone estivesse pronto NAQUELE
    instante, e, uma vez de pe, se o aparelho sumisse (fone tirado no
    meio) ele apenas dormia. Nos dois casos religar o microfone nao
    trazia a escuta de volta: era preciso fechar e abrir o NEBELL.
    """

    def setUp(self):
        super().setUp()
        J.falando_agora.clear()
        J.zerar_falas()

    def rodar_um_pouco(self, segundos=0.6):
        J.shutdown_event.clear()
        thread = threading.Thread(target=J.voice_listen_loop, daemon=True)
        thread.start()
        time.sleep(segundos)
        J.shutdown_event.set()
        thread.join(timeout=3)
        J.shutdown_event.clear()
        garantir_trabalhadores()
        return thread

    def test_sem_microfone_tenta_reabrir(self):
        gerente = mock.Mock()
        gerente.ready = False
        gerente.recover.return_value = False

        with mock.patch.object(J, "mic_manager", gerente), \
                mock.patch.object(J, "SEGUNDOS_PARA_TENTAR_O_MIC", 0.0):
            self.rodar_um_pouco()

        self.assertTrue(
            gerente.recover.called,
            "a escuta nem tentou reabrir o microfone",
        )

    def test_quando_reabre_a_janela_e_avisada(self):
        gerente = mock.Mock()
        gerente.ready = False
        gerente.recover.return_value = True

        with mock.patch.object(J, "mic_manager", gerente), \
                mock.patch.object(J, "SEGUNDOS_PARA_TENTAR_O_MIC", 0.0), \
                mock.patch.object(J, "on_microphone_change") as avisar:
            self.rodar_um_pouco()

        self.assertTrue(avisar.called)

    def test_nao_tenta_a_toda_hora(self):
        gerente = mock.Mock()
        gerente.ready = False
        gerente.recover.return_value = False

        # Com a espera normal de 10 s, uma passada curta tenta uma vez.
        with mock.patch.object(J, "mic_manager", gerente):
            self.rodar_um_pouco(segundos=0.8)

        self.assertLessEqual(gerente.recover.call_count, 1)

    def test_erro_ao_reabrir_nao_derruba_a_escuta(self):
        gerente = mock.Mock()
        gerente.ready = False
        gerente.recover.side_effect = RuntimeError("driver caiu")

        with mock.patch.object(J, "mic_manager", gerente), \
                mock.patch.object(J, "SEGUNDOS_PARA_TENTAR_O_MIC", 0.0):
            thread = self.rodar_um_pouco()

        self.assertFalse(thread.is_alive())
        self.assertTrue(gerente.recover.called)

    def test_a_escuta_sobe_sem_depender_do_microfone(self):
        fonte = Path(J.__file__).read_text(encoding="utf-8")
        corpo = fonte[fonte.index("def run_hud_mode"):]
        corpo = corpo[:corpo.index("\ndef ", 1)]

        inicio = corpo.index("voice_listen_loop")
        antes = corpo[:inicio]

        # A linha que sobe a escuta nao pode estar dentro de um
        # "if microphone_available()".
        self.assertNotIn("if microphone_available()", antes)

class TestAvisaAJanelaOQueEstaFazendo(NebellTest):
    """
    A forma da nuvem na janela vem da ferramenta que esta rodando.

    O nebell.py so precisa passar o nome adiante: o mapa de formas do
    lado da pagina usa exatamente os nomes de O_QUE_ESTA_FAZENDO.
    """

    def setUp(self):
        super().setUp()
        self.janela = mock.Mock()
        self.antiga = J.hud
        J.hud = self.janela

    def tearDown(self):
        J.hud = self.antiga
        super().tearDown()

    def test_a_ferramenta_chega_na_janela(self):
        J.descrever_trabalho("ler_tela")
        self.janela.para_ferramenta.assert_called_once_with("ler_tela")

    def test_o_texto_do_aviso_continua_funcionando(self):
        J.descrever_trabalho("pesquisar_web")
        self.assertEqual(J._fazendo_agora[0], "pesquisando na internet")

    def test_sem_janela_nao_estoura(self):
        J.hud = None
        J.descrever_trabalho("backup")
        self.assertEqual(J._fazendo_agora[0], "cuidando do backup")

    def test_janela_que_falha_nao_derruba_o_pedido(self):
        # A janela pode ter morrido no meio; isso nao pode levar a
        # resposta junto.
        self.janela.para_ferramenta.side_effect = RuntimeError("morreu")
        J.descrever_trabalho("ler_tela")
        self.assertEqual(J._fazendo_agora[0], "lendo a sua tela")

    def test_ferramenta_desconhecida_nao_quebra(self):
        J.descrever_trabalho("coisa_que_nao_existe")
        self.janela.para_ferramenta.assert_called_once_with(
            "coisa_que_nao_existe"
        )
        self.assertIn("usando", J._fazendo_agora[0])

    def test_toda_ferramenta_registrada_tem_descricao(self):
        # Guarda contra uma ferramenta nova entrar sem texto: o aviso
        # de "trabalhando nisso" ficaria feio e a janela cairia na
        # forma generica.
        faltando = [
            nome for nome in J.FERRAMENTAS_QUE_GRAVAM
            if nome not in J.O_QUE_ESTA_FAZENDO
        ]
        self.assertEqual(faltando, [], ", ".join(faltando))


if __name__ == "__main__":
    unittest.main(verbosity=2)
