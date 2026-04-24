; boxcutter.iss — Inno Setup script for BoxCutter
; Compile: ISCC.exe /DAppVersion=1.0.0 installer\windows\boxcutter.iss

#define MyAppName "BoxCutter"
#define MyAppPublisher "House//Minimal Records"
#define MyAppExeName "BoxCutter.exe"

[Setup]
AppName={#MyAppName}
AppVersion={#AppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\BoxCutter
DefaultGroupName={#MyAppName}
UninstallDisplayName={#MyAppName}
OutputBaseFilename=BoxCutter-Setup-{#AppVersion}
OutputDir=Output
SetupIconFile=..\..\static\boxcutter.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\..\LICENSE
; Install to user-local dir — no admin elevation required
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline
; Auto-updater exits the app before launching this installer, so no need to check
CloseApplications=no
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
Source: "..\..\dist\BoxCutter\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{userprograms}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall
