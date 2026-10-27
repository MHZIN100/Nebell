@echo off
rem ============================================================
rem  Acha o Python desta maquina e devolve em %PY%.
rem
rem  Chamado pelos outros .bat com:   call "%~dp0_Python.bat"
rem  e usado SEM aspas:               %PY% script.py
rem  (o valor ja vem com as aspas quando e um caminho com espaco)
rem
rem  Nao use "python" direto: no Windows esse nome costuma cair
rem  no atalho da Microsoft Store, que nao e um Python, so imprime
rem  "Python was not found" e devolve sucesso, entao o .bat segue
rem  em frente achando que instalou algo.
rem
rem  E nao confie num .venv so porque a pasta existe: um ambiente
rem  copiado de OUTRO computador tem o caminho do Python original
rem  gravado dentro e nao roda. Por isso cada candidato e testado
rem  de verdade antes de ser aceito.
rem ============================================================

set "PY="

rem 1. o ambiente do proprio projeto, mas so se ele REALMENTE roda
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" -c "import sys" >nul 2>&1

    if not errorlevel 1 (
        set PY="%~dp0.venv\Scripts\python.exe"
        goto achou
    )

    echo.
    echo  [aviso] O ambiente .venv nao funciona nesta maquina.
    echo          Isso e normal quando a pasta veio de outro PC: o
    echo          .venv guarda o caminho do Python de origem.
    echo          Rode o Instalar_Pacotes.bat para refazer o ambiente.
    echo.
)

rem 2. o lancador oficial do Windows: ignora o atalho da Store
py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set PY=py -3
    goto achou
)

rem 3. o python do PATH, mas so se ele REALMENTE executar
python -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set PY=python
    goto achou
)

rem 4. os lugares onde o instalador costuma deixar
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
    if exist %%D (
        set PY=%%D
        goto achou
    )
)

echo.
echo ============================================================
echo  NAO ACHEI O PYTHON NESTA MAQUINA.
echo.
echo  Instale em  https://www.python.org/downloads/
echo  e marque "Add python.exe to PATH" na PRIMEIRA tela do
echo  instalador. Depois rode o Instalar_Pacotes.bat.
echo ============================================================
echo.
exit /b 1

:achou
exit /b 0
