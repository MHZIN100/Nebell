"""
Testes de empacotar.py e limpar.py.

As duas mexem em arquivos de verdade, entao cada teste monta uma pasta
falsa em um diretorio temporario e aponta o modulo para la. Nada toca a
pasta real.
"""

import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import empacotar
import limpar


# ---- pasta falsa, parecida com a de verdade ----------------

ATUAIS = [
    "nebell.py", "nebell_hud.py", "nebell_audio.py", "nebell_backup.py",
    "nebell_visao.py", "nebell_janela.py", "nebell_docs.py",
    "nebell_sentinela.py", "nebell_agenda.py", "nebell_memoria.py",
    "nebell_voz.py", "nebell_web.py",
    "test_nebell.py", "test_nebell_extras.py", "test_nebell_audio_hud.py",
    "test_nebell_memoria.py", "test_nebell_backup.py", "test_nebell_web.py",
    "test_nebell_pacote.py",
    "conferir_pacotes.py", "liberar_maquina.py", "restaurar_memoria.py",
    "baixar_voz.py", "empacotar.py", "limpar.py", "instalar.py",
    "test_nebell_instalador.py",
]

BATS_ATUAIS = [
    "Instalar.bat",
    "_Python.bat", "Instalar_Pacotes.bat", "Iniciar_NEBELL.bat",
    "Testar_NEBELL.bat", "Empacotar.bat", "Limpar.bat", "Baixar_Voz.bat",
    "Liberar_Maquina.bat", "Restaurar_Memoria.bat",
]

INUTEIS = [
    "jarvis.py", "jarvis_audio.py", "jarvis_hud.py", "jarvis_backup.py",
    "jarvis_v2_antigo.py", "jarvis_v3.py",
    "test_jarvis.py", "test_audio_hud.py",
    "Iniciar_JARVIS.bat", "Renomear_Antigos.bat",
    "ajustar_voz.py", "grave.py", "medir_velocidade.py",
    "teste_piper_direto.py", "teste_piper_persistente.py",
    "nebell_dev.log", "nebell.py.bak",
]

WAVS = [
    "miro_A.wav", "miro_B.wav", "miro_C.wav", "miro_mais_encorpado.wav",
    "resposta_jarvis.wav", "teste_articulacao.wav", "teste_cadu.wav",
    "teste_jarvis.wav", "teste_jarvis_123.wav", "teste_original.wav",
    "teste_miro.wav", "teste_piper_direto.wav", "teste_velocidade.wav",
]


def montar(raiz):
    """Monta uma copia leve da pasta do NEBELL em raiz."""
    for nome in ATUAIS:
        (raiz / nome).write_text("# atual\n", encoding="utf-8")

    for nome in BATS_ATUAIS:
        (raiz / nome).write_text("@echo off\n", encoding="utf-8")

    for nome in INUTEIS + WAVS:
        (raiz / nome).write_bytes(b"x" * 2048)

    (raiz / "memoria.db").write_bytes(b"d" * 4096)
    (raiz / "memoria.db-wal").write_bytes(b"")
    (raiz / "memoria.db-shm").write_bytes(b"s" * 1024)
    (raiz / "microfone.json").write_text('{"indice": 1}', encoding="utf-8")

    (raiz / "__pycache__").mkdir()
    (raiz / "__pycache__" / "nebell.cpython-313.pyc").write_bytes(b"c" * 512)

    (raiz / ".venv_antigo" / "Scripts").mkdir(parents=True)
    (raiz / ".venv_antigo" / "Scripts" / "python.exe").write_bytes(b"p" * 512)

    (raiz / ".venv" / "Scripts").mkdir(parents=True)
    (raiz / ".venv" / "Scripts" / "python.exe").write_bytes(b"p" * 512)
    (raiz / ".venv" / "pyvenv.cfg").write_text("home = C:\\Py\n", encoding="utf-8")

    for voz in ("nebell", "miro", "cadu"):
        pasta = raiz / "voices" / voz
        pasta.mkdir(parents=True)
        (pasta / "model.onnx").write_bytes(b"v" * 4096)
        (pasta / "model.onnx.json").write_text("{}", encoding="utf-8")

    (raiz / "voices" / "nebell" / "amostra.wav").write_bytes(b"a" * 256)
    (raiz / "voices" / "pt_BR-faber-medium.onnx").write_bytes(b"f" * 4096)
    (raiz / "voices" / "pt_BR-faber-medium.onnx.json").write_text(
        "{}", encoding="utf-8"
    )

    (raiz / "hud").mkdir()
    (raiz / "hud" / "index.html").write_text("<html>", encoding="utf-8")
    (raiz / "hud" / "index.anterior.html").write_text("<html>", encoding="utf-8")

    (raiz / "workspace").mkdir()
    (raiz / "workspace" / "nota.txt").write_text("ok", encoding="utf-8")

    (raiz / "backup").mkdir()
    (raiz / "backup" / "memoria.db").write_bytes(b"b" * 4096)
    (raiz / "backup" / "memorias.txt").write_text("relato", encoding="utf-8")

    (raiz / "audio_temp").mkdir()
    (raiz / "audio_temp" / "fala.wav").write_bytes(b"t" * 256)

    (raiz / "whisper_models").mkdir()
    (raiz / "whisper_models" / "model.bin").write_bytes(b"w" * 8192)


