"""
Testes da ponte para a placa ESP32 (nebell_esp.py): traducao dos
estados, montagem do quadro/aperto de mao WebSocket, e um teste de ponta
a ponta com um socket de verdade no localhost.
"""
import json
import socket
import threading
import time
import unittest

import nebell_esp as E


class TestTraducao(unittest.TestCase):
    def test_estados_conhecidos(self):
        self.assertEqual(E.traduzir("idle"), "espera")
        self.assertEqual(E.traduzir("listening"), "ouvindo")
        self.assertEqual(E.traduzir("thinking"), "pensando")
        self.assertEqual(E.traduzir("speaking"), "falando")
        self.assertEqual(E.traduzir("erro"), "alerta")
        self.assertEqual(E.traduzir("alerta"), "alerta")

    def test_ja_em_portugues_passa(self):
        self.assertEqual(E.traduzir("falando"), "falando")

    def test_caixa_e_espacos_nao_importam(self):
        self.assertEqual(E.traduzir("  Speaking "), "falando")

    def test_desconhecido_vira_espera(self):
        self.assertEqual(E.traduzir("qualquer_coisa"), "espera")
        self.assertEqual(E.traduzir(None), "espera")


class TestQuadroEAperto(unittest.TestCase):
    def test_quadro_texto_curto(self):
        q = E._quadro_texto("oi")
        self.assertEqual(q[0], 0x81)       # FIN + texto
        self.assertEqual(q[1], 2)          # tamanho, sem mascara
        self.assertEqual(q[2:], b"oi")

    def test_aperto_de_mao_do_exemplo_da_rfc(self):
        pedido = (
            "GET / HTTP/1.1\r\n"
            "Upgrade: websocket\r\n"
            "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\r\n"
        )
        resp = E._aperto_de_mao(pedido).decode("ascii")
        self.assertIn("101 Switching Protocols", resp)
        self.assertIn("Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=", resp)

    def test_sem_chave_nao_aperta(self):
        self.assertIsNone(E._aperto_de_mao("GET / HTTP/1.1\r\n\r\n"))


class _Leitor:
    """Le quadros de texto do WebSocket, com buffer (os bytes podem vir
    em pedacos ou grudados na resposta do aperto de mao)."""

    def __init__(self, sock, resto=b""):
        self.s = sock
        self.buf = resto
        self.s.settimeout(3)

    def _garantir(self, n):
        while len(self.buf) < n:
            pedaco = self.s.recv(256)
            if not pedaco:
                raise ConnectionError("fechou")
            self.buf += pedaco

    def estado(self):
        self._garantir(2)
        tam = self.buf[1] & 0x7F
        self._garantir(2 + tam)
        corpo = self.buf[2:2 + tam]
        self.buf = self.buf[2 + tam:]
        return json.loads(corpo.decode("utf-8"))["estado"]

    def fechar(self):
        try:
            self.s.close()
        except Exception:
            pass


class TestEnviadorPontaAPonta(unittest.TestCase):
    """Sobe o servidor numa porta livre, conecta como a placa faria e
    confere que o estado chega (na conexao e a cada mudanca)."""

    def setUp(self):
        self.env = E.EnviadorESP(porta=0, host="127.0.0.1", batimento=60)
        self.assertTrue(self.env.iniciar())
        self.porta = self.env._servidor_sock.getsockname()[1]

    def tearDown(self):
        self.env.parar()

    def _conectar(self):
        """Conecta, faz o aperto de mao e devolve um leitor de quadros.
        O leitor ja carrega os bytes que vieram grudados na resposta 101
        (senao o primeiro estado se perderia)."""
        s = socket.create_connection(("127.0.0.1", self.porta), timeout=3)
        s.sendall(
            b"GET / HTTP/1.1\r\n"
            b"Upgrade: websocket\r\n"
            b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\r\n"
        )
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += s.recv(256)
        self.assertIn(b"101", buf)
        resto = buf.split(b"\r\n\r\n", 1)[1]
        return _Leitor(s, resto)

    def test_recebe_estado_na_conexao(self):
        self.env.enviar_estado("thinking")    # vira "pensando"
        time.sleep(0.05)
        leitor = self._conectar()
        self.assertEqual(leitor.estado(), "pensando")
        leitor.fechar()

    def test_recebe_mudancas(self):
        leitor = self._conectar()
        leitor.estado()                       # estado inicial (espera)
        self.env.enviar_estado("speaking")
        self.assertEqual(leitor.estado(), "falando")
        self.env.enviar_estado("idle")
        self.assertEqual(leitor.estado(), "espera")
        leitor.fechar()

    def test_enviar_sem_placa_nao_quebra(self):
        # sem ninguem conectado, enviar_estado so guarda, sem erro
        self.env.enviar_estado("listening")
        self.assertEqual(self.env._estado, "ouvindo")


if __name__ == "__main__":
    unittest.main(verbosity=2)
