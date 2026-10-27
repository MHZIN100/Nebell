"""
Testes dos modulos novos do NEBELL: agenda, visao, janelas, documentos
e sentinela de hardware.

Roda em qualquer sistema. O que e exclusivo do Windows (janelas e
teclado) e testado pelas funcoes puras e pela recusa educada fora do
Windows.

Uso:  python test_nebell_extras.py
"""

import importlib.util
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import nebell_agenda as A
import nebell_docs as D
import nebell_janela as J
import nebell_memoria as M
import nebell_sentinela as S
import nebell_visao as V

EH_WINDOWS = sys.platform.startswith("win")


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

try:
    from PIL import Image, ImageDraw
    TEM_PILLOW = True
except Exception:
    Image = ImageDraw = None
    TEM_PILLOW = False

TEM_OCR = bool(TEM_PILLOW and V.pytesseract is not None and V.achar_tesseract())

# Sexta-feira, 16 de outubro de 2026, 14:30. Toda conta de data nos
# testes parte daqui, para o resultado nao mudar conforme o dia.
AGORA = datetime(2026, 10, 16, 14, 30)


def imagem_com_texto(destino, texto="Erro 0x80070005 acesso negado"):
    imagem = Image.new("RGB", (900, 200), "white")
    desenho = ImageDraw.Draw(imagem)
    desenho.text((20, 60), texto, fill="black")
    imagem.save(destino)
    return destino


# ============================================================
# AGENDA: ENTENDER A HORA DITA
# ============================================================

class TestInterpretarQuando(unittest.TestCase):
    def quando(self, texto, agora=AGORA):
        return A.interpretar_quando(texto, agora)

    def test_em_minutos(self):
        quando, rec = self.quando("em 20 minutos")
        self.assertEqual(quando, AGORA + timedelta(minutes=20))
        self.assertIsNone(rec)

    def test_em_minutos_falado(self):
        quando, _ = self.quando("em vinte minutos")
        self.assertEqual(quando, AGORA + timedelta(minutes=20))

    def test_daqui_a(self):
        quando, _ = self.quando("daqui a 5 minutos")
        self.assertEqual(quando, AGORA + timedelta(minutes=5))

    def test_em_horas(self):
        quando, _ = self.quando("em duas horas")
        self.assertEqual(quando, AGORA + timedelta(hours=2))

    def test_meia_hora_nao_e_trinta_horas(self):
        quando, _ = self.quando("em meia hora")
        self.assertEqual(quando, AGORA + timedelta(minutes=30))

    def test_em_dias(self):
        quando, _ = self.quando("em 3 dias")
        self.assertEqual(quando.date(), (AGORA + timedelta(days=3)).date())

    def test_amanha_com_hora(self):
        quando, _ = self.quando("amanha as 8")
        self.assertEqual((quando.day, quando.hour), (17, 8))

    def test_amanha_com_hora_falada(self):
        quando, _ = self.quando("amanha as oito")
        self.assertEqual((quando.day, quando.hour), (17, 8))

    def test_depois_de_amanha_nao_casa_com_amanha(self):
        quando, _ = self.quando("depois de amanha as 10")
        self.assertEqual((quando.day, quando.hour), (18, 10))

    def test_hoje_com_hora(self):
        quando, _ = self.quando("hoje as 18h")
        self.assertEqual((quando.day, quando.hour), (16, 18))

    def test_hora_com_minuto(self):
        quando, _ = self.quando("as 14:45")
        self.assertEqual((quando.hour, quando.minute), (14, 45))

    def test_hora_com_h(self):
        quando, _ = self.quando("as 20h30")
        self.assertEqual((quando.hour, quando.minute), (20, 30))

    def test_oito_e_meia(self):
        quando, _ = self.quando("as oito e meia")
        self.assertEqual((quando.hour, quando.minute), (8, 30))

    def test_da_noite_vira_tarde(self):
        quando, _ = self.quando("as 7 da noite")
        self.assertEqual(quando.hour, 19)

    def test_hora_que_passou_vai_para_amanha(self):
        quando, _ = self.quando("as 9")
        self.assertEqual((quando.day, quando.hour), (17, 9))

    def test_hoje_aceita_hora_passada(self):
        # Dia dito e dia respeitado: quem decide se recusa e a Agenda.
        quando, _ = self.quando("hoje as 9")
        self.assertEqual((quando.day, quando.hour), (16, 9))

    def test_dia_do_mes(self):
        quando, _ = self.quando("dia 25 as 14h")
        self.assertEqual((quando.day, quando.month, quando.hour), (25, 10, 14))

    def test_dia_e_mes(self):
        quando, _ = self.quando("25 de dezembro as 9")
        self.assertEqual((quando.day, quando.month), (25, 12))

    def test_dia_que_ja_passou_vai_para_o_mes_seguinte(self):
        quando, _ = self.quando("dia 2 as 10")
        self.assertEqual((quando.day, quando.month), (2, 11))

    def test_mes_que_ja_passou_vai_para_o_ano_seguinte(self):
        quando, _ = self.quando("1 de marco as 10")
        self.assertEqual(quando.year, AGORA.year + 1)

    def test_dia_da_semana_conta_hoje_se_a_hora_nao_passou(self):
        # Hoje e sexta as 14:30; "sexta as 20h" e hoje mesmo.
        quando, _ = self.quando("sexta as 20h")
        self.assertEqual((quando.day, quando.hour), (16, 20))

    def test_dia_da_semana_passa_para_a_semana_seguinte(self):
        quando, _ = self.quando("sexta as 9")
        self.assertEqual(quando.day, 23)

    def test_dia_da_semana_proximo(self):
        quando, _ = self.quando("segunda que vem as 15")
        self.assertEqual((quando.day, quando.hour), (19, 15))

    def test_recorrencia_diaria(self):
        quando, rec = self.quando("todo dia as 6h30")
        self.assertEqual(rec, "diario")
        # 6h30 de hoje ja passou, entao o primeiro e amanha.
        self.assertEqual((quando.day, quando.hour), (17, 6))

    def test_recorrencia_diaria_ainda_hoje(self):
        quando, rec = self.quando("todo dia as 20h")
        self.assertEqual(rec, "diario")
        self.assertEqual(quando.day, 16)

    def test_recorrencia_semanal_cai_no_dia_certo(self):
        quando, rec = self.quando("toda segunda as 7")
        self.assertEqual(rec, "semanal:0")
        self.assertEqual(quando.weekday(), 0)
        self.assertEqual((quando.day, quando.hour), (19, 7))

    def test_recorrencia_semanal_sem_hora_e_recusada(self):
        quando, motivo = self.quando("toda segunda")
        self.assertIsNone(quando)
        self.assertIn("hora", motivo)

    def test_texto_vazio(self):
        quando, motivo = self.quando("")
        self.assertIsNone(quando)

    def test_texto_sem_sentido(self):
        quando, motivo = self.quando("banana com farofa")
        self.assertIsNone(quando)

    def test_passado_explicito_e_recusado(self):
        for frase in ("ontem as 8", "anteontem as 8", "semana passada"):
            quando, motivo = self.quando(frase)
            self.assertIsNone(quando, frase)
            self.assertIn("passou", motivo)

    def test_data_inexistente(self):
        quando, motivo = self.quando("30 de fevereiro as 10")
        self.assertIsNone(quando)

    def test_hora_absurda_nao_estoura(self):
        quando, _ = self.quando("as 99:00")
        # 99 horas vira algo valido ou e recusado, mas nao estoura.
        if quando is not None:
            self.assertLess(quando.hour, 24)


class TestExtrairHora(unittest.TestCase):
    def test_formatos_numericos(self):
        self.assertEqual(A.extrair_hora("as 14:30"), (14, 30))
        self.assertEqual(A.extrair_hora("as 14h30"), (14, 30))
        self.assertEqual(A.extrair_hora("as 14h"), (14, 0))
        self.assertEqual(A.extrair_hora("as 7 horas"), (7, 0))

    def test_sem_hora(self):
        self.assertEqual(A.extrair_hora("amanha"), (None, 0))

    def test_minuto_invalido_e_descartado(self):
        hora, minuto = A.extrair_hora("as oito e noventa")
        self.assertEqual(hora, 8)
        self.assertEqual(minuto, 0)


