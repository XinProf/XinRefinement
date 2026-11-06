# 变更记录

## v1.4.0（开发中）

主题：**对拍收尾——把 v1.3 已落地但没进生产配方的能力接上实样验证**。
七样同口径复测（[`docs/评估报告-实样对拍-MAUD-v1.md`](docs/评估报告-实样对拍-MAUD-v1.md)
§11.5）确认 v1.3 引擎零回归，再按「建模补全 → 全量复测」补齐三项配方能力，
并对方石英无序模型给出数据驱动的处置结论。

### 设计口径（先说清楚，避免误用）

- **CLI / 库 API 全部新能力默认关闭**（`po_probe` / `refine_biso` /
  `refine_xyz` 都是 `False`），保证 golden 与既有调用逐位零回归；
  **GUI 只把 `po_probe` 出厂默认开**，依据是 7 样对拍里三个差距样分别
  −4.82 / −12.60 / −4.45 pt。`refine_biso` / `refine_xyz` GUI 仍默认关，
  由 micro 齿轮显式勾选——这两项在实样上收益不稳定，不做静默启用
- **配方步骤「可用」≠「默认执行」**：`xyz` / `B` 两步的
  `available` 从 `False` 改为 `True`，但未显式开启时 `run_step` 仍记
  `skipped`，不做假执行

### 新增：micro 步择优取向自动试探（任务 #19）

- 根因：实样对拍里样品 3 的 CaF₂(111) 择优取向一项值 −12.06 pt，
  但引擎只有在 `prm.po_r` 里**预先填好** (h,k,l) 才会精修 `r`，
  出厂配方没有这些信息，micro 步等于空转
- `RecipeRunner._run_micro`：逐相 × 低指数候选轴
  `DEFAULT_PO_AXES = ((001),(100),(110),(111),(101))` 短精修 `r`
  （每候选只放 1 个非线性自由度），按 Rwp 增益 ≥ `po_probe_min_gain`
  （默认 0.3 pt）挑选、最多纳入 `po_probe_max_phases`（默认 2）个相，
  再把 `r=1` 写回 `po_r` 交给正式 micro 步连同 X/Y 精修
- **互斥护栏**：用户已配 `po_r`、开了 EWIMV 织构、或落在
  `DEFAULT_PO_HKL` 内置惯习面表里的相一律不试探。实测若让试探覆盖
  内置惯习面，会把更准的默认轴换成噪声轴（合成对照 5.4235 → 5.4265）
- 细节留痕 `runner.po_probe_report` 并写入 `StepRecord.message`；
  `po_probe=False` 时 `run_step` 完全不走该分支
- **窗口策略**：micro 齿轮新增 `tmin/tmax`，
  `_make_inputs` 按窗口自适应背景节点数；实测 5–120° 相对 5–90° 在
  样品 1/3/7 分别再降 0.834 / 0.812 / 0.940 pt
- CLI：`--po-probe` / `--po-probe-min-gain` / `--po-probe-max-phases` /
  `--po-probe-max-iter`

### 新增：每相 ΔB_iso（任务 #18）

- COD 导出 CIF 的 `B_iso` 恒为 0，实测样品 1 在 40–120° 的计算强度
  系统性偏高（§4.6）。`ProfileParams.b_iso = {相名: ΔB}` 与全局
  `bfactor` 共用 `exp(−B/(2d²))` 形式，逐相叠加，只压高角、不改峰位
- 落点：`forward._accumulate_peaks` / `nonlinear._pack/_unpack/_bounds`
  与 `ParameterRegistry` 的 `phase[…].B_iso` 槽（逐位对拍通过）/
  `solve._resolve_biso`（缺相补 0、`tmax<60°` 与全局 `bfactor` 同开时告警）/
  配方 `B` 步 / CLI `--refine-biso` / GUI micro 齿轮
- 上界 6 Å²；合成数据注入 ΔB=1.5 可回收到 ±10%
- **撞界护栏**（来自实样基准）：7 样里 4 样把某些相顶到 6 Å²，且撞界相
  与 PO/织构收益相高度重合（如样品 3/7 的 CaF₂）——说明 B 在吸收
  **择优取向 / 织构 / 标度的模型误差**，不是物理温度因子。`solve()` 在
  任一相撞界时追加「建议先确认 PO 与织构再启用 B 步」告警；B 步因此
  保持 opt-in，不设出厂默认

