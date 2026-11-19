// Teste de injecao (XSS) e de correcao do Markdown da HUD.
//
// A mensagem renderizada vem do MODELO, entao renderizar errado abriria
// XSS na janela. Este verificador abre a pagina real (hud_fonte/) num
// Chromium headless e confere que:
//   - <script>, <img onerror> e [x](javascript:) saem como TEXTO, nunca
//     executados (nenhum marca window.__xss);
//   - **negrito**, *italico*, `codigo`, listas "- " e blocos ``` saem
//     como os elementos certos, com botao copiar no bloco de codigo.
//
// Uso:  node verificar_hud_markdown.cjs
// Sai com 0 quando tudo passa, 1 quando algo falha. O test_nebell_hud_js.py
// chama este arquivo e pula quando o node/playwright nao estao por perto.
const { chromium } = require('playwright');
const { pathToFileURL } = require('url');
const { join } = require('path');

const indice = join(__dirname, 'hud_fonte', 'index.html');

function falhar(msg) { console.error('FALHOU: ' + msg); process.exitCode = 1; }

(async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1180, height: 720 } });
    await page.addInitScript('window.__xss=false;');
    const erros = [];
    page.on('pageerror', e => erros.push(e.message));
    await page.route('**', r => r.request().url().startsWith('file:') ? r.continue() : r.abort());
    await page.goto(pathToFileURL(indice).href, { waitUntil: 'load' });
    await page.waitForTimeout(300);

    async function render(txt) {
      return await page.evaluate((t) => {
        window.nebellUI.addMessage('nebell', t);
        const log = document.getElementById('log');
        const corpo = log.lastElementChild.querySelector('div:last-child');
        return {
          texto: corpo.textContent,
          script: !!log.lastElementChild.querySelector('script'),
          img: !!log.lastElementChild.querySelector('img'),
          strong: !!corpo.querySelector('strong'),
          em: !!corpo.querySelector('em'),
          code: !!corpo.querySelector('code'),
          pre: !!corpo.querySelector('pre'),
          copiar: !!corpo.querySelector('button.copiar'),
          itens: corpo.querySelectorAll('li').length,
        };
      }, txt);
    }

    // --- injecao: tudo tem de sair como texto, nada executado ---
    const script = await render('<script>window.__xss=true<\/script>');
    if (script.script) falhar('<script> virou elemento <script>');
    if (!script.texto.includes('<script>')) falhar('<script> nao apareceu como texto');

    const img = await render('<img src=x onerror="window.__xss=true">');
    if (img.img) falhar('<img> virou elemento <img>');
    if (!img.texto.includes('<img')) falhar('<img> nao apareceu como texto');

    const link = await render('[clique](javascript:window.__xss=true)');
    if (!link.texto.includes('javascript:')) falhar('link js nao apareceu como texto');

    // --- markdown: elementos certos ---
    const md = await render('olha **negrito**, *italico* e `codigo`');
    if (!(md.strong && md.em && md.code)) falhar('markdown inline incompleto');
    if (md.texto.includes('*') || md.texto.includes('`')) falhar('sobrou marcacao no texto');

    const lista = await render('- um\n- dois\n- tres');
    if (lista.itens !== 3) falhar('lista nao deu 3 itens (' + lista.itens + ')');

    const bloco = await render('```py\nprint("oi")\n```');
    if (!(bloco.pre && bloco.code && bloco.copiar)) falhar('bloco de codigo sem pre/code/botao');
    if (!bloco.texto.includes('print("oi")')) falhar('bloco perdeu o conteudo');

    await page.waitForTimeout(200);
    const disparou = await page.evaluate(() => window.__xss);
    if (disparou) falhar('XSS DISPAROU: algum payload foi executado');
    if (erros.length) falhar('erros de pagina: ' + JSON.stringify(erros));

    if (!process.exitCode) console.log('PASSOU: injecao segura e markdown correto');
  } finally {
    await browser.close();
  }
})();
