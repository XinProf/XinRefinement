# v1.0.0 本地二进制验收单（人工）

> 产物**只在本地**：`dist/` 已被 `.gitignore` 排除，未提交、未上传、未发布。
> 全部确认通过后，再由你决定分发方式。

## 1. 产物清单

| 产物 | 路径 | 说明 |
|---|---|---|
| GUI | `dist/XinRefinement/XinRefinement.exe` | windowed，无控制台 |
| CLI | `dist/XinRefinement/XinRefinementCLI.exe` | console，批处理 |
| 运行时 | `dist/XinRefinement/_internal/` | PyInstaller onedir 依赖 |
| 安装包 | `dist/installer/XinRefinement-1.0.0-setup.exe` | Inno Setup，zh/en/ja |

重新构建：`python tools/build_binaries.py`（约 2.5 分钟）。
构建后脚本会打印每个产物的 SHA-256 前 16 位；完整校验：

```bash
sha256sum dist/XinRefinement/XinRefinement.exe \
          dist/XinRefinement/XinRefinementCLI.exe \
          dist/installer/XinRefinement-1.0.0-setup.exe
```

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

## 2. 五轮稳健性验收（建议顺序）

| 轮 | 动作 | 通过标准 |
|---|---|---|
| 1 · 哈希一致性 | 连续构建两次，比对三个产物 SHA-256 | GUI/CLI 两次一致（安装包因时间戳允许不同）；不一致需排查非确定性来源 |
| 2 · CLI 冷启动 | 双击或 `XinRefinementCLI.exe --version` | 输出 `XinRefinement 1.0.0`，无缺 DLL 报错 |
| 3 · CLI 端到端 | `XinRefinementCLI.exe refine <谱图.xy> <物相.cif> -o out.json` | JSON 含 `r_factors`/`phases`；Rwp 与源码运行一致（v50 双相 = 3.409617） |
| 4 · GUI 双击冒烟 | 双击 `XinRefinement.exe` | 主窗口出现（标题含 1.0.0）；导入谱图+CIF → ▶精修 → 图谱与结果表刷新；切换语言（设置→语言）文案即时变化 |
| 5 · 安装/卸载 | 双击安装包 → 选简体中文 → 安装到默认目录 → 启动 → 卸载 | 安装界面为中文；开始菜单有 GUI 与 CLI 两项；卸载后目录清空 |

## 3. 已知提示

- 未代码签名：首次运行 Windows SmartScreen 可能提示「未知发布者」，选「仍要运行」。
- 安装包 66.6 MB（含 matplotlib/Qt 运行时），属正常范围。
- GUI 首次启动约 2–4 s（onedir 冷启动，PyInstaller 解包依赖）。
- 三语安装：简体中文语言文件来自社区翻译（`packaging/inno/ChineseSimplified.isl`，
  Inno Setup 官方未内置）；英文/日文用 Inno 自带语言包。
- 若需单文件 exe（onefile）或便携 zip，另开一版构建配置，当前版本未提供。

## 4. 验收记录（人工填写）

| 轮 | 结果 | 备注 |
|---|---|---|
| 1 · 哈希 | ⬜ | |
| 2 · CLI 冷启动 | ⬜ | |
| 3 · CLI 端到端 | ⬜ | |
| 4 · GUI 冒烟 | ⬜ | |
| 5 · 安装/卸载 | ⬜ | |
