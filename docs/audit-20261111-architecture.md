# XinRefinement v1.6.2 全局代码审视报告（架构师视角）

| 项 | 值 |
|---|---|
| 审视对象 | `D:/XinRefinement`，git HEAD `e6ddef3`，工作树干净 |
| 版本 / 规模 | v1.6.2；源码 72 个 `.py` / 18980 行，测试 57 个 `.py` / 8785 行 |
| 基线（文档权威值） | 532 passed / 0 skipped；golden CLI Rwp = **3.4074156640940005** |
| 基线（本机实测） | `python -m pytest -o addopts="" --basetemp=<新临时目录> -q` → **1 failed / 525 passed / 6 skipped / 775 warnings，481.53 s，EXIT=1**（主理人侧执行；QA 任务 #2 独立复现诊断，本审视不重跑） |
| 环境 | Python 3.10.11 / `.venv/Scripts/python.exe`；numpy 2.2.6 / scipy 1.15.3 / matplotlib 3.10.9 / PySide6 6.11.2 / spglib / pytest 9.2.0；**本机缺 `gemmi` / `pymatgen` / `CifFile`** |
| 审视性质 | **只读分析**。除本报告外未写入、未修改、未 git add/commit 任何文件 |
| 报告日期 | 2026-11-11（含主理人侧两条补充线索的补充修订；任务边界不变，仍只允许写本报告一个文件） |

---

## 摘要

### 关键发现

1. **数值主链本身是稳的，问题集中在「旁路 / 双轨 / 序列化 / 界面状态」四处**。核心链（读入 → 注册表 → 前向 → LM → 配方 → solve）经过多轮 golden 保护，本轮未发现任何需要动优化器、峰形、权重、配方默认值或参数打包顺序的问题；交接单里已判负的 M5/M6/M7、只适用样 7 的 M8、已产品化的 M4 均不重复建议。
2. **双轨参数系统已经断裂（已用只读脚本硬证实）**：生产走 `ParameterRegistry`，legacy `_pack/_unpack/_bounds` 保留作「兼容 API + 双轨回归参照」。在 `refine_size_strain=True` 下 registry 产 6 维、legacy 仅 4 维；且 legacy `_unpack` 重建 `ProfileParams` 时**漏搬运 `size_strain`**（`_unpack` → `None`，`registry.unpack` → 原值保留）。`width_basis` 当年补过，`size_strain` 是同一类残留。
3. **`CifStructure` 有一条元数据仍未纳入搬运清单（已硬证实）**：`cell.py:_CELL_META` 与 `recipe.py:_run_xyz` 的继承元组都覆盖题目点名的 `z_declared/n_asym/n_sym_ops/source_path`，但都**漏 `name_mineral`**。实证：`structure_with_cell()` 后 `phase_label(st,"label")` 从 `Quartz` 退化为 `SiO2`。这是纯显示字段，零数值风险，是本轮最干净的修复项。
4. **序列化往返存在精度损失**：`.xinr` 内嵌谱图与 `.xinm` 中转谱图统一用 `%.10g`（10 位有效数字）写出，float64 需 17 位；保存/重开后谱图不再逐位相等。另有 `api.report()` 与 `api.refine()` 对同一 `RefineRequest(refine_po=True)` 使用**不同** `RefineConfig`（前者漏 `refine_po`）。
5. **GUI 有两处明确的主线程阻塞**：工具栏「▶精修」同步跑 `solve()`；`estimate_esd()`（内含约 4p 次全谱前向）在结果填充 / 保存工程 / 导出报告三处各算一次且都在主线程。二者都是真实问题，但修它需要重设计测试契约或缓存生命周期，**本轮明确不动**。
6. **交接线索里有若干「已符合」项，已逐条核实、不照抄成结论**：三处残差闭包取消检查点 + 配方 7 处兜底透传、状态栏 `addPermanentWidget`、视图层操作不进结果表/报告/拟合、内部键恒为 `CifStructure.name`、配方层重建继承 4 字段、i18n 三语 141 键完全对齐（**无 i18n 缺键**）。详见第 5 节。
7. **本机基线并不绿，但根因是「测试环境可移植性 + 一处测试时序假设」，不是引擎/数值缺陷**（主理人侧实测 `1 failed / 525 passed / 6 skipped / 775 warnings，481.53 s，EXIT=1`，与文档权威值 `532 passed / 0 skipped` 有差距）。唯一失败 `test_v162_cancel.py::test_run_all_does_not_record_cancel_as_failure` 的 `assert records` 拿到 `[]`：源码级证据链指向**墙钟谓词 `> 0.15s` 与「记录非空」绑定的时序假设脆弱**（第 2.4 节给出架构判断：产品「停在已完成的最后一步」语义未被破坏）；6 skip 可静态归因于 COD 档案硬编码绝对路径 + 缺 XinMatch/gemmi（C10）；775 warnings 来自 spglib API 弃用（C11）。**特别区分**：`test_golden_b.py:27-29` 的 golden 活体绊线不依赖 gemmi，本机仍执行并通过，**不可误判为「golden 未校验」**。三项均不进入 F 短名单，也不建议装包/放宽断言绕过。

### 落地物

- 本报告：`docs/audit-20261111-architecture.md`（仓库内唯一新增文件）。
- **A 类正确性 15 条 / B 类性能 7 条 / C 类可维护性 11 条**，共 33 条，每条附 `文件:行号`、触发条件、影响、建议改法、风险、是否改变数值结果；其中 4 条附只读脚本实测输出作为硬证据。另设第 2.4 节，对基线唯一失败给出源码级架构判断（含 6 行证据链表）。
- **本轮建议修复 6 项**（F01–F06，不扩充），全部满足「golden 逐位不变 / 风险低 / 改动面小 / 有明确验收」；给出精确改动点与验收用例。补充审视的 A15/C10/C11 均不进入短名单，理由见第 3 节。
- **明确不建议本轮动的 15 类项**，逐条给理由（含新增两条：不为凑 0 skipped 装包/放宽断言、不改 `run_all` 取消语义或测试断言来「修绿」基线）。

### 下一步

1. 由 QA 按第 2 节 `文件:行号` 逐条复核，并设计 F01–F06 的复现/回归用例（任务 #2）。
2. 由 Engineer 实施 F01–F06（任务 #3），每处均为 1–4 行、纯旁路与元数据/显示/序列化改动，不触碰任何数值函数。
3. 全量回归 + golden 复验（任务 #4）：以**同一台机器、同一环境**的修复前实测基线（`1 failed / 525 passed / 6 skipped / 775 warnings`）为对照，确认 F01–F06 后「无新增失败、无新增 skip」，golden CLI Rwp 逐位等于 `3.4074156640940005`，`git status --short` 除本报告外零改动。基线红灯的定性由 QA 任务 #2 给出，**不通过装包或放宽断言消除**（文档权威值 `532 passed / 0 skipped` 属另一档「全能力基线」，二者差异见第 2.4 节 / C10）。

---

## 0. 审视范围与方法

- **清点**：`Glob xinrefinement/**/*.py` = 72 个文件；`wc -l` = 18980 行；`tests/**/*.py` = 57 个 / 8785 行；与交接数据一致。`git status --short` 为空、HEAD `e6ddef3`。
- **全量模式扫描（覆盖 72/72 文件）**：`except`（含 `pass`/静默降级）、`.copy()/np.asarray/read_text/read_bytes/open`、`.10g` 精度、TODO/FIXME、`_check_cancel`、`_pack/_unpack/_bounds/size_strain`、`tr()` 字面键、模块引用关系等，共 10+ 组 Grep。
- **完整精读（24 个文件，约 1.1 万行，覆盖全部核心链路）**：`api.py`、`__init__.py`、`registration.py`、`core/dtypes.py`、`core/patterns.py`、`core/params/registry.py`、`core/profile/forward.py`、`core/refine/{recipe,cell,solve,nonlinear,esd,optimizers,plan,linear}.py`、`core/report.py`、`core/io/xinm_import.py`、`i18n/{__init__,catalog}.py`、`gui/{main_window,canvas,workers,project}.py`、`cli/refine.py`。
- **定向 Read 核实行号**：`core/profile/cif.py`、`core/symops.py`、`core/vendor/text_formats.py`、`core/refine/site.py`、`gui/dialogs.py` 等。
- **只读校验脚本 4 次**（`python -B -c`，禁用字节码、不写任何文件）：① 三语键集合对比；② `_unpack`/`registry.unpack` 的 `size_strain` 往返；③ registry/legacy 在 `refine_size_strain` 下的维度；④ `structure_with_cell` 的元数据搬运与 `FORMAT_LABELS` 悬空引用。
- **补充审视（主理人侧两条线索）**：定向 `Read`/`Grep` 新增覆盖 `tests/test_joint_s1.py`、`tests/test_golden_b.py`、`tests/test_v162_cancel.py`、`tests/test_cif_robust.py`、`tests/test_xinm_import.py`、`tests/test_recipe.py`、`xinrefinement/core/symops.py`、`xinrefinement/gui/workers.py`、`xinrefinement/core/refine/recipe.py:919-970`、`pytest.ini`/`pyproject.toml`，并全仓核实 `run_all(` 的全部调用点（生产仅 `tools/` 下 14 处 bench/eval，其余在 `tests/`）。**未重跑 pytest**：基线数值与失败名均引自主理人侧实测，QA 任务 #2 独立复现诊断；本审视只做源码级归因与架构判断。
- **未做**：未修改任何 `.py`/测试/配置/既有文档，未 `git add/commit/push`，未访问工作目录之外的数据目录，未读取 PolyXRD/XinMatch 等其它项目，未运行会改变 golden 的数值实验，未安装任何依赖包。

