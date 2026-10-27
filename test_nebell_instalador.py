"""
Testes do instalar.py.

Ele mexe em coisa de fora -- baixa arquivo, roda instalador, cria
ambiente -- entao quase tudo aqui e simulado. O que NAO e simulado:
a criacao do ambiente, que roda de verdade num diretorio temporario.

O que esses testes protegem, em ordem de importancia:

  1. um passo que falha nao pode derrubar os outros;
  2. nada pode dizer "deu certo" sem ter dado;
  3. rodar duas vezes nao pode estragar o que ja estava pronto.
"""

import io
import shutil
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import instalar as I


class InstaladorTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.raiz = Path(self.temp.name)

        self.antes = (I.AQUI, I.VENV, list(I.recado))
        I.AQUI = self.raiz
        I.VENV = self.raiz / ".venv"
        I.recado.clear()

    def tearDown(self):
        I.AQUI, I.VENV, guardado = self.antes
        I.recado.clear()
        I.recado.extend(guardado)
        self.temp.cleanup()

    def faltas(self):
        return [t for ok, t in I.recado if not ok]

    def prontos(self):
        return [t for ok, t in I.recado if ok]


# ============================================================
# AMBIENTE
# ============================================================

class TestAmbiente(InstaladorTest):
    def test_cria_de_verdade(self):
        vpy = I.criar_ambiente()

        self.assertIsNotNone(vpy)
        self.assertTrue(Path(vpy).exists())
        self.assertEqual(self.faltas(), [])

    def test_rodar_de_novo_nao_refaz(self):
        primeiro = I.criar_ambiente()
        marca = Path(primeiro).stat().st_mtime

        I.recado.clear()
        segundo = I.criar_ambiente()

        self.assertEqual(primeiro, segundo)
        self.assertEqual(Path(segundo).stat().st_mtime, marca)
        self.assertEqual(self.faltas(), [])

    def test_ambiente_de_outra_maquina_e_guardado_e_refeito(self):
        # Um .venv copiado guarda o caminho do Python de origem e nao
        # roda aqui. Nao pode ser apagado calado nem usado quebrado.
        vpy = I.python_do_venv()
        vpy.parent.mkdir(parents=True)
        vpy.write_text("não sou um python", encoding="utf-8")

        novo = I.criar_ambiente()

        self.assertIsNotNone(novo)
        self.assertTrue((self.raiz / ".venv_antigo").is_dir())
        self.assertEqual(self.faltas(), [])

    def test_quando_nao_da_para_criar_ele_diz(self):
        with mock.patch.object(I, "roda", return_value=(False, "deu ruim")):
            self.assertIsNone(I.criar_ambiente())

        self.assertTrue(self.faltas())


# ============================================================
# BAIXAR
# ============================================================

class TestBaixar(InstaladorTest):
    def test_baixa_de_verdade_um_arquivo_local(self):
        origem = self.raiz / "origem.bin"
        origem.write_bytes(b"x" * 200000)
        destino = self.raiz / "copia.bin"

        self.assertTrue(I.baixar(origem.as_uri(), destino, "teste"))
        self.assertEqual(destino.read_bytes(), origem.read_bytes())

    def test_url_que_nao_existe_devolve_falso(self):
        destino = self.raiz / "nada.bin"
        self.assertFalse(
            I.baixar("file:///nao/existe/mesmo.bin", destino, "teste")
        )

    def test_nao_deixa_arquivo_pela_metade(self):
        # Um .exe truncado e pior do que nenhum: o instalador roda e
        # falha de um jeito confuso.
        destino = self.raiz / "meio.bin"

        with mock.patch.object(
            I.urllib.request, "urlopen", side_effect=OSError("caiu")
        ):
            self.assertFalse(I.baixar("https://x/y.exe", destino, "teste"))

        self.assertFalse(destino.exists())


# ============================================================
# OLLAMA
# ============================================================

class NoWindows(InstaladorTest):
    """
    Finge Windows.

    O Ollama e o Tesseract so sao instalados automaticamente la, e e
    la que o código dele roda. Sem isto, estes testes passariam pelo
    desvio de "outro sistema" e nao testariam nada.
    """

    def setUp(self):
        super().setUp()
        self.janela = mock.patch.object(I, "IS_WINDOWS", True)
        self.janela.start()

    def tearDown(self):
        self.janela.stop()
        super().tearDown()


