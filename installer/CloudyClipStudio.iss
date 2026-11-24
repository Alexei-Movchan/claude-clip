#define MyAppName "Cloudy Clip Studio"
#define MyAppVersion "1.0.0-dev"
#define MyAppPublisher "Cloudy Clip Studio"
#define MyAppExeName "CloudyClipStudio.exe"

[Setup]
AppId={{8C0F3B20-7E1B-4D4B-91F5-CCS100000001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Cloudy Clip Studio
DefaultGroupName={#MyAppName}
OutputDir=..\release
OutputBaseFilename=Cloudy_Clip_Studio_1.0_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin

[Files]
Source: "..\dist\CloudyClipStudio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить {#MyAppName}"; Flags: postinstall nowait skipifsilent
