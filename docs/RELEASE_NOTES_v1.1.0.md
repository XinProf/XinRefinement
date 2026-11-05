# XinRefinement v1.1.0 — 导入 XinMatch 物相分析（.xinm），工程文件自包含

> 基线 `v1.0.0`｜与 **XinMatch 3.4.0** 配套发布。精修引擎、参数模型、CLI 参数、
> 注册机制**均未改动**；本版新增一条导入通道、一个工程容器格式，并修掉一个
> v1.0.0 的 `.xrp` 丢字段缺陷。

## 下载

| 文件 | 用途 |
|---|---|
| `XinRefinement-1.1.0-setup.exe` | 正式版安装包（含注册机制，zh/en/ja 三语安装界面） |
| `XinRefinement-internal-1.1.0-portable.zip` | 内部评估版便携包（免安装、免注册，状态栏红字标识） |

## 主要能力

### 导入 XinMatch 物相分析（.xinm）

`文件 → 导入 XinMatch 物相分析…`。一次装载三样东西，不再手工搬：

| 载入项 | 来源 | 说明 |
|---|---|---|
| 谱图 | `.xinm` 内 `pattern/pattern.csv` | 两列 CSV，`%.10g` 往返零误差；`wavelength` 一并传到画布（d 轴换算即刻可用） |
| 物相 CIF | `.xinm` 内 `cifs/*.cif` | 按相逐个缓存落地后走既有 `_load_cif_paths`，与手动导入同一条代码路径 |
| 晶胞 / 空间群 | manifest | 与 CIF 解析值核对：一致则预填「物相参数编辑」，显著不符（>0.1% / >0.05°）以 CIF 为准并列出清单 |

无结构的相（PDF2 类、或 COD 归档里没找到 CIF 的）列为**「仅参照」**：灰色列出、
不参与精修、给出可读原因，可手动指定 CIF 补上。

导入内核 `core/io/xinm_import.py` **不依赖 Qt**，GUI / CLI / 库 API 共用；含
manifest 校验、版本协商（`version` 高于支持值提示升级）、zip 炸弹防护（解压上限 512 MB）、
CSV 逐行解析与可读错误。

### 工程文件 `.xinr`：自包含 zip 容器

| 项 | v1.0.0 | v1.1.0 |
|---|---|---|
| 形态 | 纯 JSON，只存外部路径 | zip：`manifest.json + pattern/ + cifs/ + result/` |
| 换机器 | 缺文件就废 | **默认内嵌**谱图 CSV + CIF + 完整精修结果，移走原始文件仍能打开并复现 |
| 结果 | 只存 R 因子摘要 | `result/refine.json`（与 CLI `--out` 同 schema）+ 导航记录，打开即回填结果面板与收敛曲线 |

扩展名分流：`.xinr` → 容器；`.xrp` → v1.0.0 的 JSON **永久只读兼容**。
顺带修掉 v1.0.0 `.xrp` 丢失 `phase_edits` 的 bug（物相参数编辑重开工程后消失）。

### 库 API

`capabilities()` 新增 `xinm_import: "1"`，使用方可探测能力位再决定是否暴露导入入口。

## 验证数据

| 项 | 结果 |
|---|---|
| S1 全闭环（真实 COD 档案 7206075 + 9001681） | `.xinm` 导入 → 精修 Rwp **3.409617019598457**，与 P0 黄金值逐位一致；GUI 一键连跑路径与「手动导入同谱图/CIF」**Rwp 逐位相等**；保存 `.xinr` → 删除临时谱图与 `.xinm` → 重开复现（rel 1e-9） |
| 定量 | 两相 50.03 / 49.97 wt% |
| S2 混合来源 | COD + 用户 CIF 打进 `cifs/`；PDF2 相 `structural=false` 列「仅参照」；**包内无任何 ICDD 衍生文件** |
| S3 异常边界 | 缺 CIF 成员 / 损坏 zip / 缺谱图 / `version=2` 各自可读报错，不崩溃 |
| S4 家族注册 | `XinRefinement.json` 与 `XinMatch.json` 各管各的，注册码算法互通不变 |
| 全量测试 | **286 项全绿**（v1.0.0 为 259；新增 `test_xinm_import.py` 13 项、`test_project_zip.py` 7 项等） |

## 安装与注册

与 v1.0.0 相同：安装包三语（简体中文 / English / 日本語），`{autopf}\XinRefinement`；
首次启动正式版提示「未注册」（可输入注册码）；内部评估版免注册。
注册码与 XinMatch 家族互通，同一个码两软件都能用。

## 构建与二进制验收（六轮）

| 轮 | 结果 | 实测 |
|---|---|---|
| 1 · 可复现构建 | ✅ | 同源连续两次构建，`XinRefinement.exe` / `XinRefinementCLI.exe` **逐字节一致**：`a2c9fcc80b0f291e…` / `7d1ed1ec7efc8642…`（`SOURCE_DATE_EPOCH` + `PYTHONHASHSEED=0`） |
| 2 · CLI 冷启动 | ✅ | 两变体均输出 `XinRefinement 1.1.0`，无缺 DLL |
| 3 · CLI 端到端 | ✅ | 两变体 `refine v50_wide.xy anatase.cif rutile.cif --peak-height` → `rwp = 3.409617`、2 相、`success = true`（合成谱为峰高口径，故需 `--peak-height`；不加该开关为积分口径 `rwp = 5.935965`，与源码逐位一致） |
| 4 · GUI 冒烟 | 🟡 离屏通过 | 离屏启动 + 自检 JSON：正式版 `{release, registration_enabled: true, 未注册}`、内部版 `{internal, false, 内部评估版本}`；**双击目视仍需人工** |
| 5 · 安装/卸载 | ✅ 静默 | 静默安装 606 文件 → 安装版 `--version` 正常 → 静默卸载后 0 残留；中文安装界面需人工目视。（安装器默认要求管理员权限，非交互环境无法提权复验；因构建可复现、`setup.exe` SHA-256 与上轮**逐字节一致**，上轮结论继续有效） |
| 6 · 双变体差异 | ✅ | 标记 `release` / `internal`；正式版设 `XINREFINEMENT_VARIANT=internal` 仍报 `release`（防绕过） |

发布件：

| 文件 | 字节 | SHA-256 |
|---|---:|---|
| `XinRefinement-1.1.0-setup.exe` | 67,586,555 | `046179e6f3ef45d651b241b41dafb273990b423667bc066e5eba2b3982a44926` |
| `XinRefinement-internal-1.1.0-portable.zip` | 113,946,723 | `a9012229b268bae36741bbd7cd9d5782ecf55a814ea907d4b39dded701db09d1` |

## 已知提示

- 正式版 `.xinr` 内嵌 CIF 与谱图，工程文件会比 v1.0.0 的 `.xrp` 大（谱图按 CSV 文本存，
  10 万点约 2 MB）。需要"只存路径"的老行为时，另存为 `.xrp`。
- `.xrp` 只读兼容，不回写：用旧文件打开再保存，会按扩展名决定写回 JSON 还是容器。
- 冻结包内没有 `pyproject.toml`，版本号取自 `xinrefinement/__init__.py` 的字面常量
  （`__version__ = "1.1.0"`），不读运行环境的安装元数据。
- 未代码签名：首次运行 Windows SmartScreen 可能提示「未知发布者」。

## 许可

沿用 v1.0.0：见仓库根 `LICENSE` / `LICENSE-CN`（与 XinMatch 同源）。