class TestFalarQuando(unittest.TestCase):
    def test_hoje(self):
        frase = A.falar_quando(AGORA.replace(hour=18, minute=0), AGORA)
        self.assertIn("hoje", frase)

    def test_amanha(self):
        frase = A.falar_quando(AGORA + timedelta(days=1), AGORA)
        self.assertIn("amanhã", frase)

    def test_data_distante_traz_o_mes(self):
        frase = A.falar_quando(datetime(2026, 12, 25, 9, 0), AGORA)
        self.assertIn("dezembro", frase)


# ============================================================
# AGENDA: BANCO
# ============================================================

class AgendaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nebell_ag_"))
        self.mem = M.Memoria(self.tmp / "memoria.db", log=lambda *a: None)
        self.assertTrue(self.mem.abrir())

        self.falas = []
        self.agenda = A.Agenda(
            self.mem, ao_disparar=self.falas.append, log=lambda *a: None
        )
        self.assertTrue(self.agenda.criar_tabela())

    def tearDown(self):
        self.agenda.parar()
        self.mem.fechar()

    def vencer(self, texto, minutos=2):
        """Empurra um lembrete para o passado, como se a hora chegasse."""
        quando = datetime.now() - timedelta(minutes=minutos)
        self.mem.executar(
            "UPDATE lembretes SET quando = ? WHERE texto = ?",
            (quando.isoformat(timespec="seconds"), texto),
        )


