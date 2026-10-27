"""
Testes da internet do NEBELL.

O urllib e simulado com as respostas REAIS das APIs (formato conferido
na documentacao da AwesomeAPI e do Open-Meteo), para o codigo de leitura
nao sair errado em campo.

Uso:  python test_nebell_web.py
"""

import io
import json
import unittest
from unittest import mock

import nebell_web as W


class FalsaResposta:
    """Resposta do urlopen, com corpo e cabecalhos."""

    def __init__(self, corpo, charset="utf-8"):
        if isinstance(corpo, (dict, list)):
            corpo = json.dumps(corpo)

        self._dados = corpo.encode(charset) if isinstance(corpo, str) else corpo
        self._charset = charset

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=None):
        dados, self._dados = self._dados, b""
        return dados if n is None else dados[:n]

    @property
    def headers(self):
        charset = self._charset

        class H:
            @staticmethod
            def get_content_charset():
                return charset

            @staticmethod
            def get(nome, padrao=None):
                return padrao

        return H()


# ============================================================
# CLIMA
# ============================================================

# Formato real do Open-Meteo.
CLIMA_OK = {
    "latitude": -12.6, "longitude": -38.96, "timezone": "America/Bahia",
    "current": {
        "time": "2026-10-16T12:00",
        "interval": 900,
        "temperature_2m": 28.4,
        "relative_humidity_2m": 71,
        "apparent_temperature": 31.2,
        "weather_code": 2,
        "wind_speed_10m": 11.5,
        "precipitation": 0.0,
    },
    "daily": {
        "temperature_2m_max": [31.1],
        "temperature_2m_min": [22.3],
        "precipitation_probability_max": [35],
    },
}


class TestClima(unittest.TestCase):
    def test_frase_com_os_dados(self):
        with mock.patch.object(W, "pegar_json", return_value=CLIMA_OK):
            texto, dados = W.clima(-12.6, -38.96, "Cachoeira")

        self.assertIsNotNone(texto)
        self.assertIn("28 graus", texto)
        self.assertIn("Cachoeira", texto)
        self.assertIn("parcialmente nublado", texto)
        self.assertIn("71 por cento", texto)

    def test_sensacao_so_quando_difere(self):
        with mock.patch.object(W, "pegar_json", return_value=CLIMA_OK):
            texto, _ = W.clima(-12.6, -38.96)

        self.assertIn("sensação de 31", texto)

        igual = json.loads(json.dumps(CLIMA_OK))
        igual["current"]["apparent_temperature"] = 28.5

        with mock.patch.object(W, "pegar_json", return_value=igual):
            texto, _ = W.clima(-12.6, -38.96)

        self.assertNotIn("sensação", texto)

    def test_maxima_e_minima_do_dia(self):
        with mock.patch.object(W, "pegar_json", return_value=CLIMA_OK):
            texto, _ = W.clima(-12.6, -38.96)

        self.assertIn("entre 22 e 31 graus", texto)

    def test_chance_de_chuva_relevante(self):
        with mock.patch.object(W, "pegar_json", return_value=CLIMA_OK):
            texto, _ = W.clima(-12.6, -38.96)

        self.assertIn("35 por cento de chance de chuva", texto)

    def test_chuva_irrelevante_fica_de_fora(self):
        seco = json.loads(json.dumps(CLIMA_OK))
        seco["daily"]["precipitation_probability_max"] = [5]

        with mock.patch.object(W, "pegar_json", return_value=seco):
            texto, _ = W.clima(-12.6, -38.96)

        self.assertNotIn("chance de chuva", texto)

    def test_vento_fraco_fica_de_fora(self):
        calmo = json.loads(json.dumps(CLIMA_OK))
        calmo["current"]["wind_speed_10m"] = 4.0

        with mock.patch.object(W, "pegar_json", return_value=calmo):
            texto, _ = W.clima(-12.6, -38.96)

        self.assertNotIn("quilômetros por hora", texto)

    def test_todos_os_codigos_wmo_tem_nome(self):
        for codigo in (0, 1, 2, 3, 45, 48, 51, 61, 63, 65, 71, 80, 95, 99):
            self.assertIn(codigo, W.WMO)
            self.assertTrue(W.WMO[codigo])

    def test_codigo_desconhecido(self):
        self.assertEqual(W.descrever_codigo(999), "tempo indefinido")
        self.assertEqual(W.descrever_codigo(None), "tempo indefinido")

    def test_sem_coordenadas(self):
        texto, erro = W.clima(None, None)
        self.assertIsNone(texto)
        self.assertIn("coordenadas", erro)

    def test_api_fora_do_ar(self):
        with mock.patch.object(W, "pegar_json", side_effect=Exception("timeout")):
            texto, erro = W.clima(-12.6, -38.96)

        self.assertIsNone(texto)
        self.assertIn("timeout", erro)

    def test_resposta_sem_o_campo_current(self):
        with mock.patch.object(W, "pegar_json", return_value={"latitude": 1}):
            texto, erro = W.clima(-12.6, -38.96)

        self.assertIsNone(texto)
        self.assertIn("não devolveu", erro)


