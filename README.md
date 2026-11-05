# XinRefinement

<p align="center">
  <img src="assets/icons/logo_512.png" width="180" alt="XinRefinement logo">
</p>

**通用粉末衍射全谱拟合（Rietveld 结构精修 / Le Bail / 谱图精修）桌面软件。**

简体中文 · [English](README-en.md)

Qt6 图形界面 + 命令行 + Python 库 API 三入口，覆盖「导入谱图 + 物相 CIF → 全谱拟合 → 定量与不确定度 → 报告」的完整工作流。
与家族项目 XinMatch 分工：XinMatch 做峰形处理与物相分析，XinRefinement 只做全谱拟合（结构精修、谱图精修、定量）。

当前版本：**v1.3.0**（开发中，未发布）· 上一版：v1.2.0
v1.3.0 主题：MAUD 借鉴清单全部落地——μ·r 计算器（按化学成分自动算 Brindley
输入）、theoreticalWeights 定权、画布点选背景锚点、EWIMV 离散 ODF 织构、
Popa LB 各向异性尺寸/应变、优化器插拔（lm/trf/dogbox），
详见 [CHANGELOG](CHANGELOG.md)。
v1.2.0 主题：实样对拍驱动的精修质量升级（配方晶胞真精修、积分强度口径、
出厂默认 tent 自适应背景、定权模式、Brindley 微吸收、插值/手动背景），
详见 [CHANGELOG](CHANGELOG.md)。
v1.1.0 主题：与 XinMatch 3.4.0 互通（`.xinm` 导入 / `.xinr` 自包含工程）。

---

## 功能

### 家族互通（v1.1.0 新增）
- **导入 XinMatch 物相分析（`.xinm`）**：`文件 → 导入 XinMatch 物相分析…` 一次装载谱图（含 wavelength，d 轴立即可用）+ 物相 CIF + 元数据，直接进入配方精修；无结构相（PDF2 类）列为「仅参照」并给出手动补 CIF 的提示
- **工程文件 `.xinr`（自包含 zip 容器）**：内嵌谱图 CSV（`%.10g`，往返零误差）+ CIF + 完整精修结果（`result/refine.json`），换机器/移目录后仍可打开并复现上次结果；旧 `.xrp` 永久只读兼容
- **库 API**：`capabilities()` 提供 `xinm_import` 能力位，外部程序可先探测再决定是否暴露导入入口

### 精修引擎
- **参数模型**：声明式参数注册表（`ParameterRegistry`），全晶胞按晶系约束（立方 1 → 三斜 6）；与旧 `_pack/_unpack` 路径双轨兼容且逐位一致
- **求解**：变量投影（标度因子与背景解析消去）+ LM / scipy-trf 双后端，带边界约束与多起点重启
- **对称性**：spglib 全 230 空间群，含 H/R 设置与 Wyckoff 位对称零空间（自由坐标维度）
- **峰形**：Caglioti FWHM、TCH 尺寸/应变分离、η（pseudo-Voigt）、低角不对称、Kα1/Kα2 双线、March–Dollase 择优取向
- **结构**：原子坐标（Wyckoff 约束）、各向同性 B、占位（含退化锚定处理）
- **定量与不确定度**：Hill–Howard QPA、Schur 补全参数 e.s.d.（含标度/背景/含量）、Durbin–Watson 统计量
- **Le Bail**：无结构强度提取 + 多相定量；**CIF 写回**：晶胞 / 坐标 / B / 占位

### 图形界面（PySide6）
- 三区主窗口：物相列表 + 交互谱图 + 导航式精修（8 步，单步 ▶ / 齿轮设置 / 一键连跑 / 停止）
- **MAUD 式物相标记条**：每相一条，左标相名、按相着色、棒高 ∝ 相内相对强度
- **轴切换**：横轴 2θ ↔ d 值（Bragg 换算、自动反向），纵轴 counts ↔ log ↔ √；左键点轴循环、右键选单
- **物相参数编辑**：晶胞 a/b/c/α/β/γ、March–Dollase 择优取向、空间群/点群/劳厄群
- 结果区三页：摘要（R 因子/含量/DW/e.s.d.）、收敛曲线、相关性矩阵
- 三语界面（简体中文 / English / 日本語，切换无需重启）、工程文件 `.xinr`（自包含）/ `.xrp`（路径引用，兼容旧版）
- 报告导出：HTML + PNG + JSON 精修日志

