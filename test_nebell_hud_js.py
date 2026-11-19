"""
Roda o verificador de injecao da HUD (verificar_hud_markdown.cjs) dentro
da suite. Precisa de node + playwright; onde nao houver, o teste e pulado
em vez de falhar -- o verificador roda no ambiente de desenvolvimento e
pula na maquina do usuario, que normalmente nao tem o playwright.
"""
import shutil
import subprocess
import unittest
from pathlib import Path

AQUI = Path(__file__).resolve().parent
VERIFICADOR = AQUI / "verificar_hud_markdown.cjs"


def _node_com_playwright():
    node = shutil.which("node")
    if not node:
        return None
    try:
        r = subprocess.run(
            [node, "-e", "require.resolve('playwright')"],
            capture_output=True, timeout=30,
        )
        return node if r.returncode == 0 else None
    except Exception:
        return None


NODE = _node_com_playwright()


@unittest.skipUnless(NODE, "node + playwright não disponíveis aqui")
class TestInjecaoMarkdownHud(unittest.TestCase):
    """Payloads de XSS têm de sair como texto; o markdown, como os
    elementos certos. O verificador abre a página real num Chromium."""

    def test_injecao_segura_e_markdown_correto(self):
        r = subprocess.run(
            [NODE, str(VERIFICADOR)],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(r.returncode, 0, (r.stdout or "") + (r.stderr or ""))
        self.assertIn("PASSOU", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
