# XinRefinement · 全谱拟合（结构精修 / Rietveld）项目方案 v1

> 承接 D:\Project\XRD\XinMatch 的数据精修职责；XinMatch 只做峰形处理 + 物相分析（对接 GSAS-II 做谱图精修），**本项目只做全谱拟合（结构精修、谱图精修）**。
> 方案依据：界面草图 `pre-temp/0.jpg` + 家族已验证引擎（RutAna B 法 / NCA / NCM / LFP）+ 四个开源精修软件（GSAS-II / FullProf / MAUD / Profex）本机源码勘察。
> 状态：**已确认** —— 2026-11-04 用户拍板 6 项决策按最优建议执行，进入实施。

---

## 0. 结论先行（TL;DR）

| 维度 | 结论 |
|---|---|
| 项目本质 | 一个**通用粉末衍射全谱拟合（Rietveld）桌面软件**：任意 CIF + 任意谱图 → 精修结构/谱参数 → 输出 R 因子、定量、报告 |
| 算法底座 | **复用家族已验证的精修引擎**（RutAna B 法：变量投影 + LM，NCA/NCM 扩展 TCH 尺寸/应变、占位、相关性）。它在 TiO₂ 虚拟样 round-trip（Rwp 2.1–3.5%、回收误差 ≤0.09pp）与 NCM811 实样上已通过验收，**不必重写数值核心** |
| 核心新增 | ① 通用空间群对称（spglib）② 全晶胞/原子坐标/B 因子/占位精修 ③ 声明式参数模型 ④ 导航式精修 + 按钮/齿轮 GUI |
| 差异定位 | 对标 GSAS-II 的**能力完备度**、FullProf 的**精修顺序可操作性**、MAUD 的**参数面板直观性**、Profex 的**报告与 UI 简洁度**，但**易用性/简洁性优先**（非全参数轰炸） |
| 技术栈 | Python 3.10 + PySide6(Qt6) + numpy/scipy + matplotlib + spglib（BSD，商用兼容），复用家族 venv `D:/Project/XRD/python310` |

---

## 1. 项目定位与范围

### 1.1 做什么 / 不做什么

| ✅ 本项目做（全谱拟合） | ❌ 本项目不做（归 XinMatch） |
|---|---|
| Rietveld / Le Bail 全谱拟合 | 峰形处理、寻峰、峰拟合 |
| 结构精修：晶胞、原子坐标、温度因子 B、占位 | 物相定性鉴定、数据库检索 |
| 谱图精修：零点/样品位移、背景、峰形、择优取向、微结构 | 对接 GSAS-II 做精修 |
| 仪器/辐射参数：波长 λ、Kα1/Kα2 比、单色器 | — |
| 多相定量（Hill-Howard 等）、R 因子、相关性、e.s.d. | 谱图格式转换（复用 Converter） |
| Le Bail 模式（无结构强度提取 + 定量） | — |
| 精修结果写回 CIF（晶胞/坐标/B/occ） | — |
| 工程文件保存/恢复（.xrp） | — |
| 导航式精修向导 + 交互图谱 + 报告导出 + CLI 批处理 | ab initio 结构求解（模拟退火/直接法/倒空间法，归结构求解工具） |

### 1.2 与 XinMatch / 家族的关系

- **独立仓库独立 GUI**（workspace = `D:/Project/XinRefinement`），但核心层设计成**可被 import 的库**，未来 XinMatch 可嵌入 `xinrefinement.core` 替代其 GSAS-II 委托。
- 复用家族资产：谱图读入器（Converter vendor）、CIF 解析器（cif.py，含 symop 展开）、散射因子表（Cromer-Mann 4-Gaussian）、精修引擎核心。
- 命名空间 `xinrefinement`（对齐 `xinmatch`/`rutana`/`nca`）。

---

## 2. 现状盘点（关键发现）

### 2.1 家族已具备、可复用且已验证的资产