### 命令行与库 API
```bash
XinRefinementCLI refine <谱图> <物相.cif...> [-o out.json]
                        [--recipe] [--report DIR] [--quant] [--esd] [--peak-height]
```
- `--recipe`：按标准配方分步精修；`--report`：HTML/PNG/JSON 三件套；`--quant`：Hill–Howard 定量表；`--esd`：Schur e.s.d.
- 库 API：`xinrefinement/api.py`（`RefineRequest` / `RefineResponse`、`refine` / `quant` / `report` / `capabilities`、`API_VERSION`），供 XinMatch 等外部程序调用

### 双构建变体
| 变体 | 形态 | 注册 |
|---|---|---|
| **正式版** | Inno Setup 安装包（zh/en/ja） | 接入 PolyXRD-Reg 离线注册机制 |
| **内部评估版** | 免安装便携 zip | 不接注册，状态栏标注「内部评估版本」 |

---

## 安装

发布件见 [GitHub Releases](https://github.com/PolyXRD/XinRefinement/releases)（当前 `v1.1.0`）。

### 正式版（推荐）
1. 下载 `XinRefinement-1.1.0-setup.exe`（67.6 MB，SHA-256 `046179e6…a44926`），双击安装（可选简体中文 / English / 日本語）；
2. 首次启动会提示「本软件未注册，版权所有，禁止用于商业用途」——
   按「确定」继续试用，或按「输入注册码」粘贴注册码完成注册；
3. 安装后开始菜单含 **XinRefinement**（GUI）与 **XinRefinementCLI**（命令行）两项。

注册码由开发方按「单位 / 部门名称」签发，离线校验、无需联网、同单位多机通用。
申请与技术支持：**sshztx@outlook.com**

### 内部评估版
从源码构建（见下）可得 `XinRefinement-internal-1.1.0-portable.zip`，解压即用，无需安装、无需注册
（内部测试与评估专用，**不随 Release 分发**）。

---

## 快速开始

### 图形界面
```bash
XinRefinement.exe
```
1. **导入谱图**（`.xy/.txt/.dat/.csv/.xye`）+ **导入 CIF**（可多选）；
   若已在 XinMatch 完成物相分析，直接 `文件 → 导入 XinMatch 物相分析…` 选 `.xinm`，谱图与 CIF 一并就位；
2. 谱图区下方出现每相标记条，可勾选物相开关即时预览；
3. 右侧导航逐项点 ▶ 精修，或「一键连跑」按标准配方一次跑完 8 步；
4. 结果区查看 Rwp / 含量 / e.s.d.，工具栏「报告导出」输出 HTML+PNG+JSON；
5. `文件 → 保存工程…` 存为 `.xinr`（内嵌谱图/CIF/结果，可换机器继续）。

### 命令行
```bash
# 单次统一精修
XinRefinementCLI refine pattern.xy phase_a.cif phase_b.cif -o out.json --peak-height

# 配方分步 + HTML 报告 + 定量 + e.s.d.
XinRefinementCLI refine pattern.xy phase_a.cif phase_b.cif --recipe --report report_dir --quant --esd
```

### 源码运行（开发）
```bash
python -m pytest -q            # 测试
python -m xinrefinement.gui    # 界面
python -m xinrefinement.cli --help
run_dev.bat                    # Windows 一键启动（自动挑解释器，跑最新源码）
```

---

## 构建（本地）

```bash
python tools/build_binaries.py                    # 两个变体全流程
python tools/build_binaries.py --variant release  # 只构建正式版
python tools/build_binaries.py --variant internal # 只构建内部评估版
```

产物（`dist/`，不入库）：

| 路径 | 说明 |
|---|---|
| `dist/XinRefinement-1.1.0/` | onedir，GUI + CLI 双 exe 共享依赖 |
| `dist/installer/XinRefinement-1.1.0-setup.exe` | 正式版安装包（Inno Setup，zh/en/ja）——Release 只发这一个 |
| `dist/XinRefinement-internal-1.1.0/` + `…-portable.zip` | 内部评估版目录与便携包（不对外发布） |

依赖：Inno Setup 6（仅安装包需要）。打包脚本会做变体标记回读校验，避免内部版退化成强制注册版。
构建已固定 `SOURCE_DATE_EPOCH`（= git HEAD 提交时间）与 `PYTHONHASHSEED=0`，
同一 commit 连续两次构建四个 exe **逐字节一致**（安装包/zip 含内嵌时间戳，不参与哈希比对）。

---

## 测试与验证

| 类别 | 结果 |
|---|---|
| 单元/集成测试 | **286 项全绿**（引擎、GUI 离屏冒烟、CLI、i18n、注册与变体、`.xinm`/`.xinr` 互通） |
| 家族链路 S1–S4 | 真实 COD 档案（7206075 + 9001681）`.xinm` → 导入 → 精修 **Rwp 3.409617019598457**（与 P0 黄金值逐位一致），Wt 50.03/49.97；删源后 `.xinr` 复现（rel 1e-9） |
| 合成基准 `bench_b`（家族 golden） | 8/8 PASS，Rwp 3.41–4.04%，移植前后逐位一致 |
| 全基准 `bench_full`（5 晶系 × 1–3 相） | 18/18 PASS |
| 真实锚点 | NCM811 实样收敛（Rwp 11.25%） |
| **GSAS-II 交叉验证** | 晶胞最大相对差 **0.031%**（实样）/ **0.015%**（双相） |

交叉验证方法与结论见 [`docs/CROSS_VALIDATION.md`](docs/CROSS_VALIDATION.md)。

---

## 项目结构

```
xinrefinement/
  core/            # 引擎（不依赖 GUI）
    io/            # .xinm 导入（XinMatch 物相分析状态）
    profile/       # CIF 解析、峰形、结构因子
    refine/        # 求解器、参数注册表、配方、e.s.d.、Le Bail、诊断
    report.py      # HTML/PNG/JSON 报告
    palette.py     # 家族配色（GUI 与报告共用）
  gui/             # PySide6 界面（主窗口、画布、对话框、图标）
  cli/             # 命令行入口
  i18n/            # 三语目录
  data/            # 内置 CIF、空间群表、品牌资源
  api.py           # 公开库 API 契约
  registration.py  # PolyXRD-Reg 注册（与家族项目同源）
  build_variant.py # 构建变体识别
packaging/         # PyInstaller spec + Inno Setup 脚本
tools/             # 构建、交叉验证、基准、出码
docs/              # 方案、任务手册、验收单、交叉验证
tests/             # pytest（含离屏 GUI 冒烟）
```

---

## 文档

| 文档 | 内容 |
|---|---|
| [`CHANGELOG.md`](CHANGELOG.md) | 版本变更记录 |
| [`docs/RELEASE_NOTES_v1.1.0.md`](docs/RELEASE_NOTES_v1.1.0.md) | v1.1.0 发布说明（互通能力与验收数据） |
| [`docs/RELEASE_1.0.0.md`](docs/RELEASE_1.0.0.md) | v1.0.0 发布验收清单（六轮稳健性） |
| [`docs/JOINT_PLAN_xinm_xinr.md`](docs/JOINT_PLAN_xinm_xinr.md) | 与 XinMatch 的 `.xinm`/`.xinr` 格式契约（单一事实源） |
| [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md) | 技术方案与架构决策 |
| [`docs/TASKS.md`](docs/TASKS.md) | 任务手册（P1–P5 交付记录） |
| [`docs/CROSS_VALIDATION.md`](docs/CROSS_VALIDATION.md) | 与 GSAS-II 的结构量交叉验证 |
| [`README-en.md`](README-en.md) | English README |

---

## 许可

**双许可**：学术许可（非商业研究与教学）或另行申请商业许可。
版权所有 (c) 2026 PolyXRD Team。详见 [`LICENSE`](LICENSE) / [`LICENSE-CN`](LICENSE-CN)。

许可与注册机制继承家族项目 XinMatch；商业使用须先取得书面商业许可。

第三方组件：PySide6（LGPL-3.0）、matplotlib（PSF-based）、NumPy / SciPy（BSD-3-Clause）、spglib（BSD-3-Clause）。

---

## 联系

- 注册码申请 / 商业授权 / 问题反馈：**sshztx@outlook.com**
