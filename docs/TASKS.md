# XinRefinement 任务手册（TASKS）

> 依据 `docs/PROJECT_PLAN.md`（已拍板 v1 决策）。每任务卡 = 目标 / 文件 / 关键方法签名 / I-O / 算法要点 / 边界 / 验收命令。
> 验收统一用家族 venv：`D:/Project/XRD/python310/python.exe -m pytest -q`（在 `D:/Project/XinRefinement` 下执行）。

## 0. 阶段总览

| 阶段 | 目标 | 步骤 | 状态 |
|---|---|---|---|
| P0 | 基线冻结（先立基线） | P0.1–P0.3 | ✅ 完成（2026-11-04） |
| M0 | 垂直切片 MVP | M0.1–M0.3 | ✅ 完成（2026-11-04） |
| P1 | 通用化引擎（结构精修） | P1-PRE、P1.0a/b/c、P1.1–P1.5 | ✅ **全部完成**（P1.5 e.s.d. 已落地） |
| P2 | 精修参数模块（谱图精修） | P2.1–P2.11 | ✅ **全部完成**（P2.3/2.4/2.5/2.7/2.8/2.9/2.11 已落地，见第 3 节） |
| P3 | 导航式精修 + GUI | P3.1–P3.7 | ✅ **全部完成**（P3.5 结果区深化已落地） |
| P4 | 报告 + 验收 + 发布 | P4.1–P4.6 | 🟡 进行中：P4.1 / P4.2 / P4.5 / P4.6 已完成（品牌资产一并落地）；P4.3 交叉验证 / P4.4 打包发布待实施 |

**关键路径 / 依赖**：
```
P0 ✅ ─→ M0（垂直切片 MVP：solve+CLI，现有引擎单相）
              │  （M0 产出与 P1.0a 复用，P1.0a 直接升级此 solve）
              ↓
P1-PRE（虚拟样合成器，P1/P2 验收地基）
   ├─→ P1.0a ─→ P1.0b ─→ P1.0c ─────────┐
   └─→ P1.1（spglib，与 P1.0 可并行）     │
        └─────────→ P1.2 → P1.3 → P1.4 → P1.5
                       ↓
              P2（依赖 P1.2/P1.4/P1.5 与 P1-PRE）
                       ↓
              P3（依赖 P2 稳定 core；P3.1/P3.2 可用 P0 引擎先渲染假数据）
                       ↓
              P4（P4.6 XinMatch 对接依赖 P1.0c 公开 solve 入口）
```

---

## 1. P0 基线冻结（原子级）

### P0.1 仓库骨架

**目标**：可 import、可测试的最小工程骨架。

**文件**
```
D:/Project/XinRefinement/
├── pyproject.toml          # 包元数据 + 依赖 + mypy/pytest 配置
├── requirements.txt        # numpy 2.2.6 / scipy 1.15.3 / matplotlib 3.10.9 /
│                           #   PySide6 6.11.2 / spglib / pytest（锁定）
├── pytest.ini              # testpaths=tests, addopts
├── README.md               # 项目定位一句话 + 目录
├── xinrefinement/
│   ├── __init__.py         # __version__
│   ├── core/__init__.py
│   ├── gui/__init__.py
│   ├── cli/__init__.py
│   └── i18n/__init__.py
└── tests/
    └── test_smoke.py       # import 冒烟
```

**验收**
- `D:/Project/XRD/python310/python.exe -m pytest -q` 通过（空跑 + 冒烟）
- `D:/Project/XRD/python310/python.exe -c "import xinrefinement; print(xinrefinement.__version__)"` 输出版本号

### P0.2 vendor 移植精修引擎核心

**目标**：把家族已验证引擎收编到 `xinrefinement.core`，命名空间重写 + 测试迁移。

