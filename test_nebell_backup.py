"""
Testes do backup da memoria do NEBELL.

Usa bancos de verdade em pasta temporaria: SQLite e da biblioteca
padrao, e o que importa aqui e justamente o comportamento real com
arquivo, incluindo o caso do banco corrompido.

Uso:  python test_nebell_backup.py
"""

import shutil
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import nebell_agenda as A
import nebell_backup as B
import nebell_memoria as M


def banco_com_conteudo(caminho):
    """Uma memoria pequena, mas com algo de cada tipo."""
    memoria = M.Memoria(caminho, log=lambda *a: None)
    assert memoria.abrir()

    memoria.iniciar_conversa(modo="teste")
    memoria.guardar_fato("gosta de café sem açúcar", "preferencia")
    memoria.guardar_fato("usa Windows com RTX 3050", "tecnico")
    memoria.salvar_projeto("NEBELL", "assistente local", "ativo", "C:\\x")
    memoria.anotar_projeto("NEBELL", "contexto em 8192")
    memoria.ensinar_comando("modo foco", "fecha o discord")
    memoria.registrar_arquivo("C:\\x\\script.py", "um script", None)
    memoria.registrar_mensagem("user", "oi")

    return memoria


def destruir(caminho):
    """Deixa o arquivo com cara de banco, mas quebrado por dentro."""
    Path(caminho).write_bytes(
        b"SQLite format 3\x00" + b"\x00" * 400 + b"LIXO" * 300
    )


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nebell_bk_"))
        self.banco = self.tmp / "memoria.db"
        self.pasta = self.tmp / "backup"

        self.memoria = banco_com_conteudo(self.banco)
        self.backup = B.Backup(
            self.banco, self.pasta, memoria=self.memoria,
            log=lambda *a: None, intervalo=0.05,
        )

    def tearDown(self):
        self.backup.parar()

        try:
            self.memoria.fechar()
        except Exception:
            pass

    @property
    def copia(self):
        return self.pasta / B.NOME_BANCO


# ============================================================
# CONFERIR A INTEGRIDADE
# ============================================================

class TestBancoEstaSao(BackupTest):
    def test_banco_bom(self):
        sao, motivo = B.banco_esta_sao(self.banco)
        self.assertTrue(sao, motivo)
        self.assertEqual(motivo, "")

    def test_banco_corrompido(self):
        # Fecha antes: com a conexão aberta, o SQLite reconstrói o
        # conteúdo pelo -wal e o banco continua legível, então destruir
        # só o .db não provaria nada.
        self.memoria.fechar()
        destruir(self.banco)

        sao, motivo = B.banco_esta_sao(self.banco)

        self.assertFalse(sao)
        self.assertTrue(motivo)

    def test_banco_inexistente(self):
        sao, motivo = B.banco_esta_sao(self.tmp / "nao_existe.db")
        self.assertFalse(sao)
        self.assertIn("não existe", motivo)

    def test_banco_vazio(self):
        vazio = self.tmp / "vazio.db"
        vazio.write_bytes(b"")

        sao, motivo = B.banco_esta_sao(vazio)
        self.assertFalse(sao)
        self.assertIn("vazio", motivo)

    def test_sqlite_de_outra_coisa(self):
        # Um banco valido, mas que nao e a memoria do NEBELL: restaurar
        # isso por cima apagaria tudo sem avisar.
        outro = self.tmp / "outro.db"
        conexao = sqlite3.connect(outro)
        conexao.execute("CREATE TABLE qualquer (a)")
        conexao.commit()
        conexao.close()

        sao, motivo = B.banco_esta_sao(outro)
        self.assertFalse(sao)
        self.assertIn("tabelas", motivo)


# ============================================================
# COPIAR
# ============================================================

