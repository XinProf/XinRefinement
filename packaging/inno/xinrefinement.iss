; XinRefinement · Inno Setup 6 安装脚本
; 语言：简体中文（默认）/ English / 日本語
; 构建：tools/build_binaries.py（先 PyInstaller，再 ISCC 本脚本）
; 产物：dist/installer/XinRefinement-<version>-setup.exe
;
; 版本号只有一个真相源：xinrefinement.__version__。这里的 AppVersion 是
; **默认值**，构建脚本用 `ISCC /DAppVersion=<ver> /DDistDir=<dir>` 覆盖；
; tests/test_version_consistency.py 校验这个默认值与 __version__ 一致。
; （历史缺陷：1.4 系列某次发版时这里还停在旧号，构建脚本按 __version__ 找产物，
;  于是「安装包未生成」——见 docs 里的发布说明。）

#define AppName "XinRefinement"
#ifndef AppVersion
#define AppVersion "1.6.3"
#endif
#define AppPublisher "PolyXRD"
#define AppExe "XinRefinement.exe"
#define AppCli "XinRefinementCLI.exe"
; 产物目录（构建脚本用 ISCC /DDistDir=... 覆盖；默认按版本约定）
#ifndef DistDir
#define DistDir "..\..\dist\XinRefinement-" + AppVersion
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