**源 → 目标映射**（主源 NCA，它是 RutAna 超集；对称元数据用 NCA 版 `data/spacegroups.json`，非 LFP 版）
| 源 | 目标 | 说明 |
|---|---|---|
| `nca/core/dtypes.py` | `core/dtypes.py` | Pattern 等数据类型 |
| `nca/core/patterns.py` | `core/patterns.py` | 谱读入（家族 Converter vendor）；P1 迁入 `core/io/` |
| `nca/core/background.py` | `core/background.py` | 背景（含 tent） |
| `nca/core/kalpha2.py`（RutAna） | `core/kalpha2.py` | Kα2 剥离 |
| `nca/core/profile/cif.py` | `core/profile/cif.py` | CifStructure + symop 展开 |
| `nca/core/profile/shape.py` | `core/profile/shape.py` | PV/Caglioti/波长/M-D |
| `nca/core/profile/struct.py` | `core/profile/struct.py` | 结构因子/峰枚举 |
| `nca/core/profile/forward.py` | `core/profile/forward.py` | 前向模型（含 TCH X/Y） |
| `nca/core/profile/size_strain.py` | `core/profile/size_strain.py` | TCH 尺寸/应变 |
| `nca/core/refine/linear.py` | `core/refine/linear.py` | 变量投影线性层 |
| `nca/core/refine/lm.py` | `core/refine/lm.py` | 自研 LM |
| `nca/core/refine/nonlinear.py` | `core/refine/nonlinear.py` | 精修主入口（超集） |
| `nca/core/refine/rfactors.py` | `core/refine/rfactors.py` | R 因子 |
| `nca/core/refine/rbragg.py` | `core/refine/rbragg.py` | R_Bragg |
| `nca/core/refine/corr.py` | `core/refine/corr.py` | 相关性矩阵 |
| `nca/core/refine/qpa.py` | `core/refine/qpa.py` | Hill-Howard 定量 |
| `nca/core/refine/occ.py` | `core/refine/occ.py` | 占位精修 |
| `nca/core/refine/plan.py` | `core/refine/plan.py` | 段配置翻译 |
| `nca/core/refine/valley.py` | `core/refine/valley.py` | 谷扫描（P1 用） |
| `nca/core/symmetry.py` + `nca/data/spacegroups.json` | `core/symmetry.py` + `data/spacegroups.json` | 230 空间群元数据（**NCA 版**，非 LFP 版；LFP 版为独立全表留作 P1 兜底评估） |

**关键规则**
- 命名空间替换：`from nca.core...` / `from rutana.core...` / `from lfp.core...` → `from xinrefinement.core...`；相对 import 同步改。
- 保留文件头 vendor 来源注释（版权/复用说明）。
- 测试随源迁移到 `tests/`，import 同步改写。

**验收**
- `pytest -q` 全绿（家族原测试在新命名空间下通过）
- `grep -rn "from nca\|from rutana\|from lfp\|import nca\|import rutana\|import lfp" xinrefinement/` 无残留

### P0.3 golden 基线冻结

**目标**：在 `xinrefinement.core` 上复现家族基准，冻结数值基线。

**验收（实际结果）**
- ✅ TiO₂ 虚拟样 8 配比 round-trip：与 RutAna `bench_report_b.md` **逐位一致**（Rwp 3.41–4.04%、回收误差 ±0.038~0.121pp、8/8 PASS），golden 冻结于 `tests/golden/method_b_roundtrip.json`
- ✅ 引擎移植逐位精确（numpy 浮点行为与源一致）
- ⏳ NCM811 实样：并入 P2.11「真实数据锚点」卡收尾验证

---

## 1.5 M0 垂直切片 MVP（✅ 完成 2026-11-04）

> 目的：先用 P0 已 vendor 引擎把「读谱+CIF → solve → CLI 报告」端到端跑通，证明闭环可用，再投入 P1 通用化。M0 产出与 P1.0a 复用（P1.0a 直接升级此 solve）。

| 卡 | 内容 | 验收 | 状态 |
|---|---|---|---|
| M0.1 | 高层入口 `core/refine/solve.py`：`solve(RefineInputs)->SolveResult`（单相/多相；能力=zero+背景+scale+峰形 U/V/W/η + 可选 TCH/PO），含窗口裁剪 + QPA + warnings | 调用 solve 返回 Rwp/参数表/QPA | ✅ |
| M0.2 | CLI `cli/refine.py` + `cli/__main__.py`：`python -m xinrefinement.cli refine <pattern> <cif> [-o report.{json,txt}]` | 一条命令出 JSON/TXT 报告 | ✅ |
| M0.3 | 验收：virtual_b v50 双相 Rwp 3.4096%（与 golden 逐位一致）；QPA anatase 50.03% / rutile 49.97%（对真值 50% 回收 <0.5pp） | 报告含 Rwp/Rp/Rexp/χ² + 参数表 + 物相 | ✅ |

