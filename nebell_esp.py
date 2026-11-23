"""
Ponte da NEBELL para a placa ESP32 com tela (a CYD, 320x240).

A placa nao roda a NEBELL -- ela e um MONITOR: mostra, de longe, o que a
NEBELL esta fazendo no PC. Este modulo e um servidor WebSocket leve (so a
biblioteca padrao do Python) que fica no PC e, a cada mudanca de estado,
manda para a placa uma linha JSON: {"estado": "espera"}.

Quem dispara isto e o `ui_state` do nebell.py, o ponto unico por onde
todo estado passa. Entao a placa recebe os estados mesmo com a janela da
HUD fechada.

Os estados viajam traduzidos para o portugues que a placa entende:
  idle/espera        -> espera
  listening/ouvindo  -> ouvindo
  thinking/pensando  -> pensando
  speaking/falando   -> falando
  alerta/erro        -> alerta

Projeto para NUNCA atrapalhar a NEBELL: se a porta nao abre, se a placa
cai, se o envio falha -- tudo e engolido. O enviar_estado nunca bloqueia
(so guarda o estado e avisa a thread; quem fala na rede e a thread).
"""

import base64
import hashlib
import json
import socket
import threading
import time

PORTA_PADRAO = 8765
_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"   # da RFC 6455

# Como cada estado que a NEBELL emite chega traduzido para a placa.
TRADUCAO = {
    "idle": "espera",
    "espera": "espera",
    "listening": "ouvindo",
    "ouvindo": "ouvindo",
    "thinking": "pensando",
    "pensando": "pensando",
    "speaking": "falando",
    "falando": "falando",
    "alerta": "alerta",
    "erro": "alerta",
    "alert": "alerta",
}


def traduzir(estado):
    """Nome de estado que a placa entende. Desconhecido -> 'espera'."""
    return TRADUCAO.get(str(estado or "").strip().lower(), "espera")


def _aperto_de_mao(pedido):
    """Monta a resposta 101 do WebSocket a partir do pedido do cliente.

    Devolve os bytes da resposta, ou None se nao for um pedido WebSocket
    valido (sem a chave Sec-WebSocket-Key)."""
    chave = None
    for linha in pedido.split("\r\n"):
        if linha.lower().startswith("sec-websocket-key:"):
            chave = linha.split(":", 1)[1].strip()
            break

    if not chave:
        return None

    accept = base64.b64encode(
        hashlib.sha1((chave + _GUID).encode("ascii")).digest()
    ).decode("ascii")

    return (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
    ).encode("ascii")


def _quadro_texto(texto):
    """Um quadro WebSocket de texto, servidor->cliente (sem mascara).

    So para payloads curtos (< 126 bytes), que e sempre o nosso caso: o
    JSON do estado tem umas poucas dezenas de bytes."""
    dados = texto.encode("utf-8")
    return bytes([0x81, len(dados)]) + dados


class EnviadorESP:
    """
    Servidor que mantem o ultimo estado e o empurra para as placas ligadas.

    Uma thread aceita conexoes; cada placa que conecta recebe o estado
    atual na hora. Um batimento reenvia o estado de tempos em tempos, para
    uma placa que reconectou nao ficar parada no estado errado.
    """

    def __init__(self, porta=PORTA_PADRAO, host="0.0.0.0", batimento=10.0,
                 log=None):
        self.porta = porta
        self.host = host
        self.batimento = batimento
        self.log = log or (lambda *a: None)

        self._estado = "espera"
        self._lock = threading.Lock()
        self._clientes = []          # sockets das placas ligadas
        self._parar = threading.Event()
        self._servidor_sock = None
        self._vivo = False

    # ---- ciclo de vida ----
    def iniciar(self):
        """Abre a porta e sobe as threads. Devolve True se a porta abriu."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((self.host, self.porta))
            s.listen(4)
            s.settimeout(1.0)
        except Exception as exc:
            self.log(f"[ESP] Não consegui abrir a porta {self.porta}: {exc}")
            return False

        self._servidor_sock = s
        self._vivo = True
        threading.Thread(target=self._aceitar, daemon=True).start()
        threading.Thread(target=self._bater, daemon=True).start()
        self.log(f"[ESP] Ouvindo a placa na porta {self.porta}.")
        return True

    def parar(self):
        self._parar.set()
        self._vivo = False
        with self._lock:
            clientes = list(self._clientes)
            self._clientes.clear()
        for c in clientes:
            try:
                c.close()
            except Exception:
                pass
        if self._servidor_sock:
            try:
                self._servidor_sock.close()
            except Exception:
                pass

    # ---- o que o nebell.py chama ----
    def enviar_estado(self, estado):
        """
        Guarda o novo estado e o manda para as placas. NUNCA bloqueia nem
        levanta: um erro de rede aqui nao pode travar a NEBELL.
        """
        traduzido = traduzir(estado)

        with self._lock:
            if traduzido == self._estado:
                # ja esta nesse estado; ainda assim reenvia, barato, para
                # garantir (ex.: placa acabou de reconectar entre batimentos)
                pass
            self._estado = traduzido
            clientes = list(self._clientes)

        self._difundir(traduzido, clientes)

    # ---- tripas ----
    def _difundir(self, estado, clientes):
        if not clientes:
            return

        quadro = _quadro_texto(json.dumps({"estado": estado}))
        mortos = []

        for c in clientes:
            try:
                c.sendall(quadro)
            except Exception:
                mortos.append(c)

        if mortos:
            with self._lock:
                for c in mortos:
                    if c in self._clientes:
                        self._clientes.remove(c)
            for c in mortos:
                try:
                    c.close()
                except Exception:
                    pass

    def _aceitar(self):
        while not self._parar.is_set():
            try:
                sock, _ = self._servidor_sock.accept()
            except socket.timeout:
                continue
            except Exception:
                if self._parar.is_set():
                    break
                time.sleep(0.5)
                continue

            threading.Thread(
                target=self._apertar_e_registrar, args=(sock,), daemon=True
            ).start()

    def _apertar_e_registrar(self, sock):
        try:
            sock.settimeout(5.0)
            pedido = sock.recv(2048).decode("latin-1", "ignore")
            resposta = _aperto_de_mao(pedido)

            if resposta is None:
                sock.close()
                return

            sock.sendall(resposta)
            sock.settimeout(None)
        except Exception:
            try:
                sock.close()
            except Exception:
                pass
            return

        with self._lock:
            self._clientes.append(sock)
            estado = self._estado

        self.log("[ESP] Placa conectada.")

        # manda o estado atual na hora
        try:
            sock.sendall(_quadro_texto(json.dumps({"estado": estado})))
        except Exception:
            pass

    def _bater(self):
        """Reenvia o estado de tempos em tempos, para reconexoes."""
        while not self._parar.wait(self.batimento):
            with self._lock:
                estado = self._estado
                clientes = list(self._clientes)
            self._difundir(estado, clientes)
