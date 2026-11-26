; ============================================================
;  N.E.B.E.L.L. — instalador (Inno Setup)
;
;  Monta um assistente de instalação bonito que:
;    - copia a NEBELL para a pasta do usuário (sem pedir administrador);
;    - monta o ambiente (.venv + dependências + modelos) chamando o
;      Instalar.bat que já existe;
;    - cria atalhos (Menu Iniciar / Área de Trabalho / Inicializar com o
;      Windows) com o ÍCONE da NEBELL e que abrem SEM console (NEBELL.vbs);
;    - instala um desinstalador.
;
;  Como gerar o .exe (na sua máquina Windows):
;    1. Instale o Inno Setup: https://jrsoftware.org/isdl.php
;    2. Dê dois cliques em instalador\build_instalador.bat
;       (ou abra este arquivo no Inno Setup e clique em "Compile").
;    3. Sai  instalador\Saida\NEBELL-Setup.exe
;
;  Observação: este instalador NÃO baixa o Python. Se faltar, ele avisa
;  e aponta para python.org — a NEBELL roda sobre o Python do sistema.
; ============================================================

#define Nome "N.E.B.E.L.L."
#define NomeCurto "NEBELL"
#define Versao "1.0.0"
#define Autor "MHZIN"
#define AppDir ".."          ; a pasta do app é a de cima (onde está o nebell.py)

[Setup]
; AppId fixo: mantém atualizações e desinstalação ligadas ao mesmo app.
AppId={{B9E1B4B2-7E6E-4E2A-9E7A-1A2B3C4D5E6F}
AppName={#Nome}
AppVersion={#Versao}
AppPublisher={#Autor}
; Instala na pasta do usuário — sem precisar de administrador.
PrivilegesRequired=lowest
DefaultDirName={localappdata}\{#NomeCurto}
DefaultGroupName={#Nome}
DisableProgramGroupPage=yes
OutputDir=Saida
OutputBaseFilename={#NomeCurto}-Setup
SetupIconFile={#AppDir}\nebell.ico
UninstallDisplayIcon={app}\nebell.ico
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "pt"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar um atalho na Área de Trabalho"; GroupDescription: "Atalhos:"
Name: "startupicon"; Description: "Abrir a NEBELL quando o Windows iniciar"; GroupDescription: "Atalhos:"; Flags: unchecked

[Files]
; Copia a NEBELL inteira, deixando de fora o que é da máquina de origem,
; o que é gerado sozinho e o que é pesado/opcional.
Source: "{#AppDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs; \
  Excludes: ".venv,.venv_antigo,__pycache__,.git,.idea,.vscode,_lixo,hud,audio_temp,backup,whisper_models,*.pyc,*.pyo,*.zip,*.db-wal,*.db-shm,microfone.json,nebell_dev.log,index.anterior.html,instalador\Saida"

[Icons]
; Todos os atalhos abrem o NEBELL.vbs (sem console) e usam o ícone da NEBELL.
Name: "{group}\{#Nome}";                 Filename: "{win}\wscript.exe"; Parameters: """{app}\NEBELL.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\nebell.ico"
Name: "{group}\Desinstalar a {#Nome}";   Filename: "{uninstallexe}"
Name: "{autodesktop}\{#Nome}";           Filename: "{win}\wscript.exe"; Parameters: """{app}\NEBELL.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\nebell.ico"; Tasks: desktopicon
Name: "{userstartup}\{#Nome}";           Filename: "{win}\wscript.exe"; Parameters: """{app}\NEBELL.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\nebell.ico"; Tasks: startupicon

[Run]
; Ao terminar, o assistente oferece (caixas marcáveis) montar o ambiente
; e abrir a NEBELL. O Instalar.bat abre VISÍVEL (ele mostra o progresso e
; pede uma tecla no fim), por isso não roda escondido: assim nada trava.
Filename: "{app}\Instalar.bat"; WorkingDir: "{app}"; \
  Description: "Montar o ambiente da NEBELL agora (baixa os modelos — pode demorar)"; \
  Flags: postinstall waituntilterminated
Filename: "{win}\wscript.exe"; Parameters: """{app}\NEBELL.vbs"""; WorkingDir: "{app}"; \
  Description: "Abrir a {#Nome} ao terminar"; Flags: postinstall nowait skipifsilent unchecked

[Code]
{ Avisa se não houver Python no sistema — a NEBELL precisa dele. }
function AchouPython(): Boolean;
var
  codigo: Integer;
begin
  { 'py -3 --version' ou 'python --version' retornam 0 quando existem. }
  Result := False;
  if Exec('cmd.exe', '/c py -3 --version', '', SW_HIDE, ewWaitUntilTerminated, codigo) and (codigo = 0) then
    Result := True
  else if Exec('cmd.exe', '/c python --version', '', SW_HIDE, ewWaitUntilTerminated, codigo) and (codigo = 0) then
    Result := True;
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if not AchouPython() then
  begin
    if MsgBox('A NEBELL roda sobre o Python, e não encontrei o Python neste computador.' + #13#10 + #13#10 +
              'Instale o Python 3 (marque "Add Python to PATH") de python.org e rode este instalador de novo.' + #13#10 + #13#10 +
              'Quer continuar mesmo assim?', mbConfirmation, MB_YESNO) = IDNO then
      Result := False;
  end;
end;
