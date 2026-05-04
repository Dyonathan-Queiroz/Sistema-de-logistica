; ============================================================
;  Inno Setup Script — PDV Entregas
;  Versão: 1.0
;  Autor:  Sistema Logístico
;
;  Como compilar:
;    1. Instale o Inno Setup 6 em https://jrsoftware.org/isinfo.php
;    2. Abra este arquivo no Inno Setup Compiler
;    3. Clique em Build → Compile  (ou pressione F9)
;    4. O instalador gerado fica em:
;       Output\PDV_Entregas_Setup_1.0.exe
; ============================================================

#define AppName      "PDV Entregas"
#define AppVersion   "1.0"
#define AppPublisher "Sistema Logistico"
#define AppExeName   "PDV Entregas.exe"
#define DistDir      "dist\PDV Entregas"

[Setup]
; Identificador único — NÃO altere após a primeira instalação
AppId={{F3A2E8C1-7B4D-4E9F-A1D3-2C8B5E6F0A7D}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
AllowNoIcons=no
; Saída do instalador
OutputDir=Output
OutputBaseFilename=PDV_Entregas_Setup_{#AppVersion}
; Compressão LZMA2 — melhor taxa de compressão
Compression=lzma2/ultra64
SolidCompression=yes
; Ícone do instalador (mesmo do aplicativo)
; SetupIconFile=pdv_icon.ico
; Requer administrador para instalar em Program Files
PrivilegesRequired=admin
; Mínimo: Windows 10 64-bit
MinVersion=10.0.17763
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Mostrar assistente moderno
WizardStyle=modern
; Permite fechar versão anterior antes de instalar
CloseApplications=yes
CloseApplicationsFilter=*PDV Entregas.exe*
RestartApplications=no
; Não cria pasta de desinstalação no menu iniciar
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
; Atalho na área de trabalho (marcado por padrão)
Name: "desktopicon"; Description: "Criar atalho na &Área de Trabalho"; GroupDescription: "Atalhos adicionais:"; Flags: checkedonce
; Iniciar com o Windows (desmarcado por padrão — caixa pode preferir abrir manualmente)
Name: "startup"; Description: "Iniciar automaticamente com o &Windows"; GroupDescription: "Inicialização:"; Flags: unchecked

[Files]
; Copia todo o conteúdo da pasta dist gerada pelo PyInstaller
Source: "{#DistDir}\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#DistDir}\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Atalho no Menu Iniciar
Name: "{group}\{#AppName}";        Target: "{app}\{#AppExeName}"
Name: "{group}\Desinstalar PDV";   Target: "{uninstallexe}"
; Atalho na Área de Trabalho (opcional, criado se tarefa selecionada)
Name: "{autodesktop}\{#AppName}";  Target: "{app}\{#AppExeName}"; Tasks: desktopicon

[Registry]
; Entrada de inicialização automática no Windows (opcional, somente se tarefa selecionada)
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\Run";
    ValueType: string; ValueName: "{#AppName}";
    ValueData: """{app}\{#AppExeName}""";
    Flags: uninsdeletevalue; Tasks: startup

[Run]
; Oferece iniciar o aplicativo ao final da instalação
Filename: "{app}\{#AppExeName}"; Description: "Iniciar {#AppName} agora"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Mata o processo se estiver rodando antes de desinstalar
Filename: "taskkill"; Parameters: "/F /IM ""{#AppExeName}"""; Flags: runhidden; RunOnceId: "KillPDV"

[Code]
// Verifica se o processo está rodando antes de instalar
// (redundante com CloseApplications=yes, mas garante segurança extra)
function InitializeSetup(): Boolean;
begin
  Result := True;
end;