| 资产 | 来源 | 状态 |
|---|---|---|
| 变量投影精修引擎（scale+背景 lstsq 解析 / 非线性 LM+scipy-trf / 多起点重启 / 取消钩子） | RutAna `refine/` | ✅ 已验证 |
| 前向模型：倒易基矢 + 全 hkl 枚举 + 结构因子 + LP + Kα1/α2 双线 + March-Dollase | RutAna `profile/` | ✅ 已验证 |
| 峰形：pseudo-Voigt + Caglioti（正确的 tanθ 口径）+ 不对称分裂（split-PV，s=asym/tanθ）+ 经验高角衰减（bfactor） | RutAna `profile/forward.py`（asym/bfactor 在向前模型层） | ✅ |
| TCH 尺寸/应变峰形（X=4ε、Y=Kλ/D） | NCA `profile/size_strain.py` | ✅ NCM811 实样 |
| 背景：Chebyshev + tent（分片线性帽） | RutAna `refine/linear.py` | ✅ |
| R 因子（Rwp/Rp/Rexp/χ²）+ R_Bragg + 相关性矩阵 | RutAna/NCA | ✅ |
| 定量 QPA（Hill-Howard）、占位精修（Li 3a）、原子坐标（O z） | RutAna/NCA | ✅（相专用） |
| 空间群对称元数据（230 号分段 → 晶系/点群/劳厄群/布拉维、H-M→编号全表） | NCA `core/symmetry.py`（依赖 `data/spacegroups.json`；已用 NCA 版替代 LFP 版） | ✅ |
| CIF symop 解析 + 非对称单元展开（`parse_symop`/`expand_symmetry`） | 家族 `cif.py` | ✅ |

> 勾稽：LFP 版 `symmetry.py` 为独立全表（不依赖 `spacegroups.json`），v1 未纳入；若 P1 遇到 NCA 表未登记的符号，再评估并入兜底（不阻塞主线）。

### 2.2 家族引擎的**通用化缺口**（本项目要补的）

| 缺口 | 现状 | 影响 |
|---|---|---|
| **空间群 → symop 生成** | 仅依赖 CIF 显式给出的 symop；CIF 只给 `_space_group_IT_number`/H-M 符号时无法展开；且 H-M 符号存在设置/原点选择差异（如 Pnma↔Pbnm、R-3m 六方↔菱方） | 部分 COD/ICSD CIF 无法精修；设置不匹配会导致展开错误 |
| **全晶胞精修（6 参数）** | 只有四方晶系 a,c 缩放 `_scaled(fa,fc)` | 单斜/三斜/正交等无法精修晶胞 |
| **原子坐标/B 因子通用精修** | NCA 硬编码「O z」「Li 3a」 | 无法对任意相的任意 Wyckoff 位精修 |
| **Wyckoff 位约束** | 无 | 坐标精修不约束位点对称会发散 |
| **参数模型硬编码** | `_pack/_unpack` 写死开关集合 | 无法声明式驱动 GUI/导航/e.s.d./约束 |
| **背景手动插值点** | 只有 Chebyshev/tent | 「精修背景曲线」齿轮弹窗缺用户自定义背景 |

### 2.3 四个开源项目「集百家之长」对照

| 借鉴点 | 来源 | 落到本项目 |
|---|---|---|
| 空间群/对称操作、约束、球谐择优取向、吸收、序贯精修、**多谱联合精修、IRF 仪器参数** | GSAS-II（`GSASIIspc`/`mapvars`/`constrGUI`/`seqGUI`/`Absorb`） | 对称用 spglib；约束/序贯/球谐/吸收/多谱联合/IRF → v2 待办（见 §10） |
| 精修顺序的手动控制、背景手动点、经典 Rietveld 流程、TCH 峰形 | FullProf | 导航式精修的「步骤序列」思想 + TCH |
| 参数面板直观分组、物相/参数树式可操作 | MAUD | GUI 的参数分组面板 |
| 现代化简洁 UI、结构化报告（report.css）、BGMN 参数树 | Profex | 报告格式 + 简洁 UI 基调 |

---

## 3. 总体架构方案

### 3.1 分层架构

```
xinrefinement/
├── core/                      # 算法层：无 I/O、numpy/dataclass、可独立测试
│   ├── io/                    # 谱图读入（vendor Converter）、CIF 解析
│   ├── symmetry/              # 空间群/symop 生成（spglib 封装）+ 家族 symmetry.py
│   ├── structure/             # CifStructure → 全晶胞结构、Wyckoff 位
│   ├── profile/               # 前向模型：结构因子、峰形、择优取向
│   ├── refine/                # 精修引擎：线性层/非线性层/LM/R 因子/相关性/e.s.d.
│   ├── qpa/                   # 定量分析
│   └── params/                # 声明式参数模型（ParameterRegistry）
├── gui/                       # PySide6 MVVM：主窗、图谱、面板、弹窗、导航向导
├── cli/                       # 命令行入口（脚本/批处理）
├── i18n/                      # zh / en / ja
└── data/                      # 内置资源
```

