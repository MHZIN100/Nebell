@echo off
chcp 65001 >nul
title NEBELL - restaurar a memoria
cd /d "%~dp0"

echo.
echo  Este programa devolve a memoria do NEBELL a partir do backup.
echo  O NEBELL tem de estar FECHADO.
echo.

call "%~dp0_Python.bat"
if errorlevel 1 (
    pause
    exit /b 1
)

%PY% "%~dp0restaurar_memoria.py"

pause
