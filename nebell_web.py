"""
Internet do NEBELL: respostas concretas, nao links.

O problema que isto resolve: perguntar "qual a cotacao do dolar" devolvia
cinco titulos de noticia, e o modelo (que e pequeno) nao conseguia tirar
o numero dali. Ele acabava dizendo "veja em tal site", que nao serve.

Aqui, as perguntas mais comuns tem resposta direta, de fonte propria:

  clima      api.open-meteo.com      sem chave, dados do modelo europeu
  cotacao    economia.awesomeapi     sem chave, cotacao do dia em tempo real
  busca      DuckDuckGo              com o TEXTO da pagina, nao so o titulo

Para a busca geral, a diferenca esta em trazer o conteudo da primeira
pagina junto: com texto de verdade o modelo conclui; com titulos, nao.
"""

import json
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from html import unescape

TEMPO_LIMITE = 12
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NEBELL/1.0"

# Quanto texto de pagina mandar ao modelo. Pouco demais nao conclui,
# muito demais enche o contexto.
TEXTO_POR_PAGINA = 1400
TEXTO_TOTAL = 3000


def normalize(texto):
    texto = unicodedata.normalize("NFD", str(texto).lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", texto).strip()


def pegar_json(url, timeout=TEMPO_LIMITE):
    pedido = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    with urllib.request.urlopen(pedido, timeout=timeout) as resposta:
        return json.loads(resposta.read().decode("utf-8", "replace"))


def pegar_texto(url, timeout=TEMPO_LIMITE):
    pedido = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    with urllib.request.urlopen(pedido, timeout=timeout) as resposta:
        bruto = resposta.read(600_000)
        codificacao = resposta.headers.get_content_charset() or "utf-8"
        return bruto.decode(codificacao, "replace")


# ============================================================
# CLIMA
# ============================================================

# Codigos WMO que o Open-Meteo devolve, em portugues.
WMO = {
    0: "céu limpo",
    1: "predominantemente limpo",
    2: "parcialmente nublado",
    3: "nublado",
    45: "névoa",
    48: "névoa com geada",
    51: "garoa leve",
    53: "garoa",
    55: "garoa forte",
    56: "garoa congelante",
    57: "garoa congelante forte",
    61: "chuva fraca",
    63: "chuva",
    65: "chuva forte",
    66: "chuva congelante",
    67: "chuva congelante forte",
    71: "neve fraca",
    73: "neve",
    75: "neve forte",
    77: "grãos de neve",
    80: "pancadas de chuva fracas",
    81: "pancadas de chuva",
    82: "pancadas de chuva fortes",
    85: "pancadas de neve",
    86: "pancadas de neve fortes",
    95: "trovoada",
    96: "trovoada com granizo",
    97: "trovoada forte",
    99: "trovoada com granizo forte",
}


def descrever_codigo(codigo):
    try:
        return WMO.get(int(codigo), "tempo indefinido")
    except (TypeError, ValueError):
        return "tempo indefinido"


def clima(latitude, longitude, cidade=None, com_previsao=True):
    """
    Clima de agora, com uma frase pronta para ser falada.

    Devolve (texto, dados) ou (None, erro).
    """
    if latitude is None or longitude is None:
        return None, "sem coordenadas para consultar o clima"

    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={latitude}&longitude={longitude}"
        "&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
        "weather_code,wind_speed_10m,precipitation"
        "&timezone=auto"
    )

    if com_previsao:
        url += "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&forecast_days=1"

    try:
        dados = pegar_json(url)
    except Exception as exc:
        return None, f"não consegui consultar o clima: {exc}"

    agora = dados.get("current") or {}

    if not agora:
        return None, "o serviço de clima não devolveu os dados de agora"

    temperatura = agora.get("temperature_2m")
    sensacao = agora.get("apparent_temperature")
    umidade = agora.get("relative_humidity_2m")
    vento = agora.get("wind_speed_10m")
    ceu = descrever_codigo(agora.get("weather_code"))

    onde = f" em {cidade}" if cidade else ""
    partes = [f"Agora{onde} faz {round(temperatura)} graus, {ceu}"]

    if sensacao is not None and abs(sensacao - temperatura) >= 2:
        partes.append(f"sensação de {round(sensacao)}")

    if umidade is not None:
        partes.append(f"umidade de {round(umidade)} por cento")

    if vento is not None and vento >= 15:
        partes.append(f"vento de {round(vento)} quilômetros por hora")

    diario = dados.get("daily") or {}

    try:
        maxima = diario.get("temperature_2m_max", [None])[0]
        minima = diario.get("temperature_2m_min", [None])[0]
        chuva = diario.get("precipitation_probability_max", [None])[0]

        if maxima is not None and minima is not None:
            partes.append(
                f"hoje entre {round(minima)} e {round(maxima)} graus"
            )

        if chuva is not None and chuva >= 20:
            partes.append(f"{round(chuva)} por cento de chance de chuva")

    except (IndexError, TypeError):
        pass

    return ". ".join(partes) + ".", dados


