#define MyAppName "Bill Eduthu Agent"
#define MyAppExeName "BillEduthuAgent.exe"
#define MyAppVersion "3.1.0"

[Setup]
AppId={{A73E8C81-8426-4F40-A3E8-B21E60B167B5}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\Bill Eduthu Agent
DefaultGroupName=Bill Eduthu Agent
OutputDir=.
OutputBaseFilename=BillEduthuAgentSetup
Compression=lzma
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayIcon={app}\{#MyAppExeName}

[Files]
Source: "..\dist\BillEduthuAgent\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Dirs]
Name: "{commonappdata}\BillEduthuAgent"
Name: "{commonappdata}\BillEduthuAgent\incoming"
Name: "{commonappdata}\BillEduthuAgent\queue"
Name: "{commonappdata}\BillEduthuAgent\logs"

[Icons]
Name: "{group}\Bill Eduthu Agent"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Bill Eduthu Agent"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "startup"; Description: "Start Bill Eduthu Agent when Windows starts"; GroupDescription: "Startup:"; Flags: checkedonce

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "BillEduthuAgent"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: startup; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch Bill Eduthu Agent"; Flags: nowait postinstall skipifsilent
