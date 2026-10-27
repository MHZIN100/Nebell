# NEBELL

Assistente de voz local para Windows, em português. Roda **inteiramente
na sua máquina**: nada do que você fala ou pede sai do computador.

Ela ouve, responde falando, enxerga a tela, mexe em arquivos e
programas, lê documentos, lembra das conversas e tem uma janela própria
com uma nuvem de partículas que muda de forma conforme o que ela está
fazendo.

---

## Instalação

Baixe este repositório e **dê dois cliques em `Instalar.bat`**.

É só isso. Ele cuida de tudo sozinho:

- instala o **Python**, se não houver nenhum na máquina;
- cria o ambiente do projeto e instala os pacotes;
- baixa e instala o **Ollama** (que normalmente é um download manual à
  parte);
- baixa o modelo **qwen3.5:4b**;
- baixa a **voz** do Piper;
- instala o **Tesseract**, para ela ler a tela (opcional).

Da primeira vez leva um tempo e baixa uns 4 GB. Pode rodar de novo
quando quiser: ele pula o que já está pronto.

No fim ele mostra um resumo do que ficou pronto e do que faltou — e
cada linha que faltou diz como resolver.

Depois: **dois cliques em `Iniciar_NEBELL.bat`**.

### Se preferir pular o OCR

```
Instalar.bat --sem-tesseract
```

### Para só conferir o que está instalado

```
.venv\Scripts\python.exe instalar.py --so-conferir
```

---

## O que ela faz

| | |
|---|---|
| **Fala e ouve** | Piper para a voz, faster-whisper para a escuta, tudo offline |
| **Pensa** | Ollama com qwen3.5:4b, local |
| **Enxerga** | lê a sua tela, lê e edita imagens (OCR com Tesseract) |
| **Mexe no PC** | abre programas, controla janelas, digita, busca e edita arquivos |
| **Documentos** | lê e cria Word, Excel, PowerPoint e PDF |
| **Internet** | pesquisa, lê páginas, clima, cotação |
| **Lembra** | memória em SQLite, com backup automático durante a conversa |
| **Agenda** | lembretes e avisos |
| **Vigia a máquina** | temperatura, memória, disco — avisa quando algo aperta |
| **Janela** | HUD com nuvem de 30.000 partículas que muda de forma conforme o trabalho |

### A janela

O núcleo da HUD é uma nuvem de partículas com física — mola,
amortecimento, campo de fluxo, cursor. **Cada forma é um estado**:
globo de malha quando ela está na internet, olho quando está lendo a
tela, ampulheta no backup, hélice na memória, e assim por diante.
Bater o olho e saber o que ela está fazendo, sem ler nada.

A cor sai da profundidade e da energia de cada partícula — azul ao
fundo, vermelho na frente, acendendo quando elas viajam. E o quanto a
nuvem "ferve" vem da carga real de CPU e GPU: quando a máquina aperta,
você vê.

Tudo em canvas 2D, sem WebGL e sem biblioteca nenhuma.

---

## Os outros atalhos

| Arquivo | Para quê |
|---|---|
| `Instalar.bat` | instalação completa, do zero |
| `Iniciar_NEBELL.bat` | abrir |
| `Testar_NEBELL.bat` | rodar as oito suítes de teste |
| `Empacotar.bat` | gerar um zip para levar para outro PC |
| `Limpar.bat` | tirar da pasta o que não serve mais |
| `Baixar_Voz.bat` | baixar ou trocar a voz |
| `Liberar_Maquina.bat` | soltar a placa de vídeo sem abrir a NEBELL |
| `Restaurar_Memoria.bat` | voltar a memória a partir do backup |
| `Instalar_Pacotes.bat` | refazer só o ambiente Python |

---

## O que precisa da máquina

- **Windows 10 ou 11**
- **8 GB de RAM**
- Placa de vídeo com **6 GB** roda confortável. Sem placa também
  funciona, mais devagar.
- Uns **6 GB de disco** com tudo instalado
- Internet **só na instalação**. Depois roda offline.

A NEBELL solta a placa de vídeo e fecha o Ollama quando você a encerra,
para não pesar em jogo.

---

## O que não vem no repositório

| | Por quê |
|---|---|
| `.venv` | guarda o caminho do Python que o criou; não roda em outra máquina. O `Instalar.bat` cria um novo. |
| `voices/` | 63 MB por voz. O instalador baixa. |
| `whisper_models/` | meio giga. Baixa sozinho na primeira fala. |
| `memoria.db` | **são as suas conversas.** Fica só na sua máquina. |
| `microfone.json` | é o número do microfone *daquela* máquina. |

Se quiser levar a memória de uma máquina para outra, use o
`Empacotar.bat` — ele inclui o `memoria.db` no zip.

---

## Testes

```
Testar_NEBELL.bat
```

Oito suítes, mais de 1.390 testes. Cobrem desde o reconhecimento de
fala e a memória até o instalador e a consistência entre o Python e a
janela — por exemplo, toda ferramenta da NEBELL precisa ter uma forma
correspondente na HUD, e o teste falha dizendo o nome se faltar.

---

## Licença

Uso pessoal. O Ollama, o Piper, o faster-whisper, o Tesseract e os
modelos têm cada um a sua própria licença.