---

## 1. 架构总览

### 1.1 端到端调用链

```
[谱图 .xy/.raw/.xrdml/... ]  core/patterns.py::load_pattern
        ├─ 旧四格式 → _parse_two_column / _parse_pd（v1.5 golden 行为）
        └─ 其余 → core/vendor/{text_formats,raw_formats,model}.py → XRDData
                                   ↓
[CIF] core/profile/cif.py::parse_cif → CifStructure（name/cell/atoms + symops 展开
      + spacegroup/sg_number/formula/z_declared/name_mineral/source_path）
[.xinm] core/io/xinm_import.py::read_xinm → XinmPayload
[.xinr/.xrp] gui/project.py::load_project → 会话目录解压 + manifest
                                   ↓
              core/dtypes.py::Pattern（frozen，校验 1-D / 等长 / 严格升序）
                                   ↓
        参数载体 core/profile/forward.py::ProfileParams（frozen dataclass, 21 字段）
        参数注册表 core/params/registry.py::ParameterRegistry
            └─ build_registry_from_config(cfg, prm, n_phase, po_names)
               slots → pack / unpack / bounds / groups / set_esd
               （生产唯一路径；与 legacy nonlinear._pack/_unpack/_bounds「双轨」）
                                   ↓
    core/refine/solve.py::solve(RefineInputs) → SolveResult
        ├─ _clip_to_window / _resolve_interp_bg / _resolve_theoretical_sigma
        ├─ _resolve_texture / _resolve_aniso / _resolve_biso（一次性，不进热路径）
        ├─ QPA：core/refine/qpa.py::qpa_weights（Hill–Howard）
        └─ 引擎 nonlinear.refine → RFactors / PhaseInfo / history / engine
                                   ↓
    前向 core/profile/forward.py::compute_phase_profile
        ├─ _peaks_with_po → _phase_peaks（_PEAKS_CACHE，键含 id(struct)+_variant，上限 256 全清）
        ├─ core/profile/struct.py::compute_peaks（|F|²·LP，symops 展开）
        ├─ core/profile/shape.py（pseudo-Voigt、March–Dollase、Kα1/α2 波长）
        ├─ core/profile/size_strain.py::split_fwhm（TCH）
        └─ _accumulate_peaks（±8·FWHM 窗口化）→ _apply_microabs（Brindley）
                                   ↓
    优化 core/refine/nonlinear.py::refine
        ├─ _build_residual（变量投影残差闭包，_check_cancel 在入口）
        ├─ core/refine/optimizers.py::minimize（lm / trf / dogbox 查表）
        ├─ core/refine/lm.py::lm_minimize（数值雅可比 LM）
        ├─ core/refine/linear.py::solve_linear_detail（lstsq 解 scale + 背景）
        └─ core/refine/rfactors.py::compute_rfactors
                                   ↓
    配方 core/refine/recipe.py::RecipeRunner（DEFAULT_STEPS 8 步）
        ├─ config_for（按步翻译开关；profile 步强制开 refine_cell/refine_zero/asym）
        ├─ cell 步 → core/refine/cell.py::refine_cell_full（3 次 solve，独立残差闭包）
        ├─ xyz 步 → core/refine/site.py::refine_sites（独立残差闭包，重读未展开 CIF）
        ├─ micro 步 PO 试探 / 墙钟护栏 / Rwp 不改善即回退 / 快照
        └─ 取消：_with_cancel + _reraise_if_cancelled（7 处兜底）
                                   ↓
  ┌───────────────┬──────────────────────────┬─────────────────────────────┐
  │ GUI            │ CLI                      │ Library API / 报告           │
  │ main_window.py │ cli/refine.py::_run      │ api.py::refine/quant/report  │
  │  → workers.py  │  → to_report/to_text     │ core/report.py::export_report│
  │    RefineWorker│  → core/report.py        │   HTML + PNG + JSON         │
  │    (QThread,   │  → core/refine/esd.py    │ core/refine/diagnostics.py  │
  │     6 Signal)  │    core/refine/polymorph │ core/refine/esd.py (Schur)  │
  │  → canvas.py   │  → cli/__main__.py       │ core/refine/corr.py         │
  │    dialogs.py  │                          │ gui/project.py::save_project │
  │    project.py  │                          │   → result/refine.json      │
  └───────────────┴──────────────────────────┴─────────────────────────────┘
```

### 1.2 关键模块边界

| 边界 | 约定 | 证据 |
|---|---|---|
| core 不碰 Qt | 配方引擎、报告、e.s.d. 均在 core，PySide6 只在 `gui/` 与 `registration.py` 延迟导入 | `recipe.py:1-10`、`report.py:1-8`、`registration.py:276-291` |
| solve 不读写文件 | 谱图/CIF 由调用方 `load_pattern`/`parse_cif` 负责 | `solve.py:13-16` |
| 只读契约对象 | `Pattern`/`ProfileParams`/`RefineConfig`/`SolveResult` 全部 frozen dataclass，改动一律 `dataclasses.replace` | `dtypes.py:16`、`forward.py:157`、`nonlinear.py:118`、`solve.py:41,66` |
| 视图层 ↔ 结果层 | canvas 的轴切换/缩放/背景点选/标记条只改画布自身状态，或经信号写 `_settings`；结果表由 `_fill_results` 只读 `self._result` 回填，不反向写结果 | `canvas.py:279-300,536-568,889-948`、`main_window.py:315-321,1620-1653` |
| 内部键 ↔ 显示名 | `CifStructure.name` 是 `po_r/texture/aniso/b_iso/size_strain`、QPA、画布显隐的唯一键；`core/profile/naming.py::phase_label` 只产展示文案 | `main_window.py:958-960,989-996,1064-1067`、`canvas.py:230-242` |
| GUI 默认 ≠ CLI/API 默认 | GUI `_make_inputs` 出厂 `aniso_auto=True`、`po_probe=True`、`bg_mode="tent"`；CLI/API 默认关以保 golden | `main_window.py:1233,1244,1253`、`cli/refine.py:41-42`、`api.py:82-85` |

### 1.3 耦合点 / 易回归面

