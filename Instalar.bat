@echo off
rem ============================================================
rem  NEBELL - INSTALACAO COMPLETA, DO ZERO
rem
rem  Este e o unico arquivo que precisa ser clicado numa maquina
rem  nova. Ele resolve ate o Python: se nao houver nenhum, baixa e
rem  instala sozinho, porque sem Python nem o instalador de verdade
rem  (instalar.py) consegue rodar. Dai em diante quem trabalha e ele.
rem ============================================================

chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title NEBELL - instalacao

echo.
echo ================================================================
echo  NEBELL - instalacao completa
echo ================================================================
echo.
echo  Vou deixar tudo pronto nesta maquina:
echo.
echo    - Python, se nao houver
echo    - o ambiente do projeto e os pacotes
echo    - o Ollama, que e o motor que pensa
echo    - o modelo qwen3.5:4b (uns 2,5 GB)
echo    - a voz do Piper
echo    - o Tesseract, para ela ler a sua tela (opcional)
echo.
echo  Da primeira vez isso leva bastante tempo e baixa uns 4 GB.
echo  Pode rodar de novo quando quiser: ele pula o que ja esta feito.
echo.
pause

rem ---------------------------------------------------------------
rem  1. Achar um Python que REALMENTE execute
rem
rem  Nao basta "python" responder: no Windows esse nome costuma cair
rem  no atalho da Microsoft Store, que nao e um Python, so imprime
rem  "Python was not found" e devolve sucesso. Por isso cada
rem  candidato e testado de verdade.
rem ---------------------------------------------------------------

set "PY="

call :testar "%~dp0.venv\Scripts\python.exe"
if defined PY goto achou

py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PY=py -3"
    goto achou
)

python -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PY=python"
    goto achou
)

for %%D in (
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "C:\Python313\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "C:\Program Files\Python313\python.exe"
    "C:\Program Files\Python312\python.exe"
    "C:\Program Files\Python311\python.exe"
) do (
    call :testar %%D
    if defined PY goto achou
)

rem ---------------------------------------------------------------
rem  2. Nao ha Python. Baixar e instalar sozinho.
rem ---------------------------------------------------------------

echo.
echo ----------------------------------------------------------------
echo  Nao achei Python nesta maquina. Vou baixar e instalar.
echo ----------------------------------------------------------------
echo.

set "PYVER=3.12.8"
set "PYURL=https://www.python.org/ftp/python/%PYVER%/python-%PYVER%-amd64.exe"
set "PYEXE=%TEMP%\python-%PYVER%-amd64.exe"

echo  Baixando o Python %PYVER% ...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ProgressPreference='SilentlyContinue';" ^
  "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12;" ^
  "try { Invoke-WebRequest -Uri '%PYURL%' -OutFile '%PYEXE%' -UseBasicParsing; exit 0 }" ^
  "catch { Write-Host $_.Exception.Message; exit 1 }"

if errorlevel 1 goto sem_python
if not exist "%PYEXE%" goto sem_python

echo  Instalando (so para voce, sem pedir administrador) ...
"%PYEXE%" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_test=0
del /q "%PYEXE%" >nul 2>&1

rem O PATH desta janela nao enxerga o que acabou de ser instalado,
rem entao procura direto onde o instalador poe.
for %%D in (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
) do (
    call :testar %%D
    if defined PY goto achou
)

py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PY=py -3"
    goto achou
)

:sem_python
echo.
echo ================================================================
echo  NAO CONSEGUI INSTALAR O PYTHON SOZINHO.
echo.
echo  Instale a mao em  https://www.python.org/downloads/
echo  e marque "Add python.exe to PATH" na PRIMEIRA tela.
echo  Depois rode este arquivo de novo.
echo ================================================================
echo.
pause
exit /b 1

:achou
echo.
echo  Python: %PY%
echo.

rem ---------------------------------------------------------------
rem  3. O instalador de verdade
rem ---------------------------------------------------------------

if not exist "%~dp0instalar.py" (
    echo  Nao achei o instalar.py aqui do lado. A pasta veio incompleta.
    echo.
    pause
    exit /b 1
)

%PY% "%~dp0instalar.py" %*

echo.
pause
exit /b 0

rem ---------------------------------------------------------------
:testar
rem  Aceita o caminho so se ele executar de verdade.
if not exist %1 exit /b 0
%1 -c "import sys" >nul 2>&1
if errorlevel 1 exit /b 0
set "PY=%~1"
exit /b 0
