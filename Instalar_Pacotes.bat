@echo off
chcp 65001 >nul
title NEBELL - instalar
cd /d "%~dp0"

echo ============================================================
echo  NEBELL - preparando esta maquina
echo ============================================================
echo.

rem --- 1. o ambiente proprio do projeto -----------------------
rem Um .venv que veio de outro PC nao funciona: ele guarda o
rem caminho do Python de origem. Nesse caso o antigo e posto de
rem lado e um novo e criado aqui.
set "VENV=%~dp0.venv"
set "VPY=%VENV%\Scripts\python.exe"

if exist "%VPY%" (
    "%VPY%" -c "import sys" >nul 2>&1

    if errorlevel 1 (
        echo  O ambiente .venv veio de outra maquina e nao roda aqui.
        echo  Vou guarda-lo como .venv_antigo e criar um novo.
        echo.

        if exist "%~dp0.venv_antigo" rmdir /s /q "%~dp0.venv_antigo"
        move /y "%VENV%" "%~dp0.venv_antigo" >nul
    )
)

if not exist "%VPY%" (
    echo  Criando o ambiente do projeto em .venv ...
    echo.

    py -3 -m venv "%VENV%" 2>nul

    if not exist "%VPY%" python -m venv "%VENV%" 2>nul

    if not exist "%VPY%" (
        echo.
        echo  NAO CONSEGUI CRIAR O AMBIENTE.
        echo  Instale o Python em https://www.python.org/downloads/
        echo  marcando "Add python.exe to PATH", e rode isto de novo.
        echo.
        pause
        exit /b 1
    )

    echo  Ambiente criado.
    echo.
)

call "%~dp0_Python.bat"
if errorlevel 1 (
    pause
    exit /b 1
)

echo Python: %PY%
echo.
echo Isso pode levar alguns minutos na primeira vez.
echo.

%PY% -m pip install --upgrade pip
if errorlevel 1 goto falhou

echo.
echo [1/6] Voz e conversa
%PY% -m pip install piper-tts requests
if errorlevel 1 goto falhou

echo.
echo [2/6] Escuta (reconhecimento de voz)
%PY% -m pip install faster-whisper SpeechRecognition pyaudio
if errorlevel 1 goto falhou

echo.
echo [3/6] Bibliotecas da placa de video (deixa a escuta na GPU)
%PY% -m pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
if errorlevel 1 goto falhou

echo.
echo [4/6] Interface, internet e monitoramento
%PY% -m pip install pywebview ddgs psutil
if errorlevel 1 goto falhou

echo.
echo [5/6] Visao: ler a tela, ler e editar imagens
%PY% -m pip install pillow pytesseract
if errorlevel 1 goto falhou

echo.
echo [6/6] Documentos: ler e criar PDF, Word, Excel e PowerPoint
%PY% -m pip install pypdf python-docx openpyxl python-pptx reportlab
if errorlevel 1 goto falhou

echo.
echo ============================================================
echo  Conferindo o que o NEBELL enxerga nesta maquina:
echo ============================================================
echo.
%PY% "%~dp0conferir_pacotes.py"

echo.
echo ============================================================
echo  Duas coisas NAO vem pelo pip. Se o teste acima acusou,
echo  instale:
echo.
echo  TESSERACT (ler a tela e imagens)
echo    https://github.com/UB-Mannheim/tesseract/wiki
echo    Marque "Portuguese" na lista de idiomas adicionais.
echo.
echo  OLLAMA + o modelo (a conversa em si)
echo    https://ollama.com/download
echo    Depois de instalar, abra o Prompt e rode:
echo        ollama pull qwen3.5:4b
echo ============================================================
echo.
echo  Pronto. Abra com o Iniciar_NEBELL.bat
echo.
pause
exit /b 0

:falhou
echo.
echo ============================================================
echo  UM DOS PASSOS FALHOU. Role a tela para cima, veja qual foi
echo  e me mande a mensagem de erro.
echo ============================================================
echo.
pause
exit /b 1