class TestOllama(NoWindows):
    def test_se_ja_existe_nao_baixa_nada(self):
        with mock.patch.object(I, "existe_programa", return_value=True), \
                mock.patch.object(I, "roda", return_value=(True, "ollama 0.5")), \
                mock.patch.object(I, "baixar") as baixou:
            self.assertTrue(I.instalar_ollama())

        baixou.assert_not_called()
        self.assertIn("Ollama", self.prontos())

    def test_silencioso_que_funciona(self):
        with mock.patch.object(I, "existe_programa", return_value=False), \
                mock.patch.object(I, "baixar", return_value=True), \
                mock.patch.object(I, "roda", return_value=(True, "")), \
                mock.patch.object(I, "achar_ollama", return_value="C:\\ollama.exe"), \
                mock.patch.object(I.subprocess, "run") as rodou:
            self.assertTrue(I.instalar_ollama())

        # Deu certo em silencio: nao pode abrir janela nenhuma.
        rodou.assert_not_called()
        self.assertIn("Ollama", self.prontos())

    def test_quando_o_silencio_falha_abre_o_instalador(self):
        """
        O ponto deste teste.

        A instalacao silenciosa do Ollama nao e documentada. Se um dia
        parar de funcionar, o script NAO pode dizer que instalou: tem
        de abrir o instalador para a pessoa clicar.
        """
        achou = [None, "C:\\ollama.exe"]

        with mock.patch.object(I, "existe_programa", return_value=False), \
                mock.patch.object(I, "baixar", return_value=True), \
                mock.patch.object(I, "roda", return_value=(True, "")), \
                mock.patch.object(I, "achar_ollama", side_effect=achou), \
                mock.patch.object(I.subprocess, "run") as rodou:
            self.assertTrue(I.instalar_ollama())

        rodou.assert_called_once()
        self.assertIn("Ollama", self.prontos())

    def test_quando_nao_instala_de_jeito_nenhum_e_honesto(self):
        with mock.patch.object(I, "existe_programa", return_value=False), \
                mock.patch.object(I, "baixar", return_value=True), \
                mock.patch.object(I, "roda", return_value=(True, "")), \
                mock.patch.object(I, "achar_ollama", return_value=None), \
                mock.patch.object(I.subprocess, "run"):
            self.assertFalse(I.instalar_ollama())

        self.assertTrue(any("Ollama" in t for t in self.faltas()))

    def test_download_que_falha_manda_para_a_pagina(self):
        with mock.patch.object(I, "existe_programa", return_value=False), \
                mock.patch.object(I, "baixar", return_value=False):
            self.assertFalse(I.instalar_ollama())

        self.assertTrue(any(I.OLLAMA_PAGINA in t for t in self.faltas()))


# ============================================================
# MODELO
# ============================================================

class TestModelo(InstaladorTest):
    def test_sem_ollama_nao_tenta(self):
        with mock.patch.object(I, "achar_ollama", return_value=None):
            self.assertFalse(I.baixar_modelo())

        self.assertTrue(self.faltas())

    def test_modelo_ja_baixado_nao_baixa_de_novo(self):
        lista = f"NAME\\n{I.MODELO}  2.5 GB\\n"

        with mock.patch.object(I, "achar_ollama", return_value="ollama"), \
                mock.patch.object(I, "roda", return_value=(True, lista)) as r:
            self.assertTrue(I.baixar_modelo())

        # So o "list"; nenhum "pull".
        for chamada in r.call_args_list:
            self.assertNotIn("pull", chamada[0][0])

    def test_falha_no_pull_diz_o_comando(self):
        def resposta(comando, **kw):
            return (False, "") if "pull" in comando else (True, "vazio")

        with mock.patch.object(I, "achar_ollama", return_value="ollama"), \
                mock.patch.object(I, "roda", side_effect=resposta):
            self.assertFalse(I.baixar_modelo())

        self.assertTrue(any("ollama pull" in t for t in self.faltas()))


# ============================================================
# VOZ
# ============================================================