# ============================================================
# COTACAO
# ============================================================

# Formato real da AwesomeAPI.
COTACAO_OK = {
    "USDBRL": {
        "code": "USD", "codein": "BRL",
        "name": "Dólar Americano/Real Brasileiro",
        "high": "5.4521", "low": "5.4012", "varBid": "-0.0054",
        "pctChange": "-0.35", "bid": "5.4189", "ask": "5.4195",
        "timestamp": "1760620000", "create_date": "2026-10-16 12:00:00",
    }
}


class TestCotacao(unittest.TestCase):
    def test_frase_com_o_valor(self):
        with mock.patch.object(W, "pegar_json", return_value=COTACAO_OK):
            texto, dados = W.cotacao("dolar")

        self.assertIsNotNone(texto)
        self.assertIn("5,42", texto)
        self.assertIn("dólar", texto)

    def test_mostra_a_variacao(self):
        with mock.patch.object(W, "pegar_json", return_value=COTACAO_OK):
            texto, _ = W.cotacao("USD")

        self.assertIn("queda", texto)
        self.assertIn("0,35 por cento", texto)

    def test_mostra_a_faixa_do_dia(self):
        with mock.patch.object(W, "pegar_json", return_value=COTACAO_OK):
            texto, _ = W.cotacao("USD")

        self.assertIn("5,40", texto)
        self.assertIn("5,45", texto)

    def test_variacao_positiva_e_alta(self):
        alta = json.loads(json.dumps(COTACAO_OK))
        alta["USDBRL"]["pctChange"] = "1.20"

        with mock.patch.object(W, "pegar_json", return_value=alta):
            texto, _ = W.cotacao("USD")

        self.assertIn("alta", texto)

    def test_reconhece_as_moedas_pelo_nome(self):
        self.assertEqual(W.achar_moeda("qual a cotação do euro"), "EUR")
        self.assertEqual(W.achar_moeda("quanto está o bitcoin"), "BTC")
        self.assertEqual(W.achar_moeda("a libra hoje"), "GBP")
        self.assertEqual(W.achar_moeda("peso argentino"), "ARS")
        self.assertEqual(W.achar_moeda("qualquer coisa"), "USD")

    def test_nome_composto_antes_do_simples(self):
        self.assertEqual(W.achar_moeda("dolar canadense"), "CAD")

    def test_codigo_de_tres_letras_e_usado_direto(self):
        with mock.patch.object(W, "pegar_json", return_value=COTACAO_OK) as pegar:
            W.cotacao("EUR")

        self.assertIn("EUR-BRL", pegar.call_args[0][0])

    def test_cai_para_o_frankfurter(self):
        frank = {"amount": 1.0, "base": "USD", "date": "2026-10-16",
                 "rates": {"BRL": 5.43}}

        with mock.patch.object(
            W, "pegar_json", side_effect=[Exception("fora"), frank]
        ):
            texto, _ = W.cotacao("USD")

        self.assertIn("5,43", texto)
        self.assertIn("Banco Central Europeu", texto)

    def test_as_duas_fontes_falham(self):
        with mock.patch.object(W, "pegar_json", side_effect=Exception("sem rede")):
            texto, erro = W.cotacao("USD")

        self.assertIsNone(texto)
        self.assertIn("não consegui", erro)

    def test_mesma_moeda(self):
        texto, _ = W.cotacao("BRL", "BRL")
        self.assertIn("vale um", texto)

    def test_resposta_com_chave_inesperada(self):
        """A API às vezes muda a chave; pega o primeiro valor."""
        estranho = {"QUALQUER": COTACAO_OK["USDBRL"]}

        with mock.patch.object(W, "pegar_json", return_value=estranho):
            texto, _ = W.cotacao("USD")

        self.assertIn("5,42", texto)


