; Inno Setup script - builds OrdersDesk-Setup-<version>.exe (per-user install, no admin rights needed)
#define AppName "Orders Desk"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{B7C1D6A4-5E0B-4F3A-9A0E-0D5E5A6B7C11}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\OrdersDesk
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
OutputDir=..\dist-installer
OutputBaseFilename=OrdersDesk-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\OrdersDesk.exe
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "..\dist\OrdersDesk\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\OrdersDesk.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\OrdersDesk.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: checkedonce

[Run]
Filename: "{app}\OrdersDesk.exe"; Description: "Start {#AppName}"; Flags: nowait postinstall skipifsilent
; Note: user data lives in Documents\OrdersDesk and is NOT removed on uninstall.