class PastaFalsa(unittest.TestCase):
    """Monta a pasta e aponta os dois modulos para ela."""

    modulo = None

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.raiz = Path(self.temp.name) / "NEBELL"
        self.raiz.mkdir()
        montar(self.raiz)

        self.antigo = self.modulo.AQUI
        self.modulo.AQUI = self.raiz

    def tearDown(self):
        self.modulo.AQUI = self.antigo
        self.temp.cleanup()

    def nomes(self):
        return {p.name for p in self.raiz.iterdir()}


# =========================  limpar  =========================


class LimparTest(PastaFalsa):
    modulo = limpar


class TestLimparAchar(LimparTest):
    def alvos(self):
        return {c.name for _, lista in limpar.achar() for c in lista}

    def test_acha_as_versoes_antigas(self):
        alvos = self.alvos()

        for nome in ("jarvis.py", "jarvis_audio.py", "jarvis_hud.py",
                     "jarvis_backup.py", "jarvis_v2_antigo.py"):
            self.assertIn(nome, alvos, nome)

    def test_pega_jarvis_que_eu_nao_listei_um_por_um(self):
        # O padrao e jarvis*.py justamente para pegar o que aparecer.
        self.assertIn("jarvis_v3.py", self.alvos())

    def test_acha_os_testes_antigos(self):
        alvos = self.alvos()
        self.assertIn("test_jarvis.py", alvos)
        self.assertIn("test_audio_hud.py", alvos)

    def test_acha_os_atalhos_antigos(self):
        alvos = self.alvos()
        self.assertIn("Iniciar_JARVIS.bat", alvos)
        self.assertIn("Renomear_Antigos.bat", alvos)

    def test_acha_os_scripts_soltos(self):
        alvos = self.alvos()

        for nome in ("ajustar_voz.py", "grave.py", "medir_velocidade.py",
                     "teste_piper_direto.py", "teste_piper_persistente.py"):
            self.assertIn(nome, alvos, nome)

    def test_acha_todos_os_wav_da_raiz(self):
        alvos = self.alvos()

        for nome in WAVS:
            self.assertIn(nome, alvos, nome)

    def test_acha_as_sobras(self):
        alvos = self.alvos()
        self.assertIn("nebell_dev.log", alvos)
        self.assertIn("nebell.py.bak", alvos)

    def test_acha_as_pastas_de_sobra(self):
        alvos = self.alvos()
        self.assertIn("__pycache__", alvos)
        self.assertIn(".venv_antigo", alvos)

    def test_nao_toca_no_programa_de_hoje(self):
        alvos = self.alvos()

        for nome in ATUAIS + BATS_ATUAIS:
            self.assertNotIn(nome, alvos, nome)

    def test_nao_toca_na_memoria(self):
        alvos = self.alvos()
        self.assertNotIn("memoria.db", alvos)

    def test_nao_toca_no_diario_do_sqlite(self):
        # Apagar o -wal com o NEBELL aberto perde memoria. De proposito
        # fora da limpeza.
        alvos = self.alvos()
        self.assertNotIn("memoria.db-wal", alvos)
        self.assertNotIn("memoria.db-shm", alvos)

    def test_nao_toca_no_microfone(self):
        self.assertNotIn("microfone.json", self.alvos())

    def test_nao_toca_no_venv_em_uso(self):
        self.assertNotIn(".venv", self.alvos())

    def test_nao_entra_em_pastas(self):
        # O amostra.wav da voz esta dentro de voices e nao pode ser
        # confundido com um wav de teste da raiz.
        alvos = self.alvos()
        self.assertNotIn("amostra.wav", alvos)
        self.assertNotIn("fala.wav", alvos)

    def test_nada_repetido(self):
        todos = [c for _, lista in limpar.achar() for c in lista]
        self.assertEqual(len(todos), len(set(todos)))

    def test_cada_grupo_tem_motivo_e_alvos(self):
        for motivo, alvos in limpar.achar():
            self.assertTrue(motivo.strip())
            self.assertTrue(alvos)

    def test_pasta_limpa_nao_acha_nada(self):
        with TemporaryDirectory() as temp:
            limpar.AQUI = Path(temp)
            self.assertEqual(limpar.achar(), [])