### 新增：原子坐标 xyz 步接入配方（任务 #17）

- `CifStructure.source_path`：`parse_cif` 写入 CIF 路径；xyz 步必须
  **重读未展开的不对称单位 + symop**（`parse_cif` 已展开等价位置，
  无法反推 Wyckoff 位）。`parse_cif_string` / 手工结构为 `None`，自动跳过
- `cell.structure_with_cell` 的元数据白名单补 `source_path`，
  保证 cell 步精修晶胞后 xyz 步仍找得到 CIF
- `site.refine_sites` 增 `fixed_structures`（不参与结构精修的相作为常量基
  进入变量投影，避免强度被算到被精修相的标度上）与 `bg_points` 透传
  （手动/插值背景的固定层必须一致，否则坐标被背景差吸收）
- `RecipeRunner._run_xyz`：用 cell 步精修后的晶胞覆盖 `SiteModel.cell`；
  自由坐标系数 > `xyz_max_params`（默认 40）直接判 `failed`；
  精修后重新 `solve` 比较 Rwp，**没有改善就整体回退**原结构；
  诊断写入 `runner.xyz_report`
- **元数据继承**：站点引擎由不对称单位重建结构时只回填
  `formula/spacegroup`，配方层逐项继承
  `z_declared / n_asym / n_sym_ops / source_path`，否则 QPA 静默退化、
  下一轮 xyz 步找不到 CIF
- **性能护栏 `XYZ_SITE_MAX_ITER=12`**：站点 LM 用数值雅可比，每次迭代
  需 O(n_free) 次「多相全谱 + 线性层」评估；实样 5 相体系沿用配方
  `max_iter=40` 会跑十几分钟仍不收敛。xyz 步单独封顶 12 次
  （坐标精修一般 8–12 次即到平台），主 `solve` 的迭代预算不变
- **实样复测（3 个差距样）**：样品 1 接受 14 个自由系数，
  Rwp 23.880 → **21.628%（−2.251 pt）**、最大位移 0.0266，与 §4.6
  点名的方解石 O 坐标缺口吻合；样品 3 只有 −0.118 pt（其缺口是
  CaF₂(111) 织构，不是坐标）；样品 7 有 48 个自由系数，触发
  `xyz_max_params=40` 判 failed 并整体回退，Rwp/QPA 逐位不变
- CLI `--refine-xyz` / `--xyz-max-params`；GUI micro 齿轮开关

### 修复

- `core/absorption.py`：样品 5 的 gehlenite CIF 化学式与占位不一致，
  `infer_z` 抛错导致 μ·r 不可算。新增 `_density_from_cell_mass` 回退
  （直接按晶胞占位质量算 ρ），输出 `density_source="cell_mass"` 与
  「请核对结构模型」warning；7 样全部相可算
- `tools/bench_v14.py::stage_base` 引用了未定义的 `runner`（重跑 base
  阶段才触发），改为显式构造 `RecipeRunner`
- `tests/test_biso.py` 一条过时断言仍期待 `xyz` 步 `available=False`，
  已同步为 v1.4 口径；`recipe.py` 模块 docstring 从 v1.1 的
  「xyz/B 未落地」更新为 v1.4 的 opt-in 语义
- `README-en.md` 长期停在 v1.1.0，补上当前版本与「功能描述仍为 v1.1.0
  基线、新特性见中文 CHANGELOG」的明确说明，不再假装已同步

### 测试

- 新增 `tests/test_po_probe.py`（4 项）、`tests/test_biso.py`（6 项）、
  `tests/test_xyz_recipe.py`（6 项）：配置默认关、真值轴回收、
  互斥/阈值护栏、registry 逐位对拍、合成 ΔB 回收与撞界告警、xyz 步
  skipped / 欠定 / 迭代封顶 / 元数据继承 / 不恶化承诺
- `tests/test_absorption.py` 加密度回退用例（用 `try/finally` 恢复 fixture）
- `tests/test_gui_smoke.py` / `tests/test_recipe.py` 同步
  「7 done / 1 skipped」与 `len(DEFAULT_STEPS)-1` 快照口径
- **全量回归**：368 项收集 / 364 通过 / 4 skip / 0 失败
  （v1.3.0 为 350 收集，净增 18 项）