class TestCopiar(BackupTest):
    def test_primeira_copia(self):
        deu_certo, mensagem = self.backup.copiar(forcar=True)

        self.assertTrue(deu_certo, mensagem)
        self.assertTrue(self.copia.is_file())
        self.assertGreater(self.copia.stat().st_size, 0)

    def test_a_copia_tem_o_conteudo(self):
        self.backup.copiar(forcar=True)

        aberta = M.Memoria(self.copia, log=lambda *a: None)
        self.assertTrue(aberta.abrir())

        textos = [f["texto"] for f in aberta.listar_fatos()]
        self.assertIn("gosta de café sem açúcar", textos)
        aberta.fechar()

    def test_a_copia_e_um_arquivo_unico(self):
        # Sem isto sobram -wal e -shm, e quem copiasse so o .db levaria
        # um banco incompleto.
        self.backup.copiar(forcar=True)

        for sufixo in ("-wal", "-shm"):
            self.assertFalse(
                Path(str(self.copia) + sufixo).exists(), sufixo
            )

    def test_nao_deixa_provisorio_para_tras(self):
        self.backup.copiar(forcar=True)

        restos = [
            f.name for f in self.pasta.iterdir() if ".novo" in f.name
        ]
        self.assertEqual(restos, [])

    def test_copia_recente_nao_repete(self):
        self.backup.copiar(forcar=True)
        deu_certo, mensagem = self.backup.copiar()

        self.assertTrue(deu_certo)
        self.assertIn("há pouco", mensagem)

    def test_sem_mudanca_nao_copia(self):
        self.backup.copiar(forcar=True)
        self.backup.ultima_copia = 0          # passa do tempo mínimo

        deu_certo, mensagem = self.backup.copiar()
        self.assertTrue(deu_certo)
        self.assertIn("nada mudou", mensagem)

    def test_conta_as_copias_da_sessao(self):
        self.backup.copiar(forcar=True)
        self.backup.copiar(forcar=True)

        self.assertEqual(self.backup.copias_feitas, 2)

    def test_cria_a_pasta_que_nao_existe(self):
        self.assertFalse(self.pasta.exists())
        self.backup.copiar(forcar=True)
        self.assertTrue(self.pasta.is_dir())

    def test_registro_de_cada_tentativa(self):
        self.backup.copiar(forcar=True)
        registro = (self.pasta / B.NOME_REGISTRO).read_text(encoding="utf-8")

        self.assertIn("ok", registro)


class TestCopiarProtege(BackupTest):
    def test_banco_corrompido_nao_sobrescreve_o_backup_bom(self):
        # O ponto mais importante do módulo: um backup único
        # sobrescrito às cegas perde tudo no dia da corrupção.
        self.backup.copiar(forcar=True)
        bom = self.copia.read_bytes()

        self.memoria.fechar()
        destruir(self.banco)

        deu_certo, mensagem = self.backup.copiar(forcar=True)

        self.assertFalse(deu_certo)
        self.assertIn("intacta", mensagem)
        self.assertEqual(self.copia.read_bytes(), bom)

    def test_banco_que_desapareceu(self):
        self.backup.copiar(forcar=True)
        bom = self.copia.read_bytes()

        self.memoria.fechar()
        self.banco.unlink()

        deu_certo, _ = self.backup.copiar(forcar=True)

        self.assertFalse(deu_certo)
        self.assertEqual(self.copia.read_bytes(), bom)

    def test_copia_que_sai_ruim_e_descartada(self):
        self.backup.copiar(forcar=True)
        bom = self.copia.read_bytes()

        # A cópia "dá certo" mas gera um arquivo quebrado.
        def copia_ruim(origem, destino, timeout=15):
            destruir(destino)
            return True, ""

        with mock.patch.object(B, "copiar_banco", copia_ruim):
            deu_certo, mensagem = self.backup.copiar(forcar=True)

        self.assertFalse(deu_certo)
        self.assertIn("mantive a anterior", mensagem)
        self.assertEqual(self.copia.read_bytes(), bom)

    def test_falha_ao_copiar_vira_mensagem(self):
        with mock.patch.object(
            B, "copiar_banco", lambda *a, **k: (False, "disco cheio")
        ):
            deu_certo, mensagem = self.backup.copiar(forcar=True)

        self.assertFalse(deu_certo)
        self.assertIn("disco cheio", mensagem)

    def test_erro_fica_no_registro(self):
        self.memoria.fechar()
        destruir(self.banco)
        self.backup.copiar(forcar=True)

        registro = (self.pasta / B.NOME_REGISTRO).read_text(encoding="utf-8")
        self.assertIn("RECUSADO", registro)


class TestGeracoes(BackupTest):
    def test_guarda_as_geracoes_anteriores(self):
        for _ in range(3):
            self.backup.copiar(forcar=True)

        self.assertTrue(self.copia.with_suffix(".1.db").is_file())
        self.assertTrue(self.copia.with_suffix(".2.db").is_file())

    def test_nao_passa_do_limite(self):
        for _ in range(6):
            self.backup.copiar(forcar=True)

        self.assertFalse(self.copia.with_suffix(".3.db").exists())

    def test_o_principal_e_sempre_o_mais_novo(self):
        self.backup.copiar(forcar=True)
        self.memoria.guardar_fato("lembrança nova", "geral")
        self.backup.copiar(forcar=True)

        aberta = M.Memoria(self.copia, log=lambda *a: None)
        aberta.abrir()
        textos = [f["texto"] for f in aberta.listar_fatos()]
        aberta.fechar()

        self.assertIn("lembrança nova", textos)

    def test_a_geracao_anterior_guarda_o_estado_antigo(self):
        self.backup.copiar(forcar=True)
        self.memoria.guardar_fato("lembrança nova", "geral")
        self.backup.copiar(forcar=True)

        antiga = M.Memoria(
            self.copia.with_suffix(".1.db"), log=lambda *a: None
        )
        antiga.abrir()
        textos = [f["texto"] for f in antiga.listar_fatos()]
        antiga.fechar()

        self.assertNotIn("lembrança nova", textos)

    def test_rodar_sem_arquivo_nao_estoura(self):
        B.rodar_geracoes(self.tmp / "nao_existe.db")