# ============================================================
# COTACAO
# ============================================================

MOEDAS = {
    "dolar": "USD", "dólar": "USD", "usd": "USD", "dolar americano": "USD",
    "euro": "EUR", "eur": "EUR",
    "libra": "GBP", "gbp": "GBP", "libra esterlina": "GBP",
    "peso": "ARS", "peso argentino": "ARS", "ars": "ARS",
    "iene": "JPY", "yen": "JPY", "jpy": "JPY",
    "bitcoin": "BTC", "btc": "BTC",
    "ethereum": "ETH", "eth": "ETH",
    "real": "BRL", "brl": "BRL",
    "franco": "CHF", "yuan": "CNY", "dolar canadense": "CAD",
}

NOMES = {
    "USD": "dólar", "EUR": "euro", "GBP": "libra", "ARS": "peso argentino",
    "JPY": "iene", "BTC": "bitcoin", "ETH": "ethereum", "CHF": "franco",
    "CNY": "yuan", "CAD": "dólar canadense", "BRL": "real",
}


def achar_moeda(texto):
    """Descobre a moeda pedida. O padrao e o dolar."""
    alvo = normalize(texto)

    # Nomes compostos primeiro ("dolar canadense" antes de "dolar").
    for nome in sorted(MOEDAS, key=len, reverse=True):
        if normalize(nome) in alvo:
            return MOEDAS[nome]

    return "USD"


def cotacao(moeda="USD", destino="BRL"):
    """
    Cotacao de agora, com frase pronta.

    Devolve (texto, dados) ou (None, erro).
    """
    codigo = moeda if len(str(moeda)) == 3 else achar_moeda(moeda)
    codigo = str(codigo).upper()[:3]
    destino = str(destino).upper()[:3]

    if codigo == destino:
        return f"Um {NOMES.get(codigo, codigo)} vale um.", {}

    par = f"{codigo}-{destino}"
    erros = []

    # 1. AwesomeAPI: brasileira, em tempo real, sem chave.
    try:
        dados = pegar_json(f"https://economia.awesomeapi.com.br/last/{par}")
        chave = f"{codigo}{destino}"
        info = dados.get(chave) or next(iter(dados.values()), {})

        venda = float(info.get("ask") or info.get("bid"))
        variacao = info.get("pctChange")
        maxima = info.get("high")
        minima = info.get("low")

        nome = NOMES.get(codigo, codigo)
        texto = f"O {nome} está a {venda:.2f} reais".replace(".", ",", 1)

        if variacao not in (None, ""):
            try:
                numero = float(variacao)
                direcao = "alta" if numero > 0 else "queda" if numero < 0 else "estável"

                if direcao == "estável":
                    texto += ", estável hoje"
                else:
                    texto += (
                        f", em {direcao} de "
                        + f"{abs(numero):.2f}".replace(".", ",")
                        + " por cento hoje"
                    )
            except ValueError:
                pass

        if maxima and minima:
            try:
                texto += (
                    f". Hoje variou entre "
                    + f"{float(minima):.2f}".replace(".", ",")
                    + " e "
                    + f"{float(maxima):.2f}".replace(".", ",")
                )
            except ValueError:
                pass

        return texto + ".", info

    except Exception as exc:
        erros.append(f"AwesomeAPI: {exc}")

    # 2. Frankfurter: Banco Central Europeu, sem chave.
    try:
        dados = pegar_json(
            f"https://api.frankfurter.app/latest?from={codigo}&to={destino}"
        )
        valor = float(dados["rates"][destino])
        nome = NOMES.get(codigo, codigo)
        data = dados.get("date", "")

        return (
            f"O {nome} está a "
            + f"{valor:.2f}".replace(".", ",")
            + f" reais, conforme o Banco Central Europeu em {data}.",
            dados,
        )

    except Exception as exc:
        erros.append(f"Frankfurter: {exc}")

    return None, "não consegui a cotação agora. " + "; ".join(erros)


# ============================================================
# BUSCA COM CONTEUDO
# ============================================================

