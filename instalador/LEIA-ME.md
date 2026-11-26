# NEBELL como app do Windows — instalador, ícone e bandeja

Este pacote transforma a NEBELL em um **app de verdade**: abre sem a
janela preta de console, tem ícone próprio, fica na **bandeja** (ao lado
do relógio) e pode ser **fixado na barra de tarefas** e **abrir com o
Windows**.

O que foi preparado (já está no projeto):

- **`nebell.ico`** — o ícone da NEBELL (o giroscópio violeta), em todos
  os tamanhos.
- **`NEBELL.vbs`** — abre a NEBELL **sem console** (usa o `pythonw` do
  `.venv`). É o que os atalhos chamam.
- **`nebell_app.py`** — identidade de app no Windows (para a barra
  agrupar sob o ícone da NEBELL) e o **ícone na bandeja** com menu
  rápido (Mostrar · Falar agora · Nova conversa · Sair). É opcional e à
  prova de falha: sem a biblioteca `pystray`, a NEBELL abre igual, só
  sem o ícone da bandeja.
- **`instalador\NEBELL.iss`** + **`build_instalador.bat`** — geram o
  instalador bonito (`NEBELL-Setup.exe`).

## Passo a passo (na sua máquina Windows)

### 1. Ícone na bandeja
Já funciona assim que a `pystray` estiver instalada. O `Instalar.bat`
agora a instala (ela é opcional; se falhar, não tem problema). Para
instalar só ela, na pasta da NEBELL:

```
.venv\Scripts\python.exe -m pip install pystray
```

### 2. Abrir sem console
Dê dois cliques em **`NEBELL.vbs`** (na pasta da NEBELL). A interface
abre direto, sem a janela preta.

> O OCR (ler texto dentro de imagens) agora é decidido pelo
> `nebell_config.json` (`"usar_tesseract"`), não mais por uma pergunta no
> arranque. Para deixar o app leve, use `"usar_tesseract": false`.

### 3. Gerar o instalador bonito
1. Instale o **Inno Setup**: https://jrsoftware.org/isdl.php
2. Dê dois cliques em **`instalador\build_instalador.bat`**.
3. Sai **`instalador\Saida\NEBELL-Setup.exe`** — é esse arquivo que você
   (ou outra pessoa) roda para instalar a NEBELL com atalhos e ícone.

O instalador copia a NEBELL para a sua pasta de usuário, monta o
ambiente (chama o `Instalar.bat`), e cria os atalhos de Menu Iniciar,
Área de Trabalho e (se marcar) "abrir com o Windows".

### 4. Fixar na barra de tarefas
Abra a NEBELL pelo atalho, **clique com o botão direito** no ícone dela
na barra e escolha **"Fixar na barra de tarefas"**. Como a NEBELL agora
tem identidade de app própria, o ícone fixado fica certo.

## O que eu NÃO consegui fazer daqui (e por quê)
Eu preparei tudo isto num ambiente Linux na nuvem. **Compilar o
`.exe` do instalador e testar o ícone/bandeja tem de ser no Windows** —
é onde o Inno Setup, o `pythonw` e a bandeja realmente rodam. Se algo não
sair perfeito de primeira (ex.: a bandeja ou o "fixar"), me diz o que
aconteceu que a gente ajusta.

## Desfazer
O que mudou é **aditivo**: o `Instalar.bat` e o `Iniciar_NEBELL.bat` de
sempre continuam funcionando exatamente como antes. Se não quiser o
modo app, é só continuar usando o `Iniciar_NEBELL.bat`.