### 实样复测结论（7 样，详见评估报告 §11.5）

- **v1.3 零回归**：base 与 v1.2 tent14 基线逐位一致，均值 18.8439%
- **PO 自动试探**：样品 1/3/7 端到端 −4.816 / −12.604 / −4.451 pt；
  样品 3 自动选中 CaF₂(111) `r≈0.448`，与全轴穷举上界差 ≤0.05 pt；
  窗口 5–120° 再降 0.81–0.94 pt
- **EWIMV / Popa LB**：织构在 1/3/7 值 −6.004 / −13.666 / −5.206 pt
  （但 19 自由参数，不设默认）；样品 5 各向异性 −0.768 pt
- **μ·r QPA**：Rwp 不变（数学简并），样品 4 hematite wt% +4.60 pt 最大；
  样品 5 gehlenite 触发 `cell_mass` 密度回退
- **组合口径**：5–120° + PO + B + xyz 一起开，样品 1 23.880 → 17.185%、
  样品 3 24.525 → 13.537%；**收益不可加**——B 先把 CaF₂ 的 ΔB 顶到
  6 Å² 吸收大半高角失配，组合里 micro 步只剩单项收益的三分之一
- **#21 无序方石英**：不引入无序模型。三多型 Rwp 26.709/26.350/25.235、
  wt% 2.72/3.52/5.27；移除该相 +1.00 pt；ΔB_iso 阻尼最多只动 0.11 pt
  且 wt% 仍漂移。降级为「仅参照相」、wt% 不报告，需 TEM/IR 或
  21.9° 单峰 Le Bail 人工判读；不新增引擎开关、不改用户数据

### 文档

- `docs/评估报告-实样对拍-MAUD-v1.md` §11.5：v1.4 全量复测记录
  （零回归基线 / 增量口径修正 / PO·EWIMV·μ·r / PO 试探与窗口 /
  ΔB_iso 与撞界 / xyz 与组合口径 / 无序方石英 / 发布口径与遗留缺口）
- 可复现脚本 `tools/bench_v14.py`、`tools/eval_cristobalite.py`
  （基准数据落临时目录，不入 Git）

## v1.3.0（已推送）

主题：MAUD 源码复核借鉴清单**全部落地**（μ·r 计算器、theoreticalWeights、
画布点选背景、EWIMV 织构、Popa LB 各向异性、优化器插拔）+ 一项重要设计
评审结论（μ·r 精修证伪，改为计算器）。测试 350 项收集 / 346 通过 / 4 skip。

### 设计评审（重要）

- **μ·r 精修证伪，降级为实验机制**：Brindley 因子是每相常数标量，与线性层
  每相自由 scale **完全简并**（乘积 S_p·f(μr_p) 才可辨识）。数值实验证实：
  单谱精修 μ·r 数学上不可辨识，LM 在零梯度平面漂移到边界（真值 2.0 →
  撞界 20.0），且 **Rwp 逐位不变而 wt% 静默漂移**——MAUD 的 Brindley 实现
  同构、同样存在该简并。`RefineConfig.refine_microabs` 机制代码保留仅供
  多谱联合/受约束标度等未来场景实验，生产路径（配方/GUI/CLI）一律不暴露

### 新增

- **μ·r 计算器 `core/absorption.py`**（替代精修的正确路径）：内嵌元素
  质量衰减系数表（`core/mu_table.py`，由 xraylib 4.3 / NIST-Chantler 评估
  生成，Z=1–94 × 6 阳极，运行时零依赖）；`calc_mu_r(CIF, 晶粒半径)` 按
  晶胞占位算元素质量分数、ρ=Z·M/(N_A·V)、μ=(μ/ρ)·ρ，输出 μ·r。
  物理对照：锐钛矿 ρ=3.890（文献 3.89）、μ/ρ=124 cm²/g（文献 124–129）。
  GUI 物相参数编辑新增「按成分计算 μ·r」（晶粒半径输入 + 计算明细弹窗）；
  CLI `--grain-size 相名=r_μm`（手工 `--microabs` 同名时优先）