1. **双轨参数系统**（`registry.py:237-334` ↔ `nonlinear.py:294-515`）：注释明确要求「逐位一致」，由 `tests/test_registry.py` 参数化断言。新增参数组只改一侧就会断裂 —— 本报告 A02 即实证。
2. **`ProfileParams` 字段手工搬运**（`nonlinear.py:446-456`、`_restart_points:748-761`）：每次重建都要显式列出全部字段；`width_basis` 已补（`:453`），`size_strain` 漏（A01）。
3. **取消通道三处残差闭包 + 7 处兜底**：`nonlinear.py:687`、`cell.py:295`、`site.py:333`（另 `nonlinear.py:895` 最终合成前）；`recipe.py` 7 处 `except Exception` 均先 `_reraise_if_cancelled`（`:331,389,456,642,665,748,819,867`）。任一处漏接都会让「停止」退化或把取消记成 failed。
4. **两条结构重建路径**：`cell.py::structure_with_cell`（`_CELL_META` 7 字段）与 `recipe.py::_run_xyz`（4 字段 + `site.py::to_structure` 回填 formula/spacegroup/sg_number）。二者字段集合不同，`name_mineral` 两边都漏（A03）。
5. **两套报告 JSON schema**：`cli/refine.py::to_report`（`:322-379`）与 `core/report.py::_log_dict`（`:52-76`）字段命名/覆盖范围不同，后者经 `solve_result_dict` 写入 `.xinr`（C06）。
6. **三套同名 `tr()`**：`i18n/__init__.py:13`（三语）、`core/vendor/text_formats.py:73`（本地错误格式化）、`registration.py:134`（模块自包含）。静态扫描容易把 `err.*` 误判成 i18n 缺键（C09）。
7. **取消信号的双通道**（`recipe.py:932,941-943` ↔ `core/refine/nonlinear.py:592-597`）：`run_all` 步边界检查读自己的 `cancel_cb` 形参（`:942`），引擎残差检查点读 `inputs.config.cancel_cb`；`_with_cancel`（`:84-92`）把形参挂到 config，因此「两个入口都传」才两处都覆盖。`test_v162_cancel.py:119` 只挂 config 一侧 → 步边界检查被禁用，取消只能落在首次残差（A15 / 第 2.4 节）。生产 GUI 不用 `run_all`（`workers.py:96-115` 自建步循环），故该耦合只在库/工具/测试路径暴露。
8. **测试基线的双档口径**（第 2.4 节、C10）：文档权威值 `532 passed / 0 skipped` 隐含「本机 COD 档案 + XinMatch/gemmi 齐全」；仓库自足档在本机为 `1 failed / 525 passed / 6 skipped`。二者不可互相替代作为回归判据，否则会把环境差异误读成代码回归。

---

## 2. 问题清单

> 风险＝实施该建议的技术风险（不是缺陷严重度）。「改数值」列指**该缺陷本身/其修复**是否会改变数值结果；所有建议修复项均保证 golden 逐位不变。

### 2.1 A 类 · 正确性缺陷

| 编号 | 文件:行号 | 触发条件 | 影响 | 建议改法 | 风险 | 改数值 |
|---|---|---|---|---|---|---|
| **A01** | `core/refine/nonlinear.py:446-456` | 调用 legacy `_unpack(x, base, cfg, n)`，且 `base.size_strain` 非空（逐相 TCH 展宽）；`tests/test_registry.py:92` 等双轨参照即此路径 | 重建出的 `ProfileParams.size_strain` 变 `None`，逐相 (X,Y) 展宽静默失效；registry 路径不受影响，双轨结果不同步。**实测**：`legacy _unpack -> None`，`registry.unpack -> {'foo': (0.1, 0.2)}` | 在 `ProfileParams(...)` 构造中补 `size_strain=base.size_strain` | 低 | 否（生产走 `reg.unpack`，见 `nonlinear.py:894,869`） |
| **A02** | `core/params/registry.py:325-331` ↔ `core/refine/nonlinear.py:294-350,460-515` | `RefineConfig(refine_size_strain=True)` 下比较 registry 与 legacy | registry 有逐相 2 维槽位、legacy `_pack/_bounds` 完全无该分支；**实测** `legacy _pack 4 维 / registry.pack 6 维`，`_bounds 4 / 6`，registry labels 含 `phase[foo].micro.X/Y`。`test_registry.py` 声称的「逐位一致」在该开关下不成立（参数化用例未覆盖此开关＝测试盲区） | legacy 补对应分支，或在文档/测试中显式声明 legacy 不支持该开关并加保护断言 | 中 | 否（生产走 registry） |
| **A03** | `core/refine/cell.py:169-170,173-184`；`core/refine/recipe.py:655-658`；字段定义 `core/profile/cif.py:180` | CIF 含 `_chemical_name_mineral`，GUI 选「物相名称」显示口径，且走过 cell 步 / xyz 步 / CLI 晶胞回写（任一 `structure_with_cell`） | `_CELL_META` 与 xyz 继承元组均漏 `name_mineral`；**实测** `'Quartz' → None`，`phase_label(st,'label')` 由 `Quartz` 退化为 `SiO2`。多型同化学式时 `_disp_unique` 区分信息随之丢失 | 两处各加 `name_mineral`（`_CELL_META` 与 `for attr in (...)`） | 低 | 否（纯展示字段，QPA/峰强/晶胞均不读） |
| **A04** | `xinrefinement/api.py:82-85` ↔ `:130-131` | `RefineRequest(refine_po=True)` 时对比 `api.refine()` 与 `api.report()` | `refine()` 的 `RefineConfig` 带 `refine_po=request.refine_po`，供 report 复用的 `_solve_raw()` 漏该字段（默认 False）；两个公开入口对同一请求给出不同精修配置/结果 | `_solve_raw` 的 `RefineConfig(...)` 补 `refine_po=request.refine_po` | 低 | 否（默认 `refine_po=False` 路径逐位不变） |
| **A05** | `gui/project.py:133-134,218`；`gui/main_window.py:711` | 保存并重新打开 `.xinr`（`embed=True`），或导入 `.xinm` | 谱图以 `%.10g` / `:.10g`（10 位有效数字）写出，float64 需 17 位；`_load_zip` 再 `float()` 读回（`project.py:213-214`）。保存/重开后 `two_theta`/`intensity` 与原谱不再逐位相等，重开后 Rwp 可能微漂 | 3 处改 `%.17g` / `:.17g` | 低 | 否（golden 为 CLI 路径，不经 `.xinr`/`.xinm`） |
| **A06** | `gui/project.py:287` | 每次 `load_project()` | `head = p.open("rb").read(2)` 未 `with`/`close`；句柄释放依赖 CPython 引用计数即时回收，Windows 上可能短暂占用文件，非 CPython 或异常路径下延迟 | `with p.open("rb") as fh: head = fh.read(2)` | 低 | 否 |
| **A07** | `gui/project.py:179-184`；`gui/main_window.py:705-707` | 反复打开不同 mtime 的 `.xinr`，或多次导入 `.xinm` | 会话解压目录按 `f"{stem}_{mtime}"` 建在 `tempfile.gettempdir()`，注释称「会话级复用」，但**从不清理**；内嵌谱图/CIF 长期驻留磁盘并无限累积 | 需设计清理时机（退出/会话/容量上限）与并发安全 | 中 | 否 |
| **A08** | `gui/project.py:238-244` | `.xinr` 内 `result/refine.json` 损坏（UTF-8/JSON 错误） | `except (UnicodeDecodeError, json.JSONDecodeError): result_full = None`，不写入 `missing`，界面按「无完整结果」静默恢复，用户无提示 | 追加一条 `missing`/警告文案 | 低 | 否 |
| **A09** | `cli/refine.py:491-508`（对照 `core/report.py:161-162` 有 `mkdir`） | `xinrefinement refine ... -o <不存在目录>/report.json` | `out.write_text(...)` 前未建父目录 → 抛 `FileNotFoundError` traceback（退出码非 2，无友好提示） | 写文件前 `out.parent.mkdir(parents=True, exist_ok=True)` | 低 | 否 |
| **A10** | `cli/refine.py:355-358` | `--texture-model harmonic` 精修后 `-o report.json` | `to_report` 的 `parameters.texture` 只写 `axis` 与 `grid`；球谐 entry 无 `grid`，故 `model`/`degree`/`coeffs` 全部丢失，报告里织构结果为 `{"axis":[...],"grid":[]}`，无法还原 | 补 `model`、`degree`、`coeffs`（`coeffs` 用 `_round_list`） | 低 | 否 |
| **A11** | `cli/refine.py:429-441`（`EsdResult` 定义 `core/refine/esd.py:50-63`） | `--esd --format txt` | `_esd_section` 用 `for lab, v, e in zip(esd.labels, esd.esd, esd.esd)`：表头写「参数 / 值 / e.s.d.」，但 `v` 与 `e` 是同一个 e.s.d. 值，`EsdResult` 根本不带参数值 → 「值」列显示 e.s.d. 本身 | 去掉「值」列改为两列，或把参数值列表传入 | 低 | 否（仅文本表格） |
| **A12** | `gui/main_window.py:1453-1460`（对照 `:530-533` 的 `retranslate`） | 切换到 `en`/`ja` 后执行任一步骤精修（单步或连跑） | `_on_step_finished` 用 `STEPS` 的**硬编码中文** `title` 重设按钮文本，而 `retranslate()` 用 `tr(f'step.{step}')`；该按钮退回中文，与其余已翻译按钮语言混杂 | 改用 `tr(f'step.{key}')`（`:1456` 的 `title` 仍可用于日志，日志本就中文） | 低 | 否 |
| **A13** | `core/profile/cif.py:370-381` | CIF 中某条对称操作表达式超出 `parse_symop` 支持范围而抛异常 | `except Exception: pass` 静默丢弃该 symop → `expand_symmetry` 展开不完整 → |F|²、相对强度、QPA 静默错误且不报错。同文件 `:199-202` 的注释正是强调「静默出错」的危害（针对 `_to_float`），此处同类问题未收敛 | 至少记录告警/跳过原因，或改抛带上下文的 `ValueError` | 中 | 是（异常路径下改变结构展开；正常路径不变） |
| **A14** | `core/refine/optimizers.py:91-94`（对照文件头 `:12`）；`gui/main_window.py:588-604,1059-1060,1487-1490,1582-1583,1633-1638,1810-1813`；`core/refine/esd.py:226`；`core/refine/solve.py:123-133`；`core/refine/cell.py:70-77`；`gui/dialogs.py:210-214`；`core/refine/recipe.py:904-910` | 相应子步骤抛异常 | 一批 `except Exception` 静默降级：`backend=trf` 时 scipy 导入失败静默回退自研 LM（**用户指定优化器被替换、Rwp 完全不同、无提示**，且与文件头「只有配置错误才抛」矛盾）；保存工程时 `result_full` 静默置 `None`；峰棒/背景曲线/e.s.d./QPA/晶系判定失败静默给空值或 0 | 按类型收窄捕获；至少把降级写进 `warnings`/日志/状态栏 | 中 | 部分：优化器回退会改变数值；其余否 |
| **A15** | `tests/test_v162_cancel.py:112-123`（失败断言 `:120`，谓词 `:116-117`，`t0` 在 `:114`）；源码 `core/refine/recipe.py:919-970`（步边界 `:941-943`、捕获 `:960-963`、返回 `:970`）、`:387-395`（`run_step` 追加记录 `:394`）、`:84-92`（`_with_cancel`）、`:73-81`（`_reraise_if_cancelled`）；引擎 `core/refine/nonlinear.py:583-601,687`；产品对照 `gui/workers.py:96-128` | 本机全量回归**唯一失败**：`cancel()` 是墙钟谓词 `time.monotonic()-t0 > 0.15`，`t0` 早于 `_inputs()` 的 `load_pattern` + 2× `parse_cif`（`test_v162_cancel.py:41-49`）；且回调**只挂 `inputs.config.cancel_cb`、未作为 `run_all` 的 `cancel_cb` 形参传入**（`:119`）→ 步边界检查 `:942` 被禁用。当 `t0` 到首次残差评估耗时 > 0.15 s（本机 481.53 s 全量重负载下易触发），`nonlinear.py:596-597` 在**第一步第一次残差**即抛 `RefineCancelled`；`run_step` 在追加记录前先 `_reraise_if_cancelled`（`recipe.py:390`），`run_all:960-963` 直接 `break` → `records == []`，`assert records` 失败 | 基线 `EXIT=1`；**不是数值缺陷、golden 逐位不受影响**。**架构判断：主要是测试时序假设脆弱，非产品语义缺陷**——`run_all:961-963` 契约即「停在**已完成**的最后一步」，零完成步返回空记录与之相符；GUI 路径不调 `run_all` 且对 `result is None` 已有明确文案（`workers.py:126`）。完整证据链与判断见第 2.4 节 | 由 QA 任务 #2 独立复现定性；若确认属时序脆弱，方向是让谓词与机器速度解耦（同文件 `:56-58,102-104` 已用确定性调用计数），属测试契约设计决策；**本轮只读，不改代码/测试/配置，不放宽断言** | 中 | 否 |