# ============================================================
# BUSCA
# ============================================================

HTML_BUSCA = '''
<div><a class="result__a" href="/l/?uddg=https%3A%2F%2Fexemplo.com%2Fdolar">
Cotação do dólar hoje</a>
<a class="result__snippet">O dólar fechou a R$ 5,42 nesta quinta.</a></div>
<div><a class="result__a" href="/l/?uddg=https%3A%2F%2Foutro.com%2Fcambio">
Câmbio hoje</a>
<a class="result__snippet">Moedas em queda.</a></div>
'''

HTML_PAGINA = '''
<html><head><style>body{color:red}</style>
<script>var x = 1;</script></head>
<body><nav>menu que não interessa</nav>
<h1>Cotação do dólar</h1>
<p>O dólar comercial fechou cotado a R$ 5,42 nesta quinta-feira,
em queda de 0,35%. O euro ficou em R$ 5,89. O mercado reagiu aos
dados de emprego divulgados pela manhã, com o índice futuro em
leve recuperação ao longo da tarde segundo operadores ouvidos.</p>
<footer>rodapé</footer></body></html>
'''


class TestBusca(unittest.TestCase):
    def test_le_os_resultados_do_duckduckgo(self):
        with mock.patch.object(
            W.urllib.request, "urlopen", return_value=FalsaResposta(HTML_BUSCA)
        ):
            achados = W.buscar_duckduckgo("cotação do dólar")

        self.assertEqual(len(achados), 2)
        self.assertEqual(achados[0]["titulo"], "Cotação do dólar hoje")
        self.assertIn("5,42", achados[0]["texto"])
        self.assertEqual(achados[0]["url"], "https://exemplo.com/dolar")

    def test_desembrulha_o_redirecionamento(self):
        with mock.patch.object(
            W.urllib.request, "urlopen", return_value=FalsaResposta(HTML_BUSCA)
        ):
            achados = W.buscar_duckduckgo("x")

        for item in achados:
            self.assertFalse(item["url"].startswith("/l/"))
            self.assertTrue(item["url"].startswith("https://"))

    def test_traz_o_texto_da_pagina(self):
        """
        O ponto principal: sem o texto da página, o modelo pequeno não
        conseguia concluir e dizia "veja em tal site".
        """
        def falso_urlopen(pedido, timeout=None):
            url = pedido.full_url if hasattr(pedido, "full_url") else str(pedido)

            if "duckduckgo" in url:
                return FalsaResposta(HTML_BUSCA)

            return FalsaResposta(HTML_PAGINA)

        with mock.patch.dict(
            W.__dict__, {"buscar_com_ddgs": lambda *a, **k: []}
        ), mock.patch.object(
            W.urllib.request, "urlopen", side_effect=falso_urlopen
        ):
            resultado, erro = W.buscar("cotação do dólar")

        self.assertIsNone(erro)
        self.assertIn("TEXTO DA PÁGINA", resultado)
        self.assertIn("5,42", resultado)
        self.assertIn("0,35%", resultado)
        # O lixo da página não entra.
        self.assertNotIn("var x", resultado)
        self.assertNotIn("menu que não interessa", resultado)

    def test_sem_pagina_quando_pedido(self):
        with mock.patch.object(
            W, "buscar_com_ddgs",
            return_value=[{"titulo": "t", "texto": "r", "url": "https://x"}],
        ):
            resultado, erro = W.buscar("x", com_pagina=False)

        self.assertNotIn("TEXTO DA PÁGINA", resultado)

    def test_usa_o_ddgs_quando_existe(self):
        achados = [{"titulo": "Do ddgs", "texto": "corpo", "url": "https://a"}]

        with mock.patch.object(W, "buscar_com_ddgs", return_value=achados), \
             mock.patch.object(W, "buscar_duckduckgo") as reserva:
            resultado, _ = W.buscar("x", com_pagina=False)

        reserva.assert_not_called()
        self.assertIn("Do ddgs", resultado)

    def test_cai_para_o_html_quando_o_ddgs_falha(self):
        with mock.patch.object(
            W, "buscar_com_ddgs", side_effect=ImportError("sem ddgs")
        ), mock.patch.object(
            W, "buscar_duckduckgo",
            return_value=[{"titulo": "Reserva", "texto": "r", "url": "https://x"}],
        ):
            resultado, erro = W.buscar("x", com_pagina=False)

        self.assertIsNone(erro)
        self.assertIn("Reserva", resultado)

    def test_consulta_vazia(self):
        resultado, erro = W.buscar("   ")
        self.assertIsNone(resultado)
        self.assertIn("informe", erro.lower())

    def test_nenhum_resultado(self):
        with mock.patch.object(W, "buscar_com_ddgs", return_value=[]), \
             mock.patch.object(W, "buscar_duckduckgo", return_value=[]):
            resultado, erro = W.buscar("xyzinexistente")

        self.assertIsNone(resultado)
        self.assertIn("não devolveu", erro)

    def test_pagina_que_nao_abre_nao_derruba(self):
        with mock.patch.object(
            W, "buscar_com_ddgs",
            return_value=[{"titulo": "t", "texto": "r", "url": "https://x"}],
        ), mock.patch.object(W, "pegar_texto", side_effect=Exception("403")):
            resultado, erro = W.buscar("x")

        self.assertIsNone(erro)
        self.assertIn("t", resultado)

    def test_resultado_tem_tamanho_limitado(self):
        enorme = [
            {"titulo": "t" * 500, "texto": "r" * 500, "url": "https://x"}
            for _ in range(20)
        ]

        with mock.patch.object(W, "buscar_com_ddgs", return_value=enorme):
            resultado, _ = W.buscar("x", maximo=20, com_pagina=False)

        self.assertLessEqual(
            len(resultado), W.TEXTO_TOTAL + W.TEXTO_POR_PAGINA
        )


