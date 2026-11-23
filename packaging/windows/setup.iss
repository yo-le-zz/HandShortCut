; Installateur Windows de HandShortCut (Inno Setup 6).
; Construit par packaging\windows\build.ps1 (ou la CI) : il embarque l'executable
; natif compile avec Nuitka (aucun Python ni internet requis a l'installation).
; Les donnees utilisateur vont dans %LOCALAPPDATA%\HandShortCut.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppName "HandShortCut"
#define MyAppExe "{app}\handshortcut.exe"
#define MyAppCli "{app}\handshortcut.exe"

[Setup]
AppId={{7C0B6E52-3F0D-4D8E-9A57-2B6C1E4F8A11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=yolezz
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\..\assets\icon.ico
UninstallDisplayIcon={app}\icon.ico
OutputDir=..\..\dist
OutputBaseFilename=HandShortCut-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\..\LICENSE

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "autostart"; Description: "Demarrer HandShortCut avec Windows"; GroupDescription: "Options :"
Name: "desktopicon"; Description: "Creer un raccourci sur le bureau"; GroupDescription: "Options :"; Flags: unchecked

[Files]
Source: "..\..\build\exe\handshortcut.dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\assets\icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{#MyAppExe}"; Parameters: "--open"; IconFilename: "{app}\icon.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{#MyAppExe}"; Parameters: "--open"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon
Name: "{commonstartup}\{#MyAppName}"; Filename: "{#MyAppExe}"; IconFilename: "{app}\icon.ico"; Tasks: autostart

[Run]
Filename: "{#MyAppExe}"; Parameters: "--open"; Description: "Lancer HandShortCut"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{#MyAppCli}"; Parameters: "stop"; Flags: runhidden skipifdoesntexist; RunOnceId: "StopHandShortCut"

[Code]
function StopRunningInstance(): Boolean;
var
  ResultCode: Integer;
  Cli: String;
begin
  Cli := ExpandConstant('{#MyAppCli}');
  if FileExists(Cli) then
    Exec(Cli, 'stop', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := True;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopRunningInstance();  { libere les fichiers avant une mise a jour }
  Result := '';
end;
