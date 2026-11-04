# v1.0.0 本地二进制验收单（人工）

> 产物**只在本地**：`dist/` 已被 `.gitignore` 排除，未提交、未上传、未发布。
> 全部确认通过后，再由你决定分发方式。

## 1. 产物清单（双变体，参照 XinMatch）

| 变体 | 产物 | 路径 | 说明 |
|---|---|---|---|
| **正式版** release | GUI / CLI | `dist/XinRefinement-1.0.0/XinRefinement.exe`、`…CLI.exe` | windowed + console，onedir |
| | 安装包 | `dist/installer/XinRefinement-1.0.0-setup.exe` | Inno Setup，zh/en/ja；**含 PolyXRD-Reg 注册机制** |
| **内部评估版** internal | GUI / CLI | `dist/XinRefinement-internal-1.0.0/XinRefinement.exe`、`…CLI.exe` | 免注册、免安装 |
| | 便携包 | `dist/installer/XinRefinement-internal-1.0.0-portable.zip` | 解压即用；状态栏红字「内部评估版本」 |

变体以随包 `variant.txt` 固化（在 `_internal/` 下），运行时由
`xinrefinement.build_variant` 读取；**缺失标记按正式版处理**（fail-safe）。

重新构建：`python tools/build_binaries.py`（两个变体约 3.5 分钟）或
`--variant release` / `--variant internal` 单建。
构建脚本已内置可复现设置（`SOURCE_DATE_EPOCH` = git HEAD 提交时间、`PYTHONHASHSEED=0`），
同一 commit 连续构建**逐字节一致**（见 §2.1）；构建后脚本会打印每个产物 SHA-256 前 16 位。完整校验：

```bash
sha256sum dist/XinRefinement-1.0.0/XinRefinement.exe \
          dist/XinRefinement-1.0.0/XinRefinementCLI.exe \
          dist/installer/XinRefinement-1.0.0-setup.exe \
          dist/installer/XinRefinement-internal-1.0.0-portable.zip
```

### 1.2 v1.0.0 发布件哈希（最终构建实测）

| 文件 | 大小 | SHA-256 |
|---|---|---|
| `XinRefinement-1.0.0/XinRefinement.exe` | 8.4 MB | `d452f324d8ffa1b62c2728e15de97a15a7254fcb16e354dca275f24227c5eb32` |
| `XinRefinement-1.0.0/XinRefinementCLI.exe` | 8.3 MB | `009236bd21789f3de9c21adaee4143b308c33a92ef6fa0d193fefef31b9d0916` |
| `installer/XinRefinement-1.0.0-setup.exe` | 67.6 MB | `410d74d9c35c8d8fc5e77bd3a42a443b4f5d7b9c653b3e7e1798136f031be54e` |
| `installer/XinRefinement-internal-1.0.0-portable.zip` | 113.9 MB | `3c2a3842a3c48f14a822326f4f30f56f2f5f9c7444656c6c9f19f299976340c4` |

内部评估版的 `XinRefinement.exe` / `XinRefinementCLI.exe` 与上表前两行**完全同哈希**：
onedir 模式下变体由 `_internal/variant.txt` 决定，exe 本身不含变体差异。

### 1.1 两种变体的机器可读自检（不必驱动 GUI）

```bat
set XINREFINEMENT_SELFTEST_REG_OUT=%TEMP%\reg.json
dist\XinRefinement-1.0.0\XinRefinement.exe
type %TEMP%\reg.json
:: 正式版 → {"variant":"release","registration_enabled":true,"status_text":"未注册"}

dist\XinRefinement-internal-1.0.0\XinRefinement.exe
type %TEMP%\reg.json
:: 内部版 → {"variant":"internal","registration_enabled":false,"status_text":"内部评估版本"}
```

注册状态文件：`%APPDATA%\PolyXRD\Registration\XinRefinement.json`
（与 XinMatch 同一家族目录，注册码互通）。
开发方出码：`python tools/make_reg_code.py "单位部门名称"`。

## 1.5 源码模式预检（可选，先跑这一步可快速排除环境问题）

`run_dev.bat` 不打包、不冻结，直接用工作树源码运行，用于区分「代码问题」与「打包问题」：

```bat
run_dev.bat                                    :: 启动 GUI（标题应含 v1.0.0）
run_dev.bat --version                          :: 应输出 XinRefinement 1.0.0
run_dev.bat refine tests\data\virtual_b\v50_wide.xy ^
    xinrefinement\data\anatase.cif xinrefinement\data\rutile.cif ^
    --peak-height -o out.json                  :: Rwp 应为 3.409617
run_dev.bat refine <谱图> <物相.cif...> --recipe --report out_dir --esd
```

解释器按以下顺序自动选取（首个命中即用）：`%XINREFINEMENT_DEV_PYTHON%` →
`.venv\Scripts\python.exe` → `venv\Scripts\python.exe` → `D:\Project\XRD\python310\python.exe` → PATH 上的 `python`。
换解释器只需设环境变量：`set XINREFINEMENT_DEV_PYTHON=D:\path\to\python.exe`。

若源码模式通过而 exe 失败 → 问题在打包（缺 hiddenimport / 数据文件）；两者都失败 → 问题在代码或数据。

## 2. 六轮稳健性验收（建议顺序）