class TestLimparProtegidos(LimparTest):
    def test_programa_protegido(self):
        for nome in ATUAIS + BATS_ATUAIS:
            self.assertTrue(
                limpar.protegido(self.raiz / nome), nome
            )

    def test_inutil_nao_protegido(self):
        for nome in INUTEIS + WAVS:
            self.assertFalse(
                limpar.protegido(self.raiz / nome), nome
            )

    def test_bak_do_programa_nao_fica_protegido_por_engano(self):
        # nebell.py.bak nao e nebell*.py.
        self.assertFalse(limpar.protegido(self.raiz / "nebell.py.bak"))

    def test_protege_mesmo_se_um_padrao_sair_errado(self):
        # Rede de seguranca: ainda que um grupo passe a pegar nebell.py,
        # o filtro de protegidos nao deixa.
        antes = limpar.GRUPOS

        try:
            limpar.GRUPOS = [("padrão largo demais", ["*.py"])]
            alvos = {c.name for _, lista in limpar.achar() for c in lista}
            self.assertNotIn("nebell.py", alvos)
            self.assertNotIn("test_nebell.py", alvos)
            self.assertNotIn("limpar.py", alvos)
            # mas ainda pega o que e inutil
            self.assertIn("jarvis.py", alvos)
        finally:
            limpar.GRUPOS = antes


class TestLimparVozes(LimparTest):
    def test_acha_as_vozes_sem_uso(self):
        nomes = {c.name for c in limpar.vozes_sem_uso()}
        self.assertEqual(
            nomes,
            {"miro", "cadu", "pt_BR-faber-medium.onnx",
             "pt_BR-faber-medium.onnx.json"},
        )

    def test_nao_mexe_na_voz_em_uso(self):
        nomes = {c.name for c in limpar.vozes_sem_uso()}
        self.assertNotIn("nebell", nomes)

    def test_vozes_ficam_fora_da_limpeza_normal(self):
        # Sao grandes e a pessoa pode querer guardar: pergunta a parte.
        alvos = {c.name for _, lista in limpar.achar() for c in lista}
        self.assertNotIn("miro", alvos)
        self.assertNotIn("cadu", alvos)

    def test_sem_pasta_de_vozes_nao_quebra(self):
        with TemporaryDirectory() as temp:
            limpar.AQUI = Path(temp)
            self.assertEqual(limpar.vozes_sem_uso(), [])