- **theoreticalWeights 定权模式**（借鉴 MAUD `theoreticalWeights`）：
  `weight_mode="theoretical"`，σ=√max(ycalc,1) 用计算值代替观测值定权
  （抗弱峰噪声漂移）；solve() 入口按初始参数引导解析为固定 σ 数组
  （静态 σ 保证残差确定性），引擎/e.s.d./Rwp 口径自动一致；
  GUI 背景弹窗新增「定权模式」下拉；CLI `--weight-mode theoretical`
- **画布点选背景锚点**（借鉴 MAUD 手工背景点）：工具栏「点选背景」开关，
  主轴内左键添加/移除锚点（±0.15° 判同点，强度取实测插值）、右键清空；
  d 轴模式自动换算（存 2θ）；锚点回写 settings.bg 并自动切 manual 模式，
  经既有 `bg_points` 引擎路径下次精修生效；工程保存/恢复闭环；zh/en/ja

### EWIMV 离散 ODF 织构（任务 #14）

规格见 [`docs/规格-EWIMV织构-v1.md`](docs/规格-EWIMV织构-v1.md)（已实现）。

- **模型**：Bragg–Brentano 平板对称反射几何下散射矢量恒沿样品法向，织构
  因子退化为**每反射常数** `T(χ_hkl)`——χ 为晶面法向与织构轴夹角（0–90°，
  用倒易基矢算，非正交晶系正确）。每相 19 点网格（5° 步长）线性插值
- **正则化**：二阶差分光滑罚 `√λ·(T[k−1]−2T[k]+T[k+1])`（λ 默认 1.0，
  CLI/GUI 可调）+ **末端节点锚定 1.0**（权重 100）。锚定不只是物理论断
  （远场回归无织构），它还**消除「T 整体乘常数 ↔ 该相 scale 除常数」这条
  零空间**——没有它 T 的水平不可辨识，LM 会沿平盘漂移
- **护栏**：相内独立 χ 桶数（5° 分桶）< 3 直接 `ValueError`（欠定不给结果）；
  开织构的相忽略 March–Dollase r 并告警（同一自由度不给两套模型）
- **落点**：`ProfileParams.texture` / `compute_peaks(with_dirs=)` 的峰方向 /
  `RefineConfig.refine_texture`+`texture_lambda` / registry `texture` 组
  （19 槽/相）/ GUI 物相编辑「织构 (EWIMV)」/ CLI `--texture 相名=h,k,l`
- **实测**（合成谱，anatase (001) 方向 T=3）：无织构模型 17.91% → 开织构
  0.002%，T(0) 精确回收 3.000，末端 1.000

### Popa LB 各向异性尺寸/应变（任务 #15）

- **模型**：2 阶球谐截断 + **Cholesky 参数化**（`L` 行优先下三角 6 参）：

  `1/D² = |L_sᵀn|²`、`ε² = |L_εᵀn|²` → `Y = (180/π)·Kλ/√(1/D²)`、
  `X = (180/π)·4ε`（与标量 TCH 同单位同语义，逐位可退化验证）

  用 Cholesky 而非直接二次型系数，是因为 `|Lᵀn|` 对参数**处处可导**，
  直接二次型在 q=0 处 `sqrt` 导数发散、LM 数值差分会被放大
- **可辨识性护栏**（本任务的硬要求）：`aniso_mode` 默认 `"size"`（6 参）；
  窗口内独立晶向 < 8 直接报错；`"both"`（12 参）给出「size 与 strain 会
  互相吸收」告警。实测印证：纯尺寸合成数据 + both 模式 → Rwp 0.14% 但
  L 矩阵乱、比值 52 而非 3.3；只放 size → 参数与比值都正确
- **落点**：`ProfileParams.aniso` / registry `aniso` 槽（6 或 12/相，
  对角/非对角分别给界）/ GUI「各向异性尺寸/应变 (Popa LB)」/ CLI `--aniso`
- **实测**（合成 D_a=200 Å、D_c=60 Å）：各向同性 30.80% → 各向异性 0.06%，
  `size` 对角回收 4.999e-3 / 1.664e-2（真值 5.000e-3 / 1.667e-2），
  Dmax/Dmin 3.346（真值 3.333）

### 优化器插拔（任务 #16）

- 新增 `core/refine/optimizers.py`：`OPTIMIZERS = {lm, trf, dogbox}` +
  别名 `scipy = trf`，统一入口 `minimize()`；cost 一律 `0.5·||r||²`
  （重启比较才能直接比）；未知方法**报错并列出可用项**，不静默回退；
  scipy 缺失时自动回退自研 LM（历史行为）