def limpar_html(html):
    """Tira o que nao e texto e devolve o conteudo legivel."""
    html = re.sub(
        r"(?is)<(script|style|noscript|svg|nav|footer|header|form|aside)\b.*?</\1>",
        " ", html,
    )
    html = re.sub(r"(?is)<!--.*?-->", " ", html)
    texto = unescape(re.sub(r"(?s)<[^>]+>", " ", html))
    texto = re.sub(r"[ \t\xa0]+", " ", texto)
    texto = re.sub(r"\n\s*\n\s*\n+", "\n\n", texto)
    return texto.strip()


def buscar_duckduckgo(consulta, maximo=5):
    """Resultados do DuckDuckGo sem depender de pacote externo."""
    dados = urllib.parse.urlencode({"q": consulta, "kl": "br-pt"}).encode()
    pedido = urllib.request.Request(
        "https://html.duckduckgo.com/html/",
        data=dados,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )

    with urllib.request.urlopen(pedido, timeout=TEMPO_LIMITE) as resposta:
        html = resposta.read().decode("utf-8", "replace")

    achados = []

    padrao = re.compile(
        r'result__a[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<titulo>.*?)</a>'
        r'.*?result__snippet[^>]*>(?P<texto>.*?)</a>',
        re.S,
    )

    def limpo(bruto):
        return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", bruto))).strip()

    for achado in padrao.finditer(html):
        url = unescape(achado.group("url"))
        real = re.search(r"uddg=([^&]+)", url)

        if real:
            url = urllib.parse.unquote(real.group(1))

        if not url.startswith("http"):
            continue

        achados.append({
            "titulo": limpo(achado.group("titulo")),
            "texto": limpo(achado.group("texto")),
            "url": url,
        })

        if len(achados) >= maximo:
            break

    return achados


def buscar_com_ddgs(consulta, maximo=5):
    """Usa o pacote ddgs quando instalado: resultados melhores."""
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS

    saida = []

    for item in DDGS().text(consulta, region="br-pt", max_results=maximo):
        saida.append({
            "titulo": item.get("title", ""),
            "texto": item.get("body", ""),
            "url": item.get("href", ""),
        })

    return saida


def buscar(consulta, maximo=5, com_pagina=True):
    """
    Pesquisa e devolve algo com que o modelo consiga concluir.

    Alem dos titulos e resumos, traz o TEXTO da primeira pagina. Era
    isso que faltava: com cinco titulos o modelo pequeno nao tira o
    numero da cotacao, mas com o texto da pagina ele tira.
    """
    consulta = str(consulta).strip()

    if not consulta:
        return None, "informe o que pesquisar"

    achados = []
    erros = []

    for tentativa in (buscar_com_ddgs, buscar_duckduckgo):
        try:
            achados = tentativa(consulta, maximo)

            if achados:
                break

        except Exception as exc:
            nome = getattr(tentativa, "__name__", "busca")
            erros.append(f"{nome}: {exc}")

    if not achados:
        return None, (
            "a pesquisa não devolveu resultados. " + "; ".join(erros)
            if erros else "a pesquisa não devolveu resultados."
        )

    linhas = [f"Resultados para: {consulta}", ""]

    for i, item in enumerate(achados, 1):
        linhas.append(f"{i}. {item['titulo']}")

        if item["texto"]:
            linhas.append(f"   {item['texto']}")

        linhas.append(f"   fonte: {item['url']}")

    if com_pagina:
        for item in achados[:2]:
            try:
                texto = limpar_html(pegar_texto(item["url"]))

                # 120 e o suficiente: uma cotacao ou uma temperatura
                # cabem em pouco mais de cem caracteres.
                if len(texto) < 120:
                    continue

                linhas.append("")
                linhas.append(
                    f"TEXTO DA PÁGINA ({item['titulo']}):"
                )
                linhas.append(texto[:TEXTO_POR_PAGINA])
                break

            except Exception:
                continue

    resultado = "\n".join(linhas)
    return resultado[:TEXTO_TOTAL + TEXTO_POR_PAGINA], None


def ler_pagina(url, limite=TEXTO_TOTAL):
    """O texto de uma pagina, limpo."""
    url = str(url).strip()

    if not re.match(r"https?://", url, re.IGNORECASE):
        url = "https://" + url

    try:
        texto = limpar_html(pegar_texto(url))
    except Exception as exc:
        return None, f"não consegui abrir a página: {exc}"

    if not texto:
        return None, "a página não tem texto legível"

    return texto[:limite], None