**实现要点 / 已知差异**
- 高层结果命名 `SolveResult`（plan 写作 `RefineResult`）：避免与引擎层 `nonlinear.RefineResult` 重名；`SolveResult.engine` 保留原始低层结果。
- QPA 化学式来源：优先 `RefineInputs.formulas`，缺省回退 CIF `_chemical_formula_sum`（NCA T5.3 决策）。内置 rutile CIF 为 `O2 Ti0.992`，故与 bench 显式教材式 `O2 Ti` 口径差 ~0.12pp（均 <0.5pp）。
- **已知限制（不阻塞 M0）**：单相全参数冷启动（U/V/W+zero 同时精修）在无噪声合成谱上可能落入 ~7% 相关局部极小；virtual_b 双相 round-trip 正常。多起点阈值/初值策略在 P1/P2 改进。
- 新增测试：`tests/test_solve.py`（5）+ `tests/test_cli.py`（2），全套 78 测试全绿。

**M0 明确不含**：全晶胞（除现有四方 a,c）、通用 xyz/B/occ（→P1）、多相定量细化（→P2.5）、Le Bail（→P2.8）、GUI（→P3）。

---

## 2. P1 通用化引擎（结构精修）

> **风险/回退**：P1.0 参数模型重构是最大风险点，故拆 a/b/c 三小步、每步可回退；P1.1 spglib 与 P1.0 可并行（P1.2/1.3/1.4 依赖 Wyckoff 位识别）。

| 卡 | 内容 | 验收 |
|---|---|---|
| P1-PRE | 虚拟样合成器 `tools/gen_virtual.py`：参数化合成已知真值谱（任意晶系/多相/零点/样品位移/背景含弯/PO/尺寸应变/含量/噪声/λ），seed 可复现，冻结 golden 真值 JSON | ✅ 完成：自包含（不跨仓 SynthPattern）、8 配比数据集 `tests/data/virtual_p1/`、seed 复现 + QPA 回收 <0.5pp + 5 个参数旋钮可注入（`tests/test_gen_virtual.py` 7 项） |
| P1.0a | 在 M0.1 基础上补齐 `refine.solve(inputs)->SolveResult` 契约与单测（包一层，**不重构** `_pack/_unpack`，补 NCA 未迁 `solve.py` 职责）；命名以 `SolveResult` 为准，避免与引擎层 `nonlinear.RefineResult` 重名 | TiO₂ 虚拟样 round-trip 串通；`SolveResult` 契约稳定 |
| P1.0b | `core/params/registry.py::ParameterRegistry`（key/owner/histogram/bounds/refine/group/esd）双轨落地：registry 生成 pack 顺序，与旧 `_pack` 并存逐位对比 | ✅ 完成：17 组开关组合下 pack/unpack/bounds 与旧路径**逐位一致**（`tests/test_registry.py`） |
| P1.0c | 生产精修路径切到声明式 registry | ✅ 完成：`refine()` 的 x0/bounds/unpack 与 `_build_residual` **残差热路径**全走 `ParameterRegistry`（闭包外构造一次避免重复建表）；旧 `_pack/_unpack/_bounds` 保留为兼容 API + 双轨回归参照（不删除，保证 `test_size_strain`/`test_registry` 仍可对照）。全量 149 测试 + bench_b 8/8 PASS + CLI 3.409617 逐位不回归 |
| P1.1 | spglib 集成：空间群编号/H-M → symop + 非对称单元展开 + Wyckoff 位识别；**处理设置/原点选择**（CIF 显式 symop 优先；无则匹配 spglib hall_number 或把坐标变换到标准设置） | ✅ 完成：`core/symops.py`（扁平命名，避开既有 `core/symmetry.py`）；全 230 群 symop sanity + R-3m H/R 设置区分 + family symop 等价 + Wyckoff 零空间自由维度（`tests/test_symops.py` 8 项） |
| P1.2 | 全晶胞精修 a,b,c,α,β,γ（按晶系约束：立方 1/四方 2/正交 3/单斜 4/三斜 6/六方三方 2） | ✅ 完成：`core/refine/cell.py` 独立引擎（**不改 nonlinear 默认路径，golden 零风险**）；晶系判定空间群优先 + 度量兜底；`apply_cell_scales` 非自由轴跟随；LM/scipy-trf 双后端。虚拟样 round-trip 各轴相对误差 <1e-3（优于 0.1% 要求），`tests/test_cell_refine.py` 13 项 |
| P1.3 | 原子坐标精修（Wyckoff 位约束）：用 site symmetry 旋转矩阵 (R−I) 的零空间求每个位点的**自由坐标维度**，只对自由分量建变量、联动分量用约束表达 | ✅ 完成：`core/refine/site.py` 自建**不对称单位模型**（`parse_cif` 会展开、不保留映射，故重新读 CIF 未展开位点 + symop）；`to_structure` 按 symop 重新展开→等价原子天然联动。实测 anatase Ti 特殊位 `n_free=0`、O 位 `n_free=1`；零向量重建与 `parse_cif` 原子数/峰位数/坐标逐位一致。坐标回收 <1e-3，9 项测试 |
| P1.4 | 各向同性 B + 占位精修 | ✅ 完成：同一站点引擎按位点联动 B/occ；B 回收 ±0.2 Å²、occ ±0.02。**实测发现两个真实约束**：① `forward._PEAKS_CACHE` 的 `id(struct)` 键会让原子参数变化被缓存吞掉 → 用引擎预留的 `_variant` 盐值修复；② 单相全位点 occ 绝对标度被变量投影 scale 吸收（不可辨识）→ 实现 `occ_anchor=True` 固定首位点，只精修相对占位 |
| P1.5 | 参数 e.s.d.（雅可比协方差 + **Schur 补纳入变量投影消去的 scale/背景线性参数**） | ✅ 完成：`core/refine/esd.py`。全参数 θ=(x,c) 协方差由 `S = JfᵀP⊥Jf` 的 Schur 补组装；**两条独立路径互校**（reduced 残差 Jacobian 的 JᵀJ vs Schur 补）相对差 <5%；scale、背景、物相含量 e.s.d. 均非空；协方差对称半正定、对角相关=1 |