class TestLimparMover(LimparTest):
    def test_mover_leva_para_o_lixo(self):
        alvo = self.raiz / "jarvis.py"
        feitos, bytes_, erros = limpar.mover_ou_apagar([alvo], apagar=False)

        self.assertEqual(feitos, 1)
        self.assertEqual(erros, [])
        self.assertFalse(alvo.exists())
        self.assertTrue((self.raiz / "_lixo" / "jarvis.py").exists())

    def test_mover_conta_os_bytes(self):
        alvo = self.raiz / "jarvis.py"
        tamanho = alvo.stat().st_size
        _, bytes_, _ = limpar.mover_ou_apagar([alvo], apagar=False)
        self.assertEqual(bytes_, tamanho)

    def test_mover_pasta_inteira(self):
        alvo = self.raiz / "__pycache__"
        feitos, _, erros = limpar.mover_ou_apagar([alvo], apagar=False)

        self.assertEqual(feitos, 1)
        self.assertEqual(erros, [])
        self.assertFalse(alvo.exists())
        self.assertTrue(
            (self.raiz / "_lixo" / "__pycache__" / "nebell.cpython-313.pyc")
            .exists()
        )

    def test_mover_duas_vezes_nao_quebra(self):
        (self.raiz / "_lixo").mkdir()
        (self.raiz / "_lixo" / "jarvis.py").write_text("velho")

        feitos, _, erros = limpar.mover_ou_apagar(
            [self.raiz / "jarvis.py"], apagar=False
        )

        self.assertEqual(feitos, 1)
        self.assertEqual(erros, [])

    def test_apagar_apaga(self):
        alvo = self.raiz / "jarvis.py"
        feitos, _, erros = limpar.mover_ou_apagar([alvo], apagar=True)

        self.assertEqual(feitos, 1)
        self.assertEqual(erros, [])
        self.assertFalse(alvo.exists())
        self.assertFalse((self.raiz / "_lixo").exists())

    def test_apagar_pasta(self):
        alvo = self.raiz / ".venv_antigo"
        feitos, _, erros = limpar.mover_ou_apagar([alvo], apagar=True)

        self.assertEqual(feitos, 1)
        self.assertEqual(erros, [])
        self.assertFalse(alvo.exists())

    def test_o_que_nao_existe_e_anotado_nao_estourado(self):
        feitos, _, erros = limpar.mover_ou_apagar(
            [self.raiz / "nao_existe.py"], apagar=True
        )

        self.assertEqual(feitos, 0)
        self.assertEqual(len(erros), 1)

    def test_limpeza_inteira_deixa_o_programa_de_pe(self):
        todos = [c for _, lista in limpar.achar() for c in lista]
        limpar.mover_ou_apagar(todos, apagar=True)

        sobrou = self.nomes()

        for nome in ATUAIS + BATS_ATUAIS:
            self.assertIn(nome, sobrou, nome)

        self.assertIn("memoria.db", sobrou)
        self.assertIn("memoria.db-wal", sobrou)
        self.assertIn("microfone.json", sobrou)
        self.assertIn(".venv", sobrou)
        self.assertIn("voices", sobrou)
        self.assertIn("hud", sobrou)
        self.assertIn("workspace", sobrou)

        for nome in INUTEIS + WAVS:
            self.assertNotIn(nome, sobrou, nome)


