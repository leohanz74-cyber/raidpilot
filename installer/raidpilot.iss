; Wird von GitHub Actions gebaut: iscc /DVersion=1.0.0 installer\raidpilot.iss
#ifndef Version
  #define Version "0.0.0"
#endif

[Setup]
AppId={{7B0E2C55-3F0B-4C5E-9D6E-5C2B9A41D7E3}
AppName=RaidPilot
AppVersion={#Version}
DefaultDirName={localappdata}\Programs\RaidPilot
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=RaidPilot-{#Version}-Setup
SetupIconFile=..\raidpilot\ui\icon.ico
UninstallDisplayIcon={app}\RaidPilot.exe
Compression=lzma2
SolidCompression=yes
CloseApplications=yes

[Files]
Source: "..\dist\RaidPilot\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\RaidPilot"; Filename: "{app}\RaidPilot.exe"
Name: "{autodesktop}\RaidPilot"; Filename: "{app}\RaidPilot.exe"

[Run]
; Ohne "skipifsilent": nach einem stillen Update startet die App wieder
Filename: "{app}\RaidPilot.exe"; Description: "RaidPilot starten"; Flags: nowait postinstall
