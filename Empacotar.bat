@echo off
chcp 65001 >nul
title NEBELL - empacotar para levar
cd /d "%~dp0"

echo.
echo  Isto cria um zip do NEBELL para levar para outro computador.
echo.
echo  O ambiente .venv NAO vai no pacote, de proposito: ele guarda
echo  o caminho do Python desta maquina e nao roda em outra. No
echo  destino, o Instalar_Pacotes.bat cria um novo.
echo.

call "%~dp0_Python.bat"
if errorlevel 1 (
    pause
    exit /b 1
)

echo  [1] Enxuto     - uns 70 MB. O modelo de escuta baixa sozinho na
echo                   primeira fala no outro PC (precisa de internet
echo                   uma vez; depois roda offline).
echo  [2] Completo   - uns 500 MB. Ja vai com o modelo de escuta, para
echo                   funcionar sem internet desde a primeira fala.
echo.
echo  O zip vai para a sua AREA DE TRABALHO, e no fim eu abro a pasta
echo  com ele selecionado.
echo.

set /p ESCOLHA="  Qual? [1/2, Enter para enxuto] "

if "%ESCOLHA%"=="2" (
    %PY% "%~dp0empacotar.py" --completo
) else (
    %PY% "%~dp0empacotar.py"
)

pause