class TestLimparMedidas(unittest.TestCase):
    def test_tamanho_legivel(self):
        self.assertEqual(limpar.tamanho_legivel(0), "0 B")
        self.assertEqual(limpar.tamanho_legivel(512), "512 B")
        self.assertIn("KB", limpar.tamanho_legivel(2048))
        self.assertIn("MB", limpar.tamanho_legivel(5 * 1024 * 1024))
        self.assertIn("GB", limpar.tamanho_legivel(3 * 1024 ** 3))

    def test_peso_de_arquivo_e_de_pasta(self):
        with TemporaryDirectory() as temp:
            raiz = Path(temp)
            (raiz / "a.txt").write_bytes(b"x" * 100)
            (raiz / "sub").mkdir()
            (raiz / "sub" / "b.txt").write_bytes(b"y" * 50)

            self.assertEqual(limpar.peso(raiz / "a.txt"), 100)
            self.assertEqual(limpar.peso(raiz), 150)

    def test_pergunta_sem_teclado_responde_nao(self):
        def estourar(_):
            raise EOFError

        with patch("builtins.input", estourar):
            self.assertFalse(limpar.perguntar("vai?", padrao_sim=True))

    def test_enter_aceita_o_padrao(self):
        with patch("builtins.input", lambda _: ""):
            self.assertTrue(limpar.perguntar("vai?", padrao_sim=True))
            self.assertFalse(limpar.perguntar("vai?", padrao_sim=False))

    def test_entende_sim_e_nao(self):
        for resposta in ("s", "S", "sim", " Sim ", "y", "yes"):
            with patch("builtins.input", lambda _, r=resposta: r):
                self.assertTrue(limpar.perguntar("vai?"), resposta)

        for resposta in ("n", "N", "não", "nao", "qualquer"):
            with patch("builtins.input", lambda _, r=resposta: r):
                self.assertFalse(limpar.perguntar("vai?"), resposta)


# ========================  empacotar  =======================


class EmpacotarTest(PastaFalsa):
    modulo = empacotar

    def pacote(self, completo=False, todas=False):
        entram, ficaram = empacotar.escolher(self.raiz, completo, todas)
        return {nome for _, nome in entram}, ficaram


class TestEmpacotarEscolher(EmpacotarTest):
    def test_o_codigo_vai(self):
        nomes, _ = self.pacote()

        for nome in ATUAIS:
            self.assertIn(nome, nomes, nome)

    def test_os_atalhos_vao(self):
        nomes, _ = self.pacote()

        for nome in BATS_ATUAIS:
            self.assertIn(nome, nomes, nome)

    def test_a_memoria_vai(self):
        nomes, _ = self.pacote()
        self.assertIn("memoria.db", nomes)

    def test_a_interface_vai(self):
        nomes, _ = self.pacote()
        self.assertIn("hud/index.html", nomes)

    def test_a_voz_em_uso_vai(self):
        nomes, _ = self.pacote()
        self.assertIn("voices/nebell/model.onnx", nomes)
        self.assertIn("voices/nebell/model.onnx.json", nomes)

    def test_o_venv_nao_vai(self):
        # Ele guarda o caminho do Python de origem; nao roda no destino.
        nomes, _ = self.pacote()
        self.assertFalse([n for n in nomes if n.startswith(".venv/")])

    def test_o_microfone_nao_vai(self):
        nomes, _ = self.pacote()
        self.assertNotIn("microfone.json", nomes)

    def test_o_diario_do_sqlite_nao_vai(self):
        nomes, _ = self.pacote()
        self.assertNotIn("memoria.db-wal", nomes)
        self.assertNotIn("memoria.db-shm", nomes)

    def test_pastas_de_trabalho_nao_vao(self):
        nomes, _ = self.pacote()

        for prefixo in ("__pycache__/", "audio_temp/", "backup/",
                        ".venv_antigo/", "_lixo/"):
            self.assertFalse(
                [n for n in nomes if n.startswith(prefixo)], prefixo
            )

    def test_a_pagina_antiga_da_interface_nao_vai(self):
        nomes, _ = self.pacote()
        self.assertNotIn("hud/index.anterior.html", nomes)

    def test_as_vozes_sem_uso_nao_vao(self):
        nomes, _ = self.pacote()
        vozes = {n for n in nomes if n.startswith("voices/")}

        self.assertFalse([n for n in vozes if "miro" in n])
        self.assertFalse([n for n in vozes if "cadu" in n])
        self.assertFalse([n for n in vozes if "faber" in n])
        self.assertTrue(vozes)

    def test_com_todas_as_vozes_elas_vao(self):
        nomes, _ = self.pacote(todas=True)
        self.assertIn("voices/miro/model.onnx", nomes)
        self.assertIn("voices/cadu/model.onnx", nomes)
        self.assertIn("voices/pt_BR-faber-medium.onnx", nomes)

    def test_o_modelo_de_escuta_fica_fora_por_padrao(self):
        nomes, _ = self.pacote()
        self.assertNotIn("whisper_models/model.bin", nomes)

    def test_com_completo_o_modelo_de_escuta_vai(self):
        nomes, _ = self.pacote(completo=True)
        self.assertIn("whisper_models/model.bin", nomes)

    def test_o_workspace_vai(self):
        nomes, _ = self.pacote()
        self.assertIn("workspace/nota.txt", nomes)

    def test_diz_o_que_ficou_de_fora_e_por_que(self):
        _, ficaram = self.pacote()
        self.assertTrue(ficaram)

        for motivo, bytes_ in ficaram.items():
            self.assertTrue(motivo.strip())
            self.assertGreaterEqual(bytes_, 0)

    def test_barra_do_windows_virou_barra_do_zip(self):
        nomes, _ = self.pacote()
        self.assertFalse([n for n in nomes if "\\" in n])

    def test_nao_empacota_um_pacote(self):
        (self.raiz / "NEBELL_2026-01-01.zip").write_bytes(b"z" * 128)
        nomes, _ = self.pacote()
        self.assertFalse([n for n in nomes if n.endswith(".zip")])

    def test_pasta_vazia_nao_quebra(self):
        with TemporaryDirectory() as temp:
            entram, _ = empacotar.escolher(Path(temp))
            self.assertEqual(entram, [])


