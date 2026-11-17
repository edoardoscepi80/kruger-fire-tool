; Inno Setup 6 Script for Kruger National Park - Fire & Rainfall Management DSS
; Author: PROGES / Edoardo Scepi
; Target: Windows 64-bit (Windows 10 / Windows 11 / Windows Server)

#define MyAppName "Kruger National Park - Fire & Rainfall Management DSS"
#define MyAppShortName "Kruger Fire DSS"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "PROGES / South African National Parks"
#define MyAppURL "https://github.com/edoardoscepi80/kruger-fire-tool"
#define MyAppExeName "launch.vbs"

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
OutputDir=..\dist
OutputBaseFilename=Setup_Kruger_Fire_Tool_v{#MyAppVersion}
SetupIconFile=..\resources\logo_proges.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequiredOverridesAllowed=commandline dialog
UninstallDisplayIcon={app}\resources\logo_proges.ico
DisableProgramGroupPage=auto

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Copy all application files recursively
Source: "..\\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: ".git\*,.gitignore,installer\*,dist\*,*.pyc,__pycache__\*,settings.json,.vscode\*"
; Copy default settings if not already customized by user
Source: "..\settings.json"; DestDir: "{app}"; Flags: onlyifdoesntexist ignoreversion

[Icons]
; Desktop Shortcut (Silent via wscript)
Name: "{autodesktop}\{#MyAppShortName}"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\{#MyAppExeName}"""; IconFilename: "{app}\resources\logo_proges.ico"; Tasks: desktopicon

; Start Menu Shortcuts
Name: "{group}\{#MyAppName}"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\{#MyAppExeName}"""; IconFilename: "{app}\resources\logo_proges.ico"
Name: "{group}\{#MyAppShortName} (Console Mode Debug)"; Filename: "{app}\run_app.bat"; IconFilename: "{app}\resources\logo_proges.ico"
Name: "{group}\{cm:ProgramOnTheWeb,{#MyAppName}}"; Filename: "{#MyAppURL}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"

[Run]
Filename: "{sys}\wscript.exe"; Parameters: """{app}\{#MyAppExeName}"""; Description: "{cm:LaunchProgram,{#MyAppShortName}}"; Flags: postinstall shellexec skipifsilent nowait

[Code]
// Helper function to check if QGIS is installed in standard locations
function CheckForQGIS(): Boolean;
var
  FindRec: TFindRec;
begin
  Result := DirExists('C:\Program Files\QGIS 3.44.12') or
            DirExists('C:\Program Files\QGIS 3.34.14') or
            DirExists('C:\Program Files\QGIS 3.28.15') or
            DirExists('C:\OSGeo4W') or
            DirExists('C:\OSGeo4W64');
  
  if not Result then
  begin
    if FindFirst('C:\Program Files\QGIS 3*', FindRec) then
    begin
      Result := True;
      FindClose(FindRec);
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    if not CheckForQGIS() then
    begin
      MsgBox('Note: QGIS 3.x LTR Python runtime was not detected in standard directories.' + #13#10#13#10 +
             'Kruger Fire DSS requires QGIS 3.x (64-bit) to run its spatial analysis algorithms.' + #13#10 +
             'Please make sure QGIS 3.x is installed from https://qgis.org before launching the tool.',
             mbInformation, MB_OK);
    end;
  end;
end;
