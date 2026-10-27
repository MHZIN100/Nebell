@echo off
chcp 65001 >nul
title NEBELL - Baixar a voz
cd /d "%~dp0"

call "%~dp0_Python.bat"
if errorlevel 1 (
    pause
    exit /b 1
)

%PY% "%~dp0baixar_voz.py"

echo.
pause