class TestEmpacotarZip(EmpacotarTest):
    def gravar(self, completo=False):
        entram, _ = empacotar.escolher(self.raiz, completo, False)
        destino = self.raiz.parent / "pacote.zip"

        with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as pacote:
            for caminho, nome in entram:
                pacote.write(caminho, f"NEBELL/{nome}")

            pacote.writestr("NEBELL/LEIA-ME.txt", empacotar.LEIA_ME)

        return destino

    def test_o_zip_abre_e_tem_tudo_sob_uma_pasta(self):
        destino = self.gravar()

        with zipfile.ZipFile(destino) as pacote:
            self.assertIsNone(pacote.testzip())
            nomes = pacote.namelist()

        self.assertTrue(nomes)

        for nome in nomes:
            self.assertTrue(nome.startswith("NEBELL/"), nome)

    def test_o_leia_me_vai_dentro(self):
        destino = self.gravar()

        with zipfile.ZipFile(destino) as pacote:
            texto = pacote.read("NEBELL/LEIA-ME.txt").decode("utf-8")

        self.assertIn("Instalar_Pacotes.bat", texto)
        self.assertIn("ollama", texto.lower())

    def test_o_conteudo_chega_igual(self):
        esperado = (self.raiz / "nebell.py").read_bytes()
        destino = self.gravar()

        with zipfile.ZipFile(destino) as pacote:
            self.assertEqual(pacote.read("NEBELL/nebell.py"), esperado)

    def test_descompactado_da_para_rodar(self):
        destino = self.gravar()

        with TemporaryDirectory() as temp:
            with zipfile.ZipFile(destino) as pacote:
                pacote.extractall(temp)

            saiu = Path(temp) / "NEBELL"

            # O minimo para por de pe no outro PC.
            for nome in ("nebell.py", "nebell_hud.py", "Instalar_Pacotes.bat",
                         "Iniciar_NEBELL.bat", "LEIA-ME.txt"):
                self.assertTrue((saiu / nome).exists(), nome)

            self.assertTrue((saiu / "voices" / "nebell" / "model.onnx").exists())
            self.assertTrue((saiu / "hud" / "index.html").exists())
            self.assertFalse((saiu / ".venv").exists())