> **落地约定（2026-11-04 实测修正）**：P0 落地时 core 为**扁平结构**（`core/patterns.py`、`core/symmetry.py` 在 core 根）。因 `core/symmetry.py` 是单文件模块（被 16 项测试依赖），同目录不能并存 `symmetry/` 包，故 P1.1 的 symop 生成以扁平 `core/symops.py` 落地、P1.0b 以新建 `core/params/` 子包落地；`io/`、`structure/` 的迁移统一推迟到 P1.0c，避免来回搬文件。上图为**目标分层**，当前实际目录以 `TASKS.md` §2 落地注记为准。

分层纪律（沿用 XinMatch `docs/CONVENTIONS.md`）：core 不读写文件、绝对导入、类型注解、mypy 通过、numpy.float64、pytest+hypothesis、`logging`、**无 GPL 依赖**（双许可兼容）。

### 3.2 关键技术决策

| # | 决策 | 选型 | 理由 |
|---|---|---|---|
| D1 | 语言/GUI | Python 3.10 + PySide6(Qt6) + matplotlib | 家族一致；MVVM；成熟 |
| D2 | 引擎复用 | **vendor 复制** RutAna/NCA 精修核心到 `xinrefinement.core` | 已验证，避免重写数值核心 |
| D3 | 空间群对称 | **spglib**（BSD-3-Clause）生成 symop/找 Wyckoff；保留家族 cif.py 显式 symop 路径兜底 | 230 群全覆盖、商用兼容、免维护大表 |
| D4 | 参数模型 | 声明式 `ParameterRegistry`（替换硬编码 `_pack/_unpack`） | 统一驱动 GUI/导航/e.s.d./约束 |
| D5 | 峰形 | v1 = PV + Caglioti + TCH(尺寸/应变) + η + asym（经验 split-PV，s=asym/tanθ）+ bfactor 高角衰减 + Kα1/α2；split-Pearson VII / FCJ 几何不对称（v2） | 已覆盖主流需求 |
| D6 | 背景 | Chebyshev + tent + **手动插值点** | 满足「精修背景曲线」弹窗 |
| D7 | 择优取向 | March-Dollase（多相，v1）；球谐（v2 可选） | 先保核心 |
| D8 | 定量 | Hill-Howard（v1）；Brindley 微吸收（v2 可选） | — |
| D9 | e.s.d. | 由收敛点雅可比协方差，**并用 Schur 补纳入变量投影消去的线性参数**（scale/背景，含量 e.s.d. 依赖它）；NCA 已有 `corr_from_jacobian` 基础设施 | — |
| D10 | 精修顺序 | 导航式「配方（Recipe）」引擎：有序步骤 + 单步/连跑 + Rwp 监控 | 草图「导航式精修」核心 |
| D11 | 仪器/辐射参数 | λ 与 Kα1/Kα2 比可配置（Cu/Mo/Co、同步辐射任意 λ）；v1 仅 **X 射线**（Cromer-Mann f0）+ **非偏振 LP**；单色器偏振因子、中子（散射长度 b 表 + 独立结构因子 + 磁散射）、TOF 专用峰形均归 v2 | 任意谱图可精修的前提 |
| D12 | 几何 | v1 仅 Bragg-Brentano 平板几何（zero + 样品位移 S·cosθ）；毛细管/透射/平板透明度归 v2 | 最主流实验室几何，先保核心 |

### 3.3 参数模型（声明式，D4）

每个可精修参数注册为统一条目，替代当前硬编码：

```
Parameter {
  key: str                 # "phase0.cell.a" / "global.zero" / "phase0.atom3.B"
  owner: "global"|"phase"|"atom"
  histogram: int|"all"     # 谱图维度（v1 单谱恒为 0/"all"；为 v2 多谱联合精修预留）
  value / bounds / refine(bool)
  group: str               # 导航步骤归属（zero/bg/scale/cell/profile/xyz/B/po/micro）
  esd: float|None          # 收敛后回填
}
```

- **线性参数**（scale、背景系数）仍由 lstsq 解析求解（变量投影不变）。
- **非线性参数**由注册表动态 `pack/unpack` + 边界，喂给自研 LM / scipy-trf。
- 精修开关 = 一组 `group` 的 refine 标记 → 直接映射到导航步骤与齿轮弹窗。
- **预留 histogram 维度**：结构参数（晶胞/坐标/B/occ）跨谱共享（`histogram="all"`），标度/背景每谱独立（`histogram=0,1,…`），为 v2 多谱联合精修铺路，避免日后返工。

---

## 4. 精修参数模型（导航步骤 ↔ 参数）