| 轮 | 动作 | 通过标准 |
|---|---|---|
| 1 · 哈希一致性 | 连续构建两次，比对四个产物 SHA-256 | GUI/CLI 两次**逐字节一致**（见 §2.1；安装包/zip 因内嵌时间戳允许不同）；不一致需排查非确定性来源 |
| 2 · CLI 冷启动 | 双击或 `XinRefinementCLI.exe --version` | 输出 `XinRefinement 1.0.0`，无缺 DLL 报错 |
| 3 · CLI 端到端 | `XinRefinementCLI.exe refine <谱图.xy> <物相.cif> -o out.json` | JSON 含 `r_factors`/`phases`；Rwp 与源码运行一致（v50 双相 = 3.409617） |
| 4 · GUI 双击冒烟 | 双击 `XinRefinement.exe` | 主窗口出现（标题含 1.0.0）；导入谱图+CIF → ▶精修 → 图谱与结果表刷新；切换语言（设置→语言）文案即时变化 |
| 5 · 安装/卸载 | 双击安装包 → 选简体中文 → 安装到默认目录 → 启动 → 卸载 | 安装界面为中文；开始菜单有 GUI 与 CLI 两项；卸载后目录清空 |
| 6 · 双变体差异 | 分别跑 §1.1 的两条自检；再双击两个 GUI 看状态栏右端 | 正式版：帮助菜单有「输入注册码…」、状态栏「未注册」→ 输入注册码后变「已注册：单位名」；内部版：无注册菜单、状态栏红字「内部评估版本」 |

### 2.1 第 1 轮补充：可复现构建（已内置于脚本）

PyInstaller 默认**不可复现**，实测有两处非确定性来源，均在 `tools/build_binaries.py` 中已处理：

| 来源 | 现象 | 处理 |
|---|---|---|
| PE 头 `TimeDateStamp` | 写入构建时刻，两次构建 8 MB 里 4 字节不同 | 设 `SOURCE_DATE_EPOCH`（PyInstaller 6 支持），取值 = git HEAD 提交时间 `%ct` |
| 字符串集合的哈希随机化 | PYZ 内 marshal 字节流随进程变化，压缩长度抖动（实测两次差 17 字节） | 设 `PYTHONHASHSEED=0` |

处理后在**同一 commit** 上连续两次构建，四个 exe 逐字节一致（已验证）。
安装包与便携 zip 仍会变：Inno Setup 无 `SOURCE_DATE_EPOCH` 支持，`zipfile` 会写入文件 mtime，
二者只做「功能一致」验收，不参与哈希比对。

## 3. 已知提示

- 正式版首次启动会弹「未注册，版权所有，禁止用于商业用途」提示
  （确定=继续使用 / 输入注册码=完成注册）；离屏运行或设
  `POLYXRD_REG_NO_PROMPT=1` 时不弹（自动化友好）。
- 注册码为离线 HMAC 校验（密钥随软件分发，属混淆级）；同一注册码可在同单位多机使用，无机器绑定。
- 内部评估版是**便携 zip**，不做安装包；若需要内部版安装包，可再扩 Inno 配置加一个 `--variant internal` 的 AppId。
- 未代码签名：首次运行 Windows SmartScreen 可能提示「未知发布者」，选「仍要运行」。
- 安装包 67.6 MB（含 matplotlib/Qt 运行时），属正常范围。
- GUI 首次启动约 2–4 s（onedir 冷启动，PyInstaller 解包依赖）。
- 三语安装：简体中文语言文件来自社区翻译（`packaging/inno/ChineseSimplified.isl`，
  Inno Setup 官方未内置）；英文/日文用 Inno 自带语言包。

## 4. 验收记录

自动化可执行部分（第 1–3、6 轮 + 第 5 轮静默安装）已于 2026-11-05 全部通过；
带 GUI 交互的第 4 轮与「双击安装包看中文界面」仍需人工确认。

| 轮 | 结果 | 备注 |
|---|---|---|
| 1 · 哈希 | ✅ 自动 | 修复两处非确定性（PE 时间戳 / 哈希随机化）后，同一 commit 连续两次构建四个 exe 逐字节一致；`dist` 实测 `XinRefinement.exe = d452f324…`、`XinRefinementCLI.exe = 009236bd…` |
| 2 · CLI 冷启动 | ✅ 自动 | 两变体均输出 `XinRefinement 1.0.0`，无缺 DLL |
| 3 · CLI 端到端 | ✅ 自动 | 两变体均 `rwp = 3.409617`、`chi2 = 1.205705`、2 相、`success = true`，与源码/golden 逐位一致 |
| 4 · GUI 冒烟 | 🟡 半自动 | 离屏启动 + 自检 JSON 通过（窗口可建、菜单/图标/画布加载完成）；**双击实机仍需人工目视** |
| 5 · 安装/卸载 | ✅ 半自动 | 静默安装 534 文件 / 263 MB → 安装版 `--version` 正常 → 注册码写入后自检 `已注册：验收测试单位` → 卸载后 0 残留、注册表项移除；中文安装界面需人工目视 |
| 6 · 双变体差异 | ✅ 自动 | 正式版 `{release, registration_enabled: true, 未注册}`；内部版 `{internal, registration_enabled: false, 内部评估版本}`；正式版设 `XINREFINEMENT_VARIANT=internal` 仍报 release（防绕过） |

> 说明：单文件 exe 在 onedir 模式下**不含变体差异**（变体由 `_internal/variant.txt` 决定），
> 因此正式版与内部版的 `XinRefinement.exe` 哈希相同属预期，不是打包错误。