class TestVoz(InstaladorTest):
    def test_voz_ja_presente_e_pulada(self):
        voz = self.raiz / "voices" / "nebell" / "model.onnx"
        voz.parent.mkdir(parents=True)
        voz.write_bytes(b"0" * 2_000_000)

        with mock.patch.object(I, "roda") as r:
            self.assertTrue(I.baixar_voz(Path("python")))

        r.assert_not_called()

    def test_arquivo_pequeno_demais_nao_conta_como_voz(self):
        # Um download interrompido deixa um arquivo de alguns KB.
        voz = self.raiz / "voices" / "nebell" / "model.onnx"
        voz.parent.mkdir(parents=True)
        voz.write_bytes(b"0" * 500)

        (self.raiz / "baixar_voz.py").write_text("", encoding="utf-8")

        with mock.patch.object(I, "roda", return_value=(False, "")):
            self.assertFalse(I.baixar_voz(Path("python")))

    def test_sem_o_script_e_honesto(self):
        self.assertFalse(I.baixar_voz(Path("python")))
        self.assertTrue(self.faltas())


# ============================================================
# TESSERACT
# ============================================================

class TestTesseract(NoWindows):
    def test_pular_nao_vira_falta(self):
        I.instalar_tesseract(pular=True)
        self.assertEqual(I.recado, [])

    def test_ja_instalado(self):
        with mock.patch.object(I, "existe_programa", return_value=True):
            self.assertTrue(I.instalar_tesseract(pular=False))

        self.assertEqual(self.faltas(), [])

    def test_tenta_as_outras_versoes(self):
        # O nome do instalador muda a cada versao; tem de tentar mais
        # de um antes de desistir.
        with mock.patch.object(I, "existe_programa", return_value=False), \
                mock.patch.object(I, "baixar", return_value=False) as b:
            I.instalar_tesseract(pular=False)

        self.assertEqual(b.call_count, len(I.TESSERACT_URLS))

    def test_falhar_aqui_e_so_um_aviso(self):
        with mock.patch.object(I, "existe_programa", return_value=False), \
                mock.patch.object(I, "baixar", return_value=False):
            self.assertFalse(I.instalar_tesseract(pular=False))

        falta = self.faltas()
        self.assertEqual(len(falta), 1)
        self.assertIn("opcional", falta[0])


# ============================================================
# PACOTES
# ============================================================

class TestPacotes(InstaladorTest):
    def test_um_bloco_que_falha_nao_para_os_outros(self):
        """
        O caso real: o pyaudio e o que mais falha em maquina nova. Se
        ele derrubasse a instalacao, o NEBELL nao abriria por causa de
        um recurso que e opcional.
        """
        tentados = []

        def resposta(comando, **kw):
            if "install" in comando and "--quiet" in comando:
                pacotes = comando[comando.index("--quiet") + 1:]
                tentados.append(pacotes)
                return (False, "erro") if "pyaudio" in pacotes else (True, "")

            return (True, "")

        with mock.patch.object(I, "roda", side_effect=resposta):
            I.instalar_pacotes(Path("python"))

        self.assertEqual(len(tentados), len(I.BLOCOS))
        self.assertTrue(any("áudio" in t for t in self.faltas()))

    def test_tudo_certo_nao_gera_falta(self):
        with mock.patch.object(I, "roda", return_value=(True, "")):
            I.instalar_pacotes(Path("python"))

        self.assertEqual(self.faltas(), [])

    def test_todo_pacote_conferido_e_instalado_por_algum_bloco(self):
        # Guarda contra conferir um modulo que nenhum bloco instala:
        # o relatorio diria FALTA para sempre.
        instalados = {p.lower() for _, lista in I.BLOCOS for p in lista}
        apelidos = {
            "piper": "piper-tts", "speech_recognition": "speechrecognition",
            "faster_whisper": "faster-whisper", "webview": "pywebview",
            "PIL": "pillow", "docx": "python-docx", "pptx": "python-pptx",
        }

        for modulo, _ in I.CONFERIR:
            pacote = apelidos.get(modulo, modulo).lower()
            self.assertIn(pacote, instalados, modulo)


# ============================================================
# O CONJUNTO
# ============================================================