| 导航步骤（草图顺序） | 参数组 | 归属 | 说明 |
|---|---|---|---|
| ⓿ 仪器/辐射 | `wave`(λ)、`kalpha_ratio`、`polarization`、单色器 | 全局 | 导入/设置时指定（配置项，非步进精修） |
| ① 零点/样品位移 | `zero`（2θ 平移）、`disp`（S·cosθ 位移） | 全局 | 分两档：零点、样品位移 |
| ② 背景 | Chebyshev 阶数 / tent 节点数 / 手动插值点 | 全局 | 线性参数（lstsq） |
| ③ 标度因子 | `scale`（每相 S_p） | 相 | 线性参数（lstsq） |
| ④ 晶胞参数 | `a,b,c,α,β,γ`（按晶系约束） | 相 | 多相分别设置（齿轮弹窗） |
| ⑤ 峰形参数 | `U,V,W,η` + TCH `X,Y` + asym + Kα2 比 | 全局/相 | 尺寸/应变归微结构 |
| ⑥ 原子坐标 | `x,y,z`（按 Wyckoff 位约束） | 原子 | 每相可展开原子表 |
| ⑦ 温度因子 | `B_iso`（各向同性） | 原子/相 | 各向异性 U_ij 为 v2 |
| ⑧ 择优取向 | March-Dollase `r`（+ 惯习面 hkl） | 相 | — |
| ⑨ 微结构/应力/应变 | TCH `X`(应变)、`Y`(尺寸) | 相 | 输出 ε、D(Å) |
| ⑩ 占位 | `occ` | 原子 | 化学约束可选 |

结果区输出：Rwp / Rp / Rexp / χ² / R_Bragg / GOF / 物相含量 / 参数相关性矩阵 / 收敛曲线。

---

## 5. 导航式精修方案（核心 UX）

1. **精修配方（Recipe）**：预置标准顺序（零点→背景→标度→晶胞→峰形→原子坐标→温度因子→择优取向→微结构），与 GSAS-II/FullProf 推荐的精修顺序一致。
2. **两种模式**：
   - 单步执行：点某一步的「执行」按钮，只精修该组参数；
   - 连跑（导航）：按配方顺序逐步精修，每步后自动重估 Rwp，收敛（ΔRwp < 阈值）则进入下一步；任一步可暂停/跳过。
3. **每步的状态**：待精修 / 已精修（显示该步 Rwp 贡献）/ 已跳过。
4. **齿轮弹窗**：每步旁的齿轮打开该参数组的详细设置（见 §6），按钮执行则用当前设置。
5. **步骤快照 / 回退**：每步执行前保存参数快照，可回退到任意历史步骤（撤销/重做），便于对比不同精修策略。

---

## 6. GUI / UX 方案（完善草图）

### 6.1 主窗口布局（三区）

```
┌───────────────────────────────────────────────────────────┐
│ 菜单：File  Edit  Refine  Setting  Help                    │
│ 工具栏：新建 | 导入谱图 | 导入CIF | ▶精修 | 报告导出        │
├───────────────┬───────────────────────────┬───────────────┤
│ 左侧          │  中央：交互式图谱          │ 右侧          │
│ 物相列表      │  实测/计算/残差/峰位棒      │ 导航式精修面板 │
│ (phase1/2…)   │  缩放/框选/相开关          │ 步骤+执行+齿轮  │
│ + 精修参数树  │  峰[放大]区                │ 结果区(R因子等) │
└───────────────┴───────────────────────────┴───────────────┘
```

### 6.2 关键交互（对应草图标注）

| 草图元素 | 落地设计 |
|---|---|
| 每个功能「按钮执行 + 齿轮设置」 | 导航面板每行 = 步骤名 + ▶执行按钮 + ⚙设置弹窗 |
| 「精修背景曲线」 | ⚙ 弹窗：函数类型（Chebyshev/tent/手动点）+ 阶数/节点数 + 曲线上可直接拖拽加背景点 |
| 「晶胞参数修正·多物相」 | ⚙ 弹窗：按导入 CIF 列出所有物相，每相独立勾选 a/b/c/α/β/γ 是否精修 + 边界 |
| 「导航式精修」 | 步骤序列 + 进度/状态指示 + 一键连跑 |
| 「微结构/应力/择优取向」 | 高级参数区：尺寸 D、应变 ε、March-Dollase r 等 |
| 结果区 | Rwp/Rp/Rexp/χ²/含量，附相关性矩阵与收敛曲线 |
| 中央图谱 | 实测(点/线)、计算(线)、残差(底部)、每相峰位棒(不同色)、缩放框选 |