### 2.2 B 类 · 性能瓶颈

| 编号 | 文件:行号（代码证据） | 触发条件 | 影响 / 量级 | 建议改法 | 风险 | 改数值 |
|---|---|---|---|---|---|---|
| **B01** | `gui/main_window.py:1601-1610` `res = solve(inputs)` 在主线程同步执行；对照 `:1408-1434` 已用 `RefineWorker(QThread)` | 点击工具栏「▶精修」 | 全谱拟合几十秒～分钟级，UI 完全冻结、无进度、无法取消。同一操作在导航单步/一键连跑已异步化，属明显不一致。**量级**：与配方连跑同一计算量（GUI 出厂预算 45 min，`recipe.py:66`） | 迁到 worker；但注释明确「同步，保留脚本/测试契约」，需重设计 | 高 | 否（但改动面大、破坏测试契约） |
| **B02** | `gui/main_window.py:1633-1635`（`_fill_results`）、`:591-595`（`project_state`）、`:1810-1813`（`export_report`）各调一次 `estimate_esd`；`core/refine/esd.py:142` `j_red=_num_jacobian(...)`、`:155` `jf=_num_jacobian(ycalc_fixed,...)`，每个 `_num_jacobian` 为 2p 次全谱前向（`:71-76`） | 一次精修完成后刷新结果 + 保存工程 + 导出报告 | 同一 `res` 重复计算 3 次，每次约 **4p 次全谱前向**（p≈10 → 40 次），每次含 `np.vstack` 全相 profile + `solve_linear_detail`（`esd.py:128-135,150-153`）；N≈5000 点、5 相时量级数十秒，且全部在主线程槽函数内 → 界面卡顿 | 按 `res` 身份缓存 `EsdResult`，或统一移到 worker | 中 | 否 |
| **B03** | `gui/canvas.py:912-948` `_redraw` 每次 `self._reset_axes()`（`:858-874` `figure.clear()` + 重建 GridSpec/全部 axes），并每次重算 `_visible_sticks`(`:851-856`)、`_sticks_in_units`(`:950-966`)、`draw_fit`(`:103-157`) 重画全部峰棒；调用点 `:260`（相显隐）、`:557`（背景点选）、`:586,593`（轴切换）、`:519,525`、`refresh():889-894` | 点选背景锚点、2θ↔d / counts↔log↔√ 切换、勾选相显隐 | n 相 × 数百峰时单次重绘含 `ax_t.vlines` 数百条 + 全谱曲线重画，**量级几十～百 ms/次**；轴切换本可只改数据变换却整图重建 | 缓存 axes/sticks，仅更新 artist 数据 | 中 | 否 |
| **B04** | `core/profile/cif.py:283-311` `expand_symmetry` 去重为 Python 双重循环（外层遍历 `out`，内层遍历 `ded`，每次 6 次 `abs`/比较） | 导入高对称空间群（symop 数多）+ 多原子 CIF | `out = n_atom × n_symop`，可达 10³；比较次数 **10⁵～10⁶ 次 Python 级循环**，导入耗时显著（读入路径，一次性） | 向量化/空间哈希去重 | 高 | 是（去重顺序改变会影响展开结果，属数值风险） |
| **B05** | `core/refine/nonlinear.py:689-691`、`core/refine/cell.py:298`、`core/refine/solve.py:195-196`、`core/profile/forward.py:795-799` | LM 每次迭代 n+1 次残差 × 迭代数 × 配方 8 步 | 每次残差评估对所有相重算 `compute_phase_profile`（`np.zeros_like` 分配 N 长数组 + 逐峰累加），再 `np.vstack(rows)` 拷成 `(n_phase, N)`；这是全链主要计算成本。已有 `_PEAKS_CACHE`（`forward.py:586-640`）缓解峰枚举，但 profile 累加无法省 | 缓存/复用（数值核心） | 高 | 是（禁止动） |
| **B06** | `core/profile/forward.py:586-640`（`_PEAKS_CACHE_MAX=256`，`:638-640` 超限 `clear()` 全清）；`core/refine/nonlinear.py:676-684` 与 `core/refine/cell.py:281-289` 两处 `cell_cache` 无上限 | 长迭代 / 多起点重启 / 占位精修（结构对象频繁新建） | 全局缓存到 256 项**整表清空**后重建，命中率呈锯齿；`_PEAKS_CACHE` 键含 `id(struct)`（`:615`），依赖 GC 与 `_variant` 盐值防地址复用 | 改 LRU / 限定容量淘汰 | 中 | 否 |
| **B07** | `core/patterns.py:163`（`_read_text(p)`）→ `:168`（`detect_vendor_format(p)`）→ `:212`（`load_vendor_pattern(path)` 再读盘）→ `:229`（部分分支第三次 `_read_text`） | 打开 `.xy/.txt/.dat/.csv` 且落到 vendored 分支 | 同一文件**重复 IO 2～3 次**（谱图通常 MB 级，毫秒量级，非热路径） | 把已读 `text` 传给 reader，避免二次读盘 | 低 | 否 |