# ============================================================
# RELATORIO
# ============================================================

class TestRelatorio(BackupTest):
    def relatorio(self):
        self.backup.copiar(forcar=True)
        return (self.pasta / B.NOME_RELATORIO).read_text(encoding="utf-8")

    def test_o_relatorio_e_gravado(self):
        self.assertTrue(self.relatorio().strip())

    def test_traz_as_lembrancas(self):
        texto = self.relatorio()
        self.assertIn("gosta de café sem açúcar", texto)
        self.assertIn("preferencia", texto)

    def test_traz_os_projetos_e_as_notas(self):
        texto = self.relatorio()
        self.assertIn("NEBELL", texto)
        self.assertIn("contexto em 8192", texto)

    def test_traz_os_comandos_ensinados(self):
        texto = self.relatorio()
        self.assertIn("modo foco", texto)
        self.assertIn("fecha o discord", texto)

    def test_traz_os_arquivos(self):
        self.assertIn("script.py", self.relatorio())

    def test_traz_a_contagem(self):
        texto = self.relatorio()
        self.assertIn("RESUMO", texto)
        self.assertIn("lembrança(s)", texto)

    def test_diz_como_restaurar(self):
        self.assertIn("memoria_backup.db", self.relatorio())

    def test_traz_os_lembretes_quando_existem(self):
        agenda = A.Agenda(self.memoria, log=lambda *a: None)
        agenda.criar_tabela()
        agenda.criar("pagar a luz", "amanha as 8")

        texto = self.relatorio()
        self.assertIn("LEMBRETES", texto)
        self.assertIn("pagar a luz", texto)

    def test_sem_a_tabela_de_lembretes_nao_estoura(self):
        # A tabela só existe depois de a agenda abrir uma vez.
        self.assertNotIn("LEMBRETES", self.relatorio())

    def test_memoria_que_falha_nao_derruba_o_relatorio(self):
        class Quebrada:
            def numeros(self):
                raise RuntimeError("quebrou")

            def listar_fatos(self, **kwargs):
                raise RuntimeError("quebrou")

            def listar_projetos(self, **kwargs):
                raise RuntimeError("quebrou")

            def listar_comandos(self, **kwargs):
                raise RuntimeError("quebrou")

            def conversas_recentes(self, **kwargs):
                raise RuntimeError("quebrou")

            def buscar_arquivos(self, *a, **kwargs):
                raise RuntimeError("quebrou")

            def consultar(self, *a, **kwargs):
                raise RuntimeError("quebrou")

        texto = B.montar_relatorio(Quebrada())
        self.assertIn("MEMÓRIAS DO NEBELL", texto)

    def test_sem_memoria_nao_grava_relatorio(self):
        sozinho = B.Backup(
            self.banco, self.tmp / "b2", memoria=None, log=lambda *a: None
        )
        sozinho.copiar(forcar=True)

        self.assertFalse((self.tmp / "b2" / B.NOME_RELATORIO).exists())


# ============================================================
# VIGIA
# ============================================================

class TestVigia(BackupTest):
    def test_iniciar_e_parar(self):
        self.assertTrue(self.backup.iniciar())
        self.assertFalse(self.backup.iniciar())
        self.backup.parar()
        self.assertFalse(self.backup.ligado)

    def test_o_vigia_copia_sozinho(self):
        self.backup.iniciar()

        for _ in range(60):
            if self.copia.is_file():
                break

            threading.Event().wait(0.05)

        self.backup.parar()
        self.assertTrue(self.copia.is_file())

    def test_erro_no_ciclo_nao_mata_o_vigia(self):
        with mock.patch.object(
            self.backup, "copiar", side_effect=RuntimeError("falhou")
        ):
            self.backup.iniciar()
            threading.Event().wait(0.2)
            vivo = self.backup.ligado

        self.backup.parar()
        self.assertTrue(vivo)

    def test_chamadas_ao_mesmo_tempo_nao_se_atropelam(self):
        resultados = []

        def copiar():
            resultados.append(self.backup.copiar(forcar=True)[0])

        fios = [threading.Thread(target=copiar) for _ in range(4)]

        for fio in fios:
            fio.start()

        for fio in fios:
            fio.join(timeout=10)

        self.assertTrue(all(resultados))
        self.assertTrue(self.copia.is_file())