### 6.3 易用性 / 简洁性 / 高效性落地

- **易用**：导航式引导 + 预置配方 + **自动初值估算**（导入谱图+CIF 后自动估 scale/零点/背景/展宽初值）+ 默认值即跑出可用结果；新手无需懂全部参数。
- **简洁**：**新手/专家双模式**切换——新手模式只暴露导航一键 + 必要项，专家模式展开全参数树与全部齿轮弹窗；默认折叠高级参数，避免 GSAS-II 式全参数树轰炸。
- **高效**：精修在后台线程执行（可取消，复用 NCA `cancel_cb`）；前向模型窗口化累加 + 峰枚举缓存已具备；**参数改动即时预览**（改参数→图谱即时重算，不重新精修）。

---

## 7. 分阶段实施路线（可实现、易验收）

> 每阶段独立可验收，P0 先立基线再迭代。验收命令统一用家族 venv：`D:/Project/XRD/python310/python.exe -m pytest -q`。

### 阶段 P0 · 基线冻结（先立基线）

| 步 | 内容 | 验收 |
|---|---|---|
| P0.1 | 仓库骨架：pyproject、`xinrefinement/` 包结构、pytest、mypy、venv、依赖锁定（numpy/scipy/matplotlib/PySide6/spglib） | `pytest` 空跑通过；`import xinrefinement` 成功 |
| P0.2 | vendor 复制 RutAna+NCA 精修核心（refine/profile/qpa/对称元数据）到 `xinrefinement.core`，命名空间重写、测试迁移 | 家族原测试在 `xinrefinement` 下全绿 |
| P0.3 | golden 基线冻结：TiO₂ 虚拟样 8 配比 + NCM811 实样，跑通并冻结 Rwp/含量基线 | 与 RutAna `bench_report_b.md` 数值一致（Rwp 2.1–3.5%） |

### 阶段 M0 · 垂直切片 MVP（✅ 完成 2026-11-04，早于 P1）

> 目的：先用 P0 已 vendor 引擎把「读谱+CIF → solve → CLI 报告」端到端跑通，证明闭环可用，再投入 P1 通用化。M0 产出与 P1.0a 复用（P1.0a 直接升级此 solve）。实施记录见 `docs/TASKS.md` §1.5。

| 步 | 内容 | 验收 |
|---|---|---|
| M0.1 | 最小 `refine.solve(inputs)->SolveResult`（plan 原写 RefineResult，命名 `SolveResult` 以避免与引擎层 `nonlinear.RefineResult` 重名；单相/多相复用现有引擎；能力=zero+背景+scale+峰形 U/V/W/η + 可选 TCH/PO） | 调用 solve 返回 Rwp/参数表/QPA |
| M0.2 | CLI `python -m xinrefinement.cli refine <pattern> <cif> [-o report.{json,txt}]` | 一条命令出 JSON/TXT 报告 |
| M0.3 | 验收：virtual_b v50 双相 Rwp 3.4096%（与 golden 逐位一致）+ QPA <0.5pp | 报告含 Rwp/Rp/Rexp/χ² + 参数表 + 物相 |

**M0 明确不含**：全晶胞（除现有四方 a,c）、通用 xyz/B/occ（→P1）、多相（→P2.5）、Le Bail（→P2.8）、GUI（→P3）。

### 阶段 P1 · 通用化引擎核心（结构精修能力）

> **依赖**：`P1.0a/b/c`（主入口/参数模型）与 `P1.1`（spglib）可**并行**；`P1.2/P1.3/P1.4` 依赖 `P1.0 ∩ P1.1`（需 Wyckoff 位识别）。**前置**：`P1-PRE` 虚拟样合成器是 P1/P2 验收的地基，须先落地（M0 验收可复用 P0 `tests/data/virtual_b`，不阻塞）。