class TestLerPagina(unittest.TestCase):
    def test_tira_script_estilo_e_menu(self):
        with mock.patch.object(W, "pegar_texto", return_value=HTML_PAGINA):
            texto, erro = W.ler_pagina("https://exemplo.com")

        self.assertIsNone(erro)
        self.assertIn("5,42", texto)
        self.assertNotIn("var x", texto)
        self.assertNotIn("color:red", texto)
        self.assertNotIn("rodapé", texto)

    def test_completa_o_https(self):
        with mock.patch.object(W, "pegar_texto", return_value=HTML_PAGINA) as pegar:
            W.ler_pagina("exemplo.com")

        self.assertTrue(pegar.call_args[0][0].startswith("https://"))

    def test_pagina_que_nao_abre(self):
        with mock.patch.object(W, "pegar_texto", side_effect=Exception("404")):
            texto, erro = W.ler_pagina("https://x.com")

        self.assertIsNone(texto)
        self.assertIn("404", erro)

    def test_pagina_sem_texto(self):
        with mock.patch.object(W, "pegar_texto", return_value="<html></html>"):
            texto, erro = W.ler_pagina("https://x.com")

        self.assertIsNone(texto)
        self.assertIn("não tem texto", erro)

    def test_entidades_html(self):
        with mock.patch.object(
            W, "pegar_texto", return_value="<p>caf&eacute; &amp; p&atilde;o</p>"
        ):
            texto, _ = W.ler_pagina("https://x.com")

        self.assertIn("café & pão", texto)


class TestAjudantes(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(W.normalize("  Cotação  DO Dólar "), "cotacao do dolar")

    def test_limpar_html_mantem_paragrafos(self):
        texto = W.limpar_html("<p>um</p>\n\n\n\n<p>dois</p>")
        self.assertIn("um", texto)
        self.assertIn("dois", texto)
        self.assertNotIn("\n\n\n", texto)

    def test_limpar_html_com_comentario(self):
        self.assertNotIn(
            "oculto", W.limpar_html("<!-- oculto --><p>visível</p>")
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