### 2.3 C 类 · 可维护性

| 编号 | 文件:行号 | 问题 | 影响 | 建议改法 | 风险 | 改数值 |
|---|---|---|---|---|---|---|
| **C01** | `core/refine/plan.py:1-83`（整文件） | **整块死代码**：全仓 Grep 无任何源码/测试引用；`TYPE_CHECKING` 下 `from xinrefinement.core.pipeline import PipelineOptions` / `from xinrefinement.core.solve import SolveOptions, SolveResult`（`:22-24`）两个模块**均不存在**（已 `ls` 确认）；注释全篇引用兄弟项目 `nca/core/pipeline.py`；`wavelength_for(stage1.result.params)`（`:47`）双重 `.result`；`check_cancel`（`:27-37`）与 `nonlinear._check_cancel`（`:583-601`）重复实现 | 误导维护者；mypy 会报未定义名；`from __future__ import annotations` + `TYPE_CHECKING` 使其运行时「假装可用」 | 删除或移入 `archive/` 并注明来源 | 低 | 否 |
| **C02** | `core/vendor/text_formats.py:83-91,73-80` | `FORMAT_LABELS` 17 个值全指向 `fmt.*` 键，但 **catalog 中 `fmt.*` 键数 = 0、`i18n` 未导出 `fmt_label`**（只读脚本实测）；且该表除 `__all__`(`:29`) 与定义外无引用；`_L(key)`(`:78-80`) 实际直接返回内部 key。注释 `:83-84` 却写「展示名统一经 `i18n.fmt_label` 翻译」 | 死配置 + 注释与实现不符（vendored 遗留） | 删表或补齐文案键并改注释 | 低 | 否 |
| **C03** | `xinrefinement/api.py:113`；`cli/refine.py:463` | `pat = request  # 复用 refine 的求解，避免二次读盘不一致`（赋值后从未使用，且 `_solve_raw` 确实重新读盘求解）；`res = res  # noqa: PLW0127 — 最后一步的结果`（自赋值空操作） | 死代码；注释与实现相反，易误导 | 删除两行 | 低 | 否 |
| **C04** | `core/refine/recipe.py:965-969` | `if (rec.status == "done" and ...): pass` 空块，注释写「已收敛：后续步骤仍执行但记录不再改进」，实现什么都不做 | 让人误以为存在提前终止/收敛判定逻辑 | 删除或补实现 | 低 | 否 |
| **C05** | `xinrefinement/api.py:68-99` ↔ `:118-133` | `refine()` 与 `_solve_raw()` 逐字重复求解样板（load_pattern / parse_cif / ProfileParams / RefineConfig / solve），仅差 `refine_po` | 漏改一处即产生 A04 那类入口不一致 | 抽 `_build_solve_inputs(request)` 公共函数 | 低 | 否 |
| **C06** | `cli/refine.py:322-379` ↔ `core/report.py:52-76,79-90` | 两套「精修结果 JSON」schema 并存：`to_report` 有 `input/background/history/warnings/rbragg`，`_log_dict` 有 `rwp_history/diagnostics/esd`，`parameters` 覆盖字段也不同；后者经 `solve_result_dict` 写入 `.xinr` | 同一结果三份 JSON 口径不一，下游解析需分别适配 | 统一到 `solve_result_dict` | 中 | 否 |
| **C07** | `core/refine/cell.py:70-77`、`gui/dialogs.py:210-214`、`core/symops.py:126-129`、`core/refine/recipe.py:904-910` | 对 `crystal_system_of` / `symmetry.lookup` 的异常兜底重复 4 层，层层静默降级到「按晶胞度量猜 / 按 a,c 处理 / ndof=0」 | 真正的解析错误被层层吞掉，最终静默退化且无告警 | 集中一处处理并给 warning | 中 | 是（潜在改变晶系判定→数值） |
| **C08** | `gui/main_window.py:120-134` | `from xinrefinement.gui.dialogs import ...` / `project` / `workers` / `i18n` 的 import 写在两个模块级函数定义（`:70-119`）之后，不在文件顶部 | PEP8/静态检查告警，import 位置混乱 | 上移到顶部（注意 `canvas.py:28-40` 已有同类 E402 例外，属 matplotlib 初始化必需，二者不同） | 低 | 否 |
| **C09** | `core/vendor/text_formats.py:73`、`xinrefinement/i18n/__init__.py:13`、`registration.py:134` | 三个同名 `tr()` 语义完全不同（错误格式化 / 三语翻译 / 注册文案）；`gui/canvas.py:172` 的 `manualPeaksChanged = Signal(list)` 在 `:404` emit 但 `main_window._start_worker:1423-1429` 等处均未 connect（死信号） | 静态扫描易把 `err.*`(33 键) 误判为 i18n 缺键（本报告已核实不是）；手动峰位无外部消费者 | 改名 `_err_msg`；信号接入日志或移除 | 低 | 否 |
| **C10** | `tests/test_joint_s1.py:25,29-31,34-48`；`tests/test_cif_robust.py:17,20-22,45-52`；`tests/test_xinm_import.py:243-252`；同类 `tests/test_cif_compat.py:29`、`tests/test_edge_peaks.py:25`、`tests/test_peaks_vectorized.py:28`、`tests/test_esd_geometry.py:184,188` | `COD_ROOT` 硬编码为工作目录之外的绝对路径 `D:/Project/XRD/sync-COD/COD`（两处逐字相同），模块级 `skipif` 依赖 `COD_ROOT.is_dir()`；`xm_api`/真实导出器 fixture 再依赖 `xinmatch`/`gemmi` 可导入，否则 `pytest.skip`。本机缺 `gemmi`/`pymatgen`/`CifFile` 且无该档案 → 整文件/整用例跳过 | 文档权威基线 `532 passed / 0 skipped` 只在「COD 档案 + XinMatch/gemmi 齐全」的机器上成立；本机实测 **6 skipped**，静态归因恰为 6：`test_joint_s1.py` 3 个用例经模块级 `skipif`（`:29-31`）+ `test_cif_robust.py:52` 2 个 COD 参数化用例 + `test_xinm_import.py:252` 1 个（与主理人实测吻合；本审视未重跑 pytest）。基线随环境漂移；`test_joint_s1.py:98-122` 这**第二条** golden 断言因此长期不执行（该文件 `:104-107` 自述曾致 golden 静默过期） | 把外部档案/包依赖显式化为 CI 能力标记，并在报告层分档记录「全能力基线 / 仓库自足基线」（不改被测代码）；**不引入工作目录之外的依赖、不装包、不放宽断言绕过**，也不为满足 0 skipped 去改断言 | 低（不改被测代码） | 否 |
| **C11** | `xinrefinement/core/symops.py:39-42,90-105`（`_all_types()` 内 `:95` 对 1..530 逐个调 `spglib.get_spacegroup_type`）；`pytest.ini:3` / `pyproject.toml:34` 均只配 `addopts = "-q"`，**无 `filterwarnings` 配置** | 全量回归在 `-o addopts=""` 下暴露 **775 个 spglib DeprecationWarning**（主理人实测）；警告来自 spglib 自身 API 弃用，被 `core/symops.py` 的高频调用放大 | 基线日志噪音大，掩盖新增警告；与「6 skip」同属依赖侧/基线可移植性，不是代码回归。不应把「装包消除警告」当作基线红灯的处置手段 | 在 CI/基线报告层按来源归类统计警告；如确需消除，另行评估 spglib API 迁移与版本固定（独立依赖侧任务，本轮不动） | 低 | 否 |

### 2.4 基线红灯的架构判断（补充审视 · 只读）

> 来源：主理人侧两条补充线索（本机 venv 依赖清单、全量回归基线结果）。本节只做源码级判断，**未重跑 pytest**（QA 任务 #2 独立复现诊断），不修改任何代码/测试/配置。

**实测事实（主理人侧）**