- `nonlinear.refine` 与 `cell.refine_cell_full` 均改走注册表；CLI
  `--backend lm|trf|dogbox|scipy`；新增优化器只需写一个 `_run_xxx` 登记
- 三方法在同一良态问题上收敛到同一解（cost 到 1e-4 相对一致），边界投影
  一致；端到端 trf/dogbox 与 lm 的 Rwp 同盆收敛

### 修复

- **重启起点丢扩展字段**（`nonlinear._restart_points`）：此前手工重建
  `ProfileParams`，把 X/Y、microabs、texture、aniso 静默清零——重启后
  registry.pack 直接崩溃（v1.3 各向异性实测暴露）。改为 `dataclasses.replace`
  只改 U/V/W，其余字段全部保留
- **解除 `registry` ↔ `nonlinear` 模块级循环导入**：registry 改为用到时
  局部导入 nonlinear，使「谁先被 import」都不影响可导入性

### 文档

- `docs/规格-EWIMV织构-v1.md`：EWIMV 离散 ODF 织构规格 + 实现落地记录
  （纤维 1D ODF + 光滑罚 + 六条验收 A1–A6 及实测值）

## v1.2.0（未发布）

主题：实样对拍（7 个 MAUD 手工精修样品，见
[`docs/评估报告-实样对拍-MAUD-v1.md`](docs/评估报告-实样对拍-MAUD-v1.md)）
暴露的 P0 缺陷修复 + 出厂默认升级 + MAUD 源码复核借鉴前三项
（[`docs/MAUD源码复核-v1.md`](docs/MAUD源码复核-v1.md)）。

### 修复

- **配方「晶胞参数」步骤假执行**（`core/refine/recipe.py`）：`config_for`
  从不设置 `refine_cell`，注释引用的 `run_cell_step` 全仓库不存在，
  该步 status=done 但 Rwp 前后逐位相同。现由 `RecipeRunner._run_cell`
  编排「solve → `refine_cell_full`（按晶系放自由分量）→ 用新晶胞再 solve」，
  新晶胞回写后续步骤共用的相列表。实样 1：该步 36.29% → 26.57%，
  配方末值 33.74% → 25.92%
- **GUI 单次精修用峰高旧口径**（`gui/main_window.py`）：`integrated=False`
  → `True`（Rietveld 标度 S 标准口径，CLI 本就是 True）。实样 1 同配置
  差 3.65 个百分点
- **晶胞回写丢元数据**（`core/refine/cell.py`）：新增 `structure_with_cell`
  公共入口，`apply_cell_scales` 与配方回写共用；漏搬 `formula/z_declared`
  会让晶胞精修后 QPA 静默变 None
- **CLI 失败分支崩溃**（`cli/refine.py`）：`rec.note` → `rec.message`
  （`StepRecord` 无 note 字段，仅真失败时触发 AttributeError）

### 新增

- **定权模式 `weight_mode`**（借鉴 MAUD `getWeight`，P0 对拍§4.3 关联）：
  `sqrt`（默认，计数统计，与 v1.1.x 逐位一致）/ `file`（谱图自带
  σ，即 `_pd_meas_intensity_sigma`）/ `unit` / `1/y`；残差与 Rwp 同口径；
  `esd.py` 同步走该口径；CLI `--weight-mode`
- **Brindley 微吸收校正（按相）**（借鉴 MAUD `MicroAbsorptionBrindley`）：
  `ProfileParams.microabs = {相名: μ·r}`，因子 `(1−e^(−μr))/(μr)` 乘到该相
  计算强度（小 μr 走 Taylor 展开避免消元）；默认关闭逐位不变；
  GUI 物相参数编辑对话框新增「微吸收校正」组；CLI `--microabs 相名=μr`；
  v1.2.0 只施加不精修
- **插值背景 `bg_mode="interp"`**（借鉴 MAUD `backgroundSubtraction`
  默认 10 次迭代语义）：`interp_background_nodes` 自动提取锚点
  （2σ 贴背景带 + 段内中位数，合成谱回收 p50 误差 <1 counts），
  一次性提取后走 P2.2 固定背景分支；CLI `--bg-mode interp`
