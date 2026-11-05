; Instalador do Photo Organizer (Inno Setup 6). Não compile direto: scripts/build_exe.py
; gera a pasta do programa e chama o ISCC passando AppVersion, SourceDir e IconFile.
; Instala por usuário (sem pedir administrador) em %LOCALAPPDATA%\Programs.

#ifndef AppVersion
  #error Rode scripts/build_exe.py, que define AppVersion, SourceDir e IconFile.
#endif

[Setup]
AppId={{6F1E5C2A-8B7D-4E3F-9A41-2C5D7B8E9F10}
AppName=Photo Organizer
AppVersion={#AppVersion}
AppVerName=Photo Organizer {#AppVersion}
DefaultDirName={autopf}\Photo Organizer
DefaultGroupName=Photo Organizer
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=PhotoOrganizer-Setup-{#AppVersion}
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\PhotoOrganizer.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "pt"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Photo Organizer"; Filename: "{app}\PhotoOrganizer.exe"
Name: "{autodesktop}\Photo Organizer"; Filename: "{app}\PhotoOrganizer.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PhotoOrganizer.exe"; Description: "{cm:LaunchProgram,Photo Organizer}"; Flags: nowait postinstall skipifsilent

[InstallDelete]
; Atualização: remove arquivos da versão anterior que a nova não traz mais.
Type: filesandordirs; Name: "{app}\_internal"