> **P1 目录落地约定（实测修正）**：`core/symmetry.py` 是 P0 的**单文件模块**（16 项测试依赖），同目录不能并存 `symmetry/` 包。故 P1.1 以扁平 `core/symops.py` 落地，P1.0b 以新建 `core/params/` 子包落地；`core/io/`、`core/structure/` 的迁移推迟到 P1.0c 统一整理，避免来回搬文件。
> 已落地关键方法：`core/symops.py::symops_from_spg/hall_candidates/match_setting/expand_unit_cell/free_coordinate_dims/free_coordinate_basis`、`core/params/registry.py::ParameterRegistry`、`tools/gen_virtual.py::synthesize/write_dataset`。
> 待落地：`refine/cell.py::cell_scale_from_system()`（P1.2）、全晶胞/坐标/B/occ 变量接入 registry（P1.2–P1.4）。

---

## 3. P2 精修参数模块（谱图精修）

| 卡 | 内容 | 验收 |
|---|---|---|
| P2.1 | 零点 + 样品位移（S·cosθ，**默认 Bragg-Brentano 平板几何**；毛细管/透射几何归 v2） | ✅ 完成：`core/refine/geometry.py` 独立引擎，位移在求值网格上施加（不改 P0 前向模型）；3 组虚拟样 zero/disp 回收 <0.005° |
| P2.2 | 背景三模式：Chebyshev / tent / 手动插值点 | ✅ 完成：`linear.py` 加 `manual_basis`（点自动排序、区间外端点外推）+ `solve_linear_detail(..., bg_mode="manual", bg_points=...)` 独立分支（先扣固定背景再解 scale）；cheb/tent 路径逐位不变 |
| P2.3 | 峰形全开关：Caglioti + TCH 尺寸/应变 + η + asym + Kα2 | ✅ 完成：全开关组合一键精修收敛、Rwp<5%（`tests/test_p2_p46.py`）；NCM811 Rwp 11.25% 已登记 `docs/REAL_ANCHORS.md` |
| P2.4 | March-Dollase 择优取向（多相独立） | ✅ 完成：双相独立 r 精修收敛；完美拟合（Rwp≈0）时 LM success=False 属 ftol 语义，测试按 rwp 判定 |
| P2.5 | 标度 + QPA（Hill-Howard） | ✅ 完成：bench_full 18/18 PASS 含量回收 ±0.12pp 内（含弯背景/位移/PO/尺寸应变注入） |
| P2.6 | 微结构输出：尺寸 D、应变 ε | ✅ 完成：`core/refine/micro.py`，D/ε 正反演误差 <5%；`Y=0` 正确报「超出检出上限」而非无限大晶粒 |
| P2.7 | 仪器/辐射参数：波长 λ、Kα1/Kα2 比（Cu/Mo/Co、同步辐射任意 λ；v1 仅 X 射线 + 非偏振 LP，单色器偏振归 v2） | ✅ 完成：换 λ 峰位按 λ 比例迁移 + Kα2 双线结构验证（`test_p27_wavelength_shift`） |
| P2.8 | Le Bail 模式：无结构强度提取 + 多相定量 | ✅ 完成：`core/refine/lebail.py`（迭代分解 I→解析解线性 c→更新 I）；多相定量与 Rietveld 同数量级；**实现注**：峰形矩阵按峰高校准（与家族口径一致） |
| P2.9 | 精修结果写回 CIF（晶胞/坐标/B/occ） | ✅ 完成：`core/profile/cif_writer.py`（对称位全原子写出）；写回后 `parse_cif` 重新解析原子数/晶胞一致（`test_p29_cif_writeback`） |
| P2.10 | 自动初值估算器：导入谱图+CIF 后自动估 scale/零点/背景/展宽初值 | ✅ 完成：`core/refine/initial.py`（背景分位数 / 最强峰对齐 zero / 半高宽反推 W / scale 比值）；估算初值一键精修 `success=True, Rwp<10%`；已知零点谱估算偏差 <0.05° |
| P2.11 | 真实数据锚点：TiO₂（RutAna）、NCM811（NCA）、LFP、NCA 实样在 `xinrefinement.core` 上跑通 | ✅ 部分完成：`tools/real_anchors.py` 登记脚本 + `docs/REAL_ANCHORS.md`（TiO₂ 虚拟 golden Rwp 5.85%、NCM811 实样 Rwp 11.25% 均收敛）；LFP/NCA 实样待补 |