- **手动背景点真正接线**（P2.2 断线修复）：GUI 背景弹窗的 manual 模式
  此前被降级成 cheb、`bg_points` 从未进引擎；现经 `RefineConfig.bg_points`
  贯通 solve/`refine_cell_full`/配方全路径，结果区背景曲线正确重建
- **`adaptive_n_bg(tmin, tmax)`**：tent/interp 节点数自适应 ≈1 节点/6°

### 变更（默认值）

- **GUI 出厂背景默认 `tent` + 自适应节点数**（原 cheb + 固定 3 项）：
  实样对拍 §11.2 实测 7 样均值 23.06% → 18.84%（tent14）；
  用户在齿轮弹窗显式设置的值优先

### 实测效果（7 个实样，出厂「一键连跑」口径）

| 配置 | 7 样平均 Rwp |
|---|---|
| v1.1.1 出厂（cheb3 + 峰高口径 + cell 假执行） | 26.00% |
| v1.2.0 出厂（tent14 + integrated=True + cell 真执行） | 18.84% |
| v1.2.0 出厂 + interp14（借鉴 1a，两层可加） | 19.01% |
| MAUD 手工参考 | 11.23% |

> interp（固定插值层 + 自由 Chebyshev 层）与自由 tent 基本打平（差 0.17 点，
> 逐样互有胜负）：说明本实现已复现 MAUD 背景框架的等效能力；
> 首版「仅固定曲线、无可叠加多项式层」实测明显劣化（样品 2: 19.49% vs 7.76%），
> 两层结构是必要条件。

### 验证

- 新增 `tests/test_weight_mode.py`（5 项）、`tests/test_microabs.py`（4 项）、
  `tests/test_bg_interp.py`（5 项）；`test_recipe.py`/`test_gui_smoke.py`
  P0 回归锁 3 项；全量 `pytest` → **303 项收集，299 通过 / 4 skip / 0 失败**
  （v1.1.0 基线 286 项收集，无回归）
- 借鉴清单后续项（EWIMV ODF / Popa LB / 多优化器 / theoreticalWeights /
  画布点选背景 / μ·r 精修）已登记任务清单，排 v1.3+

### 文档

- `docs/MAUD源码复核-v1.md`：上游源码（v3.09）逐模块复核，
  6 项可借鉴能力与 4 项不建议照搬项

## v1.1.0（2026-11-05 发布）

