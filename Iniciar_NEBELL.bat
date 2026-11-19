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

rem Escolha do OCR (Tesseract): ler texto DENTRO de imagens. Fica
rem desligado por padrao (mais leve); escolha [2] quando for usar.
echo Leitura de texto em imagens (OCR / Tesseract)?
echo    [1] SEM OCR  (mais leve) -- padrao
echo    [2] COM OCR
choice /c 12 /n /t 6 /d 1 /m "Escolha (1 ou 2): "
if errorlevel 2 (
    set "NB_ARGS=--com-tesseract"
    echo    -^> iniciando COM OCR.
) else (
    set "NB_ARGS=--sem-tesseract"
    echo    -^> iniciando SEM OCR.
)
echo.

%PY% "%~dp0nebell.py" %NB_ARGS%

echo.
pause
