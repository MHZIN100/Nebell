@echo off
chcp 65001 >nul
title NEBELL - Assistente Local
cd /d "%~dp0"

echo.
echo ========================================
echo        INICIANDO O N.E.B.E.L.L.
echo ========================================
echo.

call "%~dp0_Python.bat"
if errorlevel 1 (
    pause
    exit /b 1
)

rem O Ollama NAO e aberto aqui de proposito. Quem abre e o proprio
rem nebell.py, que assim fica com o processo na mao e consegue fechar
rem exatamente aquele servidor no fim, devolvendo a memoria da placa.
rem Abrir por fora fazia o NEBELL achar que o Ollama era de outra
rem pessoa e deixar o modelo preso na VRAM depois de fechado.

%PY% "%~dp0nebell.py"

echo.
pause