class TestEmpacotarMedidas(unittest.TestCase):
    def test_tamanho_legivel(self):
        self.assertEqual(empacotar.tamanho_legivel(0), "0 B")
        self.assertIn("MB", empacotar.tamanho_legivel(3 * 1024 * 1024))

    def test_fora_por_nome(self):
        self.assertTrue(empacotar.fora_por_nome("microfone.json"))
        self.assertTrue(empacotar.fora_por_nome("memoria.db-wal"))
        self.assertTrue(empacotar.fora_por_nome("algo.pyc"))
        self.assertTrue(empacotar.fora_por_nome("NEBELL_2026.zip"))
        self.assertFalse(empacotar.fora_por_nome("nebell.py"))
        self.assertFalse(empacotar.fora_por_nome("memoria.db"))

    def test_o_leia_me_explica_o_venv(self):
        texto = empacotar.LEIA_ME.lower()
        self.assertIn("venv", texto)
        self.assertIn("python", texto)


# ====================  um não bate no outro  ================


class TestAsDuasJuntas(unittest.TestCase):
    """O que a limpeza tira nao pode ser o que o pacote precisa."""

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.raiz = Path(self.temp.name) / "NEBELL"
        self.raiz.mkdir()
        montar(self.raiz)

        self.antes = (limpar.AQUI, empacotar.AQUI)
        limpar.AQUI = self.raiz
        empacotar.AQUI = self.raiz

    def tearDown(self):
        limpar.AQUI, empacotar.AQUI = self.antes
        self.temp.cleanup()

    def test_limpar_nao_tira_nada_que_o_pacote_leva(self):
        entram, _ = empacotar.escolher(self.raiz)
        no_pacote = {caminho for caminho, _ in entram}

        for _, alvos in limpar.achar():
            for alvo in alvos:
                if alvo.is_file():
                    self.assertNotIn(alvo, no_pacote, alvo.name)
                else:
                    dentro = {
                        c for c in no_pacote
                        if alvo in c.parents
                    }
                    self.assertFalse(dentro, f"{alvo.name}: {dentro}")

    def test_depois_de_limpar_o_pacote_continua_completo(self):
        antes, _ = empacotar.escolher(self.raiz)
        antes = {nome for _, nome in antes}

        todos = [c for _, lista in limpar.achar() for c in lista]
        limpar.mover_ou_apagar(todos, apagar=True)

        depois, _ = empacotar.escolher(self.raiz)
        depois = {nome for _, nome in depois}

        self.assertEqual(antes, depois)

    def test_o_lixo_nao_entra_no_pacote(self):
        todos = [c for _, lista in limpar.achar() for c in lista]
        limpar.mover_ou_apagar(todos, apagar=False)

        self.assertTrue((self.raiz / "_lixo").exists())

        entram, _ = empacotar.escolher(self.raiz)
        nomes = {nome for _, nome in entram}
        self.assertFalse([n for n in nomes if n.startswith("_lixo/")])

    def test_a_voz_em_uso_e_a_mesma_nos_dois(self):
        self.assertEqual(limpar.VOZ_EM_USO, empacotar.VOZ_EM_USO)

