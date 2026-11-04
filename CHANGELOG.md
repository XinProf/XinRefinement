# 变更记录

## v1.0.0（2026-11-04）

首个完整版本：通用粉末衍射全谱拟合（Rietveld 结构精修 / 谱图精修）。

### 引擎

- **精修核心**：变量投影（线性 scale/背景解析消去）+ LM / scipy-trf 双后端；Pnma/R-3m 等全 230 空间群（spglib），含 H/R 设置与 Wyckoff 零空间自由坐标
- **参数模型**：声明式 `ParameterRegistry`（pack/unpack/bounds 与旧路径逐位一致），全晶胞按晶系约束（立方 1 → 三斜 6）
- **结构精修**：原子坐标（Wyckoff 约束）、各向同性 B、占位（含 `occ_anchor` 退化处理）
- **谱图精修**：零点/样品位移、背景三模式（Chebyshev/tent/手动点）、Caglioti+TCH 尺寸应变、η、asym、Kα1/Kα2、March-Dollase 多相 PO
- **定量与不确定度**：Hill-Howard QPA、Schur 补全参数 e.s.d.（含 scale/背景/含量）、DW 统计量
- **Le Bail**：无结构强度提取 + 多相定量；**CIF 写回**：晶胞/坐标/B/占位

### GUI（PySide6）

- 三区主窗口 + 8 步导航式精修（单步 / 一键连跑 / 后台线程 / 停止 / 回退）
- 交互图谱：实测/计算/残差双轴、背景曲线、每相峰位棒、框选缩放、相开关即时重绘
- 齿轮弹窗：背景、晶胞（多物相分别勾选）、峰形、原子、温度因子、PO、微结构
- 结果区三页：摘要（R 因子/含量/DW/e.s.d.）、收敛曲线、相关性矩阵
- 三语 i18n（zh/en/ja，切换无需重启）、工程文件 `.xrp` 保存/恢复
- 报告导出：HTML + PNG + JSON 精修日志

### 命令行与 API

- `XinRefinementCLI refine <pattern> <cif...>`：`--recipe`（配方分步）、`--report`（HTML/PNG/JSON 目录）、`--quant`（WPF 定量）、`--esd`（Schur e.s.d.）、`--version`
- 公开库 API：`xinrefinement/api.py`（`RefineRequest`/`RefineResponse`、`refine`/`quant`/`report`/`capabilities`、`API_VERSION`）

### 验收

- 测试 **238 项全绿**；`bench_b` 家族 golden round-trip **8/8 PASS**（Rwp 3.41–4.04%，与移植前逐位一致）
- 虚拟样全基准 **18/18 PASS**（5 晶系 × 1–3 相 × 注入旋钮）
- 真实锚点：NCM811 实样收敛（Rwp 11.25% 登记）；**GSAS-II 5.8.2 交叉验证晶胞最大相对差 0.031%（实样）/ 0.015%（双相）**
- 本地二进制：PyInstaller onedir（GUI + CLI）+ Inno Setup 安装包（zh/en/ja）

### 已知限制

- TCH 尺寸应变的 X/Y 若精修后停在 0（分支切换点），其 e.s.d. 记为空值（导数无定义）
- 占位精修需锚定位点（单相全位点绝对占位被 scale 吸收，物理不可辨识）
- 多相 QPA 的 GSAS-II 交叉验证、FullProf/MAUD/Profex 对比为人工步骤
