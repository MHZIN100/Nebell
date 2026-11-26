@echo off
chcp 65001 >nul
title Gerar o instalador da NEBELL
cd /d "%~dp0"

echo.
echo ========================================
echo   GERANDO O INSTALADOR DA N.E.B.E.L.L.
echo ========================================
echo.

rem Procura o compilador do Inno Setup (ISCC.exe) nos lugares de sempre.
set "ISCC="
for %%P in (
  "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
  "%ProgramFiles%\Inno Setup 6\ISCC.exe"
  "%ProgramFiles(x86)%\Inno Setup 5\ISCC.exe"
  "%ProgramFiles%\Inno Setup 5\ISCC.exe"
) do if exist %%~P set "ISCC=%%~P"

if not defined ISCC (
  echo Nao encontrei o Inno Setup.
  echo.
  echo   1. Baixe e instale: https://jrsoftware.org/isdl.php
  echo   2. Rode este arquivo de novo.
  echo.
  pause
  exit /b 1
)

echo Usando: "%ISCC%"
echo.
"%ISCC%" "NEBELL.iss"
if errorlevel 1 (
  echo.
  echo Falhou ao compilar. Veja as mensagens acima.
  pause
  exit /b 1
)

echo.
echo ========================================
echo   PRONTO!
echo   O instalador esta em:  instalador\Saida\NEBELL-Setup.exe
echo ========================================
echo.
pause
