@echo off
chcp 65001 >nul
title NEBELL - testes
cd /d "%~dp0"

echo ============================================================
echo  NEBELL - rodando as oito suites de teste
echo ============================================================
echo.

call "%~dp0_Python.bat"
if errorlevel 1 (
    pause
    exit /b 1
)

echo Python: %PY%
echo.

set FALHOU=0

echo --- 1/8 principal (nebell.py)
%PY% test_nebell.py
if errorlevel 1 set FALHOU=1
echo.

echo --- 2/8 audio e interface
%PY% test_nebell_audio_hud.py
if errorlevel 1 set FALHOU=1
echo.

echo --- 3/8 memoria
%PY% test_nebell_memoria.py
if errorlevel 1 set FALHOU=1
echo.

echo --- 4/8 internet
%PY% test_nebell_web.py
if errorlevel 1 set FALHOU=1
echo.

echo --- 5/8 agenda, visao, janelas, documentos e hardware
%PY% test_nebell_extras.py
if errorlevel 1 set FALHOU=1
echo.

echo --- 6/8 backup da memoria
%PY% test_nebell_backup.py
if errorlevel 1 set FALHOU=1
echo.

echo --- 7/8 empacotar e limpar
%PY% test_nebell_pacote.py
if errorlevel 1 set FALHOU=1
echo.

echo --- 8/8 instalador
%PY% test_nebell_instalador.py
if errorlevel 1 set FALHOU=1
echo.

echo ============================================================
if "%FALHOU%"=="1" (
  echo  ALGUMA SUITE FALHOU. Role a tela para cima e me mande o
  echo  trecho que comeca com FAIL ou ERROR.
) else (
  echo  Tudo passou.
)
echo ============================================================
echo.
pause