- 命令：`D:/XinRefinement/.venv/Scripts/python.exe -m pytest -o addopts="" --basetemp=<系统临时新目录> -q`
- 结果：`1 failed / 525 passed / 6 skipped / 775 warnings，481.53 s，EXIT=1`；文档权威基线 `532 passed / 0 skipped`。
- 唯一失败：`tests/test_v162_cancel.py::test_run_all_does_not_record_cancel_as_failure`，`assert records, "应至少跑完/开始过一步"`（`tests/test_v162_cancel.py:120`）得到 `[]`。

**逐层证据链（全部可 `Read` 复核）**

| 环节 | 文件:行号 | 事实 |
|---|---|---|
| 回调挂载与计时起点 | `tests/test_v162_cancel.py:114-119`、`:41-49`、`:116-117` | `t0 = time.monotonic()` 在 `:114`，**早于** `_inputs()` 内的 `load_pattern` + 2× `parse_cif`；`cancel()` 是绝对墙钟谓词 `> 0.15s`。调用为 `run_all(_inputs(cancel_cb=cancel))`，回调只进 `RefineConfig.cancel_cb`（`:46-48`），**未作为 `run_all` 的 `cancel_cb` 形参传入** |
| 双通道取消 | `core/refine/recipe.py:932`、`:941-943`、`:84-92` | 步边界检查 `:942` 用的是 `run_all` 自己的形参；`_with_cancel` 才把形参挂到 config。本测试形参为 `None` → **步边界检查被禁用**，取消只能经引擎残差检查点 |
| 引擎检查点 | `core/refine/nonlinear.py:583-601`、`:687`、`:895` | `_check_cancel` 在每次残差评估入口调 `cb()`，为真即抛 `RefineCancelled`（`:596-597`）。若首次残差评估时 `time.monotonic()-t0 > 0.15` 已成立，取消**发生在第一步第一次残差** |
| 记录追加时机 | `core/refine/recipe.py:387-395`、`:73-81` | `run_step` 的 `try: solve(inp)` 抛取消后，`:390` 先 `_reraise_if_cancelled(exc)` 重抛，**在 `:391-394` 追加 `StepRecord` 之前**；故取消不产生任何记录 —— 这正是 v1.6.2「取消不记成 failed」的设计 |
| 连跑收敛 | `core/refine/recipe.py:958-963`、`:970` | `run_all` 捕获 `RefineCancelled` 后 `break` 并 `return result, self.state.records`；第一步即取消 → `result=None`、`records=[]` |
| 产品路径对照 | `xinrefinement/gui/workers.py:83-128`；全仓 `run_all(` Grep | GUI 后台线程**自建步循环**（`:96-115`，逐 `run_step`），不调 `run_all`；`result is None` 时显式 `failed.emit("精修已停止（尚未产生结果）")`（`:126`）。`run_all(` 的生产调用仅 `tools/` 下 14 处 bench/eval 脚本，其余全在 `tests/` |

**架构判断：主要是「测试时序假设脆弱」，不是产品语义缺陷。**

1. **契约一致**：`run_all:961-963` 写明取消语义是「停在**已完成**的最后一步，把已有结果交回去」。取消早于任何一步完成时「已完成的最后一步」为空，返回 `records=[]` / `result=None` 与该契约相符。`assert records`（隐含「至少开始过一步」）是测试额外附加、源码从未承诺的前置条件。
2. **产品不变量未被破坏**：v1.6.2 要守的是「取消不能被记成 `failed`」（`recipe.py:73-81`）。空列表里没有假 failed 记录，不变量成立。凭空补一条 `started/cancelled` 记录属于**新增功能**（改变 `run_all` 返回契约，波及 `tools/` 14 处与 20+ 处测试），不是缺陷修复。
3. **产品侧已有定义行为**：GUI 对「取消早于任何结果」有明确文案（`workers.py:126`），说明这是被设计过的状态，不是漏掉的边界。
4. **同文件已有确定性范式**：`test_cancel_cb_aborts_inside_step`（`:56-58`，`calls[0]>=3`）与 `test_cell_engine_honours_cancel`（`:102-104`，`calls[0]>=4`）用**调用计数**谓词，与机器速度解耦；`tests/test_recipe.py:89-98` 的 `run_all(_inputs(), cancel_cb=cancel)` 同样用计数谓词且不断言记录非空。唯独 `:112-123` 把「绝对墙钟 `> 0.15`（`t0` 早于测试自身 IO/setup）」与「记录非空断言」绑定，在 481.53 s 全量重负载下，从 `t0` 到首次残差评估的耗时超过 150 ms 即稳定复现 `[]`。这是**基线可移植性**问题（与 C10 同源），不是引擎缺陷。
5. **顺带发现（不单列编号）**：`run_all:937-940` 重置了 `current/_phases/po_probe_report/xyz_report/time_report`，**未重置 `self.state.records`**；同一 runner 二次 `run_all` 会累加旧记录。属状态同步小瑕疵，需结合 `RecipeState` 生命周期一并评估，本轮不动。

**处置建议（严守只读边界）**：由 QA 在任务 #2 独立复现诊断并给出定性；若确认属时序脆弱，修复方向应是让取消谓词与机器速度解耦（现成范式见 `test_v162_cancel.py:56-58,102-104`）——这是**测试契约设计决策**，不属于本轮 F01–F06 的源码小修，也**不是放宽断言或装包绕过**。本审视不改代码、不改测试、不改配置。

**golden 绊线必须区分清楚（勿误判为「golden 未校验」）**：`tests/test_golden_b.py:27-29` 的 `skipif` 只检查仓库内 `tests/data/virtual_b/v50_wide.xy` 与 `tests/golden/method_b_roundtrip.json`，**不依赖 gemmi / XinMatch / COD 档案**；其 `test_golden_5050_bit_identical`（`:51-74`）直连 `refine()` 对拍 50/50 档，本机该文件**不受 6 skip 影响、按主理人侧核查为执行并通过**，golden 活体绊线有效。被环境门禁挡住的是 `tests/test_joint_s1.py:98-122` 那**第二条** golden 断言（模块级 `skipif :29-31` + `xm_api :34-48`），二者不可混为一谈。

---

## 3. 本轮建议修复（6 项）

**统一硬性条件**：① golden CLI Rwp 逐位不变（6 项均不触碰优化器、峰形、权重、配方默认值、参数打包顺序，也不触碰任何残差/前向函数）；② 风险低；③ 改动面小（每项 1～4 处、共 ≤10 行）；④ 有明确验收方式。

> **补充审视项的归属（不扩充短名单）**：新增 A15（基线唯一失败）、C10（基线可移植性 / 6 skip）、C11（775 warnings 依赖噪音）**均不进入本轮 F 短名单**。理由：A15 的处置落在测试侧、且需 QA 任务 #2 独立复现定性，属测试契约设计决策（第 2.4 节）；C10/C11 属 C 类，不符合「从 A/B 里挑」的硬性条件。F01–F06 仍为 6 项，均不改数值、**不改任何测试文件**。

| 编号 | 对应问题 | 精确改动点 | 改动量 | 风险 | 改数值 |
|---|---|---|---|---|---|
| F01 | A03 | `core/refine/cell.py:169-170` 的 `_CELL_META` 元组追加 `"name_mineral"`；`core/refine/recipe.py:655-658` 的 `for attr in (...)` 元组追加 `"name_mineral"` | 2 行 | 低 | 否 |
| F02 | A01 | `core/refine/nonlinear.py:446-456` 的 `ProfileParams(...)` 构造中，在 `X=X, Y=Y` 前后补 `size_strain=base.size_strain` | 1 行 | 低 | 否 |
| F03 | A04 | `xinrefinement/api.py:130-131` 的 `RefineConfig(refine_zero=True, refine_uvw=True, n_bg=3, ...)` 补 `refine_po=request.refine_po` | 1 行 | 低 | 否 |
| F04 | A05 | `gui/project.py:133-134` 两处 `"%.10g" % v` → `"%.17g" % v`；`gui/project.py:218` `f"{x:.10g} {y:.10g}\n"` → `.17g`；`gui/main_window.py:711` 同改 | 3 文件 / 4 处 | 低 | 否 |
| F05 | A09 + A10 | `cli/refine.py:508` 写文件前加 `out.parent.mkdir(parents=True, exist_ok=True)`；`cli/refine.py:355-358` 的 texture dict 补 `model`、`degree`、`coeffs`（`coeffs` 走 `_round_list`） | 1 文件 / 2 处 | 低 | 否 |
| F06 | A12 | `gui/main_window.py:1456` 的 `title = next((s[1] for s in STEPS ...))` 保留给日志，但 `:1459` 按钮文本改 `f"{mark} {tr(f'step.{key}')}"`（与 `retranslate():530-533` 同口径） | 1 行 | 低 | 否 |