| 步 | 内容 | 验收 |
|---|---|---|
| P1-PRE | **虚拟样合成器 `tools/gen_virtual.py`**：参数化合成已知真值谱（任意晶系/多相/零点/样品位移/背景含弯/PO/尺寸应变/含量/噪声/λ），seed 可复现，冻结 golden 真值 JSON | 合成谱可被引擎读入并回读 seed 真值；为 P1/P2 验收提供地基 |
| P1.0a | 在 M0.1 基础上补齐 `solve(inputs)->SolveResult` 契约与单测（包一层，**不重构** `_pack/_unpack`，补 NCA 未迁 `solve.py` 职责）；命名统一为 `SolveResult`，避免与引擎层 `nonlinear.RefineResult` 重名 | TiO₂ 虚拟样 round-trip 串通；`SolveResult` 契约稳定 |
| P1.0b | `ParameterRegistry` 双轨落地（registry 生成 pack 顺序，与旧 `_pack` 并存逐位对比） | registry 单测（注册/开关/边界/pack-unpack）全绿；与旧 `_pack` 逐位一致 |
| P1.0c | 全面替换硬编码 `_pack/_unpack` + 删除旧路径 | 旧路径 grep 无残留；round-trip 数值不回归 |
| P1.1 | spglib 集成：由空间群编号/H-M 符号生成 symop + 非对称单元展开 + Wyckoff 位识别；保留家族显式 symop 路径 | 全 230 群 symop 数 sanity check + 手验 golden 多重度子集（少量 ICSD 结构人工核对），不引入 pymatgen/GSAS-II 重依赖 |
| P1.2 | 全晶胞精修：a,b,c,α,β,γ 按晶系约束（立方 1 参、四方 2 参、正交 3 参、单斜 4 参、三斜 6 参） | 虚拟样 round-trip 晶胞回收误差 < 0.1% |
| P1.3 | 原子坐标精修：按 Wyckoff 位约束（对称等价坐标联动） | 虚拟样原子坐标回收 < 1e-3 |
| P1.4 | 各向同性 B 因子 + 占位精修 | 与 seed 真值比对：B 回收 ±0.2 Å²、occ ±0.02 内（不依赖 e.s.d.） |
| P1.5 | 参数 e.s.d. 估计（由雅可比协方差） | 输出 e.s.d. 且量级合理 |

### 阶段 P2 · 精修参数模块完备（谱图精修能力）

