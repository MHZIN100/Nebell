' ============================================================
'  NEBELL — abre o assistente SEM a janela preta de console.
'
'  É isto que o atalho do app (Menu Iniciar / Área de Trabalho /
'  barra de tarefas) chama. Usa o pythonw.exe do ambiente da NEBELL
'  (.venv), então nada aparece a não ser a própria interface.
'
'  O OCR (ler texto dentro de imagens) agora é decidido pelo
'  nebell_config.json ("usar_tesseract"); no modo app não há mais a
'  pergunta no arranque. Para deixar leve, use "usar_tesseract": false.
' ============================================================
Option Explicit
Dim fso, sh, pasta, py
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")

pasta = fso.GetParentFolderName(WScript.ScriptFullName)
py = pasta & "\.venv\Scripts\pythonw.exe"

' Sem o ambiente próprio, tenta o pythonw do sistema (último recurso).
If Not fso.FileExists(py) Then py = "pythonw.exe"

sh.CurrentDirectory = pasta
' 0 = janela oculta (sem console);  False = não espera terminar.
sh.Run """" & py & """ """ & pasta & "\nebell.py""", 0, False
