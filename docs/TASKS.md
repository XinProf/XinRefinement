# XinRefinement 任务手册（TASKS）

> 依据 `docs/PROJECT_PLAN.md`（已拍板 v1 决策）。每任务卡 = 目标 / 文件 / 关键方法签名 / I-O / 算法要点 / 边界 / 验收命令。
> 验收统一用家族 venv：`D:/Project/XRD/python310/python.exe -m pytest -q`（在 `D:/Project/XinRefinement` 下执行）。

## 0. 阶段总览

| 阶段 | 目标 | 步骤 | 状态 |
|---|---|---|---|
| P0 | 基线冻结（先立基线） | P0.1–P0.3 | ✅ 完成（2026-11-04） |
| M0 | 垂直切片 MVP | M0.1–M0.3 | ✅ 完成（2026-11-04） |
| P1 | 通用化引擎（结构精修） | P1-PRE、P1.0a/b/c、P1.1–P1.5 | ⬜ 待实施 |
| P2 | 精修参数模块（谱图精修） | P2.1–P2.11 | ⬜ 待实施 |
| P3 | 导航式精修 + GUI | P3.1–P3.7 | ⬜ 待实施 |
| P4 | 报告 + 验收 + 发布 | P4.1–P4.6 | ⬜ 待实施 |

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
| `lfp/core/symmetry.py` | `core/symmetry.py` | 230 空间群元数据（**实际采用 NCA 版**，依赖 `data/spacegroups.json`） |

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
| P1-PRE | 虚拟样合成器 `tools/gen_virtual.py`：参数化合成已知真值谱（任意晶系/多相/零点/样品位移/背景含弯/PO/尺寸应变/含量/噪声/λ），seed 可复现，冻结 golden 真值 JSON | 合成谱可被引擎读入并回读 seed 真值；为 P1/P2 验收提供地基 |
| P1.0a | 在 M0.1 基础上补齐 `refine.solve(inputs)->RefineResult` 契约与单测（包一层，**不重构** `_pack/_unpack`，补 NCA 未迁 `solve.py` 职责） | TiO₂ 虚拟样 round-trip 串通；RefineResult 契约稳定 |
| P1.0b | `params/registry.py::ParameterRegistry`（key/owner/histogram/bounds/refine/group/esd）双轨落地：registry 生成 pack 顺序，与旧 `_pack` 并存逐位对比 | registry 单测（注册/开关/边界/pack-unpack）全绿；与旧 `_pack` 逐位一致 |
| P1.0c | 全面替换硬编码 `_pack/_unpack` + 删除旧路径 | 旧路径 grep 无残留；round-trip 数值不回归 |
| P1.1 | spglib 集成：空间群编号/H-M → symop + 非对称单元展开 + Wyckoff 位识别；**处理设置/原点选择**（CIF 显式 symop 优先；无则匹配 spglib hall_number 或把坐标变换到标准设置） | 全 230 群 symop 数 sanity check + 同群不同设置（Pnma/Pbnm、R-3m 六方/菱方）展开一致 + 手验 golden 多重度子集 |
| P1.2 | 全晶胞精修 a,b,c,α,β,γ（按晶系约束：立方 1/四方 2/正交 3/单斜 4/三斜 6） | 虚拟样晶胞回收 < 0.1% |
| P1.3 | 原子坐标精修（Wyckoff 位约束）：用 site symmetry 旋转矩阵 (R−I) 的零空间求每个位点的**自由坐标维度**，只对自由分量建变量、联动分量用约束表达 | 坐标回收 < 1e-3；特殊位（4a/4c/8d…）自由坐标数与 International Tables 一致 |
| P1.4 | 各向同性 B + 占位精修 | 与 seed 真值比对：B ±0.2 Å²、occ ±0.02 内（不依赖 e.s.d.） |
| P1.5 | 参数 e.s.d.（雅可比协方差 + **Schur 补纳入变量投影消去的 scale/背景线性参数**） | e.s.d. 与数值 Hessian 交叉验证误差 < 5%；scale/含量 e.s.d. 非空且量级合理 |

> 关键方法（实施时细化签名）：`symmetry/ops.py::symops_from_spg()`、`structure/expand.py::expand_unit_cell()`、`params/registry.py::ParameterRegistry`、`refine/cell.py::cell_scale_from_system()`。

