@echo off
chcp 65001 >nul
title NEBELL - instalar pacotes
rem  Mantido so por compatibilidade. A instalacao de verdade, que escolhe
rem  o Python certo (3.12) e instala tambem o Ollama, a voz e o Tesseract,
rem  e o Instalar.bat.
cd /d "%~dp0"
call "%~dp0Instalar.bat" %*
