; Inno Setup 6 Script for Kruger National Park - Fire & Rainfall Management DSS
; Standalone Windows 64-bit Distribution (Independent of QGIS & Python)
; Author: PROGES / Edoardo Scepi

#define MyAppName "Kruger National Park - Fire & Rainfall Management DSS"
#define MyAppShortName "Kruger Fire DSS"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "PROGES / South African National Parks"
#define MyAppURL "https://github.com/edoardoscepi80/kruger-fire-tool"
#define MyAppExeName "KrugerFireDSS.exe"

[Setup]
AppId={{5D8B41E2-9F1B-4C67-B089-3F20A8E9A1A2}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL=https://raw.githubusercontent.com/edoardoscepi80/kruger-fire-tool/main/version.json
DefaultDirName={autopf}\Proges\Kruger Fire Tool
DefaultGroupName=Proges\{#MyAppName}
AllowNoIcons=yes
OutputDir=..\installer_output
OutputBaseFilename=Setup_Kruger_Fire_Tool_v{#MyAppVersion}
SetupIconFile=..\resources\logo_proges.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=commandline dialog
UninstallDisplayIcon={app}\resources\logo_proges.ico
DisableProgramGroupPage=auto

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Copy PyInstaller standalone build bundle
Source: "..\dist\KrugerFireDSS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Copy initial default settings if user hasn't created one
Source: "..\settings.json"; DestDir: "{app}"; Flags: onlyifdoesntexist ignoreversion

[Icons]
; Desktop Shortcut
Name: "{autodesktop}\{#MyAppShortName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\resources\logo_proges.ico"; Tasks: desktopicon

; Start Menu Shortcuts
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\resources\logo_proges.ico"
Name: "{group}\{cm:ProgramOnTheWeb,{#MyAppName}}"; Filename: "{#MyAppURL}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppShortName}}"; Flags: postinstall nowait skipifsilent
