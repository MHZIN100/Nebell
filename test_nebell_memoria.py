"""
Testes da memoria de longo prazo do NEBELL.

Usa um banco de verdade em pasta temporaria: SQLite e da biblioteca
padrao, entao nao ha o que simular aqui.

Uso:  python test_nebell_memoria.py
"""

import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import nebell_memoria as M


class MemoriaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nebell_mem_"))
        self.mem = M.Memoria(self.tmp / "memoria.db", log=lambda *a: None)
        self.assertTrue(self.mem.abrir())

    def tearDown(self):
        self.mem.fechar()


# ============================================================
# BASICO
# ============================================================

class TestAbertura(MemoriaTest):
    def test_cria_o_arquivo(self):
        self.assertTrue((self.tmp / "memoria.db").exists())

    def test_cria_as_tabelas(self):
        nomes = {
            linha["name"] for linha in self.mem.consultar(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        for tabela in ("conversas", "mensagens", "fatos", "projetos",
                       "notas", "arquivos", "comandos", "meta"):
            self.assertIn(tabela, nomes)

    def test_abrir_duas_vezes_nao_quebra(self):
        outra = M.Memoria(self.tmp / "memoria.db", log=lambda *a: None)
        self.assertTrue(outra.abrir())
        outra.fechar()

    def test_pasta_inexistente_e_criada(self):
        fundo = M.Memoria(
            self.tmp / "a" / "b" / "c.db", log=lambda *a: None
        )
        self.assertTrue(fundo.abrir())
        fundo.fechar()

    def test_abrir_que_falha_nao_derruba(self):
        # Antes isto usava um caminho "impossível" (/proc no Linux, Z:
        # no Windows) e dependia do sistema de arquivos: na máquina do
        # usuário o Z: existia e o teste quebrou sem haver bug. O que
        # importa é o comportamento: falhar ao abrir não pode estourar.
        ruim = M.Memoria(self.tmp / "qualquer.db", log=lambda *a: None)

        with mock.patch.object(
            M.sqlite3, "connect",
            side_effect=M.sqlite3.OperationalError("unable to open")
        ):
            self.assertFalse(ruim.abrir())

        self.assertFalse(ruim.disponivel)

    def test_erro_inesperado_ao_abrir_tambem_e_contido(self):
        ruim = M.Memoria(self.tmp / "outro.db", log=lambda *a: None)

        with mock.patch.object(
            M.sqlite3, "connect", side_effect=RuntimeError("disco pegou fogo")
        ):
            self.assertFalse(ruim.abrir())
        # Tudo continua respondendo, só sem guardar nada.
        self.assertFalse(ruim.registrar_mensagem("user", "oi"))
        self.assertEqual(ruim.buscar_mensagens("oi"), [])
        self.assertEqual(ruim.briefing(), "")

    def test_numeros_iniciais(self):
        numeros = self.mem.numeros()
        self.assertEqual(numeros["mensagens"], 0)
        self.assertIn("arquivo", numeros)


# ============================================================
# CONVERSAS E MENSAGENS
# ============================================================

class TestConversas(MemoriaTest):
    def test_registra_e_conta(self):
        self.mem.iniciar_conversa("voz")
        self.mem.registrar_mensagem("user", "bom dia")
        self.mem.registrar_mensagem("assistant", "bom dia, senhor")

        self.assertEqual(self.mem.numeros()["mensagens"], 2)

        linhas = self.mem.consultar("SELECT total, modo FROM conversas")
        self.assertEqual(linhas[0]["total"], 2)
        self.assertEqual(linhas[0]["modo"], "voz")

    def test_mensagem_sem_conversa_abre_uma(self):
        self.assertIsNone(self.mem.conversa_id)
        self.mem.registrar_mensagem("user", "oi")
        self.assertIsNotNone(self.mem.conversa_id)

    def test_ignora_vazio_e_papel_estranho(self):
        self.assertFalse(self.mem.registrar_mensagem("user", "   "))
        self.assertFalse(self.mem.registrar_mensagem("system", "segredo"))
        self.assertFalse(self.mem.registrar_mensagem("tool", "resultado"))
        self.assertEqual(self.mem.numeros()["mensagens"], 0)

    def test_corta_mensagem_gigante(self):
        self.mem.registrar_mensagem("user", "x" * 99999)
        linha = self.mem.consultar("SELECT conteudo FROM mensagens")[0]
        self.assertEqual(len(linha["conteudo"]), M.MAX_MESSAGE_CHARS)

    def test_encerrar_grava_o_resumo(self):
        self.mem.iniciar_conversa()
        self.mem.registrar_mensagem("user", "oi")
        self.mem.encerrar_conversa(resumo="Falamos do carrinho.", titulo="Carrinho")

        linha = self.mem.consultar("SELECT resumo, titulo, fim FROM conversas")[0]
        self.assertEqual(linha["resumo"], "Falamos do carrinho.")
        self.assertEqual(linha["titulo"], "Carrinho")
        self.assertIsNotNone(linha["fim"])

    def test_encerrar_sem_conversa_nao_quebra(self):
        self.mem.encerrar_conversa(resumo="nada")

    def test_material_para_resumo(self):
        self.mem.iniciar_conversa()
        self.mem.registrar_mensagem("user", "primeira")
        self.mem.registrar_mensagem("assistant", "segunda")

        material = self.mem.material_para_resumo()
        self.assertEqual(len(material), 2)
        self.assertEqual(material[0]["conteudo"], "primeira")


# ============================================================
# BUSCA NO QUE JA FOI DITO
# ============================================================

class TestBusca(MemoriaTest):
    def povoar(self):
        self.mem.iniciar_conversa()
        self.mem.registrar_mensagem(
            "user", "estou fazendo um carrinho seguidor de linha com Arduino"
        )
        self.mem.registrar_mensagem(
            "assistant", "O driver HW-095 serve bem para os motores"
        )
        self.mem.encerrar_conversa(resumo="Carrinho seguidor de linha")

        self.mem.iniciar_conversa()
        self.mem.registrar_mensagem("user", "liga os LEDs pelos dedos no MediaPipe")
        self.mem.encerrar_conversa(resumo="LEDs com MediaPipe")

        # Conversa atual, que não deve aparecer nas buscas por padrão.
        self.mem.iniciar_conversa()
        self.mem.registrar_mensagem("user", "assunto de agora sobre carrinho")

    def test_acha_por_palavra(self):
        self.povoar()
        achados = self.mem.buscar_mensagens("carrinho")
        self.assertTrue(achados)
        self.assertTrue(
            any("seguidor de linha" in a["conteudo"] for a in achados)
        )

    def test_nao_devolve_a_conversa_atual(self):
        self.povoar()
        achados = self.mem.buscar_mensagens("carrinho")
        self.assertFalse(
            any("assunto de agora" in a["conteudo"] for a in achados)
        )

    def test_pode_incluir_a_atual(self):
        self.povoar()
        achados = self.mem.buscar_mensagens("carrinho", incluir_atual=True)
        self.assertTrue(
            any("assunto de agora" in a["conteudo"] for a in achados)
        )

    def test_acha_pelo_plural(self):
        self.povoar()
        self.assertTrue(self.mem.buscar_mensagens("motores"))

    def test_acha_o_que_ele_mesmo_disse(self):
        self.povoar()
        achados = self.mem.buscar_mensagens("HW-095")
        self.assertTrue(achados)
        self.assertEqual(achados[0]["papel"], "assistant")

    def test_busca_vazia(self):
        self.povoar()
        self.assertEqual(self.mem.buscar_mensagens("   "), [])

    def test_sem_resultado(self):
        self.povoar()
        self.assertEqual(self.mem.buscar_mensagens("submarino nuclear"), [])

    def test_respeita_o_limite(self):
        self.mem.iniciar_conversa()
        for i in range(20):
            self.mem.registrar_mensagem("user", f"teste numero {i}")
        self.mem.encerrar_conversa()
        self.mem.iniciar_conversa()

        self.assertLessEqual(len(self.mem.buscar_mensagens("teste", limite=4)), 4)

    def test_funciona_sem_fts5(self):
        """Em um SQLite sem FTS5, a busca cai para LIKE."""
        self.povoar()
        self.mem.fts = False
        achados = self.mem.buscar_mensagens("carrinho")
        self.assertTrue(achados)

    def test_conversas_recentes_so_com_resumo(self):
        self.povoar()
        recentes = self.mem.conversas_recentes(limite=5)
        self.assertEqual(len(recentes), 2)
        self.assertTrue(all(c["resumo"] for c in recentes))

    def test_transcricao(self):
        self.povoar()
        primeira = self.mem.conversas_recentes(limite=5)[-1]
        falas = self.mem.transcricao(primeira["id"])
        self.assertEqual(len(falas), 2)


# ============================================================
# FATOS
# ============================================================

class TestFatos(MemoriaTest):
    def test_guardar_e_listar(self):
        deu, _ = self.mem.guardar_fato("mora em Cachoeira, Bahia")
        self.assertTrue(deu)
        self.assertEqual(len(self.mem.listar_fatos()), 1)

    def test_nao_duplica_ignorando_acento_e_caixa(self):
        self.mem.guardar_fato("Gosta de Café")
        deu, msg = self.mem.guardar_fato("gosta de cafe")
        self.assertFalse(deu)
        self.assertIn("já está", msg)

    def test_categoria_preferencia(self):
        self.mem.guardar_fato("respostas curtas", categoria="preferencia")
        self.assertEqual(len(self.mem.listar_fatos(categoria="preferencia")), 1)
        self.assertEqual(len(self.mem.listar_fatos(categoria="geral")), 0)

    def test_esquecer_por_assunto(self):
        self.mem.guardar_fato("tem um carrinho seguidor de linha")
        self.mem.guardar_fato("usa Arduino Uno")
        self.assertEqual(self.mem.esquecer_fato("carrinho"), 1)
        self.assertEqual(len(self.mem.listar_fatos()), 1)

    def test_esquecer_sem_achar(self):
        self.assertEqual(self.mem.esquecer_fato("inexistente"), 0)

    def test_fato_vazio(self):
        deu, _ = self.mem.guardar_fato("   ")
        self.assertFalse(deu)


# ============================================================
# PROJETOS
# ============================================================

class TestProjetos(MemoriaTest):
    def test_criar_e_achar(self):
        self.mem.salvar_projeto("Carro seguidor de linha", "Arduino com HW-095")
        projeto = self.mem.achar_projeto("carro seguidor de linha")
        self.assertIsNotNone(projeto)
        self.assertIn("HW-095", projeto["descricao"])

    def test_acha_por_pedaco_do_nome(self):
        self.mem.salvar_projeto("Carro seguidor de linha")
        self.assertIsNotNone(self.mem.achar_projeto("seguidor"))

    def test_acha_sem_acento(self):
        self.mem.salvar_projeto("Projeto Nebell São Paulo")
        self.assertIsNotNone(self.mem.achar_projeto("nebell sao paulo"))

    def test_acha_por_semelhanca(self):
        """Você registra "Carro seguidor de linha" e chama de "carrinho"."""
        self.mem.salvar_projeto("Carro seguidor de linha")
        achado = self.mem.achar_projeto("carrinho")
        self.assertIsNotNone(achado)
        self.assertEqual(achado["nome"], "Carro seguidor de linha")

    def test_semelhanca_em_outros_casos(self):
        self.mem.salvar_projeto("Site Zeon")
        self.mem.salvar_projeto("Projeto dos LEDs com MediaPipe")
        self.assertEqual(self.mem.achar_projeto("sites")["nome"], "Site Zeon")
        self.assertIn("LEDs", self.mem.achar_projeto("mediapipes")["nome"])

    def test_semelhanca_nao_inventa(self):
        self.mem.salvar_projeto("Carro seguidor de linha")
        self.assertIsNone(self.mem.achar_projeto("submarino nuclear"))
        self.assertIsNone(self.mem.achar_projeto("planilha de impostos"))

    def test_semelhanca_escolhe_o_mais_proximo(self):
        self.mem.salvar_projeto("Carro seguidor de linha")
        self.mem.salvar_projeto("Carrinho de compras do site")
        self.assertEqual(
            self.mem.achar_projeto("carrinho")["nome"],
            "Carrinho de compras do site",
        )

    def test_palavra_curta_nao_dispara_semelhanca(self):
        self.mem.salvar_projeto("Carro seguidor de linha")
        self.assertIsNone(self.mem.achar_projeto("de"))

    def test_salvar_de_novo_atualiza(self):
        self.mem.salvar_projeto("Site Zeon", "versão inicial")
        deu, msg = self.mem.salvar_projeto("site zeon", "com catálogo")
        self.assertTrue(deu)
        self.assertIn("atualizado", msg)
        self.assertEqual(len(self.mem.listar_projetos()), 1)
        self.assertIn("catálogo", self.mem.achar_projeto("zeon")["descricao"])

    def test_atualizacao_preserva_o_que_nao_veio(self):
        self.mem.salvar_projeto("Site Zeon", "descrição original")
        self.mem.salvar_projeto("Site Zeon", status="pausado")
        projeto = self.mem.achar_projeto("zeon")
        self.assertEqual(projeto["descricao"], "descrição original")
        self.assertEqual(projeto["status"], "pausado")

    def test_anotar(self):
        self.mem.salvar_projeto("Carrinho")
        deu, _ = self.mem.anotar_projeto("carrinho", "o sensor da direita falha")
        self.assertTrue(deu)

        projeto, notas = self.mem.notas_do_projeto("carrinho")
        self.assertEqual(len(notas), 1)
        self.assertIn("sensor", notas[0]["texto"])

    def test_anotar_cria_o_projeto_se_nao_existir(self):
        deu, msg = self.mem.anotar_projeto("Projeto Novo", "primeira ideia")
        self.assertTrue(deu)
        self.assertIsNotNone(self.mem.achar_projeto("projeto novo"))

    def test_notas_de_projeto_inexistente(self):
        projeto, notas = self.mem.notas_do_projeto("nada disso")
        self.assertIsNone(projeto)
        self.assertEqual(notas, [])

    def test_listar_por_status(self):
        self.mem.salvar_projeto("Ativo um")
        self.mem.salvar_projeto("Parado", status="pausado")
        self.assertEqual(len(self.mem.listar_projetos(status="ativo")), 1)

    def test_projeto_mais_recente(self):
        self.mem.salvar_projeto("Antigo")
        self.mem.salvar_projeto("Recente")
        self.mem.anotar_projeto("Recente", "mexi nisso agora")
        self.assertEqual(self.mem.projeto_mais_recente()["nome"], "Recente")

    def test_apagar_projeto_leva_as_notas(self):
        self.mem.salvar_projeto("Temporario")
        self.mem.anotar_projeto("Temporario", "nota")
        projeto = self.mem.achar_projeto("Temporario")
        self.mem.executar("DELETE FROM projetos WHERE id = ?", (projeto["id"],))
        self.assertEqual(self.mem.numeros()["projetos"], 0)
        sobrou = self.mem.consultar("SELECT COUNT(*) AS n FROM notas")
        self.assertEqual(sobrou[0]["n"], 0)

    def test_nome_vazio(self):
        deu, _ = self.mem.salvar_projeto("  ")
        self.assertFalse(deu)


# ============================================================
# ARQUIVOS
# ============================================================

class TestArquivos(MemoriaTest):
    def test_registrar_com_tamanho_real(self):
        alvo = self.tmp / "relatorio.txt"
        alvo.write_text("conteúdo de teste", encoding="utf-8")

        deu, _ = self.mem.registrar_arquivo(alvo, resumo="relatório do mês")
        self.assertTrue(deu)

        achados = self.mem.buscar_arquivos("relatorio")
        self.assertEqual(len(achados), 1)
        self.assertGreater(achados[0]["tamanho"], 0)

    def test_arquivo_que_nao_existe_mais(self):
        deu, _ = self.mem.registrar_arquivo("C:\\sumiu\\antigo.pdf")
        self.assertTrue(deu)
        self.assertEqual(len(self.mem.buscar_arquivos("antigo")), 1)

    def test_registrar_de_novo_conta_as_vezes(self):
        self.mem.registrar_arquivo("C:\\x\\dados.csv")
        self.mem.registrar_arquivo("C:\\x\\dados.csv")
        achado = self.mem.buscar_arquivos("dados")[0]
        self.assertEqual(achado["vezes"], 2)

    def test_resumo_antigo_e_preservado(self):
        self.mem.registrar_arquivo("C:\\x\\a.py", resumo="script do carrinho")
        self.mem.registrar_arquivo("C:\\x\\a.py")
        self.assertEqual(
            self.mem.buscar_arquivos("a.py")[0]["resumo"], "script do carrinho"
        )

    def test_vincular_a_projeto(self):
        self.mem.salvar_projeto("Carrinho")
        self.mem.registrar_arquivo("C:\\x\\sensor.ino", projeto="carrinho")
        self.assertEqual(
            self.mem.buscar_arquivos("sensor")[0]["projeto"], "Carrinho"
        )

    def test_busca_pelo_resumo(self):
        self.mem.registrar_arquivo("C:\\x\\z1.bin", resumo="firmware do ESP32")
        self.assertTrue(self.mem.buscar_arquivos("firmware"))

    def test_listar_sem_termo(self):
        self.mem.registrar_arquivo("C:\\x\\um.txt")
        self.mem.registrar_arquivo("C:\\x\\dois.txt")
        self.assertEqual(len(self.mem.buscar_arquivos("")), 2)

    def test_caminho_vazio(self):
        deu, _ = self.mem.registrar_arquivo("  ")
        self.assertFalse(deu)


# ============================================================
# COMANDOS APRENDIDOS
# ============================================================

class TestComandos(MemoriaTest):
    def test_ensinar_e_casar(self):
        self.mem.ensinar_comando(
            "modo foco", "feche o navegador e diga apenas o essencial"
        )
        achado = self.mem.casar_comando("Nebell, ativa o modo foco agora")
        self.assertIsNotNone(achado)
        self.assertIn("essencial", achado["acao"])

    def test_casa_sem_acento_e_sem_caixa(self):
        self.mem.ensinar_comando("relatório da manhã", "leia minhas notas")
        self.assertIsNotNone(self.mem.casar_comando("faz o RELATORIO DA MANHA"))

    def test_casa_por_palavras_fora_de_ordem(self):
        self.mem.ensinar_comando("abrir projeto carrinho", "abra a pasta do carrinho")
        achado = self.mem.casar_comando("quero abrir o projeto do carrinho")
        self.assertIsNotNone(achado)

    def test_gatilho_mais_longo_ganha(self):
        self.mem.ensinar_comando("abrir projeto", "pergunte qual projeto")
        self.mem.ensinar_comando("abrir projeto carrinho", "abra a pasta do carrinho")

        achado = self.mem.casar_comando("abrir projeto carrinho")
        self.assertIn("pasta do carrinho", achado["acao"])

    def test_comando_com_ferramenta(self):
        deu, _ = self.mem.ensinar_comando(
            "boa noite", "desligue o bluetooth",
            ferramenta="bluetooth", argumentos={"acao": "desligar"},
        )
        self.assertTrue(deu)

        achado = self.mem.casar_comando("boa noite")
        self.assertEqual(achado["tipo"], "ferramenta")
        self.assertEqual(achado["ferramenta"], "bluetooth")
        self.assertEqual(json.loads(achado["argumentos"]), {"acao": "desligar"})

    def test_argumentos_em_texto(self):
        self.mem.ensinar_comando(
            "tocar meu som", "toque a playlist",
            ferramenta="tocar_musica", argumentos='{"busca": "rock"}',
        )
        achado = self.mem.casar_comando("tocar meu som")
        self.assertEqual(json.loads(achado["argumentos"])["busca"], "rock")

    def test_ensinar_de_novo_atualiza(self):
        self.mem.ensinar_comando("modo foco", "primeira versão")
        deu, msg = self.mem.ensinar_comando("modo foco", "segunda versão")
        self.assertTrue(deu)
        self.assertIn("atualizado", msg)
        self.assertEqual(len(self.mem.listar_comandos()), 1)

    def test_conta_os_usos(self):
        self.mem.ensinar_comando("modo foco", "faça algo")
        self.mem.casar_comando("modo foco")
        self.mem.casar_comando("modo foco")
        self.assertEqual(self.mem.listar_comandos()[0]["usos"], 2)

    def test_esquecer(self):
        self.mem.ensinar_comando("modo foco", "faça algo")
        self.assertEqual(self.mem.esquecer_comando("foco"), 1)
        self.assertEqual(self.mem.listar_comandos(), [])

    def test_gatilho_curto_e_recusado(self):
        deu, msg = self.mem.ensinar_comando("ok", "faça algo")
        self.assertFalse(deu)
        self.assertIn("curto", msg)

    def test_faltando_a_acao(self):
        deu, _ = self.mem.ensinar_comando("modo foco", "")
        self.assertFalse(deu)

    def test_frase_comum_nao_dispara(self):
        self.mem.ensinar_comando("modo foco", "faça algo")
        self.assertIsNone(self.mem.casar_comando("que horas são"))

    def test_texto_vazio_nao_dispara(self):
        self.mem.ensinar_comando("modo foco", "faça algo")
        self.assertIsNone(self.mem.casar_comando(""))


# ============================================================
# RESUMO PARA O PROMPT
# ============================================================

class TestBriefing(MemoriaTest):
    def test_vazio_no_comeco(self):
        self.assertEqual(self.mem.briefing(), "")

    def test_traz_fatos_projetos_e_comandos(self):
        self.mem.guardar_fato("mora em Cachoeira")
        self.mem.guardar_fato("prefere respostas curtas", categoria="preferencia")
        self.mem.salvar_projeto("Carrinho", "seguidor de linha")
        self.mem.ensinar_comando("modo foco", "seja breve")

        texto = self.mem.briefing()
        self.assertIn("Cachoeira", texto)
        self.assertIn("Preferências", texto)
        self.assertIn("Carrinho", texto)
        self.assertIn("modo foco", texto)

    def test_traz_o_resumo_da_conversa_anterior(self):
        self.mem.iniciar_conversa()
        self.mem.registrar_mensagem("user", "oi")
        self.mem.encerrar_conversa(resumo="Ajustamos o driver do motor")
        self.mem.iniciar_conversa()

        self.assertIn("driver do motor", self.mem.briefing())

    def test_projeto_pausado_fica_de_fora(self):
        self.mem.salvar_projeto("Parado", "nada agora", status="pausado")
        self.assertNotIn("Parado", self.mem.briefing())

    def test_nao_cresce_sem_limite(self):
        for i in range(120):
            self.mem.guardar_fato(f"fato numero {i}")

        texto = self.mem.briefing()
        self.assertLessEqual(texto.count("- fato numero"), M.MAX_FACTS_IN_PROMPT)


# ============================================================
# MANUTENCAO, MIGRACAO E CONCORRENCIA
# ============================================================

class TestManutencao(MemoriaTest):
    def test_importar_memoria_antiga(self):
        antigo = self.tmp / "memoria.json"
        antigo.write_text(
            json.dumps({"fatos": ["mora em Cachoeira", "usa Arduino"]}),
            encoding="utf-8",
        )

        self.assertEqual(self.mem.importar_json_antigo(antigo), 2)
        self.assertEqual(len(self.mem.listar_fatos()), 2)
        # O arquivo é marcado para não ser importado outra vez.
        self.assertFalse(antigo.exists())

    def test_importar_arquivo_que_nao_existe(self):
        self.assertEqual(
            self.mem.importar_json_antigo(self.tmp / "nada.json"), 0
        )

    def test_importar_json_corrompido(self):
        ruim = self.tmp / "ruim.json"
        ruim.write_text("{não é json", encoding="utf-8")
        self.assertEqual(self.mem.importar_json_antigo(ruim), 0)

    def test_podar_mensagens_antigas(self):
        self.mem.iniciar_conversa()

        with mock.patch.object(M, "MAX_MESSAGES_KEPT", 10):
            for i in range(25):
                self.mem.registrar_mensagem("user", f"mensagem {i}")

            cortadas = self.mem.podar()

        self.assertEqual(cortadas, 15)
        self.assertEqual(self.mem.numeros()["mensagens"], 10)

    def test_podar_quando_esta_pequeno(self):
        self.mem.registrar_mensagem("user", "oi")
        self.assertEqual(self.mem.podar(), 0)

    def test_sql_invalido_nao_derruba(self):
        self.assertIsNone(self.mem.executar("ISSO NÃO É SQL"))
        self.assertEqual(self.mem.consultar("NEM ISSO"), [])
        # O banco continua funcionando.
        self.assertTrue(self.mem.registrar_mensagem("user", "ainda vivo"))

    def test_varias_threads_escrevendo(self):
        self.mem.iniciar_conversa()
        erros = []

        def trabalhar(n):
            try:
                for i in range(30):
                    self.mem.registrar_mensagem("user", f"thread {n} item {i}")
                    self.mem.guardar_fato(f"fato da thread {n} numero {i}")
            except Exception as exc:
                erros.append(exc)

        threads = [threading.Thread(target=trabalhar, args=(n,)) for n in range(4)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(erros, [])
        self.assertEqual(self.mem.numeros()["mensagens"], 120)

    def test_dados_sobrevivem_ao_fechamento(self):
        self.mem.guardar_fato("isso tem de sobreviver")
        self.mem.salvar_projeto("Carrinho")
        self.mem.fechar()

        outra = M.Memoria(self.tmp / "memoria.db", log=lambda *a: None)
        outra.abrir()
        self.assertEqual(len(outra.listar_fatos()), 1)
        self.assertIsNotNone(outra.achar_projeto("carrinho"))
        outra.fechar()


class TestAjudantes(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(M.normalize("  Ação   ÚNICA "), "acao unica")

    def test_quando(self):
        hoje = datetime.now().isoformat(timespec="seconds")
        ontem = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
        semana = (datetime.now() - timedelta(days=4)).isoformat(timespec="seconds")
        velho = (datetime.now() - timedelta(days=200)).isoformat(timespec="seconds")

        self.assertIn("hoje", M.quando(hoje))
        self.assertIn("ontem", M.quando(ontem))
        self.assertIn("4 dias", M.quando(semana))
        self.assertIn("/", M.quando(velho))

    def test_quando_com_data_estranha(self):
        self.assertIn("algum momento", M.quando("isso não é data"))




# ============================================================
# DOWNLOAD DA VOZ
# ============================================================

import nebell_voz as V


class TestVozDownload(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nebell_voz_"))
        self.voices = self.tmp / "voices"

    def pasta_valida(self, chave="nebell", tamanho=None):
        pasta = self.voices / V.VOZES[chave]["pasta"]
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / "model.onnx").write_bytes(
            b"x" * (tamanho if tamanho is not None else V.TAMANHO_MINIMO + 10)
        )
        (pasta / "model.onnx.json").write_text(
            json.dumps({"audio": {"sample_rate": 22050}}), encoding="utf-8"
        )
        return pasta

    def test_conferir_pasta_vazia(self):
        certo, motivo = V.conferir(self.voices / "nada")
        self.assertFalse(certo)
        self.assertIn("faltou", motivo)

    def test_conferir_voz_boa(self):
        pasta = self.pasta_valida()
        certo, detalhe = V.conferir(pasta)
        self.assertTrue(certo)
        self.assertIn("22050 Hz", detalhe)

    def test_conferir_download_cortado(self):
        pasta = self.pasta_valida(tamanho=5000)
        certo, motivo = V.conferir(pasta)
        self.assertFalse(certo)
        self.assertIn("interrompido", motivo)

    def test_conferir_json_quebrado(self):
        pasta = self.pasta_valida()
        (pasta / "model.onnx.json").write_text("{quebrado", encoding="utf-8")
        certo, motivo = V.conferir(pasta)
        self.assertFalse(certo)
        self.assertIn("JSON", motivo)

    def test_conferir_sem_taxa(self):
        pasta = self.pasta_valida()
        (pasta / "model.onnx.json").write_text("{}", encoding="utf-8")
        self.assertFalse(V.conferir(pasta)[0])

    def test_ja_instalada(self):
        self.assertFalse(V.ja_instalada(self.voices))
        self.pasta_valida()
        self.assertTrue(V.ja_instalada(self.voices))

    def test_instalar_pula_se_ja_existe(self):
        self.pasta_valida()

        with mock.patch.object(V, "baixar_arquivo") as baixar:
            deu, msg = V.instalar(self.voices, log=lambda *a: None)

        baixar.assert_not_called()
        self.assertTrue(deu)
        self.assertIn("já está instalada", msg)

    def test_forcar_baixa_de_novo(self):
        self.pasta_valida()
        chamadas = []

        def falso(url, destino, progresso=None):
            chamadas.append(url)
            Path(destino).parent.mkdir(parents=True, exist_ok=True)

            if str(destino).endswith(".json"):
                Path(destino).write_text(
                    json.dumps({"audio": {"sample_rate": 22050}}),
                    encoding="utf-8",
                )
            else:
                Path(destino).write_bytes(b"y" * (V.TAMANHO_MINIMO + 5))

            return True, ""

        with mock.patch.object(V, "baixar_arquivo", falso):
            deu, msg = V.instalar(
                self.voices, log=lambda *a: None, forcar=True
            )

        self.assertTrue(deu)
        self.assertGreaterEqual(len(chamadas), 2)

    def test_falha_no_modelo_e_relatada(self):
        def falso(url, destino, progresso=None):
            return False, "HTTP 404"

        with mock.patch.object(V, "baixar_arquivo", falso):
            deu, msg = V.instalar(self.voices, log=lambda *a: None)

        self.assertFalse(deu)
        self.assertIn("404", msg)

    def test_download_incompleto_e_recusado(self):
        def falso(url, destino, progresso=None):
            Path(destino).parent.mkdir(parents=True, exist_ok=True)

            if str(destino).endswith(".json"):
                Path(destino).write_text(
                    json.dumps({"audio": {"sample_rate": 22050}}),
                    encoding="utf-8",
                )
            else:
                Path(destino).write_bytes(b"z" * 1000)   # pequeno demais

            return True, ""

        with mock.patch.object(V, "baixar_arquivo", falso):
            deu, msg = V.instalar(self.voices, log=lambda *a: None)

        self.assertFalse(deu)
        self.assertIn("estranho", msg)

    def test_voz_desconhecida(self):
        deu, msg = V.instalar(self.voices, "inexistente", log=lambda *a: None)
        self.assertFalse(deu)

    def test_parcial_nao_vira_arquivo_final(self):
        """Download interrompido não pode deixar um arquivo quebrado."""
        destino = self.tmp / "model.onnx"

        class RespostaQuebrada:
            headers = {"Content-Length": "999999"}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, n):
                raise OSError("conexão caiu")

        with mock.patch.object(
            V.urllib.request, "urlopen", return_value=RespostaQuebrada()
        ):
            deu, falha = V.baixar_arquivo("https://x/y", destino)

        self.assertFalse(deu)
        self.assertFalse(destino.exists())
        self.assertFalse(destino.with_suffix(".onnx.parcial").exists())

    def test_download_bom_renomeia(self):
        destino = self.tmp / "arquivo.bin"

        class Resposta:
            headers = {"Content-Length": "6"}

            def __init__(self):
                self.restante = [b"abc", b"def"]

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, n):
                return self.restante.pop(0) if self.restante else b""

        avisos = []

        with mock.patch.object(
            V.urllib.request, "urlopen", return_value=Resposta()
        ):
            deu, _ = V.baixar_arquivo(
                "https://x/y", destino, lambda b, t: avisos.append((b, t))
            )

        self.assertTrue(deu)
        self.assertEqual(destino.read_bytes(), b"abcdef")
        self.assertTrue(avisos)


if __name__ == "__main__":
    unittest.main(verbosity=2)