主题：打通「物相检索（XinMatch）→ 全谱拟合精修（XinRefinement）」家族链路。
计划与格式契约见 [`docs/JOINT_PLAN_xinm_xinr.md`](docs/JOINT_PLAN_xinm_xinr.md)，
发布说明见 [`docs/RELEASE_NOTES_v1.1.0.md`](docs/RELEASE_NOTES_v1.1.0.md)，
安装包见 [Release v1.1.0](https://github.com/PolyXRD/XinRefinement/releases/tag/v1.1.0)。
配套版本：**XinMatch 3.4.0**。精修引擎、参数模型、CLI 参数与注册机制均未改动。

### 新增

- **导入 XinMatch 物相分析（`.xinm`）**：文件菜单新入口；装载谱图 + 已选物相 CIF +
  wavelength/anode 元数据；`structural=false` 的相（PDF2 类无结构条目）列为「仅参照」
  并提示手动补 CIF，不参与精修；导入内核 `core/io/xinm_import.py` 不依赖 Qt，
  GUI/CLI/库 API 共用，含 zip 炸弹防护与版本协商（version > 支持值提示升级）
- **工程文件升级 `.xinr`（自包含 zip 容器）**：默认内嵌谱图（规范 CSV，`%.10g`，
  往返相对误差 ≤ 1e-9）+ CIF + 完整精修结果（`result/refine.json`，与 CLI `--out`
  同族 schema：R 因子/参数/物相/收敛历史/diagnostics/e.s.d.），换机器/移目录后仍可
  打开精修；打开工程即回填结果摘要与收敛曲线，**无需重新精修即可复现上次结果**；
  扩展名分流——`.xinr` 走容器、`.xrp` 保持 v1.0.0 的 JSON 路径引用（**旧文件永久只读兼容**）；
  顺带修复 v1.0.0 `.xrp` 丢失 `phase_edits` 的问题
- **导入时晶胞/空间群一致性核对**：manifest 与 CIF 一致则预填 `phase_edits`（记录来源），
  显著不符（>0.1% 或 >0.05°）时以 CIF 为准并列清单提示，空间群符号做 `:1`/下划线归一化
  避免误报；`structural=true` 但包内缺 CIF 的相降级为「仅参照」并给出含文件名的原因
- **库 API**：`capabilities()` 新增 `xinm_import: "1"` 能力位

### 验证

- 新增 `tests/test_xinm_import.py`（13 项，含跨仓库 round-trip 与 S2/S3/S4 场景）、
  `tests/test_project_zip.py`（7 项，含 `result_full` 往返与缺 source 自包含打开）、
  `tests/test_joint_s1.py`（3 项，真实 COD 档案 7206075 + 9001681 全闭环）
- S1 数值保真：`.xinm` 导入后走公开 API → **Rwp 3.409617019598457（与 P0 黄金值逐位一致）**，
  定量 50.03 / 49.97 wt%；GUI 一键连跑口径下「导入路径」与「手动导入同谱图+CIF」
  Rwp 逐位相等；保存 `.xinr` 后删除临时谱图与 `.xinm` 重开，Rwp 复现（rel 1e-9）
- S2 混合来源：COD + 用户 CIF 相打包，PDF2 相仅参照且**包内无 ICDD 衍生文件**；
  S3 边界：缺 CIF / 损坏 zip / 缺谱图 / version=2 均给可读提示不崩溃
- 全量测试 259 → **286 项全绿**；i18n 三语补 `menu.import_xinm`

### 二进制与六轮验收

- 构建脚本修掉一处**假失败**：结尾 `print("⚠ …")` 在 GBK 控制台抛
  `UnicodeEncodeError`，产物已全部生成但退出码为 1（CI 会误判）。`main()` 现先
  `reconfigure(errors="replace")`。
- 六轮自动化全通过（报告 `.scratch/accept110.json`）：同源两次构建 exe **逐字节一致**
  （`a2c9fcc8…` / `7d1ed1ec…`）；两变体 CLI `--version` → `XinRefinement 1.1.0`；
  CLI 端到端 `rwp = 3.409617`；离屏 GUI 自检两变体分别报 `release/未注册` 与
  `internal/内部评估版本`；静默安装 606 文件 → 卸载 0 残留；正式版设
  `XINREFINEMENT_VARIANT=internal` 仍报 `release`（防绕过）。
- 发布件：`XinRefinement-1.1.0-setup.exe` 67,586,555 B
  （`046179e6f3ef45d6…`）、`XinRefinement-internal-1.1.0-portable.zip` 113,946,723 B
  （`a9012229b268bae3…`）。详见 `docs/RELEASE_NOTES_v1.1.0.md`。

## v1.0.0（2026-11-05 发布）

**首个正式发布版本。** 通用粉末衍射全谱拟合（Rietveld 结构精修 / Le Bail / 谱图精修）。

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
- **轴切换**：横轴 2θ ↔ d 值（Bragg 换算 d=λ/2sinθ，轴自动反向，标记条
  同步换算，波长取谱图 meta 缺省 Cu Kα1）；纵轴 counts ↔ 对数 ↔ √
  （FunctionScale）；轴标签左键循环、右键弹选单，悬停显示操作提示与手型
  光标，平移/框选激活时点击让位给工具栏
- **MAUD 式物相标记条**：主谱下方每相一条窄标记轴，左侧按相着色标注相名，
  布拉格棒高度 ∝ 相内相对强度（|F|²·LP 归一化）；残差面板高度收窄（1 → 0.55）
- **编辑 → 物相参数编辑**：按相编辑晶胞 a/b/c/α/β/γ（写回结构体，即时刷新
  标记条）、March–Dollase 择优取向 hkl+r（传导到前向模型与精修）、
  空间群/点群/劳厄群（显示与记录）；双击物相列表项直达；随 `.xrp` 持久化
- **精修菜单**：一键连跑（默认配置）/ 停止
- **帮助 → 关于**：家族版式（继承 XinMatch 版权主体 PolyXRD Team、联系方式
  与 Academic/Commercial 双许可，根目录 LICENSE / LICENSE-CN）
- **品牌资源**：logo / 窗口图标 / splash 启动画面来自项目 `assets/`
  （源码模式实时可换；打包时内置 `xinrefinement/data/assets/` 副本，
  三级回退：项目根 → PyInstaller `_MEIPASS` → 包内）
- **导航工具栏图标彩色化**：以 matplotlib 矢量源 SVG 按品牌色系重新着色
  （home 蓝 / back 橙 / forward 绿 / 平移紫 / 缩放青 / 子图红 / 编辑棕 /
  保存深蓝），同色系圆角浅底衬，QtSvg 高清渲染，失败静默回退原图标
- **功能按钮彩色图标**：新建（蓝文档+绿加号）/ 导入谱图（青·衍射峰形）/
  导入 CIF（紫·六边形晶格）/ ▶精修（绿·播放三角）/ 报告导出（橙·导出箭头），
  QPainter 程序化绘制（零素材依赖），16–48px 多尺寸高 DPI 清晰
- 齿轮弹窗：背景、晶胞（多物相分别勾选）、峰形、原子、温度因子、PO、微结构
- 结果区三页：摘要（R 因子/含量/DW/e.s.d.）、收敛曲线、相关性矩阵
- 三语 i18n（zh/en/ja，切换无需重启）、工程文件 `.xrp` 保存/恢复
- 报告导出：HTML + PNG + JSON 精修日志

### 命令行与 API

- `XinRefinementCLI refine <pattern> <cif...>`：`--recipe`（配方分步）、`--report`（HTML/PNG/JSON 目录）、`--quant`（WPF 定量）、`--esd`（Schur e.s.d.）、`--version`
- 公开库 API：`xinrefinement/api.py`（`RefineRequest`/`RefineResponse`、`refine`/`quant`/`report`/`capabilities`、`API_VERSION`）

### 双变体与注册（参照 XinMatch）

- **正式版（release）**：Inno Setup 安装包；接入 PolyXRD-Reg 离线注册机制
  （`xinrefinement/registration.py` 与 XinMatch 逐字同源、密钥一致，注册码互通），
  启动弹未注册版权提示，帮助菜单「输入注册码…」，状态栏右端「已注册：单位名 / 未注册」
- **内部评估版（internal）**：免安装便携 zip，不接注册；状态栏右端红字「内部评估版本」
- 变体由随包 `variant.txt` 固化（缺失按正式版处理，fail-safe）；冻结产物忽略环境变量，
  防止用 `XINREFINEMENT_VARIANT` 绕过注册提示
- 注册状态文件 `%APPDATA%\PolyXRD\Registration\XinRefinement.json`；
  开发方出码 `tools/make_reg_code.py "单位名"`
- 验收辅助：`XINREFINEMENT_SELFTEST_REG_OUT=<json>` 启动即导出变体/注册状态后退出

### 验收

- 测试 **259 项全绿**；`bench_b` 家族 golden round-trip **8/8 PASS**（Rwp 3.41–4.04%，与移植前逐位一致）
- 虚拟样全基准 **18/18 PASS**（5 晶系 × 1–3 相 × 注入旋钮）
- 真实锚点：NCM811 实样收敛（Rwp 11.25% 登记）；**GSAS-II 5.8.2 交叉验证晶胞最大相对差 0.031%（实样）/ 0.015%（双相）**
- 发布物：`XinRefinement-1.0.0-setup.exe`（Windows x64 安装包，zh/en/ja，含 PolyXRD-Reg 注册）；
  内部评估版 `XinRefinement-internal-1.0.0-portable.zip` 仅内部使用，不随 Release 分发
- **可复现构建**：构建脚本固定 `SOURCE_DATE_EPOCH`（= git HEAD 提交时间）与 `PYTHONHASHSEED=0`，
  消除 PyInstaller 的 PE 头时间戳与字符串集合哈希随机化两处非确定性——同一 commit 连续两次构建
  四个 exe 逐字节一致（安装包/zip 因内嵌时间戳仍会变，只做功能验收）

### 已知限制

- TCH 尺寸应变的 X/Y 若精修后停在 0（分支切换点），其 e.s.d. 记为空值（导数无定义）
- 占位精修需锚定位点（单相全位点绝对占位被 scale 吸收，物理不可辨识）
- 多相 QPA 的 GSAS-II 交叉验证、FullProf/MAUD/Profex 对比为人工步骤