---

## 4. P3 导航式精修 + GUI

| 卡 | 内容 | 验收 |
|---|---|---|
| P3.1 | 主窗口骨架（三区 + 工具栏 + 菜单） | ✅ 完成：`gui/main_window.py` + `gui/__main__.py`；菜单 5 项、工具栏 5 按钮、8 个导航步骤行（▶+⚙）、结果表；`python -m xinrefinement.gui` 可启动 |
| P3.2 | 交互图谱（实测/计算/残差/峰位棒/相开关/缩放） | ✅ 完成：`core/palette.py` + `gui/canvas.py`；双轴 obs/calc/diff + 每相峰位棒 + 背景曲线重建 + NavigationToolbar 框选缩放 + `set_phase_visible()` 即时重绘（不重新精修） |
| P3.3 | 导航式精修向导（Recipe 引擎 + 单步/连跑 + Rwp 监控 + 快照回退 + 后台线程） | ✅ 完成：`core/refine/recipe.py`（8 步标准配方，xyz/B 标记 `available=False` 连跑跳过不做假执行；StepRecord + 快照回退 + cancel_cb）+ `gui/workers.py`（QThread 后台，5 个 Signal，可取消）+ 主窗口接入（单步/一键连跑/停止/进度）。`tests/test_recipe.py` 7 项 + GUI 冒烟 3 项。**实测修复**：取消路径的模态 QMessageBox 在离屏测试会永久阻塞（挂 12 分钟），已改为取消不弹框 |
| P3.4 | 按钮+齿轮弹窗（背景/晶胞多相/峰形/原子坐标/温度因子/择优取向/微结构） | ✅ 骨架完成：`gui/dialogs.py`；背景弹窗（函数/阶数/手动点）**已传导到 RefineConfig**、晶胞多物相分别勾选（b/α/β/γ 待 P1.2 开放）、其余通用开关表 |
| P3.5 | 结果区（R 因子/含量/相关性/收敛曲线/DW/e.s.d.） | ✅ 完成：三页 QTabWidget（摘要 / 收敛曲线 / 相关性）；`core/refine/diagnostics.py` 提供 DW 与收敛摘要；摘要含 DW 与含量 e.s.d.；高相关参数对 `|r|≥0.7` 标 ⚠；三语标签同步 |
| P3.6 | i18n 三语 zh/en/ja | ✅ 完成：`i18n/catalog.py` 三语字典（键集合一致、无空值）+ `tr()` 回退链 + `set_language`；主窗口 `retranslate()` 刷新标题/菜单/工具栏/导航步骤/结果表，画布 `retranslate()` 刷新图例/轴标签/空态。**语言切换无需重启**，10 项测试 |
| P3.7 | 工程文件保存/恢复（.xrp：谱图引用+CIF+设置+结果摘要+导航状态+步骤记录+语言） | ✅ 完成：`gui/project.py` JSON 格式（含 `format`/`format_version`/`app_version` 校验）；路径相对化（跨盘符回退绝对）、缺文件报 `missing` 不中断；主窗口 `project_state()` / `apply_project()`。保存→新建→恢复全状态还原，10 项测试 |