class TestNumerosEDescricao(BackupTest):
    def test_sem_backup_ainda(self):
        dados = self.backup.numeros()
        self.assertFalse(dados["existe"])
        self.assertIn("Ainda não há backup", self.backup.descrever())

    def test_depois_do_backup(self):
        self.backup.copiar(forcar=True)
        dados = self.backup.numeros()

        self.assertTrue(dados["existe"])
        self.assertGreater(dados["tamanho_kb"], 0)
        self.assertEqual(dados["copias_na_sessao"], 1)
        self.assertTrue(dados["quando"])

    def test_descricao_e_falavel(self):
        self.backup.copiar(forcar=True)
        frase = self.backup.descrever()

        self.assertIn("Backup de", frase)
        self.assertTrue(frase.endswith("."))

    def test_conta_as_geracoes(self):
        for _ in range(3):
            self.backup.copiar(forcar=True)

        self.assertEqual(self.backup.numeros()["geracoes"], 2)

    def test_descricao_conta_a_falha(self):
        self.memoria.fechar()
        destruir(self.banco)
        self.backup.copiar(forcar=True)

        self.assertIn("não há backup", self.backup.descrever())


# ============================================================
# RESTAURAR
# ============================================================

class TestRestaurar(BackupTest):
    def test_restaura_a_memoria(self):
        self.backup.copiar(forcar=True)
        self.memoria.fechar()
        destruir(self.banco)

        deu_certo, mensagem = B.restaurar(self.pasta, self.banco)
        self.assertTrue(deu_certo, mensagem)

        aberta = M.Memoria(self.banco, log=lambda *a: None)
        self.assertTrue(aberta.abrir())
        textos = [f["texto"] for f in aberta.listar_fatos()]
        aberta.fechar()

        self.assertIn("gosta de café sem açúcar", textos)

    def test_guarda_o_banco_atual_antes_de_trocar(self):
        self.backup.copiar(forcar=True)
        self.memoria.fechar()

        B.restaurar(self.pasta, self.banco)

        self.assertTrue(
            self.banco.with_suffix(".antes_de_restaurar.db").is_file()
        )

    def test_apaga_o_wal_do_banco_antigo(self):
        # O -wal do banco velho não serve para o novo e corromperia.
        self.backup.copiar(forcar=True)
        self.memoria.fechar()
        Path(str(self.banco) + "-wal").write_bytes(b"lixo")

        B.restaurar(self.pasta, self.banco)

        self.assertFalse(Path(str(self.banco) + "-wal").exists())

    def test_recusa_backup_ruim(self):
        self.backup.copiar(forcar=True)
        destruir(self.copia)

        deu_certo, mensagem = B.restaurar(self.pasta, self.banco)
        self.assertFalse(deu_certo)
        self.assertIn("não serve", mensagem)

    def test_recusa_quando_nao_ha_backup(self):
        deu_certo, mensagem = B.restaurar(self.tmp / "vazia", self.banco)
        self.assertFalse(deu_certo)

    def test_restaurar_duas_vezes_nao_perde_o_guardado(self):
        self.backup.copiar(forcar=True)
        self.memoria.fechar()

        B.restaurar(self.pasta, self.banco)
        deu_certo, _ = B.restaurar(self.pasta, self.banco)

        self.assertTrue(deu_certo)


class TestCopiarBanco(BackupTest):
    def test_copia_em_pasta_que_nao_existe(self):
        destino = self.tmp / "a" / "b" / "c.db"
        deu_certo, erro = B.copiar_banco(self.banco, destino)

        self.assertTrue(deu_certo, erro)
        self.assertTrue(destino.is_file())

    def test_origem_inexistente(self):
        deu_certo, erro = B.copiar_banco(
            self.tmp / "nao_existe.db", self.tmp / "saida.db"
        )
        self.assertFalse(deu_certo)

    def test_copia_com_o_banco_em_uso(self):
        # A memória está aberta e escrevendo: é o caso normal, e é
        # justamente onde copiar o arquivo à mão daria lixo.
        self.memoria.guardar_fato("durante a cópia", "geral")

        deu_certo, erro = B.copiar_banco(self.banco, self.tmp / "viva.db")
        self.assertTrue(deu_certo, erro)

        sao, motivo = B.banco_esta_sao(self.tmp / "viva.db")
        self.assertTrue(sao, motivo)


class TestNormalizar(unittest.TestCase):
    def test_tira_acento_e_caixa(self):
        self.assertEqual(B.normalize("  Ação  DO  Coração "), "acao do coracao")


if __name__ == "__main__":
    unittest.main(verbosity=2)
