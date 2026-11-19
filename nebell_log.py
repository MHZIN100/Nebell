"""
Observabilidade do NEBELL: um registro em arquivo (nebell.log) que
guarda, com data e hora, tudo o que o NEBELL mostra no terminal -- sem
mudar em nada o que aparece na tela.

Por que assim: o NEBELL conversa com voce pelo terminal (os prints do
dia a dia) e voce ja esta acostumado com eles. Este modulo NAO mexe
nesses prints; ele so faz uma COPIA de cada linha para o arquivo
nebell.log, com o horario na frente. Assim, quando algo der errado,
existe um historico para olhar depois -- mesmo que a janela do terminal
ja tenha sido fechada, e mesmo sem ninguem na frente do PC.

O arquivo e ROTATIVO: ao passar de ~2 MB, vira nebell.log.1, depois .2,
ate 3 copias antigas. Nunca cresce sem limite e nao enche o disco.

Regra de ouro: nada aqui pode derrubar o NEBELL. Se o disco estiver
cheio, se a pasta for somente-leitura ou se a linha tiver um caractere
estranho, a copia e descartada em silencio e o terminal continua
funcionando igualzinho.
"""

import logging
import logging.handlers
import sys
from pathlib import Path


# O log fica ao lado do nebell.py (a pasta do projeto).
ARQUIVO_LOG = Path(__file__).resolve().parent / "nebell.log"

TAMANHO_MAX = 2 * 1024 * 1024    # 2 MB por arquivo
COPIAS_ANTIGAS = 3               # nebell.log.1, .2, .3

_log = None
_ja_iniciado = False


def obter_logger():
    """Devolve o logger do NEBELL (cria e configura na primeira chamada).

    O logger escreve SO no arquivo rotativo -- de proposito, sem handler
    de tela, para nao duplicar os prints que o NEBELL ja mostra."""
    global _log

    if _log is not None:
        return _log

    log = logging.getLogger("nebell")
    log.setLevel(logging.DEBUG)
    log.propagate = False            # nao sobe para o root (evita eco)

    try:
        ARQUIVO_LOG.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            ARQUIVO_LOG,
            maxBytes=TAMANHO_MAX,
            backupCount=COPIAS_ANTIGAS,
            encoding="utf-8",
            delay=True,              # so abre o arquivo quando for escrever
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        log.addHandler(handler)
    except Exception:
        # Sem poder criar o arquivo? O NEBELL roda do mesmo jeito; o log
        # vira um "buraco negro" silencioso em vez de dar erro.
        log.addHandler(logging.NullHandler())

    _log = log
    return log


class _Tee:
    """Espelha um fluxo (stdout/stderr) para o log, sem atrapalha-lo.

    Repassa tudo para o terminal exatamente como antes e, de quebra,
    manda cada linha completa para o arquivo de log. Blindado: qualquer
    erro na copia e engolido, para nunca derrubar um print()."""

    def __init__(self, original, nivel):
        self._original = original
        self._nivel = nivel
        self._buffer = ""
        self._log = obter_logger()

    def write(self, texto):
        # 1) o de sempre: mostra no terminal.
        try:
            self._original.write(texto)
        except Exception:
            pass

        # 2) a copia para o arquivo, linha a linha (so linhas inteiras).
        try:
            self._buffer += texto
            while "\n" in self._buffer:
                linha, self._buffer = self._buffer.split("\n", 1)
                linha = linha.rstrip("\r")
                if linha.strip():
                    self._log.log(self._nivel, linha)
        except Exception:
            self._buffer = ""

    def flush(self):
        try:
            self._original.flush()
        except Exception:
            pass

    def isatty(self):
        try:
            return self._original.isatty()
        except Exception:
            return False

    def __getattr__(self, nome):
        # Delega o resto (fileno, encoding, ...) ao fluxo original.
        # Usa __dict__ para nao cair em recursao se chamado cedo demais.
        original = self.__dict__.get("_original")
        if original is None:
            raise AttributeError(nome)
        return getattr(original, nome)


def engolido(contexto=""):
    """Registra no log, com a pilha, uma excecao que acabou de ser
    capturada e engolida (um `except ...: pass`). Deve ser chamada DE
    DENTRO do except. Fica em nivel DEBUG para nao poluir o dia a dia,
    mas deixa rastro de problemas que antes sumiam sem deixar nada.

    Nunca levanta erro: se ate o log falhar, o programa segue como se o
    `pass` continuasse ali."""
    try:
        obter_logger().debug(
            "engoliu excecao em %s", contexto or "?", exc_info=True
        )
    except Exception:
        pass


def iniciar_log():
    """Liga o arquivo de log e passa a espelhar os prints para ele.

    Seguro chamar mais de uma vez (so faz efeito na primeira). Deve ser
    chamado no inicio do programa de verdade (dentro do main()), nunca na
    importacao -- assim os testes, que so importam o modulo, nao tem o
    seu stdout trocado. Devolve o logger."""
    global _ja_iniciado

    log = obter_logger()

    if _ja_iniciado:
        return log
    _ja_iniciado = True

    # Espelha stdout (prints normais) e stderr (erros e tracebacks).
    try:
        if sys.stdout is not None and not isinstance(sys.stdout, _Tee):
            sys.stdout = _Tee(sys.stdout, logging.INFO)
    except Exception:
        pass

    try:
        if sys.stderr is not None and not isinstance(sys.stderr, _Tee):
            sys.stderr = _Tee(sys.stderr, logging.ERROR)
    except Exception:
        pass

    log.info("=" * 60)
    log.info("NEBELL iniciado -- registro de sessao aberto (%s).", ARQUIVO_LOG.name)
    return log
