@echo off
chcp 65001 >nul
title NEBELL - liberar a maquina
cd /d "%~dp0"

call "%~dp0_Python.bat"
if errorlevel 1 (
    pause
    exit /b 1
)

%PY% "%~dp0liberar_maquina.py"

pause