class TestOndeOPacoteCai(unittest.TestCase):
    """
    O zip tem de cair onde a pessoa ACHA.

    Antes ele caia dentro da propria pasta do NEBELL, no meio de
    quarenta arquivos, e quem rodava o Empacotar.bat nao achava o
    pacote depois.
    """

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.antigo = empacotar.AQUI
        empacotar.AQUI = self.base / "NEBELL"
        empacotar.AQUI.mkdir(parents=True)

    def tearDown(self):
        empacotar.AQUI = self.antigo
        self.temp.cleanup()

    def test_prefere_a_area_de_trabalho(self):
        mesa = self.base / "casa" / "Desktop"
        mesa.mkdir(parents=True)

        with patch.object(Path, "home", staticmethod(lambda: self.base / "casa")):
            self.assertEqual(empacotar.onde_gravar(), mesa)

    def test_o_onedrive_vem_na_frente(self):
        # Com o OneDrive ligado, a area de trabalho de verdade e a dele;
        # a outra fica velha e vazia.
        casa = self.base / "casa"
        (casa / "Desktop").mkdir(parents=True)
        nuvem = casa / "OneDrive" / "Desktop"
        nuvem.mkdir(parents=True)

        with patch.object(Path, "home", staticmethod(lambda: casa)):
            self.assertEqual(empacotar.onde_gravar(), nuvem)

    def test_aceita_o_nome_em_portugues(self):
        casa = self.base / "casa"
        mesa = casa / "Área de Trabalho"
        mesa.mkdir(parents=True)

        with patch.object(Path, "home", staticmethod(lambda: casa)):
            self.assertEqual(empacotar.onde_gravar(), mesa)

    def test_sem_area_de_trabalho_fica_ao_lado_da_pasta(self):
        casa = self.base / "casa"
        casa.mkdir()

        with patch.object(Path, "home", staticmethod(lambda: casa)):
            self.assertEqual(empacotar.onde_gravar(), empacotar.AQUI.parent)

    def test_nunca_devolve_um_lugar_onde_nao_da_para_escrever(self):
        casa = self.base / "casa"
        mesa = casa / "Desktop"
        mesa.mkdir(parents=True)

        original = Path.write_text

        def recusar(self, *args, **kwargs):
            if mesa in self.parents:
                raise PermissionError("pasta sincronizada recusou")

            return original(self, *args, **kwargs)

        with patch.object(Path, "home", staticmethod(lambda: casa)), \
                patch.object(Path, "write_text", recusar):
            escolhido = empacotar.onde_gravar()

        self.assertNotEqual(escolhido, mesa)

    def test_nao_deixa_lixo_de_teste_atras(self):
        casa = self.base / "casa"
        mesa = casa / "Desktop"
        mesa.mkdir(parents=True)

        with patch.object(Path, "home", staticmethod(lambda: casa)):
            empacotar.onde_gravar()

        self.assertEqual(list(mesa.iterdir()), [])

    def test_em_ultimo_caso_a_propria_pasta(self):
        # Nada existe e nada aceita escrita: ainda devolve algo.
        with patch.object(Path, "home", staticmethod(lambda: self.base / "nao_existe")), \
                patch.object(Path, "is_dir", lambda self: False):
            self.assertEqual(empacotar.onde_gravar(), empacotar.AQUI)

    def test_mostrar_no_explorer_fora_do_windows_nao_estoura(self):
        with patch.object(empacotar.os, "name", "posix"):
            self.assertFalse(
                empacotar.mostrar_no_explorer(self.base / "x.zip")
            )

    def test_mostrar_no_explorer_chama_o_explorer_com_select(self):
        alvo = self.base / "NEBELL_hoje.zip"

        with patch.object(empacotar.os, "name", "nt"), \
                patch.object(empacotar.subprocess, "Popen") as popen:
            self.assertTrue(empacotar.mostrar_no_explorer(alvo))

        comando = popen.call_args[0][0]
        self.assertEqual(comando[0], "explorer")
        self.assertIn("/select,", comando[1])
        self.assertIn(str(alvo), comando[1])

    def test_explorer_que_falha_nao_derruba_o_empacotamento(self):
        with patch.object(empacotar.os, "name", "nt"), \
                patch.object(
                    empacotar.subprocess, "Popen",
                    side_effect=OSError("sem explorer")
                ):
            self.assertFalse(
                empacotar.mostrar_no_explorer(self.base / "x.zip")
            )

    def test_o_zip_nao_cai_mais_dentro_da_pasta_do_nebell(self):
        fonte = Path(empacotar.__file__).read_text(encoding="utf-8")
        corpo = fonte[fonte.index("def main("):]

        # O destino sai do onde_gravar(), nao de AQUI.
        self.assertIn("pasta = onde_gravar()", corpo)
        self.assertNotIn('destino = AQUI / f"NEBELL_', corpo)


if __name__ == "__main__":
    unittest.main(verbosity=2)
