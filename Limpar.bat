@echo off
chcp 65001 >nul
title NEBELL - limpar
cd /d "%~dp0"

echo.
echo  Isto lista o que sobrou das versoes antigas (os arquivos
echo  jarvis, os audios de teste de voz, scripts soltos) e tira
echo  da pasta. Ele mostra tudo e pergunta antes.
echo.
echo  Por padrao ele MOVE para uma pasta _lixo, em vez de apagar,
echo  para dar para voltar atras. Apagar de vez e uma escolha
echo  separada, que ele pergunta depois.
echo.
echo  Feche o NEBELL antes, se ele estiver aberto.
echo.
pause

call "%~dp0_Python.bat"
if errorlevel 1 (
    pause
    exit /b 1
)

%PY% "%~dp0limpar.py"

pause