### 逐项改法与验收

**F01 — 补齐 `name_mineral` 元数据搬运**
- 改法：`_CELL_META = ("n_asym","n_sym_ops","spacegroup","sg_number","formula","z_declared","source_path","name_mineral")`；recipe 的继承元组同步追加。
- 依据：`CifStructure.name_mineral`（`cif.py:177-180`）只被 `core/profile/naming.py::phase_label` 用于显示文案；QPA/前向/晶胞/`crystal_system_of` 均不读。实测 before=`Quartz` / after=`None`。
- 验收：新增小测试 `test_structure_with_cell_preserves_name_mineral`（构造带 `name_mineral` 的结构 → `structure_with_cell` → 断言字段与 `phase_label(...,"label")` 不变）；新增/扩展 xyz 步元数据继承断言。现有 `tests/test_cell*.py`、`tests/test_recipe*.py` 全绿。

**F02 — legacy `_unpack` 补 `size_strain`**
- 改法：在 `nonlinear.py:446-456` 的 `ProfileParams(...)` 关键字参数中补一行；`base` 为同类型 frozen dataclass，直接透传即可，不需要 `getattr` 兜底。
- 依据：硬证据 `legacy _unpack -> size_strain = None`，`registry.unpack -> {'foo': (0.1, 0.2)}`；生产 `refine()` 只用 `_unpack_reg`→`reg.unpack`（`nonlinear.py:617-620,894`），故 golden 零影响。
- 验收：新增小测试 `test_legacy_unpack_preserves_size_strain`；`tests/test_registry.py`、`tests/test_size_strain.py`、`tests/test_size_strain_phase.py` 全绿；golden 逐位不变。

**F03 — `api.report()` 与 `api.refine()` 配置对齐**
- 改法：`_solve_raw` 的 `RefineConfig` 补 `refine_po=request.refine_po`（与 `refine():82` 一致）。
- 依据：两个入口除该字段外其余参数逐字相同；默认 `refine_po=False`，因此现有 API 测试与 golden 逐位不变。
- 验收：新增小测试，用同一 `RefineRequest(refine_po=True)` 调 `api.refine()` 与 `api.report()`（可 monkeypatch `export_report` 捕获 `SolveResult`），断言两者 `rwp` 一致；或轻量断言 `_solve_raw` 产出的 `config.refine_po` 与请求一致。

**F04 — 谱图序列化保留 float64 全精度**
- 改法：4 处 `10g → 17g`。`%.17g` 保证 `float → str → float` 往返逐位相等（`repr` 等价精度）。
- 影响面：只影响**新写出**的 `.xinr` / `.xinm` 中转 `.xy`；读取侧 `float()` / `np.array(...,dtype=float)` 无需改；旧文件仍可读（只是精度仍为旧值，不破坏兼容）。
- 验收：新增 `test_xinr_pattern_roundtrip_exact`：构造非整齐小数强度数组 → `save_project(embed=True)` → `load_project()` → `load_pattern` → `np.array_equal` 断言；新增 `.xinm` 导入往返断言。golden 为 CLI 路径，不经此链路。

**F05 — CLI 报告两处小修**
- 改法 A09：`out = Path(args.out)` 后、`write_text` 前加 `out.parent.mkdir(parents=True, exist_ok=True)`（与 `core/report.py:162` 同口径）。
- 改法 A10：`to_report` 的 `"texture"` 字典补 `"model": entry.get("model")`、`"degree": entry.get("degree")`、`"coeffs": _round_list(entry.get("coeffs") or [])`；`grid` 保留（EWIMV 需要）。对无 texture 的常规报告输出不变（`or None` 仍成立）。
- 验收：新增 `test_cli_out_creates_parent_dir`（`-o tmp/sub/report.json` 断言文件生成）、`test_to_report_harmonic_texture`（构造 harmonic `ProfileParams.texture` → `to_report` → 断言 `coeffs/degree/model` 存在）。现有 CLI 测试全绿。

**F06 — 步骤按钮语言与 `retranslate()` 同口径**
- 改法：`_on_step_finished` 中按钮文本改用 `tr(f'step.{key}')`；`title`（中文）仅继续用于跑码日志 `log.step_done`，不影响界面。
- 验收：扩展现有 i18n / `retranslate` 冒烟用例：切到 `en`，触发 `step_finished` 信号后断言对应按钮文本为英文（`step.*` 在 `catalog.py:148-152,260-263` 有译文）；`--offscreen` 冒烟不弹模态框。

**统一回归验收（任务 #4）**
1. `pytest` → 以**同一机器、同一环境**的修复前实测基线为对照（本机 `1 failed / 525 passed / 6 skipped / 775 warnings`；文档权威值 `532 passed / 0 skipped` 属「全能力基线」另一档，见第 2.4 节 / C10）。判据是「**无新增失败、无新增 skip**，F01–F06 涉及的纯源码用例全绿」；既有 1 failed 由 QA 任务 #2 单独定性处置，不计入本轮修复回归。含新增小测试后为 525+N passed。
2. golden CLI Rwp **逐位等于 `3.4074156640940005`**（逐位比较，不是近似）。`test_golden_b.py` 的活体绊线不依赖 gemmi，本机仍执行，必须保持通过（第 2.4 节末段）。
3. `git status --short` 除 `docs/audit-20261111-architecture.md` 外无任何改动/新增/暂存；不通过装包或放宽断言消除基线差异。

---

## 4. 明确不建议本轮动的项

| # | 项 | 理由 |
|---|---|---|
| 1 | 任何**优化器 / 峰形 / 权重 / 配方默认值 / 参数打包顺序**改动 | 数值红线；M5 峰形 d 基、M6 每原子 B、M7 λ 已判负，M8 仅适用样 7，M4 Popa LB 已产品化。本审视**未提出**任何「改峰形基 / 改织构模型 / 换优化器 / 加背景节点」类建议 |
| 2 | A02：给 legacy `_pack/_bounds` 补 `refine_size_strain` 分支 | 会给 legacy 增加向量维度、牵动 `test_registry.py`「双轨逐位一致」的参数化设计与兼容 API 语义，需要单独设计决策；本轮只修 A01 的字段搬运（生产路径不受益也不受损） |
| 3 | B01：工具栏同步 `solve()` 改异步 | 注释（`main_window.py:1602`）明确「同步，保留脚本/测试契约」；改异步会破坏现有离屏冒烟与取消/进度语义，属重设计 |
| 4 | B02：`estimate_esd` 三处重复计算缓存化 | 需引入缓存生命周期与失效策略（按 `res` 身份 / 线程安全 / 何时失效），改动面超出「小修」；且 e.s.d. 本身是数值结果 |
| 5 | B03 / B06：画布重绘与缓存策略（LRU）优化 | 需基准与 artist 生命周期设计；`_PEAKS_CACHE` 键含 `id(struct)`，改动牵动峰枚举命中，须专门评估 |
| 6 | B04：`expand_symmetry` O(n²) 去重向量化 | 去重顺序改变会改变展开结果 → 直接影响 |F|² 与 QPA，数值风险高 |
| 7 | B05：残差热路径 `compute_phase_profile` 复用/向量化 | 数值核心，明确禁止 |
| 8 | A13：`parse_symop` 异常改抛 / C07 晶系兜底重构 | 会改变异常路径下结构展开与晶系判定 → 可能改变成功导入样本的数值；需先补 CIF 语料回归集 |
| 9 | A14 中 `optimizers.py:91-94` 收窄 `except Exception` | 虽是异常吞噬（且与文件头 `:12` 矛盾），但位于优化器选择路径，改动会改变 `backend=trf` 异常时的行为；建议单独评估，本轮避开优化器相关改动 |
| 10 | `core/refine/esd.py:130-132`（`design()` 未传 `bg_points`，与主引擎 `nonlinear.py:695` 口径不一致） | 修它会改变 `bg_mode=manual/interp` 下 e.s.d. 的数值结果，属数值侧 |
| 11 | A07：临时会话目录清理 | 需设计清理时机/并发/容量上限，属跨会话生命周期决策 |
| 12 | 配方层 7 处 `except Exception` 兜底整体重构 | v1.6.2 已接 `_reraise_if_cancelled` 透传（`recipe.py:73-81`），重构会牵动取消语义，需专门回归（不在本轮 6 项名额内） |
| 13 | C01–C11 全部可维护性清理（删死代码/统一 schema/改名/测试基线分档与 CI 能力标记/警告归类） | 类别为 C，不符合「从 A/B 里挑」的硬性条件；虽多数零风险，但涉及 CI/依赖配置变更，建议单列清理任务排期，不占本轮名额 |
| 14 | **为满足 `0 skipped` / 消除 6 skip 而装外部包（`gemmi`/`pymatgen`/`CifFile`/XinMatch）、引入工作目录之外的 COD 档案、放宽或改写断言绕过**（C10、C11） | 主理人明确禁止；这些 skip 是环境能力差异，不是代码回归。装包会改变测试覆盖面口径、`改断言绕过`会掩盖真实契约；正确做法是在报告层分档记录基线（全能力 / 仓库自足），并把外部依赖显式化为 CI 能力标记 |
| 15 | **修改 `run_all` 取消语义（补 `started/cancelled` 记录）或修改 `tests/test_v162_cancel.py:120` 断言来「修绿」唯一失败**（A15 / 第 2.4 节） | 前者是新增功能、改变 `run_all` 返回契约并波及 `tools/` 14 处 + 20+ 处测试；后者属测试契约设计决策，须先由 QA 任务 #2 独立复现定性。本轮为**只读审视**，不改代码/测试/配置，也不放宽断言。补记录还会与 v1.6.2「取消不记成 failed」的设计意图纠缠 |