class TestTudoJunto(InstaladorTest):
    def test_uma_instalacao_inteira_com_tudo_dando_certo(self):
        with mock.patch.object(I, "criar_ambiente", return_value=Path("py")), \
                mock.patch.object(I, "instalar_pacotes"), \
                mock.patch.object(I, "instalar_ollama", return_value=True), \
                mock.patch.object(I, "baixar_modelo", return_value=True), \
                mock.patch.object(I, "baixar_voz", return_value=True), \
                mock.patch.object(I, "instalar_tesseract", return_value=True), \
                mock.patch.object(I, "conferir", return_value=set()), \
                mock.patch.object(sys, "argv", ["instalar.py"]):
            saida = io.StringIO()

            with mock.patch("sys.stdout", saida):
                self.assertEqual(I.main(), 0)

        self.assertIn("Iniciar_NEBELL.bat", saida.getvalue())

    def test_sem_ambiente_para_e_avisa(self):
        with mock.patch.object(I, "criar_ambiente", return_value=None), \
                mock.patch.object(I, "instalar_pacotes") as pacotes, \
                mock.patch.object(sys, "argv", ["instalar.py"]):
            saida = io.StringIO()

            with mock.patch("sys.stdout", saida):
                self.assertEqual(I.main(), 1)

        pacotes.assert_not_called()
        self.assertIn("PAREI", saida.getvalue())

    def test_sem_ollama_o_modelo_e_pulado_e_dito(self):
        with mock.patch.object(I, "criar_ambiente", return_value=Path("py")), \
                mock.patch.object(I, "instalar_pacotes"), \
                mock.patch.object(I, "instalar_ollama", return_value=False), \
                mock.patch.object(I, "baixar_modelo") as modelo, \
                mock.patch.object(I, "baixar_voz", return_value=True), \
                mock.patch.object(I, "instalar_tesseract", return_value=True), \
                mock.patch.object(I, "conferir", return_value=set()), \
                mock.patch.object(sys, "argv", ["instalar.py"]):
            with mock.patch("sys.stdout", io.StringIO()):
                I.main()

        modelo.assert_not_called()
        self.assertTrue(any(I.MODELO in t for t in self.faltas()))

    def test_sem_tesseract_pula(self):
        with mock.patch.object(I, "criar_ambiente", return_value=Path("py")), \
                mock.patch.object(I, "instalar_pacotes"), \
                mock.patch.object(I, "instalar_ollama", return_value=True), \
                mock.patch.object(I, "baixar_modelo", return_value=True), \
                mock.patch.object(I, "baixar_voz", return_value=True), \
                mock.patch.object(I, "conferir", return_value=set()), \
                mock.patch.object(I, "instalar_tesseract") as tess, \
                mock.patch.object(sys, "argv",
                                  ["instalar.py", "--sem-tesseract"]):
            with mock.patch("sys.stdout", io.StringIO()):
                I.main()

        tess.assert_called_once_with(True)

    def test_os_instaladores_baixados_sao_apagados(self):
        pasta = self.raiz / "_download"
        pasta.mkdir()
        (pasta / "OllamaSetup.exe").write_bytes(b"0" * 1000)

        with mock.patch("sys.stdout", io.StringIO()):
            I.limpar_downloads()

        self.assertFalse(pasta.exists())


class TestMedidas(unittest.TestCase):
    def test_tamanho_legivel(self):
        self.assertEqual(I.tamanho_legivel(0), "0 B")
        self.assertIn("MB", I.tamanho_legivel(5 * 1024 * 1024))
        self.assertIn("GB", I.tamanho_legivel(3 * 1024 ** 3))

    def test_roda_com_programa_que_nao_existe(self):
        ok, saida = I.roda(["programa_que_nao_existe_mesmo"], mostrar=False)
        self.assertFalse(ok)
        self.assertIn("não achei", saida)

    def test_o_requirements_bate_com_o_instalador(self):
        """
        Os dois listam os mesmos pacotes e podem sair do lugar um sem
        o outro. Quem instala na mão pelo requirements.txt acabaria
        com um ambiente diferente de quem clicou no Instalar.bat.
        """
        arquivo = Path(I.__file__).resolve().parent / "requirements.txt"

        if not arquivo.is_file():
            self.skipTest("sem requirements.txt ao lado")

        pedidos = {
            linha.strip().lower()
            for linha in arquivo.read_text(encoding="utf-8").splitlines()
            if linha.strip() and not linha.lstrip().startswith("#")
        }
        instalados = {p.lower() for _, lista in I.BLOCOS for p in lista}

        self.assertEqual(
            pedidos, instalados,
            "requirements.txt e instalar.py discordam",
        )

    def test_o_modelo_e_o_mesmo_do_nebell(self):
        # Se os dois saírem do lugar, o instalador baixa um modelo e o
        # NEBELL procura outro.
        import nebell as J
        self.assertEqual(I.MODELO, J.MODEL_NAME)


if __name__ == "__main__":
    unittest.main(verbosity=2)