| 步 | 内容 | 验收 |
|---|---|---|
| P2.1 | 零点 + 样品位移精修（S·cosθ） | 位移虚拟样回收 < 0.005° |
| P2.2 | 背景：Chebyshev/tent/**手动插值点** 三模式 | 含弯背景虚拟样 `Rwp ≤ Rexp×1.10` 且 `χ² ≤ 1.21`（口径见 §8.5；**不得**用"噪声理论 Rwp"这类未定义量） |
| P2.3 | 峰形：Caglioti + TCH 尺寸/应变 + η + asym + Kα2 全开关 | NCM811 实样 Rwp 不劣于 NCA 基线 |
| P2.4 | 择优取向 March-Dollase（多相独立） | PO 虚拟样 r 回收 |
| P2.5 | 标度 + QPA（Hill-Howard 定量） | 多相虚拟样含量回收 < 0.5pp |
| P2.6 | 微结构输出：尺寸 D、应变 ε | 尺寸/应变虚拟样反演误差 < 5% |
| P2.7 | 仪器/辐射参数：波长 λ、Kα1/Kα2 比（Cu/Mo/Co、同步辐射任意 λ；v1 仅 X 射线 + 非偏振 LP，单色器偏振归 v2） | 换 λ 虚拟样峰位正确迁移 |
| P2.8 | Le Bail 模式：无结构强度提取 + 多相定量 | 与对应 Rietveld 强度/含量一致 |
| P2.9 | 精修结果写回 CIF（晶胞/坐标/B/occ） | 写回后 CIF 可用 spglib 重新解析且结构一致 |
| P2.10 | 自动初值估算器：导入谱图+CIF 后自动估 scale/零点/背景/展宽初值 | 无人工初值时一键精修：`Rwp ≤ Rexp + 1pp` 且所有精修参数不触边界、无 `Restarted=true`（阈值明确定义） |
| P2.11 | 真实数据锚点：TiO₂（RutAna）、NCM811（NCA）、LFP、NCA 实样在 `xinrefinement.core` 上跑通 | Rwp/含量与家族基线登记一致 |

### 阶段 P3 · 导航式精修 + GUI

| 步 | 内容 | 验收 |
|---|---|---|
| P3.1 | 主窗口骨架（三区布局 + 工具栏 + 菜单） | GUI 可启动、导入谱图/CIF |
| P3.2 | 交互式图谱（实测/计算/残差/峰位棒/相开关/缩放框选 + **参数改动即时预览**） | 图谱正确渲染并可交互；改参数后图谱即时重算 |
| P3.3 | 导航式精修向导（配方引擎 + 单步/连跑 + Rwp 监控） | 一个虚拟样连跑全程，Rwp 收敛 |
| P3.4 | 按钮+齿轮 设置弹窗（背景/晶胞多相/峰形/原子坐标/温度因子/择优取向/微结构） | 各弹窗改设置后精修结果随之变化 |
| P3.5 | 结果区（R 因子/含量/相关性/收敛曲线） | 结果与 core 数值一致 |
| P3.6 | i18n 三语（zh/en/ja） | 语言切换生效 |
| P3.7 | 工程文件保存/恢复（.xrp：谱图引用+CIF+参数设置+结果+导航状态+历史+步骤快照回退） | 保存→关闭→重开状态完全恢复且结果可复现；可回退到任意历史步骤 |

### 阶段 P4 · 报告 + 验收 + 发布

| 步 | 内容 | 验收 |
|---|---|---|
| P4.1 | 报告导出（PNG/CSV/JSON/HTML，参考 Profex report 结构）+ 精修日志（.lst/JSON：每步参数变化、Rwp 历史、最终参数+e.s.d.） | 导出文件可读、数据完整、可复现 |
| P4.2 | 虚拟样 round-trip 全基准（多晶系×多相） | 全 PASS，误差在阈值内 |
| P4.3 | 真实数据交叉验证：同一谱用 GSAS-II/FullProf/MAUD/Profex 对照 | Rwp/晶胞/含量一致性登记 |
| P4.4 | 打包：PyInstaller 单文件 + Inno Setup（zh/en/ja） | 双击验收 + 5 轮稳健性（哈希/便携/冻结冒烟/静默安装/启动） |
| P4.5 | CLI 批处理入口（`refine --recipe/--report/--quant`） | 无 GUI 环境跑通 TiO₂ 虚拟样并输出报告 |
| P4.6 | 公开库 API 契约 + XinMatch 对接 demo（`xinrefinement.core` 稳定 solve/quant/report 入口 + 版本化约定） | XinMatch 侧可 import 并跑通一个最小精修调用 |

---

## 8. 验收与基准方案

0. **M0 门（前置垂直切片）**：单相虚拟样/实样经 `solve + CLI` 端到端出报告，Rwp 达标且数值与 P0 golden 一致；未过 M0 不进入 P1 通用化。
1. **黄金基线（golden）**：`tests/golden/` 冻结数值，回归比对（RutAna/NCA 沿用）。
2. **虚拟样（round-trip）**：`tools/gen_virtual.py`（seed 可复现）合成已知结构谱 → 精修回收真值。
3. **真实锚点**：TiO₂（RutAna）、NCM811（NCA）、LFP、NCA 家族实样。
4. **交叉验证**：GSAS-II / FullProf / MAUD / Profex 同谱对照；**只比结构量**（晶胞、含量、占位、R_Bragg），Rwp 因背景/峰形/权重实现不同仅登记不硬比；统一同数据、同初始结构、同背景点数。
5. **判定档位**（沿用 RutAna verdict）：Rwp <10% 很好 / 10–15% 良好 / 15–20% 尚可 / >20% 不佳。
   **虚拟样严格档（口径定义，替换原"噪声理论 Rwp"这一未定义量）**：泊松计数噪声下
   `Rexp = 100·√((N−P)/Σ w·y_o²)` 即理论最小 Rwp（完美模型 χ²=1）。验收统一用
   **`Rwp ≤ 1.10·Rexp` 且 `χ² ≤ 1.21`**（`χ²=(Rwp/Rexp)²`）；`rwp_noise_theory`
   由 `tools/gen_virtual.py` 冻结进 `*_truth.json`（P=0 上界估计）供对照。
6. **性能基准（量化门槛）**：大谱 `10⁴ 点 × 5 相 × 100 参数`，单次精修
   **≤ 30 s、峰值内存 ≤ 1.5 GB**（家族 venv / 本机基准机）；另登记 `10³ 点 × 2 相`
   常规谱 **≤ 3 s**。超出门槛须给出 profile 报告并在 P4 优化，不静默放过。
7. **数值稳健性**：病态矩阵/发散保护/多起点重启在新参数（晶胞/坐标/B/PO）上的边界回归（hypothesis）。
8. **草图逐条核对**：P3 GUI 交付时，截图对照 `pre-temp/0.jpg` 逐条打钩（按钮+齿轮/背景曲线/多物相晶胞/导航式），避免 UI 与草图构想脱节。
9. **残差统计**：结果区输出 Durbin-Watson（DW）统计量；权重方案可选（默认 1/σ² Poisson，可切 1/y）。

---

## 9. 风险与待确认问题

### 9.1 风险

| 风险 | 缓解 |
|---|---|
| 空间群对称实现复杂度 | 用 spglib（BSD），不自研 230 群表；家族 cif.py 兜底 |
| 坐标精修发散 | Wyckoff 位约束（site symmetry 零空间法定自由坐标）+ 边界 + 先晶胞后坐标的顺序 |
| 多相强重叠精修不稳定 | 变量投影 + scipy-trf + 多起点重启（已有） |
| GUI 与 core 耦合 | MVVM + core 无 I/O，参数模型声明式 |

### 9.2 已拍板决策（2026-11-04 用户确认）

| # | 决策项 | 拍板结果 |
|---|---|---|
| 1 | 技术栈 | ✅ PySide6(Qt6) + Python 3.10 + spglib |
| 2 | 引擎复用 | ✅ vendor 复制（自包含，家族惯例） |
| 3 | 与 XinMatch 关系 | ✅ 独立 GUI 应用，核心层预留 import 接口 |
| 4 | v1 范围 | ✅ March-Dollase + Hill-Howard + 背景三模式；球谐 PO / Brindley / 各向异性 U_ij 留 v2 |
| 5 | spglib 依赖 | ✅ 同意安装 |
| 6 | 报告格式 | ✅ 参考 Profex 的 HTML 报告结构 |

> 决策已固化，进入实施。产出原子级 `docs/TASKS.md`，按 P0→P4 顺序推进。

---

## 10. v2 待办（明确延后，不阻塞 v1）

> v1 已在 D4 参数模型**预留 histogram 维度**（见 §3.3），为「多谱联合精修」铺路。

| 能力 | 说明 | 触发条件 |
|---|---|---|
| 序贯精修（Sequential） | 多谱图/温度/原位/时间分辨批处理，全局参数共享 | GSAS-II 对标，用户有多谱图需求 |
| 多谱联合精修（Joint） | XRD+中子/多台仪器/多温度点**联合拟合同一结构**（histogram 维度） | 需要多谱互补定结构（如轻元素占位） |
| 参数硬约束框架（equality/linear/coupling） | 对标 GSAS-II `mapvars`：参数等式约束、线性组合、跨相共享、固定比例 | 复杂结构/多相共享参数 |
| 键长/键角/原子间距/软约束（restraints/penalty） | 结构精修稳定性的进阶约束 | 复杂结构/低分辨谱出现发散 |
| IRF 仪器参数文件 + 标样标定 | FullProf `.irf` / GSAS-II instrument parameter file + LaB6/Si 标样标定零点/展宽 | 需严格仪器展宽函数 |
| 各向异性峰宽（尺寸/应变） | Stephens 各向异性应变、Popa/球谐各向异性尺寸、位错展宽 | 各向同性 TCH 不足以描述峰宽 |
| 球谐择优取向（hp spherical harmonics） | 替代 March-Dollase 的通式 | M-D 不足以描述的强取向 |
| 无定形/非晶含量（内标法） | 加内标（刚玉/ZnO）定无定形相与非晶含量 | 电池材料等含无定形相 |
| Brindley 微吸收校正 | 定量精度的进阶 | 含重元素吸收差异 |
| 各向异性温度因子 U_ij | 高对称性破坏/高 Q 数据 | 需要各向异性温度模型 |
| 消光 + 透射吸收校正 | extinction/absorption/transmission | 强散射/透射几何数据 |
| 中子数据（恒定波长/TOF） | 散射长度 b 表 + 独立结构因子（磁散射可选）+ TOF 峰形（Ikeda-Carpenter/back-to-back） | 中子数据 |
| FCJ 几何不对称（Finger-Cox-Jephcoat） | 样品高度/衍射仪几何尾模型，替代经验 split-PV | 强不对称/低角数据 |
| 异常散射 f′/f″ | 同步辐射近吸收边色散校正（Cromer-Mann 仅 f0） | 同步辐射/近边数据 |
| 偏振/单色器校正 | LP 偏振因子（当前为非偏振 `(1+cos²2θ)/(sin²θcosθ)`） | 单色器/同步辐射偏振数据 |
| 几何扩展（毛细管/透射/平板） | Bragg-Brentano 之外的位移/吸收/透明度模型 | 毛细管/透射几何数据 |
| 多核并行 | 多相峰枚举/多起点重启并行化（P4 性能基准后再评估） | 大谱/多相性能瓶颈 |
| 谱图格式扩展 | Panalytical `.xrdml/.udf`、Rigaku、MAUD `.ins/.esg`、FullProf `.dat/.pcr`、标准 `.cif` 粉谱、Bruker `.raw/.ras`、GSAS 等 | 用户带来新格式 |
