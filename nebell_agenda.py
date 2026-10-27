"""
Agenda e lembretes do NEBELL.

Guarda compromissos no mesmo banco da memoria e tem um vigia que avisa
na hora certa, falando em voz alta.

Entende o jeito que a gente fala a hora: "amanha as oito", "em vinte
minutos", "toda segunda as sete", "dia 25 as 14h30". Nao depende de
biblioteca nenhuma: so a padrao do Python.
"""

import re
import threading
import unicodedata
from datetime import datetime, timedelta

# Quantos segundos entre uma conferida e a seguinte. Trinta segundos
# erra no maximo meio minuto, que para um lembrete falado esta de bom
# tamanho e nao custa nada de CPU.
INTERVALO = 30.0

# Avisa de novo se ele nao foi atendido? Nao: lembrete falado duas vezes
# irrita mais que ajuda. Fica marcado como avisado.
MINUTOS_DE_ATRASO_ACEITO = 10

DIAS = {
    "segunda": 0, "segunda-feira": 0, "terca": 1, "terca-feira": 1,
    "quarta": 2, "quarta-feira": 2, "quinta": 3, "quinta-feira": 3,
    "sexta": 4, "sexta-feira": 4, "sabado": 5, "domingo": 6,
}

MESES = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5,
    "junho": 6, "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10,
    "novembro": 11, "dezembro": 12,
}

NUMEROS = {
    "uma": 1, "um": 1, "duas": 2, "dois": 2, "tres": 3, "quatro": 4,
    "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10,
    "onze": 11, "doze": 12, "meia": 30, "quinze": 15, "vinte": 20,
    "trinta": 30, "quarenta": 40, "cinquenta": 50,
}


