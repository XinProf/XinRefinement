; XinRefinement v1.0.0 · Inno Setup 6 安装脚本
; 语言：简体中文（默认）/ English / 日本語
; 构建：tools/build_binaries.py（先 PyInstaller，再 ISCC 本脚本）
; 产物：dist/installer/XinRefinement-1.0.0-setup.exe

#define AppName "XinRefinement"
#define AppVersion "1.0.0"
#define AppPublisher "PolyXRD"
#define AppExe "XinRefinement.exe"
#define AppCli "XinRefinementCLI.exe"
; 产物目录（构建脚本用 ISCC /DDistDir=... 覆盖；默认按版本约定）
#ifndef DistDir
  #define DistDir "..\..\dist\XinRefinement-1.0.0"
#endif

[Setup]
AppId={{CF28301D-078D-46B1-BCEE-C8734B6DE0E6}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\..\dist\installer
OutputBaseFilename={#AppName}-{#AppVersion}-setup
SetupIconFile=..\xinrefinement.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; 未签名：本地验收用，不对外分发
MinVersion=10.0

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[CustomMessages]
chinesesimplified.LaunchApp=启动 XinRefinement
english.LaunchApp=Launch XinRefinement
japanese.LaunchApp=XinRefinement を起動
chinesesimplified.CliHint=命令行入口（批处理）：XinRefinementCLI.exe
english.CliHint=Command-line entry (batch): XinRefinementCLI.exe
japanese.CliHint=コマンドライン入口（バッチ）: XinRefinementCLI.exe

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:CliHint}"; Filename: "{app}\{#AppCli}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchApp}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