---

## 5. P4 报告 + 验收 + 发布

| 卡 | 内容 | 验收 |
|---|---|---|
| P4.1 | 报告导出 PNG/CSV/JSON/HTML（参考 Profex report 结构）+ 精修日志（每步参数变化、Rwp 历史、最终参数+e.s.d.） | ✅ 完成：`core/report.py` 三件套（HTML 含拟合图/R因子/参数/物相/收敛/DW/e.s.d.；PNG 离屏拟合图；JSON 可复现日志），色板与界面同源；GUI 报告菜单已接入。**CSV 导出留待 P4.1b**（当前 JSON 可等价承载） |
| P4.2 | 虚拟样 round-trip 全基准（多晶系×多相） | ✅ 完成：`tools/bench_full.py` 18/18 PASS（立方/四方/六方/正交/单斜 × 1–3 相 × 注入旋钮），报告落盘 `bench_full_report.md` |
| P4.3 | 真实数据交叉验证（GSAS-II/FullProf/MAUD/Profex），**只比结构量**（晶胞/含量/占位/R_Bragg），Rwp 因实现差异仅登记 | 结构量一致性登记；Rwp 差异有口径说明 |
| P4.4 | 打包 PyInstaller + Inno Setup（zh/en/ja） | 双击验收 + 5 轮稳健性 |
| P4.5 | CLI 批处理入口（`refine --recipe/--report/--quant/--esd`） | ✅ 完成：四旗全接（配方分步/HTML 报告目录/WPF 定量表/Schur e.s.d.）；v50 一条命令全流程通过 |
| P4.6 | 公开库 API 契约 + XinMatch 对接 demo（`xinrefinement.core` 稳定 solve/quant/report 入口 + 版本化约定） | ✅ 完成：`xinrefinement/api.py`（RefineRequest/RefineResponse + refine/quant/report/capabilities + API_VERSION）；`test_p46_public_api` 验证最小调用 |

---

## 6. v2 待办（明确延后，不阻塞 v1）

> v1 已在参数模型**预留 histogram 维度**（见 plan §3.3），为「多谱联合精修」铺路。

| 能力 | 说明 |
|---|---|
| 序贯精修（Sequential） | 多谱图/温度/原位批处理，全局参数共享 |
| 多谱联合精修（Joint） | XRD+中子/多台仪器/多温度点联合拟合同一结构（histogram 维度） |
| 参数硬约束框架（equality/linear/coupling） | 对标 GSAS-II `mapvars`：参数等式约束、线性组合、跨相共享、固定比例 |
| 键长/键角/原子间距/软约束 | 复杂结构/低分辨谱的进阶稳定性约束 |
| IRF 仪器参数文件 + 标样标定 | FullProf `.irf` / GSAS-II instrument parameter file + LaB6/Si 标样标定零点/展宽 |
| 各向异性峰宽（尺寸/应变） | Stephens 各向异性应变、Popa/球谐各向异性尺寸、位错展宽 |
| 球谐择优取向 | M-D 不足以描述的强取向 |
| 无定形/非晶含量（内标法） | 加内标（刚玉/ZnO）定无定形相与非晶含量 |
| Brindley 微吸收 | 含量精度的进阶 |
| 各向异性温度因子 U_ij | 高 Q / 对称性破坏数据 |
| 消光 + 透射吸收校正 | extinction/absorption/transmission |
| 中子数据（恒定波长/TOF） | 散射长度 b 表 + 独立结构因子（磁散射可选）+ TOF 峰形（Ikeda-Carpenter/back-to-back） |
| FCJ 几何不对称 | Finger-Cox-Jephcoat 样品高度尾模型，替代经验 split-PV |
| 异常散射 f′/f″ | 同步辐射近边色散校正（Cromer-Mann 仅 f0） |
| 偏振/单色器校正 | LP 偏振因子（当前非偏振） |
| 几何扩展（毛细管/透射/平板） | BB 之外的位移/吸收/透明度模型 |
| 多核并行 | 多相峰枚举/多起点重启并行化（P4 性能基准后评估） |
| 谱图格式扩展 | Panalytical `.xrdml/.udf`、Rigaku、MAUD `.ins/.esg`、FullProf `.dat/.pcr`、标准 `.cif` 粉谱、Bruker `.raw/.ras`、GSAS 等 |