def normalize(texto):
    texto = unicodedata.normalize("NFD", str(texto).lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", texto).strip()


def numero(palavra):
    """Transforma "oito" em 8, e "8" em 8."""
    palavra = normalize(palavra)

    if palavra.isdigit():
        return int(palavra)

    return NUMEROS.get(palavra)


# ============================================================
# ENTENDER A HORA DITA
# ============================================================

def interpretar_quando(texto, agora=None):
    """
    Descobre a data e a hora a partir do jeito que se fala.

    Devolve (datetime, recorrencia) ou (None, motivo). A recorrencia e
    None, "diario" ou "semanal:<dia>".
    """
    agora = agora or datetime.now()
    alvo = normalize(texto)

    if not alvo:
        return None, "não entendi quando"

    if re.search(r"\b(ontem|anteontem|semana passada|mes passado)\b", alvo):
        return None, "isso já passou"

    # --- "em X minutos / horas" ---
    relativo = re.search(
        r"\b(?:em|daqui a|dentro de)\s+(\w+)\s*"
        r"(minuto|minutos|min|hora|horas|h|segundo|segundos|dia|dias)\b",
        alvo,
    )

    if relativo:
        quantidade = numero(relativo.group(1))

        if quantidade is None:
            return None, "não entendi a quantidade de tempo"

        unidade = relativo.group(2)

        # "meia hora" e meia hora, nao trinta horas: "meia" vale 30 em
        # minutos ("oito e meia"), mas em horas quer dizer a metade.
        if normalize(relativo.group(1)) == "meia" and unidade.startswith(("hora", "h")):
            return agora + timedelta(minutes=30), None

        if unidade.startswith("seg"):
            return agora + timedelta(seconds=quantidade), None

        if unidade.startswith("min"):
            return agora + timedelta(minutes=quantidade), None

        if unidade.startswith("dia"):
            return agora + timedelta(days=quantidade), None

        return agora + timedelta(hours=quantidade), None

    # --- a hora do dia ---
    hora, minuto = extrair_hora(alvo)

    # --- recorrencia ---
    recorrencia = None

    if re.search(r"\b(todo dia|todos os dias|diariamente|diario)\b", alvo):
        recorrencia = "diario"

    semanal = re.search(
        r"\b(?:toda|todas as|todo)\s+("
        + "|".join(sorted(DIAS, key=len, reverse=True))
        + r")\b",
        alvo,
    )

    if semanal:
        recorrencia = f"semanal:{DIAS[semanal.group(1)]}"

    # --- o dia ---
    data = agora.date()

    # dia_dito: o pedido trouxe o dia, entao uma hora que ja passou NAO
    # deve ser empurrada para o dia seguinte. Antes isso era descoberto
    # por um regex no fim, e "todo dia as 6h30" caia na armadilha de
    # conter a palavra "dia".
    dia_dito = False
    passo_da_repeticao = timedelta(days=1)

    if re.search(r"\bdepois de amanha\b", alvo):
        # Tem de vir antes de "amanha", senao o "amanha" de dentro
        # casa primeiro e o lembrete fica um dia adiantado.
        data = data + timedelta(days=2)
        dia_dito = True
    elif re.search(r"\bamanha\b", alvo):
        data = data + timedelta(days=1)
        dia_dito = True
    elif re.search(r"\bhoje\b", alvo):
        dia_dito = True
    elif recorrencia and recorrencia.startswith("semanal:"):
        # "toda segunda": a proxima segunda, contando hoje se a hora
        # ainda nao passou (quem decide isso e o ajuste do fim).
        desejado = int(recorrencia.split(":")[1])
        data = data + timedelta(days=(desejado - agora.weekday()) % 7)
        passo_da_repeticao = timedelta(days=7)
    else:
        # "dia 25", "25 de dezembro"
        dia_mes = re.search(
            r"\b(?:dia\s+)?(\d{1,2})\s+de\s+("
            + "|".join(MESES) + r")\b",
            alvo,
        )

        if dia_mes:
            dia = int(dia_mes.group(1))
            mes = MESES[dia_mes.group(2)]
            ano = agora.year

            if (mes, dia) < (agora.month, agora.day):
                ano += 1

            try:
                data = datetime(ano, mes, dia).date()
            except ValueError:
                return None, "essa data não existe"

        else:
            so_dia = re.search(r"\bdia\s+(\d{1,2})\b", alvo)

            if so_dia:
                dia = int(so_dia.group(1))
                mes, ano = agora.month, agora.year

                if dia < agora.day:
                    mes += 1

                    if mes > 12:
                        mes, ano = 1, ano + 1

                try:
                    data = datetime(ano, mes, dia).date()
                except ValueError:
                    return None, "essa data não existe"

            else:
                # Nome de dia da semana: o proximo que vier.
                nome_dia = re.search(
                    r"\b(" + "|".join(sorted(DIAS, key=len, reverse=True))
                    + r")\b",
                    alvo,
                )

                if nome_dia and not recorrencia:
                    # Hoje conta quando a hora ainda nao passou: numa
                    # sexta de manha, "sexta as 20h" e hoje mesmo.
                    desejado = DIAS[nome_dia.group(1)]
                    data = data + timedelta(
                        days=(desejado - agora.weekday()) % 7
                    )
                    passo_da_repeticao = timedelta(days=7)

    if hora is None:
        if recorrencia:
            return None, "diga a hora do lembrete"

        # Sem hora nem dia: não dá para adivinhar.
        if data == agora.date():
            return None, "diga quando: a hora ou quanto tempo a partir de agora"

        hora, minuto = 9, 0          # um dia sem hora: de manhã

    quando = datetime.combine(data, datetime.min.time()).replace(
        hour=hora, minute=minuto
    )

    # Hora que já passou e nenhum dia dito: vai para a próxima vez que
    # essa hora acontecer: amanhã, ou na semana seguinte quando o
    # pedido foi por dia da semana.
    if quando <= agora and not dia_dito:
        quando += passo_da_repeticao

    return quando, recorrencia


def extrair_hora(alvo):
    """Acha a hora e o minuto no texto. Devolve (hora, minuto)."""
    # 14:30, 14h30, 8h, 8 h
    formato = re.search(r"\b(\d{1,2})\s*(?::|h|hs|horas?)\s*(\d{2})?\b", alvo)

    if formato:
        hora = int(formato.group(1))
        minuto = int(formato.group(2) or 0)
    else:
        # "as oito", "as oito e meia", "as oito e quinze"
        falado = re.search(
            r"\b(?:as|a|ao)\s+(\w+)(?:\s+e\s+(\w+))?\b", alvo
        )

        if not falado:
            return None, 0

        hora = numero(falado.group(1))

        if hora is None or hora > 24:
            return None, 0

        minuto = numero(falado.group(2)) if falado.group(2) else 0
        minuto = minuto if minuto is not None and minuto < 60 else 0

    # Tarde e noite: "as oito da noite" é 20h.
    if re.search(r"\b(da noite|a noite|da tarde|a tarde)\b", alvo) and hora < 12:
        hora += 12

    if re.search(r"\b(da manha|de manha)\b", alvo) and hora == 12:
        hora = 0

    if hora > 23:
        hora = hora % 24

    return hora, minuto


def falar_quando(quando, agora=None):
    """Transforma a data em algo natural de ouvir."""
    agora = agora or datetime.now()
    dias = (quando.date() - agora.date()).days
    hora = f"{quando.hour} horas"

    if quando.minute:
        hora += f" e {quando.minute} minutos"

    if dias == 0:
        return f"hoje às {hora}"

    if dias == 1:
        return f"amanhã às {hora}"

    if 2 <= dias <= 6:
        nomes = ["segunda", "terça", "quarta", "quinta", "sexta",
                 "sábado", "domingo"]
        return f"{nomes[quando.weekday()]} às {hora}"

    return f"{quando.day} de {list(MESES)[quando.month - 1]} às {hora}"


# ============================================================
# AGENDA
# ============================================================

class Agenda:
    """
    Lembretes guardados no banco, com vigia que avisa na hora.

    Usa a conexao da memoria, entao tudo fica em um arquivo so.
    """

    def __init__(self, memoria, ao_disparar=None, log=print):
        self.memoria = memoria
        self.ao_disparar = ao_disparar
        self.log = log

        self._parar = threading.Event()
        self._vigiando = False

    @property
    def disponivel(self):
        return self.memoria is not None and self.memoria.disponivel

    def criar_tabela(self):
        if not self.disponivel:
            return False

        self.memoria.executar(
            """
            CREATE TABLE IF NOT EXISTS lembretes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                texto TEXT NOT NULL,
                quando TEXT NOT NULL,
                recorrencia TEXT,
                criado_em TEXT NOT NULL,
                avisado_em TEXT,
                ativo INTEGER DEFAULT 1
            )
            """
        )
        self.memoria.executar(
            "CREATE INDEX IF NOT EXISTS idx_lembretes_quando "
            "ON lembretes(quando, ativo)"
        )
        return True

    # --------------------------------------------------------
    # Criar e cancelar
    # --------------------------------------------------------

    def criar(self, texto, quando_texto, agora=None):
        """Cria um lembrete. Devolve (deu_certo, mensagem)."""
        if not self.disponivel:
            return False, "A agenda não está disponível."

        texto = str(texto or "").strip()

        if not texto:
            return False, "Diga do que devo lembrá-lo."

        quando, recorrencia = interpretar_quando(quando_texto, agora)

        if quando is None:
            return False, (
                f"Não entendi quando: {recorrencia}. "
                "Pode dizer como 'amanhã às oito' ou 'em vinte minutos'."
            )

        agora = agora or datetime.now()

        if quando < agora - timedelta(minutes=1):
            return False, "Essa hora já passou, senhor."

        self.memoria.executar(
            "INSERT INTO lembretes (texto, quando, recorrencia, criado_em) "
            "VALUES (?, ?, ?, ?)",
            (texto, quando.isoformat(timespec="seconds"), recorrencia,
             agora.isoformat(timespec="seconds")),
        )

        quadro = falar_quando(quando, agora)

        if recorrencia == "diario":
            quadro += ", todos os dias"
        elif recorrencia and recorrencia.startswith("semanal"):
            quadro += ", toda semana"

        return True, f"Combinado: {texto}, {quadro}."

    def cancelar(self, assunto):
        """
        Cancela os lembretes que combinam com o assunto.

        Devolve (quantos, mensagem) para quem vai falar a resposta.
        """
        if not self.disponivel:
            return 0, "A agenda não está disponível."

        alvo = normalize(assunto)

        if not alvo:
            return 0, "Diga qual lembrete eu devo cancelar."

        linhas = self.memoria.consultar(
            "SELECT id, texto FROM lembretes WHERE ativo = 1"
        )
        apagados = []

        for linha in linhas:
            if alvo in normalize(linha["texto"]):
                self.memoria.executar(
                    "UPDATE lembretes SET ativo = 0 WHERE id = ?",
                    (linha["id"],),
                )
                apagados.append(linha["texto"])

        if not apagados:
            return 0, f"Não tenho nenhum lembrete sobre '{assunto}'."

        if len(apagados) == 1:
            return 1, f"Cancelei o lembrete: {apagados[0]}."

        return len(apagados), (
            f"Cancelei {len(apagados)} lembretes: " + ", ".join(apagados) + "."
        )

    def listar(self, limite=15, incluir_passados=False):
        if not self.disponivel:
            return []

        if incluir_passados:
            linhas = self.memoria.consultar(
                "SELECT * FROM lembretes ORDER BY quando DESC LIMIT ?",
                (limite,),
            )
        else:
            linhas = self.memoria.consultar(
                "SELECT * FROM lembretes WHERE ativo = 1 "
                "ORDER BY quando LIMIT ?",
                (limite,),
            )

        return [dict(linha) for linha in linhas]

    def descrever(self, limite=None):
        """Lista os lembretes de um jeito falavel."""
        lembretes = self.listar()

        if limite:
            lembretes = lembretes[:limite]

        if not lembretes:
            return "Não há nada marcado, senhor."

        agora = datetime.now()
        linhas = []

        for item in lembretes:
            try:
                quando = datetime.fromisoformat(item["quando"])
            except Exception:
                continue

            marca = ""

            if item["recorrencia"] == "diario":
                marca = ", todos os dias"
            elif item["recorrencia"]:
                marca = ", toda semana"

            linhas.append(
                f"- {item['texto']}: {falar_quando(quando, agora)}{marca}"
            )

        if not linhas:
            return "Não há nada marcado, senhor."

        return f"{len(linhas)} lembrete(s):\n" + "\n".join(linhas)

    # --------------------------------------------------------
    # Vigia
    # --------------------------------------------------------

    def vencidos(self, agora=None):
        """Os lembretes que chegaram a hora e ainda nao foram avisados."""
        if not self.disponivel:
            return []

        agora = agora or datetime.now()
        limite = agora.isoformat(timespec="seconds")
        atraso = (
            agora - timedelta(minutes=MINUTOS_DE_ATRASO_ACEITO)
        ).isoformat(timespec="seconds")

        linhas = self.memoria.consultar(
            "SELECT * FROM lembretes WHERE ativo = 1 AND avisado_em IS NULL "
            "AND quando <= ? AND quando >= ? ORDER BY quando",
            (limite, atraso),
        )

        # Lembretes muito atrasados (o computador estava desligado) são
        # encerrados sem avisar, para nao assustar ao abrir o programa.
        velhos = self.memoria.consultar(
            "SELECT id FROM lembretes WHERE ativo = 1 AND avisado_em IS NULL "
            "AND quando < ?",
            (atraso,),
        )

        for velho in velhos:
            self.marcar_avisado(velho["id"], perdido=True)

        return [dict(linha) for linha in linhas]

    def marcar_avisado(self, lembrete_id, perdido=False):
        """Marca como avisado e reagenda, se for recorrente."""
        if not self.disponivel:
            return

        linhas = self.memoria.consultar(
            "SELECT * FROM lembretes WHERE id = ?", (lembrete_id,)
        )

        if not linhas:
            return

        item = dict(linhas[0])
        agora = datetime.now()

        self.memoria.executar(
            "UPDATE lembretes SET avisado_em = ?, ativo = 0 WHERE id = ?",
            (agora.isoformat(timespec="seconds"), lembrete_id),
        )

        recorrencia = item.get("recorrencia")

        if not recorrencia or perdido:
            return

        try:
            quando = datetime.fromisoformat(item["quando"])
        except Exception:
            return

        if recorrencia == "diario":
            proximo = quando + timedelta(days=1)

            while proximo <= agora:
                proximo += timedelta(days=1)

        elif recorrencia.startswith("semanal"):
            proximo = quando + timedelta(days=7)

            while proximo <= agora:
                proximo += timedelta(days=7)

            # A recorrencia manda no dia da semana. Se a data guardada
            # tiver escorregado por qualquer motivo, o lembrete volta
            # para o dia que a pessoa pediu em vez de herdar o erro.
            try:
                desejado = int(recorrencia.split(":")[1])
                proximo += timedelta(
                    days=(desejado - proximo.weekday()) % 7
                )

                if proximo <= agora:
                    proximo += timedelta(days=7)

            except (IndexError, ValueError):
                pass

        else:
            return

        self.memoria.executar(
            "INSERT INTO lembretes (texto, quando, recorrencia, criado_em) "
            "VALUES (?, ?, ?, ?)",
            (item["texto"], proximo.isoformat(timespec="seconds"),
             recorrencia, agora.isoformat(timespec="seconds")),
        )

    def frase_do_aviso(self, item):
        """O que ele vai dizer em voz alta quando o lembrete vencer."""
        return f"Lembrete: {str(item.get('texto', '')).strip()}."

    def conferir(self, agora=None):
        """Uma passada: avisa o que venceu. Devolve quantos avisou."""
        avisados = 0

        for item in self.vencidos(agora):
            try:
                if self.ao_disparar:
                    # Quem recebe e a fala pronta, nao a linha do banco:
                    # o nebell.py so precisa falar.
                    self.ao_disparar(self.frase_do_aviso(item))

                self.marcar_avisado(item["id"])
                avisados += 1

            except Exception as exc:
                self.log(f"[Agenda] Falha ao avisar: {exc}")

        return avisados

    def vigiar(self):
        """Laco do vigia. Rode em uma thread."""
        self._vigiando = True

        while not self._parar.is_set():
            try:
                self.conferir()
            except Exception:
                pass

            self._parar.wait(INTERVALO)

        self._vigiando = False

    def iniciar(self):
        if not self.disponivel:
            return False

        self.criar_tabela()
        self._parar.clear()
        threading.Thread(target=self.vigiar, daemon=True).start()
        return True

    def parar(self):
        self._parar.set()

    def numeros(self):
        if not self.disponivel:
            return {"ativos": 0, "total": 0}

        ativos = self.memoria.consultar(
            "SELECT COUNT(*) AS n FROM lembretes WHERE ativo = 1"
        )
        total = self.memoria.consultar("SELECT COUNT(*) AS n FROM lembretes")

        return {
            "ativos": ativos[0]["n"] if ativos else 0,
            "total": total[0]["n"] if total else 0,
        }