class TestAgendaCriar(AgendaTest):
    def test_cria_a_tabela(self):
        nomes = {
            linha["name"] for linha in self.mem.consultar(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        self.assertIn("lembretes", nomes)

    def test_criar_devolve_frase_falavel(self):
        deu, mensagem = self.agenda.criar("pagar a luz", "amanha as 8")
        self.assertTrue(deu)
        self.assertIn("pagar a luz", mensagem)
        self.assertIn("amanhã", mensagem)

    def test_criar_sem_texto(self):
        deu, mensagem = self.agenda.criar("", "amanha as 8")
        self.assertFalse(deu)

    def test_criar_sem_quando(self):
        deu, mensagem = self.agenda.criar("algo", "")
        self.assertFalse(deu)

    def test_criar_com_hora_que_passou(self):
        deu, mensagem = self.agenda.criar(
            "reuniao", "hoje as 9", agora=datetime(2026, 10, 16, 14, 30)
        )
        self.assertFalse(deu)
        self.assertIn("passou", mensagem)

    def test_recorrente_avisa_que_repete(self):
        _, mensagem = self.agenda.criar("alongar", "todo dia as 23h")
        self.assertIn("todos os dias", mensagem)

    def test_semanal_avisa_que_repete(self):
        _, mensagem = self.agenda.criar("lixo", "toda segunda as 7")
        self.assertIn("semana", mensagem)

    def test_sem_banco_nao_estoura(self):
        orfa = A.Agenda(None, log=lambda *a: None)
        deu, mensagem = orfa.criar("x", "amanha as 8")
        self.assertFalse(deu)
        self.assertEqual(orfa.listar(), [])
        self.assertEqual(orfa.conferir(), 0)
        self.assertFalse(orfa.criar_tabela())
        self.assertFalse(orfa.iniciar())


class TestAgendaListarCancelar(AgendaTest):
    def test_listar_em_ordem_de_hora(self):
        self.agenda.criar("terceiro", "em 3 horas")
        self.agenda.criar("primeiro", "em 10 minutos")
        self.agenda.criar("segundo", "em 1 hora")

        textos = [item["texto"] for item in self.agenda.listar()]
        self.assertEqual(textos, ["primeiro", "segundo", "terceiro"])

    def test_descrever_sem_nada(self):
        self.assertIn("nada", self.agenda.descrever().lower())

    def test_descrever_lista_os_assuntos(self):
        self.agenda.criar("pagar a luz", "amanha as 8")
        descricao = self.agenda.descrever()
        self.assertIn("pagar a luz", descricao)

    def test_descrever_com_limite(self):
        for numero in range(5):
            self.agenda.criar(f"item {numero}", f"em {numero + 1} horas")

        self.assertEqual(self.agenda.descrever(limite=2).count("- "), 2)

    def test_cancelar_devolve_mensagem(self):
        self.agenda.criar("pagar a luz", "amanha as 8")
        quantos, mensagem = self.agenda.cancelar("luz")
        self.assertEqual(quantos, 1)
        self.assertIn("pagar a luz", mensagem)
        self.assertEqual(self.agenda.listar(), [])

    def test_cancelar_sem_achar(self):
        quantos, mensagem = self.agenda.cancelar("foguete")
        self.assertEqual(quantos, 0)
        self.assertIn("foguete", mensagem)

    def test_cancelar_vazio(self):
        quantos, _ = self.agenda.cancelar("")
        self.assertEqual(quantos, 0)

    def test_cancelar_varios_de_uma_vez(self):
        self.agenda.criar("pagar a luz", "amanha as 8")
        self.agenda.criar("pagar a agua", "amanha as 9")
        quantos, mensagem = self.agenda.cancelar("pagar")
        self.assertEqual(quantos, 2)

    def test_numeros(self):
        self.agenda.criar("a", "em 1 hora")
        self.agenda.criar("b", "em 2 horas")
        self.agenda.cancelar("a")

        numeros = self.agenda.numeros()
        self.assertEqual(numeros["ativos"], 1)
        self.assertEqual(numeros["total"], 2)


class TestAgendaDisparo(AgendaTest):
    def test_avisa_o_que_venceu(self):
        self.agenda.criar("tomar agua", "em 1 minuto")
        self.vencer("tomar agua")

        self.assertEqual(self.agenda.conferir(), 1)
        self.assertEqual(self.falas, ["Lembrete: tomar agua."])

    def test_nao_avisa_duas_vezes(self):
        self.agenda.criar("tomar agua", "em 1 minuto")
        self.vencer("tomar agua")
        self.agenda.conferir()
        self.agenda.conferir()
        self.assertEqual(len(self.falas), 1)

    def test_nao_avisa_antes_da_hora(self):
        self.agenda.criar("tomar agua", "em 2 horas")
        self.assertEqual(self.agenda.conferir(), 0)
        self.assertEqual(self.falas, [])

    def test_recorrente_e_reagendado(self):
        self.agenda.criar("alongar", "todo dia as 23h")
        self.vencer("alongar")
        self.agenda.conferir()

        pendentes = self.agenda.listar()
        self.assertEqual(len(pendentes), 1)
        self.assertEqual(pendentes[0]["texto"], "alongar")
        self.assertGreater(
            datetime.fromisoformat(pendentes[0]["quando"]), datetime.now()
        )

    def test_semanal_reagenda_uma_semana_a_frente(self):
        self.agenda.criar("lixo", "toda segunda as 7")
        self.vencer("lixo")
        self.agenda.conferir()

        pendentes = self.agenda.listar()
        self.assertEqual(len(pendentes), 1)
        self.assertEqual(
            datetime.fromisoformat(pendentes[0]["quando"]).weekday(), 0
        )

    def test_muito_atrasado_e_encerrado_calado(self):
        # O computador estava desligado: ninguem quer ouvir o lembrete
        # de cinco horas atras ao abrir o programa.
        self.agenda.criar("antigo", "em 1 minuto")
        self.vencer("antigo", minutos=600)

        self.assertEqual(self.agenda.conferir(), 0)
        self.assertEqual(self.falas, [])
        self.assertEqual(self.agenda.listar(), [])

    def test_falha_do_aviso_nao_derruba_a_volta(self):
        def explodir(_):
            raise RuntimeError("sem som")

        self.agenda.ao_disparar = explodir
        self.agenda.criar("tomar agua", "em 1 minuto")
        self.vencer("tomar agua")

        self.assertEqual(self.agenda.conferir(), 0)

    def test_frase_do_aviso(self):
        frase = self.agenda.frase_do_aviso({"texto": "  pagar a luz  "})
        self.assertEqual(frase, "Lembrete: pagar a luz.")

    def test_iniciar_e_parar_o_vigia(self):
        self.assertTrue(self.agenda.iniciar())
        self.agenda.parar()


# ============================================================
# VISAO
# ============================================================

class TestVisaoDisponibilidade(unittest.TestCase):
    def test_falta_o_que_sem_pillow(self):
        with mock.patch.object(V, "Image", None):
            faltando = V.falta_o_que()

        self.assertTrue(any("pillow" in f for f in faltando))

    def test_falta_o_que_sem_pytesseract(self):
        with mock.patch.object(V, "pytesseract", None), \
                mock.patch.object(V, "_tesseract_pronto", [None]):
            faltando = V.falta_o_que(para_ocr=True)

        self.assertTrue(any("pytesseract" in f for f in faltando))

    def test_falta_o_que_sem_o_programa_tesseract(self):
        with mock.patch.object(V, "_tesseract_pronto", [""]):
            faltando = V.falta_o_que(para_ocr=True)

        self.assertTrue(any("Tesseract" in f for f in faltando))

    def test_achar_tesseract_usa_o_cache(self):
        with mock.patch.object(V, "_tesseract_pronto", ["/x/tesseract"]):
            self.assertEqual(V.achar_tesseract(), "/x/tesseract")

    def test_sem_pillow_a_captura_explica_o_que_falta(self):
        with mock.patch.object(V, "Image", None):
            caminho, erro = V.capturar_tela("/tmp/x.png")

        self.assertIsNone(caminho)
        self.assertIn("pillow", erro.lower())

    def test_ocr_sem_pacote_explica(self):
        with mock.patch.object(V, "pytesseract", None), \
                mock.patch.object(V, "_tesseract_pronto", [None]):
            texto, erro = V.ler_texto("/tmp/x.png")

        self.assertIsNone(texto)
        self.assertIn("pytesseract", erro)

    def test_janela_em_foco_fora_do_windows(self):
        if not EH_WINDOWS:
            self.assertIsNone(V.janela_em_foco_retangulo())


@unittest.skipUnless(TEM_PILLOW, "precisa do Pillow")
class TestVisaoEdicao(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nebell_img_"))
        self.origem = self.tmp / "foto.png"
        Image.new("RGB", (800, 600), (40, 80, 160)).save(self.origem)

    def editar(self, acao, valor=None):
        return V.editar(self.origem, acao, valor)

    def test_nao_toca_no_original(self):
        antes = self.origem.read_bytes()
        saida, _ = self.editar("cinza")
        self.assertNotEqual(saida, self.origem)
        self.assertEqual(self.origem.read_bytes(), antes)

    def test_redimensionar_por_porcentagem(self):
        saida, _ = self.editar("redimensionar", "50%")
        with Image.open(saida) as imagem:
            self.assertEqual(imagem.size, (400, 300))

    def test_redimensionar_por_tamanho(self):
        saida, _ = self.editar("redimensionar", "320x200")
        with Image.open(saida) as imagem:
            self.assertEqual(imagem.size, (320, 200))

    def test_redimensionar_por_largura_mantem_proporcao(self):
        saida, _ = self.editar("redimensionar", "400")
        with Image.open(saida) as imagem:
            self.assertEqual(imagem.size, (400, 300))

    def test_redimensionar_metade(self):
        saida, _ = self.editar("redimensionar", "metade")
        with Image.open(saida) as imagem:
            self.assertEqual(imagem.size, (400, 300))

    def test_redimensionar_porcentagem_zero_e_recusado(self):
        saida, erro = self.editar("redimensionar", "0%")
        self.assertIsNone(saida)
        self.assertIn("zero", erro)

    def test_redimensionar_gigante_e_recusado(self):
        saida, erro = self.editar("redimensionar", "90000x90000")
        self.assertIsNone(saida)
        self.assertIn("grande", erro)

    def test_recortar_centro(self):
        saida, _ = self.editar("recortar", "centro 50%")
        with Image.open(saida) as imagem:
            self.assertEqual(imagem.size, (400, 300))

    def test_recortar_por_coordenadas(self):
        saida, _ = self.editar("recortar", "10,10,100,50")
        with Image.open(saida) as imagem:
            self.assertEqual(imagem.size, (100, 50))

    def test_recortar_porcentagem_invalida(self):
        saida, erro = self.editar("recortar", "centro 150%")
        self.assertIsNone(saida)

    def test_girar_troca_os_lados(self):
        saida, _ = self.editar("girar", "90")
        with Image.open(saida) as imagem:
            self.assertEqual(imagem.size, (600, 800))

    def test_espelhar(self):
        saida, _ = self.editar("espelhar")
        self.assertTrue(saida.exists())

    def test_cinza(self):
        saida, _ = self.editar("cinza")
        with Image.open(saida) as imagem:
            self.assertEqual(imagem.mode, "L")

    def test_converter_para_jpg(self):
        saida, _ = self.editar("converter", "jpg")
        with Image.open(saida) as imagem:
            self.assertEqual(imagem.format, "JPEG")

    def test_converter_para_formato_desconhecido(self):
        saida, erro = self.editar("converter", "xyz")
        self.assertIsNone(saida)
        self.assertIn("xyz", erro)

    def test_comprimir_gera_jpeg(self):
        saida, mensagem = self.editar("comprimir", "40")
        with Image.open(saida) as imagem:
            self.assertEqual(imagem.format, "JPEG")

    def test_comprimir_com_qualidade_fracionaria(self):
        # "60.5" vinha do modelo e o Pillow recusa qualidade float.
        saida, mensagem = self.editar("comprimir", "60.5")
        self.assertIsNotNone(saida, mensagem)

    def test_miniatura_cabe_no_lado_pedido(self):
        saida, _ = self.editar("miniatura", "128")
        with Image.open(saida) as imagem:
            self.assertLessEqual(max(imagem.size), 128)

    def test_filtros_simples(self):
        for acao in ("clarear", "escurecer", "contraste", "borrar",
                     "nitidez", "contorno"):
            saida, mensagem = self.editar(acao)
            self.assertIsNotNone(saida, f"{acao}: {mensagem}")

    def test_acao_desconhecida_lista_as_possiveis(self):
        saida, erro = self.editar("fritar")
        self.assertIsNone(saida)
        self.assertIn("redimensionar", erro)

    def test_arquivo_inexistente(self):
        saida, erro = V.editar(self.tmp / "nao_existe.png", "cinza")
        self.assertIsNone(saida)
        self.assertIn("não encontrei", erro)

    def test_destino_escolhido(self):
        destino = self.tmp / "saida" / "nova.png"
        saida, _ = V.editar(self.origem, "cinza", destino=destino)
        self.assertEqual(saida, destino)
        self.assertTrue(destino.exists())

    def test_informacao(self):
        dados, erro = V.informacao(self.origem)
        self.assertIsNone(erro)
        self.assertEqual((dados["largura"], dados["altura"]), (800, 600))
        self.assertEqual(dados["formato"], "PNG")

    def test_descrever_e_falavel(self):
        frase, erro = V.descrever(self.origem)
        self.assertIsNone(erro)
        self.assertIn("800 por 600", frase)

    def test_descrever_arquivo_que_nao_e_imagem(self):
        texto = self.tmp / "nota.txt"
        texto.write_text("oi", encoding="utf-8")
        frase, erro = V.descrever(texto)
        self.assertIsNone(frase)

    def test_para_numero(self):
        self.assertEqual(V._para_numero("50%", 10), 50)
        self.assertEqual(V._para_numero("90 graus", 10), 90)
        self.assertEqual(V._para_numero("", 10), 10)
        self.assertEqual(V._para_numero(None, 10), 10)
        self.assertEqual(V._para_numero("abc", 10), 10)
        self.assertEqual(V._para_numero("1,5", 0), 1.5)


@unittest.skipUnless(TEM_OCR, "precisa do Tesseract instalado")
class TestVisaoOcr(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nebell_ocr_"))

    def test_le_o_texto_da_imagem(self):
        alvo = imagem_com_texto(self.tmp / "erro.png", "acesso negado")
        texto, erro = V.ler_texto(alvo)
        self.assertIsNone(erro)
        self.assertIn("acesso", texto.lower())

    def test_imagem_branca_avisa_que_nao_ha_texto(self):
        alvo = self.tmp / "branca.png"
        Image.new("RGB", (300, 200), "white").save(alvo)
        texto, erro = V.ler_texto(alvo)
        self.assertIsNone(texto)
        self.assertIn("texto", erro)

    def test_arquivo_inexistente(self):
        texto, erro = V.ler_texto(self.tmp / "nao_existe.png")
        self.assertIsNone(texto)
        self.assertIn("não encontrei", erro)

    def test_preparar_para_ocr_aumenta_a_imagem(self):
        with Image.open(imagem_com_texto(self.tmp / "p.png")) as imagem:
            preparada = V.preparar_para_ocr(imagem)
            self.assertGreaterEqual(preparada.width, imagem.width)

    def test_ler_tela_usa_a_captura(self):
        alvo = imagem_com_texto(self.tmp / "tela.png", "teste de tela")

        def captura_falsa(destino, regiao=None, monitor_inteiro=True):
            Path(destino).write_bytes(alvo.read_bytes())
            return Path(destino), None

        with mock.patch.object(V, "capturar_tela", captura_falsa):
            texto, erro = V.ler_tela(self.tmp)

        self.assertIsNone(erro)
        self.assertIn("tela", texto.lower())

    def test_ler_tela_repassa_o_erro_da_captura(self):
        with mock.patch.object(
            V, "capturar_tela", lambda *a, **k: (None, "sem monitor")
        ):
            texto, erro = V.ler_tela(self.tmp)

        self.assertIsNone(texto)
        self.assertEqual(erro, "sem monitor")


# ============================================================
# JANELAS E TECLADO
# ============================================================

class TestAtalhos(unittest.TestCase):
    def test_combinacao_simples(self):
        codigos, erro = J.interpretar_atalho("ctrl+c")
        self.assertIsNone(erro)
        self.assertEqual(codigos, [J.VK["ctrl"], J.VK["c"]])

    def test_tres_teclas(self):
        codigos, _ = J.interpretar_atalho("ctrl+shift+n")
        self.assertEqual(len(codigos), 3)

    def test_separado_por_espaco(self):
        codigos, _ = J.interpretar_atalho("alt tab")
        self.assertEqual(codigos, [J.VK["alt"], J.VK["tab"]])

    def test_nome_em_portugues(self):
        codigos, _ = J.interpretar_atalho("copiar")
        self.assertEqual(codigos, [J.VK["ctrl"], J.VK["c"]])

    def test_todos_os_nomes_conhecidos_funcionam(self):
        for nome in J.ATALHOS_NOMEADOS:
            codigos, erro = J.interpretar_atalho(nome)
            self.assertIsNone(erro, f"{nome}: {erro}")
            self.assertTrue(codigos)

    def test_tecla_de_funcao(self):
        codigos, _ = J.interpretar_atalho("f5")
        self.assertEqual(codigos, [0x74])

    def test_tecla_inventada(self):
        codigos, erro = J.interpretar_atalho("abracadabra")
        self.assertIsNone(codigos)
        self.assertIn("abracadabra", erro)

    def test_vazio(self):
        codigos, erro = J.interpretar_atalho("")
        self.assertIsNone(codigos)

    def test_teclas_demais(self):
        codigos, erro = J.interpretar_atalho("a+b+c+d+e")
        self.assertIsNone(codigos)
        self.assertIn("demais", erro)

    def test_acento_nao_quebra(self):
        codigos, erro = J.interpretar_atalho("espaço")
        self.assertIsNone(erro)


class TestAreasDaTela(unittest.TestCase):
    def area(self, posicao):
        return J.calcular_area(posicao, 1920, 1080)

    def test_metade_esquerda(self):
        self.assertEqual(self.area("esquerda"), (0, 0, 960, 1080))

    def test_metade_direita(self):
        self.assertEqual(self.area("direita"), (960, 0, 960, 1080))

    def test_tela_cheia(self):
        self.assertEqual(self.area("tela cheia"), (0, 0, 1920, 1080))

    def test_cantos(self):
        self.assertEqual(self.area("canto superior esquerdo"), (0, 0, 960, 540))
        self.assertEqual(
            self.area("canto inferior direito"), (960, 540, 960, 540)
        )

    def test_sinonimo_de_fala(self):
        self.assertEqual(self.area("metade esquerda"), self.area("esquerda"))

    def test_posicao_desconhecida(self):
        self.assertIsNone(self.area("na diagonal"))

    def test_largura_impar_nao_perde_pixel(self):
        esquerda = J.calcular_area("esquerda", 1365, 768)
        direita = J.calcular_area("direita", 1365, 768)
        self.assertEqual(esquerda[2] + direita[2], 1365)

    def test_todas_as_posicoes_anunciadas_existem(self):
        for posicao in J.POSICOES:
            self.assertIsNotNone(self.area(posicao), posicao)


class TestAcharJanela(unittest.TestCase):
    def setUp(self):
        self.janelas = [
            {"identificador": 1, "titulo": "Brave Browser",
             "em_foco": False, "minimizada": False},
            {"identificador": 2, "titulo": "nebell.py - Visual Studio Code",
             "em_foco": True, "minimizada": False},
            {"identificador": 3, "titulo": "Documento1 - Word",
             "em_foco": False, "minimizada": True},
        ]

    def test_pedaco_do_titulo(self):
        janela, erro = J.achar("brave", self.janelas)
        self.assertIsNone(erro)
        self.assertEqual(janela["identificador"], 1)

    def test_sem_diferenca_de_acento_ou_caixa(self):
        janela, _ = J.achar("WORD", self.janelas)
        self.assertEqual(janela["identificador"], 3)

    def test_titulo_exato_tem_preferencia(self):
        janela, _ = J.achar("Brave Browser", self.janelas)
        self.assertEqual(janela["identificador"], 1)

    def test_palavras_fora_de_ordem(self):
        janela, _ = J.achar("code studio", self.janelas)
        self.assertEqual(janela["identificador"], 2)

    def test_nao_achou_lista_as_abertas(self):
        janela, erro = J.achar("photoshop", self.janelas)
        self.assertIsNone(janela)
        self.assertIn("Brave Browser", erro)

    def test_pedido_vazio(self):
        janela, erro = J.achar("", self.janelas)
        self.assertIsNone(janela)


@unittest.skipIf(EH_WINDOWS, "fora do Windows a recusa é o comportamento")
class TestJanelasForaDoWindows(unittest.TestCase):
    def test_tudo_recusa_com_explicacao(self):
        chamadas = (
            lambda: J.listar(),
            lambda: J.descrever_janelas(),
            lambda: J.focar("x"),
            lambda: J.mudar_estado("x", "minimizar"),
            lambda: J.fechar("x"),
            lambda: J.posicionar("x", "esquerda"),
            lambda: J.atalho("ctrl+c"),
            lambda: J.digitar("oi"),
            lambda: J.colar_texto("oi"),
            lambda: J.minimizar_tudo(),
        )

        for chamada in chamadas:
            resultado, mensagem = chamada()
            self.assertIsNone(resultado)
            self.assertIn("Windows", mensagem)

    def test_tamanho_da_tela(self):
        self.assertEqual(J.tamanho_da_tela(), (None, None))

    def test_user32_e_none(self):
        self.assertIsNone(J._user32())


class TestDigitacaoLimites(unittest.TestCase):
    def test_texto_vazio(self):
        with mock.patch.object(J, "_user32", lambda: mock.MagicMock()):
            quantos, erro = J.digitar("")

        self.assertIsNone(quantos)
        self.assertIn("escrever", erro)

    def test_texto_longo_demais(self):
        with mock.patch.object(J, "_user32", lambda: mock.MagicMock()):
            quantos, erro = J.digitar("a" * (J.LIMITE_DIGITACAO + 1))

        self.assertIsNone(quantos)
        self.assertIn("digito até", erro)

    def test_estado_desconhecido(self):
        with mock.patch.object(J, "_user32", lambda: mock.MagicMock()), \
                mock.patch.object(J, "achar", lambda a, j=None: ({
                    "identificador": 1, "titulo": "X"}, None)):
            titulo, erro = J.mudar_estado("x", "fritar")

        self.assertIsNone(titulo)
        self.assertIn("minimizar", erro)

    def test_posicao_desconhecida(self):
        with mock.patch.object(J, "_user32", lambda: mock.MagicMock()), \
                mock.patch.object(J, "tamanho_da_tela", lambda: (1920, 1080)):
            titulo, erro = J.posicionar("x", "na diagonal")

        self.assertIsNone(titulo)
        self.assertIn("esquerda", erro)

    def test_ruido_de_sistema_e_filtrado(self):
        for titulo in ("Program Manager", "Default IME", "Windows Input Experience"):
            self.assertTrue(J.RUIDO.match(titulo), titulo)

    def test_titulo_comum_nao_e_filtrado(self):
        for titulo in ("Brave", "Word", "Configurações do jogo"):
            self.assertFalse(J.RUIDO.match(titulo), titulo)


# ============================================================
# DOCUMENTOS
# ============================================================

class DocsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nebell_doc_"))


class TestDocsTipos(DocsTest):
    def test_reconhece_as_extensoes(self):
        self.assertEqual(D.tipo_de("a.pdf"), "pdf")
        self.assertEqual(D.tipo_de("a.DOCX"), "word")
        self.assertEqual(D.tipo_de("a.xlsx"), "planilha")
        self.assertEqual(D.tipo_de("a.csv"), "csv")
        self.assertEqual(D.tipo_de("a.pptx"), "apresentacao")
        self.assertEqual(D.tipo_de("a.txt"), "texto")
        self.assertEqual(D.tipo_de("a.py"), "texto")
        self.assertIsNone(D.tipo_de("a.png"))

    def test_arquivo_inexistente(self):
        dados, erro = D.ler(self.tmp / "nao_existe.pdf")
        self.assertIsNone(dados)
        self.assertIn("não encontrei", erro)

    def test_pasta_nao_e_documento(self):
        dados, erro = D.ler(self.tmp)
        self.assertIsNone(dados)
        self.assertIn("pasta", erro)

    def test_arquivo_vazio(self):
        vazio = self.tmp / "vazio.txt"
        vazio.write_text("", encoding="utf-8")
        dados, erro = D.ler(vazio)
        self.assertIsNone(dados)
        self.assertIn("vazio", erro)

    def test_extensao_desconhecida_diz_o_que_le(self):
        estranho = self.tmp / "coisa.xyz"
        estranho.write_text("dados", encoding="utf-8")
        dados, erro = D.ler(estranho)
        self.assertIsNone(dados)
        self.assertIn("PDF", erro)

    def test_arquivo_gigante_e_recusado(self):
        grande = self.tmp / "grande.txt"
        grande.write_text("x", encoding="utf-8")

        verdadeiro = Path.stat

        class Fingir:
            st_size = D.MAX_BYTES + 1
            st_mode = verdadeiro(grande).st_mode

        with mock.patch.object(
            Path, "stat", lambda self, **kwargs: Fingir()
        ):
            dados, erro = D.ler(grande)

        self.assertIsNone(dados)
        self.assertIn("grande", erro)

    def test_doc_antigo_orienta_a_converter(self):
        velho = self.tmp / "antigo.doc"
        velho.write_bytes(b"\xd0\xcf qualquer coisa")
        dados, erro = D.ler(velho)
        self.assertIsNone(dados)
        self.assertIn("docx", erro)


class TestDocsTexto(DocsTest):
    def test_le_texto_simples(self):
        alvo = self.tmp / "nota.txt"
        alvo.write_text("lembrar de pagar a luz", encoding="utf-8")

        dados, erro = D.ler(alvo)
        self.assertIsNone(erro)
        self.assertIn("pagar a luz", dados["texto"])
        self.assertEqual(dados["palavras"], 5)
        self.assertEqual(dados["nome"], "nota.txt")

    def test_le_arquivo_latin1(self):
        alvo = self.tmp / "velho.txt"
        alvo.write_bytes("ação e coração".encode("cp1252"))

        dados, erro = D.ler(alvo)
        self.assertIsNone(erro)
        self.assertIn("ação", dados["texto"])

    def test_texto_e_codigo_vem_exatamente_como_estao(self):
        # Nao pode normalizar: isto apagaria a indentacao, e um .py
        # relido e regravado sem indentacao nao roda.
        codigo = (
            "def soma(a, b):\n"
            "    if a > b:\n"
            "        return a\n"
            "    return b\n"
        )
        alvo = self.tmp / "codigo.py"
        alvo.write_text(codigo, encoding="utf-8")

        dados, _ = D.ler(alvo)
        self.assertEqual(dados["texto"], codigo)

    def test_linhas_vazias_do_texto_sao_preservadas(self):
        alvo = self.tmp / "espacado.txt"
        alvo.write_text("um\n\n\n\n\ndois", encoding="utf-8")

        dados, _ = D.ler(alvo)
        self.assertEqual(dados["texto"], "um\n\n\n\n\ndois")

    def test_fim_de_linha_do_windows_e_normalizado(self):
        alvo = self.tmp / "crlf.py"
        alvo.write_bytes(b"a = 1\r\nb = 2\r\n")

        dados, _ = D.ler(alvo)
        self.assertEqual(dados["texto"], "a = 1\nb = 2\n")

    def test_documento_do_word_continua_normalizado(self):
        # O `limpar` segue valendo onde faz sentido.
        self.assertEqual(D.limpar("a   b\n\n\n\nc"), "a b\n\nc")

    def test_le_csv_com_ponto_e_virgula(self):
        alvo = self.tmp / "dados.csv"
        alvo.write_text("nome;valor\nluz;300\n", encoding="utf-8")

        dados, erro = D.ler(alvo)
        self.assertIsNone(erro)
        self.assertEqual(dados["separador"], ";")
        self.assertIn("luz | 300", dados["texto"])

    def test_le_csv_com_virgula(self):
        alvo = self.tmp / "dados2.csv"
        alvo.write_text("nome,valor\nagua,90\n", encoding="utf-8")

        dados, _ = D.ler(alvo)
        self.assertEqual(dados["separador"], ",")


class TestDocsOffice(DocsTest):
    def test_le_word_com_titulo_e_tabela(self):
        try:
            from docx import Document
        except Exception:
            self.skipTest("precisa do python-docx")

        documento = Document()
        documento.add_heading("Plano", level=1)
        documento.add_paragraph("Primeira etapa.")
        tabela = documento.add_table(rows=1, cols=2)
        tabela.cell(0, 0).text = "Etapa"
        tabela.cell(0, 1).text = "Prazo"

        alvo = self.tmp / "plano.docx"
        documento.save(alvo)

        dados, erro = D.ler(alvo)
        self.assertIsNone(erro)
        self.assertIn("## Plano", dados["texto"])
        self.assertIn("Etapa | Prazo", dados["texto"])

    def test_le_planilha(self):
        try:
            import openpyxl
        except Exception:
            self.skipTest("precisa do openpyxl")

        livro = openpyxl.Workbook()
        folha = livro.active
        folha.title = "Gastos"
        folha.append(["Item", "Valor"])
        folha.append(["Internet", 120])

        alvo = self.tmp / "gastos.xlsx"
        livro.save(alvo)

        dados, erro = D.ler(alvo)
        self.assertIsNone(erro)
        self.assertEqual(dados["folhas"], ["Gastos"])
        self.assertIn("Internet | 120", dados["texto"])

    def test_le_apresentacao(self):
        try:
            from pptx import Presentation
        except Exception:
            self.skipTest("precisa do python-pptx")

        apresentacao = Presentation()
        slide = apresentacao.slides.add_slide(apresentacao.slide_layouts[1])
        slide.shapes.title.text = "Nebell"
        slide.placeholders[1].text = "Assistente local"

        alvo = self.tmp / "slides.pptx"
        apresentacao.save(alvo)

        dados, erro = D.ler(alvo)
        self.assertIsNone(erro)
        self.assertEqual(dados["slides"], 1)
        self.assertIn("Assistente local", dados["texto"])

    def test_le_pdf(self):
        try:
            from reportlab.pdfgen import canvas
        except Exception:
            self.skipTest("precisa do reportlab para montar o PDF do teste")

        alvo = self.tmp / "relatorio.pdf"
        folha = canvas.Canvas(str(alvo))
        folha.drawString(70, 760, "Relatorio trimestral")
        folha.showPage()
        folha.drawString(70, 760, "Conclusao: manter o plano")
        folha.save()

        dados, erro = D.ler(alvo)
        self.assertIsNone(erro)
        self.assertEqual(dados["paginas"], 2)
        self.assertIn("Relatorio trimestral", dados["texto"])
        self.assertIn("[página 2]", dados["texto"])

    def test_pacote_faltando_diz_o_comando(self):
        with mock.patch.dict(sys.modules, {"pypdf": None}):
            with mock.patch.object(
                D, "_importar",
                lambda tipo: (None, "preciso de um pacote: pip install pypdf")
            ):
                dados, erro = D.ler_pdf("x.pdf")

        self.assertIsNone(dados)
        self.assertIn("pip install", erro)


class TestDocsResumo(DocsTest):
    def test_texto_curto_vai_inteiro(self):
        self.assertEqual(D.recortar_para_resumo("oi", 1000), "oi")

    def test_texto_longo_e_cortado_no_limite(self):
        recorte = D.recortar_para_resumo("a" * 50_000, 2000)
        self.assertLessEqual(len(recorte), 2000)

    def test_recorte_guarda_o_comeco_e_o_fim(self):
        texto = "COMECO" + "x" * 50_000 + "FINAL"
        recorte = D.recortar_para_resumo(texto, 2000)
        self.assertTrue(recorte.startswith("COMECO"))
        self.assertTrue(recorte.endswith("FINAL"))

    def test_recorte_avisa_o_que_omitiu(self):
        recorte = D.recortar_para_resumo("a" * 50_000, 2000)
        self.assertIn("omitida", recorte)

    def test_pedido_de_resumo_tem_instrucao(self):
        dados = {
            "nome": "x.pdf", "tipo": "pdf", "paginas": 2, "lidas": 2,
            "texto": "conteudo", "palavras": 1,
        }
        pedido = D.pedido_de_resumo(dados)
        self.assertIn("Resuma", pedido)
        self.assertIn("conteudo", pedido)
        self.assertIn("Não invente", pedido)

    def test_pedido_com_pergunta_manda_responder(self):
        dados = {
            "nome": "x.pdf", "tipo": "pdf", "paginas": 1, "lidas": 1,
            "texto": "o prazo é novembro", "palavras": 4,
        }
        pedido = D.pedido_de_resumo(dados, "qual o prazo?")
        self.assertIn("qual o prazo?", pedido)
        self.assertNotIn("Resuma o documento", pedido)

    def test_ficha_do_pdf_diz_as_paginas(self):
        ficha = D.ficha({
            "nome": "x.pdf", "tipo": "pdf", "paginas": 10, "lidas": 10,
            "palavras": 500,
        })
        self.assertIn("10 páginas", ficha)

    def test_ficha_avisa_quando_leu_so_uma_parte(self):
        ficha = D.ficha({
            "nome": "x.pdf", "tipo": "pdf", "paginas": 900, "lidas": 400,
            "palavras": 500,
        })
        self.assertIn("400", ficha)


class TestDocsProcurar(DocsTest):
    def setUp(self):
        super().setUp()
        self.dados = {
            "nome": "contrato.txt",
            "texto": (
                "O prazo de entrega é novembro. "
                "O pagamento ocorre em dezembro. "
                "O prazo pode ser renegociado."
            ),
        }

    def test_acha_todas_as_ocorrencias(self):
        achados = D.procurar_dentro(self.dados, "prazo")
        self.assertEqual(len(achados), 2)

    def test_ignora_acento_e_caixa(self):
        achados = D.procurar_dentro(self.dados, "PRAZO")
        self.assertEqual(len(achados), 2)

    def test_traz_o_contexto_em_volta(self):
        achados = D.procurar_dentro(self.dados, "pagamento")
        self.assertIn("dezembro", achados[0])

    def test_termo_ausente(self):
        self.assertEqual(D.procurar_dentro(self.dados, "foguete"), [])

    def test_termo_vazio(self):
        self.assertEqual(D.procurar_dentro(self.dados, ""), [])


# ============================================================
# SENTINELA DE HARDWARE
# ============================================================

class TestAvaliarHardware(unittest.TestCase):
    def test_tudo_normal_nao_avisa(self):
        foto = {
            "memoria": {"porcento": 40, "livre_mb": 4000},
            "disco": {"livre_gb": 200, "total_gb": 476, "porcento": 50},
            "cpu": {"temperatura": 55},
            "gpu": {"temperatura": 50, "vram_porcento": 30},
            "bateria": {"porcento": 90, "na_tomada": True},
        }
        self.assertEqual(S.avaliar(foto), [])

    def test_foto_vazia_nao_estoura(self):
        self.assertEqual(S.avaliar({}), [])

    def test_memoria_no_limite(self):
        achados = S.avaliar({"memoria": {"porcento": 95, "livre_mb": 300}})
        self.assertEqual(achados[0][0], "memoria")
        self.assertEqual(achados[0][1], "perigo")

    def test_memoria_pouca_mesmo_com_porcento_baixo(self):
        achados = S.avaliar({"memoria": {"porcento": 60, "livre_mb": 200}})
        self.assertTrue(achados)

    def test_disco_quase_cheio_e_perigo(self):
        achados = S.avaliar(
            {"disco": {"caminho": "C:", "livre_gb": 2, "total_gb": 476,
                       "porcento": 99}}
        )
        self.assertEqual(achados[0][0], "disco")
        self.assertEqual(achados[0][1], "perigo")

    def test_disco_cheio_em_porcento_e_so_aviso(self):
        achados = S.avaliar(
            {"disco": {"caminho": "C:", "livre_gb": 40, "total_gb": 476,
                       "porcento": 96}}
        )
        self.assertEqual(achados[0][1], "aviso")

    def test_temperatura_da_placa(self):
        achados = S.avaliar({"gpu": {"temperatura": 90}})
        self.assertEqual(achados[0][0], "gpu_temperatura")

    def test_vram_cheia_e_aviso(self):
        achados = S.avaliar({"gpu": {"vram_porcento": 97}})
        self.assertEqual(achados[0][0], "gpu_vram")

    def test_temperatura_do_processador(self):
        achados = S.avaliar({"cpu": {"temperatura": 95}})
        self.assertEqual(achados[0][0], "cpu_temperatura")

    def test_sem_sensor_de_temperatura_nao_inventa(self):
        self.assertEqual(S.avaliar({"cpu": {"uso_porcento": 100}}), [])

    def test_bateria_baixa_fora_da_tomada(self):
        achados = S.avaliar(
            {"bateria": {"porcento": 8, "na_tomada": False, "minutos": 10}}
        )
        self.assertEqual(achados[0][0], "bateria")
        self.assertIn("tomada", achados[0][2])

    def test_bateria_baixa_na_tomada_nao_avisa(self):
        self.assertEqual(
            S.avaliar({"bateria": {"porcento": 8, "na_tomada": True}}), []
        )

    def test_limites_podem_ser_afrouxados(self):
        foto = {"gpu": {"temperatura": 88}}
        self.assertTrue(S.avaliar(foto))
        self.assertEqual(S.avaliar(foto, {"gpu_temperatura": 95}), [])


class TestSentinelaVolta(unittest.TestCase):
    def setUp(self):
        self.foto = {
            "memoria": {"porcento": 95, "livre_mb": 300},
            "disco": {"caminho": "C:", "livre_gb": 2, "total_gb": 476,
                      "porcento": 99},
            "gpu": {"nome": "RTX 3050", "temperatura": 88,
                    "vram_porcento": 96},
        }
        self.avisos = []
        self.sentinela = S.Sentinela(
            ao_avisar=lambda frase, gravidade: self.avisos.append(
                (gravidade, frase)
            ),
            log=lambda *a: None,
        )

    def conferir(self, agora):
        with mock.patch.object(S, "medir_tudo", lambda: self.foto), \
                mock.patch.object(
                    S, "maiores_processos",
                    lambda quantos=5: [{"nome": "chrome.exe",
                                        "memoria_mb": 1800}]):
            return self.sentinela.conferir(agora=agora)

    def test_primeira_volta_e_calada(self):
        self.assertEqual(self.conferir(1000), [])
        self.assertEqual(self.avisos, [])

    def test_avisa_na_segunda_volta(self):
        self.conferir(1000)
        self.assertTrue(self.conferir(1001))
        self.assertTrue(self.avisos)

    def test_nao_despeja_tudo_de_uma_vez(self):
        self.conferir(1000)
        primeira = self.conferir(1001)
        # dois assuntos no maximo (mais o detalhe da memoria)
        self.assertLessEqual(len(primeira), S.MAX_ASSUNTOS_POR_VOLTA + 1)

    def test_o_resto_sai_nas_voltas_seguintes(self):
        self.conferir(1000)
        total = 0

        for segundo in range(1001, 1006):
            total += len(self.conferir(segundo))

        self.assertGreaterEqual(total, 4)

    def test_mesmo_assunto_fica_quieto_por_vinte_minutos(self):
        self.conferir(1000)
        self.conferir(1001)
        self.conferir(1002)
        quantos = len(self.avisos)

        self.assertEqual(self.conferir(1100), [])
        self.assertEqual(len(self.avisos), quantos)

    def test_volta_a_avisar_depois_do_silencio(self):
        self.conferir(1000)
        self.conferir(1001)
        self.assertTrue(self.conferir(1001 + S.SILENCIO_POR_ASSUNTO + 1))

    def test_problema_resolvido_rearma_o_assunto(self):
        self.conferir(1000)
        self.conferir(1001)
        self.conferir(1002)

        self.foto = {"memoria": {"porcento": 30, "livre_mb": 5000}}
        self.conferir(1003)

        self.foto = {"memoria": {"porcento": 95, "livre_mb": 300}}
        self.assertTrue(self.conferir(1004))

    def test_perigo_sai_antes_do_aviso(self):
        self.conferir(1000)
        self.conferir(1001)
        self.assertEqual(self.avisos[0][0], "perigo")

    def test_memoria_traz_quem_esta_pesando(self):
        self.conferir(1000)
        self.conferir(1001)
        tudo = " ".join(frase for _, frase in self.avisos)
        self.assertIn("chrome.exe", tudo)

    def test_falha_do_aviso_nao_derruba_a_volta(self):
        self.sentinela.ao_avisar = lambda frase, gravidade: 1 / 0
        self.conferir(1000)
        self.assertTrue(self.conferir(1001))

    def test_iniciar_e_parar(self):
        self.sentinela.intervalo = 0.01
        self.assertTrue(self.sentinela.iniciar())
        self.assertFalse(self.sentinela.iniciar())
        self.sentinela.parar()
        self.assertFalse(self.sentinela.ligada)


class TestMedidas(unittest.TestCase):
    def test_disco_do_sistema(self):
        dados = S.medir_disco()
        self.assertIsNotNone(dados)
        self.assertGreater(dados["total_gb"], 0)

    def test_disco_inexistente(self):
        self.assertIsNone(S.medir_disco("/caminho/que/nao/existe/mesmo"))

    def test_gpu_sem_nvidia_smi(self):
        with mock.patch.object(S, "_rodar", lambda *a, **k: ""):
            self.assertIsNone(S.medir_gpu())

    def test_gpu_le_a_saida_da_nvidia_smi(self):
        saida = "NVIDIA GeForce RTX 3050 Laptop GPU, 67, 3200, 6144, 45"

        with mock.patch.object(S, "_rodar", lambda *a, **k: saida):
            dados = S.medir_gpu()

        self.assertEqual(dados["temperatura"], 67)
        self.assertEqual(dados["vram_total_mb"], 6144)
        self.assertAlmostEqual(dados["vram_porcento"], 52.1, places=1)

    def test_gpu_com_saida_truncada(self):
        with mock.patch.object(S, "_rodar", lambda *a, **k: "RTX, 67"):
            self.assertIsNone(S.medir_gpu())

    def test_gpu_com_campo_nao_numerico(self):
        saida = "RTX 3050, [N/A], [N/A], [N/A], 0"

        with mock.patch.object(S, "_rodar", lambda *a, **k: saida):
            dados = S.medir_gpu()

        self.assertIsNone(dados["temperatura"])
        self.assertNotIn("vram_porcento", dados)

    def test_sem_psutil_nao_estoura(self):
        with mock.patch.object(S, "psutil", None):
            self.assertIsNone(S.medir_memoria())
            self.assertIsNone(S.medir_cpu())
            self.assertIsNone(S.medir_bateria())
            self.assertEqual(S.maiores_processos(), [])

    def test_medir_tudo_tem_todas_as_chaves(self):
        foto = S.medir_tudo()

        for chave in ("memoria", "disco", "cpu", "gpu", "bateria", "quando"):
            self.assertIn(chave, foto)

    def test_relatorio_e_falavel(self):
        texto = S.Sentinela(log=lambda *a: None).relatorio()
        self.assertIsInstance(texto, str)
        self.assertTrue(texto.endswith("."))

    def test_relatorio_sem_nenhuma_medida(self):
        with mock.patch.object(S, "medir_tudo", lambda: {
            "memoria": None, "disco": None, "cpu": None,
            "gpu": None, "bateria": None, "quando": 0,
        }):
            texto = S.Sentinela(log=lambda *a: None).relatorio()

        self.assertIn("psutil", texto)

    def test_relatorio_aponta_o_problema(self):
        with mock.patch.object(S, "medir_tudo", lambda: {
            "memoria": {"porcento": 96, "livre_mb": 200, "total_mb": 8000},
            "disco": None, "cpu": None, "gpu": None, "bateria": None,
            "quando": 0,
        }):
            texto = S.Sentinela(log=lambda *a: None).relatorio()

        self.assertIn("Atenção", texto)


# ============================================================
# NORMALIZACAO (os modulos novos trazem a sua)
# ============================================================

class TestNormalizarEmTodosOsModulos(unittest.TestCase):
    def test_tira_acento_e_caixa(self):
        for modulo in (A, D, J, S, V):
            self.assertEqual(
                modulo.normalize("  Ação   DO   Coração "),
                "acao do coracao",
                modulo.__name__,
            )

    def test_aceita_nao_texto(self):
        for modulo in (A, D, J, S, V):
            self.assertEqual(modulo.normalize(None), "none", modulo.__name__)
            self.assertEqual(modulo.normalize(12), "12", modulo.__name__)


# ============================================================
# DOCUMENTOS: CRIAR
# ============================================================

class CriarDocsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nebell_criar_"))

    def criar(self, nome, conteudo):
        return D.criar(self.tmp / nome, conteudo)

    def ler(self, nome):
        dados, erro = D.ler(self.tmp / nome)
        self.assertIsNone(erro, erro)
        return dados


class TestDaParaCriar(unittest.TestCase):
    def test_reconhece_os_formatos(self):
        self.assertEqual(D.da_para_criar("a.docx"), "word")
        self.assertEqual(D.da_para_criar("a.xlsx"), "planilha")
        self.assertEqual(D.da_para_criar("a.pptx"), "apresentacao")
        self.assertEqual(D.da_para_criar("a.PDF"), "pdf")

    def test_texto_puro_nao_e_documento(self):
        for nome in ("a.py", "a.txt", "a.java", "a.md"):
            self.assertIsNone(D.da_para_criar(nome), nome)

    def test_todo_formato_tem_montador(self):
        for tipo in D.CRIAVEIS.values():
            self.assertIn(tipo, D.MONTADORES, tipo)
            self.assertIn(tipo, D.PACOTES_PARA_CRIAR, tipo)


@PRECISA_WORD
class TestCriarWord(CriarDocsTest):
    def test_titulos_e_itens(self):
        feito, erro = self.criar(
            "r.docx", "# Título\n## Parte\n- um\n- dois\n\nParágrafo."
        )
        self.assertIsNone(erro)

        texto = self.ler("r.docx")["texto"]
        self.assertIn("Título", texto)
        self.assertIn("dois", texto)
        self.assertIn("Parágrafo", texto)

    def test_lista_numerada(self):
        self.criar("n.docx", "1. primeiro\n2) segundo")
        texto = self.ler("n.docx")["texto"]

        self.assertIn("primeiro", texto)
        # O numero vira estilo de lista, nao texto solto.
        self.assertNotIn("1.", texto)

    def test_conteudo_vazio_nao_estoura(self):
        feito, erro = self.criar("v.docx", "")
        self.assertIsNone(erro)
        self.assertTrue(feito.exists())

    def test_cria_a_pasta_que_falta(self):
        feito, erro = D.criar(self.tmp / "a" / "b" / "x.docx", "# oi")
        self.assertIsNone(erro)
        self.assertTrue(feito.exists())


@PRECISA_PLANILHA
class TestCriarPlanilha(CriarDocsTest):
    def colunas(self, nome):
        import openpyxl

        livro = openpyxl.load_workbook(self.tmp / nome)
        linhas = [list(l) for l in livro.active.iter_rows(values_only=True)]
        livro.close()
        return linhas

    def test_separador_ponto_e_virgula(self):
        self.criar("a.xlsx", "Item;Valor\nLuz;300")
        self.assertEqual(self.colunas("a.xlsx")[1], ["Luz", 300])

    def test_separador_barra_vertical(self):
        self.criar("b.xlsx", "Item | Valor\nLuz | 300")
        self.assertEqual(self.colunas("b.xlsx")[1], ["Luz", 300])

    def test_separador_tabulacao(self):
        self.criar("c.xlsx", "Item\tValor\nLuz\t300")
        self.assertEqual(self.colunas("c.xlsx")[1], ["Luz", 300])

    def test_numero_com_virgula_decimal(self):
        self.criar("d.xlsx", "Item;Valor\nLuz;120,50")
        self.assertAlmostEqual(self.colunas("d.xlsx")[1][1], 120.50, places=2)

    def test_numero_com_real_e_porcento(self):
        self.criar("e.xlsx", "a;b\nR$ 300;15%")
        linha = self.colunas("e.xlsx")[1]
        self.assertEqual(linha[0], 300)
        self.assertEqual(linha[1], 15)

    def test_texto_continua_texto(self):
        self.criar("f.xlsx", "Nome;Obs\nAna;pagou em 3x")
        self.assertEqual(self.colunas("f.xlsx")[1][1], "pagou em 3x")

    def test_uma_coluna_so(self):
        self.criar("g.xlsx", "primeiro\nsegundo")
        self.assertEqual(self.colunas("g.xlsx")[0], ["primeiro"])

    def test_linha_vazia_e_ignorada(self):
        self.criar("h.xlsx", "a;b\n\n\nc;d")
        self.assertEqual(len(self.colunas("h.xlsx")), 2)


@PRECISA_APRESENTACAO
class TestCriarApresentacao(CriarDocsTest):
    def test_um_slide_por_titulo(self):
        self.criar(
            "a.pptx", "# Um\n- ponto\n# Dois\n- outro"
        )
        self.assertEqual(self.ler("a.pptx")["slides"], 2)

    def test_separador_de_tres_tracos(self):
        self.criar("b.pptx", "# Um\n- ponto\n---\n# Dois\n- outro")
        self.assertEqual(self.ler("b.pptx")["slides"], 2)

    def test_slide_so_com_titulo(self):
        feito, erro = self.criar("c.pptx", "# Só o título")
        self.assertIsNone(erro)
        self.assertIn("título", self.ler("c.pptx")["texto"])

    def test_sem_titulo_nenhum(self):
        feito, erro = self.criar("d.pptx", "texto solto\noutra linha")
        self.assertIsNone(erro)
        self.assertEqual(self.ler("d.pptx")["slides"], 1)

    def test_conteudo_vazio_gera_um_slide(self):
        feito, erro = self.criar("e.pptx", "")
        self.assertIsNone(erro)
        self.assertTrue(feito.exists())

    def test_separar_slides_e_funcao_pura(self):
        slides = D._separar_slides("# A\n- um\n# B\n- dois")
        self.assertEqual(slides, [("A", ["um"]), ("B", ["dois"])])


@PRECISA_PDF
class TestCriarPdf(CriarDocsTest):
    def test_pdf_com_titulo(self):
        feito, erro = self.criar("a.pdf", "# Título\nUm parágrafo.")
        self.assertIsNone(erro)
        self.assertIn("Título", self.ler("a.pdf")["texto"])

    def test_texto_longo_vira_varias_paginas(self):
        self.criar(
            "b.pdf", chr(10).join(f"linha {n}" for n in range(200))
        )
        self.assertGreater(self.ler("b.pdf")["paginas"], 1)

    def test_linha_larga_e_quebrada(self):
        feito, erro = self.criar("c.pdf", "palavra " * 200)
        self.assertIsNone(erro)
        self.assertTrue(feito.exists())

    def test_vazio_nao_estoura(self):
        feito, erro = self.criar("d.pdf", "")
        self.assertIsNone(erro)
        self.assertTrue(feito.exists())


class TestCriarRecusas(CriarDocsTest):
    def test_extensao_desconhecida(self):
        feito, erro = self.criar("x.odt", "a")
        self.assertIsNone(feito)
        self.assertIn("odt", erro)

    def test_pacote_faltando_diz_o_comando(self):
        with mock.patch.object(
            D, "_importar_para_criar",
            lambda tipo: (None, "instale com: pip install python-docx")
        ):
            feito, erro = self.criar("x.docx", "# oi")

        self.assertIsNone(feito)
        self.assertIn("pip install", erro)

    def test_o_que_ele_cria_ele_consegue_ler(self):
        # A prova de que o arquivo e valido: o leitor do proprio modulo
        # abre o que o montador gravou. Só entra na lista o formato
        # cujo pacote existe nesta máquina.
        casos = []

        if TEM_WORD:
            casos.append(("r.docx", "# Título\nTexto."))

        if TEM_PLANILHA:
            casos.append(("p.xlsx", "a;b\n1;2"))

        if TEM_APRESENTACAO:
            casos.append(("s.pptx", "# Slide\n- ponto"))

        if TEM_PDF:
            casos.append(("d.pdf", "# Título\nTexto."))

        if not casos:
            self.skipTest("nenhum pacote de documento instalado")

        for nome, conteudo in casos:
            feito, erro = self.criar(nome, conteudo)
            self.assertIsNone(erro, f"{nome}: {erro}")

            dados, erro = D.ler(feito)
            self.assertIsNone(erro, f"{nome}: {erro}")
            self.assertTrue(dados["texto"].strip(), nome)


if __name__ == "__main__":
    unittest.main(verbosity=2)