---

## 5. 已核实为「已符合 / 不重复建议」的交接线索

> 以下为交接单点名的易回归点，逐条核实后**当前实现正确**，不作为缺陷列出，也不照抄成结论。

| 线索 | 核实结果 | 证据 |
|---|---|---|
| 取消通道需引擎三处残差闭包 + 配方层 7 处兜底同时接上 | **已接上**：主残差 `nonlinear.py:687`、晶胞残差 `cell.py:295`、站点残差 `site.py:333`，另 `nonlinear.py:895` 最终合成前再查一次；配方 8 处 `except Exception` 均先 `_reraise_if_cancelled`（`recipe.py:331,389,456,642,665,748,819,867`），`run_all:960` 捕获 `RefineCancelled` 停在已完成步 | `workers.py:87-93`、`recipe.py:73-92,960-963` |
| 谱图视图层操作不得进入结果表/报告/拟合 | **符合**：canvas 的轴模式/缩放/背景点选/标记条只改画布自身状态；`bgPointsChanged` 经 `main_window.py:315-321` 只写 `_settings`；结果表 `_fill_results`（`:1620-1653`）只读 `self._result`，不反向写 | `canvas.py:279-300,536-568,889-948` |
| 状态栏常驻标签必须 `addPermanentWidget` | **已用**：内部版 `main_window.py:499`、注册标签 `registration.py:307,461`；`main_window.py:487-489` 注释说明 `addWidget` 会被 `showMessage()` 临时隐藏 | — |
| `_unpack` 重建 `ProfileParams` 时新增字段必须显式搬运 | `width_basis` **已补**（`nonlinear.py:453`）；但 `size_strain` **仍漏** → 这是本轮 A01/F02（自己核实出的残留，非照抄） | `forward.py:249`、`nonlinear.py:446-456` |
| 配方层重建结构必须继承 `z_declared/n_asym/n_sym_ops/source_path` | **已覆盖**：`cell.py:_CELL_META`（`:169-170`）含 7 字段；`recipe.py:655-658` xyz 步显式继承 4 字段。`name_mineral` 是**另外**漏掉的字段 → A03 | `cell.py:165-184`、`recipe.py:652-659` |
| 内部键恒为 `CifStructure.name`，显示名只进文案 | **符合**：`item.setData(Qt.UserRole, st.name)`、`canvas._phase_sticks` 用 key、`_disp()/_disp_unique()` 只产文案 | `main_window.py:958-960,989-1017,1064-1067`、`canvas.py:230-242` |
| i18n 缺键 | **无实证**：`zh/en/ja` 各 **141 键、集合完全相等**（只读脚本实测 `missing/extra` 均为空）；GUI 字面 `tr()` 键 139 个全部可解析，动态键 `disp.{mode}`/`step.{key}`/`axis.{x,y}_{mode}`/`plot.peak_{action}` 均有对应文案；`err.*`(33) 走 vendor 自带 `_ERROR_MESSAGES`、`registration.py` 中文键走模块自带 `_TRANSLATIONS`，**均不是** i18n 缺键 | `i18n/catalog.py:18-343`、`i18n/__init__.py:13-21`、`text_formats.py:36-75`、`registration.py:98-121` |
| golden 数值红线 | 本轮未执行任何数值实验、未改任何数值函数；4 次只读脚本均为纯配置/元数据对比 | 见第 0 节 |
| **golden 活体绊线在本机是否失效** | **未失效，勿误判为「golden 未校验」**：`tests/test_golden_b.py:27-29` 的 `skipif` 只查仓库内 `v50_wide.xy` 与 golden JSON，不依赖 gemmi/XinMatch/COD；`test_golden_5050_bit_identical`（`:51-74`）直连 `refine()` 对拍 50/50 档，本机不受 6 skip 影响、按主理人侧核查为执行并通过。被环境门禁挡住的是 `test_joint_s1.py:98-122` 那**第二条** golden 断言（模块级 `skipif :29-31` + `xm_api :34-48`），两者不同 | `test_golden_b.py:1-13,27-29,51-74`、`test_joint_s1.py:25-31,34-48,98-122` |
| **6 skip / 1 failed 是否等于「golden 未校验 / 引擎回归」** | **否**：6 skip 静态归因于 COD 档案硬编码绝对路径 + 缺 XinMatch/gemmi（C10）；1 failed 是墙钟谓词时序假设（A15 / 第 2.4 节），均非引擎或数值回归。本机 golden 绊线仍有效 | 第 2.4 节、C10、C11 |

---

## 6. 第三方复核指引

1. **按行号复核**：本报告每条问题的 `文件:行号` 均可直接 `Read` 定位；A01/A02/A03 与 C02 附的只读脚本输出可用 `python -B -c` 复现（不写文件）。
2. **硬证据复现**（任选）：
   - `nonlinear._unpack(..., ProfileParams(size_strain={'foo':(0.1,0.2)}), ...)` → `.size_strain is None`；`registry.unpack` → 保留。
   - `refine_size_strain=True`：`nl._pack` 4 维 / `reg.pack` 6 维；`nl._bounds` 4 / `reg.bounds` 6。
   - `structure_with_cell` 后 `name_mineral` 丢失、`phase_label(...,"label")` 退化。
   - `TRANSLATIONS` 三语键集合相等（各 141）；`catalog` 中 `fmt.*` 键数 0、`i18n` 无 `fmt_label`。
3. **仓库零改动核对**：`git status --short` 应只显示 `?? docs/audit-20261111-architecture.md`；`git rev-parse --short HEAD` = `e6ddef3`。补充修订后仍只应多出本报告一个未跟踪文件（补充线索未触发任何其它写入）。
4. **基线红灯复核**：`1 failed / 525 passed / 6 skipped / 775 warnings，481.53 s` 引自主理人侧实测；本审视**未重跑 pytest**，QA 任务 #2 独立复现。静态归因见第 2.4 节与 C10：`test_joint_s1.py:29-31` 3 例 + `test_cif_robust.py:52` 2 例 + `test_xinm_import.py:252` 1 例 = 6 skip。失败用例可按第 2.4 节证据链逐层 `Read` 复核。
5. **golden 绊线复核**：`test_golden_b.py:27-29` 的 skipif 条件在本机为假（两文件均在仓库内），`test_golden_5050_bit_identical` 应执行并通过；不要据「6 skipped / 1 failed」误判为 golden 未校验。
6. **修复后回归**：见第 3 节统一验收（以本机修复前实测基线为对照，无新增失败/无新增 skip + golden 逐位 + 零额外改动；文档权威值 `532 passed / 0 skipped` 属「全能力基线」另一档）。