---

## 3. P2 精修参数模块（谱图精修）

| 卡 | 内容 | 验收 |
|---|---|---|
| P2.1 | 零点 + 样品位移（S·cosθ，**默认 Bragg-Brentano 平板几何**；毛细管/透射几何归 v2） | 位移虚拟样回收 < 0.005° |
| P2.2 | 背景三模式：Chebyshev / tent / 手动插值点 | 弯背景虚拟样 Rwp ≤ 噪声理论 Rwp + 0.5pp |
| P2.3 | 峰形全开关：Caglioti + TCH 尺寸/应变 + η + asym + Kα2 | NCM811 Rwp 不劣于 NCA 基线 |
| P2.4 | March-Dollase 择优取向（多相独立） | PO 虚拟样 r 回收 |
| P2.5 | 标度 + QPA（Hill-Howard） | 多相含量回收 < 0.5pp |
| P2.6 | 微结构输出：尺寸 D、应变 ε | D/ε 反演误差 < 5% |
| P2.7 | 仪器/辐射参数：波长 λ、Kα1/Kα2 比（Cu/Mo/Co、同步辐射任意 λ；v1 仅 X 射线 + 非偏振 LP，单色器偏振归 v2） | 换 λ 虚拟样峰位正确迁移 |
| P2.8 | Le Bail 模式：无结构强度提取 + 多相定量 | 与对应 Rietveld 强度/含量一致 |
| P2.9 | 精修结果写回 CIF（晶胞/坐标/B/occ） | 写回后可用 spglib 重新解析且结构一致 |
| P2.10 | 自动初值估算器：导入谱图+CIF 后自动估 scale/零点/背景/展宽初值 | 无人工初值时一键精修可收敛到阈值内 |
| P2.11 | 真实数据锚点：TiO₂（RutAna）、NCM811（NCA）、LFP、NCA 实样在 `xinrefinement.core` 上跑通 | Rwp/含量与家族基线登记一致 |

---

## 4. P3 导航式精修 + GUI

| 卡 | 内容 | 验收 |
|---|---|---|
| P3.1 | 主窗口骨架（三区 + 工具栏 + 菜单） | GUI 可启动、导入谱图/CIF |
| P3.2 | 交互图谱（实测/计算/残差/峰位棒/相开关/缩放） | 渲染正确可交互 |
| P3.3 | 导航式精修向导（Recipe 引擎 + 单步/连跑 + Rwp 监控） | 虚拟样连跑收敛 |
| P3.4 | 按钮+齿轮弹窗（背景/晶胞多相/峰形/原子坐标/温度因子/择优取向/微结构） | 改设置后结果随之变化 |
| P3.5 | 结果区（R 因子/含量/相关性/收敛曲线） | 与 core 数值一致 |
| P3.6 | i18n 三语 zh/en/ja | 语言切换生效 |
| P3.7 | 工程文件保存/恢复（.xrp：谱图引用+CIF+参数设置+结果+导航状态+历史） | 保存→关闭→重开状态完全恢复且结果可复现 |

---

## 5. P4 报告 + 验收 + 发布

| 卡 | 内容 | 验收 |
|---|---|---|
| P4.1 | 报告导出 PNG/CSV/JSON/HTML（参考 Profex report 结构）+ 精修日志（.lst/JSON：每步参数变化、Rwp 历史、最终参数+e.s.d.） | 导出可读、数据完整、可复现 |
| P4.2 | 虚拟样 round-trip 全基准（多晶系×多相） | 全 PASS |
| P4.3 | 真实数据交叉验证（GSAS-II/FullProf/MAUD/Profex），**只比结构量**（晶胞/含量/占位/R_Bragg），Rwp 因实现差异仅登记 | 结构量一致性登记；Rwp 差异有口径说明 |
| P4.4 | 打包 PyInstaller + Inno Setup（zh/en/ja） | 双击验收 + 5 轮稳健性 |
| P4.5 | CLI 批处理入口（`refine --recipe/--report/--quant`） | 无 GUI 环境跑通 TiO₂ 虚拟样并输出报告 |
| P4.6 | 公开库 API 契约 + XinMatch 对接 demo（`xinrefinement.core` 稳定 solve/quant/report 入口 + 版本化约定） | XinMatch 侧可 import 并跑通一个最小精修调用 |

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
