@echo off
chcp 65001 >nul
title Gerar o NEBELL.exe
rem Vai para a raiz da NEBELL (esta pasta é app_exe\).
cd /d "%~dp0.."

echo.
echo ========================================
echo        GERANDO O N.E.B.E.L.L..exe
echo ========================================
echo.

rem Python: o do ambiente da NEBELL, se existir; senao o do sistema.
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo Instalando o PyInstaller (se faltar)...
"%PY%" -m pip install --quiet --disable-pip-version-check pyinstaller
if errorlevel 1 (
  echo Nao consegui instalar o PyInstaller. Tem Python com pip?
  pause
  exit /b 1
)

echo Compilando o lancador...
"%PY%" -m PyInstaller --noconfirm --clean --onefile --noconsole ^
  --icon "nebell.ico" --name NEBELL "app_exe\launcher.py"
if errorlevel 1 (
  echo Falhou ao compilar. Veja as mensagens acima.
  pause
  exit /b 1
)

copy /y "dist\NEBELL.exe" "NEBELL.exe" >nul
echo.
echo ========================================
echo   PRONTO!  NEBELL.exe esta na pasta da NEBELL.
echo   De dois cliques nele para abrir; ou gere o
echo   instalador com instalador\build_instalador.bat.
echo ========================================
echo.

rem Limpa o rascunho do PyInstaller (deixa so o NEBELL.exe).
rmdir /s /q build >nul 2>&1
del /q NEBELL.spec >nul 2>&1
rmdir /s /q dist >nul 2>&1

pause
